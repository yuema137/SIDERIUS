# PR 01a — Contract-derived prompt extraction (Step 01, child 1 of 2)

## Status

**MERGED (2026-08-12).** PR [#199](https://github.com/Galileo-Sandbox/SIDERIUS/pull/199)
was approved at the operator merge gate and merged into `master`.

| Item | Value |
|---|---|
| Merge commit | **`39f89f52eea12901ee0ae4254bba56d2248f5418`** (parents `6f3866b6` + `d84f6711`) |
| PR | **#199**, merged 2026-08-12T20:19:27Z, merge-commit strategy (matching PR #198) |
| Final PR head | **`d84f6711`** |
| Final EXECUTABLE head | **`fe4ec2e5`** — the three trailing commits are docs-only |
| Exact-head CI | **SUCCESS** on `d84f6711` (run 31635897741, 11m44s) and on `8a05bbe8` (run 31633988555, 11m05s); both include **pyright strict (blocking)** |
| Full unit suite | **8407 passed, 3 skipped** at `fe4ec2e5` from a clean tree |
| Merge gate | **PASS** — see the parent's "Merge gate" block and §8 below |

This document remains the historical implementation ledger for PR 01a.
It is now CLOSED: no further implementation is recorded here. PR 01b
has its own document and is UNBLOCKED / NOT STARTED.

Ledger convention note: the sections below were written DURING
implementation and are preserved in that voice (including the
merge-gate finding that this status table was once stale). They are
history, not current instructions.

### Live implementation status (mechanical, 2026-08-12)

| Semantic commit | State | SHA | Title |
|---|---|---|---|
| `S1-A0` | **COMPLETE** | `4a11e4e8` | `test(step01a-S1-A0): complete the PB-3 test-owned ForwardContract fixture` |
| `S1-A` | **COMPLETE** | `a3a97014` | `feat(step01a-S1-A): render the legacy commit prompt from its declarations` |
| `S1-B` | **COMPLETE** | `aa1127d7` | `feat(step01a-S1-B): derive the proposing stage's loss legality from the authority` |
| `S1-D` (§4.4) | **COMPLETE** | `e27e6af0` | `test(step01a-S1-D): contrast rungs B-i/B-ii/FX-2/FX-5 + mutation closeout` |
| closeout evidence | **COMPLETE** | `fe4ec2e5` | `test(step01a): prove the standalone-CLI disposition is reachable` |
| final validation record | **COMPLETE** | `8a05bbe8` | `docs(step01a): record final-head validation evidence` |
| merge-gate reconciliation | **COMPLETE** | (this commit) | §8 shipped-profile parity proof, §1 claim reconciliation, this table |
| PR closeout (§5/§6) | **COMPLETE** | — | PR #199 open, CI green, full suite + static gates recorded below |
| MERGE | **DONE** | `39f89f52` | `Merge pull request #199` — operator-approved 2026-08-12 |

**PR: [#199](https://github.com/Galileo-Sandbox/SIDERIUS/pull/199)**
(`feat/generic-framework-step-01a-contract-derived-prompt-extraction`
→ `master`). Final executable head **`fe4ec2e5`**; docs-only commits
follow it. **STATUS: MERGED** as `39f89f52` after operator approval at
the merge gate.

| Final gate | Result |
|---|---|
| `pytest tests/unit/ -m "not real_run"` at `fe4ec2e5`, clean tree | **8407 passed, 3 skipped**, 538 s, pytest exit code 0 |
| `ruff check .` / `ruff format --check .` | clean / 802 files formatted |
| **Exact-head CI** on `8a05bbe8` | **SUCCESS** — run 31633988555, "Lint + Type + Unit Tests", 11m05s, including the **pyright strict (blocking)** step that cannot run locally (Node v10.19.0) |

A NOTE ON THIS TABLE'S HISTORY (operator merge-gate finding, kept as a
process record): the `8a05bbe8` version of this document still showed
`S1-D` as "(this commit)" and the closeout as IN PROGRESS, with no PR
number, no final SHA and no CI record. The cause was a deliberate but
wrong decision to keep CI state OUT of the ledger to avoid moving the
head — which silently left the whole closeout state unrecorded, not
just the CI line. The correct handling is the one used here: record it,
push, and re-verify CI on the new exact head.

Branch base: master `6f3866b6` (designs frozen) — the four
implementation commits are the only commits ahead of master on this
branch. **PR 01b has NOT started** — no branch, no commit, no file
touched.

S1-D lands one new test file
(`tests/unit/agent/ml_model_proposal_agent/test_step01a_contrast_rungs.py`,
372 lines / 31 cases) plus this ledger and the parent's status pointer.
**Zero production diff in S1-D.**

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

**Central acceptance claim (stated with its one approved exception —
operator merge-gate reconciliation, 2026-08-12).**

1. **Exact parity where it is claimed.** Every Step-00-goldened
   proposer surface and the STANDARD PRODUCTION WORKFLOW path are
   byte-identical under the shipped TIDMAD profile. This is pure
   Stage-A extraction parity: if a golden's bytes move, that is a
   defect, not an expected diff.
2. **No default production-pipeline prompt change.** There is no
   task-description JOIN and no PR-01b prompt-behavior change here.
3. **One explicitly approved compatibility repair.** The documented
   STANDALONE node CLI now receives the canonical shipped task framing
   it previously omitted — see §6 item 5 and §3.1. Its reasoning
   prompt therefore differs from before this PR, by design and by
   prior operator approval of the §3.1 disposition. It is not covered
   by any golden and does not touch the workflow path.

The earlier phrasing of this section — "the final TIDMAD prompt bytes
are UNCHANGED … no intentional default-prompt-byte change" — was too
strong once §3.1 landed, because it read as an unqualified claim over
EVERY surface including the CLI. Corrected here rather than in a
footnote so the top-level claim and the §6 exception cannot be read as
contradicting each other.

**Direct shipped-profile evidence (merge-gate, §8).** The parity claim
is proven against the merge base for the SHIPPED 256-class profile, not
only against the 192-class PB-3 fixture — see §8.

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
- ANY intentional default TIDMAD prompt-byte change on a
  Step-00-goldened surface or the standard workflow path. (The one
  approved CLI convergence repair of §3.1 is NOT such a change — see
  §1 item 3; it is owned here, not by PR 01b.)

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
- [x] Inspected all sites. Placeholder set fixed to TIER (i) ONLY, from
      the shipped declaration's actual byte values: `{INPUT_SHAPE}` ×3,
      `{OUTPUT_SHAPE}` ×2, `{OUTPUT_DESCRIPTION}` ×1,
      `{CLASSIFIER_LOSSES}` ×1, `{REGRESSOR_LOSSES}` ×1. Verified
      byte-identity of each against `configs/task_config.yaml:19-35`
      BEFORE substituting: `input_shape="[B, T] int64"`,
      `output_shape="[B, 256, T] float32"`,
      `output_description="per-timestep logits over 256 denoising
      classes"`. NOTE: the prompt's `(per-timestep ADC class indices)`
      parenthetical is NOT the shipped `input_description`
      ("raw signal, integer class indices 0-255"), so it stays literal
      — a source discovery that keeps one more token out of tier (i).
- [x] `_render_loss_legality(frozenset) -> str` (sorted, backticked)
      and `_render_commit_system_prompt(fc) -> str`, both typed,
      docstringed, module-local; plus `ProposalContractRenderError`.
      Import of the authority is module-level per §3.2.
- [x] Template conversion + render wired at the real call site
      (first consumer, same commit).
- [x] PB-4 re-targeted to a BOUNDARY capture through the legacy
      `run()` path (`_LegacyCommitRecorder` + `_run_legacy_capture`),
      golden bytes untouched; render-vs-constant differential added.
- [x] `test_contract_reassertion.py` re-targeted to the render under
      the shipped profile (helper `_rendered_commit_prompt()`).
- [x] Renderer unit suite added:
      `tests/unit/agent/ml_model_proposal_agent/
      test_step01a_contract_renderers.py` (14 tests).

**SOURCE DISCOVERY — the boundary capture immediately earned its keep.**
The first run of the re-targeted PB-4 test FAILED because the capture
ran under the PB-3 *fixture* profile (192 classes) while the golden
pins the *shipped* render (256). A direct-helper assert would have
silently passed the wrong profile. Fixed by driving the capture with
`forward_contract=_shipped_forward_contract()`; recorded in-test.

**Validation plan.** [x] Proposer package **536 passed, 2.0 s**;
affected suites (`tests/unit/agent/ tests/unit/workflows/
tests/unit/ml_models/`) **4030 passed** at the point of measurement,
with the five remaining fail-closed fixtures then fixed (below).
[x] ruff check + format clean on every touched file.

**Acceptance criteria (observable).** `pb4_legacy_commit_system.txt`
passes UNMODIFIED against the render; `git diff` shows zero template
literal for the extracted tokens (grep evidence recorded); the
differential test proves constant ≠ golden while render == golden;
contract-reassertion re-target red under mutation M-2, green
otherwise.

**Failure/edge cases.** [x] EXERCISED. The design's rule 6.2-6
(fail-closed) fired in 20 pre-existing tests whose fixtures never
declared a contract — 15 in the proposer package, 5 in
`tests/unit/agent/protocols/test_pr_e_candidate_id_transport.py`.
Diagnosis (not a production defect, not a reason to weaken the rule):
production ALWAYS supplies a contract (the workflow via
`load_task_config()`, and now the CLI per §3.1), so the fixtures were
relying on a laxness that the extraction legitimately removes. Each
fixture now declares a hermetic test-owned contract (explicit, not
config-loaded, to keep the unit tier cwd-independent). Files touched:
`test_proposal_agent.py`, `test_preflight_advisory.py`,
`test_pipeline_runner.py`, `test_pr_e_candidate_id_transport.py`.

**MUTATION BATTERY (executed; each restored and re-verified green).**

| Mutation | Result |
|---|---|
| **M-1b** delete the render call at the production call site | **RED** on the PB-4 boundary assert — *this is the acceptance proof that the capture is at the boundary*; a direct-helper test would have stayed green |
| **M-2** perturb a rendered token (`output_shape + " "`) | **RED** (2 tests) |
| **M-4** re-inline a hardcoded `[B, T] int64` at ONE of three `{INPUT_SHAPE}` sites | **SURVIVED at first** → classified as a TEST-ARCHITECTURE gap, not an equivalent mutation: `"<declared>" in rendered` is satisfied by the other two sites, so an `in` assertion cannot see a partial shadow. **Suite strengthened** with `test_no_shadow_literal_survives_a_non_tidmad_profile` (absence of `[B, T] int64` / `[B, 256, T] float32` under a rank-4 profile, scoped to exclude the §9.5 whitelisted survivors). M-4 re-run → **RED** |
| **M-5** change the loss AUTHORITY (`CLASSIFICATION_LOSSES + zz_probe`) | **RED** — proves the prompt derives from the authority, not a copy |
| **M-8** iterate the frozenset instead of `sorted()` | **RED** (2 tests) — the flaky-order defect rule 6.2-5 exists to prevent |
| **M-9** remove the fail-closed guard | **RED** (4 tests) |

**Verification commands and evidence.**
- `pytest tests/unit/agent/ml_model_proposal_agent/ -q` → **536 passed, 2.0 s**.
- `pytest tests/unit/agent/ tests/unit/workflows/ tests/unit/ml_models/ -q` → 4030 passed / 5 fail-closed fixtures (since fixed).
- `pytest tests/unit/agent/protocols/ -q` → **106 passed**.
- Byte-parity probe: `_render_commit_system_prompt(shipped) == pb4 golden` → **True**; `PROPOSAL_COMMIT_PROMPT != golden` → **True**.
- ruff check + ruff format → clean on all touched files.

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
- [x] Inspected `proposing_stage.md` line-by-line against §4/§4.1.
      **SCOPE FINDING (source-grounded, narrows the plan):** of the
      four F5 loss sites in this template, only the output-contract
      TABLE cells are tier (i) — their `` `ce`, `focal`, `focal_cw` ``
      / `` `smooth_l1` `` form is byte-identical to
      `_render_loss_legality`. The other three state the SAME fact in
      three DIFFERENT surface forms — `:41` slash-separated
      (`ce/focal/focal_cw`), `:92` slash-separated inside quoted
      backticks, `:168` "or"-joined, and `:85-86` line-wrapped mid-list
      — so each would need its own formatting rule, which OD-S1-7
      explicitly rejects for this step. They stay literal and are
      routed with the tier-(ii) set to step 03. The table's
      dtype-dropped SHAPE column (`` `[B, 256, T]` float ``) is tier
      (ii) for the same reason and is likewise untouched.
- [x] Placeholder names `{CLASSIFIER_LOSS_LIST}` / `{REGRESSOR_LOSS_LIST}`
      chosen collision-free (verified absent from all nine templates
      before wiring — the global-`str.replace` double-substitution
      hazard).
- [x] `template_vars` entries added in `_run_pipeline`, fed by the
      S1-A renderers.
- [x] Byte-parity: all **9 PB-3 goldens pass UNMODIFIED** on top of
      the S1-A0 set.
- [x] Pins added (`TestS1BProposingStageDerivation`): template-layer
      ABSENCE pin (placeholders present, extracted literals gone —
      kept distinct from the rendered pins per the roadmap §13.3
      rule); a tier-(ii) RETENTION pin so nobody "finishes the job" by
      inventing a formatting rule; and an alphabet-count consistency
      pin (`LossConfig.loss_type` has five Literal members while the
      prose says "accepts five values") — the drift the extraction
      itself cannot catch, since those three sites stay literal.

**Validation evidence (executed).** Proposer package **539 passed,
2.0 s**; PB-3 ×9 byte-identical; ruff check + format clean.
Mutations, each restored and re-verified green:
**M-5b** one-sided template edit (placeholder re-inlined while the
renderer stays wired) → **RED** on the absence pin — the failure mode
byte-parity alone cannot see, since the render output is unchanged.
**M-5c** change the loss AUTHORITY (`+zz_probe`) → **RED** (4 tests,
incl. the PB-3 goldens) — the rendered stage tracks the authority.

**Original validation plan.** Pack 1 + 2; mutation M-5 (one-sided template
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

**Verification commands and evidence.**
- `pytest tests/unit/agent/ml_model_proposal_agent/ -q` → **539 passed,
  2.0 s** at the S1-B head (`aa1127d7`). Corroborated by the rescue
  session's read-only re-run on the same head WITH the uncommitted
  S1-D rung file present: **558 passed, 1.91 s** — 539 + the 19 new
  rung cases, i.e. the S1-B figure is exactly reproduced and nothing
  regressed.
- All **9 PB-3 goldens byte-identical** (unmodified on top of the
  S1-A0 regeneration); `git status --short` on the goldens directory
  showed no change through this commit.
- Mutations, each restored and re-verified green: **M-5b** (one-sided
  template edit — placeholder re-inlined while the renderer stays
  wired) → **RED** on the absence pin; **M-5c** (loss AUTHORITY
  `+zz_probe`) → **RED**, 4 tests including the PB-3 goldens.
- ruff check + ruff format --check → clean on every touched file.

**SCOPE FINDING RECORDED AS THE COMMIT'S PRIMARY EVIDENCE.** The
audited tier-(i) extraction is NARROWER than a naive loss-alphabet
sweep would be. Of the four F5 loss sites in `proposing_stage.md`,
only the output-contract TABLE cells are byte-identical to
`_render_loss_legality`; the other three state the same fact in three
DIFFERENT surface formats (`:41` slash-separated, `:92`
slash-separated inside quoted backticks, `:168` "or"-joined, `:85-86`
line-wrapped mid-list). Deriving those would require INVENTING new
formatting rules, which **OD-S1-7 explicitly rejects for this step**.
S1-B therefore extracted ONLY the source-audited tier-(i) legality
cells and left the rest literal, with a tier-(ii) RETENTION pin so a
later contributor cannot "finish the job" by inventing the formatting
semantics OD-S1-7 refused.

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
- [n/a] 13.4-A fixture + asserts (§9.1) — **MOVED to PR 01b** by the
      operator carve-out below (it is rung FX-1, the description axis).
- [x] 13.4-B rungs **B-i** (regressor, the roadmap's named fixture)
      and **B-ii** (16-class classifier) as SEPARATE same-axis
      fixtures (§9.2), B-ii carrying the contrast half of the
      re-targeted contract-reassertion pins.
      → `test_step01a_contrast_rungs.py::TestRungBi` (4 cases),
      `::TestRungBii` (3), `::TestContractReassertionContrast` (3).
- [x] FX-2 rung (§9.4): rank-4 NEUTRAL-axis contract profile + an
      unfamiliar `task_type`; assert (a) the declared rank-4 text and
      the opaque `task_type` label render on all Step-01 surfaces, and
      (b) zero `[B, 256, T]`/`[B, T]`/"amplitude bins"/"256 denoising"
      residue **within the contract-DERIVED blocks only** — the three
      §9.5 whitelisted survivors are expected and must not be
      "fixed". One axis only — description and losses untouched.
      → `::TestRungFX2` (4) + `::TestSecondStepOneSurface` (8, the
      "all Step-01 surfaces" half — see the SURFACE-COVERAGE finding).
- [x] FX-5 rung (§9.4): multi-channel temporal declaration; assert it
      renders verbatim with no scalar-`[B,T]` residue in the derived
      blocks (proves "time series" is not assumed scalar).
      → `::TestRungFX5` (3) + the FX-5 case in `::TestSecondStepOneSurface`.
- [x] Record FX-3/FX-4 as DEFERRED prerequisites for the contract-owning
      step (§6A.5 binding dependency) — no stub, no placeholder test.
      → recorded in the DEFERRAL REGISTER below; parent §9.4 already
      carries the rows. No test file was created for either rung, by
      design: a skipped placeholder would read as coverage.
- [x] Execute remaining mutations (M-3, M-4, M-7, M-8, M-9) + the flexible-input
      mutations N-RANK/N-RESIDUE/N-OPAQUE (§15.1) with mutation-proof
      hygiene (cache clear, count==1, baseline re-run); record the
      dossier in this document.
      → S1-D DOSSIER below. M-8/M-9 were already executed RED at S1-A
      (§14.1 dossier) against the same production sites and are
      cross-referenced rather than re-run; M-7 is DEFERRED with PR 01b
      because its steady-state assertion IS fixture 13.4-A.

**RE-JUSTIFICATION ON RESUME (required by the rescue record below).**
Every assertion in the rung file was re-derived from source before this
commit, not accepted because it was green. The re-justification produced
two corrections and one gap, all recorded below. The rendered commit
prompt was dumped under a rank-4 profile and read line by line to
separate DERIVED tokens from literal survivors:

| Line in the render | Class |
|---|---|
| `mathematical_definition` "Input: … Output: …" citation | DERIVED (`{INPUT_SHAPE}`, `{OUTPUT_SHAPE}`, `{OUTPUT_DESCRIPTION}`) |
| "- The input is fixed: …" hard-constraint line | DERIVED (`{INPUT_SHAPE}`) |
| `"classifier"` → output … (per-timestep class logits) | shape DERIVED, parenthetical LITERAL |
| `output_type` catalogue `[B, 256, T] per-timestep class logits` | LITERAL — tier (ii), §9.5 survivor |
| `[B, T] float32 (the denoised waveform directly)` (×2) | LITERAL — tier (iii), §9.5 survivor |
| `256 denoising bins per time step is contract-fixed` | LITERAL — tier (iii), §9.5 survivor |

That table is what licenses `_TIDMAD_DERIVED_ONLY_TOKENS =
("[B, T] int64", "[B, 256, T] float32")`: both tokens are reachable
ONLY through substitution (the catalogue's copy drops the dtype, so it
does not collide), while every whitelisted survivor is asserted
PRESENT rather than absent.

**FINDING — the rungs covered only ONE of the two Step-01 surfaces
(gap found by the resume re-justification; now closed).**

```text
Previous state (as written before the context break):
  all four rungs asserted against `_render_commit_system_prompt`
  alone — the LEGACY commit surface.

Audit evidence:
  §4.4 requires FX-2 to assert "the declared rank-4 text and the
  opaque `task_type` label render on ALL Step-01 surfaces". The
  production PIPELINE surface is the proposing stage, which receives
  the declaration through the pre-existing `{forward_contract}`
  placeholder fed at `ml_model_proposal_agent.py:1709` with
  `render_forward_contract(inp.forward_contract)`, plus the S1-B
  legality cells at `proposing_stage.md:70-71`. None of that was
  exercised by any rung.

Corrected understanding:
  the rank-agnosticism claim was demonstrated only on the surface the
  pipeline does NOT use. An in-tree precedent for rendering the other
  surface already existed
  (`test_proposer_task_config.py::TestProposingStageMdSubstitution`),
  so the gap was coverage, not feasibility.

Implementation consequence:
  added `TestSecondStepOneSurface` (8 cases) rendering
  `load_stage_prompt("proposing_stage", …)` with production-shaped
  template_vars. NO production change.

Validation consequence:
  mutation N-OPAQUE now reds on this surface specifically — before the
  addition, a `task_type` branch inside `render_forward_contract`
  would have left every PR-01a rung green.
```

**FINDING — residue must be judged relative to EACH rung's own
declaration (correction made during this commit).**

```text
Previous assumption:
  "TIDMAD residue" is a fixed token set that must be absent from every
  rung's derived block.

Evidence:
  the first run of the new surface test failed on rung B-ii with
  `'[B, T] int64' is contained here: input: [B, T] int64`. B-ii is the
  CLASS-COUNT rung: by the one-axis rule it holds the input shape at
  the TIDMAD value and varies only `num_classes`/`output_shape`. That
  token is its DECLARATION, not residue.

Corrected understanding:
  a blanket absence set silently mis-classifies a declared value as a
  shadow literal, and the "fix" would have been to weaken or exempt
  the rung — i.e. to damage the atomicity that makes the ladder
  meaningful.

Implementation consequence:
  `test_derived_block_states_this_rung_and_nothing_else` now asserts
  (a) both declared shapes are present and (b) each TIDMAD shape this
  rung does NOT declare is absent, computed as a set difference
  against the rung's own fields.

Validation consequence:
  strictly stronger — it now also catches a derived block that DROPS a
  declaration, which the absence-only form could not see. N-RESIDUE
  reds all four rungs through it.
```

**DEFERRAL REGISTER (§4.4 bookkeeping).**

| Item | State | Owner | Why not here |
|---|---|---|---|
| **FX-3** preset resolution | DEFERRED | step 02/03 contract owner | no preset mechanism exists (§6A.1); PR 01a is forbidden from creating one |
| **FX-4** mismatch rejection | DEFERRED — binding dependency (§6A.5) | step 02/03 contract owner | Step 01 cannot fail closed on a conflict it has no structured contract to represent |
| **FX-1 / 13.4-A** description axis | MOVED | PR 01b | needs the JOIN |
| **M-7** SQUID-residue check | MOVED | PR 01b | its steady-state assertion IS 13.4-A |

No stub or `skip`-marked placeholder was added for any of these: a
skipped test in the rung file would show up in a coverage read as a
rung that exists, which is the opposite of the record intended here.

**S1-D MUTATION DOSSIER** (hygiene for every row: target-string site
count asserted `== 1`, file backed up and restored, all `__pycache__`
cleared before AND after, mutated run RED, restored run re-verified
GREEN at **570 passed** for the proposer pack / **789 passed** for
proposer + workflows).

| Mutation | Site | Result |
|---|---|---|
| **M-3** authority disconnected pre-render (`_render_loss_legality(frozenset())` at the `{CLASSIFIER_LOSSES}` call site) | `ml_model_proposal_agent.py` | **RED** — 45 failed + 13 errors; the fail-closed guard raises and the re-targeted contract-reassertion pins error out. Overlaps M-9 by construction (both reach the same guard) — recorded rather than counted twice |
| **M-4 canonical** hardcoded task fact pasted BESIDE the placeholder (`{INPUT_SHAPE} (i.e. [B, 256, T] float32)`) | `ml_model_proposal_agent.py:373` | **RED** — 6 failed, and critically on the **13.4-B contrast fixture** exactly as §15 predicted (`TestRungBii::test_no_256_class_derived_residue`, `TestRungBi::test_no_classifier_derived_residue`, `TestRungFX2::…residue…`, plus the PB-4 raw-template pin). The S1-A run of M-4 used the shadow-at-a-substitution-site variant and needed a strengthened test; the canonical variant is caught by the rungs that did not exist then |
| **N-RANK** rank branch substituting TIDMAD for an unrecognised rank (`fc.input_shape if fc.input_shape.count(",") <= 2 else "[B, T] int64"`) | `ml_model_proposal_agent.py` | **RED** — 6 failed, **including FX-2's POSITIVE assertion** (`test_rank4_declaration_renders_verbatim`), which is the specific outcome §15.1 requires: a rank branch cannot be added without reddening FX-2 |
| **N-OPAQUE** renderer branches on `task_type` instead of rendering it as an opaque label | `workflows/task_config.py:206-212` | **RED** — 8 failed, including `TestSecondStepOneSurface::test_fx2_rank4_and_opaque_task_type_render_on_the_proposing_stage`. This is the mutation that the single-surface rungs would have MISSED |
| **N-RESIDUE** hardcoded `[B, 256, T] float32` reintroduced into the derived output line | `workflows/task_config.py:197` | **RED** — 10 failed, all four rungs through the derived-block pin. **Shipped-profile parity stayed GREEN**: CFG-2 (`test_forward_contract_render`) and the PB-4 commit goldens are absent from the mutated run's failure list, which is the §15.1 claim — the rungs catch a shadow literal that TIDMAD parity alone cannot |
| **M-8** iterate the frozenset instead of `sorted()` | — | **RED at S1-A** (§14.1 dossier, 2 tests). Same production site, unchanged by S1-D; not re-run |
| **M-9** remove the fail-closed guard | — | **RED at S1-A** (§14.1 dossier, 4 tests). Same site; not re-run |
| **M-7** SQUID-residue check | — | **DEFERRED to PR 01b** — its steady-state assertion is fixture 13.4-A, which the carve-out moved |

Zero surviving behavior-changing mutations. No mutation was excused;
the one gap the battery exposed (single-surface coverage) was closed by
adding tests, not by weakening the mutation.

**IMPLEMENTATION STATE — COMPLETE.** The rescue-session record below
is preserved verbatim because it is what forced the re-justification
that found the surface-coverage gap; read it as history, not as
current state.

The rung test file EXISTS and is untracked:
`tests/unit/agent/ml_model_proposal_agent/test_step01a_contrast_rungs.py`
(then 244 lines / 19 test cases; now 372 lines / 31 cases). It
implements exactly the four rungs this
PR owns — **B-i** (regressor contract), **B-ii** (16-class
classifier), **FX-2** (rank-4 neutral-axis + unfamiliar `task_type`),
**FX-5** (multi-channel temporal) — plus a `TestRungAtomicity` class
pinning that loss legality is identical across every rung and that the
description axis (PR 01b) physically cannot be varied here.

Sequence of events, as durably recoverable:

1. the file was created and its first targeted run produced **two
   failures**;
2. the first failure's diagnosis IS durably recorded — it is the
   `input_description` finding below, written into the file as an
   in-test NOTE (`test_channel_axis_survives_to_the_prompt`,
   lines 198-206);
3. **the second failure's diagnosis is NOT durably recovered.** No log
   of that run survives. It is NOT reconstructed here from memory.
   Both corrections appear to have been applied before the context was
   lost, because the rescue session's read-only re-run of the file is
   green (below) — but WHY the second assertion failed, and therefore
   whether its correction was source-grounded or merely
   assertion-weakening, is unverified. **The resuming session must
   re-read the four rung bodies against §9.2/§9.4/§9.5 and satisfy
   itself that every assertion still names a defect, before committing
   S1-D.**

Rescue-session evidence (read-only; no file was edited, no test added):

- `pytest tests/unit/agent/ml_model_proposal_agent/test_step01a_contrast_rungs.py -q`
  → **19 passed, 1.09 s**;
- `pytest tests/unit/agent/ml_model_proposal_agent/ -q`
  → **558 passed, 1.91 s** (= the S1-B head's 539 + these 19).

**RESOLUTION OF THE UNRECOVERED SECOND FAILURE (resuming session).**
Its diagnosis was NOT reconstructed from memory. Instead the assertion
it had produced was re-derived from source and found to be weak on its
own terms, so it was REPLACED rather than trusted:

```text
What was there:
  `test_rungs_cannot_vary_the_task_description_axis` asserted
  `inspect.signature(_render_commit_system_prompt).parameters == ["fc"]`
  — a structural proxy for "a PR-01a rung cannot vary the description".

Why that was not good enough:
  it pins the renderer's ARITY, which is a fact about the function's
  shape, not about the prompt. It would pass unchanged if the commit
  surface began carrying description prose by some other route, and it
  would fail as a FALSE alarm the moment PR 01b legitimately threads a
  description argument. Neither behaviour names a defect in this PR.

What replaced it (source-grounded):
  `test_commit_surface_carries_no_task_description_prose` — verified
  from source before writing: the shipped `task_description` is a
  single sentence and appears NOWHERE in `PROPOSAL_COMMIT_PROMPT`, and
  the surface contains none of "SQUID" / "TIDMAD" / "dark-matter".
  So the atomicity claim is true by CONTENT: on this surface the
  description is not an axis at all, which is exactly why the rungs
  can hold it fixed and remain single-axis.
```

This closes the rescue record's open item: no assertion in the file now
rests on an unrecovered diagnosis, and the one that did has been
re-derived from source rather than kept because it was green.

**S1-D COMPLETE (this commit).** The FX-3/FX-4 deferral register, the
full §15/§15.1 battery with hygiene, the surface-coverage gap and the
two corrections are all recorded above. Final targeted evidence:

| Run | Result |
|---|---|
| `pytest …/test_step01a_contrast_rungs.py -q` | **31 passed, 1.15 s** (19 → 31: +8 second-surface, +3 reassertion contrast, atomicity pin replaced) |
| `pytest tests/unit/agent/ml_model_proposal_agent/ -q` | **570 passed, 2.50 s** |
| `pytest tests/unit/agent/ml_model_proposal_agent/ tests/unit/workflows/ -q` | **789 passed, 25.8 s** |
| `ruff check` + `ruff format` on the touched test file | clean |

**SOURCE FINDING — `input_description` is NOT a tier-(i) surface
(bounded implementation correction, NOT a scope deviation).**

```text
Previous assumption:
  every semantic field of ForwardContract that names an input or
  output fact is extractable as a tier-(i) verbatim-renderable token,
  so a contrast rung may assert that a rung's declared
  `input_description` appears in the rendered commit prompt.

Audit / implementation evidence:
  the commit prompt's input parenthetical is the literal
  "(per-timestep ADC class indices)", which is NOT byte-identical to
  the shipped `ForwardContract.input_description`
  ("raw signal, integer class indices 0-255"),
  configs/task_config.yaml:19-35. S1-A had ALREADY recorded this at
  §14.1 ("the prompt's `(per-timestep ADC class indices)`
  parenthetical is NOT the shipped `input_description` ... so it stays
  literal") and therefore never placed it in the tier-(i) placeholder
  set (`{INPUT_SHAPE}` x3, `{OUTPUT_SHAPE}` x2,
  `{OUTPUT_DESCRIPTION}` x1, `{CLASSIFIER_LOSSES}` x1,
  `{REGRESSOR_LOSSES}` x1). The S1-D rung re-derived the same fact
  from the failing assertion.

Corrected understanding:
  `input_description` remains OUTSIDE tier-(i) extraction. Making it
  derive would be a default prompt-BYTE change, which §1 forbids for
  this PR; making the surfaces agree by rewording would be an
  intentional wording change, which §2 also excludes.

Implementation consequence:
  NONE for production — no production file changes as a result. The
  extraction set stays exactly as S1-A landed it. The field is routed
  with the tier-(ii)/(iii) set to the contract-owning step.

Validation consequence:
  a contrast rung may assert only against (a) Step-01-owned
  contract-DERIVED blocks and (b) declarations actually extracted in
  S1-A/S1-B. It must NOT assert that prose which is literal BY DESIGN
  renders as though it had been extracted. The FX-5 rung now asserts
  the NEGATIVE (`"multi-channel sensor stream" not in rendered`) with
  the reason recorded in-test, which is the honest form: it pins the
  current boundary instead of pretending the boundary is elsewhere.
```

**Classification.** This is a **bounded implementation correction, not
a deviation from the design.** The design already requires
source-driven tier classification (§4.1, §6.2) and OD-S1-7 already
forbids inventing formatting/derivation semantics in this step; the
S1-A ledger already carried the finding. The rung was written against
a stale assumption and was corrected TO the design, not away from it.
No operator decision is required.

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

**Verification commands and evidence.** Recorded in the S1-D
dossier and the final-evidence table above; mutation logs at
`/tmp/mut_{M-3,M-4,N-RANK,N-OPAQUE,N-RESIDUE}.log` with their restored
counterparts at `/tmp/res_*.log` (transient — the durable record is the
dossier table).

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

- [x] Every named Stage-A golden is byte-identical after the last
      commit — `git diff` on `tests/unit/agent/**/goldens/` and
      `tests/unit/workflows/goldens/` shows ZERO changed bytes.
      → `git diff --stat 4a11e4e8..HEAD -- '*goldens*'` lists only the
      PB-4 test MODULE (the re-target), no golden content file. The two
      `pb3_proposing_*_system.txt` regenerations are confined to the
      pre-declared S1-A0 fixture commit, exactly as §1 permits.
- [x] The re-targeted PB-4 system assert captures at the legacy `run()`
      LLM boundary, proven by mutation **M-1b** going RED when the
      render call at `ml_model_proposal_agent.py:1385` is deleted.
      → re-run at the FINAL head (call site is now `:1488`): replacing
      `_render_commit_system_prompt(inp.forward_contract)` with the raw
      `PROPOSAL_COMMIT_PROMPT` reds exactly
      `TestPB4LegacyCommit::test_commit_system_rendered_at_the_llm_boundary`
      (1 failed / 571 passed), restored **572 passed**.
- [x] FX-2/FX-5 assert derived-block residue only, and the three §9.5
      whitelisted survivors are present and untouched.
      → `_assert_whitelisted_survivors_present` asserts all three are
      PRESENT under every rung; residue is scoped to
      `_TIDMAD_DERIVED_ONLY_TOKENS` on the commit surface and to
      `render_forward_contract`'s block on the pipeline surface.
- [x] The standalone CLI runs end-to-end with a complete commit prompt
      (§3.1), and the fail-closed path fires only on a missing/invalid
      config.
      → `TestStandaloneCliDisposition` (2 cases) drives the real
      `main()` with a captured agent, asserting no `{PLACEHOLDER}`
      survives the render and that the contract is byte-equal to
      `load_task_config()`'s. **Reachability proven** by mutation
      **M-CLI**: reverting `main()` to its pre-PR-01a shape (contract
      omitted) reds both cases with `ProposalContractRenderError` —
      i.e. without §3.1 the extraction really would have broken this
      surface, and no other test in the repo would have noticed.
- [x] No production default prompt bytes changed anywhere in this PR.
      → All pipeline and legacy `run()` prompt surfaces are byte-pinned
      unchanged (PB-3 ×9, PB-4 ×2, CFG-1/2/3a/3b, WF-3).

      **One bounded, design-approved exception, stated precisely.** The
      standalone CLI's OWN reasoning prompt does change — and only
      because it was previously degenerate. `main()` supplied neither
      `task_description` nor `forward_contract`, so
      `_render_task_background` hit its "both empty" branch
      (`ml_model_proposal_agent.py:417`) and the `{TASK_BACKGROUND}`
      block collapsed to `""`. Under §3.1 the CLI now loads the shipped
      config, so its prompt gains the SAME task-background block the
      workflow path has always produced. This is convergence onto the
      production framing, not a new wording: no golden covers the CLI
      path, no workflow-path byte moves, and the alternative — leaving
      it empty — would have raised `ProposalContractRenderError` at the
      commit render (proven by M-CLI). Recorded here rather than left
      implicit because "no prompt bytes changed" would otherwise be an
      overstatement.

      Note also that `main()` now populates `ProposalInput
      .task_description`. That is NOT the PR-01b JOIN: no stage
      template references a task-description placeholder (verified —
      `grep task_description agent/prompt_templates/proposal/*.md`
      returns nothing), so the pipeline seam at `:1708` stays inert.
      PR 01b still owns making it render.

## 7. Closeout audit (final head)

| Check | Evidence |
|---|---|
| No PR-01b scope in the diff | no `{TASK_DESCRIPTION}` placeholder, no JOIN, no `~100M parameters` / `10 GB VRAM` budget cleanup in the production diff |
| No shape parsing / rank branching | diff of `nodes/` greps clean for `.split(`, `.count(`, `ndim`, `rank`, `task_type ==`, `if …shape` |
| Loss authority still single | the diff only ADDS consumers of `CLASSIFICATION_LOSSES`/`REGRESSION_LOSSES`; no second definition |
| Schemas / protocols / scorer / dataset / model execution untouched | branch touches exactly 4 non-test files: `ml_model_proposal_agent.py`, `proposing_stage.md`, and the two design docs. The one file under `tests/unit/agent/protocols/` is a test FIXTURE given a contract by the fail-closed fallout, not a protocol change |
| Step-00 hard gates | PB-3/PB-4 + CFG-1/2/3a/3b → **11 passed** |

**Final validation at head `fe4ec2e5`, clean tree.**

| Gate | Result |
|---|---|
| `pytest tests/unit/ -m "not real_run"` | **8407 passed, 3 skipped, 538.05 s**; pytest's OWN exit code `0`, verdict read from `/tmp/full_suite_01a.log` (zero `FAILED`/`ERROR` lines), not from a wrapper |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 802 files already formatted |
| `pyright` | **CANNOT RUN LOCALLY** — Node v10.19.0; pyright-python refuses to bootstrap. CI is the only pyright, per the repo's environment-assumptions rule. Not claimed as locally validated |


## 8. Merge-gate evidence — shipped-TIDMAD parity, base vs final

Requested by the operator at the merge gate (2026-08-12) and executed
as one-off merge evidence, NOT as a new permanent test.

**Why it was needed.** S1-A0 deliberately moved the PB-3 TEST-OWNED
fixture from a shipped-like 256 classes to 192. That is a strong
anti-hardcode fixture — but it means "the nine PB-3 goldens are
byte-identical" proves extraction parity *under the 192 profile*. It is
no longer, by itself, a direct proof that the production pipeline's
prompt under the REAL shipped 256-class profile is byte-identical to
the merge base. The legacy commit surface already had a shipped-profile
probe (PB-4); the pipeline did not.

**Method.** Two clean `git archive` extractions — merge base
`6f3866b6` and final executable head `fe4ec2e5` — neither tree
modified. In each, the same probe ran the SAME production pipeline path
PB-3 exercises (`MLModelProposalAgent.run` with the canned
`_CannedProposerBridge`, fully pinned environment) with exactly ONE
fixture override: the forward contract and task description forced to
the **shipped** values from `load_task_config()`. Prompts were hashed
at the LLM boundary.

Pre-checks: `configs/task_config.yaml` is byte-identical across the two
trees (`a627350d…`), and the shared harness (`pin_environment`,
`fixture_interpretation`, `fixture_proposal_input` apart from the
contract fields, `_CannedProposerBridge`, `run_pipeline`) is
byte-identical across them — so the ONLY difference between the two
runs is the production code under test.

| Surface (shipped 256-class profile) | base `6f3866b6` | final `fe4ec2e5` | exact_equal |
|---|---|---|---|
| explore / comparison — system | `a9120e37b782` | `a9120e37b782` | **true** |
| explore / comparison — user | `0f3ac3832aaf` | `0f3ac3832aaf` | **true** |
| explore / causal_reasoning — system | `0e4acd29a31e` | `0e4acd29a31e` | **true** |
| explore / causal_reasoning — user | `a1c72673941d` | `a1c72673941d` | **true** |
| explore / proposing — system | `e5dc7eba7290` | `e5dc7eba7290` | **true** |
| explore / proposing — user | `80a4b75a95b0` | `80a4b75a95b0` | **true** |
| exploit / comparison — system | `fc69830b2d5c` | `fc69830b2d5c` | **true** |
| exploit / comparison — user | `0f3ac3832aaf` | `0f3ac3832aaf` | **true** |
| exploit / causal_reasoning — system | `56ecc3173bf3` | `56ecc3173bf3` | **true** |
| exploit / causal_reasoning — user | `a1c72673941d` | `a1c72673941d` | **true** |
| exploit / proposing — system | `0ec3bdc5a4e8` | `0ec3bdc5a4e8` | **true** |
| exploit / proposing — user | `80a4b75a95b0` | `80a4b75a95b0` | **true** |
| shipped `forward_contract` declaration | `7e3690006d0b` | `7e3690006d0b` | **true** |
| shipped `task_description` | `1bbb764b545a` | `1bbb764b545a` | **true** |

**Legacy commit surface, same comparison** (base evaluates the raw
constant, final evaluates `_render_commit_system_prompt(shipped)`):
both `b93997951b04…`, length 5221 — **exact_equal = true**. So the
extraction is byte-transparent on that surface too, under the shipped
profile rather than a fixture.

**NEGATIVE CONTROL — the comparison can actually fail.** An all-equal
table is worthless if the probe is incapable of detecting a difference.
In the throwaway `final` archive only, `_render_loss_legality` was
changed to `sorted(losses, reverse=True)`. The probe then reported
`explore/proposing` and `exploit/proposing` system prompts CHANGED —
and only those two, exactly the surfaces S1-B touched. The archive was
restored and re-hashed to the original final values. This proves two
things at once: the probe is sensitive, and the shipped-profile
pipeline render genuinely flows through the extracted renderer, so the
equality above is substantive rather than vacuous.

**Verdict.** Shipped-TIDMAD byte parity between merge base and final
executable head is **directly proven** for every standard production
pipeline proposer surface and for the legacy commit surface. The
standalone CLI is excluded by construction and handled as the approved
§1 item 3 exception.
