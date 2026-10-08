# Protected GPU observation contract

## Scope and owners

`GpuPhaseObserver` supports explicit `protection_policy`, `protection_binding`
and `initial_observation` together. `gpu_protection.py` owns typed evidence and
pure observation checks; `gpu_protection_state.py` owns fixed-size state. The
existing observer still owns one sampling thread. `process_control.py` defines
an evidence-only supervisor interface. `observed_subprocess.py` alone signals,
drains pipes, reaps and checks its owned process group.

This API is not connected to training/inference execution or the tuner. There
is no protection CLI flag, automatic policy, hardware discovery or changed
ordinary observation default. Production activation needs separately reviewed
admission transport, infrastructure-outcome persistence and partial-artifact
handling. It must not map this stop to candidate OOM or automatic batch shrink.

## Inputs and decision

All three protection inputs are required together. The binding names an attempt,
phase, device UUID, physical capacity, effective ceiling and ceiling origin.
The caller supplies admission's already resolved ceiling, at or below capacity.
The observer never rereads operator limits. Policy selects the existing cadence
schema plus explicit maximum sample age and process poll/grace/reap bounds.
There are no new timing or capacity defaults. Effective cleanup bounds intersect
active supervisor bounds; legacy poll=0 is omitted from the positive polling
minimum, while grace=0 remains an immediate-termination instruction.

The caller supplies a pre-spawn observation, including query start/completion
from the same parent monotonic clock used for subsequent observations. It is
checked during construction and immediately before Popen, after preparation.
Missing/incoherent data, wrong UUID/capacity, future timestamps, stale data and
occupancy above the ceiling refuse. Accounting uses `OccupancyBound`; usage is
**total device usage**, without adding the new worker's requirement again.
Equality is allowed. Arithmetic does not infer a GPU vendor or model. The
existing nvidia-smi producer cannot establish telemetry on unsupported hardware.

Live coverage needs a successful query bracketed by child-liveness observations.
Maximum age starts at query start. Before a fresh observation replaces the
previous accepted one, the previous coverage is checked at publication time.
If both threads stall past its expiry, the new reading cannot repair that gap.
An unavailable observation or ceiling breach latches the first stop; later good
readings remain diagnostics and cannot restore permission. No history list grows
with phase duration. One live sample is a minimum coverage fact, not proof of
unseen peaks or a physical memory partition.

## Lifecycle and errors

States are prepared, running, stopping and frozen. The same object must be
passed as observer and control. It is single-use, including after pre-spawn,
Popen or thread-start failure. Selecting control creates an owned session and
finite communication polling even without a watchdog or CPU limits.

All sampler IO, child polling, thread join and cleanup run outside the state
lock. The lock protects only bounded state changes. Phase end is recorded before
cleanup; terminal freshness uses that observed end, not cleanup duration. No
post-exit query can improve live coverage. Such a query can still report a breach
or failure. Stop never launches a synchronous post-failure GPU query. Join is
bounded by the selected observation policy; a timed-out daemon may finish later,
but cannot mutate the frozen receipt. A very short child with no live sample is
unavailable even if it exits successfully.

`ProcessControlError` carries the latched decision, process lifecycle and child
stdout/stderr. A competing watchdog timeout remains in the exception's `timeout`
field; the lifecycle retains any earlier supervisor stop reason. It takes precedence over an ordinary nonzero child exit, including
a signal caused by the guard. Package refusal and primary interrupt exceptions
keep their type and lifecycle evidence. A zero exit during TERM grace never
clears a stop. Existing process cleanup remains authoritative and reports unknown
or surviving group evidence separately. Containment covers only the owned group,
not deliberately escaped sessions; synchronous callbacks and arbitrary captured
output have no new hard bound.

`observer.protection_receipt()` exposes the immutable frozen GPU receipt.
Lifecycle results include an optional `control_decision`; the field is omitted
when no control was selected. `GpuEvidenceBundle` retains its historical schema;
protected authority is the separate receipt, never its old peak/last fields.

## Identity and verification

The receipt records a separate `protection_mechanism_digest()` using the existing
labelled-source `source_fingerprint` algorithm. Its closure includes observation,
state, pure decision, accounting/visibility, conversion, process control,
supervision/group cleanup and the fingerprint owner. It does not replace the
prephase estimator digest or establish paper runtime equivalence.

CPU tests use supplied snapshots and clocks plus harmless real children. They
cover scaled thresholds, coverage gaps/recovery, terminal races, bounded join,
single-use failure, owned process cleanup, control transport and ordinary-path
regressions. No GPU qualification, training or provider request follows from them.
