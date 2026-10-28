# Adaptor strategy core contract (B6-2)

## Scope and owners

`workflows.adaptors` is the pure deterministic core of an adaptor node:
admit → COMBINE → SELECT → DISTRIBUTE over typed items. It has no I/O, no
global state, no LLM and no execution wiring. Declaration format, readiness,
record publication, graph trace and verifier recomputation belong to later
B6 PRs (format: B6-1; execution: B6-3). LLM COMBINE kinds belong to B2
(`admit_/run_/replay_llm_strategy`); their rankings re-enter through `select`.

| Owner | Responsibility |
| --- | --- |
| `workflows/definition/adaptor_strategies.py` | Closed, versioned strategy declarations; shared B6 types `SelectStrategy`, `CardinalityBound`, `Fallback`, `derive_cardinality` (imported by B2) |
| `workflows/definition/catalog.py` | `SPLITTABLE_ITEMS` (contract → list field), `RANKABLE_FIELDS` (contract → `RankableField(list_field, item_field, provenance)`) |
| `items.py` | `AdaptorInputRef`, `AdaptorItem`, `admit` / `admit_items`, `AdaptorStrategyError` |
| `combine.py` | `combine`, `Unit`, `Combined`, `Ranking`, `RankEntry`, `CollectedItems` |
| `select.py` | `select` (unit indices), `chosen_units` |
| `run.py` | `run_deterministic_adaptor`, `AdaptorOutcome`, `AdaptorOutput` |
| `record.py` | `AdaptorRecord`, `AdaptorContribution`, `build_adaptor_record`, `canonical_sha256` |
| `MetricOrder` / `reconcile_metric_specs` | The only direction and metric-identity authorities used here |

## Interface

```python
run_deterministic_adaptor(items, *, combine_strategy, select_strategy,
                          distribute_strategy, metric: MetricSpec | None) -> AdaptorOutcome
build_adaptor_record(*, adaptor_id, iteration, combine, select, distribute,
                     outcome, fallback=None) -> AdaptorRecord
```

`items` must be in declared order (port order, then binding position). The
caller supplies each succeeded value already validated against its catalogue
contract; `AdaptorItem.value` is present iff `state == "succeeded"`.
`admit_items` refuses (`AdaptorStrategyError`) any tuple not in declared order:
each port's items must be contiguous and their positions strictly increasing.

## Admissibility (shared with B2)

| Input | Admission |
| --- | --- |
| upstream `rejected` / `skipped` | that state |
| `VALIDITY_GATED_CONTRACTS` (`validation.output`) | `admissible` iff `ValidatorOutput.passed`, else `rejected` |
| `METRIC_SCORED_CONTRACTS` (`tuning.output`) | `admissible` iff `best_valid_formal_denoising_score` is not `None`; else `health_invalid` when `best_formal_denoising_score` exists, `not_scoreable` otherwise |
| any other succeeded contract | `admissible` |

Labels are read from committed fields; nothing is recomputed. Only admissible
items reach COMBINE.

## Strategy kinds

COMBINE: `pass/v1` (each item, declared order); `collect/v1` (one
`CollectedItems`, `contribution_id` = source node id or external binding id,
one contract required); `concat-items/v1(field)` (field must equal
`SPLITTABLE_ITEMS[contract]`; non-list fields from the first item, revalidated
by the native model; each entry keeps its owning input as `entry_refs`); `metric-rank/v1(score="best_valid_formal")` (requires
the run metric; every item's `metric_spec` is reconciled against it with
`reconcile_metric_specs`, conflicts raise `MetricIdentityConflictError`;
ranking via `MetricOrder.is_better`); `field-rank/v1(field, order)` (`order`: `descending` | `ascending`, a plain
sort order deliberately outside the metric `direction` vocabulary; ranks
the list entries of exactly one admissible value; field must equal
`RANKABLE_FIELDS[contract].item_field`; v1 = literature finding `confidence`,
ranking labelled `provenance="self-reported"`; entries whose field is `None`
are unranked; entry units are labelled `element_contract="<contract>:<list_field>"`).
`RANKABLE_FIELDS` never names a `METRIC_SCORED_CONTRACTS` member (guard test).

SELECT returns unit indices: `all/v1` (declared order); `first-admissible/v1`
(requires `pass/v1`); `top-k/v1(k)` (ranking order, requires a ranking;
`k=1` is best-1); `threshold/v1(basis, metric_id, at_least)` (declared order;
`metric`: `MetricOrder.is_at_least`, `metric_id` must equal the run metric
and the ranking metric; `rubric`: total `>= at_least`, rubric scale is
higher-is-better by type). `top-k` over a `rubric`/`judge` ranking of
`METRIC_SCORED_CONTRACTS` items is refused (Q-B2-2: an LLM may filter, never
reorder, metric-scored items). A list-entry selection rebuilds the one parent
value with the kept entries in selection order; its inputs are the parent ref
followed by the kept entry refs.

DISTRIBUTE: `single/v1` (index `None`); `per-item/v1(count, on_short)` (value
`i` → index `i`, missing indices `skipped`); `split-items/v1(field, count,
on_short)` (one value → one value per list entry, all other fields unchanged;
each output's inputs are `(owner of the non-list fields, owner of entry i with
item_path="<field>[i]")`, so a concat → split names the right source review); `replicate/v1(count)` (same value,
role `replicated`).

Ties always resolve to declared order (stable sort); completion order is never
an input.

## Cardinality and outcomes

`derive_cardinality(select, distribute)`: `single`, `split-items`, `replicate`
→ `(1, 1)`; `per-item(M, skip)` → `(1, M)`; `per-item(M, fail)` → `(M, M)`;
`top-k(k)` caps max at `k`; `first-admissible` caps it at 1. An unsatisfiable
pair (min > max) raises `ValidationError`. The bound excludes the source count:
`all/v1` and `threshold/v1` keep up to every admissible item, so B6-1 must
refuse a declaration unless the bound ports' `max_items` (summed) is
`<= bound.max` for those selects; at run time an excess raises.

Declaration errors refused before admission (B6-1 validation-table rows):
`per-item/v1` after `collect/v1`, `concat-items/v1` or `field-rank/v1` (each
yields exactly one value); `split-items/v1` after `collect/v1`.

| Condition | Outcome |
| --- | --- |
| no admissible item | `rejected` / `no_admissible_input`, no outputs |
| any shortfall (including zero kept or zero split entries) under `on_short="fail"` | `failed` / `insufficient_items`, no outputs |
| zero kept or zero split entries without a `fail` policy (`single`, `replicate`, `on_short="skip"`) | `rejected` / `insufficient_items`, no outputs |
| `per-item`/`split-items` with `on_short="skip"` and 0 < n < count | `succeeded`; indices `n..count-1` `skipped` |
| split entries > count | `failed` / `too_many_items` (never truncated) |
| kept count > bound max | `AdaptorStrategyError` (declaration must bound SELECT) |
| inapplicable strategy (no ranking, uncatalogued field, mixed contracts, wrong basis) | `AdaptorStrategyError` |

## Record

`AdaptorRecord` (`siderius.adaptor-record/v1`) holds strategy kinds,
`parameters_sha256` (canonical JSON of the three declarations), status/reason,
every admission, the ranking, metric id/direction, one contribution per emitted
output and `OutputDigest(port, index, status, sha256)` where `sha256` is
`canonical_sha256(value)` (sorted-key, compact, ASCII JSON of
`model_dump(mode="json")`, the encoding of `WorkflowDefinition.declaration_digest`;
no package-neutral owner exists). The record test pins a literal digest.
Fields for implementation identity, B2 strategy evidence and custom execution
are added by the PRs that produce them.

## Validation evidence

`tests/unit/workflows/test_adaptor_strategies.py`: direction flip (mutation
proven against a hard-coded `>`), inadmissible exclusion, declared-order ties,
metric identity refusal, threshold tie inclusion, rubric filter-only rule,
empty inputs, monotonic shortfall, declared-order refusal, one-value combine
before per-item, cardinality table, field-rank + split, concat → split entry
provenance, collect external attribution, concat mixed contracts, ranking
direction iff metric, rankable-field guard, record literal digest.

## Limitations

- Not reachable from any workflow until B6-3 wires execution; no paper or
  existing digest is affected.
- Decided (review of B6-2): shortfall is monotonic; under `on_short="fail"`
  any shortfall fails, otherwise an empty result is `rejected`.
- Open semantics to confirm: `too_many_items` for split (never truncated);
  `field-rank` over exactly one value.
