# Project Memory — LimitLens

Context file for AI agents and future contributors. Read this first; it captures
decisions and findings that aren't obvious from the code.

## What this project is

A token-usage and quota monitor for the Ubuntu/GNOME top bar, covering AI coding
CLIs, in the spirit of the macOS menu bar app **CodexBar**. Built July 2026 in
conversation with the owner (devded@pm.me).

Three parts, one data flow:

```
Python collector  ──writes──▶  ~/.local/share/limitlens/stats.json  ──read by──▶  GNOME extension
(lib/limitlens)                         (a few KB)                                 CLI dashboard
```

The extension deliberately does **no** scanning: GNOME Shell extensions run
inside the compositor, and walking 116 MB of session logs on the main loop would
stutter the desktop.

## Scope: limits only (deliberately)

The first version also counted tokens and cost by parsing
`~/.claude/projects/**/*.jsonl`. It worked and was verified exact, but the
owner cut it: the totals are dominated by cache reads (~97% on agentic work —
measured 145M of 149M over one week, 1016 calls averaging 143k cache-read
tokens each), which makes headline numbers read as nonsense. **Do not
reintroduce token counting.** The remaining feature is the one that changes
behaviour: how much of each limit is left, and when it resets.

## Provider research (done the hard way — don't redo it)

### Claude — the status line hook (free), then the pty probe

**Best source, found late: Claude Code's status line hook.** A configured
`statusLine` command is run on every render and receives a JSON blob on stdin
that already contains what we want:

```json
"rate_limits": {"five_hour": {"used_percentage": 81, "resets_at": 1785115800},
                "seven_day": {"used_percentage": 1,  "resets_at": 1785708000}}
```

So the CLI *pushes* to us: `limitlens --install-hook` writes
`statusLine` into `~/.claude/settings.json` pointing at `limitlens-statusline`,
which records `rate_limits` to
`~/.local/share/limitlens/claude-statusline.json` and prints a compact line.
An existing status line command is preserved in `statusline_delegate` and
chained, and restored on uninstall.

Measured effect: a collection drops from **6.4 s / 369 MB to 0.09 s / 26 MB**,
and CPU from 22 s/h to 2.4 s/h (0.62% -> 0.07% of a core).

**A stale hook reading is still valid** — usage cannot rise while Claude Code
is closed, and the hook rewrites the file whenever it runs. Only rows whose
`resets_at` has passed are discarded (the window rolled over, so the percentage
describes something that no longer exists). Do not add an age-based expiry that
triggers a probe: it burns 325 MB to re-learn an unchanged number.

**Fallback: drive the `/usage` panel over a pty** (`providers/claude_cli.py`).
Needed when the hook isn't installed or every window has reset. Must be a pty —
in `--print` mode `/usage` is answered by the *model* and returns only the
local "what's contributing" analysis, because the panel is drawn by the
interactive UI. Costs no tokens (`0 input, 0 output, $0.0000`) but does
increment Claude Code's `numStartups` and add a project entry to
`~/.claude.json`, skewing its own stats — another reason to prefer the hook.

Screen text after ANSI stripping has no space in `72%used`, because the bar is
drawn with cursor moves. Reset strings come in two shapes: `4:30am
(Europe/Istanbul)` and `Aug 3, 1am (Europe/Istanbul)`.

### Claude — `GET https://api.anthropic.com/api/oauth/usage` (rejected)

`Authorization: Bearer <accessToken from ~/.claude/.credentials.json>` plus
`anthropic-beta: oauth-2025-04-20`; parse the generic `limits[]` array. It
works, and it is **not used**: the endpoint rate-limits so aggressively that it
is unusable for monitoring (see the gotcha below). Kept documented only so the
next person doesn't "discover" it and switch back.

CodexBar's Claude source order is OAuth -> CLI PTY -> Web cookies
(`docs/claude.md`); it also has a known bug where refreshing tokens itself
desyncs Claude Code's refresh token and forces daily re-login (CodexBar #1161).
LimitLens never touches tokens, so that failure mode cannot occur here.

### Antigravity — the local language server, NOT a Google API

**This is the one that took real digging.** While `agy` runs it hosts a
language server on a loopback port answering the exact RPC its `/usage` panel
draws from:

```
POST http://127.0.0.1:<port>/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary
Content-Type: application/json
{}
```

Response: `response.groups[]` ("Gemini Models", "Claude and GPT models"), each
with `buckets[]` carrying `bucketId`, `displayName`, `window` (`5h`/`weekly`),
**`remainingFraction`** and `resetTime`. `remainingFraction` is what is LEFT —
percent used is `1 - remainingFraction`. `GetUserStatus` on the same server
gives `userStatus.planStatus.planInfo.planName` ("Pro").

Port discovery reads `/proc` directly (match `agy` pids → socket inodes →
`/proc/net/tcp` LISTEN rows on `0100007F`), avoiding `ss`/`lsof`, which may not
exist in the GNOME Shell subprocess environment. `agy` opens several ports;
only one speaks plain HTTP (the others answer "Client sent an HTTP request to
an HTTPS server"), so try each in turn.

### Antigravity routes that do NOT work (verified, don't retry)

- `cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota` **answers 200**
  with the keyring token, but returns Gemini *Code Assist* buckets
  (`gemini-2.5-*`) that sit at 100% remaining no matter how much `agy` is used.
  Different quota pool from the one the CLI enforces. Shipping it would have
  been confidently wrong.
- `:retrieveUserQuotaSummary` on that host → `403 PERMISSION_DENIED` (the
  request message has no `metadata` field; `{}` parses but is denied).
- `agy --print "/usage"` → the *model* answers, because the panel is rendered
  client-side. There is no `usage`/`quota` subcommand.
- `~/.gemini/oauth_creds.json` holds an **expired** token → `401`. The live one
  is in the keyring (`service=gemini, username=antigravity`, JSON
  `{"token": {"access_token": ...}}`), which is what the Code Assist attempt
  used. The keyring is no longer needed now that the local RPC is used.

### Claude token/cost endpoints that do NOT work (Pro plan)

- `/v1/organizations/usage_report/messages`, `/v1/organizations/cost_report` →
  `403 Authentication method not allowed`. Admin API key required
  (Team/Enterprise); this account is `claude_pro`.
- `/api/organizations/<uuid>/usage` → `403 account_session_invalid`. Wants a
  claude.ai browser session cookie, not the CLI OAuth token.

### Other CLIs

| CLI | Limits | Notes |
|---|---|---|
| Codex | cached in `~/.codex/sessions/**/rollout-*.jsonl` as `rate_limits` (`used_percent`, `window_minutes`, `resets_at`) | provider module was written then dropped with the token-counting removal; easy to re-add |
| GitHub Copilot CLI | none found | `~/.copilot/session-store.db` has no usage tables |
| opencode | n/a | its db has per-session tokens/cost, but that's counting, which is out of scope now |

## Key design decisions (and why)

- **Panel shows the highest limit in use** across providers — the number that
  says how much room is left. Glyph fills with it (`○ ◔ ◑ ◕ ●`); amber at 75%,
  red at 90%; trailing `*` means stale.
- **The extension does no network I/O.** GNOME Shell extensions run inside the
  compositor, so a hanging request would stutter the desktop. The collector
  runs out of process and writes `stats.json`; the extension renders it.
- **Poll at most every 5 min** (Claude) / 2 min (Antigravity, local so cheap).
  A 5-hour window doesn't need minute resolution.
- **429 handling:** honour `retry-after`, floor of 10 minutes, keep serving the
  last reading flagged stale. The manual Refresh bypasses the interval throttle
  but *never* the cooldown — retrying into a rate limit is how a short block
  becomes a long one.
- **Providers never raise.** `fetch()` returns `(rows, warning, cache)`; one
  broken provider degrades to a warning line instead of an empty panel.

## Gotchas that cost time (don't rediscover these)

- **`/api/oauth/usage` rate-limits aggressively, and it is a known upstream
  bug** — claude-code issues #31021, #30930, #31637; CodexBar #575. Tools
  polling every 30-60s get stuck in permanent 429 loops, Claude Code's own
  `/usage` is affected, and repeated retries can leave the token in a degraded
  state where 429s outlast the nominal window. Probing it in a loop during this
  build cost ~1 hour of blocked verification. **Probe it once**, then test the
  render path by seeding `state.json` under a throwaway `XDG_DATA_HOME`.
  Mitigation in `providers/claude.py`: 5-minute floor, escalating backoff
  (10/20/40/60 min), manual refresh never bypasses the cooldown.
- **There is no alternative Claude source.** `~/.claude.json` caches no usage
  data (`metricsStatusCache` is a feature flag, not quota), so the endpoint is
  the only route and everyone shares the constraint.
- **`agy` must be running** for its limits to refresh; the loopback port only
  exists during a session. Cached readings cover the gap.
- **Wayland reload rule:** JS changes need a full log out/in. `gnome-extensions
  disable`+`enable` reloads **stylesheet.css only**. Collector changes need
  nothing.
- **Headless test works and is worth it:**
  `dbus-run-session -- gnome-shell --headless --virtual-monitor 1280x720`, then
  `gnome-extensions enable` + `info` on that bus. `State: ACTIVE` with no
  `limitlens` lines in the shell log means `enable()`/`_init()` didn't throw.
  This also proves the subprocess path — check `stats.json`'s mtime afterwards.
- `gjs -m extension.js` outside the shell fails at `resource:///...` imports —
  expected; it still catches syntax errors (grep for SyntaxError).
- GNOME screenshot D-Bus is Access-denied for CLI; ask the owner for
  screenshots.
- An unrelated `tokenbar@devded.pm.me` extension (from an earlier Antigravity
  experiment in `~/Downloads/Workspace/tokeng`) may be installed. Different
  UUID, no conflict, but disable it to avoid two indicators.

## Workflow

```sh
./install.sh                 # collector + CLI + extension, then one collection
limitlens                    # dashboard
limitlens --json             # what the extension renders
/usr/bin/python3 -m py_compile lib/limitlens/*.py lib/limitlens/providers/*.py
```


Extension changes: `./install.sh`, then owner logs out/in (JS) or
disable+enable (CSS only).

## Current state & TODO

- Working end to end: extension `ACTIVE` in a headless shell, spawning the
  collector (3 ms incremental), rendering `stats.json`. CLI dashboard works.
- First full scan: 0.96 s for 116 MB / 113 transcripts.
- **Not yet done:**
  - [ ] Owner has not yet logged out/in, so the indicator hasn't been seen in a
        live session — panel visuals unconfirmed on real hardware.
  - [x] Antigravity verified against the owner's own `/usage` panel:
        86.71% remaining weekly / 80.82% remaining 5h matched the collector's
        13.4% / 19.9% used, plan "Pro".
  - [x] Claude verified end to end through the status line hook: the file is
        rewritten by Claude Code on every render (observed 0 s old), and the
        collector reads it in 0.09 s with no subprocess.
  - [x] The pty fallback verified independently against the owner's `/usage`
        (72% session / 0% weekly at the time).
  - [ ] No git repo yet; no LICENSE-referenced release.
  - [ ] opencode would be a cheap addition (sqlite, per-session cost + tokens).
  - [ ] Consider a `--since`/history view; daily totals are already retained.
