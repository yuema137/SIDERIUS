"""Uncomposed task guidance is task-neutral after externalization."""

from agent.prompt_templates.implementor.task_blocks import load_implementor_task_blocks
from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks
from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks


def test_uncomposed_guidance_loaders_are_empty_and_typed() -> None:
    assert load_proposal_task_blocks().model_dump(exclude_none=True) == {}
    assert load_implementor_task_blocks().model_dump(exclude_none=True) == {}
    assert load_interpretation_task_blocks().model_dump(exclude_none=True) == {}
