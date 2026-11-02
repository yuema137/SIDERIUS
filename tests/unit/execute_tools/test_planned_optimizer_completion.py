"""Final planned training accounts for adaptive horizons at any workload scale."""

import time

import pytest

from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.training_budget import TrainingBudgetEnvelope
from core.runtime_control.workload import ResolvedPhaseWorkload
from execute_tools.training_budget_execution import (
    TrainingBudgetExecution,
    complete_planned_optimizer_work,
    complete_training_workload,
)


@pytest.mark.parametrize(
    "steps,epochs,seconds", [(4, 1, 0.01), (7168, 3, 430), (10_000_000, 20, 86_400)]
)
def test_adaptive_planned_completion_reconciles_only_optimizer_work(
    tmp_path, steps, epochs, seconds
):
    """Calibration-sized counts cannot replace the executed long-epoch horizon."""
    session = RuntimeVerificationSession(
        str(tmp_path / "completion.json"),
        policy=RuntimeControlPolicy(
            training_budget=TrainingBudgetEnvelope(
                budget_seconds=seconds * 10,
                reserve_fraction=0.2,
                max_epochs=epochs,
                started_monotonic_seconds=time.monotonic(),
            )
        ),
    )
    session.complete_setup(storage_provenance={})
    for phase, unit in [("training", "optimizer_step"), ("validation", "validation_sample")]:
        session.record_phase_workload(
            phase, ResolvedPhaseWorkload(phase=phase, unit=unit, unit_count=4)
        )
    verifier = session.start_phase_verification("training", unit="optimizer_step")
    for _ in range(4):
        verifier.feed(1)
    complete_planned_optimizer_work(
        session,
        verifier=verifier,
        optimizer_steps=steps,
        completed_epochs=epochs,
        training_seconds=seconds,
        epoch0_dataset_seconds=7,
    )
    training = session.observation.components["training"]
    assert training.workload.unit_count == steps
    assert training.actual_seconds == seconds
    assert training.completion is not None
    validation = session.observation.components["validation"]
    assert validation.workload.unit_count == 4
    assert validation.completion is None
    assert validation.actual_seconds is None


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("budgeted", [False, True])
def test_finalization_preserves_planned_boundary(tmp_path, verified, budgeted):
    """Later validation overhead cannot rewrite actuals or calibration provenance."""
    envelope = TrainingBudgetEnvelope(
        budget_seconds=1000,
        reserve_fraction=0.2,
        max_epochs=2,
        started_monotonic_seconds=time.monotonic(),
    )
    session = RuntimeVerificationSession(
        str(tmp_path / "boundary.json"),
        policy=RuntimeControlPolicy(training_budget=envelope if budgeted else None),
    )
    session.complete_setup(storage_provenance={})
    initial = ResolvedPhaseWorkload(
        phase="training", unit="optimizer_step", unit_count=4 if budgeted else 8
    )
    session.record_phase_workload("training", initial)
    session.record_phase_workload(
        "validation",
        ResolvedPhaseWorkload(
            phase="validation", unit="validation_sample", unit_count=2 if budgeted else 4
        ),
    )
    verifier = None
    if verified:
        verifier = session.start_phase_verification("training", unit="optimizer_step")
        for _ in range(initial.unit_count):
            verifier.feed(1)
    complete_planned_optimizer_work(
        session,
        verifier=verifier,
        optimizer_steps=8,
        completed_epochs=2,
        training_seconds=10,
        epoch0_dataset_seconds=1,
    )
    boundary = session.observation.components["training"]
    assert (boundary.completion is not None) == verified
    execution = TrainingBudgetExecution(envelope, proposed_epochs=2) if budgeted else None
    if execution is not None:
        execution.costs = [6, 6]
        execution.optimizer_steps = 8
    complete_training_workload(
        session,
        budget_execution=execution,
        training_verifier=None,
        validation_verifier=None,
        optimizer_steps=8,
        completed_epochs=2,
        epoch_limit=2,
        training_seconds=15,
        validation_seconds=2,
        validation_rows=2,
        epoch0_dataset_seconds=1,
    )
    training = session.observation.components["training"]
    assert training.actual_seconds == 10
    assert training == boundary
    if budgeted:
        assert training.workload.detail["initial_workload"] == initial.model_dump()
        assert session.observation.components["validation"].workload.unit_count == 4
    assert session.observation.components["validation"].actual_seconds == 2
