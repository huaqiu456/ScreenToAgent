# ScreenToAgent

**Capture a question on screen, annotate it, and send it to a local Codex CLI or an OpenAI-compatible API.**

[简体中文](README.md) | [English](README.en.md)

ScreenToAgent is a Windows desktop tool. Hold a global hotkey to select a screen region, type your question directly on the screenshot, and send the annotated image plus the question to a local Codex CLI or a configured OpenAI-compatible API. When the answer is ready, a notification appears in the bottom-right corner. Tap the hotkey to open a full-screen, semi-transparent conversation view with history and the latest answer.

Version: `0.10.0` · Platform: Windows 10/11 x64 · UI: PySide6 (Qt 6)

```text
Hold F1 (~250 ms) -> select a region -> annotate -> Ctrl+Enter to send
                                                    |
                                        Codex CLI / OpenAI-compatible API
                                                    |
                     completion notification (when the view is hidden) -> tap F1
```

## Features

- **Screenshot questions**: hold the hotkey to enter region selection. Annotation text is burned into the image and also used as the question for this request.
- **Draft preservation**: pressing the hotkey again, the exit shortcut, or cancel during capture/annotation keeps the question draft; the next capture restores it.
- **Conversation view**: full-screen and semi-transparent, with history, image thumbnails, streamed answers, and a bottom input bar for follow-up questions.
- **Session handling**: in Codex CLI mode, the most recent session is reused by default. `/new` starts a new one, `/resume` switches, and CLI session files are parsed read-only.
- **Model switching**: a model selector in the header. CLI mode reads the Codex model catalog and passes `-m`; API mode uses the configured model list.
- **Streaming**: `--json` events for CLI and SSE for API. A single Agent message is updated in place and corrected with the final text when done.
- **Rich history**: historical images are shown as thumbnails and can be previewed. Images come from the attachment cache or local paths in CLI history; missing files show a placeholder.
- **Display controls**: conversation body text is adjustable from 9–24 pt and image width from 160–1200 px. Role labels are always 2 pt larger than body text.
- **Notification policy**: no "generating" overlay after sending. A bottom-right notification appears only when the conversation view is hidden.
- **Configurable**: screenshot hotkey, attachment storage root, send/exit shortcuts for capture and conversation input, font size, and image width are all configurable in Settings.
- **Privacy-first boundaries**: no local Q&A database, no writing or renaming of Codex CLI session files, and no question/answer/image content in logs.

## Requirements

| Item | Requirement |
| --- | --- |
| OS | Windows 10 / 11 x64 |
| Python | 3.11+ (when running from source) |
| Package manager | [uv](https://docs.astral.sh/uv/) (recommended) or pip |
| Codex CLI | Required for CLI mode; install and sign in, and make sure `codex` is on `PATH` |
| API key | Required for API mode; provided through an environment variable, never the config file |

> Windows only: global hotkeys, screen capture, and the keyboard-hook fallback depend on Win32 APIs.

## Quick Start

### With uv (recommended)

```bash
cd ScreenToAgent
uv sync --extra dev
uv run python -m screen_to_agent
```

Alternatively:

```bash
uv run python main.py
```

On first launch the app creates a default config, registers the hotkey, and shows a tray icon. If the hotkey is taken by another program, the app reports it and lets you change it in Settings.

### With pip

```bash
cd ScreenToAgent
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m screen_to_agent
```

### Build a single-file executable

Packaging is only needed for release or delivery; use the source directly during development. Install the development dependencies first and run it from a terminal with the project virtual environment activated:

```bat
build.bat
```

The output is `dist\ScreenToAgent.exe`. The target machine does not need Python or PySide6. Codex CLI is not bundled and must be installed separately or configured through `codex.executable`.

## Usage

### Screenshot questions

1. **Hold** the hotkey for about 250 ms to freeze the screen and enter region selection.
2. Drag to select a region and type your question in the annotation box. The text is drawn into the image and used as the question for this request.
3. Press `Ctrl+Enter` (default) to send. Press `Esc` or the hotkey again to exit while keeping the draft.
4. When the answer completes, a bottom-right notification appears only if the conversation view is hidden.

A tap (without holding) opens or hides the conversation view. With no existing session, it opens an empty conversation.

### Conversation view

- Tap the hotkey to show/hide the view. `Esc` only clears input focus; it does not hide the view.
- Scroll with the wheel, `PageUp` / `PageDown`, or the scrollbar.
- Use the bottom input bar for text questions. `Enter` sends and `Shift+Enter` inserts a newline (configurable in Settings).
- Switch models in the header. During streaming, the selector and session-switching commands are temporarily disabled.
- Slash commands:

| Command | Effect |
| --- | --- |
| `/new` | Switch to a new session; the next CLI message creates a new Codex session |
| `/resume [id\|name]` | Switch to a CLI session; without an argument, opens the session picker |
| `/rename [name]` | The current Codex CLI has no rename command, so the app reports it as unsupported |
| `/help` | Show command help |

> API mode is single-turn and keeps no history; `/resume` and `/rename` are unavailable there.

### Settings

Tray menu -> "Settings...":

| Group | Options |
| --- | --- |
| Screenshot hotkey | `F1`–`F12` with optional `Ctrl` / `Alt` / `Shift` / `Win`; conflicts are probed before saving |
| Attachment storage | Custom root directory; attachments live in `<root>\attachments`, and old attachments are not migrated |
| Input shortcuts | Capture send/exit and conversation send/exit; same-context conflicts, conflicts with the screenshot hotkey, and `Shift+Enter` as a send key are rejected |
| Conversation display | Body font size 9–24 pt; historical image width 160–1200 px; live font preview |

## Backends

### Codex CLI (default)

- The app does not manage sessions: context, history, and continuation are owned by Codex CLI.
- The most recent Codex session is reused by default. Only the first request after `/new` creates a new session.
- Session lists and history are read-only parsed from `~/.codex/sessions/`; files are never written, renamed, or deleted.
- Models come from `codex debug models --bundled` and are passed with `-m` on each request; global CLI configuration is not modified.
- Streaming updates come from the CLI's JSONL events; the granularity depends on Codex CLI.

### OpenAI-compatible API (single-turn)

Set `default_backend` in `config.json` to a value other than `codex-cli` (for example, `openai-compatible`) and configure:

```json
{
  "default_backend": "openai-compatible",
  "api": {
    "base_url": "https://your-api-host/v1",
    "model": "your-model",
    "api_key_env": "SCREEN_TO_AGENT_API_KEY",
    "timeout_seconds": 120,
    "models": ["your-model"]
  }
}
```

Then set the environment variable (PowerShell):

```powershell
$env:SCREEN_TO_AGENT_API_KEY = "your-api-key"
```

- Requests go to `<base_url>/chat/completions`. SSE streaming is preferred, with a fallback to a regular response when the server does not support it.
- API mode carries no history context; every question is an independent request. `/new` only clears the current on-screen messages.
- The API key is read only from the environment variable; it is never written to the config file or logs.

## Configuration

Default config file: `%APPDATA%\ScreenToAgent\config.json` (created on first launch).

```json
{
  "hotkey": "F1",
  "default_backend": "codex-cli",
  "answer_overlay": {
    "opacity": 0.72
  },
  "storage": {
    "root": ""
  },
  "conversation": {
    "font_size": 13,
    "image_width": 360
  },
  "input_shortcuts": {
    "screenshot": {
      "send": "Ctrl+Return",
      "exit": "Esc"
    },
    "conversation": {
      "send": "Return",
      "exit": "Esc"
    }
  },
  "codex": {
    "executable": "codex",
    "sandbox": "read-only",
    "resume": true,
    "model": ""
  },
  "api": {
    "base_url": "",
    "model": "",
    "api_key_env": "SCREEN_TO_AGENT_API_KEY",
    "timeout_seconds": 120,
    "models": []
  }
}
```

| Key | Description |
| --- | --- |
| `hotkey` | Global screenshot/conversation hotkey; defaults to `F1` |
| `default_backend` | `codex-cli` uses Codex CLI; any other value selects the OpenAI-compatible API |
| `answer_overlay.opacity` | Conversation view opacity, clamped to 0.5–0.9 |
| `storage.root` | Attachment root; when empty, `%APPDATA%\ScreenToAgent` is used |
| `conversation.font_size` | Conversation body font size, 9–24 pt, default 13 |
| `conversation.image_width` | Historical image thumbnail width, 160–1200 px, default 360 |
| `input_shortcuts.*` | Send and exit shortcuts for capture and conversation input |
| `codex.executable` | Codex CLI executable or command name |
| `codex.sandbox` | Codex CLI sandbox level, default `read-only` |
| `codex.resume` | Whether to continue the most recent session by default |
| `codex.model` | Codex CLI model; empty means the CLI default |
| `api.*` | OpenAI-compatible API URL, model, key environment variable, and timeout |

Environment variables:

| Variable | Purpose |
| --- | --- |
| `SCREEN_TO_AGENT_API_KEY` | API key for API mode; the variable name can be overridden by `api.api_key_env` |
| `SCREEN_TO_AGENT_ATTACHMENTS` | Overrides the attachment directory under the default storage root |
| `SCREEN_TO_AGENT_CONFIG` | Points to an alternative config file for development and testing |

## Data and Privacy

- Attachments are content-addressed by SHA-256: by default under `%APPDATA%\ScreenToAgent\attachments`, or `<root>\attachments` with a custom root.
- Changing the storage location does not migrate old attachments. Historical images keep their original absolute paths and show "image unavailable" when missing.
- The app has no local session or Q&A database. Codex CLI session files are parsed read-only.
- At startup, files older than 30 days in the current attachment directory are pruned. Only that directory is scanned; subdirectories are not deleted recursively.
- Logs live at `%APPDATA%\ScreenToAgent\logs\app.log` and do not record question text, annotations, answers, image content, or keys.
- The API key is read from the environment only. Do not commit `.env` files, keys, or personal screenshots.

## Project Layout

```text
ScreenToAgent/
├── screen_to_agent/
│   ├── app.py                    # Controller, hotkey routing, tray, app orchestration
│   ├── config.py                 # Config models, defaults, and persistence
│   ├── domain/                   # Domain models (messages, captures, sessions, results)
│   ├── application/              # Interaction state machine and prompt builder
│   ├── infrastructure/           # Codex/API backends, sessions, hotkeys, capture, attachments
│   └── presentation/             # Capture overlay, conversation view, settings, session picker
├── tests/                        # pytest suite (offscreen Qt)
├── docs/                         # Architecture and numbered requirement documents
├── assets/                       # Application icon
├── main.py                       # Local development entry point
├── build.bat                     # PyInstaller single-file build
├── pyproject.toml
└── AGENTS.md                     # Collaboration rules, coding conventions, invariants
```

## Development and Testing

```bash
# Install development dependencies
uv sync --extra dev

# Run all tests (offscreen Qt)
uv run pytest

# Lint and format checks
uv run ruff check .
uv run ruff format --check .
```

This project follows spec-driven development: write the feature into `docs/YYYY-MM-DD-<feature-name>/requirements.md` first, and move the requirement through "draft -> confirmed -> implementing -> done". See [docs/architecture.md](docs/architecture.md) for architecture and module boundaries, and [AGENTS.md](AGENTS.md) for collaboration rules.

## Documentation

| Document | Contents |
| --- | --- |
| [Architecture](docs/architecture.md) | Layering, modules, threading, configuration, safety, and testing strategy |
| [REQ-001 Screenshot questions](docs/2026-11-14-截图提问转发Agent/requirements.md) | Screenshot, annotation, notification, and answer-view fundamentals |
| [REQ-002 Conversation UI](docs/2026-11-14-会话式回答界面/requirements.md) | History, input bar, hide/restore, session commands, hold/tap |
| [REQ-003 Models, streaming, image history](docs/2026-11-14-模型切换流式输出与图片历史/requirements.md) | Model switching, SSE/JSONL streaming, image history, attachment cache |
| [REQ-004 Storage and input shortcuts](docs/2026-11-14-存储位置与输入快捷键设置/requirements.md) | Custom attachment root, send/exit shortcuts, conflict validation |
| [REQ-005 Conversation font size](docs/2026-11-14-会话字体大小设置/requirements.md) | Font size, role labels, historical image width |

## Known Limitations

- DPAPI-encrypted API key storage and a backend-switching settings UI are not implemented yet; switching currently uses the config file and environment variables.
- API mode has no history context and does not support `/resume` or `/rename`.
- `/rename` depends on a future Codex CLI command; the app never fakes a local rename.
- Codex CLI streaming granularity depends on the CLI's JSONL events; Codex app-server is not integrated yet.
- Paste/drag image upload, attachment migration, multiple annotations, a single-instance guard, code signing, and an installer are not implemented.
- Windows 10/11 x64 only.

## License

No `LICENSE` file has been added yet. Please add a license before publishing the project as open source.
