"""MIDI backend — detect the LCXL MK3, enter DAW mode, send RGB LED colours, receive input.

Forwards remapped CC messages to a persistent VirMIDI port (snd-virmidi)
so other applications (DAWs, Carla, etc.) receive controller data on a
stable ALSA port that survives app restarts.
"""

from __future__ import annotations

import glob
import os
import threading
import time
from typing import Callable, Dict, IO, Optional

import mido

from .led_state import (
    ALL_LED_ELEMENTS,
    BUTTON_ELEMENTS,
    FADER_ELEMENTS,
    KNOB_ELEMENTS,
    RGBColor,
    COLOR_OFF,
    ControllerState,
    Element,
    ElementKind,
)

# ---------------------------------------------------------------------------
# Constants — LCXL MK3
# ---------------------------------------------------------------------------
_DEVICE_SUBSTRING = "lcxl"

# SysEx header (without F0/F7 — mido adds those)
_SYSEX_HEADER = [0x00, 0x20, 0x29, 0x02, 0x15]

# DAW mode enable / disable via Note On on ch 16 (0-indexed ch 15)
_DAW_MODE_CHANNEL = 15
_DAW_MODE_NOTE = 0x0C  # 12

# RGB SysEx command: F0 00 20 29 02 15 01 53 <idx> <R> <G> <B> F7
_SYSEX_RGB_CMD = [0x01, 0x53]

# Colour via CC on channel 1 (0-indexed ch 0): B0 <control_index> <colour_index>
_COLOR_CC_CHANNEL = 0

# DAW mode button input arrives on channel 1 (0-indexed ch 0)
_BTN_INPUT_CHANNEL = 0
# Encoders/faders input on channel 16 (0-indexed ch 15)
_ANALOG_INPUT_CHANNEL = 15


# Display SysEx commands
# Configure display:  F0 00 20 29 02 15 04 <target> <config> F7
# Set text:           F0 00 20 29 02 15 06 <target> <field> <text...> F7
_SYSEX_DISPLAY_CONFIG = 0x04
_SYSEX_DISPLAY_TEXT = 0x06
_DISPLAY_STATIONARY = 0x35   # target: permanent display
_DISPLAY_OVERLAY = 0x36      # target: temporary/overlay display
# Config arrangement 1 = 2 lines (Name + Value), arrangement 4 = Name + numeric value
_DISPLAY_ARRANGEMENT_2LINE = 0x01

# Feature controls channel (ch 7, 0-indexed = 6)
_FEATURE_CC_CHANNEL = 6

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
_CC_TO_BUTTON: Dict[int, Element] = {e.hw_id: e for e in BUTTON_ELEMENTS}
_CC_TO_KNOB: Dict[int, Element] = {e.hw_id: e for e in KNOB_ELEMENTS}

# ---------------------------------------------------------------------------
# CC remap table for virtual-port forwarding
# ---------------------------------------------------------------------------
# DAW-mode uses CC numbers that clash with reserved MIDI CCs
# (CC7=Volume, CC10=Pan, CC11=Expression).  We remap to safe ranges
# so MIDI Learn in DAWs works reliably.  All forwarded on channel 1.
#
# Faders:  CC 5-12  (DAW ch16)  →  CC 20-27  (ch1)  [undefined range]
# Knobs:   CC 13-36 (DAW ch16)  →  CC 41-64  (ch1)  [general purpose]
# Buttons: CC 37-52 (DAW ch1)   →  CC 65-80  (ch1)  [no conflict]
_FORWARD_CHANNEL = 0  # remap everything to channel 1

_FADER_REMAP: Dict[int, int] = {5 + i: 20 + i for i in range(8)}    # 5→20 .. 12→27
_KNOB_REMAP: Dict[int, int] = {13 + i: 41 + i for i in range(24)}   # 13→41 .. 36→64
_BUTTON_REMAP: Dict[int, int] = {37 + i: 65 + i for i in range(16)} # 37→65 .. 52→80


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

class MidiBackend:
    """Manages bidirectional MIDI communication with the LCXL MK3 in DAW mode."""

    def __init__(self) -> None:
        self._outport: Optional[mido.ports.BaseOutput] = None
        self._inport: Optional[mido.ports.BaseInput] = None
        self._virtual_out: Optional[IO[bytes]] = None  # raw /dev/snd/midiC*D* file
        self._listen_thread: Optional[threading.Thread] = None
        self._running = False
        self._daw_mode = False
        self._brightness: int = 127  # current LED brightness (0-127)

        # Callbacks
        self.on_button_press: Optional[Callable[[Element], None]] = None
        self.on_button_release: Optional[Callable[[Element], None]] = None
        self.on_cc: Optional[Callable[[int, int], None]] = None  # (cc, value)
        self.on_disconnect: Optional[Callable[[], None]] = None
        self.on_connect: Optional[Callable[[], None]] = None

    # -- connection ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._outport is not None and not self._outport.closed

    @staticmethod
    def find_ports() -> tuple[Optional[str], Optional[str]]:
        """Return (input_name, output_name) for the DAW port, or (None, None)."""
        inp = out = None
        # Prefer the DAW port for full LED/button control
        for name in mido.get_input_names():
            low = name.lower()
            if _DEVICE_SUBSTRING in low and "daw" in low:
                inp = name
                break
        if inp is None:
            inp = next(
                (n for n in mido.get_input_names() if _DEVICE_SUBSTRING in n.lower()),
                None,
            )
        for name in mido.get_output_names():
            low = name.lower()
            if _DEVICE_SUBSTRING in low and "daw" in low:
                out = name
                break
        if out is None:
            out = next(
                (n for n in mido.get_output_names() if _DEVICE_SUBSTRING in n.lower()),
                None,
            )
        return inp, out

    @staticmethod
    def _open_virmidi_raw() -> Optional[IO[bytes]]:
        """Open the VirMIDI raw device for writing.

        Writing raw MIDI bytes to the device file makes them appear on the
        VirMIDI ALSA-sequencer port as *input*, which PipeWire then
        distributes to connected clients.  This is the correct data-flow
        direction — writing via the ALSA sequencer port would send data
        *into* the raw device instead.
        """
        # snd-virmidi creates /dev/snd/midiC<card>D<dev> devices.
        # With midi_devs=1 there is exactly one; pick the highest card
        # number so we don't accidentally grab a real hardware device.
        candidates = glob.glob("/dev/snd/midiC*D*")
        # Sort numerically by card number so highest card is last
        def _card_num(p: str) -> int:
            try:
                return int(p.split("midiC")[1].split("D")[0])
            except (IndexError, ValueError):
                return -1
        candidates.sort(key=_card_num)
        # Filter to VirMIDI cards by checking the ALSA card name
        for path in reversed(candidates):
            # Extract card number from path like /dev/snd/midiC6D0
            try:
                card_str = path.split("midiC")[1].split("D")[0]
                card_name_path = f"/sys/class/sound/card{card_str}/id"
                with open(card_name_path) as f:
                    card_id = f.read().strip()
                low_id = card_id.lower()
                if "virmidi" in low_id or "virtual" in low_id or "lcxl3" in low_id:
                    return open(path, "wb", buffering=0)
            except (IndexError, FileNotFoundError, OSError):
                continue
        # Fallback: pick the last candidate (highest card = most likely virmidi)
        if candidates:
            try:
                return open(candidates[-1], "wb", buffering=0)
            except OSError:
                return None
        return None

    def connect(self) -> bool:
        """Open the LCXL MK3 DAW port and enter DAW mode. Returns True on success."""
        self.disconnect()
        inp_name, out_name = self.find_ports()
        if not inp_name or not out_name:
            return False
        try:
            self._outport = mido.open_output(out_name)
            self._inport = mido.open_input(inp_name)
        except (IOError, OSError):
            self._outport = self._inport = None
            return False

        # Persistent VirMIDI raw device — write raw MIDI bytes here so they
        # appear on the ALSA sequencer port that PipeWire distributes.
        self._virtual_out = self._open_virmidi_raw()

        self._enter_daw_mode()
        self._start_listener()
        if self.on_connect:
            self.on_connect()
        return True

    def disconnect(self, exit_daw: bool = True) -> None:
        self._stop_listener()
        if exit_daw and self._daw_mode and self._outport and not self._outport.closed:
            self._exit_daw_mode()
        for port in (self._outport, self._inport):
            if port and not port.closed:
                try:
                    port.close()
                except Exception:
                    pass
        if self._virtual_out:
            try:
                self._virtual_out.close()
            except Exception:
                pass
        self._outport = self._inport = self._virtual_out = None

    # -- DAW mode -----------------------------------------------------------

    def _enter_daw_mode(self) -> None:
        """Send DAW-mode enable message and reset all LEDs."""
        if not self._outport:
            return
        # Note On ch16, note 12, velocity 127
        msg = mido.Message("note_on", channel=_DAW_MODE_CHANNEL,
                           note=_DAW_MODE_NOTE, velocity=127)
        self._outport.send(msg)
        self._daw_mode = True
        # Give the device time to switch mode before sending LED data
        time.sleep(0.05)
        # Clear all LEDs so stale palette colours from standalone don't leak
        self.reset_leds()

    def _exit_daw_mode(self) -> None:
        """Send DAW-mode disable message."""
        if not self._outport:
            return
        msg = mido.Message("note_on", channel=_DAW_MODE_CHANNEL,
                           note=_DAW_MODE_NOTE, velocity=0)
        self._outport.send(msg)
        self._daw_mode = False

    # -- sending LEDs -------------------------------------------------------

    def set_led_rgb(self, control_index: int, color: RGBColor) -> None:
        """Set an LED to an arbitrary RGB colour via SysEx."""
        if not self.connected:
            return
        data = _SYSEX_HEADER + _SYSEX_RGB_CMD + [
            control_index, color.r, color.g, color.b
        ]
        self._outport.send(mido.Message("sysex", data=data))

    def set_led(self, elem: Element, color: RGBColor) -> None:
        """Set any LED by element."""
        self.set_led_rgb(elem.hw_id, color)

    def push_all(self, state: ControllerState) -> None:
        """Push every LED colour from *state* to the hardware."""
        for i, elem in enumerate(ALL_LED_ELEMENTS):
            self.set_led(elem, state.current_color(elem))
            # Brief pause every 8 elements to avoid SysEx flood
            if (i + 1) % 8 == 0:
                time.sleep(0.005)

    def push_cc_state(self, state: ControllerState) -> None:
        """Replay all known CC positions to VirMIDI.

        Sends saved fader/knob values so downstream apps get the last-known
        positions immediately without requiring physical movement.
        """
        if not self._virtual_out or self._virtual_out.closed:
            return
        for cc, val in state.all_cc_values():
            fwd = self._remap_for_forward(
                mido.Message("control_change",
                             channel=_ANALOG_INPUT_CHANNEL,
                             control=cc, value=val))
            if fwd is not None:
                try:
                    self._virtual_out.write(fwd.bin())
                except (IOError, OSError):
                    return

    def push_toggle_state(self, state: ControllerState) -> None:
        """Replay saved toggle button states to VirMIDI.

        Sends CC 127 (on) or CC 0 (off) for each TOGGLE-mode button so
        downstream apps see the persisted button positions on startup.
        """
        if not self._virtual_out or self._virtual_out.closed:
            return
        for key, is_on in state.all_toggle_states():
            # Derive hw_id (CC number) from the key, e.g. "button_37" → 37
            parts = key.rsplit("_", 1)
            if len(parts) != 2 or not parts[1].isdigit():
                continue
            cc = int(parts[1])
            if cc not in _BUTTON_REMAP:
                continue
            fwd = self._remap_for_forward(
                mido.Message("control_change",
                             channel=_BTN_INPUT_CHANNEL,
                             control=cc,
                             value=127 if is_on else 0))
            if fwd is not None:
                try:
                    self._virtual_out.write(fwd.bin())
                except (IOError, OSError):
                    return

    def reset_leds(self) -> None:
        """Turn all LEDs off."""
        for elem in ALL_LED_ELEMENTS:
            self.set_led(elem, COLOR_OFF)

    # -- OLED display -------------------------------------------------------

    def set_stationary_display(self, text: str) -> None:
        """Set the permanent OLED display to show a single line of text."""
        if not self.connected:
            return
        # Configure stationary display: arrangement 1 (2-line: Name + Value)
        config_data = _SYSEX_HEADER + [_SYSEX_DISPLAY_CONFIG,
                                        _DISPLAY_STATIONARY,
                                        _DISPLAY_ARRANGEMENT_2LINE]
        self._outport.send(mido.Message("sysex", data=config_data))
        # Set field 0 (Name line) with the text
        ascii_bytes = [min(b, 0x7E) for b in text.encode("ascii", errors="replace")]
        text_data = _SYSEX_HEADER + [_SYSEX_DISPLAY_TEXT,
                                      _DISPLAY_STATIONARY, 0x00] + ascii_bytes
        self._outport.send(mido.Message("sysex", data=text_data))
        # Trigger display (config 7F = show with current contents)
        trigger = _SYSEX_HEADER + [_SYSEX_DISPLAY_CONFIG,
                                    _DISPLAY_STATIONARY, 0x7F]
        self._outport.send(mido.Message("sysex", data=trigger))

    def clear_stationary_display(self) -> None:
        """Cancel the stationary display (returns to default)."""
        if not self.connected:
            return
        data = _SYSEX_HEADER + [_SYSEX_DISPLAY_CONFIG, _DISPLAY_STATIONARY, 0x00]
        self._outport.send(mido.Message("sysex", data=data))

    def setup_encoder_names(self) -> None:
        """Send parameter names for each encoder/fader so the temp display
        shows e.g. 'Enc 1' instead of just the raw value."""
        if not self.connected:
            return
        all_analog = list(KNOB_ELEMENTS) + list(FADER_ELEMENTS)
        for i, elem in enumerate(all_analog):
            target = elem.hw_id  # CC index = display target for analog controls
            # Configure: arrangement 4 = Name + numeric value (with auto-trigger)
            # Bit 6 (0x40) = auto on change, Bit 5 (0x20) = auto on touch
            cfg_byte = 0x40 | 0x20 | 0x04  # arrangement 4 + auto bits
            config_data = _SYSEX_HEADER + [_SYSEX_DISPLAY_CONFIG, target, cfg_byte]
            self._outport.send(mido.Message("sysex", data=config_data))
            # Set the name (field 0)
            name = elem.label
            ascii_bytes = [min(b, 0x7E) for b in name.encode("ascii", errors="replace")]
            text_data = _SYSEX_HEADER + [_SYSEX_DISPLAY_TEXT, target, 0x00] + ascii_bytes
            self._outport.send(mido.Message("sysex", data=text_data))
            # Brief pause every 8 controls to avoid SysEx flood
            if (i + 1) % 8 == 0:
                time.sleep(0.01)

    # -- listening ----------------------------------------------------------

    def _start_listener(self) -> None:
        self._running = True
        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="lcxl-midi-listener"
        )
        self._listen_thread.start()

    def _stop_listener(self) -> None:
        self._running = False
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=1.0)
        self._listen_thread = None

    def _listen_loop(self) -> None:
        """Background loop that reads incoming MIDI messages."""
        while self._running and self._inport and not self._inport.closed:
            try:
                for msg in self._inport.iter_pending():
                    self._handle_message(msg)
            except (IOError, OSError):
                self._running = False
                if self.on_disconnect:
                    self.on_disconnect()
                return
            time.sleep(0.005)  # ~200 Hz poll

    def _handle_message(self, msg: mido.Message) -> None:
        # Forward CC messages to the virtual output with safe remap
        if self._virtual_out and not self._virtual_out.closed:
            try:
                fwd = self._remap_for_forward(msg)
                if fwd is not None:
                    self._virtual_out.write(fwd.bin())
            except (IOError, OSError):
                pass

        if msg.type != "control_change":
            return

        cc, val, ch = msg.control, msg.value, msg.channel

        # Buttons (channel 1, CCs 37-52)
        if ch == _BTN_INPUT_CHANNEL and cc in _CC_TO_BUTTON:
            elem = _CC_TO_BUTTON[cc]
            if val > 0:
                if self.on_button_press:
                    self.on_button_press(elem)
            else:
                if self.on_button_release:
                    self.on_button_release(elem)
            return

        # Encoders / faders (channel 16)
        if ch == _ANALOG_INPUT_CHANNEL and self.on_cc:
            self.on_cc(cc, val)

    @staticmethod
    def _remap_for_forward(msg: mido.Message) -> Optional[mido.Message]:
        """Remap a DAW-mode message to safe CC numbers on ch1 for forwarding."""
        if msg.type != "control_change":
            return None  # only forward CC messages
        cc, val, ch = msg.control, msg.value, msg.channel
        if ch == _ANALOG_INPUT_CHANNEL:
            # Faders / knobs on ch16
            new_cc = _FADER_REMAP.get(cc) or _KNOB_REMAP.get(cc)
            if new_cc is not None:
                return mido.Message("control_change", channel=_FORWARD_CHANNEL,
                                    control=new_cc, value=val)
        elif ch == _BTN_INPUT_CHANNEL:
            # Buttons on ch1
            new_cc = _BUTTON_REMAP.get(cc)
            if new_cc is not None:
                return mido.Message("control_change", channel=_FORWARD_CHANNEL,
                                    control=new_cc, value=val)
        return None

    # -- LED brightness -----------------------------------------------------

    def set_brightness(self, value: int) -> None:
        """Set LED brightness (0-127) via feature CC 111 on channel 7."""
        value = max(0, min(127, value))
        self._brightness = value
        if not self.connected:
            return
        # Enable feature controls: Note On ch16 note 11 vel 127
        enable = mido.Message("note_on", channel=_DAW_MODE_CHANNEL,
                              note=0x0B, velocity=127)
        self._outport.send(enable)
        time.sleep(0.01)
        # CC 111 on channel 7 (0-indexed 6)
        cc_msg = mido.Message("control_change", channel=_FEATURE_CC_CHANNEL,
                              control=111, value=value)
        self._outport.send(cc_msg)

    # -- auto-reconnect helper (call periodically from a QTimer) ------------

    def try_reconnect(self) -> bool:
        if self.connected:
            return True
        return self.connect()
