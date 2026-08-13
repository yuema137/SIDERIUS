# Step 03 — Model / Loss Contract — detailed design (parent)

## 0. Status and verified prerequisites

**STEP 03 DESIGN — READY FOR OPERATOR FREEZE (revision 2, 2026-08-13).**

Design only. No implementation, no branch, no Gate has been run.

### 0.1 Verified base (mechanical, not conversational)

| Fact | Value |
|---|---|
| Design base | `136214b9` = `origin/master`, clean tree |
| Step 00 / 01 | MERGED — PR #198; 01a PR #199, 01b PR #201 |
| Step 02 | **COMPLETE / MERGED** — 02a `47359538`, 02b `c17469ec`, 02c `1807054b`; governance sync `1826f9fd` |
| Step-03 document | created at `136214b9` (revision 1); this is **revision 2** |

### 0.2 Revision 2 — what the operator review changed

Revision 1 was approved **in principle**. Six operator decisions and four
contract corrections were applied. The two that changed the design's
shape:

1. **ONE PR, not two** (§6). Revision 1 refuted itself: its own PR-03b
   block said *"MERGE ALONE? NO — strictly after 03a"*. A unit that can
   never merge alone is an internal milestone, not a delivery unit.
   Different Gate classes are not a reason to split.
2. **Dataset dtype ≠ model-boundary dtype** (§4a). Revision 1's
   "contradictions with the Dataset Profile fail closed" would have
   mis-classified the *currently correct shipped conversion* as a
   contradiction.

Two further corrections came from source audits run for this revision
(§1 rows 11-12): R2-6 is narrower and more concrete than revision 1
claimed, and there is an in-repo precedent for the dtype fix.

### 0.3 There was no Step-03 draft before revision 1

Recorded because the original task assumed one. The folder held only
steps 00-02; the README said *"not created"*; roadmap §15.1 said NOT
STARTED. The hypothesis came from roadmap §5, Step-01's deferred
decision **D13** (FX-3/FX-4, assigned to *"the contract owner"* — Step 02
correctly did not land them), and Step 02's completed Dataset Profile.

### 0.4 Revision-2 landing provenance

Revision 2 was authored in a design session that was lost before it
could write to the repository. It is landed here from that session's
scratch artifact, **re-verified against the current checkout** rather
than trusted: every source claim carrying a file, line or count in §1
was re-run against `136214b9` before this document was written (§1
footnote).

A second scratch artifact from the same session, a nine-commit
implementation choreography, was **audited and deliberately not
appended**. What it contributed, and why the rest is excluded, is §17.

---

## 1. Source audit of current master

Rows 1-10 verified at `1826f9fd`; rows 11-12 added by revision 2's
audits.

| # | Hypothesis | Current source evidence | Still true? | Corrected understanding | Consequence |
|---|---|---|---|---|---|
| 1 | `ForwardContract` carries shapes as PROSE | `agent/schemas/task_config.py:50-99` — `input_shape: str`, `output_shape: str`; only `num_classes: int` is structured | **TRUE** | No structured tensor representation exists anywhere | the core deliverable |
| 2 | 256 hardcoded across builtins | **27 lines** in `ml_models/models_sandbox.py` contain `256` | **TRUE** | class count is a construction literal | Phase B derives it |
| 3 | Dtype at the model boundary is NAME-keyed | **6 sites**: `train_engine_sandbox.py:614,660,817,1029`; `inference_single.py:213,410` | **TRUE, and sharper** | the **input dtype of a real training tensor** is chosen by a model-NAME comparison — fails silently, in the data path | Phase B's primary failure class |
| 4 | `output_type` alphabet asymmetric; `hybrid` ungeneratable | `plugin_loader.py:82` accepts 3 values; `proposal.py:974` / `implementor.py:189` are `Literal` of 2 | **TRUE** | `hybrid` is reachable **only** for builtin `fcnet`; the loader's hybrid arm is dead for plugins | §8c — legacy-only adapter |
| 5 | Loss compatibility has a single authority | `models_format_sandbox.py:374`, documented *"THE production authority"*, two named consumers | **TRUE** | do **not** create a second loss declaration | §8a — re-key only |
| 6 | Loss families are shape-coupled | frozenset docstrings: *"per-timestep class logits, [B, C, T]"* vs *"a continuous waveform, [B, T]"* | **TRUE** | loss legality is a **function of the output tensor contract** | why loss cannot split from the contract |
| 7 | Step 01 left renderer survivors | `workflows/task_config.py:209` — `" (per-timestep {num_classes}-class)" if fc.num_classes` | **TRUE** | the renderer asserts a **temporal axis** whenever a class count exists | derive from axis ROLES |
| 8 | FX-3/FX-4 owned by "step 2 §4 / step 3 §5" | roadmap §14 D13 | **TRUE** | Step 02 closed without them, correctly | **binding** Stage-B rungs |
| 9 | `[B,256,T]` prose is confined to the contract | **FALSE — duplicated** at `validator.py:200`, `implementor.py:195`, `proposal.py:996`, `models_format_sandbox.py:367,371` | **NEW (rev 1)** | the contract is already **four** independent prose restatements, two hardcoding `256` | Stage-A must cover every site |
| 10 | Encoding/cardinality unowned | **FALSE since 02a** — `ValueEncoding` declares `num_classes`, `value_offset`, `storage_dtype`, `compute_dtype` | **CHANGED BY STEP 02** | the data-side fact has an owner | DERIVE / cross-validate (§4b) |
| **11** | R2-6 is "description ↔ contract consistency" | `configs/task_config.yaml:10-14` — the shipped `task_description` literally reads *"map a noisy **[B, T]** integer signal to a clean **[B, 256, T]** reconstruction"* | **TRUE but far narrower than rev 1 claimed** | this is **prose duplication of a contract-owned fact**, not a free-text semantic-agreement problem. It is a **FIFTH restatement site** | §9 — authority fix, NOT an NLP validator |
| **12** | The dtype fix has no precedent | `agent_generated/_loss_loader.py:220` defines **`LOSS_TARGET_DTYPE_REGISTRY`**; `loss_models_sandbox.py:101` populates it per plugin; `train_engine_sandbox.py:665-668` consumes it, commented *"single source of truth for target dtype routing"* | **NEW** | contract-keyed dtype routing **already exists for TARGETS** (I13). The input side is the un-migrated half | Phase B follows an in-repo precedent, not a new invention |

**Row 12 is the sharpest fact in this audit.** The two halves are
*adjacent lines in the same loop body*:

```text
train_engine_sandbox.py:660   INPUT dtype   <- model_cfg.model_type == "fcnet"      NAME branch
train_engine_sandbox.py:668   TARGET dtype  <- get_target_torch_dtype(loss_cfg)     CONTRACT-keyed
```

Phase B makes line 660 look like line 668. That is the whole of the
dtype work — a migration to an established in-repo pattern, not a new
abstraction. Roadmap §5.1's estimator precedent
(`training_skill/estimator.py:305-319`, migrated to signature
introspection) is the second such precedent.

> Re-verified at `136214b9` for this landing: rows 2, 3, 7, 11 and 12
> were re-run mechanically against the current checkout. All hold as
> written.

---

## 2. Final observable Step-03 effect

> **A task declares ONE normalized, rank-agnostic model I/O contract —
> one structured input tensor and one structured output tensor,
> optionally authored through a semantic preset — and the production
> consumers that today restate `[B, 256, T]` prose or branch on a model
> NAME resolve that single declaration instead. Machine-checkable
> contradictions between the contract, its preset and the Dataset
> Profile's shared facts are rejected as typed failures before any
> LLM-facing or executable consumer sees them, while every TIDMAD model,
> loss and rendered prompt byte behaves exactly as today.**

### 2.1 What Step 03 explicitly does NOT prove or claim

- **no free-text semantic validation** — arbitrary agreement between a
  natural-language `task_description` and the tensor contract is not
  claimed and not implementable (§9);
- **no arbitrary tensor multiplicity** — single input, single output
  (§4c);
- that generated models **execute**, or that arbitrary **probes** can be
  built — Step 04;
- that every implementor/validator **prompt** is generic — Step 04;
- arbitrary **metrics** — Step 06; **HealthGate** — Step 08;
  **orchestration binding** — Step 10; **composition** — Step 12.

---

## 3. Ownership

**Step 03 OWNS:** the normalized single-input/single-output tensor
contract (rank, ordered axes, semantic axis roles, dtype,
fixed/symbolic/dynamic dimensions — including the **shared symbolic
dimensions and axis roles** through which input and output alignment is
expressed); preset **resolution** into it; the consistency boundary
(FX-3/FX-4 + shared Dataset-Profile facts); the canonical output
semantic authority; loss legality as a **derivation**; contract-keyed
**model-boundary dtype routing** and cardinality derivation.

**Step 03 does NOT own a general cross-tensor relationship semantic**
(§4e) — that is deferred, for the same consumer-less-seam reason as
multi-tensor I/O.

**Step 03 does NOT own:**

| Not owned | Owner | Why |
|---|---|---|
| topology, naming, decomposition, dataset legality, channel identity, **dataset encoding declaration**, SampleSet, task-owned file sets | **Step 02 (merged)** | consume and cross-validate; never a second authority |
| **`task_type`** | **Step 01 / task-description layer** | opaque prompt/task framing. Step 03 must **not** branch on it, validate from it, or derive tensor semantics from it. Preserved unchanged for TIDMAD (operator Q4) |
| **registry population via import side effect; bare-`except` loading; module discovery** | **Step 11** | execution infrastructure. Step 03 may PIN registry contents/availability for parity, but does not own the loading mechanics (operator Q5) |
| probe tensor **construction**, `_PROBE_NUM_CLASSES`, shape probes, implementor/validator prompt mechanics, generated-plugin templates, forbidden-pattern enforcement, generated-code execution | **Step 04** | Step 03 owns the CONTRACT those mechanics consume, not their execution (§10) |
| metric identity | Step 06 | |
| estimator cardinality / resource derivations | Step 07d | will derive from this contract |
| HealthGate semantics | Step 08 | |
| orchestration / task binding | Step 10 | |
| spawn / IPC / rlimits / discovery | Step 11 | |
| composition root, universal Regime-B "missing required contract" | Step 12 | |

**No mega TaskConfig.** One contract, not a task-wide config object.
Dataset Profile and Model-I/O Contract remain **distinct concepts**
(§4a, §18).

---

## 4. Contract scope and the three authority boundaries

### 4a. Model-boundary dtype vs dataset dtype — **DISTINCT, not equal**

The most important semantic correction in revision 2.

Source (`train_engine_sandbox.py:658-660`), verbatim comment and code:

```text
# 1. Input: Based on Architecture
# The forward contract is [B, T] int64 for all embedding-based models.
# Only fcnet (AE) uses float input for regression.
input_seq = input_seq.float() if model_cfg.model_type == "fcnet" else input_seq.int()
```

The decoded dataset tensor is **converted** at the model boundary, and
the conversion is selected by model NAME. Both arms are legitimate today.

Therefore the authority model is:

```text
Dataset Profile        what the stored/decoded data PROVIDES
                       (storage_dtype, compute_dtype, value_offset)

Model I/O Contract     what dtype the model input boundary REQUIRES

Step-03 execution      resolves a SUPPORTED, EXPLICIT adaptation
                       between the two
```

**Requiring `dataset.compute_dtype == model.input.dtype` would be wrong**
— it would classify today's correct shipped conversion as a
contradiction. Frozen observable semantics:

- TIDMAD reaches **every** builtin with the exact same model-boundary
  dtype as today, `fcnet` included;
- a contrast can vary the model-required input dtype **without changing
  the model name**, and behaviour follows the contract;
- an **unsupported** adaptation fails closed rather than silently
  coercing.

**No general dtype-conversion algebra** beyond what current production
consumers require. Precedent to follow, not invent:
`LOSS_TARGET_DTYPE_REGISTRY` already does exactly this for *target*
dtype, on the adjacent line (audit row 12).

### 4b. Cardinality — DERIVE / CROSS-VALIDATE, never redeclare

`ValueEncoding.num_classes` is the **dataset-side data fact** (Step 02).
For categorical/classifier output semantics, model output cardinality
**derives from or explicitly cross-validates against** it. **No second
independently configurable class count.**

Where class cardinality is **not meaningful** for the output semantic
(e.g. a continuous-output contract), the dataset class-count fact is
**not** forced into the model output contract. That asymmetry is
deliberate and must be **explicit in the schema**, not implied by a `0`
sentinel as today. A legacy magic number is not promoted into the
contract.

### 4c. Tensor multiplicity — **single in / single out** (operator Q3)

Step-03 v1 represents exactly what is consumed today:

```text
ONE structured input tensor + ONE structured output tensor
  arbitrary rank · ordered axes · semantic axis roles · dtype
  fixed / symbolic / dynamic dimensions as source-supported
```

**No tensor-multiplicity containers** (`inputs: [...]` / `outputs: [...]`)
are added to future-proof the schema — that is the consumer-less seam
roadmap §0 rule 8 forbids. Multi-input/multi-output is recorded as a
**later additive extension** once a real production consumer exists. The
final effect, ownership and capability matrix must not claim it as
delivered, and **it is not a Stage-B rung** (§11).

### 4e. Cross-tensor relationships — **DEFERRED, no relation DSL** (operator decision)

Revision 2 as first landed listed `input↔output relationships` with
**zero live consumers** and a disposition of **DECLARE**. That
contradicted this design's own rule — *a declared field lands without a
production consumer* is a **STOP** (§21) — and it contradicted the
reasoning that deferred multi-tensor. Corrected:

> **Step-03 v1 introduces no general cross-tensor relationship
> declaration and no relationship DSL.**

The alignment that current consumers actually need is already
expressible **inside the normalized tensor contract**, through shared
axis roles and shared symbolic dimensions:

```text
input  axis: role = temporal, dim = symbolic T
output axis: role = temporal, dim = symbolic T
                      ^ the SAME symbolic dimension expresses the
                        alignment — no separate surface required
```

So this is **NOT** added:

```yaml
relationships:
  - output.T == input.T        # consumer-less seam — do not build
```

Disposition:

- general cross-tensor relationship semantics → **DEFERRED**;
- shared dimension / axis-role consistency required by today's
  single-input / single-output consumers → **expressed through the
  normalized axis and dimension contract**;
- no relation surface is introduced for future extensibility alone.

**If an implementation pre-read identifies an existing production
consumer that genuinely requires an independently represented
relationship semantic, that is a material source finding: STOP and
report it — do not silently add the field.**

### 4d. Capability matrix

| Capability | Structured today? | Missing? | Live consumers | Step-03 disposition |
|---|---|---|---|---|
| tensor rank, ordered axes, **axis semantic roles** | — | **MISSING** | — | **DECLARE** — roles are what replace rank-specific branching |
| fixed / symbolic / dynamic dimensions | prose only | **MISSING as data** | renderers | **DECLARE** |
| model-boundary dtype | inside a prose string | **MISSING as data** | **6 name-branch sites** | **DECLARE** + Phase B routes from it (§4a) |
| batch/sample semantics | `B` by convention | **MISSING** | — | **DECLARE** as an axis role |
| shared symbolic dimension / axis-role alignment between input and output | prose only | **MISSING as data** | renderers | **DECLARE** — as ordinary axis/dimension semantics, not a relation surface (§4e) |
| general cross-tensor relationship declarations / relation DSL | — | missing | **none** | **DEFER** (§4e) |
| tensor names / multiplicity | — | missing | **none** | **DEFER** (§4c) |
| class cardinality | two producers | — | renderer; 27 builtin literals | **DERIVE / CROSS-VALIDATE** (§4b) |
| `output_type` | 3 competing surfaces | — | validators, loaders | **ONE authority, as a projection** (§8b) |
| loss-family legality | single authority + frozensets | — | 2 consumers | **RE-KEY**, do not re-declare (§8a) |
| output-head semantics | `output_head_note` prose | — | implementor prompt | **DERIVE** from output tensor + roles |
| `task_type` | free-form `str` | — | prompt framing | **NOT OWNED** — Step 01 (§3) |

---

## 5. Stage-A compatibility contract

The governing principle for every row: **assert the observable, never
the configuration.** Validate the dtype, shape and cardinality that
actually reach the model, and the bytes that are actually rendered — not
the field that was set (§16).

| # | Surface | Strongest criterion | Baseline exists? |
|---|---|---|---|
| A1 | rendered proposer prompts (3 stages) + contract block | **TIDMAD bytes BYTE-IDENTICAL.** No pre-authorized golden-delta exception (operator Q6). Goldens pass **unmodified**; `configs/task_config.yaml` round-trips load → normalize → render to today's exact bytes | **YES** — Step-01 `pb3_*` |
| A2 | `validate_output_loss_compatibility` verdicts | the **full cross-product** asserted cell by cell — every `output_type` × every `loss_type`, including `custom` permitted everywhere and `hybrid`. No cell left unasserted | **capture first** |
| A3 | plugin load tolerance tiers | **both tiers pinned as distinct behaviours**: load-time missing/invalid `PLUGIN_OUTPUT_TYPE` → silent `classifier` default; lookup-time `get_output_type` on an unregistered model → fails closed. Their divergence is **pre-existing and not Step 03's to unify** | **capture first** |
| A4 | builtin model forwards | byte-identical outputs, every builtin | **YES** — Step-00 |
| A5 | registry contents | identical under the TIDMAD profile (contents pinned; loading mechanics are Step 11's) | **YES** — Step-00 |
| A6 | **model-boundary dtype** | the exact same tensor dtype reaches each builtin, `fcnet` included — observed **at the model call**, not at the branch condition, and `fcnet` asserted distinctly from the non-`fcnet` arm | **MISSING — capture first** |
| A7 | Step-00 numeric baselines | unchanged | **YES** |
| A8 | prior on-disk generated plugins | still loadable and registering, or a declared and accepted workspace boundary | **MISSING — capture first** |

Capture only A2, A3, A6, A8 — **before** any production change, since
those are exactly the surfaces the work changes. Reuse Step-00/01/02 for
the rest; do not re-pin an existing baseline.

**A1 is a hard byte-identity requirement.** If implementation proves
exact bytes are materially incompatible with the frozen generic
contract, that is a **STOP** and an explicit operator decision — not a
pre-authorized exception (§13, §21).

**Legacy-configuration classes that must keep working** (the Regime-A
inventory): on-disk plugins with no `PLUGIN_OUTPUT_TYPE`; builtin
`hybrid`; a `ForwardContract` authored in the old prose form; a legacy
caller constructing a bare `ForwardContract()`.

---

## 6. PR decomposition — **ONE PR** (operator decision)

```text
Previous proposal (revision 1): TWO children.
Refuted by its own text: PR-03b said "MERGE ALONE? NO — strictly after
03a". A unit that can never merge alone is a milestone, not a PR.
Different Gate classes are not a split criterion; one PR may run Gate 1
at its rendering phase and Gate 2 at its final executable head.
```

Three candidate splits stay rejected for their original source reasons:
**presets** (no independent production consumer), **loss legality** (the
authority exists with two consumers and derives from the output
contract), **output-type alphabet** (same boundary, same oracle).

The phase seam is preserved as a **checkpoint boundary, not a merge
boundary**: Phase A changes no executed tensor; Phase B changes no
rendered prompt. **The Step-03 capability exists only when both phases
are complete.**

---

## 7. The Step-03 PR — capability block

```text
CAPABILITY: a task declares ONE normalized, rank-agnostic model I/O
  contract (one structured input tensor, one structured output tensor)
  with ordered axes, semantic axis ROLES, dtype and dimension
  constraints — optionally authored via a preset that RESOLVES into it.
  Every consumer that today restates [B,256,T] prose or branches on a
  model NAME resolves that one declaration; machine-checkable
  contradictions fail closed before any LLM-facing or executable
  consumer; TIDMAD rendering bytes and every executed tensor are
  unchanged.

PHASE A — semantic authority (changes no executed tensor)
  normalized contract · preset resolution · consistency validation
  (FX-3/FX-4 + shared Dataset-Profile facts) · canonical output
  semantic authority · loss-legality re-keying · exact TIDMAD rendering

PHASE B — production execution consumption (changes no rendered prompt)
  contract-keyed model-boundary dtype routing (kills the 6 name
  branches) · cardinality derivation (kills the 27 builtin literals) ·
  builtin catalogue / runtime consumption · the real training and
  inference boundary

OWNS / DOES NOT OWN: §3.
CURRENT PRODUCTION CONSUMERS:
  Phase A — workflows/task_config.render_forward_contract and the three
    proposer stages; the shape prose in agent/schemas/{proposal,
    implementor,validator}.py; models_format_sandbox's compatibility
    authority and its two callers.
  Phase B — execute_tools/train_engine_sandbox.py (:614,:660,:817,:1029),
    execute_tools/inference_single.py (:213,:410), ml_models/
    models_sandbox.py builtins, and the class-weight histogram
    (train_engine_sandbox.py:80,126,196).
STAGE-A PARITY: §5 A1-A8.
STAGE-B CONTRAST: §11 ladder, incl. BINDING FX-3 and FX-4.
LIVE CHECKPOINT C: §12.
FAILURE CLASSES PREVENTED:
  (a) a model contract contradicting the data it will be trained on
      reaches the LLM and yields a plausible-but-wrong model;
  (b) a silently wrong tensor dtype or class count in real training —
      invisible to every prompt-level and schema-level test.
DEPENDENCIES: Steps 01 and 02 (merged). No intra-Step dependency —
  there is one PR.
GATES: §13.
STOP CONDITIONS: §21.
```

---

## 8. Output semantics and loss authority

### 8a. Loss — re-key, do not re-declare

`validate_output_loss_compatibility` and its frozensets remain the
**framework implementation-availability authority**. Step 03 only re-keys
their applicability to the canonical output semantics, so legality stops
being inferred from the legacy string `"classifier"`.

- **No task-owned `LossContract`. No `allowed_losses` config.**
  Loss-family membership names implementations that exist *in this
  repository*; it is framework availability, not task-authored
  semantics. A task declaring a family with no implementation is a
  consumer-less seam.
- `custom` stays deliberately permissive for every contract (the
  plugin's forward raises at training time).
- Custom-loss **execution** mechanics (zero-arg instantiation,
  `loss_models_sandbox:253-276`) remain **Step 04**.
- **Verdicts do not change.** A changed accept/reject cell is a policy
  change, not an authority change — that is a **STOP** (§21).

### 8b. `output_type` — a projection, not a second authority

Preferred shape, if current execution consumers permit it:

```text
normalized output tensor semantics        <- the authority
        |
        v
output_type (classifier / regressor)      <- a DERIVED compatibility
                                             projection / view
```

Legacy `Proposal.output_type` and the plugin-loader field may persist as
**compatibility views** during migration. What must not exist is
normalized tensor semantics **plus** an independent competing
`output_type` authority. Exactly one authority must answer *"what output
semantics does this model have"*.

### 8c. `hybrid` — legacy builtin compatibility only (operator Q2)

```text
generic authoring alphabet   classifier / regressor
legacy builtin adapter       hybrid remains accepted for existing
                             compatible builtin state (fcnet)
```

Do **not** promote `hybrid` into the canonical generic authoring
surface: source shows it is reachable for builtin `fcnet` and
unreachable for generated plugins, so exposing it generically would
create a contract value with **no generic consumer**. Do not delete or
behaviour-change existing builtin hybrid. If `hybrid` cannot be projected
from tensor semantics, it stays an adapter value — **do not invent
tensor semantics for it**. This is the Regime-A pattern: preserve history
through an adapter; do not upgrade a historical accident into a
universal promise.

---

## 9. The description ↔ contract channel (R2-6) — narrowed

Revision 1 claimed contradictions with *"the task description"* fail
closed. **That claim is withdrawn.** Source audit:

`configs/task_config.yaml:10-14` — the shipped `task_description` reads
*"map a noisy **[B, T]** integer signal to a clean **[B, 256, T]**
reconstruction"*. It **hand-restates the exact shapes the contract
owns**, making it a **fifth** prose restatement site (audit row 11).

So R2-6 is not a semantics-agreement problem; it is **duplication of an
owned fact**. Dispositions:

| Channel | Disposition |
|---|---|
| preset ↔ normalized contract | **machine-checkable → fail closed** (FX-4) |
| Dataset Profile ↔ normalized contract | **machine-checkable only for source-defined shared/compatibility facts** — cardinality (§4b) and supported dtype adaptation (§4a). Not a blanket equality check |
| renderer-generated contract prose ↔ contract | internally consistent **by construction**, because it is DERIVED from the contract |
| arbitrary free-text `task_description` | **NO automatic validation claimed.** No NLP semantic validator will be built |

**Only machine-checkable overlaps are fail-closed.** The correct fix for
the shipped duplication is **authority, not validation**:
`task_description` should stop hand-restating contract-owned shapes, or
that sentence should be rendered from the contract. Ownership of
`task_description` is Step-01's (§3), so Step 03 **records** this and
coordinates; it does not unilaterally rewrite the task description, and
it does not invent NLP validation. If a future structured
description-derived field creates a genuine machine-checkable overlap,
that becomes a new rung — not now.

---

## 10. Step-03 vs Step-04 boundary — resolved from source

| Item | Owner |
|---|---|
| normalized tensor contract, axis roles, dtype declaration | **03** |
| canonical output semantics, loss-legality derivation | **03** |
| preset resolution + fail-closed consistency | **03** |
| **probe tensor construction**, `_PROBE_NUM_CLASSES`, shape probes | **04** |
| custom-loss probe recipes / zero-arg instantiation | **04** |
| implementor + validator prompt mechanics, plugin templates | **04** |
| forbidden-pattern enforcement, generated-code execution | **04** |
| validator compatibility **rule** vs **running it on generated code** | rule **03**, execution **04** |

Prior documents routed probes inconsistently. **Resolved: semantic
contract → 03; construction and execution → 04.** No conflicting
ownership statement remains.

---

## 11. Stage-B generic contrast ladder

One semantic axis per rung; neutral names — swapping "time series" for
another familiar modality proves nothing.

| Rung | Varies ONLY | Held fixed | What failure exposes a fake abstraction | Phase |
|---|---|---|---|---|
| **3-A** axis structure | rank + ordered axes (roles preserved) | dtype, cardinality, output semantics, dataset | any consumer branching on rank | A |
| **3-B** model-boundary dtype | the dtype the model REQUIRES | axes, cardinality, output semantics, **dataset dtype unchanged** | dtype still resolved from a model name; or a valid adaptation misreported as a contradiction | A → proven in B |
| **3-B-neg** unsupported adaptation | an adaptation source does not support | everything else | silent coercion instead of a typed failure | A |
| **3-C** cardinality | class count only | axes, dtype, output semantics | `256` surviving in any resolved path | B |
| **3-D** canonical output semantic | classifier ↔ regressor | axes, dtype, cardinality | loss legality still keyed on a legacy string | A |
| **FX-3** preset resolution | preset only, over a fixed explicit contract | everything else | a preset producing a second runtime path | A |
| **FX-4** preset mismatch | preset contradicts the explicit contract | everything else | the contradiction reaching LLMBridge, or being silently repaired | A |
| **3-E** dataset consistency | contract cardinality vs `ValueEncoding.num_classes` | everything else | silent coercion, or the contradiction reaching training | A |

**3-B carries the §4a nuance explicitly**: a model-required dtype that
differs from the decoded dataset dtype is a **valid explicit
adaptation**, not automatically a contradiction. **3-B-neg** supplies the
negative evidence that unsupported adaptations still fail closed. The
pair proves both directions of the correction.

### 11.1 What makes a rung count

Binding quality criteria for the ladder as a whole:

- **atomicity is machine-checked, not asserted in prose** — each rung
  varies exactly one axis relative to the TIDMAD declaration, proven
  mechanically (the 02a/02b/02c `_diff_paths` precedent);
- **the unvaried consumer is asserted unchanged** in each rung. That is
  what proves independence, and it is the 02c §19 lesson;
- **vary more than membership** wherever a count could be silently
  assumed (the 02c cardinality lesson);
- **each rung must red when its consumer re-hardcodes its literal** —
  a rung that passes with the literal still present is too weak (02a M9
  / 02b M10 / 02c M-C2-1);
- **a rung that needs two axes to be meaningful is a STOP** — it means
  the contract model, or the rung, is wrong.

**FX-3 and FX-4 are binding** (D13). **Multi-tensor is deferred and is
NOT a rung** (§4c).

---

## 12. Checkpoint C — the live integration checkpoint

One PR ⇒ **one PR-level live checkpoint**, which must jointly prove that
**both** semantic phases are live. Three boundaries:

| | Boundary | Required evidence |
|---|---|---|
| **(i)** | semantic authority — rendering | a **real production LLM-facing rendering path** consumes the normalized contract in a live chain iteration |
| **(ii)** | semantic authority — fail-closed | a **real machine-checkable contradictory configuration** is rejected before the relevant LLM/executable boundary, asserted by **LLMBridge call count == 0** — not by exception type alone |
| **(iii)** | execution | a **real training + inference round** feeds a contract-derived input dtype and cardinality through the **actual subprocess/runtime path** |

Binding qualifications:

- **each boundary must be entered at the production entry point**, not by
  calling a resolver directly (the 02c §12.1 rule);
- **serialization-only or rendering-only evidence is explicitly
  insufficient** for Checkpoint C;
- **arbitrary generated-model execution is NOT required** — that is
  Step 04. (iii) is satisfied by the existing builtin path.

---

## 13. Gates

Decided against the **current** `docs/gates/gate_testing_standard.md`
(283 lines, "Gate assignment by commit type" at :254). With one PR, Gate
choice is not a decomposition argument.

| Gate | Decision | Basis in the current standard |
|---|---|---|
| **Gate 1** | **NOT REQUIRED** by default | The standard triggers Gate 1 on *"a new LLM-facing system prompt"* (:261) and *"new agent node or workflow wiring"* (:262); Step 03 is neither. Its commit types map to *"Config files, YAML, schema-only → Unit only"* (:258) and *"New loader/renderer (pure Python) → Unit only"* (:259). A changed **internal contract representation** is not a trigger |
| **Gate 2** | **REQUIRED** | *"Checkpoint (end of feature) → Gate 2"* (:263), and Gate 2's stated purpose (:48-55) is end-to-end plumbing with real training. Step 03 changes real training/inference **input dtype** and **cardinality** routing — the only boundary at which a wrong dtype or class count manifests |

**The Gate-1 condition, stated mechanically so it needs no operator
call at implementation time:** Gate 1 stays out of scope **if and only
if the entire LLM-visible surface is byte-identical**. That surface is
both (a) rendered prompt bytes (A1's `pb3_*` goldens) **and** (b) the
LLM-facing schema descriptions actually shipped to the model from
`agent/schemas/{proposal,implementor,validator}.py`. Step 03 edits shape
prose in exactly those schema files (§1 row 9). If any byte the model
receives changes, the standard's *"changed LLM-facing schema"* trigger
(:29-30) fires and **Gate 1 becomes required** — and an intentional
LLM-visible byte change is itself a **STOP** for operator reconciliation
first (§5 A1, §21).

If both Gates end up required, **one PR runs both** — Gate 1 at the
rendering phase, Gate 2 at the final executable head. No intermediate
tier. **No Gate is run at design time.**

---

## 14. Evidence economy

One PR ⇒ no child-by-child broad regression.

```text
targeted semantic tests
  -> true affected package tests
  -> atomic contrast rungs / mutations (§11.1)
  -> live Checkpoint C (§12)
  -> required Gate(s) (§13)
  -> terminal broad regression ONLY if it adds unique evidence
  -> exact-final-head CI
```

**A local full suite is not required merely because Step 02 ran one.**
The default position is that **exact-head CI supplies the broad
regression property**, since CI is unit + static over the whole tree at
the exact final SHA. A terminal local full suite is therefore **not
planned**, and may be added only by naming evidence it uniquely
provides that exact-head CI does not — stated before it is run, not
after.

**The number of semantic commits is not pre-authorized** (§17).

---

## 15. Checkpoint ladder

| Checkpoint | Meaning |
|---|---|
| **0** | A2, A3, A6, A8 baselines captured **before** any behaviour change |
| **A** | TIDMAD parity across every owned surface — all five prose restatement sites, the loss matrix, builtin forwards, **model-boundary dtype**, registry contents |
| **B** | §11 rungs pass atomically under §11.1, incl. **FX-3, FX-4, 3-B-neg, 3-E** |
| **C** | the three live boundaries of §12 |
| **D** | risk-targeted regression + static + mutation per §14 |
| **E** | parent / roadmap §15.1 / §14 convergence / folder README synchronized **after merge** |

---

## 16. Evidence and acceptance principles

The operator's commit standard was written for the ordering-engine PR
and names `file_order`, `shuffle`, visited sequence and resume — none of
which exist on Step 03's surface. **Translated, not copied, and not
silently dropped:**

| Standard's requirement | Step-03 analogue |
|---|---|
| *"validate the actual visited sample/file sequence, not only the configuration value"* | validate the **actual dtype, shape and cardinality reaching the model**, and the **actual rendered prompt bytes** — never the config field that was set |
| *"for the default path prove selection, seed, visited sequence and step count unchanged"* | for the **default TIDMAD path** prove rendered prompt bytes, builtin forward outputs, model-boundary dtype per builtin, registry contents and Step-00 numerics all unchanged |
| *"invalid `file_order`, missing files, duplicate files, scope mismatch"* | invalid preset name; unknown axis role; duplicate axis name; a dimension that is neither fixed, symbolic nor dynamic; contract↔dataset cardinality mismatch; unsupported dtype adaptation |
| *"legacy configuration"* | the Regime-A inventory in §5 |
| *"resume behaviour"* | **not applicable** — Step 03 persists no run state. Recorded so it is visibly considered, not forgotten |
| *"propagation failures"* | the contract crossing the **real subprocess boundary** (train / inference) |

Standing constraints for the implementation, at parent level:

- **transport is existing, not invented.** The contract reaches the
  subprocesses through the established config-file/argv mechanism; a new
  IPC mechanism is out of scope (the 02a C3 lesson, and §3 routes IPC to
  Step 11).
- **fail closed on a missing contract at the boundary** — a diagnostic
  naming the missing config, never a silent fall-back to a name branch.
- **resolution is applied at call time, never at import time** (the 02b
  §13.9 lesson).
- **nothing silently repairs**: no TIDMAD fallback, no shape rewriting,
  no preset dropping, no dtype coercion.
- **no preset label is read at runtime after resolution** — greppable.
- **planner exposure and production-default changes are OUT of scope**;
  they need separate evidence and operator approval.
- **no empirical comparison campaign** is authorized by this design.
- **inspect before editing; if inspection reveals ambiguity or a larger
  scope than this design assumes, STOP and ask** — do not silently
  widen (CLAUDE.md design-ambiguity rule).

---

## 17. What this parent deliberately does NOT freeze

The folder README (:56-60) records the convention *"One PR = one design
doc: when one PR suffices, the parent `step_NN_<name>.md` IS the PR doc"*
and carries the operator's per-commit 8-section checklists. Step 03 is
one PR, so those checklists will eventually live in **this** file.

They are **not written at design-freeze time**, by operator decision.
The parent stops at the abstraction level of the final Step-02 parent:
capability, ownership, authorities, compatibility, contrasts, checkpoint,
Gates, evidence economy, routing, stop conditions.

Explicitly **not frozen here**:

- any `C1 … C9` semantic-commit sequence, or a **pre-authorized commit
  count**;
- helper/schema decomposition and internal API shape;
- source-file edit order;
- test module names and mutation ordering;
- exact verification command lines.

Those belong to the implementation design/context, authored **after**
this parent is frozen and implementation is authorized, and after the
re-read of each touched file that the standard requires. A prior
session's nine-commit choreography exists as a scratch artifact; its
**parent-level acceptance content was extracted** into §5, §8a, §11.1,
§12, §14, §16 and §21, and the choreography itself was **not appended**.

---

## 18. Convergence ledger implications

| Row | Disposition |
|---|---|
| ForwardContract / Model I/O contract | Step 03 lands the structured authority. Shared ownership with §6 candidate creation stays **DO-NOT-MERGE** — Step 04 has no completed design, so the ≥2-design bar is unmet |
| Dataset Profile ↔ model-facing contract | **Distinct, deliberately not merged.** Dataset says *what data exists*; the contract says *what the model boundary requires*; §4a resolves the adaptation between them |
| cardinality | ONE authority: dataset declares the fact, the contract derives/cross-validates (§4b) |
| `output_type` | collapses from three surfaces to one **projection** (§8b) |
| loss-family authority | already single; re-keyed, not merged with anything |
| semantic presets | authoring convenience only — **never** a convergence candidate |
| estimator ×256 (§7d) | remains Step-07d's; will derive from this contract |

---

## 19. Cross-step routing

| Finding | Owner | Blocking? |
|---|---|---|
| registry population via import side effect, bare `except` (`models_sandbox:749-755`) | **Step 11** (operator Q5) — Step 03 pins contents only | NO |
| custom-loss zero-arg instantiation | Step 04 | NO |
| `_PROBE_NUM_CLASSES`, probe construction | Step 04 | NO |
| `task_type` ownership | Step 01 / task-description layer | NO |
| `task_description` restating contract-owned shapes (§9) | Step 01 layer, coordinated with Step 03 | NO |
| second builtin name→config map (`models_format_sandbox:338-345`) | Step 03, opportunistic; else Step 04 | NO |
| class-weight histogram fixed 256 bins (`train_engine:80,126,196`) | **Step 03** — a cardinality derivation on the training path | NO |
| dtype-registry "float" arm with zero implementations | Step 04 | NO |
| plugin-loader tolerance tiers diverging (§5 A3) | **pre-existing**; pinned, not unified by Step 03 | NO |
| estimator ×256 | Step 07d | NO |
| metric identity | Step 06 | NO |

**No "owner TBD" remains.**

---

## 20. Adversarial genericity re-review (revision 2)

| # | Attack | Verdict |
|---|---|---|
| 1 | Does the contract represent only semantics with live consumers? | **YES** — multi-tensor deferred (§4c); `task_type` not owned; no task-owned loss config |
| 2 | Did single-in/single-out become a hardcoded TIDMAD shape? | **NO** — rank, axes and roles are declared and varied by 3-A. "One tensor" is a multiplicity bound, not a shape |
| 3 | Are arbitrary rank/axes genuinely supported without modality branches? | **3-A tests exactly this**; branching on rank/modality is a STOP |
| 4 | Did multi-tensor sneak back in? | **NO** — §4c forbids containers; not a rung |
| 4b | Did a consumer-less **relationship DSL** survive? | **NO — corrected before freeze.** The matrix listed `input↔output relationships` as DECLARE with zero live consumers, contradicting §21. Now DEFERRED; alignment rides on shared axis roles + shared symbolic dimensions (§4e) |
| 5 | Did model dtype duplicate dataset dtype? | **NO** — §4a keeps them distinct |
| 6 | Did we wrongly require model dtype == dataset dtype? | **NO — corrected in rev 2.** This was the live error; 3-B + 3-B-neg encode the fix |
| 7 | Is cardinality still duplicated? | **NO** — derived/cross-validated (§4b); 3-E proves it |
| 8 | Is `output_type` a second authority? | **Guarded** — §8b makes it a derived projection |
| 9 | Did `hybrid` become a generic promise? | **NO** — legacy builtin adapter only (§8c) |
| 10 | Did `task_type` become model-I/O authority? | **NO** — explicitly not owned (§3) |
| 11 | Can a machine-checkable contradiction still reach LLM/execution? | **FX-4, 3-E, 3-B-neg + Checkpoint C (ii)** exist to make this impossible |
| 12 | Did we claim free-text validation we cannot implement? | **NO — corrected in rev 2** (§9). The rev-1 claim is explicitly withdrawn |
| 13 | Did a second loss authority appear? | **NO** (§8a) |
| 14 | Did Step-04 probe/execution mechanics leak in? | **NO** (§10, §19) |
| 15 | Did we split internal milestones into unnecessary PRs? | **NO — corrected in rev 2.** ONE PR (§6) |
| 16 | Is every Stage-B rung atomic and source-supported? | One axis per rung (§11); §11.1 makes atomicity machine-checked; 3-B-neg added for negative evidence |
| 17 | Do TIDMAD parity claims use the strongest existing oracle? | §5 reuses Step-00/01/02; A1 is hard byte-identity; A2/A6 assert observables, not configuration |
| 18 | Any field present only because a legacy literal existed? | **Audited**: `task_type` routed out; `num_classes`'s `0` sentinel replaced by explicit "cardinality not meaningful" semantics (§4b) rather than preserved as a magic value |
| 19 | Does the parent freeze implementation choreography? | **NO** (§17) — no commit sequence, count, helper design, edit order, test module or command line is frozen |

---

## 21. Stop conditions

- a preset acquires runtime semantics, or any consumer branches on rank,
  modality or preset name;
- dataset cardinality or encoding is **redeclared** instead of derived /
  cross-validated;
- model-boundary dtype is required to **equal** dataset dtype, or a
  general dtype-conversion algebra is invented beyond current consumers;
- a second loss or output-type authority appears;
- **any loss accept/reject verdict changes** — that is a policy change,
  not an authority change;
- `hybrid` is exposed as a generic authoring value;
- **TIDMAD rendered prompt bytes change**, or any LLM-visible schema byte
  changes — STOP and return for an explicit operator decision; do not
  self-authorize a golden delta (§13);
- a machine-checkable contradiction can still reach an LLM-facing or
  executable consumer;
- any builtin forward output changes, or FocalLoss1D math is touched;
- prior on-disk generated plugins stop loading without a declared,
  accepted workspace boundary;
- a Stage-A baseline **cannot be captured without a production change** —
  that is a design finding, not a licence to edit;
- a Stage-B rung needs two axes to be meaningful (§11.1);
- multi-tensor containers are added without a live consumer;
- **a general cross-tensor relationship surface or relation DSL is
  introduced** (§4e) — alignment belongs to shared axis roles and shared
  symbolic dimensions. If a real production consumer needs an
  independent relationship semantic, STOP and report the finding;
- a declared field lands without a production consumer;
- Step-04 probe/execution or Step-11 loading/IPC mechanics are absorbed;
- inspection reveals ambiguity or a scope larger than this design
  assumes — STOP and ask, do not silently widen;
- the work is split into more than one PR.

---

## 22. Remaining operator decisions

**NONE.**

All six revision-1 questions were decided by the operator (Q1 one PR;
Q2 hybrid legacy-only; Q3 multi-tensor deferred; Q4 `task_type` not
owned; Q5 registry → Step 11; Q6 byte-identical prompts, no
pre-authorized exception) and are applied above. Revision 2's own source
audits (rows 11-12) produced corrections, not new questions. The Gate
disposition (§13) is decided from the current standard, with its one
conditional resolved mechanically at implementation time rather than by
an operator call.

---

## 23. Status

**STEP 03 DESIGN — READY FOR OPERATOR FREEZE (revision 2).**

Not frozen. No implementation authorized. No Implementation Working
Rules contract exists. No Gate has been run. Step 04 is not begun.
