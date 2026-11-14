from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QTextCursor
from PySide6.QtTest import QTest

from screen_to_agent.application.prompt_builder import DEFAULT_QUESTION
from screen_to_agent.domain.models import AttachmentRef, ChatMessage, ModelInfo
from screen_to_agent.presentation.capture_overlay import CaptureOverlay
from screen_to_agent.presentation.conversation_overlay import ConversationOverlay


def _make_overlay(qapp, draft: str = "") -> CaptureOverlay:
    pixmap = QPixmap(800, 600)
    pixmap.fill(QColor("white"))
    overlay = CaptureOverlay(pixmap, QRect(0, 0, 800, 600), initial_draft=draft)
    overlay.start()
    qapp.processEvents()
    return overlay


def _select_region(overlay: CaptureOverlay, qapp) -> None:
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    QTest.mouseMove(overlay, QPoint(500, 400))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(500, 400))
    qapp.processEvents()


def _non_white_pixels(png_bytes: bytes) -> int:
    image = QImage.fromData(png_bytes)
    assert not image.isNull()
    count = 0
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            if QColor(image.pixel(x, y)) != QColor("white"):
                count += 1
    return count


def test_send_burns_annotation_and_emits_capture(qapp) -> None:
    overlay = _make_overlay(qapp)
    _select_region(overlay, qapp)

    assert overlay._phase == "annotating"
    assert overlay._editor is not None
    overlay._editor.setPlainText("这个错误怎么修？")

    received: list[tuple[str, object]] = []
    overlay.submitted.connect(lambda question, capture: received.append((question, capture)))
    overlay._send()
    qapp.processEvents()

    assert len(received) == 1
    question, capture = received[0]
    assert question == "这个错误怎么修？"
    assert capture.width == 401
    assert capture.height == 301
    assert capture.png_bytes.startswith(b"\x89PNG")
    assert _non_white_pixels(capture.png_bytes) > 0


def test_empty_annotation_uses_default_question(qapp) -> None:
    overlay = _make_overlay(qapp)
    _select_region(overlay, qapp)

    received: list[tuple[str, object]] = []
    overlay.submitted.connect(lambda question, capture: received.append((question, capture)))
    overlay._send()
    qapp.processEvents()

    assert received[0][0] == DEFAULT_QUESTION


def test_draft_is_restored_after_reselect(qapp) -> None:
    overlay = _make_overlay(qapp, draft="保留的问题")
    _select_region(overlay, qapp)

    assert overlay._editor is not None
    assert overlay._editor.toPlainText() == "保留的问题"

    overlay._reset_selection()
    _select_region(overlay, qapp)

    assert overlay._editor is not None
    assert overlay._editor.toPlainText() == "保留的问题"


def test_ctrl_enter_sends_question(qapp) -> None:
    overlay = _make_overlay(qapp, draft="用快捷键发送")
    _select_region(overlay, qapp)

    received: list[str] = []
    overlay.submitted.connect(lambda question, _capture: received.append(question))
    assert overlay._editor is not None
    overlay._editor.setFocus()
    QTest.keyClick(
        overlay._editor,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ControlModifier,
    )
    qapp.processEvents()

    assert received == ["用快捷键发送"]


def test_custom_capture_shortcuts(qapp) -> None:
    pixmap = QPixmap(800, 600)
    pixmap.fill(QColor("white"))
    overlay = CaptureOverlay(
        pixmap,
        QRect(0, 0, 800, 600),
        send_shortcut="Alt+S",
        exit_shortcut="Alt+X",
    )
    overlay.start()
    qapp.processEvents()
    _select_region(overlay, qapp)

    received: list[str] = []
    overlay.submitted.connect(lambda question, _capture: received.append(question))
    assert overlay._editor is not None
    overlay._editor.setPlainText("自定义发送键")
    overlay._editor.setFocus()
    QTest.keyClick(overlay._editor, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    qapp.processEvents()

    assert received == ["自定义发送键"]

    overlay2 = CaptureOverlay(
        pixmap,
        QRect(0, 0, 800, 600),
        send_shortcut="Alt+S",
        exit_shortcut="Alt+X",
    )
    overlay2.start()
    qapp.processEvents()
    _select_region(overlay2, qapp)
    cancelled: list[bool] = []
    drafts: list[str] = []
    overlay2.canceled.connect(lambda: cancelled.append(True))
    overlay2.canceled.connect(lambda: drafts.append(overlay2.draft_text()))
    assert overlay2._editor is not None
    overlay2._editor.setPlainText("退出保留")
    overlay2._editor.setFocus()
    QTest.keyClick(overlay2._editor, Qt.Key.Key_X, Qt.KeyboardModifier.AltModifier)
    qapp.processEvents()

    assert cancelled == [True]
    assert drafts == ["退出保留"]


def test_conversation_custom_shortcuts(qapp) -> None:
    overlay = ConversationOverlay()
    overlay.set_shortcuts("Ctrl+Return", "Alt+X")
    overlay.show_on_cursor_screen()
    qapp.processEvents()

    received: list[str] = []
    overlay.send_requested.connect(received.append)
    overlay._input.setPlainText("第一行")
    cursor = overlay._input.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    overlay._input.setTextCursor(cursor)
    overlay._input.setFocus()

    QTest.keyClick(overlay._input, Qt.Key.Key_Return)
    qapp.processEvents()
    assert received == []
    assert "\n" in overlay._input.toPlainText()

    QTest.keyClick(
        overlay._input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ControlModifier,
    )
    qapp.processEvents()
    assert received == ["第一行\n"]

    overlay._input.setFocus()
    QTest.keyClick(overlay._input, Qt.Key.Key_X, Qt.KeyboardModifier.AltModifier)
    qapp.processEvents()
    assert overlay.isVisible()
    assert not overlay._input.hasFocus()

    overlay.hide_view()
    overlay.deleteLater()
    qapp.processEvents()


def test_conversation_overlay_history_input_and_busy(qapp) -> None:
    overlay = ConversationOverlay()
    overlay.set_session("测试会话", "01a1d92f-f029-70a2-a041-073d00525fea")
    overlay.set_messages(
        [
            ChatMessage(role="user", text="历史问题"),
            ChatMessage(role="assistant", text="## 历史回答\n\n这是内容。"),
        ]
    )
    overlay.show_on_cursor_screen()
    qapp.processEvents()

    text = overlay._browser.toPlainText()
    assert "历史问题" in text
    assert "历史回答" in text

    overlay.set_busy(True)
    assert not overlay._send_button.isEnabled()
    assert not overlay._shot_button.isEnabled()
    overlay.set_busy(False)
    assert overlay._send_button.isEnabled()

    received: list[str] = []
    overlay.send_requested.connect(received.append)
    overlay._input.setPlainText("新问题")
    QTest.keyClick(overlay._input, Qt.Key.Key_Return)
    qapp.processEvents()
    assert received == ["新问题"]

    overlay.hide_view()
    overlay.deleteLater()
    qapp.processEvents()


def test_conversation_overlay_page_scrolling(qapp) -> None:
    overlay = ConversationOverlay()
    messages = [
        ChatMessage(role="assistant", text="\n\n".join(f"line {index}" for index in range(200)))
    ]
    overlay.set_messages(messages)
    overlay.show_on_cursor_screen()
    qapp.processEvents()

    bar = overlay._browser.verticalScrollBar()
    assert bar.maximum() > 0
    start = bar.value()
    overlay._page_down()
    qapp.processEvents()
    assert bar.value() > start

    overlay.hide_view()
    overlay.deleteLater()
    qapp.processEvents()


def test_conversation_overlay_model_selector(qapp) -> None:
    overlay = ConversationOverlay()
    models = [
        ModelInfo(slug="model-a", display_name="Model A"),
        ModelInfo(slug="model-b", display_name="Model B"),
    ]
    overlay.set_models(models, "model-b")

    assert overlay._model_combo.currentData() == "model-b"
    assert overlay._model_combo.currentText() == "Model B"
    overlay.deleteLater()


def test_conversation_font_size_applies_and_clamps(qapp) -> None:
    overlay = ConversationOverlay(font_size=13)
    overlay.set_messages([ChatMessage(role="assistant", text="回答内容")])
    qapp.processEvents()

    html = overlay._browser.toHtml()
    assert "13pt" in html
    assert "15pt" in html
    assert "13pt" in overlay._input_frame.styleSheet()

    overlay.set_font_size(18)
    qapp.processEvents()
    html = overlay._browser.toHtml()
    assert "18pt" in html
    assert "20pt" in html
    assert "18pt" in overlay._input_frame.styleSheet()
    assert overlay._input.height() >= 68

    overlay.set_font_size(99)
    assert overlay._font_size == 24
    overlay.set_font_size(1)
    assert overlay._font_size == 9

    overlay.deleteLater()
    qapp.processEvents()


def test_conversation_overlay_images_and_stream_update(qapp) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "shot.png"
        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor("red"))
        assert pixmap.save(str(image_path), "PNG")

        overlay = ConversationOverlay()
        overlay.set_messages(
            [
                ChatMessage(
                    role="user",
                    text="看图",
                    attachments=(AttachmentRef(path=str(image_path)),),
                ),
                ChatMessage(role="assistant", text="回答"),
            ]
        )
        qapp.processEvents()
        assert 'width="360"' in overlay._browser.toHtml()

        overlay.set_image_width(520)
        qapp.processEvents()
        assert 'width="520"' in overlay._browser.toHtml()
        overlay.set_image_width(9999)
        assert overlay._image_width == 1200
        overlay.set_image_width(1)
        assert overlay._image_width == 160

        overlay.update_last_answer("回答更新", final=True)
        qapp.processEvents()
        assert "回答更新" in overlay._browser.toPlainText()

        overlay.set_messages(
            [
                ChatMessage(
                    role="user",
                    text="缺失图片",
                    attachments=(AttachmentRef(path=str(Path(temp_dir) / "missing.png")),),
                )
            ]
        )
        qapp.processEvents()
        assert "图片不可用" in overlay._browser.toPlainText()
        overlay.deleteLater()
        qapp.processEvents()

