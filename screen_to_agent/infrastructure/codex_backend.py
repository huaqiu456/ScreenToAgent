from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from screen_to_agent.config import CodexSettings
from screen_to_agent.domain.models import TurnResult
from screen_to_agent.infrastructure.codex_sessions import CodexSessionStore

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def build_codex_args(
    executable: str,
    image_path: Path | None,
    output_path: Path,
    prompt: str,
    session_id: str | None = None,
    resume_last: bool = False,
    start_new: bool = False,
    sandbox: str = "read-only",
    model: str = "",
) -> list[str]:
    image_args = ["-i", str(image_path)] if image_path is not None else []
    model_args = ["-m", model] if model else []
    if not start_new and (session_id or resume_last):
        args = [
            executable,
            "exec",
            "resume",
            "--skip-git-repo-check",
            "--json",
            *model_args,
            *image_args,
            "-o",
            str(output_path),
        ]
        if session_id:
            args.append(session_id)
        else:
            args.insert(3, "--last")
        args.append(prompt)
        return args

    return [
        executable,
        "exec",
        "--skip-git-repo-check",
        "-s",
        sandbox,
        "--color",
        "never",
        "--json",
        *model_args,
        *image_args,
        "-o",
        str(output_path),
        prompt,
    ]


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def resolve_executable(value: str) -> str | None:
    for candidate in (value, f"{value}.cmd", f"{value}.exe"):
        found = shutil.which(candidate)
        if found:
            return found

    path = Path(value).expanduser()
    if path.is_file():
        return str(path)

    if sys.platform == "win32" and not path.is_absolute():
        appdata = os.environ.get("APPDATA")
        if appdata:
            for suffix in ("", ".cmd", ".exe"):
                candidate = Path(appdata) / "npm" / f"{value}{suffix}"
                if candidate.is_file():
                    return str(candidate)
    return None


def parse_codex_stream_line(line: str) -> tuple[str, str] | None:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    event_type = str(obj.get("type") or "")
    lowered = event_type.lower()

    if "error" in lowered:
        message = obj.get("message") or obj.get("error")
        if isinstance(message, str) and message.strip():
            return "error", message.strip()

    if "delta" in lowered and ("agent" in lowered or "message" in lowered):
        delta = obj.get("delta")
        if not isinstance(delta, str):
            delta = obj.get("text")
        if isinstance(delta, str) and delta:
            return "delta", delta

    item = obj.get("item")
    if isinstance(item, dict):
        item_type = str(item.get("type") or "").lower()
        if "agent" in item_type:
            text = _item_text(item)
            if text:
                if lowered in ("item.completed", "item_completed"):
                    return "final", text
                if lowered in ("item.started", "item_started", "item.updated", "item_updated"):
                    return "snapshot", text

    if lowered in ("turn.completed", "turn_completed"):
        last_message = obj.get("last_agent_message")
        if isinstance(last_message, str) and last_message.strip():
            return "final", last_message.strip()

    if isinstance(obj.get("delta"), str) and "agent" in lowered:
        return "delta", obj["delta"]
    return None


def _item_text(item: dict) -> str:
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    content = item.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, dict):
            value = part.get("text")
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return "\n".join(parts).strip()


class CodexWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    canceled = Signal()
    stream_text = Signal(str)

    def __init__(
        self,
        image_path: Path | None,
        prompt: str,
        settings: CodexSettings,
        store: CodexSessionStore,
        session_id: str | None,
        start_new: bool,
        resume_last: bool,
        model: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._image_path = image_path
        self._prompt = prompt
        self._settings = settings
        self._store = store
        self._session_id = session_id
        self._start_new = start_new
        self._resume_last = resume_last
        self._model = model
        self._cancel_requested = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._streamed_text = ""
        self._final_event_text = ""
        self._stream_error = ""
        self._stderr_lines: list[str] = []

    def run(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="screen-to-agent-"))
        output_path = temp_dir / "answer.txt"
        process: subprocess.Popen[str] | None = None
        stdout_thread: threading.Thread | None = None
        stderr_thread: threading.Thread | None = None
        try:
            executable = resolve_executable(self._settings.executable)
            if not executable:
                self.failed.emit(
                    f"未找到 Codex CLI：{self._settings.executable}。\n"
                    "请先安装 codex，或在配置文件中修改 codex.executable。"
                )
                return

            args = build_codex_args(
                executable,
                self._image_path,
                output_path,
                self._prompt,
                session_id=None if self._start_new else self._session_id,
                resume_last=self._resume_last,
                start_new=self._start_new,
                sandbox=self._settings.sandbox,
                model=self._model,
            )
            started_at = time.time()
            process = subprocess.Popen(
                args,
                cwd=str(Path.cwd()),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
            )
            with self._process_lock:
                self._process = process

            stdout_thread = threading.Thread(
                target=self._read_stdout, args=(process,), daemon=True
            )
            stderr_thread = threading.Thread(
                target=self._read_stderr, args=(process,), daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()

            if self._cancel_requested.is_set():
                _kill_tree(process)

            timed_out = False
            deadline = time.monotonic() + self._settings.timeout_seconds
            while process.poll() is None:
                if self._cancel_requested.is_set():
                    _kill_tree(process)
                    break
                if time.monotonic() > deadline:
                    _kill_tree(process)
                    timed_out = True
                    break
                time.sleep(0.03)

            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

            if self._cancel_requested.is_set():
                self.canceled.emit()
                return
            if timed_out:
                self.failed.emit(
                    f"Codex CLI 执行超时（{self._settings.timeout_seconds} 秒）。"
                    "可以重试或调整 codex.timeout_seconds。"
                )
                return

            stderr = "".join(self._stderr_lines).strip()
            if process.returncode != 0:
                detail = strip_ansi(stderr)[-1500:]
                prefix = "Codex CLI 执行失败"
                if not self._start_new:
                    prefix = "无法续接 Codex CLI 会话"
                if not detail:
                    with self._stream_lock:
                        detail = self._stream_error[-1500:]
                self.failed.emit(f"{prefix}（退出码 {process.returncode}）。\n\n{detail}")
                return

            answer = ""
            if output_path.exists():
                answer = strip_ansi(
                    output_path.read_text(encoding="utf-8", errors="replace")
                )
            with self._stream_lock:
                if not answer.strip():
                    answer = self._final_event_text or self._streamed_text
                stream_error = self._stream_error
            answer = answer.strip()
            if not answer:
                self.failed.emit(stream_error or "Codex CLI 未返回回答内容。")
                return

            session_info = None
            if self._start_new:
                session_info = self._store.find_new_session_since(
                    started_at, cwd=str(Path.cwd())
                )
            elif self._session_id:
                session_info = self._store.find_session(self._session_id)
            elif self._resume_last:
                session_info = self._store.latest_session()

            self.succeeded.emit(
                TurnResult(
                    answer=answer,
                    session_id=session_info.id if session_info else None,
                    session_title=session_info.title if session_info else None,
                    started_new_session=self._start_new,
                )
            )
        except OSError as exc:
            self.failed.emit(f"启动 Codex CLI 失败：{exc}")
        finally:
            with self._process_lock:
                self._process = None
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        try:
            for line in process.stdout:
                update = parse_codex_stream_line(line)
                if update is not None:
                    self._handle_stream_update(*update)
        except (OSError, ValueError):
            return

    def _read_stderr(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        try:
            for line in process.stderr:
                self._stderr_lines.append(line)
        except (OSError, ValueError):
            return

    def _handle_stream_update(self, kind: str, text: str) -> None:
        if not text:
            return
        if kind == "error":
            with self._stream_lock:
                self._stream_error = text
            return

        emit_text = ""
        with self._stream_lock:
            if kind == "delta":
                self._streamed_text += text
                emit_text = text
            elif kind == "snapshot":
                if text.startswith(self._streamed_text) and len(text) > len(
                    self._streamed_text
                ):
                    emit_text = text[len(self._streamed_text) :]
                    self._streamed_text = text
                elif not self._streamed_text:
                    emit_text = text
                    self._streamed_text = text
            else:
                self._final_event_text = text
                if not self._streamed_text:
                    emit_text = text
                    self._streamed_text = text
        if emit_text:
            self.stream_text.emit(emit_text)

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            _kill_tree(process)


def _kill_tree(process: subprocess.Popen[str]) -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass
