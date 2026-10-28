"""Inert parallel-dispatch request (B3-4): per-capability unit resources, never guessed.

``CandidateRunRequest.parallel`` is omitted for serial runs, so their request
bytes and digests are unchanged. A capability absent from ``capabilities`` is
not parallelized: its units run alone with today's environment. Contract:
candidate-worker-contract.md, "Parallel dispatch".
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from core.runtime_control.pair_admission import PositiveGpuGiB
from core.runtime_control.scheduling import HostBudget, Placement, PositiveCount, PositiveQuantity
from tools.workflow_preview.models import PreviewModel

ParallelCapability = Literal[
    "proposal", "implementation", "validation", "literature", "interpretation", "tuning"
]


class CapabilityResources(PreviewModel):
    """What one unit of a capability reserves while it runs (operator-declared).

    ``vram_gib`` is required exactly when ``gpu`` is true. For ``tuning`` it must
    cover the run's active VRAM budget (checked at training admission).
    """

    gpu: bool
    vram_gib: PositiveGpuGiB | None = None
    host_memory_gib: PositiveQuantity
    cpu_slots: PositiveCount

    @model_validator(mode="after")
    def vram_iff_gpu(self) -> "CapabilityResources":
        if self.gpu != (self.vram_gib is not None):
            raise ValueError("vram_gib is declared exactly for a GPU capability")
        return self


class ParallelDispatch(PreviewModel):
    """Opt-in parallel graph dispatch for one candidate run.

    ``budget`` is the run's own host budget for a launch outside a host
    reservation ledger. Under a ledger the run's budget is derived from its
    reservation instead, and a request budget is refused (one authority).
    """

    capabilities: dict[ParallelCapability, CapabilityResources] = Field(min_length=1)
    budget: HostBudget | None = Field(default=None, exclude_if=lambda value: value is None)


class HostGrant(PreviewModel):
    """A host-ledger reservation handed to a parallel run (B3-4a).

    ``placement`` is the run's placed envelope against ``budget``. The run never
    schedules against ``budget`` itself, only against ``run_budget()``: the
    reserved slot, memory, CPU slots and unit slots, so no unit can be placed
    outside what the ledger reserved.
    """

    budget: HostBudget
    placement: Placement

    @model_validator(mode="after")
    def placed_against_budget(self) -> "HostGrant":
        if self.placement.decision != "placed" or self.placement.budget_digest != (
            self.budget.digest
        ):
            raise ValueError("a host grant is a placement against its own budget")
        return self

    def run_budget(self) -> HostBudget:
        reserved = self.placement.reserved
        gpus = ()
        if self.placement.gpu_uuid is not None:
            assert reserved.vram_gib is not None
            slot = self.budget.slot(self.placement.gpu_uuid)
            ceiling = slot.ceiling.model_copy(
                update={"operator_ceiling_gib": reserved.vram_gib, "operator_source": "caller"}
            )
            gpus = (slot.model_copy(update={"ceiling": ceiling}),)
        return HostBudget(
            gpus=gpus,
            host_memory_gib=reserved.host_memory_gib,
            cpu_slots=reserved.cpu_slots,
            max_concurrent_units=reserved.unit_slots,
            source="host_reservation",
            acknowledge_shared_gpu_time_budget=self.budget.acknowledge_shared_gpu_time_budget,
        )


#: Published write-once beside ``request.json`` (or a loop segment's continuation).
GRANT_CONTROL_FILE = "host_grant.json"


def admitted_run_budget(
    parallel: ParallelDispatch | None, grant: HostGrant | None
) -> HostBudget | None:
    """The one budget a run schedules against; ``None`` for a serial run.

    A parallel run takes exactly one authority: its host-ledger grant, or its own
    ``parallel.budget`` when launched without a ledger.
    """
    if parallel is None:
        if grant is not None:
            raise ValueError("a serial run takes no host grant")
        return None
    if (grant is None) == (parallel.budget is None):
        raise ValueError(
            "a parallel run schedules against exactly one budget: its host grant or parallel.budget"
        )
    return grant.run_budget() if grant is not None else parallel.budget


UnitExit = Literal["returned", "raised", "process_failed", "exited", "interrupted", "terminated"]


class UnitReceipt(PreviewModel):
    """Write-once dispatch evidence of one parallel-mode entry (B3-4b).

    Published as ``units/<node_id>/placement.json`` in the body's control
    directory. ``placement`` is ``None`` for a unit of an undeclared capability
    (it ran alone) and for an adaptor (a parent step). ``*_event`` values are one
    body-wide parent sequence, the only ordering the drain verifier trusts;
    ``*_at`` wall times are for humans. Scientific values stay in native records.
    """

    node_id: str
    placement: Placement | None = None
    queued_event: int | None = Field(default=None, ge=0)
    started_event: int = Field(ge=0)
    ended_event: int = Field(ge=0)
    started_at: str
    ended_at: str
    exit: UnitExit

    @model_validator(mode="after")
    def ordered(self) -> "UnitReceipt":
        if self.placement is not None and self.placement.decision != "placed":
            raise ValueError("a unit is dispatched only from a placed placement")
        queued = self.queued_event if self.queued_event is not None else self.started_event
        if not queued <= self.started_event <= self.ended_event:
            raise ValueError("unit receipt events are out of order")
        return self


def control_run_budget(
    request_parallel: ParallelDispatch | None, control: Path
) -> HostBudget | None:
    """The worker's scheduling budget from its control directory (``None``: serial).

    Reads the launch-published ``host_grant.json`` when present (bounded control
    read) and applies ``admitted_run_budget``.
    """
    from .graph_evidence import read_graph_control

    path = control / GRANT_CONTROL_FILE
    grant = None
    if path.exists():
        grant = HostGrant.model_validate_json(read_graph_control(path))
    return admitted_run_budget(request_parallel, grant)
