from __future__ import annotations

from enum import Enum


class InteractionState(Enum):
    IDLE = "idle"
    CAPTURING = "capturing"
    ANNOTATING = "annotating"
    GENERATING = "generating"


class InteractionStateMachine:
    """Owns screenshot/generation UI state; conversation visibility is separate."""

    def __init__(self) -> None:
        self.state = InteractionState.IDLE

    def set_state(self, state: InteractionState) -> None:
        self.state = state

    def can_start_capture(self) -> bool:
        return self.state not in (
            InteractionState.CAPTURING,
            InteractionState.ANNOTATING,
            InteractionState.GENERATING,
        )
