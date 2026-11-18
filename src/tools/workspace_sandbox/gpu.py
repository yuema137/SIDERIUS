"""The sandbox-owned GPU passthrough added when a profile declares an NVIDIA GPU node.

A ``/dev/nvidia<N>`` node alone does not let CUDA start: without host ``/sys``,
``cudaGetDeviceCount`` fails with error 304 (cudaErrorOperatingSystem). On the
checked RTX 5090 host the GPU's PCI directory plus ``/sys/module/nvidia*`` was
also enough, but the passthrough mounts all of ``/sys`` read-only (Docker
mounts sysfs read-only; Apptainer binds host ``/sys``), so a driver that reads other
sysfs metadata keeps working. It also passes the NVIDIA control nodes the host
has. Nothing here is user configuration and a profile without a GPU node gets
no passthrough at all.

:func:`host_gpu_devices` is the one detector of this host's GPU nodes for a
request's device list (``candidate_devices``): console ``add-task`` and the
documented request recipes call it, so a copied recipe passes the GPUs this
machine has, and none on a machine without one.
"""

from __future__ import annotations

import glob
import re
from collections.abc import Iterable
from pathlib import Path

#: A GPU device node; ``nvidiactl`` and ``nvidia-uvm`` are control nodes, not GPUs.
GPU_NODE = re.compile(r"/dev/nvidia[0-9]+")
SYSFS = Path("/sys")
#: Control nodes CUDA/NVML open beside ``/dev/nvidia<N>``, passed when present.
CONTROL_NODES = tuple(
    Path(p)
    for p in ("/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools", "/dev/nvidia-modeset")
)
#: MIG capability nodes, passed when present.
CAPS_DIRECTORY = Path("/dev/nvidia-caps")


def declares_gpu(devices: Iterable[Path]) -> bool:
    return any(GPU_NODE.fullmatch(str(device)) for device in devices)


def _host_node(path: Path) -> bool:
    return path.is_char_device() and not path.is_symlink()


def host_gpu_devices() -> tuple[str, ...]:
    """This host's GPU device nodes (``/dev/nvidia<N>`` character devices), by number.

    Empty on a machine without an NVIDIA GPU node. Control nodes (``nvidiactl``,
    ``nvidia-uvm``, ...) are not listed: :func:`passthrough` adds the ones present
    at launch, and listing them would refuse a run whenever a lazily created node
    is absent.
    """
    found = [
        name
        for name in glob.glob("/dev/nvidia*")
        if GPU_NODE.fullmatch(name) and _host_node(Path(name))
    ]
    return tuple(sorted(found, key=lambda name: int(name.removeprefix("/dev/nvidia"))))


def control_nodes() -> tuple[Path, ...]:
    """The NVIDIA control and MIG capability nodes present on this host, in a fixed order."""
    caps = sorted(CAPS_DIRECTORY.glob("*")) if CAPS_DIRECTORY.is_dir() else []
    return tuple(path for path in (*CONTROL_NODES, *caps) if _host_node(path))


def passthrough(devices: tuple[Path, ...]) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """``(read_only, devices)`` to add for ``devices``; both empty without a GPU node."""
    if not declares_gpu(devices):
        return (), ()
    extra_devices = tuple(node for node in control_nodes() if node not in devices)
    return ((SYSFS,) if SYSFS.is_dir() else ()), extra_devices
