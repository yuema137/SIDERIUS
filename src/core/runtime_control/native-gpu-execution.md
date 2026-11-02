# Optional protected native GPU execution

Scope: explicit `GpuExecutionPolicy` selected through the standard single-iteration
workflow or typed tuner input. Native composed training/evaluation scopes only.
The policy does not turn ordinary observation into a mandatory global gate.

## Owners and transport

- `gpu_execution_policy.py` validates the frozen policy; `launch_identity.py` loads
  its CLI JSON once. `WorkflowLaunchConfig`, the existing tuner protocol and
  `HyperparamTuningInput` carry the same object. Run invariants lock its values.
- `nodes/ml_hyperparameter_tune_agent/gpu_execution.py` owns attempt preparation.
  It reuses task probe projection, existing inference batch selection, measurement
  bindings, the checkpoint identity runner, phase runners and complete assessors.
- `gpu_execution_evidence.py` carries the complete typed phase input, returned run,
  assessment and attempt nonce. Only complete admitted evidence yields a requirement
  with ended-worker ownership. Incomplete RSS or group cleanup refuses authority.
- `native_gpu_execution.py` checks current configs, loss contract, task/scopes,
  sampling, source identity, device and batch at native launch. It passes one timed
  admission sample and the decision's resolved ceiling to the protected observer.
- `observed_subprocess.py` remains the sole process signal/cleanup owner. The same
  `GpuPhaseObserver` is both observer and control; selected plain calls own a new
  session even with the scientific watchdog disabled.

No scientific values or hardware names are introduced. The existing
`GpuMeasurementSpec` owns sample/workload defaults; the resolved spec is retained
in each measurement record. Existing GPU ceiling resolution owns capacity/quota
arithmetic. Runtime protection compares current total device occupancy with that
same ceiling; it does not add the measured worker a second time.

## Budget and startup boundary

`MeasurementAllowance` starts one segment before source/request/checkpoint
preparation and charges it once after cleanup. Training and inference measurement
share a total, including actual cleanup overrun. Native training preparation is
charged through the final pre-spawn check, then scientific work is excluded.
Native inference preparation includes checkpoint loading until parent authorization.
A 60-second total with 20 seconds spent measuring leaves 40 seconds even after
1000 seconds of actual training. Exhaustion cannot acquire another full allowance.

The optional inference request contains the complete bound spec, attempt nonce,
absolute monotonic preparation deadline, ACK timeout, polling interval and receipt
byte limit. The existing bound loader verifies the sentinel and checkpoint on a
single descriptor. Child `loaded.json` → parent `authorized.json` → child
`consumed.json` precedes inference forward/data iteration. Parent validation uses
that child's explicit plugin environment, not the parent's unrelated ambient roots.
The supervisor requires complete startup RSS within the selected bound before
publishing authorization. The scientific watchdog begins at publication. Missing
or late consumption is separately refused, including with the watchdog disabled.

Returned receipts are opened with the shared nonblocking/no-follow regular-file
helper, bounded on the same descriptor and parsed as typed messages. Duplicate JSON
keys, wrong nonce/PID/checkpoint/binding and special files refuse. These checks detect
ordinary mutation under trusted same-user execution; they are not an immutable
snapshot or containment boundary against a malicious same-user writer. Parent
filesystem work cannot be hard-interrupted by the cooperative deadline.

## Failure and persistence

Each attempt has a unique token; phase measurement and terminal files use durable
write-once publication below the executor's existing run directory:

```
gpu_execution/<token>/
  training/measurement.json
  inference/checkpoint.json
  inference/measurement.json
  startup/{request,loaded,authorized,consumed}.json
  training-admission-<receipt-count>.json  # transient sampling only
  inference-admission-<receipt-count>.json # transient sampling only
  training-terminal.json
  inference-terminal.json
```

`GpuExecutionReceipt` contains policy, charged intervals, measurement, admission,
protection and process lifecycle; inference adds the startup receipt. Raw child
stdout/stderr and watchdog evidence remain available on failure. Existing successful
or failed experiment emission includes the accumulated typed receipts.
Execution-evidence failures first persist terminal evidence, then reach the tuner's existing
`RuntimeEvidenceChannelError` stop path. Persistent admission refusal and exhausted
sampling instead reach `infrastructure_abort` through the shared phase owner.
If persistence itself fails, the returned in-memory receipt reports infrastructure failure and cannot claim a successful
write. An existing write-once receipt is never replaced. Cleanup targets only this
attempt's existing checkpoint/sentinel/result/deliverable paths.

All pre-launch admission refusals return `skipped_resource_admission` to
`phase_admission.run_admitted_skill`, the single tuner recovery/record owner,
which consumes core `AdmissionDecision.refusal_kind` classification.
The evaluator receives `require_evidence=True`: protected trial execution requires
usable accounting and ownership just as formal execution does, without relabelling
its mode. Typed query failures and exceptions from `sample()` receive the existing
`sampler_error` classification. Persistent evidence gaps stop immediately; capacity
refusals retain the existing resource disposition. No refused phase launches a child.

Each transient refusal writes `<phase>-admission-<receipt-count>.json`, preserving
its charged segment and measurement before retry. It does not occupy the write-once
terminal path. On exhaustion the tuner calls `finalize_admission_refusal` to publish
the last receipt as `<phase>-terminal.json`; on recovery the normal phase result
owns terminal publication. Direct executor callers receive the sampling receipt
and must finalize it if they do not retry. Storage failure overrides recovery with
`aborted_infrastructure`. Other refusal and execution outcomes publish terminal
receipts immediately. No existing receipt is overwritten.

Re-entry clears only current admission/observer/startup/lifecycle/child-error state.
It retains the attempt token, measured phase object, bound checkpoint and cumulative
`MeasurementAllowance`. Every call charges its actual preparation duration.
`pause_admission_retry` charges backoff as a separate preparation segment, capped
by the remaining allowance, so waiting cannot renew the absolute deadline.
Exhausted allowance refuses before
calling the executor body. Source/checkpoint/input validation runs again on every
call, and observer creation happens only after fresh admission. Inference retry
never re-enters training. Admission recovery never retries launched work.

Complete measured capacity refusal retains resource disposition. Unknown admission,
stale identity, unavailable runtime monitoring, startup failure or cleanup/storage
failure is infrastructure termination, independent of trial/formal or ordinary
admission enforcement posture. An ordinary candidate subprocess error after valid
startup/protection retains existing error and OOM-attribution semantics.

## Compatibility and qualification

No policy means no new serialized policy/evidence field, measurement, startup argv
or selected observer. CPU and pseudo paths bypass GPU preparation. The separate
`strict_lifecycle=False` measurement default is omitted from serialized requests;
selection reuses complete RSS/finalization for checkpoint inference without changing
the ordinary inference assessor's contract. Explicitly selected runs intentionally
add evidence to records and therefore to consumers that render those records.

Source identities change and require explicit external qualification. Historical
paper configurations/plugins belong in siderius-exp; this change does not certify
paper replay. CPU fixtures and harmless child processes test dispatch, clocks,
source checks, refusals and persistence; they do not qualify actual GPU performance,
telemetry or four-mode onboarding. Full `run_chain` setup review, custom external
evaluators, hard RSS quotas on scientific work and peak guarantees remain outside
this interface.

Admission recovery evidence: `tests/unit/core/test_protected_admission_recovery.py`
drives both native executor entrypoints through the shared tuner owner with
synthetic accounting and a stubbed child boundary. Its trial/formal × ordinary/isolated
matrix covers recovery, sampling exceptions, exhaustion, persistent refusal,
allowance exhaustion and terminal publication failure, retained measurement and
checkpoint, and durable sampling/terminal receipts. Existing native execution tests
exercise the real CPU process supervisor and checkpoint startup handshake.
