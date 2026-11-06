import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import service_control as control


class SafeServiceControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(control, 'RUNTIME', self.base))
        self.stack.enter_context(patch.object(control, 'PID_FILE', self.base / '.pid'))
        self.record = {'pid':12345, 'port':8787, 'born':'123', 'instance':'a' * 32}

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def test_legacy_pid_is_never_used_to_signal_a_process(self):
        control.PID_FILE.write_text('12345')
        with patch.object(control.os, 'kill') as signal, self.assertRaises(ValueError):
            control.stop()
        signal.assert_not_called()
        self.assertEqual(control.PID_FILE.read_text(), '12345')

    def test_reused_or_mismatched_pid_is_not_stopped(self):
        control.write_record(self.record)
        with patch.object(control, 'identity', return_value='different-birth-time'), \
                patch.object(control.os, 'kill') as signal, self.assertRaises(ValueError):
            control.stop()
        signal.assert_not_called()
        self.assertTrue(control.PID_FILE.exists())

    def test_stale_record_is_not_silently_overwritten_on_start(self):
        control.write_record(self.record)
        with patch.object(control, 'identity', return_value=None), \
                patch.object(control.subprocess, 'Popen') as launch, self.assertRaises(ValueError):
            control.start()
        launch.assert_not_called()
        self.assertEqual(json.loads(control.PID_FILE.read_text()), self.record)

    def test_existing_healthy_process_is_not_started_twice(self):
        control.write_record(self.record)
        with patch.object(control, 'identity', return_value='123'), patch.object(control, 'healthy', return_value=True), \
                patch.object(control.subprocess, 'Popen') as launch:
            result = control.start()
        self.assertEqual(result['pid'], self.record['pid'])
        launch.assert_not_called()

    def test_unhealthy_process_is_not_reported_ready_or_duplicated(self):
        control.write_record(self.record)
        with patch.object(control, 'identity', return_value='123'), patch.object(control, 'healthy', return_value=False):
            self.assertEqual(control.status()['status'], 'starting_or_unhealthy')
            with self.assertRaises(ValueError):
                control.start()

    def test_stop_only_signals_verified_process_and_removes_its_record(self):
        control.write_record(self.record)
        with patch.object(control, 'identity', side_effect=['123', '123', None]), \
                patch.object(control, 'open_pidfd', return_value=9), patch.object(control.os, 'close'), \
                patch.object(control, 'send_pidfd') as signal:
            self.assertEqual(control.stop()['status'], 'stopped')
        signal.assert_called_once_with(9)
        self.assertFalse(control.PID_FILE.exists())

    def test_process_identity_rejects_self_or_unrelated_command(self):
        import os
        self.assertIsNone(control.identity(os.getpid(), 8787))
        self.assertIsNone(control.identity(1, 8787))
        self.assertIsNone(control.identity(-3, 8787))

    def test_identity_change_after_pidfd_open_prevents_signaling(self):
        with patch.object(control, 'open_pidfd', return_value=9), patch.object(control.os, 'close') as close, \
                patch.object(control, 'same_process', return_value=False), \
                patch.object(control, 'send_pidfd') as signal, self.assertRaises(ValueError):
            control.signal_verified(self.record)
        signal.assert_not_called()
        close.assert_called_once_with(9)
