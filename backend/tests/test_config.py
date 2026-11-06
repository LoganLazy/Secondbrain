import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app import config


class ConfigurationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.file = self.base / 'settings.json'
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, 'SETTINGS_FILE', self.file))
        self.stack.enter_context(patch.object(config, 'SETTINGS', {**config.DEFAULTS, 'DEEPSEEK_KEY':'', 'ZHIPU_KEY':''}))
        self.stack.enter_context(patch.object(config, 'WARNINGS', []))
        self.stack.enter_context(patch('app.restore.pending_path', return_value=self.base / 'pending.json'))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def test_numeric_legacy_values_are_normalized_and_all_fields_round_trip(self):
        config.save({'FC_MASTER_BOX':'3', 'FC_INTERVALS':'0, 1, 3, 7, 10', 'NET_MODE':'offline'})
        self.assertEqual(config.get('FC_MASTER_BOX'), 3)
        self.assertEqual(config.get('FC_INTERVALS'), '0,1,3,7,10')
        self.assertEqual(config.get('NET_MODE'), 'offline')
        self.assertIs(type(json.loads(self.file.read_text())['FC_MASTER_BOX']), int)

    def test_invalid_values_and_combinations_do_not_modify_saved_configuration(self):
        config.save({'CHAT_MODEL':'saved-model'})
        before = self.file.read_bytes()
        for value in [{'TOP_K':0}, {'TOP_K':True}, {'FC_MASTER_BOX':'4.5'},
                      {'CHUNK_SIZE':64, 'CHUNK_OVERLAP':64}, {'NET_MODE':'invalid'},
                      {'CHAT_MODEL':''}, {'FC_INTERVALS':'0,3,1'}, {'FC_INTERVALS':'0,1'},
                      {'CHAT_BASE_URL':'https://user:password@example.test/v1'},
                      {'CHAT_BASE_URL':'https://example.test/v1?key=secret'},
                      {'CHAT_BASE_URL':'file:///etc/passwd'}, {'CHAT_BASE_URL':'http://localhost:99999'},
                      {'ZHIPU_KEY':'line\nsecret'}, {'UNKNOWN':'value'}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.save(value)
            self.assertEqual(self.file.read_bytes(), before)
            self.assertEqual(config.get('CHAT_MODEL'), 'saved-model')

    def test_local_model_urls_and_blank_keys_are_supported(self):
        config.save({'CHAT_BASE_URL':'http://127.0.0.1:11434/v1/', 'DEEPSEEK_KEY':'saved-secret'})
        config.save({'DEEPSEEK_KEY':'', 'CHAT_MODEL':'local-model'})
        self.assertEqual(config.get('CHAT_BASE_URL'), 'http://127.0.0.1:11434/v1')
        self.assertEqual(config.get('DEEPSEEK_KEY'), 'saved-secret')

    def test_corrupt_settings_do_not_crash_reload_or_get_overwritten(self):
        for value in ('{broken', '[]'):
            self.file.write_text(value)
            config.reload()
            self.assertTrue(config.WARNINGS)
            self.assertEqual(config.get('NET_MODE'), 'offline')
            with self.assertRaises(ValueError):
                config.save({'CHAT_MODEL':'new'})
            self.assertEqual(self.file.read_text(), value)

    def test_invalid_startup_values_fall_back_with_redacted_warnings(self):
        self.file.write_text(json.dumps({'CHAT_BASE_URL':'https://user:secret@example.test',
                                         'CHUNK_SIZE':64, 'CHUNK_OVERLAP':80, 'NET_MODE':'invalid'}))
        config.reload()
        self.assertEqual(config.get('CHAT_BASE_URL'), config.DEFAULTS['CHAT_BASE_URL'])
        self.assertEqual(config.get('CHUNK_SIZE'), config.DEFAULTS['CHUNK_SIZE'])
        self.assertEqual(config.get('NET_MODE'), 'offline')
        self.assertTrue(config.WARNINGS)
        self.assertNotIn('secret', str(config.WARNINGS))

    def test_atomic_replace_failure_preserves_file_and_runtime_snapshot(self):
        config.save({'CHAT_MODEL':'before'})
        before = self.file.read_bytes()
        with patch.object(config.os, 'replace', side_effect=OSError('disk full')), self.assertRaises(OSError):
            config.save({'CHAT_MODEL':'after'})
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(config.get('CHAT_MODEL'), 'before')
        self.assertEqual(list(self.base.glob('.settings-*')), [])

    def test_saved_keys_are_private_and_not_injected_into_environment(self):
        config.save({'DEEPSEEK_KEY':'test-secret'})
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertNotIn('DEEPSEEK_KEY', os.environ)

    def test_pending_restore_blocks_configuration_changes(self):
        (self.base / 'pending.json').touch()
        with self.assertRaises(BlockingIOError):
            config.save({'CHAT_MODEL':'blocked'})
        self.assertFalse(self.file.exists())

    def test_saved_settings_take_precedence_over_environment(self):
        os.environ['NET_MODE'] = 'online'
        self.file.write_text(json.dumps({'NET_MODE':'offline', 'FC_MASTER_BOX':'3'}))
        config.reload()
        self.assertEqual(config.get('NET_MODE'), 'offline')
        self.assertEqual(config.get('FC_MASTER_BOX'), 3)
