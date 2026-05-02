"""
Pure-function tests for ``_aggregate_inference_file_timings`` in
``agent/skills/evaluate_time_skill/wrapper.py``.

Pins the contract that drives Commit C of
``docs/refine_inference_time_estimator.md``:

  * Discard a leading fraction of files (one-shot CUDA / cold-disk costs)
  * Normalise per PSD segment so trial files with 3 vs 8 segments are
    comparable
  * Return ``None`` whenever the signal is too sparse or degenerate, so
    the caller falls through to the legacy ``× 2.7`` ratio (Commit D)

No torch, no h5py, no subprocess — these tests run in milliseconds.
"""
from __future__ import annotations

import pytest

from agent.skills.evaluate_time_skill.wrapper import (
    _aggregate_inference_file_timings as agg,
)


def _row(file_index: int, n_psd_segs: int, elapsed_ms: float) -> dict:
    return {
        "file_index": file_index,
        "n_psd_segs": n_psd_segs,
        "elapsed_ms": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# Fallback paths — return None so the caller drops to the static ratio
# ---------------------------------------------------------------------------


class TestFallbackBranches:

    def test_empty_list_returns_none(self):
        value, bd = agg([])
        assert value is None
        assert bd["aggregator"] is None
        assert bd["n_timed_files"] == 0
        assert bd["timings_ms"] == []

    def test_single_file_returns_none(self):
        """One file is not enough — we'd be reporting the warmup leak as
        the median, which is exactly what the discard rule prevents."""
        value, bd = agg([_row(0, 5, 100.0)])
        assert value is None
        assert bd["aggregator"] is None
        # The single file still appears in the audit trail.
        assert len(bd["timings_ms"]) == 1

    def test_all_zero_elapsed_returns_none(self):
        """Degenerate sidecar — every file reports 0 elapsed. The
        aggregator must not return 0.0 (which would mask a broken
        measurement); returning None routes the gate to the constant
        ratio fallback."""
        rows = [_row(i, 2, 0.0) for i in range(5)]
        value, bd = agg(rows)
        assert value is None
        assert bd["aggregator"] is None

    def test_negative_elapsed_treated_as_degenerate(self):
        """Defensive: a corrupt sidecar with negative elapsed must not
        produce a negative ms estimate. ``all(v <= 0)`` covers this."""
        rows = [_row(i, 2, -10.0) for i in range(5)]
        value, bd = agg(rows)
        assert value is None


# ---------------------------------------------------------------------------
# Warmup-discard math — the n_warmup formula
# ---------------------------------------------------------------------------


class TestWarmupDiscard:

    def test_two_files_discards_one(self):
        """The smallest n_files that still produces a measurement.
        ``round(2 × 0.20) = 0`` rounds up via the ``max(1, ...)`` clamp."""
        rows = [_row(0, 1, 100.0), _row(1, 1, 50.0)]
        value, bd = agg(rows)
        assert value == pytest.approx(50.0)  # only file 1 timed
        assert bd["n_warmup_files"] == 1
        assert bd["n_timed_files"] == 1

    def test_five_files_discards_one(self):
        """``round(5 × 0.20) = 1`` exactly."""
        rows = [_row(i, 2, 10.0 + i) for i in range(5)]
        value, bd = agg(rows)
        # Drops file 0 (elapsed 10), times files 1-4 (elapsed 11..14).
        # per-PSD-seg = [11/2, 12/2, 13/2, 14/2] = [5.5, 6.0, 6.5, 7.0]
        # median (even n) = (6.0 + 6.5) / 2 = 6.25
        assert value == pytest.approx(6.25)
        assert bd["n_warmup_files"] == 1
        assert bd["n_timed_files"] == 4

    def test_ten_files_discards_two(self):
        """``round(10 × 0.20) = 2`` exactly."""
        rows = [_row(i, 1, 100.0) for i in range(10)]
        value, bd = agg(rows)
        assert bd["n_warmup_files"] == 2
        assert bd["n_timed_files"] == 8

    def test_twenty_files_discards_four(self):
        """Full eval-volume case (formal eval_portion=1.0 with 20 files)."""
        rows = [_row(i, 1, 100.0) for i in range(20)]
        value, bd = agg(rows)
        assert bd["n_warmup_files"] == 4
        assert bd["n_timed_files"] == 16

    def test_n_warmup_clamped_below_n_files(self):
        """The clamp ``min(..., n_files - 1)`` guarantees at least one
        timed file. With a high warmup_fraction this prevents
        ``timed = []``."""
        rows = [_row(i, 1, 100.0) for i in range(3)]
        value, bd = agg(rows, warmup_fraction=0.99)
        # round(3 × 0.99) = 3, clamped to n_files - 1 = 2.
        assert bd["n_warmup_files"] == 2
        assert bd["n_timed_files"] == 1
        assert value == pytest.approx(100.0)

    def test_zero_fraction_floors_at_one(self):
        """With ``warmup_fraction=0.0``, the ``max(1, ...)`` clamp still
        discards one file. Reasoning: even with the lowest configured
        warmup, the cold-disk read on file 0 is non-negligible."""
        rows = [_row(i, 1, 100.0) for i in range(5)]
        value, bd = agg(rows, warmup_fraction=0.0)
        assert bd["n_warmup_files"] == 1
        assert bd["n_timed_files"] == 4


# ---------------------------------------------------------------------------
# Per-PSD-segment normalisation — different segment counts per file
# ---------------------------------------------------------------------------


class TestPerPsdSegNormalisation:

    def test_mixed_segment_counts_normalise_correctly(self):
        """File A: 2 segs / 20 ms = 10 ms/seg. File B: 8 segs / 80 ms =
        10 ms/seg. Even though raw elapsed differs by 4×, the per-segment
        cost is identical and the median should report 10."""
        rows = [
            _row(0, 1, 50.0),    # warmup discarded
            _row(1, 2, 20.0),    # 10 ms/seg
            _row(2, 8, 80.0),    # 10 ms/seg
            _row(3, 4, 40.0),    # 10 ms/seg
        ]
        value, bd = agg(rows)
        # n_warmup = round(4 × 0.20) = 1. timed = files 1-3, all 10 ms/seg.
        assert value == pytest.approx(10.0)
        assert bd["n_timed_files"] == 3

    def test_variable_per_segment_cost_takes_median(self):
        """When per-segment cost legitimately varies (different file
        sizes, different segment alignment), the median is robust to
        one outlier."""
        rows = [
            _row(0, 4, 100.0),   # warmup discarded
            _row(1, 4, 40.0),    # 10 ms/seg
            _row(2, 4, 50.0),    # 12.5 ms/seg
            _row(3, 4, 1000.0),  # 250 ms/seg — outlier
            _row(4, 4, 60.0),    # 15 ms/seg
        ]
        value, bd = agg(rows)
        # timed = [10, 12.5, 250, 15] sorted = [10, 12.5, 15, 250]
        # median (even n) = (12.5 + 15) / 2 = 13.75
        # Mean would be ~72 — the outlier completely takes over.
        assert value == pytest.approx(13.75)

    def test_zero_n_psd_segs_treated_as_one(self):
        """Defensive: if a sidecar entry reports n_psd_segs=0 (would
        cause ZeroDivisionError), the ``max(..., 1)`` floor prevents it.
        The cost is conservatively counted as full elapsed (cost / 1)."""
        rows = [
            _row(0, 1, 100.0),
            _row(1, 0, 50.0),   # would divide by zero without the floor
            _row(2, 0, 30.0),
        ]
        value, bd = agg(rows)
        # n_warmup = round(3 × 0.20) = 1. timed = files 1-2 with
        # elapsed/max(0,1) = 50.0 and 30.0. median = 40.0.
        assert value == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Defensive consumption — partial / legacy sidecars
# ---------------------------------------------------------------------------


class TestDefensiveConsumption:

    def test_missing_n_psd_segs_defaults_to_one(self):
        """If a future or older sidecar omits n_psd_segs, treat each
        file as 1 segment (so the elapsed becomes the per-segment cost).
        Avoids a KeyError that would crash the whole gate verdict."""
        rows = [
            {"file_index": 0, "elapsed_ms": 100.0},  # no n_psd_segs
            {"file_index": 1, "elapsed_ms": 50.0},
            {"file_index": 2, "elapsed_ms": 30.0},
        ]
        value, bd = agg(rows)
        # n_warmup = 1; timed = [50, 30]; median = 40
        assert value == pytest.approx(40.0)

    def test_missing_elapsed_ms_treated_as_zero(self):
        """If elapsed_ms is missing on every timed file, treat as
        degenerate and return None — same as the all-zero branch."""
        rows = [
            {"file_index": 0, "n_psd_segs": 2, "elapsed_ms": 100.0},
            {"file_index": 1, "n_psd_segs": 2},  # no elapsed_ms
            {"file_index": 2, "n_psd_segs": 2},
        ]
        value, bd = agg(rows)
        assert value is None

    def test_breakdown_preserves_input_list_independence(self):
        """``breakdown["timings_ms"]`` must be a copy, not the input
        list — otherwise downstream mutation could clobber the caller's
        data."""
        rows = [_row(i, 1, 100.0) for i in range(3)]
        value, bd = agg(rows)
        bd["timings_ms"].append({"sentinel": True})
        assert all("sentinel" not in r for r in rows)


# ---------------------------------------------------------------------------
# Breakdown shape — symmetry with _aggregate_warmup_timings
# ---------------------------------------------------------------------------


class TestBreakdownShape:

    def test_breakdown_has_required_keys(self):
        """The five keys the tuner / audit log consumes."""
        rows = [_row(i, 1, 100.0) for i in range(5)]
        _, bd = agg(rows)
        for key in (
            "aggregator", "n_warmup_files", "n_timed_files",
            "warmup_fraction", "timings_ms",
        ):
            assert key in bd, f"breakdown missing required key: {key}"

    def test_warmup_fraction_echoed_in_breakdown(self):
        """The fraction the caller passed is round-tripped so an
        operator looking at a record knows exactly which discard rule
        produced the median."""
        rows = [_row(i, 1, 100.0) for i in range(5)]
        _, bd = agg(rows, warmup_fraction=0.30)
        assert bd["warmup_fraction"] == 0.30

    def test_aggregator_is_median_when_value_returned(self):
        rows = [_row(i, 1, 100.0) for i in range(5)]
        value, bd = agg(rows)
        assert value is not None
        assert bd["aggregator"] == "median"

    def test_aggregator_is_none_when_value_is_none(self):
        rows = []
        value, bd = agg(rows)
        assert value is None
        assert bd["aggregator"] is None
