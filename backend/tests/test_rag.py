import json
import sqlite3
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app import rag


class RagReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE chats(id INTEGER PRIMARY KEY, role TEXT, content TEXT,
                sources TEXT, created REAL, kb_id TEXT, session_id TEXT);
            CREATE TABLE sessions(id TEXT, updated REAL);
            CREATE TABLE memories(id INTEGER PRIMARY KEY, content TEXT);
        ''')
        self.hit = {'doc_id': 7, 'title': '手册', 'filename': 'manual.txt',
                    'page': 3, 'text': 'alpha original evidence', 'score': .85}
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(rag.db, 'get', return_value=self.conn))
        self.stack.enter_context(patch.object(rag, 'search_with_threshold', return_value=[self.hit]))

    def tearDown(self):
        self.stack.close()
        self.conn.close()

    def saved(self):
        return self.conn.execute("SELECT * FROM chats WHERE role='assistant' ORDER BY id DESC").fetchone()

    def test_stream_sources_are_complete_and_persisted(self):
        with patch.object(rag.ingest, 'call_chat_stream', return_value=(piece for piece in ['答', '案'])):
            events = list(rag.chat_stream('alpha', 'work', 'session'))
        self.assertEqual(events[-1], {'type': 'done', 'mode': 'generated'})
        sources = json.loads(self.saved()['sources'])
        self.assertEqual(sources, events[0]['sources'])
        self.assertEqual(sources[0]['doc_id'], 7)
        self.assertEqual(sources[0]['text'], self.hit['text'])
        self.assertEqual(sources[0]['score'], .85)
        self.assertEqual(self.saved()['content'], '答案')

    def test_sync_failure_keeps_sources_and_uses_explicit_extracts(self):
        with patch.object(rag.ingest, 'call_chat', side_effect=OSError('secret-api-key')):
            result = rag.chat('alpha')
        self.assertEqual(result['mode'], 'extracts')
        self.assertIn('不是 AI 生成的结论', result['answer'])
        self.assertIn(self.hit['text'], result['answer'])
        self.assertNotIn('secret-api-key', str(result))
        self.assertEqual(json.loads(self.saved()['sources']), result['sources'])

    def test_interrupted_stream_replaces_unfinished_answer_and_redacts_error(self):
        def failing_stream(messages):
            yield 'unfinished unsupported conclusion'
            raise OSError('secret-api-key')
        with patch.object(rag.ingest, 'call_chat_stream', side_effect=failing_stream):
            events = list(rag.chat_stream('alpha'))
        replacement = next(event['text'] for event in events if event['type'] == 'replace')
        self.assertEqual(events[-1]['mode'], 'extracts')
        self.assertEqual(self.saved()['content'], replacement)
        self.assertNotIn('unfinished', replacement)
        self.assertNotIn('secret-api-key', str(events))

    def test_no_matches_are_not_described_as_empty_library_and_are_saved(self):
        with patch.object(rag, 'search_with_threshold', return_value=[]), patch.object(rag.ingest, 'call_chat') as model:
            result = rag.chat('missing')
            events = list(rag.chat_stream('missing'))
        model.assert_not_called()
        self.assertEqual(result['mode'], 'no_match')
        self.assertEqual(events[-1]['mode'], 'no_match')
        self.assertIn('没有找到足够相关', result['answer'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM chats').fetchone()[0], 4)

    def test_empty_session_does_not_include_other_sessions(self):
        self.conn.execute("INSERT INTO chats(role,content,kb_id,session_id) VALUES('user','private session','work','other')")
        with patch.object(rag.ingest, 'call_chat', return_value='answer') as model:
            rag.chat('alpha', 'work', '')
        self.assertNotIn('private session', str(model.call_args))

    def test_closing_stream_closes_provider_and_does_not_save_partial(self):
        closed = []
        def stream(messages):
            try:
                yield 'partial'
                yield 'rest'
            finally:
                closed.append(True)
        with patch.object(rag.ingest, 'call_chat_stream', side_effect=stream):
            response = rag.chat_stream('alpha')
            next(response)
            next(response)
            response.close()
        self.assertEqual(closed, [True])
        self.assertIsNone(self.saved())

    def test_empty_model_answer_uses_extract_fallback(self):
        with patch.object(rag.ingest, 'call_chat', return_value='  '):
            self.assertEqual(rag.chat('alpha')['mode'], 'extracts')
        with patch.object(rag.ingest, 'call_chat_stream', return_value=(piece for piece in [])):
            self.assertEqual(list(rag.chat_stream('alpha'))[-1]['mode'], 'extracts')
