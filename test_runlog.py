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


if __name__ == '__main__':
    unittest.main()
