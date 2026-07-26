"""Antigravity (``agy``) usage limits, from its own language server.

While ``agy`` is running it hosts a language server on a loopback port, and
that server answers the very RPC the ``/usage`` panel is drawn from:

    POST http://127.0.0.1:<port>
         /exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary

The response is grouped exactly as the panel shows it — "Gemini Models" and
"Claude and GPT models", each with a weekly and a 5-hour bucket carrying
``remainingFraction`` and ``resetTime``.  Note the field is what is *left*, so
the percentage used is ``1 - remainingFraction``.

Two other routes were tried and rejected:

- The Code Assist API (``cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota``)
  answers with the consumer OAuth token, but returns Gemini Code Assist buckets
  (``gemini-2.5-*``) that sit at 100% remaining regardless of ``agy`` use — a
  different quota pool from the one the CLI enforces.  Its
  ``:retrieveUserQuotaSummary`` sibling returns ``403 PERMISSION_DENIED``.
- ``agy --print "/usage"`` doesn't work: in print mode the slash command is
  answered by the model, because the panel is rendered client-side.

The port only exists while ``agy`` is running.  When it isn't, the last reading
is served from cache and flagged stale rather than dropped.
"""

import glob
import json
import os
import time
import urllib.error
import urllib.request

from ..util import iso_to_epoch

NAME = 'Antigravity'
RPC_PATH = ('/exa.language_server_pb.LanguageServerService/'
            'RetrieveUserQuotaSummary')
STATUS_PATH = '/exa.language_server_pb.LanguageServerService/GetUserStatus'
TIMEOUT = 4
MIN_INTERVAL = 30


def _agy_pids():
    pids = []
    for entry in glob.glob('/proc/[0-9]*'):
        try:
            with open(os.path.join(entry, 'comm'), 'r') as fh:
                if fh.read().strip() != 'agy':
                    continue
        except OSError:
            continue
        pids.append(os.path.basename(entry))
    return pids


def _listening_ports():
    """Loopback TCP ports listened on by an `agy` process.

    Read from /proc directly: matching socket inodes to the process's open file
    descriptors avoids shelling out to `ss` or `lsof`, which the GNOME Shell
    subprocess environment may not have.
    """
    pids = _agy_pids()
    if not pids:
        return []

    inodes = set()
    for pid in pids:
        fd_dir = '/proc/%s/fd' % pid
        try:
            names = os.listdir(fd_dir)
        except OSError:
            continue
        for name in names:
            try:
                target = os.readlink(os.path.join(fd_dir, name))
            except OSError:
                continue
            if target.startswith('socket:['):
                inodes.add(target[8:-1])

    if not inodes:
        return []

    proc_files = [
        ('/proc/net/tcp', {'0100007F', '00000000'}),
        ('/proc/net/tcp6', {'00000000000000000000000001000000', '00000000000000000000000000000000'}),
    ]
    ports = []
    for net_file, valid_addrs in proc_files:
        try:
            with open(net_file, 'r') as fh:
                for line in fh.readlines()[1:]:
                    fields = line.split()
                    if len(fields) < 10 or fields[3] != '0A':  # 0A = LISTEN
                        continue
                    if fields[9] not in inodes:
                        continue
                    local = fields[1]
                    address, port = local.split(':')
                    if address.upper() not in valid_addrs:
                        continue
                    ports.append(int(port, 16))
        except OSError:
            continue
    return sorted(set(ports))


def _post(port, path, timeout=TIMEOUT):
    request = urllib.request.Request(
        'http://127.0.0.1:%d%s' % (port, path),
        data=b'{}',
        headers={'Content-Type': 'application/json',
                 'User-Agent': 'limitlens/1.0'},

    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def _plan(port):
    try:
        status = _post(port, STATUS_PATH, timeout=2)
    except Exception:
        return None
    plan = (((status.get('userStatus') or {}).get('planStatus') or {})
            .get('planInfo') or {}).get('planName')
    return plan or None


WINDOW_LABELS = {'5h': '5h', 'weekly': 'Weekly', 'daily': 'Daily'}


def _short_group(name):
    """"Gemini Models" -> "Gemini"; "Claude and GPT models" -> "Claude and GPT"."""
    for suffix in (' Models', ' models'):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _rows(payload, plan):
    rows = []
    for group in (payload.get('response') or {}).get('groups') or []:
        group_name = _short_group(group.get('displayName') or 'Models')
        for bucket in group.get('buckets') or []:
            remaining = bucket.get('remainingFraction')
            if remaining is None:
                continue
            # remainingFraction is what is LEFT; the panel shows what is used.
            percent = max(0.0, min(100.0, (1.0 - float(remaining)) * 100.0))
            rows.append({
                'provider': NAME,
                'plan': plan,
                'label': '%s · %s' % (
                    group_name,
                    WINDOW_LABELS.get(bucket.get('window'),
                                      bucket.get('displayName') or 'Limit')),
                'percent': percent,
                'resets_at': iso_to_epoch(bucket.get('resetTime')),
                'source': 'rpc',
            })
    rows.sort(key=lambda row: row['percent'], reverse=True)
    return rows


def fetch(cache, force=False):
    """Return (rows, warning, new_cache).  Never raises."""
    now = time.time()
    cache = dict(cache or {})

    if not force and now - cache.get('fetched_at', 0) < MIN_INTERVAL:
        return cache.get('rows') or [], None, cache

    ports = _listening_ports()
    if not ports:
        return cache.get('rows') or [], (
            'Antigravity: agy is not running (showing last reading)'
            if cache.get('rows') else 'Antigravity: agy is not running'), cache

    # Try the last known working port first to avoid timeouts on non-HTTP ports
    cached_port = cache.get('port')
    if cached_port and cached_port in ports:
        ports.remove(cached_port)
        ports.insert(0, cached_port)

    last_error = None
    for port in ports:
        try:
            payload = _post(port, RPC_PATH)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = exc
            continue  # agy opens several ports; only one speaks plain HTTP

        rows = _rows(payload, _plan(port))
        if rows:
            return rows, None, {'fetched_at': now, 'rows': rows, 'port': port}

    return cache.get('rows') or [], (
        'Antigravity: language server did not answer (%s)' % last_error), cache
