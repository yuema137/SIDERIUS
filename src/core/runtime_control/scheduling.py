"""Pure admission and placement of concurrently schedulable units.

``plan_dispatch`` decides, from typed inputs only, which ready units may start
now, which wait, and which can never run under the declared ``HostBudget``.
It performs no I/O, reads no environment or clock and discovers no device.
The budget is a reservation ledger: running placements reserve their full
request until the caller removes them. Per-device VRAM arithmetic is delegated
to ``pair_admission.evaluate_resolved_pair_admission``; host memory requests
derive from the ``execution_calibration`` role ceiling. Contract: scheduling.md.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from core.execution_calibration import RoleCeiling
from core.runtime_control.pair_admission import (
    PairMember,
    PositiveGpuGiB,
    ResolvedGpuCeiling,
    evaluate_resolved_pair_admission,
)

_FROZEN = ConfigDict(frozen=True, extra="forbid")


def _reject_boolean(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("a scheduling quantity must be a number, not a boolean")
    return value


PositiveQuantity = Annotated[
    float, BeforeValidator(_reject_boolean), Field(gt=0, allow_inf_nan=False)
]
PositiveCount = Annotated[PositiveInt, Field(strict=True)]
Ordinal = Annotated[NonNegativeInt, Field(strict=True)]
GpuUuid = Annotated[str, Field(pattern=r"^(GPU|MIG)-[0-9A-Za-z-]+$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ResourceRequest(BaseModel):
    """What one schedulable unit reserves while it runs; derived, never LLM-authored.

    ``dispatch_ordinal`` is the unit's position in the reference serial order.
    It is the only ordering key: ties never depend on input order or timing.
    """

    model_config = _FROZEN

    unit_id: str = Field(min_length=1)
    dispatch_ordinal: Ordinal
    gpu_count: Literal[0, 1]
    vram_gib: PositiveGpuGiB | None = None
    vram_source: Literal["measured", "configured_cap"] | None = None
    host_memory_gib: PositiveQuantity
    cpu_slots: PositiveCount
    wall_seconds: PositiveQuantity

    @model_validator(mode="after")
    def _vram_matches_gpu_count(self) -> ResourceRequest:
        declared = (self.vram_gib is not None, self.vram_source is not None)
        if self.gpu_count == 1 and declared != (True, True):
            raise ValueError("a GPU unit requires vram_gib and vram_source")
        if self.gpu_count == 0 and declared != (False, False):
            raise ValueError("a CPU-only unit must not declare vram_gib or vram_source")
        return self


def host_memory_gib_from_role(ceiling: RoleCeiling) -> float:
    """Project a declared role address-space cap into a host-memory request.

    An inherited (undeclared) or explicit-zero (uncapped) role has no bound a
    reservation could rely on, so it refuses instead of guessing a host cap.
    """
    if not ceiling.gib:
        raise ValueError(
            f"role {ceiling.role!r} declares no positive address-space cap "
            "(SIDERIUS_SUBPROCESS_RSS_GB); supply an explicit host_memory_gib instead"
        )
    return float(ceiling.gib)


class GpuHardwareClass(BaseModel):
    """The LLM-visible hardware facts every budget slot must share."""

    model_config = _FROZEN

    device_name: str = Field(min_length=1)
    total_memory_bytes: PositiveCount
    compute_capability: tuple[Ordinal, Ordinal]


class GpuSlot(BaseModel):
    """One placeable device, keyed by its normalized driver UUID."""

    model_config = _FROZEN

    uuid: GpuUuid
    hardware_class: GpuHardwareClass
    ceiling: ResolvedGpuCeiling


class HostBudget(BaseModel):
    """The operator's explicit host budget; parallel mode has no discovered default."""

    model_config = _FROZEN

    gpus: tuple[GpuSlot, ...]
    host_memory_gib: PositiveQuantity
    cpu_slots: PositiveCount
    max_concurrent_units: PositiveCount
    source: Literal["caller", "file"]

    @model_validator(mode="after")
    def _distinct_homogeneous_slots(self) -> HostBudget:
        uuids = [slot.uuid for slot in self.gpus]
        if len(set(uuids)) != len(uuids):
            raise ValueError(f"duplicate GPU slot UUIDs in budget: {uuids}")
        classes = [slot.hardware_class for slot in self.gpus]
        if any(other != classes[0] for other in classes[1:]):
            raise ValueError(
                "heterogeneous GPU slots are refused: the proposer's hardware context "
                f"is LLM-visible and must not depend on placement; got {classes}"
            )
        return self

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical schedulable content; ``source`` is provenance."""
        payload = self.model_dump(mode="json", exclude={"source"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def slot(self, uuid: str) -> GpuSlot:
        for slot in self.gpus:
            if slot.uuid == uuid:
                return slot
        raise ValueError(f"GPU {uuid} is not a slot of budget {self.digest[:12]}")


class Placement(BaseModel):
    """One unit's scheduling decision against one budget; timing belongs to the runner."""

    model_config = _FROZEN

    reserved: ResourceRequest
    decision: Literal["placed", "queued", "refused"]
    gpu_uuid: GpuUuid | None = None
    budget_digest: Sha256Hex
    reasons: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _gpu_only_when_placed_on_one(self) -> Placement:
        needs_gpu = self.decision == "placed" and self.reserved.gpu_count == 1
        if needs_gpu != (self.gpu_uuid is not None):
            raise ValueError("gpu_uuid is required exactly for a placed GPU unit")
        return self

    @property
    def unit_id(self) -> str:
        return self.reserved.unit_id

    @property
    def dispatch_ordinal(self) -> int:
        return self.reserved.dispatch_ordinal

    @property
    def cuda_visible_devices(self) -> str | None:
        """The child's device selector: the placed UUID, so it sees logical 0."""
        return self.gpu_uuid


class ScheduleDecision(BaseModel):
    """``placements`` holds placed and queued units in ordinal order."""

    model_config = _FROZEN

    budget_digest: Sha256Hex
    placements: tuple[Placement, ...]
    refused: tuple[Placement, ...]

    @model_validator(mode="after")
    def _partitioned(self) -> ScheduleDecision:
        if any(p.decision == "refused" for p in self.placements):
            raise ValueError("refused units belong in refused, not placements")
        if any(p.decision != "refused" for p in self.refused):
            raise ValueError("refused holds only refused units")
        if any(p.budget_digest != self.budget_digest for p in self.placements + self.refused):
            raise ValueError("every decision must name the decision's budget digest")
        return self

    @property
    def placed(self) -> tuple[Placement, ...]:
        return tuple(p for p in self.placements if p.decision == "placed")

    @property
    def queued(self) -> tuple[Placement, ...]:
        return tuple(p for p in self.placements if p.decision == "queued")


class _Ledger(BaseModel):
    """Placed reservations against one budget; additions return a new ledger."""

    model_config = ConfigDict(frozen=True)

    budget: HostBudget
    placed: tuple[Placement, ...]

    def with_placement(self, placement: Placement) -> _Ledger:
        return _Ledger(budget=self.budget, placed=(*self.placed, placement))

    def host_memory_gib(self) -> float:
        return sum(p.reserved.host_memory_gib for p in self.placed)

    def cpu_slots(self) -> int:
        return sum(p.reserved.cpu_slots for p in self.placed)

    def gpu_members(self, uuid: str) -> tuple[PairMember, ...]:
        return tuple(_pair_member(p.reserved) for p in self.placed if p.gpu_uuid == uuid)


def plan_dispatch(
    ready: tuple[ResourceRequest, ...],
    running: tuple[Placement, ...],
    budget: HostBudget,
) -> ScheduleDecision:
    """Place ready units first-fit in strict FIFO ordinal order; refuse impossible ones.

    A unit that cannot fit now is queued, and every later ordinal queues behind
    it (head-of-line blocking; no backfill). A unit that cannot fit even on an
    empty budget is refused before any effect and does not hold the line.
    """
    digest = budget.digest
    ledger = _ledger_from_running(running, budget, digest)
    _require_unique_identities(ready, running)
    admitted: list[Placement] = []
    refused: list[Placement] = []
    head: ResourceRequest | None = None
    for request in sorted(ready, key=lambda r: r.dispatch_ordinal):
        refusal = _refusal_reasons(request, budget)
        if refusal:
            refused.append(_decide(request, "refused", digest, refusal))
            continue
        if head is not None:
            reasons = (f"strict FIFO: waiting behind earlier unit {head.unit_id!r}",)
            admitted.append(_decide(request, "queued", digest, reasons))
            continue
        placement = _place(request, ledger, digest)
        admitted.append(placement)
        if placement.decision == "placed":
            ledger = ledger.with_placement(placement)
        else:
            head = request
    return ScheduleDecision(
        budget_digest=digest, placements=tuple(admitted), refused=tuple(refused)
    )


def _ledger_from_running(
    running: tuple[Placement, ...], budget: HostBudget, digest: str
) -> _Ledger:
    for placement in running:
        if placement.decision != "placed" or placement.budget_digest != digest:
            raise ValueError(
                f"running unit {placement.unit_id!r} is not a placement against budget "
                f"{digest[:12]}; a reservation from another budget is not ledger evidence"
            )
        if placement.gpu_uuid is not None:
            budget.slot(placement.gpu_uuid)
    ordered = tuple(sorted(running, key=lambda p: p.dispatch_ordinal))
    return _Ledger(budget=budget, placed=ordered)


def _require_unique_identities(
    ready: tuple[ResourceRequest, ...], running: tuple[Placement, ...]
) -> None:
    requests = [*ready, *(p.reserved for p in running)]
    for key in ("unit_id", "dispatch_ordinal"):
        values = [getattr(r, key) for r in requests]
        if len(set(values)) != len(values):
            raise ValueError(f"ready and running units must have distinct {key} values")


def _decide(
    request: ResourceRequest,
    decision: Literal["placed", "queued", "refused"],
    digest: str,
    reasons: tuple[str, ...],
    gpu_uuid: str | None = None,
) -> Placement:
    return Placement(
        reserved=request,
        decision=decision,
        gpu_uuid=gpu_uuid,
        budget_digest=digest,
        reasons=reasons,
    )


def _refusal_reasons(request: ResourceRequest, budget: HostBudget) -> tuple[str, ...]:
    """Shortfalls that persist even with nothing running: escalate, never shrink."""
    reasons: list[str] = []
    if request.host_memory_gib > budget.host_memory_gib:
        reasons.append(
            f"needs {request.host_memory_gib:.2f} GiB host memory; "
            f"budget declares {budget.host_memory_gib:.2f} GiB"
        )
    if request.cpu_slots > budget.cpu_slots:
        reasons.append(f"needs {request.cpu_slots} CPU slots; budget declares {budget.cpu_slots}")
    if request.gpu_count == 1:
        reasons.extend(_gpu_refusal_reasons(request, budget))
    if reasons:
        reasons.insert(0, "escalated to operator: cannot fit the declared budget even when idle")
    return tuple(reasons)


def _gpu_refusal_reasons(request: ResourceRequest, budget: HostBudget) -> list[str]:
    if not budget.gpus:
        return ["needs one GPU; budget declares no GPU slots"]
    alone = (_pair_member(request),)
    if any(_fits(alone, slot) for slot in budget.gpus):
        return []
    largest = max(slot.ceiling.effective_gib for slot in budget.gpus)
    return [f"needs {request.vram_gib:.2f} GiB VRAM; largest slot ceiling is {largest:.2f} GiB"]


def _place(request: ResourceRequest, ledger: _Ledger, digest: str) -> Placement:
    shortfall = _shared_shortfall(request, ledger)
    if shortfall:
        return _decide(request, "queued", digest, (shortfall,))
    if request.gpu_count == 0:
        return _decide(request, "placed", digest, ("placed without a GPU",))
    return _place_on_gpu(request, ledger, digest)


def _shared_shortfall(request: ResourceRequest, ledger: _Ledger) -> str | None:
    budget = ledger.budget
    if len(ledger.placed) >= budget.max_concurrent_units:
        return f"max_concurrent_units {budget.max_concurrent_units} reached"
    free_memory = budget.host_memory_gib - ledger.host_memory_gib()
    if request.host_memory_gib > free_memory:
        return (
            f"needs {request.host_memory_gib:.2f} GiB host memory; "
            f"{free_memory:.2f} GiB unreserved in the ledger"
        )
    free_cpu = budget.cpu_slots - ledger.cpu_slots()
    if request.cpu_slots > free_cpu:
        return f"needs {request.cpu_slots} CPU slots; {free_cpu} unreserved in the ledger"
    return None


def _place_on_gpu(request: ResourceRequest, ledger: _Ledger, digest: str) -> Placement:
    candidate = _pair_member(request)
    headroom: list[str] = []
    for slot in ledger.budget.gpus:
        members = (*ledger.gpu_members(slot.uuid), candidate)
        decision = evaluate_resolved_pair_admission(members, limits=slot.ceiling)
        if decision.feasible:
            return _decide(request, "placed", digest, decision.reasons, gpu_uuid=slot.uuid)
        free = decision.headroom_gib + candidate.predicted_peak_vram_gb
        headroom.append(f"{slot.uuid}: {free:.2f} GiB unreserved")
    reason = f"needs {request.vram_gib:.2f} GiB VRAM; " + "; ".join(headroom)
    return _decide(request, "queued", digest, (reason,))


def _fits(members: tuple[PairMember, ...], slot: GpuSlot) -> bool:
    return evaluate_resolved_pair_admission(members, limits=slot.ceiling).feasible


def _pair_member(request: ResourceRequest) -> PairMember:
    if request.vram_gib is None or request.vram_source is None:
        raise ValueError(f"unit {request.unit_id!r} declares no GPU reservation")
    return PairMember(
        run_name=request.unit_id,
        predicted_peak_vram_gb=request.vram_gib,
        provenance=request.vram_source,
    )
