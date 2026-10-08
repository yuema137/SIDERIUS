"""Installed backend facts must not imply runtime readiness or invent identity."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import core.hardware_context as hardware
from core.runtime_control.gpu_accounting import device_identity_from_hardware


def forbidden(*args, **kwargs):
    raise AssertionError("unexpected hardware effect")


@pytest.fixture
def environment(monkeypatch):
    """No real property, subprocess, allocation or manifest access is allowed."""
    props = SimpleNamespace(
        name="Unlisted accelerator",
        total_memory=96 * 1024**3,
        major=9,
        minor=0,
        multi_processor_count=128,
        uuid="abcd-1234",
    )
    monkeypatch.setattr(hardware.torch.version, "cuda", "12.8")
    monkeypatch.setattr(hardware.torch.version, "hip", None)
    monkeypatch.setattr(hardware.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(hardware.torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(hardware.torch.cuda, "get_device_properties", lambda index: props)
    monkeypatch.setattr(hardware, "_probe_repo_commit", lambda errors: "a" * 40)
    monkeypatch.setattr(hardware, "_physical_index_by_uuid", lambda errors: {"GPU-abcd-1234": 2})
    monkeypatch.setattr(hardware, "_probe_driver_version", lambda errors: "example-driver")
    monkeypatch.setattr(hardware.subprocess, "run", forbidden)
    monkeypatch.setattr(hardware.torch, "empty", forbidden)
    monkeypatch.setattr(hardware.torch.cuda, "synchronize", forbidden)
    monkeypatch.setattr(hardware, "write_manifest", forbidden)
    monkeypatch.setattr(hardware, "load_manifest", forbidden)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2")
    return props


def test_unlisted_cuda_device_uses_logical_visibility_without_claiming_readiness(environment):
    facts = hardware.inspect_gpu_runtime()
    assert facts.installed_backend == "cuda"
    assert facts.runtime_version == "12.8"
    assert facts.implemented_accounting_adapter == "nvidia-smi"
    assert facts.hardware.device_name == "Unlisted accelerator"
    assert facts.hardware.total_memory_bytes == 96 * 1024**3
    assert facts.hardware.visible_device_count == 1
    assert facts.hardware.devices[0].physical_index == 2
    assert facts.hardware.devices[0].logical_index == 0
    assert facts.hardware.active_device_uuid == "GPU-abcd-1234"
    assert facts.hardware.cuda_visible_devices == "2"
    assert facts.limitations == ()


def test_installed_cuda_without_access_does_not_become_a_cpu_permission(monkeypatch, environment):
    monkeypatch.setattr(hardware.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(hardware.torch.cuda, "get_device_properties", forbidden)
    facts = hardware.inspect_gpu_runtime()
    assert facts.installed_backend == "cuda"
    assert facts.implemented_accounting_adapter == "nvidia-smi"
    assert not facts.hardware.device_available
    assert facts.hardware.visible_device_count == 0
    assert facts.hardware.active_device_uuid is None


@pytest.mark.parametrize("cuda_version", [None, "12.8"])
def test_rocm_never_queries_or_fabricates_nvidia_identity(monkeypatch, environment, cuda_version):
    monkeypatch.setattr(hardware.torch.version, "hip", "7.1")
    monkeypatch.setattr(hardware.torch.version, "cuda", cuda_version)
    monkeypatch.setattr(hardware, "_physical_index_by_uuid", forbidden)
    monkeypatch.setattr(hardware, "_probe_driver_version", forbidden)
    monkeypatch.setattr(hardware, "_normalize_uuid", forbidden)
    facts = hardware.inspect_gpu_runtime()
    assert facts.installed_backend == "rocm"
    assert facts.runtime_version == "7.1"
    assert facts.implemented_accounting_adapter is None
    assert facts.hardware.device_available
    assert facts.hardware.active_device_uuid is None
    assert facts.hardware.devices[0].uuid is None
    assert facts.hardware.devices[0].physical_index is None
    assert facts.hardware.driver_version is None
    assert device_identity_from_hardware(facts.hardware) is None
    assert any("driver_identity" in error for error in facts.hardware.collection_errors)
    assert any("not been hardware-tested" in text for text in facts.limitations)
    assert any("not implemented" in text for text in facts.limitations)


def test_no_gpu_backend_does_not_probe_driver_or_infer_physical_hardware(monkeypatch, environment):
    monkeypatch.setattr(hardware.torch.version, "cuda", None)
    monkeypatch.setattr(hardware.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(hardware, "_physical_index_by_uuid", forbidden)
    monkeypatch.setattr(hardware, "_probe_driver_version", forbidden)
    facts = hardware.inspect_gpu_runtime()
    assert facts.installed_backend == "none"
    assert facts.runtime_version is None
    assert facts.implemented_accounting_adapter is None
    assert not facts.hardware.device_available
    assert facts.hardware.collection_errors == []


def test_failed_properties_cannot_become_a_successful_runtime_report(monkeypatch, environment):
    def unavailable(index):
        raise RuntimeError("device query failed")

    monkeypatch.setattr(hardware.torch.cuda, "get_device_properties", unavailable)
    with pytest.raises(RuntimeError, match="device query failed"):
        hardware.inspect_gpu_runtime()


def test_report_uses_fresh_discovery_instead_of_cached_workspace_identity(monkeypatch, environment):
    monkeypatch.setattr(hardware, "get_or_create", forbidden)
    first = hardware.inspect_gpu_runtime()
    environment.uuid = None
    second = hardware.inspect_gpu_runtime()
    assert first.hardware.active_device_uuid == "GPU-abcd-1234"
    assert second.hardware.active_device_uuid is None
    assert second.hardware.hardware_fingerprint_version == 1


def test_cuda_discovery_keeps_legacy_serialized_payload(monkeypatch, environment):
    class FixedTime:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 8, tzinfo=UTC)

    monkeypatch.setattr(hardware, "datetime", FixedTime)
    monkeypatch.setattr(hardware.socket, "gethostname", lambda: "portable-host")
    monkeypatch.setattr(hardware._platform_mod, "platform", lambda: "synthetic-platform")
    monkeypatch.setattr(hardware.sys, "version", "3.12.13 synthetic")
    monkeypatch.setattr(hardware.torch, "__version__", "2.10.0+cu128")
    # Complete legacy payload, fixed independently of the model's field/default table.
    assert hardware.discover().model_dump(mode="json") == {
        "device_name": "Unlisted accelerator",
        "total_memory_bytes": 103079215104,
        "compute_capability": [9, 0],
        "multiprocessor_count": 128,
        "cuda_runtime_version": "12.8",
        "torch_version": "2.10.0+cu128",
        "hostname": "portable-host",
        "device_available": True,
        "discovered_at": "2026-10-08T00:00:00Z",
        "platform": "synthetic-platform",
        "python_version": "3.12.13",
        "cuda_visible_devices": "2",
        "visible_device_count": 1,
        "devices": [
            {
                "logical_index": 0,
                "name": "Unlisted accelerator",
                "total_memory_bytes": 103079215104,
                "compute_capability": [9, 0],
                "uuid": "GPU-abcd-1234",
                "physical_index": 2,
            }
        ],
        "active_device_uuid": "GPU-abcd-1234",
        "hardware_fingerprint_version": 2,
        "driver_version": "example-driver",
        "repo_commit": "a" * 40,
        "collection_errors": [],
    }
