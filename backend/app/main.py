"""FastAPI 入口"""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, ingest, rag

app = FastAPI(title="Memory AI")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class QA(BaseModel):
    question: str


class SearchQ(BaseModel):
    query: str
    k: int | None = None


class MemoryIn(BaseModel):
    content: str


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, f"暂不支持 {suffix}，目前支持 pdf/docx/txt/md")

    # 先落盘到持久目录(阅读器需要原文)
    fh_tmp = hashlib.md5(file.filename.encode()).hexdigest()[:8]
    dest = config.UPLOAD_DIR / f"{fh_tmp}_{file.filename}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        info = ingest.ingest(dest, display_name=file.filename, keep_path=dest)
        return {"code": 0, "doc": info}
    except ValueError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"处理失败: {e}")


@app.get("/api/docs/{doc_id}/content")
def doc_content(doc_id: int):
    try:
        return {"code": 0, "pages": ingest.doc_pages(doc_id)}
    except ValueError as e:
        raise HTTPException(404, str(e))


class AssistIn(BaseModel):
    question: str
    passage: str = ""
    title: str = ""
    page: int | None = None


@app.post("/api/assist")
def assist(a: AssistIn):
    """阅读助手: 基于指定段落/全文回答, 不走知识库检索"""
    sys_prompt = (
        "你是Memory AI的阅读助手。用户正在阅读自己的文档"
        + (f"《{a.title}》第{a.page}页" if a.page else f"《{a.title}》" if a.title else "")
        + "。用简洁中文回答；若提供了文档片段，答案必须基于片段内容。"
    )
    user = a.question
    if a.passage:
        user = f"文档片段:\n{a.passage[:6000]}\n\n问题: {a.question}"
    messages = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": user}]
    try:
        return {"code": 0, "answer": ingest.call_chat(messages, temperature=0.4)}
    except Exception as e:
        raise HTTPException(500, f"AI调用失败: {e}")


@app.get("/api/docs")
def list_docs():
    rows = db.get().execute(
        "SELECT id,filename,title,category,tags,summary,chunks,created"
        " FROM docs ORDER BY id DESC"
    ).fetchall()
    return [
        {**dict(r), "tags": json.loads(r["tags"])} for r in rows
    ]


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: int):
    try:
        ingest.delete_doc(doc_id)
        return {"code": 0}
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/search")
def search(q: SearchQ):
    hits = ingest.search(q.query, q.k)
    return [
        {"title": h["title"], "filename": h["filename"], "page": h["page"],
         "text": h["text"], "score": round(h["score"], 3)}
        for h in hits
    ]


@app.post("/api/chat")
def chat(qa: QA):
    return rag.chat(qa.question)


@app.get("/api/history")
def history(limit: int = 50):
    rows = db.get().execute(
        "SELECT role,content,sources,created FROM chats ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{**dict(r), "sources": json.loads(r["sources"])} for r in rows][::-1]


@app.post("/api/memory")
def add_memory(m: MemoryIn):
    db.get().execute(
        "INSERT INTO memories(content,created) VALUES(?,?)", (m.content, db.now())
    )
    db.get().commit()
    return {"code": 0}


@app.get("/api/memory")
def list_memory():
    return [dict(r) for r in db.get().execute(
        "SELECT * FROM memories ORDER BY id DESC LIMIT 100"
    )]


@app.delete("/api/memory/{mid}")
def del_memory(mid: int):
    db.get().execute("DELETE FROM memories WHERE id=?", (mid,))
    db.get().commit()
    return {"code": 0}


@app.get("/api/stats")
def stats():
    docs = db.get().execute("SELECT COUNT(*) c FROM docs").fetchone()["c"]
    chunks = ingest._col.count()
    return {"docs": docs, "chunks": chunks}


# 生产模式挂载前端构建产物(存在才生效)
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="fe")
