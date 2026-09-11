"""
core/runtime_control/verifier.py

Generic `RuntimePhaseVerifier` abstraction (RT2-A).

Design: docs/design/runtime_estimation_and_watchdog.md §2.4. One
verification framework, phase-specific workload semantics. Every
runtime phase (training, inference, scoring, and future scientific
phases) follows the same lifecycle:

    resolve_workload() → prepare() → reach_steady_state() → measure()
    → predict() → record() → finalize_actual()

The FRAMEWORK owns: lifecycle sequencing, Prediction/Measurement/Actual
separation, record assembly, and (in later stages) prior comparison,
observation writing, and error-ledger updates. PHASE implementations
own: exact workload units, production execution semantics, steady-state
behavior, resource preparation, and output handling.

RT2-A ships the abstraction + deterministic assembly driver; the
adaptive stopping / prior-comparison / failure policies land in RT2-C.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.runtime_control.phases import RuntimePhase
from core.runtime_control.records import (
    PhaseComponentRecord,
    PhaseMeasurement,
    RuntimePrediction,
)
from core.runtime_control.steady_state import SteadyStateDetection
from core.runtime_control.workload import ResolvedPhaseWorkload


class RuntimePhaseVerifier(ABC):
    """Common lifecycle contract for verifying one runtime phase.

    Subclasses implement the abstract steps with production semantics;
    :meth:`run_verification` drives them in order and assembles the
    component record so no phase implementation can skip a step or
    conflate measurement with prediction.
    """

    #: The phase this verifier covers — set by each subclass.
    phase: RuntimePhase

    @abstractmethod
    def resolve_workload(self) -> ResolvedPhaseWorkload:
        """Resolve the EXACT production workload before any measurement
        (§1.2) — units must mirror the production implementation."""

    @abstractmethod
    def prepare(self) -> None:
        """Prepare the actual production phase (real model/optimizer/
        loss/data on the actual device) — never a proxy."""

    @abstractmethod
    def reach_steady_state(self) -> SteadyStateDetection:
        """Adaptive stabilization (§2.5 B1): run until steady state is
        DETECTED or the budget is exhausted — never a fixed step count.
        Phases where stabilization is unnecessary (§2.7 scoring) return
        a trivially-reached detection."""

    @abstractmethod
    def measure(self, detection: SteadyStateDetection) -> PhaseMeasurement:
        """Representative steady-state measurement (§2.5 B2) with raw
        timings preserved for the observation store."""

    @abstractmethod
    def predict(
        self, workload: ResolvedPhaseWorkload, measurement: PhaseMeasurement
    ) -> RuntimePrediction:
        """Build the phase prediction from resolved workload × measured
        unit time (+ phase-specific setup/output terms)."""

    def run_verification(self) -> PhaseComponentRecord:
        """Drive the lifecycle in order and assemble the component record.

        Deterministic sequencing only (RT2-A): resolve → prepare →
        reach_steady_state → measure → predict. Failure policy,
        adaptive early exit, and prior comparison are RT2-C
        responsibilities layered on top of this driver.
        """
        workload = self.resolve_workload()
        self.prepare()
        detection = self.reach_steady_state()
        measurement = self.measure(detection)
        prediction = self.predict(workload, measurement)
        return PhaseComponentRecord(
            workload=workload,
            prediction=prediction,
            measurement=measurement,
        )

    @staticmethod
    def finalize_actual(
        record: PhaseComponentRecord, actual_seconds: float
    ) -> PhaseComponentRecord:
        """Attach the phase's ACTUAL runtime after production execution,
        deriving the prediction error (prediction vs actual — §2.3)."""
        return record.with_actual(actual_seconds)
