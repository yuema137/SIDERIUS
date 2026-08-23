# Step 12 — External Extensibility Graduation (task composition regime B, CAP-SCOPE, out-of-tree proof)

## 0. Status, source anchors, authority

**STEP 12 — REVISION 3 — OPERATOR APPROVED 2026-08-22. LIVE PARENT
LEDGER, not an immutable freeze (operator clarification, 2026-08-22): the
semantic contracts, PR topology, invariants and Gate classes below are the
approved authority, and the parent is UPDATED as each child PR completes
(the §11.1 checkpoint's ledger step). READY FOR PR-12A DETAILED DESIGN.
IMPLEMENTATION MUST NOT BEGIN (each child implements only after ITS
detailed design is approved).**

Revision history: rev 1 (2026-08-22, anchor `c1caa609`, Step 11 unmerged) →
operator review 2026-08-22 (verdict **NOT READY TO FREEZE**: architecture
direction PASS · debt coverage PASS · PR decomposition NEEDS REVISION ·
CAP-SCOPE contract NEEDS MATERIAL HARDENING · lifecycle/child integrity
NEEDS MATERIAL HARDENING · validation STRONG BUT NOT YET SUFFICIENT; nine
required amendments) → rev 2 applies all nine amendments (§0.1-B) and the
mandatory Step-11 reconciliation (§0.1-A) → second operator review
2026-08-22 (verdict **ARCHITECTURALLY READY FOR PARENT FREEZE AFTER MINOR
CONSISTENCY AMENDMENTS**; Q-12-3 and Q-12-4 ratified; freeze authorized on
a clean final sweep) → **rev 3 = the bounded closeout**: stale
`--task_scope_json` row corrected, structural/source baselines refreshed to
`e4cd5c18`, Q-12-3/Q-12-4 recorded RATIFIED, the pre-freeze
all-five-child-drafts requirement replaced by the sequential child-design
rule, the inter-PR reconciliation checkpoint added (§11.1), roadmap/D14
wording synced, final consistency sweep clean → **FROZEN**.

**The parent freezes capability boundaries, PR ownership/order, cross-PR
invariants, debt ownership, Gate classes, the graduation acceptance and the
checkpoint protocol — deliberately NOT implementation-level detail.** Each
child PR's detailed design (starting with PR-12a, next) is drafted fresh
against the then-current merged source, follows the operator's 8-section
per-commit checklist standard, and freezes before that child implements.

| field | value |
|---|---|
| roadmap contract | `siderius_generic_framework_upgrade.md` §15.1 Step-12 row (line ~1566), §22.12 (Step-12 cell), §22.14, §22.23.12, **§22.24 (forward invariant + §22.24.3 acceptance upgrade, operator 2026-08-18)** |
| debt-audit authority | `step_01_07_extensibility_debt_audit.md` — TRIAGE ACCEPTED 2026-08-18; its §6/§7.6 B-class set is a FORMAL INPUT to this design and is re-audited in §4 below (operator directive, 2026-08-22) |
| CAP-SCOPE authority | `step_10_orchestration_task_binding/pr_10_p5_6_lifecycle_and_three_task_closure.md` §2.5 (a)–(f) + §10.2 (frozen operator constraint); Step-11 design §4 Q-11-4 = B / R-11-12 |
| source anchor (rev 2) | **post-Step-11 master `e4cd5c18`** (= `origin/master`), main checkout `/home/yuema137/SIDERIUS`, branch `step12-external-extensibility`. Rev 1 was drafted at pre-merge `c1caa609` |
| Step-11 status (rev 2) | **MERGED.** PR #247, squash `da2aa705` (merged 2026-08-22); final PR head `fd6bfccb`; **final executable head `88f190a1`**, exact-head CI `32562135614` SUCCESS; Gate-2 FINAL **PASS** at that head (Step-11 doc §11d). The rev-1 `[P11]` provisional facts are ALL reconciled against merged source — §0.1-A. Two new operator rulings recorded in Step-11's closeout, **R-11-13** (argv byte-parity wording) and **R-11-14** (C8 stamp ratified as a bounded contract correction), are absorbed there |
| roadmap-row filename note | the roadmap row forward-referenced `step_12_task_composition_binding.md`; **corrected to this document in the rev-3 freeze commit**, together with the CAP-SCOPE-owner annotation and the D14 seam-wording amendment (Q-12-2 = A) |
| operator questions (rev 3) | **0 OPEN.** Q-12-1 RULED = five PRs (§11) · Q-12-2 RULED = A (sibling `TaskScopeCapability` + artifact/digest transport, §5.5) · **Q-12-3 RATIFIED** (operator, 2026-08-22): fail-closed guard when the optional legacy lit-review path is explicitly enabled on a composed non-legacy run; full generic lit-review prompts = named post-roadmap debt; the Step-12 external graduation does NOT claim optional lit-review support (§0.1-B item 8) · **Q-12-4 RATIFIED AT PARENT LEVEL** (operator, 2026-08-22): the generic-topology principle is FROZEN; the concrete `DatasetProfile` topology contract is intentionally delegated to the PR-12b detailed design, which must source-audit and freeze it before 12b implements (§5.5) |
| PR decomposition | **FIVE PRs — RULED (Q-12-1)**: 12a → 12b → 12c → 12d → 12e (§11) |
| Gate disposition | per-PR (§14): 12a Gate 1 REQUIRED + Gate 2 REQUIRED (default 2×1) · 12b Gate 2 REQUIRED · 12c Gate 2 REQUIRED (minimal real-subprocess bootstrap, no training) · 12d Gate 2 REQUIRED (Pets + DAVIS, both out-of-tree-loaded) · 12e Gate 2 REQUIRED (fourth task 2×1) — five distinct real failure classes, no giant terminal Gate |

Authority order used throughout: repository/git/source truth → frozen designs
00–11 → merged implementation/tests 00–11 (Step 11 merged 2026-08-22; during
rev 1 its candidate was consulted READ-ONLY as provisional evidence) →
roadmap → handoffs → memory.
Two documents agreeing are not independent evidence; every load-bearing claim
below carries a `file:line` anchor — **originally verified at `c1caa609` by
the design author (three parallel read-only audits supplied breadth; each
claim used here was re-verified directly), then revalidated against
post-Step-11 master `e4cd5c18` at the rev-3 closeout with changed anchors
refreshed in place** (the affected files: the tuner main file ±1–14 lines,
`task_composition.py` +15, `sandbox_executor.py` +13, `execution.py` +10,
`denoising_score_single.py` C5 restructuring; all other cited files
unmoved).

**Standing operator directives incorporated (2026-08-22):**

1. **No Step 11.5.** The accepted debt-audit triage assigned B-class items to
   Step-10/12 composition and required re-audit at Step 12. They are re-audited
   here (§4), classified `CLOSED BY STEP 10/11` / `STILL BLOCKS STEP 12` /
   `NO LONGER LOAD-BEARING`, and the still-load-bearing ones are placed into
   Step-12 children. A prerequisite milestone outside Step 12 would require
   new source evidence of a finding that is semantically independent of
   extensibility yet must land first — §4 found none.
2. **Multi-PR is the default posture**; a single-PR Step 12 carries the burden
   of proof. §11 derives the topology from Gate boundaries, not file counts.
3. Graduation is the full chain, not registration: external package → parent
   loads → children load → scope reconstructs generically → training /
   inference / scoring cross the same infrastructure → resume/fingerprint
   correct → SIDERIUS core source diff = 0.

### 0.1 Rev-2 change record — Step-11 reconciliation + operator-review dispositions

**A. Step-11 post-merge reconciliation (DISCHARGED 2026-08-22).** Merged
truth: PR #247, squash `da2aa705` (merged 2026-08-22T17:19Z); final PR head
`fd6bfccb` (docs-only above the executable head); **final executable head
`88f190a1`**, exact-head CI `32562135614` SUCCESS; master `e4cd5c18` after
the roadmap/CLAUDE.md status-sync commit. Gate-2 FINAL **PASS** at
`88f190a1` (Step-11 doc §11d): composed children consumed the transported
data root and the declared metric; ceilings 40/60/24 with recorded
provenance; TIDMAD glob unchanged; chain-lock fingerprint
`d6628a93fcb3578c` stamped on BOTH record and output. Each rev-1 `[P11]`
fact re-verified against merged source:

| item | verdict at `e4cd5c18` |
|---|---|
| `deliverable:` manifest family + `RunTaskComposition.deliverable_naming` | **HELD** |
| `--task_manifest` child re-composition (`denoising_score_single.py:108,212-216`; `compose_metric_from_manifest` / `compose_deliverable_naming_from_manifest`) | **HELD** — §7's 12c mechanism stands on it |
| `bind_run_task_composition(…, physical_data_root=…)` (`task_composition.py:1223`) + `CompositionDataRootMissing` fail-closed | **HELD** |
| `bind_task_manifest_path` / `bind_composition_fingerprint` ContextVars (`task_composition.py:1040` area) | **HELD** |
| C8 additive default-`None` fingerprint stamps (`agent/schemas/hyperparam_tuning.py:550,2852`) | **HELD — now operator-RATIFIED as R-11-14** (bounded contract correction; the process lesson — a schema expansion is never implementation discretion — is recorded there and binds every Step-12 child) |
| C1 env transport (`isolated_probe.py:510` `env=subprocess_env(…)`); `probe_subprocess.py:336` recorded production-unreachable | **HELD** |
| `core/resume.py` task token removed (the two remaining `TIDMAD` hits, `resume.py:1487,1491`, are the C8 explanatory comments) | **HELD** |
| `run_one_iteration.py:1499` `run_scope.resolve(TIDMAD)` NOT fixed by Step 11 | **CONFIRMED on merged source — F-12-1 stays 12a's** |
| **R-11-13** (new operator ruling in the Step-11 closeout): legacy byte-parity wording corrected — legacy transport OPTION SURFACE and execution semantics byte-identical; the positional child-script token may canonicalize to the current-checkout absolute path | **ABSORBED** — every "legacy argv byte-identical" obligation in this design reads through R-11-13's wording |
| **F-11-C10-a** (Gate-caught C8 defect, fixed): BOTH fingerprint stamps now read `active_composition_fingerprint()` (exactly two production call sites, `records.py:490,838`, AST-pinned); the dead `RunBindings.task_composition_fingerprint` field removed | **ABSORBED — narrows F-P56-3**: the per-model lock's `None` no longer feeds any stamp; 12a's remaining F-P56-3 scope = the lock's own recorded honesty + the `task_health_binding` kwarg (§4.1-R3) |

**B. Operator review of Revision 1 (2026-08-22) — nine required amendments,
all applied in this revision:**

| # | amendment | applied at |
|---|---|---|
| 1 | Step-11 reconciliation before anything else | §0.1-A |
| 2 | **Q-12-1 RULED: FIVE PRs** — 12c stands alone with a minimal real-subprocess bootstrap Gate (F-12-3/F-12-4 are real process failure classes provable without training); 12d keeps only real contrast data + training/inference/scoring | §11, §12, §14 |
| 3 | 12a's "Gate 2 NOT REQUIRED — no execution-path semantics change" WITHDRAWN; default = bounded 2×1 composed-TIDMAD Gate 2 on the per-model lock / fingerprint / resume chain; downgrade only via an explicit semantic-latency analysis in the child design | §12-12a, §14 |
| 4 | scope transport = atomic workspace artifact + digest, NEVER raw scope JSON on argv (`ARG_MAX` class); attempt-scope identity (`payload → canonical bytes → scope_digest → transport → child check → evidence stamp`) gets ONE evidence authority | §5.5 |
| 5 | **Q-12-4 opened, principle FROZEN**: generic `DatasetProfile` topology contract — no `TidmadTopology \| PetsTopology \| DavisTopology` union, no "three optional built-in topology blocks" | §5.5-(d) |
| 6 | registration lifecycle = transactional/run-scoped overlay: within a run, same-id-different-content refuses; after unwind, a different roster is legal (no permanent poisoning); the health ledger is precedent, not a mechanical copy; a registry hit is never trusted bare | §8, §7 |
| 7 | parent-level FROZEN invariant: every child-consumed external semantic is validated against a parent-pinned identity before consumption | §7 |
| 8 | Q-12-3 approval withheld pending source evidence — **evidence now recorded**: literature review is opt-in and OFF by default at all three layers (`_chain_common.sh:192` `ML_LIT_REVIEW_ENABLED=0`; `run_one_iteration.py:2021-2032` CLI > YAML `enabled` > False, fail-safe False on unreadable YAML; `configs/lit_review_config.yaml:34` top-level `enabled: false`) — NOT a load-bearing node of the normal composed chain. Disposition re-submitted for ratification: fail-closed guard when explicitly enabled on a composed non-legacy run + named post-roadmap genericization debt + the graduation contract explicitly not claiming lit review for external tasks. **RATIFIED (operator, 2026-08-22, rev-3 closeout)** — this does not weaken the "normal composed workflow" graduation claim, because the path is not default/load-bearing | §0.1-B, §20 |
| 9 | the explicit final validation matrix (§18a); per-PR terminal discipline (§12 preamble); post-Step-12 cross-system graduation audit (12e scope) | §18a, §12 |

Validation strengthenings from the same review, applied: 12b's anonymous
fourth-shaped scope-capability fixture (§12-12b) · 12d requires BOTH tracks
loaded via out-of-tree `file:` refs (§12-12d) · 12e's restore proven by
process provenance + negative controls EXECUTED, not unit-only (§12-12e).
Process wording: the 12e mechanism-gap rule now reads
`12e BLOCKS → bounded corrective PR against the owning subsystem →
re-validate invalidated downstream evidence → return to 12e` (§12-12e).

---

## 1. Final graduation capability statement

> **A materially new scientific task package OUTSIDE the SIDERIUS source tree
> can declare all task-owned semantics through the supported public
> mechanisms and run the normal composed workflow — parent process AND every
> required child process — with ZERO SIDERIUS production-source edits.**
> The final claim is the roadmap's §22.24.3 form: *"SIDERIUS supports a
> task-package protocol; TIDMAD, Pets and DAVIS are three packages using
> it."*

Decomposed into the six capabilities the operator's directive names, each with
its owning PR (§11):

| # | capability | owner |
|---|---|---|
| G1 | the composed path resolves **zero** implicit TIDMAD semantics (values or prompt science) | 12a |
| G2 | task-owned training/eval **scope** is constructed by the task, transported generically, and rehydrated in the child (CAP-SCOPE (a)–(f)) | 12b |
| G3 | an out-of-tree package's plugins are loadable in the **parent and in every required child**, run-scoped, leak-free | 12c |
| G4 | Pets and DAVIS cross the **same real subprocess training/inference/scoring boundary** with no task-specific infra edits (contrast L4) | 12d |
| G5 | a genuinely out-of-tree **fourth task** registers and runs end-to-end with a machine-checked zero-core-edit census | 12e |
| G6 | resume / invariants / fingerprints are correct for external packages (content-pinned, relocation-equal, fail-closed on mismatch) | 12a/12c/12e |

Two kinds of openness stay deliberately distinguished (§22.24.2, frozen):
**task-plugin semantics** must be externally extensible with zero core edits;
**execution backends** (Python · executable · skill/agent · container · MCP)
are framework capabilities added only on real need. Step 12 ships the Python
plugin backend everywhere; it does not implement speculative backends (§2).

---

## 2. Explicit non-goals

* **No new execution backends.** Python `file:`/`module:` refs are the shipped
  backend for every family. Command/skill/container/MCP adapters are
  documented as protocol-compatible future adapters only (§22.24.2); building
  one now would be speculative.
* **No renaming of frozen record keys** (`denoising_score`, `file_vector`,
  `score_table` — D1/Step-06 frozen names). 12a fixes the planner's
  *hardcoded prose literal* (§4.6-L1); the persisted key names stay frozen and
  their rename remains post-M1 D1 debt.
* **No change to the frozen TIDMAD score formula, metric semantics,
  direction vocabulary, or the Step-06 evaluation contract.**
* **Un-composed (regime-A) behaviour stays byte-identical** — the roadmap's
  Stage-A criterion for this step. Legacy fallbacks (`derive_tidmad_metric`,
  the TIDMAD data-path compatibility row, the import-time data-root template)
  remain reachable by *not composing*; Step 12 removes their reachability
  from the *composed* path only. Full removal of the import-time
  `data_paths.py` template fallback stays named post-roadmap debt (R-11-8:
  the removal breaks CI collection repo-wide and belongs to its own change).
  **Recorded contradiction (resolved by authority order, no operator ruling
  needed):** two in-source comments describe the un-composed path as "the
  bounded compatibility path Step 12 removes" (`workflows/task_composition.py`
  module docstring `:40-42`; `workflows/model_exploration.py:2195-2197`). The
  roadmap's Step-12 row — the binding contract — says the opposite
  ("regime-A callers byte-unchanged"), and §22.14's regression rule assumes
  the legacy control keeps executing. This design follows the roadmap:
  regime A survives Step 12 byte-identical; retiring it (making composition
  mandatory, "TIDMAD is just a package" with no special path) is a POST-M1
  operator decision. 12a corrects the two comments' wording in passing
  (docs-only) so source stops promising a removal this step does not
  perform.
* **No `run_comparison.py` composition support** (Q-P1-1 frozen: the
  standalone baseline harness stays legacy).
* **No opportunistic debt sweep.** §19 triages every known debt; anything not
  promoted there by the graduation test ("would its absence make the
  external out-of-tree graduation false, fragile, or dishonest?") stays
  named post-roadmap debt: five-OOM-matcher consolidation (F-11-9), device-0
  selection (F-11-10), PRESETS register-or-retire, stale docstrings,
  timing-sensitive real-training tests in the unit tier, dashboard direction
  literals beyond what 12a's re-audit proves composed-path-load-bearing.
* **No big-bang prompt rewrite.** 12a moves the *misleading-science* prompt
  surfaces behind task-owned declarations (the 09b pattern); it does not
  re-architect prompt engineering, few-shot corpora, or the literature-review
  templates beyond the Q-12-3 ruling.
* **No repo-wide structural refactor.** §10 imposes per-site extraction rules
  on the functions Step 12 touches; nothing else.
* **Step 12 freezes only after the Step-11 merge reconciliation** (§20). No
  unmerged Step-11 behaviour is treated as repository truth here.

---

## 3. Cross-Step-00–11 extensibility matrix

Classification vocabulary: **EXT** = externally extensible today (proven load
path, no core edit) · **IN-TREE** = extensible only by in-tree source ·
**CENTRAL** = built-in / central-edit required · **CAP-SCOPE** = blocked by
CAP-SCOPE · **LEGACY** = legacy-only surface · **NLB** = not load-bearing for
graduation. `[P11]` = landed by Step 11. **Rev-2 note:** every `[P11]` cell
was re-verified against merged master `e4cd5c18` and HELD (§0.1-A); the
marker is retained as provenance only, no longer as a provisional flag.

| subsystem | semantic owner | selection / binding | crosses process? | unknown ref | classification | anchor |
|---|---|---|---|---|---|---|
| DatasetProfile / topology / value encoding | `execute_tools/dataset_config.py` | manifest `dataset_profile.config` → `load_dataset_profile` | yes (`--dataset_profile_json`) | fail-closed when supplied-broken | **EXT for declaration; CENTRAL for topology semantics** — the schema itself requires TIDMAD 1-D topology (`psd_segment_length`, `segments_per_file`, `abra_*.h5` patterns, `dataset_config.py:42-61`); Pets/DAVIS fixtures FABRICATE those values | CAP-SCOPE (d) → 12b |
| ModelIOContract | `agent/schemas/model_io_contract.py` | external JSON, argv-bound `--model_io_json` | yes | fail-closed | **EXT** (debt-audit #6 SATISFIES; unchanged since) | — |
| TaskDataPath (4-method seam) | `execute_tools/task_data_path.py` | manifest `task_data_path` `file:`/`module:` → registry | **id only** (`--task_data_path_id`, emitted `core/sandbox_executor.py:852-875`, consumed via `resolve_transported_task_data_path`) | fail-closed both ends (`task_data_path.py:294-300`) | **EXT in parent; IN-TREE in children** — children bootstrap exactly the 3 built-ins (`train_engine_sandbox.py:31-32`, `inference_single.py:26-27`, `denoising_score_single.py:174-176`; all three carry "out-of-tree … Step 12 owns it") | 12c |
| task-owned scope | the 3 impl modules (`TidmadScope` `tidmad_data_path.py:297`, `PetsScope` `pets_data_path.py:115`, `DavisScope` `davis_data_path.py:86`) | direct Python instantiation only | **NO** — no serialization, no registry, no shared base (Step-11 §4 Q-11-4 table re-verified) | n/a — wrong-task scope raises `TypeError` in-process (`tidmad_data_path.py:327-334`) | **CAP-SCOPE** | 12b |
| DeliverableSpec / DeliverableNaming | `execute_tools/deliverable_spec.py` | derived (`derive_tidmad_deliverable_spec`); [P11] optional manifest `deliverable:` → `DeliverableNaming` | reconstructed from `--dataset_profile_json`; [P11] scoring child re-composes from `--task_manifest` | validated by the contract's own type | **IN-TREE pre-Step-11; [P11] EXT** — but the TUNER-side spec acquisition is still unconditional TIDMAD (`ml_hyperparameter_tune_agent.py:537`) | 12a re-audit |
| TrainingObjective (losses) | `models_format_sandbox.py` + `SIDERIUS_LOSS_DIRS` | env two-tier resolution, `loss_type="custom"` | yes (`subprocess_env` sets `SIDERIUS_LOSS_DIRS`; child reads `agent_generated/_loss_loader.py:148`) | fail-closed | **EXT** (the Level-2 existence proof, debt-audit §3.4) | — |
| ValidationDiagnostic / TrainingDiagnosis | `execute_tools/training_history.py`, `agent/schemas/training_diagnosis.py` | derived from R2/R3 histories | R3 runs inside the training child | open `objective_kind: str`, zero task vocabulary | **EXT** (SATISFIES; unchanged) | — |
| EvaluationMetric / MetricSpec / scoreability | `execute_tools/evaluation_metric.py` | manifest `metric.declaration` + `metric.implementation` (`_compose_metric`, `workflows/task_composition.py:573-635`) | in-process route bound; subprocess route: the legacy branch derives TIDMAD (`denoising_score_single.py:226,248`), the composed route re-composes via `--task_manifest` (`:108,212-216`) [P11] | fail-closed 5 branches | **EXT in parent (P1); [P11] EXT in scoring child after Step 11** | 12a pin |
| primary + secondary metric declarations | same, P2b | manifest `secondary_metrics:` list, same authority | stamped on records/outputs; evaluated in-process | fail-closed, dup/primary-collision refused | **EXT** | — |
| Health declarations / plugins / views | `execute_tools/health_checks/` (08b/08c) | task config `plugins: kind:file/directory` refs → run-scoped loader `_plugin_binding.py` | **parent-only by design** ("no sandbox subprocess imports this package") | fail-closed; run-scope ledger `HealthPluginRunScopeError` (`_plugin_binding.py:381-398`) | **EXT** — the working precedent for §8's lifecycle | — |
| proposer evidence | P3 `build_proposer_evidence` | typed, one projection | n/a | typed | **EXT** (task-free carriers) | — |
| proposer / implementor / planner PROMPT science | hardcoded framework literals | none — no task-blocks mechanism for these nodes (zero `task_blocks` outside `agent/schemas/interpretation.py:818`) | n/a | n/a | **CENTRAL** — `denoising` role prose, `[B,256,T]`/256-bin contract semantics, score-table protocol (`ml_model_proposal_agent.py:336,391,393,430`; `ml_model_implementor.py:426,635`; `agent/prompts.py:66` hardcodes `` `denoising_score` `` beside the parameterized `{METRIC_IDENTITY_LINE}`) | 12a (G1) |
| interpretation task blocks | 09b `InterpretationTaskBlocks` | manifest `interpretation_blocks:`; workflow site composition-aware (`model_exploration.py:2197-2201`) | n/a | fail-closed loader | **EXT** (the pattern 12a extends to the proposer) | — |
| tuner policy inputs (order, thresholds) | `MetricOrder` + spec stamps | from the bound spec | spec stamped on outputs | refuse-to-rank semantics | **EXT** | — |
| tuner sample selection / eligibility | `planning.py:397-413` `build_sample_set` unconditional; trial anchors `ml_hyperparameter_tune_agent.py:795-803`; health peek paths `execution.py:42` + TIDMAD file naming | none — TIDMAD-shaped | TIDMAD ingredients as `--sample_set_json` etc. | n/a | **CAP-SCOPE (b)(e)(f)** | 12b |
| runtime measurement scope | `agent/skills/evaluate_time_skill/wrapper.py:379` builds `TidmadScope` against the **bound** data path | none | in-process | wrong-task scope would `TypeError` at runtime | **CAP-SCOPE — a consumer the Step-11 audit did not list** (verified: `resolve_bound_task_data_path().training_dataset(TidmadScope(...))`) | 12b |
| task composition root | `workflows/task_composition.py` | `--task_composition` on chain + module CLI + `run_one_iteration.py` (P5+P6 W1) | manifest path [P11] to scoring child only | every branch fail-closed; unknown manifest keys refused | **EXT** for its 7 families | 12c extends to all children |
| run-scoped registries/bindings | ContextVars via `bind_run_task_composition` ExitStack (5 binders) | launcher edge | n/a | `verify_composition_is_bound` refuses half-composed runs | **EXT**; but plugin REGISTRATION is process-global with no content ledger (§8 finding) | 12c |
| plugin discovery (models) | `ml_models/plugin_loader.py` + `SIDERIUS_PLUGIN_DIRS` | env / per-run dir; mirrored files | yes (`subprocess_env`) | **FAIL-OPEN**: unknown `PLUGIN_OUTPUT_TYPE` silently coerced to `"classifier"` (`plugin_loader.py:80-87`); loader accepts 3 types, validator 2 (`ml_code_validator_agent.py:368`) — **issue #234, verified OPEN** | **EXT with a graduation-relevant defect** | 12a (#234) |
| plugin discovery (losses) | `SIDERIUS_LOSS_DIRS` | env union | yes | fail-closed | **EXT** | — |
| backend adapters | §22.24.2 | n/a | n/a | n/a | Python only, by design | NLB (doc only) |
| data-root execution binding | master: import-time `TIDMAD_DATA_DIR` (`data_paths.py:20-60`); [P11] `bind_physical_data_root` + argv to all 3 children + `CompositionDataRootMissing` fail-closed | [P11] launcher `--data_dir` via `bind_run_task_composition(…, physical_data_root=…)` | [P11] yes | [P11] fail-closed for composed | **CENTRAL on master → [P11] EXT after Step 11** | 12a pin |
| subprocess env/bootstrap | `core/subprocess_env.py` (3 vars, task-free) | spawner-passed | yes | n/a | **EXT**; two env-less spawners on master (`isolated_probe.py:482-487`, `probe_subprocess.py:336-341`) are [P11] fixed by C1 | 12a pin |
| child-process plugin availability (composition families) | none | none | **NO** for out-of-tree `file:` refs — child registry never learns them | fail-closed (named id error) | **CENTRAL gap — the 12c core** | 12c |
| resume / invariants / fingerprints | `core/run_invariants.py` (11-key `_CANONICAL`, `task_composition_fingerprint` equality-enforced at the workspace lock; omitted-when-None) + `core/resume.py` | stamped at chain level | n/a | `_reject_legacy_runtime_lock` precedent; [P11] R-11-9 3-case record ingress | **EXT**, with residues: the `resume.py` TIDMAD import (REMOVED by Step-11 C8 — closed), **`run_one_iteration.py:1499` `run_scope.resolve(TIDMAD)` (verified live on merged master)**, and F-P56-3 (tuner's per-model `build_run_invariants` at `ml_hyperparameter_tune_agent.py:605-625` passes neither fingerprint nor health binding; narrowed per §0.1-A) | 12a |
| plugin-registry lifecycle layering | `workflows/model_exploration.py:924-967` `_add_plugin_to_registries`; **`core/resume.py:74` module-level private import** (verified) forcing the cycle workarounds at `model_exploration.py:2883-2887` | n/a | process-local, 3 registries | n/a | **CENTRAL layering debt — named Step-12 input (09.5 Q2 = B)** | 12a |
| CLI / composition-root entrypoints | `run_chain.sh` / `_chain_common.sh` / `run_one_iteration.py` / module CLI | `--task_composition` (W1) | n/a | malformed manifest → crash-marked manifest + exit 1 (`run_one_iteration.py:1919-1934`) | **EXT** | — |
| in-tree task manifests / packs | `configs/task_composition/tidmad.yaml` (only shipped one); packs lack task_config/profile/composition (governance pins: no top-level `task_description` YAML under `examples/` until Step 12, `test_pack_governance.py:129-140`) | — | — | — | **IN-TREE, incomplete at L4** | 12d completes packs |
| Pets/DAVIS D14 runners | `scripts/run_pets_gate2.py` / `run_davis_gate2.py` (+`_gate2_health_stage.py`) | direct in-process calls, self-built scopes | **never spawn** | n/a | **LEGACY-ONLY evidence harnesses** (Q-10-5 = B retention contract; retire only when every retained claim has a generic owner) | 12d |
| genericity censuses | §13.1 inventory (task-identity dispatch over 312 files, data-path surface, W1–W7, health-core, ordering scanner, secondaries, pack governance) | — | — | — | standing guards Step 12 extends, never weakens | 12a/12e |

**Matrix summary.** Nine families are already externally extensible with
proven load paths (model plugins, losses, health, metric declaration+impl,
secondaries, interpretation blocks, ModelIOContract, composition root,
run-scoped binding). The graduation blockers concentrate in exactly four
places: **(1)** the CAP-SCOPE family (scope + profile topology + trial
anchoring + peek paths + measurement scope), **(2)** out-of-tree availability
in children, **(3)** composed-path TIDMAD residues (three invariant sites +
the tuner deliverable acquisition + prompt science + #234), **(4)** pack/L4
completion and the final external proof. That is the 12a/12b/12c/12d/12e
partition.

---

## 4. B-class debt re-audit (the formal Step-12 input) + remaining blockers

Per the operator directive: every item the accepted audit assigned to Step
10/12 is re-audited against `c1caa609` (+ the then-provisional Step-11
candidate; every candidate-derived verdict re-confirmed against merged
`e4cd5c18` at §0.1-A), not
re-implemented from the 2026-08-18 table.

### 4.1 The re-audit table

| audit item | 2026-08-18 state | state at `c1caa609` (+[P11]) | verdict |
|---|---|---|---|
| #1 task-config run-scoped binding | editing tracked YAML was the extension path | `bind_task_config` ContextVar override inside `load_task_config` (`workflows/task_config.py:82-84,173-176`); composed runs bind it via the manifest `task_config:` section (P1) | **CLOSED BY STEP 10** for composed runs; the un-composed default-path read is the bounded regime-A adapter and stays |
| #2 ambient TIDMAD fallbacks on the composed path | `resolve_dataset_profile() or TIDMAD_PROFILE` etc. | profile/metric/task-config/data-path all bound at the edge (P1); W4 reference-science guard keyed on composition PRESENCE (`ml_hyperparameter_tune_agent.py:839`); [P11] data root fail-closed | **PARTIALLY CLOSED — four named residues STILL BLOCK STEP 12**: (R1) `run_one_iteration.py:1499` `run_scope.resolve(TIDMAD)` with import at `:56` — the composed pre-flight resolves the workspace lock's `resolved_data_scope` against TIDMAD topology (outside every census surface; **the candidate's delta to this file is only `physical_data_root=` threading — verified**); (R2) ~~tuner deliverable-spec acquisition unconditional~~ — **RE-CLASSIFIED by PR-12a's source audit (A-12a-1) and CLOSED for its NAMING half by Step 11 C6**: `bind_run_task_composition` enters `bind_deliverable_naming` when the task declared one and `derive_tidmad_deliverable_spec` resolves the BOUND value internally, so the tuner's single acquisition site already yields the declared naming with no branch. PR-12a C3 PINS that (differential + reachability, `test_step12_pr12a_c3_deliverable_pin.py`) and corrects the stale source comment; the STORAGE half stays profile-derived and is **Q-12-4 / PR-12b's**, not 12a's; (R3) **F-P56-3** — the tuner's per-model `build_run_invariants` (`:605-625`) passes neither `task_composition_fingerprint` nor `task_health_binding`, so a composed run's per-model lock records `None` and (gates on) re-materializes the effective health config under `LEGACY_OMITTED`. *Rev-2 narrowing (§0.1-A)*: Step 11's F-11-C10-a fix re-pointed both output/record stamps at the run-scoped authority, so the lock's `None` no longer feeds any stamp — what remains for 12a is the lock's own recorded honesty plus the `task_health_binding` kwarg; (R4) the ambient `active_task_data_path()` read pattern — the tuner consumes composition state ambiently instead of on its input (roadmap-carried "→ Step 12") |
| #5 TaskDataPath external loading + transport | module-tail imports; `transport_argv` dormant | loading: manifest `file:`/`module:` (P1, out-of-tree-proven); transport: id emitted when composed (P1 C3), in-tree ids resolve in all 3 children (P5+P6 W3) | **parent CLOSED; child out-of-tree half STILL BLOCKS STEP 12** (12c) |
| #12 tuner regime-A `derive_tidmad_*` | the one true central-edit site | metric: composed-aware with bounded legacy fallback, self-flagged "removing it belongs to Step 12" (`:548-556`); deliverable: the call site is unconditional but resolves the BOUND naming internally (Step 11 C6) | **metric half CLOSED for composed runs** (fallback stays for regime A by design); **deliverable NAMING half CLOSED BY STEP 11**, pinned by PR-12a C3 (A-12a-1); storage half → PR-12b (Q-12-4) |
| #13 metric `plugin_ref` + adapters | no registry, no loader | `_compose_metric`: declaration JSON + `file:`/`module:` implementation ref, five fail-closed branches, out-of-tree-proven (P1/P2b); [P11] scoring child re-composes via `compose_metric_from_manifest` | **CLOSED** (parent by Step 10; child [P11] by Step 11 — 12a pins both) |
| #14 first-class objective-kind promotion procedure | undocumented | unchanged | **STILL OPEN — documentation-only obligation**, owned by 12e's operator docs |
| issue #234 (output-type fail-open + 3-vs-2 vocabulary) | filed, "must be resolved before external composition acceptance" | **both defects verified live**: silent coercion `plugin_loader.py:80-87`; `_LEGAL_OUTPUT_TYPES` 2-member `ml_code_validator_agent.py:368` vs loader's 3 | **STILL BLOCKS STEP 12** → 12a. It is the canonical graduation falsifier: external model plugin with a novel/malformed output declaration must refuse, never silently train as a classifier |
| D16 lexical loss-id refusal | rejects `log_loss` | unchanged (`evaluation_metric.py`; the reason Pets `log_loss` stayed out at P2b) | **STILL BLOCKS STEP 12** (an external task may legitimately declare a `*_loss` evaluation metric) → 12a; the fourth task deliberately falsifies it (§16) |
| D17 scalar-only runtime enforcement | construction-only | unchanged | **NO LONGER LOAD-BEARING for graduation** (composition validates the instance; scoreable⇒scalar is enforced by the Step-06 route) — fix opportunistically in 12a if trivially cheap, else named debt |
| D18 scalar-only per-sample evidence | bridge | typed `PerSampleEvidence` landed (08b D18) | **CLOSED BY STEP 08** |
| resume/dashboard direction literals | Step-10-assigned | golden-ordering scanner standing with `EXPECTED_ORDERING_SURFACE = ()` (P2a; `test_step10_p2a_c0_ordering_scanner.py:415`) | **CLOSED BY STEP 10** (dashboard peripherals stay post-roadmap per D1 row) |
| `core/resume.py:74` private `_add_plugin_to_registries` import (09.5 Q2 = B) | named Step-12 input | verified unchanged; forces the local-import + quoted-annotation cycle workarounds (`model_exploration.py:2883-2887`) | **MUST FIX INSIDE STEP 12** → 12a (move the plugin-registration authority to a lifecycle-owner module; both callers migrate) |
| proposer task-science prompts (roadmap 15.1c "Step 10/12") | open | P3 delivered typed evidence + direction authoring only; the science prose remains hardcoded (§3 row; §4.6) | **STILL BLOCKS STEP 12** (honesty: C-P56-1's class one node over) → 12a |

### 4.2 New findings this design's own audit adds (not in any prior table)

| id | finding | anchor | owner |
|---|---|---|---|
| **F-12-1** | the launcher's composed pre-flight resolves `resolved_data_scope` against the `TIDMAD` constant (R1 above) — for a composed task with ≠20 files the pre-flight lock value and the workflow's profile-derived value (`model_exploration.py:1803-1804`) can disagree | `run_one_iteration.py:56,1499` | 12a |
| **F-12-2** | the runtime-measurement path builds `TidmadScope` against whatever data path is bound — a composed contrast run reaching time estimation raises `TypeError` in production | `agent/skills/evaluate_time_skill/wrapper.py:379` | 12b |
| **F-12-3** | **stale-instance / fresh-digest divergence**: `_compose_task_data_path` re-executes a `file:` plugin, digests the NEW bytes into the fingerprint, then returns the PREVIOUSLY REGISTERED instance when the id already exists (`workflows/task_composition.py:546-547`) — in one process, a second composition after a plugin edit runs the OLD code under the NEW identity. The health family already solved exactly this with its run-scope ledger (`_plugin_binding.py:381-398`) | `task_composition.py:498-560` | 12c (§8) |
| **F-12-4** | parent/child same-authority divergence window: [P11] the scoring child re-composes the metric from the manifest **bytes at spawn time**; nothing cross-checks the child's composition against the parent's pinned `semantic_fingerprint` — a manifest/declaration edited mid-run scores with different semantics under the parent's identity | [P11] candidate `denoising_score_single.py` `--task_manifest` | 12c (falsifier §17-H) |
| **F-12-5** | the planner prompt hardcodes `` `denoising_score` `` **beside** the parameterized `{METRIC_IDENTITY_LINE}` — a composed run's goal line names the wrong metric while the identity line names the right one | `agent/prompts.py:66` (verified) | 12a |
| **F-12-6** | no scanned census covers `sdsc_submission_scripts/run_one_iteration.py` or `core/resume.py` for task-singleton imports (the P1 guard covers only `P1_OWNED_SURFACE` + `model_exploration.py`, `test_step10_p1_c4_extension_proof.py:235-266`) — which is exactly where F-12-1 and the (since-removed-by-C8) `resume.py` TIDMAD token survived | census scope | 12a widens |

### 4.3 What is NOT re-opened

The audit's SATISFIES rows (model registration, probe realization, losses,
history/diagnosis, ModelIOContract, DeliverableSpec-as-representation) were
re-verified as unchanged-or-improved and are not re-opened. The C-class rows
(PRESETS, stale docstrings) stay C-class.

---

## 5. CAP-SCOPE design (the Phase-2 forensic result) and alternatives

### 5.1 What a task-owned scope IS (from source, not doctrine)

All three scopes are small frozen Pydantic value objects naming **which
samples are in play** — and nothing else:

| scope | fields | serializable? |
|---|---|---|
| `TidmadScope` (`tidmad_data_path.py:297-311`) | `sample_set: dict` ({file_index: [segment_indices]}), `seg_size: int` (planner knob), `profile: DatasetProfile \| None` | yes (JSON via model_dump) |
| `PetsScope` (`pets_data_path.py:115-127`) | `rows: tuple[PetsItem, ...]` (image_id, class_index) | yes |
| `DavisScope` (`davis_data_path.py:86-93`) | `rows: tuple[DavisClip, ...]` (sequence_name, start_frame) | yes |

WHERE data lives travels separately (`params.data_dir`); the transform rule is
CODE pinned by probe hashes, deliberately not scope data (`pets_data_path.py`
docstring). Every implementation type-checks its own scope
(`_scope()` isinstance → `TypeError: "the binding and the scope object must
come from the same task"`, `tidmad_data_path.py:327-334`): **scope identity is
already coupled to data-path binding identity by the implementations
themselves.** That observed invariant is the load-bearing input to §5.4.

### 5.2 Producers vs consumers today (complete site list)

| role | site | note |
|---|---|---|
| CONSTRUCT (production) | training child builds `TidmadScope` unconditionally when `main()` passes none | `train_engine_sandbox.py:1125,1246`; `run_experiment_streaming` already accepts generic `task_scope`/`task_eval_scope` params — only the argv boundary is missing (CAP-SCOPE (c)) |
| CONSTRUCT (production) | time-estimation wrapper builds a mini `TidmadScope` | `wrapper.py:379` (F-12-2) |
| CONSTRUCT (tuner, ingredients) | `build_sample_set` trial+formal | `planning.py:397-413` (CAP-SCOPE (b)) |
| CONSTRUCT (harness) | D14 runners build Pets/DAVIS scopes in-process | `run_pets_gate2.py:185-217`, `run_davis_gate2.py:182-213` |
| CONSUME | the four seam methods, `scope: object` | `task_data_path.py:185-204` |

Related TIDMAD-shaped satellites frozen into the same capability family
(P5+P6 §2.5/§10.2, "one capability family with one future design"):
trial anchoring **(e)** (`segment_anchors.json` demanded from
`sandbox.dirs["data"]`, `ml_hyperparameter_tune_agent.py:795-803` — under
[P11] C4 that directory is the COMPOSED data root, so a composed run with
trial mode raises today), health peek paths **(f)** (`execution.py:42` +
`abra_validation_{i:04d}.h5` naming), and profile topology **(d)**
(`dataset_config.py:42-61`).

### 5.3 Field classification, serialization, and what must cross

* **Semantic task configuration** (must cross, must fingerprint-participate
  per-attempt): the sample identity payload (sample_set / rows) and
  task-level knobs the task itself owns (`seg_size`).
* **Execution/runtime state** (must NOT enter the scope): data_dir (crosses
  separately, [P11] `--data_dir`), epoch seed/portion/max_samples (framework
  `EpochSamplingParams`, already cross as argv), device, workspace.
* **Identity** (must cross beside the payload): WHICH implementation decodes
  it. **No new identity is needed** — `--task_data_path_id` already crosses
  and the implementations already enforce scope↔binding pairing (§5.1).
* **Version/schema**: owned by the task package (its scope model IS its
  schema); the framework transports an opaque JSON string + the impl id. A
  task that evolves its scope shape versions it inside its own payload; the
  framework deliberately cannot inspect it (scope opacity, parent D14 §3).
* **Validation**: the impl's own deserializer fails closed (Pydantic), and
  the exact-materialization obligation stays the impl's (unchanged).

### 5.4 The alternatives, compared adversarially

| # | design | verdict |
|---|---|---|
| A | **generic ScopeCodec/ScopeFactory registry** (scope-type id → codec), parallel to the data-path registry | REJECTED. Introduces a SECOND identity (scope-type id) that must be kept consistent with the data-path id forever; its unknown-ref/duplicate/leak semantics duplicate the registry machinery that already exists one seam over; and the operator's Q-11-4 ruling already diagnosed this shape: "a registry only in name … a task-owned scope extensibility mechanism". The observed invariant (§5.1: impls already refuse foreign scopes) says the identities are one |
| B | **task-package-owned scope model + generic symbol/plugin ref in the manifest** (manifest names the scope class; child loads it by ref) | REJECTED as the primary mechanism. It makes the SCOPE TYPE a fifth manifest family with its own load path in every child, when the scope's only legitimate consumer is the data-path implementation that already crosses by id; it also lets a manifest pair impl X with scope-type Y — an error class that cannot exist in D |
| C | **amend the frozen D14 four-method contract in place** (add methods to `TaskDataPath`) | VIABLE but not preferred: it would force every existing implementation (including external ones written against the frozen 4-method protocol) to grow methods, and it edits a FROZEN contract where an additive sibling suffices |
| **D** | **an OPTIONAL sibling capability protocol owned by the same implementation** — scope construction + codec hang off the data-path binding that already crosses | **RECOMMENDED** (§5.5) |
| E | scope schema + self-describing envelope with framework-side dispatch | REJECTED: "self-describing" means the framework reads scope internals — the exact opacity violation D14 froze out |

The forbidden shape is rejected in all branches: no
`{"tidmad": TidmadScope, "pets": PetsScope, "davis": DavisScope}` mapping may
exist in core. Every mutation of §17-D plants exactly that and must turn a
census RED.

### 5.5 The recommended mechanism (12b) — sketch, to be detailed in the child design

```text
TaskScopeCapability (NEW optional Protocol, execute_tools/task_data_path.py
                     or a sibling module — Q-12-2 decides placement wording)

    build_training_scope(request: ScopeBuildRequest) -> object
    build_eval_scope(request: ScopeBuildRequest)     -> object
    serialize_scope(scope: object)   -> str          # JSON, task-owned shape
    deserialize_scope(payload: str)  -> object       # fail-closed
```

* `ScopeBuildRequest` is a frozen framework carrier of FRAMEWORK-level
  selection knobs only — round kind (trial/formal), sampling portion, seed,
  max-samples ceiling, an OPAQUE operator subset ref (see below) — mirroring
  `EpochSamplingParams`' discipline: zero task vocabulary
  (`task_data_path.py:100-103` stays true).
* **Construction** (CAP-SCOPE (a)+(b)): on the composed path the tuner asks
  the bound implementation to build the attempt's train/eval scopes instead
  of `build_sample_set`; the un-composed path keeps `build_sample_set`
  byte-identically (regime A). `TidmadTaskDataPath` implements the capability
  BY CALLING `build_sample_set` — one authority, relocated call, provable by
  a differential oracle (composed-TIDMAD constructed scope deep-equals the
  legacy-built one for identical inputs).
* **Transport** (CAP-SCOPE (c)) — **FROZEN SHAPE (operator amendment,
  2026-08-22): scope payloads do NOT ride argv.** Scope payloads are
  attempt-varying and unbounded (Pets rows, DAVIS clips, future
  variable-length tasks); raw-JSON argv would eventually hit
  `ARG_MAX`/process argv limits, and a graduation-grade framework does not
  ship a transport with a payload-size cliff. The pipeline:

  ```text
  parent:  serialize_scope -> canonical bytes -> sha256 = scope_digest
           -> ATOMIC write to a run/workspace scope artifact
  argv:    --task_scope_ref <artifact path>  --task_scope_digest <sha256>
           (+ the eval-scope pair; additive, composed-only — the
           --task_data_path_id precedent, R-11-1/R-11-13)
  child:   read artifact -> recompute digest -> MISMATCH refuses closed
           -> resolve impl by the id that already crosses
           -> deserialize_scope -> task_scope= / task_eval_scope= into
              run_experiment_streaming (the parameters that exist since
              D14 and have never been argv-fed:
              train_engine_sandbox.py:987-989 + main()'s argv boundary)
  ```

  **Attempt-scope identity is a first-class evidence value** (operator
  amendment): the composition fingerprint is task-level STATIC identity,
  while the scope varies per attempt. The 12b child design must define ONE
  evidence authority for the chain
  `scope payload → canonical bytes → scope_digest → transport → child
  check → record/evidence stamp` — an additive record/evidence stamp is
  acceptable; a persisted-global-schema change is not required — so Gate
  and adversarial evidence can cite WHICH scope a child executed instead of
  inferring it.
* **Capability absence fails closed**: a composed run that needs loop
  training on an implementation without the capability raises a NAMED error
  at composition time (never at first spawn) — the truth-table discipline of
  `resolve_task_data_path` extended one row.
* **Task-instance configuration**: an implementation that needs its own
  sources to build scopes (Pets manifests, DAVIS clip caps) receives them at
  CONSTRUCTION, via an optional task-owned `config:` mapping in the
  manifest's `task_data_path` section passed to the factory — the task's own
  plugin reading the task's own files, which the `examples/`-import census
  never forbids (it forbids FRAMEWORK imports of `examples/`,
  `test_pack_governance.py:211-221`).
* **Satellites resolved in the same child PR**: (d) profile topology is
  **promoted to a formal design ruling — Q-12-4 (opened by the operator
  review, 2026-08-22), with the governing principle FROZEN:**

  > *Generic `DatasetProfile` MAY own genuinely framework-generic model/data
  > facts; task-specific physical/storage topology must either be opaque
  > task-owned config/capability data or live behind an extensible
  > contract. Core must NOT become a union of
  > `TidmadTopology | PetsTopology | DavisTopology | …`.*

  Rev 1's "additive restructuring making TIDMAD fields an optional block"
  is DEMOTED to one candidate shape and is acceptable ONLY where it does not
  reduce to "N optional built-in topology blocks" — that is a central
  catalog with extra steps, explicitly rejected. The 12b child design must
  present the concrete contract satisfying the principle BEFORE 12b
  freezes, auditing every composed-path consumer (`_compose_task_config`'s
  cardinality cross-check, TunerTaskRender's `full_scope_segments`,
  `validate_sample_set`, fingerprints), with TIDMAD's resolved instance
  byte-identical and the Pets/DAVIS fabrications deleted rather than
  blessed. This is the core of whether the fourth task can truly be "unlike
  the first three".

  **Q-12-4 — RULED AT PARENT LEVEL (operator, 2026-08-22): the governing
  principle above is FROZEN; the concrete `DatasetProfile` topology
  contract is intentionally delegated to the PR-12b detailed design**,
  which source-audits and freezes it before 12b implements. No open
  operator question remains on this axis at the parent.

  (e) trial
  anchoring becomes a declared optional task capability (absent ⇒ trial mode
  refused for that task with a named reason, never a crash on a TIDMAD
  filename). (f) the tuner health-peek path derivation flows from the
  deliverable naming authority + composed data root instead of
  `TIDMAD_DATA_DIR` literals. (g) F-12-2: the time-estimation wrapper asks
  the capability for its mini-scope (or skips measurement with a named
  reason when the capability is absent).
* **DataScope (`--data_scope`)** stays TIDMAD/legacy vocabulary: on a
  composed non-TIDMAD run it is REFUSED loudly (it names file indices of a
  topology the run does not have); the opaque subset ref in
  `ScopeBuildRequest` is the generic replacement. Composed TIDMAD may keep
  honoring it through its own capability implementation.

**Q-12-2 — RULED: A (operator review, 2026-08-22).** The capability is the
optional sibling `TaskScopeCapability`; the frozen four-method `TaskDataPath`
body is NOT amended. The transport is the artifact-ref + digest pipeline
above — raw scope JSON on argv is rejected. The D14 parent's "four methods"
language and the roadmap's seam wording receive their recorded amendment in
the Step-12 freeze commit.

---

## 6. External plugin / discovery design (Phase 3)

**What the framework owns** (all already exist; Step 12 extends, never
re-invents): the protocol/ABI per family; the `file:`/`module:` symbol loader
with content digests, collision-proof module prefixes and rollback
(`task_composition.py:396-480`); fail-closed resolution everywhere; the
fingerprint; the run-scoped binding ExitStack. **What it must never own**: a
task catalog. The census families (§13.1) are the executable form of that
rule.

**Findings and dispositions:**

1. **Registration is currently a mix**: composition-driven (data path,
   metric, health — config-named, run-scoped-checked for health only),
   env-driven (models `SIDERIUS_PLUGIN_DIRS`, losses `SIDERIUS_LOSS_DIRS`),
   and one legacy module-tail import family (the three in-tree data paths —
   legitimate as the built-ins' bootstrap, guard-pinned).
2. **Model/loss plugins need no new mechanism for graduation.** Both are
   out-of-tree TODAY with child transport via `subprocess_env`
   (`plugin_loader.py:112,115`; `_loss_loader.py:148-155`). The external
   package documents "set `SIDERIUS_PLUGIN_DIRS`/`SIDERIUS_LOSS_DIRS` to the
   package's plugin dirs" (or the launcher flags that already thread them —
   12e's child design audits the exact operator surface and adds a manifest
   `plugin_dirs:` declaration ONLY if the packaged UX proves it necessary;
   it is not assumed).
3. **The unified loading root already exists** — `workflows/task_composition.py`
   is the "one mechanism" the debt audit told every family to wait for.
   12c's job is to finish its two missing properties: child-side availability
   (§7) and a run-scope content ledger (§8). No new per-subsystem loaders.
4. **#234 is the discovery-layer fail-open** and is closed in 12a: unknown
   `PLUGIN_OUTPUT_TYPE` refuses (loader), and the loader/validator vocabulary
   is reconciled to ONE authority (either both accept `hybrid` or neither —
   decided from the actual consumer branches, recorded in the 12a child
   design; the current disagreement means a plugin legal at load time is
   refused at validation).

---

## 7. Child-process bootstrap design (Phase 4)

**Boundary inventory** (all verified): training child
(`train_engine_sandbox.py`, spawned `sandbox_executor.py:1401-1421` → env
`:1506`), inference child (`inference_single.py`, `:1752-1778` → `:1839`),
scoring child (`denoising_score_single.py`, `subprocess.run` `:2068-2095`),
GPU measurement worker (spec carries plugin/loss dirs; `subprocess_env`,
`gpu_measurement_runner.py:279-284`), preflight/probe workers
(`isolated_probe.py:482-487`, `probe_subprocess.py:336-341` — env-less on
master; [P11] C1 fixes the production-reachable one and records the other).
`multiprocessing` spawn pools in scoring utils inherit interpreter state and
need nothing.

**What crosses today vs what must cross:**

| family | parent | child today | child after Step 12 |
|---|---|---|---|
| model plugins | env dirs | **works** (env + import-time scan) | unchanged |
| losses | env dirs | **works** | unchanged |
| data-path impl | resolved object | **id only** — in-tree ids resolve (W3), out-of-tree ids fail closed by name | 12c: out-of-tree impls resolvable |
| metric | bound instance | master: TIDMAD re-derivation; [P11] re-composed from `--task_manifest` | 12a pins [P11]; 12c generalizes the idiom |
| deliverable naming | [P11] composed | [P11] re-composed from manifest | pinned |
| data root | [P11] bound | [P11] `--data_dir`/`--raw_data_dir` argv | pinned |
| scope | — (CAP-SCOPE) | — | 12b: scope artifact ref + digest + bound-`TaskScopeCapability` deserialization (§5.5 frozen transport) |
| health | parent-only by design | (none — correct) | unchanged |

**The 12c mechanism — extend the idiom Step 11 introduced, don't invent a
second one.** [P11] establishes *manifest-path transport + child-side
per-family re-composition through the SAME authority* (`--task_manifest` →
`compose_metric_from_manifest`). 12c generalizes it:

* the spawn parent emits the manifest path to the training and inference
  children too (additive, composed-only);
* each child that needs the data-path implementation resolves it as:
  transported id → registry lookup → **on miss, compose the
  `task_data_path` section from the transported manifest through
  `_compose_task_data_path` itself** (which registers it and returns it),
  then proceed through the normal truth table. An id that is neither
  registered nor composable from the manifest fails closed with both facts
  named. **A registry HIT is never sufficient by itself** (operator
  amendment, 2026-08-22): even on a hit, the resolved implementation's
  content identity must equal the parent-pinned identity, or a stale
  registration silently satisfies the lookup while running different code.
  No second loader, no env-var plugin path for this family, no child-side
  divergence from the parent's authority (R-11-4's discipline, one family
  over);
* **integrity — PARENT-LEVEL FROZEN INVARIANT (operator amendment,
  2026-08-22):**

  > *Every child-consumed external semantic MUST be validated against an
  > identity pinned by the parent before the child consumes it; a registry
  > hit is never sufficient evidence of identity.*

  The mechanism — per-family transported declaration/plugin digests vs the
  full composition fingerprint — remains the 12c child design's choice;
  "re-read the manifest and trust it" is not an option. This closes
  **F-12-4**: a manifest or plugin edited between bind and spawn must
  refuse, never silently score or train under the parent's identity;
* `cwd` independence: refs resolve against the manifest's directory
  (`_resolve_path`, `task_composition.py:347-353`) and the spawn anchors
  script paths absolutely ([P11] C7) — a child launched from a non-repo cwd
  resolves identically (§17-C falsifier).

Backends stay Python; the capability table in §22.24.2 is referenced in the
operator docs, not implemented.

---

## 8. Run-scoped lifecycle / registration semantics

**The lifecycle contract, corrected by the operator review (2026-08-22).**
Rev 1 carried an internal contradiction: a permanent process-global content
ledger that refuses any different roster would also refuse the LEGITIMATE
next task in the same interpreter — while §17-G simultaneously demands a
`TIDMAD → Pets → external → DAVIS` sequential composition with zero
leakage. The frozen semantics are therefore TWO-PHASED:

```text
WITHIN an active run     same canonical identity + same content   ⇒ idempotent
                         same id + DIFFERENT content (F-12-3)     ⇒ refuse, named error
                         a different roster mid-run               ⇒ refuse, named error
AFTER the run unwinds    the next run may legitimately register a
                         DIFFERENT roster — no permanent poisoning
```

What 12c must build is a **transactional / run-scoped registration overlay**
(or an equivalent restore/visibility mechanism scoped to the composition
binding's ExitStack): registrations made for a run become
invisible-or-retired when the run unwinds, exactly as the ContextVar
bindings already do. The health ledger (`HealthPluginRunScopeError`,
`_plugin_binding.py:106-112,381-398`) is the *refusal-semantics and
canonical-identity precedent* (normalized ref + symbol + content sha, host
paths excluded) — but it is NOT mechanically copied: its `_RUN_SCOPE` is
process-permanent with a test-only reset, which cannot serve heterogeneous
sequential runs. Whether the health family itself migrates onto the new
overlay is a 12c child-design decision (allowed, not required; it must not
weaken any 08b guarantee). Binding is already correct (five ContextVar
binders, token-reset). The `_compose_task_data_path` idempotent-return
branch (`task_composition.py:546-547`) compares CONTENT identity, not just
id, before returning a registered instance — the same-id-different-content
case refuses inside a run and resolves freshly in the next one. Cross-run
falsifiers: §17-G.

The plugin-registry layering debt rides here too: 12a relocates
`_add_plugin_to_registries` (`model_exploration.py:924-967`) to a
plugin-lifecycle owner module so `core/resume.py:74` stops importing a
private symbol from `workflows` (09.5 Q2 = B), dissolving the import cycle
workarounds at `model_exploration.py:2883-2887`. Behaviour-preserving: same
three registries, same callers, one authority.

---

## 9. Resume / fingerprint / compatibility implications

* The identity spine is already right (Agent-verified end to end): manifest →
  `compute_semantic_fingerprint` (semantic values + declaration contents +
  plugin content digests; host paths excluded, `task_composition.py:835-898`)
  → `run_invariants_lock.json` `_CANONICAL` equality set (key omitted for
  legacy, `run_invariants.py:158`, omitted-when-None in
  `write_run_invariants` `:233+`) → workspace-lock validation
  before any prior iteration is touched (`resume.py:1422-1423`) → [P11]
  R-11-9 three-case record ingress + record stamps.
* **12a closes the three residues** (§4.1-R1/R3 + the census hole F-12-6):
  composed pre-flight scope from the composed profile, per-model tuner lock
  carries the fingerprint + health binding, censuses widened over
  `run_one_iteration.py`/`resume.py`.
* **External-package consequences to prove, not assume** (12e): same-task
  resume with unchanged package = legal; edited external plugin bytes ⇒
  fingerprint moves ⇒ resume refuses closed (the 08b property, now for
  composition plugins); package relocation (different absolute path) ⇒ SAME
  identity, resume legal (Q-P1-2); cross-task seed/resume ⇒ refused by the
  fingerprint key; a pre-composition legacy record read by a composed run ⇒
  refused under [P11] R-11-9's named rule.
* Persisted-schema compatibility: Step 12 adds NO new required record fields;
  any new stamps follow the additive default-None idiom ([P11] C8
  precedent). Legacy locks stay byte-identical (omitted-key rule pinned by
  `test_step10_p1_c0_census.py:552-605`).

---

## 10. Structural / modularity audit (Phase 1A)

**Baseline = post-Step-11 master `e4cd5c18`** (mechanical AST re-measure at
the rev-3 closeout — statements / branch-ish nodes / LOC / params; NOT a new
architecture audit). Rev 1's `c1caa609` numbers are superseded; these are
the god-file / function-growth CHECKPOINT values every child PR's pre/post
comparison starts from — each later child compares against this table or
against the previous merged child's recorded post-values, whichever is
newer.

| surface | measure at `e4cd5c18` | Step-12 exposure | rule imposed on the child designs |
|---|---|---|---|
| `run_workflow` (`model_exploration.py:1467`) | 369 st / 143 br / 1,567 LOC / 21 params | 12a threading (composition → tuner input), 12c argv | **sibling-shaped deltas only**; pre/post LOC + branch counts recorded per the P5+P6 §12.1 tripwire; any new branch family extracts first |
| tuner `run()` (`ml_hyperparameter_tune_agent.py:462`) | 257 st / 67 br / 1,085 LOC | 12a (deliverable acquisition, lock kwargs), 12b (scope acquisition) | scope construction is a NEW typed boundary called from `run()`/planning — never inline branching |
| `planning.prepare_attempt` (`planning.py:42`) | 115 st / 32 br / 471 LOC / 7 params | 12b replaces the sample-set half on the composed path | the composed branch delegates to the capability boundary; the legacy branch is untouched bytes |
| `execution.run_admission_preflight` / `run_inference_scoring_health` (`execution.py:129,838`) | 106/36/521 · 110/26/474 | 12b (peek paths (f)), 12a (F-P56-3) | extract the peek-path derivation into the naming authority's consumer; no new branch families in either function |
| `run_experiment_streaming` + `main()` (`train_engine_sandbox.py:985,1750`) | 175/58/728/19 · 86/23/294 | 12b scope rehydration in `main()` | rehydration is a helper module boundary; `main()` gains a call, not a family |
| `core/sandbox_executor.py` (2,534 LOC; `execute_training` 91/38/358/14 at `:1384`) | Step-11 C0/C9 baselines + R-11-11 budget govern | 12b/12c argv emitters | follow `_task_data_path_argv()` shape: small pure emitter functions |
| `restore_prior_state` (`resume.py:1345`) | 99/47/383 | 12a census widening only | no new branch families |
| `denoising_score_single.py` (385 LOC) | module-level script, no `main()` guard; [P11] added top-level manifest handling | if 12c touches it again, wrap a `main()` first (bounded, behaviour-preserving) — the one structural prerequisite, LOCAL to that file | — |
| `workflows/task_composition.py` (1,363 LOC; largest fn `compose_run_task_bindings` 40 st; `bind_run_task_composition` 24 st / 2 params) | healthy | 12b/12c grow it | per-family composer functions stay ≤ the current largest; child-side entries mirror the Step-11 thin-public-entry shape |
| `core/run_invariants.py` (606 LOC; `validate_stamped_invariants` 24/14/101 at `:505`) | grew by Step-11 C3/C8 (calibration recording + R-11-9) | 12a lock kwargs | additive kwargs only; no new branch family in the validator |

**Verdict: no repository-wide structural prerequisite exists and none is
manufactured.** One file-local prerequisite (the scoring child's missing
`main()` guard, only if touched again) plus per-site extraction rules above.
No Step-11.5, no cleanup PR.

---

## 11. PR decomposition (Phase 10) — derivation and recommendation

The operator's five semantic work classes are confirmed real by the audit:

```text
12a  composed-path closure & B-class re-audit   (values + prompts + #234 + layering)
12b  CAP-SCOPE                                   (scope construction/rehydration + (d)(e)(f)(g))
12c  external loading closure                    (child out-of-tree + run-scope ledger + F-12-3/4)
12d  contrast subprocess closure                 (Pets/DAVIS through the real boundary; packs → L4)
12e  out-of-tree graduation                      (fourth task + zero-core-edit census + adversarial suite)
```

Topologies compared (split rule: **a PR split point is a Gate 1 + Gate 2
boundary**; validation economy: the same failure class is not validated
twice):

| topology | shape | verdict |
|---|---|---|
| T1 | one PR | REJECTED. Five genuinely different real failure classes (§14) would share one giant terminal Gate; review of ~5 semantic authorities collapses into one cycle; the operator has inverted the burden of proof |
| **T2** | **five PRs: 12a → 12b → 12c → 12d → 12e** | **RULED — Q-12-1 (operator review, 2026-08-22).** Rev 1's objection to a standalone 12c ("no independent real failure class") is OVERRULED with a better Gate shape: 12c's own failure classes — **F-12-3** stale-instance/fresh-digest divergence and **F-12-4** parent/child semantic divergence — are REAL process-boundary classes provable by a **minimal real-subprocess bootstrap Gate with NO training** (out-of-tree plugin → parent load + identity pin → real child spawn → child load → digest/integrity check). Splitting 12c from 12d is failure-class ISOLATION, not evidence duplication: 12c proves loading/identity; 12d proves real contrast data through training/inference/scoring |
| T3 | four PRs (12c folded into 12d) | rev 1's recommendation — **SUPERSEDED** by the Q-12-1 ruling |
| T4 | three PRs (12b absorbs 12c+12d) | REJECTED: it fuses distinct failure classes and produces the mega-PR pattern Step 10 was decomposed to avoid |

**RULED sequence and dependencies (Q-12-1 = five PRs):**

```text
PR-12a  composed-path closure & re-audit   Gate 1 REQUIRED · Gate 2 REQUIRED
   ↓                                       (default 2×1 composed TIDMAD — §12-12a/§14)
PR-12b  CAP-SCOPE                          Gate 2 REQUIRED (composed TIDMAD through the
   ↓                                       generic scope-artifact path)
PR-12c  external loading closure           Gate 2 REQUIRED (minimal real-subprocess
   ↓                                       bootstrap + integrity; NO training)
PR-12d  contrast subprocess closure        Gate 2 REQUIRED (Pets AND DAVIS bounded real
   ↓                                       chains, BOTH via out-of-tree file: refs)
PR-12e  out-of-tree graduation             Gate 2 REQUIRED (fourth task 2×1 + census
                                           + executed negative controls)
```

Each PR: independent semantic authority, independently reviewable contract,
its own Gate boundary, real implementation risk. Each gets its own child
detailed design (frozen per the kickoff protocol) before implementation; this
parent freezes the split, the contracts, and the acceptance shape.

### 11.1 Inter-PR reconciliation checkpoint (FROZEN — operator, 2026-08-22)

The dominant terminal-phase risk is not a wrong initial design but a later
child implementing against stale assumptions ("12a merged, 12b still holds
three-day-old source beliefs"). Therefore, BINDING on every Step-12 child:

```text
After each Step-12 child PR merges, before the NEXT child design freezes:

1. re-anchor to clean current master;
2. verify the just-merged PR's final SHA / Gate result / exact-head CI;
3. reconcile the next child's assumptions against landed source;
4. update the Step-12 parent implementation/debt/extensibility ledger;
5. re-run the relevant structural baseline (§10) for modules the next
   child will touch;
6. confirm no new load-bearing task-identity branch / central catalog
   was introduced;
7. re-classify any newly discovered debt:
       blocks next child · owned later in Step 12 · post-roadmap debt;
8. initialize a fresh PR Implementation Working Rules context.

This is a BOUNDED reconciliation, not a cross-repository re-audit.
```

The checkpoint is recorded in the next child's design §0 with the anchors it
verified; a child design frozen without it is not validly frozen.

---

## 12. Per-PR plans (8-section format; commit-level checklists live in the child designs, all-`[ ]` at their creation)

**Terminal discipline, binding on EVERY child PR (operator amendment,
2026-08-22):** node/operator doc sync lands BEFORE the final push; ONE
authoritative exact-final-head CI on the merge-candidate SHA; no trailing
production or docs commits after that head (a review change moves the head
and CI re-runs itself). Each child design carries this as an explicit
closing checklist stage.

### PR-12a — Composed-path closure & extensibility debt re-audit

1. **Goal.** G1/G6-partial: a composed run resolves ZERO implicit TIDMAD
   semantics — neither as values (locks, scopes, deliverable spec) nor as
   prompt science — and the ratified B-class set is dispositioned against
   current source with the census widened over the two uncovered files.
2. **Scope.** (i) F-12-1 launcher scope resolution from the composed profile;
   (ii) R2 tuner deliverable-spec acquisition composed-aware (consuming the
   [P11] `deliverable_naming` where declared; legacy branch byte-identical);
   (iii) F-P56-3 per-model lock carries `task_composition_fingerprint` +
   `task_health_binding`; (iv) ambient-read threading: the tuner receives the
   composition (or its needed projection) on its INPUT, with the W4 guard
   keying on that value; (v) issue #234 both halves; (vi) D16 removal/narrow;
   (vii) `_add_plugin_to_registries` relocation (§8); (viii) the LLM-facing
   family: F-12-5 planner literal renders the bound spec id; proposer +
   implementor task-science moves behind caller-supplied task blocks (the 09b
   pattern: framework owns keys/placement, task owns prose; TIDMAD prose
   moves VERBATIM to `configs/task_*` files; manifest gains the
   corresponding optional section(s)); model-description prose rendered from
   the description source, not the five hardcoded lines; lit-review per
   Q-12-3; (ix) census widening F-12-6; (x) re-audit table (§4.1) recorded
   in the ledger with per-item evidence.
3. **Implementation plan.** `[ ]` per-commit checklists in
   `step_12_external_extensibility_graduation/pr_12a_composed_path_closure.md`
   (to be drafted; suggested commit spine: C0 baselines/inverted guards → C1
   invariant-site fixes (i)-(iii) → C2 threading (iv) → C3 #234 + D16 → C4
   layering (vii) → C5 prompt family (viii) with TIDMAD byte-parity
   fixtures → C6 censuses + docs → C7 Gate 1 + ledger).
4. **Validation.** Deterministic: un-composed byte-parity on every touched
   surface (prompt bytes, lock bytes, argv); composed-path differential
   fixtures (Pets/DAVIS/fourth-fixture manifests); mutation plants per §17.
   **Gate 1 REQUIRED** (prompt deltas are LLM-facing; the 09b/P3 Gate-1
   shape: bounded real-LLM probes proving the composed prompts carry the
   task's science and none of TIDMAD's, and legacy prompts are
   byte-identical). **Gate 2 REQUIRED — default disposition (operator
   amendment, 2026-08-22).** Rev 1's "no execution-path semantics change" is
   WITHDRAWN: 12a changes execution/state semantics — pre-flight scope
   resolution, the per-model fingerprint/health lock, deliverable
   acquisition, ambient composition threading, the plugin-lifecycle
   authority. Default: ONE bounded composed-TIDMAD real chain run at
   **2 iterations × 1 round**, whose witness is the per-model lock /
   fingerprint / resume chain across a REAL restore. The child design MAY
   downgrade the depth or the requirement only through an explicit
   semantic-latency analysis proving the changed state is produced and
   consumed inside a shallower window — never by assertion, and the gate
   standard's row is quoted either way.
5. **Acceptance.** Composed non-TIDMAD run: pre-flight lock scope from its
   own profile; per-model lock fingerprint-stamped; deliverable spec from its
   declaration; prompts free of TIDMAD science (probe-verified); unknown
   plugin output type REFUSES; `log_loss` composable as a metric id; legacy
   runs byte-identical everywhere.
6. **Failure/edge cases.** The prompt family is where 09b/P3 found real
   model-behaviour regressions — parity fixtures pin the TIDMAD bytes before
   any prose moves; a Gate-1 FAIL is a design signal, never a tuning target.
7. **Verification commands/evidence.** `[ ]` pending.
8. **Commit boundary.** No scope machinery, no child-loading machinery, no
   pack completion. Strictly the composed-path closure + re-audit.

### PR-12b — CAP-SCOPE

1. **Goal.** G2: the frozen (a)–(f) family (+ (g) F-12-2) closes as ONE
   capability with one design, per §5.5; composed runs construct, transport
   and rehydrate task-owned scopes generically.
2. **Scope.** The `TaskScopeCapability` protocol + `ScopeBuildRequest`;
   tuner composed-path scope acquisition; spawn argv emitters + child
   rehydration; TIDMAD capability implementation delegating to
   `build_sample_set`; Pets/DAVIS capability implementations (manifest-fed
   via task-instance config); (d) profile topology honesty; (e) trial-anchor
   capability declaration; (f) peek-path derivation from the naming
   authority; (g) measurement-scope acquisition; `--data_scope` refusal on
   composed non-TIDMAD.
3. **Implementation plan.** `[ ]` — child design
   `pr_12b_cap_scope.md` (C0 differential baselines incl. the
   composed-TIDMAD scope-equality oracle → protocol + request carrier →
   TIDMAD impl → tuner acquisition → transport + child rehydration →
   satellites (d)(e)(f)(g) → censuses → Gate 2).
4. **Validation.** Deterministic: scope round-trip per task; wrong-task
   payload refused; malformed payload refused; tampered scope artifact
   (bytes ≠ transported digest) refused before deserialization;
   capability-absent composed run refused at composition; un-composed argv
   byte-parity (C0 census, read through R-11-13's wording);
   composed-TIDMAD constructed-scope ≡ legacy-built (deep-equal oracle);
   and an **anonymous fourth-shaped scope-capability fixture** (operator
   amendment, 2026-08-22): a synthetic capability whose scope is
   non-`rows`, non-1-D, different topology — exercised beside the three
   known tasks so CAP-SCOPE is adversarially stressed BEFORE 12e instead of
   being quietly fitted to three known shapes.
   **Gate 2 REQUIRED, and RE-DERIVED to a LIGHTWEIGHT REAL witness by
   §14a (2026-08-23)**: the failure class is *"did the parent-built scope
   cross the real process boundary and get CONSUMED by the correct
   child?"*, and it is fully observable at the training child's scope
   consumption. So the witness is: parent builds scope → atomic artifact +
   digest → **real production child spawn** → child verifies the digest →
   child resolves the correct `TaskDataPath` → child deserializes → the
   real dataset/materialization/training entry consumes that scope →
   evidence recorded. **It STOPS there.** Inference and scoring exercise no
   part of scope transport and are no longer required; the earlier
   "1 iteration × 1 round full chain" framing was inherited from the phrase
   "real chain", not derived from the class. Un-composed parity intact. If
   the production entry point makes a fuller path unavoidable, the child
   design records WHY with the site cited. Gate 1 NOT
   REQUIRED expected — no prompt-byte deltas; pinned executably by a
   prompt-parity test (if Q-12-4's profile work moves any rendered value,
   the disposition is re-derived in the child design, row quoted).
5. **Acceptance.** Zero unconditional `TidmadScope` constructions on the
   composed path (census); the child builds no scope it was not handed;
   Pets/DAVIS scopes serialize/rehydrate bit-stably; fabrication deleted from
   the contrast fixtures; TIDMAD legacy path byte-identical.
6. **Failure/edge cases.** The scope payload is attempt-varying (unlike every
   existing composed value) — the oracle must cover trial AND formal rounds;
   seg_size/planner-knob provenance must not fork into two authorities.
7. **Verification.** `[ ]` pending.
8. **Commit boundary.** No out-of-tree child loading (12c), no real contrast
   spawns (12d), no pack completion.

### PR-12c — External loading closure (child bootstrap + registration lifecycle)

1. **Goal.** G3: an out-of-tree package's composition plugins resolve in
   every required child under a PARENT-PINNED identity, and registration
   follows the §8 two-phase transactional run-scoped lifecycle.
2. **Scope.** Manifest transport to the training and inference children +
   child-side `_compose_task_data_path` resolution under the §7 frozen
   integrity invariant (a registry hit is never sufficient; content
   identity must equal the parent-pinned identity); the F-12-4 integrity
   mechanism (per-family digests vs full fingerprint — chosen and frozen in
   the child design); the transactional/run-scoped registration overlay
   closing F-12-3 (§8); cwd-independence of child resolution.
3. **Implementation plan.** `[ ]` — child design
   `pr_12c_external_loading_closure.md`.
4. **Validation.** Deterministic: the child-resolution truth table
   (registered-with-matching-identity / composable-from-manifest / neither →
   named refusal; **hit-with-divergent-content → refusal**); overlay
   falsifiers incl. heterogeneous sequential runs (§17-B/G);
   cwd-independence; `allow_real_subprocess` bootstrap tests.
   **Gate 2 REQUIRED — the minimal real-subprocess bootstrap Gate (Q-12-1
   ruling)**: an out-of-tree TaskDataPath plugin → parent composes and pins
   identity → REAL child spawn through the production spawner → the child
   loads the plugin → digest/integrity verification witnessed → a
   tampered/edited plugin or manifest REFUSES in the child. **No training,
   no GPU** — the failure class is loading/identity; requiring training
   would blur it into 12d's class and duplicate its cost.
5. **Acceptance.** Out-of-tree ids resolve in all three children under
   pinned identity; every §17-C/G falsifier proven RED-then-GREEN; zero new
   loaders; legacy child bootstrap byte-unchanged; sequential
   heterogeneous-task composition in one interpreter leaks nothing and
   poisons nothing.
6. **Failure/edge cases.** The overlay must not weaken any 08b health
   guarantee (§8); a child that cannot verify identity REFUSES — it never
   proceeds "because the id resolved".
7. **Verification.** `[ ]` pending.
8. **Commit boundary.** No contrast-task execution, no pack completion, no
   fourth task.

### PR-12d — Contrast subprocess closure (Pets + DAVIS L4)

1. **Goal.** G4: Pets and DAVIS cross the REAL spawn/sentinel/rlimit/cleanup
   boundary through the normal composed chain — contrast L4, closing the
   roadmap's Step-12 contrast obligation (§22.12), with 12b as the enabling
   capability and 12c as the loading mechanism. Ideal shape: validation
   plus at most a handful of genuinely GENERIC fixes.
2. **Scope.** Pack completion to L4 (Pets/DAVIS/TIDMAD gain task_config +
   Q-12-4-conformant profiles + shipped composition manifests; governance
   pin (a) relaxed by its owner, `test_pack_governance.py:129-140`, with a
   replacement guard: pack task-config files are CONSUMED via manifests,
   never scanned); runner-claim transfer per the Q-10-5 = B contract (the
   D14 runners' retained claims move to generic-path owners; full
   retirement only when every claim has one). A needed MECHANISM change
   discovered here is routed to its owning subsystem per the §12-12e
   blocking rule — never patched into 12d.
3. **Implementation plan.** `[ ]` — child design
   `pr_12d_contrast_subprocess_closure.md`.
4. **Validation.** **Gate 2 REQUIRED — two tracks** (§22.13 corpus breadth:
   both contrast tracks become executable at this seam for the first time):
   ONE bounded real composed chain run EACH for Pets and DAVIS
   (1 iteration × 1 round, real LLM + real training/inference/scoring
   through the spawn boundary), with **BOTH tracks loading their data-path
   implementations via out-of-tree `file:` refs** (operator amendment,
   2026-08-22 — zero extra training cost, and it proves each contrast task
   individually does not lean on the in-tree bootstrap). Acceptance = the
   children provably consumed the transported binding + scope artifact on
   real task data; rlimit/sentinel/cleanup semantics exercised.
   **NOT criteria**: accuracy/MSE quality, HealthGate PASS (the Pets
   collapse fixture is acceptable evidence), convergence.
5. **Acceptance.** `if task == "pets"` anywhere = design failure (census
   RED); zero task-specific infra edits in the diff (the §18-class census
   applied to the contrast tracks here, before 12e applies it to the
   fourth task); both packs' STATUS.md at honest L4.
6. **Failure/edge cases.** Semantic-latency preflight per the gate
   standard: the witness (child consumed transported binding/scope on real
   data) is produced and consumed within one iteration — 1×1 is sufficient
   depth; a contrast-task quality subsystem must not become an implicit
   criterion.
7. **Verification.** `[ ]` pending.
8. **Commit boundary.** No fourth task, no graduation census finalization.

### PR-12e — Out-of-tree graduation + final systems validation

1. **Goal.** G5 (+G6 closure): the §22.24.3 acceptance — a genuinely
   out-of-tree fourth task package registers, composes, spawns, trains,
   infers, scores, resumes; SIDERIUS core source diff = 0, machine-checked.
2. **Scope.** The external package (selected per §16's criteria; lives
   OUTSIDE the repo; its identifiers appear in zero production source); the
   zero-core-edit census (§18) as a standing repository guard; the
   adversarial/negative suite (§17) rows not owned by earlier PRs; operator
   docs (the task-package protocol guide + the objective-kind promotion
   procedure, audit item #14); execution of the **§18a final validation
   matrix**; the **post-Step-12 cross-system graduation audit** (operator
   amendment, 2026-08-22): after 12e's Gate, re-run the §3 extensibility
   matrix, the structural delta against §10's baselines, the §19 debt
   ledger, the §18 zero-core-edit census, and the four-task evidence
   inventory — the roadmap's Step-12 row is marked COMPLETE only after this
   audit is recorded; then roadmap/§15.1 row updates.
3. **Implementation plan.** `[ ]` — child design
   `pr_12e_out_of_tree_graduation.md`. **No new semantic machinery** — a
   mechanism gap discovered here BLOCKS 12e (operator wording, 2026-08-22):

   ```text
   12e BLOCKS → open a bounded corrective PR against the owning Step-12
   subsystem (already merged by then) → re-validate ONLY the invalidated
   downstream evidence → return to 12e
   ```

   There is no "follow-up commit" into a merged PR's history, and 12e never
   patches the gap itself.
4. **Validation.** **Gate 2 REQUIRED**: the fourth task end-to-end through
   the normal composed chain, bounded **2 iterations × 1 round** — one more
   than the default because the graduation claim includes G6's real restore
   with external plugin digests (semantic latency: fingerprint-pinned resume
   evidence needs a second iteration reading the first's committed state;
   the F-P56-4 lesson). Real LLM + real (small) training. **The restore is
   proven REAL, not asserted from the CLI's iteration count** (operator
   amendment, 2026-08-22): the evidence records process provenance
   (PIDs / process boundaries) showing iteration 2 ran in a fresh process
   consuming iteration 1's committed state. The relocation-equality,
   edited-plugin-refusal and package-removal negative controls are
   **EXECUTED against the real package** in this Gate's evidence set —
   unit proofs alone do not discharge them. **§14a (2026-08-23) bounds
   HOW they execute**: each negative control is discharged by a
   deterministic proof or by the cheap C-class real-subprocess witness, and
   **must not spawn its own training chain**. "Executed against the real
   package" is a statement about the ARTIFACT under test, not a licence to
   re-burn the full workflow per control. The 2×1 stays, for the restore
   claim alone. Gate 1 NOT REQUIRED expected
   (12e changes no prompts; pinned by parity).
5. **Acceptance.** §18 verbatim, plus: the negative control (package
   removed ⇒ named fail-closed refusal), the resume pair (unchanged package
   ⇒ legal; edited plugin ⇒ refused), and the census suite green at the
   final head.
6. **Failure/edge cases.** A graduation run that needs ANY core edit fails
   the step — the edit is evidence of a mechanism gap, routed per §12-12e-3.
7. **Verification.** `[ ]` pending.
8. **Commit boundary.** Validation, package, docs, censuses only.

---

## 13. Deterministic validation plan (Phase 8)

**UNIT owns** (all cheap, all repeatable): registries + truth tables; scope
codec round-trips; fingerprints (inclusion/exclusion, relocation-equality,
edit-divergence); fail-closed branches (every named error in §5-§8); the
zero-core-edit + task-identity censuses (§18, §13.1); mutation guards (§17);
argv construction (emitters as pure functions); prompt byte-parity fixtures;
the composed-TIDMAD scope differential oracle; run-scope ledger semantics;
bounded `allow_real_subprocess`-marker bootstrap tests (real spawn, no
GPU/training). **REAL GATES own** (§14): real LLM behaviour where prompts
changed (12a); real subprocess execution under composed bindings (12b);
real out-of-tree loading + identity integrity under a real spawn (12c);
real contrast data through the boundary (12d); real external package
end-to-end + real restore (12e). No property is duplicated across layers
without an independent reason; no new real-training test enters the unit
tier (the existing timing-flaky family is named debt, not extended).

### 13.1 Standing censuses extended (never weakened)

| census | extension in Step 12 |
|---|---|
| task-identity dispatch, 312 files (`test_step10_p1_c4_extension_proof.py`) | fourth-task identifiers join `TASK_NAMES`; surface unchanged; plants for the new shapes §17-A |
| data-path surface (`test_task_data_path_census.py`) | scope-capability consumption sites join the required set; emitters censused |
| P1-owned singleton-import guard | **widened over `sdsc_submission_scripts/run_one_iteration.py` and `core/resume.py`** (F-12-6) |
| W4 composition-presence guard | re-keyed to the threaded value (12a-iv) with the same forbidden-token list |
| health-core census | untouched (its partition already excludes nothing Step 12 adds) |
| pack governance | pin (a) relaxed BY 12d with a replacement guard: pack task-config files must be CONSUMED via manifests, not scanned |
| ordering scanner / secondaries censuses | surfaces extended over any new files; `EXPECTED_ORDERING_SURFACE` stays `()` |

Census-hygiene rule carried from F-P2b-4: any census extended here is
re-checked for anchored-symbol blindness in the same commit.

---

## 14. Gate plan (Phase 9) — five failure-class families across five PRs (12a carries two bounded runs)

> **AMENDED by §14a (operator ruling, 2026-08-23).** The FAILURE CLASSES
> below are unchanged and none is removed. What changed is COST: `G-12b`
> is re-derived to a lightweight real-subprocess witness that stops at the
> training child's scope consumption, and `G-12e`'s negative controls no
> longer each require their own training chain. **Read §14a's row for a
> Gate before quoting this table's `required real components` column.**
> `G-12a-1` and `G-12a-2` are NOT re-derived — 12a is already executing
> under its own frozen authorization.

| gate | PR | FAILURE CLASS UNDER TEST | required real components | explicitly NOT required | depth + why | isolation | est. cost |
|---|---|---|---|---|---|---|---|
| G-12a-1 | 12a | composed prompts carry the TASK's science (and legacy bytes unchanged) — real-model reading, the 09b/P3 class | real LLM calls, bounded probe set (~≤6 calls); no training | model quality, training, GPU | n/a (prompt-level) | probe harness re-reads persisted prompts | minutes |
| G-12a-2 | 12a | the composed run's LOCK / FINGERPRINT / RESUME chain — pre-flight scope resolution, per-model lock kwargs, threaded composition, plugin-lifecycle authority — across a REAL restore | ONE composed-TIDMAD real chain, **default 2 iter × 1 round** (real training/inference/scoring) | model quality, HealthGate PASS, score magnitude, convergence | 2×1 default — the witness is carried STATE (iteration 2 ingests iteration 1's lock/records); downgrade only via the child design's explicit semantic-latency analysis | quality subsystems isolated by existing switches | ≤ ~45 min |
| G-12b | 12b | the real subprocess boundary transports + rehydrates a task-built scope (spawn/artifact/digest/sentinel path under the new mechanism) | ONE composed-TIDMAD real chain: real training + inference + scoring, 1 iter × 1 round | model quality, HealthGate PASS, score magnitude, convergence | 1×1 — the witness (child consumed the transported scope artifact, digest-verified) is produced and consumed inside one iteration | same | ≤ ~30 min |
| G-12c | 12c | **out-of-tree loading + identity integrity under a REAL spawn** — parent pins identity, child loads, digest verifies; tampered plugin/manifest refuses (F-12-3/F-12-4 made real) | out-of-tree plugin file → real child spawn through the production spawner → child-side load + integrity witness. **NO training, NO GPU** | training, scoring, model quality, contrast data | single spawn cycle — loading/identity has no iteration semantics | n/a | minutes |
| G-12d | 12d | REAL contrast data crosses the same execution boundary (spawn/rlimit/sentinel/cleanup) with task-correct data shapes | Pets real chain 1×1 AND DAVIS real chain 1×1, **BOTH with out-of-tree `file:`-loaded data paths** | accuracy/MSE quality, HealthGate PASS (Pets collapse acceptable), convergence | 1×1 each — single-iteration witness; two tracks because §22.13 corpus breadth applies at the newly-executable seam | same as G-12b | ≤ ~1 h total |
| G-12e | 12e | the WHOLE graduation chain for an unknown external package, including fingerprint-pinned restore | fourth-task real chain 2×1 (real LLM, small real training) + EXECUTED negative controls (removal, edited-plugin, relocation) + process-provenance restore evidence | quality, convergence, benchmark movement | **2×1** — iteration 2 must READ iteration 1's committed state through a real process restart with external plugin digests (semantic latency, the F-P56-4 rule) | same | ≤ ~1 h |

No giant terminal Gate; each Gate's row is re-quoted against
`docs/gates/gate_testing_standard.md` in its child design immediately before
launch, with the readiness packet (SHA, command, taxonomy) written first.
Gate-1 dispositions for 12b/12c/12d/12e are "NOT REQUIRED expected", each pinned
by an executable prompt-parity test, and re-derived in the child design if
any prompt byte moves.

---

## 14a. VALIDATION-ECONOMY AMENDMENT (operator ruling, 2026-08-23)

**Planning amendment. It changes the REMAINING Step-12 validation plan and
nothing else.** It does not touch PR-12a's frozen Gate dispositions, does not
reinterpret G-12a-2 (already launched under its own authorization), and
authorizes no implementation.

### 14a.0 The governing principle, replacing "one Gate per PR"

```text
Gate COUNT is determined by distinct real FAILURE CLASSES.

Gate COST  is determined by the EARLIEST REAL WITNESS sufficient to prove
           that failure class.

"Gate 2" does NOT mean, by default:
    full training + full inference + full scoring + a complete workflow.
```

Three corollaries, each of which the pre-amendment plan violated somewhere:

1. **A PR boundary is not a Gate boundary, and a Gate boundary is not a
   full-training boundary.** A PR may carry no Gate 2, one lightweight real
   Gate, several distinct real witnesses, or a full Gate 2 — decided by the
   changed failure class, never by milestone count.
2. **Non-training does not mean Gate 1.** Gate 1 owns exactly one thing: **real
   LLM behaviour when prompt or semantic rendering changed.** A process-boundary
   property with no LLM and no GPU is still a Gate-2-class witness; it is
   *cheap*, not *Gate 1*. Routing it to Gate 1 would test the wrong thing
   with the wrong instrument.
3. **Stop at the witness.** When a failure class is fully observable at the
   training child's dataset-consumption entry, running inference and scoring
   afterwards proves nothing about that class and costs GPU-hours.

### 14a.1 Four evidence tiers, with strict ownership

| tier | owns | must NOT own |
|---|---|---|
| **deterministic / unit / mutation** | pure semantics · schema truth tables · codecs · fingerprints · content digests · fail-closed branches · task-identity censuses · mutation plants · authority tests · structural deltas · most negative controls | anything whose failure mode lives in a real process boundary |
| **Gate 1** | REAL LLM reading changed prompts / semantic rendering | subprocess, plugin, bootstrap or transport properties — *"it needs no training"* is not a Gate-1 admission ticket |
| **lightweight real Gate (Gate-2 class)** | process boundaries · subprocess bootstrap · environment propagation · out-of-tree availability in a fresh child · identity/digest verification · artifact transport · cleanup/reaping — **provable with no full scientific workflow** | scientific claims about task performance |
| **full Gate 2** | real task data + real training/inference/scoring · persisted state across a real restart · heterogeneous end-to-end execution · final graduation | anything a cheaper tier already proves |

### 14a.2 Topology note — read before applying this section

The operator's current direction is **12a → 12bc → 12d → 12e**, consolidating
the loading/lifecycle work. **§11's frozen ruling is still T2 (five PRs:
12a → 12b → 12c → 12d → 12e), and this amendment does NOT change it** — the
consolidation is a separate decision that must be taken in §11 on its own
merits.

This amendment is therefore keyed on **failure classes, not PR names**, so it
holds under either topology. Where the tables below say **B** and **C** they
mean the §14 failure classes `G-12b` (scope transport) and `G-12c` (external
loading + identity); under the consolidated topology those become the two
distinct real witnesses of one PR, and neither disappears.

### 14a.3 Per-Gate re-derivation

Columns: **sub** = needs a real subprocess · **LLM** · **trn** = real training ·
**inf** = inference · **scr** = scoring · **2×** = needs a second
iteration/restart.

| gate | failure class | cheapest sufficient real witness | sub | LLM | trn | inf | scr | 2× | disposition |
|---|---|---|---|---|---|---|---|---|---|
| **G-12a-1** | composed prompts carry the task's science; a real model reads them | bounded probe set over prompts rendered by production assembly | — | ✔ | — | — | — | — | **UNCHANGED — PASS already recorded** |
| **G-12a-2** | lock / fingerprint / **resume** across a real process restart | composed-TIDMAD 2×1 real chain | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | **KEEP AS FULL GATE — frozen, running, NOT re-derived** (§14a.6) |
| **B** — scope transport | parent-built scope crosses the real process boundary via artifact+digest and is CONSUMED by the correct child | parent builds scope → atomic artifact + digest → **real production child spawn** → child verifies digest → child resolves the correct `TaskDataPath` → child deserializes → **the real dataset/materialization/training entry consumes that scope** → evidence recorded. **STOP THERE.** | ✔ | — | minimal¹ | — | — | — | **KEEP AS LIGHTWEIGHT REAL GATE** |
| **C** — external loading + identity | parent pins an out-of-tree identity → real child starts → child loads/verifies the same implementation → tampered plugin/manifest REFUSES | one spawn cycle through the production spawner | ✔ | — | — | — | — | — | **KEEP AS LIGHTWEIGHT REAL GATE** (already so in §14; re-affirmed) |
| **G-12d** | REAL heterogeneous contrast data crosses the generic execution infrastructure | Pets 1×1 **and** DAVIS 1×1, both with out-of-tree `file:`-loaded data paths | ✔ | ✔ | ✔ | ✔ | ✔ | — | **KEEP AS FULL GATE — both tracks REQUIRED** |
| **G-12e** | whole graduation chain for an unknown external package, incl. fingerprint-pinned restore | fourth-task 2×1 real chain + process-provenance restore | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | **KEEP AS FULL GATE**, with its negative controls demoted (§14a.4) |

¹ *minimal* = the smallest real execution that genuinely consumes the scope —
a real child, real dataset materialization, and a one-batch training smoke if
that is what the production entry point requires. If the source makes a fuller
path unavoidable, the child design records **why**, with the site cited.

### 14a.4 What is removed, and what is deliberately retained

**REMOVED as duplicate or unnecessary evidence:**

| removed | from | why it proved nothing extra |
|---|---|---|
| full `train → infer → score` chain | **B** | the failure class ENDS at the training child's scope consumption. Inference and scoring exercise no part of scope transport; they were inherited from the phrase "real chain" in an earlier draft, not derived from the class |
| the 1×1 *complete-workflow* framing | **B** | a single iteration was already right; what was wrong was assuming "iteration" means the whole scientific pipeline |
| a separate full training workflow per negative case | **G-12e** | plugin tamper · manifest tamper · package removal · relocation equality · unknown ref · malformed declaration are all provable **deterministically or by the C-class lightweight subprocess witness**. Running a training chain per negative control is the same class re-burned |
| re-proving scope/bootstrap mechanics | **G-12d** | discharged by **B** and **C**; 12d exercises them only where the real task path necessarily does |

**RETAINED as independent — do NOT collapse:**

| retained | why |
|---|---|
| **B kept separate from G-12d** (the tempting saving) | deferring B's real witness to 12d buys minutes and costs *failure isolation*: a red 12d could then mean a broken scope artifact, broken external child loading, a broken Pets data path, or a wrong training shape — four candidates, one signal. A few minutes for a real subprocess witness is the right trade |
| **C kept as a real Gate** | deterministic evidence cannot reach the actual process/bootstrap boundary. This is precisely the case §14a.1 exists to name: real, but cheap |
| **Pets AND DAVIS both** | materially different data and task shapes. **Do NOT substitute one representative contrast task** |
| **G-12e's 2×1** | real persisted-state restore requires a real second process reading the first's committed state — the F-P56-4 semantic-latency rule, unchanged |
| **G-12a-2's 2×1** | same rule; 1×1 never re-reads its own lock |

### 14a.5 The fourth out-of-tree task — not weakened

The genuine external-extensibility graduation proof stands. This amendment
re-derives its *cheapest* evidence, it does not convert it into a
registration-only claim: if the acceptance genuinely requires parent discovery
+ child discovery + real execution + real restore, that evidence is retained.
What moves out of the expensive path is only the negative/integrity half, which
deterministic and lightweight-subprocess evidence already proves.

### 14a.6 PR-12a is untouched

G-12a-2 was launched under its own frozen authorization before this ruling.
It is **not** stopped, restarted, shortened, invalidated or re-scoped, and its
acceptance criteria are not retroactively changed. This amendment governs the
REMAINING plan and the final accounting.

### 14a.7 Terminal coverage check (must all hold at Step-12 completion)

| required | owner |
|---|---|
| TIDMAD real Gate-2-level execution evidence | **G-12a-2** (+ B's child witness) |
| Pets real Gate-2-level execution evidence | **G-12d** |
| DAVIS real Gate-2-level execution evidence | **G-12d** |
| external fourth-task graduation evidence | **G-12e**, at the level the final extensibility claim requires |
| parent/child external plugin identity proven | **C** |
| scope transport + rehydration proven in a REAL child | **B** |
| real resume proven where claimed | **G-12a-2**, **G-12e** |
| zero-core-edit proven | §18 census at G-12e + post-Step-12 audit |
| negative / fail-closed properties proven | deterministic + **C** |

And the economy side, which must all be **NO**:

| must be NO | status under this amendment |
|---|---|
| duplicated expensive evidence | NO — B/C/12d/12e own disjoint classes |
| full training where a subprocess witness suffices | NO — removed from B and from 12e's negative controls |
| inference/scoring where the class ended at training-child consumption | NO — removed from B |
| a full Gate repeated because another PR touched the same generic boundary | NO — 12d does not re-prove B/C |

### 14a.8 Remaining expensive real runs after this amendment

```text
BEFORE   G-12a-2 (2x1) · G-12b (1x1 full) · G-12d (Pets 1x1 + DAVIS 1x1) · G-12e (2x1)
         = 5 full training chains + 1 cheap spawn Gate

AFTER    G-12a-2 (2x1, running) · G-12d (Pets 1x1 + DAVIS 1x1) · G-12e (2x1)
         = 4 full training chains + 2 cheap real-subprocess witnesses (B, C)
```

Five distinct real failure classes remain — **none removed**. One full training
chain becomes a minutes-long subprocess witness, and 12e's negative controls
stop each demanding their own chain.


---

## 15. Pets/DAVIS real subprocess closure plan (Phase 5, part 1)

**PLANNED — owner PR-12d** (§12), standing on 12b's scope capability and
12c's loading/integrity mechanism. What it proves: the SAME generic
execution machinery (spawn, argv, env, rlimit 40/60/24 posture, sentinel,
cleanup, deliverable codec, metric route, record/lock stamping) executes
three materially different data shapes; what it deliberately does not prove:
model quality on either task. The D14 runners' retained claims
(real decode→tensor parity, codec round-trip on real bytes,
`comparability == established` on real curves, real Pets-collapse health
verdicts, the DAVIS baseline comparison — P5+P6 §10.4 table) transfer to
generic-path owners as part of this PR; the runner scripts retire only when
every claim has a surviving owner (Q-10-5 = B honoured, not re-litigated).
Pack STATUS/README/composition manifests reach honest L4 in the same PR
(§22.23.8/§22.23.12).

---

## 16. Out-of-tree fourth-task graduation plan (Phase 5, part 2)

**REQUIRED — owner PR-12e.** A copied in-repo task proves nothing (the P1
fixture `spectro_segmentation_v0` is a composition fixture, not a graduation
proof, and its name is already burned into the census). Selection is NOT made
here; the 12e child design selects against these criteria, each tied to the
assumption it falsifies:

| criterion | falsifies |
|---|---|
| lives outside the repository tree; installed/checked out at an arbitrary path; **no file under SIDERIUS** | zero-core-edit reality; relocation-equal fingerprints |
| topology unlike all three tracks (not 1-D 20-file PSD, not RGB image folder, not video frames — e.g. variable-length sequences or tabular groups) | residual `DatasetProfile`/scope shape assumptions (12b (d)) |
| scope vocabulary NOT `rows` of (id, label) | accidental row-shape coupling in anything generic |
| primary metric id containing a `loss` token (e.g. `log_loss`), direction `lower` | D16 removal; direction genericity end-to-end |
| ≥1 observational secondary with the OPPOSITE direction | secondary observational censuses under an external task |
| model roster = its own plugin ONLY (no TIDMAD builtin fits its contract) | builtin-roster and MODEL_DESCRIPTIONS assumptions |
| deliverable format none of the three use | naming/codec genericity ([P11] `deliverable:` family) |
| health = `EXPLICIT_NONE` **or** one external check — whichever the three tracks exercise less at that point | binding-state coverage |
| synthetic, deterministically generatable by a script INSIDE the package; CPU-trainable in minutes | bounded real Gate; no downloads; reproducibility |
| task_description / forward contract / interpretation blocks / (12a) proposer blocks all supplied by the package | the full declared-semantics surface |

The package is also the graduation's negative-control vehicle (§17-B/E) and
the census subject (§18).

---

## 17. Adversarial / negative validation design (Phase 7)

Each row names the mutation/scenario, the expected RED, and the owner. Rows
already owned by standing guards are extensions, not duplicates.

| class | falsifier | expected result | owner |
|---|---|---|---|
| A identity-leak | plant `if task == "external_task"` / `if scope_kind == "pets"` / a fourth-task import in production; plant a scope-class mapping table in core | dispatch census RED per shape; §18 census RED | 12a/12e censuses |
| B registration | unknown plugin id; unknown/missing `file:`; duplicate id; malformed impl (missing protocol method); non-`EvaluationMetric` implementation; **unknown `PLUGIN_OUTPUT_TYPE`** | named `TaskCompositionError`/`TaskDataPathRegistrationError`/refusal — never a default, never `"classifier"` | 12a (#234) + existing branches, pinned |
| C process-boundary | parent resolves, child cannot (manifest transport severed — remove the argv hop); plugin dir omitted from child env; child launched from non-repo cwd; sequential external runs in one process; **registry hit with divergent content** | child fails closed naming BOTH facts; cwd-independent resolution; overlay refusal; identity-mismatch refusal | 12c |
| D scope | valid external scope round-trip; malformed payload; unknown impl id; wrong task's scope payload fed to an impl; capability absent; **tampered scope artifact (bytes ≠ transported digest)**; missing artifact file | codec fail-closed; `TypeError` pairing rule preserved; composition-time named refusal; **digest mismatch refuses before deserialization** | 12b |
| E resume/state | same-task resume (legal); cross-task resume (refused); edited external plugin bytes (refused); package relocated (legal); pre-composition legacy record into composed run (refused, [P11] R-11-9) | per-row exact behaviour | 12a/12e |
| F authority | metric declared externally while a planted core TIDMAD re-derivation is restored (mutation: re-inline `derive_tidmad_metric` in the scoring child) | the [P11] C5 pin / 12a pin turns RED | 12a |
| F authority | deliverable naming declared while the shipped default is force-returned | naming parity census RED | 12a |
| F authority | external data root missing/placeholder | `CompositionDataRootMissing` ([P11]) pinned | 12a pin |
| F authority | secondary metric value injected into an ordering expression | ordering scanner / observational census RED | standing (P2a/P2b) |
| G cross-task sequentiality | TIDMAD → Pets → external → DAVIS composed in ONE process (deterministic, pseudo-execution): assert zero binding leakage after each unwind, MID-RUN roster/content change refuses, and the NEXT run's different roster is LEGAL (§8 two-phase overlay — both halves falsified) | ContextVars empty between runs; in-run refusal named; post-unwind heterogeneous registration succeeds | 12c |
| H mutation (transport hops) | sever each hop one at a time: scope artifact writer / ref-argv emitter / digest emitter; manifest argv emitter; child re-composition call; child identity check; fingerprint stamp; per-model lock kwargs; **the F-12-4 window** (edit the manifest or plugin between bind and spawn) | ≥1 named test RED per severed hop; the F-12-4 edit refuses at the child integrity check | 12b/12c/12d |
| anti-vacuity meta | every census plant asserted count==1, cache-cleared, baseline re-run (mutation-proof hygiene) | recorded per plant | all |

Load-bearing claims → executable falsifiers (the anti-vacuity table the
operator required): "external plugins are discoverable in children" → sever
child bootstrap (H); "scope rehydration is generic" → plant the built-in
scope switch (A/D); "zero core edit" → plant the fourth task in a central
import list (A + §18); "run-scoped lifecycle" → leak a registration across
runs (G); "same semantic authority parent/child" → F-12-4 edit + re-inlined
derivation (F/H).

---

## 18. Final zero-core-edit acceptance criterion (Phase 6) — executable

```text
BASELINE   clean SIDERIUS tree at the candidate SHA (git status --porcelain empty)
EXTERNAL   the fourth-task package at an arbitrary OUTSIDE path, supplying its
           manifest + declarations + plugins (data path w/ scope capability,
           metric(+secondary), model plugin, objective config, health
           statement, task config, interpretation/proposer blocks)
ACTION     the normal operator surface only:
           run_chain.sh … --task_composition <pkg>/composition.yaml
                          --data_dir <pkg data> (+ documented plugin-dir surface)
RESULT     workflow exit 0; real children spawned; training/inference/scoring
           executed; records + lock stamped with the package's metric id and
           semantic fingerprint; iteration-2 restore consumed iteration-1
           state (G-12e)
CORE DIFF  zero SIDERIUS production-source edits
```

Machine-checked, not asserted:

1. `git status --porcelain` empty before AND after the run (no production
   file created/modified); recorded in the Gate evidence.
2. A sha256 manifest over the nine production dirs
   (`PRODUCTION_DIRS`, `test_step10_p1_c4_extension_proof.py:43-53`) equal
   before/after.
3. The standing census suite green at the same SHA with the fourth task's
   identifiers added to the forbidden sets: package name, task id, scope
   class name, metric id appear in ZERO production source (the
   `TestTheFourthTaskIsUnknownToTheFramework` shape, re-pointed).
4. The run's own artifacts prove execution through generic contracts (child
   argv captured; record metric stamps = the package's declaration;
   fingerprint present in the lock).
5. Negative control: with the package path removed, the same command fails
   closed with the composition's named error — proving the run actually
   depended on the external package.

A task that requires adding an import, a registry row, an enum member, or a
central YAML edit inside SIDERIUS **fails graduation**; the diff itself is
the counter-evidence.

---

## 18a. Step-12 final validation matrix (terminal contract; operator amendment 2026-08-22)

The minimal falsifiable evidence set across the required axes — every cell
names its MINIMAL independent evidence owner; no Cartesian sweep. `det` =
deterministic (unit / `allow_real_subprocess` marker) · `G-x` = the §14 Gate
owning the real half · "standing" = an already-green census cited, not
re-proven. 12e executes this matrix as part of its scope; the post-Step-12
graduation audit re-verifies it at the final head.

| axis \ task | TIDMAD | Pets | DAVIS | external fourth |
|---|---|---|---|---|
| composition resolves + binds (parent) | standing (P1 suite) | det (12d manifests) | det (12d manifests) | det (12e) + G-12e |
| in-process execution semantics | standing suites | det + retained L3 runner claims until their 12d transfer | same | det (12e fixtures) |
| real subprocess execution | G-12a-2 (lock/resume chain, full) + **G-12b** (scope path — **lightweight**, stops at child scope consumption per §14a) | **G-12d** (full) | **G-12d** (full) | **G-12e** (full) |
| child discovery — in-tree ids | standing (W3 census) | standing | standing | n/a |
| child discovery — out-of-tree + identity integrity | **G-12c** | G-12d (`file:` ref) | G-12d (`file:` ref) | G-12e |
| scope build / serialize / artifact / rehydrate | det oracle (12b) + G-12b | det (12b) + G-12d | det (12b) + G-12d | det (12b **anonymous fourth-shaped fixture**) + G-12e |
| full composed workflow (real LLM) | G-12a-1/-2, G-12b | G-12d | G-12d | G-12e (2×1) |
| resume — same task | **G-12a-2** (real restore) + det | det | det | **G-12e** (real restore, process provenance) |
| resume — cross-task / edited plugin / relocation | det (12a/12c) | det | det | **EXECUTED controls in G-12e** — deterministic or C-class subprocess witness, never one training chain per control (§14a.4) |
| failure modes (unknown ref · missing package · malformed/tampered scope · wrong pairing · missing data root · bootstrap failure · cross-run leakage) | det — every §17 row RED-proven | det | det | det + G-12e negative control |
| architecture (zero identity branches · zero central catalog · zero core edit · one owner per declaration · no new god function) | §13.1 censuses + §10 structural deltas, at EVERY PR head | same | same | §18 census at G-12e + post-Step-12 audit |
| compatibility (legacy byte-parity per R-11-13 · locks · prompts · records · CLI) | det parity fixtures, at every PR head | n/a (no legacy Pets path exists) | n/a | n/a |

---

## 19. Debt triage (Phase 12)

| disposition | items |
|---|---|
| **BLOCKS STEP 12 (prerequisite)** | none. Step-11 merge is a sequencing prerequisite for freeze (§20), not a debt. **No Step 11.5 exists or is created** |
| **MUST FIX INSIDE STEP 12** | CAP-SCOPE (a)–(g) incl. Q-12-4 + the scope artifact/digest transport → 12b · child out-of-tree availability + the transactional run-scoped overlay + F-12-3/F-12-4 under the §7 frozen invariant → 12c · composed-path residues F-12-1/R2/F-P56-3(narrowed, §0.1-A)/ambient-threading + census hole F-12-6 → 12a · issue #234 → 12a · D16 → 12a · `resume.py:74` layering (09.5 Q2 = B) → 12a · proposer/implementor/planner prompt-science family + F-12-5 → 12a · pack L4 completion + governance-pin relaxation → 12d · objective-kind promotion procedure DOCS (#14) + the §18a matrix execution + the post-Step-12 graduation audit → 12e |
| **SHOULD FIX BEFORE FINAL GRADUATION (cheap, inside an owner PR; dropped without ceremony if not)** | D17 runtime scalar refusal (12a, if trivial) · the interpreter node-CLI unconditional legacy `task_blocks` load (`result_interpretation_agent.py:1308` — Regime-A entry; add the composition-aware branch if 12a touches the file) |
| **NAMED POST-ROADMAP DEBT (explicitly deferred, with reasons)** | import-time data-root template REMOVAL (R-11-8: repo-wide CI collection dependency) · five OOM matchers (F-11-9) · device-0 selection (F-11-10, operator-surface feature) · D1 frozen record-key renames (`denoising_score` et al.) · dashboard/peripheral direction literals (D1 row) · lit-review full prompt genericization beyond Q-12-3's bounded ruling · `run_comparison.py` composition (Q-P1-1) · PRESETS register-or-retire · stale registration docstrings · timing-sensitive real-training tests in the unit tier (not expanded by Step 12) · anchored-census hygiene as a repo-wide sweep (stays per-census-when-touched, F-P2b-4) · auto-resume `START_ITER` stdout corruption (P5+P6-carried, workaround documented) |
| **OUT OF SCOPE** | execution backends beyond Python (§22.24.2) · new tasks beyond the graduation fourth · any TIDMAD science change |

Promotion rule applied throughout: an item is promoted only if its absence
makes the external out-of-tree graduation false, fragile, or dishonest.

---

## 20. Implementation ledger / freeze prerequisites

*(empty — implementation has not started; every checkbox in §12 and the child
designs starts `[ ]` and no evidence line is filled before the work runs.)*

**Freeze prerequisites (ALL must hold before Revision N is FROZEN):**

- [x] **Step 11 MERGED and the bounded reconciliation DISCHARGED**
      (2026-08-22, §0.1-A): PR #247 squash `da2aa705`, final PR head
      `fd6bfccb`, final executable head `88f190a1` with exact-head CI
      `32562135614`, master `e4cd5c18`. Every `[P11]` fact re-verified
      against merged source; R-11-13 and R-11-14 absorbed; F-11-C10-a's
      narrowing of F-P56-3 recorded; F-12-1 confirmed still live and
      12a-owned.
- [x] **Q-12-1 RULED** (five PRs) and **Q-12-2 RULED** (A — sibling
      `TaskScopeCapability` + artifact/digest transport) — operator review,
      2026-08-22, recorded in §0.1-B/§5/§11.
- [x] **Q-12-3 RATIFIED and Q-12-4 RATIFIED AT PARENT LEVEL** (operator,
      2026-08-22, rev-3 closeout): Q-12-3 = the evidence-backed fail-closed
      disposition for the optional lit-review path (§0.1-B item 8); Q-12-4 =
      principle frozen, concrete `DatasetProfile` contract intentionally
      delegated to the PR-12b detailed design (§5.5). **Open semantic
      operator questions: 0.**
- [x] Roadmap + D14 wording synced IN the rev-3 freeze commit: the Step-12
      row's doc filename corrected to this document; the row's CAP-SCOPE
      prerequisite annotated with its assigned owner (PR-12b; remains OPEN
      until 12b merges); the D14 parent carries the recorded Q-12-2 = A
      amendment (frozen four-method contract + optional sibling
      `TaskScopeCapability`).
- [x] **Sequential child-design rule (REPLACES rev 2's
      all-five-drafts-before-freeze requirement — operator, 2026-08-22):**
      *Each child PR MUST have a fresh detailed design frozen before THAT
      child's implementation begins. Later child designs SHOULD be
      drafted/reconciled against the merged truth of all preceding Step-12
      children (via the §11.1 checkpoint) rather than being prematurely
      frozen against the parent base.* Child docs live at
      `step_12_external_extensibility_graduation/pr_12{a,b,c,d,e}_*.md`,
      each with per-commit 8-section all-`[ ]` checklists per the
      operator's standard (Goal · Scope · Implementation plan · Validation
      plan · Acceptance criteria · Failure/edge cases · Verification
      commands/evidence · Commit boundary), its own Evidence Economy
      section, Gate-standard row quotes, and the §12 terminal-discipline
      closing stage. **The next action after this freeze is the PR-12a
      detailed design** — nothing else is drafted ahead of need.
- [x] Final consistency/adversarial sweep of Revision 3 recorded
      (2026-08-22): stale `--task_scope_json` row corrected (§7); zero
      `12cd` references outside historical records; anchors in the five
      Step-11-touched files refreshed against `e4cd5c18`; §10 baseline
      re-measured; no material finding — freeze proceeds under the
      operator's conditional authorization.
- [x] No implementation and no Gate launched from the design sessions.

**APPROVED 2026-08-22 — LIVE PARENT LEDGER (updated as each child PR
completes; not an immutable freeze).**

Child-design ledger: **PR-12a detailed design REVISION 2 — FROZEN,
operator approved 2026-08-22** (`pr_12a_composed_path_closure.md`; its §2
audit re-classified three parent §4 rows — deliverable naming half
closed-by-Step-11, F-P56-3's health half confirmed real, layering fix as
consolidation). PR-12b design follows the §11.1 checkpoint after 12a merges.

**PR-12a — COMPLETE / MERGED (2026-08-23).** PR #248, squash
**`15554174`** (`1555417464bb48982b813458c08a113be60c6c37`); final executable
head **`ec30bd65`** (where G-12a-2 ran); final PR head **`d4bf899d`** with
exact-head CI **32615196536 SUCCESS**; local master verified identical to
`origin/master` at the squash SHA.

```text
G-12a-1   PASS   SHA f542e89e   4 real calls of a 6 cap
G-12a-2   PASS   SHA ec30bd65   attempt 4 canonical; A1/A2/A3
CI        SUCCESS 32615196536   on the exact final PR head d4bf899d
```

Operator terminal review 2026-08-23 returned **APPROVE WITH SMALL CLOSEOUT
FIXES**, ratifying four substantive items: the TIDMAD composition fingerprint
move (fail-closed resume intended, **no compatibility bypass**), C7-5's
`ProposalTaskBlocks` key growth as an **in-scope completion of D-12a-6**,
F-12a-G2 as implemented (not to be broadened), and attempt 4 as the canonical
G-12a-2 PASS. A **BOUNDED TERMINAL-EQUIVALENCE EXCEPTION** was granted for
this PR's `ec30bd65..870897c6` delta, which was **not literally docs-only** and
was accepted on proven execution-inertness — **explicitly not a generic
relaxation of the Step-12 terminal rule** (child §8.23/§8.24).

Two things that must not be claimed from the Gate: that the chain ran
uninterrupted (it was killed mid-run after a provider hang and resumed at
iteration 2 in the same workspace), and anything about provider-hang
robustness.

The child doc's §8 remains the evidence authority. What the parent carries
forward:

* **Every §4 residue this child owns is closed**, and the composed path
  resolves no implicit TIDMAD semantics as VALUES (pre-flight scope topology,
  per-model lock identity, health materialization, deliverable naming) or as
  PROMPT SCIENCE (planner, reflector, proposer, implementor).
* **ONE ratified deviation from the child's frozen §0.1**: **D-12a-9**
  (`ImplementorTaskBlocks` + `ImplementorInput.implementor_blocks` + an
  optional manifest `implementor_blocks:` section). C7-4 STOPPED as a material
  deviation because the child's ratification enumerated the proposer family
  and not the implementor's, while this parent's §12-12a-viii names both; the
  operator authorized **Option A** as a bounded contract correction on
  2026-08-22. The R-11-14 rule held: the expansion was raised and priced, not
  discovered afterwards.
* **The shipped TIDMAD composition manifest now declares `proposal_blocks:`
  and `implementor_blocks:`, so its semantic fingerprint moved**
  `d6628a93…` → `9125bf58…`. A composed TIDMAD run started before 12a fails
  its resume closed — designed behaviour for a composition that gained two
  declared sources, and the affected population is the Step-10 P5+P6 and
  Step-11 Gate runs. Declaring nothing was the alternative, and it would have
  meant a composed TIDMAD run proposing and implementing with no science at
  all (child §8.16, F-12a-C8-1).
* **NOT claimed and unchanged**: CAP-SCOPE (still the frozen prerequisite for
  contrast-track L4 — 12b), external child loading / registration overlay
  (12c), Pets/DAVIS L4 (12d), a fourth task (12e).
* **New debt recorded for the later lifecycle PR**: the pre-existing global
  process-registry test-order fragility, CLOSED as **CASE A** by
  operator-directed forensic — not introduced by 12a and not CI-reachable —
  with its exact reproducer and baseline SHA recorded in child §8.12 as a
  regression falsifier.
* **Named debt carried forward by PR-12a, none solved here**: **Q-07c-6**
  (admission prices `phase="training"` only; it killed G-12a-2 attempt 2) ·
  registration-order **CASE A** · **F-12a-G2b** (the usable VRAM cap derives
  from TOTAL rather than currently-free memory, so it over-promises on a
  shared GPU) · **partial-calibration acceptance + a true probe watchdog**
  (deferred because the descending batch search cannot derive a conservative
  successful batch from larger-batch failures without changing the algorithm)
  · **CAP-SCOPE** · **external child loading** · **Pets/DAVIS L4** ·
  **fourth-task graduation**.
* **§14a (validation economy) stands** — Gate count by failure class, Gate
  cost by earliest sufficient witness, keyed on failure classes because §11's
  frozen topology is still T2.

**NEXT — owned by the isolated Step-12 planning session, NOT by any
implementation session**: re-anchor the provisional PR-12bc design against
LANDED PR-12a source and perform the mandatory post-merge delta reconciliation
(§11.1) before 12bc freezes. No 12bc design decision is taken here.

**PROVISIONAL STEP-11 FINDINGS — ALL RESOLVED at the reconciliation
(§0.1-A):**

| id | finding (rev 1) | resolution at merged `e4cd5c18` |
|---|---|---|
| P11-1 | child-side manifest re-composition exists for metric + naming (C5/C6) | **HELD** — `--task_manifest`, `denoising_score_single.py:108,212-216`; §7's 12c mechanism stands on it |
| P11-2 | data root is a launcher binding (`--data_dir` → binder kwarg), not a manifest key | **HELD** — `task_composition.py:1223`; fail-closed via `CompositionDataRootMissing`; 12a pins |
| P11-3 | `run_one_iteration.py:1499` TIDMAD scope-resolve not in the candidate's delta | **CONFIRMED on merged source** — F-12-1 stays 12a's |
| P11-4 | Gate 2 in flight at draft time | **RESOLVED** — Gate-2 FINAL PASS at `88f190a1` (Step-11 doc §11d); F-11-C10-a fixed (both stamps read `active_composition_fingerprint()`, dead `RunBindings` field removed, AST-pinned); R-11-13 + R-11-14 recorded as operator rulings and absorbed (§0.1-A) |
