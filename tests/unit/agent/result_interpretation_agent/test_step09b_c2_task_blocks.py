"""Generic interpretation task-block declaration contract."""

from pathlib import Path

import pytest

from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks


def test_omitted_declaration_is_an_empty_typed_value() -> None:
    assert load_interpretation_task_blocks().model_dump(exclude_none=True) == {}


def test_explicit_declaration_is_loaded_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "interpretation.yaml"
    path.write_text("evidence_reading: Use the declared measurement units.\n")
    assert load_interpretation_task_blocks(str(path)).evidence_reading.startswith("Use")


@pytest.mark.parametrize("text", ["- not-a-mapping\n", "unknown_section: nope\n"])
def test_invalid_explicit_declaration_fails_closed(tmp_path: Path, text: str) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_interpretation_task_blocks(str(path))


def test_missing_explicit_declaration_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_interpretation_task_blocks(str(tmp_path / "missing.yaml"))
