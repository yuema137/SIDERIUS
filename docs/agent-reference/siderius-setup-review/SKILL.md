---
name: siderius-setup-review
description: Guide SIDERIUS setup from a short problem description and data location through an external task package, experiment and launch instructions. Use when a user wants to try a new task or review an existing setup; configuration review is optional and arbitrary workflow control flow is not automatically reviewed.
---

# SIDERIUS setup review

Use the [human setup guide](../../../src/tools/setup_review/README.md) to explain
the route and the [command reference](../../../src/tools/setup_review/usage.md)
for exact commands. Read the relevant linked contract when a report or refusal
needs investigation. The source and validated schemas own runtime behavior;
this skill adds guidance, not another configuration authority.

Professional and Assistant describe who leads the setup decisions. Both use the
same public preparation and execution owners below. Select the execution route
separately: a candidate, optional native training, an
[authored research loop](#authored-research-loops) over saved source, or a native
iterative chain.

## Start from the user's problem, not a prepared manifest

A brief such as "I have MNIST images and labels in /data/mnist; help me build and
evaluate a digit classifier" is enough to begin. Do not require the user to name
this skill, supply configuration files or understand the repository architecture.
Own the preparation work and guide the decisions using the current source and
references below. A described task is not authorization for unbounded API/GPU work.

1. Inspect available local data metadata and the selected installation. Follow
   [installation](../../getting-started/installation.md) for the checkout's own
   environment and explain missing dependencies, supported hardware and required
   credential names. Reuse existing data; never print key values or put them in
   generated files. Distinguish a tool sandbox restriction from a missing host
   capability. Do not claim setup succeeded without actually checking it.
2. Resolve consequential scientific choices with the user: inputs and targets,
   leakage-safe split unit, workflow validation versus held-out final test, metric
   and any task-specific validity rules. Propose concrete choices with reasons;
   reuse choices already given instead of making the user answer them again.
3. Author or adapt the [task package](../../reference/task-composition.md) in a
   new external project. For tabular classification data in CSV files, start
   from `examples/task_templates/csv_classification`: copy the folder and
   change its `EDIT HERE` lines as its [README](../../../examples/task_templates/csv_classification/README.md)
   lists. It already supplies the data path, metric, complete Health
   declaration and a parameter lock. Inspect an existing task before reusing
   it; a similarly named dataset does not guarantee matching labels, splits or
   objectives.
   Implement its required adapters through the published contracts. Explain the
   resulting scientific choices without asking the user to handwrite schemas.
   For the local console, keep one package per folder under the console
   workspace, `siderius_workspace/tasks/<name>/` (manifest, plugins and
   declarations together; data stays in `siderius_workspace/data/<task_id>/`), and
   register it with `python -m tools.candidate_console add-task --config <console.json>
   --manifest <manifest>`. It writes the task entry with
   `task_read_only=[<package folder>]` and explicit starter resource values, then
   runs `check`, which refuses a manifest-referenced file outside the run sandbox
   mounts and names it. Show the user the printed entry for review and tell them to
   restart the console. A package elsewhere needs `--external`. See the
   [add-task contract](../../../src/tools/candidate_console/console-contract.md#registering-a-task-add-task).
4. Prepare the experiment separately: model routing, workflow, data exposure,
   iterations, budgets and output workspace. Recommend the
   [Luna test profile](../../../configs/llm/README.md) for an initial process check,
   while honoring an explicitly chosen model. Keep keys external. For v1.1.0 the
   recommended route is a saved workflow declaration, `workflow.py` in the external
   project, prepared with `.venv/bin/python -m tools.candidate_prepare --reusable-request PATH`
   and launched with `.venv/bin/python -m tools.candidate_operations submit --store-config FILE --request FILE`
   (see [Reusable candidates and native training](#reusable-candidates-and-native-training)).
   A saved `run_chain.sh` launch script and its settings remain supported for
   companion and paper tasks. Either way, do not reimplement framework training.
5. Run the applicable [offline checks and command preview](../../getting-started/first-run.md)
   in the selected environment, resolve actual failures, and give the user the
   saved task/experiment paths, important effective settings, exact command and
   result locations. Offer the optional review route below. Continue to a real
   run only within the user's existing execution and spending authorization.

If data, tools or access are unavailable, state the specific missing prerequisite
and continue independent preparation. Do not present a plan or unexecuted command
as a completed setup. Manual authoring remains available for users who prefer it.

## Preserve the user's intended run

- Reuse the user's already stated task, data location/split, provider/model,
  hardware and budget choices. Ask only for consequential missing decisions.
  Do not substitute a documentation example for a model or spend limit the user
  selected. Do not infer the authorized duration from a training budget.
- Keep task meaning separate from experiment settings. Build and edit files in
  an external project; leave repository templates and archived runs untouched.
  Name the task manifest, data directory, LLM config, optional advice, launch
  request and new result workspace explicitly.
- Use the selected installation's own Python environment and declared plugins.
  Historical paper policies must be selected from exp; do not recreate them as
  framework defaults or silently install a historical fallback.

## Offer the appropriate route

Direct standard launch remains valid without this skill or a review receipt.
When the user wants the optional reviewed route, prepare a fresh standard
single-iteration request and follow this sequence:

1. Inspect declarations and resolve the trusted task/providers using the task
   check with `--resolve-task-settings`. Preserve failures and fix their actual
   cause. Do not remove the application's sandbox to make a check pass.
2. Inspect the intended execution environment with `--bind-launch`. Explain
   resolved defaults, conditional/unknown values and remaining checks. Hardware
   discovery, key presence and a parsed configuration do not prove a real run
   will succeed. If the agent's tool context restricts hardware or namespaces,
   identify that distinction before calling it a task or host failure.
3. Let the user select LLM review or an explicit skip, honoring existing session
   choices. An unperformed review is not a skip receipt. Send only the authorized
   saved review packet to the selected provider; do not send data or secrets.
4. Save the [reviewed launch request](../../../src/tools/setup_review/reviewed-launch.md#request-recipe)
   with exact report/receipt hashes and necessary finding dispositions. Show the
   user the actual settings and the command, working directory and interpreter
   that will execute them. An acknowledgement cannot override changed inputs.
5. Launch only within the user's authorization for real API/GPU work. Reading
   this skill grants no budget or external-action permission. Use fresh reports
   and, when necessary, a fresh run workspace after a bound input changes.

For [external orchestration](../../../src/tools/orchestration_setup/README.md),
help prepare the documented agent instructions, explicit caller and sandbox.
The standard reviewed-launch gate does not review arbitrary caller control flow;
do not silently replace the user's orchestration with a fixed workflow.

## Report what actually happened

Distinguish declaration inspection, task composition, environment discovery,
LLM review/skip, launch authorization and successful scientific execution.
Inspect the run's manifest, records and actual result files; a zero process exit
or matched launch check alone is insufficient. Report failed/no-record runs as
such, without changing scientific checks just to obtain a successful status.

Give the user exact paths for saved task/experiment files, the launch command,
run status and results. Explain one requested parameter change and which files
and reports must be saved again. Keep README prose concise and link detailed
schema/identity/error contracts instead of copying them into the human entry.

Task composition does not select local versus complete external evaluation.
Before calling local inference readiness complete, check the task's
[output inventory requirement](../../reference/model-output-retention.md).
Workflow and direct tuner startup enforce that route-specific prerequisite;
a composition-only review does not certify it or the eventual output files.

## Reusable candidates and native training

When the user selects a reusable proposal/implementation/validation candidate,
Professional and Assistant routes both use
`tools.candidate_prepare.prepare_reusable_candidate` or
`python -m tools.candidate_prepare --reusable-request PATH`. Author source and
request in the external project; follow the
[shared preparation contract](../../../src/tools/candidate_prepare/candidate-prepare-contract.md#managed-reusable-preparation)
and [operator steps](../../../src/tools/candidate_prepare/README.md#prepare-several-runs-from-one-workflow).
Keep task references/advice in authored v2 source and allocate an explicit fresh
UUID under the selected runs root. Do not edit generated v1 input or pass an
existing envelope as resume. Require top-level prepared success; partial requests
are diagnostics. Preparation is offline but imports trusted task code and grants
no effectful launch budget. For an authorized candidate launch, use
`select_reusable_preparation` immediately after publication (or a previously
retained selection), then `build_reusable_operation(config, selection, request_id)`.
Save the submission outside the envelope and call existing `submit_operation` or
CLI `submit --request`. Follow the [operation contract and recipe](../../../src/tools/candidate_operations/candidate-operations-contract.md#retained-reusable-candidate-operations).
The builder and admission/dispatch verify original-v2 provenance; direct worker
launch checks resolved-v1 inputs only. Do not hash CLI stdout or require human
digest bookkeeping. Recovery retries the same saved UUID/payload, never a newly
selected/reconstructed request. Distinguish captured source from current edits,
prepared from admitted from native accepted/rejected, and candidate outputs from
training/scientific results. For browser preparation and retained-capture
selection, follow the [console saved-source steps](../../../src/tools/candidate_console/README.md#prepare-saved-source-or-open-an-existing-run).
The GUI uses the same preparation and operation owners; preparation and candidate
launch remain separate explicit actions. Source-declared native training uses the
[training inspector](../../../src/tools/candidate_console/README.md#edit-reusable-training-settings)
or ordinary source editing. Keep sparse settings in saved source; completion is
not scientific validity. An authored loop can be paused and resumed at completed
iterations; other candidates have no resume. See below.

## Authored research loops

A saved reusable workflow over the five-node interpreted training body
(Interpret → Propose → Implement → Validate → Train & Tune) may declare an
`AuthoredLoop` that repeats the body. Follow the
[declaration contract](../../../src/workflows/definition/definition-contract.md#authored-loop)
for fields and stop conditions, and the
[worker contract](../../../src/tools/candidate_worker/candidate-worker-contract.md#declared-finite-research-body)
for execution. Preparation and launch are those of any saved source above.

- Assistant: propose `final_iteration` and whether a metric threshold or
  no-improvement stop is scientifically meaningful, with reasons. Professional:
  implement the user's stated values exactly. `final_iteration` is a ceiling,
  not a budget estimate.
- A `MetricThresholdStop.metric_id` must equal the task's composed metric id;
  read it from the task package, never guess. Direction comes from the task's
  metric, never from the declaration. A mismatch refuses at worker admission,
  not at editor Review.
- If the user edits the loop in the console's Workflow tab, re-read `workflow.py`
  before changing it; the editor rewrites the file in canonical form.
- Stop (run-wide, terminal) and Pause (this segment) take effect at the next
  completed-iteration boundary; an acknowledgement is not the outcome. From
  code or the CLI follow the
  [loop control recipe](../../../src/tools/candidate_operations/candidate-operations-contract.md#control-an-authored-loop-from-code-or-the-cli);
  CLI `review-resume` is for native chains only. Resume launches paid work and
  needs the same authorization and provider credentials as Launch. Failed,
  stopped, timed-out or condition-completed loops cannot be resumed.
- Report per-iteration results as recorded; do not combine or rank iterations
  on the user's behalf unless asked.
- `on_met="request_input"` ("Pause and ask me") is valid on `MetricThresholdStop`,
  `NoImprovementStop` and `JudgeStop`; the default `"stop"` completes the loop.
  At a completed-iteration boundary a met `stop` condition wins over a met
  `request_input` one. `MetricThresholdStop` pauses once, when the incumbent first
  reaches the threshold. For a `JudgeStop` with `request_input`, a judge "stop"
  verdict means "ask the operator"; the judge prompt is unchanged. Tell the user
  that the run is paused, not finished, and that the loop continues only after
  an explicit Resume.
- Resume a paused loop with advice (`--advice-file` is optional; without it the
  Resume carries no advice). Run the review-and-save step from the selected
  checkout, with the same operation store config used to launch:

  ```bash
  .venv/bin/python -m tools.candidate_operations write-loop-resume \
    --store-config /absolute/path/operation-store.json \
    --operation-id <paused-operation-uuid> \
    --output /absolute/path/loop-resume.json \
    --advice-file /absolute/path/advice.txt
  ```

  The advice file is UTF-8 text, 1 to 4000 characters after trimming
  surrounding whitespace, with no control or format characters (CRLF is read as
  LF; a lone CR is refused). An invalid file exits 2 with `invalid_input_or_record`
  and nothing is written. The command reviews the paused segment and creates
  `--output` once; an existing file is refused with `output_exists` and left
  unchanged, so a retry after a lost response reuses the same request ID. It does
  not launch. Launch is then the ordinary
  `.venv/bin/python -m tools.candidate_operations submit --store-config ... --request /absolute/path/loop-resume.json`,
  which needs the same authorization and provider credentials as Launch.
  Authored loops are controlled by these CLI and Python routes, not by
  `review-resume`, which serves captured native chains only.

## Literature reviews aggregated by an LLM judge

Use this route only when the user wants several external literature reviews
combined into one proposal input by an LLM judge. Its execution profile is
`native-literature-judged/v1`. Follow the
[judge strategies contract](../../../src/workflows/judge_strategies/judge-strategies-contract.md)
for the strategy semantics and the
[declaration contract](../../../src/workflows/definition/definition-contract.md#adaptor-declarations-inert)
for the adaptor declaration (`siderius.adaptors/v1`, one `literature.output` input
port with a declared `max_items`, one combine strategy and one select strategy).
The admitted LLM combine kinds are `debate-judge/v1` (`DebateJudgeStrategy`;
`judge_output` `rank` or `synthesize`, `synthesize_count` required only for
`synthesize`), `rubric-rank/v1` (`RubricRankStrategy`; the rubric must come from
the task composition's `rubrics:`) and `judge-merge/v1` (`JudgeMergeStrategy`).
Declare `synthesize` with `synthesize_count: 1` when the proposer should receive one
merged review.

- Judge routes are operator configuration: `WorkflowLLMConfig.judge` in the LLM
  config, with the route slot the strategy declares (`aggregate` or `debate`). The
  route needs an explicit provider and model and a bounded output budget. Declare
  `judge.max_judge_calls`; launch refuses a run whose static call bound exceeds it,
  and refuses this profile when it is absent. Do not declare a route or cap the
  user has not chosen; the bound is `rounds × (N + critic) + 1` for `debate-judge/v1`, where `rounds` is the API field for debate rounds, not loop iterations
  ([judge strategies contract](../../../src/workflows/judge_strategies/judge-strategies-contract.md)).
- Network: remote paper roots, or enabled dynamic search, need an explicit
  `network=true` on the review request. Provider calls remain subject to the
  sandbox network policy. Do not enable network access on the user's behalf.
- The only worked example in the repository is
  `tests/unit/tools/candidate_worker/test_literature_judged.py`. Copy its shape,
  not a scientific choice from it.

## v1.1.0 limit: loops and literature-judged reviews do not combine

An authored loop is admitted only with `native-interpretation-candidate/v1`
(`admit_loop` in `src/tools/candidate_worker/loop_models.py`). The
literature-judged profile cannot carry a loop, so one declaration cannot have both.
Do not add a loop to a literature-judged declaration, and do not invent a combined
profile. The v1.1.0 workaround is two steps, and the operator must approve each
paid run:

1. Run A: the literature-judged workflow, with its judge synthesizing the key
   findings into one merged review (`synthesize_count: 1`).
2. Run B: the authored loop. Give run A's merged findings to the proposer as
   human advice, using one of these two routes:
   - Declared advice: set `preparation_options.proposal_advice` in run B's
     `workflow.py` to the findings text. It is the proposal capability's advice
     (`human_advice` of `interpretation-to-proposal`) and is applied on every
     iteration. The field is `str | None` (`CandidatePreparationOptions`,
     `src/workflows/definition/models.py`) with no declared length bound, so keep
     the text to the findings the user chose and do not paste raw run output.
   - Resume advice: at a pause, pass the text with `--advice-file`. It is 1 to
     4000 characters after trimming (`MAX_OPERATOR_ADVICE_CHARS`), is appended after
     the declared advice, and applies only to the resumed segment.

Do not set `expert_context` for this workaround. For
`native-interpretation-candidate/v1` it is framework-managed, and reusable
preparation sets it to `None` (`src/tools/candidate_prepare/reusable_interpretation.py`).

A combined profile is deferred to v1.2. Tell the user this limit when they ask for
both in one run.

## Captured native iterative chains

When the user selects the native Interpret → Propose → Implement → Validate →
Tune recipe, follow the [native capture guide](../../../src/tools/native_chain/README.md)
and [capture contract](../../../src/tools/native_chain/native-chain-contract.md).
Save the declaration and review request in the external project, preserve the
chosen scientific settings, and name the capture output and fresh absent native
workspace explicitly. From the selected checkout, run
`.venv/bin/python -m tools.native_chain review --request PATH`; its complete
printed command is the foreground launch route. Capture checks do not run an
iteration or produce a scientific semantic-review receipt. Launch remains a
separate authorized action.
Changing original bound inputs can refuse launch or a later iteration.

Professional CLI and Assistant routes share the Linux native writer owner.
Create the workspace parent before launch. To inspect a selected workspace, run
`.venv/bin/python -m core.native_writer inspect --workspace PATH`; this does not
authorize a new launch. Registered captured workspaces cannot be restarted through
the direct legacy CLI. Preserve `unresolved` or `invalid` ownership evidence and
use the [detached continuation admission](../../../src/tools/candidate_operations/candidate-operations-contract.md#captured-native-continuation)
only for supported absent-next-slot histories. It requires an exited outer operation,
confirmed cleanup, unchanged original capture/source and verified prefix; idle writer
state alone is insufficient. Existing failed/partial slots and explicit stop states
remain unsupported. Foreground-only/legacy runs lack this operation proof.
Never delete coordination files, reclaim by missing PID, or describe a fresh
destination as resume. See the [ownership contract](../../../src/core/native_writer/native-writer-contract.md).

For detached execution, follow the [operation steps](../../../src/tools/candidate_operations/README.md#run-a-captured-native-chain)
and [construction recipe](../../../src/tools/candidate_operations/candidate-operations-contract.md#construct-a-native-chain-operation).
Before capture review, create a dedicated empty envelope and declare its exact
absent `workspace` child as the native workspace; do not retarget a capture. Save
`chain-operation.json` outside that envelope, using the existing typed
`NativeChainOperation` owner; review it through `review_native_chain_operation`
or CLI `review`, then explicitly call `submit_operation` or CLI `submit`.
Retain the saved submission and UUID. Recover a lost response by reading that
UUID or resubmitting the identical saved payload; never rebuild it with a new ID.

For GUI use, prepare the same native capture and operation request externally,
then configure `native_chain_choices` using the [console contract](../../../src/tools/candidate_console/console-contract.md#configured-native-chains).
Follow [Review native capture → Launch native chain → Monitor](../../../src/tools/candidate_console/README.md#run-a-configured-native-chain).
The console uses the same operation owner independently of the editor. Preserve
the displayed operation UUID; navigation, reconnect and monitoring never launch.
Retry only the retained pending launch. Each new destination needs its own fresh
envelope and reviewed capture; the console does not edit native-chain captures or
stop/resume them. An [authored research loop](#authored-research-loops) is a
different route and can be stopped, paused and resumed.

Give the user the saved declaration, request, capture, submission/configuration
and workspace paths relevant to their route. Inspect shell outcome, cleanup and
native checkpoint evidence separately; completion does not establish scientific
success. Preserve `no_records`, unavailable or invalid evidence explicitly.
