#!/usr/bin/env python3
"""Hardware brightness for available screens and LG synchronization after on."""
import argparse
import ctypes as C
import ctypes.util
from contextlib import contextmanager
import fcntl
import json
import math
from pathlib import Path
import subprocess
import time

from brighty import read_screens, STATE

ROOT = Path(__file__).resolve().parent
DDC = '/opt/homebrew/bin/m1ddc'
# A single DDC/CI request occasionally fails, notably right after a write or
# while the monitor wakes; repeat it a few times before failing the command.
DDC_ATTEMPTS = 3
DDC_RETRY_PAUSE = 0.3
# After on, the monitor needs several seconds before it answers DDC requests.
SYNC_ATTEMPTS = 8
SYNC_RETRY_PAUSE = 1.0


def target_level(current):
    if not math.isfinite(current) or not 0 <= current <= 1:
        raise RuntimeError('Invalid current brightness.')
    return 1.0 if current < 0.75 else 0.5


class Builtin:
    def __init__(self, number):
        self.number = number
        self.api = C.CDLL('/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices')
        self.api.DisplayServicesGetBrightness.argtypes = [C.c_uint32, C.POINTER(C.c_float)]
        self.api.DisplayServicesGetBrightness.restype = C.c_int
        self.api.DisplayServicesSetBrightness.argtypes = [C.c_uint32, C.c_float]
        self.api.DisplayServicesSetBrightness.restype = C.c_int

    def get(self):
        value = C.c_float()
        rc = self.api.DisplayServicesGetBrightness(self.number, C.byref(value))
        if rc:
            raise RuntimeError(f'Could not read MacBook brightness: code {rc}.')
        if not math.isfinite(value.value) or not 0 <= value.value <= 1:
            raise RuntimeError('macOS returned an invalid MacBook brightness value.')
        return value.value

    def set(self, value):
        rc = self.api.DisplayServicesSetBrightness(self.number, value)
        if rc:
            raise RuntimeError(f'Could not set MacBook brightness: code {rc}.')

    def quantize(self, value):
        return value


class External:
    def __init__(self, uid):
        self.uid = uid
        self.maximum = self.read_maximum()

    def read_maximum(self):
        # The tested LG occasionally answers 8224 (0x2020, two ASCII spaces)
        # instead of its real maximum. Accept only two equal consecutive reads.
        values = []
        for attempt in range(DDC_ATTEMPTS + 1):
            if attempt:
                time.sleep(DDC_RETRY_PAUSE)
            value = self.command('max', 'luminance')
            if value > 0 and values and values[-1] == value:
                return value
            values.append(value)
        raise RuntimeError(f'DDC returned an inconsistent maximum brightness: {values}.')

    def command(self, *args):
        # Timeouts are not retried: each one already costs 8 seconds.
        for attempt in range(DDC_ATTEMPTS):
            if attempt:
                time.sleep(DDC_RETRY_PAUSE)
            process = subprocess.run([DDC, 'display', self.uid, *map(str, args)],
                                     text=True, capture_output=True, timeout=8)
            if process.returncode:
                error = f'DDC LG: {(process.stderr or process.stdout).strip()}'
                continue
            if args[0] == 'set':
                return
            try:
                return int(process.stdout.strip())
            except ValueError:
                error = f'Invalid DDC response: {process.stdout.strip()!r}'
        raise RuntimeError(f'{error} ({DDC_ATTEMPTS} attempts)')

    def get(self):
        # Out-of-range answers are transient garbage (see read_maximum); re-read.
        values = []
        for attempt in range(DDC_ATTEMPTS):
            if attempt:
                time.sleep(DDC_RETRY_PAUSE)
            raw = self.command('get', 'luminance')
            if 0 <= raw <= self.maximum:
                return raw / self.maximum
            values.append(raw)
        raise RuntimeError(f'DDC returned out-of-range brightness values {values} (maximum {self.maximum}).')

    def quantize(self, value):
        return int(value * self.maximum + 0.5) / self.maximum

    def set(self, value):
        self.command('set', 'luminance', int(value * self.maximum + 0.5))


def verify(device, expected):
    for _ in range(8):
        actual = device.get()
        if abs(actual - expected) <= 0.005:
            return actual
        time.sleep(0.15)
    raise RuntimeError(f'Brightness verification failed: expected {expected:.1%}, received {actual:.1%}.')


def apply(devices, level):
    """Preflight all reads, verify writes, best-effort rollback on failure."""
    previous = {name: device.get() for name, device in devices.items()}
    attempted = []
    try:
        for name, device in devices.items():
            attempted.append(name)
            device.set(level)
            verify(device, device.quantize(level))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        failures = []
        for name in reversed(attempted):
            try:
                device = devices[name]
                device.set(previous[name])
                verify(device, device.quantize(previous[name]))
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as rollback_error:
                failures.append(f'{name}: {rollback_error}')
        detail = (' Rollback failed: ' + '; '.join(failures)) if failures else ' Original brightness restored.'
        raise RuntimeError(str(error) + detail) from error
    return {name: device.get() for name, device in devices.items()}


def devices_for_screens(screens, target=None):
    """Accept the MacBook alone; never control an unknown external display."""
    builtin = [s for s in screens if s['builtin']]
    external = [s for s in screens if s['external']]
    if not screens or len(builtin) > 1 or len(external) > 1 or len(screens) != len(builtin) + len(external):
        raise RuntimeError('A MacBook and/or one saved Brighty external display is required. Brightness was not changed.')
    if external:
        if target is None:
            saved = json.loads(STATE.read_text()) if STATE.exists() else {}
            target = saved.get('id')
        if external[0]['id'] != target:
            raise RuntimeError('The external display does not match the saved Brighty display. Brightness was not changed.')
    devices = {}
    if external:
        devices['LG'] = External(external[0]['id'])
    if builtin:
        devices['MacBook'] = Builtin(builtin[0]['system_id'])
    return devices


def available_screens():
    # displayplacer Enabled follows CGDisplayIsActive, which is false during
    # display sleep too. Online distinguishes sleep from software disconnect.
    screens = read_screens()
    cg = C.CDLL(ctypes.util.find_library('ApplicationServices'))
    cg.CGDisplayIsOnline.argtypes = [C.c_uint32]
    cg.CGDisplayIsOnline.restype = C.c_bool
    return [s for s in screens if cg.CGDisplayIsOnline(s['system_id'])]


def connect():
    screens = available_screens()
    devices = devices_for_screens(screens)
    cg = C.CDLL(ctypes.util.find_library('ApplicationServices'))
    cg.CGMainDisplayID.restype = C.c_uint32
    main_id = cg.CGMainDisplayID()
    main = next((s for s in screens if s['system_id'] == main_id), None)
    if main is None:
        raise RuntimeError('Could not identify the main macOS display.')
    return devices, 'MacBook' if main['builtin'] else 'LG'


@contextmanager
def brightness_lock(wait=0):
    with (ROOT / '.brightness.lock').open('a') as lock:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('The previous brightness change is still running.') from None
                time.sleep(0.1)
        yield


def sync_external(target=None):
    """After on, copy the MacBook's live brightness to LG without toggling."""
    with brightness_lock(wait=5):
        for attempt in range(SYNC_ATTEMPTS):
            try:
                screens = available_screens()
                devices = devices_for_screens(screens, target)
                if 'LG' not in devices:
                    raise RuntimeError('LG has not appeared among the available displays yet.')
                if 'MacBook' not in devices:
                    return ' MacBook is not available; LG brightness was left unchanged.'
                level = devices['MacBook'].get()
                apply({'LG': devices['LG']}, level)
                return f' LG brightness synchronized with MacBook: {level:.1%}.'
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                if attempt == SYNC_ATTEMPTS - 1:
                    raise
                time.sleep(SYNC_RETRY_PAUSE)


def main():
    parser = argparse.ArgumentParser(description='Hardware display brightness: 50% ↔ 100%.')
    parser.add_argument('action', choices=['status', 'half', 'max', 'toggle', 'sync'])
    args = parser.parse_args()
    from runlog import Report
    if args.action == 'sync':
        text = sync_external().strip()
        return Report(text, 'Brightness synchronized', text)
    # Nonblocking process lock: repeated hotkeys never queue extra toggles.
    with brightness_lock():
        devices, main_name = connect()
        current = {name: device.get() for name, device in devices.items()}
        if args.action == 'status':
            return json.dumps({'main': main_name, 'brightness': current}, ensure_ascii=False)
        level = target_level(current[main_name]) if args.action == 'toggle' else {'half': 0.5, 'max': 1.0}[args.action]
        result = apply(devices, level)
        text = (f'Main display: {main_name}, previously {current[main_name]:.1%}. '
                + ' '.join(f'{name}: {value:.1%}.' for name, value in result.items()))
        body = ', '.join(f'{name} {value:.0%}' for name, value in result.items())
        if 'LG' not in result:
            body += ' (external display off)'
        return Report(text, f'Brightness {level:.0%}', f'{body}. Was {current[main_name]:.0%} on {main_name}.')


if __name__ == '__main__':
    from runlog import run
    run('brightness', main, (RuntimeError, OSError, ValueError, AttributeError, subprocess.TimeoutExpired))
