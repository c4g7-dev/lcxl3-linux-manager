# LCXL3 Linux Manager

**The missing Linux companion app for the Novation Launch Control XL MK3.**

Novation ships Components for macOS/Windows — but nothing for Linux. This app fills that gap: full RGB LED control, OLED display text, MIDI forwarding with safe CC remapping, persistent fader/knob state, profiles, and a dark native GUI. Runs on any distro with ALSA and PipeWire (or JACK).

## Features

- **Full RGB LED control** — 16.7M colors on all 48 LEDs (24 knobs, 16 buttons, 8 side buttons) via MK3 DAW-mode SysEx
- **LED modes** — Static, Momentary (lit while held), Toggle (flip on each press)
- **OLED display text** — set a persistent custom text on the controller's built-in screen
- **LED brightness control** — global brightness slider (0–127)
- **Gradient tool** — paint color gradients across rows, columns, or all elements
- **Multi-select** — Ctrl+click individual LEDs or drag-select regions
- **Scene profiles** — save / load / rename / copy / delete named LED + display + brightness layouts
- **MIDI forwarding** — remaps DAW-mode CCs to safe numbers (avoids CC7/10/11 conflicts) and forwards through a persistent VirMIDI port
- **Persistent CC state** — fader/knob positions are saved per-profile and replayed to downstream apps on startup — no need to touch every control after reboot
- **Auto-reconnect** — detects when the controller is plugged in or unplugged
- **System tray** — minimize to tray, quick scene switching, `--minimized` flag for headless autostart
- **Single instance** — prevents duplicate app launches
- **Dark theme** — native dark UI that matches the hardware aesthetic

## Requirements

- Python 3.10+
- Linux with ALSA (Arch, Fedora, Ubuntu, etc.)
- PipeWire or JACK for MIDI routing (optional but recommended)
- `snd-virmidi` kernel module (for persistent MIDI forwarding port)

## Installation

```bash
git clone https://github.com/c4g7-dev/lcxl3-linux-manager.git
cd lcxl3-linux-manager

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Persistent MIDI forwarding port (optional)

To create a stable virtual MIDI port that survives app restarts (so Carla, Reaper, etc. auto-reconnect):

```bash
# Load the kernel module
sudo modprobe snd-virmidi midi_devs=1 index=20 id=LCXL3_Fwd

# Make it permanent across reboots
echo 'snd-virmidi' | sudo tee /etc/modules-load.d/virmidi.conf
echo 'options snd-virmidi midi_devs=1 index=20 id=LCXL3_Fwd' | sudo tee /etc/modprobe.d/virmidi.conf
```

## Usage

```bash
# GUI mode
python -m launch_control_xl.main

# Start minimized to system tray (for autostart)
python -m launch_control_xl.main --minimized
```

### Hyprland / Sway autostart

```ini
exec-once = sleep 5 && cd /path/to/lcxl3-linux-manager && .venv/bin/python -m launch_control_xl.main --minimized
```

### Quick start

1. Plug in the Launch Control XL MK3 via USB
2. Run the app — it auto-detects the device and enters DAW mode
3. Click any LED in the visual layout (Ctrl+click for multi-select)
4. Pick a color and mode in the editor panel
5. Save your layout as a profile

### MIDI forwarding

The app remaps DAW-mode CC numbers to avoid conflicts with reserved MIDI CCs:

| Control | DAW-mode CC | Forwarded CC | Channel |
|---------|------------|--------------|---------|
| Faders 1–8 | CC 5–12 | CC 20–27 | 1 |
| Knobs 1–24 | CC 13–36 | CC 41–64 | 1 |
| Buttons 1–16 | CC 37–52 | CC 65–80 | 1 |

Connect your DAW to the `VirMIDI 20-0` / `Virtual Raw MIDI 20-0` port for MIDI Learn.

## Project Structure

```
launch_control_xl/
├── main.py              # Entry point, single-instance lock, CLI flags
├── led_state.py         # RGB color model, LED config, controller state, CC tracking
├── midi_backend.py      # MIDI I/O — DAW mode, SysEx LEDs, CC remap, VirMIDI forwarding
├── presets.py           # Scene save/load (JSON), factory defaults
├── resources/
│   └── icon.svg         # App icon
└── gui/
    ├── main_window.py       # Main window, toolbar, tray, MIDI callbacks
    ├── controller_widget.py # Visual LCXL3 layout with interactive LEDs
    ├── color_editor.py      # Color picker, mode selector, gradient tool
    └── scene_panel.py       # Profile list management
```

## Troubleshooting

**"Disconnected" in toolbar:**
- Check `amidi -l` — the device should appear as `LCXL3`
- Try unplugging and replugging the controller

**No MIDI data in DAW:**
- Ensure `snd-virmidi` is loaded: `lsmod | grep virmidi`
- In your DAW, select `VirMIDI 20-0` as the MIDI input
- Move a fader to verify data flows

**LEDs not changing:**
- The app uses MK3 DAW mode — make sure you have the **MK3** (not the original LCXL)
- The app enters DAW mode automatically on connect

## License

MIT
