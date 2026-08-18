"""Unit tests for core/hardware_context.py — schema + discover().

All tests are CPU-only. We monkeypatch ``torch.cuda`` to simulate each
target device family (RTX 5090 / A100-40GB / A100-80GB / CPU-only) without
needing any of them physically present. The goal is to prove that the same
code adapts to every device — no hardcoded literals anywhere in the module.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from types import SimpleNamespace

import pytest
import torch
from pydantic import ValidationError

from core.hardware_context import (
    _SAFETY_FRACTION,
    HardwareContext,
    discover,
)

# ── HardwareContext schema ──────────────────────────────────────────────────


def _make_ctx(**overrides) -> HardwareContext:
    """Build a minimal valid HardwareContext for schema-level tests."""
    defaults: dict = dict(
        device_name="TEST-DEVICE",
        total_memory_bytes=32 * 1024**3,  # 32 GiB
        compute_capability=(12, 0),
        multiprocessor_count=170,
        cuda_runtime_version="12.8",
        torch_version="2.10.0+cu128",
        hostname="test-host",
        device_available=True,
        discovered_at=datetime(2026, 4, 23, tzinfo=UTC),
    )
    defaults.update(overrides)
    return HardwareContext(**defaults)


def test_usable_cap_bytes_is_exactly_safety_fraction_of_total():
    total = 32 * 1024**3
    ctx = _make_ctx(total_memory_bytes=total)
    assert ctx.usable_cap_bytes == int(_SAFETY_FRACTION * total)
    assert _SAFETY_FRACTION == 0.80, (
        "Safety fraction changed — review design doc §3.9.1 and "
        "regenerate golden numbers before updating this test."
    )


def test_usable_cap_rescales_without_code_change():
    """Same code on a 40 GiB A100 must yield a 40-GiB-scaled cap; on an
    80 GiB A100, an 80-GiB-scaled cap. This is Principle 5."""
    for total_gib in [16, 24, 32, 40, 80]:
        total = total_gib * 1024**3
        ctx = _make_ctx(total_memory_bytes=total)
        assert ctx.usable_cap_bytes == int(0.80 * total)
        assert ctx.usable_cap_gb == pytest.approx(0.80 * total_gib, rel=1e-9)


def test_total_memory_gb_conversion():
    ctx = _make_ctx(total_memory_bytes=32 * 1024**3)
    assert ctx.total_memory_gb == pytest.approx(32.0, rel=1e-9)


def test_cpu_stub_cap_is_zero():
    """On CPU-only hosts, total_memory_bytes=0 and the cap follows. Consumers
    that need a GPU must branch on device_available, NOT on cap>0."""
    ctx = _make_ctx(
        device_name="cpu",
        total_memory_bytes=0,
        device_available=False,
        compute_capability=(0, 0),
        multiprocessor_count=0,
        cuda_runtime_version=None,
    )
    assert ctx.usable_cap_bytes == 0
    assert ctx.usable_cap_gb == 0.0
    assert ctx.device_available is False


# ── discover() — patched CUDA ────────────────────────────────────────────────


def _patch_cuda_available(
    monkeypatch, *, available: bool, props=None, runtime: str | None = "12.8"
):
    """Swap ``torch.cuda.is_available`` and ``get_device_properties`` wholesale.

    ``props`` is a SimpleNamespace with the attributes discover() reads
    (``name``, ``total_memory``, ``major``, ``minor``, ``multi_processor_count``).
    """
    monkeypatch.setattr(torch.cuda, "is_available", lambda: available)
    if available:
        monkeypatch.setattr(torch.cuda, "get_device_properties", lambda idx: props)
    # torch.version.cuda is read as an attribute, not called — patch via setattr
    monkeypatch.setattr(torch.version, "cuda", runtime, raising=False)


def test_discover_on_cpu_only_host(monkeypatch):
    _patch_cuda_available(monkeypatch, available=False, runtime=None)
    ctx = discover()
    assert ctx.device_available is False
    assert ctx.device_name == "cpu"
    assert ctx.total_memory_bytes == 0
    assert ctx.compute_capability == (0, 0)
    assert ctx.multiprocessor_count == 0
    assert ctx.cuda_runtime_version is None
    assert ctx.torch_version == torch.__version__
    assert ctx.discovered_at.tzinfo is not None  # UTC-aware


def test_discover_on_fake_rtx_5090(monkeypatch):
    """Simulate lilab's 32 GiB RTX 5090."""
    props = SimpleNamespace(
        name="NVIDIA GeForce RTX 5090",
        total_memory=32 * 1024**3,
        major=12,
        minor=0,
        multi_processor_count=170,
    )
    _patch_cuda_available(monkeypatch, available=True, props=props, runtime="12.8")
    ctx = discover()
    assert ctx.device_available is True
    assert ctx.device_name == "NVIDIA GeForce RTX 5090"
    assert ctx.total_memory_bytes == 32 * 1024**3
    assert ctx.compute_capability == (12, 0)
    assert ctx.multiprocessor_count == 170
    assert ctx.cuda_runtime_version == "12.8"
    assert ctx.usable_cap_bytes == int(0.80 * 32 * 1024**3)


def test_discover_on_fake_a100_40gb_same_code(monkeypatch):
    """Principle 5: the same code adapts to SDSC Expanse A100-40GB."""
    props = SimpleNamespace(
        name="NVIDIA A100-SXM4-40GB",
        total_memory=40 * 1024**3,
        major=8,
        minor=0,
        multi_processor_count=108,
    )
    _patch_cuda_available(monkeypatch, available=True, props=props, runtime="11.8")
    ctx = discover()
    assert ctx.device_name == "NVIDIA A100-SXM4-40GB"
    assert ctx.total_memory_bytes == 40 * 1024**3
    assert ctx.usable_cap_gb == pytest.approx(32.0, rel=1e-9)


def test_discover_on_fake_a100_80gb_same_code(monkeypatch):
    """Principle 5: same code, 80-GiB cap."""
    props = SimpleNamespace(
        name="NVIDIA A100-SXM4-80GB",
        total_memory=80 * 1024**3,
        major=8,
        minor=0,
        multi_processor_count=108,
    )
    _patch_cuda_available(monkeypatch, available=True, props=props, runtime="11.8")
    ctx = discover()
    assert ctx.total_memory_bytes == 80 * 1024**3
    assert ctx.usable_cap_gb == pytest.approx(64.0, rel=1e-9)


def test_discover_timestamp_is_fresh(monkeypatch):
    """discovered_at must be UTC-aware and within the last second."""
    props = SimpleNamespace(
        name="fake",
        total_memory=1024,
        major=1,
        minor=0,
        multi_processor_count=1,
    )
    _patch_cuda_available(monkeypatch, available=True, props=props)
    before = datetime.now(UTC)
    ctx = discover()
    after = datetime.now(UTC)
    assert before <= ctx.discovered_at <= after


# ── V19 O1a — runtime provenance (multi-GPU, driver, env, errors) ───────────


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


def _patch_probes(
    monkeypatch,
    *,
    driver: str | Exception | _FakeCompleted = "580.65.06\n580.65.06",
    commit: str | Exception | _FakeCompleted = "a" * 40,
):
    """Mock both external probes (nvidia-smi + git) deterministically."""
    import core.hardware_context as hc

    def fake_run(argv, **kwargs):
        target = driver if argv[0] == "nvidia-smi" else commit
        if isinstance(target, Exception):
            raise target
        if isinstance(target, _FakeCompleted):
            return target
        return _FakeCompleted(0, str(target) + "\n")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)


def _patch_multi_gpu(monkeypatch, names: list[str]):
    props_by_idx = {
        i: SimpleNamespace(
            name=n,
            total_memory=(i + 1) * 1024**3,
            major=8,
            minor=0,
            multi_processor_count=100 + i,
        )
        for i, n in enumerate(names)
    }
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: len(names))
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda idx: props_by_idx[idx])
    monkeypatch.setattr(torch.version, "cuda", "12.8", raising=False)


def test_provenance_multi_gpu_deterministic_order(monkeypatch):
    _patch_probes(monkeypatch)
    _patch_multi_gpu(monkeypatch, ["GPU-A", "GPU-B", "GPU-C"])
    ctx = discover()
    assert ctx.visible_device_count == 3
    assert [d.logical_index for d in ctx.devices] == [0, 1, 2]
    assert [d.name for d in ctx.devices] == ["GPU-A", "GPU-B", "GPU-C"]
    assert ctx.devices[1].total_memory_bytes == 2 * 1024**3
    assert ctx.driver_version == "580.65.06"  # first line of multi-GPU output
    assert ctx.repo_commit == "a" * 40
    assert ctx.collection_errors == []


def test_provenance_cpu_only_explicit_unavailable(monkeypatch):
    _patch_probes(monkeypatch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    ctx = discover()
    assert ctx.device_available is False
    assert ctx.visible_device_count == 0
    assert ctx.devices == []
    assert ctx.driver_version is None  # not probed — no fabrication on CPU hosts
    assert ctx.platform  # stdlib facts still populated
    assert ctx.python_version


def test_provenance_nvidia_smi_missing_records_error_without_abort(monkeypatch):
    _patch_probes(monkeypatch, driver=FileNotFoundError("nvidia-smi not found"))
    _patch_multi_gpu(monkeypatch, ["GPU-A"])
    ctx = discover()  # must not raise
    assert ctx.driver_version is None
    assert any(e.startswith("driver_version:") for e in ctx.collection_errors)
    assert ctx.devices and ctx.devices[0].name == "GPU-A"  # other probes unaffected


def test_provenance_nvidia_smi_malformed_and_nonzero(monkeypatch):
    _patch_multi_gpu(monkeypatch, ["GPU-A"])
    _patch_probes(monkeypatch, driver=_FakeCompleted(0, "   \n"))
    assert discover().driver_version is None
    _patch_probes(monkeypatch, driver=_FakeCompleted(9, ""))
    ctx = discover()
    assert ctx.driver_version is None
    assert any("exit 9" in e for e in ctx.collection_errors)


def test_provenance_cuda_visible_devices_recorded(monkeypatch):
    _patch_probes(monkeypatch)
    _patch_multi_gpu(monkeypatch, ["GPU-A"])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,3")
    assert discover().cuda_visible_devices == "2,3"
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    assert discover().cuda_visible_devices is None


def test_provenance_device_probe_failure_recorded_without_abort(monkeypatch):
    _patch_probes(monkeypatch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 2)

    def flaky_props(idx):
        if idx == 1:
            raise RuntimeError("device 1 lost")
        return SimpleNamespace(
            name="GPU-A", total_memory=1024, major=1, minor=0, multi_processor_count=1
        )

    monkeypatch.setattr(torch.cuda, "get_device_properties", flaky_props)
    monkeypatch.setattr(torch.version, "cuda", "12.8", raising=False)
    ctx = discover()
    assert len(ctx.devices) == 1  # device 0 recorded, device 1 a recorded gap
    assert any(e.startswith("devices[1]:") for e in ctx.collection_errors)


def test_provenance_backward_compatible_manifest_load():
    """A pre-O1a manifest (only the original 9 fields) still validates —
    every provenance field defaults."""
    legacy = {
        "device_name": "NVIDIA GeForce RTX 5090",
        "total_memory_bytes": 32 * 1024**3,
        "compute_capability": [12, 0],
        "multiprocessor_count": 170,
        "cuda_runtime_version": "12.8",
        "torch_version": "2.10.0+cu128",
        "hostname": "old-host",
        "device_available": True,
        "discovered_at": "2026-04-23T00:00:00Z",
    }
    ctx = HardwareContext.model_validate(legacy)
    assert ctx.devices == []
    assert ctx.driver_version is None
    assert ctx.collection_errors == []
    assert ctx.platform is None


def test_provenance_serialization_round_trip(monkeypatch):
    _patch_probes(monkeypatch)
    _patch_multi_gpu(monkeypatch, ["GPU-A", "GPU-B"])
    ctx = discover()
    payload = ctx.model_dump(mode="json")
    restored = HardwareContext.model_validate(payload)
    assert restored.devices == ctx.devices
    assert restored.driver_version == ctx.driver_version
    assert restored == ctx


def test_provenance_no_secret_env_capture(monkeypatch):
    """Only CUDA_VISIBLE_DEVICES may appear from the environment — a
    sentinel secret must never leak into the serialized manifest."""
    _patch_probes(monkeypatch)
    _patch_multi_gpu(monkeypatch, ["GPU-A"])
    monkeypatch.setenv("SECRET_SENTINEL_TOKEN", "sk-THIS-MUST-NOT-APPEAR")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    import json as _json

    dump = _json.dumps(discover().model_dump(mode="json"))
    assert "sk-THIS-MUST-NOT-APPEAR" not in dump
    assert '"cuda_visible_devices": "0"' in dump
