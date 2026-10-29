"""The sandbox-owned GPU passthrough: read-only /sys and NVIDIA control nodes.

Profiles here are built with ``model_construct`` because CI hosts have no
``/dev/nvidia<N>`` character device; ``command_prefix`` does not revalidate, and
admission of a missing node is tested separately against the real validator.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tools.workspace_sandbox import gpu
from tools.workspace_sandbox.command import command_prefix
from tools.workspace_sandbox.profile import SandboxProfile

CONTROL = (Path("/dev/nvidiactl"), Path("/dev/nvidia-uvm"), Path("/dev/nvidia-caps/nvidia-cap1"))


@pytest.fixture(autouse=True)
def gpu_host(monkeypatch):
    """Pretend bwrap exists and this host has NVIDIA control nodes."""
    monkeypatch.setattr("tools.workspace_sandbox.command.shutil.which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(gpu, "control_nodes", lambda: CONTROL)


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
    monkeypatch.setattr(gpu, "control_nodes", lambda: ())
    monkeypatch.setattr(gpu, "SYSFS", tmp_path / "absent")
    assert [command_prefix(value) for value in profiles] == on_gpu_host
    assert not any("/sys" in argv for argv in on_gpu_host)


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


def test_missing_gpu_node_is_refused_with_a_plain_cause(tmp_path):
    """Defect: a task naming a GPU this machine lacks launches anyway, or is refused
    with only a path error. Fails if admission's validator accepts the node or the
    refusal stops saying the GPU is not on this machine."""
    with pytest.raises(ValidationError, match="GPU device /dev/nvidia97 is not present"):
        SandboxProfile(
            workspace=tmp_path,
            network=False,
            devices=(Path("/dev/nvidia97"),),
            timeout_seconds=10,
        )
