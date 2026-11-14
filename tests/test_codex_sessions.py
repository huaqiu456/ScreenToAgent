from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

from screen_to_agent.infrastructure.codex_sessions import CodexSessionStore


def _write_session(root: Path, session_id: str, user_text: str, answer: str) -> Path:
    path = root / "2026" / "11" / "14" / f"rollout-2026-11-14T10-00-00-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {
            "type": "session_meta",
            "payload": {
                "session_id": session_id,
                "timestamp": "2026-11-14T10:00:00Z",
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
                    "content": [{"type": "Text", "text": answer}],
                },
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )
    return path


def test_list_latest_find_and_history() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session_id = str(uuid.uuid4())
        _write_session(root, session_id, "这个错误怎么修？", "## 回答\n\n先看日志。")

        store = CodexSessionStore(root=root)
        sessions = store.list_sessions()

        assert len(sessions) == 1
        assert sessions[0].id == session_id
        assert sessions[0].title == "这个错误怎么修？"
        assert sessions[0].cwd == "D:\\Work\\Demo"
        assert store.latest_session() is not None
        assert store.find_session(session_id[:8]) is not None

        history = store.load_history(session_id)
        assert [message.role for message in history] == ["user", "assistant"]
        assert history[0].text == "这个错误怎么修？"
        assert "先看日志" in history[1].text


def test_find_new_session_since() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session_id = str(uuid.uuid4())
        path = _write_session(root, session_id, "问题", "回答")

        store = CodexSessionStore(root=root)
        new_session = store.find_new_session_since(path.stat().st_mtime - 1)

        assert new_session is not None
        assert new_session.id == session_id


def test_history_contains_image_attachments() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session_id = str(uuid.uuid4())
        path = root / f"rollout-2026-11-14T10-00-00-{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            {
                "type": "session_meta",
                "payload": {"session_id": session_id, "cwd": "D:\\Work\\Demo"},
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "UserMessage",
                        "content": [
                            {"type": "text", "text": "看图"},
                            {
                                "type": "local_image",
                                "path": "C:\\tmp\\shot.png",
                            },
                        ],
                    },
                },
            },
        ]
        path.write_text(
            "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
            encoding="utf-8",
        )

        history = CodexSessionStore(root=root).load_history(session_id)

        assert len(history) == 1
        assert history[0].text == "看图"
        assert len(history[0].attachments) == 1
        assert history[0].attachments[0].path == "C:\\tmp\\shot.png"
