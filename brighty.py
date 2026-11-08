#!/usr/bin/env python3
"""LG display connection switch; displayplacer is used for discovery only."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

STATE = Path(__file__).resolve().with_name('.brighty-state.json')


def displays(output):
    result = []
    for block in re.split(r'(?=Persistent screen id:)', output):
        uid = re.search(r'^Persistent screen id:\s*(\S+)', block, re.M)
        if not uid:
            continue
        number = re.search(r'^Contextual screen id:\s*(\d+)', block, re.M)
        kind = re.search(r'^Type:\s*(.+)', block, re.M)
        enabled = re.search(r'^Enabled:\s*(true|false)\s*$', block, re.M)
        origin = re.search(r'^Origin:\s*\((-?\d+),\s*(-?\d+)\)', block, re.M)
        if not number or not kind or not enabled:
            raise RuntimeError('Неполный ответ displayplacer: переключение отменено.')
        result.append({'id': uid[1], 'system_id': int(number[1]),
                       'origin': [int(origin[1]), int(origin[2])] if origin else None,
                       'builtin': bool(re.search(r'built.in|internal', kind[1], re.I)),
                       'external': 'external' in kind[1].lower(),
                       'enabled': enabled[1] == 'true'})
    return result


class Controller:
    def __init__(self, read, set_enabled, state_path=STATE, attempts=10, pause=time.sleep, set_origins=None, after_on=None):
        self.read, self.set_enabled, self.path = read, set_enabled, state_path
        self.attempts, self.pause = attempts, pause
        self.set_origins = set_origins
        self.after_on = after_on

    def finish_on(self, state):
        restored = self.restore_layout(state)
        if self.after_on is not None:
            try:
                restored += self.after_on(state['id']) or ''
            except (RuntimeError, OSError, ValueError, AttributeError, subprocess.TimeoutExpired) as error:
                raise RuntimeError('Экран включён в macOS, но яркость не синхронизирована. '
                                   f'{error} Повтори on для синхронизации без отключения.') from error
        return restored

    def capture_layout(self, screens):
        layout = {s['id']: s.get('origin') for s in screens if s['enabled']}
        if any(not isinstance(p, list) or len(p) != 2 for p in layout.values()):
            raise RuntimeError('Не удалось прочитать координаты экранов; отключение отменено.')
        if len({tuple(p) for p in layout.values()}) != len(layout):
            raise RuntimeError('Сохранение расположения поддерживает расширенный рабочий стол, без зеркалирования.')
        return layout

    def restore_layout(self, state):
        if not state.get('layout_pending'):
            return ''
        layout = state.get('layout')
        current = {s['id']: s for s in self.read() if s['enabled']}
        if not layout or set(current) != set(layout):
            raise RuntimeError('Экран включён, но состав дисплеев изменился: расположение не восстановлено. Сохранённая схема оставлена для повторного on.')
        def matches():
            observed = {s['id']: s.get('origin') for s in self.read() if s['enabled']}
            return observed == layout
        if not matches():
            if self.set_origins is None:
                raise RuntimeError('Нет обработчика восстановления расположения.')
            positions = [(current[uid]['system_id'], *point) for uid, point in layout.items()]
            positions.sort(key=lambda item: (item[1:3] != (0, 0)))
            self.set_origins(positions)
            for _ in range(self.attempts):
                if matches():
                    break
                self.pause(0.3)
            else:
                raise RuntimeError('Экран включён, но координаты не совпали с сохранёнными. Повтори on; схема сохранена.')
        state['layout_pending'] = False
        self.save(state)
        return ' Расположение экранов восстановлено.'

    def save(self, state):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state) + '\n')
        temporary.replace(self.path)

    def wait_for(self, target, enabled):
        for _ in range(self.attempts):
            screens = self.read()
            # Empty results can mean no WindowServer access, not successful off.
            if screens:
                active = any(s['id'] == target and s['enabled'] for s in screens)
                if active == enabled:
                    return True
            self.pause(0.3)
        return False

    def act(self, action, requested=None):
        screens = self.read()
        if not screens:
            raise RuntimeError('macOS не вернула список экранов. Запусти из обычного Terminal в текущем сеансе macOS.')
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        target = requested or saved.get('id')
        if not target:
            external = [s for s in screens if s['external']]
            if len(external) != 1:
                raise RuntimeError('Нужен ровно один внешний экран либо --id из list.')
            target = external[0]['id']
        screen = next((s for s in screens if s['id'] == target), None)
        if screen and not screen['external']:
            raise RuntimeError('Управлять встроенным экраном запрещено.')
        active = bool(screen and screen['enabled'])
        if action == 'save-layout':
            if not active:
                raise RuntimeError('Для сохранения расположения внешний экран должен быть активен.')
            self.save({'id': target, 'system_id': screen['system_id'], 'disabled': False,
                       'layout': self.capture_layout(screens), 'layout_pending': False})
            return 'Текущее расположение экранов сохранено.'
        if action == 'status':
            return 'Внешний экран активен в macOS.' if active else 'Внешний экран отсутствует среди активных; он может быть отключён или отсоединён.'
        if action == 'toggle':
            action = 'off' if active else 'on'
        # Idempotency comes BEFORE any display mutation, including fallback.
        if action == 'on' and active:
            state = dict(saved) if saved.get('id') == target else {}
            state.update(id=target, system_id=screen['system_id'], disabled=False)
            self.save(state)
            restored = self.finish_on(state)
            return 'Внешний экран уже включён в macOS.' + (restored or ' Ничего переключать не потребовалось.')
        if action == 'off' and not active:
            return 'Внешний экран уже отсутствует среди активных. Ничего не изменено.'
        if action == 'off':
            if not any(s['builtin'] and s['enabled'] for s in screens):
                raise RuntimeError('Открой крышку MacBook: нужен активный встроенный экран.')
            # Keep the numeric ID BEFORE the display disappears from discovery.
            state = {'id': target, 'system_id': screen['system_id'], 'disabled': True,
                     'layout': self.capture_layout(screens), 'layout_pending': True}
            self.save(state)
            number = screen['system_id']
        else:
            number = screen['system_id'] if screen else saved.get('system_id')
            if not number or (not screen and saved.get('id') != target):
                raise RuntimeError('Нет сохранённого системного номера для включения. Используй recover_display.py --all --apply либо перезагрузку после сохранения работы.')
            # Never use a stale number now belonging to a different online display.
            if any(s['system_id'] == number and s['id'] != target for s in screens):
                raise RuntimeError('Системный номер сменился. Автоматическое включение отменено; используй восстановление.')
            state = dict(saved)
            state.update(id=target, system_id=number, disabled=True)
        error = None
        try:
            self.set_enabled(number, action == 'on')
        except RuntimeError as exc:
            error = exc
        confirmed = self.wait_for(target, action == 'on')
        if confirmed:
            state['disabled'] = action == 'off'
            self.save(state)
            restored = self.finish_on(state) if action == 'on' else ''
            return ('Внешний экран отключён в macOS. Вернуть: python3 brighty.py on' if action == 'off'
                    else 'Внешний экран активен в macOS.' + restored + ' Проверь изображение на LG.')
        detail = f' {error}' if error else ''
        if action == 'off':
            raise RuntimeError('Отключение не подтверждено.' + detail + ' Сохранён номер для on.')
        raise RuntimeError('Включение не подтверждено.' + detail + ' Проверь кабель; для восстановления: python3 recover_display.py --all --apply')


def read_screens():
    binary = shutil.which('displayplacer')
    if not binary:
        raise RuntimeError('Нужен displayplacer: brew install displayplacer')
    process = subprocess.run([binary, 'list'], text=True, capture_output=True, timeout=15)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or 'Не удалось прочитать экраны.')
    return displays(process.stdout)


def sync_brightness_after_on(target):
    # Lazy import keeps list/status/off independent of brightness dependencies.
    from brightness import sync_external
    return sync_external(target)


def main():
    parser = argparse.ArgumentParser(description='Переключатель внешнего дисплея. Питание USB-C не отключается.')
    parser.add_argument('action', choices=['list', 'status', 'off', 'on', 'toggle', 'save-layout'])
    parser.add_argument('--id', help='Persistent screen id внешнего дисплея')
    args = parser.parse_args()
    if args.action == 'list':
        screens = read_screens()
        if not screens:
            raise RuntimeError('Список пуст: запусти из обычного Terminal в текущем сеансе macOS.')
        for screen in screens:
            print(f"{'MacBook' if screen['builtin'] else 'Внешний'}: {screen['id']}, системный номер {screen['system_id']}, активен: {screen['enabled']}, координаты: {screen['origin']}")
        return
    from display_api import DisplayAPI
    # Load the private API only when a change is actually required.
    def change(number, enabled):
        DisplayAPI().set_enabled(number, enabled)
    def position(items):
        DisplayAPI().set_origins(items)
    print(Controller(read_screens, change, set_origins=position,
                     after_on=sync_brightness_after_on).act(args.action, args.id))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, AttributeError, subprocess.TimeoutExpired) as error:
        sys.exit(str(error))
