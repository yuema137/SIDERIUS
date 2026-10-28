# Native candidate execution contract

`CandidateRunRequest` and `launch_candidate(request, *, invocation_id=None)`
are the common JSON/Python boundary.
The CLI decodes the same request and calls that function. The parent imports
inert declaration/preview/routing schemas and public pure evidence projections;
it never composes tasks, executes task/generated plugins or constructs agents/providers. `child` verifies captured inputs, binds generated
library discovery to its workspace, and only then imports `native` and task
consumers. Each launch gets a fresh interpreter through the existing sandbox.

Python callers may supply a strict UUID `invocation_id`, validated before any
filesystem effects. The native launch uses its hex form as the existing `run_id`
for artifacts and accounting. Omission preserves native `uuid4().hex` generation.
Request/receipt schemas, CLI behavior and exclusive claim ownership are unchanged;
only the claim winner can publish records with that invocation identity.

## Selected inputs and task authority

The parent revalidates the selected supported execution profile, canonical selected
paths, bytes/size hashes, declaration digest and constructor routes against the
request. Canvas positions do not enter declaration identity. It exclusively
creates `candidate_run/` in an absent/empty workspace; losers cannot publish
snapshots or receipts. After claiming, the parent rechecks that no other
workspace contents appeared. Source/data/workspace separation uses preview's existing
checks. A failed launch never removes its claim or partial output.

`candidate_run/request.json`, `launch.json` and `input_NNN.snapshot` are durable,
write-once control artifacts. Snapshot ordering and original source paths are
recorded in `request.files`. The child rechecks snapshots and selected files
before composition. The manifest is composed at its original canonical path,
so manifest-relative dependencies keep their native semantics. Read-only mounts
must expose the selected data, manifest, external inputs and task dependencies;
framework source and the active Python environment use existing sandbox mounts.

These checks bind selected inputs, not the complete dependency closure. Native
composition, local-code capture, plugin/profile resolution and task reference
owners establish their own semantic identities. The complete native
`ProposalInput.task_composition_ref`, task description, forward contract and
proposal blocks must match the composed values, including explicit `None`.
`data_dir` must identify the selected physical root. A changed task requires
an explicitly prepared new seed. Prepared interpretation, literature and data
analysis evidence is preserved as native typed input; this worker does not
independently verify its historical origin or regenerate it.

`managed_fresh` is mandatory. A missing seed storage key authorizes insertion of
managed proposal storage; an explicit storage must match canonical workspace,
local backend and run name. Both protocol storage arguments must match managed
implementation storage. Debug output must be inside `candidate_run/debug/`, separated from captured
inputs, control receipts and native output records. Only the
catalogued native optional context/task-ref/provider/model schemas are decoded;
protocol arguments must agree with native seed/task/constructor authorities.
Unused externals and result injection are unsupported.

For the three-stage mode, constraint disclosure may be incomplete. Claimed task rules/objective must agree
with composition, workflow rules with the seed, and duplicated time/VRAM facts
with seed declarations. Known execution sections compare duplicated budgets including explicit nulls.
Populated overrides, timing and execution controls without a worker authority
are refused before provider calls. Unknown sections remain unknown. Hardware/VRAM inputs
are declarations, not measurements certified by this worker. Future training
budgets are not training admission. Scope, sampling, allowed outputs, parameter
locks, reasoning stages and proposal advice remain native input values.

## Credential admission

Before a new workspace claim, `preflight.fresh_preview` reobserves the selected
files, declaration digest and constructor routes through the preview owner.
Native launch consumes that observation and retains its input-byte capture/recheck.
`preflight.credential_requirements` projects registry-backed required names using
`setup_review.environment.credential_name_checks`; disabled and pseudo routes
are excluded, repeated proposer stages share one required name, and unknown live
transports remain unresolved.

New launches refuse unresolved routes, required names omitted from
`environment_names`, or any declared name absent/empty in the actual process
environment. Extra declared runtime names are required too. Errors and the typed
policy contain names only. This checks local binding presence; it does not prove
provider authentication, network access or quota. The sandbox remains the owner
of environment forwarding. No request validator, historical reader, offline
preparation, dotenv behavior or general `LLMBridge` constructor policy changes.

## Fixed-candidate sequence and persistence

For the fixed candidate profile, one immutable run ID, run name and logical
iteration 1 reach the proposer
(including its eager/lazy stage bridges), implementor and validator through the
existing accounting helper. `WorkflowLLMConfig.get` owns constructor routing.
Native retries remain native; the worker has no retry or replay loop.

The sequence immediately consumes the three typed native calls in `phases.py`.
Each call receives an immutable `FixedInvocationContext` constructed from
`candidate_nodes`' declared node IDs, the launch receipt and already materialized
native storage. It compares the expected phase/node, launch run/workspace and
storage binding before agent construction, then uses that context to bind native
accounting. Iteration and attempt remain fixed at 1. Implementation and validation
share the existing `impl_001` storage slot and keep their separate record names.
Node IDs remain internal invocation identities: they do not enter prompts,
scientific candidate/model IDs or native filenames. Input reconciliation stays
with `materialize`; artifact and record verification stay with their existing
owners. The sequence owns receipt status, output ordering and optional tuning.

These calls are internal fixed-candidate boundaries, not a scheduler or a new
storage namespace. The supported topology remains exactly one proposer,
implementor and validator, with optional tuning; repeated capabilities still
refuse admission. Professional and Assistant use the same native execution
boundary, and this extraction adds no executable authored-graph topology or
new setup behavior.

The proposer returns its own candidate ID. The worker checks implementation-bound
schema eligibility, output types, generated name and unsupported historical
experiment-source inheritance before implementation. The existing isolation
policy applies when the native seed requests it. `local_full_spec` constructs
implementation input; managed model/test/loss directories and task/advice/hardware
context are added through existing helpers. `local_all_fields` constructs the
validator input, using the same native routing authority and immediate upstream
objects. Downstream nodes do not read other nodes' storage records.

The fixed storage slot is:

```
<workspace>/<run_name>/iteration_001/attempt_001/
  proposal_<run_name>.json
  impl_001/
    implementor_<run_name>.json
    validation_<run_name>.json
    models/ tests/ losses/
```

`impl_attempt_storage` owns implementation layout. The worker does not rename
the proposal directory after the model name arrives. Native record schemas and
basenames remain unchanged. When a native node has written its record, the
worker verifies schema equality with the returned object and preserves bytes.
When a native branch returns without persistence, the worker captures that
native object with the durable publisher. Mismatch fails instead of overwriting.

Generated artifacts must belong to the managed roots. A returned read-only reuse
artifact must match native declared-package model identity/source, and the
native sibling description path must remain inside declared read-only roots.
The empty test-path sentinel is preserved; missing description remains a native
validator rejection. Reused loss source/contract must match the task-owned loss
projection and native digest check. Nothing fabricates descriptions or tests.

These returned-object checks do not broaden native reuse eligibility. A task
model declaration alone is not a validated capability-index offer. A fresh
workspace has no historical generated-library offers, and therefore normally
uses native generation rather than Branch B reuse. Component tests that seed a
capability-index fixture only verify handling of a returned native reuse branch;
they do not qualify fresh end-to-end reuse. There is no library promotion.

## Terminal meaning and isolation limits

The child writes `child.json` only after native validation completes. The parent
reconciles the sandbox return code/status, immutable launch identity, validation
status and managed native record paths before writing `receipt.json`. Timeout,
process failure, interruption and absent/malformed/inconsistent child results
cannot become validation success. Partial records remain inspectable.

The receipt is an execution index with task fingerprint, candidate/node IDs,
storage/output paths, selected constructor routes, log and usage-ledger paths.
The native records remain data authorities. `worker.log` captures child stdout
and stderr. Usage remains owned by native bridges; missing usage is unknown,
not zero. Constructor route observations do not certify provider availability,
SDK-selected endpoints or exactly-once provider work.

The existing bubblewrap runner owns process-group and namespace cleanup and the
wall-time deadline. Network, environment names and character devices are
explicit. There is no unsandboxed fallback, memory/VRAM ceiling, or hostile-task
security claim. Generated code and CPU/GPU probes are code execution even though
this tool performs no training. No GPU is automatically mounted. Abrupt parent
death can leave only a launch receipt: incomplete/unknown, never resumable.

The pure `layout.candidate_proposal_dir(workspace, run_name)` owns the fixed first
proposal slot used by materialization and parent receipt reconciliation. It does
not create directories. Implementation storage continues to use
`workflows.attempt_storage.impl_attempt_storage` and the existing attempt owner.

## Reported-token read projection

`read_candidate_tokens(CandidateTokenReadRequest) -> CandidateTokenSnapshot` is
an inert Python API, also for direct native CLI/Python runs without an operation
store. The strict frozen request declares canonical absolute
`allowed_workspace_root`, `workspace` (strict descendant) and `expected_run_id`.
The API revalidates the request and refuses symlink components/nonregular files.
It reads only fixed request/launch, optional final receipt and usage-ledger files;
no preview, composition, providers, native nodes or generated code are loaded.
`records.verify_candidate_records` shares identity comparisons with the operation
reader; launch reconciliation and acceptance remain execution-owned.

Missing request/launch is `native_evidence_unavailable`; a missing ledger is
`usage_unavailable`, including terminal runs. Malformed/foreign control records
refuse. A final receipt is optional while running, but if present must verify.
Snapshots have no competing lifecycle status. Native receipt / operation status
remain their respective owners.

Groups preserve `(provider, requested_model, served_model)` exactly, including
empty strings and absent served identity. Nonmarker responses require non-null
provider and requested model. Marker shapes have all three identities and all
counts null, independent of label. Each token field sums only its own reported
values, returns null if none were reported, and counts missing fields separately.
Known zero stays zero. Equal retry rows remain separate observations. Totals are
never derived from input/output. No raw rows, extras, components or paths are
returned. Empty/marker-only evidence means “No reported responses observed,” not
zero billing. Every snapshot carries “Observed provider reports; missing or
unrecorded usage may exist.”

The reader opens one ledger descriptor, captures size and reads at most that
prefix: 4 MiB, 10,000 complete lines, 64 KiB per line, 256 model groups and
256 UTF-8 bytes per identity string. Oversize rows/identities or excess groups
are excluded and flagged. Byte/row limits disclose truncation; partial trailing
lines are ignored; short reads/observed shrink are partial. Invalid, negative or
foreign-run complete rows are excluded, with trustworthy sums retained and
labeled partial. Invalid/naive timestamps mark partial without discarding count
arithmetic; `last_valid_usage_at` is the latest accepted response timestamp
converted to UTC. Append after capture belongs to the next read. No atomic
whole-run completeness, same-size replacement detection, deduplication, cache,
quota, dollar cost or exactly-once/provider billing claim is made.

## Optional source capture

`CandidateRunRequest.workflow_source` optionally carries exact UTF-8 declaration
text, SHA-256, diagnostic absolute origin path and inert reviewed-context
provenance. Request validation binds source hash and the complete parsed
`WorkflowDocument`, including layout. The origin path is never read for execution.
After exclusive claim, launch publishes `candidate_run/workflow.py.snapshot`
before sandbox dispatch. The child verifies that fixed file against request text
before binding/importing native execution. Missing, changed, nonregular or alias
snapshots refuse execution. Captures do not freeze trusted task/plugin deployment.
Absent capture preserves ordinary native caller behavior and legacy operation
digests; only the absent `workflow_source` key is omitted by the operation digest
owner.
Newly serialized requests include `workflow_source: null` when no source is
provided. This is an additive request metadata format change, not byte parity
with older newly written requests. Existing persisted bytes that omit the field
remain readable and retain their old operation identity; prepared artifact hashes
continue to describe the actual stored bytes.

## Fresh native training (schema version 1)

The executable fourth node is `tuning`, using `validated-candidate-to-tuning`.
Its `proposal` and `validation` result arguments must reference this graph's
proposal and validator; `settings` must reference an external
`native-training.settings` file. `prepare_tuning_request` exposes these three
values and the internal admitted context/storage, then delegates to
`workflows.tuner_preparation.prepare_native_tuner_input`. There is no reflective
protocol executor. Version-2 reusable preparation resolves source-owned training
settings and the matching seed into this same v1 worker path. The console uses
that preparation owner; it does not define another tuning lifecycle.

`CandidateTrainingSettings` wraps `WorkflowLaunchConfig` with the seven native
startup controls. `SUPPORTED_LAUNCH_FIELDS`, `INACTIVE_LAUNCH_FIELDS` and
`MANAGED_LAUNCH_FIELDS` are the closed ownership census. Defaults come from the
direct workflow, not automatic CLI host-profile resolution. Inactive history,
outer iteration/retry, omitted-stage/advice, raw `plan_overrides`, cooperative
allocation, and chain-incumbent controls must equal their native defaults.
Those defaults do not activate omitted phases or outer retries. Tuning advice,
ordinary budgets, epoch limits, typed frozen portions, retention, parameter
rules and runtime controls use the native owners. `data_dir` must match the
selected root; `require_probe_runner` resolves to true and explicit false is
refused. Trial/formal time budgets are finite positive minutes or null. Zero
is refused at this ingress because the historical forecast/measured paths do
not share zero semantics; their existing behavior is unchanged.

Known native scalar, schedule, formal-policy, scope, order and deadline checks
run before proposer construction. Runtime-verifier identity, measurement
capability, hardware and root invariants use their established owners.
Candidate/model-dependent checks still run at native tuner admission. The
standard workflow shares only scope/Health preparation and lock projection;
its seed validation and launch self-test still precede lock publication.

An explicit `health_checks_config` is project-relative (or absolute), observed
as `training.health_checks_config`, snapshotted and rechecked in the child.
The canonical original path reaches the tuner, not the snapshot or effective
Health output. Dataset contents and arbitrary plugin assets are not recursively
snapshotted. Read-only task/dependency admission remains required.

The worker reconciles the captured `ProposalInput` against admitted controls.
Omitted fields can be filled; explicit values, including null time budgets,
must agree. Hardware null means unresolved and is populated from the live
hardware owner; a supplied hardware object must agree. Known conflicting
constraint sections refuse; incomplete context is completed from
`workflow_constraint_context`. Implementation and validation external context
bindings are checked against that same result. The admitted proposal is saved
before its first call; resolved settings are saved to
`candidate_run/training_settings.json`.

Passed validation returns typed in-memory outputs to training. Missing model
or loss sources refuse before construction/staging. The shared construction
owner admits the model; `stage_native_plugins` stages only the native tuner
destination. No global capability publication or model/loss promotion occurs.
The public tuner owns its entire training/scoring/Health lifecycle.

The first three `native_output_paths` retain their legacy ordering. The fourth
is `<workspace>/<run_name>/iteration_001/<model_name>/run_output_<run_name>.json`.
That native model directory also owns run configuration, records and retained
outputs under existing native naming/inventory rules. The receipt is an index,
not a second recursive artifact inventory; retention follows the native flags.
`completed` means the tuner returned, not scientific validity or scoreability.
An infrastructure abort returns `failed` while retaining its native output.
Rejected validation still returns three records and `rejected`. Parent timeout,
interruption or process failure overrides a child's reported completion.

The optional `training_output` receipt field contains the model name and native
output SHA-256. It is omitted entirely for legacy receipts. Reconcile and later
`candidate_operations` reads reach the same inert fixed-path/identity/digest
verifier. An operation completion marker pins the whole receipt digest, so
editing both output and receipt is also refused after completion. Without a
trusted completion marker these files provide internal consistency, not an
external tamper-proof signature. Missing or replaced output causes an integrity
refusal. Status readers import no task/plugin runtime to perform this check.

`examples/workflow_declarations/native_training.py` writes a matched synthetic
seed/settings pair and both Python-model-derived workflow and serialized
request. It performs no launch. Offline tests qualify propagation/admission and
artifact reading, not real LLM behavior, scientific training, GUI readiness,
resume, historical-profile parity or paper reproduction.

### Explicit fixed input bindings

`inputs.materialize` retains fixed `candidate_nodes` admission and selects nodes by
those declared IDs. It passes captured proposal bytes, managed proposal storage,
composed task, physical data root and control directory to `materialize_proposal`;
`reconcile_protocol_inputs` receives the selected protocol requests and managed
implementation attempt, returning the external IDs it consumed. The caller still
refuses unused externals. Training reconciliation and native defaults are unchanged.

`fixed_invocations` snapshots selected node/storage through `invocation_from_storage`.
Each phase still calls `require_binding`, which selects the fixed declaration
binding before `require_resolved_binding` checks node, phase, run and native storage.
These internal helpers do not admit a new topology or bypass task/artifact owners.
The default path retains exactly one proposal/implementation/validation and its
existing optional tuning path. The opt-in profile below consumes these same helpers.

Internal phase callers can select a positive integer `iteration` through
`invocation_from_storage`; `FixedInvocationContext` remains the identity owner.
The default is one, and attempt remains one. Fixed and graph phase binding checks
derive the expected native iteration slot before node construction or input writes;
agreement between an input and context alone does not admit a different slot.
The same iteration reaches eager proposal accounting and lazy literature bridges.

Native storage retains `iteration_NNN/attempt_001` under its fixed or graph-instance
owner. Iteration-one diagnostics keep their existing paths exactly. Later phase
diagnostics live under `candidate_run/iteration_NNN/` with the same per-profile
proposal/literature names; literature cache remains under its native iteration slot.
The pure layout helpers accept a keyword iteration from the validated identity.
Callers must supply independently prepared typed inputs with matching storage and
debug roots; these helpers never retarget captured requests.

Internal `execute_fanout`, `materialize_fanout` and graph evidence functions accept
a keyword-only iteration, default one. `candidate_control_dir` names the snapshot
set for that body: `candidate_run/input_NNN.snapshot` for one and
`candidate_run/iteration_NNN/input_NNN.snapshot` thereafter. The caller supplies
independently captured inputs and corresponding request observations before body
execution; materialization still checks explicit native storage and debug roots,
task facts and routes. Nothing silently retargets the previous capture.

The expected iteration must also reach `admit_graph_control` and
`verify_graph_trace` from the caller, independently of the child trace. The parent
derives expected native slots and reconstructs the literature edge from that
iteration's captured inputs and diagnostics. Existing record checks and typed
protocols remain their authorities; trace serialization is unchanged.

Run request/HTTP admission and public preparation still select iteration one and
require a fresh workspace. These internal body functions supply no append
admission, feedback/history policy, scheduler, retries or resume. Multiple body
calls alone are not an admitted multi-iteration authored workflow or historical
qualification. Fixed candidate/training execution also remains default-one.

### Opt-in proposal fanout

Set `WorkflowPreviewRequest.execution_profile="native-proposal-fanout/v1"` for a
fresh version-1 document containing one external proposal and complete
implementation/validation pairs. Omit it for the existing fixed three/four-stage
path. This field and terminal `graph_trace` are absent from default serialization.
No branch-count limit is imposed; the control-record byte envelope admits size.

Every implementation uses `proposal-to-implementation` with `output` referencing
the same proposal. Every validator uses `proposed-implementation-to-validation`
with two required result arguments, `proposal` and `implementation`, referencing
that proposal and its own implementation. It also takes required external
`storage`; optional `llm_provider`, `llm_model_id`, and `constraint_context` retain
the existing native defaults/reconciliation. There is exactly one validator per
implementation. This is a proposal/implementation AND boundary, not a merge of
independent branch results. The protocol composes the existing implementation
mapping and lineage enrichment, preserving immediate model-I/O/segmentation echoes.

For implementation ID `build_a`, its storage external must name
`<workspace>/<run_name>/graph_instances/build_a/iteration_001/attempt_001/impl_001`.
Its validator shares that attempt's native storage. The proposal has its own
`graph_instances/<proposal-id>/iteration_001/attempt_001` slot. IDs select invocation
slots, not scientific model names: separate branches may generate different source
bytes under the same proposal model name. Existing artifact ownership is checked
again before validation; equal scientific IDs do not authorize sibling artifacts.
The proposal seed is still published once under `candidate_run/proposal_input.json`.

The existing child dispatches ready nodes serially in declaration order. All
required predecessor results must have succeeded before constructing the consumer.
Values move through typed results held by the dispatching worker, never
peer-file communication; each dispatched node runs as one unit process (below).
Validation rejection is retained and independent siblings can continue. A native
exception aborts further effects; remaining instances become blocked. Training,
routing, loops, human pauses, buffers, cross-branch aggregation and graph resume
are not supported by this profile.

#### Per-unit processes (B3-3)

Every graph profile (`execution_profile` set, including loop bodies) runs each
dispatched node, except adaptors (`adaptor_phase.execute_adaptor` runs those in the worker), in its
own child process, still one at a time. Readiness,
input materialization, predecessor-result selection, terminal classification
and the trace stay in the worker (`graph.execute_fanout`). The fixed
three/four-stage path is unchanged and runs in the worker.

- `unit_dispatch.node_invocation` builds a frozen `unit_models.NodeInvocation`:
  the `execute_fanout` arguments (`request`, `initial`, `config`), the bound
  composition's `manifest_path`, `composition_fingerprint` and
  `physical_data_root`, `node_id`, `iteration`, the selected native `storage`,
  and a phase payload discriminated by `phase` (`ProposalUnit`,
  `ImplementationUnit`, `ValidationUnit`, `LiteratureUnit`,
  `InterpretationUnit`, `TuningUnit`). A proposal after a literature review
  carries the review evidence already applied. `TuningUnit` carries the
  predecessor outputs of the branch `adaptor_phase.tuning_branch` selected in
  the worker (the selection adaptor's contribution, else the only branch), `chain_formal_incumbent_reference` and
  `AdmittedTraining`: the `TrainingAdmission` without its task composition and
  LLM config, which `admission_from` refuses to build if restoring it would not
  equal the admitted value.
- `unit_runner.run_unit` publishes the invocation write-once at
  `candidate_control_dir(workspace, iteration)/units/<node_id>/invocation.json`
  (the directory must not exist), runs
  `python -m tools.candidate_worker.unit_child <invocation>` through
  `core.runtime_control.observed_subprocess.supervise_subprocess` with
  `core.subprocess_env.subprocess_env()` (no device selector, so the worker's
  GPUs) and reads the write-once `result.json` beside it. Both files are
  bounded by the 4 MiB control envelope (`core.control_json.JSON_LIMIT`) on
  write and read through `graph_evidence.read_graph_control`; an oversized
  invocation fails its node before the child starts. A result over the bound
  (in practice only a tuning output; the largest real `run_output` today is
  about 1.1 MB) becomes `failed`/`native_failure` after training has run
  (sizing this bound from the tuner's limits is tracked in #1015).
- The unit runs with `PYTHONSAFEPATH=1` (added only when the worker lacks it,
  flagged by `SIDERIUS_UNIT_SAFE_PATH_ADDED`), because `-m` would otherwise put
  its cwd, the writable workspace where earlier generated code can write,
  first on `sys.path`. The child removes both variables at entry, so its own
  subprocesses see the worker's environment.
- Transport (`unit_transport.encode_transport`/`decode_transport`) writes two
  JSON lines: the `model_fields_set` tree of every nested model, then the
  value's complete JSON with inf/NaN kept as JSON constants (`-inf` scoring
  sentinels and launch knobs are valid values). Decoding validates the JSON and restores each model's
  set fields, because LLM-config defaults, protocol mappings and
  reconciliation read `model_fields_set` (an `exclude_unset` dump cannot carry
  validator-filled fields such as a tuning output's metric contract). Encoding
  refuses a value whose decoded `model_dump(mode="python")` differs from the
  original's under NaN-aware structural equality (NaN equals NaN, +/-inf
  compare exactly, so a stable lossy encoding such as -inf -> null is
  refused), that is not a byte fixpoint of decode and re-encode (covers set
  fields), or that decodes with a different set-field shape; a refused
  invocation fails its node (`failed`/`native_failure`) before any child
  starts. The child's `NodeUnitResult` and phase output cross back under the
  same rule.
- `unit_child` requires the generated-library binding the worker placed in its
  environment, recomposes the task from `manifest_path`, refuses a different
  `semantic_fingerprint`, binds the composition with the transported data root
  and calls the same native phase function the worker called before B3-3
  (`phases.run_*`, `run_literature`, `run_interpretation`, `run_training`).
  Its stderr joins the inherited stdout, so `worker.log` still holds the unit's
  output and tracebacks in order.

`NodeUnitResult.outcome` keeps the in-process failure semantics: `returned`
yields the output and record path; `raised` (native exception, traceback
logged by the child) becomes `failed`/`native_failure` with remaining nodes
blocked; `exited` re-raises `SystemExit(exit_code)` and `interrupted`
re-raises `KeyboardInterrupt` in the worker, as the in-process call propagated
them. A unit process that exits nonzero without a result (crash, kill) is also
`failed`/`native_failure` after the worker logs the supervision error; an
in-process crash instead ended the whole worker without a trace. The unit
shares the worker's session and process group (a plain supervised call), so
the sandbox wall-time deadline and terminal signals reach it as before.
Subprocess lifecycles the unit observed (for example tuner children) are
returned in `NodeUnitResult.lifecycles` and replayed in order through
`replay_process_lifecycle` to the worker's observer, so a loop body's
`iteration_owner` lease still sees uncertain cleanup. Replay happens before
the result's identity check, so a refused result cannot hide that evidence.
Grandchildren left by a killed unit that stay in the worker's process group
are reaped by the sandbox's group cleanup when the worker exits; supervised
grandchildren that created their own session (owned-group supervision) are
reaped only when the bubblewrap PID namespace is torn down.

Each unit pays its own interpreter start, native imports and task
recomposition, measured in review at about 2.5–2.8 s and 680 MB peak RSS per
unit on CPU. That time is charged against the run's `timeout_seconds`; the
memory is released before the next unit starts.

Parity limits, all outside recorded scientific outputs:

- The torch default RNG is process-global. Before B3-3 the implementor
  self-check and validator probes of one body drew unseeded inputs and probe
  weights from one shared stream; each unit now starts its own fresh,
  nondeterministic stream. Neither was reproducible. Probes stay unseeded;
  seeding them is a separate behaviour decision.
- `subprocess_env` sets `PYTHONHASHSEED=0` unless the operator set it, so unit
  string hashing is fixed where the worker's was per-process random.
- Each unit imports native modules and process registries afresh; registry
  writes (only tuning writes them) no longer outlive their unit.
- `units/<node_id>/` adds two control files per dispatched node; the trace,
  records and receipt bytes are unchanged
  (`test_unrouted_graph_trace_bytes_are_unchanged`).
- `core/runtime_control/observed_subprocess.py` gained
  `replay_process_lifecycle`, so `gpu_protection.protection_mechanism_digest()`
  (recorded on protection receipts) moves from `d3f8cf19…` to `b79dbdde…`. The
  rendering, verifier and estimation assembly digests are unchanged.

Tests run units through an in-process seam (`native_runner` replaces
`unit_runner.spawn_unit` with `unit_child.run_invocation_file`), which keeps the
file transport, recomposition and result mapping. `test_unit_process.py` runs
real unit processes with a generated provider harness: it requires the pinned
accepted and failed trace digests, prompts and normalized records equal to the
in-process run, a distinct process per unit importing this checkout, no
registry write visible to a later unit or the worker, a crashed unit treated as
a native failure, an adaptor-selected branch (reversed bindings) reaching a
real tuning unit with the verifier's verdict and staged-bytes checks passing,
replay of a unit's subprocess lifecycle, -inf values and a
validator-filled nested field crossing the transport, and no import of
`tools`/`json` shadows planted in the workspace.

`tools.candidate_worker.readiness.next_dispatch` is the single readiness
authority. It is pure: `ReadinessInput` carries every declared node in
declaration order as `NodeReadiness(node_id, predecessors, state, reason,
routing)` (`pending` for undecided nodes), `aborted`, and `decisions` (the
recorded `RouteEvaluationOutput` values, at most one per branch; empty for
every profile except `native-routed-candidate/v1`). It refuses duplicate ids, undeclared
predecessors or merge candidates, two decisions for one branch, a `skipped`
node without a reason in `SKIP_REASONS` (B1: `route_not_selected`; B6-4:
`insufficient_items`, set through `skipped_input`, see "Literature adaptor
profiles"), and a node
whose merge candidate is also one of its `predecessors`, or whose
`NodeRouting.control` is set without `route` or is not one of its `predecessors`.
`predecessors` are the
required sources (including a route's control edge), excluding merge
candidates: declared dependency facts list every candidate as a consumer
dependency, so `readiness_input` removes a node's merge candidates from its slot
predecessors (safe because declaration validation refuses a plain dependence on
a merged arm). It
inspects the first `pending` node whose sources (predecessors plus every merge
candidate) are all terminal (neither `pending` nor `running`) and returns one
action as `ReadinessOutput`: `next=<node_id>` to dispatch it, or
`terminal=((node_id, state, reason),)` to close it without dispatch;
`next=None, terminal=()` means no node can act. An adaptor slot
(`kind="adaptor"`) follows its own rule (see "Opt-in first-passing selection").
For a capability node, the per-node rule `_close_reason`, in precedence order:

1. `aborted` (an earlier native failure) → `blocked/dependency_not_successful`.
2. Any required source `failed`, `rejected` or `blocked` →
   `blocked/dependency_not_successful`. Blocked beats skipped. Exception
   (B1-PR5, B1-Q1 fallback): `NodeRouting.control` names the branch source when
   the target binds no data from it (a control-only edge). That source blocks only
   when `failed` or `blocked`; a `rejected` source still produced the record its
   decision read, so rule 4 decides. A target that also reads the source's data
   keeps rule 2 (pinned: `test_readiness.py` route rows).
3. Any required source `skipped` → `skipped` with that source's reason (first
   skipped source in predecessor order). This generic propagation applies to any
   skip reason, so later reasons (B6 `insufficient_items`) need no second rule;
   skipped never satisfies a required input.
4. `NodeRouting.route` (the node is an entry target of that branch): dispatched
   when the branch decision lists it in `selected_targets`, closed
   `skipped/route_not_selected` when it lists it in `skipped_targets`. A missing
   decision, or one naming neither, raises `ValueError` (never treated as
   selected). Arm interiors are skipped by rule 3, not by a separate arm list.

A merge (`NodeRouting.merges`, one `MergeReadiness(branch, candidates)` per
`SelectedSource` argument; each `MergeCandidate(node, entry)` names the entry
targets of the arm it lies in) consumes only the candidate whose `entry` equals
the decision's `selected_targets` as a set (declared order carries no meaning); non-selected candidates (skipped or blocked)
are ignored. No unique match raises `ValueError`. Without a decision (the branch
source never succeeded) the consumer is blocked if any candidate is
failed/rejected/blocked, inherits the skip if all are skipped, and otherwise
raises. `body_status(states, tuning=...)` is the one body aggregate: `failed` if
any node failed, else `rejected` if any node was rejected, else
`completed`/`accepted`; `skipped` and `blocked` are neutral (blocked only follows
a failure or rejection). `validation_passed` is unchanged: with tuning it
requires every validation node `succeeded`. That rule is not reached by a routed
run: the routed profile is the selection profile, whose `validation_passed` is
the selection adaptor's outcome. `readiness.may_run(node_id, value)` applies the
same per-node rule (without abort) to a fully recorded trace; the verifier uses
it as its per-entry dependency check, so a merge consumer is checked against the
selected candidate only and a control-only source may be `rejected`.

`execute_fanout` dispatches from this decision, and `verify_graph_trace` replays
the recorded terminal states through `graph_evidence.replay_readiness(nodes, *,
decisions=(), routing=None)`, which refuses a node readiness would dispatch but
the trace closed, and a node readiness would close whose recorded `(state,
reason)` differs (for example dispatched inside a non-selected arm, or `blocked`
where readiness derives `skipped`). The verifier also accepts `skipped` without a
record path/digest only with a `SKIP_REASONS` reason. Both call sites pass the
recorded decisions and `route_phase.node_routing(definition)` (empty for an
unrouted declaration), so a `skipped` state in an unrouted trace is refused by
replay. Adding the `skipped` state and `route_not_selected` reason does
not change existing trace bytes (pinned by
`test_unrouted_graph_trace_bytes_are_unchanged`). If no node can act while some
remain undecided (unreachable for a validated acyclic declaration),
`execute_fanout` raises `RuntimeError("graph readiness found no dispatchable
node")` and `verify_graph_trace` raises `ValueError`.

The final optional `graph_trace` contains every declared node exactly once: its
capability, predecessor IDs, managed storage, terminal state, fixed reason code and
native record path/digest. Native records remain scientific authority. The existing
receipt verifier checks membership, paths, digests, dependency success and serial
failure-stop semantics; the operation reader and console HTTP status use that
verified projection. There is no active per-node trace file and no graph GUI.
Outer timeout/interruption still overrides child success and may leave no complete
trace; native files remain inspectable, never an automatic resume permit.

Graph requests, initial/child/final receipts use the existing 4 MiB encoded control
limit. Before claiming the workspace, admission encodes the complete request and
largest possible terminal index using actual node IDs and paths, full digest
placeholders and longest fixed state/reason representations. It refuses overflow
before native calls; it never truncates membership. Final encoding is checked again;
unexpected overflow publishes `failed` with `graph_control_overflow` and no partial
accepted trace. Existing fixed synchronous CLI/input-file behavior is unchanged.
For a bounded public JSON consumer, submit the existing `CandidateOperation` through
`python -m tools.candidate_operations submit`, then use its existing status/log
commands. The operation UUID identifies submission recovery; the native run ID
continues identifying accounting. Same-UUID lookup does not relaunch effects.

### Opt-in independent proposal families

`WorkflowPreviewRequest.execution_profile="native-proposal-families/v1"` admits
one or more independently declared external proposal instances, each with at least
one complete implementation/validation branch. Each implementation's `output`
selects its proposal result. Each validator's `proposal` must select that same
proposal, and its `implementation` must select its own implementation. Cross-family
joins, orphan proposals, duplicate validators and extra capabilities refuse.
Declaration order need not be topological; actual typed edges determine readiness.

Use the version-1 `WorkflowDocument` and complete native inputs described above,
then the existing `CandidateRunRequest`/candidate operation interface. For example,
`proposal_a -> build_a/check_a` and `proposal_b -> build_b/check_b` produce two
native candidate identities in one run. Each proposal seed must match the selected
run task composition and data root. Its optional explicit storage must match
`<workspace>/<run_name>/graph_instances/<proposal-id>/iteration_001/attempt_001`.
Implementation storage and validator sharing follow the fanout convention above.
Every captured seed retains its existing `input_<index>.snapshot`; the materialized
proposal diagnostic is `candidate_run/proposal_inputs/<proposal-id>.json`.
An optional absolute `debug_dump_proposing_prompt_path` must resolve below
`candidate_run/debug/<proposal-id>/`; a shared or sibling path refuses before any
native call. The existing native pipeline writes the debug dump when selected;
the legacy proposer mode does not write it. Default/G1 retain their previous
`proposal_input.json` and debug directory semantics.

The existing serial worker, native nodes/protocols, output formats, control byte
limits and independently verified operation/HTTP trace remain the execution path.
A validator rejection permits other ready families to continue. A native exception
aborts all remaining families because the run is uncertain; independent exception
recovery is not supported. Candidate IDs are native outputs, never dispatch keys.
The family profile generates N independent instances, not N outputs from one
proposer call; no scientific diversity, ranking, aggregation, parallel execution,
training, conditional routing, buffers, human gates or graph resume is implied.

Branch isolation within one body (audited for B3 parallel scheduling): no
family or branch reads a file or plugin registry an independent sibling wrote.
Family inputs are materialized from the captured snapshots before the first node
runs; the interpretation candidate re-materializes its proposal input after the
interpretation node, inside its single chain, which has no sibling. Each
implementation writes its plugin, `description.md`, tests and losses only below
its own `graph_instances/<implementation-id>/.../impl_001/`. The worker never
registers into the workspace `generated_library` (capability index, models,
losses) and never writes `<workspace>/plugins/`. These are the shared locations
that the proposer, implementor and model-description readers consult. The
validator loads a generated plugin with a plain `exec_module` that does not
enter `sys.modules`, and it does not populate the process model/loss registries.
Only a tuning node mutates those registries (`stage_native_plugins`). The only
profile admitting tuning (interpretation candidate) has one branch, so tuning is
the body's last node; the next loop body is sequential by design.

One process-global state is shared: the torch default RNG. The implementor
self-check and the validator probes draw unseeded probe inputs, and their probe
models draw initial weights from it. A family-1 node's probe tensors and weights
therefore depend on how many draws earlier nodes made. Recorded outputs are
unaffected (pass/fail, shapes, gradient checks and records compare equal across
declaration orders). The stream is not reproducible even serially: an unseeded
process starts from a nondeterministic torch default seed. Since B3-3 each unit
runs in its own process and draws from a fresh stream instead of a shared one
(see Per-unit processes). Seeding the probes is a behaviour change outside B3.

The shared `token_usage.jsonl` is append-only. By source reading (the witness
below replaces `LLMBridge`), the only in-run read is `LLMBridge`'s first-row
`run_id` identity check. Every aggregating reader (token read projection,
iteration rollup, campaign spend, baseline report) groups by run, iteration,
label or provider, never by row position. `validate_token_usage_jsonl` checks
order only against iteration-flush markers, and warns without failing on
non-monotonic timestamps. Rows carry no unit identity; optional unit attribution
is deferred to parallel dispatch, so serial ledgers are unchanged.

The B3-0 audit therefore found nothing to snapshot per body. Witness:
`tests/unit/tools/candidate_worker/test_branch_isolation.py` runs real native
node bodies with a scripted provider in three declaration orders. Its two
families propose distinct models. It requires the actual dispatch sequence to
equal the declaration order, and no node to leave a process-registry write
behind. It requires an empty workspace `generated_library` and no
`<workspace>/plugins/`. Finally it requires byte-identical family-1 proposal
input, prompts, debug dump and normalized proposal, implementation and
validation records. A future profile that promotes into the workspace library,
writes `<workspace>/plugins/`, or admits several tuning nodes in one body must
snapshot those reads per unit, or run each unit in its own process, before
independent units may run concurrently.

Reusable version-2 source and managed preparation also support this profile through
[the reusable family contract](../candidate_prepare/candidate-prepare-contract.md#reusable-independent-proposal-families).
Code callers may still supply version-1 native inputs directly. Both routes use
the same existing operation/HTTP observation without loading an editor.


### Opt-in first-passing selection (S1, B6-3)

`WorkflowPreviewRequest.execution_profile="native-proposal-fanout-selection/v1"`
(`workflows.definition.fanout.SELECTION_PROFILE`) admits B6 scenario S1: one
external proposal, its complete implementation/validation branches (the
proposal-fanout ownership rules above), exactly one declared adaptor and exactly
one tuning node. Admission (`fanout.selection_candidate`) requires:

- `adaptor_format="siderius.adaptors/v1"` and one `AdaptorInstance` with one
  `validation.output` input port, `combine=pass/v1`, `select=first-admissible/v1`,
  `distribute=single/v1` (no other strategy triple is admitted);
- the port binding lists every validator `ResultSource` exactly once, in any order;
  that declared binding order is the selection order;
- the tuner uses `validated-candidate-to-tuning` with `proposal` = the proposal
  result, `validation` = `AdaptorSource(adaptor=<id>)` and an external `settings`
  (`candidate.check_tuning_edge` accepts either a validator id or this adaptor
  source); no route and no loop.

`ProposalFamilies.selection = AdaptorSelection(adaptor, validators)` records the
admitted adaptor and its bound validators in declared order; `tuning` names the
tuner. Every other profile still refuses an adaptor document
(`ADAPTORS_NOT_ADMITTED`). The proposal seed path and branch storage slots are
those of `native-proposal-fanout/v1`; training admission and the native tuner path
are those of the interpretation profile's training ("Native training after
interpretation"), so the seed must leave training-owned fields unset or equal.

**Readiness.** `NodeReadiness.kind` is `"capability"` (default) or `"adaptor"`
(B6-D8). An adaptor is ready once every bound source is terminal; `_close_reason`
closes it `blocked/dependency_not_successful` only after an abort or when a source
is `failed` or `blocked`. A `rejected` or `skipped` source does not close it; the
strategy treats it as inadmissible. An adaptor never carries routing.
Its consumers keep the capability rule, so a `rejected` adaptor blocks the tuner.

**Execution** (`adaptor_phase.execute_adaptor`). Items are built by
`adaptor_items` in declared port order, then binding position, never completion
order. Every succeeded or rejected source's native record is read (digest checked
against the trace) and parsed with the contract's native model
(`workflows.custom_adaptors.contracts.native_type`). A rejected source must be
rejected by its record (a `VALIDITY_GATED_CONTRACTS` value with `passed=False`),
else `ValueError`; it becomes an item with state `rejected` and no value. A
route-skipped source becomes an item with state `skipped`, no value, and
`AdaptorInputRef.record_sha256` = its skip record digest from
`route_phase.skip_citations` (see "Routed execution"). A `skipped` source without
a citation raises `SkippedAdaptorInputError`, which `execute_adaptor` re-raises
instead of closing the slot; any other state raises `ValueError`. The pure
`run_deterministic_adaptor` decides with `metric=None` (no metric-ranking kind is
admitted), and `build_adaptor_record` builds the `AdaptorRecord`. Each emitted
output value is published write-once as canonical JSON at
`candidate_run[/iteration_NNN]/adaptors/<id>.out.result.json` (`<id>.out.result.<i>.json`
for indexed outputs), then the record at `.../adaptors/<id>.json`; the file digest of
an output equals its `OutputDigest.sha256`. The trace slot closes with the outcome
status and reason (`succeeded`; `rejected/no_admissible_input`;
`rejected|failed/insufficient_items`), the record path and its digest. The closure
is computed before anything is published. Any other exception
closes it `failed/native_failure` without a record and stops later effects, as for
a native node. The tuner trains the branch whose validator the adaptor emitted
(`adaptor_phase.tuning_branch`, read from the outcome's contribution); all
validators rejected gives `rejected/no_admissible_input` and a blocked tuner.

**Trace.** `GraphTrace.adaptors` holds one `GraphNodeEvidence` per declared
adaptor, in declaration order, with `capability="adaptor"`, predecessor ids,
`storage` = the adaptors control directory, state, reason, record path and digest.
It is omitted when empty, so unadapted traces keep their bytes (pinned:
`test_unrouted_graph_trace_bytes_are_unchanged`,
`test_unadapted_training_trace_bytes_are_unchanged`). `GraphTrace` refuses an
`"adaptor"` capability in `nodes` and any other capability in `adaptors`.
`GraphReason` gains `no_admissible_input`, `insufficient_items` and the reserved
`judge_failure` (B6-8). Adaptor records are not in `native_output_paths`.

**Body outcome** (`adaptor_phase.body_outcome`, shared by worker and verifier).
A `rejected` node bound to an adaptor that `succeeded` was an inadmissible input
the adaptor absorbed; it is neutral in `body_status`, like a skip. Adaptor states
themselves count. Under the selection profile the selected path decides the body:
selected input and tuner `succeeded` gives `completed`; an adaptor
`rejected/no_admissible_input` (or `insufficient_items`) gives `rejected` with a
blocked tuner. `validation_passed` is the selected candidate's validation, i.e.
`True` iff the selection adaptor `succeeded`. Every branch keeps its own node
state in the trace (a rejected sibling stays `rejected/validation_rejected`).
Profiles without adaptors keep the existing rules (pinned trace bytes above).

**Verification.** `verify_graph_trace` checks adaptor membership and bindings
against `expected_adaptors`, record path/digest of a decided adaptor, that its
sources were terminal and none failed or blocked, and replays readiness over nodes
then adaptors. `adaptor_phase.verify_adaptors` then recomputes each recorded
adaptor from the native records the trace names and requires the record bytes, each
emitted output's bytes and the trace `(state, reason)` to equal the recomputation;
an `<id>.out.*` file the recomputation does not emit is refused. Selection inputs
are trace states, so the native verifier loop also requires every `validation`
entry's state to be its record's verdict (`succeeded` iff `ValidatorOutput.passed`,
else `rejected`), read from the digest-checked record. `verify_graph_training`
reads the trained (implementation, validation) pair from the verified outcome
(`tuning_branch`), checks the validation record and the tuner identity as before,
and binds the tuner to that implementation from record facts only, mirroring
`artifacts.verify_artifacts`. A generated model (its `model_file_path` under the
attempt's `models` directory) is copied verbatim by `stage_native_plugins`, so the
staged `get_plugin_dir(<tuner storage>, run_name)/<model>.py` must equal its bytes;
this applies to every trained profile and changes no record. A reused task-declared
package model (`test_file_path == ""`, model outside the attempt) is trained from
its declared source and `stage_model_source` copies nothing, so no bytes are
compared; under the selection profile a staged copy then contradicts the record and
is refused. An unreadable staged or model file is a `ValueError` ("tuner staged
model ..."), never an incidental `OSError`.
Witness: `tests/unit/tools/candidate_worker/test_adaptor_selection.py` (second
branch trained when the first is rejected; all rejected; declared and reversed
binding order over execution order; tampered record/output/closure; extra output
file; relabelled validator verdict; staged model of a sibling; declared package
reuse; missing staged model; shape refusals).

Not admitted: v2 reusable source, managed preparation and console for this profile;
any other strategy triple, metric ranking, per-item/split distribution, routes,
loops, custom and LLM strategies (split distribution runs only under the literature
split profile, "Literature adaptor profiles" below). Routes run only under
`native-routed-candidate/v1` (next section).

### Routed execution profile (B1-PR5)

`WorkflowPreviewRequest.execution_profile="native-routed-candidate/v1"`
(`workflows.definition.fanout.ROUTED_PROFILE`) admits the S1 selection node set
(same admission, `fanout.selection_candidate`, via `fanout.routed_candidate`) plus
at least one declared route whose arms (targets and every node they dominate,
`routes.branch_arms`) contain only implementation/validation nodes: an arm holding
the selection adaptor or the tuner is refused ("the routed profile routes only
implementation/validation arms, never the adaptor or the tuner"), because gating
training on a predicate (B1-Q1(b), not chosen) would let a body complete untrained.
It is the only profile whose `refuse_declaration_only` call passes
`admits_routes=True`. Every other profile, the fixed candidate, v2 reusable
sources, managed preparation and the console profile lists still refuse a routed
document (`ROUTING_NOT_ADMITTED`). No loop is admitted (`admit_loop` admits only
the interpretation profile; B1-Q5 leaves no admissible route target in the
single-branch interpretation loop, so routed loops wait for a later design). First
consumer (B1-Q1(a)): a fallback branch, e.g. `Branch(source=check0,
cases=(RouteCase(when=BoolIs("validation.passed", False), targets=("build1",)),))`:
`build1`/`check1` run only when `check0` rejects, and the first-admissible adaptor
trains whichever validator passed (a passing fallback rescues the body; the
absorbed `check0` rejection is neutral).

**Run metric.** `route_phase.admit_route_metric(definition, composed)` derives the
run metric once, before any effect in `execute_fanout`: the composed task metric
(no loop, so no seed reconciliation). `route_eval.admit_route_metrics` refuses a
`metric_at_least` naming another metric there (`RouteConditionError`; the child
fails, no node is dispatched). The same object is passed to every
`RouteEvaluationInput`. In the selection node set only a tuning record carries a
metric observable and the tuner has no descendants, so a `metric_at_least` route
is not declarable today; the admission is generic.

**Decisions.** After each node closes, `route_phase.decide_routes` decides every
branch whose source it is, provided it closed `succeeded` or `rejected` with a
record: `project_observation` from the record path, a digest check against the
trace's `record_sha256`, then `evaluate_route`. A `failed` source decides nothing
and its targets are blocked. Any exception during projection or evaluation is a
`RouteConditionError` raised out of `execute_fanout` (outside the node's own
failure handling): the body fails as an uncertain child failure, never reading the
route as false. This is deliberately fail-closed for B1-PR5: the child exits
nonzero, the receipt is `failed` with no `graph_trace`, and native records already
written for nodes that ran in that body stay on disk unindexed by any receipt (they
are never read as evidence). A per-body failure that keeps its trace, as adaptor
exceptions do (`failed/native_failure`), is tracked in issue #1016. Each decision is recorded as
`GraphRouteEvidence(branch_id, source_node, source_record_sha256,
evaluator="siderius.route/v1", decision, decided_by="predicate")` and fed to
readiness. `GraphTrace.routes` lists them in branch declaration order and is
omitted when empty (unrouted bytes unchanged). `route_phase.node_routing` builds
each node's `NodeRouting` from the declaration through the public
`workflows.definition.routes` helpers `route_targets` (entry target → branch,
source, `control_only`) and `merge_arms` (merge candidate → its arm's entry
targets, via `branch_arms`).

**Skip records.** A route-skipped node's skip record is the `GraphRouteEvidence`
that skipped it: directly (it is a `skipped_targets` entry of its own branch) or by
propagation (the walk follows the first route-skipped predecessor to the deciding
branch). `route_phase.skip_citations` maps each such node to
`evidence_digest(evidence)` = SHA-256 of the evidence's canonical JSON; an
adaptor cites it as `AdaptorInputRef.record_sha256` of the skipped input. The
worker computes citations at adaptor dispatch, the verifier from the trace; both
feed `adaptor_phase.decide`, so the adaptor record is recomputed byte for byte.
The `routes.py` arm-label relaxation stands for this shape: the adaptor reads both
arms (one outside, one inside the fallback arm) and runs either way (B6-D8), so its
tuner consumer is not refused.

**Verification.** `verify_graph_trace` additionally runs
`route_phase.verify_routes`: for every node closed `succeeded`/`rejected` with a
record it re-projects and re-evaluates each branch it sources and requires the
recorded tuple to equal the re-derivation (a forged decision, source digest,
missing or extra decision is refused: "graph route evidence does not match its
re-derivation"). The verifier holds no composition, so it evaluates under the
source record's own stamped metric, which the worker already reconciled with the
run metric (a tuning record without a stamp would make a metric route
unverifiable; not declarable today). Readiness replay then uses the recorded
decisions, refusing a node dispatched in a non-selected arm and any terminal
`(state, reason)` readiness would not produce.
Witness: `tests/unit/tools/candidate_worker/test_routed_profile.py` (tuner- or adaptor-gating route refused; passing
`check0` skips the fallback and the adaptor cites the skip record; rejected
`check0` runs the fallback, trains `build1` and completes; both rejected; forged
decision, source digest and dropped decision refused; metric admission before any
dispatch; refusal by every other profile; unrouted selection trace bytes pinned on
base 405d7aaf; console projection of skipped nodes).

### Opt-in native literature candidate

Set `WorkflowPreviewRequest.execution_profile="native-literature-candidate/v1"`
on a version-1 document. Exactly four instances are supported:

| Instance capability | Request and required result sources |
| --- | --- |
| `literature` | External `literature.input`, the existing `LiteratureReviewInput` |
| `proposal` | `literature-to-proposal`: `output` selects that review result; `proposal_input` selects an external `proposal.input` seed |
| `implementation` | Existing `proposal-to-implementation`, selecting that proposal |
| `validation` | Existing `proposed-implementation-to-validation`, selecting that proposal and implementation |

The closed catalog points `literature-to-proposal` to the existing
`ml_literature_review_to_ml_model_propose.local_typed_evidence`. Its target-owned
bounded projection replaces `ProposalInput.literature_review_evidence`; it does not
merge multiple reviews, rank findings or alter native prompts. Declaration order
can differ from execution order. The existing serial readiness loop executes the
review, projects its typed in-memory output, then calls the same native candidate
phases. No interpreter is executed in this profile. Callers supply native typed
interpretation evidence and may construct review inputs with
`workflows.literature_input.build_literature_input`.

The external review must explicitly select the run name and local storage
`<workspace>/<run_name>/graph_instances/<review-id>/iteration_001/attempt_001`.
Its task description and constraint context must equal the checked proposal seed.
The seed retains task composition, data-root and native constraint reconciliation.
Main/search bridge settings, retries and sharing must match the captured
`WorkflowLLMConfig` routes; existing `lit_review` inheritance from `interpret`
remains the configuration owner. Missing main configuration refuses, with no new
provider fallback. Actual lazy bridges receive the existing run accounting context.

All selected input files require explicit read-only mount admission. This profile
refuses `PaperSource.source_type="local"`: the existing native resolver gives those
paths checkout-relative semantics, which this external graph does not reinterpret.
Use the existing literature workflow/CLI for local papers; their behavior is
unchanged. Remote roots or enabled dynamic search require explicit `network=true`;
network access is never guessed or enabled automatically. Provider calls also
remain subject to the selected sandbox network policy. Empty roots with search
disabled do not establish network retrieval support or zero provider usage.

Each review uses a fresh managed `cache/root_papers` below its instance directory;
existing input/cache/output slots refuse before native calls. The native output
filename remains `ml_literature_review_<run_name>.json`. `capture_record` preserves
and compares native-persisted bytes, or captures the returned typed output when
native persistence is absent, under the existing ownership rule. The review input
diagnostic is `candidate_run/literature_inputs/<review-id>.json`; the projected
proposal diagnostic is `candidate_run/proposal_inputs/<proposal-id>.json`. Optional
proposal prompt dumps stay under `candidate_run/debug/<proposal-id>/`.

The parent checks graph membership, dependencies, storage, record paths and hashes,
then independently compares the review diagnostic against captured external input,
checks task/run binding, and reconstructs the target projection for a successful
proposal. Native review bytes are read with no-follow stable file identity and
compared to the recorded digest; no new scientific-output size cap is imposed.
Inputs and control records retain their existing control-size boundary.

A valid empty native review remains successful. Native synthesis already handles
some provider failures by returning empty findings; this profile does not invent a
stricter scientific policy. An escaping exception marks the review failed and all
remaining instances blocked; no proposal runs. Timeout/interruption retains the
existing uncertain-outcome behavior.

This explicit native code/CLI/operation route also accepts inputs from
[reusable source preparation](../candidate_prepare/candidate-prepare-contract.md#reusable-native-literature-candidate),
with the same source available to code and the existing source editor. Captured
review settings appear in GUI review; dedicated visual creation controls are not
added. There is no per-review freeform human
advice field, N-way aggregation, parallelism, training, conditional routing, buffer,
human pause or resume. Shared proposal advice is not literature advice. Historical
scientific settings remain experiment-owned. Omitted/default fixed, fanout and
family profiles retain their serialization and native scientific payloads.

### Literature adaptor profiles (S2 collection, S3 split; B6-4)

Two opt-in v1 profiles (`fanout.LITERATURE_COLLECTION_PROFILE`,
`fanout.LITERATURE_SPLIT_PROFILE`) connect reviews to proposals through one declared
deterministic adaptor. Both reuse the single-review profile above for every review
(external `literature.input`, managed storage/cache/diagnostic paths, route,
network and task/constraint admission against **every** proposal seed the review
feeds, `capture_record`) and the family branch ownership rules
(`_proposal_branches`) for proposals, implementations and validators. No tuner, loop
or route is admitted. `ProposalFamilies.literature_adaptor =
LiteratureAdaptorEdges(adaptor, reviews, protocol, proposals)` records the reviews in
the adaptor's declared binding order (`LiteratureReview(node, binding)`) and each
proposal's seed binding and adaptor output index (`LiteratureProposal(node,
seed_binding, index)`); `ProposalFamilies.literature_reviews` lists the review ids of
either literature shape. Proposal diagnostics are per node
(`candidate_run/proposal_inputs/<proposal-id>.json`, debug under
`candidate_run/debug/<proposal-id>/`).

| Profile | Admission (`fanout.literature_collection_candidate` / `literature_split_candidate`) |
| --- | --- |
| `native-literature-collection/v1` (S2) | ≥ 1 external reviews; one adaptor with one `literature.output` port binding every review result exactly once, `collect/v1` + `all/v1` + `single/v1`; exactly one proposal using `literature-collection-to-proposal(reviews=AdaptorSource(<adaptor>), proposal_input=<external seed>)`; its complete branches |
| `native-literature-split/v1` (S3) | exactly one external review; one adaptor with one `literature.output` port bound to it and `split-items/v1(field="findings", count=M, on_short)` after any COMBINE/SELECT pair the declaration validation table admits (S3 is `field-rank/v1(confidence, descending)` + `top-k/v1(k)`); exactly M proposals, each `literature-to-proposal(output=AdaptorSource(<adaptor>, index=i), proposal_input=<external seed>)`, indices `0..M-1` each bound once; one complete family per proposal |

**Protocol application** (`literature_edges.proposal_input`, the one owner unit
dispatch and the verifier call). The single-review profile keeps
`local_typed_evidence(review, proposal_input=seed)` unchanged. S2 converts the
adaptor's `CollectedItems` into the catalogued `literature.collection`
(`literature_collection`: one `NamedLiteratureReviewOutput(contribution_id=<source
review node id>, output=<review>)` per collected entry, in collected order) and
applies `local_typed_evidence_many`; the proposer prompt therefore renders the
existing collection section, one `### Review: <review node id>` heading per review in
declared binding order, never completion order. Renaming a review node therefore
changes the proposer prompt (operator-accepted, 2026-10-28). This profile is the first
framework producer of a collection: before B6-4 only hand-written
`ProposalInput.literature_review_evidence` seeds reached the collection renderer.
Every proposal seed under either adaptor profile must leave
`literature_review_evidence` unset; `materialize_fanout` refuses one that carries it
before any review or proposer call (the reusable-preparation rule). S3 applies `local_typed_evidence` to
output `i`, a `LiteratureReviewOutput` whose `findings` hold exactly the one entry
`split-items/v1` placed there (all other fields of the review unchanged), so family
`i` sees the singular literature section with that one claim. With `field-rank/v1`
+ `top-k/v1`, index `i` is the `i`-th ranked finding by self-reported `confidence`
(the ranking's `provenance="self-reported"` is recorded in the adaptor record, not
rendered in the prompt). No prompt template, agent schema or rendering owner changes
(`rendering_assembly_digest` unchanged).

**Shortfall and per-index skip.** Under `on_short="skip"`, fewer than M split entries
leave indices `n..M-1` `skipped` in the outcome and record. Under `field-rank/v1`
a finding whose `confidence` is `None` is unranked and never kept by `top-k/v1`, so
unscored findings alone can cause a shortfall (and a skip or failure per `on_short`). `adaptor_phase.skipped_inputs`
maps every node whose request reads a skipped index to `insufficient_items`;
`readiness_input(..., skipped_inputs=...)` sets `NodeReadiness.skipped_input`, and
`_close_reason` closes that node `skipped/insufficient_items` after the blocked rule
(a failed/rejected/blocked source still blocks) and before its own route decision.
`readiness.SKIP_REASONS` now holds `route_not_selected` and `insufficient_items`, so
generic skip propagation carries the reason to the family's implementation and
validator. A skipped node is neutral in `body_status`; a node skipped this way cannot
feed an adaptor (`SkippedAdaptorInputError`, no profile binds one). Under
`on_short="fail"` any shortfall closes the adaptor `failed/insufficient_items` with its
record; more split entries than M closes it `failed/too_many_items` (never truncated;
`GraphReason` gains `too_many_items`). A failed adaptor stops later effects, so every
proposal is `blocked` and the body is `failed`. Zero admissible inputs or zero entries
without a fail policy is `rejected` (no outputs), which blocks every proposal.

**Verification.** `verify_graph_trace` recomputes the adaptors
(`verify_adaptors`) before readiness replay and replays with the recomputed
`skipped_inputs`, so a proposal that ran on a non-emitted index, or a family skipped
despite an emitted one or with another reason, is refused ("graph trace violates
serial readiness"). `literature_edges.verify_literature_evidence` (moved from
`graph_evidence`, extended to many reviews and proposals) checks every succeeded
review's diagnostic input against its capture and every fed seed, the review record's
digest and run binding, and requires each succeeded proposal's diagnostic input to
equal `proposal_input` over the verified review records and adaptor outcomes (a
reordered collection or a sibling's finding is refused: "proposal input does not match
the declared literature edge").
Witness: `tests/unit/tools/candidate_worker/test_literature_adaptors.py` (binding
order over execution order with per-review attribution in the proposer prompt; a seed
already carrying literature evidence refused before any call; self-reported ranking
provenance in the S3 record;
skip of the short index with ranked findings per family; relabelled skip and swapped
finding refused; `on_short="fail"` and `too_many_items` failures recorded and blocking;
admission refusals).

Not admitted: v2 reusable source, managed preparation and console for these profiles
(B6-7); tuning after either profile; collection over other contracts
(`tuning.collection`, B6-9); `per-item/v1` and `replicate/v1` distribution; custom and
LLM strategies.

## Opt-in native interpretation candidate

`WorkflowPreviewRequest.execution_profile="native-interpretation-candidate/v1"`
executes a concrete `WorkflowDocument` with exactly one externally supplied
`interpretation.input`, one `interpretation-to-proposal` edge, and one complete
proposal/implementation/validation branch. The existing declaration dependency
check and serial AND readiness determine order, including declarations whose
interpreter appears after its consumers in source. Reusable managed-source preparation uses the
[reusable interpretation profile](../candidate_prepare/candidate-prepare-contract.md#reusable-native-interpretation-candidate);
the authored feedback loop and its Pause/Resume are specified under
[Declared finite research body](#declared-finite-research-body). An optional fifth
node may tune that branch using `validated-candidate-to-tuning` with the same
proposal/validation lineage and an explicit `native-training.settings` binding.

The interpretation input is the existing native `InterpretationInput`: explicit
`cold_start=True` uses the node's honest no-prior-evidence branch; supplied typed
summaries use the ordinary interpretation path. No tuner result or prior history
is synthesized. Storage, iteration, composed task description/blocks, metric
identity, description-source policy and constraint disclosures are checked before
node construction. Native schema/constraint owners retain scientific validation.

The bounded protocol exposes these native `local_full_context` arguments:

| Argument | Source |
| --- | --- |
| `output` | This interpretation node's result |
| `storage` | Explicit managed proposal `StorageConfig` |
| `data_dir` | Explicit physical task root |
| `task_composition_ref` | Explicit native task projection |
| `human_advice`, `expert_context` | Optional native advice/context values |
| `constraint_context`, `workflow_parameter_rules` | Optional native disclosures/rules |

All arguments except `output` use captured external bindings. Although the native
function accepts a null task projection/data root for other callers, this composed
execution profile requires their actual values. Unlisted arguments are refused by
the catalog; omitted optional parameters retain the native adapter's defaults.
There is no proposal seed to overlay. After interpretation completes, the unchanged
native adapter creates `ProposalInput`; composition supplies task description,
forward contract and proposer blocks, and existing proposal/branch materialization
checks the resulting input before downstream execution. Human advice reaches the
existing protocol unchanged; this slice does not modify prompt precedence.
Captured workflow proposer routing selects the reasoning pipeline through the
shared `get_reasoning_pipeline` owner, and parent replay uses the same captured
configuration without introducing stage configuration.

Invocation accounting uses the existing node/run/iteration identity. Input capture
is under `candidate_run/interpretation_inputs/<node>.json` for iteration one, with
later internal invocations using B1b's numbered control directory. Output uses the
native `interpretation_<run>.json` record in that node's managed graph slot. The
worker captures missing native persistence (including the cold-start early return)
and preserves existing native bytes. Parent verification checks captured inputs,
record identities, readiness and the native protocol projection independently.
Task description is also compared with the captured interpretation input. Forward
contract and proposer blocks remain checked by child composition and
`materialize_proposal`; the parent does not execute task plugins or claim an
independent reconstruction of those two task fields.

Existing execution profiles, default iteration-one paths, fixed native workflow,
scientific policy and historical prompt profiles are unchanged. Offline stub
witnesses establish this transport/execution boundary, not scientific training or
historical rendering qualification.


### Native training after interpretation

For the five-node shape, `admit_training` runs before interpretation or provider
construction. Existing task, measurement, hardware, run-invariant and constraint
owners admit the selected training settings. Explicit interpreter disclosures,
workflow rules and the structured-Health flag must agree with those owners;
omitted launch facts are filled. Human advice and explicit history are preserved.
The native interpretation adapter still owns the proposal mapping. Its late input
is serialized with `exclude_unset=True` so schema defaults do not masquerade as
explicit user choices during `reconcile_proposal`.

Only successful validation dispatches tuning. `training.run_training` shares
native construction admission, plugin/loss staging and tuner preparation/execution
with the fixed wrapper. The declared tuner has its own graph storage slot;
`candidate_run/tuning_inputs/<node>.json` captures the native input (numbered
control directory for later internal iteration). Existing fixed training keeps
its model-named directory and four-record receipt. Invocation identity uses
`FixedInvocationContext`; the shared preparation call requires an explicit
incumbent reference. Fresh public invocations pass `None`, not a fabricated score.
Internal callers can transport an explicit incumbent and iteration; this does not
qualify imported history or implement loop dispatch.

A returned native tuner output produces `completed`, independent of scientific
score or Formal validity. Native `infrastructure_abort` instead produces `failed`
with its native record retained. `validation_passed` reports the validator's result
even when subsequent tuning fails. The parent permits failed-with-record only for
that verified tuner termination, rechecks graph readiness and native output
identity, and refuses relabeling it as completion. Other failed nodes cannot claim
records. Graph training uses `GraphTrace`, not the fixed `training_output` field.

Parent replay compares the declared adapter/advice and preparation-known launch
projection, managed slots, typed native input/output lineage and explicit constraint
transport. Actual hardware and fully composed runtime constraints remain checked
by child admission; comparing their transport does not independently certify them.
The parent does not run task plugins or derive a scientific expectation from a
returned score. Offline five-node witnesses stub provider/tuner and external
hardware/measurement effects: they establish dispatch/evidence behavior, not real
training or historical-profile/paper qualification.

## Declared finite research body

A concrete `WorkflowDefinition.loop` optionally carries `AuthoredLoop` with a
positive `final_iteration` and explicit `LoopFeedback`. The feedback names the
body's tuner result, interpreter target, `protocol="tuning-to-interpretation"`,
and `history="native-research/v1"`. Admission requires the supported
`native-interpretation-candidate/v1` interpretation→proposal→implementation→
validation→tuning body. The optional declaration is omitted from serialized
source when absent; the existing single-body path remains unchanged. Reusable
source preserves this declaration but its profile preparation has a separate owner.

The worker claims one fresh workspace, captures source and external inputs once,
and holds the existing native writer lease throughout finite execution. Each body
uses its explicit invocation iteration and managed node storage. Later-body input
materialization reads the original captures and changes only declared managed
storage, iteration and native history fields. It does not rewrite authored source,
change its digest, replace static task/launch/advice inputs, or launch another
fresh-workspace request against used storage.

`workflows.research_history` owns the extracted completed-body transition shared
with the fixed native workflow: bounded tuner feedback, cache retention, prediction
memory, vocabulary confirmations, accumulated findings, previous proposal and
strictly-better valid Formal incumbent updates. An authored initial summary is
not by itself a qualified Formal incumbent. An explicit seed metric binds identity;
when omitted, committed native tuner metric stamps supply history/cache ordering
and later interpretation inputs. Subsequent stamps reconcile against the prior
known metric. Missing identity remains unknown; no task name supplies a default. Authored replay resolves Health roles
through `core.resume.commit_time_gate_ids`, using the committed output's stamped
effective policy as native resume does. Unknown policy remains unknown; an
explicitly health-disabled record retains the native classifier's semantics.
The existing fixed workflow retains its task-resolved Health roster and early
abort/promotion ordering. No new scientific ranking or feedback policy is added.

A body must finish with successful required producers before the next body can
start. Rejected validation, missing/failed producer records, infrastructure abort,
or failed evidence verification stop progression. Native failed tuner records
remain available as failed body evidence. Experiment-source inheritance is still
explicitly unsupported; this is not full fixed-native parity.

Each attempted body publishes an ordinary graph receipt at
`candidate_control_dir(workspace, iteration=N)/body.json`. The aggregate receipt
has `loop_trace.attempted_iterations`; it does not impersonate one graph trace or
flatten repeated node IDs into root scientific fields. `verify_loop` verifies
contiguous body identities and native record bindings, replays the same history
transition, checks actual generated inputs/incumbent transport, and rejects an
aggregate hiding a later dispatched body; it returns the accepted body receipts in
iteration order (empty when no body index is verified) for read-only consumers
such as the console graph-results projection. Parent verification never composes task
plugins or invokes agents. Child native admission retains ownership of actual
task, hardware, full constraints and Health execution; replay is not additional
scientific certification. Timeout/interruption retains the existing supervisor
status and may leave completed body records without a successful aggregate.

`tools.candidate_operations.request_loop_stop(config, operation_id)` accepts only
an operation-bound, already-claimed, confirmed-running authored finite loop. It
verifies the saved request/run identity and publishes an immutable `stop.json`
marker in native control storage. Acknowledgement means requested, not stopped.
The worker checks it before each body dispatch; once that check passes, the body
counts as active even if the request arrives before its first node starts. It
finishes that active body and reports
`stopped` unless the finite limit or a native failure completes first. Repeating
an identical request is idempotent. Queued/not-yet-claimed operations refuse with
`not_ready`; this operation does not create their workspace. Stop is neither an
immediate signal nor resumable Pause. The console's **Stop at next boundary**
control and the `stop-loop` operation CLI call this same operation
([console contract](../candidate_console/console-contract.md#authored-loop-stop-and-state));
completed-boundary Pause/Resume follows below.

Offline acceptance covers two actual native bodies with typed feedback and advice,
source roundtrip, parent input-tamper refusal, operation-bound graceful Stop, and
failed required feedback preventing another dispatch. Provider/training effects
are doubled; these witnesses make no real-training or paper qualification claim.


### Clean completed-boundary Pause and Resume

`request_loop_pause(config, operation_id)` requests Pause for the selected running
segment. A request before that segment's first body lets one body finish; later
requests are observed at the next boundary check. The declared finite limit or a
native failure wins over Pause; Stop wins when both control requests are pending.
Pause is not immediate cancellation. A paused receipt's completed-body count exceeds
its segment's resume point (zero for the initial segment), so a successor never pauses
before dispatching its own body, and it cannot represent unfinished required feedback.
A resumed segment that reaches its boundary without dispatching keeps the last
completed body's `validation_passed`.

Native iteration ownership must close cleanly before child receipt publication.
The loop launcher retains `run_observed` supervision before publishing the final
receipt: successful child exit, reaping and proven absent process group are required
for `paused`. An unresolved native lease or uncertain supervision produces failure,
not a resumable checkpoint. The existing `iteration_owner` context now yields its
lease on Linux; callers ignoring the context value retain their behavior. Guarded
Pause is unavailable without that lease. Fixed profiles reject loop control statuses.

A continuation has a distinct operation/segment UUID but preserves the original
run_id, task/source/input snapshots, routes, finite limit, advice and token ledger.
Its controls live at `candidate_run/continuations/<operation-id>/`; the original
request, receipts and completed body records are never rewritten. Each segment owns
its Pause marker, so an old Pause never pauses the successor; Pause the successor by
its own operation ID. Root Stop remains run-wide and terminal. `loop_trace.segment_id`
is omitted on the initial segment and identifies later segments. Native body records
keep their existing numbered iteration slots. Logs are selected by operation;
the receipt's root log identity remains unchanged with the original invocation.

Only the internal admitted continuation entry can restart execution. Under the
native writer lease it verifies the immutable predecessor/successor binding, rejects
a partial next slot, and reconstructs ChainState through the same native completed
history fold before dispatching N+1. Captured inputs and original external identities
must still match; changing workflow source or configuration requires a new run.
Historical paused receipts can coexist with later bodies only through the exact
verified successor binding. There is no general partial-record acceptance switch.

Resume does not recover failed, stopped, interrupted, timed-out or uncertain runs.
It does not change the declared loop limit or scientific history policy. The existing
sandbox timeout applies independently to each launch. The operation contract owns
single-successor reservation and requires the predecessor wrapper to have exited;
a visible paused receipt while that wrapper is finishing is not authorization.

Offline acceptance adds a process-separated witness: body 1 pauses, both processes
exit, a new operation dispatches bodies 2 and 3 despite the old Pause, and the
resumed body-2 interpretation input equals an uninterrupted run's except storage
paths and minted candidate IDs. The same witnesses cover Stop and native failure
winning over Pause, the final body winning over a successor Pause, and an unresolved
lease or uncertain supervision publishing failure. Provider/training effects remain
doubled.

### Deterministic stop conditions

`AuthoredLoop.stop_conditions` optionally declares hard criteria that complete the
loop before `final_iteration` (declaration fields: the workflow definition contract).
They are evaluated by `tools.candidate_worker.loop_stop.evaluate_stop`, a pure,
stateless function of a typed `StopEvaluationInput` (`iteration`, `final_iteration`,
`conditions`, every completed body's `BodyScore(iteration, valid_formal,
metric_spec)` from 1 to now, and the reconciled run `metric`) returning a typed
`StopEvaluationOutput(decision="continue"|"stop", reason)`. `BodyScore` is projected
from each verified body's committed tuning record; the evaluator never reads or
mutates `ChainState` or native history. The metric is reconciled once over the
captured seed metric and every body stamp. A future judge implements the same
contract.

The score is the loop incumbent: the best HealthGate-valid Formal score
(`best_valid_formal_denoising_score`) over all completed bodies, advanced only by a
strictly better value under the declared `MetricOrder` (the same rule as the native
history fold). `metric_threshold` stops once the incumbent exists and is at least
the threshold (ties stop); `no_improvement` stops after `completed_bodies`
consecutive bodies that did not strictly improve the incumbent (a body without a
valid Formal score is non-improving; the first valid value is an improvement).
Conditions are any-of in declared order; the first met condition wins.

Evaluation happens once per completed-body boundary, after the body is verified,
published and folded. Precedence: a body that is not completed ends the loop with
its own status and is never evaluated; the last declared iteration completes at the
limit without a reason; otherwise a met condition yields status `completed` with
`loop_trace.stop_reason` (a discriminated `metric_threshold`/`no_improvement`
reason carrying `condition_index` and the observed values) and wins over a pending
Stop or Pause at that boundary. No evaluation precedes body 1. Admission
(`admit_stop_conditions`, called by `execute_loop` before any body is dispatched)
reconciles the captured seed metric with the composed run metric — the spec every
body's tuning record stamps — and refuses with a typed `StopConditionError` naming
the condition when any `metric_threshold` names another metric id, so no body trains,
commits or is orphaned and no earlier-met condition or one-iteration limit can hide
the mismatch. The evaluator keeps the same check (`require_threshold_metrics`, the
one shared function) as its own precondition for replay over persisted records; a
run without a reconcilable metric also fails with a typed error rather than ignoring
a condition or guessing a direction.

`verify_loop` trusts no recorded value: it re-runs the evaluator at every verified
boundary, refuses a loop that continued past a met condition, and requires the
recorded `stop_reason` to equal the re-derived one exactly (absent otherwise).
A resumed segment rebuilds its score carrier from the same whole-run replay, so the
incumbent and the no-improvement window span segments. A condition-completed run is
`completed`, not a resumable checkpoint. Receipts and source without conditions are
byte-identical to those before this feature.

## Route evaluator (pure)

`tools.candidate_worker.route_eval` decides one declared `Branch` (definition
contract, "Route declarations") from one native record. Its execution caller is
`route_phase.decide_routes` under `native-routed-candidate/v1` ("Routed execution
profile" above); readiness consumes its output (skip semantics above).

- `project_observation(branch, capability, record_path, *, iteration)` reads the
  branch source's committed record once (no-follow, 4 MiB bound), validates it with
  the native output schema of `CAPABILITIES[capability].output`
  (`ValidatorOutput` for `validation.output`, `HyperparamTuningOutput` for
  `tuning.output`), and returns `RouteObservation(source_node, iteration,
  record_sha256, values, metric_spec)`. `record_sha256` hashes exactly the parsed
  bytes; `values` holds only the observables the branch reads, in first-read order,
  each taken from the native attribute `RouteObservable.attribute` (the last segment
  of its `ROUTE_OBSERVABLES` field, the same name the catalog drift test checks);
  `metric_spec` is chosen explicitly per contract (the tuning record's `metric_spec`;
  `None` for validation records). An observable outside the source contract, or a
  contract without a projection owner, raises `RouteConditionError`. Reading or
  parsing may also raise `OSError`, `ValueError` (4 MiB bound, record changed) or
  pydantic `ValidationError`: **every** projection exception fails the body
  (`route_phase.decide_routes` re-raises each as `RouteConditionError`).
- `evaluate_route(RouteEvaluationInput(branch, observation, metric))` is pure (no
  I/O). It returns `RouteEvaluationOutput(branch_id, selected_case, selected_targets,
  skipped_targets, case_results)`: cases are tested in declared order and the first
  match wins; `case_results` has one predicate outcome per case up to and including
  the match. With no match, `selected_case` is `None` and `selected_targets` is the
  default (or empty when `default` is `None`). `skipped_targets` lists every other
  entry target in declared order; arm expansion belongs to readiness.
- Leaves: `bool_is` and `enum_in` compare the projected value; `metric_at_least` is
  `MetricOrder(metric).is_at_least(value, threshold)` (ties hold; direction only from
  the run `MetricSpec`); an absent metric value makes `metric_at_least` false and
  `is_missing` true (decision B1-Q4).
- Before any case is evaluated, `evaluate_route` checks every leaf of every case:
  its observable is catalogued with the leaf's kind, present in the observation, and
  of the catalogued kind (bool; str within the catalog values; float or `None` for a
  metric). Neither an earlier matching case nor a short-circuiting `all_of`/`any_of`
  can therefore hide an unevaluable leaf.
- Fail closed (`RouteConditionError`, a `ValueError`; the body fails, never "false"):
  an observable missing from the observation, a value of the wrong kind (for example
  `None` for a bool), a `metric_at_least` without a bound run metric or naming another
  metric id, and a record `metric_spec` stamp that does not reconcile with the run
  metric (`reconcile_metric_specs`, always called; with no run metric a stamp alone is
  accepted and only `metric_at_least` needs a metric).
- Metric admission: `admit_route_metrics(branches, metric)` is the one identity check
  and runs over every case of every branch, so an earlier matching case cannot hide a
  mismatched later one. Execution admission must call it before any dispatch;
  `evaluate_route` repeats it as its own precondition for replay.

Tests: `tests/unit/tools/candidate_worker/test_route_eval.py`.
