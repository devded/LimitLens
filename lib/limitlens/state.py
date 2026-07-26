"""On-disk state: the per-provider quota cache and the rendered stats file."""

import json
import os
import tempfile

DATA_DIR = os.path.join(
    os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'),
    'limitlens',
)

STATE_FILE = os.path.join(DATA_DIR, 'state.json')
STATS_FILE = os.path.join(DATA_DIR, 'stats.json')

STATE_VERSION = 3


def load_json(path, default):
    try:
        with open(path, 'r') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    """Write atomically — the extension reads stats.json on file modification."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(obj, fh, separators=(',', ':'))
            fd = None  # fd is now owned and closed by the context manager
        os.replace(tmp, path)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_state():
    state = load_json(STATE_FILE, None)
    if not isinstance(state, dict) or state.get('version') != STATE_VERSION:
        return {'version': STATE_VERSION, 'providers': {}}
    state.setdefault('providers', {})
    return state


def save_state(state):
    save_json(STATE_FILE, state)
