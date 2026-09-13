# What a task must provide

**Audience**: a scientist or engineer bringing their own problem to SIDERIUS.
**Answers**: "what do I actually have to write?"

The short answer: **one YAML manifest with thirteen possible sections, five of
which are required**, plus whatever small amount of Python the framework cannot
supply generically for your data.

This page explains the concepts. The exact table — every section, required or
optional, what absence means — is the
[task composition reference](../reference/task-composition.md).

---

## The mental model

A task package answers five questions. Everything else is the framework's job.

| # | question | how you answer it |
|---|---|---|
| 1 | **How is my data read?** | a `TaskDataPath` implementation + a `DatasetProfile` |
| 2 | **What does a model read and produce?** | a task config declaring the forward contract |
| 3 | **What is being optimised during training?** | a training objective (built-in, or a loss plugin) |
| 4 | **What does "better" mean at the end?** | an `EvaluationMetric` with a declared direction |
| 5 | **What makes an output invalid?** | a task health configuration |

Notice what is *not* on this list: how to train, how to retry, how to budget GPU
memory, how to resume, how to persist provenance, how to prompt an LLM. Those are
the framework's responsibilities and you do not re-declare them.

## 1. How your data is read

You provide an object implementing **`TaskDataPath`** — four methods, and only
four:

| method | responsibility |
|---|---|
| `training_dataset(scope, params)` | produce a training dataset for a scope |
| `validation_dataset(scope, params)` | produce a validation dataset, **exactly** as requested — it may never silently pad or truncate |
| `write_deliverable(outputs, request)` | write model outputs — a codec, nothing more |
| `read_evaluation_payload(request)` | read them back for scoring — a codec, nothing more |

Alongside it you declare a **`DatasetProfile`**: how many partitions your data has,
which partitions anchor selection, which are safe to peek at for health checks,
and an opaque `topology` payload that is *yours* — the framework carries it and
never looks inside.

A task may optionally add a **`TaskScopeCapability`** — the ability to build and
serialise its own training and evaluation scopes. The base data path consumes
already-supplied scopes; the composed workflow needs this sibling to construct
them, regardless of data geometry, and refuses missing methods with
`TaskScopeCapabilityError`. There is no automatic default split for an
implementation without the capability.

> The four `TaskDataPath` methods are a frozen interface. Capabilities beyond them
> are declared as *optional siblings* on the same object, so the base contract
> never grows to accommodate one task.

The package also owns the
[required task-owned split evidence](../guides/define-a-task.md#required-task-owned-split-evidence).
Follow that canonical checklist before claiming scientific evaluation: scope
hashes authenticate transport, but do not prove training/evaluation independence.

## 2. What a model reads and produces

Your task config supplies two things in prose, which reach every LLM prompt:

- **`task_description`** — what the scientific problem is;
- **`forward_contract`** — the exact tensor contract a model must satisfy.

These are what let the proposer and implementor write a model for *your* problem
rather than a generic one. They are required — a composed run with an empty task
description is refused.

## 3. The training objective

What optimisation minimises during training. Most tasks use a built-in
(cross-entropy, MSE, L1, focal loss, …). If your science needs something else,
you supply a loss plugin — the same shape as a model plugin — and the manifest
names where it lives (`loss_plugins:`). If your science requires one *specific*
objective, declare it authoritative (`objective:`): the task's declaration then
overrides whatever the LLM planner would have chosen, as a typed value rather
than a prompt suggestion.

The objective is **not** the same thing as the evaluation metric, even when the
mathematics is identical. See
[Objectives, metrics and what "better" means](objectives-and-metrics.md).

## 4. What "better" means

You declare one **primary metric** (also called the golden metric): its identity,
its aggregation, and — critically — its **direction**, `higher` or `lower`.
Direction is always declared explicitly and never inferred, because a metric that
is negative-valued and higher-is-better (TIDMAD's is both) breaks every heuristic
guess.

The primary metric is the only thing that selects models.

You may also declare **secondary metrics**. These are *observational evidence*.
They appear in records and in what the agents read, and they influence no
ordering, no ranking and no selection anywhere in the framework. That is a
deliberate design rule, not an oversight: secondary metrics are how you watch a
run without turning it into a hidden multi-objective optimisation.

Your metric also declares a **scoreability contract** — an executable check that
runs *before* the arithmetic and answers "is this deliverable scoreable at all?".
A refusal is a structured, recorded outcome, not a crash and not a bad score.

## 5. What makes an output invalid

A **health gate** answers "is this output structurally valid enough to trust?" —
a completely different question from "is this output good?".

You declare a roster of checks with their thresholds. For each you choose exactly
one thing: whether it is **blocking** or **observational**. The framework derives
everything else — when it runs, what a failure does, how severity resolves — so
your task and the framework cannot disagree about policy.

Several checks are generic and reusable across tasks (dispersion floors,
categorical collapse detection). Others are yours. See
[Health gates](health-gates.md).

---

## What you write, concretely

For a task the framework can already serve generically, a package is:

```
my_task/
├── composition.yaml            # the manifest — the only file SIDERIUS is pointed at
└── declared/
    ├── dataset_profile.json    # partition count, anchors, peek set, opaque topology
    ├── task_config.yaml        # task_description + forward_contract
    ├── metric_primary.json     # id, direction, aggregation, scoreability
    └── task_health.yaml        # roster + thresholds
```

For a task that needs its own data access or metric mathematics, add:

```
└── plugins/
    ├── my_task_data_path.py    # TaskDataPath (+ optional TaskScopeCapability)
    ├── my_task_metric.py       # EvaluationMetric
    └── my_model/
        └── description.md      # optional — the planner reads this
```

A model plugin declared through `model_plugins:` may ship a `description.md`
under `{plugin root}/{model_type}/`. The tuner reads it into the planner's
prompt; a pack without one runs with a thinner prompt and says nothing, so it
is worth adding. It is searched after the run's own workspace, so it never
shadows the copy a run actually staged.

Plugins may be declared **by module** (importable) or **by file** (an arbitrary
path). A `file:` reference is how a task lives outside the SIDERIUS source tree —
and its content hash joins the run's semantic fingerprint, so an edited plugin is
detected rather than silently used.

> ✅ **Current**: `file:` plugin references, out-of-tree metric and data-path
> implementations, out-of-tree health plugins, manifest-declared model and loss
> plugin roots (`model_plugins:` / `loss_plugins:`), and a task-declared
> authoritative training objective (`objective:`) all work today. The full
> package contract is demonstrated end to end: a fourth task living entirely
> outside the repository ran the composed workflow with zero framework edits
> (PR-12e's `G-12e` proof), and each shipped example pack carries one documented
> run command (`examples/<pack>/quickstart.sh` —
> [the pack index](../../examples/README.md) is the worked-example surface).
> See [Supported tasks and current maturity](supported-tasks.md).

## What absence means

This is the part worth reading twice. In a composition manifest, an omitted
optional section usually means **nothing is supplied** — not "use a default":

- no `secondary_metrics` → no secondary evidence anywhere, zero record keys
- no `proposal_blocks` → the proposer receives no task science
- no `interpretation_blocks` → the interpreter renders no task blocks

There is **one nuance**, and it used to be a hazard: the `deliverable` section
(an indexed file-naming template). If your task names its own artifacts through
its data path — `write_deliverable` / `read_evaluation_payload` with a declared
deliverable name, as Pets and DAVIS do — omit the section: a composed run then
gets an **honest refusal** wherever an indexed template would be consulted,
never TIDMAD's template. Declare the section only if your task genuinely names
its artifacts by a zero-padded input index. (Before PR-12d landed, absence
silently resolved to TIDMAD's naming — that fallback is gone for tasks that own
their names; a composed task that declares neither, like TIDMAD's own manifest,
still resolves the shipped template.)

---

## Next

- [Task composition reference](../reference/task-composition.md) — the authoritative table
- [Define your own task](../guides/define-a-task.md) — step by step
- [Objectives, metrics and what "better" means](objectives-and-metrics.md)
- [Health gates](health-gates.md)
