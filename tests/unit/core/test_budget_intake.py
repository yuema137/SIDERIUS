"""B3-2 budget intake: one validated budget file, and the lock's scheduling mode.

What only these tests catch:

* ``TestBudgetFile`` — the operator file becomes a ``HostBudget`` exactly once,
  with intake-owned provenance; an ambiguous or self-labelled file refuses
  instead of silently choosing a value.
* ``TestSchedulingModeLock`` — the mode is compared on resume (decision B3-Q7)
  through real lock files, the budget is recorded but not compared, and a
  run without a budget keeps every pre-B3-2 lock byte and resume outcome.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.run_invariants import (
    LockLaunchIdentity,
    RunInvariants,
    RunInvariantsViolation,
    build_run_invariants,
    ensure_run_invariants,
    write_run_invariants,
)
from core.runtime_control.budget_intake import (
    MAX_HOST_BUDGET_FILE_BYTES,
    HostBudgetFileError,
    HostBudgetProvenance,
    load_host_budget_file,
)
from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.scheduling import GpuHardwareClass, GpuSlot, HostBudget

_SLOT = {
    "uuid": "GPU-0a1b2c3d",
    "hardware_class": {
        "device_name": "synthetic-accelerator",
        "total_memory_bytes": 48 * 1024**3,
        "compute_capability": [8, 9],
    },
    "ceiling": {
        "operator_ceiling_gib": 40.0,
        "operator_source": "caller",
        "host_quota_gib": None,
        "measured_capacity_gib": 47.5,
    },
}
_FILE = {"gpus": [_SLOT], "host_memory_gib": 64.0, "cpu_slots": 8, "max_concurrent_units": 2}


def _caller_budget(units: int = 2) -> HostBudget:
    slot = GpuSlot(
        uuid="GPU-0a1b2c3d",
        hardware_class=GpuHardwareClass(
            device_name="synthetic-accelerator",
            total_memory_bytes=48 * 1024**3,
            compute_capability=(8, 9),
        ),
        ceiling=ResolvedGpuCeiling(
            operator_ceiling_gib=40.0,
            operator_source="caller",
            host_quota_gib=None,
            measured_capacity_gib=47.5,
        ),
    )
    return HostBudget(
        gpus=(slot,),
        host_memory_gib=64.0,
        cpu_slots=8,
        max_concurrent_units=units,
        source="caller",
    )


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "budget.json"
    path.write_text(text, encoding="utf-8")
    return path


class TestBudgetFile:
    def test_file_becomes_the_declared_budget_with_file_provenance(self, tmp_path):
        """A dropped or renamed field, or a source left as ``caller``, fails here:
        the digest is compared with an independently constructed budget."""
        budget = load_host_budget_file(_write(tmp_path, json.dumps(_FILE)))
        assert budget.source == "file"
        assert budget.digest == _caller_budget().digest

    def test_a_file_cannot_author_its_own_source(self, tmp_path):
        """Provenance is the intake's fact; a file claiming ``caller`` would let
        the lock attribute a file budget to a programmatic caller."""
        with pytest.raises(HostBudgetFileError, match="declares 'source'"):
            load_host_budget_file(_write(tmp_path, json.dumps({**_FILE, "source": "caller"})))

    def test_duplicate_keys_refuse_instead_of_last_wins(self, tmp_path):
        """``json.loads`` keeps the last duplicate silently; the operator's
        first declaration (here a smaller concurrency limit) would vanish."""
        text = json.dumps(_FILE)[:-1] + ', "max_concurrent_units": 1}'
        with pytest.raises(HostBudgetFileError, match="duplicate JSON keys"):
            load_host_budget_file(_write(tmp_path, text))

    def test_non_regular_or_oversized_input_refuses_before_parsing(self, tmp_path):
        """A directory or a huge file must not reach the parser: the cap bounds
        what one launch flag can make the parent read into memory."""
        with pytest.raises(HostBudgetFileError, match="not a regular file"):
            load_host_budget_file(tmp_path)
        padded = json.dumps(_FILE) + " " * MAX_HOST_BUDGET_FILE_BYTES
        with pytest.raises(HostBudgetFileError, match=f"exceeds {MAX_HOST_BUDGET_FILE_BYTES}"):
            load_host_budget_file(_write(tmp_path, padded))

    def test_an_invalid_budget_names_the_file(self, tmp_path):
        """A launch-time refusal must point the operator at the file to fix."""
        path = _write(tmp_path, json.dumps({k: v for k, v in _FILE.items() if k != "cpu_slots"}))
        with pytest.raises(HostBudgetFileError, match=str(path)):
            load_host_budget_file(path)


def _build(tmp_path: Path, budget: HostBudget | None) -> RunInvariants:
    return build_run_invariants(
        resolved_data_scope=[0],
        health_gate_enabled=False,
        health_gate_files=None,
        health_checks_config=None,
        workspace=str(tmp_path),
        task_composition_fingerprint="a" * 64,
        include_runtime_identities=False,
        launch_identity=LockLaunchIdentity(host_budget=budget),
    )[0]


class TestSchedulingModeLock:
    def test_serial_lock_carries_no_scheduling_keys(self, tmp_path):
        """Every run without a budget must keep its pre-B3-2 lock bytes."""
        path = write_run_invariants(str(tmp_path / "ws"), _build(tmp_path, None))
        raw = json.loads(Path(path).read_text())
        assert "scheduling_mode" not in raw
        assert "host_budget" not in raw

    def test_budget_selects_parallel_mode_and_records_its_digest(self, tmp_path):
        """Fails if the builder drops the carrier's budget: the lock would
        claim serial for a run scheduled in parallel."""
        budget = _caller_budget()
        path = write_run_invariants(str(tmp_path / "ws"), _build(tmp_path, budget))
        raw = json.loads(Path(path).read_text())
        assert raw["scheduling_mode"] == "parallel-v1"
        assert raw["host_budget"] == {
            "digest": budget.digest,
            "max_concurrent_units": 2,
            "source": "caller",
        }

    @pytest.mark.parametrize(
        ("locked", "resumed"),
        [(None, _caller_budget()), (_caller_budget(), None)],
        ids=["serial-workspace-resumed-parallel", "parallel-workspace-resumed-serial"],
    )
    def test_resume_cannot_switch_mode(self, tmp_path, locked, resumed):
        """B3-Q7: drain semantics change failed-body traces, so the mode is
        canonical. The serial row is also every legacy workspace."""
        workspace = str(tmp_path / "ws")
        write_run_invariants(workspace, _build(tmp_path, locked))
        with pytest.raises(RunInvariantsViolation, match="scheduling_mode"):
            ensure_run_invariants(workspace, _build(tmp_path, resumed))

    def test_a_different_budget_resumes(self, tmp_path):
        """The budget is host capacity, like execution calibration: resuming a
        parallel workspace on another budget stays legal."""
        workspace = str(tmp_path / "ws")
        write_run_invariants(workspace, _build(tmp_path, _caller_budget(units=2)))
        assert ensure_run_invariants(workspace, _build(tmp_path, _caller_budget(units=4))) == (
            "validated"
        )

    def test_parallel_mode_requires_its_budget(self):
        """A parallel lock without a budget digest is unattributable."""
        with pytest.raises(ValueError, match="requires host_budget"):
            RunInvariants(
                resolved_data_scope=[0],
                health_gate_enabled=False,
                health_config_sha256=None,
                scheduling_mode="parallel-v1",
            )
        with pytest.raises(ValueError, match="requires host_budget"):
            RunInvariants(
                resolved_data_scope=[0],
                health_gate_enabled=False,
                health_config_sha256=None,
                host_budget=HostBudgetProvenance.of(_caller_budget()),
            )
