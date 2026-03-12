"""Visual representation of the Launch Control XL MK3 — clickable LED grid."""

from __future__ import annotations

from typing import List, Optional, Set

import math

from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF, QSize
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QMouseEvent, QFont
from PyQt6.QtWidgets import (
    QWidget, QSizePolicy, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
)

from ..led_state import (
    ALL_LED_ELEMENTS,
    BUTTON_ELEMENTS,
    KNOB_ELEMENTS,
    FADER_ELEMENTS,
    SIDE_BUTTON_PAIRS,
    SIDE_BUTTON_SINGLES,
    SideButton,
    RGBColor,
    ControllerState,
    Element,
    ElementKind,
    LEDMode,
)

# Layout geometry constants
_COLS = 8
_KNOB_ROWS = 3
_BTN_ROWS = 2
_PAD = 8       # spacing between cells
_CELL = 48     # cell size
_SIDE_W = 110  # width of the side panel (OLED display + buttons)
_FADER_H = 80  # fader visual height
_FADER_LABEL_H = 14  # space below fader for value text
_LABEL_H = 20  # reserved height for section labels
_SIDE_BTN_H = 30  # side button height


class ControllerWidget(QWidget):
    """Renders the Launch Control XL MK3 layout and handles LED selection."""

    selection_changed = pyqtSignal()
    display_set_requested = pyqtSignal(str)   # text to send to OLED
    display_clear_requested = pyqtSignal()     # clear OLED

    def __init__(self, state: ControllerState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._selected: Set[str] = set()
        self._hovered: Optional[str] = None
        self._last_clicked_key: Optional[str] = None  # for shift-click range
        self._locked = False  # when True, clicks on LEDs are ignored
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(QSize(520, 400))

        # -- OLED display child widgets (positioned in _build_rects) --------
        self._display_edit = QLineEdit(self)
        self._display_edit.setPlaceholderText("Display text")
        self._display_edit.setMaxLength(32)
        self._display_edit.setStyleSheet(
            "background-color: #0a0a0a; color: #00ccff; border: 1px solid #333;"
            "border-radius: 2px; font-family: monospace; font-size: 10px;"
            "padding: 2px 4px;"
        )
        self._display_edit.returnPressed.connect(self._on_display_set)

        self._btn_set = QPushButton("Set", self)
        self._btn_set.setFixedHeight(20)
        self._btn_set.setStyleSheet(
            "font-size: 9px; padding: 1px 4px; background: #333; color: #aaa;"
            "border: 1px solid #555; border-radius: 2px;"
        )
        self._btn_set.clicked.connect(self._on_display_set)

        self._btn_clear = QPushButton("Clear", self)
        self._btn_clear.setFixedHeight(20)
        self._btn_clear.setStyleSheet(
            "font-size: 9px; padding: 1px 4px; background: #333; color: #aaa;"
            "border: 1px solid #555; border-radius: 2px;"
        )
        self._btn_clear.clicked.connect(self._on_display_clear)

        self._build_rects()

    # -- display helpers ----------------------------------------------------

    @property
    def display_text(self) -> str:
        return self._display_edit.text().strip()

    @display_text.setter
    def display_text(self, text: str) -> None:
        self._display_edit.setText(text)

    def _on_display_set(self) -> None:
        txt = self.display_text
        if txt:
            self.display_set_requested.emit(txt)
        else:
            self.display_clear_requested.emit()

    def _on_display_clear(self) -> None:
        self._display_edit.clear()
        self.display_clear_requested.emit()

    def set_locked(self, locked: bool) -> None:
        """When locked, LED selection clicks are ignored (for protected profiles)."""
        self._locked = locked
        if locked:
            self._selected.clear()
            self.selection_changed.emit()
            self.update()

    def set_display_editable(self, editable: bool) -> None:
        """Enable or disable the display text field and buttons."""
        self._display_edit.setReadOnly(not editable)
        self._btn_set.setEnabled(editable)
        self._btn_clear.setEnabled(editable)
        opacity = "1.0" if editable else "0.5"
        self._btn_set.setStyleSheet(
            f"font-size: 9px; padding: 1px 4px; background: #333; color: #aaa;"
            f"border: 1px solid #555; border-radius: 2px; opacity: {opacity};"
        )
        self._btn_clear.setStyleSheet(
            f"font-size: 9px; padding: 1px 4px; background: #333; color: #aaa;"
            f"border: 1px solid #555; border-radius: 2px; opacity: {opacity};"
        )

    # -- geometry -----------------------------------------------------------

    def _build_rects(self) -> None:
        self._elem_rects: dict[str, tuple[QRectF, Element]] = {}
        self._ordered_keys: list[str] = []
        self._section_labels: list[tuple[float, float, str]] = []
        # Non-selectable side button rects: (QRectF, SideButton)
        self._side_btn_rects: list[tuple[QRectF, SideButton]] = []
        # Labels for SIDE elements (key → symbol text)
        self._side_elem_labels: dict[str, str] = {}

        # The main grid starts after the side panel
        x_off = _SIDE_W + _PAD
        y = _PAD

        # --- Knobs label ---
        self._section_labels.append((x_off, y, "Encoders"))
        y += _LABEL_H

        # ---------- SIDE PANEL (left column) ----------
        side_x = _PAD
        side_w = _SIDE_W - _PAD  # usable width
        sy = y  # align top of side panel with first knob row

        # OLED display area
        oled_h = 44
        self._oled_rect = QRectF(side_x, sy, side_w, oled_h)
        # Position child widgets inside the OLED area
        self._display_edit.setGeometry(
            int(side_x + 2), int(sy + 2), int(side_w - 4), 20
        )
        btn_w = (int(side_w) - 6) // 2
        self._btn_set.setGeometry(int(side_x + 2), int(sy + 24), btn_w, 18)
        self._btn_clear.setGeometry(int(side_x + 4 + btn_w), int(sy + 24), btn_w, 18)
        sy += oled_h + _PAD

        # Paired buttons (Page, Track)
        half_w = (side_w - _PAD) / 2
        for sb_left, sb_right in SIDE_BUTTON_PAIRS:
            r_left = QRectF(side_x, sy, half_w, _SIDE_BTN_H)
            r_right = QRectF(side_x + half_w + _PAD, sy, half_w, _SIDE_BTN_H)
            for rect, sb in [(r_left, sb_left), (r_right, sb_right)]:
                if sb.hw_id is not None:
                    key = f"side_{sb.hw_id}"
                    elem = next(e for e in ALL_LED_ELEMENTS if e.kind == ElementKind.SIDE and e.hw_id == sb.hw_id)
                    self._elem_rects[key] = (rect, elem)
                    self._ordered_keys.append(key)
                    self._side_elem_labels[key] = sb.symbol
                else:
                    self._side_btn_rects.append((rect, sb))
            sy += _SIDE_BTN_H + _PAD

        # Single buttons (Record, Play, Shift, Mode, DAW/Ctrl, DAW Mixer)
        for sb in SIDE_BUTTON_SINGLES:
            rect = QRectF(side_x, sy, side_w, _SIDE_BTN_H)
            if sb.hw_id is not None:
                key = f"side_{sb.hw_id}"
                elem = next(e for e in ALL_LED_ELEMENTS if e.kind == ElementKind.SIDE and e.hw_id == sb.hw_id)
                self._elem_rects[key] = (rect, elem)
                self._ordered_keys.append(key)
                self._side_elem_labels[key] = sb.symbol
            else:
                self._side_btn_rects.append((rect, sb))
            sy += _SIDE_BTN_H + _PAD

        # ---------- MAIN GRID ----------
        # Knobs — 3 rows of 8
        for row in range(_KNOB_ROWS):
            x = x_off
            for col in range(_COLS):
                elem = KNOB_ELEMENTS[row * _COLS + col]
                key = f"knob_{elem.hw_id}"
                rect = QRectF(x, y, _CELL, _CELL)
                self._elem_rects[key] = (rect, elem)
                self._ordered_keys.append(key)
                x += _CELL + _PAD
            y += _CELL + _PAD

        # --- Faders label ---
        self._section_labels.append((x_off, y, "Faders (no LED)"))
        y += _LABEL_H

        # Faders — 1 row of 8
        x = x_off
        self._fader_rects: list[QRectF] = []
        for col in range(_COLS):
            rect = QRectF(x, y, _CELL, _FADER_H)
            self._fader_rects.append(rect)
            x += _CELL + _PAD
        y += _FADER_H + _FADER_LABEL_H + _PAD

        # --- Buttons label ---
        self._section_labels.append((x_off, y, "Buttons"))
        y += _LABEL_H

        # Buttons — 2 rows of 8
        for row in range(_BTN_ROWS):
            x = x_off
            for col in range(_COLS):
                elem = BUTTON_ELEMENTS[row * _COLS + col]
                key = f"btn_{elem.hw_id}"
                rect = QRectF(x, y, _CELL, _CELL)
                self._elem_rects[key] = (rect, elem)
                self._ordered_keys.append(key)
                x += _CELL + _PAD
            y += _CELL + _PAD

        self._total_w = x_off + _COLS * (_CELL + _PAD)
        self._total_h = max(y, sy + _PAD)

    def sizeHint(self) -> QSize:
        return QSize(int(self._total_w), int(self._total_h))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # -- public API ---------------------------------------------------------

    @property
    def selected_elements(self) -> List[Element]:
        return [
            data[1] for key, data in self._elem_rects.items() if key in self._selected
        ]

    def clear_selection(self) -> None:
        self._selected.clear()
        self.selection_changed.emit()
        self.update()

    def refresh(self) -> None:
        self.update()

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        p.fillRect(self.rect(), QColor("#1a1a1a"))

        # Section labels
        label_font = QFont("Sans", 9)
        p.setFont(label_font)
        p.setPen(QColor("#888888"))
        for lx, ly, text in self._section_labels:
            p.drawText(QRectF(lx, ly, 300, _LABEL_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       text)

        # Draw selectable LED elements (knobs + buttons)
        for key, (rect, elem) in self._elem_rects.items():
            color = self._state.current_color(elem)
            fill = QColor(color.to_hex())

            is_selected = key in self._selected
            is_hovered = key == self._hovered

            if is_selected:
                pen = QPen(QColor("#ffffff"), 2)
            elif is_hovered:
                pen = QPen(QColor("#aaaaaa"), 2)
            else:
                pen = QPen(QColor("#555555"), 2)

            p.setBrush(fill)
            p.setPen(pen)

            if elem.kind == ElementKind.KNOB:
                p.drawEllipse(rect)
                # Draw knob position arc
                self._draw_knob_arc(p, rect, elem)
            elif elem.kind == ElementKind.SIDE:
                p.drawRoundedRect(rect, 4, 4)
                # Draw the side button label
                btn_font = QFont("Sans", 7, QFont.Weight.Bold)
                p.setFont(btn_font)
                # Use light text on dark fill, dark text on bright fill
                lum = color.r + color.g + color.b
                p.setPen(QColor("#222222") if lum > 180 else QColor("#cccccc"))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                           self._side_elem_labels.get(key, ""))
            else:
                p.drawRoundedRect(rect, 6, 6)
                # Draw toggle indicator dot for non-static buttons
                self._draw_button_indicator(p, rect, elem)

        # Draw faders with live position handle
        for i, rect in enumerate(self._fader_rects):
            fader_elem = FADER_ELEMENTS[i]
            self._draw_fader(p, rect, fader_elem)

        # Draw OLED display frame
        p.setBrush(QColor("#0a0a0a"))
        p.setPen(QPen(QColor("#333333"), 1))
        p.drawRoundedRect(self._oled_rect, 4, 4)
        # "OLED" label just above
        tiny = QFont("Sans", 7)
        p.setFont(tiny)
        p.setPen(QColor("#555555"))
        p.drawText(QRectF(self._oled_rect.x(), self._oled_rect.y() - 12,
                          self._oled_rect.width(), 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   "Display")

        # Draw non-mappable side buttons
        for rect, sb in self._side_btn_rects:
            self._draw_side_btn(p, rect, sb)

        p.end()

    def _draw_knob_arc(self, p: QPainter, rect: QRectF, elem: Element) -> None:
        """Draw a position arc around the knob based on live CC value."""
        val = self._state.get_cc_value(elem.hw_id)
        if val is None:
            # Unknown position — show dim '?' in center
            val_font = QFont("Sans", 7)
            p.setFont(val_font)
            p.setPen(QColor("#555555"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
            return
        if val == 0:
            # Known zero — show '0' but no arc
            val_font = QFont("Sans", 7)
            p.setFont(val_font)
            p.setPen(QColor("#aaccff"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "0")
            return
        # Arc from ~225° (min) to ~-45° (max), sweeping clockwise
        # Qt arcs are in 1/16th degree, zero = 3 o'clock, counter-clockwise positive
        start_angle = 225 * 16  # 7 o'clock position
        max_sweep = -270 * 16   # full sweep to 5 o'clock
        sweep = int(max_sweep * val / 127)

        arc_rect = rect.adjusted(-3, -3, 3, 3)
        p.setPen(QPen(QColor("#66aaff"), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(arc_rect, start_angle, sweep)

        # Draw small value text
        val_font = QFont("Sans", 7)
        p.setFont(val_font)
        p.setPen(QColor("#aaccff"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(val))

    def _draw_button_indicator(self, p: QPainter, rect: QRectF, elem: Element) -> None:
        """Draw active-color swatch at top and toggle dot for non-static buttons."""
        cfg = self._state.get_config(elem)
        if cfg.mode == LEDMode.STATIC:
            return

        # Active-color swatch bar across the top of the button
        swatch_h = 6
        swatch_rect = QRectF(rect.x() + 3, rect.y() + 3,
                             rect.width() - 6, swatch_h)
        active_hex = cfg.active_color.to_hex()
        p.setBrush(QColor(active_hex))
        p.setPen(QPen(QColor("#888888"), 0.5))
        p.drawRoundedRect(swatch_rect, 2, 2)

        # Mode label (tiny text)
        mode_font = QFont("Sans", 6)
        p.setFont(mode_font)
        p.setPen(QColor("#aaaaaa"))
        mode_text = "T" if cfg.mode == LEDMode.TOGGLE else "M"
        p.drawText(QRectF(rect.x() + 2, rect.bottom() - 12, 10, 10),
                   Qt.AlignmentFlag.AlignCenter, mode_text)

        # Toggle state dot in bottom-right corner
        toggled = self._state.is_toggled(elem)
        dot_r = 3
        cx = rect.right() - dot_r - 3
        cy = rect.bottom() - dot_r - 3
        if toggled:
            p.setBrush(QColor("#44ff44"))
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setBrush(QColor("#444444"))
            p.setPen(QPen(QColor("#666666"), 1))
        p.drawEllipse(QPointF(cx, cy), dot_r, dot_r)

    def _draw_fader(self, p: QPainter, rect: QRectF, elem: Element) -> None:
        """Draw a fader track with a handle at the live CC position."""
        # Background
        p.setBrush(QColor("#333333"))
        p.setPen(QPen(QColor("#555555"), 1))
        p.drawRoundedRect(rect, 4, 4)

        # Track slot
        slot_x = rect.center().x() - 2
        slot_top = rect.y() + 8
        slot_h = rect.height() - 16
        slot = QRectF(slot_x, slot_top, 4, slot_h)
        p.setBrush(QColor("#555555"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(slot, 2, 2)

        val = self._state.get_cc_value(elem.hw_id)

        if val is None:
            # Unknown — draw centered '?' instead of handle
            val_font = QFont("Sans", 8)
            p.setFont(val_font)
            p.setPen(QColor("#555555"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
            return

        # Handle position (val 0 = bottom, 127 = top)
        frac = val / 127.0
        handle_h = 10
        handle_w = rect.width() - 8
        handle_y = slot_top + slot_h - handle_h - frac * (slot_h - handle_h)
        handle_x = rect.x() + 4
        handle_rect = QRectF(handle_x, handle_y, handle_w, handle_h)

        # Filled portion below handle
        fill_rect = QRectF(slot_x, handle_y + handle_h / 2, 4,
                           slot_top + slot_h - handle_y - handle_h / 2)
        p.setBrush(QColor("#4488cc"))
        p.drawRoundedRect(fill_rect, 2, 2)

        # Handle
        p.setBrush(QColor("#cccccc"))
        p.setPen(QPen(QColor("#888888"), 1))
        p.drawRoundedRect(handle_rect, 3, 3)

        # Value text below the fader (outside the rect)
        val_font = QFont("Sans", 7)
        p.setFont(val_font)
        p.setPen(QColor("#999999"))
        text_rect = QRectF(rect.x(), rect.bottom() + 1, rect.width(), _FADER_LABEL_H)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   str(val))

    def _draw_side_btn(self, p: QPainter, rect: QRectF, sb: SideButton) -> None:
        """Draw a non-mappable side-panel button (dim, non-interactive)."""
        p.setBrush(QColor("#2a2a2a"))
        p.setPen(QPen(QColor("#444444"), 1))
        p.drawRoundedRect(rect, 4, 4)

        btn_font = QFont("Sans", 7, QFont.Weight.Bold)
        p.setFont(btn_font)
        p.setPen(QColor("#666666"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, sb.symbol)

    # -- mouse interaction --------------------------------------------------

    def _key_at(self, pos) -> Optional[str]:
        for key, (rect, _) in self._elem_rects.items():
            if rect.contains(pos.x(), pos.y()):
                return key
        return None

    def _range_between(self, a: str, b: str) -> Set[str]:
        """Return the set of keys between a and b (inclusive) in layout order."""
        try:
            ia = self._ordered_keys.index(a)
            ib = self._ordered_keys.index(b)
        except ValueError:
            return {a, b}
        lo, hi = min(ia, ib), max(ia, ib)
        return set(self._ordered_keys[lo:hi + 1])

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if self._locked:
            return
        key = self._key_at(ev.pos())
        ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if key is None:
            if not ctrl and not shift:
                self._selected.clear()
        elif shift and self._last_clicked_key and self._last_clicked_key in self._elem_rects:
            # Shift-click: select range from last click to current
            rng = self._range_between(self._last_clicked_key, key)
            if ctrl:
                self._selected |= rng
            else:
                self._selected = rng
        elif ctrl:
            self._selected ^= {key}
            self._last_clicked_key = key
        else:
            self._selected = {key}
            self._last_clicked_key = key

        self.selection_changed.emit()
        self.update()

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        key = self._key_at(ev.pos())
        if key != self._hovered:
            self._hovered = key
            self.update()

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._hovered = None
        self.update()
