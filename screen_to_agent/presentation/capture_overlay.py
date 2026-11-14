from __future__ import annotations

from PySide6.QtCore import (
    QBuffer,
    QEvent,
    QIODevice,
    QPoint,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QWidget,
)

from screen_to_agent.application.prompt_builder import build_prompt
from screen_to_agent.domain.models import Capture
from screen_to_agent.presentation.shortcut_utils import event_matches_shortcut

_MIN_SELECTION_WIDTH = 120
_MIN_SELECTION_HEIGHT = 80


class CaptureOverlay(QWidget):
    submitted = Signal(str, object)
    canceled = Signal()
    selection_ready = Signal()

    def __init__(
        self,
        screenshot: QPixmap,
        screen_geometry: QRect,
        initial_draft: str = "",
        send_shortcut: str = "Ctrl+Return",
        exit_shortcut: str = "Esc",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._screenshot = screenshot
        self._draft_text = initial_draft
        self._send_sequence = QKeySequence(send_shortcut or "Ctrl+Return")
        self._exit_sequence = QKeySequence(exit_shortcut or "Esc")
        self._selection: QRect | None = None
        self._start: QPoint | None = None
        self._cursor = QPoint()
        self._dragging = False
        self._phase = "selecting"
        self._editor: QTextEdit | None = None
        self._toolbar: QWidget | None = None
        self._message = ""
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._clear_message)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setGeometry(screen_geometry)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        escape = QShortcut(QKeySequence(exit_shortcut or "Esc"), self)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self._cancel)

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._cursor = self.mapFromGlobal(QCursor.pos())
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self._screenshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        if self._selection is not None and self._selection.isValid():
            source = self._source_rect(self._selection)
            painter.drawPixmap(self._selection, self._screenshot, source)
            painter.setPen(QPen(QColor("#4C9AFF"), 2))
            painter.drawRect(self._selection.adjusted(0, 0, -1, -1))
            self._draw_size_label(painter, self._selection)

        if self._phase == "selecting":
            self._draw_crosshair(painter)

        if self._message:
            painter.setFont(QFont("Microsoft YaHei UI", 11))
            metrics = QFontMetricsF(painter.font())
            width = metrics.horizontalAdvance(self._message) + 32
            box = QRectF(
                (self.width() - width) / 2,
                self.height() - 90,
                width,
                36,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(20, 24, 32, 230))
            painter.drawRoundedRect(box, 8, 8)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._message)

        painter.end()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._phase != "selecting" or event.button() != Qt.MouseButton.LeftButton:
            return
        self._start = event.position().toPoint()
        self._selection = QRect(self._start, self._start)
        self._dragging = True
        self._cursor = self._start
        self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        self._cursor = event.position().toPoint()
        if self._dragging and self._start is not None:
            self._selection = QRect(self._start, self._cursor).normalized()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if not self._dragging or self._start is None:
            return
        self._dragging = False
        rect = QRect(self._start, event.position().toPoint()).normalized()
        self._start = None
        self._cursor = event.position().toPoint()

        if rect.width() < _MIN_SELECTION_WIDTH or rect.height() < _MIN_SELECTION_HEIGHT:
            self._selection = None
            self._phase = "selecting"
            self._show_message("选区太小，请重新框选")
            self.update()
            return

        self._selection = rect
        self._phase = "annotating"
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._create_annotation_ui(rect)
        self.selection_ready.emit()
        self.update()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def _create_annotation_ui(self, rect: QRect) -> None:
        self._editor = QTextEdit(self)
        self._editor.setPlaceholderText("在截图上输入你的问题…")
        self._editor.setStyleSheet(
            "QTextEdit {"
            "  background: rgba(255, 255, 255, 0.96);"
            "  color: #1b1b1b;"
            "  border: 2px solid #4C9AFF;"
            "  border-radius: 8px;"
            "  padding: 8px;"
            "  font: 12pt 'Microsoft YaHei UI';"
            "}"
        )
        editor_width = min(520, max(90, rect.width() - 24))
        editor_height = min(140, max(58, rect.height() - 24))
        self._editor.setGeometry(
            rect.x() + 12,
            rect.y() + 12,
            editor_width,
            editor_height,
        )
        self._editor.show()
        self._editor.installEventFilter(self)
        if self._draft_text:
            self._editor.setPlainText(self._draft_text)
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._editor.setTextCursor(cursor)
        self._editor.setFocus()

        toolbar_width = 360
        toolbar_height = 40
        toolbar_x = min(max(8, rect.x()), max(8, self.width() - toolbar_width - 8))
        toolbar_y = rect.bottom() + 8
        if toolbar_y + toolbar_height > self.height() - 8:
            toolbar_y = max(8, rect.y() - toolbar_height - 8)

        self._toolbar = QWidget(self)
        self._toolbar.setGeometry(toolbar_x, toolbar_y, toolbar_width, toolbar_height)
        self._toolbar.setStyleSheet(
            "QWidget { background: rgba(20, 24, 32, 0.94); border-radius: 8px; }"
            "QLabel { color: #DCE6F5; font: 10pt 'Microsoft YaHei UI'; }"
            "QPushButton { color: #FFFFFF; background: #2D6CDF; border: none;"
            "  border-radius: 5px; padding: 5px 10px; font: 9pt 'Microsoft YaHei UI'; }"
            "QPushButton:hover { background: #3D7CEF; }"
            "QPushButton#ghost { background: rgba(255, 255, 255, 0.12); }"
        )
        layout = QHBoxLayout(self._toolbar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        label = QLabel("文字问题")
        layout.addWidget(label)
        layout.addStretch(1)

        reselect = QPushButton("重新框选")
        reselect.setObjectName("ghost")
        reselect.clicked.connect(self._reset_selection)
        layout.addWidget(reselect)

        cancel = QPushButton("取消")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self._cancel)
        layout.addWidget(cancel)

        send = QPushButton("发送 (Ctrl+Enter)")
        send.clicked.connect(self._send)
        layout.addWidget(send)
        self._toolbar.show()

    def _reset_selection(self) -> None:
        if self._editor is not None:
            self._draft_text = self._editor.toPlainText()
        self._remove_annotation_ui()
        self._selection = None
        self._phase = "selecting"
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocus()
        self.update()

    def draft_text(self) -> str:
        if self._editor is not None:
            return self._editor.toPlainText()
        return self._draft_text

    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj is self._editor and event.type() == QEvent.Type.KeyPress:
            if event_matches_shortcut(
                event,
                self._send_sequence.toString(
                    QKeySequence.SequenceFormat.PortableText
                ),
            ):
                self._send()
                return True
            if event_matches_shortcut(
                event,
                self._exit_sequence.toString(
                    QKeySequence.SequenceFormat.PortableText
                ),
            ):
                self._cancel()
                return True
        return super().eventFilter(obj, event)

    def _send(self) -> None:
        if self._selection is None or self._editor is None:
            return
        question = build_prompt(self._editor.toPlainText())
        capture = self._build_capture()
        self._draft_text = ""
        self.submitted.emit(question, capture)
        self.close()

    def _cancel(self) -> None:
        self.canceled.emit()
        self.close()

    def _build_capture(self) -> Capture:
        assert self._selection is not None
        assert self._editor is not None

        source = self._source_rect(self._selection)
        crop = self._screenshot.copy(source)
        crop.setDevicePixelRatio(1.0)

        text = self._editor.toPlainText().strip()
        if text:
            self._burn_annotation(crop, text)

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        crop.save(buffer, "PNG")
        png_bytes = bytes(buffer.data())
        buffer.close()

        return Capture(
            png_bytes=png_bytes,
            width=crop.width(),
            height=crop.height(),
            origin_x=self.geometry().x() + self._selection.x(),
            origin_y=self.geometry().y() + self._selection.y(),
        )

    def _burn_annotation(self, crop: QPixmap, text: str) -> None:
        assert self._selection is not None
        assert self._editor is not None

        ratio_x = crop.width() / max(1, self._selection.width())
        ratio_y = crop.height() / max(1, self._selection.height())
        offset_x = (self._editor.x() - self._selection.x()) * ratio_x + 8 * ratio_x
        offset_y = (self._editor.y() - self._selection.y()) * ratio_y + 8 * ratio_y
        box_width = max(40.0, (self._editor.width() - 16) * ratio_x)

        font = QFont(self._editor.font())
        font.setPixelSize(max(14, int(self._editor.fontMetrics().height() * ratio_y)))
        metrics = QFontMetricsF(font)
        bounds = metrics.boundingRect(
            QRectF(0, 0, box_width, 100000),
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft,
            text,
        )

        painter = QPainter(crop)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QRectF(
            offset_x - 6,
            offset_y - 6,
            bounds.width() + 12,
            bounds.height() + 12,
        )
        painter.setPen(QPen(QColor("#4C9AFF"), 1))
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawRoundedRect(background, 5, 5)
        painter.setFont(font)
        painter.setPen(QColor("#A4001E"))
        painter.drawText(
            QRectF(offset_x, offset_y, box_width, bounds.height() + 4),
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        painter.end()

    def _source_rect(self, rect: QRect) -> QRect:
        scale_x = self._screenshot.width() / max(1, self.width())
        scale_y = self._screenshot.height() / max(1, self.height())
        return QRect(
            int(rect.x() * scale_x),
            int(rect.y() * scale_y),
            max(1, int(rect.width() * scale_x)),
            max(1, int(rect.height() * scale_y)),
        )

    def _draw_size_label(self, painter: QPainter, rect: QRect) -> None:
        label = f"{rect.width()} × {rect.height()}"
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        box = QRect(rect.left(), max(0, rect.top() - 24), 110, 22)
        painter.fillRect(box, QColor(20, 24, 32, 220))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_crosshair(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DashLine))
        painter.drawLine(0, self._cursor.y(), self.width(), self._cursor.y())
        painter.drawLine(self._cursor.x(), 0, self._cursor.x(), self.height())

    def _remove_annotation_ui(self) -> None:
        if self._editor is not None:
            self._editor.hide()
            self._editor.deleteLater()
            self._editor = None
        if self._toolbar is not None:
            self._toolbar.hide()
            self._toolbar.deleteLater()
            self._toolbar = None

    def _show_message(self, message: str) -> None:
        self._message = message
        self._message_timer.start(1600)

    def _clear_message(self) -> None:
        self._message = ""
        self.update()
