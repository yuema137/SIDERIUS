# Native candidate execution contract

`CandidateRunRequest` and `launch_candidate(request, *, invocation_id=None)`
are the common JSON/Python boundary.
The CLI decodes the same request and calls that function. The parent imports
inert declaration/preview/routing schemas; it does not compose a task or import
native node implementations. `child` verifies captured inputs, binds generated
library discovery to its workspace, and only then imports `native` and task
consumers. Each launch gets a fresh interpreter through the existing sandbox.

Python callers may supply a strict UUID `invocation_id`, validated before any
filesystem effects. The native launch uses its hex form as the existing `run_id`
for artifacts and accounting. Omission preserves native `uuid4().hex` generation.
Request/receipt schemas, CLI behavior and exclusive claim ownership are unchanged;
only the claim winner can publish records with that invocation identity.

## Selected inputs and task authority

The parent revalidates the supported three- or four-node graph, canonical selected
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

## Native sequence and persistence

One immutable run ID, run name and logical iteration 1 reach the proposer
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
Values move through typed in-memory results, never peer-file communication.
Validation rejection is retained and independent siblings can continue. A native
exception aborts further effects; remaining instances become blocked. Training,
routing, loops, human pauses, buffers, cross-branch aggregation and graph resume
are not supported by this profile.

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

Reusable version-2 source and managed preparation also support this profile through
[the reusable family contract](../candidate_prepare/candidate-prepare-contract.md#reusable-independent-proposal-families).
Code callers may still supply version-1 native inputs directly. Both routes use
the same existing operation/HTTP observation without loading an editor.


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
