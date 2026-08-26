# Supported tasks and current maturity

**Audience**: anyone deciding whether SIDERIUS can run *their* task today.
**Reflects**: landed `master` at `23276743` (2026-08-25).

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
| **real training / inference / scoring executed** | ✅ | ✅ | ✅ |
| **runs through the production chain** | ✅ | ✅ | ✅ |
| **full agent loop demonstrated** | ✅ | 🟡 *(one composed iteration)* | 🟡 *(one composed iteration)* |
| **persistent example pack** | ✅ *(read-only projection)* | ✅ | ✅ |
| **declared maturity** | **L4** | **L4** | **L4** |

### What the Pets and DAVIS rows mean concretely

Both contrast tasks now run through the **normal composed production chain**
across the real subprocess boundary — PR-12d landed this (`84d74280`, PR #274).
All three child processes (training, inference, scoring) receive the task's
scope as a hash-verified artifact; the inference child iterates the task's own
evaluation scope; the scoring child resolves the run-bound `TaskDataPath` and
the run's declared metric with no fallback; and the packs' model plugins are
declared in the manifest and reach every child. The `G-12d` witness runs are
persisted: one formal round each, `status: success`, with the primary and both
declared secondaries evaluated (Pets `accuracy` 0.0946, `macro_f1`, `log_loss`;
DAVIS `mse` 0.016067, `psnr`, `mae`) — recorded in each pack's `STATUS.md`.

Three honesty caveats those runs do **not** erase:

- **No scientific claim.** The recorded values are observations from a
  single-round plumbing witness, not benchmark results. Pets' 0.0946 against a
  37-way chance of 0.027 says the plumbing works, not that the model is good.
- **Zero health gates fired on either composed run.** HealthGate evaluation is
  still reached only on the legacy chain branch; this is declared debt in the
  PR-12d ledger (§A1), stated the same way in
  [bring your own health checks](../guides/bring-your-own-health-checks.md#an-honesty-note-about-enforcement-today).
- **One round each, not a chain.** No multi-iteration composed behaviour for
  either pack is evidenced yet — hence the 🟡 in the loop row above.

The earlier direct-execution harness era also left one artefact worth knowing:
a genuine, reproducible Pets constant-prediction collapse (accuracy 0.027 —
chance), kept deliberately as committed health-gate evidence rather than tuned
away.

## Capability status

| capability | status | note |
|---|---|---|
| task composition manifest binds a whole run | ✅ | thirteen known sections, five required; unknown keys refused |
| out-of-tree plugin by `file:` reference | ✅ | data path, metric, health checks and view providers |
| plugin content hashed into the run fingerprint | ✅ | an edited plugin is detected, not silently used |
| declared secondary metrics carried through the lifecycle | ✅ | evaluated, recorded, rendered; never an ordering operand |
| task-owned health family, thresholds and plugins | ✅ | external task needs no SIDERIUS edit |
| task-owned scope construction (`TaskScopeCapability`) | ✅ | crosses to **all three** children as a hash-verified artifact |
| task scope reaches inference and scoring children | ✅ | emitted at all three spawn sites; the child verifies the digest before deserializing |
| generic (non-TIDMAD) inference iteration | ✅ | with a scope artifact, the inference child iterates the task's own evaluation scope |
| generic scoring handoff | ✅ | the scoring child resolves the run-bound data path + declared metric; **no fallback** |
| pack model plugin visible to a composed run | ✅ | `model_plugins:` / `loss_plugins:` manifest sections; declared roots reach every child spawn |
| Pets `macro_f1` / `log_loss`, DAVIS `psnr` / `mae` evaluated | ✅ | pack-local implementations; evaluated on the `G-12d` composed runs |
| omitting `deliverable` means "nothing" rather than "TIDMAD's template" | ✅ | a composed task that names its own artifacts gets an honest refusal, never TIDMAD naming |
| one documented run command per example pack | ✅ | `examples/<pack>/quickstart.sh` — a thin adapter over the normal chain launcher |
| complete out-of-tree task *package* contract | ✅ | PR-12e — see [what a task must provide](task-package.md) |
| a fourth task running with zero framework edits | ✅ | the `G-12e` graduation proof: an external event-sequence package ran the composed workflow with the production source byte-identical before and after |
| health gates firing on the composed chain path | ⏳ | declared debt (PR-12d ledger §A1) — a composed run records zero gate results today |

## Where this is heading

Step 12 of the framework roadmap was the *graduation* step: its goal was that a
materially new scientific task package living **outside** the SIDERIUS source tree
can declare all of its semantics through public mechanisms and run the normal
workflow — parent process and every child process — with **zero** edits to
SIDERIUS production source.

All four of its children have landed — 12a (#248), 12bc (#249), 12d (#274) and
12e (#306) — plus the C12-P composed admission/preflight closure (#295/#298/#296).
The graduation claim is evidenced: the `G-12e` run executed an external
event-sequence package through the composed workflow, across a real process
restart, with the production-source sha256 manifest byte-identical before and
after. The one deliberately open row above — health gates on the composed chain
path — is named debt, not an oversight.

---

## Next

- [What a task must provide](task-package.md)
- [Define your own task](../guides/define-a-task.md)
- Example packs: [TIDMAD](../../examples/tidmad/README.md) · [Oxford-IIIT Pet](../../examples/oxford_iiit_pet/README.md) · [DAVIS](../../examples/davis_future_prediction/README.md)
