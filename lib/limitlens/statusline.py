"""Status line hook: let Claude Code hand us its limits for free.

Claude Code runs a configured status line command on every render and passes it
a JSON blob on stdin.  That blob contains exactly what this project wants::

    "rate_limits": {
      "five_hour": {"used_percentage": 81, "resets_at": 1785115800},
      "seven_day": {"used_percentage": 1,  "resets_at": 1785708000}
    }

So instead of limitlens spawning the CLI to read its ``/usage`` panel — a
~325 MB, six-second subprocess — the CLI you are already running drops the
numbers into a small file, and the collector just reads it.  No polling, no
spawning, no network.

Wire it up with ``limitlens --install-hook``.  The command is additive: if a
status line command is already configured, this one runs it and passes its
output straight through, so nothing you had is lost.
"""

import json
import os
import subprocess
import sys
import time

from . import state as state_mod

CACHE_FILE = os.path.join(state_mod.DATA_DIR, 'claude-statusline.json')
CONFIG_FILE = os.path.join(
    os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'),
    'limitlens', 'config.json',
)



def _record(payload):
    limits = payload.get('rate_limits')
    if not isinstance(limits, dict):
        return
    state_mod.save_json(CACHE_FILE, {
        'written_at': int(time.time()),
        'rate_limits': limits,
        'plan': (payload.get('model') or {}).get('display_name'),
    })


def _delegate(raw):
    """Run a previously configured status line command, if any."""
    config = state_mod.load_json(CONFIG_FILE, {}) or {}
    command = config.get('statusline_delegate')
    if not command:
        return None
    try:
        result = subprocess.run(
            command, shell=True, input=raw, text=True,
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.rstrip('\n')


def _default_line(payload):
    limits = payload.get('rate_limits') or {}
    parts = []
    model = (payload.get('model') or {}).get('display_name')
    if model:
        parts.append(model)
    for key, label in (('five_hour', '5h'), ('seven_day', 'week')):
        window = limits.get(key) or {}
        percent = window.get('used_percentage')
        if percent is not None:
            parts.append('%s %d%%' % (label, percent))
    return ' · '.join(parts)


def main(argv=None):
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0

    try:
        _record(payload)
    except Exception:
        # A status line must never break the CLI it is rendering for.
        pass

    delegated = _delegate(raw)
    line = delegated if delegated is not None else _default_line(payload)
    if line:
        sys.stdout.write(line + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
