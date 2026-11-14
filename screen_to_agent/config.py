from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "ScreenToAgent"

CONVERSATION_FONT_SIZE_MIN = 9
CONVERSATION_FONT_SIZE_MAX = 24
CONVERSATION_FONT_SIZE_DEFAULT = 13
CONVERSATION_IMAGE_WIDTH_MIN = 160
CONVERSATION_IMAGE_WIDTH_MAX = 1200
CONVERSATION_IMAGE_WIDTH_DEFAULT = 360


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / APP_NAME


def config_path() -> Path:
    override = os.environ.get("SCREEN_TO_AGENT_CONFIG")
    if override:
        return Path(override).expanduser()
    return app_data_dir() / "config.json"


@dataclass(frozen=True)
class CodexSettings:
    executable: str = "codex"
    timeout_seconds: int = 180
    sandbox: str = "read-only"
    resume: bool = True
    model: str = ""


@dataclass(frozen=True)
class APISettings:
    base_url: str = ""
    model: str = ""
    api_key_env: str = "SCREEN_TO_AGENT_API_KEY"
    timeout_seconds: int = 120
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class InputShortcuts:
    screenshot_send: str = "Ctrl+Return"
    screenshot_exit: str = "Esc"
    conversation_send: str = "Return"
    conversation_exit: str = "Esc"


@dataclass(frozen=True)
class AppConfig:
    hotkey: str = "F1"
    backend: str = "codex-cli"
    overlay_opacity: float = 0.72
    storage_root: str = ""
    conversation_font_size: int = CONVERSATION_FONT_SIZE_DEFAULT
    conversation_image_width: int = CONVERSATION_IMAGE_WIDTH_DEFAULT
    codex: CodexSettings = field(default_factory=CodexSettings)
    api: APISettings = field(default_factory=APISettings)
    input_shortcuts: InputShortcuts = field(default_factory=InputShortcuts)


DEFAULT_CONFIG = {
    "hotkey": "F1",
    "default_backend": "codex-cli",
    "answer_overlay": {"opacity": 0.72},
    "storage": {"root": ""},
    "conversation": {
        "font_size": CONVERSATION_FONT_SIZE_DEFAULT,
        "image_width": CONVERSATION_IMAGE_WIDTH_DEFAULT,
    },
    "input_shortcuts": {
        "screenshot": {"send": "Ctrl+Return", "exit": "Esc"},
        "conversation": {"send": "Return", "exit": "Esc"},
    },
    "backends": [
        {
            "id": "codex-cli",
            "name": "Codex CLI（CLI 管理会话）",
            "type": "cli",
            "session_mode": "cli-managed",
            "command": ["codex", "exec", "-i", "{image}", "{prompt}"],
            "timeout_seconds": 180,
        }
    ],
    "codex": {
        "executable": "codex",
        "sandbox": "read-only",
        "resume": True,
        "model": "",
    },
    "api": {
        "base_url": "",
        "model": "",
        "api_key_env": "SCREEN_TO_AGENT_API_KEY",
        "timeout_seconds": 120,
        "models": [],
    },
}


def ensure_default_config(path: Path | None = None) -> Path:
    target = path or config_path()
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return target


def save_hotkey(spec: str, path: Path | None = None) -> Path:
    return save_settings(path, hotkey=spec)


def save_settings(
    path: Path | None = None,
    *,
    hotkey: str | None = None,
    storage_root: str | None = None,
    input_shortcuts: InputShortcuts | None = None,
    conversation_font_size: int | None = None,
    conversation_image_width: int | None = None,
) -> Path:
    target = path or config_path()
    data: dict = {}
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    if not data:
        data = json.loads(json.dumps(DEFAULT_CONFIG))

    if hotkey is not None:
        data["hotkey"] = hotkey
    if storage_root is not None:
        storage = data.get("storage")
        if not isinstance(storage, dict):
            storage = {}
        storage["root"] = storage_root
        data["storage"] = storage
    if conversation_font_size is not None or conversation_image_width is not None:
        conversation = data.get("conversation")
        if not isinstance(conversation, dict):
            conversation = {}
        if conversation_font_size is not None:
            conversation["font_size"] = _clamp_font_size(conversation_font_size)
        if conversation_image_width is not None:
            conversation["image_width"] = _clamp_image_width(
                conversation_image_width
            )
        data["conversation"] = conversation
    if input_shortcuts is not None:
        data["input_shortcuts"] = {
            "screenshot": {
                "send": input_shortcuts.screenshot_send,
                "exit": input_shortcuts.screenshot_exit,
            },
            "conversation": {
                "send": input_shortcuts.conversation_send,
                "exit": input_shortcuts.conversation_exit,
            },
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(target)
    return target


def load_config(path: Path | None = None) -> AppConfig:
    target = path or config_path()
    if not target.exists():
        return AppConfig()

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()

    backend_id = str(data.get("default_backend", "codex-cli"))
    overlay = data.get("answer_overlay")
    opacity = 0.72
    if isinstance(overlay, dict):
        opacity = _as_float(overlay.get("opacity"), opacity)
    opacity = min(0.9, max(0.5, opacity))

    codex_data = data.get("codex") if isinstance(data.get("codex"), dict) else {}
    executable = str(codex_data.get("executable") or "").strip()
    timeout = _as_int(codex_data.get("timeout_seconds"), 180)
    sandbox = str(codex_data.get("sandbox") or "read-only")
    resume = bool(codex_data.get("resume", True))
    codex_model = str(codex_data.get("model") or "").strip()

    api_data = data.get("api") if isinstance(data.get("api"), dict) else {}
    api_models = api_data.get("models")
    api_model_list: tuple[str, ...] = ()
    if isinstance(api_models, list):
        api_model_list = tuple(
            str(item).strip() for item in api_models if str(item).strip()
        )

    storage_data = data.get("storage")
    storage_root = ""
    if isinstance(storage_data, dict):
        storage_root = str(storage_data.get("root") or "").strip()

    conversation_data = data.get("conversation")
    font_size = CONVERSATION_FONT_SIZE_DEFAULT
    image_width = CONVERSATION_IMAGE_WIDTH_DEFAULT
    if isinstance(conversation_data, dict):
        font_size = _clamp_font_size(
            _as_int(
                conversation_data.get("font_size"),
                CONVERSATION_FONT_SIZE_DEFAULT,
            )
        )
        image_width = _clamp_image_width(
            _as_int(
                conversation_data.get("image_width"),
                CONVERSATION_IMAGE_WIDTH_DEFAULT,
            )
        )

    shortcut_data = data.get("input_shortcuts")
    shortcut_defaults = InputShortcuts()
    screenshot_shortcuts = (
        shortcut_data.get("screenshot") if isinstance(shortcut_data, dict) else None
    )
    conversation_shortcuts = (
        shortcut_data.get("conversation") if isinstance(shortcut_data, dict) else None
    )
    input_shortcuts = InputShortcuts(
        screenshot_send=str(
            (screenshot_shortcuts or {}).get("send")
            or shortcut_defaults.screenshot_send
        ),
        screenshot_exit=str(
            (screenshot_shortcuts or {}).get("exit")
            or shortcut_defaults.screenshot_exit
        ),
        conversation_send=str(
            (conversation_shortcuts or {}).get("send")
            or shortcut_defaults.conversation_send
        ),
        conversation_exit=str(
            (conversation_shortcuts or {}).get("exit")
            or shortcut_defaults.conversation_exit
        ),
    )

    backends = data.get("backends")
    if isinstance(backends, list):
        for item in backends:
            if not isinstance(item, dict) or item.get("id") != backend_id:
                continue
            if item.get("type") != "cli":
                continue
            if not executable:
                command = item.get("command")
                if isinstance(command, list) and command:
                    executable = str(command[0])
            timeout = _as_int(item.get("timeout_seconds"), timeout)
            break

    return AppConfig(
        hotkey=str(data.get("hotkey") or "F1"),
        backend=backend_id,
        overlay_opacity=opacity,
        storage_root=storage_root,
        conversation_font_size=font_size,
        conversation_image_width=image_width,
        codex=CodexSettings(
            executable=executable or "codex",
            timeout_seconds=max(10, timeout),
            sandbox=sandbox,
            resume=resume,
            model=codex_model,
        ),
        api=APISettings(
            base_url=str(api_data.get("base_url") or "").strip(),
            model=str(api_data.get("model") or "").strip(),
            api_key_env=str(
                api_data.get("api_key_env") or "SCREEN_TO_AGENT_API_KEY"
            ).strip(),
            timeout_seconds=max(10, _as_int(api_data.get("timeout_seconds"), 120)),
            models=api_model_list,
        ),
        input_shortcuts=input_shortcuts,
    )


def _as_int(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _clamp_font_size(value: int) -> int:
    return max(CONVERSATION_FONT_SIZE_MIN, min(CONVERSATION_FONT_SIZE_MAX, value))


def _clamp_image_width(value: int) -> int:
    return max(CONVERSATION_IMAGE_WIDTH_MIN, min(CONVERSATION_IMAGE_WIDTH_MAX, value))


def _as_float(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
