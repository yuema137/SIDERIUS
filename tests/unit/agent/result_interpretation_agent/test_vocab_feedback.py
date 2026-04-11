"""
Unit tests for Phase C vocabulary feedback loop helpers.

Tests evaluate_prediction, generate_discoveries, build_runtime_vocab.
"""
import pytest
from nodes.interpretation_helpers import (
    evaluate_prediction,
    generate_discoveries,
    build_runtime_vocab,
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
