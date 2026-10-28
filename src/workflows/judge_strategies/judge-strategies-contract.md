# `workflows/judge_strategies/` — LLM COMBINE strategies for adaptors

Technical contract for the LLM strategy framework (advanced design B2, PR B2-6).
Source and tests determine current behavior. Implemented kind: `rubric-rank/v1`.
The other three declared kinds (`debate-judge/v1`, `primary-advisors-llm/v1`,
`judge-merge/v1`) are refused until their PRs (B2-7, B2-8, B2-9) land. No
adaptor can declare or run an LLM kind yet: the adaptor wiring (B6-8) makes the
union declarable in `AdaptorInstance.combine` and calls this package.

## Scope and owners

| Owner | Responsibility |
| --- | --- |
| `workflows/definition/llm_strategies.py` | Declarations: `LLMStrategy` = discriminated union (`kind`) of `DebateJudgeStrategy`, `RubricRankStrategy`, `PrimaryAdvisorsStrategy`, `JudgeMergeStrategy`, all with common `route_slot`, `max_calls`, `on_failure: "fail" \| Fallback`, `guidance`, `criterion` |
| `admission.py` | `admit_llm_strategy` (pure, no I/O) |
| `projection.py` | `ITEM_PROJECTORS` (contract → projector), `project_item`, `strategy_items` |
| `kinds.py` | `IMPLEMENTED_KINDS`, `implemented_kind`, `strategy_call_bound` |
| `plan.py` | `PlannedCall`, `StrategyKind`, `strategy_route`, `call_request`, `call_path`, `decide` (shared by run and replay) |
| `rubric_rank.py` | `rubric-rank/v1`: `call_bound`, `plan_call`, `fold` (pure) |
| `run.py` | `run_llm_strategy`: the only provider effect in the package |
| `replay.py` | `replay_llm_strategy`: readback, imports no provider path |
| `models.py` | `StrategyItem`, `StrategyInvocation`, `invocation_sha256`, `RubricScore`, `CriterionValue`, `ItemRanking`, `StrategyOutcome`, `StrategyEvidence`, `StrategyResult`, `StrategyAdmission`, `StrategyRefusal`, `StrategyError` |
| `agent/judge/rubric_template.py` | `RUBRIC_TEMPLATE` (`judge.rubric/v1`, role `scorer`, usage label `judge.rubric-rank`, response `RubricVerdict`) |
| `agent/schemas/judge.py` | Call-level types: `RubricScoringRequest` (`CallContent` kind `rubric_scoring`), `JudgedItem`, `ItemProjection`, `ProjectedField`, `RubricVerdict` (`CallPayload` kind `rubric`) |

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
| `unbounded_port` | a `many` port without `max_items`: the static call bound needs the item capacity (`one` port = 1, `many` port = `max_items`) |
| `mixed_contracts` | ports of more than one contract |
| `unprojectable_contract` | no projector in `ITEM_PROJECTORS` (v1: `proposal.output`, `literature.output`) |
| `output_contract_mismatch` | a ranking passes values through, so the output contract must equal the input contract |
| `select_incompatible` | a rubric ranking feeds only `all/v1`, `top-k/v1` or `threshold/v1` with `basis="rubric"` |
| `metric_scored_reorder` | Q-B2-2: over `METRIC_SCORED_CONTRACTS` items an LLM ranking may feed only `all/v1` or `threshold(basis="rubric")`, never `top-k/v1` (B6 `select` re-checks at run time) |
| `call_bound_exceeds_max_calls` | `strategy_call_bound(strategy, capacity) > max_calls` |

`cardinality` bounds combining kinds' output count and is not used by a ranking
kind. `on_failure` fallback admissibility is B6's: it validates
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

Every item is scored, including a single item (N ≥ 1): its rubric total is a
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
`weighted_total = Σ weight × median` in rubric criterion order; ranking by
`weighted_total` descending, equal totals in input order. `RubricScore` is not a
metric: it never enters `MetricOrder`, tuning records, the incumbent, Health or
stop conditions.

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
3. `decide`: all decided → `StrategyOutcome(status="decided", ranking=fold(...))`;
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

## Validation evidence

`tests/unit/workflows/test_judge_strategies.py`: hand-computed weighted totals
and input-order ties; per-criterion median of repeats; LLM-supplied total
refused; incomplete, foreign or out-of-scale verdicts end the chain and report
the declared fallback (and replay); inadmissible or reordered inputs refused;
replay equality and refusal of an edited call, a re-anchored truncation, stray
files, a reordered invocation and another route; run refusals before any call;
invocation rubric/guidance coherence; one row per admission refusal; unimplemented
kinds refused at admission and run; pinned `judge.rubric/v1` request, template,
prompt and response-schema digests; weights absent from the prompt; projection
bounds; AST guards (rubric fold imports no metric owner; replay, plan, kinds and
the fold import no provider path).

## Limitations

- Not reachable from a workflow until B6-8 (declaration in
  `AdaptorInstance.combine`, catalogue rows, invocation construction, evidence
  directory, fallback execution and the run-level call cap).
- `tuning.output` and `validation.output` have no projector, so rubric ranking of
  trained candidates is refused (B6-9/B3 multi-tuning).
