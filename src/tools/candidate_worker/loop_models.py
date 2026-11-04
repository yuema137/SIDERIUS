"""Bounded finite-loop receipt and operation-bound graceful Stop marker."""

import unicodedata
from typing import TYPE_CHECKING, Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, Field, model_validator

from workflows.definition.models import NATIVE_INTERPRETATION_PROFILE

if TYPE_CHECKING:
    from .models import CandidateRunRequest

from tools.workflow_preview.models import PreviewModel

from .loop_stop import JudgeBoundaryVerdict, LoopInputRequest, StopReason


class LoopTrace(PreviewModel):
    """Body receipts live in managed iteration slots, not an unbounded root array."""

    attempted_iterations: int = Field(ge=0)
    segment_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    # Present only when a declared stop condition completed the loop before its limit.
    stop_reason: StopReason | None = Field(default=None, exclude_if=lambda value: value is None)
    # Present only when a met ``request_input`` condition paused the loop at its last
    # attempted boundary; ``stop_reason`` keeps meaning "completed before the limit".
    input_request: LoopInputRequest | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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
        if self.input_request is not None and (
            self.stop_reason is not None
            or self.input_request.reason.iteration != self.attempted_iterations
        ):
            raise ValueError("an input request pauses the last attempted boundary, never a stop")
        return self


MAX_OPERATOR_ADVICE_CHARS = 4000


def _operator_advice(value: str) -> str:
    text = value.strip()
    if not 1 <= len(text) <= MAX_OPERATOR_ADVICE_CHARS:
        raise ValueError(f"operator advice must be 1 to {MAX_OPERATOR_ADVICE_CHARS} characters")
    # Cc covers C0, DEL and C1 (e.g. CSI \x9b); Cf covers bidi overrides and the BOM.
    # Joiners are meaningful in multilingual words and emoji; they do not reorder text.
    if any(
        unicodedata.category(char) in ("Cc", "Cf") and char not in "\n\t\u200c\u200d"
        for char in text
    ):
        raise ValueError("operator advice may not contain control or format characters")
    return text


# Untrusted operator text given at Resume; surrounding whitespace is removed, so a
# retried request with the same text is byte-identical. Of the Cc/Cf characters, only
# newline, tab, ZWNJ (U+200C) and ZWJ (U+200D) are allowed.
OperatorAdvice = Annotated[str, AfterValidator(_operator_advice)]


class ResumeAdvice(PreviewModel):
    """Operator advice in force for one segment's bodies: given after body ``after_body``."""

    after_body: int = Field(gt=0)
    text: OperatorAdvice


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
    # Advice given at this Resume; it reaches this segment's proposals only. Omitted when
    # absent, so bindings of advice-free resumes keep their bytes.
    operator_advice: OperatorAdvice | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    def resume_advice(self) -> ResumeAdvice | None:
        """The advice this segment's bodies receive, anchored to its checkpoint."""
        if self.operator_advice is None:
            return None
        return ResumeAdvice(after_body=self.completed_iterations, text=self.operator_advice)


class LoopAdmissionRefusal(ValueError):
    """Safe, typed admission reason; no input paths or exception payloads."""

    def __init__(self, reason: Literal["profile", "shape", "feedback"]) -> None:
        self.reason = reason
        super().__init__(
            "research loops require the native-interpretation-candidate profile"
            if reason == "profile"
            else "research loops require a native interpretation-to-tuning iteration; "
            "review the workflow nodes and connections"
            if reason == "shape"
            else "research loop feedback must connect native tuning to interpretation; "
            "review the workflow connections"
        )


def admit_loop(request: "CandidateRunRequest") -> LoopAdmissionRefusal | None:
    from workflows.definition.fanout import execution_families

    definition = request.preview.document.definition
    loop = definition.loop
    assert loop is not None
    if request.preview.execution_profile != NATIVE_INTERPRETATION_PROFILE:
        return LoopAdmissionRefusal("profile")
    try:
        shape = execution_families(definition, request.preview.execution_profile)
    except ValueError:
        return LoopAdmissionRefusal("shape")
    if shape.interpretation is None or shape.tuning is None:
        return LoopAdmissionRefusal("shape")
    if (
        loop.feedback.source.node != shape.tuning
        or loop.feedback.target != shape.interpretation.interpretation
    ):
        return LoopAdmissionRefusal("feedback")
    return None


def require_loop(request: "CandidateRunRequest") -> None:
    """Raise the owner's refusal at execution and evidence boundaries."""
    refusal = admit_loop(request)
    if refusal is not None:
        raise refusal
