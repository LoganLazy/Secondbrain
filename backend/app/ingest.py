"""入库流水线: 解析->切块->向量化->写Chroma->AI生成标题/分类/标签/摘要"""
import hashlib
import json
from pathlib import Path

import chromadb

from . import config, db, parser, providers

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
            config.CHAT_BASE_URL.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {config.CHAT_KEY}"},
            json={"model": config.CHAT_MODEL, "messages": messages,
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


def ingest(path: Path, display_name: str | None = None, keep_path: Path | None = None) -> dict:
    fh = file_hash(path)
    exist = db.get().execute("SELECT * FROM docs WHERE file_hash=?", (fh,)).fetchone()
    if exist:
        raise ValueError(f"文档已存在: {exist['title'] or exist['filename']}")

    pages = parser.parse(path)
    chunks = parser.chunk_text(pages)
    if not chunks:
        raise ValueError("没有解析出有效内容")

    texts = [c["text"] for c in chunks]
    vectors = providers.embed(texts)

    ids = [f"{fh}_{i}" for i in range(len(chunks))]
    metadatas = [
        {"file_hash": fh, "page": c["page"], "chunk_index": i}
        for i, c in enumerate(chunks)
    ]
    _col.add(ids=ids, documents=texts, embeddings=vectors, metadatas=metadatas)

    full_head = "\n".join(texts[:8])
    info = analyze(full_head)
    info = {
        "title": info["title"] or (display_name or path.stem),
        **{k: v for k, v in info.items() if k != "title"},
    }

    stored = str(keep_path) if keep_path else ""
    cur = db.get().execute(
        "INSERT INTO docs(filename,title,category,tags,summary,chunks,file_hash,created,file_path)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (display_name or path.name, info["title"], info["category"],
         json.dumps(info["tags"], ensure_ascii=False),
         info["summary"], len(chunks), fh, db.now(), stored),
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
    """读取原文并返回按页文本(阅读器用)"""
    row = get_doc(doc_id)
    fp = row["file_path"]
    if not fp or not Path(fp).exists():
        raise ValueError("原文文件已丢失，请重新上传")
    pages = parser.parse(Path(fp))
    return [{"page": p, "text": t} for t, p in pages]


def delete_doc(doc_id: int):
    row = db.get().execute("SELECT file_hash FROM docs WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise ValueError("文档不存在")
    _col.delete(where={"file_hash": row["file_hash"]})
    db.get().execute("DELETE FROM docs WHERE id=?", (doc_id,))
    db.get().commit()


def search(query: str, k: int | None = None, where: dict | None = None) -> list[dict]:
    k = k or config.TOP_K
    if _col.count() == 0:
        return []
    vec = providers.embed([query])[0]
    res = _col.query(query_embeddings=[vec], n_results=min(k, _col.count()),
                     where=where or None)
    hits = []
    docs_table = db.get()
    for i, meta in enumerate(res["metadatas"][0]):
        fh = meta["file_hash"]
        row = docs_table.execute(
            "SELECT id,title,filename FROM docs WHERE file_hash=?", (fh,)
        ).fetchone()
        if not row:
            continue
        hits.append({
            "doc_id": row["id"], "title": row["title"] or row["filename"],
            "filename": row["filename"], "page": meta["page"],
            "text": res["documents"][0][i],
            "score": 1 - res["distances"][0][i],
        })
    return hits
