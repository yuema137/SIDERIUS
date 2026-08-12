# PR 01b — Task-description JOIN (Step 01, child 2 of 2)

## Status

**DRAFT — BLOCKED on PR 01a merge.** Design/audit only; no
implementation authorized. Parent design (audit, authority map,
baselines, packs, golden policy, mutation catalogue):
`../step_01_proposer_hypothesis_space.md`.

This PR carries the **one operator-authorized intentional change to
default TIDMAD prompt bytes** in Step 01 (OD-S1-8). It is deliberately
isolated from PR 01a so that a reviewer never has to separate
"behaviour-preserving extraction" from "we changed what the agent
sees" inside one diff.

## 1. Final effect of THIS PR

**The production proposer actually reads the shipped task
description.** Today the pipeline path — the standard production path
— renders no task description at all:
`template_vars["task_description"]` is supplied at
`ml_model_proposal_agent.py:1597` and consumed by NO template (a live
dead key catalogued by roadmap §0 rule 8; assigned to Step 01 by the
Step-00 coverage manifest, step_00 design §15.2).

After this PR the declared task background reaches all three pipeline
stage system prompts (OD-S1-3(a) — the comparison and causal stages
are exactly where the architecture family is chosen, so leaving them
task-blind would satisfy the letter of the JOIN and miss its point).

**This is NOT extraction parity.** It is an intentional, reviewable
behaviour change with declared golden regeneration.

## 2. Scope

OWNS:

- former `S1-C` — the JOIN itself, all three stages;
- the task-description contrast: fixture **13.4-A** / rung **FX-1**;
- the declared golden regeneration (parent §13 event **R2**);
- the stale proposer budget-literal cleanup (former `S1-E`,
  OD-S1-2) as its OWN isolated semantic commit with capture-first
  golden governance;
- **Checkpoint C** live-integration evidence (pre-merge, §5);
- the Step-01 aggregate closeout (former `S1-F`) and roadmap sync.

Does NOT own: anything in PR 01a; any new authority; any Step-02/03
contract semantics.

## 3. Implementation phases (per-commit 8-section checklists)

Standing rules: parent §18.1 (autonomous semantic commits;
minimum-sufficient per-commit testing; full suite + static + CI once at
the final executable head).

### 14.3 Commit S1-C — the JOIN (the mandatory scope's one deliberate render change)

**Goal.** The production pipeline renders the shipped task
description (task-background block in stage system prompts),
consuming the dead template_vars key; §13 rule-2 golden regeneration.

**Scope.** Stage base templates (per OD-S1-3 placement) +
`_run_pipeline` (no new key needed — :1597 exists); PB-3 golden
regeneration (provenance per §13); JOIN tests (§8.3, §10.2);
WF-3 key-set golden verified UNCHANGED. NON-goals: forward-contract
expansion to stages 1-2; wording beyond the minimal labeled block;
legacy surfaces (already render the description).

**Implementation plan.**
- [ ] Inspect stage templates + the WF-3 component audit to confirm
      the block lands inside the `system_prompt` component.
- [ ] Add the labeled task-background block + placeholder per
      OD-S1-3.
- [ ] Regenerate affected PB-3 goldens in THIS commit with the §13
      rule-2 message + attached diffs.
- [ ] JOIN test: shipped description (via `load_task_config()`)
      appears verbatim in the captured production render.
- [ ] Workflow-tier pseudo assert (§10.2) — inspect-first whether to
      extend an existing dual-mode test or add a bounded one.

**Validation plan.** Pack 1 + 2 + the touched integration test (pack
4, manual, log recorded); mutations M-1 and M-6 executed and
recorded.

**Acceptance criteria.** The regenerated goldens contain the shipped
description exactly once per stage system prompt; WF-3 key sets
unchanged; M-1 (remove the placeholder) turns the JOIN test red;
M-6 (drop the workflow post-hoc injection) turns the workflow-tier
assert red.

**Failure/edge cases.** Empty description (node CLI main()) → block
collapses to "" (legacy precedent), pinned by a test; prompt-size
growth is bounded (description is ~4 lines; `test_prompt_ceiling`
budget tests must stay green).

**Verification commands and evidence.** (after execution)

**Commit boundary.** The only commit that changes rendered TIDMAD
bytes **in the mandatory scope** (S1-E, if OD-S1-2 approves it, is a
second and clearly-labeled one — finding F13 contradiction fixed);
everything needed to review this change (templates, goldens, diffs,
tests) is inside it.

### 14.5 Commit S1-E (OPTIONAL — exists only if OD-S1-2 approves) — stale budget-literal cleanup

**Goal.** Delete/re-point the two stale budget numerals ("~100M"
`PROPOSAL_REASONING_PROMPT:284`; "10 GB" causal_reasoning_stage.md:145)
to the [HARDWARE CONTEXT] deferral pattern (roadmap §14 resolved row).
Also the single declared carve-out from non-goal N10.
**Scope.** Two prose lines + regeneration R3 (§13) + the 2 pinned
`test_prompt_ceiling_policy` sentences if touched.
**Implementation plan.**
- [ ] **CAPTURE FIRST**: the legacy reasoning SYSTEM render has NO
      golden today (§8.1 PB-0 row, finding F6a) — capture a Step-01
      baseline of it BEFORE editing :284, otherwise the edit lands on
      an unpinned surface.
- [ ] Edit the two lines; regenerate the just-captured golden + any
      affected `pb3_*` golden in the same commit with provenance.
- [ ] per further inspection.
**Validation.** Packs 1-2. **Acceptance.** No numeral budget literal
in proposer surfaces (extending the existing `<10 GB VRAM` absence
pin); goldens regenerated with provenance. **Failure cases.** none
beyond golden hygiene. **Evidence.** (after execution).
**Boundary.** Isolated, clearly-labeled, skippable.

### 14.6 Commit S1-F — docs closeout + PR readiness

**Goal.** This ledger fully reconciled ([x] with evidence); node doc
sync (`nodes/ml_model_proposal_agent/ml_model_proposal_agent.md` —
prompt-surface documentation current per the pre-merge doc-sync rule);
final full-suite + static gates at the executable head (pack 5),
clean tree; PR READY FOR OPERATOR REVIEW (never merge).
**Scope.** docs + any final test bookkeeping. **Plan.** [ ] ledger
reconciliation; [ ] node .md quote-verified against merged-state
flags/defaults; [ ] pack-5 run from a clean tree, verdict from the
log. **Acceptance.** CI green on the exact head; every §14 box [x]
with evidence or explicitly deferred with reason; §16 checkpoint
table filled. **Boundary.** docs-only.


## 4. Prompt-delta accounting (required at implementation)

Because this PR deliberately grows three stage system prompts, the
final ledger MUST record, per stage:

| Field | Requirement |
|---|---|
| files/goldens changed | exact list (expected: the `pb3_*_system.txt` set named in parent §13 R2) |
| added bytes / characters | measured per stage, from the golden diff |
| token delta | ONLY if a trustworthy local tokenizer is already available; otherwise state "token count unavailable — bytes/characters recorded instead". **Do not add a tokenizer dependency for this.** |
| why intentional | one line tying it to the dead-seam closure (roadmap §0 rule 8) |
| unchanged surfaces | explicit confirmation that USER prompts, `label=` values and `components=` key sets are unchanged (WF-3 golden stays green) |

## 5. Checkpoint C — PRE-MERGE (operator correction, OD-S1-4)

Every "post-merge chain evidence" formulation is superseded. The
bounded `--is_pseudo_llm` production-entry iteration:

- runs AFTER this PR's implementation is complete;
- runs ON its final executable head;
- runs BEFORE the PR is declared READY FOR OPERATOR REVIEW;
- attaches its log + prompt dump to the PR evidence packet;
- requires no real LLM and no API cost.

Unit goldens and the workflow-tier capture remain the primary
evidence; the chain run is a production-entry smoke proving the render
reaches the real boundary through the real entry point.

Known coverage limit (first review, F11): the dump hook covers the
proposing stage only (`ml_model_proposal_agent.py:1897-1900`), while
OD-S1-3(a) places the block in all three; the workflow-tier capture
covers the other two. Accepted, recorded, not silently glossed.

## 6. Validation and dependencies

- **Starts from merged PR 01a** — never implemented in parallel.
- Packs 1-4 of parent §12, plus the pre-merge chain evidence (§5).
- The regenerated goldens are the ONLY expected byte changes; every
  other Stage-A golden stays byte-identical (a diff outside parent
  §13's R2 set is a defect).
- Final executable head: full `pytest tests/unit/ -m "not real_run"`,
  ruff check + format, pyright, exact-head CI.

## 7. Acceptance criteria (observable)

- [ ] The shipped `task_description` appears verbatim in all three
      rendered stage system prompts, captured at the LLM boundary.
- [ ] Exactly the goldens named in parent §13 R2 changed; the diff is
      attached and each changed byte is attributable to the JOIN.
- [ ] WF-3's component-key-set golden is UNCHANGED (the JOIN renders
      into the existing `system_prompt` component — a new key would be
      a design failure, not a regeneration).
- [ ] FX-1 contrast: swapping ONLY the description text changes only
      the description-derived block.
- [ ] The two stale budget literals are gone from the proposer
      surfaces, with the legacy reasoning SYSTEM render captured
      BEFORE the edit (parent §13 R3 capture-first rule).
- [ ] The pre-merge chain log is attached and shows the rendered task
      background at the production entry.
- [ ] Prompt-delta accounting (§4) is filled in with measured numbers.
