from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from screen_to_agent.config import InputShortcuts
from screen_to_agent.presentation.shortcut_utils import (
    event_matches_shortcut,
    validate_input_shortcuts,
)


def test_default_shortcuts_are_valid() -> None:
    ok, message = validate_input_shortcuts(InputShortcuts(), "F1")
    assert ok, message


def test_same_context_send_and_exit_conflict() -> None:
    shortcuts = InputShortcuts(
        screenshot_send="Alt+S",
        screenshot_exit="Alt+S",
    )
    ok, message = validate_input_shortcuts(shortcuts, "F1")
    assert not ok
    assert "冲突" in message


def test_hotkey_conflict() -> None:
    ok, message = validate_input_shortcuts(InputShortcuts(), "Ctrl+Return")
    assert not ok
    assert "截图热键" in message


def test_shift_enter_send_is_rejected() -> None:
    shortcuts = InputShortcuts(conversation_send="Shift+Return")
    ok, message = validate_input_shortcuts(shortcuts, "F1")
    assert not ok
    assert "Shift+Enter" in message


def test_event_matches_normalized_shortcut() -> None:
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_S,
        Qt.KeyboardModifier.AltModifier,
    )
    assert event_matches_shortcut(event, "Alt+S")
    assert not event_matches_shortcut(event, "Ctrl+S")
