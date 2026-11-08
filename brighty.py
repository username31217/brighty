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
            raise RuntimeError('Incomplete displayplacer response: switching canceled.')
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
                raise RuntimeError('The display is enabled in macOS, but brightness was not synchronized. '
                                   f'{error} Run on again to synchronize without disconnecting.') from error
        return restored

    def capture_layout(self, screens):
        layout = {s['id']: s.get('origin') for s in screens if s['enabled']}
        if any(not isinstance(p, list) or len(p) != 2 for p in layout.values()):
            raise RuntimeError('Could not read display coordinates; disconnection canceled.')
        if len({tuple(p) for p in layout.values()}) != len(layout):
            raise RuntimeError('Layout saving supports an extended desktop only, without mirroring.')
        return layout

    def restore_layout(self, state):
        if not state.get('layout_pending'):
            return ''
        layout = state.get('layout')
        current = {s['id']: s for s in self.read() if s['enabled']}
        if not layout or set(current) != set(layout):
            raise RuntimeError('The display is enabled, but the set of displays changed: layout was not restored. The saved layout was kept for another on attempt.')
        def matches():
            observed = {s['id']: s.get('origin') for s in self.read() if s['enabled']}
            return observed == layout
        if not matches():
            if self.set_origins is None:
                raise RuntimeError('No layout restoration handler is available.')
            positions = [(current[uid]['system_id'], *point) for uid, point in layout.items()]
            positions.sort(key=lambda item: (item[1:3] != (0, 0)))
            self.set_origins(positions)
            for _ in range(self.attempts):
                if matches():
                    break
                self.pause(0.3)
            else:
                raise RuntimeError('The display is enabled, but coordinates do not match the saved layout. Run on again; the layout was kept.')
        state['layout_pending'] = False
        self.save(state)
        return ' Display layout restored.'

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
            raise RuntimeError('macOS did not return a display list. Run from a regular Terminal in the current macOS session.')
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        target = requested or saved.get('id')
        if not target:
            external = [s for s in screens if s['external']]
            if len(external) != 1:
                raise RuntimeError('Exactly one external display or an explicit --id from list is required.')
            target = external[0]['id']
        screen = next((s for s in screens if s['id'] == target), None)
        if screen and not screen['external']:
            raise RuntimeError('Controlling the built-in display is not allowed.')
        active = bool(screen and screen['enabled'])
        if action == 'save-layout':
            if not active:
                raise RuntimeError('The external display must be active to save the layout.')
            self.save({'id': target, 'system_id': screen['system_id'], 'disabled': False,
                       'layout': self.capture_layout(screens), 'layout_pending': False})
            return 'Current display layout saved.'
        if action == 'status':
            return 'The external display is active in macOS.' if active else 'The external display is not active; it may be disabled or unplugged.'
        if action == 'toggle':
            action = 'off' if active else 'on'
        # Idempotency comes BEFORE any display mutation, including fallback.
        if action == 'on' and active:
            state = dict(saved) if saved.get('id') == target else {}
            state.update(id=target, system_id=screen['system_id'], disabled=False)
            self.save(state)
            restored = self.finish_on(state)
            return 'The external display is already enabled in macOS.' + (restored or ' No connection change was needed.')
        if action == 'off' and not active:
            return 'The external display is already absent from the active list. Nothing was changed.'
        if action == 'off':
            if not any(s['builtin'] and s['enabled'] for s in screens):
                raise RuntimeError('Open the MacBook lid: an active built-in display is required.')
            # Keep the numeric ID BEFORE the display disappears from discovery.
            state = {'id': target, 'system_id': screen['system_id'], 'disabled': True,
                     'layout': self.capture_layout(screens), 'layout_pending': True}
            self.save(state)
            number = screen['system_id']
        else:
            number = screen['system_id'] if screen else saved.get('system_id')
            if not number or (not screen and saved.get('id') != target):
                raise RuntimeError('No saved system display ID is available for enabling. Use recover_display.py --all --apply or save your work and restart.')
            # Never use a stale number now belonging to a different online display.
            if any(s['system_id'] == number and s['id'] != target for s in screens):
                raise RuntimeError('The system display ID changed. Automatic enabling was canceled; use recovery.')
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
            return ('The external display is disabled in macOS. Restore with: python3 brighty.py on' if action == 'off'
                    else 'The external display is active in macOS.' + restored + ' Check the image on LG.')
        detail = f' {error}' if error else ''
        if action == 'off':
            raise RuntimeError('Disconnection was not confirmed.' + detail + ' The display ID was saved for on.')
        raise RuntimeError('Enabling was not confirmed.' + detail + ' Check the cable; recover with: python3 recover_display.py --all --apply')


def read_screens():
    binary = shutil.which('displayplacer')
    if not binary:
        raise RuntimeError('displayplacer is required: brew install displayplacer')
    process = subprocess.run([binary, 'list'], text=True, capture_output=True, timeout=15)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or 'Could not read displays.')
    return displays(process.stdout)


def sync_brightness_after_on(target):
    # Lazy import keeps list/status/off independent of brightness dependencies.
    from brightness import sync_external
    return sync_external(target)


def main():
    parser = argparse.ArgumentParser(description='External display connection toggle. USB-C power is not disconnected.')
    parser.add_argument('action', choices=['list', 'status', 'off', 'on', 'toggle', 'save-layout'])
    parser.add_argument('--id', help='Persistent screen ID of the external display')
    args = parser.parse_args()
    if args.action == 'list':
        screens = read_screens()
        if not screens:
            raise RuntimeError('The display list is empty: run from a regular Terminal in the current macOS session.')
        for screen in screens:
            print(f"{'MacBook' if screen['builtin'] else 'External'}: {screen['id']}, system ID {screen['system_id']}, active: {screen['enabled']}, coordinates: {screen['origin']}")
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
