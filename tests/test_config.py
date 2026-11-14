from __future__ import annotations

import json
import tempfile
from pathlib import Path

from screen_to_agent.config import InputShortcuts, load_config, save_hotkey, save_settings


def test_loads_documented_config_shape() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "hotkey": "Ctrl+Shift+F2",
                    "default_backend": "codex-cli",
                    "answer_overlay": {"opacity": 0.8},
                    "backends": [
                        {
                            "id": "codex-cli",
                            "type": "cli",
                            "command": ["codex", "exec", "-i", "{image}", "{prompt}"],
                            "timeout_seconds": 60,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        config = load_config(path)

    assert config.hotkey == "Ctrl+Shift+F2"
    assert config.backend == "codex-cli"
    assert config.overlay_opacity == 0.8
    assert config.codex.executable == "codex"
    assert config.codex.timeout_seconds == 60


def test_clamps_opacity_and_handles_broken_json() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "config.json"

        path.write_text('{"answer_overlay": {"opacity": 9}}', encoding="utf-8")
        assert load_config(path).overlay_opacity == 0.9

        path.write_text("{not-json", encoding="utf-8")
        config = load_config(path)

    assert config.hotkey == "F1"
    assert config.overlay_opacity == 0.72


def test_save_hotkey_preserves_other_settings() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "hotkey": "F1",
                    "codex": {"executable": "codex", "resume": False},
                    "answer_overlay": {"opacity": 0.8},
                }
            ),
            encoding="utf-8",
        )

        save_hotkey("Ctrl+F2", path)
        data = json.loads(path.read_text(encoding="utf-8"))

    assert data["hotkey"] == "Ctrl+F2"
    assert data["codex"]["resume"] is False
    assert data["answer_overlay"]["opacity"] == 0.8


def test_loads_storage_and_input_shortcuts() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "storage": {"root": "D:\\ScreenToAgentData"},
                    "input_shortcuts": {
                        "screenshot": {"send": "Alt+S", "exit": "Alt+X"},
                        "conversation": {"send": "Ctrl+Return", "exit": "Alt+Q"},
                    },
                }
            ),
            encoding="utf-8",
        )

        config = load_config(path)

    assert config.storage_root == "D:\\ScreenToAgentData"
    assert config.input_shortcuts.screenshot_send == "Alt+S"
    assert config.input_shortcuts.screenshot_exit == "Alt+X"
    assert config.input_shortcuts.conversation_send == "Ctrl+Return"
    assert config.input_shortcuts.conversation_exit == "Alt+Q"


def test_loads_and_clamps_conversation_font_size() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "config.json"

        path.write_text(
            json.dumps({"conversation": {"font_size": 18, "image_width": 520}}),
            encoding="utf-8",
        )
        config = load_config(path)
        assert config.conversation_font_size == 18
        assert config.conversation_image_width == 520

        path.write_text(
            json.dumps({"conversation": {"font_size": 30, "image_width": 9999}}),
            encoding="utf-8",
        )
        config = load_config(path)
        assert config.conversation_font_size == 24
        assert config.conversation_image_width == 1200

        path.write_text(
            json.dumps({"conversation": {"font_size": 3, "image_width": 10}}),
            encoding="utf-8",
        )
        config = load_config(path)
        assert config.conversation_font_size == 9
        assert config.conversation_image_width == 160

        path.write_text(
            json.dumps({"conversation": {"font_size": "abc", "image_width": "abc"}}),
            encoding="utf-8",
        )
        config = load_config(path)
        assert config.conversation_font_size == 13
        assert config.conversation_image_width == 360

        path.write_text("{}", encoding="utf-8")
        config = load_config(path)
        assert config.conversation_font_size == 13
        assert config.conversation_image_width == 360


def test_save_settings_preserves_other_fields() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "config.json"
        path.write_text(
            json.dumps({"codex": {"executable": "codex"}, "hotkey": "F1"}),
            encoding="utf-8",
        )
        shortcuts = InputShortcuts(
            screenshot_send="Alt+S",
            screenshot_exit="Alt+X",
            conversation_send="Ctrl+Return",
            conversation_exit="Alt+Q",
        )

        save_settings(
            path,
            hotkey="F2",
            storage_root="D:\\Data",
            input_shortcuts=shortcuts,
            conversation_font_size=18,
            conversation_image_width=520,
        )
        data = json.loads(path.read_text(encoding="utf-8"))

    assert data["hotkey"] == "F2"
    assert data["storage"]["root"] == "D:\\Data"
    assert data["input_shortcuts"]["screenshot"]["send"] == "Alt+S"
    assert data["conversation"]["font_size"] == 18
    assert data["conversation"]["image_width"] == 520
    assert data["codex"]["executable"] == "codex"
