from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog

from screen_to_agent.config import InputShortcuts
from screen_to_agent.presentation.settings_dialog import SettingsDialog


def _apply_recorder(records: list[tuple[str, str, InputShortcuts, int, int]]):
    def apply(
        hotkey: str,
        storage_root: str,
        shortcuts: InputShortcuts,
        font_size: int,
        image_width: int,
    ) -> tuple[bool, str]:
        records.append((hotkey, storage_root, shortcuts, font_size, image_width))
        return True, ""

    return apply


def test_settings_apply_hotkey_storage_and_shortcuts(qapp) -> None:
    records: list[tuple[str, str, InputShortcuts, int, int]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        dialog = SettingsDialog(
            "F1",
            "",
            InputShortcuts(),
            13,
            360,
            lambda _spec: (True, ""),
            _apply_recorder(records),
            temp_dir,
        )
        dialog._modifier_boxes["Ctrl"].setChecked(True)
        dialog._combo.setCurrentText("F3")
        dialog._storage_edit.setText(str(Path(temp_dir) / "data"))
        dialog._shortcut_edits["conversation_send"].setKeySequence(
            QKeySequence("Ctrl+Return")
        )
        qapp.processEvents()

        assert dialog.selected_hotkey() == "Ctrl+F3"
        dialog._save()
        qapp.processEvents()

        assert len(records) == 1
        hotkey, storage_root, shortcuts, font_size, image_width = records[0]
        assert hotkey == "Ctrl+F3"
        assert storage_root == str(Path(temp_dir) / "data")
        assert shortcuts.conversation_send == "Ctrl+Return"
        assert font_size == 13
        assert image_width == 360
        assert dialog.result() == QDialog.DialogCode.Accepted
        dialog.deleteLater()


def test_settings_apply_font_size(qapp) -> None:
    records: list[tuple[str, str, InputShortcuts, int, int]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        dialog = SettingsDialog(
            "F1",
            "",
            InputShortcuts(),
            13,
            360,
            lambda _spec: (True, ""),
            _apply_recorder(records),
            temp_dir,
        )
        assert dialog.selected_font_size() == 13
        dialog._font_spin.setValue(18)
        qapp.processEvents()

        assert "18pt" in dialog._font_preview.styleSheet()
        dialog._save()
        qapp.processEvents()

        assert records[0][3] == 18
        dialog.deleteLater()


def test_settings_apply_image_width(qapp) -> None:
    records: list[tuple[str, str, InputShortcuts, int, int]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        dialog = SettingsDialog(
            "F1",
            "",
            InputShortcuts(),
            13,
            360,
            lambda _spec: (True, ""),
            _apply_recorder(records),
            temp_dir,
        )
        assert dialog.selected_image_width() == 360
        dialog._image_spin.setValue(520)
        qapp.processEvents()

        dialog._save()
        qapp.processEvents()

        assert records[0][4] == 520
        dialog.deleteLater()


def test_conflicting_hotkey_blocks_save(qapp) -> None:
    records: list[tuple[str, str, InputShortcuts, int, int]] = []

    def probe(spec: str) -> tuple[bool, str]:
        return False, f"{spec} 已被其他程序占用，无法选择。"

    with tempfile.TemporaryDirectory() as temp_dir:
        dialog = SettingsDialog(
            "F1",
            "",
            InputShortcuts(),
            13,
            360,
            probe,
            _apply_recorder(records),
            temp_dir,
        )
        dialog._combo.setCurrentText("F2")
        dialog._save()
        qapp.processEvents()

        assert records == []
        assert "占用" in dialog._status.text()
        assert dialog.result() != QDialog.DialogCode.Accepted
        dialog.deleteLater()


def test_conflicting_input_shortcuts_block_save(qapp) -> None:
    records: list[tuple[str, str, InputShortcuts, int, int]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        dialog = SettingsDialog(
            "F1",
            "",
            InputShortcuts(),
            13,
            360,
            lambda _spec: (True, ""),
            _apply_recorder(records),
            temp_dir,
        )
        dialog._shortcut_edits["screenshot_exit"].setKeySequence(
            QKeySequence("Ctrl+Return")
        )
        dialog._save()
        qapp.processEvents()

        assert records == []
        assert "冲突" in dialog._status.text()
        assert dialog.result() != QDialog.DialogCode.Accepted
        dialog.deleteLater()


def test_apply_failure_keeps_dialog_open(qapp) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        dialog = SettingsDialog(
            "F1",
            "",
            InputShortcuts(),
            13,
            360,
            lambda _spec: (True, ""),
            lambda _hotkey, _root, _shortcuts, _font_size, _image_width: (
                False,
                "保存配置失败。",
            ),
            temp_dir,
        )
        dialog._save()
        qapp.processEvents()

        assert "保存配置失败" in dialog._status.text()
        assert dialog.result() != QDialog.DialogCode.Accepted
        dialog.deleteLater()
