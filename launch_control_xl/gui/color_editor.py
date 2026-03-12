"""Color editor panel — configure LED color and mode for selected elements."""

from __future__ import annotations

from typing import List

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..led_state import (
    ALL_LED_ELEMENTS,
    BUTTON_ELEMENTS,
    KNOB_ELEMENTS,
    RGBColor,
    PRESET_COLORS,
    ControllerState,
    Element,
    ElementKind,
    LEDConfig,
    LEDMode,
)


class _ColorPicker(QWidget):
    """A button swatch that opens Qt's color dialog, plus quick-pick presets."""

    changed = pyqtSignal(RGBColor)

    def __init__(self, label_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = RGBColor(0, 0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Label + swatch button
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text))
        self._swatch = QPushButton()
        self._swatch.setFixedSize(36, 24)
        self._swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swatch.clicked.connect(self._open_dialog)
        row.addWidget(self._swatch)
        row.addStretch()
        layout.addLayout(row)

        # Quick-pick preset row
        preset_row = QHBoxLayout()
        preset_row.setSpacing(3)
        for name, rgb in PRESET_COLORS.items():
            btn = QPushButton()
            btn.setFixedSize(18, 18)
            btn.setToolTip(name)
            btn.setStyleSheet(
                f"background-color: {rgb.to_hex()}; border: 1px solid #555; "
                "border-radius: 2px;"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, c=rgb: self._set_and_emit(c))
            preset_row.addWidget(btn)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        self._update_swatch()

    def _update_swatch(self) -> None:
        h = self._color.to_hex()
        self._swatch.setStyleSheet(
            f"background-color: {h}; border: 1px solid #888; border-radius: 3px;"
        )

    def _open_dialog(self) -> None:
        initial = QColor(self._color.to_hex())
        c = QColorDialog.getColor(initial, self, "Pick LED Color")
        if c.isValid():
            rgb = RGBColor(c.red() >> 1, c.green() >> 1, c.blue() >> 1)
            self._set_and_emit(rgb)

    def _set_and_emit(self, c: RGBColor) -> None:
        self._color = c
        self._update_swatch()
        self.changed.emit(c)

    def color(self) -> RGBColor:
        return self._color

    def set_color(self, c: RGBColor, *, block: bool = True) -> None:
        self._color = c
        self._update_swatch()


class ColorEditor(QWidget):
    """Right-side panel for editing the selected LED(s)."""

    config_changed = pyqtSignal()

    def __init__(self, state: ControllerState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._elements: List[Element] = []

        self.setMinimumWidth(260)
        self.setMaximumWidth(360)

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # -- selection info -------------------------------------------------
        self._sel_label = QLabel("No LED selected")
        self._sel_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        root.addWidget(self._sel_label)

        # -- mode -----------------------------------------------------------
        mode_group = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_group)
        self._mode_combo = QComboBox()
        for m in LEDMode:
            self._mode_combo.addItem(m.value.capitalize(), m.value)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_change)
        mode_layout.addWidget(self._mode_combo)
        root.addWidget(mode_group)

        # -- colors ---------------------------------------------------------
        color_group = QGroupBox("Colors")
        color_layout = QVBoxLayout(color_group)

        self._idle_color = _ColorPicker("Idle:")
        self._idle_color.changed.connect(self._on_idle_change)
        color_layout.addWidget(self._idle_color)

        self._active_color = _ColorPicker("Active:")
        self._active_color.changed.connect(self._on_active_change)
        color_layout.addWidget(self._active_color)

        self._active_hint = QLabel("(used when toggled / held)")
        self._active_hint.setStyleSheet("color: #888; font-size: 11px;")
        color_layout.addWidget(self._active_hint)

        root.addWidget(color_group)

        # -- quick actions --------------------------------------------------
        actions_group = QGroupBox("Quick Actions")
        actions_layout = QVBoxLayout(actions_group)

        row1 = QHBoxLayout()
        btn_all = QPushButton("Apply to all LEDs")
        btn_all.clicked.connect(self._apply_to_all)
        row1.addWidget(btn_all)
        actions_layout.addLayout(row1)

        row2 = QHBoxLayout()
        btn_knobs = QPushButton("All knobs")
        btn_knobs.clicked.connect(self._apply_to_knobs)
        row2.addWidget(btn_knobs)

        btn_buttons = QPushButton("All buttons")
        btn_buttons.clicked.connect(self._apply_to_buttons)
        row2.addWidget(btn_buttons)
        actions_layout.addLayout(row2)

        root.addWidget(actions_group)

        # -- gradient tool --------------------------------------------------
        grad_group = QGroupBox("Gradient Tool")
        grad_layout = QVBoxLayout(grad_group)

        self._grad_start = _ColorPicker("Start:")
        grad_layout.addWidget(self._grad_start)

        self._grad_end = _ColorPicker("End:")
        grad_layout.addWidget(self._grad_end)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Direction:"))
        self._grad_dir = QComboBox()
        self._grad_dir.addItem("Each element", "all")
        self._grad_dir.addItem("Per column  ←→", "col")
        self._grad_dir.addItem("Per row  ↕", "row")
        dir_row.addWidget(self._grad_dir)
        grad_layout.addLayout(dir_row)

        btn_grad = QPushButton("Apply Gradient")
        btn_grad.clicked.connect(self._apply_gradient)
        grad_layout.addWidget(btn_grad)

        self._grad_hint = QLabel(
            "Per column: same color for whole column,\n"
            "gradient spreads left → right.\n"
            "Per row: same color for whole row,\n"
            "gradient spreads top → bottom."
        )
        self._grad_hint.setStyleSheet("color: #888; font-size: 10px;")
        self._grad_hint.setWordWrap(True)
        grad_layout.addWidget(self._grad_hint)

        root.addWidget(grad_group)

        root.addStretch()

        # initial state
        self._update_ui()

    # -- public API ---------------------------------------------------------

    def set_elements(self, elements: List[Element]) -> None:
        self._elements = elements
        self._update_ui()

    # -- internal -----------------------------------------------------------

    def _current_config(self) -> LEDConfig:
        return LEDConfig(
            idle_color=self._idle_color.color(),
            active_color=self._active_color.color(),
            mode=LEDMode(self._mode_combo.currentData()),
        )

    def _apply_config(self, targets: List[Element]) -> None:
        cfg = self._current_config()
        for elem in targets:
            self._state.set_config(elem, LEDConfig(
                idle_color=cfg.idle_color,
                active_color=cfg.active_color,
                mode=cfg.mode,
            ))
        self.config_changed.emit()

    def _update_ui(self) -> None:
        n = len(self._elements)
        if n == 0:
            self._sel_label.setText("No LED selected")
            self.setEnabled(False)
            return
        self.setEnabled(True)
        if n == 1:
            self._sel_label.setText(self._elements[0].label)
        else:
            self._sel_label.setText(f"{n} LEDs selected")

        cfg = self._state.get_config(self._elements[0])
        idx = list(LEDMode).index(cfg.mode)
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(idx)
        self._mode_combo.blockSignals(False)

        self._idle_color.set_color(cfg.idle_color)
        self._active_color.set_color(cfg.active_color)

        show_active = cfg.mode != LEDMode.STATIC
        self._active_color.setVisible(show_active)
        self._active_hint.setVisible(show_active)

    # -- slots --------------------------------------------------------------

    def _on_mode_change(self) -> None:
        show_active = LEDMode(self._mode_combo.currentData()) != LEDMode.STATIC
        self._active_color.setVisible(show_active)
        self._active_hint.setVisible(show_active)
        self._apply_config(self._elements)

    def _on_idle_change(self, _color: RGBColor) -> None:
        self._apply_config(self._elements)

    def _on_active_change(self, _color: RGBColor) -> None:
        self._apply_config(self._elements)

    def _apply_to_all(self) -> None:
        self._apply_config(ALL_LED_ELEMENTS)

    def _apply_to_knobs(self) -> None:
        self._apply_config(KNOB_ELEMENTS)

    def _apply_to_buttons(self) -> None:
        self._apply_config(BUTTON_ELEMENTS)

    # -- gradient -----------------------------------------------------------

    @staticmethod
    def _lerp_color(a: RGBColor, b: RGBColor, t: float) -> RGBColor:
        """Linear interpolation between two colors, t in [0, 1]."""
        return RGBColor(
            r=int(a.r + (b.r - a.r) * t + 0.5),
            g=int(a.g + (b.g - a.g) * t + 0.5),
            b=int(a.b + (b.b - a.b) * t + 0.5),
        )

    def _apply_gradient(self) -> None:
        targets = self._elements
        if len(targets) < 2:
            return

        direction = self._grad_dir.currentData()
        start = self._grad_start.color()
        end = self._grad_end.color()

        if direction == "col":
            # Group by column — each column is one gradient step, left→right
            unique_cols = sorted(set(e.col for e in targets))
            steps = len(unique_cols)
            col_to_color = {}
            for i, c in enumerate(unique_cols):
                t = i / max(steps - 1, 1)
                col_to_color[c] = self._lerp_color(start, end, t)
            for elem in targets:
                color = col_to_color[elem.col]
                cfg = self._state.get_config(elem)
                self._state.set_config(elem, LEDConfig(
                    idle_color=color, active_color=cfg.active_color, mode=cfg.mode,
                ))

        elif direction == "row":
            # Group by row — each row is one gradient step, top→bottom
            unique_rows = sorted(set(e.row for e in targets))
            steps = len(unique_rows)
            row_to_color = {}
            for i, r in enumerate(unique_rows):
                t = i / max(steps - 1, 1)
                row_to_color[r] = self._lerp_color(start, end, t)
            for elem in targets:
                color = row_to_color[elem.row]
                cfg = self._state.get_config(elem)
                self._state.set_config(elem, LEDConfig(
                    idle_color=color, active_color=cfg.active_color, mode=cfg.mode,
                ))

        else:  # "all" — each element gets its own gradient step
            ordered = sorted(targets, key=lambda e: (e.row, e.col))
            steps = len(ordered)
            for i, elem in enumerate(ordered):
                t = i / max(steps - 1, 1)
                color = self._lerp_color(start, end, t)
                cfg = self._state.get_config(elem)
                self._state.set_config(elem, LEDConfig(
                    idle_color=color, active_color=cfg.active_color, mode=cfg.mode,
                ))

        self.config_changed.emit()
