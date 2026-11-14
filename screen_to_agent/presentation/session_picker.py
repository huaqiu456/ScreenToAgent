from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from screen_to_agent.domain.models import SessionInfo


class SessionPickerDialog(QDialog):
    def __init__(self, sessions: list[SessionInfo], parent=None) -> None:
        super().__init__(parent)
        self._sessions = {session.id: session for session in sessions}
        self.setWindowTitle("选择会话")
        self.setModal(True)
        self.resize(640, 420)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(
            "QDialog { background: #1F2430; }"
            "QLabel { color: #E8EEF8; }"
            "QListWidget { background: #2A3140; color: #E8EEF8;"
            "  border: 1px solid rgba(76, 154, 255, 0.45); border-radius: 6px; }"
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:selected { background: #2D6CDF; color: #FFFFFF; }"
            "QPushButton { color: #FFFFFF; background: #2D6CDF; border: none;"
            "  border-radius: 5px; padding: 6px 16px; }"
            "QPushButton:hover { background: #3D7CEF; }"
            "QPushButton:disabled { background: #3A4252; color: #8793A8; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        title = QLabel("选择一个 Codex CLI 会话")
        title.setStyleSheet("font: 600 13pt 'Microsoft YaHei UI';")
        layout.addWidget(title)

        self._list = QListWidget()
        for session in sessions:
            updated = session.updated_at.replace("T", " ")[:16]
            cwd = session.cwd or ""
            text = f"{session.title}\n{updated}  ·  {cwd}  ·  {session.id[:8]}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setStyleSheet("background: rgba(255, 255, 255, 0.14);")
        cancel.clicked.connect(self.reject)
        open_button = QPushButton("打开会话")
        open_button.setDefault(True)
        open_button.setEnabled(bool(sessions))
        open_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(open_button)
        layout.addLayout(buttons)

        if sessions:
            self._list.setCurrentRow(0)

    def selected_session(self) -> SessionInfo | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return self._sessions.get(item.data(Qt.ItemDataRole.UserRole))
