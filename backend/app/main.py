"""FastAPI 入口"""
import hashlib
import hashlib
import json
import threading
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, ingest, rag
from . import cards as cards_mod

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
async def upload(files: list[UploadFile] = File(...)):
    """支持多文件上传, 返回每个文件的结果"""
    results = []
    for file in files:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in (".pdf", ".docx", ".txt", ".md"):
            results.append({"file": file.filename, "ok": False,
                            "msg": f"暂不支持 {suffix} 格式"})
            continue
        fh_tmp = hashlib.md5(file.filename.encode()).hexdigest()[:8]
        dest = config.UPLOAD_DIR / f"{fh_tmp}_{file.filename}"
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            info = ingest.ingest(dest, display_name=file.filename, keep_path=dest)
            results.append({"file": file.filename, "ok": True,
                            "title": info["title"], "id": info["id"]})
        except ValueError as e:
            dest.unlink(missing_ok=True)
            results.append({"file": file.filename, "ok": False, "msg": str(e)})
        except Exception as e:
            dest.unlink(missing_ok=True)
            results.append({"file": file.filename, "ok": False,
                            "msg": f"处理失败: {e}"})
    return {"code": 0, "results": results}


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
    result = rag.chat(qa.question)
    # 后台自动提取长期记忆, 不阻塞回答
    threading.Thread(
        target=auto_memory, args=(qa.question, result.get("answer", "")),
        daemon=True,
    ).start()
    return result


def auto_memory(question: str, answer: str):
    """从对话中自动提取值得长期记住的用户信息"""
    try:
        existing = [r["content"] for r in db.get().execute(
            "SELECT content FROM memories ORDER BY id DESC LIMIT 100")]
        prompt = (
            "从下面的用户对话中, 提取值得AI长期记住的【用户个人信息/设备/偏好/背景】"
            "(例如: 有什么服务器、用什么工具、职业、习惯)。"
            "只提取明确提到的事实, 没有就返回[]。"
            '只返回JSON数组如["事实1","事实2"]\n\n'
            f"用户问: {question[:300]}\nAI答: {answer[:300]}"
        )
        raw = ingest.call_chat(
            [{"role": "system", "content": prompt},
             {"role": "user", "content": prompt.split("\n\n")[-1]}],
            temperature=0.2,
        )
        s = raw[raw.find("["): raw.rfind("]") + 1]
        facts = json.loads(s)
        if not isinstance(facts, list):
            return
        for fact in facts[:3]:
            fact = str(fact).strip()[:120]
            if len(fact) < 4:
                continue
            # 去重: 与已有记忆高度重合则跳过
            if any(fact[:20] in e or e[:20] in fact for e in existing):
                continue
            db.get().execute(
                "INSERT INTO memories(content,created) VALUES(?,?)",
                (fact, db.now()),
            )
            db.get().commit()
            existing.insert(0, fact)
    except Exception as e:
        print(f"[auto_memory] 提取失败(不影响使用): {e}", flush=True)


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


# ---------------- 闪卡 ----------------

class GenIn(BaseModel):
    doc_id: int
    num: int = 10


@app.post("/api/flashcards/generate")
def fc_generate(q: GenIn):
    try:
        n = cards_mod.generate(q.doc_id, q.num)
        return {"code": 0, "count": n}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"出题失败: {e}")


@app.get("/api/flashcards")
def fc_list(doc_id: int | None = None):
    return cards_mod.list_cards(doc_id)


@app.get("/api/flashcards/due")
def fc_due():
    return cards_mod.due_queue()


class AnswerIn(BaseModel):
    result: str


@app.post("/api/flashcards/{card_id}/answer")
def fc_answer(card_id: int, a: AnswerIn):
    if a.result not in ("correct", "fuzzy", "wrong"):
        raise HTTPException(400, "result 必须是 correct/fuzzy/wrong")
    try:
        cards_mod.answer(card_id, a.result)
        return {"code": 0}
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/flashcards/{card_id}")
def fc_delete(card_id: int):
    cards_mod.delete(card_id)
    return {"code": 0}


@app.get("/api/flashcards/stats")
def fc_stats():
    return cards_mod.stats()


# 生产模式挂载前端构建产物(存在才生效)
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="fe")
