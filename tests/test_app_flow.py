from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import QEventLoop, QPoint, QRect, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest

import screen_to_agent.app as app_module
from screen_to_agent.application.interaction_state import InteractionState
from screen_to_agent.config import APISettings, AppConfig
from screen_to_agent.domain.models import TurnResult


class _FakeScreen:
    def geometry(self) -> QRect:
        return QRect(0, 0, 800, 600)


class _FakeWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    canceled = Signal()
    stream_text = Signal(str)
    _counter = 0

    def __init__(
        self,
        _image_path,
        prompt,
        _settings,
        _store,
        session_id,
        start_new,
        _resume_last,
        model="",
        parent=None,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._prompt = prompt
        self._start_new = start_new
        self._session_id = session_id
        type(self)._counter += 1
        self._new_id = f"session-{type(self)._counter}"

    def run(self) -> None:
        session_id = self._new_id if self._start_new or not self._session_id else self._session_id
        self.stream_text.emit("流式")
        self.succeeded.emit(
            TurnResult(
                answer=f"回答：{self._prompt}",
                session_id=session_id,
                session_title="测试会话",
                started_new_session=self._start_new,
            )
        )

    def cancel(self) -> None:
        return


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _write_old_session(
    root: Path,
    user_text: str = "旧的会话问题",
    answer_text: str = "旧的会话回答",
) -> str:
    session_id = str(uuid.uuid4())
    path = root / "2026" / "11" / "14" / f"rollout-2026-11-14T09-00-00-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {
            "type": "session_meta",
            "payload": {
                "session_id": session_id,
                "timestamp": "2026-11-14T09:00:00Z",
                "cwd": "D:\\Work\\Demo",
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "UserMessage",
                    "content": [{"type": "text", "text": user_text}],
                },
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "AgentMessage",
                    "content": [{"type": "Text", "text": answer_text}],
                },
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )
    return session_id


def test_conversation_flow_without_generation_prompt(qapp, monkeypatch) -> None:
    pixmap = QPixmap(800, 600)
    pixmap.fill(QColor("white"))
    monkeypatch.setattr(app_module, "screen_under_cursor", lambda: _FakeScreen())
    monkeypatch.setattr(app_module, "capture_screen", lambda _screen: pixmap)
    monkeypatch.setattr(app_module, "CodexWorker", _FakeWorker)

    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setenv("SCREEN_TO_AGENT_CODEX_SESSIONS", temp_dir)
        monkeypatch.setenv(
            "SCREEN_TO_AGENT_ATTACHMENTS", str(Path(temp_dir) / "attachments")
        )
        controller = app_module.ScreenToAgentApp(qapp, AppConfig())
        try:
            notifications: list[str] = []
            controller._tray.showMessage = (
                lambda title, _body, *_args: notifications.append(title)
            )
            assert not controller._has_conversation

            controller._start_capture()
            _wait(150)
            overlay = controller._capture_overlay
            assert overlay is not None
            assert controller._state.state is InteractionState.CAPTURING

            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
            QTest.mouseMove(overlay, QPoint(500, 400))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(500, 400))
            qapp.processEvents()
            overlay._editor.setPlainText("这个错误怎么修？")
            overlay._send()
            _wait(200)

            assert controller._state.state is InteractionState.IDLE
            assert controller._has_conversation
            assert not controller._conversation.isVisible()
            assert [message.role for message in controller._messages] == ["user", "assistant"]
            assert "回答完成" in notifications

            controller._on_hotkey_tap()
            qapp.processEvents()
            assert controller._conversation.isVisible()
            assert "这个错误怎么修" in controller._conversation._browser.toPlainText()

            controller._on_hotkey_tap()
            qapp.processEvents()
            assert not controller._conversation.isVisible()

            controller._on_hotkey_tap()
            qapp.processEvents()
            notifications.clear()
            controller._on_text_requested("继续问")
            _wait(200)
            assert controller._conversation.isVisible()
            assert controller._messages[-1].text == "回答：继续问"
            assert "回答完成" not in notifications

            controller._handle_command("/new")
            assert controller._session is None
            assert controller._start_new_next
            controller._on_text_requested("新会话问题")
            _wait(200)
            assert controller._session is not None
            assert not controller._start_new_next
            assert controller._messages[-1].text == "回答：新会话问题"
        finally:
            controller.shutdown()
            qapp.processEvents()


def test_default_old_session_opens_conversation(qapp, monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session_id = _write_old_session(Path(temp_dir))
        monkeypatch.setenv("SCREEN_TO_AGENT_CODEX_SESSIONS", temp_dir)
        controller = app_module.ScreenToAgentApp(qapp, AppConfig())
        try:
            assert controller._has_conversation
            assert controller._session is not None
            assert controller._session.id == session_id
            assert not controller._conversation.isVisible()

            controller._on_hotkey_tap()
            qapp.processEvents()

            assert controller._conversation.isVisible()
            assert [message.role for message in controller._messages] == ["user", "assistant"]
            assert "旧的会话问题" in controller._conversation._browser.toPlainText()

            controller._on_hotkey_tap()
            qapp.processEvents()
            assert not controller._conversation.isVisible()
        finally:
            controller.shutdown()
            qapp.processEvents()


def test_tap_opens_conversation_and_hold_starts_capture(qapp, monkeypatch) -> None:
    pixmap = QPixmap(800, 600)
    pixmap.fill(QColor("white"))
    monkeypatch.setattr(app_module, "screen_under_cursor", lambda: _FakeScreen())
    monkeypatch.setattr(app_module, "capture_screen", lambda _screen: pixmap)

    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setenv("SCREEN_TO_AGENT_CODEX_SESSIONS", temp_dir)
        controller = app_module.ScreenToAgentApp(qapp, AppConfig())
        try:
            controller._on_hotkey_down()
            controller._on_hotkey_up()
            qapp.processEvents()
            assert controller._has_conversation
            assert controller._conversation.isVisible()
            assert controller._messages == []

            controller._on_hotkey_down()
            controller._on_hotkey_up()
            qapp.processEvents()
            assert not controller._conversation.isVisible()

            controller._on_hotkey_down()
            _wait(300)
            assert controller._hold_triggered
            assert controller._state.state is InteractionState.CAPTURING
            controller._on_hotkey_up()
            _wait(150)
            assert controller._capture_overlay is not None
            assert not controller._conversation.isVisible()

            controller._capture_overlay._cancel()
            qapp.processEvents()
            assert controller._state.state is InteractionState.IDLE
        finally:
            controller.shutdown()
            qapp.processEvents()


def test_hotkey_exit_preserves_capture_draft(qapp, monkeypatch) -> None:
    pixmap = QPixmap(800, 600)
    pixmap.fill(QColor("white"))
    monkeypatch.setattr(app_module, "screen_under_cursor", lambda: _FakeScreen())
    monkeypatch.setattr(app_module, "capture_screen", lambda _screen: pixmap)

    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setenv("SCREEN_TO_AGENT_CODEX_SESSIONS", temp_dir)
        controller = app_module.ScreenToAgentApp(qapp, AppConfig())
        try:
            controller._start_capture()
            _wait(150)
            overlay = controller._capture_overlay
            assert overlay is not None
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
            QTest.mouseMove(overlay, QPoint(500, 400))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(500, 400))
            qapp.processEvents()
            overlay._editor.setPlainText("保留的问题")

            controller._on_hotkey_down()
            controller._on_hotkey_up()
            qapp.processEvents()

            assert controller._state.state is InteractionState.IDLE
            assert controller._capture_overlay is None
            assert controller._capture_draft == "保留的问题"
            assert not controller._conversation.isVisible()

            controller._start_capture()
            _wait(150)
            overlay = controller._capture_overlay
            assert overlay is not None
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
            QTest.mouseMove(overlay, QPoint(500, 400))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(500, 400))
            qapp.processEvents()

            assert overlay._editor is not None
            assert overlay._editor.toPlainText() == "保留的问题"
            overlay._cancel()
        finally:
            controller.shutdown()
            qapp.processEvents()


def test_api_mode_opens_empty_conversation(qapp) -> None:
    config = AppConfig(
        backend="openai-compatible",
        api=APISettings(
            base_url="http://127.0.0.1:9/v1",
            model="api-model",
            models=("api-model", "api-model-2"),
        ),
    )
    controller = app_module.ScreenToAgentApp(qapp, config)
    try:
        assert controller._is_api
        assert controller._session is None
        assert not controller._has_conversation

        controller._on_hotkey_down()
        controller._on_hotkey_up()
        qapp.processEvents()

        assert controller._conversation.isVisible()
        assert controller._messages == []

        controller._handle_command("/resume")
        assert "API 为单轮模式" in controller._messages[-1].text
    finally:
        controller.shutdown()
        qapp.processEvents()


def test_resume_and_rename_commands(qapp, monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        first_id = _write_old_session(root, "第一个会话", "第一回答")
        second_id = _write_old_session(root, "第二个会话", "第二回答")
        monkeypatch.setenv("SCREEN_TO_AGENT_CODEX_SESSIONS", temp_dir)
        controller = app_module.ScreenToAgentApp(qapp, AppConfig())
        try:
            assert controller._session is not None
            assert controller._session.id in (first_id, second_id)

            controller._handle_command(f"/resume {first_id}")
            assert controller._session is not None
            assert controller._session.id == first_id
            assert controller._messages[0].text == "第一个会话"
            assert "已切换" in controller._messages[-1].text

            controller._handle_command("/rename 新名字")
            assert "不支持" in controller._messages[-1].text
            assert controller._session.id == first_id
        finally:
            controller.shutdown()
            qapp.processEvents()
