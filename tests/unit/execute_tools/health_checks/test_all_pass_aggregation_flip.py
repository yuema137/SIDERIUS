"""Per-file aggregation mechanics and task-declared override coverage.

Defects only this file catches:

* **The two aggregation directions swapping or converging** — proven on ONE
  shared per-file fixture, both directions, through the real consumer
  (``_multi_file_peek._apply_aggregation`` via ``peek_and_aggregate``). A
  test with separate fixtures per mode cannot show the SAME evidence
  flipping the verdict.
* **A task override being overwritten by framework policy** — the declared
  per-gate value must survive into the effective run artifact.

How each test fails when the behaviour breaks: revert the YAML flip and
``test_shipped_policy_composes_all_pass_into_every_blocking_gate`` reports
the offending gate id; make ``all_pass`` tolerate one degraded file and
``test_one_passing_file_among_failures_splits_the_two_modes`` fails its
``passed is False`` arm; restore the unconditional
``check_config.update(policy.check_config)`` in ``compose_gate`` and
``test_one_gate_declares_a_different_aggregation_than_its_siblings``
reports the declared value replaced by the framework's.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest
import yaml

from execute_tools.dataset_config import resolve_dataset_profile, tidmad_topology
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks._multi_file_peek import peek_and_aggregate
from execute_tools.health_checks.config import (
    clear_health_gates_config_cache,
    materialize_effective_config,
)
from execute_tools.health_checks.schemas import HealthCheckContext


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
    output_channel = tidmad_topology(resolve_dataset_profile()).channels.input_channel
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group(output_channel)
        c1.create_dataset("timeseries", data=ch1, chunks=True)


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
            output_channel = tidmad_topology(resolve_dataset_profile()).channels.input_channel
            return peek_and_aggregate(
                ctx,
                peek_file_indices=[3, 10, 17],
                metric_fn=lambda arr: int(np.unique(arr).size),
                # The production output_diversity threshold value (25).
                predicate=lambda m: m > 25,
                aggregation=aggregation,
                peek_samples=10_000,
                channel=output_channel,
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


class TestATaskDeclaresItsOwnAggregation:
    """F-SCAND-2 — the strictness of a gate is task science, per gate.

    The row's stated parameter is that blocking-gate aggregation is "not
    task-declarable at all", and its ``worse_than_recorded`` clause names
    the concrete harm: one framework value governs every blocking gate of
    every task, so ``amplitude_collapse_blocking`` cannot be made strict
    without making all three strict. These tests drive the SAME production
    materialization the tests above use — ``materialize_effective_config``,
    the function that writes the run's pinned
    ``health_checks_effective.yaml`` — never ``compose_gate`` in isolation,
    because a witness that stops at the helper cannot show the value
    surviving the artifact the run actually reads.
    """

    def _task_health(self, tmp_path: Path, amplitude_aggregation: str | None) -> str:
        """Three blocking gates; only the amplitude gate may declare a mode.

        Deliberately the row's own example. The other two entries declare
        nothing, so one file exercises both halves of the contract at once.
        """
        amplitude: dict[str, object] = {"collapse_threshold": 0.95, "peek_samples": 1000}
        if amplitude_aggregation is not None:
            amplitude["aggregation"] = amplitude_aggregation
        document = {
            "facts": {"encoding_family": "int8_symbol_stream", "symbol_cardinality": 256},
            "value_scale": {"unit": "mV", "units_per_sample": 0.3125},
            "health_peek_files": [3, 10, 17],
            "roster": [
                {
                    "gate_id": "output_diversity_blocking",
                    "check": "output_diversity",
                    "disposition": "blocking",
                    "parameters": {"min_unique_int8_values": 25, "peek_samples": 1000},
                    "uses_health_peek_files": True,
                },
                {
                    "gate_id": "output_std_blocking",
                    "check": "output_std",
                    "disposition": "blocking",
                    "parameters": {"min_std_mv": 1.0, "peek_samples": 1000},
                    "uses_health_peek_files": True,
                },
                {
                    "gate_id": "amplitude_collapse_blocking",
                    "check": "amplitude_collapse",
                    "disposition": "blocking",
                    "parameters": amplitude,
                    "uses_health_peek_files": True,
                },
            ],
        }
        path = tmp_path / "task_health.yaml"
        path.write_text(yaml.safe_dump(document, sort_keys=True))
        return str(path)

    def _aggregations(self, tmp_path: Path, binding: str) -> dict[str, str]:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        effective, _ = materialize_effective_config(None, None, str(workspace), None, binding)
        gates = yaml.safe_load(Path(effective).read_text())["health_gates"]
        return {g["id"]: g["checks"][0]["config"]["aggregation"] for g in gates}

    def test_one_gate_declares_a_different_aggregation_than_its_siblings(self, tmp_path):
        """The capability the row asks for, stated as the row states it.

        ``amplitude_collapse_blocking`` declares ``any_pass`` while the two
        silent siblings keep the framework's ``all_pass``. Restore the
        unconditional ``check_config.update(policy.check_config)`` in
        ``compose_gate`` and the amplitude entry reads ``all_pass`` here —
        the framework value having overwritten the task's declaration.
        """
        binding = self._task_health(tmp_path, "any_pass")

        assert self._aggregations(tmp_path, binding) == {
            "output_diversity_blocking": "all_pass",
            "output_std_blocking": "all_pass",
            "amplitude_collapse_blocking": "any_pass",
        }

    def test_the_same_roster_declaring_nothing_gets_the_framework_value(self, tmp_path):
        """The other half: the override is an override, not a new default.

        Identical roster, the one declaration removed. Every gate resolves
        to the frozen ``all_pass``. Without this, a bug that dropped the
        framework injection entirely would still pass the test above.
        """
        binding = self._task_health(tmp_path, None)

        assert self._aggregations(tmp_path, binding) == {
            "output_diversity_blocking": "all_pass",
            "output_std_blocking": "all_pass",
            "amplitude_collapse_blocking": "all_pass",
        }

    def test_a_declared_mode_reaches_every_disposition_not_just_blocking(self, tmp_path):
        """Declarability is a property of the key, not of the gate role.

        A recording gate gets no ``aggregation`` from framework policy at
        all (asserted above), so this is the case where the task's value is
        the ONLY source. A ``compose_gate`` that honoured declarations by
        special-casing the blocking policy dict would pass every other test
        here and fail this one.
        """
        document = {
            "roster": [
                {
                    "gate_id": "per_file_output_std_recording",
                    "check": "per_file_output_std",
                    "disposition": "recording",
                    "parameters": {"peek_samples": 1000, "aggregation": "median"},
                }
            ]
        }
        path = tmp_path / "recording_health.yaml"
        path.write_text(yaml.safe_dump(document, sort_keys=True))

        assert self._aggregations(tmp_path, str(path)) == {
            "per_file_output_std_recording": "median"
        }


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
