# src/core/runtime_control

Runtime measurement/admission/observation/record/watchdog modules. Start at
[`bootstrap.py`](bootstrap.py), [`admission.py`](admission.py), and the
current admission boundary. The [runtime estimation guide](../../../docs/design/runtime_estimation_and_calibration.md)
is historical design context, not a second execution authority.
Focused admission tests are in [`test_admission.py`](../../../tests/unit/core/test_admission.py);
forecasts and blocking measurements are distinct authorities.

See [the parent guide](../README.md) for child ownership and the focused validation route.

## GPU admission before a new phase

A successful measurement describes the GPU memory held by its isolated worker.
That worker must have completed cleanly before its result can size a new worker.
The requirement carries its GPU UUID and original process receipt; missing
ownership, a different UUID, or a measured PID still visible on the device does
not establish an applicable requirement.

The admission check adds the new worker's measured demand to **all memory already
used on that device**. For example, a 1000 MiB worker beside a parent holding
500 MiB needs 1500 MiB of headroom accounting, so a 1200 MiB ceiling refuses it.
Parent memory is additional because the measurement did not include the parent.
Unattributed device bytes remain unattributed, but still consume headroom.
Decision evidence preserves the own/other/residual split and the worker receipt.

Ordinary `GpuAdmissionPolicy.enforcement` still determines whether a refusal
stops execution or is recorded as an observation. Explicit namespace-limited
execution continues to stop whenever headroom evidence is insufficient.
These are environment decisions; they do not justify shrinking the model.
The measured demand is an empirical estimate, not a bound on every later input.
This check does not add runtime GPU monitoring or supply missing trial/inference
measurements. Historical unlabelled requirements remain readable but cannot
silently acquire new-worker ownership. External estimator profiles must qualify
the changed observation/decision source identity before reuse.

## Measurement dimensions

Measurement identity records whether temporal segmentation is applicable. The
ordinary temporal path carries a positive `seg_size` and preserves the
existing calibration hash. A task-owned fixed-shape probe carries
`segmentation_applicability="not_applicable"` and `seg_size=None`; it may
measure bounded resource use, but the calibration derivation quarantines it
from temporal throughput evidence. No caller may replace the absent dimension
with a framework default. `TaskProbeDataSpec` carries this typed fact
explicitly; merely supplying task probe data does not decide applicability.

### First-epoch training allocation

An explicit `training_budget` is checked before optimizer and validation batch
dispatch, using its continuing monotonic clock and downstream reserve. Once
validation calibration completes, its verified full-pass cost is checked against
remaining training time, and normal runtime admission is refreshed immediately.
A refusal unwinds the attempt, persists its reason in the runtime sidecar, and
produces no completed epoch, checkpoint or score from partial validation. The
validation scope is never shortened to fit. A running batch is not killed and
may finish late; this is cooperative allocation, not a prediction watchdog.
Unbudgeted runs keep their existing behavior. Batch size, epoch limits and
scientific stopping/checkpoint selection are unchanged.

### Fast-phase calibration

`AdaptiveVerificationConfig.max_steps` bounds acquisition of stability and the
minimum observation count. Existing rolling-median detection remains the primary
path. When the measured median predicts that observations cannot reach `min_timed_ms` inside
`max_steps`, a 100-observation suffix may establish fast-phase evidence if the
normalized-rate medians of its first and second halves agree within the existing
relative stability tolerance. This distribution check tolerates heterogeneous
batch costs without treating a trend as steady. Reachability accounts for the
observations consumed before the earliest possible steady-state declaration; at
the defaults the fallback is unreachable around 2.7 ms and above, so those phases
retain the existing time requirement and detector behavior. Re-arming still
discards the old plateau's evidence. The wall bound also includes local verifier
processing.
Exhausted or unstable traces never become verified by relaxing evidence floors.
Relative slow observations are recorded in measurement details. A consecutive
streak of `steady.stable_windows` above `pathological_factor` times the prior
plateau fails verification; an isolated spike does not. Explicit `max_unit_ms`
still fails immediately after stabilization. These rules do not change data
selection, model size, resource budgets or prediction-watchdog enablement.

### Calibration across separate passes

Validation may need several epochs to gather enough timing evidence. Its
verification window counts active validation intervals, including dataset
construction, loading, transfers and computation. Training between those
intervals does not consume the validation window. Observations and stability
requirements survive between passes; an exception also closes the active
interval. Continuous callers keep the original uninterrupted wall clock.

Measurement receipts report `verification_active_wall_ms` and
`verification_excluded_inactive_seconds` to distinguish a real phase stall from
time spent elsewhere. The enclosing training allocation and campaign deadline
continue running throughout; pausing calibration does not extend either budget.

### Measuring a native inference checkpoint

The inference measurement worker can load an explicitly identified checkpoint
through `GpuMeasurementSpec.inference_checkpoint`. This supports the native
state-dictionary format written by `training_checkpoint_path`; whole-model
pickles and arbitrary external trainer formats are outside this interface.
The caller must already know the absolute path, experiment ID, SHA256 and byte
size, and provide the existing task evaluation scope and measurement budgets.
The historical training artifact sidecar can supply identity when present,
but is not available for every task or training path.

1. Construct an `InferenceCheckpointReference` with those four identity fields
   and attach it to an inference spec. Leave it absent to measure a fresh model.
2. Compute and attach `inference_measurement_binding(spec)` after adding the
   reference. Dispatch requires that complete binding; the initial spec does not.
3. Use the existing bounded measurement runner. Inside measured setup, the worker
   checks the training completion marker, verifies the opened file, loads weights
   on CPU into the resident model, and restores target-standardization state.
   Streaming checks before and after loading consume the existing worker budget;
   the parent retains its hard deadline and host-memory limit. A changed file or
   expired verification budget yields unavailable evidence.
4. Assess the returned run with `assess_inference_measurement`. A positive result
   requires the verified checkpoint receipt, complete setup and inference
   sampling, acknowledged reservation holds, matching evaluation geometry and
   identity, and clean process termination. `worker_requirement_mib` covers the
   larger of setup and inference peaks. A classifier result alone is insufficient.

For example, setup at 900 MiB followed by inference at 700 MiB needs a 900 MiB
worker requirement, subject to all those evidence checks. This says what the
bounded evaluation workload observed, not what arbitrary later inputs will use.
Two file checks detect ordinary mutation; they do not provide an immutable
snapshot against a hostile concurrent writer.

This interface does **not** dispatch measurements for trial or post-training
inference, produce missing checkpoint identities, or populate runtime admission
tables. Those integrations remain required before isolated GPU onboarding works.
Fresh-model request serialization remains unchanged when the optional reference
is absent. The implementation's source identity changes, so externally selected
preflight estimators must qualify the new assembly explicitly.

### Supervising an owned subprocess

`observed_subprocess` owns the lifecycle used by the executor's training and
inference launches. Ordinary calls retain their existing arguments and return
values. Plain children stay in the caller's session so terminal stop signals
still reach them. Watchdog calls create a separate process group so termination
can reach that child's descendants. The executor keeps its existing import and
mocking entry points; this owner does not import model registries.

Code that explicitly needs a CPU work deadline and host-memory monitoring can
call `supervise_process` with validated `ProcessLimits`. Supply the deadline,
RSS limit in bytes, polling interval, termination grace and reap interval; none
is inferred from a scientific task. This opt-in route creates its own session
and requires usable Linux `/proc` evidence before launch and during execution.
It returns `ObservedProcessResult` with the process result and a typed lifecycle
receipt. It is not yet wired to checkpoint identity preparation or phase budgets.

The supervisor now cleans up when observer startup or a deadline callback raises,
and checks for descendants after an owned leader exits. For example, a leader
can return 0 while its child still holds an output pipe open. The supervisor
terminates the remaining owned group and reports an unclean lifecycle rather than
waiting indefinitely for that pipe. Required cleanup and remaining descendants
are separate facts: successful termination does not erase the first problem.
Only the direct child can be reaped here; descendant zombies may still await the
host reaper and are recorded as present.

`ProcessSupervisionError.lifecycle` reports new monitoring/resource/cleanup
failures. A pre-existing exception, including a nonzero child exit, keeps its type
and identity and receives `process_lifecycle` evidence instead. Observer shutdown
cannot replace that primary failure. Missing process-memory evidence is distinct
from zero usage; a permission error checking group liveness is unknown, not proof
that the group is gone. Existing numeric and Boolean process helpers retain their
legacy projections for callers that have not selected strict supervision.

These checks sample a process group. They do not contain children that deliberately
escape into another session, cap arbitrary captured output, or interrupt blocked
parent callbacks and package preparation. The watchdog clock now starts before child creation and observer startup, and
checks the deadline before its first wait. This deliberately includes startup
time that the old path excluded; thresholds remain unchanged. Startup time counts
toward the work deadline, but the synchronous callback itself cannot be interrupted
by this loop. Cleanup may extend beyond that work deadline. No GPU memory stop,
measurement-budget sharing, checkpoint handshake or complete isolated onboarding
is provided by this change. Successful ordinary output and launch semantics remain
unchanged; exception/orphan cleanup deliberately improves. The shared supervision
source identity changes, including the existing estimation assembly digest, so
external historical estimator qualifications must be refreshed explicitly.

### Preparing a checkpoint reference on CPU

`checkpoint_identity_runner.prepare_checkpoint_identity` can produce the explicit
reference required by native inference measurement. It reads and hashes a completed
native checkpoint in a fixed CPU worker; it does not deserialize weights, import
model registries or select a scientific task. This interface supports the native
filename owned by `training_checkpoint_path` and its existing completion marker.
Historical artifact sidecars are not required.

1. Supply a `CheckpointIdentityRequest` with the absolute native checkpoint path,
   model type, experiment ID and a fresh request nonce. Set `cooperative_seconds`
   to the same work allowance supplied in `ProcessLimits`; the parent remains the
   hard deadline owner.
2. Supply explicit process limits, the child environment and an absolute,
   caller-owned `request_directory`. The adapter creates a temporary request
   directory there and removes it on completion. Package-bound callers pass the
   existing `subprocess_env()` result so the usual code-integrity guard applies.
3. Read `CheckpointPreparationResult.status`. Only `available` has an accepted
   `reference`. Unavailable results retain parsed worker evidence and lifecycle
   information where available; their raw worker receipt is not authorization.
   The result also reports request preparation, supervised execution and final
   checking/cleanup time. No attempt budget is debited by this interface.

Preparation consumes the supplied allowance. With 10 seconds available, request
preparation taking 3 seconds and package preparation taking 2 seconds leave at
most 5 seconds for monitoring preparation and the worker. Each layer deducts its
own preceding work; expiry before launch refuses without spawning. Parsing and
request cleanup count too: a valid worker receipt that finishes those steps late
becomes unavailable, retaining its evidence and actual elapsed time.

The worker hashes the same unbuffered regular file twice, checks metadata and
pathname continuity, and refuses missing completion markers, changed files,
symlinks and unsupported file types. The parent requires the matching request
nonce, child PID and native reference, plus a clean process lifecycle. Package
refusals retain child cleanup evidence. The file checks are shared with the bound
inference loader; two checks detect ordinary mutation, not a hostile-writer
snapshot. A later production load must still verify the same identity.

Only this fixed worker's compact protocol output is supported. The supervisor
does not impose a general output-memory cap or interrupt blocked parent request,
package or filesystem operations. If parent preparation returns late, it refuses
instead of granting the child a fresh allowance; necessary cleanup may overrun
the work deadline and is reported. This interface does not connect trial/formal
phase measurement, shared attempt budgets, inference authorization or GPU memory
stopping. Those remain separate prerequisites for isolated onboarding. Shared
file-verification code participates in the estimator assembly identity, so source
qualification must be updated even though absent-checkpoint request bytes and
ordinary inference loading remain unchanged.
