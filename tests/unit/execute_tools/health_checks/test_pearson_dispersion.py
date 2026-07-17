"""PearsonDispersionCheck tests (M8 §3.4 — revised 2026-07-16).

Recording-only: exposes only pearson_dispersion = stdev(per_file_pearsons)
as a scalar in metrics. Per-file values are computed internally but NOT
exposed (they were shown uninformative per-file in
docs/design/paper_and_collapse_reference_baselines.md §6.3).
"""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
from execute_tools.health_checks.schemas import HealthCheckContext


def _write_two_channel(path, ch1: np.ndarray, ch2: np.ndarray) -> None:
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=ch1, chunks=True)
        c2 = ts.create_group("channel0002")
        c2.create_dataset("timeseries", data=ch2, chunks=True)


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


class TestPearsonDispersionCheck:
    def test_no_target_path_fn_passes_not_applicable(self, tmp_path):
        d = tmp_path / "d0.h5"
        _write_two_channel(d, np.zeros(100, np.int8), np.zeros(100, np.int8))
        ctx = _ctx(denoised_paths={0: str(d)})
        r = PearsonDispersionCheck().run(ctx)
        assert r.passed is True
        assert "not applicable" in r.reason
        # No per-file exposure regardless of context state
        assert "pearson_per_file_json" not in r.metrics

    def test_multi_file_dispersion_reflects_stdev_of_per_file_values(self, tmp_path):
        """Two paired-file setups with different correlation strengths must
        produce a non-zero pearson_dispersion."""
        rng = np.random.default_rng(0)
        n = 50_000
        # File 0: strong correlation (shared signal)
        base_0 = rng.integers(-30, 31, size=n, dtype=np.int8)
        d0 = tmp_path / "d0.h5"
        t0 = tmp_path / "t0.h5"
        _write_two_channel(d0, ch1=base_0, ch2=np.zeros(n, np.int8))
        _write_two_channel(t0, ch1=np.zeros(n, np.int8), ch2=base_0)
        # File 1: uncorrelated noise
        base_1 = rng.integers(-30, 31, size=n, dtype=np.int8)
        target_1 = rng.integers(-30, 31, size=n, dtype=np.int8)
        d1 = tmp_path / "d1.h5"
        t1 = tmp_path / "t1.h5"
        _write_two_channel(d1, ch1=base_1, ch2=np.zeros(n, np.int8))
        _write_two_channel(t1, ch1=np.zeros(n, np.int8), ch2=target_1)

        ctx = _ctx(
            denoised_paths={0: str(d0), 1: str(d1)},
            target_path_fn=lambda i: str(t0) if i == 0 else str(t1),
        )
        r = PearsonDispersionCheck().run(ctx, config={"peek_samples": n})
        assert r.passed is True
        assert r.metrics["n_files_measured"] == 2
        # Non-zero dispersion because per-file pearsons differ substantially
        assert r.metrics["pearson_dispersion"] > 0.1

    def test_single_file_dispersion_is_nan(self, tmp_path):
        """A single measured value cannot yield a stdev — report NaN."""
        n = 10_000
        rng = np.random.default_rng(1)
        base = rng.integers(-20, 21, size=n, dtype=np.int8)
        d0 = tmp_path / "d.h5"
        t0 = tmp_path / "t.h5"
        _write_two_channel(d0, ch1=base, ch2=np.zeros(n, np.int8))
        _write_two_channel(t0, ch1=np.zeros(n, np.int8), ch2=base)
        ctx = _ctx(
            denoised_paths={0: str(d0)},
            target_path_fn=lambda i: str(t0),
        )
        r = PearsonDispersionCheck().run(ctx, config={"peek_samples": n})
        assert r.passed is True
        assert r.metrics["n_files_measured"] == 1
        # Sample stdev is undefined for n=1 → NaN by convention
        assert r.metrics["pearson_dispersion"] != r.metrics["pearson_dispersion"]  # NaN
        assert r.metrics["pearson_range"] == 0.0

    def test_all_files_io_failure_returns_passed_false(self, tmp_path):
        ctx = _ctx(
            denoised_paths={
                0: str(tmp_path / "missing0.h5"),
                1: str(tmp_path / "missing1.h5"),
            },
            target_path_fn=lambda i: str(tmp_path / f"tmissing{i}.h5"),
        )
        r = PearsonDispersionCheck().run(ctx)
        assert r.passed is False
        assert "all 2 files failed I/O" in r.reason
        assert r.metrics["n_files_measured"] == 0
        assert r.metrics["n_files_io_failed"] == 2

    def test_partial_io_failure_measures_available_files(self, tmp_path):
        """One file OK, one missing → still reports dispersion using what's available."""
        rng = np.random.default_rng(2)
        n = 10_000
        base_0 = rng.integers(-20, 21, size=n, dtype=np.int8)
        base_1 = rng.integers(-20, 21, size=n, dtype=np.int8)
        d0 = tmp_path / "d0.h5"
        t0 = tmp_path / "t0.h5"
        d1 = tmp_path / "d1.h5"
        t1 = tmp_path / "t1.h5"
        _write_two_channel(d0, ch1=base_0, ch2=np.zeros(n, np.int8))
        _write_two_channel(t0, ch1=np.zeros(n, np.int8), ch2=base_0)
        _write_two_channel(d1, ch1=base_1, ch2=np.zeros(n, np.int8))
        _write_two_channel(t1, ch1=np.zeros(n, np.int8), ch2=base_1)
        ctx = _ctx(
            denoised_paths={
                0: str(d0),
                1: str(d1),
                2: str(tmp_path / "missing2.h5"),
            },
            target_path_fn=(
                lambda i: (
                    str(t0) if i == 0 else str(t1) if i == 1 else str(tmp_path / f"tmissing{i}.h5")
                )
            ),
        )
        r = PearsonDispersionCheck().run(ctx, config={"peek_samples": n})
        assert r.passed is True
        assert r.metrics["n_files_measured"] == 2
        assert r.metrics["n_files_io_failed"] == 1

    def test_metrics_never_contain_per_file_json(self, tmp_path):
        """Regression guard: per-file values must NEVER be exposed
        (the whole design change from pearson_correlation → pearson_dispersion
        was to hide them)."""
        rng = np.random.default_rng(3)
        n = 10_000
        base = rng.integers(-20, 21, size=n, dtype=np.int8)
        d0 = tmp_path / "d.h5"
        t0 = tmp_path / "t.h5"
        _write_two_channel(d0, ch1=base, ch2=np.zeros(n, np.int8))
        _write_two_channel(t0, ch1=np.zeros(n, np.int8), ch2=base)
        ctx = _ctx(
            denoised_paths={0: str(d0)},
            target_path_fn=lambda i: str(t0),
        )
        r = PearsonDispersionCheck().run(ctx, config={"peek_samples": n})
        assert r.passed is True
        forbidden_keys = {"pearson_per_file_json", "per_file_pearsons"}
        assert not (set(r.metrics.keys()) & forbidden_keys)

    def test_no_files_at_all_passes_not_applicable(self):
        ctx = _ctx(target_path_fn=lambda i: f"/nowhere/{i}.h5")
        r = PearsonDispersionCheck().run(ctx)
        assert r.passed is True
        assert "no files in context" in r.reason
