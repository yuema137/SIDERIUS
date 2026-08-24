# Task composition reference

**Audience**: anyone authoring or debugging a composition manifest.
**Authority**: `workflows/task_composition.py` — `_MANIFEST_KEYS` /
`_REQUIRED_KEYS` (`:94-123`), resolvers (`:420-1083`),
`compose_run_task_bindings` (`:1308`), `bind_run_task_composition` (`:1485`).

If this page and that module disagree, the module is right. It is the single
authority; this page is a human-readable projection of it.

---

## What a manifest is

One YAML file. You point an entrypoint at it with `--task_composition`, and its
declarations are bound for the whole run.

Two properties worth knowing before you start:

- **Unknown keys are refused, not ignored.** A misspelled section name fails the
  run at startup rather than silently taking a default.
- **Paths resolve against the manifest's own directory**, never the working
  directory. A package is therefore relocatable.

There is **no `version` field**. (Recorded as a known gap — see
[DOC-F3](../audit/documentation_gap_audit.md#12-findings-recorded-deliberately-not-fixed-here).)

## The ten sections

| section | required | what it declares | absence means |
|---|:---:|---|---|
| `task_data_path` | ✅ | how your data is read and deliverables written | **run refused** |
| `dataset_profile` | ✅ | partition count, anchor set, health peek set, opaque topology | **run refused** |
| `metric` | ✅ | the primary metric: declaration + implementation | **run refused** |
| `task_config` | ✅ | `task_description` + `forward_contract` | **run refused** |
| `task_health` | ✅ *(as a statement)* | the health family, or an explicit `none: true` | **run refused** — see below |
| `secondary_metrics` | — | a list of observational metrics | the run has none: no record keys, no rendered bytes |
| `proposal_blocks` | — | task science for the proposer's prompts | the proposer gets **no** task science |
| `implementor_blocks` | — | task science for the implementor's prompts | the implementor renders nothing |
| `interpretation_blocks` | — | task science for the interpreter's prompts | the interpreter renders no task blocks |
| `deliverable` | — | deliverable file naming | ⚠ **silently resolves to TIDMAD's naming template** |

### Why `task_health` is required but may say "none"

Omitting the section and declaring `none: true` are *different states*.

Omission is the legacy state, and the legacy state resolves **TIDMAD's health
family**. A composition is therefore forbidden from expressing it — because "I
said nothing" would silently give an unrelated task TIDMAD's thresholds. Saying
`none: true` is a named absence and is safe.

```yaml
task_health:
  none: true        # explicit: this task declares no health family
```

Declaring both `none: true` and `config:` is refused.

### The one hazardous default

`deliverable` is the only optional section whose absence means something other
than "nothing". Omit it and the run uses the shipped TIDMAD naming template —
including the cleanup glob derived from it, which can match files the run never
wrote.

**Declare it explicitly for any non-TIDMAD task.** Narrowing this so absence
means clean emptiness is owned by the unmerged PR-12d
([DOC-F1](../audit/documentation_gap_audit.md#12-findings-recorded-deliberately-not-fixed-here)).

## Declaring code: `module:` versus `file:`

Any section that names an implementation takes exactly one of:

```yaml
task_data_path:
  module: my_package.data_path      # importable dotted module
  symbol: MyTaskDataPath
  id: my_task                       # optional cross-check against the class's own id
```

```yaml
task_data_path:
  file: ../plugins/my_data_path.py  # arbitrary path — out-of-tree
  symbol: MyTaskDataPath
```

Supplying both, or neither, is refused.

A **`file:` reference is how a task lives outside the SIDERIUS tree.** Its content
is hashed and that hash joins the run's semantic fingerprint, so editing the
plugin between a run and its resume is detected rather than silently accepted.
`module:` references carry no digest.

The `id:` on `task_data_path` is optional and is only a cross-check: if given, it
must equal the implementation's own declared id, and a mismatch is refused.

## Section shapes

```yaml
task_data_path:
  module: execute_tools.tidmad_data_path      # or `file:`
  symbol: TidmadTaskDataPath
  id: tidmad                                   # optional

dataset_profile:
  config: ./declared/dataset_profile.json

metric:
  declaration: ./declared/metric_spec.json
  implementation:
    module: execute_tools.evaluation_metric    # or `file:`
    symbol: TidmadDenoisingMetric

secondary_metrics:                             # optional; ORDER IS SEMANTIC
  - declaration: ./declared/metric_macro_f1.json
    implementation:
      file: ./plugins/my_metrics.py
      symbol: MacroF1Metric

task_health:
  config: ./declared/task_health.yaml          # or `none: true`

task_config:
  config: ./declared/task_config.yaml

proposal_blocks:                               # optional
  config: ./declared/proposal_blocks.yaml
implementor_blocks:                            # optional
  config: ./declared/implementor_blocks.yaml
interpretation_blocks:                         # optional
  config: ./declared/interpretation_blocks.yaml

deliverable:                                   # optional — but declare it
  prefix: my_task_output
  extension: npz
  index_width: 4
```

Notes:

- `secondary_metrics` **order is semantic** — it participates in the composition
  fingerprint and the record stamp. Duplicate ids, or a secondary whose id
  collides with the primary's, are refused.
- A metric implementation must be an `EvaluationMetric` and may not rewrite the
  `id` declared in its declaration file.
- `deliverable` is `extra="forbid"`: a misspelled key is refused rather than
  falling back to a template.
- An empty `task_description` is refused.

## Beyond the manifest: `--data_dir`

A composed run **requires** `--data_dir`. It fails closed before any LLM call or
GPU work with `CompositionDataRootMissing`. Without it every child subprocess
would fall back to the import-time TIDMAD data directory.

## Things the manifest does *not* declare

| thing | how it is supplied instead |
|---|---|
| model plugins | `SIDERIUS_PLUGIN_DIRS` environment variable (directory scan) |
| loss / objective plugins | `SIDERIUS_LOSS_DIRS` environment variable |
| framework health policy | `configs/health_checks.yaml` |
| data scope, budgets, rounds | CLI flags — see [entrypoints](entrypoints.md) |

The model/loss plugin split is worth remembering: those two families are the only
plugin kinds **not** reachable from the manifest.

## What happens at composition time

1. The manifest is read; unknown keys refuse; required keys are checked.
2. Each section resolves — files loaded, symbols imported or executed by path,
   types checked.
3. A semantic fingerprint is computed over the declared content (never absolute
   paths).
4. `bind_run_task_composition` activates every binding on one exit stack, so any
   failure unwinds all of them.
5. `verify_composition_is_bound` asserts the bindings are actually live. A
   half-composed run is fatal, not degraded.

If no manifest is supplied, none of this happens and the run takes the ⚠ legacy
un-composed path with byte-identical child argv.

## Worked example

`configs/task_composition/tidmad.yaml` is the shipped reference manifest. It
declares eight of the ten sections — no `secondary_metrics` (TIDMAD has none) and
no `deliverable` (it *is* the TIDMAD default). Nothing in it is special-cased:
the id `tidmad` is an ordinary declared id and the built-in metric class is
reached by the same `module:`/`symbol:` mechanism an external task uses.

---

## Next

- [Define your own task](../guides/define-a-task.md)
- [Configuration map](configuration-map.md) — which file is owned by whom
- [Composition mechanism reference](../agent-reference/mechanisms/composition.md) — for implementers
