"""SpectralPeakRatioCheck tests (M8 §3.4).

Recording-only: records PSD(peak) / median(neighborhood) per file. Uses
production find_peak so the check sees what get_snr would see.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from execute_tools.health_checks._composition import (
    VALUE_SCALE_PARAMETER,
    VALUE_SCALE_UNIT_PARAMETER,
)
from execute_tools.health_checks.schemas import HealthCheckContext
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck
from tests.helpers.two_family_profile import write_bound_timeseries


def _write_ch1(path, ch1: np.ndarray) -> None:
    write_bound_timeseries(path, ch1)


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


TIDMAD_VALUE_SCALE: dict[str, object] = {
    VALUE_SCALE_PARAMETER: 40.0 / 128.0,
    VALUE_SCALE_UNIT_PARAMETER: "mV",
}
"""The scale composition injects for TIDMAD (Step 08b C5).

These tests assert MILLIVOLT arithmetic, so they now have to say what a
millivolt is. Before C5 the factor was a module-local literal inside the
check and every test inherited it silently — which is exactly why no task
could supply a different one."""


def _cfg(**overrides) -> dict:
    """Check config as composition would build it: scale + the test's keys."""
    return {**TIDMAD_VALUE_SCALE, **overrides}


class TestSpectralPeakRatioCheck:
    def test_synthetic_sinusoid_produces_finite_high_ratio(self, tmp_path):
        """Sinusoid at 1 kHz: PSD peak is dominant → ratio finite and high."""
        n = 100_000
        fs = 10_000_000.0
        t = np.arange(n) / fs
        sig = np.clip(60 * np.sin(2 * np.pi * 1000 * t), -128, 127).astype(np.int8)
        p = tmp_path / "sin.h5"
        _write_ch1(p, sig)
        ctx = _ctx(denoised_paths={0: str(p)})
        r = SpectralPeakRatioCheck().run(ctx, config=_cfg(**{"peek_samples": n}))
        assert r.passed is True  # recording-only
        per_file = json.loads(r.metrics["ratio_per_file_json"])
        # For a strong pure sinusoid the peak dominates the neighborhood.
        # Not asserting a specific ratio value (depends on windowing) —
        # just that it's finite and positive.
        assert np.isfinite(per_file["0"])
        assert per_file["0"] > 0

    def test_constant_output_produces_nan_ratio(self, tmp_path):
        """Constant int8 output → noise_win at subnormal → ratio=NaN."""
        n = 100_000
        p = tmp_path / "const.h5"
        _write_ch1(p, np.full(n, -65, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        r = SpectralPeakRatioCheck().run(ctx, config=_cfg(**{"peek_samples": n}))
        assert r.passed is True  # recording-only
        per_file = json.loads(r.metrics["ratio_per_file_json"])
        # Constant signal → noise window at subnormal → guarded to NaN
        assert per_file["0"] != per_file["0"]  # NaN

    def test_all_io_failure_returns_passed_false(self, tmp_path):
        ctx = _ctx(
            denoised_paths={
                0: str(tmp_path / "missing0.h5"),
                1: str(tmp_path / "missing1.h5"),
            }
        )
        r = SpectralPeakRatioCheck().run(ctx, config=_cfg())
        assert r.passed is False
        assert r.metrics["n_files_io_failed"] == 2

    def test_no_files_passes_not_applicable(self):
        r = SpectralPeakRatioCheck().run(_ctx(), config=_cfg())
        assert r.passed is True
        assert "no files in context" in r.reason

    def test_metrics_include_summary_stats_when_measured(self, tmp_path):
        n = 100_000
        rng = np.random.default_rng(0)
        p = tmp_path / "n.h5"
        _write_ch1(p, rng.integers(-40, 41, size=n, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        r = SpectralPeakRatioCheck().run(ctx, config=_cfg(**{"peek_samples": n}))
        assert r.passed is True
        # Summary stats present because at least one file measured
        assert "ratio_mean" in r.metrics
        assert "ratio_median" in r.metrics


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
