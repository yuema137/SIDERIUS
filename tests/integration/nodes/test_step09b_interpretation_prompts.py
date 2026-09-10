"""Task guidance reaches interpretation without an implicit scientific default."""

from pathlib import Path

from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks


def test_explicit_guidance_round_trips(tmp_path: Path) -> None:
    declaration = tmp_path / "guidance.yaml"
    declaration.write_text("evidence_reading: Compare only declared metrics.\n")
    blocks = load_interpretation_task_blocks(str(declaration))
    assert blocks.evidence_reading == "Compare only declared metrics."


def test_omitted_guidance_renders_no_task_bytes() -> None:
    assert load_interpretation_task_blocks().model_dump(exclude_none=True) == {}
