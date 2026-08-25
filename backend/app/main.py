"""FastAPI 入口"""
import hashlib
import hashlib
import json
import threading
import time
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, ingest, rag
from . import cards as cards_mod

app = FastAPI(title="Memory AI")


def KB(request) -> str:
    """从请求头解析知识库ID, 非法则回退默认库"""
    kb = request.headers.get("x-kb-id", "default")
    if kb != "default":
        row = db.get().execute("SELECT id FROM kbs WHERE id=?", (kb,)).fetchone()
        if not row:
            return "default"
    return kb
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
async def upload(request: Request, files: list[UploadFile] = File(...)):
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
            info = ingest.ingest(dest, display_name=file.filename,
                                 keep_path=dest, kb_id=KB(request))
            results.append({"file": file.filename, "ok": True,
                            "title": info["title"], "id": info["id"]})
        except ValueError as e:
            # 注意: "文档已存在"时不能删除dest, 它可能就是库里已有文档的原文!
            if "已存在" not in str(e):
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
def list_docs(request: Request):
    rows = db.get().execute(
        "SELECT id,filename,title,category,tags,summary,chunks,created,"
        "(file_path IS NOT NULL AND file_path!='') AS has_file"
        " FROM docs WHERE kb_id=? ORDER BY id DESC", (KB(request),)
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
def search(request: Request, q: SearchQ):
    hits = ingest.search(q.query, q.k, kb_id=KB(request))
    return [
        {"title": h["title"], "filename": h["filename"], "page": h["page"],
         "text": h["text"], "score": round(h["score"], 3)}
        for h in hits
    ]


@app.post("/api/chat")
def chat(request: Request, qa: QA):
    result = rag.chat(qa.question, kb_id=KB(request))
    # 后台自动提取长期记忆, 不阻塞回答
    threading.Thread(
        target=auto_memory, args=(qa.question, result.get("answer", "")),
        daemon=True,
    ).start()
    return result


@app.post("/api/chat/stream")
def chat_stream(request: Request, qa: QA):
    from fastapi.responses import StreamingResponse

    kb = KB(request)

    def gen():
        for ev in rag.chat_stream(qa.question, kb_id=kb):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/review/today")
def review_today(request: Request):
    """每日回顾: 到期闪卡 + 随机推荐重读的文档"""
    kb = KB(request)
    due = cards_mod.due_queue(kb)
    rows = db.get().execute(
        "SELECT id,title,summary FROM docs WHERE kb_id=? ORDER BY RANDOM() LIMIT 2",
        (kb,),
    ).fetchall()
    picks = [dict(r) for r in rows]
    return {"due_cards": len(due), "picks": picks}


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
def history(request: Request, limit: int = 50):
    rows = db.get().execute(
        "SELECT role,content,sources,created FROM chats WHERE kb_id=?"
        " ORDER BY id DESC LIMIT ?",
        (KB(request), limit),
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
def stats(request: Request):
    kb = KB(request)
    docs = db.get().execute(
        "SELECT COUNT(*) c FROM docs WHERE kb_id=?", (kb,)
    ).fetchone()["c"]
    chunks = len(ingest._col.get(where={"kb_id": kb})["ids"])
    return {"docs": docs, "chunks": chunks}


# ---------------- 设置 ----------------

@app.get("/api/config")
def get_config():
    out = {}
    for k in ("CHAT_BASE_URL", "CHAT_MODEL", "EMBED_BASE_URL",
              "EMBED_MODEL", "EMBED_PROVIDER"):
        out[k] = config.get(k)
    for k in config.SECRET_KEYS:
        v = config.get(k) or ""
        out[k] = {"set": bool(v), "preview": (v[:6] + "…" + v[-4:]) if len(v) > 12 else ("已设置" if v else "")}
    out["LABELS"] = config.LABELS
    return out


class ConfigIn(BaseModel):
    patch: dict


@app.post("/api/config")
def set_config(c: ConfigIn):
    allowed = {"CHAT_BASE_URL", "CHAT_MODEL", "EMBED_BASE_URL", "EMBED_MODEL",
               "EMBED_PROVIDER", "DEEPSEEK_KEY", "ZHIPU_KEY"}
    patch = {k: str(v).strip() for k, v in c.patch.items() if k in allowed}
    config.save(patch)
    return {"code": 0}


@app.post("/api/config/test")
def test_config(c: ConfigIn):
    import httpx

    t = c.patch.get("type")
    try:
        if t == "chat":
            base = str(c.patch.get("CHAT_BASE_URL") or config.get("CHAT_BASE_URL")).rstrip("/")
            key = c.patch.get("DEEPSEEK_KEY") or config.get("DEEPSEEK_KEY")
            model = c.patch.get("CHAT_MODEL") or config.get("CHAT_MODEL")
            r = httpx.post(f"{base}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": model, "messages": [{"role": "user", "content": "hi"}],
                                 "max_tokens": 5}, timeout=30)
            r.raise_for_status()
            return {"code": 0, "msg": f"对话模型连通 ✓ ({model})"}
        if t == "embed":
            base = str(c.patch.get("EMBED_BASE_URL") or config.get("EMBED_BASE_URL")).rstrip("/")
            key = c.patch.get("ZHIPU_KEY") or config.get("ZHIPU_KEY")
            model = c.patch.get("EMBED_MODEL") or config.get("EMBED_MODEL")
            r = httpx.post(f"{base}/embeddings",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": model, "input": ["测试"]}, timeout=30)
            r.raise_for_status()
            dim = len(r.json()["data"][0]["embedding"])
            return {"code": 0, "msg": f"向量模型连通 ✓ ({model}, {dim}维)"}
        raise HTTPException(400, "type 必须是 chat 或 embed")
    except HTTPException:
        raise
    except Exception as e:
        return {"code": 1, "msg": f"连接失败: {e}"}


# ---------------- 多知识库 ----------------

@app.get("/api/kbs")
def list_kbs():
    return [dict(r) for r in db.get().execute(
        "SELECT * FROM kbs ORDER BY created")]


@app.post("/api/kbs")
def create_kb(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    import random
    kid = "kb_" + "".join(random.choices("0123456789abcdef", k=6))
    while db.get().execute("SELECT 1 FROM kbs WHERE id=?", (kid,)).fetchone():
        kid = "kb_" + "".join(random.choices("0123456789abcdef", k=6))
    db.get().execute("INSERT INTO kbs(id,name,created) VALUES(?,?,?)",
                     (kid, name, db.now()))
    db.get().commit()
    return {"code": 0, "id": kid, "name": name}


@app.delete("/api/kbs/{kb_id}")
def delete_kb(kb_id: str):
    if kb_id == "default":
        raise HTTPException(400, "默认知识库不能删除")
    # 删文档(含向量/关键词索引/原文件)
    for row in db.get().execute(
            "SELECT id FROM docs WHERE kb_id=?", (kb_id,)).fetchall():
        try:
            ingest.delete_doc(row["id"])
        except Exception:
            pass
    db.get().execute("DELETE FROM flashcards WHERE kb_id=?", (kb_id,))
    db.get().execute("DELETE FROM chats WHERE kb_id=?", (kb_id,))
    db.get().execute("DELETE FROM kbs WHERE id=?", (kb_id,))
    db.get().commit()
    return {"code": 0}


# ---------------- 知识库文件夹自动导入 ----------------

_importing_lock = threading.Lock()


def scan_inbox():
    """扫描 知识库文件夹/, 自动导入新文件; 成功移到 已导入/, 失败移到 失败/"""
    if not _importing_lock.acquire(blocking=False):
        return
    try:
        done_dir = config.INBOX_DIR / "已导入"
        fail_dir = config.INBOX_DIR / "失败"
        for d in (done_dir, fail_dir):
            d.mkdir(exist_ok=True)
        for f in sorted(config.INBOX_DIR.iterdir()):
            if not f.is_file() or f.suffix.lower() not in (".pdf", ".docx", ".txt", ".md"):
                continue
            try:
                info = ingest.ingest(f, display_name=f.name, keep_path=f)
                shutil.move(str(f), str(done_dir / f.name))
                log(f"[自动导入] 成功: {f.name} -> 《{info['title']}》")
            except ValueError as e:
                if "已存在" in str(e):
                    shutil.move(str(f), str(done_dir / f.name))
                    log(f"[自动导入] 跳过重复: {f.name}")
                else:
                    shutil.move(str(f), str(fail_dir / f.name))
                    log(f"[自动导入] 失败: {f.name}: {e}")
            except Exception as e:
                shutil.move(str(f), str(fail_dir / f.name))
                log(f"[自动导入] 失败: {f.name}: {e}")
    finally:
        _importing_lock.release()


def inbox_loop():
    while True:
        try:
            scan_inbox()
        except Exception as e:
            print("[inbox] 扫描异常:", e, flush=True)
        time.sleep(60)


threading.Thread(target=inbox_loop, daemon=True).start()


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
def fc_list(request: Request, doc_id: int | None = None):
    return cards_mod.list_cards(doc_id, kb_id=KB(request))


@app.get("/api/flashcards/due")
def fc_due(request: Request):
    return cards_mod.due_queue(KB(request))


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
def fc_stats(request: Request):
    return cards_mod.stats(KB(request))


# 生产模式挂载前端构建产物(存在才生效)
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="fe")
