"""Domain models for ScreenToAgent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Capture:
    png_bytes: bytes
    width: int
    height: int
    origin_x: int = 0
    origin_y: int = 0


@dataclass(frozen=True)
class AttachmentRef:
    path: str
    mime: str = "image/png"
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant", "system"]
    text: str
    is_error: bool = False
    attachments: tuple[AttachmentRef, ...] = ()


@dataclass(frozen=True)
class ModelInfo:
    slug: str
    display_name: str
    supports_image: bool = True


@dataclass(frozen=True)
class SessionInfo:
    id: str
    title: str
    cwd: str = ""
    updated_at: str = ""
    path: str = ""


@dataclass(frozen=True)
class TurnResult:
    answer: str
    session_id: str | None = None
    session_title: str | None = None
    started_new_session: bool = False
