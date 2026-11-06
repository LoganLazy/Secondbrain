"""入库流水线: 解析->切块->向量化->写Chroma->AI生成标题/分类/标签/摘要"""
import hashlib
import os
import json
import threading
import time
from pathlib import Path

import chromadb
import httpx

from . import bm25, config, db, parser, providers
from .vector_compat import dimensions_compatible, mismatch_message
from .lifecycle import serialized

_client = chromadb.PersistentClient(path=str(config.DATA_DIR / "chroma"))
_col = _client.get_or_create_collection("knowledge", metadata={"hnsw:space": "cosine"})
_vector_warning = ""
_last_query_dimension: int | None = None
_rebuild_lock = threading.Lock()


def collection_dimension() -> int | None:
    """Return the persisted collection dimension without calling any provider."""
    if _col.count() == 0:
        return None
    sample = _col.get(limit=1, include=["embeddings"])
    embeddings = sample.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        return None
    return len(embeddings[0])


def vector_health() -> dict:
    stored = collection_dimension()
    current = _last_query_dimension
    return {
        "stored_dimension": stored,
        "current_dimension": current,
        "compatible": dimensions_compatible(stored, current),
        "warning": _vector_warning,
        "rebuilding": _rebuild_lock.locked(),
    }


def _check_vectors(vectors: list[list[float]]) -> None:
    """Reject incompatible writes before Chroma emits an opaque exception."""
    global _last_query_dimension, _vector_warning
    current = len(vectors[0]) if vectors else None
    _last_query_dimension = current
    stored = collection_dimension()
    if not dimensions_compatible(stored, current):
        _vector_warning = mismatch_message(stored, current)
        raise ValueError(_vector_warning)
    _vector_warning = ""


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def chunk_id(kb_id: str, file_hash_value: str, index: int) -> str:
    """IDs are collection-global, so namespace them by knowledge base."""
    return f"{kb_id}_{file_hash_value}_{index}"


def _doc_where(file_hash_value: str, kb_id: str) -> dict:
    return {"$and": [{"file_hash": file_hash_value}, {"kb_id": kb_id}]}


def call_chat(messages: list[dict], temperature: float = 0.3,
              max_tokens: int = 2000) -> str:
    import httpx

    if config.get("NET_MODE") == "offline":
        raise ValueError("当前为离线模式，AI对话不可用")

    # 推理模型会先消耗token思考, 预算不足会导致正文为空
    for budget in (max_tokens, max_tokens * 3, max_tokens * 5):
        r = httpx.post(
            config.get("CHAT_BASE_URL").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {config.get('DEEPSEEK_KEY')}"},
            json={"model": config.get("CHAT_MODEL"), "messages": messages,
                  "temperature": temperature, "max_tokens": budget},
            timeout=180,
        )
        r.raise_for_status()
        data = r.json()
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        if content and data["choices"][0].get("finish_reason") == "length":
            raise ValueError("AI回答被截断")
        if content:
            return content
        # 正文为空但思考有内容 => token被思考耗尽, 加大预算重试
        if data["choices"][0].get("finish_reason") == "length":
            continue
        # 模型明确拒答等场景, 直接返回原样
        raise ValueError("AI未能给出有效回答")
    raise ValueError("回答超时或被截断")


ANALYZE_PROMPT = (
    "你是个人知识库管理员。根据下面的文档内容, 只返回一个JSON对象(不要多余文字), 字段:\n"
    '{"title":"简洁标题","category":"顶级分类(如 技术/学习/工作/生活)","tags":["标签","最多5个"],'
    '"summary":"50字以内摘要"}'
)


def call_chat_stream(messages: list[dict], temperature: float = 0.4,
                     max_tokens: int = 3000):
    """SSE流式对话生成器, 逐段yield文本"""
    import httpx

    if config.get("NET_MODE") == "offline":
        raise ValueError("当前为离线模式，AI对话不可用")
    budget = max_tokens
    with httpx.stream(
        "POST",
        config.get("CHAT_BASE_URL").rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {config.get('DEEPSEEK_KEY')}"},
        json={"model": config.get("CHAT_MODEL"), "messages": messages,
              "temperature": temperature, "max_tokens": budget, "stream": True},
        timeout=300,
    ) as r:
        r.raise_for_status()
        got_any = False
        completed = False
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                completed = True
                break
            try:
                j = json.loads(payload)
            except Exception:
                continue
            choices = j.get("choices", [])
            if not choices:
                if j.get("error"):
                    raise ValueError("AI服务返回错误")
                continue  # 部分兼容服务会单独发送 usage
            finish = choices[0].get("finish_reason")
            if finish in ("length", "content_filter"):
                raise ValueError("AI回答被截断或过滤")
            if finish == "stop":
                completed = True
            delta = choices[0].get("delta", {})
            piece = delta.get("content") or ""
            if piece:
                got_any = True
                yield piece
        if not completed:
            raise ValueError("AI连接在完成前中断")
        # 完成但没有正文时尝试非流式回答
        if not got_any:
            yield call_chat(messages, temperature, max_tokens * 3)


def analyze(text_sample: str) -> dict:
    sample = text_sample[:3000]
    try:
        raw = call_chat(
            [{"role": "system", "content": ANALYZE_PROMPT},
             {"role": "user", "content": sample}],
            temperature=0.2,
        )
        s = raw[raw.find("{"): raw.rfind("}") + 1]
        info = json.loads(s)
    except Exception:
        info = {}
    return {
        "title": info.get("title") or "",
        "category": info.get("category") or "未分类",
        "tags": info.get("tags") or [],
        "summary": info.get("summary") or "",
    }


@serialized
def ingest(path: Path, display_name: str | None = None,
           keep_path: Path | None = None, kb_id: str = "default", progress=None) -> dict:
    from .restore import pending_path
    if pending_path().exists():
        raise ValueError('已有等待重启的恢复任务，请先重启服务')
    progress = progress or (lambda stage: None)
    progress('checking')
    fh = file_hash(path)
    exist = db.get().execute(
        "SELECT * FROM docs WHERE file_hash=? AND kb_id=?", (fh, kb_id)
    ).fetchone()
    if exist:
        raise ValueError(f"该库中已有此文档: {exist['title'] or exist['filename']}")

    # 版本更新: 同名文件内容变了 => 替换旧版本(保留文档ID)
    old_row = db.get().execute(
        "SELECT id, file_hash FROM docs WHERE filename=? AND kb_id=?",
        (display_name or path.name, kb_id),
    ).fetchone()
    progress('parsing')
    pages = parser.parse(path)
    chunks = parser.chunk_text(pages)
    if not chunks:
        raise ValueError("没有解析出有效内容")

    texts = [c["text"] for c in chunks]
    progress('embedding')
    vectors = providers.embed(texts)
    _check_vectors(vectors)

    ids = [chunk_id(kb_id, fh, i) for i in range(len(chunks))]
    metadatas = [
        {"file_hash": fh, "page": c["page"], "chunk_index": i, "kb_id": kb_id}
        for i, c in enumerate(chunks)
    ]
    progress('summarizing')
    full_head = "\n".join(texts[:8])
    info = analyze(full_head)
    info = {
        "title": info["title"] or (display_name or path.stem),
        **{k: v for k, v in info.items() if k != "title"},
    }

    stored = str(keep_path) if keep_path else ""
    progress('saving')
    # 新版本准备好后才开始写索引；解析/向量化失败不动旧资料。
    try:
        _col.upsert(ids=ids, documents=texts, embeddings=vectors, metadatas=metadatas)
        bm25.INDEX.add_batch(list(zip(ids, texts, metadatas)))
    except Exception:
        _col.delete(ids=ids)
        for cid in ids:
            bm25.INDEX.remove(cid)
        raise
    if old_row:
        db.get().execute(
            "UPDATE docs SET title=?, category=?, tags=?, summary=?, chunks=?, "
            "file_hash=?, file_path=? WHERE id=?",
            (info["title"], info["category"],
             json.dumps(info["tags"], ensure_ascii=False),
             info["summary"], len(chunks), fh, stored, old_row["id"]),
        )
        db.get().commit()
        old_res = _col.get(where=_doc_where(old_row["file_hash"], kb_id))
        if old_res['ids']:
            _col.delete(ids=old_res['ids'])
            for cid in old_res['ids']:
                bm25.INDEX.remove(cid)
        return {"id": old_row["id"], **info, "chunks": len(chunks),
                "filename": display_name or path.name, "updated": True}

    cur = db.get().execute(
        "INSERT INTO docs(filename,title,category,tags,summary,chunks,file_hash,"
        "created,file_path,kb_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (display_name or path.name, info["title"], info["category"],
         json.dumps(info["tags"], ensure_ascii=False),
         info["summary"], len(chunks), fh, db.now(), stored, kb_id),
    )
    db.get().commit()
    return {"id": cur.lastrowid, **info, "chunks": len(chunks),
            "filename": display_name or path.name}


def get_doc(doc_id: int):
    row = db.get().execute(
        "SELECT id,filename,title,file_path,file_hash,source_url,kb_id FROM docs WHERE id=?", (doc_id,)
    ).fetchone()
    if not row:
        raise ValueError("文档不存在")
    from .backup import locate_original
    located = locate_original(row['file_path'], row['file_hash'])
    return {**dict(row), 'file_path': str(located) if located else row['file_path']}


def doc_pages(doc_id: int) -> list[dict]:
    """读取原文并返回按页文本(阅读器用); 自动剔除跨页重复的水印行"""
    row = get_doc(doc_id)
    fp = row["file_path"]
    if not fp or not Path(fp).exists():
        raise ValueError("原文文件已丢失，请重新上传")
    pages = parser.parse(Path(fp))

    if len(pages) >= 4:  # 页数太少不做统计过滤
        import re
        from collections import Counter

        norm = lambda s: re.sub(r"\s+", "", s)[:60]
        lines = [norm(ln) for t, _ in pages for ln in t.split("\n") if ln.strip()]
        counter = Counter(lines)
        threshold = max(4, int(len(pages) * 0.35))
        noisy = {ln for ln, c in counter.items() if c >= threshold}
        if noisy:
            cleaned = []
            for t, p in pages:
                kept = [ln for ln in t.split("\n")
                        if not (ln.strip() and norm(ln) in noisy)]
                cleaned.append(("\n".join(kept).strip(), p))
            pages = cleaned

    return [{"page": p, "text": t} for t, p in pages]


@serialized
def delete_doc(doc_id: int):
    row = db.get().execute(
        "SELECT file_hash,kb_id,file_path FROM docs WHERE id=?", (doc_id,)
    ).fetchone()
    if not row:
        raise ValueError("文档不存在")
    where = _doc_where(row["file_hash"], row["kb_id"] or "default")
    ids = _col.get(where=where)["ids"]
    for cid in ids:
        bm25.INDEX.remove(cid)
    _col.delete(where=where)
    db.get().execute("DELETE FROM docs WHERE id=?", (doc_id,))
    db.get().commit()
    _delete_original(row["file_path"])


def _delete_original(file_path):
    """删除文档原文: 仅当文件位于 uploads/ 或收件夹内, 且无其他文档引用它。

    路径不在这两个根目录内的不删(防止数据库里的异常路径删到外面去)。
    """
    if not file_path:
        return
    try:
        target = Path(file_path).resolve()
    except (OSError, RuntimeError):
        return
    roots = [config.UPLOAD_DIR.resolve(), config.INBOX_DIR.resolve()]
    if target in roots or not any(target.is_relative_to(root) for root in roots):
        return
    if db.get().execute(
            "SELECT 1 FROM docs WHERE file_path=? LIMIT 1", (file_path,)).fetchone():
        return
    try:
        target.unlink()
    except OSError:
        pass


def _ensure_bm25():
    """启动后首次检索时, 从Chroma重建关键词索引"""
    if bm25.INDEX.docs or _col.count() == 0:
        return
    res = _col.get(include=["documents", "metadatas"])
    for cid, text, meta in zip(res["ids"], res["documents"], res["metadatas"]):
        bm25.INDEX.add(cid, text, meta)


_search_times: list[dict] = []


def get_search_latency() -> dict:
    """最近检索平均耗时(ms): total=全程, local=纯本地索引部分"""
    if not _search_times:
        return None
    n = len(_search_times)
    return {
        "total": round(sum(x["total"] for x in _search_times) / n, 1),
        "local": round(sum(x["local"] for x in _search_times) / n, 1),
    }


def search(query: str, k: int | None = None, kb_id: str = "default",
           diagnostics: dict | None = None, mode: str = 'hybrid') -> list[dict]:
    """混合检索: 向量语义 + BM25关键词, 加权融合"""
    import os
    import time as _time

    if mode not in ('hybrid', 'keyword'):
        raise ValueError('检索模式无效')
    t0 = _time.perf_counter()
    marker = {"embed_done": False, 'mode': mode}
    try:
        result = _search_impl(query, k, kb_id, marker, mode)
        if diagnostics is not None:
            diagnostics.update({"warning": marker.get("warning", ""), 'mode': marker['mode']})
        return result
    finally:
        total = (_time.perf_counter() - t0) * 1000
        local = (_time.perf_counter() - (marker.get("t_embed_done") or t0)) * 1000
        _search_times.append({"total": total, "local": local})
        if len(_search_times) > 20:
            _search_times.pop(0)


def _search_impl(query: str, k: int | None = None,
                 kb_id: str = "default", marker: dict | None = None,
                 mode: str = 'hybrid') -> list[dict]:
    k = k or config.get("TOP_K")
    fetch = max(k * 3, 12)
    where = {"kb_id": kb_id}

    # --- 向量路 ---
    vec_results = {}
    if mode == 'hybrid' and _col.count() > 0:
        global _last_query_dimension, _vector_warning
        try:
            vec = providers.embed([query])[0]
            _last_query_dimension = len(vec)
            stored = collection_dimension()
            if not dimensions_compatible(stored, len(vec)):
                raise ValueError(mismatch_message(stored, len(vec)))
            res = _col.query(query_embeddings=[vec], n_results=min(fetch, _col.count()),
                             where=where)
            _vector_warning = ""
            docs_table = db.get()
            v_scores = []
            for i, meta in enumerate(res["metadatas"][0]):
                if meta.get("kb_id", "default") != kb_id:
                    continue
                fh = meta["file_hash"]
                r = docs_table.execute(
                    "SELECT id,title,filename FROM docs WHERE file_hash=? AND kb_id=?",
                    (fh, meta.get("kb_id", "default")),
                ).fetchone()
                if not r:
                    continue
                cid = res["ids"][0][i]
                sim = max(0.0, 1 - res["distances"][0][i])
                vec_results[cid] = {
                    "doc_id": r["id"], "title": r["title"] or r["filename"],
                    "filename": r["filename"], "page": meta["page"],
                    "text": res["documents"][0][i], "v": sim, 'revision': fh,
                }
                v_scores.append(sim)
        except Exception:
            vec_results.clear()
            _vector_warning = "语义检索暂不可用（连接或向量维度异常），已降级为关键词检索；可检查模型配置及索引。"
            if marker is not None:
                marker["warning"] = _vector_warning
                marker['mode'] = 'keyword_fallback'
    # 归一化向量分
    if vec_results:
        vmax = max(x["v"] for x in vec_results.values()) or 1.0
        for x in vec_results.values():
            x["vn"] = x["v"] / vmax

    if marker is not None:
        import time as _time
        marker["t_embed_done"] = _time.perf_counter()

    # --- 关键词路(BM25) ---
    _ensure_bm25()
    kw_results = {}
    for cid, s, meta in bm25.INDEX.search(query, top_k=fetch, kb_id=kb_id):
        if meta.get("kb_id", "default") != kb_id:
            continue
        kw_results[cid] = {"score": s, "meta": meta}
    if kw_results:
        kmax = max(x["score"] for x in kw_results.values()) or 1.0
        for x in kw_results.values():
            x["kn"] = x["score"] / kmax

    # --- 融合 ---
    fused: dict[str, dict] = {}
    for cid, x in vec_results.items():
        fused[cid] = {**x, "kw": kw_results.get(cid, {}).get("kn", 0.0)}
    for cid, x in kw_results.items():
        if cid not in fused:
            m = x["meta"]
            r = db.get().execute(
                "SELECT id,title,filename FROM docs WHERE file_hash=? AND kb_id=?",
                (m.get("file_hash"), m.get("kb_id", "default")),
            ).fetchone()
            if not r:
                continue
            documents = _col.get(ids=[cid])["documents"]
            if not documents:
                continue  # 旧关键词条目或并发删除不能中断整个检索
            doc_text = documents[0]
            fused[cid] = {
                "doc_id": r["id"], "title": r["title"] or r["filename"],
                "filename": r["filename"], "page": m.get("page", 1),
                "text": doc_text, "v": 0.0, "vn": 0.0, 'revision': m.get('file_hash', ''),
                "kw": x["kn"],
            }

    out = list(fused.values())
    for x in out:
        x["score"] = round(0.65 * x["vn"] + 0.35 * x["kw"], 4)

    # --- 可选Rerank精排 ---
    rerank_base = os.environ.get("RERANK_BASE_URL")
    if mode == 'hybrid' and rerank_base and len(out) > 1:
        try:
            pairs = [x["text"][:1500] for x in out]
            rr = httpx.post(
                rerank_base.rstrip("/") + "/rerank",
                headers={"Authorization":
                         f"Bearer {os.environ.get('RERANK_KEY') or config.get('ZHIPU_KEY')}"},
                json={"model": os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
                      "query": query, "documents": pairs},
                timeout=30,
            )
            rr.raise_for_status()
            order = rr.json()["results"]
            ranked = []
            for item in sorted(order, key=lambda i: -i["relevance_score"])[:k]:
                cand = out[item["index"]]
                cand["score"] = round(item["relevance_score"], 4)
                ranked.append(cand)
            return ranked
        except Exception:
            pass  # 精排失败退回融合排序

    out.sort(key=lambda x: -x["score"])
    return out[:k]


@serialized
def rebuild_vector_index() -> dict:
    """Rebuild all vectors in a temporary collection, then atomically switch.

    Document metadata and source files remain untouched. A provider/parser
    failure deletes only the temporary collection and preserves the old index.
    """
    global _col, _vector_warning, _last_query_dimension
    if not _rebuild_lock.acquire(blocking=False):
        raise ValueError("向量索引正在重建，请稍后再试")
    temp_name = f"knowledge_rebuild_{int(time.time())}"
    temp = None
    items_for_bm25: list[tuple[str, str, dict]] = []
    skipped: list[str] = []
    try:
        temp = _client.get_or_create_collection(
            temp_name, metadata={"hnsw:space": "cosine"}
        )
        rows = db.get().execute(
            "SELECT id,filename,file_hash,file_path,kb_id FROM docs ORDER BY id"
        ).fetchall()
        chunk_total = 0
        for row in rows:
            path = Path(row["file_path"] or "")
            if not row["file_path"] or not path.exists():
                skipped.append(row["filename"])
                continue
            chunks = parser.chunk_text(parser.parse(path))
            if not chunks:
                skipped.append(row["filename"])
                continue
            texts = [c["text"] for c in chunks]
            vectors = providers.embed(texts)
            kb_id = row["kb_id"] or "default"
            ids = [chunk_id(kb_id, row["file_hash"], i) for i in range(len(chunks))]
            metas = [
                {"file_hash": row["file_hash"], "page": c["page"],
                 "chunk_index": i, "kb_id": kb_id}
                for i, c in enumerate(chunks)
            ]
            temp.add(ids=ids, documents=texts, embeddings=vectors, metadatas=metas)
            items_for_bm25.extend(zip(ids, texts, metas))
            chunk_total += len(chunks)
            db.get().execute("UPDATE docs SET chunks=? WHERE id=?",
                             (len(chunks), row["id"]))

        # Chroma collection dimensions persist even after deleting all rows,
        # so replace the collection rather than clearing it.
        backup_name = f"knowledge_backup_{int(time.time())}"
        old = _col
        old.modify(name=backup_name)
        try:
            temp.modify(name="knowledge")
        except Exception:
            old.modify(name="knowledge")
            raise
        _col = temp
        _client.delete_collection(backup_name)
        bm25.INDEX.clear()
        bm25.INDEX.add_batch(items_for_bm25)
        db.get().commit()
        _last_query_dimension = collection_dimension()
        _vector_warning = ""
        return {"docs": len(rows) - len(skipped), "chunks": chunk_total,
                "skipped": skipped, "dimension": _last_query_dimension}
    except Exception:
        if temp is not None:
            try:
                # After a successful rename the temporary name no longer exists.
                _client.delete_collection(temp_name)
            except Exception:
                pass
        raise
    finally:
        _rebuild_lock.release()
