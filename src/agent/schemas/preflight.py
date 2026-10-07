"""Decision evidence from structural resource inspection, never a GPU measurement."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.preflight_estimation import PreflightEstimatorIdentity


class StaticPreflightBypass(BaseModel):
    """Explicit CPU-only skip, retaining the resolved arithmetic identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: Literal["cpu_only"] = "cpu_only"
    estimator_identity: PreflightEstimatorIdentity


class StaticPhaseDecision(BaseModel):
    """The exact values used for one phase's static admission decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: Literal["training", "inference"]
    batch_size: int = Field(gt=0)
    vram_cap_bytes: int = Field(ge=0)
    vram_estimate_bytes: int | None = Field(default=None, ge=0)
    estimator: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.-]+$"
    )
    intensity_product: int | None = Field(default=None, ge=0)
    intensity_limit: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def consistent_observations(self) -> StaticPhaseDecision:
        if (self.vram_estimate_bytes is None) != (self.estimator is None):
            raise ValueError("A structural estimate and its estimator must be supplied together")
        if (self.intensity_product is None) != (self.intensity_limit is None):
            raise ValueError("An intensity observation and its limit must be supplied together")
        if self.vram_estimate_bytes is None and self.intensity_product is None:
            raise ValueError("A static decision needs an observed estimate or intensity check")
        if self.estimator in {"training_saved_tensors_v1", "inference_leaf_sum_v1"}:
            expected = (
                "training_saved_tensors_v1" if self.phase == "training" else "inference_leaf_sum_v1"
            )
            if self.estimator != expected:
                raise ValueError("Estimator does not describe the observed phase")
        if (
            self.vram_estimate_bytes is None
            and self.intensity_product is not None
            and self.intensity_limit is not None
            and self.intensity_product <= self.intensity_limit
        ):
            raise ValueError(
                "An unobserved VRAM estimate cannot establish a passing static decision"
            )
        return self

    @property
    def binding_caps(self) -> tuple[str, ...]:
        caps = []
        if self.vram_estimate_bytes is not None and self.vram_estimate_bytes > self.vram_cap_bytes:
            caps.append("vram")
        if (
            self.intensity_product is not None
            and self.intensity_limit is not None
            and self.intensity_product > self.intensity_limit
        ):
            caps.append("compute_intensity")
        return tuple(caps)


class StaticPreflightEvidence(BaseModel):
    """Bounded, versioned evidence transported independently of diagnostic text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["static-preflight-v1", "static-preflight-v2"] = "static-preflight-v1"
    estimator_identity: PreflightEstimatorIdentity | None = None
    phases: tuple[StaticPhaseDecision, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_phases(self) -> StaticPreflightEvidence:
        if self.version == "static-preflight-v2" and self.estimator_identity is None:
            raise ValueError("Version 2 preflight evidence requires a pinned estimator identity")
        if self.version == "static-preflight-v1":
            if self.estimator_identity is not None:
                raise ValueError("Version 1 evidence cannot carry an estimator identity")
            if any(
                p.estimator not in {None, "training_saved_tensors_v1", "inference_leaf_sum_v1"}
                for p in self.phases
            ):
                raise ValueError("Version 1 evidence only describes its original estimators")
        if len({item.phase for item in self.phases}) != len(self.phases):
            raise ValueError("Static preflight evidence must contain each phase at most once")
        return self

    @property
    def binding_caps(self) -> tuple[str, ...]:
        return tuple(
            cap
            for cap in ("vram", "compute_intensity")
            if any(cap in phase.binding_caps for phase in self.phases)
        )

    @property
    def refused_phase(self) -> StaticPhaseDecision | None:
        return next((phase for phase in self.phases if phase.binding_caps), None)
