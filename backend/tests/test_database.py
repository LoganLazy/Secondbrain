import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db


class DatabaseMigrationTests(unittest.TestCase):
    def test_legacy_flashcard_progress_survives_source_version_migration(self):
        old_conn = db._conn
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            conn = sqlite3.connect(data_dir / 'memory.db')
            conn.executescript('''
                CREATE TABLE flashcards(id INTEGER PRIMARY KEY,doc_id INTEGER,q TEXT,a TEXT,
                    box INTEGER DEFAULT 0,reviews INTEGER DEFAULT 0,wrongs INTEGER DEFAULT 0,
                    last_result TEXT DEFAULT '',last_reviewed REAL DEFAULT 0,created REAL,
                    kb_id TEXT DEFAULT 'default');
                INSERT INTO flashcards VALUES(17,5,'old question','old answer',3,5,2,'correct',123,100,'work');
            ''')
            conn.commit(); conn.close()
            db._conn = None
            try:
                with patch('app.db.config.DATA_DIR', data_dir):
                    row = db.get().execute('SELECT * FROM flashcards WHERE id=17').fetchone()
                    self.assertEqual(row['q'], 'old question')
                    self.assertEqual(row['reviews'], 5)
                    self.assertEqual(row['wrongs'], 2)
                    self.assertEqual(row['box'], 3)
                    self.assertEqual(row['source_hash'], '')
            finally:
                if db._conn is not None:
                    db._conn.close()
                db._conn = old_conn

    def test_legacy_unique_hash_migration_keeps_source_url(self):
        old_conn = db._conn
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            conn = sqlite3.connect(data_dir / "memory.db")
            conn.executescript(
                """
                CREATE TABLE docs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT, title TEXT, category TEXT, tags TEXT,
                    summary TEXT, chunks INTEGER DEFAULT 0,
                    file_hash TEXT UNIQUE, created REAL,
                    file_path TEXT, kb_id TEXT DEFAULT 'default', source_url TEXT
                );
                INSERT INTO docs(filename,file_hash,kb_id,source_url)
                VALUES('saved.md','abc','default','https://example.com/article');
                """
            )
            conn.commit()
            conn.close()
            db._conn = None
            try:
                with patch("app.db.config.DATA_DIR", data_dir):
                    migrated = db.get()
                    row = migrated.execute(
                        "SELECT filename,source_url FROM docs"
                    ).fetchone()
                    self.assertEqual(row["filename"], "saved.md")
                    self.assertEqual(row["source_url"], "https://example.com/article")
            finally:
                if db._conn is not None:
                    db._conn.close()
                db._conn = old_conn

    def test_legacy_memories_gain_kb_id_and_keep_default(self):
        old_conn = db._conn
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            conn = sqlite3.connect(data_dir / "memory.db")
            conn.executescript(
                """
                CREATE TABLE memories(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT, created REAL
                );
                INSERT INTO memories(content,created) VALUES('old fact', 100);
                """
            )
            conn.commit()
            conn.close()
            db._conn = None
            try:
                with patch("app.db.config.DATA_DIR", data_dir):
                    row = db.get().execute(
                        "SELECT content,kb_id FROM memories WHERE id=1"
                    ).fetchone()
                    self.assertEqual(row["content"], "old fact")
                    self.assertEqual(row["kb_id"], "default")
            finally:
                if db._conn is not None:
                    db._conn.close()
                db._conn = old_conn

    def test_concurrent_reads_and_writes_do_not_raise_interface_error(self):
        # 回归: 单个共享连接时, 并发请求会抛 sqlite3.InterfaceError。
        old_conn = db._conn
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            db._conn = None
            try:
                with patch("app.db.config.DATA_DIR", data_dir):
                    errors = []

                    def work(n):
                        try:
                            conn = db.get()
                            for i in range(20):
                                conn.execute(
                                    "INSERT INTO memories(content,kb_id,created)"
                                    " VALUES(?,?,?)", (f"fact-{n}-{i}", "default", 1.0))
                                conn.commit()
                                conn.execute(
                                    "SELECT COUNT(*) FROM memories").fetchone()
                        except Exception as exc:  # noqa: BLE001 - 收集后统一断言
                            errors.append(exc)

                    threads = [threading.Thread(target=work, args=(n,))
                               for n in range(16)]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                    self.assertEqual(errors, [])
                    count = db.get().execute(
                        "SELECT COUNT(*) c FROM memories").fetchone()["c"]
                    self.assertEqual(count, 16 * 20)
            finally:
                if db._conn is not None:
                    db._conn.close()
                db._conn = old_conn


if __name__ == "__main__":
    unittest.main()
