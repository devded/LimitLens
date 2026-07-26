"""Run one collection pass: ask each provider for its limits, write stats.json."""

import os
import time

from . import state as state_mod
from .providers import antigravity, claude
from .util import severity

CONFIG_FILE = os.path.join(
    os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'),
    'limitlens', 'config.json',
)


PROVIDERS = {'claude': claude, 'agy': antigravity}
DEFAULT_PROVIDERS = ['claude', 'agy']


def load_config():
    config = state_mod.load_json(CONFIG_FILE, {}) or {}
    names = config.get('providers')
    if not isinstance(names, list) or not names:
        names = DEFAULT_PROVIDERS
    return [n for n in names if n in PROVIDERS]


def run(force=False):
    started = time.time()
    state = state_mod.load_state()
    limits = []
    warnings = []

    for name in load_config():
        module = PROVIDERS[name]
        cache = state['providers'].get(name) or {}
        rows, warning, cache = module.fetch(cache, force=force)
        state['providers'][name] = cache
        if warning:
            warnings.append(warning)
        age = time.time() - cache.get('fetched_at', 0)
        for row in rows:
            row = dict(row)
            row['severity'] = severity(row['percent'])
            row['as_of'] = int(cache.get('fetched_at', 0))
            # A provider may know better than the clock whether its reading is
            # stale (the status line hook does), so only fall back to age.
            if 'stale' not in row:
                row['stale'] = age > module.MIN_INTERVAL * 2
            limits.append(row)

    # The panel wants the single worst limit anywhere, but the list is read as
    # grouped blocks — so order providers by their worst limit, then sort
    # within each provider.  Sorting the flat list by percent alone interleaves
    # providers and repeats their headings.
    worst = {}
    for row in limits:
        worst[row['provider']] = max(worst.get(row['provider'], 0), row['percent'])
    limits.sort(key=lambda row: (-worst[row['provider']], row['provider'],
                                 -row['percent']))

    panel = None
    if limits:
        top = max(limits, key=lambda row: row['percent'])
        panel = {
            'percent': top['percent'],
            'provider': top['provider'],
            'label': top['label'],
            'severity': top['severity'],
            'stale': top.get('stale', False),
        }

    stats = {
        'version': 2,
        'generated_at': int(time.time()),
        'duration_ms': int((time.time() - started) * 1000),
        'panel': panel,
        'limits': limits,
        'warnings': warnings,
    }

    state_mod.save_state(state)
    state_mod.save_json(state_mod.STATS_FILE, stats)
    return stats
