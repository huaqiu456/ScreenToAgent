from __future__ import annotations

DEFAULT_QUESTION = "请分析这张截图中的内容，并给出可执行的建议。"


def build_prompt(annotation_text: str) -> str:
    text = annotation_text.strip()
    return text or DEFAULT_QUESTION
