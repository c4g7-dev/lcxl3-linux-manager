"""Scene management panel — list, create, save, load, delete presets."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..led_state import ControllerState
from .. import presets


class ScenePanel(QWidget):
    """Left-side panel listing saved scenes with create / load / delete."""

    # Emitted after a scene is loaded into state
    scene_loaded = pyqtSignal(str)  # scene name

    # Callback that the main window sets so we can snapshot display text / brightness
    # before saving.  Signature: () -> None (should update state.display_text etc.)
    pre_save_hook: Optional[Callable[[], None]] = None

    def __init__(self, state: ControllerState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state

        self.setMinimumWidth(180)
        self.setMaximumWidth(240)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Scenes")
        layout = QVBoxLayout(group)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._list)

        # Buttons
        btn_row1 = QHBoxLayout()
        self._btn_new = QPushButton("New")
        self._btn_new.clicked.connect(self._new_scene)
        btn_row1.addWidget(self._btn_new)

        self._btn_save = QPushButton("Save")
        self._btn_save.clicked.connect(self._save_scene)
        btn_row1.addWidget(self._btn_save)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self._btn_rename = QPushButton("Rename")
        self._btn_rename.clicked.connect(self._rename_scene)
        btn_row2.addWidget(self._btn_rename)

        self._btn_delete = QPushButton("Delete")
        self._btn_delete.clicked.connect(self._delete_scene)
        btn_row2.addWidget(self._btn_delete)
        layout.addLayout(btn_row2)

        self._btn_load = QPushButton("Load selected")
        self._btn_load.clicked.connect(self._load_selected)
        layout.addWidget(self._btn_load)

        btn_row3 = QHBoxLayout()
        self._btn_copy = QPushButton("Copy")
        self._btn_copy.setToolTip("Duplicate the selected scene")
        self._btn_copy.clicked.connect(self._copy_scene)
        btn_row3.addWidget(self._btn_copy)
        btn_row3.addStretch()
        layout.addLayout(btn_row3)

        root.addWidget(group)
        presets.ensure_default_scene()
        self.refresh_list()

    # -- public -------------------------------------------------------------

    @property
    def current_scene_name(self) -> str | None:
        return self._scene_name_of(self._list.currentItem())

    def refresh_list(self) -> None:
        self._list.clear()
        for name in presets.list_scenes():
            item = QListWidgetItem(name)
            if presets.is_protected(name):
                item.setText(f"\U0001f512 {name}")  # 🔒 prefix
                item.setData(Qt.ItemDataRole.UserRole, name)
            else:
                item.setData(Qt.ItemDataRole.UserRole, name)
            self._list.addItem(item)

    def select_scene(self, name: str) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self._list.setCurrentRow(i)
                return

    # -- helpers ------------------------------------------------------------

    def _scene_name_of(self, item: QListWidgetItem | None) -> str | None:
        """Get the real scene name from a list item (strips lock icon)."""
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # -- slots --------------------------------------------------------------

    def _on_double_click(self, item: QListWidgetItem) -> None:
        name = self._scene_name_of(item)
        if name:
            self._load_scene(name)

    def _load_selected(self) -> None:
        name = self.current_scene_name
        if name:
            self._load_scene(name)

    def _load_scene(self, name: str) -> None:
        try:
            presets.load_scene(name, self._state)
            presets.save_last_scene_name(name)
            self.scene_loaded.emit(name)
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", str(exc))

    def _save_scene(self) -> None:
        name = self.current_scene_name
        if not name:
            self._new_scene()
            return
        if presets.is_protected(name):
            QMessageBox.information(self, "Protected",
                                   f"'{name}' cannot be overwritten.\n"
                                   "Use 'Copy' to create an editable duplicate.")
            return
        if self.pre_save_hook:
            self.pre_save_hook()
        presets.save_scene(name, self._state)
        presets.save_last_scene_name(name)

    def _new_scene(self) -> None:
        name, ok = QInputDialog.getText(self, "New Scene", "Scene name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if presets.is_protected(name):
            QMessageBox.warning(self, "Reserved", f"'{name}' is a reserved name.")
            return
        # Start with a completely blank state (no preset colours)
        blank = ControllerState()
        presets.save_scene(name, blank)
        presets.save_last_scene_name(name)
        self.refresh_list()
        self.select_scene(name)
        self.scene_loaded.emit(name)

    def _copy_scene(self) -> None:
        src = self.current_scene_name
        if not src:
            return
        default_name = f"{src} Copy"
        name, ok = QInputDialog.getText(self, "Copy Scene", "New name:", text=default_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        if presets.is_protected(name):
            QMessageBox.warning(self, "Reserved", f"'{name}' is a reserved name.")
            return
        # Load the source scene into a temp state, then save as new name
        presets.copy_scene(src, name)
        self.refresh_list()
        self.select_scene(name)

    def _rename_scene(self) -> None:
        old = self.current_scene_name
        if not old:
            return
        if presets.is_protected(old):
            QMessageBox.information(self, "Protected",
                                   f"'{old}' cannot be renamed.")
            return
        new, ok = QInputDialog.getText(self, "Rename Scene", "New name:", text=old)
        if not ok or not new.strip() or new.strip() == old:
            return
        presets.rename_scene(old, new.strip())
        self.refresh_list()
        self.select_scene(new.strip())

    def _delete_scene(self) -> None:
        name = self.current_scene_name
        if not name:
            return
        if presets.is_protected(name):
            QMessageBox.information(self, "Protected",
                                   f"'{name}' cannot be deleted.")
            return
        reply = QMessageBox.question(
            self,
            "Delete Scene",
            f"Delete scene '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            presets.delete_scene(name)
            self.refresh_list()
