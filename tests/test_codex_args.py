from __future__ import annotations

from pathlib import Path

from screen_to_agent.infrastructure.codex_backend import build_codex_args, strip_ansi

IMAGE = Path("C:/tmp/capture.png")
OUTPUT = Path("C:/tmp/answer.txt")


def test_new_session_args() -> None:
    args = build_codex_args(
        "codex", IMAGE, OUTPUT, "这个错误怎么修？", start_new=True
    )
    assert args[:2] == ["codex", "exec"]
    assert "resume" not in args
    assert args[-1] == "这个错误怎么修？"
    assert "-i" in args and str(IMAGE) in args
    assert "-o" in args and str(OUTPUT) in args
    assert "--json" in args


def test_model_argument() -> None:
    args = build_codex_args(
        "codex",
        IMAGE,
        OUTPUT,
        "问题",
        start_new=True,
        model="gpt-6.1-sol",
    )
    index = args.index("-m")
    assert args[index + 1] == "gpt-6.1-sol"


def test_resume_explicit_session_args() -> None:
    args = build_codex_args(
        "codex",
        IMAGE,
        OUTPUT,
        "继续",
        session_id="01a1d92f-f029-70a2-a041-073d00525fea",
    )
    assert args[:3] == ["codex", "exec", "resume"]
    assert "--last" not in args
    assert "01a1d92f-f029-70a2-a041-073d00525fea" in args
    assert args[-1] == "继续"


def test_resume_last_args() -> None:
    args = build_codex_args("codex", IMAGE, OUTPUT, "继续", resume_last=True)
    assert args[:3] == ["codex", "exec", "resume"]
    assert "--last" in args
    assert args[-1] == "继续"


def test_text_only_has_no_image_argument() -> None:
    args = build_codex_args("codex", None, OUTPUT, "只问文字", start_new=True)
    assert "-i" not in args


def test_strip_ansi() -> None:
    assert strip_ansi("\x1b[31m回答\x1b[0m") == "回答"
