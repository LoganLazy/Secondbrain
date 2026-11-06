import tempfile
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import chromadb
from app import bm25, config, db, ingest


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, 'DATA_DIR', Path(self.temp.name)))
        self.old_conn, db._conn = db._conn, None
        self.col = chromadb.EphemeralClient().create_collection('search_' + uuid.uuid4().hex)
        self.stack.enter_context(patch.object(ingest, '_col', self.col))
        self.index = bm25.BM25Index()
        self.stack.enter_context(patch.object(bm25, 'INDEX', self.index))
        self.add('mine', 'work', 'alpha local document')
        for i in range(20):
            self.add('foreign' + str(i), 'private', 'alpha alpha private secret')

    def add(self, cid, kb, text):
        meta = {'kb_id': kb, 'file_hash': cid, 'page': 1}
        db.get().execute("INSERT INTO docs(filename,title,file_hash,kb_id) VALUES(?,?,?,?)",
                         (cid + '.txt', cid, cid, kb))
        db.get().commit()
        self.col.add(ids=[cid], documents=[text], embeddings=[[.1, .2]], metadatas=[meta])
        self.index.add(cid, text, meta)

    def tearDown(self):
        if db._conn is not None:
            db._conn.close()
        db._conn = self.old_conn
        self.stack.close()
        self.temp.cleanup()

    def test_keyword_filter_is_applied_before_limit(self):
        rows = self.index.search('alpha', top_k=1, kb_id='work')
        self.assertEqual([row[0] for row in rows], ['mine'])

    def test_embedding_failure_uses_only_current_kb_and_redacts_error(self):
        diagnostics = {}
        with patch.object(ingest.providers, 'embed', side_effect=OSError('secret-api-key')):
            hits = ingest.search('alpha', k=1, kb_id='work', diagnostics=diagnostics)
        self.assertEqual([hit['filename'] for hit in hits], ['mine.txt'])
        self.assertIn('关键词', diagnostics['warning'])
        self.assertNotIn('secret-api-key', str(diagnostics))

    def test_hybrid_results_do_not_leak_other_kbs(self):
        with patch.object(ingest.providers, 'embed', return_value=[[.1, .2]]):
            hits = ingest.search('alpha', k=10, kb_id='work')
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['filename'], 'mine.txt')

    def test_dimension_mismatch_still_finds_keyword_match(self):
        with patch.object(ingest.providers, 'embed', return_value=[[.1, .2, .3]]):
            hits = ingest.search('alpha', kb_id='work')
        self.assertEqual(hits[0]['filename'], 'mine.txt')

    def test_stale_keyword_row_is_skipped(self):
        self.col.delete(ids=['mine'])
        with patch.object(ingest.providers, 'embed', side_effect=OSError('offline')):
            self.assertEqual(ingest.search('alpha', kb_id='work'), [])

    def test_keyword_mode_never_calls_embeddings_or_online_reranking(self):
        diagnostics = {}
        self.add('second', 'work', 'alpha second document')
        with patch.object(ingest.providers, 'embed') as embed, patch.object(ingest.httpx, 'post') as rerank, \
                patch.dict('os.environ', {'RERANK_BASE_URL':'https://unused.example'}):
            hits = ingest.search('alpha', kb_id='work', mode='keyword', diagnostics=diagnostics)
        embed.assert_not_called()
        rerank.assert_not_called()
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(hit['vn'] == 0 for hit in hits))
        self.assertEqual(diagnostics, {'mode':'keyword', 'warning':''})

    def test_search_reflects_metadata_edits_without_new_embeddings(self):
        db.get().execute("UPDATE docs SET title='Edited title' WHERE file_hash='mine'")
        db.get().commit()
        with patch.object(ingest.providers, 'embed') as embed:
            hits = ingest.search('alpha', kb_id='work', mode='keyword')
        embed.assert_not_called()
        self.assertEqual(hits[0]['title'], 'Edited title')
        self.assertEqual(hits[0]['revision'], 'mine')

    def test_invalid_search_mode_does_not_call_provider(self):
        with patch.object(ingest.providers, 'embed') as embed, self.assertRaises(ValueError):
            ingest.search('alpha', mode='unknown')
        embed.assert_not_called()
