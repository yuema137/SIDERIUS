"""``check --gpu``: the in-sandbox CUDA probe's verdicts reach the operator unchanged.

The sandbox itself is replaced by a recorder; the real bubblewrap path is the
operator's host qualification (``check --gpu`` on a GPU machine), not CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.candidate_console import gpu_check
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import ExecutionResult


def _with_devices(config, devices):
    task = config.tasks[0].model_copy(update={"candidate_devices": devices})
    return config.model_copy(update={"tasks": (task,)})


def _never_run(*_args, **_kwargs):
    raise AssertionError("the sandbox must not start")


def test_missing_gpu_node_fails_with_the_admission_cause_before_any_sandbox(
    console_config, monkeypatch, capsys
):
    """Defect: check --gpu on a host without the declared GPU starts a sandbox (or
    reports PASS) instead of the plain admission cause. Fails if run() is called, the
    exit status is 0, or the line stops naming the missing GPU."""
    monkeypatch.setattr(gpu_check, "run", _never_run)
    config = _with_devices(console_config, ("/dev/nvidia97",))
    assert gpu_check.check_gpu(config) == 2
    out = capsys.readouterr().out
    assert "Task synthetic: GPU FAIL:" in out
    assert "GPU device /dev/nvidia97 is not present on this machine" in out


def test_task_without_gpu_node_is_not_probed(console_config, monkeypatch, capsys):
    """Defect: a CPU-only task is probed (and fails) or check --gpu exits 0 having
    probed nothing. Fails if run() is called or the status is 0."""
    monkeypatch.setattr(gpu_check, "run", _never_run)
    assert gpu_check.check_gpu(console_config) == 2
    assert "not probed" in capsys.readouterr().out
    assert gpu_check.check_gpu(console_config, "absent") == 2


@pytest.mark.parametrize(
    "outcome,result,expected,code",
    [
        ("completed", {"passed": True, "message": "1 CUDA device(s)"}, "GPU PASS: 1 CUDA", 0),
        ("failed", {"passed": False, "message": "CUDA error 304"}, "GPU FAIL: CUDA error 304", 2),
        ("timed_out", None, "GPU FAIL: the probe did not finish within 120 s", 2),
        ("failed", None, "GPU FAIL: the sandbox exited with code 1 before the probe", 2),
    ],
)
def test_probe_outcome_is_reported_as_pass_or_its_cause(
    outcome, result, expected, code, console_config, monkeypatch, capsys
):
    """Defect: a timed-out or crashed probe, or one whose CUDA failed, is printed as
    PASS (or exits 0). Fails if any outcome's line or exit status is misreported, or
    if the probe runs outside the task's profile/workspace."""
    seen = []

    def profile(task, workspace):
        return SandboxProfile.model_construct(
            workspace=workspace,
            read_only=(),
            network=False,
            devices=(Path("/dev/nvidia0"),),
            environment_names=(),
            timeout_seconds=gpu_check.PROBE_TIMEOUT_SECONDS,
        )

    def fake_run(value, argv):
        seen.append(argv)
        assert Path(argv[-1]).parent == value.workspace
        if result is not None:
            Path(argv[-1]).write_text(json.dumps(result))
        returncode = {"completed": 0, "failed": 1, "timed_out": 124}[outcome]
        return ExecutionResult(status=outcome, returncode=returncode, elapsed_seconds=1.0)

    monkeypatch.setattr(gpu_check, "task_profile", profile)
    monkeypatch.setattr(gpu_check, "run", fake_run)
    config = _with_devices(console_config, ("/dev/nvidia0",))
    assert gpu_check.check_gpu(config, "synthetic") == code
    assert expected in capsys.readouterr().out
    assert seen and seen[0][1:3] == ["-m", "tools.candidate_console.gpu_check"]


@pytest.mark.parametrize("uvm_present", [True, False])
def test_missing_uvm_node_prints_the_host_side_fix(
    uvm_present, console_config, monkeypatch, tmp_path, capsys
):
    """Defect: on a fresh headless host /dev/nvidia-uvm does not exist yet, the sandbox
    cannot create it (no capabilities, private /dev), and check --gpu gives no hint
    that one host-side nvidia-smi fixes it. Fails if the note is missing when the node
    is absent or printed when it is present."""
    monkeypatch.setattr(gpu_check, "UVM_NODE", Path("/dev/null") if uvm_present else tmp_path)
    monkeypatch.setattr(
        gpu_check,
        "task_profile",
        lambda task, workspace: SandboxProfile.model_construct(
            workspace=workspace,
            read_only=(),
            network=False,
            devices=(Path("/dev/nvidia0"),),
            environment_names=(),
            timeout_seconds=gpu_check.PROBE_TIMEOUT_SECONDS,
        ),
    )

    def fake_run(value, argv):
        Path(argv[-1]).write_text(json.dumps({"passed": False, "message": "no CUDA"}))
        return ExecutionResult(status="failed", returncode=1, elapsed_seconds=1.0)

    monkeypatch.setattr(gpu_check, "run", fake_run)
    gpu_check.check_gpu(_with_devices(console_config, ("/dev/nvidia0",)))
    out = capsys.readouterr().out
    assert ("run nvidia-smi (or nvidia-modprobe -u -c=0) once on the host" in out) is not (
        uvm_present
    )
