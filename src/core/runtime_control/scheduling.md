# Pure scheduling contract

Owner: `scheduling.py`. Scope: typed resource requests, an explicit host
budget, and the pure `plan_dispatch` decision that places, queues or refuses
ready units against a reservation ledger. This module has no production
caller yet; budget intake, environment projection, process dispatch,
receipts and timing are later owners (B3-2, B3-4, B3-5). Without a
`HostBudget`, execution remains serial and nothing here is consulted.

## Inputs

- `ResourceRequest` (frozen, `extra="forbid"`): `unit_id`, `dispatch_ordinal`
  (position in the reference serial order; the sole ordering key),
  `gpu_count` (`0` or `1`; the trainer owns one device), `vram_gib` and
  `vram_source` (`measured` or `configured_cap`; both required exactly when
  `gpu_count == 1`), `host_memory_gib`, `cpu_slots`, `wall_seconds` (the
  existing watchdog/timeout owner's value; carried, not used for admission).
  Requests are derived by the core, never authored by an LLM. Booleans and
  non-finite quantities are refused.
- `host_memory_gib_from_role(RoleCeiling)` projects a declared positive
  `SIDERIUS_SUBPROCESS_RSS_GB` role cap from
  `core.execution_calibration.resolve_role_ceiling` into a request value. An
  inherited (undeclared) or explicit-zero (uncapped) role refuses: it has no
  bound a reservation could rely on, and no host cap is guessed. Callers may
  instead pass an explicit value.
- `GpuSlot`: normalized driver `uuid` (`GPU-…` or `MIG-…`), `hardware_class`
  (`GpuHardwareClass`: `device_name`, `total_memory_bytes`,
  `compute_capability`) and a per-device `ResolvedGpuCeiling` from
  `pair_admission.resolve_gpu_ceiling`.
- `HostBudget`: `gpus` (declared order is first-fit order; may be empty),
  `host_memory_gib`, `cpu_slots`, `max_concurrent_units`, `source`
  (`caller` or `file`). There are no defaults: every quantity is an explicit
  operator input. Measured capacity alone and `hardware_models._SAFETY_FRACTION`
  are never promoted into a budget. Duplicate slot UUIDs refuse.
  Heterogeneous hardware classes refuse (decision B3-Q3): the proposer's
  `hardware_context` is LLM-visible and must not depend on placement.
- `HostBudget.digest`: SHA-256 hex of the sorted-key compact JSON of every
  field except `source` (where the operator declared it is provenance; what
  is scheduled against is identity). Slot order is part of the digest.

## Decision

`plan_dispatch(ready, running, budget, *, on_refusal) -> ScheduleDecision`
reads no environment, clock, file or device. `on_refusal`
(`RefusalPolicy = Literal["continue", "halt"]`) is required and has no
default, so every caller states its refusal semantics.

1. `running` is the reservation ledger. Every entry must be a `placed`
   `Placement` naming this budget's digest and, for a GPU unit, one of its
   slots; otherwise `ValueError`. A reservation from another budget is not
   ledger evidence. The ledger closes the occupancy-snapshot
   time-of-check/time-of-use gap; measured occupancy admission
   (`admission.py`) and runtime protection remain separate, additional checks.
2. `unit_id` and `dispatch_ordinal` must be distinct across `ready` and
   `running`; a tie refuses rather than being broken by input order.
3. Ready units are visited in ascending `dispatch_ordinal`:
   - **refused** when the request cannot fit even an idle budget: host
     memory or CPU slots above the budget total, a GPU unit with no slots, or
     a VRAM request infeasible alone on every slot. Reasons start with
     `escalated to operator`. Nothing is shrunk, re-batched or re-routed. The
     refusal policy then applies:
     - `halt`: if any unit is refused, `placements` is empty and only the
       refused units are returned. This is the graph-mode serial reference:
       the body aborts with `resource_refused` before any effect. Graph
       callers (B3-4) must pass `halt`.
     - `continue`: a refused unit does not hold the queue; the remaining
       units are planned as if it were absent. This is the cross-operation
       mode (B3-5), where operations are independent submissions.
   - **queued** when it would fit an idle budget but the ledger is full in
     some dimension: `max_concurrent_units`, unreserved host memory,
     unreserved CPU slots, or no slot with enough unreserved VRAM. Strict
     FIFO (decision B3-Q4): after the first queued unit, every later ordinal
     queues behind it (`strict FIFO: waiting behind earlier unit …`), even a
     smaller unit that would fit. No backfill.
   - **placed** otherwise. A GPU unit takes the first declared slot whose
     ledger members plus the candidate are feasible under
     `evaluate_resolved_pair_admission(..., limits=slot.ceiling)`; that
     function is the only VRAM arithmetic (aggregate `<=` effective ceiling,
     effective ceiling = min of operator ceiling, host quota, measured
     capacity). Its reasons become the placement reasons. A placed unit is
     added to the ledger before the next unit is visited.
4. Host memory and CPU slots fit when `ledger sum + request <= budget`
   (queued when `ledger sum + request > budget`), the same form as the
   pair-admission aggregate.
5. Every shortfall reason ends with `(short by <excess> GiB)` printed to six
   significant digits, so a near-boundary message whose two-decimal values
   round equal still states why it does not fit.

The result is a deterministic function of the request set, the running set
and the budget: permuting either tuple yields an identical `ScheduleDecision`.

## Outputs

- `Placement` (frozen): `reserved` (the request), `decision`
  (`placed`/`queued`/`refused`), `gpu_uuid` (required exactly for a placed
  GPU unit), `budget_digest`, non-empty `reasons`. Derived properties:
  `unit_id`, `dispatch_ordinal`, `cuda_visible_devices`: for a placed GPU
  unit the slot UUID (the child sees it as logical device 0); for a placed
  CPU-only unit `""`, which hides every GPU so the child cannot allocate VRAM
  the ledger does not reserve; `None` only for a queued or refused unit,
  which must not be dispatched. Timing (`queued_at`, `started_at`, end and exit
  classification) is runner-owned receipt data, not part of this pure
  decision.
- `ScheduleDecision`: `budget_digest`, `placements` (placed and queued, in
  ordinal order), `refused`; properties `placed` and `queued`.

## Limits and validation

A ledger sum within the ceiling is admission evidence, not a guarantee
against other host users (see [GPU ceilings](gpu-ceilings.md)). Wall time
is not admitted here; time-budget coupling on a shared GPU (decision
B3-Q6) belongs to the dispatching owners. Focused CPU tests:
`tests/unit/core/test_scheduling.py`. No GPU, process or LLM was exercised.
