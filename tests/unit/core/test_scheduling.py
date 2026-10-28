"""Pure scheduler witnesses (B3-1): reservation ledger, strict FIFO, refusal.

Every quantity is an explicit input; no environment, clock or device is read.
"""

from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from core.execution_calibration import RoleCeiling
from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.scheduling import (
    GpuHardwareClass,
    GpuSlot,
    HostBudget,
    Placement,
    ResourceRequest,
    host_memory_gib_from_role,
    plan_dispatch,
)

_CLASS = GpuHardwareClass(
    device_name="NVIDIA H100", total_memory_bytes=80 * 1024**3, compute_capability=(9, 0)
)


def _slot(uuid: str, ceiling_gib: float, *, quota_gib: float | None = None) -> GpuSlot:
    ceiling = ResolvedGpuCeiling(
        operator_ceiling_gib=ceiling_gib,
        operator_source="caller",
        host_quota_gib=quota_gib,
        measured_capacity_gib=80.0,
    )
    return GpuSlot(uuid=uuid, hardware_class=_CLASS, ceiling=ceiling)


def _budget(*slots: GpuSlot, memory: float = 64.0, cpus: int = 16, units: int = 8) -> HostBudget:
    return HostBudget(
        gpus=slots,
        host_memory_gib=memory,
        cpu_slots=cpus,
        max_concurrent_units=units,
        source="caller",
    )


def _gpu(unit: str, ordinal: int, vram: float, *, memory: float = 4.0) -> ResourceRequest:
    return ResourceRequest(
        unit_id=unit,
        dispatch_ordinal=ordinal,
        gpu_count=1,
        vram_gib=vram,
        vram_source="configured_cap",
        host_memory_gib=memory,
        cpu_slots=1,
        wall_seconds=600.0,
    )


def _cpu(unit: str, ordinal: int, *, memory: float = 4.0, cpus: int = 1) -> ResourceRequest:
    return ResourceRequest(
        unit_id=unit,
        dispatch_ordinal=ordinal,
        gpu_count=0,
        host_memory_gib=memory,
        cpu_slots=cpus,
        wall_seconds=60.0,
    )


def _running(budget: HostBudget, *requests: ResourceRequest) -> tuple[Placement, ...]:
    return plan_dispatch(requests, (), budget).placed


def _shape(decision) -> list[tuple[str, str, str | None]]:
    return [(p.unit_id, p.decision, p.gpu_uuid) for p in decision.placements + decision.refused]


def test_a_queued_head_is_never_overtaken_by_a_smaller_later_unit():
    """Backfill would let `small` start before `big`, changing serial order."""
    budget = _budget(_slot("GPU-a", 16.0))
    running = _running(budget, _gpu("held", 0, 8.0))
    decision = plan_dispatch((_gpu("small", 2, 2.0), _gpu("big", 1, 10.0)), running, budget)

    assert _shape(decision) == [("big", "queued", None), ("small", "queued", None)]
    assert "waiting behind earlier unit 'big'" in decision.queued[1].reasons[0]


def test_decision_is_independent_of_ready_and_running_input_order():
    """Completion timing permutes both tuples; placement must not depend on it."""
    budget = _budget(_slot("GPU-a", 12.0), _slot("GPU-b", 12.0), units=4)
    held = _running(budget, _gpu("h0", 0, 5.0), _gpu("h1", 1, 5.0), _cpu("h2", 2))
    ready = (_gpu("r3", 3, 6.0), _cpu("r4", 4), _gpu("r5", 5, 7.0), _gpu("r6", 6, 1.0))

    outcomes = {
        plan_dispatch(r, h, budget).model_dump_json()
        for r in itertools.permutations(ready)
        for h in itertools.permutations(held)
    }

    assert len(outcomes) == 1


def test_reservation_exactly_at_the_quota_bound_ceiling_is_placed():
    """Uses pair_admission's effective ceiling (quota 10 < caller 12) and its `<=`."""
    budget = _budget(_slot("GPU-a", 12.0, quota_gib=10.0))
    running = _running(budget, _gpu("held", 0, 6.0))

    at_bound = plan_dispatch((_gpu("fits", 1, 4.0),), running, budget)
    over = plan_dispatch((_gpu("over", 1, 4.5),), running, budget)

    assert _shape(at_bound) == [("fits", "placed", "GPU-a")]
    assert at_bound.placed[0].cuda_visible_devices == "GPU-a"
    assert _shape(over) == [("over", "queued", None)]


def test_running_reservation_steers_first_fit_to_the_next_declared_slot():
    """A snapshot ignoring the ledger would double-book GPU-a (the TOCTOU gap)."""
    budget = _budget(_slot("GPU-a", 10.0), _slot("GPU-b", 10.0))
    running = _running(budget, _gpu("held", 0, 7.0))
    decision = plan_dispatch((_gpu("next", 1, 7.0), _gpu("last", 2, 3.0)), running, budget)

    assert _shape(decision) == [("next", "placed", "GPU-b"), ("last", "placed", "GPU-a")]


def test_impossible_unit_is_refused_and_does_not_hold_the_line():
    """Refusal escalates instead of shrinking, and must not starve later units."""
    budget = _budget(_slot("GPU-a", 10.0), memory=32.0)
    ready = (_gpu("huge", 0, 11.0), _cpu("greedy", 1, memory=40.0), _gpu("ok", 2, 3.0))
    decision = plan_dispatch(ready, (), budget)

    assert _shape(decision) == [
        ("ok", "placed", "GPU-a"),
        ("huge", "refused", None),
        ("greedy", "refused", None),
    ]
    huge, greedy = decision.refused
    assert huge.reasons[0].startswith("escalated to operator")
    assert "largest slot ceiling is 10.00 GiB" in huge.reasons[1]
    assert "40.00 GiB host memory" in greedy.reasons[1]


def test_gpu_unit_against_a_gpu_less_budget_is_refused():
    decision = plan_dispatch((_gpu("needs", 0, 1.0),), (), _budget())
    assert _shape(decision) == [("needs", "refused", None)]


@pytest.mark.parametrize(
    ("budget_kwargs", "expected"),
    [
        ({"units": 1}, "max_concurrent_units 1 reached"),
        ({"memory": 10.0}, "6.00 GiB unreserved"),
        ({"cpus": 2}, "1 unreserved"),
    ],
)
def test_shared_host_ledger_queues_when_the_budget_is_reserved(budget_kwargs, expected):
    """Each shared dimension must count running reservations, not only the request."""
    budget = _budget(**budget_kwargs)
    running = _running(budget, _cpu("held", 0, memory=4.0))
    decision = plan_dispatch((_cpu("wait", 1, memory=8.0, cpus=2),), running, budget)

    assert _shape(decision) == [("wait", "queued", None)]
    assert expected in decision.queued[0].reasons[0]


def test_heterogeneous_or_duplicate_slots_are_refused():
    """Q3: placement must not change the LLM-visible hardware class."""
    other = GpuHardwareClass(
        device_name="NVIDIA A100", total_memory_bytes=80 * 1024**3, compute_capability=(8, 0)
    )
    mixed = GpuSlot(uuid="GPU-b", hardware_class=other, ceiling=_slot("GPU-b", 8.0).ceiling)
    with pytest.raises(ValidationError, match="heterogeneous"):
        _budget(_slot("GPU-a", 8.0), mixed)
    with pytest.raises(ValidationError, match="duplicate"):
        _budget(_slot("GPU-a", 8.0), _slot("GPU-a", 8.0))


def test_running_placement_from_another_budget_is_not_ledger_evidence():
    old = _budget(_slot("GPU-a", 10.0))
    new = _budget(_slot("GPU-a", 20.0))
    with pytest.raises(ValueError, match="another budget"):
        plan_dispatch((_gpu("next", 1, 1.0),), _running(old, _gpu("held", 0, 9.0)), new)


def test_ordinal_ties_are_refused_rather_than_broken_by_input_order():
    budget = _budget()
    with pytest.raises(ValueError, match="dispatch_ordinal"):
        plan_dispatch((_cpu("a", 0), _cpu("b", 0)), (), budget)
    with pytest.raises(ValueError, match="unit_id"):
        plan_dispatch((_cpu("a", 1),), _running(budget, _cpu("a", 0)), budget)


def test_budget_digest_tracks_schedulable_content_but_not_its_source():
    base = _budget(_slot("GPU-a", 8.0), _slot("GPU-b", 8.0))
    from_file = base.model_copy(update={"source": "file"})
    reordered = _budget(_slot("GPU-b", 8.0), _slot("GPU-a", 8.0))

    assert from_file.digest == base.digest
    assert reordered.digest != base.digest  # declared slot order decides first-fit


def test_host_memory_derives_only_from_a_declared_positive_role_cap():
    """Inherited or uncapped roles have no bound; guessing one would invent a host cap."""
    declared = RoleCeiling(role="training", gib=24, source="environment")
    assert host_memory_gib_from_role(declared) == 24.0
    for ceiling in (
        RoleCeiling(role="training"),
        RoleCeiling(role="training", gib=0, source="environment"),
    ):
        with pytest.raises(ValueError, match="no positive address-space cap"):
            host_memory_gib_from_role(ceiling)
