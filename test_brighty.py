import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import brighty
from brighty import Controller, displays
from display_api import DisplayAPI

BUILTIN = dict(id='internal', system_id=1, builtin=True, external=False, enabled=True, origin=[0, 0])
LG = dict(id='lg', system_id=3, builtin=False, external=True, enabled=True, origin=[-2560, -458])


class SwitchTests(unittest.TestCase):
    def test_after_on_runs_after_layout_and_retries_for_already_active(self):
        self.control.act('off')
        def sync(target):
            self.assertEqual(target, 'lg')
            self.assertFalse(json.loads(self.path.read_text())['layout_pending'])
            self.assertTrue(any(s['id'] == 'lg' for s in self.screens))
            return ' synced'
        self.control.after_on = Mock(side_effect=sync)
        self.assertIn('synced', self.control.act('toggle'))
        self.control.after_on.assert_called_once_with('lg')
        self.control.act('on')
        self.assertEqual(self.control.after_on.call_count, 2)
        self.control.act('off')
        self.assertEqual(self.control.after_on.call_count, 2)

    def test_brightness_failure_keeps_monitor_on_and_retry_does_not_reenable(self):
        self.control.act('off')
        self.control.after_on = Mock(side_effect=RuntimeError('DDC unavailable'))
        with self.assertRaisesRegex(RuntimeError, 'display is enabled.*brightness was not synchronized'):
            self.control.act('on')
        self.assertFalse(json.loads(self.path.read_text())['disabled'])
        self.assertTrue(any(s['id'] == 'lg' for s in self.screens))
        calls = list(self.calls)
        self.control.after_on = Mock(return_value=' synced')
        self.control.act('on')
        self.assertEqual(self.calls, calls)
        self.control.after_on.assert_called_once_with('lg')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.screens = [BUILTIN.copy(), LG.copy()]
        self.calls = []
        self.positions = []
        self.control = Controller(lambda: self.screens, self.change, self.path, attempts=1, pause=lambda _: None, set_origins=self.move)

    def move(self, items):
        self.positions.append(items)
        for number, x, y in items:
            for screen in self.screens:
                if screen['system_id'] == number:
                    screen['origin'] = [x, y]

    def change(self, number, enabled):
        self.calls.append((number, enabled))
        self.screens = [BUILTIN.copy()] + ([LG.copy()] if enabled else [])

    def save(self, **extra):
        self.path.write_text(json.dumps(dict(id='lg', disabled=True, **extra)))

    def test_on_already_active_makes_no_api_calls(self):
        self.save()
        self.assertIn('already enabled', self.control.act('on'))
        self.assertEqual(self.calls, [])
        self.assertEqual(json.loads(self.path.read_text())['system_id'], 3)
        self.assertFalse(json.loads(self.path.read_text())['disabled'])

    def test_on_restores_missing_display_by_saved_numeric_id(self):
        self.save(system_id=3)
        self.screens = [BUILTIN.copy()]
        self.control.act('on')
        self.assertEqual(self.calls, [(3, True)])

    def test_off_saves_id_before_mutation(self):
        def change(number, enabled):
            self.assertEqual(json.loads(self.path.read_text())['system_id'], 3)
            self.change(number, enabled)
        self.control.set_enabled = change
        self.control.act('off')
        self.assertEqual(self.calls, [(3, False)])
        self.control.act('on')
        self.assertEqual(self.calls[-1], (3, True))

    def test_toggle_uses_real_state_not_saved_flag(self):
        self.save(system_id=3)
        self.control.act('toggle')
        self.assertEqual(self.calls, [(3, False)])
        self.control.act('toggle')
        self.assertEqual(self.calls[-1], (3, True))

    def test_missing_numeric_id_does_not_guess(self):
        self.save()
        self.screens = [BUILTIN.copy()]
        with self.assertRaisesRegex(RuntimeError, 'No saved system display ID'):
            self.control.act('on')
        self.assertEqual(self.calls, [])

    def test_requires_builtin_for_off(self):
        self.screens = [LG.copy()]
        with self.assertRaisesRegex(RuntimeError, 'lid'):
            self.control.act('off')
        self.assertEqual(self.calls, [])

    def test_never_switches_builtin(self):
        with self.assertRaisesRegex(RuntimeError, 'built-in'):
            self.control.act('off', 'internal')
        self.assertEqual(self.calls, [])

    def test_error_does_not_override_observed_success(self):
        self.save(system_id=3)
        self.screens = [BUILTIN.copy()]
        def change(number, enabled):
            self.change(number, enabled)
            raise RuntimeError('API returned an error')
        self.control.set_enabled = change
        self.assertIn('active', self.control.act('on'))

    def test_success_code_without_observed_change_is_not_success(self):
        self.save(system_id=3)
        self.screens = [BUILTIN.copy()]
        self.control.set_enabled = lambda *_: None
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            self.control.act('on')

    def test_no_access_is_not_off_success(self):
        self.screens = []
        with self.assertRaisesRegex(RuntimeError, 'did not return'):
            self.control.act('off')
        self.assertEqual(self.calls, [])

    def test_id_reuse_rejected(self):
        self.save(system_id=1)
        self.screens = [BUILTIN.copy()]
        with self.assertRaisesRegex(RuntimeError, 'display ID changed'):
            self.control.act('on')
        self.assertEqual(self.calls, [])

    def test_parse_contextual_id(self):
        self.assertEqual(displays('Persistent screen id: lg\nContextual screen id: 3\nType: 27 inch external screen\nOrigin: (-2560,-458)\nEnabled: true\n')[0], LG)

    def test_restores_left_position_after_on_using_new_numeric_id(self):
        self.control.act('off')
        state = json.loads(self.path.read_text())
        self.assertEqual(state['layout']['lg'], [-2560, -458])
        def change(number, enabled):
            self.change(number, enabled)
            self.screens[1].update(system_id=9, origin=[1512, 0])
        self.control.set_enabled = change
        self.control.act('on')
        self.assertEqual(self.screens[1]['origin'], [-2560, -458])
        self.assertIn((9, -2560, -458), self.positions[0])
        self.assertFalse(json.loads(self.path.read_text())['layout_pending'])

    def test_retry_on_restores_pending_layout_without_reenabling(self):
        self.control.act('off')
        self.screens = [BUILTIN.copy(), dict(LG, origin=[1512, 0])]
        self.calls.clear()
        self.control.act('on')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.screens[1]['origin'], [-2560, -458])

    def test_layout_failure_keeps_snapshot_for_retry(self):
        self.control.act('off')
        self.screens = [BUILTIN.copy(), dict(LG, origin=[1512, 0])]
        self.control.set_origins = lambda _: None
        with self.assertRaisesRegex(RuntimeError, 'coordinates do not match'):
            self.control.act('on')
        self.assertTrue(json.loads(self.path.read_text())['layout_pending'])

    def test_changed_display_set_does_not_apply_partial_layout(self):
        self.control.act('off')
        self.screens = [BUILTIN.copy(), LG.copy(), dict(LG, id='other', system_id=7)]
        with self.assertRaisesRegex(RuntimeError, 'set of displays changed'):
            self.control.act('on')
        self.assertEqual(self.positions, [])

    def test_save_layout_and_idempotent_on_preserve_snapshot(self):
        self.control.act('save-layout')
        self.control.act('on')
        self.assertEqual(json.loads(self.path.read_text())['layout']['lg'], [-2560, -458])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.positions, [])

    def test_missing_coordinates_refuse_off_before_mutation(self):
        self.screens[1]['origin'] = None
        with self.assertRaisesRegex(RuntimeError, 'coordinates'):
            self.control.act('off')
        self.assertEqual(self.calls, [])

    def test_position_api_commits_for_session_not_process_lifetime(self):
        api = DisplayAPI.__new__(DisplayAPI)
        api.cg = Mock()
        api.cg.CGBeginDisplayConfiguration.return_value = 0
        api.cg.CGConfigureDisplayOrigin.return_value = 0
        api.cg.CGCompleteDisplayConfiguration.return_value = 0
        api.set_origins([(1, 0, 0), (3, -2560, -458)])
        self.assertEqual(api.cg.CGCompleteDisplayConfiguration.call_args.args[1], 1)
        self.assertEqual(api.cg.CGConfigureDisplayOrigin.call_args.args[1:], (3, -2560, -458))

    def test_position_api_cancels_transaction_on_error(self):
        api = DisplayAPI.__new__(DisplayAPI)
        api.cg = Mock()
        api.cg.CGBeginDisplayConfiguration.return_value = 0
        api.cg.CGConfigureDisplayOrigin.return_value = 1001
        with self.assertRaises(RuntimeError):
            api.set_origins([(3, -2560, -458)])
        api.cg.CGCancelDisplayConfiguration.assert_called_once()
        api.cg.CGCompleteDisplayConfiguration.assert_not_called()

    def test_on_retries_enable_after_macos_failure(self):
        self.control.act('off')
        failures = [RuntimeError('macOS: applying configuration for display 3, code 1001.')]
        original = self.change
        def flaky(number, enabled):
            if failures:
                self.calls.append((number, enabled))
                raise failures.pop()
            original(number, enabled)
        self.control.set_enabled = flaky
        self.assertIn('active', self.control.act('on'))
        self.assertEqual(self.calls[-2:], [(3, True), (3, True)])
        self.assertEqual(self.control.event, 'on')

    def test_on_gives_up_after_bounded_enable_attempts(self):
        self.control.act('off')
        def broken(number, enabled):
            self.calls.append((number, enabled))
            raise RuntimeError('code 1001')
        self.control.set_enabled = broken
        before = len(self.calls)
        with self.assertRaisesRegex(RuntimeError, 'Enabling was not confirmed'):
            self.control.act('on')
        self.assertEqual(len(self.calls) - before, brighty.ENABLE_ATTEMPTS)

    def test_off_is_never_repeated(self):
        def broken(number, enabled):
            self.calls.append((number, enabled))
            raise RuntimeError('code 1001')
        self.control.set_enabled = broken
        with self.assertRaisesRegex(RuntimeError, 'Disconnection was not confirmed'):
            self.control.act('off')
        self.assertEqual(self.calls, [(3, False)])

    def test_layout_waits_for_late_display_discovery(self):
        self.control.act('off')
        self.control.attempts = 3
        reads = iter([[BUILTIN.copy()]])
        original = self.control.read
        self.control.read = lambda: next(reads, None) or original()
        state = json.loads(self.path.read_text())
        self.screens = [BUILTIN.copy(), LG.copy()]
        self.assertIn('restored', self.control.restore_layout(state))

    def test_notification_summaries(self):
        on = brighty.notification('on', 'The external display is active in macOS. Display layout restored. '
                                        'LG brightness synchronized with MacBook: 54.0%. Check the image on LG.')
        self.assertEqual(on.title, 'External display on')
        self.assertEqual(on.body, 'Layout restored. LG brightness set to 54.0% to match the MacBook.')
        self.assertEqual(brighty.notification('off', 'x').title, 'External display off')

if __name__ == '__main__':
    unittest.main()
