#!/usr/bin/env bash
# lcxl3-leds-off.sh — Turn off all 48 LEDs on the Novation LCXL MK3.
#
# Uses amidi (alsa-utils) to send raw SysEx directly — no Python needed.
# Called by the lcxl3-leds-off.service systemd unit on shutdown.
#
# SysEx format per LED:
#   F0 00 20 29 02 15 01 53 <idx> 00 00 00 F7
#   (Novation LCXL MK3 DAW-mode RGB set to black)

set -euo pipefail

# Auto-detect the LCXL3 DAW MIDI port
PORT=$(amidi -l 2>/dev/null | grep -i 'lcxl.*daw' | awk '{print $2}' | head -1)

if [[ -z "$PORT" ]]; then
    echo "LCXL MK3 not found — skipping LED shutdown." >&2
    exit 0
fi

echo "Turning off LEDs on $PORT ..."

# Enter DAW mode: Note On ch16 (0x9F) note 12 (0x0C) velocity 127 (0x7F)
amidi -p "$PORT" -S '9F 0C 7F'
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
