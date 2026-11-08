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
import sys
import time

from brighty import read_screens, STATE

ROOT = Path(__file__).resolve().parent
DDC = '/opt/homebrew/bin/m1ddc'


def target_level(current):
    if not math.isfinite(current) or not 0 <= current <= 1:
        raise RuntimeError('Некорректная текущая яркость.')
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
            raise RuntimeError(f'Не удалось прочитать яркость MacBook: код {rc}.')
        if not math.isfinite(value.value) or not 0 <= value.value <= 1:
            raise RuntimeError('macOS вернула некорректную яркость MacBook.')
        return value.value

    def set(self, value):
        rc = self.api.DisplayServicesSetBrightness(self.number, value)
        if rc:
            raise RuntimeError(f'Не удалось изменить яркость MacBook: код {rc}.')

    def quantize(self, value):
        return value


class External:
    def __init__(self, uid):
        self.uid = uid
        self.maximum = self.command('max', 'luminance')
        if self.maximum <= 0:
            raise RuntimeError('DDC вернул некорректный максимум яркости.')

    def command(self, *args):
        process = subprocess.run([DDC, 'display', self.uid, *map(str, args)],
                                 text=True, capture_output=True, timeout=8)
        if process.returncode:
            raise RuntimeError(f'DDC LG: {(process.stderr or process.stdout).strip()}')
        if args[0] == 'set':
            return
        try:
            return int(process.stdout.strip())
        except ValueError:
            raise RuntimeError(f'Некорректный ответ DDC: {process.stdout.strip()!r}') from None

    def get(self):
        raw = self.command('get', 'luminance')
        if not 0 <= raw <= self.maximum:
            raise RuntimeError('DDC вернул яркость вне диапазона.')
        return raw / self.maximum

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
    raise RuntimeError(f'Яркость не подтверждена: ожидалось {expected:.1%}, получено {actual:.1%}.')


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
        detail = (' Ошибка возврата: ' + '; '.join(failures)) if failures else ' Исходная яркость восстановлена.'
        raise RuntimeError(str(error) + detail) from error
    return {name: device.get() for name, device in devices.items()}


def devices_for_screens(screens, target=None):
    """Accept the MacBook alone; never control an unknown external display."""
    builtin = [s for s in screens if s['builtin']]
    external = [s for s in screens if s['external']]
    if not screens or len(builtin) > 1 or len(external) > 1 or len(screens) != len(builtin) + len(external):
        raise RuntimeError('Нужен MacBook и/или один сохранённый внешний экран Brighty. Яркость не изменена.')
    if external:
        if target is None:
            saved = json.loads(STATE.read_text()) if STATE.exists() else {}
            target = saved.get('id')
        if external[0]['id'] != target:
            raise RuntimeError('Внешний экран не совпадает с сохранённым экраном Brighty. Яркость не изменена.')
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
        raise RuntimeError('Не удалось определить главный экран macOS.')
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
                    raise RuntimeError('Предыдущее переключение яркости ещё выполняется.') from None
                time.sleep(0.1)
        yield


def sync_external(target=None):
    """After on, copy the MacBook's live brightness to LG without toggling."""
    with brightness_lock(wait=5):
        for attempt in range(3):
            try:
                screens = available_screens()
                devices = devices_for_screens(screens, target)
                if 'LG' not in devices:
                    raise RuntimeError('LG ещё не появился среди активных экранов.')
                if 'MacBook' not in devices:
                    return ' MacBook не активен; яркость LG оставлена без изменений.'
                level = devices['MacBook'].get()
                apply({'LG': devices['LG']}, level)
                return f' Яркость LG синхронизирована с MacBook: {level:.1%}.'
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                if attempt == 2:
                    raise
                time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description='Аппаратная яркость обоих экранов: 50% ↔ 100%.')
    parser.add_argument('action', choices=['status', 'half', 'max', 'toggle', 'sync'])
    args = parser.parse_args()
    if args.action == 'sync':
        print(sync_external().strip())
        return
    # Nonblocking process lock: repeated hotkeys never queue extra toggles.
    with brightness_lock():
        devices, main_name = connect()
        current = {name: device.get() for name, device in devices.items()}
        if args.action == 'status':
            print(json.dumps({'main': main_name, 'brightness': current}, ensure_ascii=False))
            return
        level = target_level(current[main_name]) if args.action == 'toggle' else {'half': 0.5, 'max': 1.0}[args.action]
        result = apply(devices, level)
        print(f'Главный экран: {main_name}, было {current[main_name]:.1%}. '
              + ' '.join(f'{name}: {value:.1%}.' for name, value in result.items()))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, AttributeError, subprocess.TimeoutExpired) as error:
        sys.exit(str(error))
