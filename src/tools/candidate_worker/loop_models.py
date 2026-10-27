"""Bounded finite-loop receipt and operation-bound graceful Stop marker."""

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field

if TYPE_CHECKING:
    from .models import CandidateRunRequest

from tools.workflow_preview.models import PreviewModel

from .loop_stop import StopReason


class LoopTrace(PreviewModel):
    """Body receipts live in managed iteration slots, not an unbounded root array."""

    attempted_iterations: int = Field(ge=0)
    segment_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    # Present only when a declared stop condition completed the loop before its limit.
    stop_reason: StopReason | None = Field(default=None, exclude_if=lambda value: value is None)


class LoopStop(PreviewModel):
    run_id: str
    declaration_digest: str


class LoopPause(LoopStop):
    segment_id: UUID | None = None


class LoopContinuation(LoopStop):
    """Immutable successor reservation, bound to one completed paused segment."""

    operation_id: UUID
    predecessor_segment: UUID | None
    predecessor_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_iterations: int = Field(gt=0)


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
