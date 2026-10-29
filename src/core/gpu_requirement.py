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
"""

from __future__ import annotations

from core.hardware_models import HardwareContext


def gpu_required_message(detail: str) -> str:
    """The plain refusal sentence, with the observed reason in parentheses."""
    return (
        "SIDERIUS real training needs an NVIDIA GPU with CUDA, and none is "
        f"visible here ({detail}). Run on a machine with a CUDA GPU; in the "
        "console, the task's candidate_devices must include the GPU device nodes."
    )


def gpu_refusal_for(hardware: HardwareContext) -> str | None:
    """The refusal for a real launch on ``hardware``, or None when a GPU is visible.

    ``hardware`` comes from ``core.hardware_context.discover()``, the single
    device-discovery owner; this function reads it and never probes.
    """
    if hardware.device_available:
        return None
    visible = hardware.cuda_visible_devices
    detail = (
        f"PyTorch {hardware.torch_version} reports no CUDA device; "
        f"CUDA_VISIBLE_DEVICES={'unset' if visible is None else repr(visible)}"
    )
    return gpu_required_message(detail)


def real_launch_gpu_refusal() -> str | None:
    """Discover this process's device view and return the refusal, if any.

    Reads ``core.hardware_context.discover()`` (imported here, so importing
    this module stays torch-free) and writes nothing.
    """
    from core import hardware_context

    return gpu_refusal_for(hardware_context.discover())
