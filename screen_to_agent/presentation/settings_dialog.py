from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from screen_to_agent.config import (
    CONVERSATION_FONT_SIZE_DEFAULT,
    CONVERSATION_FONT_SIZE_MAX,
    CONVERSATION_FONT_SIZE_MIN,
    CONVERSATION_IMAGE_WIDTH_DEFAULT,
    CONVERSATION_IMAGE_WIDTH_MAX,
    CONVERSATION_IMAGE_WIDTH_MIN,
    InputShortcuts,
)
from screen_to_agent.presentation.shortcut_utils import validate_input_shortcuts

_FKEYS = [f"F{index}" for index in range(1, 13)]
_MODIFIERS = (
    ("Ctrl", "CTRL"),
    ("Alt", "ALT"),
    ("Shift", "SHIFT"),
    ("Win", "WIN"),
)


class SettingsDialog(QDialog):
    def __init__(
        self,
        current_hotkey: str,
        current_storage_root: str,
        current_shortcuts: InputShortcuts,
        current_font_size: int,
        current_image_width: int,
        probe_hotkey: Callable[[str], tuple[bool, str]],
        apply_settings: Callable[
            [str, str, InputShortcuts, int, int], tuple[bool, str]
        ],
        default_root: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._probe_hotkey = probe_hotkey
        self._apply_settings = apply_settings
        self._default_root = default_root
        self.setWindowTitle("ScreenToAgent 设置")
        self.setModal(True)
        self.setMinimumSize(640, 820)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(
            "QDialog { background: #1F2430; }"
            "QLabel { color: #E8EEF8; }"
            "QCheckBox { color: #E8EEF8; }"
            "QComboBox, QLineEdit, QKeySequenceEdit, QSpinBox { color: #E8EEF8;"
            "  background: #2A3140; border: 1px solid #4C9AFF;"
            "  border-radius: 5px; padding: 5px 8px; }"
            "QComboBox QAbstractItemView { color: #E8EEF8; background: #2A3140;"
            "  selection-background-color: #2D6CDF; selection-color: #FFFFFF; }"
            "QPushButton { color: #FFFFFF; background: #2D6CDF; border: none;"
            "  border-radius: 5px; padding: 6px 16px; }"
            "QPushButton:hover { background: #3D7CEF; }"
            "QPushButton:disabled { background: #3A4252; color: #8793A8; }"
            "QPushButton#ghost { background: rgba(255, 255, 255, 0.14); }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel("设置")
        title.setStyleSheet("font: 600 16pt 'Microsoft YaHei UI';")
        layout.addWidget(title)

        hotkey_title = QLabel("截图快捷键")
        hotkey_title.setStyleSheet("font: 600 12pt 'Microsoft YaHei UI';")
        layout.addWidget(hotkey_title)
        hotkey_hint = QLabel("支持 F1–F12，可叠加 Ctrl / Alt / Shift / Win。")
        hotkey_hint.setStyleSheet("color: #9FB3D1; font: 9pt 'Microsoft YaHei UI';")
        layout.addWidget(hotkey_hint)

        self._combo = QComboBox()
        self._combo.addItems(_FKEYS)
        layout.addWidget(self._combo)

        modifiers = QWidget()
        modifier_layout = QHBoxLayout(modifiers)
        modifier_layout.setContentsMargins(0, 0, 0, 0)
        modifier_layout.setSpacing(16)
        self._modifier_boxes: dict[str, QCheckBox] = {}
        for label, _ in _MODIFIERS:
            box = QCheckBox(label)
            modifier_layout.addWidget(box)
            self._modifier_boxes[label] = box
        modifier_layout.addStretch(1)
        layout.addWidget(modifiers)

        storage_title = QLabel("附件存储位置")
        storage_title.setStyleSheet("font: 600 12pt 'Microsoft YaHei UI';")
        layout.addWidget(storage_title)
        storage_hint = QLabel(
            "实际附件保存在所选根目录下的 attachments 子目录；旧附件不会自动迁移。"
        )
        storage_hint.setWordWrap(True)
        storage_hint.setStyleSheet("color: #9FB3D1; font: 9pt 'Microsoft YaHei UI';")
        layout.addWidget(storage_hint)

        storage_row = QHBoxLayout()
        self._storage_edit = QLineEdit(current_storage_root or default_root)
        self._storage_edit.textChanged.connect(self._update_storage_status)
        storage_row.addWidget(self._storage_edit, 1)
        browse = QPushButton("浏览…")
        browse.setObjectName("ghost")
        browse.clicked.connect(self._browse_storage)
        storage_row.addWidget(browse)
        open_dir = QPushButton("打开目录")
        open_dir.setObjectName("ghost")
        open_dir.clicked.connect(self._open_storage)
        storage_row.addWidget(open_dir)
        layout.addLayout(storage_row)

        self._storage_status = QLabel("")
        self._storage_status.setWordWrap(True)
        self._storage_status.setStyleSheet(
            "color: #9FB3D1; font: 9pt 'Microsoft YaHei UI';"
        )
        layout.addWidget(self._storage_status)
        self._update_storage_status()

        shortcuts_title = QLabel("输入快捷键")
        shortcuts_title.setStyleSheet("font: 600 12pt 'Microsoft YaHei UI';")
        layout.addWidget(shortcuts_title)
        shortcuts_hint = QLabel(
            "截图输入：退出会保留草稿；会话输入：退出只让输入框失焦，不隐藏会话。"
        )
        shortcuts_hint.setWordWrap(True)
        shortcuts_hint.setStyleSheet("color: #9FB3D1; font: 9pt 'Microsoft YaHei UI';")
        layout.addWidget(shortcuts_hint)

        self._shortcut_edits: dict[str, QKeySequenceEdit] = {}
        for key, label, value in (
            ("screenshot_send", "截图发送", current_shortcuts.screenshot_send),
            ("screenshot_exit", "截图退出", current_shortcuts.screenshot_exit),
            ("conversation_send", "会话发送", current_shortcuts.conversation_send),
            ("conversation_exit", "会话退出", current_shortcuts.conversation_exit),
        ):
            row = QHBoxLayout()
            label_widget = QLabel(label)
            label_widget.setMinimumWidth(90)
            row.addWidget(label_widget)
            edit = QKeySequenceEdit(QKeySequence(value))
            edit.setMaximumSequenceLength(1)
            edit.editingFinished.connect(self._refresh_status)
            row.addWidget(edit, 1)
            self._shortcut_edits[key] = edit
            layout.addLayout(row)

        display_title = QLabel("会话显示")
        display_title.setStyleSheet("font: 600 12pt 'Microsoft YaHei UI';")
        layout.addWidget(display_title)
        display_hint = QLabel(
            "调节会话历史正文、输入框字号与历史图片宽度；"
            "角色标签固定比正文大 2pt。"
        )
        display_hint.setWordWrap(True)
        display_hint.setStyleSheet("color: #9FB3D1; font: 9pt 'Microsoft YaHei UI';")
        layout.addWidget(display_hint)

        font_row = QHBoxLayout()
        font_label = QLabel("字号")
        font_label.setMinimumWidth(90)
        font_row.addWidget(font_label)
        self._font_spin = QSpinBox()
        self._font_spin.setRange(CONVERSATION_FONT_SIZE_MIN, CONVERSATION_FONT_SIZE_MAX)
        self._font_spin.setSingleStep(1)
        self._font_spin.setSuffix(" pt")
        self._font_spin.setValue(
            max(
                CONVERSATION_FONT_SIZE_MIN,
                min(CONVERSATION_FONT_SIZE_MAX, current_font_size),
            )
        )
        font_row.addWidget(self._font_spin)
        font_row.addStretch(1)
        layout.addLayout(font_row)

        self._font_preview = QLabel("预览：Agent 回答与输入框会以该字号显示。")
        self._font_preview.setWordWrap(True)
        layout.addWidget(self._font_preview)
        self._font_spin.valueChanged.connect(self._update_font_preview)
        self._update_font_preview(self._font_spin.value())

        image_row = QHBoxLayout()
        image_label = QLabel("图片宽度")
        image_label.setMinimumWidth(90)
        image_row.addWidget(image_label)
        self._image_spin = QSpinBox()
        self._image_spin.setRange(
            CONVERSATION_IMAGE_WIDTH_MIN, CONVERSATION_IMAGE_WIDTH_MAX
        )
        self._image_spin.setSingleStep(20)
        self._image_spin.setSuffix(" px")
        self._image_spin.setValue(
            max(
                CONVERSATION_IMAGE_WIDTH_MIN,
                min(CONVERSATION_IMAGE_WIDTH_MAX, current_image_width),
            )
        )
        image_row.addWidget(self._image_spin)
        image_row.addStretch(1)
        layout.addLayout(image_row)
        image_hint = QLabel("历史图片按该宽度显示并保持原比例。")
        image_hint.setStyleSheet("color: #9FB3D1; font: 9pt 'Microsoft YaHei UI';")
        layout.addWidget(image_hint)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(46)
        self._status.setStyleSheet("color: #9FB3D1; font: 9pt 'Microsoft YaHei UI';")
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        reset = QPushButton("恢复默认")
        reset.setObjectName("ghost")
        reset.clicked.connect(self._reset_defaults)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("保存")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._load_hotkey(current_hotkey)
        self._combo.currentTextChanged.connect(self._refresh_status)
        for box in self._modifier_boxes.values():
            box.toggled.connect(self._refresh_status)
        self._refresh_status()

    def selected_hotkey(self) -> str:
        parts = [
            label for label, _ in _MODIFIERS if self._modifier_boxes[label].isChecked()
        ]
        parts.append(self._combo.currentText())
        return "+".join(parts)

    def selected_shortcuts(self) -> InputShortcuts:
        values = {
            key: edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            for key, edit in self._shortcut_edits.items()
        }
        return InputShortcuts(
            screenshot_send=values["screenshot_send"],
            screenshot_exit=values["screenshot_exit"],
            conversation_send=values["conversation_send"],
            conversation_exit=values["conversation_exit"],
        )

    def selected_font_size(self) -> int:
        return self._font_spin.value()

    def selected_image_width(self) -> int:
        return self._image_spin.value()

    def _update_font_preview(self, size: int) -> None:
        self._font_preview.setStyleSheet(
            f"color: #E8EEF8; font: {size}pt 'Microsoft YaHei UI';"
        )

    def _load_hotkey(self, spec: str) -> None:
        parts = [part.strip().upper() for part in spec.split("+") if part.strip()]
        key = parts[-1] if parts and parts[-1] in _FKEYS else "F1"
        modifiers = set(parts[:-1])
        self._combo.setCurrentText(key)
        for label, token in _MODIFIERS:
            self._modifier_boxes[label].setChecked(token in modifiers)

    def _refresh_status(self) -> None:
        spec = self.selected_hotkey()
        try:
            available, message = self._probe_hotkey(spec)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            available, message = False, f"检测快捷键失败：{exc}"
        if not available:
            self._set_status(message or f"{spec} 已被占用，无法选择。", error=True)
            return

        shortcuts = self.selected_shortcuts()
        shortcuts_ok, shortcuts_message = validate_input_shortcuts(shortcuts, spec)
        if not shortcuts_ok:
            self._set_status(shortcuts_message, error=True)
            return
        self._set_status("设置可用。", error=False)

    def _set_status(self, message: str, error: bool) -> None:
        self._status.setText(message)
        color = "#FF7B72" if error else "#7EE787"
        self._status.setStyleSheet(
            f"color: {color}; font: 9pt 'Microsoft YaHei UI';"
        )

    def _browse_storage(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择附件存储根目录",
            self._storage_edit.text() or self._default_root,
        )
        if selected:
            self._storage_edit.setText(selected)
            self._update_storage_status()

    def _open_storage(self) -> None:
        path = Path(self._storage_edit.text() or self._default_root)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _update_storage_status(self) -> None:
        root = Path(self._storage_edit.text() or self._default_root)
        self._storage_status.setText(f"实际附件目录：{root / 'attachments'}")

    def _reset_defaults(self) -> None:
        self._storage_edit.setText(self._default_root)
        self._font_spin.setValue(CONVERSATION_FONT_SIZE_DEFAULT)
        self._image_spin.setValue(CONVERSATION_IMAGE_WIDTH_DEFAULT)
        for key, value in (
            ("screenshot_send", "Ctrl+Return"),
            ("screenshot_exit", "Esc"),
            ("conversation_send", "Return"),
            ("conversation_exit", "Esc"),
        ):
            self._shortcut_edits[key].setKeySequence(QKeySequence(value))
        self._update_storage_status()
        self._refresh_status()

    def _save(self) -> None:
        hotkey = self.selected_hotkey()
        available, message = self._probe_hotkey(hotkey)
        if not available:
            self._set_status(message or "截图快捷键不可用。", error=True)
            return

        shortcuts = self.selected_shortcuts()
        shortcuts_ok, shortcuts_message = validate_input_shortcuts(shortcuts, hotkey)
        if not shortcuts_ok:
            self._set_status(shortcuts_message, error=True)
            return

        root_text = self._storage_edit.text().strip() or self._default_root
        root = Path(root_text).expanduser()
        if not root.is_absolute():
            self._set_status("存储位置必须是绝对路径。", error=True)
            return
        if os.path.normcase(str(root)) == os.path.normcase(str(Path(self._default_root))):
            storage_value = ""
        else:
            storage_value = str(root)

        applied, apply_message = self._apply_settings(
            hotkey,
            storage_value,
            shortcuts,
            self.selected_font_size(),
            self.selected_image_width(),
        )
        if not applied:
            self._set_status(apply_message or "设置应用失败。", error=True)
            return
        self.accept()
