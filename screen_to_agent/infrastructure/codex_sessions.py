from __future__ import annotations

import io
import json
import os
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

try:
    import zstandard
except ImportError:  # pragma: no cover - optional at runtime
    zstandard = None

from screen_to_agent.domain.models import AttachmentRef, ChatMessage, SessionInfo

_SESSION_ID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def default_sessions_root() -> Path:
    override = os.environ.get("SCREEN_TO_AGENT_CODEX_SESSIONS")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex" / "sessions"


class CodexSessionStore:
    """Read-only view over Codex CLI's rollout session files.

    The app never creates or edits sessions; it only lists and reads what the CLI wrote.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_sessions_root()

    def list_sessions(self, limit: int = 50) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        seen: set[str] = set()
        for path in self._session_files():
            try:
                info = self._read_info(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if info.id in seen:
                continue
            seen.add(info.id)
            sessions.append(info)
            if len(sessions) >= max(1, limit):
                break
        return sessions

    def latest_session(self) -> SessionInfo | None:
        sessions = self.list_sessions(1)
        return sessions[0] if sessions else None

    def find_session(self, token: str) -> SessionInfo | None:
        needle = token.strip()
        if not needle:
            return None
        lowered = needle.casefold()
        sessions = self.list_sessions(200)
        for session in sessions:
            if session.id == needle:
                return session
        for session in sessions:
            if session.id.startswith(needle):
                return session
        for session in sessions:
            if session.title.casefold() == lowered:
                return session
        for session in sessions:
            if lowered in session.title.casefold():
                return session
        return None

    def find_new_session_since(
        self, timestamp: float, cwd: str | None = None
    ) -> SessionInfo | None:
        candidates = [
            path
            for path in self._session_files()
            if path.stat().st_mtime >= timestamp - 2
        ]
        for path in candidates:
            try:
                info = self._read_info(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if cwd and info.cwd:
                if os.path.normcase(info.cwd) != os.path.normcase(cwd):
                    continue
            return info
        return None

    def paths_for_session(self, session_id: str) -> list[Path]:
        matches = [
            path for path in self._session_files() if session_id in path.name
        ]
        if matches:
            return sorted(matches, key=lambda item: item.stat().st_mtime)
        for path in self._session_files():
            try:
                info = self._read_info(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if info.id == session_id:
                matches.append(path)
        return sorted(matches, key=lambda item: item.stat().st_mtime)

    def load_history(self, session_id: str, limit: int = 1000) -> list[ChatMessage]:
        paths = self.paths_for_session(session_id)
        if not paths:
            return []

        messages: deque[ChatMessage] = deque(maxlen=max(1, limit))
        for path in paths:
            for line in self._iter_lines(path):
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "event_msg":
                    continue
                payload = obj.get("payload")
                if not isinstance(payload, dict) or payload.get("type") != "item_completed":
                    continue
                item = payload.get("item")
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                text, attachments = _extract_content(item.get("content"))
                if not text and not attachments:
                    continue
                if item_type == "UserMessage":
                    messages.append(
                        ChatMessage(role="user", text=text, attachments=attachments)
                    )
                elif item_type == "AgentMessage":
                    messages.append(ChatMessage(role="assistant", text=text))

        if messages:
            return list(messages)

        # Older rollout formats may only have response_item messages.
        for path in paths:
            for line in self._iter_lines(path):
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "response_item":
                    continue
                payload = obj.get("payload")
                if not isinstance(payload, dict) or payload.get("type") != "message":
                    continue
                role = payload.get("role")
                if role not in ("user", "assistant"):
                    continue
                text, attachments = _extract_content(payload.get("content"))
                if text or attachments:
                    messages.append(
                        ChatMessage(role=role, text=text, attachments=attachments)
                    )
        return list(messages)

    def _session_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        files = [
            path
            for path in self.root.rglob("rollout-*.jsonl*")
            if path.name.endswith(".jsonl") or path.name.endswith(".jsonl.zst")
        ]
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return files

    def _read_info(self, path: Path) -> SessionInfo:
        session_id = ""
        updated_at = ""
        cwd = ""
        title = ""
        for index, line in enumerate(self._iter_lines(path)):
            if index > 300:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "session_meta":
                payload = obj.get("payload")
                if isinstance(payload, dict):
                    session_id = str(payload.get("session_id") or payload.get("id") or "")
                    updated_at = str(payload.get("timestamp") or "")
                    cwd = str(payload.get("cwd") or "")
            elif not title and obj.get("type") == "event_msg":
                payload = obj.get("payload")
                if (
                    isinstance(payload, dict)
                    and payload.get("type") == "item_completed"
                    and isinstance(payload.get("item"), dict)
                    and payload["item"].get("type") == "UserMessage"
                ):
                    title = _extract_content(
                        payload["item"].get("content")
                    )[0]
            if session_id and title:
                break

        if not session_id:
            match = _SESSION_ID_RE.search(path.name)
            session_id = match.group(1) if match else path.stem
        if not updated_at:
            updated_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        title = _clean_title(title) or f"会话 {session_id[:8]}"
        return SessionInfo(
            id=session_id,
            title=title,
            cwd=cwd,
            updated_at=updated_at,
            path=str(path),
        )

    @staticmethod
    def _iter_lines(path: Path):
        if path.name.endswith(".zst"):
            if zstandard is None:
                return
            with path.open("rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw) as reader:
                    text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
                    yield from text
            return
        with path.open("r", encoding="utf-8", errors="replace") as text:
            yield from text


def _extract_content(content: object) -> tuple[str, tuple[AttachmentRef, ...]]:
    if isinstance(content, str):
        return content.strip(), ()
    if not isinstance(content, list):
        return "", ()
    parts: list[str] = []
    attachments: list[AttachmentRef] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
        path = item.get("path")
        if (
            item.get("type") in ("local_image", "image")
            and isinstance(path, str)
            and path.strip()
        ):
            attachments.append(AttachmentRef(path=path.strip()))
    return "\n".join(parts).strip(), tuple(attachments)


def _extract_text(content: object) -> str:
    return _extract_content(content)[0]


def _clean_title(text: str) -> str:
    normalized = " ".join(text.split())
    return normalized[:60]
