"""The sandbox-owned GPU passthrough added when a profile declares a GPU device node.

A GPU device node alone does not let CUDA start. For ``/dev/nvidia<N>``, without
host ``/sys`` ``cudaGetDeviceCount`` fails with error 304
(cudaErrorOperatingSystem). On the checked RTX 5090 host the GPU's PCI directory
plus ``/sys/module/nvidia*`` was also enough, but the passthrough mounts all of
``/sys`` read-only (Docker mounts sysfs read-only; Apptainer binds host ``/sys``),
so a driver that reads other sysfs metadata keeps working. It also passes the
companion nodes the host has.

Which nodes are GPUs and what each driver stack needs beside them is owned by
``core.gpu_devices`` (one provider per stack: native NVIDIA, WSL2 ``/dev/dxg``).
This module only turns the providers a profile declares into mounts. Nothing
here is user configuration, and a profile without a GPU node gets no passthrough
at all.

:func:`host_gpu_devices` is the one detector of this host's GPU nodes for a
request's device list (``candidate_devices``): console ``add-task`` and the
documented request recipes call it, so a copied recipe passes the GPUs this
machine has, and none on a machine without one.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from core.gpu_devices import declared_providers, host_gpu_nodes


def declares_gpu(devices: Iterable[Path]) -> bool:
    return bool(declared_providers(devices))


def host_gpu_devices() -> tuple[str, ...]:
    """This host's GPU device nodes, as ``candidate_devices`` strings.

    Every ``core.gpu_devices`` provider's nodes in provider order:
    ``/dev/nvidia<N>`` by GPU number, then WSL2's ``/dev/dxg``; character devices
    only, symlinks excluded. Empty on a machine without a GPU node. Control nodes
    (``nvidiactl``, ``nvidia-uvm``, ...) are not listed: :func:`passthrough` adds
    the ones present at launch, and listing them would refuse a run whenever a
    lazily created node is absent.
    """
    return tuple(str(node) for node in host_gpu_nodes())


def passthrough(devices: tuple[Path, ...]) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """``(read_only, devices)`` to add for ``devices``; both empty without a GPU node.

    Each declared provider contributes its present read-only runtime directories
    and companion nodes, in provider order, without duplicates or nodes the
    profile already lists.
    """
    providers = declared_providers(devices)
    read_only = dict.fromkeys(path for item in providers for path in item.present_read_only())
    extra = dict.fromkeys(
        node for item in providers for node in item.present_control_nodes() if node not in devices
    )
    return tuple(read_only), tuple(extra)
