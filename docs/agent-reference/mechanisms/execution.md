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

**Transport is emitted only when bound**, so a legacy un-composed run's child
argv is byte-identical to what it always was.

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
| scoring | 24 | measured |

Resolution is **exactly two layers** — declared default, then an environment
override — with no third. `0` disables the ceiling; a malformed override
**refuses loudly**. The invariants lock *records* the ceilings and never compares
them.

> The inference value is not arbitrary. Full-scope baseline inference needs it:
> CUDA static VA ~18–20 GiB, plus ~7.4 GiB NumPy peak per partition, plus
> caching-allocator overhead. **Lowering it without re-verifying full-scope
> baseline inference is a regression.**

## Deliverables

`DeliverableNaming` is the sole owner of deliverable file naming: `prefix`,
`extension`, `index_width`, `extra="forbid"`.

`extra="forbid"` is load-bearing — a misspelled declaration key would otherwise
yield the shipped TIDMAD template *and* a cleanup glob that deletes files the run
never wrote.

Absence of the manifest's `deliverable` section resolves by **declared
capability** (`resolve_deliverable_naming`,
`execute_tools/deliverable_spec.py:380` — four states, F-A4-1 closed by PR-12d
seam E): a composed task that names its own artifacts through its data path is
**refused** an indexed template; a composed task that does not (TIDMAD's own
manifest) still resolves the shipped one; the un-composed path is
byte-unchanged.

## Task-neutrality — closed by PR-12d

The execution path below the composition edge is task-neutral end to end. The
six boundary rows this section used to carry as ⏳ are all landed:

| | status | evidence |
|---|---|---|
| training child receives the task scope | ✅ | `task_scope_argv` in `execute_training`, `core/sandbox_executor.py:1542` |
| inference child receives the task scope | ✅ | `task_scope_argv` in `execute_inference`, `:1839`; parsed at `execute_tools/inference_single.py:147` |
| scoring child receives the task scope | ✅ | `task_scope_argv` in `execute_scoring`, `:2180`; parsed at `execute_tools/denoising_score_single.py:76` |
| scoring child is task-neutral | ✅ | task-owned route: run-bound `TaskDataPath` resolution + `_emit_task_owned_score` (`denoising_score_single.py:178,195`), payload via `read_evaluation_payload` |
| inference iteration is task-neutral | ✅ | a supplied scope artifact ⇒ the child iterates the task's own evaluation scope and writes through `write_deliverable` (`inference_single.py:142-155`) |
| a pack's model plugin reaches a composed child | ✅ | `model_plugins:` / `loss_plugins:` → run-scoped binding → env **union** at every spawn (`core/subprocess_env.py::subprocess_env`) |

The real-run witnesses are the `G-12d` Pets and DAVIS composed runs (one formal
round each, persisted in the packs' `STATUS.md`) and `G-12e`'s external package.
Still deliberately open: HealthGate evaluation on the composed chain path
(declared debt, PR-12d ledger §A1).

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

| concern | location |
|---|---|
| scope argv emitter | `execute_tools/scope_artifact.py:252` (`task_scope_argv`), validation rows `:313` |
| manifest argv | `core/sandbox_executor.py:847` (`_task_manifest_argv`) |
| data-root argv | `:823` (`_data_root_argv`) |
| training spawn | manifest `:1444`, data root `:1445`, scope `:1542` |
| inference spawn | manifest `:1817`, data root `:1818`, scope `:1839` |
| scoring spawn | `--raw_data_dir` `:2166`, manifest `:2167`, scope `:2180` |
| child env (plugin-root union) | `core/subprocess_env.py::subprocess_env` |
| role ceilings | `core/execution_calibration.py:95`, resolver `:152` |
| ceiling consumer | `core/sandbox_executor.py:137` (`_subprocess_rss_gb`) |
| deliverable naming | `execute_tools/deliverable_spec.py:92` (`DeliverableNaming`), resolution `:380` |

## Related

- [Data path and scope](data-path-and-scope.md) · [Plugins](plugins.md) · [Composition](composition.md)
- [Supported tasks and maturity](../../concepts/supported-tasks.md)
