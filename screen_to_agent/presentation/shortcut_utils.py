from __future__ import annotations

from PySide6.QtGui import QKeySequence

from screen_to_agent.config import InputShortcuts


def normalize_shortcut(value: str) -> str:
    return QKeySequence(value).toString(QKeySequence.SequenceFormat.PortableText)


def event_matches_shortcut(event, value: str) -> bool:
    if not value:
        return False
    try:
        event_sequence = QKeySequence(event.keyCombination()).toString(
            QKeySequence.SequenceFormat.PortableText
        )
    except (AttributeError, TypeError):
        return False
    return bool(event_sequence) and event_sequence == normalize_shortcut(value)


def validate_input_shortcuts(
    shortcuts: InputShortcuts,
    hotkey: str,
) -> tuple[bool, str]:
    contexts = [
        (
            "截图输入",
            [
                ("截图发送", shortcuts.screenshot_send),
                ("截图退出", shortcuts.screenshot_exit),
            ],
        ),
        (
            "会话输入",
            [
                ("会话发送", shortcuts.conversation_send),
                ("会话退出", shortcuts.conversation_exit),
            ],
        ),
    ]
    normalized: list[tuple[str, str]] = []
    for context, entries in contexts:
        context_entries: list[tuple[str, str]] = []
        for label, value in entries:
            sequence = normalize_shortcut(value)
            if not sequence:
                return False, f"{label}快捷键不能为空或无效。"
            if label.endswith("发送") and sequence == "Shift+Return":
                return False, f"{label}不能使用 Shift+Enter，它与换行冲突。"
            context_entries.append((label, sequence))
        if context_entries[0][1] == context_entries[1][1]:
            return False, (
                f"{context}发送与退出快捷键冲突：{context_entries[0][1]}"
            )
        normalized.extend(context_entries)

    hotkey_sequence = normalize_shortcut(hotkey)
    for label, sequence in normalized:
        if hotkey_sequence and sequence == hotkey_sequence:
            return False, f"{label}与截图热键冲突：{sequence}"

    return True, ""
