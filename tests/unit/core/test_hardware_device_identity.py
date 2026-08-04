"""V20 B-C2b / FU-A-13 — device identity, versioned and backward compatible.

The identity primary key is the GPU UUID, because a device name is not
one: two cards of the same model are indistinguishable by it, and a
measurement attributed to the wrong card would look perfectly valid.

Old manifests have no UUID. They must stay readable and must not fail a
resume — so the fingerprint is versioned rather than replaced in place.
"""

from __future__ import annotations

import json

import pytest

from core.hardware_context import (
    GpuDeviceProvenance,
    HardwareContext,
    _normalize_uuid,
    _physical_index_by_uuid,
    load_manifest,
    write_manifest,
)
from core.runtime_control.gpu_accounting import device_identity_from_hardware

UUID_A = "GPU-aaaaaaaa-0000-0000-0000-000000000000"
UUID_B = "GPU-bbbbbbbb-1111-1111-1111-111111111111"


def _ctx(**over) -> HardwareContext:
    from datetime import UTC, datetime

    base = dict(
        device_name="NVIDIA Test 9000",
        total_memory_bytes=32 * 1024**3,
        compute_capability=(9, 0),
        multiprocessor_count=100,
        torch_version="2.0",
        hostname="testhost",
        device_available=True,
        discovered_at=datetime.now(UTC),
    )
    base.update(over)
    return HardwareContext(**base)


class TestUuidNormalisation:
    def test_torch_and_driver_forms_compare_equal(self):
        """torch reports bare hex, nvidia-smi prefixes it. Without
        normalising, the two sources would never match and the physical
        index would always be unknown."""
        assert _normalize_uuid("c30b-dead") == _normalize_uuid("GPU-c30b-dead")

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_absent_uuid_stays_absent(self, raw):
        assert _normalize_uuid(raw) is None

    def test_mig_uuids_are_not_reprefixed(self):
        assert _normalize_uuid("MIG-abc") == "MIG-abc"


class TestPhysicalIndexMapping:
    def test_the_map_is_built_by_uuid_not_by_order(self):
        """Under CUDA_VISIBLE_DEVICES the logical order is a subset in a
        different order; only the UUID relates the two."""

        class _R:
            stdout = f"0, {UUID_A}\n1, {UUID_B}\n"

        errors: list[str] = []
        import core.hardware_context as hc

        real = hc.subprocess.run
        hc.subprocess.run = lambda *_a, **_k: _R()
        try:
            mapping = _physical_index_by_uuid(errors)
        finally:
            hc.subprocess.run = real
        assert mapping == {UUID_A: 0, UUID_B: 1}
        assert errors == []

    def test_a_driver_failure_is_a_recorded_gap_not_an_abort(self):
        import core.hardware_context as hc

        errors: list[str] = []
        real = hc.subprocess.run

        def _boom(*_a, **_k):
            raise OSError("nvidia-smi missing")

        hc.subprocess.run = _boom
        try:
            assert _physical_index_by_uuid(errors) == {}
        finally:
            hc.subprocess.run = real
        assert errors and "physical_index_map" in errors[0]


class TestFingerprintVersioning:
    def test_legacy_records_default_to_v1(self):
        """Old manifests have no UUID, so they cannot claim v2 identity."""
        ctx = _ctx()
        assert ctx.hardware_fingerprint_version == 1
        assert ctx.active_device_uuid is None

    def test_uuid_bearing_records_are_v2(self):
        ctx = _ctx(active_device_uuid=UUID_A, hardware_fingerprint_version=2)
        assert ctx.hardware_fingerprint_version == 2


class TestBackwardCompatibleManifests:
    def test_a_manifest_without_the_new_fields_still_loads(self, tmp_path):
        """The persisted file is parent-child IPC. A manifest written
        before UUIDs existed must keep loading, or every existing
        workspace breaks."""
        legacy = {
            "device_name": "NVIDIA Old 1000",
            "total_memory_bytes": 8 * 1024**3,
            "compute_capability": [7, 0],
            "multiprocessor_count": 40,
            "torch_version": "1.13",
            "hostname": "oldhost",
            "device_available": True,
            "discovered_at": "2026-01-01T00:00:00Z",
        }
        path = tmp_path / "legacy_hardware.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        ctx = load_manifest(path)
        assert ctx.device_name == "NVIDIA Old 1000"
        assert ctx.active_device_uuid is None
        assert ctx.hardware_fingerprint_version == 1

    def test_round_trip_preserves_identity(self, tmp_path):
        ctx = _ctx(
            active_device_uuid=UUID_A,
            hardware_fingerprint_version=2,
            devices=[
                GpuDeviceProvenance(
                    logical_index=0,
                    name="NVIDIA Test 9000",
                    total_memory_bytes=32 * 1024**3,
                    compute_capability=(9, 0),
                    uuid=UUID_A,
                    physical_index=3,
                )
            ],
        )
        path = tmp_path / "r_hardware.json"
        write_manifest(ctx, path)
        back = load_manifest(path)
        assert back.active_device_uuid == UUID_A
        assert back.devices[0].physical_index == 3


class TestAdapter:
    def test_it_resolves_a_full_identity(self):
        ctx = _ctx(
            active_device_uuid=UUID_A,
            hardware_fingerprint_version=2,
            cuda_visible_devices="2",
            devices=[
                GpuDeviceProvenance(
                    logical_index=0,
                    name="NVIDIA Test 9000",
                    total_memory_bytes=1,
                    compute_capability=(9, 0),
                    uuid=UUID_A,
                    physical_index=2,
                )
            ],
        )
        ident = device_identity_from_hardware(ctx)
        assert ident is not None
        assert ident.uuid == UUID_A
        assert ident.physical_index == 2
        assert ident.logical_index == 0
        assert ident.cuda_visible_devices == "2"

    def test_a_legacy_record_yields_none_not_a_guess(self):
        """Degraded identity is never repaired by guessing. Filling in
        device 0 or keying on the name would conflate two cards of the
        same model."""
        assert device_identity_from_hardware(_ctx()) is None

    def test_a_cpu_only_record_yields_none(self):
        assert device_identity_from_hardware(_ctx(device_available=False)) is None

    def test_same_name_different_uuid_are_different_devices(self):
        """The whole reason the name is not the key."""
        a = device_identity_from_hardware(
            _ctx(active_device_uuid=UUID_A, hardware_fingerprint_version=2)
        )
        b = device_identity_from_hardware(
            _ctx(active_device_uuid=UUID_B, hardware_fingerprint_version=2)
        )
        assert a is not None and b is not None
        assert a.uuid != b.uuid

    def test_it_is_the_only_translation_point(self):
        """A second identity schema is what this adapter exists to
        prevent; assert no rival constructor appeared.

        Checked over the AST rather than the text. The substring form
        flagged a module whose only mention of the constructor was a
        docstring explaining why it does NOT call it -- a scan cannot tell
        an explanation from an instruction, and a guardrail that cries wolf
        on prose is one somebody eventually exempts. The AST sees calls
        only, so the property enforced is exactly the one stated.
        """
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        rivals = []
        for path in (root / "core").rglob("*.py"):
            if path.name == "gpu_accounting.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                called = isinstance(node, ast.Call) and (
                    (isinstance(node.func, ast.Name) and node.func.id == "DeviceIdentity")
                    or (isinstance(node.func, ast.Attribute) and node.func.attr == "DeviceIdentity")
                )
                if called:
                    rivals.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
        assert not rivals, f"DeviceIdentity constructed outside the adapter: {rivals}"
