"""
Unit tests for Phase C+E vocabulary feedback loop helpers.

Tests evaluate_prediction, generate_discoveries, build_runtime_vocab,
promote_candidates (C.11), seen_in_runs tracking (C.5-3),
compute_vocab_diversity_ratio (centrifugal health metric),
update_vocab_link_confirmations (E.7), and scientific_accuracy
accumulation helpers (E.4).
"""
import pytest
from nodes.interpretation_helpers import (
    evaluate_prediction,
    generate_discoveries,
    build_runtime_vocab,
    promote_candidates,
    compute_vocab_diversity_ratio,
    update_vocab_link_confirmations,
)
from agent.schemas.proposal import VocabEntry


# ---------------------------------------------------------------------------
# evaluate_prediction
# ---------------------------------------------------------------------------

class TestEvaluatePrediction:
    """
    evaluate_prediction compares actual score against the SOTA at proposal time
    (current_value in the prediction dict, or explicit current_sota override).
    Outcomes are preset labels: confirmed / partial / refuted.
    """

    def _pred(self, current_value=5.0, predicted_value=6.0, metric="denoising_score"):
        return {
            "metric": metric,
            "current_value": current_value,
            "predicted_value": predicted_value,
        }

    # --- Core outcome labels ---

    def test_confirmed_beats_sota(self):
        """actual > sota → confirmed, delta_from_sota > 0."""
        result = evaluate_prediction(self._pred(current_value=5.0), {"best_denoising_score": 5.5})
        assert result["outcome"] == "confirmed"
        assert result["actual_value"] == 5.5
        assert result["delta_from_sota"] > 0

    def test_partial_within_margin(self):
        """actual slightly below sota but within 5% → partial, delta_from_sota < 0."""
        # sota=5.0, margin=0.05 → partial if actual >= 4.75
        result = evaluate_prediction(self._pred(current_value=5.0), {"best_denoising_score": 4.8})
        assert result["outcome"] == "partial"
        assert result["delta_from_sota"] < 0

    def test_refuted_clearly_below_sota(self):
        """actual clearly below sota (> 5% gap) → refuted."""
        # sota=5.0, 5% threshold=4.75 → refuted if actual < 4.75
        result = evaluate_prediction(self._pred(current_value=5.0), {"best_denoising_score": 4.0})
        assert result["outcome"] == "refuted"
        assert result["delta_from_sota"] < 0

    def test_exactly_at_sota_is_partial(self):
        """actual == sota (not strictly greater) → partial (not confirmed)."""
        result = evaluate_prediction(self._pred(current_value=5.0), {"best_denoising_score": 5.0})
        assert result["outcome"] == "partial"
        assert result["delta_from_sota"] == 0.0

    # --- current_sota parameter ---

    def test_current_sota_override_takes_precedence(self):
        """Explicit current_sota replaces prediction['current_value']."""
        pred = self._pred(current_value=5.0)  # stale SOTA in prediction
        # Pass fresher SOTA of 6.0 — actual=6.5 should still confirm
        result = evaluate_prediction(pred, {"best_denoising_score": 6.5}, current_sota=6.0)
        assert result["outcome"] == "confirmed"
        assert result["current_sota"] == 6.0
        assert abs(result["delta_from_sota"] - 0.5) < 1e-6

    def test_missing_current_sota_falls_back_to_current_value(self):
        """Without override, current_value from prediction is used."""
        result = evaluate_prediction(self._pred(current_value=5.0), {"best_denoising_score": 6.0})
        assert result["current_sota"] == 5.0

    def test_partial_margin_custom(self):
        """Custom partial_margin=0.10 widens the partial band."""
        # sota=5.0, 10% threshold=4.5 → actual=4.6 is partial (not refuted)
        result = evaluate_prediction(
            self._pred(current_value=5.0),
            {"best_denoising_score": 4.6},
            partial_margin=0.10,
        )
        assert result["outcome"] == "partial"

    # --- File vector metric ---

    def test_file_vector_metric_confirmed(self):
        """mean(file_vector[0:5]) above SOTA → confirmed."""
        pred = {
            "metric": "mean(file_vector[0:5])",
            "current_value": 1.5,
            "predicted_value": 2.5,
        }
        fv = [1.0, 1.5, 2.0, 2.5, 3.0] + [None] * 15
        result = evaluate_prediction(pred, {"best_denoising_score": 5.0, "best_file_vector": fv})
        assert result["actual_value"] == 2.0  # mean of [1, 1.5, 2, 2.5, 3]
        assert result["outcome"] == "confirmed"  # 2.0 > 1.5 SOTA

    # --- Missing data fallback ---

    def test_missing_actual_results(self):
        """No metric data in actual_results → partial with notes."""
        result = evaluate_prediction(self._pred(), {})
        assert result["outcome"] == "partial"
        assert "Could not compute" in result.get("notes", "")
        assert result["delta_from_sota"] is None

    def test_missing_current_sota_and_current_value(self):
        """Neither override nor current_value → partial with notes."""
        result = evaluate_prediction(
            {"metric": "denoising_score", "predicted_value": 6.0},
            {"best_denoising_score": 6.5},
        )
        assert result["outcome"] == "partial"
        assert result["current_sota"] is None

    # --- Boldness and information_gain ---

    def test_boldness_uses_sota_baseline(self):
        """boldness = |predicted - sota| / |sota|."""
        # predicted=6.0, sota=5.0 → boldness = 1.0/5.0 = 0.2
        result = evaluate_prediction(self._pred(current_value=5.0, predicted_value=6.0),
                                     {"best_denoising_score": 5.5})
        assert abs(result["boldness"] - 0.2) < 1e-4

    def test_boldness_zero_when_no_predicted_value(self):
        """No predicted_value in prediction → boldness=0."""
        result = evaluate_prediction(
            {"metric": "denoising_score", "current_value": 5.0},
            {"best_denoising_score": 6.0},
        )
        assert result["boldness"] == 0.0

    def test_information_gain_confirmed_equals_delta(self):
        """Confirmed outcome: information_gain = delta_from_sota."""
        result = evaluate_prediction(self._pred(current_value=5.0), {"best_denoising_score": 5.5})
        assert result["outcome"] == "confirmed"
        assert abs(result["information_gain"] - result["delta_from_sota"]) < 1e-6

    def test_information_gain_zero_when_refuted(self):
        """Refuted outcome: information_gain = 0."""
        result = evaluate_prediction(self._pred(current_value=5.0), {"best_denoising_score": 3.0})
        assert result["outcome"] == "refuted"
        assert result["information_gain"] == 0.0

    def test_information_gain_zero_when_partial(self):
        """Partial outcome: information_gain = 0."""
        result = evaluate_prediction(self._pred(current_value=5.0), {"best_denoising_score": 4.8})
        assert result["outcome"] == "partial"
        assert result["information_gain"] == 0.0


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
            "actual_value": 6.5,
            "current_sota": 5.5,  # evaluate_prediction now returns current_sota (not current_value)
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

    def test_overall_best_score_overrides_stale_sota(self):
        """
        When overall_best_score > prediction_eval current_sota, the discovery
        should use the higher value as the SOTA baseline. Without this fix the
        agent would report "beat SOTA" against an already-superseded reference.
        """
        eval_result = {
            "outcome": "confirmed",
            "metric": "denoising_score",
            "actual_value": 6.5,
            "current_sota": 5.5,  # stale — a newer model already scored 6.2
        }
        discoveries = generate_discoveries(
            prediction_eval=eval_result,
            model_type="new_model",
            best_score=6.5,
            inherited_components=[],
            proposed_vocab_links=[],
            overall_best_score=6.2,  # real current SOTA this iteration
        )
        score_disc = next((d for d in discoveries if "score" in d.name), None)
        assert score_disc is not None
        # 6.5 beats 6.2 → "beating" expected
        assert "beating" in score_disc.description
        # The baseline used must be 6.2, not 5.5
        assert "6.2" in score_disc.description

    def test_overall_best_score_negates_false_beat(self):
        """
        When the new model's score exceeds the stale prediction SOTA but NOT
        the real current SOTA, the discovery must NOT say "beating".
        """
        eval_result = {
            "outcome": "partial",
            "metric": "denoising_score",
            "actual_value": 5.8,
            "current_sota": 5.5,  # stale SOTA — model appears to beat it
        }
        discoveries = generate_discoveries(
            prediction_eval=eval_result,
            model_type="new_model",
            best_score=5.8,
            inherited_components=[],
            proposed_vocab_links=[],
            overall_best_score=6.0,  # real SOTA is higher — model did NOT beat it
        )
        score_disc = next((d for d in discoveries if "score" in d.name), None)
        assert score_disc is not None
        assert "beating" not in score_disc.description

    def test_overall_best_score_only_no_prediction(self):
        """When there is no prediction_eval, overall_best_score alone is used as SOTA."""
        discoveries = generate_discoveries(
            prediction_eval=None,
            model_type="new_model",
            best_score=5.8,
            inherited_components=[],
            proposed_vocab_links=[],
            overall_best_score=5.5,
        )
        score_disc = next((d for d in discoveries if "score" in d.name), None)
        assert score_disc is not None
        assert "beating" in score_disc.description


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


# ---------------------------------------------------------------------------
# compute_vocab_diversity_ratio (centrifugal health metric)
# ---------------------------------------------------------------------------

class TestComputeVocabDiversityRatio:

    def test_empty_vocab_returns_zero(self):
        assert compute_vocab_diversity_ratio([]) == 0.0

    def test_all_canonical_returns_zero(self):
        """No candidates → no diversity → ratio = 0."""
        vocab = [
            VocabEntry(name="a", kind="feature", description="x", tier="canonical"),
            VocabEntry(name="b", kind="capability", description="y", tier="canonical"),
        ]
        assert compute_vocab_diversity_ratio(vocab) == 0.0

    def test_all_candidates_returns_one(self):
        vocab = [
            VocabEntry(name="a", kind="feature", description="x", tier="candidate"),
            VocabEntry(name="b", kind="capability", description="y", tier="candidate"),
        ]
        assert compute_vocab_diversity_ratio(vocab) == 1.0

    def test_half_candidates(self):
        vocab = [
            VocabEntry(name="a", kind="feature", description="x", tier="canonical"),
            VocabEntry(name="b", kind="feature", description="y", tier="candidate"),
        ]
        assert abs(compute_vocab_diversity_ratio(vocab) - 0.5) < 1e-9

    def test_discoveries_excluded_from_ratio(self):
        """Discoveries are never counted — only feature/capability entries matter."""
        vocab = [
            VocabEntry(name="a", kind="feature", description="x", tier="canonical"),
            VocabEntry(name="d1", kind="discovery", description="found X", tier="candidate"),
            VocabEntry(name="d2", kind="discovery", description="found Y", tier="candidate"),
        ]
        # 1 feature/capability total, 0 candidates → 0.0
        assert compute_vocab_diversity_ratio(vocab) == 0.0

    def test_mixed_vocab(self):
        """2 canonical features, 1 candidate feature, 3 discoveries → ratio = 1/3."""
        vocab = [
            VocabEntry(name="f1", kind="feature", description="x", tier="canonical"),
            VocabEntry(name="f2", kind="feature", description="y", tier="canonical"),
            VocabEntry(name="f3", kind="feature", description="z", tier="candidate"),
            VocabEntry(name="disc1", kind="discovery", description="a", tier="candidate"),
            VocabEntry(name="disc2", kind="discovery", description="b", tier="candidate"),
            VocabEntry(name="disc3", kind="discovery", description="c", tier="candidate"),
        ]
        ratio = compute_vocab_diversity_ratio(vocab)
        assert abs(ratio - 1 / 3) < 1e-9

    def test_only_discoveries_returns_zero(self):
        vocab = [
            VocabEntry(name="d1", kind="discovery", description="x"),
        ]
        assert compute_vocab_diversity_ratio(vocab) == 0.0


# ---------------------------------------------------------------------------
# update_vocab_link_confirmations (Phase E.7)
# ---------------------------------------------------------------------------

def _feat(name="dilated_causal_conv", related_to=None):
    return VocabEntry(name=name, kind="feature", description="test",
                      related_to=related_to or [])


def _cap(name="receptive_field"):
    return VocabEntry(name=name, kind="capability", description="test")


def _link(feature="dilated_causal_conv", capability="receptive_field"):
    return {"feature": feature, "capability": capability, "evidence": "test"}


class TestUpdateVocabLinkConfirmations:

    # --- Confirmation counting ---

    def test_confirmed_outcome_increments_count(self):
        """A 'confirmed' prediction adds run_name to the link's confirmation list."""
        confs, _, _ = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="confirmed",
            run_name="run_a",
            existing_confirmations={},
            runtime_vocab=[_feat(), _cap()],
        )
        assert confs["dilated_causal_conv:receptive_field"] == ["run_a"]

    def test_partial_outcome_does_not_increment(self):
        """'partial' outcome leaves confirmation counts unchanged."""
        confs, _, _ = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="partial",
            run_name="run_a",
            existing_confirmations={},
            runtime_vocab=[_feat(), _cap()],
        )
        assert confs.get("dilated_causal_conv:receptive_field", []) == []

    def test_refuted_outcome_does_not_increment(self):
        """'refuted' outcome leaves confirmation counts unchanged."""
        confs, _, _ = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="refuted",
            run_name="run_a",
            existing_confirmations={},
            runtime_vocab=[_feat(), _cap()],
        )
        assert confs.get("dilated_causal_conv:receptive_field", []) == []

    def test_none_outcome_does_not_increment(self):
        """None outcome (first iteration) leaves counts unchanged."""
        confs, _, _ = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome=None,
            run_name="run_a",
            existing_confirmations={},
            runtime_vocab=[_feat(), _cap()],
        )
        assert confs.get("dilated_causal_conv:receptive_field", []) == []

    def test_same_run_not_counted_twice(self):
        """Confirming the same run twice keeps only one entry."""
        existing = {"dilated_causal_conv:receptive_field": ["run_a"]}
        confs, _, _ = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="confirmed",
            run_name="run_a",
            existing_confirmations=existing,
            runtime_vocab=[_feat(), _cap()],
        )
        assert confs["dilated_causal_conv:receptive_field"].count("run_a") == 1

    def test_different_runs_accumulated(self):
        """Confirmations from different runs stack up correctly."""
        existing = {"dilated_causal_conv:receptive_field": ["run_a", "run_b"]}
        confs, _, _ = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="confirmed",
            run_name="run_c",
            existing_confirmations=existing,
            runtime_vocab=[_feat(), _cap()],
        )
        assert set(confs["dilated_causal_conv:receptive_field"]) == {"run_a", "run_b", "run_c"}

    # --- related_to promotion ---

    def test_promotes_to_related_to_at_threshold(self):
        """When count reaches min_runs, capability added to feature.related_to."""
        existing = {"dilated_causal_conv:receptive_field": ["run_a", "run_b"]}
        confs, vocab, promoted = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="confirmed",
            run_name="run_c",  # 3rd confirmation → trigger
            existing_confirmations=existing,
            runtime_vocab=[_feat(), _cap()],
            min_runs=3,
        )
        assert "dilated_causal_conv:receptive_field" in promoted
        feat = next(v for v in vocab if v.name == "dilated_causal_conv")
        assert "receptive_field" in feat.related_to

    def test_below_threshold_no_promotion(self):
        """Two confirmations with min_runs=3 → no promotion yet."""
        existing = {"dilated_causal_conv:receptive_field": ["run_a"]}
        confs, vocab, promoted = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="confirmed",
            run_name="run_b",  # only 2nd confirmation
            existing_confirmations=existing,
            runtime_vocab=[_feat(), _cap()],
            min_runs=3,
        )
        assert promoted == []
        feat = next(v for v in vocab if v.name == "dilated_causal_conv")
        assert "receptive_field" not in feat.related_to

    def test_already_in_related_to_not_promoted_twice(self):
        """If capability already in related_to, it is not added again."""
        existing = {"dilated_causal_conv:receptive_field": ["run_a", "run_b"]}
        # Feature already has capability in related_to from a previous iteration
        feat_with_link = _feat(related_to=["receptive_field"])
        confs, vocab, promoted = update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="confirmed",
            run_name="run_c",
            existing_confirmations=existing,
            runtime_vocab=[feat_with_link, _cap()],
            min_runs=3,
        )
        assert promoted == []
        feat = next(v for v in vocab if v.name == "dilated_causal_conv")
        assert feat.related_to.count("receptive_field") == 1

    def test_feature_not_in_vocab_no_crash(self):
        """Link referencing a feature not in runtime_vocab is silently skipped."""
        existing = {"unknown_feat:receptive_field": ["run_a", "run_b"]}
        _, vocab, promoted = update_vocab_link_confirmations(
            prev_vocab_links=[{"feature": "unknown_feat", "capability": "receptive_field", "evidence": "x"}],
            prediction_outcome="confirmed",
            run_name="run_c",
            existing_confirmations=existing,
            runtime_vocab=[_cap()],  # feature not present
            min_runs=3,
        )
        assert promoted == []

    def test_multiple_links_promoted_independently(self):
        """Multiple links in one proposal can be promoted independently."""
        existing = {
            "dilated_causal_conv:receptive_field": ["run_a", "run_b"],
            "gated_activation:frequency_resolution": ["run_a", "run_b"],
        }
        vocab = [
            _feat("dilated_causal_conv"),
            _feat("gated_activation"),
            _cap("receptive_field"),
            VocabEntry(name="frequency_resolution", kind="capability", description="test"),
        ]
        links = [
            _link("dilated_causal_conv", "receptive_field"),
            _link("gated_activation", "frequency_resolution"),
        ]
        confs, updated_vocab, promoted = update_vocab_link_confirmations(
            prev_vocab_links=links,
            prediction_outcome="confirmed",
            run_name="run_c",
            existing_confirmations=existing,
            runtime_vocab=vocab,
            min_runs=3,
        )
        assert len(promoted) == 2
        dc = next(v for v in updated_vocab if v.name == "dilated_causal_conv")
        ga = next(v for v in updated_vocab if v.name == "gated_activation")
        assert "receptive_field" in dc.related_to
        assert "frequency_resolution" in ga.related_to

    def test_does_not_mutate_existing_confirmations(self):
        """existing_confirmations dict is not mutated in place."""
        existing = {"dilated_causal_conv:receptive_field": ["run_a"]}
        original_list = existing["dilated_causal_conv:receptive_field"]
        update_vocab_link_confirmations(
            prev_vocab_links=[_link()],
            prediction_outcome="confirmed",
            run_name="run_b",
            existing_confirmations=existing,
            runtime_vocab=[_feat(), _cap()],
        )
        assert existing["dilated_causal_conv:receptive_field"] is original_list
        assert "run_b" not in original_list
