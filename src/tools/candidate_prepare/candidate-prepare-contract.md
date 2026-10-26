# Native candidate preparation contract

`CandidatePreparationRequest` and `prepare_candidate(request, *, invocation_id=None) ->
CandidatePreparationReceipt` are the shared Python/JSON operation. The CLI
`python -m tools.candidate_prepare --request PATH` decodes the same request and
returns zero only for `prepared`. It never launches the worker.

Python callers may supply a strict UUID `invocation_id` to bind an admitted
operation to the native preparation identity. It is validated before filesystem
effects and becomes the existing `preparation_id`; omission preserves native
`uuid4()` generation. The request/receipt schemas, CLI and exclusive output claim
are unchanged. A losing claim cannot publish a receipt with its supplied identity.

## Admission

The request is strict, frozen and rejects extra fields. Required selections:
`task_manifest`, `data_root`, `llm_config_file`, `output_dir`,
`candidate_workspace`, `run_name`, `preparation_timeout_seconds`,
`candidate_timeout_seconds`, `task_read_only`, `candidate_network`,
`candidate_devices`, `candidate_environment_names`. Optional strings
`proposal_advice`, `implementation_advice`, `validation_advice` default to None.
Optional `allowed_output_types` is the native nonempty classifier/regressor tuple;
None leaves output policy unconstrained. Timeouts are finite positive seconds.

Paths must be canonical absolute local paths. Manifest/profile are existing
regular files; data is an existing directory. Output and future workspace must
be absent (including symlinks), with existing directory parents. They cannot
overlap each other, input data/files/source mounts or protected runtime roots.
Sandbox device/environment-name and mount rules apply before ownership claim;
preparation does not require values for future environment names.

`admission` reads original manifest/profile bytes, validates the profile using
`workflow_preview.config.parse_config`, and makes no writes. The parent claims
output with exclusive mkdir; losing callers write nothing. After claim, errors
preserve partial state and attempt a failed receipt. No recursive cleanup or reuse.
Neither preparation nor the pure candidate layout helper creates the future run.

## Process and native owners

The parent imports only inert declarations, routing, observations and selected
configuration models. It never composes a task or imports native request/node
modules. `child` checks source/snapshot identity, binds generated library to the
preparation output, then imports `native`. Ambient generated models are excluded
by the existing bound-library mechanism.

The actual sandbox uses output as writable workspace, network false, no devices,
and no passed environment names. Selected manifest/profile/data and explicitly
selected dependencies are read-only mounts. Runtime mounts come from the active
checkout/environment owner. Composition executes trusted Python and can read
mounted data; preparation requests no decoding, evaluation or training. Provider
clients are never constructed by the framework preparation route. This is not
an attestation about arbitrary selected plugin behavior.

`compose_run_task_bindings`, `bind_run_task_composition` and
`build_task_composition_ref` own task resolution, physical directory admission and
identity. Native InterpretationInput uses composed task description/task blocks,
metric spec, COMPOSED description policy, explicit cold_start=True, model_types=None,
empty summaries/cache/history and no analysis request. The public node-owned
`build_cold_start_interpretation` creates InterpretationOutput without a bridge.
The native `local_full_context` protocol owns evidence/advice/contributor mapping;
`get_reasoning_pipeline` supplies the same configured stages as the Professional
workflow. Composed description/forward contract/proposal blocks and the optional
caller output restriction are validated in ProposalInput. All unexposed fields
retain native defaults. No training budget, sampling or hardware policy is inferred.

`candidate_worker.layout.candidate_proposal_dir` computes the future
`workspace/run_name/iteration_001/attempt_001`; `impl_attempt_storage` owns impl_001.
The fixed WorkflowDocument contains proposal, implementation and validation with
the two native protocols, external proposal JSON and shared implementation storage.

## Artifacts and reconciliation

Fixed bundle files: `interpretation.json`, `proposal.json`, `storage.json`,
`llm.json`, `workflow.json`, `preview_request.json`, `preview.json`,
`candidate_request.json`. Fixed control subtree: `preparation/request.json`,
`manifest.snapshot`, `llm.snapshot`, `interpretation_input.json`, `child.json`,
`receipt.json`, `worker.log` (created by the child). JSON/snapshot publications use
`publish_bytes_write_once`; the child log opens exclusively. `request.json` is a
PreparationControl envelope containing the immutable selection, preparation UUID
and original FileObservations. The child index carries control hash, native
composition fingerprint and the exact native artifact observations.

Parent reconciliation rejects non-completed process status regardless of child
files, changed sources/control/native file hashes, wrong preparation identity,
wrong fixed declaration/profile bytes, a fingerprint inconsistent with the saved
proposal reference, or a newly occupied future workspace. A narrow inert identity
projection checks the fingerprint; full native payload validation remains in the
child and later worker. Hostile-child attestation is not promised.

The parent obtains observations/routes from `preview_workflow` and emits
CandidateRunRequest with managed_fresh storage, future timeout/network/devices/
environment names and downstream advice. Future read_only is the sorted unique
union of output, data, original manifest and explicit dependencies. The profile
bytes are copied unchanged to llm.json. Successful receipt paths point only to
fixed filenames. Receipt is an index, not a new task schema or execution receipt.
The preview's execution_ready remains false. No token ledger/usage is synthesized.

Receipt status is prepared, failed, timed_out or interrupted. Failure after claim
retains evidence; failure before claim raises without writes. Parent death can
leave no terminal receipt. No automatic retry/resume or future-workspace reservation
exists. Callers must not treat partial files as a successful bundle.

## Identity and qualification limits

FileObservation hashes selected bytes, not complete dependency closure. Native
captured code packages identify their finite member set; legacy file refs hash
selected files rather than arbitrary imports, and module references have their
existing weaker coverage. Worker recomposition compares represented native facts
before providers. This operation does not broaden those guarantees or migrate tasks.
The cold-start owner move changes rendering assembly identity, and the proposal
pipeline owner is included in preflight source closure. Historical accepted hashes
are not repinned; exp-owned historical qualification remains separate.

Validation owners: frozen pre-extraction oracle and reachability tests for native
owners; scoped admission/reconciliation tests; real sandbox checks for offline
mounts/import order, timeout and prepared-bundle worker integration. Fake provider
worker checks prove native plumbing and CPU validation, not real model quality.
No paid LLM, training, scoring, GPU or full GUI claim follows from preparation.

## Shared inert bundle verification

`bundle.verify_bundle(control, read_bytes=...)` owns reconciliation of the fixed
prepared artifacts and construction of the expected candidate request. It returns
that request, observed workflow bindings and composition fingerprint without
publishing, importing task/node implementations or inspecting candidate workspace
emptiness. `launch.reconcile` retains source verification, absent-workspace checks
and publication. Public operation readers supply confined bounded reads to the
same verifier, so rereading after launch cannot replay preparation effects.

## Pure reusable declaration resolution

`resolution.resolve_reusable_candidate(document, bindings)` accepts a validated
ReusableWorkflowDocument and ReusableCandidateLocations, and returns a
ResolvedReusableCandidate containing a revalidated v1 WorkflowDocument plus
CandidatePreparationOptions. It is exported alongside the unchanged legacy
preparation API, and managed reusable preparation invokes it as described below.
It performs no reads, path traversal, allocation, native imports, payload
validation, provider work or publication. The pure function itself does not prepare or launch v2.

ReusableCandidateLocations requires explicit manifest, data_root, workspace and
an externals tuple of ResolvedExternalLocation(binding, location). IDs must be
unique and maps must exactly cover declarations. Inputs are revalidated even
when created through unchecked copies. Locations are inert strings; callers own
physical path admission and observations. No aliases or filenames select roles.

The shared candidate shape checker requires one proposal, implementation and
validation with their expected upstream results and protocols. Resolution
requires exactly one managed proposal alias used by the proposal request and
managed storage aliases used only by storage arguments; all storage aliases map
to the same explicit generated attempt-storage destination. Unused bindings,
literal proposal/storage seeds, misrouted roles, and unsupported literal roles
refuse. Optional constraint context, composition reference, provider and model
literals survive using explicit alias mappings; their bytes are not read here.

Resolution retains authored node/external/argument order, IDs, edges, layout and
preparation options. It never calls legacy candidate_document(request), whose
fixed names and graph remain unchanged. The resulting v1 declaration alone is
insufficient to launch: no native inputs, observations, request, receipt, run
identity or parent bundle verification are created. Those remain a separate
bounded integration responsibility.

## Managed reusable preparation

`ReusableCandidatePreparationRequest` and
`prepare_reusable_candidate(request) -> ReusablePreparationReceipt` implement
managed-only reusable preparation. CLI mutually exclusive `--reusable-request`
and legacy `--request` call their respective typed Python owners. Professional
and Assistant setup both use these owners; neither has another backend.
`preflight_reusable_candidate(request) -> ReusablePreparationPlan` is inert
read-only admission, not a reusable execution authorization. Preparation captures
again internally and never accepts a caller's stale plan.

Required reusable selections: canonical absolute `source_path`, `project_root`,
existing `runs_root`, expected lowercase SHA-256, explicit UUID `run_id`, plus
legacy run_name/config/timeouts/task mounts/future sandbox policy. Source owns
task references and all preparation options. Relative task paths resolve once
against project_root. A's resolver owns graph/role validation and mapping;
preparation rejects every literal external before allocation. v1 optional
literal handling and legacy PreparationControl serialization are unchanged.

`reusable_admission.capture` reads original source once as a bounded regular
no-follow file, using the restricted parser's source limit. Those same bytes
supply parse/hash/snapshot. Native artifact reads use a preparation-local 16 MiB
bound; this does not import the independent operation store's private-file or
error contract. Canonical path admission and safe reads reject aliases. Parent
origin rechecks detect drift without replacing captured bytes. Existing task
manifest/profile observations are retained; this is not a snapshot of every
imported dependency. The existing admission policy now accepts an explicit
future parent only for the reusable envelope's actual children and validates
the envelope itself against protected/input/data/mount roots. Legacy defaults
still require existing destination parents.

The exclusive `runs_root/<run_id>` claim precedes all publications. The losing
caller writes nothing. `binding.json` stores `ReusableBindingCapture`: original
FileObservation, fixed snapshot path, project base, reusable semantic digest,
resolved native selections, A locations, and input observations. Exact original
bytes live only in `workflow.py.snapshot`, not another serialized source string.
`inputs/` contains the native bundle; sibling `workspace/` stays absent. UUID
run_id identifies this envelope, preparation_id identifies the offline child,
and the eventual worker run_id is separately owned. They are not interchangeable.

`ReusablePreparationControl` adds an explicit reusable kind and binding path/hash
beside the unchanged legacy type. `reusable_child` is a separate explicit module
entrypoint. The sandbox supervisor is shared with legacy preparation; only exact
parent binding/snapshot files are mounted read-only, never their envelope parent.
The child verifies capture/control, binds generated library, and calls shared
`native.prepare_payloads`. Legacy `prepare_native` separately publishes its fixed
`candidate_document`; reusable publishes A's resolved authored graph plus canonical
`workflow.resolved.py`. `REUSABLE_FILES` adds that source to unchanged NATIVE_FILES.

`reusable_verify` receives retained parent plan/source/control. It compares exact
saved parent bytes and child index/control identity, independently reruns A
resolution, verifies the complete artifact index, canonical derived source,
profile bytes and composition fingerprint linkage. Narrow inert projections
check native proposal storage and advice/output types. Existing StorageConfig,
candidate_proposal_dir and impl_attempt_storage own the two concrete native
storage destinations. Native child/worker still own full scientific decoding.
Source options are independently checked against native selections, including
implementation/validation advice outside v1 graph equality. Shared build_candidate
uses existing preview/config owners for observations, routes and worker policy;
multiple storage aliases retain distinct observation references.

CandidateRunRequest.workflow_source captures the derived v1 source with its
resolved origin path/hash and reviewed_context=None. The unchanged worker source
validator checks equality with the v1 preview. Parent publishes preview/request
only after bundle checks and rechecks capture/input/publication bytes before
receipt. `inputs/preparation/receipt.json` remains the native preparation receipt;
top-level `receipt.json` is published last with binding/request/preview digests.
Statuses are prepared/failed/timed_out/interrupted. Failures preserve partial
evidence and attempt terminal receipts without overwrite. Late failures may
leave request-shaped diagnostics: only a prepared top-level receipt with matching
digests establishes reusable success. Missing receipt is unknown. Collision is
not retry/resume, and there is no auto-cleanup or ID substitution.

The preparation guarantee is coherence of original capture, binding and request
at successful publication. Later original-v2 provenance verification is provided
by the retained-selection API below and consumed by candidate operations.
Direct worker launch still validates resolved-v1 inputs only. GUI adapters consume
this preparation API and retained-selection verification through the
[console contract](../candidate_console/console-contract.md#new-run-from-saved-reusable-source);
this owner does not implement UI behavior. Resume and literal materialization
remain unsupported by reusable preparation.

## Retained reusable selection verification

`ReusablePreparedSelection(envelope, expected_receipt_sha256)` is a strict inert
selection: a canonical absolute UUID envelope and caller-retained lowercase
SHA-256 of its exact `receipt.json` bytes. `select_reusable_preparation(envelope)`
reads and verifies the currently published bundle and returns that selection.
Call it immediately after successful preparation to select the publication, then
retain the returned object outside the mutable envelope (for example in the
operation submission). Calling it later explicitly selects the current bytes;
it cannot recover independent historical authenticity. Never recompute the
expected digest during admission or retry. A known retained digest can also be
supplied directly through `ReusablePreparedSelection`.

Published receipt bytes are indented JSON plus a trailing newline. Hashing CLI
stdout or arbitrary model JSON does not identify those bytes. The selection API
reads the actual fixed receipt once, hashes those same bytes, then verifies with
that same per-pass reader. It is intended for callers selecting trusted local
paths; operation-facing review additionally enforces configured root policy.

`verify_reusable_preparation(selection) -> VerifiedReusablePreparation` performs
fresh bounded read-only verification and returns the exact validated candidate
request, retained selection, binding, top receipt, native preparation UUID and
composition fingerprint. It creates no directories, executes no task code, calls
no provider, and does not require a fresh/absent envelope or workspace. Each call
has its own byte cache; hashing, observation and decoding use the same bytes per
path. It uses canonical/no-follow regular-file reads capped at 16 MiB and the
original parser's smaller source limit. Existing trusted-root path policy is
preserved, not upgraded to hostile same-UID filesystem attestation.

Verification requires a complete successful top receipt with fixed paths and
canonical envelope UUID; it checks exact receipt, binding and candidate-request
hashes before decoding their corresponding payloads. It compares the snapshot
against the original observation's path/reference/hash/size, parses v2 and checks
its semantic digest. It never calls `verify_origin` or reads current canonical
workflow contents. Edits after preparation affect future captures only.

`reusable_admission.reusable_locations` is the shared managed-only layout mapper
for initial capture and retained verification. It independently reconstructs task
paths from captured source/project and proposal/storage/workspace paths from the
fixed envelope layout, then compares binding and native request destinations.
The existing A resolver checks the authored graph and source options.
`verify_sources` checks manifest/config references, paths and observed bytes.
Saved reusable control must agree with pinned request/sources/binding path/hash.
`reusable_verify.verify_reusable_bundle(read_bytes=...)` remains the sole native
bundle verifier: artifact index, derived v1 document/source, profile, composition
linkage, native storage and advice/output options, and independently expected
candidate request. The exact decoded candidate must equal that expected request.

The preview is hashed against the receipt and compared with the verifier's
bindings and the preparation-time `workspace_state="absent"`; this does not assert
that the current workspace is still absent. Native receipt status, UUID, paths,
source observations and composition linkage must agree. Its bytes are diagnostic
consistency evidence, not independently pinned by the top receipt. No promise
covers every imported task dependency. Existing worker checks remain authoritative
at actual launch. Missing/partial/failed receipts, unsafe reads, changed inputs,
wrong graph/options/storage or mismatched native relationships refuse without
writes. B1's two publication checks remain independent fresh passes with its
parent-held plan/source/control, not a cache retained from an earlier pass.

See [operation binding](../candidate_operations/candidate-operations-contract.md#retained-reusable-candidate-operations)
for root-aware review, submission identity, dispatch and retry. Preparation,
admission and native terminal state are three distinct events.


## Reusable request recipe

A coding agent or Python caller constructs the strict request from explicit
operator choices. Compute the expected source identity and allocate a fresh UUID
programmatically; do not ask the operator to transcribe or compare digest strings.
The preparation owner reobserves the source and refuses drift before allocation.
For example, in the selected checkout's frozen environment:

```python
import hashlib
from pathlib import Path
from uuid import uuid4

from tools.candidate_prepare import ReusableCandidatePreparationRequest

project = Path("/projects/my-task").resolve()
source = project / "workflow.py"
request = ReusableCandidatePreparationRequest(
    source_path=str(source),
    project_root=str(project),
    expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    runs_root="/runs/my-task",  # Existing, outside task/data mounts.
    run_id=uuid4(),
    run_name="candidate",
    llm_config_file=str(project / "llm.json"),
    preparation_timeout_seconds=60.0,
    candidate_timeout_seconds=600.0,
    task_read_only=(str(project / "package"),),
    candidate_network=True,
    candidate_devices=(),
    candidate_environment_names=("OPENAI_API_KEY",),
)
(project / "reusable-request.json").write_text(request.model_dump_json(indent=2))
```

Substitute the operator's selected paths, budgets and enabled provider names;
no example choice creates scientific defaults or launch permission. The API's
receipt digests are machine-consumed integrity fields. The retained-selection
consumer validates them against caller-retained expected identity as specified
above; the human-facing success signal is prepared status and CLI exit zero.


### Policy preinspection of a retained capture

`inspect_current_reusable_binding(envelope)` selects current exact receipt bytes;
`inspect_reusable_binding(selection)` inspects caller-retained identity. Both return
`ReusableBindingInspection` (selection, binding, receipt and control), reusing the
full verifier's prefix: bounded regular-file reads, canonical UUID/fixed paths,
complete prepared receipt, receipt-to-binding digest, and control request/sources
matching the binding. They do not read external observation contents or certify
complete preparation. Callers must apply external path/resource policy and then
invoke full retained verification or the operation builder with the same selection.
These are Python owner seams, not arbitrary-path HTTP endpoints.


## Detached invocation and historical terminal identity

`prepare_reusable_candidate(request, *, invocation_id=None,
expected_observations=None)` remains the sole B1 execution owner. Omitted invocation
ID creates a native UUID; supplied IDs are strictly validated before effects.
`ReusablePreparationObservations` holds the original source plus ordered manifest
and config observations derived from the plan binding. When supplied, B1 compares
it against its actual new capture before origin verification and envelope mkdir.
Admission prechecks cannot substitute for this comparison. Later drift continues
to fail through the existing origin guard.

New top receipts include `preparation_id`, even for failure before control
publication. Legacy receipts may lack it: serialization omits that field alone
when None and preserves other optional null fields. Whenever present, retained
binding inspection verifies correspondence with control.

`reusable_terminal.read_reusable_terminal(request, observations, invocation_id,
*, expected_receipt_sha256=None)` returns a typed top receipt and its exact raw
SHA, or None for a missing unpinned top receipt. It uses fixed bounded no-follow
capture reads and shared source/resolution owners, not `capture`, `verify_origin`,
`admit`, task imports or full selection verification. Contradictory identities,
statuses/errors or incomplete referenced evidence raise. Success requires native
control/inner receipt plus prepared artifact references. Failure without an inner
receipt can be verified when binding/snapshot evidence exists; any present control
is checked. Missing early binding/snapshot evidence cannot certify terminal failure.
A missing pinned top receipt raises; an inner receipt cannot replace it.

This helper establishes historical preparation identity for operation monitoring.
It deliberately does not certify current launch eligibility. B2/B3 still use the
full retained verifier and reobserve external inputs before candidate launch.


### Source-only preparation policy projection

`inspect_reusable_source(request)` returns inert `ReusableSourceInspection`:
source observation, parsed reusable document, resolved locations/document and typed
native request. It shares the bounded regular/no-follow reader, parser, managed-only
layout and resolver with `capture`. Canonicalization and destination/path metadata
checks may occur; manifest/config content reads, imports and writes do not.
`capture` retains the same internally captured source bytes for snapshot publication,
then calls full admission. Console fresh review/prepare uses this projection to
reject unconfigured task/resource references before full external-content preflight.
It is not a full admission or a reusable authorization token.


## Reusable native training inputs

A supported fourth tuning node pairs with one managed `native-training.settings`
external and sparse document `training_settings`. The role maps only to
`inputs/training_settings.json`. Native settings validation refuses unsupported
controls and explicit disabled probe requirements. Non-null external Health config
is refused before content reads; source/manifest/config observation census is unchanged.

`effective_training_settings` preserves authored keys and inserts only absent
`launch.allowed_output_types` from preparation options, including explicit null.
An explicit conflict refuses. Original source remains sparse. `reusable_files`
returns unchanged `REUSABLE_FILES` for three-stage mode and adds only that settings
file for four-stage mode. Child and parent use the same census; parent independently
regenerates settings bytes and expected proposal facts from retained source.

Native-owned `proposal_training_values` projects budgets, rules, sampling seed,
trial identity, output types, baseline isolation, supplied/default data scope,
portions, structured Health feedback and active VRAM. Managed seeds explicitly
serialize these, including null, while omitting runtime hardware and constraint
context. Worker reconciliation remains authoritative and rejects explicit v1
conflicts. Training base seed stays in settings and reaches the native tuner.
Retained selection repeats these checks without needing current source. Child
hash repair cannot legitimize substituted settings/seed facts. Terminal operation
reads verify the native output digest and identity, not every checkpoint or
scientific success. No outer loops, resume or historical defaults are added.

### Accepted task binding enforcement

A v2 `TaskBinding` is optional; None/absence retains the exact legacy source,
request/control/receipt and native payload contracts. Source-only inspection
retains the declaration without importing task code or reading external contents.
Full capture preserves the exact original source in the existing snapshot and
its typed document in the parent plan; no second pin or identity registry is added.

After verifying capture/control/snapshot identity, `reusable_child` forwards the
captured document's pin to `native.prepare_payloads(expected_task_binding=None)`.
The native owner composes once and constructs its existing `TaskCompositionRef`.
Before proposal construction or any native payload write, a supplied pin must
match both semantic_fingerprint and task_data_path_id. Package/revision labels
are readable metadata, not another identity algorithm. Native mismatch fails the
child; existing capture/worker diagnostics and failed receipts may remain, but
no native proposal/storage payload or successful candidate request is published.
This is preparation, never provider execution, training or launch approval.

Parent `reusable_verify.verify_payloads` separately compares both raw proposal
identity fields to the retained `plan.document.task_binding`, in addition to its
existing child-index/proposal fingerprint linkage. Missing task_data_path_id is
permitted by the inert projection for old unbound fixtures, but refuses a bound
plan. A self-consistent forged child index/fingerprint cannot replace the accepted
parent pin. Existing exact-byte snapshot/binding/control, artifact census/hash,
profile/options/storage and receipt-last checks remain unchanged. No parent
composition or extra observation child is introduced.

Retained verification uses captured source, preserving old runs after current
source edits. At actual launch the existing native worker materialize_proposal
check compares the whole TaskCompositionRef against fresh composition; later task
drift remains that owner's refusal. Native assembly fingerprints remain authoritative;
a declaration of a readable version cannot suppress their mismatch. Arbitrary
task migration and graphical task/version selection are separate capabilities.

## Reusable proposal fanout

A v2 source can explicitly select `execution_profile="native-proposal-fanout/v1"`.
Omission retains fixed three/four-stage preparation and its existing bytes. The
profile participates in the source semantic digest and is reconstructed from the
captured source when the parent builds the worker request. It is never inferred
from node count or accepted from child output. The existing G1 shape owner admits
one proposal, one or more implementations and exactly one matching validator per
implementation, with each validator consuming both proposal and implementation
results. `training_settings` is unsupported with this profile.

The shared preparation layout uses the existing graph instance and first-attempt
storage owners. `proposal.json` uses the proposal instance directory; each
implementation owns `storage.<implementation-id>.json`. Its validator uses that
same storage through its declared implementation result edge. Different external
aliases within one branch may select the same file; aliases shared across branches
refuse. Locations must exactly match the generated binding map. Reordered node
declarations do not change which implementation owns a validator's storage.

The exact artifact index replaces `storage.json` in `NATIVE_FILES` with branch
storage files in admitted implementation order, followed by the usual
`workflow.resolved.py`. There are B+6 files for B branches. The parent derives the
same census from retained source and rejects missing, extra or reordered index
entries and incorrect storage even if a child recomputes their hashes. This is
index membership, not a recursive prohibition on diagnostic files. Both A2 task
pin checks remain before successful publication.

Graph preparation applies the existing 4 MiB control encoder to capture/control,
child index and published preview/request records before successful publication.
Every graph-native payload write uses the preparation reader's existing 16 MiB
per-file ceiling. Source remains limited to 1 MiB, 100,000 AST nodes and depth 64.
No arbitrary branch-count limit is added. Captured reads cache each path once;
there is no independent aggregate memory budget. Overflow may preserve partial
diagnostics but cannot produce a successful preparation receipt or launch.

The saved candidate request selects the existing G1 dispatcher and trace verifier.
Python, CLI and the existing saved-source review/preparation/launch transport use
that same request. This adds no graph editing controls, training branch,
aggregation, new scheduler, resume or additional capability adapters.

## Reusable independent proposal families

A v2 document can select `execution_profile="native-proposal-families/v1"` and
independently declare several proposal instances with complete native branches.
For example, `hypothesis -> build_left/check_left, build_right/check_right` and
`alternate -> build_other/check_other` prepare two seeds and three implementation
storage records. The existing family admission owns exact typed edges; a validator
must consume its implementation's proposal. Every proposer needs its own managed
`proposal.input` binding. Storage aliases may be shared only by the implementation
and validator that own the same attempt. Unused or cross-owner aliases refuse.

Preparation composes the task and cold interpretation once, verifies the accepted
task binding before publishing native payloads, then maps each seed with the same
native protocol and source-owned preparation options. No native agent, schema or
prompt format changes. Advice, output restrictions and constructor settings remain
shared source selections; there is no new per-node settings editor. Native debug
dumps remain unset by managed preparation. Explicit native callers retain the
worker's separately admitted per-proposal debug path capability.

The ordered native index contains `preparation/interpretation_input.json`,
`interpretation.json`, `proposal.<proposal-id>.json` in proposal declaration order,
`storage.<implementation-id>.json` in admitted family/branch order, `llm.json`,
`workflow.json` and `workflow.resolved.py`: exactly P+B+5 entries. Each seed's native
storage belongs to its declared proposal instance. The parent independently
reconstructs all names, paths, observations, pins, source options and the candidate
request; a repaired child index cannot authorize a swapped or missing family seed.
The existing byte limits apply without truncation or a new node-count policy.

For this explicit family profile only, a successful native preparation receipt has
`status="prepared", proposal_path=null`: there is no singular proposal file. The
complete existing artifact index identifies the seeds. The top reusable receipt,
retained selection, full verifier and operation terminal status determine success;
null alone never means failed or unprepared. A first-family filename is not an
acceptable scalar substitute. Old fixed/G1 prepared receipts still require their
exact `proposal.json` path; old callers are not silently widened. No new public
proposal-path list is added without a consumer.

Professional and Assistant callers author the same v2 source. Existing Advanced
source review/save/reopen and canvas preserve the profile, all instances and actual
argument edges. This does not add visual node-creation or connection controls.
The prepared-run review reports independent instances executed
serially and lists nodes without inventing a chain. Existing New run preparation,
retained-capture launch and editor-independent operation/HTTP observation use the
same G3A native executor. This yields N independently declared proposal calls, not
N outputs from one proposer or a guarantee of scientific diversity. Aggregation,
ranking, parallel generation, training, conditional routing, evidence buffers,
human gates and graph resume remain outside this profile.
