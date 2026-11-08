#!/usr/bin/env python3
"""Explicit recovery for older state files lacking a saved numeric ID."""
import argparse
import json
import sys
import time
from brighty import STATE, Controller, read_screens, sync_brightness_after_on
from display_api import DisplayAPI


def record_recovery(saved, active):
    state = dict(saved)
    state.update(system_id=active['system_id'], disabled=False)
    controller = Controller(read_screens, None, set_origins=lambda positions: DisplayAPI().set_origins(positions),
                            after_on=sync_brightness_after_on)
    controller.save(state)
    return controller.finish_on(state)


def main():
    parser = argparse.ArgumentParser(description='Только включение дисплеев; без --apply изменений нет.')
    parser.add_argument('--all', action='store_true', help='Пробовать номера 1–10; может включить другие отключённые экраны')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    saved = json.loads(STATE.read_text()) if STATE.exists() else {}
    target = saved.get('id')
    if not target:
        raise RuntimeError('Нет сохранённого дисплея.')
    screens = read_screens()
    if not screens:
        raise RuntimeError('Список экранов пуст: запусти из обычного Terminal.')
    active = next((s for s in screens if s['id'] == target and s['enabled']), None)
    if active:
        if args.apply:
            detail = record_recovery(saved, active)
        else:
            detail = ''
        print('LG уже активен в macOS. Запросы включения не отправлялись.' + detail)
        return
    if not args.apply:
        print('Режим проверки: LG не активен. Изменений нет. Для восстановления используй --apply; --all разрешает перебор номеров 1–10.')
        return
    api = DisplayAPI()
    if not args.all:
        print(Controller(read_screens, api.set_enabled, set_origins=api.set_origins,
                         after_on=sync_brightness_after_on).act('on'))
        return
    online = {s['system_id'] for s in screens if s['enabled']}
    errors = []
    for number in range(1, 11):
        if number in online:
            continue
        try:
            api.set_enabled(number, True)
        except RuntimeError as error:
            errors.append(str(error))
        # API error alone does not determine whether recovery succeeded.
        for _ in range(3):
            time.sleep(0.3)
            current = read_screens()
            active = next((s for s in current if s['id'] == target and s['enabled']), None)
            if active:
                restored = record_recovery(saved, active)
                print('LG снова активен в macOS.' + restored + ' Проверь изображение.')
                return
    raise RuntimeError('LG не появился среди активных. ' + '; '.join(errors) + '\nСохрани работу и перезагрузи Mac; автоматическая перезагрузка не выполняется.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, AttributeError) as error:
        sys.exit(str(error))
