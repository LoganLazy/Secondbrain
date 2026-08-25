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
                file_hash TEXT UNIQUE,
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
        _conn.commit()
    return _conn


def now() -> float:
    return time.time()
