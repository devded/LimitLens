# Install, update, uninstall

## Requirements

- GNOME Shell 45–50 (for the top bar extension; the CLI works anywhere)
- Python 3.9+, standard library only — no pip packages
- At least one supported CLI, signed in:
  - **Claude Code** (`claude` on `PATH`) — read by driving its `/usage` panel
  - **Antigravity** (`agy`) — read from its language server while it runs

On Ubuntu, use `/usr/bin/python3`. If `python3` resolves to a Homebrew build,
that's fine here — the collector imports nothing outside the standard library —
but the installer and the extension both call `/usr/bin/python3` explicitly.

## Install

```sh
git clone https://github.com/devded/LimitLens.git
cd LimitLens
./install.sh
```

The installer places three things:

| What | Where |
|---|---|
| collector library | `~/.local/share/limitlens/lib/limitlens/` |
| CLI | `~/.local/bin/limitlens` |
| GNOME extension | `~/.local/share/gnome-shell/extensions/limitlens@devded.pm.me/` |

It then polls each provider once so the panel has data immediately.

Install the status line hook — strongly recommended, it makes Claude Code hand
its limits over for free instead of limitlens spawning the CLI to read them
(0.09 s / 26 MB per poll instead of 6.4 s / 369 MB):

```sh
limitlens --install-hook     # limitlens --uninstall-hook to undo
```

It edits only `statusLine` in `~/.claude/settings.json`, keeps and chains any
status line command you already had, and restores it exactly on uninstall.
Restart Claude Code afterwards.

Enable the extension:

```sh
gnome-extensions enable limitlens@devded.pm.me
```

On Wayland, **new extension code only loads after a full log out and back in.**
If `gnome-extensions enable` reports the extension as `INITIALIZED` rather than
`ACTIVE`, that's what's missing.

## Verify

```sh
limitlens                    # dashboard
limitlens --json | head -30  # raw document
gnome-extensions info limitlens@devded.pm.me
```

`State: ACTIVE` means the top bar indicator is running.

## Configure

Optional, `~/.config/limitlens/config.json`:

```json
{ "providers": ["claude", "agy"] }
```

Valid names are `claude` and `agy`; the default is both. Removing one stops it
being polled and hides it from the panel.

## Update

```sh
cd LimitLens
git pull
./install.sh
```

Then log out and back in if `extension.js` changed. A change to
`stylesheet.css` alone only needs:

```sh
gnome-extensions disable limitlens@devded.pm.me
gnome-extensions enable limitlens@devded.pm.me
```

Collector-only changes take effect on the next collection — no restart at all.

## Uninstall

```sh
gnome-extensions disable limitlens@devded.pm.me
rm -rf ~/.local/share/gnome-shell/extensions/limitlens@devded.pm.me
rm -rf ~/.local/share/limitlens
rm -f  ~/.local/bin/limitlens
rm -rf ~/.config/limitlens
```

Nothing is written outside those paths, and no CLI's own files are ever
modified — limitlens only ever reads them.

## Troubleshooting

**Panel shows `…` and never updates.** The collector hasn't produced
`stats.json`. Run `limitlens` by hand and read the error. The most common cause
is `/usr/bin/python3` not existing (some distros ship only `python3` on `PATH`);
edit `PYTHON` at the top of `extension.js` if so.

**Panel shows `—`.** No limits could be read from any provider. Run
`limitlens` and read the warning lines — usually an expired token (run the CLI
in question once) or a locked keyring.

**Antigravity rows missing or stale.** Its language server only listens while
`agy` is running. Start `agy` and the next poll picks it up; until then the last
reading is shown flagged stale.

**Claude rows missing.** The probe needs `claude` on `PATH` and a signed-in CLI.
Run `claude` once by hand; if `/usage` shows the panel, limitlens will read it.

**Start over.** `rm ~/.local/share/limitlens/state.json` and run
`limitlens --force`.

