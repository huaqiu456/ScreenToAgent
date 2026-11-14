from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from screen_to_agent.domain.models import ModelInfo
from screen_to_agent.infrastructure.codex_backend import (
    _CREATE_NEW_PROCESS_GROUP,
    _CREATE_NO_WINDOW,
    resolve_executable,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def parse_model_catalog(text: str) -> list[ModelInfo]:
    data = json.loads(text)
    raw_models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(raw_models, list):
        return []
    models: list[ModelInfo] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue
        modalities = item.get("input_modalities")
        supports_image = True
        if isinstance(modalities, list):
            supports_image = "image" in {str(value) for value in modalities}
        models.append(
            ModelInfo(
                slug=slug,
                display_name=str(item.get("display_name") or slug).strip(),
                supports_image=supports_image,
            )
        )
    return models


class CodexModelCatalogWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, executable: str, parent=None) -> None:
        super().__init__(parent)
        self._executable = executable

    def run(self) -> None:
        try:
            executable = resolve_executable(self._executable)
            if not executable:
                self.failed.emit(f"未找到 Codex CLI：{self._executable}")
                return
            result = subprocess.run(
                [executable, "debug", "models", "--bundled"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
            )
            if result.returncode != 0:
                detail = (result.stderr or "").strip()[-500:]
                self.failed.emit(f"读取模型目录失败：{detail}")
                return
            models = parse_model_catalog(_ANSI_RE.sub("", result.stdout))
            if not models:
                self.failed.emit("模型目录为空。")
                return
            self.loaded.emit(models)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            self.failed.emit(f"读取模型目录失败：{exc}")
