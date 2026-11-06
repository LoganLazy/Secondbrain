"""SQLite 元数据: 文档表/对话表"""
import sqlite3
import threading
import time
from pathlib import Path

from . import config

# 每个线程一个连接: 单个 sqlite3 连接不能跨线程并发使用, 否则并发请求会
# 抛 sqlite3.InterfaceError。连接按线程缓存, 首次使用时在 _lock 下建库。
_conns: dict[int, sqlite3.Connection] = {}
_lock = threading.Lock()
# 兼容旧写法: 测试用 `db._conn = None` 重置缓存, 用 `db._conn` 取当前线程连接。
# get() 把 _conn 当作"最近一次使用的连接"的别名; _conn 为 None 时视为重置请求,
# 下次 get() 会关闭并丢弃全部缓存连接后再建新连接。
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DATA_DIR / "memory.db", timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL 让读不阻塞写; busy_timeout 让短暂的写竞争等待而不是直接报错。
    # 备份用 sqlite3 backup API(与 WAL 兼容), 恢复是整个 DATA_DIR 的替换,
    # 均不受 WAL 影响。
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
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
            content TEXT, created REAL,
            kb_id TEXT DEFAULT 'default'
        );
        CREATE TABLE IF NOT EXISTS flashcards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER,
            q TEXT, a TEXT,
            box INTEGER DEFAULT 0,
            reviews INTEGER DEFAULT 0,
            wrongs INTEGER DEFAULT 0,
            last_result TEXT DEFAULT '',
            last_reviewed REAL DEFAULT 0,
            created REAL,
            kb_id TEXT DEFAULT 'default'
        );
        """
    )
    # 轻量迁移: 老库补列
    cols = [r[1] for r in conn.execute("PRAGMA table_info(docs)")]
    if "file_path" not in cols:
        conn.execute("ALTER TABLE docs ADD COLUMN file_path TEXT")
    if "kb_id" not in cols:
        conn.execute("ALTER TABLE docs ADD COLUMN kb_id TEXT DEFAULT 'default'")
    if "source_url" not in cols:
        conn.execute("ALTER TABLE docs ADD COLUMN source_url TEXT")
    # 唯一约束从 file_hash 改为 (file_hash, kb_id): 允许同文件存入多个知识库
    need_rebuild = False
    for idx in conn.execute("PRAGMA index_list(docs)").fetchall():
        if idx[2]:  # unique
            cols_in_idx = [r[2] for r in
                           conn.execute(f"PRAGMA index_info({idx[1]})").fetchall()]
            if cols_in_idx == ["file_hash"]:
                need_rebuild = True
    if need_rebuild:
        conn.executescript(
            """
            CREATE TABLE docs_new(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT, title TEXT, category TEXT,
                tags TEXT, summary TEXT,
                chunks INTEGER DEFAULT 0,
                file_hash TEXT,
                created REAL, file_path TEXT,
                kb_id TEXT DEFAULT 'default',
                source_url TEXT,
                UNIQUE(file_hash, kb_id)
            );
            INSERT INTO docs_new(
                id,filename,title,category,tags,summary,chunks,file_hash,
                created,file_path,kb_id,source_url
            ) SELECT
                id,filename,title,category,tags,summary,chunks,file_hash,
                created,file_path,kb_id,source_url FROM docs;
            DROP TABLE docs;
            ALTER TABLE docs_new RENAME TO docs;
            """
        )
    for tbl in ("chats", "flashcards", "memories"):
        c2 = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
        if "kb_id" not in c2:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN kb_id TEXT DEFAULT 'default'")
    c3 = [r[1] for r in conn.execute("PRAGMA table_info(chats)")]
    if "session_id" not in c3:
        conn.execute("ALTER TABLE chats ADD COLUMN session_id TEXT DEFAULT ''")
    card_columns = {r[1] for r in conn.execute('PRAGMA table_info(flashcards)')}
    if 'source_hash' not in card_columns:
        conn.execute("ALTER TABLE flashcards ADD COLUMN source_hash TEXT DEFAULT ''")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions(
            id TEXT PRIMARY KEY, title TEXT,
            kb_id TEXT DEFAULT 'default',
            created REAL, updated REAL)"""
    )
    # 旧聊天记录归档到每库的"历史对话"会话
    old = conn.execute(
        "SELECT DISTINCT kb_id FROM chats WHERE session_id=''").fetchall()
    for r in old:
        kbv = r["kb_id"] or "default"
        sid = f"legacy_{kbv}"
        conn.execute(
            "INSERT OR IGNORE INTO sessions(id,title,kb_id,created,updated)"
            " VALUES(?,?,?,?,?)",
            (sid, "历史对话", kbv, time.time(), time.time()),
        )
        conn.execute("UPDATE chats SET session_id=? WHERE session_id='' AND kb_id=?",
                      (sid, kbv))
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5("
        "cid UNINDEXED, body, meta_json UNINDEXED)"
    )
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kbs("
            "id TEXT PRIMARY KEY, name TEXT, created REAL)"
        )
        if not conn.execute("SELECT COUNT(*) c FROM kbs").fetchone()["c"]:
            conn.execute(
                "INSERT INTO kbs(id,name,created) VALUES('default','默认知识库',?)",
                (time.time(),),
            )
    except Exception:
        pass
    conn.commit()


def get() -> sqlite3.Connection:
    """Return the calling thread's connection, creating it on first use.

    Schema creation/migration runs once per connection, serialized by _lock,
    so concurrent first use from several threads is safe.
    """
    global _conn
    with _lock:
        if _conn is None and _conns:
            # 重置请求(测试置 db._conn = None): 丢弃全部缓存连接。
            for cached in _conns.values():
                try:
                    cached.close()
                except Exception:
                    pass
            _conns.clear()
        tid = threading.get_ident()
        conn = _conns.get(tid)
        if conn is None:
            conn = _connect()
            _init_schema(conn)
            _conns[tid] = conn
        _conn = conn
        return conn


def now() -> float:
    return time.time()
