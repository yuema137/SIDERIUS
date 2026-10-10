# src/core/runtime_control

Runtime measurement/admission/observation/record/watchdog modules. Start at
[`bootstrap.py`](bootstrap.py), [`admission.py`](admission.py), and the
current admission boundary. The [runtime estimation guide](../../../docs/design/runtime_estimation_and_calibration.md)
is historical design context, not a second execution authority.
Focused admission tests are in [`test_admission.py`](../../../tests/unit/core/test_admission.py);
forecasts and blocking measurements are distinct authorities.

See [the parent guide](../README.md) for child ownership and the focused validation route.

## Stopping at a time budget

When enabled, the watchdog normally uses your declared time ceiling. A forecast
of two minutes does not shorten a fifteen-minute budget. A short explicit ceiling
also takes precedence over the old minimum runtime floor. Admission checks and
resource monitoring remain separate.

Use `--runtime_watchdog_deadline_policy forecast-tightening-v1` only when you
explicitly want the old forecast-based deadline. For configuration, missing-budget
errors and historical compatibility, see [watchdog deadlines](../../../docs/reference/watchdog-deadlines.md).

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

The ceiling comes from the current device and your configuration. With no
operator limit, admission uses the measured device capacity. You can set a lower
aggregate ceiling with `--gpu_pair_ceiling_gib`; a declared host quota also
constrains it. Moving to a larger GPU no longer silently inherits a 28 GiB
setting from another machine. For example, a caller ceiling of 24 GiB on an
80 GiB device still becomes 20 GiB if the host quota is 20 GiB. See
[GPU ceiling configuration](gpu-ceilings.md) for precedence, units and errors.

Ordinary `GpuAdmissionPolicy.enforcement` still determines whether a refusal
stops execution or is recorded as an observation. Explicit namespace-limited
execution continues to stop whenever headroom evidence is insufficient.
These are environment decisions; they do not justify shrinking the model.
The measured demand is an empirical estimate, not a bound on every later input.
This check does not add runtime GPU monitoring or supply missing trial/inference
measurements. Historical unlabelled requirements remain readable but cannot
silently acquire new-worker ownership. External estimator profiles must qualify
the changed observation/decision source identity before reuse.

## When a short task finishes before timing stabilizes

A task that has finished its selected work does not need a prediction of how
long that same work would take. The default `completed-workload-v1` policy checks
its actual elapsed time against the budget. Remaining work still needs the
existing conservative checks. A completed training stage includes its required
validation; inference must finish writing every prediction before it can pass.

This does not make a few fast batches a reliable speed estimate. Their timing
record remains unsuitable for future calibration. Partial work cannot claim
completion. With a timing budget enforced, exceeded measurement limits or a
real budget overrun still refuse execution; without one, timing stays record-only.
A broken evidence channel always refuses execution. The framework does not add
epochs or change batch sizes to make timing pass.

For historical runs, the experiment repository can explicitly select
`--runtime_completion_policy verified-prediction-v1`. That keeps the earlier
requirement for a verified prediction. Use a new workspace when changing policy;
old records are never silently relabeled. The [technical timing contract](../../../docs/design/runtime_estimation_and_watchdog.md)
describes the accounting and compatibility boundary.

An experiment may also select an installed timing-verifier provider when its
historical algorithm differs from today's default. This is optional; ordinary
runs need no plugin. The framework checks the selected implementation in both
the launcher and execution environment, and keeps its calibration records apart
from other implementations. Follow the experiment's installation and selection
instructions; a missing or changed provider is an error, never a silent fallback.
See the [provider contract](verifier_provider_contract.md) for integration details.

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

This low-level interface does not dispatch a complete attempt by itself. The
[optional native execution policy](#protecting-a-native-gpu-attempt) connects it
to trial/formal training and post-training inference.
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
measurement-budget sharing or checkpoint handshake is implied by ordinary
supervision. The optional policy below selects those additional mechanisms. Successful ordinary output and launch semantics remain
unchanged; exception/orphan cleanup deliberately improves. The shared supervision
source identity changes, including the existing estimation assembly digest, so
external historical estimator qualifications must be refreshed explicitly.

### Testing optional GPU runtime protection

Framework integrators can test the protected observer through the Python API.
The optional native execution policy below connects this mechanism to the
training/inference launcher. Calls without that policy retain ordinary observation
behavior. This section describes the lower-level API for framework integrators.

Before calling it, obtain a typed `GpuProtectionBinding` and
`TimedGpuObservation` from your admission boundary and explicitly choose a
`GpuRuntimeProtectionPolicy`. The binding carries the already resolved ceiling;
the policy carries observation and cleanup timing. Do not substitute a GPU name,
nominal capacity or a new environment lookup for those admitted facts.

Pass one `GpuPhaseObserver` as both `observer` and `control` to
`supervise_process` or its package-aware `supervise_subprocess` facade:

```python
from core.runtime_control.gpu_observer import GpuPhaseObserver
from core.runtime_control.observed_subprocess import supervise_subprocess

observer = GpuPhaseObserver(
    binding.device,
    protection_policy=policy,
    protection_binding=binding,
    initial_observation=initial_observation,
)
result = supervise_subprocess(
    command,
    env=child_environment,
    preexec_fn=None,
    capture_stdout=True,
    observer=observer,
    control=observer,
)
receipt = observer.protection_receipt()
```

Here `command` and `child_environment` are your explicit child inputs; the three
protection objects must already be validated. A successful result has a frozen
receipt with usable live samples. A ceiling breach or missing/stale telemetry
raises `ProcessControlError`; inspect its lifecycle and the observer receipt.
The supervisor stops only its owned child group. A stop is an environment result,
not evidence that the model should shrink.

For example, with a supplied 900 MiB ceiling, a sampled total of 950 MiB stops
the child even if the next reading is 700 MiB. The total already includes the
worker, so its measured demand is not added again. Samples can miss intervening
spikes; this is not a hard GPU partition. See the [protection contract](gpu-protection.md)
for coverage, shutdown, identity and the remaining production integration work.

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
stopping by itself. The optional native execution policy below connects them. Shared
file-verification code participates in the estimator assembly identity, so source
qualification must be updated even though absent-checkpoint request bytes and
ordinary inference loading remain unchanged.

## Training measurement with complete evidence

A bound training measurement records setup and training separately, then uses
whichever observed peak is larger. It loads a real task batch and preserves a
short tail when the task permits one. If target standardization is enabled, it
fits the authorized training pool using the same rule as native training before
loading the measured batch.

Callers preparing this measurement use `bind_training_measurement(spec)` and
check the result with `assess_training_measurement(spec, run, cap_mib=...)`.
Missing sampling, preprocessing or cleanup evidence yields `unavailable`; it
does not establish that a smaller model would work. A successful result describes
the bounded probe, not every future input. The optional native execution policy
selects this API for both trial and formal attempts. See the [training measurement contract](training-measurement.md)
for required inputs, evidence and remaining integration work.


## Protecting a native GPU attempt

For a composed task using the native trainer and inference executable, you can
request a measurement before each phase and sampled GPU protection while it runs.
Both trial and formal attempts follow the same sequence:

1. Measure a bounded training workload using the selected task scope and settings.
2. Check current GPU headroom, then train under sampled protection.
3. Identify the saved checkpoint and measure inference with those weights.
4. Load and verify that checkpoint in the inference child. The parent authorizes
   inference only after verifying the child's receipt and startup memory evidence.
5. Record the measurement, admission decision, protection outcome and child cleanup.

Save an explicit policy outside this repository, for example at
`/home/me/experiment/gpu-execution.json`:

```json
{
  "phase_measurement_budget_seconds": 120.0,
  "worker_rss_limit_bytes": 8589934592,
  "startup_ack_timeout_seconds": 5.0,
  "startup_receipt_limit_bytes": 1048576,
  "protection": {
    "observation": {
      "fast_interval_ms": 20,
      "fast_window_ms": 1000,
      "steady_interval_ms": 100,
      "join_timeout_ms": 500
    },
    "max_sample_age_seconds": 2.0,
    "control": {
      "poll_seconds": 0.05,
      "grace_seconds": 1.0,
      "reap_seconds": 2.0
    }
  }
}
```

These are example choices, not defaults or a hardware recommendation. The 120-second
allowance is shared by preparation and both measurements; actual training is outside
it. The 8 GiB RSS limit applies to measurement/checkpoint/startup preparation, not to
all later training. Choose values that fit your task and machine. The GPU aggregate
ceiling remains configured through the existing [ceiling settings](gpu-ceilings.md).

Add this argument to your existing single-iteration launch command:

```bash
--gpu_execution_policy_json /home/me/experiment/gpu-execution.json
```

The resolved policy becomes part of the workspace lock. Changing it requires a new
workspace. Without this argument, ordinary launches keep their existing behavior;
CPU and pseudo execution do not launch these GPU measurements.

Inspect `gpu_execution/<attempt-token>/training-terminal.json` and
`inference-terminal.json` inside the executor's run directory. Measurement details
are in the corresponding `training/measurement.json` and `inference/measurement.json`.
Completed experiment records also carry the attempt's typed `gpu_execution` evidence.
A missing measurement, changed source/checkpoint, unavailable monitoring or failed
cleanup stops the run as an infrastructure error. It is not evidence that the model
should be smaller. A complete capacity refusal retains its resource refusal status.

This option currently requires task-owned training/evaluation scopes and the native
checkpoint path. External evaluation executors are refused before training. GPU
telemetry must be available and usable; selecting a policy does not add a vendor
telemetry adapter. Sampled protection can miss spikes between samples and is not a
hard GPU partition. Parent filesystem operations are cooperative, and cleanup may
extend past the work deadline. See the [execution contract](native-gpu-execution.md)
for interfaces, record semantics and compatibility boundaries.
