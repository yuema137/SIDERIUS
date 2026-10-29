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
    return plan_dispatch(requests, (), budget, on_refusal="continue").placed


def _shape(decision) -> list[tuple[str, str, str | None]]:
    return [(p.unit_id, p.decision, p.gpu_uuid) for p in decision.placements + decision.refused]


def test_a_queued_head_is_never_overtaken_by_a_smaller_later_unit():
    """Backfill would let `small` start before `big`, changing serial order."""
    budget = _budget(_slot("GPU-a", 16.0))
    running = _running(budget, _gpu("held", 0, 8.0))
    decision = plan_dispatch(
        (_gpu("small", 2, 2.0), _gpu("big", 1, 10.0)), running, budget, on_refusal="continue"
    )

    assert _shape(decision) == [("big", "queued", None), ("small", "queued", None)]
    assert "waiting behind earlier unit 'big'" in decision.queued[1].reasons[0]


def test_decision_is_independent_of_ready_and_running_input_order():
    """Completion timing permutes both tuples; placement must not depend on it."""
    budget = _budget(_slot("GPU-a", 12.0), _slot("GPU-b", 12.0), units=4)
    held = _running(budget, _gpu("h0", 0, 5.0), _gpu("h1", 1, 5.0), _cpu("h2", 2))
    ready = (_gpu("r3", 3, 6.0), _cpu("r4", 4), _gpu("r5", 5, 7.0), _gpu("r6", 6, 1.0))

    outcomes = {
        plan_dispatch(r, h, budget, on_refusal="continue").model_dump_json()
        for r in itertools.permutations(ready)
        for h in itertools.permutations(held)
    }

    assert len(outcomes) == 1


def test_reservation_exactly_at_the_quota_bound_ceiling_is_placed():
    """Uses pair_admission's effective ceiling (quota 10 < caller 12) and its `<=`."""
    budget = _budget(_slot("GPU-a", 12.0, quota_gib=10.0))
    running = _running(budget, _gpu("held", 0, 6.0))

    at_bound = plan_dispatch((_gpu("fits", 1, 4.0),), running, budget, on_refusal="continue")
    over = plan_dispatch((_gpu("over", 1, 4.5),), running, budget, on_refusal="continue")

    assert _shape(at_bound) == [("fits", "placed", "GPU-a")]
    assert at_bound.placed[0].cuda_visible_devices == "GPU-a"
    assert _shape(over) == [("over", "queued", None)]


def test_running_reservation_steers_first_fit_to_the_next_declared_slot():
    """A snapshot ignoring the ledger would double-book GPU-a (the TOCTOU gap)."""
    budget = _budget(_slot("GPU-a", 10.0), _slot("GPU-b", 10.0))
    running = _running(budget, _gpu("held", 0, 7.0))
    decision = plan_dispatch(
        (_gpu("next", 1, 7.0), _gpu("last", 2, 3.0)), running, budget, on_refusal="continue"
    )

    assert _shape(decision) == [("next", "placed", "GPU-b"), ("last", "placed", "GPU-a")]


def test_continue_policy_refuses_the_impossible_unit_without_holding_the_line():
    """Cross-operation mode: refusal escalates instead of shrinking, never starves others."""
    budget = _budget(_slot("GPU-a", 10.0), memory=32.0)
    ready = (_gpu("huge", 0, 11.0), _cpu("greedy", 1, memory=40.0), _gpu("ok", 2, 3.0))
    decision = plan_dispatch(ready, (), budget, on_refusal="continue")

    assert _shape(decision) == [
        ("ok", "placed", "GPU-a"),
        ("huge", "refused", None),
        ("greedy", "refused", None),
    ]
    huge, greedy = decision.refused
    assert huge.reasons[0].startswith("escalated to operator")
    assert "largest slot ceiling is 10.00 GiB" in huge.reasons[1]
    assert "40.00 GiB host memory" in greedy.reasons[1]


def test_halt_policy_places_nothing_once_any_unit_is_refused():
    """Graph-mode serial reference: a refusal aborts the body before any effect."""
    budget = _budget(_slot("GPU-a", 10.0))
    ready = (_cpu("first", 0), _gpu("huge", 1, 11.0), _gpu("later", 2, 3.0))
    decision = plan_dispatch(ready, (), budget, on_refusal="halt")

    assert decision.placements == ()
    assert _shape(decision) == [("huge", "refused", None)]


def test_gpu_unit_against_a_gpu_less_budget_is_refused():
    decision = plan_dispatch((_gpu("needs", 0, 1.0),), (), _budget(), on_refusal="continue")
    assert _shape(decision) == [("needs", "refused", None)]
    assert decision.refused[0].reasons[1] == "needs one GPU; budget declares no GPU slots"


def test_vram_refusal_uses_the_quota_bound_ceiling_not_the_caller_ceiling():
    """Quota 10 GiB constrains a 12 GiB caller ceiling; 11 GiB can never fit."""
    budget = _budget(_slot("GPU-a", 12.0, quota_gib=10.0))
    decision = plan_dispatch((_gpu("big", 0, 11.0),), (), budget, on_refusal="continue")

    assert _shape(decision) == [("big", "refused", None)]
    assert "largest slot ceiling is 10.00 GiB (short by 1 GiB)" in decision.refused[0].reasons[1]


def test_near_boundary_queue_reason_states_the_exact_shortfall():
    """Two-decimal rounding alone would print 'needs 4.00; 4.00 unreserved'."""
    budget = _budget(_slot("GPU-a", 10.0), memory=8.0)
    running = _running(budget, _gpu("held", 0, 6.0))
    ready = (_gpu("vram", 1, 4.001), _cpu("mem", 2, memory=4.001))
    vram = plan_dispatch(ready[:1], running, budget, on_refusal="continue")
    memory = plan_dispatch(ready[1:], running, budget, on_refusal="continue")

    assert "GPU-a: 4.00 GiB unreserved (short by 0.001 GiB)" in vram.queued[0].reasons[0]
    assert "(short by 0.001 GiB)" in memory.queued[0].reasons[0]


def test_placed_cpu_unit_hides_gpus_and_unplaced_units_select_nothing():
    """A CPU child seeing every GPU could allocate VRAM the ledger never reserved."""
    budget = _budget(_slot("GPU-a", 10.0), units=1)
    decision = plan_dispatch((_cpu("cpu", 0), _cpu("next", 1)), (), budget, on_refusal="continue")

    placed, queued = decision.placements
    assert (placed.decision, placed.cuda_visible_devices) == ("placed", "")
    assert (queued.decision, queued.cuda_visible_devices) == ("queued", None)


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
    decision = plan_dispatch(
        (_cpu("wait", 1, memory=8.0, cpus=2),), running, budget, on_refusal="continue"
    )

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
        plan_dispatch(
            (_gpu("next", 1, 1.0),), _running(old, _gpu("held", 0, 9.0)), new, on_refusal="continue"
        )


def test_ordinal_ties_are_refused_rather_than_broken_by_input_order():
    budget = _budget()
    with pytest.raises(ValueError, match="dispatch_ordinal"):
        plan_dispatch((_cpu("a", 0), _cpu("b", 0)), (), budget, on_refusal="continue")
    with pytest.raises(ValueError, match="unit_id"):
        plan_dispatch(
            (_cpu("a", 1),), _running(budget, _cpu("a", 0)), budget, on_refusal="continue"
        )


def test_budget_digest_tracks_schedulable_content_but_not_its_source():
    base = _budget(_slot("GPU-a", 8.0), _slot("GPU-b", 8.0))
    from_file = base.model_copy(update={"source": "file"})
    reordered = _budget(_slot("GPU-b", 8.0), _slot("GPU-a", 8.0))

    assert from_file.digest == base.digest
    assert reordered.digest != base.digest  # declared slot order decides first-fit


def test_shared_gpu_acknowledgment_leaves_existing_budget_digests_unchanged():
    """B3-Q6 field: a budget that does not set it keeps its pre-B3-5 digest.

    The literal was computed from the B3-2 revision (a5028bc3) before the field
    existed; serializing ``false`` would change every recorded budget digest.
    """
    budget = _budget(_slot("GPU-aaaa", 40.0), units=8)
    assert budget.digest == "d102373eb72f3b9f5a0aa69fb4fba431bab66157e9934759d3d01acf933d1f9d"
    acknowledged = budget.model_copy(update={"acknowledge_shared_gpu_time_budget": True})
    assert acknowledged.digest != budget.digest


def test_time_budgeted_unit_takes_an_unshared_slot_and_queues_only_when_none_is_free():
    """Decision B3-Q6 is a placement constraint (#1019), not a post-placement veto.

    Contention on a shared GPU changes measured-time admission, so a time-budgeted
    unit (or a unit joining one) must not share a slot unless acknowledged. A rule
    applied after first-fit would refuse ``timed`` although ``GPU-b`` is idle.
    """
    budget = _budget(_slot("GPU-a", 16.0), _slot("GPU-b", 16.0))
    timed = _gpu("timed", 1, 2.0).model_copy(update={"time_budgeted": True})
    held = _running(budget, _gpu("held", 0, 2.0))

    decision = plan_dispatch((timed,), held, budget, on_refusal="continue")
    assert _shape(decision) == [("timed", "placed", "GPU-b")]

    # `other` does not fit beside `held` on GPU-a, so first-fit puts it on GPU-b.
    both_held = _running(budget, _gpu("held", 0, 2.0), _gpu("other", 2, 15.0))
    assert {p.gpu_uuid for p in both_held} == {"GPU-a", "GPU-b"}
    queued = plan_dispatch((timed,), both_held, budget, on_refusal="continue").placements[0]
    assert queued.decision == "queued"
    assert "time-budgeted unit would share it" in queued.reasons[0]

    # Either side counts: a plain unit may not join a time-budgeted one.
    timed_held = plan_dispatch((timed,), (), budget, on_refusal="continue").placed
    joining = plan_dispatch((_gpu("plain", 3, 2.0),), timed_held, budget, on_refusal="continue")
    assert _shape(joining) == [("plain", "placed", "GPU-b")]

    acknowledged = budget.model_copy(update={"acknowledge_shared_gpu_time_budget": True})
    shared = plan_dispatch(
        (timed,),
        _running(acknowledged, _gpu("held", 0, 2.0)),
        acknowledged,
        on_refusal="continue",
    )
    assert _shape(shared) == [("timed", "placed", "GPU-a")]


def test_an_envelope_counts_every_unit_it_may_run_against_the_concurrency_limit():
    """B3-4a: a parallel run is one reservation running ``unit_slots`` units.

    Counting reservations instead would admit two 2-unit envelopes under a
    3-unit limit, i.e. four concurrent units.
    """
    budget = _budget(units=3)
    envelope = _cpu("run-a", 0).model_copy(update={"unit_slots": 2})
    running = _running(budget, envelope)
    second = _cpu("run-b", 1).model_copy(update={"unit_slots": 2})
    queued = plan_dispatch((second,), running, budget, on_refusal="continue").placements[0]
    assert (queued.decision, queued.reasons) == ("queued", ("max_concurrent_units 3 reached",))
    oversized = _cpu("run-c", 2).model_copy(update={"unit_slots": 4})
    refused = plan_dispatch((oversized,), (), budget, on_refusal="continue").refused
    assert "max_concurrent_units 3" in refused[0].reasons[1]


def test_unset_time_budget_flag_keeps_request_serialization():
    """Recorded placements (placement.json, ledger) predate the field; false is omitted."""
    assert "time_budgeted" not in _gpu("plain", 0, 1.0).model_dump(mode="json")


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
