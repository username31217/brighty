import unittest
from unittest.mock import patch
from contextlib import nullcontext

from brightness import apply, target_level, External, devices_for_screens, sync_external

BUILTIN = dict(id='internal', system_id=1, builtin=True, external=False)
LG = dict(id='lg', system_id=3, builtin=False, external=True)


class Device:
    def __init__(self, value, fail=False):
        self.value, self.fail = value, fail

    def get(self):
        return self.value

    def quantize(self, value):
        return value

    def set(self, value):
        self.value = value
        if self.fail:
            self.fail = False
            raise RuntimeError('write failed after change')


class BrightnessTests(unittest.TestCase):
    def test_macbook_only_never_opens_ddc(self):
        with patch('brightness.Builtin') as builtin, patch('brightness.External') as external:
            devices = devices_for_screens([BUILTIN])
            self.assertEqual(devices, {'MacBook': builtin.return_value})
            external.assert_not_called()

    def test_single_screen_toggle(self):
        device = Device(0.5)
        for expected in (1, 0.5):
            self.assertEqual(apply({'MacBook': device}, target_level(device.get())), {'MacBook': expected})

    def test_unknown_external_rejected_before_opening_devices(self):
        with patch('brightness.External') as external, patch('brightness.Builtin') as builtin:
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                devices_for_screens([BUILTIN, LG], target='another')
            external.assert_not_called()
            builtin.assert_not_called()

    def test_no_screens_refused(self):
        with self.assertRaises(RuntimeError):
            devices_for_screens([])

    def test_returning_lg_copies_live_macbook_without_toggle(self):
        for level in (0.5, 1, 0.31):
            devices = {'MacBook': Device(level), 'LG': Device(1 - level)}
            with patch('brightness.brightness_lock', return_value=nullcontext()), \
                 patch('brightness.available_screens', return_value=[BUILTIN, LG]), \
                 patch('brightness.devices_for_screens', return_value=devices):
                sync_external('lg')
            self.assertEqual(devices['LG'].get(), level)
            self.assertEqual(devices['MacBook'].get(), level)

    def test_ddc_wakes_later_retry_reads_fresh_brightness(self):
        devices = {'MacBook': Device(0.5), 'LG': Device(1)}
        with patch('brightness.brightness_lock', return_value=nullcontext()), \
             patch('brightness.available_screens', return_value=[BUILTIN, LG]), \
             patch('brightness.devices_for_screens', side_effect=[RuntimeError('DDC waking'), devices]), \
             patch('brightness.time.sleep'):
            sync_external('lg')
        self.assertEqual(devices['LG'].get(), 0.5)

    def test_decision_boundary_and_examples(self):
        for current in (0, 0.1, 0.5, 0.74, 0.749999):
            self.assertEqual(target_level(current), 1)
        for current in (0.75, 0.9, 1):
            self.assertEqual(target_level(current), 0.5)

    def test_invalid_readings(self):
        for current in (-0.1, 1.1, float('nan'), float('inf')):
            with self.assertRaises(RuntimeError):
                target_level(current)

    def test_alternating_and_sync(self):
        devices = {'LG': Device(0.2), 'MacBook': Device(0.9)}
        for expected in (0.5, 1, 0.5):
            apply(devices, target_level(devices['MacBook'].get()))
            self.assertEqual([d.get() for d in devices.values()], [expected] * 2)

    def test_partial_write_restores_both(self):
        devices = {'LG': Device(0.2), 'MacBook': Device(0.9, fail=True)}
        with self.assertRaisesRegex(RuntimeError, 'Original brightness restored'):
            apply(devices, 0.5)
        self.assertEqual([d.get() for d in devices.values()], [0.2, 0.9])

    def test_read_failure_changes_nothing(self):
        devices = {'LG': Device(0.2), 'MacBook': Device(0.9)}
        with patch.object(devices['MacBook'], 'get', side_effect=RuntimeError('read failed')):
            with self.assertRaises(RuntimeError):
                apply(devices, 0.5)
        self.assertEqual(devices['LG'].get(), 0.2)

    def test_actual_ddc_maximum_and_rounding(self):
        device = External.__new__(External)
        device.maximum = 255
        with patch.object(device, 'command', return_value=128) as command:
            self.assertEqual(device.get(), 128 / 255)
            device.set(0.5)
            command.assert_called_with('set', 'luminance', 128)
        self.assertEqual(device.quantize(0.5), 128 / 255)


if __name__ == '__main__':
    unittest.main()
