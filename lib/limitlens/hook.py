"""Install/remove the Claude Code status line hook.

Editing another tool's config is intrusive, so this is an explicit opt-in
command rather than something install.sh does behind your back — and it never
discards a status line you already had: an existing command is preserved and
chained.
"""

import json
import os
import shutil

from . import state as state_mod

SETTINGS = os.path.expanduser('~/.claude/settings.json')
CONFIG_FILE = os.path.join(
    os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'),
    'limitlens', 'config.json',
)
COMMAND = 'limitlens-statusline'


def _resolved_command():
    """Prefer an absolute path — Claude Code may not share your PATH.

    Points at the standalone hook rather than ``limitlens --statusline``:
    the latter imports the whole package (~34 ms) for work that needs two
    modules, and this runs on every status line render.
    """
    return shutil.which(COMMAND) or COMMAND


def install():
    settings = state_mod.load_json(SETTINGS, {}) or {}
    existing = settings.get('statusLine')
    command = _resolved_command()

    if isinstance(existing, dict) and existing.get('command'):
        if 'limitlens' in existing['command'] or 'tokencount' in existing['command']:
            if existing['command'] == command:
                print('Already installed.')
                return 0
            # An older hook command — upgrade it in place.
            settings['statusLine'] = {'type': 'command', 'command': command}
            state_mod.save_json(SETTINGS, settings)
            print('Updated the hook command to %s' % command)
            print('Restart Claude Code for it to take effect.')
            return 0
        # Chain rather than clobber: ours records the limits, then runs theirs
        # and prints its output verbatim.
        config = state_mod.load_json(CONFIG_FILE, {}) or {}
        config['statusline_delegate'] = existing['command']
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        state_mod.save_json(CONFIG_FILE, config)
        print('Kept your existing status line and chained it:')
        print('  %s' % existing['command'])

    settings['statusLine'] = {'type': 'command', 'command': command}
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        state_mod.save_json(SETTINGS, settings)
    except OSError as exc:
        print('Could not write %s: %s' % (SETTINGS, exc))
        return 1

    print('Installed the status line hook in %s' % SETTINGS)
    print()
    print('Claude Code now hands limitlens its limits on every render, so no')
    print('polling or subprocess is needed while you are using it.')
    print('Restart Claude Code for it to take effect.')
    return 0


def uninstall():
    settings = state_mod.load_json(SETTINGS, {}) or {}
    current = (settings.get('statusLine') or {}).get('command', '')
    if 'limitlens' not in current and 'tokencount' not in current:
        print('Not installed.')
        return 0

    config = state_mod.load_json(CONFIG_FILE, {}) or {}
    delegate = config.pop('statusline_delegate', None)
    if delegate:
        settings['statusLine'] = {'type': 'command', 'command': delegate}
        print('Restored your previous status line:')
        print('  %s' % delegate)
        state_mod.save_json(CONFIG_FILE, config)
    else:
        settings.pop('statusLine', None)

    state_mod.save_json(SETTINGS, settings)
    print('Removed the status line hook. Restart Claude Code.')
    return 0

