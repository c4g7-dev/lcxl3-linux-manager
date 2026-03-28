"""LED state model, color definitions, and controller state management.

Targets the Launch Control XL **MK3** (LCXL3).  The MK3 has full RGB LEDs
and uses CC-based controls in DAW mode.  LED colours can be set via:
  - CC palette:  B0 <control_index> <colour_index>   (channel 1)
  - RGB SysEx:   F0 00 20 29 02 15 01 53 <idx> <R> <G> <B> F7
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# RGB colour representation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RGBColor:
    """An RGB colour with 7-bit per channel (0-127) for MIDI SysEx."""
    r: int = 0
    g: int = 0
    b: int = 0

    def to_hex(self) -> str:
        """Qt-friendly hex string (scaled to 8-bit)."""
        if self.r == 0 and self.g == 0 and self.b == 0:
            return "#2a2a2a"  # "off" visual
        return f"#{self.r * 2:02x}{self.g * 2:02x}{self.b * 2:02x}"

    def to_tuple(self) -> Tuple[int, int, int]:
        return (self.r, self.g, self.b)

    def to_dict(self) -> dict:
        return {"r": self.r, "g": self.g, "b": self.b}

    @classmethod
    def from_dict(cls, d: dict) -> RGBColor:
        return cls(r=d["r"], g=d["g"], b=d["b"])

    @classmethod
    def from_hex(cls, h: str) -> RGBColor:
        """Parse a '#RRGGBB' string (8-bit) and scale down to 7-bit."""
        h = h.lstrip("#")
        r8, g8, b8 = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return cls(r=r8 >> 1, g=g8 >> 1, b=b8 >> 1)


# Handy preset colours
COLOR_OFF = RGBColor(0, 0, 0)
COLOR_RED = RGBColor(127, 0, 0)
COLOR_GREEN = RGBColor(0, 127, 0)
COLOR_BLUE = RGBColor(0, 0, 127)
COLOR_YELLOW = RGBColor(127, 127, 0)
COLOR_AMBER = RGBColor(127, 64, 0)
COLOR_CYAN = RGBColor(0, 127, 127)
COLOR_MAGENTA = RGBColor(127, 0, 127)
COLOR_WHITE = RGBColor(127, 127, 127)
COLOR_PINK = RGBColor(127, 40, 80)
COLOR_ORANGE = RGBColor(127, 48, 0)
COLOR_PURPLE = RGBColor(80, 0, 127)
COLOR_LIME = RGBColor(64, 127, 0)

# Named presets for the GUI quick-pick palette
PRESET_COLORS: Dict[str, RGBColor] = {
    "Off": COLOR_OFF,
    "Red": COLOR_RED,
    "Green": COLOR_GREEN,
    "Blue": COLOR_BLUE,
    "Yellow": COLOR_YELLOW,
    "Amber": COLOR_AMBER,
    "Cyan": COLOR_CYAN,
    "Magenta": COLOR_MAGENTA,
    "White": COLOR_WHITE,
    "Pink": COLOR_PINK,
    "Orange": COLOR_ORANGE,
    "Purple": COLOR_PURPLE,
    "Lime": COLOR_LIME,
}


class LEDMode(Enum):
    """How a button LED reacts to presses."""
    STATIC = "static"        # color never changes on press
    MOMENTARY = "momentary"  # active_color while held, idle_color on release
    TOGGLE = "toggle"        # flip between idle_color and active_color each press


# ---------------------------------------------------------------------------
# Per-LED configuration
# ---------------------------------------------------------------------------

@dataclass
class LEDConfig:
    """Colour & behaviour settings for a single LED."""
    idle_color: RGBColor = COLOR_OFF
    active_color: RGBColor = COLOR_RED
    mode: LEDMode = LEDMode.STATIC

    def to_dict(self) -> dict:
        return {
            "idle_color": self.idle_color.to_dict(),
            "active_color": self.active_color.to_dict(),
            "mode": self.mode.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LEDConfig:
        return cls(
            idle_color=RGBColor.from_dict(d["idle_color"]),
            active_color=RGBColor.from_dict(d["active_color"]),
            mode=LEDMode(d["mode"]),
        )


# ---------------------------------------------------------------------------
# Element types & hardware mappings  (LCXL MK3 DAW-mode CC indices)
# ---------------------------------------------------------------------------

class ElementKind(Enum):
    BUTTON = "button"
    KNOB = "knob"
    FADER = "fader"
    SIDE = "side"


@dataclass
class Element:
    """A single physical control on the Launch Control XL MK3."""
    kind: ElementKind
    # CC control index used in DAW mode for both I/O and LED colouring.
    hw_id: int
    label: str
    row: int
    col: int


# Encoders (knobs) — 3 rows of 8, CCs 13-36
# Row 1: 13-20, Row 2: 21-28, Row 3: 29-36
KNOB_ELEMENTS: List[Element] = [
    Element(ElementKind.KNOB, 13 + row * 8 + col, f"Knob {row+1}-{col+1}", row, col)
    for row in range(3) for col in range(8)
]

# Faders — CCs 5-12  (no LEDs, kept for display-name reference)
FADER_ELEMENTS: List[Element] = [
    Element(ElementKind.FADER, 5 + col, f"Fader {col+1}", 0, col)
    for col in range(8)
]

# Buttons — 2 rows of 8, CCs 37-52
# Row 1 (Focus): 37-44, Row 2 (Control): 45-52
_BUTTON_CCS = [
    list(range(37, 45)),   # top row
    list(range(45, 53)),   # bottom row
]

BUTTON_ELEMENTS: List[Element] = [
    Element(ElementKind.BUTTON, cc, f"Btn {r+1}-{c+1}", r, c)
    for r, row in enumerate(_BUTTON_CCS)
    for c, cc in enumerate(row)
]

# Combined list of all LED-bearing elements (faders have no LEDs)
# (SIDE_LED_ELEMENTS appended below after SideButton definitions)
ALL_LED_ELEMENTS: List[Element] = KNOB_ELEMENTS + BUTTON_ELEMENTS


# ---------------------------------------------------------------------------
# Side-panel buttons
# ---------------------------------------------------------------------------
# Some side buttons have RGB LEDs controllable via SysEx (hw_id != None).

@dataclass
class SideButton:
    """A button on the LCXL MK3 side panel."""
    label: str
    symbol: str  # short symbol for rendering
    hw_id: Optional[int] = None  # SysEx RGB index, None = no LED


# Paired rows (rendered side-by-side)
SIDE_BUTTON_PAIRS: List[tuple[SideButton, SideButton]] = [
    (SideButton("Page Up",     "\u25B2",  hw_id=106),
     SideButton("Page Down",   "\u25BC",  hw_id=107)),
    (SideButton("Track Left",  "\u25C0",  hw_id=103),
     SideButton("Track Right", "\u25B6",  hw_id=102)),
]

# Single-width rows (rendered full-width, stacked vertically)
SIDE_BUTTON_SINGLES: List[SideButton] = [
    SideButton("Record",     "\u25CF REC",  hw_id=118),
    SideButton("Play",       "\u25B6 PLAY", hw_id=116),
    SideButton("Shift",      "SHIFT"),
    SideButton("Mode",       "MODE"),
    SideButton("DAW/Ctrl",   "CTRL",        hw_id=65),
    SideButton("DAW Mixer",  "MIXER",       hw_id=66),
]

# Side buttons that have controllable RGB LEDs
SIDE_LED_ELEMENTS: List[Element] = []
for _sb_pair in SIDE_BUTTON_PAIRS:
    for _sb in _sb_pair:
        if _sb.hw_id is not None:
            SIDE_LED_ELEMENTS.append(
                Element(ElementKind.SIDE, _sb.hw_id, _sb.label, row=0, col=0)
            )
for _sb in SIDE_BUTTON_SINGLES:
    if _sb.hw_id is not None:
        SIDE_LED_ELEMENTS.append(
            Element(ElementKind.SIDE, _sb.hw_id, _sb.label, row=0, col=0)
        )

# Include side LED elements in the master list
ALL_LED_ELEMENTS = ALL_LED_ELEMENTS + SIDE_LED_ELEMENTS


# ---------------------------------------------------------------------------
# Controller state
# ---------------------------------------------------------------------------

class ControllerState:
    """Holds the full LED state for every element on the controller."""

    def __init__(self) -> None:
        self._configs: Dict[str, LEDConfig] = {}
        self._toggled: Dict[str, bool] = {}
        for elem in ALL_LED_ELEMENTS:
            key = self._key(elem)
            self._configs[key] = LEDConfig()
            self._toggled[key] = False
        # Live CC values (0-127) for knobs and faders, keyed by CC number.
        # None = not yet received (physical position unknown until first move).
        self._cc_values: Dict[int, Optional[int]] = {}
        for elem in KNOB_ELEMENTS:
            self._cc_values[elem.hw_id] = None
        for elem in FADER_ELEMENTS:
            self._cc_values[elem.hw_id] = None
        # Profile-saved display text and brightness
        self.display_text: str = ""
        self.brightness: int = 127

    # -- key helpers --------------------------------------------------------
    @staticmethod
    def _key(elem: Element) -> str:
        if elem.kind == ElementKind.BUTTON:
            return f"btn_{elem.hw_id}"
        if elem.kind == ElementKind.SIDE:
            return f"side_{elem.hw_id}"
        return f"knob_{elem.hw_id}"

    @staticmethod
    def key_for(kind: ElementKind, hw_id: int) -> str:
        if kind == ElementKind.BUTTON:
            return f"btn_{hw_id}"
        if kind == ElementKind.SIDE:
            return f"side_{hw_id}"
        return f"knob_{hw_id}"

    # -- config access ------------------------------------------------------
    def get_config(self, elem: Element) -> LEDConfig:
        return self._configs[self._key(elem)]

    def set_config(self, elem: Element, cfg: LEDConfig) -> None:
        self._configs[self._key(elem)] = cfg
        self._toggled[self._key(elem)] = False

    # -- resolve the *current* display color for an element -----------------
    def current_color(self, elem: Element) -> RGBColor:
        key = self._key(elem)
        cfg = self._configs[key]
        if cfg.mode in (LEDMode.TOGGLE, LEDMode.MOMENTARY) and self._toggled[key]:
            return cfg.active_color
        return cfg.idle_color

    # -- button press / release handling ------------------------------------
    def on_press(self, elem: Element) -> RGBColor:
        """Call when a button is physically pressed. Returns new color."""
        key = self._key(elem)
        cfg = self._configs[key]
        if cfg.mode == LEDMode.TOGGLE:
            self._toggled[key] = not self._toggled[key]
        elif cfg.mode == LEDMode.MOMENTARY:
            self._toggled[key] = True
        return self.current_color(elem)

    def on_release(self, elem: Element) -> RGBColor:
        """Call when a button is physically released. Returns new color."""
        key = self._key(elem)
        cfg = self._configs[key]
        if cfg.mode == LEDMode.MOMENTARY:
            self._toggled[key] = False
        return self.current_color(elem)

    # -- live CC values -----------------------------------------------------
    def set_cc_value(self, cc: int, value: int) -> None:
        self._cc_values[cc] = value

    def get_cc_value(self, cc: int) -> Optional[int]:
        return self._cc_values.get(cc)

    def all_cc_values(self) -> list[tuple[int, int]]:
        """Return list of (cc, value) for all known (non-None) CC values."""
        return [(cc, val) for cc, val in self._cc_values.items()
                if val is not None]

    def is_toggled(self, elem: Element) -> bool:
        return self._toggled.get(self._key(elem), False)

    # -- bulk operations ----------------------------------------------------
    def reset_toggles(self) -> None:
        for k in self._toggled:
            self._toggled[k] = False

    def all_toggle_states(self) -> list[tuple[str, bool]]:
        """Return list of (key, is_on) for TOGGLE-mode buttons."""
        return [(k, self._toggled.get(k, False))
                for k, cfg in self._configs.items()
                if cfg.mode == LEDMode.TOGGLE]

    # -- serialisation (used by presets.py) ---------------------------------
    def to_dict(self) -> dict:
        # Only save CC values that have been received (not None)
        cc_data = {str(cc): val for cc, val in self._cc_values.items()
                   if val is not None}
        # Only save toggle state for TOGGLE-mode buttons that are ON
        toggle_data = {k: True for k, cfg in self._configs.items()
                       if cfg.mode == LEDMode.TOGGLE and self._toggled.get(k)}
        return {
            "leds": {k: cfg.to_dict() for k, cfg in self._configs.items()},
            "display_text": self.display_text,
            "brightness": self.brightness,
            "cc_values": cc_data,
            "toggles": toggle_data,
        }

    def load_dict(self, data: dict) -> None:
        # Support both old format (flat dict of LEDs) and new format (nested)
        if "leds" in data and isinstance(data["leds"], dict):
            led_data = data["leds"]
            self.display_text = data.get("display_text", "")
            self.brightness = data.get("brightness", 127)
        else:
            # Legacy format: data is {key: LEDConfig dict, ...}
            led_data = data
            self.display_text = ""
            self.brightness = 127
        toggle_data = data.get("toggles", {})
        for k, d in led_data.items():
            if k in self._configs:
                self._configs[k] = LEDConfig.from_dict(d)
                self._toggled[k] = toggle_data.get(k, False)
        # Restore saved CC values (leave missing ones as None)
        cc_data = data.get("cc_values", {})
        for cc_str, val in cc_data.items():
            cc = int(cc_str)
            if cc in self._cc_values:
                self._cc_values[cc] = val
