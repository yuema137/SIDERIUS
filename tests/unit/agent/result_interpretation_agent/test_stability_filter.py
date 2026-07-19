"""Unit tests for Commit 6.1 — Active-Model Policy + Stability Filter.

Covers Pre-Commit Checklist items 1-3 from the design doc §8 Commit 6.1:

  1. ``test_active_set_top_k_plus_last_n_plus_delta`` — given a 7-model
     cache with synthetic scores, recency, and one model with a current-iter
     score delta ≥ Δ, the active set is exactly
     ``top3 ∪ last2 ∪ {delta_model}`` (deduplicated).
  2. ``test_compress_preserves_key_finding`` — ``compress_model_summary``
     extracts the original ``key_finding`` verbatim and emits ≤ 200 chars
     of takeaway.
  3. ``test_stability_filter_skips_stable_models`` — given a 7-model cache
     where 5 models are stable and 2 are active, ``should_recall_per_model``
     returns ``False`` for the 5 and ``True`` for the 2.

Plus boundary tests for empty caches, missing scores, lex-tiebreak
determinism, and cache-miss handling.

The helpers under test live in ``nodes/interpretation_helpers.py`` and
are pure deterministic functions (no LLM call) — they can be tested
without any API key, GPU, or workspace fixture.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from agent.schemas.interpretation import ModelRunSummary
from nodes.interpretation_helpers import (
    compress_model_summary,
    select_active_models,
    should_recall_per_model,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _entry(
    best: float | None,
    rounds: int = 5,
    findings: list[str] | None = None,
    best_config_analysis: str = "",
) -> dict[str, Any]:
    """Build a synthetic cache entry shaped like the live cache.

    Mirrors the cache shape produced by ``result_interpretation_agent.py:722-738``:
    8 LLM text fields (here we only populate ``key_findings`` and
    ``best_config_analysis`` since they're the only ones the helpers read)
    plus the ``_stats`` numerical block.
    """
    return {
        "key_findings": findings or [],
        "bottlenecks": [],
        "best_config_analysis": best_config_analysis,
        "score_trend": "",
        "per_file_analysis": "",
        "data_sensitivity": "",
        "efficiency_assessment": "",
        "strategy_assessment": "",
        "_stats": {
            "best_denoising_score": best,
            "best_valid_denoising_score": best,
            "completed_rounds": rounds,
        },
    }


def _summary(model_type: str, best: float | None, rounds: int = 1) -> ModelRunSummary:
    """Build a minimal ModelRunSummary for the helper tests."""
    return ModelRunSummary(
        model_type=model_type,
        run_name=f"{model_type}_run",
        status="completed",
        completed_rounds=rounds,
        best_denoising_score=best,
        best_valid_denoising_score=best,
    )


# ---------------------------------------------------------------------------
# select_active_models (Pre-Commit Checklist #1)
# ---------------------------------------------------------------------------


class TestSelectActiveModels:
    """The active set is the union of Top-K + Last-N + Delta-Δ."""

    def test_active_set_top_k_plus_last_n_plus_delta(self):
        """7-model cache, current iter has 1 model with significant delta.

        Active set must be exactly ``top3 ∪ last2 ∪ {delta_model}``,
        deduplicated. This pins the exact V12 forensic scenario: iter 14
        has 12 cached models; only ~3 are worth re-summarising.
        """
        # 7-model cache with distinct scores so Top-K is unambiguous.
        cache = {
            "mt_a": _entry(best=1.0),
            "mt_b": _entry(best=2.0),
            "mt_c": _entry(best=3.0),  # 3rd best
            "mt_d": _entry(best=4.0),  # 2nd best
            "mt_e": _entry(best=5.0),  # 1st best
            "mt_f": _entry(best=0.5),  # bottom
            "mt_g": _entry(best=0.7),  # bottom
        }
        # Current iter: tuned mt_x (new — Last-N), mt_y (new — Last-N),
        # and mt_b (was 2.0 → now 2.5: |Δ|=0.5 ≥ 0.05 → Delta path).
        current_summaries = [
            _summary("mt_x", best=2.2),
            _summary("mt_y", best=2.3),
            _summary("mt_b", best=2.5),  # delta=0.5 from cached 2.0
        ]

        active = select_active_models(
            cache,
            current_summaries,
            top_k=3,
            last_n=2,
            score_delta_threshold=0.05,
        )

        # Top-3: mt_e (5.0), mt_d (4.0), mt_c (3.0)
        # Last-2: first two of current_summaries → mt_x, mt_y
        # Delta: mt_b
        # Union: {mt_e, mt_d, mt_c, mt_x, mt_y, mt_b}
        assert active == {"mt_e", "mt_d", "mt_c", "mt_x", "mt_y", "mt_b"}

    def test_top_k_excludes_models_with_none_score(self):
        """Models with best_denoising_score=None cannot be ranked."""
        cache = {
            "rank_me": _entry(best=1.0),
            "no_score": _entry(best=None),
        }
        active = select_active_models(cache, current_iter_summaries=[], top_k=2, last_n=0)
        assert active == {"rank_me"}

    def test_last_n_truncates_to_first_n(self):
        """When current_iter_summaries > last_n, take the first N (caller-ordered)."""
        cache: dict[str, dict] = {}
        summaries = [_summary(f"mt_{i}", best=1.0) for i in range(5)]
        active = select_active_models(cache, summaries, top_k=0, last_n=2)
        # First two only.
        assert active == {"mt_0", "mt_1"}

    def test_delta_path_skipped_for_models_without_prior(self):
        """A current-iter model with no cache entry contributes via Last-N only."""
        cache: dict[str, dict] = {}  # no prior data
        summaries = [_summary("brand_new", best=10.0)]
        active = select_active_models(
            cache, summaries, top_k=3, last_n=1, score_delta_threshold=0.05
        )
        assert active == {"brand_new"}  # via Last-N, not Delta

    def test_delta_below_threshold_excluded(self):
        """|Δ| < threshold → not added via Delta path."""
        cache = {"stable": _entry(best=2.0)}
        # Score went 2.0 → 2.01: |Δ|=0.01 < 0.05 threshold.
        summaries = [_summary("stable", best=2.01)]
        active = select_active_models(
            cache, summaries, top_k=0, last_n=0, score_delta_threshold=0.05
        )
        # Top-K=0 disables ranking, Last-N=0 disables recency, Δ below threshold:
        # active set is empty.
        assert active == set()

    def test_delta_at_or_above_threshold_included(self):
        """|Δ| == threshold (boundary) → included.

        Uses exactly-representable floats (0.5 = 2^-1) to avoid spurious
        boundary failures from float imprecision.
        """
        cache = {"changed": _entry(best=2.0)}
        summaries = [_summary("changed", best=2.5)]  # |Δ|=0.5 == threshold
        active = select_active_models(
            cache, summaries, top_k=0, last_n=0, score_delta_threshold=0.5
        )
        assert active == {"changed"}

    def test_lex_tiebreak_determinism(self):
        """Equal scores → lexicographic order so the active set is deterministic."""
        cache = {
            "zebra": _entry(best=5.0),
            "apple": _entry(best=5.0),
            "mango": _entry(best=5.0),
        }
        active = select_active_models(cache, current_iter_summaries=[], top_k=2, last_n=0)
        # Ties → sorted lexicographically → "apple", "mango" win Top-2.
        assert active == {"apple", "mango"}

    def test_empty_cache_and_no_summaries(self):
        cache: dict[str, dict] = {}
        active = select_active_models(cache, current_iter_summaries=[], top_k=3, last_n=2)
        assert active == set()

    def test_negative_thresholds_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            select_active_models({}, [], top_k=-1)
        with pytest.raises(ValueError, match="non-negative"):
            select_active_models({}, [], last_n=-1)
        with pytest.raises(ValueError, match="non-negative"):
            select_active_models({}, [], score_delta_threshold=-0.1)


# ---------------------------------------------------------------------------
# compress_model_summary (Pre-Commit Checklist #2)
# ---------------------------------------------------------------------------


class TestCompressModelSummary:
    """Deterministic compressor: cache entry → ≤200 char one-liner."""

    def test_compress_preserves_key_finding(self):
        """The takeaway is the first key_finding, truncated to max chars."""
        finding = "Architectural insight: spectral attention beats convolution at low SNR."
        entry = _entry(best=4.5, rounds=8, findings=[finding, "secondary one"])
        result = compress_model_summary("punet", entry, max_takeaway_chars=150)

        assert result["model_type"] == "punet"
        assert result["best_score"] == 4.5
        assert result["n_rounds"] == 8
        # First finding, verbatim (well under 150 chars).
        assert result["one_line_takeaway"] == finding

    def test_compress_truncates_long_finding_with_ellipsis(self):
        """Findings over the cap get truncated; ellipsis marks the cut."""
        long_finding = "x" * 500
        entry = _entry(best=1.0, findings=[long_finding])
        result = compress_model_summary("mt", entry, max_takeaway_chars=50)
        # 49 chars + "…" = 50 chars.
        assert len(result["one_line_takeaway"]) == 50
        assert result["one_line_takeaway"].endswith("…")

    def test_compress_falls_back_to_best_config_analysis(self):
        """Empty key_findings → fall back to best_config_analysis."""
        entry = _entry(
            best=2.0,
            findings=[],
            best_config_analysis="hidden=128, dropout=0.3 was the winning combo",
        )
        result = compress_model_summary("mt", entry)
        assert "hidden=128" in result["one_line_takeaway"]

    def test_compress_placeholder_when_nothing_available(self):
        """No findings, no analysis → placeholder."""
        entry = _entry(best=None, findings=[], best_config_analysis="")
        result = compress_model_summary("mt", entry)
        assert result["one_line_takeaway"] == "(no cached takeaway)"

    def test_compress_total_serialised_length_under_200(self):
        """The result, serialised back into prompt-ish text, is ≤ 200 chars.

        Mirrors how the synthesis prompt will render the compressed entry:
        ``"- {model_type} (best={best_score}, n={n_rounds}): {takeaway}"``.
        """
        entry = _entry(best=4.5, rounds=8, findings=["x" * 200])  # over-long
        result = compress_model_summary("punet", entry, max_takeaway_chars=150)
        rendered = (
            f"- {result['model_type']} (best={result['best_score']}, "
            f"n={result['n_rounds']}): {result['one_line_takeaway']}"
        )
        assert len(rendered) <= 200, (
            f"Compressed render exceeded 200 chars: {len(rendered)}\n{rendered}"
        )

    def test_compress_zero_max_takeaway_rejected(self):
        with pytest.raises(ValueError, match="must be positive"):
            compress_model_summary("mt", _entry(best=1.0), max_takeaway_chars=0)


# ---------------------------------------------------------------------------
# should_recall_per_model (Pre-Commit Checklist #3)
# ---------------------------------------------------------------------------


class TestShouldRecallPerModel:
    """Decide whether to issue a fresh per_model LLM call.

    The Stability Filter is the V12 +5,947 tok/iter clamp: stable models
    skip the LLM call entirely.
    """

    def test_cache_miss_always_recalls(self):
        """A model never seen before must be summarised at least once.

        Cache miss → True regardless of active_set membership.
        """
        assert (
            should_recall_per_model(
                model_type="brand_new",
                cache_entry=None,
                current_iter_summary=_summary("brand_new", best=1.0),
                active_set=set(),  # not even active!
            )
            is True
        )

    def test_stability_filter_skips_stable_models(self):
        """7-model cache, 5 stable + 2 active → 5 skip, 2 recall.

        This is the headline V12 regression test: at iter 14 we had
        12 cached models but only 3 worth re-summarising.
        """
        cache = {f"mt_{i}": _entry(best=float(i)) for i in range(7)}
        # 2 active: mt_5 + mt_6 (Top-K).
        active = {"mt_5", "mt_6"}
        # No new tuning data this iter (all stable from a tuning perspective).
        skip_decisions = {}
        for mt in cache:
            skip_decisions[mt] = should_recall_per_model(
                model_type=mt,
                cache_entry=cache[mt],
                current_iter_summary=None,
                active_set=active,
            )
        # 5 stable models → False (skip).
        assert skip_decisions == {
            "mt_0": False,
            "mt_1": False,
            "mt_2": False,
            "mt_3": False,
            "mt_4": False,
            "mt_5": False,  # in active set BUT no new data → skip
            "mt_6": False,  # in active set BUT no new data → skip
        }

    def test_active_with_more_rounds_recalls(self):
        """Active model + more completed rounds → True (re-call)."""
        cache = {"mt": _entry(best=2.0, rounds=5)}
        new_summary = _summary("mt", best=2.0, rounds=8)  # +3 new rounds
        assert (
            should_recall_per_model(
                model_type="mt",
                cache_entry=cache["mt"],
                current_iter_summary=new_summary,
                active_set={"mt"},
            )
            is True
        )

    def test_active_with_score_delta_recalls(self):
        """Active model + score delta ≥ threshold → True."""
        cache = {"mt": _entry(best=2.0, rounds=5)}
        new_summary = _summary("mt", best=3.0, rounds=5)  # +1.0 delta, no new rounds
        assert (
            should_recall_per_model(
                model_type="mt",
                cache_entry=cache["mt"],
                current_iter_summary=new_summary,
                active_set={"mt"},
                score_delta_threshold=0.05,
            )
            is True
        )

    def test_active_with_no_new_evidence_skips(self):
        """In active set BUT no new tuning data → False (skip).

        This is the subtle case: a model is in Top-K (worth keeping in
        synthesis) but had no new training rounds and no score change.
        We do not waste an LLM call re-summarising unchanged data.
        """
        cache = {"mt": _entry(best=2.0, rounds=5)}
        new_summary = _summary("mt", best=2.0, rounds=5)  # no change
        assert (
            should_recall_per_model(
                model_type="mt",
                cache_entry=cache["mt"],
                current_iter_summary=new_summary,
                active_set={"mt"},
            )
            is False
        )

    def test_inactive_with_new_data_still_skips(self):
        """Not in active set → False, even if there's new training data.

        The active-set decision is the master gate. If a model is excluded
        from the active set, we trust that decision and skip the LLM call.
        """
        cache = {"mt": _entry(best=2.0, rounds=5)}
        new_summary = _summary("mt", best=5.0, rounds=10)  # huge change
        assert (
            should_recall_per_model(
                model_type="mt",
                cache_entry=cache["mt"],
                current_iter_summary=new_summary,
                active_set=set(),  # NOT active
            )
            is False
        )

    def test_below_threshold_delta_skips(self):
        """|Δ| < threshold AND no new rounds → False."""
        cache = {"mt": _entry(best=2.0, rounds=5)}
        new_summary = _summary("mt", best=2.01, rounds=5)  # delta 0.01 < 0.05
        assert (
            should_recall_per_model(
                model_type="mt",
                cache_entry=cache["mt"],
                current_iter_summary=new_summary,
                active_set={"mt"},
                score_delta_threshold=0.05,
            )
            is False
        )
