"""Final planned training accounts for adaptive horizons at any workload scale."""

import time

import pytest

from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.training_budget import TrainingBudgetEnvelope
from core.runtime_control.workload import ResolvedPhaseWorkload
from execute_tools.training_budget_execution import complete_planned_optimizer_work


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
