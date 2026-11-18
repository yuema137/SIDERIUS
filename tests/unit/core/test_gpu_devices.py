"""``core.gpu_devices``: which /dev nodes are GPUs, per driver-stack provider (#1524).

No CI host has a GPU character device, so a fixture /dev holds regular files and
``Path.is_char_device`` is answered for that folder only; symlinks keep their
real answer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.gpu_devices import NVIDIA, WSL2, declared_providers, gpu_provider, host_gpu_nodes

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def fake_dev(tmp_path, monkeypatch):
    dev = tmp_path / "dev"
    dev.mkdir()
    real = Path.is_char_device
    monkeypatch.setattr(Path, "is_char_device", lambda self: self.parent == dev or real(self))
    return dev


def _layout(dev: Path, *names: str) -> None:
    for name in names:
        (dev / name).write_text("")


def test_native_nvidia_layout_lists_only_gpu_nodes_by_number(fake_dev):
    """Defect: control nodes (nvidia-uvm may be absent until first CUDA use, so a
    written one refuses the run) or symlink aliases (refused by the sandbox) are
    listed, or GPUs are ordered as text (nvidia10 before nvidia2). Fails on any."""
    _layout(fake_dev, "nvidia-uvm", "nvidia0", "nvidia10", "nvidia2", "nvidiactl", "null")
    (fake_dev / "nvidia3").symlink_to(fake_dev / "nvidia0")
    assert host_gpu_nodes(dev=fake_dev) == tuple(
        fake_dev / name for name in ("nvidia0", "nvidia2", "nvidia10")
    )


def test_wsl2_layout_lists_dxg(fake_dev):
    """Defect #1524: under WSL2 the only GPU node is /dev/dxg, so detection that
    knows only /dev/nvidia<N> finds no GPU and add-task writes none. Fails if
    /dev/dxg is not found on a WSL2 layout."""
    _layout(fake_dev, "dxg", "null", "tty0")
    assert host_gpu_nodes(dev=fake_dev) == (fake_dev / "dxg",)


def test_a_host_without_dev_access_lists_nothing(tmp_path):
    """Defect: an unreadable or missing /dev crashes detection. Fails if it raises."""
    assert host_gpu_nodes(dev=tmp_path / "absent") == ()


def test_declared_providers_classify_by_node_not_by_prefix():
    """Defect: a control node, a MIG cap or a path outside /dev selects a provider
    and so mounts /sys and driver folders for a CPU task. Fails if any non-GPU path
    selects a provider or the order stops following PROVIDERS."""
    non_gpu = ("/dev/nvidiactl", "/dev/nvidia-caps/nvidia-cap1", "/dev/dxg0", "/tmp/nvidia0")
    assert declared_providers(map(Path, non_gpu)) == ()
    assert declared_providers(map(Path, ("/dev/dxg", "/dev/nvidia1"))) == (NVIDIA, WSL2)


def test_browser_gpu_rule_matches_the_providers():
    """Defect: the console page (compute-requirement.js) keeps its own copy of the
    GPU-node rule, so a provider added here leaves the page warning that a WSL2
    task passes no GPU (or the reverse). Fails if the page's regex and
    ``gpu_provider`` disagree on any sample path."""
    script = (REPO / "src/tools/candidate_console/static/compute-requirement.js").read_text()
    literal = re.search(r"device => /(.+?)/\.test\(device\)", script)
    assert literal is not None
    page_rule = re.compile(literal.group(1).replace("\\/", "/"))
    samples = (
        "/dev/nvidia0",
        "/dev/nvidia12",
        "/dev/dxg",
        "/dev/nvidiactl",
        "/dev/nvidia-uvm",
        "/dev/nvidia-caps/nvidia-cap1",
        "/dev/dxg0",
        "/dev/null",
        "/dev/sub/nvidia0",
    )
    for sample in samples:
        assert (page_rule.fullmatch(sample) is not None) is (
            gpu_provider(Path(sample)) is not None
        ), sample
