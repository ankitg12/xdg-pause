#!/bin/sh
# pause-loop.sh — Crostini cadence scheduler for xdg-pause.
# Why: systemd --user timers are unreliable inside Crostini (no linger, the
# container sleeps with the lid, resume units get lost). This loop sleeps to
# the next 10-minute boundary and fires `xdg-pause auto`, exactly mirroring
# systemd/xdg-pause.timer (OnCalendar=*:0/10:00, long breaks at :45-:54).
# It honors the same SKIP guards as the timer path: `xdg-pause main` exits 0
# immediately when an overlay is already up or the file snooze marker is set.
#
# Usage: pause-loop.sh [pause-binary]
#   nohup ./pause-loop.sh >/dev/null 2>&1 &
# Logging: echoes to stdout; redirect to a logfile or run under the
# autostart entry created by crostini/install.sh.
set -u

BIN="${1:-xdg-pause}"
INTERVAL=600

log() {
    printf '%s pause-loop: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

if ! command -v "$BIN" >/dev/null 2>&1; then
    log "ERROR: '$BIN' not on PATH. Install it first (see crostini/install.sh)."
    exit 1
fi

log "started (backend: XDG_PAUSE_BACKEND=${XDG_PAUSE_BACKEND:-auto}, interval ${INTERVAL}s)"

while true; do
    now=$(date +%s)
    # Sleep to the next exact 10-minute wall-clock boundary (:00, :10, ...),
    # matching the systemd OnCalendar=*:0/10:00 cadence.
    next=$(( (now / INTERVAL + 1) * INTERVAL ))
    sleep_for=$(( next - now ))
    log "next break at $(date -d "@$next" '+%H:%M') (sleeping ${sleep_for}s)"
    sleep "$sleep_for"

    # If the machine slept past the boundary, skip the catch-up storm: fire
    # once and realign on the next iteration.
    if [ "$("$BIN" snooze status 2>/dev/null | grep -c snoozed)" -gt 0 ]; then
        log "snoozed — skipping this boundary"
        continue
    fi
    if ! "$BIN" auto; then
        log "break exited non-zero (overlay skipped or dismissed)"
    fi
done
