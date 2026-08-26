# Plugins, identity and provenance

**Semantic owners**: `workflows/task_composition.py` (manifest-declared),
`ml_models/plugin_binding.py` (declared model/loss roots),
`ml_models/plugin_loader.py` and `agent_generated/_loss_loader.py`
(directory-scanned), `execute_tools/health_checks/_plugin_binding.py` (health)
**Status**: ✅ Current

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
| **ScoreabilityContract** | `BaseModel, ABC` | inside the metric declaration JSON, by `contract_id` | rebuilt from a **closed** declaration lookup (`_SCOREABILITY_CONTRACT_TYPES`, `execute_tools/evaluation_metric.py:687`) | ❌ closed vocabulary, not a plugin surface — a new contract class is a framework contribution; an unknown id is refused by name |
| **HealthCheckSkill** | `Protocol` | task health YAML `roster[].check` + `plugins:` | file/dir executed; plugin calls public `register()` | ✅ |
| **HealthViewProvider** | `Protocol` | task health YAML `providers:` | resolved against what plugins registered | ✅ |
| **Model plugin** | attribute contract | manifest `model_plugins` (`dir` + `require`) *or* env var | directory scan over the declared/injected roots | ✅ |
| **Loss plugin** | attribute contract | manifest `loss_plugins` (`dir`) *or* env var | directory scan; resolved by `loss_name` at training time | ✅ |
| **Objective (authoritative loss)** | the loss plugin's own self-declaration symbol | manifest `objective.implementation` | `_load_symbol` returns the declared loss name → a validated `LossConfig` | ✅ via `file:` |
| **DeliverableNaming** | `BaseModel` — a *declaration*, not code | manifest `deliverable` | direct Pydantic construction | ❌ no `module:`/`file:` form |

### The two directory-scanned families

Model and loss plugins resolve by directory scan. A composed run declares the
roots in the manifest (`model_plugins:` / `loss_plugins:` — PR-12d seams P/D4c,
resolved by `resolve_declared_model_plugins` with content identities pinned);
an un-composed run supplies them by environment variable:

```
SIDERIUS_PLUGIN_DIRS   os.pathsep-separated   → PLUGIN_MODEL_TYPE / PLUGIN_CONFIG_CLASS / PLUGIN_MODEL_CLASS (+ PLUGIN_OUTPUT_TYPE)
SIDERIUS_LOSS_DIRS     deliberately separate  → PLUGIN_LOSS_TYPE / PLUGIN_LOSS_CONFIG_CLASS / PLUGIN_LOSS_CLASS (+ PLUGIN_LOSS_TARGET_DTYPE)
```

They extend `MODEL_REGISTRY` / `LOSS_REGISTRY` at runtime through
`CapabilityRegistry`, and each run stages its plugins into
`{workspace}/plugins/{run_name}/`.

### The generated-capability library (arXiv P1)

Cross-run durable state — promoted model/loss plugins and the capability
index (`_capability_index.json`) — lives under ONE resolved, non-checkout
**generated-library root** (`core/generated_library.py`):

```
SIDERIUS_GENERATED_LIBRARY_DIR   absolute path; "~" expanded; empty = unset;
                                 non-empty RELATIVE path is refused loudly
    else
~/.siderius/generated_library    per-user default (the ~/.siderius precedent)
```

Layout mirrors the old checkout layout: `models/`, `losses/`,
`_capability_index.json`. Promotion writes here; startup preloads and the
no-env plugin/loss scans read here FIRST. The repository checkout's
`agent_generated/` is a **read-only legacy fallback** (scanned after the
resolved root; the index is read only until the resolved index exists, and
its rows are carried into the resolved index by the first write) — a
pre-migration checkout keeps resolving everything it promoted, and **no
production path writes into the checkout**. Each run's lock records the
resolved root as `generated_library` provenance (`{root, source}`;
recorded, never compared).

> ✅ A pack's declared plugin roots propagate to a composed run's children
> automatically (PR-12d seam P): `core/subprocess_env.py::subprocess_env`
> **unions** the run-scoped declared roots into `SIDERIUS_PLUGIN_DIRS` /
> `SIDERIUS_LOSS_DIRS` at every child spawn — a child or runtime default may
> extend the set the run declared, but can never overwrite or drop it. The
> ambient environment is deliberately *not* a third union source: with no
> binding, the inherited value passes through byte-unchanged, so un-composed
> plugin resolution is observably identical to the pre-seam behaviour.

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
| symbol loading, digesting | `workflows/task_composition.py:451-547` (`_load_symbol`) |
| fingerprint | `:1509` (`compute_semantic_fingerprint`) |
| declared model/loss roots | `:1008` / `:1084`; binding + identities in `ml_models/plugin_binding.py` |
| child env union | `core/subprocess_env.py::subprocess_env` |
| registration rollback | `:525-527`, `execute_tools/task_registration_scope.py:114` |
| data-path registry | `execute_tools/task_data_path.py:612-743` (`register_task_data_path` `:682`) |
| model plugin loader | `ml_models/plugin_loader.py:9-13, 32, 110-199` |
| loss plugin loader | `agent_generated/_loss_loader.py:8-10, 26-27, 99-136` |
| health plugin binding | `execute_tools/health_checks/_plugin_binding.py:34-37, 86-91` |
| health plugin refs | `_task_health_config.py:171-191` |

## Related

- [Composition](composition.md) · [Execution](execution.md) · [Health gates](health-gates.md)
- [Define a task](../../guides/define-a-task.md)
