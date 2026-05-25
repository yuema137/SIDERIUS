"""Unit tests for _truncate_memory_history (Phase 6.8 Commit 10).

Validates the sliding-window truncation applied to the planner prompt's
experiment-history JSON.  The full record list is never mutated — only the
serialised prompt copy is condensed.
"""

from __future__ import annotations

import json

import pytest

from agent.prompts import _CONDENSED_KEYS, _CONDENSED_MEMORY_KEYS, _truncate_memory_history

# ── Helpers ───────��────────────────────────────────────────────────────────


def _make_record(exp_id: str, score: float = 5.0, **extra) -> dict:
    """Build a minimal but realistic experiment record."""
    return {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "wavenet",
        "denoising_score": score,
        "is_trial": True,
        "params": {
            "model_config": {"hidden_channels": 32},
            "train_config": {"lr": 1e-3, "batch_size": 8},
            "loss_config": {"loss_type": "focal"},
        },
        "score_table": {"file_6": {"raw": 5.1}},
        "loss_history": [0.9, 0.5, 0.3],
        "file_vector": [5.1, 4.9],
        "timing": {"train_time_s": 120, "inference_time_s": 30, "scoring_time_s": 10},
        "memory": {
            "hypothesis": f"Try config for {exp_id}",
            "conclusion": f"Result for {exp_id}",
            "round_index": 1,
            "key_factor": "lr",
            "discovery": "found something",
            "memory_update": "updated memory",
        },
        **extra,
    }


# ── Tests ────────��─────────────────────────────────────────────────────────


def test_fewer_than_window_returns_all_verbatim():
    records = [_make_record(f"exp_{i}") for i in range(2)]
    result = _truncate_memory_history(records, full_window=3)
    assert len(result) == 2
    assert result == records


def test_exact_window_returns_all_verbatim():
    records = [_make_record(f"exp_{i}") for i in range(3)]
    result = _truncate_memory_history(records, full_window=3)
    assert len(result) == 3
    for orig, out in zip(records, result, strict=True):
        assert out == orig


def test_10_records_gives_7_condensed_3_full():
    records = [_make_record(f"exp_{i}", score=float(i)) for i in range(10)]
    result = _truncate_memory_history(records, full_window=3)
    assert len(result) == 10

    # Last 3 are verbatim
    for i in range(7, 10):
        assert result[i] is records[i]

    # First 7 are condensed
    for i in range(7):
        rec = result[i]
        assert "params" not in rec
        assert "score_table" not in rec
        assert "loss_history" not in rec
        assert "file_vector" not in rec
        assert "timing" not in rec
        assert rec["exp_id"] == f"exp_{i}"
        assert rec["denoising_score"] == float(i)
        assert rec["status"] == "success"
        assert rec["memory"]["hypothesis"] == f"Try config for exp_{i}"
        assert rec["memory"]["conclusion"] == f"Result for exp_{i}"
        assert rec["memory"]["round_index"] == 1
        # Stripped memory keys
        assert "key_factor" not in rec["memory"]
        assert "discovery" not in rec["memory"]
        assert "memory_update" not in rec["memory"]


def test_condensed_keys_are_exactly_specified():
    """Condensed records must have only the expected top-level and memory keys."""
    records = [_make_record(f"exp_{i}") for i in range(5)]
    result = _truncate_memory_history(records, full_window=2)

    for rec in result[:3]:
        top_keys = set(rec.keys()) - {"memory"}
        assert top_keys <= _CONDENSED_KEYS, f"unexpected keys: {top_keys - _CONDENSED_KEYS}"
        if "memory" in rec:
            assert set(rec["memory"].keys()) <= _CONDENSED_MEMORY_KEYS


def test_non_destructive_original_list_unchanged():
    records = [_make_record(f"exp_{i}") for i in range(5)]
    import copy

    original = copy.deepcopy(records)
    _truncate_memory_history(records, full_window=2)
    assert records == original


def test_empty_list():
    assert _truncate_memory_history([], full_window=3) == []


def test_missing_memory_key_handled():
    """Records without a 'memory' block should not crash."""
    records = [
        {"exp_id": f"exp_{i}", "status": "success", "denoising_score": 1.0} for i in range(5)
    ]
    result = _truncate_memory_history(records, full_window=2)
    assert len(result) == 5
    for rec in result[:3]:
        assert "memory" not in rec


def test_json_size_reduction():
    """Condensed history should be substantially smaller than full."""
    records = [_make_record(f"exp_{i}", score=float(i)) for i in range(10)]
    full_size = len(json.dumps(records, indent=2))
    truncated = _truncate_memory_history(records, full_window=3)
    truncated_size = len(json.dumps(truncated, indent=2))
    # Expect at least 50% reduction (7 of 10 records condensed)
    assert truncated_size < full_size * 0.7, (
        f"truncated={truncated_size}, full={full_size} — expected at least 30% reduction"
    )
