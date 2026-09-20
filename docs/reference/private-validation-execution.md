# Private validation execution: current mechanism and integration contract

Status: RNG transport, native observation and an explicit training execution
binding are implemented. There is **no installed private validation service**
in this change. Without a deployment binding, training still uses its local
`_validation_pass` and original observation lifecycle.

The supported coordinator entry is
`execute_tools.train_engine_sandbox.observe_validation`, an alias of that same
implementation. It accepts numeric `nn.Module` proxies without reconstructing
candidate classes in the coordinator. Its optional
`resolved_custom_target_dtype` carries the loss declaration already resolved in
research (`long` or `float`). The existing `get_target_torch_dtype` remains the
sole interpreter: built-ins reject an override and a conflicting loaded custom
declaration is refused. Omission preserves the ordinary local route. No plugin
registry mutation or candidate loss import is needed for this transport.

## Bind an explicit deployment client

`execute_tools.validation_execution.ValidationDeployment` declares an importable
research-side client factory (`module:function`) and JSON settings. The factory
validates its settings and returns an executor implementing `declared_rows(scope)`
and `observe(request, callbacks)`. It must not load a privileged scorer or worker
in research. The declaration belongs to deployment configuration, separate from
the frozen task manifest. Settings must contain no credentials or private data:
they cross the child argv and may appear in ordinary execution records.

Wrap the native parent invocation in `bind_validation_deployment(declaration)`.
The production sandbox transports this explicit declaration to the training
child using `--validation_executor_json`; the child reconstructs the same client.
There is no environment-variable discovery. A missing/broken supplied factory
or settings fails instead of selecting local execution. An in-process-only
`bind_validation_executor(executor)` is available to callers that do not spawn;
attempting a native child launch without its deployment declaration refuses.
Bindings unwind on exceptions and preserve the enclosing binding.

The executor handles both ends of validation:

- Parent row declaration calls `declared_rows` instead of materializing private
  validation data in the parent. The service must authorize the task scope and
  return a positive integer. Serialization or deserialization is not authorization.
- Each completed training epoch sends a validated `ValidationExecutionRequest`
  with live model/objective objects, task scope, model I/O contract (when present),
  loss configuration, device, batch size and independently declared row count.
  This object is research-local and must never be pickled into a privileged
  coordinator. The client is responsible for safe staged module transport.
- `ValidationCallbacks` retains the original verifier, verification-completion
  callback and allocation callback. The client must feed them **during** the pass,
  before further batches run; reporting only after the final receipt is insufficient.
- A validated `ValidationExecutionResult` carries R3, materialized rows and
  aggregate observable outcomes. Row mismatch refuses before history append.
  The existing observation owner checks complete declared outcomes, finite
  observable values and the persistent failure latch without calling private
  observable implementations in research. Nonfinite R3 remains numerical evidence.
- The engine measures the entire bound call, including snapshot preparation,
  transport and callbacks, as validation time. The default local path retains
  the existing native timing definition.

The binding does not authenticate requests, enforce treatment, grant data access
or supply an endpoint. Those remain deployment/service responsibilities. Native
inference and scoring require their own connected execution routes; binding
training validation does not implicitly redirect them.

The synthetic transport test launches the actual training child through the
production sandbox for two epochs, verifies client execution in that child and
checks R3 against independent model replay. Its synthetic client deliberately
uses local fixture data: this proves the parent-to-child binding and absence of
parent validation materialization, not private-data isolation. A separate
three-epoch test compares R2, R3 and final model tensors with the default route.

## Preserve the existing transaction

A deployment that withholds validation data from research must run candidate
code outside the data owner's privileges. Moving validation into workers must
also preserve its scientific behavior. The existing validation loop remains
the authority for sample weighting, dataset order, dtype conversion, objective
state checks, observables, and in-pass verification/timing callbacks.

In that loop, each batch executes model → objective → observables. These calls
share Python, NumPy and Torch random generators. Computing every prediction
first and every objective afterwards changes stochastic models/objectives;
independently seeding workers also changes that shared stream.

`execute_tools.validation_rng` supplies schema-validated snapshots and restore:

- `capture_validation_rng(cuda_devices=...)` captures Python v3, NumPy's legacy
  MT19937 global generator, Torch CPU, and only explicitly selected CUDA devices.
- `ValidationRngState.model_dump_json()` / `model_validate_json()` provide a
  bounded byte representation and retain cached Gaussian values. Duplicate CUDA
  device identities and malformed schema fields are refused.
- `restore_validation_rng(snapshot)` tests incoming states on private generators
  before restoring global generators. Invalid CPU state or an unavailable CUDA
  device cannot partially replace the Python/NumPy/CPU streams.

The worker and coordinator must use identical runtime versions and CUDA device
mapping. This is not cross-version state conversion. Device initialization and
unexpected device failure during restore remain deployment concerns.

## Intended coordinator boundary

The private coordinator starts from the training transaction's initial RNG
snapshot and transfers current state into each isolated model/objective call.
It adopts the worker's post-call state **inside that private transaction** before
the next call. It returns only authorized aggregate results to research, never
post-validation RNG state, raw outputs, targets, or arbitrary worker diagnostics.
A model or objective can encode data into its RNG state; that state is therefore
private evaluation material once evaluation has started.

The RNG schema is a representation contract, not peer authentication, a sandbox,
an execution service, or a guarantee against information encoded in an authorized
scalar. Candidate modules must not be deserialized or imported by a privileged
coordinator. A data-owning service must retain its own scope and deadline authority.

## Evidence and remaining work

`tests/integration/execute_tools/test_validation_rng_workers.py` runs two real
CPU subprocesses and uses the unchanged native validation pass with RPC proxies.
Both the model and objective consume RNG, including Gaussian caches. Five rows
with batch size two produce exactly the native R3, with three calls to each
worker and unchanged caller RNG state. This is a process/order witness; those
workers do not establish distinct host identities or private-data mounts.

Unit tests cover JSON round trips and refusal before global-state replacement.
The CUDA round-trip test requires a real GPU; a skip is not CUDA evidence.

Release qualification still needs module/state transport without a new scripting
requirement on Python objectives, preserved observable behavior, per-batch runtime
callbacks, actual service identity/mount isolation, continuing deadline cleanup,
GPU equivalence, and the real training → validation → submission path. An RNG
round trip alone proves none of those deployment properties.
