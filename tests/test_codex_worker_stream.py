from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer

from screen_to_agent.config import CodexSettings
from screen_to_agent.infrastructure.codex_backend import CodexWorker
from screen_to_agent.infrastructure.codex_sessions import CodexSessionStore


def _make_fake_codex(root: Path) -> Path:
    script = root / "fake_codex.py"
    script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "out = None\n"
        "for i, value in enumerate(args):\n"
        "    if value == '-o' and i + 1 < len(args):\n"
        "        out = args[i + 1]\n"
        "Path(out).write_text('流式回答', encoding='utf-8')\n"
        "print(json.dumps({'type': 'item/agentMessage/delta', 'delta': '流式'}, ensure_ascii=True), flush=True)\n"
        "print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '流式回答'}}, ensure_ascii=True), flush=True)\n"
        "print(json.dumps({'type': 'turn.completed', 'last_agent_message': '流式回答'}, ensure_ascii=True), flush=True)\n",
        encoding="utf-8",
    )
    wrapper = root / "fake_codex.cmd"
    wrapper.write_text(
        f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
        encoding="utf-8",
    )
    return wrapper


def test_codex_worker_streams_jsonl(qapp, monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        executable = _make_fake_codex(root)
        store = CodexSessionStore(root=root / "sessions")
        worker = CodexWorker(
            None,
            "问题",
            CodexSettings(executable=str(executable), timeout_seconds=20),
            store,
            None,
            True,
            False,
            model="",
        )

        chunks: list[str] = []
        results: list[object] = []
        failures: list[str] = []
        worker.stream_text.connect(chunks.append)
        worker.succeeded.connect(results.append)
        worker.failed.connect(failures.append)

        loop = QEventLoop()
        worker.succeeded.connect(loop.quit)
        worker.failed.connect(loop.quit)
        QTimer.singleShot(10000, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(5000)

        assert not failures
        assert "".join(chunks) == "流式"
        assert results
        assert results[0].answer == "流式回答"
