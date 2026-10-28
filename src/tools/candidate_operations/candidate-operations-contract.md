# Detached local candidate operations contract

## Owners and public boundary

`tools.candidate_operations` exports `OperationStoreConfig`, `PrepareOperation`,
`ReusablePrepareOperation`, `CandidateOperation`, discriminated `OperationSubmission`, `OperationHandle`,
`OperationSnapshot`, `LogReadRequest`, `LogChunk`, `submit_operation`,
`read_operation`, and `read_operation_log`. All models inherit strict frozen
extra-forbid `PreviewModel`; requests are revalidated from JSON at use. Native
`CandidatePreparationRequest`/`CandidateRunRequest` and receipt schemas retain
their existing owners. Submit/read imports do not compose tasks, load generated
models, construct providers or import native node implementations.

`submit_operation(config, submission, *, launch_environment)` accepts an
explicit ephemeral string mapping. The environment is not serialized, hashed or
placed in command arguments. It returns after admission/spawn, without waiting
for native completion. Preparation never automatically launches a candidate.
The submission's UUID is the operation UUID and directory name. The request
digest hashes kind and canonical JSON native request values, plus reusable selection
only when present, excluding UUID,
environment and observation times. Same UUID/digest returns an existing handle
in any state; changed content conflicts. Existing IDs do not require fresh
credential values and never dispatch again.

The CLI has `submit --store-config FILE --request FILE`, `status --store-config
FILE --operation-id UUID`, and `log --store-config FILE --operation-id UUID
--kind native|operation --offset N --limit N`, plus `review`, `review-resume` and
`tokens` (native chains, below) and the authored-loop controls `stop-loop`,
`pause-loop`, `review-loop-resume` and `write-loop-resume`
([authored-loop CLI](#control-an-authored-loop-from-code-or-the-cli)). Outputs are schema JSON. Submit
exit zero establishes admission/existing identity, not native success. Status
exit zero includes rejected/failed/unknown observations. Invalid records/config
produce a nonzero typed error; CLI argument grammar errors use argparse's normal
nonzero usage response. Exceptions that might include caller content are not
serialized into CLI errors or wrapper completion.

Read-only package/CLI bootstrap must not import the execution registry or load
discoverable model plugins. Resume status eligibility uses the dependency-light
`core.iteration_manifest.restorable_manifest_status`; native restoration imports
the same predicate. Successful status stdout is one complete JSON document.

## Store and admission

Config supplies canonical absolute `state_root`, nonempty `preparation_roots`
and `candidate_roots`. Allowed output roots must already exist; each actual native
destination must be a strict descendant of an allowed root. State is disjoint
from actual destinations, selected inputs and active source/runtime roots.
All paths reject symlink components. This is a trusted local-user filesystem
contract, not protection against a hostile same-UID process.

State directories must be owned mode 0700, state records/logs mode 0600. Existing
incorrect permissions are refused, never silently chmodded. The root parent must
exist. Under an exclusive per-store `flock` on `admission.lock`, submission checks
prior claims and publishes:

```
state_root/
  admission.lock
  active.json
  operations/<UUID>/
    request.json
    process.json
    spawn_failure.json
    completion.json
    operation.log
```

`request.json` holds the validated submission, digest, exact store config,
source/runtime identity, selected input observations, UTC admission time and a
required fresh `native_id` UUID. This native invocation nonce is generated once
per new admission and is distinct from the caller UUID, including across stores.
Existing-ID submission reuses it; readers never generate a missing nonce.
The complete request record is encoded and checked against the 4 MiB JSON limit
before creating its operation directory. Size refusal leaves no operation claim
or active pointer and does not dispatch a child. Publication uses those exact
checked bytes, including the trailing newline.
`active.json` is a derived pointer. Every earlier operation directory must be
proven releasable before another UUID is admitted. This includes orphan directories
left by crashes before request or active-pointer publication. No partial directory
is deleted or automatically reconciled. Readers require the saved store config,
preventing a different root policy from silently changing admitted authority.

Records use existing `core.durable_io` write-once/atomic publishers through a
pinned directory descriptor. These fsync file contents; no stronger machine-power-
loss guarantee is added. Readers walk directories with `O_NOFOLLOW`, open only
fixed names, reject nonregular files and decode at most 4 MiB of JSON. No arbitrary
artifact path, tree listing or receipt-provided log path is accepted.

New candidate submissions, after matching existing-ID lookup and store availability,
use the native [shared preflight](../candidate_worker/candidate-worker-contract.md#credential-admission)
to reobserve selected files/routes and check all declared environment bindings
against the supplied mapping before record claim or spawn. The operation child
rechecks at native launch across the asynchronous dispatch gap. Existing matching
admissions return before either freshness or value checks, preserving observation
when inputs change or credentials disappear. Store lock/directories may already
exist on refusal; no new operation record, worker or native workspace is claimed.
The existing environment filter remains the forwarding authority.

## Detached process and environment

`process.spawn` executes this interpreter with fixed `-m
tools.candidate_operations.child`, no shell, stdin DEVNULL, stdout/stderr to
exclusive private `operation.log`, close_fds=True and start_new_session=True.
There are no pipes owned by the submitting process. The child writes its boot
ID/PID/start-ticks identity before entering native invocation. Runtime binding
compares interpreter path/resolved target, environment prefix, source root and
observed Git revision. These facts do not pin a clean tree or arbitrary plugin
imports against changes; selected-file identities retain their native limitations.

Before constructing the outer environment, `SandboxProfile.environment_keys`
rejects invalid/reserved names, including PYTHON* and LD_*. The host allowlist is
PATH from the interpreter directory plus `/usr/bin:/bin`, LANG=C.UTF-8,
LC_ALL=C.UTF-8, PYTHONNOUSERSITE=1, PYTHONDONTWRITEBYTECODE=1. Candidate execution
adds only explicitly declared, nonempty names from the supplied mapping.
Preparation adds none. HOME/TMPDIR/proxies/provider values are not ambiently
inherited. No process-global environment mutation or new dotenv loading occurs.
The inner sandbox separately applies its existing whitelist.

The existing native LLM bridge still calls `load_dotenv()` and the sandbox may
mount checkout dotenv files. This operation layer does not certify that native
credential discovery is absent. Explicit credential binding remains the caller's
obligation. A stronger no-dotenv policy belongs in a separate native-owner change.
Arbitrary trusted plugin output is not universally redacted; state is not a vault.

The operation process calls `prepare_candidate`, `prepare_reusable_candidate`, or `launch_candidate` directly
with keyword-only `invocation_id=record.native_id`. Native launchers validate the
UUID before effects and use it in their existing preparation UUID / run-ID hex
fields; direct callers that omit it still receive native uuid4 identities.
Native timeout, process-group supervision, artifacts, storage, accounting and
scientific semantics remain unchanged. Production code adds no signals or cleanup
ladder. Start-new-session isolates terminal process-group signals but does not
escape host/session-manager cgroup cleanup. Persistent user service/session is
required for caller-independent use; logout policy, reboot and SIGKILL survival
are not promised. Missing usage evidence is unknown, never zero billing.

## Outcome and process projection

`read_operation` revalidates saved requests and marker identity on each read.
Linux process observation compares boot ID, PID and `/proc/PID/stat` start ticks.
Readers and operation processes must share the same host PID namespace. PID
reuse and zombies establish original-process exit within that namespace. Unreadable/malformed
identity is unknown. Presence only describes the wrapper, not provider progress.
No persisted monotonic clock or elapsed-time timeout inference exists.

A submission handle may say `starting`; a later reader without trustworthy
process/outcome evidence says `unknown`. Matching live marker without completion
is `active`. A validated native final receipt yields `completed`, retaining the
native status. `finishing=True` means the wrapper is still observed alive.
Release requires a validated terminal native/pre-dispatch outcome plus positively
observed wrapper exit, or a definite failed spawn. Missing identity or uncertain
outcome keeps admission blocked even after apparent process death.

Known Popen failure publishes `spawn_failure.json`. Known wrapper failure before
entering native invocation produces `pre_dispatch_failure` completion and
`operation_failed`. Any unclassified exception after entering native invocation
produces unknown completion; an exception does not prove no provider work occurred.
Completion contains outcome/reference digest, not a duplicated native receipt.
A valid native final receipt remains authoritative even if the wrapper died before
completion publication. If completion names a receipt digest and bytes change or
vanish, the reader returns unknown integrity failure. Corrupt request records
raise; corrupt markers/native artifacts yield unknown. `child.json` is never a
terminal authority.

Preparation reads fixed `output_dir/preparation/{request.json,receipt.json}` and
checks saved request, preparation UUID against the admitted native nonce, source
observations and fixed paths.
Candidate reads fixed `workspace/candidate_run/{request.json,launch.json,receipt.json}`
and checks saved request, run ID against the admitted native nonce (hex format),
declaration/node/route identity and fixed log/ledger
paths. The native parent's receipt owns validation result semantics; this reader
does not rerun reconciliation, compose tasks, rank models or reinterpret metrics.
An identical old native request/receipt cannot satisfy a new admission: its
native nonce differs. Under cross-store races the native exclusive directory
claim still selects the winner; a loser cannot inherit the winner's receipt and
remains unknown/nonreleasable. This is ownership binding, not global admission.
No automatic retry, resume, cancellation, force-clear, attachment, queue, HTTP or
cross-store resource/spend admission is supplied.

## Operation list

`list_operations(config, limit=50) -> OperationListing` is read-only. It lists only
`{state_root}/operations/<UUID>` entries of the configured store (an absent store
lists nothing and is not created), verifies each through `load_record`, orders by
`admitted_at` (newest first, then operation UUID) and returns at most `limit`
(1..200) entries, each with its `read_operation` snapshot, `admitted_at`, and the
generated `run_name` / reviewed `project_id` when recorded. Non-canonical names and
records that fail verification are counted in `unreadable`, never listed. At most
4096 entries are examined per call (`incomplete` reports more). Callers that
expose the result must project away receipts and paths.

## Logs and validation

`read_operation_log` selects only `operation.log` or native fixed `worker.log`.
`offset` is nonnegative; `max_bytes` is 1..65536, counting source-file bytes.
`next_offset` advances by bytes read. UTF-8 decoding uses replacement and can split
characters across chunks; JSON output may exceed the source-byte bound. Missing
logs return `missing=True`. Offset beyond current size returns `truncated=True`
and restarts from zero. Same-size file replacement/rotation is not detectable
from an offset-only cursor; no rotation-detection guarantee is provided. Fixed
native logs have no rotation mechanism here.

Deterministic tests own identity/digest/confined-reader/admission failures and
unknown projection. Real process tests own duplicate racing submission, parent
exit/crash/TERM survival and wrapper TERM. Opt-in native sandbox tests own
prepare→explicit candidate→fresh CLI receipt/log reachability, using a test-only
fake provider and actual generated CPU validation. Those tests qualify plumbing,
not real LLM behavior, GPU, training or scientific outcomes. Existing paper,
workflow, prompt, task and experiment defaults are unchanged.

## Prepared request accessor

`read_prepared_candidate(config, operation_id) -> PreparedCandidate` is the public
read-only bridge for callers that need to review or launch an existing preparation.
It requires a verified `prepared` receipt through `read_operation`, loads the saved
`CandidatePreparationRequest`, and returns that request alongside the candidate
request, raw candidate-file SHA256, native preparation UUID, receipt SHA256 and
composition fingerprint. It derives fixed paths from the saved request, never
accepts a receipt-supplied arbitrary file path, and uses bounded no-follow reads.

The native preparation bundle verifier checks control/index identity, fixed file
observations, profile bytes, supported declaration, fresh selected bindings/routes
and complete candidate request equality. Original selected manifest/profile bytes
must still match their captured observations. Changed candidate advice/declaration,
foreign bundle substitution and symlink aliases refuse. The accessor neither
publishes files nor requires the candidate workspace to remain empty. It does not
claim complete arbitrary code/dependency immutability or execution readiness.
Console task authorization is a separate consumer policy, not an operation-store
rule; known-ID native monitoring does not require a console task choice.


## Reported-token accessor

`read_operation_tokens(config, operation_id) -> CandidateTokenSnapshot` is a
read-only adapter to the native [token projection](../candidate_worker/candidate-worker-contract.md#reported-token-read-projection).
For candidate/preparation kinds it revalidates configuration and calls
`read_operation` first; an integrity-failure
verdict refuses before ledger access, including marker identity, terminal receipt
digest and contradictory pre-dispatch completion. It does not replace or reinterpret
status/process semantics. Unknown process observation alone permits verified usage.

Preparation returns not-applicable without ledger access. For candidates, the
adapter derives workspace/root from saved validated submission and configured roots,
never receipt paths. Even without final receipt it compares saved request equality
and launch run ID against the admitted native nonce through the inert shared native
record verifier. Missing request/launch gives unavailable publication evidence;
changed/corrupt records refuse. The direct native reader verifies the optional final
receipt and supplies the one arithmetic/quality projection. Multiple observational
reads are not an atomic transaction. No credential read, task-choice authorization,
submission, provider call, native launch or writes occur. Existing status-reader
missing-final-receipt early return and all native statuses remain unchanged.


Native-chain kinds take a separate branch before full scientific status reads.
They validate admitted records, bounded root fences and continuation controls via
`native_resume_lineage`, then read the fixed 256-byte `.token_run_id` using the
same parser/hash owner as checkpoint observation. Every retained terminal or
admitted baseline identity anchor must match. Known retained integrity failures,
invalid checkpoints, contradictory/unlinked terminal outcomes, tampered controls,
aliases and nonregular files refuse. An expected pre-launch interval before writer
state/identity exists is unavailable; an anchored identity disappearing refuses.
Old limit-exceeded terminals may have no anchor: the current format-checked sidecar
then supplies observed identity, never terminal-verified scientific evidence.

One root `token_usage.jsonl` is read once using the existing candidate ledger
bounds, grouping and quality rules. Parent and linked-successor UUIDs see the same
current whole-chain cumulative usage; snapshots must not be added together.
`scope=chain_cumulative` and `identity_basis=observed_sidecar|retained_sidecar`
are native-only, omission-safe snapshot metadata. Candidate serialization remains
unchanged. The CLI `tokens --store-config ... --operation-id ...`, Python accessor
and authenticated HTTP endpoint call this same owner; the GUI renders that result.

Token-only reads do not reverify scientific output files and cannot detect new
scientific-file drift. The independent status reader retains that responsibility.
Usage does not authorize launch/resume, certify science, reconstruct missing reports,
prove complete billing or enforce a spend cap. Concurrent files are bounded snapshots,
not an atomic ledger/sidecar transaction. Provenance and limits appear in secondary
GUI detail text; missing identity/ledger never becomes a fabricated zero.


## Retained reusable candidate operations

`CandidateOperation.reusable_preparation: ReusablePreparedSelection | None = None`
adds explicit original-v2 provenance to the existing candidate kind. It does not
change CandidateRunRequest, worker source equality, ReviewedContext, native output
formats, prepare-kind requests or legacy edited-v1 behavior. Missing/explicit null
selection preserves the historical operation digest. Canonical content still uses
sorted JSON with separators `(",", ":")` and omits absent request.workflow_source.
Old records load without migration or rewriting. Newly serialized legacy records
may include the additive field as null; their byte encoding is not promised equal
to old serialization, but their identities remain equal. When present, both the
selection and complete native request enter the immutable submission/digest.

`build_reusable_operation(config, selection, request_id) -> CandidateOperation`
is the public read-only review/builder. All three arguments are explicit, including
the operation UUID. It validates config and confines envelope beneath preparation
roots before mutable reads, invokes the preparation-owned retained verifier, and
validates native destination/input policy before returning the typed operation.
The request describes the captured original source, not today's editor contents.
The builder does not check credential values, claim storage or launch. It is not
a required trusted shortcut: manually constructed submissions must pass the same
fresh provenance check in submit. Python and existing CLI `submit --request` use
`submit_operation`; there is no new execution kind or submit engine.

`reusable.validate_selection_root` performs only static canonical containment and
state-overlap checks. It requires no surviving envelope files and is safe in
`validate_submission` and `load_record`. Keep mutable receipt/binding/source/request
reads out of those paths. After `existing` finds no record, under the existing
store lock and before credentials/claim/spawn, `verify_reusable_operation` calls
`candidate_prepare.verify_reusable_preparation` and requires exact typed request
equality. Native fresh_preview and credential admission still follow. Errors use
bounded credential-safe `OperationFailure(code="reusable_preparation")`. Rejected
admission may create store lock/directories but no operation claim or workspace.

The detached child repeats the same content verification with a separate fresh
pass after runtime binding and before `entered = True`/`launch_candidate`. A proven
failure publishes `pre_dispatch_failure` with reason `reusable_preparation_failed`,
never ambiguous native status or worker effects. Runtime failures retain
`runtime_binding_failed`; uncertainty after native entry retains
`native_outcome_unresolved`. Dispatch uses `record.submission.request`, never a
replacement loaded from the envelope. Native launch rechecks its own source and
observed inputs. The store lock serializes operation claims, not external writers;
these checks do not freeze the filesystem against a hostile same-UID actor.

Identical operation UUID/digest returns the saved handle before provenance,
preview or credential checks, including after receipt or whole-envelope deletion.
Different selection/request with the same UUID conflicts. Never reconstruct the
request or select current receipt bytes to recover an ambiguous response: retry
the saved submission. A new UUID is a new admission and cannot resume/reuse a
claimed native workspace. Native terminal evidence can become unknown if removed;
this does not authorize re-execution. Envelope UUID, offline preparation UUID,
operation UUID and native invocation UUID are distinct linked identities.

### Shared Python and CLI recipe

After successful preparation and explicit selection of a trusted local envelope,
construct and save the reviewable submission outside that envelope. This example
uses the existing store config; for reusable runs both output-root lists normally
include `/runs/my-task`, since inputs and workspace are sibling children of each
UUID envelope. The state directory must remain separate. Select required provider
environment names during preparation and bind their values only at launch.

```python
from pathlib import Path
from uuid import uuid4

from tools.candidate_prepare import select_reusable_preparation
from tools.candidate_operations import OperationStoreConfig, build_reusable_operation

config = OperationStoreConfig.model_validate_json(Path("store.json").read_bytes())
selection = select_reusable_preparation("/runs/my-task/PREPARED_ENVELOPE_UUID")
submission = build_reusable_operation(config, selection, uuid4())
# Retain this file for exact-ID recovery. Do not regenerate it when retrying.
Path("reusable-submission.json").write_text(submission.model_dump_json(indent=2))
```

Substitute the actual reported envelope UUID. This helper pins current published
receipt bytes correctly; a later scan is an explicit new selection, not proof of
an earlier publication event. An integration that already retained the selection
should pass that object directly instead of selecting again. No digest transcription
or hashing of CLI stdout is required. Review task/project/workspace, node IDs,
selected routes, limits and advice from the returned typed request before launch.

```sh
.venv/bin/python -m tools.candidate_operations submit \
  --store-config store.json --request reusable-submission.json
```

The equivalent Python launch is
`submit_operation(config, submission, launch_environment=explicit_environment)`.
Both return admission/existing identity; use the existing status/log/token readers
for native terminal results. `prepared` precedes admission; native accepted/rejected
follows proposal/implementation/validation. None means training or scientific
quality qualification. Professional and Assistant routes differ in how users
choose inputs, not in these preparation/execution owners. Reusable GUI review,
automatic preparation, source editing integration, run discovery, resume and
whole-chain launching remain separate work.

Validation: fixed legacy digest/record witnesses, production admission/dispatch
reachability, exact-ID recovery after removal, current source edit preservation,
CLI parity and actual two-envelope offline preparation→detached operations→native
worker integration with test-only provider responses and CPU checks. This is no
real API/GPU or paper-performance qualification.


## Detached reusable preparation

`ReusablePrepareOperation(kind="prepare_reusable", request_id, request)` carries
`ReusableCandidatePreparationRequest` through the same store lock, process,
completion and release rules. No new queue or job registry exists. The operation
UUID, request.run_id (envelope UUID), and record.native_id (preparation invocation
UUID) remain distinct. Static checks confine the full envelope under preparation
roots and its workspace under candidate roots, protect selected inputs/runtime
paths, and isolate state. The project root is a reference base, not a blanket
output exclusion: a project may contain its configured runs directory.

Fresh submission performs native inert preflight under the admission lock after
known-ID and availability checks. The operation record retains observations in
exact order: authored `workflow.source`, `task.manifest`, `llm_config`.
`ReusablePreparationExpectation(request_digest, observations)` optionally binds
reviewed intent. `observations` is the preparation-owned
`ReusablePreparationObservations`; the digest comes from
`operation_request_digest(submission)`. Comparison against actual admission happens
before claim. Mismatches raise `OperationFailure(code="conflict")`; unavailable or
invalid fresh inputs raise `reusable_preflight`. No credentials are read or passed
to preparation. Store lock/directories may exist after refusal, but no operation
claim or native envelope is created.

```python
from pathlib import Path
from uuid import uuid4
from tools.candidate_prepare import (
    ReusableCandidatePreparationRequest, ReusablePreparationObservations,
    preflight_reusable_candidate,
)
from tools.candidate_operations import (
    ReusablePrepareOperation, ReusablePreparationExpectation,
    operation_request_digest, submit_operation, recover_reusable_preparation,
)

request = ReusableCandidatePreparationRequest.model_validate_json(
    Path("reusable-request.json").read_bytes()
)
submission = ReusablePrepareOperation(request_id=uuid4(), request=request)
plan = preflight_reusable_candidate(request)
expected = ReusablePreparationExpectation(
    request_digest=operation_request_digest(submission),
    observations=ReusablePreparationObservations.from_binding(plan.binding),
)
# Review and retain these typed values outside the envelope before submitting.
handle = submit_operation(
    config, submission, launch_environment={}, expected_reusable_inputs=expected
)
# After a lost response, use the retained UUID/expectation, not fresh preflight.
recovered = recover_reusable_preparation(config, submission.request_id, expected)
```

`config` is the previously loaded `OperationStoreConfig`. Recovery returns the
original typed submission, or None only for an absent operation directory.
Existing-ID submit and recovery compare the durable request digest/kind and
retained observations before mutable source/configuration or credential reads.
Both perform current static store/config checks; neither silently changes admitted
policy. The expectation is a call argument, not a new persisted review record.
The request digest describes request parameters, not mutable manifest/config bytes.
The existing JSON CLI accepts the same new submission kind without an expectation;
it still captures and retains native admission observations.

The child passes those exact observations and its native UUID to B1. B1 compares
its actual capture before envelope claim; a second capture cannot establish a new
baseline. Native preclaim refusal after dispatch is conservatively unknown.
The child does not introduce a second preparation implementation.

Status delegates to `candidate_prepare.reusable_terminal.read_reusable_terminal`.
It reads only fixed retained envelope paths; no authored-source recapture, native
task import, credentials, fresh source verification or full selection occurs.
It binds top receipt/run/envelope/nonce, source snapshot, reconstructed native
request, admission observations, binding hash, and any control/inner receipt.
Success requires complete consistent control/inner evidence and prepared artifact
references. A failed top receipt without an inner receipt is valid only with
sufficient binding/snapshot evidence; any existing control is still checked.
Earliest incomplete publication stays unknown. A referenced missing inner receipt
is integrity failure. Missing top plus successful inner never establishes completion.
`Completion.receipt_digest` pins the exact top receipt bytes and is checked on every
subsequent read. Native failed/timed_out/interrupted statuses remain completed
native outcomes, not candidate acceptance. Release still requires exited-process
evidence.

Native logs use `envelope/inputs/preparation/worker.log`; an absent log is normal.
Tokens are not applicable for both preparation variants, after integrity checks.
`read_prepared_candidate` remains legacy-only; reusable completion uses explicit
`select_reusable_preparation` / B3 selection and full verification before launch.
Old prepare/candidate serialized records and request digests are unchanged by this
variant. New reusable top receipts carry the invocation UUID; legacy receipts omit
only that new field when absent, preserving all historical null fields.

## Captured native chain operation

`NativeChainOperation(kind="native_chain")` carries an A-owned capture path and
SHA-256, an explicitly created empty envelope, read-only roots, network/devices,
environment names, timeout and read bounds. Candidate roots also allowlist chain
envelopes. The capture's workspace must be exactly `envelope/workspace`, absent
until native shell admission; neither operation review nor claim creates it.
Capture/pin bytes use A's reader and its exact captured limit, at most 16 MiB.
Operation JSON remains limited to 4 MiB. Observation controls explicitly bound
indices to 1000 and evidence to 1 MiB; they introduce no scientific defaults.

`review --store-config FILE --request FILE` returns a typed admission without
claiming or launching. Submit repeats review after existing-ID recovery. Review
uses the exact interpreter and a subprocess cwd to invoke A's real `check admit`;
server cwd is unchanged. Full resolved native routes use existing credential
policy, including interpretation and tuning. Only names/requirements persist.
Captured settings are not rewritten into a candidate loop or another scheduler.
The native shell remains the sole scheduler. Capture source/config/package edits
may refuse admission or a subsequent native iteration; capture is not portable
snapshot replay.

Each stored chain admission retains workspace, final index, run name, recipe,
input digests and exact checkout/Git metadata directories. The detached child
compares a fresh admission, exclusively creates `.native-chain-operation` in the
empty envelope, verifies its identity and dispatches the original captured shell
with exact capture controls. Claim collisions refuse before dispatch; partial
claims are never reused or removed. Original files and linked-worktree Git
metadata are mounted read-only at original paths. The envelope is the only
writable project mount; the host operation store is never mounted. Git alternates
and GIT_* environment injection are unsupported. Missing sandbox support has no
unsandboxed fallback.

`run_observed` adds supervision evidence without changing legacy `run`: actual
shell result, shared-owner group cleanup and direct-child reaping. Only a proven
pre-spawn failure is safe pre-dispatch failure; post-spawn exceptions are unknown.
A sampled present/unknown group remains unresolved even if it exits later.
The private host `native-chain-terminal.json` is bound by Completion. It is not a
scientific receipt: `receipt_available` stays false. Terminal identity, proven
cleanup and wrapper exit govern release, separately from scientific evidence.
Missing/modified host terminal or contradictory pre-dispatch completion blocks
release. Failed/timeout shell outcomes remain visible even when lifecycle finishes.
Both log kinds read the inherited private operation log for this kind. Reported tokens use the separate bounded accessor described above. Same UUID recovery reads only
stored identity and evidence, even after original capture deletion and key loss.
This fresh-launch boundary adds no cancellation or scientific qualification.
Reported-token monitoring is the separate read-only accessor above. Explicit continuation is described separately below.

The chain snapshot's `native_chain.evidence` reports bounded current checkpoint
observations, distinct from immutable `native_chain.terminal.evidence`. Active
observations cannot complete lifecycle. Final reads compare observation under the
terminal's stored `observation_policy` with terminal evidence;
changed/disappeared evidence reports integrity_failure,
while trustworthy cleanup still permits lifecycle release. Manifest and artifact
verification flags remain distinct: legacy unverified artifacts never become
verified. `no_records` remains its own native status. Scores and formal-evidence
counts come only from validated HyperparamTuningOutput and its existing role
owner. No metric arithmetic or interpretation of human detail strings is added.

`NativeChainTerminal.observation_policy` accepts only strict integers 1, 2 and 3.
Missing fields in historical terminals mean policy 1; new terminal writes
record policy 2 when the root request omits `max_evidence_read_bytes`,
and policy 3 when it supplies that field. Policy 1 retains the original control names
and discovery cap. Policy 2 additionally recognizes `token_usage.jsonl` without
reading its rows, increasing the finite control-name cap by one. Policy 3
keeps policy 2 discovery and verification, but separates aggregate input reads
from the compact projection limit. The positive `max_evidence_read_bytes` is
charged for manifest, output and token-sidecar bytes; `input_max_bytes` still
bounds each artifact (the sidecar additionally retains its 256-byte bound).
`max_observation_bytes` independently bounds the emitted compact evidence.
Policies 1/2 reject an explicit read budget; policy 3 requires one. Full evidence
equality is checked under the stored policy before a legacy terminal's live
evidence is projected under the current policy. Historical terminal evidence,
raw bytes and Completion digest remain unchanged. Unknown policies fail terminal
validation. This is reader compatibility, independent of scientific task policy.
Legacy reads can perform two bounded observations; filesystem mutation between
observations is not atomic. A historical limit result remains a limit result
in terminal evidence even when the current policy can return complete live evidence.
Such a terminal has no retained checkpoint baseline: a complete current projection
does not establish that checkpoint bytes stayed unchanged since completion.

Directory discovery, per-file bytes, aggregate retained bytes and emitted evidence
are bounded. Limits produce `limit_exceeded` with no truncated checkpoint list.
Artifact paths must remain canonical within the scheduled iteration; aliases and
escapes refuse. Each observation reads each bounded artifact once; the shared manifest verifier
hashes supplied bytes and HyperparamTuningOutput parses those same bytes. Existing
verifier callers retain their file behavior. The legacy inspector now delegates
its original unbounded chain projection to `tools.native_chain.inspection`, with
unchanged human display and next-iteration semantics. The new strict observation
path does not silently impose new bounds on the legacy inspector.

Only the native `.token_run_id` sidecar is read (at most 256 bytes), validated as
`run_name-YYYYMMDDTHHMMSS-pid`, and retained with its byte digest. It is distinct
from operation/native invocation UUIDs. No invented token-to-checkpoint binding
is supplied. Missing sidecar remains unavailable. The separate token accessor
reads bounded ledger rows without reopening scientific outputs.

Required `NativeChainOperationRequest` JSON fields are `capture_path`,
`capture_sha256`, `envelope`, `read_only`, `network`, `devices`,
`environment_names`, `timeout_seconds`, `input_max_bytes`,
`max_iterations_observed`, and `max_observation_bytes`. Those fields have no implicit
request defaults. Optional `max_evidence_read_bytes` is a strict positive integer;
when absent it is omitted from serialization, preserving old request identities.
It has no additional fixed ceiling: the operator chooses a finite aggregate
allowance. Parsed JSON and Pydantic objects can consume substantially more memory
than the encoded input, so this is not a process-memory guarantee. Existing
requests and terminals are never upgraded to policy 3. `input_max_bytes` equals A's `launch_binding.file_max_bytes`
and is strict positive <=16 MiB; `max_iterations_observed` is strict positive
<=1000 and must cover the captured final iteration; `max_observation_bytes` is
strict positive <=1 MiB. Enumeration permits at most twice the captured final
index (iteration directory plus its native hardware file) plus the fixed
recognized native control-name count. Unrecognized entries consume that same
budget and remain explicit anomalies. This is distinct from reading those
control files, which the checkpoint observer does not do.

## Construct a native chain operation

Save this complete recipe as an external `build_chain_operation.py`; replace
capture/input/data paths and choose sandbox resources before invocation. It
computes the capture identity automatically and preserves A's exact byte limit.
Run once and retain the resulting `chain-operation.json` for UUID recovery.

```python
import hashlib
from pathlib import Path
from uuid import uuid4
from tools.candidate_operations import NativeChainOperation, NativeChainOperationRequest
from tools.native_chain.models import NativeChainCapture

capture_path = Path("/absolute/external/review/capture.json")
capture_bytes = capture_path.read_bytes()
capture = NativeChainCapture.model_validate_json(capture_bytes)
assert capture.environment.launch_binding is not None
submission = NativeChainOperation(
    request_id=uuid4(),  # Generate once; reuse the saved JSON for every retry.
    request=NativeChainOperationRequest(
        capture_path=str(capture_path),
        capture_sha256=hashlib.sha256(capture_bytes).hexdigest(),
        envelope=str(capture.declaration.run.workspace.parent),
        read_only=("/absolute/external/task-inputs", "/absolute/external/data"),
        network=False,
        devices=(),
        environment_names=(),  # Pseudo routes need no provider keys.
        timeout_seconds=300,
        input_max_bytes=capture.environment.launch_binding.file_max_bytes,
        max_iterations_observed=capture.declaration.run.final_iteration,
        max_observation_bytes=1048576,
    ),
)
Path("chain-operation.json").write_text(submission.model_dump_json(indent=2))
```

The empty envelope must have been created before capture review. Its native
workspace remains absent until native shell launch. The explicit 300-second
timeout and 1 MiB observation budget are example caller choices. Configure
provider environment names for enabled real routes. Explicit GPU device paths
and read-only `/sys` may be needed to reproduce captured hardware facts; select
the actual host paths, never bypass installation/hardware binding. No GUI or automatic capture builder is implied.

## Captured native continuation

`review_native_chain_resume(config, predecessor_operation_id)` and CLI
`review-resume --store-config PATH --operation-id UUID` inspect the unique tail
of a registered detached native run. `NativeChainResumeOperation` has kind
`native_chain_resume`, a new `request_id`, and a `NativeChainResumeRequest` containing
only `predecessor_operation_id` and `expected_review_digest`. Scientific controls,
capture, sandbox mounts, provider-name policy, timeout and observation bounds are
inherited from the verified root request. No new launcher, scheduler or scientific
configuration is reconstructed. The native shell remains the iteration owner.

Admission requires an exited wrapper, a digest-bound host terminal with a reaped
direct child and cleanup final `absent`, root-request policy-2 or policy-3 evidence matching that
terminal, a consistent registered writer snapshot and a free kernel lock. The
prefix must be contiguous, verified and restorable under native status semantics,
with at least one completed iteration. Selection uses the existing next-index
owner; the selected and all later iteration directories must be absent. A completed
target reports `not_needed`. Existing failed/no_records/partial selected slots,
first-iteration recovery, dangling history, unknown anomalies, STOP,
chain_stopped.json and .chain_halted refuse. Ordinary fresh and legacy behavior
is unchanged. Native restoration can still refuse incompatible plugin state;
read-only admission does not run that mutating restoration.

Source/install/input verification uses the original capture in its exact working
directory. The initial capture and run must be created on this continuation-capable
source; an older capture does not become resumable by upgrading its checkout.
Foreground-only/legacy/Slurm runs are unsupported by this detached proof boundary.
No force-fresh, automatic reclaim, stop clearing, parameter changes or new target
is supplied. Deliberately escaped same-user daemon writers remain outside the
cooperative supervision guarantee.

`NativeResumeAdmission` persists root/predecessor/baseline operation identities,
raw predecessor Completion and baseline terminal digests, original request and
admission, typed writer snapshot, bounded scientific evidence, start index and
store identity. Its review digest excludes timestamps and FD numbers. Repeated
read-only reviews of unchanged state are stable. New-kind syntax validation is
inert; same-ID lookup precedes fresh sources/credentials and never respawns,
including after interruption, missing source or lost response.

Host admission retains existing store locking and typed OperationRecord publication.
The wrapper rechecks admission under the existing writer lock, then publishes
`successor.<predecessor-UUID>.json` write-once inside the existing writable writer
sidecar. The original envelope fence is never replaced. This shared physical
reservation excludes a competing store as well as another UUID. Host and child do
not transfer a descriptor across bubblewrap. The child verifies the same reservation,
source, baseline and lock snapshot, publishes a permanent adoption marker, removes
only exact prior owner metadata, and transfers the same held FD into the existing
shell runner. It does not mount the host operation store. Core owns exclusion and
single-use adoption; operations own cleanup/lineage admission. See the
[writer contract](../../core/native_writer/native-writer-contract.md#explicit-successor-ownership-primitives).

Any uncertain reservation publication, adoption transition or missing host receipt
blocks further effects. An existing UUID is status retrieval only. An actual child
always produces the existing observed terminal when supervision completes, including
pre-scientific refusal. Only an `ObservedSpawnFailure` after confirmed reservation
can produce `Completion(outcome="pre_dispatch_failure",
reason="native_resume_spawn_failed")`: before publishing this narrow no-child proof,
the wrapper reacquires the writer lock and checks the exact reservation, absent
adoption, unchanged owner and unchanged scientific baseline. No cleanup terminal is
fabricated. After that wrapper exits, a new explicit UUID may follow the no-effect
leaf; generic pre-dispatch errors do not grant this permission. The failed leaf and
its reservation remain immutable.

Reads follow deterministic successor filenames from the root fence. They validate
operation/config identities, Completion/terminal hashes, reservations and adoption
records without scanning other stores. Limits are 64 successor links, 4096 bytes per
writer record and 16 MiB aggregate host record bytes (charged before reads, including
a conservative allowance for the initially loaded record). Existing 4 MiB record,
16 MiB per-file capture/input and 1 MiB compact projection limits remain separate.
An explicit aggregate evidence-read allowance is inherited unchanged in the
reservation and checked by native adoption; it does not change host-record limits.
Overflow, cycles, missing or contradictory linked records refuse; no truncation is
presented as complete history. Root requests without successors retain the old
terminal-policy comparison, including legacy policy-1 compatibility.

`native_chain.terminal` remains the selected operation's immutable snapshot;
`native_chain.evidence` is current workspace evidence. Optional `continuation`
contains root/head operation IDs, head state and reserved/adopted/no-child/terminal
lifecycle. Selected `OperationSnapshot.state` never becomes the successor's outcome.
Without adoption, a reservation authorizes no scientific change. With adoption,
only the previously absent suffix may change; every protected prefix and token
sidecar identity must still match. A later terminal cannot launder altered prior
checkpoints. At a terminal tail current evidence must match that terminal completely.
Missing/unknown cleanup never grants another continuation. Token ledger append is
allowed through its native producer; this observer does not read or promise integrity
of aggregate usage rows. Native token identity is distinct from both operation UUIDs.

GUI continuation is not supplied. Professional and Assistant code/CLI consumers use
this same request/read path. Existing native log behavior remains the selected
operation's wrapper log. Both native kinds share cumulative token monitoring
through the separate reported-token accessor.

## Construct a native continuation

Run once from the original checkout after inspecting the completed operation. Save
the request outside the scientific envelope and reuse it unchanged for response
recovery. This code reviews eligibility and constructs a request; it does not launch.

```python
from pathlib import Path
from uuid import UUID, uuid4
from tools.candidate_operations import (
    NativeChainResumeOperation, NativeChainResumeRequest, OperationStoreConfig,
    review_native_chain_resume,
)

config = OperationStoreConfig.model_validate_json(Path("store.json").read_bytes())
predecessor = UUID("PREVIOUS_OPERATION_UUID")
review = review_native_chain_resume(config, predecessor)
if review.eligibility != "ready":
    raise RuntimeError("Original target already reached")
request = NativeChainResumeOperation(
    request_id=uuid4(),
    request=NativeChainResumeRequest(
        predecessor_operation_id=predecessor,
        expected_review_digest=review.review_digest,
    ),
)
Path("resume-operation.json").write_text(request.model_dump_json(indent=2))
```

Bind the original provider environment names and submit with the ordinary CLI or
`submit_operation`. New credentials are checked only for new execution; status and
identical same-ID recovery do not read their values. Source, writer or checkpoint
changes after review refuse the new operation rather than changing its meaning.

### Authored finite-loop Stop

`request_loop_stop(config, operation_id)` is an operation-bound graceful request
for the candidate worker's declared finite loop. It reuses the store lock,
configured-root admission, saved request/run identity checks and current process
observation. It writes only the already-claimed native control marker, never
creates a queued candidate workspace, and never sends a signal. Identical marker
requests are idempotent. Read the ordinary operation snapshot for the eventual
native outcome; acknowledgement alone does not mean stopped. The worker's
[candidate contract](../candidate_worker/candidate-worker-contract.md#declared-finite-research-body)
owns completed-body observation, the `stopped` receipt and evidence replay.


### Authored completed-boundary Pause/Resume

`request_loop_pause(config, operation_id)` shares the Stop identity, configured-root
and live-process admission. It writes the selected segment's immutable Pause marker;
acknowledgement means requested, not paused. Before the root worker has claimed
its workspace, Pause (like Stop) and the Resume review refuse with `not_ready`. A
successor never inherits its predecessor's marker; Pause it by its own operation ID. Stop applies to the whole root run even
when requested through a resumed segment. Neither request sends a process signal.

`review_loop_resume(config, predecessor_operation_id)` returns the selected verified
`OperationSnapshot` only when its native receipt is paused, its Completion binds
that receipt, the wrapper is observably exited, and recorded native supervision
proves clean process-group shutdown. Missing/unknown lifecycle evidence, a reached
finite limit, a met stop condition (a `completed` receipt with `loop_trace.stop_reason`),
a root Stop or an existing successor refuses with `loop_resume`. A
partial next body already invalidates the paused readback, so the review finds no
verified paused segment. The review constructs no process and reads no credentials.

Submit `CandidateLoopResumeOperation(request_id=..., request=CandidateLoopResumeRequest(
predecessor_operation_id=..., expected_receipt_digest=review.receipt_digest))` through
`submit_operation`. The ordinary store lock serializes review, immutable operation
claim and predecessor successor reservation before dispatch. Reusing the same request
ID returns the existing operation before mutable checks. Before claiming, admission
re-verifies the root's captured input files and source snapshot (the same identity
check the continuation child repeats), so an edited input refuses with `loop_resume`
without consuming the reservation.

The single-successor reservation is the predecessor segment's immutable write-once
`successor.json`, published after the continuation's own `continuation.json`. A
competing ID cannot obtain a second successor. A crash after the continuation operation
record is claimed but before `successor.json` exists leaves an unresolved, never
dispatched orphan record (possibly with an unreferenced
`continuations/<id>/continuation.json`) and does not consume the reservation. The
orphan is not releasable, so the store stays `busy` and admits no new ID until it is
resolved. A crash or spawn failure after `successor.json` exists remains fail-closed
and never re-dispatches: this scope does not recycle reservations or automatically
retry uncertain dispatch.
New execution rechecks the original runtime and provider environment names (missing
names refuse with `credentials`); values are never stored. Native worker admission owns task plugins and scientific validation.

`read_operation` retains the selected segment's receipt and exposes an optional
`successor_operation_id`, rather than replacing history with a descendant's status.
Its ordinary completed/finishing process projection remains unchanged. Native log
reads select that segment's worker log. Reported-token reads use the original run
identity and ledger, so they describe the run total, not a fabricated per-segment
subtotal. Root source/captures and earlier receipts remain immutable.

`loop_root_operation(config, operation_id)` is the read-only root resolver for
callers (the console's loop bound, Resume credential names and per-body results).
It returns the root `CandidateOperation` of an authored-loop operation or segment,
or `None` for any other operation, by following immutable
`predecessor_operation_id` records only; a resume segment whose root is not an
authored loop raises `kind` (reachable only with tampered records). It reads no
native file, process or credential, and an unknown operation raises `FileNotFoundError`.
Predecessor-link cycles raise `integrity`.

`operation_admitted(config, operation_id) -> bool` is the only absence proof. It
opens the private state root (missing or non-private root raises, never `False`)
and returns `False` only when `operations/` or the `operations/<UUID>` entry is
absent; any present entry, even one still mid-admission, returns `True`. Callers
that need a typed refusal raise `UnknownOperation` (code `unknown_operation`).

### Control an authored loop from code or the CLI

CLI `review-resume` and the native continuation above serve captured native
chains only and refuse an authored loop; use these routes instead. Each CLI
subcommand parses its arguments and calls the Python function on the same line, so
admission, refusals and idempotency are the owner's:

| CLI (`--store-config FILE --operation-id UUID`) | Python | Output |
| --- | --- | --- |
| `stop-loop` | `request_loop_stop(config, operation_id)` | `LoopStop` marker (requested) |
| `pause-loop` | `request_loop_pause(config, operation_id)` | `LoopPause` marker (requested) |
| `review-loop-resume` | `review_loop_resume(config, operation_id)` | paused `OperationSnapshot` with `receipt_digest` |
| `write-loop-resume ... --output FILE` | review, then construct the request below | the saved `CandidateLoopResumeOperation` |

`write-loop-resume` reviews the paused segment and creates `FILE` once; an existing
file refuses with `output_exists` and is left unchanged, so a retry after a lost
response submits the same request ID. It does not launch. Launch is the ordinary
`submit --store-config FILE --request FILE`, which reads the launching process
environment; admission requires the root request's provider environment names.
Failures use the ordinary one-line JSON error and exit status 2.

```python
from pathlib import Path
from uuid import UUID, uuid4
from core.durable_io import publish_bytes_write_once
from tools.candidate_operations import (
    CandidateLoopResumeOperation, CandidateLoopResumeRequest, OperationStoreConfig,
    read_operation, request_loop_pause, request_loop_stop, review_loop_resume,
    submit_operation,
)

config = OperationStoreConfig.model_validate_json(Path("store.json").read_bytes())
segment = UUID("RUNNING_SEGMENT_UUID")
request_loop_pause(config, segment)  # or request_loop_stop: run-wide and terminal
# Poll read_operation(config, segment) until the receipt is paused and the wrapper exited.
review = review_loop_resume(config, segment)
assert review.receipt_digest is not None
resume = CandidateLoopResumeOperation(
    request_id=uuid4(),
    request=CandidateLoopResumeRequest(
        predecessor_operation_id=segment,
        expected_receipt_digest=review.receipt_digest,
    ),
)
# Create the file once, as the CLI does. FileExistsError means a saved request
# already exists: submit that file unchanged, never overwrite it.
publish_bytes_write_once(
    str(Path("loop-resume.json").absolute()), resume.model_dump_json().encode()
)
# environment_with_root_provider_names: placeholder for the launching process's
# environment mapping (e.g. dict(os.environ)); it must contain the provider
# environment names the root request declared.
submit_operation(config, resume, launch_environment=environment_with_root_provider_names)
```

Acknowledgement is not the outcome: read `read_operation` until the receipt says
`stopped`, `paused` or `completed`. The resumed segment is a new operation UUID on
the same native run; pause it by its own UUID. Witnesses for the CLI routing:
`tests/unit/tools/candidate_operations/test_cli_loop_controls.py`.

These authored controls do not use fixed native-chain capture recipes or shell
resume flags. No arbitrary iteration cap, new history policy or mid-body recovery
is introduced; the console's Pause/Resume controls only call these functions.
Offline tests separate operation and worker processes, exercise real native
body/evidence construction with provider/training doubles, and cover required
lifecycle/admission refusals; they are not paper qualification.
