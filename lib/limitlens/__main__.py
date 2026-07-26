"""limitlens — AI CLI usage limits in the terminal and the top bar.

  limitlens              show the limits
  limitlens --watch      redraw on an interval
  limitlens --json       raw stats document
  limitlens --once       collect silently (used by the GNOME extension)
"""

import argparse
import datetime
import json
import os
import sys
import time

from . import collect, hook
from .util import fmt_reset

BAR_WIDTH = 24


def _supports_colour():
    if os.environ.get('NO_COLOR'):
        return False
    if not sys.stdout.isatty():
        return False
    return os.environ.get('TERM', '') not in ('', 'dumb')


class Style:
    def __init__(self, enabled):
        self.enabled = enabled

    def _wrap(self, code, text):
        return '\033[%sm%s\033[0m' % (code, text) if self.enabled else text

    def dim(self, text):
        return self._wrap('2', text)

    def bold(self, text):
        return self._wrap('1', text)

    def cyan(self, text):
        return self._wrap('36', text)

    def severity(self, level, text):
        if level == 'critical':
            return self._wrap('31', text)
        if level == 'warning':
            return self._wrap('33', text)
        return self._wrap('32', text)


def _bar(percent, level, style):
    filled = int(round(min(max(percent, 0.0), 100.0) / 100.0 * BAR_WIDTH))
    return (style.severity(level, '█' * filled)
            + style.dim('░' * (BAR_WIDTH - filled)))


def render(stats, style):
    now = int(time.time())
    lines = ['']

    stamp = datetime.datetime.fromtimestamp(
        stats.get('generated_at') or now).strftime('%a %d %b %H:%M')
    lines.append('  %s   %s' % (style.bold(style.cyan('LIMITLENS')),
                                style.dim(stamp)))
    lines.append('')

    limits = stats.get('limits') or []
    if not limits:
        lines.append('  ' + style.dim('No limits available.'))
    else:
        provider = None
        for limit in limits:
            if limit['provider'] != provider:
                provider = limit['provider']
                heading = provider
                if limit.get('plan'):
                    heading += ' · %s' % limit['plan']
                lines.append('  ' + style.bold(heading))

            reset = ''
            if limit.get('resets_at'):
                reset = 'resets in %s' % fmt_reset(limit['resets_at'] - now)
            tag = style.dim(' (stale)') if limit.get('stale') else ''

            lines.append('    %-24s %s %5.1f%%  %s%s' % (
                limit['label'][:24],
                _bar(limit['percent'], limit['severity'], style),
                limit['percent'],
                reset,
                tag,
            ))
        lines.append('')

    for warning in stats.get('warnings') or []:
        lines.append('  ' + style.dim('! ' + warning))

    lines.append('')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='limitlens', description=__doc__)

    parser.add_argument('--once', action='store_true',
                        help='collect without printing (used by the extension)')
    parser.add_argument('--json', action='store_true', help='print raw stats JSON')
    parser.add_argument('--watch', nargs='?', const=60, type=int, metavar='SECONDS',
                        help='redraw on an interval (default 60s)')
    parser.add_argument('--force', action='store_true',
                        help='bypass the per-provider fetch throttle')
    parser.add_argument('--install-hook', action='store_true',
                        help="let Claude Code push its limits (no polling)")
    parser.add_argument('--uninstall-hook', action='store_true',
                        help='remove the status line hook')
    parser.add_argument('--statusline', action='store_true',
                        help=argparse.SUPPRESS)  # invoked by Claude Code
    args = parser.parse_args(argv)

    if args.statusline:
        # Compatibility shim for a settings.json still pointing here.  The real
        # hook is a standalone, import-light script: it runs inside Claude
        # Code's render path, where this entry point's imports cost 4x more.
        import shutil
        hook_path = shutil.which('limitlens-statusline')
        if hook_path:
            os.execv(hook_path, [hook_path])
        return 0
    if args.install_hook:
        return hook.install()
    if args.uninstall_hook:
        return hook.uninstall()

    if args.watch:
        style = Style(_supports_colour())
        try:
            while True:
                stats = collect.run(force=True)
                sys.stdout.write('\033[2J\033[H' if style.enabled else '\n')
                print(render(stats, style))
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0

    stats = collect.run(force=args.force or not args.once)

    if args.once:
        return 0
    if args.json:
        json.dump(stats, sys.stdout, indent=2)
        print()
        return 0

    print(render(stats, Style(_supports_colour())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
