# `execute_tools/health_checks/` — pluggable validity checks

**Audience**: a coding agent or engineer touching the Health subsystem, or a
task author writing a custom check. **Authority**: the source. Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../../../docs/agent-reference/MODULE_README_TEMPLATE.md).
Concepts for humans: [health gates](../../../docs/concepts/health-gates.md);
cross-cutting semantics:
[health-gates mechanism](../../../docs/agent-reference/mechanisms/health-gates.md).

## Purpose

Answers *"is this output structurally valid enough to trust?"* — a different
question from "is it good?". Checks run on peeked outputs at tuner round
boundaries, outside the scoring pipeline. The framework owns *what a failure
does*; the task owns *what is checked and how strictly*.

## Public interface

| file | surface |
|---|---|
| `registry.py` | `register(check)` · `register_view_provider(provider)` — the **public** registration API for built-ins and external plugins alike · `get` / `all_registered` (+ provider counterparts). Duplicates raise |
| `protocol.py` | `HealthCheckSkill` (Protocol): `name`, `declaration: CheckInputDeclaration`, and `run(ctx, config=None, *, view=None) -> HealthCheckResult`. A check that declares no view is invoked as `run(ctx, config)` |
| `schemas.py` | the typed vocabulary: `CheckVerdict` (`passed` / `failed` / `inapplicable` / `error`) · `GateAction` (`continue` / `invalidate_round` / `skip_to_formal` / `skip_iter`) + severity · `HealthCheckContext` / `HealthCheckResult` / `GateResult` · `CheckInputDeclaration` · the `FACT_AXES` |
| `runner.py` | `evaluate_gate` (decides applicability **before** invoking a check) · `resolve_action` (max severity wins) |
| `evaluation.py` | `evaluate_and_persist_health_gates` — the batched evaluate-and-persist adapter both Phase-1 baselines and tuner rounds use |
| `config.py` | `load_health_gates_config` (returns the **composed** result) · `materialize_effective_config` → `{workspace}/health_checks_effective.yaml`, sha256-pinned by the invariants lock |
| `_task_health_config.py` | `TaskHealthConfig` — the task-owned document: facts, value scale, peek files, roster (`gate_id`, `check`, **`disposition`** — the task's only policy choice — `parameters`, `reason`), `plugins:` |
| `_plugin_binding.py` | `load_task_health_plugins` — run-scoped loading of external plugin files |
| `standard_views.py` | the framework-standard view capabilities `categorical_predictions` / `continuous_samples`: 1-D typed, read-only, no-copy, engine-opaque |
| check modules | six TIDMAD-rostered checks (`amplitude_collapse`, `output_diversity`, `output_std`, `pearson_dispersion`, `per_file_output_std`, `spectral_peak_ratio`) + three generic view-based checks (`sample_dispersion_floor`, `categorical_distinct_symbols`, `categorical_dominant_fraction`) |

## Inputs

Framework policy (`configs/health_checks.yaml` — policy ONLY) + a task health
config (TIDMAD's ships at `configs/task_health/tidmad.yaml`; an external task
supplies its own anywhere on disk); run-level inputs that are deliberately
CLI, not YAML (`--health_gate_enabled`, `--health_gate_files`); deliverable
peeks and views.

## Outputs

`GateResult`s with per-check verdicts; a resolved `GateAction`; persisted
`PersistedHealthGateResult`s on the experiment record; the pinned
`health_checks_effective.yaml`.

## Owned semantics

- **Applicability is decided before invocation** — an inapplicable check opens
  no artifact, never blocks, and *never counts as a pass*; `error` on a
  blocking check fails closed.
- **The verdict boundary**: unreadable/empty evidence ⇒ `ERROR`; read-but-
  invalid evidence (non-finite sample, out-of-range symbol) ⇒ `FAILED`.
- **Disposition is the task's whole policy choice**; role, cadence,
  short-circuit and actions are derived from framework policy, so task and
  framework cannot disagree.
- **Declaration-driven injection**: fact axes reach checks only through the
  frozen injectable-parameters table; a roster hand-authoring an injected key
  is a deterministic `HealthCompositionError`.
- Roster **declaration order is semantic**, and the composed effective config
  is content-addressed (plugin digests included) — editing any of it forks
  the workspace identity.

## Non-owned semantics

- **Where gates fire** (tuner round boundaries) and what an action does to the
  round → the tuner node. Never inside `score_vector`.
- Threshold *values* and failure prose → the task's health config.
- The lock that pins the composed sha → [`core/`](../../core/README.md).

## Extension points

A task adds a check with **no SIDERIUS edit**: write a `HealthCheckSkill`-
conformant class in your own file, `register()` it at module scope, and list
the file under `plugins:` in your task health config. View providers register
the same way. **The `__init__.py` import list is the built-ins' bootstrap, NOT
the extension path** (censused). Prefer the shipped generic checks first:
`sample_dispersion_floor` (continuous), `categorical_distinct_symbols` /
`categorical_dominant_fraction` (classification).

🟡 Health families on the **composed chain path** are still not demonstrated —
this is now *landed, declared debt*, not an unmerged-work gap: PR-12d (landed
`84d74280`) records finding **A1** — HealthGate evaluation lives only inside
the legacy `ANCHOR_NORMALIZED` branch, so a composed run fires **zero** gates,
and the `G-12d` PASS lists deliberately did not require them. The 08c evidence
ran through the D14 direct-execution runners and stands unchanged. Do not
claim composed-path enforcement beyond what a real run has shown.

## State and filesystem effects

Writes `{workspace}/health_checks_effective.yaml` atomically; external plugin
content digests join the pinned sha (an edited plugin fails a resume closed).
Registries are process-global with run-scoped plugin loading.

## Failure modes

| refusal | meaning |
|---|---|
| `HealthCompositionError` | hand-authored injected key, or both framework and task declared a roster |
| `HealthPluginError` / `HealthPluginRunScopeError` | plugin file missing/raising, registration collision, or a different plugin set already loaded this process |
| view materialization error | `CheckVerdict.ERROR` — never converted to `inapplicable` or a pass |
| effective-config sha mismatch on resume | the workspace refuses silently-changed health semantics |

## Files normally edited

For a task: **nothing here** — your own health config + plugin files. For the
framework: a new built-in check module (+ its bootstrap import, tests, and the
health-core census), or policy in `configs/health_checks.yaml`.

## Files normally NOT edited

`registry.py` semantics; the verdict/action vocabularies in `schemas.py`
(persisted records depend on them); the injectable-parameters table without a
task that forces a new axis; `_composition.py`'s refusal paths.

## Minimal example

A complete external check (place in your task package, list under `plugins:`):

```python
from typing import Any, ClassVar
from execute_tools.health_checks.registry import register
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration, CheckVerdict, HealthCheckContext, HealthCheckResult,
)

class NonEmptyOutputCheck:
    name: ClassVar[str] = "my_task_non_empty_output"
    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        required_context_inputs=("denoised_source",),
    )

    def run(self, ctx: HealthCheckContext,
            config: dict[str, Any] | None = None) -> HealthCheckResult:
        n = len(ctx.denoised_paths)          # {partition_index: deliverable path}
        ok = n > 0
        return HealthCheckResult(
            check_name=self.name, passed=ok,
            reason="" if ok else f"{self.name}: no deliverable to inspect",
            metrics={"n_deliverables": n},
            verdict=CheckVerdict.PASSED if ok else CheckVerdict.ERROR,
        )

register(NonEmptyOutputCheck())
```

`sample_dispersion_floor.py` is the reference implementation for a
view-consuming check, including the §3.2a error/failed boundary.

## Related tests

`tests/unit/execute_tools/health_checks/` — the health-core census, verdict
manifest, composition refusals, plugin-binding lifecycle, and the per-check
suites.
