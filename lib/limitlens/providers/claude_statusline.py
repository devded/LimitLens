"""Read the limits Claude Code's status line hook left for us.

Free in every sense: no process spawned, no request made, just a small file the
CLI wrote while you were using it.  See ``limitlens.statusline``.


The catch is that it only updates while Claude Code is running.  That is mostly
fine — the numbers only move when you're using it — but a window can *reset*
while the CLI is closed, which would leave a high percentage on screen that is
no longer true.  So a reading past its own reset time is refused, and the caller
falls back to the authoritative probe.
"""

import os
import time

from .. import state as state_mod

CACHE_FILE = os.path.join(state_mod.DATA_DIR, 'claude-statusline.json')

WINDOWS = (
    ('five_hour', 'Session (5h)'),
    ('seven_day', 'Weekly'),
)

# Beyond this the reading is still shown, but flagged stale in the UI.
STALE_AFTER = 900


def read(plan=None):
    """Return (rows, age_seconds) — rows is empty if there is nothing usable."""
    data = state_mod.load_json(CACHE_FILE, None)
    if not isinstance(data, dict):
        return [], None

    written_at = data.get('written_at') or 0
    limits = data.get('rate_limits') or {}
    now = time.time()
    age = now - written_at

    rows = []
    for key, label in WINDOWS:
        window = limits.get(key) or {}
        percent = window.get('used_percentage')
        if percent is None:
            continue
        resets_at = window.get('resets_at')
        # The window rolled over since this was written, so the percentage
        # describes a window that no longer exists.
        if resets_at and resets_at <= now:
            continue
        rows.append({
            'provider': 'Claude',
            'plan': plan or data.get('plan'),
            'label': label,
            'percent': float(percent),
            'resets_at': resets_at,
            'source': 'statusline',
        })

    return rows, age


def fresh(age, limit):
    return age is not None and age <= limit
