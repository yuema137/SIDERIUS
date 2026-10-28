"""Closed settings admission for a fresh native candidate operation.

Defaults are direct ``WorkflowLaunchConfig`` / ``run_workflow`` defaults, not
CLI host-profile resolution. Inactive defaults are carrier placeholders, not
instructions to execute omitted history, retries or analysis phases.
"""

import json
from dataclasses import fields
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.ordering import OrderStrategy
from agent.schemas.proposal import ProposalInput
from core.retired_seed_pins import RetiredSeedPins, split_retired_seed_pins
from core.runtime_control.validation_limits import validate_phase_deadline
from execute_tools.dataset_config import DataScope
from workflows.run_config import WorkflowLaunchConfig, validate_launch_admission

SUPPORTED_LAUNCH_FIELDS = frozenset(
    {
        "allow_extreme_steps",
        "allowed_output_types",
        "attempts_per_formal_round",
        "attempts_per_round",
        "baseline_isolation",
        "bypass_formal_time_budget_min_delta",
        "bypass_formal_time_budget_minutes",
        "cleanup_denoised",
        "degenerate_penalty_score",
        "disclose_execution_constraints",
        "eval_portion",
        "experiment_arm",
        "file_index",
        "force_formal_round",
        "formal_eval_portion",
        "formal_max_epochs",
        "formal_portion",
        "formal_round_strategy",
        "formal_strategy",
        "formal_time_admission_source",
        "formal_time_budget_minutes",
        "formal_train_portion",
        "formal_training_scope_source",
        "formal_vram_budget_gb",
        "gpu_admission_enforcement",
        "gpu_admission_measurement_source",
        "gpu_execution_policy",
        "gpu_pair_ceiling_gib",
        "health_feedback_history_max_entries_per_model",
        "health_feedback_history_window_iterations",
        "healthgate_mode",
        "human_advice_tune",
        "is_trial",
        "max_epochs",
        "max_fail_rounds",
        "max_rounds",
        "max_steps_per_attempt",
        "min_formal_batch_size",
        "result_authority",
        "retain_model_outputs",
        "retain_training_checkpoints",
        "runtime_completion_policy",
        "runtime_formal_safety_factor",
        "runtime_safety_factor",
        "runtime_trial_safety_factor",
        "runtime_verification_max_wall_seconds",
        "runtime_verifier",
        "runtime_verifier_identity",
        "runtime_watchdog_deadline_policy",
        "runtime_watchdog_enabled",
        "runtime_watchdog_floor_seconds",
        "runtime_watchdog_safety_factor",
        "skip_formal_min_delta",
        "train_portion",
        "train_validation_align",
        "training_validation_portion",
        "trial_max_epochs",
        "trial_portion",
        "trial_time_admission_source",
        "trial_time_budget_minutes",
        "trial_vram_budget_gb",
        "validation_max_phase_seconds",
        "validation_max_portion",
        "validation_max_samples",
        "validation_max_train_samples",
        "vram_preflight_host_memory_limit_gb",
        "vram_preflight_total_timeout_seconds",
        "vram_probe_step_timeout_seconds",
        "workflow_parameter_rules",
    }
)

INACTIVE_LAUNCH_FIELDS = frozenset(
    {
        "advice_path",
        "advice_sha256",
        "analysis_source_prompt",
        "data_analysis_enabled",
        "debug_dump_prompts",
        "enable_chain_incumbent_formal_gates",
        "exploration_mode",
        "human_advice_analysis",
        "human_advice_implement",
        "human_advice_interpret",
        "human_advice_mindset",
        "human_advice_propose",
        "human_advice_validate",
        "lit_review_config_path",
        "lit_review_enabled",
        "max_impl_attempts",
        "max_iterations",
        "max_proposal_attempts",
        "minimum_boldness",
        "model_types",
        "n_candidates",
        "plan_overrides",
        # Issue #983 (M3): a candidate graph's seed authority is its run request.
        "run_seed",
        "scientific_evidence_order",
        "source_paths",
        "source_run_name",
        "start_iteration",
        "target_score",
        "training_budget_reserve_fraction",
        "validation_fixed_candidate_plan",
    }
)

MANAGED_LAUNCH_FIELDS = frozenset(
    {
        "data_dir",
        "require_probe_runner",
    }
)


class CandidateTrainingSettings(BaseModel):
    """Child-validated native launch and the seven run-level startup controls."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    launch: WorkflowLaunchConfig = Field(default_factory=WorkflowLaunchConfig)
    # These seven defaults follow run_workflow's public startup signature.
    data_scope: DataScope | None = None
    health_gate_enabled: bool = True
    health_gate_files: list[int] | None = None
    health_checks_config: str | None = None
    order_strategy_override: OrderStrategy | None = None
    file_order_override: list[int] | None = None
    enable_structured_health_feedback: bool = False
    # Issue #983 — readback only: set pins of a pre-retirement settings
    # document, kept as provenance; training admission refuses to execute them.
    retired_seed_pins: RetiredSeedPins | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_retired_seed_pins(cls, data: Any) -> Any:
        """Readback: lift retired launch pins out of ``launch`` (null pins drop)."""
        if not isinstance(data, dict) or not isinstance(data.get("launch"), dict):
            return data
        launch = split_retired_seed_pins(data["launch"])
        assert isinstance(launch, dict)
        pins = launch.pop("retired_seed_pins", None)
        return {**data, "launch": launch, **({"retired_seed_pins": pins} if pins else {})}

    @model_validator(mode="after")
    def validate_admitted_controls(self) -> Self:
        groups = (SUPPORTED_LAUNCH_FIELDS, INACTIVE_LAUNCH_FIELDS, MANAGED_LAUNCH_FIELDS)
        classified = set().union(*groups)
        if sum(map(len, groups)) != len(classified) or classified != {
            f.name for f in fields(WorkflowLaunchConfig)
        }:
            raise ValueError("native training launch field classification requires review")
        defaults = WorkflowLaunchConfig()
        unsupported = sorted(
            name
            for name in INACTIVE_LAUNCH_FIELDS
            if getattr(self.launch, name) != getattr(defaults, name)
        )
        if unsupported:
            raise ValueError(f"unsupported fresh training controls: {unsupported}")
        for name in SUPPORTED_LAUNCH_FIELDS:
            value = getattr(self.launch, name)
            # Native transit portions resolve None later; optionality is retained.
            if value is not None and name in HyperparamTuningInput.model_fields:
                annotation = HyperparamTuningInput.model_fields[name].rebuild_annotation()
                TypeAdapter(annotation).validate_python(value)
        for name in type(self).model_fields.keys() & HyperparamTuningInput.model_fields.keys():
            value = getattr(self, name)
            if value is not None:
                TypeAdapter(
                    HyperparamTuningInput.model_fields[name].rebuild_annotation()
                ).validate_python(value)
        for value in (self.launch.trial_vram_budget_gb, self.launch.formal_vram_budget_gb):
            TypeAdapter(
                ProposalInput.model_fields["vram_budget_gb"].rebuild_annotation()
            ).validate_python(value)
        validate_launch_admission(self.launch)
        validate_phase_deadline(
            self.launch.validation_max_phase_seconds,
            watchdog_enabled=self.launch.runtime_watchdog_enabled,
        )
        return self


def parse_training_settings(payload: str | bytes) -> CandidateTrainingSettings:
    """Validate inert ingress, preserving omission of the managed probe requirement."""
    settings = CandidateTrainingSettings.model_validate_json(payload)
    if (
        "require_probe_runner" in json.loads(payload).get("launch", {})
        and not settings.launch.require_probe_runner
    ):
        raise ValueError("require_probe_runner cannot be disabled for native training")
    return settings


def proposal_training_values(settings: CandidateTrainingSettings) -> dict[str, object]:
    """Preparation-known native proposal facts; hardware/disclosure stay runtime-owned."""
    from agent.utils.proposer_preflight import (
        UNCONSTRAINED_TRAIN_PORTION,
        UNCONSTRAINED_TRIAL_PORTION,
    )
    from workflows.run_config import active_vram_budget

    launch = settings.launch
    values = {
        name: getattr(launch, name)
        for name in (
            "trial_time_budget_minutes",
            "formal_time_budget_minutes",
            "workflow_parameter_rules",
            "is_trial",
            "allowed_output_types",
            "baseline_isolation",
        )
    }
    values.update(
        data_scope=settings.data_scope if settings.data_scope is not None else DataScope.default(),
        trial_portion=UNCONSTRAINED_TRIAL_PORTION
        if launch.trial_portion is None
        else launch.trial_portion,
        train_portion=UNCONSTRAINED_TRAIN_PORTION
        if launch.train_portion is None
        else launch.train_portion,
        enable_structured_health_feedback=settings.enable_structured_health_feedback,
        vram_budget_gb=active_vram_budget(launch),
    )
    return values


def effective_training_settings(
    authored: dict[str, JsonValue], allowed_output_types: tuple[str, ...] | None
) -> bytes:
    """Bind preparation-owned output selection while retaining every authored presence."""
    settings = parse_training_settings(json.dumps(authored, allow_nan=False))
    # Copy through JSON so nested authored state is never mutated.
    value = json.loads(json.dumps(authored, allow_nan=False))
    launch = value.setdefault("launch", {})
    if (
        "allowed_output_types" in launch
        and settings.launch.allowed_output_types != allowed_output_types
    ):
        raise ValueError("training allowed_output_types disagrees with preparation options")
    launch.setdefault("allowed_output_types", allowed_output_types)
    payload = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    parse_training_settings(payload)
    return payload


def reconcile_constraints(
    actual: ConstraintContext | None, expected: ConstraintContext | None
) -> None:
    """Accept incomplete evidence, but refuse each already known conflicting section."""
    if actual is None:
        return
    if expected is None:
        raise ValueError("constraint_context conflicts with disabled disclosure")
    for name in type(actual).model_fields:
        if name == "known_sections":
            continue
        value = getattr(actual, name)
        if (name in actual.known_sections or value is not None) and value != getattr(
            expected, name
        ):
            raise ValueError(f"constraint_context.{name} disagrees with native training")
