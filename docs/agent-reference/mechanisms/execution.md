# Execution and subprocess transport

**Semantic owners**: `core/sandbox_executor.py`,
`core/execution_calibration.py`, `execute_tools/{train_engine_sandbox,
inference_single, denoising_score_single}.py`
**Status**: 🟡 Current, with a stated task-neutrality boundary

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
| inference | `execute_tools/inference_single.py` | `--data_dir` = physical data root |
| scoring | `execute_tools/denoising_score_single.py` | `--raw_data_dir` = physical data root; its `--data_dir` is the **deliverable** dir |

> **Do not conflate the two `--data_dir`s.** For scoring, `--data_dir` is the
> deliverable directory and the physical root is `--raw_data_dir`. This is the
> single most confusable thing in the transport surface.

## What crosses the boundary

| value | mechanism | emitted |
|---|---|---|
| physical data root | `--data_dir` / `--raw_data_dir` | **only when composed** |
| task manifest path | `_task_manifest_argv()` | at all three spawn sites, **only when bound** |
| task scope | artifact path + sha256 digest | **training child only** — see below |
| declared metric | the scoring child re-composes it from the transported manifest | **no fallback** — a failed composition terminates the subprocess |

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

⚠ Absence of the manifest's `deliverable` section currently resolves to that same
TIDMAD template. Narrowing is owned by the unmerged PR-12d.

## Task-neutrality boundary — read before assuming

On landed `master` the execution path below the composition edge is **not**
task-neutral end to end:

| | status | evidence |
|---|---|---|
| training child receives the task scope | ✅ | `_task_scope_argv` sole call site, `core/sandbox_executor.py:1622` |
| inference child receives the task scope | ⏳ | `grep -c task_scope inference_single.py` = 0 |
| scoring child receives the task scope | ⏳ | `grep -c task_scope denoising_score_single.py` = 0 |
| scoring child is task-neutral | ⏳ | builds its sample set from TIDMAD topology **at module level, unguarded**; `tidmad_topology` fails closed for a profile with none |
| inference iteration is task-neutral | ⏳ | iterates partition → segments via `profile_dataset.validation_file_name` |
| a pack's model plugin reaches a composed child | ⏳ | `SIDERIUS_PLUGIN_DIRS` injected only by the two Gate harnesses; zero occurrences in the chain launchers |

All six are 🧭 PR-12d's scope. Until it lands, only TIDMAD runs the full chain.

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
| scope argv | `core/sandbox_executor.py:902` |
| manifest argv | `:960` |
| data-root argv | `:893` |
| training spawn | `:1447`, manifest `:1554`, scope `:1622` |
| inference spawn | `:1825`, manifest `:1901` |
| scoring spawn | `:2189`, `--raw_data_dir` `:2224`, manifest `:2225` |
| role ceilings | `core/execution_calibration.py:95-149`, resolver `:152` |
| ceiling consumer | `core/sandbox_executor.py:123` |
| deliverable naming | `execute_tools/deliverable_spec.py:92-130` |

## Related

- [Data path and scope](data-path-and-scope.md) · [Plugins](plugins.md) · [Composition](composition.md)
- [Supported tasks and maturity](../../concepts/supported-tasks.md)
