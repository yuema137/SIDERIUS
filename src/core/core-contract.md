# `core/` — run-scoped execution infrastructure

Technical inventory for this module. Start with [the directory guide](README.md)
for navigation. Source and tests determine current behavior.

## Purpose

Everything a run needs *underneath* the science: subprocess sandboxing and
memory ceilings, hardware discovery, the run-invariants lock, chain resume,
runtime measurement/admission, and campaign bookkeeping. Nothing here knows
what a task means — task semantics live in
[`execute_tools/`](../execute_tools/README.md) and in task packages.

## Public interface

| file | surface |
|---|---|
| `run_invariants.py` | `RunInvariants` (frozen model) · `build_run_invariants` (the ONE shared construction path — materializes + hashes the effective health config first) · `ensure_run_invariants(workspace, expected)` (create-or-validate, first writer wins) · `validate_stamped_invariants` (ingress check for seeds/restored records) |
| `resume.py` | `restore_prior_state(workspace, current_iter, seed_paths, …) -> RestoredState` · `union_key_findings` (THE findings-union authority) · the digest projections (`project_knowledge`, `project_prediction_memory`, `project_vocab_link_confirmations`, …) |
| `chain_state.py` | `ChainState` — the chain's mutable cross-iteration state; `chain_state_field_names()` feeds the carriers' deny-lists |
| `sandbox_executor.py` | `TidmadSandbox` / `StubSandbox` — the GPU child launch surface: `execute_training`, `execute_inference`, `evaluate_metric`, `execute_scoring`; every child goes through one observed-subprocess seam |
| `execution_calibration.py` | `resolve_role_ceiling(role)` (typed role/value/source) · `resolve_role_ceiling_gb(role)` (compatibility projection: `None` inherits existing OS limits; explicit `0` adds no cap; positive GiB retains the child RLIMIT_AS setter) · `SIDERIUS_SUBPROCESS_RSS_GB` accepts one global integer or complete role mapping; malformed **refuses** · `calibration_provenance()` records configured policy, not measured OS limits |
| `hardware_context.py` | `get_or_create(workspace, run_name)` — discovery + the per-run `{run_name}_hardware.json` manifest; `inspect_gpu_runtime()` — fresh backend/property facts without persistence, under the [accelerator contract](accelerator-runtime.md) |
| `subprocess_env.py` | the one environment a child needs for generated plugin roots and optional captured task-code transport |
| [`local_code/`](local_code/README.md) | finite captured package imports, whole-set identity, verified child transport and named integrity refusal |
| `runtime_control/` | measurement, admission, watchdog, calibration registry, `launch_guard.run_launch_self_test`, estimator/policy identity |
| `server_configs/` | per-server calibration registry (`_base.py` schema; one module per host) |
| `campaign_identity.py` | validates campaign ids, binds campaign state to its identity stamp, and admits campaign homes |
| `runtime_control/campaign.py` | typed C12 validation-campaign matrix, measured cell records, pairwise plans, and campaign verdicts |
| `committed_digests.py` · `memory_probe.py` · `inference_defaults.py` · `scientific_authority.py` | single-purpose authorities (read their docstrings) |

## Inputs

Workspace paths and run names; the environment overrides named above; the
calibration store (default `~/.siderius`, override `SIDERIUS_CALIBRATION_DIR`);
prior-run outputs for resume/seeding.

## Outputs

`{workspace}/run_invariants_lock.json` · `{workspace}/{run_name}_hardware.json` ·
child subprocesses with role-scoped `RLIMIT_AS` · `RestoredState` for the
workflow · calibration observations.

## Owned semantics

- **The lock partition rule**: `_CANONICAL` fields are compared on resume,
  `_PROVENANCE` fields (e.g. the resolved role ceilings) are recorded and
  *never* compared — a resume on a differently-calibrated host stays legal. A
  guard test asserts the two partition every declared field.
- **Role memory ceilings via `RLIMIT_AS`** constrain process address space,
  with one application per execution role. Allocation refusal can be recorded;
  this is not universal protection from kernel OOM or host failure.
- **The findings-union rule** has one authority (`union_key_findings`), called
  by both the digest projection and the loop closure; re-inlining it is the
  defect a mutation-proven structural guard exists to catch.
- **Replay integrity on resume**: a prior iteration whose `run_output` hash
  does not match its manifest stops the chain (`ReplayIntegrityError`).

## Non-owned semantics

- What the children *do* → [`execute_tools/`](../execute_tools/README.md)
  engines; [execution mechanism](../../docs/agent-reference/mechanisms/execution.md).
- What the lock's health hash *means* →
  [`execute_tools/health_checks/`](../execute_tools/health_checks/README.md).
- When gates fire, round policy → the tuner node.
- The workspace layout narrative →
  [workspaces and resume](../../docs/guides/workspaces-and-resume.md).

## Extension points

- A new host: add `server_configs/{hostname}.py` (unknown hosts fall back with
  a one-time warning — only time forecasts are affected).
- Additional address-space cap: `SIDERIUS_SUBPROCESS_RSS_GB`, an operator
  decision. Its legacy name means RLIMIT_AS, not physical RAM/RSS. Omit it to
  inherit OS limits without an additional cap. Use
  one non-negative integer to set every role, or one complete mapping such as
  `training=0,inference=96,scoring=24` when a host needs different ceilings.
  A mapping must name all three roles exactly once; `0` adds no cap for that
  role and does not remove inherited OS restrictions. Numeric validation applies
  to the selected role; provenance resolves and checks all three.
- There is deliberately **one caller-owned override layer**, not a hierarchy
  of global and per-role variables. The role mapping is a value carried by
  that existing layer; do not add another precedence level.

## State and filesystem effects

Writes the lock and hardware manifest into the workspace; appends calibration
observations under `~/.siderius` (host-global by design); spawns process-group
children. `StubSandbox` is the pseudo-training stub — no GPU, canned results.

## Failure modes

| refusal | meaning |
|---|---|
| `RunInvariantsViolation` | canonical lock field differs — new workspace, not a bypass |
| a pre-runtime-identity lock | rejected, not defaulted — that workspace cannot be resumed by this build |
| `MalformedCeilingOverride` | a bad `SIDERIUS_SUBPROCESS_RSS_GB` refuses loudly instead of silently falling back |
| `ResumeError` / `ReplayIntegrityError` | workspace state unreadable / tampered — fails closed |
| `LocalCodeError` | declared task-code integrity/dependency refusal; the workflow halts the chain with its own diagnosis, not a scientific failure |
| `MemoryError` in a child | may be classified as `oom_host_ram`; address-space limits do not prove host-wide OOM immunity |

## Files normally edited

`server_configs/` (new host); `runtime_control/` policy modules under their own
design docs. Additional address-space limits belong in caller environment
configuration, not machine-specific defaults in `execution_calibration.py`.
Historical experiment limits require verified provenance in exp; absence of an
archived environment does not prove that the old fallback value was used.

## Files normally NOT edited

`run_invariants.py` field partitions (adding a field to the wrong partition
either weakens the guarantee or breaks every resume); `sandbox_executor.py`'s
launch seam and role sites; `resume.py`'s union/projection authorities.

## Minimal example

```python
from core.execution_calibration import resolve_role_ceiling_gb
resolve_role_ceiling_gb("training")   # -> 40, or the caller override
```

## Related tests

`tests/unit/core/` (lock partition guard, calibration refusal, resume
projections, replay integrity) and the tuner/workflow suites that exercise the
sandbox seam in pseudo mode.
