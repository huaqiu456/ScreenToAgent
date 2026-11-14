from __future__ import annotations

from screen_to_agent.infrastructure.codex_backend import parse_codex_stream_line


def test_parse_codex_agent_delta() -> None:
    line = '{"type":"item/agentMessage/delta","delta":"你"}'
    assert parse_codex_stream_line(line) == ("delta", "你")


def test_parse_codex_completed_item() -> None:
    line = (
        '{"type":"item.completed","item":'
        '{"type":"agent_message","content":[{"type":"text","text":"完整回答"}]}}'
    )
    assert parse_codex_stream_line(line) == ("final", "完整回答")


def test_parse_codex_updated_item() -> None:
    line = (
        '{"type":"item.updated","item":'
        '{"type":"agent_message","text":"部分回答"}}'
    )
    assert parse_codex_stream_line(line) == ("snapshot", "部分回答")


def test_parse_codex_turn_completed_and_error() -> None:
    line = '{"type":"turn.completed","last_agent_message":"结束回答"}'
    assert parse_codex_stream_line(line) == ("final", "结束回答")

    kind, message = parse_codex_stream_line('{"type":"error","message":"出错了"}')
    assert kind == "error"
    assert "出错" in message


def test_parse_ignores_non_agent_events() -> None:
    assert parse_codex_stream_line('{"type":"item.completed","item":{"type":"Reasoning"}}') is None
    assert parse_codex_stream_line("not-json") is None
