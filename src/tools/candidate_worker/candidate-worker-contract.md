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

The parent revalidates the exact supported three-node graph, canonical selected
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

Constraint disclosure may be incomplete. Claimed task rules/objective must agree
with composition, workflow rules with the seed, and duplicated time/VRAM facts
with seed declarations. Known execution sections compare duplicated budgets including explicit nulls.
Populated overrides, timing and execution controls without a worker authority
are refused before provider calls. Unknown sections remain unknown. Hardware/VRAM inputs
are declarations, not measurements certified by this worker. Future training
budgets are not training admission. Scope, sampling, allowed outputs, parameter
locks, reasoning stages and proposal advice remain native input values.

## Native sequence and persistence

One immutable run ID, run name and logical iteration 1 reach the proposer
(including its eager/lazy stage bridges), implementor and validator through the
existing accounting helper. `WorkflowLLMConfig.get` owns constructor routing.
Native retries remain native; the worker has no retry or replay loop.

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
