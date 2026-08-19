"""OutputStdCheck tests (M8 §3.3 + M9 §5.3).

Blocking check: fails when std of denoised output falls below min_std_mv.
Empirical: FCNet 7.35 mV vs collapse < 0.2 mV; default threshold 1.0 mV.

M9: per-file std travels via metrics['per_file_json']; the top-level
scalar metrics are only aggregate/routing (aggregated_passed,
n_files_attempted, n_files_io_failed) plus the check-specific
threshold_mv for observability.
"""

from __future__ import annotations

import json

import h5py
import numpy as np

from execute_tools.health_checks._composition import (
    VALUE_SCALE_PARAMETER,
    VALUE_SCALE_UNIT_PARAMETER,
)
from execute_tools.health_checks.output_std import OutputStdCheck
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


def _per_file(result) -> list[dict]:
    return json.loads(result.metrics["per_file_json"])


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


class TestOutputStdCheck:
    def test_fcnet_like_input_passes(self, tmp_path):
        """int8 with wide range (~ +/-24 → std_mv ~ 7.3) passes 1.0 mV floor."""
        p = tmp_path / "d.h5"
        rng = np.random.default_rng(0)
        wide = rng.integers(-24, 25, size=100_000, dtype=np.int8)
        _write_ch1(p, wide)
        ctx = _ctx(denoised_paths={0: str(p)})
        r = OutputStdCheck().run(ctx, config=_cfg())
        assert r.passed is True
        assert _per_file(r)[0]["metric_value"] > 1.0
        assert r.metrics["threshold_mv"] == 1.0

    def test_collapse_like_input_fails(self, tmp_path):
        """Constant + 0.007% perturbation ~ std_mv ~ 0.008 mV; fails 1.0 mV."""
        p = tmp_path / "d.h5"
        arr = np.full(100_000, -65, dtype=np.int8)
        arr[:7] = -68  # 0.007% perturbation, matches agent_012 pattern
        _write_ch1(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        r = OutputStdCheck().run(ctx, config=_cfg())
        assert r.passed is False
        assert _per_file(r)[0]["metric_value"] < 1.0
        # M9: reason no longer contains "output_std_mv" literal; it contains
        # the check-name + threshold declaration.
        assert "output_std" in r.reason
        assert "threshold" in r.reason

    def test_below_threshold_fails(self, tmp_path):
        """Small-std input measured under a permissive threshold, then
        re-run under a threshold above the measured value → must fail."""
        p = tmp_path / "d.h5"
        rng = np.random.default_rng(1)
        arr = rng.integers(-1, 2, size=100_000, dtype=np.int8)
        _write_ch1(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        # First measure without threshold to know the value
        r0 = OutputStdCheck().run(ctx, config=_cfg(**{"min_std_mv": 0.0001}))
        measured = _per_file(r0)[0]["metric_value"]
        # Set threshold above measured → must fail (predicate: m >= threshold)
        r = OutputStdCheck().run(ctx, config=_cfg(**{"min_std_mv": measured * 2}))
        assert r.passed is False

    def test_missing_path_passes_not_applicable(self):
        """No path → passed=True with 'not applicable' reason."""
        ctx = _ctx()
        r = OutputStdCheck().run(ctx, config=_cfg())
        assert r.passed is True
        assert "not applicable" in r.reason

    def test_missing_file_surfaces_io_error(self, tmp_path):
        """OSError → passed=False; per_file[0].io_error carries the class name
        and path via the exception message."""
        bogus = tmp_path / "does_not_exist.h5"
        ctx = _ctx(denoised_paths={0: str(bogus)})
        r = OutputStdCheck().run(ctx, config=_cfg())
        assert r.passed is False
        per_file = _per_file(r)
        assert per_file[0]["io_error"] is not None
        assert str(bogus) in per_file[0]["io_error"]
        assert per_file[0]["io_error"].startswith("OSError") or per_file[0]["io_error"].startswith(
            "FileNotFoundError"
        )

    def test_custom_threshold_via_config(self, tmp_path):
        """Config override for min_std_mv."""
        p = tmp_path / "d.h5"
        rng = np.random.default_rng(2)
        arr = rng.integers(-24, 25, size=100_000, dtype=np.int8)
        _write_ch1(p, arr)
        ctx = _ctx(denoised_paths={0: str(p)})
        # Config threshold 100 mV — must fail
        r = OutputStdCheck().run(ctx, config=_cfg(**{"min_std_mv": 100.0}))
        assert r.passed is False
        assert r.metrics["threshold_mv"] == 100.0
