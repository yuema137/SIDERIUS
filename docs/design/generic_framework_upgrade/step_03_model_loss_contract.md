# Step 03 — Model / Loss Contract — detailed design (parent)

## 0. Status and verified prerequisites

**STEP 03 DESIGN — FROZEN.**
**OPERATOR APPROVED FOR IMPLEMENTATION.**

| Freeze fact | Value |
|---|---|
| Frozen revision | **Revision 2** |
| Frozen semantic basis | `a490e99e` |
| Operator freeze date | **2026-08-13** |
| Implementation base | **this freeze commit**, stacked on `a490e99e` |
| Implementation branch | `feat/generic-framework-step-03-model-loss-contract` |

The freeze commit is **docs-only**: it changes status surfaces only and
leaves every revision-2 semantic section below byte-unchanged. At the
time of the freeze no production source, no test and no Gate has been
touched, and the implementation checklist / live ledger (§24) is not yet
written.

**Operator deviation, recorded at freeze:** implementation runs in the
PRIMARY checkout `/home/yuema137/SIDERIUS` on the branch named above —
**no separate implementation worktree**. This is an explicit
operator-approved departure from the Implementation Working Rules'
isolation default (the recommended branch was already checked out in the
primary working directory, so a second worktree on it is impossible).
It changes no semantic contract.

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
semantic authority; loss legality as a **derivation**; the
**model-boundary dtype ADMISSIBILITY requirement** and the
execution-side resolution of a concrete dtype satisfying it (§4a.1 A-1);
and cardinality derivation.

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

> **§4a is AMENDED by §4a.1 (operator-approved 2026-08-13).** The text
> above survives unchanged as the dataset-vs-model distinction, which
> A-1 does not touch. What A-1 corrects is the implicit assumption in
> the phrase *"the exact same model-boundary dtype"* — that one input
> tensor maps to one concrete dtype. Read §4a.1 before implementing any
> dtype behaviour.

### 4a.1 AMENDMENT A-1 — dtype REQUIREMENT vs concrete representation

**Status: OPERATOR-APPROVED, 2026-08-13.** Raised as finding F-1
(§24.2), evidenced by baseline A6 (§24.6), approved with corrections.
This is the only frozen-semantics amendment in Step 03.

```text
Previous frozen assumption
  One Model-I/O input tensor maps to ONE concrete torch dtype, and
  Phase B lifts that single concrete dtype out of the model-NAME branch.

A6 evidence (§24.6 — executed, at the model call, per builtin)
                   epoch training   streaming training   inference
  embedding arm    int32            int32                int64
  fcnet            float32          float32              float32

  Every embedding-arm builtin executes under BOTH int32 and int64 with
  the identical (1, 256, T) result. configs/task_config.yaml declares
  int64 — true of inference, false of both training paths.

Verdict
  The previous assumption is REFUTED. There is no single shipped
  concrete model-boundary dtype to lift.
```

**Corrected semantic contract.** The amendment freezes SEMANTICS, not an
implementation API.

| Authority | Owns |
|---|---|
| **Model-I/O contract** | the model input's **dtype REQUIREMENT / admissibility constraint** — which concrete representations the model boundary will accept |
| **Execution** | **selection of the concrete dtype** that actually reaches `model.forward`, subject to (a) what the Dataset path provides, (b) adaptations the framework actually supports, and (c) the model's dtype requirement |

```text
available concrete representations
      ∩
model-admissible representations
      ->  one valid concrete model-boundary dtype
      ->  empty intersection => TYPED FAIL-CLOSED
```

The Model-I/O contract does **NOT** own `training_dtype`,
`inference_dtype`, `boundary_dtype_map`, or any other boundary-specific
concrete dtype. **Adding one is a STOP** (§21).

**Site dtype is compatibility behaviour, not model semantics.** The
shipped concrete choices — int32 in the training engine, int64 in
inference — are observable compatibility behaviour. They may live as
implementation-local site preferences or equivalent; they must never
become contract fields, and a site preference must never be mistaken for
a model requirement.

**Resolution is not "legacy site dtype or fail."** That would elevate a
legacy site preference into a semantic constraint. The rule is:

```text
if the site's preferred concrete dtype is admissible      -> use it
                                       (TIDMAD: A6 stays green, exactly)
else if another concrete dtype is BOTH supported by the current
     adaptation path AND admissible to the model           -> use that
else                                                       -> typed failure
```

The exact deterministic selection mechanism is **implementation-time**
and must be derived from current source (§17 — no API is frozen here).

**Contract expressiveness > currently validated runtime support**
(operator refinement, 2026-08-13). The admissibility requirement is an
**extensible normalized dtype admissibility declaration**. It is
explicitly **NOT** bounded to today's concrete `{int32, int64, float32}`
set, and `INTEGER_INDEX` / `REAL_VALUED` are **NOT** frozen as the
public contract vocabulary — they were a source-grounded sketch in the
proposal, and are not promoted here.

Three distinct layers, which must not be collapsed:

| Layer | Owns |
|---|---|
| **Model-I/O contract** | an *extensible* normalized dtype admissibility requirement for the input tensor |
| **Runtime / execution capability** | the concrete dtypes the current data→model adaptation path can actually materialize and support |
| **Resolution** | `model-admissible ∩ runtime-supported → deterministic concrete dtype`; empty ⇒ typed fail-closed |

**What Step-03 execution evidence may claim.** Only the cases today's
production consumers actually require — **`int32`, `int64`, `float32`**.
No other concrete dtype may be claimed executable without evidence.

**What the schema must not preclude.** Representing a legitimate model
requirement over `float16`, `bfloat16`, `float64`, `bool`,
`complex64` / `complex128` or another backend-supported dtype must not
need a **schema redesign** later. Execution support for those stays
**capability-gated** and is added when a real consumer exists. Audit the
schema and resolver against this before any Phase-B production edit
(§24.9 Q13-Q14).

**Not widened into quantization / mixed-precision policy.** Those may
need dedicated execution semantics later. The contract must be
extensible enough not to block them, while claiming no support for them
now.

Deliberately **not** frozen: enum or vocabulary names, the field name
`dtype_requirement`, the helper name `resolve_model_input_dtype`, and the
schema nesting (§17). What IS frozen is the observable capability: **the
contract can express the input dtype admissibility today's consumers
require, and is extensible to requirements it does not yet support.**

**Dtype requirement is INDEPENDENT of output semantics.** It must not be
inferred from `output_type`, classifier/regressor/`hybrid`, model name,
rank, modality or preset label. A6's apparent correlation
(classifier ↔ integer input, `hybrid` ↔ `fcnet` float input) is a fact
about the **current builtin roster**, not a generic contract: a generic
classifier may eventually require real-valued input, and the Step-03
contract must not make that structurally impossible. **Stage-B keeps
dtype as an independent semantic axis.**

**Consequences.**

| Dimension | Consequence |
|---|---|
| Compatibility | the TIDMAD concrete matrix above remains **exact**; A6 passes **unmodified** |
| Genericity | no model-name branch; no boundary dimension in the model contract; site preference is not semantic authority |
| Validation | **3-B** proves a supported admissible case; **3-B-neg** proves an empty/unsupported intersection fails closed |
| Precedent | `LOSS_TARGET_DTYPE_REGISTRY` remains the *target*-side precedent to mirror — it is **not** merged into the input contract |

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
| model-boundary dtype **requirement** | inside a prose string | **MISSING as data** | **3 input-dtype name-branch sites** (F-2) | **DECLARE the requirement** (§4a.1 A-1); Phase B resolves a concrete dtype satisfying it. The concrete site dtype is NOT a contract field |
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
| A6 | **model-boundary dtype** | **AMENDED by A-1 (§4a.1).** The exact CONCRETE dtype of A6's matrix reaches each builtin at each boundary — embedding arm int32 / int32 / int64, `fcnet` float32 / float32 / float32 — observed **at the model call**, not at the branch condition, with `fcnet` asserted distinctly from the embedding arm and each boundary asserted separately. The pre-A-1 wording *"the exact same tensor dtype reaches each builtin"* presumed one concrete dtype; A6 refuted it | **CAPTURED** — §24.6 |
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
  model-boundary dtype RESOLVED against the declared admissibility
  requirement, not a model name (§4a.1 A-1) — kills the 3 input-dtype
  name branches; the 3 constructor name branches are audited and out of
  scope (F-2) · cardinality derivation (kills the 27 builtin literals) ·
  builtin catalogue / runtime consumption · the real training and
  inference boundary

OWNS / DOES NOT OWN: §3.
CURRENT PRODUCTION CONSUMERS:
  Phase A — workflows/task_config.render_forward_contract and the three
    proposer stages; the shape prose in agent/schemas/{proposal,
    implementor,validator}.py; models_format_sandbox's compatibility
    authority and its two callers.
  Phase B — the 3 INPUT-DTYPE sites train_engine_sandbox.py (:660,
    :1029) and inference_single.py (:216), plus ml_models/
    models_sandbox.py builtins. CORRECTED at kickoff (§24.2): the
    constructor branches (:614, :817, inference_single:410) are a
    different failure class and are NOT migrated (F-2); the class-weight
    histogram was ALREADY migrated by Step 02a (F-3).
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
| **3-B** model-boundary dtype | the dtype REQUIREMENT the model declares (§4a.1) | axes, cardinality, output semantics, **dataset dtype unchanged**, concrete site preferences unchanged | dtype still resolved from a model name; a valid adaptation misreported as a contradiction; or the requirement inferred from output semantics rather than declared independently | A → proven in B |
| **3-B-neg** unsupported adaptation | a requirement no supported concrete representation satisfies — the empty intersection of §4a.1 | everything else | silent coercion instead of a typed failure; or the site's preferred dtype being treated as the only candidate, so a supported admissible alternative is never reached | A |
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
| **(iii)** | execution | a **real training + inference round** feeds a **contract-SATISFYING** input dtype (§4a.1 — resolved against the declared requirement, not lifted from a contract field) and a contract-derived cardinality through the **actual subprocess/runtime path** |

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
| 5 | Did model dtype duplicate dataset dtype? | **NO** — §4a keeps them distinct; §4a.1 keeps the model's REQUIREMENT distinct from execution's concrete selection |
| 6 | Did we wrongly require model dtype == dataset dtype? | **NO — corrected in rev 2.** This was the live error; 3-B + 3-B-neg encode the fix |
| **6b** | Did we wrongly assume ONE concrete model-boundary dtype? | **YES, and it is corrected by AMENDMENT A-1 (§4a.1).** A6 refuted the assumption with executed evidence; the contract now owns dtype ADMISSIBILITY and execution owns the concrete representation. The 12-question dtype re-review is §24.9 |
| **6c** | Did a boundary-specific dtype reach the model contract? | **NO** — `training_dtype` / `inference_dtype` / `boundary_dtype_map` are forbidden fields (§4a.1, §21) |
| **6d** | Did a legacy site preference become a semantic constraint? | **NO** — §4a.1's resolution rule reaches a supported admissible alternative when the site preference is inadmissible; "site dtype or fail" is explicitly rejected |
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
- **(A-1)** a boundary-specific concrete dtype — `training_dtype`,
  `inference_dtype`, `boundary_dtype_map` or equivalent — is added to the
  Model-I/O contract (§4a.1);
- **(A-1)** the model's dtype requirement is inferred from `output_type`,
  model name, rank, modality or preset label instead of declared
  independently (§4a.1);
- **(A-1)** a legacy concrete SITE preference is treated as the model's
  semantic requirement — including a resolver that fails whenever the
  site's preferred dtype is inadmissible, without considering a supported
  admissible alternative (§4a.1);
- **(A-1)** a dtype requirement kind is frozen into the contract with no
  live consumer;
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

**STEP 03 DESIGN — FROZEN (revision 2; operator freeze 2026-08-13).**
**OPERATOR APPROVED FOR IMPLEMENTATION.**

Implementation has **not yet begun** at the time of this freeze commit:
no production source, no test and no Gate has been touched, and the
implementation checklist / live ledger is not yet written. Step 04 is
not begun.

Frozen semantic basis `a490e99e`; implementation base is this freeze
commit. The Implementation Working Rules contract for Step 03 exists as
of this freeze. §0 carries the freeze facts and the operator-approved
primary-checkout deviation.

*Historical:* before this commit both §0 and this section read
*"READY FOR OPERATOR FREEZE (revision 2) — not frozen, no
implementation authorized"*. All revision-1 and revision-2 discussion
above is preserved unchanged.

---

## 24. Implementation ledger (LIVE — added at implementation kickoff)

Everything from §24 down is the **live implementation ledger**. It never
edits §1-§23; where implementation contradicts them, the contradiction
is *recorded here* and, if material, stopped on (§21).

### 24.1 Implementation context

| Fact | Value |
|---|---|
| Frozen design SHA | `f865038f` (freeze commit; semantic basis `a490e99e`) |
| Implementation base | `f865038f` |
| Implementation branch | `feat/generic-framework-step-03-model-loss-contract` |
| Working location | **PRIMARY checkout** `/home/yuema137/SIDERIUS` — **no worktree** |
| PR shape | **ONE PR**; Phase A / Phase B are internal checkpoints (§6) |
| Handoff | `before_end_memory.md` (per `docs/development/claude_context_continuity.md`) |
| Current checkpoint | **kickoff** — Checkpoint 0 not yet started |

**Operator deviation (approved 2026-08-13).** The Implementation Working
Rules default to an isolated worktree outside `.claude/`. The recommended
branch was already checked out in the primary working directory, so a
second worktree on it is impossible. The operator directed implementation
into the primary checkout. No semantic consequence; recorded so a later
reviewer does not read the missing worktree as a skipped step.

**Base identity (mechanical).** `git diff --name-only 1826f9fd f865038f`
returns **only** the two Step-03 doc files. The source tree at the
implementation base is therefore **byte-identical** to the tree at which
§1 rows 1-10 were audited, and to `136214b9` where rows 11-12 were
re-verified. **Every §1 audit row holds at the base by construction** —
no row could have drifted.

### 24.2 Kickoff source re-audit — findings

Five findings. **F-1 is a STOP** (§21: *"inspection reveals ambiguity or
a scope larger than this design assumes"*). F-2 … F-5 are ordinary
implementation discoveries with recorded dispositions.

---

#### F-1 — the model-boundary input dtype is **not one value today**: training feeds int32, inference feeds int64 — **RESOLVED: Amendment A-1, §4a.1**

```text
Previous implementation assumption
  §1 row 3 / §4a / §7 treat "the input dtype at the model boundary" as
  ONE semantic, name-keyed at six sites, to be replaced by ONE
  contract-supplied value. Row 12's fix template is "make line 660 look
  like line 668".

Source evidence (re-read at f865038f, dtype observed AT the model call)
  execute_tools/train_engine_sandbox.py:660   epoch path
  execute_tools/train_engine_sandbox.py:1029  streaming path
      input_seq = input_seq.float() if model_cfg.model_type == "fcnet"
                                    else input_seq.int()      # int32
      ...
      output = model(input_seq)                               # :671 / :1036

  execute_tools/inference_single.py:213
      if args.denoising_model == "fcnet":
          input_seq = input_seq.float().to(DEVICE)
      else:
          input_seq = input_seq.long().to(DEVICE)             # int64
      ...
      output = model(input_seq)                               # :228

  configs/task_config.yaml:22
      input_shape: "[B, T] int64"        <- agrees with INFERENCE only

Corrected implementation understanding
  On the non-fcnet (embedding) arm the shipped model-boundary input
  dtype is **torch.int32 in training and torch.int64 in inference**.
  The fcnet arm is float32 at both. So there is no single shipped
  "model-boundary input dtype" to lift into the contract, and the
  declared contract prose already disagrees with the training boundary.

  This is invisible to every existing oracle: nn.Embedding accepts both
  int32 and int64, so forward OUTPUTS are numerically identical and
  Step-00's baselines (A4/A7) cannot see it. It is exactly the surface
  A6 was created to pin — and A6 does not exist yet (§5: "MISSING —
  capture first").

Why this is MATERIAL, not bounded
  The frozen contract carries ONE input tensor with ONE dtype (§4c).
  Routing both boundaries from it forces int32 == int64 at one of them:

    - unify on int64  -> the TRAINING boundary's observed dtype changes
    - unify on int32  -> the INFERENCE boundary's observed dtype changes
    - preserve both   -> the contract is NOT the sole authority at both
                         sites, or the dtype becomes boundary-scoped

  Every branch touches a frozen invariant: A6 ("the exact same tensor
  dtype reaches each builtin"), §21 ("any builtin forward output
  changes"), or §4c/§21 ("a declared field lands without a production
  consumer" / no widening). The design nowhere anticipates a
  per-boundary dtype, so no reading of §4a resolves it.

RESOLUTION (operator, 2026-08-13)
  Baseline A6 (§24.6) confirmed the matrix by execution. The operator
  approved AMENDMENT A-1 with two corrections; it is now frozen design
  §4a.1, and its provenance is §24.8. The options below are the
  proposal as originally offered, kept because the reasoning that
  narrowed them is the reason A-1 has the shape it does.

Options as offered (superseded by A-1)
  O1  Contract declares ONE model-required input dtype; the two
      boundaries keep their observed dtypes through an explicit,
      source-supported adaptation that is boundary-scoped. Preserves
      A6 exactly. Cost: "supported adaptation" gains a boundary
      dimension the frozen text does not describe.
  O2  Contract declares ONE dtype and BOTH boundaries are routed to it,
      accepting a deliberate change of observed dtype at one boundary.
      Cleanest contract; requires operator sign-off that the executed
      tensor change is intended, and A6 is captured as a CHANGED
      baseline with the delta attributed.
  O3  Migrate only the boundary that already matches the declared
      contract (inference, int64) in this PR; record the training
      int32 site as a named pre-existing divergence routed to a later
      step. Smallest change; leaves a name branch alive, weakening the
      §2 final effect.

Validation consequence (any option)
  A6 must be captured BEFORE any production change and must assert the
  training and inference boundaries SEPARATELY, per builtin, fcnet
  distinctly from non-fcnet — a single shared assertion would hide
  precisely this divergence.
```

---

#### F-2 — the "6 name branches" are two failure classes; only **3** are dtype

```text
Previous implementation assumption
  §7: Phase B "kills the 6 name branches" at
  train_engine_sandbox.py:614,660,817,1029 + inference_single.py:213,410.

Source evidence
  INPUT-DTYPE branches (3):
    train_engine_sandbox.py:660, :1029     input_seq.float()/.int()
    inference_single.py:213                 input_seq.float()/.long()

  CONSTRUCTOR branches (3):
    train_engine_sandbox.py:614, :817       model_class(cfg, loss_type=...)
    inference_single.py:410                 vs model_class(cfg)

Corrected implementation understanding
  The frozen SEMANTIC claim is untouched — §4a and row 12 describe the
  dtype class precisely, and line 660 is one of the three. Only the
  COUNT in §7 conflates dtype routing with a constructor-signature
  difference (fcnet's __init__ takes loss_type; the others do not).

Implementation consequence
  Contract-keyed dtype routing migrates the THREE dtype sites.
  The three constructor sites are **audited and deliberately NOT
  migrated**: no Model-I/O semantic backs "this model's constructor
  takes loss_type", so declaring one would be the consumer-less seam
  §21 forbids, and §8c forbids behaviour-changing existing builtin
  fcnet/hybrid. Recorded as a decision, not an oversight.

Validation consequence
  A mutation restoring a model-name branch at any of the three dtype
  sites must red. No rung asserts anything about the constructor sites.
```

---

#### F-3 — the class-weight histogram named as a Phase-B consumer **was already migrated by Step 02a**

```text
Previous implementation assumption
  §7 lists "the class-weight histogram (train_engine_sandbox.py:80,126,196)"
  as a Phase-B consumer; §19 routes "class-weight histogram fixed 256
  bins" to Step 03 as a cardinality derivation.

Source evidence (f865038f)
  execute_tools/train_engine_sandbox.py:142  np.bincount(alltarget + enc.value_offset,
                                                         minlength=enc.num_classes)
  execute_tools/train_engine_sandbox.py:219-221  same, streaming path
  grep -n "256" execute_tools/train_engine_sandbox.py  ->  NO MATCHES

Corrected implementation understanding
  The histogram already derives its bin count and offset from the
  resolved Dataset Profile's ValueEncoding. The cited lines 80/126/196
  now hold Step-02a profile-resolution code. `train_engine_sandbox.py`
  contains ZERO `256` literals.

Implementation consequence
  This Phase-B consumer does not exist. Nothing to migrate — the §4b
  authority model is already satisfied here by Step 02. Step-03
  cardinality work is confined to the 27 construction literals in
  ml_models/models_sandbox.py (§1 row 2, re-counted: 27 lines).

Validation consequence
  No 3-C rung may be attached to the histogram; it would pass without
  Step 03 existing. 3-C binds to the builtin construction path.
```

---

#### F-4 — `agent/prompts.py:1037` is a further **LLM-visible** `[B, 256, T]` site, owned by Step 07a

```text
Source evidence
  agent/prompts.py:1035-1041, inside get_planner_user_prompt(:905):
      "- This model is a **CLASSIFIER** (output [B, 256, T]). "
      "Valid loss types: **ce, focal, focal_cw**. "
      "Do NOT use smooth_l1 (regression only)."
  — keyed on `output_type`, and the surrounding block renders the loss
  legality the planner is told, raising rather than guessing (:1032).

Corrected implementation understanding
  This is a real LLM-visible restatement of BOTH contract-owned facts
  (cardinality 256) and loss legality, and §7's Phase-A consumer list
  does not name it. Ownership is NOT Step 03's: roadmap §15.1 assigns
  "planner/reflector prompts render from the profile" to Step 07a,
  whose A-cell is "planner/reflector prompts EXACT-equal".

Implementation consequence
  Step 03 does NOT migrate it (that would absorb Step-07a scope).
  Step 03 MUST hold its rendered bytes EXACT: §8a re-keys loss legality,
  and this prompt's loss_note is a downstream reader of that authority,
  so a re-key that changes these bytes is the §21 LLM-visible-drift STOP.

Validation consequence
  Checkpoint A gains a parity surface the frozen §5 A1 does not name:
  the rendered planner prompt. A1's `pb3_*` goldens cover the proposer
  stages only. Recorded here rather than editing §5.
```

---

#### F-5 — the `[B, 256, T]` prose surface is wider than §1 row 9's four sites

```text
Source evidence — additional sites, with owners
  agent/llm_bridge.py:181,192,202,2033,2139,2152   stub/pseudo-mode text
                                                    + docstrings
  agent/skills/training_skill/estimator.py:210,421  Step 07d (§19)
  agent/skills/evaluate_vram_skill/wrapper.py:90,196-197,205,236
  agent/skills/evaluate_vram_skill/batch_resolver.py:85
                                                    probe recipes -> Step 04 (§10)
  ml_models/models_sandbox.py:473,512               builtin comments
  agent/schemas/task_config.py:62                   ForwardContract field
                                                    description (an EXAMPLE)
  ml_models/models_format_sandbox.py (error strings inside
      validate_output_loss_compatibility)           "[B, 256, T]" / "[B, T]"

Corrected implementation understanding
  §1 row 9's four sites are the four LLM-visible CONTRACT-PROSE
  restatements; the wider grep surface is mostly comments, stub text and
  other steps' property. Two need explicit disposition:
    - the compatibility authority's own ERROR strings hardcode 256 and
      are reachable by an agent-facing validation failure;
    - task_config.py:62's description is an LLM-visible schema byte
      under §13's Gate-1 condition.

Implementation consequence
  Neither is migrated for tidiness. Both are held BYTE-EXACT unless the
  authority re-key (§8a) forces a change — which is a STOP, not a fix.

Roadmap divergence recorded
  Roadmap §15.1's Step-3 C-cell says "executor dtype routing + VRAM-probe
  recipes consume the contract in production". The FROZEN Step-03 design
  routes probe construction to Step 04 (§10) and defines Checkpoint C as
  §12's three boundaries, which contain no probe. Per the authority
  order the frozen design outranks the roadmap: **VRAM-probe recipes are
  NOT a Step-03 Checkpoint-C boundary.** §15.1 is reconciled at
  Checkpoint E, after merge — not now.
```

### 24.3 Checkpoint-0 baseline audit (existing oracles)

Per §15 Checkpoint 0, only A2/A3/A6/A8 are captured, and only where no
oracle exists. Audited at `f865038f`:

| Baseline | Existing oracle? | Disposition |
|---|---|---|
| **A2** loss cross-product | **PARTIAL.** `tests/unit/core/test_plugin_loss_compatibility.py:102` parametrizes `CLASSIFICATION_LOSSES` against a regressor plugin; `tests/unit/agent/test_output_contract_end_to_end.py:122-131` asserts one legal + one illegal pair per output type | **CAPTURE.** No test asserts the matrix cell by cell. Universe is exact and small: `output_type` ∈ {classifier, regressor, hybrid} × `loss_type` ∈ {focal, focal_cw, ce, smooth_l1, custom} (`models_format_sandbox.py:458`) = **15 cells**, incl. `custom` permitted everywhere and `hybrid` accepting all |
| **A3** loader tolerance tiers | **PARTIAL.** `tests/unit/ml_models/test_unknown_contract_consumer_reachability.py` covers the fail-closed lookup tier | **CAPTURE** the two tiers as *distinct* behaviours: load-time invalid/missing `PLUGIN_OUTPUT_TYPE` → warn + default `"classifier"` (`plugin_loader.py:81-88`) vs lookup-time `get_output_type` → `UnknownOutputContractError` (`:192-214`). Divergence is pre-existing and NOT unified (§5 A3) |
| **A6** model-boundary dtype | **NONE** | **CAPTURE** — and per F-1 it must assert training and inference **separately**, per builtin, fcnet distinctly. This baseline is what makes F-1 decidable |
| **A8** prior on-disk plugins | **NONE** | **CAPTURE** — `agent_generated/models/` holds **85** `.py` plugins at this checkout |

### 24.4 Implementation checklist (semantic milestones — commit count NOT pre-authorized, §17)

- [x] **M0 — Checkpoint 0 — PASS.** A2, A3, A6, A8 all captured before
      any production change; zero production diff; every new oracle
      mutation-proven. Evidence §24.6, dossier §24.7.
      Commits `9ddcc63a` (A6) and the A2/A3/A8 module commit.
- [x] **M1 — Phase A: normalized contract — LANDED (inert seam).**
      `agent/schemas/model_io_contract.py` — `ModelIOContract` (one input,
      one output), `TensorContract` (ordered axes + dtype), `TensorAxis`,
      `AxisRole` (`batch`/`temporal`/`class` — exactly the three roles a
      consumer reads today), `Dimension` (fixed | symbolic | dynamic,
      exactly one), `DtypeAdmissibility` (A-1). No multi-tensor
      container, no relation DSL.
      **Byte-exact rendering proven**: the normalized TIDMAD contract
      renders `"[B, T] int64"` and `"[B, 256, T] float32"`, equal to
      `configs/task_config.yaml` — so M4 can switch the renderer without
      a golden delta. Cardinality DERIVES from the class axis (256), and
      absence of a class axis yields `None`, not the legacy `0` sentinel.
      Tests: `tests/unit/agent/schemas/test_model_io_contract.py`,
      **33 passed / 0.11 s**.
      *Seam note*: the schema has no production consumer yet — M4 (render)
      and M5/M6 (execute) are its consumers, inside this same PR. A
      consumer-less seam at PR level would be the §21 stop; a
      seam-then-wire split across commits is the established boundary.
- [x] **M2 — Phase A: preset resolution + fail-closed — LANDED.**
      `agent/schemas/model_io_resolution.py` —
      `resolve_model_io_contract(contract, *, preset, dataset_num_classes)`
      plus the typed family `ModelIOResolutionError` →
      `UnknownPresetError` / `PresetContradictionError` (FX-4) /
      `DatasetContradictionError` (3-E). The preset **does not survive
      resolution**: the return type is the same `ModelIOContract` every
      consumer takes, so no runtime consumer *can* branch on a label.
      Rungs FX-3, FX-4 and 3-E all landed.
      Tests: `tests/unit/agent/schemas/test_model_io_resolution.py`,
      **17 passed / 0.21 s**. Four mutations, each isolating its class.
- [x] **M3 — Phase A: output semantics + loss re-key — LANDED.**
      `OutputSemantic` (`categorical` / `continuous`) in
      `ml_models/models_format_sandbox.py`, beside the frozensets it keys;
      `validate_semantic_loss_compatibility` is now THE rule and
      `validate_output_loss_compatibility` a thin legacy adapter over it —
      one implementation, two entry points. `ModelIOContract.output_semantic`
      DERIVES from the class-role axis; `.legacy_output_type` is the §8b
      one-way projection. `hybrid` adapts to `None` (§8c) and keeps
      accepting every loss.
      **Every verdict unchanged** — A2's 15 cells plus both pre-existing
      oracles: **40 passed**. Affected packages
      (`tests/unit/{ml_models,agent/schemas,core}`): **2979 passed / 2
      skipped**. M3's own module **24 passed**. Four mutations.
- [x] **M4 — Phase A: derived rendering, exact bytes — LANDED.**
      `ForwardContract` gains `model_io` (the normalized contract) and
      `preset`. When `model_io` is present it is THE authority:
      `input_shape`, `output_shape` and `num_classes` are DERIVED, and a
      contradicting authored prose value is a typed failure rather than a
      silent overwrite. When absent, Regime A is byte-for-byte unchanged.
      `renders_per_timestep_class_clause()` derives §1 row 7's clause from
      axis ROLES (class **and** temporal) instead of cardinality
      truthiness. `configs/task_config.yaml` migrated to author `model_io:`
      and dropped the duplicated prose — **rendered output proven
      byte-identical** against `HEAD:configs/task_config.yaml`.
      `load_task_config` now resolves at the production entry point, so
      M1 and M2 have live consumers.
- [x] **M5 — Phase B: requirement-resolved input dtype — LANDED.**
      `execute_tools/model_input_dtype.py` — `resolve_input_dtype` is the
      single entry point the three sites call; `RUNTIME_SUPPORTED_DTYPES`
      is the runtime-capability half of A-1's intersection.
      `ml_models/models_sandbox.BUILTIN_INPUT_DTYPES` declares only `fcnet`.
      Transport mirrors `--dataset_profile_json` exactly: `--model_io_json`
      on both engines, `_write_model_io_config` on the parent,
      `load_model_io_contract` fail-closed on the child.
      **A6 passes UNMODIFIED (30 passed)** against the migrated path, and
      `git diff` shows the A6 module untouched. Zero input-dtype name
      branches remain. Q7/Q8 proven. **51 passed** with A6.
      *(superseded planning text below kept for provenance)*
- [ ] ~~**M5 — Phase B: requirement-resolved input dtype (§4a.1 A-1).**~~
      The three dtype sites of F-2, following the `get_target_torch_dtype`
      precedent on the adjacent line (`train_engine_sandbox.py:668`).
      Resolution is `model-admissible ∩ runtime-supported`, honouring the
      legacy site preference when it lies in the intersection and
      reaching a supported admissible alternative when it does not;
      empty intersection fails closed. **UNBLOCKED** — A-1 approved.
      Run the §24.9 re-review against the code first.
- [x] **M6 — Phase B: cardinality derivation — LANDED.**
      `BaseConfig.num_classes` (derived, cross-validated, 256 as the
      declared Regime-A value); all builtin construction literals migrated
      to `config.num_classes`; `apply_contract_cardinality` injects the
      contract's count in both engines and fails closed on a contradicting
      config. Rung **3-C**: every builtin builds and emits at 10 and 64
      classes; TIDMAD's 256 unchanged; Regime A unchanged. **31 passed.**
      *(superseded planning text below kept for provenance)*
- [ ] ~~**M6 — Phase B: cardinality derivation.**~~ The 27 construction
      literals in `ml_models/models_sandbox.py`, derived from /
      cross-validated against `ValueEncoding.num_classes`
      (`execute_tools/dataset_config.py:406`), whose own docstring
      (`:389-392`) assigns this derivation to the model-contract module.
      NOT the class-weight histogram (F-3). → Phase-B invariant:
      **no rendered prompt bytes change**

**PHASE A COMPLETE** (M1-M4). Phase-A invariant held throughout: no
executed model tensor behaviour changed — `train_engine_sandbox.py` and
`inference_single.py` are byte-untouched since the freeze. §24.9
re-reviewed against the code at `4819b44a`: no material NO.

- [x] **CHECKPOINT A — PASS.** `tests/unit/{agent,workflows,ml_models,execute_tools,core,guardrails}`
      at the clean committed head `0634bb56`: **7616 passed / 3 skipped /
      0 failed**, pytest rc 0, 416 s. Covers A1 (all `pb3_*` goldens
      UNMODIFIED) through A8, plus the F-4 planner prompt. A6 passes
      **unmodified** against the fully migrated execution path.
- [x] **CHECKPOINT B — PASS.** All eight rungs, **229 passed** across
      their owning modules. 3-A and 3-D landed in
      `tests/unit/agent/schemas/test_step03_checkpoint_b_ladder.py`, which
      also machine-checks §11.1 atomicity via a semantic-facet diff (the
      `_diff_paths` precedent) and asserts the ladder is complete with no
      multi-tensor or relation rung.
- [x] **CHECKPOINT C — PASS.** (i)+(ii) `tests/unit/workflows/
      test_step03_checkpoint_c_live_boundary.py` **9 passed**;
      (iii) `tests/integration/execute_tools/
      test_step03_checkpoint_c_subprocess.py` **7 passed** (real
      `subprocess.run`, real HDF5). Found and closed a production gap: the
      3-E cross-check now also runs at the subprocess boundary.
- [ ] **CHECKPOINT D** — targeted regression + static + mutation (§14)
- [ ] **GATE 2** — required (§13); gate standard re-read immediately
      before launch. **Gate 1 NOT required** unless an LLM-visible byte
      changes, which is itself a STOP
- [ ] **CLOSEOUT** — ledger synchronized, PR opened, exact-final-head CI
      green, `local HEAD == PR headRefOid == CI headSha`, tree clean

### 24.5 Gate disposition, resolved mechanically at kickoff

`docs/gates/gate_testing_standard.md` re-read at `f865038f` (283 lines);
§13's citations verified verbatim: the assignment table at :254-263, the
*"changed LLM-facing system prompt or schema"* Gate-1 trigger at :29-30,
and Gate 2 at *"Checkpoint commits (end of a feature's commit plan)"*.
**§13 stands as written.** Gate 1 stays out of scope iff every
LLM-visible byte is exact — now including the F-4 planner prompt and the
F-5 schema-description sites.

### 24.6 Validation ledger

#### A6 — model-boundary input dtype — **CAPTURED**

```text
command      .venv/bin/python -m pytest \
               tests/unit/execute_tools/test_step03_a6_model_boundary_dtype.py \
               -q --no-header -p no:randomly
purpose      Checkpoint-0 baseline A6, and the evidence the F-1 decision
             is made against
environment  CPU only; no GPU, no LLM, no real dataset
runtime      5.69 s
result       30 passed / 0 failed  (pytest rc 0, read from the log)
production   ZERO diff — the module is new and adds no production edit
```

**Method.** The dtype is observed **at the model call**, not at the cast,
by registering a subclass of the real builtin whose `forward` records
`x.dtype` and delegates unchanged, then driving the **real production
functions**: `run_experiment` (epoch), `run_experiment_streaming`
(THE production training path) and `inference_single.process_batch`.
The synthetic loader serves **int16**, which is what the real loaders
serve (Step-02a C1 pinned that), so the engine's cast operates on its
production input.

#### The A6 matrix — concrete dtype reaching `model.forward`

| builtin | `output_type` | epoch training `run_experiment` | streaming training `run_experiment_streaming` | inference `process_batch` |
|---|---|---|---|---|
| `punet` | classifier | **int32** | **int32** | **int64** |
| `transformer` | classifier | **int32** | **int32** | **int64** |
| `wavenet` | classifier | **int32** | **int32** | **int64** |
| `rnn` | classifier | **int32** | **int32** | **int64** |
| `gated_fno` | classifier | **int32** | **int32** | **int64** |
| `fcnet` | hybrid | float32 | float32 | float32 |

Cast sites: `train_engine_sandbox.py:660` (call `:671`), `:1029`
(call `:1036`), `inference_single.py:216` (call `:228`).

**F-1 CONFIRMED, exactly as the source read predicted.** The embedding
arm diverges — int32 in both training paths, int64 in inference. The
non-embedding arm (`fcnet`) does **not** diverge, so the divergence is a
property of the embedding arm, not of the boundaries in general.

**Cross-boundary acceptance, executed not assumed.** Every embedding-arm
builtin runs under **both** int32 and int64 and returns the identical
`(1, 256, T)` shape. That is why the divergence has survived unnoticed:
nothing fails today, and no existing oracle can see it — `nn.Embedding`
accepts both, so Step-00's forward baselines (A4/A7) are numerically
identical either way.

**The declared contract matches inference only.**
`configs/task_config.yaml:22` declares `"[B, T] int64"`; that is true of
`process_batch` and false of both training paths. Pinned in the suite,
not left as prose.

#### M1 — normalized contract schema

```text
module       agent/schemas/model_io_contract.py (new)
tests        tests/unit/agent/schemas/test_model_io_contract.py
result       33 passed / 0.11 s, pytest rc 0
lint         ruff check + ruff format --check clean
types        pyright CANNOT RUN LOCALLY — the vendored pyright needs a
             newer Node than this host provides (`internal/modules/cjs`
             loader error). CI is the only environment that runs strict
             pyright, and it is authoritative for this module. Recorded
             rather than claimed, per CLAUDE.md.
```

Design decisions taken at M1, from source:

- **`AxisRole` has exactly three members** — `batch`, `temporal`, `class`
  — because exactly three are read by a production consumer today
  (rendered shape, the renderer's per-timestep phrasing at
  `workflows/task_config.py:209`, and cardinality). `role` is **optional**:
  an axis nothing branches on carries none. That is what keeps arbitrary
  rank expressible without inventing consumer-less roles (§21).
- **`DtypeAdmissibility.admissible` is an ordered tuple of dtype names**,
  not an enum — A-1 correction 2. `admissible[0]` is the canonical
  representation: it renders into prose and is the deterministic default.
  That single ordering removes the need for a second "display dtype"
  field, which would have been duplicate authority.
- **Cardinality is derived from the class axis**, never declared, so no
  second configurable class count exists (§4b). No class axis ⇒ `None`.
- **Alignment rides on shared symbolic names** (§4e). `T` on both sides
  IS the alignment; the cross-validator only rejects a shared symbol whose
  two axes claim different roles, because anything stronger would need the
  relationship DSL §4e defers.

#### M2 — preset resolution + fail-closed consistency

```text
module   agent/schemas/model_io_resolution.py (new)
tests    tests/unit/agent/schemas/test_model_io_resolution.py
result   17 passed / 0.21 s, pytest rc 0
lint     ruff check + ruff format --check clean
types    pyright still cannot run locally (Node v10.19.0); CI authoritative
```

**Binding inheritance re-read before implementing.** FX-3/FX-4 are
roadmap deferred decision **D13**, whose rule is frozen in Step-01
§6A.5: a preset/contract inconsistency must fail with a typed error
*"before any LLM request is constructed"*, and silently rewriting the
shape, dropping the preset, defaulting to TIDMAD or letting the
contradiction reach the Proposer are all forbidden. §6A.5 also requires
the resolved output to be *"a single normalized rank-agnostic contract,
not a preset label plus loose fields"*.

```text
Previous implementation assumption
  A preset SUPPLIES structure — the authoring shorthand expands into
  axes, and resolution merges preset + explicit fields.

Source evidence
  Step-01 §6A.5's own failure examples are "`time_series` with no
  temporal axis; `spatial_grid` with no spatial axis" — both are the
  explicit contract failing to SATISFY the preset, not the preset
  filling anything in. Nothing in source defines an axis order for a
  modality, and §4d assigns rank-independence to axis ROLES.

Corrected implementation understanding
  A preset is a REQUIREMENT: a named set of axis roles the contract must
  declare. Requirement-only is the narrowest form that satisfies both
  binding rungs.

Implementation consequence
  A supplying preset was considered and REJECTED: it would have to invent
  an axis ORDER no source supports, baking a modality's conventional
  layout into the framework — the opposite of what roles are for. The
  shipped registry holds exactly one preset, `sequence`, deliberately NOT
  named for a modality, requiring `batch` + `temporal` on both tensors.
  A `spatial_grid` preset is NOT shipped: it would need a `spatial` axis
  role no production consumer reads — the consumer-less field §21 forbids.

Validation consequence
  FX-3 becomes provable as an IDENTITY: resolving with the preset returns
  a contract equal to resolving without it, so "a preset producing a
  second runtime path" is structurally impossible rather than merely
  unobserved. §16's *"no preset label is read at runtime after
  resolution — greppable"* is asserted mechanically by a repo scan that
  allows exactly one reader, the resolver itself.
```

**Description↔contract consistency — discharged, not dropped.** Step-01
§6A.5 and its R2-6 review named *"description↔contract consistency"* as
part of the contract owner's FX-4 obligation. Step-03's frozen §9
explicitly **withdrew** that: the shipped `task_description` duplicates
a contract-owned fact, so the correct fix is *authority* (Step-01's
surface to own), not an NLP validator Step 03 refuses to build. No new
contradiction — §9 already records the narrowing, and M2 implements the
machine-checkable channels only.

#### M3 — canonical output semantics + loss-authority re-key

```text
modules  ml_models/models_format_sandbox.py   (OutputSemantic, projection,
                                               re-keyed rule)
         agent/schemas/model_io_contract.py   (derived properties)
tests    tests/unit/ml_models/test_step03_m3_output_semantic_authority.py
result   24 passed (module) / 40 passed (verdict oracles) /
         2979 passed + 2 skipped (affected packages), pytest rc 0
lint     ruff check + ruff format --check clean
```

**Placement decided by layering, not preference.** `OutputSemantic` is a
tensor semantic and conceptually belongs with the contract, but
`agent/` imports `ml_models/` and **not** the reverse, so defining it in
`agent/schemas/` would invert the dependency the moment the loss
authority consumed it. It therefore lives in `models_format_sandbox.py`
beside the frozensets it keys — which is also what §8a asks for: RE-KEY
the existing authority, do not create a second one.
`models_format_sandbox.py` is torch-free (only `typing` + `pydantic`),
so the schema layer takes on no heavy import.

**The re-key, concretely.** `validate_semantic_loss_compatibility(semantic,
loss_type, *, model_type)` is the rule, keyed on `OutputSemantic`.
`validate_output_loss_compatibility(output_type, ...)` keeps its exact
signature and projects the legacy string onto the semantic, then
delegates. `output_semantic_from_legacy` returns `None` for BOTH
`"hybrid"` and any unrecognised string — deliberately collapsing two
cases, because that is what preserves the shipped verdicts:

- `hybrid` is a legacy builtin adapter (§8c), not a tensor semantic, and
  its shipped behaviour is that every loss is legal;
- an unrecognised value matches neither guard today, so it raises
  nothing. Tightening that would change an accept/reject verdict — a §21
  STOP — and A2's tolerance test is the tripwire that would demand the
  operator call.

Error-message bytes are unchanged, including their hardcoded `[B, 256, T]`
(F-5): the re-key must not touch them, and A2 pins their content.

#### M4 — derived rendering + the live resolution boundary

```text
modules  agent/schemas/task_config.py   (`model_io`, `preset`, derivation)
         workflows/task_config.py       (role-derived clause; resolution
                                         wired at the loader; resolved dump)
         configs/task_config.yaml       (migrated to author `model_io`)
tests    tests/unit/workflows/test_step03_m4_derived_rendering.py
lint     ruff check + ruff format --check clean
```

**Byte-identity, proven mechanically.** The migrated YAML was rendered and
compared against the pre-migration file read out of `HEAD` in the same
process: **identical**. The LLM-visible golden
`cfg2_forward_contract_block.txt` passes **UNMODIFIED**, which is the §21
invariant. Regime A re-ran at the same count as its pre-M4 baseline
(829 passed).

```text
FINDING — a production defect M4 introduced, caught by two Step-00 baselines

Previous implementation assumption
  Migrating `configs/task_config.yaml` to author `model_io` is
  self-contained: the prose is derived onto the validated
  `ForwardContract`, so consumers see the same values.

Source evidence
  `load_task_config` returned `dict(raw)` — the RAW YAML mapping. Once the
  YAML stopped authoring `input_shape` / `output_shape` / `num_classes`,
  `cfg["forward_contract"]["num_classes"]` simply VANISHED, because the
  derivation lives on the validated object and was thrown away. Two
  baselines caught it:
    tests/unit/workflows/test_task_config.py
      ::TestCommittedConfigLoads::test_repo_task_config_loads
    tests/unit/workflows/test_step00_task_config_baselines.py
      ::TestCFG1ResolvedTaskConfig::test_resolved_shipped_config_deep_equal

Corrected implementation understanding
  The loader must return the RESOLVED contract. It validated a contract
  with derived fields and then handed back something less resolved than
  what it had just validated — a real defect, not a baseline needing
  relaxation.

Implementation consequence
  `config["forward_contract"] = contract.model_dump(mode="json")`.
  `mode="json"` is load-bearing: a plain dump leaks tuples and `StrEnum`s
  into a mapping callers serialize, and the JSON golden compared
  `tuple != list` on the first attempt.

Validation consequence
  A regression test now pins that the derived fields survive the loader
  (`test_the_loader_returns_the_resolved_contract_not_the_raw_block`).
  One of M4's OWN tests was also wrong — it asserted the derived keys were
  absent from the LOADED config, when the claim it meant to make is about
  what the YAML AUTHORS. It now reads the YAML file directly.
```

**Declared baseline delta — CFG-1, non-LLM-visible.** After the fix, the
Step-00 CFG-1 golden still differed, and the difference was measured
rather than assumed:

```text
ADDED   : model_io, preset
REMOVED : (none)
CHANGED : (none — every pre-existing key holds a byte-identical value)
task_description : identical
```

`input_shape`, `output_shape` and `num_classes` are unchanged in value and
are now DERIVED rather than authored. This is the authoring-surface change
Step 03 exists to make, it is **not** an LLM-visible surface, and the
rendered-block golden passes unmodified. The golden was re-captured by
hand per the Step-00 policy the helper states — *"capture in an explicit
test-only commit; tests never write goldens"* — with the attribution above
recorded in its `_captured_at` note. Following the Step-01 OD-S1-8
precedent: a declared golden delta, mechanically attributable, never a
silent regeneration.

#### M5 — contract-keyed model-boundary input dtype (Phase B)

```text
modules  execute_tools/model_input_dtype.py     NEW — the resolver
         ml_models/models_sandbox.py            BUILTIN_INPUT_DTYPES
         ml_models/models_format_sandbox.py     DtypeAdmissibility moved here
         execute_tools/train_engine_sandbox.py  2 dtype sites + --model_io_json
         execute_tools/inference_single.py      1 dtype site + --model_io_json
         core/sandbox_executor.py               _write_model_io_config + 2 spawns
tests    tests/unit/execute_tools/test_step03_m5_input_dtype_resolution.py
result   51 passed with A6, pytest rc 0; ruff clean
```

**A6 passes UNMODIFIED.** `git diff` over
`test_step03_a6_model_boundary_dtype.py` is empty and the module is green
against the migrated path — the concrete matrix (embedding arm int32 /
int32 / int64, `fcnet` float32 ×3) is byte-exact while the model-name
branches are gone from the data path.

**Zero input-dtype name branches remain.** The only surviving
`== "fcnet"` occurrences are the three CONSTRUCTOR branches of F-2 —
audited and deliberately not migrated — plus two comments naming what was
replaced. A test asserts the count did not grow and that no dtype cast
sits on one.

```text
Previous implementation assumption
  The task's Model-I/O contract alone determines the model-boundary dtype.

Source evidence
  A6 shows `fcnet` is fed float32 while every other builtin is fed an
  integer, under the SAME task. One task-level contract cannot express
  both, and the shipped contract declares ("int64", "int32") — which
  `fcnet` does not accept in production.

Corrected implementation understanding
  Admissibility is resolved with a documented PRECEDENCE, mirroring
  `plugin_loader.get_output_type`'s builtin-then-registry lookup:
    1. the model's OWN declaration (`BUILTIN_INPUT_DTYPES`), when it has
       one — a model whose requirement genuinely differs;
    2. otherwise the TASK contract, which is the declaration rendered to
       the LLM and therefore what any model built for this task must meet.
  Not two authorities: one lookup, and the task contract answers for every
  model that does not override.

Implementation consequence
  Only `fcnet` declares, and its absence elsewhere is the design: a
  registry listing every builtin would become a second place to look up
  every model's dtype. `fcnet` declares `("float32",)` ALONE even though
  A6 shows it would also RUN under int32/int64 — a permissive declaration
  would let the training site's int32 preference win and silently change
  the tensor `fcnet` is fed.

Validation consequence
  `fcnet` becomes the LIVE production case for §24.9 Q7: its site
  preference is inadmissible at every boundary, so every real training and
  inference run exercises the supported-alternative path. Q7 is not a
  synthetic rung.
```

**§24.9 Q7 and Q8, now answerable against code.**

| # | Question | Answer, with evidence |
|---|---|---|
| **Q7** | can a supported non-default concrete dtype be selected when the legacy site preference is inadmissible? | **YES** — and `fcnet` takes that path in production. The selected alternative is the contract's canonical `admissible[0]` filtered to runtime support, so it is deterministic |
| **Q8** | does an empty model-admissible ∩ runtime-supported intersection fail closed? | **YES** — `UnsupportedModelInputDtypeError`, naming the declared set and the supported set. A `bfloat16`-only requirement is expressible and refused; a partially-supported requirement still resolves |

**Transport.** `--model_io_json` mirrors `--dataset_profile_json` in
shape and in its two-case rule: *supplied but broken* fails closed with a
diagnostic naming the path; *absent* is the Regime-A adapter. Scoring is
deliberately NOT given the contract — it feeds no model, so a dtype
requirement would have no consumer there.

**Layering.** `DtypeAdmissibility` moved from `agent/schemas/` to
`ml_models/models_format_sandbox.py` (re-exported), for the same reason as
`OutputSemantic` at M3: `ml_models` must not import `agent`, and the
builtin catalogue has to declare admissibility. The resolver itself lives
in `execute_tools/` because it needs both `torch` and the contract.

*Test defect found and fixed during M5*: the no-name-branch assertion
scanned raw source and matched the resolver's own DOCSTRING, which quotes
the branch it replaced. It now parses the function with `ast`, drops the
docstring and asserts over executable code — a test reading prose as if
it were code is a test that will lie in the other direction later.

#### M6 — cardinality derivation (Phase B), rung 3-C

```text
modules  ml_models/models_format_sandbox.py     BaseConfig.num_classes
         ml_models/models_sandbox.py            11 construction sites migrated
         execute_tools/model_input_dtype.py     apply_contract_cardinality
         execute_tools/train_engine_sandbox.py  injection at config build
         execute_tools/inference_single.py      injection at config build
tests    tests/unit/ml_models/test_step03_m6_cardinality_derivation.py
result   31 passed; A6 + Step-00 numeric baselines + ml_models: 285 passed
```

```text
Previous implementation assumption
  §7 and §24.4 both say "the 27 builtin literals" in
  ml_models/models_sandbox.py.

Source evidence
  27 is a LINE count — `grep -c 256 ml_models/models_sandbox.py`. Reading
  them, only ELEVEN are construction sites (`:227` `adc_channel = 256`,
  `:356`, `:380`, `:403`, `:479`, `:494`, `:526`, `:548`, `:557`, `:632`,
  `:678`); the other sixteen are comments and docstrings describing the
  shape, e.g. "Output: [B, 256, T] — class logits per time step".

Corrected implementation understanding
  Eleven construction sites had to change. The comment/docstring mentions
  are prose about the TIDMAD instance and are NOT migrated — rewriting
  them would be the cosmetic literal-hunt §"IMPLEMENTATION PRINCIPLE"
  warns against ("do NOT judge success by disappearance of literals").

Implementation consequence
  Same shape as F-2's site-count correction: the frozen SEMANTIC claim is
  untouched, only a count in the prose was loose. 3-C's source-level guard
  therefore scans for a class-count literal in a CONSTRUCTION expression
  (`nn.Embedding` / `nn.Linear` / `nn.Conv1d` / `adc_channel =`) with
  comments stripped, rather than for the substring `256`.

Validation consequence
  The rung asserts the count reaching a CONSTRUCTED MODEL — emitted logit
  count and embedding-table size — not a config field. A test asserting
  `cfg.num_classes == 10` would pass with every builtin still hardcoding
  256, which is exactly §11.1's "must red when its consumer re-hardcodes
  the literal".
```

**Two builtins needed threading, not just a substitution.** `RNNSeq2Seq`
builds `Seq2SeqEncoder` / `Seq2SeqDecoder` from loose parameters rather
than the config, so the count is threaded through their signatures with
a `num_classes=256` default — a direct constructor call (Regime A) is
byte-unchanged.

**One authority, enforced.** `apply_contract_cardinality` derives the
count from the contract's class axis — itself cross-validated against
`ValueEncoding.num_classes` at load time (rung 3-E) — and raises
`ContractCardinalityConflictError` when a config declares a contradicting
value. Neither side is silently adopted: the config winning would make it
a second authority, and silently overwriting it would let an author
believe a value that never took effect. Where the output carries no class
axis, nothing is injected — §4b's deliberate asymmetry.

The `256` default on `BaseConfig.num_classes` is the declared Regime-A
value, in the same sense as an absent `--dataset_profile_json` resolving
the shipped profile. A resolved path never reaches it, and 3-C proves the
resolved path is genuinely derived.

#### CHECKPOINT A — first run, ONE failure, diagnosed

```text
command  pytest tests/unit/{agent,workflows,ml_models,execute_tools,core,guardrails}
result   1 failed, 7615 passed, 3 skipped in 414.56 s — pytest rc 1
```

**The harness reported "exit code 0" for this run while pytest's own
status was 1.** That is the wrapper's status, not pytest's — the second
time this session. The verdict came from the log, as CLAUDE.md requires.

Failure:
`tests/unit/agent/evaluate_vram_skill/test_isolated_preflight.py
::TestThirdValidationOutcomesUnchanged::test_candidate_configs_and_hashes_are_unchanged`

```text
Diagnosis
  M6's BaseConfig.num_classes grows every NORMALIZED model config by one
  key, so the pinned sha256 of each VRAM-preflight candidate moves.
  Classification: attributable schema delta, NOT a behaviour change and
  NOT an LLM-visible surface.

Evidence — measured, not assumed
  Removing ONLY `num_classes` from each normalized config reproduces the
  three ORIGINAL digests exactly:
      fcnet@323M-official   ad0e07aa864a6492  (recovered)
      wavenet@17M           958440417b837b89  (recovered)
      transformer@medium    80581a7d24d2f100  (recovered)
  Zero keys removed, zero pre-existing values changed.

Disposition
  The pin is UPDATED, and STRENGTHENED rather than hash-swapped. It now
  asserts BOTH halves: the current digests, and that stripping the new key
  still reproduces the pre-M6 digests. A bare hash swap would assert
  nothing about WHAT changed; this version reds specifically when a
  pre-existing value moves, which is the failure the pin exists for.
```

#### CHECKPOINT A — **PASS**

```text
head     0634bb56 (clean tree)
command  pytest tests/unit/{agent,workflows,ml_models,execute_tools,core,guardrails}
result   7616 passed / 3 skipped / 0 failed — pytest rc 0, 416.01 s
```

| Row | Surface | Evidence |
|---|---|---|
| A1 | rendered prompts + contract block | every `pb3_*` golden passes **UNMODIFIED**; `cfg2_forward_contract_block.txt` untouched |
| A2 | loss verdicts | the 15-cell matrix, unchanged through the M3 re-key |
| A3 | plugin tolerance tiers | both tiers and their divergence |
| A4 | builtin forwards | Step-00 numeric baselines |
| A5 | registry contents | Step-00 |
| A6 | model-boundary dtype | passes **unmodified** against the fully migrated path; `git diff` over the module is empty |
| A7 | Step-00 numerics | unchanged |
| A8 | prior on-disk plugins | 85 load and register |
| F-4 | planner prompt (`agent/prompts.py:1037`) | bytes exact — Step-07a's surface, held not migrated |

#### CHECKPOINT B — **PASS**

```text
command  pytest over the eight rungs' owning modules
result   229 passed — pytest rc 0
```

| Rung | Owner | Varies |
|---|---|---|
| **3-A** | `test_step03_checkpoint_b_ladder.py` | rank / ordered axes, roles preserved |
| **3-B** | `test_step03_m5_input_dtype_resolution.py` | declared dtype requirement |
| **3-B-neg** | same | a requirement no supported dtype satisfies |
| **3-C** | `test_step03_m6_cardinality_derivation.py` | class count |
| **3-D** | `test_step03_checkpoint_b_ladder.py` | canonical output semantic |
| **FX-3** | `test_model_io_resolution.py` | preset resolution |
| **FX-4** | same | preset-vs-contract mismatch |
| **3-E** | same | contract cardinality vs `ValueEncoding.num_classes` |

**§11.1 atomicity is machine-checked, not asserted.** A semantic-facet
diff (`_varied_facets`) reports exactly which of eight independent facets
a contrast moves. Deliberately not a `model_dump()` diff: a raw dump
conflates facets — moving the class axis changes `axes` AND
`class_cardinality` AND `output_semantic` at once — so it could never show
that a rung varies one THING.

```text
RECONCILIATION with §11's phrasing of 3-D — recorded, not glossed

Frozen text
  §11 lists 3-D as varying "classifier <-> regressor" while holding
  "axes, dtype, cardinality" fixed.

Source evidence
  §8b made the output semantic DERIVED from the output tensor, so a
  contract cannot change its semantic without changing whether it carries
  a class axis; cardinality then becomes `None` (not applicable) rather
  than a different number.

Corrected understanding
  §11's phrasing presumed output semantics were a separate DECLARATION.
  Under the derived design the rung still varies ONE semantic axis — does
  the output carry a class alphabet — and the class axis is that
  semantic's REPRESENTATION, with cardinality following it to `None` by
  §4b's deliberate asymmetry.

Why this is NOT the §11.1 STOP
  §11.1 stops on "a rung that needs TWO axes to be meaningful". 3-D needs
  one. The facet diff proves it: the entire INPUT side is untouched, and
  every facet that moves is the class axis or something derived from it.
  The test states that assertion explicitly rather than leaving the
  reader to infer it.
```

3-D also pins the §4a.1 independence claim from the other side: flipping
the output semantic must NOT move the input dtype admissibility. The
correlation A6 shows in the current builtin roster (classifier ↔ integer
input) is a fact about that roster, not a framework law.

#### Evidence-economy correction (operator, 2026-08-13) — binding for the rest of Step 03

The Checkpoint-A run above was **broader than intended**. The checkpoint
model is:

```text
Checkpoint A  = EXTRACTION PARITY
Checkpoint B  = ATOMIC GENERIC CONTRAST
Checkpoint C  = LIVE PRODUCTION INTEGRATION
Checkpoint D  = TARGETED REGRESSION / MUTATION / STATIC
exact-head CI = BROAD REGRESSION
```

Checkpoint A is **not** a general regression suite. Before every further
test launch, state (1) which checkpoint property it proves, (2) the
failure class it uniquely catches, (3) why a narrower set is
insufficient. No concrete answer to (2) or (3) ⇒ narrow the command.

**The lesson from the one real finding that broad run produced:** *the
candidate-config serialization surface needed an explicit parity oracle
in Checkpoint A.* It now has one, and it is used directly rather than
rediscovered by sweeping.

#### Test-disposition audit — `test_candidate_configs_and_hashes_are_unchanged`

```text
Original test intent
  Freeze the normalized VRAM-preflight candidate configs by sha256 so a
  silent edit to CANDIDATES or a model schema is caught.

Production behavior it protects
  The validation set spans the range the V19 campaign could not explore —
  a 323M FCNet, a 10-20M convolutional candidate, a medium Transformer. A
  candidate quietly shrinking would make the tool pass where it used to
  fail, which the script's own docstring names as the defect.

Unique failure class
  A changed scale parameter, a dropped candidate, an altered model_type.

Is the DIGEST itself operationally meaningful?  Traced to source.
  `config_identity` (scripts/vram_preflight_validation.py:141) is NOT dead
  — it is emitted into every result record at :194. But it is a REPORT
  LABEL: nothing outside a single run compares its value. No cache key, no
  resume key, no cross-run compatibility boundary reads it. Pinning the hex
  froze an incidental JSON serialization, which is why Step 03 adding the
  DERIVED `num_classes` field failed the pin while nothing it protected
  had changed.

Higher-level replacement
  None needed — the same failure class is expressible directly.

Disposition: REWRITE
  `test_candidate_configs_are_the_intended_ones` asserts the semantic
  values explicitly, plus that the only key beyond them is the derived
  `num_classes`. `test_config_identity_distinguishes_the_candidates`
  keeps the digest's genuine property — deterministic and collision-free
  across the set, which is what makes a result record attributable —
  without freezing its value.

Why evidence is NOT weakened
  Every failure the hash could catch reds here too, and NAMES ITSELF. A
  hash failure says only "something moved"; these say which field and to
  what. The rewrite is strictly more informative, and it is justified
  independently of whether the current implementation passes: the pin was
  freezing a serialization, not a semantic.
```

*Supersedes the interim reconciliation recorded above* (which strengthened
the pin to assert the pre-M6 digest was recoverable). That was the right
move while the digest's status was unknown; tracing its consumers showed
the pin should not exist at all.

#### CHECKPOINT C — boundaries (i) and (ii)

```text
module   tests/unit/workflows/test_step03_checkpoint_c_live_boundary.py
result   9 passed — pytest rc 0
scope    entered ONLY through production entry points; no resolver is
         called directly (§12's binding qualification)
```

**C(i)** — the contract reaches the real LLM-facing renderer. Proven by
VARYING the declaration and observing the bytes follow: a renderer still
emitting a literal produces identical output for both. The variation is
carried all the way into `_render_commit_system_prompt`
(`ml_model_proposal_agent.py:1347`), which is what the production proposer
hands the model.

**C(ii)** — a real contradiction is rejected before the boundary, asserted
by **LLMBridge call count == 0** on a `BoundaryRecorderBridge` constructed
BEFORE the attempt, not by exception type alone. A consistent config is
also shown to reach the renderer, without which a load that rejected
everything would satisfy the zero-call assertion and prove nothing.

```text
TWO TEST DEFECTS found and fixed while writing this checkpoint

1. The first cut asserted the whole rendered CONTRACT BLOCK appears in the
   proposer system prompt. It does not. Reading
   `_render_commit_system_prompt` shows it substitutes INDIVIDUAL fields —
   `fc.input_shape`, `fc.output_shape`, `fc.output_description` — into
   `PROPOSAL_COMMIT_PROMPT`. After M4 the first two are DERIVED, so the
   claim holds; the assertion was wrong, not the code. Corrected to assert
   the derived shapes.

2. A cardinality contrast varied the contract's class axis alone and was
   correctly REFUSED at load by rung 3-E, because the bound Dataset
   Profile still declared 256. That is the system working — and it is
   C(ii)'s subject. Corrected by binding a profile whose
   `ValueEncoding.num_classes` matches, so the contrast varies the
   cardinality on BOTH authorities rather than bypassing the check.
```

**A boundary deliberately NOT enforced at load, recorded so it is not read
as a gap.** An unsupported input dtype (e.g. `bfloat16`-only) is *not*
rejected by `load_task_config`. Dtype admissibility is a model-boundary
requirement resolved at EXECUTION (§4a.1), and the contract may
legitimately express a dtype this runtime cannot materialize (A-1
correction 2). It fails closed where it is consumed — the subprocess
boundary of C(iii) — and a test states that division explicitly.

#### CHECKPOINT C (iii) — **PASS**, and it found a production gap

```text
module   tests/integration/execute_tools/test_step03_checkpoint_c_subprocess.py
result   7 passed — pytest rc 0, 13.8 s
method   real subprocess.run of execute_tools/train_engine_sandbox.py,
         real HDF5 on disk, PYTHONPATH pinned to THIS checkout
         (the 02a portability lesson, asserted by its own test)
```

```text
PRODUCTION GAP FOUND BY THIS CHECKPOINT — and closed

Previous implementation assumption
  Rung 3-E is enforced at `load_task_config`, so a contract that
  contradicts the dataset cannot reach execution.

Source evidence
  The training child receives the Dataset Profile and the Model-I/O
  contract as TWO SEPARATE argv files and cannot assume the parent paired
  them. Nothing re-checked them. A contradictory pair built a 16-wide
  model against 256-valued data and died with a torch embedding index
  error deep inside `forward`.

Corrected implementation understanding
  Production is safe BY CONSTRUCTION today — the parent derives the
  contract from an already-validated `load_task_config()` — but "safe by
  construction" is not "fails closed", and the child is the boundary that
  actually consumes the pair.

Implementation consequence
  `train_engine_sandbox.main` re-runs M2's resolver with the profile's
  `num_classes`. It REUSES the same authority rather than adding a second
  check, so there is still one rule. A contradiction is now a typed
  refusal naming both numbers, before a single training step.

Validation consequence
  Only a real subprocess test could find this: every in-process test
  passes either way, because in-process callers get the pair from the one
  validated source.
```

**Cardinality: what C(iii) can and cannot prove, decided from source.**
A positive 16-class contrast is NOT expressible over a real HDF5 fixture.
`ValueEncoding` validates that the alphabet holds the storage dtype's
shifted range, so an `int8` dataset offset by 128 spans `[0, 255]` and its
`num_classes` is necessarily **256**; numpy has no narrower integer type.
The dataset-side alphabet is bounded by its storage dtype — Step-02's
authority, not this PR's to change.

| Claim | Owner |
|---|---|
| cardinality DERIVATION at 10 / 64 classes | in-process rung 3-C (M6) — constructs models directly, unbound by a real dataset |
| cardinality TRANSPORT across the subprocess | C(iii)'s contradiction case — the child could not refuse a contradiction it had not received |

The negative case is the stronger evidence: a passing 256 run cannot
distinguish *"the contract crossed"* from *"the literal was already
right"*, whereas a typed refusal naming both numbers can only happen if
the contract arrived and was consulted.

**Dtype: proven by the case that must FAIL, for the same reason.** For
TIDMAD, "the contract's dtype was consulted" and "the site's historical
dtype was used anyway" both yield int32. A `bfloat16`-only contract
discriminates: it fails only if the declared admissibility reached the
child and was intersected with runtime capability THERE. A narrowed
`int64`-only contract is the positive control — not the training site's
historical int32 preference, so it exercises §24.9 Q7 across the process
boundary.

**Three fixture corrections, all the same lesson.** C(i) and C(iii) each
first varied cardinality on the CONTRACT alone while the dataset still
declared 256, and were correctly refused; the third was the encoding bound
above. Cardinality lives on two authorities by design (§4b), and a
contrast must move both. Each refusal was the system working.

**A PRE-EXISTING failure, recorded and NOT adopted.**
`tests/integration/execute_tools/test_step02a_checkpoint_c_profile_boundary.py`
fails one test at HEAD. Verified pre-existing: `git show f865038f:<path>`
contains **zero** occurrences of `anchor_selection_files`, so it never
carried the fields Step 02c made required — it was already broken before
Step 03 began. Not adopted into this PR; recorded as follow-up debt on the
Step-02 integration surface.

### 24.7 Mutation dossier

| # | Mutation | Expected | Observed | Verdict |
|---|---|---|---|---|
| **M-A6-1** | `train_engine_sandbox.py:660` `.int()` → `.long()` | epoch rung reds on the embedding arm only | **5 failed, 1 passed** — `fcnet` correctly unaffected | behaviour-changing, **caught** |
| **M-A6-2** | `train_engine_sandbox.py:1029` `.int()` → `.long()` | streaming rung reds on the embedding arm only | **5 failed, 1 passed** | behaviour-changing, **caught** |
| **M-A6-3** | `inference_single.py:216` `.long()` → `.int()` | inference rung reds on the embedding arm only | **5 failed, 7 passed** | behaviour-changing, **caught** |

Hygiene: `__pycache__` cleared before each run; each mutation restored
with `git checkout --` immediately after; the baseline re-run **green
(30 passed)** from the restored tree. The `1 passed` / `7 passed` in each
row is `fcnet` — the per-arm separation is load-bearing, not decoration:
a single shared expectation across all six builtins would have hidden
exactly this.

**Failure class covered.** *A Phase-B change silently alters, or quietly
unifies, the concrete dtype reaching a model.* Nothing else in the suite
catches it.

#### A2 / A3 / A8 mutations

| # | Mutation | Expected | Observed | Verdict |
|---|---|---|---|---|
| **M-A2-1** | a re-key treats `custom` as a classification family member (`CLASSIFICATION_LOSSES` += `"custom"`) | the `regressor × custom` cell flips ACCEPT→REJECT | **2 failed** — `test_every_matrix_cell[regressor-custom]` **and** the frozenset partition pin | behaviour-changing, **caught by the cell itself**, not only by the frozenset pin |
| **M-A2-2** | a re-key generalises `classifier` to `!= "regressor"` | some accept flips to reject | **1 failed** — and it is `test_an_output_type_outside_the_alphabet_is_currently_TOLERATED`, the ONLY test that catches it | behaviour-changing, **caught** |
| **M-A3-1** | load-time tier becomes STRICT (`return None` instead of defaulting) | lenient tier + divergence red | **2 failed**, incl. the divergence claim | behaviour-changing, **caught** |
| **M-A3-2** | lookup tier becomes LENIENT (`return "classifier"` instead of raising) | strict tier + divergence red | **2 failed**, incl. the divergence claim | behaviour-changing, **caught** |
| **M-A8-1** | `PLUGIN_OUTPUT_TYPE` becomes REQUIRED (`module.X` not `getattr(..., default)`) | prior plugins stop loading | **A8 stayed GREEN**; only A3's absent-declaration test red | **SURVIVED at A8** — see below |
| **M-A8-2** | the loader requires a NEW attribute prior plugins cannot have (`PLUGIN_IO_CONTRACT`) | every on-disk plugin stops loading | **8 failed**, incl. `test_every_on_disk_plugin_still_loads_and_declares_a_valid_contract` | behaviour-changing, **caught** |

**M-A2-2 is the most informative row.** Under that mutant, `hybrid` is
still protected by the unconditional early `return` at `:422`, so every
`hybrid` cell survives and only the out-of-alphabet case flips. The
tolerance test — the one nearly not written, since "unknown values are
out of the declared universe" — is the sole oracle for that re-key
shape. Recorded so nobody deletes it as redundant.

**M-A8-1's survival is a finding, not a gap.** A8 stayed green because
**all 85 on-disk plugins already declare `PLUGIN_OUTPUT_TYPE`**, so
making it required genuinely does not break this population. The
mutation was therefore not behaviour-changing *for A8's claim*, and was
replaced by **M-A8-2**, which is. Recorded rather than quietly swapped:
a mutation that survives because the codebase made it equivalent is
different from one that survives because the oracle is weak.

#### A2 / A3 / A8 — **CAPTURED**

```text
A2   tests/unit/ml_models/test_step03_a2_loss_compatibility_matrix.py
     22 passed / 0.10 s
A3   tests/unit/ml_models/test_step03_a3_a8_plugin_compatibility.py
A8   (same module — 10 passed / 1.19 s, ZERO skips, so the on-disk
      population really was exercised)
environment  CPU only; no GPU, no LLM, no real dataset
production   ZERO diff across all three
ruff check + ruff format --check clean on both modules
```

**A2 — the full 15-cell matrix**, hardcoded from source
(`models_format_sandbox.py:374-437`), never computed from the frozensets
the function itself reads. 11 accept, 4 reject; the only rejections are
`classifier × smooth_l1` and `regressor × {ce, focal, focal_cw}`.
`hybrid` (all five) and `custom` (all three) were asserted **nowhere**
before this module.

Also pinned, as behaviour rather than endorsement: an `output_type`
**outside** the declared alphabet is currently **TOLERATED** — neither
guard branch matches, so the function returns without raising. §8a's
re-key would most naturally start failing closed there. That would be a
changed verdict, i.e. a §21 STOP, not a free improvement. **If that test
reds during the re-key, stop and decide — do not update the
expectation.**

**A3 — the two tolerance tiers, and their divergence.** Load-time
(`plugin_loader.py:81-88`) warns and defaults to `classifier`;
lookup-time (`:192-214`) raises `UnknownOutputContractError`. The strict
tier already had oracles; the **lenient** tier had none, and **nothing
asserted that the two differ** — which is the assertion §5 A3 actually
asks for, since §8b's projection is a natural place to harmonise them in
either direction.

**A8 — 85 on-disk plugins**, all loading through the production loader
and all declaring a contract in `{classifier, regressor, hybrid}`.

*Workspace boundary, declared not assumed.* `agent_generated/models/*`
is **gitignored** (only `.gitkeep` tracked), so a fresh clone and CI hold
zero plugins while a developer checkout holds the accumulated
population. §5 A8 accepts either evidence, so the module inspects the
workspace and **skips with an explicit reason** when empty rather than
passing vacuously. This run had 85 and zero skips.

*Finding.* **All 85 declare `PLUGIN_OUTPUT_TYPE`** — so §5's Regime-A
inventory item *"on-disk plugins with no `PLUGIN_OUTPUT_TYPE`"* is an
**empty class in this workspace**. The legacy tolerance path is therefore
exercised only by A3's synthetic fixture, which is exactly why that
fixture is not decoration.

#### **CHECKPOINT 0 — PASS**

A2, A3, A6 and A8 all captured before any production change. Every
module has zero production diff; every genuinely new oracle is
mutation-proven (§24.7).

#### M2 mutations

| # | Mutation | Expected | Observed | Verdict |
|---|---|---|---|---|
| **M-M2-1** | the preset is silently DROPPED (`if missing:` → `if False:`) | FX-4 family reds | **3 failed** — exactly the FX-4 class | behaviour-changing, **caught** |
| **M-M2-2** | an unknown preset is silently IGNORED | the invalid-preset-name guard reds | **1 failed** — only `test_an_unknown_preset_fails_closed` | behaviour-changing, **caught precisely** |
| **M-M2-3** | a dataset contradiction is silently ACCEPTED | 3-E family reds | **3 failed** — the 3-E class + the atomicity claim | behaviour-changing, **caught** |
| **M-M2-4** | the *"cardinality not meaningful"* guard is dropped (`declared is not None and …` → `declared != …`) | the §4b asymmetry reds | **1 failed** — only `test_an_output_without_class_semantics_is_not_forced_to_match` | behaviour-changing, **caught by its sole oracle** |

Baseline re-run **17 passed** from the restored tree; the three mutated
lines verified back to their originals by inspection, not assumed.

```text
FINDING — a mutation-hygiene defect, caught by the restore check

Previous implementation assumption
  `git checkout -- <file>` restores a mutated file.

Source evidence
  The first M2 mutation round ran against UNTRACKED new files. Every
  `git checkout --` printed
  "error: pathspec ... did not match any file(s) known to git"
  and restored nothing, so mutations ACCUMULATED: by round 3 all three
  guards were `if False:` simultaneously and the per-round failure
  counts (3 / 4 / 7 / 7) were cumulative, not attributable.

Corrected implementation understanding
  Only the first round of that series was a valid attribution. The
  accumulation was visible only because the mandatory post-mutation
  baseline re-run came back RED instead of green.

Implementation consequence
  The whole series was discarded and re-run after `git add` staged the
  files, which gives `git checkout --` an index to restore from. Every
  count in the table above comes from that clean series.

Validation consequence
  A mutation target must be TRACKED (committed or at least staged)
  before mutating. The post-mutation baseline re-run is not ceremony —
  it is the only thing that detected this, and a dossier written without
  it would have recorded four confident, wrong attributions.
```

#### M3 mutations

| # | Mutation | Expected | Observed | Verdict |
|---|---|---|---|---|
| **M-M3-1** | `hybrid` acquires tensor semantics (`None` → `CATEGORICAL`) | the `hybrid` row and the tolerance rule red | **6 failed** — §8c tests, both tolerance tests, and A2's `hybrid × smooth_l1` cell | behaviour-changing, **caught** |
| **M-M3-2** | the §8b projection is inverted | verdicts flip wholesale | **11 failed** — the entire `regressor` row plus the diagnostic pin | behaviour-changing, **caught** |
| **M-M3-3** | the output semantic stops being DERIVED (always categorical) | the derivation class reds | **4 failed** — derivation, projection-from-contract and the contract-drives-legality test. **A2 untouched**, correctly: A2 does not go through the contract | behaviour-changing, **caught** |
| **M-M3-4** | the legacy entry point REIMPLEMENTS the rule instead of delegating | the duplicate-authority class reds | **1 failed** — `test_the_legacy_entry_point_delegates_rather_than_reimplementing`, and **A2 stayed fully green (45 passed)** | behaviour-preserving but authority-duplicating, **caught by its sole oracle** |

Baseline re-run **46 passed** from the restored tree.

**M-M3-4 is the row that justifies the module.** The duplicated rule
agrees with the delegated one on all 15 cells, so every verdict oracle —
A2 included — stays green while a second copy of the loss rule is live.
That is exactly how `LossConfig.check_compatibility` became a
contradictory second authority before V21 PR A deleted it. Only a
structural assertion catches it, which is why §8a's *"re-key, do not
re-declare"* needed a test that reads the delegation rather than the
verdicts.

Hygiene: all four ran with the modified production files **staged**, so
`git checkout --` restored from the index rather than reverting the M3
work itself — the generalisation of the §24.7 finding recorded at M2.

### 24.8 Amendment A-1 — **OPERATOR-APPROVED 2026-08-13**

**Approved with two corrections, and PROMOTED into the frozen design as
§4a.1.** That section is now the authority; what follows is the
provenance record of how it got there, kept so a reviewer can see the
proposal, the corrections and the reasoning rather than only the result.

```text
proposed      one dtype REQUIREMENT on the contract; each site keeps its
              own concrete dtype; resolver validates
approved      YES — the model owns dtype ADMISSIBILITY, execution owns
              the concrete representation
correction 1  resolution must NOT be "site dtype if admissible, else
              fail". That would elevate a legacy site preference into a
              semantic constraint. It must reach a supported admissible
              ALTERNATIVE, and fail only on an empty intersection.
correction 2  do NOT bound the contract to {int32, int64, float32}, and
              do NOT freeze INTEGER_INDEX / REAL_VALUED as the public
              vocabulary. The requirement is an EXTENSIBLE normalized
              admissibility declaration:
                contract expressiveness > validated runtime support.
              Validated today: int32, int64, float32 — nothing else may
              be claimed executable. Expressible without a schema
              redesign: float16, bfloat16, float64, bool, complex64/128.
              Not widened into quantization / mixed-precision policy.
```

The original proposal text is superseded by §4a.1 and is not duplicated
here.

### 24.9 Narrow dtype adversarial re-review — required before Phase B

Answered against §4a.1 as amended. Q1-Q12 are the operator's list;
Q13-Q14 come from correction 2. **Re-run mechanically against the code
before the first Phase-B production edit** — the answers below are the
DESIGN's position, and only the implementation can confirm them.

| # | Question | Design answer |
|---|---|---|
| 1 | Does any model-name branch still determine dtype semantics? | **NO by design** — §4a.1 routes on the declared requirement. The 3 input-dtype sites are the migration target; the guardrail must cover them (§24.10) |
| 2 | Does any `output_type` value determine input dtype semantics? | **NO** — §4a.1 forbids inferring the requirement from output semantics. A6's correlation is a fact about the current roster, not a contract |
| 3 | Did training / inference become fields in the Model-I/O contract? | **NO** — `training_dtype` / `inference_dtype` / `boundary_dtype_map` are forbidden fields and a §21 stop condition |
| 4 | Is the concrete TIDMAD A6 matrix preserved? | **YES** — the legacy site dtype is a compatibility preference honoured whenever it lies in the valid intersection. A6 must pass **unmodified** |
| 5 | Can the contract express today's index-style and float-input requirements without a modality / model-name branch? | **YES** — admissibility is declared per contract, resolved by intersection |
| 6 | Is a site preference being mistaken for a model requirement? | **NO** — explicitly separated; correction 1 exists precisely to prevent it |
| 7 | Can a supported non-default concrete dtype be selected when the site's preferred dtype is inadmissible? | **YES, required** — this is correction 1. A resolver that cannot do this is wrong |
| 8 | Does an unsupported / empty intersection fail closed? | **YES** — typed failure, never coercion. Rung 3-B-neg |
| 9 | Did we invent a general conversion algebra? | **NO** — only adaptations current production consumers justify (§4a) |
| 10 | Did we freeze a dtype taxonomy with no live consumer? | **NO** — correction 2 forbids freezing the vocabulary; validated support stays `int32` / `int64` / `float32` |
| 11 | Is dtype still atomic and independent from cardinality / output semantics? | **YES** — 3-B varies dtype alone; 3-C cardinality alone; 3-D output semantics alone |
| 12 | Does `LOSS_TARGET_DTYPE_REGISTRY` remain a *precedent* rather than being merged into the input contract? | **YES** — target-side authority, untouched. It is the shape to mirror, not to absorb |
| **13** | Would representing `float16` / `bfloat16` / `float64` / `bool` / `complex64` / `complex128` require a schema redesign? | **Must be NO.** Expressiveness exceeds validated runtime support; verify against the actual schema before Phase B |
| **14** | Does the design claim any concrete dtype executable without evidence? | **NO** — only `int32`, `int64`, `float32` are claimed, and A6 executes all three |

#### §24.9 RE-RUN AGAINST THE ACTUAL PHASE-A CODE — 2026-08-13, at `4819b44a`

Required before the first Phase-B edit. The §24.9 table records the
DESIGN's position; this records what the code does.

| # | Question | Verified against code |
|---|---|---|
| 1 | dtype keyed by model NAME? | **NO** — no `admissible` reference co-occurs with a model-name literal anywhere in `agent/`, `workflows/`, `ml_models/`, `execute_tools/` |
| 2 | dtype keyed by `output_type`? | **NO** — no classifier/regressor/hybrid token appears near the dtype declaration |
| 3 | boundary dtype fields in the contract? | **NO** — `training_dtype` / `inference_dtype` / `boundary_dtype` / `site_dtype` return zero hits |
| 4 | A6 concrete matrix preserved? | **YES, by construction** — `git diff f865038f..HEAD` over `train_engine_sandbox.py` and `inference_single.py` is **empty**; Phase A touched no execution dtype site |
| 5 | today's requirements expressible without a modality branch? | **YES** — the shipped YAML declares both tensors' admissibility; the only `len(axes)` is the schema's own `rank` accessor, not a branch |
| 6 | site preference mistaken for model semantics? | **NO** — "site preference" appears only in docstrings explaining that it is *not* model semantics; no field carries one |
| 10 / 14 | any dtype claimed executable without evidence? | **NO** — the only `float16` / `bfloat16` / `complex64` mentions in production are the docstring stating they are EXPRESSIBLE-not-supported. Other `float64` hits are pre-existing numpy scoring/health-check code, unrelated to the model contract |
| 11 | dtype independent of cardinality / output semantics? | **YES** — `DtypeAdmissibility` and `class_cardinality` / `output_semantic` share no field and no derivation |
| 12 | `LOSS_TARGET_DTYPE_REGISTRY` still a separate precedent? | **YES** — not referenced from `agent/schemas/` at all |
| 13 | future dtypes need a schema redesign? | **NO** — M1's expressibility tests declare `float16`, `bfloat16`, `float64`, `bool`, `complex64`, `complex128` through the shipped schema unchanged |

**Q7 and Q8 are M5's to satisfy** — "can a supported non-default dtype be
selected when the site preference is inadmissible" and "does an empty
intersection fail closed" are properties of resolution code that does not
exist until Phase B. They are carried as M5's acceptance criteria rather
than answered here, because answering them now would be answering about
code that has not been written.

**Verdict: no material NO. Phase B may proceed.**

### 24.10 Guardrail coverage (implementation evidence, not a new capability)

`tests/unit/guardrails/test_no_model_name_branches.py` `_SCAN_TARGETS`
covers `evaluate_vram_skill`, the two estimators and
`core/inference_defaults.py` — **not** `execute_tools/
train_engine_sandbox.py` or `execute_tools/inference_single.py`, i.e.
not the sites Step 03 migrates. Roadmap §15.1's Step-3 A-cell already
names *"guardrail targets extended"*.

Treated as **implementation evidence**, not a new design capability. The
final guardrail must catch reintroduction of model-name-based dtype
routing on every migrated Step-03 execution surface, using
semantic / AST / source-pattern coverage in the existing guardrail's
idiom — **not** a pin on today's line numbers.

**DELIVERED** as `tests/unit/guardrails/test_no_model_name_dtype_routing.py`.

```text
Previous implementation assumption
  Extend `_SCAN_TARGETS` in test_no_model_name_branches.py to the two
  migrated files.

Source evidence
  That guardrail bans architecture-name TOKENS outright. Pointing it at
  train_engine_sandbox.py / inference_single.py flags the three
  CONSTRUCTOR branches finding F-2 deliberately leaves in place. Clearing
  them would require inventing a consumer-less contract field (§21).

Corrected implementation understanding
  The token ban is the wrong instrument for this surface. Step 03's actual
  invariant is narrower and exact: a model NAME must never decide a DTYPE.
  Stated semantically over the AST — an `if`/`IfExp` comparing a
  model-name literal whose body performs a dtype operation — with no count
  and no line number.

Implementation consequence
  A second, focused guardrail module rather than a row in the existing
  one. `MIGRATED_SURFACES` is the list a future step extends to declare a
  surface contract-routed.

Validation consequence
  Reachability is proven, not assumed: the guard is fed the exact
  expression form removed from `train_engine_sandbox.py:660` and the exact
  statement form removed from `inference_single.py:213`, and must flag
  both. A regression here is behaviourally INVISIBLE — re-hardcoding the
  branch reproduces A6 exactly — so a structural claim is the only oracle
  that can see it.
```

**A defect in the first cut of the guard, caught by its own F-2 case.**
`.to` was put in the unambiguous-dtype set, so `.to(device)` matched and
the guard reported `train_engine_sandbox.py:621` — an F-2 constructor
branch — as a live violation. It is not one. `.to()` is now classified by
its ARGUMENT: a `dtype=` kwarg or a dtype-valued positional makes it a
cast, a bare device move does not. Both directions are pinned — the
constructor branches are NOT flagged, and `.to(torch.int32)` still is.

*Test economy*: M5's `test_the_data_path_contains_no_input_dtype_name_branch`
counted surviving branch lines and was REMOVED, with a comment in its
place explaining where the claim went. It was brittle — it would red if a
later step legitimately added a constructor branch — and this guard now
states the same property properly. One claim, one owner.

### 24.11 Final state

*(empty — no PR opened)*
