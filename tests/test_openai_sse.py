from __future__ import annotations

from screen_to_agent.infrastructure.openai_backend import parse_sse_data


def test_parse_sse_delta() -> None:
    data = (
        '{"choices":[{"delta":{"content":"你"}}]}'
    )
    assert parse_sse_data(data) == ("delta", "你")


def test_parse_sse_done_and_error() -> None:
    assert parse_sse_data("[DONE]") == ("done", "")
    kind, message = parse_sse_data('{"error":{"message":"bad key"}}')
    assert kind == "error"
    assert "bad key" in message


def test_parse_sse_full_message() -> None:
    data = '{"choices":[{"message":{"content":"完整回答"}}]}'
    assert parse_sse_data(data) == ("full", "完整回答")
