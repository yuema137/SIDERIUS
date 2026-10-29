# Workflow declarations

Scope: how to write, prepare and run a SIDERIUS workflow declaration in v1.1.0
with a coding agent (Professional or Assistant mode), and which features combine.
This page is a guide over the owning contracts; when a detail here and an owner
disagree, the owner wins:

| Subject | Owner |
| --- | --- |
| Declaration models, loop, stop conditions, adaptors | [`src/workflows/definition/`](../../src/workflows/definition/README.md), [declaration contract](../../src/workflows/definition/definition-contract.md) |
| Reusable preparation (`--reusable-request`) | [preparation contract](../../src/tools/candidate_prepare/candidate-prepare-contract.md) |
| Execution profiles, loop execution, literature adaptors | [candidate-worker contract](../../src/tools/candidate_worker/candidate-worker-contract.md) |
| Submit, status, cancel, stop/pause/resume | [operations contract](../../src/tools/candidate_operations/candidate-operations-contract.md) |
| LLM routes, judge routes, `max_judge_calls` | `src/workflows/llm_config.py` (`WorkflowLLMConfig`, `JudgeLLMConfig`) |
| Training settings | `src/workflows/run_config.py` (`WorkflowLaunchConfig`), `src/workflows/candidate_training_settings.py` |
| LLM aggregation strategies | [judge strategies contract](../../src/workflows/judge_strategies/judge-strategies-contract.md) |

Terms used below: an **iteration** is one pass of the research loop
(Interpret → Propose → Implement → Validate → Train & tune). A **tuning round**
is one training configuration planned and run inside Train & tune. A
**segment** is the part of a run before or after a pause and resume. API names
keep their historical spelling (`completed_bodies`, `min_completed_bodies`,
`final_iteration`, `max_rounds`).

## 1. What a declaration is

A declaration is a short Python file, conventionally `workflow.py` in your
external project. It is parsed as restricted static Python, never executed
(`src/workflows/definition/source.py`):

- an optional docstring, then exactly one `from workflows.definition import ...`
  of allowlisted names (no aliases, no wildcard);
- exactly one final statement `document = ReusableWorkflowDocument(...)` (or
  `WorkflowDocument(...)`); the name must be `document`;
- only constructor calls, literals and tuples. Lists and dicts are refused,
  except inside `training_settings` and `literature_settings`.

Validation is pure: it checks structure and connections, not whether the task,
data or plugins exist, and it never calls a model. The console editor
additionally limits the file to 32 KiB.

There are two document formats:

| Format | Class | Task references | Externals | Run route |
| --- | --- | --- | --- | --- |
| Reusable (v2, recommended) | `ReusableWorkflowDocument(definition=ReusableWorkflowDefinition(...))` | `ReusableTaskReferences(manifest, data_root)`; no workspace | Mostly `ManagedCandidateBinding`: the preparation step generates the values | `python -m tools.candidate_prepare --reusable-request` then `tools.candidate_operations submit` |
| Concrete (v1) | `WorkflowDocument(definition=WorkflowDefinition(...))` | `TaskReferences(manifest, data_root, workspace)` | `ExternalBinding(id, contract, location)`: you supply every JSON input file | `tools.workflow_preview` then a `CandidateRunRequest` for `tools.candidate_worker` or `tools.candidate_operations submit` |

Use the reusable format unless you need a profile that only the concrete
format runs (see the [profile matrix](#8-execution-profiles-what-combines)).
Relative `manifest` and `data_root` resolve against the request's
`project_root`, not the working directory.

A declaration is a list of `NodeInstance(id, capability, request)`. The
capabilities are `interpretation`, `literature`, `proposal`, `implementation`,
`validation` and `tuning`. A node's `request` is either an
`ExternalRequest(binding=...)` (the input comes from outside) or a
`ProtocolRequest(protocol=..., arguments=(ArgumentBinding(name, source), ...))`
that maps earlier results (`ResultSource(node=...)`), externals
(`ExternalSource(binding=...)`) or adaptor outputs (`AdaptorSource(adaptor=...,
index=...)`) into the node's input. `positions` only stores the console layout.

Starting points in [`examples/workflow_declarations/`](../../examples/workflow_declarations/):

| File | Shape |
| --- | --- |
| `managed_reusable_candidate.py` | Propose → Implement → Validate, reusable |
| `reusable_training.py` | Propose → Implement → Validate → Train & tune, reusable |
| `reusable_candidate.py` | Reusable shape with a literal external; authoring and resolution only, not a preparation starting point |
| `native_training.py` | Script that writes a concrete (v1) four-stage document and its JSON inputs; never launches |
| `research_loop_request_input.py` | Interpreted research loop that pauses and asks you when a stop condition is met (added by a parallel PR) |
| `literature_debate_judged.py` | Several literature reviews aggregated by a debate judge before proposals (added by a parallel PR) |

## 2. Externals

`definition.externals` lists every input that does not come from another node.
Every declared external must be used, and every used one must be declared.

`ManagedCandidateBinding(id, contract)` values are generated by preparation
from the task, the LLM profile and the document's own settings. Supported
contracts: `proposal.input`, `storage`, `native-training.settings`,
`literature.input` (requires `literature_settings`), `interpretation.input`,
and, in the interpretation profile, the optional protocol arguments
`optional.text` (`data_dir`), `optional.task-composition-ref`,
`optional.expert-advice` (`human_advice`), `optional.expert-context`,
`optional.constraint-context` and `optional.parameter-rules`.

Treat literal `ExternalBinding` files as unsupported in reusable
preparation: the [preparation contract](../../src/tools/candidate_prepare/candidate-prepare-contract.md)
rejects literal externals before allocation, and `storage`, `proposal.input`
and `native-training.settings` must always be managed. Literal files are the
concrete (v1) format's mechanism.

`interpretation-to-proposal` takes `output`, `storage`, and the optional
`data_dir`, `task_composition_ref`, `human_advice`, `expert_context`,
`constraint_context` and `workflow_parameter_rules`
(`src/workflows/definition/catalog.py`). In
`native-interpretation-candidate/v1` these are framework-managed: preparation
fills `human_advice` from `preparation_options.proposal_advice` and always sets
`expert_context` to `null` (`src/tools/candidate_prepare/reusable_interpretation.py`).
There is no supported way to supply your own `expert_context` in v1.1.0; carry
outside findings as proposal advice instead (see
[section 9](#9-two-step-scenario-literature-findings-then-a-loop)).

## 3. LLM configuration

The run's model routes come from the LLM profile JSON named by the request
(`llm_config_file`), validated as `WorkflowLLMConfig`. Node slots are
`interpret`, `data_analysis`, `propose` (`comparison`/`reasoning`/`proposing`),
`implement`, `validate`, `tune` (`planner`/`reflector`) and `lit_review`
(`main`/`search`; falls back to `interpret` when absent). An omitted slot uses
the node's built-in default. See the [configuration guide](../../configs/llm/README.md).

Judges are a separate `judge` block, required only when the declaration uses an
LLM judge:

```json
{
  "judge": {
    "stop":      {"provider": "openai", "model_id": "...", "max_output_tokens": 2000, "max_retries": 1},
    "aggregate": {"provider": "openai", "model_id": "...", "max_output_tokens": 4000, "max_retries": 1},
    "debate":    {"provider": "openai", "model_id": "...", "max_output_tokens": 4000, "max_retries": 1},
    "max_judge_calls": 40
  }
}
```

- Each route (`JudgeRouteConfig`) requires `provider`, `model_id` and
  `max_output_tokens`; `max_retries` is a finite count of total transport
  attempts; `reasoning_effort` is optional (OpenAI only). No central default
  is substituted for a judge model.
- `stop` serves `JudgeStop`; `aggregate` serves `rubric-rank/v1`,
  `judge-merge/v1` and `primary-advisors-llm/v1`; `debate` serves
  `debate-judge/v1`. A strategy names its slot with `route_slot`.
- Declare only the slots you use; an empty `judge` block is refused.
- `max_judge_calls` (integer > 0) is optional in the schema but every judge
  consumer requires it. Admission refuses the run before any node starts when
  the static judge call bound exceeds it:
  `sum(adaptor strategy bound) × final_iteration + JudgeStop bound ≤ max_judge_calls`
  (`final_iteration` is 1 without a loop).
- The run lock records the judge routes and cap; a continuation under a
  different route or cap is refused.

## 4. Training settings

A declaration with a `tuning` node must set `training_settings` and declare
exactly one `ManagedCandidateBinding(contract="native-training.settings")` bound
to the tuner's `settings` argument. Only the default profile and
`native-interpretation-candidate/v1` accept `training_settings`.

`training_settings` is a sparse JSON-shaped mapping validated as
`CandidateTrainingSettings`: a `launch` mapping of `WorkflowLaunchConfig`
fields plus startup controls (`data_scope`, `health_gate_enabled` (default
`true`), `health_gate_files`, `order_strategy_override`, `file_order_override`,
`enable_structured_health_feedback` (default `false`)). External
`health_checks_config` is refused in reusable capture; task-composed Health
still applies. Unset fields take the `WorkflowLaunchConfig` defaults below.

| `launch` field | Default | Meaning |
| --- | --- | --- |
| `is_trial` | `false` | `true`: tuning rounds may run in Trial mode on sampled data, and the last tuning round is Formal. `false`: single-file mode, which trains only for tasks whose dataset profile declares the TIDMAD topology; other tasks are refused before training. The shipped templates and examples (for example `reusable_training.py`) set `true`; the schema default stays `false`, so set it explicitly. |
| `max_rounds` | `10` | Tuning rounds per iteration (the training configurations Train & tune plans and runs). With `is_trial: true`, `force_formal_round: true` and `max_rounds: 1`, Trial-only overrides are refused; use at least 2. |
| `force_formal_round` | `true` | Force a Formal tuning round. |
| `trial_time_budget_minutes`, `formal_time_budget_minutes` | unset | Wall-time budget per Trial / Formal tuning round attempt. |
| `trial_vram_budget_gb`, `formal_vram_budget_gb` | unset | VRAM ceilings per mode. |
| `max_epochs` | unset | Epoch ceiling for both modes. |
| `trial_max_epochs`, `formal_max_epochs` | unset | Per-mode epoch ceilings; unset means `max_epochs` governs. |
| `trial_portion`, `train_portion`, `eval_portion` | unset | Trial data portions. Unset leaves them to the tuning planner; a typed value fixes them for the experiment. |
| `formal_portion` | `0.1` | Formal sampling portion. |
| `formal_train_portion`, `formal_eval_portion` | `1.0` | Formal training / evaluation portions. |
| `training_validation_portion` | unset | Optional seeded snapshot for per-epoch validation loss (`0 < value ≤ 1`). |
| `attempts_per_round`, `attempts_per_formal_round` | `3`, `5` | Attempts per Trial / Formal tuning round. |
| `max_fail_rounds` | `3` | Failed tuning rounds tolerated. |
| `healthgate_mode` | unset | `blocking` (a Health failure blocks) or `observe_only` (recorded only). |
| `result_authority` | unset | `scientific` or `diagnostic`. `observe_only` with `scientific` is refused. Declare both: the console's run review refuses a workflow that omits either, and the templates declare `blocking` + `scientific`. |
| `human_advice_tune` | unset | Advice to Train & tune (the only advice field accepted here). |
| `allowed_output_types` | from `preparation_options` | `classifier` and/or `regressor`; a conflicting value is refused. |

The full accepted set is `SUPPORTED_LAUNCH_FIELDS` in
`src/workflows/candidate_training_settings.py`. Fields in
`INACTIVE_LAUNCH_FIELDS` (for example `max_iterations`, `run_seed`,
`lit_review_enabled`, `human_advice_propose`) are refused when set to a
non-default value; the run seed belongs to the run request
(`tools.candidate_operations submit --run-seed N`).

## 5. Advice per step

| Step | Where |
| --- | --- |
| Propose | `preparation_options=CandidatePreparationOptions(proposal_advice=...)`; in the interpretation profile it reaches the proposer through `interpretation-to-proposal`'s `human_advice` |
| Implement | `preparation_options.implementation_advice` |
| Validate | `preparation_options.validation_advice` |
| Train & tune | `training_settings["launch"]["human_advice_tune"]` |
| Interpret | no field in the reusable format |
| Literature review | no advice field; distinguish reviews by `root_papers` and `dynamic_search` in `literature_settings` |
| Later iterations of a paused loop | `write-loop-resume --advice-file FILE`: given to the proposal step of every iteration in the resumed segment, after the declared advice; replaces an earlier resume's advice; 1 to 4000 characters |

`preparation_options.allowed_output_types` restricts proposals to
`classifier`, `regressor` or both. Advice is part of the declaration digest.

## 6. Research loop

A loop repeats the five-node interpretation profile. Set
`execution_profile="native-interpretation-candidate/v1"` and add:

```python
loop=AuthoredLoop(
    final_iteration=5,
    feedback=LoopFeedback(
        source=ResultSource(node="fit"),        # the tuning node
        target="interpret",                      # the interpretation node
        protocol="tuning-to-interpretation",
        history="native-research/v1",
    ),
    stop_conditions=(
        NoImprovementStop(completed_bodies=2, on_met="request_input"),
        MetricThresholdStop(metric_id="<task metric id>", threshold=0.95),
    ),
),
```

- `final_iteration` (> 0) is a ceiling, not a promise that every iteration
  runs.
- Stop conditions (at most one of each kind) are checked after each completed
  iteration below `final_iteration`; the final iteration is never judged.
  Deterministic conditions are any-of in declared order; `JudgeStop` is
  consulted only when no deterministic condition fired.

| Condition | Fields | Met when |
| --- | --- | --- |
| `NoImprovementStop` | `completed_bodies` (iterations; > 0 and < `final_iteration`) | that many consecutive completed iterations without a strict improvement of the best result so far |
| `MetricThresholdStop` | `metric_id` (must equal the task's composed metric id), `threshold` (finite) | the best result reaches `threshold` in the task metric's direction (direction is never declared) |
| `JudgeStop` | `criterion` (1..2000 characters), `min_completed_bodies=1` (< `final_iteration`), `on_failure="fail"` or `"continue"` | the `judge.stop` model answers "stop". At most `final_iteration - min_completed_bodies` calls, counted against `max_judge_calls`. |

Every condition has `on_met`:

- `"stop"` (default): the loop completes early.
- `"request_input"` ("Pause and ask me"): the segment ends `paused` with an
  input request. The status receipt holds only numbers
  (`InputRequestSummary`: iteration, final iteration, metric id and direction,
  best result and its iteration, iterations without improvement, iterations
  since the last request). After a resume, a `request_input` condition counts
  from the iteration where it last asked, so it does not ask again at once.

At one boundary, a met `stop` condition wins over a met `request_input`
condition, which wins over the judge.

Loop controls, all with `--store-config FILE --operation-id UUID`:

```bash
.venv/bin/python -m tools.candidate_operations stop-loop  --store-config store.json --operation-id OP
.venv/bin/python -m tools.candidate_operations pause-loop --store-config store.json --operation-id OP
.venv/bin/python -m tools.candidate_operations review-loop-resume --store-config store.json --operation-id OP
.venv/bin/python -m tools.candidate_operations write-loop-resume --store-config store.json --operation-id OP \
  --output loop-resume.json --advice-file advice.txt
.venv/bin/python -m tools.candidate_operations submit --store-config store.json --request loop-resume.json
```

`stop-loop` ends the run after the current iteration (terminal). `pause-loop`
ends the current segment after the current iteration. `write-loop-resume`
reviews the paused segment and writes the resume request once (an existing
output file is refused); `submit` launches it as a new operation with a new
UUID. `cancel` stops at once and cannot be resumed. Stopped, failed, timed-out,
cancelled or condition-completed loops cannot be resumed. `review-resume`
(without `loop`) is for captured native chains and refuses a loop.

## 7. Literature reviews and LLM aggregation

**One review before one candidate** (reusable or concrete):
`execution_profile="native-literature-candidate/v1"`, a `literature` node with a
managed `literature.input` binding and explicit `literature_settings`, feeding
`literature-to-proposal(output=ResultSource(review), proposal_input=<managed
proposal.input>)`. `literature_settings={}` selects native defaults. Supported
keys: `root_papers` (list of `PaperSource(source_type, identifier,
verbosity)`, `source_type` `arxiv`, `doi` or `openreview`; `local` is refused
here), `dynamic_search` (`DynamicSearchConfig`; `enabled` defaults to `true`,
so `{}` searches and needs network), `confidence_rubric`, `findings_verbosity`
(0 or 1), `synthesis`.

**Several reviews aggregated by an LLM** (`native-literature-judged/v1`).
This profile runs only from a concrete (v1) `WorkflowDocument` passed in a
`WorkflowPreviewRequest(execution_profile="native-literature-judged/v1")`, then
a `CandidateRunRequest` for `python -m tools.candidate_worker --request` or a
`candidate` operation. The LLM strategy constructors are not in the
`workflow.py` source allowlist, so write this document as JSON (or build it in
a Python script) rather than as a `workflow.py` declaration; reusable
preparation and the console do not accept adaptors. The shape:

- one or more `literature` nodes, each with its own `literature.input` file;
- one adaptor (`definition.adaptor_format="siderius.adaptors/v1"`):
  `AdaptorInstance(id, inputs=(InputPort(name="reviews",
  contract="literature.output", cardinality="many", max_items=N),),
  bindings=(PortBinding(port="reviews", sources=(ResultSource(...), ...)),),
  combine=<LLM strategy>, select=..., distribute=...)` binding every review
  exactly once; `max_items` is required;
- one proposal per adaptor output through
  `literature-to-proposal(output=AdaptorSource(adaptor=<id>[, index=i]),
  proposal_input=<external seed>)`, each with its own implementation and
  validation. No tuner, loop or route is admitted.

COMBINE strategies (`workflows.definition.llm_strategies`; common fields
`route_slot` (`aggregate` or `debate`), `max_calls` (> 0), `guidance`
(`task_blocks` or `none`), `criterion` (1..2000 characters), `on_failure`
(`"fail"` or a deterministic `Fallback`)):

| Strategy | Specific fields | Output | Static call bound |
| --- | --- | --- | --- |
| `rubric-rank/v1` | `rubric` (from the task's `rubrics:`), `scoring` `per_item`/`batch`, `repeats` 1..3 | ranking | `per_item`: N × repeats; `batch`: repeats |
| `judge-merge/v1` | `synthesize_count` (1..64), `min_parents` (≥ 2) | merged review(s) | 1 |
| `debate-judge/v1` | `rounds` 1..4, `critic`, `judge_output` `rank`/`synthesize`, `synthesize_count` iff synthesize | ranking or merged review(s) | rounds × (N + critic) + 1 |
| `primary-advisors-llm/v1` | `primary`, `primary_item`, `advice` | one revised review | see the judge strategies contract |

N is the number of reviews; a strategy lists every review in one call, so
N ≤ 16. `max_calls` must be at least the static bound.

SELECT and DISTRIBUTE:

- A ranking feeds `AllSelect()` (`all/v1`) or `TopKSelect(k=...)`
  (`top-k/v1`); a merge or synthesize feeds only `all/v1`.
- `SingleDistribute()` (`single/v1`) sends one value to one proposal (no
  `index`). `PerItemDistribute(count=M, on_short="skip"|"fail")`
  (`per-item/v1`) sends output `i` to the proposal with `index=i`, `0..M-1`.

To keep only the most important findings for one proposer, use
`debate-judge/v1` with `judge_output="synthesize", synthesize_count=1`, or
`judge-merge/v1` with `synthesize_count=1`, plus `all/v1` and `single/v1`.

Network: every provider call needs network access in the candidate sandbox.
Remote `root_papers` or enabled `dynamic_search` additionally require explicit
`candidate_network: true` (reusable) or `network: true` (worker request); it is
never enabled automatically.

Cost drivers: the number of reviews (each runs the review's own LLM calls, plus
search calls when dynamic search is on); the judge strategy's call bound;
`per-item/v1` count M (each output runs a full Propose → Implement → Validate
branch). In a loop: `final_iteration` × the per-iteration calls and GPU time,
`max_rounds` tuning rounds per iteration, and up to
`final_iteration - min_completed_bodies` stop-judge calls.

## 8. Execution profiles: what combines

| `execution_profile` | Format | Training | Loop | Literature | LLM aggregation |
| --- | --- | --- | --- | --- | --- |
| unset | reusable, concrete | optional | no | no | no |
| `native-proposal-fanout/v1` | reusable, concrete | no | no | no | no |
| `native-proposal-families/v1` | reusable, concrete | no | no | no | no |
| `native-literature-candidate/v1` | reusable, concrete | no | no | one review | no |
| `native-interpretation-candidate/v1` | reusable, concrete | optional | yes (requires the five-node shape with tuning) | no | `JudgeStop` only |
| `native-literature-collection/v1`, `native-literature-split/v1` | concrete | no | no | several / one | deterministic only |
| `native-literature-judged/v1` | concrete | no | no | several | yes |
| `native-proposal-judged/v1` | concrete | no | no | no | yes, over proposals |

In v1.1.0 a loop and literature-judged aggregation cannot run in one
declaration. Use the two-step scenario below.

## 9. Two-step scenario: literature findings, then a loop

1. **Run A: literature, judged.** Write a concrete document with
   `execution_profile="native-literature-judged/v1"`, several reviews that
   differ by `root_papers` and `dynamic_search`, and a synthesizing judge
   (`debate-judge/v1` with `judge_output="synthesize", synthesize_count=1`, or
   `judge-merge/v1`), `all/v1`, `single/v1`. The example
   `examples/workflow_declarations/literature_debate_judged.py` shows this shape.
   Preview it, build the `CandidateRunRequest`
   ([worker README](../../src/tools/candidate_worker/README.md)), and submit it
   as a `candidate` operation. The merged review is recorded in the adaptor
   record of the run's graph trace.
2. **Carry the findings forward.** Read the merged review's findings from run
   A's adaptor record and write them as plain text.
3. **Run B: the loop.** Use an interpretation-profile loop
   (`examples/workflow_declarations/research_loop_request_input.py` shows the
   loop with `on_met="request_input"`). Put the findings text in
   `preparation_options.proposal_advice` of run B's `workflow.py`; it reaches the
   proposer of every iteration through `interpretation-to-proposal`'s
   `human_advice` argument, which the declaration binds to a managed
   `optional.expert-advice` external. `proposal_advice` has no field-level length limit, but the
   whole source is limited to 1 MiB (32 KiB when edited in the console), and
   the text is part of the declaration digest. To add or revise findings
   later, pause the loop and resume with `write-loop-resume --advice-file`
   (1 to 4000 characters; replaces an earlier resume's advice).

An integrated literature + loop profile is planned for v1.2.

## 10. Viewing a hand-written workflow.py in the console (experimental)

Add an `editor_projects` entry (`project_id`, `project_root`, `source_file`,
`recovery_directory`) to the console configuration and restart it; see
[workflow authoring](../../src/tools/workflow_authoring/README.md) steps 3-4.
The Workflow Editor then shows the file, including its research loop and stop
conditions, and can save edits back to it (it rewrites the file in canonical
form; re-read `workflow.py` afterwards). Adaptors and LLM judges are not drawn,
and the console lists no literature-judged profile. The file, not the screen,
is the authority for what runs.

## 11. Known limitations (v1.1.0)

- No per-review advice for literature reviews; reviews differ only by their
  `literature_settings`.
- No wall-clock stop condition: `StopCondition` is `metric_threshold`,
  `no_improvement` or `judge`. Bound time with training budgets and
  `final_iteration`.
- A loop and literature-judged aggregation cannot be combined; integrated
  literature + loop is planned for v1.2.
- No supported input path for your own `expert_context` in the interpretation profile; use proposal advice.
- Advice for the interpretation step has no field in the reusable format.
