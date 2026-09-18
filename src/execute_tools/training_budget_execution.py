"""Training-loop adapter for cooperative budgeting and execution receipts."""

from __future__ import annotations

import time

from core.runtime_control.phases import RuntimePhase
from core.runtime_control.session import RuntimeVerificationSession
from core.runtime_control.training_budget import (
    TrainingBudgetDecision,
    TrainingBudgetEnvelope,
    TrainingBudgetReceipt,
    decide_training_budget,
)
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

    def receipt(self) -> dict:
        if self.last_decision is None or self.last_decision.action != "stop":
            raise RuntimeError("Training budget has no completed stop decision")
        return TrainingBudgetReceipt(
            policy=self.envelope,
            proposed_epochs=self.proposed_epochs,
            completed_epochs=len(self.costs),
            optimizer_steps=self.optimizer_steps,
            epoch_seconds_including_validation=self.costs,
            stop=self.last_decision,
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
