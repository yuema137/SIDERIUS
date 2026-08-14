# Step 04 — Candidate Creation Mechanics (+ the §13 remainder this step owns) — detailed design (parent)

## 0. Status and provenance

| Field | Value |
|---|---|
| Roadmap row | §15.1 "6-M Candidate-creation mechanics (+ §13 remainder)", step 4 |
| Module sections | roadmap §6 (Candidate Creation), §13 (Task Profile & Prompt Assembly) |
| Design base | `e802b810` (master at design time; Step 03 merged as `e1181f61`, PR #205) |
| Depends on | Step 01 (MERGED, PR #199/#201), Step 02 (MERGED, PR #202/#203/#204), Step 03 (MERGED, PR #205) |
| Decomposition | **TWO PRs** — `04a` then `04b` (independent; see §8) |
| Status | **Step 04 = IN PROGRESS.** Child **04a = COMPLETE — MERGED** (PR #207, squash `6458dd95`, final head `d019f94b`; child §17.11). Child **04b = DESIGN FROZEN** (revision 2, frozen at `4282112a`, 2026-08-14) — **implementation NOT authorized, NOT started**. **Step 04 must NOT be marked COMPLETE until 04b merges** (§20). |
| Freeze posture | This parent stays a **LIVE governance document**, deliberately not frozen, following the Step-02 multi-PR precedent: it must still absorb 04b's design and both children's status. The frozen contracts live in the children |

This parent owns Step-level scope, the authority map, the decomposition
decision and the completion contract. Each child owns its own PR's
implementation-ready design and, later, its live ledger.

---

## 1. Final observable Step effect

> A task declares its model I/O contract once (Step 03) and its task
> description once (the **§13 task-profile authority**). The
> **implementor** and the **validator** then generate and validate
> candidate plugins whose probe tensors, self-checks, generated
> artifacts and rendered prompts all DERIVE from those declarations.
> A declared-regressor candidate with a custom loss can be generated
> and can pass validation, which today it cannot.

**The precise invariant** (it is not "no literals"):

> No task-semantic **class-count**, **tensor-shape** or **dtype** fact
> is independently restated inside candidate creation. Every such fact
> resolves from the declaring authority.

Step-04-owned **probe recipe constants may remain** where they are
genuinely validation convenience and satisfy the declared contract —
`T = 64` in the validator probe and `100` in the loss probe are recipe
values, not task semantics (§10). Eliminating them by pushing probe
sizes into task config is explicitly **wrong**, not an improvement.

Under TIDMAD every rendered prompt, every generated artifact and every
validator verdict is unchanged, with **one deliberate exception**
(§12, OD-S4-1: the stale implementor capacity literal).

### 1.1 What Step 04 explicitly does NOT claim

- It does **not** redefine the Model-I/O contract — Step 03 owns it (§3).
- It does **not** own planner/reflector prompt content (Step 07a), the
  interpretation grammar (Step 09), or metric identity (Step 06), even
  though those prompts are part of the historical §13 inventory (§6).
- It does **not** make `hybrid` a generic plugin-authoring value (§11).
- It does **not** claim loop-wide task-literal elimination.

---

## 2. Current source census (audited at `e802b810`)

Every row below was read at the cited line, not inferred from the
roadmap. The roadmap's §6.1 inventory is a starting point; the
"Disposition" column is this design's verdict.

### 2.1 Contract transport — the defining gap

| Surface | Current state | Disposition |
|---|---|---|
| `agent/schemas/validator.py:45` `ValidatorInput` | carries `model_file_path`, `config_fields`, `model_description`… and **no contract of any kind** | **STEP-04 OWNED — LIVE.** New typed transport required |
| `agent/schemas/implementor.py:219` `ImplementorInput.forward_contract` | carries `ForwardContract` — the **prose** contract from `configs/task_config.yaml`, used for prompt rendering only | **STEP-04 OWNED — LIVE.** Must additionally reach the normalized contract |
| `nodes/ml_code_validator_agent/ml_code_validator_agent.py:326-332` | source comment states FU-A-1 verbatim: *"This agent holds no task config and its caller passes only a file path, so threading it here would mean a NEW transport… the literal is retained and the genericization deferred"* | **STEP-04 OWNED — LIVE.** This is the deferral Step 04 exists to close |

`ForwardContract` (`agent/schemas/task_config.py:33`) is a **prose**
model: `input_shape: str = "[B, T] int64"`, `output_shape: str`,
`num_classes: int`, `task_type: str` (free-form). `ModelIOContract`
(`agent/schemas/model_io_contract.py:220`) is the **normalized
semantic** model: `TensorContract` of `TensorAxis`/`AxisRole`/
`Dimension`, with `output_semantic`, `legacy_output_type` and
`class_cardinality` derived properties. They are two representations of
one concept — this is the open convergence row (§14).

### 2.2 Probe and self-check literals

| Surface | Current state | Disposition |
|---|---|---|
| `ml_code_validator_agent.py:333` `_PROBE_NUM_CLASSES: int = 256` | module constant | **DERIVE** from `ModelIOContract.class_cardinality` |
| `ml_code_validator_agent.py:431-432` `(1, _PROBE_NUM_CLASSES, 64)` / `(1, 64)` | expected-shape tuple; branches on `declared_type` (already name-blind — Stage-A precedent) | **DERIVE** rank/axes from `TensorContract`; `64` is a probe recipe (§10) |
| `ml_code_validator_agent.py:437` `torch.randint(0, _PROBE_NUM_CLASSES, (1, 64))` | probe input | **DERIVE** value range from cardinality, dtype from the Step-03 dtype requirement |
| `ml_model_implementor.py:120,129` | `torch.randint(0, 256, (1, T))`; `expected = (1, 256, T) if declared == "classifier" else (1, T)` | **DERIVE** — same rule, implementor side |
| `ml_model_implementor.py:118-131` (`_smoke_test_plugin`, :82) | in-process self-check: `T = 64`, `randint(0, 256, (1, T))`, `expected = (1, 256, T) if declared == "classifier" else (1, T)`; already reads the plugin's declared `PLUGIN_OUTPUT_TYPE` | **DERIVE** the `256`; `T = 64` stays a recipe (§10) |

### 2.3 Generated artifacts

| Surface | Current state | Disposition |
|---|---|---|
| `ml_model_implementor.py:281-282` `_OUTPUT_CONTRACT_COMMENTS` | `"input [B, T] int64 → output [B, 256, T] float32"`, `"[B, 256, T] → 256-class classification"` — written into **every generated plugin** | **DERIVE** from `TensorContract.render_shape()` |
| `TEST_TEMPLATE` (`:309`), body at `:323`, `:328-331`, `:340` | a `.format(model_name=…)` template; the generated test hardcodes `randint(0, 256, …)` and `(2, 256, config.segmentation_size)`. `T` already derives from `config.segmentation_size`; only the class count is hardcoded | **DERIVE** the class count via a new render-time placeholder. **Correction**: an earlier revision described `:323/:329/:340` as a separate "baseline self-check" — they are the generated **test body** inside `TEST_TEMPLATE`. Existing oracle `tests/unit/agent/test_output_contract_end_to_end.py::test_generated_test_file_matches_the_declared_contract` is already parameterized by `output_type` |
| **generated candidate description artifact** (`ml_model_implementor.py:1776-1796`, written to `agent_generated/models/{model_name}/description.md`) | `:1783` already guards a regressor claiming `[B, 256, T]` | **KEEP** — existing generic behaviour, becomes a Stage-A precedent. **04a surface** |

### 2.3.1 The two description surfaces are distinct — verified

"Generated description artifact" (04a) and "model-description task
seams" (04b) are **different files, produced by different code, from
different sources**:

| | **04a** — generated candidate description artifact | **04b** — static builtin model-description task content |
|---|---|---|
| Path | `agent_generated/models/{model_name}/description.md` | `ml_models/{model_type}/description.md` |
| Producer | written at runtime by `ml_model_implementor.py:1776-1796` | checked-in static content, authored by hand |
| Count | one per generated candidate | **6** files (`wavenet`, `punet`, `rnn`, `transformer`, `fcnet`, `gated_fno`) |
| Carries task prose? | derived from the candidate's own spec | **2 of 6** contain SQUID/axion task prose: `punet`, `gated_fno` |
| Step-04 concern | the generated artifact must not restate contract facts | the static task prose must come from the task profile |

`ml_models/model_descriptions.py` is the **loader** for both and is
**owned by neither PR** — no PR changes it.

**Independence therefore holds**: 04b does **not** modify the
implementor-generated description path that 04a owns. The two-PR split
survives this clarification on evidence, not on wording.

### 2.4 Custom-loss probe — the genuine capability gap

`ml_model_implementor.py:785-870` `_dummy_tensor_validate_loss`
constructs, unconditionally:

```text
inputs  = torch.randn(2, 256, 100, requires_grad=True)     # :859
targets = torch.randint(0, 256, (2, 100), dtype=torch.int64)  # :860
```

A declared-**regressor** custom loss expects `inputs [B, T] float` and
`targets [B, T]`; it cannot pass this probe under any circumstance.
**STEP-04 OWNED — LIVE**, and it is a capability gap, not a literal
sweep (§9).

### 2.5 Prompt surfaces this step owns

| Surface | Current state | Disposition |
|---|---|---|
| `ml_code_validator_agent.py:73` | validator LLM prompt: `PLUGIN_OUTPUT_TYPE: "classifier" must emit [B, 256, T]` | **DERIVE** — rendered from the contract |
| `ml_model_implementor.py:85` docstring, `:447` config-fields example | `[1, 64] int64 → expected [1, 256, 64]`; `le=256` in an unrelated field example | `:85` **DERIVE**; `:447` is an illustrative Pydantic bound, **NOT a contract literal — KEEP** |
| `ml_model_implementor.py:363` | `- GPU budget: <10 GB VRAM, <100M parameters for initial exploration.` | **DERIVE from the live `[HARDWARE CONTEXT]` block** — the last open half of roadmap §6.3. This is the one deliberate byte change (§12) |
| loss-generation prompt path | zero `task_config` reads today | **STEP-04 OWNED — LIVE** |

### 2.6 Already closed — do NOT redo

| Historical roadmap item | Closed by | Evidence |
|---|---|---|
| Proposer prompt task facts + contract prose | **Step 01** (PR #199/#201) | `pb3_*`/`pb4_*` goldens; roadmap §6.1 "PROPOSER half CLOSED" |
| Proposer capacity literals (`~100M`, `10 GB VRAM`) | **Step 01** (S1-E `5dee6c4a`) | `test_prompt_ceiling_policy.py::_numeric_capacity_literals` — the detector is **directly reusable** for the implementor literal |
| Sample-shape legality / dataset facts | **Step 02** (PR #202/#204) | resolved Dataset Profile crosses the subprocess boundary |
| Normalized contract, dtype admissibility, cardinality, output semantics, loss re-keying | **Step 03** (PR #205) | `agent/schemas/model_io_contract.py`; Step-03 §10 boundary table |
| `declared output_type` flowing end-to-end, name-blind compat, fail-closed `get_output_type` | pre-existing | preserve as Stage-A precedents (roadmap §6.1) |
| `agent/prompts.py:1037` `[B, 256, T]` | **Step 07a** — NOT Step 04 | Step-03 §24.2 F-4 routes it explicitly |

### 2.7 §13 remainder — what Step 04 actually owns

Of the fifteen hardcoded prose families in roadmap §13.1, Step 04 owns
**four**. The rest are already closed or belong to later steps:

| Family | Owner |
|---|---|
| implementor prompts (incl. loss generation) | **04a** |
| validator prompt + probe literal | **04a** |
| duplicate byte-equal task description in `lit_review_config.yaml` | **04b** |
| static builtin model-description task content (`ml_models/{model_type}/description.md`) | **DEFERRED / RECORD** — was assigned to 04b; 04b's revision-2 source audit found **no live task-block consumer**, so migrating it now would create a consumer-less seam (§20.4) |
| PROPOSAL_COMMIT_PROMPT, personas, proposer family | CLOSED — Step 01 |
| planner roster / collapse advice / data-volume anchors / CH1-CH2, `REFLECTOR_PROMPT` | **Step 07a** |
| interpretation prediction grammar | **Step 09** |
| SQUID worked examples in lit-review *formats*, full-spectrum doctrine | **04b** only where they are task **content**; format doctrine stays module-owned |

**This is a substantial shrink of the historical §13 remainder** and is
the D9 finding: Step 04 must not inherit planner/reflector/metric prose
merely because §13 catalogued it.

---

## 3. Authority map

Genericization is **authority assignment**, not configuration expansion.

| Concept | Authority | Step-04 role |
|---|---|---|
| class cardinality | `ModelIOContract.class_cardinality` (**Step 03**) | DERIVE |
| tensor rank / axis roles / symbolic dims | `TensorContract` (**Step 03**) | DERIVE |
| model-boundary dtype requirement | Step-03 Amendment A-1 | DERIVE |
| canonical output semantic | `ModelIOContract.output_semantic` (**Step 03**) | DERIVE |
| loss legality per output semantic | the singular Step-03 loss authority | DERIVE — **never a second LossContract** |
| dataset sample-shape legality | Dataset Profile (**Step 02**) | DERIVE |
| task description / task-profile content | the **§13 task-profile authority** (NOT Step 02 — Step 02 owns Dataset Profile semantics). Step 01 migrated the proposer-side consumer and is an inherited consumer precedent, not the authority | DERIVE (04b collapses the duplicate) |
| runtime capacity (VRAM, params) | live `[HARDWARE CONTEXT]` block | DERIVE — **no new config field** |
| **probe tensor construction / recipes** | **Step 04** | **DECLARE** |
| **custom-loss probe recipe per output semantic** | **Step 04** | **DECLARE** |
| **generated-artifact templates** | **Step 04** | **DECLARE** |
| **forbidden-pattern enforcement, generated-code execution** | **Step 04** | **DECLARE** |
| batch size `2`, probe length `64`/`100` | Step 04 (probe convenience) | **DECLARE as recipe, NOT task config** (§10) |

This table is the direct application of the Step-03 §10 boundary:
*semantic contract → 03; construction and execution → 04.*

---

## 4. Approved scope

1. A typed transport carrying the normalized `ModelIOContract` into the
   implementor and the validator.
2. Probe construction and self-checks derived from that contract.
3. Generated plugin/test/description artifacts derived from it.
4. A custom-loss probe recipe keyed by output semantic, so a declared
   regressor can pass.
5. Implementor/validator prompt contract blocks rendered from it.
6. The implementor capacity literal derived from the live hardware block.
7. Task description collapsed to one source; static builtin
   model-description task content sourced from the task profile.

## 5. Explicit non-goals

- No new Model-I/O semantics, no second contract, no `LossContract`.
- No change to frozen loss math or the frozen TIDMAD score formula.
- No mega prompt config — blocks land with their consuming template.
- No new task-config field for VRAM/parameter capacity.
- No planner/reflector/interpretation/metric prompt work.
- No generic `hybrid` authoring path.
- No repository-wide literal sweep.

---

## 6. Inherited semantics (consume, do not re-derive)

- **Step 01**: proposer prompts render from the profile; the
  `_numeric_capacity_literals` concept detector exists and is reusable.
- **Step 02**: the resolved Dataset Profile is the sample-shape legality
  authority and already crosses the subprocess boundary.
- **Step 03**: one normalized Model-I/O authority; `output_type` is a
  **projection**, not a second authority; loss legality is re-keyed, not
  duplicated; `hybrid` is legacy-builtin compatibility only.

**Residue-scoping rule inherited from Step 01 (§13.4).** The shipped
`task_description` itself contains `[B, T]` and `[B, 256, T]`, and since
PR 01b it renders into three stage SYSTEM prompts. Any Step-04 residue
assertion **must be scoped to the block under test**. A whole-prompt
"no `[B, 256, T]` anywhere" assertion is unsatisfiable and is a
test-design error, not a production defect.

---

## 7. PR decomposition — **TWO PRs**

**Decision: `04a` and `04b`. Not one; not three.**

### 7.1 Why not ONE PR (the Step-03 shape)

Step 03 stayed one PR because Phase A and Phase B were internal
milestones with no independently mergeable capability between them.
That is **not** true here: `04b` touches a different node (lit review),
a different config file (`configs/lit_review_config.yaml`), and shares
**zero** code and zero schema with `04a`. Merging them would bundle two
unrelated rollback surfaces behind one review.

### 7.2 Why not THREE+ PRs (splitting `04a`)

The tempting split is *validator probes* vs *implementor generation*.
It fails criterion 5 (own atomic contrast) and criterion 3 (coherent
repository behaviour):

- The implementor **generates** the artifact the validator **validates**.
  They are one pipeline.
- Under a contrast task declaring `num_classes=16`, a validator that
  derives its probe while the implementor still emits `256` into
  `_OUTPUT_CONTRACT_COMMENTS` and its self-check would **reject every
  generated candidate**. The intermediate state is incoherent for any
  non-TIDMAD task — it is TIDMAD-green only by coincidence.
- The 6.5-A/C rungs are therefore only meaningful **end-to-end**. A
  validator-only rung could be tested solely against a hand-written
  fixture plugin, never against generated output — a strictly weaker
  rung, which §11 forbids.
- The transport (§2.1) is a single seam consumed by both nodes.
  Landing it for one consumer only is exactly the consumer-less seam
  D6/§8 criterion 8 prohibits.

Splitting the custom-loss capability out separately fails criterion 1:
it depends on the same transport and the same probe-recipe machinery,
and alone it delivers no capability a user can observe.

### 7.3 The two children

| PR | Capability | Depends on |
|---|---|---|
| **04a** `pr_04a_contract_derived_candidate_mechanics.md` | Candidate creation and validation derive every model-contract fact from the normalized Step-03 contract; a declared-regressor custom loss can pass | Steps 01/02/03 |
| **04b** `pr_04b_task_description_single_source.md` | **ONE canonical runtime declaration** of `task_description` (the §13 task profile), consumed by the **production lit-review node** instead of a byte-duplicated copy in `lit_review_config.yaml`. The static builtin model-description task prose is **NOT** part of 04b (§20.4) | §13 task-profile authority |

**Order**: independent — neither requires the other. Recommended
sequence **04a → 04b**, because 04a carries the convergence-ledger
evidence (§14) and is the higher-risk surface; 04b is a small, cheap
closer. The operator may reverse or parallelize without redesign.

### 7.4 Criterion check

| Criterion | 04a | 04b |
|---|---|---|
| 1. independently useful capability | yes — candidates derive from the contract | yes — one file to edit one task |
| 2. real first consumer | production implementor + validator | production lit-review node |
| 3. coherent repository after merge | yes | yes |
| 4. own TIDMAD parity surface | `pb5_*` (13) + `pb6_*` (3) goldens, generated-plugin bytes, validator verdicts, prior-plugin loadability | `pb9_*` (10) goldens |
| 5. own atomic contrast | 6.5-A / 6.5-C / 6.5-D (**6.5-B removed** — §10.1) | 13.4-A (task-description axis) |
| 6. own live Checkpoint C | yes (§13) | yes (§13) |
| 7. independent review/rollback | yes | yes |
| 8. no consumer-less seam | transport consumed within 04a | no new seam |

---

## 8. TIDMAD compatibility surfaces

| Surface | Criterion | Owner |
|---|---|---|
| implementor rendered prompts | EXACT byte equality, `pb5_*` (13 goldens) — **except** the §12 capacity block | 04a |
| validator rendered prompts | EXACT byte equality, `pb6_*` (3 goldens) | 04a |
| same kwargs reach `LLMBridge` | unchanged (§2 nondeterministic-surface rule) | 04a |
| generated plugin file | byte-identical for a fixed TIDMAD spec | 04a |
| validator verdicts | identical on existing fixture plugins | 04a |
| prior on-disk generated plugins | remain loadable, or a workspace boundary is declared | 04a |
| lit-review rendered prompts | EXACT byte equality, `pb9_*` (10 goldens) | 04b |

**Generated-plugin byte equality is retained as a real criterion** (D17):
the generated file is assembled from in-repo templates plus LLM output,
so for a *fixed* spec the template contribution is deterministic and a
byte diff is meaningful. It is not an opaque snapshot of LLM behaviour.

---

## 9. Stage-A baseline inventory

| Surface | Classification |
|---|---|
| `pb5_*` implementor goldens (13) | **EXISTING SUFFICIENT ORACLE** |
| `pb6_*` validator goldens (3) | **EXISTING SUFFICIENT ORACLE** |
| `pb9_*` lit-review goldens (10) | **EXISTING SUFFICIENT ORACLE** |
| `test_output_contract_end_to_end.py` (generated test vs declared contract, parameterized by `output_type`) | **EXISTING SUFFICIENT ORACLE** |
| `ml_models/legacy_baseline_configs.json`, builtin forwards | **NOT A STEP-04 COMPATIBILITY SURFACE** (Step 03) |
| generated-plugin byte baseline for a fixed spec | **MISSING — CAPTURE BEFORE PRODUCTION EDIT** (04a) |
| validator verdict baseline on fixture plugins | **MISSING — CAPTURE BEFORE PRODUCTION EDIT** (04a) |
| prior on-disk plugin loadability | **MISSING — CAPTURE BEFORE PRODUCTION EDIT** (04a) |
| `_PROBE_NUM_CLASSES == 256` value pins, template-internal regex pins | **OBSOLETE IMPLEMENTATION PIN — REWRITE** to profile-parameterized form in the PR that changes them |

Step 00 already captured the prompt goldens Step 04 needs. **No new
prompt golden capture is required** — only the three artifact/verdict
baselines above.

---

## 10. Probe recipe vs task semantics (the D11 boundary)

The contract says **what is valid**; Step 04 owns **how a minimal
instance is constructed to test it**.

| Literal | Classification | Verdict |
|---|---|---|
| `256` (class count) | **semantic** | DERIVE from the contract |
| `[B, 256, T]` shape | **semantic** | DERIVE from `TensorContract` |
| input dtype | **semantic** | DERIVE (Step-03 A-1) |
| `T = 64` (validator probe), `100` (loss probe) | **validation convenience** | **Step-04 recipe.** Must satisfy declared legality; must NOT enter task config |
| batch `1` / `2` | **validation convenience** | Step-04 recipe |
| torch minimum sizes | **backend minimum** | recipe constraint |

Do not put probe tensor sizes into task config merely because they vary.

### 10.1 Consequence — rung 6.5-B is REMOVED from the required ladder

The roadmap proposed a *"shape/T only"* rung (`T=64 → T=128`). Resolved
now from source, not left provisional.

`Dimension` (`agent/schemas/model_io_contract.py:94-125`) has exactly
three forms: `fixed`, `symbolic`, `dynamic`. In the TIDMAD contract the
time axis is **symbolic** (`T`), and a symbolic dimension declares
**alignment** — *"two axes carrying the same symbol are the same
extent"* — **not a magnitude**. Cardinality, by contrast, is
`fixed: 256`: a concrete declared extent.

Therefore:

> Changing probe `T` from 64 to 128 varies **no declared task or model
> semantic**. Both values satisfy the identical symbolic constraint
> (input `T` equals output `T`). There is no upstream authority for a
> rung to vary.

**Disposition: 6.5-B is NOT part of the required Step-04 Stage-B
semantic ladder.** Keeping it would have produced exactly the failure
§11.1-style criteria forbid — a rung that passes whether or not the
consumer re-hardcodes its literal.

It **may** be retained by 04a as *probe-recipe robustness /
implementation evidence* (the probe still builds correctly at a second
length), which is useful but is **not** a generic semantic contrast and
must not be reported as one.

The required semantic ladder is therefore **6.5-A, 6.5-C, 6.5-D**.

---

## 11. `hybrid` disposition

Step 03 settled: `hybrid` is **legacy builtin compatibility only** —
never produced by the output-semantic projection, never a generic
plugin-authoring value. Step 04 narrows accordingly: no schema, prompt,
template, validator path or generated artifact may expose `hybrid` as an
authorable option. Existing builtin `fcnet` behaviour is unchanged.

This **closes the open half of deferred decision D2**: the
"extend generation vs retire" question was scoped "decide in §5 **with
§6**". Step 04's answer is **neither extend nor retire** — generation
does not offer it, and the builtin compatibility path stays.

---

## 12. The one deliberate byte change — **OD-S4-1: APPROVED**

`ml_model_implementor.py:363` renders, today:

```text
- GPU budget: <10 GB VRAM, <100M parameters for initial exploration.
```

Deriving it from the live `[HARDWARE CONTEXT]` block — the precedent
roadmap §6.3 mandates and Step 01 already proved end-to-end (a real
gpt-5.5 cited *"Usable VRAM cap is 25.07 GB on the RTX 5090"*) — **will
change LLM-visible bytes** on the implementor prompts.

This is exactly the Step-01 OD-S1-8 A-cell exception shape.

**AUTHORIZED by the operator.** Binding conditions:

- the `pb5_*` golden set may change **only** by deltas that are
  mechanically attributable to this authority correction — any other
  byte movement is a defect, not a golden to update;
- the affected golden files are declared explicitly in 04a before the
  change lands;
- the derived text comes from the live `[HARDWARE CONTEXT]` block, not
  from a new task-config field.

**This is the ONLY intentional LLM-visible golden delta in Step 04.**
Every other rendered surface — the rest of `pb5_*`, all of `pb6_*`, all
of `pb9_*` — must stay byte-exact.

**Note**: this decision does **not** change 04a's Gate 1 requirement.
Gate 1 is required regardless, by the loss-generation row (§14).

---

## 13. Step-level live integration (Checkpoint C)

| PR | Required live evidence |
|---|---|
| **04a** | In a real chain iteration, the production implementor generates a candidate whose contract comments/self-check derive from the resolved contract, and the production validator probes it with a contract-derived tensor — proven from run artifacts, not unit mocks |
| **04b** | **Deterministic production-path integration — no real chain required.** Canonical §13 task config → real `_build_lit_review_input` → real lit-review rendering / recording bridge → captured task-description block, proven with a distinguishable alternate description. Both Gates are NOT REQUIRED for 04b, so a paid iteration would add no evidence a deterministic capture cannot give (04b §7) |

Neither child may use the other's run as its only live proof.

---

## 14. Gate disposition

Quoting the **current** standard (`docs/gates/gate_testing_standard.md`
§"Gate assignment by commit type", read at `e802b810`):

| Commit type | Typical gate |
|---|---|
| Prompt placeholder substitution | Unit only + optional Gate 1 |
| New LLM-facing system prompt | Gate 1 |
| Checkpoint (end of feature) | Gate 2 |
| Loss function generation (L4) | Gate 1 (dummy-tensor) + Gate 2 at Checkpoint L |

| PR | Gate 1 | Gate 2 | Reasoning |
|---|---|---|---|
| **04a** | **REQUIRED — unconditionally** | **REQUIRED** | The "Loss function generation (L4)" row applies on its own, because 04a changes the loss dummy-tensor probe. OD-S4-1 does **not** gate whether Gate 1 runs — it gates only whether a declared `pb5_*` golden set changes alongside it. No flip condition removes Gate 1 |
| **04b** | **NOT REQUIRED** | **NOT REQUIRED** | Pure single-sourcing; `pb9_*` bytes must be identical. Flip: if any rendered lit-review byte changes, Gate 1 becomes REQUIRED |

Gate 2, where required, uses the **current bounded canonical command**
and `llm_configs/openai_tiered_pro.json`. **No Gate runs during design.**

---

## 15. Evidence economy

- Prompt parity is carried by the **existing** Step-00 goldens — do not
  duplicate them.
- Contract-derivation correctness is a **deterministic** property; test
  it deterministically, not through a Gate.
- Gates prove the real chain executes; they do not replace cheap
  failure-semantics tests.
- **No local full suite by default.** Exact-head CI is the broad
  regression authority. The full suite runs once, at the final
  executable head, from a clean tree.

## 16. Test-disposition policy

Touched tests are classified by **functional intent** — KEEP / UPGRADE /
MERGE / REWRITE / DELETE. Never delete a test because it fails.

Specifically expected:
- `_PROBE_NUM_CLASSES == 256` and template-internal regex pins →
  **REWRITE** as profile-parameterized pins on rendered/derived output.
- ABSENCE pins proving the *template* layer carries no task literal →
  **KEEP template-scoped** (retargeting them to rendered output makes
  them vacuous — roadmap §13.3(b)).

---

## 17. Convergence-ledger implications (§14 row: Model I/O contract / ForwardContract)

The ledger threshold is "§5 **and** §6 detailed designs **complete**".

- Step 03 supplies the **§5** completed-design evidence (merged, PR #205).
- This document supplies the **§6** evidence **once operator-frozen /
  approved** — a design awaiting review is not completed-design
  evidence.
- **At that point, and not before, the evidentiary threshold is met.**

Reaching the *design* threshold is not implementation convergence, and
does not authorize one.

Crossing it does **not** authorize a merge of `ForwardContract` and
`ModelIOContract`. The recorded finding is:

- they model the **same concept** at two altitudes — prose for prompt
  rendering, normalized for machine derivation;
- they have **different lifecycles** (one is rendered into text for an
  LLM; the other is consumed by executable derivation);
- 04a will make both reach the same nodes, which is the first time a
  single consumer holds both.

**Recommendation: record, do not implement, during Step 04.** Revisit
when a third consumer needs it. Collapsing them now would either force
prose into the normalized model or force normalization into prompt
rendering — neither has a live benefit today.

---

## 18. Compatibility with prior generated plugins and workspaces

**Operator decision OD-S4-3: PRESERVE LOADABILITY.** No workspace
boundary is declared by default.

Mechanically enumerated at design time (`agent_generated/models/`, this
checkout):

| Measure | Count |
|---|---|
| total on-disk generated plugin `.py` files examined | **89** |
| explicitly declaring `PLUGIN_OUTPUT_TYPE` | **89** |
| lacking `PLUGIN_OUTPUT_TYPE` | **0** |
| relying on the legacy classifier fallback | **0** |
| malformed / unparseable | **0** (all 89 parse) |
| declared `classifier` / `regressor` | **86 / 3** |
| excluded from the count | `__pycache__` (the only non-plugin subdirectory); each plugin's `{name}/description.md` mirror directory |

**Correction to the previous revision.** It stated that many plugins
predate the declaration and rely on
`_DEFAULT_OUTPUT_TYPE = "classifier"`
(`ml_code_validator_agent.py:320-323`). That is **false against the
current corpus**: every plugin declares the field. No legacy-fallback
class exists on disk, and this design must not invent one.

**Reconciliation with Step-03 A8**: A8 recorded **85** plugins, all
loading and registering. The corpus is now **89** — it grew by 4 through
real chain runs since (including the plugin promoted by the Gate-2 run
executed during this session's PHASE V). This is growth of a live,
gitignored artifact directory, not a contradiction; any count is
checkout- and time-specific, which is why 04a's oracle must re-enumerate
at implementation time rather than pin a number from this document.

**Consequence for the 04a compatibility oracle**: the oracle is
"every plugin present at implementation time still loads and registers",
enumerated mechanically then. The `_DEFAULT_OUTPUT_TYPE` fallback is
**retained** — it remains intentionally supported behaviour for a plugin
that omits the declaration — and, because no on-disk plugin exercises
it, it is protected by a **synthetic A3-style fixture**, not by the
corpus.

---

## 19. Stop conditions

- Deriving a probe requires a semantic the Step-03 contract does not
  express **and** the semantic genuinely belongs to the contract →
  STOP; growing Model-I/O is an operator decision.
- Any need for a second loss authority → STOP.
- A `pb5_*` delta appears that is NOT mechanically attributable to the
  OD-S4-1 authority correction → STOP.
- Prior-plugin loadability cannot be preserved and no boundary is
  acceptable → STOP.
- Scope pressure to absorb planner/reflector/metric prose → STOP.
- Any change to frozen loss math or the frozen score formula → STOP.

---

## 20. Completion / Checkpoint-E obligations

Step 04 is COMPLETE when both children are merged and:
Checkpoints 0/A/B/C/D pass for each; required Gates pass at the
assembled head; exact-head CI green; the roadmap §15.1 row and the
`README.md` index are synchronized; the §14 convergence row records the
threshold-met finding; D2's remaining half is recorded closed (§11).

### 20.1 Progress — **Step 04 is IN PROGRESS, not complete**

| Child | State | Evidence |
|---|---|---|
| **04a** | **COMPLETE — MERGED** | PR #207, squash `6458dd95`, final head `d019f94b`; Checkpoints 0/A/B/C/D, Gate 1 PASS, Gate 2 PASS, exact-head CI green — all in the child's §17.11 |
| **04b** | **DESIGN FROZEN — implementation NOT authorized, NOT started** | frozen at `4282112a` (2026-08-14) after the revision-2 re-scope from post-04a master and the pre-freeze acceptance corrections |

**Do not mark Step 04 COMPLETE.** The completion contract above requires
*both* children — and **only** those. The deferred static builtin
model-description task prose (§20.4) is explicitly **not** a completion
criterion. The `04a → 04b` sequencing recommended in §7.3 is preserved:
04a landed first because it carries the higher-risk surface and the §14
convergence evidence.

**04b was re-scoped from post-04a master** (revision 2, frozen `4282112a`),
not resumed from its pre-04a draft. 04a changed the seams 04b would build on
— a new transport field on two schemas, a shared probe-recipe skill, two
prompt templates gaining placeholders, and a shared capacity rule — and the
child's §17.11.2 lists the interfaces and authorities it leaves behind, which
that re-scope consumed. Independence was re-verified against merged 04a
source (04b §0.2).

### 20.2 Step-level obligations still OPEN

| Obligation | State |
|---|---|
| roadmap §15.1 row synchronized | **OPEN** — must read *Step 04 IN PROGRESS; 04a merged, 04b pending* |
| `generic_framework_upgrade/README.md` index | **OPEN** — same one-line mirror |
| §14 convergence row records the threshold-met finding | **OPEN** — 04a supplies the §6 consumer evidence (first single consumer holding both `ForwardContract` and `ModelIOContract`); still **RECORD ONLY**, no merge of the two authorities (OD-S4-4) |
| D2's remaining half recorded closed (§11) | satisfied by §11 — carried to Step-level closeout |

### 20.4 Static builtin model-description task prose — DEFERRED / RECORD

**Scope correction, recorded before 04b freezes.** Earlier revisions of this
parent (§2.7, §7.3) assigned the checked-in
`ml_models/{model_type}/description.md` task prose to 04b. 04b's revision-2
source audit found that assignment cannot be honoured as scoped:

| Finding | Evidence |
|---|---|
| `ml_models/model_descriptions.py` is a **whole-file loader** — it reads the markdown and returns its text | it has no task-block seam |
| **No live consumer** would render task-profile content into that surface | nothing calls for one |
| Creating one in 04b would be a **consumer-less seam** | roadmap §0 rule 8 forbids it |

Two of the six builtin descriptions (`punet`, `gated_fno`) do carry
SQUID/axion task prose. That remains true and remains duplication. It is
**recorded, not fixed**.

**Revisit trigger — the only one:**

> a real production consumer exists that can render task-profile content
> into the builtin model-description surface.

Until then, do not re-assign this to a PR and do not build the seam
speculatively.

**Effect on Step-04 completion: NOT REQUIRED.** §20's completion contract is
*"both children merged"* plus their checkpoint/Gate/CI evidence. This
deferred item is **not** a child, **not** part of 04a (which owns the
implementor-*generated* description artifact — a different file and
producer, §2.3.1), and **not** part of 04b as re-scoped. Step 04 may
therefore complete with this surface still duplicated. Nothing in §20 should
be read as requiring it, and the §2.7 / §7.3 rows above have been corrected
so they no longer imply otherwise.

### 20.3 Carried-forward finding from 04a's Gates (not a Step-04 deliverable)

Gate 1 surfaced a **pre-existing** defect: `--data_dir` is optional
(`_chain_common.sh:92`) while the tuner's pre-phase GPU measurement fails
closed without it, so the Gate standard's canonical Gate-2 command cannot
reach a measured admission. 04a correctly did **not** fix it (out of frozen
scope) and supplied the flag explicitly. Recommended as a small
docs/harness correction **after 04a, before 04b**. Details in the child's
§17.9.6.

---

## 21. Operator decisions — RECORDED

All four decisions are resolved. **Remaining operator questions: NONE.**

| ID | Decision | Disposition |
|---|---|---|
| **OD-S4-1** | Implementor capacity-literal byte change (§12) | **APPROVED.** Derive the stale `<10 GB` / `<100M` prose from the live Hardware Context. The affected `pb5_*` golden set may change **only** by mechanically attributable deltas caused by that authority correction. This is the **only** intentional LLM-visible golden delta in Step 04 |
| **OD-S4-2** | TWO PRs, `04a → 04b` (§7) | **APPROVED.** Independence re-verified twice: at design time via §2.3.1 (04a owns the implementor-*generated* candidate description artifact — different file, different producer), and again against MERGED 04a source in 04b revision 2. **Correction**: the static builtin model-description task content is no longer claimed by 04b — it is DEFERRED (§20.4). The two-PR split does not depend on it |
| **OD-S4-3** | Prior-plugin compatibility (§18) | **APPROVED — PRESERVE LOADABILITY.** No workspace boundary. Corpus re-audited mechanically: 89/89 declare `PLUGIN_OUTPUT_TYPE`, 0 legacy-fallback, 0 malformed. The fallback stays supported and is protected by a synthetic fixture |
| **OD-S4-4** | Convergence disposition (§17) | **APPROVED — RECORD ONLY.** No convergence abstraction is implemented in Step 04 |

Neither the plugin re-audit nor the description-surface clarification
produced a contradiction with these decisions, so none of them is
reopened here.
