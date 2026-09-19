"""
core/runtime_control/adaptive.py

Adaptive phase verification driver (RT2-C).

Design: docs/design/runtime_estimation_and_watchdog.md §2.5 (B1
stabilization / B2 measurement), §2.11 (fail closed), §2.12
(verification performance budget). One INCREMENTAL driver for phases
whose production loop owns execution (training: the epoch-0 batch loop
feeds real per-step timings): the driver consumes one unit duration at
a time, detects steady state (RT2a rolling-median detector with re-arm
on drift), enforces evidence minimums and hard caps, detects
pathological units, compares against a historical prior, and produces
the phase's `PhaseMeasurement` + `RuntimePrediction`.

Stopping rule (§2.5, "lightweight adaptive stopping"): verified when
steady state is DETECTED and the declaration has survived at least
``min_timed_steps`` steady observations AND ``min_timed_ms`` of steady
measurement — early exit is never granted on B1 stability alone. A
matching historical prior permits exit at exactly these minimums; a
drifting prior extends the requirement (``drift_extra_factor``) within
the caps. For very slow units the ``min_timed_ms`` term is satisfied by
a few observations — a handful of slow steps is sufficient evidence.

All caps/tolerances live in :class:`AdaptiveVerificationConfig`, which
reaches production through ``RuntimeControlPolicy`` — the §5
"equivalent runtime-policy surface". Defaults are stopping-POLICY
bounds (how long we are willing to measure), never substitutes for
measurement; per-host overrides land with §5 guardrail wiring (RT5).
"""

from __future__ import annotations

import math
import statistics
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.records import (
    Confidence,
    PhaseMeasurement,
    PredictionSource,
    PriorAgreement,
    RuntimePrediction,
)
from core.runtime_control.steady_state import SteadyStateConfig, SteadyStateDetector
from core.runtime_control.workload import ResolvedPhaseWorkload

VerificationState = Literal[
    "stabilizing",
    "measuring",
    "verified",
    "failed_no_steady_state",
    "failed_pathological_unit",
]

TERMINAL_STATES: frozenset[str] = frozenset(
    {"verified", "failed_no_steady_state", "failed_pathological_unit"}
)


class AdaptiveVerificationConfig(BaseModel):
    """Stopping policy for one phase's adaptive verification (§2.5/§2.12).

    Every bound here is a policy decision about how much evidence to
    collect before trusting (or abandoning) a measurement — none of
    them ever substitutes for the measurement itself.
    """

    model_config = ConfigDict(frozen=True)

    steady: SteadyStateConfig = Field(default_factory=SteadyStateConfig)
    min_timed_steps: int = Field(
        default=5,
        ge=1,
        description="Minimum steady observations before a prediction is trusted (B2 survival).",
    )
    min_timed_ms: float = Field(
        default=500.0,
        ge=0.0,
        description=(
            "Minimum cumulative steady measurement time. For very slow "
            "units this is reached in a few observations — the §2.5 "
            "'few observations suffice' rule falls out naturally."
        ),
    )
    max_steps: int = Field(
        default=200,
        ge=4,
        description=(
            "Observation cap for establishing stability and count evidence. Once those "
            "are satisfied, fast units may continue to the time floor within max_wall_ms."
        ),
    )
    max_wall_ms: float = Field(
        default=60_000.0,
        gt=0.0,
        description=(
            "Hard cap on cumulative verification time (§2.12 'seconds "
            "to protect against hours'). Environment-scopeable via the "
            "runtime policy (§5)."
        ),
    )
    pathological_factor: float = Field(
        default=10.0,
        gt=1.0,
        description=(
            "A unit measured AFTER steady-state declaration exceeding "
            "factor × steady median records a slow observation. A sustained streak "
            "of steady.stable_windows such observations terminates verification. "
            "Never applied to warm-up transients."
        ),
    )
    max_unit_ms: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Absolute pathological unit-time threshold (§5 provisional "
            "'single step > 5 s' rule) — environment-scoped, None "
            "disables. Applied only after steady-state declaration, "
            "like pathological_factor."
        ),
    )
    prior_match_tol: float = Field(
        default=0.25,
        gt=0.0,
        description=(
            "Relative tolerance for measured-vs-prior unit time: within "
            "→ verified_match (exit at evidence minimums); outside → "
            "verified_drift (extended measurement)."
        ),
    )
    drift_extra_factor: float = Field(
        default=2.0,
        ge=1.0,
        description="Multiplier on min_timed_steps when the prior is drifting (§2.5).",
    )

    @model_validator(mode="after")
    def _caps_allow_detection(self) -> AdaptiveVerificationConfig:
        if self.max_steps < self.steady.min_steps_to_detect + self.min_timed_steps:
            raise ValueError(
                f"max_steps={self.max_steps} cannot accommodate detection "
                f"({self.steady.min_steps_to_detect}) + minimum measurement "
                f"({self.min_timed_steps})."
            )
        return self


class AdaptiveUnitVerification:
    """Incremental verification of one phase's unit time.

    Feed one production unit duration at a time with :meth:`feed`; the
    driver moves through ``stabilizing → measuring → verified`` (or a
    terminal failure). The production loop stops timing as soon as a
    terminal state is returned. If the loop exhausts its units first,
    call :meth:`finalize` to resolve the outcome from the evidence
    collected so far.

    Args:
        unit:   Phase unit name (e.g. ``"optimizer_step"``).
        config: Stopping policy; default :class:`AdaptiveVerificationConfig`.
        prior_expected_unit_ms: Historical prior for this unit time
            (RT2-F store; ``None`` until then → ``new_configuration``).
    """

    def __init__(
        self,
        unit: str,
        config: AdaptiveVerificationConfig | None = None,
        prior_expected_unit_ms: float | None = None,
    ):
        if prior_expected_unit_ms is not None and prior_expected_unit_ms <= 0:
            raise ValueError(
                f"prior_expected_unit_ms must be positive; got {prior_expected_unit_ms!r}."
            )
        self.unit = unit
        self.config = config or AdaptiveVerificationConfig()
        self.prior_expected_unit_ms = prior_expected_unit_ms
        self._detector = SteadyStateDetector(self.config.steady)
        self._all_times_ms: list[float] = []
        self._elapsed_times_ms: list[float] = []
        self._state: VerificationState = "stabilizing"
        self._failure_reason: str | None = None
        self._prior_agreement: PriorAgreement | None = None
        self._slow_reference_ms: float | None = None
        self._slow_streak = 0
        self._slow_observations: list[int] = []
        self._started_at: float | None = None

    # ── State ────────────────────────────────────────────────────────────

    @property
    def state(self) -> VerificationState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    @property
    def verification_seconds(self) -> float:
        """Cumulative measured verification time (§2.12 overhead term)."""
        return sum(self._elapsed_times_ms) / 1000.0

    def _required_steady_steps(self) -> int:
        base = self.config.min_timed_steps
        if self._prior_agreement == "verified_drift":
            return max(base, round(base * self.config.drift_extra_factor))
        return base

    # ── Driving ──────────────────────────────────────────────────────────

    def feed(self, unit_ms: float, *, elapsed_ms: float | None = None) -> VerificationState:
        """Consume a normalized unit rate and its actual observation duration.

        ``elapsed_ms`` is the complete batch wall time when ``unit_ms`` has
        been divided by batch size. Stability and prediction use the unit
        rate; evidence minimums and wall caps use actual elapsed time. Omit
        it for one-unit observations to preserve their existing semantics.

        Raises:
            RuntimeError: fed after a terminal state (a loop bug — the
                caller must stop feeding once terminal).
            ValueError: non-positive duration.
        """
        if self.is_terminal:
            raise RuntimeError(f"verification already terminal ({self._state}); stop feeding.")
        if not math.isfinite(unit_ms) or unit_ms <= 0:
            raise ValueError(f"unit_ms must be positive; got {unit_ms!r}.")

        elapsed = unit_ms if elapsed_ms is None else elapsed_ms
        if not math.isfinite(elapsed) or elapsed <= 0:
            raise ValueError(f"elapsed_ms must be finite and positive; got {elapsed!r}.")
        if self._started_at is None:
            self._started_at = time.monotonic()
        self._all_times_ms.append(unit_ms)
        self._elapsed_times_ms.append(elapsed)
        # Compare with the pre-observation plateau. An isolated I/O/scheduler
        # delay is evidence, not a conclusive persistent slowdown; repeated
        # slow observations still fail before a new plateau can hide the drift.
        prior_steady = self._detector.steady_times_ms()
        reference = self._slow_reference_ms
        if reference is None and self._detector.detected and prior_steady:
            reference = statistics.median(prior_steady)
        if reference is not None:
            if unit_ms > self.config.pathological_factor * reference:
                self._slow_reference_ms = reference
                self._slow_streak += 1
                self._slow_observations.append(len(self._all_times_ms) - 1)
                if self._slow_streak >= self.config.steady.stable_windows:
                    self._failure_reason = (
                        f"pathological sustained slowdown: {self._slow_streak} consecutive "
                        f"units > {self.config.pathological_factor}x steady median "
                        f"{reference:.3g} ms; latest {unit_ms:.3g} ms"
                    )
                    self._state = "failed_pathological_unit"
                    return self._state
            else:
                self._slow_reference_ms = None
                self._slow_streak = 0
        self._detector.observe(unit_ms)

        if self._detector.detected:
            steady = self._detector.steady_times_ms()
            steady_median = statistics.median(steady)
            if self.config.max_unit_ms is not None and unit_ms > self.config.max_unit_ms:
                self._failure_reason = (
                    f"pathological unit: {unit_ms:.1f} ms > absolute threshold "
                    f"{self.config.max_unit_ms:.1f} ms (environment-scoped §5)"
                )
                self._state = "failed_pathological_unit"
                return self._state
            self._state = "measuring"
            self._compare_prior(steady_median)
            if (
                self._slow_streak == 0
                and len(steady) >= self._required_steady_steps()
                and self._steady_elapsed_ms() >= self.config.min_timed_ms
            ):
                self._state = "verified"
                return self._state
        else:
            # Not (or no longer — re-arm) detected.
            self._state = "stabilizing"

        # A fast, already stable phase can need more observations to accumulate
        # the same evidence time. Never extend an unstable/count-deficient trace.
        extend_for_time = (
            self._detector.detected
            and self._slow_streak == 0
            and len(self._detector.steady_times_ms()) >= self._required_steady_steps()
            and self._steady_elapsed_ms() < self.config.min_timed_ms
        )
        wall_ms = max(sum(self._elapsed_times_ms), (time.monotonic() - self._started_at) * 1000.0)
        if (
            len(self._all_times_ms) >= self.config.max_steps and not extend_for_time
        ) or wall_ms >= self.config.max_wall_ms:
            self._fail_insufficient()
        return self._state

    def _steady_elapsed_ms(self) -> float:
        """Wall time of the detector's current, possibly re-armed suffix."""
        count = len(self._detector.steady_times_ms())
        return sum(self._elapsed_times_ms[-count:]) if count else 0.0

    def finalize(self) -> VerificationState:
        """Resolve the outcome when the production loop ran out of units.

        A detected-but-under-minimum trace is insufficient evidence —
        never silently promoted to verified (§2.5: early exit only after
        B2 survival).
        """
        if not self.is_terminal:
            self._fail_insufficient()
        return self._state

    def _fail_insufficient(self) -> None:
        if self._detector.detected:
            # Step 09.5a Gate-2 forensics (2026-08-20). `verified` requires
            # BOTH minimums — a steady COUNT and a steady TIME:
            #
            #     len(steady) >= _required_steady_steps()
            #     sum(steady) >= config.min_timed_ms
            #
            # The message used to report only the first, so a trace that
            # satisfied it read as self-contradictory — the Gate's validation
            # phase failed with "26 steady observations, required 5" while the
            # real violation was 84 ms of steady time against a 500 ms floor.
            # A diagnostic that names a satisfied condition sends the reader to
            # the wrong subsystem, which is exactly what it did. Both are now
            # reported with their actual values, and the unmet one is named.
            steady = self._detector.steady_times_ms()
            steady_ms = self._steady_elapsed_ms()
            unmet = []
            if len(steady) < self._required_steady_steps():
                unmet.append("steady_count")
            if steady_ms < self.config.min_timed_ms:
                unmet.append("steady_time")
            self._failure_reason = (
                "insufficient_stability: steady state declared but evidence "
                f"minimums not met within caps (unmet: {'+'.join(unmet) or 'none'}; "
                f"steady observations {len(steady)}, required "
                f"{self._required_steady_steps()}; steady time {steady_ms:.1f} ms, "
                f"required {self.config.min_timed_ms:.1f} ms; "
                f"{len(self._all_times_ms)} units observed within caps "
                f"max_steps={self.config.max_steps})"
            )
            if self._prior_agreement is None:
                self._prior_agreement = "insufficient_stability"
        else:
            self._failure_reason = (
                f"no steady state within caps ({len(self._all_times_ms)} units observed, "
                f"{self.verification_seconds:.1f}s measured)"
            )
            self._prior_agreement = (
                "verification_failed" if self.prior_expected_unit_ms is not None else None
            )
        self._state = "failed_no_steady_state"

    def _compare_prior(self, steady_median_ms: float) -> None:
        """§2.5 prior comparison; sets the agreement outcome."""
        if self.prior_expected_unit_ms is None:
            self._prior_agreement = "new_configuration"
            return
        ratio = steady_median_ms / self.prior_expected_unit_ms
        # Recomputed on EVERY measuring step from the current steady
        # median: a transient early median must not lock in a "drift"
        # verdict that the settled plateau contradicts (pre-Gate S4
        # finding F3 — the old sticky rule labeled a 0.98-ratio run
        # verified_drift). While the momentary ratio is outside
        # tolerance the extended-measurement requirement applies (§2.5
        # "keep measuring within budget"); the outcome that persists is
        # the one in force at the verification stopping point.
        self._prior_agreement = (
            "verified_match"
            if abs(ratio - 1.0) <= self.config.prior_match_tol
            else "verified_drift"
        )

    # ── Results ──────────────────────────────────────────────────────────

    @property
    def prior_agreement(self) -> PriorAgreement | None:
        return self._prior_agreement

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    def measurement(self) -> PhaseMeasurement | None:
        """Evidence collected so far (``None`` before any observation)."""
        if not self._all_times_ms:
            return None
        steady = self._detector.steady_times_ms()
        if steady:
            median = statistics.median(steady)
            mad = statistics.median(abs(t - median) for t in steady)
        else:
            median = statistics.median(self._all_times_ms)
            mad = statistics.median(abs(t - median) for t in self._all_times_ms)
        return PhaseMeasurement(
            unit=self.unit,
            n_measured_units=max(len(steady), 1) if steady else len(self._all_times_ms),
            n_stabilization_units=len(self._all_times_ms) - len(steady),
            unit_time_ms_median=max(median, 1e-9),
            unit_time_ms_mad=mad,
            steady_state_reached=bool(steady),
            total_measurement_seconds=self.verification_seconds,
            raw_timings_ms=list(self._all_times_ms),
            detail={
                "state": self._state,
                "observation_elapsed_ms": list(self._elapsed_times_ms),
                "failure_reason": self._failure_reason,
                "prior_agreement": self._prior_agreement,
                "prior_expected_unit_ms": self.prior_expected_unit_ms,
                "rolling_medians_ms": self._detector.result().rolling_medians_ms,
                "relative_slow_observation_indices": list(self._slow_observations),
                "observation_cap_extended": len(self._all_times_ms) > self.config.max_steps,
            },
        )

    def _confidence(self, steady: list[float], median: float) -> Confidence:
        """Evidence-derived confidence (§2.9): stability + observation count."""
        mad = statistics.median(abs(t - median) for t in steady)
        if mad / median <= 0.05 and len(steady) >= self.config.min_timed_steps:
            return "high"
        return "medium"

    def prediction(
        self,
        workload: ResolvedPhaseWorkload,
        source: PredictionSource,
        *,
        safety_factor: float = 1.0,
        extra_predicted_seconds: float = 0.0,
        extra_detail: dict | None = None,
    ) -> RuntimePrediction | None:
        """Build the phase prediction from resolved workload × steady unit time.

        Returns ``None`` unless the verification VERIFIED — a failed or
        incomplete verification never yields a formal-eligible
        prediction (§2.11 fail closed; the caller records the
        measurement evidence regardless).

        Args:
            workload:               Resolved production workload.
            source:                 Measurement-backed source string for
                                    this phase (e.g.
                                    ``"real_training_verification"``).
            safety_factor:          Recorded multiplier (policy).
            extra_predicted_seconds: Additive engine-specific term with
                                    its own provenance (e.g. per-epoch
                                    dataset reconstruction) — exposed in
                                    detail, never hidden in unit time.
            extra_detail:           Merged into the prediction detail.
        """
        if self._state != "verified":
            return None
        steady = self._detector.steady_times_ms()
        median = statistics.median(steady)
        predicted = workload.unit_count * median / 1000.0 + extra_predicted_seconds
        prior_ratio = None
        if self.prior_expected_unit_ms is not None:
            prior_ratio = median / self.prior_expected_unit_ms
        detail = {
            "measured_unit_ms": median,
            "unit_count": workload.unit_count,
            "extra_predicted_seconds": extra_predicted_seconds,
            "verification_seconds": self.verification_seconds,
            "prior_agreement": self._prior_agreement,
            **(extra_detail or {}),
        }
        return RuntimePrediction(
            predicted_seconds=max(predicted, 1e-9),
            source=source,
            formal_execution_eligible=True,
            steady_state=True,
            verification="passed",
            confidence=self._confidence(steady, median),
            ms_per_unit=median,
            n_steady_units=len(steady),
            unit_count=workload.unit_count,
            safety_factor=safety_factor,
            prior_expected_seconds=(
                workload.unit_count * self.prior_expected_unit_ms / 1000.0
                if self.prior_expected_unit_ms is not None
                else None
            ),
            prior_agreement_ratio=prior_ratio,
            detail=detail,
        )
