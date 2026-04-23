"""Unit tests for core/hardware_context.py — schema + discover().

All tests are CPU-only. We monkeypatch ``torch.cuda`` to simulate each
target device family (RTX 5090 / A100-40GB / A100-80GB / CPU-only) without
needing any of them physically present. The goal is to prove that the same
code adapts to every device — no hardcoded literals anywhere in the module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import torch

from core.hardware_context import (
    HardwareContext,
    _SAFETY_FRACTION,
    discover,
)


# ── HardwareContext schema ──────────────────────────────────────────────────

def _make_ctx(**overrides) -> HardwareContext:
    """Build a minimal valid HardwareContext for schema-level tests."""
    defaults: dict = dict(
        device_name="TEST-DEVICE",
        total_memory_bytes=32 * 1024 ** 3,  # 32 GiB
        compute_capability=(12, 0),
        multiprocessor_count=170,
        cuda_runtime_version="12.8",
        torch_version="2.10.0+cu128",
        hostname="test-host",
        device_available=True,
        discovered_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return HardwareContext(**defaults)


def test_schema_is_frozen():
    ctx = _make_ctx()
    with pytest.raises(Exception):  # pydantic raises ValidationError on frozen writes
        ctx.device_name = "CHANGED"


def test_usable_cap_bytes_is_exactly_safety_fraction_of_total():
    total = 32 * 1024 ** 3
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
        total = total_gib * 1024 ** 3
        ctx = _make_ctx(total_memory_bytes=total)
        assert ctx.usable_cap_bytes == int(0.80 * total)
        assert ctx.usable_cap_gb == pytest.approx(0.80 * total_gib, rel=1e-9)


def test_total_memory_gb_conversion():
    ctx = _make_ctx(total_memory_bytes=32 * 1024 ** 3)
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

def _patch_cuda_available(monkeypatch, *, available: bool, props=None, runtime: str | None = "12.8"):
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
        total_memory=32 * 1024 ** 3,
        major=12, minor=0,
        multi_processor_count=170,
    )
    _patch_cuda_available(monkeypatch, available=True, props=props, runtime="12.8")
    ctx = discover()
    assert ctx.device_available is True
    assert ctx.device_name == "NVIDIA GeForce RTX 5090"
    assert ctx.total_memory_bytes == 32 * 1024 ** 3
    assert ctx.compute_capability == (12, 0)
    assert ctx.multiprocessor_count == 170
    assert ctx.cuda_runtime_version == "12.8"
    assert ctx.usable_cap_bytes == int(0.80 * 32 * 1024 ** 3)


def test_discover_on_fake_a100_40gb_same_code(monkeypatch):
    """Principle 5: the same code adapts to SDSC Expanse A100-40GB."""
    props = SimpleNamespace(
        name="NVIDIA A100-SXM4-40GB",
        total_memory=40 * 1024 ** 3,
        major=8, minor=0,
        multi_processor_count=108,
    )
    _patch_cuda_available(monkeypatch, available=True, props=props, runtime="11.8")
    ctx = discover()
    assert ctx.device_name == "NVIDIA A100-SXM4-40GB"
    assert ctx.total_memory_bytes == 40 * 1024 ** 3
    assert ctx.usable_cap_gb == pytest.approx(32.0, rel=1e-9)


def test_discover_on_fake_a100_80gb_same_code(monkeypatch):
    """Principle 5: same code, 80-GiB cap."""
    props = SimpleNamespace(
        name="NVIDIA A100-SXM4-80GB",
        total_memory=80 * 1024 ** 3,
        major=8, minor=0,
        multi_processor_count=108,
    )
    _patch_cuda_available(monkeypatch, available=True, props=props, runtime="11.8")
    ctx = discover()
    assert ctx.total_memory_bytes == 80 * 1024 ** 3
    assert ctx.usable_cap_gb == pytest.approx(64.0, rel=1e-9)


def test_discover_timestamp_is_fresh(monkeypatch):
    """discovered_at must be UTC-aware and within the last second."""
    props = SimpleNamespace(
        name="fake", total_memory=1024,
        major=1, minor=0, multi_processor_count=1,
    )
    _patch_cuda_available(monkeypatch, available=True, props=props)
    before = datetime.now(timezone.utc)
    ctx = discover()
    after = datetime.now(timezone.utc)
    assert before <= ctx.discovered_at <= after
