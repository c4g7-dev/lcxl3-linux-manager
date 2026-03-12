"""Main application window — assembles controller view, color editor, and scene panel."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QMetaObject, QTimer, Qt, Q_ARG, pyqtSlot
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QSlider,
    QSystemTrayIcon,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..led_state import ControllerState, Element, ElementKind, ALL_LED_ELEMENTS, RGBColor
from ..midi_backend import MidiBackend
from .. import presets
from .controller_widget import ControllerWidget
from .color_editor import ColorEditor
from .scene_panel import ScenePanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LCXL MK3 — LED Manager")
        self.setStyleSheet(_DARK_STYLE)

        # Core objects
        self._state = ControllerState()
        self._midi = MidiBackend()

        # Quick lookup: key → Element  (for thread-safe MIDI callbacks)
        self._elem_by_key = {
            ControllerState.key_for(e.kind, e.hw_id): e for e in ALL_LED_ELEMENTS
        }

        # -- central layout -------------------------------------------------
        central = QWidget()
        self.setCentralWidget(central)
        h = QHBoxLayout(central)

        # Scene panel (left)
        self._scene_panel = ScenePanel(self._state)
        self._scene_panel.scene_loaded.connect(self._on_scene_loaded)
        self._scene_panel.pre_save_hook = self._sync_state_from_gui
        h.addWidget(self._scene_panel)

        # Controller view (centre)
        self._controller = ControllerWidget(self._state)
        self._controller.selection_changed.connect(self._on_selection_changed)
        self._controller.display_set_requested.connect(self._send_display_text)
        self._controller.display_clear_requested.connect(self._clear_display_text)
        h.addWidget(self._controller, 1)

        # Color editor (right)
        self._color_editor = ColorEditor(self._state)
        self._color_editor.config_changed.connect(self._on_config_changed)
        h.addWidget(self._color_editor)

        # -- toolbar --------------------------------------------------------
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self._status_label = QLabel("  Disconnected  ")
        self._status_label.setStyleSheet(
            "color: #ff4444; font-weight: bold; padding: 2px 8px;"
        )
        tb.addWidget(self._status_label)
        tb.addSeparator()

        self._act_connect = QAction("Connect", self)
        self._act_connect.triggered.connect(self._toggle_connection)
        tb.addAction(self._act_connect)

        act_reset = QAction("All LEDs Off", self)
        act_reset.triggered.connect(self._reset_leds)
        tb.addAction(act_reset)

        act_push = QAction("Push All", self)
        act_push.triggered.connect(self._push_all)
        tb.addAction(act_push)

        tb.addSeparator()

        # LED Brightness slider
        tb.addWidget(QLabel(" Brightness: "))
        self._brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self._brightness_slider.setRange(0, 127)
        self._brightness_slider.setValue(127)
        self._brightness_slider.setFixedWidth(100)
        self._brightness_slider.setToolTip("LED brightness (CC 111)")
        self._brightness_slider.valueChanged.connect(self._on_brightness_change)
        tb.addWidget(self._brightness_slider)
        self._brightness_label = QLabel("127")
        self._brightness_label.setFixedWidth(28)
        tb.addWidget(self._brightness_label)

        # -- MIDI callbacks (called from listener thread) ------------------
        self._midi.on_button_press = self._on_hw_press_threadsafe
        self._midi.on_button_release = self._on_hw_release_threadsafe
        self._midi.on_cc = self._on_hw_cc_threadsafe
        self._midi.on_disconnect = self._on_midi_disconnect

        # -- timers ---------------------------------------------------------
        # Auto-reconnect every 3 seconds
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        self._reconnect_timer.start(3000)
        self._manual_disconnect = False  # True when user clicked Disconnect

        # MIDI poll (triggers GUI refresh for live LED changes)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._controller.refresh)
        self._refresh_timer.start(50)

        # Debounced CC auto-save (2 seconds after last CC change)
        self._cc_save_timer = QTimer(self)
        self._cc_save_timer.setSingleShot(True)
        self._cc_save_timer.setInterval(2000)
        self._cc_save_timer.timeout.connect(self._auto_save_cc)

        # -- system tray ----------------------------------------------------
        self._setup_tray()

        # -- initial state --------------------------------------------------
        self._try_connect()
        self._load_last_scene()

    # -- tray ---------------------------------------------------------------

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(self)
        icon = QIcon(str(Path(__file__).parent.parent / "resources" / "icon.svg"))
        self._tray.setIcon(icon)
        self._tray.setToolTip("LCXL MK3 LED Manager")
        menu = QMenu()
        act_show = menu.addAction("Show")
        act_show.triggered.connect(self.show)
        menu.addSeparator()
        # Scene quick-switch submenu
        self._tray_scene_menu = menu.addMenu("Scenes")
        self._rebuild_tray_scenes()
        menu.addSeparator()
        act_quit = menu.addAction("Quit")
        act_quit.triggered.connect(self._quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _rebuild_tray_scenes(self) -> None:
        if not self._tray:
            return
        self._tray_scene_menu.clear()
        for name in presets.list_scenes():
            act = self._tray_scene_menu.addAction(name)
            act.triggered.connect(lambda checked, n=name: self._load_scene_by_name(n))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show()
            self.raise_()
            self.activateWindow()

    # -- close / quit -------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._tray:
            self.hide()
            event.ignore()
        else:
            self._shutdown()
            event.accept()

    def _quit(self) -> None:
        self._shutdown()
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def _shutdown(self) -> None:
        self._reconnect_timer.stop()
        self._refresh_timer.stop()
        self._cc_save_timer.stop()
        # Flush any pending CC save before exit
        self._auto_save_cc()
        self._midi.reset_leds()
        self._midi.disconnect()

    # -- MIDI connection ----------------------------------------------------

    def _toggle_connection(self) -> None:
        if self._midi.connected:
            self._manual_disconnect = True
            self._midi.disconnect()
            self._update_connection_ui(False)
        else:
            self._manual_disconnect = False
            self._try_connect()

    def _try_connect(self) -> None:
        if self._midi.connect():
            self._update_connection_ui(True)
            self._midi.setup_encoder_names()
            self._midi.push_all(self._state)
            # Restore idle display text if set
            txt = self._controller.display_text
            if txt:
                self._midi.set_stationary_display(txt)
            # Delay CC replay — PipeWire needs time to route the VirMIDI port
            QTimer.singleShot(1500, self._push_saved_cc)
        else:
            self._update_connection_ui(False)

    def _push_saved_cc(self) -> None:
        """Replay saved CC positions to VirMIDI after PipeWire routing settles."""
        if self._midi.connected:
            self._midi.push_cc_state(self._state)

    def _update_connection_ui(self, connected: bool) -> None:
        if connected:
            self._status_label.setText("  Connected  ")
            self._status_label.setStyleSheet(
                "color: #44ff44; font-weight: bold; padding: 2px 8px;"
            )
            self._act_connect.setText("Disconnect")
        else:
            self._status_label.setText("  Disconnected  ")
            self._status_label.setStyleSheet(
                "color: #ff4444; font-weight: bold; padding: 2px 8px;"
            )
            self._act_connect.setText("Connect")

    def _try_reconnect(self) -> None:
        if not self._midi.connected and not self._manual_disconnect:
            self._try_connect()

    def _on_midi_disconnect(self) -> None:
        self._update_connection_ui(False)

    # -- hardware input handling (thread-safe) -----------------------------

    def _on_hw_press_threadsafe(self, elem: Element) -> None:
        """Called from MIDI listener thread — marshal to main thread."""
        QMetaObject.invokeMethod(
            self, "_do_hw_press",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, elem.hw_id), Q_ARG(str, elem.kind.value),
        )

    def _on_hw_release_threadsafe(self, elem: Element) -> None:
        """Called from MIDI listener thread — marshal to main thread."""
        QMetaObject.invokeMethod(
            self, "_do_hw_release",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, elem.hw_id), Q_ARG(str, elem.kind.value),
        )

    @pyqtSlot(int, str)
    def _do_hw_press(self, hw_id: int, kind_val: str) -> None:
        kind = ElementKind(kind_val)
        key = ControllerState.key_for(kind, hw_id)
        elem = self._elem_by_key.get(key)
        if elem is None:
            return
        color = self._state.on_press(elem)
        self._midi.set_led(elem, color)

    @pyqtSlot(int, str)
    def _do_hw_release(self, hw_id: int, kind_val: str) -> None:
        kind = ElementKind(kind_val)
        key = ControllerState.key_for(kind, hw_id)
        elem = self._elem_by_key.get(key)
        if elem is None:
            return
        color = self._state.on_release(elem)
        self._midi.set_led(elem, color)

    def _on_hw_cc_threadsafe(self, cc: int, value: int) -> None:
        """Called from MIDI listener thread for encoder/fader CC."""
        QMetaObject.invokeMethod(
            self, "_do_hw_cc",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, cc), Q_ARG(int, value),
        )

    @pyqtSlot(int, int)
    def _do_hw_cc(self, cc: int, value: int) -> None:
        self._state.set_cc_value(cc, value)
        # Debounced auto-save so CC positions persist across restarts
        self._cc_save_timer.start()

    def _auto_save_cc(self) -> None:
        """Save current scene to disk (debounced) to persist CC values."""
        name = getattr(self, '_current_scene_name', None)
        if name and not presets.is_protected(name):
            self._sync_state_from_gui()
            presets.save_scene(name, self._state)

    # -- GUI actions --------------------------------------------------------

    def _on_selection_changed(self) -> None:
        self._color_editor.set_elements(self._controller.selected_elements)

    def _on_config_changed(self) -> None:
        """User changed colour/mode in the editor — push to hardware."""
        # Block edits on protected profiles
        if hasattr(self, '_current_scene_name') and presets.is_protected(
                self._current_scene_name):
            return
        for elem in self._controller.selected_elements:
            self._midi.set_led(elem, self._state.current_color(elem))
        self._controller.refresh()

    def _on_scene_loaded(self, name: str) -> None:
        self._state.reset_toggles()
        self._midi.push_all(self._state)
        self._controller.refresh()
        self._color_editor.set_elements(self._controller.selected_elements)
        self._rebuild_tray_scenes()
        self.setWindowTitle(f"LCXL MK3 — {name}")
        # Restore display text and brightness from profile
        self._controller.display_text = self._state.display_text
        if self._state.display_text:
            self._midi.set_stationary_display(self._state.display_text)
        else:
            self._midi.clear_stationary_display()
        self._brightness_slider.setValue(self._state.brightness)
        self._midi.set_brightness(self._state.brightness)
        # Lock editing for protected profiles
        locked = presets.is_protected(name)
        self._controller.set_locked(locked)
        self._controller.set_display_editable(not locked)
        self._color_editor.setEnabled(not locked)
        self._brightness_slider.setEnabled(not locked)
        self._current_scene_name = name

    def _load_scene_by_name(self, name: str) -> None:
        try:
            presets.load_scene(name, self._state)
            presets.save_last_scene_name(name)
            self._on_scene_loaded(name)
            self._scene_panel.refresh_list()
            self._scene_panel.select_scene(name)
        except Exception:
            pass

    def _load_last_scene(self) -> None:
        name = presets.load_last_scene_name()
        if name and name in presets.list_scenes():
            self._load_scene_by_name(name)

    def _reset_leds(self) -> None:
        self._midi.reset_leds()

    def _push_all(self) -> None:
        self._midi.push_all(self._state)

    def _send_display_text(self, text: str = "") -> None:
        txt = text.strip() if text else self._controller.display_text
        if txt:
            self._midi.set_stationary_display(txt)
        else:
            self._midi.clear_stationary_display()

    def _clear_display_text(self) -> None:
        self._midi.clear_stationary_display()

    def _on_brightness_change(self, value: int) -> None:
        self._brightness_label.setText(str(value))
        self._midi.set_brightness(value)

    def _sync_state_from_gui(self) -> None:
        """Snapshot GUI-only state (display text, brightness) into ControllerState."""
        self._state.display_text = self._controller.display_text
        self._state.brightness = self._brightness_slider.value()


# ---------------------------------------------------------------------------
# Dark theme stylesheet
# ---------------------------------------------------------------------------
_DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #cccccc;
    font-family: "Segoe UI", "Noto Sans", sans-serif;
    font-size: 12px;
}
QToolBar {
    background-color: #2d2d2d;
    border: none;
    spacing: 6px;
    padding: 4px;
}
QToolBar QLabel {
    background: transparent;
}
QPushButton {
    background-color: #3a3a3a;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 5px 12px;
    color: #ddd;
}
QPushButton:hover {
    background-color: #4a4a4a;
}
QPushButton:pressed {
    background-color: #555;
}
QGroupBox {
    border: 1px solid #444;
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QComboBox {
    background-color: #3a3a3a;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 3px 8px;
    color: #ddd;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #ddd;
    selection-background-color: #4a6fa5;
}
QListWidget {
    background-color: #2a2a2a;
    border: 1px solid #444;
    border-radius: 3px;
    color: #ddd;
}
QListWidget::item:selected {
    background-color: #4a6fa5;
}
QListWidget::item:hover {
    background-color: #3a3a3a;
}
QLineEdit {
    background-color: #3a3a3a;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 3px 6px;
    color: #ddd;
}
"""
