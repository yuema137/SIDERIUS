# C12-P-P — Composed Prompt Contamination Closure

**Status: PREP ACTIVE — FINAL IMPLEMENTATION BLOCKED ON C12-P CORE AUTHORITY.**
Branch `c12pp-prompt-contamination`. Not pushed, not merged, no Gate launched,
**zero production files touched**.

> **§§0–8 below were written against master `c991d6f6`, BEFORE PR-12d landed.**
> PR-12d has since landed as `84d74280` and C12-P has closed B3. **§Z is the
> current authority** and supersedes §4.3's wiring sketch and §5's overlap map
> wherever they differ. Read §Z first.

---

## §0 — The one-paragraph result

A foreign composed task's proposing prompt **does** receive TIDMAD-specific
scientific constraints, and this is now proven at the byte level rather than
asserted. But the premise needs one correction that changes the whole fix:
**the contaminating block is TRUTHFUL.** The rule it states is enforced,
unconditionally and for every task, by a Pydantic validator that a foreign
proposal really does hit. The prompt text and the validator are a *matched
pair* reading the same module-scope `TIDMAD` constant. Deleting the prompt
half alone would convert a stated constraint into a hidden one and make the
foreign regime strictly worse. That is why this phase ships evidence and a
design, and deliberately implements neither half.

---

## §1 — Census

Scope discipline: this table lists only sites where **genuinely TIDMAD-only
task science** can reach a **composed** run's LLM-facing prompt. Class (b)
items — generic framework guidance that merely mentions a number or a config
field name — are summarised in §1.3 and are explicitly **not** proposed for
change. Over-reporting would make this unit unbounded.

### §1.1 Proposer path — the unit's own surface (all files DISJOINT from PR-12d)

| # | file:line | contaminating text (verbatim, abridged) | placeholder | call path | gated today? | class |
|---|---|---|---|---|---|---|
| **P1** | renderer `agent/prompts.py:720-757`; bound at `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:51` (`from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG`) and `:1653` | `## SYSTEM-ENFORCED DATASET CONSTRAINTS … segmentation_size — must EXACTLY divide psd_segment_length (10,000,000). Valid values: [100, 125, … 100000]. Powers of 2 such as 16384, 8192, 4096 are INVALID … (16000 is the nearest valid neighbor of 16384).` | `{known_constraints_block}` → `agent/prompt_templates/proposal/proposing_stage.md:108` | `run()` → `_run_pipeline()` (`:1520`) → `template_vars` (`:1653`) → `load_stage_prompt("proposing_stage", …)` (`:1738`) → proposing **SYSTEM** prompt | **UNGATED.** The renderer's only guard is `if dataset_config is None: return ""` (`agent/prompts.py:740-741`); the call site passes the module singleton unconditionally. It reads no `proposal_blocks`, no composition, no run `DatasetProfile`. | **(a)** |
| **P2** | `agent/schemas/proposal.py:28`, `:1232-1266` | `baseline_config['model_config']['segmentation_size'] ({seg}) must exactly divide psd_segment_length ({psd}). Remainder: … Valid segmentation_size values: {valid}.` | not a placeholder — raised as a `ValidationError`, appended to `accumulated["proposing_stage_errors"]` (`ml_model_proposal_agent.py:2154-2159`) and re-rendered into the **retry USER prompt** | proposing loop `:2046-2159` | **UNGATED**, same module-scope constant. Fires only when the model emits `segmentation_size` — which **P1 instructs it to do**. | **(a)** |
| **P3** | `agent/prompt_templates/proposal/proposing_stage.md:41` | `classifier -> [B, 256, T] with ce/focal/focal_cw; regressor -> [B, T] with smooth_l1.` | none — **hardcoded template bytes** | `load_stage_prompt("proposing_stage", …)` | **UNGATED, and unreachable by any declared channel** — there is no placeholder, so PR-12a's `proposal_blocks` cannot suppress it. PR-12a's `render_classifier_output_shape` fixed only the *legacy* `PROPOSAL_COMMIT_PROMPT`. | **(a)** |
| **P4** | `agent/prompt_templates/proposal/proposing_stage.md:70` | `` \| `"classifier"` \| `[B, 256, T]` float \| `` | shape column hardcoded; only the loss cells are substituted | same as P3 | **UNGATED.** Acknowledged in-source at `ml_model_proposal_agent.py:1636-1641`. | **(a)** |
| **P5** | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:685-697` | `if scope.is_full(_TIDMAD.num_files)` … `[DATA SCOPE] This run is restricted to validation files {resolved} …` | `data_scope_block`, prepended to **every** stage user prompt (`:1604`, `:1768`) | `_render_data_scope_block(inp.data_scope)` | Gated only on `scope is None or scope.is_full(_TIDMAD.num_files)`. The partition count **20 is TIDMAD's**, not the run's `DatasetProfile.partition_count`. | **(a)** |
| **P6** | `agent/prompt_templates/proposal/comparison_stage.md:50-52, 63, 74-75, 93` | `"best_score": 5.57` · `"Scores 8.2 on files 15-19 (highest freq)"` · `"near-zero on files 0-4 (low freq)"` | hardcoded JSON examples | `load_stage_prompt("comparison_stage", …)` | **UNGATED** | **(a)** — real TIDMAD scores and its 20-file frequency-band partition, false for a 37-class or a video task |
| **P7** | `comparison_stage.md:118-120` | `propose a Wasserstein-distance loss on ADC bins, use \`emd_ordinal_loss\`` | hardcoded (Rule 5) | as P6 | **UNGATED** | **(a)** — "ADC bins" is digitizer semantics |
| **P8** | `causal_reasoning_stage.md:116` | `"contribution_evidence": "Core mechanism of wavenet's 5.57 SOTA score."` | hardcoded | `load_stage_prompt("causal_reasoning_stage", …)` | **UNGATED** | **(a)** |

**Implementor / validator**: `nodes/ml_model_implementor/ml_model_implementor.py:678-701` and `:640-669` assert the TIDMAD forward contract as universal in the **loss-authoring** prompt (`targets : [B, T] (int64, class indices)`, `PLUGIN_LOSS_TARGET_DTYPE = "long"`), UNGATED — while `_dummy_tensor_validate_loss` at `:897-915` *does* branch on the declared `model_io_contract`. **The prompt and its own validator disagree.** The parallel model-plugin sites (`ml_model_implementor.py:330-339`, `ml_code_validator_agent.py:131-134`, `:389-390`) are **correctly GATED** on `model_io_contract is not None`, which a composed run always supplies (`task_config` is a required manifest section, `workflows/task_composition.py:114-116`). Recorded; not this unit's surface.

### §1.2 Planner path — confirmed, but OVERLAPPING PR-12d (see §5)

Independently re-confirmed at landed master; this is PR-12d's own declared
debt row **A2/A3** (`pr_12d_contrast_subprocess_closure.md` §D-12d-52), quoted
verbatim there as *"a real C-P56-1 hole, but LLM-FACING … DEBT — declared, not
fixed"*.

| # | file:line | text | path | gated? |
|---|---|---|---|---|
| **T1** | `agent/skills/check_config_format_skill/wrapper.py:23` | `- 'punet' and 'transformer' are CLASSIFIERS (256 classes) and MUST use 'ce' or 'focal'.` | `ml_hyperparameter_tune_agent.py:1102` → `config_manual_data` → `planning.py:154` → `llm_bridge.py:1060-1061` `[STRICT PHYSICAL CONSTRAINTS / CONFIG MANUAL]` | **UNGATED** — called unconditionally, raises if it fails |
| **T2** | `.../wrapper.py:27` | `3. Transformer: Default segmentation_size is 20000 to avoid OOM.` | same | **UNGATED** |
| **T3** | `.../wrapper.py:12-18` | the five built-in TIDMAD config JSON schemas, whose field descriptions include `"Latent space dimension for ADC values"` | same (`data["schemas"]`) | **UNGATED** |
| **T4** | `agent/prompts.py:613-617` (`RESOURCE_GATE_GUIDANCE_BLOCK`) | `do NOT change segmentation_size to fit either budget. It is pinned by frequency-resolution physics (must divide PSD_SEGMENT_LENGTH; the valid divisor list is in your expert advice).` | spliced into the planner **USER** prompt at `agent/prompts.py:1321-1323` | Gated on `active_budgets_block` being non-empty — **a budget condition, never a task condition** |

`_format_known_constraints_block` **never reaches a planner prompt**; its only
production caller is the proposer (`:1653`). Verified independently twice.

### §1.3 Deliberately classified (b) — reported, not proposed for change

`"loss_config": {"loss_type": "focal", "alpha": 0.5, …}` in
`proposing_stage.md:55` is the framework's shipped `LossConfig` field
defaults rendered as a JSON skeleton — it asserts no fact about the data
(it is *also* TIDMAD's paper value, which is why the operator brief named it;
recorded, and the call is (b)). Likewise `segmentation_size` as a **field
name** in workload-reduction advice, `T=16000` as an illustrative allocation
magnitude, the `40000` stale fallback default, and `"Reduce batch_size or
segmentation_size."` — all name a knob, none carry physics. The honest
boundary: **(a) requires a claim that is FALSE for a foreign task**; naming a
framework field that every task has is not that.

---

## §2 — Byte-exact baselines

**Location**: `tests/fixtures/c12pp_prompt_baselines/` — 12 files, 2 regimes ×
3 stages × {system, user}.

**Harness**: `tests/helpers/c12pp_prompt_capture.py`.

**Reproduce**:

```bash
cd /home/yuema137/siderius-c12pp-prompts
OPENAI_API_KEY=sk-c12pp-dummy-not-a-real-key \
PYTHONPATH=/home/yuema137/siderius-c12pp-prompts \
/home/yuema137/SIDERIUS/.venv/bin/python -m tests.helpers.c12pp_prompt_capture
```

`OPENAI_API_KEY` must be non-empty because the OpenAI **client object** is
constructed eagerly; no request is issued, because both `LLMBridge.generate`
and `generate_text` are patched. Zero LLM calls, zero network, zero GPU, ~2 s.

**The rendering path is production, not invented.** It reuses the technique of
the landed `scripts/render_proposer_prompts_for_audit.py` (Checkpoint P): a
real `ProposalInput` built through the production protocol `local_full_context`,
driven through `MLModelProposalAgent.run` → `_run_pipeline`, with the bridge
patched only at the two generate methods. Every prompt byte is assembled by
production code. This matters — `scripts/step12_pr12a_gate1.py:213` calls
`_build_reasoning_system_prompt`, which is a real assembler but on the
**legacy** branch that a production chain never takes.

**The two regimes differ in exactly one field**, because that is the only thing
production varies at this node. `workflows/model_exploration.py:974`
`resolve_run_proposal_blocks` returns `load_proposal_task_blocks()` when
un-composed and `task_composition.proposal_blocks` when composed — `None` for a
task declaring no `proposal_blocks:` section, which is the case for both the
Pets and DAVIS fixtures (`tests/fixtures/step10_p1/{pets,davis}/composition.yaml`).
Any other difference would be one the harness invented.

### What the bytes show

`diff tidmad_regime_a__03_proposer_proposing__system.txt foreign_composed__03_...`:

```
79,80c79
< Both are fully supported. Regression predicts the denoised waveform directly;
< classification predicts a distribution over 256 amplitude bins per timestep.
---
> Both are fully supported.
```

**PR-12a's channel works.** That two-line prose delta is the *entire* difference
between the two regimes. Everything else is byte-identical — including, at
foreign line 114, the full `## SYSTEM-ENFORCED DATASET CONSTRAINTS` block with
`psd_segment_length (10,000,000)`, the 36-divisor list and *"16000 is the
nearest valid neighbor of 16384"*, plus `[B, 256, T]` at lines 47 and 76.

**The contamination is precisely what does not travel through a declared
channel.**

---

## §3 — Tests

`tests/unit/agent/prompt_templates/test_c12pp_composed_prompt_contamination.py`
— **proven state: 1 failed, 8 passed** (`1 failed, 8 passed, 1 warning in 1.62s`).

| test | state | defect it alone catches |
|---|---|---|
| `test_foreign_composed_prompt_has_no_tidmad_dataset_constraints` | **RED — the finding** | TIDMAD dataset science reaching a composed foreign proposing prompt through a path `proposal_blocks` does not cover. Nothing else in the suite asserts on the COMPOSED regime's prompt bytes. |
| `test_marker_matcher_actually_sees_contamination_in_the_tidmad_baseline` | GREEN | a **vacuous** contamination test — a misspelled marker, the wrong stage, or an empty capture would make the RED test go green for the wrong reason. Also fires if a fix strips TIDMAD's own guidance, which the ruling forbids. |
| `test_planted_contamination_is_detected` | GREEN | a matcher correct only against the current fixtures. Builds a clean synthetic prompt, asserts clean, splices the real block in, requires detection — no fixture involved. |
| `test_tidmad_regime_a_prompt_is_byte_identical_to_baseline[6 cases]` | GREEN | **a fix that satisfies the RED test by removing the block from BOTH regimes.** This is the only assertion that fails in that case. Re-renders through production today; comparing the file to itself would assert nothing. |

The RED is the deliverable. Every marker is a hardcoded literal — none read
back from `TIDMAD`, from `_format_known_constraints_block`, or from a baseline
file. A marker derived from the thing under test follows it when it changes and
can never fail; that is the exact shape that let **F-12bc-7** through.

### §3.1 Why an existing test did not catch this — worth keeping

`tests/unit/agent/ml_model_proposal_agent/test_known_constraints_block.py` has
covered this block since it was written, in nine cases. Every one of them calls
`_format_known_constraints_block(TIDMAD)` — **the test SUPPLIES the dataset
config where production HARDCODES it.** It therefore certifies the renderer
perfectly and can never observe that the *call site* is unconditional; passing
`None` in one case proves the renderer no-ops, not that anything ever passes
`None`. This is the F-12bc-7 family one step over: there the test captured what
production recomputed, here the test parameterises what production fixes.

**The rule this suggests**: a test that supplies an argument the production call
site hardcodes is testing a function, not a behaviour. Deriving the value the
way production does — or asserting on the assembled prompt, as §3 does — is what
makes the call site observable.

Corroboration, in the other direction: the un-composed goldens
`tests/unit/agent/ml_model_proposal_agent/goldens/pb3_proposing_{explore,exploit}_system.txt`
**do** contain the block, so PB-3 independently guards Regime-A parity. They are
un-composed captures and are unaffected by a composed-only change — a second
reason the designed fix must not alter the un-composed leg.

---

## §4 — The bounded fix: designed, NOT applied

### §4.1 The correction to the brief's premise — and why it changes the fix

The brief allows that *"it is explicitly acceptable for the bounded fix to OMIT
the irrelevant TIDMAD-specific section from the foreign-task prompt."* **For P1
that is not acceptable, and the reason is executable, not stylistic.**

`ProposalOutput._validate_baseline_segmentation_size`
(`agent/schemas/proposal.py:1232`) is a `@model_validator(mode="after")` that
reads the **same** module-scope `DATASET_CONFIG`. Executed against a real
`ProposalOutput` in this worktree:

```
segmentation_size=   224 (plausible Pets/DAVIS spatial size): REJECTED
    -> must exactly divide psd_segment_length (10000000). Remainder: 192.
segmentation_size=    37 (Pets class count):                  REJECTED
    -> must exactly divide psd_segment_length (10000000). Remainder: 10.
segmentation_size= 20000 (TIDMAD divisor):                    ACCEPTED
```

So the block is **not gratuitous** — it accurately describes a gate the foreign
task really hits. Remove only the prompt and a Pets proposal is rejected by a
`ValidationError` naming a quantity Pets does not have, with the guidance that
would have prevented it now deleted, burning retries (the block's own words:
*"burning one of your retry attempts"*).

**Therefore: P1 and P2 move together or neither moves.** A prompt-only fix is a
regression disguised as a cleanup.

### §4.2 Is there an existing channel? No — wrong semantic slot

`ProposalTaskBlocks` (`agent/schemas/proposal.py:621-748`, ten fields, values in
`configs/task_proposal/tidmad.yaml`) is **free prose rendered verbatim into a
sentence**: a role clause, noun phrases, a guidance paragraph. The P1 block is
categorically different — it is **computed** (`psd = dataset_config.psd_segment_length`;
`valid = dataset_config.valid_segmentation_sizes()`, `agent/prompts.py:743-744`)
and must stay in **lockstep with an executable validator**. Declaring it as
prose would put the *stated* rule and the *enforced* rule in two unrelated
authorities — the duplicate-authority failure that `extra="forbid"` and the
"shapes are DERIVED, only the prose is declared" comment
(`agent/schemas/proposal.py:677-681`) exist to prevent. **Do not put P1 in
`proposal_blocks`.**

Its natural authority is the run's already-composed dataset declaration.

### §4.3 The designed change

**One run-scoped value, read by both halves.**

```text
composition manifest (optional section)
    -> a typed, declared "proposal constraint" value  (None = declares none)
    -> ProposalInput field, CALLER-SUPPLIED   [the PR-12a pattern]
         -> _format_known_constraints_block(value)     # P1
         -> carried onto ProposalOutput so the validator reads
            the SAME value instead of the module constant  # P2
```

Exact minimal edits:

| site | change |
|---|---|
| `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:1653` | `_format_known_constraints_block(DATASET_CONFIG)` → `_format_known_constraints_block(inp.<new field>)` |
| `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:51` | delete the module-scope `TIDMAD as DATASET_CONFIG` import (it has no other use — verified: `:1653` is its sole reference) |
| `agent/schemas/proposal.py:28`, `:1257-1259` | validator reads the run-scoped value; **`seg is None` still early-returns**, and a task declaring no rule runs no check |
| `agent/prompt_templates/proposal/proposing_stage.md:41,70` | P3/P4: the `[B, 256, T]` literals need a placeholder fed by `declared_output_tensor`, the authority the implementor and probe already use |
| `workflows/model_exploration.py` (≈`:2580`, beside `proposal_blocks`) | populate the new field from the composition — **OVERLAP, see §5** |

**Byte-parity argument for Regime A.** `resolve_run_proposal_blocks` establishes
the pattern: the un-composed leg resolves the same shipped TIDMAD value the
module constant supplies today, so `_format_known_constraints_block` receives an
object with identical `psd_segment_length` and `valid_segmentation_sizes()`, and
the f-string at `agent/prompts.py:745-757` is unchanged. Identical inputs to an
unchanged renderer produce identical bytes. **This is asserted, not argued**: the
six `test_tidmad_regime_a_prompt_is_byte_identical_to_baseline` cases re-render
through production and compare to the committed baseline, and they are green
today. If the fix moves a TIDMAD byte, they go red.

A **composed TIDMAD** run declares the section and keeps the block — which is
correct, and is the case an ambient "composed ⇒ suppress" shortcut would get
wrong (see §4.4).

### §4.4 A rejected shortcut, recorded

A fully node-local fix exists: import the no-fallback accessor
`active_task_manifest_path()` (`workflows/task_composition.py:1298`) and pass
`None` when it returns non-`None`. It touches only DISJOINT files and would turn
the RED test green immediately. **Rejected for two reasons**: it makes a
*composed TIDMAD* run silently lose a constraint it is entitled to (and still
enforced against), and it reintroduces ambient reading into a node, contradicting
both the schema/storage/protocol rule and PR-12a's deliberate caller-supplied
choice. Speed here buys a second defect.

### §4.5 Why nothing was implemented

The brief permits speculative implementation only where every touched file is
disjoint. The **prompt half is disjoint; the validator's wiring and the
composition plumbing are not** (§5). Implementing the disjoint half alone would
land exactly the prompt-only change §4.1 proves is a regression. So: design
complete, implementation deferred. This is the finding, not a shortfall.

---

## §5 — Per-file DISJOINT / OVERLAP classification

Against `git diff --name-only c991d6f6...step12-pr12d-contrast-subprocess-closure`
(126 paths, PR-12d head `d2095f6c`, which **moves**; reference checkout
`dd369f3b`).

| file | verdict |
|---|---|
| `agent/prompts.py` | **DISJOINT** |
| `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` | **DISJOINT** |
| `agent/schemas/proposal.py` | **DISJOINT** |
| `agent/prompt_templates/proposal/proposing_stage.md` | **DISJOINT** |
| `agent/prompt_templates/proposal/comparison_stage.md` | **DISJOINT** |
| `agent/prompt_templates/proposal/causal_reasoning_stage.md` | **DISJOINT** |
| `agent/skills/check_config_format_skill/wrapper.py` | **DISJOINT** |
| `nodes/ml_model_implementor/ml_model_implementor.py` | **DISJOINT** |
| `agent/prompt_templates/tuner/rendering.py` | **OVERLAP** |
| `agent/llm_bridge.py` | **OVERLAP** |
| `nodes/ml_hyperparameter_tune_agent/planning.py` | **OVERLAP** |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | **OVERLAP** |
| `execute_tools/dataset_config.py` | **OVERLAP** |
| `workflows/model_exploration.py` | **OVERLAP** |
| `workflows/task_composition.py` | **OVERLAP** |

Files this unit **wrote** — all new, all disjoint by construction:
`tests/helpers/c12pp_prompt_capture.py` ·
`tests/fixtures/c12pp_prompt_baselines/` (12 files) ·
`tests/unit/agent/prompt_templates/test_c12pp_composed_prompt_contamination.py` ·
this document.

**The split is clean and it is the schedule**: the whole proposer contamination
surface is disjoint; the whole planner surface (T1–T4) and all composition
wiring is PR-12d's. §6 follows from this, not from preference.

---

## §6 — Timing discipline

| ready NOW, against landed master | must WAIT for landed PR-12d |
|---|---|
| the census (§1) | any edit to T1–T4 (planner path) — and note PR-12d has already *declared* A2/A3 as debt, so re-fixing it here would collide with its ledger |
| the baselines + harness (§2) | the `workflows/model_exploration.py` line that populates the new field |
| the tests (§3) — including the RED | any change to `execute_tools/dataset_config.py` or `workflows/task_composition.py` |
| the fix design + parity argument (§4) | therefore: the **canonical** production commit, since the wiring is unavoidable |
| the Gate-1 protocol (§7) | the Gate-1 **run** |

**Canonical production prompt edits must not be authored against a moving 12d
authority.** The disjoint proposer edits could technically be written now, but
§4.5 shows the disjoint subset is not a coherent fix. Re-anchor against landed
PR-12d before implementing.

---

## §7 — Gate 1 protocol (PREPARED, NOT RUN)

C12-P-P owns **exactly one** bounded Gate 1, because it changes LLM-facing
prompt bytes. Repository policy (`feedback_gate_llm_config_pro`): **all** Gate
tests use `llm_configs/openai_tiered_pro.json`. Real LLM calls; no training, no
GPU, no inference.

**Launch is blocked today** by the `require_launch_approval` hook regardless of
any frozen authorization (`feedback_gate_launch_hook_vs_frozen_authorization`,
2026-08-24). Per-PR **scoped operator authorization must be obtained before the
run** — do not attempt to fix the hook mid-PR.

### §7.1 The question the Gate exists to answer

> **Does a real model still author a legal `baseline_config` for a foreign
> composed task once the TIDMAD constraint block is absent — or does the task
> need its own declared constraints in its place?**

This is not answerable by inspection. §4.1 shows the constraint is genuinely
enforced; the open question is whether a task that declares *no* rule leaves
the model with enough structure to emit a config that passes the remaining
validators, or whether omission simply relocates the failure.

### §7.2 Design

Four arms, each one proposer run to a real model, prompts and outputs persisted:

| arm | regime | block | purpose |
|---|---|---|---|
| **A1** | TIDMAD, un-composed | present (today's bytes) | control — the block still works |
| **A2** | TIDMAD, composed | present (declared) | the composed-TIDMAD case §4.4's shortcut would break |
| **A3** | foreign composed (Pets) | **absent** | **the question** |
| **A4** | foreign composed (DAVIS) | **absent** | a second, lower-is-better foreign task — one task is an anecdote |

Fixtures: `tests/fixtures/step10_p1/{pets,davis}/composition.yaml`, already in
repo. Prior art for injecting sections at render time:
`scripts/step12_pr12a_gate1.py:157-201`.

### §7.3 Pass / fail checks

| # | check | PASS |
|---|---|---|
| G1 | A3/A4 prompts contain **none** of the §3 TIDMAD-only markers | absent |
| G2 | A1 prompt is **byte-identical** to the committed baseline | identical |
| G3 | A2 retains the block | present |
| G4 | **A3/A4 produce a `ProposalOutput` that validates** | constructed without `ValidationError` |
| G5 | if A3/A4 emit `segmentation_size`, its value is **not** justified by TIDMAD reasoning | no `psd_segment_length` / divisor / `16384` reasoning in `motivation` or `memo_consistency_notes` |
| G6 | A3/A4 `model_description` contains no denoising/ADC/waveform/amplitude-bin claims | absent |
| G7 | retry count for A3/A4 ≤ the A1 control | no retry inflation |

### §7.4 What counts as a FAIL — stated in advance

- **G4 red** ⇒ the omission-only fix is **insufficient**; the task needs its own
  declared constraints, and the bounded fix must grow a declaration slot. This
  is the single most important outcome and the reason the Gate is required.
- **G2 red** ⇒ Regime-A parity broke. Blocking, independent of everything else.
- **G5 red** ⇒ the model *invented* TIDMAD's rule from surrounding context, so
  removing the block did not remove the science — the contamination has a
  second source.
- **G7 red** ⇒ omission is operationally worse even if formally legal.
- A3 passing while A4 fails ⇒ **not a PASS.** Two tasks precisely so that one
  cannot carry the claim.

### §7.5 What this Gate cannot establish — honest limits

1. **Nothing about training, scoring or convergence.** No training runs. A
   `baseline_config` that validates is not a config that trains, and PR-12d's
   contrast-track execution claims are untouched by this Gate.
2. **Nothing about the planner path.** T1–T4 are OVERLAP and out of scope; a
   PASS here says nothing about the config manual (T1–T3), which is UNGATED and
   reaches every composed planner prompt.
3. **Not a generalisation to a fourth task.** Pets and DAVIS are in-repo
   fixtures. An out-of-tree task is PR-12e's.
4. **One sample per arm is not a distribution.** A single PASS shows the prompt
   is *sufficient*, not that it is *robust*. Nondeterminism is not measured, and
   no rerun-stability claim may be made from it.
5. **It cannot prove absence of contamination in general** — only that the
   enumerated markers are absent. §1.3's boundary is a judgement, and G6 is a
   substring probe, not a semantic one.
6. **Model-version-bound.** The verdict holds for the model in
   `openai_tiered_pro.json` at run time and does not transfer.

---

## §8 — Where the brief was wrong, or incomplete

1. **"TIDMAD-only scientific constraints ABSENT" is not sufficient for P1.**
   The constraint is machine-enforced for foreign tasks too (§4.1, executable).
   The minimal acceptable contrast must be *prompt and validator agree*, not
   *prompt is silent*. This is the single most consequential correction.
2. **`ProposalTaskBlocks` is the wrong slot** — confirmed, as the brief
   suspected it might be, and now with a reason: the block is computed and
   validator-coupled, not prose (§4.2).
3. **`agent/prompts.py:720-757` is exact**, and its `dataset_config=None -> ""`
   backward-compat contract is real (`:740-741`). The `{known_constraints_block}`
   placeholder is at `proposing_stage.md:108`. All confirmed.
4. **The named example *"punet and transformer are CLASSIFIERS (256 classes)"*
   is on the PLANNER path, not the proposer** — `check_config_format_skill/wrapper.py:23`,
   which is PR-12d's declared A2/A3 debt and is **OVERLAP**. The brief grouped
   it with the proposer anchors; they are two different surfaces with two
   different schedules.
5. **The brief's confirmed example list was incomplete in one material way**:
   `[B, 256, T]` is hardcoded in the stage **template** with no placeholder
   (P3/P4), so it is unreachable by *any* declared channel. Anchor-following
   alone would have missed it.
6. **`--force_model` reduces but does not remove the blast radius.** PR-12d's
   A2/A3 row reasons that the real planner used the pack's own fields. That is
   about the *planner*; the *proposer* is bypassed entirely by `--force_model`,
   so P1–P8 are unexercised by PR-12d's frozen command and correspondingly
   un-witnessed by it.

---

# §Z — PREP PACKET (2026-08-24, post-12d / post-B3). CURRENT AUTHORITY.

**Status: PREP ACTIVE · FINAL IMPLEMENTATION BLOCKED ON C12-P CORE AUTHORITY.**
No production writes. No Gate launch. No landing.

## Z.1 Current source audit — mechanically inspected, not assumed

| fact | value | how verified |
|---|---|---|
| landed authority | `84d74280` = *"PR-12d — Contrast subprocess closure (Pets + DAVIS reach L4) (#274)"* | `git cat-file -t` + `git log -1` |
| C12-P candidate | branch `c12p-landed` @ `b7b08586`, **12d is an ancestor** | `git merge-base --is-ancestor` ⇒ YES |
| B3 closure commit | `22833317` *"B3 fix + B1/B2/B8 evidence onto landed 12d — B3 is CLOSED"* | `git show --stat` |
| C12-P open | rows 4/5 witness, then B5+B6 / B11 | design §Y, ledger row 2015 |
| this branch | `c12pp-prompt-contamination` @ `76bebfd1`, based on `c991d6f6` — **12d is NOT an ancestor**; a rebase onto C12-P core is required before landing | `git merge-base --is-ancestor` ⇒ NO |

**PR-12d landing invalidates §5's overlap map.** Those files are no longer a
moving write set; they are landed source. §Z.3 replaces it.

### Z.1a The B3 authority underneath P1

`agent/schemas/proposal.py::_validate_baseline_segmentation_size` no longer
reads the module-scope `TIDMAD`. Its applicability decision, verbatim:

```python
profile = resolve_dataset_profile()
if not declares_tidmad_topology(profile):
    return self
dataset = tidmad_topology(profile).dataset
```

All three functions are **landed 12d's canonical predicates**
(`execute_tools/dataset_config.py:824`, `:842`, `:887`) — C12-P vendored
nothing. Applicability is an explicit **membership test**, never
`try: tidmad_topology(...) except ValueError`, because that function raises for
ABSENT *and* for PRESENT-BUT-MALFORMED sections; catching it would silently
reclassify a malformed TIDMAD profile as "declares none". **A malformed
topology must stay loud.** This is the semantics P1 must mirror exactly.

## Z.2 P1 — refreshed patch plan (re-derived, not replayed)

**Applicability boundary (current):** *the run's resolved `DatasetProfile`
declares a TIDMAD topology.* Not a task name, not artifact presence, not
composition presence.

**Prompt construction path (current, re-verified — all three files UNCHANGED
since `c991d6f6`):**

```
MLModelProposalAgent.run()
  -> _run_pipeline()
  -> template_vars["known_constraints_block"]
       = _format_known_constraints_block(DATASET_CONFIG)   # :1653, module const from :51
  -> load_stage_prompt("proposing_stage", ...)
  -> {known_constraints_block} at proposing_stage.md:108
  -> proposing-stage SYSTEM prompt
```

**Exact proposed write set — 1 production file, 2 hunks:**

| # | file:line | change |
|---|---|---|
| Z-P1-a | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:51` | drop `from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG`; import the three canonical predicates |
| Z-P1-b | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:1653` | resolve the applicable dataset exactly as B3 does; pass `None` when the run declares no TIDMAD topology |

`agent/prompts.py` needs **no edit** — `_format_known_constraints_block(None)`
already returns `""` (`:740-741`), its documented backward-compat contract.
This satisfies **Y.2 (suppress, do not invent a capability family)** literally:
zero new schema fields, zero new config sections, zero new channels.

**P1 does NOT edit `agent/schemas/proposal.py`.** B3 already owns that file's
applicability decision; P1 mirrors it at the prompt layer. One semantic
authority, two consumers — Y.2 preserved.

### Z.2a Regime-A byte parity — DISCHARGED IN ADVANCE

Executed on `c12p-landed` (post-B3) with no production change:

```
same object          : False     <-- identity does NOT hold
psd equal            : True
divisors equal       : True
RENDERED BYTES EQUAL : True  | len 820
foreign (None) renders: ''
```

**Precision correction to `22833317`'s message**, which says the resolved
dataset *"IS the `TIDMAD` singleton"*: it is **not the same object**. The
parity claim is **value equality**, and it holds — `_format_known_constraints_block`
reads only `psd_segment_length` and `valid_segmentation_sizes()`, both equal,
producing the identical 820 bytes. B3's correctness is unaffected (it also
reads only values), but the wording should not be relied on as identity.

So P1's parity argument is proven *before* implementation, and the six live
Regime-A parity cases will confirm it against the committed baseline.

## Z.3 Collision map — exact, mechanically computed

P1 write set vs every active branch, base `84d74280`:

| branch | verdict |
|---|---|
| `c12p-landed` `b7b08586` | `agent/schemas/proposal.py` — **SAME SEMANTIC AUTHORITY (B3)**. `RECONCILE_AFTER_C12P`: P1 must **not** edit it. No collision on P1's actual write set |
| `c12p-composed-admission-preflight` `2515ac8a` | **no overlap** (133 files) |
| `c12p-w1-b7b11` `3d21edc9` | **no overlap** (137 files) |
| `c12p-w2-b3` `74dab0a9` | **no overlap** (133 files) |
| `c12p-w3-b1b2` `96b81951` | **no overlap** (134 files) |
| `infra/ci-parity-hermetic-harness` `3bd186b5` | **no overlap** (13 files) |
| `arxiv/integration-post12d` `6b811df5` | **same file / semantic-disjoint** — see Z.3a |
| `arxiv/p1-agent-generated-migration` `a84775f6` | identical U3 delta; same classification |

### Z.3a arXiv U3 — adjacent, and it takes two census rows off C12-P-P

arXiv U3 (`baseline_isolation`, #260 / R6) edits the proposer's prompt surface
for a *different* reason: suppressing bundled-baseline identity for the WITHOUT
experiment arm.

* `ml_model_proposal_agent.py` — touches `:1720` (`available_models_block`) and
  four `baseline_isolation=` kwargs. P1 touches `:51` and `:1653`. **≥64 lines
  apart, different `template_vars` key ⇒ semantic-disjoint and mechanically
  conflict-free at 3-line hunk context.**
* `agent/schemas/proposal.py` — adds `ProposalInput.baseline_isolation` at
  `:787`; B3 changed the validator at `:1246-1290`. **~460 lines apart ⇒
  semantic-disjoint.**
* **`comparison_stage.md` + `causal_reasoning_stage.md`: arXiv U3 now OWNS the
  `5.57` / wavenet worked-example literals**, parameterised as
  `example_sota_score`. Those are census rows **P6 and P8**.
  ⇒ **P6/P8 are REMOVED from C12-P-P's surface** and deferred to arXiv U3.
  Re-fixing them here would create a second authority for the same literals.
* arXiv U3 does **not** touch `proposing_stage.md`, so **P1, P3 and P4 are
  collision-free everywhere.**

**Net: P1's core has ZERO collisions on any active branch.**

## Z.4 Deterministic test / falsifier matrix

Command (all deterministic rows; no key, no network, no GPU):

```bash
cd /home/yuema137/siderius-c12pp-prompts
env -u OPENAI_API_KEY PYTHONPATH=/home/yuema137/siderius-c12pp-prompts \
  /home/yuema137/SIDERIUS/.venv/bin/python -m pytest \
  tests/unit/agent/prompt_templates/test_c12pp_composed_prompt_contamination.py -q -rs \
  > /tmp/c12pp.log 2>&1; rc=$?; tail -n 20 /tmp/c12pp.log; exit $rc
```

| row | property | state | owner |
|---|---|---|---|
| **A** | Regime-A / TIDMAD prompt parity | **GREEN, 6 cases**, mutation-proven RED under the naive both-regimes fix | exists |
| **B** | foreign composed task carries no TIDMAD science | **RED — live production render**, names all six markers | exists |
| **C** | applicability is explicit semantic **membership**, not artifact presence | **TO AUTHOR** with the fix — assert the call site routes through `declares_tidmad_topology`, and that a profile *declaring* the topology keeps the block regardless of any artifact on disk | new, P1-side twin of B3 |
| **D** | malformed applicable declaration stays **loud** | **TO AUTHOR** with the fix — a PRESENT-BUT-MALFORMED TIDMAD topology must **raise** at the prompt path, never silently render `""`. This is the highest-value new falsifier: the naive `try/except` P1 shape passes A and B and fails only here | new, P1-side twin of B3 |
| **E** | no `OPENAI_API_KEY` vacuity | **CLOSED** — `env -u OPENAI_API_KEY` ⇒ `1 failed, 8 passed`, **0 skipped**; network-proven at the socket layer (§Y.3) | closed |
| **F** | live contamination witness has a real RED baseline | **CLOSED** — the test renders through production, not a snapshot | closed |

**C and D are deliberately NOT authored yet.** Both must fail *for the right
reason*, which requires the production change to exist; authoring them now
would bake in an assumed API and create exactly the reconciliation burden §7 of
the operator brief forbids. Their assertions are specified above; authoring is
~15 minutes at implementation time.

## Z.5 Evidence banking

| evidence | class |
|---|---|
| the census §1 (P1–P5, P7; T1–T4) | **source-independent** — target files byte-unchanged since `c991d6f6` |
| P6 / P8 census rows | **OBSOLETE for C12-P-P** — reassigned to arXiv U3 (Z.3a) |
| prompt baselines, 12 files | **source-independent** — the three files that produce them are unchanged; re-verified by row A passing today |
| rows A, B, E, F | **source-independent** (they run green/RED against current source) |
| §5 overlap map | **OBSOLETE** — superseded by Z.3 |
| §4.3 wiring sketch (new `ProposalInput` field + `model_exploration.py`) | **OBSOLETE** — Y.2 + B3 make suppression sufficient; no schema field, no workflow edit |
| Z.2a parity numbers | **source-dependent, ALREADY REFRESHED** on post-B3 `c12p-landed` |
| Gate 1 arms/criteria §7 | **source-independent**; arm list refreshed in Z.6 |

## Z.6 Live Gate 1 packet — PREPARED, NOT LAUNCHED

* **Blocked by**: landed PR-12d (✅ `84d74280`) **+ B3 closure** (✅) **+ P1
  implementation** (⛔ not yet). Per **Y.4**, **NOT** blocked by B7 — do not
  serialize behind it.
* **Authorization**: the `require_launch_approval` hook blocks all real
  launches regardless of frozen approval. **Per-PR scoped operator
  authorization required before launch**; do not modify the hook.
* **Config**: `llm_configs/openai_tiered_pro.json` (repository policy: all
  Gate tests). Real LLM calls only — no training, no inference, no GPU.
* **Expected source state**: C12-P core landed; this branch rebased onto it;
  P1's two hunks applied; rows A–D green/RED as specified.
* **Arms**: A1 TIDMAD un-composed (block present, control) · A2 TIDMAD composed
  (block present) · A3 Pets composed (**block absent** — the question) · A4
  DAVIS composed (block absent, second task).
* **Checks G1–G7, failure classification and the six honest limits**: unchanged,
  §7.3–§7.5.
* **The question**: does a real model still author a legal `baseline_config`
  for a foreign composed task once the block is absent? **G4 red ⇒ suppression
  is insufficient** and the operator must rule on a declared-constraint slot —
  the one outcome that would reopen Y.2.

## Z.7 Post-C12-P execution order + estimate

```
refresh landed C12-P SHA -> rebase this branch -> apply P1 (2 hunks)
  -> author rows C+D -> deterministic RED->GREEN -> live contamination proof
  -> [AUTHORIZATION] -> bounded Gate 1 -> final local validation -> LAND
```

| step | estimate |
|---|---|
| rebase + reconcile | 10–20 min (no collisions; 4 commits, 0 production files) |
| P1 implementation (2 hunks) | 10 min |
| rows C + D | 15 min |
| deterministic re-validation + ruff | 10 min |
| live contamination proof | 5 min |
| Gate 1 (4 arms, ~12 real calls) + evaluation | 30–45 min **after** authorization |
| doc sync + final validation | 20 min |
| **total** | **≈ 1.5–2 h**, of which ~45 min is Gate wall-clock |

## Z.8 True semantic ambiguities — operator input needed

1. **Are P3/P4 in P1's scope?** The `[B, 256, T]` literals at
   `proposing_stage.md:41,70` are hardcoded with **no placeholder**, so no
   suppression channel reaches them; fixing them needs a new placeholder fed by
   `declared_output_tensor` (already imported at the proposer `:46`, so not a
   new capability family). But it is a *template* change, not a call-site
   suppression, and it moves Regime-A bytes only if `declared_output_tensor`
   renders differently. **Recommendation: land P1 alone; carry P3/P4 as a named
   follow-up.** They are currently inside row B's marker set, so P1 alone will
   leave row B RED on one marker — **this must be decided before implementation
   or row B cannot go green.** ⚠️ *This is the one item that blocks a clean
   RED→GREEN.*
2. **Composed TIDMAD**: `resolve_dataset_profile()` returns TIDMAD's profile, so
   the block is retained — correct, and confirms §4.4's rejection of an ambient
   "composed ⇒ suppress" shortcut. No ambiguity; recorded for the Gate's A2 arm.
3. **T1–T4 (planner path)** remain PR-12d's declared A2/A3 debt and are **not**
   C12-P-P's. Landed 12d did not close them. Recorded, unclaimed.

---

# §ZZ — OPTION 2 SPLIT: P1-A / P1-B. Prep only.

Operator ruling 2026-08-24 (fifth). **Splitting the marker set is a test-STRUCTURE
decision, not permission to weaken acceptance.**

```text
P1-A GREEN alone  !=  C12-P-P DONE
DONE = P1-A closed AND P1-B closed AND the ZZ.5 aggregate render GREEN
```

## ZZ.1 P1-A — final proposed write set (confirmed against current source)

One production file, two hunks. `agent/prompts.py` unedited.
**B3 remains the SOLE applicability authority; P1-A does not reimplement it.**

```text
nodes/ml_model_proposal_agent/ml_model_proposal_agent.py
  :51   - from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG
        + from execute_tools.dataset_config import (
        +     declares_tidmad_topology, resolve_dataset_profile, tidmad_topology,
        + )

  :1653 - "known_constraints_block": _format_known_constraints_block(DATASET_CONFIG),
        + "known_constraints_block": _format_known_constraints_block(
        +     _applicable_dataset_constraints()
        + ),
```

plus one private helper in the same module, mirroring B3's decision verbatim:

```python
def _applicable_dataset_constraints():
    """The dataset whose segmentation rule the proposer is actually judged by.

    Mirrors ProposalOutput._validate_baseline_segmentation_size (C12-P / B3):
    the PROMPT must state exactly the rule the VALIDATOR enforces. Membership
    test, never try/except -- tidmad_topology() raises for ABSENT and for
    PRESENT-BUT-MALFORMED alike, so catching it would silently reclassify a
    malformed profile as "declares none" and render no constraint at all.
    """
    profile = resolve_dataset_profile()
    if not declares_tidmad_topology(profile):
        return None
    return tidmad_topology(profile).dataset
```

**Regime-A byte parity: PROVEN IN ADVANCE** (§Z.2a) — `fmt(resolved) == fmt(TIDMAD)`,
820 bytes, and `fmt(None) == ""`. P1-A is byte-preserving for TIDMAD.

## ZZ.2 P1-B — classification **B CONFIRMED**, with independent evidence

Verified myself, not taken on report.

| link | verified |
|---|---|
| `proposing_stage.md:130` holds `{forward_contract}` | ✅ read |
| fed at `ml_model_proposal_agent.py:1705` by `render_forward_contract(inp.forward_contract)` | ✅ read |
| `workflows/task_config.py:308` emits `input:` / `output:` lines | ✅ read |
| composed runs get the FOREIGN contract | ✅ `load_task_config()` returns `_BOUND_TASK_CONFIG.get()` when bound (`task_config.py:194-196`), bound at `task_composition.py:2184` |

**Executed on landed 12d (`84d74280`), all three tasks render non-empty:**

```
TIDMAD  len=666  output: [B, 256, T] float32  — per-timestep logits over 256 denoising classes
PETS    len=699  output: [B, 37] float32      — per-breed logits, one score per Oxford-IIIT Pet class
DAVIS   len=880  output: [B, 3, 4, 128, 224] float32 — ... NOT logits and NOT class indices
```

**The safety argument HOLDS: TIDMAD loses no required scientific instruction**,
because its authoritative `[B, 256, T]` is already in the SAME prompt at `:130`.
The template's `:41`/`:70` shapes are a redundant duplicate.

**DAVIS is the decisive witness**: today one prompt simultaneously tells it
*"classifier -> [B, 256, T]"* (`:41`) and *"output: [B, 3, 4, 128, 224] … NOT
logits and NOT class indices"* (`:130`). A direct self-contradiction.

### ZZ.2a Two corrections to the ruling's scope

1. **`:71` must move with `:70`.** The ruling names `:41` and `:70`; the
   regressor row `:71` (`` | `"regressor"` | `[B, T]` float | ``) is the same
   table and equally TIDMAD-only — DAVIS's regressor output is
   `[B, 3, 4, 128, 224]`, not `[B, T]`. Leaving it would fix half a table.
2. **Scope is closed**: `grep` over every `agent/prompt_templates/proposal/*.md`
   finds these shape literals **only** in `proposing_stage.md`. The `_explore` /
   `_exploit` variants are clean.

### ZZ.2b Proposed minimal correction — concept preserved, examples removed

`:41` — `output_type` field description:

```
  "output_type": "classifier | regressor — REQUIRED. See 'Output contract' above
  and this task's forward contract below for the exact shapes. classifier -> a
  per-class score axis, legal with ce/focal/focal_cw; regressor -> continuous
  values, legal with smooth_l1. Independent of loss_type: state it explicitly,
  never infer it.",
```

`:70-71` — the table body (header, placeholders and column structure unchanged):

```
| `"classifier"` | a per-class score axis (see the forward contract below) | {CLASSIFIER_LOSS_LIST} |
| `"regressor"`  | continuous values (see the forward contract below)      | {REGRESSOR_LOSS_LIST}               |
```

No new placeholder, no new formatter, no new channel — per the ruling. The
framework vocabulary (classifier vs regressor, which losses are legal,
`{CLASSIFIER_LOSS_LIST}` / `{REGRESSOR_LOSS_LIST}`) is untouched.

### ZZ.2c ⚠️ P1-B deliberately BREAKS Regime-A byte parity

Task-neutral rewriting necessarily moves TIDMAD's bytes. **The acceptance
criterion differs per mechanism**, which is what the ruling's *"byte-preserved
**where required**"* qualifier licenses:

| | P1-A | P1-B |
|---|---|---|
| Regime-A criterion | **byte-identical** (proven) | **deliberately changed**; criterion is *no required scientific instruction lost* |
| evidence | row A green against the committed baseline | forward-contract co-presence + a re-captured baseline whose diff is confined to `:41`/`:70`/`:71` |

The Regime-A baseline must be **re-captured at P1-B**, with the diff reviewed to
confirm it touches only those three lines. Re-capturing at P1-A would be a
ceremony that destroys row A's meaning.

## ZZ.3 Per-mechanism falsifiers

**P1-A**
* `A1` non-membership ⇒ computed block ABSENT. A profile declaring no TIDMAD
  topology renders no `SYSTEM-ENFORCED DATASET CONSTRAINTS`.
* `A2` Regime-A ⇒ the 820-byte block byte-identical (row A, 6 cases).
* `A3` **membership, not artifact presence** — a profile that DECLARES the
  topology keeps the block regardless of any on-disk artifact.
* `A4` **malformed stays LOUD** — a PRESENT-BUT-MALFORMED topology must RAISE at
  the prompt path, never render `""`. *Highest value: the naive `try/except`
  shape passes A1–A3 and fails only here.*
* `A5` prompt/validator agreement — the block is emitted iff B3 would enforce
  the rule. Guards the §4.1 "strictly worse" state.

**P1-B**
* `B1` no hardcoded `[B, 256, T]` or `[B, T]` shape assumption in the rendered
  proposing prompt for any task.
* `B2` **TIDMAD loses no required instruction** — `[B, 256, T]` still present in
  the same prompt, sourced from `{forward_contract}`.
* `B3'` concept preserved — `classifier`, `regressor`, and both loss lists still
  render.
* `B4'` DAVIS self-consistency — no sentence contradicts the rendered contract.

## ZZ.4 ⚠️ Gap in this unit's OWN evidence, found while verifying

The 12 committed baselines were captured with `forward_contract` left at its
default-empty value, so `{forward_contract}` renders `""` in them
(`grep` for the block ⇒ ABSENT). Production always populates it
(`model_exploration.py:2547`).

Consequences, stated plainly:
* the baselines **under-represent** the real prompt;
* row A stays valid (a self-consistent parity pin), but
* **the ZZ.5 aggregate test must populate `forward_contract`**, or it would
  certify a prompt production never emits — and P1-B's whole safety argument
  rests on a block those fixtures do not contain.

**Fix at implementation time**: extend `tests/helpers/c12pp_prompt_capture.py`
to populate `forward_contract` per regime (TIDMAD / Pets / DAVIS) and re-capture.
This is a test-harness change, not a production change.

## ZZ.5 The AGGREGATE invariant test (the anti-drop guard)

One test, authored after both mechanisms land, over the **complete** rendered
foreign composed proposing prompt with `forward_contract` populated:

```
tests/unit/agent/prompt_templates/test_c12pp_composed_prompt_contamination.py
    ::test_foreign_composed_prompt_carries_no_tidmad_contamination_aggregate
```

* asserts the FULL `TIDMAD_ONLY_MARKERS` set — **both** the P1-A computed-block
  markers **and** the P1-B shape literals — is absent;
* the marker set must **not** be split, narrowed or parameterised per mechanism.
  Per-mechanism tests may exist *in addition*; this one keeps the union;
* runs for **Pets and DAVIS**, since DAVIS is the only task whose contract
  contradicts the removed literals;
* non-vacuity: the same matcher must still find every marker in a pre-fix
  fixture, so the union cannot silently shrink to nothing.

**This is the test that makes "P1-A green ≠ done" mechanically true.**

## ZZ.6 Estimated post-C12-P wall-clock

| step | est. |
|---|---|
| rebase onto landed C12-P core (0 production files, no collisions) | 10–20 min |
| **P1-A** — 2 hunks + helper; falsifiers A1–A5 | 35 min |
| **P1-B** — 3 lines; falsifiers B1–B4'; harness `forward_contract` fix + re-capture + diff review | 45 min |
| **ZZ.5 aggregate** test | 15 min |
| deterministic re-validation + ruff (`check` and `format --check`) | 15 min |
| Gate 1 (4 arms) + evaluation — **after** scoped authorization | 30–45 min |
| doc sync + final validation | 20 min |
| **total** | **≈ 2.5–3 h**, ~45 min of it Gate wall-clock |

pyright cannot run locally (Node v10.19.0; the vendored bundle raises
`SyntaxError`). **No pyright pass is claimed.** CI is the only environment that
can run it.

---

# §ZW — MINIMUM SEMANTIC WITNESS (parent policy, pre-H100). Prep only.

Policy: *framework readiness / contract / semantic-route behaviour — NOT
scientific quality.* **Prefer zero training.** Applied below to both the live
contamination witness and Gate 1.

## ZW.1 The feasibility result that removes the expensive dimension

Executed on landed `84d74280`, against the REAL shipped manifests
`configs/task_composition/{pets,davis}.yaml`, with an **empty synthetic data
root** (`mkdir -p` on a scratch dir; not one byte of real data):

```
pets   BOUND ok in 0.86s | proposal_blocks=None | fc 699 chars
         output: [B, 37] float32  — per-breed logits, one score per Oxford-IIIT Pet class
davis  BOUND ok in 0.01s | proposal_blocks=None | fc 880 chars
         output: [B, 3, 4, 128, 224] float32 — ... NOT logits and NOT class indices
```

**`compose_run_task_bindings` + `bind_run_task_composition(comp,
physical_data_root=<empty tmp dir>)` succeeds in under one second per task with
zero data, zero training, zero GPU and zero network**, and under that binding
`load_task_config()` returns the FOREIGN contract.

Three consequences:

1. The parent's constraint is **satisfiable**: the aggregate test can render
   under a **real composed binding** rather than loading pack configs directly,
   so it never hits `DatasetContradictionError` and never passes for the wrong
   reason.
2. The `forward_contract` fixture gap (§ZZ.4) closes through the **same**
   mechanism — bind, then read `load_task_config()`. No hand-built contract, no
   invented rendering path.
3. **The contamination invariant needs no expensive execution at all.**
   Both shipped manifests declare **no `proposal_blocks:` section**, so
   `proposal_blocks = None` is the production value, not a fixture guess.

## ZW.2 Minimum live-witness design — training 0, real data none

The invariant is *"a foreign composed run's proposing prompt contains no
TIDMAD-specific science"*. That is a **prompt-construction** property. Nothing
in it depends on optimizer steps, dataset scale, or model quality.

| layer | what it proves | cost |
|---|---|---|
| **W1 — composed render** (deterministic) | the node, under a real Pets/DAVIS binding, renders a clean prompt with the foreign `{forward_contract}` present | < 2 s, no data, no training |
| **W2 — orchestration reachability** (pseudo-mode, existing tier) | `run_workflow` actually executes the proposer INSIDE the composition binding, so the ambient resolution P1-A relies on is really active — the gap a pure unit render leaves | milliseconds, mocked LLM + subprocess |
| **W3 — Gate 1** (real LLM) | a real model still authors a legal `baseline_config` with the block absent | LLM calls only |

**W1 + W2 replace what would otherwise be "run a real composed chain".** I am
**not** inheriting a TIDMAD workflow to prove prompt cleanliness. There is no
W-layer requiring training, and none requiring real data.

W2's justification for existing at all: P1-A resolves through the **ambient**
binding, so "the node renders clean when I bind it myself" does not prove
production binds it. `bind_run_task_composition`'s docstring claims launcher-edge
lifetime covering the iteration loop; W2 is the executable check of that claim,
at pseudo-mode cost. If W2 cannot be built without real execution, I will report
that rather than escalate to a real chain.

## ZW.3 Gate 1 — REQUIRED-FIELDS launch packet

| field | value |
|---|---|
| **exact invariant** | With the TIDMAD constraint block absent (P1-A) and the shape literals task-neutral (P1-B), a **real** LLM still authors a `baseline_config` that passes `ProposalOutput` validation for a foreign composed task — and does not re-import TIDMAD science from context |
| **exact source SHA** | landed C12-P core + this branch rebased + P1-A + P1-B applied. **Not yet known**; recorded at launch, never assumed |
| **exact command** | a bounded driver in the shape of `scripts/step12_pr12a_gate1.py` — compose the shipped manifest, bind with a synthetic data root, build one `ProposalInput`, call the proposer once per arm. **Not `run_chain.sh`, not `run_comparison.py`** |
| **expected LLM/model calls** | **12** — 4 arms × 3 pipeline stages (comparison, causal_reasoning, proposing). Config `llm_configs/openai_tiered_pro.json` (repository policy) |
| **expected dataset scope** | **NONE.** Empty synthetic data root, proven sufficient in ZW.1 |
| **expected training workload** | **ZERO.** No training subprocess, no optimizer step, no GPU, no checkpoint |
| **expected inference / scoring** | **ZERO** |
| **expected wall-clock** | **~10–15 min** (12 calls + evaluation) |
| **why each non-trivial computation cannot be removed** | *4 arms*: A1 TIDMAD un-composed is the parity control; A2 TIDMAD composed is the only arm that would catch an over-broad "composed ⇒ suppress"; A3 Pets and A4 DAVIS are two foreign tasks because one is an anecdote, and **DAVIS is the only task whose contract contradicts the removed literals**. *3 stages per arm*: the proposing prompt is assembled by `_run_pipeline`, whose earlier stages feed it — calling the proposing stage alone would not be the production path. **Nothing else is spent.** |
| **required authorization** | per-PR scoped operator approval via the parent; `require_launch_approval` blocks all real launches regardless of frozen approval |

**Why a real LLM is load-bearing at all** — the one dimension I cannot remove:
G4 asks whether omission leaves the model *able to comply*. That is a claim about
a real model's behaviour under a changed prompt; a deterministic test can assert
the prompt's bytes but cannot answer it. Every other Gate check (G1, G2, G3, G6)
is deterministic and is asserted in the falsifier suite instead, so the Gate is
scoped to the **only** question that needs a model.

**Not claimed by this Gate**: nothing about training, scoring, convergence or
model quality. Per policy, poor proposal quality is **not** a framework failure
here — only `ProposalOutput` validation failure (G4) is.

## ZW.4 Aggregate test — binding requirement now explicit

§ZZ.5 stands, amended: the aggregate test **must** obtain its prompt by

```text
compose_run_task_bindings(configs/task_composition/{pets,davis}.yaml)
  -> bind_run_task_composition(comp, physical_data_root=<tmp_path>)
     -> build ProposalInput with forward_contract from load_task_config()
        -> render through the production _run_pipeline path
```

and **never** by loading a pack's `task_config.yaml` directly — that raises
`DatasetContradictionError` against the ambient TIDMAD `ValueEncoding` and would
fail for the wrong reason.

## ZW.5 Anti-vacuity is mandatory for every rewritten structural test

Per parent ruling: an updated assertion without a mutation proof is
insufficient. Each of A1–A5, B1–B4' and the ZZ.5 aggregate must carry a recorded
mutation that turns it RED, with the mutation reverted and the file verified
byte-identical afterwards (`feedback_mutation_proof_hygiene`: clear `.pyc`,
assert the plant landed exactly once, re-run the baseline).

## ZW.6 Durable correction to propagate (ledger / PR narrative, NOT history)

> `tidmad_topology(resolve_dataset_profile()).dataset is TIDMAD` → **False**.
> Value / semantic equivalence → **True** (`psd_segment_length` equal, divisor
> list equal, rendered block byte-identical at 820 chars).

Commit `22833317`'s message says *"IS the `TIDMAD` singleton"*. **Do not claim
singleton identity.** B3's correctness is unaffected — it reads only values —
and no historical commit is to be rewritten for prose.

---

# §ZG — GATE-1 CALL INVENTORY (minimized). Shadow head, not launched.

Measured, not assumed: **one proposer run makes exactly 3 LLM calls** —
`proposer.comparison`, `proposer.causal_reasoning`, `proposer.proposing`.

## ZG.1 Per-arm inventory

| arm | proves | already proven deterministically? | verdict |
|---|---|---|---|
| **A1** TIDMAD un-composed, block present | that P1-B's task-neutral table still lets a real model emit a correct `output_type`/shape when the shape lives only in `{forward_contract}` | **No.** W1 proves the BYTES; it cannot prove the remaining instruction is *sufficient for a model*. P1-B changed TIDMAD's prompt, and "no required scientific instruction lost" is a frozen criterion | **KEEP — 3 calls** |
| **A2** TIDMAD composed, block present | that a composed TIDMAD run RETAINS the constraint block | **YES.** W1 ran `tidmad` through a real `bind_run_task_composition` and found all 8 markers present. There is no model question here — it is a rendering fact | **DROP — 0 calls** |
| **A3** Pets composed, block absent | G4: a real model authors a legal `baseline_config` with the block absent — classifier branch | **No.** This is the frozen live question | **KEEP — 3 calls** |
| **A4** DAVIS composed, block absent | G4 on the **regressor** branch, and the only task whose declared contract contradicted the removed literals | **No.** Different `output_type` branch, not a repeat sample of A3 | **KEEP — 3 calls** |

**12 → 9 calls.** A2 is removed because W1 already answers it with zero calls.

## ZG.2 Per-stage inventory (why 3 and not 1)

| stage | semantically required? |
|---|---|
| `comparison` | **Yes — sequentially dependent.** `_run_pipeline` feeds each stage's output into the next; the proposing prompt embeds the DiscoveryMemo these stages produce |
| `causal_reasoning` | **Yes — same dependency chain** |
| `proposing` | **Yes — the stage under test** |

`ReasoningPipelineConfig(stages=[...])` *is* a public bounded configuration and
could cut the first two. **Rejected**: with no reasoning stages the proposing
prompt carries an empty memo, so the model would be answering a prompt
production never emits. That is reducing by inventing a bypass, which the
ruling forbids, and it would invalidate the very thing G4 measures. **Ordering
is part of the invariant, so the sequence is preserved.**

## ZG.3 Irreducible live-call count: **9**

| field | value |
|---|---|
| **training workload** | **ZERO** |
| **dataset scope** | **NONE** — empty synthetic data root, proven sufficient by W1 |
| **inference / scoring** | **ZERO** |
| **GPU** | **NONE** |
| **live LLM calls** | **9** (3 arms × 3 sequentially-dependent stages) |
| **expected wall-clock** | **~10 min** |
| **config** | `llm_configs/openai_tiered_pro.json` |
| **driver** | bounded, shaped like `scripts/step12_pr12a_gate1.py`; composes the shipped manifest, binds with an empty root, runs the proposer once per arm. **Not `run_chain.sh`, not `run_comparison.py`** |
| **source SHA** | landed C12-P core + this branch rebased. Recorded at launch, never assumed |

**Parallelism**: the three arms are semantically independent (different tasks,
no shared state). Stages *within* an arm are not. No concurrency subsystem is
proposed; if the harness already supports independent invocations they may run
concurrently, otherwise sequential at ~10 min is acceptable.

## ZG.4 Acceptance, unchanged in substance

G1 markers absent in A3/A4 · G2 A1 parity confined to the reviewed 3-line diff ·
G4 **`ProposalOutput` validates** (the frozen question) · G5 no TIDMAD-derived
reasoning in `motivation` · G6 no denoising/ADC claims · G7 retries not inflated
vs A1. **Poor proposal quality is NOT a failure** — only validation failure is.

**FAIL ⇒ suppression is insufficient** and the operator must rule on a declared
constraint slot. That is the one outcome that reopens Y.2.
