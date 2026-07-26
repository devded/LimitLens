# LimitLens

AI CLI usage limits in the Ubuntu/GNOME top bar, inspired by the macOS menu bar
app [CodexBar](https://github.com/steipete/CodexBar).

```
              ┌───────────┐
   top bar →  │  ◑ 50%    │        ← highest limit in use, text-only
              ├───────────┴──────────────────────────────┐
              │ Claude · Pro                             │
              │   Session (5h)  ▓▓▓░░░░░  14%   2h 14m   │
              │   Weekly        ▓▓▓▓▓░░░  50%   4h       │
              │ Antigravity · Pro                        │
              │   Gemini · 5h     █████░░  20%   3h 54m  │
              │   Gemini · Weekly ███░░░░  13%   2d 12h  │
              └──────────────────────────────────────────┘
```

Every number comes from the provider's own API. Nothing is inferred from local
logs, and no usage is estimated.

## What it shows

| Provider | Limits | Source |
|---|---|---|
| **Claude Code** | session (5h) and weekly windows, % used + reset time | Claude Code's status line hook (free), or its `/usage` panel as fallback |
| **Antigravity (`agy`)** | per model-group 5-hour and weekly limits, % used + reset time | its language server's `RetrieveUserQuotaSummary` on loopback |

Neither needs a login, a key, or a token you have to paste.

- **Claude** — the obvious source is `GET /api/oauth/usage`, and it works, but
  it rate-limits so aggressively that it is unusable for monitoring: tools
  polling it every 30–60 s get stuck in permanent 429 loops, and repeated
  retries can leave the OAuth token degraded (claude-code
  [#31021](https://github.com/anthropics/claude-code/issues/31021),
  [#30930](https://github.com/anthropics/claude-code/issues/30930),
  [#31637](https://github.com/anthropics/claude-code/issues/31637)). Claude
  Code's `/usage` panel keeps working throughout, so limitlens reads that
  instead — the same numbers you see, with no rate limit and no token handling.
  It costs no tokens: the panel is rendered locally.
- **Antigravity** — while `agy` runs it hosts a language server on a loopback
  port, which answers the exact RPC its own `/usage` panel is drawn from. No
  credential is needed: the request never leaves the machine. When `agy` isn't
  running, the last reading is shown and flagged stale.

## Install

```sh
git clone https://github.com/devded/LimitLens.git
cd LimitLens
./install.sh
limitlens --install-hook     # recommended — see below
```

Then **log out and back in** (GNOME on Wayland can't load new extension code
without a session restart) and enable it:

```sh
gnome-extensions enable limitlens@devded.pm.me
```

Full instructions, updating and uninstalling: **[docs/INSTALL.md](docs/INSTALL.md)**

## Terminal

```sh
limitlens            # print the limits
limitlens --watch    # redraw every 60s
limitlens --json     # raw stats document
```

```
  LIMITLENS   Mon 27 Jul 01:15

  Claude · Pro
    Session (5h)         ███░░░░░░░░░░░░░░░░░░░░░  14.0%  resets in 2h 14m
    Weekly               ████████████░░░░░░░░░░░░  50.0%  resets in 4h
  Antigravity · Pro
    Gemini · 5h              █████░░░░░░░░░░░░░░░░░░░  19.9%  resets in 3h 54m
    Gemini · Weekly          ███░░░░░░░░░░░░░░░░░░░░░  13.4%  resets in 2d 12h
    Claude and GPT · Weekly  ░░░░░░░░░░░░░░░░░░░░░░░░   0.0%  resets in 6d 23h
```

## The status line hook (recommended)

Claude Code runs a status line command on every render and hands it a JSON blob
that already contains what we want:

```json
"rate_limits": {
  "five_hour": {"used_percentage": 81, "resets_at": 1785115800},
  "seven_day": {"used_percentage": 1,  "resets_at": 1785708000}
}
```

`limitlens --install-hook` wires that up, so **Claude Code pushes its limits to
limitlens instead of limitlens polling for them**. No subprocess, no request,
no rate limit. It also prints a compact `Opus 5 · 5h 81% · week 1%` status line,
and if you already had a status line command it is kept and chained, not
replaced. `limitlens --uninstall-hook` restores exactly what was there before.

Without the hook everything still works — the `/usage` panel is driven over a
pty instead — it just costs a great deal more (see below).

A stale hook reading is still used: your usage cannot rise while Claude Code is
closed, and a reading whose window has already reset is discarded rather than
shown.

## Resource use

Measured, not estimated. Nothing stays resident between polls — the collector
exits after each run.

| | with the hook | without it |
|---|---|---|
| per collection | 0.09 s, 26 MB | 6.4 s, **369 MB** |
| collector CPU per hour | 2.4 s | 22 s |
| hook CPU per hour | 4.5 s (~3 calls/min × 20 ms) | — |
| **total CPU per hour** | **6.9 s (0.19% of a core)** | 22 s (0.62%) |
| `claude` spawns per hour | 0 | 6 |

The hook runs inside Claude Code's status line render path, so it is kept
import-light: a standalone script with `-S`, not `limitlens --statusline`,
which pulled in the whole package and cost 80 ms instead of 20 ms.

The 369 MB is the `claude` CLI itself booting Node to render one panel; the
26 MB is the Python interpreter. The extension adds two GLib timers and ~10
St actors inside `gnome-shell`, and re-reads a 1.2 KB file every 5 s.

The pty probe also has a side effect the hook avoids: each run increments
Claude Code's `numStartups` and adds a project entry to `~/.claude.json`,
skewing its own session stats.

## Does any of this use tokens?

No, and it is worth being precise about it because the fallback literally runs
Claude Code:

- The **status line hook** is a local file write. It never contacts the API.
- The **pty probe** opens the CLI to read a panel that is rendered locally. Its
  own session summary reports `$0.0000` and `0 input, 0 output, 0 cache read,
  0 cache write`, and the 5-hour percentage is identical before and after a
  probe (measured 88% → 88%).
- The Anthropic **usage API is not called at all**.

The probe does spawn the real CLI, so it costs a few seconds of CPU and
increments Claude Code's `numStartups`. It does not touch your quota.

## Panel behaviour

The panel shows the **highest limit in use** across all providers — the number
that tells you how much room is left. The glyph fills as the limit does
(`○ ◔ ◑ ◕ ●`), turning amber at 75% and red at 90%. A trailing `*` means the
reading could not be refreshed and is being shown stale rather than dropped.

## How it works

GNOME Shell extensions run *inside* the compositor, so a network call on the
main loop can stutter the desktop if it hangs. Instead a small Python collector
does the requests out of process and writes a few KB of JSON; the extension only
renders that file.

- Claude is polled every 10 minutes (it spawns the CLI, ~6 s), Antigravity
  every 2 minutes (a loopback call, near-free). Limit windows are hours wide,
  so nothing is lost.
- Every failure is caught. A provider that can't be read contributes a warning
  line and keeps showing its last reading, flagged stale, instead of breaking
  the panel.
- The pty probe runs the CLI with `--allowed-tools ""` in a scratch directory
  and deletes the transcript it leaves behind.

## Repository layout

```
extension/          GNOME Shell extension (renders stats.json)
  extension.js
  metadata.json
  stylesheet.css
hooks/
  limitlens-statusline  the status line hook (standalone, import-light)
lib/limitlens/      collector + CLI
  collect.py          one collection pass over all providers
  hook.py             install/remove the status line hook
  state.py            cache + atomic stats.json write
  util.py             reset formatting, severity
  providers/
    claude.py             picks the cheapest available source
    claude_statusline.py  reads what the hook recorded (free)
    claude_cli.py         drives the /usage panel over a pty (fallback)
    antigravity.py        agy language server RPC on loopback
install.sh
docs/
```

Runtime data lives in `~/.local/share/limitlens/`: `state.json` (cached
readings) and `stats.json` (what the UIs render).

## Adding a provider

A provider module needs one function:

```python
def fetch(cache, force=False):
    """Return (rows, warning, new_cache).  Must never raise."""
```

where each row is `{provider, plan, label, percent, resets_at}`. Register it in
`PROVIDERS` in `collect.py`. Severity, sorting, staleness and the panel value
are derived centrally.

## License

MIT

