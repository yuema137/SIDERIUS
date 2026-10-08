"""Source-pinned providers for incremental runtime verification.

Providers own timing evidence semantics, not data selection, execution or budgets.
An explicit selection is trusted installed code, like a preflight estimator.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from core.planner_strategy_identity import source_fingerprint
from core.runtime_control.adaptive import AdaptiveUnitVerification, AdaptiveVerificationConfig
from core.runtime_control.completion import RuntimeCompletionPolicy
from core.runtime_control.records import PhaseMeasurement, PredictionSource, RuntimePrediction
from core.runtime_control.workload import ResolvedPhaseWorkload


@runtime_checkable
class RuntimeVerifier(Protocol):
    """The incremental evidence interface consumed by production phase owners."""

    @property
    def state(self) -> str: ...
    @property
    def is_terminal(self) -> bool: ...
    @property
    def failure_reason(self) -> str | None: ...
    @property
    def verification_seconds(self) -> float: ...
    @property
    def permits_workload_completion(self) -> bool: ...
    def feed(self, unit_ms: float, *, elapsed_ms: float | None = None) -> str: ...
    def active_interval(self) -> AbstractContextManager[None]: ...
    def finalize(self) -> str: ...
    def measurement(self) -> PhaseMeasurement | None: ...
    def prediction(
        self,
        workload: ResolvedPhaseWorkload,
        source: PredictionSource,
        *,
        safety_factor: float = 1.0,
        extra_predicted_seconds: float = 0.0,
        extra_detail: dict[str, Any] | None = None,
    ) -> RuntimePrediction | None: ...


class RuntimeVerifierFactory(Protocol):
    def __call__(
        self,
        *,
        unit: str,
        config: AdaptiveVerificationConfig,
        prior_expected_unit_ms: float | None,
        completion_policy: RuntimeCompletionPolicy,
    ) -> RuntimeVerifier: ...


class RuntimeVerifierIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assembly_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def verifier_assembly_digest() -> str:
    """Bind timing production, transport, admission and prior consumption."""
    root = Path(__file__).resolve().parents[2]
    names = (
        "core/runtime_control/verifier_provider.py",
        "core/runtime_control/adaptive.py",
        "core/runtime_control/steady_state.py",
        "core/runtime_control/distribution_shift.py",
        "core/runtime_control/session.py",
        "core/runtime_control/records.py",
        "core/runtime_control/workload.py",
        "core/runtime_control/completion.py",
        "core/runtime_control/execution_status.py",
        "core/run_invariants.py",
        "core/sandbox_executor.py",
        "nodes/ml_hyperparameter_tune_agent/runtime.py",
        "core/runtime_control/observation_store.py",
        "execute_tools/train_engine_sandbox.py",
        "execute_tools/training_budget_execution.py",
        "execute_tools/inference_runtime.py",
        "execute_tools/inference_single.py",
    )
    return source_fingerprint({name: (root / name).read_bytes() for name in names})


@dataclass(frozen=True)
class RuntimeVerifierProfile:
    name: str
    version: str
    create: RuntimeVerifierFactory
    sources: Mapping[str, Path]
    qualified_assemblies: frozenset[str]

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("A runtime verifier must declare its source files")
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))
        object.__setattr__(self, "qualified_assemblies", frozenset(self.qualified_assemblies))

    def identity(self) -> RuntimeVerifierIdentity:
        assembly = verifier_assembly_digest()
        if assembly not in self.qualified_assemblies:
            raise ValueError(f"Runtime verifier {self.name!r} has not qualified this assembly")
        return RuntimeVerifierIdentity(
            name=self.name,
            version=self.version,
            content_sha256=source_fingerprint(
                {name: path.read_bytes() for name, path in self.sources.items()}
            ),
            assembly_sha256=assembly,
        )


def resolve_runtime_verifier(selection: str) -> RuntimeVerifierProfile:
    matches = [e for e in entry_points(group="siderius.runtime_verifiers") if e.name == selection]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one installed runtime verifier {selection!r}; found {len(matches)}"
        )
    profile = matches[0].load()()
    if not isinstance(profile, RuntimeVerifierProfile) or profile.name != selection:
        raise TypeError("Runtime verifier factory must return the selected profile")
    profile.identity()
    return profile


def resolve_runtime_verifier_identity(
    selection: str | None,
    expected: RuntimeVerifierIdentity | None = None,
) -> RuntimeVerifierIdentity | None:
    if selection is None:
        if expected is not None:
            raise ValueError("Runtime verifier identity requires an explicit provider selection")
        return None
    identity = resolve_runtime_verifier(selection).identity()
    if expected is not None and identity != expected:
        raise ValueError("Runtime verifier changed after launch or subprocess dispatch")
    return identity


def create_runtime_verifier(
    *,
    selection: str | None,
    expected: RuntimeVerifierIdentity | None,
    unit: str,
    config: AdaptiveVerificationConfig,
    prior_expected_unit_ms: float | None,
    completion_policy: RuntimeCompletionPolicy,
) -> RuntimeVerifier:
    if selection is None:
        if expected is not None:
            raise ValueError("Native runtime verifier cannot carry an external identity")
        return AdaptiveUnitVerification(
            unit=unit,
            config=config,
            prior_expected_unit_ms=prior_expected_unit_ms,
        )
    if expected is None:
        raise ValueError("Selected runtime verifier requires a resolved identity before phase work")
    profile = resolve_runtime_verifier(selection)
    if profile.identity() != expected:
        raise ValueError("Runtime verifier changed after launch or subprocess dispatch")
    verifier = profile.create(
        unit=unit,
        config=config,
        prior_expected_unit_ms=prior_expected_unit_ms,
        completion_policy=completion_policy,
    )
    if not isinstance(verifier, RuntimeVerifier):
        raise TypeError("Runtime verifier does not implement the production evidence interface")
    return verifier
