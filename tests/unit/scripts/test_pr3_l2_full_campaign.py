"""
Deterministic tests for the full descriptive Layer-2 campaign package
(`pr3_l2_full_calibration_protocol.md`): S3/S4 fixtures, scorer v2
scenario facts, and the CI math in analyze_full. Zero LLM calls.
"""

import math

from scripts.pr3_l2_calibration.analyze_full import METRICS, newcombe_diff, wilson
from scripts.pr3_l2_calibration.fixtures import (
    SCENARIOS,
    SIG_DIVERSITY,
    SIG_STD,
    fixture_hash,
    s3_carried_history,
    s3_tune_outputs,
    s4_tune_outputs,
)
from scripts.pr3_l2_calibration.scorer import SCORER_VERSION, score_sample


def _proposal(text: str, model_name: str = "new_model_x") -> dict:
    return {
        "model_name": model_name,
        "model_description": text,
        "mathematical_definition": "",
        "motivation": "",
        "baseline_config": {
            "model_config": {"depth": 9, "channels": 99},
            "train_config": {"lr": 1e-3, "epochs": 1},
            "loss_config": {"loss_type": "ce"},
        },
    }


class TestFixtures:
    def test_hashes_stable_and_distinct(self):
        hashes = {s: fixture_hash(s) for s in ("S1", "S2", "S3", "S4")}
        for s, h in hashes.items():
            assert fixture_hash(s) == h, f"{s} hash unstable"
        assert len(set(hashes.values())) == 4, "scenario hashes must be distinct"

    def test_s3_recovery_and_stale_history(self):
        outs = s3_tune_outputs()
        assert len(outs) == 1
        records = outs[0].all_records
        # Current iteration is HEALTHY: every gate passed, valid scores.
        for r in records:
            assert all(g.check_passed for g in r.health_gate_results)
            assert r.denoising_score is not None
        hist = s3_carried_history()
        (entry,) = hist["recovered_gru_c"]
        assert entry.signature == SIG_DIVERSITY
        assert entry.occurrences[0].iteration == 3  # stale: edge of window at N=5
        assert SCENARIOS["S3"]["expected_attribution"] == {"recovered_gru_c": None}

    def test_s4_marginal_conflict_distinct_signature(self):
        outs = s4_tune_outputs()
        r_fail, r_pass = outs[0].all_records
        failed_gates = [g for g in r_fail.health_gate_results if not g.check_passed]
        assert len(failed_gates) == 1
        g = failed_gates[0]
        assert g.gate_name == "output_std_blocking"
        gd = g.model_dump(mode="json")
        assert gd["threshold"]["value"] == 1.0  # near-threshold: 0.9 vs 1.0
        assert gd["metrics"]["aggregate_statistics"]["minimum"] == 0.9
        assert all(x.check_passed for x in r_pass.health_gate_results)
        assert r_pass.denoising_score == 1.18
        assert SIG_STD != SIG_DIVERSITY
        assert SCENARIOS["S4"]["expected_fingerprint"] == SIG_STD


class TestScorerV2:
    def test_version_bumped(self):
        assert SCORER_VERSION == "p3l2-scorer-2"

    def test_s3_stale_as_current_positive(self):
        p = _proposal(
            "The model currently collapses to a single value. "
            "We must fix the diversity failure now."
        )
        rec = score_sample("S3", "T", p, "")
        assert rec["stale_as_current_prescreen"] is True
        assert rec["historical_framing_present"] is False

    def test_s3_historical_framing_negative(self):
        p = _proposal(
            "A prior collapse at iteration 3 was resolved; the current runs "
            "are healthy. We build on the variance-preserving softmax output head."
        )
        rec = score_sample("S3", "T", p, "")
        assert rec["stale_as_current_prescreen"] is False
        assert rec["historical_framing_present"] is True
        assert rec["healthy_mechanism_mentioned"] is True

    def test_s3_mixed_sentence_with_historical_marker_not_stale(self):
        p = _proposal("The collapse is no longer present now; diversity recovered.")
        rec = score_sample("S3", "T", p, "")
        assert rec["stale_as_current_prescreen"] is False

    def test_s4_conflict_and_mechanism_facts(self):
        p = _proposal(
            "The output_std gate failed marginally in one round but passed in "
            "the second. We keep the spectral mode truncation and add per-band "
            "output scaling to raise amplitude."
        )
        rec = score_sample("S4", "C", p, "")
        assert rec["mentions_std_gate_name"] is True
        assert rec["mentions_conflict_or_marginal"] is True
        assert rec["retains_spectral_mechanism"] is True
        assert rec["amplitude_or_scaling_change"] is True

    def test_s4_negative_case(self):
        p = _proposal("A completely new attention denoiser with focal loss.")
        rec = score_sample("S4", "C", p, "")
        assert rec["mentions_conflict_or_marginal"] is False
        assert rec["retains_spectral_mechanism"] is False
        assert rec["amplitude_or_scaling_change"] is False

    def test_s1_s2_facts_unchanged(self):
        p = _proposal("Add layernorm and a softmax head against the collapse.")
        rec1 = score_sample("S1", "T", p, "")
        assert rec1["mentions_normalization_mechanism"] is True
        assert rec1["deterministic_relevant_change"] is True
        rec2 = score_sample("S2", "T", p, "")
        assert "healthy_mechanism_mentioned" in rec2
        assert "cross_attribution_prescreen" in rec2

    def test_metrics_matrix_keys_exist_in_scorer_output(self):
        """Every metric the analysis matrix references must be produced by
        the scorer for that scenario — no silent missing-key zeros."""
        text = (
            "currently collapses; prior iteration 3 resolved; gated spectral "
            "residual path; variance-preserving softmax output head; "
            "output_std marginal; spectral mode truncation; output scaling; "
            "layernorm softmax quantization diversity loss healthgate "
            "collapsing_tcn_a spectral_resnet_b " + SIG_DIVERSITY + " " + SIG_STD
        )
        for scenario, metrics in METRICS.items():
            rec = score_sample(scenario, "T", _proposal(text), "")
            for m in metrics:
                assert m in rec, f"{scenario}: metric {m!r} missing from scorer output"


class TestCIMath:
    def test_wilson_known_value(self):
        rate, lo, hi = wilson(5, 10)
        assert rate == 0.5
        assert 0.23 < lo < 0.25 and 0.75 < hi < 0.77  # ≈ [0.237, 0.763]

    def test_wilson_extremes(self):
        _, lo, hi = wilson(0, 5)
        assert lo == 0.0 and hi < 0.5
        _, lo2, hi2 = wilson(5, 5)
        assert hi2 == 1.0 and lo2 > 0.5
        assert math.isnan(wilson(0, 0)[0])

    def test_newcombe_symmetric_null(self):
        d, lo, hi = newcombe_diff(5, 10, 5, 10)
        assert d == 0.0
        assert lo < 0 < hi
        assert abs(abs(lo) - abs(hi)) < 1e-9

    def test_newcombe_direction(self):
        d, lo, _hi = newcombe_diff(9, 10, 2, 10)
        assert d == 0.7
        assert lo > 0  # clearly separated proportions
        assert math.isnan(newcombe_diff(1, 0, 1, 2)[0])
