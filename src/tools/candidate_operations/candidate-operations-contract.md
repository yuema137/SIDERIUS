# Detached local candidate operations contract

## Owners and public boundary

`tools.candidate_operations` exports `OperationStoreConfig`, `PrepareOperation`,
`CandidateOperation`, discriminated `OperationSubmission`, `OperationHandle`,
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
digest hashes kind and canonical JSON native request values, excluding UUID,
environment and observation times. Same UUID/digest returns an existing handle
in any state; changed content conflicts. Existing IDs do not require fresh
credential values and never dispatch again.

The CLI has `submit --store-config FILE --request FILE`, `status --store-config
FILE --operation-id UUID`, and `log --store-config FILE --operation-id UUID
--kind native|operation --offset N --limit N`. Outputs are schema JSON. Submit
exit zero establishes admission/existing identity, not native success. Status
exit zero includes rejected/failed/unknown observations. Invalid records/config
produce a nonzero typed error; CLI argument grammar errors use argparse's normal
nonzero usage response. Exceptions that might include caller content are not
serialized into CLI errors or wrapper completion.

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

The operation process calls `prepare_candidate` or `launch_candidate` directly
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
It revalidates configuration and calls `read_operation` first; an integrity-failure
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
