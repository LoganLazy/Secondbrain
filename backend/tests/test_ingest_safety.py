import tempfile
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import chromadb
from app import backup, bm25, config, db, ingest


class IngestSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.uploads = self.base / 'uploads'
        self.uploads.mkdir()
        self.stack = ExitStack()
        for key, value in {'BASE_DIR':self.base, 'DATA_DIR':self.base, 'UPLOAD_DIR':self.uploads, 'INBOX_DIR':self.base / 'inbox'}.items():
            self.stack.enter_context(patch.object(config, key, value))
        self.old_conn = db._conn
        db._conn = None
        self.collection = chromadb.EphemeralClient().create_collection('test_' + uuid.uuid4().hex)
        self.stack.enter_context(patch.object(ingest, '_col', self.collection))
        self.stack.enter_context(patch.object(bm25, 'INDEX', bm25.BM25Index()))
        self.stack.enter_context(patch.object(ingest.providers, 'embed', side_effect=lambda texts: [[0.1, 0.2] for _ in texts]))
        self.stack.enter_context(patch.object(ingest, 'analyze', return_value={'title':'资料', 'category':'测试', 'tags':[], 'summary':''}))
        self.first = self.uploads / 'first.txt'
        self.first.write_text('original alpha reference document')
        self.info = ingest.ingest(self.first, display_name='same.txt', keep_path=self.first)

    def tearDown(self):
        if db._conn is not None:
            db._conn.close()
        db._conn = self.old_conn
        self.stack.close()
        self.temp.cleanup()

    def test_failed_same_name_replacement_keeps_old_document_and_index(self):
        replacement = self.uploads / 'second.txt'
        replacement.write_text('replacement beta reference document')
        before = self.collection.get()['ids']
        with patch.object(ingest.providers, 'embed', side_effect=OSError('offline')), self.assertRaises(OSError):
            ingest.ingest(replacement, display_name='same.txt', keep_path=replacement)
        self.assertEqual(self.collection.get()['ids'], before)
        self.assertEqual(ingest.get_doc(self.info['id'])['file_path'], str(self.first))
        self.assertIn('original alpha', ingest.doc_pages(self.info['id'])[0]['text'])

    def test_successful_replacement_keeps_document_id_and_new_original(self):
        replacement = self.uploads / 'second.txt'
        replacement.write_text('replacement beta reference document')
        info = ingest.ingest(replacement, display_name='same.txt', keep_path=replacement)
        self.assertEqual(info['id'], self.info['id'])
        self.assertEqual(self.collection.count(), 1)
        self.assertEqual(ingest.get_doc(info['id'])['file_path'], str(replacement))
        self.assertIn('replacement beta', ingest.doc_pages(info['id'])[0]['text'])

    def test_moved_legacy_inbox_original_is_found_by_hash(self):
        source = config.INBOX_DIR / 'work' / 'old.txt'
        archive = source.parent / '已导入'
        archive.mkdir(parents=True)
        moved = archive / '123456_old.txt'
        moved.write_text('legacy inbox source')
        self.assertEqual(backup.locate_original(str(source), ingest.file_hash(moved)), moved)
        self.assertIsNone(backup.locate_original(str(source), 'wronghash'))

    def test_long_line_middle_remains_searchable_after_ingestion(self):
        source = self.uploads / 'long.txt'
        source.write_text('prefix ' * 100 + ' middleuniquemarker ' + 'suffix ' * 100)
        info = ingest.ingest(source, display_name='long.txt', keep_path=source)
        self.assertGreater(info['chunks'], 1)
        hits = ingest.search('middleuniquemarker')
        self.assertTrue(any(hit['doc_id'] == info['id'] and 'middleuniquemarker' in hit['text']
                            for hit in hits))
