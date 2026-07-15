"""OutputDiversityCheck (rev-6) — catches class-127 collapse via unique int8 count.

Rev-6 Protocol: no ``is_applicable``, ``run(ctx, config=None) -> HealthCheckResult``,
``passed=True`` means healthy. See ``docs/design/pluggable_health_checks.md``
§6 (Protocol) and §9.1 (this check's spec).

Failure-mode taxonomy (per operator correction on 4a):
    * ``get_denoised_path`` returns None → the ONLY legitimate "not
      applicable" case → ``passed=True`` with "no path configured" reason.
    * OSError or KeyError during HDF5 open/walk → caller misconfiguration
      or unexpected file format → ``passed=False`` with the attempted path
      baked into the reason. Not a silent-pass case.

Path contract (AMB-4-3 → A): ``denoised_paths`` / ``denoised_filename_fn``
values are used verbatim. Tests pass absolute paths via ``str(tmp_path / ...)``.
"""

from __future__ import annotations

import h5py
import numpy as np

from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.schemas import HealthCheckContext


def _write_denoised_h5(path, ch1: np.ndarray) -> None:
    """Write a minimal denoised HDF5 with ``channel0001/timeseries`` populated."""
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=ch1, chunks=True)


def _ctx(**overrides) -> HealthCheckContext:
    """Minimal-valid HealthCheckContext with the three required identity fields."""
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


# ---------------------------------------------------------------------------
# Constant / near-constant output → passed=False
# ---------------------------------------------------------------------------


class TestConstantOutputDetection:
    def test_constant_neg1_is_flagged(self, tmp_path):
        """The v16 canonical case: constant int8=-1 (class 127)."""
        p = tmp_path / "denoised.h5"
        _write_denoised_h5(p, np.full(200_000, -1, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        result = OutputDiversityCheck().run(
            ctx, {"min_unique_int8_values": 5, "peek_samples": 100_000}
        )
        assert result.passed is False
        assert result.check_name == "output_diversity"
        assert "output_diversity" in result.reason
        assert "5.5762667" in result.reason  # collapse-artifact score in reason
        assert result.metrics["unique_count"] == 1

    def test_two_alternating_values_is_flagged(self, tmp_path):
        """Just above trivial constant — still collapsed."""
        p = tmp_path / "denoised.h5"
        arr = np.tile(np.array([-1, 0], dtype=np.int8), 50_000)
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        result = OutputDiversityCheck().run(
            ctx, {"min_unique_int8_values": 5, "peek_samples": 100_000}
        )
        assert result.passed is False
        assert result.metrics["unique_count"] == 2


# ---------------------------------------------------------------------------
# Healthy output → passed=True
# ---------------------------------------------------------------------------


class TestHealthyOutput:
    def test_50_unique_values_not_flagged(self, tmp_path):
        p = tmp_path / "denoised.h5"
        rng = np.random.default_rng(42)
        arr = rng.integers(-25, 25, size=100_000, dtype=np.int8)
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        result = OutputDiversityCheck().run(
            ctx, {"min_unique_int8_values": 5, "peek_samples": 100_000}
        )
        assert result.passed is True
        assert result.reason == ""
        assert result.metrics["unique_count"] > 5


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


class TestCallablePath:
    def test_uses_denoised_filename_fn_with_default_file_index_zero(self, tmp_path):
        """AMB-4-5 → A: default file_index=0 when denoised_paths is empty."""
        p = tmp_path / "denoised_ghost_0000.h5"
        _write_denoised_h5(p, np.full(100_000, -1, dtype=np.int8))
        ctx = _ctx(
            denoised_filename_fn=lambda fi: str(tmp_path / f"denoised_ghost_{fi:04d}.h5"),
        )
        result = OutputDiversityCheck().run(
            ctx, {"min_unique_int8_values": 5, "peek_samples": 100_000}
        )
        assert result.passed is False
        assert result.metrics["file_index"] == 0

    def test_uses_min_key_from_denoised_paths(self, tmp_path):
        """AMB-4-5 → A: min key from denoised_paths wins over higher indices."""
        p7 = tmp_path / "seven.h5"
        p3 = tmp_path / "three.h5"
        _write_denoised_h5(p7, np.arange(-25, 25, dtype=np.int8).repeat(2000))
        _write_denoised_h5(p3, np.full(100_000, -1, dtype=np.int8))
        ctx = _ctx(denoised_paths={7: str(p7), 3: str(p3)})
        result = OutputDiversityCheck().run(ctx, {"min_unique_int8_values": 5})
        # min key is 3 → picks p3 (collapsed) → flagged
        assert result.passed is False
        assert result.metrics["file_index"] == 3


# ---------------------------------------------------------------------------
# Not-applicable — the ONE case that returns passed=True with a reason
# ---------------------------------------------------------------------------


class TestNotApplicable:
    def test_no_path_configured_returns_passed_with_reason(self):
        """Context has neither denoised_paths nor denoised_filename_fn →
        the only legitimate ``passed=True`` + reason case per §6."""
        ctx = _ctx()  # no paths, no callable
        result = OutputDiversityCheck().run(ctx)
        assert result.passed is True
        assert "not applicable" in result.reason.lower()
        assert "no path configured" in result.reason.lower()


# ---------------------------------------------------------------------------
# Peek errors — passed=False with path in reason (not silent-pass)
# ---------------------------------------------------------------------------


class TestPeekError:
    def test_missing_file_returns_failed_with_path(self, tmp_path):
        """OSError → passed=False, path in reason, peek_error in metrics."""
        bogus = str(tmp_path / "does_not_exist.h5")
        ctx = _ctx(denoised_paths={0: bogus})
        result = OutputDiversityCheck().run(ctx)
        assert result.passed is False
        assert bogus in result.reason
        assert result.metrics["attempted_path"] == bogus
        err_name = result.metrics["peek_error"]
        assert isinstance(err_name, str) and err_name
        assert err_name in result.reason  # exact class name appears in reason

    def test_missing_dataset_returns_failed_with_path(self, tmp_path):
        """KeyError → passed=False, path in reason, peek_error='KeyError'."""
        p = tmp_path / "wrong_shape.h5"
        with h5py.File(str(p), "w") as f:
            f.create_group("wrong_group")  # no timeseries/channel0001
        ctx = _ctx(denoised_paths={0: str(p)})
        result = OutputDiversityCheck().run(ctx)
        assert result.passed is False
        assert str(p) in result.reason
        assert result.metrics["peek_error"] == "KeyError"
        assert result.metrics["attempted_path"] == str(p)
        assert "KeyError" in result.reason


# ---------------------------------------------------------------------------
# Config defaults (rev-6 Protocol §6: config=None or empty dict → defaults)
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    def test_config_none_uses_defaults(self, tmp_path):
        """config=None → skill's class-level _DEFAULT_MIN_UNIQUE / _DEFAULT_PEEK_SAMPLES."""
        p = tmp_path / "denoised.h5"
        _write_denoised_h5(p, np.full(200_000, -1, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        result = OutputDiversityCheck().run(ctx)  # config omitted → None
        assert result.passed is False
        assert result.metrics["threshold"] == 5  # default min_unique_int8_values

    def test_config_empty_dict_uses_defaults(self, tmp_path):
        """Partial-overlay semantic (§6): empty dict is equivalent to defaults."""
        p = tmp_path / "denoised.h5"
        _write_denoised_h5(p, np.full(200_000, -1, dtype=np.int8))
        ctx = _ctx(denoised_paths={0: str(p)})
        result = OutputDiversityCheck().run(ctx, {})
        assert result.passed is False
        assert result.metrics["threshold"] == 5


# ---------------------------------------------------------------------------
# Config-driven threshold behavior
# ---------------------------------------------------------------------------


class TestConfigThresholds:
    def test_min_unique_int8_values_honored(self, tmp_path):
        """7-unique data: threshold=5 → passes, threshold=10 → fails."""
        p = tmp_path / "denoised.h5"
        arr = np.tile(np.array([-3, -2, -1, 0, 1, 2, 3], dtype=np.int8), 15_000)
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        pass_res = OutputDiversityCheck().run(ctx, {"min_unique_int8_values": 5})
        fail_res = OutputDiversityCheck().run(ctx, {"min_unique_int8_values": 10})
        assert pass_res.passed is True
        assert fail_res.passed is False

    def test_peek_samples_honored(self, tmp_path):
        """peek_samples=40 only sees the constant prefix; larger peek sees tail."""
        p = tmp_path / "denoised.h5"
        arr = np.concatenate(
            [
                np.full(50, -1, dtype=np.int8),
                np.arange(-50, 50, dtype=np.int8).repeat(100),
            ]
        )
        _write_denoised_h5(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        small = OutputDiversityCheck().run(ctx, {"min_unique_int8_values": 5, "peek_samples": 40})
        assert small.passed is False
        assert small.metrics["unique_count"] == 1
        big = OutputDiversityCheck().run(ctx, {"min_unique_int8_values": 5, "peek_samples": 10_000})
        assert big.passed is True
