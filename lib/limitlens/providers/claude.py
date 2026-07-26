"""Claude usage limits, cheapest source first.

Three ways to get the same two numbers, in ascending cost:

1. **Status line hook** — Claude Code hands its ``rate_limits`` to a configured
   status line command on every render, so if the hook is installed
   (``limitlens --install-hook``) the numbers are already on disk. Free.
2. **The /usage panel**, driven over a pty. Authoritative and always available,
   but spawns the CLI: ~325 MB for about six seconds.
3. ~~``GET /api/oauth/usage``~~ — deliberately not used. It rate-limits so
   aggressively that it is unusable for monitoring, and repeated retries can
   degrade the OAuth token (claude-code #31021, #30930, #31637).

So: use the hook's reading when it is recent; otherwise fall back to the probe,
which also covers the case where the hook was never installed.
"""

import json
import os
import time

from . import claude_cli, claude_statusline

NAME = 'Claude'
CREDENTIALS = os.path.expanduser('~/.claude/.credentials.json')

# Age at which the reading is still used but flagged in the UI.  It is not a
# expiry: your usage cannot rise while Claude Code is closed, and the hook
# rewrites the file whenever it runs, so an old reading is still correct until
# its window resets — and `claude_statusline.read` already drops rows past
# their own reset time.  Probing on age alone would burn 325 MB to re-learn a
# number that hasn't changed.
HOOK_STALE_AFTER = 900

# The probe spawns the CLI, so keep it infrequent.
MIN_INTERVAL = 600


def _plan():
    """Subscription name, read from the local credentials file."""
    try:
        with open(CREDENTIALS, 'r') as fh:
            oauth = (json.load(fh) or {}).get('claudeAiOauth') or {}
    except (OSError, ValueError):
        return None
    return (oauth.get('subscriptionType') or '').replace('_', ' ').title() or None


def fetch(cache, force=False):
    """Return (rows, warning, new_cache).  Never raises."""
    now = time.time()
    cache = dict(cache or {})
    plan = _plan()

    # 1. Free path: whatever the status line hook last wrote.  Rows whose
    #    window has already reset were dropped by the reader, so anything left
    #    still describes a live window.
    rows, age = claude_statusline.read(plan)
    if rows:
        if age is not None and age > HOOK_STALE_AFTER:
            for row in rows:
                row['stale'] = True
        return rows, None, {'fetched_at': now, 'rows': rows, 'via': 'statusline',
                            'cli_at': cache.get('cli_at', 0)}

    if not force and now - cache.get('fetched_at', 0) < MIN_INTERVAL:
        return cache.get('rows') or [], None, cache

    # 2. Spawn the CLI and read its panel.
    probe_rows, warning = claude_cli.fetch(plan)
    cache['cli_at'] = now
    if probe_rows:
        return probe_rows, None, {'fetched_at': now, 'rows': probe_rows,
                                  'via': 'cli', 'cli_at': now}

    # 3. Nothing fresh — serve whatever we have, saying so.
    if rows:
        return rows, ('Claude: %s (using the status line reading, %dm old)'
                      % (warning, int((age or 0) // 60))), cache
    stale = cache.get('rows') or []
    return stale, 'Claude: %s%s' % (
        warning, ' (showing last reading)' if stale else ''), cache
