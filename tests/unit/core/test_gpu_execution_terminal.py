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
    started = time.monotonic()

    def samples(*args):
        if time.monotonic() - started < 0.07:
            return snapshot()
        if fault == "breach":
            return snapshot(used=1500)
        return GpuAccountingSnapshot(device=DEVICE, telemetry_available=False)

    @native.record_protected_phase("training")
    def execute(sandbox, exp_id, run_name, model_type):
        obs = observer(sampler=samples)
        state.current_observer = obs
        native.run_native_subprocess(
            sandbox,
            None,
            [
                sys.executable,
                "-c",
                "import time;print('started candidate',flush=True);time.sleep(10)",
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
