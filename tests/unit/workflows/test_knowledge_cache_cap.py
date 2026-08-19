"""Unit tests for _cap_knowledge_cache (Phase 6.8 Commit 10).

Validates the top-N eviction policy that keeps model_knowledge_cache bounded
across iterations.
"""

from __future__ import annotations

from execute_tools.metric_order import MetricOrder
from tests.helpers.metric_fixtures import shipped_spec
from workflows.model_exploration import _cap_knowledge_cache

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as a
#: REQUIRED keyword. The shipped TIDMAD spec is `higher`, so every expectation in
#: this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(shipped_spec())


def _make_cache_entry(score: float | None = None) -> dict:
    """Build a minimal cache entry with a _stats block."""
    return {
        "key_findings": ["finding"],
        "bottlenecks": [],
        "_stats": {
            "best_denoising_score": score,
            "completed_rounds": 3,
        },
    }


def test_under_limit_no_eviction():
    cache = {f"model_{i}": _make_cache_entry(float(i)) for i in range(4)}
    capped, evicted = _cap_knowledge_cache(cache, current_model="model_0", order=_STEP09A_ORDER)
    assert len(capped) == 4
    assert evicted == set()


def test_exact_limit_no_eviction():
    cache = {f"model_{i}": _make_cache_entry(float(i)) for i in range(5)}
    capped, evicted = _cap_knowledge_cache(cache, current_model="model_0", order=_STEP09A_ORDER)
    assert len(capped) == 5
    assert evicted == set()


def test_8_entries_top5_by_score():
    """8 models → keep top-5. Current model always survives."""
    cache = {f"model_{i}": _make_cache_entry(float(i)) for i in range(8)}
    # current_model = "model_0" (score=0.0, the worst)
    capped, evicted = _cap_knowledge_cache(cache, current_model="model_0", order=_STEP09A_ORDER)
    assert len(capped) == 5
    # model_0 kept (current), top-4 by score: model_7, model_6, model_5, model_4
    assert "model_0" in capped
    assert "model_7" in capped
    assert "model_6" in capped
    assert "model_5" in capped
    assert "model_4" in capped
    assert evicted == {"model_1", "model_2", "model_3"}


def test_current_model_survives_even_if_worst():
    cache = {
        "bad_current": _make_cache_entry(0.1),
        "good_1": _make_cache_entry(9.0),
        "good_2": _make_cache_entry(8.0),
        "good_3": _make_cache_entry(7.0),
        "good_4": _make_cache_entry(6.0),
        "good_5": _make_cache_entry(5.0),
        "good_6": _make_cache_entry(4.0),
    }
    capped, evicted = _cap_knowledge_cache(cache, current_model="bad_current", order=_STEP09A_ORDER)
    assert "bad_current" in capped
    assert len(capped) == 5
    # Top-4 non-current: good_1..good_4
    assert "good_1" in capped
    assert "good_4" in capped
    assert "good_5" in evicted
    assert "good_6" in evicted


def test_none_scores_evicted_first():
    """Models with None score rank below all scored models."""
    cache = {
        "scored_1": _make_cache_entry(3.0),
        "scored_2": _make_cache_entry(2.0),
        "scored_3": _make_cache_entry(1.0),
        "scored_4": _make_cache_entry(0.5),
        "none_1": _make_cache_entry(None),
        "none_2": _make_cache_entry(None),
        "current": _make_cache_entry(4.0),
    }
    capped, evicted = _cap_knowledge_cache(cache, current_model="current", order=_STEP09A_ORDER)
    assert len(capped) == 5
    assert "none_1" in evicted
    assert "none_2" in evicted


def test_custom_max_entries():
    cache = {f"model_{i}": _make_cache_entry(float(i)) for i in range(10)}
    capped, evicted = _cap_knowledge_cache(
        cache, current_model="model_0", max_entries=3, order=_STEP09A_ORDER
    )
    assert len(capped) == 3
    assert "model_0" in capped  # current
    assert "model_9" in capped  # top-1
    assert "model_8" in capped  # top-2
    assert len(evicted) == 7
