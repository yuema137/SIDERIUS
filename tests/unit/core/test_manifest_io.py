"""Unit tests for core/hardware_context.py manifest I/O + get_or_create lifecycle.

Uses ``tmp_path`` for filesystem isolation and monkeypatches ``discover``
wherever we need a deterministic ctx without touching real hardware.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import core.hardware_context as hc
from core.hardware_context import (
    HardwareContext,
    get_or_create,
    load_manifest,
    write_manifest,
)


def _ctx(
    device_name: str = "NVIDIA GeForce RTX 5090",
    hostname: str = "ligroup",
    total_memory_bytes: int = 32 * 1024 ** 3,
) -> HardwareContext:
    return HardwareContext(
        device_name=device_name,
        total_memory_bytes=total_memory_bytes,
        compute_capability=(12, 0),
        multiprocessor_count=170,
        cuda_runtime_version="12.8",
        torch_version="2.10.0+cu128",
        hostname=hostname,
        device_available=True,
        discovered_at=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
    )


# ── write/load round-trip ───────────────────────────────────────────────────

def test_write_manifest_creates_parents(tmp_path):
    ctx = _ctx()
    path = tmp_path / "deep" / "nested" / "run_hardware.json"
    write_manifest(ctx, path)
    assert path.exists()
    assert path.parent.is_dir()


def test_write_manifest_is_valid_json(tmp_path):
    ctx = _ctx()
    path = tmp_path / "hw.json"
    write_manifest(ctx, path)
    raw = json.loads(path.read_text())
    assert raw["device_name"] == "NVIDIA GeForce RTX 5090"
    assert raw["total_memory_bytes"] == 32 * 1024 ** 3
    assert raw["compute_capability"] == [12, 0]  # tuple → JSON list
    assert isinstance(raw["discovered_at"], str)  # ISO-8601


def test_write_manifest_trailing_newline(tmp_path):
    """Trailing newline keeps `git diff` + POSIX-tooling happy."""
    ctx = _ctx()
    path = tmp_path / "hw.json"
    write_manifest(ctx, path)
    assert path.read_text().endswith("\n")


def test_load_manifest_roundtrip_preserves_all_fields(tmp_path):
    original = _ctx()
    path = tmp_path / "hw.json"
    write_manifest(original, path)
    loaded = load_manifest(path)
    assert loaded == original  # Pydantic equality covers every field
    # Tuple is preserved (not converted to list) after round-trip:
    assert isinstance(loaded.compute_capability, tuple)
    assert loaded.compute_capability == (12, 0)


def test_load_manifest_raises_on_missing_fields(tmp_path):
    """Corrupt manifests must surface as ValidationError — get_or_create is
    the only caller allowed to swallow this."""
    path = tmp_path / "hw.json"
    path.write_text(json.dumps({"device_name": "only-this-field"}))
    with pytest.raises(Exception):  # pydantic ValidationError
        load_manifest(path)


# ── get_or_create lifecycle ─────────────────────────────────────────────────

def test_get_or_create_creates_missing_manifest(tmp_path, monkeypatch):
    fresh = _ctx()
    monkeypatch.setattr(hc, "discover", lambda: fresh)

    result = get_or_create(tmp_path, "run_alpha")

    expected_path = tmp_path / "run_alpha_hardware.json"
    assert expected_path.exists()
    assert result == fresh


def test_get_or_create_reuses_matching_manifest_without_rewrite(tmp_path, monkeypatch):
    """On match, the stored manifest is returned verbatim and the file is
    NOT rewritten (preserves original ``discovered_at``)."""
    stored = _ctx()
    path = tmp_path / "run_beta_hardware.json"
    write_manifest(stored, path)
    mtime_before = path.stat().st_mtime_ns

    # discover returns a DIFFERENT ctx with the same device+host identity —
    # the timestamp differs, but get_or_create must prefer the stored one.
    fresh = _ctx()  # same identity, semantically equal to stored
    monkeypatch.setattr(hc, "discover", lambda: fresh)

    result = get_or_create(tmp_path, "run_beta")

    assert result == stored
    assert path.stat().st_mtime_ns == mtime_before, (
        "Manifest was rewritten on a matching identity — get_or_create must "
        "skip the write to avoid churning discovered_at on every run."
    )


def test_get_or_create_regenerates_on_device_mismatch(tmp_path, monkeypatch, caplog):
    """Workspace moved from lilab RTX 5090 to SDSC A100 — manifest must
    regenerate, not silently keep the stale ceiling."""
    stored = _ctx(device_name="NVIDIA GeForce RTX 5090", hostname="ligroup")
    path = tmp_path / "run_gamma_hardware.json"
    write_manifest(stored, path)

    fresh = _ctx(
        device_name="NVIDIA A100-SXM4-80GB",
        hostname="expanse-09",
        total_memory_bytes=80 * 1024 ** 3,
    )
    monkeypatch.setattr(hc, "discover", lambda: fresh)

    with caplog.at_level("WARNING", logger="core.hardware_context"):
        result = get_or_create(tmp_path, "run_gamma")

    assert result.device_name == "NVIDIA A100-SXM4-80GB"
    assert result.hostname == "expanse-09"
    # File on disk must reflect the fresh ctx now:
    assert load_manifest(path) == fresh
    assert any("regenerating" in rec.message.lower() or
               "regenerating" in rec.message for rec in caplog.records)


def test_get_or_create_regenerates_on_hostname_mismatch(tmp_path, monkeypatch):
    """Same GPU model, different host — still treat as a different environment."""
    stored = _ctx(device_name="NVIDIA A100-SXM4-40GB", hostname="expanse-09")
    path = tmp_path / "run_delta_hardware.json"
    write_manifest(stored, path)

    fresh = _ctx(device_name="NVIDIA A100-SXM4-40GB", hostname="expanse-17")
    monkeypatch.setattr(hc, "discover", lambda: fresh)

    result = get_or_create(tmp_path, "run_delta")
    assert result.hostname == "expanse-17"


def test_get_or_create_regenerates_on_corrupt_manifest(tmp_path, monkeypatch, caplog):
    """Partial or invalid JSON must not crash the run — regenerate from
    fresh discover() and log the recovery."""
    path = tmp_path / "run_eps_hardware.json"
    path.write_text("{ this is not json ")

    fresh = _ctx()
    monkeypatch.setattr(hc, "discover", lambda: fresh)

    with caplog.at_level("WARNING", logger="core.hardware_context"):
        result = get_or_create(tmp_path, "run_eps")

    assert result == fresh
    assert load_manifest(path) == fresh


def test_get_or_create_regenerates_on_schema_mismatch(tmp_path, monkeypatch):
    """Old-schema manifest (missing fields) triggers the same recovery path
    as corruption — the stored file is silently replaced."""
    path = tmp_path / "run_zeta_hardware.json"
    path.write_text(json.dumps({"device_name": "stale", "hostname": "old"}))

    fresh = _ctx()
    monkeypatch.setattr(hc, "discover", lambda: fresh)

    result = get_or_create(tmp_path, "run_zeta")
    assert result == fresh
