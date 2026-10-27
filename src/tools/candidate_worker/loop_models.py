"""Bounded finite-loop receipt and operation-bound graceful Stop marker."""

from typing import TYPE_CHECKING

from pydantic import Field

if TYPE_CHECKING:
    from .models import CandidateRunRequest

from tools.workflow_preview.models import PreviewModel


class LoopTrace(PreviewModel):
    """Body receipts live in managed iteration slots, not an unbounded root array."""

    attempted_iterations: int = Field(ge=0)


class LoopStop(PreviewModel):
    run_id: str
    declaration_digest: str


def admit_loop(request: "CandidateRunRequest") -> None:
    from workflows.definition.fanout import execution_families

    definition = request.preview.document.definition
    loop = definition.loop
    assert loop is not None
    shape = execution_families(definition, request.preview.execution_profile)
    if (
        request.preview.execution_profile != "native-interpretation-candidate/v1"
        or shape.interpretation is None
        or shape.tuning is None
        or loop.feedback.source.node != shape.tuning
        or loop.feedback.target != shape.interpretation.interpretation
    ):
        raise ValueError("finite loop requires the declared native interpretation-to-tuning body")
