# PR 01b — Task-description JOIN (Step 01, child 2 of 2)

## Status

**DESIGN — READY FOR OPERATOR REVIEW. Implementation NOT authorized.**

Prerequisite satisfied: **PR 01a is MERGED** (PR #199, merge commit
`39f89f52`, 2026-08-12); post-merge status sync `aec6db05`. "Unblocked"
is not "authorized" — this document must be frozen by the operator
before any branch is cut.

Parent design (audit, authority map, baselines, packs, golden policy,
mutation catalogue): `../step_01_proposer_hypothesis_space.md`.

This PR carries the **one operator-authorized intentional change to
default TIDMAD prompt bytes** in Step 01 (OD-S1-8). It is deliberately
isolated from PR 01a so that a reviewer never has to separate
"behaviour-preserving extraction" from "we changed what the agent
sees" inside one diff.

**ONE OPEN OPERATOR DECISION — `OD-S1-9` (§3.3).** The source audit
found that the frozen parent wording ("consuming the audited dead key …
WIRE, not REMOVE") and the frozen failure-case requirement ("empty
description → the block collapses to `\"\"`") cannot both be satisfied
by the same implementation. §3.3 states the three options, the source
evidence, and a recommendation. **Do not start implementation until
OD-S1-9 is decided** — S1-C's entire shape depends on it.

### Source-audit baseline (mechanical, 2026-08-13)

Every line reference below was verified against `master` `aec6db05`.

| Fact | Evidence |
|---|---|
| The dead key exists and is transported | `ml_model_proposal_agent.py:1708` — `"task_description": inp.task_description` inside the pipeline `template_vars` dict |
| NO proposal template consumes it | `grep -rn task_description agent/prompt_templates/` returns only `literature_review/` hits (a DIFFERENT, live surface with its own `{TASK_DESCRIPTION}`) — zero hits under `proposal/` |
| Substitution is literal and case-sensitive | `agent/prompt_templates/proposal/__init__.py:76` — `prompt.replace(f"{{{key}}}", str(value))` |
| Production always supplies a description | workflow injects at `model_exploration.py:2290`; the standalone CLI injects since PR 01a (`ml_model_proposal_agent.py:2287`) |
| A labelled block + renderer ALREADY exist for the legacy path | `PROPOSAL_REASONING_PROMPT` carries `{TASK_BACKGROUND}` at `:290`; `_render_task_background` at `:400`; substituted in `_build_reasoning_system_prompt` at `:441` |
| That renderer already collapses to `""` | `_render_task_background` returns `""` when the description is empty AND `fc.is_empty()` (`:417`) |
| Affected goldens under OD-S1-3(a) | the six `pb3_{comparison,causal,proposing}_{explore,exploit}_system.txt`; the three `pb3_*_user.txt` and `wf3_proposer_components_key_sets.json` must NOT change |
| The legacy reasoning SYSTEM render has NO golden | only behavioural asserts exist (`test_proposer_task_config.py:107-120`); `ls goldens/` has no `pb0_*` — this is why S1-E is capture-first |
| The chain entry for Checkpoint C | `sdsc_submission_scripts/run_one_iteration.py` — `--is_pseudo_llm` at `:1320`, `--debug_dump_prompts` at `:1306`, forwarded to `run_workflow(debug_dump_prompts=…)` at `:1940`; the dump is written at `ml_model_proposal_agent.py:2008-2011` |

**Two source discoveries that change the plan** (details in §3.1/§3.2):
a stale in-code comment documents a placeholder that cannot work, and
the existing prompt-contamination guard does not scan the constant
holding one of the two literals S1-E must delete.

## 1. Final effect of THIS PR

**The production proposer actually reads the shipped task
description.** Today the pipeline path — the standard production path —
renders no task description at all: `template_vars["task_description"]`
is supplied at `ml_model_proposal_agent.py:1708` and consumed by NO
template (a live dead key catalogued by roadmap §0 rule 8; assigned to
Step 01 by the Step-00 coverage manifest, step_00 design §15.2).

After this PR the declared task background reaches all three pipeline
stage system prompts (OD-S1-3(a) — the comparison and causal stages are
exactly where the architecture family is chosen, so leaving them
task-blind would satisfy the letter of the JOIN and miss its point).

**This is NOT extraction parity.** It is an intentional, reviewable
behaviour change with declared golden regeneration.

Scope honesty, carried from PR 01a §1: this PR changes what the agent
READS. It does not make SIDERIUS execute a non-TIDMAD task, and it does
not add any validation of the description's content.

## 2. Scope

OWNS:

- former `S1-C` — the JOIN itself, all three stages;
- the task-description contrast: fixture **13.4-A** / rung **FX-1**;
- the declared golden regeneration (parent §13 event **R2**);
- the stale proposer budget-literal cleanup (former `S1-E`, OD-S1-2)
  as its OWN isolated semantic commit with capture-first golden
  governance (parent §13 event **R3**);
- **Checkpoint C** live-integration evidence (pre-merge, §6);
- the Step-01 aggregate closeout (former `S1-F`) and roadmap sync.

Does NOT own: anything already merged in PR 01a; any new authority; any
Step-02/03 contract semantics; forward-contract expansion to stages 1-2
(parent §8.3 defers it explicitly — a separable render change with its
own prompt-budget implications); FX-3/FX-4 (deferred to the
contract-owning step, parent §6A.5).

**Terminology note on the operator's generic checklist.** The standard
template asks for `file_order` / `shuffle` / visited-sample-sequence
acceptance criteria. Those belong to a dataset-ordering feature and
have **no counterpart in this PR** — PR 01b touches prompt text only
and reaches no dataset, sampler or RNG. The equivalent "ordering"
obligation here is **render determinism and placement**: the block must
appear at a fixed position in each stage prompt, exactly once, with a
byte-stable rendering across processes. That is what §4's acceptance
criteria pin instead, and it is why no shuffle/seed criteria appear
below.

## 3. Source findings that shape the plan

### 3.1 FINDING — the in-code comment documents a placeholder that cannot work

```text
Comment at ml_model_proposal_agent.py:1704-1707:
  "{FORWARD_CONTRACT} is rendered into proposing_stage.md (line 68
   area); {TASK_DESCRIPTION} is rendered into any future template that
   wants the bare task string."

Source evidence:
  load_stage_prompt substitutes f"{{{key}}}" (proposal/__init__.py:76)
  and the key is the lowercase "task_description" (:1708). An
  UPPERCASE {TASK_DESCRIPTION} in a proposal stage template would
  therefore NEVER be substituted — it would ship to the LLM as a
  literal brace token. (The uppercase form IS correct for the
  literature_review module, which does its own explicit
  .replace("{TASK_DESCRIPTION}", …) at
  literature_review/__init__.py:305 — a different surface. The comment
  appears to have imported that convention by analogy.)

Consequence for this PR:
  an implementer following the comment writes the wrong placeholder and
  produces a visibly broken prompt. The comment must be corrected in
  whichever commit wires the block, and the JOIN test must assert that
  NO unsubstituted brace token survives in the rendered stage prompts —
  not merely that the description is present.
```

### 3.2 FINDING — the contamination guard does not scan one of S1-E's two targets

```text
Previous assumption (parent OD-S1-2):
  S1-E is "delete two stale prose literals".

Source evidence:
  test_prompt_ceiling_policy.py::_all_template_texts (:48) builds its
  scan set from PROPOSAL_COMMIT_PROMPT plus every *.md in
  agent/prompt_templates/proposal/. It does NOT include
  PROPOSAL_REASONING_PROMPT — which is where the "~100M" literal lives
  (:292). And test_stale_hardcoded_vram_budget_removed (:108) pins the
  EXACT string "<10 GB VRAM", while the surviving literal reads
  "the 10 GB VRAM budget" (causal_reasoning_stage.md:146) — no "<".

Corrected understanding:
  both literals survive today precisely BECAUSE the existing guards do
  not reach them. Deleting the text without widening the guards would
  leave the same blind spots open for the next contributor, and the
  commit would have no test that fails if the literals come back.

Implementation consequence:
  S1-E widens the scan set to include PROPOSAL_REASONING_PROMPT and
  generalises the VRAM pin from an exact literal to a numeral-budget
  pattern — and does so BEFORE deleting the literals, so the widened
  guard is observed RED first. This is guard-strengthening inside the
  commit that needs it, not scope creep: without it the commit cannot
  state an acceptance criterion that can fail.
```

### 3.3 OPEN OPERATOR DECISION — OD-S1-9: how the block is wired

Two frozen requirements collide. Parent §8.3 says the block renders
"via the existing `template_vars` mechanism — **consuming** the audited
dead key at :1708 (**WIRE, not REMOVE**)". The frozen failure case says
"empty description → block collapses to `\"\"` (legacy precedent)".

A bare `{task_description}` placeholder carries no label, so the label
must live in the template — and template text cannot collapse when the
value is empty. The two requirements are not jointly satisfiable.

| Option | Shape | Consequence |
|---|---|---|
| **(a)** literal label in each of the 3 templates around `{task_description}` | consumes the dead key exactly as §8.3 words it | an empty description renders an orphan heading with no body in all three stage prompts; the label is duplicated in 3 files and can drift |
| **(b) RECOMMENDED** — replace the bare key with `"TASK_BACKGROUND": <rendered block>`; templates reference `{TASK_BACKGROUND}` | mirrors the LEGACY surface exactly (`PROPOSAL_REASONING_PROMPT:290` + `_render_task_background:400`), collapses to `""` for free, single source for the label | the literal key NAME `task_description` disappears from `template_vars`. This is a REMOVE in letter, but it satisfies §8.3's stated rationale — the transport survives and description-derived blocks exist in the render, which is what fixture 13.4-A needs. The dead key stops being dead by ceasing to exist rather than by acquiring a consumer |
| **(c)** keep the bare key AND add `TASK_BACKGROUND` | both exist | the dead key SURVIVES — the roadmap §0 rule 8 defect this PR exists to close would still be there afterwards. Rejected on its face; listed for completeness |

**Recommendation: (b).** It reuses a proven in-tree pattern instead of
inventing a second one, it is the only option that gives the frozen
empty-collapse behaviour without special-casing, and it keeps one label
definition. Its only cost is a wording correction to parent §8.3, which
this document requests explicitly rather than silently reinterpreting.

Everything below is written **against option (b)** and is marked where
option (a) would change it. If the operator picks (a), S1-C's
implementation plan changes but its validation plan does not.

## 4. Implementation phases (per-commit 8-section checklists)

Standing rules: parent §18.1 (autonomous semantic commits;
minimum-sufficient per-commit testing; full suite + static + CI once at
the final executable head; stop only for material deviation).

Commit order and why: the JOIN (`S1-C`) must land before its contrast
(`S1-C2`), because the contrast asserts against a block that does not
exist yet. `S1-E` is independent of both and is deliberately last among
the code commits so that a reviewer can drop it without touching the
JOIN. Checkpoint C runs on the final executable head, so it follows all
code commits.

| # | Commit | Kind | Changes rendered TIDMAD bytes? |
|---|---|---|---|
| 1 | `S1-C` — the JOIN | production + goldens | **YES** (declared, R2) |
| 2 | `S1-C2` — fixture 13.4-A / rung FX-1 | test-only | no |
| 3 | `S1-E` — budget-literal cleanup | production + goldens | **YES** (declared, R3) |
| 4 | `S1-CP` — Checkpoint C evidence | evidence + docs | no |
| 5 | `S1-F` — docs closeout | docs-only | no |

---

### 4.1 Commit S1-C — the JOIN

**1. Goal.**
Close the audited dead seam: make the production pipeline render the
shipped task description into all three stage SYSTEM prompts, so the
stages that actually choose the architecture family are no longer
task-blind. This is the single deliberate rendered-byte change in the
mandatory scope, authorized by OD-S1-8.

It belongs in its own commit because it is the ONLY commit in Step 01
whose golden diff is intentional. Bundling it with the contrast tests
(S1-C2) or the literal cleanup (S1-E) would force a reviewer to
separate two different kinds of golden change inside one diff — the
exact failure mode the PR 01a/01b split exists to prevent.

**2. Scope.**

Expected to change:
- `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` — the
  `template_vars` entry at `:1708` (option (b): becomes
  `"TASK_BACKGROUND": <rendered block>`), the stale comment at
  `:1704-1707` (§3.1), and a description-only block renderer (either a
  thin new helper or an `fc`-optional overload of
  `_render_task_background:400` — decided at implementation after
  re-reading the helper's callers).
- `agent/prompt_templates/proposal/comparison_stage.md`,
  `causal_reasoning_stage.md`, `proposing_stage.md` — one
  `{TASK_BACKGROUND}` placeholder each, at a fixed position.
- `tests/unit/agent/ml_model_proposal_agent/goldens/pb3_*_system.txt`
  — six files regenerated (parent §13 R2).
- `tests/unit/agent/ml_model_proposal_agent/test_step00_prompt_goldens.py`
  or a new sibling — the JOIN assertions.

Must remain unchanged:
- the three `pb3_*_user.txt` goldens (USER prompts are not a JOIN
  surface);
- `wf3_proposer_components_key_sets.json` — the block renders INTO the
  existing `system_prompt` component; a new component key would be a
  design failure, not a regeneration;
- `pb4_legacy_commit_*.txt` and every CFG golden;
- the legacy reasoning path — it already renders the description via
  `{TASK_BACKGROUND}:290` and this commit must not alter that surface;
- stage `label=` values, stage order, retry/correction behaviour,
  parsing, candidate minting, persistence.

Depends on: PR 01a merged (`39f89f52`) — the goldens being regenerated
are the post-01a ones. No dependency on any later commit here.

**3. Implementation plan.**
- [ ] Re-read `_render_task_background:400-428` and both of its call
      sites before writing anything; decide helper-reuse vs thin new
      helper on what the source actually supports, and record which and
      why.
- [ ] Implement the description-only block renderer; it MUST return
      `""` for an empty description (matching `:417`).
- [ ] Wire it into `template_vars` per OD-S1-9 (option (b): replace the
      bare `task_description` key; option (a): keep it and label in the
      templates).
- [ ] Correct the stale `{TASK_DESCRIPTION}` comment at `:1704-1707`
      (§3.1) — it documents a placeholder that cannot substitute.
- [ ] Add the placeholder to all three stage base templates at a fixed,
      reviewed position; confirm from the WF-3 component audit that the
      position falls inside the `system_prompt` component.
- [ ] Regenerate exactly the six `pb3_*_system.txt` goldens IN THIS
      COMMIT, with the parent §13 rule-2 provenance message and the
      before/after unified diffs attached to the PR.
- [ ] JOIN test: the SHIPPED description (loaded via
      `load_task_config()`, never a literal copy) appears verbatim in
      each of the three captured production stage system prompts.
- [ ] Placement test: the block appears EXACTLY ONCE per stage system
      prompt, and no unsubstituted `{...}` brace token survives in any
      rendered stage prompt (§3.1).
- [ ] Empty-description test: the block collapses to `""` and leaves no
      orphan label (option (b)) — or, under option (a), pin whatever
      the chosen shape actually renders, honestly.
- [ ] Workflow-tier pseudo assert (parent §10 item 2): inspect first
      whether `tests/integration/workflows/test_vocab_accumulation.py::
      test_vocab_discoveries_appear_in_proposal_prompt` already captures
      the proposer prompt and can take one added assert, before adding a
      new bounded test.
- [ ] Fill in the §5 prompt-delta accounting table with measured bytes.

**4. Validation plan.**

Unit:
- JOIN presence, per stage, from the captured boundary render.
- Exactly-once placement; zero surviving brace tokens.
- The six regenerated goldens re-assert byte-equality after
  regeneration (the standard `assert_golden` path).
- Determinism: the same render in two fresh processes is byte-identical
  (the block must not depend on dict/set iteration order).

Negative / invalid input:
- empty description → block collapses, no orphan label;
- whitespace-only description → treated as empty (decide and pin, do
  not leave implicit);
- a description containing a `{`/`}` brace → must not corrupt
  subsequent substitutions (the substitution loop is sequential
  `str.replace`, so a value containing another key's placeholder text
  is a real, if unlikely, ordering hazard — pin it).

Backward-compatibility / default-parity:
- the three USER goldens byte-identical;
- WF-3 component-key-set golden byte-identical;
- PB-4 and all CFG goldens byte-identical;
- `test_prompt_ceiling_policy` and `test_prompt_banned_vocabulary`
  still green (the JOIN inserts shipped prose into surfaces those
  guards scan).

Mutations (parent §15): **M-1** (remove the placeholder from one stage
template) must red the JOIN test AND that stage's golden; **M-6**
(comment out the workflow post-hoc injection at
`model_exploration.py:2290`) must red the workflow-tier assert.

Real-training Gate: **none required.** No Gate 1 / Gate 2 / real-LLM
run is part of this commit's evidence, and none may be launched without
separate operator approval.

**5. Acceptance criteria (observable).**
- The shipped description string returned by
  `get_task_description(load_task_config())` appears, byte-for-byte, in
  the captured system prompt of all three stages, in both `explore` and
  `exploit` modes — six captures.
- The block appears exactly once per stage system prompt (count == 1,
  not "is present").
- `re.findall(r"\{[A-Za-z_]+\}", rendered) == []` for all six stage
  system prompts — no placeholder, in either case convention, survives.
- Exactly six golden FILES differ in the commit; `git diff --stat` on
  `tests/unit/**/goldens/` lists those six and nothing else.
- Every changed line in those six diffs is attributable to the block —
  no incidental reflow.
- Two fresh interpreters produce byte-identical renders.
- M-1 red on the JOIN test and the affected golden; M-6 red on the
  workflow-tier assert; both restored green afterwards.

**6. Failure and edge cases.**

| Case | Required handling |
|---|---|
| Empty description (test fixtures; never production after PR 01a) | block collapses to `""`; **safe fallback**, pinned by test |
| Whitespace-only description | normalised to empty; **safe fallback**, pinned — must not emit a label over blank space |
| Description containing brace tokens | must not corrupt other substitutions; **pinned by test**. If the sequential-replace ordering makes this genuinely unsafe, STOP and report rather than sanitising the shipped config |
| A new `components` key appears in WF-3 | **stop execution** — this means the block landed outside the `system_prompt` component; it is a design failure, not a regeneration |
| A golden outside the declared six changes | **stop execution** — parent §13 rule 1: fix the code, never the golden |
| Prompt-size growth | bounded (~4 lines/stage); `test_prompt_ceiling_policy` must stay green. If a size guard fires, record the measurement and stop — do not raise a ceiling to fit the block |
| Missing/invalid task config at render time | out of scope here: `load_task_config()` already fails closed upstream and PR 01a's CLI disposition covers the standalone entry |

**7. Verification commands and evidence.**
```bash
# pack 1 + 2 (fast inner loop + Stage-A parity)
.venv/bin/python -m pytest tests/unit/agent/ml_model_proposal_agent/ \
  tests/unit/workflows/test_step00_task_config_baselines.py -q
# determinism (two fresh processes)
.venv/bin/python -m pytest <join test> -q -p no:cacheprovider   # x2
# guards that scan the surfaces the JOIN grows
.venv/bin/python -m pytest \
  tests/unit/agent/ml_model_proposal_agent/test_prompt_ceiling_policy.py \
  tests/unit/agent/test_prompt_banned_vocabulary.py -q
```
Record after execution: test counts, wall time, the six golden diffs,
and the M-1/M-6 dossier rows. Any test that could not be run is
recorded with the reason — never claimed as passed.

**8. Commit boundary.**
Independently reviewable: templates, renderer, goldens, diffs and tests
are all inside it, so a reviewer can judge the behaviour change without
reading another commit. Contains no contrast fixtures (S1-C2), no
literal cleanup (S1-E), no docs closeout (S1-F). Before committing:
stop and show the diff summary, the staged file list, the test output,
and any deviation from this plan.

---

### 4.2 Commit S1-C2 — fixture 13.4-A / rung FX-1 (description axis)

**1. Goal.**
Prove the description CHANNEL is real: swapping only the description
changes only the description-derived block, and no SQUID-specific text
is hiding inside that block. Byte-equality on the shipped profile
cannot distinguish "the block renders the declared description" from
"the block happens to contain TIDMAD prose".

Separate from S1-C because it is test-only and adds no golden churn: a
reviewer checking the intentional byte change (S1-C) should not have to
read contrast fixtures at the same time. It is the description-axis
twin of PR 01a's B-i/B-ii/FX-2/FX-5 rungs, and it completes the
roadmap's 13.4-A/13.4-B pair.

**2. Scope.**
Adds one test module (or a class in PR 01a's
`test_step01a_contrast_rungs.py` — decide at implementation; a sibling
file is likely cleaner since that file's docstring scopes it to PR
01a). Uses the in-tree `_ALT_TD` string
(`tests/unit/agent/test_planner_prompt_task_config.py:32`, "audio
enhancement for speech synthesis: spectrogram → waveform"). No
production change, no golden change.

Depends on: S1-C (the block must exist).

**3. Implementation plan.**
- [ ] Build the 13.4-A fixture: `_ALT_TD` as the description, the
      SHIPPED TIDMAD `ForwardContract` UNCHANGED — one axis only.
- [ ] Assert `_ALT_TD` appears in the task-background block of all
      three stage system prompts (OD-S1-3(a)).
- [ ] Assert ZERO SQUID residue **inside the description-derived block
      only** — `SQUID`, `dark-matter`, `magnetometry` absent from that
      block, NOT from the whole prompt (contract prose legitimately
      still says "denoising classes" because the CONTRACT is still
      TIDMAD's; parent §9.1 and the §9.5 whitelist discipline).
- [ ] Assert the contract-derived tokens are byte-identical to the
      TIDMAD-description variant of the same render — proving the two
      axes are independent.
- [ ] Assert atomicity explicitly: the fixture varies the description
      and nothing else.

**4. Validation plan.**
Unit only (pack 3). Negative case: a description that itself contains a
contract-like token must not be mistaken for contract residue — scope
the residue assertion to the block, as PR 01a's §9.5 discipline
requires. No integration, no Gate.

Mutation: reintroduce a hardcoded SQUID phrase into the block renderer
→ 13.4-A must go red while every shipped-profile golden stays green
(the description-axis analogue of PR 01a's N-RESIDUE).

**5. Acceptance criteria (observable).**
- `_ALT_TD` present in all three stage system prompts under the alt
  fixture; the shipped description absent from them under that fixture.
- The three named SQUID tokens absent from the description-derived
  block; explicitly NOT asserted against the whole prompt.
- Contract-derived tokens identical between the alt-description and
  shipped-description renders (proving axis isolation).
- The SQUID-contamination mutation reds 13.4-A and leaves the goldens
  green; restored green afterwards.

**6. Failure and edge cases.**
- A residue assertion written against the whole prompt would be
  **unsatisfiable** (the TIDMAD contract prose is still there by
  design) — writing it that way is the mistake this criterion exists to
  prevent.
- If the block cannot be located in the rendered prompt for scoping,
  that indicates S1-C chose an unstable placement — **stop** and fix
  S1-C's placement rather than loosening the assertion.

**7. Verification commands and evidence.**
```bash
.venv/bin/python -m pytest tests/unit/agent/ml_model_proposal_agent/ -q
```
Record counts, wall time, and the mutation row.

**8. Commit boundary.**
Test-only; no production or golden diff. Independently reviewable.
Show the diff summary and test output before committing.

---

### 4.3 Commit S1-E — stale budget-literal cleanup (capture-first)

**1. Goal.**
Delete the two stale numeral budget literals so the proposer defers to
the `[HARDWARE CONTEXT]` effective cap (roadmap §14 resolved row), and
close the two guard blind spots (§3.2) that let them survive. Without
the guard work the deletion has no test that fails if the literals
return.

Separate commit because OD-S1-2 explicitly requires it to be isolated
and skippable, and because it regenerates a DIFFERENT golden set (R3)
than the JOIN (R2) for a different reason.

**2. Scope.**
- `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:292` —
  "~100M" inside `PROPOSAL_REASONING_PROMPT`.
- `agent/prompt_templates/proposal/causal_reasoning_stage.md:146` —
  "the 10 GB VRAM budget" (inside a devil's-advocate EXAMPLE sentence;
  re-read the sentence before editing — the fix may be rewording the
  example rather than deleting the clause).
- `tests/unit/agent/ml_model_proposal_agent/test_prompt_ceiling_policy.py`
  — widen `_all_template_texts:48` to include
  `PROPOSAL_REASONING_PROMPT`; generalise
  `test_stale_hardcoded_vram_budget_removed:108` from the exact
  `<10 GB VRAM` literal to a numeral-budget pattern.
- A NEW captured golden for the legacy reasoning SYSTEM render.
- Any `pb3_causal_*_system.txt` golden affected by the `.md` edit
  (R3, same commit, with provenance).

Must remain unchanged: the VRAM-limit REQUIREMENT itself
(`test_vram_limit_requirement_retained:65` — deterministic capacity
guidance is legitimate and stays); the JOIN block from S1-C.

Depends on: nothing in this PR (independent of S1-C/S1-C2), but ordered
last among code commits so it can be dropped without disturbing them.

**3. Implementation plan.**
- [ ] **CAPTURE FIRST** — add a Step-01 golden for the legacy reasoning
      SYSTEM render BEFORE editing `:292`. It has no oracle today
      (parent §8.1 PB-0 row; verified: only behavioural asserts exist
      at `test_proposer_task_config.py:107-120`). Editing first would
      change an unpinned surface.
- [ ] Widen the guard scan set and generalise the VRAM pattern, and
      **observe them RED** against the current literals before deleting
      anything — that red is the evidence the guards now reach.
- [ ] Delete/repoint the two literals.
- [ ] Regenerate the just-captured golden and any affected `pb3_*`
      golden in the SAME commit, with §13 R3 provenance.
- [ ] Re-run the widened guards → green.

**4. Validation plan.**
Unit (packs 1-2) plus the widened guards. Negative: the generalised
VRAM pattern must not fire on legitimate text — verify it does not red
`test_vram_limit_requirement_retained` or the fixture-supplied
`constraints=["VRAM < 10 GB"]` strings used across the proposer tests
(those are TEST INPUTS, not template literals; a pattern that catches
them is too broad). No Gate.

**5. Acceptance criteria (observable).**
- No numeral parameter-count or VRAM budget literal remains in any
  proposer prompt surface, including `PROPOSAL_REASONING_PROMPT`.
- The widened guard was observed RED before the deletion and GREEN
  after — both recorded.
- The legacy reasoning SYSTEM golden exists, was captured BEFORE the
  edit, and its regeneration diff shows only the literal's removal.
- `test_vram_limit_requirement_retained` still green; the VRAM
  requirement sentence is intact.
- Only R3's declared goldens changed.

**6. Failure and edge cases.**
- Capture-after-edit → the golden pins the already-changed surface and
  proves nothing. **Ordering is the acceptance criterion**, not a
  nicety.
- An over-broad VRAM pattern reddening test fixtures → narrow the
  pattern to template texts only; do not edit the fixtures.
- If the causal-stage sentence cannot be reworded without losing the
  devil's-advocate example's point, **stop and ask** — the example's
  pedagogical value is a prompt-quality judgement, not a mechanical
  edit.

**7. Verification commands and evidence.**
```bash
.venv/bin/python -m pytest \
  tests/unit/agent/ml_model_proposal_agent/test_prompt_ceiling_policy.py -q   # RED first, then GREEN
.venv/bin/python -m pytest tests/unit/agent/ml_model_proposal_agent/ -q
```
Record the RED output, the GREEN output, counts, wall time, diffs.

**8. Commit boundary.**
Isolated, clearly labelled, skippable — droppable without touching the
JOIN. Show the diff summary, staged files, both guard runs and the
golden diffs before committing.

---

### 4.4 Commit S1-CP — Checkpoint C evidence (PRE-MERGE)

**1. Goal.**
Prove the JOIN reaches the real LLM boundary through the real
production entry point, not only through unit harnesses. Per OD-S1-4
this is **pre-merge**, on the final executable head.

**2. Scope.**
Evidence + ledger only. Runs
`sdsc_submission_scripts/run_one_iteration.py` with `--is_pseudo_llm`
(`:1320`) and `--debug_dump_prompts` (`:1306`); the dump is written by
`ml_model_proposal_agent.py:2008-2011`. No production change. No API
cost, no real LLM, no training.

Depends on: all code commits landed.

**3. Implementation plan.**
- [ ] Re-read the flag plumbing (`run_one_iteration.py:1306,1320,1940`
      → `run_workflow` → `model_exploration.py:2304`) and confirm the
      invocation before running.
- [ ] Run ONE bounded pseudo-LLM iteration from the production entry.
- [ ] Verify the dumped proposing-stage system prompt contains the
      shipped description and the derived contract tokens.
- [ ] Attach the log + prompt dump to the PR evidence packet and record
      the exact command, runtime and head SHA in this ledger.

**4. Validation plan.**
This IS the validation. Its known coverage limit is stated, not glossed
(§6). No unit work. No Gate approval needed — pseudo-LLM only; if the
run turns out to require a real LLM call or GPU, that is a **material
deviation**: stop and report.

**5. Acceptance criteria (observable).**
- The command completes without error on the final executable head.
- The dumped file exists and contains the shipped description verbatim.
- The log and dump are attached, with the head SHA recorded.
- Coverage limit restated in the PR: the dump covers 1 of the 3 JOIN
  surfaces; the other two rest on the workflow-tier capture and the
  S1-C goldens.

**6. Failure and edge cases.**
- Dump file absent → the flag plumbing regressed; **stop** and diagnose
  before declaring readiness.
- Description absent from the dump while unit tests are green → the
  production entry diverges from the harness; that is a **blocker**,
  and exactly the divergence this checkpoint exists to detect.
- Run exceeds a bounded wall time or needs GPU/API → stop and report
  rather than escalating autonomously.

**7. Verification commands and evidence.**
Exact command recorded at execution (flags verified against source
first). Record runtime, head SHA, dump path, and the grep result.

**8. Commit boundary.**
Evidence/docs only.

---

### 4.5 Commit S1-F — docs closeout + PR readiness

**1. Goal.** Leave the ledger and the operator-facing docs true.

**2. Scope.** This document (every box `[x]` with evidence or
explicitly deferred with a reason); the node doc
`nodes/ml_model_proposal_agent/ml_model_proposal_agent.md` (25 KB — it
already documents the dump hook at `:39`/`:142`; the prompt-surface
description must be updated for the JOIN per the pre-merge doc-sync
rule); parent §16 checkpoint table; the folder README / roadmap rows at
the merge boundary. Docs-only.

**3. Implementation plan.**
- [ ] Reconcile every checklist box in this document with recorded
      evidence.
- [ ] Update the node `.md`, quote-verifying each documented flag and
      default against the merged source.
- [ ] Fill the §5 prompt-delta accounting table.
- [ ] Fill the parent §16 checkpoint table (Checkpoint C closed here;
      Checkpoint A was closed by PR 01a).
- [ ] Full suite + static gates ONCE at the final executable head from
      a CLEAN tree; verdict read from the log, never a wrapper's exit
      status.

**4. Validation plan.** Pack 5: `pytest tests/unit/ -m "not real_run"`,
`ruff check`, `ruff format --check`, pyright **in CI only** (Node
v10.19.0 cannot bootstrap pyright locally — record it as not locally
validated, never as green).

**5. Acceptance criteria (observable).**
- Every `[ ]` in this document is either `[x]` with evidence or
  explicitly marked deferred with a reason.
- Full-suite result recorded with pytest's own exit code and the log
  path; ruff clean; CI green on the EXACT final head SHA.
- Clean working tree; PR body lists the intentional golden changes.
- **PR READY FOR OPERATOR REVIEW — never merged autonomously.**

**6. Failure and edge cases.**
- A stale ledger at the final head is a defect in its own right — the
  PR-01a merge gate caught exactly that. Record CI state in the ledger
  and re-verify CI on the resulting head rather than withholding it.

**7. Verification commands and evidence.** Recorded at execution.

**8. Commit boundary.** Docs-only.

## 5. Prompt-delta accounting (required at implementation)

Because this PR deliberately grows three stage system prompts, the
final ledger MUST record, per stage:

| Field | Requirement |
|---|---|
| files/goldens changed | exact list (expected: the six `pb3_*_system.txt` named in §3's audit table) |
| added bytes / characters | measured per stage, from the golden diff |
| token delta | ONLY if a trustworthy local tokenizer is already available; otherwise state "token count unavailable — bytes/characters recorded instead". **Do not add a tokenizer dependency for this.** |
| why intentional | one line tying it to the dead-seam closure (roadmap §0 rule 8) |
| unchanged surfaces | explicit confirmation that USER prompts, `label=` values and `components=` key sets are unchanged (WF-3 golden stays green) |

## 6. Checkpoint C — PRE-MERGE (operator correction, OD-S1-4)

Every "post-merge chain evidence" formulation is superseded. The
bounded `--is_pseudo_llm` production-entry iteration:

- runs AFTER this PR's implementation is complete;
- runs ON its final executable head;
- runs BEFORE the PR is declared READY FOR OPERATOR REVIEW;
- attaches its log + prompt dump to the PR evidence packet;
- requires no real LLM and no API cost.

Unit goldens and the workflow-tier capture remain the primary evidence;
the chain run is a production-entry smoke proving the render reaches
the real boundary through the real entry point.

Known coverage limit (first review, F11; re-verified 2026-08-13): the
dump hook writes ONLY the proposing-stage system prompt
(`ml_model_proposal_agent.py:2008-2011`), while OD-S1-3(a) places the
block in all three. The workflow-tier capture covers the other two.
Accepted, recorded, not silently glossed.

## 7. Validation and dependencies

- **Starts from merged PR 01a** (`39f89f52`) — satisfied.
- Packs 1-4 of parent §12, plus the pre-merge chain evidence (§6).
- The regenerated goldens (R2 in S1-C, R3 in S1-E) are the ONLY
  expected byte changes; a diff outside those declared sets is a
  defect.
- Final executable head: full `pytest tests/unit/ -m "not real_run"`,
  ruff check + format, pyright (CI only), exact-head CI.
- Integration tests are **never** added to CI (repo policy); pack 4 is
  manual with fresh logs attached to any claim that cites it.

## 8. Acceptance criteria (observable, PR level)

- [ ] The shipped `task_description` appears verbatim in all three
      rendered stage system prompts, captured at the LLM boundary, in
      both modes.
- [ ] Exactly the goldens named in parent §13 R2 changed in S1-C, and
      exactly those named in R3 changed in S1-E; each diff is attached
      and every changed byte is attributable.
- [ ] WF-3's component-key-set golden is UNCHANGED.
- [ ] FX-1 contrast: swapping ONLY the description changes only the
      description-derived block, with contract-derived tokens
      byte-identical across the two variants.
- [ ] No unsubstituted placeholder token survives in any rendered stage
      prompt (§3.1).
- [ ] The two stale budget literals are gone, the guards that failed to
      see them are widened, and the widened guards were observed RED
      before the deletion.
- [ ] The legacy reasoning SYSTEM render was captured BEFORE the S1-E
      edit (parent §13 R3 capture-first rule).
- [ ] The pre-merge chain log is attached and shows the rendered task
      background at the production entry.
- [ ] Prompt-delta accounting (§5) filled with measured numbers.
- [ ] Full suite + static gates at the final executable head; CI green
      on the exact final head SHA; clean tree.
- [ ] **Not merged.** Stop at READY FOR OPERATOR REVIEW.

## 9. Open questions for the operator

1. **OD-S1-9 (§3.3) — BLOCKING.** Wiring shape for the JOIN: option (b)
   recommended, which requires amending parent §8.3's "WIRE, not
   REMOVE" wording.
2. **Non-blocking, recorded.** S1-E's guard widening (§3.2) is slightly
   larger than "delete two literals". It is included because without it
   the commit has no failing test; flagged so the operator can strike it
   if they prefer a pure-deletion commit.
