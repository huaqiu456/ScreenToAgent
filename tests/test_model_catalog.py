from __future__ import annotations

from screen_to_agent.infrastructure.model_catalog import parse_model_catalog


def test_parse_model_catalog() -> None:
    models = parse_model_catalog(
        '{"models":['
        '{"slug":"a","display_name":"Model A","input_modalities":["text","image"]},'
        '{"slug":"b","display_name":"Model B","input_modalities":["text"]},'
        '{"slug":"","display_name":"ignored"}'
        "]}"
    )

    assert [model.slug for model in models] == ["a", "b"]
    assert models[0].display_name == "Model A"
    assert models[0].supports_image
    assert not models[1].supports_image


def test_parse_empty_catalog() -> None:
    assert parse_model_catalog('{"models":[]}') == []
