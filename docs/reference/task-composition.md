# Task composition reference

**Audience**: anyone authoring or debugging a composition manifest.
**Authority**: `workflows/task_composition.py` — `_MANIFEST_KEYS` /
`_REQUIRED_KEYS` (`:96-121`), resolvers (`:706-1643`),
`compose_run_task_bindings` (`:1867`), `bind_run_task_composition` (`:2092`).

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

## The thirteen sections

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
| `model_plugins` | — | the pack's model-plugin root + the model types it must produce | nothing bound; legacy discovery only |
| `loss_plugins` | — | the pack's loss-plugin root | nothing bound; legacy loss discovery only |
| `objective` | — | the task's **authoritative** training objective (overrides the planner) | no override; the planner's choice governs |
| `deliverable` | — | an indexed deliverable filename template | see below — a task that names its own artifacts is **refused** an indexed template, never handed TIDMAD's |

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

### What `deliverable` absence means — four states, keyed on capability

`deliverable` absence is resolved by `resolve_deliverable_naming`
(`execute_tools/deliverable_spec.py:380`), and the discriminator is a
**declared capability** — does the task name its artifacts itself? — never a
task identity:

1. a naming is **bound** (the section was declared) → it is used, composed or
   not;
2. not bound and **not composed** → the legacy path, byte-for-byte unchanged;
3. composed, and the task declares **no** deliverable name of its own → the
   shipped indexed template (this is what TIDMAD's composed manifest resolves);
4. composed, and the task **names its own artifacts** through its data path
   (Pets, DAVIS) → **refused**: no indexed template exists for such a run, and
   handing it TIDMAD's would give the cleanup glob filenames the run never
   wrote.

State 4 closed the old hazard (F-A4-1, PR-12d seam E), under which absence
silently resolved TIDMAD's template for every composed task. The historical
finding record is
[DOC-F1](../audit/documentation_gap_audit.md#12-findings-recorded-deliberately-not-fixed-here).

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

model_plugins:                                 # optional
  dir: ./plugins                               # resolved, content-identity-pinned
  require: [my_reference_model]                # model types this root MUST produce
loss_plugins:                                  # optional
  dir: ./plugins                               # no `require` — losses resolve by name
objective:                                     # optional — the task's authoritative loss
  implementation:
    file: ./plugins/my_exact_loss.py
    symbol: PLUGIN_LOSS_TYPE                   # the plugin's own self-declared loss name

deliverable:                                   # only if the task names artifacts by index
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
| framework health policy | `configs/health_checks.yaml` (owned by the framework, never the task) |
| data scope, budgets, rounds | CLI flags — see [entrypoints](entrypoints.md) |
| the physical data root | `--data_dir` (below) |

Model and loss plugins *are* manifest-declarable (`model_plugins:` /
`loss_plugins:` above). The `SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS`
environment variables remain the un-composed channel — and at every child spawn
the declared roots are **unioned** into them, so a child may add to the set the
run declared but can never drop it.

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
declares eight of the thirteen sections — no `secondary_metrics` (TIDMAD has
none), no `deliverable` (it *is* the shipped indexed default — resolution
state 3 above), no `model_plugins`/`loss_plugins` (TIDMAD's models are the
built-ins plus run-generated plugins) and no `objective` (the planner chooses).
Nothing in it is special-cased: the id `tidmad` is an ordinary declared id and
the built-in metric class is reached by the same `module:`/`symbol:` mechanism
an external task uses. `configs/task_composition/pets.yaml` and `davis.yaml`
are the shipped contrast manifests — both declare `model_plugins:`, and
`davis.yaml` additionally declares `loss_plugins:` and an authoritative
`objective:`.

---

## Next

- [Define your own task](../guides/define-a-task.md)
- [Configuration map](configuration-map.md) — which file is owned by whom
- [Composition mechanism reference](../agent-reference/mechanisms/composition.md) — for implementers
