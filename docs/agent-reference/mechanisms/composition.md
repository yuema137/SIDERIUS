# Task composition

**Semantic owner**: `workflows/task_composition.py`
**Status**: ✅ Current

---

## Purpose

Resolve a task's declared semantics from one YAML manifest, and bind them for the
duration of a run so that every downstream consumer reads the same authority.

## Non-responsibilities

- It does **not** scan for or import model/loss plugin *code* — it resolves the
  task's **declared roots** (`model_plugins:` / `loss_plugins:`, PR-12d seams
  P/D4c) into a run-scoped binding with pinned content identities; the actual
  loading stays with the directory scanners, reached through the
  `SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS` env union at spawn. See
  [plugins](plugins.md).
- It does **not** bind the Health family or the interpretation blocks. Both are
  passed explicitly rather than ambiently — Health into `build_run_invariants`,
  interpretation blocks as a field on `InterpretationInput`.
- It does **not** interpret a task's `topology` payload or scope vocabulary.
- It performs no fallback. Every failure path raises; nothing degrades to TIDMAD.

## Position in the workflow

The launcher composes, then enters the binding context around the entire run:

```
run_one_iteration.py: compose_run_task_bindings(manifest)
  → bind_run_task_composition(composition, physical_data_root=args.data_dir)
    → run_workflow(...)
      → verify_composition_is_bound(task_composition)   # first thing
```

Passing `None` to the binding context creates no task binding. It does not
make production execution usable without a composition: task-data and metric
resolvers refuse missing authority rather than selecting a scientific default.

## Inputs

A manifest path. The typed manifest declares required and optional sections;
unknown keys are refused. See the [composition reference](../../reference/task-composition.md)
for the table.

## Outputs

`RunTaskComposition`, a frozen dataclass carrying the resolved authorities, plus
the run-scoped bindings activated by `bind_run_task_composition`.

## Main lifecycle

1. `_read_manifest` — parse, refuse unknown keys, check required keys.
2. Per-section resolvers — load declaration files; import (`module:`) or execute
   by path (`file:`) each symbol; type-check the result.
3. `compute_semantic_fingerprint` over the declared content.
4. `bind_run_task_composition` activates every binding on **one `ExitStack`**, so
   any failure unwinds all of them in reverse.
5. `verify_composition_is_bound` asserts the bindings are live — identity, not
   equality, for the data path, dataset profile and metric; ordered equality for
   secondaries; a non-`None` `physical_data_root`; a non-empty task description.

A half-composed run is fatal (`CompositionNotBoundError`), never degraded.

## Extension points

- Any section naming a symbol accepts `module:` **or** `file:` — exactly one.
  `file:` is the out-of-tree path, and the file's content sha256 joins the
  semantic fingerprint.
- `task_data_path.id` is an optional cross-check against the implementation's own
  `task_data_path_id`; a mismatch refuses.

## Invariants

- **Unknown keys refuse.** A misspelled section never silently takes a default.
- **Paths resolve against the manifest's directory**, never the cwd — packages
  are relocatable.
- **Absolute paths are never hashed** into the fingerprint, so the same package at
  two locations has one identity.
- **`task_health` may not be omitted.** The uncomposed
  `LEGACY_OMITTED` state is neutral and is not valid in a manifest; a composition
  may only express `EXPLICIT_NONE`
  (`none: true`) or a path.
- **`secondary_metrics` order is semantic** — it participates in the fingerprint
  and the record stamp.
- **One error type** — `TaskCompositionError` — for every fail-closed branch.

## Fail-closed behaviour

| condition | result |
|---|---|
| unknown manifest key | `TaskCompositionError` |
| missing required section | `TaskCompositionError` |
| both `module:` and `file:`, or neither | `TaskCompositionError` |
| `task_data_path.id` ≠ implementation id | `TaskCompositionError` |
| metric implementation is not an `EvaluationMetric`, or rewrites the declared id | `TaskCompositionError` |
| duplicate secondary id, or collision with the primary | `TaskCompositionError` |
| `task_health` declaring both `none: true` and `config:` | `TaskCompositionError` |
| composed run without `--data_dir` | `CompositionDataRootMissing`, before any LLM/GPU work |
| bindings not actually live | `CompositionNotBoundError` |

## Provenance

The semantic fingerprint is stamped on every persisted record. Two records with
the same fingerprint were produced under the same declared semantics — including
the same file-plugin contents, since those hashes are folded in.

## Deliverable-absence semantics

A manifest either declares indexed `deliverable` naming or supplies a task
data path with its own `deliverable_name`. Omitting both is refused during
composition. Own-naming tasks may use their codec without an indexed template;
`resolve_deliverable_naming` refuses that inapplicable capability, while
`active_deliverable_naming` returns `None`. These decisions are based on declared
capability, never task identity.

## Source map

| concern | location |
|---|---|
| key sets | `workflows/task_composition.py:96-121` |
| resolved carrier (`RunTaskComposition`) | `:183` |
| manifest read / validate | `:340-383` |
| path resolution | `:402` |
| symbol loading (`module:` / `file:`) | `:451-600` |
| companion-symbol refusal (`_require_companion_symbols`) | `:602` |
| per-section resolvers | `:787-1786` |
| declared model/loss roots + objective | `:1089` / `:1165` / `:1301` |
| semantic fingerprint | `:1595` |
| compose entrypoint | `:1970` |
| run-scoped binding | `:2237` |
| post-condition guard | `:2333` |
| shipped manifests | `configs/task_composition/{quickstart,synthetic_masked_regression}.yaml` |

## Related

- [Composition reference](../../reference/task-composition.md) — the section table
- [Plugins](plugins.md) — loading and identity
- [Metrics](metrics.md), [Health gates](health-gates.md), [Data path and scope](data-path-and-scope.md)
