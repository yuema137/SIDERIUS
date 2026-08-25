# C12-P-P — Composed Prompt Contamination Closure

**Status: PREPARATION COMPLETE. NOTHING IMPLEMENTED IN PRODUCTION.**
Branch `c12pp-prompt-contamination`, based on landed master `c991d6f6`.
Operator ruling 2026-08-24. Not pushed, not merged, no Gate launched.

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
