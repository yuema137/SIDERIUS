"""The one statement of SIDERIUS's real-training GPU requirement (issue #1136).

A real (non-pseudo) launch trains and measures candidates on a CUDA device;
no CPU execution mode exists. Two places refuse a launch on a host without one:

* the CLI preflight in ``workflows.run_one_iteration``, before any iteration
  directory, run lock or LLM call, through ``real_launch_gpu_refusal`` (which
  reads ``core.hardware_context.discover()``);
* the runtime-control launch guard, when the measurement capability it is
  handed reports that no accelerator is usable.

Both render the refusal through ``gpu_required_message`` so an operator reads
the same sentence wherever the launch stops. Importing this module never
probes a device.

When CUDA is unavailable, :func:`observe_gpu_unavailable_cause` names which
prerequisite is missing from two filesystem facts this process can see (a
``/dev/nvidia<N>`` character device; ``/sys/bus/pci/devices``), never from
driver message text. The launch guard receives the cause through its
measurement capability and words the fix for it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from core.hardware_models import HardwareContext

#: Why no CUDA device is usable here, in prerequisite order:
#: ``no_device_nodes`` no ``/dev/nvidia<N>`` character device is visible;
#: ``sys_not_mounted`` device nodes are visible but ``/sys`` is not (CUDA then
#: fails with error 304, cudaErrorOperatingSystem); ``cuda_init_failed`` both are
#: visible and CUDA still reports no device (driver or library problem).
GpuUnavailableCause = Literal["no_device_nodes", "sys_not_mounted", "cuda_init_failed"]

_GPU_NODE = re.compile(r"nvidia[0-9]+")

_FIX: dict[GpuUnavailableCause, str] = {
    "no_device_nodes": (
        "no NVIDIA device node (/dev/nvidia<N>) was passed into this process. Run on a "
        "machine with a CUDA GPU; in the console, list its device nodes in the task's "
        "candidate_devices"
    ),
    "sys_not_mounted": (
        "NVIDIA device nodes were passed, but /sys is not mounted here, so CUDA cannot "
        "start (CUDA error 304). The console run sandbox mounts /sys read-only by itself "
        "for a task that lists a /dev/nvidia<N> device node; check that the task lists "
        "one, then run check --gpu (see GPU runs in the console README)"
    ),
    "cuda_init_failed": (
        "NVIDIA device nodes and /sys are visible, but CUDA failed to initialize. "
        "Check the driver on this machine with nvidia-smi, pass /dev/nvidiactl and "
        "/dev/nvidia-uvm as well as /dev/nvidia<N>, and make sure CUDA_VISIBLE_DEVICES "
        "is not set to an empty value"
    ),
}


def observe_gpu_unavailable_cause(
    *, dev: Path = Path("/dev"), sys_root: Path = Path("/sys")
) -> GpuUnavailableCause:
    """Classify why CUDA is unavailable, from what this process can see.

    Call only after PyTorch reported no CUDA device. Reads two filesystem facts
    and never touches the driver.
    """
    try:
        nodes = any(
            _GPU_NODE.fullmatch(entry.name) and entry.is_char_device() for entry in dev.iterdir()
        )
    except OSError:
        nodes = False
    if not nodes:
        return "no_device_nodes"
    if not (sys_root / "bus" / "pci" / "devices").is_dir():
        return "sys_not_mounted"
    return "cuda_init_failed"


def gpu_required_message(detail: str, cause: GpuUnavailableCause | None = None) -> str:
    """The plain refusal sentence, with the observed reason in parentheses.

    ``cause`` (from :func:`observe_gpu_unavailable_cause`) selects the fix; without
    one the sentence names the requirement and the device-node setting.
    """
    if cause is not None:
        return f"SIDERIUS real training needs an NVIDIA GPU with CUDA: {_FIX[cause]} ({detail})."
    return (
        "SIDERIUS real training needs an NVIDIA GPU with CUDA, and none is "
        f"visible here ({detail}). Run on a machine with a CUDA GPU; in the "
        "console, the task's candidate_devices must include the GPU device nodes."
    )


def gpu_refusal_for(
    hardware: HardwareContext, cause: GpuUnavailableCause | None = None
) -> str | None:
    """The refusal for a real launch on ``hardware``, or None when a GPU is visible.

    ``hardware`` comes from ``core.hardware_context.discover()``, the single
    device-discovery owner; ``cause`` (when observed) selects the fix. This
    function reads its arguments and never probes.
    """
    if hardware.device_available:
        return None
    visible = hardware.cuda_visible_devices
    detail = (
        f"PyTorch {hardware.torch_version} reports no CUDA device; "
        f"CUDA_VISIBLE_DEVICES={'unset' if visible is None else repr(visible)}"
    )
    return gpu_required_message(detail, cause)


def real_launch_gpu_refusal() -> str | None:
    """Discover this process's device view and return the refusal, if any.

    Reads ``core.hardware_context.discover()`` (imported here, so importing
    this module stays torch-free) and, when no device is available, the
    filesystem facts of :func:`observe_gpu_unavailable_cause`; writes nothing.
    """
    from core import hardware_context

    hardware = hardware_context.discover()
    if hardware.device_available:
        return None
    return gpu_refusal_for(hardware, observe_gpu_unavailable_cause())
