"""Typed evidence and admission authority for bounded inference observations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.preflight import StaticPhaseDecision, StaticPreflightEvidence
from core.runtime_control.gpu_measurement_runner import PrephaseMeasurementRun
from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
from core.runtime_control.inference_measurement_assessment import (
    Disposition,
    assess_inference_measurement,
)
from core.runtime_control.inference_measurement_binding import InferenceMeasurementBinding


def eligible_inference_refusal(evidence: StaticPreflightEvidence) -> StaticPhaseDecision | None:
    """Only the final inference VRAM refusal after a passing training check."""
    if tuple(phase.phase for phase in evidence.phases) != ("training", "inference"):
        return None
    training, inference = evidence.phases
    if training.binding_caps or inference.binding_caps != ("vram",):
        return None
    return inference


class InferenceVerification(BaseModel):
    """Compact replayable decision evidence; raw samples remain in the workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["bounded-inference-v1"] = "bounded-inference-v1"
    static_evidence: StaticPreflightEvidence
    max_batches: int = Field(gt=0)
    request: CandidateMeasurementRequest | None = None
    binding: InferenceMeasurementBinding | None = None
    measurement: PrephaseMeasurementRun | None = None
    raw_evidence_path: str | None = None
    unavailable_reason: str = ""

    @model_validator(mode="after")
    def _must_describe_an_eligible_refusal(self):
        if eligible_inference_refusal(self.static_evidence) is None:
            raise ValueError("Bounded inference verification cannot clear this static refusal")
        return self

    @property
    def assessment(self) -> tuple[Disposition, str]:
        phase = eligible_inference_refusal(self.static_evidence)
        assert phase is not None
        result = assess_inference_measurement(
            request=self.request,
            binding=self.binding,
            run=self.measurement,
            batch_size=phase.batch_size,
            max_batches=self.max_batches,
            cap_mib=phase.vram_cap_bytes // 1024**2,
            unavailable_reason=self.unavailable_reason,
        )
        return result.disposition, result.detail
