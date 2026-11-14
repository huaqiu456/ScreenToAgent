from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QSystemTrayIcon

from screen_to_agent import __version__
from screen_to_agent.application.interaction_state import (
    InteractionState,
    InteractionStateMachine,
)
from screen_to_agent.config import (
    CONVERSATION_FONT_SIZE_MAX,
    CONVERSATION_FONT_SIZE_MIN,
    CONVERSATION_IMAGE_WIDTH_MAX,
    CONVERSATION_IMAGE_WIDTH_MIN,
    AppConfig,
    InputShortcuts,
    app_data_dir,
    ensure_default_config,
    load_config,
    save_settings,
)
from screen_to_agent.domain.models import (
    Capture,
    ChatMessage,
    ModelInfo,
    SessionInfo,
    TurnResult,
)
from screen_to_agent.infrastructure.attachments import (
    AttachmentStore,
    default_storage_root,
    resolve_attachments_dir,
)
from screen_to_agent.infrastructure.codex_backend import CodexWorker
from screen_to_agent.infrastructure.codex_sessions import CodexSessionStore
from screen_to_agent.infrastructure.hotkey_win32 import HotkeyManager
from screen_to_agent.infrastructure.model_catalog import CodexModelCatalogWorker
from screen_to_agent.infrastructure.openai_backend import OpenAIWorker
from screen_to_agent.infrastructure.screen_capture import capture_screen, screen_under_cursor
from screen_to_agent.presentation.capture_overlay import CaptureOverlay
from screen_to_agent.presentation.conversation_overlay import ConversationOverlay
from screen_to_agent.presentation.session_picker import SessionPickerDialog
from screen_to_agent.presentation.settings_dialog import SettingsDialog
from screen_to_agent.presentation.shortcut_utils import validate_input_shortcuts

logger = logging.getLogger(__name__)

_HOLD_THRESHOLD_MS = 250


def make_app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2D6CDF"))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRoundedRect(16, 20, 32, 24, 5, 5)
    painter.setBrush(QColor("#2D6CDF"))
    painter.drawEllipse(24, 25, 14, 14)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(28, 29, 6, 6)
    painter.setPen(QPen(QColor("#FFFFFF"), 4))
    painter.drawLine(22, 18, 42, 18)
    painter.end()
    return QIcon(pixmap)


def setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "app.log", encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


class ScreenToAgentApp(QObject):
    def __init__(self, app: QApplication, config: AppConfig) -> None:
        super().__init__()
        self._app = app
        self._config = config
        self._state = InteractionStateMachine()
        self._store = CodexSessionStore()
        self._is_api = config.backend != "codex-cli"
        self._session = None if self._is_api else self._load_latest_session()
        self._start_new_next = (not self._is_api) and self._session is None
        self._use_last_next = False
        self._has_conversation = (not self._is_api) and self._session is not None
        self._messages: list[ChatMessage] = []
        self._history_loaded = self._is_api or self._session is None
        self._ever_shown = False
        self._last_visible_count = 0
        self._worker: CodexWorker | OpenAIWorker | None = None
        self._model_worker: CodexModelCatalogWorker | None = None
        self._models: list[ModelInfo] = []
        self._model = (
            config.codex.model
            if config.backend == "codex-cli"
            else config.api.model
        )
        self._shortcut_warning = ""
        self._storage_warning = ""
        self._shortcuts = config.input_shortcuts
        shortcuts_ok, shortcut_error = validate_input_shortcuts(
            self._shortcuts, config.hotkey
        )
        if not shortcuts_ok:
            self._shortcut_warning = shortcut_error
            self._shortcuts = InputShortcuts()
        self._attachments = self._make_attachment_store(config.storage_root)
        self._stream_text = ""
        self._stream_message_started = False
        self._capture_overlay: CaptureOverlay | None = None
        self._capture_draft = ""
        self._settings_open = False
        self._picker_open = False
        self._closed = False
        self._hotkey_down = False
        self._hotkey_press_accepted = False
        self._hold_triggered = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(_HOLD_THRESHOLD_MS)
        self._hold_timer.timeout.connect(self._on_hold_elapsed)

        self._conversation = ConversationOverlay(
            config.overlay_opacity,
            config.conversation_font_size,
            config.conversation_image_width,
        )
        self._conversation.set_hotkey_label(config.hotkey)
        self._set_conversation_session()
        self._conversation.set_models([], self._model)
        self._conversation.send_requested.connect(self._on_text_requested)
        self._conversation.screenshot_requested.connect(self._on_screenshot_from_conversation)
        self._conversation.model_changed.connect(self._on_model_changed)
        self._conversation.set_shortcuts(
            self._shortcuts.conversation_send,
            self._shortcuts.conversation_exit,
        )

        self._hotkey = HotkeyManager(config.hotkey, self)
        self._hotkey.pressed.connect(self._on_hotkey_down)
        self._hotkey.released.connect(self._on_hotkey_up)

        self._tray = QSystemTrayIcon(make_app_icon(), self)
        self._menu = self._build_menu()
        self._tray.setContextMenu(self._menu)
        self._tray.messageClicked.connect(self._on_message_clicked)
        self._update_tray_state()

    def start(self) -> None:
        self._tray.show()
        ok, note = self._hotkey.register()
        if ok:
            if note:
                logger.warning("Hotkey fallback active: %s", note)
                self._tray.showMessage(
                    f"{self._config.hotkey} 热键提示",
                    note,
                    QSystemTrayIcon.MessageIcon.Warning,
                    9000,
                )
            else:
                self._tray.showMessage(
                    "ScreenToAgent",
                    f"已启动：轻点 {self._config.hotkey} 开关会话，按住 {self._config.hotkey} 截图",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            logger.info("ScreenToAgent started with hotkey %s", self._config.hotkey)
        else:
            logger.error("Hotkey registration failed: %s", note)
            self._tray.showMessage(
                "ScreenToAgent",
                note,
                QSystemTrayIcon.MessageIcon.Warning,
                9000,
            )
        if self._config.backend != "codex-cli":
            if not self._config.api.base_url:
                self._tray.showMessage(
                    "ScreenToAgent",
                    "API 模式尚未配置 api.base_url，请编辑配置文件。",
                    QSystemTrayIcon.MessageIcon.Warning,
                    8000,
                )
        self._load_model_catalog()
        removed = self._attachments.prune(30)
        if removed:
            logger.info("Pruned %s expired attachments", removed)
        if self._storage_warning:
            self._tray.showMessage(
                "存储位置提示",
                self._storage_warning,
                QSystemTrayIcon.MessageIcon.Warning,
                9000,
            )
        if self._shortcut_warning:
            self._tray.showMessage(
                "输入快捷键提示",
                f"{self._shortcut_warning} 已使用默认快捷键。",
                QSystemTrayIcon.MessageIcon.Warning,
                9000,
            )

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        self._capture_action = menu.addAction("截屏提问")
        self._capture_action.triggered.connect(self._tray_capture)
        self._toggle_action = menu.addAction("打开会话")
        self._toggle_action.triggered.connect(self._tray_toggle_conversation)
        self._cancel_action = menu.addAction("取消当前回答")
        self._cancel_action.triggered.connect(self._cancel_generation)
        settings = menu.addAction("设置…")
        settings.triggered.connect(self._open_settings)
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._app.quit)
        return menu

    def _load_latest_session(self) -> SessionInfo | None:
        try:
            return self._store.latest_session()
        except OSError:
            logger.warning("Unable to read Codex sessions", exc_info=True)
            return None

    def _make_attachment_store(self, storage_root: str) -> AttachmentStore:
        try:
            return AttachmentStore(root=resolve_attachments_dir(storage_root))
        except (OSError, ValueError) as exc:
            self._storage_warning = (
                f"配置的存储位置不可用，已回退默认路径：{exc}"
            )
            logger.warning(self._storage_warning)
            try:
                return AttachmentStore(root=resolve_attachments_dir(""))
            except (OSError, ValueError):
                return AttachmentStore(root=default_storage_root() / "attachments")

    def _load_model_catalog(self) -> None:
        if self._config.backend != "codex-cli":
            models = [
                ModelInfo(slug=slug, display_name=slug)
                for slug in self._config.api.models
            ]
            self._models = models
            self._conversation.set_models(models, self._model)
            return
        worker = CodexModelCatalogWorker(self._config.codex.executable, self)
        worker.loaded.connect(self._on_models_loaded)
        worker.failed.connect(self._on_models_failed)
        worker.finished.connect(worker.deleteLater)
        self._model_worker = worker
        worker.start()

    def _on_models_loaded(self, models) -> None:
        self._models = list(models)
        self._conversation.set_models(self._models, self._model)
        logger.info("Model catalog loaded: %s models", len(self._models))

    def _on_models_failed(self, message: str) -> None:
        logger.warning("Model catalog unavailable: %s", message)
        self._models = []
        self._conversation.set_models([], self._model)

    def _on_model_changed(self, slug: str) -> None:
        if self._is_busy():
            return
        self._model = slug.strip()
        logger.info("Model changed to %s", self._model or "default")

    def _model_supports_image(self) -> bool:
        if not self._model:
            return True
        for model in self._models:
            if model.slug == self._model:
                return model.supports_image
        return True

    def _session_title(self) -> str:
        if self._is_api:
            return "API 单轮会话"
        if self._session is None:
            return "新会话"
        return self._session.title or f"会话 {self._session.id[:8]}"

    def _session_id(self) -> str | None:
        return self._session.id if self._session else None

    def _backend_label(self) -> str:
        return "API" if self._is_api else "Codex CLI"

    def _set_conversation_session(self) -> None:
        self._conversation.set_session(
            self._session_title(),
            self._session_id(),
            self._backend_label(),
        )

    def _is_busy(self) -> bool:
        return self._worker is not None or self._state.state is InteractionState.GENERATING

    def _update_tray_state(self) -> None:
        visible = self._conversation.isVisible()
        self._toggle_action.setText("隐藏会话" if visible else "打开会话")
        self._toggle_action.setEnabled(self._has_conversation)
        self._capture_action.setEnabled(
            not self._is_busy()
            and self._state.state
            not in (InteractionState.CAPTURING, InteractionState.ANNOTATING)
        )
        self._cancel_action.setEnabled(self._worker is not None)
        if visible:
            self._tray.setToolTip("ScreenToAgent · 会话已打开")
        elif self._has_conversation:
            self._tray.setToolTip(
                f"ScreenToAgent · 轻点 {self._config.hotkey} 开关会话 · 按住截图"
            )
        else:
            self._tray.setToolTip(
                f"ScreenToAgent · 轻点 {self._config.hotkey} 打开会话 · 按住截图"
            )

    def _on_hotkey_down(self) -> None:
        if self._settings_open or self._picker_open:
            return
        if self._state.state in (
            InteractionState.CAPTURING,
            InteractionState.ANNOTATING,
        ):
            self._hotkey_press_accepted = False
            self._hotkey_down = False
            self._hold_triggered = False
            self._hold_timer.stop()
            overlay = self._capture_overlay
            if overlay is not None:
                overlay._cancel()
            else:
                self._state.set_state(InteractionState.IDLE)
                self._update_tray_state()
            return
        self._hotkey_down = True
        self._hotkey_press_accepted = True
        self._hold_triggered = False
        self._hold_timer.start()

    def _on_hold_elapsed(self) -> None:
        if not self._hotkey_down:
            return
        if not self._state.can_start_capture() or self._is_busy():
            return
        self._hold_triggered = True
        self._start_capture()

    def _on_hotkey_up(self) -> None:
        self._hold_timer.stop()
        accepted = self._hotkey_press_accepted
        self._hotkey_press_accepted = False
        self._hotkey_down = False
        if not accepted:
            return
        if self._hold_triggered:
            self._hold_triggered = False
            return
        if self._settings_open or self._picker_open:
            return
        if self._state.state in (
            InteractionState.CAPTURING,
            InteractionState.ANNOTATING,
        ):
            return
        self._on_hotkey_tap()

    def _on_hotkey_tap(self) -> None:
        if not self._has_conversation:
            self._has_conversation = True
            if self._session is None:
                self._start_new_next = True
                self._history_loaded = True
            self._set_conversation_session()
        self._toggle_conversation()

    def _toggle_conversation(self) -> None:
        if self._conversation.isVisible():
            self._hide_conversation()
        else:
            self._show_conversation()

    def _show_conversation(self) -> None:
        if not self._has_conversation:
            return
        if not self._history_loaded:
            self._load_history()
        new_since = (not self._ever_shown) or len(self._messages) > self._last_visible_count
        if not self._ever_shown:
            self._conversation.set_messages(self._messages, scroll_to_latest=False)
        self._set_conversation_session()
        self._conversation.show_on_cursor_screen(scroll_to_newest=new_since)
        self._ever_shown = True
        self._last_visible_count = len(self._messages)
        self._update_tray_state()

    def _hide_conversation(self) -> None:
        self._last_visible_count = len(self._messages)
        self._conversation.hide_view()
        self._update_tray_state()

    def _load_history(self) -> None:
        if self._is_api:
            self._history_loaded = True
            return
        if self._session is None:
            self._messages = []
            self._history_loaded = True
            return
        try:
            self._messages = self._store.load_history(self._session.id)
        except (OSError, ValueError) as exc:
            logger.warning("Unable to load session history: %s", exc)
            self._messages = []
            self._add_system_message(f"无法从 CLI 读取历史：{exc}", is_error=True)
        self._history_loaded = True

    def _prepare_turn(self) -> None:
        if self._start_new_next:
            self._messages = []
            self._history_loaded = True
        elif self._session is not None and not self._history_loaded:
            self._load_history()
        else:
            self._history_loaded = True
        self._has_conversation = True

    def _on_text_requested(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        if stripped.startswith("/"):
            self._handle_command(stripped)
            return
        if self._is_busy() or self._state.state in (
            InteractionState.CAPTURING,
            InteractionState.ANNOTATING,
        ):
            return
        if self._send_question(stripped, None):
            self._conversation.clear_input()

    def _handle_command(self, text: str) -> None:
        self._conversation.clear_input()
        if self._is_busy():
            self._add_system_message("正在回答，暂时不能切换会话。", is_error=True)
            return
        command, _, argument = text.partition(" ")
        command = command.casefold()
        argument = argument.strip()
        if command == "/new":
            self._new_session()
        elif command == "/resume":
            if self._is_api:
                self._add_system_message(
                    "API 为单轮模式，不保留历史会话。", is_error=True
                )
            else:
                self._resume_session(argument)
        elif command == "/rename":
            if self._is_api:
                self._add_system_message(
                    "API 模式不支持会话重命名。", is_error=True
                )
            elif argument:
                self._add_system_message(
                    "当前 Codex CLI 版本不支持通过命令行重命名会话，"
                    "未在本地伪造改名。",
                    is_error=True,
                )
            else:
                self._add_system_message("用法：/rename <new-name>", is_error=True)
        elif command == "/help":
            self._add_help()
        else:
            self._add_help(prefix=f"未知命令：{command}")

    def _new_session(self) -> None:
        self._session = None
        self._start_new_next = True
        self._use_last_next = False
        self._has_conversation = True
        self._history_loaded = True
        self._messages = []
        self._conversation.clear_messages()
        self._conversation.set_session("新会话", None, self._backend_label())
        if self._is_api:
            self._add_system_message("已清空当前 API 单轮对话。")
        else:
            self._add_system_message(
                "已切换到新会话；下一条消息将创建新的 Codex CLI 会话。"
            )
        self._last_visible_count = len(self._messages)
        self._update_tray_state()

    def _resume_session(self, argument: str) -> None:
        if self._is_api:
            self._add_system_message(
                "API 为单轮模式，不保留历史会话。", is_error=True
            )
            return
        try:
            sessions = self._store.list_sessions(30)
        except OSError as exc:
            self._add_system_message(f"读取 CLI 会话失败：{exc}", is_error=True)
            return
        if not sessions:
            self._add_system_message("没有找到可恢复的 CLI 会话。", is_error=True)
            return

        if argument:
            session = self._store.find_session(argument)
            if session is None:
                self._add_system_message(f"未找到会话：{argument}", is_error=True)
                return
            self._switch_session(session)
            return

        self._picker_open = True
        try:
            dialog = SessionPickerDialog(sessions)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                session = dialog.selected_session()
                if session is not None:
                    self._switch_session(session)
        finally:
            self._picker_open = False

    def _switch_session(self, session: SessionInfo) -> None:
        error: str | None = None
        try:
            history = self._store.load_history(session.id)
        except (OSError, ValueError) as exc:
            history = []
            error = str(exc)
        self._session = session
        self._start_new_next = False
        self._use_last_next = False
        self._has_conversation = True
        self._history_loaded = True
        self._messages = history
        self._conversation.set_session(
            session.title, session.id, self._backend_label()
        )
        self._conversation.set_messages(self._messages, scroll_to_latest=True)
        if error:
            self._add_system_message(f"读取会话历史失败：{error}", is_error=True)
        self._add_system_message(f"已切换到会话：{session.title}")
        self._last_visible_count = len(self._messages)
        self._update_tray_state()

    def _add_help(self, prefix: str = "可用命令") -> None:
        self._add_system_message(
            f"{prefix}：/new 新建会话；/resume [id|name] 选择会话；"
            "/rename <name> 重命名（需 CLI 支持）；/help 帮助。"
        )

    def _add_system_message(self, text: str, is_error: bool = False) -> None:
        message = ChatMessage(role="system", text=text, is_error=is_error)
        self._messages.append(message)
        self._conversation.append_message(message, scroll_to_latest=True)

    def _send_question(self, question: str, png_bytes: bytes | None) -> bool:
        if self._is_busy() or self._state.state in (
            InteractionState.CAPTURING,
            InteractionState.ANNOTATING,
        ):
            return False
        if png_bytes is not None and not self._model_supports_image():
            self._add_system_message(
                "当前所选模型不支持图片输入，请更换模型或取消截图。",
                is_error=True,
            )
            return False

        attachment = None
        image_path: Path | None = None
        if png_bytes is not None:
            try:
                attachment = self._attachments.save_png(png_bytes)
                image_path = Path(attachment.path)
            except OSError as exc:
                self._add_system_message(f"保存截图失败：{exc}", is_error=True)
                return False

        if self._is_api:
            self._has_conversation = True
            self._history_loaded = True
        else:
            self._prepare_turn()
        user_message = ChatMessage(
            role="user",
            text=question,
            attachments=(attachment,) if attachment is not None else (),
        )
        self._messages.append(user_message)
        self._conversation.append_message(user_message, scroll_to_latest=True)
        self._set_conversation_session()

        start_new = self._start_new_next
        session_id = None if start_new else self._session_id()
        resume_last = (not start_new) and not session_id and self._use_last_next
        if not start_new and not session_id and not resume_last:
            start_new = True

        self._stream_text = ""
        self._stream_message_started = False
        self._state.set_state(InteractionState.GENERATING)
        self._conversation.set_busy(True)
        self._update_tray_state()

        if self._is_api:
            worker = OpenAIWorker(
                image_path,
                question,
                self._config.api,
                model=self._model,
                parent=self,
            )
        else:
            worker = CodexWorker(
                image_path,
                question,
                self._config.codex,
                self._store,
                session_id,
                start_new,
                resume_last,
                model=self._model,
                parent=self,
            )
        worker.stream_text.connect(self._on_stream_text)
        worker.succeeded.connect(self._on_generation_succeeded)
        worker.failed.connect(self._on_generation_failed)
        worker.canceled.connect(self._on_generation_canceled)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._update_tray_state()
        worker.start()
        return True

    def _start_capture(self) -> None:
        if self._is_busy() or not self._state.can_start_capture():
            return
        if self._conversation.isVisible():
            self._hide_conversation()
        self._state.set_state(InteractionState.CAPTURING)
        self._update_tray_state()
        QTimer.singleShot(80, self._grab_and_show)

    def _grab_and_show(self) -> None:
        if self._state.state is not InteractionState.CAPTURING:
            return
        try:
            screen = screen_under_cursor()
            screenshot = capture_screen(screen)
        except (RuntimeError, OSError) as exc:
            logger.exception("Screen capture failed")
            self._state.set_state(InteractionState.IDLE)
            self._tray.showMessage(
                "ScreenToAgent",
                f"截屏失败：{exc}",
                QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )
            return

        overlay = CaptureOverlay(
            screenshot,
            screen.geometry(),
            initial_draft=self._capture_draft,
            send_shortcut=self._shortcuts.screenshot_send,
            exit_shortcut=self._shortcuts.screenshot_exit,
        )
        overlay.submitted.connect(self._on_submitted)
        overlay.canceled.connect(self._on_capture_canceled)
        overlay.selection_ready.connect(self._on_selection_ready)
        overlay.destroyed.connect(lambda _=None, ov=overlay: self._on_capture_destroyed(ov))
        self._capture_overlay = overlay
        overlay.start()

    def _on_selection_ready(self) -> None:
        if self._state.state is InteractionState.CAPTURING:
            self._state.set_state(InteractionState.ANNOTATING)

    def _on_capture_canceled(self) -> None:
        overlay = self._capture_overlay
        if overlay is not None:
            self._capture_draft = overlay.draft_text()
            self._capture_overlay = None
        self._state.set_state(InteractionState.IDLE)
        self._update_tray_state()

    def _on_capture_destroyed(self, overlay) -> None:
        if self._capture_overlay is overlay:
            self._capture_overlay = None

    def _on_submitted(self, question: str, capture: Capture) -> None:
        self._state.set_state(InteractionState.IDLE)
        self._capture_draft = ""
        self._send_question(question, capture.png_bytes)

    def _on_screenshot_from_conversation(self) -> None:
        if self._is_busy():
            return
        self._hide_conversation()
        self._start_capture()

    def _on_stream_text(self, text: str) -> None:
        if self.sender() is not self._worker or not text:
            return
        self._stream_text += text
        if not self._stream_message_started:
            message = ChatMessage(role="assistant", text=self._stream_text)
            self._messages.append(message)
            self._conversation.append_message(message, scroll_to_latest=True)
            self._stream_message_started = True
        else:
            self._conversation.update_last_answer(self._stream_text)

    def _on_generation_succeeded(self, result: TurnResult) -> None:
        if self.sender() is not self._worker:
            return
        self._state.set_state(InteractionState.IDLE)
        self._conversation.set_busy(False)

        if result.session_id:
            self._session = SessionInfo(
                id=result.session_id,
                title=result.session_title or self._pending_title(),
            )
            self._start_new_next = False
            self._use_last_next = False
            self._history_loaded = True
            self._has_conversation = True
        elif result.started_new_session:
            self._session = None
            self._start_new_next = False
            self._use_last_next = True
            self._history_loaded = True
            self._has_conversation = True

        self._conversation.set_session(
            self._session_title(), self._session_id(), self._backend_label()
        )
        if self._stream_message_started and self._messages:
            self._messages[-1] = ChatMessage(role="assistant", text=result.answer)
            self._conversation.update_last_answer(result.answer, final=True)
        else:
            self._messages.append(ChatMessage(role="assistant", text=result.answer))
            self._conversation.append_message(
                ChatMessage(role="assistant", text=result.answer),
                scroll_to_latest=True,
            )
        self._stream_text = ""
        self._stream_message_started = False
        if self._conversation.isVisible():
            self._last_visible_count = len(self._messages)
            self._tray.setToolTip("ScreenToAgent · 回答已追加到会话")
        else:
            self._tray.showMessage(
                "回答完成",
                f"按 {self._config.hotkey} 查看会话",
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )
            self._tray.setToolTip(
                f"ScreenToAgent · 按 {self._config.hotkey} 查看会话"
            )
        self._update_tray_state()
        logger.info("Agent answer ready")

    def _pending_title(self) -> str:
        for message in reversed(self._messages):
            if message.role == "user":
                normalized = " ".join(message.text.split())
                return normalized[:60] or "会话"
        return "会话"

    def _on_generation_failed(self, message: str) -> None:
        if self.sender() is not self._worker:
            return
        self._state.set_state(InteractionState.IDLE)
        self._conversation.set_busy(False)
        self._stream_text = ""
        self._stream_message_started = False
        self._add_system_message(message, is_error=True)
        if self._conversation.isVisible():
            self._last_visible_count = len(self._messages)
            self._tray.setToolTip("ScreenToAgent · 回答失败")
        else:
            self._tray.showMessage(
                "回答失败",
                f"按 {self._config.hotkey} 查看会话",
                QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )
        self._update_tray_state()
        logger.warning("Agent generation failed: %s", message.splitlines()[0][:300])

    def _on_generation_canceled(self) -> None:
        if self.sender() is not self._worker:
            return
        self._state.set_state(InteractionState.IDLE)
        self._conversation.set_busy(False)
        self._stream_text = ""
        self._stream_message_started = False
        self._add_system_message("已取消。")
        if self._conversation.isVisible():
            self._last_visible_count = len(self._messages)
        self._update_tray_state()
        logger.info("Agent generation canceled")

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if self._worker is worker:
            self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._conversation.set_busy(False)
        self._update_tray_state()

    def _cancel_generation(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _tray_capture(self) -> None:
        if self._is_busy():
            return
        self._start_capture()

    def _tray_toggle_conversation(self) -> None:
        if not self._has_conversation:
            self._tray.showMessage(
                "ScreenToAgent",
                "还没有会话。按热键或托盘“截屏提问”开始。",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
            return
        self._toggle_conversation()

    def _on_message_clicked(self) -> None:
        if self._has_conversation and not self._conversation.isVisible():
            self._show_conversation()

    def _open_settings(self) -> None:
        if self._state.state in (
            InteractionState.CAPTURING,
            InteractionState.ANNOTATING,
        ):
            return
        self._settings_open = True
        try:
            dialog = SettingsDialog(
                self._config.hotkey,
                self._config.storage_root,
                self._shortcuts,
                self._config.conversation_font_size,
                self._config.conversation_image_width,
                self._hotkey.probe,
                self._apply_settings,
                str(default_storage_root()),
            )
            dialog.exec()
        finally:
            self._settings_open = False

    def _apply_settings(
        self,
        hotkey: str,
        storage_root: str,
        shortcuts: InputShortcuts,
        font_size: int,
        image_width: int,
    ) -> tuple[bool, str]:
        shortcuts_ok, shortcuts_message = validate_input_shortcuts(shortcuts, hotkey)
        if not shortcuts_ok:
            return False, shortcuts_message

        font_size = max(
            CONVERSATION_FONT_SIZE_MIN,
            min(CONVERSATION_FONT_SIZE_MAX, font_size),
        )
        image_width = max(
            CONVERSATION_IMAGE_WIDTH_MIN,
            min(CONVERSATION_IMAGE_WIDTH_MAX, image_width),
        )

        available, hotkey_message = self._hotkey.probe(hotkey)
        if not available:
            return False, hotkey_message or "截图快捷键不可用。"

        try:
            attachments_dir = resolve_attachments_dir(storage_root)
        except (OSError, ValueError) as exc:
            return False, f"存储位置不可用：{exc}"

        old = self._config
        try:
            save_settings(
                hotkey=hotkey,
                storage_root=storage_root,
                input_shortcuts=shortcuts,
                conversation_font_size=font_size,
                conversation_image_width=image_width,
            )
        except OSError as exc:
            return False, f"保存配置失败：{exc}"

        ok, note = self._hotkey.set_spec(hotkey, allow_fallback=False)
        if not ok:
            try:
                save_settings(
                    hotkey=old.hotkey,
                    storage_root=old.storage_root,
                    input_shortcuts=old.input_shortcuts,
                    conversation_font_size=old.conversation_font_size,
                    conversation_image_width=old.conversation_image_width,
                )
            except OSError:
                logger.exception("Failed to restore settings config")
            return False, note

        self._config = replace(
            self._config,
            hotkey=hotkey,
            storage_root=storage_root,
            input_shortcuts=shortcuts,
            conversation_font_size=font_size,
            conversation_image_width=image_width,
        )
        self._shortcuts = shortcuts
        self._conversation.set_hotkey_label(hotkey)
        self._conversation.set_shortcuts(
            shortcuts.conversation_send,
            shortcuts.conversation_exit,
        )
        self._conversation.set_font_size(font_size)
        self._conversation.set_image_width(image_width)
        self._attachments = AttachmentStore(root=attachments_dir)
        self._attachments.prune(30)
        self._tray.setToolTip(self._base_tooltip())
        self._tray.showMessage(
            "设置已更新",
            "快捷键、存储位置、会话字号与图片宽度已应用。",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
        logger.info("Settings updated")
        return True, note

    def _base_tooltip(self) -> str:
        if self._conversation.isVisible():
            return "ScreenToAgent · 会话已打开"
        if self._has_conversation:
            return (
                f"ScreenToAgent · 轻点 {self._config.hotkey} 开关会话 · 按住截图"
            )
        return f"ScreenToAgent · 轻点 {self._config.hotkey} 打开会话 · 按住截图"

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(2000)
        self._hotkey.unregister()
        self._conversation.hide_view()
        self._tray.hide()
        logger.info("ScreenToAgent stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="screen-to-agent",
        description="截图/文本提问，会话由 Codex CLI 管理",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)

    setup_logging()
    try:
        ensure_default_config()
    except OSError:
        logger.warning("Unable to write default config", exc_info=True)
    config = load_config()

    app = QApplication(sys.argv[:1])
    app.setApplicationName("ScreenToAgent")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_app_icon())

    controller = ScreenToAgentApp(app, config)
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()
    return app.exec()
