import sqlite3
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app import reader


class ReaderGroundingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE docs(id INTEGER, title TEXT, filename TEXT, kb_id TEXT);
            INSERT INTO docs VALUES(1,'Manual','manual.pdf','work');
            INSERT INTO docs VALUES(2,'Private','secret.pdf','private');
        ''')
        self.pages = [{'page': 1, 'text': 'first page evidence'},
                      {'page': 3, 'text': 'alpha original\nselected passage'}]
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(reader.db, 'get', return_value=self.conn))
        self.read_pages = self.stack.enter_context(patch.object(reader.ingest, 'doc_pages', return_value=self.pages))

    def tearDown(self):
        self.stack.close()
        self.conn.close()

    def test_document_ownership_is_checked_before_reading(self):
        with self.assertRaises(LookupError):
            reader.prepare(2, 'work', 'document')
        self.read_pages.assert_not_called()

    def test_page_scope_uses_only_server_original_on_requested_page(self):
        prepared = reader.prepare(1, 'work', 'page', 3, 'FAKE CLIENT CONTENT')
        self.assertIn('alpha original', prepared['context'])
        self.assertNotIn('first page', prepared['context'])
        self.assertNotIn('FAKE', prepared['context'])
        self.assertEqual(prepared['sources'][0]['page'], 3)

    def test_nonexistent_or_missing_page_is_rejected(self):
        for page in (None, 2, 99):
            with self.subTest(page=page), self.assertRaises(ValueError):
                reader.prepare(1, 'work', 'page', page)

    def test_selected_text_is_verified_and_whitespace_is_normalized(self):
        prepared = reader.prepare(1, 'work', 'selection', 3, 'original selected\n passage')
        self.assertIn('original selected passage', prepared['context'])
        self.assertNotIn('alpha', prepared['context'])
        for passage in ('unrelated invented claim', '', 'first page evidence'):
            with self.subTest(passage=passage), self.assertRaises(ValueError):
                reader.prepare(1, 'work', 'selection', 3, passage)

    def test_document_truncation_is_explicit_and_keeps_correct_sources(self):
        self.read_pages.return_value = [{'page': 1, 'text': 'a' * 10000}, {'page': 3, 'text': 'b' * 10000}]
        prepared = reader.prepare(1, 'work', 'document')
        self.assertTrue(prepared['truncated'])
        self.assertEqual(prepared['used_chars'], 12000)
        self.assertEqual(prepared['total_chars'], 20000)
        self.assertIn('不是完整全文', prepared['notice'])
        self.assertIn('b' * 2000, prepared['context'])
        self.assertNotIn('b' * 2001, prepared['context'])
        self.assertEqual([s['page'] for s in prepared['sources']], [1, 3])

    def test_model_receives_original_context_and_returns_sources(self):
        prepared = reader.prepare(1, 'work', 'page', 3)
        with patch.object(reader.ingest, 'call_chat', return_value='answer [1]') as model:
            result = reader.answer('question', prepared)
        messages = model.call_args.args[0]
        self.assertIn('alpha original', messages[0]['content'])
        self.assertEqual(messages[-1]['content'], 'question')
        self.assertEqual(result['mode'], 'generated')
        self.assertEqual(result['sources'][0]['doc_id'], 1)
        self.assertNotIn('context', result)

    def test_model_failure_returns_labeled_original_extracts_without_secrets(self):
        prepared = reader.prepare(1, 'work', 'page', 3)
        with patch.object(reader.ingest, 'call_chat', side_effect=OSError('secret-api-key')):
            result = reader.answer('question', prepared)
        self.assertEqual(result['mode'], 'extracts')
        self.assertIn('不是 AI 生成的结论', result['answer'])
        self.assertIn('alpha original', result['answer'])
        self.assertNotIn('secret-api-key', str(result))

    def test_empty_scope_or_empty_answer_is_not_a_generated_answer(self):
        prepared = reader.prepare(1, 'work', 'page', 3)
        with patch.object(reader.ingest, 'call_chat', return_value=' '):
            self.assertEqual(reader.answer('question', prepared)['mode'], 'extracts')
        self.read_pages.return_value = [{'page': 1, 'text': '  '}]
        with self.assertRaises(ValueError):
            reader.prepare(1, 'work', 'document')
