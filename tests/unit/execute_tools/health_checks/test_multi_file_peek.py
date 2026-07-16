"""Multi-file peek helper tests (M9 §5.1).

Covers ``peek_and_aggregate`` for all six aggregation modes plus the
three ambiguity cases from the M9 plan (§4.3):
  1. Empty ``peek_file_indices`` → fallback to single-file min-key or [0].
  2. I/O failure on a subset — differing semantics per aggregation mode.
  3. ``peek_file_indices`` contains an index not in ``denoised_paths``.

Also covers backward-compat with the pre-M9 output_diversity "not
applicable" contract for empty contexts.
"""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from execute_tools.health_checks._multi_file_peek import (
    MultiFilePeekOutcome,
    PerFilePeekResult,
    peek_and_aggregate,
)
from execute_tools.health_checks.schemas import HealthCheckContext


def _write_ch1(path, ch1: np.ndarray) -> None:
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=ch1, chunks=True)


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


def _metric_unique(arr: np.ndarray) -> int:
    return len(np.unique(arr))


def _predicate_gt_10(v):
    return v > 10


def _predicate_gt_100(v):
    return v > 100


# ---------------------------------------------------------------------------
# Backward-compat: empty peek_file_indices → single-file min-key fallback
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_empty_indices_falls_back_to_min_key(self, tmp_path):
        """Explicit denoised_paths → fallback picks min key (0 wins over 5)."""
        p0 = tmp_path / "d0.h5"
        p5 = tmp_path / "d5.h5"
        _write_ch1(p0, np.tile(np.arange(-30, 30, dtype=np.int8), 2000))
        _write_ch1(p5, np.full(10_000, -65, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p0), 5: str(p5)})
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[],  # backward-compat fallback
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.n_files_attempted == 1
        assert outcome.per_file[0].file_index == 0  # min key
        assert outcome.passed is True

    def test_empty_indices_and_no_paths_returns_not_applicable(self):
        """Pre-M9 output_diversity behavior: no paths at all → pass with 'not applicable'."""
        ctx = _ctx()  # no denoised_paths, no denoised_filename_fn
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is True
        assert "not applicable" in outcome.reason

    def test_empty_indices_with_filename_fn_but_missing_file_is_io_error(self, tmp_path):
        """denoised_filename_fn returns a real string, but the file doesn't
        exist — that's an I/O error, NOT 'not applicable'."""
        missing = tmp_path / "missing.h5"
        ctx = _ctx(denoised_filename_fn=lambda i: str(missing))
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is False
        assert outcome.n_files_io_failed == 1


# ---------------------------------------------------------------------------
# any_pass — dropping I/O failures from consideration
# ---------------------------------------------------------------------------


class TestAnyPass:
    def test_all_three_pass(self, tmp_path):
        paths = {}
        for i in (3, 10, 17):
            p = tmp_path / f"d{i}.h5"
            _write_ch1(p, np.tile(np.arange(-30, 30, dtype=np.int8), 500))
            paths[i] = str(p)
        ctx = _ctx(denoised_paths=paths)
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=30_000,
        )
        assert outcome.passed is True
        assert outcome.n_files_attempted == 3
        assert all(r.passed for r in outcome.per_file)

    def test_one_passes(self, tmp_path):
        """3 files: 1 diverse, 2 near-constant → any_pass passes."""
        p3 = tmp_path / "d3.h5"
        p10 = tmp_path / "d10.h5"
        p17 = tmp_path / "d17.h5"
        _write_ch1(p3, np.full(10_000, -65, dtype=np.int8))
        _write_ch1(p10, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        _write_ch1(p17, np.full(10_000, 5, dtype=np.int8))
        ctx = _ctx(denoised_paths={3: str(p3), 10: str(p10), 17: str(p17)})
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is True
        # Exactly one file passed
        assert sum(r.passed for r in outcome.per_file) == 1

    def test_none_pass(self, tmp_path):
        """3 files all near-constant → any_pass fails."""
        paths = {}
        for i in (3, 10, 17):
            p = tmp_path / f"d{i}.h5"
            _write_ch1(p, np.full(10_000, -65, dtype=np.int8))
            paths[i] = str(p)
        ctx = _ctx(denoised_paths=paths)
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is False
        assert "aggregation=any_pass failed" in outcome.reason

    def test_one_ok_two_io_failures(self, tmp_path):
        """1 OK diverse file + 2 missing → any_pass passes (drops failed)."""
        p3 = tmp_path / "d3.h5"
        _write_ch1(p3, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        ctx = _ctx(
            denoised_paths={
                3: str(p3),
                10: str(tmp_path / "missing10.h5"),
                17: str(tmp_path / "missing17.h5"),
            }
        )
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is True
        assert outcome.n_files_io_failed == 2
        assert outcome.n_files_attempted == 3

    def test_all_three_io_failures(self, tmp_path):
        """All 3 missing → any_pass fails; reason mentions I/O."""
        ctx = _ctx(
            denoised_paths={
                3: str(tmp_path / "m3.h5"),
                10: str(tmp_path / "m10.h5"),
                17: str(tmp_path / "m17.h5"),
            }
        )
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is False
        assert outcome.n_files_io_failed == 3
        assert "all 3 peeked file(s) failed I/O" in outcome.reason


# ---------------------------------------------------------------------------
# all_pass — I/O failure counts as fail
# ---------------------------------------------------------------------------


class TestAllPass:
    def test_all_three_pass(self, tmp_path):
        paths = {}
        for i in (3, 10, 17):
            p = tmp_path / f"d{i}.h5"
            _write_ch1(p, np.tile(np.arange(-30, 30, dtype=np.int8), 500))
            paths[i] = str(p)
        ctx = _ctx(denoised_paths=paths)
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="all_pass",
            peek_samples=30_000,
        )
        assert outcome.passed is True

    def test_two_pass_one_fail(self, tmp_path):
        """3 files, 2 diverse + 1 near-constant → all_pass fails."""
        p3 = tmp_path / "d3.h5"
        p10 = tmp_path / "d10.h5"
        p17 = tmp_path / "d17.h5"
        _write_ch1(p3, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        _write_ch1(p10, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        _write_ch1(p17, np.full(10_000, -65, dtype=np.int8))
        ctx = _ctx(denoised_paths={3: str(p3), 10: str(p10), 17: str(p17)})
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="all_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is False

    def test_one_ok_two_io_failures_fails(self, tmp_path):
        """all_pass strictest: I/O failure counts as fail even if only file
        with real data is diverse."""
        p3 = tmp_path / "d3.h5"
        _write_ch1(p3, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        ctx = _ctx(
            denoised_paths={
                3: str(p3),
                10: str(tmp_path / "missing10.h5"),
                17: str(tmp_path / "missing17.h5"),
            }
        )
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="all_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is False


# ---------------------------------------------------------------------------
# max / min / mean / median — apply predicate to aggregated metric
# ---------------------------------------------------------------------------


class TestNumericAggregations:
    @staticmethod
    def _write_three_diverse_files(tmp_path):
        """Return paths + expected uniq counts. Diverse ranges chosen so
        the three files have distinct unique counts for aggregation."""
        p3 = tmp_path / "d3.h5"
        p10 = tmp_path / "d10.h5"
        p17 = tmp_path / "d17.h5"
        _write_ch1(p3, np.arange(-5, 5, dtype=np.int8).repeat(2000))  # ~10 uniq
        _write_ch1(p10, np.tile(np.arange(-30, 30, dtype=np.int8), 200))  # ~60 uniq
        _write_ch1(p17, np.arange(-60, 60, dtype=np.int8).repeat(100))  # ~120 uniq
        return {3: str(p3), 10: str(p10), 17: str(p17)}

    def _outcome(self, tmp_path, aggregation, predicate):
        ctx = _ctx(denoised_paths=self._write_three_diverse_files(tmp_path))
        return peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=predicate,
            aggregation=aggregation,
            peek_samples=20_000,
        )

    def test_max_passes_at_120(self, tmp_path):
        outcome = self._outcome(tmp_path, "max", _predicate_gt_100)
        assert outcome.passed is True  # max is ~120 > 100
        values = [r.metric_value for r in outcome.per_file]
        assert max(values) > 100

    def test_max_fails_at_high_threshold(self, tmp_path):
        outcome = self._outcome(tmp_path, "max", lambda v: v > 200)
        assert outcome.passed is False

    def test_min_uses_worst_file(self, tmp_path):
        outcome = self._outcome(tmp_path, "min", _predicate_gt_10)
        # min is ~10, threshold > 10 (strict >) → fails
        assert outcome.passed is False

    def test_mean_uses_average(self, tmp_path):
        outcome = self._outcome(tmp_path, "mean", _predicate_gt_10)
        # mean of ~10, ~60, ~120 = ~63.3 > 10 → passes
        assert outcome.passed is True

    def test_median_uses_middle(self, tmp_path):
        outcome = self._outcome(tmp_path, "median", _predicate_gt_100)
        # median of ~10, ~60, ~120 = ~60 → fails 100
        assert outcome.passed is False

    def test_all_io_failures_numeric_aggregation_fails(self, tmp_path):
        ctx = _ctx(
            denoised_paths={
                3: str(tmp_path / "m3.h5"),
                10: str(tmp_path / "m10.h5"),
                17: str(tmp_path / "m17.h5"),
            }
        )
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="max",
            peek_samples=10_000,
        )
        assert outcome.passed is False
        assert outcome.n_files_io_failed == 3


# ---------------------------------------------------------------------------
# Edge cases: unresolved paths, deduplication, unknown aggregation
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_index_not_in_denoised_paths_and_no_fn(self, tmp_path):
        """peek_file_indices=[3, 10, 17] but denoised_paths only has {3}."""
        p3 = tmp_path / "d3.h5"
        _write_ch1(p3, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        ctx = _ctx(denoised_paths={3: str(p3)})
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        # File 3 succeeds and passes; 10 and 17 unresolvable → io_error
        assert outcome.passed is True  # any_pass
        assert outcome.n_files_io_failed == 2
        io_reasons = [r.io_error for r in outcome.per_file if r.io_error]
        assert all("no path resolved" in e for e in io_reasons)

    def test_deduplicates_indices(self, tmp_path):
        p3 = tmp_path / "d3.h5"
        _write_ch1(p3, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        ctx = _ctx(denoised_paths={3: str(p3)})
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 3, 3],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.n_files_attempted == 1  # deduped

    def test_unknown_aggregation_raises(self, tmp_path):
        p = tmp_path / "d.h5"
        _write_ch1(p, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        ctx = _ctx(denoised_paths={0: str(p)})
        with pytest.raises(ValueError, match="unknown aggregation"):
            peek_and_aggregate(
                ctx,
                peek_file_indices=[0],
                metric_fn=_metric_unique,
                predicate=_predicate_gt_10,
                aggregation="bogus",  # type: ignore[arg-type]
                peek_samples=10_000,
            )

    def test_constant_channel_does_not_crash(self, tmp_path):
        """A constant int8 output (std=0) should still peek and compute
        metric normally — the helper doesn't inject any special-case
        NaN handling; that's each check's responsibility."""
        p = tmp_path / "const.h5"
        _write_ch1(p, np.full(10_000, -65, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[0],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.n_files_attempted == 1
        assert outcome.per_file[0].metric_value == 1  # single unique value
        assert outcome.per_file[0].passed is False


# ---------------------------------------------------------------------------
# Outcome shape — record observability
# ---------------------------------------------------------------------------


class TestOutcomeShape:
    def test_per_file_populated_on_failure(self, tmp_path):
        """Even when the aggregate fails, per_file must be populated with
        full detail so the round record can render the failure reason."""
        paths = {}
        for i in (3, 10, 17):
            p = tmp_path / f"d{i}.h5"
            _write_ch1(p, np.full(10_000, -65, dtype=np.int8))
            paths[i] = str(p)
        ctx = _ctx(denoised_paths=paths)
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[3, 10, 17],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        assert outcome.passed is False
        assert len(outcome.per_file) == 3
        for r in outcome.per_file:
            assert r.metric_value == 1
            assert r.passed is False
            assert r.io_error is None

    def test_outcome_serialisable(self, tmp_path):
        """MultiFilePeekOutcome must round-trip through Pydantic dump —
        callers persist per_file via json.dumps."""
        p = tmp_path / "d.h5"
        _write_ch1(p, np.tile(np.arange(-30, 30, dtype=np.int8), 200))
        ctx = _ctx(denoised_paths={0: str(p)})
        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=[0],
            metric_fn=_metric_unique,
            predicate=_predicate_gt_10,
            aggregation="any_pass",
            peek_samples=10_000,
        )
        dumped = outcome.model_dump()
        assert dumped["passed"] is True
        assert isinstance(dumped["per_file"], list)
        assert dumped["per_file"][0]["metric_value"] > 10
