# PR-12a — Composed-path closure & extensibility debt re-audit

## 0. Status, anchors, opening checkpoint

**CURRENT STATUS: PR-12a — TERMINAL REVIEW FIXES APPLIED / MERGE PENDING
FINAL CI.** Implementation COMPLETE (C0–C9); **G-12a-1 PASS** (§8.18) and
**G-12a-2 PASS** (§8.22); operator terminal review 2026-08-23 returned
**APPROVE WITH SMALL CLOSEOUT FIXES** with all four substantive items ratified
and no Gate rerun required (§8.24). Merge authority granted conditional on the
post-review exact-head CI (§8.25).

Historical freeze record, preserved:

> **REVISION 2 — FROZEN. OPERATOR APPROVED 2026-08-22
> ("APPROVE WITH TARGETED AMENDMENTS"; all five amendments + the #234
> reachability addition applied in this revision; freeze authorized on a
> clean internal consistency sweep, which found no material finding).
> READY FOR IMPLEMENTATION — in a FRESH implementation session, never this
> design session.**

Revision history: rev 1 (draft, 2026-08-22) → operator review 2026-08-22
(Architecture PASS · Scope PASS · Debt ownership PASS · Validation
topology PASS · PR size accepted, no 12a1/12a2 split · five amendments
required) → **rev 2 = the amendments (§0.1) + freeze**.

### 0.1 Operator review dispositions (rev 1 → rev 2)

| # | amendment | applied at |
|---|---|---|
| 1 | C1/C2 dependency cleaned: NO semantic commit temporarily reads an authority the next commit replaces. C1 = pre-flight scope fix + health single-materialization (projection-independent); C2 = the typed projection AND every consumer that reads it (W4 discriminator + the per-model lock's fingerprint/health-binding kwargs) in one coherent state | C0 guard split, C1, C2 |
| 2 | D16 strengthened to the operator's ruling: **`MetricSpec.id` is an OPAQUE identifier** — lexical metric-name semantics are removed wherever the owning typed contract enforces the real boundary; expected end state: `_is_loss_shaped` exits EvaluationMetric identity validation entirely; any residual protection guards the TYPED seam, never the `"loss"` token | D-12a-4, C5 |
| 3 | D-12a-5 strengthened: removing TIDMAD science is NOT sufficient — every removed block is classified (optional TIDMAD-only advice → may disappear; required task semantics → REPLACED from a task-owned authority); Gate 1 asserts explicit pre-chosen task facts, never a subjective "understands the task" | D-12a-5, C7, C9 |
| 4 | This design approval IS the explicit ratification of ALL additive contract changes: **D-12a-1** (`HyperparamTuningInput` composition projection), **D-12a-6** (`ProposalTaskBlocks` + `proposal_blocks:` manifest family, fingerprint-participating), **D-12a-4** (metric-id lexical-invariant amendment), **D-12a-5** (LLM-facing composed-prompt disposition). No schema/protocol expansion in this PR is "discovered during implementation" (the R-11-14 lesson, designed-in) | §0.1, §4, §8 |
| 5 | C9 terminal SHA discipline corrected to the Step-11 shape: Gates execute at the exact final EXECUTABLE head; after PASS only evidence/ledger docs change; the executable-head→PR-head delta is VERIFIED docs-only; ONE authoritative CI at the exact final PR head; no commit after it | C9 |
| + | #234 end-to-end reachability: an explicitly REQUIRED malformed external model plugin must fail the run closed — a loader-level named skip must never let the run silently fall back to another model and succeed | C4 |

**IN-FLIGHT RATIFICATION — the one deviation from the frozen ratification
above.** Item 4 enumerates the additive contracts and forbids discovering more
"during implementation". C7-4 found one it could not close without a new
schema family, and STOPPED rather than take it (§8.14). The operator ruled on
2026-08-22:

| # | ratified in flight | authority | applied at |
|---|---|---|---|
| 6 | **D-12a-9 — `ImplementorTaskBlocks` + `ImplementorInput.implementor_blocks` + optional manifest `implementor_blocks:` section, fingerprint-participating.** A BOUNDED CONTRACT CORRECTION, deliberately narrow: it resolves the implementor role clauses and the continuous-output phrase, and does NOT redesign the implementor prompt. Frozen semantics: framework owns schema/placement, task owns prose; absent composed blocks MUST NOT fall back to TIDMAD science; legacy prose arrives through the bounded adapter with rendered bytes identical; unknown/malformed declaration fails closed; no task-name dispatch, no central catalog, **no ambient composition discriminator**; no invented framework prose for missing scientific meaning | operator ruling 2026-08-22 ("OPTION A IS AUTHORIZED") | §8.14 → §8.15, C7-4 |

The process point is worth keeping: the R-11-14 lesson held. The expansion was
raised as a boundary, priced, and ratified — not folded into an implementation
commit and explained afterwards.

Operator PASS confirmations recorded: the A-12a-2 health fix (chain-level
effective config → tuner, one-authority) · the #234 vocabulary-vs-
plugin-legal distinction · the A-12a-3 consolidation (no new lifecycle
abstraction) · validation topology sufficient, no additional Gate ·
**G-12a-2 stays 2×1 — never downgraded to 1×1** · no sixth Step-12 PR · no
structural prerequisite PR, with C8's structural comparison a HARD
checkpoint (a new branch family in any baselined function ⇒ extract first;
total-LOC arguments do not excuse it).

| field | value |
|---|---|
| parent authority | `../step_12_external_extensibility_graduation.md` — REVISION 3, operator approved 2026-08-22 (LIVE parent ledger). This child owns parent §12-PR-12a; scope items (i)–(x); Gates G-12a-1 + G-12a-2 |
| source anchor | master `e4cd5c18` (= `origin/master`, verified by fetch at drafting), branch `step12-external-extensibility` |
| §11.1 opening checkpoint | no prior Step-12 child has merged, so the checkpoint degenerates to: (1) master re-anchored and UNMOVED since the parent's rev-3 closeout (`e4cd5c18`); (2) the parent's §10 structural baseline is current for every module this child touches; (3) the parent's §4 re-audit table is the assumption set this design re-verified — three rows CHANGED by this child's own deeper audit (§2.1); (4) fresh working-rules context = this document |
| PR-doc standard | the operator's 8-section per-commit checklist standard (2026-08-22): Goal · Scope · Implementation plan · Validation plan · Acceptance criteria · Failure/edge cases · Verification commands/evidence · Commit boundary; `[ ]` flips to `[x]` only with recorded evidence; pre-commit stop shows the exact diff summary, staged files, tests, and deviations |
| Gate disposition (parent-frozen) | **Gate 1 REQUIRED** (prompt deltas, 09b/P3 probe shape). **Gate 2 REQUIRED — default 2 iterations × 1 round composed-TIDMAD** on the per-model lock / fingerprint / resume chain; §6.3 carries this child's semantic-latency analysis; any downgrade must be argued there, never asserted |
| open operator questions | **0** — the approval review RATIFIED the four additive/recorded-contract changes (§0.1 item 4) and RULED the D16 and prompt-disposition semantics (§0.1 items 2–3); nothing remains flagged |

Terminal discipline (parent §12 preamble) applies: doc sync before the final
push; ONE authoritative exact-final-head CI; no trailing commits.

---

## 1. Goal / capability (parent G1 + G6-partial)

A composed run resolves **zero** implicit TIDMAD semantics — neither as
values (pre-flight scope topology, per-model lock identity, health-family
materialization) nor as prompt science (planner/proposer/implementor
prose) — and the ratified Steps-01–07 B-class set is dispositioned against
current source with the census holes closed. Legacy (un-composed) behaviour
stays byte-identical everywhere, read through R-11-13's parity wording.

Explicitly NOT this PR (parent boundaries): scope construction/transport
(12b) · out-of-tree child loading + registration overlay (12c) · pack
completion / contrast closure (12d) · fourth task (12e) · any frozen record
key rename (D1) · removal of the regime-A fallbacks for un-composed runs.

---

## 2. Source audit (fresh, at `e4cd5c18`; every claim re-verified by the author)

### 2.1 Findings that CHANGE the parent's assumption set

| id | finding | consequence |
|---|---|---|
| **A-12a-1** | Parent §4.1-R2 ("tuner deliverable-spec acquisition unconditional") is **already CLOSED by Step-11 C6 for its naming half**: `bind_run_task_composition` enters `bind_deliverable_naming(composition.deliverable_naming)` when declared (`workflows/task_composition.py:1286-1292`), and `derive_tidmad_deliverable_spec` resolves the BOUND naming internally (`execute_tools/deliverable_spec.py:313-339,382`), exactly as the scoring child does (`denoising_score_single.py:205-225`). The tuner's `:537` call therefore already yields the declared naming on a composed run. What remains TIDMAD-shaped is the STORAGE half (profile-derived dtype/layout) — owned by 12b's Q-12-4 work, not here | R2 becomes **PIN + docs**, not implementation: C3 shrinks to a differential pin plus correction of the stale `:524-537` comment ("the spec … crosses no process boundary" predates C5/C6) |
| **A-12a-2** | `WorkflowRunBindings.health_checks_config` carries the operator's RAW source value (`run_bindings.py:85`; construction passes the `run_workflow` parameter through, `model_exploration.py` bindings site), and the tuner materializes its per-model effective config FROM that raw value with `task_health_binding` absent (`ml_hyperparameter_tune_agent.py:600-635`), then loads gates from the result (`:646`). For a composed run whose source is `None`, the per-model materialization resolves **`LEGACY_OMITTED` → TIDMAD's task-health family** — the F-P56-3 health half is REAL, and the three-task closure drives could not see it because they ran `health_gate_enabled=False` (`tests/helpers/step00_pseudo_iteration.py:165`) | C1 must fix BOTH halves of F-P56-3: the per-model lock's identity kwargs AND the health-family source. The chain-level effective config (already composed-correct via W7, `run_one_iteration.py:1470-1528` + `run_invariants.py` "already-effective returned untouched") is the single-materialization vehicle |
| **A-12a-3** | `_add_plugin_to_registries` (`model_exploration.py:924-967`) and the PUBLIC `plugin_loader.register_model_in_memory` (`ml_models/plugin_loader.py:230-278`) write the SAME three registries from the same `_load_plugin`; the public one additionally warns on same-type/different-class re-registration. The (vii) relocation is therefore a **consolidation onto the existing public authority**, not a new module | C6 retires the private duplicate; `core/resume.py:74` imports the public function; the import-cycle workarounds (`model_exploration.py:2883-2887`) dissolve |

### 2.2 Facts grounding the remaining scope (unchanged from the parent, re-verified)

* **F-12-1**: `run_one_iteration.py:1499` `resolved_scope = run_scope.resolve(TIDMAD)` inside the W7-hardened `compute_expected_invariants(args, run_composition)` — the composition object is ALREADY a parameter (`:1520-1527` threads its health binding + fingerprint), and the pre-flight runs BEFORE `bind_run_task_composition` (`:2061`), so the fix reads `run_composition.dataset_profile.dataset` explicitly, mirroring the workflow's own composed-aware site (`model_exploration.py:1803-1804`).
* **Threading (iv)**: the W4 guard keys on the ambient `active_task_data_path()` (`ml_hyperparameter_tune_agent.py:839`); the record/output stamps already read the run-scoped `active_composition_fingerprint()` (exactly two call sites, `records.py:490,838`, AST-pinned by Step 11). The roadmap-carried debt is the tuner's ambient DISCRIMINATOR read, not the subsystem ContextVar seams.
* **#234**: silent coercion `plugin_loader.py:80-87`; loader accepts `{classifier, regressor, hybrid}`, validator `_LEGAL_OUTPUT_TYPES` accepts 2 (`ml_code_validator_agent.py:368`). `"hybrid"` is LOAD-BEARING for builtins (`models_sandbox.py:747` `fcnet`, consumed `inference_single.py:296-319`) and documented as "a legacy builtin adapter value (§8c), not a tensor" (`models_format_sandbox.py:497`) — so the plugin-legal set and the full vocabulary are genuinely different sets.
* **D16**: `_is_loss_shaped` / `_reject_loss_shaped` (`evaluation_metric.py:118-140`), applied to `MetricSpec.id` (`:390`). Roadmap §22.18-D16 assigns removal/narrowing to Step 12; CLAUDE.md's Step-06 invariant bullet ("metric types refuse loss-shaped ids") must be amended in the same commit that narrows it.
* **Prompt surfaces** (inventory per the design-session audit, spot re-verified): planner `agent/prompts.py:66` hardcodes `` `denoising_score` `` beside `{METRIC_IDENTITY_LINE}`; `:69-73` five static builtin-model descriptions (no `MODEL_DESCRIPTIONS` linkage — that KB has zero consumers in the planner path); `:239-266` per-file-table protocol prose; reflector `:280-319`. Proposer: `ml_model_proposal_agent.py:336` (denoising-architect role), `:391,393,430` (`[B,256,T]`/256-bin/denoised-waveform contract semantics), `:362-379` (score-table reading protocol), templates `proposal/proposing_stage.md:41,70-74`, `comparison_stage.md:118,122-123`; the node has NO task-blocks mechanism (zero `task_blocks` hits outside `agent/schemas/interpretation.py:818`). Implementor: `ml_model_implementor.py:426,635` (role lines), `:316-321` `_LEGACY_OUTPUT_CONTRACT_COMMENTS`. Prompt-byte pins to disposition: `tests/unit/agent/test_prompt_banned_vocabulary.py`, `test_planner_prompt_task_config.py`, `test_llm_bridge.py`, `llm_bridge/test_step07b_c4_task_rendering.py`, `tests/unit/workflows/test_step10_p1_c2_consumption.py`.
* **Lit review (Q-12-3, RATIFIED)**: `should_run_literature_review` returns the resolved flag (`model_exploration.py:497-526`); resolution CLI > YAML `enabled` > False (`run_one_iteration.py:2021-2032`); chain default OFF (`_chain_common.sh:192`); shipped config `enabled: false` (`configs/lit_review_config.yaml:34`). Guard point: `run_workflow` startup, where composition presence and the resolved flag are both in hand.
* **Censuses to widen (F-12-6)**: the P1 singleton-import guard's surface (`test_step10_p1_c4_extension_proof.py:235-266`) excludes `sdsc_submission_scripts/run_one_iteration.py` and `core/resume.py`.

---

## 3. Scope re-baseline (the parent's (i)–(x), post-audit)

| parent item | disposition in this design | owner commit |
|---|---|---|
| (i) F-12-1 launcher scope topology | IMPLEMENT | C1 |
| (ii) tuner deliverable acquisition | **RE-CLASSIFIED: CLOSED BY STEP 11 (naming half) — pin + stale-comment fix** (A-12a-1); storage half → 12b | C3 |
| (iii) F-P56-3 per-model lock | IMPLEMENT, both halves (A-12a-2) — health-source half projection-independent; lock-honesty half rides the projection | C1 (health) + C2 (lock kwargs) |
| (iv) ambient-read threading | IMPLEMENT (typed projection on the tuner input; W4 re-keyed) | C2 |
| (v) issue #234 | IMPLEMENT (fail-closed + one vocabulary authority with a declared plugin-legal subset) | C4 |
| (vi) D16 | IMPLEMENT (declaration-path narrowing + recorded invariant amendment) | C5 |
| (vii) `resume.py:74` layering | IMPLEMENT as consolidation (A-12a-3) | C6 |
| (viii) prompt-science family + F-12-5 + lit-review guard | IMPLEMENT | C7 |
| (ix) census widening F-12-6 | IMPLEMENT | C8 |
| (x) B-class re-audit table recorded with evidence | IMPLEMENT (ledger artifact) | C8 |

---

## 4. Design decisions (all within parent contracts; D-12a-1/-4/-5/-6 RATIFIED at the approval review, §0.1 item 4)

* **D-12a-1 — threading shape (iv).** `HyperparamTuningInput` gains an
  additive, default-`None` typed projection field (working name
  `task_composition_ref`) carrying: presence, `semantic_fingerprint`,
  `task_data_path_id`. The workflow populates it from
  `bindings.task_composition`; the tuner's W4 guard and its per-model
  `build_run_invariants` read IT. The subsystem ContextVar seams
  (metric/profile/task-config/naming) are run-scoped authorities by design
  and are NOT converted. The ambient `active_task_data_path()` call in the
  tuner is retired from the W4 guard; `verify_composition_is_bound` (the
  wiring guard) is unchanged. Exact field set is finalized by C2's audit
  step against every tuner read. **Additive contract change RATIFIED at
  design approval (§0.1 item 4).**
* **D-12a-2 — single health materialization (iii).** The workflow passes the
  tuner the CHAIN-LEVEL effective config path (not the raw source) so the
  per-model materialization is the 08b "already-effective returned
  untouched" no-op, AND the tuner's `build_run_invariants` gains the
  `task_health_binding` + `task_composition_fingerprint` kwargs from
  D-12a-1's projection — the per-model lock becomes honest and the
  composed family can never re-resolve `LEGACY_OMITTED`. Legacy runs:
  byte-identical lock and effective config (differential fixture).
* **D-12a-3 — #234 vocabulary authority (v).** ONE module-level authority
  (in `ml_models/plugin_loader.py`) declares `OUTPUT_TYPE_VOCABULARY`
  (3-member, includes the legacy builtin adapter `hybrid`) and
  `PLUGIN_LEGAL_OUTPUT_TYPES` (audited subset; expected 2-member per
  `models_format_sandbox.py:497` — C4's audit step confirms from the §8c
  consumers before freezing the sets). The loader REFUSES (skip with a
  named, printed reason and `None` return — its established malformed-plugin
  convention) any plugin declaring outside the plugin-legal set; the
  validator imports the SAME subset. No silent default remains; the GitHub
  issue closes at merge with the falsifier test cited.
* **D-12a-4 — D16 removal (vi) — OPERATOR RULED at approval (2026-08-22),
  superseding rev 1's declaration-path carve-out.** **`MetricSpec.id` is an
  OPAQUE identifier**: the framework never infers "this is a training
  objective, not an evaluation metric" from a name token. The
  TrainingObjective / EvaluationMetric distinction is owned by the typed
  contracts and construction authorities, not by lexical heuristics —
  `"accuracy"`, `"mse"`, `"log_loss"`, `"negative_log_loss"` and
  `"banana_metric"` are all equally legal identities whose meaning and
  direction come from the declaration. C5's audit enumerates every
  `_reject_loss_shaped` consumer and removes lexical rejection wherever the
  owning typed contract can enforce the actual boundary; **the expected end
  state is that `_is_loss_shaped` exits EvaluationMetric identity
  validation entirely.** If the audit finds a real internal seam where a
  TrainingObjective could be mis-fed into an EvaluationMetric slot, that
  TYPED seam gets the guard — never the `"loss"` token. A name-based
  rejection may not be retained merely because a construction path is
  "internal". CLAUDE.md's Step-06 invariant bullet is amended in the same
  commit (the boundary is typed-contract-owned; roadmap §22.18-D16 is the
  standing authority). **RATIFIED at design approval.**
* **D-12a-5 — planner/reflector prompt strategy (viii) — STRENGTHENED and
  RATIFIED at approval (2026-08-22).** The governing invariant, in the
  operator's wording:

  > *A composed prompt must contain no implicit TIDMAD science. Any
  > removed TIDMAD block that carried information necessary for the
  > node's semantic task must be REPLACED from a task-owned declaration;
  > only genuinely optional TIDMAD-specific advice may disappear.*

  "No TIDMAD science" ≠ "task science is present" — a blanket
  named-absence treatment is NOT acceptable. C7's render-path audit
  therefore classifies EVERY removed hardcoded block into exactly one of:
  (1) **optional TIDMAD-only guidance** → the composed path renders the
  named absence; (2) **required task semantic guidance for this node** →
  the composed path renders a replacement drawn from an existing
  task-owned authority (task description, ModelIOContract /
  forward-contract wording, metric identity + direction, proposal
  blocks) — never invented framework prose. The W4 gating mechanism and
  legacy byte-identity stand as designed. **F-12-5's literal**:
  `denoising_score` in the goal line names the FROZEN record field every
  run's history JSON carries (D1); C7's audit presents the exact
  byte-level rewording options with the pinned tests' disposition, and the
  Gate-1 probes cover whichever lands.
* **D-12a-6 — proposer/implementor task blocks (viii).** Mirror 09b: a new
  `ProposalTaskBlocks` schema (framework owns keys + placement; absent ⇒
  zero bytes), TIDMAD prose moved VERBATIM to
  `configs/task_proposal/tidmad.yaml` behind one bounded Regime-A adapter
  (single default-path constant, AST-guarded — the
  `interpretation/task_blocks.py` shape), an optional manifest section
  `proposal_blocks:` composed exactly like `interpretation_blocks:`
  (fingerprint-participating). The implementor's two role literals and
  `_LEGACY_OUTPUT_CONTRACT_COMMENTS` render from the run's
  ModelIOContract/forward-contract wording instead of hardcoded
  denoising text — audit-gated in C7, byte-pinned for legacy. **Additive
  contract change (schema + manifest family + fingerprint participation)
  RATIFIED at design approval (§0.1 item 4).**
* **D-12a-7 — lit-review guard (Q-12-3, ratified).** At `run_workflow`
  startup, composition present AND resolved `lit_review_enabled=True` ⇒
  raise a named error (before any LLM/GPU spend), stating the ratified
  disposition and the named debt. Un-composed runs unaffected.
* **D-12a-8 — consolidation (vii).** `_add_plugin_to_registries` is retired;
  both callers use `plugin_loader.register_model_in_memory` after a
  behavioural parity check (same three registries, same failure returns;
  the extra re-registration warning is accepted as strictly-more-visible).
  `core/resume.py:74` imports the public symbol; the local-import cycle
  workarounds at `model_exploration.py:2883-2887` are dissolved.

---

## 5. Commit plan (all checkboxes `[ ]`; evidence recorded only after execution)

### C0 — Baselines, parity fixtures, inverted guards

1. **Goal.** Every behaviour this PR must preserve is pinned BEFORE any
   change, and every defect it fixes is executably visible, so each later
   commit flips a named guard.
2. **Scope.** Tests + fixtures only. No production change.
3. **Implementation plan**
   - [x] Legacy byte-parity fixtures: planner/reflector/proposer/implementor
         prompt bytes (sha256 over rendered payloads for a pinned pseudo
         run), per-model lock JSON, chain lock JSON, effective-config body
         sha, un-composed argv (via the Step-11 C0 censuses, read through
         R-11-13).
         **Landed** in `tests/unit/guardrails/test_step12_pr12a_c0_legacy_parity.py`
         (23 tests) on `tests/helpers/step12_pr12a_prompt_capture.py`:
         rendered legacy tuner manifest sha
         `6e8de64b660da36c4801bd0e9d590e206dcf4f1395701305d5115bfe753039d6`
         (5 calls — planner ×3, reflector ×2; per-call byte table recorded
         beside it so a mismatch localizes); 16 prompt-source shas covering
         `PLANNER_PROMPT` / `REFLECTOR_PROMPT`, both proposer prompts, the
         three implementor prompts and all nine `prompt_templates/proposal/*.md`;
         the un-composed lock's exact 12-key set with the composition key
         ABSENT; the legacy `legacy_default` effective-config body reproduced
         byte-identically from two workspaces. **Argv is CITED, not
         duplicated** — PR-12a emits none, so `TestLegacyArgvFlagBaseline`
         (`test_step11_c0_baselines.py`) stays its owner and an executable
         citation test fails if that owner is renamed away.
   - [x] Composed-path defect baselines (inverted guards): (a) pre-flight
         `resolved_data_scope` for a composed manifest with a non-TIDMAD
         profile currently equals TIDMAD's range [flips in C1];
         (b-health) a composed+gates-on tuner materialization resolves
         `legacy_default` [flips in C1]; (b-fingerprint) the per-model lock
         records `task_composition_fingerprint=None` [flips in C2];
         (c) unknown `PLUGIN_OUTPUT_TYPE` currently loads as `"classifier"`
         [flips in C4]; (d) a `log_loss` metric declaration is currently
         refused by the lexical check [flips in C5]; (e) composed pseudo
         prompts currently contain the five-model TIDMAD descriptions
         [flips in C7].
         **Landed** in `tests/unit/guardrails/test_step12_pr12a_c0_defect_baselines.py`
         (33 tests). All six reproduce; (b-health) reproduces in a STRONGER
         form than the design anticipated — see §8 finding F-12a-C0-1.
   - [x] Record the §10-parent structural numbers for the files this PR
         touches (pre values for the C8 comparison). **16 functions across 9
         files**, measured with the Step-11 C0 counting rules; table + budget
         in the same module. Convention delta vs the parent §10 table
         recorded as §8 finding F-12a-C0-2.
4. **Validation plan.** Unit only; each inverted guard names the commit that
   flips it.
5. **Acceptance criteria.** Baselines reproduce the §2 audit numbers
   exactly; every guard is RED-by-construction against the defect and
   documents its flip owner. — [x] **DISCHARGED.** 56 tests green; the
   guard/flip-owner table is the module docstring; three mutation proofs
   below establish the guards are load-bearing rather than decorative.
6. **Failure/edge cases.** A parity fixture that normalizes too much would
   pass vacuously — each fixture states what it deliberately does NOT
   normalize (R-11-13's repo-rooted-token rule is the only normalization).
   — [x] **DISCHARGED, with one addition the design did not anticipate**
   (§8 finding F-12a-C0-3): the capture normalizes wall-clock timestamps
   and NOTHING else (established by diffing two fresh processes), and the
   machine-local capability index is **PINNED, not scrubbed** — a sha over a
   prompt embedding gitignored `agent_generated/` state would have passed
   locally and failed on a fresh CI clone.
7. **Verification commands and evidence.**

   ```text
   pytest tests/unit/guardrails/test_step12_pr12a_c0_defect_baselines.py \
          tests/unit/guardrails/test_step12_pr12a_c0_legacy_parity.py -q
       -> 56 passed in 3.60s

   pytest <the 12 step00-helper consumers> -q
       -> 169 passed in 13.81s
          (regression evidence for the two ADDITIVE helper parameters)

   ruff check / ruff format --check  <4 changed files>   -> clean
   pyright                                               -> NOT RUN LOCALLY:
       the vendored pyright cannot execute in this environment (its
       bundled Node vendor bundle fails to load). CI owns this check;
       claiming a local run would be false.
   ```

   **Mutation proofs** (each planted with `count == 1`, `__pycache__`
   cleared, reverted via `git checkout --`, baseline re-confirmed green):

   | # | mutation | expected | observed |
   |---|---|---|---|
   | 1 | one character inside `PLANNER_PROMPT` (`RULE:` → `RULES:`) | rendered + source parity RED | **3 RED** — rendered manifest, the anti-vacuity probe, and the `PLANNER_PROMPT` source sha; 20 passed |
   | 2 | apply the C1 fix shape to `run_one_iteration.py` (resolve against the composed dataset) | guard (a) RED — proving it is genuinely INVERTED and will flip | **2 RED** — the value assertion and the reachability assertion; 31 passed |
   | 3 | four `if` statements into `build_run_invariants` | structural budget RED naming the function | **1 RED** — *"gained 8 branch nodes (3 -> 11) — that is a new branch family"*; 16 passed |

8. **Commit boundary.** Tests only; per R-11-10 each guard later becomes the
   permanent owner or is deleted. — [x] **HELD**: zero production files
   changed (`git diff --name-only` at the commit = 4 paths, all under
   `tests/`).

### C1 — Projection-independent invariant closure: F-12-1 + the health source (D-12a-2)

**Ordering rule from the approval review (§0.1 item 1): no semantic commit
may temporarily read an authority the next commit replaces.** C1 therefore
contains ONLY the fixes that are independent of D-12a-1's projection; every
projection CONSUMER lands with the projection itself in C2. There is no
interim state in which the per-model lock kwargs read the ContextVars.

1. **Goal.** A composed run's pre-flight scope topology and its per-model
   HEALTH-FAMILY materialization are composed-correct — without touching
   the tuner's input schema.
2. **Scope.** `run_one_iteration.py::compute_expected_invariants` (`:1499`);
   the workflow→tuner health-config hand-off (the chain-level EFFECTIVE
   config path replaces the raw source value). NOT here: the per-model
   lock's fingerprint/health-binding kwargs (C2's, with the projection).
3. **Implementation plan**
   - [x] `resolved_scope` resolves against
         `run_composition.dataset_profile.dataset` when composed; TIDMAD
         constant only on the legacy branch (import demoted accordingly).
         **Landed** `run_one_iteration.py::compute_expected_invariants`. The
         legacy branch reads `resolve_dataset_profile().dataset` — un-composed
         that returns `TIDMAD_PROFILE`, whose `.dataset` IS the singleton the
         constant named (same object), so the value cannot move — and the
         `TIDMAD` import is **REMOVED** from the launcher rather than demoted
         to a dormant name. This mirrors `run_workflow`'s own composed-aware
         `_run_dataset` site and pre-empts F-12-6's census on this file.
   - [x] Extend the W7 agreement census to cover the VALUE (pre-flight
         scope == workflow scope) for a composed non-TIDMAD profile.
         **Landed** as `TestW7ValueAgreement` (Pets and DAVIS), driving the
         REAL `run_workflow` and comparing the pre-flight's value against the
         workspace lock the workflow actually wrote. See §8.3 finding
         F-12a-C1-1 for why the existing keyword-set census could never have
         seen this.
   - [x] D-12a-2 source half: the workflow hands the tuner the chain-level
         effective config path, so the per-model materialization is the
         08b "already-effective returned untouched" no-op.
         **Landed** at `model_exploration.py` — the pre-flight's
         `build_run_invariants` return value is captured
         (`_run_effective_health_config`, previously discarded) and forwarded
         as `bindings.health_checks_config`, whose ONLY consumer is the tuner
         hand-off. **Keyed on composition PRESENCE**, not applied
         unconditionally — see F-12a-C1-2.
   - [x] Flip C0 guard (a) and guard (b)'s LEGACY_OMITTED half into
         permanent contract tests. **Both RETIRED, not twinned** (R-11-10):
         the two guard classes are deleted from the C0 module, which now
         carries a pointer to their permanent owners in
         `tests/unit/workflows/test_step12_pr12a_c1_composed_invariants.py`.
         The tuner-level half — that the tuner's own `build_run_invariants`
         call passes NEITHER identity kwarg — was **re-anchored to C2**
         (F-12a-C1-3) and folded into the renamed
         `TestInvertedGuardBTunerOmitsCompositionIdentity`.
4. **Validation plan.** Unit: composed fixture (non-TIDMAD num_files) →
   pre-flight scope correct; ~~the per-model effective body sha equals the
   chain's~~ **(re-anchored to C2 — F-12a-C1-3)**; gates-on composed
   materialization can NEVER resolve `legacy_default` **(roster half here;
   marker half C2)**. Legacy: effective-config + lock byte-parity vs C0.
5. **Acceptance criteria.** Guard (a) and guard (b)-health closed with
   named tests; zero legacy byte movement; W7 value-census green; zero new
   reads of any run-scoped composition authority introduced by this
   commit. — [x] **DISCHARGED.** 13 C1 tests + the 56 C0 tests green;
   legacy pre-flight scope, legacy tuner hand-off value (`None`) and the C0
   legacy-parity baselines all unmoved; the only composition read added is
   `run_composition.dataset_profile` on a parameter the function ALREADY
   received — no ContextVar, no projection, no new authority.
6. **Failure/edge cases.** A workspace with an existing pre-fix per-model
   lock must not be refused by the fix (locks are per-model-workspace and
   fresh per run — verify, don't assume); a composed run with
   `EXPLICIT_NONE` health must record that state, not a path.
   — [x] **VERIFIED, both.** Per-model locks are written under the tuner's
   own workspace and the lock's `resolved_data_scope` was already
   composition-correct there (the tuner resolves from the bound profile), so
   C1 moves no per-model lock value and no existing workspace is refused.
   `EXPLICIT_NONE`: `build_run_invariants` returns `(_, None)` whenever gates
   are disabled and `load_composed_health_config` short-circuits
   `EXPLICIT_NONE` to an empty roster BEFORE the already-gated branch — so a
   named absence can never acquire another task's family through the
   hand-off, which is exactly the state the hand-off had to preserve.
7. **Verification commands and evidence.**

   ```text
   pytest tests/unit/workflows/test_step12_pr12a_c1_composed_invariants.py -q
       -> 13 passed in 3.18s
   pytest <C0 modules> + <the C1 module> -q
       -> 65 passed in 5.24s
   pytest tests/unit/workflows tests/unit/sdsc_submission_scripts -q
       -> see §8.3 (subsystem regression for both changed authorities)
   ruff check / ruff format --check on the 4 touched files -> clean
   ```

   **Live defect reproduction recorded before the fix** (the evidence C1's
   acceptance rests on): a composed Pets pseudo tuner run with gates ON
   raised
   `ValueError: HealthGate monitored files violate the DataScope: gate
   'output_diversity_blocking' … peek_file_indices [10, 17] outside the
   DataScope [0, 1, 2, 3]` — TIDMAD's gates, TIDMAD's peek files, Pets'
   scope. After the fix the workflow hands the tuner
   `{workspace}/health_checks_effective.yaml` carrying
   `pets_distinct_symbols_blocking` / `pets_dominant_fraction_blocking` and
   `task_health_binding: explicit`.

8. **Commit boundary.** Projection-independent invariant sites only; no
   schema, prompt, plugin or census work. — [x] **HELD**: two production
   files (`run_one_iteration.py`, `model_exploration.py`), no schema field,
   no ContextVar read, no prompt byte, no plugin surface.

### C2 — Composition threading (D-12a-1) + EVERY projection consumer

1. **Goal.** The tuner learns "this run is composed" from its INPUT — and
   every consumer of that fact (the W4 discriminator AND the per-model
   lock's identity kwargs) moves onto the projection in the SAME commit,
   so no temporary dual authority ever exists.
2. **Scope.** `agent/schemas/hyperparam_tuning.py` (additive default-`None`
   projection field — RATIFIED, §0.1 item 4); the workflow's tuner-input
   construction; the W4 guard (`ml_hyperparameter_tune_agent.py:839`); the
   tuner's `build_run_invariants` call (`:605-625`) gaining
   `task_composition_fingerprint` + `task_health_binding` READ FROM THE
   PROJECTION; the W4 census
   (`test_step10_p56_c5_wiring_closures.py:199-259`) re-pointed at the new
   key while keeping its forbidden-token list.
3. **Implementation plan**
   - [x] Audit every tuner-file read of `active_task_data_path` /
         `active_composition_fingerprint`; enumerate which move to the
         projection (W4 guard, lock kwargs) and which remain authority
         reads (record stamps — Step-11's AST pin stays green); finalize
         the projection field set from this enumeration.
         **Audit result** (complete, at `c54dc960`):

         | read | sites | disposition |
         |---|---|---|
         | `active_task_data_path()` | 1 — the W4 guard, tuner `:839` | **MOVES** to the projection |
         | `active_composition_fingerprint()` | 2 — `records.py:490,838` | **STAYS** (Step-11 F-11-C10-a, AST-pinned) |
         | `resolve_dataset_profile()` | tuner `:502` | STAYS — run-scoped subsystem authority; D-12a-1 excludes it |
         | `resolve_bound_run_metric()` / `..._secondary_metrics()` | tuner `:555`, `:570` | STAY, same reason |

         **Field set FINALIZED as three** — `semantic_fingerprint`,
         `task_data_path_id`, `task_health_binding`. The health binding is a
         member because C1's F-12a-C1-3 left the marker half open and C2 owns
         it; D-12a-1 explicitly delegates the exact set to this audit step.
   - [x] Add the field; populate from `bindings.task_composition`; re-key
         W4; add the lock kwargs reading the projection (closing F-P56-3's
         lock-honesty half; flips C0 guard (b)'s fingerprint half).
         **Landed**: `TaskCompositionRef` (frozen, `extra="forbid"`) and
         `HyperparamTuningInput.task_composition_ref` (additive, default-`None`);
         `build_task_composition_ref` beside C1's authority in
         `model_exploration.py`; threaded through the `local_validated_model`
         protocol; the W4 guard and BOTH `build_run_invariants` kwargs read it;
         the tuner's `active_task_data_path` import is REMOVED.
   - [x] Mutation: populate the field while leaving ContextVars unbound ⇒
         W4 and the lock kwargs behave per the FIELD (proving the reads
         moved); `verify_composition_is_bound` still refuses the
         half-composed run at the workflow layer.
         **Landed as a PERMANENT test**, not a throwaway plant:
         `test_the_guard_follows_the_FIELD_even_with_the_contextvars_unbound`
         asserts the ContextVars are unbound FIRST, then requires the composed
         named-absence line and forbids the legacy "Reference scores loaded"
         line.
4. **Validation plan.** Unit + the re-pointed W4 census + prompt-byte parity
   (the guard's OUTPUT is unchanged for both branches); composed fixture →
   per-model lock carries the fingerprint + honest health identity.
   — [x] all four; see §7 below.
5. **Acceptance criteria.** Zero `active_task_data_path()` calls remain in
   the tuner package (census); guard (b)'s fingerprint half closed; legacy
   and composed prompt bytes identical to C0/C1 state; Step-11's
   two-call-site fingerprint pin still green. — [x] **DISCHARGED**, with the
   census implemented over the AST rather than as a text scan (F-12a-C2-2).
6. **Failure/edge cases.** A caller constructing `HyperparamTuningInput`
   without the field (every existing test) gets `None` ⇒ legacy behaviour;
   the field must never be REQUIRED (additive schema discipline, R-11-14's
   lesson — designed-in, not discovered-in). — [x] **HELD**: `default=None`,
   and the legacy behavioural consequence is asserted directly
   (`test_an_un_composed_run_OMITS_the_key_entirely`,
   `test_the_legacy_branch_still_loads_them`).
7. **Verification commands and evidence.**

   ```text
   pytest tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py -q
       -> 12 passed
   pytest <C0 x2, C1, C2, P56-C5 wiring, health-feedback wiring> -q
       -> 114 passed in 6.76s
   ruff check / ruff format --check on every touched file -> clean
   pyright -> NOT RUN LOCALLY (vendored bundle cannot execute here); CI owns it
   ```

   **Live closure evidence** (composed TIDMAD, gates ON, through the real tuner):

   ```text
   chain effective sha   c69fda089cb33b1872fef0bba3f005325f70e32b8aa770004596d23d651c41da
   per-model lock sha    c69fda089cb33b1872fef0bba3f005325f70e32b8aa770004596d23d651c41da  EQUAL
   per-model lock fp     d6628a93fcb3578ca32812f39246f2b51abeecbd24d21df56856ea0ef9c56d3a
   per-model doc marker  explicit          (was `legacy_default` after C1 alone)
   ```

   The body-sha equality is the half C1 deferred (F-12a-C1-3), now closed.

8. **Commit boundary.** The projection and ALL its consumers, nothing else.
   — [x] **HELD**: schema + protocol + workflow builder/hand-off + the two
   tuner consumers, plus the tests those changes own. No prompt byte, no
   plugin surface, no metric semantics.

### C3 — Deliverable acquisition: pin + stale-comment truth (A-12a-1)

1. **Goal.** The already-landed C6 behaviour at the tuner is PINNED, and the
   source stops describing the pre-C5/C6 world.
2. **Scope.** A differential test; the `:524-537` comment block; the parent
   §4.1-R2 ledger row.
3. **Implementation plan**
   - [x] Differential pin: composed run with a declared `deliverable:` ⇒
         `run_deliverable_spec.naming` IS the declared naming at the tuner;
         un-declared ⇒ shipped naming byte-identical.
         **Landed** `tests/unit/workflows/test_step12_pr12a_c3_deliverable_pin.py`
         (5 tests): declared `pr12a_c3_declared_pred` resolves; un-declared
         composed AND un-composed both resolve `abra_validation_denoised`;
         plus a REACHABILITY assertion that the tuner still has exactly ONE
         acquisition site and that it is still
         `derive_tidmad_deliverable_spec(run_profile)` — without it the
         differential could drift into testing an expression production no
         longer evaluates.
   - [x] Correct the stale comment (naming crosses via the bound authority +
         `--task_manifest`; storage half remains profile-derived → 12b).
         **Landed** at the tuner's acquisition site: the old text claimed the
         spec "crosses no process boundary" and is reconstructed child-side
         from `--dataset_profile_json` alone, which stopped being the whole
         truth at Step 11 C5/C6. It now separates the two halves explicitly.
   - [x] Update the parent ledger row (re-classification recorded with this
         evidence). **Landed** — parent §4.1 rows `#2 (R2)` and `#12` both
         corrected, each naming the Step-11 mechanism that closed the naming
         half and routing the storage half to PR-12b/Q-12-4.
4. **Validation plan.** The pin + existing C6 suites untouched. — [x]
   `test_step12_pr12a_c3_deliverable_pin.py` + `test_step11_c6_deliverable_naming.py`
   + the C0 guards = **56 passed**.
5. **Acceptance criteria.** Pin green both branches; comment matches source
   behaviour; no production logic change in this commit. — [x] **DISCHARGED.**
6. **Failure/edge cases.** None new — this commit must be logic-free. — [x]
   **HELD**: the only production edit is a comment block; `git diff` on the
   tuner shows no executable line changed.
7. **Verification commands and evidence.**

   ```text
   pytest tests/unit/workflows/test_step12_pr12a_c3_deliverable_pin.py \
          tests/unit/execute_tools/test_step11_c6_deliverable_naming.py \
          tests/unit/guardrails/test_step12_pr12a_c0_defect_baselines.py -q
       -> 56 passed in 3.17s
   ruff check / ruff format --check -> clean
   ```

8. **Commit boundary.** Pin + docs truth only. — [x] **HELD.**

### C4 — Issue #234: fail-closed output types, one vocabulary authority

1. **Goal.** An external model plugin with a novel or malformed output
   declaration REFUSES loudly; loader and validator read one authority.
2. **Scope.** `ml_models/plugin_loader.py:80-87`; `_LEGAL_OUTPUT_TYPES`
   (`ml_code_validator_agent.py:368`); D-12a-3's two declared sets; the
   `hybrid` §8c audit.
3. **Implementation plan**
   - [x] Audit step: enumerate every `output_type` consumer branch
         (`inference_single.py:296-319`, `models_format_sandbox.py` §8c,
         `get_output_type` callers) and freeze the plugin-legal set from
         the evidence. **Audit result:**

         | consumer | branch | verdict |
         |---|---|---|
         | `inference_single.py:318-319` | `output_type == "regressor" or (output_type == "hybrid" and target_dtype == torch.float32)` | `hybrid` is LOAD-BEARING — it routes regression |
         | `models_format_sandbox.py:491+` `output_semantic_from_legacy` | `hybrid` → `None` (a legacy adapter value, "not a tensor semantic") | keeps `hybrid` in the vocabulary |
         | `models_sandbox.py:745` `BUILTIN_OUTPUT_TYPES` | `fcnet` → `hybrid` | `hybrid` reaches the registry via BUILTINS only |
         | `agent/prompts.py:1176-1183`, validator `:509`, `scripts/inspection_cost_study` | classifier / regressor | no `hybrid` arm |

         **Plugin-legal set frozen at 2 from the corpus, not from doctrine:**
         109 generated plugins on record = **106 `classifier` + 3 `regressor`
         + 0 `hybrid`**; the pseudo-data plugin declares `classifier`; the
         implementor template always emits one of the two.
   - [x] Declare `OUTPUT_TYPE_VOCABULARY` + `PLUGIN_LEGAL_OUTPUT_TYPES` in
         one place; loader refuses (named skip) outside the plugin-legal
         set; validator imports the same subset. **Landed** in
         `ml_models/plugin_loader.py`; the validator's `_LEGAL_OUTPUT_TYPES`
         now BINDS the imported authority (`is` the same object).
   - [x] Flip C0 guard (c); regression test = the graduation falsifier
         (plugin declaring `"segmentation_masks"` refuses, never trains as
         a classifier). **Guard (c) RETIRED**; the falsifier and the
         end-to-end reachability chain live in
         `tests/unit/ml_models/test_step12_pr12a_c4_output_type_vocabulary.py`
         (17 tests).
   - [ ] Stage the GitHub #234 closure text (posted at merge) — C9.
4. **Validation plan.** Unit: refusal + named reason; builtin `fcnet`
   (`hybrid`) unaffected; validator/loader agreement census (a planted
   divergent literal turns RED). **End-to-end reachability (operator
   addition, §0.1 item +): a run that explicitly REQUIRES a malformed
   external model plugin (its `model_type` is the run's selected model)
   must FAIL CLOSED — a deterministic test proves the loader-level named
   skip surfaces as a run-level failure naming the plugin, and the run
   can never silently fall back to another model and succeed.**
5. **Acceptance criteria.** Zero silent output-type defaults; one authority,
   two derived sets, agreement mutation-proven; the required-plugin-invalid
   → no-fallback-success chain has a named test. — [x] **DISCHARGED**, with
   one precision: "zero silent defaults" is true of every PRESENT
   declaration. Omission keeps its default by the evidence decision below,
   and that default is neither silent nor unrecorded.
6. **Failure/edge cases.** A plugin OMITTING `PLUGIN_OUTPUT_TYPE` keeps its
   current documented default only if the audit proves that default is
   load-bearing for existing generated plugins; otherwise it joins the
   refusal — decided by evidence, recorded either way.
   — [x] **DECIDED: the omission default is KEPT.** The corpus evidence
   points the other way (0/109 rely on it), but the decisive evidence is a
   sibling subsystem's: the VALIDATOR's matching `_DEFAULT_OUTPUT_TYPE` is a
   deliberately preserved legacy-read path with its OWN reachability test
   (`test_step04a_validator_compat_baseline.py:148`, whose docstring calls
   itself "the only thing standing between `_DEFAULT_OUTPUT_TYPE` and silent
   removal"). Refusing omission in the loader while the validator still
   accepts it would **recreate the exact loader/validator divergence this
   commit exists to remove.** #234 is about a declaration that is PRESENT
   and unrecognised; that is what fails closed.
7. **Verification commands and evidence.**

   ```text
   pytest tests/unit/ml_models tests/unit/agent/ml_code_validator_agent \
          tests/unit/guardrails -q      -> 752 passed in 25.40s
   ruff check / ruff format --check     -> clean
   ```

   **Three Step-03 A3 tests were UPGRADED, not deleted** — see §8.6.

8. **Commit boundary.** Output-type vocabulary only. — [x] **HELD.**

### C5 — D16: `MetricSpec.id` becomes an opaque identifier (D-12a-4 as RULED)

1. **Goal.** The framework stops inferring metric-vs-objective semantics
   from a name token anywhere; the loss/metric boundary is enforced only by
   the owning typed contracts.
2. **Scope.** `evaluation_metric.py:118-140,390` and every
   `_reject_loss_shaped` consumer; the pinning tests; the CLAUDE.md
   Step-06 invariant bullet (amended to "metric identity is opaque; the
   loss/metric boundary is typed-contract-owned", citing roadmap
   §22.18-D16).
3. **Implementation plan**
   - [x] Audit step (per the ruling): enumerate EVERY `_reject_loss_shaped`
         consumer and every MetricSpec construction path, and determine
         whether ANY remaining lexical rejection protects a real typed
         invariant that the owning contract cannot express. Expected
         conclusion: none — `_is_loss_shaped` exits EvaluationMetric
         identity validation entirely.
         **Audit result: THREE consumers, not the one §2.2 names** —
         `MetricSpec.id` (`:390`), `MetricResult.metric_id` (`:418`) and
         `NotScoreableResult.metric_id` (`:438`). All three are pure IDENTITY
         validation, so all three lose the lexical check; leaving any one
         would make a `log_loss` metric declarable but unusable end-to-end.
         **No typed seam needs a replacement guard**, and the audit found the
         boundary already enforced three ways: `EvaluationMetric` requires a
         `MetricSpec` with an `aggregation` and an executable
         `ScoreabilityContract` over a DELIVERABLE (a training objective has
         neither); `_compose_metric` type-checks the declared implementation;
         and the record-facing types are `extra="forbid"` with zero
         loss-named fields.
   - [x] If (and only if) the audit finds a real internal seam where a
         TrainingObjective could be mis-fed into an EvaluationMetric slot,
         guard THAT typed seam explicitly; the `"loss"` token check is
         removed regardless. — **No such seam. No new guard added**, which is
         the expected end state the ruling names.
   - [x] Flip C0 guard (d) (`log_loss` declaration composes; direction
         still comes from the declaration, never the name). **Guard (d)
         RETIRED**; its successors are the UPGRADED pins where the refusal
         used to live (§8.7).
   - [x] Amend the CLAUDE.md bullet in the same commit. **Done** — the
         Step-06 invariant bullet now states that the loss/metric boundary is
         typed-contract-owned and that `MetricSpec.id` is OPAQUE. The
         `evaluation_metric.py` MODULE docstring carried the same stale claim
         ("reject loss-shaped identities at construction") and was corrected
         with it.
4. **Validation plan.** Unit: `log_loss` (lower) composes and evaluates in a
   fixture; an arbitrary opaque id (`banana_metric`) composes identically;
   the tuner's same-loss `final_loss` rank untouched (its pinned test stays
   green); no metric arithmetic moves; any new typed-seam guard has its own
   reachability + mutation test. — [x] all; no typed-seam guard was needed.
5. **Acceptance criteria.** Zero lexical metric-name semantics remain in
   identity validation (census over `evaluation_metric.py`); the
   fourth-task criterion "primary metric id containing a loss token" is
   satisfiable as ordinary declaration, not as a special-cased permission;
   every previously-pinned refusal test is UPGRADED (not deleted) to pin
   the typed boundary instead. — [x] **DISCHARGED.** `_is_loss_shaped` is
   DELETED; `_reject_loss_shaped` became `_validate_metric_identifier`,
   which does hygiene only. `log_loss` composes as an ordinary declaration
   with no permission list anywhere. Four pinning tests upgraded across
   three modules, zero deleted.
6. **Failure/edge cases.** A declaration whose id is loss-shaped AND whose
   direction is omitted must still fail the declaration validator for the
   missing direction — the removal must not weaken any sibling check.
   — [x] **HELD, and pinned**: `direction` is a required `MetricDirection`
   field, unchanged; and the identifier hygiene sibling (non-empty, no
   surrounding whitespace) now has its OWN parametrized test across all
   three types, which it did not have before — removing the lexical rule
   made that check the only thing left in the function, so it needed to
   stop being incidental.
7. **Verification commands and evidence.**

   ```text
   pytest tests/unit/execute_tools tests/unit/examples tests/unit/guardrails -q
       -> 2410 passed, 2 skipped in 137.57s
   ruff check / ruff format --check   -> clean
   ```

8. **Commit boundary.** D16 only. — [x] **HELD**: one production module, the
   four tests that pinned its old rule, two pack docs whose own inverted pin
   forced them, and the CLAUDE.md bullet the design requires in the same
   commit.

### C6 — Plugin-registration consolidation (D-12a-8)

1. **Goal.** One public plugin-registration authority; `core/resume.py`
   stops importing a private `workflows` symbol (09.5 Q2 = B closed).
2. **Scope.** `model_exploration.py:924-967` (retire), `:1122` +
   `resume.py:74` (migrate), `:2883-2887` (dissolve workarounds);
   `plugin_loader.register_model_in_memory` (unchanged unless parity audit
   demands a keyword).
3. **Implementation plan**
   - [x] Parity audit: side-by-side behaviour table (inputs, registries
         written, return values, failure paths, prints) — recorded in this
         doc before the switch.

         | axis | `_add_plugin_to_registries` (retired) | `register_model_in_memory` (survivor) |
         |---|---|---|
         | input | `plugin_path: str` | `plugin_path: str` |
         | loader | `_load_plugin(path)` | `_load_plugin(path)` — the same function |
         | registries written | `MODEL_REGISTRY`, `PLUGIN_CONFIG_REGISTRY`, `PLUGIN_OUTPUT_TYPE_REGISTRY` | the same three |
         | success return | `model_type` | `model_type` |
         | failure return | `None` (loader logged the reason) | `None` (loader logged the reason) |
         | extra behaviour | none | **prints a warning** when re-registering a `model_type` whose class `__qualname__` differs |

         The ONLY delta is the re-registration warning, and it is strictly
         MORE visible — which is why the public one is the survivor rather
         than the private one being kept for byte-sameness.
   - [x] Migrate both callers; delete the private function; restore
         `union_key_findings` to a normal top-level import if the cycle is
         gone (audit confirms). **Done, and the cycle IS gone**: both
         `RestoredState` and `union_key_findings` are ordinary top-level
         imports, the `TYPE_CHECKING` block is deleted, the quoted
         `restored_state: "RestoredState | None"` annotation is unquoted, and
         the function-local import buried inside `run_workflow` is removed.
         A second local import (`register_model_in_memory` at the
         post-validation registration site) collapsed into the module-level
         one in passing.
   - [x] Reachability: a restored plugin registers through the public
         authority (existing resume tests re-pointed, not weakened).
         **Re-pointed**: `TestAddPluginToRegistries` →
         `TestRegisterModelInMemory` with every assertion unchanged — the
         failure class it owns (a regressor miscategorised as a classifier
         because `PLUGIN_OUTPUT_TYPE_REGISTRY` was never written) belongs to
         whichever function writes those registries, and that is now the
         public authority.
4. **Validation plan.** Unit + the resume plugin-restoration suite; import
   census (zero `workflows.model_exploration` imports in `core/`). — [x]
   `tests/unit/core/test_step12_pr12a_c6_registration_layering.py` (24 tests).
   **The census bans PRIVATE cross-layer imports, not the layer edge** — see
   §8.8 finding F-12a-C6-1 — and carries its own anti-vacuity test proving the
   scanner detects the shape it bans.
5. **Acceptance criteria.** One authority; cycle gone; behaviour parity
   recorded; the re-registration warning is the only permitted delta. — [x]
   **DISCHARGED**, all four.
6. **Failure/edge cases.** `restore_prior_state` must keep its
   warn-and-continue semantics on a plugin that fails to load (`resume.py`
   `:1499-1506` shape) — the consolidation must not convert it to a raise.
   — [x] **HELD, and pinned from BOTH sides**: the branch still tests
   `registered is None` and calls `warnings.warn` with no `raise` before it,
   AND the new callee still returns `None` rather than raising on a broken
   plugin. Only the pair makes warn-and-continue actually preserved.
7. **Verification commands and evidence.**

   ```text
   pytest tests/unit/core/test_step12_pr12a_c6_registration_layering.py -q
       -> 24 passed
   pytest tests/unit/{workflows,core,ml_models,guardrails} -q
       -> 3930 passed in 175.41s
   ruff check / ruff format --check -> clean
   ```

8. **Commit boundary.** Registration lifecycle only. — [x] **HELD.**

### C7 — LLM-facing family: prompt science ownership (D-12a-5/6/7)

1. **Goal.** A composed run's prompts carry the TASK's science and none of
   TIDMAD's; legacy prompt bytes are byte-identical; lit-review's ratified
   guard lands.
2. **Scope.** `agent/prompts.py` (planner/reflector TIDMAD blocks →
   composition-gated; F-12-5 rewording per D-12a-5); the proposer task-blocks
   mechanism + `configs/task_proposal/tidmad.yaml` + manifest
   `proposal_blocks:` section + fingerprint participation; implementor
   literals; `run_workflow`'s lit-review guard; the five prompt-pinning test
   files (each UPGRADED with the disposition recorded).
3. **Implementation plan**
   - [x] Audit step: exact render-path map for each block (which are inside
         the reference-scores conditional already, which always render);
         byte-level options for F-12-5 with the recommendation; **and the
         D-12a-5 classification (operator amendment, §0.1 item 3): every
         removed hardcoded block is classified as (1) optional TIDMAD-only
         advice → named absence, or (2) required task semantic guidance →
         replaced from a task-owned authority (task description,
         ModelIOContract/forward-contract wording, metric identity +
         direction, proposal blocks). The classification table is recorded
         in this document before any block moves; a blanket
         "not available" treatment is not acceptable.**
         — `cf7670c1`; the table is §8.9, recorded BEFORE any block moved. The
         design's inventory was INCOMPLETE: the banned-token census found 3
         more blocks, so 10 are classified, not 7.
   - [x] Implement D-12a-6 (schema, loader+adapter, manifest section,
         composer, verbatim prose move, AST guard on the single default-path
         constant). — C7-3 `bf0b37a4`; §8.13; 20 tests.
   - [x] Implement D-12a-5 gating; D-12a-7 guard. — C7-2 `ed29cb7b` (7 tokens,
         legacy rendered manifest UNCHANGED at `6e8de64b…`), C7-1 `2a9e95c9`.
   - [x] **C7-5 — the Pr2/Pr3 residues (F-12a-C9-1, §8.17).** Found by
         building the Gate-1 harness, not by a census: `PROPOSAL_COMMIT_PROMPT`
         was never on any census's surface list. Closed inside D-12a-6 with
         seven additional `ProposalTaskBlocks` keys; composed banned-concept
         count 0 with blocks declared AND absent; legacy byte-identical.
   - [x] **D-12a-9 `ImplementorTaskBlocks`** — the operator-ratified bounded
         contract correction (§8.15). NOT in the frozen §0.1 ratification; the
         boundary was raised (§8.14) and Option A authorized. Eight required
         validations discharged; 25 tests; mutation 5 RED / restore 25 green.
   - [x] Flip C0 guard (e); legacy byte-parity fixtures green untouched.
         — the two DECLARED source-sha re-freezes (C7-2, C7-4) carry their
         evidence; `LEGACY_TUNER_PROMPT_MANIFEST_SHA` and the PB goldens never
         moved.
4. **Validation plan.** Unit: composed pseudo prompts contain zero
   banned-TIDMAD tokens (extend `test_prompt_banned_vocabulary` to the
   composed branch); legacy sha fixtures byte-identical; manifest unknown-key
   refusal covers the new section; fingerprint moves when blocks change and
   only then. **Gate 1 (G-12a-1) evidence commits ride C9.**
5. **Acceptance criteria.** Composed-run prompt surface free of TIDMAD
   science (probe-verifiable); **every removed block carries a recorded
   classification, and every "required semantics" block has a named
   task-owned replacement rendering**; legacy bytes identical; lit-review
   enabled + composed ⇒ named startup refusal; proposer blocks absent ⇒
   zero bytes.
6. **Failure/edge cases.** The P3 lesson: a JSON example does not teach a
   semantic — the proposer blocks carry TIDMAD's prose VERBATIM, and any
   wording change is out of scope; a composed task with no proposal blocks
   must degrade to structural guidance, never to TIDMAD's.
7. **Verification commands and evidence.** `[x]` C7 deterministic re-run at
   the C7-4 head — `pytest tests/unit/guardrails/ tests/unit/agent/
   ml_model_implementor/ tests/unit/agent/test_step04a_stage_b_ladder.py
   tests/unit/workflows/ tests/unit/agent/protocols/ tests/unit/agent/
   ml_model_proposal_agent/ tests/unit/nodes/ -q` → **2,210 passed, 0 failed**.
   Two declared goldens/pins moved, surgically (§8.15).
8. **Commit boundary.** Prompt/content ownership only; no evidence-schema
   changes. **Amended by the operator ruling of 2026-08-22**: C7-4 adds ONE
   additive default-`None` input field and its optional manifest section
   (D-12a-9, §8.15). This is a ratified contract correction, recorded as a
   deviation from the frozen §0.1 ratification rather than folded in silently.

### C8 — Censuses, re-audit table, docs sync

1. **Goal.** The guards cover the files where the residues survived; the
   B-class re-audit is a recorded ledger artifact; operator docs match
   merged behaviour.
2. **Scope.** F-12-6 census widening (singleton-import guard over
   `run_one_iteration.py` + `resume.py`); the §3 re-baseline table completed
   with per-item evidence; node/operator `.md` sync (tuner `.md`, workflow
   docs, `configs/task_proposal/` README); parent-ledger update; structural
   pre/post comparison vs C0.
3. **Implementation plan**
   - [x] F-12-6 census widening over `run_one_iteration.py` + `core/resume.py`
         — both already clean; mutation-proven RED on each independently
         (F-12a-C8-2, §8.16).
   - [x] Shipped TIDMAD manifest + P1 fixture declare `proposal_blocks:` and
         `implementor_blocks:`; two Step-10 pins updated WITH the reason
         recorded; the additive rule re-proved on DAVIS + Pets against
         `eeb073dc`-measured values (F-12a-C8-1).
   - [x] Node/operator `.md` sync — tuner `.md` guard snippet, `architecture.md`
         loss-shaped claim, manifest comments (§8.16 table).
   - [x] Structural pre/post comparison vs the C0 table (F-12a-C8-3): zero
         parameter growth, max branch growth +1 against a budget of 3, and
         `HyperparamTuningAgent.run` UNCHANGED at 258.
   - [x] Parent-ledger update — the parent's child-design ledger now carries the C0-C8 state, the D-12a-9 deviation, the shipped-manifest fingerprint move and the CASE A debt.
4. **Validation plan.** Widened census RED on a planted TIDMAD singleton
   import in either file; doc claims quoted against merged source. — `[x]`
   both discharged, §8.16.
5. **Acceptance criteria.** Census plants proven; every touched function's
   post-measure within the parent §10 rules (no new branch family).
6. **Failure/edge cases.** Widening may surface pre-existing leaks — record,
   never exempt by name (Step-11 C9's rule). — none surfaced; both files were
   already migrated, and the widening is regression protection (F-12a-C8-2).
7. **Verification commands and evidence.** `[x]` `pytest tests/unit/workflows/
   tests/unit/guardrails/ tests/unit/agent/ tests/unit/nodes/ -q` at the C8
   head; the structural table is reproduced by
   `current_structure()` vs `STRUCTURAL_BASELINE` (§8.16).
8. **Commit boundary.** Guards + docs only. **Doc sync lands here, before
   the final push.**

### C9 — Gate evidence and closeout

1. **Goal.** The PR's two owed real-evidence artifacts, at the final
   executable head.
2. **Scope.** Gate readiness packets, launches, §7-ledger records. No
   production change beyond what Gate evidence itself requires.
3. **Implementation plan**
   - [x] **G-12a-1 (Gate 1) — PASS (§8.18).** readiness packet; bounded real-LLM probe set
         (≤ ~6 calls) with **explicit pre-chosen task-fact assertions
         (operator amendment, §0.1 item 3)** — the fixture names 2–3
         concrete facts of the composed task (input topology; prediction
         target; primary metric identity + direction) and the real model's
         response must correctly reflect EACH of them while hitting ZERO
         banned TIDMAD concepts. Never a subjective "the model understands
         the task" criterion. Legacy prompts asserted byte-identical (no
         probe needed where bytes are pinned).
   - [x] **G-12a-2 (Gate 2) — PASS (§8.22).** readiness packet quoting the gate-standard
         row; §6.3's semantic-latency analysis attached; DEFAULT 2 × 1
         composed-TIDMAD real chain — acceptance = iteration 2's pre-flight
         validates against iteration 1's lock (fingerprint carried), the
         per-model lock carries the fingerprint + honest health identity,
         records/outputs stamped from the one authority; **NOT criteria**:
         model quality, HealthGate PASS, score magnitude, convergence.
   - [x] Record both results against exact SHAs, then close out under the
         **terminal SHA discipline (operator amendment, §0.1 item 5 — the
         Step-11 shape)**:

         ```text
         FINAL EXECUTABLE HEAD  →  Gate 1 + Gate 2 execute HERE
             ↓
         Gate evidence / ledger / closeout docs committed
             ↓
         FINAL PR HEAD          →  verify executable-head..PR-head is
                                   DOCS-ONLY (git diff name-status census)
             ↓
         ONE authoritative CI at the exact final PR head
             ↓
         NO commit after that CI head
         ```

         Gate SHA == PR SHA is NOT required and MUST NOT trigger a Gate
         re-run for formal sameness; a Gate re-runs only if a
         post-Gate change touches a Gate-owned execution path.
4. **Validation plan.** The Gates ARE it; launched only inside the
   pre-authorized envelope and never tuned green.
5. **Acceptance criteria.** Both Gates PASS at the final EXECUTABLE head
   (or their failures dispositioned per the standard); the
   executable-head→PR-head delta verified docs-only; CI SUCCESS at the
   final PR head; no commit after it.
6. **Failure/edge cases.** A Gate-exposed production defect gets its own
   commit + checklist; the Gate re-runs only if the fix touches a Gate-owned
   path.
7. **Verification commands and evidence.** `[x]` COMPLETE.

   ```text
   G-12a-1   PASS      executable SHA  f542e89e  (Gate ran here; C7-5 head)
             4 real calls of a 6 cap, 13 of 13 checks after the probe
             correction, 12 of 12 as originally enumerated
             evidence  /home/klz/Data/SIDEREIS_DATA/gate_evidence/
                       step12_pr12a_gate1/gate1_result.json

   G-12a-2   PASS      executable SHA  ec30bd65  (Gate ran here; F-12a-G2 head)
             canonical run = ATTEMPT 4
             A1 iteration 2 validated iteration 1's lock         PASS
             A2 per-model lock identity (fingerprint + health)   PASS
             A3 records stamped from ONE authority               PASS (9)
             evaluator  scripts/step12_pr12a_gate2_evaluate.py
                        (written and falsified BEFORE the outcome)
             evidence   /home/klz/Data/SIDEREIS_DATA/gate_evidence/
                        step12_pr12a_gate2/gate2_result.json
             disposition: NOT an uninterrupted chain. Iteration 1 completed
                        and committed state; a provider/network hang followed;
                        the process was KILLED; a NEW process resumed at
                        iteration 2 in the SAME workspace and consumed
                        iteration 1's committed state. Accepted by operator
                        terminal review as proving the owned failure class
                        across a real process restart (§8.22, §8.24 1D)

   PRE-TERMINAL-REVIEW final state (superseded by the closeout commit that
   applies the terminal-review fixes, which necessarily moves the PR head):
             final executable head   ec30bd65
             PR head                 870897c6
             authoritative CI        32613380946 SUCCESS
   ```

   The post-review final PR SHA and its authoritative CI are recorded in
   §8.25.
8. **Commit boundary.** Evidence + ledger only. STOP at READY FOR OPERATOR
   REVIEW; never merge.

---

## 6. Validation topology & evidence economy

### 6.1 Deterministic (unit) ownership
Byte-parity fixtures (prompts, locks, argv, effective-config shas) ·
composed differentials (scope topology, lock identity, naming, log_loss,
output-type refusal, prompt gating) · mutation plants (censuses, W4 re-key,
vocabulary agreement) · negative tests (LEGACY_OMITTED unreachable when
composed; lit-review guard; unknown output type). Targeted runs per commit;
no full local suite; the formal PR's automatic CI is the canonical
exact-head evidence.

### 6.2 Gate ownership
G-12a-1 owns real-model reading of the changed prompt surface; G-12a-2 owns
the real lock/fingerprint/resume chain. Neither owns model quality.

### 6.3 Semantic-latency analysis (obligation for the G-12a-2 depth)
The changed state (pre-flight lock values, per-model lock stamps,
health-family identity) is PRODUCED in iteration 1 and CONSUMED by
iteration 2's pre-flight (`compute_expected_invariants` →
`validate_run_invariants`) and `restore_prior_state` ingress. That
consumption exists ONLY across an iteration boundary through a real process
restart — a 1×1 run never re-reads its own lock. **Default 2×1 therefore
stands; no downgrade is proposed.**

---

## 7. Risks

| risk | mitigation |
|---|---|
| prompt work regresses model behaviour (the P3 precedent) | verbatim prose moves only; byte-pins for legacy; G-12a-1 probes for composed; any wording change beyond the audited set is out of scope |
| the health hand-off change collides with per-model workspace semantics | C1's audit step maps every consumer of `agent_input.health_checks_config` before the switch; effective-body-sha equality is the oracle |
| additive schema field misused as a second authority | the field is a PROJECTION; record stamps keep reading the run-scoped authority (Step-11 AST pin stays green as the guard) |
| D16 narrowing weakens the loss/metric boundary | refusal retained on non-declaration paths; every old refusal test upgraded, none deleted |

---

## 8. Implementation ledger

**Entry conditions (all must hold before C0 begins):**

- [x] Operator approval — GRANTED 2026-08-22 ("APPROVE WITH TARGETED
      AMENDMENTS"; all amendments applied in rev 2, §0.1), constituting the
      explicit ratification of the additive contract changes D-12a-1 /
      D-12a-6 and the D-12a-4 / D-12a-5 rulings.
- [x] Master re-anchored at implementation start; if it moved past
      `e4cd5c18`, a bounded delta re-check of §2's anchors is recorded here
      first. — **VERIFIED 2026-08-22, master UNMOVED.** `git fetch` then
      `origin/master == master == e4cd5c18`; `720c3efc` and `e4cd5c18` are
      both ancestors of the implementation start `eeb073dc`;
      `git diff --name-status e4cd5c18..eeb073dc` = **4 files, all under
      `docs/`** (zero production source touched by the planning session). No
      bounded delta re-check is owed.
- [x] Fresh Implementation Working Rules context. — Fresh session, fresh
      filled contract, `before_end_memory.md` re-initialized for PR-12a
      (the Step-11 handoff was REPLACED, not appended to).

### 8.0 Implementation anchors

```text
implementation branch   step12-pr12a-composed-path-closure
implementation base     eeb073dc   (frozen design 720c3efc + parent ledger)
executable source base  e4cd5c18   (= origin/master)
```

### 8.1 Entry source audit — every §2 anchor re-verified live

| §2 claim | verdict at `eeb073dc` |
|---|---|
| F-12-1 `run_one_iteration.py:1499` `run_scope.resolve(TIDMAD)`, import `:56`, composition already a parameter (`:1520-1527`) | **HELD**, exact line numbers unchanged |
| F-P56-3 tuner `:600` raw `agent_input.health_checks_config` → `build_run_invariants(` `:605` with neither identity kwarg | **HELD**, exact |
| W4 ambient read `:839` `active_task_data_path()`; the ONLY such call in the tuner package (import `:71`) | **HELD** |
| record/output stamps read `active_composition_fingerprint()` at exactly two sites, `records.py:490,838` | **HELD** — these STAY (D-12a-1) |
| A-12a-1 tuner `:537` `derive_tidmad_deliverable_spec(run_profile)` + the stale `:533-537` "crosses no process boundary" comment | **HELD** |
| #234 `plugin_loader.py:80-87` coercion; validator `_LEGAL_OUTPUT_TYPES` 2-member at `ml_code_validator_agent.py:368`, already fail-closed at `:485` | **HELD** |
| A-12a-3 `_add_plugin_to_registries` (`model_exploration.py:924`) vs public `register_model_in_memory` (`plugin_loader.py:230`); `resume.py:74` private import; cycle workaround `model_exploration.py:2887`; callers `model_exploration.py:1122` + `resume.py:1504` | **HELD** |
| F-12-5 `agent/prompts.py:66` hardcoded `` `denoising_score` ``; `:69-73` five model descriptions | **HELD** |
| Lit review `should_run_literature_review` returns the resolved flag (`model_exploration.py:497-526`) | **HELD** |

### 8.2 C0 findings

**F-12a-C0-1 — the (b-health) defect is worse than "a mislabelled marker".**

```text
Previous assumption (design §5 C0 guard (b-health)):
  a composed + gates-on tuner materialization "resolves `legacy_default`" —
  i.e. the per-model effective config carries the wrong binding marker.

Audit evidence:
  driving a COMPOSED Pets pseudo tuner run with `health_gate_enabled=True`
  does not merely mislabel the document — the run CANNOT START. The tuner's
  `build_run_invariants` omits `task_health_binding`, 08b resolves state A,
  and TIDMAD's task-health family is composed: gates
  `output_diversity_blocking` / `output_std_blocking` /
  `amplitude_collapse_blocking`, peeking files `[10, 17]`. Pets declares
  `num_files = 4`, so `validate_health_scope` refuses the run naming
  TIDMAD's gates and TIDMAD's peek files.

Corrected understanding:
  F-P56-3's health half is not an honesty defect on a working run; it makes
  every composed run with gates ON and a smaller topology unlaunchable, and
  a composed run with a LARGER topology silently evaluates another task's
  health science. A-12a-2 was right that the three-task closure drives could
  not see it (`health_gate_enabled=False`, `step00_pseudo_iteration.py:165`).

Implementation consequence:
  none for C0. C1's fix is unchanged in shape; its acceptance is stronger —
  the composed gates-on run must START and evaluate the TASK's family.

Validation consequence:
  guard (b-health) asserts the exact refusal message rather than a marker
  string, which is a strictly more specific witness, plus an AST reachability
  assertion that the tuner's call site omits BOTH identity kwargs.
```

**F-12a-C0-2 — structural-measurement convention delta vs parent §10.** The
parent's table and the Step-11 C0 `measure()` rules disagree by at most ±1
statement per function, and by +1 branch on `run_workflow` (parent 143, this
tool 144). A pre/post comparison needs ONE tool on both sides, so C0 freezes
**this module's** numbers and C8 compares against them. Recorded rather than
silently absorbed. Measured (stmts/branch/loc/params):

| function | C0 pre-value |
|---|---|
| `model_exploration.run_workflow` | 369 / 144 / 1567 / 21 |
| `model_exploration._add_plugin_to_registries` | 13 / 1 / 44 / 1 |
| `model_exploration._register_plugin` | 60 / 19 / 175 / 4 |
| `model_exploration.should_run_literature_review` | 4 / 0 / 29 / 2 |
| `HyperparamTuningAgent.run` | 258 / 67 / 1085 / 2 |
| `planning.prepare_attempt` | 116 / 32 / 471 / 7 |
| `execution.run_admission_preflight` | 107 / 36 / 521 / 6 |
| `execution.run_inference_scoring_health` | 109 / 26 / 474 / 6 |
| `run_one_iteration.compute_expected_invariants` | 6 / 3 / 64 / 2 |
| `resume.restore_prior_state` | 100 / 47 / 383 / 4 |
| `run_invariants.build_run_invariants` | 8 / 3 / 103 / 13 |
| `run_invariants.validate_stamped_invariants` | 25 / 14 / 101 / 4 |
| `plugin_loader._load_plugin` | 23 / 7 / 46 / 1 |
| `plugin_loader.register_model_in_memory` | 16 / 3 / 48 / 1 |
| `evaluation_metric._is_loss_shaped` | 4 / 1 / 14 / 1 |
| `evaluation_metric._reject_loss_shaped` | 6 / 3 / 14 / 2 |

**F-12a-C0-3 — a rendered prompt baseline is machine-dependent unless the
capability index is pinned.** The planner renders an AVAILABLE CUSTOM LOSSES
block from `agent_generated/_capability_index.json` — gitignored, mutable,
machine-local. A first capture embedded six developer-local loss names and
produced a different sha in two identical fresh processes. Diagnosis showed
only TWO variability sources: wall-clock timestamps (normalized) and that
registry (**pinned to an empty index via the injectable
`capability_index_path`, not scrubbed** — the block still renders through the
production path, it just renders the empty-registry content everywhere). With
both handled the manifest sha is bit-identical across three fresh processes.
This is the `CLAUDE.md` portability rule applied to evidence: a baseline that
is green only on the machine that recorded it validates nothing.

**F-12a-C0-4 — D16 has three lexical consumers, not one.** The frozen §2.2
names `MetricSpec.id` (`evaluation_metric.py:390`). Source also applies
`_reject_loss_shaped` to `metric_id` at `:418` and `:438`. Bounded deviation:
C5's audit step already requires enumerating EVERY consumer, so no contract
moves; the fact is pinned by an executable assertion in guard (d) so C5
cannot quietly close two of three.

**Bounded deviation — two ADDITIVE parameters on a shared test helper.**
`run_bounded_pseudo_iteration` gained `bridge=None` and
`capability_index_path=None`. Reason: `RecordingLLMBridge` is HANDED a prompt
and never renders one, so a baseline built on it would pin the test's own
strings; `StubLLMBridge` is a real `LLMBridge` subclass overriding only the
HTTP seam, so `plan()`/`reflect()` execute the production render paths.
Forking the harness would have produced two harnesses that drift. Both
defaults reproduce the previous behaviour exactly — **169 tests across the 12
existing consumers pass unchanged**.

### 8.3 C1 findings

**F-12a-C1-1 — the W7 census was structurally incapable of catching F-12-1.**
`TestW7PreflightAndWorkflowAgree` compares the two `build_run_invariants` call
sites' composition-derived keyword **NAMES**, and it was written precisely so
that "the next time a third is added" the blind spot would not recur. But
`resolved_data_scope` is passed by both sites, spelled identically, and
computed from different topologies — a name census cannot see a value
divergence. C1 therefore adds `TestW7ValueAgreement`, which drives the REAL
`run_workflow` for Pets and DAVIS and compares the pre-flight's value against
the workspace lock the workflow actually wrote. A pointer to it was added to
the W7 class so a future reader finds both halves.

**F-12a-C1-2 — the hand-off must be keyed on composition presence, because a
legacy swap would move a PERSISTED value.**

```text
Previous assumption (design D-12a-2):
  "the workflow passes the tuner the CHAIN-LEVEL effective config path" —
  stated unconditionally.

Audit evidence:
  the tuner captures `agent_input.health_checks_config` as
  `health_checks_config_source` at `:600`, BEFORE its own effective-path swap
  at `:635`. That value is persisted: `HyperparamTuningOutput.
  health_checks_config_source` (schema `:2837`) and the record key of the same
  name (`records.py:932`). `bindings.health_checks_config` has exactly ONE
  consumer — the tuner hand-off at `model_exploration.py:2686` — so the blast
  radius is precisely that field.

Corrected understanding:
  an unconditional swap would move a LEGACY gates-on run's recorded provenance
  from `None` to a path. C1's own acceptance says "zero legacy byte movement",
  so the swap is keyed on composition PRESENCE (C-P56-1's discriminator, never
  a task identity).

Implementation consequence:
  the decision became `resolve_tuner_health_config_source`, a named
  module-level authority with an exhaustive truth table.

Validation consequence:
  a 6-row parametrized truth table plus a LEGACY `run_workflow` drive
  asserting the tuner is still handed `None`.
```

**F-12a-C1-3 — C1 closes the composed ROSTER; the binding MARKERS are C2's.**
Handing over the chain's effective config makes the tuner's re-materialization
a roster no-op (measured: the per-model document carries
`pets_distinct_symbols_blocking` / `pets_dominant_fraction_blocking`, and none
of TIDMAD's three blocking gates). It does **not** make the body sha equal the
chain's, because `body_markers()` restamps from the binding it was called
with and the tuner still passes none — so the per-model document says
`legacy_default` while carrying the task's gates. C1's design line "the
per-model effective body sha equals the chain's" is therefore **re-anchored to
C2**, which supplies `task_health_binding` from the projection. Recorded, not
quietly redefined; the C1 test asserts the roster equality AND the
still-`legacy_default` marker so the gap cannot close silently or reopen.

Consequently the C0 guard's tuner-level half — that the tuner's own
`build_run_invariants` call passes NEITHER identity kwarg — was **re-anchored
from C1 to C2** and folded into `TestInvertedGuardBTunerOmitsCompositionIdentity`.
C1 changes what the workflow HANDS the tuner; it cannot change what the tuner
ASKS FOR.

**F-12a-C1-4 — the structural tripwire fired, and the fix was extraction, not
a raised number.** The first cut wrote the decision inline as a conditional
expression in `run_workflow`. That turned
`test_step10_p56_c2_confirmations_reachability.py::test_the_workflow_delta_stayed_sibling_shaped`
RED (§12.1's frozen 132 branch-ish nodes). Per CLAUDE.md's
responsibility-oriented decomposition rule the answer is to establish the
boundary first, so the decision moved to `resolve_tuner_health_config_source`
and `run_workflow` gained a CALL. **The tripwire is back at exactly 132 — the
orchestrator's shape is unchanged** — and the decision is now independently
testable, which the inline form was not.

**Bounded test repair (not a production defect).**
`test_health_feedback_wiring.py::test_workflow_lock_call_passes_policy_explicitly`
regex-matched `_run_invariants, _ = build_run_invariants\(`. C1 binds the
second element (the effective-config path was previously discarded), so the
regex found nothing and the test raised `AttributeError` on `None.group`. The
test's subject is the three POLICY KWARGS; the throwaway binding name was
over-specified. The regex now accepts any binding name and the test asserts
the call site was found at all, so it fails loudly instead of by attribute
error. No assertion was weakened.

**PROCESS INCIDENT — a `git checkout --` restore wiped an UNCOMMITTED fix.**
The two C1 mutation proofs below were planted and reverted with
`git checkout -- <file>` while the C1 production edits were still
uncommitted, so the revert restored those files to the C0 commit and silently
deleted both fixes. The tell was the post-restore baseline: **16 failed**
where 13 had passed. This is the exact hazard the mutation-hygiene rule names
("mutation proofs lie via … git-checkout restores"); the mutation RESULTS are
still valid (each planted defect turned the intended tests RED), but the
restore was not. Both edits were re-applied verbatim and the baseline
re-confirmed green (122 tests). **Rule applied for the rest of this PR: never
plant a mutation against an uncommitted production change — commit the
semantic checkpoint first, or revert by re-writing the planted hunk rather
than by checking the file out.**

Mutation evidence, recorded:

| # | mutation | expected | observed |
|---|---|---|---|
| C1-1 | `resolve_tuner_health_config_source` always returns `operator_config` (the hand-off severed) | the composed hand-off tests RED | **6 RED** — handed-config, task-roster, re-materialization, two truth-table rows, and the boundary test; 13 passed |
| C1-2 | re-inline the un-composed dataset for every run (F-12-1 restored) | every composed topology row RED | **15 RED** — both parametrized topology rows, the two-task anti-vacuity row and both W7 value-agreement rows among them; 4 passed |

### 8.5 C2 findings

**F-12a-C2-1 — re-keying the discriminator retroactively changed what
"composed" MEANS for tests, and one guard silently flipped branch.**

```text
Previous assumption:
  a test that wraps a tuner run in `bind_run_task_composition` is exercising
  the COMPOSED path. That was true while W4 read `active_task_data_path()`.

Audit evidence:
  after C2 the tuner decides from `agent_input.task_composition_ref`. C0's
  guard (e) bound the ContextVars but passed no projection, so its "composed"
  capture quietly became a LEGACY run — it printed "Reference scores loaded"
  where a composed run prints the named absence. The tell was indirect and
  ugly: the C0 legacy prompt-byte baseline began failing ONLY when run after
  guard (e), because that run had loaded TIDMAD's reference tables and the
  next capture in the same process then rendered a reflector prompt
  9,677 -> 5,581 bytes (the whole per-file reference table missing).

Corrected understanding:
  the projection is now the ONLY thing that makes a tuner run composed. Every
  test that means "composed tuner run" must pass it. Binding alone is no
  longer sufficient — which is the point of the change, and is exactly why
  `test_the_guard_follows_the_FIELD_even_with_the_contextvars_unbound` is a
  permanent test.

Implementation consequence:
  guard (e) now passes `build_task_composition_ref(composition)`.

Validation consequence:
  the order dependency is gone (114 tests green in the combined order), and
  the C0 module gained the standard `_isolated_run_scope` fixture it should
  have had from the start.
```

Two diagnostic dead ends are recorded because they cost real time and both
looked right: the health-gates process cache (`_CACHED_GATES`) and the health
plugin run-scope were each suspected first, and each was measured and
EXCLUDED — the roster after the C0 module is byte-identical to a clean
process. The cache reset added to the capture helper is kept anyway: a
prompt-BYTE baseline that depends on process history is order-lucky, not
deterministic.

**F-12a-C2-2 — a substring census would have called the fix a violation.**
The acceptance criterion is "zero `active_task_data_path()` calls in the tuner
package". The tuner keeps a COMMENT explaining what the guard used to read and
why it moved. A text scan cannot tell an explanatory comment from a live read,
so the census is AST-based (name loads, attribute access, imports). This is the
F-P2b-4 hygiene rule applied at creation time rather than discovered later.

**F-12a-C2-3 — the Step-09.5a envelope oracle caught the additive field, and
that is the guard working.** `tests/unit/workflows/test_step09_5a_c0_oracle.py`
reported exactly one difference:

```text
.node_calls.tuner.run_inputs[0].task_composition_ref: ADDED (None)
```

Handled by that module's established convention — a DECLARED delta in its
docstring plus a **surgical** one-line golden edit, joining the P2b-C2, P3-C1,
P3-C3, Step-11-C3 and Step-11-C8 entries. The first attempt re-serialized the
whole golden (`json.dumps(indent=1, sort_keys=True)`), which reported
`1430 insertions / 1429 deletions` — a wholesale reformat, precisely the
"nothing else moves under cover of a re-baseline" hazard the module warns
about. Reverted and redone as a textual single-line insertion:
**1 insertion, 0 deletions.**

Verified before touching the golden that the field reaches NO persisted
artifact: three production read sites, all in the tuner's main module;
`records.py` never mentions it; the persisted dump is `agent_output.model_dump()`
(the OUTPUT schema), which is untouched.

### 8.6 C4 findings

**F-12a-C4-1 — the omission default is kept, and the reason is a sibling
subsystem's pinned contract, not convenience.** The design left this to
evidence. The corpus says the default is unused (0 of 109 generated plugins
omit the declaration; the implementor template always emits it), which points
toward refusal. The VALIDATOR says otherwise and outranks it: its matching
`_DEFAULT_OUTPUT_TYPE` is a legacy-read path deliberately protected by a
reachability test that describes itself as "the only thing standing between
`_DEFAULT_OUTPUT_TYPE` and silent removal". Making the loader stricter than
the validator would rebuild the very loader/validator divergence #234 is
about — in the opposite direction. Recorded either way, as required.

**F-12a-C4-2 — three Step-03 A3 tests were UPGRADED, and the module's own
baseline amended in the same commit.** `test_step03_a3_a8_plugin_compatibility.py`
exists to pin the load-time tier's LENIENCY so it cannot change by accident;
#234 is the decision to change it on purpose. Deleting the tests would have
thrown away the failure class they own, so each was upgraded by INTENT:

| test | disposition |
|---|---|
| `test_invalid_declaration_warns_and_defaults_to_classifier` | **UPGRADED** → `..._now_REFUSES`. Same failure class, reversed expectation; the trace requirement is stronger (named reason AND no load) |
| `test_each_declared_value_is_carried_through_verbatim[hybrid]` | **NARROWED** to the plugin-legal pair. Its stated concern — "the hybrid arm must not be dropped" — transfers to `TestHybridStaysLoadBearingForBuiltins`, which pins the builtin table, `get_output_type` AND the real consumer branch |
| `test_a_bad_declaration_defaults_while_a_bad_lookup_raises` | **UPGRADED** → `test_an_OMITTED_declaration_defaults_while_a_bad_lookup_raises`. Its job (the two tiers must not be accidentally harmonised) is unchanged; the divergence MOVED, so the demonstration moved with it |

The module docstring now carries the amendment table, so a future reader
finds the reversal where A3's original claim lives rather than only in this
ledger.

**F-12a-C4-3 — the agreement census targets the DECLARATION, not the
literal.** A first cut asserted the validator contains no
`("classifier", "regressor")` text and went RED on an unrelated loop that
renders the two prompt SHAPE tokens. That loop is coupled to
`{CLASSIFIER_SHAPE}` / `{REGRESSOR_SHAPE}`, not to this vocabulary, and
binding it to the set would create a silent mismatch the day the set grew. The
census is now AST-based on the ASSIGNMENT to `_LEGAL_OUTPUT_TYPES`, so
re-declaring it as a tuple literal is RED even when the value is still equal.

### 8.7 C5 findings

**F-12a-C5-1 — the rule was self-contradictory in its own docstring.**
`_is_loss_shaped` explained that `mse` — a loss FORMULA — "is a legitimate
evaluation-metric identity for a task whose deliverable IS scored by mean
squared error", and then refused anything spelled with a `loss` token. So the
same quantity was legal as `surprisal` and illegal as `log_loss`. That is a
lint on vocabulary, not a boundary, and it is why the operator ruled the
identity OPAQUE.

**F-12a-C5-2 — three consumers, and leaving any one would have been worse
than leaving all three.** The frozen §2.2 names `MetricSpec.id` only; source
also applies the check to `MetricResult.metric_id` and
`NotScoreableResult.metric_id`. A `log_loss` metric could then have been
DECLARED and never RECORDED — declarable but unusable, which is a more
confusing state than the original refusal.

**F-12a-C5-3 — the sibling check was incidental and is now explicit.**
`_reject_loss_shaped` did two things: identifier hygiene (non-empty, no
surrounding whitespace) and the lexical judgement. Removing the second left
the first as the function's whole purpose, so it was renamed
`_validate_metric_identifier` and given its own parametrized test across all
three types — it had none before, having only ever been exercised in passing.
C5's §6 obligation ("must not weaken any sibling check") is discharged by
strengthening it.

**F-12a-C5-4 — the Pets pack's INVERTED pin fired exactly as written, and
took the docs with it.** `test_log_loss_is_refused_by_the_metric_schema_today_d16_pin`
said: *"the day D16 is narrowed and `log_loss` becomes declarable, this test
FAILS — forcing STATUS/README (which say 'blocked by D16') to change."* It
did. `examples/oxford_iiit_pet/STATUS.md` and `README.md` are corrected in
this commit. The pack still does not SHIP a `log_loss` declaration — what
Pets is evaluated on is a scientific choice, not a side effect of a schema
change — and the test asserts that too. This is what a well-written inverted
guard buys, and it is the model the C0 guards follow.

**F-12a-C5-5 — two rows left the C0 structural table, in the commit that
moved them.** `_is_loss_shaped` (4, 1, 14, 1) was DELETED;
`_reject_loss_shaped` (6, 3, 14, 2) became `_validate_metric_identifier`
(5, 2, 41, 2). The successor is strictly smaller in responsibility — branch
3 → 2, executable statements 4 → 3 — and grew in LOC only because it now
documents what enforces the boundary instead. Re-anchoring the row would have
made C8's comparison for it vacuous, so the numbers are recorded here and the
row leaves the growth budget it can no longer be measured against. This is
the disposition C0's own table anticipated for a deliberately retired
function.

### 8.8 C6 findings

**F-12a-C6-1 — `core` DOES still import from `workflows`, and that edge is
deliberate.** The first census banned every `core -> workflows` import and
immediately caught `core/sandbox_executor.py` importing
`workflows.task_composition.active_task_manifest_path` and
`workflows.task_config.run_bound_model_io_contract`. Both are PUBLIC
run-scoped accessors, both function-local, both added by Step 11 so the spawn
surface can ask what the run is bound to. That is a design edge Step 11 chose,
not a defect for this commit to relitigate — and a census asserting otherwise
would have been asserting a rule the repository does not hold.

The rule is therefore about PRIVATE symbols, which is what 09.5 Q2 = B named
and what actually caused harm: `core.resume` importing
`workflows.model_exploration._add_plugin_to_registries` inverted the layering
AND made `workflows -> core.resume` a cycle. The public edge is pinned by its
own test so a future reader sees it was measured, not missed. **Recorded as
observed debt, owned by nobody in this PR.**

**F-12a-C6-2 — the cycle had cost two workarounds, and both are now gone.**
The consolidation's visible benefit is one authority; its structural benefit
is larger. `model_exploration` carried a `TYPE_CHECKING`-only `RestoredState`
with a QUOTED annotation, and a `union_key_findings` import buried inside
`run_workflow` — a cross-layer dependency hidden in the middle of an
already-1,500-line function. Both existed only to break the cycle. Both are
ordinary top-level imports now, and the census asserts the AST shapes rather
than the comments, because a stale comment claiming the cycle exists would
read as licence to reintroduce them. A third local import
(`register_model_in_memory` at the post-validation site) collapsed into the
module-level one in passing.

**F-12a-C6-3 — warn-and-continue is only preserved if BOTH halves are.**
C6's edge case says `restore_prior_state` must not become a raise. Asserting
that on the caller alone would miss the other half: if the new callee RAISED
where the old one returned `None`, the caller's `if registered is None:`
branch would simply never run and the warning would be replaced by a
traceback. Both are pinned.

### 8.9 C7 audit — the D-12a-5 classification table (recorded BEFORE any block moves)

The governing rule, in the operator's wording: *removing TIDMAD science is NOT
sufficient.* Every removed hardcoded block is classified as **(1)** optional
TIDMAD-only advice, which may disappear on a composed run, or **(2)** required
task semantics, which must be REPLACED from a task-owned authority — never
invented framework prose, and never a blanket "not available".

| # | block | what it actually is | class | composed-path disposition |
|---|---|---|---|---|
| **P1** | planner goal line, `` the `denoising_score` metric `` | **NOT a metric name — the FROZEN RECORD KEY** (see F-12a-C7-1) | **(2)** | the literal STAYS; the NOUN is corrected on the composed branch only |
| **P2** | planner `### AVAILABLE MODELS:` — five builtin descriptions | a roster a composed task may not have | **(2)** | replaced by the run's OWN model description, from the description source |
| **P3** | planner `### PER-FILE PERFORMANCE TABLE:` protocol prose (~28 lines) | TIDMAD reference science: raw_baseline / ground_truth / global `s_max` / log-space | **(1)** | renders nothing — and W4 already sets `reference_scores = None`, so the table it explains is ALREADY absent; today only the prose survives, explaining a table that is not there |
| **R1** | reflector `### CRITICAL — HOW TO JUDGE THE DENOISING SCORE:` + "actual Denoising Score" | the JUDGEMENT protocol (compare to baseline/best, never call a negative score a failure) is task-generic; only its NAMING is TIDMAD's | **(2)** | protocol kept, wording de-TIDMAD-ised on the composed branch; the direction words are already parameterized |
| **R2** | reflector `` `denoising_score` is the golden metric `` | field explanation, task-invariant | **KEEP** | unchanged on both branches |
| **Pr1** | proposer role: "specialising in deep learning for **signal denoising**" | task identity | **(2)** | replaced from `proposal_blocks` / the task description |
| **Pr2** | proposer `[B, 256, T]`, "256 denoising bins", "the denoised waveform directly" | the FORWARD CONTRACT | **(2)** | replaced from the run's `ModelIOContract` / `forward_contract`, which every composed task already declares |
| **Pr3** | proposer score-table reading protocol | TIDMAD reference science | **(1)** | renders nothing |
| **I1** | implementor roles: "for signal denoising", "for **loss functions for signal denoising**" | task identity | **(2)** | replaced from the task description |
| **I2** | implementor `_LEGACY_OUTPUT_CONTRACT_COMMENTS` | the forward contract, as generated-code comments | **(2)** | replaced from the run's `ModelIOContract` |

**F-12a-C7-1 — F-12-5 is a NOUN defect, not a wrong-value defect, and the
frozen design already anticipated the distinction.**

```text
Previous framing (parent §4.2 F-12-5):
  "the planner prompt hardcodes `denoising_score` BESIDE the parameterized
   {METRIC_IDENTITY_LINE} — a composed run's goal line names the wrong metric
   while the identity line names the right one."

Audit evidence:
  `denoising_score` is a FROZEN RECORD KEY, written unconditionally by
  `records.py` (:230, :374, :681, :1193 — no task branch anywhere) and
  explicitly documented as such by the renderer that sits next to it:
  `render_metric_identity_line`'s docstring says the identity was "added
  BESIDE the record field name rather than replacing it: `denoising_score` is
  the key the LLM actually reads out of the history JSON, and renaming it is
  D1's job, not 07b's (Q-07b-3)". The prompts say the same thing in three
  other places, correctly ("The `denoising_score` FIELD carries the
  {METRIC_IDENTITY_LINE}").

Corrected understanding:
  on a composed Pets run the history JSON key IS `denoising_score`. The
  literal is therefore CORRECT and load-bearing — replacing it with the
  composed metric id would instruct the model to read a key that does not
  exist, which is strictly worse than the defect being fixed. What is wrong
  on a composed run is the NOUN: the line calls that field "the metric",
  while the metric identity is what the parameterized clause beside it
  already carries.

Implementation consequence:
  the byte-level rewording option that lands is (b) of two:
    (a) reword for BOTH branches   -> legacy prompt bytes MOVE; every pin in
                                      the C0 fixture re-baselined
    (b) reword on the COMPOSED branch only -> legacy bytes byte-identical
  (b) is chosen, and it is not merely the cheaper one: "the `denoising_score`
  metric" is TRUE for a legacy TIDMAD run and false only when composed, so
  gating it is the accurate statement on both paths rather than a compromise.
  D-12a-5 explicitly delegated this choice to this audit and required the
  pinned tests' disposition with it — the C0 legacy fixtures stay GREEN
  untouched, which is that disposition.

Validation consequence:
  Gate-1's probes cover the composed wording; the legacy sha fixtures are
  unchanged evidence rather than re-baselined evidence.
```

**F-12a-C7-2 — P3 is already half-dead, which changes its class.** W4 (Step 10
P5+P6) sets `reference_scores = None` for every composed run, so
`{SCORE_COMPARISON_TABLE}` renders its fallback and the per-file table is
ALREADY absent. What survives today is ~28 lines of prose explaining a table
that is not there — `raw_baseline`, `ground_truth`, a global `s_max`,
`Impact_Score` ranking — presented to a task that has none of it. That makes
it unambiguously class (1): there is no task semantics to replace, because the
evidence it describes was already withheld.

### 8.10 C7 findings

**F-12a-C7-3 — P2's required semantics was ALREADY supplied, which simplified
the replacement.** The classification put the built-in roster at class (2):
the planner must know what it is tuning. The audit of the render path then
found `LLMBridge.plan` already emits the run's OWN architecture description
into the user message as `[MODEL ARCHITECTURE DESCRIPTION]`, on both paths and
independently of that block. So the required fact is answered elsewhere in the
same prompt, and what the five built-in lines add to a composed run is a menu
of architectures it is not using. The composed rendering therefore POINTS at
that authority instead of restating it — restating would have created a second
place the same fact is rendered, which is the shape this PR removes everywhere
else.

**F-12a-C7-4 — the design's block inventory was incomplete, and the TOKEN
census is what found the rest.**

```text
Previous assumption:
  the §8.9 table (built from the frozen design's own inventory: planner
  :66, :69-73, :239-266; reflector :280-319) enumerated every block.

Audit evidence:
  the acceptance test — "a composed prompt contains none of these TIDMAD
  tokens" — went RED on `Impact_Score` in THREE planner calls and on
  `ground_truth` + `Impact_Score` in TWO reflector calls, from blocks the
  inventory did not list: the planner's `"target"` sampling justification
  (which argues from the `Impact_Score` column) and its sampling tradeoff
  advice, plus the reflector's whole `### PER-FILE COMPARISON (Impact-Aware):`
  section.

Corrected understanding:
  a line-range inventory of "the TIDMAD blocks" is a starting point, not a
  closure criterion. Seven blocks are gated, not four.

Implementation consequence:
  three more tokens, all class (1) — they argue from a per-file table W4
  already withholds from composed runs. The planner's `target` STRATEGY
  itself (that `target_files` exists and concentrates data) is framework
  machinery and is deliberately NOT gated; only the TIDMAD evidence it cites
  is.

Validation consequence:
  the banned-token census over the RENDERED composed prompt is the closure
  criterion, and it is what the acceptance criterion should have been read as
  all along. It is kept as the permanent owner.
```

**F-12a-C7-5 — the composed subject is TIDMAD, deliberately, and that is
stricter.** The end-to-end composed capture uses the composed TIDMAD manifest.
The gating keys on composition PRESENCE (C-P56-1), so a composed TIDMAD run
must lose TIDMAD's science too — a gate that keyed on task identity would
leave every banned token in place and the census would go green for the wrong
reason. It is also the only composed fixture that COMPLETES rounds under the
Step-00 canned plans (their `segmentation_size` is valid only for a
256-sample profile, so a composed Pets drive fails validation before reaching
the reflector). That fixture limit is stated in the test rather than
parametrized away, and a Pets planner-only row covers the second topology as
far as it runs.

**F-12a-C7-6 — the template shas moved TWICE and the rendered manifest never
did.** C0's parity module set the condition in advance: *"if the constant
itself had to change, prove the legacy rendered manifest is still identical
and re-freeze here."* Seven blocks became named substitution tokens whose
legacy bytes moved VERBATIM into the render authority, so
`PLANNER_PROMPT` / `REFLECTOR_PROMPT` were re-frozen — while
`LEGACY_TUNER_PROMPT_MANIFEST_SHA` stayed at `6e8de64b…` throughout. The
constants moved; what an un-composed run actually sends did not. That is only
true because the gating is a rendered STRING in the render authority and the
`llm_bridge` assembly sites still just substitute tokens — pinned by
`TestTheAssemblySiteNeverLearnsAboutComposition`.

### 8.11 F-12a-C7-7 — the registration-order failure is PRE-EXISTING (operator-directed forensic)

**Classification: CASE A — baseline fails in the same way. PR-12a did not
introduce it.**

**§1 — the exact failure shape.**

```text
CI command (.github/workflows/ci.yml:94,116), full-suite branch:
    pytest tests/unit/ -m "not real_run" -q          # ONE process

selector verdict for PR-12a's 43 changed paths:
    FULL SUITE  ("agent/schemas/: declared hub — selecting would be a lie")

minimal reproducer (both checkouts, identical command):
    pytest tests/unit/agent/tune_ml_hyperparam_agent \
           tests/unit/workflows/test_step10_p56_c5_wiring_closures.py \
           -m "not real_run" -q

failure shape, every occurrence:
    TaskCompositionError: task_data_path names module
    'execute_tools.tidmad_data_path', which could not be imported:
    TaskDataPathRegistrationError: Task data path 'tidmad' is already
    registered. Currently registered: ['davis_future_prediction',
    'oxford_iiit_pet', 'spectro_segmentation_v0', 'tidmad'].
```

It depends on EXECUTION order, not collection: every affected file passes in
isolation and passes when `tests/unit/workflows` is collected FIRST. The
poisoning half is `tests/unit/agent/tune_ml_hyperparam_agent`, and it is
CUMULATIVE — no single file in it reproduces the effect (the two files that
import a child, the only composition-touching file, and the full
pseudo-iteration choreography file were each tested individually and are all
clean against the probe; splitting the directory in half, only the 40-file
second half reproduces).

**§2 — baseline, in an ISOLATED detached worktree.** The active PR-12a
checkout was never moved and C7-2 was left uncommitted, per the ruling. A
detached worktree at `e4cd5c18` was equalized for machine-local state before
running — `tidmad_data_config.yaml`, `agent_generated/{models,losses}` and the
capability index were copied in, because the step-09.5a capture harness
records exactly this trap ("equalising the code under test is not enough; the
environment the code reads must be equal too"), and import resolution was
verified to come from the worktree (`/tmp/pr12a_baseline/...`) rather than the
active checkout.

| | PR-12a branch | baseline `e4cd5c18` |
|---|---|---|
| `wiring_closures.py` failures | **9** | **9 — the identical set** |
| W2 ×3, W3 ×2, W4, W5, W7 ×2 | yes | yes |
| tuner-suite failures | 2 (the WF goldens — this PR's own declared delta, since fixed) | 0 |

**Verdict: pre-existing order fragility, present on unmodified master.**

**§3 — not applicable.** No PR-12a-owned cause exists to localize, so nothing
was changed, and in particular PR-12c's transactional run-scoped registration
overlay was NOT pulled forward. The mechanism (a process-global
`_REGISTRY` in `execute_tools/task_data_path.py` that refuses duplicate
registration, against a module that can be executed twice under some
accumulated test state) is squarely F-12-3 / §8 territory — **PR-12c's**.

**§4 — CI reachability.** "Pre-existing" is not by itself a licence, so the
CI-EQUIVALENT command was run on the branch: `pytest tests/unit/ -m "not
real_run" -q`, the exact full-suite invocation the selector resolves to.
Result recorded in §8.12.

**Recorded as carried debt, not fixed here** (the ruling's §4: do not
opportunistically fix unrelated global registry/test-order debt merely
because PR-12a exposed it). Owner: **PR-12c**, whose §8 run-scoped
registration lifecycle is the mechanism that makes duplicate registration a
non-question. Until then the standing constraint is that
`tests/unit/workflows` composition suites must not run after the tuner suite
in a single process — which the full-suite ordering satisfies (§8.12).

### 8.12 F-12a-C7-8 — the pre-existing fragility is NOT reachable under the formal CI command

The ruling's §4 is explicit that "pre-existing bug exists" does not by itself
license a CI failure, so the CI-EQUIVALENT command was run on the branch.

```text
selector verdict for PR-12a's 43 changed paths   -> FULL SUITE
                (agent/schemas/ is a declared hub: "selecting would be a lie")

pytest tests/unit/ -m "not real_run" -q          # the exact CI invocation
    -> 12,022 passed · 1 failed · 2 skipped · 18m57s

wiring_closures failures under the full suite    -> ZERO
```

**The ~45-failure cluster does not occur under the full suite.** It requires
the restricted two-directory command that puts the tuner suite immediately
before the composition suites; the full ordering interposes enough other work
that the poisoning condition never arises. So PR-12a changes nothing about
reachability, and the pre-existing fragility stays where §8.11 put it —
recorded, owned by PR-12c.

**The single failure is the documented dirty-tree guard, working as designed:**

```text
test_pr3_l2p_preflight.py::test_preflight_all_invariants
  rev-3 preflight check failed: no_production_file_modified
  (['agent/llm_bridge.py', 'agent/prompt_templates/tuner/rendering.py',
    'agent/prompts.py',
    'nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py'])
```

Those are exactly C7-2's four uncommitted production files. CLAUDE.md names
this case verbatim — *"Run the full suite on a work-in-progress tree and it
reports a failure naming the files you are editing. That is the guard
working"* — and the rule is to commit the semantic checkpoint and re-run,
never to relax the guard. Re-run on the clean tree after the C7-2 commit:
recorded in §5-C7's verification block.

**CLOSED as CASE A by operator ruling, 2026-08-22.** Pre-existing global
process-registry / test-order fragility, NOT introduced by PR-12a and NOT made
CI-reachable by it. PR-12a does **not** fix it: doing so would mean pulling
PR-12c's transactional / run-scoped registration overlay into 12a, which the
ruling names as a material deviation. It is retained as explicit **PR-12c (now
possibly PR-12bc) lifecycle debt**, and the reproducer is recorded here so that
PR can use it as a REGRESSION FALSIFIER rather than rediscovering it:

```text
baseline SHA (pre-PR-12a, master)  e4cd5c18
reproducer (fails at the BASELINE, in an isolated detached worktree):

    git worktree add --detach <tmp> e4cd5c18
    cd <tmp> && <repo>/.venv/bin/python -m pytest \
        tests/unit/nodes/ml_hyperparameter_tune_agent tests/unit/workflows -q

    -> ~45 failures in the composition suites' wiring_closures

mechanism : the tuner suite leaves process-global registration state
            (`execute_tools/task_data_path.py::_REGISTRY` refuses duplicate
            registration) that the composition suites then trip over
does NOT   : occur under `pytest tests/unit/ -m "not real_run" -q` (the CI
occur      command) — the full ordering interposes enough work that the
            poisoning condition never arises (§8.12)
falsifier  : after the lifecycle overlay lands, the command above must PASS
            at that head
```

### 8.13 C7-3 findings (D-12a-6, ProposalTaskBlocks)

**F-12a-C7-9 — the relocation is proved BYTE-EXACT, which is stronger than
C7-2's evidence and cheaper.** For the tuner, the best available proof was
"the rendered manifest did not move". For the proposer there is a stricter
one: substituting TIDMAD's declared blocks back into the tokenized templates
reproduces the PRE-C7 sha256 exactly.

```text
PROPOSAL_REASONING_PROMPT   substituted -> 7c69ce7bae2509b8…  == C0 original
proposing_stage.md          substituted -> 8d52e15675dcd6f5…  == C0 original
```

`TestTheRelocationIsBYTE_EXACT` hardcodes those ORIGINAL digests rather than
recomputing them, so it compares against the recorded past and not against
itself. Anyone who later "tidies" a value in
`configs/task_proposal/tidmad.yaml` turns it RED and is told which surface.
That is the whole safety argument for calling D-12a-6 a relocation rather
than a rewrite.

**F-12a-C7-10 — Pr1 renders a CLAUSE, not a sentence.** The role line was
`"You are a senior ML architect specialising in deep learning for signal
denoising."` Tokenizing the whole sentence would have forced every task to
supply one or forced a named absence into the first line of the prompt.
Tokenizing the CLAUSE (`{ARCHITECT_ROLE}` → `" specialising in …"`) means an
undeclared task reads `"You are a senior ML architect."` — grammatical, honest,
and zero added bytes, which is what D-12a-6 requires.

**F-12a-C7-11 — fingerprint participation is additive-WHEN-DECLARED, and the
undeclared identity is unchanged.** Following the secondaries (P2b) and
deliverable-naming (Step-11 C6) precedent exactly. Verified against the value
Step-11's Gate 2 and this PR's C2 lock evidence both recorded: an undeclared
TIDMAD manifest still fingerprints
`d6628a93fcb3578ca32812f39246f2b51abeecbd24d21df56856ea0ef9c56d3a`. An
unconditional key would have moved every existing composed run's identity and
failed its resume for a reason with no scientific content. The test suite
also pins that editing the PROSE moves it — a fingerprint keyed on the
section's PRESENCE would pass the "declaring moves it" row and still let an
edited declaration resume against a stale lock.

**F-12a-C7-12 — the §12.1 tripwire fired a third time; extraction again.**
The composed/un-composed fork was written inline as the ternary 09b uses, and
`run_workflow` went to 133. Extracted to `resolve_run_proposal_blocks`; back
at 132. Three extractions now (C1, C7-1, C7-3) — the tripwire is doing exactly
what it was written to do, and each extraction left a decision independently
testable that had only been reachable through a full workflow drive.

### 8.14 F-12a-C7-13 — C7-4 (implementor I1/I2) hits a SCOPE BOUNDARY

**Established by bounded forensic work, not asserted. One half of C7-4 turned
out to be already closed; the other half cannot be closed inside the ratified
contracts.**

**I2 is ALREADY CLOSED for any run with a ModelIOContract** — an
A-12a-1-shaped finding. Step 04a's `_render_output_contract`
(`ml_model_implementor.py:337-372`) renders BOTH generated-code comments from
the declaration through the same `declared_output_tensor` rule the validator
probes with; `_LEGACY_OUTPUT_CONTRACT_COMMENTS` is only the
no-contract fallback (§15.1 row 1). A composed run always has a contract, so
the composed path already emits its own shapes. **What remains is one residue**:
`_CONTINUOUS_OUTPUT_PHRASE = "continuous waveform regression"` (`:332`), used
at `:372` ON the contract path — "waveform" is TIDMAD's word for a regressor's
output.

**I1 (both role clauses) and I2's residue need a task-owned VALUE the
implementor's input does not carry.** Three candidate sources were audited:

| candidate | verdict |
|---|---|
| `inp.task_description` (D-12a-5 names it as a legitimate authority, and the node already receives it) | works for the COMPOSED path — but on a LEGACY run it renders TIDMAD's declared description (`"full-spectrum 1-D time-series denoising of SQUID dark-matter detector data"`) where the literal says `"deep learning for signal denoising"`. **That moves LEGACY implementor prompt bytes**, which C7's own acceptance criterion forbids. Implemented, measured, and REVERTED |
| `ModelIOContract` | carries axis roles and `output_semantic()`, but NO free-text output description. Deriving a phrase from it means INVENTING framework prose, which D-12a-5 explicitly forbids |
| gate on composition presence, as C7-2 did for the tuner | the tuner could do this because D-12a-1 put `task_composition_ref` on ITS input. `ImplementorInput` has no composition signal, and D-12a-1 deliberately moved AWAY from ambient reads |

So closing I1 requires an additive, default-`None`, task-owned blocks field on
`ImplementorInput` — the SAME shape ratified twice already
(`HyperparamTuningInput.task_composition_ref` by D-12a-1,
`ProposalInput.proposal_blocks` by D-12a-6) — plus its config and manifest
section.

**Why this is a boundary and not ordinary discretion.** The two readings
genuinely differ:

* the PARENT (§12-12a-viii) says *"proposer + implementor task-science moves
  behind caller-supplied task blocks … manifest gains the corresponding
  optional **section(s)**"* — plural, and naming the implementor. That reads
  as authorising it;
* the CHILD's ratification (§0.1 item 4) enumerates **D-12a-6 =
  `ProposalTaskBlocks` + `proposal_blocks:`** and nothing for the implementor,
  and the frozen invariants say *"Any additional schema/protocol/persisted-state
  expansion beyond the explicitly ratified additive contracts above is a
  MATERIAL deviation, not ordinary implementation discretion"* — the R-11-14
  lesson, designed in.

Both readings are defensible, the difference is a new schema family, and the
operator's standing instruction is *"Do not silently expand scope."* So it is
raised rather than taken.

**Status: RESOLVED — see §8.15.** The boundary above was raised, and the
operator ratified **Option A** as a bounded contract correction inside PR-12a.

### 8.15 D-12a-9 — `ImplementorTaskBlocks` (operator-ratified contract correction)

**Operator ruling, 2026-08-22: OPTION A IS AUTHORIZED.** The stop in §8.14 was
judged correct; the additive contract is granted as a **BOUNDED CONTRACT
CORRECTION inside PR-12a**, not deferred. C7-4 remains IN SCOPE, and the
surviving implementor role clauses must NOT be carried as post-12a debt.

This is the third instance of the same ratified shape (D-12a-1
`task_composition_ref`, D-12a-6 `ProposalTaskBlocks`), and it is recorded here
as a **DEVIATION FROM THE FROZEN §0.1 RATIFICATION**, ratified in-flight — not
as ordinary implementation discretion. The R-11-14 lesson holds: a schema
expansion is an operator decision even when its shape is obvious.

**What landed**

| artefact | file |
|---|---|
| `ImplementorTaskBlocks` — `science_domain`, `continuous_output_phrase`; frozen, `extra="forbid"`, both optional | `agent/schemas/implementor.py` |
| `ImplementorInput.implementor_blocks` — additive, default `None`, a CARRIER not a second authority | `agent/schemas/implementor.py` |
| bounded Regime-A adapter; its single task-identity occurrence is a default-path CONSTANT | `agent/prompt_templates/implementor/task_blocks.py` |
| TIDMAD's two values, moved VERBATIM | `configs/task_implementor/tidmad.yaml` |
| optional manifest section `implementor_blocks:`, composed by the same `_compose_*` mechanics and participating in `semantic_fingerprint` | `workflows/task_composition.py` |
| run-scoped resolution at the composition root | `workflows/model_exploration.py::resolve_run_implementor_blocks` |
| `render_engineer_role` / `render_continuous_output_phrase` — framework framing, task prose | `nodes/ml_model_implementor/ml_model_implementor.py` |
| shared FAIL-CLOSED loading mechanics for all three adapters; **schemas deliberately NOT shared** | `agent/prompt_templates/_task_blocks_loader.py` |

**The god-object warning was heeded.** The ruling permitted a generic helper
"only where it reduces duplication without collapsing schemas into a god 'task
blocks' object". So `_task_blocks_loader.py` shares the MECHANICS (resolve,
read, insist on a mapping, validate, fail closed) and never inspects the model;
each family keeps its own schema because each renders in a different place for a
different reason. 09b's interpretation adapter is deliberately left untouched —
rewriting frozen Step-09b evidence for a few saved lines buys nothing.

**Absent blocks do not fall back.** `render_engineer_role(None)` returns `""`,
so the line reads "You are a senior PyTorch engineer." — grammatical, and
carrying no science the task did not declare. No invented framework prose stands
in for missing scientific meaning. The continuous phrase falls back to the name
of the DECLARED form (`f"continuous {emitted.render_shape()} output"`), which is
a contract fact, not science — and is exactly how the classifier half has always
worked (it derives from the declared class cardinality).

**No ambient discriminator.** Nothing here asks whether the run is composed. The
composition root resolves the value; the node renders whatever it is handed.
That is D-12a-1's carrier rule applied unchanged.

**F-12a-C7-14 — one PINNED residue.** `_LEGACY_OUTPUT_CONTRACT_COMMENTS`'s
regressor entry still reads `"continuous waveform regression"`. It is reachable
ONLY by a task that declines Step 03's `model_io` declaration; the shipped
TIDMAD config declares one, so the production path renders from the
declaration. Routing it through the task-owned phrase would mean either moving
the legacy bytes that table exists to preserve, or branching on composition
presence. It is PINNED BY COUNT (`== 1`) so a second occurrence — e.g. someone
restoring the unconditional phrase in the renderer — turns the census RED.

**F-12a-C7-15 — the standalone node CLI.** `ml_model_implementor.main()`
constructs its own `ImplementorInput` and never passes through `run_workflow`,
so it resolves the bounded adapter directly. Un-composed by construction: there
is no manifest to read. The proposal node's `main()` was audited for the same
gap and has none — it constructs no `ProposalInput`.

**Evidence — the ruling's eight required validations**, all in
`tests/unit/workflows/test_step12_pr12a_c7_implementor_blocks.py` (25 tests):

| # | requirement | evidence |
|---|---|---|
| 1 | legacy rendered-prompt byte parity vs the pre-C7 digest | `TestLegacyRenderedPromptByteParity` — substituting TIDMAD's declared blocks reproduces the HARDCODED pre-C7 `5f32ce79…`; and the PB-5 prompt goldens are UNCHANGED (not regenerated) |
| 2 | composed + declared ⇒ science comes from the blocks | `TestComposedWithDeclaredBlocks`, through a real composed manifest |
| 3 | composed + absent ⇒ ZERO fallback to TIDMAD | `TestComposedWithoutBlocksNeverFallsBackToTidmad`, incl. a real DAVIS manifest declaring none |
| 4 | changing only the blocks moves the fingerprint | `TestFingerprintParticipation` — and an undeclared manifest fingerprints UNCHANGED at `d6628a93…` |
| 5 | malformed / unknown declaration fails closed | `TestFailClosed` — missing file, non-mapping section, unknown key, non-mapping file, plus `EXPLICIT_NONE` still a legal NAMED absence |
| 6 | mutation: restoring the unconditional phrase turns the ownership test RED | planted, `count == 1` asserted, caches cleared: **5 RED**, restore **25 green**. Kept as a PERMANENT count-pinned census rather than a one-off plant |
| 7 | no task-identity dispatch / central catalog row | `TestNoTaskDispatchWasIntroduced` — AST over the adapter's conditionals and over both renderers' executable bodies |
| 8 | structural | `TestStructuralOwnership` — the workflow calls the named resolver; `run_workflow` branch count UNCHANGED at 132 (§12.1 tripwire) |

**Deterministic C7 evidence re-run after C7-4** (the ruling's closing
condition), 2,210 passed / 0 failed: all guardrails, the implementor node, the
Step-04a ladder, all workflows, all protocols, the proposal node and all node
boundaries. Two DECLARED deltas, applied surgically and nothing else
regenerated:

* `PROMPT_SOURCE_SHA["implementor.IMPLEMENTOR_REASONING_PROMPT"]` re-frozen
  `5f32ce79…` → `f484a166…`, on the same condition C7-2/C7-3 met: the SOURCE
  constant moved, the RENDERED bytes did not;
* the Step-09.5a envelope oracle gained exactly one key
  (`.node_calls.implementor.run_inputs[0].implementor_blocks: ADDED`), inserted
  textually — **1 insertion, 0 deletions**.

**Test dispositions (UPGRADE, never weaken).** Four fixtures that model the
LEGACY un-composed caller now resolve the bounded adapter, exactly as the
composition root does for a run with no manifest: `tests/helpers/
step04a_fixtures.py::implementor_input`, `test_step00_prompt_goldens.py::
fixture_input`, and two direct `_render_output_contract` call sites. The
Step-04a parity property is unchanged and slightly STRONGER — it now proves the
DECLARED phrase reproduces the tabulated legacy bytes.

**R-11-10 applied:** `_CONTINUOUS_OUTPUT_PHRASE` had no remaining reader and was
DELETED, not left beside its replacement.

### 8.16 C8 findings

**F-12a-C8-1 — the shipped TIDMAD manifest DECLARES the two new sections, and
its identity moves.** This is the C8 decision most worth operator attention.

`configs/task_composition/tidmad.yaml` (and the P1 fixture it must stay
equivalent to, per W2) now carry `proposal_blocks:` and `implementor_blocks:`.
Without them a composed TIDMAD run would propose and implement with **no
science at all** — the frozen semantic "absent composed blocks must not fall
back to TIDMAD" working exactly as designed, against the one task that has
science to declare. Declaring them is what makes composed TIDMAD equivalent to
legacy TIDMAD, and it needs no special-casing: two ordinary refs, like every
other section.

The consequence is a genuine identity change:

```text
tidmad composition semantic_fingerprint
    d6628a93fcb3578ca32812f39246f2b51abeecbd24d21df56856ea0ef9c56d3a   (eeb073dc)
 -> 9125bf587fea5bae1493800e9b50bafbb63164ff72ec1bfe3b08520ae1e72aac   (this PR)
```

**A composed TIDMAD run started before this PR therefore FAILS ITS RESUME
CLOSED**, even though the rendered prompt bytes are identical. That is the
designed behaviour for a composition that gained two declared sources, and the
population is small: composed runs only became launchable in Step 10 P5+P6
(2026-08-21) and the Step-11 Gate 2.

Two Step-10 pins were updated with the reason recorded, never relaxed:

* `test_step10_p2b_c1_secondary_declaration.PRE_P2B_FINGERPRINTS["tidmad"]` —
  precisely the case that pin's own docstring names ("a shipped declaration
  legitimately changes a fingerprint and the literal is then updated with the
  reason recorded"). `fourth_task`, which declares neither section, is
  UNCHANGED, and that is what separates "a declaration was added" from "the
  machinery moved";
* `TestW2ShippedManifest::test_it_is_the_SAME_composition_the_p1_fixture_proved`
  passes again because the fixture gained the same two sections. A fixture
  quietly declaring less than the shipped manifest would make the shipped
  manifest's identity untestable.

The additive rule itself is proved against the recorded past on the two
fixtures that declare NEITHER section, measured at `eeb073dc` in a detached
worktree:

```text
davis  c59342f809073690b305448e3301d997aed209449ba11ee35bc860ca7805d3b7  UNCHANGED
pets   2b3b53837670592d36e072bdd49a37059cb2a3a63b7cda950f3a0b96bc4447e8  UNCHANGED
```

Both C7 modules' "undeclared fingerprints unchanged" tests were RE-POINTED at
these two. They used to read the TIDMAD fixture, which now declares both
sections — so they would have been asserting the opposite property against a
moved value: green for the wrong reason, the F-P2b-4 shape.

**F-12a-C8-2 — the F-12-6 census widening found no leak, which is the point.**
`sdsc_submission_scripts/run_one_iteration.py` and `core/resume.py` join the P1
singleton-import guard's surface. Both had ALREADY been migrated to
`resolve_dataset_profile` — resume by Step-11 C8 (F-11-5), the iteration runner
by this PR's C1 — so the widening records no new offender. It closes the gap
that let those migrations be undone silently: **the guard that would have
caught the original defect did not look at the two files where that defect
lived longest.** Mutation-proven on each file independently (planted
`TIDMAD` / `TIDMAD_PROFILE` import → RED; restored → 14 passed, both files
byte-restored).

**C8 doc sync.** Claims quoted against merged source, not memory:

| doc | claim | disposition |
|---|---|---|
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md` | showed `if active_task_data_path() is None:` as the reference-science guard | CORRECTED to `agent_input.task_composition_ref`, with D-12a-1's reason (a node should not read a ContextVar to learn what kind of run it was handed) |
| `docs/architecture.md` | "the metric types refuse loss-shaped identities" | CORRECTED — D16/C5 made `MetricSpec.id` OPAQUE; the boundary is enforced where the real distinction lives, and naming is validated for hygiene only |
| `configs/task_composition/tidmad.yaml` | — | the two new sections, with the reason inline |
| historical Step-06/09.5/10 design ledgers | mention `_is_loss_shaped`, `_add_plugin_to_registries` | LEFT AS RECORDED. They are dated records of their own moment; the doc-sync rule targets node/skill and operator-surface docs, and rewriting a frozen ledger to match later work destroys the evidence trail |

**F-12a-C8-3 — structural pre/post, the MANDATORY C8 comparison** against the
C0 table (`current_structure()` vs `STRUCTURAL_BASELINE`):

| function | branch | stmts | LOC | returns |
|---|---|---|---|---|
| `run_workflow` | 369 → 370 (+1) | 144 (=) | 1567 → 1596 (+29) | 21 (=) |
| `_register_plugin` | 60 (=) | 19 (=) | 175 → 180 (+5) | 4 (=) |
| `should_run_literature_review` | 4 (=) | 0 (=) | 29 (=) | 2 (=) |
| `HyperparamTuningAgent.run` | **258 (=)** | 67 → 69 (+2) | 1085 → 1142 (+57) | 2 (=) |
| `prepare_attempt` | 116 (=) | 32 (=) | 471 (=) | 7 (=) |
| `run_admission_preflight` | 107 (=) | 36 (=) | 521 (=) | 6 (=) |
| `run_inference_scoring_health` | 109 (=) | 26 (=) | 474 (=) | 6 (=) |
| `compute_expected_invariants` | 6 → 7 (+1) | 3 → 4 (+1) | 64 → 83 (+19) | 2 (=) |
| `restore_prior_state` | 100 (=) | 47 (=) | 383 (=) | 4 (=) |
| `build_run_invariants` | 8 (=) | 3 (=) | 103 (=) | 13 (=) |
| `validate_stamped_invariants` | 25 (=) | 14 (=) | 101 (=) | 4 (=) |
| `_load_plugin` | 23 (=) | 7 (=) | 46 → 59 (+13) | 1 (=) |
| `register_model_in_memory` | 16 (=) | 3 (=) | 48 (=) | 1 (=) |

**Zero parameter growth on every row. Maximum branch growth +1**, against a
budget of 3 — and the two rows that moved are the lit-review guard and the
invariants expansion, each a sibling-shaped delta rather than a new family.

The row that matters most is `HyperparamTuningAgent.run` at **258, unchanged**.
CLAUDE.md records why that number is not cosmetic: 258 branch nodes pass
pyright's strict complexity ceiling and 259 fails, and past the limit strict
mode abandons the whole function rather than degrading. A PR that added
composition handling to the tuner's main method and left the count where it was
is a PR that put the handling somewhere else. Three §12.1 tripwire firings
during C7 were each answered by extracting a named authority
(`resolve_tuner_health_config_source`, `build_task_composition_ref`,
`refuse_legacy_lit_review_on_composed_run`, `resolve_run_proposal_blocks`,
`resolve_run_implementor_blocks`) — never by raising the number.

`_is_loss_shaped` / `_reject_loss_shaped` left the table in C5, the commit that
did it, with their successor's numbers in §8.7. Re-anchoring a deleted
function's budget here would have made this comparison vacuous for that row.

### 8.17 F-12a-C9-1 — C7-3 did NOT close Pr2 or Pr3, and the Gate-1 harness found it

**Status: OPEN. This BLOCKS G-12a-1, and G-12a-1 has NOT been run.**

Building the Gate-1 probe harness meant rendering the composed proposer prompt
for a real non-TIDMAD task and censusing it. The census came back dirty:

```text
PROPOSAL_COMMIT_PROMPT      denois · waveform · impact_score   (6 sites)
PROPOSAL_REASONING_PROMPT   impact_score · linear_weight       (2 sites)
prompt_templates/proposal/*.md                                 CLEAN (9 files)
```

A DAVIS-composed run is therefore still told that `"regressor"` emits *"the
denoised waveform directly"*, that its input is *"per-timestep ADC class
indices"*, that `"256 denoising bins per time step is contract-fixed"*, and to
rank files by an `Impact_Score` column its evidence does not contain.

**This is not a new discovery — it is an incomplete C7-3.** §8.9's frozen
classification names these exact strings:

* **Pr2** — *"proposer `[B, 256, T]`, '256 denoising bins', 'the denoised
  waveform directly'"* → **class (2)**, replace from the run's
  `ModelIOContract` / `forward_contract`;
* **Pr3** — *"proposer score-table reading protocol"* → **class (1)**, renders
  nothing.

`ProposalTaskBlocks`'s own docstring names them as the reason the family
exists. C7-3 tokenized the role line (Pr1), the `{EVIDENCE_READING}` region
and `{OUTPUT_CONTRACT_GUIDANCE}`, and the byte-exactness proof it recorded is
real — but it proved the RELOCATION was exact, not that the SURFACE was clean.
Nothing in C7-3 measured the residue, and the deterministic banned-token
census did not cover `PROPOSAL_COMMIT_PROMPT`. **A census is only as strong as
the surfaces it enumerates** — the F-P2b-4 lesson, one PR later.

**Why this is inside D-12a-6 and not a new ratification.** Closing it needs no
new schema family, no new node, no new manifest section and no new adapter:
`ProposalTaskBlocks` is the ratified home, its docstring already states that
*"key-set growth is a framework protocol decision"*, and §8.9 already assigned
both blocks to a task-owned authority. What it needs is additional KEYS in an
existing ratified family — the same relationship `continuous_output_phrase`
has to `science_domain` in D-12a-9.

**The eight sites and their proposed disposition** (shapes are already
derivable; only the PROSE needs a declared home):

| site | residue | disposition |
|---|---|---|
| COMMIT L7 | `"classifier" emits [B, 256, T] …; "regressor" emits [B, T] the denoised waveform directly` | shapes from `declared_output_tensor` (the authority the implementor already uses); the continuous noun phrase declared |
| COMMIT L9 | `Input: … (per-timestep ADC class indices)`; `Output: [B, T] float32 (the denoised waveform directly)`; `'256 denoising bins per time step is contract-fixed'` | input noun phrase declared; continuous noun phrase declared; class-axis noun declared, cardinality derived |
| COMMIT L46 | `output [B, T] float32 (the denoised waveform directly)` | same continuous noun phrase |
| COMMIT L19/L20/L22 | `Impact_Score` trial-strategy bullets + rationale clause | class (1) — task-owned, absent ⇒ omitted |
| REASONING ×2 | `Impact_Score` bullet + the closing "Reference … the `Impact_Score` / `Linear_Weight` columns" sentence | class (1) — task-owned, absent ⇒ omitted |

Legacy byte-exactness is achievable by the same proof C7-3 used: substituting
TIDMAD's declared values back must reproduce the pre-C7 sha256 of both
constants.

**Why Gate 1 was not run first.** G-12a-1's acceptance criterion *is* this
property ("composed-run prompt surface free of TIDMAD science,
probe-verifiable"). Running it now would spend real calls to observe a defect
already established deterministically, and every probe would have to be
re-run after the fix. The harness itself
(`scripts/step12_pr12a_gate1.py`) is committed — it is the instrument that
found this, and it is ready to run once the surface is clean.

**RESOLVED by C7-5.** No new schema family, node, manifest section or adapter:
seven keys were added to the already-ratified `ProposalTaskBlocks`, which is
what §8.9 assigned these blocks to and what its own docstring says the family
is for. Step 01a's renderer had stated the exact condition for lifting the
deferral — *"no authority declares them ... owned by a later step"* — and
D-12a-6 is that authority.

```text
composed DAVIS, blocks DECLARED     banned concepts: 0
composed DAVIS, blocks ABSENT       banned concepts: 0
  and the regressor line reads       [B, 3, 4, H, W] float  -- the task's own shape
```

**Shapes are DERIVED, prose is DECLARED.** `render_classifier_output_shape`
and `render_regressor_output_form` go through `declared_output_tensor` — the
same authority the implementor renders from and the probe validates against —
so the commit prompt can no longer document a form the validator would reject.
Only the noun phrases beside them are declared. One framework sentence stands
in for an absent `class_axis_note` ("the declared output dimension is
contract-fixed, not a hyperparameter"); it is structure, not science, true of
every task and naming no count. Pr3's five sites render NOTHING when
undeclared, per their class (1).

**The task writes prose; the framework writes JSON.**
`per_file_strategy_guidance` is one sentence per LINE and the framework
supplies the commas, quoting and indentation — a declaration should never have
to know it is being spliced into a JSON example.

**Legacy is byte-identical, proved two different ways** because the two
constants are in different states:

```text
PROPOSAL_REASONING_PROMPT  substituted -> 7c69ce7bae2509b8…  == the C0 original
PROPOSAL_COMMIT_PROMPT     rendered    == pb4_legacy_commit_system.txt, UNCHANGED
```

The commit prompt has no pre-C7 constant digest to compare against — Step 01a
had already tokenized it — so its parity is proved against the committed
golden of the RENDER, which is what the model actually reads. An anti-vacuity
test additionally requires every one of the seven new tokens to be present in
the template and absent from the render, so a token nobody substitutes cannot
hide behind either proof.

**Test dispositions — six Step-01a pins INVERTED, none deleted.**
`_assert_whitelisted_survivors_present`, `test_tier_iii_literals_are_
deliberately_retained`, `test_tier_iii_bins_clause_is_whitelisted_not_derived`
and the shadow-literal check all pinned the DEFERRAL: they asserted these
literals were present because nothing owned them, and one of them warned a
later contributor not to "finish the job by inventing an authority". Nothing
was invented, so each is inverted to assert the new ownership — the same
failure class, checkable in the stronger direction. Two more (`test_render_
does_not_branch_on_rank_or_task_type`, and the legacy fixtures in
`test_contract_reassertion` / PB-4) were UPGRADED: the first's normalization
now covers the derived dtype-dropped shapes, and the second pair resolve the
bounded adapter as the composition root does for a legacy run.

Mutation (restore the unconditional TIDMAD noun): **3 RED**, restore 17 green.

**Declared deltas, applied surgically.** `PROMPT_SOURCE_SHA` re-frozen for
both proposer constants with the evidence above; the envelope oracle's one
`proposal_blocks` line rewritten in place (1 insertion, 1 deletion); and the
shipped TIDMAD composition fingerprint moved a second time
(`5836cb0a…` -> `9125bf58…`) because the declaration it points at gained the
seven values. F-12a-C8-1's reasoning is unchanged and its consequence is the
same: a composed TIDMAD run started before this PR fails its resume closed.

### 8.18 G-12a-1 — Gate 1 evidence: **PASS**

**One launch, 4 real calls (cap 6), 12/12 checks.** Provider `openai`, model
`gpt-5.5`. Evidence:
`/home/klz/Data/SIDEREIS_DATA/gate_evidence/step12_pr12a_gate1/gate1_result.json`
— every prompt and every response persisted verbatim.

The fixture is the committed DAVIS composition, rendered through the
PRODUCTION assembly path, with three facts chosen BEFORE the run: 8 context
frames in / 4 future frames out; the target is video; `mse`, LOWER better.

```text
[PASS] x4  every rendered COMPOSED prompt carries no TIDMAD science
[PASS] x4  the declared probes reflect every pre-chosen fact
[PASS] x4  no response imports TIDMAD science — declared or not
```

**The absence probe is the result worth reading.** Asked what domain it was
working in with NO declared blocks, the real model answered, in full:

> No domain was stated.

That is the frozen semantic — *absent composed blocks must not fall back to
TIDMAD science* — observed in model behaviour rather than in bytes. A
deterministic test can prove the prose is gone; only a real call shows the
model does not supply it anyway. With blocks declared, the same probe named
"video future-frame prediction".

**A note on what the blocks do and do not carry.** `proposer.undeclared` still
got all three facts right, because they come from the task's own
`task_description` and `ForwardContract`. That is correct and worth stating
plainly: the blocks carry science FRAMING, not the facts. A reading of this
Gate that credited the blocks with the facts would be overclaiming.

**F-12a-G1-1 — the single FAIL was a defect in the Gate's own evaluation
function, and the Step-09b discipline caught it.** Run 1 reported 11/12 with
`F3_metric_direction` failing on `proposer.declared`. The persisted response
said:

> The primary evaluation metric is the global mean squared error over clips ×
> channels × time × height × width.
> Lower mean squared error is better.

— correct on all three facts. The matcher looked for a literal `"lower is
better"` and could not see the metric name sitting between the words. It is
the same class as 09b's three probe defects (a decimal-breaking sentence
splitter, a probe contradicting its own frozen split, a name-only matcher).

Corrected to a regex **paired with a NEGATIVE clause**, so a fix cannot be
mistaken for a loosening, and FALSIFIED before re-evaluating:

```text
"Lower mean squared error is better."          -> True
"Higher mean squared error is better."         -> False
"...mean squared error over clips." (no dir.)  -> False
"Lower accuracy is better."                    -> False
```

The verdict was then re-derived from the PERSISTED responses of the original
run — **zero additional LLM calls**, exactly the 09b precedent.

### 8.19 G-12a-2 — attempt 1: **INCONCLUSIVE (machine condition), aborted deliberately**

Evidence preserved at
`/home/klz/Data/SIDEREIS_DATA/gate_evidence/step12_pr12a_gate2_attempt1/`
(both locks, the effective health config, the full chain log, and the GPU
census taken at abort).

**INITIAL DIAGNOSIS AT ABORT TIME — LATER SUPERSEDED BY THE §8.20 FORENSIC
AUDIT.** Kept here because the abort decision was taken on it, and deleting it
would hide the reasoning that produced this attempt's classification.

Every attempt died in the same place:

```text
InconclusivePreflight: the bounded 'batch candidate' step at candidate batch 64
exceeded its 120s budget after 191.7s / 182.9s
```

A TIMEOUT, not an OOM, and the subsystem labels it itself: *"pre-flight
produced no usable footprint (timeout) — recorded as an inspection gap, NOT as
evidence about this model."*

| | |
|---|---|
| **initial observation** | the machine was shared: five foreign training processes belonging to another user (`/home/wenyu/summer/…`, running since 2026-08-17 and 2026-08-21) held ~12.9 GiB. At abort time this was read as the cause, and the attempt was written up as a "shared GPU" condition |
| **forensic result (§8.20)** | **the batch-candidate probe is CPU-ONLY and never touches the GPU** — `_build_probe_input` builds a CPU tensor and `probe_activation_footprint` defaults to `device="cpu"`. The direct slowdown was host CPU/load variability, not GPU contention. And the real defect was neither: a **post-hoc wall-clock rejection of a measurement that had already COMPLETED** |

So the GPU census does **not** explain the failure. It recorded a true fact
about the machine that the initial diagnosis over-attributed. The measured
timings and this attempt's INCONCLUSIVE classification stand unchanged; only
the causal claim is corrected.

**Aborted rather than left to exhaust.** The chain had burned 2 of 5 attempts
on the identical cause and would have burned the rest, plus the chain brake,
plus real LLM calls, on a condition that cannot resolve itself. The standing
rule is explicit: *do not repeatedly relaunch hoping for green.*

**NOT accommodated in production.** `ProbeBudgets` is a frozen Pydantic model
with no env override and no CLI flag, so raising the 120 s bound would mean
editing production source to make a Gate pass. That is refused. The blocking
condition must be removed (the foreign jobs finish, or the run moves to an
uncontended GPU) and the Gate re-run unchanged.

**What attempt 1 DID prove, before it stopped — and it is not nothing.**
Composition bound, both locks written, and **F-P56-3's lock half closed, live**:

```text
                                   chain lock          per-model lock
task_composition_fingerprint       9125bf58…      ==   9125bf58…
health_config_sha256               2b804d73…      ==   2b804d73…
resolved_data_scope                [4,5,6,7,8,9]  ==   [4,5,6,7,8,9]
```

Before C1/C2 the per-model lock recorded `None` for the fingerprint and
re-materialized the effective health config under `LEGACY_OMITTED`. Both are
now the run-scoped authority's values, and the two locks agree — observed in a
real composed run rather than in a unit test. That does **not** discharge
G-12a-2, whose failure class is the RESUME chain across a real restart, and
which still requires iteration 2 to read iteration 1's committed state.

### 8.20 F-12a-G2 — Gate-exposed production defect, corrected (operator-authorized)

**A completed CPU resource measurement was discarded solely because it took
too long on a busy host.** Recorded as a **Gate-exposed bounded corrective
commit**, NOT part of the original C0–C8 scope.

**Audit before editing** (`resolve_inference_batch`, `batch_resolver.py`):

| question | answer |
|---|---|
| authority | `ProbeBudgets.single_candidate_seconds`, via the module-level `_BUDGETS = ProbeBudgets()` (`wrapper.py:112`). No env, no config, no CLI |
| watchdog, admission requirement, or feasibility contract? | **none of them.** The check runs AFTER `probe_activation_footprint` RETURNS, so it interrupts nothing and a hung probe never reaches it |
| hung or progressing? | **progressing** — proven by the control flow: the probe returned, at 191.7 s |
| VRAM sufficient? | not the binding question. `_build_probe_input` builds a CPU tensor and the probe traces a CPU-instantiated model, so **the candidate probe never touches the GPU**. Host load average was ~10 on 24 cores with 72 users |
| production-supported override? | **none** |
| would using one change the workload? | n/a |

The module's own docstring already contained the falsification test:
*"The same configuration both failed and passed depending on CPU load, which
is what proves it was never a capacity signal."* This is that defect one level
below where it was first fixed — rule 1 split the budgets per operation, but
the per-candidate budget stayed a wall-clock verdict on finished work.

**The correction, narrowed to the root cause.** A completed probe is accepted
whatever its duration; the elapsed time survives as a `SLOW PROBE (accepted)`
diagnostic. Deliberately NOT done: making the threshold configurable, which
would have preserved the wrong semantics at a looser number. The
`batch_search_seconds` backstop is UNTOUCHED — it is evaluated BEFORE starting
another candidate, so it bounds future work rather than discarding finished
work. `ForwardPassTimeoutError` already exists as the real
probe-has-not-returned watchdog and was not extended here.

`probe_budgets`' docstring gains **rule 3**, the converse of its rule 2, and
the four concepts it keeps apart:

```text
memory feasibility != calibration completeness != host wall time != watchdog timeout
```

**Calibration: `single_candidate_seconds` 120.0 → 200.0** (operator-approved).
Provenance recorded at the field: the observed 191.7 s / 182.9 s completed
probes plus margin, against a 120 s value the docstring says was calibrated on
this same machine UNCONTENDED. Since the correction it only controls how often
the diagnostic prints; it can no longer change a verdict.
`batch_search_seconds` is unchanged at 600.

**Partial-calibration acceptance — audited and DEFERRED, with the reason.**
Asked whether a mid-search deadline could accept already-accumulated evidence:
**it cannot, by construction.** The scan is DESCENDING and returns the FIRST
candidate that passes, so at any mid-search deadline every probed candidate has
FAILED and every untested one is SMALLER; `vram_ok` grows with B and
`intensity_ok` (`B*T <= 800_000`, pure) shrinks with B, so a smaller untested
candidate may still pass. The accumulated evidence is always failures at larger
batches, from which no conservative accepted batch follows. A principled
sufficiency rule needs the search ORDER changed (ascending, so the first pass is
a safe floor) or a two-phase pre-filter on the free intensity predicate — an
architectural change, correctly out of scope here. **Named follow-up:
partial-calibration acceptance + a true probe watchdog.**

**Evidence.** 6 falsifiers in
`tests/unit/agent/evaluate_vram_skill/test_f12a_g2_completed_probe.py`:
a slow-but-finished candidate still returns a batch · the elapsed time is still
reported · **the same model/cap resolves identically on a fast and a slow host**
· the search backstop still raises · a MEASURED memory failure still steps down
to a smaller batch · the 200/600 defaults pinned to the recorded decision.
Mutation (restore the post-hoc rejection): **3 RED**, restore 6 green.
Subsystem re-run: 342 passed.

**Invalidated evidence: none.** The correction touches no prompt, so G-12a-1 is
not re-run; it changes no schema, record, lock or scientific path.

**F-12a-G2b — recorded separately, NOT repaired here.** Free VRAM was ~19.1 GiB
while the Gate requested a 24 GB budget, because the usable cap is derived from
TOTAL rather than currently-free memory — so on a shared GPU it over-promises.
This was **not** the cause of attempt 1 (which failed on a CPU probe), and
repairing it opportunistically in the same commit would blur what the Gate
proves. If the resumed Gate hits a real GPU-capacity failure, it is classified
under its own failure class.

### 8.21 G-12a-2 — attempt 2 INCONCLUSIVE (Q-07c-6), attempt 3 is the canonical run

**Attempt 2 — INCONCLUSIVE: the pre-existing Q-07c-6 runtime-admission defect
prevented the run from reaching the G-12a-2 resume witness.** Operator-recorded
classification; **NOT repaired or absorbed into PR-12a.**

It also VALIDATED the F-12a-G2 correction in production:

```text
attempt 1:  InconclusivePreflight x4  -> never reached training
attempt 2:  InconclusivePreflight x0  -> reached REAL TRAINING
```

Then:

```text
WallClockTimeoutError: watchdog killed training after 119.365s
                       (deadline 118.749s, source=verified_components)
```

A 0.6 s overshoot — the exact signature CLAUDE.md records for **Q-07c-6 = B**:
admission prices `phase="training"` only, so 07a's validation pass, which runs
INSIDE the training subprocess, is unpriced. Step-11's Gate 2 run 1 hit the
identical thing and it was named OPEN and not-Step-11's there too. Shrinking
capacity shrinks the deadline, so the configuration cannot converge by
retrying.

**Attempt 3 — `--runtime_watchdog` ISOLATED.** Accepted by the operator as a
production-supported Gate-isolation control, not a semantic weakening,
conditional on a source audit that was performed and holds on all four counts:

| condition | source evidence |
|---|---|
| an existing supported control | `run_one_iteration.py:1253` — `action="store_true"`, help says **"Default off."** Isolating it IS the default production posture; the gate standard's canonical command opts IN |
| changes no iterations, rounds, model, data, training algorithm, subprocess boundary, composition/lock/state production, restart or restore semantics | the flag decides only whether a `deadline_provider` reaches the sandbox spawn |
| watchdog correctness is not G-12a-2's owned failure class | that class is the composed lock / fingerprint / resume chain |
| process cleanup / restart machinery stays active | **stronger than assumed.** `sandbox_executor.py:992-998`: plain mode deliberately does NOT pass `start_new_session`, so the child stays in the caller's process group and receives the chain's terminal SIGINT (`run_chain.sh:171` + `install_chain_stop_traps`). `killpg`/`setsid` exist ONLY because the deadline path needs its own session |

Precedent: Step 09.5a's Gate 2 ran with Health gating isolated OFF as
"lifecycle-Gate isolation only" — the same shape, an orthogonal subsystem
isolated for a lifecycle Gate.

### 8.22 G-12a-2 — **PASS** (infrastructure / lifecycle semantics)

> **G-12a-2 PASS — infrastructure / lifecycle semantics.**
> **Scientific round outcome: HealthGate INVALID / collapsed candidate —
> observed but explicitly NON-GATING.**
>
> Stated this way on purpose. A later reader who greps the chain log will find
> `HealthGate INVALID` and a `None` best score, and must not conclude the Gate
> should have failed. Model quality, HealthGate PASS, score magnitude and
> convergence are NOT this Gate's criteria — the Step-10 P5+P6 governance
> correction, that a Gate never acquires acceptance criteria by proximity.

Evidence:
`/home/klz/Data/SIDEREIS_DATA/gate_evidence/step12_pr12a_gate2/gate2_result.json`
plus both chain logs, all three per-model locks, the chain lock, the effective
health config and both manifests.

**The verdict was computed by an evaluator written BEFORE the outcome was
known** (`scripts/step12_pr12a_gate2_evaluate.py`, committed at `99cb7853`
while the run was still going). It reads only persisted artifacts and re-runs
nothing. Falsifying it first against the known-bad attempt-3 workspace caught a
vacuity hole in the Gate's own check — A3 passed with ZERO stamped artifacts,
because "none found, all correct" is an empty set rather than evidence. Fixed
before it judged anything real. That is the Step-09b lesson applied to my own
probe rather than learned from it again.

| criterion | result |
|---|---|
| **A1** iteration 2's pre-flight validated against iteration 1's lock | **PASS** — iteration 1 `no_records` (chainable), iteration 2 produced its own per-model locks, i.e. it reached real work AFTER surviving `validate_stamped_invariants`, which raises on mismatch and is silent on success |
| **A2** the per-model lock carries the fingerprint AND an honest health identity | **PASS** — all THREE per-model locks carry `task_composition_fingerprint 9125bf58…` and `health_config_sha256 2b804d73…`, matching the chain lock AND the shipped manifest's declared value |
| **A3** records / outputs stamped from ONE run-scoped authority | **PASS** — 9 stamped artifacts, every one carrying the declared fingerprint |

**F-P56-3 is closed with a live witness, not an inference.** Before C1/C2 the
per-model lock recorded `None` for the fingerprint and re-materialized the
effective health config under `LEGACY_OMITTED`; it now mirrors the chain lock
exactly, observed in a real composed run.

**The process boundary is stronger than the frozen shape asked for, and the
ledger says so rather than implying a clean single chain.** The frozen
disposition was 2 iterations × 1 round in one chain. What actually happened:
iteration 1 completed with real training and a real score (`-1.514`); the
chain then HUNG for ~20 minutes on four provider HTTPS sockets stuck in
`CLOSE-WAIT` after `tuner.planner` had already returned (a provider/network
condition, no timeout fired, `do_sys_poll`, 0.4 % CPU, no children); the
process was KILLED; and a NEW process resumed at `--start_iter 2` in the same
workspace, where `restore_prior_state` consumed iteration 1's committed state
and the pre-flight validated its lock.

That is the same failure class with an UNAMBIGUOUS process boundary — a real
kill-and-restart rather than a loop turn — so it is at least as strong a
witness for "iteration 2 reads iteration 1's committed state across a real
restart". It is recorded honestly instead of being presented as one
uninterrupted run.

**Attempt history, for the record:**

| attempt | outcome |
|---|---|
| 1 | INCONCLUSIVE — VRAM pre-flight discarded a COMPLETED probe under host load (§8.19). Cause corrected: **F-12a-G2** |
| 2 | INCONCLUSIVE — reached REAL TRAINING (`InconclusivePreflight` 4 → 0, proving F-12a-G2 in production), then the pre-existing **Q-07c-6** watchdog killed training at deadline + 0.6 s (§8.21). NOT repaired here |
| 3 | INVALID — **my launch error**, not a Gate finding: I dropped `--runtime_watchdog` but kept `--validation_max_phase_seconds`, and the schema correctly fail-closed on the incoherent pair ("the watchdog is what enforces the deadline, so without it the ceiling would be recorded and never applied") |
| 4 | **PASS**, with the mid-run provider hang and resume described above |

### 8.23 Terminal SHA discipline — what the executable-head delta actually contains

The frozen rule is *executable head → Gates run there → docs-only after →
ONE authoritative CI at the exact final PR head*. The delta from the Gate's
head `ec30bd65` is stated exactly rather than claimed to be docs-only:

| path | classification |
|---|---|
| `docs/design/.../pr_12a_composed_path_closure.md` | documentation |
| `scripts/step12_pr12a_gate2_evaluate.py` | Gate EVIDENCE TOOLING — reads persisted artifacts, imported by no production module, never executed by a run |
| `agent/skills/evaluate_vram_skill/probe_budgets.py` | **production file, comment-only.** Compiled bytecode is BIT-IDENTICAL across the change (both code objects marshalled and hashed); the one line removes an architecture-family string from a module that documents itself as containing none |

**The frozen mechanical DOCS-ONLY condition was NOT literally satisfied, and
this document does not claim it was.** Two of the three paths are not
documentation. Operator terminal review accepted the observed delta because
every non-documentation item was independently shown to be **execution-inert**:
evidence-only tooling not reachable from production, plus a comment-only
production-file edit with bytecode identity proven.

Recorded as a **BOUNDED TERMINAL-EQUIVALENCE EXCEPTION FOR PR-12a**
(operator terminal review, 2026-08-23).

**This is NOT a generic relaxation of the Step-12 terminal rule.** Future
Step-12 PRs still aim for `final executable head → Gates → evidence/ledger/docs
only → final PR head`. The exception was granted on proven inertness for one
observed delta, not on a principle that comment edits are free. Nothing was
edited afterwards to make the historical delta cosmetically docs-only, and
neither Gate was re-run.

### 8.24 Operator terminal review — ratifications and closeout fixes (2026-08-23)

**VERDICT: APPROVE WITH SMALL CLOSEOUT FIXES.** The implementation
architecture is accepted; G-12a-1 and G-12a-2 are both accepted as PASS; no
Gate rerun is required.

**1A — TIDMAD composition fingerprint `d6628a93…` → `9125bf58…`: ACCEPTED.**
The shipped manifest genuinely declares `proposal_blocks:` and
`implementor_blocks:`; those are semantic sources and belong in composition
identity. A composed TIDMAD workspace started before this PR may therefore fail
its resume closed against the new identity — **intended fail-closed behaviour,
and no compatibility bypass is to be added.** The Pets/DAVIS
undeclared-fingerprint differential evidence is retained (§8.16).

**1B — C7-5 / `ProposalTaskBlocks` key growth: ACCEPTED and TERMINALLY
RATIFIED**, in the operator's words:

> "Operator terminal review confirms C7-5 key-set growth as an in-scope
> completion of the already-ratified D-12a-6 family, not a new additive schema
> family requiring a separate contract."

The seven keys extend an already-ratified family, close Pr2/Pr3 surfaces
already assigned to that authority, introduce no new schema family, no new
manifest section and no new task authority, and preserve legacy rendered
bytes. The implementation is unchanged. This closes the one judgement call
this PR flagged for possible reversal (§8.17).

**1C — F-12a-G2: ACCEPTED as implemented.** The semantic distinction is
confirmed correct, and a completed CPU resource probe may not be rejected
merely for being slow. The 120 → 200 s calibration update is accepted
**because that threshold now controls diagnostic classification and provenance
rather than capacity validity**. The `batch_search_seconds` future-work
backstop remains separate. Partial-calibration acceptance remains a named
follow-up. **The correction is not to be broadened** (§8.20).

**1D — G-12a-2 process boundary: attempt 4 ACCEPTED as the canonical PASS.**
A clean uninterrupted 2×1 rerun is NOT required. The evidence stands exactly
as it occurred, and two things must not be claimed from it: **that the chain
was uninterrupted**, and **any inference about provider-hang robustness**
(§8.22).

**Closeout fixes applied under this review**, all documentation/ledger/PR-body
only:

| # | fix |
|---|---|
| 1 | §8.19's superseded "shared GPU" causal claim relabelled as the initial diagnosis at abort time, with the forensic result beside it. Measured timings and the INCONCLUSIVE classification unchanged; history not erased |
| 2 | §5-C9 checklist closed with real evidence, and the pre-terminal-review head `870897c6` / CI `32613380946` explicitly labelled as PRE-review state |
| 3 | §8.23's "docs-only" wording replaced by the ratified BOUNDED TERMINAL-EQUIVALENCE EXCEPTION, with its non-generality stated |

### 8.4 Milestone status

| commit | state | evidence |
|---|---|---|
| **C0** | **COMPLETE** — `7385f569` | §5-C0 §7; 56 tests; 3 mutation proofs; 169-test helper regression |
| **C1** | **COMPLETE** — `c54dc960` | §5-C1 §7; 13 new tests + 2 guards retired; subsystem regression 1197 passed |
| **C2** | **COMPLETE** | §5-C2 §7; 12 new tests + 1 guard retired; the W4 census re-pointed; findings §8.5 |
| **C3** | **COMPLETE** | §5-C3 §7; 5 tests; comment + parent §4.1 rows corrected; zero executable production lines changed |
| **C4** | **COMPLETE** | §5-C4 §7; 17 new tests, 3 A3 tests upgraded, guard (c) retired; 752 passed |
| **C5** | **COMPLETE** | §5-C5 §7; `_is_loss_shaped` deleted, 4 pins upgraded across 3 modules, pack docs + CLAUDE.md amended; 2410 passed |
| **C6** | **COMPLETE** | §5-C6 §7; private duplicate retired, both callers migrated, cycle + 2 workarounds dissolved; 24-test layering census; 3930 passed |
| **C7 audit** | **COMPLETE** — `cf7670c1` | §8.9 classification table, 10 blocks, recorded before any moved |
| **C7-1** | **COMPLETE** — `2a9e95c9` | D-12a-7 lit-review refusal, extracted authority, §12.1 tripwire back at 132 |
| **C7-2** | **COMPLETE** — `ed29cb7b` | seven blocks gated; legacy rendered manifest unmoved; guard (e) retired — all six C0 guards closed; CI-equivalent suite 12,022 passed |
| **C7-3** | **COMPLETE** | §8.13; ProposalTaskBlocks + config + adapter + manifest section + fingerprint; relocation proved BYTE-EXACT; 1503 passed |
| **C7-4** | **COMPLETE** | §8.15; D-12a-9 ratified in flight; 8/8 required validations; mutation 5 RED / restore green; legacy rendered bytes + PB goldens unmoved; 2,210 passed |
| **C8** | **COMPLETE** — `ebea3289` | §8.16; F-12-6 widening mutation-proven on both files; docs synced against merged source; structural pre/post — zero parameter growth, max branch +1, tuner `run()` unchanged at 258 |
| **C7-5** | **COMPLETE** | §8.17; the Pr2/Pr3 residues C7-3 did not reach; composed banned concepts 0 both declared and absent; legacy byte-identical two ways; 17 tests; mutation 3 RED; six Step-01a pins INVERTED |
| **C9** | **COMPLETE** | **G-12a-1 PASS** (§8.18) · **G-12a-2 PASS** (§8.22), verdict from an evaluator written before the outcome and falsified against a known-bad run · F-12a-G2 corrective commit (§8.20) · PR #248 |
