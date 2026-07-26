# LimitLens

Read **MEMORY.md** first — it holds the provider research (including every
endpoint that was tried and rejected, so you don't retry them), the design
decisions, and the GNOME/Wayland testing gotchas.

Quick facts:

- **Scope: usage limits only.** Claude Code session (5h) + weekly, and
  Antigravity per-model-group 5h + weekly. Percentages, reset times, nothing
  else. An earlier version counted tokens and cost from local logs; that was
  removed deliberately — don't reintroduce it.
- Every number comes from the provider's own API. Never estimate, never infer
  from local logs. A provider that can't be reached produces a warning line.
- Three parts: Python collector (`lib/limitlens/`) → `stats.json` → GNOME
  extension (`extension/`) + CLI. The extension does no network I/O.
- A provider module exposes `fetch(cache, force=False) -> (rows, warning, cache)`
  and must never raise. Register it in `PROVIDERS` in `collect.py`.
- Antigravity's numbers come from the **local `agy` language server** on a
  loopback port, not from a Google API. `remainingFraction` is what's LEFT.
- Claude's numbers come, in order: **the status line hook** (Claude Code hands
  us `rate_limits` for free — `limitlens --install-hook`), then **the `/usage`
  panel driven over a pty** (~325 MB, 6 s). Never `/api/oauth/usage` — that
  endpoint rate-limits so hard it is unusable. Don't "simplify" back to it.
- A stale hook reading is still valid: usage can't rise while Claude Code is
  closed. Only a reading past its window's reset is discarded.
- Use `/usr/bin/python3`. Extension JS changes need the owner to log out/in;
  CSS-only changes need disable+enable; collector changes need nothing.

