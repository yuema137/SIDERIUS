# Data path, dataset profile and scope

**Semantic owners**: `execute_tools/task_data_path.py`,
`execute_tools/dataset_config.py`, `execute_tools/scope_artifact.py`
**Status**: ✅ Current

---

## Purpose

Everything about *which data a run touches and how it is read*: the task's data
access interface, its topology declaration, the framework's partition-index scope
form, and how a task-owned scope crosses a process boundary intact.

## Non-responsibilities

- Not scoring — the data path's read/write methods are **codecs only**.
- Not sampling policy — the data path receives a scope and materialises it.
- Not interpreting task topology — the framework carries `topology` opaquely.

## `TaskDataPath` — the frozen four

```python
class TaskDataPath(Protocol):
    task_data_path_id: ClassVar[str]

    def training_dataset(self, scope, params: EpochSamplingParams) -> Dataset: ...
    def validation_dataset(self, scope, params: EvalMaterializationParams) -> Dataset: ...
    def write_deliverable(self, outputs, request: DeliverableWriteRequest) -> None: ...
    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object: ...
```

`@runtime_checkable`. Four methods, deliberately frozen: capabilities beyond them
are declared as **optional siblings** on the same object rather than growing the
base contract.

Two obligations that are easy to violate:

- `validation_dataset` must materialise **exactly** what was requested. It fails
  rather than padding, truncating or resampling.
- `write_deliverable` / `read_evaluation_payload` are codecs. No scoring, no
  aggregation, no filtering.

Generic inference passes unpaired predictions in deterministic
`validation_dataset` index order. Its `DeliverableWriteRequest` includes the
opaque task scope and an optional typed `DeliverableSourceContext` containing
the run's physical data root, output sample count, and fixed ordering contract.
A task whose deliverable needs source- or supervision-associated values may
rematerialise its own validation dataset through that context and must refuse a
count mismatch. Prediction-only tasks ignore the optional context. The
framework does not retain task tensors, inspect sample fields, or add another
data-path method.

## Optional sibling capabilities

| capability | methods | detected by |
|---|---|---|
| `TaskScopeCapability` | `build_training_scope`, `build_eval_scope`, `serialize_scope`, `deserialize_scope` | duck-typed callability against `_SCOPE_CAPABILITY_METHODS`; missing ⇒ fails closed **by name** |
| `TaskTrialAnchoring` | `trial_anchor_path` | `declares_trial_anchoring` TypeGuard |
| `TaskInferenceBatching` | `max_inference_batch_size` | `declares_inference_batching` TypeGuard; malformed or non-positive values fail closed |

`build_training_scope` and `build_eval_scope` are **separate methods**, not one
method with a `leg` argument — the leg is not a parameter, it is a different
question.

`serialize_scope` **must be canonical**: the framework digests its output.

`max_inference_batch_size` is a semantic collation ceiling, not a resource
estimate. The VRAM probe chooses only from batches at or below it, and generic
inference verifies the same ceiling before materializing a dataset. Tasks that
omit the capability retain resource-derived inference batching unchanged.

## `DatasetProfile`

Frozen. Generic identity plus an opaque payload:

| field | meaning |
|---|---|
| `partition_count` | the one generic topology fact the framework reasons about (`gt=0`) |
| `anchor_selection_files` | **required**, no default — a TIDMAD-shaped default is explicitly rejected |
| `health_peek_files` | **required** |
| `topology` | **opaque, task-owned** — "the framework NEVER inspects inside this payload" |

The legacy wire form is still accepted and emitted (`to_wire()`), and a
cross-field validator checks the declared file sets are legal for the topology.

## `DataScope` — the framework's partition-index form

`--data_scope 4-9`, `4,5,6,7,8,9` and mixed `0-3,7` all canonicalise to one
sorted, deduplicated list. Enforcement is layered and **never by prompt**:

1. **constructive** — `build_sample_set(scope=…)`
2. **boundary** — `validate_sample_set` at the sandbox before *all* file I/O
   (train, inference, scoring); a violation terminates the run, non-retryable
3. **direct-access** — `health_gate_files ⊆ scope` validated at startup

Under a partial scope only `snapshot` sampling is legal. Operator config errors
fail at startup; LLM plans are normalised with recorded provenance.

Aggregate scalars are comparable **only within one scope**. The resolved scope,
health-gate enablement and effective-config sha256 are pinned per workspace by
`run_invariants_lock.json`.

## Scope transport across a process boundary

The identity discipline, owned by `execute_tools/scope_artifact.py`:

```
task scope object
  → TaskScopeCapability.serialize_scope     (the TASK owns canonicality)
  → canonical bytes → sha256 = scope_digest
  → ATOMIC write to a run-scoped artifact   (tmp + os.replace)
  → argv carries only <path> and <digest>   (raw scope JSON never goes on argv)
  → child: read → RECOMPUTE the digest → refuse on mismatch → only then deserialize
```

Three guarantees:

- the digest is **recomputed, never re-read**;
- verification happens **before** deserialization;
- the write is **atomic**.

Two artifact stems exist deliberately — `task_scope` and `task_eval_scope` — so
that "eval scope absent" is distinguishable from "eval scope empty".

The framework never parses the payload. It is the task's vocabulary.

## Physical data-root resolution

A composed run binds its explicit physical data root at run scope and
transports that value to execution children. Importing generic composition or
workflow modules performs no task selection and therefore must not read
`tidmad_data_config.yaml`.

The two historical module attributes, `TIDMAD_DATA_DIR` and
`SIDERIUS_DATA_DIR`, remain available for un-composed legacy callers. Their
configuration is resolved lazily on first value access, preserving the prior
real-file/template precedence, warning, and missing-config refusal. An explicit
composed data root never falls through to that legacy task configuration.

## Registration

`register_task_data_path` uses a two-phase lifecycle rule: same id + same content
⇒ idempotent; same id + different content ⇒ refuse. A registry **hit is not
identity proof** — the parent pins a per-family content identity captured *at
registration* and the child verifies it *before consuming*.

> The captured-at-registration detail is load-bearing. Re-deriving the identity at
> spawn time reads whatever is on disk *now*, so the pin follows the very edit it
> exists to catch.

## Maturity

| | status |
|---|---|
| `TaskDataPath` four methods | ✅ |
| `TaskScopeCapability` construction and serialisation | ✅ |
| scope artifact reaching the **training** child | ✅ |
| scope artifact reaching the **inference** child | ✅ PR-12d |
| scope artifact reaching the **scoring** child | ✅ PR-12d |
| generic (non-TIDMAD) inference iteration | ✅ PR-12d — a supplied scope ⇒ the child iterates the task's own evaluation scope |
| prediction-aligned deliverable source context | ✅ issue #385 repair — additive request context; four-method contract unchanged |

On landed master the emitter is `task_scope_argv`
(`execute_tools/scope_artifact.py:252`), called at **all three** spawn sites in
`core/sandbox_executor.py` — `execute_training` (`:1542`), `execute_inference`
(`:1839`) and `execute_scoring` (`:2180`); it returns `[]` for an absent scope,
so un-composed argv is unchanged. All three children accept
`--task_scope_ref` / `--task_scope_digest` and recompute the digest before
deserializing.

## Source map

| concern | location |
|---|---|
| `TaskDataPath` | `execute_tools/task_data_path.py:350` |
| `TaskScopeCapability` | `:394` |
| `TaskTrialAnchoring` | `:453` |
| registry lifecycle | `:612-743` (`register_task_data_path` `:682`) |
| `DatasetProfile` | `execute_tools/dataset_config.py:466-486` |
| `DataScope` | `:186-336` |
| TIDMAD topology | `:814` |
| scope artifact contract | `execute_tools/scope_artifact.py:1-40` |
| read/write/paths | `:81`, `:91`, `:137` |
| child-side consumption (`load_transported_scope`, `execute_tools/scope_artifact.py:199`) | `train_engine_sandbox.py:2207-2210` · `inference_single.py:772` · `denoising_score_single.py:240` |
| implementations | `execute_tools/{tidmad,pets,davis}_data_path.py` |

## Related

- [Composition](composition.md) · [Execution](execution.md) · [Plugins](plugins.md)
