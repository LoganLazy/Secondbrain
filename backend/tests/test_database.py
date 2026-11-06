import sqlite3
import tempfile
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


if __name__ == "__main__":
    unittest.main()
