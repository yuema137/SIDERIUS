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
Duplicate `(port, position)` raises `AdaptorStrategyError`.

## Admissibility (shared with B2)

| Input | Admission |
| --- | --- |
| upstream `rejected` / `skipped` | that state |
| `validation.output` | `admissible` iff `ValidatorOutput.passed`, else `rejected` |
| `tuning.output` | `admissible` iff `best_valid_formal_denoising_score` is not `None`; else `health_invalid` when `best_formal_denoising_score` exists, `not_scoreable` otherwise |
| any other succeeded contract | `admissible` |

Labels are read from committed fields; nothing is recomputed. Only admissible
items reach COMBINE.

## Strategy kinds

COMBINE: `pass/v1` (each item, declared order); `collect/v1` (one
`CollectedItems`, `contribution_id` = source node id or external binding id,
one contract required); `concat-items/v1(field)` (field must equal
`SPLITTABLE_ITEMS[contract]`; non-list fields from the first item, revalidated
by the native model); `metric-rank/v1(score="best_valid_formal")` (requires
the run metric; every item's `metric_spec` is reconciled against it with
`reconcile_metric_specs`, conflicts raise `MetricIdentityConflictError`;
ranking via `MetricOrder.is_better`); `field-rank/v1(field, order)` (`order`: `descending` | `ascending`, a plain
sort order deliberately outside the metric `direction` vocabulary; ranks
the list entries of exactly one admissible value; field must equal
`RANKABLE_FIELDS[contract].item_field`; v1 = literature finding `confidence`,
ranking labelled `provenance="self-reported"`; entries whose field is `None`
are unranked).

SELECT returns unit indices: `all/v1` (declared order); `first-admissible/v1`
(requires `pass/v1`); `top-k/v1(k)` (ranking order, requires a ranking;
`k=1` is best-1); `threshold/v1(basis, metric_id, at_least)` (declared order;
`metric`: `MetricOrder.is_at_least`, `metric_id` must equal the run metric
and the ranking metric; `rubric`: total `>= at_least`, rubric scale is
higher-is-better by type). `top-k` over a `rubric`/`judge` ranking of
`tuning.output` is refused (Q-B2-2: an LLM may filter, never reorder,
metric-scored items). A list-entry selection rebuilds the one parent value with
the kept entries in selection order.

DISTRIBUTE: `single/v1` (index `None`); `per-item/v1(count, on_short)` (value
`i` → index `i`, missing indices `skipped`); `split-items/v1(field, count,
on_short)` (one value → one value per list entry, all other fields unchanged;
entry provenance `item_path="<field>[i]"`); `replicate/v1(count)` (same value,
role `replicated`).

Ties always resolve to declared order (stable sort); completion order is never
an input.

## Cardinality and outcomes

`derive_cardinality(select, distribute)`: `single`, `split-items`, `replicate`
→ `(1, 1)`; `per-item(M, skip)` → `(1, M)`; `per-item(M, fail)` → `(M, M)`;
`top-k(k)` caps max at `k`; `first-admissible` caps it at 1. An unsatisfiable
pair (min > max) raises `ValidationError`.

| Condition | Outcome |
| --- | --- |
| no admissible item | `rejected` / `no_admissible_input`, no outputs |
| SELECT keeps nothing, or a split value has no entries | `rejected` / `insufficient_items`, no outputs |
| kept count < bound min (`on_short="fail"`), or split entries < count with `fail` | `failed` / `insufficient_items` |
| split entries > count | `failed` / `too_many_items` (never truncated) |
| kept count > bound max | `AdaptorStrategyError` (declaration must bound SELECT) |
| inapplicable strategy (no ranking, uncatalogued field, mixed contracts, wrong basis) | `AdaptorStrategyError` |

## Record

`AdaptorRecord` (`siderius.adaptor-record/v1`) holds strategy kinds,
`parameters_sha256` (canonical JSON of the three declarations), status/reason,
every admission, the ranking, metric id/direction, one contribution per emitted
output and `OutputDigest(port, index, status, sha256)` where `sha256` is
`canonical_sha256(value)` (sorted-key compact JSON of `model_dump(mode="json")`).
Fields for implementation identity, B2 strategy evidence and custom execution
are added by the PRs that produce them.

## Validation evidence

`tests/unit/workflows/test_adaptor_strategies.py`: direction flip (mutation
proven against a hard-coded `>`), inadmissible exclusion, declared-order ties,
metric identity refusal, threshold tie inclusion, rubric filter-only rule,
empty inputs, cardinality table, shortfall, field-rank + split, collect/concat
attribution, record digests.

## Limitations

- Not reachable from any workflow until B6-3 wires execution; no paper or
  existing digest is affected.
- Open semantics to confirm: zero selected → `rejected` (not `failed`);
  `too_many_items` for split; `field-rank` over exactly one value.
