# Task composition

**Semantic owner**: `workflows/task_composition.py`
**Status**: ✅ Current

---

## Purpose

Resolve a task's declared semantics from one YAML manifest, and bind them for the
duration of a run so that every downstream consumer reads the same authority.

## Non-responsibilities

- It does **not** load model or loss plugins — those come from
  `SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS`. See [plugins](plugins.md).
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

`composition is None` is a **total no-op** — no ContextVar is set and the run
takes the ⚠ legacy un-composed path with byte-identical child argv.

## Inputs

A manifest path. Ten possible sections, five required; unknown keys refused by
set difference. See the [composition reference](../../reference/task-composition.md)
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
- **`task_health` may not be omitted.** Omission is `LEGACY_OMITTED`, which
  resolves TIDMAD's family; a composition may only express `EXPLICIT_NONE`
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

## Known hazard

⚠ Omitting `deliverable` resolves to the shipped TIDMAD naming, and the cleanup
glob derived from it can match files the run never wrote. Narrowing is owned by
the unmerged PR-12d (seam E / F-A4-1).

## Source map

| concern | location |
|---|---|
| key sets | `workflows/task_composition.py:94-123` |
| resolved carrier | `:177-296` |
| manifest read / validate | `:309-352` |
| path resolution | `:371-377` |
| symbol loading (`module:` / `file:`) | `:420-514` |
| per-section resolvers | `:532-1083` |
| semantic fingerprint | `:961-1046` |
| compose entrypoint | `:1308` |
| run-scoped binding | `:1485-1565` |
| post-condition guard | `:1568-1628` |
| shipped manifest | `configs/task_composition/tidmad.yaml` |

## Related

- [Composition reference](../../reference/task-composition.md) — the section table
- [Plugins](plugins.md) — loading and identity
- [Metrics](metrics.md), [Health gates](health-gates.md), [Data path and scope](data-path-and-scope.md)
