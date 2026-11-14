from __future__ import annotations

import pytest

from screen_to_agent.infrastructure.hotkey_win32 import (
    MOD_ALT,
    MOD_NOREPEAT,
    MOD_SHIFT,
    parse_hotkey,
)


def test_parse_f1() -> None:
    assert parse_hotkey("F1") == (MOD_NOREPEAT, 0x70)


def test_parse_modifiers() -> None:
    modifiers, virtual_key = parse_hotkey("Alt+Shift+F4")
    assert modifiers == (MOD_ALT | MOD_SHIFT | MOD_NOREPEAT)
    assert virtual_key == 0x73


@pytest.mark.parametrize("spec", ["", "A", "Ctrl+F13", "Hyper+F1"])
def test_rejects_unsupported_hotkeys(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_hotkey(spec)
