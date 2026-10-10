# Structural preflight estimation providers

## Ownership and selection

`core.preflight_estimation` resolves the optional task-composition
`preflight_estimator` through `siderius.preflight_estimators`. The named factory
returns `PreflightEstimatorProfile`. Native `registered-state-v1` is the default;
external package installation alone cannot replace it. Providers are trusted
installed code, not generated model code or a security sandbox.

Providers receive `PhaseObservations` and return `PhaseEstimate`. Both are frozen,
extra-forbid Pydantic contracts. The framework copies nested input data before
calling a provider and revalidates its result. It requires matching phases,
nonnegative integer byte counts and a diagnostic breakdown summing to the
diagnostic total. Providers cannot return admission flags, new caps, candidate
batches or timeout policies through an estimate. Admission and diagnostic bytes can differ: search
and human-facing summaries use different documented activation proxies.

## Explicit static workload rules

`PreflightEstimatorProfile.workload_rule` optionally declares a frozen, strict
`BatchSegmentationLimit(kind="batch-times-segmentation-v1", limit=...)`.
Native `registered-state-v1` selects `None`: batch size times a transport or
segmentation extent does not establish generic kernel cost. There is no implicit
product ceiling and no GPU/model/task-name exception.

A selected rule is applied only when segmentation extent is declared. The same
rule owns training inspection, early inference-candidate filtering and recorded
`intensity_product`/`intensity_limit`. Without an applicable rule both evidence
fields are null. A static refusal may omit a VRAM estimate only when the explicit
rule rejected the candidate before probing; absent evidence never proves a pass.

This declaration does not disable structural memory checks, probe deadlines/RSS
limits, task batch constraints, measured admission or selected runtime protection.
Direct structural-skill calls still establish only estimates, not GPU feasibility.
The protected native execution route separately requires bounded phase measurements
and usable device headroom; an incomplete measurement remains a refusal.

Declare calibrated historical limits in an experiment-owned provider. The resolved
rule (including null) is hashed with the declared sources, so even a rule-only
change invalidates composition, worker and resume identities. Installing a profile
does not select its rule. Migrate to a new workspace; keep archived locks intact.

## Observation contract

`estimation_inputs.observe_phase` preserves the completed structural probe's
leaf-call parameter total, leaf output sum/maximum, input/output bytes and saved
tensor bytes. It adds independent model/loss registered-state inventories and
the production `TrainConfig.optimizer_type`. The original JSON training
declaration is retained separately; normalizing through `TrainConfig` must not
erase information required by an explicitly selected external provider.

An inventory is either available with complete byte/count fields or unavailable
with a reason and no numeric fields. Unsupported layouts and unmaterialized
tensors never become zero-byte observations. Native estimation requires available
inventory; an external provider can consume the other observations without that
requirement if its qualified arithmetic does not use inventory.

## Native accounting and limits

Registered parameters are counted by Parameter object identity across the module
tree, independently of forward invocation count. Parent-owned, unused and frozen
parameters remain resident. Buffers include nonpersistent registrations and are
counted per registration slot within unique module objects. Distinct objects
sharing CPU storage are priced separately because allocating transfers can break
storage sharing. These are projected registered allocations, not proof of target
device aliasing or a universal upper bound.

Training uses registered model/loss state, saved tensors, input/output,
trainable-model gradients and optimizer state, trainable-loss gradients and the
existing context/backward residual terms. The production optimizer owns model
parameters; loss parameters do not receive model optimizer moments. Frozen
parameters have resident bytes but no gradient or optimizer-state charge.
Native arithmetic uses the production optimizer selection, including SGD versus
Adam-family state requirements.

Inference admission retains the leaf-output sum proxy plus registered model
state and the existing context residual. Inference diagnostics retain input
bytes plus the maximum of final/leaf output bytes, registered model state and
context residual. No sum-to-maximum admission change is included.

Saved-tensor overlap/lifetime and leaf-output lifetime are unresolved structural
limitations. The existing residual constants are calibrated assumptions. This
change does not establish actual device peak, architecture-independent precision,
or acceptance on arbitrary hardware. Static refusal remains distinct from a
measured GPU-capacity failure.

## Identity, transport and failure

Profile identity includes name, version, declared source-content hash and the
framework estimation assembly hash. External profiles declare qualified assembly
hashes. The assembly covers observation, arithmetic, evidence, worker transport
and task-composition binding. Both native and external identities enter new
workspace semantic fingerprints and are rechecked while bound. A changed source
or unknown assembly fails closed; there is no fallback to a different estimator.

The parent snapshots the active identity into `IsolatedProbeSpec`; the child
independently resolves the installed provider and verifies the exact identity
before model construction or task-data probing. New structural results carry
`static-preflight-v2` evidence with that identity. The parent checks returned
identity against dispatch. A successful device-available structural inspection
cannot omit this evidence. CPU-only skipping carries `StaticPreflightBypass`
with reason `cpu_only` and the matching estimator identity, rather than phase
decisions. The parent rejects that bypass when its hardware snapshot declares a
device available. Standalone discovery without a parent snapshot must still
return explicit bypass evidence; an incomplete success cannot masquerade as CPU
skipping. Bypass and structural decisions are mutually exclusive.
V1 archived evidence remains readable, but cannot substitute for new worker
identity evidence.

## Historical experiments

Frozen historical arithmetic belongs in the experiment repository. Selecting a
qualified external provider can restore its historical phase totals and batch
selection on the qualified observation domain. Restoring only prompt text cannot
restore a batch decision made by different arithmetic.

Existing archives and locks remain unchanged. Because every new composition pins
the estimator, migrate a verified historical configuration to a new workspace
with an explicit experiment-owned provider. Do not silently resume an old lock
under native corrected accounting. Historical prompt providers must independently
qualify the exact estimator identity before interpreting new records as old
inputs. This does not promise identical stochastic LLM responses or scores.
