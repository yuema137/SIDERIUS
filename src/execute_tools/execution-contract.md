# `execute_tools/` — deterministic execution: engines + task seams

Technical inventory for this module. Start with [the directory guide](README.md)
for navigation. Source and tests determine current behavior.

## Purpose

The deterministic half of a run: the three child engines (training, inference,
scoring) and the seams through which a *task* supplies its semantics — data
path, dataset profile and scope, evaluation metric, deliverable naming. Agents
can supply model/configuration choices through validated inputs. These engines
execute those choices under deterministic guards; they do not ask an LLM to
change scientific scoring or scope rules during execution.

## Public interface

The task-facing seams:

| file | surface |
|---|---|
| `task_data_path.py` | `TaskDataPath` (Protocol, exactly four methods: `training_dataset` · `validation_dataset` · `write_deliverable` · `read_evaluation_payload`, plus `task_data_path_id`) · optional siblings `TaskScopeCapability`, `TaskTrialAnchoring` · `register_task_data_path` · `resolve_task_data_path` / `bind_task_data_path` / `active_task_data_path` · argv transport + identity verification |
| `evaluation_metric.py` | `MetricSpec` (id **opaque**, `direction` explicit, `aggregation`, `scoreability`; frozen, `extra="forbid"`) · `EvaluationMetric` (ABC — `evaluate` runs the scoreability contract **before** any arithmetic) · `ScoreabilityContract` · `MetricResult` / `NotScoreableResult` / `NotScoreableError` · `bind_run_metric` / `resolve_run_metric` (+ secondaries) · shipped generic metric implementations |
| `metric_order.py` | `MetricOrder` — **the one authority interpreting metric direction** (`is_better`, `best`, `worst_sentinel`, `direction_words`, …) |
| `dataset_config.py` | `DatasetProfile` (generic identity + opaque `topology` the framework never reads) · `DataScope` (`--data_scope "4-9"`) · `ChannelIdentity` / `ValueEncoding` |
| `deliverable_spec.py` | `DeliverableNaming` — **the sole owner of deliverable file naming** — and `DeliverableStorage`/`DeliverableSpec` |
| `sample_set_builder.py` / `scoring_utils.py` | `build_sample_set` (partition SampleSet construction) · `validate_sample_set` (membership validation on the legacy SampleSet route) · `score_vector` (legacy compatibility helper; bound task metrics own current scoring semantics) |
| `data_paths.py` | explicit physical data-root validation plus run-scoped bind/active/resolve transport |
| `scope_artifact.py` | the hash-verified scope artifact ABI crossing the process boundary |
| `spawned_file_callable.py` | content-pinned execution of a task-owned `file:` plugin callable in fresh `multiprocessing` spawn workers; use this instead of submitting a dynamically loaded function directly |
| `task_registration_scope.py` | run-scoped registration visibility/rollback |

The engines (subprocess entrypoints, launched only by `core/sandbox_executor`):
`train_engine_sandbox.py` · `inference_single.py` · `denoising_score_single.py`.
Task implementations are supplied by caller-owned plugins; this checkout ships
only the generic protocols and engines. Plus focused single-authority modules
(`persisted_ranking.py`, `per_file_best.py`, `workload_resolvers.py`,
`probe_batch.py`, `scientific_aggregation.py`, …) — read their docstrings.

## Inputs

Argv from the sandbox (scope artifacts, dataset profile JSON, data roots,
task identity flags — emitted **only when a composition is bound**, so legacy
argv is unchanged); the run-scoped bindings; deliverables for scoring.

## Outputs

Trained checkpoints, deliverable files (named by `DeliverableNaming`), score
records (`metric_result` / `metric_refusal`), typed training results.

## Owned semantics

- **Fail-closed task resolution**: an explicitly bound task never falls back
  to TIDMAD; unknown ids refuse; registration follows the two-phase rule
  (same id + same content ⇒ idempotent; same id + different content ⇒ refused).
- **Scoreability before arithmetic** — a refused deliverable is a structured
  `not_scoreable` outcome, never a garbage number; never re-inline
  `score_vector` at a call site or move the contract after the arithmetic.
- **Direction is interpreted only by `MetricOrder`**; prose renders through
  `direction_words()`.
- **Scope enforcement in layers** (constructive, boundary, direct-access) —
  never by prompts; violations terminate, non-retryable.
- **Custom-loss execution is contract-bound**: an expected immutable
  capability snapshot travels from the composed task through warmups,
  measurement workers and the training child. In-memory and file-backed loss
  loaders compare it before loss construction/import; omission remains only
  the explicit uncomposed compatibility path.
- Scientific metric implementations and their frozen definitions belong to the
  task package. Generic execution does not select a scientific formula.

## Non-owned semantics

- What a health failure *does* →
  [`health_checks/`](health_checks/README.md).
- When engines run, retries, round policy → the tuner node.
- Manifest resolution / binding lifecycle → `workflows/task_composition.py`
  ([composition mechanism](../../docs/agent-reference/mechanisms/composition.md)).
- Ceilings and child spawning → [`core/`](../core/README.md).

## Extension points

- **A task supplies its own `TaskDataPath` and `EvaluationMetric` as
  out-of-tree `file:` plugins** declared in its manifest — no edit here
  ([define a task](../../docs/guides/define-a-task.md)). Data not shaped like
  "N partitions of M units" adds the `TaskScopeCapability` sibling; the four
  base methods are frozen and never grow.
- A task-owned `file:` plugin that needs process parallelism captures its
  worker with `SpawnedFileCallable.capture(...)` and maps it through
  `map_spawned_file_callable(...)`. A raw `ProcessPoolExecutor` cannot submit
  functions from the composition loader's synthetic module: fresh spawn
  workers have no import authority for that parent-only module name.
- Task-owned scoreability subclasses are selected by the metric section's
  `scoreability_contracts` mapping. Unknown undeclared ids refuse. See the
  [metric extension reference](../../docs/guides/bring-your-own-metric.md).

## State and filesystem effects

Engines read the bound data root and write deliverables/records under the
sandbox directories. The legacy partition SampleSet route calls
`validate_sample_set` at its execution boundaries. Opaque task-owned scopes
instead cross the digest-verified scope transport and are materialized by the
task data path; the framework does not parse them as SampleSets. Registry
visibility has run-scoped rollback through `task_registration_scope`, and task
data configuration is caller-bound.

## Failure modes

| refusal | meaning |
|---|---|
| `TaskDataPathRegistrationError` / `TaskDataPathResolutionError` | bad or divergent registration; unknown/absent binding — fail closed |
| `TaskDataPathIdentityError` | a transported plugin's content does not match the parent-pinned identity |
| `ScopeViolationError` | I/O outside the resolved scope — terminates the run |
| `ValidationScopeError` | `validation_dataset` could not materialize exactly what was requested (padding/truncating is forbidden) |
| `NotScoreableError` → `error_scoring` / `failure_type="not_scoreable"` | the metric refused before arithmetic |

## Files normally edited

Nothing, for task authors. Framework work: adding a generic metric instance or
a new single-authority module, always with its census/guard.

## Files normally NOT edited

`scoring_utils.score_vector` remains a legacy compatibility surface;
`metric_order.py` (one authority); `deliverable_spec.py` naming ownership; the
four `TaskDataPath` methods (frozen — extend via optional siblings).

## Current maturity

✅ Task-owned scopes reach **all three** children (training, inference, scoring).
The current tuner reaches inference, scoring and Health through the generic
round boundary; task qualification evidence remains external. See
[`health_checks/README.md`](health_checks/README.md). See
[supported tasks](../../docs/concepts/supported-tasks.md) for the authoritative
current-vs-target table.

## Minimal example

```python
class MyTaskDataPath:
    task_data_path_id = "my_task"
    def training_dataset(self, scope, params): ...
    def validation_dataset(self, scope, params): ...   # EXACT materialization
    def write_deliverable(self, outputs, request): ...  # codec only
    def read_evaluation_payload(self, request): ...     # codec only
```

`read_evaluation_payload` normally returns the decoded task value. If one
scientific result spans multiple physical artifacts, return
`TaskEvaluationPayload(value=..., deliverables=...)` instead. The scoring child
then gives `value` to the task metric while the scoreability contract inspects
every named artifact. This is an explicit carrier, not a filename or
payload-shape heuristic; single-artifact tasks remain unchanged.

For a shared, immutable training parent, a task may also implement the
three-method `TaskFrozenTrainingPoolCapability` in `training_pool.py`.
It owns the parent selection, relative Trial draw, and task-specific
containment proof. The framework never decodes the scope and does not enable
this capability for tasks that have not explicitly implemented all three
methods.

Declared from a manifest via `file:` — never by editing this package.

## Related tests

`tests/unit/execute_tools/` (registry two-phase rule, scope transport,
scoreability ordering, metric reconciliation, deliverable naming) and the
Gate-2 harnesses under `scripts/` for real-execution evidence.
