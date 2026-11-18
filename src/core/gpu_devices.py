"""GPU device providers: how a driver stack exposes CUDA devices to a Linux process.

The one owner (issue #1524) of which ``/dev`` nodes are GPU device nodes, which
companion nodes and read-only runtime paths a sandboxed CUDA process needs beside
them, and how a host's GPU nodes are found. Each driver stack is one
:class:`GpuDeviceProvider` in :data:`PROVIDERS`:

* ``nvidia``: the native Linux NVIDIA driver. One ``/dev/nvidia<N>`` per GPU;
  CUDA/NVML also open the control nodes (``/dev/nvidiactl``, ``/dev/nvidia-uvm``,
  ...) and read host ``/sys`` (without it CUDA fails with error 304).
* ``wsl2``: GPU paravirtualization in Windows Subsystem for Linux 2. One
  ``/dev/dxg`` serves every GPU; the CUDA user-mode driver (``libcuda``,
  ``libdxcore``, NVML and ``nvidia-smi``) lives in the Windows driver store under
  ``/usr/lib/wsl`` (``lib`` and ``drivers``), mounted there by WSL.

Consumers (sandbox passthrough, ``add-task`` detection, profile admission,
``check --gpu`` and the launch-refusal cause) ask this module instead of matching
device names themselves. Only filesystem facts are read; importing never probes
a device or imports torch. Adding a driver stack means adding one provider here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DEV = Path("/dev")


def _host_node(path: Path) -> bool:
    """A real character device, not a symlink alias (the sandbox refuses aliases)."""
    return path.is_char_device() and not path.is_symlink()


@dataclass(frozen=True)
class GpuDeviceProvider:
    """One driver stack's GPU device nodes and what CUDA needs beside them."""

    #: Stable identifier, e.g. ``"nvidia"``.
    name: str
    #: Plain name for operator messages, e.g. ``"NVIDIA GPU"``.
    label: str
    #: Basename under ``/dev`` of one GPU device node (full match).
    node_name: re.Pattern[str]
    #: How messages write the node, e.g. ``"/dev/nvidia<N>"``.
    node_display: str
    #: Shell command an operator runs to list this provider's nodes.
    listing_command: str
    #: What the sandbox adds beside a declared node, in plain words.
    passthrough_note: str
    #: Companion character devices passed when present on the host.
    control_nodes: tuple[Path, ...] = ()
    #: A directory whose character devices are passed when present (MIG caps).
    control_directory: Path | None = None
    #: Runtime directories mounted read-only when present on the host.
    read_only: tuple[Path, ...] = ()

    def is_gpu_node(self, path: Path, *, dev: Path = DEV) -> bool:
        return path.parent == dev and self.node_name.fullmatch(path.name) is not None

    def host_gpu_nodes(self, *, dev: Path = DEV) -> tuple[Path, ...]:
        """This provider's GPU nodes present under ``dev``, by GPU number."""
        try:
            entries = list(dev.iterdir())
        except OSError:
            return ()
        nodes = [path for path in entries if self.is_gpu_node(path, dev=dev) and _host_node(path)]
        return tuple(sorted(nodes, key=_gpu_number))

    def present_control_nodes(self) -> tuple[Path, ...]:
        """Companion nodes present on this host, in a fixed order."""
        directory = self.control_directory
        listed = sorted(directory.glob("*")) if directory is not None and directory.is_dir() else []
        return tuple(path for path in (*self.control_nodes, *listed) if _host_node(path))

    def present_read_only(self) -> tuple[Path, ...]:
        return tuple(path for path in self.read_only if path.is_dir())


def _gpu_number(path: Path) -> tuple[int, str]:
    digits = re.search(r"[0-9]+$", path.name)
    return (int(digits.group()) if digits else 0, path.name)


SYSFS = Path("/sys")

NVIDIA = GpuDeviceProvider(
    name="nvidia",
    label="NVIDIA GPU",
    node_name=re.compile(r"nvidia[0-9]+"),
    node_display="/dev/nvidia<N>",
    listing_command="ls /dev/nvidia*",
    passthrough_note="read-only /sys and the NVIDIA control nodes",
    control_nodes=tuple(
        Path(p)
        for p in (
            "/dev/nvidiactl",
            "/dev/nvidia-uvm",
            "/dev/nvidia-uvm-tools",
            "/dev/nvidia-modeset",
        )
    ),
    control_directory=Path("/dev/nvidia-caps"),
    read_only=(SYSFS,),
)

WSL2 = GpuDeviceProvider(
    name="wsl2",
    label="WSL2 GPU",
    node_name=re.compile(r"dxg"),
    node_display="/dev/dxg",
    listing_command="ls -l /dev/dxg",
    passthrough_note="read-only /sys and the WSL GPU driver libraries (/usr/lib/wsl)",
    read_only=(SYSFS, Path("/usr/lib/wsl")),
)

#: Every supported driver stack, in the order detection lists their nodes.
PROVIDERS: tuple[GpuDeviceProvider, ...] = (NVIDIA, WSL2)


def gpu_provider(path: Path, *, dev: Path = DEV) -> GpuDeviceProvider | None:
    """The provider whose GPU device node ``path`` is, or None (e.g. a control node)."""
    return next((item for item in PROVIDERS if item.is_gpu_node(path, dev=dev)), None)


def declared_providers(devices: Iterable[Path]) -> tuple[GpuDeviceProvider, ...]:
    """Providers with at least one GPU node in ``devices``, in :data:`PROVIDERS` order."""
    found = {gpu_provider(Path(device)) for device in devices}
    return tuple(item for item in PROVIDERS if item in found)


def host_gpu_nodes(*, dev: Path = DEV) -> tuple[Path, ...]:
    """Every provider's GPU nodes present on this host, provider by provider."""
    return tuple(node for item in PROVIDERS for node in item.host_gpu_nodes(dev=dev))


def gpu_node_examples() -> str:
    """How messages name a GPU node of any provider: ``/dev/nvidia<N> or /dev/dxg``."""
    return " or ".join(item.node_display for item in PROVIDERS)
