"""``check --gpu``: start CUDA inside the production run sandbox for each GPU task.

The host side builds the same ``SandboxProfile`` a candidate run of the task gets
(``candidate_prepare.bundle``: data root, manifest and ``task_read_only`` read-only,
the task's ``candidate_devices``, network off) around a fresh temporary workspace,
and runs :func:`probe` inside it through ``workspace_sandbox.runner.run``. The
probe writes one JSON result into the workspace; no network, no model calls.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from tools.workspace_sandbox.command import SandboxUnavailable
from tools.workspace_sandbox.gpu import declares_gpu, passthrough
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import run

from .models import ConsoleConfig, TaskChoice

#: Wall-clock cap for one probe (PyTorch import plus CUDA initialization).
PROBE_TIMEOUT_SECONDS = 120.0
RESULT_FILE = "gpu-check.json"


def probe() -> tuple[bool, str]:
    """Inside the sandbox: is CUDA usable? ``(passed, plain sentence)``."""
    try:
        import torch
    except ImportError as error:
        return False, f"PyTorch is not importable in the run environment ({error})"
    if not torch.cuda.is_available():
        from core.gpu_requirement import real_launch_gpu_refusal

        return False, real_launch_gpu_refusal() or "PyTorch reports no CUDA device"
    try:
        torch.zeros(1, device="cuda")
        torch.cuda.synchronize()
    except RuntimeError as error:
        return False, f"CUDA started but could not use the GPU ({str(error).splitlines()[0]})"
    count = torch.cuda.device_count()
    return True, f"{count} CUDA device(s), first: {torch.cuda.get_device_name(0)}"


def task_profile(task: TaskChoice, workspace: Path) -> SandboxProfile:
    """The candidate-run profile of ``task`` with ``workspace`` as its project folder."""
    return SandboxProfile(
        workspace=workspace,
        read_only=tuple(
            sorted(
                {Path(task.data_root), Path(task.task_manifest), *map(Path, task.task_read_only)}
            )
        ),
        network=False,
        devices=tuple(map(Path, task.candidate_devices)),
        environment_names=(),
        timeout_seconds=PROBE_TIMEOUT_SECONDS,
    )


def _check_task(task: TaskChoice) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="siderius-gpu-check-") as folder:
        workspace = Path(folder).resolve()
        try:
            profile = task_profile(task, workspace)
        except ValueError as error:
            return False, f"the run sandbox refuses this task's settings ({error})"
        extra_read_only, extra_devices = passthrough(profile.devices)
        passed = ", ".join(str(p) for p in (*profile.devices, *extra_devices))
        print(
            f"Task {task.task_id}: sandbox passes {passed}"
            + (" and read-only /sys" if extra_read_only else "")
        )
        command = [sys.executable, "-m", __name__, str(workspace / RESULT_FILE)]
        try:
            outcome = run(profile, command)
        except SandboxUnavailable as error:
            return False, f"the run sandbox cannot start ({error})"
        result = workspace / RESULT_FILE
        if outcome.status == "timed_out":
            return False, f"the probe did not finish within {PROBE_TIMEOUT_SECONDS:g} s"
        if not result.is_file():
            return False, (
                f"the sandbox exited with code {outcome.returncode} before the probe "
                "reported (see the output above)"
            )
        reported = json.loads(result.read_text())
        return bool(reported["passed"]), str(reported["message"])


def check_gpu(config: ConsoleConfig, task_id: str | None = None) -> int:
    """Probe each selected GPU task; 0 only when every probed task passes."""
    tasks = [task for task in config.tasks if task_id is None or task.task_id == task_id]
    if task_id is not None and not tasks:
        print(f"check --gpu: no task {task_id} in this console configuration", file=sys.stderr)
        return 2
    gpu_tasks = [task for task in tasks if declares_gpu(map(Path, task.candidate_devices))]
    for task in tasks:
        if task not in gpu_tasks:
            print(f"Task {task.task_id}: no /dev/nvidia<N> in candidate_devices; not probed")
    if not gpu_tasks:
        print("check --gpu: no selected task lists a GPU device node", file=sys.stderr)
        return 2
    failed = False
    for task in gpu_tasks:
        passed, message = _check_task(task)
        print(f"Task {task.task_id}: GPU {'PASS' if passed else 'FAIL'}: {message}")
        failed = failed or not passed
    return 2 if failed else 0


if __name__ == "__main__":
    passed, message = probe()
    Path(sys.argv[1]).write_text(json.dumps({"passed": passed, "message": message}))
    raise SystemExit(0 if passed else 1)
