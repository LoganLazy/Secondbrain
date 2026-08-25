"""SQLite 元数据: 文档表/对话表"""
import sqlite3
import threading
import time
from pathlib import Path

from . import config

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def get() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DATA_DIR / "memory.db", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT, title TEXT, category TEXT,
                tags TEXT, summary TEXT,
                chunks INTEGER DEFAULT 0,
                file_hash TEXT,
                created REAL
            );
            CREATE TABLE IF NOT EXISTS chats(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT, content TEXT, sources TEXT, created REAL
            );
            CREATE TABLE IF NOT EXISTS memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT, created REAL
            );
            """
        )
        # 轻量迁移: 老库补列
        cols = [r[1] for r in _conn.execute("PRAGMA table_info(docs)")]
        if "file_path" not in cols:
            _conn.execute("ALTER TABLE docs ADD COLUMN file_path TEXT")
        if "kb_id" not in cols:
            _conn.execute("ALTER TABLE docs ADD COLUMN kb_id TEXT DEFAULT 'default'")
        # 唯一约束从 file_hash 改为 (file_hash, kb_id): 允许同文件存入多个知识库
        need_rebuild = False
        for idx in _conn.execute("PRAGMA index_list(docs)").fetchall():
            if idx[2]:  # unique
                cols_in_idx = [r[2] for r in
                               _conn.execute(f"PRAGMA index_info({idx[1]})").fetchall()]
                if cols_in_idx == ["file_hash"]:
                    need_rebuild = True
        if need_rebuild:
            _conn.executescript(
                """
                CREATE TABLE docs_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT, title TEXT, category TEXT,
                    tags TEXT, summary TEXT,
                    chunks INTEGER DEFAULT 0,
                    file_hash TEXT,
                    created REAL, file_path TEXT,
                    kb_id TEXT DEFAULT 'default',
                    UNIQUE(file_hash, kb_id)
                );
                INSERT INTO docs_new SELECT * FROM docs;
                DROP TABLE docs;
                ALTER TABLE docs_new RENAME TO docs;
                """
            )
        for tbl in ("chats", "flashcards"):
            c2 = [r[1] for r in _conn.execute(f"PRAGMA table_info({tbl})")]
            if "kb_id" not in c2:
                _conn.execute(f"ALTER TABLE {tbl} ADD COLUMN kb_id TEXT DEFAULT 'default'")
        try:
            _conn.execute(
                "CREATE TABLE IF NOT EXISTS kbs("
                "id TEXT PRIMARY KEY, name TEXT, created REAL)"
            )
            if not _conn.execute("SELECT COUNT(*) c FROM kbs").fetchone()["c"]:
                _conn.execute(
                    "INSERT INTO kbs(id,name,created) VALUES('default','默认知识库',?)",
                    (time.time(),),
                )
        except Exception:
            pass
        _conn.commit()
    return _conn


def now() -> float:
    return time.time()
