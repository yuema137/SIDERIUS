# Pure scheduling contract

Owner: `scheduling.py`. Scope: typed resource requests, an explicit host
budget, and the pure `plan_dispatch` decision that places, queues or refuses
ready units against a reservation ledger. Its production caller is the
cross-operation host ledger (B3-5a admission; B3-5b queued operations and their
waiting children); budget intake, the run-invariant fields and the child
environment projection are below. In-run graph dispatch, unit receipts and
timing belong to B3-4. Without a
`HostBudget`, execution remains serial and nothing here is consulted.

## Inputs

- `ResourceRequest` (frozen, `extra="forbid"`): `unit_id`, `dispatch_ordinal`
  (position in the reference serial order; the sole ordering key),
  `gpu_count` (`0` or `1`; the trainer owns one device), `vram_gib` and
  `vram_source` (`measured` or `configured_cap`; both required exactly when
  `gpu_count == 1`), `host_memory_gib`, `cpu_slots`, `wall_seconds` (the
  existing watchdog/timeout owner's value; carried, not used for admission),
  `time_budgeted` (strict bool, default `false`, omitted from serialization
  when false: the unit runs under a measured time budget, decision B3-Q6).
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
  `acknowledge_shared_gpu_time_budget` (strict bool, default `false`, omitted
  from serialization and the digest when false) is the operator's acceptance
  that time-budgeted runs may share a GPU slot (decision B3-Q6);
  `plan_dispatch` enforces it (step 3).
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
     unreserved CPU slots, or no slot with enough unreserved VRAM that it may
     share. Decision B3-Q6: unless the budget sets
     `acknowledge_shared_gpu_time_budget`, a slot already holding a placed
     unit is not eligible when either the candidate or any unit on that slot
     is `time_budgeted` (contention changes measured-time admission). That
     slot's reason reads `<uuid>: a time-budgeted unit would share it …`.
     An idle slot is always eligible, so this rule never refuses. Strict
     FIFO (decision B3-Q4): after the first queued unit, every later ordinal
     queues behind it (`strict FIFO: waiting behind earlier unit …`), even a
     smaller unit that would fit. No backfill.
   - **placed** otherwise. A GPU unit takes the first declared eligible slot
     whose ledger members plus the candidate are feasible under
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

## Budget intake, run invariants and child environment

Owner: `budget_intake.py` (decision B3-Q8: a JSON file only, no environment
variable).

- `load_host_budget_file(path) -> HostBudget` requires a regular file of at
  most `MAX_HOST_BUDGET_FILE_BYTES` (64 KiB), then reads one UTF-8 JSON object
  holding every `HostBudget` field except `source`, validates it once and
  returns a budget with `source="file"`. Consumers read the returned object,
  never the file. Refusals raise `HostBudgetFileError` naming the path: a
  missing path or non-regular file, a file above the byte cap, an unreadable
  or non-JSON file, a non-object top level, duplicate keys at any
  depth (never resolved last-wins), a file that declares `source` (intake owns
  provenance), and any `HostBudget` validation failure. Nothing is defaulted,
  discovered or read from the environment; each slot's `ceiling` is the
  operator's declared `ResolvedGpuCeiling`, e.g.

  ```json
  {"gpus": [{"uuid": "GPU-…", "hardware_class": {"device_name": "…",
     "total_memory_bytes": 51539607552, "compute_capability": [8, 9]},
     "ceiling": {"operator_ceiling_gib": 40.0, "operator_source": "caller",
                 "host_quota_gib": null, "measured_capacity_gib": 47.5}}],
   "host_memory_gib": 64.0, "cpu_slots": 8, "max_concurrent_units": 2}
  ```

- `scheduling_mode_for(budget)` is the one mode rule: `None` ⇒ `serial`, a
  budget ⇒ `parallel-v1` (also when `max_concurrent_units == 1`).
- Run invariants (`core/run_invariants.py`): `LockLaunchIdentity.host_budget`
  carries the validated budget to `build_run_invariants`, which records
  `scheduling_mode` (`_CANONICAL`, decision B3-Q7) and `host_budget`
  (`HostBudgetProvenance`: `digest`, `max_concurrent_units`, `source`;
  `_PROVENANCE`). The two travel together (`parallel-v1` ⇔ budget present).
  Both are omitted from the lock when serial and a legacy lock parses as
  `serial`: the B3-2 fields do not alter serial lock bytes or the canonical
  comparison; cross-revision resume still follows the assembly-digest rule
  (#999). Resume matrix: serial↔parallel-v1 refuses; parallel-v1 with a
  different budget validates.
- The lock records only the first run's budget (first writer wins). A resume
  under a different budget is accepted and leaves the lock unchanged;
  per-launch budget evidence belongs to the B3-4 placement receipts.
- Known limitation: a pre-B3-2 build ignores `scheduling_mode` and would read
  a parallel-v1 lock as serial. No forward-compatibility promise is made.
- Child environment (`core/subprocess_env.py`):
  `subprocess_env(..., cuda_visible_devices=Placement.cuda_visible_devices)`
  sets `CUDA_VISIBLE_DEVICES` (a slot UUID, or `""` for a placed CPU-only
  unit, replacing any inherited value). The default `None` leaves the
  environment exactly as before; no other key changes with a placement.

The candidate operations CLI (`submit --host-budget FILE`, B3-5a) is the first
caller of the loader; it places whole operations through the host reservation
ledger ([candidate operations contract](../../tools/candidate_operations/candidate-operations-contract.md#host-reservation-ledger))
and does not set `LockLaunchIdentity.host_budget`: a run that recorded
`parallel-v1` while its graph still dispatches serially would misstate its
trace semantics, so that binding belongs with B3-4. No console upload calls
the loader yet.

## Limits and validation

A ledger sum within the ceiling is admission evidence, not a guarantee
against other host users (see [GPU ceilings](gpu-ceilings.md)). Wall time
is not admitted here; only its coupling on a shared GPU (decision B3-Q6) is a
placement constraint. Focused CPU tests:
`tests/unit/core/test_scheduling.py`, `tests/unit/core/test_budget_intake.py`,
`tests/unit/core/test_subprocess_env_placement.py`. No GPU, process or LLM was exercised.
