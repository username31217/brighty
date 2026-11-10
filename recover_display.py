#!/usr/bin/env python3
"""Explicit recovery for older state files lacking a saved numeric ID."""
import argparse
import json
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
    parser = argparse.ArgumentParser(description='Enable displays only; no changes without --apply.')
    parser.add_argument('--all', action='store_true', help='Try IDs 1–10; may enable other disabled displays')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    saved = json.loads(STATE.read_text()) if STATE.exists() else {}
    target = saved.get('id')
    if not target:
        raise RuntimeError('No saved display is available.')
    screens = read_screens()
    if not screens:
        raise RuntimeError('The display list is empty: run from a regular Terminal.')
    active = next((s for s in screens if s['id'] == target and s['enabled']), None)
    if active:
        if args.apply:
            detail = record_recovery(saved, active)
        else:
            detail = ''
        return 'LG is already active in macOS. No enable requests were sent.' + detail
    if not args.apply:
        return 'Diagnostic mode: LG is not active. No changes were made. Use --apply to recover; --all permits trying IDs 1–10.'
    api = DisplayAPI()
    if not args.all:
        return Controller(read_screens, api.set_enabled, set_origins=api.set_origins,
                          after_on=sync_brightness_after_on).act('on')
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
                return 'LG is active in macOS again.' + restored + ' Check the image.'
    raise RuntimeError('LG did not appear among active displays. ' + '; '.join(errors) + '\nSave your work and restart the Mac; no automatic restart will be performed.')


if __name__ == '__main__':
    import subprocess
    from runlog import run
    run('recover_display', main, (RuntimeError, OSError, ValueError, AttributeError, subprocess.TimeoutExpired))
