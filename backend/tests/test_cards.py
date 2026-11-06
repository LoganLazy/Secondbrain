from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import cards, config, db


class FlashcardReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.stack = ExitStack()
        for key, value in {'DATA_DIR':self.base, 'UPLOAD_DIR':self.base, 'INBOX_DIR':self.base / 'inbox'}.items():
            self.stack.enter_context(patch.object(config, key, value))
        self.pending = self.base / 'pending.json'
        self.stack.enter_context(patch.object(cards, 'pending_path', return_value=self.pending))
        self.stack.enter_context(patch.object(cards.db, 'now', return_value=1720000000))
        self.old_conn, db._conn = db._conn, None
        self.source = self.base / 'manual.txt'
        self.source.write_text('alpha original evidence for questions and answers')
        db.get().execute('INSERT INTO docs(id,title,filename,file_hash,file_path,kb_id) VALUES(?,?,?,?,?,?)',
                         (1,'Manual','manual.txt','h1',str(self.source),'work'))
        db.get().commit()
        self.stack.enter_context(patch.object(config, 'SETTINGS', {**config.DEFAULTS,
            'FC_INTERVALS':'0,1,2,4,7', 'FC_MASTER_BOX':3, 'NET_MODE':'offline'}))

    def tearDown(self):
        if db._conn is not None:
            db._conn.close()
        db._conn = self.old_conn
        self.stack.close()
        self.temp.cleanup()

    def add(self, question='question', source_hash='h1', doc_id=1):
        cursor = db.get().execute('INSERT INTO flashcards(doc_id,q,a,created,kb_id,source_hash) VALUES(?,?,?,?,?,?)',
                                  (doc_id, question, 'answer', db.now(), 'work', source_hash))
        db.get().commit()
        return cursor.lastrowid

    def count(self):
        return db.get().execute('SELECT COUNT(*) FROM flashcards').fetchone()[0]

    def test_generation_limits_requested_count_and_records_source_version(self):
        raw = json.dumps([{'q':f'question {i}', 'a':'answer'} for i in range(12)])
        with patch.object(cards.ingest, 'call_chat', return_value=raw):
            self.assertEqual(cards.generate(1, 6, 'work'), 6)
        self.assertEqual(self.count(), 6)
        self.assertTrue(all(card['source_hash'] == 'h1' for card in cards.list_cards(kb_id='work')))

    def test_duplicate_questions_are_normalized_per_source_version(self):
        self.add(' What   is Alpha? ')
        self.add('new question', source_hash='old-version')
        raw = json.dumps([{'q':'what is alpha?', 'a':'answer'}, {'q':'new question', 'a':'new answer'},
                          {'q':' NEW   QUESTION ', 'a':'duplicate'}])
        with patch.object(cards.ingest, 'call_chat', return_value=raw):
            self.assertEqual(cards.generate(1, 6, 'work'), 1)
        self.assertEqual(self.count(), 3)

    def test_malformed_and_oversized_candidates_do_not_create_bad_cards(self):
        for raw in ('not json', '{}', '[{"q":true,"a":"answer"}]',
                    json.dumps([{'q':'x' * 501,'a':'answer'}]), '[]'):
            with self.subTest(raw=raw), patch.object(cards.ingest, 'call_chat', return_value=raw), self.assertRaises(ValueError):
                cards.generate(1, 6, 'work')
        self.assertEqual(self.count(), 0)

    def test_source_change_during_generation_discards_result(self):
        def change(messages, **kwargs):
            db.get().execute("UPDATE docs SET file_hash='h2' WHERE id=1")
            db.get().commit()
            return '[{"q":"question","a":"answer"}]'
        with patch.object(cards.ingest, 'call_chat', side_effect=change), self.assertRaises(cards.CardConflict):
            cards.generate(1, 6, 'work')
        self.assertEqual(self.count(), 0)

    def test_source_deletion_during_generation_does_not_create_orphan(self):
        def remove(messages, **kwargs):
            db.get().execute('DELETE FROM docs WHERE id=1'); db.get().commit()
            return '[{"q":"question","a":"answer"}]'
        with patch.object(cards.ingest, 'call_chat', side_effect=remove), self.assertRaises(cards.CardConflict):
            cards.generate(1, 6, 'work')
        self.assertEqual(self.count(), 0)

    def test_invalid_count_and_foreign_kb_do_not_call_model(self):
        with patch.object(cards.ingest, 'call_chat') as model:
            for count in (0, 21, True):
                with self.assertRaises(ValueError):
                    cards.generate(1, count, 'work')
            with self.assertRaises(ValueError):
                cards.generate(1, 6, 'private')
        model.assert_not_called()

    def test_empty_source_is_rejected_before_model_and_long_source_is_bounded(self):
        self.source.write_text('   ')
        with patch.object(cards.ingest, 'call_chat') as model, self.assertRaises(ValueError):
            cards.generate(1, 6, 'work')
        model.assert_not_called()
        self.source.write_text('x' * 10000 + 'excludedmarker')
        with patch.object(cards.ingest, 'call_chat', return_value='[{"q":"question","a":"answer"}]') as model:
            cards.generate(1, 6, 'work')
        self.assertNotIn('excludedmarker', str(model.call_args))

    def test_source_states_pause_changed_or_missing_but_preserve_legacy(self):
        self.add('current')
        self.add('changed', source_hash='old')
        self.add('missing', doc_id=99)
        self.add('legacy', source_hash='')
        states = {card['q']:card['source_state'] for card in cards.list_cards(kb_id='work')}
        self.assertEqual(states, {'current':'current','changed':'changed','missing':'missing','legacy':'unverified'})
        self.assertEqual({card['q'] for card in cards.due_queue('work')}, {'current','legacy'})
        self.assertEqual(cards.stats('work')['paused'], 2)
        self.assertEqual(cards.stats('work')['unverified'], 1)
        self.assertEqual(self.count(), 4)

    def test_correct_fuzzy_wrong_and_explicit_statistics(self):
        card_id = self.add()
        first = cards.answer(card_id, 'correct', 'work', 0)
        self.assertEqual(first['box'], 1)
        self.assertEqual(first['next_due'], db.now() + 86400)
        self.assertEqual(cards.due_queue('work'), [])
        second = cards.answer(card_id, 'fuzzy', 'work', 1)
        self.assertEqual(second['box'], 1)
        third = cards.answer(card_id, 'wrong', 'work', 2)
        self.assertEqual(third['box'], 0)
        self.assertEqual(cards.stats('work')['accuracy'], 67)
        self.assertEqual(cards.stats('work')['reviews'], 3)

    def test_duplicate_or_concurrent_submission_counts_only_once(self):
        card_id = self.add()
        def submit():
            try:
                cards.answer(card_id, 'correct', 'work', 0)
                return 'ok'
            except cards.CardConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _:submit(), range(2)))
        self.assertCountEqual(results, ['ok','conflict'])
        self.assertEqual(cards.stats('work')['reviews'], 1)

    def test_changed_missing_or_invalid_review_does_not_change_progress(self):
        changed = self.add('changed', source_hash='old')
        missing = self.add('missing', doc_id=99)
        current = self.add('current')
        for card_id in (changed, missing):
            with self.assertRaises(cards.CardConflict):
                cards.answer(card_id, 'correct', 'work', 0)
        with self.assertRaises(ValueError):
            cards.answer(current, 'invalid', 'work', 0)
        with self.assertRaises(ValueError):
            cards.answer(current, 'correct', 'private', 0)
        self.assertEqual(cards.stats('work')['reviews'], 0)

    def test_pending_restore_blocks_generation_review_and_deletion(self):
        card_id = self.add()
        self.pending.touch()
        for operation in (lambda:cards.generate(1, 6, 'work'),
                          lambda:cards.answer(card_id, 'correct', 'work', 0),
                          lambda:cards.delete(card_id, 'work')):
            with self.assertRaises(BlockingIOError):
                operation()
        self.assertEqual(self.count(), 1)

    def test_legacy_review_remains_explicitly_unverified(self):
        card_id = self.add(source_hash='')
        cards.answer(card_id, 'correct', 'work', 0)
        card = cards.list_cards(kb_id='work')[0]
        self.assertEqual(card['reviews'], 1)
        self.assertEqual(card['source_state'], 'unverified')
        self.assertEqual(card['source_hash'], '')

    def test_cross_kb_source_metadata_is_not_exposed(self):
        db.get().execute('INSERT INTO docs(id,title,filename,file_hash,kb_id) VALUES(?,?,?,?,?)',
                         (2,'private secret','private.txt','h2','private'))
        db.get().commit()
        self.add('mismatched card', source_hash='h2', doc_id=2)
        card = cards.list_cards(kb_id='work')[0]
        self.assertEqual(card['source_state'], 'missing')
        self.assertIsNone(card['source_title'])
        self.assertIsNone(card['source_filename'])
