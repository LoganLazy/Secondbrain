"""FastAPI 入口"""
import hashlib
import json
import re
import secrets
import sys
import threading
import time
import shutil
import tempfile
import os
import uuid
from typing import Literal
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from urllib.parse import urljoin

from . import config, db
from .lifecycle import acquire_service_lease, serialized, MUTATION_LOCK
from .restore import activate_pending, preview_restore, queue_restore, restore_status, pending_path, cancel_restore, write_json

acquire_service_lease()
activate_pending()
from . import ingest, rag
from . import cards as cards_mod
from .security import copy_limited, kb_inbox_path, safe_rmtree, safe_upload_name, validate_public_url

app = FastAPI(title="Nebula Memory")
_jobs = None
_jobs_lock = threading.Lock()
_admission_lock = threading.RLock()


def import_jobs():
    global _jobs
    with _jobs_lock:
        if _jobs is None:
            from .import_jobs import ImportJobs
            _jobs = ImportJobs()
        return _jobs


def require_import_ready():
    if pending_path().exists():
        raise HTTPException(409, '已有等待重启的恢复任务，请先重启知识库服务')


def import_kb(request):
    kb_id = KB(request)
    if request.headers.get('x-kb-id', 'default') != kb_id:
        raise HTTPException(404, '知识库已不存在')
    return kb_id


def require_local_origin(request):
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, '请从本机知识库页面执行此操作')


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def KB(request) -> str:
    """解析知识库；失效的显式选择不能悄悄回退到默认库。"""
    kb = request.headers.get("x-kb-id", "default")
    if kb != "default":
        row = db.get().execute("SELECT id FROM kbs WHERE id=?", (kb,)).fetchone()
        if not row:
            raise HTTPException(404, "知识库已不存在，请重新选择")
    return kb


def ensure_session(kb_id: str, session_id: str) -> None:
    """Reject a missing or cross-knowledge-base conversation session."""
    if session_id and not db.get().execute(
            "SELECT 1 FROM sessions WHERE id=? AND kb_id=?",
            (session_id, kb_id)).fetchone():
        raise HTTPException(404, "对话会话不存在")


app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver"],
)


@app.middleware('http')
async def protect_mutations(request: Request, call_next):
    if request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'请从本机知识库页面执行此操作'}, status_code=403)
    return await call_next(request)


_INSTANCE_ID = os.environ.get('NEBULA_MEMORY_INSTANCE_ID') or uuid.uuid4().hex


@app.get('/api/health')
def health():
    from fastapi.responses import JSONResponse
    try:
        db.get().execute('SELECT 1').fetchone()
        return {'product':'Nebula Memory', 'status':'ok', 'instance':_INSTANCE_ID}
    except Exception:
        return JSONResponse({'product':'Nebula Memory', 'status':'unavailable'}, status_code=503)


class QA(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


class SearchQ(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=30)
    mode: Literal['hybrid', 'keyword'] = 'hybrid'


class DocumentPatch(BaseModel):
    model_config = {'extra': 'forbid'}
    title: str = Field(default='', max_length=160)
    category: str = Field(default='', max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=20)


class MemoryIn(BaseModel):
    content: str


@app.post("/api/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    """支持多文件上传, 返回每个文件的结果"""
    require_import_ready()
    results = []
    for file in files:
        try:
            filename = safe_upload_name(file.filename)
        except ValueError as e:
            results.append({"file": file.filename or "", "ok": False, "msg": str(e)})
            continue
        suffix = Path(filename).suffix.lower()
        if suffix not in (".pdf", ".docx", ".txt", ".md",
                          ".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            results.append({"file": filename, "ok": False,
                            "msg": f"暂不支持 {suffix} 格式"})
            continue
        kb_dir = config.UPLOAD_DIR / KB(request)
        kb_dir.mkdir(parents=True, exist_ok=True)
        fh_tmp = uuid.uuid4().hex
        dest = kb_dir / f"{fh_tmp}_{filename}"
        try:
            copy_limited(file.file, dest)
            info = ingest.ingest(dest, display_name=filename,
                                 keep_path=dest, kb_id=KB(request))
            results.append({"file": filename, "ok": True,
                            "title": info["title"], "id": info["id"]})
        except ValueError as e:
            # 注意: "文档已存在"时不能删除dest, 它可能就是库里已有文档的原文!
            if "已存在" not in str(e):
                dest.unlink(missing_ok=True)
            results.append({"file": filename, "ok": False, "msg": str(e)})
        except Exception as e:
            dest.unlink(missing_ok=True)
            results.append({"file": filename, "ok": False,
                            "msg": f"处理失败: {e}"})
    return {"code": 0, "results": results}


@app.post('/api/import/jobs')
def create_import_job(request: Request, files: list[UploadFile] = File(...)):
    require_local_origin(request)
    require_import_ready()
    if len(files) > 50:
        raise HTTPException(413, '每次最多选择 50 个文件')
    kb_id = import_kb(request)
    items, rejected = [], []
    remaining = 500 * 1024 * 1024
    for file in files:
        dest = None
        try:
            filename = safe_upload_name(file.filename)
            if Path(filename).suffix.lower() not in ('.pdf', '.docx', '.txt', '.md', '.jpg', '.jpeg', '.png', '.webp', '.bmp'):
                raise ValueError('不支持的文档格式')
            folder = config.UPLOAD_DIR / kb_id
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / f'{uuid.uuid4().hex}_{filename}'
            size = copy_limited(file.file, dest, min(100 * 1024 * 1024, remaining))
            remaining -= size
            items.append({'file': filename, 'path': str(dest)})
        except Exception as exc:
            if dest is not None:
                dest.unlink(missing_ok=True)
            rejected.append({'file': file.filename or '', 'ok': False, 'msg': str(exc)})
    with _admission_lock:
        require_import_ready()
        job = import_jobs().create(kb_id, items) if items else None
    return {'code': 0, 'job': job, 'results': rejected}


@app.get('/api/import/jobs')
def list_import_jobs(request: Request):
    return {'jobs': import_jobs().list(import_kb(request))}


@app.post('/api/import/jobs/{job_id}/{action}')
def control_import_job(request: Request, job_id: str, action: str):
    require_local_origin(request)
    try:
        with _admission_lock:
            if action != 'stop':
                require_import_ready()
            return {'job': import_jobs().control(job_id, import_kb(request), action)}
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/docs/{doc_id}/content")
def doc_content(request: Request, doc_id: int):
    try:
        row = db.get().execute(
            "SELECT source_url, file_path, filename, file_hash FROM docs WHERE id=? AND kb_id=?",
            (doc_id, KB(request))).fetchone()
        if not row:
            raise ValueError("文档不存在")
        fp_lower = (row["file_path"] or "").lower()
        if fp_lower.endswith(".pdf"):
            kind = "pdf"
        elif fp_lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
            kind = "image"
        else:
            kind = "text"
        return {"code": 0, "pages": ingest.doc_pages(doc_id),
                "source_url": row["source_url"] if row else None,
                "kind": kind, "revision": row['file_hash'] or ''}
    except ValueError as e:
        raise HTTPException(404, str(e))


class AssistIn(BaseModel):
    doc_id: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=8000)
    scope: Literal['document', 'page', 'selection'] = 'page'
    passage: str = Field(default='', max_length=4000)
    page: int | None = Field(default=None, ge=1)


@app.post("/api/assist")
def assist(request: Request, a: AssistIn):
    """核验文档归属及范围后，从服务器原文构造上下文，不信任客户端全文。"""
    from . import reader
    try:
        prepared = reader.prepare(a.doc_id, KB(request), a.scope, a.page, a.passage)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return reader.answer(a.question, prepared)


@app.get("/api/docs")
def list_docs(request: Request):
    rows = db.get().execute(
        "SELECT id,filename,title,category,tags,summary,chunks,created,file_hash AS revision,"
        "(file_path IS NOT NULL AND file_path!='') AS has_file, source_url"
        " FROM docs WHERE kb_id=? ORDER BY id DESC", (KB(request),)
    ).fetchall()
    return [
        {**dict(r), "tags": json.loads(r["tags"])} for r in rows
    ]


@app.delete("/api/docs/{doc_id}")
def delete_doc(request: Request, doc_id: int):
    try:
        if not db.get().execute(
                "SELECT 1 FROM docs WHERE id=? AND kb_id=?",
                (doc_id, KB(request))).fetchone():
            raise ValueError("文档不存在")
        ingest.delete_doc(doc_id)
        return {"code": 0}
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/search")
def search(request: Request, q: SearchQ):
    return search_details(request, q)['hits']


@app.post('/api/search/details')
def search_details(request: Request, q: SearchQ):
    if not q.query.strip():
        raise HTTPException(400, '请输入搜索词')
    diagnostics = {}
    hits = ingest.search(q.query.strip(), q.k, kb_id=KB(request),
                         diagnostics=diagnostics, mode=q.mode)
    items = [
        {"doc_id": h["doc_id"], "title": h["title"], "filename": h["filename"], "page": h["page"],
         "text": h["text"], "score": round(h["score"], 3),
         'revision': h.get('revision', ''),
         "semantic": round(h.get("vn", 0), 3), "keyword": round(h.get("kw", 0), 3)}
        for h in hits
    ]
    return {'hits': items, 'query': q.query.strip(), **diagnostics}


@app.patch('/api/docs/{doc_id}')
def update_document(request: Request, doc_id: int, value: DocumentPatch):
    from . import documents
    require_local_origin(request)
    try:
        return documents.update(doc_id, KB(request), value.model_dump(exclude_unset=True))
    except BlockingIOError as exc:
        raise HTTPException(409, str(exc))
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/chat")
def chat(request: Request, qa: QA):
    kb = KB(request)
    ensure_session(kb, qa.session_id)
    result = rag.chat(qa.question, kb_id=kb, session_id=qa.session_id)
    # 后台自动提取长期记忆, 不阻塞回答
    if result.get("mode") == "generated":
        threading.Thread(
            target=auto_memory, args=(qa.question, result.get("answer", ""), kb),
            daemon=True,
        ).start()
    return result


@app.post("/api/chat/stream")
def chat_stream(request: Request, qa: QA):
    from fastapi.responses import StreamingResponse

    kb = KB(request)
    sid = qa.session_id
    ensure_session(kb, sid)

    def gen():
        first_q = True
        for ev in rag.chat_stream(qa.question, kb_id=kb, session_id=sid):
            if ev["type"] == "delta" and first_q and sid:
                db.get().execute(
                    "UPDATE sessions SET title=? WHERE id=? AND title='新对话'",
                    (qa.question[:20], sid))
                first_q = False
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


def auto_memory(question: str, answer: str, kb_id: str = "default"):
    """从对话中自动提取值得长期记住的用户信息(仅归属当前知识库)"""
    if config.get("NET_MODE") == "offline":
        return
    try:
        existing = [r["content"] for r in db.get().execute(
            "SELECT content FROM memories WHERE kb_id=? ORDER BY id DESC LIMIT 100",
            (kb_id,))]
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
                "INSERT INTO memories(content,kb_id,created) VALUES(?,?,?)",
                (fact, kb_id, db.now()),
            )
            db.get().commit()
            existing.insert(0, fact)
    except Exception as e:
        print(f"[auto_memory] 提取失败(不影响使用): {e}", flush=True)


@app.get("/api/history")
def history(request: Request, limit: int = 200, session_id: str = ""):
    ensure_session(KB(request), session_id)
    conds, args = ["kb_id=?", "session_id=?"], [KB(request), session_id]
    limit = max(1, min(limit, 500))
    rows = db.get().execute(
        "SELECT role,content,sources,created FROM chats WHERE "
        + " AND ".join(conds) + " ORDER BY id DESC LIMIT ?",
        (*args, limit),
    ).fetchall()
    return [{**dict(r), "sources": json.loads(r["sources"])} for r in rows][::-1]


@app.post("/api/memory")
def add_memory(request: Request, m: MemoryIn):
    db.get().execute(
        "INSERT INTO memories(content,kb_id,created) VALUES(?,?,?)",
        (m.content, KB(request), db.now())
    )
    db.get().commit()
    return {"code": 0}


@app.get("/api/memory")
def list_memory(request: Request):
    return [dict(r) for r in db.get().execute(
        "SELECT * FROM memories WHERE kb_id=? ORDER BY id DESC LIMIT 100",
        (KB(request),)
    )]


@app.delete("/api/memory/{mid}")
def del_memory(request: Request, mid: int):
    db.get().execute("DELETE FROM memories WHERE id=? AND kb_id=?",
                     (mid, KB(request)))
    db.get().commit()
    return {"code": 0}


def _dir_size_mb(path) -> float:
    total = 0
    for f in Path(path).rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return round(total / 1048576, 1)


@app.get("/api/stats")
def stats(request: Request):
    kb = KB(request)
    docs = db.get().execute(
        "SELECT COUNT(*) c FROM docs WHERE kb_id=?", (kb,)
    ).fetchone()["c"]
    chunks = len(ingest._col.get(where={"kb_id": kb})["ids"])
    lat = ingest.get_search_latency()
    if lat is None:
        est = "尚无检索记录"
    else:
        local = lat["local"]
        if chunks < 2000:
            grade = "流畅(本地<80ms)"
        elif chunks < 10000:
            grade = "良好(本地<250ms)"
        else:
            grade = "可用(资料量大, 建议关注性能)"
        est = f"{grade} · 本地实测{local}ms · 含云端向量化共{lat['total']}ms"
    return {"docs": docs, "chunks": chunks,
            "db_size_mb": _dir_size_mb(config.DATA_DIR),
            "search_ms": lat["total"] if lat else None,
            "local_ms": lat["local"] if lat else None,
            "perf_estimate": est,
            "vector": ingest.vector_health()}


@app.post("/api/index/rebuild")
def rebuild_index():
    require_import_ready()
    try:
        result = ingest.rebuild_vector_index()
        report = config.DATA_DIR / 'restore-report.json'
        if report.exists():
            info = json.loads(report.read_text(encoding='utf-8'))
            info['needs_rebuild'] = False
            write_json(report, info)
        return {"code": 0, **result}
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception:
        raise HTTPException(500, '重建未完成，请检查原文、模型配置和服务日志；不要删除备份或原始资料')


@app.get("/api/backup")
def download_backup():
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask
    from .backup import cleanup_backup, create_backup

    archive = create_backup()
    import zipfile
    with zipfile.ZipFile(archive) as zipped:
        missing_count = len(json.loads(zipped.read('Nebula-Memory/backup-manifest.json')).get('missing_originals', []))
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=archive.name,
        headers={'X-Backup-Missing-Originals': str(missing_count)},
        background=BackgroundTask(cleanup_backup, archive),
    )


# ---------------- 会话 ----------------
@app.post('/api/backup/preview')
def restore_preview(request: Request, file: UploadFile = File(...)):
    require_local_origin(request)
    try:
        return preview_restore(file.file)
    except Exception as exc:
        raise HTTPException(400, f'备份无法恢复：{exc}')


class RestoreConfirm(BaseModel):
    preview_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    restore_settings: bool = False
    confirm: Literal[True]


@app.post('/api/backup/restore')
def restore_confirm(request: Request, value: RestoreConfirm):
    require_local_origin(request)
    with _admission_lock:
        if import_jobs().active():
            raise HTTPException(409, '请先完成或停止文档导入任务')
        with MUTATION_LOCK:
            if import_jobs().active():
                raise HTTPException(409, '请先完成或停止文档导入任务')
            try:
                return queue_restore(value.preview_id, value.restore_settings)
            except Exception as exc:
                raise HTTPException(409, str(exc))


@app.get('/api/backup/restore-status')
def backup_restore_status():
    return restore_status()


@app.post('/api/backup/restore-cancel')
def backup_restore_cancel(request: Request):
    require_local_origin(request)
    return cancel_restore()



@app.get("/api/sessions")
def list_sessions(request: Request):
    kb = KB(request)
    return [dict(r) for r in db.get().execute(
        "SELECT * FROM sessions WHERE kb_id=? ORDER BY updated DESC", (kb,))]


@app.post("/api/sessions")
def create_session(request: Request, body: dict = None):
    kb = KB(request)
    sid = "s_" + secrets.token_hex(8)
    title = ((body or {}).get("title") or "新对话").strip()[:30]
    db.get().execute(
        "INSERT INTO sessions(id,title,kb_id,created,updated) VALUES(?,?,?,?,?)",
        (sid, title, kb, db.now(), db.now()))
    db.get().commit()
    return {"code": 0, "id": sid, "title": title}


class RenameIn(BaseModel):
    title: str


@app.post("/api/sessions/{sid}/rename")
def rename_session(request: Request, sid: str, body: RenameIn):
    t = body.title.strip()[:40]
    if not t:
        raise HTTPException(400, "标题不能为空")
    cur = db.get().execute(
        "UPDATE sessions SET title=?, updated=? WHERE id=? AND kb_id=?",
        (t, db.now(), sid, KB(request)))
    if not cur.rowcount:
        raise HTTPException(404, "对话会话不存在")
    db.get().commit()
    return {"code": 0}


@app.delete("/api/sessions/{sid}")
def delete_session(request: Request, sid: str):
    kb = KB(request)
    db.get().execute("DELETE FROM chats WHERE session_id=? AND kb_id=?", (sid, kb))
    db.get().execute("DELETE FROM sessions WHERE id=? AND kb_id=?", (sid, kb))
    db.get().commit()
    return {"code": 0}


@app.get("/api/docs/{doc_id}/file")
def doc_file(request: Request, doc_id: int):
    from fastapi.responses import FileResponse
    try:
        row = ingest.get_doc(doc_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if (row["kb_id"] or "default") != KB(request):
        raise HTTPException(404, "文档不存在")
    fp = row["file_path"]
    if not fp or not Path(fp).exists():
        raise HTTPException(404, "原文件已丢失，请重新上传")
    return FileResponse(fp, filename=row["filename"])


# ---------------- 设置 ----------------

@app.get("/api/config")
def get_config():
    out = {}
    for k in config.DEFAULTS:
        out[k] = config.get(k)
    for k in config.SECRET_KEYS:
        v = config.get(k) or ""
        out[k] = {"set": bool(v)}
    out['warnings'] = config.WARNINGS
    out["LABELS"] = config.LABELS
    from . import ocr
    out["ocr_available"] = ocr.available()
    return out


class ConfigIn(BaseModel):
    model_config = {'extra':'forbid'}
    patch: dict


@app.post("/api/config")
def set_config(c: ConfigIn):
    try:
        config.save(c.patch)
    except BlockingIOError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except OSError:
        raise HTTPException(500, '配置写入失败，原配置已保留，请检查目录权限和磁盘空间')
    return {"code": 0}


@app.post("/api/config/test")
def test_config(c: ConfigIn):
    import httpx

    t = c.patch.get("type")
    try:
        draft = config.validate_patch({key:value for key,value in c.patch.items() if key != 'type'})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    effective = {**config.SETTINGS, **{key:value for key,value in draft.items() if key not in config.SECRET_KEYS or value}}
    if t not in ('chat', 'embed'):
        raise HTTPException(400, 'type 必须是 chat 或 embed')
    if effective['NET_MODE'] == 'offline':
        return {'code':1, 'msg':'当前草稿为离线模式，不会发起在线连接测试；切换模式后可测试，测试不会保存配置。'}
    try:
        if t == "chat":
            base, key, model = (effective[name] for name in ('CHAT_BASE_URL', 'DEEPSEEK_KEY', 'CHAT_MODEL'))
            r = httpx.post(f"{base}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": model, "messages": [{"role": "user", "content": "hi"}],
                                 "max_tokens": 5}, timeout=30)
            r.raise_for_status()
            return {"code": 0, "msg": f"对话模型连通 ✓ ({model})"}
        if t == "embed":
            base, key, model = (effective[name] for name in ('EMBED_BASE_URL', 'ZHIPU_KEY', 'EMBED_MODEL'))
            r = httpx.post(f"{base}/embeddings",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": model, "input": ["测试"]}, timeout=30)
            r.raise_for_status()
            dim = len(r.json()["data"][0]["embedding"])
            return {"code": 0, "msg": f"向量模型连通 ✓ ({model}, {dim}维)"}
        raise HTTPException(400, "type 必须是 chat 或 embed")
    except HTTPException:
        raise
    except Exception:
        return {"code": 1, "msg": "连接失败，请检查接口地址、模型、密钥和网络；未修改已保存配置。"}


# ---------------- 多知识库 ----------------

KB_NAME_MAX_LENGTH = 64
_KB_NAME_FORBIDDEN = '/\\:*?"<>|'


@app.get("/api/kbs")
def list_kbs():
    return [dict(r) for r in db.get().execute(
        "SELECT * FROM kbs ORDER BY created")]


@app.post("/api/kbs")
def create_kb(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    if len(name) > KB_NAME_MAX_LENGTH:
        raise HTTPException(400, "名称不能超过 64 个字符")
    if name in (".", ".."):
        raise HTTPException(400, "名称不能为 . 或 ..")
    if any(ch in name for ch in _KB_NAME_FORBIDDEN):
        raise HTTPException(400, "名称不能包含 \\ / : * ? 等符号")
    if db.get().execute("SELECT 1 FROM kbs WHERE name=?", (name,)).fetchone():
        raise HTTPException(400, "已存在同名知识库")
    try:
        inbox_dir = kb_inbox_path(name, config.INBOX_DIR)
    except ValueError:
        raise HTTPException(400, "知识库名称无效")
    kid = "kb_" + secrets.token_hex(4)
    while db.get().execute("SELECT 1 FROM kbs WHERE id=?", (kid,)).fetchone():
        kid = "kb_" + secrets.token_hex(4)
    # 先建收件夹再写库: 建夹失败不留孤儿库记录。
    try:
        inbox_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise HTTPException(500, "创建知识库文件夹失败")
    db.get().execute("INSERT INTO kbs(id,name,created) VALUES(?,?,?)",
                     (kid, name, db.now()))
    db.get().commit()
    return {"code": 0, "id": kid, "name": name}


@app.delete("/api/kbs/{kb_id}")
def delete_kb(kb_id: str):
    if import_jobs().active():
        raise HTTPException(409, '请先完成或停止导入任务后删除知识库')
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
    db.get().execute("DELETE FROM sessions WHERE kb_id=?", (kb_id,))
    db.get().execute("DELETE FROM memories WHERE kb_id=?", (kb_id,))
    row = db.get().execute("SELECT name FROM kbs WHERE id=?", (kb_id,)).fetchone()
    db.get().execute("DELETE FROM kbs WHERE id=?", (kb_id,))
    db.get().commit()
    if row:
        # 只删严格位于收件夹内的目录; 旧库里的异常名称绝不能删到外面。
        safe_rmtree(config.INBOX_DIR / row["name"], config.INBOX_DIR)
    # 清理该库的原文目录(可能含此前删文档留下的孤儿文件)。
    safe_rmtree(config.UPLOAD_DIR / kb_id, config.UPLOAD_DIR)
    return {"code": 0}


# ---------------- 网页链接导入 ----------------

def _extract_web(url: str) -> tuple[str, str]:
    """抓取网页并提取正文, 返回 (标题, 正文文本)"""
    import trafilatura
    import httpx as _hx

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/120.0 Safari/537.36"}
    current = validate_public_url(url)
    for _ in range(6):
        # 每跳都重新校验, 校验后立即请求(见 validate_public_url 的 TOCTOU 说明)。
        r = _hx.get(current, headers=headers, timeout=25, follow_redirects=False)
        if r.status_code not in (301, 302, 303, 307, 308):
            break
        location = r.headers.get("location")
        if not location:
            break
        current = validate_public_url(urljoin(current, location))
    else:
        raise ValueError("网页重定向次数过多")
    r.raise_for_status()
    html = r.text
    if len(html) > 3_000_000:
        raise ValueError("页面过大")
    text = trafilatura.extract(html, include_comments=False,
                               favor_recall=True, url=current)
    if not text or len(text.strip()) < 80:
        raise ValueError("提取不到正文(可能是登录墙、JS动态页或非文章类页面)")
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = (m.group(1).strip() if m else "")[:80]
    title = re.sub(r"\s*[-_|·].*$", "", title) or url
    return title, text.strip()


class LinksIn(BaseModel):
    urls: list[str]


@app.post("/api/import/links")
def import_links(request: Request, body: LinksIn):
    kb = KB(request)
    results = []
    for url in body.urls[:10]:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            if url:
                results.append({"url": url, "ok": False, "msg": "不是有效链接"})
            continue
        if config.get("NET_MODE") == "offline":
            return {"code": 0,
                    "results": [{"url": url, "ok": False,
                                 "msg": "当前为离线模式，无法抓取网页"}]}
        try:
            # 同库URL去重
            dup = db.get().execute(
                "SELECT 1 FROM docs WHERE source_url=? AND kb_id=?",
                (url, kb)).fetchone()
            if dup:
                results.append({"url": url, "ok": False, "msg": "已导入过"})
                continue
            title, text = _extract_web(url)
            content = (f"# {title}\n\n> 来源: {url}\n"
                       f"> 抓取时间: {time.strftime('%Y-%m-%d %H:%M')}\n\n{text}")
            safe = re.sub(r"[^\w\u4e00-\u9fff-]", "_", title)[:40] or "web"
            kb_dir = config.UPLOAD_DIR / kb
            kb_dir.mkdir(parents=True, exist_ok=True)
            dest = kb_dir / f"web_{hashlib.md5(url.encode()).hexdigest()[:8]}_{safe}.md"
            dest.write_text(content, encoding="utf-8")
            info = ingest.ingest(dest, display_name=title, keep_path=dest, kb_id=kb)
            db.get().execute("UPDATE docs SET source_url=? WHERE id=?",
                             (url, info["id"]))
            db.get().commit()
            results.append({"url": url, "ok": True, "title": info["title"],
                            "id": info["id"], "chars": len(text)})
        except Exception as e:
            msg = str(e)
            if "404" in msg: msg = "页面不存在(404)"
            elif "403" in msg or "521" in msg or "520" in msg: msg = "站点反爬拒绝，无法抓取"
            elif "timed out" in msg.lower(): msg = "抓取超时"
            results.append({"url": url, "ok": False, "msg": msg})
    return {"code": 0, "results": results}


# ---------------- 知识库文件夹自动导入 ----------------

_importing_lock = threading.Lock()


@serialized
def scan_inbox():
    """扫描 知识库文件夹/, 每个知识库一个同名子文件夹.
    丢进哪个文件夹就导入哪个库; 根目录散落文件归入默认库."""
    if pending_path().exists() or not _importing_lock.acquire(blocking=False):
        return
    try:
        # 为每个库准备同名收件夹; 旧库里的异常名称跳过, 绝不建到收件夹外面
        kbs = db.get().execute("SELECT id,name FROM kbs").fetchall()
        folders: list[tuple[str, str]] = []   # (path, kb_id)
        for r in kbs:
            try:
                d = kb_inbox_path(r["name"], config.INBOX_DIR)
                d.mkdir(parents=True, exist_ok=True)
                folders.append((str(d), r["id"]))
            except (OSError, ValueError):
                continue
        # 根目录散落文件 -> 默认库
        for f in sorted(config.INBOX_DIR.iterdir()):
            if f.is_file():
                target = config.UPLOAD_DIR / "default"
                target.mkdir(parents=True, exist_ok=True)
                moved = target / f'{uuid.uuid4().hex}_{f.name}'
                shutil.move(str(f), str(moved))
                folders.insert(0, (str(target), "default"))
                import_jobs().create('default', [{'path': str(moved), 'file': f.name}])
                folders.pop(0)

        for path_str, kb_id in folders:
            folder = Path(path_str)
            done_dir = folder / "已导入"
            fail_dir = folder / "失败"
            for d in (done_dir, fail_dir):
                d.mkdir(exist_ok=True)
            for f in sorted(folder.iterdir()):
                if not f.is_file() or f.suffix.lower() not in (
                        ".pdf", ".docx", ".txt", ".md",
                        ".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                    continue
                _import_file(f, kb_id, done_dir, fail_dir)
    finally:
        _importing_lock.release()


def _import_file(f: Path, kb_id: str, done_dir: Path, fail_dir: Path):
    """处理单个待导入文件"""
    import time as _time
    stamp = _time.strftime("%H%M%S")
    try:
        info = ingest.ingest(f, display_name=f.name, keep_path=f, kb_id=kb_id)
        dest = done_dir / f"{stamp}_{uuid.uuid4().hex[:8]}_{f.name}"
        shutil.move(str(f), str(dest))
        db.get().execute('UPDATE docs SET file_path=? WHERE id=?', (str(dest), info['id']))
        db.get().commit()
        log(f"[自动导入] 成功({kb_id}): {f.name} -> 《{info['title']}》")
    except ValueError as e:
        if "已存在" in str(e) or "已有此文档" in str(e):
            dest = done_dir / f"{stamp}_{uuid.uuid4().hex[:8]}_{f.name}"
            shutil.move(str(f), str(dest))
            db.get().execute('UPDATE docs SET file_path=? WHERE file_path=?', (str(dest), str(f)))
            db.get().commit()
            log(f"[自动导入] 跳过重复({kb_id}): {f.name}")
        else:
            shutil.move(str(f), str(fail_dir / f"{stamp}_{f.name}"))
            log(f"[自动导入] 失败({kb_id}): {f.name}: {e}")
    except Exception as e:
        shutil.move(str(f), str(fail_dir / f"{stamp}_{f.name}"))
        log(f"[自动导入] 失败({kb_id}): {f.name}: {e}")


def migrate_uploads():
    """存量文件按所属库归入子目录"""
    conn = db.get()
    rows = conn.execute(
        "SELECT id, file_path, kb_id FROM docs WHERE file_path IS NOT NULL"
    ).fetchall()
    for r in rows:
        fp = Path(r["file_path"])
        if not fp.exists():
            continue
        # 已经在子目录里的跳过
        if fp.parent != config.UPLOAD_DIR:
            continue
        target_dir = config.UPLOAD_DIR / (r["kb_id"] or "default")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / fp.name
        try:
            shutil.move(str(fp), str(target))
            conn.execute("UPDATE docs SET file_path=? WHERE id=?",
                         (str(target), r["id"]))
            log(f"[迁移] {fp.name} -> {r['kb_id']}/")
        except OSError as e:
            log(f"[迁移] 失败: {fp.name}: {e}")
    conn.commit()


def inbox_loop():
    try:
        migrate_uploads()
    except Exception as e:
        print("[迁移] 失败:", e, flush=True)
    while True:
        try:
            scan_inbox()
        except Exception as e:
            print("[inbox] 扫描异常:", e, flush=True)
        time.sleep(60)


if os.environ.get('NEBULA_DISABLE_INBOX') != '1':
    threading.Thread(target=inbox_loop, daemon=True).start()


# ---------------- 闪卡 ----------------

class GenIn(BaseModel):
    doc_id: int = Field(gt=0)
    num: int = Field(default=10, ge=1, le=20)


@app.post("/api/flashcards/generate")
def fc_generate(request: Request, q: GenIn):
    try:
        if not db.get().execute(
                "SELECT 1 FROM docs WHERE id=? AND kb_id=?",
                (q.doc_id, KB(request))).fetchone():
            raise ValueError("文档不存在")
        n = cards_mod.generate(q.doc_id, q.num, KB(request))
        return {"code": 0, "count": n}
    except (cards_mod.CardConflict, BlockingIOError) as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(502, '出题未完成，请检查网络、离线模式或模型配置；已有卡片不受影响')


@app.get("/api/flashcards")
def fc_list(request: Request, doc_id: int | None = None):
    return cards_mod.list_cards(doc_id, kb_id=KB(request))


@app.get("/api/flashcards/due")
def fc_due(request: Request, doc_id: int | None = None):
    return cards_mod.due_queue(KB(request), doc_id)


class AnswerIn(BaseModel):
    result: Literal['correct', 'fuzzy', 'wrong']
    expected_reviews: int = Field(ge=0, strict=True)


@app.post("/api/flashcards/{card_id}/answer")
def fc_answer(request: Request, card_id: int, a: AnswerIn):
    if a.result not in ("correct", "fuzzy", "wrong"):
        raise HTTPException(400, "result 必须是 correct/fuzzy/wrong")
    try:
        result = cards_mod.answer(card_id, a.result, KB(request), a.expected_reviews)
        return {"code": 0, **result}
    except (cards_mod.CardConflict, BlockingIOError) as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/flashcards/{card_id}")
def fc_delete(request: Request, card_id: int):
    try:
        cards_mod.delete(card_id, KB(request))
        return {"code": 0}
    except BlockingIOError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/flashcards/stats")
def fc_stats(request: Request):
    return cards_mod.stats(KB(request))


# 生产模式挂载前端构建产物
if getattr(sys, "frozen", False):
    _dist = Path(sys._MEIPASS) / "frontend_dist"
else:
    _dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="fe")
