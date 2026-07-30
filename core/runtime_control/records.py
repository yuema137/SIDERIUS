"""
core/runtime_control/records.py

Prediction / Measurement / Actual data model of the runtime-control
framework (RT2-A).

Design: docs/design/runtime_estimation_and_watchdog.md §2.3 (core
principle), §2.8 (source vocabulary), §6.1 (component-first
observation schema). Three fundamentally different objects that are
never conflated:

- **Prediction** (`RuntimePrediction`): produced BEFORE execution;
  combines priors and verification evidence; used for admission.
- **Measurement** (`PhaseMeasurement`): representative observations
  collected during runtime verification; evidence that refines the
  prediction; never the final runtime.
- **Actual**: the duration of the complete production phase, recorded
  after completion; the target that prediction error is computed
  against (`PredictionError` = prediction vs actual, NEVER measurement
  vs actual).

The rev-4/5 admission invariant is SCHEMA-ENFORCED here: a
`formal_execution_eligible=True` prediction cannot be constructed
unless it is measurement-backed, verified, and steady-state with
measurement provenance present — no consumer can admit a formal
execution from an uncalibrated source even by accident.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.phases import RUNTIME_PHASES, RuntimePhase
from core.runtime_control.workload import ResolvedPhaseWorkload

# ── Vocabulary (§2.8, rev 5 — widened) ───────────────────────────────────────

PredictionSource = Literal[
    # Priors — never formal-eligible on their own.
    "static_uncalibrated",
    "legacy_calibration_prior",
    "historical_observation_prior",
    "historical_orchestration",
    # Live measurement-backed sources.
    "real_dataset_setup",
    "real_training_verification",
    "real_inference_verification",
    "measured_representative_scoring",
    # Kept for wrapper compatibility (§7.1): the training-phase live
    # source string the RT1 breakdown contract already exposes.
    "real_dataset_warmup",
    # Evidence-bounded conservative estimate (§2.7).
    "bounded_negligible",
    # Component-derived total (§1.1).
    "derived_total",
    # C3 vocabulary extension (runtime_estimation_and_calibration.md §7.3
    # mapping table): the post-implementation bounded live probe (C6
    # producer) and its historically-corrected form, plus the
    # complete-execution observation tier (§8.4). Additive — no existing
    # value changes meaning; nothing produces these until C6/C7.
    "bounded_live_probe",
    "bounded_live_probe_calibrated",
    "complete_observation",
]

#: Sources backed by a live measurement of the actual configuration —
#: the only sources that may ever carry ``formal_execution_eligible``.
MEASUREMENT_BACKED_SOURCES: frozenset[str] = frozenset(
    {
        "real_dataset_setup",
        "real_training_verification",
        "real_inference_verification",
        "measured_representative_scoring",
        "real_dataset_warmup",
        # C3 extension: live measurements of the ACTUAL implemented
        # candidate (design contract §8.2/§8.4). The RuntimePrediction
        # admission invariant applies unchanged: formal eligibility still
        # requires verification="passed" + steady_state + measurement
        # provenance — a contended or non-steady probe can never be
        # formal-eligible.
        "bounded_live_probe",
        "bounded_live_probe_calibrated",
        "complete_observation",
    }
)

VerificationResult = Literal["passed", "failed", "not_attempted"]
Confidence = Literal["low", "medium", "high"]

#: Prior-comparison outcomes (§2.5).
PriorAgreement = Literal[
    "verified_match",
    "verified_drift",
    "new_configuration",
    "insufficient_stability",
    "verification_failed",
]


# ── Prediction ───────────────────────────────────────────────────────────────


class RuntimePrediction(BaseModel):
    """One phase's runtime prediction with full provenance.

    Admission invariant (schema-enforced): ``formal_execution_eligible=True``
    requires a MEASUREMENT_BACKED source AND ``verification="passed"``
    AND ``steady_state=True`` with measurement provenance present.
    Everything else is a preliminary risk screen.
    """

    model_config = ConfigDict(frozen=True)

    predicted_seconds: float = Field(gt=0.0)
    source: PredictionSource
    formal_execution_eligible: bool
    steady_state: bool = Field(
        description="Whether the backing measurement reached detected steady state."
    )
    verification: VerificationResult
    confidence: Confidence

    # Measurement provenance (measurement-backed predictions).
    ms_per_unit: float | None = Field(default=None, gt=0.0)
    n_steady_units: int | None = Field(default=None, ge=1)
    unit_count: int | None = Field(default=None, ge=0)
    safety_factor: float = Field(ge=1.0)

    # Prior-verification provenance (§2.5 / §6).
    prior_expected_seconds: float | None = Field(default=None, gt=0.0)
    prior_agreement_ratio: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "measurement-backed prediction ÷ prior expectation. Near 1.0 → "
            "prior verified (early exit); large deviation → prior flagged "
            "for invalidation (§6b)."
        ),
    )

    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form extra provenance (rolling medians, MAD, jitter flags…).",
    )

    @model_validator(mode="after")
    def _admission_invariant(self) -> RuntimePrediction:
        if self.formal_execution_eligible:
            problems = []
            if self.source not in MEASUREMENT_BACKED_SOURCES:
                problems.append(
                    f"source={self.source!r} is not measurement-backed "
                    f"(require one of {sorted(MEASUREMENT_BACKED_SOURCES)})"
                )
            if self.verification != "passed":
                problems.append(f"verification={self.verification!r} (require 'passed')")
            if not self.steady_state:
                problems.append("steady_state=False (require True)")
            if self.ms_per_unit is None or self.n_steady_units is None:
                problems.append("missing measurement provenance (ms_per_unit/n_steady_units)")
            if problems:
                raise ValueError(
                    "formal_execution_eligible=True violates the admission "
                    "invariant: " + "; ".join(problems)
                )
        if self.source in MEASUREMENT_BACKED_SOURCES and self.verification == "not_attempted":
            raise ValueError(f"source={self.source!r} contradicts verification='not_attempted'.")
        if (self.prior_agreement_ratio is None) != (self.prior_expected_seconds is None):
            raise ValueError(
                "prior_agreement_ratio and prior_expected_seconds must be set together."
            )
        return self

    @property
    def predicted_minutes(self) -> float:
        return self.predicted_seconds / 60.0


# ── Measurement ──────────────────────────────────────────────────────────────


class PhaseMeasurement(BaseModel):
    """Representative execution evidence collected during verification.

    Evidence for building/refining a prediction — never the actual
    runtime, never the prediction-error target.
    """

    model_config = ConfigDict(frozen=True)

    unit: str = Field(min_length=1)
    n_measured_units: int = Field(ge=1)
    n_stabilization_units: int = Field(ge=0)
    unit_time_ms_median: float = Field(gt=0.0)
    unit_time_ms_mad: float | None = Field(default=None, ge=0.0)
    steady_state_reached: bool
    total_measurement_seconds: float = Field(ge=0.0)
    raw_timings_ms: list[float] = Field(
        default_factory=list,
        description="Individual unit timings (observation-store provenance).",
    )
    detail: dict[str, Any] = Field(default_factory=dict)


# ── Actual + error ───────────────────────────────────────────────────────────


class PredictionError(BaseModel):
    """Prediction-vs-actual error for one phase (or the total).

    Always FINAL PREDICTION vs ACTUAL (§2.3). ``log_error`` feeds the
    §2.10 acceptance criterion `|log(actual/predicted)| ≤ log(F)`.
    """

    model_config = ConfigDict(frozen=True)

    predicted_seconds: float = Field(gt=0.0)
    actual_seconds: float = Field(gt=0.0)
    ratio: float = Field(gt=0.0, description="actual / predicted")
    log_error: float = Field(ge=0.0, description="|log(actual / predicted)|")

    @classmethod
    def from_values(cls, predicted_seconds: float, actual_seconds: float) -> PredictionError:
        ratio = actual_seconds / predicted_seconds
        return cls(
            predicted_seconds=predicted_seconds,
            actual_seconds=actual_seconds,
            ratio=ratio,
            log_error=abs(math.log(ratio)),
        )

    def within_contract(self, factor: float) -> bool:
        """§2.10 acceptance criterion against contract factor F (> 1)."""
        if factor <= 1.0:
            raise ValueError(f"contract factor must exceed 1.0; got {factor!r}.")
        return self.log_error <= math.log(factor)

    @model_validator(mode="after")
    def _consistent(self) -> PredictionError:
        expect_ratio = self.actual_seconds / self.predicted_seconds
        if not math.isclose(self.ratio, expect_ratio, rel_tol=1e-9):
            raise ValueError("ratio must equal actual_seconds / predicted_seconds.")
        if not math.isclose(self.log_error, abs(math.log(expect_ratio)), rel_tol=1e-9):
            raise ValueError("log_error must equal |log(actual / predicted)|.")
        return self


# ── Component-first observation schema (§6.1) ────────────────────────────────


class PhaseComponentRecord(BaseModel):
    """One phase's {prediction, measurement, actual, error} quartet."""

    model_config = ConfigDict(frozen=True)

    workload: ResolvedPhaseWorkload | None = None
    prediction: RuntimePrediction | None = None
    measurement: PhaseMeasurement | None = None
    actual_seconds: float | None = Field(default=None, gt=0.0)
    prediction_error: PredictionError | None = None

    @model_validator(mode="after")
    def _error_requires_both(self) -> PhaseComponentRecord:
        if self.prediction_error is not None:
            if self.prediction is None or self.actual_seconds is None:
                raise ValueError(
                    "prediction_error requires both prediction and actual_seconds "
                    "(error is prediction vs actual — §2.3)."
                )
            if not math.isclose(
                self.prediction_error.predicted_seconds,
                self.prediction.predicted_seconds,
                rel_tol=1e-9,
            ) or not math.isclose(
                self.prediction_error.actual_seconds, self.actual_seconds, rel_tol=1e-9
            ):
                raise ValueError(
                    "prediction_error must be computed from THIS record's "
                    "prediction and actual_seconds — never from the measurement."
                )
        return self

    def with_actual(self, actual_seconds: float) -> PhaseComponentRecord:
        """Finalize the phase's actual runtime, deriving the error."""
        error = (
            PredictionError.from_values(self.prediction.predicted_seconds, actual_seconds)
            if self.prediction is not None
            else None
        )
        return self.model_copy(update={"actual_seconds": actual_seconds, "prediction_error": error})


class TotalRecord(BaseModel):
    """Derived total — components are the source of truth (§6.1)."""

    model_config = ConfigDict(frozen=True)

    predicted_seconds: float = Field(gt=0.0)
    safety_adjusted_seconds: float | None = Field(default=None, gt=0.0)
    operator_budget_seconds: float | None = Field(default=None, gt=0.0)
    actual_seconds: float | None = Field(default=None, gt=0.0)
    prediction_error: PredictionError | None = None


class AdmissionRecord(BaseModel):
    """Admission decision with the explicit rejected-verification cost
    model (§2.1)."""

    model_config = ConfigDict(frozen=True)

    decision: Literal["admitted", "rejected"]
    stage: str = Field(
        min_length=1,
        description='e.g. "pre_launch_screen", "post_setup_runtime_verification"',
    )
    setup_cost_seconds: float | None = Field(default=None, ge=0.0)
    verification_cost_seconds: float | None = Field(default=None, ge=0.0)
    avoided_predicted_runtime_seconds: float | None = Field(default=None, ge=0.0)
    reason: str | None = None


class RuntimeObservation(BaseModel):
    """One attempt's component-first runtime observation (§6.1).

    The primary persistent artifact of the runtime-control system —
    append-only in the store (RT2-F); calibration is derived from these,
    never stored as the only artifact. Total is DERIVED from components
    (validated when all component predictions are present).
    """

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    timestamp: str = Field(min_length=1)
    chain_id: str | None = None
    attempt_id: str | None = None
    hardware: dict[str, Any] = Field(default_factory=dict)
    software: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Dataset/storage provenance of the setup measurement (§2.2): "
            "dataset root, filesystem, expected vs actually-read bytes, "
            "cache state, host memory before/after."
        ),
    )
    runtime_policy: dict[str, Any] = Field(
        default_factory=dict,
        description="Environment-scoped thresholds in force (§5).",
    )
    historical_prior: dict[str, Any] | None = None
    prior_agreement: PriorAgreement | None = None
    calibration_context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "§6a key inputs recorded at measurement time (precision, "
            "optimizer_type, model_family, param_count, seg_size, "
            "batch_size, runtime_flags). Empty → the observation stays "
            "evidence but never feeds calibration."
        ),
    )

    components: dict[RuntimePhase, PhaseComponentRecord] = Field(default_factory=dict)
    total: TotalRecord | None = None
    admission: AdmissionRecord | None = None
    watchdog_status: str | None = None
    final_status: str | None = None
    calibration_eligible: bool = False

    @model_validator(mode="after")
    def _derived_total_consistent(self) -> RuntimeObservation:
        if self.total is None:
            return self
        predictions = [c.prediction for c in self.components.values()]
        if predictions and all(p is not None for p in predictions):
            component_sum = sum(p.predicted_seconds for p in predictions)  # type: ignore[union-attr]
            if not math.isclose(self.total.predicted_seconds, component_sum, rel_tol=1e-6):
                raise ValueError(
                    f"total.predicted_seconds={self.total.predicted_seconds} must be "
                    f"DERIVED from components (sum={component_sum}) — §6.1."
                )
        return self

    def phase(self, phase: RuntimePhase) -> PhaseComponentRecord | None:
        return self.components.get(phase)


# ── Legacy-record compatibility (§7.3) ───────────────────────────────────────

RUNTIME_VERIFICATION_RECORD_KEY = "runtime_verification"


def extract_runtime_observation(record: dict[str, Any]) -> RuntimeObservation | None:
    """Parse a record's runtime-verification block, legacy-aware.

    Legacy records (including the archived V18 workspaces) carry no
    `runtime_verification` key → returns ``None`` (absence is explicit,
    never an error). Records WITH the key must validate — a malformed
    block is a real defect, not legacy data.
    """
    block = record.get(RUNTIME_VERIFICATION_RECORD_KEY)
    if block is None:
        return None
    return RuntimeObservation.model_validate(block)


def record_is_formal_verified(record: dict[str, Any]) -> bool:
    """Fail-closed formal-eligibility check for persisted records.

    A legacy record (no verification metadata), an unparsed block, or an
    observation without an admitted decision is NEVER treated as
    verified (§7.3). Total eligibility follows the contribution-based
    policy (RT2-E, operator decision 2026-07-23): live-verified major
    phases + evidence-backed historical phases within the recorded
    share limit.
    """
    from core.runtime_control.total_assembly import observation_formal_eligible

    try:
        obs = extract_runtime_observation(record)
    except Exception:
        return False
    if obs is None or obs.admission is None:
        return False
    if obs.admission.decision != "admitted":
        return False
    return observation_formal_eligible(obs.components, obs.runtime_policy)


def observation_totals_from_components(
    components: dict[RuntimePhase, PhaseComponentRecord],
    *,
    safety_factor: float | None = None,
    operator_budget_seconds: float | None = None,
) -> TotalRecord:
    """Derive the TotalRecord from component predictions (§1.1/§6.1).

    Raises:
        ValueError: any known phase lacks a prediction — an incomplete
            component set must never silently produce a total.
    """
    missing = [p for p in RUNTIME_PHASES if p in components and components[p].prediction is None]
    if missing:
        raise ValueError(
            f"cannot derive total: phases missing predictions: {missing}. "
            "Incomplete component prediction → ineligible (§3)."
        )
    if not components:
        raise ValueError("cannot derive total from an empty component set.")
    total = sum(
        c.prediction.predicted_seconds  # type: ignore[union-attr]
        for c in components.values()
    )
    return TotalRecord(
        predicted_seconds=total,
        safety_adjusted_seconds=(total * safety_factor if safety_factor is not None else None),
        operator_budget_seconds=operator_budget_seconds,
    )
