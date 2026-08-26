"""
Unit tests for Phase C+E vocabulary feedback loop helpers.

Tests evaluate_prediction, generate_discoveries, build_runtime_vocab,
promote_candidates (C.11), seen_in_runs tracking (C.5-3),
compute_vocab_diversity_ratio (centrifugal health metric),
update_vocab_link_confirmations (E.7), and scientific_accuracy
accumulation helpers (E.4).
"""

import pytest

from agent.schemas.proposal import VocabEntry
from execute_tools.metric_order import MetricOrder
from nodes.interpretation_helpers import (
    _content_words,
    _find_duplicate_candidate,
    build_runtime_vocab,
    compute_vocab_diversity_ratio,
    generate_discoveries,
    promote_candidates,
    update_vocab_link_confirmations,
)

# Step 09a C1b: prediction evaluation is interpreter-owned semantics and moved
# out of the mixed helpers module into the node's private `prediction` module.
# It is DEFINED there exactly once — this import is the definition site, not a
# compatibility alias, so these cases keep testing the production code path.
from nodes.result_interpretation_agent.prediction import evaluate_prediction
from tests.helpers.metric_fixtures import shipped_spec

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder
#: as a REQUIRED keyword. TIDMAD is `higher`, so expectations are unchanged.
_STEP09A_ORDER = MetricOrder(shipped_spec())

#: Step 09a C4 — a NEW prediction's default metric is the run's BOUND id,
#: never the literal `denoising_score` (one task's name, hardcoded).
_BOUND_METRIC_ID = shipped_spec().id

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

    # Each outcome branch is stated once, as a whole contract: the label, the
    # sign of the delta, and the information_gain that follows from it.
    # Six cases used to split these across two sections -- an outcome test
    # and an information_gain test per branch -- running byte-identical
    # calls. `test_boldness_uses_sota_baseline` was a third copy of the
    # confirmed call.

    def test_confirmed_beats_sota(self):
        """actual > sota: confirmed, positive delta, gain == delta."""
        result = evaluate_prediction(
            self._pred(current_value=5.0),
            {"best_denoising_score": 5.5},
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["outcome"] == "confirmed"
        assert result["actual_value"] == 5.5
        assert result["delta_from_sota"] > 0
        assert abs(result["information_gain"] - result["delta_from_sota"]) < 1e-6
        # boldness = |predicted - sota| / |sota| = |6.0 - 5.0| / 5.0
        assert abs(result["boldness"] - 0.2) < 1e-4

    def test_partial_within_margin(self):
        """actual slightly below sota but within 5%: partial, no gain."""
        # sota=5.0, margin=0.05 → partial if actual >= 4.75
        result = evaluate_prediction(
            self._pred(current_value=5.0),
            {"best_denoising_score": 4.8},
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["outcome"] == "partial"
        assert result["delta_from_sota"] < 0
        assert result["information_gain"] == 0.0

    def test_refuted_clearly_below_sota(self):
        """actual clearly below sota (> 5% gap): refuted, no gain."""
        # sota=5.0, 5% threshold=4.75 → refuted if actual < 4.75
        result = evaluate_prediction(
            self._pred(current_value=5.0),
            {"best_denoising_score": 4.0},
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["outcome"] == "refuted"
        assert result["delta_from_sota"] < 0
        assert result["information_gain"] == 0.0

    def test_exactly_at_sota_is_partial(self):
        """actual == sota (not strictly greater) → partial (not confirmed)."""
        result = evaluate_prediction(
            self._pred(current_value=5.0),
            {"best_denoising_score": 5.0},
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["outcome"] == "partial"
        assert result["delta_from_sota"] == 0.0

    # --- current_sota parameter ---

    def test_current_sota_override_takes_precedence(self):
        """Explicit current_sota replaces prediction['current_value']."""
        pred = self._pred(current_value=5.0)  # stale SOTA in prediction
        # Pass fresher SOTA of 6.0 — actual=6.5 should still confirm
        result = evaluate_prediction(
            pred,
            {"best_denoising_score": 6.5},
            current_sota=6.0,
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["outcome"] == "confirmed"
        assert result["current_sota"] == 6.0
        assert abs(result["delta_from_sota"] - 0.5) < 1e-6

    def test_missing_current_sota_falls_back_to_current_value(self):
        """Without override, current_value from prediction is used."""
        result = evaluate_prediction(
            self._pred(current_value=5.0),
            {"best_denoising_score": 6.0},
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["current_sota"] == 5.0

    def test_partial_margin_custom(self):
        """Custom partial_margin=0.10 widens the partial band."""
        # sota=5.0, 10% threshold=4.5 → actual=4.6 is partial (not refuted)
        result = evaluate_prediction(
            self._pred(current_value=5.0),
            {"best_denoising_score": 4.6},
            partial_margin=0.10,
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["outcome"] == "partial"

    # --- File vector metric ---

    def test_file_vector_slice_metric_is_refused(self):
        """UPGRADED by F-SCAND-1 — this asserted `confirmed` on a slice mean.

        A prediction phrased against a forbidden aggregation can no longer be
        CONFIRMED, because the number that would confirm it is one the
        aggregation standard refuses to produce.
        """
        pred = {
            "metric": "mean(file_vector[0:5])",
            "current_value": 1.5,
            "predicted_value": 2.5,
        }
        fv = [1.0, 1.5, 2.0, 2.5, 3.0] + [None] * 15
        result = evaluate_prediction(
            pred,
            {"best_denoising_score": 5.0, "best_file_vector": fv},
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["actual_value"] is None
        assert result["metric_resolution"] == "refused_forbidden_aggregation"
        assert result["outcome"] == "unevaluated"

    # --- Missing data fallback ---

    def test_missing_actual_results(self):
        """No metric data → UNEVALUATED (Step 09a C4), not a weak "partial".

        This was the defect: an uncomputable metric was labelled `partial`,
        which put a non-observation into the accuracy pool and published it as
        a discovery reading "achieved metric=N/A".
        """
        result = evaluate_prediction(
            self._pred(), {}, order=_STEP09A_ORDER, bound_metric_id=_BOUND_METRIC_ID
        )
        assert result["outcome"] == "unevaluated"
        assert "not evaluated" in result["notes"]
        assert result["delta_from_sota"] is None
        assert result["information_gain"] == 0.0

    def test_missing_current_sota_and_current_value(self):
        """No baseline at all → UNEVALUATED. There is nothing to compare to,
        and the actual value alone is evidence for or against nothing."""
        result = evaluate_prediction(
            {"metric": "denoising_score", "predicted_value": 6.0},
            {"best_denoising_score": 6.5},
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["outcome"] == "unevaluated"
        assert result["current_sota"] is None
        assert "no SOTA baseline" in result["notes"]

    # --- Boldness and information_gain ---

    # `test_boldness_uses_sota_baseline` was a third copy of the confirmed
    # call (`_pred`'s predicted_value already defaults to 6.0); its
    # assertion now sits there. The zero case below stays: it is the other
    # leg of the ternary, and reaches it with a DIFFERENT input.

    def test_boldness_zero_when_no_predicted_value(self):
        """No predicted_value in prediction → boldness=0."""
        result = evaluate_prediction(
            {"metric": "denoising_score", "current_value": 5.0},
            {"best_denoising_score": 6.0},
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert result["boldness"] == 0.0

    # The three `test_information_gain_*` cases lived here, each repeating
    # the call of its outcome test above to assert one more field of the
    # same result. Folded into those contracts.


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
            order=_STEP09A_ORDER,
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
            order=_STEP09A_ORDER,
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
            order=_STEP09A_ORDER,
        )
        assert any("PARTIAL" in d.description for d in discoveries)
        assert any("N/A" in d.description for d in discoveries)

    def test_no_prediction_and_no_sota_yields_nothing(self):
        """With nothing to compare against, there is no finding to report.

        This asserted `all(d.kind == "discovery" for d in discoveries)` over
        a list that is EMPTY in this configuration -- Discovery 1 needs a
        prediction and Discovery 2 needs a SOTA, so both are skipped. `all()`
        over an empty list is True, so no production edit could fail it.
        """
        discoveries = generate_discoveries(
            prediction_eval=None,
            model_type="test_model",
            best_score=5.0,
            inherited_components=[],
            proposed_vocab_links=[],
            order=_STEP09A_ORDER,
        )
        assert discoveries == []

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
            order=_STEP09A_ORDER,
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
            order=_STEP09A_ORDER,
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
            order=_STEP09A_ORDER,
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
            order=_STEP09A_ORDER,
        )
        score_disc = next((d for d in discoveries if "score" in d.name), None)
        assert score_disc is not None
        assert "beating" in score_disc.description


# ---------------------------------------------------------------------------
# build_runtime_vocab
# ---------------------------------------------------------------------------


class TestBuildRuntimeVocab:
    # `test_seed_only`, `test_adds_discoveries` and `test_adds_candidates`
    # lived here. `test_vocab_grows_across_iterations` below performs exactly
    # those three steps in sequence -- seed only, then add a discovery, then
    # add a discovery and a candidate -- and additionally asserts the
    # resulting kind set. It is a strict superset of all three.

    def test_deduplicates_by_name(self):
        seed = [VocabEntry(name="feature_a", kind="feature", description="original")]
        discovery = VocabEntry(name="feature_a", kind="feature", description="updated")
        result = build_runtime_vocab(seed, [discovery], [])
        assert len(result) == 1
        # Discovery overwrites seed entry with same name
        assert result[0].description == "updated"

    def test_vocab_grows_across_iterations(self):
        """Simulate 3 iterations of vocab growth.

        Also the seed-only, add-a-discovery and add-a-candidate cases: each
        is one step of this sequence, asserted as it happens.
        """
        # Iteration 1: seed only
        vocab = build_runtime_vocab(
            [VocabEntry(name="f1", kind="feature", description="feature 1")],
            [],
            [],
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
        # The candidate arrived as a plain dict and must be a real entry by
        # name, not merely counted -- the absorbed `test_adds_candidates`
        # and `test_adds_discoveries` each checked membership.
        assert {v.name for v in vocab} == {"f1", "d1", "d2", "f2"}


# ---------------------------------------------------------------------------
# _find_duplicate_candidate + _content_words (post-v15 dedup heuristic)
# ---------------------------------------------------------------------------


def _cand_entry(name, kind="feature", description="", tier="candidate"):
    """Build a VocabEntry with explicit description — used by dedup tests
    that exercise the description-overlap predicate."""
    return VocabEntry(
        name=name,
        kind=kind,
        description=description or f"placeholder description for {name}",
        tier=tier,
    )


class TestContentWords:
    """``_content_words`` filters stopwords + sub-4-char tokens. Mechanism-
    bearing words like 'ordinal', 'wasserstein', 'curriculum' must survive."""

    def test_filters_stopwords_and_short_tokens(self):
        words = _content_words("The ordinal loss is a transport-based metric.")
        # 'ordinal', 'transport', 'metric' survive. 'loss' is in stopwords.
        # 'the', 'is', 'a' are stopwords or sub-4-char.
        assert "ordinal" in words
        assert "transport" in words
        assert "metric" in words
        assert "the" not in words
        assert "loss" not in words  # in _STOPWORDS

    def test_lowercases(self):
        assert "wasserstein" in _content_words("WASSERSTEIN distance over ADC bins")

    def test_splits_on_non_alpha(self):
        words = _content_words("snake_case-and-hyphen tokens")
        assert "snake" in words
        assert "case" in words
        assert "hyphen" in words
        assert "tokens" in words


class TestFindDuplicateCandidate:
    """Post-v15: this heuristic exists to fix the seen_in_runs==1 epidemic
    that caused zero promotions across all 20 v15 iterations."""

    def test_returns_none_on_empty_vocab(self):
        result = _find_duplicate_candidate(
            new_name="new_feature",
            new_kind="feature",
            new_description="some description",
            existing_vocab={},
        )
        assert result is None

    def test_name_substring_match_long_names(self):
        """``emd_loss`` is a substring of ``emd_ordinal_loss`` — should
        dedup. v15's canonical example: ``emd_ordinal_loss`` (iter 3) and
        a hypothetical ``emd_ordinal_loss_v2`` (later iter) should merge."""
        existing = {
            "emd_ordinal_loss": _cand_entry("emd_ordinal_loss", description="EMD on bins"),
        }
        result = _find_duplicate_candidate(
            new_name="emd_ordinal_loss_v2",
            new_kind="feature",
            new_description="totally unrelated wording",
            existing_vocab=existing,
        )
        assert result is not None
        assert result.name == "emd_ordinal_loss"

    def test_name_substring_floor_blocks_trivial_match(self):
        """``emd`` (3 chars) and ``emd_bin_loss`` should NOT trigger the
        substring predicate because ``emd`` is below the length floor.
        Description-overlap may still match — this test uses unrelated
        descriptions to isolate the name predicate."""
        existing = {
            "emd_bin_loss": _cand_entry(
                "emd_bin_loss",
                description="lorem ipsum dolor sit amet consectetur adipiscing",
            ),
        }
        result = _find_duplicate_candidate(
            new_name="emd",
            new_kind="feature",
            new_description="unrelated text about colourful sunsets nightfall",
            existing_vocab=existing,
        )
        assert result is None

    def test_description_overlap_matches_paraphrases(self):
        """Two candidates with different names but overlapping mechanism
        descriptions should dedup. v15 canonical: ``snr_weighted_loss``
        and ``hardness_reweighting_loss`` both describe per-sample
        reweighting but with different name surfaces."""
        existing = {
            "snr_weighted_loss": _cand_entry(
                "snr_weighted_loss",
                description=(
                    "reweight training samples by inverse signal-to-noise "
                    "ratio so hard examples receive larger gradient"
                ),
            ),
        }
        result = _find_duplicate_candidate(
            new_name="hardness_reweighting_loss",
            new_kind="feature",
            new_description=(
                "reweight examples by hardness signal during training "
                "so noisy gradient samples receive larger update"
            ),
            existing_vocab=existing,
        )
        assert result is not None
        assert result.name == "snr_weighted_loss"

    def test_kind_mismatch_skipped(self):
        """A feature-kind new candidate must not match a capability-kind
        existing entry, even if names/descriptions overlap."""
        existing = {
            "selective_scan": _cand_entry(
                "selective_scan",
                kind="capability",
                description="parallelisable recurrent scan",
            ),
        }
        result = _find_duplicate_candidate(
            new_name="selective_scan_block",
            new_kind="feature",
            new_description="parallelisable recurrent scan",
            existing_vocab=existing,
        )
        assert result is None

    def test_canonical_entries_skipped(self):
        """A new candidate that overlaps a CANONICAL entry should NOT
        dedup here — canonical merge is the existing ``_dedup_promoted``
        path's job. This function is for candidate→candidate merges only."""
        existing = {
            "dilated_causal_conv": _cand_entry(
                "dilated_causal_conv",
                tier="canonical",
                description="dilated convolution with causal masking",
            ),
        }
        result = _find_duplicate_candidate(
            new_name="causal_dilated_conv",
            new_kind="feature",
            new_description="dilated convolution with causal masking",
            existing_vocab=existing,
        )
        assert result is None

    def test_exact_name_match_returns_none(self):
        """Exact-name matches are the caller's job (the dict lookup in
        ``build_runtime_vocab`` handles them directly). This helper is
        for NEAR-duplicate detection."""
        existing = {
            "ordinal_emd_loss": _cand_entry("ordinal_emd_loss", description="X"),
        }
        result = _find_duplicate_candidate(
            new_name="ordinal_emd_loss",
            new_kind="feature",
            new_description="X",
            existing_vocab=existing,
        )
        assert result is None


class TestBuildRuntimeVocabDedup:
    """End-to-end: ``build_runtime_vocab`` should merge a near-duplicate
    candidate's run signal into the existing entry rather than creating a
    separate entry. This is the change that breaks the v15 zero-promotion
    deadlock."""

    def test_near_duplicate_merges_seen_in_runs(self):
        incoming = [
            VocabEntry(
                name="emd_ordinal_loss",
                kind="feature",
                description="earth-mover distance between predicted and target bin distributions",
                tier="candidate",
                seen_in_runs=["run_a"],
            ),
        ]
        # A new candidate with overlapping name (substring) AND fresh run.
        new_candidates = [
            {
                "name": "emd_ordinal_loss_v2",
                "kind": "feature",
                "description": "earth-mover distance on bin distributions",
                "proposed_by_run": "run_b",
            },
        ]
        result = build_runtime_vocab(
            incoming_vocab=incoming,
            new_discoveries=[],
            proposed_candidates=new_candidates,
        )
        # Should be ONE entry, not two; with seen_in_runs accumulated.
        assert len(result) == 1
        entry = result[0]
        assert entry.name == "emd_ordinal_loss"  # original name kept
        assert set(entry.seen_in_runs) == {"run_a", "run_b"}
        assert "emd_ordinal_loss_v2" in entry.aliases

    def test_genuinely_new_candidate_added_as_separate_entry(self):
        """Sanity check: a new candidate with no overlap to existing must
        still create a fresh entry, not get spuriously merged."""
        incoming = [
            VocabEntry(
                name="dilated_causal_conv",
                kind="feature",
                description="dilated convolution with causal masking",
                tier="candidate",
                seen_in_runs=["run_a"],
            ),
        ]
        new_candidates = [
            {
                "name": "fourier_neural_operator",
                "kind": "feature",
                "description": "spectral convolution using truncated Fourier modes",
                "proposed_by_run": "run_b",
            },
        ]
        result = build_runtime_vocab(
            incoming_vocab=incoming,
            new_discoveries=[],
            proposed_candidates=new_candidates,
        )
        assert len(result) == 2
        names = {e.name for e in result}
        assert names == {"dilated_causal_conv", "fourier_neural_operator"}

    def test_three_iters_of_near_duplicates_promote(self):
        """The v15-failure-mode regression test: three iters propose the
        same mechanism under three different compound names. Combined
        with the post-v15 min_runs=2 default, the merged entry should
        promote to canonical."""
        vocab: list[VocabEntry] = []
        # Iter 1
        vocab = build_runtime_vocab(
            incoming_vocab=vocab,
            new_discoveries=[],
            proposed_candidates=[
                {
                    "name": "snr_weighted_loss",
                    "kind": "feature",
                    "description": (
                        "reweight training samples by signal-to-noise ratio "
                        "so hard examples receive larger gradient"
                    ),
                    "proposed_by_run": "iter_001",
                }
            ],
        )
        # Iter 2 — different name, overlapping description
        vocab = build_runtime_vocab(
            incoming_vocab=vocab,
            new_discoveries=[],
            proposed_candidates=[
                {
                    "name": "hardness_reweighting_loss",
                    "kind": "feature",
                    "description": (
                        "reweight examples by hardness signal during training "
                        "so harder gradient samples receive larger update"
                    ),
                    "proposed_by_run": "iter_002",
                }
            ],
        )
        assert len(vocab) == 1
        # Promotion should fire on iter 2 with the new min_runs=2 default.
        _, promoted = promote_candidates(vocab)
        assert promoted == ["snr_weighted_loss"]


# ---------------------------------------------------------------------------
# promote_candidates (C.11)
# ---------------------------------------------------------------------------


def _make_candidate(name, kind="feature", seen_in_runs=None, tier="candidate"):
    return VocabEntry(
        name=name,
        kind=kind,
        description="test",
        tier=tier,
        seen_in_runs=seen_in_runs or [],
    )


class TestPromoteCandidates:
    # Four cases lived here as separate tests -- a feature with enough runs,
    # a candidate with too few, a discovery that must never promote, and an
    # already-canonical entry. `test_mixed_vocab_only_eligible_promoted`
    # below is those four as rows of one vocab, asserting the resulting tier
    # of each by name, plus the promoted list. The capability case stays: no
    # entry in that mixed vocab has kind="capability", so it is the only
    # thing pinning the second member of the eligible-kind set.

    def test_capability_with_enough_runs_promoted(self):
        entry = _make_candidate(
            "freq_selectivity", kind="capability", seen_in_runs=["r1", "r2", "r3"]
        )
        vocab, promoted = promote_candidates([entry])
        assert promoted == ["freq_selectivity"]
        assert vocab[0].tier == "canonical"

    def test_returns_correct_promoted_names(self):
        # Post-v15 default min_runs=2: 'b' and 'c' both qualify; 'a' is below.
        # Keeps the original three-entry shape so we still verify ordering /
        # set-membership semantics across multiple promotable entries.
        entries = [
            _make_candidate("a", seen_in_runs=["r1"]),
            _make_candidate("b", seen_in_runs=["r1", "r2"]),
            _make_candidate("c", seen_in_runs=["r1", "r2", "r3", "r4"]),
        ]
        _, promoted = promote_candidates(entries)
        assert set(promoted) == {"b", "c"}

    def test_custom_min_runs_actually_moves_the_threshold(self):
        """The parameter, exercised.

        This case used to pass `min_runs=2`, which IS the signature's
        default (post-v15, lowered from 3). It therefore tested the default
        path under a name that claimed otherwise: hardcoding the literal 2
        inside the comparison and ignoring the argument left it green.

        Three runs promote by default and must NOT promote at min_runs=4.
        """
        entry = _make_candidate("log_fno", seen_in_runs=["r1", "r2", "r3"])

        _, promoted_by_default = promote_candidates([entry])
        assert promoted_by_default == ["log_fno"]

        vocab, promoted = promote_candidates([entry], min_runs=4)
        assert promoted == []
        assert vocab[0].tier == "candidate"

    def test_empty_vocab(self):
        vocab, promoted = promote_candidates([])
        assert vocab == []
        assert promoted == []

    def test_mixed_vocab_only_eligible_promoted(self):
        entries = [
            _make_candidate("feat_a", kind="feature", seen_in_runs=["r1", "r2", "r3"]),
            _make_candidate("feat_b", kind="feature", seen_in_runs=["r1"]),
            _make_candidate("disc_x", kind="discovery", seen_in_runs=["r1", "r2", "r3"]),
            # Enough runs to promote if the tier guard were dropped. With the
            # empty seen_in_runs this fixture used to carry, the run-count
            # test rejected it first and the tier guard was never reached --
            # widening `tier == "candidate"` to include canonical changed
            # nothing, here or in the standalone test this absorbed.
            _make_candidate("canon_y", tier="canonical", seen_in_runs=["r1", "r2", "r3"]),
        ]
        vocab, promoted = promote_candidates(entries)
        assert promoted == ["feat_a"], (
            "an already-canonical entry must not be re-promoted: it would be "
            "announced as newly promoted on every iteration"
        )
        by_name = {e.name: e for e in vocab}
        assert by_name["feat_a"].tier == "canonical"
        assert by_name["feat_b"].tier == "candidate"
        assert by_name["disc_x"].tier == "candidate"
        assert by_name["canon_y"].tier == "canonical"


# ---------------------------------------------------------------------------
# seen_in_runs tracking in build_runtime_vocab (C.5-3)
# ---------------------------------------------------------------------------


class TestSeenInRunsTracking:
    # `test_new_candidate_gets_proposed_by_run` lived here. The test below
    # opens with that exact case -- a first-appearance candidate whose
    # seen_in_runs must be its proposing run -- and asserts it before going
    # on to the second iteration.

    def test_existing_candidate_seen_in_runs_extended(self):
        """Second iteration adds a new run to an existing candidate.

        Starts from first appearance, so the initial-population case is
        asserted here too.
        """
        # Iteration 1: candidate first appears
        vocab = build_runtime_vocab(
            [],
            [],
            [
                {
                    "name": "gated_fno",
                    "kind": "feature",
                    "description": "test",
                    "proposed_by_run": "model_a",
                }
            ],
        )
        assert next(e for e in vocab if e.name == "gated_fno").seen_in_runs == ["model_a"]

        # Iteration 2: same candidate proposed by a different model
        vocab = build_runtime_vocab(
            vocab,
            [],
            [
                {
                    "name": "gated_fno",
                    "kind": "feature",
                    "description": "test",
                    "proposed_by_run": "model_b",
                }
            ],
        )
        entry = next(e for e in vocab if e.name == "gated_fno")
        assert set(entry.seen_in_runs) == {"model_a", "model_b"}

    def test_same_run_not_duplicated_in_seen_in_runs(self):
        """If the same run proposes the same candidate twice, seen_in_runs stays deduplicated."""
        candidate = {
            "name": "gated_fno",
            "kind": "feature",
            "description": "test",
            "proposed_by_run": "model_a",
        }
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
                vocab,
                [],
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

    # `test_half_candidates` (1 canonical + 1 candidate) and
    # `test_discoveries_excluded_from_ratio` (1 feature + 2 discoveries)
    # lived here. `test_mixed_vocab` below is both at once: its 1/3 is only
    # reachable if canonical entries are in the denominator and discoveries
    # are in NEITHER -- counting the three discoveries would give 4/6, and
    # dropping canonical from the denominator would give 1/1.

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
    return VocabEntry(name=name, kind="feature", description="test", related_to=related_to or [])


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
        _confs, vocab, promoted = update_vocab_link_confirmations(
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
        _confs, vocab, promoted = update_vocab_link_confirmations(
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
        _confs, vocab, promoted = update_vocab_link_confirmations(
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
        _, _vocab, promoted = update_vocab_link_confirmations(
            prev_vocab_links=[
                {"feature": "unknown_feat", "capability": "receptive_field", "evidence": "x"}
            ],
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
        _confs, updated_vocab, promoted = update_vocab_link_confirmations(
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
