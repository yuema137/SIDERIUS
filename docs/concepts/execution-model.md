# The execution model

**Answers**: what runs in a subprocess, under what limits, and how a task's
declarations reach it.

For implementer-depth detail (spawn sites, argv shapes, source map) see the
[execution mechanism reference](../agent-reference/mechanisms/execution.md).

---

## Everything heavy runs in a sandboxed child process

The three heavy workloads — **training**, **inference**, **scoring** — never
run inside the agent process. `core/sandbox_executor.py` launches each as a
child subprocess with role-scoped address-space limits and explicit task
transport. Watchdog-owned launches use process-group control; ordinary untimed
subprocess launches do not promise a separate process group.

| role | child entrypoint | what it does |
|---|---|---|
| training | `execute_tools/train_engine_sandbox.py` | train one candidate, emit typed training history |
| inference | `execute_tools/inference_single.py` | produce the deliverables |
| scoring | `execute_tools/denoising_score_single.py` | evaluate the declared metric over the deliverables |

The boundary lets the parent capture child failures and apply its continuation
policy. It also requires task bindings to cross through explicit transport.
Process separation does not guarantee host survival, recovery from every CUDA
failure, or security isolation of generated code.

> One argv trap worth knowing even at this altitude: the scoring child's
> `--data_dir` is the **deliverable** directory; its physical data root
> arrives as `--raw_data_dir`. For training and inference, `--data_dir` *is*
> the physical root.

## Memory ceilings: declared, with provenance

Each role runs under an `RLIMIT_AS` ceiling declared in
`core/execution_calibration.py::ROLE_CEILINGS` — not a magic number in the
launch path. Every ceiling carries machine-readable provenance: a
`derivation` (`measured` / `incident` / `empirical_unverified`), the date it
was set or confirmed, the host it was calibrated for, and a one-line
rationale.

| role | GiB | derivation |
|---|---:|---|
| training | 40 | measured |
| inference | 60 | ⚠ `empirical_unverified` — the value is known necessary (full-scope baseline inference fails under 40), but its recorded arithmetic no longer describes the current code; re-measuring is named debt. **Lowering it without re-verifying full-scope baseline inference is a regression.** |
| scoring | 24 | incident — pinned by a real 2026-04-20 OOM-kill mid-scoring |

`RLIMIT_AS` limits process virtual address space. It can cause allocations to
fail within the child and allow a structured host-memory failure record; it is
not a guarantee against every kernel OOM event or host-wide memory problem.

**Resolution is exactly two layers, and no third**:
`SIDERIUS_SUBPROCESS_RSS_GB`, then the role's declared default. The override
accepts one nonnegative integer for every role or a complete mapping such as
`training=0,inference=96,scoring=24`. `0` disables that role's ceiling
entirely (a deliberate operator escape hatch). A malformed override —
`RSS_GB=4O` with a letter O — **refuses loudly**
(`MalformedCeilingOverride`) instead of silently falling back: an ignored
override is how a run comes to execute under limits nobody chose.

The run-invariants lock **records** the resolved ceilings as provenance and
never compares them — resuming the same science on a differently-calibrated
host stays legal.

## Admission: the tuner prices work before spending GPU time

Before a training attempt runs, the tuner's runtime-control layer estimates
its cost from measured observations (per-host calibration under
`~/.siderius`, server profiles in `core/server_configs/`). An attempt whose
predicted footprint does not fit is **rejected at admission — and the
rejection consumes the attempt**, so an agent cannot propose unpayable work
for free. In-subprocess setup measurement then verifies the estimate against
the first real steps.

One honest boundary: pre-run admission currently prices the *training* phase
only — the training child's validation pass is priced for runtime prediction
and the watchdog, not at admission (a recorded open item, Q-07c-6).

## Watchdog selection

The standard CLI accepts explicit enable/disable choices. When omitted, the
watchdog policy is resolved from the selected hardware/profile inputs rather
than a universal disabled default. `workflows.runtime_settings` records the
resolved choice and its provenance. Enabled watchdogs can terminate a child
process group when its deadline is exceeded. See the
[launch reference](../reference/entrypoints.md) for controls and refusal rules.

## Transport is emitted only when bound

A run composed from a task manifest transports its bindings to every child —
the physical data root, the manifest path (each child re-composes its own
bindings from it), the task scope as a **hash-verified artifact** (the path
and sha256 digest go on argv; raw scope JSON never does; the child recomputes
the digest and refuses a mismatch *before* deserializing), and the pack's
plugin directories. The scoring child composes the run's **declared metric**
with **no fallback** — a failed composition terminates the subprocess rather
than silently scoring with the wrong task's metric.

Transport helpers emit task inputs from their bindings. Missing bindings are
not a supported scientific fallback: production data and metric resolvers refuse
absent authority.

Deliverable file naming is declared by the task and validated by
`DeliverableNaming` (`extra="forbid"` — a misspelled key refuses rather than
silently resolving to the shipped template). A composed task that names its
own artifacts in its data path gets an honest refusal from the indexed-naming
capability instead of a template it never writes.

## Where to go next

- [Operating a run](../guides/operating-a-run.md) — budgets, scope, refusal table
- [Execution mechanism reference](../agent-reference/mechanisms/execution.md) — spawn sites and source map
- [`core/README.md`](../../src/core/README.md) — the execution substrate's module map
- [Data paths](data-paths.md) — the task side of the same boundary
