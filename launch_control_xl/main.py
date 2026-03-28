#!/usr/bin/env python3
"""Launch Control XL LED Manager — entry point."""

import signal
import sys
import fcntl
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon

from launch_control_xl.gui.main_window import MainWindow

_LOCK_PATH = Path("/tmp/lcxl3-manager.lock")


def _acquire_lock():
    """Try to acquire a file lock. Returns the file object if successful, else None."""
    lock_file = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(sys.modules[__name__]))
        lock_file.flush()
        return lock_file
    except OSError:
        lock_file.close()
        return None


def _icon_path() -> str:
    return str(Path(__file__).parent / "resources" / "icon.svg")


_DARK_DIALOG_STYLE = """
QMessageBox {
    background-color: #1e1e1e;
    color: #cccccc;
}
QMessageBox QLabel {
    color: #cccccc;
    font-size: 13px;
}
QPushButton {
    background-color: #3a3a3a;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 5px 16px;
    color: #ddd;
    min-width: 60px;
}
QPushButton:hover {
    background-color: #4a4a4a;
}
QPushButton:pressed {
    background-color: #555;
}
"""


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("LCXL MK3 LED Manager")
    app.setOrganizationName("lcxl")

    # Set application icon
    icon = QIcon(_icon_path())
    app.setWindowIcon(icon)

    # Single-instance check
    lock = _acquire_lock()
    if lock is None:
        app.setStyleSheet(_DARK_DIALOG_STYLE)
        dlg = QMessageBox()
        dlg.setWindowTitle("Already Running")
        dlg.setText("LCXL MK3 LED Manager is already running.\nCheck your system tray.")
        dlg.setWindowIcon(icon)
        dlg.setIconPixmap(icon.pixmap(48, 48))
        dlg.exec()
        sys.exit(0)

    # Ensure clean shutdown (LEDs off) on SIGTERM / SIGHUP (e.g. system poweroff)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: app.quit())

    # Periodic no-op timer lets Python process pending signal handlers
    # while Qt's C++ event loop is running
    _sig_timer = QTimer()
    _sig_timer.timeout.connect(lambda: None)
    _sig_timer.start(200)

    minimized = "--minimized" in sys.argv or "--tray" in sys.argv

    window = MainWindow()
    window.resize(900, 500)
    if not minimized:
        window.show()

    # Guarantee _shutdown() runs on quit even when minimised to tray
    app.aboutToQuit.connect(window._shutdown)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

