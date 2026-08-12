# PR 01a — Contract-derived prompt extraction (Step 01, child 1 of 2)

## Status

**FROZEN / OPERATOR APPROVED FOR IMPLEMENTATION (2026-08-12).**
OD-S1-5 approved: PR 01a implementation is authorized. This document
is now the LIVE IMPLEMENTATION LEDGER — checklists, evidence,
deviations and discoveries are recorded here as work proceeds.

### Kickoff record (mechanical, 2026-08-12)

| Item | Value |
|---|---|
| master at kickoff | `9400ec73ba43f007230592abffc9387d71a94767` |
| parent design SHA | `9400ec73` (same commit — designs live on master) |
| PR-01a child design SHA | `9400ec73` |
| branch point | master `9400ec73` |
| implementation branch | `feat/generic-framework-step-01a-contract-derived-prompt-extraction` |
| clean-tree fingerprint at kickoff | `bd3e625c9ea6d5e075b10911e42031bcb0c64e28fa9bda9c040f81b5b2a5ebf1` |
| prerequisite | Step 00 merged `e80da078` (ancestor of HEAD — verified), post-merge sync `47fdf6e5` |
| working tree at kickoff | clean (0 changes) |

Parent design (the audit, authority map, coupling inventory, baseline
map, flexible-input boundary, test-disposition inventory, acceptance
packs, golden policy and mutation catalogue):
`../step_01_proposer_hypothesis_space.md`. This child does NOT repeat
that material — it owns PR-level scope, commits, acceptance and the
live implementation ledger.

Prerequisite: Step 00 merged (PR #198 → `e80da078`) — satisfied.
Blocks: **PR 01b** (`pr_01b_task_description_join.md`) must not start
until this PR merges.

## 1. Final effect of THIS PR

Every Step-01-owned task fact that a proposer surface states — declared
input/output shape, class count, task type, and which loss families are
legal for which output type — is RENDERED from its existing authority
(`ForwardContract` via `render_forward_contract`;
`CLASSIFICATION_LOSSES`/`REGRESSION_LOSSES`) at every surface that
states it, instead of being restated as a prompt literal.

**Central acceptance claim: the final TIDMAD prompt bytes are
UNCHANGED.** This PR is pure Stage-A extraction parity. It contains no
intentional default-prompt-byte change; if any golden's bytes move,
that is a defect, not an expected diff.

## 2. Scope

OWNS (commits detailed in §4):

- `S1-A0` PB-3 fixture completion (test-only prerequisite);
- `S1-A` legacy commit-prompt extraction + renderers;
- `S1-B` pipeline template extraction;
- the contract/rank/loss portion of the former `S1-D`: rungs **B-i**,
  **B-ii**, **FX-2**, **FX-5** and their mutations;
- the **PB-4 boundary-capture re-target** (parent §11.1, 2nd-review
  R2-4) and mutation **M-1b**;
- the standalone-CLI disposition (§3 below).

Explicitly does NOT own (they are PR 01b's):

- the task-description JOIN (former `S1-C`);
- the task-description contrast (13.4-A / FX-1);
- the stale budget-literal cleanup (former `S1-E`);
- Checkpoint-C chain evidence;
- ANY intentional default TIDMAD prompt-byte change.

## 3. Frozen dispositions resolved for this PR (source-grounded)

### 3.1 Standalone node CLI — LOAD THE SHIPPED CONFIG (frozen)

Audit (main agent, 2026-08-12):

- The CLI is a **documented architectural surface**, not an accident:
  `docs/architecture.md:164` ("Has CLI interface ✅") and `:273`
  ("CLI interface: `argparse` entry point — called by humans for
  standalone use"). `main()` at
  `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:2136`,
  guarded at `:2196`.
- It constructs `ProposalInput` from **interpretation + storage only**
  (`:2163-2171`) — no `task_description`, no `forward_contract`, so
  both take schema defaults today.
- That is harmless TODAY only because the commit prompt has zero
  substitution. After this PR's extraction, an empty contract would hit
  the parent's §6.2 rule 6 fail-closed path — i.e. extraction would
  BREAK a documented surface.
- No script, sdsc launcher, doc procedure or test invokes it
  (verified); its support status rests on the architecture contract,
  not on call sites.
- Precedent check: **no node CLI loads the task config today**; the
  implementor instead papers over the gap with a silent literal
  fallback (`ml_model_implementor.py:980`,
  `output_shape or "[B, C, T] float32"`) — the anti-pattern this PR
  must NOT copy (it is 2nd-review R2-9, owned by step 03/04).

**Disposition:** the CLI loads the shipped config through the CANONICAL
loader, exactly as every other production caller does
(`workflows/model_exploration.py:2105`, `scripts/pr3_l2_calibration/
runner.py:231`, `scripts/checkpoint_l_gate1.py:189` — all call
`load_task_config()` with no path argument):

```text
cfg = load_task_config()
task_description = get_task_description(cfg)          # regime-A default
forward_contract = ForwardContract(**cfg["forward_contract"])
```

No second loader path is invented; the cwd-relative default is the
same assumption every existing caller makes (parent §13.2 hazard —
stated, not newly introduced). Consequence: the fail-closed rule then
fires only for a genuinely missing/invalid config, never merely
because the CLI omitted the fields.

### 3.2 Loss-authority import — DIRECT MODULE-LEVEL IMPORT (frozen)

- Authority: `ml_models/models_format_sandbox.py:368,371`
  (`CLASSIFICATION_LOSSES`, `REGRESSION_LOSSES`).
- That module imports **only `typing` and `pydantic`** (`:1-3`): no
  torch, no registry population, no import back into `nodes/` — so a
  plain module-level import is safe. No lazy import is required, and
  no circular-import risk exists. (Contrast: the proposer's existing
  `ml_models.models_sandbox` import at `:106` is function-local
  precisely because THAT module is heavy.)
- **No production consumer imports these frozensets today** —
  verified repo-wide. This PR's renderer is therefore their FIRST
  production consumer, satisfying the roadmap's seam-with-consumer
  rule.
- Rendering obeys parent §6.2 rule 5: `sorted()` for membership
  listing (frozenset iteration order is process-dependent — measured:
  3 processes, 3 orders) and `Literal.__args__` for the alphabet.

## 4. Implementation phases (per-commit 8-section checklists)

Standing rules: parent §18.1 (autonomous semantic commits;
minimum-sufficient per-commit testing; full suite + static + CI once at
the final executable head; stop only for material deviation).

### 14.0 Commit S1-A0 — PB-3 fixture completion (test-only prerequisite)

**Goal.** Make the PB-3 fixture contract a complete, self-consistent
TEST-OWNED declaration so that later extraction commits' byte-parity
claims are meaningful (§8.1a; adversarial finding F6b).

**Scope.** `tests/unit/agent/ml_model_proposal_agent/
test_step00_prompt_goldens.py` fixture contract (`:153-166`) +
regeneration R1 of the affected `pb3_*` goldens. NON-goals: zero
production diff; no renderer yet; no template edit; PB-4/PB-0/CFG/WF-3
goldens untouched.

**Implementation plan.**
- [x] Inspected the fixture (`test_step00_prompt_goldens.py:153-170`)
      and all nine `pb3_*` goldens. FINDING: only
      `pb3_proposing_{explore,exploit}_system.txt` carry the contract
      block at all (via `{forward_contract}` at
      `proposing_stage.md:131`); the comparison/causal systems and all
      three user prompts carry ZERO contract tokens — confirming §8.1a
      and bounding this commit's blast radius to two goldens.
- [x] Populated `num_classes=192` + `task_type="classification"` and
      aligned the shapes/descriptions (`[B, 192, T] float32`,
      "logits over 192 classes"). **Deliberately 192, not the shipped
      256** — a test-owned value makes an accidentally-hardcoded
      production literal visible in later commits instead of silently
      agreeing with the fixture. Rationale comment landed in-file.
- [x] Regenerated the two affected goldens through the same real
      `run()` capture the Step-00 harness uses. Diff is EXACTLY the
      declared values (6 lines total across both files):
      `output: [B, 256, T]…256 classes` → `[B, 192, T]…192 classes`,
      plus the newly-emitted
      `Task type: classification (per-timestep 192-class).`

**Validation plan.** [x] Packs 1-2: **860 passed, 21.6 s**
(`tests/unit/agent/ml_model_proposal_agent/ tests/unit/workflows/
tests/unit/agent/llm_bridge/ tests/helpers/test_recording_fakes.py`).
[x] `git status` confirms the ONLY changed goldens are the two
declared ones. [x] ruff check + format clean on the touched test.

**Acceptance criteria (observable).** The fixture contract has no
defaulted semantic field; the regenerated goldens differ from their
predecessors ONLY where the fixture's declared values appear; PB-4,
PB-0, CFG-1/2/3a/3b and WF-3 goldens are byte-unchanged.

**Failure/edge cases.** [x] EXERCISED: seven of the nine goldens did
NOT change. That is the designed outcome, recorded as evidence rather
than forced — those surfaces derive nothing from the contract today,
which is precisely the gap S1-B closes for the proposing stage and
which the roadmap leaves for the comparison/causal stages (they
receive the contract only via the JOIN in PR 01b, if at all).

**Empirical confirmation of §4 row F21 (2nd-review R2-2).** The
regenerated goldens now literally contain
`Task type: classification (per-timestep 192-class).` — produced by
`render_forward_contract:206-212`, not by any template. This is the
production renderer asserting a TEMPORAL axis for a contract that
never declared one, visible in a test-owned fixture that is not
TIDMAD. It is kept byte-identical here (grandfathered, §6A.4) and
routed to step 02/03; §9.5 whitelists it so the FX-2/FX-5 rungs do
not fail on it.

**Verification commands and evidence.**
- `pytest tests/unit/agent/ml_model_proposal_agent/ tests/unit/workflows/ tests/unit/agent/llm_bridge/ tests/helpers/test_recording_fakes.py -q` → **860 passed, 21.6 s**.
- `git status --short tests/` → exactly 2 golden files + the fixture file.
- `ruff check` / `ruff format --check` on the touched test → clean.

**Commit boundary.** Test-only, no production file touched.

### 14.1 Commit S1-A — legacy commit-prompt extraction + renderers (byte-parity)

**Goal.** The commit prompt's task facts (shapes/classes/loss
legality) derive from ForwardContract + the loss frozensets; TIDMAD
render byte-identical; the two new proposer-local renderers exist WITH
their first consumer.

**Scope.** `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py`
(PROPOSAL_COMMIT_PROMPT → template + render at the :1385 call site;
new renderer helpers, module-local); tests:
`test_step00_prompt_goldens.py` PB-4 system assert re-target,
`test_contract_reassertion.py` re-target (§11.1),
new renderer unit tests. NON-goals: pipeline templates (S1-B), any
rendered-byte change, schemas, protocols, other nodes.

**Implementation plan.**
- [ ] Inspect the commit prompt + call site + `render_forward_contract`
      + frozensets; fix the exact placeholder set (inspect-first).
- [ ] Loss-legality renderer (frozensets → legality prose tokens) +
      contract-prose renderer (ForwardContract → shape/class tokens),
      typed, docstringed, module-local.
- [ ] Template conversion + render at :1385 (first consumer, same
      commit).
- [ ] PB-4 re-target (golden bytes untouched) + render-vs-constant
      differential (§8.2).
- [ ] `test_contract_reassertion.py` re-target to the render, TIDMAD
      variant (§11.1 row 1; contrast variant lands in S1-D).
- [ ] Renderer unit tests incl. empty-input behavior pins.

**Validation plan.** Pack 1 + pack 2 (§12); ruff/format on touched
files; mutations M-2 partial (commit-prompt token) executed and
recorded.

**Acceptance criteria (observable).** `pb4_legacy_commit_system.txt`
passes UNMODIFIED against the render; `git diff` shows zero template
literal for the extracted tokens (grep evidence recorded); the
differential test proves constant ≠ golden while render == golden;
contract-reassertion re-target red under mutation M-2, green
otherwise.

**Failure/edge cases.** Empty ForwardContract (legacy CLI main(),
test fixtures) → render degrades exactly as `_render_task_background`
does today (regime-A, pinned); regex-extraction in the re-targeted
reassertion test must tolerate the placeholder line shape.

**Verification commands and evidence.** (recorded after execution;
never claim an unrun test passed)

**Commit boundary.** Test-and-production change for the LEGACY commit
surface only; no pipeline template touched; goldens byte-identical.

### 14.2 Commit S1-B — pipeline template extraction (byte-parity)

**Goal.** proposing_stage.md's **tier-(i)** hardcoded fact lines
(§4.1) and its loss-legality prose derive via template_vars from the
S1-A renderers; TIDMAD render byte-identical (all 9 PB-3 goldens
unmodified, on top of the S1-A0 fixture completion). Tier-(ii)/(iii)
lines (:41, :70-71's dtype-stripped forms, :74's "amplitude bins", the
regressor branch) stay LITERAL unless OD-S1-7 approves the formatting
rule.

**Scope.** `agent/prompt_templates/proposal/proposing_stage.md` (+
`_run_pipeline` template_vars additions); tests: new rendered-layer
pins mirroring `test_proposer_task_config.py`'s shape. NON-goals: the
task-description placeholder (S1-C); comparison/causal templates
(no extractable fact rows — §4); wording changes; the
double-substitution quirk (kept byte-identical).

**Implementation plan.**
- [ ] Inspect proposing_stage.md line-by-line against the §4 fact
      rows; fix the placeholder set; verify no prose mention of a new
      placeholder name exists elsewhere in the template (the :177/:235
      double-render hazard — choose collision-free names).
- [ ] template_vars entries from the S1-A renderers.
- [ ] Byte-parity check of all 9 PB-3 goldens (against the S1-A0
      regenerated set — §8.1a; a red here after S1-A0 is production
      drift, not fixture rot).
- [ ] Rendered-layer pins: TIDMAD tokens present; template file no
      longer contains the extracted literals (template-layer absence
      pin, new).

**Validation plan.** Pack 1 + 2; mutation M-5 (one-sided template
edit) executed and recorded.

**Acceptance criteria.** All 9 PB-3 goldens (as regenerated by
S1-A0) + label-sequence pin + WF-3 key-set golden pass UNMODIFIED by
this commit; grep shows the tier-(i) literals absent from the
template while the tier-(ii)/(iii) literals are still present AND
listed in the commit message as knowingly retained; new absence pin
red if an extracted literal is reintroduced (M-4 pre-check);
loss-list render order matches §6.2 rule 5 (mutation M-8 red on a
shuffled source).

**Failure/edge cases.** Placeholder-name collision with prose (global
str.replace) — checked by inspection + a collision guard assert in
the new tests; a missing template_vars key ships the literal
placeholder to the LLM (silent no-op) — covered by the rendered pins.

**Verification commands and evidence.** (after execution)

**Commit boundary.** proposing_stage.md + template_vars + tests;
rendered TIDMAD bytes unchanged.

### 4.4 Commit 01a-D — contract/rank/loss contrast rungs + mutation closeout

Scope note: this is the CONTRACT/RANK/LOSS half of the former `S1-D`.
The task-description contrast (13.4-A / FX-1) moves to PR 01b.


**Goal.** 13.4-A and 13.4-B land (§9), plus — under OD-S1-6(a) — the
FX-2/FX-5 rank-agnosticism prose rungs (§9.4) that convert "the templates
are rank-agnostic" from a claim into a test; the §15 battery is fully
executed and recorded; contract-reassertion contrast variant lands.

**Scope.** New tests + fixtures only (test-only commit). NON-goals:
any production diff.

**Implementation plan.**
- [ ] 13.4-A fixture + asserts (§9.1).
- [ ] 13.4-B rungs **B-i** (regressor, the roadmap's named fixture)
      and **B-ii** (16-class classifier) as SEPARATE same-axis
      fixtures (§9.2), B-ii carrying the contrast half of the
      re-targeted contract-reassertion pins.
- [ ] FX-2 rung (§9.4): rank-4 NEUTRAL-axis contract profile + an
      unfamiliar `task_type`; assert (a) the declared rank-4 text and
      the opaque `task_type` label render on all Step-01 surfaces, and
      (b) zero `[B, 256, T]`/`[B, T]`/"amplitude bins"/"256 denoising"
      residue **within the contract-DERIVED blocks only** — the three
      §9.5 whitelisted survivors are expected and must not be
      "fixed". One axis only — description and losses untouched.
- [ ] FX-5 rung (§9.4): multi-channel temporal declaration; assert it
      renders verbatim with no scalar-`[B,T]` residue in the derived
      blocks (proves "time series" is not assumed scalar).
- [ ] Record FX-3/FX-4 as DEFERRED prerequisites for the contract-owning
      step (§6A.5 binding dependency) — no stub, no placeholder test.
- [ ] Execute remaining mutations (M-3, M-4, M-7, M-8, M-9) + the flexible-input
      mutations N-RANK/N-RESIDUE/N-OPAQUE (§15.1) with mutation-proof
      hygiene (cache clear, count==1, baseline re-run); record the
      dossier in this document.

**Validation plan.** Packs 1-3; full battery dossier.

**Acceptance criteria.** Each fixture varies exactly one axis
(reviewed against §9/§9.4 atomicity notes — no fixture changes
description AND rank AND dtype); every §15/§15.1 mutation has a
recorded RED and a restored GREEN; zero surviving behavior-changing
mutations; N-RESIDUE specifically proves the FX-2/FX-5 rungs catch a
shadow literal that TIDMAD parity alone cannot; the design's F3/F4
rows read DEFERRED with an owner, never "covered".

**Failure/edge cases.** A contrast fixture accidentally varying two
axes (e.g. alt description that also implies different shapes) — the
§9 fixtures pin the OTHER axis explicitly to the TIDMAD value.

**Verification commands and evidence.** (after execution)

**Commit boundary.** Test-only.


**PR-01a carve-out (operator split, 2026-08-12).** Within this commit:
- LANDS here: B-i, B-ii, FX-2, FX-5 and mutations M-2..M-9,
  N-RANK/N-RESIDUE/N-OPAQUE, M-1b.
- MOVES to PR 01b: fixture 13.4-A / rung FX-1 (task-description axis)
  and mutations M-1/M-4 insofar as they depend on the JOIN.

## 5. Validation and dependencies

- Packs 1-3 of parent §12 (fast inner loop ≈3 s; Stage-A parity pack;
  the contrast rungs this PR owns).
- Stage-A hard gates: PB-0, PB-3 (9 goldens), PB-4 (2 goldens), WF-3
  component-key-set golden, CFG-1/2/3a/3b — all byte-unchanged.
- Final executable head: full `pytest tests/unit/ -m "not real_run"`,
  ruff check + format, pyright, exact-head CI.
- Checkpoint C is NOT closed by this PR (no chain evidence required
  here); Checkpoint A is.

## 6. Acceptance criteria (observable)

- [ ] Every named Stage-A golden is byte-identical after the last
      commit — `git diff` on `tests/unit/agent/**/goldens/` and
      `tests/unit/workflows/goldens/` shows ZERO changed bytes.
- [ ] The re-targeted PB-4 system assert captures at the legacy `run()`
      LLM boundary, proven by mutation **M-1b** going RED when the
      render call at `ml_model_proposal_agent.py:1385` is deleted.
- [ ] FX-2/FX-5 assert derived-block residue only, and the three §9.5
      whitelisted survivors are present and untouched.
- [ ] The standalone CLI runs end-to-end with a complete commit prompt
      (§3.1), and the fail-closed path fires only on a missing/invalid
      config.
- [ ] No production default prompt bytes changed anywhere in this PR.
