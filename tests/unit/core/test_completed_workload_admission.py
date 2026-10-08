"""Actual completed work is not a throughput forecast or a partial-work waiver."""

import pytest

from core.runtime_control.adaptive import AdaptiveVerificationConfig
from core.runtime_control.observation_store import component_calibration_eligible
from core.runtime_control.records import RuntimeObservation
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.workload import ResolvedPhaseWorkload


def _session(tmp_path, **policy):
    session = RuntimeVerificationSession(
        str(tmp_path / "timing.json"), policy=RuntimeControlPolicy(**policy)
    )
    session.complete_setup(storage_provenance={})
    session.record_phase_workload(
        "training", ResolvedPhaseWorkload(phase="training", unit="optimizer_step", unit_count=4)
    )
    return session


def _short_verifier(session):
    verifier = session.start_phase_verification("training", unit="optimizer_step")
    for _ in range(4):
        verifier.feed(1)
    return verifier


def _finish(session, verifier, **kwargs):
    session.complete_phase_workload(
        "training",
        verifier=verifier,
        source="real_training_verification",
        executed_unit_count=4,
        **kwargs,
    )


def test_complete_actual_is_unmultiplied_and_not_a_calibration_prior(tmp_path):
    session = _session(tmp_path, operator_budget_seconds=3, safety_factor=10)
    _finish(session, _short_verifier(session), actual_seconds=2)
    assert session.decide_admission().decision == "admitted"
    session.finalize("completed")
    component = session.observation.components["training"]
    assert component.prediction is None
    assert component.completion.verification_basis == "workload_exhausted"
    assert not component_calibration_eligible(session.observation, "training")
    # Even a detected but too-short plateau must not become a reusable rate.
    raw = session.observation.model_dump()
    raw["components"]["training"]["measurement"]["steady_state_reached"] = True
    assert not component_calibration_eligible(RuntimeObservation.model_validate(raw), "training")


def test_complete_actual_over_budget_is_rejected(tmp_path):
    session = _session(tmp_path, operator_budget_seconds=1)
    _finish(session, _short_verifier(session), actual_seconds=2)
    assert session.decide_admission().reason_code == "budget_exceeded"


def test_plain_actual_does_not_promote_partial_evidence(tmp_path):
    session = _session(tmp_path, operator_budget_seconds=10)
    session.complete_phase_verification(
        "training", _short_verifier(session), source="real_training_verification"
    )
    session.record_phase_actual("training", 0.01)
    assert session.decide_admission().reason_code == "verification_failed"
    assert session.observation.components["training"].completion is None


def test_count_mismatch_and_invalid_actual_are_not_completion(tmp_path):
    session = _session(tmp_path)
    verifier = _short_verifier(session)
    with pytest.raises(ValueError, match="completed count"):
        session.complete_phase_workload(
            "training",
            actual_seconds=1,
            executed_unit_count=3,
            verifier=verifier,
            source="real_training_verification",
        )
    for duration in [0, -1, float("nan"), float("inf")]:
        with pytest.raises(ValueError, match="finite positive"):
            _finish(session, verifier, actual_seconds=duration)
    assert not verifier.is_terminal


@pytest.mark.parametrize("failure", ["last_unit_cap", "late_wall_cap"])
def test_true_end_cannot_erase_a_verification_cap(tmp_path, monkeypatch, failure):
    clock = [0.0]
    monkeypatch.setattr("core.runtime_control.adaptive.time.monotonic", lambda: clock[0])
    session = _session(
        tmp_path,
        operator_budget_seconds=100,
        verification=AdaptiveVerificationConfig(
            max_wall_ms=4 if failure == "last_unit_cap" else 1000
        ),
    )
    verifier = session.start_phase_verification("training", unit="optimizer_step")
    for _ in range(4 if failure == "last_unit_cap" else 2):
        verifier.feed(1)
    if failure == "late_wall_cap":
        clock[0] = 2
    _finish(session, verifier, actual_seconds=0.01)
    assert session.decide_admission().reason_code == "verification_failed"
    assert session.observation.components["training"].completion is None


def test_completed_cost_does_not_hide_evidence_channel_failure(tmp_path):
    session = _session(tmp_path, operator_budget_seconds=100)
    _finish(session, _short_verifier(session), actual_seconds=1)
    session.record_evidence_channel_failure("missing child receipt")
    assert session.decide_admission().reason_code == "evidence_channel_failure"


def test_strict_policy_preserves_failed_component_shape(tmp_path):
    session = _session(
        tmp_path, runtime_completion_policy="verified-prediction-v1", operator_budget_seconds=100
    )
    verifier = _short_verifier(session)
    session.complete_phase_verification("training", verifier, source="real_training_verification")
    assert session.decide_admission().reason_code == "verification_failed"
    assert "completion" not in session.observation.components["training"].model_dump()
    with pytest.raises(ValueError, match="disabled"):
        _finish(session, verifier, actual_seconds=1)


@pytest.mark.parametrize(("budget", "expected"), [(22, "rejected"), (24, "admitted")])
def test_actual_setup_training_plus_remaining_estimate_are_counted_once(
    tmp_path, monkeypatch, budget, expected
):
    clock = [0.0]
    monkeypatch.setattr("core.runtime_control.session.time.perf_counter", lambda: clock[0])
    session = RuntimeVerificationSession(
        str(tmp_path / "mixed.json"),
        policy=RuntimeControlPolicy(operator_budget_seconds=budget, safety_factor=2),
    )
    clock[0] = 1.0
    session.complete_setup(storage_provenance={})
    session.record_phase_workload(
        "training", ResolvedPhaseWorkload(phase="training", unit="optimizer_step", unit_count=4)
    )
    _finish(session, _short_verifier(session), actual_seconds=2)
    session.record_phase_workload(
        "validation",
        ResolvedPhaseWorkload(phase="validation", unit="validation_sample", unit_count=100),
    )
    verifier = session.start_phase_verification("validation", unit="validation_sample")
    while not verifier.is_terminal:
        verifier.feed(100)
    prediction = session.complete_phase_verification(
        "validation", verifier, source="real_validation_verification"
    )
    assert prediction.predicted_seconds == 10
    decision = session.decide_admission()
    # 1 setup actual + 2 training actual + (10 remaining validation x 2) = 23.
    assert decision.decision == expected
    if expected == "rejected":
        assert decision.avoided_predicted_runtime_seconds == 20
