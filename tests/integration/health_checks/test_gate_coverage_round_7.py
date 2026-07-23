"""Validation Gate G1 reproduction: agent_012 phantom-shape at round 7.

Before M8, round 7 had NO gate configured in configs/health_checks.yaml
(gates existed only at rounds 1, 3, 5, 10) — so agent_012's near-constant
output (unique_int8=2, values {-68, -65}, ~99.99% at -65) was scored as
``status=success`` with ``denoising_score=1.05`` and reported as
``healthgate_result=passed`` by build_diagnostic_summary.

Under M8's every-round coverage this must invalidate. This integration
test builds a synthetic HDF5 with the exact agent_012 fingerprint and
runs the framework end-to-end (real YAML + real registry + real
evaluate_gate + real resolve_action) at round_index=7.
"""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from execute_tools.health_checks import (
    HealthCheckContext,
    evaluate_gate,
    get_gates_for_position,
    resolve_action,
)
from execute_tools.health_checks.config import clear_health_gates_config_cache


def _write_agent_012_fingerprint(path, n_samples: int = 100_000) -> None:
    """Mostly -65 with a small fraction at -68 — mirrors agent_012 exactly."""
    arr = np.full(n_samples, -65, dtype=np.int8)
    # 0.007% perturbation, matching /home/klz/Data/.../agent_012_00XX.h5 fingerprint
    arr[:7] = -68
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=arr, chunks=True)
        c2 = ts.create_group("channel0002")
        c2.create_dataset("timeseries", data=np.zeros(n_samples, np.int8), chunks=True)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure the process-wide YAML cache is fresh."""
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


class TestGateCoverageRound7:
    """Round 7 must be gated under M8; agent_012's fingerprint must invalidate."""

    def test_at_least_one_gate_fires_at_round_7(self):
        """Regression guard against the pre-M8 config gap."""
        ids = get_gates_for_position(7)
        assert ids, (
            "round 7 has no gate configured — this was the exact "
            "misconfiguration that allowed agent_012's phantom to pass"
        )
        # Under the M8 YAML, all 6 gates fire at every round.
        assert "output_diversity_blocking" in ids
        assert "output_std_blocking" in ids
        assert "amplitude_collapse_blocking" in ids

    def test_agent_012_fingerprint_invalidates_round_at_7(self, tmp_path):
        """End-to-end: real YAML + registry, agent_012 output → invalidate_round."""
        # Build denoised HDF5 for a single file with the agent_012 pattern.
        # (Denoised paths are used verbatim by output_diversity /
        # output_std / amplitude_collapse — they peek only the first file.)
        d0 = tmp_path / "d0.h5"
        _write_agent_012_fingerprint(d0)

        ctx = HealthCheckContext(
            model_name="wavenet",
            run_name="round_7_reproducer",
            round_index=7,
            denoised_paths={12: str(d0)},  # matches agent_012's files 12-19 set
            file_vector=[None] * 12 + [5.9, 3.7, 6.0, 7.5, 7.0, 10.0, 1.6, 0.5],
            denoising_score=1.05,
        )

        # Run every gate the real YAML registers for round 7.
        gate_ids = get_gates_for_position(7)
        results = [evaluate_gate(gid, ctx) for gid in gate_ids]

        # At least one blocking gate must have flagged the collapse.
        blocking_failed = [
            r for r in results if not r.passed and r.action.value == "invalidate_round"
        ]
        assert blocking_failed, (
            "no blocking gate fired on the agent_012 fingerprint — the "
            "coverage fix is not working; failing results were: "
            + repr([(r.gate_id, r.passed, r.action.value, r.failure_reason) for r in results])
        )

        # The resolved action must be invalidate_round (or stricter).
        action = resolve_action(results)
        assert action.value == "invalidate_round", f"expected invalidate_round; got {action.value}"

        # output_diversity_blocking specifically must have failed with a
        # reason mentioning unique_int8. Verbatim substring assertion:
        div_results = [r for r in results if r.gate_id == "output_diversity_blocking"]
        assert len(div_results) == 1
        assert div_results[0].passed is False
        # M9: reason format changed from single-file "N unique int8 values"
        # to multi-file "aggregation=... failed — per-file: file_N=metric".
        # Substring-check both the check name and the threshold token to
        # confirm this is the diversity check failing on unique_int8.
        assert "output_diversity" in div_results[0].failure_reason
        assert "unique_int8" in div_results[0].failure_reason

    def test_healthy_output_at_round_7_still_passes(self, tmp_path):
        """Regression guard: the tight coverage must not false-positive on
        a FCNet-scale output (~7.35 mV std, many unique values)."""
        rng = np.random.default_rng(0)
        wide = rng.integers(-24, 25, size=100_000, dtype=np.int8)
        d0 = tmp_path / "healthy.h5"
        with h5py.File(str(d0), "w") as f:
            ts = f.create_group("timeseries")
            c1 = ts.create_group("channel0001")
            c1.create_dataset("timeseries", data=wide, chunks=True)

        ctx = HealthCheckContext(
            model_name="wavenet",
            run_name="round_7_healthy",
            round_index=7,
            # The healthy file must be present at the indices the blocking
            # gates actually peek (configs/health_checks.yaml
            # peek_file_indices: [3, 10, 17]) — unresolved peeks fail
            # closed by design, so a fixture that misses the configured
            # peek coverage can never pass regardless of output quality.
            denoised_paths={3: str(d0), 10: str(d0), 17: str(d0)},
            file_vector=[None] * 12 + [5.9, 3.7, 6.0, 7.5, 7.0, 10.0, 1.6, 0.5],
            denoising_score=1.05,
        )

        gate_ids = get_gates_for_position(7)
        results = [evaluate_gate(gid, ctx) for gid in gate_ids]

        # No blocking gate should have flagged this output.
        blocking_failed = [
            r for r in results if not r.passed and r.action.value == "invalidate_round"
        ]
        assert not blocking_failed, "healthy FCNet-scale output false-positive: " + repr(
            [(r.gate_id, r.failure_reason) for r in blocking_failed]
        )

        # Resolved action stays CONTINUE.
        action = resolve_action(results)
        assert action.value == "continue"
