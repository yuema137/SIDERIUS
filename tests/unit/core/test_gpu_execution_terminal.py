"""Real protected child stops must reach terminal infrastructure evidence."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.runtime_control import native_gpu_execution as native
from core.runtime_control.gpu_execution_evidence import GpuExecutionReceipt
from core.sandbox_layout import training_checkpoint_path
from tests.helpers.process_bounds import CHILD_PROCESS_BOUND_SECONDS
from tests.unit.core.test_checkpoint_inference_measurement import bound_spec
from tests.unit.core.test_gpu_runtime_protection import observer, snapshot
from tests.unit.core.test_native_gpu_execution import selected_state


@pytest.mark.parametrize("fault", ["breach", "unknown"])
def test_runtime_stop_keeps_raw_child_and_cleans_only_current_attempt(tmp_path, bound_spec, fault):
    from core.runtime_control.gpu_accounting import GpuAccountingSnapshot
    from tests.unit.core.test_gpu_runtime_protection import DEVICE

    state = selected_state(bound_spec, "training")
    sandbox = SimpleNamespace(
        gpu_execution=state,
        base_dir=str(tmp_path),
        dirs={"models": str(tmp_path), "records": str(tmp_path)},
        deliverable_naming=None,
    )
    current = training_checkpoint_path(tmp_path, "synthetic", "exp-a")
    unrelated = training_checkpoint_path(tmp_path, "synthetic", "other")
    current.write_text("partial")
    unrelated.write_text("preserve")
    # The fault appears only after the child has printed, whatever the host load
    # (#1578: a 0.07 s wall-clock switch could stop the child before it printed).
    printed = tmp_path / "printed"

    def samples(*args):
        if not printed.exists():
            return snapshot()
        if fault == "breach":
            return snapshot(used=1500)
        return GpuAccountingSnapshot(device=DEVICE, telemetry_available=False)

    @native.record_protected_phase("training")
    def execute(sandbox, exp_id, run_name, model_type):
        # Logical time: sample ageing has its own witnesses; this test owns the stop.
        anchor = time.monotonic()
        obs = observer(sampler=samples, clock=lambda: anchor)
        state.current_observer = obs
        native.run_native_subprocess(
            sandbox,
            None,
            [
                sys.executable,
                "-c",
                "import pathlib, sys, time; print('started candidate', flush=True); "
                f"pathlib.Path(sys.argv[1]).touch(); time.sleep({CHILD_PROCESS_BOUND_SECONDS:g})",
                str(printed),
            ],
            env=dict(os.environ),
            preexec_fn=None,
            capture_stdout=True,
            observer=obs,
            control=obs,
        )
        pytest.fail("protection stop returned scientific success")

    result = execute(sandbox, "exp-a", "run", "synthetic")
    assert result["status"] == "aborted_infrastructure"
    receipt = GpuExecutionReceipt.model_validate_json(
        (tmp_path / "gpu_execution" / "attempt" / "training-terminal.json").read_bytes()
    )
    assert receipt.outcome == result["status"]
    assert receipt.protection.decision.status == "stop"
    assert (
        receipt.lifecycle.child_reaped and receipt.lifecycle.group_cleanup.final.status == "absent"
    )
    assert "started candidate" in receipt.stdout
    assert not current.exists()
    assert unrelated.read_text() == "preserve"
