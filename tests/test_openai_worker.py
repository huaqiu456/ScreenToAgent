from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QEventLoop, QTimer

from screen_to_agent.config import APISettings
from screen_to_agent.infrastructure.openai_backend import OpenAIWorker


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for text in ("流", "式"):
            payload = {"choices": [{"delta": {"content": text}}]}
            self.wfile.write(
                f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
            )
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, _format: str, *_args) -> None:
        return


def test_openai_worker_consumes_sse(qapp, monkeypatch) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEST_API_KEY", "secret")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    try:
        settings = APISettings(
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            model="test-model",
            api_key_env="TEST_API_KEY",
            timeout_seconds=10,
        )
        worker = OpenAIWorker(None, "问题", settings, model="test-model")

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
        assert results[0].answer == "流式"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
