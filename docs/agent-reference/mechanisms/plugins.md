# Plugins, identity and provenance

**Semantic owners**: `workflows/task_composition.py` (manifest-declared),
`ml_models/plugin_loader.py` and `agent_generated/_loss_loader.py`
(directory-scanned), `execute_tools/health_checks/_plugin_binding.py` (health)
**Status**: ✅ Current, with one stated propagation gap

---

## Purpose

Load task-owned code at run scope, and pin its identity so that a result's
provenance names exactly what produced it.

## The families

| family | protocol / contract | declared where | loaded how | out-of-tree |
|---|---|---|---|:---:|
| **TaskDataPath** | `Protocol`, 4 methods + `task_data_path_id` | manifest `task_data_path` | `_load_symbol` + `register_task_data_path` | ✅ via `file:` |
| **TaskScopeCapability** | `Protocol`, 4 methods | *not a section* — an optional sibling on the same object | duck-typed callability | ✅ rides the data path |
| **TaskTrialAnchoring** | `Protocol`, 1 method | same object | `declares_trial_anchoring` TypeGuard | ✅ |
| **EvaluationMetric** | ABC | manifest `metric` / `secondary_metrics[i]` | `_load_symbol`, instantiated with the declared spec, type-checked | ✅ via `file:` |
| **ScoreabilityContract** | `BaseModel, ABC` | inside the metric declaration JSON | Pydantic, `SerializeAsAny` | ✅ shipped in the metric plugin |
| **HealthCheckSkill** | `Protocol` | task health YAML `roster[].check` + `plugins:` | file/dir executed; plugin calls public `register()` | ✅ |
| **HealthViewProvider** | `Protocol` | task health YAML `providers:` | resolved against what plugins registered | ✅ |
| **Model plugin** | attribute contract | **not in the manifest** | directory scan | ✅ env var only |
| **Loss plugin** | attribute contract | **not in the manifest** | directory scan | ✅ env var only |
| **DeliverableNaming** | `BaseModel` — a *declaration*, not code | manifest `deliverable` | direct Pydantic construction | ❌ no `module:`/`file:` form |

### The two directory-scanned families

Model and loss plugins are the only kinds unreachable from the manifest:

```
SIDERIUS_PLUGIN_DIRS   os.pathsep-separated   → PLUGIN_MODEL_TYPE / PLUGIN_CONFIG_CLASS / PLUGIN_MODEL_CLASS (+ PLUGIN_OUTPUT_TYPE)
SIDERIUS_LOSS_DIRS     deliberately separate  → PLUGIN_LOSS_TYPE / PLUGIN_LOSS_CONFIG_CLASS / PLUGIN_LOSS_CLASS (+ PLUGIN_LOSS_TARGET_DTYPE)
```

They extend `MODEL_REGISTRY` / `LOSS_REGISTRY` at runtime through
`CapabilityRegistry`, and each run stages its plugins into
`{workspace}/plugins/{run_name}/`.

> ⏳ A pack's plugin directory does **not** currently propagate to a composed
> run's children — the two example harnesses set the env var themselves, and the
> chain launchers contain zero injections. 🧭 PR-12d (seam P).

## `module:` versus `file:`

```yaml
module: my_package.module   # importable; NO content digest
file:   ../plugins/thing.py # arbitrary path; content sha256 joins the fingerprint
```

Exactly one, never both, never neither.

`file:` is the mechanism by which a task lives outside the SIDERIUS tree.

## Module namespace isolation

Three distinct `sys.modules` prefixes prevent stem collisions between unrelated
plugin files that happen to share a filename:

| prefix | family |
|---|---|
| `siderius_task_composition_plugin_` | manifest-declared symbols |
| `siderius_plugin_` | model plugins |
| `siderius_health_plugin_` | health plugins |

## Identity and provenance

The rules that make provenance trustworthy:

- **A file-declared plugin's content sha256 joins the run's semantic
  fingerprint.** Editing it between a run and its resume is detected.
- **Absolute paths are never hashed.** The same package at two locations has one
  identity — which is what makes an out-of-tree package relocatable.
- **Health plugin digests join `health_config_sha256`**, so an edited health
  plugin fails a resume closed. Host paths are again excluded.
- **The transported identity is the value captured at *registration*, never a
  fresh read of the plugin file.** Re-deriving it at spawn time reads whatever is
  on disk *now*, so the pin would follow the very edit it exists to catch.
- **A registry hit is not identity proof.** The parent pins a per-family content
  identity; the child verifies it **before consuming**.
- **A child MISS must stay a membership test**, never an exception to catch —
  otherwise a refusal silently degrades into a fallback.

## Registration lifecycle

Two-phase rule: same id + same content ⇒ idempotent; same id + different content
⇒ refuse. A run-scoped registration overlay handles per-run additions.

A plugin that raises during registration is rolled back
(`execute_tools/task_registration_scope.py::registration_rollback`).

## Directory-scan conventions

Directory scanners skip `_`-prefixed members. Pack-local plugins are therefore
loaded only by explicit `kind: file` refs — which is how an example pack ships
plugins next to a scanned directory without them being picked up implicitly.

## Fail-closed behaviour

| condition | result |
|---|---|
| both / neither of `module:` and `file:` | `TaskCompositionError` |
| declared `id` ≠ implementation's own id | `TaskCompositionError` |
| loaded symbol is the wrong type | `TaskCompositionError` |
| same id, different content, already registered | refused |
| plugin raises during registration | rolled back, run refused |
| plugin content changed since the workspace was locked | resume fails at startup |

## Source map

| concern | location |
|---|---|
| symbol loading, digesting | `workflows/task_composition.py:420-514` |
| fingerprint | `:961-1046` |
| registration rollback | `:494-506`, `execute_tools/task_registration_scope.py` |
| data-path registry | `execute_tools/task_data_path.py:668-691` |
| model plugin loader | `ml_models/plugin_loader.py:9-13, 32, 110-199` |
| loss plugin loader | `agent_generated/_loss_loader.py:8-10, 26-27, 99-136` |
| health plugin binding | `execute_tools/health_checks/_plugin_binding.py:34-37, 86-91` |
| health plugin refs | `_task_health_config.py:171-191` |

## Related

- [Composition](composition.md) · [Execution](execution.md) · [Health gates](health-gates.md)
- [Define a task](../../guides/define-a-task.md)
