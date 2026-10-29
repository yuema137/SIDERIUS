"""Parallel runs under the host reservation ledger (B3-4a): one envelope reservation.

A parallel run reserves its peak concurrent demand as one ledger entry, queues
like any run, and schedules only inside the grant derived from it.
"""

import itertools
import random
from fractions import Fraction
from uuid import uuid4

import pytest

from core.runtime_control.scheduling import ResourceRequest, plan_dispatch
from tests.helpers.candidate_fanout import fanout_request
from tests.unit.tools.candidate_operations.test_operation_scheduler import (
    GPU_NAMES,
    KEY,
    SLOT,
    _end,
    _held,
    _ledger,
    _operation_dir,
    _reservations,
    _store,
    children,
    processes,
)
from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import CandidateOperation, submit_operation
from tools.candidate_operations.host_ledger import HostScheduling
from tools.candidate_operations.host_queue import wait_for_placement
from tools.candidate_operations.models import OperationFailure, OperationResources
from tools.candidate_worker.parallel_envelope import dependency_ancestors, max_weight_antichain
from tools.candidate_worker.parallel_models import (
    CapabilityResources,
    HostGrant,
    ParallelDispatch,
    admitted_run_budget,
)

__all__ = ["children", "prepared", "processes"]  # fixtures used by name

SERIAL = OperationResources(gpu_count=0, host_memory_gib=1.0, cpu_slots=1, time_budgeted=False)


def _parallel(prepared, *, validation_vram: float = 1.5, budget=None):
    """``propose`` fans out to two build/check branches; every capability declared."""
    request = fanout_request(prepared, 2)
    request = request.model_copy(
        update={"environment_names": (*request.environment_names, *GPU_NAMES)}
    )
    table = {
        "proposal": CapabilityResources(gpu=False, host_memory_gib=2.0, cpu_slots=1),
        "implementation": CapabilityResources(gpu=False, host_memory_gib=3.0, cpu_slots=2),
        "validation": CapabilityResources(
            gpu=True, vram_gib=validation_vram, host_memory_gib=1.0, cpu_slots=1
        ),
    }
    parallel = ParallelDispatch(capabilities=table, budget=budget)
    return CandidateOperation(
        request_id=uuid4(),
        request=request.model_copy(update={"parallel": parallel}),
        resources=SERIAL,
    )


def _brute_force(weights, ancestors) -> Fraction:
    keys = list(weights)
    best = Fraction(0)
    for size in range(len(keys) + 1):
        for chosen in itertools.combinations(keys, size):
            if all(
                a not in ancestors[b] and b not in ancestors[a]
                for a, b in itertools.combinations(chosen, 2)
            ):
                best = max(best, sum((weights[k] for k in chosen), Fraction(0)))
    return best


def test_peak_demand_is_the_heaviest_set_that_can_run_together():
    """Summing every unit over-reserves a chain; a per-node max under-reserves a fan-out.

    Random DAGs compare the flow-based peak with brute-force enumeration.
    """
    rng = random.Random(1019)
    for _ in range(60):
        names = [f"n{i}" for i in range(rng.randint(1, 8))]
        predecessors = {
            name: frozenset(p for p in names[:index] if rng.random() < 0.35)
            for index, name in enumerate(names)
        }
        ancestors = dependency_ancestors(predecessors)
        weights = {name: Fraction(rng.randint(0, 6), rng.choice((1, 2, 4))) for name in names}
        assert max_weight_antichain(weights, ancestors) == _brute_force(weights, ancestors)


def test_a_parallel_run_reserves_one_envelope_and_never_schedules_outside_it(
    prepared, tmp_path, children
):
    """The envelope is the heaviest set of units that can overlap, per quantity.

    The two branches overlap: both checks (2 x 1.5 GiB), both builds (2 x 3 GiB
    memory, 2 x 2 CPU slots), two units. A per-node maximum would under-reserve
    (1.5, 3, 2, 1); summing all five units would over-reserve (3, 10, 7, 5).
    Inside the run, a unit larger than the reservation is refused and two units
    that together exceed it queue: scheduling against the host budget instead of
    the grant would place both on the 4 GiB slot.
    """
    host = _ledger(tmp_path)
    operation = _parallel(prepared)
    handle = submit_operation(_store(tmp_path, "a"), operation, launch_environment=KEY, host=host)
    assert handle.observation == "starting"
    (reservation,) = _reservations(host)
    reserved = reservation.placement.reserved
    assert (reserved.vram_gib, reserved.host_memory_gib, reserved.cpu_slots) == (3.0, 6.0, 4)
    assert reserved.unit_slots == 2
    grant_path = _operation_dir(_store(tmp_path, "a"), operation) / "host_grant.json"
    grant = HostGrant.model_validate_json(grant_path.read_bytes())
    budget = admitted_run_budget(operation.request.parallel, grant)
    assert budget is not None and budget.source == "host_reservation"

    def unit(name, ordinal, vram):
        return ResourceRequest(
            unit_id=name,
            dispatch_ordinal=ordinal,
            gpu_count=1,
            vram_gib=vram,
            vram_source="configured_cap",
            host_memory_gib=1.0,
            cpu_slots=1,
            wall_seconds=60.0,
        )

    too_big = plan_dispatch((unit("big", 0, 3.5),), (), budget, on_refusal="continue")
    assert [p.decision for p in too_big.refused] == ["refused"]
    pair = plan_dispatch((unit("a", 0, 2.0), unit("b", 1, 2.0)), (), budget, on_refusal="halt")
    assert [p.decision for p in pair.placements] == ["placed", "queued"]
    assert pair.placed[0].gpu_uuid == SLOT


def test_two_parallel_runs_never_oversubscribe_a_gpu_and_the_second_starts_when_freed(
    prepared, tmp_path, children, monkeypatch
):
    """Each 3 GiB envelope fits the 4 GiB slot alone; together they must not."""
    host = _ledger(tmp_path)
    first, second = _parallel(prepared), _parallel(prepared)
    store_a, store_b = _store(tmp_path, "a"), _store(tmp_path, "b")
    submit_operation(store_a, first, launch_environment=KEY, host=host)
    queued = submit_operation(store_b, second, launch_environment=KEY, host=host)
    assert queued.observation == "queued"
    assert [r.operation_id for r in _reservations(host)] == [first.request_id]

    _end(children.children[0])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "inherited")
    path = _operation_dir(store_b, second)
    placement = wait_for_placement(path, second.request_id, lambda: False)
    assert placement is not None and placement.reserved.vram_gib == 3.0
    grant = HostGrant.model_validate_json((path / "host_grant.json").read_bytes())
    assert grant.placement == placement
    assert [r.operation_id for r in _reservations(host)] == [second.request_id]


def test_ending_a_parallel_run_releases_its_whole_envelope(prepared, tmp_path, children):
    """One reservation holds the envelope, so its release frees every reserved unit slot."""
    host = _ledger(tmp_path)
    first = _parallel(prepared, validation_vram=2.0)
    submit_operation(_store(tmp_path, "a"), first, launch_environment=KEY, host=host)
    assert _held(host, first)
    _end(children.children[0])  # what a completed cancellation leaves behind
    assert not _held(host, first)
    again = _parallel(prepared, validation_vram=2.0)
    handle = submit_operation(_store(tmp_path, "b"), again, launch_environment=KEY, host=host)
    assert handle.observation == "starting"


def test_parallel_budget_has_exactly_one_authority(prepared, tmp_path, children):
    """A request budget under a ledger, or neither, would leave the run's limits ambiguous."""
    from tests.unit.tools.candidate_operations.test_operation_scheduler import _budget, _code

    host = _ledger(tmp_path)
    with_budget = _parallel(prepared, budget=_budget())
    code = _code(
        lambda: submit_operation(
            _store(tmp_path, "a"), with_budget, launch_environment=KEY, host=host
        )
    )
    assert code == "parallel_budget"
    no_ledger = _parallel(prepared)
    code = _code(lambda: submit_operation(_store(tmp_path, "b"), no_ledger, launch_environment=KEY))
    assert code == "parallel_budget_required"
    with pytest.raises(ValueError, match="exactly one budget"):
        admitted_run_budget(no_ledger.request.parallel, None)


def _gpu_unit(name: str, ordinal: int, vram: float) -> ResourceRequest:
    return ResourceRequest(
        unit_id=name,
        dispatch_ordinal=ordinal,
        gpu_count=1,
        vram_gib=vram,
        vram_source="configured_cap",
        host_memory_gib=1.0,
        cpu_slots=1,
        wall_seconds=60.0,
    )


def test_a_peak_above_capacity_is_admitted_and_runs_with_less_concurrency(
    prepared, tmp_path, children
):
    """Both checks (2 x 3 GiB) could overlap, but the only slot holds 4 GiB.

    Reserving the 6 GiB peak would refuse a run whose every unit fits; the
    envelope is clamped to the slot (never below one 3 GiB unit), the run is
    placed, and inside its grant the second check waits for the first.
    """
    host = _ledger(tmp_path)
    operation = _parallel(prepared, validation_vram=3.0)
    store = _store(tmp_path, "a")
    assert submit_operation(store, operation, launch_environment=KEY, host=host).observation == (
        "starting"
    )
    (reservation,) = _reservations(host)
    assert reservation.placement.reserved.vram_gib == 4.0
    grant = HostGrant.model_validate_json(
        (_operation_dir(store, operation) / "host_grant.json").read_bytes()
    )
    budget = admitted_run_budget(operation.request.parallel, grant)
    assert budget is not None
    pair = plan_dispatch(
        (_gpu_unit("check0", 0, 3.0), _gpu_unit("check1", 1, 3.0)), (), budget, on_refusal="halt"
    )
    assert [p.decision for p in pair.placements] == ["placed", "queued"]
    total = sum(p.reserved.vram_gib or 0.0 for p in pair.placed)
    assert total <= reservation.placement.reserved.vram_gib  # the grant is never exceeded


def test_concurrency_is_clamped_to_the_budget_not_refused(prepared, tmp_path, children):
    """A 2-unit peak under a 1-unit budget runs one unit at a time instead of failing."""
    from tests.unit.tools.candidate_operations.test_operation_scheduler import _budget

    root = tmp_path / "narrow"
    root.mkdir(mode=0o700)
    narrow = _budget().model_copy(update={"max_concurrent_units": 1})
    host = HostScheduling(ledger_root=str(root), budget=narrow)
    operation = _parallel(prepared)
    handle = submit_operation(_store(tmp_path, "a"), operation, launch_environment=KEY, host=host)
    assert handle.observation == "starting"
    (reservation,) = _reservations(host)
    assert reservation.placement.reserved.unit_slots == 1


def test_only_a_unit_that_fits_no_slot_is_refused_and_the_refusal_names_it(
    prepared, tmp_path, children
):
    """Clamping cannot shrink one unit below its own declaration: that is the refusal."""
    host = _ledger(tmp_path)
    store = _store(tmp_path, "a")
    too_big = _parallel(prepared, validation_vram=5.0)
    with pytest.raises(OperationFailure) as refused:
        submit_operation(store, too_big, launch_environment=KEY, host=host)
    assert refused.value.detail.code == "parallel_unit_exceeds_capacity"
    message = str(refused.value)
    assert "'check0'" in message and SLOT in message and "4.00 GiB" in message
    assert "parallel.capabilities" in message


def test_a_fully_declared_run_never_reserves_less_than_its_own_declaration(
    prepared, tmp_path, children
):
    """Every capability declared at 1 GiB, the run declared 3.5 GiB: reserving the
    1 GiB peak would undercount it beside other runs on the same GPU."""
    host = _ledger(tmp_path)
    operation = _parallel(prepared, validation_vram=0.5)
    operation = operation.model_copy(
        update={
            "resources": OperationResources(
                gpu_count=1,
                vram_gib=3.5,
                vram_source="configured_cap",
                host_memory_gib=12.0,
                cpu_slots=6,
                time_budgeted=False,
            )
        }
    )
    submit_operation(_store(tmp_path, "a"), operation, launch_environment=KEY, host=host)
    (reservation,) = _reservations(host)
    reserved = reservation.placement.reserved
    assert (reserved.vram_gib, reserved.host_memory_gib, reserved.cpu_slots) == (3.5, 12.0, 6)


def test_a_parallel_request_without_a_graph_profile_is_refused_typed(prepared, tmp_path, children):
    """The fixed (profile-less) chain used to surface a bare ValueError."""
    from tests.unit.tools.candidate_operations.test_operation_scheduler import _code

    host = _ledger(tmp_path)
    operation = _parallel(prepared)
    fixed = operation.model_copy(
        update={
            "request": operation.request.model_copy(
                update={
                    "preview": operation.request.preview.model_copy(
                        update={"execution_profile": None}
                    )
                }
            )
        }
    )
    launch = lambda: submit_operation(  # noqa: E731
        _store(tmp_path, "a"), fixed, launch_environment=KEY, host=host
    )
    assert _code(launch) == "parallel_profile"
    assert _reservations(host) == ()
