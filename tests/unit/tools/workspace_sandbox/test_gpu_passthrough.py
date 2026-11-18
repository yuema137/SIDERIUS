"""The sandbox-owned GPU passthrough: provider runtime paths and companion nodes.

Profiles here are built with ``model_construct`` because CI hosts have no GPU
character device; ``command_prefix`` does not revalidate, and admission of a
missing node is tested separately against the real validator. Which nodes are
GPUs and what each provider needs is owned by ``core.gpu_devices``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from pydantic import ValidationError

from core import gpu_devices
from core.gpu_devices import NVIDIA, WSL2, GpuDeviceProvider
from tools.workspace_sandbox import gpu
from tools.workspace_sandbox.command import command_prefix
from tools.workspace_sandbox.profile import SandboxProfile

REAL_CONTROL_NODES = GpuDeviceProvider.present_control_nodes  # before the autouse stub
REAL_READ_ONLY = GpuDeviceProvider.present_read_only
CONTROL = (Path("/dev/nvidiactl"), Path("/dev/nvidia-uvm"), Path("/dev/nvidia-caps/nvidia-cap1"))
WSL_LIBRARIES = Path("/usr/lib/wsl")


@pytest.fixture(autouse=True)
def gpu_host(monkeypatch):
    """Pretend bwrap exists, this host has NVIDIA control nodes, /sys and /usr/lib/wsl."""
    monkeypatch.setattr("tools.workspace_sandbox.command.shutil.which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(
        GpuDeviceProvider,
        "present_control_nodes",
        lambda self: CONTROL if self.name == "nvidia" else (),
    )
    monkeypatch.setattr(GpuDeviceProvider, "present_read_only", lambda self: self.read_only)


def _profile(tmp_path: Path, devices=(), read_only=()) -> SandboxProfile:
    return SandboxProfile.model_construct(
        workspace=tmp_path,
        read_only=tuple(read_only),
        network=False,
        devices=tuple(map(Path, devices)),
        environment_names=(),
        timeout_seconds=10,
    )


def _pairs(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, value in enumerate(argv) if value == flag]


def test_cpu_only_profile_gets_no_passthrough_on_a_gpu_host(tmp_path, monkeypatch):
    """Defect: a CPU-only task (or one passing an unrelated device) gains host /sys or
    NVIDIA nodes because the host has a GPU. Fails if the argv differs from the one
    built with the passthrough disabled."""
    profiles = [_profile(tmp_path, d) for d in ((), ("/dev/null",), ("/dev/nvidiactl",))]
    on_gpu_host = [command_prefix(value) for value in profiles]
    monkeypatch.setattr(GpuDeviceProvider, "present_control_nodes", lambda self: ())
    monkeypatch.setattr(GpuDeviceProvider, "present_read_only", lambda self: ())
    assert [command_prefix(value) for value in profiles] == on_gpu_host
    assert not any("/sys" in argv or str(WSL_LIBRARIES) in argv for argv in on_gpu_host)


def test_gpu_node_adds_read_only_sys_and_present_control_nodes(tmp_path):
    """Defect #1164: /dev/nvidia<N> passed without /sys makes CUDA fail with error 304.
    Fails if a GPU profile lacks exactly one read-only /sys bind before the root is
    frozen, or omits (or duplicates) a control node already declared by the task."""
    argv = command_prefix(_profile(tmp_path, ("/dev/nvidia0", "/dev/nvidiactl")))
    assert _pairs(argv, "--ro-bind").count("/sys") == 1
    assert argv.index("/sys") < argv.index("--remount-ro")
    assert _pairs(argv, "--dev-bind") == [
        "/dev/nvidia0",
        "/dev/nvidiactl",
        "/dev/nvidia-uvm",
        "/dev/nvidia-caps/nvidia-cap1",
    ]


def test_existing_sys_in_read_only_is_not_mounted_twice(tmp_path):
    """Defect: configs that already list /sys (the old manual fix) or a /sys subtree
    get a duplicate or shadowing mount. Fails if /sys appears twice or is bound after
    a declared /sys descendant (which it would hide)."""
    argv = command_prefix(
        _profile(tmp_path, ("/dev/nvidia0",), (Path("/sys"), Path("/sys/bus/pci")))
    )
    binds = _pairs(argv, "--ro-bind")
    assert binds.count("/sys") == 1
    assert binds.index("/sys") < binds.index("/sys/bus/pci")


@pytest.mark.parametrize(
    "node,listing",
    [("/dev/nvidia97", "(ls /dev/nvidia*)"), ("/dev/dxg", "(ls -l /dev/dxg)")],
)
def test_missing_gpu_node_is_refused_with_a_plain_cause(tmp_path, node, listing):
    """Defect: a task naming a GPU this machine lacks launches anyway, or is refused
    with only a path error. Fails if admission's validator accepts the node, the
    refusal stops saying the GPU is not on this machine, or a WSL2 operator is told
    to list NVIDIA nodes. (CI hosts have neither node.)"""
    with pytest.raises(ValidationError) as error:
        SandboxProfile(
            workspace=tmp_path,
            network=False,
            devices=(Path(node),),
            timeout_seconds=10,
        )
    assert f"GPU device {node} is not present on this machine" in str(error.value)
    assert listing in str(error.value)


def test_control_nodes_keep_only_real_character_devices(tmp_path):
    """Defect: a symlink or regular file named like a control node (or under
    /dev/nvidia-caps) is dev-bound, or a host without the caps folder crashes.
    Fails if anything but a non-symlink character device is returned."""
    caps = tmp_path / "caps"
    caps.mkdir()
    (caps / "nvidia-cap1").symlink_to("/dev/null")
    (caps / "nvidia-cap2").write_text("")
    (tmp_path / "ctl-link").symlink_to("/dev/null")
    (tmp_path / "ctl-file").write_text("")
    real = (Path("/dev/null"), tmp_path / "ctl-link", tmp_path / "ctl-file", tmp_path / "gone")
    provider = dataclasses.replace(NVIDIA, control_nodes=real, control_directory=caps)
    assert REAL_CONTROL_NODES(provider) == (Path("/dev/null"),)
    provider = dataclasses.replace(provider, control_directory=tmp_path / "no-caps")
    assert REAL_CONTROL_NODES(provider) == (Path("/dev/null"),)


def test_runtime_paths_are_added_only_when_the_host_has_them(tmp_path, monkeypatch):
    """Defect: a host (or container) without /sys, or a WSL2 install whose driver
    library folder is missing, gets a bind of a missing path, so bwrap fails before
    CUDA can report anything. Fails if a missing path is returned or a present one
    is dropped."""
    absent = dataclasses.replace(NVIDIA, read_only=(tmp_path / "absent",))
    present = dataclasses.replace(WSL2, read_only=(tmp_path, tmp_path / "absent"))
    assert REAL_READ_ONLY(absent) == ()
    assert REAL_READ_ONLY(present) == (tmp_path,)
    monkeypatch.setattr(gpu_devices, "PROVIDERS", (absent, present))
    monkeypatch.setattr(GpuDeviceProvider, "present_read_only", REAL_READ_ONLY)
    assert gpu.passthrough((Path("/dev/nvidia0"),)) == ((), CONTROL)
    assert gpu.passthrough((Path("/dev/dxg"),)) == ((tmp_path,), ())


def test_wsl2_gpu_node_gets_its_driver_libraries_and_no_nvidia_nodes(tmp_path):
    """Defect #1524: under WSL2 the GPU is /dev/dxg with the CUDA driver in
    /usr/lib/wsl, so a sandbox that knows only /dev/nvidia<N> passes no GPU. Fails
    if /dev/dxg gains no read-only /sys and /usr/lib/wsl before the root is frozen,
    is not dev-bound exactly once, or pulls in the NVIDIA control nodes."""
    argv = command_prefix(_profile(tmp_path, ("/dev/dxg",)))
    binds = _pairs(argv, "--ro-bind")
    assert binds.count("/sys") == 1 and binds.count(str(WSL_LIBRARIES)) == 1
    assert argv.index(str(WSL_LIBRARIES)) < argv.index("--remount-ro")
    assert _pairs(argv, "--dev-bind") == ["/dev/dxg"]
    # Read-only binds stay ordered by depth, so /usr/lib/wsl follows /usr.
    assert binds.index("/usr") < binds.index(str(WSL_LIBRARIES))


def test_host_gpu_devices_lists_every_providers_gpu_nodes(tmp_path, monkeypatch):
    """Defect: control nodes such as /dev/nvidia-uvm are written into a request's
    candidate_devices (the node can be absent until first CUDA use, and admission then
    refuses the run), a symlink alias is listed, GPUs are ordered as text (nvidia10
    before nvidia2), or a WSL2 /dev/dxg is missed (#1524). The recipes and add-task
    call this function. Fails if it returns anything but the providers' GPU nodes,
    NVIDIA by number then /dev/dxg, as strings."""
    import functools

    dev = tmp_path / "dev"
    dev.mkdir()
    for name in ("nvidia-uvm", "nvidia0", "nvidia10", "nvidia2", "nvidiactl", "dxg", "null"):
        (dev / name).write_text("")
    (dev / "nvidia3").symlink_to(dev / "nvidia0")
    real = Path.is_char_device
    monkeypatch.setattr(Path, "is_char_device", lambda self: self.parent == dev or real(self))
    monkeypatch.setattr(
        gpu, "host_gpu_nodes", functools.partial(gpu_devices.host_gpu_nodes, dev=dev)
    )
    assert gpu.host_gpu_devices() == tuple(
        str(dev / name) for name in ("nvidia0", "nvidia2", "nvidia10", "dxg")
    )
