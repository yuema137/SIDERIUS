"""PerFileOutputStdCheck tests (M8 §3.4).

Recording-only: per-file std distribution. Complements OutputStdCheck
(aggregate) with per-file granularity for diagnosis.
"""

from __future__ import annotations

import json

import h5py
import numpy as np

from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
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


class TestPerFileOutputStdCheck:
    def test_uniform_std_across_files(self, tmp_path):
        """Three files with the same std → tight distribution."""
        rng = np.random.default_rng(0)
        paths = {}
        for i in range(3):
            p = tmp_path / f"d{i}.h5"
            _write_ch1(p, rng.integers(-24, 25, size=10_000, dtype=np.int8))
            paths[i] = str(p)
        ctx = _ctx(denoised_paths=paths)
        r = PerFileOutputStdCheck().run(ctx, config={"peek_samples": 10_000})
        assert r.passed is True
        assert r.metrics["n_files_measured"] == 3
        # Std distribution is tight (all ~ same); max - min should be small
        assert r.metrics["std_mv_max"] - r.metrics["std_mv_min"] < 1.0

    def test_varying_std_across_files_produces_wide_distribution(self, tmp_path):
        """Mix low-std collapse files with high-std healthy files."""
        rng = np.random.default_rng(1)
        paths = {}
        # File 0: near-constant → low std
        collapse = np.full(10_000, -65, dtype=np.int8)
        collapse[:5] = -68
        p0 = tmp_path / "d0.h5"
        _write_ch1(p0, collapse)
        paths[0] = str(p0)
        # File 1: wide range → high std
        wide = rng.integers(-60, 61, size=10_000, dtype=np.int8)
        p1 = tmp_path / "d1.h5"
        _write_ch1(p1, wide)
        paths[1] = str(p1)

        ctx = _ctx(denoised_paths=paths)
        r = PerFileOutputStdCheck().run(ctx, config={"peek_samples": 10_000})
        assert r.passed is True
        assert r.metrics["n_files_measured"] == 2
        # Wide distribution: max >> min
        assert r.metrics["std_mv_max"] > r.metrics["std_mv_min"] * 100
        per_file = json.loads(r.metrics["std_mv_per_file_json"])
        assert per_file["0"] < 0.1
        assert per_file["1"] > 5.0

    def test_all_io_failure_returns_passed_false(self, tmp_path):
        ctx = _ctx(
            denoised_paths={
                0: str(tmp_path / "missing0.h5"),
                1: str(tmp_path / "missing1.h5"),
            }
        )
        r = PerFileOutputStdCheck().run(ctx)
        assert r.passed is False
        assert r.metrics["n_files_io_failed"] == 2

    def test_partial_io_failure_records_measured_only(self, tmp_path):
        """One file OK, one missing → passed=True, per-file JSON has only the OK one."""
        rng = np.random.default_rng(2)
        good = tmp_path / "good.h5"
        _write_ch1(good, rng.integers(-30, 31, size=5_000, dtype=np.int8))
        ctx = _ctx(
            denoised_paths={
                0: str(good),
                1: str(tmp_path / "missing.h5"),
            }
        )
        r = PerFileOutputStdCheck().run(ctx, config={"peek_samples": 5_000})
        assert r.passed is True
        assert r.metrics["n_files_measured"] == 1
        assert r.metrics["n_files_io_failed"] == 1
        per_file = json.loads(r.metrics["std_mv_per_file_json"])
        assert "0" in per_file
        assert "1" not in per_file

    def test_no_files_passes_not_applicable(self):
        r = PerFileOutputStdCheck().run(_ctx())
        assert r.passed is True
        assert "no files in context" in r.reason
