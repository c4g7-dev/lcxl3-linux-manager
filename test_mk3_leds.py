#!/usr/bin/env python3
"""Quick test: enter DAW mode on LCXL MK3, set some LEDs via RGB SysEx."""

import time
import mido

SYSEX_HEADER = [0x00, 0x20, 0x29, 0x02, 0x15]

def find_daw_port(names):
    for n in names:
        if "lcxl" in n.lower() and "daw" in n.lower():
            return n
    for n in names:
        if "lcxl" in n.lower():
            return n
    return None

def main():
    print("Output ports:", mido.get_output_names())
    print("Input ports:", mido.get_input_names())

    out_name = find_daw_port(mido.get_output_names())
    if not out_name:
        print("ERROR: No LCXL port found!")
        return
    print(f"\nUsing output: {out_name}")

    out = mido.open_output(out_name)

    # 1) Enter DAW mode: Note On ch16 (0-indexed 15), note 12, vel 127
    print("Entering DAW mode...")
    out.send(mido.Message("note_on", channel=15, note=0x0C, velocity=127))
    time.sleep(0.3)

    # 2) Set some LEDs via RGB SysEx
    #    F0 00 20 29 02 15 01 53 <control_index> <R> <G> <B> F7
    test_leds = [
        # Encoders row 1: CCs 13-20 — set to rainbow
        (13, 127, 0, 0),    # red
        (14, 127, 64, 0),   # orange
        (15, 127, 127, 0),  # yellow
        (16, 0, 127, 0),    # green
        (17, 0, 127, 127),  # cyan
        (18, 0, 0, 127),    # blue
        (19, 80, 0, 127),   # purple
        (20, 127, 0, 80),   # pink
        # Faders: CCs 5-12
        (5, 127, 127, 127), # white
        (6, 127, 0, 0),     # red
        # Buttons row 1: CCs 37-44
        (37, 0, 127, 0),    # green
        (38, 127, 0, 0),    # red
        (39, 0, 0, 127),    # blue
        (40, 127, 127, 0),  # yellow
    ]

    for cc, r, g, b in test_leds:
        data = SYSEX_HEADER + [0x01, 0x53, cc, r, g, b]
        out.send(mido.Message("sysex", data=data))
        print(f"  Set CC {cc} -> RGB({r},{g},{b})")
        time.sleep(0.02)

    print("\nLEDs should be lit! Press Enter to turn off and exit DAW mode...")
    input()

    # 3) Turn off all test LEDs
    for cc, _, _, _ in test_leds:
        data = SYSEX_HEADER + [0x01, 0x53, cc, 0, 0, 0]
        out.send(mido.Message("sysex", data=data))
        time.sleep(0.01)

    # 4) Exit DAW mode
    print("Exiting DAW mode...")
    out.send(mido.Message("note_on", channel=15, note=0x0C, velocity=0))
    time.sleep(0.1)

    out.close()
    print("Done.")

if __name__ == "__main__":
    main()
