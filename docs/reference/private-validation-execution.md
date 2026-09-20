# Private validation execution: current mechanism and integration contract

Status: RNG state transport and synthetic process parity are implemented.
There is **no installed remote validation executor** in this change. The normal
training engine still executes its local `_validation_pass` unchanged.

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
