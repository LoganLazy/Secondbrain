"""知识库全文索引: 基于 SQLite FTS5(中文bigram预分词), 替代自研BM25.

接口与旧版兼容: INDEX.add/remove/search/clear/docs
"""
import hashlib
import json
import math
import re
import threading

from . import db


def tokenize(text: str) -> list[str]:
    """中文按字+相邻二字组词, 英文按单词"""
    text = text.lower()
    toks = re.findall(r"[a-z0-9]+", text)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        grams = [run[i:i + 2] for i in range(len(run) - 1)]
        toks += grams if grams else [run]
    return toks


class BM25Index:
    """对外接口不变, 内部为FTS5虚拟表"""

    def __init__(self):
        self._lock = threading.Lock()
        self._ready = False
        self._count = 0

    # ---- 内部 ----
    def _init_table(self):
        if self._ready:
            return
        conn = db.get()
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5("
            "cid UNINDEXED, body, meta_json UNINDEXED)"
        )
        self._count = conn.execute("SELECT COUNT(*) c FROM kb_fts").fetchone()["c"]
        self._ready = True

    @staticmethod
    def _meta_json(meta: dict) -> str:
        return json.dumps(meta, ensure_ascii=False)

    # ---- 对外 ----
    @property
    def docs(self):
        """兼容旧判空用法: 返回类dict对象(truthy=有数据)"""
        class _D:
            def __bool__(self2):
                self._init_table()
                return self._count > 0
        return _D()

    def clear(self):
        with self._lock:
            self._init_table()
            db.get().execute("DELETE FROM kb_fts")
            db.get().commit()
            self._count = 0

    def add(self, cid: str, text: str, meta: dict):
        self.add_batch([(cid, text, meta)])

    def add_batch(self, items: list[tuple[str, str, dict]]):
        if not items:
            return
        with self._lock:
            self._init_table()
            conn = db.get()
            rows = []
            for cid, text, meta in items:
                self.remove_nolock(cid)
                body = " ".join(tokenize(text))
                rows.append((cid, body, self._meta_json(meta)))
            conn.executemany(
                "INSERT INTO kb_fts(cid,body,meta_json) VALUES(?,?,?)", rows)
            conn.commit()
            self._count += len(rows)

    def remove_nolock(self, cid: str):
        cur = db.get().execute("DELETE FROM kb_fts WHERE cid=?", (cid,))
        if cur.rowcount > 0:
            self._count -= cur.rowcount

    def remove(self, cid: str):
        with self._lock:
            self._init_table()
            self.remove_nolock(cid)
            db.get().commit()

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float, dict]]:
        self._init_table()
        terms = sorted(set(tokenize(query)))
        if not terms or self._count == 0:
            return []
        match = " OR ".join(f'"{t}"' for t in terms[:64])
        try:
            rows = db.get().execute(
                "SELECT cid, bm25(kb_fts) AS rank, meta_json FROM kb_fts "
                "WHERE kb_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, top_k),
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            meta = json.loads(r["meta_json"])
            # FTS5 bm25 越小越相关, 取负数让外部统一"分数越大越好"
            score = -r["rank"] if r["rank"] < 0 else 0.0
            out.append((r["cid"], score * 1000, meta))
        return out


INDEX = BM25Index()
