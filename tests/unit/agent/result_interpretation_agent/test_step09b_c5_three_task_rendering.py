"""Interpretation task-block values remain task-neutral and optional."""

from agent.schemas.interpretation import InterpretationTaskBlocks


def test_each_declared_section_is_independent() -> None:
    blocks = InterpretationTaskBlocks(
        evidence_reading="Read the declared metric.",
        synthesis_guidance="Compare candidates in the declared direction.",
    )
    assert blocks.evidence_reading.startswith("Read")
    assert blocks.synthesis_guidance.startswith("Compare")
    assert blocks.per_model_guidance is None


def test_absent_task_guidance_is_a_named_empty_value() -> None:
    assert InterpretationTaskBlocks().model_dump(exclude_none=True) == {}
