"""Generic implementor task-block declaration contract."""

from pathlib import Path

import pytest

from agent.prompt_templates.implementor.task_blocks import load_implementor_task_blocks


def test_omitted_declaration_is_an_empty_typed_value() -> None:
    assert load_implementor_task_blocks().model_dump(exclude_none=True) == {}


def test_explicit_declaration_is_loaded(tmp_path: Path) -> None:
    path = tmp_path / "implementor.yaml"
    path.write_text("continuous_output_phrase: Return the declared tensor shape.\n")
    blocks = load_implementor_task_blocks(str(path))
    assert blocks.continuous_output_phrase.startswith("Return")


def test_missing_or_unknown_explicit_declaration_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_implementor_task_blocks(str(tmp_path / "missing.yaml"))
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("unknown_section: nope\n")
    with pytest.raises(ValueError):
        load_implementor_task_blocks(str(invalid))
