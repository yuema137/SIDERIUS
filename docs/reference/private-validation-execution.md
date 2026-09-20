# Deployment-selected validation execution

The native training loop can call an explicitly bound validation executor after
each completed epoch. Without a binding, the existing local validation path is
unchanged. This interface does not grant private-data access, certify training,
or deploy a service.

## Integration

`execute_tools.validation_execution.ValidationDeployment` declares a public
client factory and JSON settings. Enter `bind_validation_deployment` around the
native tuner/training invocation. The existing sandbox transports this binding
to the training child; no environment-variable discovery is used.

The factory returns an executor with `declared_rows(scope)` and
`observe(request, callbacks)`. The former provides the authorized row count
without making the parent load private validation data. The latter receives
live model/criterion objects on the research side. These objects are not a wire
format or proof of provenance: never deserialize them in a privileged process.
The deployment owns native training admission and private execution.

Return a validated `ValidationExecutionResult` with aggregate loss and exact
row count. Existing declared observations, when enabled, must be complete or
explicitly failed; a previous failure cannot silently disappear. This mechanism
does not enable new observations in a frozen task. Exceptions, invalid results
and row mismatches fail the attempt; there is no fallback to private data reads
in the research process.

The client must invoke allocation and verification callbacks during execution.
The framework records the full elapsed call, including client setup and state
transfer, in the existing validation history. Keep one-time objective review
outside repeated epoch work. Training model/optimizer state stays in the same
process across epochs.

`train_engine_sandbox.observe_validation` exposes the existing estimator for
deployment use, including its sample weighting and transactional state handling.
It does not provide isolation. For custom losses, an already-resolved target
dtype may be passed without importing candidate plugins in the coordinator.

## Evidence and limits

Synthetic tests exercise a real training subprocess over two epochs, binding
transport, default behavior, failure propagation and history. They do not prove
private-worker permissions, real GPU performance, native training provenance,
or production task scoring. Those remain deployment smoke requirements.
