# Supported tasks and current maturity

**Audience**: anyone deciding whether SIDERIUS can run *their* task today.
**Reflects**: landed `master` at `cfaa5572` (2026-08-23).

This page exists so that nobody has to reconstruct the answer from design
documents. It states what works now, what is being built, and — where those
differ — which is which.

---

## Status vocabulary

| tag | meaning |
|---|---|
| ✅ **Current** | implemented on `master` and exercised by real execution evidence |
| 🟡 **Partial** | implemented, but with a stated limitation or limited verification |
| 🧭 **Planned** | design frozen, implementation not landed |
| 📝 **Draft** | design exists but is not frozen |
| ⏳ **Not implemented** | — |
| ⚠ **Legacy** | works, kept for compatibility, not the path to build on |

## The framework is contract-driven, not modality-limited

There is no list of supported data types in SIDERIUS source, and nothing branches
on a task's name. Whether your task is supported is decided by whether it can
express itself through the framework's contracts:

- can your data access fit the four `TaskDataPath` methods?
- can your topology be described by a `DatasetProfile` (a partition count plus an
  opaque, task-owned payload)?
- can your notion of "better" be a single scalar with a declared direction?
- can your notion of "invalid" be expressed as checks over peeked outputs?

If yes, the framework has no opinion about whether your data is a waveform, an
image, a volume or a graph.

That said, **"expressible" and "demonstrated" are different claims**, and the
table below keeps them apart.

## The three example tasks

| | TIDMAD | Oxford-IIIT Pet | DAVIS 2017 |
|---|---|---|---|
| **shape** | 1-D scientific signal | RGB image | RGB spatiotemporal |
| **task** | SQUID time-series denoising | 37-way breed classification | 8→4 future-frame prediction |
| **model I/O** | `[B,T] int → [B,256,T] float` | `float32 [3,144,144] → class id 0…36` | `float32 [3,8,128,224] → float32 [3,4,128,224]` |
| **primary metric** | denoising score, higher | accuracy, higher | global MSE, lower |
| **expressible by current contracts** | ✅ | ✅ | ✅ |
| **real data path implemented** | ✅ | ✅ | ✅ |
| **real training / inference / scoring executed** | ✅ | ✅ *(via harness)* | ✅ *(via harness)* |
| **runs through the production chain** | ✅ | ⏳ | ⏳ |
| **full agent loop demonstrated** | ✅ | ⏳ | ⏳ |
| **persistent example pack** | ✅ *(read-only projection)* | ✅ | ✅ |
| **declared maturity** | **L4** | **L2/L3 executable** | **L2/L3 executable** |

### What the Pets and DAVIS rows mean concretely

Both contrast tasks execute real data loading, real training, real inference and
real scoring against real downloaded datasets. They do so through **direct
execution harnesses** (`scripts/run_pets_gate2.py`, `scripts/run_davis_gate2.py`)
which call the experiment runner in-process.

They do **not** currently run through the production chain, because the execution
path below the composition edge is not yet task-neutral end to end:

- only the *training* child process receives the task scope; the inference and
  scoring children do not;
- the scoring child is unconditionally TIDMAD-shaped — it derives its sample set
  from TIDMAD topology at module level, and fails closed for any profile that has
  none;
- the inference child iterates partitions using TIDMAD's file/segment topology;
- a task pack's model plugin is not made visible to a composed run's children.

Closing all four is the entire purpose of the unmerged **PR-12d**. Until it
lands, a statement like "SIDERIUS runs image classification end to end" is true
only of the harness, and this documentation will not say it any other way.

Pets is also worth reading about for a second reason: its measured accuracy is
0.027 — chance for 37 classes. That is a genuine, reproducible
constant-prediction collapse, kept deliberately as health-gate evidence rather
than tuned away.

## Capability status

| capability | status | note |
|---|---|---|
| task composition manifest binds a whole run | ✅ | five required sections; unknown keys refused |
| out-of-tree plugin by `file:` reference | ✅ | data path, metric, health checks and view providers |
| plugin content hashed into the run fingerprint | ✅ | an edited plugin is detected, not silently used |
| declared secondary metrics carried through the lifecycle | ✅ | evaluated, recorded, rendered; never an ordering operand |
| task-owned health family, thresholds and plugins | ✅ | external task needs no SIDERIUS edit |
| task-owned scope construction (`TaskScopeCapability`) | ✅ | crosses to the **training** child as a hash-verified artifact |
| task scope reaches inference and scoring children | ⏳ | 🧭 PR-12d |
| generic (non-TIDMAD) inference iteration | ⏳ | 🧭 PR-12d |
| generic scoring handoff | ⏳ | 🧭 PR-12d |
| pack model plugin visible to a composed run | ⏳ | 🧭 PR-12d |
| Pets `macro_f1` / `log_loss`, DAVIS `psnr` / `mae` evaluated | ⏳ | declared in the packs; 🧭 PR-12d implements them |
| omitting `deliverable` means "nothing" rather than "TIDMAD's template" | ⏳ | ⚠ current absence resolves to TIDMAD naming; 🧭 PR-12d narrows it |
| one documented run command per example pack | ⏳ | 📝 PR-12e (design **not frozen**) |
| complete out-of-tree task *package* contract | ⏳ | 📝 PR-12e — the `file:` primitive exists; the package contract does not |
| a fourth task running with zero framework edits | ⏳ | 📝 PR-12e — the graduation proof |

## Where this is heading

Step 12 of the framework roadmap is the *graduation* step: its goal is that a
materially new scientific task package living **outside** the SIDERIUS source tree
can declare all of its semantics through public mechanisms and run the normal
workflow — parent process and every child process — with **zero** edits to
SIDERIUS production source.

Two of its four children have landed (12a, 12bc). PR-12d closes the contrast
execution path; PR-12e is the graduation proof and its design is still a draft.

When those land, the rows above move from ⏳ to ✅ — and updating this page should
be a small mechanical edit, which is why the current and target states are kept in
one table rather than in two documents that can disagree.

---

## Next

- [What a task must provide](task-package.md)
- [Define your own task](../guides/define-a-task.md)
- Example packs: [TIDMAD](../../examples/tidmad/README.md) · [Oxford-IIIT Pet](../../examples/oxford_iiit_pet/README.md) · [DAVIS](../../examples/davis_future_prediction/README.md)
