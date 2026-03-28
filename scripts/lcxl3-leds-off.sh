#!/usr/bin/env bash
# lcxl3-leds-off.sh — Turn off all 48 LEDs on the Novation LCXL MK3.
#
# Uses amidi (alsa-utils) to send raw SysEx directly — no Python needed.
# Called by the lcxl3-leds-off.service systemd unit on shutdown.
#
# Strategy:
#   1. Kill the LCXL3 manager app (SIGTERM) — its shutdown handler turns
#      LEDs off and releases the MIDI port.
#   2. Fall back to amidi if the app wasn't running or the port is still lit.
#
# SysEx format per LED:
#   F0 00 20 29 02 15 01 53 <idx> 00 00 00 F7
#   (Novation LCXL MK3 DAW-mode RGB set to black)

set -uo pipefail

# Step 1: Ask the app to quit gracefully (its _shutdown() resets LEDs)
APP_PID=$(pgrep -f 'launch_control_xl\.main' || true)
if [[ -n "$APP_PID" ]]; then
    echo "Stopping LCXL3 manager (PID $APP_PID) ..."
    kill -TERM $APP_PID 2>/dev/null || true
    # Wait up to 3s for the app to release the port
    for i in $(seq 1 30); do
        kill -0 $APP_PID 2>/dev/null || break
        sleep 0.1
    done
fi

# Step 2: Auto-detect the LCXL3 DAW MIDI port
PORT=$(amidi -l 2>/dev/null | grep -i 'lcxl.*daw' | awk '{print $2}' | head -1)

if [[ -z "$PORT" ]]; then
    echo "LCXL MK3 not found — skipping LED shutdown." >&2
    exit 0
fi

echo "Turning off LEDs on $PORT ..."

# Enter DAW mode: Note On ch16 (0x9F) note 12 (0x0C) velocity 127 (0x7F)
amidi -p "$PORT" -S '9F 0C 7F' 2>/dev/null || {
    echo "Port busy or unavailable — app likely already handled LED shutdown." >&2
    exit 0
}
sleep 0.05

# All 48 LED indices (knobs 13-36, buttons 37-52, side 65,66,102,103,106,107,116,118)
LED_IDS=(
    13 14 15 16 17 18 19 20
    21 22 23 24 25 26 27 28
    29 30 31 32 33 34 35 36
    37 38 39 40 41 42 43 44
    45 46 47 48 49 50 51 52
    65 66 102 103 106 107 116 118
)

for idx in "${LED_IDS[@]}"; do
    hex=$(printf '%02X' "$idx")
    amidi -p "$PORT" -S "F0 00 20 29 02 15 01 53 ${hex} 00 00 00 F7"
done

echo "All LEDs off."
