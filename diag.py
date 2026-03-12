#!/usr/bin/env python3
"""Diagnostic script for the Launch Control XL MK3 (LCXL3).

Run this, then press buttons/knobs on the controller. It will:
1. Try to detect and connect to the device
2. Listen for all incoming MIDI messages 
3. Try various LED control methods
"""
import sys
import time
import mido

print("=== LCXL3 Diagnostic Tool ===\n")

# 1. List all MIDI ports
print("--- Available MIDI Ports ---")
print("Inputs:")
for name in mido.get_input_names():
    print(f"  IN:  {name}")
print("Outputs:")
for name in mido.get_output_names():
    print(f"  OUT: {name}")

# 2. Find LCXL3 ports
inputs = [n for n in mido.get_input_names() if 'lcxl' in n.lower()]
outputs = [n for n in mido.get_output_names() if 'lcxl' in n.lower()]

if not inputs or not outputs:
    print("\nERROR: LCXL3 not found!")
    sys.exit(1)

print(f"\nFound LCXL3 inputs:  {inputs}")
print(f"Found LCXL3 outputs: {outputs}")

# 3. Open ALL ports
outports = []
for name in outputs:
    try:
        port = mido.open_output(name)
        outports.append((name, port))
        print(f"Opened output: {name}")
    except Exception as e:
        print(f"Failed to open output {name}: {e}")

inports = []
for name in inputs:
    try:
        port = mido.open_input(name)
        inports.append((name, port))
        print(f"Opened input: {name}")
    except Exception as e:
        print(f"Failed to open input {name}: {e}")

# 4. Try LED control methods on each output
print("\n--- Testing LED Control ---")

# The LCXL MK3 might use different protocol than original LCXL
# Try multiple approaches:

for out_name, outport in outports:
    print(f"\n>> Testing output: {out_name}")
    
    # Method A: Note On (original LCXL protocol, channel 0)
    print("  [A] Note On ch0, notes 41-44, velocity 15 (red)...")
    for note in [41, 42, 43, 44]:
        outport.send(mido.Message('note_on', channel=0, note=note, velocity=15))
    time.sleep(0.5)
    
    # Method B: Note On channel 8 (original LCXL bank 1)
    print("  [B] Note On ch8, notes 41-44, velocity 60 (green)...")
    for note in [41, 42, 43, 44]:
        outport.send(mido.Message('note_on', channel=8, note=note, velocity=60))
    time.sleep(0.5)
    
    # Method C: Note On channel 0, notes 73-76 (bottom row)
    print("  [C] Note On ch0, notes 73-76, velocity 63 (amber)...")
    for note in [73, 74, 75, 76]:
        outport.send(mido.Message('note_on', channel=0, note=note, velocity=63))
    time.sleep(0.5)
    
    # Method D: CC on channel 0 for knob LEDs
    print("  [D] CC ch0, controllers 13-20 value 127 (knob row 1)...")
    for cc in range(13, 21):
        outport.send(mido.Message('control_change', channel=0, control=cc, value=127))
    time.sleep(0.5)
    
    # Method E: SysEx original LCXL header (02 11)
    print("  [E] SysEx (original LCXL header 02 11) knob 0 red...")
    outport.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x11, 0x78, 0x08, 0x00, 0x0F]))
    time.sleep(0.3)
    
    # Method F: SysEx MK3 header (02 13) — guessing product ID
    print("  [F] SysEx (MK3 guess 02 13) knob 0 red...")
    outport.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x13, 0x78, 0x08, 0x00, 0x0F]))
    time.sleep(0.3)
    
    # Method G: Device inquiry
    print("  [G] Sending Universal Device Identity Request...")
    outport.send(mido.Message('sysex', data=[0x7E, 0x7F, 0x06, 0x01]))
    time.sleep(0.5)
    
    # Method H: Note On ch0 with different note ranges (MK3 might remap)
    print("  [H] Note On ch0, notes 0-15, velocity 15 (scanning)...")
    for note in range(16):
        outport.send(mido.Message('note_on', channel=0, note=note, velocity=15))
    time.sleep(0.5)

    # Method I: Note On ch0, notes 96-111 (higher range)
    print("  [I] Note On ch0, notes 96-111, velocity 60 (green, high range)...")
    for note in range(96, 112):
        outport.send(mido.Message('note_on', channel=0, note=note, velocity=60))
    time.sleep(0.5)

print("\n--- Listening for MIDI input (15 seconds) ---")
print("*** PRESS BUTTONS AND TURN KNOBS NOW ***\n")

start = time.time()
messages_seen = set()
while time.time() - start < 15:
    for in_name, inport in inports:
        for msg in inport.iter_pending():
            key = f"{in_name}: {msg}"
            if msg.type not in ('clock', 'active_sensing'):
                # For CC, only show when value changes significantly 
                if msg.type == 'control_change':
                    summary = f"{in_name}: CC ch{msg.channel} ctrl={msg.control} val={msg.value}"
                elif msg.type == 'note_on':
                    summary = f"{in_name}: NOTE ON ch{msg.channel} note={msg.note} vel={msg.velocity}"
                elif msg.type == 'note_off':
                    summary = f"{in_name}: NOTE OFF ch{msg.channel} note={msg.note}"
                elif msg.type == 'sysex':
                    hex_data = ' '.join(f'{b:02X}' for b in msg.data)
                    summary = f"{in_name}: SYSEX [{hex_data}]"
                else:
                    summary = f"{in_name}: {msg.type} {msg}"
                
                if summary not in messages_seen:
                    print(f"  {summary}")
                    messages_seen.add(summary)
    time.sleep(0.01)

print(f"\nTotal unique messages: {len(messages_seen)}")

# Cleanup
for _, port in outports + inports:
    port.close()

print("\nDone. Check which LED method worked (if any lit up on the controller).")
