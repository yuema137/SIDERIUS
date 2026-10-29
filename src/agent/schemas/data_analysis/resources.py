"""Sampling and resource contracts for analysis planning and execution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, SerializerFunctionWrapHandler, field_serializer, model_validator

from core.seeding import RunSeed

from .common import CertifiedArtifactRef, FrozenModel, NonEmptyStr, Sha256


class SamplingPolicy(FrozenModel):
    mode: Literal["full_if_feasible", "representative", "fixed"] = "representative"
    max_items: int | None = Field(default=None, gt=0)
    fraction: float | None = Field(default=None, gt=0.0, le=1.0)
    strategy: Literal["uniform", "stratified", "task_defined"] = "uniform"
    strata_fields: tuple[NonEmptyStr, ...] = ()
    seed: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_sampling(self) -> SamplingPolicy:
        if len(set(self.strata_fields)) != len(self.strata_fields):
            raise ValueError("sampling strata_fields must be unique")
        if self.strategy == "stratified" and not self.strata_fields:
            raise ValueError("stratified sampling requires strata_fields")
        if self.strategy != "stratified" and self.strata_fields:
            raise ValueError("strata_fields are valid only for stratified sampling")
        if self.mode == "fixed" and self.max_items is None and self.fraction is None:
            raise ValueError("fixed sampling requires max_items or fraction")
        return self


class CertifiedSelectionIdentity(FrozenModel):
    """Content identity of the one row-aligned selection shared by an invocation."""

    selection_id: NonEmptyStr
    selection_sha256: Sha256
    sampling_policy_sha256: Sha256
    sampling_mode: Literal["full_if_feasible", "representative", "fixed"]
    sampling_strategy: Literal["uniform", "stratified", "task_defined"]
    sampling_seed: int = Field(ge=0)
    population_unit: NonEmptyStr
    total_available: int | None = Field(default=None, ge=0)
    selected_count: int = Field(ge=0)
    selection_artifact_ref: CertifiedArtifactRef | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> CertifiedSelectionIdentity:
        if self.total_available is not None and self.selected_count > self.total_available:
            raise ValueError("selected_count cannot exceed total_available")
        if (
            self.selection_artifact_ref is not None
            and self.selection_artifact_ref.sha256 != self.selection_sha256
        ):
            raise ValueError("selection artifact digest must equal selection identity digest")
        return self


class AnalysisResourceEnvelope(FrozenModel):
    wall_time_budget_s: float = Field(gt=0.0)
    per_skill_timeout_s: float = Field(gt=0.0)
    max_vram_gb: float | None = Field(default=None, gt=0.0)
    preferred_device: Literal["cpu", "gpu", "either"] = "either"
    max_host_memory_gb: float | None = Field(default=None, gt=0.0)
    sampling_policy: SamplingPolicy = Field(default_factory=SamplingPolicy)

    @model_validator(mode="after")
    def validate_deadlines(self) -> AnalysisResourceEnvelope:
        if self.per_skill_timeout_s > self.wall_time_budget_s:
            raise ValueError("per_skill_timeout_s cannot exceed wall_time_budget_s")
        return self

    @field_serializer("sampling_policy", mode="wrap")
    def _omit_undeclared_seed(
        self, value: SamplingPolicy, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Serialize ``seed`` only when the operator declared it (issue #983).

        An undeclared seed is derived from the run seed at execution, so the
        schema default ``0`` never ran and is not written; omitting it also
        keeps the declaration explicit across dump/validate round trips.
        """
        dumped = handler(value)
        if "seed" not in value.model_fields_set:
            dumped.pop("seed", None)
        return dumped

    def declared_sampling_seed(self) -> int | None:
        """The operator-declared sampling seed, or ``None`` when it is derived."""
        policy = self.sampling_policy
        return policy.seed if "seed" in policy.model_fields_set else None


class ResourceUsage(FrozenModel):
    wall_time_s: float = Field(ge=0.0)
    cpu_time_s: float | None = Field(default=None, ge=0.0)
    peak_rss_bytes: int | None = Field(default=None, ge=0)
    peak_vram_bytes: int | None = Field(default=None, ge=0)
    device: NonEmptyStr
    measurement_limitations: tuple[str, ...] = ()


class InvocationSamplingSeed(FrozenModel):
    """The sampling seed one analysis invocation executed (issue #983).

    Framework-owned provenance written by the analysis run store; never
    rendered into a prompt or passed to a skill or generated program.
    """

    invocation_id: NonEmptyStr
    sampling_seed: int = Field(ge=0)
    sampling_seed_source: Literal["declared", "derived"]
    #: The plan's own seed, replaced by the derived one; absent when declared.
    llm_plan_seed_ignored: int | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_source(self) -> InvocationSamplingSeed:
        if (self.sampling_seed_source == "declared") != (self.llm_plan_seed_ignored is None):
            raise ValueError("only a derived sampling seed replaces a plan seed")
        return self


class AnalysisSamplingSeeds(FrozenModel):
    """Every invocation's executed sampling seed and the run seed it derives from."""

    run_seed: RunSeed
    derivation: Literal["siderius-seed/v1"] = "siderius-seed/v1"
    invocations: tuple[InvocationSamplingSeed, ...]
