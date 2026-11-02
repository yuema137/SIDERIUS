# Parallel causality test contract

Owner: `test_parallel_causality.py`. Production owners remain
`parallel_evidence._check_causality` and `graph_evidence.settled_sources_end`.
The README in the parent directory owns invocation commands and opt-in usage.

## Dispatcher classes and bounded default lane

The full matrix executes 288 `launch_candidate` calls through `parallel_dispatch`:
12 configured failure sets × 8 four-node hold profiles × 3 unit limits (1, 2, 4).
Hold vectors are ordered `build0, build1, check0, check1`, measured in polls:
`(0,0,0,0)`, `(1,0,1,0)`, `(3,0,3,0)`, `(8,0,8,0)`, `(13,0,13,0)`,
`(0,3,1,1)`, `(8,8,1,2)`, `(3,0,0,2)`. The last three profiles let the
second build outlive the first and let either check overlap a sibling build.
They vary all four holds without requiring a Cartesian product of every poll
count. The fake starter runs the real unit child with offline native fixtures;
it delays reporting completion, not the scientific work itself. No dispatcher
or verifier is replaced. Indices 0–179 preserve the original five-profile
product; 180–287 cross all failure sets with the last three profiles. Within
each block the product order is failure set, hold vector, then unit limit.

Classification is by each node's outcome relative to the first failed receipt's
end event, in order `propose, build0, build1, check0, check1`:

- `S`: returned before that failure, or returned in a failure-free trace.
- `F`: the first failed entry.
- `D`: already running at the first failure, then returned during drain.
- `f`: already running at the first failure, then failed during drain.
- `-`: never dispatched.

All 288 full-matrix dispatcher traces reduce to the following 23 signatures.
The original coupled-hold block (indices 0–179) produces only 17; the
independent profiles add six classes where a check overlaps a sibling build
(`SSDF-`, `SSFD-`, `SFS-D`, `SSfF-`, `SSFf-`, `SFS-f`).
The default lane retains one witness for each signature and asserts that the
actual receipt timing still produces that signature. It also keeps concurrent
success (`trace-8`) beside single-slot success (`trace-0`), asserting actual
unit overlap. Unit limits 1, 2, and 4 remain represented.

| Trace | Signature | Distinguishing failure/drain behavior |
| --- | --- | --- |
| 0 | SSSSS | No failure, one slot |
| 8 | SSSSS | No failure, concurrent units, four-slot budget |
| 15 | SF--- | First build fails before its sibling starts |
| 19 | SFD-- | First build fails while sibling build runs successfully |
| 22 | SFS-S | First build fails after sibling branch finishes |
| 30 | SSFS- | Second build fails after first branch finishes |
| 34 | SSF-- | Second build fails after first build ends, before its check starts |
| 37 | SDF-- | Second build fails while earlier-declared build drains |
| 49 | SFf-- | First build fails first; second build also fails during drain |
| 52 | SfF-- | Second build fails first; first build also fails during drain |
| 60 | SS-F- | First check fails before sibling build starts |
| 64 | SSSFD | First check fails while sibling check drains successfully |
| 67 | SSSFS | First check fails after sibling check completes |
| 75 | SSSSF | Second check fails after first branch completes |
| 82 | SDS-F | Second check fails while earlier-declared build drains |
| 94 | SSSFf | First check fails; second check also fails during drain |
| 112 | SfS-F | Second check fails; earlier-declared build fails during drain |
| 135 | F---- | Proposal fails before either branch starts |
| 196 | SFS-D | First build fails while second check drains successfully |
| 202 | SSFD- | Second build fails while first check drains successfully |
| 217 | SSDF- | First check fails while second build drains successfully |
| 250 | SFS-f | First build fails; second check also fails during drain |
| 253 | SSfF- | First check fails; second build also fails during drain |
| 256 | SSFf- | Second build fails; first check also fails during drain |

The equivalence preserves the first-failure owner, dispatch/non-dispatch set,
final outcomes, and whether each dispatched entry completed before the cut or
was still running at it. These are the distinct failure-order facts consumed by
drain/readiness verification. Different poll counts inside a class, unused
extra capacity, and failures configured on nodes that never dispatch add no new
such fact. Independent successful siblings' exact completion order is not a
causal edge; source-to-consumer ordering is checked for every dispatched receipt
in every representative. This is an equivalence for this fixture's failure/drain
coverage, not a claim to enumerate all DAG schedules or graph shapes. The direct,
route-control, fan-in, and skipped-arm regressions separately cover those edges.

`SIDERIUS_FULL_PARALLEL_CAUSALITY=1` selects all 288 combinations at
collection time. Other values select the 24 representatives. Full opt-in runs
retain the signature assertions for those representatives and receipt verification
for every combination. Adding a new graph shape or failure mode requires revisiting
this classification; silently dropping a signature assertion is not a runtime fix.

## Skipped route arm witness and mutation

`test_adaptor_waits_for_the_source_of_a_skipped_route_arm` supplies checked-slot
facts directly to `_check_causality`: `check0 -> X -> pick`, where `X` is
`skipped/route_not_selected` and has no dispatch receipt. The adaptor is
`rejected/no_admissible_input`, a dispatched adaptor outcome with a receipt
(an executed adaptor never ends `skipped`, see "Dispatched adaptor states").
The valid order is check0 start/end = 1/2, pick start/end = 3/4. Swapping check0's
end with pick's start preserves internal ordering and the body event permutation
but must raise `ValueError` because pick starts before its deciding source ends.
This test deliberately isolates traversal; the other routed integration regression
owns production route projection/binding coverage.

Mutation witness: replace only `pending.extend(recorded[source].predecessors)`
with `pass` in `settled_sources_end`, preserving its imported function references.
The valid control still passes and the forged case fails with `DID NOT RAISE`.
Disabling all of `_check_causality` must also continue to break the three
production-path direct/route/fan-in forgeries. Mutations are in-memory validation
experiments, never committed source edits.

## Dispatched adaptor states

Issue #1454 asked whether an executed adaptor can end `skipped`, which the
receipt check (`parallel_evidence._dispatched`, then `state != "blocked"` for
adaptors) treated as dispatched while the readiness replay accepts only
`graph_models.DISPATCHED_STATES`. It cannot: `adaptor_phase.execute_adaptor`
closes an executed adaptor with `AdaptorOutcome.status` (typed exactly
`succeeded`/`rejected`/`failed`) or `failed` on an exception, and readiness
closes an undispatched adaptor only as `blocked`. `_dispatched` now uses
`DISPATCHED_STATES` for units and adaptors alike.

- `test_adaptor_states_share_the_one_dispatched_definition` binds the
  `AdaptorOutcome.status` literal to `DISPATCHED_STATES` and enumerates every
  pair of terminal source states (with and without abort): readiness either
  dispatches `pick` or closes it `blocked`/`dependency_not_successful`.
- `test_real_dispatcher_adaptor_states_verify[succeeded|rejected|failed|blocked]`
  runs the S1 fan-in (`selection_request`) through the real parallel dispatcher
  (in-process `_Starter`) to each reachable adaptor state, requires a receipt iff
  the state is in `DISPATCHED_STATES`, and verifies the trace. In the `rejected`
  case the adaptor relabelled `skipped`/`insufficient_items` without a record
  (its consumer stays `blocked`) must be refused: with its receipt by the
  receipt check (`receipt contradicts its state`), without it by the replay
  (`violates serial readiness`). About 60 s for the four runs.

Mutation witnesses (in-memory edits, `PYTHONDONTWRITEBYTECODE=1`): restoring the
old `state != "blocked"` adaptor rule fails `[rejected]` (the forged entry is then
refused by the replay instead of the receipt check, and vice versa); adding
`"skipped"` to `AdaptorOutcome.status`, or having readiness close an adaptor
`skipped`, fails the guard; treating only `succeeded` adaptors as dispatched fails
`[rejected]` and `[failed]`.
