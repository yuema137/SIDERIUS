# `core/` — run-scoped execution infrastructure

**Audience**: a coding agent or engineer about to modify the execution
substrate. **Authority**: the source. Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../../docs/agent-reference/MODULE_README_TEMPLATE.md).

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
| `execution_calibration.py` | `ROLE_CEILINGS` (training 40 · inference 60 · scoring 24 GiB, with derivation provenance) · `resolve_role_ceiling_gb(role)` (two layers: `SIDERIUS_SUBPROCESS_RSS_GB` caller override, else the declared default; the override is either one global integer or one complete role mapping; `0` disables the selected role; malformed **refuses**) · `calibration_provenance()` |
| `hardware_context.py` | `get_or_create(workspace, run_name)` — discovery + the per-run `{run_name}_hardware.json` manifest; the only `torch.cuda.get_device_properties` call site |
| `subprocess_env.py` | the one environment a child needs to see generated plugins (`SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS` transport) |
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
- **Role memory ceilings via `RLIMIT_AS`**, converting a kernel OOM-kill into
  a catchable, recorded failure. Exactly three application sites (one per
  role).
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
- Host-RAM posture: `SIDERIUS_SUBPROCESS_RSS_GB`, an operator decision. Use
  one non-negative integer to set every role, or one complete mapping such as
  `training=0,inference=96,scoring=24` when a host needs different ceilings.
  A mapping must name all three roles exactly once; `0` disables that role.
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
| `MemoryError` in a child | the role ceiling working: structured `oom_host_ram`, not a dead host |

## Files normally edited

`server_configs/` (new host); `runtime_control/` policy modules under their own
design docs. `execution_calibration.py` values only with re-verified evidence —
the inference 60 GiB ceiling is marked `empirical_unverified`, and **lowering it
without re-verifying full-scope baseline inference is a regression** (CLAUDE.md
subsystem invariant).

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
