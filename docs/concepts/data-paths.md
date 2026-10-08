# Data paths

**Answers**: the `TaskDataPath` contract, what stays task-owned, how a
task-built scope crosses a process boundary intact, and how a binding is
resolved.

Implementer depth — the full protocol source map, `DatasetProfile` fields,
the `DataScope` enforcement layers — is the
[data path and scope mechanism reference](../agent-reference/mechanisms/data-path-and-scope.md).

---

## The seam: four methods, frozen

`execute_tools/task_data_path.py` is the one place the framework asks a
bound task for its executable data behaviour:

```python
class TaskDataPath(Protocol):
    task_data_path_id: ClassVar[str]

    def training_dataset(self, scope, params) -> Dataset: ...
    def validation_dataset(self, scope, params) -> Dataset: ...
    def write_deliverable(self, outputs, request) -> None: ...
    def read_evaluation_payload(self, request) -> object: ...
```

Four methods, deliberately frozen — a capability beyond them is declared as
an **optional sibling** on the same object, never by growing the base
contract. Two obligations are easy to violate and are enforced as the
implementation's own duty:

- **`validation_dataset` materializes exactly what was requested.** It fails
  rather than padding, truncating, or quietly resampling.
- **The write/read pair are codecs.** No scoring, no aggregation, no
  filtering — the output path terminates at the evaluation-metric
  authority, always.

Datasets yield `(model_input, supervision_target)`. The input must satisfy
the task's declared model I/O contract; the target belongs to the training
objective and need not share the output's shape (a classifier's `[37]`
logits against a scalar class index is the canonical case).

## The scope is the task's vocabulary

A *scope* — which data a run touches — is **task-owned and opaque to the
framework**: TIDMAD's `{file: [segments]}`, Pets' manifest rows, DAVIS's
clip identities. The framework passes it through untouched and deliberately
has no scope-aware checker; exact materialization is each implementation's
obligation in its own vocabulary.

The base protocol consumes supplied scopes. A composed workflow that constructs
them requires the **`TaskScopeCapability`** sibling, regardless of data geometry —
`build_training_scope`, `build_eval_scope` (separate methods, because the
leg is a different question, not a parameter), `serialize_scope`,
`deserialize_scope`. Serialization must be **canonical**, because the
framework digests it:

```
serialize_scope → canonical bytes → sha256
  → atomic write to a run-scoped artifact
  → argv carries only <path> + <digest>      (raw scope JSON never rides argv)
  → the child recomputes the digest, refuses a mismatch, then deserializes
```

The digest is recomputed, never re-read; verification happens *before*
deserialization; the write is atomic. On the current source the scope
artifact reaches **all three** child processes — training, inference and
scoring.

A separate, framework-owned notion also called "scope" exists for
partition-indexed tasks: the `--data_scope 4-9` CLI form, enforced in
layers (constructively at the sample-set builder, again at the sandbox I/O
boundary, never by prompts). In the standard composed workflow, a partial
file-index scope is refused if `tidmad_topology` cannot resolve a compatible
profile. This checks topology, not a task-name string. Other restrictions
belong to the task's own `TaskScopeCapability`.

Alongside the data path, a task declares a **`DatasetProfile`**: the few
generic facts the framework does reason about (`partition_count`,
`anchor_selection_files`, `health_peek_files`) plus an opaque `topology`
payload that is entirely the task's — the framework carries it and never
looks inside.

## Resolution: keyed on binding presence, never on a task name

The registry (`register_task_data_path` / `resolve_task_data_path`) is
fail-closed: it resolves the declared implementation identity and supplies no
scientific default:

- an explicit binding whose id is unknown → `TaskDataPathResolutionError`,
  naming the id and the registered set;
- a malformed implementation → refused at registration, before any
  execution;
- a run that needs scope construction from an implementation without the
  sibling capability → `TaskScopeCapabilityError`, naming the id *and* the
  missing methods;
- absence of a binding context or a bound implementation →
  `TaskDataPathResolutionError`; no scientific task is selected implicitly.

Registration follows the two-phase identity rule (same id + same content ⇒
idempotent; different content ⇒ refused), and children verify a
parent-pinned content identity before consuming — see
[plugins and generated code](plugins-and-generated-code.md).

## The shipped implementations, and yours

The shipped examples are Quickstart's `QuickstartTaskDataPath`
(`examples/quickstart/plugins/_quickstart_task.py`) and synthetic masked
regression (`examples/synthetic_masked_regression/plugins/_masked_task.py`).
They load through manifest `file:` references, as an external task does.
Scientific data paths for TIDMAD, Pets and DAVIS belong to siderius-exp;
they are not implementations under this framework's `execute_tools/`.

Your task binds through its composition manifest:

```yaml
task_data_path:
  file: ./plugins/my_data_path.py   # or module: my_package.data_path
  symbol: MyTaskDataPath
  id: my_task                       # optional cross-check against the class's own id
  config:                           # optional task-instance configuration —
    train_shards: [0, 1]            #   handed to YOUR constructor; the framework
    eval_shard: 2                   #   validates the shape and knows no field name
```

No SIDERIUS edit is involved: the registry is extended by registration at
composition time, and the manifest may live anywhere on disk.

## Where to go next

- [Define your own task](../guides/define-a-task.md) — the decisions in order
- [Data path and scope mechanism](../agent-reference/mechanisms/data-path-and-scope.md) — for implementers
- [Task composition reference](../reference/task-composition.md) — the manifest shapes
- [The execution model](execution-model.md) — the other side of the process boundary
