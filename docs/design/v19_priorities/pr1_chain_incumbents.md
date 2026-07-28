# Design: V19 PR 1 — Chain-Level Incumbents (`pr1_chain_incumbents`)

- **Status**: rev 3 — **P1-D APPROVED (operator, 2026-07-27)**; doc
  locked for implementation; implementation not started
- **Author**: Claude (operator: Yue Ma)
- **Created**: 2026-07-27
- **Revised**: 2026-07-27 (round 2: commit-time validity semantics;
  artifact-hash replay integrity; provenance expanded; iteration-local
  vs chain-state invariant + three-iteration test; flag named
  `enable_chain_incumbent_formal_gates`; standalone Gate 2 with both
  incumbent branches deterministic in pseudo. round 3: P1-C5 RESTORED
  as a required secondary commit with strengthened determinism
  contract; two-state variable design separating
  `chain_formal_incumbent_reference` from iteration-local best state;
  committed-summary fields validated against their source record;
  `round_index` from persisted identifiers only (never fabricated from
  list position); replay-integrity mismatch STOPS the chain by
  default)
- **Branch**: `feat/v19-pr1-chain-incumbents` (from `master` @ `ea8c599`)
- **Parent baseline**: [`../v19_priorities.md`](../v19_priorities.md)
  §2.4 (capability), §2.0 PR 1 exit contract + progress checkpoints,
  §4 Validation and Evaluation Standard
- **Tracks**: GitHub issue #136 item 1; V19 Progress Tracker "PR 1 —
  Chain-level incumbents"
- **PR class**: mixed — deterministic (blocking scope) with a
  conditional agent-behavior part that this PR does NOT claim (see
  §5 Non-goals)
- **Depends on**: nothing in the V19 ladder
- **Audit evidence**: §2 below (code audit 2026-07-27, branch
  @ `ea8c599`); V18r campaign audit
  [`../../../reports/v18r_campaign_audit_20260725.md`](../../../reports/v18r_campaign_audit_20260725.md) §15.10

## Development principles

Same four rules as all SIDERIUS design docs:

1. **Check, don't guess** — every claim below carries a `file:line`
   citation from the 2026-07-27 audit; re-verify on disk before
   editing code that has moved.
2. **Keep design doc and code in lock-step** — tick `[ ] → [x]` with
   evidence (hash, test counts, verbatim strings) as each item lands.
3. **Stop before each commit** — show progress + implementation
   details, wait for operator permission.
4. **Split logical commits at clean seams** — commit prefix **P1**;
   every commit leaves the relevant unit suites green.

## 0. Implementation progress

Tick discipline (baseline §2.0): a stage is ticked `[x]` only after
its implementation commits exist and its verification checklist is
green with recorded evidence.

```text
[x] P1-A  — pre-design code audit (this doc §2; agent audit 2026-07-27)
[x] P1-D  — design approved by operator (rev 3, 2026-07-27 — see
            approval record in §10; doc locked for implementation)
[x] P1-C1 — schema widening + threshold consolidation + comment sweep
            (29ec054; design-doc commit 98119e3; tune 687 green,
            workflows 206 green; pyright n/a lilab)
[x] P1-C2 — incumbent reconstruction in core/resume.py (RestoredState;
            commit-time validity; artifact-hash verification)
            (2f9d4c7 + docs 387f387; new suite 19 green; core 446
            green + 2 pre-existing watchdog env failures)
[x] P1-C3 — threading: subprocess → workflow → protocol → tuner input
            (+ enable_chain_incumbent_formal_gates flag, default OFF;
            manifest artifact hash + chain_incumbent_used stamps)
            (bb37bfc..741aff4 7-commit split + docs 0e82037; suites
            84 + 166 green; parity green)
[x] P1-C4 — trial incumbent persisted fields (read-only bookkeeping)
            (commit pending operator approval; tune suite 71 green)
[x] P1-C5 — per-file best table (SECONDARY but REQUIRED, isolated
            commit; strengthened determinism contract §3.7)
            (commit pending operator approval; 18 targeted + 340
            regression green; A4 write-side + smallest public boundary
            in core.resume landed together)
[x] P1-V1 — pre-gate sweep: targeted unit + pseudo integration
            (BOTH incumbent branches deterministic)
            (commit pending operator approval; new pseudo suite 4
            green; regression 296 green)
[x] P1-V2 — Gate 2: standalone smallest canonical smoke (real LLM +
            real training, flag ON) — **PASS WITH DOCUMENTED
            LIMITATIONS** (attempt 3, 2026-07-27; Branch B path
            validated end-to-end in 17m18s; Branch A + replay-hash
            paths remain covered by P1-V1 + P1-C2)
[x] P1-S  — stop-and-show; PR merged (coupling flag still OFF)
            (PR #137, merge commit 6678d19, 2026-07-28; one CI flake
            fixed in-passing on the branch: watchdog survivor-check
            race, 21143ca — pre-existing, not a PR-1 regression)
[ ] P1-ACT — activation: coupling flag ON in production launchers
            (separate operator decision; not part of this PR's merge)

Scope rule for P1-C5 (operator decision, rev 3): P1-C1..C4 are the
blocking chain-incumbent correctness work; P1-C5 is secondary but
REQUIRED, isolated from decision logic in its own commit, and must not
force redesign of the blocking mechanisms. It is not deferred for
being secondary. If implementation audit reveals materially larger
scope than understood here, STOP and report the concrete expansion
before changing the plan.
```

## 1. Problem statement and goal link

**Problem** (confirmed by audit, §2.1): the formal-gate reference
`current_run_best_formal_score` is a non-optional `float` defaulting
to `0.0` (`agent/schemas/hyperparam_tuning.py:1022-1031`). Its only
production write site
(`workflows/model_exploration.py:2462-2463`) is dead in chain mode
because `run_one_iteration.py` always calls
`run_workflow(max_iterations=1)` (`run_one_iteration.py:1330,1344`),
so `best_score_overall` is still `None` when the guard runs. No CLI
flag exists at any layer to inject it. `core/resume.py::RestoredState`
(`core/resume.py:157-165`) restores plugins, vocab, findings,
rejections, gate exhaustions, proposal, and knowledge cache — but no
best score. Consequently every chain iteration measures
`skip_formal_min_delta` / `bypass_formal_time_budget_min_delta`
against a constant `0.0`.

**Goal link** (baseline §1): formal decision economics measure against
the real chain incumbent, so formal budget concentrates on genuinely
better candidates. Quantified ceiling from the V18r audit
(`reports/v18r_campaign_audit_20260725.md:533-539`): with a
chain-local incumbent, exactly **one** decision in 17 closed
iterations changes (`arch_10_14/002` → SKIP), reclaiming **586.1 min**
(63.8 % of that chain's wall). This PR is shipped as **state
correctness**, not as a projected budget saving — reachability of the
gates is bounded by two independent inertness mechanisms outside this
PR's scope (§2.9 findings 1 and 5).

## 2. Audit summary (2026-07-27, code-traced)

Branch `feat/v19-pr1-chain-incumbents` @ `ea8c599`. Full agent audit
retained in the PR record; the facts that shape the design:

### 2.1 The reference and its consumers

- Schema: `current_run_best_formal_score: float = Field(default=0.0)`
  — `agent/schemas/hyperparam_tuning.py:1022-1031`. **No `None`
  sentinel is representable.** Stale "deferred to V18" doctrine at
  `:997-1002`, `:1029-1031`; load-bearing 5.5763-phantom warning at
  `:1004-1010` (KEEP).
- Exactly four read sites, all in
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`:
  startup resolver `:1931`; skip-formal gate `:2071,2080,2085`
  (fires → `break` at `:2093`, iteration produces no formal); bypass
  gate `:2702-2703,2712,2719` (fires → `time_check["feasible"]=True`
  at `:2734`).
- Helpers: `_best_trial_winner` `:170-193` (requires
  `is_valid_candidate(r)` AND `is_trial` AND
  `memory.time_mode == "trial"`); `_should_skip_formal` `:197-210`;
  `_should_bypass_formal_time_budget` `:212-225`;
  `_resolve_formal_comparison_thresholds` `:227-246`.
- **Four independent copies of `ref + delta`**: resolver `:1930-1934`
  (provenance only, by design per docstring `:236-238`), skip inline
  `:2070-2072`, `_should_skip_formal:206`, bypass inline `:2702-2703`
  + `:221`. Changing the reference without consolidation makes the
  persisted `resolved_*_threshold` lie about the gate that ran.

### 2.2 V18r evidence (why the gates never fired)

`reports/v18r_campaign_audit_20260725.md` §15.10: "**Actual firings: 0
skips, 0 bypasses**, 17 iterations, 4 chains" (`:519-521`); "**Why
zero**: both gates route through `_best_trial_winner`, which requires
a HealthGate-VALID trial. **15/17 iterations had none**" (`:522-526`);
"any reference-policy change that does not also address trial-side
HealthGate validity (or add a raw-score fallback) remains inert"
(`:540-547`). PR 1 fixes the reference; it does NOT claim to make the
gates fire.

### 2.3 What already exists on disk

- Manifest (`sdsc_submission_scripts/run_one_iteration.py:286-378`)
  already persists `best_valid_formal_score` (`:356-358`) plus
  `best_score`/`raw_best_score` (duplicates, `:353-354`),
  `best_valid_score`, `raw_best_formal_score`, `completed_rounds`, and
  the DS6c invariant stamps (`:362-364`) and PR #124 thresholds
  (`:365-371`). **The §2.4.a score source of truth exists today; no
  data migration is needed.** Absent from the manifest: `exp_id`,
  round index, `model_params`, `file_vector`, `is_trial` — provenance
  requires the `run_output` parse.
- `restore_prior_state` (`core/resume.py:573-812`) already walks
  committed iterations ascending, validates the chain lock before any
  mutation (`:642-643`), validates per-iteration invariant stamps
  (`:666-680`), and holds a fully validated `HyperparamTuningOutput`
  at `:664` — carrying `best_valid_formal_denoising_score`,
  `best_valid_formal_exp_id`, `all_records`, and the scope stamps.
  The accumulation idiom to copy is `:729-733`.
- Existing partial implementation: `best_score_overall`
  (`model_exploration.py:1792` init, `:2540-2554` formal-only update
  with the poisoning-prevention comment, `:2462-2463` consume). Two
  prior audits dismissed it (phase68 doc proposed a WRONG rebuild
  formula using the raw all-rounds best; `Consistent_growing_vocab_list.md`
  G6 rated it "Severity: None"). PR 1 reverses that judgment and must
  NOT adopt the phase68 formula.

### 2.4 Validity, scope, and per-file data

- Eligibility machinery available:
  `execute_tools/health_checks/candidate_eligibility.py`
  `classify_candidate_health` `:49-100` → `VALID|INVALID|UNKNOWN`,
  `is_valid_candidate` `:104-113`. Audit caveat that DROVE a rev-2
  design decision: it judges against the repo's shipped
  `configs/health_checks.yaml` (`:37-46`), NOT the workspace's locked
  effective config — intentional per PR #124
  (`docs/design/enable_partial_file_list.md:157-163`). Rev 2 therefore
  FORBIDS its gate-set source for incumbent eligibility; decision
  state uses commit-time evidence only (§3.3).
- Scope identity is available at every reconstruction point
  (`compute_expected_invariants` `run_one_iteration.py:955-973`,
  `resume.py:577,642-643,666-680`). The chain-level
  `run_invariants_lock.json` already guarantees within-workspace scope
  homogeneity; note the tuner writes a second per-model lock in
  `tuning_dir` — the CHAIN lock is the one PR 1 keys on.
- Per-round `file_vector` is persisted **LINEAR** in
  `run_output_*.json` `all_records`
  (`ml_hyperparameter_tune_agent.py:3461,3937`); the §2.4.b column is
  `best_log_score` → the table must convert. Formal records carry NO
  `is_trial`/`eval_portion` keys (`:3594-3606`; absence == formal) —
  formal sampling provenance must come from
  `HyperparamTuningInput.formal_eval_portion` or `run_config_*.json`.

### 2.5 Traps recorded for the implementer

1. `memory.time_mode` is only written when the time gate ran
   (`:3506,3513`) — a second, independent gate-inertness mechanism;
   OUT OF SCOPE here, filed as follow-up FU-P1-1.
2. Two tests hard-code `0.0` as correct:
   `tests/unit/workflows/test_model_exploration.py:674-714`
   (`test_trial_only_iter_does_not_poison_formal_anchor` — its INTENT
   survives, its assertion does not) and
   `tests/unit/agent/tune_ml_hyperparam_agent/test_delta_gates.py:61-63`.
3. `--auto_resume` can overwrite a `no_records` iteration (documented
   bug, `docs/chain_skip_unproductive_iters_design.md:185-198`) — the
   concrete duplicate/replay case; containment in §3.6.
4. Crash/degraded manifests omit every `best_*` key
   (`run_one_iteration.py:311-326`;
   `ml_hyperparameter_tune_agent.py:3980-3993`) — reconstruction must
   tolerate MISSING keys, not just null.
5. `no_records` iterations never enter `committed_iters`
   (`resume.py:649-661`) — correct for the incumbent; noted for PR 6.
6. `degenerate_penalty_score != None` puts scored-but-collapsed formal
   records into the population (`hyperparam_tuning.py:1057-1076`);
   `is_valid_candidate` rejects them, but any future raw-score
   fallback would not — recorded as a hazard for the V18r-audit
   recommendation, NOT implemented here.
7. Downstream manifest readers that never look at
   `best_valid_formal_score`: `scripts/v18_wave_summary.py:136,207,226`
   (`best_valid_score`), `scripts/inspect_run_state.py:192,333` (raw
   best) — the inspector will disagree with the incumbent by
   construction; follow-up FU-P1-3.

## 3. Design

### 3.1 Two invariants, three mechanisms

**Invariant I (incumbent correctness)**: at the start of chain
iteration N, the tuner's formal reference equals the best
COMMIT-TIME-HealthGate-valid FORMAL score committed by iterations
1..N-1 of the same workspace (same run-invariants lock identity),
or is absent (`None`) when no such score exists.

**Invariant II (iteration-local vs chain-state separation — rev 2)**:
`best_valid_formal_score` (and every other `best_*` field) in an
iteration's output and manifest describes ONLY that iteration's own
rounds — restoring a chain incumbent never rewrites, seeds, or
back-fills any iteration-local result field. The restored incumbent is
persisted under its own distinct keys (`chain_incumbent_used`,
`chain_incumbent_source`) and is never serialized as if the current
iteration produced it. Concretely: an iteration with no valid formal
of its own has local `best_valid_formal_score = None` in its manifest
even while its gates consumed a numeric chain incumbent, and the
incumbent's provenance continues to name the ORIGINAL source
iteration, not the iteration that merely carried it forward. (Tested
by the three-iteration case in P1-C3.)

Mechanisms: (a) constructive — reconstruction in
`restore_prior_state` from committed manifests + validated
`run_output` parses, under commit-time validity semantics with
summary-vs-source cross-validation (§3.3); (b) boundary — typed
`float | None` schema with `None` short-circuits in both gate
helpers, plus artifact-hash verification that HALTS the chain on
mismatch (§3.6); (c) provenance — the consumed incumbent (score,
source iter, round, `exp_id`, scope stamp, validity basis,
verification status) is printed at `[resume]`, persisted in the run
config, and stamped into the manifest under the `chain_incumbent_*`
keys.

### 3.2 Schema widening (P1-C1)

- `current_run_best_formal_score: float = 0.0` →
  `float | None = None` (`hyperparam_tuning.py:1022`). `None` = "no
  incumbent"; the gates short-circuit exactly as they already do for
  `winner is None` (`:206`, `:221` gain a symmetric
  `reference_score is None` early return via the resolver).
- `_resolve_formal_comparison_thresholds` becomes the SINGLE source of
  the resolved thresholds; the two inline recomputations
  (`:2070-2072`, `:2702-2703`) and the helper-internal sums read the
  resolved values. Persisted `formal_reference_score` /
  `resolved_*_threshold` become `None`-capable (schema already
  `float | None` at `:1865-1883`) and now provably equal what the
  gates used.
- Comment sweep: `:997-1002`, `:1029-1031`, `:1932-1936`,
  `ml_hyperparameter_tune_agent.py:1926-1936` ("deferred to V18"
  doctrine → replaced by V19 PR 1 reality). The 5.5763 warning block
  (`:1004-1010`) is preserved verbatim.
- **Rollback semantics (baseline-corrected)**: operator flag
  **`enable_chain_incumbent_formal_gates`** (name fixed by operator,
  rev 2; chain + tuner CLI + schema field). Reconstruction,
  persistence, printing, and provenance are UNCONDITIONAL — the flag
  controls only whether the formal gates consume the incumbent.
  OFF → gates receive `None` (no-incumbent behavior). **OFF never
  reinstates `0.0`.** Merge default: OFF (activation is P1-ACT, a
  separate operator decision per baseline §4.5).

### 3.3 Reconstruction (P1-C2) — commit-time validity semantics (rev 2)

- Extend `RestoredState` (`core/resume.py:157-165`) with:

  ```text
  chain_best_valid_formal_score: float | None
  chain_best_valid_formal_provenance: dict | None
      # {iter_idx, round_index, exp_id, model_type, score,
      #  resolved_data_scope, health_config_sha256,
      #  validity_basis: "committed_fields" | "persisted_verdicts",
      #  artifact_verified: bool}          # §3.6
  chain_best_trial_score: float | None      # read-only context
  chain_best_trial_provenance: dict | None
      # {iter_idx, round_index, exp_id, model_type, score,
      #  eval_strategy, eval_portion, train_portion,
      #  resolved_data_scope, health_config_sha256,
      #  validity_basis, artifact_verified}
  ```

  Trial scores without sampling provenance are not interpretable
  (operator rule, rev 2): `eval_strategy` and `eval_portion` are
  MANDATORY on trial provenance (`train_portion` included — present on
  every trial record per §2.4).

  **`round_index` rules (rev 3 — never fabricated)**: the `round_index`
  KEY is mandatory on both formal and trial provenance, but its value
  comes ONLY from a genuinely persisted round identifier — the
  record's `logical_round` field when non-null. Position in
  `all_records` (or among completed rounds) is NOT a round index and
  must never be presented as one: the audit shows `logical_round` is
  conditionally written (null on many historical success records), so
  no positional invariant is proven. When no persisted identifier
  exists: `round_index = null` with
  `round_provenance = "persisted" | "legacy_unknown"` making the gap
  explicit. If the implementation audit finds another committed
  mapping that is DEMONSTRABLY exact, it may be used — with the proof
  recorded in the implementation notes; otherwise null stands.

- Fold inside the existing `:648-733` walk, using the already-parsed
  `HyperparamTuningOutput` at `:664` (zero extra disk I/O, same idiom
  as rejections/exhaustions at `:729-733`).

- **Eligibility — commit-time validity ONLY (operator rule, rev 2)**:
  the incumbent must preserve the validity semantics that applied when
  the iteration committed. Decision order per candidate iteration:

  1. `best_valid_formal_denoising_score` present in the committed
     output → candidate via `validity_basis="committed_fields"` (the
     tuner computed it at commit time under that run's effective
     policy; PR #124 lineage) — **but field presence alone is NOT
     sufficient (rev 3)**. The committed summary must be validated
     against its source record; ALL of the following are required:
     - `best_valid_formal_exp_id` is non-null;
     - a record with that `exp_id` exists in the committed output's
       `all_records`;
     - that record is FORMAL (no `is_trial` key / `is_trial` falsy,
       per the absence==formal semantics, §2.4);
     - score agreement between the summary field and the record's
       `denoising_score` within the explicit tolerance
       `abs(a - b) <= 1e-9 * max(1.0, abs(a))`;
     - round provenance recoverable from that record per the
       `round_index` rules below (null + `legacy_unknown` is
       recoverable; a missing record is not);
     - no conflict among the output fields, the manifest's
       `best_valid_formal_score`, and the invariant stamps
       (scope/sha) for that iteration.
     Any check failing → the candidate is classified **UNKNOWN**,
     EXCLUDED from decision state, and a visible
     `[resume] SUMMARY-MISMATCH:` warning names the iteration, the
     field, and the discrepancy. A stale or partially written summary
     is never silently trusted.
  2. Field absent (legacy output) → re-derive ONLY from commit-time
     evidence: the per-record persisted gate verdicts
     (`health_gate_results[*].check_passed` /
     `would_invalidate_under_production_policy`, written at run time —
     `ml_hyperparameter_tune_agent.py:3591-3592`), interpreted against
     that workspace's materialized effective policy
     (`health_checks_effective.yaml` / the stamped
     `health_config_sha256`) when gate-set completeness must be
     judged. `validity_basis="persisted_verdicts"`.
  3. Commit-time validity NOT establishable (missing verdicts, missing
     effective-policy artifact, unparseable stamps) → **UNKNOWN →
     EXCLUDED** from decision state.

  The repo-current `configs/health_checks.yaml` (and
  `candidate_eligibility.required_blocking_gate_ids`, which reads it —
  `candidate_eligibility.py:37-46`) is **never** consulted for
  incumbent eligibility. It may be used for offline ANALYSIS
  (re-judging history under today's policy), but it must not silently
  change historical decision state. Consequence: reconstruction is
  deterministic across repo-policy edits — a stronger property than
  rev 1 claimed.

- Tie-breaking (explicit, replay-stable): higher score wins; equal
  scores → **earliest iteration wins**; same iteration → lexicographic
  smallest `exp_id`. (Makes the current accidental first-max behavior
  a stated rule.)
- Missing/degraded tolerance: manifests or outputs lacking `best_*`
  keys contribute nothing (never an error); `status="failed"`
  manifests keep their existing `ResumeError` behavior (`:212-217`) —
  unchanged by this PR.
- Emit `[resume] incumbent carry-over: score=… iter=… round=… exp_id=…
  basis=… verified=…` (matching the existing `[resume]` print family
  at `:748-812`), and `[resume] incumbent carry-over: none` on the
  no-incumbent path.

### 3.4 Threading (P1-C3) — two-state variable design (rev 3)

**Two distinct variables with separate semantics; no shared
accumulator (operator rule, rev 3):**

```text
chain_formal_incumbent_reference: float | None
    initialized from RestoredState.chain_best_valid_formal_score;
    consumed ONLY by the formal gates (via the named protocol
    parameter) and provenance stamps; in the in-process
    multi-iteration path it is updated AFTER each iteration commit
    from that iteration's committed best_valid_formal_denoising_score
    (max under the §3.3 tie rules) — preserving equivalence with N
    chained subprocesses.

iteration_best_valid_formal_score (existing tuner-side selection)
    derived ONLY from the current iteration's own records inside the
    tuner (:3861-3865); the ONLY value permitted to populate the
    current iteration's best_* output and manifest fields.
```

**`best_score_overall` disposition — full site enumeration
(rev-3 requirement; audit-verified)**: init
`model_exploration.py:1792`; update `:2540-2554` (from
`tune_output.best_formal_denoising_score` — RAW formal,
iteration-derived); consume `:2462-2463` (the post-hoc tuner-input
mutation — **REMOVED by this PR**); print `:2611`; serialized into
`workflow_iter_NNN.json` at `:2622`/`:2644` as `"best_score_overall"`.
After the `:2462-2463` removal, `best_score_overall` retains exactly
one role: a workflow-level RAW-formal progress tracker feeding the
workflow print/summary. Non-contamination proof obligations (asserted
by tests): (a) restored chain state is NEVER written into
`best_score_overall` (it would silently relabel a restored score as
this run's raw progress); (b) `best_score_overall` is NEVER written
into tuner input, iteration output, or iteration manifest. It is NOT
renamed in this PR (name is serialized in workflow summaries; renaming
is cosmetic churn) — but it no longer participates in any decision
path.

Call-site threading (copying the `restored_previous_proposal` idiom,
default `None` ⇒ bit-identical legacy behavior):

```text
run_one_iteration.py:1406   pass state.chain_best_* into run_workflow
model_exploration.py:1455   new kwargs in the restored_* block
model_exploration.py:~1792  NEW local chain_formal_incumbent_reference
                            (separate from best_score_overall)
ml_model_valid_to_ml_model_tune.py:62-63,214-241
                            current_run_best_formal_score becomes a
                            NAMED protocol parameter fed from
                            chain_formal_incumbent_reference; the
                            post-hoc mutation at
                            model_exploration.py:2462-2463 is removed
```

The in-process multi-iteration path (`run_workflow(max_iterations>1)`)
must produce the same incumbent sequence as N chained subprocesses —
the baseline's equivalence requirement, tested in P1-V1.

### 3.5 Trial incumbent (P1-C4, read-only)

- New output fields `best_valid_trial_exp_id` /
  `best_valid_trial_denoising_score` beside `:3915-3917` (derived from
  `valid_records` with `is_trial=True`), mirrored into the manifest.
  Note recorded: this derivation is NOT identical to
  `_best_trial_winner` (which additionally requires
  `memory.time_mode=="trial"`); the persisted field is the bookkeeping
  notion, the gate keeps its own predicate.
- Restored trial incumbent lives on `RestoredState` only. **No prompt
  or gate consumes it in this PR** (interpreter/proposer already see
  per-model `best_valid_formal_score` via `ModelRunSummary`,
  `agent/schemas/interpretation.py:108-111`; the tuner planner remains
  dark by design here — see Non-goals).

### 3.6 Replay integrity (rev 2 — hash-verified, fail closed)

Silent last-write-wins mutation of committed artifacts is NOT
acceptable containment (operator rule, rev 2). Design:

- **Immutable artifact identity**: every NEW manifest gains
  `run_output_sha256` — the SHA-256 of the exact `run_output_*.json`
  the manifest describes, computed at `write_manifest` time on the
  normal path (`run_one_iteration.py:327-372` shape only; crash /
  `no_records` shapes carry no hash because they carry no artifact).
- **Verification at reconstruction — mismatch STOPS the chain
  (rev 3)**: for each committed iteration, `restore_prior_state`
  recomputes the hash of the on-disk `run_output` and compares:
  - match → candidate proceeds, provenance `artifact_verified: true`;
  - **mismatch → raise `ReplayIntegrityError` (a `ResumeError`
    subclass) BEFORE the next iteration launches.** A changed
    committed artifact means history is no longer trustworthy;
    excluding-and-continuing could still alter the chain incumbent and
    therefore future decisions, so silent continuation is forbidden.
    The error message names the artifact path and the expected/actual
    hash prefixes (verbatim-asserted in tests). Recovery is an
    explicit operator action: either restore the original artifact or
    regenerate a consistent manifest+hash pair for the intentionally
    replaced one, then relaunch.
  - legacy manifest without `run_output_sha256` → candidate ADMITTED
    for backward compatibility but VISIBLY marked
    `artifact_verified: false` in provenance, the `[resume]` line, and
    the consuming iteration's `chain_incumbent_source` stamp. Never
    silent.
- **Diagnostic recovery mode: NOT implemented in PR 1.** If one is
  ever added, it must live explicitly outside normal production
  behavior and at minimum: disable
  `enable_chain_incumbent_formal_gates` coupling, and mark the
  workspace integrity as degraded in every manifest it produces. A
  normal production chain never continues past a detected mismatch.
- Incumbent derives only from `committed_iters` (which already
  excludes `no_records`); provenance pins
  `(iter_idx, round_index, exp_id)`. The incumbent is never cached
  across processes — every iteration re-derives from disk under the
  rules above.
- The documented `--auto_resume` `no_records` overwrite bug (§2.5
  trap 3) is still NOT fixed here (FU-P1-2) — but with hash
  verification, a replayed/overwritten artifact can no longer silently
  alter decision state: the chain stops until the operator resolves
  the inconsistency.

### 3.7 SECONDARY (required) — per-file best table (P1-C5, rev 3)

**Operator decision (rev 3): RESTORED into PR 1** as a secondary but
required, isolated commit. Never consumed by decision logic in V19;
must not force redesign of §3.1-§3.6; scope-expansion rule per §0.
Resolved design: **incremental materialization + a deterministic
rebuild script**, under the following determinism contract
(strengthened, rev 3):

- File: `{workspace}/per_file_best.json` (chain root, beside the
  lock). Rows keyed `(file_index, phase ∈ {trial, formal},
  validity ∈ {raw, valid})`; columns per baseline §2.4.b (score,
  iteration, round/exp_id per §3.3 round rules, model_type,
  model_params, eval_strategy, eval_portion, gate summary,
  source-record timestamp).
- **Source parity**: incremental and rebuild paths consume the SAME
  committed, integrity-accepted source artifacts (manifest +
  hash-verified `run_output`). A tampered / hash-mismatched artifact
  can never silently update the table — under §3.6 the chain has
  already stopped; the rebuild script performs the same hash check
  and refuses mismatched inputs.
- **Canonical serialization contract**: rows sorted by
  `(file_index, phase, validity)`; JSON written with sorted keys,
  fixed separators, `\n` line ending, UTF-8; floats serialized via
  `repr` (Python round-trip form). Byte-equality of rebuild vs
  incremental is defined OVER THIS CONTRACT.
- **Atomic writes**: temp file + `os.replace` in the same directory;
  no partially written table is ever observable.
- **Timestamps**: taken from immutable committed provenance (the
  source record's persisted `timestamp`), never from wall-clock at
  write time. Any field not derivable from committed artifacts is
  excluded from the canonical byte-equality domain (currently: none —
  the schema is fully committed-derived).
- **Metric/transform provenance**: table header records
  `metric_id` (e.g. `tidmad_denoising_score`),
  `score_transform: "log"`, `log_base: 5.27`, and the source-space
  note (`file_vector` persisted LINEAR → stored `best_log_score =
  log_5.27(linear)`; `-inf`/non-positive skipped with a count in the
  header). This is the §1.3 genericization rider satisfied at the
  schema level: nothing in the row format is TIDMAD-specific.
- **Validity semantics**: `validity = valid` means RECORD-LEVEL
  commit-time HealthGate validity (§3.3 rules — same basis as the
  incumbent), NOT a per-file HealthGate verdict. Documented in the
  table header to prevent misreading.
- Formal provenance rule: `eval_portion` for formal rows sourced from
  the run config (`formal_eval_portion`), never from the record
  (which has no key).
- Rebuild script `scripts/rebuild_per_file_best.py`: walks
  `iter_*/**/run_output_*.json` under the hash rules above, produces
  byte-identical output to the incremental path on the same inputs,
  and doubles as backfill for existing V17/V18r workspaces (legacy
  no-hash artifacts admitted, marked in the header as
  `unverified_sources: N`).

#### 3.7.1 Resolved P1-C5 decisions (operator, 2026-07-27, rev 3.1)

**A1 — incremental write location**: chain-only, in
`sdsc_submission_scripts/run_one_iteration.py::main` after the
committed `run_output`, its SHA-256, and the normal manifest are
available. No `model_exploration.py` in-process hook (the workflow
does not currently provide the same manifest/hash commit boundary).
Exact placement + failure handling pinned after code audit (§3.7.3
below).

**A2 — `gate_summary` — ONE stable schema for both raw and valid
rows** (the row key describes the candidate pool used for best
selection; `gate_summary` describes the actual source record):

```text
candidate_validity: "valid" | "invalid" | "unknown"
validity_basis:    "committed_fields" | "persisted_verdicts"
                 | "waiver" | "unknown"
blocking_failed_gate_ids: list[str]  # empty list when none
waiver_ids:               list[str]  # empty list when none
```

A `validity=raw` row may still be sourced from a HealthGate-valid
record — the `gate_summary` reports the record's actual status. Full
HealthGate payloads are NOT persisted in the table.

**A3 — per-file best selection (shared helper for incremental +
rebuild)**: for each `(file_index, phase, validity)` consider only
finite positive linear `file_vector[file_index]` values; pick the
largest linear value; convert to log for storage. Tie rule: earliest
iteration → deterministic persisted-round rule per §3.3 → lex smallest
`exp_id`. Round identity is never fabricated (§3.3 `round_provenance`).

**A4 — formal `eval_portion`**: use committed `formal_eval_portion`
when the source has it; store `null` for legacy sources where it is
unavailable. NEVER inferred from current defaults or repo config.
Audit result recorded in §3.7.2 below before table code is edited.

**A5 — equality test scope**: strict byte-equality
(incremental == rebuild) on the SYNTHETIC two-iteration workspace
only; copied real V17/V18r workspace is a legacy backfill smoke +
provenance-availability check, NOT a byte-equality expectation.

**A6 — incremental trigger**: update ONLY on normal completed
iterations with a committed source artifact. NEVER on `no_records`,
`failed`, or crash manifests. `iterations_included` is derived from
the accepted committed sources (no separate monotonic counter).

**A7 — untouched files**: no empty rows for files that never received
a usable score; `files_covered` reports the actual sorted file set.

**A8 — canonical header (compact; strict byte-equality domain)**:

```text
schema_version        # "1"
metric_id             # "tidmad_denoising_score"
score_transform       # "log"
log_base              # 5.27
iterations_included   # sorted list
files_covered         # sorted list
skipped_nonpositive_count  # int
unverified_sources    # int (legacy no-hash count)
validity_semantics    # short prose note
```

No `generated_by` and no `generated_at` (either would break byte
identity). Tool/run metadata may be PRINTED separately but MUST NOT
enter the canonical JSON.

#### 3.7.2 Formal `eval_portion` audit (§3.7 A4 requirement)

Grep + live-artifact check performed 2026-07-27. Findings:

- `formal_eval_portion` exists ONLY as a `HyperparamTuningInput` field
  (`agent/schemas/hyperparam_tuning.py:897`); it is a run-time
  parameter, threaded via the tune protocol into the tuner.
- The tuner's persisted `run_config_iter_NNN.json` (assembled at
  `ml_hyperparameter_tune_agent.py:1969`) does NOT include the field.
  The three formal-related keys it persists are
  `formal_reference_score`, `resolved_skip_formal_threshold`,
  `resolved_bypass_formal_threshold`.
- Verified against two live artifacts:
  - `exploration_loss_v17_20260718_235910/iter_001/.../run_config_iter_001.json`
    — `formal_eval_portion` MISSING.
  - `v18r_arch_10_14/iter_001/.../run_config_iter_001.json`
    — `formal_eval_portion` MISSING.
- The tuner's per-round `ExperimentRecord` writes `eval_portion` only
  when `trial_config.is_trial` (§2.4 trap 2 in this doc); formal
  records genuinely have no key.

**Consequence for P1-C5 (operator revision 2026-07-27)**: legacy rows
correctly hold `eval_portion=null`, but **P1-C5 explicitly requires
formal sampling provenance for new artifacts**, so this PR carries the
smallest write-side change: persist `formal_eval_portion` (and
`formal_strategy`, which pairs with it and is likewise required by
the P1-C5 row schema) in the committed `run_config_iter_NNN.json`.
Modern rows read the committed values; legacy rows stay `null` (never
inferred from current defaults or repo configuration). Both branches
are tested. **FU-P1-7 removed** — this is not a follow-up.

#### 3.7.3 P1-C5 code-audit and file plan

Chain-runner commit/error flow (`sdsc_submission_scripts/run_one_iteration.py`)
audited 2026-07-27 (lines 1462–1534). Structure:

- `write_manifest(iter_dir, run_name, results=[], crashed=True)` on
  every failure branch (2 exception handlers, lines 1469, 1474).
- Normal path: `manifest = write_manifest(iter_dir, run_name, results, ...)`
  at line 1477 (P1-C3 added the incumbent kwargs).
- `[TOKEN_ITER]` rollup at line 1497 is the ESTABLISHED best-effort
  pattern (wrapped in `try/except`; failure prints a `WARN` and never
  breaks the chain). **The per-file-best writer mirrors this pattern
  exactly.**
- Then a branch on `manifest["status"]`: `completed` → `sys.exit(0)`
  at 1513; `no_records` → `sys.exit(0)` at 1530; other → `sys.exit(1)`.

**Placement**: after `write_manifest` (line 1477) and after the
`[TOKEN_ITER]` rollup (line 1503), inside a `try/except` best-effort
block gated on `manifest["status"] == "completed"` (A6). Failure to
write the table logs a `WARN` and never fails the iteration — the
table is not decision state.

**File plan** (minimal, no new abstractions beyond the operator-
requested shared helper):

| File | Change |
|---|---|
| `execute_tools/per_file_best.py` (NEW) | The shared computation: `build_table(workspace) -> dict` walks `{workspace}/iter_*/manifest.json`, verifies hashes when present, parses run_outputs, applies A3 per-file selection using core.resume commit-time validity primitives, returns canonical dict. `write_table(workspace) -> Path` serializes it atomically per A8. |
| `sdsc_submission_scripts/run_one_iteration.py` | After `write_manifest` + `[TOKEN_ITER]` rollup, best-effort call `write_table(args.workspace)` gated on `manifest["status"] == "completed"`. |
| `scripts/rebuild_per_file_best.py` (NEW) | Thin CLI wrapper around `write_table`; also accepts `--print-only` for the backfill smoke. |
| `tests/unit/execute_tools/test_per_file_best.py` (NEW) | The seven design-doc test bullets. |
| `tests/unit/scripts/test_rebuild_per_file_best.py` (NEW) | CLI smoke + rebuild==incremental byte-identity assertion. |

**Shared primitives (P1-C2 ↔ P1-C5) — smallest public boundary
(operator revision 2026-07-27)**: rather than importing several
underscore-private helpers from `core.resume`, expose ONE thin
public entry point that returns the commit-time classification +
artifact-verification information P1-C5 needs. Chosen boundary
(inspected 2026-07-27): a single public function
`classify_committed_record(record, parsed_output, output_path,
workspace)` that returns a small structured result carrying
`validity` (VALID / INVALID / UNKNOWN), `validity_basis`
(`committed_fields|persisted_verdicts|waiver|unknown`) — matching
the A2 gate_summary schema — plus the `round_index` +
`round_provenance` per §3.3. Artifact-hash verification and gate-set
resolution stay INSIDE `core.resume` (the P1-C5 caller passes the
already-parsed output + workspace and receives back the classification
only). No new shared module; no bulk promotion of unrelated resume
internals.

**Write-side additions for P1-C5 A4 (operator revision 2026-07-27)**:
tuner `run_config_iter_NNN.json` (assembled at
`ml_hyperparameter_tune_agent.py:1969`) gains `formal_eval_portion`
and `formal_strategy`. Backfill-blind — historical run_configs still
parse cleanly; missing keys resolve to `null` in per_file_best rows.

## 4. Affected locations

| File | Change | Commit |
|---|---|---|
| `agent/schemas/hyperparam_tuning.py` | `float\|None` widening; comment sweep; trial-best output fields | P1-C1, P1-C4 |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | threshold consolidation; `None` short-circuits; coupling flag; trial-best serialization | P1-C1, P1-C4 |
| `core/resume.py` | `RestoredState` fields + fold + prints | P1-C2 |
| `sdsc_submission_scripts/run_one_iteration.py` | kwarg pass-through; `run_output_sha256` in manifest; `chain_incumbent_used`/`chain_incumbent_source` stamps; manifest trial-best mirror; flag plumb | P1-C2, P1-C3, P1-C4 |
| `workflows/model_exploration.py` | restored kwargs; introduce and thread the separate `chain_formal_incumbent_reference`; remove the post-hoc mutation (`:2462-2463`); preserve `best_score_overall` as current-workflow raw-formal progress only | P1-C3 |
| `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` | named incumbent parameter | P1-C3 |
| `sdsc_submission_scripts/_chain_common.sh`, `scripts/run_comparison.py` | `enable_chain_incumbent_formal_gates` surface (OFF default) | P1-C3 |
| `tests/unit/...` (see per-commit lists) | rewrites + new suites | all |
| `tests/pseudo_data/**` | schema-change mirrors (two-file rule) | P1-C1..C4 |
| `scripts/rebuild_per_file_best.py` (new) + incremental table writer | §3.7 table (restored, rev 3) | P1-C5 |

## 5. Scope and non-goals

**Blocking scope (PR 1 exit condition)** = §3.1-§3.6 (baseline
§2.4.a): reconstruction under commit-time validity, `None`-typed
reference, scope-stamped + hash-verified provenance, deterministic
resume, gate wiring behind the OFF-default
`enable_chain_incumbent_formal_gates` flag, trial incumbent as
persisted read-only context.

**Secondary scope (required)**: §3.7 per-file best table (P1-C5) —
isolated commit, no decision-logic coupling, restored by operator
decision (rev 3) with the strengthened determinism contract; must not
force redesign of the blocking mechanisms; scope-expansion stop rule
per §0.

**Non-goals (explicit)**:

- NO agent-behavior claim. This PR asserts state correctness and
  context availability only (baseline PR 1 rule: "if the PR does not
  validate behavioral use, it must limit its claim to state
  correctness and context availability"). The tuner-planner prompt is
  deliberately NOT touched — no Gate 1-triggering LLM-facing change.
  The agent-behavior checklist items in the baseline are n/a for this
  PR.
- NO fix for the trial-side gate inertness (`memory.time_mode`
  conditional write, HealthGate-valid trial scarcity) — FU-P1-1;
  overlaps PR 3/PR 4 territory.
- NO raw-score fallback for the gates (V18r audit `:544-546`
  recommendation) — interacts badly with `degenerate_penalty_score`
  (§2.5 trap 6); needs its own decision.
- NO `--auto_resume` no_records-overwrite fix (FU-P1-2), NO inspector
  alignment (FU-P1-3), NO threshold recalibration (the Δ 0.5 bypass
  miscalibration belongs to PR 4a).
- NO change to scoring, HealthGate policy, DataScope, or the V18r
  frozen protocol.

**Genericization rider (§1.3, in-passing, own commit or folded into
P1-C2)**: the new `RestoredState` fields and per-file table schema use
dataset-neutral names (`file_index`, metric-agnostic `score`), no new
TIDMAD literals introduced. Coupling ledger entry added when the
ledger exists (PR 2 commit A); nothing blocking here.

## 6. Commit plan

Commit prefix **P1**. Per-commit rule: `implement → checkpoint →
review → next`. Test gate wording per
[`../../gates/gate_testing_standard.md`](../../gates/gate_testing_standard.md).
Schema changes update `tests/pseudo_data/` mirrors in the same commit.

---

### P1-C1 — schema widening + threshold consolidation + comment sweep

**Goal**: `current_run_best_formal_score: float | None = None`; one
authoritative threshold computation; stale doctrine removed.

**Code**:

- [x] `hyperparam_tuning.py:1022-1031` — widen to `float | None`,
      default `None`; rewrite field description (V19 PR 1 semantics);
      sweep `:997-1002`, `:1029-1031`, `:1932-1936`; KEEP `:1004-1010`
      phantom warning verbatim
      *(done 2026-07-27: field + delta-gate descriptions +
      `formal_reference_score` + `best_formal`/`best_valid_formal`
      descriptions updated; phantom warning + v15 motivation block
      untouched. Note: field description forward-references the
      P1-C3 flag `enable_chain_incumbent_formal_gates` — same-PR
      forward reference, disclosed.)*
- [x] `_resolve_formal_comparison_thresholds` — `None`-aware
      (`(None, None, None)` when no reference); helpers
      `_should_skip_formal` / `_should_bypass_formal_time_budget` take
      the RESOLVED threshold, not `(ref, delta)` pairs
      *(done 2026-07-27: signatures changed to `threshold: float | None`;
      `-inf`/`inf` disable semantics preserved inside the helpers; new
      `_fmt_reference` helper renders `None` as `"none"`)*
- [x] Gate call-sites `:2070-2072`, `:2702-2703` — read resolved
      values only (four copies → one)
      *(done 2026-07-27: both inline recomputations deleted; gates
      consume `resolved_skip_formal_threshold` /
      `resolved_bypass_formal_threshold` from the startup resolver —
      verified single remaining raw read of the field is the resolver
      input at `:1953`; resolver and both gate sites confirmed in one
      function scope, no `def` boundary in `:1900-2760`)*
- [x] Startup banner + `run_config_*.json` + output fields render
      `None` as `"none"` (never `0.0`)
      *(done 2026-07-27: banner + [SkipFormal] + [BypassTimeBudget]
      logs via `_fmt_reference`; run_config/output write the resolved
      values — JSON `null` for no-incumbent)*

**Tests** (`tests/unit/agent/tune_ml_hyperparam_agent/test_delta_gates.py`
rewrite + additions):

- [x] default is `None`, and `None` reference → skip gate cannot fire,
      bypass gate cannot fire (both short-circuit)
- [x] numeric reference → thresholds equal resolver output at every
      consumer (no drift; single-source assertion)
- [x] `0.0` is a legal EXPLICIT reference and behaves as before
      (backward compatibility for standalone runs that pass it)
- [x] persisted `formal_reference_score=None` round-trips through
      `HyperparamTuningOutput` and the manifest
      *(output round-trip in test_delta_gates; run_output +
      run_config JSON null + banner "none" in test_tuning_agent's
      default-thresholds test; manifest side lands with P1-C3)*
- [x] negative test: 5.5763-family value as reference is still just a
      number (no special-casing introduced)

**Disclosed test adaptations beyond the design's File list** (same
0.0-pattern the audit identified, found at implementation time):

- [x] `test_valid_candidate_selection.py:70-87` — helper call sites
      updated to the resolved-threshold signature; added `None`-never-
      fires assertions
- [x] `test_tuning_agent.py::test_default_formal_thresholds_persist_and_match_log`
      — pinned the old 0.0 default across output/run_config/banner;
      diagnosis recorded before fix: TEST at fault (production behaved
      per approved design); updated to assert `None`/JSON null/
      `reference=none, skip=none, bypass=none`

**Verification checklist**:

- [x] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent -q`
      → **687 passed, 157.75 s — GREEN** (after the one diagnosed test
      fix above; first run 686 passed / 1 failed)
- [x] `.venv/bin/python -m pytest tests/unit/workflows -q` →
      **206 passed, 10.95 s — GREEN**
- [x] affected-file re-run (delta_gates + valid_candidate_selection +
      tuning_agent + model_exploration) → **181 passed, 127.38 s**
- [x] ruff check + `ruff format --check` clean on all touched files
      (2 SIM102 + 1 RUF059 fixed in code, no suppressions)
- [ ] ~~pyright 0 errors~~ **PYRIGHT NOT RUN — known lilab
      environment limitation** (bundled JS needs Node ≥ 14; box has
      v10.19.0; same as PR #123 disclosure). No pass claimed.

**Test gate**: unit only.

---

### P1-C2 — incumbent reconstruction in `core/resume.py`

**Goal**: `RestoredState` carries the chain incumbents with
provenance; reconstruction is deterministic and replay-stable.

**Code**:

- [x] `RestoredState` + fold at `:648-733` per §3.3 (formal + trial,
      full provenance dicts incl. `round_index`, trial sampling
      fields, `validity_basis`, `artifact_verified`, scope/sha stamps)
      *(done 2026-07-27: 4 new dataclass fields + fold in the walk;
      strictly-greater update makes earliest-iteration-wins automatic)*
- [x] eligibility per §3.3 commit-time rules: committed
      `best_valid_formal_*` fast path; legacy re-derivation from
      PERSISTED gate verdicts + the workspace's effective policy
      artifact only; commit-time validity not establishable →
      `UNKNOWN` → EXCLUDED; repo-current `configs/health_checks.yaml`
      never consulted for decision state
      *(done: `_formal_candidate_from_committed_fields` with the six
      rev-3 summary-vs-source checks; `_commit_time_gate_ids` locates
      the materialized effective config (output-sibling → chain root)
      and accepts it only when its canonical body sha equals the
      stamped `health_config_sha256` — sha recipe mirrors
      `materialize_effective_config` exactly; classifier reused
      verbatim via its `required_gate_ids` parameter)*
- [x] `run_output_sha256` verification per §3.6 (recompute, compare,
      STOP on mismatch via `ReplayIntegrityError(ResumeError)` naming
      artifact + both hash prefixes; legacy no-hash →
      `artifact_verified: false`, visible)
- [x] tie-break rule per §3.3 (explicit comparator `_pick_best`; not
      bare `max`)
- [x] tolerance: missing `best_*` keys contribute nothing; crash
      manifests unchanged (`ResumeError` preserved)
- [x] `[resume] incumbent carry-over: … basis=… verified=…` /
      `… : none` prints (+ matching `trial-incumbent` line;
      `SUMMARY-MISMATCH` warnings)

**Tests** (`tests/unit/core/test_resume_incumbent.py`, new file):

- [x] two committed iters, valid formals 1.2 then 0.8 → incumbent 1.2,
      provenance iter 1 with correct `exp_id` and `round_index` per
      the §3.3 rules
- [x] valid trial only (no valid formal) → formal incumbent `None`,
      trial incumbent set WITH `eval_strategy`, `eval_portion`,
      `train_portion` populated and `round_index` per rules
- [x] **committed-summary validation, positive**: summary fields with
      a matching formal source record (exp_id found, score within
      tolerance, no manifest/stamp conflict) →
      `validity_basis="committed_fields"`
- [x] **committed-summary validation, negatives** (each → UNKNOWN +
      excluded + `[resume] SUMMARY-MISMATCH:` warning): null
      `best_valid_formal_exp_id`; exp_id absent from `all_records`;
      score disagreement beyond `1e-9·max(1,|a|)`; source record is a
      trial; manifest `best_valid_formal_score` conflicts with the
      output field
- [x] **round_index rules**: record with persisted `logical_round` →
      that value, `round_provenance="persisted"`; legacy record with
      null `logical_round` → `round_index=null`,
      `round_provenance="legacy_unknown"` — asserted NOT inferred
      from list position
- [x] `no_records` iter contributes nothing; ordering preserved
- [x] tie (equal scores, iters 2 and 4) → earliest iteration wins;
      same-iter tie → lexicographic `exp_id`
- [x] legacy output without `best_valid_formal_*` fields but WITH
      persisted gate verdicts + effective-policy artifact →
      re-derived, `validity_basis="persisted_verdicts"`
- [x] legacy output where commit-time validity is NOT establishable
      (verdicts missing / effective policy absent) → UNKNOWN →
      excluded (negative)
- [x] repo-policy independence: mutate a COPY of
      `configs/health_checks.yaml` in the test env → reconstruction
      result unchanged (decision state never reads repo policy)
- [x] phantom/collapsed record (`failed_mode_collapse`, score present)
      can never become the incumbent (negative)
- [x] **replay integrity (rev 3)**: tamper with a committed
      `run_output` after manifest hash was written →
      `ReplayIntegrityError` raised BEFORE the next iteration; error
      message contains the artifact path and both hash prefixes
      (verbatim-asserted); no `RestoredState` is produced
- [x] legacy manifest without `run_output_sha256` → candidate
      admitted, `artifact_verified=false` visible in provenance and
      print
- [x] **non-contamination (two-state design, §3.4)**: restored chain
      state never appears in `best_score_overall` or any
      iteration-local `best_*` field; `best_score_overall` never
      reaches tuner input
- [x] missing keys / degraded partial output → no crash, no incumbent
- [x] determinism: same workspace parsed twice → identical
      `RestoredState` incumbent fields

**Verification checklist**:

- [x] `.venv/bin/python -m pytest tests/unit/core/test_resume_incumbent.py -q`
      → **19 passed, 0.95 s — GREEN** (first run 15/19: fixture defect
      — `ExperimentRecord.memory` requires `expert_advice_followed` +
      `hypothesis`; diagnosis recorded: TEST FIXTURE at fault,
      production untouched)
- [x] `.venv/bin/python -m pytest tests/unit/core -q` →
      **446 passed / 2 failed — the 2 failures are PRE-EXISTING**
      (`test_watchdog.py::TestKillTree::{test_kill_leaves_no_orphans,
      test_term_ignoring_child_is_killed}` — reproduce identically on
      a clean `git stash` tree; lilab environment issue, unrelated to
      this commit; not fixed here)
- [x] ruff check + `ruff format --check` clean on both files
- [ ] ~~pyright~~ n/a on lilab (Node < 14; PR #123 precedent)

**Test gate**: unit only.

---

### P1-C3 — threading + `enable_chain_incumbent_formal_gates` (default OFF)

**Goal**: the restored incumbent reaches `HyperparamTuningInput` as a
named protocol parameter; gates consume it ONLY when
`enable_chain_incumbent_formal_gates` is ON; rollback = flag OFF,
never 0.0; iteration-local fields never contaminated (Invariant II).

**Code**:

- [x] five-site threading per §3.4; post-hoc mutation
      `model_exploration.py:2462-2463` removed
      *(done 2026-07-27: run_one_iteration passes
      `restored_chain_incumbent_score` + flag → run_workflow kwargs →
      NEW local `chain_formal_incumbent_reference` (two-state; seeded
      from RestoredState, advanced only by committed VALID formals) →
      protocol named parameter. `best_score_overall` retains only the
      workflow print/summary role.)*
- [x] `enable_chain_incumbent_formal_gates` flag: schema field + tuner
      CLI + `run_one_iteration.py` + `_chain_common.sh` +
      `run_comparison.py`, default OFF; OFF passes `None` to the gates
      while reconstruction/provenance/persistence run UNCONDITIONALLY
      *(done: schema field; tuner CLI arg + input_dict; consumption
      applied at the resolver (`_consumed_reference`); run_config
      records `chain_incumbent_provided` + flag state so
      provided-but-not-consumed is auditable; shell arm/default/
      forwarding follow the `runtime_watchdog` 0/1 pattern; flag added
      to `CONTRACT_FLAGS` in test_chain_consistency.py — parity suite
      green)*
- [x] manifest gains `run_output_sha256` (P1-C2 write side lands
      here with `write_manifest`) plus the consumed-incumbent stamps
      `chain_incumbent_used` (float | null) and
      `chain_incumbent_source` (full provenance dict incl.
      `artifact_verified`); these keys are DISTINCT from every
      iteration-local `best_*` field (Invariant II)
- [x] rewrite `test_trial_only_iter_does_not_poison_formal_anchor`
      (`tests/unit/workflows/test_model_exploration.py:674-714`) to
      assert the INTENT: trial-only iter → next iter's formal
      incumbent is `None` (not `0.0`)
      *(done in P1-C1, disclosed there)*

**Tests**:

- [x] protocol unit
      (`tests/unit/agent/protocols/test_ml_model_valid_to_ml_model_tune.py`):
      named parameter threads; omitted → `None` (+ flag default/thread
      cases; 4 new parametrized ids)
- [x] workflow unit: restored incumbent initializes
      `chain_formal_incumbent_reference` only; `best_score_overall`
      remains derived solely from the current workflow execution's own
      formal results (formal-only update rule preserved; trial score
      never promotes)
      *(`TestChainIncumbentThreading`: restored 5.0 reaches tuner
      input while summary best_score_overall stays 1.8; raw formal 7.7
      never advances the reference)*
- [x] **three-iteration separation test (Invariant II, operator-
      specified)** — `tests/unit/sdsc_submission_scripts/
      test_run_one_iteration.py::TestChainIncumbentManifest::
      test_three_iteration_separation_and_attribution`: iter 2 manifest
      `best_valid_formal_score` is None while `chain_incumbent_used`
      == 1.2 with `source.iter_idx == 1`; iter 3 reconstruction still
      attributes iter 1
- [x] equivalence: in-process `run_workflow(max_iterations=2)`
      incumbent sequence == two chained single-iteration runs over the
      same workspace
      *(split as designed evidence: in-process half in
      `test_valid_formal_advances_reference_across_iterations`
      (iter 2 ref == iter 1's committed valid formal); on-disk half in
      the three-iteration test (write_manifest → restore yields the
      same value) — both halves assert the identical rule/value)*
- [x] flag OFF → gates see `None` even with a restored incumbent
      (rollback semantics) while `chain_incumbent_used` is still
      stamped; flag ON → gates see the restored value
      *(tuner level: `test_incumbent_provided_but_flag_off_not_consumed`
      + flag-ON `test_injected_formal_thresholds_persist` — the
      latter's old flag-less form was DIAGNOSED test-at-fault under
      the new contract and updated; manifest level:
      `test_flag_off_stamps_source_but_not_used`)*
- [x] `--auto_resume` restart mid-chain reconstructs the same
      incumbent (resume determinism)
      *(covered by P1-C2 `test_reconstruction_is_deterministic` —
      every iteration re-derives from disk, no cross-process cache;
      mapping disclosed)*

**Verification checklist**:

- [x] `.venv/bin/python -m pytest tests/unit/workflows tests/unit/agent/protocols
      tests/unit/sdsc_submission_scripts tests/unit/scripts
      tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py
      tests/unit/core/test_resume_incumbent.py -q` →
      **540 passed → after the two diagnosed test fixes: all green**
      (final runs: tuning_agent + chain_consistency 84 passed 120.7 s;
      workflows + sdsc 166 passed 10.9 s; protocols in the 540 sweep)
- [x] ruff check + format clean on all 11 touched files
- [ ] ~~pyright~~ n/a on lilab (Node < 14; PR #123 precedent)

**Test gate**: unit + pseudo integration (P1-V1 covers the chain-level
pseudo run).

---

### P1-C4 — trial incumbent persisted fields (read-only)

**Goal**: `best_valid_trial_*` exists in output + manifest; restored
trial incumbent available on `RestoredState`; nothing consumes it.

**Code**:

- [x] output selection + serialization beside `:3915-3917`; schema
      fields; manifest mirror; pseudo-data mirrors
      *(done 2026-07-27: `valid_trial_records` selection beside the
      formal twin; `best_valid_trial_exp_id`/`_denoising_score` schema
      fields; manifest mirror `best_valid_trial_score`. Pseudo-data
      mirrors n/a — grep shows zero pseudo files carry ANY
      `best_valid*` field (schema defaults apply; PR #124 precedent).)*
- [x] docstring note: bookkeeping notion ≠ `_best_trial_winner` gate
      predicate (`time_mode` requirement) — in code comment + both
      field descriptions

**Tests**:

- [x] trial best selected from valid trial records only; `None` when
      none; formal records never counted
      *(agent-level via pre-seeded sandbox records; first fixture
      attempt DIAGNOSED test-at-fault — stamped
      `health_gate_enabled=False` against a gates-enabled run and DS5
      ingress validation correctly rejected the mixed-policy history;
      fixed to stamp True + passing blocking verdicts)*
- [x] manifest round-trip; legacy manifest without the field → `None`
      (`test_manifest_mirrors_best_valid_trial_score`)

**Verification checklist**:

- [x] `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py`
      → **71 passed, 124.5 s — GREEN**; sdsc suite green in the
      combined 148-passed run; ruff check + format clean
- [ ] ~~pyright~~ n/a on lilab (Node < 14)

**Test gate**: unit only.

---

### P1-C5 — per-file best table (SECONDARY, required, isolated)

**Goal**: §3.7 under the rev-3 determinism contract. Own commit;
touches no decision logic; scope-expansion rule per §0.

**Code**:

- [x] incremental materialization at iteration commit (atomic write,
      canonical serialization, committed-provenance timestamps)
      *(done 2026-07-27: `execute_tools/per_file_best.py`
      `write_table`; atomic temp+`os.replace`; canonical JSON
      (sort_keys, fixed separators, LF, UTF-8); wired into
      `run_one_iteration.py` after `[TOKEN_ITER]` rollup as best-
      effort `[PER_FILE_BEST]`; gated on `manifest["status"] ==
      "completed"` per A6.)*
- [x] `scripts/rebuild_per_file_best.py` (hash-checked sources,
      backfill mode, `unverified_sources` header count)
      *(done: thin CLI wrapper over `write_table` +
      `canonical_bytes`; `--print-only` mode; exits 2 on missing
      workspace.)*
- [x] linear→log conversion + skip counting; formal `eval_portion`
      sourcing rule; raw/valid row separation with record-level
      commit-time validity semantics; metric/transform header
      (`metric_id`, `score_transform`, `log_base`)
      *(done incl. A4 write-side: tuner `run_config` at
      `ml_hyperparameter_tune_agent.py:1969` now persists
      `formal_strategy` + `formal_eval_portion`; per_file_best reads
      committed values, legacy sources resolve to null.)*
- [x] Smallest shared boundary added: `core.resume` gains
      `CommitTimeClassification` (dataclass) + `classify_committed_record`
      (public function) — ONE entry point covering commit-time validity
      + basis label + round provenance. `per_file_best.py` imports
      only these public names; no underscore-private imports.
      Trivial local duplicates (`_iter_run_name`, `_sha256_stream`)
      documented in-place.

**Tests** (all in
`tests/unit/execute_tools/test_per_file_best.py` unless noted; CLI
suite in `tests/unit/scripts/test_rebuild_per_file_best.py`):

- [x] rebuild == incremental (BYTE-identical under the canonical
      serialization contract) on a synthetic two-iteration workspace
      *(`test_rebuild_equals_incremental_byte_identical` + CLI-level
      `test_cli_write_matches_incremental_bytes`)*
- [x] canonical ordering stable under permuted input discovery order
      *(`test_canonical_ordering_stable_under_permuted_iteration_order` —
      touches manifests in reverse then rebuilds; bytes identical)*
- [x] atomicity: interrupted write leaves the previous table intact
      (temp+replace verified)
      *(`test_atomic_write_preserves_previous_on_failure` — patches
      `os.replace` to raise mid-write; original file byte-identical)*
- [x] timestamps derive from record provenance (two runs at different
      wall-clock times → identical bytes)
      *(`test_timestamps_derive_from_record_provenance_not_wallclock`)*
- [x] linear→log conversion correct incl. `-inf`/non-positive skip
      counting
      *(`test_linear_to_log_conversion_and_nonpositive_skip` — 5.27
      → 1.0 exact; 0.0 and -1.5 counted; None never participates.
      **Note**: the `math.inf` case was DROPPED from the fixture —
      does not survive HyperparamTuningOutput JSON round-trip and
      real scoring never emits non-finite floats.)*
- [x] phantom record appears ONLY in raw rows, never valid rows;
      `valid` rows use record-level commit-time validity (a record
      with per-file gate variance still classifies at record level)
      *(`test_phantom_score_only_in_raw_rows` +
      `test_valid_rows_use_record_level_commit_time_validity`; the
      latter's assertion was corrected from `"invalid"` to
      `"unknown"` after diagnosis — commit-time-only rules yield
      UNKNOWN when no matching effective-policy artifact is present,
      per §3.3 rule 3; my initial test contradicted my own design.)*
- [x] tampered / hash-mismatched `run_output` → rebuild refuses the
      input (error names the artifact); incremental path unreachable
      by construction (§3.6 already stopped the chain)
      *(`test_hash_mismatch_raises_replay_integrity` — same fail-
      closed behavior as incumbent walker.)*
- [x] offline real-workspace backfill smoke on a copied V17 iteration
      directory (no GPU/LLM; legacy no-hash sources admitted and
      counted in `unverified_sources`)
      *(`test_legacy_no_hash_manifest_counted_as_unverified` +
      `test_modern_run_config_populates_formal_provenance` — modern
      write-side + legacy-null contract both covered as required by
      A4.)*

**Additional coverage (operator requirements)**:

- [x] failed/missing incremental update is fully recoverable via the
      rebuild path from committed artifacts alone
      *(`test_failed_incremental_recoverable_by_rebuild` —
      simulates a completely absent `per_file_best.json`; rebuild
      writes the full state from `iter_NNN/` committed artifacts.)*
- [x] A6 (`test_no_records_and_missing_iters_skipped`),
      A7 (`test_untouched_files_have_no_rows`),
      A8 (`test_header_shape_and_schema_version` — asserts NO
      `generated_by`, NO `generated_at`),
      trial sampling provenance
      (`test_trial_row_uses_record_sampling_provenance`)

**Verification checklist**:

- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/test_per_file_best.py tests/unit/scripts/test_rebuild_per_file_best.py -q`
      → **18 passed, 1.01 s — GREEN** (first run 4 failures across
      the two suites; all 4 diagnosed as TEST at fault — see the
      corresponding test bullet evidence lines above)
- [x] regression sweep
      (`tests/unit/execute_tools/test_per_file_best.py` +
      `tests/unit/scripts/test_rebuild_per_file_best.py` +
      `tests/unit/core/test_resume_incumbent.py` +
      `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py`)
      → **108 passed, 124.75 s — GREEN**
- [x] regression sweep 2
      (`tests/unit/sdsc_submission_scripts` +
      `tests/unit/core/test_resume.py` + `tests/unit/scripts`)
      → **232 passed, 1.71 s — GREEN**
- [x] ruff check + `ruff format --check` clean on all 7 touched files
- [ ] ~~pyright~~ n/a on lilab (Node < 14; PR #123 precedent)

**Test gate**: unit only.

---

## 7. Validation plan

### P1-V1 — pre-gate sweep (no approval needed)

- [x] Targeted unit suites listed per commit (NOT the full suite;
      per operator testing policy)
      *(each of P1-C1..C5 ticked its own suite as it landed; totals
      recorded per commit)*
- [x] Pseudo integration
      (`tests/integration/workflows/test_chain_incumbent_pseudo.py`),
      **BOTH incumbent branches deterministic** (rev 2 — Gate 2 must
      not depend on a stochastic score outcome):
      - [x] Branch A (numeric incumbent): iter 1 pseudo data contains
            a valid formal → iter 2's tuner input carries it;
            manifest `chain_incumbent_used=1.25` +
            `chain_incumbent_source.iter_idx=1` +
            `artifact_verified=true`; local
            `best_valid_formal_score=0.60` untouched (Invariant II)
            *(`test_branch_a_numeric_incumbent_threads_through_full_chain`
            — real `restore_prior_state` → real `run_workflow` (agents
            mocked) → real `write_manifest`; iter 2's run_output
            written to disk so `run_output_sha256` is stamped)*
      - [x] Branch B (no incumbent): iter 1 pseudo data has no valid
            formal → iter 2's tuner input receives `None`;
            `chain_incumbent_used=null`; gates short-circuit
            *(`test_branch_b_no_incumbent_short_circuits`)*
      - [x] flag OFF variant: reconstruction + stamps still present,
            gates inert
            *(`test_branch_c_flag_off_reconstruction_still_stamps_source`;
            during-run diagnosis recorded — my initial assertion
            "tuner input receives None" contradicted §3.4: numeric
            value is delivered unconditionally, only CONSUMPTION is
            gated; assertion corrected + tuner-side flag-OFF
            short-circuit remains covered by the P1-C1 unit
            `test_incumbent_provided_but_flag_off_not_consumed`)*
      - [x] BONUS: end-to-end replay-integrity fail-closed at chain
            boundary (`test_tampered_iter1_artifact_stops_the_chain`)
- [x] `ruff check` + `ruff format --check` on all P1-C1..C5 + P1-V1
      touched files (see per-commit verification checklists);
      pyright n/a on lilab (Node < 14, PR #123 precedent)

Suite result: **4 passed, 1.42 s — GREEN**. Regression sweep across
P1-C1..C5 areas + this new suite: **296 passed, 11.13 s**. After the
documentation-surface + runtime-log additions (below), full tuner
suite: **71 passed, 124.2 s** with the strengthened Branch C also
covering the direct gate-consumption proof.

**Documentation-surface additions (operator revision 2026-07-27,
included in the same P1-V1 commit)**: audit found zero user-facing
mentions of the flag; the canonical explanation now lives in
`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
under "Chain formal-incumbent reference" (three-part contract: what
the reconstructed incumbent is; behavior with coupling ON; behavior
with coupling OFF — including the explicit "OFF is NOT a fixed-0.0
mode" clarification). Cross-references + concise notes added at the
schema field, tuner CLI `--help`, inline resolver comment, tuner
startup banner (new `[chain_incumbent] provided=… coupling=…
consumed=…` line closing the previously-scattered runtime-log gap),
`docs/running_chain_test.md`, and a legacy-pointer note on the older
top-level `nodes/ml_hyperparameter_tune_agent.md`. Every wording is
consistent with the ON = `chain_incumbent + fixed_delta` /
OFF = reconstructed-but-not-consumed / OFF ≠ 0.0 contract.

**Branch C strengthening (operator requirement 2026-07-27)**: added
direct gate-consumption proof using production helpers
(`_resolve_formal_comparison_thresholds`, `_should_skip_formal`,
`_should_bypass_formal_time_budget`) applied to the value actually
delivered on the tuner input under flag OFF. Asserts (a) consumed
reference is `None`, (b) both resolved thresholds are `None`,
(c) neither gate fires against a hypothetical high-scoring valid
trial record.

Diagnosed test failures during authoring (all TEST at fault, reported
before fixing):
1. `unittest.mock.patch(...) as name` cannot appear inside a plain
   tuple — refactored `_run_iter_2` to `contextlib.ExitStack`.
2. Missing schema-required fields on `ProposalOutput` (`expert_advice`)
   and `ImplementorOutput` (`model_type`, `description_file_path`,
   `model_file_path`, `test_file_path`, `config_fields`,
   `model_description`, `mathematical_definition`) — verified via
   `model_fields` inspection; test fixtures updated.
3. `run_output_sha256` missing on iter 2's manifest — production
   tuner writes the run_output; my mocked HyperparamTuningAgent
   didn't, so `write_manifest`'s `os.path.isfile` guard skipped the
   hash. Test now mirrors production by writing iter 2's run_output
   to the tuner's expected path before `write_manifest`.
4. See Branch C evidence line above.

### P1-V2 — Gate 2: standalone smallest canonical smoke — **REQUIRES OPERATOR APPROVAL**

**Operator decision (rev 2): standalone smallest canonical Gate 2
configuration from `docs/gates/gate_testing_standard.md` — NOT a
V18r-adjacent piggyback.** 2 chained iterations, real LLM + real
training, `enable_chain_incumbent_formal_gates` ON. Because BOTH
incumbent branches are already deterministically covered in P1-V1
pseudo, Gate 2 validates **end-to-end artifact consistency and
no-regression for whichever branch the real run produces** — it does
not need to force a particular stochastic score outcome.

#### P1-V2 launch plan — drafted 2026-07-27, awaiting operator approval

**Scope** (derived from `docs/gates/gate_testing_standard.md` "Lite
Plan" adapted for PR 1): 2 chained iterations (chain-incumbent test
needs a prior iteration for iter 2 to consume; Lite's default 1 is
insufficient), force_formal_round default ON (Lite; the incumbent
flows through the formal path — we want the `[chain_incumbent]`
banner + manifest stamps observed on a real formal round), DataScope
`4-9` (Lite's smallest 6-file scope), portions from Lite,
`enable_chain_incumbent_formal_gates=ON`. No V18r piggyback: fresh
`/tmp/checkpoint_pr1_...` workspace, standalone. Outcome-agnostic per
operator direction — both incumbent branches already deterministically
covered in P1-V1, so pass criteria verify **consistency across the
three runtime surfaces** whichever branch the real run produces.

**What this smoke primarily validates** (operator clarification,
2026-07-27):

- incumbent reconstruction;
- iteration-1 → iteration-2 threading;
- the reference actually presented to the formal-gate logic;
- consistency among logs, run_config, manifest, and run_output;
- preservation of iteration-local results (Invariant II).

**What this smoke does NOT prove — `force_formal_round` interaction
(operator clarification, 2026-07-27)**: with `force_formal_round`
enabled (Lite default), the tuner will typically continue to formal
evaluation **even when an incumbent comparison exists** — the
skip-formal gate is not required to fire for the smoke to pass, and
this Gate 2 does not attempt to demonstrate production skip behavior.
The skip/bypass gate mechanics are covered separately by P1-C1 unit
tests (`test_delta_gates.py`) and by P1-V1's Branch A/B/C
deterministic pseudo-integration coverage. **Any claim about
production skip behavior after this Gate 2 must be backed by direct
evidence from the actual logs of the run** — do not infer skip
behavior from the mere presence of an incumbent.

**Exact command** (lilab; single invocation, no `tee`). Every line
ends with a bare `\` — no trailing inline comments — so the block is
copy-pasteable verbatim into a shell:

```bash
WS=/tmp/checkpoint_pr1_$(date +%s)
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace "$WS" \
    --run_name pr1_v2_smoke \
    --num_iterations 2 \
    --max_rounds 2 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --data_scope 4-9 \
    --health_gate_files 4,5,6,7,8,9 \
    --trial_portion 0.02 \
    --train_portion 1.0 \
    --eval_portion 0.01 \
    --formal_portion 0.02 \
    --formal_train_portion 1.0 \
    --formal_eval_portion 0.01 \
    --trial_time_budget_minutes 5 \
    --formal_time_budget_minutes 30 \
    --trial_vram_budget_gb 24 \
    --formal_vram_budget_gb 24 \
    --runtime_watchdog \
    --enable_chain_incumbent_formal_gates \
    --llm_config llm_configs/openai_tiered_v1.json
```

Notes:

- `--enable_chain_incumbent_formal_gates` is the P1-C3-added shell
  arm (`_chain_common.sh:215`) that forwards to the tuner as
  `--enable_chain_incumbent_formal_gates` (P1-C3c).
- `--health_gate_files 4,5,6,7,8,9` is **REQUIRED** under any partial
  `--data_scope`. DS8 boundary enforcement (`run_one_iteration.py`
  startup) refuses to launch when the shipped
  `configs/health_checks.yaml`'s `peek_file_indices` fall outside the
  resolved DataScope OR when any check omits an explicit peek list
  under partial scope. The values must EXACTLY equal the resolved
  DataScope. V18r's launcher pairs these two flags together at
  `sdsc_submission_scripts/launch_v18_wave1.sh:121`.
- **NO `--seed_paths`**: this smoke uses **cold-start** (PR #126).
  The Gate-standard Lite Plan's canonical seeds
  (`small_sample_trial_v0` wavenet + punet) are pre-DS8 full-scope
  artifacts; DS8's `validate_stamped_invariants` refuses to admit
  legacy unstamped ingress evidence into a partial-scope run (the
  attempt-2 failure below). V18r's launcher runs the same partial
  scope without any `--seed_paths` and lets the interpreter's
  deterministic cold-start path (`nodes/result_interpretation_agent`
  under `cold_start=True`, from PR #126) emit a "no prior evidence"
  digest, followed by the normal proposer→implementor→validator→
  tuner flow. Iter 1's committed DS-4-9-stamped `run_output` is then
  a valid predecessor for iter 2's chain-incumbent reconstruction.
  Do not add `--seed_paths` for any partial-scope Gate 2 unless
  DS-scope-stamped seeds for the exact scope are available.

**Scope, rounds, iterations, portions** (spelled out from the command
above, all matching Lite Plan defaults except iteration count):

| Knob | Value | Source |
|---|---|---|
| Iterations | 2 | PR 1 requirement (chain incumbent needs a prior) |
| Rounds per iter | 2 | Lite default |
| Proposal attempts per iter | 3 | Lite default |
| Max epochs | 1 | Lite default |
| DataScope | files 4-9 (6 files) | Lite default |
| HealthGate monitored files | `4,5,6,7,8,9` — exactly matches DataScope | DS8 requirement (see notes above) |
| `trial_portion / train_portion / eval_portion` | 0.02 / 1.0 / 0.01 | Lite default |
| `formal_portion / formal_train_portion / formal_eval_portion` | 0.02 / 1.0 / 0.01 (→ ~3,000 training steps @ seg 10k b8; 12 eval PSD) | Lite default |
| `trial_time_budget_minutes` | 5 | Lite default |
| `formal_time_budget_minutes` | 30 (Gate-specific; production stays 120) | Lite default |
| `trial_vram_budget_gb / formal_vram_budget_gb` | 24 / 24 (generous per Lite policy) | Lite default |
| `runtime_watchdog` | on (passive validation) | Lite default |
| `force_formal_round` | default ON | Lite default (needed to exercise the incumbent flow through the formal path) |
| `enable_chain_incumbent_formal_gates` | **ON** | PR 1 P1-V2 |
| LLM config | `openai_tiered_v1.json` (gpt-5.4 dominant) | Gate-2 mandatory |
| Seeds | canonical wavenet + punet lilab seeds | Gate-2 canonical |

**Expected LLM calls** (per Lite/iteration profile in the gate
standard: ~15 min of LLM setup per iter = interp + 3-stage proposer +
implementor + validator; then 2 tuner rounds × 2 LLM sub-calls
[planner + reflector]). Rough envelope per iter: ~10 role-level calls
plus tuner sub-calls; **2 iters → ~25-35 total LLM calls**.

**Expected wall time**: **~50-80 min** (Lite is ~30-45 min for 1
iteration; 2 iterations doubles the LLM setup + trial rounds; the
single forced-formal round per iter is capped at
`formal_time_budget_minutes=30`, typically ~1-5 min at Lite's tiny
portions).

**Expected GPU time**: bounded by 2 iters × (2 trial rounds ≤5 min
each + 1 forced-formal round ≤~5 min at Lite portions) + subprocess
startups ≈ **~25-45 min GPU** (upper bound).

**API cost**: **~$2-3** (Lite is ~$1 for 1 iteration; 2 iterations
double the gpt-5.4 dominant cost).

**Hard upper bound**: **120 minutes wall / $5 API cost / 60 GB `/tmp`**.
If exceeded, kill immediately (see stop conditions).

**Stop conditions**:

1. **Time cap**: if wall exceeds 120 min from launch, kill the chain
   process group (`pkill -TERM -f run_chain.sh`; wait 30 s; `pkill
   -KILL -f run_chain.sh`) and record cause.
2. **Disk cap**: if `du -sh /tmp/*` shows > 60 GB total or `$WS` > 40
   GB during the run, kill and record cause (Lite portions should
   nowhere near this — this is a safety net).
3. **Repeated LLM validation failures**: if all 3 proposal attempts
   fail validation for both iterations, kill and record cause per
   the gate standard's failure-handling guidance (indicates LLM
   quality issue, not a PR 1 bug).
4. **Cost cap**: if operator's OpenAI dashboard shows this run
   crossing $5, kill immediately.
5. **Manual abort**: `Ctrl-C` (SIGINT) is safe at any point; the
   chain runner traps it, writes a `crashed` manifest for the
   in-flight iter, and stops.

**Exact pass criteria** (verbatim quotes required from the artifacts
below; anti-hallucination — do not paraphrase log lines or JSON
values):

*Gate-2 standard baseline criteria (docs/gates/gate_testing_standard.md
§Pass criteria — HealthGate framework correctness)*

1. Chain exits 0.
2. Every completed round has a recorded `gate_action` in
   `final_record` (any value: `continue`, `INVALIDATE_ROUND`,
   `SKIP_TO_FORMAL`, `SKIP_ITER`).
3. Every `denoising_score` is either finite-positive, OR
   `None`/`-inf` WITH a corresponding invalidating `gate_action` in
   that round's record.
4. No phantom `5.5762667` appears as a final accepted score.
5. At least one round triggers a HealthGate evaluation.

*PR 1 specific criteria — three-surface consistency (whichever
branch iter 1 produces)*

6. **Iter 2 tuner startup banner emits the new `[chain_incumbent]`
   line** with format `[chain_incumbent] provided=<X|none>;
   coupling=ON; consumed=<Y|none>` — verbatim-quoted from iter 2's
   log. `coupling=ON` is mandatory (matches the launch flag).
7. **Branch A (iter 1 produced a commit-time-VALID formal)**: iter
   2's `[resume] incumbent carry-over:` log line, iter 2's
   `[chain_incumbent] provided=…` value, iter 2's `Formal
   comparison thresholds: reference=…` value, and iter 2's manifest
   `chain_incumbent_used` all agree bit-for-bit (float `==`) with
   iter 1's manifest `best_valid_formal_score`. Iter 2's manifest
   `chain_incumbent_source.iter_idx == 1`, `.exp_id == iter 1's
   `best_valid_formal_exp_id`, `.artifact_verified == true`.
8. **Branch B (iter 1 produced no commit-time-VALID formal)**: iter
   2's `[resume] incumbent carry-over: none`, iter 2's
   `[chain_incumbent] provided=none; coupling=ON; consumed=none`,
   iter 2's `Formal comparison thresholds: reference=none, skip=none,
   bypass=none`, iter 2's manifest `chain_incumbent_used=null` and
   `chain_incumbent_source=null` — all four consistent.
9. **Invariant II (both branches)**: iter 2's manifest
   `best_valid_formal_score` reflects ONLY iter 2's own rounds —
   never equals iter 1's committed value except by coincidence (in
   which case iter 2's `chain_incumbent_source` still names iter 1,
   not iter 2). The two keys are structurally distinct in the
   manifest.
10. **Replay integrity**: both manifests carry a
    `run_output_sha256`; neither iter is re-run against a modified
    prior artifact (verify by comparing the `run_output_sha256`
    value in iter 1's manifest to a fresh `sha256sum` of iter 1's
    `run_output_iter_001.json` post-run).

**Exact files and logs to inspect** (chain-runner logs land in the
harness capture; workspace files land at `$WS/`):

| Artifact | Path | Used by criteria |
|---|---|---|
| Iter 1 manifest | `$WS/iter_001/manifest.json` | 7, 8, 9, 10 |
| Iter 1 run_output | `$WS/iter_001/iteration_001/<model>/run_output_iter_001.json` | 4, 10 (hash re-verify) |
| Iter 2 manifest | `$WS/iter_002/manifest.json` | 7, 8, 9, 10 |
| Iter 2 startup log | harness capture, look for `[resume] incumbent carry-over:` / `[chain_incumbent] provided=` / `Formal comparison thresholds: reference=` in iter 2's block | 6, 7, 8 |
| Chain summary | harness capture / `$WS/iter_002/manifest.json` `status` | 1 |
| Per-round records | iter N `run_output_iter_00N.json` `all_records[*]` | 2, 3, 4, 5 |
| HealthGate evaluations | iter N `run_output_iter_00N.json` `all_records[*].health_gate_results` | 5 |

Verbatim-quoted evidence pattern (per anti-hallucination rule):
> "iter 2 log line 12345: `[chain_incumbent] provided=1.2500; coupling=ON; consumed=1.2500`; iter 1 manifest `best_valid_formal_score`: `1.25`; iter 2 manifest `chain_incumbent_used`: `1.25`; iter 2 manifest `chain_incumbent_source`: `{"iter_idx":1,"exp_id":"…","artifact_verified":true,…}`."

**Cleanup behavior after timeout or failure**:

- On success or normal completion: **keep `$WS` for post-run audit
  and evidence recording** (small — under 1 GB at Lite portions).
  Operator may delete manually after the P1-V2 result line is
  filled.
- On stop-condition timeout / kill: **do not auto-delete** — the
  partial artifacts (crashed manifest, partial run_output, any hash
  written) are needed to diagnose. Cleanup only after operator
  confirms the run is unrecoverable.
- On repeated LLM validation failures (stop condition 3): keep the
  full workspace + logs for LLM-quality diagnosis.
- Process cleanup: `pkill` sequence in stop condition 1 targets only
  the chain process group; the tuner subprocess trees are children
  and get SIGTERM'd cleanly. If a training subprocess survives past
  the SIGKILL wait, `nvidia-smi` may show orphaned CUDA context;
  `pkill -KILL -f run_one_iteration` clears it.
- Disk cleanup: `rm -rf $WS` when done. Also `rm -rf /tmp/pytest-of-*`
  if any test artifacts leaked (unlikely from a Gate run).

**Preflight checklist** (before launch — operator to confirm):

- [ ] `git status` clean on `feat/v19-pr1-chain-incumbents`
- [ ] Canonical seed files exist:
      `/home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/...`
      and the punet twin
- [ ] `llm_configs/openai_tiered_v1.json` exists and OpenAI API key
      is loaded
- [ ] `$WS` chosen and its parent filesystem has **≥ 90 GB free**
      before launch (operator clarification, 2026-07-27: the 60 GB
      disk hard cap in the stop-conditions must be covered plus a
      ~30 GB reserve for the system and any other concurrent
      processes). Verify with `df -h "$(dirname "$WS")"` and refuse
      to launch if the "Avail" column is below that threshold —
      running the disk cap to zero can wedge the box or fail other
      services. If `/tmp` is tmpfs-backed and smaller than 90 GB
      free, choose a workspace on a larger disk-backed filesystem
      instead.
- [ ] `pyright` limitation on lilab is accepted (PR #123 precedent)
- [ ] Wall-clock start noted; 120-min timer set
- [ ] **Partial-DataScope HealthGate pairing (added after the 2026-07-27
      first-attempt failure)**: verify `--health_gate_files` is present
      in the command AND its value EXACTLY equals the resolved
      `--data_scope`. Confirm by parsing the launch command:
      `awk` the two flag values and assert equal. Never launch a
      partial-scope smoke without this pairing — DS8 refuses at
      startup, but the CI parity test (`test_chain_consistency.py`)
      does not catch a MISSING flag, only a mismatched forwarding.
- [ ] **CLI parse dry-run**: run
      `bash sdsc_submission_scripts/_chain_common.sh` argparse-equivalent
      or launch with `--dry_run` and confirm every flag parses and
      every seed path resolves before real launch. (See
      `docs/running_chain_test.md` "§3.2 flags" section for the
      canonical dry-run recipe.)

**Reporting after the run** (regardless of outcome):

- Fill P1-V2 result line below with: **PASS** / **PASS WITH
  LIMITATIONS** / **FAIL**, plus which incumbent branch (A or B)
  the real run produced, plus the verbatim evidence for criteria
  6-10.
- Update the validation budget table below with actual wall / GPU /
  API cost.
- Record any deviations from the launch command with rationale.

#### P1-V2 attempt log

**Attempt 1 — 2026-07-27 23:18:00-07:00 — FAILED at preflight
(no cost incurred)**

- Workspace: `/tmp/checkpoint_pr1_1785219480/` (retained for review;
  contains only a crash `manifest.json` — safe to `rm -rf` any time
  once the operator no longer needs it).
- Failure timing: exit code 1 at `2026-07-27T23:18:01-07:00` — under
  1 second after launch, during `run_one_iteration.py`'s
  run-invariants pre-flight (before any subprocess launch).
- Cause: the launch command omitted `--health_gate_files` while
  passing `--data_scope 4-9`. DS8 boundary enforcement refuses to
  start when the shipped `configs/health_checks.yaml`'s
  `peek_file_indices` (`[3, 10, 17]` on blocking checks; empty on
  recording checks → interpreted as "full dataset access") fall
  outside the resolved partial DataScope. Verbatim error from the
  log:
  ```
  FAIL: run-invariants computation refused to start: HealthGate
  monitored files violate the DataScope:
    - gate 'output_diversity_blocking' check 'output_diversity':
      peek_file_indices [3, 10, 17] outside the DataScope
      [4, 5, 6, 7, 8, 9]
    - gate 'output_std_blocking' … (same)
    - gate 'amplitude_collapse_blocking' … (same)
    - gate 'pearson_dispersion_recording' check
      'pearson_dispersion': no explicit peek_file_indices
      (defaults to full-dataset access) — an explicit in-scope
      list is required under a partial DataScope
    - gate 'spectral_peak_ratio_recording' … (same)
    - gate 'per_file_output_std_recording' … (same)
    Remediation: pass --health_gate_files with in-scope files
    (one shared list, applied to every check), or disable the
    subsystem with --no-health_gate_enabled.
  ```
- Cost: **$0.00 LLM, 0 s GPU, 0 training runs** — the chain crashed
  before any real work.
- Resolution: paired `--health_gate_files 4,5,6,7,8,9` added to the
  Exact command block above (matches V18r's launcher pattern at
  `sdsc_submission_scripts/launch_v18_wave1.sh:121`); new preflight
  rules added above to prevent recurrence.
- Doc gap identified in the Gate standard → filed as **FU-P1-8**
  (see §9 tracker).

**Attempt 2 — 2026-07-27 23:27:24-07:00 — FAILED at preflight
(no cost incurred)**

- Workspace: `/tmp/checkpoint_pr1_1785220044/` (retained for review;
  contains only a crash `manifest.json` — safe to `rm -rf` any time).
- Failure timing: exit code 1 at `2026-07-27T23:27:26-07:00` — under
  2 seconds after launch, inside `run_workflow`'s ingress-validation
  step (`workflows/model_exploration.py:1763`), immediately after
  the plugin registry preload and before any LLM call.
- Cause: the (now attempt-1-fixed) launch command still carried the
  Gate-standard's canonical `--seed_paths` (wavenet + punet
  `small_sample_trial_v0`). Those run_outputs were produced before
  DS8 shipped and are unstamped (`resolved_data_scope` absent →
  legacy = full scope `[0..19]`). DS8's
  `validate_stamped_invariants` (`core/run_invariants.py:321`)
  refuses to admit legacy full-scope ingress evidence into a
  partial-scope `[4-9]` run. Verbatim error from the log:
  ```
  core.run_invariants.RunInvariantsViolation: ingress evidence from
  seed/restored output 'small_sample_trial_v0_agent' (wavenet) is
  incompatible with this run's invariants:
    - resolved_data_scope: record is unstamped (legacy = full scope)
      [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
      vs this run's [4, 5, 6, 7, 8, 9]
    Records are only comparable within one invariant set — start a
    new workspace, or seed with matching-scope evidence.
  ```
- Cost: **$0.00 LLM, 0 s GPU, 0 training runs** — the chain crashed
  in ingress validation, before the interpreter's first LLM call.
- Resolution: **remove `--seed_paths` entirely — cold-start**. The
  Exact command block above now omits the flag. V18r's launcher
  (`sdsc_submission_scripts/launch_v18_wave1.sh` + `_chain_common.sh:280-283`)
  runs the identical `4-9` partial scope without any seeds and lets
  PR #126's seedless cold-start take over; the interpreter emits a
  deterministic "no prior experimental evidence" digest without any
  LLM call, then the normal proposer→implementor→validator→tuner
  chain runs as usual. Iter 1's committed DS-4-9-stamped run_output
  is a valid predecessor for iter 2's chain-incumbent reconstruction.
- Doc gap in the Gate standard NOW covers both DS8 rules → filed
  under the expanded **FU-P1-8** (see §9 tracker).

**Cumulative attempt cost**: $0.00 LLM, 0 s GPU. Both crashed
workspaces retained (`/tmp/checkpoint_pr1_1785219480/`,
`/tmp/checkpoint_pr1_1785220044/`) — a few KB each; safe to
`rm -rf` any time.

**Attempt 3 — 2026-07-27 23:33:26 → 23:50:44 -07:00 — PASS WITH
DOCUMENTED LIMITATIONS**

- Workspace: `/tmp/checkpoint_pr1_1785220406/` (retained for review
  per plan; do NOT delete yet).
- Command: exact form committed in `9a0a083` + cold-start
  refinement in `69da366` (no `--seed_paths`).
- Wall time: **17 min 18 s** (well inside 50-80 min expected /
  120 min hard cap).
- Chain exit code: 0. Both iterations completed (`completed_rounds=2`
  each), both landed as `status: "no_records"` — cold-start invented
  `tiny_spectral_gated_token_mixer_baseline`; every scoring round
  was invalidated by HealthGate, no round produced a valid finite
  score. This is the design's **Branch B path** (iter 1 produces no
  commit-time-valid formal → iter 2 has no incumbent to
  reconstruct).

**Applicable pass criteria (evidence verbatim from log + manifests):**

Baseline Gate 2 criteria (§`docs/gates/gate_testing_standard.md`):

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Chain exits 0 | ✅ PASS | notification exit_code=0; log tail `EXIT CODE: 0` |
| 2 | Every scoring round has `gate_action` in final_record | ✅ PASS | 4 scoring records (iter1 r003, r006; iter2 r001, r003) all carry `gate_action='invalidate_round'` |
| 3 | Every `denoising_score` is finite-positive OR None+invalidating gate_action | ✅ PASS | **Four scoring records were inspected. Two had finite scores (iter1 r003 = -1.856; iter2 r001 = -2.908) and two had no score (iter1 r006 = None; iter2 r003 = None). All four were invalidated with explicit gate failures — `gate_action='invalidate_round'` and non-empty `blocking_failed_gate_ids`. No score survived the gates.** |
| 4 | No phantom 5.5762667 as final accepted score | ✅ PASS | scanned all 9 records; no score within 1e-4 of 5.5762667; no accepted scores anywhere |
| 5 | ≥1 round triggers HealthGate | ✅ PASS | 4 rounds fired with `['output_diversity', 'output_std', 'amplitude_collapse']` blocking-failed under `any_pass` aggregation |

PR-1 specific criteria (this run exercised Branch B; Branch A + hash
write/verify remain deterministically covered elsewhere):

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 6 | Iter 2 `[chain_incumbent]` startup banner emits with `coupling=ON` | ✅ PASS | log line 2433 verbatim: `[chain_incumbent] provided=none; coupling=ON; consumed=none` |
| 7 | Branch A cross-surface consistency (numeric incumbent) | **NOT EXERCISED** in this real run — cold-start produced no commit-time-valid formal to reconstruct. Deterministically covered by P1-V1 `test_branch_a_numeric_incumbent_threads_through_full_chain` |
| 8 | **Branch B cross-surface consistency (no incumbent) — the primary claim validated by this real run** | ✅ PASS | All four surfaces agree "none":<br>• iter 2 log line 2293: `[resume] incumbent carry-over: none`<br>• iter 2 log line 2432: `Formal comparison thresholds: reference=none, skip=none, bypass=none`<br>• iter 2 log line 2433: `[chain_incumbent] provided=none; coupling=ON; consumed=none`<br>• iter 2 `manifest.json`: `"chain_incumbent_used": null`, `"chain_incumbent_source": null` |
| 9 | Invariant II (iter-local ≠ chain-state keys) | ✅ PASS | iter 2 manifest keys structurally distinct: `best_valid_formal_score: null` (iter-local — iter 2 rounds produced no valid formal) sits alongside separate `chain_incumbent_used: null` / `chain_incumbent_source: null` (chain-state). No cross-contamination |
| 10 | Replay integrity write side | **NOT EXERCISED** in this real run — both manifests are `status: "no_records"` → `output_path: null` → `write_manifest` correctly skips `run_output_sha256` (P1-C3e code path). Deterministically covered by P1-V1 `test_branch_a_numeric_incumbent_threads_through_full_chain` (hash presence) and P1-C2 `test_tampered_iter1_artifact_stops_the_chain` / `test_hash_mismatch_raises_replay_integrity` (mismatch detection) |

**What the real run did and did NOT validate**:

- **DID validate**: the Branch B no-incumbent path end-to-end, including
  reconstruction (`[resume] incumbent carry-over: none`), delivery to
  the tuner input, the resolver's None short-circuit (both resolved
  thresholds null), the manifest chain-state stamps (`chain_incumbent_used`
  and `chain_incumbent_source` both null), and the operator-requested
  `[chain_incumbent]` runtime line rendering with `coupling=ON`.
- **DID NOT exercise (remains covered by tests)**: the Branch A
  numeric-incumbent path (deterministic in P1-V1) and the replay-
  hash write/verify path (deterministic in P1-V1 + P1-C2 unit
  tests). Neither gap represents a production risk; the operator
  plan was explicitly outcome-agnostic on Branch A vs B.

**Actual resource usage**:

| Metric | Actual | Budget/cap |
|---|---|---|
| Wall time | 17 min 18 s | 50-80 min expected, 120 min hard cap |
| LLM calls | **27 real OpenAI calls** (gpt-5.4 dominant, plus mini + nano tiers) across proposer.comparison×2, proposer.causal_reasoning×2, proposer.proposing×6, implementor.reasoning×1, implementor.code×1, validator.code_review×2, tuner.planner×9, tuner.reflector×4 | ~25-35 expected |
| API cost | **Not directly reported** — the token-usage telemetry logged 27 calls but did not populate per-call `tokens.input`/`tokens.output` fields on this branch (pre-existing telemetry gap, unrelated to PR 1). **Exact cost unavailable; estimated to remain within the approved $5 hard cap** given call count + Lite-tier price structure (Gate standard's Lite Plan itself estimates ~$1 for a 1-iter run of similar shape) | $5 hard cap |
| GPU time | ~5 min (four watchdog-killed training attempts at 60-132 s each + minor formal training) | 25-45 min expected |
| Disk (workspace) | ~few MB (no denoised outputs retained — gates invalidated all scoring rounds; `cleanup_denoised` default on) | 60 GB hard cap; `/tmp` had 538 GB free |

**Telemetry limitation** (for post-run reporting only, not a PR-1
issue): `token_usage.jsonl` records 27 calls with correct
`{ts, run_id, iter, label, model, provider}` metadata but empty
`tokens.input`/`tokens.output`. Consequence: exact per-run API-cost
attribution isn't possible from the workspace alone; the OpenAI
dashboard is authoritative if precise cost is needed.

**Cumulative attempt cost (all 3 attempts)**: 27 real LLM calls, no
training success (all gate-invalidated), zero cost incurred by
attempts 1 & 2, attempt-3 cost unattributed but estimated within
the $5 cap.

- [x] **Gate 2 result recorded here: PASS WITH DOCUMENTED LIMITATIONS
      — Branch B no-incumbent path validated end-to-end; Branch A
      numeric-incumbent and replay-hash write/verify paths not
      exercised in this real run and remain covered by unit +
      pseudo-integration tests (P1-V1 + P1-C2).**

### Validation budget table (baseline §4.4 — estimates filled at P1-D approval)

```text
layer                | scenarios | samples | LLM calls | training runs | wall | GPU | API cost | hard cap | approval
unit (P1-C1..C5)     | n/a       | n/a     | 0         | 0             | ~min | 0   | 0        | n/a      | none
pseudo chain (P1-V1) | 3 (A/B/off)| 1      | 0         | 0 (stub)      | ~min | 0   | 0        | n/a      | none
backfill smoke (C5)  | 1         | 1       | 0         | 0 (offline)   | ~min | 0   | 0        | n/a      | none
Gate 2 (P1-V2)       | 1         | 1       | 27        | 2 iters, 0 valid | 17m18s | ~5m | not reported (≤$5 est.) | 120m/$5/60GB | OPERATOR (approved 2026-07-27, PASS WITH DOCUMENTED LIMITATIONS)
```

No Layer-2/Layer-3 agent-behavior campaign: this PR makes no
behavioral claim (§5).

## 8. Merge and activation

- **Merge** (P1-S): after P1-C1..C5 landed (P1-C5 included — required
  secondary scope) + P1-V1 green + P1-V2 passed + stop-and-show
  approved. Coupling flag remains OFF in every production launcher at
  merge.
- **Replay-integrity note**: a `ReplayIntegrityError` stop is not a
  rollback path and is not bypassed by the coupling flag —
  `enable_chain_incumbent_formal_gates=OFF` disables gate consumption
  only; integrity verification always runs.
- **Activation** (P1-ACT): separate operator decision flips
  `enable_chain_incumbent_formal_gates` ON in the chain launchers;
  evidence reviewed post-activation (first live iteration's banner +
  manifest). Baseline §4.5 applies.
- **Rollback**: flag OFF. Reconstruction, provenance, and persistence
  remain active; decision coupling stops. The fixed-0.0 defect cannot
  be reinstated by any supported configuration.

## 9. Follow-up tracker (NOT blocking PR 1 merge)

- [ ] FU-P1-1 — `memory.time_mode` conditional write (`:3506,3513`)
      makes `_best_trial_winner` (and both delta gates + `full_clone`
      inheritance) silently inert when the time gate does not run.
      File as GitHub issue; overlaps PR 3/4 scope.
- [ ] FU-P1-2 — `--auto_resume` `no_records` overwrite bug
      (`docs/chain_skip_unproductive_iters_design.md:185-198`).
- [ ] FU-P1-3 — `scripts/inspect_run_state.py` and
      `scripts/v18_wave_summary.py` read raw/valid bests, not
      `best_valid_formal_score`; align after PR 1 lands.
- [ ] FU-P1-4 — eligibility-vs-locked-config drift
      (`candidate_eligibility.py:37-46` reads repo config, not the
      workspace sha-pinned effective config). PR 1 sidesteps it for
      decision state (commit-time semantics, §3.3); the underlying
      dual-source design remains a policy-study input for PR 4a.
- [ ] FU-P1-5 — manifest `best_score`/`raw_best_score` duplicate alias
      cleanup (`run_one_iteration.py:353-354`).
- [x] FU-P1-8 — LANDED with the standing-rule commit
      (`docs/gates/gate_testing_standard.md` +
      `docs/running_chain_test.md` + `CLAUDE.md` + `AGENTS.md`,
      operator rule 2026-07-27): new "Partial-scope rules" section
      in the Gate standard establishes the two DS8 rules
      (`--data_scope`+`--health_gate_files` pairing; cold-start /
      no `--seed_paths`) surfaced by P1-V2 attempts 1 and 2. Lite +
      Regular plan tables gained HealthGate-files and cold-start
      rows. The pre-DS8 canonical seed section is retained as
      historical reference only, with an operator rule at the top
      forbidding it in new tests. Standing rule mirrored into
      CLAUDE.md / AGENTS.md Coding Standards so all future agents
      see it. **Root cause** of the doc gap: the Lite/Regular plans
      were added (`b38edcc`, 2026-07-23) on the same day DS8 shipped
      (`66df442`, 2026-07-23) but from a different work stream
      (runtime-control audit); the V18r launcher worked around both
      rules at the launcher level, but the standard was never
      retroactively updated. The V18r cohort was terminated by
      container replacement two days later (2026-07-25), so no
      fresh partial-scope Gate 2 hit the rules until P1-V2. Fully
      closed by the current standing-rule commit.

## 10. Open questions

All rev-1 open questions were RESOLVED by operator review:

1. ~~Flag name~~ → `enable_chain_incumbent_formal_gates` (rev 2;
   unless code audit during P1-C3 exposes a naming conflict, to be
   reported at the commit checkpoint).
2. ~~P1-C5 keep-or-defer~~ → rev 2 pre-deferred; **rev 3 REVERSED by
   operator decision: restored as required secondary commit** with the
   strengthened determinism contract (§3.7).
3. ~~Gate 2 scope~~ → standalone smallest canonical configuration; no
   V18r piggyback; both incumbent branches covered deterministically
   in pseudo so the gate is outcome-agnostic (rev 2).

**P1-D APPROVAL RECORD (operator, 2026-07-27)**: rev 3 approved in
substance after two consistency corrections (affected-locations
wording and P1-C3 test wording aligned to the two-state variable
design). Operator decisions recorded:

4. ~~Score-agreement tolerance~~ → CONFIRMED:
   `abs(a-b) <= 1e-9 * max(1, abs(a))` (§3.3).
5. ~~Diagnostic recovery mode~~ → CONFIRMED NOT implemented in PR 1: a
   hash mismatch stops the chain and requires explicit operator
   resolution (§3.6).
6. P1-C5 CONFIRMED as a required secondary commit in this PR.

This design doc is LOCKED for implementation: no further expansion or
polish unless implementation-time code inspection reveals a concrete
conflict (which is stopped-and-reported per §0).
