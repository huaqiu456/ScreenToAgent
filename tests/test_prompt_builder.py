from __future__ import annotations

from screen_to_agent.application.prompt_builder import DEFAULT_QUESTION, build_prompt


def test_uses_annotation_text_without_history() -> None:
    assert build_prompt("  这个错误怎么修？  ") == "这个错误怎么修？"


def test_falls_back_to_default_question() -> None:
    assert build_prompt("   ") == DEFAULT_QUESTION
