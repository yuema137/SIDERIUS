# PR 01b — Task-description JOIN (Step 01, child 2 of 2)

## Status

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
- [ ] Re-read the existing task-background renderer and BOTH its call
      sites before writing anything; choose the reuse shape and record
      which and why (§0 implementation-time).
- [ ] Wire a description-only block into the pipeline `template_vars`
      per OD-S1-9(b), satisfying F2/F3/F4.
- [ ] Correct the stale `{TASK_DESCRIPTION}` comment (§3.1).
- [ ] Add the placeholder to all three stage base templates at a fixed,
      reviewed position; confirm from the WF-3 component audit that the
      position falls inside the `system_prompt` component.
- [ ] Regenerate exactly the six R2 goldens IN THIS COMMIT with §13
      rule-2 provenance; attach before/after diffs.
- [ ] JOIN evidence at the boundary (properties in §4 below).
- [ ] Attributability check (adversarial finding A6): demonstrate
      mechanically that each regenerated golden equals the OLD golden
      plus the inserted block — nothing else rode along.
- [ ] Workflow-tier pseudo assert: inspect first whether an existing
      dual-mode test already captures the proposer prompt and can take
      one added assert, before adding a new bounded test.
- [ ] Fill §5 prompt-delta accounting with measured bytes.

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
- [ ] Build the 13.4-A fixture: alternative description, SHIPPED
      ForwardContract UNCHANGED — one axis only.
- [ ] Assert the alternative text reaches the task-background block of
      all three stage system prompts.
- [ ] Assert ZERO SQUID residue **inside the description-derived block
      only** — not the whole prompt (contract prose legitimately still
      says "denoising classes" because the CONTRACT is still TIDMAD's;
      parent §9.1 and the §9.5 whitelist discipline).
- [ ] Assert contract-derived tokens are byte-identical to the
      TIDMAD-description variant of the same render (axis isolation).

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
- [ ] **CAPTURE FIRST** — add a Step-01 golden for the legacy reasoning
      SYSTEM render BEFORE editing the literal. It has no oracle today;
      editing first would change an unpinned surface.
- [ ] Widen the guard scan set to include the legacy reasoning constant
      and generalise the VRAM pin beyond the exact `<10 GB VRAM`
      string; **observe RED** against the current literals before
      deleting anything.
- [ ] Delete/repoint the two literals.
- [ ] Regenerate the just-captured golden and any affected `pb3_*`
      golden in the SAME commit, with §13 R3 provenance.
- [ ] Re-run the widened guards → green.

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

## 5. Prompt-delta accounting (required at implementation)

| Field | Requirement |
|---|---|
| files/goldens changed | exact list (expected: the six R2 `pb3_*_system.txt`) |
| added bytes / characters | measured per stage, from the golden diff |
| token delta | ONLY if a trustworthy local tokenizer is already available; otherwise state "token count unavailable — bytes/characters recorded instead". **Do not add a tokenizer dependency for this.** |
| why intentional | one line tying it to the dead-seam closure (roadmap §0 rule 8) |
| unchanged surfaces | explicit confirmation that USER prompts, `label=` values and `components=` key sets are unchanged |

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

- [ ] 1. JOIN boundary evidence: shipped description in all three stage
      system prompts, both modes, captured at the LLM boundary.
- [ ] 2. Declared golden delta ONLY: exactly R2 in S1-C and R3 in S1-E;
      each regenerated golden reconstructible as old + intended change.
- [ ] 3. FX-1 description-axis isolation proven.
- [ ] 4. No surviving unsubstituted placeholders on any stage surface.
- [ ] 5. S1-E capture-first evidence + guard RED→GREEN (or S1-E
      explicitly dropped, recorded as such).
- [ ] 6. **Checkpoint C** evidence attached, HEAD named.
- [ ] 7. **Gate 1 PASS**, HEAD named, artifacts attached.
- [ ] 8. **Gate 2 PASS**, HEAD named, artifacts attached (or an
      operator waiver recorded against Q2).
- [ ] 9. Prompt-delta accounting (§5) filled with measured numbers.
- [ ] 10. ONE terminal full unit suite + ruff at the final executable
      head, verdict read from the log.
- [ ] 11. Exact-final-head CI green (CI is the only pyright).
- [ ] 12. Clean working tree.
- [ ] **Not merged.** Stop at READY FOR OPERATOR REVIEW.

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
