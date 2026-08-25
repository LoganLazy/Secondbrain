"""入库流水线: 解析->切块->向量化->写Chroma->AI生成标题/分类/标签/摘要"""
import hashlib
import os
import json
from pathlib import Path

import chromadb

from . import bm25, config, db, parser, providers

_client = chromadb.PersistentClient(path=str(config.DATA_DIR / "chroma"))
_col = _client.get_or_create_collection("knowledge", metadata={"hnsw:space": "cosine"})


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def call_chat(messages: list[dict], temperature: float = 0.3,
              max_tokens: int = 2000) -> str:
    import httpx

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
        if content:
            return content
        # 正文为空但思考有内容 => token被思考耗尽, 加大预算重试
        if data["choices"][0].get("finish_reason") == "length":
            continue
        # 模型明确拒答等场景, 直接返回原样
        return "(AI未能给出有效回答，请换个问法试试)"
    return "(回答超时或被截断，请重试)"


ANALYZE_PROMPT = (
    "你是个人知识库管理员。根据下面的文档内容, 只返回一个JSON对象(不要多余文字), 字段:\n"
    '{"title":"简洁标题","category":"顶级分类(如 技术/学习/工作/生活)","tags":["标签","最多5个"],'
    '"summary":"50字以内摘要"}'
)


def call_chat_stream(messages: list[dict], temperature: float = 0.4,
                     max_tokens: int = 3000):
    """SSE流式对话生成器, 逐段yield文本"""
    import httpx

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
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                j = json.loads(payload)
            except Exception:
                continue
            delta = j["choices"][0].get("delta", {})
            piece = delta.get("content") or ""
            if piece:
                got_any = True
                yield piece
        # 推理模型思考耗尽预算时流里可能一个字都没有
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


def ingest(path: Path, display_name: str | None = None,
           keep_path: Path | None = None, kb_id: str = "default") -> dict:
    fh = file_hash(path)
    exist = db.get().execute(
        "SELECT * FROM docs WHERE file_hash=? AND kb_id=?", (fh, kb_id)
    ).fetchone()
    if exist:
        raise ValueError(f"该库中已有此文档: {exist['title'] or exist['filename']}")

    pages = parser.parse(path)
    chunks = parser.chunk_text(pages)
    if not chunks:
        raise ValueError("没有解析出有效内容")

    texts = [c["text"] for c in chunks]
    vectors = providers.embed(texts)

    ids = [f"{fh}_{i}" for i in range(len(chunks))]
    metadatas = [
        {"file_hash": fh, "page": c["page"], "chunk_index": i, "kb_id": kb_id}
        for i, c in enumerate(chunks)
    ]
    _col.add(ids=ids, documents=texts, embeddings=vectors, metadatas=metadatas)
    for cid, text, meta in zip(ids, texts, metadatas):
        bm25.INDEX.add(cid, text, meta)

    full_head = "\n".join(texts[:8])
    info = analyze(full_head)
    info = {
        "title": info["title"] or (display_name or path.stem),
        **{k: v for k, v in info.items() if k != "title"},
    }

    stored = str(keep_path) if keep_path else ""
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
        "SELECT id,filename,title,file_path FROM docs WHERE id=?", (doc_id,)
    ).fetchone()
    if not row:
        raise ValueError("文档不存在")
    return row


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


def delete_doc(doc_id: int):
    row = db.get().execute("SELECT file_hash FROM docs WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise ValueError("文档不存在")
    _col.delete(where={"file_hash": row["file_hash"]})
    db.get().execute("DELETE FROM docs WHERE id=?", (doc_id,))
    db.get().commit()


def delete_doc(doc_id: int):
    row = db.get().execute("SELECT file_hash FROM docs WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise ValueError("文档不存在")
    ids = _col.get(where={"file_hash": row["file_hash"]})["ids"]
    for cid in ids:
        bm25.INDEX.remove(cid)
    _col.delete(where={"file_hash": row["file_hash"]})
    db.get().execute("DELETE FROM docs WHERE id=?", (doc_id,))
    db.get().commit()


def _ensure_bm25():
    """启动后首次检索时, 从Chroma重建关键词索引"""
    if bm25.INDEX.docs or _col.count() == 0:
        return
    res = _col.get(include=["documents", "metadatas"])
    for cid, text, meta in zip(res["ids"], res["documents"], res["metadatas"]):
        bm25.INDEX.add(cid, text, meta)


def search(query: str, k: int | None = None, kb_id: str = "default") -> list[dict]:
    """混合检索: 向量语义 + BM25关键词, 加权融合"""
    import os

    k = k or config.get("TOP_K")
    fetch = max(k * 3, 12)
    where = {"kb_id": kb_id}

    # --- 向量路 ---
    vec_results = {}
    if _col.count() > 0:
        vec = providers.embed([query])[0]
        res = _col.query(query_embeddings=[vec], n_results=min(fetch, _col.count()),
                         where=where or None)
        docs_table = db.get()
        v_scores = []
        for i, meta in enumerate(res["metadatas"][0]):
            fh = meta["file_hash"]
            r = docs_table.execute(
                "SELECT id,title,filename FROM docs WHERE file_hash=?", (fh,)
            ).fetchone()
            if not r:
                continue
            cid = res["ids"][0][i]
            sim = 1 - res["distances"][0][i]
            vec_results[cid] = {
                "doc_id": r["id"], "title": r["title"] or r["filename"],
                "filename": r["filename"], "page": meta["page"],
                "text": res["documents"][0][i], "v": sim,
            }
            v_scores.append(sim)
    # 归一化向量分
    if vec_results:
        vmax = max(x["v"] for x in vec_results.values()) or 1.0
        for x in vec_results.values():
            x["vn"] = x["v"] / vmax

    # --- 关键词路(BM25) ---
    _ensure_bm25()
    kw_results = {}
    for cid, s, meta in bm25.INDEX.search(query, top_k=fetch):
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
                "SELECT id,title,filename FROM docs WHERE file_hash=?",
                (m.get("file_hash"),),
            ).fetchone()
            if not r:
                continue
            doc_text = _col.get(ids=[cid])["documents"][0]
            fused[cid] = {
                "doc_id": r["id"], "title": r["title"] or r["filename"],
                "filename": r["filename"], "page": m.get("page", 1),
                "text": doc_text, "v": 0.0, "vn": 0.0,
                "kw": x["kn"],
            }

    out = list(fused.values())
    for x in out:
        x["score"] = round(0.65 * x["vn"] + 0.35 * x["kw"], 4)

    # --- 可选Rerank精排 ---
    rerank_base = os.environ.get("RERANK_BASE_URL")
    if rerank_base and len(out) > 1:
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
