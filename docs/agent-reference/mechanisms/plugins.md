# Plugins, identity and provenance

**Semantic owners**: `workflows/task_composition.py` (manifest-declared),
`ml_models/plugin_binding.py` (declared model/loss roots),
`ml_models/plugin_loader.py` and `ml_models/loss_plugin_loader.py`
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
| **ScoreabilityContract** | `BaseModel, ABC` | metric declaration JSON `contract_id` plus optional manifest `scoreability_contracts` mapping | rebuilt from the task-declared implementation mapping or supported framework contracts | ✅ via `file:`; an unknown undeclared id refuses |
| **HealthCheckSkill** | `Protocol` | task health YAML `roster[].check` + `plugins:` | file/dir executed; plugin calls public `register()` | ✅ |
| **HealthViewProvider** | `Protocol` | task health YAML `providers:` | resolved against what plugins registered | ✅ |
| **Model plugin** | attribute contract | manifest `model_plugins` (`dir` + `require`) *or* env var | directory scan over the declared/injected roots | ✅ |
| **Loss plugin** | attribute contract | manifest `loss_plugins` (`dir`) *or* env var | directory scan; resolved by `loss_name` at training time | ✅ |
| **Objective (authoritative loss)** | the loss plugin's own self-declaration symbol | manifest `objective.implementation` | `_load_symbol` returns the declared loss name → a validated `LossConfig` | ✅ via `file:` |
| **DeliverableNaming** | `BaseModel` — a *declaration*, not code | manifest `deliverable` | direct Pydantic construction | ❌ no `module:`/`file:` form |
| **Custom adaptor** | `adapt(inputs, params, ctx)` + `AdaptorManifest` | external project `adaptor.json` | captured `core.local_code` package, supervised child; admitted by `python -m tools.adaptors` | ✅ (never in framework source) |

### Custom adaptors

A custom adaptor is declared by its own manifest (`siderius.adaptor-manifest/v1`),
not by the task composition manifest. Its identity is the captured member
package digest; it runs only in a supervised child that verifies member pins
before executing; admission writes
`<project>/.siderius/adaptors/<id>/<identity>.admission.json`. A COMBINE may emit
only `CUSTOM_EMITTABLE` contracts with framework-stamped `PROTECTED_FIELDS`.
Workflow execution is not available yet. Contract:
[custom adaptor contract](../../../src/workflows/custom_adaptors/custom-adaptor-contract.md).

### The two directory-scanned families

Model and loss plugins resolve by directory scan. A composed run declares the
roots in the manifest (`model_plugins:` / `loss_plugins:` — PR-12d seams P/D4c,
resolved by `resolve_declared_model_plugins` with content identities pinned);
an un-composed run supplies them by environment variable:

```
SIDERIUS_PLUGIN_DIRS   os.pathsep-separated   → PLUGIN_MODEL_TYPE / PLUGIN_CONFIG_CLASS / PLUGIN_MODEL_CLASS (+ PLUGIN_OUTPUT_TYPE)
SIDERIUS_LOSS_DIRS     deliberately separate  → PLUGIN_LOSS_TYPE / PLUGIN_LOSS_CONFIG_CLASS / PLUGIN_LOSS_CLASS (+ PLUGIN_LOSS_TARGET_DTYPE)
```

They extend `MODEL_REGISTRY` / `LOSS_REGISTRY` through their family loaders.
Generated model source is staged into `{workspace}/plugins/{run_name}/`;
current declared package members retain their original captured source path.
The capability index records available capabilities; it is not code identity.

### Legacy module admission rollback

Legacy model and loss loaders temporarily publish a filename-derived module name
so imports and source inspection work during admission. If import or metadata
admission fails, including missing required symbols or an exception, they restore
the exact prior `sys.modules` binding, or remove the temporary entry when no
binding existed. Public registration therefore retains the previously admitted
class and its inspectable source when the rejected same-basename candidate is
a separate file and the original source remains unchanged.
Successful admission still publishes the replacement module. Model inspection
through `inspect_model_plugin` restores its entry even after successful inspection.

This transaction covers the loader-owned module entry, not arbitrary side effects
inside plugin code. It does not snapshot or restore files overwritten on disk,
isolate concurrent same-basename imports, or keep
multiple successfully admitted legacy modules under one module name. Captured
package acquisition retains its separate source identity and rollback contract.

### Custom-loss target representation

`agent/schemas/custom_loss_target.py` resolves native target routing from the
task's custom-loss capability contract. The supported canonical representations
are `int64` (`PLUGIN_LOSS_TARGET_DTYPE = "long"`) and `float32`
(`PLUGIN_LOSS_TARGET_DTYPE = "float"`). Other canonical representations fail
explicitly; the framework does not silently narrow them or infer dtype from a
task name, tensor shape or loss name. Applicability must admit the selected cast
for both the supervision target and the loss input.

Generated loss metadata follows that contract. The numerical probe applies the
same target conversion as native training and validation. A contract-aware
plugin must declare compatible target metadata; missing, invalid or conflicting
metadata is refused. A present but malformed capability contract is an error,
not an uncontracted legacy plugin. Where the caller supplies the composed task's
expected contract, loading checks it before executing the candidate module.

A loadable legacy plugin with no capability contract may retain the historical
`long` default when its target declaration is absent. An unavailable custom loss
does not establish a dtype and cannot silently select that default. Built-in
loss routing is unchanged. Correcting a plugin changes its code identity: retain
old evidence and use a new explicitly configured workspace rather than replacing
the selected code inside an existing run.

### Custom-loss normalization declarations

`PLUGIN_LOSS_REDUCTION` optionally declares `mean` or `sum`. Training-history
comparability consumes that declaration; it does not infer normalization from
the loss name or implementation. Missing, `None` and unsupported declarations
are treated as undeclared by the loader.

Both in-memory registration and filesystem resolution replace reduction
metadata only after successful plugin admission. A replacement without a valid
declaration clears the previous value; a failed load preserves the selected
registry state. This does not authorize changing an immutable selected package
or rewriting an existing workspace identity.

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

Without `code_package`, these existing `sys.modules` prefixes prevent stem
collisions between unrelated plugin files:

| prefix | family |
|---|---|
| `siderius_task_composition_plugin_` | manifest-declared symbols |
| `siderius_plugin_` | model plugins |
| `siderius_health_plugin_` | health plugins |

With the optional [package declaration](../../reference/task-composition.md),
selected file consumers share a finite namespace across families. Relative
imports execute only declared captured members, so helper-defined classes have
one identity within a package. Directory-roster rules remain unchanged; this
does not add recursive model/loss discovery. See the
[loading/transport owner](../../../src/core/local_code/README.md).

## Identity and provenance

The rules that make provenance trustworthy:

- **A file-declared plugin's content sha256 joins the run's semantic
  fingerprint.** Editing it between a run and its resume is detected.
- **A selected package member additionally pins the whole declared set.**
  Editing a helper changes every selected member's package identity, even if
  the entry file is unchanged. Parent execution and validator entry review use
  captured bytes; child startup verifies all original member pins.
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
| loss plugin loader | `ml_models/loss_plugin_loader.py` |
| health plugin binding | `execute_tools/health_checks/_plugin_binding.py:34-37, 86-91` |
| health plugin refs | `_task_health_config.py:171-191` |
| custom adaptor manifest, runner, admission | `workflows/custom_adaptors/`, CLI `tools/adaptors/cli.py` |

## Related

- [Composition](composition.md) · [Execution](execution.md) · [Health gates](health-gates.md)
- [Define a task](../../guides/define-a-task.md)

### Observe the selected model plugin source

`ml_models.plugin_loader.registered_model_plugin_path(model_type, model_class)`
returns the declaration file recorded by the native directory scan or explicit
`register_model_in_memory` call for that exact model class. It returns `None`
when there is no matching registration evidence. `None` does not identify a
builtin; check the installed registry separately.

Use this read-only observation when a deployment needs to capture the selected
plugin. Do not infer the declaration file from `inspect.getfile(model_class)`:
a valid plugin can export a class imported from a helper or installed module.
The query does not change registration or scanning behavior and does not pin
bytes, dependencies, caller identity or training provenance.

### Numerical checks for a captured loss package

`agent.schemas.custom_loss_validation.validate_custom_loss_plugin` accepts an
optional `plugin_path` for a member of the caller's active `bind_code_package`
context. Its captured bytes must match `plugin_src`. The probe uses the native
loss plugin loader, so declared relative dependencies (including imports inside
`forward`) retain their captured package identity. Keep the binding active until
the numerical check returns. Missing package selection or mismatched bytes are
reported as validation errors; this route never falls back to the current file.

Omitting `plugin_path` preserves the assembled single-file check. Both routes
use the same task-owned synthetic pair, scalar/finite checks and gradient checks.
This interface performs candidate execution; deployment callers must establish
their execution boundary before invoking it.

Loss loader results also include `plugin_path`: the selected declaration file,
including when it re-exports a class from another module. This is an observation
of native selection, not permission to read the path in a privileged caller.
Deployment code must match it against its own captured source set. Both explicit
file loading and name lookup provide it; selection precedence is unchanged.
