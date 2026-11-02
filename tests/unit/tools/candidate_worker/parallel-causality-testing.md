# Parallel causality test contract

Owner: `test_parallel_causality.py`. Production owners remain
`parallel_evidence._check_causality` and `graph_evidence.settled_sources_end`.
The README in the parent directory owns invocation commands and opt-in usage.

## Dispatcher classes and bounded default lane

The full matrix retains the original 180 executions of `launch_candidate`
through `parallel_dispatch`: 12 configured failure sets × 5 holds (0, 1, 3, 8,
13 polls) × 3 unit limits (1, 2, 4). The fake starter runs the real unit child
with offline native fixtures; it delays reporting completion, not the scientific
work itself. No dispatcher or verifier is replaced. Product order is failure
set, hold, then unit limit; `trace-N` is the original zero-based product index.

Classification is by each node's outcome relative to the first failed receipt's
end event, in order `propose, build0, build1, check0, check1`:

- `S`: returned before that failure, or returned in a failure-free trace.
- `F`: the first failed entry.
- `D`: already running at the first failure, then returned during drain.
- `f`: already running at the first failure, then failed during drain.
- `-`: never dispatched.

All 180 previously captured dispatcher traces reduce to these 17 signatures.
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

`SIDERIUS_FULL_PARALLEL_CAUSALITY=1` restores every original combination at
collection time. Other values select the 18 representatives. Full opt-in runs
retain the signature assertions for those representatives and receipt verification
for every combination. Adding a new graph shape or failure mode requires revisiting
this classification; silently dropping a signature assertion is not a runtime fix.

## Skipped route arm witness and mutation

`test_adaptor_waits_for_the_source_of_a_skipped_route_arm` supplies checked-slot
facts directly to `_check_causality`: `check0 -> X -> pick`, where `X` is
`skipped/route_not_selected` and has no dispatch receipt. The adaptor is
`skipped/no_admissible_input`, a dispatched adaptor outcome with a receipt.
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
