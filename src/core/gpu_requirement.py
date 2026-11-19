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
prerequisite is missing from two filesystem facts this process can see (a GPU
device node of any ``core.gpu_devices`` provider, ``/dev/nvidia<N>`` or WSL2's
``/dev/dxg``, as a character device; ``/sys/bus/pci/devices``), never from
driver message text. The launch guard receives the cause through its
measurement capability and words the fix for it.

Before any launch, :func:`training_gpu_warning` words the same requirement as an
advisory for a prepared run that trains but was given no GPU device node
(issue #1562). It never refuses: preparation reports it and succeeds.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from core.gpu_devices import (
    PROVIDERS,
    GpuDeviceProvider,
    declared_providers,
    gpu_node_examples,
    gpu_provider,
)
from core.hardware_models import HardwareContext

#: Why no CUDA device is usable here, in prerequisite order:
#: ``no_device_nodes`` no GPU device node (``core.gpu_devices``) is visible;
#: ``sys_not_mounted`` device nodes are visible but ``/sys`` is not (CUDA then
#: fails with error 304, cudaErrorOperatingSystem); ``cuda_init_failed`` both are
#: visible and CUDA still reports no device (driver or library problem).
GpuUnavailableCause = Literal["no_device_nodes", "sys_not_mounted", "cuda_init_failed"]

_FIX: dict[GpuUnavailableCause, str] = {
    "no_device_nodes": (
        "no GPU device node (/dev/nvidia<N>, or /dev/dxg under WSL2) was passed into "
        "this process. Run on a machine with a CUDA GPU; in the console, list its device "
        "nodes in the task's candidate_devices"
    ),
    "sys_not_mounted": (
        "GPU device nodes were passed, but /sys is not mounted here, so CUDA cannot "
        "start (CUDA error 304). The console run sandbox mounts /sys read-only by itself "
        "for a task that lists a GPU device node; check that the task lists one, then "
        "run check --gpu (see GPU runs in the console README)"
    ),
    # Completed by _fix: the remedy of each provider whose GPU nodes are visible.
    "cuda_init_failed": "GPU device nodes and /sys are visible, but CUDA failed to initialize.",
}
_EMPTY_VISIBLE_DEVICES = "Make sure CUDA_VISIBLE_DEVICES is not set to an empty value"


def _fix(cause: GpuUnavailableCause, dev: Path) -> str:
    """The operator-facing remedy for ``cause``; never recorded (issue #1577).

    ``cuda_init_failed`` names the driver checks of the providers whose GPU nodes
    this process sees under ``dev`` (one provider: its remedy alone, so the native
    NVIDIA text is unchanged; none or several: every candidate, labelled).
    """
    if cause != "cuda_init_failed":
        return _FIX[cause]
    providers = visible_providers(dev) or PROVIDERS
    if len(providers) == 1:
        remedies = providers[0].driver_remedy
    else:
        remedies = " ".join(f"{item.label}: {item.driver_remedy}" for item in providers)
    return f"{_FIX[cause]} {remedies} {_EMPTY_VISIBLE_DEVICES}"


def visible_providers(dev: Path = Path("/dev")) -> tuple[GpuDeviceProvider, ...]:
    """Providers with a GPU device node visible to this process as a character device.

    The device-node fact of :func:`observe_gpu_unavailable_cause`, per provider.
    """
    try:
        found = {
            provider
            for entry in dev.iterdir()
            if (provider := gpu_provider(entry, dev=dev)) is not None and entry.is_char_device()
        }
    except OSError:
        return ()
    return tuple(item for item in PROVIDERS if item in found)


def observe_gpu_unavailable_cause(
    *, dev: Path = Path("/dev"), sys_root: Path = Path("/sys")
) -> GpuUnavailableCause:
    """Classify why CUDA is unavailable, from what this process can see.

    Call only after PyTorch reported no CUDA device. Reads two filesystem facts
    and never touches the driver.
    """
    if not visible_providers(dev):
        return "no_device_nodes"
    if not (sys_root / "bus" / "pci" / "devices").is_dir():
        return "sys_not_mounted"
    return "cuda_init_failed"


def gpu_required_message(
    detail: str, cause: GpuUnavailableCause | None = None, *, dev: Path = Path("/dev")
) -> str:
    """The plain refusal sentence, with the observed reason in parentheses.

    ``cause`` (from :func:`observe_gpu_unavailable_cause`) selects the fix; without
    one the sentence names the requirement and the device-node setting. For
    ``cuda_init_failed`` the fix follows the GPU device providers visible under
    ``dev`` (``core.gpu_devices``), e.g. the WSL2 driver checks for ``/dev/dxg``.
    ``detail`` may quote a recorded reason, whose wording stays stable.
    """
    if cause is not None:
        return (
            f"SIDERIUS real training needs an NVIDIA GPU with CUDA: {_fix(cause, dev)} ({detail})."
        )
    return (
        "SIDERIUS real training needs an NVIDIA GPU with CUDA, and none is "
        f"visible here ({detail}). Run on a machine with a CUDA GPU; in the "
        "console, the task's candidate_devices must include the GPU device nodes."
    )


def training_gpu_warning(*, trains: bool, devices: Iterable[str]) -> str | None:
    """The advisory for a run that trains but was given no GPU device node, else None.

    ``trains`` is the caller's reading of the prepared declaration (a ``tuning``
    node); ``devices`` are the run's device paths. A node of any
    ``core.gpu_devices`` provider counts (``/dev/nvidia<N>``, WSL2's ``/dev/dxg``).
    Reads its arguments only; never probes the host.
    """
    if not trains or declared_providers(Path(device) for device in devices):
        return None
    return (
        "This workflow trains (it has a tuning node), but candidate_devices lists no "
        f"GPU device node ({gpu_node_examples()}). SIDERIUS trains only on a CUDA GPU, "
        "so the run will be refused when it reaches training, after its earlier steps "
        "have already called the LLM. Prepare a new request on the machine that will "
        "run it, with candidate_devices from "
        "tools.workspace_sandbox.gpu.host_gpu_devices() (console add-task fills it in)."
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
