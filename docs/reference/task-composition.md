# Task composition reference

**Audience**: anyone authoring or debugging a composition manifest.
**Authority**: `workflows/task_composition.py` — `_MANIFEST_KEYS` /
`_REQUIRED_KEYS`, resolvers, `compose_run_task_bindings` and
`bind_run_task_composition`. The optional Python package's capture, import and
transport mechanics live in [`core/local_code`](../../src/core/local_code/README.md).

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

## Manifest sections

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
| `dynamic_observables` | — | quantities observed DURING training, once per epoch | the run observes none: `training_history.observations` stays `{}` |
| `static_observables` | — | quantities read off the TRAINED model after training | the run observes none: no record key, no rendered bytes |
| `parameter_rules` | — | deterministic constraints on configured parameter leaves | no task-declared parameter constraints |
| `code_package` | — | one finite, content-pinned set of task-local Python files | existing independent file loading and identities, without task-relative helper imports |

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

For a `file:` plugin that needs sibling helpers, use the optional
[`code_package` declaration](#shared-task-local-python-code). It adds the
declared helper set to code identity; it does not make `module:` dependencies
content-pinned or turn the consumer repository into an installed package.

The `id:` on `task_data_path` is optional and is only a cross-check: if given, it
must equal the implementation's own declared id, and a mismatch is refused.

## Shared task-local Python code

Use this only when your file plugins share Python modules. Keep the simpler
single-file form when they do not. There is one optional package per composition:

```yaml
code_package:
  root: .                         # relative to this manifest
  files:                          # paths relative to root; explicit, no globs
    - runtime/scope.py
    - runtime/data_path.py
    - plugins/metric.py

task_data_path:
  file: runtime/data_path.py       # existing file references remain manifest-relative
  symbol: MyTaskDataPath
metric:
  declaration: declared/metric.json
  implementation:
    file: plugins/metric.py
    symbol: MyMetric
# Other required task sections are unchanged.
```

`data_path.py` can use `from .scope import MyScope`; `metric.py` can use
`from ..runtime.scope import MyScope`. Both receive the same class object
within that captured package, rather than two independently loaded copies.
The [modular synthetic example](../../examples/synthetic_masked_regression/modular/README.md)
demonstrates this through actual data/metric, model/loss, Health, observable and
scoreability interfaces.

- List every selected Python entry and helper inside the package root. Members
  must be normalized relative `.py` paths with Python-identifier components.
  Duplicate names, traversal, module/package collisions, missing files and
  symlinks escaping the root are refused. Directory scans exclude unlisted
  members; explicitly requesting one refuses instead of falling back.
- Nested and parent-relative imports are supported within that finite set.
  `__init__.py` executes only if explicitly listed; implicit namespace parents
  do not search the filesystem for extra code. Installed framework and
  third-party dependencies still use the checkout's frozen environment.
- Existing `file:`, model/loss directory and Health references keep their own
  resolution rules. The package does not change their path bases. Files outside
  the declared root retain their existing loading rules; they are not
  automatically added to the package.
- Every declared member contributes its name and captured SHA-256 to package
  identity, even if not imported yet. Editing a helper changes the composition
  fingerprint. Relocating unchanged files and relative declarations does not.
  Data, configuration files and outputs are not Python members; their existing
  task/configuration contracts remain separate.

The parent executes captured source bytes. Before a new framework child loads
selected code, it checks **all** members against the parent's captured hashes;
it must not silently capture a new revision. Transport contains paths and hashes,
not copied source or datasets, in the configured workspace's `task_code/`
directory. Normal launchers establish that workspace; a programmatic caller
must bind an explicit workspace before creating subprocess transport. In-memory
composition alone does not create that transport file. Do not add the consumer
checkout to `PYTHONPATH` or modify SIDERIUS to make imports succeed.

A declared modular model reused by the workflow retains its original selected
source rather than becoming an orphan one-file copy in the generated library.
Validator execution and its entry-source checks use the captured entry; the LLM
review does **not** recursively review every helper. Generated models remain the
existing single-file producer path, not a new modular code-generation feature.

### Missing or changed package code

`LocalCodeError` identifies a declaration, member or pin refusal. The supported
workflow/chain treats it as `code_package_integrity`, halts with exit code 3 and
preserves available diagnostics; it is not a bad candidate to retry, a measured
resource failure or a scientific Health rejection. Ordinary candidate errors
retain their existing handling.

Restore the exact declared files to continue the same captured run. For an
intentional code change, compose it again and start a fresh workspace with the
new identity. Do not edit persisted hashes or re-stamp old results to conceal
the change. See [workspaces and resume](../guides/workspaces-and-resume.md).

This is reproducible code selection, **not a Python security sandbox**. It does
not prevent arbitrary file access or recover exceptions suppressed by task or
third-party code. A killed process or unavailable diagnostic storage can also
limit the recorded explanation; missing evidence is not a scientific result.

## Section shapes

```yaml
task_data_path:
  file: ./plugins/my_data_path.py
  symbol: MyTaskDataPath
  id: my_task                                  # optional

dataset_profile:
  config: ./declared/dataset_profile.json

metric:
  declaration: ./declared/metric_spec.json
  implementation:
    file: ./plugins/my_metrics.py
    symbol: MyMetric

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
objective:                                     # optional — exactly one form
  config:                                      # framework-provided objective
    loss_type: ce
    reduction: mean
# objective:                                   # task-owned objective instead
#   implementation:
#     file: ./plugins/my_exact_loss.py
#     symbol: PLUGIN_LOSS_TYPE                 # plugin's self-declared loss name

parameter_rules:                               # optional; omitted = agent-controlled
  train_config.batch_size:
    exact: 1
  train_config.epochs:
    range: {min: 1, max: 20}                   # inclusive; either bound may be omitted
  model_config.hidden_dim:
    allowed: [128, 256, 512]
  model_config.num_layers:
    predicate: odd_integer                     # registered deterministic predicate

deliverable:                                   # only if the task names artifacts by index
  prefix: my_task_output
  extension: npz
  index_width: 4

dynamic_observables:                           # optional; ORDER IS SEMANTIC
  - name: validation_accuracy                  # the key the series is stored under
    implementation:
      file: ./plugins/my_observables.py
      symbol: ValidationAccuracy               # a DynamicObservable subclass
static_observables:                            # optional; ORDER IS SEMANTIC
  - name: trained_weight_norm
    implementation:
      file: ./plugins/my_observables.py
      symbol: TrainedWeightNorm                # a StaticObservable subclass
```

Notes:

- `secondary_metrics` **order is semantic** — it participates in the composition
  fingerprint and the record stamp. Duplicate ids, or a secondary whose id
  collides with the primary's, are refused.
- `parameter_rules` constrains leaves under `model_config`, `train_config`, or
  `loss_config` through dotted paths. Each path declares exactly one of `exact`, `range`, `allowed`,
  or `predicate`. `exact` supplies the executed leaf value even when the agent
  omitted it; the other forms validate the agent's choice. Predicate names
  must be registered with `register_parameter_predicate`; executable Python
  expressions and raw lambdas are not accepted in YAML. The complete rule set
  is part of the composition fingerprint, so changing it requires a fresh
  comparable workspace. A declared objective remains the sole owner of
  `loss_config`, and a parameter rule targeting that subtree is refused.
  The independent epoch ceiling remains a safety authority: a rule that would
  raise `train_config.epochs` above it is refused rather than weakening it.
- A workflow may add a second rule set through
  `--workflow_parameter_rules '<json>'`, using the same shape. Task and
  workflow rules are enforced together: the workflow may narrow a task rule
  but cannot escape or overwrite it. Omission keeps the workflow
  unconstrained. For example, a campaign can lock a task-supported window
  size without changing the static task package:

  ```bash
  --workflow_parameter_rules \
    '{"model_config.segmentation_size":{"exact":40000}}'
  ```

  A different workflow can leave the value agent-controlled while enforcing
  an admissible set:

  ```bash
  --workflow_parameter_rules \
    '{"model_config.segmentation_size":{"allowed":[20000,40000,50000]}}'
  ```

  The validated canonical rule set is part of the workspace run identity, so
  changing it requires a fresh workspace. This is deterministic enforcement,
  not prompt advice: `exact` controls the executed value; `range`, `allowed`,
  and `predicate` reject a non-conforming proposal.
- `dynamic_observables` / `static_observables` are the two **observable**
  families (`R-OBS-1`, `D-BUD-16`). The split is a **type**, not a naming
  convention: an implementation subclasses either
  `execute_tools.observables.DynamicObservable` (`reset` / `update` / `value`
  — fed the per-epoch validation pass, producing one value per epoch) or
  `StaticObservable` (`compute` — called once, with the trained model). The
  composition **refuses** a manifest that lists one under the other's section,
  so a declaration cannot misstate when its arithmetic runs.
- Observable **names must be unique across BOTH sections** — they are the keys
  the persisted series, the record mapping and the report table all join on.
- Observables are **observational**. They are hidden from the planner, never
  ranked against the primary metric, and never a budget or selection signal.
- Observables reach the training subprocess through the manifest the parent
  already transports (`--task_manifest`); the child composes them through this
  same authority. Nothing new crosses the process boundary — an observable is
  a live object with per-epoch state, which no argv could carry.
- A declared observable with an ordinary error or non-finite value is an
  **absence**, never a sentinel: its value is dropped and the training attempt
  succeeds. A dynamic series that is shorter than the epoch axis (an observable
  that failed in some epochs only) is dropped whole rather than padded.
  Named code-package integrity refusals are different: they propagate and halt
  the workflow rather than being hidden as an absent observation.
- A metric implementation must be an `EvaluationMetric` and may not rewrite the
  `id` declared in its declaration file.
- `deliverable` is `extra="forbid"`: a misspelled key is refused rather than
  falling back to a template.
- An empty `task_description` is refused.
- **Planner builtin offers follow declared ModelIO compatibility.** Composed runs
  require normalized output semantic/temporal facts. The planner filters builtins
  through execution's existing compatibility rule and refuses contradictory
  concrete fixed-model declarations. A declared objective is displayed exactly
  and remains deterministically authoritative, not a loss-exploration lever.
  Custom-loss registration and earlier dummy tests are not task-specific
  prediction/target compatibility certification; their existing routing is
  unchanged, and fuller custom compatibility declarations remain pending.
- **An `objective.implementation` file must export all three loss-plugin symbols** —
  `PLUGIN_LOSS_TYPE`, `PLUGIN_LOSS_CONFIG_CLASS` and `PLUGIN_LOSS_CLASS` — even
  though the manifest names only the first. The section is checked against the
  same contract the loss registry enforces, so composition refuses at startup
  and names the missing symbol.

  > **Behaviour change.** Before this check existed, a manifest naming a plugin
  > that exported only `PLUGIN_LOSS_TYPE` composed successfully and the run
  > died much later, at admission, with `Custom loss ... not found in
  > LOSS_REGISTRY` and a remediation line telling you to run the implementor —
  > wrong advice for a declared pack plugin. Such a manifest now fails to
  > launch. That is the same defect surfacing earlier and with the real cause;
  > the fix is to export the two missing symbols, not to revert the check.

## Beyond the manifest: `--data_dir`

A composed run **requires** `--data_dir`. It fails closed before any LLM call or
GPU work with `CompositionDataRootMissing`. Without it every child subprocess
would fall back to the import-time TIDMAD data directory.

That same root is what the run's **measurement capability** is resolved against,
and the capability carries the composed task's own identity (its
`task_data_path:` `id`) rather than TIDMAD's. So the launch guard's
"can this environment measure?" verdict is about the dataset the run actually
reads. A composed run that cannot supply a root is refused **by name** — the
refusal states which task could not be measured, never TIDMAD's dataset.
An un-composed run is unchanged: it resolves TIDMAD's capability against the
import-time data directory exactly as before.

## Things the manifest does *not* declare

| thing | how it is supplied instead |
|---|---|
| framework health policy | packaged default via `execute_tools.health_checks.config.default_health_policy_path()`; omitted override selects it (science stays task-owned) |
| data scope, budgets, rounds | CLI flags — see [entrypoints](entrypoints.md) |
| the physical data root | `--data_dir` (below) |

Model and loss plugins *are* manifest-declarable (`model_plugins:` /
`loss_plugins:` above). The `SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS`
environment variables remain the un-composed channel — and at every child spawn
the declared roots are **unioned** into them, so a child may add to the set the
run declared but can never drop it.

## What happens at composition time

Custom scoreability checks are part of task identity, not just executable
helpers. A metric's `scoreability_contracts` mapping selects the classes that
decide whether an artifact may be scored. Changing a selected implementation,
its file contents, or which metric/contract uses it must change the composition
fingerprint. Primary and secondary metrics follow the same rule; relocating
the whole task package without changing its logical bindings or contents does
not change that identity. Importable `module:` bindings remain subject to the
existing pinned-environment contract rather than a recursive dependency hash.

**Compatibility correction (#425):** older framework revisions omitted custom
scoreability implementations from the fingerprint. Affected old run records
must not be re-stamped to match the corrected identity. Start a fresh workspace
and rerun; no automatic old-result migration is provided. Tasks with no custom
scoreability mapping retain their previous fingerprint through this correction.

1. The manifest is read; unknown keys refuse; required keys are checked.
2. If declared, the finite Python package is captured before plugin execution.
   Each section then resolves — files loaded, symbols imported or executed by
   path, types checked. Selected members share the captured package loader.
3. A semantic fingerprint is computed over the declared content (never absolute
   paths).
4. `bind_run_task_composition` activates every binding on one exit stack, so any
   failure unwinds all of them.
5. `verify_composition_is_bound` asserts the bindings are actually live. A
   half-composed run is fatal, not degraded.

The supported chain/iteration launch requires an explicit task composition and
physical data directory. Do not omit the manifest expecting a scientific task
or a legacy child command to be selected automatically.

## Worked example

`configs/task_composition/quickstart.yaml` is the shipped reference manifest.
It binds only framework-owned synthetic declarations and demonstrates the same
resolution, plugin, objective, Health, and identity surfaces an external task
uses. Real scientific manifests live with their task packages outside this
repository.

---

## Next

- [Define your own task](../guides/define-a-task.md)
- [Configuration map](configuration-map.md) — which file is owned by whom
- [Composition mechanism reference](../agent-reference/mechanisms/composition.md) — for implementers
