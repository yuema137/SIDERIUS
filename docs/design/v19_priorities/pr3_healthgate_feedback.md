# PR 3 — Propagate Structured HealthGate Evidence into Downstream Agent Context

- **Status**: LOCKED (P3-D approved by operator, 2026-07-28, at rev 4).
  Revision history: rev 2 (Q1–Q4 + behavioral-claim precision + pilot
  diagnostic arm + genuine-use rubric + deterministic history flow),
  rev 3 (per-iteration occurrences, degraded-merge invariant, source
  identity, CB1 import-graph audit), rev 4 (CB5 three-case workspace
  contract, representative-observation raw-metric provenance). All
  recorded in §9. Changes to locked decisions require an explicit
  operator revision.
- **Baseline**: [`../v19_priorities.md`](../v19_priorities.md) §2.0 (PR 3 exit
  contract + progress checkpoints), §2.1 (feedback-propagation remainder),
  §4 (validation standard). This document is the PR-specific design the
  baseline requires; it must answer the §4.3 question list and carry the
  §4.4 budget table before any evaluation launches.
- **Validation class**: agent-behavior (§4.1) — Layers 1, 2, and 3 of §4.2
  are ALL mandatory for the top-level work item. Layer-1 deterministic
  plumbing may merge behind a disabled/recording-only boundary (§4.5);
  the top-level PR 3 checkbox stays `[ ]` until Layers 2–3 are reviewed.
- **Predecessors**: V18 PR #124 (condensed run-level health-validity
  propagation — landed); V19 PR 1 (chain incumbents — merged `6678d19`);
  V19 PR 2 (ordering provenance — merged `2c1a0b6`, whose `RoundOrdering`
  per-round summary pattern this design reuses).

## Development principles

Carried from the PR 1/PR 2 process (operator rules):

1. Check code before asking; never guess.
2. Update this doc incrementally — mark `[x]` with evidence as each item
   completes; never batch at the end.
3. Stop-and-show before every commit; pytest runs freely EXCEPT real-LLM +
   real-training.
4. Split large planned commits at clean boundaries.
5. Read the relevant section before touching any existing file.
6. Flag design ambiguity explicitly; propose options; wait.
7. On test failure: read the full traceback, report diagnosis (test bug vs
   production bug) BEFORE any fix.
8. Node/skill doc sync before merge (CLAUDE.md operator rule 2026-07-28).
9. Gradual genericization in-passing (baseline §1.3) — bounded, own commit,
   never big-bang.
10. Cold-start rule for all real-training gate runs (no `--seed_paths`).

## 0. Implementation progress

```text
[x] P3-D   — design approved and locked (operator, 2026-07-28 — rev 4;
             approval message: "The rev-4 design is now internally
             consistent and sufficiently bounded for implementation
             planning")
[x] P3-CA  — pre-implementation audit COMPLETE (2026-07-28/29,
             operator-accepted). Evidence in §2.5: three real artifact
             vintages probed (raw-JSON key presence); legacy signal =
             model_fields_set field presence, never list emptiness;
             error-status lifecycle table with code locations (gate
             call :3157 vs each error-write site; error_scoring
             nuance documented); import graph traced — canonical home
             health_checks/schemas.py, minimal extractions of
             severity_of + CandidateHealthValidity accepted, acyclic;
             model_type confirmed as history key, source_exp_ids =
             latest 8/bucket; record order verified chronological
             across persistence/replay; nested metric paths from real
             V17 payloads; configuration + lock names finalized; CB1
             file list fixed (§6). Provenance taxonomy left extensible
             per operator direction — smallest typed model chosen at
             CB1/CB2 under the §3.2 governing rule.
[x] P3-CB1 — commit block 1 COMPLETE (2026-07-29): extractions
             `153ec72` + health_feedback module `f2dcbf7`; 39 new
             tests; CI green incl. first pyright pass (§11-CB1
             evidence)
[x] P3-CB2 — commit block 2 COMPLETE (2026-07-29): `f3a0b8c`;
             RoundHealth into ModelRunSummary; 12 new tests over the
             three real artifact vintages (§11-CB2 evidence)
[x] P3-CB3 — commit block 3 COMPLETE (2026-07-29): goldens `23c3fbe`,
             deterministic outputs + degraded-merge `e4cb62b`,
             flag-gated rendering `2052fa2` (+ pyright annotation fix
             `394ec86`); byte-identical flag-OFF parity vs pre-change
             goldens; 21 new tests (§11-CB3 evidence)
[x] P3-CB4 — commit block 4 COMPLETE (2026-07-29): goldens `66efed8`,
             proposer [HEALTHGATE EVIDENCE] block `4b04723`; §14.N
             pinned byte-identical; 15 new tests (§11-CB4 evidence)
[x] P3-CB5 — commit block 5 IMPLEMENTED + validated (2026-07-29,
             operator-revised a/b/c boundaries): CB5-a lock policy +
             tuner pass-through `76f602a`; CB5-b workflow/resume carry
             `4d5390e`; CB5-c chain CLI + stamps + lock-collision
             closure + all-three-sites regression + the three
             workspace cases — implemented, 31 new tests green, block
             regression 980 passed; CB5-c commits pending
             stop-and-show approval (§11-CB5 evidence)
[x] P3-V1  — RESTORED after reopen-fix (2026-07-29): verdict PASS
             WITH DOCUMENTED LIMITATIONS. Reopen history: the blocking
             claim "structured evidence reaches the production
             proposer" was CONTRADICTED in pipeline mode — CB4 spliced
             the block into _build_reasoning_prompt (legacy 2-call mode
             only) while production uses _run_pipeline's template
             assembly (source :481); every proposer-prompt test had
             validated the non-production path (the audit's own
             false-positive pattern; found by the L2p call-count
             design). Fix: healthgate_evidence_block template variable
             mirroring the §14.N mechanism ("" when OFF/no evidence) +
             the {healthgate_evidence_block} placeholder in
             proposing_stage.md — the narrowest production stage (the
             JSON-emitting final stage; audit: the §14.N placeholder
             exists ONLY there, explore/exploit files are injected
             fragments, earlier stages would duplicate context).
             Corrected claim-G evidence (production path, direct):
             test_health_evidence_pipeline.py 6 passed 0.96s — real
             MLModelProposalAgent.run() pipeline with captured stage
             prompts: flag-ON exact fingerprints/attribution/window
             counts/representative metrics in the ACTUAL proposing-
             stage prompt; block in EXACTLY one stage; §14.N inside the
             prompt byte-identical and ordered before it; flag-OFF no
             leak + placeholder substituted + byte-identical to a
             legacy-payload prompt; legacy dict + flag ON renders
             nothing. Cross-iteration production path:
             workspace Case-1 pipeline variant — iter-1 record → digest
             → typed restore → iter-2 REAL pipeline proposing-stage
             prompt contains the fingerprint with iteration tags 1, 2
             (5 passed 1.12s). Regressions: proposer+protocols+schemas+
             workflows 1029 passed 13.13s; repo ruff + format clean.
             _build_reasoning_prompt evidence is NOT counted for this
             claim. Original closure evidence retained below (all
             non-G claims unaffected):
             Layer-1 deterministic validation had reported (2026-07-29):
             verdict PASS WITH DOCUMENTED LIMITATIONS. Full unit suite
             4617 passed / 4 xfailed / 216.20s locally (repo venv);
             CI run 30472894670 head 14f2891 SUCCESS — ruff clean,
             format clean, pyright strict 0 errors (CI is the
             type-check source of truth; not runnable on lilab),
             pytest 4617 passed / 1 skipped / 3 xfailed / 269.73s.
             Local-vs-CI count difference explained: the issue #138
             Path-A reference test runs+xfails on lilab (real data
             present) and skips on CI (data absent) — 4 xfailed vs
             3 xfailed + 1 skipped, same test, environment-dependent
             mode, no regression. Claim-to-evidence matrix in §7.1a:
             all 12 operator categories (A-L) directly proven; 4 audit
             gaps closed by test_health_feedback_p3v1_audit.py (6
             tests). Branch diff audited d811226..HEAD = exactly the
             §6 file list. Limitations (do NOT hide gaps): (1) Layer 1
             proves delivery + deterministic persistence ONLY — no
             behavioral-improvement claim; (2) the interp→propose
             pseudo full-loop lives in tests/unit as composed
             mock-LLM tests, not the tests/integration dual-mode
             harness (functionally equivalent); (3) real-environment
             chain execution deferred to P3-L3; (4) two CI-red rounds
             during CB3/CB5 (pyright annotation, ruff format) were
             mechanical, fixed same-day, final state green.
[x] P3-DOC — node/skill .md sync + operator-surface docs COMPLETE
             (2026-07-29): result_interpretation_agent.md (input flag +
             retention knobs + typed history rows; three deterministic
             output-field rows; recording-vs-rendering behavioral note
             incl. degraded invariant, one-way history flow, lock/resume
             semantics); ml_model_proposal_agent.md (input flag row;
             [HEALTHGATE EVIDENCE] note covering BOTH modes — legacy
             splice + production pipeline template variable in
             proposing_stage.md); ml_hyperparameter_tune_agent.md
             (three pass-through rows stating lock+stamp-only with the
             two-references regression note; run_config policy-stamp
             note); docs/running_chain_test.md (three-flag table with
             defaults off/3/8, startup validation, resume-rule and
             legacy-workspace paragraphs, where-to-look-afterwards).
             Every flag and default cross-checked against MERGED source
             by schema/argparse introspection (False/3/8 everywhere;
             CLI store_true + int) — not copied from this design doc.
[ ] P3-S   — stop-and-show; Layer-1 plumbing PR merged
             (flag OFF by default — no behavior change in production)
[x] P3-L2p — Layer-2 pilot EXECUTED (2026-07-29): rev-2 ABORTED
             (production-context fixture mismatch + runner artifact
             gap; behavioral outputs excluded); rev-3 executed to the
             60-call cap — terminal valid-sample rate 3/9 (33%) vs the
             70% floor, ALL failures the pre-existing #146 citation
             reliability class (both arms, zero valid control
             samples). Delivery invariants 10/10; version stable;
             cumulative Layer-2 spend 96 calls / $20.46 of $80.
             Full report:
             reports/pr3_structured_health_feedback_layer2_calibration_2026-07-29.md.
             Protocol DRAFTED 2026-07-29 —
             [`pr3_l2p_calibration_protocol.md`](pr3_l2p_calibration_protocol.md)
             (arms C/T/D, scenarios S1+S2, pipeline-mode proposer
             REQUIRED, 50-call nominal / 60 hard cap, pre-registered
             LLM config + mechanism-relevance fields + rubric +
             redesign triggers + full-campaign decision rule).
             REVISED to rev 2 per the operator protocol review
             (2026-07-29): exact 10-sample allocation table summing to
             50 nominal / 60 hard; normative production-pipeline sample
             invariant with per-sample auditable proposing-stage
             prompts; frozen LLM config with explicit
             provider-default-not-set entries + version-drift stop
             rule; narrow retry semantics (schema-repair counts as an
             LLM call); metric denominators incl. the
             acknowledgment-not-possible rule; frozen
             mechanism-relevance maps; deterministic-before-rubric
             scoring with separate outputs; 8-label blinded rubric with
             second-review rule; diagnostic-arm restrictions; 0.30 as a
             PLANNING effect with the Primary-1/Primary-2/safety
             hierarchy; Wilson/Holm reserved for the frozen full
             campaign; transition + stop conditions; dry-render-
             grounded cost table (~113k input tokens/proposer sample,
             treatment adds ~460). AWAITING operator pilot-launch
             decision — no launch from the draft.
[ ] P3-L2  — Layer-2 campaign NOT RUN — STOPPED by the frozen
             cannot-fit stop condition (2026-07-29): at the observed
             33% terminal success, the smallest justified design needs
             ~600-1200 calls / ~$120-240 vs the authorized 300 calls /
             $59.54 remaining. Layer-2 verdict: INCONCLUSIVE
             (execution-reliability-blocked). 0 valid control samples
             → no C-vs-T comparison → behavioral efficacy UNKNOWN;
             the 3 valid samples are delivery evidence only. The
             treatment's behavioral claim is OPEN, not refuted.
[x] P3-AUD — post-run zero-LLM audit (2026-07-29, operator-directed;
             report §13, protocol §21). Record-changing findings:
             P-1 production retry-loop defect — the proposing stage
             re-injects the CAUSAL stage's inherited_components on
             every structural attempt (agent :1689/:1781), discarding
             the model's corrected citations; a malformed causal-stage
             citation is a guaranteed terminal failure (proven from
             rev-3 raw bodies, S2_C_1). P-2 refines #146: causal-stage
             origin (memo never validated there), two malformed
             classes (external_agent+iteration/registry tags,
             human+"## Vocabulary" refs), semantically-correct
             provenance with no legal encoding, no worked
             prefix:identifier example in any prompt; observed under
             gpt-5.4 (v16 production — NOT gemini as earlier written)
             and gpt-5.5; treatment-independent. Runner findings
             R-1..R-4 (calibration-only): §19.1 stop rule was a
             MID-RUN PROTOCOL AMENDMENT (not pre-registration) and was
             never enforced; mid-sample cap crash left S2_T_2 unmarked
             + run_summary unwritten; wrapper echo masked the nonzero
             exit; launch command unarchived. 33% is NOT a clean
             reliability estimate (P-1 removed the assumed recovery
             channel). Unblock path: fix P-1 + #146 (operator-gated)
             → rev-4 reliability pilot → campaign re-sizing.
[ ] P3-L2p-r4 — rev-4 citation-reliability pilot: protocol DESIGNED
             (`pr3_l2p_calibration_protocol.md` §22, 2026-07-29;
             rescaled per operator decision same day) — operational
             endpoint only (terminal ProposalOutput success),
             **S1 only, 4 samples (C×2 + T×2)**, 16 nominal /
             24 hard-cap calls, ≈$3.2-4.8, gate pre-registered in
             the doc (4/4 valid [≥80% at n=4], ≥1 valid/arm, no
             dominant failure class, corrected retry values
             preserved, no provenance corruption, complete
             artifacts, runner stop + exit-code proven, exact
             treatment isolation). S2/larger runs must NOT be added
             merely for more samples if the gate fails.
             Preconditions: operator-approved production fix +
             runner fixes R-1..R-4 + green deterministic tests.
             LAUNCH REQUIRES SEPARATE OPERATOR APPROVAL — not
             launched.
[ ] P3-L3  — Layer-3 bounded real-LLM + real-training Gate complete
             (operator-approved launch; docs/gates/ conventions)
[ ] P3-ACT — production activation decision (operator; separate from merge)
[ ] top-level PR 3 checkbox in v19_priorities.md may become [x] only
    after P3-L2 + P3-L3 are reviewed and support the behavioral claim
```

Scope rule: if P3-CA reveals materially larger scope than §6 describes,
STOP and report before changing the plan.

## 1. Problem statement and goal link

**Goal link (baseline §1, §1.2)**: V19's top goal is HealthGate-valid
formal scores beating FCNet per band. The binding constraint is the
valid-round rate: 15 of 17 closed V18r iterations produced **zero**
HealthGate-valid trials, V17 produced zero valid formals in 40
iterations, and band 4-9's best formal (−0.9902) is gate-invalid. An
invalid round cannot beat any target by comparison rule (c). PR 3 exists
to raise the valid-round rate by making the *reasons* rounds fail
visible — structurally, not as prose — to the agents that decide what to
try next.

**The gap (code-traced, §2)**: rich structured gate evidence already
exists per experiment — `ExperimentRecord.health_gate_results` carries a
full `PersistedHealthGateResult` list (execution status, per-check
verdicts, counterfactual production verdict, metrics like
`unique_count` / `dominant_fraction` / `std_mv`). Within one tuning run
the planner sees `failure_reason` via memory_history (commit-5b). But at
the node boundary the evidence stops:

- `ModelRunSummary` condenses each round to
  `(score, conclusion-prose, trial_portion, model_params)`. A collapsed
  round renders to the interpreter as `Round N: score=skipped — {prose}`.
  Which gate fired, what action resolved, what the collapse looked like
  numerically — all dropped by `tuning_output_to_model_run_summary`.
- The interpreter therefore cannot preserve a collapse fingerprint, and
  its output schema has nowhere to put one.
- The proposer receives run-level validity aggregates (V18 PR #124) but
  no per-round evidence and no fingerprint. It can know *that* a model's
  best was invalid; it cannot know *how* it collapsed, so it cannot avoid
  proposing the same failure mode again.

**The hypothesis under test** (operator wording, 2026-07-28 — a tested
hypothesis, not an assumed improvement): PR 3 determines WHETHER
structured collapse evidence, relative to today's prose-only condition,
(a) reduces repeated collapse fingerprints; (b) reduces semantically
equivalent repeated proposals; (c) produces real mechanism-level changes
in proposals; (d) improves subsequent HealthGate validity where
observable. A negative or null result is a legitimate PR 3 outcome — the
flag then stays OFF and the findings are documented (§4 rollback
clause). Per baseline §4, no part of the hypothesis is accepted because
the fields appear in a prompt — it requires the three-layer validation
in §7–§9. The bounded Layer-3 Gate confirms end-to-end delivery and a
meaningful decision change on the real system; it is NEVER used alone to
make a statistical claim that the valid-round rate increased (that
statistical evidence, where obtainable, comes from Layer 2 and from
post-activation production review, P3-ACT).

**Delivery vs behavioral use**: this PR distinguishes them throughout.
§3 (delivery) is deterministic plumbing and may merge flag-OFF after
Layer-1 validation. §4–§5 (behavioral use) is the evaluation that decides
whether the mechanism works. Neither substitutes for the other.

## 2. Audit summary (2026-07-28, code-traced; §2.5 = the completed P3-CA findings)

Every claim below was traced in code on master `52151b2` on 2026-07-28.

### 2.1 What already exists (do not rebuild)

| Artifact | Location | Notes |
|---|---|---|
| Full per-gate persisted results | `ExperimentRecord.health_gate_results: list[PersistedHealthGateResult]` (`agent/schemas/hyperparam_tuning.py`) | gate_name, execution_status, check_passed, **would_invalidate_under_production_policy**, resolved_action, failure_reason, threshold, aggregation, **metrics**, runtime |
| Per-round routing fields | `ExperimentRecord.gate_action`, `ExperimentRecord.failure_reason` | populated at tuner round boundaries (commit-5b); `failure_reason` is pipe-concatenated `[gate_id] reason` |
| Round status | `ExperimentRecord.status` incl. `failed_mode_collapse` | |
| In-run planner feedback | memory_history renders `failure_reason` to the tuner's LLM planner | within-run only; not this PR's surface |
| Run-level condensed validity (V18 PR #124) | `ModelRunSummary.best_valid_denoising_score`, `.best_raw_health_validity`, `.best_valid_formal_score`, `.best_valid_config`, `.best_valid_score_table`; `InterpretationOutput.per_model_best_valid`, `.per_model_raw_best_health_validity`, `.best_valid_denoising_score`, `.best_valid_config` | **verified rendered** in both prompts: interpreter per-model header (`result_interpretation_agent.py:157-158`, synthesis `:457`) and proposer (`ml_model_proposal_agent.py:805-820`) |
| Validity classifier | `execute_tools/health_checks/candidate_eligibility.py::classify_candidate_health` | valid / invalid / unknown; DS5 disabled-mode waiver; required-blocking-gate logic — REUSE, do not reimplement |
| Blocking-action set | `BLOCKING_ACTIONS` (`execute_tools/health_checks/schemas.py:49`) | invalidate_round / skip_to_formal / skip_iter |
| Per-round summary-list pattern | `RoundOrdering` + `ModelRunSummary.round_ordering` (V19 PR 2) | the structural template for `RoundHealth` |
| Proposer structured-failure-block precedent | `_format_recent_gate_exhaustions_block` (`ml_model_proposal_agent.py`, §14.N) | existing prompt pattern for structured failure feedback incl. "switch family when the failure mode recurs" closing instruction |
| Layer-1 flag precedent | `enable_chain_incumbent_formal_gates` (PR 1) | bool through protocol → input schema → CLI, default OFF |

### 2.2 What is missing (the PR 3 surface)

| Gap | Where |
|---|---|
| Per-round gate fields in the summary | `ModelRunSummary` has no round_health analog of `round_ordering`; `tuning_output_to_model_run_summary` (`result_interpretation_agent.py:1715`) drops `status`, `gate_action`, `failure_reason`, `health_gate_results` per round |
| Trajectory rendering | interpreter per-model prompt (`:210-234`) renders `Round N: score=skipped — {prose}` with no gate cause |
| Fingerprint representation | no typed collapse-fingerprint concept anywhere |
| Interpreter output carry | `InterpretationOutput` has no field that preserves per-model collapse evidence for the proposer or the next iteration |
| Proposer prompt block | no HealthGate-evidence block (the §14.N exhaustion block covers abort-class resource failures only, not gate collapses) |
| Cross-iteration survival | workflow carry-forward (knowledge cache / vocab / prediction history) carries no gate evidence |
| Protocol mapping | `ml_model_tune_to_ml_result_interp.local_all_records` maps nothing gate-related (all mapping is inside the summary builder it calls) |

### 2.3 Naming note — "is_degenerate" (baseline §2.1 wording vs current code)

Baseline §2.1 asks for per-round `is_degenerate` fields. Post-commit-5a,
`score_vector` is pure scoring and `is_degenerate` no longer exists as a
produced field (CLAUDE.md subsystem invariant). The current-code
equivalents are: `status == "failed_mode_collapse"`, non-`continue`
`gate_action`, per-gate `check_passed` /
`would_invalidate_under_production_policy`, and the
`classify_candidate_health` verdict. This design maps §2.1's intent onto
those — it does NOT resurrect `is_degenerate`.

### 2.4 Fingerprint raw material (from `configs/health_checks.yaml` + check code)

Blocking checks and their discriminating metrics:

- `output_diversity` — `unique_count` (collapse ≈ 1–15; FCNet real
  learning 52–143; threshold 25), dominant value (the class-127 phantom
  family), per-peeked-file verdicts (`peek_file_indices: [3, 10, 17]`,
  `any_pass`)
- `output_std` — `std_mv` (collapse < 0.2 mV; FCNet ≈ 7.35 mV; threshold
  1.0 mV)
- `amplitude_collapse` — `dominant_fraction` (threshold 0.95)

Recording-only checks give the "misleading high raw score" diagnostic:
`pearson_dispersion` (real learning ≈ 0.048 vs collapse ≈ 0.002 — 24×
separation), `spectral_peak_ratio`, `per_file_output_std`.

### 2.5 P3-CA findings (2026-07-28/29 — accepted by operator)

Traced on master `52151b2` + real persisted artifacts. These are the
binding audit facts the implementation builds on.

**Record vintages (raw-JSON key presence, real artifacts):**

| Vintage | Sample | `health_gate_results` key | `health_gate_enabled` key |
|---|---|---|---|
| pre-gate-persistence | `wavenet/diagnostic_baseline_pre_v17` | absent | absent (`gate_action` present on collapse records — commit-5b round fields predate result persistence) |
| V17-era gated | `exploration_loss_v17_20260718` | present on EVERY record — incl. `skipped_time_risk` with `[]` | absent (predates DS5) |
| post-DS5 | (none on lilab yet) | present | stamped True/False on every executed record (`ml_hyperparameter_tune_agent.py:3686`; pre-flight skip and attempt-failure shapes are NOT stamped) |

**Field-presence signal**: `"health_gate_results" in
record.model_fields_set` faithfully mirrors raw-key presence on both
production paths — resume/seed (`model_exploration.py:254`
`model_validate` of raw JSON) and in-memory (tuner-authored dicts).
Hazard: any `model_dump()`→`model_validate()` round-trip manufactures
presence — CB2 carries a regression test with a fresh-authored vs
re-parsed fixture pair. List emptiness alone is never the
discriminator.

**Error-status lifecycle** (each status vs the gate call at `:3157`):

| Status | Written at | Gate evidence possible before it? |
|---|---|---|
| `skipped_oom_risk` / `skipped_time_risk` / `skipped_schema_violation` | pre-flight | no (nothing ran) |
| `error` (attempt_failure, `:3819`) | pre-execution failure stages | no |
| `error_training(_oom)` (`:2938`) | training-failure branch | no (before inference/scoring/gates) |
| `error_inference(_oom)` (`:3005-3021`) | inference-failure branch | no |
| `error_scoring` (`:3226`) | `except` wrapping the WHOLE scoring block INCLUDING the gate call | gates may have partially run, but the error-record shape persists NO gate keys — nothing to discard; evidence precedence (§3.2 step 1) protects any future shape that persists results |
| `failed_mode_collapse` / `success` | after gate evaluation | yes — evidence persisted |

**Import graph** (module-level, acyclic): `health_checks/schemas.py` is
stdlib+pydantic only — the clean canonical home. `runner.py` drags
config+registry; `candidate_eligibility.py` drags config→dataset_config.
Accepted minimal extractions: `severity_of`/`_SEVERITY`
(`runner.py:34-49`) and `CandidateHealthValidity` move INTO
`schemas.py`; `runner`/`candidate_eligibility` re-export for
compatibility; ordering logic never duplicated. Pre-existing caveat:
importing any `health_checks` submodule executes the package `__init__`
(check self-registration) — already on `hyperparam_tuning.py`'s import
path, not a new edge.

**History identity**: `exp_id = "{model_type}_iter_{NNN}_{RRR}"` (≤50
chars, self-describing). Chains propose a fresh `model_type` per
iteration → the label is architecture-precise; per-round config is
exactly recoverable via exp_id → `ExperimentRecord.params`. Accepted:
`model_type` is the history grouping key for PR 3; no config hash;
`source_exp_ids` = latest 8 per occurrence bucket, oldest-first
trimming.

**Record order**: timestamps strictly chronological in `all_records`;
JSON arrays and Pydantic list validation preserve order on both
handoff paths → the representative-observation rule ("latest
iteration, then last chronological record") is reproducible across
persistence/replay.

**Metric payloads**: real `PersistedHealthGateResult.metrics` trees are
large and NESTED (`per_file.{idx}.metrics.*` + `aggregate_statistics`);
the §3.4 allowlist must specify exact nested extraction paths, authored
from the real V17 payload fixtures, not synthesized.

## 3. Design — Layer-1 delivery

### 3.1 Principles

1. **Resolved evidence only, provenance always.** Downstream agents see
   what the gates actually recorded, never a reconstruction. Legacy
   records (pre-gate or pre-PR3) are labeled, not guessed at (mirrors PR
   2's provenance rule).
2. **Condense at the boundary, don't truncate silently.** The summary
   carries a bounded, typed condensation of `health_gate_results` — not
   the full list (payload discipline), and not prose (the failure being
   fixed). Anything dropped is dropped by documented rule.
3. **One flag, both prompts.** A single `enable_structured_health_feedback`
   switch (default OFF) gates BOTH the interpreter and proposer prompt
   blocks. Parity claim (operator wording, 2026-07-28): *with the flag
   OFF, agent-facing prompts remain byte-identical to the pre-PR3
   condition; persisted artifacts may contain additional recording-only
   structured provenance.* ON = treatment condition. The same flag IS
   the control/treatment switch for §4's evaluation — the evaluation
   exercises exactly the production mechanism, and activation is
   precisely "flip the default" (rollback = flip back).
4. **Schema/storage/protocol only.** All new data flows through node
   output schemas and protocol functions. No node reads another node's
   files.
5. **Deterministic evidence, LLM commentary.** Every structured field —
   `RoundHealth`, fingerprints, `per_model_round_health_counts`,
   `per_model_collapse_fingerprints`, `collapse_fingerprint_history` —
   is populated deterministically from `ExperimentRecord` data. The
   required flow (operator decision, 2026-07-28):

   ```text
   ExperimentRecord
     → deterministic RoundHealth (§3.2, pure function)
     → deterministic fingerprint construction + history merge (§3.3, §3.8)
     → prompt rendering (flag-gated, §3.6/§3.7)
     → LLM interpretation (commentary)
   ```

   The LLM may discuss these facts; it is never their source of truth.
   Fingerprints and history are NEVER generated, reconstructed, or
   parsed back from interpreter prose or `key_findings` — the history
   merge reads the deterministic per-round fingerprints, not the LLM
   output. Corollary (operator, 2026-07-28): the merge runs regardless
   of interpreter LLM success or degradation — see the §3.10 degraded
   invariant.

### 3.2 New schema: `RoundHealth` (per-round condensed gate evidence)

New model in `agent/schemas/interpretation.py` beside `RoundOrdering`,
plus `ModelRunSummary.round_health: list[RoundHealth]`
(default_factory=list; chronological, parallel to `round_scores`; empty
on legacy summaries).

Typed with canonical existing types wherever one exists (operator
clarification, 2026-07-28 — no parallel enums, no unrestricted strings
for known value sets, no mutable literal defaults):

```python
GateExecutionStatus = Literal["passed", "failed", "not_run", "error"]
    # extracted alias of the EXISTING PersistedHealthGateResult.execution_status
    # Literal — one definition, both models reference it (P3-CA confirms the
    # extraction is non-breaking for serialized artifacts; values unchanged)

class GateOutcome(BaseModel):
    """One gate's condensed verdict for one round."""
    gate_name: str                              # min_length=1
    execution_status: GateExecutionStatus
    check_passed: bool | None
    would_invalidate_under_production_policy: bool | None
    resolved_action: GateAction | None          # REUSE execute_tools GateAction StrEnum
    failure_reason: str | None
    key_metrics: dict[str, float | int | str] = Field(default_factory=dict)  # §3.4

class RoundHealth(BaseModel):
    exp_id: str | None                          # None on legacy records
    status: str                                 # ExperimentRecord.status verbatim
                                                # (its Literal is the canonical
                                                # definition; carried as str to
                                                # avoid coupling the summary to
                                                # the tuner's status vocabulary —
                                                # P3-CA revisits if a shared
                                                # Literal alias is cleaner)
    health_validity: CandidateHealthValidity    # REUSE the existing StrEnum
                                                # (valid | invalid | unknown)
    gate_action: GateAction | None              # round-resolved (severity-max)
    failure_reason: str | None                  # pipe-concatenated, verbatim
    gate_outcomes: list[GateOutcome] = Field(default_factory=list)
    fingerprint: CollapseFingerprint | None     # §3.3; None when healthy
    provenance: RoundHealthProvenance           # typed Literal; exact value
                                                # set finalized at CB1/CB2
                                                # (smallest model covering
                                                # the confirmed cases below)
```

**Provenance model — extensible, finalized during implementation**
(operator direction, 2026-07-29): the taxonomy is deliberately NOT
locked to an exhaustive enum before implementation. The P3-CA artifact
audit confirmed the distinctions the implementation genuinely needs:
**evidence present** (persisted `health_gate_results` authoritative —
an explicitly PRESENT empty list is current gated-era provenance, never
legacy by emptiness); **gates disabled** (explicit
`health_gate_enabled=False`, DS5 semantics — validity `valid` by rule);
**no gate evaluation** (a current attempt ended before HealthGate
execution — not healthy, not collapsed, not legacy; no outcomes, no
fingerprint); and **legacy** (no reliable structured or round-level
evidence — explicit and non-guessing, no verdict inferred from
absence). The audit also observed a commit-5b mid-vintage (round-level
`gate_action`/`failure_reason` without per-gate results — preserved
verbatim, no fingerprint invented from prose); whether that becomes its
own provenance value or a labeled sub-case is decided at CB1/CB2.

**Governing rule** (operator, 2026-07-29 — binding over any taxonomy):

> Preserve the strongest evidence actually present in the record.
> Never infer gate execution from missing fields, and never discard
> explicit gate evidence because of a broad status classification.

During CB1/CB2 the implementation must: (1) inspect the actual
lifecycle and record shapes again; (2) choose the SMALLEST typed
provenance model that represents all confirmed cases without
ambiguity; (3) add tests from real persisted examples; (4) if this
design cannot represent a real case cleanly, STOP, explain the
conflict, and propose the smallest revision before continuing.

**Audit-derived classification reference** (validated against real
artifacts of all three vintages, P3-CA 2026-07-28/29 — the
evidence-precedence ORDER is confirmed; the implementation may collapse
labels per the process above but must preserve the precedence):

```text
1. persisted health_gate_results non-empty      → evidence present
                                                  [regardless of status]
2. health_gate_enabled is False                 → gates disabled
3. attempt_failure / NOT_EXECUTED_STATUSES /
   pre-gate error statuses (§2.5 table)         → no gate evaluation
4. "health_gate_results" ∈ model_fields_set,
   executed status, list empty                  → evidence present
                                                  (current era, empty)
5. round-level gate_action / collapse
   failure_reason without per-gate results      → mid-vintage partial
                                                  evidence (verbatim)
6. otherwise                                    → legacy
```

`error_scoring` nuance (from the §2.5 lifecycle trace): its `except`
handler wraps the gate-evaluation call, so gates may have partially
executed before the crash — but the error-record shape persists no
gate keys, so classifying it "no gate evaluation" discards nothing;
step 1 protects any future error shape that DOES persist results.

Detailed provenance semantics are defined by the extensible model
above (the original three-state form was superseded by the operator
direction of 2026-07-29 after the P3-CA artifact audit; `gates_disabled`
keeps its DS5 semantics — validity `valid` by rule, `gate_outcomes`
empty).

**Legacy-detection invariant** (operator clarification, 2026-07-28):
*legacy provenance must be derived from a reliable persisted-version or
field-presence signal; an empty parsed `health_gate_results` list alone
is not sufficient.* Pydantic defaults can make "the field never
existed in the artifact" and "a current artifact with an explicitly
empty list" deserialize identically (`default_factory=list`), so the
naive emptiness check conflates a genuine legacy record with a current
gated round whose results are empty or partially populated. The
reliable signal is selected at **P3-CA** by auditing the actual
persisted and deserialized representations; candidate signals, in
preference order: original field presence via `model_fields_set` (or
raw-JSON key presence at the load boundary); an artifact/schema version
marker if one exists; explicit `health_gate_enabled` provenance
(already tri-state: True/False/absent per DS5); another existing
persisted version marker found in the audit. **If no reliable signal
exists, STOP and report — do not invent a heuristic.**

`health_validity` is computed by calling the existing
`classify_candidate_health(record)` — single source of truth, no
parallel logic.

### 3.3 New schema: `CollapseFingerprint`

The canonical, comparable identity of a failure mode. Purpose: let the
proposer recognize "this is the same collapse I caused before" across
rounds, models, and iterations.

```python
class CollapseFingerprint(BaseModel):
    check_name: str                  # min_length=1; check of the PRIMARY
                                     # gate outcome (rule below)
    signature: str                   # min_length=1; canonical BUCKETED
                                     # compact form, e.g.
                                     # "output_diversity:unique_count=1;dominant=127"
    metrics: dict[str, float | int | str]   # RAW discriminating values — never bucketed
    human_readable: str              # display-only; NEVER participates in equality
```

**Primary-fingerprint selection rule** (operator decision, 2026-07-28 —
one primary fingerprint per round, chosen as the gate outcome that
actually contributed to the final blocking verdict, NOT simply the
first failed check in configuration order). From the round's
`health_gate_results`, filter to FAILED gates, then select by, in
order:

1. **action consistency** — outcomes whose `resolved_action` equals the
   round's resolved blocking `gate_action` (the severity-max the tuner
   recorded);
2. **counterfactual verdict** —
   `would_invalidate_under_production_policy is True`;
3. **blocking severity** — highest `severity_of(resolved_action)`
   (reuse `execute_tools/health_checks/runner.py::severity_of`;
   SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE);
4. **configuration order** — deterministic final tie-break only.

Each step narrows the candidate set; if a step eliminates every
candidate it is skipped (e.g. a legacy record with no
counterfactual field falls through step 2). All other failed-gate
outcomes remain fully available in `gate_outcomes` — the primary
fingerprint is a selection for identity matching, not a truncation of
evidence.

`check_name`/`metrics` come from the selected gate's check; `signature`
is `"{check_name}:" + ";".join(f"{k}={bucket(v)}")` over the
allowlisted metrics **sorted by key** (bucketing in §3.4);
`human_readable` is composed from the check's `reason` string and is
**display-only — it never participates in fingerprint equality or
matching**.

**Raw vs bucketed** (operator decision): `metrics` always stores the
RAW values; bucketing is applied only when deriving `signature`. This
keeps fingerprints recomputable later under a different bucketing rule
without touching stored artifacts.

Two fingerprints "match" when `signature` is equal. Matching is used by
evaluation metrics (§4) and by the proposer prompt's repeated-mode
warning — it is NOT used for any routing decision (non-goal,
Candidate B).

### 3.4 Bounding rule for `key_metrics` / fingerprint metrics

Per check, the discriminating metrics are a fixed allowlist (defined in
one module-level dict next to `CollapseFingerprint`):

- `output_diversity`: `unique_count` (min over peeked files), dominant
  int8 value if the check emits it
- `output_std`: `std_mv` (min over peeked files)
- `amplitude_collapse`: `dominant_fraction` (max over peeked files)
- recording checks (in `GateOutcome.key_metrics` only, never in
  fingerprints): `pearson_dispersion` scalar, `spectral_peak_ratio`
  summary scalar, `per_file_output_std` mean/min/max — no per-file lists

Numeric bucketing applies to the `signature` string ONLY: floats
rendered at 2 significant figures (so `dominant_fraction=0.9612` and
`0.9634` are the same mode; `unique_count` stays exact — it is the
discrete discriminator). The `metrics` dict keeps the raw values
untouched (§3.3), so signatures can be recomputed under a revised
bucketing rule from stored artifacts alone. 2-sig-fig is the INITIAL
matching rule (operator: acceptable as initial); any revision is a
follow-up informed by Layer-2 evidence, not a PR 3 change. Everything
not on the allowlist stays in the `ExperimentRecord` (which persists in
full) and is deliberately NOT carried into the summary — documented
drop, per §3.1 principle 2.

### 3.5 Summary builder (`tuning_output_to_model_run_summary`)

Extend the existing per-record loop (`result_interpretation_agent.py`,
same loop that builds `round_ordering`): append
`_round_health(r)` for every record, where `_round_health` implements
§3.2–§3.4. Pure function, unit-testable against synthetic records
covering: healthy gated round; `failed_mode_collapse` with one/multiple
failed gates; `not_run`/`error` execution statuses; DS5
`health_gate_enabled=False`; legacy record with no gate fields; error
statuses (`error_training` etc. — carried with their status verbatim,
fingerprint None, validity `invalid` per the classifier).

The protocol `ml_model_tune_to_ml_result_interp.local_all_records`
needs no signature change (all mapping is inside the builder), but its
docstring's consumed/populated lists must be updated (P3-CB2).

### 3.6 Interpreter delivery (`result_interpretation_agent`)

Flag OFF: prompts byte-identical to today. Flag ON:

1. **Trajectory line** gains the gate cause:
   `Round 3: score=invalidated [GATE invalidate_round — output_diversity: unique_count=1; dominant=127] — {prose}`
   (`skipped` is kept for non-gate skips; gate-invalidated rounds get the
   explicit label — today's rendering conflates them).
2. **Per-model section** gains `### HealthGate summary`: valid/invalid/
   unknown round counts, distinct fingerprints with occurrence counts and
   round indices, recording-only diagnostic scalars for the best round.
3. **Per-model system prompt** gains an instruction block: preserve the
   collapse fingerprint verbatim in findings; never paraphrase the
   numbers away; a high raw score with invalid gate evidence must be
   reported as invalid, not as an achievement.

**Output carry (flag-independent — schema fields always populated):**
`InterpretationOutput` gains:

```python
per_model_round_health_counts: dict[str, dict[str, int]]  # model → {valid, invalid, unknown}
per_model_collapse_fingerprints: dict[str, list[CollapseFingerprint]]
    # model → distinct fingerprints observed this iteration (deduped by signature)
```

Rationale for flag-independence of the OUTPUT fields (operator-approved
Q2): recording is harmless and makes the treatment/control comparison
auditable from artifacts; only PROMPT rendering is behavior-relevant and
flag-gated. Both fields — and `collapse_fingerprint_history` (§3.8) —
are populated **deterministically from `RoundHealth`** in plain code
before/after the LLM calls (§3.1 principle 5). They are never derived
from, corrected by, or reconciled against the LLM's findings; a
degraded (LLM-failed) interpretation still populates them correctly.
The `model_knowledge_cache` `_stats` sub-dict gains the same two entries
per model so cached (non-active) models keep their fingerprint history
without a fresh LLM call — `_stats` is the deterministic side of the
cache, which is exactly where non-LLM facts belong.

### 3.7 Proposer delivery (`ml_model_proposal_agent`)

Flag OFF: prompt byte-identical to today. Flag ON: a
`[HEALTHGATE EVIDENCE]` block rendered from
`interpretation["per_model_collapse_fingerprints"]` +
`["per_model_round_health_counts"]`, modeled on the §14.N
gate-exhaustion block (which stays separate — it covers abort-class
resource failures, a different failure family):

- per model: valid/invalid round counts and the distinct fingerprints
  (signature + human_readable + occurrence count);
- a closing instruction paragraph: proposals must not repeat a
  fingerprinted failure mode without an explicit mechanism claimed to
  break it; avoiding a fingerprint is NOT a reason to avoid unrelated
  healthy strategies (the inappropriate-avoidance failure mode, §4.3);
- fingerprints from the current iteration AND the carried window (§3.8),
  labeled with relative iteration tags like the §14.N block.

`ProposalInput` needs no new field: the proposer already receives the
full `interpretation: dict` (InterpretationOutput dump), so the new
output fields arrive automatically. The renderer reads them with
`.get(...)` defaults (legacy interpretation dicts).

### 3.8 Cross-iteration carry — bounded, configurable retention policy

Fingerprint history must survive iterations to break repeated-collapse
loops. Mechanism (mirrors `prediction_outcomes_history` for transport):

**Typed history entries with per-iteration occurrences** (operator
clarifications, 2026-07-28 — no raw dicts in persisted or
protocol-facing history; and a lifetime aggregate
`count/first_seen/last_seen` cannot support windowed counts, so
occurrences are kept per iteration):

```python
class FingerprintOccurrence(BaseModel):
    iteration: int
    count: int = Field(ge=1)                 # occurrences of this mode at this iteration
    source_exp_ids: list[str] = Field(default_factory=list)
        # bounded source identity (§3.8a); FINALIZED at P3-CA: latest 8
        # exp_ids per bucket, oldest-first trimming (exp_ids are ≤50-char
        # self-describing strings — §2.5)

class CollapseFingerprintHistoryEntry(BaseModel):
    signature: str                           # min_length=1
    check_name: str                          # min_length=1
    metrics: dict[str, float | int | str] = Field(default_factory=dict)  # RAW values
    human_readable: str                      # display-only (§3.3)
    occurrences: list[FingerprintOccurrence] = Field(default_factory=list)
        # ascending by iteration; at most one bucket per iteration

# InterpretationInput (carry-forward)
collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] \
    = Field(default_factory=dict)
# InterpretationOutput
collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] \
    = Field(default_factory=dict)
```

**Raw-metric provenance within an entry — representative-observation
rule** (resolves the ambiguity flagged by the operator 2026-07-28:
multiple raw observations can share one bucketed signature, so a
single entry-level `metrics`/`human_readable` pair must be defined,
not incidental. Rule proposed for P3-D review):

- Entry-level `metrics` and `human_readable` always represent the
  **most recently merged observation**: highest iteration; within one
  iteration, the last record in the tuner output's chronological
  record order (deterministic — the same order the summary builder
  walks).
- On merging a new same-signature observation, both fields are
  OVERWRITTEN with that observation's raw values. Signature stability
  is guaranteed by construction: any member observation buckets to the
  entry's signature — that is the membership criterion — so the
  recompute-from-raw invariant (§3.4) holds for whichever observation
  is representative.
- No information is lost by the overwrite: recent observations are
  directly referenced through the bounded `source_exp_ids`; all
  observations remain available in the workspace's persisted
  `ExperimentRecord`s (operator wording, 2026-07-29 — the bound means
  not every historical observation stays DIRECTLY referenced).
- Alternative — storing per-occurrence metrics — is rejected for
  payload growth unless the P3-CA payload inspection (§3.8a) shows the
  bound makes it cheap; if P3-CA prefers it, that is a reported scope
  change, not a silent one.

**Derived, never independently persisted** (single source of truth is
the occurrence list):

- `windowed_count = sum(o.count for o in occurrences if o.iteration >= minimum_retained_iter)`
- `first_retained_iter = min(retained iterations)`
- `last_retained_iter = max(retained iterations)`

Prompt counts (§3.6/§3.7) and Layer-2 repeated-mode metrics (§4) use
the RETAINED occurrences only — never a lifetime aggregate.

Why the aggregate form was rejected (operator example): occurrences at
iterations 1, 2, 5 with `current_iter=5, window=3` retain only
iteration 5 — but `count=3, first=1, last=5` cannot be reduced to the
correct windowed `count=1`. Per-iteration buckets reduce exactly.

The typed form travels through `InterpretationInput`,
`InterpretationOutput`, resume, and the workflow carry-forward. Raw
dicts appear only at the final serialization boundary (Pydantic's own
`model_dump` when the digest is written / the proposer receives the
interpretation dump) and at prompt rendering. Validation enforced at
schema construction: per-bucket `count >= 1`; non-empty `signature` and
`check_name`; occurrences ascending with unique iterations
(model_validator).

**Retention policy (operator decision, 2026-07-28 — configurable, not
hardcoded).** PR 3 implements exactly one policy — a bounded
iteration-window — but behind an explicit configuration surface so the
window is adjustable without code changes:

```python
class HealthFeedbackRetentionPolicy(BaseModel):
    history_window_iterations: int = Field(default=3, ge=1)
        # TOTAL iterations retained, INCLUDING the current one
    max_entries_per_model: int = Field(default=8, ge=1)
        # deterministic trim bound
```

Non-positive values are rejected at schema construction (`ge=1` on
both) — an invalid zero or negative policy fails before any execution.

(Field names + defaults FINALIZED at P3-CA, operator-accepted
2026-07-29: input/CLI names `health_feedback_history_window_iterations`
and `health_feedback_history_max_entries_per_model`, riding on
`InterpretationInput` per the `active_model_top_k` /
`active_model_last_n` / `active_model_score_delta` typed-knob
convention; flag name `enable_structured_health_feedback` per the
`enable_chain_incumbent_formal_gates` precedent; lock names in §3.9.
Defaults: window 3 — the §14.N three-iteration precedent, the only
in-repo empirical prior for proposer failure-memory depth; max entries
8 — ≥2× the distinct-blocking-mode space of 3 checks × few buckets.)

Required semantics (all deterministic):

- retention operates on OCCURRENCE BUCKETS, with
  `history_window_iterations` defined as the TOTAL number of iterations
  retained including the current one (operator clarifications,
  2026-07-28):

  ```text
  minimum_retained_iter = current_iter - history_window_iterations + 1
  1. expiry: remove every FingerprintOccurrence bucket with
     iteration < minimum_retained_iter
  2. drop:   remove the entry entirely if no occurrence buckets remain
  ```

  Boundary example: `current_iter=5, window=3` → buckets at iterations
  3, 4, 5 are retained; a bucket at iteration 2 is removed. (`window=1`
  retains only the current iteration's buckets.) Non-contiguous
  example (operator): occurrences at iterations 1, 2, 5 → after expiry
  only the iteration-5 bucket remains; the windowed count is that
  bucket's count, NOT the lifetime 3;
- current-iteration merge: a fingerprint observed this iteration
  appends to (or increments) the bucket with
  `iteration == current_iter` on its same-signature entry — creating
  the entry if new. Buckets are never merged across iterations;
- **no permanent retention**: the previously proposed `count >= 3`
  exemption is dropped (operator decision). Persistent long-term
  failure memory is a future policy near workflow-evolution work,
  reconsidered from Layer-2 evidence;
- **model attribution is preserved end-to-end**: the history dict is
  keyed by `model_type` (key precision audited at P3-CA — §3.8a), the
  merge never moves entries across keys, and prompt rendering labels
  every fingerprint with its model. A fingerprint from one model is
  never presented as another's;
- deterministic ordering of retained entries: derived
  `last_retained_iter` desc, then derived `windowed_count` desc, then
  `signature` asc (total order — no dict-order dependence; derived
  values per the rules above);
- deterministic trimming: after ordering, keep the first
  `max_entries_per_model` per model;
- missing/legacy configuration resolves to the documented defaults.

The mechanism supports future policies without redesign (time-based
expiry, severity-weighted retention, global entry limits, persistent
memory) — but PR 3 implements ONLY the bounded iteration-window policy;
those extensions are explicitly out of scope.

The prompt renderers (§3.6/§3.7) consume the RESOLVED policy passed
down with the input — never a module-level constant.

The workflow's existing carry-forward step copies the field across
iterations; chain resume reads it from the persisted interpretation
digest like the other carried fields. Design wording rule: this doc
says "retain fingerprint history according to the resolved bounded
history policy; the initial default is three iterations" — never "keep
the last three iterations".

### 3.8a Source identity and attribution precision (P3-CA audit requirement)

The history must support: exact iteration tags; correct
retained-window counts; model attribution; and determining whether a
later proposal repeats the relevant failed MECHANISM. Per-iteration
occurrence buckets (§3.8) provide the first two. For the last two
(operator requirement, 2026-07-28):

- At **P3-CA**, audit whether `model_type` alone is a sufficiently
  precise history key. Agent-generated plugin types may make one
  `model_type` label span materially different configurations —
  **unrelated configurations must not be silently merged merely
  because they share a broad model-type label.**
- If `model_type` is too broad: KEEP it as the top-level key (prompt
  grouping stays by model), and preserve a bounded source identity on
  each occurrence bucket — `source_exp_ids` and/or a deterministic
  config identity (e.g. a stable hash of the collapse-relevant config
  subset). The exact inclusion and payload bound for `source_exp_ids`
  is decided at P3-CA after inspecting real record payloads.
- The chosen identity and its payload bound are REPORTED to the
  operator before implementation (part of the P3-CA stop-and-show).

### 3.9 Flag surface

`enable_structured_health_feedback: bool = False`, following the PR 1
`enable_chain_incumbent_formal_gates` pattern end-to-end:

- `InterpretationInput` + `ProposalInput` field (each node reads its own
  input — no hidden coupling);
- workflow `run_workflow(...)` parameter; protocol functions thread it;
- chain CLI `--enable_structured_health_feedback`
  (`run_one_iteration.py` + `run_chain.sh` passthrough);
- stamped into `run_config` and the iteration manifest (round-keyed
  detail is unnecessary here — the flag is run-level policy, like PR 2's
  override; the per-round EVIDENCE is in the records regardless);
- **IN the run-invariants lock** (operator decision Q4, 2026-07-28):
  although the flag changes no data or scoring, it changes the agent's
  decision context and therefore the chain's behavioral policy —
  the same class of chain-level control decision as the ordering
  override. The RETENTION POLICY (§3.8) is locked for the same reason:
  it affects agent context.

  `RunInvariants` gains three canonical fields, defaulted so a pre-PR3
  lock file validates cleanly into the pre-feature state (the PR 2
  `ordering_override_strategy: str | None = None` pattern):

  ```python
  structured_health_feedback_enabled: bool = False
  health_feedback_history_window_iterations: int = 3
  health_feedback_history_max_entries_per_model: int = 8
  ```

  Resume matrix (enforced by the existing lock-equality machinery — the
  fields join `_CANONICAL`):

  | Situation | Outcome |
  |---|---|
  | Resume with same flag + same policy values | accepted |
  | Changed flag in the same workspace | REJECTED (`RunInvariantsViolation`) |
  | Changed window or entry limit in the same workspace | REJECTED |
  | Legacy workspace (no PR3 keys in lock file) | resolves to OFF + default policy; accepted |
  | Enabling treatment for a legacy/OFF workspace | requires a NEW workspace |

  All three lock sites (tuner, `workflows/model_exploration.py`,
  `run_one_iteration.py`) must pass the fields consistently — the PR 2
  lock-collision lesson; the override-surface regression-test pattern
  is reused (§7.1).

  Consequence for §4/§5: Layer-2 control and treatment runs use
  SEPARATE workspaces (operator requirement — and the lock now enforces
  it).

### 3.10 Legacy and degraded behavior (explicit, per §4.2 Layer 1)

- Legacy `ExperimentRecord` (detected via the §3.2 reliable-signal
  invariant, NEVER by list emptiness alone) → `RoundHealth(provenance
  ="legacy")`, no fingerprint, validity from the classifier (typically
  `unknown`); prompts render "no gate evidence (legacy record)" rather
  than omitting the round. The §7.1 provenance suite distinguishes:
  genuine legacy artifact; current gates-disabled record; current gated
  record with an empty or partially populated result list; current
  non-executed/error record; mid-vintage partial-evidence record.
- DS5 disabled-gate runs → `provenance="gates_disabled"`, validity
  `valid`, prompt line states gates were disabled by config.
- Degraded interpreter output (`is_degraded=True`) — corrected
  invariant (operator, 2026-07-28; the earlier "verbatim carry, no
  growth" wording contradicted the determinism principle and is
  withdrawn): the deterministic merge runs REGARDLESS of interpreter
  LLM success or degradation —

  ```text
  previous typed history
    + current deterministic RoundHealth fingerprints
    → deterministic merge and retention (§3.8)
    → persisted InterpretationOutput history
  ```

  A current iteration's real HealthGate evidence is never lost because
  the interpreter LLM failed. Degradation affects ONLY LLM-generated
  commentary (`key_findings`, `bottlenecks`, discoveries stay empty per
  the existing degraded contract); new deterministic fingerprints,
  windowed counts, and health summaries are still recorded. (This
  differs from `runtime_vocab`, whose growth IS LLM-derived and
  correctly freezes under degradation.)
- Older interpretation digests without the new fields → workflow
  carry-forward treats missing as empty (`.get` with defaults);
  `not_executed` PR 2-style attempts (no scoring ran) get RoundHealth
  from their status with no gate outcomes.

## 4. Behavioral contract (baseline §4.3 — answers required before any evaluation)

- **What behavior is expected to change?** Hypothesis (§1): the proposer
  stops re-proposing configurations/architectures that reproduce an
  already-fingerprinted collapse mode, and the interpreter's findings
  carry the fingerprint instead of losing it. Whether the next-round
  HealthGate-valid rate then rises is the (d)-clause of the hypothesis —
  measured where observable, never assumed from (a)–(c).
- **What observable output represents it?** (a) proposer: the proposed
  architecture/config diff vs the fingerprinted failure's config, and the
  motivation text's reference to the fingerprint; (b) interpreter:
  presence + numeric accuracy of the fingerprint in
  `key_findings`/`bottlenecks`/output fields; (c) system: HealthGate
  verdict of the next executed round (L3 only).
- **What counts as superficial compliance?** The rubric (each scored
  per-sample during L2): mentions the fingerprint but proposes a
  semantically equivalent mechanism anyway; copies the numbers with wrong
  attribution (wrong check, wrong model); claims avoidance with no
  mechanism named; paraphrases that lose the discriminating number;
  **unsupported use-claims** (says "based on the diversity collapse"
  when the treatment context contained no such evidence — control arm
  probe); inappropriate avoidance (drops an unrelated healthy strategy
  citing the fingerprint).
- **Control condition**: flag OFF — prompts exactly as production today
  (prose conclusions + run-level validity aggregates only).
- **Treatment condition**: flag ON — identical context plus the §3.6/§3.7
  blocks. Same records, same seeds, same LLM config; the flag is the ONLY
  difference.
- **Synthetic situations needing coverage** (from the §4.2 library — PR 3
  subset per baseline): repeated collapse with one fingerprint; multiple
  distinct fingerprints; invalid high raw score without collapse prose;
  conflicting gate results (one gate failed, others passed);
  near-threshold values (unique_count 20–30 around threshold 25);
  recovery — healthy round after repeated failures; semantically
  equivalent repeated proposal; missing legacy fields. Excluded and why:
  incumbent-improvement/no-improvement scenarios (PR 1's subset —
  orthogonal claim); routing outcomes (Candidate B — no routing changes
  here).
- **Behaviors requiring real-training confirmation (L3)**: a REAL gate
  failure's evidence reaches the next iteration's proposer context
  (artifact-verified, not prompt-inspected), and the proposal changes
  materially vs the failed round; end-to-end provenance of the carried
  history across a chain resume. L3's role is delivery + decision-change
  confirmation ONLY — with 1–2 iterations it cannot and must not ground
  a statistical valid-round-rate claim (§1).
- **Failure modes to record**: fingerprint hallucination (invented
  numbers); stale-evidence substitution (old fingerprint attributed to
  the wrong model/iteration); over-avoidance; format brittleness (LLM
  output schema violations rising under the new blocks); token growth.
- **Evidence sufficient for MERGE** (Layer-1 plumbing, flag OFF): §7.1
  deterministic checks green — merge needs NO behavioral evidence
  because merged agent-facing behavior is unchanged (prompts
  byte-identical per the §3.1 parity claim; artifacts gain
  recording-only provenance).
- **Evidence required before ACTIVATION**: L2 shows treatment beats
  control on the primary metrics with the pre-registered margin (set at
  P3-L2p from pilot variance, documented before the full campaign), no
  worsening of inappropriate-avoidance or schema-violation rates; L3
  confirms delivery + material decision change on the real system;
  operator review.
- **Rollback / redesign trigger**: treatment ≤ control on primary
  metrics, or superficial-compliance rate exceeds genuine-use rate, or
  schema-violation/token-cost regressions — flag stays OFF; findings
  documented; redesign decision goes to the operator.

**Primary metrics** (from the baseline §4.3 candidate list; finalized
here): repeated-collapse-fingerprint rate (per §3.3 signature match,
judged on the proposed config by deterministic rule where possible +
blinded rubric otherwise); semantically-equivalent-repeat rate (rubric);
explicit-acknowledgment rate; material-change rate;
inappropriate-avoidance rate; unsupported-use-claim rate; (L3 only)
next-round HealthGate validity of the executed round.

**Genuine-use rubric** (operator decision, 2026-07-28): a proposal is
NEVER classified as changed solely because its explanation claims it
addressed the fingerprint. The rubric inspects the **actual
proposal/configuration** and asks whether a mechanism relevant to the
observed collapse changed — at minimum one of:

- architecture family;
- output activation;
- normalization scheme;
- loss function/configuration;
- optimizer or training policy;
- another field directly relevant to the observed collapse mode
  (justified case-by-case in the rubric record).

Explanation text is SUPPORTING evidence only: it can upgrade a
mechanism change to "explicitly acknowledged" or reveal an
unsupported-use claim, but it can never substitute for the config-level
mechanism check. The relevance link (which mechanisms count for which
fingerprint class) is pre-registered per scenario at P3-L2p, before the
full campaign — not adjudicated ad hoc after seeing outputs.

## 5. Validation budget (baseline §4.4 — pilot-first; no invented sample sizes)

Numbers marked **TBD-pilot** are set by P3-L2p and recorded here before
the full campaign launches; the table is a contract skeleton, not a
launch authorization.

| Layer | Scenario count | Samples/scenario | LLM calls | Training runs | Wall time | GPU time | API cost | Hard upper bound | Approval |
|---|---|---|---|---|---|---|---|---|---|
| L1 deterministic | n/a (pytest) | n/a | 0 | 0 | minutes | 0 | $0 | n/a | none (free pytest) |
| L2 pilot (P3-L2p) | 2 scenarios × 3 arms (see below) | 3 | ≈ 36 (2 nodes/sample) | 0 (pseudo) | TBD measured | 0 | small — measured | 60 calls | stop-and-show before launch (real LLM) |
| L2 full (P3-L2) | 8 scenarios × **2 arms** | **TBD-pilot** | **TBD-pilot** | 0 (pseudo) | **TBD-pilot** | 0 | **TBD-pilot** | set at P3-L2p | operator approves the sample plan |
| L3 gate (P3-L3) | 1 chain, 2 iters, small scope | 1 (+1 repeat only if ambiguous) | bounded per gate design | 2–4 real trainings, reduced portion | **TBD at gate design** | **TBD** | **TBD** | set in gate doc | **operator approval mandatory** (real LLM + real training; cold-start; docs/gates/ conventions) |

**Pilot diagnostic arm** (operator decision, 2026-07-28 — pilot ONLY):
the pilot runs three arms; the full campaign runs two.

- **Control**: both prompt renderings OFF.
- **Treatment**: both prompt renderings ON.
- **Diagnostic (pilot-only)**: interpreter rendering ON, proposer
  `[HEALTHGATE EVIDENCE]` block OFF — isolates whether failures sit in
  the interpreter leg (fingerprint lost/paraphrased before the proposer
  ever sees it) vs the proposer leg. Expressible without any new
  production surface: each node reads its own input flag (§3.9), so the
  pilot harness sets `InterpretationInput` ON / `ProposalInput` OFF
  directly; the single CLI flag that sets both stays untouched.

The diagnostic arm locates delivery-chain failures; it does NOT enter
the statistical comparison. The full campaign stays two-arm unless the
pilot yields a concrete, documented reason to expand — never expanded
by default.

Sample-size rule (baseline §4.4 verbatim): pilot → estimate variance and
runtime → determine required count → run bounded evaluation. Any change
to the planned counts after launch is documented with rationale — never
silently reduced.

Workspace rule (from §3.9): control and treatment (and diagnostic) runs
use SEPARATE workspaces — the run-invariants lock rejects a flag flip
within one workspace, and the evaluation design needs the separation
anyway for artifact-level auditability.

## 6. Affected locations (from §2 audit; re-verify at P3-CA)

| File | Change |
|---|---|
| `agent/schemas/health_feedback.py` (NEW — CB1) | `GateExecutionStatus` alias, `GateOutcome`, `RoundHealth`, `CollapseFingerprint`, `FingerprintOccurrence`, `CollapseFingerprintHistoryEntry`, `HealthFeedbackRetentionPolicy`, nested metric allowlist, selection/build/bucket/merge functions (§11-CB1) |
| `execute_tools/health_checks/schemas.py` | P3-CA-accepted minimal extractions IN: `severity_of`/`_SEVERITY` (from runner), `CandidateHealthValidity` (from candidate_eligibility), `GateExecutionStatus` alias |
| `execute_tools/health_checks/runner.py` + `candidate_eligibility.py` | import from schemas + compatibility re-exports; ordering logic never duplicated |
| `agent/schemas/interpretation.py` | imports from `health_feedback`; `ModelRunSummary.round_health`; `InterpretationInput.collapse_fingerprint_history`, `.enable_structured_health_feedback`, retention-policy fields (§3.8); `InterpretationOutput` new fields (§3.6, §3.8) |
| `core/run_invariants.py` | three new `_CANONICAL` fields with pre-PR3-compatible defaults (§3.9); docstring resume matrix |
| `nodes/result_interpretation_agent/result_interpretation_agent.py` | `_round_health()` in the summary builder; flag-gated prompt rendering (trajectory line, HealthGate summary section, system-prompt instructions); output-field population; history merge; `_stats` cache entries |
| `agent/schemas/proposal.py` | `ProposalInput.enable_structured_health_feedback` |
| `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` | `_format_healthgate_evidence_block()`; flag-gated splice |
| `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py` | docstring consumed/populated lists |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | thread the flag |
| `workflows/model_exploration.py` | `run_workflow` flag + retention-policy params; carry-forward of `collapse_fingerprint_history`; lock-site pass-through (§3.9) |
| `core/resume.py` | restore the history from the latest interpretation digest (with `.get` default) |
| `sdsc_submission_scripts/run_one_iteration.py` + `run_chain.sh` | CLI flag + retention-policy flags; manifest + run_config stamps; lock-site pass-through |
| Tuner lock site (`nodes/ml_hyperparameter_tune_agent/...`) | lock-site pass-through only (the tuner itself has no PR 3 behavior change) |
| Node/skill `.md` docs (P3-DOC) | `nodes/result_interpretation_agent/*.md`, `nodes/ml_model_proposal_agent/*.md`, `docs/running_chain_test.md` |

Not touched: gate execution (`execute_tools/health_checks/*` behavior),
`configs/health_checks.yaml` thresholds, tuner gate firing, scoring,
`score_vector`, routing of any kind.

## 7. Validation plan (maps to baseline §2.0 PR 3 checkpoints)

### 7.1 Layer 1 — deterministic (P3-V1; all free pytest)

- Schema/unit: `RoundHealth`/`CollapseFingerprint` construction for every
  record class in §3.5's list; signature canonicalization (key order,
  bucketing applied to signature ONLY); raw-metric preservation
  (recompute the signature from stored raw `metrics` and get the same
  string); `human_readable` excluded from equality (two fingerprints
  with different prose, same signature ⇒ match); allowlist bounding.
- Primary-fingerprint selection rule (§3.3): one test per selection
  step — action-consistency picks over config order; counterfactual
  narrows; severity narrows; config order as final tie-break; empty-step
  fall-through (legacy record without the counterfactual field); a
  multi-gate round where the config-order-first gate is NOT the primary.
- Retention policy (§3.8 — operator-required list, all deterministic):
  default window behavior; custom shorter and longer windows; exact
  bucket expiry at the window boundary under the inclusive-total
  definition (`current_iter=5, window=3` ⇒ a bucket at iteration 3
  retained, a bucket at iteration 2 removed; `window=1` retains only
  the current iteration's buckets); windowed-count aggregation over
  retained buckets; model/family
  isolation (fingerprints never migrate across model keys);
  deterministic max-entry trimming (total-order tie-breaks); legacy
  default resolution (missing config ⇒ documented defaults);
  non-positive policy values rejected at schema construction (0 and −1
  for both fields); renderer consumes the RESOLVED policy (no
  module-level constant import — assert via the override-surface
  pattern).
- Typed history entries (§3.8): validation — occurrence bucket
  `count=0` rejected; duplicate/descending occurrence iterations
  rejected; empty `signature`/`check_name` rejected; round-trip through
  digest serialization and resume restores typed entries with intact
  occurrence buckets (not raw dicts).
- Windowed counts from occurrences (§3.8 — operator-required):
  non-contiguous occurrences incl. the canonical example (occurrences
  at iterations 1, 2, 5; `current_iter=5, window=3` ⇒ only the
  iteration-5 bucket retained; windowed count = that bucket's count,
  not 3); expiry removes buckets then drops empty entries; derived
  `windowed_count`/`first_retained_iter`/`last_retained_iter` computed,
  never persisted; prompt-rendered counts equal the derived windowed
  values on a fixture whose lifetime totals differ from them.
- Degraded-merge invariant (§3.10 — operator-required scenario): the
  current iteration produces a NEW fingerprint; the interpreter LLM
  degrades; the output has `is_degraded=True`; the new fingerprint IS
  merged into the output history with a current-iteration occurrence
  bucket; prior history remains intact; LLM commentary fields stay
  empty per the degraded contract.
- Representative-observation rule (§3.8): two observations with the
  same signature but different raw floats (e.g. `dominant_fraction`
  0.9612 then 0.9634) merge into one entry whose `metrics` equal the
  LATER observation's raw values; recompute-from-raw still reproduces
  the stored signature; the earlier observation stays reachable via
  its occurrence bucket's `source_exp_ids`; same-iteration tie broken
  by chronological record order (deterministic on a two-records-one-
  iteration fixture).
- Provenance classification (§3.2 governing rule + §2.5 evidence, with
  fixtures authored from REAL persisted examples of all three
  vintages): genuine legacy artifact (field never present); current
  gates-disabled record; current gated record with empty or partially
  populated result list (must NOT classify as legacy — emptiness is
  never the discriminator); current non-executed/error record;
  mid-vintage record with round fields but no per-gate results
  (round fields preserved verbatim, no fingerprint from prose).
- Evidence precedence (§3.2 governing rule): a hypothetical record
  carrying non-empty persisted `health_gate_results` under an error
  status classifies by its EVIDENCE, never discarded by the status
  rule; per-status routing applies only to the §2.5-proven pre-gate
  statuses.
- Presence-manufacture regression (§2.5): a fresh-authored record and
  its `model_dump()`→`model_validate()` round-trip must classify
  identically on the production paths — guarding the
  `model_fields_set` signal against round-trip manufacture.
- Run-invariants lock (§3.9 matrix): same values resume accepted;
  changed flag rejected; changed window rejected; changed entry limit
  rejected; legacy lock file resolves to OFF + defaults and is
  accepted; all three lock sites pass the fields (regression test
  parses each `build_run_invariants(...)` call — PR 2 pattern).
- Determinism (§3.1 principle 5): structured output fields populated
  correctly on a degraded (`is_degraded=True`) interpretation — LLM
  failure must not affect them; history merge input is the
  deterministic per-round fingerprints, never parsed LLM findings.
- Builder: per-round extraction parallel-list alignment with
  `round_scores` (the PR 2 `round_ordering` tests are the template).
- Prompt plumbing: flag OFF ⇒ interpreter and proposer prompts
  byte-identical to pre-PR3 goldens; flag ON ⇒ blocks present with exact
  values from the records; stale/unrelated evidence not substituted
  (adversarial fixture: two models, distinct fingerprints — assert no
  cross-contamination); legacy/disabled/degraded renderings per §3.10.
- Protocol/wiring: flag threads end-to-end; manifest + run_config stamps;
  resume restores history; pseudo-mode full-loop test (interp → propose)
  with predefined LLM responses asserting the context snapshot contains
  the blocks (dual-mode test per repo convention).
- "No production routing behavior changed": assert `GateAction` handling
  and tuner control flow untouched (no diff outside §6's file list — the
  PR 2 override-surface test pattern).

### 7.1a P3-V1 closure — claim-to-evidence matrix (2026-07-29)

Verdict and run evidence are recorded in §0 (P3-V1 entry). Audit method:
every §7.1 bullet and every operator §1.4 category (A-L) mapped to a
DIRECT test whose assertions were inspected — never inferred from test
proximity. Four gaps found; each closed by a focused test in
`tests/unit/agent/schemas/test_health_feedback_p3v1_audit.py` (6 tests).

| Claim (category) | Direct evidence | Status |
|---|---|---|
| A. Extraction/classification: 8 record classes; presence not emptiness; evidence precedence; no invented verdicts | `test_health_feedback.py::TestProvenance` (9) + `test_round_health_summary.py` vintage suite (8) incl. error-with-evidence → gated; presence-manufacture hazard pinned | proven |
| B. Primary fingerprint: 4-step selection; persisted gate_name/threshold.metric identity; raw kept, signature bucketed; recompute-from-raw; prose excluded; allowlist bounding | `TestPrimarySelection` (6) + `TestFingerprint` (6) | proven |
| C. History/retention: buckets per iter; boundaries; non-contiguous expiry; windowed≠lifetime; drop-after-expiry; deterministic order+trim; latest-8 sources; representative rule; window variants; invalid policy fails | `TestWindowedCounts` (5) + `TestHistoryMerge` (7) + `TestHistoryEntryValidation` (6); incidental-order invariance + composed windowed-vs-lifetime→prompt added at P3-V1 (audit tests) | proven |
| D. Summary boundary: 1:1 alignment; exact fields; no fabricated fingerprints; legacy loadable; pre-PR3 fields unchanged | `test_round_health_summary.py` alignment/backward-compat/round-trip + mixed-stream lockstep audit test | proven |
| E. Deterministic outputs + degraded invariant | `test_health_feedback_outputs.py` (8) — incl. healthy≡degraded field equality (the strongest LLM-independence form) and the operator 5-condition scenario | proven |
| F. Interpreter parity + treatment | goldens committed BEFORE renderer (`23c3fbe` < `2052fa2`, git-order-proven); full-string equality with health data present; `test_health_prompt_rendering.py` (10) | proven |
| G. Proposer parity + treatment + §14.N | REOPENED + FIXED 2026-07-29: the original evidence covered legacy mode only (production gap — pipeline mode missed the block). Now proven on the PRODUCTION path: `test_health_evidence_pipeline.py` (6) — real pipeline run, captured proposing-stage prompts, ON exactness + OFF byte-parity vs legacy payload + exactly-one-stage + §14.N ordering; cross-iteration pipeline workspace case. Legacy-mode evidence (`test_health_evidence_block.py`, 12) retained for the legacy path | proven (both modes) |
| H. Flag/policy/lock matrix + three sites | `test_run_invariants_health_feedback.py` (10) + all-three-sites window-scan regression | proven |
| I. One-directional history flow | write-site count (exactly 2) + no-reverse-construction assertions; healthy≡degraded equality proves fields cannot derive from LLM output; digest-only restore suite (6) | proven |
| J. CLI/shell/run_config/manifest | `test_health_feedback_chain_wiring.py` (12) + shell parity (15) with the two documented overrides; startup rejection ×3 pre-execution | proven |
| K. Three-workspace contract | `test_health_feedback_workspace_cases.py` (4) — context snapshots on ACTUAL prompt strings | proven |
| L. No routing/scientific change | branch diff = exactly the §6 file list (audited `d811226..HEAD`, zero files outside §6 + tests/docs); tuner consumption surface = exactly 2 references per policy field (audit test); gate YAML/checks/runner logic untouched except the approved vocabulary extraction | proven |

Notes recorded during the audit:

- §7.1 "renderer consumes the RESOLVED policy" transformed structurally:
  renderers never need the policy because stored history is
  post-retention; the enforceable form — merge takes policy as a
  REQUIRED parameter; renderers import no retention constant — is now
  asserted directly (audit tests).
- §7.1 "dual-mode pseudo full-loop": covered by the composed
  interp→propose workspace-case tests (predefined LLM responses, real
  production code, context-snapshot assertions) living in `tests/unit`
  rather than the `tests/integration` dual-mode harness — functionally
  equivalent, location noted as a limitation, not a gap.
- pyright strict is CI-only (Node v10 on lilab) — the CI run is the
  type-check source of truth.

### 7.2 Layer 2 — synthetic real-LLM campaign (P3-L2p → P3-L2)

Per §4's contract and §5's budget: pseudo training/scoring with
synthetic gate records implementing the 8 scenarios; both arms driven by
the SAME records with only the flag differing; repeated samples;
metrics + rubric scoring; CI or equivalent uncertainty summary;
hallucinated-use-claims categorized. Scenario fixtures live in
`tests/pseudo_data/` per the pseudo-test infra conventions.

### 7.3 Layer 3 — bounded real gate (P3-L3)

Designed AFTER L2 (its result shapes what needs real confirmation),
against `docs/gates/gate_testing_standard.md`: cold-start, reduced
portion, small `--data_scope` with paired `--health_gate_files` (DS8
twin rule), explicit stop conditions, budget table filled before the
approval request. Success = artifact-verified delivery chain (real gate
failure → persisted record → summary → interpretation digest → next-iter
proposer context snapshot) + material decision change per §4's rubric.

## 8. Scope and non-goals

In scope: everything in §3 (delivery), §4–§5, §7 (validation).

Non-goals (explicit, with owners):

- **No routing/threshold/aggregation changes** — Candidates A + B
  (`candidate_features_v19.md`). This PR never uses fingerprints to
  route, only to inform prompts.
- **No gate-execution changes** — checks, YAML policy, firing points
  unchanged.
- **No tuner-planner changes** — in-run memory_history feedback already
  exists; PR 3 is the interp/proposer boundary. (Any tuner-planner
  fingerprint upgrade is a separate candidate.)
- **No score-formula or scoring-pipeline changes** (frozen TIDMAD
  formula).
- **No cross-chain persistence** beyond the existing digest carry
  (fingerprint DB, cross-run memory → workflow-evolution candidate).
- **Production default stays OFF** until P3-ACT.

## 9. Resolved design decisions (operator, 2026-07-28)

The draft's four open questions were resolved, with four additional
decisions, in the operator revision of 2026-07-28. Recorded here as the
binding record; the design sections above implement them.

- **Q1 — Fingerprint granularity → RESOLVED (§3.3/§3.4).** One primary
  fingerprint per round, selected by the 4-step rule (action
  consistency → counterfactual verdict → blocking severity → config
  order as final tie-break) — NOT simply first-failed-in-config-order.
  Other outcomes stay in `gate_outcomes`. Raw metrics stored separately
  from the bucketed signature so fingerprints are recomputable;
  2-sig-fig bucketing accepted as the INITIAL matching rule.
  `human_readable` is display-only and never participates in equality.
- **Q2 — Recording vs rendering → RESOLVED (§3.1, §3.6).**
  Flag-independent schema population + flag-gated prompt rendering
  approved. Parity claim clarified: flag OFF ⇒ agent-facing prompts
  byte-identical to pre-PR3; persisted artifacts may carry additional
  recording-only structured provenance. All structured fields
  (`per_model_round_health_counts`, `per_model_collapse_fingerprints`,
  `collapse_fingerprint_history`) are populated deterministically from
  `RoundHealth` — the LLM may discuss them but is never their source of
  truth.
- **Q3 — History retention → RESOLVED, amended (§3.8).** A generic,
  CONFIGURABLE bounded retention policy with an explicit configuration
  surface — not a hardcoded window. PR 3 implements only the bounded
  iteration-window policy; initial default equivalent to three
  iterations; deterministic expiry (mechanism superseded by the
  per-iteration-occurrences decision below); repeat counts
  aggregated within the retained window; NO `count >= 3` permanent
  retention (persistent failure memory is future work near
  workflow-evolution, reconsidered from Layer-2 evidence);
  model-attribution preserved; deterministic ordering and trimming;
  legacy config resolves to documented defaults. Policy values are
  recorded in run_config, the iteration manifest, and the
  run-invariants lock. Exact field names/defaults finalized at P3-CA
  after the nearby-convention audit.
- **Q4 — Run-invariants policy → RESOLVED (§3.9).**
  `enable_structured_health_feedback` AND the retention-policy values
  join the run-invariants lock: the flag changes the agent's decision
  context, hence the chain's behavioral policy. Resume matrix: same
  values accepted; changed flag or policy in the same workspace
  rejected; legacy workspace resolves to OFF + defaults; enabling
  treatment on a legacy/OFF workspace requires a new workspace.
  run_config + per-iteration manifest stamps continue. Layer-2 control
  and treatment use separate workspaces.
- **Behavioral-claim precision (§1, §4).** The claim is a tested
  hypothesis — determine WHETHER structured evidence (a) reduces
  repeated collapse fingerprints, (b) reduces semantically equivalent
  repeats, (c) produces real mechanism-level changes, (d) improves
  subsequent HealthGate validity where observable. The bounded L3 Gate
  confirms delivery + meaningful decision change; it is never used
  alone for a statistical valid-round-rate claim.
- **Pilot diagnostic arm (§5).** Full evaluation stays two-arm
  (control = both renderings OFF; treatment = both ON). The pilot adds
  a limited interpreter-ON/proposer-OFF diagnostic arm for locating
  delivery-chain failures only; the campaign expands to three arms only
  on a concrete pilot-derived reason.
- **Genuine-use rubric (§4).** A proposal counts as changed only if the
  actual proposal/configuration changed a mechanism relevant to the
  collapse (architecture family, output activation, normalization,
  loss, optimizer/training policy, or another directly relevant field);
  explanation text is supporting evidence only.
- **Deterministic history flow (§3.1 principle 5).**
  `ExperimentRecord → deterministic RoundHealth → deterministic
  fingerprint/history merge → prompt rendering → LLM interpretation`;
  history is never reconstructed from LLM-generated findings.
- **Per-iteration occurrences (2026-07-28, second revision — §3.8).**
  The lifetime `count/first_seen/last_seen` aggregate was rejected as
  unable to support windowed counts (the 1,2,5/window-3 example);
  history entries store typed `FingerprintOccurrence` buckets;
  windowed count / first / last retained iteration are DERIVED, never
  independently persisted; expiry removes buckets outside the window,
  then drops empty entries; prompt counts and Layer-2 repeated-mode
  metrics use retained occurrences only.
- **Degraded-mode merge invariant (2026-07-28, second revision —
  §3.10).** The earlier "verbatim carry, no growth" wording is
  withdrawn as self-contradictory: the deterministic merge (previous
  typed history + current RoundHealth fingerprints → retention →
  persisted output history) runs regardless of interpreter LLM success
  or degradation; degradation affects LLM commentary only. Real
  current-iteration gate evidence is never lost to an LLM failure.
- **Source-identity precision (2026-07-28, second revision — §3.8a).**
  P3-CA audits whether `model_type` is a sufficiently precise history
  key; if too broad, the top-level key stays for prompt grouping and a
  bounded per-occurrence source identity (`source_exp_ids` and/or a
  deterministic config identity) preserves attribution — unrelated
  configurations are never silently merged under a broad label. Chosen
  identity + payload bound reported before implementation.
- **CB1 import-graph audit (2026-07-28, second revision — §11-CB1).**
  Before `agent/schemas/health_feedback.py` exists, P3-CA maps the
  import graph for `GateAction` / `CandidateHealthValidity` /
  `GateExecutionStatus` / `PersistedHealthGateResult` / `severity_of`,
  selects canonical side-effect-free homes, confirms acyclicity (no
  schema→runner inversion), never duplicates the severity ordering,
  and stops to report if a clean home requires more than a minimal
  extraction.
- **CB5 workspace cases (2026-07-28, third revision — §11-CB5).** An
  ON→OFF flag transition in one workspace is never described or tested
  as a valid pseudo chain (it contradicts the Q4 lock policy). The CB5
  pseudo-integration contract is the three-case form: Workspace A flag
  ON (two iterations, fingerprint flow, stamps); Workspace A resume
  with flag OFF (fails with `RunInvariantsViolation` naming the field
  and both values); separate Workspace B flag OFF from creation
  (pre-PR3 golden prompts, recording-only provenance present, no
  treatment block).
- **Raw-metric provenance in history entries (2026-07-28, third
  revision — §3.8).** Entry-level `metrics`/`human_readable` are
  defined by the representative-observation rule: most recently merged
  observation (highest iteration; chronological record order within an
  iteration), overwritten on merge; signature stability guaranteed by
  bucket membership; earlier observations reachable via
  `source_exp_ids`. Per-occurrence metric storage rejected for payload
  unless the P3-CA payload inspection reports otherwise. *(Rule
  proposed by the implementer to resolve the operator-flagged
  ambiguity; binding upon P3-D approval.)*
- **P3-CA outcome + provenance direction (2026-07-29).** The audit was
  accepted: field-presence (`model_fields_set`) evidence over list
  emptiness, with a presence-manufacture regression test; minimal
  extractions of `severity_of` and `CandidateHealthValidity` into
  `health_checks/schemas.py` with compatibility re-exports;
  `model_type` as the PR 3 history grouping key; latest-8
  `source_exp_ids` per bucket, oldest-first trimming; nested metric
  allowlists authored from real V17 payloads; the
  representative-observation rule confirmed stable (chronological
  order verified across persistence/replay); finalized configuration
  and lock names; the CB1 file scope with `__init__.py` only if
  inspection proves it necessary; bounded source-reference wording.
  Provenance taxonomy deliberately NOT locked to an exhaustive enum:
  the design records the confirmed distinctions (evidence present /
  gates disabled / no gate evaluation / legacy, plus the observed
  mid-vintage partial-evidence case) and the audited
  evidence-precedence order; CB1/CB2 re-inspect and choose the
  smallest typed model, stopping to propose the smallest revision if a
  real case doesn't fit. Governing rule (binding over any taxonomy):
  preserve the strongest evidence actually present in the record;
  never infer gate execution from missing fields; never discard
  explicit gate evidence because of a broad status classification.

## 10. Follow-ups this design anticipates (filed only when confirmed)

- Tuner-planner structured fingerprint feedback (in-run memory_history
  currently carries prose `failure_reason` only) — candidate, not PR 3.
- Fingerprint-driven routing/avoidance automation — Candidate B.
- `#139` error-path ordering provenance interacts with §3.10's
  `not_executed` handling — verify at P3-CA that RoundHealth's legacy
  rules and PR 2's `not_executed` provenance stay consistent on the same
  records.

## 11. Commit plan (detailed — per-commit implementation checklists; operator template, 2026-07-28)

Template rules (binding for every commit block):

- Inspect the relevant code before finalizing each step — never guess
  file paths, interfaces, or behavior; if inspection reveals ambiguity
  or larger scope than this design assumes, STOP and ask before
  changing the plan.
- `[ ]` = not finished; `[x]` only after implemented AND verified with
  recorded evidence (test counts + wall time recorded next to the item).
- Each CB below is the LOGICAL unit; it may split into multiple git
  commits at clean boundaries (split-commit rule), preserving the
  block's DoD on the last split.
- Delivery and behavioral use remain separate concerns; the default is
  flag OFF; production activation is outside these commits entirely
  (P3-ACT, separate evidence + operator approval).
- Before each commit: stop-and-show the exact diff summary, staged file
  list, test evidence, and any deviation from this design.
- Any test that could not be run is recorded with the reason — never
  claimed as passed.
- Update this document immediately after each implementation or test
  checkpoint — never batched.

#### Test scope by development stage (operator principle, 2026-07-29)

Do not run the full repository test suite or wait for a complete CI
run after every commit by default. Use staged validation:

**Before an individual commit** — run only: tests directly covering
the changed behavior; the smallest relevant regression suite for the
touched modules; lint and formatting checks on touched files; type
checking where locally available and proportionate to the change.
Record exactly what was and was not run.

**After a logical commit block** — run a broader targeted regression
across the modules integrated by that block.

**Before opening, updating for final review, or merging the PR** — run
the complete PR validation plan: full required unit/regression suites;
blocking type checks; repository lint/format checks; required pseudo
integrations; any approved Gate validation.

A full CI run does not need to finish before every intermediate
commit. Waiting for CI is required only when the result is necessary
to validate an environment-specific risk, a locally unavailable
blocking check, or the final PR state. (On lilab, pyright is the
standing locally-unavailable blocking check — Node v10 — so a CI wait
is justified when a change plausibly affects typing; otherwise
continue working and read the verdict when it lands.)

PR 3 CI usage (operator, 2026-07-29 — draft PR #145 kept open so
pyright can run): push once per completed commit block, not per
micro-commit; CI runs asynchronously; no blocking watcher after a push
(one exception granted: the first pyright pass over the new CB1 schema
module); continue working unless CI reports a relevant failure; review
the latest CI result at the next block boundary; run and wait for the
full final CI only before final PR review or merge.

Governing principle:

> Validation should be proportional to the scope and risk of the
> current change. Local commit evidence is targeted; full-repository
> evidence is collected before PR completion.

### CB1 — schemas + deterministic logic (`agent/schemas/health_feedback.py`)

**Goal.** Create the complete typed data model and ALL deterministic
logic of PR 3 — fingerprint selection, signature bucketing, history
merge/retention — as a pure, consumer-free module. This commit exists
first because every later block only WIRES this logic; isolating it
makes the determinism contract (§3.1 principle 5) testable without any
node in the loop (the `agent/schemas/ordering.py` single-resolver
precedent from PR 2).

**Scope.** New module `agent/schemas/health_feedback.py` (placement
confirmed at P3-CA): `GateExecutionStatus` alias, `GateOutcome`,
`RoundHealth`, `CollapseFingerprint`, `FingerprintOccurrence`,
`CollapseFingerprintHistoryEntry`, `HealthFeedbackRetentionPolicy`,
the per-check metric allowlist, `select_primary_gate_outcome()`,
`build_collapse_fingerprint()`, `bucket_signature()`,
`merge_fingerprint_history()`. `execute_tools/health_checks/schemas.py`
touched ONLY if the `GateExecutionStatus` extraction lands there
(P3-CA). Non-goals: no consumer wiring, no prompt changes, no
`ModelRunSummary` change yet. Depends on: P3-CA (legacy signal,
naming, placement, source identity, import graph).

**Import-graph precondition** (operator requirement, 2026-07-28 —
resolved at P3-CA BEFORE this module is created): inspect the complete
import graph for `GateAction`, `CandidateHealthValidity`,
`GateExecutionStatus`, `PersistedHealthGateResult`, and `severity_of`.
A schema/pure-logic module must not depend on an execution RUNNER
(`execute_tools/health_checks/runner.py` currently hosts
`severity_of`/`_SEVERITY`) if that creates an inverted dependency or
an import cycle. Preference: canonical enums + severity ordering in a
low-level side-effect-free shared module; the severity ORDERING is
never duplicated, and no broad module reorganization is performed
silently — if the clean home requires moving code beyond a minimal
extraction, STOP and report the required scope change first.
**RESOLVED at P3-CA (§2.5, operator-accepted 2026-07-29)**: canonical
home = `health_checks/schemas.py` (stdlib+pydantic only);
`severity_of`/`_SEVERITY` and `CandidateHealthValidity` move in;
`runner`/`candidate_eligibility` re-export; graph acyclic; the
classifier FUNCTION stays in `candidate_eligibility` (only CB2's node
code calls it, keeping CB1's imports minimal); package-`__init__`
self-registration side effect is pre-existing, not a new edge;
`__init__.py` touched only if implementation inspection proves it
necessary.

**Implementation plan.**

- [x] Minimal extractions into `health_checks/schemas.py`
      (`severity_of`/`_SEVERITY` from runner, `CandidateHealthValidity`
      from candidate_eligibility, `GateExecutionStatus` alias);
      compatibility re-exports at both origin modules; serialized
      values unchanged *(2026-07-29: PersistedHealthGateResult
      execution_status retyped to the alias — same Literal values;
      runner re-export via the redundant-alias idiom `import X as X`
      (F401-exempt, no noqa); identity asserted across all three
      import paths (runner / candidate_eligibility / package init);
      ruff + format clean; health_checks suite 230 passed 0.32s;
      health_checks+core 700 passed 3.33s)*
- [x] Models per §3.2/§3.3/§3.8 with the §9 type/validation decisions
      *(2026-07-29, `agent/schemas/health_feedback.py`:
      CandidateHealthValidity + GateAction + GateExecutionStatus reused
      from health_checks.schemas; default_factory everywhere; ge=1 /
      min_length=1; occurrence ascending-unique model_validator.
      Provenance = 5-value Literal — every value maps to an observed
      §2.5 record shape, none speculative; docstring records the
      per-value evidence. Two CB1 implementation decisions recorded:
      (1) fingerprint.check_name holds the persisted gate_name — the
      check's registered name is not persisted, so the gate id is the
      strongest identity actually present; (2) blocking allowlist keyed
      by the persisted threshold.metric name, self-describing, no
      gate-id mapping table)*
- [x] Metric allowlist authored from the REAL V17 payload *(real names
      differ from design shorthand: n_unique_int8_values /
      output_std_mv / dominant_mode_fraction; worst-case via
      aggregate_statistics minimum|maximum per collapse direction;
      exactness from threshold.unit=="count"; recording allowlist =
      6 verified scalar keys, per-file trees excluded)*
- [x] `select_primary_gate_outcome()` — 4-step narrowing with
      empty-step fall-through *(6-case test class green incl.
      config-order-first-is-NOT-primary and missing-counterfactual
      fall-through)*
- [x] `build_collapse_fingerprint()` — raw metrics stored, bucketed
      signature derived *(0.9612/0.9634 → same signature, raw values
      preserved; recompute-from-raw test; no-allowlisted-metric →
      None, nothing invented from prose)*
- [x] `merge_fingerprint_history()` — inclusive-window expiry, count
      aggregation, model-key isolation, total-order sort, trim
      *(canonical 1,2,5/window-3 example; boundary iter-3-retained/
      iter-2-removed; window=1; representative-observation overwrite;
      latest-8 source_exp_ids; purity — inputs not mutated)*
- [x] Module docstring: determinism contract + governing rule verbatim

**CB1 evidence (2026-07-29)** — exact commands (repo venv python):

```text
pytest tests/unit/agent/schemas/test_health_feedback.py -q
    → 39 passed in 0.10s
pytest tests/unit/agent/schemas tests/unit/execute_tools/health_checks -q
    → 438 passed in 1.26s          (regression, both suites)
pytest tests/unit/execute_tools/health_checks/ -q
    → 230 passed in 0.32s          (post-extraction, CB1-a)
pytest tests/unit/execute_tools/health_checks/ tests/unit/core/ -q
    → 700 passed in 3.33s          (post-extraction incl. resume, CB1-a)
ruff check / ruff format --check   → clean on all touched files
```

Re-export identity asserted across all three import paths (runner /
candidate_eligibility / package `__init__` — same objects). Round-trip
presence-manufacture hazard pinned as an explicit test
(`test_round_trip_manufactures_presence_documented_hazard`).
Evidence-driven deviations from design shorthand (operator-approved
2026-07-29): fingerprint identity = persisted `gate_name` (no
gate-id→check-name mapping is invented or maintained); allowlist keyed
by persisted `threshold.metric` with `threshold.unit` driving
exact-vs-bucketed rendering — the REAL persisted vocabulary
(`n_unique_int8_values` / `output_std_mv` / `dominant_mode_fraction`),
not the design's shorthand names. CB2 and P3-V1 remain open.

**Validation plan.** Unit only (new
`tests/unit/agent/schemas/test_health_feedback.py`): selection-rule
suite (6 cases, §7.1); signature canonicalization + recompute-from-raw;
`human_readable` equality exclusion; occurrence-bucket validation
negatives; windowed-count-from-occurrences suite incl. the
non-contiguous 1,2,5/window-3 example and derived-never-persisted
assertions (§7.1); retention suite (boundary example, bucket expiry
then entry drop, non-positive rejection); merge determinism (same input
twice ⇒ identical output, key isolation, current-iteration bucket
append/increment). No integration tests (no consumers yet). No
backward-compat surface (new module).

**Acceptance criteria.** Every §7.1 item attributable to pure logic has
a green test with recorded count + wall time; `signature` recomputed
from stored raw `metrics` reproduces the stored string exactly on every
fixture; the 4-step rule selects the documented gate on the multi-gate
fixture where config-order-first is the wrong answer; merge of the
boundary example retains iters 3-5 and expels 2; ruff + pyright-in-CI
clean.

**Failure/edge cases.** Empty failed-gate set (healthy round) ⇒ no
fingerprint, never an exception; all candidates eliminated at a
narrowing step ⇒ step skipped, not empty selection; unknown metric keys
⇒ dropped by allowlist (documented drop), never a crash; non-numeric
metric values ⇒ carried as str in metrics, excluded from bucketing.

**Verification commands.** `.venv/bin/python -m pytest
tests/unit/agent/schemas/test_health_feedback.py -q` (+ the schemas
suite for regressions). Evidence recorded here on completion.

**Commit boundary.** Independently reviewable (one new module + its
tests + at most the alias extraction); no unrelated cleanup.

### CB2 — summary-builder extraction (`RoundHealth` into `ModelRunSummary`)

**Goal.** Carry per-round health across the tune→interp boundary — the
single drop point identified in §2.2. Separate from CB1 because this is
the first consumer wiring and the first place legacy detection runs
against REAL record shapes; separate from CB3 because it changes no
prompt.

**Scope.** `agent/schemas/interpretation.py`
(`ModelRunSummary.round_health`, imports from `health_feedback`);
`nodes/result_interpretation_agent/result_interpretation_agent.py`
(`_round_health()` beside `_round_ordering()`, called in the existing
per-record loop at `tuning_output_to_model_run_summary`);
`agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py`
(docstring consumed/populated lists). Non-goals: no prompt rendering,
no output fields, no flag. Unchanged behavior: every existing
`ModelRunSummary` field byte-identical. Depends on: CB1 (the legacy
signal + evidence-precedence order are P3-CA-resolved — §2.5, §3.2).

**Implementation plan.**

- [x] Re-inspect lifecycle + record shapes (§3.2 process step 1)
      *(2026-07-29: records reach the builder as models validated FROM
      dicts on both production paths — tuner `:4094`/`:4130` fresh,
      `model_exploration.py:254` reparse — so `model_fields_set`
      mirrors authored keys; gate config is process-cached
      (`_CACHED_GATES`) so per-record `classify_candidate_health` is
      cheap, matching the existing per-record `is_valid_candidate`
      precedent; no record shape outside the CB1 provenance model
      surfaced — stop-and-propose not triggered)*
- [x] `_round_health(record)` — classification per the §3.2
      evidence-precedence order; validity via
      `classify_candidate_health` (reuse); fingerprint via CB1 builders
      *(placed beside `_round_ordering`, same lazy-import precedent;
      gate evidence passed to builders only under `gated` provenance;
      `failure_reason` carried verbatim for every provenance with the
      §2.5 field-overload finding documented in the docstring — the
      provenance label is what disambiguates exception text from gate
      evidence)*
- [x] `round_health` populated parallel to `round_scores` (alignment
      guaranteed by the shared loop) *(field added after
      `round_ordering` on ModelRunSummary, default_factory=list —
      legacy digests without the field validate to empty)*
- [x] Protocol docstring update *(consumed list names round_health)*

**CB2 evidence (2026-07-29)** — exact commands (repo venv python):

```text
pytest tests/unit/agent/result_interpretation_agent/test_round_health_summary.py -q
    → 12 passed in 0.93s   (new suite: 8 vintage/precedence cases +
                            alignment + backward-compat + JSON
                            round-trip + malformed-entry negative)
pytest tests/unit/agent/result_interpretation_agent \
       tests/unit/agent/schemas tests/unit/agent/protocols -q
    → 533 passed in 1.28s  (block regression)
ruff check / ruff format --check → clean on the 4 touched files
```

NOT run at this stage (per the staged-validation principle): full repo
suite, tuner suite, pseudo integrations — deferred to P3-V1/PR-final.
CB1 CI on draft PR #145 (run 30425698414, head `2dfaf63`): SUCCESS —
first pyright pass over the new module clean.

**Validation plan.** Unit: `_round_health` across the §3.5 record-class
list + the §7.1 provenance-classification suite with fixtures authored
from REAL persisted examples of all three §2.5 vintages (read the
workspace artifacts — check code, don't guess); the §7.1
evidence-precedence and presence-manufacture regression tests;
parallel-list alignment (PR 2 `round_ordering` test as template).
Backward-compat: summary built from a pre-PR3 `HyperparamTuningOutput`
fixture validates and leaves all existing fields unchanged. Negative:
malformed `health_gate_results` entries ⇒ diagnosable error, not
silent misclassification.

**Acceptance criteria.** The §7.1 provenance suite green, incl. the
explicit tests that an empty-list current gated record does NOT
classify as legacy and that persisted evidence is never discarded by a
status rule; `len(round_health) == len(round_scores)` on every fixture
incl. attempt-failure records; existing interpreter unit suite green
unchanged (count recorded).

**Failure/edge cases.** Record with gates enabled but zero configured
gates ⇒ `gated` with empty outcomes (not legacy — the signal decides);
`not_executed`-style attempts ⇒ status verbatim, no fingerprint;
partially populated result list ⇒ outcomes for what exists, no
invention.

**Verification commands.** Interpreter unit suite + new tests;
counts/time recorded here.

**Commit boundary.** Schema field + one pure function + docstring; no
prompt diffs anywhere in the commit.

### CB3 — interpreter delivery

**Goal.** The interpreter leg of delivery: flag-gated prompt rendering
(§3.6), deterministic output fields + history merge (§3.8), degraded
path. One commit because these are one node's coherent surface;
prompts and outputs must land together for the parity claim to be
testable against a single node state.

**Scope.** `agent/schemas/interpretation.py` (`InterpretationInput`
flag + retention policy + history carry-forward;
`InterpretationOutput` counts/fingerprints/history fields);
`result_interpretation_agent.py` (trajectory line, `### HealthGate
summary` section, system-prompt instruction block — all flag-gated;
deterministic population around the LLM calls; `_stats` cache entries;
degraded-path carry). Non-goals: proposer untouched; no CLI. Depends
on: CB1, CB2.

**Implementation plan.**

- [x] Goldens captured from PRE-change code + parity scaffold
      *(2026-07-29, CB3-a: 3 golden files rendered at `f3a0b8c` clean
      tree — per-model prompt on a collapse-heavy summary WITH
      round_health populated, on a legacy summary, and the per-model
      system prompt; `test_health_prompt_parity.py` 3 passed 0.89s
      against them pre-change, exact string equality)*
- [x] Input/output schema fields (typed history, `default_factory`)
      *(CB3-b: InterpretationInput gains the flag, the two retention
      knobs (`ge=1`, active_model_* convention) with a
      `health_feedback_retention_policy()` resolver method, and the
      typed history carry; InterpretationOutput gains the three
      deterministic fields)*
- [x] Flag OFF short-circuit — prompt builders byte-identical
      *(golden string equality holds POST-change — the renderer now
      contains the flag-gated code and parity still passes)*
- [x] Flag ON rendering (§3.6 items 1-3) *(CB3-c: trajectory
      `[GATE {action} — {signature-or-verbatim-failure_reason}]`
      labels with `score=invalidated`; `### HealthGate summary`
      section — validity counts, distinct fingerprints ×count with
      round indices, best-round recording diagnostics, no empty
      headers; `HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS` appended to the
      per-model system prompt — verbatim-fingerprint,
      invalid-high-score-is-failure, no-verdict-from-absence,
      no-cross-model-transfer rules)*
- [x] Deterministic population + `merge_fingerprint_history` call
      *(CB3-b: `_collect_health_evidence()` + merge computed BEFORE
      the LLM try-block, threaded into the cold-start, healthy, AND
      degraded output dicts — the §3.10 invariant is structural)*
- [x] Degraded path *(operator 5-condition scenario green: new
      fingerprint merged with current-iteration bucket under
      `is_degraded=True`, prior history intact, commentary empty;
      plus a healthy-vs-degraded field-equality test)*
- [x] `_stats` cache entries *(round_health_counts +
      collapse_fingerprints on the deterministic side of the cache)*

**CB3 evidence (2026-07-29)** — exact commands (repo venv python):

```text
pytest tests/.../test_health_prompt_parity.py -q     → 3 passed 0.90s
    (goldens captured at f3a0b8c PRE-change; equality re-verified
     POST-change — the strong form: health data present, flag OFF,
     byte-identical)
pytest tests/.../test_health_feedback_outputs.py -q  → 8 passed 0.98s
    (3 initial failures were TEST bugs — expected counts misread
     classify_candidate_health: a success round with an empty gate
     list is UNKNOWN by the classifier's missing-required-gates rule,
     not invalid; production verdicts were correct; assertions fixed)
pytest tests/.../test_health_prompt_rendering.py -q  → 10 passed 0.94s
pytest tests/unit/agent/result_interpretation_agent \
       tests/unit/agent/schemas tests/unit/agent/protocols -q
    → 554 passed 1.47s   (block regression)
ruff check + format --check → clean
```

NOT run at this stage: full repo suite, tuner suite, pseudo
integration (deferred to P3-V1); synthesis-prompt rendering unchanged
by design (§3.6 scopes items 1-3 to the per-model call).

**Validation plan.** Unit: flag OFF ⇒ prompt strings byte-identical to
goldens captured from pre-CB3 code (parity claim, exact string
equality); flag ON ⇒ blocks present with exact record values;
cross-contamination fixture (two models, distinct fingerprints);
legacy/disabled/degraded renderings (§3.10); the §7.1 degraded-merge
scenario (new fingerprint + LLM degradation + `is_degraded=True` ⇒
fingerprint merged with a current-iteration bucket, prior history
intact, commentary empty); history merge invoked with deterministic
inputs (assert via injected fixture, not LLM mock output). Pseudo
integration: interp node in pseudo mode, both flag states. Negative:
history entry validation failures surface at input construction, not
mid-run.

**Acceptance criteria.** Byte-identical parity proven by string
equality against captured goldens (not by absence of code changes);
every structured output field on a degraded-interpretation fixture
equals the deterministically expected value; renderer receives the
policy as a parameter (grep-style assertion that no module constant is
imported — override-surface pattern).

**Failure/edge cases.** Empty history + healthy rounds ⇒ no HealthGate
section under flag ON (no empty header); missing carry-forward field in
a legacy digest ⇒ empty history via default; LLM omitting/garbling
fingerprints in findings ⇒ output fields unaffected (deterministic
source).

**Verification commands.** Interpreter suite + schema suite;
counts/time recorded here.

**Commit boundary.** One node + its schemas; no proposer, chain, or
lock changes.

### CB4 — proposer delivery

**Goal.** The proposer leg: flag-gated `[HEALTHGATE EVIDENCE]` block
(§3.7). Separate from CB3 so each node's parity is reviewable in
isolation and the pilot's diagnostic arm (interp-ON/proposer-OFF) maps
to a clean commit boundary.

**Scope.** `agent/schemas/proposal.py` (`ProposalInput` flag);
`ml_model_proposal_agent.py` (`_format_healthgate_evidence_block()`,
flag-gated splice);
`agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`
(thread the flag). Non-goals: §14.N exhaustion block untouched; no
routing. Unchanged: prompt byte-identical flag OFF. Depends on: CB3
(reads its output fields).

**Implementation plan.**

- [x] Goldens captured from PRE-change code + parity scaffold
      *(CB4-a `66efed8`, golden rendered at clean `2052fa2`: full
      reasoning prompt from the STRONG typed fixture — real
      InterpretationOutput.model_dump with two disjoint models
      (diversity vs std collapse), multi-bucket retained history,
      §14.N GateExhaustionInfo pinned inside the golden AND by a
      standalone regression; exact full-string parity with the
      structured fields PRESENT and flag OFF; leakage assertions
      supplement, never replace, the full-string test)*
- [x] `ProposalInput` flag field *(default OFF; docstring states the
      informational-only, never-routing contract)*
- [x] Block renderer *(`_format_healthgate_evidence_block()`: model-
      grouped exactly as CB3 grouped it, nothing unlabelled; current-
      iteration evidence vs retained history explicitly separated;
      retained-window counts BY CONSTRUCTION — stored history is
      post-retention, so bucket sums are window counts and bucket
      iterations are ABSOLUTE tags (spec allows exact-or-relative;
      absolute needs no new wiring); "Representative observation:"
      labelling per §3.8; bounded source exp_ids surfaced; six-rule
      closing instruction (bounded, <45 lines total); malformed
      hand-built history entry ⇒ diagnostic ValueError naming the
      model; legacy/empty ⇒ "" with no header; rendered AFTER and
      visibly separate from the untouched §14.N block)*
- [x] Protocol threading *(param default False; included in the result
      dict only when True so the schema default governs legacy
      callers)*

**Validation plan.** Unit: flag OFF golden parity (string equality);
flag ON block content exactness incl. model attribution (fingerprint
of model A never rendered under model B); legacy interpretation dict
(fields absent) ⇒ no block, no error; empty-fingerprint iteration ⇒ no
empty header. Pseudo integration: interp→propose edge, both flag
states, context snapshot asserted. Negative: malformed history entries
in a hand-built dict ⇒ diagnosable error.

**Acceptance criteria.** Parity by golden string equality; the
attribution test passes; the §14.N block's output is byte-identical
before/after this commit on the same fixture.

**CB4 evidence (2026-07-29)** — exact commands (repo venv python):

```text
pytest tests/.../ml_model_proposal_agent/test_health_prompt_parity.py \
       tests/.../ml_model_proposal_agent/test_recent_gate_exhaustions.py -q
    → 27 passed 1.01s   (CB4-a: parity 3 + full existing §14.N suite;
                          golden source commit 2052fa2, clean tree)
pytest tests/.../test_health_evidence_block.py \
       tests/.../test_health_prompt_parity.py -q
    → 15 passed 0.93s   (CB4-b flag-ON exactness: counts, signatures,
                          retained-window 3-across-iters-3,5 not
                          lifetime; representative-observation labels;
                          bounded source ids; closing rules; ordering
                          after §14.N; adversarial two-model
                          non-contamination; legacy/empty/counts-only;
                          malformed → ValueError; §14.N byte-identical
                          both flag states; parity re-verified
                          POST-change)
pytest tests/unit/agent/ml_model_proposal_agent \
       tests/unit/agent/schemas tests/unit/agent/protocols -q
    → 803 passed 1.58s  (block regression)
ruff check + format --check → clean on all touched files
```

Deferred to P3-V1 (recorded per the staged-validation principle): full
repository suite, tuner suite, pseudo interp→propose integration with
context-snapshot assertion, workflow tests. Deviation note: iteration
tags rendered ABSOLUTE (spec permits exact-or-relative) — relative tags
would need the current iteration number, which the interpretation dump
does not carry; absolute tags are fully deterministic from bucket data
alone and avoid inventing CB5 wiring early.

**Failure/edge cases.** Interpretation from a flag-OFF workspace fed to
a flag-ON proposer (mixed inputs can only occur in hand-built tests —
the lock forbids it in production): renders from whatever recorded
fields exist; documented in the renderer docstring.

**Verification commands.** Proposer suite + protocol tests;
counts/time recorded here.

**Commit boundary.** One node + one protocol; no chain wiring.

### CB5 — chain/workflow wiring, lock, CLI, stamps

**Goal.** Make the feature operable and POLICY-LOCKED end-to-end:
workflow params, cross-iteration carry, resume restore, CLI flags,
run_config + manifest stamps, run-invariants fields at all three lock
sites. Last because it touches every operator surface and depends on
every schema before it.

**Scope.** `core/run_invariants.py` (three `_CANONICAL` fields,
defaults per §3.9, docstring matrix); tuner lock site,
`workflows/model_exploration.py` (params, carry-forward, lock),
`sdsc_submission_scripts/run_one_iteration.py` + `run_chain.sh` (CLI,
stamps, lock); `core/resume.py` (typed history restore). Non-goals: no
behavior change with defaults (flag OFF + default policy ⇒ lock
equality with pre-PR3 expectations must hold for legacy workspaces).
Depends on: CB1-CB4.

**Revised commit boundaries (operator, 2026-07-29, post-audit)**:
CB5-a = canonical lock policy + tuner pass-through (workflow/chain
sites intentionally rely on builder defaults — an INTERMEDIATE state,
not completed three-site propagation; the all-three-sites regression
is deferred to CB5-c). CB5-b = workflow + resume carry. CB5-c = chain
CLI + final stamps + all-three-sites regression + the three approved
workspace cases (the end-to-end legacy+CLI-ON rejection belongs here —
the CLI surface does not exist earlier).

**Implementation plan.**

- [x] CB5-a: `RunInvariants` three fields + `_CANONICAL` + docstring
      resume matrix; `build_run_invariants` params (defaults keep every
      pre-PR3 call site producing an unchanged OFF/3/8 lock);
      `HyperparamTuningInput` three pass-through fields (tuner has NO
      PR 3 behavior — lock + stamp only); tuner lock call passes all
      three explicitly; tuner run_config stamps the three POLICY values
      (policy only — per-round evidence stays in records/digest, never
      duplicated). *(2026-07-29 evidence: new
      `test_run_invariants_health_feedback.py` 10 passed 0.09s — same
      policy accepted; changed flag rejected naming field + both
      values; changed window rejected; changed max-entries rejected;
      legacy lock loads OFF/3/8 and validates; ON-over-legacy rejected;
      tuner lock-call + run_config surface assertions; builder-default
      equivalence. Block regression core+schemas+tuner-suite: 1 failure
      diagnosed as a TEST-CONTRACT update — `test_lock_file_is_plain_json`
      pins the exact on-disk key set and legitimately grows by the
      three approved fields (same evolution it records for PR 2);
      after the update core suite 480 passed 2.99s; full regression
      1382 passed 177s pre-fix, tuner suite unaffected. ruff + format
      clean.)*
- [x] CB5-b: Workflow: params threaded, history carried, degraded-safe;
      workflow lock call passes the policy explicitly *(2026-07-29:
      `run_workflow` gains the flag + the two knobs + typed
      `restored_collapse_fingerprint_history` (all pre-PR3-default);
      workflow lock call passes the policy triple; carry is
      one-directional and has exactly two write sites — restored seed
      and interpreter-output replacement (asserted by source-surface
      test incl. a no-reverse-construction check); interpreter input
      + proposer protocol threading. Degraded-safe by CB3
      construction: the interpreter's degraded output still carries
      the merged history, so the loop replacement is total.)*
- [x] CB5-b: Resume: typed entries restored from digest *(2026-07-29:
      `load_latest_fingerprint_history` sibling loader, latest-wins —
      each digest is already the merged post-retention history, so
      concatenation would double-merge; `RestoredState` typed field +
      population. Failure policy split recorded: FILE-level problems
      warn+skip like every sibling loader; DATA-level corruption inside
      a parseable digest raises a diagnostic ValueError naming iter +
      model per the §11-CB5 failure contract — deterministic policy
      data is never silently dropped. Legacy digest → {} via .get.)*

**CB5-b evidence (2026-07-29)** — exact commands (repo venv python):

```text
pytest tests/unit/core/test_resume_fingerprint_history.py \
       tests/unit/workflows/test_health_feedback_wiring.py -q
    → 11 passed 0.93s  (typed round-trip; latest-wins; legacy empty;
                         missing-file soft-fail warning; corrupted
                         entry raises naming iter+model; first-iter
                         short-circuit; signature defaults; workflow
                         lock/interp/proposer threading; carry
                         one-directionality with write-site count)
pytest tests/unit/core tests/unit/workflows \
       tests/unit/agent/result_interpretation_agent -q
    → 959 passed 14.67s  (block regression)
ruff check + format → clean
```

One test fix during authoring (diagnosed before change): the carry
one-directionality test used whitespace-exact source matches that
`ruff format` legitimately collapsed — test made format-robust; the
production wiring was correct. run_one_iteration forwarding of
`state.collapse_fingerprint_history` is CB5-c (chain wiring).
- [x] CB5-c: CLI flags + `run_chain.sh` passthrough *(2026-07-29:
      three argparse flags with startup retention validation in
      `normalize_args` — Pydantic ge=1 via the resolved policy, routed
      through the shared `parser.error` path so an invalid value exits
      non-zero BEFORE any resume mutation or LLM work; `_chain_common.sh`
      vars + parse arms + forward-when-set (unset policy reproduces
      pre-PR3 argv byte-identically); parity contract extended — the two
      retention knobs registered in `SHELL_DEFAULT_OVERRIDES` with the
      documented shell-""≡omit vs Python-3/8 rationale)*
- [x] CB5-c: run_config + per-iteration manifest stamps *(run_config
      stamped at CB5-a; `write_manifest` gains `health_feedback_policy`
      — stamped on EVERY branch (completed/no_records/failed) so failed
      iterations stay auditable; policy only, no per-round evidence)*
- [x] CB5-c: lock-collision closure *(the CB5-b audit gap found during
      implementation: the workflow threads tuner inputs through
      `ml_model_valid_to_ml_model_tune`, which lacked the policy triple
      — a flag-ON workflow + OFF-defaulted tuner would have written
      contradictory locks, the exact PR 2 failure mode. Protocol +
      workflow tune-call now thread all three; chain lock call passes
      them; the ALL-THREE-SITES regression (window-scan over every
      `build_run_invariants(` call) pins it)*
- [x] CB5-c: three approved workspace cases *(composed end-to-end
      pseudo over real components, mock LLM only; context snapshots
      asserted on ACTUAL prompt strings: Case 1 — ws A flag-ON, iter-1
      interpreter digest → typed restore → iter-2 merge shows buckets
      [1, 2] → the iteration-2 PROPOSER prompt contains
      "- {SIG}: 2 occurrence(s) across iteration(s) 1, 2"; manifest and
      lock policy stamps agree. Case 2 — ws A resumed OFF →
      RunInvariantsViolation naming the field + locked=True vs this
      run=False. Case 3 — ws B OFF from creation: the actual bridge
      prompts carry no treatment text while the digest carries the
      recording-only structured provenance; proposer prompt has no
      block and no signature)*

**CB5-c evidence (2026-07-29)** — exact commands (repo venv python):

```text
pytest tests/.../test_health_feedback_chain_wiring.py -q
    → 12 passed 0.98s   (three-site lock regression; CLI defaults/parse/
                          startup rejection ×3; run_workflow forwarding
                          incl. typed history; manifest policy stamp +
                          legacy-None)
pytest tests/.../test_health_feedback_workspace_cases.py -q
    → 4 passed 0.97s    (the three operator cases + stamp agreement)
pytest tests/unit/scripts/test_chain_consistency.py -q
    → 15 passed 1.14s   (shell parity incl. the two documented overrides)
pytest tests/unit/sdsc_submission_scripts tests/unit/scripts \
       tests/unit/workflows tests/unit/core tests/unit/agent/protocols -q
    → 980 passed 15.04s (block regression)
bash -n _chain_common.sh → syntax ok; ruff + format clean
```

Authoring-time fixes (each diagnosed before change): startup-validation
insertion initially landed outside the existing try/except (syntax);
missing --run_name in CLI test fixtures; window-scan replacing a
non-greedy regex defeated by inner parens; manifest iter_dir not created
by a test. One production improvement made during test authoring: the
manifest policy stamp moved from the completed-branch dict to a single
post-branch assignment so ALL manifest branches carry it.

**Validation plan.** Unit: the §3.9 five-row resume matrix as five
tests; three-site regression test (parse each
`build_run_invariants(...)` call — PR 2 pattern); resume round-trip
restores TYPED entries; CLI parsing (invalid retention values rejected
before execution — exits with the Pydantic error, no partial run).
Pseudo integration (operator correction, 2026-07-28 — an ON→OFF
transition in ONE workspace is NEVER described or tested as a valid
pseudo chain; the lock rejects it. Three explicit cases instead):

1. **Workspace A, flag ON**: run two iterations; verify iteration-1
   fingerprints reach iteration 2's proposer context; verify manifest
   and run_config stamps.
2. **Workspace A, attempted resume with flag OFF**: startup fails with
   `RunInvariantsViolation`; the message identifies the changed field
   and both values.
3. **Separate Workspace B, flag OFF from creation**: prompts match
   pre-PR3 goldens; recording-only structured provenance is present in
   artifacts; no treatment prompt block appears anywhere.

Backward-compat: legacy lock file loads to OFF + defaults and
resumes cleanly. Real-training Gate: NONE in this block — L3 is
separately designed and operator-approved (P3-L3, §7.3); never
launched from a commit checklist.

**Acceptance criteria.** Legacy lock file + default invocation ⇒ lock
equality holds (no forced new workspace for existing chains); each
matrix row observable as a pass/`RunInvariantsViolation`; a pseudo
chain's iter-2 proposer context snapshot contains iter-1's fingerprint
with correct model attribution and relative iteration tag.

**Failure/edge cases.** Flag flip on resume ⇒ startup rejection with a
message naming the field and both values; corrupted history in a
digest ⇒ validation error at restore naming the entry, not silent
drop; partial CLI (flag without policy) ⇒ documented defaults;
`run_chain.sh` not forwarding a flag ⇒ caught by the shell-parity test
class (PR 1/PR 2 precedent).

**Verification commands.** Tuner + workflow + scripts + core suites;
counts/time recorded here.

**Commit boundary.** Operator-surface wiring only; no schema or prompt
logic changes (those are CB1-CB4); P3-DOC (node/skill .md sync) follows
as its own commit before merge per the standing rule.

## 12. P3-AUD follow-up — production fix options (recorded 2026-07-29; NOT implemented; operator decision pending)

Source of evidence: report §13, protocol doc §21. Two production
defects (P-1 retry-loop discard; P-2 = #146 interface + expressiveness
gap). Options compared per the operator's audit-first instruction; no
code changed.

**Option A — prompt clarification (targets P-2 induction).** Add to
`causal_reasoning_stage.md` (the stage of origin) and mirror in
`proposing_stage.md`: one worked example PER source type (incl. an
`external_agent` `prefix:identifier` example and a human example);
explicit instructions that registry losses/models inherited from past
iterations are `source_type='experiment'` with the introducing
`model_type` as `source_id` (+ `from_run` when known); that vocabulary
items are cited with a designated stable form; and the regex stated
where the schema is described. Cheap, zero schema/migration risk,
directly addresses the "no worked example" evidence. Cannot by itself
fix P-1 (corrections would still be discarded) and leaves the
provenance vocabulary semantically overloaded.

**Option B — narrow deterministic normalization.** Pre-validation
normalizer for UNAMBIGUOUS malformed forms only (e.g.
`Vocabulary:x`/`vocabulary.x` → the designated vocabulary form;
`iter_NNN`-style external_agent ids → a canonical iteration form),
with every rewrite recorded in provenance. Risk: silently converts a
possibly-wrong attribution into a legal-looking one — it can hide
attribution errors the validator exists to catch. If adopted at all,
only as a RECORDED normalization with the original preserved, never a
silent fix. Not recommended as the primary fix.

**Option C — extend the source representation (targets P-2
expressiveness).** Add legal source types/forms for what prompts
actually expose: e.g. `registry` (loss/model registry entries, id =
registry name + introducing iteration) and `vocabulary` (id = vocab
item name), or equivalently structured origin fields. Removes the
overload where everything collapses to `experiment`; makes the
semantically-correct citations the model already produces legal.
Cost: schema migration (validator, prompts, tests, any consumers of
`source_type`), medium scope; must keep old records readable.

**Option D — relax validation. REJECTED as primary.** Widening the
regex or accepting malformed ids raises pass rate by corrupting the
provenance record (`iter_004` as an external_agent id is precisely the
ambiguity the contract exists to prevent). Only defensible as a
temporary diagnostic mode, never as the fix.

**P-1 fix (required regardless of A-D).** In pipeline mode, validate
`inherited_components` at the CAUSAL stage (fail fast where the
feedback loop can actually reach the producing response) AND/OR accept
the proposing response's corrected `inherited_components` when the
injected causal values fail validation. Smallest coherent form:
validate the memo's citations inside the causal-stage retry loop with
the same `InheritedComponent` contract, so the retry instruction
becomes satisfiable; keep the proposing-stage injection unchanged.

**Recommendation (evidence-based): P-1 fix + Option A now; Option C
as the durable follow-up** (separate migration commit or PR); B/D
rejected. Rationale: rev-3 raw bodies prove the model produces correct
semantics and, when told, correct syntax — the failures are induced by
missing guidance (A), unexpressible sources (C), and an unfixable
retry seam (P-1). Deterministic validation before any rev-4: contract
tests for each malformed class (must fail with instructive messages),
prompt-render tests asserting the worked examples appear in both
stages, and a causal-stage-retry test proving a malformed memo
citation is corrected within the causal loop.

**Runner fixes (calibration scope, separate from production fix):**
R-1 enforce protocol stop conditions in the sample loop (count
terminal failures at each `run_sample` return; stop when the floor
becomes unattainable); R-2 top-level try/finally writing
`run_status.json` with outcome ∈ {completed, protocol_stop,
budget_stop, technical_failure} (+ always write `run_summary.json`);
R-3 mark an in-flight sample aborted by a cap (`aborted_incomplete`
marker in its dir); R-4 archive the exact launch command + wrapper in
the run dir; wrapper must propagate the runner's exit status (no
trailing echo as last command).

## 13. Retry-assembly pre-edit audit (2026-07-29; read-only; answers the operator's eight questions before any P-1 fix)

Inspected: `_run_pipeline` stage loop (`ml_model_proposal_agent.py:1495-1579`),
assembly (`:1681-1789`), structural-retry loop (`:1717-1835`),
`agent/schemas/proposal.py` (DiscoveryMemo `:376`, ProposalOutput
`:912`), `causal_reasoning_stage.md`, `proposing_stage.md`, git history
of the extraction lines (`301037d`, `510ec3d`, phase-c).

1. **Why immutable across retries?** Stage-ownership design from
   phase-c: the reasoning stages own the memo's scientific content
   (citations, prediction, vocab proposals); the proposing stage owns
   implementation; stages 1+2 are never re-run from either retry loop
   (cost control). The comment "these don't change on retry" encodes
   the ASSUMPTION that injected scientific fields cannot fail
   validation — never reconciled with the structural-retry feedback
   that names errors in exactly those fields. The defect is that
   assumption, not the ownership design.
2. **Can the proposing stage return/correct inherited_components?**
   Its declared output contract says NO — the "What you produce" JSON
   in `proposing_stage.md` lists 9 fields and does NOT include
   `inherited_components` (or any injected field). The corrected
   citations observed in rev-3 retries were spontaneous,
   outside-contract responses to error feedback. The causal stage's
   contract DOES include `inherited_components` (worked example at
   `causal_reasoning_stage.md:117-125`).
3. **Fields discarded/overwritten by earlier-stage values** (assembly
   `:1773-1789`): `inherited_components` (causal),
   `falsifiable_prediction` (causal), `proposed_vocab_links`
   (comparison), `proposed_vocab_candidates` (comparison+causal),
   `proposed_discoveries` (comparison+causal). All other
   ProposalOutput fields come from the proposing response and ARE
   correctable by structural retry.
4. **Other fields with the same uncorrectable pattern**: YES —
   `falsifiable_prediction` carries the
   `_prediction_differs_from_current` model validator (plus numeric
   type coercion); a causal-stage violation is exactly as terminal
   and unfixable as P-1 (latent, not yet observed).
   `proposed_vocab_links` (status Literal + str coercion),
   `proposed_vocab_candidates` (dict[str,str] coercion) and
   `proposed_discoveries` (VocabEntry) can fail on type/Literal
   errors — same pattern, lower likelihood, partly comparison-stage
   origin. No stage output is Pydantic-validated at its own stage:
   `accumulated[stage.name]` stores the raw bridge dict (`:1569/:1577`).
5. **Intended source of truth**: the causal stage, for all attempts —
   by design there is no "corrected retry" source because the design
   assumed no correction would ever be needed. First attempt / retry /
   corrected retry all currently read the same stale causal values.
6. **Would accepting the retry response violate causal invariants?**
   Partially: `proposing_stage.md` Rule 2 audits the implementation
   AGAINST the memo's component list; letting the proposing stage
   rewrite the list makes it self-referential and lets the
   implementation stage alter scientific attribution produced with
   fuller causal context. Downstream consumers
   (`ml_code_validator_agent._check_inherited_components`,
   `interpretation_helpers`, vocab accumulation) key on `component`
   NAMES only — `source_type`/`source_id` are archival lineage — so
   the blast radius of a wrong correction is provenance records, not
   behavior.
7. **Merge rule**: keep ONE rule for all attempts. Correcting at the
   producing stage (Option C) preserves the uniform injection rule at
   the proposing stage; per-attempt or error-field-selective merge
   rules (Options A/B) introduce attempt-dependent semantics and a
   second source of truth.
8. **Compat/provenance risk per option**: A — proposing contract must
   grow the field; citations restated each attempt can drift from a
   VALID memo; largest surface. B — smallest happy-path delta but
   implementation-stage attribution edits + per-index merge
   complexity; corrections made without the causal context. C —
   validation moves to the producing stage inside its own bounded
   retry; no contract change to the proposing stage; existing tests
   that inject malformed memos will fail earlier (test updates, which
   is the point); adds ≤N causal retry calls on failure only. D — C
   plus a proposing-stage override reintroduces two sources of truth;
   only justified if causal-retry exhaustion were unacceptable, but
   terminal-with-clear-message + the production workflow-level retry
   already cover that.

**Recommendation (pending operator approval): Option C, scoped to the
causal stage's scientific subset** — validate `inherited_components` +
`falsifiable_prediction` (one small partial model) immediately after
the causal stage returns, inside a bounded causal-stage retry (≤2,
error summary fed back; same feedback style as the structural loop).
Retry instruction becomes truthful at the stage that owns the data;
proposing-stage assembly unchanged; single source of truth preserved.
Comparison-stage vocab fields: same latent pattern, zero observed
failures — file as a follow-up issue rather than widening this fix.

### 13.1 Operator decision and implementation evidence (2026-07-29)

**Decision (operator)**: Option C approved — validate and retry the
causal-stage-owned fields (`inherited_components`,
`falsifiable_prediction`) at the causal stage itself; the causal stage
remains the single source of truth. Explicitly rejected: expanding the
proposing-stage contract to rewrite these fields; attempt-dependent
merge behavior; relaxing the final validator; any broad citation
sanitizer. At most two causal-stage correction retries. The
comparison-stage vocab fields stay out of scope (no observed failure)
— latent risk filed as a follow-up GitHub issue.

**Implementation** (this commit):

- `agent/schemas/proposal.py` — `CausalStageOwnedContent` (B.2a): a
  validation-only partial schema mirroring ProposalOutput's contract
  for exactly the two causal-owned fields (`falsifiable_prediction`
  stays `| None` — the legacy allowance — so no behavior tightening).
  A premature full ProposalOutput was rejected: implementation fields
  do not exist at causal time and it would couple causal validation to
  proposing-stage validators.
- `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` —
  `_MAX_CAUSAL_CORRECTION_RETRIES = 2`; a validation block placed
  AFTER the boldness retry (which can replace the causal output with a
  new, unvalidated response) and BEFORE the proposing stage. On
  failure: focused error summary (same loc→msg format as the
  structural loop), correction user prompt = the standard causal-stage
  assembly (boldness-retry P-d order) + a "## VALIDATION ERROR —
  CORRECT AND RESEND" block; IDENTICAL system prompt; label
  `proposer.causal_reasoning.correction`; ≤2 retries then a
  stage-naming RuntimeError raised BEFORE any proposing call is spent.
  Write-back only when a correction replaced the output (a pipeline
  with no causal stage is untouched). The stale "let the proposing
  stage handle it" comment on the malformed-prediction swallow was
  corrected in place.
- Proposing-stage prompt, output contract, assembly, and structural
  retry: UNCHANGED (asserted by tests).

**Tests** (`tests/unit/agent/ml_model_proposal_agent/
test_causal_stage_validation.py`, 9 tests, all green first run;
proposer-suite regression 523 passed; proposer+prompts+protocols 605
passed; ruff check + format clean):

1. malformed causal citation → correction retry → corrected citation
   present in the final ProposalOutput → success (4 calls);
2. correction call carries the focused error (marker, field name,
   offending value) and the `.correction` label;
3. repeated malformed corrections exhaust (comparison + causal + 2
   corrections, NO proposing call) with a stage-naming RuntimeError;
4. degenerate falsifiable_prediction (predicted == current) corrected
   through the same path, corrected value preserved;
5. valid causal output: byte-preserved behavior — 3 calls, no
   correction label, no marker in any prompt;
6. proposing structural retry (duplicate model name) unaffected;
7. correction system prompt byte-identical to the causal system
   prompt; no fix marker in the proposing system prompt;
8. disabled causal stage: 2 calls, no key insertion;
9. partial-schema contract: empty/None legal, malformed citation and
   degenerate prediction rejected.

**Retry contract after the fix** (now truthful):
causal stage produces invalid causal-owned data → causal validation
fails → the causal stage receives the focused validation error →
bounded causal-stage retry produces corrected data → corrected causal
output becomes the accumulated source of truth → final ProposalOutput
validation uses that corrected data.
