# Define your own task

**Prerequisite**: [What a task must provide](../concepts/task-package.md).

This guide walks the decisions in the order you actually face them. It does not
repeat the [composition reference](../reference/task-composition.md) — go there
for exact field shapes.

---

## Step 0 — Decide whether SIDERIUS fits

Answer these before writing anything:

1. Is your task **supervised** — inputs, targets, and a scalar notion of better?
2. Can "better" be **one number with a declared direction**? If your real goal is
   a trade-off between two quantities, decide now which one selects models. The
   other becomes a secondary metric, which will *not* influence selection.
3. Can your data be split into **partitions** that a run can be scoped to?
4. Do you have a notion of an **invalid** output distinct from a bad one?

If (2) has no answer, stop and get one. Everything downstream depends on it.

## Step 1 — Describe your data topology

Write a dataset profile declaring:

- `partition_count` — how many partitions exist;
- `anchor_selection_files` — which partitions anchor selection;
- `health_peek_files` — which are safe to peek at for health checks;
- `topology` — anything else your task needs. This payload is **opaque**: the
  framework carries it and never looks inside, so put whatever your data path
  needs in it.

The generic fields are deliberately few. If you find yourself wanting the
framework to understand something about your data shape, that something belongs
in `topology`.

## Step 2 — Implement the data path

A class with the four `TaskDataPath` methods and a `task_data_path_id` class
variable.

```python
class MyTaskDataPath:
    task_data_path_id = "my_task"

    def training_dataset(self, scope, params): ...
    def validation_dataset(self, scope, params): ...   # EXACT materialization
    def write_deliverable(self, outputs, request): ...  # codec only
    def read_evaluation_payload(self, request): ...     # codec only
```

Two rules that are easy to get wrong:

- **`validation_dataset` must materialise exactly what was requested.** It may
  not pad, truncate, or quietly resample. If it cannot honour the request, it
  fails.
- **The write/read pair are codecs.** They do not score, do not aggregate, do not
  filter. Scoring is the metric's job.

`EpochSamplingParams` is an execution request, not a universal sampling
policy. The framework supplies fields such as `train_portion`, `epoch_seed`
and `max_samples`; your `training_dataset` decides what those fields mean for
your scientific units. A tabular task may select seeded rows, an image task may
need label-stratified identities, and a video task may sample whole sequences.
If your task has no defensible interpretation for a requested fraction, refuse
it explicitly. Never let the framework infer scientific grouping from tensor
shape or file order.

The base interface consumes scopes supplied by its caller. For the composed
workflow to **construct** training and evaluation scopes, also implement the
`TaskScopeCapability` sibling — `build_training_scope`, `build_eval_scope`,
`serialize_scope`, `deserialize_scope` — regardless of your data's geometry.
It is optional to the four-method base contract, not a default split service:
composed scope construction refuses missing methods with
`TaskScopeCapabilityError` before launching child processes. Your serialisation
must be **canonical**: the framework hashes it to verify scope transport.

> ✅ Scopes built this way reach **all three** child processes — training,
> inference and scoring — as a hash-verified artifact; each child recomputes the
> digest before deserializing. See
> [supported tasks](../concepts/supported-tasks.md).

## Required task-owned split evidence

Before using a new task package for scientific evaluation, supply and retain a
reproducible, task-owned split check. Scope payloads are opaque to SIDERIUS:
different filenames or hashes, successful execution and a passing Health check
do **not** prove that training and evaluation are independent. For example,
training IDs `{a, b}` and evaluation IDs `{b, c}` can have different hashes while
sharing `b`. This is an onboarding proof obligation, not a new framework check
that automatically rejects every scientifically leaky task.

Evaluation used to select models or tune hyperparameters is **selection
validation**, not an untouched final test. If your task separately declares a
held-out final evaluation, document its isolation from training and selection.
SIDERIUS does not require every task to invent a third split.

Keep the following evidence with your task package or its referenced records:

1. **Define independence and the identity key.** State which overlap the claim
   forbids: samples/events, objects/patients/groups, or sequence/time context.
   Compare identities at that level, not merely distinct row or crop names.
   For forecasting, include prohibited history/target-window overlap. Shared
   context is not automatically leakage: a graph task may share adjacency while
   keeping supervised node masks disjoint, if it states and justifies that
   protocol. The task owns this scientific choice.
2. **Identify the inputs actually checked.** Record the dataset/source revision,
   split declaration, task code revision and effective configuration, including
   role overrides. Name training, selection-validation and any separately
   declared final-evaluation populations. A proof for shipped defaults does not
   certify another configuration or another dataset.
3. **Check real membership and materialization.** Use the task's scope builders
   and data-materialization rules to establish the relevant identities. Assert
   independently expected, nonempty population sizes before disjointness; an
   empty set passes an intersection check vacuously. Cover supported selection,
   sampling, window and augmentation rules that could change membership or
   identity. A constructive proof that every permitted selection stays inside
   certified disjoint base populations is sufficient; one random subset or seed
   that happens not to overlap is not.
4. **Show a failing leakage counterexample.** Deliberately admit a held-out
   identity, prohibited group or forbidden temporal context to training and
   show that the same check fails. Distinct augmented row IDs must not conceal
   a shared underlying unit when the declared protocol forbids it.
5. **Make the evidence reproducible and bounded in claim.** Retain the exact
   command, required external inputs, revisions/configuration, observed counts,
   result and limitations. Missing data, skipped checks and unavailable evidence
   mean **unverified**, not passed. Synthetic fixtures or test doubles do not
   certify official scientific data.

The shipped
[masked-regression split test](../../tests/unit/examples/test_synthetic_masked_regression_pack.py)
(`test_training_and_evaluation_scopes_are_disjoint`) is a small worked witness:
it calls the task's default full-snapshot builders, expects 48 training and 24
evaluation sample IDs, and checks disjointness. The
[Quickstart scope test](../../tests/unit/examples/test_quickstart_pack.py)
(`test_scope_construction_and_canonical_codec`) additionally exercises default
snapshot, anchor and target selection, including refusal of evaluation shard 2
as a training target. From the SIDERIUS checkout, reproduce just these witnesses:

```bash
uv sync --group dev --frozen
.venv/bin/python -m pytest -q \
  tests/unit/examples/test_synthetic_masked_regression_pack.py::test_training_and_evaluation_scopes_are_disjoint \
  tests/unit/examples/test_quickstart_pack.py::test_scope_construction_and_canonical_codec
```

These tests need no external dataset and prove only the synthetic default
configurations and cases they exercise. They do not verify arbitrary role
overrides, all materialization variants or your external task's split. Supply
your own evidence for the actual declarations and scientific claim above.

## Step 3 — Write the task config

Two typed task-context fields, both required in a production composition:

- **`task_description`** — the scientific problem, as you would explain it to a
  new collaborator;
- **`forward_contract`** — a typed `ForwardContract` declaration containing the
  exact tensor contract, e.g.
  `[B, 3, 144, 144] float32 in [0,1] → [B, 37] logits`.

The caller routes these fields to the node prompts that consume them; they are
not copied into every prompt indiscriminately. Be precise about the typed
forward contract in particular: it is what stops the implementor writing a
model with the wrong declared I/O.

## Step 4 — Declare the primary metric

A declaration file plus an implementation.

The declaration carries `id`, `direction` (`higher` or `lower`), `aggregation`,
and a scoreability contract. The implementation is an `EvaluationMetric` and may
not rewrite the declared id.

Get the **direction** right. It is the one field that silently inverts an entire
research campaign if wrong, and nothing infers it from your metric's name or sign.

Write the scoreability contract properly: it runs before your arithmetic and
decides whether the deliverable is scoreable at all. A total, non-raising check
here converts "mysterious garbage score" into "recorded refusal with a reason".

## Step 5 — Declare secondary metrics (optional)

If you want to watch other quantities, declare them here. They will be evaluated
wherever the primary is, recorded, and shown to the agents — and they will
influence nothing.

If you find yourself wishing a secondary influenced selection, what you actually
want is a different primary metric.

## Step 5b — Declare observables (optional)

A secondary metric is scored from your **deliverable**, after the run has
produced one. An **observable** watches the training itself. Declare one when
the question is "what was happening while this model trained", not "how good is
the result".

There are two kinds, and the difference is a **type**, not a label:

| section | base class | runs | produces |
|---|---|---|---|
| `dynamic_observables:` | `DynamicObservable` | during training, once per epoch, on the validation pass that already runs | one value per epoch |
| `static_observables:` | `StaticObservable` | once, after the final optimizer step | one value |

```python
from execute_tools.observables import DynamicObservable

class ValidationAccuracy(DynamicObservable):
    def reset(self):  self.hits = self.seen = 0
    def update(self, output, target):
        self.hits += int((output.argmax(1) == target).sum()); self.seen += target.numel()
    def value(self): return self.hits / self.seen
```

```yaml
dynamic_observables:
  - name: validation_accuracy
    implementation: {file: ./plugins/_my_observables.py, symbol: ValidationAccuracy}
```

Three things worth knowing before you write one:

- **The section must match the type.** Listing a `StaticObservable` under
  `dynamic_observables:` is refused at composition — the section says *when* the
  arithmetic runs, and the class is what actually decides.
- **`update` must not mutate anything.** It runs inside the transactional
  validation pass, which certifies that training state is left exactly as found.
- **Ordinary failure is an absence.** An observable's ordinary exception or
  non-finite value is dropped and the training attempt still succeeds. A named
  code-package integrity refusal instead halts the workflow: changed or missing
  declared code must not be hidden as a missing observation.

Observables are shown in the run report and are hidden from the agents. Like
secondaries, they influence nothing — and unlike a secondary, they may not be
turned into a budget or selection signal at all.

## Step 6 — Declare health behaviour

Start from the generic checks: `sample_dispersion_floor` for continuous outputs,
`categorical_distinct_symbols` and `categorical_dominant_fraction` for
classification. Set thresholds you can defend, and choose a **disposition** for
each — `blocking` or `recording`.

Advice worth taking: start almost everything `recording`, run once, look at
what the checks actually report on your data, and only then promote the ones that
catch real collapse to `blocking`. A blocking threshold guessed in advance
usually blocks the wrong thing.

If you need a check the framework does not have, write one as a plugin and list
it in your health config's `plugins:` — it registers itself through the public
registration API, and it can live entirely outside the repository.

Declare `task_health: {none: true}` if you genuinely have no health family.
**Declare the section explicitly**: use `task_health: {none: true}` for a task
with no Health family; omitting the required declaration is refused rather than
selecting a scientific default.

A Health view provider should decode the current artifact through
`ctx.load_evaluation_payload()`. That callback reuses your
`TaskDataPath.read_evaluation_payload` codec lazily after applicability has
been decided. Do not reconstruct filenames or copy artifact parsing into the
provider; doing so couples Health to one storage convention and lets the metric
and Health readers drift apart.

## Step 7 — Decide who names the deliverables

Two legitimate shapes, and the framework distinguishes them honestly:

- **Your data path names its own artifacts** (the usual case — Pets and DAVIS
  both work this way): `write_deliverable` / `read_evaluation_payload` own the
  filenames outright, alongside a declared deliverable name. **Omit the
  `deliverable` section.** A composed run whose task names its own artifacts is
  *refused* an indexed template rather than silently handed TIDMAD's — so no
  cleanup glob can ever address files your run never wrote.

  > **Declare it as a MODULE-LEVEL function, beside your data path class.**
  > The framework decides whether your task names its own artifacts by looking
  > for a callable `deliverable_name` **on the module** the class is defined
  > in (`execute_tools/deliverable_spec.py::task_names_its_own_deliverables`):
  >
  > ```python
  > # my_task_data_path.py
  > def deliverable_name(request) -> str:   # module level — this is what is read
  >     ...
  >
  > class MyTaskDataPath:
  >     ...
  > ```
  >
  > It is the same function your `write_deliverable` and
  > `read_evaluation_payload` already agree on, so asking for its presence
  > asks exactly the right question.
  >
  > A `@staticmethod` of the same name on the class does not satisfy it. You
  > will not silently get the wrong template, though: **omitting both — no
  > `deliverable:` section and no module-level `deliverable_name` — is refused
  > at compose time**, with a message naming both remedies
  > (`workflows/task_composition.py`, arXiv #268).
- **Your task genuinely names artifacts by a zero-padded input index**: declare
  the template explicitly.

```yaml
deliverable:
  prefix: my_task_output
  extension: npz
  index_width: 4
```

## Step 8 — Assemble the manifest

```
my_task/
├── composition.yaml
├── declared/
│   ├── dataset_profile.json
│   ├── task_config.yaml
│   ├── metric_primary.json
│   └── task_health.yaml
└── plugins/
    ├── my_data_path.py
    └── my_metric.py
```

Use `file:` references for your plugins if the package lives outside the SIDERIUS
tree. Paths resolve against the manifest's own directory, so the package is
relocatable.

### When your plugins share helpers

Keep the task in your consumer repository, not in the SIDERIUS checkout. If the
data path and metric need the same scope class, put that class in one helper and
declare a finite `code_package` in the manifest. Then use ordinary relative
imports, such as `from .scope import MyScope` from the data module and
`from ..runtime.scope import MyScope` from a metric in a sibling directory.
Do not copy the helper into both files or add the consumer checkout to
`PYTHONPATH`.

The [composition reference](../reference/task-composition.md#shared-task-local-python-code)
owns the exact declaration and path rules. Start with the
[modular masked-regression example](../../examples/synthetic_masked_regression/modular/README.md)
for a working tree: it shares a scope type across data and metric entries and
also shows model/loss, Health, observable and scoreability loading. The original
single-file example remains the simpler option when no shared helpers are needed.

List all Python members deliberately; do not include raw data, output files or
credentials. Keep those at explicit external paths. Every listed helper enters
the code identity, and a fresh child checks its bytes against the parent's pin
before loading it. If you deliberately edit one, use a fresh run/workspace;
do not continue old evidence by rewriting a stored hash. This package feature
does not add multi-file model generation or recursive helper review by the LLM.

## Step 9 — Declare your model and loss plugins

Declare them in the manifest:

```yaml
model_plugins:
  dir: ./plugins            # manifest-relative; resolved and identity-pinned
  require: [my_reference_model]   # model types this root MUST produce

loss_plugins:               # only if you ship a custom loss
  dir: ./plugins
```

`require:` is not decoration — without it, an unresolvable plugin would be
indistinguishable from a directory that simply had nothing in it. The declared
roots become a run-scoped binding whose content identities join the run's
fingerprint, and every child subprocess receives them automatically: the spawn
environment **unions** the declared roots into `SIDERIUS_PLUGIN_DIRS` /
`SIDERIUS_LOSS_DIRS`, so a child can add to the set but can never drop what the
run declared. (The environment variables still work on their own for
un-composed runs.)

If the task requires one specific training objective, also declare it. Select a
framework-provided objective with validated config:

```yaml
objective:
  config:
    loss_type: ce
    reduction: mean
```

For task-owned arithmetic, point at the plugin's self-declaration instead:

```yaml
objective:
  implementation:
    file: ./plugins/my_exact_loss.py
    symbol: PLUGIN_LOSS_TYPE
```

Both forms produce the same typed `LossConfig` authority and override the
planner. The config form cannot select `custom`; custom code must use the
implementation form so its content joins the run identity.

Custom losses also need a prediction/target compatibility declaration in the
task's `forward_contract`. Declare `supervision_target` plus either an
`equal_shape` or `explicit_pair` `custom_loss_applicability`; the framework
then filters proposer and tuner offers against one immutable contract snapshot
and transports that snapshot through resource measurement and training. A
loadable loss whose snapshot is missing or different is unavailable, not a
fallback candidate.

When the declared target cannot be represented by the framework's generic tiny
tensor pair, the bound task implementation may expose a zero-argument
`custom_loss_validation_pair()` sibling. It returns only a small deterministic
`(prediction, target)` pair for numerical/gradient validation. It receives no
data root or scope and must not read training data; preprocessing and real
training batches remain `TaskDataPath` responsibilities. See the shipped
`synthetic_masked_regression` example for the complete declaration shape.

## Step 10 — Launch

```bash
bash scripts/launch/run_chain.sh \
    --mode lilab \
    --workspace /path/to/workspace \
    --run_name my_task_v1 \
    --task_composition /path/to/my_task/composition.yaml \
    --data_dir /path/to/data \
    --llm_config configs/llm/openai_tiered_pro.json \
    --healthgate_mode blocking \
    --result_authority scientific \
    --num_iterations 2 \
    --max_rounds 3
```

Start with `--dry-run` to see the exact child commands before spending anything.

## When it refuses

Composition failures are deliberate and specific. Common ones:

| symptom | cause |
|---|---|
| unknown key refused | a misspelled section name — they are never ignored |
| `CompositionDataRootMissing` | composed run without `--data_dir` |
| id mismatch | the `id:` in your manifest does not match the class's `task_data_path_id` |
| health config refused | you declared both `none: true` and `config:` |
| exit code 2 | missing `--healthgate_mode` or `--result_authority` on a formal launch |
| a resume fails at startup | scope, gate enablement or effective-config hash differs from the workspace's invariants lock |
| `LocalCodeError` / `code_package_integrity` | a declared Python member, dependency or captured pin is invalid; restore the exact source, or use a fresh composition/workspace for intentional edits |

These identity refusals are the system working. Aggregate scores are only comparable within
one scope and one health configuration; a workspace that silently accepted a
changed one would produce numbers that cannot be compared to its own history.

---

## Next

- [Task composition reference](../reference/task-composition.md)
- [Operating a run](operating-a-run.md)
- [Supported tasks and current maturity](../concepts/supported-tasks.md) — what is not yet possible
