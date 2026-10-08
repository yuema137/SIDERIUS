"""Training-loop adapter for cooperative budgeting and execution receipts."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Literal

from core.checkpoint_selection import CheckpointSelection
from core.runtime_control.phases import RuntimePhase
from core.runtime_control.records import RuntimePrediction
from core.runtime_control.session import RuntimeVerificationSession
from core.runtime_control.training_budget import (
    TrainingBudgetDecision,
    TrainingBudgetEnvelope,
    TrainingBudgetReceipt,
    decide_training_budget,
)
from core.runtime_control.verifier_provider import RuntimeVerifier
from core.runtime_control.workload import ResolvedPhaseWorkload


class TrainingBudgetExecution:
    """Own epoch costs and emit decisions; never mutate a model or optimizer."""

    def __init__(self, envelope: TrainingBudgetEnvelope, *, proposed_epochs: int) -> None:
        self.envelope = envelope
        self.proposed_epochs = proposed_epochs
        self.costs: list[float] = []
        self.optimizer_steps = 0
        self._epoch_started: float | None = None
        self.last_decision: TrainingBudgetDecision | None = None

    def decide(self, *, next_optimizer_steps: int | None = None) -> TrainingBudgetDecision:
        decision = decide_training_budget(
            self.envelope,
            elapsed_seconds=time.monotonic() - self.envelope.started_monotonic_seconds,
            completed_epochs=len(self.costs),
            observed_epoch_seconds=self.costs,
            completed_optimizer_steps=self.optimizer_steps,
            next_optimizer_steps=next_optimizer_steps,
        )
        self.last_decision = decision
        print(f"[training_budget_decision] {decision.model_dump_json()}", flush=True)
        return decision

    def admit_materialized_epoch(self, *, optimizer_steps: int) -> bool:
        """Recheck actual loader size and setup cost before any optimizer work."""
        decision = self.decide(next_optimizer_steps=optimizer_steps)
        if decision.action != "stop":
            return True
        if not self.costs:
            raise ValueError(
                "Training allocation cannot fit the first materialized epoch before optimizer "
                f"work: reason={decision.reason}, next_optimizer_steps={optimizer_steps}, "
                f"max_optimizer_steps={self.envelope.max_optimizer_steps}, "
                f"remaining_seconds={decision.remaining_seconds}"
            )
        self._epoch_started = None
        return False

    def start_epoch(self) -> None:
        self._epoch_started = time.monotonic()

    def finish_epoch(self, *, optimizer_steps: int) -> TrainingBudgetDecision:
        if self._epoch_started is None:
            raise RuntimeError("Training budget epoch was not started")
        self.costs.append(max(time.monotonic() - self._epoch_started, 1e-9))
        self.optimizer_steps += optimizer_steps
        self._epoch_started = None
        return self.decide()

    def receipt(
        self, *, checkpoint_selection: CheckpointSelection = "last_completed_epoch"
    ) -> dict:
        if self.last_decision is None or self.last_decision.action != "stop":
            raise RuntimeError("Training budget has no completed stop decision")
        return TrainingBudgetReceipt(
            policy=self.envelope,
            proposed_epochs=self.proposed_epochs,
            completed_epochs=len(self.costs),
            optimizer_steps=self.optimizer_steps,
            epoch_seconds_including_validation=self.costs,
            stop=self.last_decision,
            checkpoint_selection=checkpoint_selection,
        ).model_dump()

    def reconcile(
        self,
        session: RuntimeVerificationSession,
        *,
        validation_rows: int | None,
        epoch0_dataset_seconds: float,
    ) -> None:
        """Do not calibrate future runs against the single calibration epoch."""
        workloads: tuple[tuple[RuntimePhase, str, int], ...] = (
            ("training", "optimizer_step", self.optimizer_steps),
            ("validation", "validation_sample", (validation_rows or 0) * len(self.costs)),
        )
        for phase, unit, count in workloads:
            if phase == "validation" and validation_rows is None:
                continue
            session.record_executed_workload(
                ResolvedPhaseWorkload(
                    phase=phase,
                    unit=unit,
                    unit_count=count,
                    detail={"source": "cooperative_training_completed", "epochs": len(self.costs)},
                ),
                extra_predicted_seconds=(len(self.costs) - 1) * epoch0_dataset_seconds
                if phase == "training"
                else 0.0,
            )


class TrainingAllocationRejected(RuntimeError):
    """A partial train/validation pass cannot be published as a completed candidate."""


def enforce_training_allocation(
    session: RuntimeVerificationSession | None,
    *,
    phase: RuntimePhase,
    prediction: RuntimePrediction | None = None,
) -> None:
    """Cooperate at batch boundaries; reserve downstream time without killing a process.

    After calibration, use the verified full-phase cost conservatively as the
    remaining requirement. Unknown cost stays unknown; elapsed allowance still
    bounds further batch dispatch. One already-running batch may finish late.
    """
    if session is None or session.policy.training_budget is None:
        return
    envelope = session.policy.training_budget
    elapsed = time.monotonic() - envelope.started_monotonic_seconds
    available = envelope.budget_seconds - envelope.reserved_seconds - elapsed
    needed = (
        prediction.predicted_seconds
        if prediction is not None and prediction.formal_execution_eligible
        else None
    )
    if available > 0 and (needed is None or needed <= available):
        return
    reason = (
        f"training allocation cannot fit {phase}: elapsed_seconds={elapsed:.6g}, "
        f"remaining_before_reserve_seconds={envelope.budget_seconds - elapsed:.6g}, "
        f"reserved_seconds={envelope.reserved_seconds:.6g}, "
        f"verified_full_phase_seconds={needed}; incomplete epoch is not scoreable"
    )
    session.reject_training_allocation(phase=phase, reason=reason)
    raise TrainingAllocationRejected(reason)


def return_on_allocation_rejection[**P, R](
    execute: Callable[P, R],
) -> Callable[P, R | None]:
    """Unwind model/loader ownership on cooperative refusal, preserving the sidecar."""

    @wraps(execute)
    def run(*args: P.args, **kwargs: P.kwargs) -> R | None:
        try:
            return execute(*args, **kwargs)
        except TrainingAllocationRejected as exc:
            print(f"[training_budget] REJECTED: {exc}", flush=True)
            return None

    return run


def complete_training_workload(
    session: RuntimeVerificationSession,
    *,
    budget_execution: TrainingBudgetExecution | None,
    training_verifier: RuntimeVerifier | None,
    validation_verifier: RuntimeVerifier | None,
    optimizer_steps: int,
    completed_epochs: int,
    epoch_limit: int,
    training_seconds: float,
    validation_seconds: float,
    validation_rows: int | None,
    epoch0_dataset_seconds: float,
) -> bool:
    """Close successful whole epochs after required validation has completed.

    This is called only at the production loop's successful exit. Counts are
    reconciled for an authorized cooperative stop before actual admission.
    Training seconds exclude validation; each incurred cost enters exactly once.
    """
    if budget_execution is not None:
        budget_execution.reconcile(
            session,
            validation_rows=validation_rows,
            epoch0_dataset_seconds=epoch0_dataset_seconds,
        )
    reason: Literal["requested_horizon", "cooperative_epoch_stop"] = (
        "cooperative_epoch_stop"
        if budget_execution is not None and completed_epochs < epoch_limit
        else "requested_horizon"
    )
    session.complete_phase_workload(
        "training",
        actual_seconds=training_seconds,
        executed_unit_count=optimizer_steps,
        reason=reason,
        verifier=training_verifier,
        source="real_training_verification",
    )
    if validation_rows is not None:
        session.complete_phase_workload(
            "validation",
            actual_seconds=validation_seconds,
            executed_unit_count=validation_rows * completed_epochs,
            reason=reason,
            verifier=validation_verifier,
            source="real_validation_verification",
        )
    return session.decide_admission(stage="completed_training_workload").decision == "admitted"
