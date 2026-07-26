"""Claude limits by driving the CLI itself, for when the API is rate-limited.

``/api/oauth/usage`` rate-limits hard enough to be unusable for long stretches
(claude-code issues #31021, #30930, #31637).  Claude Code's own ``/usage``
panel keeps working through those stretches, so when the API path is blocked
this drives the CLI and reads the panel it renders — the same fallback CodexBar
uses.

It has to be a pty: in ``--print`` mode ``/usage`` returns only the local
"what's contributing" analysis, because the percentage panel is drawn by the
interactive UI.

The panel looks like this once escape sequences are stripped (note the missing
space in ``72%used`` — the bar is drawn with cursor moves, not spaces)::

    Current session ██████████████            72%used
    Resets 4:30am (Europe/Istanbul)
    Current week (all models)             0%used
    Resets Aug 3, 1am (Europe/Istanbul)

Spawning the CLI costs no tokens — the panel is local — but it takes a few
seconds, so it is gated behind its own interval and only runs when the API path
has nothing to offer.
"""

import datetime
import os
import re
import select
import shutil
import time

# Give the CLI time to boot and render; it is a TUI, not a script.
BOOT_WAIT = 2.5
TOTAL_TIMEOUT = 45
PROBE_DIR = os.path.join(
    os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
    'limitlens', 'probe',
)


ANSI_CSI = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')
ANSI_OSC = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')
ANSI_MISC = re.compile(r'\x1b[()#][0-9A-Za-z]|\x1b[=>78]')
BLOCKS = re.compile('[▀-▟─-╿]+')

PERCENT = re.compile(r'(\d+(?:\.\d+)?)\s*%\s*used', re.IGNORECASE)
RESETS = re.compile(r'Resets\s+([^\n]+)', re.IGNORECASE)

WINDOWS = (
    (re.compile(r'Current session', re.IGNORECASE), 'Session (5h)'),
    (re.compile(r'Current week', re.IGNORECASE), 'Weekly'),
)


def available():
    return shutil.which('claude') is not None


def _clean(raw):
    text = raw.decode('utf-8', 'replace')
    text = ANSI_OSC.sub('', text)
    text = ANSI_CSI.sub('', text)
    text = ANSI_MISC.sub('', text)
    text = text.replace('\x08', '').replace('\r', '\n')
    text = BLOCKS.sub(' ', text)
    return text


def _run():
    """Drive `claude` to its /usage panel and return the cleaned screen text."""
    import pty

    os.makedirs(PROBE_DIR, exist_ok=True)
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(PROBE_DIR)
            os.environ['TERM'] = 'xterm-256color'
            # No tools, so the probe can't touch anything even if a prompt
            # were somehow interpreted.
            os.execvp('claude', ['claude', '--allowed-tools', ''])
        except BaseException:
            os._exit(1)

    # Non-blocking, so a read can never outlive the deadline.  An unguarded
    # blocking read here once hung the collector for minutes and orphaned the
    # child process.
    os.set_blocking(fd, False)

    buf = b''
    sent = False
    deadline = time.time() + TOTAL_TIMEOUT
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 1.0)
            if ready:
                try:
                    chunk = os.read(fd, 65536)
                except (OSError, BlockingIOError):
                    chunk = b''
                if chunk is None:
                    chunk = b''
                if not chunk:
                    break
                buf += chunk

            if not sent and len(buf) > 200:
                time.sleep(BOOT_WAIT)
                try:
                    os.write(fd, b'/usage\r')
                except OSError:
                    break
                sent = True

            if sent and buf.count(b'Resets') >= 2:
                # Let the panel finish drawing, still only reading when ready.
                settle = time.time() + 1.5
                while time.time() < settle:
                    ready, _, _ = select.select([fd], [], [], 0.25)
                    if not ready:
                        continue
                    try:
                        chunk = os.read(fd, 65536)
                    except (OSError, BlockingIOError):
                        break
                    if not chunk:
                        break
                    buf += chunk
                break
    finally:
        for keys in (b'\x1b', b'\x03', b'\x04'):
            try:
                os.write(fd, keys)
                time.sleep(0.15)
            except OSError:
                break
        try:
            os.close(fd)
        except OSError:
            pass
        _reap(pid)
        _tidy()

    return _clean(buf)


def _reap(pid):
    for _ in range(20):
        try:
            done, _status = os.waitpid(pid, os.WNOHANG)
        except OSError:
            return
        if done:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    except OSError:
        pass


def _tidy():
    """Drop the transcript the probe session leaves behind."""
    slug = PROBE_DIR.replace('/', '-')
    directory = os.path.expanduser('~/.claude/projects/%s' % slug)
    try:
        for name in os.listdir(directory):
            if name.endswith('.jsonl'):
                os.unlink(os.path.join(directory, name))
    except OSError:
        pass


def _parse_reset(text, now=None):
    """'4:30am (Europe/Istanbul)' / 'Aug 3, 1am (Europe/Istanbul)' -> epoch."""
    text = text.strip()
    zone = None
    match = re.search(r'\(([A-Za-z_]+/[A-Za-z_+\-]+)\)', text)
    if match:
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(match.group(1))
        except Exception:
            zone = None
        text = text[:match.start()].strip()
    text = text.rstrip(',').strip()

    now = now or datetime.datetime.now(tz=zone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=zone) if zone else now.astimezone()

    clock = re.search(r'(\d{1,2})(?::(\d{2}))?\s*([ap])m', text, re.IGNORECASE)
    if not clock:
        return None
    hour = int(clock.group(1)) % 12
    minute = int(clock.group(2) or 0)
    if clock.group(3).lower() == 'p':
        hour += 12

    day = re.search(r'([A-Za-z]{3,9})\s+(\d{1,2})', text[:clock.start()])
    if day:
        try:
            month = datetime.datetime.strptime(day.group(1)[:3], '%b').month
        except ValueError:
            return None
        candidate = now.replace(month=month, day=int(day.group(2)),
                                hour=hour, minute=minute,
                                second=0, microsecond=0)
        if candidate < now - datetime.timedelta(days=180):
            candidate = candidate.replace(year=candidate.year + 1)
    else:
        candidate = now.replace(hour=hour, minute=minute,
                                second=0, microsecond=0)
        if candidate <= now:
            candidate += datetime.timedelta(days=1)

    return int(candidate.timestamp())


def parse(text, plan=None):
    """Pull the limit rows out of the rendered panel."""
    rows = []
    for header, label in WINDOWS:
        match = header.search(text)
        if not match:
            continue
        tail = text[match.end():match.end() + 400]
        percent = PERCENT.search(tail)
        if not percent:
            continue
        reset = RESETS.search(tail)
        rows.append({
            'provider': 'Claude',
            'plan': plan,
            'label': label,
            'percent': float(percent.group(1)),
            'resets_at': _parse_reset(reset.group(1)) if reset else None,
            'source': 'cli',
        })
    return rows


def fetch(plan=None):
    """Return (rows, warning).  Never raises."""
    if not available():
        return [], 'claude CLI not on PATH'
    try:
        text = _run()
    except Exception as exc:
        return [], 'CLI probe failed: %s' % exc
    rows = parse(text, plan)
    if not rows:
        return [], 'CLI probe returned no usage panel'
    return rows, None
