from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from screen_to_agent.infrastructure.attachments import (
    AttachmentStore,
    resolve_attachments_dir,
)


def test_save_is_content_addressed() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = AttachmentStore(root=Path(temp_dir))
        first = store.save_png(b"same-bytes")
        second = store.save_png(b"same-bytes")

        assert first.path == second.path
        assert Path(first.path).read_bytes() == b"same-bytes"
        assert len(list(Path(temp_dir).iterdir())) == 1


def test_prune_old_files() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = AttachmentStore(root=Path(temp_dir))
        kept = store.save_png(b"new")
        old = store.save_png(b"old")
        old_path = Path(old.path)
        old_time = time.time() - 40 * 86400
        os.utime(old_path, (old_time, old_time))

        removed = store.prune(max_age_days=30)

        assert removed == 1
        assert not old_path.exists()
        assert Path(kept.path).exists()


def test_resolve_custom_storage_root() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "custom root"
        attachments = resolve_attachments_dir(str(root))
        assert attachments == root / "attachments"
        assert attachments.is_dir()


def test_resolve_rejects_relative_path() -> None:
    import pytest

    with pytest.raises(ValueError):
        resolve_attachments_dir("relative/path")
