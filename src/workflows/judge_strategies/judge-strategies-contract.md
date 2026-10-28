# `workflows/judge_strategies/` — LLM COMBINE strategies for adaptors

Technical contract for the LLM strategy framework (advanced design B2, PR B2-6).
Source and tests determine current behavior. Implemented kinds: `rubric-rank/v1`
(ranking), `judge-merge/v1` (combining, B2-9) and `primary-advisors-llm/v1`
(combining, B2-8). `debate-judge/v1` is refused until its PR (B2-7) lands. No
adaptor can declare or run an LLM kind yet: the adaptor wiring (B6-8) makes the
union declarable in `AdaptorInstance.combine` and calls this package.

## Scope and owners

| Owner | Responsibility |
| --- | --- |
| `workflows/definition/llm_strategies.py` | Declarations: `LLMStrategy` = discriminated union (`kind`) of `DebateJudgeStrategy`, `RubricRankStrategy`, `PrimaryAdvisorsStrategy`, `JudgeMergeStrategy`, all with common `route_slot`, `max_calls`, `on_failure: "fail" \| Fallback`, `guidance`, `criterion` |
| `admission.py` | `admit_llm_strategy` (pure, no I/O) |
| `projection.py` | `ITEM_PROJECTORS` (contract → projector), `project_item`, `strategy_items` |
| `kinds.py` | `IMPLEMENTED_KINDS`, `implemented_kind`, `strategy_call_bound` |
| `plan.py` | `PlannedCall`, `StrategyKind`, `StrategyFoldFailure`, `judged_items`, `precall_failure`, `next_call`, `strategy_route`, `call_request`, `call_path`, `decide` (shared by run and replay) |
| `rubric_rank.py` | `rubric-rank/v1`: `call_bound`, `min_items`, `plan_call`, `fold` (pure) |
| `judge_merge.py` | `judge-merge/v1`: `MERGE_TEMPLATE` (`judge.merge/v1`, role `merger`, usage label `judge.judge-merge`, response `SynthesisVerdict`), `call_bound`, `min_items`, `output_count`, `plan_call`, `fold` |
| `primary_advisors.py` | `primary-advisors-llm/v1`: `ADVICE_TEMPLATE` (`judge.advice/v1`, role `advisor`, response `AdvisoryNote`), `REVISION_TEMPLATE` (`judge.revision/v1`, role `reviser`, response `SynthesisVerdict`), both usage label `judge.primary-advisors-llm`; `call_bound`, `min_items`, `output_count`, `admit_parameters`, `precheck`, `split`, `plan_call`, `fold` |
| `synthesis.py` | Combining kinds' values: `output_facts` (contract JSON schema + framework-owned fields for the prompt), `check_draft`, `provenance_label`, `combined_items` |
| `run.py` | `run_llm_strategy`: the only provider effect in the package |
| `replay.py` | `replay_llm_strategy`: readback; its direct imports include no provider module (`agent.llm_bridge`, `agent.judge.call`) |
| `models.py` | `StrategyItem`, `StrategyInvocation`, `invocation_sha256`, `RubricScore`, `CriterionValue`, `ItemRanking`, `CombinedItem`, `CombinedItems`, `StrategyFailureCode`, `StrategyOutcome`, `StrategyEvidence`, `StrategyResult`, `StrategyAdmission`, `StrategyRefusal`, `StrategyError` |
| `agent/judge/rubric_template.py` | `RUBRIC_TEMPLATE` (`judge.rubric/v1`, role `scorer`, usage label `judge.rubric-rank`, response `RubricVerdict`) |
| `agent/schemas/judge.py` | Call-level types: `RubricScoringRequest` (`CallContent` kind `rubric_scoring`), `MergeRequest` (kind `merge`, role `merger`), `AdviceRequest` (kind `advice`, role `advisor`), `RevisionRequest` (kind `revision`, role `reviser`), `JudgedItem`, `ItemProjection`, `ProjectedField`, `RubricVerdict` (`CallPayload` kind `rubric`), `AdvisoryNote` (kind `advice`), `SynthesisVerdict` (kind `synthesis`) with `SynthesizedDraft(parents, value)` |

Not owned here: every judge call, its evidence file and its readback
([judge contract](../../agent/judge/judge-contract.md): `run_judge_call`,
`verify_call_evidence`); rubric declaration and resolution (`RubricSpec`,
`RubricRef`, `resolve_rubric_ref` in `agent/schemas/judge_task.py`); route
resolution and the run lock (`workflows.llm_config.locked_judge_routes`,
`RunInvariants.judge_routes`); the adaptor declaration, admissibility, SELECT,
DISTRIBUTE, `Fallback` execution and the adaptor record
([adaptor contract](../adaptors/adaptor-contract.md)).

## Interface B6 calls

```python
admit_llm_strategy(strategy, *, inputs: tuple[InputPort, ...], output_contract: str,
                   select: SelectStrategy, cardinality: CardinalityBound) -> StrategyAdmission
strategy_items(items: tuple[AdaptorItem, ...]) -> tuple[StrategyItem, ...]
run_llm_strategy(invocation, routes: JudgeRoutes, *, context: JudgeRunContext,
                 bridge_factory=bridge_for_route) -> StrategyResult
replay_llm_strategy(invocation, routes: JudgeRoutes, *, expected_sha256: str) -> StrategyResult
```

B6 records `StrategyResult.evidence_sha256` in its adaptor record and passes it
back as `expected_sha256` on readback; that anchor is what makes the whole call
chain tamper-evident. `routes` is the run lock's `JudgeRoutes`.

## Admission (`admit_llm_strategy`)

Returns `StrategyAdmission(static_call_bound, required_route_slot, refusals)`;
admitted iff `refusals` is empty. Refusal codes:

| Code | Rule |
| --- | --- |
| `kind_not_implemented` | the kind is not in `IMPLEMENTED_KINDS` (only refusal reported; `static_call_bound=None`) |
| `no_input_ports` | `inputs` is empty (only refusal reported; `static_call_bound=None`) |
| `batch_too_large` | a kind that lists every item in one call (`lists_every_item`: every kind except `rubric-rank` with `scoring="per_item"`) over an item capacity above `MAX_SCORED_ITEMS_PER_CALL` (16; `agent/schemas/judge.py`), so every prompt has a fixed size bound; rubric-rank: use `per_item` |
| `unbounded_port` | a `many` port without `max_items`: the static call bound needs the item capacity (`one` port = 1, `many` port = `max_items`) |
| `mixed_contracts` | ports of more than one contract |
| `unprojectable_contract` | no projector in `ITEM_PROJECTORS` (v1: `proposal.output`, `literature.output`) |
| `output_contract_mismatch` | the output contract must equal the input contract (a ranking passes values through; a combining kind synthesizes values of the same contract) |
| `select_incompatible` | a rubric ranking feeds only `all/v1`, `top-k/v1` or `threshold/v1` with `basis="rubric"`; a combining kind feeds only `all/v1` |
| `output_not_emittable` | a combining kind's output contract is not in `catalog.CUSTOM_EMITTABLE` (authority contracts such as `tuning.output` are never synthesized) |
| `cardinality_mismatch` | a combining kind's declared output count (`judge-merge`: `synthesize_count`) lies outside `cardinality` |
| `insufficient_capacity` | the ports hold fewer items than the kind's `min_items` (`judge-merge`: `min_parents`; `primary-advisors-llm`: 2) |
| `primary_rule_unavailable` | `primary-advisors-llm` declares `primary="metric_best"`: no projectable contract carries item metric facts yet |
| `primary_item_undeclared` | `primary="declared"` names a `primary_item` that is not an input position `<port>:<position>` of the declared ports |
| `metric_scored_reorder` | Q-B2-2: over `METRIC_SCORED_CONTRACTS` items an LLM ranking may feed only `all/v1` or `threshold(basis="rubric")`, never `top-k/v1` (B6 `select` re-checks at run time) |
| `call_bound_exceeds_max_calls` | `strategy_call_bound(strategy, capacity) > max_calls` |

`cardinality` bounds a combining kind's output count and is not used by a
ranking kind. `on_failure` fallback admissibility is B6's: it validates
`Fallback.combine` in place of the LLM kind with its deterministic validation
table. The run-level `JudgeRoutes.max_judge_calls` sum (adaptors × iterations +
the JudgeStop bound) is enforced by the B6-8 wiring.

## Items and invocation

`strategy_items` re-applies B6's `admit_items` (declared order: each port's items
contiguous, positions increasing) and refuses any item that is not `admissible`
(`AdaptorStrategyError`); B2 never judges an inadmissible input. Each
`StrategyItem(ref: AdaptorInputRef, contract, projection)` has
`item_id = "<port>:<position>"` (dispatch identity, never scientific meaning).

Projectors are bounded and deterministic: every text truncated to
`MAX_PROJECTED_CHARS` (4000); at most `MAX_PROJECTED_ENTRIES` (24) list entries,
with the omitted count recorded as a field. `proposal.output` projects
`model_name`, `model_description`, `mathematical_definition`, `motivation`;
`literature.output` projects each finding's `content` and `source_ref` plus
`findings.omitted`. System identities (`candidate_id`) and self-reported
`confidence` are not projected.

`StrategyInvocation(adaptor_id, iteration, strategy, items, output_contract,
expected_count, rubric, task_guidance, evidence_dir)` refuses: duplicate items;
more than `MAX_SCORED_ITEMS_PER_CALL` items for a kind that lists every item in
one call (the same cap is the request schemas' `max_length`, e.g. `MergeRequest.items`);
items of more than one contract; a `rubric` that is absent for `rubric-rank/v1`,
present for another kind, or whose `rubric_ref(rubric)` differs from
`strategy.rubric` (content digest); `task_guidance` present iff
`strategy.guidance == "task_blocks"` (B6 supplies the task's composed
`JudgeTaskBlocks`; a task without judge blocks cannot satisfy `task_blocks`).
`invocation_sha256` is the canonical digest of the invocation without
`evidence_dir`, so evidence is host-independent.

## `rubric-rank/v1`

Parameters: `rubric: RubricRef`, `scoring: "per_item" | "batch"`, `repeats: 1..3`,
`tie_break: "input_order"`. Static call bound: `per_item` = `N × repeats`,
`batch` = `repeats`. Calls are planned repeat-major, then input order; each is a
`scorer` call with `RubricScoringRequest(rubric, criterion, repeat, items,
guidance)` (`items` is one item for `per_item`, all items for `batch`).

Every item is scored, including a single item (N ≥ 1): its rubric weighted mean is a
value `threshold(basis="rubric")` reads, so the "one item → skipped" shortcut of
ordinal ranking kinds does not apply.

The `judge.rubric/v1` prompt shows the experiment criterion, the rubric id,
version and integer scale (higher is better), each criterion's name and
description, the projected items and, when present, the task guidance. It never
shows weights or `repeat`. The verdict `RubricVerdict(kind="rubric",
item_scores=[{item_id, scores=[{criterion, score: int}]}], rationale)` is strict
(`extra="forbid"`: a verdict carrying its own total is `invalid_payload`). Its
`check_payload` requires exactly the listed items and, per item, exactly the
rubric's criteria with integers in `[scale_min, scale_max]`; otherwise
`inadmissible_choice`.

The fold (pure, imports no metric owner): per item and criterion, the median of
the repeats' integers (`statistics.median`; with 2 repeats the mean of the two);
`weighted_mean = Σ(weight × median) / Σ weight` in rubric criterion order, computed
exactly with `fractions.Fraction` (each weight enters as the decimal it was declared
as, `Fraction(repr(weight))`; medians are exact), so it always lies on the rubric
scale `[scale_min, scale_max]` and a `threshold(basis="rubric", at_least)` reads on
that scale independently of how the weights are normalized. `RubricScore` carries
`weighted_mean_exact` (canonical `str(Fraction)`, e.g. `"4"`, `"13/3"`), the
authority for ordering, ties and thresholds and the value replay compares, plus
`weighted_mean = float(exact)` for display only. Ranking is by the exact value
descending, equal values in input order. B6 `select` compares a rubric threshold
exactly: `Fraction(RankEntry.exact) >= Fraction(repr(at_least))`. `RubricScore` is not a
metric: it never enters `MetricOrder`, tuning records, the incumbent, Health or
stop conditions.

## `judge-merge/v1`

Parameters: `synthesize_count: 1..MAX_ADAPTOR_OUTPUTS`, `min_parents: ≥ 2`.
Static call bound: 1. `min_items = min_parents`: with fewer admissible items no
call is made and the outcome is `insufficient_items` (zero recorded calls,
replayable). The one `merger` call carries `MergeRequest(criterion,
output_contract, synthesize_count, min_parents, items, guidance)`; the
`judge.merge/v1` prompt shows the criterion, the requested count and
`min_parents`, the projected items, the output contract's JSON schema and its
catalogued framework-owned fields (`PROTECTED_FIELDS`), and task guidance when
present. The prompt therefore depends on the output contract's native schema:
a schema change moves `prompt_sha256` and old evidence no longer replays.

The verdict `SynthesisVerdict(kind="synthesis", items=[{parents, value}],
rationale)`. `check_payload` (→ `inadmissible_choice`) requires, per draft:
distinct parents, all listed, at least `min_parents` of them; and a value that
validates as the output contract's native type
(`workflows.custom_adaptors.contracts`) with every framework-owned field unset
(`workflows.custom_adaptors.protected`). The count is checked by the fold: a
count other than `synthesize_count`, or outside `expected_count`, is the
strategy failure `cardinality_mismatch` (never truncated). The fold validates,
stamps `adaptor:<adaptor_id>/judge-merge/v1` into the `stamp-source` fields and
re-validates each value, returning `CombinedItems(contract, items=[CombinedItem(
output_index, parents, value, value_sha256)])`. A merged proposal is a new
candidate; downstream training still needs its own implementation and
validation (B6 profile admission). No score arithmetic is involved.

## `primary-advisors-llm/v1`

Parameters: `primary: "declared" | "metric_best" | "first_admissible"` (no
default, Q-B2-9), `primary_item` iff `declared`, `advice: "single_call" |
"per_advisor"`. `min_items` = 2, output count 1. Static call bound:
`single_call` = 1, `per_advisor` = N (N − 1 advisor calls + 1 reviser call).

Primary selection (`split`, pure) never falls back to declaration order unless
`first_admissible` is declared: `declared` → the item with id `primary_item`;
if that item is not among the admissible items, `precheck` fails the invocation
before any call with `primary_unavailable` (zero calls, replayable);
`first_admissible` → the first item; `metric_best` → refused at admission and
`StrategyError` at planning (see Limitations). Advisors are the other items in
declared order. The primary and advisors are part of every request, so a replay
re-derives them by the declared rule and refuses evidence naming another primary.

`per_advisor`: call `i < N − 1` is an `advisor` call `AdviceRequest(criterion,
output_contract, primary, advisor=advisors[i], guidance)`; its `AdvisoryNote(
advisor_item, suggestions: 1..12 strings ≤ 1000 chars)` must name that advisor
(`inadmissible_choice` otherwise). The last call (the only call for
`single_call`) is a `reviser` call `RevisionRequest(criterion, output_contract,
primary, advisors, notes, guidance)`; `notes` holds every earlier note verbatim in
advisor order (empty for `single_call`), so the reviser's request carries what the
advisors said. Planners receive the earlier decided payloads for this
(`StrategyKind.plan_call(invocation, earlier)`).

The reviser returns a `SynthesisVerdict`. `check_payload` requires, per draft,
distinct listed parents (primary or advisors) whose first entry is the primary,
and a contract-valid value with framework-owned fields unset. Lineage contract
for B6: `CombinedItem.parents[0]` is the primary; the remaining parents are the
advisors whose advice was adopted. `RevisionRequest.advisors` and `notes` hold at
most `MAX_SCORED_ITEMS_PER_CALL − 1` entries (the reviser lists every item), and
admission refuses a larger capacity (`batch_too_large`). The fold requires exactly one
value (`cardinality_mismatch` otherwise) and stamps
`adaptor:<adaptor_id>/primary-advisors-llm/v1`. No score arithmetic is involved.

## Run (`run_llm_strategy`)

1. Refuse with `StrategyError`, before any provider contact: unimplemented kind;
   no route for `route_slot` in `routes`; `context.iteration !=
   invocation.iteration`; `strategy_call_bound(strategy, len(items)) >
   max_calls`; a non-empty `evidence_dir` (evidence is never reused). A
   `JudgeCallRefused` or `ExecutionDeadlineExceeded` from the call core
   propagates; any published call files then stay without a `strategy.json`, and
   a rerun of that invocation refuses.
2. For each planned call: `run_judge_call(call_request(...), template, route,
   context, evidence_path=<evidence_dir>/calls/<NNN>_<role>.json,
   max_calls=bound)`. Each request names `invocation_sha256` and lists the
   `evidence_sha256` of every earlier call (`prior_turns`). The chain stops at the
   first call whose status is not `decided`.
3. `decide`: fewer items than `min_items` → no call, `insufficient_items`; a
   kind `precheck` failure (`primary_unavailable`) → no call, that code; all
   decided → `StrategyOutcome(status="decided", ranking=...)` for a ranking kind or
   `combined=...` for a combining kind (`combined` is omitted from the JSON when
   absent), unless the fold raises `StrategyFoldFailure` (`cardinality_mismatch`);
   otherwise `failed` with the call's `failure_code`, or `fallback` with
   `fallback_combine = on_failure.combine.kind` when a `Fallback` is declared
   (B6 then runs that deterministic combine on the same items; partial LLM output
   is never reused).
4. Publish `StrategyEvidence(schema_version="siderius.judge-strategy/v1",
   invocation_sha256, strategy_kind, static_call_bound, calls=(digests in order),
   outcome)` write-once at `<evidence_dir>/strategy.json` as canonical JSON and
   return `StrategyResult(outcome, evidence_sha256)`.

Usage rows are recorded by the bridge under label `judge.rubric-rank` with the
run context; no side ledger.

## Replay (`replay_llm_strategy`)

Never calls a provider. Refuses (`StrategyError`) when: `strategy.json` is
missing, differs from `expected_sha256`, is malformed or non-canonical; it names
another invocation (`invocation_sha256`), kind or call bound; a call follows a
failed call; a recorded call is not planned; any call fails
`verify_call_evidence` against its anchored digest, the re-derived request,
`judge.rubric/v1` identity, the locked route and `check_payload`; the chain ends
before the planner is done although its last call decided; the re-derived
outcome differs from the recorded one; any file under `evidence_dir` is not
accounted for. It returns the recorded `StrategyResult`.

## B6-8 consumer contract

The adaptor wiring (B6-8) is the only intended caller. It must:

1. **Declare.** Add `LLMStrategy` to `AdaptorInstance.combine` and the kinds to
   `catalog.ADAPTOR_STRATEGIES` (owner `workflows.judge_strategies`); new fields stay
   omitted when absent so existing declaration bytes and digests do not move.
2. **Admit.** At declaration validation and launch admission, call
   `admit_llm_strategy(strategy, inputs=adaptor.inputs, output_contract=<derived>,
   select=adaptor.select, cardinality=derive_cardinality(select, distribute))` and
   refuse on any refusal. Validate a declared `Fallback.combine` by running the
   deterministic validation table on the adaptor with `combine` replaced by it.
   Sum every adaptor's `static_call_bound` × iterations plus the JudgeStop bound and
   refuse when it exceeds the locked `JudgeRoutes.max_judge_calls`; at run time,
   refuse a call that would cross that cap.
3. **Invoke.** Build items with `strategy_items(admissible AdaptorItems in declared
   order)`; never invoke with zero admissible items (`rejected/no_admissible_input`).
   Resolve `rubric` with `resolve_rubric_ref(strategy.rubric, task + experiment
   rubrics)`; pass the task's composed `JudgeTaskBlocks` iff `guidance ==
   "task_blocks"`. Assign `evidence_dir = candidate_control_dir(workspace,
   iteration=N)/adaptors/<id>.judge/`, unique per invocation and write-once. Pass the
   run lock's `JudgeRoutes` and a `JudgeRunContext` of the same iteration.
4. **Consume.** `decided` → map `ItemRanking` to a B6 `Ranking(basis="rubric")`
   with `RankEntry.value = weighted_mean` and `RankEntry.exact = weighted_mean_exact`
   (a rubric ranking without `exact` is refused), then SELECT/DISTRIBUTE; or,
   for `combined`, validate each `CombinedItem.value` with the output contract's
   native type, record its `parents` as lineage and DISTRIBUTE them (`all/v1`);
   `fallback` → run `fallback_combine` deterministically on the same items;
   `failed` → adaptor `failed`, reason `judge_failure`. Record
   `(<evidence_dir>/strategy.json, evidence_sha256)` in
   `AdaptorRecord.strategy_evidence` and the fallback kind in `AdaptorRecord.fallback`.
5. **Replay.** Rebuild the same invocation from verified records and call
   `replay_llm_strategy(invocation, locked_routes, expected_sha256=<recorded>)`;
   never call `run_llm_strategy` on readback or resume.

## Validation evidence

`tests/unit/workflows/test_primary_advisors.py` (B2-8): single_call bound 1 with
stamped lineage and replay; a declared primary is used, not the first item;
re-anchored evidence revising another primary refused on replay; per_advisor
consults advisors in order and the reviser sees every note (N calls); a note
naming another advisor and a revision dropping the primary refused; an
inadmissible declared primary → `primary_unavailable` with no call; a fully
re-recorded forgery naming another primary (prompt identity and outcome rewritten)
refused on replay; parents not starting with the primary refused; more items than
one call may hold refused; `metric_best`
never runs; admission bounds and one row per refusal; pinned `judge.advice/v1`
and `judge.revision/v1` digests.

`tests/unit/workflows/test_judge_merge.py` (B2-9): stamped values with parents
in one call and replay; `min_parents` violated, repeated or foreign parents
refused; too few items → no call, `insufficient_items`, replayable; a value
missing a required field, setting provenance or a forbidden trust level refused;
a surplus value → `cardinality_mismatch` with the declared fallback; an edited
merged value refused on replay; admission rows (`select_incompatible`,
`cardinality_mismatch`, `insufficient_capacity`, `output_contract_mismatch`,
`output_not_emittable`); pinned `judge.merge/v1` digests.

`tests/unit/workflows/test_judge_strategies.py`: hand-computed weighted means
and input-order ties; per-criterion median of repeats; LLM-supplied total
refused; weighted mean pinned to the rubric scale and a rubric threshold
read on that scale through B6 `select`; decimal weights 0.1/0.2 keep exact ties,
thresholds and the scale maximum; a re-anchored reversed ranking is refused; incomplete, foreign or out-of-scale verdicts end the chain and report
the declared fallback (and replay); inadmissible or reordered inputs refused;
replay equality and refusal of an edited call, a re-anchored truncation, stray
files, a reordered invocation and another route; run refusals before any call;
invocation rubric/guidance coherence; one row per admission refusal; unimplemented
kinds refused at admission and run; pinned `judge.rubric/v1` request, template,
prompt and response-schema digests; weights absent from the prompt; projection
bounds; AST guards on direct imports only (`rubric_rank.py` imports no
`metric_order`/`evaluation_metric` module; `replay.py`, `plan.py`, `kinds.py` and
`rubric_rank.py` import neither `agent.llm_bridge` nor `agent.judge.call`).
Transitive imports are not checked by the guard; replay makes no provider call
because it never invokes `run_judge_call`.

## Limitations

- `primary-advisors-llm/v1` `primary="metric_best"` is refused (`primary_rule_unavailable`):
  `StrategyItem` carries no metric facts and no metric-scored contract has a
  projector. It lands with the `tuning.output` projector (B6-9/B3), choosing the
  primary with `MetricOrder` over Health-valid formal results.

- Not reachable from a workflow until B6-8 (declaration in
  `AdaptorInstance.combine`, catalogue rows, invocation construction, evidence
  directory, fallback execution and the run-level call cap).
- `tuning.output` and `validation.output` have no projector, so rubric ranking of
  trained candidates is refused (B6-9/B3 multi-tuning).
