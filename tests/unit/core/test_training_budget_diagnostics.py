"""Budget diagnostics must not turn partial cost evidence into unused budget."""

from core.runtime_control.budget_diagnostics import training_budget_diagnostic
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.workload import ResolvedPhaseWorkload


def test_low_training_projection_names_missing_work_and_preserves_policy(tmp_path):
    session = RuntimeVerificationSession(
        str(tmp_path / "runtime.json"),
        attempt_id="diagnostic",
        policy=RuntimeControlPolicy(operator_budget_seconds=1800),
    )
    session.complete_setup(
        storage_provenance={},
        training_workload=ResolvedPhaseWorkload(
            phase="training", unit="optimizer_step", unit_count=500
        ),
    )
    before = session.observation.model_dump(exclude={"timestamp"})
    initial = training_budget_diagnostic(
        session.observation,
        stage="before_optimizer",
        epochs=2,
        optimizer_steps=500,
        budget_seconds=1800,
    )
    assert initial.predicted_training_seconds is None
    assert initial.predicted_training_budget_fraction is None
    assert initial.missing_prediction_phases == ["training", "validation", "inference", "scoring"]
    assert "Fixed epoch horizon" in initial.message
    assert session.observation.model_dump(exclude={"timestamp"}) == before

    verifier = session.start_phase_verification("training", unit="optimizer_step")
    for _ in range(200):
        verifier.feed(20)
        if verifier.is_terminal:
            break
    session.complete_phase_verification("training", verifier, source="real_training_verification")
    measured = session.observation.model_dump(exclude={"timestamp"})
    report = training_budget_diagnostic(
        session.observation,
        stage="post_training_verification",
        epochs=2,
        optimizer_steps=500,
        budget_seconds=1800,
    )
    assert report.predicted_training_seconds == 10
    assert report.predicted_training_budget_fraction == 10 / 1800
    assert report.missing_prediction_phases == ["validation", "inference", "scoring"]
    assert "LOW_TRAINING_BUDGET_PROJECTION" in report.message
    assert "no unused-budget claim" in report.message
    assert session.observation.model_dump(exclude={"timestamp"}) == measured
