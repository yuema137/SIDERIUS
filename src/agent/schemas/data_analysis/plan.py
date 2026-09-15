"""Validated analysis plan between LLM output and execution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .access import RequestedInformation
from .assets import AnalysisOperation, AnalysisScopeDescriptor
from .common import FrozenModel, NonEmptyStr, Sha256
from .inference import HistoricalInferenceConfiguration
from .resources import SamplingPolicy
from .skills import CostClass


class SamplingPlan(FrozenModel):
    split_id: NonEmptyStr
    requested_scope: AnalysisScopeDescriptor = Field(discriminator="kind")
    policy: SamplingPolicy


class PlannedInferenceInputBinding(FrozenModel):
    """Plan-visible model input; never forwarded to the diagnostic skill."""

    binding_id: NonEmptyStr
    asset_id: NonEmptyStr
    requested_format_id: NonEmptyStr
    requested_information: tuple[RequestedInformation, ...]

    @model_validator(mode="after")
    def validate_information(self) -> PlannedInferenceInputBinding:
        classes = [item.information_class for item in self.requested_information]
        if not classes or len(set(classes)) != len(classes):
            raise ValueError("inference input information classes must be non-empty and unique")
        if "target" in classes:
            raise ValueError("predictor inference inputs cannot request target information")
        return self


class PlannedAssetBinding(FrozenModel):
    binding_id: NonEmptyStr
    slot_id: NonEmptyStr
    asset_id: NonEmptyStr
    operation: AnalysisOperation = "materialize"
    requested_format_id: NonEmptyStr
    requested_information: tuple[RequestedInformation, ...]
    inference_inputs: tuple[PlannedInferenceInputBinding, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    inference_configuration: HistoricalInferenceConfiguration | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_information(self) -> PlannedAssetBinding:
        classes = [item.information_class for item in self.requested_information]
        if not classes or len(set(classes)) != len(classes):
            raise ValueError("requested information classes must be non-empty and unique")
        if self.operation == "infer":
            if len(self.inference_inputs) != 1:
                raise ValueError(
                    "v1 historical inference requires exactly one explicit input binding"
                )
            if classes != ["prediction"]:
                raise ValueError("historical inference binding must request only prediction")
            if self.inference_configuration is None:
                raise ValueError("historical inference requires explicit configuration")
        elif self.inference_inputs or self.inference_configuration is not None:
            raise ValueError("inference inputs/configuration are valid only when operation='infer'")
        return self


class PlannedSkillInvocation(FrozenModel):
    invocation_id: NonEmptyStr
    skill_id: NonEmptyStr
    question_ids: tuple[NonEmptyStr, ...]
    bindings: tuple[PlannedAssetBinding, ...]
    sampling_plan: SamplingPlan
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_time_cost: CostClass
    expected_memory_cost: Literal["low", "medium", "high"]
    priority: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def validate_references(self) -> PlannedSkillInvocation:
        if not self.question_ids or len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("invocation question_ids must be non-empty and unique")
        binding_ids = [item.binding_id for item in self.bindings]
        if not binding_ids or len(set(binding_ids)) != len(binding_ids):
            raise ValueError("invocation binding IDs must be non-empty and unique")
        nested_ids = [
            nested.binding_id for binding in self.bindings for nested in binding.inference_inputs
        ]
        if set(binding_ids) & set(nested_ids) or len(set(nested_ids)) != len(nested_ids):
            raise ValueError("inference input binding IDs must be unique within the invocation")
        return self


class StopPolicy(FrozenModel):
    max_invocations: int = Field(gt=0, le=100)
    stop_when_questions_addressed: bool = True
    minimum_remaining_time_s: float = Field(default=1.0, ge=0.0)
    continue_after_skill_failure: bool = True


class AnalysisPlan(FrozenModel):
    plan_id: NonEmptyStr
    input_digest: Sha256
    access_policy_digest: Sha256
    discovery_snapshot_digest: Sha256
    questions: tuple[NonEmptyStr, ...]
    invocations: tuple[PlannedSkillInvocation, ...]
    stop_policy: StopPolicy
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_plan(self) -> AnalysisPlan:
        if not self.questions or len(set(self.questions)) != len(self.questions):
            raise ValueError("plan question IDs must be non-empty and unique")
        invocation_ids = [item.invocation_id for item in self.invocations]
        if not invocation_ids:
            raise ValueError("analysis plan requires at least one invocation")
        if len(set(invocation_ids)) != len(invocation_ids):
            raise ValueError("analysis invocation IDs must be unique")
        if len(self.invocations) > self.stop_policy.max_invocations:
            raise ValueError("plan exceeds stop_policy.max_invocations")
        declared_questions = set(self.questions)
        for invocation in self.invocations:
            if not set(invocation.question_ids).issubset(declared_questions):
                raise ValueError("invocation references a question not declared by the plan")
        return self
