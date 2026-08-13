# Step 03 — Model / Loss Contract — detailed design (parent)

## 0. Status and verified prerequisites

**STEP 03 DESIGN — READY FOR OPERATOR REVIEW (2026-08-13). NOT FROZEN.**

Design only. No implementation branch, no worktree, no Gate has been run.

### 0.1 Verified base (mechanical, not conversational)

| Fact | Value |
|---|---|
| Design base | `1826f9fd` = `origin/master`, clean tree |
| Step 00 | MERGED — PR #198 |
| Step 01 | **COMPLETE / MERGED** — 01a PR #199 (`39f89f52`), 01b PR #201 (`fe05f5f7`) |
| Step 02 | **COMPLETE / MERGED** — 02a `47359538`, 02b `c17469ec`, 02c `1807054b`; governance sync `1826f9fd` |
| Roadmap §15.1 Step-02 row | COMPLETE / MERGED |
| Step-03 document | **DID NOT EXIST before this one** |

### 0.2 There was no Step-03 draft — recorded, because the task assumed one

The instruction was to *re-read the current Step-03 draft*. Mechanically,
`docs/design/generic_framework_upgrade/` contained only steps 00, 01 and
02; the folder README listed step 03 as **"not created"** and roadmap
§15.1 as **NOT STARTED**.

So there is no draft to correct. The Step-03 *hypothesis* lives in three
places, and this document is the first to treat them as one problem:

1. **roadmap §5** — module couplings, target responsibility, the §5.5
   contrast ladder, §5.6 convergence candidates;
2. **Step-01's deferral D13** — FX-3 / FX-4, explicitly assigned to *"the
   contract owner (step 2 §4 / step 3 §5)"*. **Step 02 did not land them**
   — it owns dataset facts, not model I/O — so they land here;
3. **Step-02's completion**, which created the Dataset Profile that
   Step 03 must derive from and cross-validate against rather than
   duplicate.

§1 below audits each hypothesis against current source. Several
roadmap-era claims survive; two are sharpened; none was adopted on the
strength of already being written down.

---

## 1. Source audit of current master

Every row was re-verified at `1826f9fd`.

| # | Hypothesis (roadmap §5 / D13) | Current source evidence | Still true? | Corrected understanding | Design consequence |
|---|---|---|---|---|---|
| 1 | `ForwardContract` carries shapes as PROSE | `agent/schemas/task_config.py:50-99` — `input_shape: str`, `output_shape: str`; the only structured fields are `num_classes: int` and free-form `task_type: str` | **TRUE** | There is **no** structured tensor representation anywhere: no rank, axes, axis roles, dtype field, tensor names or multiplicity | Step 03's core deliverable is a normalized tensor contract |
| 2 | 256 hardcoded across builtins | **27 occurrences** in `ml_models/models_sandbox.py` | **TRUE** | Class count is a model-construction literal, not a derived value | PR-B derives it |
| 3 | Dtype at the model boundary is NAME-keyed | **6 production sites**: `train_engine_sandbox.py:614,660,817,1029`; `inference_single.py:213,410` — e.g. `input_seq.float() if model_cfg.model_type == "fcnet" else input_seq.int()` | **TRUE, and sharper than recorded** | The **input dtype of a real training/inference tensor is chosen by a model-NAME string comparison**. This is the single most dangerous coupling in Step 03's scope: it fails silently, in the data path | PR-B's primary failure class |
| 4 | `output_type` alphabet is asymmetric; `hybrid` cannot be generated | `plugin_loader.py:82` accepts `{classifier, regressor, hybrid}`; `proposal.py:974` and `implementor.py:189` are `Literal["classifier","regressor"]` | **TRUE — confirmed on master** | `hybrid` is reachable **only** for the builtin `fcnet`. `plugin_loader:82`'s hybrid arm is dead for plugins | The alphabet must be resolved to ONE authority; `hybrid`'s fate is an operator question (§17 Q2) |
| 5 | Loss compatibility has a single production authority | `models_format_sandbox.py:374` `validate_output_loss_compatibility`, documented as *"THE production authority"*, with two named consumers (`ExperimentConfig`; `SandboxExecutor._validate_configs`) | **TRUE** | Step 03 must **NOT** create a second loss declaration. The frozensets are already the authority | §8: NORMALIZE and re-key, do not re-declare |
| 6 | Loss families are class-agnostic but shape-coupled | `CLASSIFICATION_LOSSES` is documented as *"losses that consume per-timestep class logits, **[B, C, T]**"*; `REGRESSION_LOSSES` as *"a continuous waveform, **[B, T]**"* | **TRUE** | Loss legality is genuinely a **function of the output tensor contract** — not of a free-standing string. That is why loss cannot be split from the contract (§6) | Loss legality DERIVES from the normalized output contract |
| 7 | Step 01 left `render_forward_contract` survivors | `workflows/task_config.py:209` — `f" (per-timestep {fc.num_classes}-class)" if fc.num_classes else ""` | **TRUE** | The renderer asserts a **temporal axis exists** whenever a class count is non-zero. A rank/axis assumption leaking into prose | Must derive from axis ROLES, not from `num_classes` being truthy |
| 8 | FX-3 / FX-4 are owned by "step 2 §4 / step 3 §5" | roadmap §14 D13; `step_01_…md` §1244-1245 | **TRUE, and now unambiguous** | Step 02 closed without them (correctly — no model-I/O authority). **Step 03 is the owner** | Binding Stage-B requirement (§9) |
| 9 | `[B,256,T]` prose is confined to the contract | **FALSE — it is duplicated** at `validator.py:200`, `implementor.py:195`, `proposal.py:996`, plus `models_format_sandbox.py:367,371` | **NEW FINDING** | The model I/O contract is currently **four+ independent prose restatements**, two of which hardcode `256` | Stage-A parity must cover every restatement site, not just the renderer |
| 10 | Encoding/class count is unowned | **FALSE since 02a** — `ValueEncoding` declares `num_classes`, `value_offset`, `storage_dtype`, `compute_dtype` on the Dataset Profile | **CHANGED BY STEP 02** | The **data-side** cardinality now has an owner | Step 03 must **DERIVE / cross-validate**, never redeclare (§7) |

**Two claims sharpened rather than inherited**: #3 (the name-branch is a
*data-path dtype* decision, not cosmetic) and #9 (the contract is
already duplicated four ways, so "extract the contract" is really
"collapse four restatements into one authority").

---

## 2. Final observable Step-03 effect

> **A task declares ONE normalized, rank-agnostic model I/O contract —
> optionally authored through a semantic preset — and the production
> consumers that today restate `[B, 256, T]` prose or branch on a model
> NAME resolve that single declaration instead; contradictions between
> the contract, its preset and the Dataset Profile are rejected as typed
> failures before any LLM-facing or executable consumer sees them, while
> every TIDMAD model, loss and rendered prompt behaves exactly as today.**

### 2.1 What Step 03 explicitly does NOT prove

- that **generated arbitrary models execute correctly** — implementor /
  validator / probe mechanics are Step 04;
- that **arbitrary probe tensors can be constructed** — Step 04;
- that every implementor and validator *prompt* is generic — Step 04;
- that arbitrary **metrics** work — Step 06;
- that runtime **orchestration binds** an arbitrary task — Step 10;
- that a composed non-TIDMAD task runs end to end — Step 12.

Step 03 delivers the **contract and its consistency boundary**. It does
not deliver the machinery that consumes the contract to *build* things.

---

## 3. Ownership

**Step 03 OWNS:**

- the normalized model-I/O tensor contract: named tensors, ordered axes,
  axis semantic roles, dtype, fixed/symbolic/dynamic dimensions,
  cross-tensor dimension relationships;
- preset **resolution** into that one normalized contract;
- the consistency boundary between contract, preset and Dataset Profile
  (FX-3 / FX-4), and the description↔contract channel R2-6 opened by 01b;
- the **output-type alphabet** as a single authority;
- **loss legality as a derivation** from the output contract (re-keying
  the existing authority — not a new declaration);
- contract-keyed **dtype routing** and class-count derivation at the
  model boundary.

**Step 03 does NOT own** — with the reason:

| Not owned | Owner | Why |
|---|---|---|
| file topology, naming, decomposition, dataset legality, channel identity, dataset **encoding declaration**, SampleSet, task-owned file sets | **Step 02 (merged)** | consume and cross-validate; never a second authority |
| generated-plugin templates, implementor/validator prompt mechanics, **probe tensor construction**, `_PROBE_NUM_CLASSES`, runtime model instantiation, generated-code execution, forbidden-pattern enforcement | **Step 04** | Step 03 owns the CONTRACT those mechanics consume, not their execution (§10) |
| metric identity, scoreability | Step 06 | |
| HealthGate semantics | Step 08 | |
| orchestration / task binding | Step 10 | |
| spawn / IPC / rlimits | Step 11 | |
| composition root, universal Regime-B "missing required contract" | Step 12 | |

**No mega TaskConfig.** Step 03 adds one contract, not a task-wide
config object.

---

## 4. Current authorities and duplicated semantics

| Capability | Structured today? | Prose only? | Missing? | Current producer | Live consumers | Step-03 disposition |
|---|---|---|---|---|---|---|
| tensor rank (arbitrary) | — | — | **MISSING** | — | — | **DECLARE** |
| tensor names | — | — | **MISSING** | — | — | **DECLARE** |
| tensor multiplicity (multi-in/out) | — | — | **MISSING** | — | — | **DECLARE** (representable; no consumer yet ⇒ see §17 Q3) |
| ordered axes | — | implied by `[B,C,T]` prose | **MISSING** | — | — | **DECLARE** |
| axis semantic roles | — | implied ("per-timestep") | **MISSING** | — | — | **DECLARE** — this is what replaces rank-specific branching |
| fixed dimensions | — | in prose | partly | contract prose | renderers | **DECLARE** |
| symbolic / dynamic dimensions | — | `B`, `T` by convention | **MISSING** | — | — | **DECLARE** |
| dtype | — | inside the shape string | **MISSING as data** | prose | renderers; **name-branch at 6 exec sites** | **DECLARE** + PR-B derives routing |
| batch/sample semantics | — | `B` by convention | **MISSING** | — | — | **DECLARE** as an axis role |
| cross-tensor relationships | — | — | **MISSING** | — | — | **DECLARE** |
| class count / cardinality | `num_classes: int` (contract) **and** `ValueEncoding.num_classes` (dataset) | — | — | two producers | renderer; 27 builtin literals | **DERIVE / CROSS-VALIDATE** — never two authorities |
| `task_type` | free-form `str` | — | — | contract | renderer prose | **NORMALIZE or drop** (§17 Q4) |
| `output_type` | `Literal` ×2 (2 values) + `plugin_loader` (3 values) | — | — | **three surfaces** | validators, loaders | **ONE authority** |
| output-head semantics | — | `output_head_note` prose | — | contract | implementor prompt | **DERIVE** from output tensor + roles |
| loss-family legality | frozensets + `validate_output_loss_compatibility` | shape rationale in docstrings | — | **single authority** | `ExperimentConfig`, `_validate_configs` | **RE-KEY to the contract**, do not re-declare |

---

## 5. Compatibility contract (Stage-A)

Never "behaviour unchanged". Per surface, strongest observable criterion:

| # | Surface | Strongest criterion | Baseline exists? | Owning child |
|---|---|---|---|---|
| A1 | rendered proposer prompts (3 stages) | byte-identical for TIDMAD, or a declared, mechanically-attributable golden set (the OD-S1-8 precedent) | **YES** — Step-01 `pb3_*` goldens | PR-A |
| A2 | rendered forward-contract block | byte-identical for TIDMAD | **YES** — Step-01 | PR-A |
| A3 | `validate_output_loss_compatibility` verdicts | identical accept/reject for every (output_type, loss_type) pair, including `custom` and `hybrid` | partial — **capture the full matrix first** | PR-A |
| A4 | plugin load tolerance tiers | silent `classifier` default vs fail-closed `get_output_type` both unchanged for existing on-disk plugins | partial — **capture first** | PR-A |
| A5 | builtin model forwards | byte-identical outputs for every builtin under TIDMAD | **YES** — Step-00 | PR-B |
| A6 | registry contents | identical under the TIDMAD profile | **YES** — Step-00 | PR-B |
| A7 | training/inference dtype at the model boundary | the exact same tensor dtype reaches each builtin, `fcnet` included | **MISSING — capture first** | PR-B |
| A8 | Step-00 numeric baselines | unchanged | **YES** | PR-B |
| A9 | **prior on-disk generated plugins remain loadable** | every plugin in `agent_generated/` still loads, or a workspace boundary is declared | **MISSING — capture first** | PR-B |

Reuse Step-00/01/02 baselines; capture only A3, A4, A7, A9.

---

## 6. PR decomposition decision — **TWO** children

Tested against the six criteria, not against a wish for symmetry.

**Rejected splits, with reasons:**

- **presets as their own PR** — a preset has **no independent production
  consumer**; it resolves *into* the normalized contract. A separate PR
  would ship a consumer-less seam (§0 rule 8). **Folded into PR-A.**
- **loss as its own PR** — loss legality is documented as a function of
  the output tensor shape (audit #6), the authority already exists with
  two consumers, and its parity oracle (accept/reject matrix) is
  validated at the same boundary as the contract. A separate PR would be
  a handful of lines plus a full checkpoint ladder. **Folded into PR-A.**
- **output-type alphabet as its own PR** — same boundary, same oracle.
  **Folded into PR-A.**

**Accepted split.** PR-B is separable because all six criteria hold
independently: its own effect (models are keyed by contract, not by
name), its own consumers (`train_engine_sandbox`, `inference_single`,
builtins), its own oracle (builtin forward parity + Step-00 numerics),
its own failure class (**a silently wrong tensor dtype in real
training** — invisible to any prompt test), its own Stage-B rungs
(5.5-A/5.5-B), and real rollback value.

The seam is: **PR-A changes no executed tensor; PR-B changes no rendered
prompt.**

---

## 7. Child PR capability blocks

### PR 03a — Normalized model-I/O contract, presets, and the consistency boundary

```text
CAPABILITY: a task declares ONE structured, rank-agnostic model I/O
  contract — named tensors, ordered axes with semantic ROLES, dtype,
  fixed/symbolic/dynamic dims, cross-tensor relations — optionally
  authored via a preset; every consumer that today restates [B,256,T]
  prose resolves that one declaration; contradictions with the preset,
  the Dataset Profile or the task description fail CLOSED before any
  LLM-facing consumer.
OWNS: the normalized contract; preset RESOLUTION (never a parallel
  runtime semantic); the ONE output-type alphabet; loss legality
  RE-KEYED to the output contract; the FX-3/FX-4/R2-6 consistency
  boundary.
DOES NOT OWN: probe construction, implementor/validator mechanics
  (Step 04); dataset facts (Step 02); execution dtype routing (PR-03b).
CURRENT PRODUCTION CONSUMERS: workflows/task_config.render_forward_contract
  and the three proposer stages; agent/schemas/{proposal,implementor,
  validator}.py shape prose; models_format_sandbox's compatibility
  authority and its two callers.
STAGE-A PARITY: A1-A4. Rendered TIDMAD prompts byte-identical or a
  declared attributable golden set; the loss accept/reject matrix
  identical including `custom` and `hybrid`.
STAGE-B CONTRAST: FX-3 (preset resolution only) and FX-4 (preset-vs-
  explicit mismatch rejected before the LLM boundary) — both BINDING
  from D13 — plus axis/dtype/output-type rungs (§9).
CHECKPOINT C: a REAL proposer stage renders from the resolved contract
  in a live chain iteration, and a REAL contradictory configuration is
  rejected before any LLMBridge call is made.
FAILURE CLASS: a model contract that contradicts the data it will be
  trained on reaches the LLM, producing a plausible model that is wrong
  in a way no shape assertion catches.
DEPENDENCIES: Step 01 (renderer), Step 02 (Dataset Profile). None on 03b.
MERGE ALONE? YES — the contract and its fail-closed boundary are useful
  without changing one executed tensor.
GATE: Gate 1 LIKELY REQUIRED — this PR can move LLM-facing prompt bytes
  (the standard's "New LLM-facing system prompt" row). Gate 2 NOT
  expected: no training-path behaviour changes. Decided from the gate
  table at freeze, not now.
STOP: a preset becomes a second runtime authority; any consumer branches
  on rank or modality name; dataset cardinality is copied rather than
  derived/cross-validated; a contradiction can still reach LLMBridge.
```

### PR 03b — Contract-keyed execution: dtype routing and class-count derivation

```text
CAPABILITY: the model boundary reads its input dtype and class count
  from the resolved contract instead of from a model NAME, so a task
  with a different encoding or cardinality trains and infers correctly
  with no source edit.
OWNS: contract-keyed dtype routing at the 6 name-branch sites; class
  count derivation in the builtin catalogue.
DOES NOT OWN: probe recipes / probe construction (Step 04); estimator
  ×256 terms (Step 07d derives from this contract — §13); loss math
  (FocalLoss1D stays paper-frozen, byte-identical).
CURRENT PRODUCTION CONSUMERS: execute_tools/train_engine_sandbox.py
  (:614,:660,:817,:1029), execute_tools/inference_single.py (:213,:410),
  ml_models/models_sandbox.py builtins (27 `256` literals).
STAGE-A PARITY: A5-A9. Builtin forwards byte-identical; registry
  identical; **the same dtype reaches each builtin including fcnet**;
  Step-00 numerics unchanged; prior on-disk plugins still loadable.
STAGE-B CONTRAST: 5.5-A class count only; 5.5-B input contract only
  (a contract-keyed float-input model at 256 classes — kills the fcnet
  branches attributably).
CHECKPOINT C: a REAL training + inference round feeds a contract-derived
  dtype and class count through the actual subprocess boundary.
FAILURE CLASS: a silently wrong tensor dtype or class count in real
  training — produces a plausible model and a plausible score, and no
  prompt-level or schema-level test can see it.
DEPENDENCIES: **PR-03a** (there is no contract to key on before it).
MERGE ALONE? NO — strictly after 03a.
GATE: Gate 2 LIKELY REQUIRED — real training on real files is the only
  boundary where a wrong dtype/class count manifests. Gate 1 not
  expected (no prompt bytes). Decided from the gate table at freeze.
STOP: any builtin forward output changes; FocalLoss1D math is touched;
  a name branch is replaced by a rank branch; prior plugins stop loading
  without a declared workspace boundary.
```

---

## 8. Loss and output-type authority — findings

1. **Do not create a loss contract.** `validate_output_loss_compatibility`
   is already THE authority and its own docstring records the lesson from
   the defect that produced it. Step 03 **re-keys** it so legality derives
   from the output tensor contract rather than from the string
   `"classifier"`; it does not add a second declaration.
2. **The alphabet is genuinely split three ways** (audit #4) and must
   collapse to one. Whether `hybrid` survives that collapse is an
   operator question (§17 Q2) — it has one builtin implementation and is
   unreachable for generated plugins.
3. **`custom` is deliberately permissive** for every contract, by design,
   because the plugin's forward raises at training time. Preserve.
4. **Custom-loss hyperparameter passing** (`loss_models_sandbox:253-276`,
   instantiated with zero args) is a real defect but is **execution
   mechanics** — routed to Step 04 unless PR-03b's audit shows the
   contract is what is missing (§14).
5. **Loss-family membership is framework-owned, not task-owned** on
   current evidence: the frozensets name *implementations that exist in
   this repository*. A task declaring a new loss family without an
   implementation would be a consumer-less seam. **DEFER** until a second
   design needs it.

---

## 9. Stage-B generic contrast ladder

One semantic axis per rung; neutral names — a rung that swaps
"time series" for another familiar modality proves nothing.

| Rung | Varies ONLY | Held fixed | What failure would expose a fake abstraction | Child |
|---|---|---|---|---|
| **3-A** axis structure | rank + ordered axes (roles preserved) | dtype, cardinality, output type, dataset | any consumer branching on rank | 03a |
| **3-B** dtype | declared input dtype | axes, cardinality, output type | dtype still resolved from a model name | 03a → proven in 03b |
| **3-C** cardinality | class count only | axes, dtype, output type | `256` surviving anywhere in a resolved path | 03b |
| **3-D** output type | classifier ↔ regressor | axes, dtype, cardinality | loss legality still keyed on a literal string | 03a |
| **FX-3** preset resolution | preset only, over a fixed explicit contract | everything else | preset producing a second runtime path instead of one normalized contract | 03a |
| **FX-4** mismatch rejection | preset contradicts the explicit contract | everything else | the contradiction reaching LLMBridge, or being silently repaired | 03a |
| **3-E** dataset consistency | contract cardinality vs `ValueEncoding.num_classes` | everything else | silent coercion, or the contradiction reaching training | 03a |

**FX-3 and FX-4 are binding** (D13). **3-E is the Step-02 interface
obligation** — it is the rung that proves Step 03 derives from the
Dataset Profile rather than duplicating it.

Multi-tensor (multi-input / multi-output) is deliberately **not** a rung:
representable in the contract, but no production consumer exists yet
(§17 Q3).

---

## 10. Step-03 vs Step-04 boundary — resolved from source

| Item | Owner | Reason |
|---|---|---|
| normalized tensor contract, axis roles, dtype declaration | **03** | it is the contract |
| output-type alphabet, loss legality derivation | **03** | consumed by config validation, not by execution |
| preset resolution + fail-closed consistency | **03** | it is contract resolution |
| **probe tensor construction**, `_PROBE_NUM_CLASSES`, shape probes | **04** | building a tensor is execution mechanics; 03 supplies the contract it is built from |
| custom-loss "probe recipes" | **04** | same |
| implementor / validator prompt mechanics, generated-plugin templates | **04** | 03 supplies the declaration they render |
| forbidden-pattern enforcement, generated-code execution | **04** | |
| validator **compatibility checks** | **03 declares the rule, 04 executes it** | the rule is contract semantics; running it against generated code is mechanics |

The prior documents routed probes inconsistently. **Resolved: semantic
contract → 03; construction and execution → 04.** No conflicting
ownership statement remains in this parent.

---

## 11. Checkpoint ladder

| Checkpoint | Meaning for Step 03 |
|---|---|
| **0** | A3, A4, A7, A9 baselines captured before any behaviour changes |
| **A** | TIDMAD parity across every owned surface — all four prose restatement sites, the loss matrix, builtin forwards, dtype at the boundary |
| **B** | 3-A/3-B/3-D + **FX-3, FX-4** + 3-E pass atomically; 3-C in 03b |
| **C** | per child, at a REAL production boundary: 03a a live proposer render + a real pre-LLM rejection; 03b a real training/inference round |
| **D** | per child, risk-targeted: targeted → affected package → focused mutation → exact-head CI. **No child is pre-assigned a local full suite** |
| **E** | parent / roadmap §15.1 / §14 convergence / folder README synchronized after the final child merges |

Evidence economy, carried from Step 02: the finalizer (03b) owns **one**
terminal local full unit suite if the assembled blast radius justifies
it; otherwise exact-head CI supplies the broad regression property and
the parent says so explicitly at freeze.

---

## 12. Gates

Read from the **current** `docs/gates/gate_testing_standard.md`, not from
Step-02's shape.

| | PR-03a | PR-03b |
|---|---|---|
| Gate 1 | **LIKELY REQUIRED** — may move LLM-facing prompt bytes | not expected |
| Gate 2 | not expected | **LIKELY REQUIRED** — real training is the only boundary where a wrong dtype/class count manifests |
| Flip condition | if 03a changes no rendered byte, Gate 1 drops to unit-only | if 03b turns out to change no executed tensor, Gate 2 drops |

Unique evidence: Gate 1 proves a real LLM still accepts the re-rendered
contract; Gate 2 proves a contract-derived dtype survives the real
subprocess boundary. Neither substitutes for the other. **No intermediate
tier.** Gates are decided at freeze from the table, and none is run
during design.

---

## 13. Convergence ledger implications

| Row | Disposition |
|---|---|
| ForwardContract / Model I/O contract | Step 03 lands the structured authority. **Shared ownership with §6 candidate creation stays DO-NOT-MERGE** — Step 04 has no completed design yet, so the ≥2-design bar is unmet |
| Dataset Profile ↔ model-facing tensor contract | **Distinct concepts, deliberately not merged.** Dataset Profile says *what data exists and how it is encoded*; the model contract says *what tensor interface a model consumes*. 3-E cross-validates them; neither derives the other wholesale |
| num_classes / cardinality | ONE authority after 03: dataset declares the data fact, the model contract derives/cross-validates. Removes today's two-producer split |
| output_type | collapses from three surfaces to one |
| loss-family authority | already single; Step 03 re-keys, does not merge it with anything |
| semantic presets | authoring convenience only. **Never a convergence candidate** — a preset with runtime semantics is the failure mode, not the goal |
| estimator ×256 terms (§7d) | remains Step-07d's; it will DERIVE from this contract |

---

## 14. Cross-step routing

| Finding | Owner | Why not Step 03 | Blocking? |
|---|---|---|---|
| custom-loss zero-arg instantiation (`loss_models_sandbox:253-276`) | **Step 04** | execution mechanics; revisit only if 03b proves the contract is what is missing | NO |
| `_PROBE_NUM_CLASSES`, probe construction | Step 04 | §10 | NO |
| second builtin name→config map (`models_format_sandbox:338-345`) | **Step 03, opportunistic** | it is a duplicate catalogue inside 03's own surface — fold into 03b if cheap, else route to Step 04 | NO |
| registry population as an import side effect with bare `except` (`models_sandbox:749-755`) | **UNKNOWN — operator question §17 Q5** | plausibly Step 11 execution infrastructure | NO |
| class-weight histogram fixed 256 bins (`train_engine:80,126,196`) | **Step 03 (03b)** | it is a cardinality derivation on the training path | NO |
| dtype-registry "float" arm with zero implementations | Step 04 | dead until a generated float model exists | NO |
| estimator ×256 | Step 07d | | NO |
| metric identity | Step 06 | | NO |

No item is left "owner TBD" except Q5, which is a genuine operator
question rather than an unaudited gap.

---

## 15. Adversarial genericity review

| # | Attack | Verdict |
|---|---|---|
| 1 | Did we convert `[B,256,T]` prose into structured hardcodes? | **Guarded** — the contract declares axis ROLES and symbolic dims; §9's 3-A varies rank with roles preserved, which a structured hardcode cannot survive |
| 2 | Can it represent unfamiliar rank/axes without source edits? | **This is exactly what 3-A tests.** If it cannot, the abstraction is wrong |
| 3 | Are presets convenience only? | **Enforced** — one normalized contract is the only runtime representation; FX-4 rejects preset/explicit conflict; a preset producing a second path is a STOP |
| 4 | Does any code branch on modality / rank / preset name? | **STOP condition in both children** |
| 5 | Is dataset cardinality duplicated? | **NO** — derived/cross-validated; 3-E proves it |
| 6 | Can contract and Dataset Profile contradict and still reach the LLM? | **FX-4 + 3-E exist precisely to make this impossible**; Checkpoint C requires a real pre-LLM rejection |
| 7 | Can contract and preset contradict silently? | **FX-4** |
| 8 | Any generic schema with no production consumer? | **Multi-tensor is the live risk** — representable but consumer-less; escalated as Q3 rather than quietly shipped |
| 9 | Did we freeze implementation syntax? | Field names, YAML nesting and helper decomposition are **deliberately not specified here** |
| 10 | Does loss config duplicate the existing validator authority? | **NO** — §8.1 forbids it; the authority is re-keyed |
| 11 | Is output_type still split? | It **is** today (audit #4); collapsing it is 03a's job |
| 12 | Was `hybrid` invented from the roadmap? | **No — it exists**, but is unreachable for plugins. Its fate is Q2, not an assumption |
| 13 | Did custom-loss semantics absorb Step-04 mechanics? | **NO** — §14 routes them out |
| 14 | Over-split? | **Two children**, with three candidate splits explicitly rejected in §6 |
| 15 | Could one broader PR own both? | **Considered and rejected**: PR-A moves prompt bytes and PR-B moves executed tensors — different Gates, different oracles, different failure classes. One PR would need both Gates for a diff whose halves are independently reviewable |
| 16 | Does each child have a real failure class and merge value? | **YES** (§7); 03b's is the silent-dtype class that no prompt test can see |
| 17 | Are Stage-B contrasts atomic? | One axis per rung by construction (§9) |
| 18 | Does Checkpoint C prove production consumption? | **Yes by definition** — a live proposer render + a real pre-LLM rejection; a real training round. Serialization or rendering alone is explicitly insufficient |
| 19 | Are TIDMAD behaviours being upgraded into universal contracts? | **Watch item** — the frozensets name implementations that exist HERE; §8.5 defers making loss families task-owned for exactly this reason |
| 20 | Any field configurable only because a literal existed? | `task_type` is the suspect — Q4 asks whether it is a real semantic or prompt framing Step 01 owns |

---

## 16. Stop conditions

- a preset acquires runtime semantics, or any consumer branches on rank,
  modality or preset name;
- dataset cardinality/encoding is redeclared instead of derived or
  cross-validated;
- a second loss or output-type authority appears;
- a contradiction between contract, preset, description or Dataset
  Profile can still reach an LLM-facing consumer or executable workflow;
- any builtin forward output changes, or FocalLoss1D math is touched;
- prior on-disk generated plugins stop loading without a declared,
  accepted workspace boundary;
- a declared field lands without a production consumer;
- Step-04 probe/execution mechanics are absorbed;
- the child count grows beyond two without a source-grounded capability
  argument.

---

## 17. Remaining operator decisions

| # | Question | Why it needs a decision | Recommendation |
|---|---|---|---|
| **Q1** | **Two children, or one?** | The §6 seam is clean (prompt bytes vs executed tensors) but a single PR is defensible if you prefer one review | **TWO** — they need different Gates |
| **Q2** | **What happens to `hybrid`?** | One builtin implementation, unreachable for generated plugins, accepted by `plugin_loader` and by the loss authority. Preserve as a builtin-only legacy value, or normalize it away? | Preserve as legacy-only in 03a; do not extend it to plugins |
| **Q3** | **Should multi-tensor I/O be representable in this Step?** | Genuinely generic, but **no production consumer exists** — shipping it now would be the consumer-less seam §0 rule 8 forbids | Represent single-tensor now; design the schema so multi-tensor is a later addition, not a rewrite |
| **Q4** | **Is `task_type` a Step-03 semantic at all?** | Free-form `str`, consumed only for prompt framing. Step 01 may own it | Likely Step-01 prose; confirm at freeze |
| **Q5** | **Who owns the import-side-effect registry with a bare `except`?** | Source does not decide between Step 03 and Step 11 | Operator call |
| **Q6** | **Is the A1 prompt-byte exception acceptable again?** | If 03a re-renders the contract, TIDMAD prompt bytes may move, as they did for 01b under OD-S1-8 | Pre-authorize the same declared-golden-set mechanism, or require byte-identity |

**Q1-Q6 are genuine.** Everything else in this document was decided from
source.

---

## 18. Status

**STEP 03 DESIGN — READY FOR OPERATOR REVIEW.**

Not frozen. No implementation authorized. No Implementation Working Rules
contract exists for any child. Step 04 is not begun.
