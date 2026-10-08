# Execution and subprocess transport

**Semantic owners**: `core/sandbox_executor.py`,
`core/execution_calibration.py`, `execute_tools/{train_engine_sandbox,
inference_single, denoising_score_single}.py`
**Status**: ✅ Current — task-neutral below the composition edge (PR-12d)

---

## Purpose

Run the three heavy workloads — training, inference, scoring — as sandboxed child
processes, and transport everything a child needs across that boundary without
the child inferring anything.

## Non-responsibilities

- Not scoring mathematics (owned by the metric).
- Not scope construction (owned by the task).
- Not deliverable naming policy (owned by `DeliverableNaming`).

## The three children

| role | entrypoint | receives |
|---|---|---|
| training | `execute_tools/train_engine_sandbox.py` | `--data_dir` = physical data root, the eval sample set, **the task scope artifact** |
| inference | `execute_tools/inference_single.py` | `--data_dir` = physical data root, **the task *evaluation* scope artifact** — supplied ⇒ it iterates the task's own scope and writes through `write_deliverable` |
| scoring | `execute_tools/denoising_score_single.py` | `--raw_data_dir` = physical data root; its `--data_dir` is the **deliverable** dir; **the task scope artifact** — on the task-owned route it reads via `read_evaluation_payload` and evaluates the composed metric |

> **Do not conflate the two `--data_dir`s.** For scoring, `--data_dir` is the
> deliverable directory and the physical root is `--raw_data_dir`. This is the
> single most confusable thing in the transport surface.

## What crosses the boundary

| value | mechanism | emitted |
|---|---|---|
| physical data root | `--data_dir` / `--raw_data_dir` | **only when composed** |
| task manifest path | `_task_manifest_argv()` | at all three spawn sites, **only when bound** |
| task scope | artifact path + sha256 digest (`--task_scope_ref` / `--task_scope_digest`) | at **all three** spawn sites, **only when armed** — `task_scope_argv` returns `[]` for an absent scope |
| declared plugin roots | env union into `SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS` (`core/subprocess_env.py`) | a child spawn may **add** to the declared set, never drop it |
| declared metric | the scoring child re-composes it from the transported manifest | **no fallback** — a failed composition terminates the subprocess |
| task inference batch ceiling | optional `TaskInferenceBatching` capability projected through `TaskProbeDataSpec` | resource selection and generic inference both enforce the same task-semantic maximum |

Task transport is emitted from explicit bindings. This conditional emission
is not an execution fallback: production children require the declared task
and refuse missing authority.

The scoring child having *no fallback* is deliberate: silently scoring with
TIDMAD's metric would be the same class of defect as an implicit task binding,
one layer further down.

## Scope transport

Raw scope JSON never goes on argv. See
[data path and scope](data-path-and-scope.md#scope-transport-across-a-process-boundary)
for the write → digest → verify → deserialize discipline.

## Resource ceilings

Host-RAM ceilings per role, declared with provenance in
`core/execution_calibration.py::ROLE_CEILINGS`:

| role | GiB | derivation |
|---|---:|---|
| training | 40 | measured |
| inference | **60** | ⚠ empirical, unverified |
| scoring | 24 | incident-derived |

Resolution is **exactly two layers** — declared default, then an environment
override — with no third. `0` disables the ceiling; a malformed override
**refuses loudly**. The invariants lock *records* the ceilings and never compares
them.

The inference declaration explicitly retires its old four-array arithmetic:
task-declared storage and agent-mode writes changed that path. The 60 GiB value
remains because the historical full-scope baseline failed under 40 GiB;
re-measurement is still debt. These are recorded host/process ceilings, not a
portable claim about every task's current memory use. Follow the declaration's
calibration evidence before changing them.

## Deliverables

`DeliverableNaming` is the sole owner of deliverable file naming: `prefix`,
`extension`, `index_width`, `extra="forbid"`.

`DeliverableNaming` retains legacy defaults for individual fields; it is not
the manifest-section presence rule. `extra="forbid"` rejects misspelled keys
instead of silently ignoring them and selecting those defaults. All indexed
names and matching patterns derive from the validated declaration.

The composer requires indexed `deliverable` naming or a task-owned
`deliverable_name`. It refuses a declaration with neither. A task that owns
its artifact names uses its codec; asking for an undeclared indexed naming
capability raises `DeliverableNamingNotApplicableError`. See
[composition absence semantics](composition.md#deliverable-absence-semantics).

## Task-neutrality — closed by PR-12d

The execution path below the composition edge is task-neutral end to end. The
six boundary rows this section used to carry as ⏳ are all landed:

| | status | evidence |
|---|---|---|
| training child receives the task scope | ✅ | `task_scope_argv` in `execute_training`, `core/sandbox_executor.py::SandboxExecutor.execute_training` |
| inference child receives the task scope | ✅ | `task_scope_argv` in `execute_inference`, `SandboxExecutor.execute_inference`; consumed by `execute_tools/inference_single.py` |
| scoring child receives the task scope | ✅ | `task_scope_argv` in `execute_scoring`, `SandboxExecutor.execute_scoring`; consumed by `execute_tools/denoising_score_single.py` |
| scoring child is task-neutral | ✅ | task-owned route: run-bound `TaskDataPath` resolution + `_emit_task_owned_score` in `denoising_score_single.py`, payload via `read_evaluation_payload` |
| inference iteration is task-neutral | ✅ | a supplied scope artifact ⇒ the child iterates the task's own evaluation scope and writes through `write_deliverable` in `inference_single.py` |
| a pack's model plugin reaches a composed child | ✅ | `model_plugins:` / `loss_plugins:` → run-scoped binding → env **union** at every spawn (`core/subprocess_env.py::subprocess_env`) |

Historical PR-12d/PR-12e witnesses belong to their recorded revisions and task
packages. Current composed rounds reach the shared Health boundary after
successful scoring; disabled Health, position selection and applicability still
control which checks execute. See the [Health mechanism](health-gates.md) and
external task qualification records; source reachability is not a fresh run
qualification.

## Provenance stamps

Records and outputs carry the composition fingerprint. Both the **record** stamp
and the **output** stamp must read one run-scoped authority — a real gate run
caught them disagreeing, where the output stamp read the tuner's own
sub-workspace lock and resolved to `None`, which would have made a composed
2-iteration chain refuse its own iteration-1 output.

Every run-scoped binding has an `active_*` / `resolve_*` split. **Transport must
ask the one without the legacy fallback**, or every un-composed child's argv
changes.

## Source map

| Concern | Owner and symbols |
| --- | --- |
| Scope and validation rows | `src/execute_tools/scope_artifact.py`: `task_scope_argv`, `validation_rows_argv` |
| Manifest and physical-root transport | `src/core/task_transport.py`: `task_manifest_argv`, `data_root_argv` |
| Training, inference and scoring spawn | `src/core/sandbox_executor.py`: corresponding `SandboxExecutor.execute_*` methods |
| Child environment and plugin-root union | `src/core/subprocess_env.py`: `subprocess_env` |
| Role ceilings | `src/core/execution_calibration.py`: `ROLE_CEILINGS`, `resolve_role_ceiling_gb`; consumed by `sandbox_executor._subprocess_rss_gb` |
| Deliverable naming | `src/execute_tools/deliverable_spec.py`: `DeliverableNaming`, `resolve_deliverable_naming`, `task_names_its_own_deliverables` |

## Related

- [Data path and scope](data-path-and-scope.md) · [Plugins](plugins.md) · [Composition](composition.md)
- [Supported tasks and maturity](../../concepts/supported-tasks.md)
