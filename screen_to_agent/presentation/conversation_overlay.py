from __future__ import annotations

import html
import re
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QTextDocumentFragment,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTextEdit,
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
)
from screen_to_agent.domain.models import ChatMessage, ModelInfo
from screen_to_agent.presentation.shortcut_utils import event_matches_shortcut

_INPUT_FRAME_STYLE = (
    "QFrame { background: rgba(20, 24, 32, 0.94);"
    "  border: 1px solid rgba(76, 154, 255, 0.55); border-radius: 10px; }"
    "QTextEdit { background: rgba(255, 255, 255, 0.06); color: #F2F6FC;"
    "  border: none; border-radius: 6px; padding: 8px;"
    "  font: {font_size}pt 'Microsoft YaHei UI'; selection-background-color: #2D6CDF; }"
    "QPushButton { color: #FFFFFF; background: #2D6CDF; border: none;"
    "  border-radius: 5px; padding: 6px 14px; font: 9pt 'Microsoft YaHei UI'; }"
    "QPushButton:hover { background: #3D7CEF; }"
    "QPushButton:disabled { background: #3A4252; color: #8793A8; }"
    "QPushButton#ghost { background: rgba(255, 255, 255, 0.12); }"
    "QLabel { color: #9FB3D1; background: transparent;"
    "  font: 8pt 'Microsoft YaHei UI'; }"
)


def _clamp_font_size(size: int) -> int:
    return max(CONVERSATION_FONT_SIZE_MIN, min(CONVERSATION_FONT_SIZE_MAX, size))


def _clamp_image_width(width: int) -> int:
    return max(
        CONVERSATION_IMAGE_WIDTH_MIN,
        min(CONVERSATION_IMAGE_WIDTH_MAX, width),
    )


class MessageInput(QTextEdit):
    submit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._send_shortcut = "Return"

    def set_send_shortcut(self, shortcut: str) -> None:
        self._send_shortcut = shortcut or "Return"

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event_matches_shortcut(event, self._send_shortcut):
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _SafeTextBrowser(QTextBrowser):
    def loadResource(self, resource_type, url):  # type: ignore[override]
        if url.scheme().lower() in ("http", "https"):
            return None
        return super().loadResource(resource_type, url)


class ConversationOverlay(QWidget):
    send_requested = Signal(str)
    screenshot_requested = Signal()
    model_changed = Signal(str)

    def __init__(
        self,
        opacity: float = 0.72,
        font_size: int = CONVERSATION_FONT_SIZE_DEFAULT,
        image_width: int = CONVERSATION_IMAGE_WIDTH_DEFAULT,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._opacity = min(0.9, max(0.5, opacity))
        self._font_size = _clamp_font_size(font_size)
        self._image_width = _clamp_image_width(image_width)
        self._messages: list[ChatMessage] = []
        self._busy = False
        self._hotkey_label = "F1"
        self._saved_scroll = 0
        self._new_since_hide = False
        self._previews: list[QDialog] = []
        self._dirty = False
        self._exit_shortcut_obj: QShortcut | None = None
        self._stream_timer = QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.setInterval(50)
        self._stream_timer.timeout.connect(self._flush_stream)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(56, 36, 56, 32)
        outer.setSpacing(12)

        header = QHBoxLayout()
        self._title = QLabel("会话")
        self._title.setStyleSheet(
            "color: #EAF1FF; font: 600 15pt 'Microsoft YaHei UI'; background: transparent;"
        )
        self._meta = QLabel("Codex CLI")
        self._meta.setStyleSheet(
            "color: #9FB3D1; font: 9pt 'Microsoft YaHei UI'; background: transparent;"
        )
        self._hint = QLabel("F1 隐藏 · 滚轮/PageUp/PageDown 查看历史")
        self._hint.setStyleSheet(
            "color: #9FB3D1; font: 9pt 'Microsoft YaHei UI'; background: transparent;"
        )
        header.addWidget(self._title)
        header.addWidget(self._meta)
        model_label = QLabel("模型")
        model_label.setStyleSheet(
            "color: #9FB3D1; font: 9pt 'Microsoft YaHei UI'; background: transparent;"
        )
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._model_combo.setMinimumWidth(160)
        self._model_combo.setMaximumWidth(240)
        self._model_combo.setStyleSheet(
            "QComboBox { color: #E8EEF8; background: rgba(20, 24, 32, 0.9);"
            "  border: 1px solid rgba(76, 154, 255, 0.45); border-radius: 5px;"
            "  padding: 3px 6px; font: 9pt 'Microsoft YaHei UI'; }"
            "QComboBox QAbstractItemView { color: #E8EEF8; background: #2A3140;"
            "  selection-background-color: #2D6CDF; }"
        )
        self._model_combo.addItem("默认模型", "")
        self._model_combo.activated.connect(lambda _index: self._emit_model())
        editor = self._model_combo.lineEdit()
        if editor is not None:
            editor.editingFinished.connect(self._emit_model)
        header.addWidget(model_label)
        header.addWidget(self._model_combo)
        header.addStretch(1)
        header.addWidget(self._hint)
        outer.addLayout(header)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: rgba(120, 150, 190, 0.45);")
        outer.addWidget(divider)

        self._browser = _SafeTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_anchor_clicked)
        self._browser.setFrameShape(QFrame.Shape.NoFrame)
        self._browser.setReadOnly(True)
        self._browser.viewport().setAutoFillBackground(False)
        self._browser.document().setDocumentMargin(0)
        self._browser.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }"
            "QTextBrowser viewport { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }"
            "QScrollBar::handle:vertical { background: rgba(160, 180, 210, 0.5);"
            "  border-radius: 5px; min-height: 30px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        outer.addWidget(self._browser, 1)

        input_frame = QFrame()
        self._input_frame = input_frame
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 8, 10, 8)
        input_layout.setSpacing(6)

        self._input = MessageInput()
        self._input.setPlaceholderText("输入问题；Enter 发送，Shift+Enter 换行；/ 查看会话命令")
        self._input.submit_requested.connect(self._submit)
        self._input.installEventFilter(self)
        input_layout.addWidget(self._input)

        actions = QHBoxLayout()
        command_hint = QLabel("Enter 发送 · Shift+Enter 换行 · /new /resume /rename")
        actions.addWidget(command_hint)
        actions.addStretch(1)
        self._shot_button = QPushButton("截图提问")
        self._shot_button.setObjectName("ghost")
        self._shot_button.clicked.connect(self._request_screenshot)
        self._send_button = QPushButton("发送")
        self._send_button.clicked.connect(self._submit)
        actions.addWidget(self._shot_button)
        actions.addWidget(self._send_button)
        input_layout.addLayout(actions)
        outer.addWidget(input_frame)
        self._apply_input_font(self._font_size)

        page_up = QShortcut(QKeySequence("PageUp"), self)
        page_up.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        page_up.activated.connect(self._page_up)
        page_down = QShortcut(QKeySequence("PageDown"), self)
        page_down.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        page_down.activated.connect(self._page_down)

        self.set_shortcuts("Return", "Esc")

    def set_shortcuts(self, send_shortcut: str, exit_shortcut: str) -> None:
        self._input.set_send_shortcut(send_shortcut or "Return")
        if self._exit_shortcut_obj is not None:
            self._exit_shortcut_obj.setEnabled(False)
            self._exit_shortcut_obj.deleteLater()
        exit_shortcut_obj = QShortcut(
            QKeySequence(exit_shortcut or "Esc"), self
        )
        exit_shortcut_obj.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        exit_shortcut_obj.activated.connect(self._blur_input)
        self._exit_shortcut_obj = exit_shortcut_obj

    def set_hotkey_label(self, spec: str) -> None:
        self._hotkey_label = spec
        self._hint.setText(
            f"{spec} 隐藏 · 按住 {spec} 截图 · 滚轮/PageUp 查看历史"
        )

    def set_font_size(self, size: int) -> None:
        clamped = _clamp_font_size(size)
        if clamped == self._font_size:
            return
        self._font_size = clamped
        self._apply_input_font(clamped)
        self._rerender_preserving_scroll()

    def set_image_width(self, width: int) -> None:
        clamped = _clamp_image_width(width)
        if clamped == self._image_width:
            return
        self._image_width = clamped
        self._rerender_preserving_scroll()

    def _rerender_preserving_scroll(self) -> None:
        position = self._browser.verticalScrollBar().value()
        self._render()
        bar = self._browser.verticalScrollBar()
        bar.setValue(min(position, bar.maximum()))

    def _apply_input_font(self, size: int) -> None:
        self._input_frame.setStyleSheet(
            _INPUT_FRAME_STYLE.replace("{font_size}", str(size))
        )
        self._input.setFixedHeight(max(68, round(size * 4)))

    def set_session(self, title: str, session_id: str | None, backend: str = "Codex CLI") -> None:
        self._title.setText(f"会话：{title}")
        suffix = session_id[:8] if session_id else "新会话"
        self._meta.setText(f"{backend} · {suffix}")

    def set_models(self, models: list[ModelInfo], current: str = "") -> None:
        self._model_combo.blockSignals(True)
        try:
            self._model_combo.clear()
            self._model_combo.addItem("默认模型", "")
            for model in models:
                self._model_combo.addItem(model.display_name, model.slug)
            if current:
                index = self._model_combo.findData(current)
                if index < 0:
                    self._model_combo.addItem(current, current)
                    index = self._model_combo.count() - 1
                self._model_combo.setCurrentIndex(index)
            else:
                self._model_combo.setCurrentIndex(0)
        finally:
            self._model_combo.blockSignals(False)

    def set_current_model(self, slug: str) -> None:
        self._model_combo.blockSignals(True)
        try:
            index = self._model_combo.findData(slug)
            if index < 0:
                self._model_combo.addItem(slug or "默认模型", slug)
                index = self._model_combo.count() - 1
            self._model_combo.setCurrentIndex(index)
        finally:
            self._model_combo.blockSignals(False)

    def _emit_model(self) -> None:
        if self._busy:
            return
        text = self._model_combo.currentText().strip()
        index = self._model_combo.currentIndex()
        data = self._model_combo.currentData()
        if index >= 0 and self._model_combo.itemText(index) == text:
            slug = str(data) if data is not None else text
        else:
            slug = text
        self.model_changed.emit(slug)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._send_button.setEnabled(not busy)
        self._shot_button.setEnabled(not busy)
        self._model_combo.setEnabled(not busy)

    def is_busy(self) -> bool:
        return self._busy

    def set_messages(self, messages: list[ChatMessage], scroll_to_latest: bool = False) -> None:
        self._messages = list(messages)
        self._render()
        if scroll_to_latest:
            self._scroll_to_latest_answer()
        else:
            self._restore_scroll()

    def append_message(self, message: ChatMessage, scroll_to_latest: bool = True) -> None:
        self._messages.append(message)
        self._render()
        if self.isVisible():
            if scroll_to_latest:
                self._scroll_to_latest_answer()
        else:
            self._new_since_hide = True

    def update_last_answer(self, text: str, final: bool = False) -> None:
        if not self._messages or self._messages[-1].role != "assistant":
            return
        self._messages[-1] = ChatMessage(role="assistant", text=text)
        if final:
            self._stream_timer.stop()
            self._render()
            if self.isVisible():
                self._scroll_to_latest_answer()
            return
        if self.isVisible():
            if not self._stream_timer.isActive():
                self._stream_timer.start()
        else:
            self._dirty = True
            self._new_since_hide = True

    def _flush_stream(self) -> None:
        if not self._dirty:
            return
        self._render()
        if self.isVisible():
            self._scroll_to_latest_answer()

    def clear_messages(self) -> None:
        self._messages.clear()
        self._render()
        self._saved_scroll = 0
        self._new_since_hide = False

    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    def input_text(self) -> str:
        return self._input.toPlainText()

    def clear_input(self) -> None:
        self._input.clear()

    def show_on_cursor_screen(self, scroll_to_newest: bool = False) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        if self._dirty:
            self._render()
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus()
        if scroll_to_newest or self._new_since_hide:
            QTimer.singleShot(0, self._scroll_to_latest_answer)
            self._new_since_hide = False
        else:
            QTimer.singleShot(0, self._restore_scroll)

    def hide_view(self) -> None:
        self._saved_scroll = self._browser.verticalScrollBar().value()
        self.hide()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(10, 14, 22, int(255 * self._opacity)))
        painter.end()

    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj is self._input and event.type() == QEvent.Type.Wheel:
            QApplication.sendEvent(self._browser, event)
            return True
        return super().eventFilter(obj, event)

    def _submit(self) -> None:
        text = self._input.toPlainText()
        if text.strip():
            self.send_requested.emit(text)

    def _blur_input(self) -> None:
        if self._input.hasFocus():
            self._input.clearFocus()
        self._browser.setFocus()

    def _request_screenshot(self) -> None:
        if not self._busy:
            self.screenshot_requested.emit()

    def _render(self) -> None:
        role_size = self._font_size + 2
        hint_size = max(9, self._font_size - 3)
        parts = [
            (
                "<html><body style=\"color:#F2F6FC; font-family:'Microsoft YaHei UI';"
                f" font-size:{self._font_size}pt; margin:0;\">"
            )
        ]
        for index, message in enumerate(self._messages):
            parts.append(f'<a name="msg-{index}"></a>')
            attachment_html = self._attachments_html(message)
            if message.role == "assistant":
                body = _markdown_fragment_html(message.text)
                role = "Agent"
                role_color = "#79B8FF"
            elif message.role == "user":
                body = (
                    '<div style="white-space:pre-wrap;">'
                    + html.escape(message.text).replace("\n", "<br>")
                    + "</div>"
                )
                role = "你"
                role_color = "#7EE787"
            else:
                color = "#FF7B72" if message.is_error else "#B9C7DB"
                body = (
                    f'<div style="color:{color}; white-space:pre-wrap;">'
                    + html.escape(message.text).replace("\n", "<br>")
                    + "</div>"
                )
                role = "系统"
                role_color = color
            parts.append(
                '<div style="margin: 0 0 18px 0;">'
                f'<div style="color:{role_color}; font-size:{role_size}pt;'
                ' margin-bottom:4px;">'
                f"{role}</div>"
                f'<div style="color:#F2F6FC;">{attachment_html}{body}</div>'
                "</div>"
            )
        if not self._messages:
            parts.append(
                f'<div style="color:#9FB3D1; font-size:{hint_size}pt;">'
                "还没有消息。可以在下方输入问题，或点击“截图提问”。"
                "</div>"
            )
        parts.append("</body></html>")
        self._browser.setHtml("".join(parts))
        self._dirty = False

    def _attachments_html(self, message: ChatMessage) -> str:
        if not message.attachments:
            return ""
        parts: list[str] = []
        for attachment in message.attachments:
            path = Path(attachment.path)
            if not path.exists():
                parts.append(
                    '<div style="color:#FF7B72; font-size:9pt; margin:4px 0;">'
                    "图片不可用</div>"
                )
                continue
            url = QUrl.fromLocalFile(str(path)).toString()
            parts.append(
                '<div style="margin:4px 0 8px 0;">'
                f'<a href="{url}"><img src="{url}" width="{self._image_width}" /></a>'
                "</div>"
            )
        return "".join(parts)

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.isLocalFile():
            self._preview_image(url.toLocalFile())

    def _preview_image(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        max_width = 1100
        max_height = 800
        if screen is not None:
            geometry = screen.availableGeometry()
            max_width = max(320, geometry.width() - 120)
            max_height = max(240, geometry.height() - 120)
        scaled = pixmap.scaled(
            max_width,
            max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("图片预览")
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel()
        label.setPixmap(scaled)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        self._previews.append(dialog)

        def _forget() -> None:
            if dialog in self._previews:
                self._previews.remove(dialog)

        dialog.destroyed.connect(_forget)
        dialog.show()

    def _latest_answer_index(self) -> int:
        for index in range(len(self._messages) - 1, -1, -1):
            if self._messages[index].role == "assistant":
                return index
        return max(0, len(self._messages) - 1)

    def _scroll_to_latest_answer(self) -> None:
        if not self._messages:
            return
        self._browser.scrollToAnchor(f"msg-{self._latest_answer_index()}")

    def _restore_scroll(self) -> None:
        self._browser.verticalScrollBar().setValue(self._saved_scroll)

    def _page_up(self) -> None:
        bar = self._browser.verticalScrollBar()
        bar.setValue(bar.value() - bar.pageStep())

    def _page_down(self) -> None:
        bar = self._browser.verticalScrollBar()
        bar.setValue(bar.value() + bar.pageStep())


def _markdown_fragment_html(text: str) -> str:
    fragment = QTextDocumentFragment.fromMarkdown(text).toHtml()
    match = re.search(r"<body[^>]*>(.*)</body>", fragment, re.IGNORECASE | re.DOTALL)
    body = match.group(1) if match else fragment
    return body.replace("<!--StartFragment-->", "").replace("<!--EndFragment-->", "")
