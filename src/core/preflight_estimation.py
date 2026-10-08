"""Versioned arithmetic providers for structural preflight observations.

The framework retains probing, budgets, batch search and failure attribution.
Installed providers are trusted code; their declared sources and the framework
observation/decision assembly are pinned before execution.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
from importlib.metadata import entry_points
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from core.planner_strategy_identity import source_fingerprint
from core.preflight_observations import PhaseEstimate, PhaseObservations

NATIVE_ESTIMATOR = "registered-state-v1"


class PreflightEstimatorIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assembly_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def estimation_assembly_digest() -> str:
    """Bind observation production, transport and decision consumption."""
    root = Path(__file__).resolve().parents[1]
    paths = list((root / "agent/skills/evaluate_vram_skill").glob("*.py"))
    paths += list((root / "ml_models").rglob("*.py"))
    paths += [
        root / name
        for name in (
            "core/preflight_observations.py",
            "core/runtime_control/gpu_measurement_hold.py",
            "core/inference_preflight_policy.py",
            "core/runtime_control/inference_measurement_binding.py",
            "core/runtime_control/training_measurement_binding.py",
            "core/runtime_control/training_measurement_assessment.py",
            "core/runtime_control/training_measurement_lifecycle.py",
            "core/runtime_control/training_measurement_steps.py",
            "core/runtime_control/gpu_training_components.py",
            "core/runtime_control/measurement_hold_assessment.py",
            "core/target_standardization.py",
            "execute_tools/target_standardization.py",
            "core/runtime_control/inference_refusal_verification.py",
            "core/runtime_control/inference_verification_evidence.py",
            "core/runtime_control/inference_measurement_assessment.py",
            "core/runtime_control/inference_checkpoint_reference.py",
            "core/stream_identity.py",
            "core/file_identity.py",
            "execute_tools/inference_checkpoint.py",
            "core/runtime_control/gpu_inference_components.py",
            "core/runtime_control/gpu_measurement_spec.py",
            "core/runtime_control/gpu_measurement_identity.py",
            "core/runtime_control/gpu_measurement_worker_main.py",
            "core/runtime_control/gpu_measurement_phases.py",
            "core/runtime_control/gpu_measurement_runner.py",
            "core/runtime_control/gpu_measurement_sampler.py",
            "core/runtime_control/gpu_measurement_classifier.py",
            "core/runtime_control/gpu_requirement.py",
            "core/runtime_control/gpu_requirement_evidence.py",
            "core/runtime_control/admission.py",
            "core/runtime_control/isolated_admission.py",
            "core/runtime_control/prephase_admission.py",
            "core/runtime_control/pair_admission.py",
            "core/runtime_control/gpu_accounting.py",
            "core/runtime_control/process_group.py",
            "core/subprocess_env.py",
            "execute_tools/inference_model.py",
            "execute_tools/inference_stream.py",
            "execute_tools/inference_forward.py",
            "execute_tools/model_input_dtype.py",
            "execute_tools/generic_inference.py",
            "execute_tools/inference_single.py",
            "ml_models/plugin_loader.py",
            "ml_models/loss_plugin_loader.py",
            "nodes/ml_hyperparameter_tune_agent/execution.py",
            "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
            "nodes/ml_hyperparameter_tune_agent/runtime.py",
            "nodes/ml_hyperparameter_tune_agent/feedback.py",
            "agent/schemas/hyperparam_tuning.py",
            "workflows/model_exploration.py",
            "workflows/task_settings.py",
            "core/preflight_estimation.py",
            "core/planner_strategy_identity.py",
            "agent/schemas/preflight.py",
            "workflows/task_composition.py",
            "execute_tools/task_probe_batch.py",
            "execute_tools/train_engine_sandbox.py",
            "ml_models/models_format_sandbox.py",
        )
    ]
    return source_fingerprint({str(p.relative_to(root)): p.read_bytes() for p in paths})


@dataclass(frozen=True)
class PreflightEstimatorProfile:
    """One installed, source-pinned arithmetic function.

    External providers declare the assemblies they have qualified. Installation
    alone never selects a provider. A manifest must select it explicitly.
    """

    name: str
    version: str
    estimate: Callable[[PhaseObservations], PhaseEstimate]
    sources: Mapping[str, Path]
    qualified_assemblies: frozenset[str]

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("A preflight estimator must declare its source files")
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))
        object.__setattr__(self, "qualified_assemblies", frozenset(self.qualified_assemblies))

    def identity(self) -> PreflightEstimatorIdentity:
        assembly = estimation_assembly_digest()
        if assembly not in self.qualified_assemblies:
            raise ValueError(f"Preflight estimator {self.name!r} has not qualified this assembly")
        return PreflightEstimatorIdentity(
            name=self.name,
            version=self.version,
            content_sha256=source_fingerprint({k: p.read_bytes() for k, p in self.sources.items()}),
            assembly_sha256=assembly,
        )


def _native_estimate(observations: PhaseObservations) -> PhaseEstimate:
    # Keep parent-side provider discovery torch-free.
    from agent.skills.evaluate_vram_skill.native_estimation import estimate_native_phase

    return estimate_native_phase(observations)


def resolve_preflight_estimator(selection: str | None = None) -> PreflightEstimatorProfile:
    if selection is None or selection == NATIVE_ESTIMATOR:
        root = Path(__file__).resolve().parents[1]
        paths = [
            root / "agent/skills/evaluate_vram_skill" / name
            for name in (
                "native_estimation.py",
                "registered_state.py",
                "overhead.py",
            )
        ]
        return PreflightEstimatorProfile(
            name=NATIVE_ESTIMATOR,
            version="1",
            estimate=_native_estimate,
            sources={str(p.relative_to(root)): p for p in paths},
            qualified_assemblies=frozenset({estimation_assembly_digest()}),
        )
    matches = [
        e for e in entry_points(group="siderius.preflight_estimators") if e.name == selection
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one installed preflight estimator {selection!r}; found {len(matches)}"
        )
    profile = matches[0].load()()
    if not isinstance(profile, PreflightEstimatorProfile) or profile.name != selection:
        raise TypeError("Preflight estimator factory must return the selected profile")
    profile.identity()
    return profile


_active: ContextVar[tuple[PreflightEstimatorProfile, PreflightEstimatorIdentity] | None] = (
    ContextVar("preflight_estimator", default=None)
)


def active_preflight_identity() -> PreflightEstimatorIdentity:
    binding = _active.get()
    if binding is None:
        return resolve_preflight_estimator().identity()
    profile, identity = binding
    if profile.identity() != identity:
        raise ValueError("Preflight estimator changed during the run")
    return identity


@contextmanager
def bind_preflight_estimator(
    profile: PreflightEstimatorProfile,
    *,
    expected: PreflightEstimatorIdentity | None = None,
) -> Iterator[None]:
    identity = profile.identity()
    if expected is not None and identity != expected:
        raise ValueError("Preflight estimator changed after composition or worker dispatch")
    token = _active.set((profile, identity))
    try:
        yield
    finally:
        _active.reset(token)


def preflight_estimation_scope[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    """Pin one identity across a complete standalone or composed inspection."""

    @wraps(function)
    def scoped(*args: P.args, **kwargs: P.kwargs) -> T:
        if _active.get() is not None:
            active_preflight_identity()
            return function(*args, **kwargs)
        with bind_preflight_estimator(resolve_preflight_estimator()):
            return function(*args, **kwargs)

    return scoped


@preflight_estimation_scope
def estimate_phase(observations: PhaseObservations) -> PhaseEstimate:
    """Validate provider output without delegating execution control."""
    active_preflight_identity()
    binding = _active.get()
    profile = binding[0] if binding is not None else resolve_preflight_estimator()
    result = profile.estimate(deepcopy(observations))
    if not isinstance(result, PhaseEstimate):
        raise TypeError("Preflight estimator must return PhaseEstimate")
    validated = PhaseEstimate.model_validate(result.model_dump(), strict=True)
    if validated.phase != observations.phase:
        raise ValueError("Preflight estimator returned a different phase")
    active_preflight_identity()
    return validated
