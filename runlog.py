"""Local run log and notifications: Shortcuts hides script errors from the unified log."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import NamedTuple

LOG = Path(__file__).resolve().with_name('.brighty.log')
LIMIT = 256 * 1024
# Diagnostics run from Terminal; they print but do not raise a notification.
QUIET_ACTIONS = {'list', 'status'}


class Report(NamedTuple):
    """CLI text plus a short notification title and body."""
    text: str
    title: str
    body: str = ''


def record(script, action, outcome, started, path=None):
    """Append one line; never let logging break a display command."""
    path = path or LOG
    try:
        if path.exists() and path.stat().st_size > LIMIT:
            lines = path.read_text(errors='replace').splitlines()
            path.write_text('\n'.join(lines[len(lines) // 2:]) + '\n')
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        text = ' '.join(str(outcome).split())
        with path.open('a') as handle:
            handle.write(f'{stamp} {script} {action} {time.monotonic() - started:.2f}s {text}\n')
    except OSError:
        pass


def notify(title, body, subtitle=''):
    """Best-effort macOS notification; BRIGHTY_NOTIFY=0 disables it."""
    if sys.platform != 'darwin' or os.environ.get('BRIGHTY_NOTIFY') == '0':
        return
    script = ('on run argv\n'
              'display notification (item 3 of argv) with title (item 1 of argv) subtitle (item 2 of argv)\n'
              'end run')
    try:
        # Text is passed as arguments, never interpolated into AppleScript.
        subprocess.run(['/usr/bin/osascript', '-e', script, title, subtitle, body],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def run(script, main, expected):
    """Run a CLI main, print and notify its result, log it, exit nonzero on failure."""
    started = time.monotonic()
    args = sys.argv[1:]
    action = ' '.join(args) or '-'
    quiet = bool(QUIET_ACTIONS & set(args))
    try:
        result = main()
    except expected as error:
        record(script, action, f'ERROR {type(error).__name__}: {error}', started)
        notify('Brighty error', str(error), f'{script} {action}')
        sys.exit(str(error))
    except BaseException as error:
        if not isinstance(error, SystemExit) or error.code not in (0, None):
            record(script, action, f'ERROR {type(error).__name__}: {error}', started)
            if not isinstance(error, SystemExit):
                notify('Brighty error', f'{type(error).__name__}: {error}', f'{script} {action}')
        raise
    report = result if isinstance(result, Report) else Report(result or '', '')
    if report.text:
        print(report.text)
    if not quiet:
        notify(report.title or 'Brighty', report.body or report.text)
    # list output holds machine identifiers; keep them out of the log.
    record(script, action, 'ok' if 'list' in args else f'ok {report.text}', started)
