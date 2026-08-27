"""C2 flip witness — blocking per-file aggregation ``any_pass`` → ``all_pass``.

Operator-frozen decision, 2026-08-26. It repairs the leniency the shipped
TIDMAD config itself documented and deferred ("all_pass would arguably be
stricter; deferred to post-V17 empirical validation", m9 execution plan §9
Q1): under ``any_pass`` a model that collapses on two of the three peeked
files while clearing the bar on one still PASSES every blocking gate.

Defects only this file catches:

* **The flip silently reverting** — ``configs/health_checks.yaml`` (or the
  observe-mode sibling, or the built-in fallback table) carrying
  ``any_pass`` again. The composition tests pin the policy MECHANISM; only
  these tests pin the frozen VALUE on the production path, per gate.
* **The two aggregation directions swapping or converging** — proven on ONE
  shared per-file fixture, both directions, through the real consumer
  (``_multi_file_peek._apply_aggregation`` via ``peek_and_aggregate``). A
  test with separate fixtures per mode cannot show the SAME evidence
  flipping the verdict.

How each test fails when the behaviour breaks: revert the YAML flip and
``test_shipped_policy_composes_all_pass_into_every_blocking_gate`` reports
the offending gate id; make ``all_pass`` tolerate one degraded file and
``test_one_passing_file_among_failures_splits_the_two_modes`` fails its
``passed is False`` arm.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest
import yaml

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks._composition import DEFAULT_DISPOSITION_POLICY
from execute_tools.health_checks._multi_file_peek import peek_and_aggregate
from execute_tools.health_checks.config import (
    clear_health_gates_config_cache,
    materialize_effective_config,
)
from execute_tools.health_checks.schemas import HealthCheckContext

REPO_ROOT = Path(__file__).resolve().parents[4]

#: The three blocking gates the shipped TIDMAD roster declares. Hardcoded —
#: the witness must prove the flip reaches ALL of them, so the expectation
#: can never be read back from the thing under test.
BLOCKING_GATE_IDS = [
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
]

RECORDING_GATE_IDS = [
    "pearson_dispersion_recording",
    "spectral_peak_ratio_recording",
    "per_file_output_std_recording",
]


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    """Composing BINDS run-scoped plugin/fact state; isolate it per test."""
    clear_health_gates_config_cache()
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        clear_health_gates_config_cache()
        _plugin_binding.reset_run_scope()


def _write_ch1(path: Path, ch1: np.ndarray) -> None:
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=ch1, chunks=True)


def _composed_gates(tmp_path: Path, source: str | None) -> list[dict]:
    path, _ = materialize_effective_config(source, None, str(tmp_path))
    return yaml.safe_load(Path(path).read_text())["health_gates"]


class TestOneFixtureBothDirections:
    """The frozen C2 witness: same per-file evidence, opposite verdicts."""

    def test_one_passing_file_among_failures_splits_the_two_modes(self, tmp_path):
        """File 3 healthy, files 10 and 17 collapsed — the production peek
        triplet with exactly one clearing file. ``any_pass`` calls that a
        gate PASS; ``all_pass`` calls it a gate FAIL, on identical per-file
        results."""
        healthy = tmp_path / "d3.h5"
        collapsed_a = tmp_path / "d10.h5"
        collapsed_b = tmp_path / "d17.h5"
        _write_ch1(healthy, np.tile(np.arange(-60, 60, dtype=np.int8), 100))
        _write_ch1(collapsed_a, np.full(10_000, -65, dtype=np.int8))
        _write_ch1(collapsed_b, np.full(10_000, 127, dtype=np.int8))
        ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_paths={3: str(healthy), 10: str(collapsed_a), 17: str(collapsed_b)},
        )

        def run(aggregation: str):
            return peek_and_aggregate(
                ctx,
                peek_file_indices=[3, 10, 17],
                metric_fn=lambda arr: int(np.unique(arr).size),
                # The production output_diversity threshold value (25).
                predicate=lambda m: m > 25,
                aggregation=aggregation,
                peek_samples=10_000,
            )

        under_any = run("any_pass")
        under_all = run("all_pass")

        # SAME underlying per-file results — one file passed, two failed.
        assert [r.model_dump() for r in under_any.per_file] == [
            r.model_dump() for r in under_all.per_file
        ]
        assert [r.passed for r in under_any.per_file] == [True, False, False]

        # …and OPPOSITE gate verdicts. Both directions from one fixture.
        assert under_any.passed is True
        assert under_all.passed is False
        assert "all_pass" in under_all.reason


class TestFlipReachesEveryBlockingGate:
    """The policy value, asserted per gate on the real composed artifact."""

    def test_shipped_policy_composes_all_pass_into_every_blocking_gate(self, tmp_path):
        gates = _composed_gates(tmp_path, None)
        blocking = [g for g in gates if g["gate_role"] == "blocking"]

        assert [g["id"] for g in blocking] == BLOCKING_GATE_IDS
        for gate in blocking:
            assert gate["checks"][0]["config"]["aggregation"] == "all_pass", gate["id"]

        recording = [g for g in gates if g["gate_role"] == "observational"]
        assert [g["id"] for g in recording] == RECORDING_GATE_IDS
        for gate in recording:
            assert "aggregation" not in gate["checks"][0]["config"], gate["id"]

    def test_observe_mode_policy_composes_all_pass_too(self, tmp_path):
        """Observe mode differs from production in ``on_fail`` ONLY — the
        aggregation flip must land in both, or a baseline-characterization
        run measures different collapse semantics than production enforces."""
        gates = _composed_gates(
            tmp_path, str(REPO_ROOT / "configs" / "health_checks_baseline_observe_mode.yaml")
        )
        blocking = [g for g in gates if g["gate_role"] == "blocking"]

        assert [g["id"] for g in blocking] == BLOCKING_GATE_IDS
        for gate in blocking:
            assert gate["checks"][0]["config"]["aggregation"] == "all_pass", gate["id"]
            assert gate["on_fail"]["action"] == "continue", gate["id"]

    def test_builtin_default_policy_matches_the_shipped_policy(self):
        """The fallback table's contract is "the shipped policy when the
        framework file declares none". A flip applied to the YAML but not
        the table (or vice versa) would give a policy-less framework config
        silently different blocking semantics — nothing else compares the
        two authorities."""
        shipped = yaml.safe_load((REPO_ROOT / "configs" / "health_checks.yaml").read_text())[
            "health_policy"
        ]
        for disposition, policy in DEFAULT_DISPOSITION_POLICY.items():
            declared = shipped[disposition]
            assert policy.check_config == declared["check_config"], disposition
            assert policy.short_circuit == declared["short_circuit"], disposition
            assert policy.gate_role == declared["gate_role"], disposition
            assert policy.on_pass.value == declared["on_pass"], disposition
            assert policy.on_fail.value == declared["on_fail"], disposition

        assert DEFAULT_DISPOSITION_POLICY["blocking"].check_config == {"aggregation": "all_pass"}
