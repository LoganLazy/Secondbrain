import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app import documents


class DocumentMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE docs(id INTEGER PRIMARY KEY, title TEXT, filename TEXT,
                category TEXT, tags TEXT, kb_id TEXT, file_path TEXT,
                file_hash TEXT, chunks INTEGER, created REAL);
            INSERT INTO docs VALUES(1,'Original','original.txt','Work','["old"]','work','/managed/source.txt','hash',9,123);
        ''')
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(documents.db, 'get', return_value=self.conn))
        self.pending = Path(self.temp.name) / 'pending.json'
        self.stack.enter_context(patch.object(documents, 'pending_path', return_value=self.pending))

    def tearDown(self):
        self.stack.close()
        self.conn.close()
        self.temp.cleanup()

    def row(self):
        return dict(self.conn.execute('SELECT * FROM docs WHERE id=1').fetchone())

    def test_metadata_updates_preserve_original_identity_and_index_metadata(self):
        before = self.row()
        result = documents.update(1, 'work', {'title':' New title ', 'category':' Study ', 'tags':[' #AI ', 'ai', '阅读', '']})
        self.assertEqual(result['title'], 'New title')
        self.assertEqual(result['category'], 'Study')
        self.assertEqual(result['tags'], ['AI', '阅读'])
        for key in ('filename', 'file_path', 'file_hash', 'chunks', 'created', 'kb_id'):
            self.assertEqual(before[key], self.row()[key])

    def test_partial_update_and_clear_optional_fields(self):
        documents.update(1, 'work', {'category':'', 'tags':[]})
        self.assertEqual(self.row()['title'], 'Original')
        self.assertEqual(self.row()['category'], '')
        self.assertEqual(json.loads(self.row()['tags']), [])

    def test_cross_knowledge_base_update_is_rejected(self):
        with self.assertRaises(LookupError):
            documents.update(1, 'private', {'title':'Wrong'})
        self.assertEqual(self.row()['title'], 'Original')

    def test_invalid_changes_are_rejected_without_partial_writes(self):
        before = self.row()
        invalid = [{}, {'file_path':'/etc/passwd'}, {'title':'  '}, {'title':'x' * 161},
                   {'title':'bad\x00title'}, {'category':'x' * 81}, {'tags':'tag'},
                   {'tags':['x'] * 21}, {'tags':['x' * 41]}, {'tags':[1]},
                   {'title':'valid', 'tags':['bad\nvalue']}]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                documents.update(1, 'work', changes)
            self.assertEqual(self.row(), before)

    def test_pending_restore_blocks_editing(self):
        self.pending.touch()
        with self.assertRaises(BlockingIOError):
            documents.update(1, 'work', {'title':'Blocked'})
        self.assertEqual(self.row()['title'], 'Original')
