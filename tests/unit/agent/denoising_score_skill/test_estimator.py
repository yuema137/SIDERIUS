"""
Tests for agent/skills/denoising_score_skill/estimator.py

K.2.5 Commit 4 covers:

- ``estimate_peak_bytes``:
  * always 0 bytes (scoring is CPU-only by design).
  * phase tag and empty breakdown.

- ``estimate_wall_time_seconds``:
  * shape ``{"phase", "seconds", "breakdown"}``.
  * linear in total PSD-segment count.
  * inverse in ``num_workers``; ``num_workers=0`` floored to 1.
  * ligroup path applies the measured 0.613 s/segment.
  * unknown host falls back to ligroup with a ``UserWarning``.
"""

from __future__ import annotations

import pytest

import core.server_configs as sc
from agent.skills.denoising_score_skill import estimator as est


def _sample_set(total_segments: int, n_files: int = 20) -> dict:
    """Build a sample_set with ``total_segments`` split over ``n_files``."""
    per_file = total_segments // n_files
    return {i: list(range(per_file)) for i in range(n_files)}


# ---------------------------------------------------------------------------
# estimate_peak_bytes
# ---------------------------------------------------------------------------

class TestEstimatePeakBytes:

    def test_zero_vram(self):
        out = est.estimate_peak_bytes()
        assert out["phase"] == "scoring"
        assert out["total_bytes"] == 0
        assert out["breakdown"] == {}


# ---------------------------------------------------------------------------
# estimate_wall_time_seconds
# ---------------------------------------------------------------------------

class TestEstimateWallTimeSeconds:

    def test_return_shape(self):
        out = est.estimate_wall_time_seconds(_sample_set(400), hostname="ligroup")
        assert set(out.keys()) == {"phase", "seconds", "breakdown"}
        assert out["phase"] == "scoring"
        assert out["seconds"] > 0
        assert set(out["breakdown"].keys()) == {
            "total_psd_segments", "num_workers",
            "per_psd_segment_seconds", "hostname",
        }

    def test_linear_in_segments(self):
        small = est.estimate_wall_time_seconds(_sample_set(100), hostname="ligroup")
        big   = est.estimate_wall_time_seconds(_sample_set(400), hostname="ligroup")
        assert big["seconds"] == pytest.approx(4 * small["seconds"], rel=1e-6)

    def test_inverse_in_num_workers(self):
        few  = est.estimate_wall_time_seconds(
            _sample_set(400), num_workers=4, hostname="ligroup",
        )
        many = est.estimate_wall_time_seconds(
            _sample_set(400), num_workers=8, hostname="ligroup",
        )
        assert few["seconds"] == pytest.approx(2 * many["seconds"], rel=1e-6)

    def test_num_workers_zero_floored_to_one(self):
        zero = est.estimate_wall_time_seconds(
            _sample_set(100), num_workers=0, hostname="ligroup",
        )
        one = est.estimate_wall_time_seconds(
            _sample_set(100), num_workers=1, hostname="ligroup",
        )
        assert zero["seconds"] == pytest.approx(one["seconds"])
        assert zero["breakdown"]["num_workers"] == 1

    def test_ligroup_arithmetic_against_measured_constant(self):
        """400 segments / 8 workers × 0.613 s = 30.65 s."""
        out = est.estimate_wall_time_seconds(
            _sample_set(400), num_workers=8, hostname="ligroup",
        )
        assert out["seconds"] == pytest.approx(400 * 0.613 / 8, rel=1e-6)
        assert out["breakdown"]["per_psd_segment_seconds"] == pytest.approx(0.613)
        assert out["breakdown"]["hostname"] == "ligroup"
        assert out["breakdown"]["total_psd_segments"] == 400

    def test_unknown_host_falls_back_to_ligroup(self, monkeypatch):
        monkeypatch.setattr(sc, "_WARNED_HOSTS", set())
        with pytest.warns(UserWarning):
            out = est.estimate_wall_time_seconds(
                _sample_set(400), hostname="fake-host-xyz",
            )
        assert out["breakdown"]["hostname"] == "ligroup"
        assert out["breakdown"]["per_psd_segment_seconds"] == pytest.approx(0.613)
