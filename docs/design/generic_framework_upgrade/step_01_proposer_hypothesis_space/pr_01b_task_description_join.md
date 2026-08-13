# PR 01b — Task-description JOIN (Step 01, child 2 of 2)

## Status

**IMPLEMENTED — READY FOR OPERATOR REVIEW (2026-08-12). NOT MERGED.**

Implementation complete on
`feat/generic-framework-step-01b-task-description-join`. Final
EXECUTABLE head `6b259b93`; commits `a7ffcccf` (S1-C), `e67b4651`
(S1-C2), `5dee6c4a` (S1-E), `6b259b93` (S1-F). CP1/CP2/CP3, Checkpoint
C, Gate 1 and Gate 2 all PASS; terminal suite 8540 passed / 3 skipped;
ruff clean. The live implementation ledger is §14-§17; acceptance is
§11. The design below is the frozen contract it was implemented
against, preserved unchanged.

---

**FROZEN / OPERATOR APPROVED FOR IMPLEMENTATION (2026-08-13).**

The operator approved the freeze subject to one documentation-only
reconciliation (the S1-C golden-ownership wording, §4.1), which is
applied here. APPROVED as frozen: the checkpoint ladder (§9), Gate 1
(§7), Gate 2 (§8), the Evidence Economy policy (§10), OD-S1-9(b)
(§3.3), S1-E's guard widening (§3.2/§4.3), and every F1-F10 invariant
(§0). No further broad design audit is required.

**Implementation is authorized but must NOT begin in the design
session.** It starts in a NEW, fresh implementation context using the
filled Implementation Working Rules contract and Context Continuity v2,
and the implementation handoff is initialized only after this frozen
design is the authoritative repository state.

Revision 2 applied the operator design review of 2026-08-13:
**OD-S1-9 decided (option (b))**; premature implementation detail
relaxed (§0); a real **Gate 1 / Gate 2** ladder added from the
repository's own gate standard (§7, §8); the checkpoint ladder made
explicit and blocking (§9); acceptance criteria re-ordered (§11); an
**Evidence Economy** section added under the frozen test-economy
principle (§10); and a focused adversarial review recorded (§12).

Prerequisite satisfied: **PR 01a is MERGED** (PR #199, merge commit
`39f89f52`); post-merge status sync `aec6db05`. Parent design (audit,
authority map, baselines, packs, golden policy, mutation catalogue):
`../step_01_proposer_hypothesis_space.md`.

This PR carries the **one operator-authorized intentional change to
default TIDMAD prompt bytes** in Step 01 (OD-S1-8). It is deliberately
isolated from PR 01a so that a reviewer never has to separate
"behaviour-preserving extraction" from "we changed what the agent
sees" inside one diff.

## 0. What this design FREEZES vs what it leaves to implementation

The operator review flagged that revision 1 froze code structure before
implementation had re-read the live source. This section is normative:
anything not listed as FROZEN is an implementation-time decision, and
implementation may choose freely among equivalent forms **provided the
frozen property is demonstrably proven**.

**FROZEN — may not change without a new operator decision:**

| # | Frozen item |
|---|---|
| F1 | Observable behaviour: the shipped task description reaches all THREE pipeline stage SYSTEM prompts, in both `explore` and `exploit` modes |
| F2 | Empty description ⇒ the block collapses to `""`, leaving no orphan label |
| F3 | ONE label authority — the label text is defined in exactly one place, not duplicated per template |
| F4 | No duplicate dead key survives (OD-S1-9) |
| F5 | Authority/ownership: `configs/task_config.yaml` via `load_task_config()` stays the only description authority; this PR creates none |
| F6 | Affected prompt surfaces: the three pipeline stage SYSTEM prompts only. USER prompts, `label=` values, `components=` key sets, stage order, retry/parse/persistence behaviour unchanged |
| F7 | Expected golden-change sets: **R2** = the six `pb3_*_system.txt` (S1-C); **R3** = the newly-captured legacy-reasoning SYSTEM golden + any `pb3_causal_*_system.txt` touched (S1-E). No other golden changes anywhere in the PR |
| F8 | Validation PROPERTIES (§4 per commit) and mutation INTENT (§4, §10) |
| F9 | Gate ladder and its stop conditions (§7, §8, §9) |
| F10 | Forward-contract rendering is NOT expanded to stages 1-2 (parent §8.3 defers it) |

**IMPLEMENTATION-TIME — decide after re-reading the live source, then
record the decision and why:**

- exact helper decomposition (reuse `_render_task_background` with an
  empty contract, give it an optional-contract form, or add a thin
  sibling — all three can satisfy F2/F3);
- exact placeholder name and its position within each template;
- exact test-file placement (new module vs a class in an existing one);
- exact assertion implementation where several equivalent forms prove
  the same property (e.g. how "no unsubstituted placeholder survives"
  is expressed as a regex or a scan);
- exact local command shape, which may drift with the source;
- incidental line numbers — the citations in this document are dated
  evidence, not addresses to code against.

## Source-audit baseline (mechanical, 2026-08-13, verified at `aec6db05`)

Line numbers are **evidence as of this date**, not frozen addresses.

| Fact | Evidence |
|---|---|
| The dead key exists and is transported | `ml_model_proposal_agent.py:1708` — `"task_description": inp.task_description` in the pipeline `template_vars` |
| NO proposal template consumes it | `grep -rn task_description agent/prompt_templates/` returns only `literature_review/` hits (a DIFFERENT, live surface); zero under `proposal/` |
| Substitution is literal and case-sensitive | `agent/prompt_templates/proposal/__init__.py:76` — `prompt.replace(f"{{{key}}}", str(value))` |
| Production always supplies a description | workflow `model_exploration.py:2290`; standalone CLI since PR 01a (`ml_model_proposal_agent.py:2287`) |
| A labelled block + renderer ALREADY exist for the legacy path | `PROPOSAL_REASONING_PROMPT` carries `{TASK_BACKGROUND}` at `:290`; `_render_task_background` at `:400`; substituted at `:441` |
| That renderer already collapses to `""` | `_render_task_background` returns `""` when the description is empty AND `fc.is_empty()` (`:417`) |
| …and already renders description-only, contract-free | **`test_proposer_task_config.py:99`** — `_render_task_background("solo task", ForwardContract())` yields the label + bullet with `"[B," not in block`. This is exactly the shape F1-F3 need, already pinned |
| Affected goldens under OD-S1-3(a) | the six `pb3_{comparison,causal,proposing}_{explore,exploit}_system.txt` |
| The legacy reasoning SYSTEM render has NO golden | only behavioural asserts (`test_proposer_task_config.py:107-120`); no `pb0_*` in `goldens/` — hence S1-E is capture-first |
| Gate entry points exist | `sdsc_submission_scripts/run_one_iteration.py` — `--is_pseudo_training:1328`, `--is_pseudo_llm:1320`, `--llm_config:1020`, `--debug_dump_prompts:1306`, `--data_scope:1056`, `--health_gate_files:1078` |
| Chain gate flags are really parsed | `_chain_common.sh` parses `--no-force_formal_round`, `--data_scope`, `--health_gate_files`, `--llm_config`, `--trial_time_budget_minutes`, `--formal_time_budget_minutes`, `--max_rounds`, `--trial_portion`, `--max_proposal_attempts`, `--debug_dump_prompts` |
| The gate LLM config exists and is per-stage | **`llm_configs/openai_tiered_pro.json`** (mechanically verified 2026-08-13: exists, 865 B, valid JSON) — `propose.comparison` / `propose.reasoning` / `propose.proposing` all `openai/gpt-5.5`, plus `interpret`, `implement`, `validate`, `tune.planner`, `tune.reflector` → every role Gate 1 and Gate 2 exercise is defined, and **all three JOIN surfaces are exercised by real top-tier models** |

## 1. Final effect of THIS PR

**The production proposer actually reads the shipped task
description.** Today the pipeline path — the standard production path —
renders no task description at all: the transported value is supplied
to `template_vars` and consumed by NO template (a live dead key
catalogued by roadmap §0 rule 8; assigned to Step 01 by the Step-00
coverage manifest, step_00 design §15.2).

After this PR the declared task background reaches all three pipeline
stage system prompts (OD-S1-3(a) — the comparison and causal stages are
exactly where the architecture family is chosen, so leaving them
task-blind would satisfy the letter of the JOIN and miss its point).

**This is NOT extraction parity.** It is an intentional, reviewable
behaviour change with declared golden regeneration.

Scope honesty, carried from PR 01a §1: this PR changes what the agent
READS. It does not make SIDERIUS execute a non-TIDMAD task, and it adds
no validation of the description's content.

## 2. Scope

OWNS: the JOIN itself (all three stages); the task-description contrast
(fixture **13.4-A** / rung **FX-1**); golden regeneration **R2**; the
stale budget-literal cleanup (OD-S1-2) as an isolated, droppable commit
with capture-first governance (**R3**); **Checkpoint C**; **Gate 1**;
**Gate 2**; the Step-01 aggregate closeout and roadmap sync.

Does NOT own: anything merged in PR 01a; any new authority; any
Step-02/03 contract semantics; forward-contract expansion to stages 1-2
(F10); FX-3/FX-4 (parent §6A.5).

**Terminology note on the generic checklist template.** The standard
template asks for `file_order` / `shuffle` / visited-sample-sequence
criteria. Those belong to a dataset-ordering feature and have **no
counterpart here** — this PR reaches no dataset, sampler or RNG. The
equivalent obligation is **render determinism and placement**: the
block appears at a fixed position, exactly once per surface, byte-stable
across processes. §11 pins that instead.

## 3. Source findings that shape the plan

### 3.1 FINDING — an in-code comment documents a placeholder that cannot work

The comment beside the dead key states that `{TASK_DESCRIPTION}` "is
rendered into any future template that wants the bare task string".
It cannot be: `load_stage_prompt` builds `f"{{{key}}}"` from the
**lowercase** key, so an UPPERCASE placeholder in a proposal stage
template would never substitute and would ship to the LLM as a literal
brace token. (The uppercase form IS correct for the `literature_review`
module, which does its own explicit replace — a different surface; the
comment appears to have imported that convention by analogy.)

Consequence: an implementer following the comment produces a visibly
broken prompt. The comment is corrected in the commit that wires the
block, and the JOIN evidence must prove **no unsubstituted placeholder
token survives** — not merely that the description is present.

### 3.2 FINDING — the contamination guard cannot see one of S1-E's two targets

`test_prompt_ceiling_policy.py`'s scan set is built from
`PROPOSAL_COMMIT_PROMPT` plus every `*.md` in the proposal template
directory. It does **not** include `PROPOSAL_REASONING_PROMPT`, where
the `~100M` literal lives. And the stale-VRAM pin matches the exact
string `<10 GB VRAM`, while the surviving literal reads "the 10 GB VRAM
budget" — no `<`.

Both literals survive **because the guards cannot reach them**.
Deleting the text without widening the guards leaves the blind spot
open and gives the commit no test that fails if the literals return.
S1-E therefore widens the guards and observes them RED **before**
deleting. Operator review accepted this reasoning (review item 5).

### 3.3 OD-S1-9 — RESOLVED: option (b) APPROVED (operator, 2026-08-13)

> The invariant is semantic: the existing transported task-description
> authority must become a LIVE consumed prompt channel — not: a
> particular dictionary key must survive forever.

Approved shape: a rendered task-background block, reusing the existing
in-tree pattern where the source audit supports it. The bare
`task_description` key is not preserved merely to preserve a key name.

Preserved requirements: F1 (all three stages), F2 (empty collapse), F3
(one label authority), F4 (no duplicate dead key). Parent §8.3's "WIRE,
not REMOVE" wording has been amended to state the semantic requirement
(done in this revision).

**Consequence for evidence (§10):** because the approved shape reuses
the existing renderer, F2 and the description-only/contract-free shape
are **already pinned** by `test_proposer_task_config.py:87` and `:99`.
New unit tests for those two properties would be duplicates and are
therefore **not** planned.

## 4. Implementation phases (per-commit checklists)

Standing rules: parent §18.1, plus the frozen **test-economy principle**
(§10): validate by risk and unique evidence value, narrowest sufficient
first, ONE terminal full suite at the final executable head.

Order and why: the JOIN (`S1-C`) precedes its contrast (`S1-C2`), which
asserts against a block that must exist. `S1-E` is independent and last
among code commits so it stays droppable. Gates run on the assembled
executable head, after all code commits.

| # | Commit | Kind | Rendered TIDMAD bytes? |
|---|---|---|---|
| 1 | `S1-C` — the JOIN | production + goldens | **YES** (declared, R2) |
| 2 | `S1-C2` — fixture 13.4-A / rung FX-1 | test-only | no |
| 3 | `S1-E` — budget-literal cleanup | production + goldens | **YES** (declared, R3) |
| 4 | `S1-CP` — Checkpoint C + Gate 1 + Gate 2 evidence | evidence + docs | no |
| 5 | `S1-F` — docs closeout | docs-only | no |

---

### 4.1 Commit S1-C — the JOIN

**1. Goal.** Close the audited dead seam: the production pipeline
renders the shipped task description into all three stage SYSTEM
prompts, so the stages that choose the architecture family are no
longer task-blind. This is the MANDATORY-scope intentional
rendered-byte change, authorized by OD-S1-8.

It is its own commit because this PR contains **two independent
intentional golden changes, and they must never share a diff**:

| Commit | Golden event | Status |
|---|---|---|
| **S1-C** (this one) | **R2** — the six `pb3_*_system.txt`, caused by the JOIN | mandatory |
| **S1-E** | **R3** — the newly-captured legacy-reasoning SYSTEM golden plus any `pb3_causal_*_system.txt` touched by the literal edit | separate and independently DROPPABLE |

Bundling S1-C with the contrast tests or with S1-E would force a
reviewer to separate two unrelated kinds of golden change inside one
diff — the failure mode the 01a/01b split exists to prevent, and the
reason S1-E stays droppable without disturbing the JOIN.

*(Wording corrected at operator design freeze, 2026-08-13: an earlier
draft called S1-C "the ONLY commit whose golden diff is intentional",
which contradicted S1-E's deliberate R3 event recorded in F7 and §4.3.
Documentation only — no scope or implementation change.)*

**2. Scope.**
Changes: the proposer node's pipeline `template_vars` wiring and the
stale comment (§3.1); a description-only task-background rendering path
(shape = implementation-time, per §0); the three stage base templates;
the six `pb3_*_system.txt` goldens; the JOIN tests.

Unchanged (F6): the three `pb3_*_user.txt` goldens; the WF-3
component-key-set golden; PB-4 and all CFG goldens; the legacy
reasoning path, which already renders the description; stage `label=`
values, stage order, retry/correction, parsing, candidate minting,
persistence.

Depends on: PR 01a merged. Nothing later in this PR.

**3. Implementation plan.**
- [x] Re-read the existing task-background renderer and BOTH its call
      sites before writing anything; choose the reuse shape and record
      which and why (§0 implementation-time). → **thin sibling**
      `_render_pipeline_task_background`, §14.1 decision D1.
- [x] Wire a description-only block into the pipeline `template_vars`
      per OD-S1-9(b), satisfying F2/F3/F4. → the dead `"task_description"`
      key is REPLACED by `"task_background_block"`; no second transport
      survives.
- [x] Correct the stale `{TASK_DESCRIPTION}` comment (§3.1).
- [x] Add the placeholder to all three stage base templates at a fixed,
      reviewed position; confirm from the WF-3 component audit that the
      position falls inside the `system_prompt` component. → placed
      immediately before `## Your task` in each base template;
      `wf3_proposer_components_key_sets.json` unchanged (§14.2).
- [x] Regenerate exactly the six R2 goldens IN THIS COMMIT with §13
      rule-2 provenance; attach before/after diffs. → `git diff --stat`
      over the golden directory lists exactly those six, `3 +++` each.
- [x] JOIN evidence at the boundary (properties in §4 below). → new
      module `tests/unit/agent/ml_model_proposal_agent/
      test_step01b_task_description_join.py`.
- [x] Attributability check (adversarial finding A6): demonstrate
      mechanically that each regenerated golden equals the OLD golden
      plus the inserted block — nothing else rode along. → §14.3, all
      six `attributable=True`.
- [x] Workflow-tier pseudo assert: inspect first whether an existing
      dual-mode test already captures the proposer prompt and can take
      one added assert, before adding a new bounded test. → inspect-first
      performed; result and bounded deviation in §14.4.
- [x] Fill §5 prompt-delta accounting with measured bytes.

**4. Validation plan — properties, not implementations.**

Unit (targeted; the inner loop is the proposer package, not the suite):
- the SHIPPED description (loaded via the config authority, never a
  literal copy) is present in **each of the three** stage system
  prompts, in **both** modes — six captures, asserted per stage so a
  single missing stage cannot hide (adversarial finding A7);
- the block appears **exactly once** per surface;
- **no unsubstituted placeholder token survives** in any rendered stage
  prompt (§3.1);
- byte-stability across two fresh processes;
- the six regenerated goldens re-assert byte-equality.

NOT planned, because already covered (§10 de-duplication): empty-
description collapse and the description-only/contract-free block shape
— pinned by `test_proposer_task_config.py:87` and `:99`.

Negative/invalid input:
- a description containing brace-like tokens must not corrupt other
  substitutions (the substitution loop is sequential `str.replace`, so
  a value containing another key's placeholder text is a genuine, if
  unlikely, ordering hazard).

Backward-compatibility/default-parity: the three USER goldens, the WF-3
key-set golden, PB-4 and all CFG goldens byte-identical; the ceiling and
banned-vocabulary guards still green (the JOIN injects shipped prose
into surfaces they scan).

Mutations (parent §15): **M-1** (remove the placeholder from ONE stage
template) must red both the JOIN evidence for that stage and its
golden; **M-6** (disable the workflow post-hoc injection) must red the
workflow-tier assert.

Real-training Gate: **none in this commit.** Gates run once on the
assembled head (§7, §8).

**5. Acceptance criteria (observable).**
- The shipped description appears byte-for-byte in all six stage-system
  captures (3 stages × 2 modes), asserted per stage.
- Count == 1 per surface (not "is present").
- Zero unsubstituted placeholder tokens in all six.
- Exactly six golden FILES differ in the commit; `git diff --stat` over
  the golden directories lists those six and nothing else.
- Each regenerated golden is reconstructible as old-golden + inserted
  block (no incidental reflow, no smuggled edit).
- Two fresh interpreters produce byte-identical renders.
- M-1 red on the affected stage's evidence AND its golden; M-6 red on
  the workflow assert; both restored green.

**6. Failure and edge cases.**

| Case | Required handling |
|---|---|
| Empty description (test fixtures only; never production after PR 01a) | collapse to `""`; **safe fallback**, already pinned |
| Whitespace-only description | decide and pin explicitly; must not emit a label over blank space |
| Description containing brace tokens | must not corrupt other substitutions; **pinned**. If sequential replace makes this genuinely unsafe, STOP and report — do not sanitise the shipped config |
| A new `components` key appears in WF-3 | **STOP** — the block landed outside the `system_prompt` component; design failure, not a regeneration |
| A golden outside the declared six changes | **STOP** — parent §13 rule 1: fix the code, never the golden |
| A regenerated golden is not reconstructible as old+block | **STOP** — an unrelated change is riding along inside a declared regeneration |
| Prompt-size growth trips a ceiling guard | record the measurement and **STOP**; never raise a ceiling to fit the block |

**7. Verification commands and evidence.**
Targeted proposer-package evidence plus the two guard files; commands
recorded at execution (shapes may drift — §0). Record counts, wall
time, the six golden diffs, the attributability proof, and the M-1/M-6
dossier rows. Any test that could not be run is recorded with the
reason — never claimed as passed. **No full-suite run in this commit**
(§10.A) unless targeted evidence shows an unbounded blast radius, in
which case the reason is recorded.

**8. Commit boundary.** Independently reviewable: templates, wiring,
goldens, diffs and evidence all inside. No contrast fixtures, no
literal cleanup, no docs closeout. Before committing: stop and show the
diff summary, staged file list, test output, and any deviation.

---

### 4.2 Commit S1-C2 — fixture 13.4-A / rung FX-1 (description axis)

**1. Goal.** Prove the description CHANNEL is real: swapping only the
description changes only the description-derived block, and no
SQUID-specific text hides inside that block. Byte-equality on the
shipped profile cannot distinguish "renders the declared description"
from "happens to contain TIDMAD prose".

Separate from S1-C because it is test-only and adds no golden churn; it
is the description-axis twin of PR 01a's B-i/B-ii/FX-2/FX-5 rungs and
completes the roadmap's 13.4-A/13.4-B pair.

**2. Scope.** One contrast fixture using the in-tree alternative
description string (`test_planner_prompt_task_config.py:32`). Placement
= implementation-time. No production change, no golden change.
Depends on S1-C.

**3. Implementation plan.**
- [x] Build the 13.4-A fixture: alternative description, SHIPPED
      ForwardContract UNCHANGED — one axis only. → new module
      `test_step01b_description_axis_contrast.py`; the in-tree `_ALT_TD`
      is imported from `test_planner_prompt_task_config.py`, and the
      contract is read from `load_task_config()` and passed IDENTICALLY
      to both variants.
- [x] Assert the alternative text reaches the task-background block of
      all three stage system prompts. → plus the displacement half (the
      shipped description must be ABSENT), which is what fails when the
      channel is a constant rather than a live read.
- [x] Assert ZERO SQUID residue **inside the description-derived block
      only** — not the whole prompt (contract prose legitimately still
      says "denoising classes" because the CONTRACT is still TIDMAD's;
      parent §9.1 and the §9.5 whitelist discipline).
- [x] Assert contract-derived tokens are byte-identical to the
      TIDMAD-description variant of the same render (axis isolation). →
      implemented in the STRONGEST available form (§14.7).

**4. Validation plan.** Targeted unit only. Mutation: reintroduce a
hardcoded SQUID phrase into the block rendering → 13.4-A red while
every shipped-profile golden stays green (the description-axis analogue
of PR 01a's N-RESIDUE). No integration, no Gate.

**5. Acceptance criteria.**
- The alternative description present in all three stage system prompts
  under the alt fixture; the shipped description absent from them.
- The named SQUID tokens absent from the description-derived block;
  explicitly NOT asserted against the whole prompt.
- Contract-derived tokens identical across the two description variants.
- The SQUID-contamination mutation reds 13.4-A and leaves goldens
  green; restored green.

**6. Failure and edge cases.**
- A whole-prompt residue assertion is **unsatisfiable** by design — the
  TIDMAD contract prose is still there. Writing it that way is the
  mistake this criterion exists to prevent.
- If the block cannot be located for scoping, S1-C chose an unstable
  placement — **STOP** and fix S1-C rather than loosening the assert.

**7. Verification commands and evidence.** Targeted proposer tests;
record counts, wall time, mutation row.

**8. Commit boundary.** Test-only; no production or golden diff.

---

### 4.3 Commit S1-E — stale budget-literal cleanup (capture-first, DROPPABLE)

**1. Goal.** Delete the two stale numeral budget literals so the
proposer defers to the `[HARDWARE CONTEXT]` effective cap (roadmap §14
resolved row), and close the two guard blind spots (§3.2) that let them
survive. Without the guard work the deletion has no test that fails if
the literals return.

Its own commit because OD-S1-2 requires it isolated and skippable, and
because it regenerates a DIFFERENT golden set (R3) for a different
reason.

**2. Scope.** The two literals (one in the legacy reasoning prompt
constant, one in the causal stage template — re-read the surrounding
sentence before editing; the fix may be rewording the devil's-advocate
EXAMPLE rather than deleting a clause); the contamination guard's scan
set and VRAM pattern; a NEW captured golden for the legacy reasoning
SYSTEM render; any `pb3_causal_*_system.txt` affected by the template
edit.

Unchanged: the VRAM-limit REQUIREMENT itself (deterministic capacity
guidance is legitimate and stays); the JOIN block from S1-C.

Depends on nothing in this PR; ordered last among code commits so it
can be dropped without disturbing S1-C/S1-C2.

**3. Implementation plan.**
- [x] **CAPTURE FIRST** — add a Step-01 golden for the legacy reasoning
      SYSTEM render BEFORE editing the literal. It has no oracle today;
      editing first would change an unpinned surface. → captured at
      3642 bytes, sha256 `bb8e974b88a98e4b7b1d543002eec3e51a8742bded2043711cdce87914a7ff41`,
      with the `~100M` literal still present in it (§16.2).
- [x] Widen the guard scan set to include the legacy reasoning constant
      and generalise the VRAM pin beyond the exact `<10 GB VRAM`
      string; **observe RED** against the current literals before
      deleting anything. → RED observed, naming BOTH literals (§16.2).
- [x] Delete/repoint the two literals.
- [x] Regenerate the just-captured golden and any affected `pb3_*`
      golden in the SAME commit, with §13 R3 provenance. → exactly three
      files; every diff shows only the literal's removal (§16.3).
- [x] Re-run the widened guards → green.

**4. Validation plan.** Targeted unit plus the widened guards.
Negative: the generalised pattern must NOT fire on legitimate text —
specifically not on the VRAM-limit requirement sentence, not on the
fixture-supplied `constraints=["VRAM < 10 GB"]` strings used across the
proposer tests (those are TEST INPUTS, not template literals), and
**not on the task description S1-C newly injects** (adversarial finding
A9 — the shipped description contains numerals such as `256`). No Gate.

**5. Acceptance criteria.**
- No numeral parameter-count or VRAM budget literal remains in any
  proposer prompt surface, including the legacy reasoning constant.
- The widened guard was observed RED before deletion and GREEN after —
  both recorded.
- The legacy reasoning SYSTEM golden exists, was captured BEFORE the
  edit, and its regeneration diff shows only the literal's removal.
- The VRAM-limit requirement sentence is intact.
- Only R3's declared goldens changed.
- The widened pattern does not fire on S1-C's injected description.

**6. Failure and edge cases.**
- Capture-after-edit ⇒ the golden pins the already-changed surface and
  proves nothing. **Ordering is an acceptance criterion**, not a
  nicety.
- Over-broad pattern reddening fixtures or the JOIN block → narrow the
  pattern to template texts and budget contexts; do not edit fixtures
  and do not touch the JOIN.
- If the causal sentence cannot be reworded without losing the
  devil's-advocate example's point, **STOP and ask** — prompt-quality
  judgement, not a mechanical edit.

**7. Verification commands and evidence.** Record the RED output, the
GREEN output, counts, wall time, golden diffs.

**8. Commit boundary.** Isolated, clearly labelled, droppable without
touching the JOIN (re-verified in §12 A9).

---

### 4.4 Commit S1-CP — Checkpoint C + Gate 1 + Gate 2 evidence

**1. Goal.** Carry the three escalating production-boundary evidences
(§6, §7, §8) and record them. Evidence + ledger only; no production
change. Runs on the assembled executable head, after all code commits.

**2-8.** Per-gate specifications live in §6/§7/§8 rather than being
duplicated here; this commit's boundary is "evidence recorded, nothing
executable changed". If any gate demands an executable fix, the fix
lands as its own commit and the gate is re-run on the new head — the
gate evidence must name the exact HEAD it ran on (§11).

---

### 4.5 Commit S1-F — docs closeout + PR readiness

**1. Goal.** Leave the ledger and operator-facing docs true.

**2. Scope.** This document (every box `[x]` with evidence or
explicitly deferred with a reason); the node doc
`nodes/ml_model_proposal_agent/ml_model_proposal_agent.md` (prompt-
surface documentation updated for the JOIN, per the pre-merge doc-sync
rule); parent §16 checkpoint table; folder README / roadmap rows.
Docs-only.

**3. Implementation plan.**
- [ ] Reconcile every checklist box with recorded evidence.
- [ ] Update the node `.md`, quote-verifying each documented flag and
      default against the merged source.
- [ ] Fill §5 prompt-delta accounting.
- [ ] Fill the parent §16 checkpoint table (Checkpoint C closed here;
      Checkpoint A was closed by PR 01a).
- [ ] **Terminal validation, ONCE** at the final executable head from a
      CLEAN tree (§10.A); verdict read from the log, never a wrapper's
      exit status.

**4. Validation plan.** Full `pytest tests/unit/ -m "not real_run"`,
`ruff check`, `ruff format --check`; pyright **in CI only** (Node
v10.19.0 cannot bootstrap pyright locally — recorded as not locally
validated, never as green).

**5. Acceptance criteria.** Every `[ ]` resolved or explicitly deferred
with a reason; full-suite result recorded with pytest's own exit code
and log path; ruff clean; CI green on the EXACT final head; clean tree;
**PR READY FOR OPERATOR REVIEW — never merged autonomously.**

**6. Failure and edge cases.** A stale ledger at the final head is a
defect in its own right — the PR-01a merge gate caught exactly that.
Record CI state in the ledger and re-verify CI on the resulting head
rather than withholding it.

**7-8.** Recorded at execution; docs-only boundary.

## 5. Prompt-delta accounting (MEASURED at S1-C, HEAD `f223956d` + working tree)

| Field | Value |
|---|---|
| files/goldens changed | exactly the six R2 goldens: `pb3_{comparison,causal,proposing}_{explore,exploit}_system.txt`. `git diff --stat` over `tests/unit/agent/ml_model_proposal_agent/goldens/` lists those six and nothing else, `3 +++` each (18 insertions, 0 deletions) |
| added bytes — GOLDEN fixture render | **+86 bytes on every one of the six**, from the test-owned fixture description (`"Step-00 fixture task: denoise a synthetic 1-D int8 series."`). Identical on all six because the block is description-only and stage-independent |
| added bytes — PRODUCTION (shipped description) | **+262 chars / +262 UTF-8 bytes** on every stage system prompt. Shipped description = 234 chars over 4 lines; block = label + bullet + one blank line. Relative growth: comparison +2.87 % (explore) / +2.90 % (exploit); causal +2.56 % / +2.61 %; proposing +1.69 % / +1.68 % |
| token delta | **token count unavailable — bytes/characters recorded instead.** No trustworthy local tokenizer is already available and the design forbids adding a dependency for this |
| why intentional | closes the audited dead seam (roadmap §0 rule 8): the transported `task_description` had NO consuming template on the production pipeline path, so the two stages that choose the architecture family were task-blind. OD-S1-8 authorizes this one rendered-byte change |
| unchanged surfaces | CONFIRMED: the three `pb3_*_user.txt` USER goldens byte-identical; `wf3_proposer_components_key_sets.json` byte-identical (the block lands inside the existing `system_prompt` component, introducing no key); `pb4_legacy_commit_{system,user}.txt` byte-identical; all CFG goldens untouched; stage `label=` values and stage order unchanged (the JOIN tests re-assert the exact `proposer.comparison → proposer.causal_reasoning → proposer.proposing` label sequence) |
| ceiling / guard headroom | `test_prompt_ceiling_policy.py` green unmodified after the JOIN — no ceiling was raised (§4.1 failure table) |

## 6. Checkpoint C — production-entry pseudo evidence (PRE-MERGE)

Per OD-S1-4, every "post-merge chain evidence" formulation is
superseded.

- **Boundary exercised**: the real production entry
  (`run_one_iteration.py`) → real workflow → real proposer renders,
  with a stub LLM bridge.
- **Cost class**: `--is_pseudo_llm`; **no real LLM, no GPU, no API
  cost**.
- **Unique failure class**: harness-vs-production divergence — the unit
  tier drives `MLModelProposalAgent.run()` directly, so it cannot catch
  a workflow/entry-point wiring defect that leaves the description
  unset in a real invocation.
- **PASS**: the run completes; the dumped proposing-stage system prompt
  contains the shipped description and the derived contract tokens.
- **FAIL/STOP**: dump absent (flag plumbing regressed) or description
  absent while unit tests are green (production entry diverges from the
  harness — a blocker, and exactly what this checkpoint exists to
  detect).
- **Artifacts**: the run log and the prompt dump, attached, with the
  exact HEAD recorded.
- **Known coverage limit** (F11, re-verified): the dump hook writes
  ONLY the proposing-stage system prompt while OD-S1-3(a) places the
  block in all three. The workflow-tier capture and the S1-C goldens
  cover the other two. Accepted, recorded, not glossed.
- **When**: pre-merge, on the final executable head, before Gate 1.

## 7a. Gate LLM configuration — `openai_tiered_pro.json` (operator amendment, 2026-08-13)

**Both gates use `--llm_config llm_configs/openai_tiered_pro.json`.**

Standing SIDERIUS policy is to use the `pro` config explicitly for
formal/official production campaigns rather than relying on or
substituting `openai_tiered_v1`. PR-01b's Gate 1 and Gate 2 are
**official pre-merge production validation**, so they take the `pro`
config.

Mechanical verification performed before this amendment (2026-08-13):

| Check | Result |
|---|---|
| file exists / parses | YES — `llm_configs/openai_tiered_pro.json`, 865 bytes, valid JSON |
| proposer stages exercised by the JOIN | `propose.comparison`, `propose.reasoning`, `propose.proposing` — **all present, all `openai/gpt-5.5`** |
| other roles Gate 1 / Gate 2 traverse | `interpret`, `implement`, `validate`, `tune.planner`, `tune.reflector` — all present |
| new provider dependency introduced? | NO — `lit_review.*` is `deepseek/deepseek-v4-pro` in BOTH configs, and lit review is not forced on (`--ml_lit_review_enabled` defaults to unset) |

Effect on the Gate-1 rationale: **strengthened, not weakened.** Under
`v1`, `propose.comparison` ran on `gpt-5.4-mini`; under `pro` all three
JOIN surfaces run on the same top-tier model, so the gate exercises the
enlarged prompts uniformly.

**Honest cost note (no budget change authorized or made).** The
budget figures quoted in §7/§8 come from
`docs/gates/gate_testing_standard.md`, which derived them with
`openai_tiered_v1` (a mixed 5.4 / mini / nano tiering). `pro` is
uniformly `gpt-5.5`, so ACTUAL cost may exceed those estimates. The
figures are left unchanged because this amendment is config-only and
changing budgets was explicitly excluded; the deviation is recorded
here so the eventual gate evidence can be compared against a stated
expectation rather than a silently stale one.

**Relationship to the gate standard.** `docs/gates/gate_testing_standard.md`
still names `openai_tiered_v1.json` as mandatory. That document is NOT
edited by this PR — amending a repository-wide standard is outside PR
01b's scope. For this PR the operator's production-validation policy
governs; if the standard should be updated repo-wide, that is a
separate change with its own approval.

## 7. Gate 1 — real LLM + pseudo training

Instantiated from `docs/gates/gate_testing_standard.md` "Gate 1 — Real
LLM + pseudo training", and following the direct in-repo precedent:
`enable_global_task_config` T3 (the same class of change — task-config
text reaching the proposer prompt) assigned exactly this gate ("Real
proposer LLM call → real implementor LLM call → dummy-tensor check,
with `task_config.yaml` present"). The standard's assignment table also
routes "New LLM-facing system prompt → Gate 1" and "Prompt placeholder
substitution → Unit only + optional Gate 1". This PR is both, so Gate 1
is **required, not optional**.

| Field | Value |
|---|---|
| **Unique failure class** | Every layer below uses a canned/stub bridge, so none can answer: *does a REAL model, given the enlarged and re-framed system prompts, still return schema-valid output?* A JOIN that renders perfectly can still degrade the contract — e.g. the added task framing competes with the JSON instructions, or the three-stage handoff breaks because stage 1's output shifts. Only a real LLM call surfaces that. |
| **Boundary exercised** | Production entry → real workflow → interpretation → **all three real proposer stage calls** → implementor → validator dummy-tensor check. Note the tiered config assigns real models to `propose.comparison`, `propose.reasoning` and `propose.proposing`, so **all three JOIN surfaces get a real model** — this gate is unusually well matched to this PR. |
| **Uses** | Real LLM: YES (**`llm_configs/openai_tiered_pro.json`** — official production-validation config, §7a). Real training: NO (`--is_pseudo_training`, dummy-tensor check only). GPU: none required. |
| **Budget** | Standard's estimate ~2-5 min, ~$0.05-0.20. Bounded to ONE iteration. |
| **Inputs/profile** | Shipped `configs/task_config.yaml` (the whole point is the shipped description); cold-start (no `--seed_paths`, per the operator rule); `--debug_dump_prompts` on, so the real-LLM run also yields a prompt dump. |
| **PASS** | (1) all LLM calls complete without error; (2) every stage output passes Pydantic validation; (3) the proposal reaches the implementor and the generated code compiles + passes the dummy-tensor check; (4) the dumped proposing-stage prompt contains the shipped description. |
| **FAIL / STOP** | Schema-validation failure attributable to the prompt change, a stage-handoff break, or repeated proposal rejection → **diagnose before Gate 2**; do not "try Gate 2 anyway". A failure here means the JOIN changed model behaviour in a way no unit test models. |
| **Artifacts** | Run log, prompt dump, the validated proposal JSON, exact HEAD SHA. |
| **Why sufficient, not broader** | It answers the one question unit evidence cannot (real-model structural validity under the new prompts) at the cheapest tier that can ask it. It deliberately does NOT train — training cannot fail *because of* a prompt wording change except through the proposal, which this gate already validates. |
| **When** | Pre-merge, after Checkpoint C, on the final executable head. |
| **vs Checkpoint C** | Checkpoint C proves the description REACHES the boundary through the production entry (stub bridge, free). Gate 1 proves a real model still behaves correctly when it does. Different questions; neither replaces the other. |
| **Approval** | Real-LLM cost ⇒ **operator approval required before launch** (standard §Gate 1). Not launched during design. |

## 8. Gate 2 — real LLM + real training (smoke)

The standard's assignment table routes "Checkpoint (end of feature) →
Gate 2". PR 01b **is** the Step-01 feature checkpoint (it owns the
aggregate closeout), so Gate 2 applies.

| Field | Value |
|---|---|
| **Unique failure class** | Gate 1 validates ONE proposal's structure. Gate 2 asks whether the chain still COMPLETES end-to-end with the new prompts across iterations: the proposal must survive implementor → validator → real training → scoring, and iteration 2's proposer consumes iteration 1's real interpretation. A prompt change that shifts the proposal distribution toward exotic-but-schema-valid architectures would pass Gate 1 and fail here. That cross-node, cross-iteration consequence is unreachable from Gate 1. |
| **Boundary exercised** | Full chain, production entry, real LLM + real training. |
| **Uses** | Real LLM: YES (**`openai_tiered_pro.json`** — official production-validation config, §7a; `certify_minimal` remains forbidden, it cannot reliably pass the validator). Real training: YES (trial rounds only). GPU: yes, bounded. |
| **Plan chosen** | The **trial-only smoke** (`--no-force_formal_round`), NOT the Lite/Regular formal-round plans. Justification from the standard: "The trial-only smoke remains correct for features that don't touch the formal path", and Lite's forced formal round is "required when the feature under test must exercise real formal admission". **This PR touches no formal-admission logic** — it changes prompt text only. Choosing Lite would buy a formal round that tests nothing this PR can break. |
| **Scope/config** | Partial scope with the DS8-mandatory pairing (`--data_scope` + matching `--health_gate_files`), **cold-start — no `--seed_paths`** (operator rule 2026-07-27; pre-DS8 seeds cannot be admitted into a partial-scope run). Mandatory guards from the standard: `--trial_portion 0.02`, `--trial_time_budget_minutes 5`, `--formal_time_budget_minutes` as a safety net, `--llm_config llm_configs/openai_tiered_pro.json` (§7a). `--num_iterations 2`, `--max_rounds 2`, `--max_proposal_attempts 3`. `--debug_dump_prompts` on. Exact invocation assembled at execution from the standard (§0: command shapes may drift). |
| **Budget** | ~30-45 min, ~$1-1.5 (below the standard's $1.50-2.50 for the heavier plans, because no formal round runs). |
| **PASS** | The standard's HealthGate-framework criteria verbatim — chain exits 0; every round has a recorded `gate_action`; every `denoising_score` is finite OR `None`/`-inf` with a corresponding `INVALIDATE_ROUND`/`ABORT_CHAIN`; no phantom `5.5762667` accepted; at least one HealthGate evaluation fires. **Plus one PR-specific criterion**: the dumped proposing prompt from a real chain iteration contains the shipped description. |
| **NOT pass/fail** | Per the standard, explicitly: whether `denoising_score` beat baseline, whether the model learned to denoise, or any score threshold. This PR must not be judged on model quality. |
| **FAIL / STOP** | Chain does not complete, or proposals systematically fail validation in a way traceable to the prompt change → **the PR cannot reach READY FOR OPERATOR REVIEW**. A Gate 2 failure is never excused by green lower layers. If the failure is an LLM-quality artefact (standard's failure-handling section), verify the config and retry once, and record both attempts. |
| **Artifacts** | Chain log, per-round records, prompt dump, exact HEAD SHA, wall time, cost estimate. |
| **Why sufficient, not broader** | One bounded trial-only chain at 0.02 portions on a partial scope is the smallest run that exercises the multi-iteration LLM loop with real training. Rejected as unnecessary: forced formal round (no formal logic touched), full scope, Regular plan's larger portions, and any second chain. |
| **When** | Pre-merge, after Gate 1 passes, on the final executable head. |
| **Approval** | **Operator approval required before launch** (real LLM + training cost/time). Not launched during design. |

**Q2 DECIDED — Gate 2 is NOT waived (operator, 2026-08-13.)**
Approved exactly at the bounded trial-only shape designed above.
Operator rationale, recorded verbatim in substance: it has a distinct
failure class over Gate 1 (cross-node / cross-iteration chain
completion after a prompt change that may shift the proposal
distribution); PR 01b is also the Step-01 aggregate feature closeout;
and the designed shape is already the minimum sufficient vetted one.

**FROZEN Gate-2 shape — do not broaden merely because it is
available:**

| Frozen parameter | Value |
|---|---|
| chains | exactly ONE bounded trial-only chain |
| formal round | NONE — `--no-force_formal_round` |
| scope | partial, with matching `--health_gate_files` |
| seeds | cold start (no `--seed_paths`) |
| trial portion | 0.02 |
| iterations / rounds | 2 / 2 |
| retry | at most ONE, and only where the gate standard explicitly permits it for a DIAGNOSED transient LLM-quality failure (standard §"Failure handling"); both attempts recorded |

Any deviation from this table is a material deviation requiring a new
operator decision — not an implementation judgement call.

## 9. Checkpoint ladder (blocking)

Each rung must produce its evidence before the next begins. No later
gate may excuse an earlier failed invariant.

```text
S1-C  JOIN
  └─ CHECKPOINT 1: declared prompt/golden delta verified
       six goldens and no others; each reconstructible as old+block;
       zero surviving placeholders; M-1/M-6 red→restored
       FAIL ⇒ stop; do not start S1-C2
S1-C2 FX-1
  └─ CHECKPOINT 2: description-axis isolation verified
       alt text on all three stages; no SQUID residue in the block;
       contract tokens identical across variants
       FAIL ⇒ stop; the JOIN's placement or scoping is wrong
S1-E  literal cleanup (DROPPABLE)
  └─ CHECKPOINT 3: capture-first + guard RED→GREEN verified
       golden captured BEFORE the edit; widened guard observed red,
       then green; pattern does not fire on the JOIN block
       FAIL ⇒ drop S1-E entirely rather than weaken the guard
assembled executable head
  └─ CHECKPOINT C  (pseudo LLM, free)      FAIL ⇒ diagnose; no Gate 1
  └─ GATE 1        (real LLM, ~$0.2)       FAIL ⇒ diagnose; no Gate 2
  └─ GATE 2        (real LLM + training)   FAIL ⇒ NOT ready for review
terminal
  └─ ONE full unit suite + static + exact-head CI
```

## 10. Evidence economy (frozen operator principle, 2026-08-13)

> Test by RISK and UNIQUE EVIDENCE VALUE, not by code surface.

**A. Validation cadence.** Inner loop = directly affected tests →
affected package → focused integration/mutation → Gate 1 → Gate 2 →
**ONE** terminal full unit suite at the final executable head → static
/ exact-head CI. The full suite (~8-10 min, >8k tests) is a **terminal
compatibility gate, not an inner-loop default**; it is NOT run after
each semantic commit. An early broad run is permitted only when the
change is genuinely cross-cutting or targeted evidence shows an
unbounded blast radius — and the reason is recorded.

**B. Unique-failure-class rule.** No test is added merely because a
function lacks one. Each planned test above names a defect it alone can
catch. Implementation-shape pins (helper arity, private decomposition,
internal call structure) are avoided unless that shape IS a frozen
contract. The one shape-adjacent pin retained is the template-layer
placeholder check, justified as the anti-re-inlining guard — it catches
someone hardcoding the description back into a template, which every
golden would still pass.

**C. De-duplication already applied in this design.** Because OD-S1-9(b)
reuses the existing renderer, these are **NOT** planned as new tests:

| Property | Already covered by | Why no new test |
|---|---|---|
| empty description ⇒ `""` | `test_proposer_task_config.py:87` | identical assertion; a copy adds no failure class |
| description-only block, no contract text | `test_proposer_task_config.py:99` | exactly the F1/F3 shape, already pinned |
| `{TASK_BACKGROUND}` never survives the legacy render | `test_proposer_task_config.py:112` | the pipeline analogue IS new and IS planned; the legacy one is untouched |

**D. Retirement candidates (decide at implementation, not now).** Only
within the directly affected proposer test surface. One candidate
identified so far — recorded in the required format, deliberately NOT
pre-approved:

```text
TEST: TestProposalInputTaskConfigFields::test_fields_round_trip_through_pydantic
WHAT IT CLAIMED TO PROVE: task_description/forward_contract survive a
  Pydantic round-trip.
INDEPENDENT FAILURE CLASS: none identified — no custom serializer is
  involved; CLAUDE.md names this exact pattern ("a scalar round-tripping
  through JSON with no custom serializer") as decoration.
EXISTING/NEW EVIDENCE: after the JOIN, any transport break is caught by
  the JOIN evidence, Checkpoint C and Gate 1, all of which read the
  value end-to-end.
WHY REMOVAL DOES NOT REDUCE ACCEPTANCE EVIDENCE: the higher layers fail
  loudly on a transport break; this test adds no localisation the
  targeted JOIN assertions do not already give.
STATUS (operator, 2026-08-13): DEFAULT = KEEP. Retirement is NOT a
  goal of this PR. Remove only if implementation NATURALLY touches this
  surface AND a cheap controlled-defect experiment proves no
  independent failure class. Do not spend substantial implementation
  time on it. Its sibling test_defaults_are_empty is NOT a candidate —
  it pins a production default, which CLAUDE.md preserves. No
  repository-wide cleanup.
```

**E. Gate redundancy statement.** Gate 1's new class over unit/golden:
real-model structural validity under the enlarged prompts. Gate 2's new
class over Gate 1: cross-node, cross-iteration chain completion.
Low-level tests **retained deliberately** because they localise faster
and deterministically: the per-stage JOIN assertions (a gate failure
would not tell you WHICH stage), the golden set (byte-level diff), and
the mutation dossier (proves the tests can fail at all). No existing
directly-affected test is made redundant by the gates.

**F. Terminal policy.** One full suite at the final executable head. If
a post-run executable fix is needed, re-run the targeted evidence
first, then re-run the terminal suite on the NEW final executable head.

## 11. Acceptance criteria — READY FOR OPERATOR REVIEW (ordered)

Gate evidence must name the **exact executable HEAD** it ran on.

- [x] 1. JOIN boundary evidence: shipped description in all three stage
      system prompts, both modes, captured at the LLM boundary. →
      `TestJoinReachesEveryStageSystemPrompt`, asserted per stage over
      six captures through the real `run()` (§14.3).
- [x] 2. Declared golden delta ONLY: exactly R2 in S1-C and R3 in S1-E;
      each regenerated golden reconstructible as old + intended change.
      → six R2 goldens, all `attributable=True` (§14.3); three R3
      goldens, each diff showing only the literal's removal (§16.3).
- [x] 3. FX-1 description-axis isolation proven. → §15, including the
      strongest form (block-deleted remainders byte-identical).
- [x] 4. No surviving unsubstituted placeholders on any stage surface.
      → unit scan (§14.3), plus an explicit by-name check on the real
      Checkpoint C, Gate 1 and Gate 2 prompt dumps (§17.2-§17.4).
- [x] 5. S1-E capture-first evidence + guard RED→GREEN. → captured
      pre-edit at sha256 `bb8e974b…` with the literal still present;
      guard `1 failed/9 passed` → `10 passed` (§16.2). S1-E was NOT
      dropped.
- [x] 6. **Checkpoint C** evidence attached, HEAD named. → PASS on
      `de8a5b8a` (§17.2).
- [x] 7. **Gate 1 PASS**, HEAD named, artifacts attached. → PASS on
      `de8a5b8a`, 15m15s, 197,070 tokens (§17.3).
- [x] 8. **Gate 2 PASS**, HEAD named, artifacts attached. → PASS on
      `de8a5b8a`, 33m35s, 581,345 tokens, all five standard criteria
      plus the PR-specific one (§17.4). No waiver was needed.
- [x] 9. Prompt-delta accounting (§5) filled with measured numbers. →
      +262 chars/stage in production; +86 B per golden.
- [x] 10. ONE terminal full unit suite + ruff at the final executable
      head, verdict read from the log. → **8540 passed / 3 skipped /
      0 failed, 493.25 s** at `6b259b93` from a clean tree; `PYTEST
      EXIT: 0` captured from pytest itself before `tail`; zero
      `FAILED`/`ERROR` lines. `ruff check .` and
      `ruff format --check .` (817 files) clean.
- [x] 11. Exact-final-head CI green (CI is the only pyright). → PR
      **[#201](https://github.com/Galileo-Sandbox/SIDERIUS/pull/201)**,
      CI run **31654760883**, `conclusion: success`, `headSha
      5946528a9895e6b5cb97deb7667ad6581d8f0aeb` — identical to local
      HEAD and to the PR's `headRefOid`. Every step green, including
      **Type check — pyright (strict, blocking)**, which closes the
      locally-unavailable gap. (Two infrastructure annotations on the
      run — a Node 20 deprecation notice and a GitHub cache-service
      outage — are warnings on the runner, not job failures; the job
      concluded `success`.) A docs-only closeout commit sits on top and
      is re-verified by its own CI run, per the repository's convention.
- [x] 12. Clean working tree.
- [ ] **Not merged.** Stop at READY FOR OPERATOR REVIEW.

**FINAL STATE — PR 01b is READY FOR OPERATOR REVIEW.** Every acceptance
item above is closed except the deliberate final one. Nothing in this PR
may be merged without explicit operator approval.

**Executable-head note.** `6b259b93` (S1-F) touched
`agent/schemas/proposal.py` — two `Field` description strings only, no
behaviour — so it moved the executable head off `de8a5b8a`, and the
terminal suite was re-run on it per §10.F rather than reusing the
earlier result. The gates ran on `de8a5b8a`, whose executable content
differs from `6b259b93` by those docstrings alone. Any commit after
`6b259b93` in this PR is docs-only.

## 12. Adversarial design review (revision 2, 2026-08-13)

Ten questions from the operator review, answered against this document
and the source.

| # | Question | Finding | Correction |
|---|---|---|---|
| A1 | Implementation detail frozen too early? | **YES, in revision 1** — it froze the helper choice, exact test-file placement, and an exact regex as an acceptance criterion | §0 now separates FROZEN behaviour from implementation-time decisions; the regex became a property ("no unsubstituted placeholder survives") |
| A2 | Observable checkpoint before each risky phase? | **NO, in revision 1** — commits were ordered but nothing blocked progression | §9 adds a blocking ladder with explicit FAIL⇒stop rules |
| A3 | Does Gate 1 catch what earlier layers cannot? | **YES** — every lower layer uses a canned bridge; only Gate 1 asks whether a real model still returns schema-valid output under the enlarged prompts. Strengthened by the tiered config putting real models on all three JOIN surfaces | recorded in §7 |
| A4 | Does Gate 2 catch what Gate 1 cannot? | **YES, but narrowly** — cross-node, cross-iteration chain completion under a possibly-shifted proposal distribution | recorded in §8, with an honest statement that its marginal value is lower here than for a training feature, and Q2 raised |
| A5 | Gates broader/more expensive than necessary? | **Revision-1 had none; the risk now is over-gating.** Explicitly rejected: Lite/Regular formal-round plans (no formal logic touched), full scope, a second chain, real-LLM Checkpoint C | §8 records each rejection with its justification |
| A6 | Can a declared golden change conceal an unrelated prompt change? | **YES — real gap.** Regenerating six goldens means any other simultaneous template edit rides along invisibly, and "every changed byte is attributable" was a human-judgement criterion | S1-C now requires a MECHANICAL attributability proof: each regenerated golden must equal old-golden + the inserted block. A mismatch is a STOP |
| A7 | Can the description reach one surface but not another with everything green? | **YES if assertions are written loosely** — an "appears in the render" assert, or a placeholder added to a MODE file instead of the base template, could leave one stage/mode uncovered | criteria now require per-stage assertions across all three stages AND both modes (six captures), not an aggregate |
| A8 | Any test asserting implementation shape instead of behaviour? | One: the template-layer placeholder pin | retained deliberately and justified in §10.B as the anti-re-inlining guard — the only defect no golden can catch |
| A9 | Is S1-E still independently droppable? | **YES, but a new interaction appeared** — S1-E's widened numeral pattern could fire on the description S1-C injects (it contains `256`) | §4.3 adds an explicit negative criterion: the widened pattern must not fire on the JOIN block. Droppability re-confirmed: S1-E touches no file S1-C depends on |
| A10 | Step-02/03 semantics leaking in? | **NO**, but there is a temptation: having added the description to stages 1-2, a contributor may want to add the forward contract too | F10 states the non-goal at the top of the frozen list, and parent §8.3 records it as a separately-owned deferred question |

## 13. Operator decisions at freeze (2026-08-13) — no open questions

| # | Question | Decision |
|---|---|---|
| **Q1** | OD-S1-9 wiring shape | **RESOLVED — option (b).** Parent §8.3 amended to state the semantic invariant (§3.3) |
| **Q2** | Waive Gate 2 for a prompt-only change? | **NO — DO NOT WAIVE.** Approved at exactly the bounded trial-only shape, now frozen as a parameter table in §8. One retry only for a diagnosed transient LLM-quality failure where the gate standard permits it |
| **Q3** | Retire the `test_fields_round_trip_through_pydantic` candidate? | **DEFAULT = KEEP.** Test retirement is not a goal of PR 01b. Remove ONLY if implementation naturally touches that surface AND a cheap controlled-defect experiment proves it has no independent failure class. **Do not spend substantial implementation time proving one trivial test can be deleted** |

**Nothing remains open.** The design is frozen; implementation is
authorized to begin in a fresh context (see Status).

---

# LIVE IMPLEMENTATION LEDGER

Implementation began 2026-08-12 in a fresh context on branch
`feat/generic-framework-step-01b-task-description-join`.

**Kickoff verification (repository truth, not conversation):** HEAD
`f223956d`; `master` = `origin/master` = `a7cf42d1` = the merge-base, so
master has NOT advanced since the freeze (branch 4 ahead, 0 behind).
`39f89f52` (PR #199 / PR 01a) and `adbc835d` (PR #200 / Context
Continuity v2) both verified as ancestors of HEAD. Working tree clean;
no PR open for the branch; no implementation commit present. A second
worktree exists at `.claude/worktrees/agent-a20add3fd68ee21ed` on branch
`docs/generic-framework-step-01-design` — a different branch, so it
cannot mutate this checkout.

> **Previous assumption:** the Implementation Working Rules contract
> names the frozen design HEAD as `adca5079`.
> **Audit evidence:** HEAD is `f223956d`, one commit further on. That
> commit is docs-only — the §7a amendment making both Gates use
> `llm_configs/openai_tiered_pro.json`.
> **Corrected understanding:** the contract text already REQUIRES the
> `pro` config, so it incorporates this amendment; the two agree.
> **Implementation consequence:** none. Implementation proceeds from
> `f223956d`.
> **Validation consequence:** Gate 1 / Gate 2 use
> `openai_tiered_pro.json`, per §7a and the contract.

## 14. S1-C — the JOIN (implemented)

### 14.1 Implementation-time decisions

**D1 — reuse shape (§0 leaves this open; three shapes were acceptable).**
CHOSEN: a thin sibling, `_render_pipeline_task_background(task_description)`
in `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py`, which
delegates to the existing `_render_task_background` with an EMPTY
`ForwardContract`.

Why this over the alternatives:

- *Reuse `_render_task_background` directly at the call site* — would
  satisfy F3 but not F2. Its empty guard is
  `not task_description and fc.is_empty()`, so a WHITESPACE-ONLY
  description renders a label over a blank bullet: exactly the "orphan
  label over blank space" §4.1's failure table forbids. The sibling
  strips first, and that strip is the only guard for the case.
- *Give the existing helper an optional-contract form* — would change a
  helper the LEGACY reasoning path renders through, i.e. touch bytes
  outside S1-C's declared R2 set for no gain.
- The sibling also owns the ONE trailing blank line (see D2), which the
  legacy caller must not gain: `PROPOSAL_REASONING_PROMPT` deliberately
  runs the block straight into its next bullet.

F3 is preserved because the label string `"Background on the task:"`
still has exactly one definition, inside `_render_task_background`. F10
is preserved because the empty contract means no contract prose enters
the comparison or causal stages; the proposing stage continues to render
the contract through its own pre-existing `{forward_contract}`.

**D2 — placeholder name and placement.** Key `task_background_block`,
matching the sibling `*_block` keys already in the same `template_vars`
dict. Placed immediately before the `## Your task` heading in each of the
three BASE templates, written adjacently as
`{task_background_block}## Your task`, with the rendered block carrying
its own trailing blank line.

Measured consequence: with an EMPTY description the rendered stage prompt
is **byte-identical to the pre-JOIN template render** — verified
mechanically against `git show HEAD:...comparison_stage.md` with the
mode overlay applied. The alternative (placeholder on its own line)
would have left one stray blank line whenever the description is empty.

**D3 — the dead key is REMOVED, not kept alongside.** Under OD-S1-9(b)
the invariant is semantic, so `"task_description": inp.task_description`
is replaced by `"task_background_block": _render_pipeline_task_background(...)`.
The TRANSPORT (`inp.task_description`, `ProposalInput.task_description`,
the workflow injection) is untouched — only the unconsumed
`template_vars` key is gone, so F4 holds with no duplicate transport.

**D4 — the stale comment.** Rewritten in place to state the real
mechanism, including WHY the key must be lowercase
(`load_stage_prompt` builds `f"{{{key}}}"` from the key verbatim), so the
next reader cannot repeat the §3.1 mistake.

### 14.2 Source audit — every frozen assumption re-verified at `f223956d`

| Frozen assumption | Verified |
|---|---|
| dead key transported into pipeline `template_vars` | YES — `ml_model_proposal_agent.py:1708` (pre-edit) |
| NO proposal template consumes it | YES — the only placeholders in the three base templates were `{# EXPLORATION_MODE_BLOCK #}`, `{available_losses_block}`, `{available_models_block}`, `{minimum_boldness}`, `{CLASSIFIER_LOSS_LIST}`, `{REGRESSOR_LOSS_LIST}`, `{known_constraints_block}`, `{recent_gate_exhaustions_block}`, `{recent_trial_validity_block}`, `{healthgate_evidence_block}`, `{existing_model_types}`, `{forward_contract}`. Zero `{task_description}` |
| substitution literal, lowercase-keyed, sequential | YES — `agent/prompt_templates/proposal/__init__.py:76` |
| renderer + label + empty-collapse already exist | YES — `:400`, `:417`, consumed at `:441-442` via `{TASK_BACKGROUND}` at `:290` |
| description-only shape already pinned | YES — `test_proposer_task_config.py:88` and `:100` |
| shipped description is stripped | YES — `workflows/task_config.py:168`; 234 chars, 4 lines, no trailing newline |
| PB-3 fixture uses a TEST-OWNED description | YES — `test_step00_prompt_goldens.py:167` |
| WF-3 key set unaffected | YES — `_audit_proposer_components` reports 10 fixed CONTENT keys; system-prompt growth lands in `LLMBridge`'s derived `template_and_scaffolding` VALUE, not a new key. The golden is byte-identical after the JOIN |
| all production `load_stage_prompt` call sites share one `template_vars` | YES — `:1742` (main loop), `:1845` (boldness retry), `:1940` (causal correction), `:1998` (proposing) all pass the same dict, so one wiring point covers every surface |

### 14.3 CP1 evidence — CHECKPOINT 1 **PASS**

| Required evidence | Result |
|---|---|
| shipped description reaches 3 stages × 2 modes | PASS — `TestJoinReachesEveryStageSystemPrompt::test_shipped_description_present_exactly_once_per_stage[explore\|exploit]`, asserted PER STAGE at the LLM boundary through the real `run()` |
| exactly-once placement | PASS — the same test counts `== 1` for both the description and the label on every surface; `TestTemplateLayerJoinPins` additionally pins one placeholder per base template and none in any mode overlay |
| zero surviving placeholders | PASS — `test_no_unsubstituted_placeholder_reaches_the_boundary` scans all six captures with `\{[A-Za-z_][A-Za-z0-9_]*\}`; zero hits. (The pattern is identifier-only, so it does not false-positive on `proposing_stage.md`'s literal `{loss_name, description, ...}` JSON sketch or `{# EXPLORATION_MODE_BLOCK #}`) |
| exactly R2 goldens change | PASS — `git diff --stat` over the golden directory: the six `pb3_*_system.txt`, `3 +++` each, nothing else |
| each R2 golden = old + intended block | PASS — see the attributability table below |
| render deterministic across fresh processes | PASS — `test_join_render_is_byte_stable_across_fresh_processes` renders all six surfaces in two subprocesses under `PYTHONHASHSEED=0` and `=1` and compares SHA-256 |
| M-1 RED then restored GREEN | PASS — see mutation dossier |
| M-6 RED then restored GREEN | PASS — see mutation dossier |

**Attributability proof (adversarial finding A6).** For each golden:
`new.count(BLOCK) == 1` **and** `new.replace(BLOCK, "", 1) == old`, where
`old` is read from `git show HEAD:<path>` and `BLOCK` is the renderer's
output for the fixture description. The second equality proves every
OTHER byte is unchanged — no reflow, no smuggled edit.

| Golden | block count | old → new | delta | attributable |
|---|---|---|---|---|
| `pb3_comparison_explore_system.txt` | 1 | 9114 → 9200 | +86 | **True** |
| `pb3_comparison_exploit_system.txt` | 1 | 8985 → 9071 | +86 | **True** |
| `pb3_causal_explore_system.txt` | 1 | 10934 → 11020 | +86 | **True** |
| `pb3_causal_exploit_system.txt` | 1 | 10730 → 10816 | +86 | **True** |
| `pb3_proposing_explore_system.txt` | 1 | 19801 → 19887 | +86 | **True** |
| `pb3_proposing_exploit_system.txt` | 1 | 19839 → 19925 | +86 | **True** |

**Capture provenance (§13 rule 2).** The six goldens were regenerated by
an explicit developer act — a throwaway script driving the SAME
production path the PB-3 test drives (real `MLModelProposalAgent.run()`,
`_CannedProposerBridge` boundary capture, `pin_environment`), asserting
the exact stage-label sequence and refusing to CREATE any golden file
that did not already exist. Tests never regenerate
(`tests/helpers/golden.py`).

**Mutation dossier.**

| ID | Mutation | Site count | Expected RED | Observed | Restored |
|---|---|---|---|---|---|
| **M-1** | remove `{task_background_block}` from ONE stage template (`causal_reasoning_stage.md`) | 1 (asserted before mutating) | the causal stage's JOIN evidence + its two goldens | **RED, 6 failed / 17 passed**: both `test_shipped_description_present_exactly_once_per_stage` params, the causal template pin, the brace-token case (same stage), AND both `TestPB3PipelineProposer` golden tests | GREEN, 23 passed — file restored from backup, `git diff` clean, `__pycache__` cleared before both runs |
| **M-6** | delete the workflow injection `propose_input.task_description = get_task_description(_task_cfg)` in `workflows/model_exploration.py` | 1 (asserted before mutating) | the workflow-tier JOIN assert | **RED**: `AssertionError: the workflow's task-config injection did not reach the proposer's rendered SYSTEM prompt` in `test_pr_e_funnel_gate_pseudo.py` | GREEN, 1 passed in 14.5 s — `git diff` on `workflows/model_exploration.py` empty |

No mutation was committed.

### 14.4 Bounded deviation — where the workflow-tier assert landed

```text
Deviation:
  The workflow-tier JOIN assert (parent §10.2, mutation M-6's RED target)
  was added to the LEGACY proposer system surface inside
  tests/integration/workflows/test_pr_e_funnel_gate_pseudo.py, rather
  than to a pipeline-path workflow capture.

Reason / source evidence (inspect-first, as §4.1 requires):
  - test_vocab_accumulation.py::test_vocab_discoveries_appear_in_
    proposal_prompt builds its ProposalInput DIRECTLY and never calls
    run_workflow, so it cannot see the injection hop at all.
  - test_chain_candidate_graduation.py patches the proposer AGENT with a
    side-effect, so no prompt is ever rendered.
  - test_full_exploration_loop.py needs a real API key and a GPU.
  - test_pr_e_funnel_gate_pseudo.py is the ONLY in-tree pseudo test that
    runs the REAL proposer run() through the REAL run_workflow. It
    passes no llm_config, so propose=None selects the LEGACY path
    (parent §11.3 records this).
  - Flipping it to the pipeline path is not a minimal extension: its
    bridge is a MagicMock with ONE generate.return_value, and the
    pipeline needs three distinct stage responses. That would mean
    rewriting the canned choreography of an unrelated merge-requirement
    Gate test.

Impact:
  The assert proves the hop this PR depends on — that run_workflow
  actually DELIVERS the shipped description into a rendered proposer
  SYSTEM prompt. It does NOT prove the three-stage pipeline JOIN; that is
  proven by the S1-C unit captures, the six R2 goldens, and Checkpoint C
  (production entry, pipeline path, dumped proposing prompt).

Validation:
  M-6 observed RED against it and GREEN after restore (§14.3).
```

### 14.5 Discovery — the brace-token hazard is NOT introduced by the JOIN

> **Previous assumption:** §4.1 lists "a description containing
> brace-like tokens must not corrupt other substitutions", with a STOP
> branch if sequential replace makes this "genuinely unsafe".
> **Audit evidence:** `load_stage_prompt` substitutes with `str.replace`
> over DISTINCT tokens at DISTINCT sites, so no other placeholder's own
> site can ever receive the wrong value. The only order-dependent effect
> is confined to the injected block itself: a token inside the
> description either survives verbatim (its key was substituted earlier
> in the dict) or expands (its key comes later).
> **Corrected understanding:** this is a pre-existing property of EVERY
> rendered `*_block` value — `known_constraints_block`,
> `available_losses_block` and the vocab blocks have carried it since
> they were introduced. The JOIN adds no new risk class, so the STOP
> branch is not triggered and the shipped config is NOT sanitised.
> **Implementation consequence:** none.
> **Validation consequence:** the negative test asserts the honest
> property — every other placeholder site still renders its own value,
> the block is rendered rather than sanitised away, and the substitution
> loop neither raises nor aborts. Its unique failure class is a future
> refactor to `str.format` / `string.Template`, which would raise on
> brace-bearing content.
>
> Recorded limitation (no action in this PR): a FUTURE
> `configs/task_config.yaml` description containing a literal
> `{identifier}` token could ship that token to the LLM, or absorb a
> later block. No in-tree description does. Owner: whoever introduces a
> task profile with brace syntax.

### 14.6 Validation run at S1-C

| Validation | Result |
|---|---|
| `pytest tests/unit/agent/ml_model_proposal_agent/test_step01b_task_description_join.py tests/.../test_step00_prompt_goldens.py` | **23 passed, 4.3 s** |
| `pytest tests/unit/agent/ml_model_proposal_agent/ tests/unit/agent/prompt_templates/ tests/unit/workflows/test_step00_task_config_baselines.py` | **761 passed, 5.3 s** (includes `test_prompt_ceiling_policy.py`, `test_contract_reassertion.py`, `test_proposer_task_config.py`, `test_audit_components.py`, WF-3) |
| `pytest tests/unit/agent/ml_model_proposal_agent/ ... + tests/unit/agent/llm_bridge/test_step00_prompt_goldens.py` | **767 passed, 4.8 s** |
| `pytest tests/integration/workflows/test_pr_e_funnel_gate_pseudo.py` | **1 passed, 15.5 s** (pseudo, never CI per repository policy) |
| `ruff check` on touched files | clean |
| `ruff format --check` on touched files | clean (the new test module was formatted before commit) |
| full unit suite | **deliberately NOT run** — §10.A: terminal gate only. Targeted evidence shows a bounded blast radius (three templates, one node function, one `template_vars` key) |

No test was skipped, and none is claimed as passed without being run.

## 15. S1-C2 — fixture 13.4-A / rung FX-1 (implemented)

Test-only. Zero production diff, zero golden diff (verified:
`git diff --stat` over the golden directory is empty for this commit).

### 15.1 What landed

`tests/unit/agent/ml_model_proposal_agent/test_step01b_description_axis_contrast.py`
renders the SAME PB-3 fixture twice IN ONE PROCESS, varying only
`task_description` (shipped ⇄ the in-tree `_ALT_TD`) and passing the
SHIPPED `ForwardContract` identically to both. Four properties, each
parameterised over both modes:

1. the alternative text reaches the task-background block of all three
   stage system prompts, **and the shipped description is absent** from
   them (the displacement half);
2. zero `SQUID` / `dark-matter` / `magnetometry` inside the
   description-DERIVED BLOCK — scoped by slicing between the label and
   the `## Your task` heading, never whole-prompt (parent §9.5);
3. **axis isolation in its strongest form**: delete the
   description-derived block from both renders and the remainders must
   be BYTE-IDENTICAL. This subsumes the planned "contract-derived tokens
   byte-identical" criterion and additionally catches a description
   leaking anywhere else in the prompt;
4. the positive half — the fixed TIDMAD contract tokens
   (`[B, T] int64`, `[B, 256, T] float32`) are present under BOTH
   descriptions, so criterion 3 cannot pass by rendering no contract at
   all. Scoped to the proposing stage, because F10 keeps the contract
   out of stages 1-2.

The S1-C harness `capture_stage_systems` gained an optional
`forward_contract` argument for this; the rung remains single-axis
because that contract is held IDENTICAL across the two variants.

The block locator asserts loudly if it cannot find the block, with the
§4.2 rule written into the message: an unlocatable block means S1-C
chose an unstable placement, and the fix is S1-C — never a loosened
residue assertion.

### 15.2 CP2 evidence — CHECKPOINT 2 **PASS**

| Required evidence | Result |
|---|---|
| alternative description reaches all three stages | PASS — `test_alternative_description_reaches_every_stage[explore\|exploit]` |
| `task_description` is the only varied axis | PASS — `test_only_the_description_block_moves`: block-deleted remainders byte-identical across variants, all three stages, both modes |
| no SQUID-specific residue inside the description-derived block | PASS — `test_no_squid_residue_inside_the_description_derived_block` |
| contract-derived tokens byte-identical | PASS — covered by the isolation assertion, plus the positive presence check |
| description-contamination mutation RED then restored GREEN | PASS — MUT-A and MUT-B′ below |

**Mutation dossier (S1-C2).**

| ID | Mutation | Site count | Result | Classification |
|---|---|---|---|---|
| **MUT-A** (§4.2's named SQUID-contamination mutation) | append `" (SQUID dark-matter magnetometry data)"` to the description inside `_render_pipeline_task_background` | 1 | **13.4-A RED — 2 failed / 6 passed**, both `test_no_squid_residue_...` params. PB-3 goldens ALSO red (2 failed / 4 passed) | behaviour-changing; target hit |
| **MUT-B** (hypothesised "channel does not vary") | decorate the renderer with `functools.lru_cache(maxsize=1)` | 1 | **SURVIVED** — 8 passed, goldens 6 passed, JOIN 17 passed | **EQUIVALENT MUTANT.** The renderer is a pure function of its argument, and the cache key IS that argument, so memoisation cannot change any observable value. Not a test gap; the mutation was invalid |
| **MUT-B′** (the corrected form) | stash the FIRST rendered block in a module-level list and return it forever, ignoring the argument thereafter | 1 | **13.4-A RED — 4 failed / 4 passed** (both `test_alternative_description_reaches_every_stage` params AND both residue params), while **every PB-3 golden stayed GREEN — 6 passed** | behaviour-changing; this is 13.4-A's unique failure class |

Restored after each: `git diff` over `nodes/` empty, `__pycache__`
cleared before every run, baseline re-verified — **769 passed, 5.0 s**
over the proposer package + templates + task-config baselines. No
mutation was committed.

> **Previous assumption:** §4.2 predicted the SQUID-contamination
> mutation would red 13.4-A "while every shipped-profile golden stays
> green".
> **Audit evidence:** MUT-A reddened the PB-3 goldens too.
> **Corrected understanding:** the prediction assumed the PB-3 fixture
> renders the SHIPPED profile. PR 01a's S1-A0 deliberately made it
> TEST-OWNED (fixture description, 192-class contract) precisely so an
> accidentally-hardcoded production literal becomes visible. Against a
> test-owned fixture the goldens are NOT blind to an unconditional
> hardcode — which is the goldens working as intended, not a defect.
> **Implementation consequence:** none; no test or production change.
> **Validation consequence:** the "golden-blind" half of the design's
> expectation is demonstrated by MUT-B′ instead, which is the sharper
> statement of what 13.4-A alone owns — a channel that renders a valid
> description but does not VARY with its input. Every golden pins one
> profile per process and cannot see that; two profiles in one process
> is the only way to.

## 16. S1-E — stale budget-literal cleanup (implemented)

Isolated and independently droppable: it touches no file S1-C depends on
for the JOIN, and reverting this commit alone leaves S1-C/S1-C2 intact.

### 16.1 The two literals and how they were repointed

| # | Surface | Before | After |
|---|---|---|---|
| 1 | `PROPOSAL_REASONING_PROMPT` (`ml_model_proposal_agent.py`) | "and keep `parameter_count_estimate` under **~100M** for initial exploration." | "and justify `parameter_count_estimate` against that cap rather than against a fixed parameter budget." |
| 2 | `agent/prompt_templates/proposal/causal_reasoning_stage.md`, rule 3's devil's-advocate EXAMPLE | "…may exceed the **10 GB VRAM budget**" is. | "…may exceed the **Effective cap in [HARDWARE CONTEXT]**" is. |

Both edits repoint at the live `[HARDWARE CONTEXT]` effective cap, which
the same sentence already names as the hard limit — so each literal is
replaced by the authority it was contradicting, not merely deleted.

§4.3's STOP branch (subjective rewriting of the devil's-advocate
example) was **not** triggered: the example's point is a concrete,
checkable capacity failure mode, and swapping the stale number for the
live cap preserves it mechanically. Recorded so the operator can see the
branch was evaluated rather than skipped.

### 16.2 CP3 evidence — CHECKPOINT 3 **PASS**

| Required evidence | Result |
|---|---|
| legacy reasoning SYSTEM surface captured BEFORE modification | **PASS, and ordering is provable**: the capture ran against the unedited tree and its content still contained `~100M` (asserted at capture time). New golden `goldens/s1e_legacy_reasoning_system.txt`, 3642 bytes, sha256 `bb8e974b…`, taken at the LLM boundary through the REAL legacy `run()` path (reusing PB-4's `_run_legacy_capture`, pinned to the SHIPPED contract per PB-4's precedent) |
| widened guards observed RED against the old literals | **PASS** — `1 failed, 9 passed`; the failure message named BOTH offenders with their surrounding sentences: `PROPOSAL_REASONING_PROMPT` (`~100M`) and `causal_reasoning_stage.md` (`10 GB`) |
| literals removed / reworded | PASS — §16.1 |
| guards GREEN after modification | **PASS** — `10 passed` |
| widened numeral/budget pattern does NOT fire on the JOIN block | **PASS** — asserted directly against `_render_pipeline_task_background(get_task_description(load_task_config()))`, which carries `256` and `[B, 256, T]`. Adversarial finding A9 closed |
| legitimate VRAM requirement remains | **PASS** — `test_vram_requirement_prose_survives_the_cleanup` pins "must include at least one VRAM limit" in `PROPOSAL_COMMIT_PROMPT` and "VRAM ceiling" + "HARDWARE CONTEXT" in `PROPOSAL_REASONING_PROMPT`; `test_vram_limit_requirement_retained` unchanged and green |
| only R3-declared goldens change | **PASS** — §16.3 |

**What the widened guard actually is.** Two blind spots, closed
separately because they are different defects:

1. *Scan-set blindness.* `_all_template_texts()` was
   `PROPOSAL_COMMIT_PROMPT` + the `*.md` files. `PROPOSAL_REASONING_PROMPT`
   was never in it, which is the ONLY reason `~100M` survived the
   original C2 sweep. It is now in the set — so every existing member of
   that family (the mandate patterns, the `<10 GB VRAM` pin) now also
   covers the reasoning constant.
2. *Pattern blindness.* The old pin matched the exact string
   `"<10 GB VRAM"`; the surviving literal read "the 10 GB VRAM budget"
   and differed by one `<`. The replacement is a CONCEPT detector,
   `_numeric_capacity_literals`: a magnitude with a size/count unit
   (`GiB|GB|MB|M|B`) within 90 whitespace-normalised characters of
   capacity language (`vram|memory|budget|parameter|param|ceiling|cap`).
   Both halves are required, because the templates legitimately contain
   bare numerals (`segmentation_size > 20000`, `[B, 256, T]`, boldness
   ratios) AND legitimately contain numeral-free capacity prose. Only the
   conjunction is the defect.

   Precision measured against every real surface before the edit: exactly
   two hits, both the S1-E targets, zero elsewhere; and zero hits on all
   six rendered stage prompts other than the causal one. The dated
   exact-string pin is KEPT alongside it as the historical regression
   marker.

The negative control is its own test, with a positive half so it cannot
silently degenerate into a tautology: the detector must NOT fire on the
VRAM-requirement prose, on `segmentation_size > 20000`, or on the JOIN
block — and MUST still fire on the two removed literals.

**Reachability.** The RED observation IS this commit's reachability
evidence: the guard was seen failing against the real, unedited
production surfaces before anything was deleted. No separate mutation was
needed, and none is claimed.

### 16.3 R3 golden event — exactly three files, each diff attributable

| Golden | Event | Diff |
|---|---|---|
| `s1e_legacy_reasoning_system.txt` | **NEW** — captured pre-edit, regenerated post-edit in the same commit | the three-line literal sentence only |
| `pb3_causal_explore_system.txt` | regenerated | `- may exceed the 10 GB VRAM budget" is.` / `+ may exceed the Effective cap in [HARDWARE CONTEXT]" is.` |
| `pb3_causal_exploit_system.txt` | regenerated | identical single-line change |

`pb3_comparison_*`, `pb3_proposing_*`, all three `pb3_*_user.txt`, PB-4,
WF-3 and every CFG golden are **byte-identical** — the regeneration
script refuses to write any file outside the declared R3 set.

### 16.4 Follow-up recorded, deliberately NOT fixed here

`nodes/ml_model_implementor/ml_model_implementor.py:363` carries the same
stale literal class in the IMPLEMENTOR's reasoning prompt:
`"GPU budget: <10 GB VRAM, <100M parameters for initial exploration."`
— both halves, including the exact `<10 GB VRAM` string the proposer-side
pin has forbidden since C2.

It is OUT of PR 01b's scope: §4.3 names exactly two literals, both
proposer-side, and `test_prompt_ceiling_policy.py` is a proposer guard.
Widening the scan set to another node would turn a droppable cleanup
commit into a cross-node change. Owner: whoever next touches the
implementor prompt surface; the detector built here is directly reusable.

### 16.5 Validation run at S1-E

| Validation | Result |
|---|---|
| `pytest .../test_prompt_ceiling_policy.py` BEFORE the edit | **1 failed, 9 passed** (intended RED) |
| `pytest .../test_prompt_ceiling_policy.py` AFTER the edit | **10 passed, 1.1 s** |
| proposer package + templates + task-config baselines + llm_bridge step00 goldens | **780 passed, 5.0 s** (includes `test_health_prompt_parity.py`, whose PB-0 legacy USER golden is untouched) |
| `ruff check` / `ruff format --check` on touched files | clean |
| repository-wide grep for other consumers of the removed literals | none outside the guard's own documentation and positive-control assertions |

## 17. Production-boundary ladder

**Operator approved all three launches (2026-08-12), after an initial
denial recorded below. Checkpoint C has PASSED.**

### 17.0 Mandatory launch declarations — a frozen-design gap, closed

> **Previous assumption:** the frozen Gate design (§6, §7, §8) specifies
> the Checkpoint C / Gate 1 / Gate 2 flag sets completely.
> **Audit evidence:** the first real invocation was refused by the
> application's own preflight:
>
> ```text
> [run_one_iteration] FORMAL LAUNCH REFUSED: a formal launch must declare
> --healthgate_mode and --result_authority. There is no default:
> defaulting to blocking/scientific would let this run claim enforcement
> and scientific standing that nobody configured.
> ```
>
> Neither flag appears anywhere in §6/§7/§8. They are enforced by
> `execute_tools/health_checks/launch_policy.py::validate_formal_launch`.
> **Corrected understanding:** the values are NOT free choices — they are
> determined by the shipped configuration and by what this PR is
> honestly claiming. Resolved from source, not guessed:
>
> | Flag | Value | Why it is the only honest one |
> |---|---|---|
> | `--healthgate_mode` | `blocking` | `_enforcing_gate_ids(None)` over the shipped `configs/health_checks.yaml` returns `{amplitude_collapse_blocking, output_diversity_blocking, output_std_blocking}` — non-empty, so `observe_only` is REFUSED ("gates still invalidate"). `resolve_scientific_gate_ids(None)` returns the same set, so `scientific - enforcing == ∅` and `blocking` is accepted |
> | `--result_authority` | `diagnostic` | These runs validate the FRAMEWORK, not the science. §8 states PASS is chain completion and bookkeeping, explicitly NOT denoising quality — so this evidence must never enter the scientific aggregate. `blocking + diagnostic` is legal by design ("enforced, deliberately not promoted") |
>
> **Implementation consequence:** both flags are added to every launch in
> this ladder. This is a frozen-design OMISSION being filled from source,
> not a scope change or a deviation: the flags are mandatory declarations
> the entry point refuses to default, and the chosen values weaken
> nothing — `diagnostic` is the more conservative claim.
> **Validation consequence:** none. No gate criterion changes.

### 17.1 The initial denial (resolved)

The repository carries a launch guard,
`.claude/hooks/require_launch_approval.sh`, which intercepts any command
that would execute `run_one_iteration.py`:

```text
BLOCKED: this command would execute run_one_iteration.py, which can start
a real SIDERIUS chain or training run.
Launching production runs requires explicit operator approval.
If the operator has approved THIS launch, prefix the command with
SIDERIUS_ALLOW_LAUNCH=1 to record that approval explicitly.
```

The Implementation Working Rules contract for this PR authorizes the
bounded Checkpoint C / Gate 1 / Gate 2 launches in writing, so the
documented approval mechanism was used — the command was re-issued with
the `SIDERIUS_ALLOW_LAUNCH=1` prefix. **That invocation was then DENIED
at the session permission layer.**

A denial is an operator decision and was treated as one: the ladder
stopped rather than being worked around, no alternative launch path was
attempted, and no gate result was claimed. The operator was asked
directly and **approved all three launches**; the ladder then proceeded.

### 17.2 Checkpoint C — **PASS**, on HEAD `de8a5b8a`

Audited before assembly, at `5dee6c4a`:
`run_one_iteration.py` defines `--is_pseudo_llm` and `--is_pseudo_training`
(the pseudo-mode pair), `--debug_dump_prompts`, `--llm_config`,
`--start_iteration`, `--max_rounds`, `--max_proposal_attempts`,
`--is_trial`, `--trial_portion`, `--max_epochs`; only `--workspace` and
`--run_name` are `required=True`; `--seed_paths` is genuinely optional
("omit the flag entirely to start a cold chain").

```bash
SIDERIUS_ALLOW_LAUNCH=1 ./.venv/bin/python \
    sdsc_submission_scripts/run_one_iteration.py \
    --workspace "$WS" \
    --run_name step01b_checkpoint_c \
    --start_iteration 1 \
    --llm_config llm_configs/openai_tiered_pro.json \
    --is_pseudo_llm \
    --is_pseudo_training \
    --debug_dump_prompts \
    --healthgate_mode blocking \
    --result_authority diagnostic \
    --max_rounds 1 \
    --max_proposal_attempts 1 \
    --is_trial \
    --trial_portion 0.02 \
    --max_epochs 1
```

Two choices in it deserve to be visible rather than assumed:

- **`--llm_config` is REQUIRED even in pseudo mode**, and this is not
  cosmetic. `run_workflow` without an `llm_config` leaves `propose=None`
  and dispatches the **LEGACY** proposer path (parent §11.3). The legacy
  path already rendered the description before this PR, so a Checkpoint C
  run without `--llm_config` would exercise the wrong surface and prove
  nothing about the JOIN. `openai_tiered_pro.json` is used for
  consistency with §7a; under `--is_pseudo_llm` the bridge is stubbed, so
  it costs nothing.
- **`--is_pseudo_training` is paired with `--is_pseudo_llm`** so the run
  matches §6's declared cost class ("no real LLM, no GPU, no API cost").
  `--is_pseudo_llm` alone would still train for real
  (`run_one_iteration.py`: `require_probe_runner=not (args.is_pseudo_training
  or args.is_pseudo_llm)` shows the two flags are independent switches).
  Precedent: DS8's pseudo chain smoke used exactly this pair,
  cold-start, and exited 0 with a graceful `no_records` manifest
  (`enable_partial_file_list.md`).

**Result — PASS.** Exit 0; workflow completed in 3 s wall
(2026-08-12 16:23:23 → 16:23:26); no GPU, no API cost. Manifest
`status=no_records`, which is the correct and expected cold-start
outcome under the stub sandbox (the DS8 pseudo chain smoke recorded
exactly the same, `enable_partial_file_list.md`) — Checkpoint C's
question is prompt delivery through the production entry, not scores.

Verified on the dump
`{WS}/iter_001/debug/iter001_attempt001_proposing_system_prompt.md`
(518,891 bytes):

| Criterion | Result |
|---|---|
| run completes | **PASS** — exit 0, "Workflow Complete" |
| dump written (flag plumbing intact) | **PASS** |
| shipped description present, exactly once | **PASS** — `count == 1`, read via `get_task_description(load_task_config())`, never a literal |
| task-background label present, exactly once | **PASS** |
| derived contract tokens present | **PASS** — `[B, T] int64` and `[B, 256, T] float32` |
| no TEMPLATE placeholder survives | **PASS** — all sixteen production `template_vars` key names (plus `{TASK_DESCRIPTION}`/`{TASK_BACKGROUND}`) checked explicitly: NONE present |

This is the harness-vs-production divergence question §6 exists to ask,
and it is answered: the unit tier drives `MLModelProposalAgent.run()`
directly, so only this run could show that the real workflow entry point
populates the description.

> **Incidental finding, recorded so a future reader is not alarmed.** A
> naïve `\{[A-Za-z_]\w*\}` scan over the DUMP reports tokens like `{B}`,
> `{d_1}`, `{hat}`, `{emb}`. These are **LaTeX subscripts inside
> agent-generated model descriptions** carried by the
> `available_models_block` registry content — e.g.
> `"B_{d_1}"`, `"y_{hat}"`, `"R^{B x C_{emb} x T}"` — not unsubstituted
> template placeholders. Pre-existing, unrelated to this PR, and the
> reason the unit-tier scan is scoped to template-derived text (the PB-3
> fixture has an empty registry, where the scan finds zero). The explicit
> by-name check above is what actually establishes the property.

### 17.3 Gate 1 — **PASS**, on HEAD `de8a5b8a`

Command (Checkpoint C's, minus `--is_pseudo_llm` so the LLM is real,
keeping `--is_pseudo_training` so no training runs — exactly §7's
"Real LLM: YES. Real training: NO. GPU: none required"), with
`--max_proposal_attempts 3`, run name `step01b_gate1`.

Actual: **15 min 15 s** wall (16:24:13 → 16:39:28), exit 0.
**197,070 tokens across 7 calls** (proposer 150,455; tuner 43,365;
validator 3,250).

| §7 PASS criterion | Result |
|---|---|
| all LLM calls complete without error | **PASS** — zero tracebacks, zero `ValidationError`, and the three proposer stages ran `comparison → causal_reasoning → proposing` with NO structural retry or correction call |
| every stage output passes Pydantic validation | **PASS** — the persisted `proposal_iter_001.json` re-validates: `ProposalOutput.model_validate(...)` OK, `model_name='wavenet40_ce_fullspectrum_control'`, `output_type='classifier'`, `candidate_id='cand_3be90d87…'` |
| proposal reaches the implementor, code compiles + passes the dummy-tensor check | **PASS** — plugin generated, `All 7 checks passed`, registered into the run-scoped plugin dir |
| dumped proposing-stage prompt contains the shipped description | **PASS** — count == 1, label count == 1, and all sixteen template placeholder names absent |

This is the question no lower layer could answer: a REAL gpt-5.5, given
the enlarged and re-framed system prompts, still returns schema-valid
output across all three stages and downstream to a passing dummy-tensor
check.

**Unplanned bonus evidence for S1-E.** The real model's own
`expert_advice.constraints` came back as *"Usable VRAM cap is 25.07 GB on
the RTX 5090; target peak memory should stay below roughly 20 GB"* — it
derived its budget from the live `[HARDWARE CONTEXT]` effective cap, not
from any prompt literal. That is precisely the behaviour S1-E's cleanup
exists to produce, observed end-to-end with a real model.

**Diagnosed non-failure: the tuner phase ended on
`STOP_INFRASTRUCTURE_FAILURE`.** After the validator passed, the tuner's
VRAM pre-flight reported *"Pre-phase GPU MEASUREMENT FAILED
(STOP_INFRASTRUCTURE_FAILURE) — the environment could not measure this
candidate"*, three fail-rounds ran, and the iteration closed with a
graceful `no_records` manifest.

Diagnosis, from source rather than from the symptom: `run_one_iteration.py`
passes `require_probe_runner=not (args.is_pseudo_training or
args.is_pseudo_llm)`. Gate 1 sets `--is_pseudo_training`, so **no probe
runner is resolved by design** — the same line Checkpoint C's log states
outright (`probe_runner=no measurement capability was resolved by the
caller`). With no measurement capability, the VRAM gate cannot make an
admission decision and correctly refuses to guess. A GPU is present and
healthy (RTX 5090, 24.76 GB free of 32 GB, `torch.cuda.is_available()`
True), so this is not a hardware problem.

It is therefore **not a Gate 1 failure**: §7's PASS criteria stop at the
dummy-tensor check, and §7 explicitly says the gate "deliberately does
NOT train". §7's FAIL conditions — schema failure attributable to the
prompt change, a stage-handoff break, repeated proposal rejection — none
occurred. The behaviour is also entirely independent of prompt text.

Secondary observation, recorded because it shaped the log: `--max_rounds 1`
with `force_formal_round` defaulting ON made the single round a FORMAL
one. Harmless here, and it is exactly why the frozen Gate 2 shape carries
`--no-force_formal_round`.

### 17.4 Gate 2 — bounded trial-only chain

Assembled from CURRENT source and verified with the launcher's own
`--dry-run` (free, no side effects) BEFORE committing to the run. Every
frozen §8 parameter was confirmed in the emitted per-iteration command:

| Frozen parameter | Verified in the dry-run |
|---|---|
| exactly ONE bounded trial-only chain | one `run_chain.sh` invocation, 2 iterations walked |
| formal round | `--no-force_formal_round` present |
| scope + matching monitored files | `--data_scope 4-9 --health_gate_files 4,5,6,7,8,9` |
| seeds | **cold start** — "Source paths: 0 entries", no `--seed_paths` |
| trial portion | `--trial_portion 0.02` |
| iterations / rounds | `--num_iterations 2`, `--max_rounds 2` |
| proposal attempts | `--max_proposal_attempts 3` |
| time budgets | `--trial_time_budget_minutes 5`, `--formal_time_budget_minutes 30` (safety only) |
| LLM config | `--llm_config llm_configs/openai_tiered_pro.json` |
| prompt dumping | `--debug_dump_prompts` |
| mode | "Pseudo-mode: off (production)" |

Two notes for the reader: `--llm_model gemini-3.1-pro-preview` also
appears in the emitted command, but `--llm_config` overrides it by that
flag's own contract, so no Gemini call occurs; and
`--healthgate_mode blocking --result_authority diagnostic` are passed
explicitly because the launcher defaults `RESULT_AUTHORITY=scientific`,
which would overclaim for a framework gate (§17.0).

`--trial_vram_budget_gb 24` was added on the gate standard's own guidance
("be generous on GPU VRAM, stingy on wall time — a VRAM-gate rejection
wastes a whole Gate attempt"). It is not in §8's frozen parameter table,
so it is an unfrozen knob rather than a deviation.

**Runtime projection, recorded before launch.** §8 estimated ~30-45 min
on figures the gate standard derived with `openai_tiered_v1`. Gate 1's
measured 15 min for ONE iteration's LLM setup under `pro` suggested
Gate 2 might reach 45-60 min. **The projection was pessimistic — actual
was 33m 35s, inside §8's original estimate.** Recorded because the
pre-launch worry is part of the audit trail, and because the correction
matters: combined real validation was ~49 min, comfortably inside the
contract's ~1 h envelope.

#### Gate 2 result — **PASS**, on executable head `de8a5b8a`

| | |
|---|---|
| wall time | **33 min 35 s** — iter 1 `16:41:44 → 16:59:47` (18m03s), iter 2 `16:59:49 → 17:15:19` (15m30s) |
| chain exit | **0** — "CHAIN COMPLETE — 2 iterations" |
| tokens | **581,345 total** (iter 1: 280,123; iter 2: 301,222 across 14 calls — proposer 185,372, tuner 96,066, implementor 17,017, validator 2,767) |
| cost | not instrumented by the runner; token counts recorded instead of an invented dollar figure |
| real training | YES — 4 trial rounds, each a full `train → inference → score` over the resolved scope `[4..9]` |
| models | iter 1 `hybrid_spectral_gated_tcn_probe`, iter 2 `compact_wavenet16_ce_fullspectrum` — both newly invented by the real LLM |

**§8 PASS criteria, verbatim from the gate standard:**

| # | Criterion | Result |
|---|---|---|
| 1 | Chain exits 0 | **PASS** |
| 2 | Every round has a recorded `gate_action` | **PASS** — 4/4 records carry `gate_action='invalidate_round'` with `status='failed_mode_collapse'` |
| 3 | Every `denoising_score` finite, or `None`/`-inf` WITH an invalidating `gate_action` | **PASS** — all four are finite (`-1.6639`, `-1.4309`, `-1.3262`, `-0.5748`) and each is paired with `invalidate_round`. No score exists without accounting. (The standard's phrase "finite **positive**" is loose wording for "a real number": this project's scores are routinely negative — the raw baseline in this very run is `-0.0735`.) |
| 4 | No phantom `5.5762667` accepted as a final score | **PASS, in the strongest available form.** Recorded scores are the four above; `best_denoising_score=None`, `best_exp_id=None` in both iterations. And the gate's own `failure_reason` names what it prevented: *"Class-127 collapse artifact — score would be 5.5762667 via 2^17 FP ratio."* The phantom was detected and blocked, not merely absent |
| 5 | At least one round triggers a HealthGate evaluation | **PASS** — three blocking gates fired on every round (`output_diversity_blocking`, `output_std_blocking`, `amplitude_collapse_blocking`), each with per-file metrics across all six scope files |
| PR-specific | the dumped proposing prompt from a real chain iteration contains the shipped description | **PASS on BOTH iterations** — `iter001_attempt001` (518,891 B) and `iter002_attempt002` (523,069 B): shipped description count == 1, label count == 1, zero surviving template placeholders |

**The unique failure class §8 exists to catch is exercised and clean.**
Iteration 2's proposer consumed iteration 1's real outcome and proposed a
*different* architecture with explicit collapse-recovery reasoning; the
`[trial-validity] … Surfacing to next proposer` hand-off fired; and
iteration 2's dump is `attempt002`, so the chain also survived a
proposal-retry cycle. Cross-node, cross-iteration completion after the
prompt change is demonstrated, which is exactly what Gate 1 could not
reach.

**Scientific outcome, and why it is NOT the verdict.** Every round
collapsed (unique int8 values 2-9 against a >25 threshold; output std
0.23-0.55 mV against a >=1 mV threshold) and every score sits below the
raw baseline. §8 states this explicitly: *"whether `denoising_score` beat
baseline, whether the model learned to denoise, or any score threshold"*
are **not** pass/fail criteria. The models were trained for one epoch on
`trial_portion=0.02` (24-60 PSD segments) — collapse is the expected
outcome of that budget, and the reflector diagnosed it as such. **No
retry was taken, no portion was raised, no threshold was touched, and the
scorer was not modified.** Gate 2 asked whether the framework completes
end-to-end with the new prompts; it does.

**Observation recorded, deliberately not acted on.** The
`[trial-validity]` accounting line reads *"0 gate-invalid, 0
validity-unknown, 2 execution failures of 2 trial(s)"*, while the
persisted records carry `gate_action='invalidate_round'` and
`status='failed_mode_collapse'`. Whether a mode-collapse invalidation
should count in the `gate-invalid` bucket rather than the
`execution failures` bucket is a trial-validity bookkeeping question
owned elsewhere. It is untouched by this PR, identical before and after
the JOIN, and changing HealthGate or trial-validity semantics is a frozen
non-goal. Noted here for whoever owns that accounting.

### 17.5 Readiness — CURRENT state

**Checkpoint C PASS · Gate 1 PASS · Gate 2 PASS.
PR 01b is READY FOR OPERATOR REVIEW.** §11 acceptance items 6, 7 and 8
are CLOSED. No gate was skipped, excused or waived.

> **Superseded — PRE-LAUNCH / PRE-APPROVAL state, preserved as history.**
> Before the operator granted launch approval, this section read:
> *"PR 01b **cannot** reach READY FOR OPERATOR REVIEW until Checkpoint C,
> Gate 1 and Gate 2 have run and passed on the final executable head.
> §11 acceptance items 6, 7 and 8 are open. This is recorded as a
> blocked dependency, not a waiver."* That was accurate while the ladder
> was blocked (§17.1). It is **false as of 2026-08-12**, when all three
> ran and passed on executable head `de8a5b8a`. Kept only so the blocked
> interval remains auditable; it is NOT a current statement.

### 17.6 Terminal validation — the FINAL executable head is `6b259b93`

**Unambiguous current statement.** The final executable head is
**`6b259b93`**, NOT `5dee6c4a`. S1-F (`6b259b93`) edited two `Field`
description strings in `agent/schemas/proposal.py` — documentation only,
no behaviour — and that is still an executable file, so §10.F's standing
obligation applied and the terminal suite was **re-run on `6b259b93`**
rather than the earlier result being reused.

```text
pytest tests/unit/ -m "not real_run"      # at 6b259b93, clean tree
  8540 passed, 3 skipped, 404 warnings in 493.25s (0:08:13)
  PYTEST EXIT: 0        <- pytest's OWN status, captured before `tail`
  grep -cE "^(FAILED|ERROR)" over the log: 0
  log: <scratchpad>/full_suite_final.log
```

`ruff check .` — All checks passed. `ruff format --check .` — 817 files
already formatted.

**pyright: NOT run locally.** The box has Node v10.19.0, which cannot
bootstrap pyright. Recorded as unavailable, never as green; **blocking
CI is the authoritative and only pyright for this PR**, and it passed
(§11 item 11).

Every commit after `6b259b93` in this PR is **docs-only**, proven
mechanically rather than asserted: `git diff <prev> <head> -- ':!docs'
':!*.md'` is empty at each step.

> **Superseded — earlier terminal run, preserved as history.** The same
> suite was first run at `5dee6c4a` (8540 passed, 3 skipped, 498.92 s,
> `PYTEST EXIT: 0`, log `<scratchpad>/full_unit_suite.log`) while the
> gate ladder was blocked, so the operator would have complete non-gated
> evidence alongside the launch decision. That section closed with
> *"`5dee6c4a` is the final executable head only if the gates require no
> change."* The gates required no change — but **S1-F's docstring edit
> did**, so the head legitimately moved to `6b259b93`. The `5dee6c4a`
> run is historical evidence, not the terminal result.

## 18. Operator-reviewed judgements — ACCEPTED, do not revisit

Implementation review 2026-08-12: **positive. No production change and
no additional Gate requested.** These four judgements are accepted as
reviewed and are not to be reopened, re-litigated or "improved" by a
later contributor:

| # | Judgement | Accepted status |
|---|---|---|
| J1 | **Mandatory launch declarations.** `--healthgate_mode blocking` and `--result_authority diagnostic` were added to every launch in the ladder. | **ACCEPTED** as the source-grounded completion of a frozen-design OMISSION (§17.0), not a scope change and not a deviation. `blocking` is the only mode the shipped `configs/health_checks.yaml` permits; `diagnostic` is the conservative, honest authority for a framework gate. |
| J2 | **Gate 2's poor scientific / model scores.** All four rounds collapsed; every score sits below the raw baseline. | **NOT A FAILURE.** §8 states model quality is explicitly not a pass/fail criterion. Requires **no** retry, **no** larger portion, **no** threshold change and **no** scorer change. The frozen scorer stays byte-identical. Anyone tempted to "fix" this outcome is misreading the gate. |
| J3 | **The `lru_cache` mutation (MUT-B).** It survived. | **CORRECTLY CLASSIFIED as an EQUIVALENT MUTANT** — the renderer is a pure function and the cache key IS its argument, so memoisation cannot change any observable value. It is an invalid mutation, not a test gap. **MUT-B′** (serve the first block forever) is the meaningful behaviour-changing replacement, and it reddened four 13.4-A tests while every golden stayed green (§15.2). |
| J4 | **The stale implementor budget literal** at `nodes/ml_model_implementor/ml_model_implementor.py:363` (`"GPU budget: <10 GB VRAM, <100M parameters…"`). | **EXPLICIT FOLLOW-UP, OUT OF SCOPE for PR 01b** (§16.4). Deliberately untouched. The detector built in S1-E is directly reusable by whoever next owns the implementor prompt surface. |

## 19. Final status ledger — PR 01b

| Field | Value |
|---|---|
| PR | **[#201](https://github.com/Galileo-Sandbox/SIDERIUS/pull/201)**, base `master` |
| Branch | `feat/generic-framework-step-01b-task-description-join` |
| **Final EXECUTABLE head** | **`6b259b93`** — every later commit is docs-only, proven with `git diff … -- ':!docs' ':!*.md'` returning empty |
| **Final PR head** | the docs-only tip of this branch. A commit cannot contain its own SHA, so the exact value is recorded in the PR-scoped handoff and in the merge-gate report, and is independently verifiable via `gh pr view 201 --json headRefOid`. Preceding docs-only tip: `a01615d6` |
| Implementation commits | `a7ffcccf` (S1-C) · `e67b4651` (S1-C2) · `5dee6c4a` (S1-E) · `6b259b93` (S1-F) |
| CP1 / CP2 / CP3 | **PASS / PASS / PASS** (§14.3, §15.2, §16.2) |
| **Checkpoint C** | **PASS** on `de8a5b8a` — production entry, pseudo LLM + pseudo training, 3 s, exit 0 (§17.2) |
| **Gate 1** | **PASS** on `de8a5b8a` — real gpt-5.5 across all three proposer stages + dummy-tensor check, 15m15s, 197,070 tokens (§17.3) |
| **Gate 2** | **PASS** on `de8a5b8a` — bounded trial-only chain, 2 iterations × 2 real-training rounds, 33m35s, 581,345 tokens, chain exit 0, all five standard criteria + the PR-specific dump criterion (§17.4) |
| Terminal unit suite | **8540 passed / 3 skipped / 0 failed**, 493.25 s, at `6b259b93` from a clean tree; `PYTEST EXIT: 0` read from pytest itself; zero `FAILED`/`ERROR` lines |
| ruff / format | `ruff check .` clean; `ruff format --check .` — 817 files already formatted |
| **pyright — local** | **UNAVAILABLE.** Node v10.19.0 cannot bootstrap it. Never claimed as green |
| **pyright — CI** | **AUTHORITATIVE.** "Type check — pyright (strict, blocking)" passed in CI |
| Merge gate | `local HEAD == PR headRefOid == successful CI headSha`, clean working tree, PR mergeable — verified in the merge-gate report |
| Context state | **CLOSED / AWAITING OPERATOR ACTION** |
| Merge | **NOT MERGED. Operator-owned.** |
