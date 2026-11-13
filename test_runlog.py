from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runlog


class RunLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'run.log'
        patcher = patch.object(runlog, 'LOG', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.real_notify = runlog.notify
        notifier = patch.object(runlog, 'notify')
        self.notify = notifier.start()
        self.addCleanup(notifier.stop)

    def run_cli(self, argv, main):
        with patch('sys.argv', ['script.py', *argv]), patch('builtins.print'):
            runlog.run('brightness', main, (RuntimeError,))

    def test_expected_error_is_logged_and_exits_nonzero(self):
        def fail():
            raise RuntimeError('DDC LG: busy')
        with self.assertRaises(SystemExit) as exit_:
            self.run_cli(['toggle'], fail)
        self.assertEqual(exit_.exception.code, 'DDC LG: busy')
        self.assertIn('brightness toggle', self.path.read_text())
        self.assertIn('ERROR RuntimeError: DDC LG: busy', self.path.read_text())

    def test_success_is_logged_without_list_identifiers(self):
        self.run_cli(['toggle'], lambda: 'LG: 50.0%.')
        self.run_cli(['list'], lambda: 'External: secret-uuid')
        text = self.path.read_text()
        self.assertIn('toggle', text)
        self.assertIn('ok LG: 50.0%.', text)
        self.assertNotIn('secret-uuid', text)

    def test_unexpected_error_is_logged_and_reraised(self):
        def crash():
            raise KeyError('id')
        with self.assertRaises(KeyError):
            self.run_cli(['on'], crash)
        self.assertIn('ERROR KeyError', self.path.read_text())

    def test_large_log_is_trimmed(self):
        self.path.write_text('old line\n' * 40000)
        self.run_cli(['status'], lambda: 'ok')
        self.assertLess(self.path.stat().st_size, runlog.LIMIT)

    def test_every_change_raises_a_notification(self):
        self.run_cli(['toggle'], lambda: runlog.Report('long CLI text', 'Brightness 50%', 'LG 50%, MacBook 50%'))
        self.notify.assert_called_once_with('Brightness 50%', 'LG 50%, MacBook 50%')

    def test_error_raises_an_error_notification(self):
        def fail():
            raise RuntimeError('DDC LG: busy')
        with self.assertRaises(SystemExit):
            self.run_cli(['toggle'], fail)
        self.notify.assert_called_once_with('Brighty error', 'DDC LG: busy', 'brightness toggle')

    def test_diagnostics_do_not_notify(self):
        self.run_cli(['status'], lambda: '{}')
        self.run_cli(['list'], lambda: 'External: secret-uuid')
        self.notify.assert_not_called()

    def test_notification_text_is_passed_as_arguments(self):
        with patch.object(runlog.sys, 'platform', 'darwin'), patch.dict('os.environ', {'BRIGHTY_NOTIFY': '1'}), \
             patch('runlog.subprocess.run') as run:
            self.real_notify('Title "x"', 'Body " & do shell script "y"')
        command = run.call_args.args[0]
        self.assertEqual(command[-3:], ['Title "x"', '', 'Body " & do shell script "y"'])
        self.assertNotIn('do shell script', command[2])

    def test_notifications_can_be_disabled(self):
        with patch.dict('os.environ', {'BRIGHTY_NOTIFY': '0'}), patch('runlog.subprocess.run') as run:
            self.real_notify('Title', 'Body')
        run.assert_not_called()

if __name__ == '__main__':
    unittest.main()
