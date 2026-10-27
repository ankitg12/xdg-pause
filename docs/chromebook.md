# xdg-pause on Chromebook (dev-mode / Crostini)

Same repo, same tool, third backend. No `chromebook-pause`, no `crostini-pause`.

## Which path applies

| Chromebook state | Path | Strict mini-break? |
|---|---|---|
| Dev-mode + Linux container (penguin) | `crostini/install.sh` below; backend auto-detects `chromeos` | No — best-effort window, Esc is the host's hatch |
| Stock ChromeOS, no Linux | Not supported by this repo; needs the PWA idea in the README roadmap | No — Chrome reserves hold-Esc exit |

## Why not a separate repo

Crostini is an implementation detail ("Linux on ChromeOS"), already renamed
once. The durable IP — cadence semantics (`auto` long-window `:45–:54`),
`config.json` schema, hooks payload, snooze UX — is identical. The only things
that differ are window placement and scheduling, both isolated behind
`_select_backend()` and `_has_systemd_user()`. A fork would duplicate the
spec and drift within a quarter.

## What the chromeos backend does

- **Detection** (`XDG_PAUSE_BACKEND=auto`, the default): Sommelier env,
  `/dev/.cros_milestone`, `crosvm`/`chromebook` DMI product. Force with
  `XDG_PAUSE_BACKEND=chromeos|x11|layer-shell`.
- **One fullscreen window** instead of per-monitor surfaces. Sommelier bridges
  X11; ChromeOS owns compositing, Alt+Tab, and Overview — there is no
  layer-shell, no key grab, no `Gdk.fullscreen_on_monitor` worth calling.
- **Strict degrades to friction, honestly.** Mini breaks are Esc-exitable on
  ChromeOS (the host always wins). The overlay logs this, routes Esc through
  the same reason-prompt friction as desktop long breaks, and never pretends
  to swallow keys it cannot reach.
- **GNOME paths skipped**: no overview suppressor, no switcher suspend, no
  Mutter Xauthority hunt.
- Everything else is shared: `LocaleAdapter`, progress bar, clock,
  `break_start`/`break_complete`/`early_exit` hooks, `$XDG_RUNTIME_DIR/xdg-pause.active`
  marker (so dictation tools still defer).

## Scheduling without systemd

`systemd --user` timers die with the Crostini session (no linger, lid-sleep).
`xdg-pause snooze` therefore writes a **file marker** first
(`~/.local/state/xdg-pause/snoozed-until`, epoch seconds):

- `snooze 90` → marker + (if systemd exists) transient resume timer.
- `snooze start` / indefinite → far-future epoch, cleared by `snooze end`.
- `main()` and the loop both SKIP while the marker is in the future.
- `snooze status` reports the marker when systemd is absent.

## Install (inside penguin)

```bash
bash crostini/install.sh
```

Installs GTK3/PyGObject + fonts, `pip install --user .`, writes a first-run
config, registers `~/.config/autostart/xdg-pause-loop.desktop`, and starts
`crostini/pause-loop.sh` immediately. The loop sleeps to the next exact
10-minute wall-clock boundary and fires `xdg-pause auto` — the same cadence
as `systemd/xdg-pause.timer` (`OnCalendar=*:0/10:00`).

## Manual checks on the Chromebook

```bash
XDG_PAUSE_BACKEND=chromeos xdg-pause 10   # 10s overlay, single window
xdg-pause snooze 5 && xdg-pause snooze status
xdg-pause auto                            # SKIP while snoozed, else overlay
```

## Known limits (documented, not hidden)

1. Esc / window-close always exits on ChromeOS. Friction (reason prompt),
   not enforcement.
2. One window: external monitors show the Chromebook's normal desktop behind
   the fullscreen surface only on the display Sommelier targets.
3. The loop is a plain `sleep`; deep lid-sleep pauses it. On wake it fires
   once and realigns — no catch-up storm.
