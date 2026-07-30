"""C8c — the TimeEval wall-time gate now decides through the SHARED
runtime policy.

Two things must hold at once:

* PARITY — a MEASURED (warmup-backed) projection over budget still
  rejects the round, with the same effective budget and the same 10 %
  measured-inference slack (numeric parity is pinned in
  tests/unit/core/test_c8_consumer_parity.py);
* CORRECTION — a static or historical-prior projection can no longer
  reject a round by itself. That is the authority rule the V19 wave-1
  incident violated: an uncalibrated formula must never gate execution
  (§7.4 matrix rows ``static_prior`` / ``historical_prior_only`` =
  cannot_block).

REJECT (candidate verdict) and ABORT (evidence-channel failure) stay
distinct: ABORT surfaces as an ERROR result the tuner raises on, never
as "this candidate is infeasible".
"""

from __future__ import annotations

import pytest

from agent.skills.evaluate_time_skill.wrapper import _gate_decision


def _shape(*, minutes: float, source: str) -> dict:
    return {
        "status": "success",
        "estimated_minutes": minutes,
        "breakdown": {"source": source},
        "phase_breakdown": {
            "training": {"seconds": minutes * 60.0 * 0.8},
            "inference": {"seconds": minutes * 60.0 * 0.2},
        },
        "inference_batch_uncalibrated": False,
    }


def _decide(*, minutes, source, budget=10.0, phase="trial", probe=False):
    return _gate_decision(
        result_shape=_shape(minutes=minutes, source=source),
        effective_budget_minutes=budget,
        runtime_phase=phase,
        probe_record_available=probe,
    )


class TestMeasuredEvidenceKeepsItsAuthority:
    def test_measured_over_budget_rejects(self):
        decision = _decide(minutes=13.0, source="real_dataset_warmup")
        assert decision["kind"] == "REJECT"
        assert decision["evidence_provenance"] == "real_dataset_warmup"

    def test_measured_within_budget_allows(self):
        assert _decide(minutes=8.0, source="real_dataset_warmup")["kind"] == "ALLOW"

    def test_measured_formal_over_budget_still_rejects(self):
        """Measurement-backed evidence is not affected by probe absence."""
        decision = _decide(minutes=13.0, source="real_dataset_warmup", phase="formal")
        assert decision["kind"] == "REJECT"


class TestPriorEvidenceCannotGate:
    def test_static_over_budget_is_advisory_not_reject(self):
        decision = _decide(minutes=848.0, source="static_uncalibrated")
        assert decision["kind"] == "ADVISORY"
        assert decision["evidence_rank"] == 0
        assert any("advisory" in r for r in decision["reasons"])

    def test_store_prior_over_budget_is_advisory_not_reject(self):
        decision = _decide(minutes=13.0, source="store")
        assert decision["kind"] == "ADVISORY"
        assert decision["evidence_provenance"] == "historical_observation_prior"

    def test_the_wave1_shape_no_longer_gates(self):
        """An 84x static overshoot — the exact wave-1 signature — is
        advisory evidence, not a gate."""
        decision = _decide(minutes=1692.8, source="static_uncalibrated", budget=20.0)
        assert decision["kind"] != "REJECT"


class TestFormalMissingProbe:
    def test_formal_prior_evidence_requests_a_probe(self):
        decision = _decide(minutes=13.0, source="static_uncalibrated", phase="formal")
        assert decision["kind"] == "REQUEST_PROBE"
        assert any("bounded live measurement is required" in r for r in decision["reasons"])

    def test_formal_within_budget_prior_still_requests_a_probe(self):
        """A formal decision may not rest on a prior even when the prior is
        comfortable — the requirement is measurement, not optimism."""
        decision = _decide(minutes=1.0, source="static_uncalibrated", phase="formal")
        assert decision["kind"] == "REQUEST_PROBE"

    def test_trial_prior_evidence_does_not_request_a_probe(self):
        assert _decide(minutes=13.0, source="static_uncalibrated")["kind"] == "ADVISORY"

    def test_a_present_probe_record_removes_the_request(self):
        decision = _decide(minutes=13.0, source="static_uncalibrated", phase="formal", probe=True)
        assert decision["kind"] == "ADVISORY"


class TestEvidenceChannelFailure:
    def test_uninterpretable_source_aborts(self):
        decision = _decide(minutes=5.0, source="something_unknown")
        assert decision["kind"] == "ABORT"
        assert "uninterpretable runtime evidence" in decision["reasons"][0]

    def test_abort_surfaces_as_an_error_result_not_an_infeasible_verdict(self, monkeypatch):
        from agent.skills.evaluate_time_skill import wrapper as w

        def _phase(name, seconds, breakdown=None):
            return {"phase": name, "seconds": seconds, "breakdown": breakdown or {}}

        monkeypatch.setattr(w, "_count_params", lambda *a, **k: 1000)
        monkeypatch.setattr(w, "_detect_gpu_name", lambda: None)
        monkeypatch.setattr(
            w._training_est,
            "estimate_wall_time_seconds",
            lambda *a, **k: _phase(
                "training",
                60.0,
                {
                    "total_train_steps": 10,
                    "ms_per_step": 1.0,
                    "k_correction": 1.0,
                    "safety_multiplier": 1.0,
                    "ms_source": "a_source_from_the_future",
                    "formal_execution_eligible": False,
                    "gpu_name": None,
                },
            ),
        )
        monkeypatch.setattr(
            w._inference_est,
            "estimate_wall_time_seconds",
            lambda *a, **k: _phase(
                "inference", 1.0, {"inference_batch": 25, "inference_batch_uncalibrated": False}
            ),
        )
        monkeypatch.setattr(
            w._scoring_est, "estimate_wall_time_seconds", lambda *a, **k: _phase("scoring", 1.0)
        )
        result = w.run_skill(
            None,
            model_type="m",
            model_config={"segmentation_size": 40_000},
            train_config={"batch_size": 1, "epochs": 1},
            loss_config={"loss_type": "ce"},
            sample_set={"0": [0]},
            time_budget_minutes=10.0,
        )
        assert result["status"] == "error"
        assert "ABORT" in result["message"]
        assert "feasible" not in result  # never a candidate-level verdict


class TestDecisionIsRecorded:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("real_dataset_warmup", "REJECT"),
            ("static_uncalibrated", "ADVISORY"),
            ("store", "ADVISORY"),
        ],
    )
    def test_policy_identity_and_kind_travel_with_the_decision(self, source, expected):
        decision = _decide(minutes=13.0, source=source)
        assert decision["kind"] == expected
        assert decision["policy_identity"].startswith("runtime_decision_policy@")
