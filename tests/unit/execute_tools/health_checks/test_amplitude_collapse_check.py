"""AmplitudeCollapseCheck (rev-6, distribution-based) — single-bin dominance.

Rev-6 Protocol: no ``is_applicable``, ``run(ctx, config=None) -> HealthCheckResult``,
``passed=True`` means healthy. Predicate: ``dominant_fraction > threshold``
(strict; exactly-at-threshold does NOT trip, per design §9.2).

Failure-mode taxonomy (identical to OutputDiversityCheck per operator
correction on 4a):
    * ``get_denoised_path`` returns None → passed=True with "not applicable" reason.
    * OSError / KeyError on peek → passed=False with the attempted path in reason.
    * Peek returns 0 samples → passed=False with "empty peek" reason
      (AMB-4b-EMPTY → A).
    * Peek succeeds and dominant_fraction > threshold → passed=False with
      ``dominant_class`` + ``dominant_fraction`` in metrics.
    * Otherwise → passed=True.
"""

from __future__ import annotations

import json

import h5py
import numpy as np

from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.schemas import HealthCheckContext


def _per_file(result) -> list[dict]:
    """M9: per-file breakdown is JSON-serialised in metrics['per_file_json']."""
    return json.loads(result.metrics["per_file_json"])


def _write_denoised_h5(path, ch1: np.ndarray) -> None:
    """Write a minimal denoised HDF5 with ``channel0001/timeseries`` populated."""
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=ch1, chunks=True)


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


# ---------------------------------------------------------------------------
# Single-bin dominance → passed=False
# ---------------------------------------------------------------------------


class TestSingleBinDominance:
    def test_100_percent_same_class_is_flagged(self, tmp_path):
        """The v16 canonical case: constant int8=-1 (class 127) → 100% dominance."""
        p = tmp_path / "denoised.h5"
        _write_denoised_h5(p, np.full(100_000, -1, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        result = AmplitudeCollapseCheck().run(ctx, {"collapse_threshold": 0.95})
        assert result.passed is False
        assert result.check_name == "amplitude_collapse"
        # M9: dominant_class is no longer exposed (metric_fn returns only
        # the fraction). Operator can recover it from the raw data if
        # needed for diagnosis.
        assert _per_file(result)[0]["metric_value"] == 1.0
        assert "amplitude_collapse" in result.reason

    def test_96_percent_dominance_is_flagged(self, tmp_path):
        """96% of one class, 4% spread — > 0.95 threshold → flagged.

        Variety range ``arange(1, 41)`` is 40 positive values with NO zeros —
        keeps the dominant-fraction arithmetic clean (any 0 in the tile
        would inflate the dominant-class count and skew this test).
        """
        p = tmp_path / "denoised.h5"
        # 96,000 zeros + 4,000 non-zero variety → dominant class = 0 at exactly 0.96
        arr = np.concatenate(
            [
                np.zeros(96_000, dtype=np.int8),
                np.tile(np.arange(1, 41, dtype=np.int8), 100),  # 40 * 100 = 4000
            ]
        )
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        result = AmplitudeCollapseCheck().run(ctx, {"collapse_threshold": 0.95})
        assert result.passed is False
        # M9: dominant_class no longer exposed; check the fraction only.
        assert _per_file(result)[0]["metric_value"] == 0.96


# ---------------------------------------------------------------------------
# Healthy distribution → passed=True
# ---------------------------------------------------------------------------


class TestHealthyDistribution:
    def test_uniform_distribution_not_flagged(self, tmp_path):
        """Uniform int8 in [-25, 25] → dominant_fraction ≈ 1/50 = 0.02."""
        p = tmp_path / "denoised.h5"
        rng = np.random.default_rng(42)
        arr = rng.integers(-25, 25, size=100_000, dtype=np.int8)
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        result = AmplitudeCollapseCheck().run(ctx, {"collapse_threshold": 0.95})
        assert result.passed is True
        assert result.reason == ""
        assert _per_file(result)[0]["metric_value"] < 0.1  # nowhere near 0.95

    def test_balanced_two_class_not_flagged(self, tmp_path):
        """50/50 two classes → dominant_fraction ≈ 0.5, far below 0.95."""
        p = tmp_path / "denoised.h5"
        arr = np.tile(np.array([-1, 1], dtype=np.int8), 50_000)
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        result = AmplitudeCollapseCheck().run(ctx, {"collapse_threshold": 0.95})
        assert result.passed is True
        assert _per_file(result)[0]["metric_value"] == 0.5


# ---------------------------------------------------------------------------
# Strict `>` boundary (design §9.2)
# ---------------------------------------------------------------------------


class TestStrictThresholdBoundary:
    def test_exactly_at_threshold_not_flagged(self, tmp_path):
        """Exactly 95% dominance with threshold=0.95 → strict `>` → not flagged."""
        p = tmp_path / "denoised.h5"
        # 95,000 zeros + 5,000 ones → 0.95 exactly.
        arr = np.concatenate(
            [
                np.zeros(95_000, dtype=np.int8),
                np.ones(5_000, dtype=np.int8),
            ]
        )
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        result = AmplitudeCollapseCheck().run(ctx, {"collapse_threshold": 0.95})
        assert result.passed is True
        assert _per_file(result)[0]["metric_value"] == 0.95


# ---------------------------------------------------------------------------
# Path resolution — AMB-4-5 → A
# ---------------------------------------------------------------------------


class TestPathResolution:
    def test_uses_denoised_filename_fn_with_default_file_index_zero(self, tmp_path):
        p = tmp_path / "denoised_ghost_0000.h5"
        _write_denoised_h5(p, np.full(100_000, -1, dtype=np.int8))
        ctx = _ctx(
            denoised_filename_fn=lambda fi: str(tmp_path / f"denoised_ghost_{fi:04d}.h5"),
        )
        result = AmplitudeCollapseCheck().run(ctx)
        assert result.passed is False
        assert _per_file(result)[0]["file_index"] == 0

    def test_uses_min_key_from_denoised_paths(self, tmp_path):
        """AMB-4-5 → A: min key wins."""
        p7 = tmp_path / "seven.h5"
        p3 = tmp_path / "three.h5"
        _write_denoised_h5(p7, np.arange(-25, 25, dtype=np.int8).repeat(2000))  # diverse
        _write_denoised_h5(p3, np.full(100_000, -1, dtype=np.int8))  # collapsed
        ctx = _ctx(denoised_paths={7: str(p7), 3: str(p3)})
        result = AmplitudeCollapseCheck().run(ctx)
        # min key is 3 → picks the collapsed file → flagged
        assert result.passed is False
        assert _per_file(result)[0]["file_index"] == 3


# ---------------------------------------------------------------------------
# Not applicable — the ONE passed=True + reason case
# ---------------------------------------------------------------------------


class TestNotApplicable:
    def test_no_path_configured_returns_passed_with_reason(self):
        ctx = _ctx()  # no paths, no callable
        result = AmplitudeCollapseCheck().run(ctx)
        assert result.passed is True
        assert "not applicable" in result.reason.lower()
        assert "no path configured" in result.reason.lower()


# ---------------------------------------------------------------------------
# Peek errors → passed=False with path
# ---------------------------------------------------------------------------


class TestPeekError:
    def test_missing_file_returns_failed_with_path(self, tmp_path):
        """OSError → passed=False; per_file[0].io_error carries the class name
        and the path via the exception message."""
        bogus = str(tmp_path / "does_not_exist.h5")
        ctx = _ctx(denoised_paths={0: bogus})
        result = AmplitudeCollapseCheck().run(ctx)
        assert result.passed is False
        assert bogus in result.reason
        per_file = _per_file(result)
        assert per_file[0]["io_error"] is not None
        assert bogus in per_file[0]["io_error"]
        assert per_file[0]["io_error"].startswith("OSError") or per_file[0]["io_error"].startswith(
            "FileNotFoundError"
        )

    def test_missing_dataset_returns_failed_with_path(self, tmp_path):
        p = tmp_path / "wrong_shape.h5"
        with h5py.File(str(p), "w") as f:
            f.create_group("wrong_group")
        ctx = _ctx(denoised_paths={0: str(p)})
        result = AmplitudeCollapseCheck().run(ctx)
        assert result.passed is False
        assert "KeyError" in result.reason
        per_file = _per_file(result)
        assert per_file[0]["io_error"] is not None
        assert per_file[0]["io_error"].startswith("KeyError")


# ---------------------------------------------------------------------------
# Config defaults (rev-6 Protocol §6)
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    def test_config_none_uses_default_threshold(self, tmp_path):
        p = tmp_path / "denoised.h5"
        _write_denoised_h5(p, np.full(100_000, -1, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        result = AmplitudeCollapseCheck().run(ctx)  # config omitted → None
        assert result.passed is False
        assert result.metrics["threshold"] == 0.95  # _DEFAULT_COLLAPSE_THRESHOLD

    def test_config_empty_dict_uses_default_threshold(self, tmp_path):
        p = tmp_path / "denoised.h5"
        _write_denoised_h5(p, np.full(100_000, -1, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        result = AmplitudeCollapseCheck().run(ctx, {})
        assert result.passed is False
        assert result.metrics["threshold"] == 0.95


# ---------------------------------------------------------------------------
# Custom threshold
# ---------------------------------------------------------------------------


class TestCustomThreshold:
    def test_stricter_threshold_flags_lower_dominance(self, tmp_path):
        """Threshold=0.5 flags at 60% dominance; threshold=0.95 does not.

        Variety range ``arange(1, 41)`` — same reason as
        ``test_96_percent_dominance_is_flagged``: no zeros in the tile so
        the dominant-fraction arithmetic is exact.
        """
        p = tmp_path / "denoised.h5"
        # 60,000 zeros + 40,000 non-zero variety → dominant_fraction = 0.60 exactly.
        arr = np.concatenate(
            [
                np.zeros(60_000, dtype=np.int8),
                np.tile(np.arange(1, 41, dtype=np.int8), 1_000),  # 40 * 1000 = 40000
            ]
        )
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        # threshold=0.5 (strict) → 0.60 > 0.5 → flagged
        strict = AmplitudeCollapseCheck().run(ctx, {"collapse_threshold": 0.5})
        assert strict.passed is False
        assert _per_file(strict)[0]["metric_value"] == 0.6
        # threshold=0.95 → 0.60 < 0.95 → not flagged
        loose = AmplitudeCollapseCheck().run(ctx, {"collapse_threshold": 0.95})
        assert loose.passed is True
