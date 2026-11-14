from __future__ import annotations

from screen_to_agent.application.interaction_state import (
    InteractionState,
    InteractionStateMachine,
)


def test_can_start_capture_only_when_idle() -> None:
    machine = InteractionStateMachine()
    assert machine.can_start_capture()

    for state in (
        InteractionState.CAPTURING,
        InteractionState.ANNOTATING,
        InteractionState.GENERATING,
    ):
        machine.set_state(state)
        assert not machine.can_start_capture()

    machine.set_state(InteractionState.IDLE)
    assert machine.can_start_capture()
