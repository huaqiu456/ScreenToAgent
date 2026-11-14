from __future__ import annotations

import base64
import json
import mimetypes
import os
import threading
from pathlib import Path

import httpx
from PySide6.QtCore import QThread, Signal

from screen_to_agent.config import APISettings
from screen_to_agent.domain.models import TurnResult


def parse_sse_data(data: str) -> tuple[str, str] | None:
    data = data.strip()
    if not data:
        return None
    if data == "[DONE]":
        return "done", ""
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    error = obj.get("error")
    if error:
        if isinstance(error, dict):
            message = error.get("message")
        else:
            message = str(error)
        return "error", str(message or "API 返回错误")
    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    delta = choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        text = _content_text(content)
        if text:
            return "delta", text
    message = choice.get("message")
    if isinstance(message, dict):
        text = _content_text(message.get("content"))
        if text:
            return "full", text
    return None


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


class OpenAIWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    canceled = Signal()
    stream_text = Signal(str)

    def __init__(
        self,
        image_path: Path | None,
        prompt: str,
        settings: APISettings,
        model: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._image_path = image_path
        self._prompt = prompt
        self._settings = settings
        self._model = model or settings.model
        self._cancel_requested = threading.Event()
        self._client: httpx.Client | None = None
        self._client_lock = threading.Lock()

    def run(self) -> None:
        base_url = self._settings.base_url.strip()
        if not base_url:
            self.failed.emit("API 模式未配置 api.base_url。")
            return
        if not self._model:
            self.failed.emit("API 模式未选择模型。")
            return
        api_key = os.environ.get(self._settings.api_key_env, "").strip()
        if not api_key:
            self.failed.emit(
                f"API 模式未找到密钥，请设置环境变量 {self._settings.api_key_env}。"
            )
            return

        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"

        content: list[dict] = [{"type": "text", "text": self._prompt}]
        if self._image_path is not None and self._image_path.exists():
            mime = mimetypes.guess_type(self._image_path.name)[0] or "image/png"
            encoded = base64.b64encode(self._image_path.read_bytes()).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                }
            )
        payload = {
            "model": self._model,
            "stream": True,
            "messages": [{"role": "user", "content": content}],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        client = httpx.Client(timeout=self._settings.timeout_seconds)
        with self._client_lock:
            self._client = client
        try:
            with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", errors="replace")[:1000]
                    self.failed.emit(
                        f"API 请求失败（HTTP {response.status_code}）：{detail}"
                    )
                    return
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type.lower():
                    raw = response.read().decode("utf-8", errors="replace")
                    self._handle_non_stream(raw)
                    return

                answer_parts: list[str] = []
                for line in response.iter_lines():
                    if self._cancel_requested.is_set():
                        self.canceled.emit()
                        return
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                    elif line.startswith("{"):
                        data = line
                    else:
                        continue
                    update = parse_sse_data(data)
                    if update is None:
                        continue
                    kind, text = update
                    if kind == "done":
                        break
                    if kind == "error":
                        self.failed.emit(text)
                        return
                    if kind == "delta":
                        answer_parts.append(text)
                        self.stream_text.emit(text)
                    elif kind == "full":
                        answer_parts = [text]
                        self.stream_text.emit(text)

                if self._cancel_requested.is_set():
                    self.canceled.emit()
                    return
                answer = "".join(answer_parts).strip()
                if not answer:
                    self.failed.emit("API 未返回回答内容。")
                    return
                self.succeeded.emit(
                    TurnResult(
                        answer=answer,
                        session_id=None,
                        session_title="API 单轮会话",
                        started_new_session=False,
                    )
                )
        except httpx.TimeoutException:
            if self._cancel_requested.is_set():
                self.canceled.emit()
            else:
                self.failed.emit(
                    f"API 请求超时（{self._settings.timeout_seconds} 秒）。"
                )
        except httpx.HTTPError as exc:
            if self._cancel_requested.is_set():
                self.canceled.emit()
            else:
                self.failed.emit(f"API 请求失败：{exc}")
        except OSError as exc:
            self.failed.emit(f"读取图片失败：{exc}")
        except Exception as exc:
            if self._cancel_requested.is_set():
                self.canceled.emit()
            else:
                self.failed.emit(f"API 请求失败：{exc}")
        finally:
            with self._client_lock:
                self._client = None
            client.close()

    def _handle_non_stream(self, raw: str) -> None:
        try:
            obj = json.loads(raw)
            choices = obj.get("choices")
            text = ""
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                text = _content_text((choices[0].get("message") or {}).get("content"))
        except json.JSONDecodeError:
            text = ""
        if not text:
            self.failed.emit("API 返回内容无法解析。")
            return
        self.stream_text.emit(text)
        self.succeeded.emit(
            TurnResult(
                answer=text,
                session_id=None,
                session_title="API 单轮会话",
                started_new_session=False,
            )
        )

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._client_lock:
            client = self._client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
