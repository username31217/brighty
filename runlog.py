"""Local run log: Shortcuts hides script errors from the unified log."""
from datetime import datetime
from pathlib import Path
import sys
import time

LOG = Path(__file__).resolve().with_name('.brighty.log')
LIMIT = 256 * 1024


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


def run(script, main, expected):
    """Run a CLI main, print its message, log the outcome, exit nonzero on failure."""
    started = time.monotonic()
    action = ' '.join(sys.argv[1:]) or '-'
    try:
        message = main()
    except expected as error:
        record(script, action, f'ERROR {type(error).__name__}: {error}', started)
        sys.exit(str(error))
    except BaseException as error:
        if not isinstance(error, SystemExit) or error.code not in (0, None):
            record(script, action, f'ERROR {type(error).__name__}: {error}', started)
        raise
    if message:
        print(message)
    # list output holds machine identifiers; keep them out of the log.
    record(script, action, 'ok' if 'list' in action.split() else f'ok {message or ""}', started)
