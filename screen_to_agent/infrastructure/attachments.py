from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from screen_to_agent.config import app_data_dir
from screen_to_agent.domain.models import AttachmentRef


def default_storage_root() -> Path:
    return app_data_dir()


def resolve_attachments_dir(storage_root: str) -> Path:
    if not storage_root.strip():
        override = os.environ.get("SCREEN_TO_AGENT_ATTACHMENTS")
        if override:
            attachments = Path(override).expanduser()
        else:
            attachments = default_storage_root() / "attachments"
    else:
        base = Path(storage_root).expanduser()
        if not base.is_absolute():
            raise ValueError("存储位置必须是绝对路径。")
        if base.exists() and not base.is_dir():
            raise ValueError("存储位置不是目录。")
        attachments = base / "attachments"

    attachments.mkdir(parents=True, exist_ok=True)
    probe = attachments / ".screen-to-agent-write-test"
    probe.write_bytes(b"ok")
    probe.unlink()
    return attachments


class AttachmentStore:
    """Content-addressed local image cache for conversation display."""

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            override = os.environ.get("SCREEN_TO_AGENT_ATTACHMENTS")
            root = Path(override).expanduser() if override else app_data_dir() / "attachments"
        self.root = root

    def save_png(self, data: bytes, mime: str = "image/png") -> AttachmentRef:
        digest = hashlib.sha256(data).hexdigest()
        suffix = ".png" if "png" in mime else ".img"
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        return AttachmentRef(path=str(path), mime=mime)

    def prune(self, max_age_days: int = 30) -> int:
        if not self.root.exists():
            return 0
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for path in self.root.iterdir():
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
