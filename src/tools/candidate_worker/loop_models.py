"""Bounded finite-loop receipt and operation-bound graceful Stop marker."""

from typing import TYPE_CHECKING, Self
from uuid import UUID

from pydantic import Field, model_validator

if TYPE_CHECKING:
    from .models import CandidateRunRequest

from tools.workflow_preview.models import PreviewModel

from .loop_stop import JudgeBoundaryVerdict, StopReason


class LoopTrace(PreviewModel):
    """Body receipts live in managed iteration slots, not an unbounded root array."""

    attempted_iterations: int = Field(ge=0)
    segment_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    # Present only when a declared stop condition completed the loop before its limit.
    stop_reason: StopReason | None = Field(default=None, exclude_if=lambda value: value is None)
    # Every judged boundary's verified verdict, ``continue`` and abstentions included:
    # the evidence digest each one carries anchors that boundary's judge record.
    judge_verdicts: tuple[JudgeBoundaryVerdict, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    # Readback summary: judged boundaries whose failed call was a recorded abstention.
    judge_abstentions: int = Field(default=0, ge=0, exclude_if=lambda value: value == 0)

    @model_validator(mode="after")
    def coherent_judge_summary(self) -> Self:
        iterations = [item.iteration for item in self.judge_verdicts]
        if iterations != sorted(set(iterations)) or (
            iterations and iterations[-1] > self.attempted_iterations
        ):
            raise ValueError("judge verdicts must be increasing attempted boundaries")
        if self.judge_abstentions != sum(item.decision is None for item in self.judge_verdicts):
            raise ValueError("judge_abstentions must count the abstained judge verdicts")
        return self


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
