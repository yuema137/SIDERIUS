"""C8a — characterization fixtures pinning the CURRENT runtime-consumer
numerics before the estimator/policy rewiring.

Every expected value below is a LITERAL derived by hand from the formula
in force today, not a re-computation of the production expression: a
rewiring that changes the arithmetic fails here even if it changes the
code that produces it in the same way. These fixtures are the byte-parity
contract for C8b-C8f.

Pinned formulas (V19 launch configuration):

    admission  : adjusted = Σ(component predicted_seconds) × safety_factor
                 reject iff adjusted > operator_budget_seconds
                 formal safety_factor 2.0, trial record-only
    watchdog   : deadline = max(floor, min(operator_budget,
                                           Σ(predicted) × watchdog_factor))
                 watchdog_factor 3.5, floor 120 s
    TimeEval   : feasible = total_minutes <= budget × (1 + slack)
                 slack 0.10 ONLY on the measured trial_inference_warmup
                 branch; strict comparison otherwise
"""

from __future__ import annotations

import pytest

from core.runtime_control.records import PhaseComponentRecord, RuntimePrediction
from core.runtime_control.session import (
    RuntimeControlPolicy,
    RuntimeVerificationSession,
    WatchdogConfig,
)
from core.sandbox_executor import _watchdog_deadline_provider
from tests.helpers.two_family_profile import make_two_family_profile

# ── the V19 launch constants these fixtures pin ─────────────────────────────
FORMAL_BUDGET_S = 7200.0  # --formal_time_budget_minutes 120
FORMAL_SAFETY = 2.0
WATCHDOG_FACTOR = 3.5
WATCHDOG_FLOOR_S = 120.0
PROFILE = make_two_family_profile(
    num_files=1,
    psd_segment_length=40_000,
    segments_per_file=1,
)

_STORAGE = {
    "dataset_root": "/data",
    "file_count": 1,
    "files_present": 1,
    "expected_raw_bytes": 1_000,
    "filesystem_type": "ext4",
}


def _verified_prediction(seconds: float) -> RuntimePrediction:
    """A measurement-backed, formal-eligible component prediction."""
    return RuntimePrediction(
        predicted_seconds=seconds,
        source="real_training_verification",
        formal_execution_eligible=True,
        steady_state=True,
        verification="passed",
        confidence="high",
        ms_per_unit=10.0,
        n_steady_units=7,
        unit_count=int(seconds * 100),
        safety_factor=1.0,
    )


def _session_with(tmp_path, *, policy, training_seconds: float | None):
    session = RuntimeVerificationSession(str(tmp_path / "rv.json"), policy=policy)
    session.complete_setup(storage_provenance=_STORAGE)
    if training_seconds is not None:
        session._components["training"] = PhaseComponentRecord(
            prediction=_verified_prediction(training_seconds)
        )
    return session


def _formal_policy(**over) -> RuntimeControlPolicy:
    base = dict(
        operator_budget_seconds=FORMAL_BUDGET_S,
        safety_factor=FORMAL_SAFETY,
        trial_safety_factor=3.0,
        formal_safety_factor=FORMAL_SAFETY,
        watchdog=WatchdogConfig(
            enabled=True, floor_seconds=WATCHDOG_FLOOR_S, safety_factor=WATCHDOG_FACTOR
        ),
    )
    base.update(over)
    return RuntimeControlPolicy(**base)


class TestAdmissionParity:
    """Setup is genuinely measured, so it adds a sub-millisecond epsilon to
    the known-cost sum; every scenario is chosen so that epsilon cannot
    flip the verdict, and the numeric assertions carry an explicit 0.5 s
    tolerance that is orders of magnitude larger than it."""

    def test_formal_within_budget_is_admitted(self, tmp_path):
        session = _session_with(tmp_path, policy=_formal_policy(), training_seconds=100.0)
        record = session.decide_admission()
        assert record.decision == "admitted"
        assert record.avoided_predicted_runtime_seconds is None
        # 100 s × 2.0 = 200 s ≤ 7200 s
        assert "known cost 200.0s: completed actual 0.0s" in record.reason
        assert "remaining estimates with safety x2 within budget 7200.0s" in record.reason

    def test_formal_over_budget_is_rejected_with_pinned_avoided_cost(self, tmp_path):
        session = _session_with(tmp_path, policy=_formal_policy(), training_seconds=3700.0)
        record = session.decide_admission()
        assert record.decision == "rejected"
        # 3700 s × 2.0 = 7400 s > 7200 s
        assert record.avoided_predicted_runtime_seconds == pytest.approx(7400.0, abs=0.5)

    def test_rejection_boundary_is_strictly_greater_than(self, tmp_path):
        """adjusted == budget admits; adjusted just above rejects."""
        at_budget = _session_with(tmp_path, policy=_formal_policy(), training_seconds=3599.0)
        assert at_budget.decide_admission().decision == "admitted"  # 7198 s ≤ 7200 s
        over = _session_with(tmp_path / "b", policy=_formal_policy(), training_seconds=3601.0)
        assert over.decide_admission().decision == "rejected"  # 7202 s > 7200 s

    def test_trial_is_record_only(self, tmp_path):
        trial = RuntimeControlPolicy(safety_factor=3.0)  # no operator budget
        session = _session_with(tmp_path, policy=trial, training_seconds=999_999.0)
        record = session.decide_admission()
        assert record.decision == "admitted"
        assert "record-only" in record.reason

    def test_verification_failure_fails_closed_under_a_budget(self, tmp_path):
        session = _session_with(tmp_path, policy=_formal_policy(), training_seconds=None)
        session._verification_failures["training"] = "did not stabilize"
        record = session.decide_admission()
        assert record.decision == "rejected"
        assert "fail closed" in record.reason

    def test_watchdog_override_never_changes_admission(self, tmp_path):
        """The V19 split: admission always reads the shared safety_factor."""
        for watchdog_factor in (None, WATCHDOG_FACTOR, 10.0):
            session = _session_with(
                tmp_path / f"w{watchdog_factor}",
                policy=_formal_policy(
                    watchdog=WatchdogConfig(
                        enabled=True,
                        floor_seconds=WATCHDOG_FLOOR_S,
                        safety_factor=watchdog_factor,
                    )
                ),
                training_seconds=3700.0,
            )
            record = session.decide_admission()
            assert record.decision == "rejected"
            assert record.avoided_predicted_runtime_seconds == pytest.approx(7400.0, abs=0.5)


class TestWatchdogDeadlineParity:
    def _provider(self, monkeypatch, *, policy, predicted_seconds: float | None):
        import core.sandbox_executor as se

        block = (
            {
                "components": {
                    "training": {
                        "prediction": {
                            "predicted_seconds": predicted_seconds,
                            "source": "real_training_verification",
                        }
                    }
                }
            }
            if predicted_seconds is not None
            else {}
        )
        monkeypatch.setattr(se, "_read_runtime_observation_sidecar", lambda _p: block)
        return _watchdog_deadline_provider(policy, "unused")

    @pytest.mark.parametrize(
        ("predicted", "expected_deadline", "expected_source"),
        [
            (1000.0, 3500.0, "verified_components"),  # 1000 × 3.5 < budget
            (10.0, 120.0, "verified_components"),  # 35 → clamped up to the floor
            (3000.0, 7200.0, "operator_budget"),  # 10500 → clamped to the budget
            (None, 7200.0, "operator_budget"),  # nothing verified yet
        ],
    )
    def test_deadline_table(self, monkeypatch, predicted, expected_deadline, expected_source):
        provider = self._provider(monkeypatch, policy=_formal_policy(), predicted_seconds=predicted)
        deadline, source = provider()
        assert deadline == pytest.approx(expected_deadline)
        assert source == expected_source

    def test_watchdog_factor_defaults_to_the_shared_safety_factor(self, monkeypatch):
        policy = _formal_policy(
            watchdog=WatchdogConfig(
                enabled=True, floor_seconds=WATCHDOG_FLOOR_S, safety_factor=None
            )
        )
        provider = self._provider(monkeypatch, policy=policy, predicted_seconds=1000.0)
        # falls back to safety_factor 2.0 → 2000 s, not 3500 s
        assert provider()[0] == pytest.approx(2000.0)

    def test_no_budget_and_no_evidence_disables_the_deadline(self, monkeypatch):
        policy = RuntimeControlPolicy(watchdog=WatchdogConfig(enabled=True))
        provider = self._provider(monkeypatch, policy=policy, predicted_seconds=None)
        assert provider() == (None, "none")

    def test_a_prior_backed_prediction_never_sets_a_deadline(self, monkeypatch):
        """C8d: §7.4 watchdog column — static evidence is `never_used`.
        A prior-sourced component cannot arm the kill deadline; the
        operator budget remains the only bound."""
        import core.sandbox_executor as se

        block = {
            "components": {
                "training": {
                    "prediction": {
                        "predicted_seconds": 10.0,
                        "source": "static_uncalibrated",
                    }
                }
            }
        }
        monkeypatch.setattr(se, "_read_runtime_observation_sidecar", lambda _p: block)
        deadline, source = _watchdog_deadline_provider(_formal_policy(), "unused")()
        assert (deadline, source) == (7200.0, "operator_budget")  # not 120 s floor

        no_budget = RuntimeControlPolicy(
            watchdog=WatchdogConfig(enabled=True, safety_factor=WATCHDOG_FACTOR)
        )
        assert _watchdog_deadline_provider(no_budget, "unused")() == (None, "none")


class TestTimeEvalGateParity:
    """The pre-flight wall-time gate as it behaves today: a private
    comparison inside the skill, with a 10 % slack allowed only on the
    measured inference branch."""

    @staticmethod
    def _run(monkeypatch, *, train_s, inf_s, score_s, hint=None):
        from agent.skills.evaluate_time_skill import wrapper as w

        def _phase(name, seconds, breakdown=None):
            return {"phase": name, "seconds": seconds, "breakdown": breakdown or {}}

        monkeypatch.setattr(w, "_count_params", lambda *a, **k: 45_408)
        monkeypatch.setattr(w, "_detect_gpu_name", lambda: "pinned-gpu")
        monkeypatch.setattr(
            w._training_est,
            "estimate_wall_time_seconds",
            lambda *a, **k: _phase(
                "training",
                train_s,
                {
                    "total_train_steps": 1000,
                    "ms_per_step": 20.0,
                    "k_correction": 1.0,
                    "safety_multiplier": 1.0,
                    "ms_source": "real_dataset_warmup",
                    "formal_execution_eligible": True,
                    "gpu_name": "pinned-gpu",
                },
            ),
        )
        monkeypatch.setattr(
            w._inference_est,
            "estimate_wall_time_seconds",
            lambda *a, **k: _phase(
                "inference", inf_s, {"inference_batch": 25, "inference_batch_uncalibrated": False}
            ),
        )
        monkeypatch.setattr(
            w._scoring_est, "estimate_wall_time_seconds", lambda *a, **k: _phase("scoring", score_s)
        )
        return w.run_skill(
            None,
            model_type="pinned_model",
            model_config={"segmentation_size": 40_000},
            train_config={"batch_size": 8, "epochs": 1},
            loss_config={"loss_type": "ce"},
            sample_set={"0": [0]},
            time_budget_minutes=10.0,
            inference_per_psd_seg_ms_hint=hint,
            dataset_profile=PROFILE,
        )

    def test_under_budget_is_feasible(self, monkeypatch):
        result = self._run(monkeypatch, train_s=300.0, inf_s=120.0, score_s=60.0)
        assert result["feasible"] is True
        assert result["estimated_minutes"] == 8.0
        assert result["breakdown"]["slack_applied"] is False

    def test_over_budget_is_infeasible(self, monkeypatch):
        result = self._run(monkeypatch, train_s=600.0, inf_s=120.0, score_s=60.0)
        assert result["feasible"] is False  # 13.0 min > 10 min
        assert result["estimated_minutes"] == 13.0

    def test_exactly_at_budget_is_feasible(self, monkeypatch):
        result = self._run(monkeypatch, train_s=540.0, inf_s=0.6, score_s=59.4)
        assert result["estimated_minutes"] == 10.0
        assert result["feasible"] is True  # `<=`, not `<`

    def test_measured_inference_branch_gets_ten_percent_slack(self, monkeypatch):
        result = self._run(monkeypatch, train_s=600.0, inf_s=30.0, score_s=15.0, hint=4.0)
        assert result["estimated_minutes"] == 10.75  # > 10 min budget…
        assert result["breakdown"]["inference_ms_source"] == "trial_inference_warmup"
        assert result["breakdown"]["slack_applied"] is True
        assert result["breakdown"]["effective_budget_minutes"] == 11.0
        assert result["feasible"] is True  # …but inside 11.0 min effective budget

    def test_slack_does_not_apply_to_the_fallback_branch(self, monkeypatch):
        result = self._run(monkeypatch, train_s=600.0, inf_s=30.0, score_s=15.0, hint=None)
        assert result["breakdown"]["slack_applied"] is False
        assert result["breakdown"]["effective_budget_minutes"] == 10.0
        assert result["feasible"] is False
