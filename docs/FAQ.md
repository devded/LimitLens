# FAQ

## What exactly does it show?

The limit windows each provider enforces, as that provider reports them:

- **Claude Code** — the 5-hour session window and the weekly window(s), with
  the percentage used and when each resets.
- **Antigravity (`agy`)** — the per-model request quota, as a percentage
  consumed, with the reset time.

Nothing is counted locally and nothing is estimated. If a provider can't be
reached, you get a warning line rather than a made-up number.

## Where do the numbers come from?

| Provider | Source | Credential |
|---|---|---|
| Claude | Claude Code's `/usage` panel, driven over a pty | none — the CLI uses its own |
| Antigravity | `POST http://127.0.0.1:<port>/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary` | none — loopback |

Neither path needs a credential of its own, and nothing is ever written to your
CLI's config.

## How does Antigravity work without a token?

While `agy` is running it hosts a language server on a loopback port, and that
server answers the exact RPC its own `/usage` panel is drawn from. The request
never leaves the machine, so there is no credential and no rate limit.

The response is grouped as the panel shows it — "Gemini Models" and "Claude and
GPT models", each with a weekly and a 5-hour bucket. Note `remainingFraction`
is what's **left**, so limitlens shows `1 - remainingFraction` as used: your
86.71% remaining is displayed as 13.3% used.

The port only exists while `agy` is running. When it isn't, the last reading is
shown flagged stale rather than dropped.

Two other routes were tried and rejected. Google's Code Assist API
(`cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota`) answers with the
token from the system keyring, but reports a *different quota pool* —
`gemini-2.5-*` buckets that sit at 100% remaining no matter how much you use
`agy`. Its `:retrieveUserQuotaSummary` sibling returns `403 PERMISSION_DENIED`.
Shipping either would have looked right and been wrong.

## Why a percentage in the panel instead of a token count?

Because the percentage is the number that changes what you do. Tokens tell you
what you already spent; the percentage tells you how much room is left before
the CLI stops answering. The panel shows the highest limit in use across all
providers, so `◑ 50%` means your most-consumed window is half gone.

## What does the `*` after the percentage mean?

The reading is stale — the last refresh failed, so limitlens is showing the
previous value rather than silently dropping the row or presenting an old
number as current. The menu spells out why in a warning line.

## Why does it drive the CLI instead of calling the API?

Because Anthropic's `/api/oauth/usage` endpoint rate-limits far more
aggressively than a read-only stats endpoint should. Tools polling it every
30–60 s get stuck in permanent 429 loops, and repeated retries can leave the
OAuth token in a degraded state where the 429s outlast the nominal window — see
claude-code [#31021](https://github.com/anthropics/claude-code/issues/31021),
[#30930](https://github.com/anthropics/claude-code/issues/30930),
[#31637](https://github.com/anthropics/claude-code/issues/31637); CodexBar hit
the same wall in [#575](https://github.com/steipete/CodexBar/issues/575).
During this project's own build it stayed blocked for the better part of an
hour.

Claude Code's `/usage` panel keeps working throughout, so that is what
limitlens reads. Advantages: identical numbers to what you see, no rate limit,
no token handling, and no risk of desyncing Claude Code's OAuth refresh token
(a real failure mode — CodexBar
[#1161](https://github.com/steipete/CodexBar/issues/1161)).

The cost is a subprocess that takes about six seconds, so Claude is polled
every 10 minutes rather than continuously. Limit windows are hours wide, so
this loses nothing.

## Does any of this use tokens or quota?

No — verified two ways rather than assumed:

- The probe session's own summary reads `$0.0000` and `0 input, 0 output,
  0 cache read, 0 cache write`.
- The 5-hour percentage is unchanged across a forced probe (88% → 88%).

`/usage` renders locally from data the CLI already has, so nothing is inferred
and no request is billed. The probe runs with `--allowed-tools ""` in a scratch
directory, and the transcript it leaves is deleted afterwards.

The one real side effect: each probe increments Claude Code's `numStartups` and
adds a project entry to `~/.claude.json`, slightly skewing its own session
stats. Installing the status line hook avoids this — with it, the probe
effectively never runs.

## What does it cost to run?

Measured on the author's machine. Nothing is resident between polls.

| | with the hook | without it |
|---|---|---|
| per collection | 0.09 s, 26 MB | 6.4 s, 369 MB |
| total CPU per hour | 6.9 s (0.19% of a core) | 22 s (0.62%) |

The hook itself is ~20 ms per call and Claude Code calls it roughly three times
a minute, so it adds about 4.5 s of CPU an hour and ~20 ms of latency to a
status line render. It is deliberately a standalone, import-light script — the
first version went through the full `limitlens` entry point and cost 80 ms,
which is a poor trade for something in a UI render path.

It does need a pty: in `--print` mode `/usage` returns only the local
"what's contributing to your limits" analysis, because the percentage panel is
drawn by the interactive UI.


## Claude says "token expired"

Claude Code refreshes its own token; if you haven't run `claude` in a while the
stored one goes stale. Run `claude` once and the next poll picks it up.
LimitLens deliberately does not attempt a refresh itself — that would mean
handling your refresh token, which it has no business doing.

## Does it send anything anywhere?

Two requests, both to the provider you're already using, both authenticated as
you, both read-only: your Claude usage and your Antigravity quota. Nothing else
leaves the machine. No telemetry, no analytics, no third parties.

## Does it slow down my desktop?

No. GNOME Shell extensions run inside the compositor, so a network call on the
main loop can stutter the desktop if it hangs. All requests happen in a separate
Python process; the extension only reads a few KB of JSON from disk.

## Can I turn one provider off?

`~/.config/limitlens/config.json`:

```json
{ "providers": ["claude"] }
```

Valid names are `claude` and `agy`; the default is both.

## Where is my data stored?

`~/.local/share/limitlens/` — `state.json` (last reading per provider, plus
any active cooldown) and `stats.json` (what the UIs render). Delete both to
start clean; the next poll rebuilds them. No credentials are ever copied there.

