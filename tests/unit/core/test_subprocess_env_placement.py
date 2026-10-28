"""B3-2: a scheduler placement reaches the child only through ``subprocess_env``.

Without a placement the child environment must be exactly what it was before
placement existed; with one, only the device selector changes.
"""

from __future__ import annotations

import pytest

from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.scheduling import (
    GpuHardwareClass,
    GpuSlot,
    HostBudget,
    ResourceRequest,
    plan_dispatch,
)
from core.subprocess_env import CUDA_VISIBLE_DEVICES_ENV_VAR, subprocess_env

_UUID = "GPU-0a1b2c3d"


@pytest.mark.parametrize("inherited", [None, "1"], ids=["unset", "inherited"])
def test_no_placement_leaves_the_selector_as_inherited(monkeypatch, inherited):
    """Fails if an absent placement writes a selector (e.g. ``""``), which
    would hide every GPU from every existing serial child."""
    if inherited is None:
        monkeypatch.delenv(CUDA_VISIBLE_DEVICES_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(CUDA_VISIBLE_DEVICES_ENV_VAR, inherited)
    assert subprocess_env().get(CUDA_VISIBLE_DEVICES_ENV_VAR) == inherited


def test_placement_changes_only_the_device_selector(monkeypatch):
    """Parity: a placed child differs from an unplaced one in exactly one key."""
    monkeypatch.setenv(CUDA_VISIBLE_DEVICES_ENV_VAR, "0,1")
    unplaced = subprocess_env()
    placed = subprocess_env(cuda_visible_devices=_UUID)
    assert placed[CUDA_VISIBLE_DEVICES_ENV_VAR] == _UUID
    assert {k: v for k, v in placed.items() if k != CUDA_VISIBLE_DEVICES_ENV_VAR} == {
        k: v for k, v in unplaced.items() if k != CUDA_VISIBLE_DEVICES_ENV_VAR
    }


def test_a_placed_cpu_unit_hides_every_inherited_gpu(monkeypatch):
    """The scheduler reserved no VRAM for a CPU unit. A truthiness check on
    the selector would drop its ``""`` and leak the parent's GPUs."""
    monkeypatch.setenv(CUDA_VISIBLE_DEVICES_ENV_VAR, "0")
    slot = GpuSlot(
        uuid=_UUID,
        hardware_class=GpuHardwareClass(
            device_name="synthetic-accelerator",
            total_memory_bytes=48 * 1024**3,
            compute_capability=(8, 9),
        ),
        ceiling=ResolvedGpuCeiling(
            operator_ceiling_gib=40.0,
            operator_source="caller",
            host_quota_gib=None,
            measured_capacity_gib=47.5,
        ),
    )
    budget = HostBudget(
        gpus=(slot,), host_memory_gib=16.0, cpu_slots=4, max_concurrent_units=2, source="caller"
    )
    request = ResourceRequest(
        unit_id="validator",
        dispatch_ordinal=0,
        gpu_count=0,
        host_memory_gib=2.0,
        cpu_slots=1,
        wall_seconds=60.0,
    )
    (placement,) = plan_dispatch((request,), (), budget, on_refusal="halt").placed
    env = subprocess_env(cuda_visible_devices=placement.cuda_visible_devices)
    assert env[CUDA_VISIBLE_DEVICES_ENV_VAR] == ""
