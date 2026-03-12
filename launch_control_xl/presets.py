"""Scene / preset management — save and load LED configurations as JSON."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .led_state import (
    ALL_LED_ELEMENTS,
    BUTTON_ELEMENTS,
    KNOB_ELEMENTS,
    ControllerState,
    LEDConfig,
    LEDMode,
    RGBColor,
)

# Default scene directory
_DEFAULT_DIR = Path.home() / ".config" / "launch-control-xl" / "scenes"
_LAST_SCENE_FILE = Path.home() / ".config" / "launch-control-xl" / "last_scene.txt"

# The built-in default scene name (cannot be deleted)
DEFAULT_SCENE_NAME = "Default"


def _ensure_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Scene dataclass
# ---------------------------------------------------------------------------

@dataclass
class Scene:
    name: str
    data: dict  # serialised ControllerState (key → LEDConfig dict)

    def to_json(self) -> str:
        return json.dumps({"name": self.name, "leds": self.data}, indent=2)

    @classmethod
    def from_json(cls, text: str) -> Scene:
        obj = json.loads(text)
        return cls(name=obj["name"], data=obj["leds"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scenes_dir() -> Path:
    """Return (and create) the default scenes directory."""
    _ensure_dir(_DEFAULT_DIR)
    return _DEFAULT_DIR


def list_scenes(directory: Optional[Path] = None) -> List[str]:
    """Return sorted list of scene names (without .json extension)."""
    d = directory or scenes_dir()
    if not d.exists():
        return []
    return sorted(
        p.stem for p in d.glob("*.json")
    )


def save_scene(name: str, state: ControllerState, directory: Optional[Path] = None) -> Path:
    """Save *state* as a named scene. Returns the file path."""
    d = directory or scenes_dir()
    _ensure_dir(d)
    scene = Scene(name=name, data=state.to_dict())
    path = d / f"{name}.json"
    path.write_text(scene.to_json(), encoding="utf-8")
    return path


def load_scene(name: str, state: ControllerState, directory: Optional[Path] = None) -> None:
    """Load a named scene into *state* (in-place)."""
    d = directory or scenes_dir()
    path = d / f"{name}.json"
    scene = Scene.from_json(path.read_text(encoding="utf-8"))
    state.load_dict(scene.data)


def is_protected(name: str) -> bool:
    """Return True if the scene cannot be deleted or renamed."""
    return name == DEFAULT_SCENE_NAME


# ---------------------------------------------------------------------------
# Factory-default colours (matches the MK3 out-of-box rainbow)
# ---------------------------------------------------------------------------
# 8-column rainbow gradient used by the MK3 factory preset
_FACTORY_RAINBOW = [
    RGBColor(127, 0, 0),     # red
    RGBColor(127, 48, 0),    # orange
    RGBColor(127, 127, 0),   # yellow
    RGBColor(0, 127, 0),     # green
    RGBColor(0, 127, 127),   # cyan
    RGBColor(0, 0, 127),     # blue
    RGBColor(80, 0, 127),    # purple
    RGBColor(127, 0, 127),   # magenta
]


def _build_factory_state() -> ControllerState:
    """Build a ControllerState matching the MK3 factory-default LED colours."""
    state = ControllerState()
    state.display_text = "Default"
    # Knobs: 3 rows × 8 cols, each row uses the rainbow
    for elem in KNOB_ELEMENTS:
        color = _FACTORY_RAINBOW[elem.col]
        state.set_config(elem, LEDConfig(
            idle_color=color,
            active_color=RGBColor(127, 127, 127),
            mode=LEDMode.STATIC,
        ))
    # Button row 1 (Focus/Solo): cyan-ish tones
    for elem in BUTTON_ELEMENTS:
        if elem.row == 0:
            color = _FACTORY_RAINBOW[elem.col]
            state.set_config(elem, LEDConfig(
                idle_color=color,
                active_color=RGBColor(127, 127, 127),
                mode=LEDMode.TOGGLE,
            ))
        else:
            # Button row 2 (Control/Mute): rainbow
            color = _FACTORY_RAINBOW[elem.col]
            state.set_config(elem, LEDConfig(
                idle_color=color,
                active_color=RGBColor(127, 127, 127),
                mode=LEDMode.TOGGLE,
            ))
    return state


def ensure_default_scene(directory: Optional[Path] = None) -> None:
    """Create the Default scene with factory colours if it doesn't exist."""
    d = directory or scenes_dir()
    path = d / f"{DEFAULT_SCENE_NAME}.json"
    if not path.exists():
        state = _build_factory_state()
        save_scene(DEFAULT_SCENE_NAME, state, directory=d)


def delete_scene(name: str, directory: Optional[Path] = None) -> None:
    if is_protected(name):
        return
    d = directory or scenes_dir()
    path = d / f"{name}.json"
    if path.exists():
        path.unlink()


def rename_scene(old: str, new: str, directory: Optional[Path] = None) -> None:
    if is_protected(old):
        return
    d = directory or scenes_dir()
    src = d / f"{old}.json"
    dst = d / f"{new}.json"
    if src.exists():
        # Update the name field inside the JSON too
        scene = Scene.from_json(src.read_text(encoding="utf-8"))
        scene.name = new
        dst.write_text(scene.to_json(), encoding="utf-8")
        src.unlink()


def copy_scene(src_name: str, new_name: str, directory: Optional[Path] = None) -> Path:
    """Duplicate scene *src_name* as *new_name*."""
    d = directory or scenes_dir()
    src = d / f"{src_name}.json"
    scene = Scene.from_json(src.read_text(encoding="utf-8"))
    scene.name = new_name
    dst = d / f"{new_name}.json"
    dst.write_text(scene.to_json(), encoding="utf-8")
    return dst


def save_last_scene_name(name: str) -> None:
    _ensure_dir(_LAST_SCENE_FILE.parent)
    _LAST_SCENE_FILE.write_text(name, encoding="utf-8")


def load_last_scene_name() -> Optional[str]:
    if _LAST_SCENE_FILE.exists():
        name = _LAST_SCENE_FILE.read_text(encoding="utf-8").strip()
        return name if name else None
    return None
