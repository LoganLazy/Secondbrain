import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app import ingest


class ChatProviderTests(unittest.TestCase):
    def run_stream(self, payloads):
        class Response:
            def raise_for_status(self):
                pass
            def iter_lines(self):
                for payload in payloads:
                    yield 'data: ' + (payload if isinstance(payload, str) else json.dumps(payload))
        @contextmanager
        def stream(*args, **kwargs):
            yield Response()
        with patch.object(ingest.config, 'get', return_value='online'), patch('httpx.stream', side_effect=stream):
            return list(ingest.call_chat_stream([]))

    def test_abrupt_eof_is_not_a_completed_answer(self):
        with self.assertRaisesRegex(ValueError, '完成前中断'):
            self.run_stream([{'choices': [{'delta': {'content': 'partial'}}]}])

    def test_length_limit_is_reported_as_incomplete(self):
        with self.assertRaisesRegex(ValueError, '截断'):
            self.run_stream([{'choices': [{'delta': {'content': 'partial'}, 'finish_reason': 'length'}]}, '[DONE]'])

    def test_normal_stream_with_usage_and_completion(self):
        self.assertEqual(self.run_stream([
            {'choices': [{'delta': {'content': 'answer'}}]},
            {'choices': [], 'usage': {'total_tokens': 8}},
            {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}, '[DONE]']), ['answer'])

    def test_offline_mode_does_not_open_network_connection(self):
        with patch.object(ingest.config, 'get', return_value='offline'), patch('httpx.stream') as network:
            with self.assertRaisesRegex(ValueError, '离线'):
                list(ingest.call_chat_stream([]))
            network.assert_not_called()
