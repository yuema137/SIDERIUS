"""
Unit tests for Phase C vocabulary feedback loop helpers.

Tests evaluate_prediction, generate_discoveries, build_runtime_vocab,
promote_candidates (C.11), and seen_in_runs tracking (C.5-3).
"""
import pytest
from nodes.interpretation_helpers import (
    evaluate_prediction,
    generate_discoveries,
    build_runtime_vocab,
    promote_candidates,
)
from agent.schemas.proposal import VocabEntry


# ---------------------------------------------------------------------------
# evaluate_prediction
# ---------------------------------------------------------------------------

class TestEvaluatePrediction:

    def test_confirmed(self):
        pred = {
            "metric": "denoising_score",
            "current_value": 5.0,
            "predicted_value": 6.0,
            "threshold_for_refutation": 4.5,
        }
        result = evaluate_prediction(pred, {"best_denoising_score": 6.5})
        assert result["outcome"] == "confirmed"
        assert result["actual_value"] == 6.5
        assert result["boldness"] > 0

    def test_refuted(self):
        pred = {
            "metric": "denoising_score",
            "current_value": 5.0,
            "predicted_value": 6.0,
            "threshold_for_refutation": 4.5,
        }
        result = evaluate_prediction(pred, {"best_denoising_score": 4.0})
        assert result["outcome"] == "refuted"

    def test_partial(self):
        pred = {
            "metric": "denoising_score",
            "current_value": 5.0,
            "predicted_value": 6.0,
            "threshold_for_refutation": 4.5,
        }
        result = evaluate_prediction(pred, {"best_denoising_score": 5.5})
        assert result["outcome"] == "partial"

    def test_file_vector_metric(self):
        pred = {
            "metric": "mean(file_vector[0:5])",
            "current_value": 0.5,
            "predicted_value": 2.0,
            "threshold_for_refutation": 0.3,
        }
        fv = [1.0, 1.5, 2.0, 2.5, 3.0] + [None] * 15
        result = evaluate_prediction(pred, {
            "best_denoising_score": 5.0,
            "best_file_vector": fv,
        })
        assert result["actual_value"] == 2.0  # mean of [1, 1.5, 2, 2.5, 3]
        assert result["outcome"] == "confirmed"

    def test_missing_results(self):
        pred = {
            "metric": "denoising_score",
            "current_value": 5.0,
            "predicted_value": 6.0,
            "threshold_for_refutation": 4.5,
        }
        result = evaluate_prediction(pred, {})
        assert result["outcome"] == "partial"
        assert "Could not compute" in result.get("notes", "")

    def test_boldness_calculation(self):
        pred = {
            "metric": "denoising_score",
            "current_value": 5.0,
            "predicted_value": 6.0,
            "threshold_for_refutation": 4.5,
        }
        result = evaluate_prediction(pred, {"best_denoising_score": 6.5})
        # boldness = |6.0 - 5.0| / |5.0| = 0.2
        assert abs(result["boldness"] - 0.2) < 0.01

    def test_information_gain_confirmed(self):
        pred = {
            "metric": "denoising_score",
            "current_value": 5.0,
            "predicted_value": 6.0,
            "threshold_for_refutation": 4.5,
        }
        result = evaluate_prediction(pred, {"best_denoising_score": 6.5})
        assert result["information_gain"] > 0  # confirmed = boldness

    def test_information_gain_refuted(self):
        pred = {
            "metric": "denoising_score",
            "current_value": 5.0,
            "predicted_value": 6.0,
            "threshold_for_refutation": 4.5,
        }
        result = evaluate_prediction(pred, {"best_denoising_score": 4.0})
        assert result["information_gain"] == 0  # refuted = 0


# ---------------------------------------------------------------------------
# generate_discoveries
# ---------------------------------------------------------------------------

class TestGenerateDiscoveries:

    def test_confirmed_prediction(self):
        eval_result = {
            "outcome": "confirmed",
            "metric": "denoising_score",
            "predicted_value": 6.0,
            "actual_value": 6.5,
        }
        discoveries = generate_discoveries(
            prediction_eval=eval_result,
            model_type="attn_wavenet",
            best_score=6.5,
            inherited_components=[{"component": "dilated_causal_conv"}],
            proposed_vocab_links=[],
        )
        assert len(discoveries) >= 1
        assert any("CONFIRMED" in d.description for d in discoveries)
        assert all(d.kind == "discovery" for d in discoveries)

    def test_refuted_prediction(self):
        eval_result = {
            "outcome": "refuted",
            "metric": "denoising_score",
            "predicted_value": 6.0,
            "actual_value": 4.0,
        }
        discoveries = generate_discoveries(
            prediction_eval=eval_result,
            model_type="bad_model",
            best_score=4.0,
            inherited_components=[],
            proposed_vocab_links=[],
        )
        assert any("REFUTED" in d.description for d in discoveries)

    def test_partial_with_none_actual(self):
        """Regression: actual_value=None should not crash format string."""
        eval_result = {
            "outcome": "partial",
            "metric": "denoising_score",
            "predicted_value": 6.8,
            "actual_value": None,
        }
        discoveries = generate_discoveries(
            prediction_eval=eval_result,
            model_type="transformer_wavenet",
            best_score=None,
            inherited_components=[],
            proposed_vocab_links=[],
        )
        assert any("PARTIAL" in d.description for d in discoveries)
        assert any("N/A" in d.description for d in discoveries)

    def test_no_prediction(self):
        discoveries = generate_discoveries(
            prediction_eval=None,
            model_type="test_model",
            best_score=5.0,
            inherited_components=[],
            proposed_vocab_links=[],
        )
        # No prediction = no prediction discovery, but might still have score comparison
        assert all(d.kind == "discovery" for d in discoveries)

    def test_score_vs_sota(self):
        eval_result = {
            "outcome": "confirmed",
            "metric": "denoising_score",
            "predicted_value": 6.0,
            "actual_value": 6.5,
            "current_value": 5.5,
        }
        discoveries = generate_discoveries(
            prediction_eval=eval_result,
            model_type="new_model",
            best_score=6.5,
            inherited_components=[],
            proposed_vocab_links=[],
        )
        score_discoveries = [d for d in discoveries if "score" in d.name]
        assert len(score_discoveries) >= 1
        assert any("beating" in d.description for d in score_discoveries)


# ---------------------------------------------------------------------------
# build_runtime_vocab
# ---------------------------------------------------------------------------

class TestBuildRuntimeVocab:

    def test_seed_only(self):
        seed = [
            VocabEntry(name="dilated_causal_conv", kind="feature", description="test"),
            VocabEntry(name="receptive_field", kind="capability", description="test"),
        ]
        result = build_runtime_vocab(seed, [], [])
        assert len(result) == 2

    def test_adds_discoveries(self):
        seed = [VocabEntry(name="feature_a", kind="feature", description="test")]
        discovery = VocabEntry(name="discovery_1", kind="discovery", description="Found X")
        result = build_runtime_vocab(seed, [discovery], [])
        assert len(result) == 2
        names = {v.name for v in result}
        assert "discovery_1" in names

    def test_deduplicates_by_name(self):
        seed = [VocabEntry(name="feature_a", kind="feature", description="original")]
        discovery = VocabEntry(name="feature_a", kind="feature", description="updated")
        result = build_runtime_vocab(seed, [discovery], [])
        assert len(result) == 1
        # Discovery overwrites seed entry with same name
        assert result[0].description == "updated"

    def test_adds_candidates(self):
        seed = [VocabEntry(name="feature_a", kind="feature", description="test")]
        candidates = [{"name": "new_feature", "kind": "feature", "description": "discovered"}]
        result = build_runtime_vocab(seed, [], candidates)
        assert len(result) == 2

    def test_vocab_grows_across_iterations(self):
        """Simulate 3 iterations of vocab growth."""
        # Iteration 1: seed only
        vocab = build_runtime_vocab(
            [VocabEntry(name="f1", kind="feature", description="feature 1")],
            [], [],
        )
        assert len(vocab) == 1

        # Iteration 2: add a discovery
        vocab = build_runtime_vocab(
            vocab,
            [VocabEntry(name="d1", kind="discovery", description="finding 1")],
            [],
        )
        assert len(vocab) == 2

        # Iteration 3: add another discovery + a candidate
        vocab = build_runtime_vocab(
            vocab,
            [VocabEntry(name="d2", kind="discovery", description="finding 2")],
            [{"name": "f2", "kind": "feature", "description": "new feature"}],
        )
        assert len(vocab) == 4
        kinds = {v.kind for v in vocab}
        assert kinds == {"feature", "discovery"}


# ---------------------------------------------------------------------------
# promote_candidates (C.11)
# ---------------------------------------------------------------------------

def _make_candidate(name, kind="feature", seen_in_runs=None, tier="candidate"):
    return VocabEntry(
        name=name, kind=kind, description="test",
        tier=tier,
        seen_in_runs=seen_in_runs or [],
    )


class TestPromoteCandidates:

    def test_feature_with_enough_runs_promoted(self):
        entry = _make_candidate("log_fno", kind="feature", seen_in_runs=["r1", "r2", "r3"])
        vocab, promoted = promote_candidates([entry])
        assert promoted == ["log_fno"]
        assert vocab[0].tier == "canonical"

    def test_capability_with_enough_runs_promoted(self):
        entry = _make_candidate("freq_selectivity", kind="capability", seen_in_runs=["r1", "r2", "r3"])
        vocab, promoted = promote_candidates([entry])
        assert promoted == ["freq_selectivity"]
        assert vocab[0].tier == "canonical"

    def test_insufficient_runs_stays_candidate(self):
        entry = _make_candidate("log_fno", seen_in_runs=["r1", "r2"])
        vocab, promoted = promote_candidates([entry])
        assert promoted == []
        assert vocab[0].tier == "candidate"

    def test_discovery_never_promoted_regardless_of_runs(self):
        entry = _make_candidate("disc_finding", kind="discovery", seen_in_runs=["r1", "r2", "r3", "r4", "r5"])
        vocab, promoted = promote_candidates([entry])
        assert promoted == []
        assert vocab[0].tier == "candidate"

    def test_already_canonical_untouched(self):
        entry = _make_candidate("dilated_causal_conv", tier="canonical", seen_in_runs=[])
        vocab, promoted = promote_candidates([entry])
        assert promoted == []
        assert vocab[0].tier == "canonical"

    def test_returns_correct_promoted_names(self):
        entries = [
            _make_candidate("a", seen_in_runs=["r1", "r2", "r3"]),
            _make_candidate("b", seen_in_runs=["r1", "r2"]),
            _make_candidate("c", seen_in_runs=["r1", "r2", "r3", "r4"]),
        ]
        _, promoted = promote_candidates(entries)
        assert set(promoted) == {"a", "c"}

    def test_custom_min_runs(self):
        entry = _make_candidate("log_fno", seen_in_runs=["r1", "r2"])
        vocab, promoted = promote_candidates([entry], min_runs=2)
        assert promoted == ["log_fno"]
        assert vocab[0].tier == "canonical"

    def test_empty_vocab(self):
        vocab, promoted = promote_candidates([])
        assert vocab == []
        assert promoted == []

    def test_mixed_vocab_only_eligible_promoted(self):
        entries = [
            _make_candidate("feat_a", kind="feature", seen_in_runs=["r1", "r2", "r3"]),
            _make_candidate("feat_b", kind="feature", seen_in_runs=["r1"]),
            _make_candidate("disc_x", kind="discovery", seen_in_runs=["r1", "r2", "r3"]),
            _make_candidate("canon_y", tier="canonical"),
        ]
        vocab, promoted = promote_candidates(entries)
        assert promoted == ["feat_a"]
        by_name = {e.name: e for e in vocab}
        assert by_name["feat_a"].tier == "canonical"
        assert by_name["feat_b"].tier == "candidate"
        assert by_name["disc_x"].tier == "candidate"
        assert by_name["canon_y"].tier == "canonical"


# ---------------------------------------------------------------------------
# seen_in_runs tracking in build_runtime_vocab (C.5-3)
# ---------------------------------------------------------------------------

class TestSeenInRunsTracking:

    def test_new_candidate_gets_proposed_by_run(self):
        candidate = {"name": "gated_fno", "kind": "feature", "description": "test", "proposed_by_run": "wavenet_v2"}
        result = build_runtime_vocab([], [], [candidate])
        entry = next(e for e in result if e.name == "gated_fno")
        assert entry.seen_in_runs == ["wavenet_v2"]

    def test_existing_candidate_seen_in_runs_extended(self):
        """Second iteration adds a new run to an existing candidate."""
        # Iteration 1: candidate first appears
        vocab = build_runtime_vocab(
            [],
            [],
            [{"name": "gated_fno", "kind": "feature", "description": "test", "proposed_by_run": "model_a"}],
        )
        assert next(e for e in vocab if e.name == "gated_fno").seen_in_runs == ["model_a"]

        # Iteration 2: same candidate proposed by a different model
        vocab = build_runtime_vocab(
            vocab,
            [],
            [{"name": "gated_fno", "kind": "feature", "description": "test", "proposed_by_run": "model_b"}],
        )
        entry = next(e for e in vocab if e.name == "gated_fno")
        assert set(entry.seen_in_runs) == {"model_a", "model_b"}

    def test_same_run_not_duplicated_in_seen_in_runs(self):
        """If the same run proposes the same candidate twice, seen_in_runs stays deduplicated."""
        candidate = {"name": "gated_fno", "kind": "feature", "description": "test", "proposed_by_run": "model_a"}
        vocab = build_runtime_vocab([], [], [candidate])
        # Same run again
        vocab = build_runtime_vocab(vocab, [], [candidate])
        entry = next(e for e in vocab if e.name == "gated_fno")
        assert entry.seen_in_runs.count("model_a") == 1

    def test_missing_proposed_by_run_no_crash(self):
        """Candidates without proposed_by_run are added but seen_in_runs stays empty."""
        candidate = {"name": "mystery_feature", "kind": "feature", "description": "no run info"}
        result = build_runtime_vocab([], [], [candidate])
        entry = next(e for e in result if e.name == "mystery_feature")
        assert entry.seen_in_runs == []

    def test_seen_in_runs_enables_promotion_after_three_iterations(self):
        """End-to-end: three iterations of the same candidate → promote_candidates fires."""
        candidate_base = {"name": "log_fno", "kind": "feature", "description": "test"}

        vocab = []
        for run in ["model_a", "model_b", "model_c"]:
            vocab = build_runtime_vocab(
                vocab, [],
                [{**candidate_base, "proposed_by_run": run}],
            )

        entry = next(e for e in vocab if e.name == "log_fno")
        assert set(entry.seen_in_runs) == {"model_a", "model_b", "model_c"}

        # Now promote_candidates should fire
        vocab, promoted = promote_candidates(vocab)
        assert "log_fno" in promoted
        assert next(e for e in vocab if e.name == "log_fno").tier == "canonical"
