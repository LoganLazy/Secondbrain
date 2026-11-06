import json
import sqlite3
import unittest
from unittest.mock import patch

from app import cards, rag


class KnowledgeBaseIsolationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE flashcards(
                id INTEGER PRIMARY KEY, doc_id INTEGER, q TEXT, a TEXT,
                box INTEGER DEFAULT 0, reviews INTEGER DEFAULT 0,
                wrongs INTEGER DEFAULT 0, last_result TEXT DEFAULT '',
                last_reviewed REAL DEFAULT 0, created REAL,
                kb_id TEXT DEFAULT 'default'
            );
            CREATE TABLE chats(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT, content TEXT, sources TEXT, created REAL,
                kb_id TEXT, session_id TEXT
            );
            CREATE TABLE sessions(
                id TEXT PRIMARY KEY, title TEXT, kb_id TEXT,
                created REAL, updated REAL
            );
            CREATE TABLE memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT, created REAL, kb_id TEXT DEFAULT 'default'
            );
            INSERT INTO flashcards(id,q,a,kb_id) VALUES(1,'q','a','kb_a');
            INSERT INTO sessions VALUES('s_a','A','kb_a',0,0);
            INSERT INTO sessions VALUES('s_b','B','kb_a',0,0);
            INSERT INTO chats(role,content,sources,created,kb_id,session_id)
                VALUES('user','only session A','[]',0,'kb_a','s_a');
            INSERT INTO chats(role,content,sources,created,kb_id,session_id)
                VALUES('user','only session B','[]',0,'kb_a','s_b');
            INSERT INTO memories(content,kb_id,created)
                VALUES('work-only fact','kb_a',0);
            INSERT INTO memories(content,kb_id,created)
                VALUES('private-only fact','kb_b',0);
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_flashcard_cannot_be_answered_or_deleted_from_another_kb(self):
        with patch("app.cards.db.get", return_value=self.conn):
            with self.assertRaisesRegex(ValueError, "卡片不存在"):
                cards.answer(1, "correct", "kb_b")
            with self.assertRaisesRegex(ValueError, "卡片不存在"):
                cards.delete(1, "kb_b")
            row = self.conn.execute(
                "SELECT reviews FROM flashcards WHERE id=1"
            ).fetchone()
            self.assertEqual(row["reviews"], 0)

    def test_chat_history_is_limited_to_current_session(self):
        hit = {"doc_id": 7, "title": "Doc", "filename": "doc.md",
               "page": 1, "text": "knowledge", "score": 0.9}
        captured = {}

        def fake_chat(messages, temperature=0.4):
            captured["messages"] = messages
            return "answer"

        with (
            patch("app.rag.db.get", return_value=self.conn),
            patch("app.rag.db.now", return_value=1.0),
            patch("app.rag.search_with_threshold", return_value=[hit]),
            patch("app.rag.ingest.call_chat", side_effect=fake_chat),
        ):
            rag.chat("new question", kb_id="kb_a", session_id="s_a")

        contents = [message["content"] for message in captured["messages"]]
        self.assertIn("only session A", contents)
        self.assertNotIn("only session B", contents)
        saved = self.conn.execute(
            "SELECT COUNT(*) count FROM chats WHERE session_id='s_a'"
        ).fetchone()["count"]
        self.assertEqual(saved, 3)

    def test_memories_are_scoped_to_the_current_kb_in_chat(self):
        hit = {"doc_id": 7, "title": "Doc", "filename": "doc.md",
               "page": 1, "text": "knowledge", "score": 0.9}
        captured = {}

        def fake_chat(messages, temperature=0.4):
            captured["messages"] = messages
            return "answer"

        with (
            patch("app.rag.db.get", return_value=self.conn),
            patch("app.rag.db.now", return_value=1.0),
            patch("app.rag.search_with_threshold", return_value=[hit]),
            patch("app.rag.ingest.call_chat", side_effect=fake_chat),
        ):
            rag.chat("new question", kb_id="kb_a", session_id="s_a")

        system = next(
            message["content"] for message in captured["messages"]
            if message["role"] == "system"
        )
        self.assertIn("work-only fact", system)
        self.assertNotIn("private-only fact", system)

    def test_memories_query_is_scoped_per_kb(self):
        # 与 /api/memory 同款过滤条件: 只读本库的记忆, 删也只删本库的。
        rows_a = self.conn.execute(
            "SELECT content FROM memories WHERE kb_id=? ORDER BY id DESC",
            ("kb_a",)).fetchall()
        self.assertEqual([r["content"] for r in rows_a], ["work-only fact"])
        self.conn.execute(
            "DELETE FROM memories WHERE id=? AND kb_id=?",
            (2, "kb_a"))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"], 2)
        self.conn.execute(
            "DELETE FROM memories WHERE id=? AND kb_id=?",
            (2, "kb_b"))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"], 1)


if __name__ == "__main__":
    unittest.main()
