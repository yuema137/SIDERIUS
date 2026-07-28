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
[ ] P1-C2 — incumbent reconstruction in core/resume.py (RestoredState;
            commit-time validity; artifact-hash verification)
[ ] P1-C3 — threading: subprocess → workflow → protocol → tuner input
            (+ enable_chain_incumbent_formal_gates flag, default OFF;
            manifest artifact hash + chain_incumbent_used stamps)
[ ] P1-C4 — trial incumbent persisted fields (read-only bookkeeping)
[ ] P1-C5 — per-file best table (SECONDARY but REQUIRED, isolated
            commit; strengthened determinism contract §3.7)
[ ] P1-V1 — pre-gate sweep: targeted unit + pseudo integration
            (BOTH incumbent branches deterministic)
[ ] P1-V2 — Gate 2: standalone smallest canonical smoke (real LLM +
            real training, flag ON) — REQUIRES OPERATOR APPROVAL
[ ] P1-S  — stop-and-show; PR merged (coupling flag still OFF)
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

- [ ] five-site threading per §3.4; post-hoc mutation
      `model_exploration.py:2462-2463` removed
- [ ] `enable_chain_incumbent_formal_gates` flag: schema field + tuner
      CLI + `run_one_iteration.py` + `_chain_common.sh` +
      `run_comparison.py`, default OFF; OFF passes `None` to the gates
      while reconstruction/provenance/persistence run UNCONDITIONALLY
- [ ] manifest gains `run_output_sha256` (P1-C2 write side lands
      here with `write_manifest`) plus the consumed-incumbent stamps
      `chain_incumbent_used` (float | null) and
      `chain_incumbent_source` (full provenance dict incl.
      `artifact_verified`); these keys are DISTINCT from every
      iteration-local `best_*` field (Invariant II)
- [ ] rewrite `test_trial_only_iter_does_not_poison_formal_anchor`
      (`tests/unit/workflows/test_model_exploration.py:674-714`) to
      assert the INTENT: trial-only iter → next iter's formal
      incumbent is `None` (not `0.0`)

**Tests**:

- [ ] protocol unit
      (`tests/unit/agent/protocols/test_ml_model_valid_to_ml_model_tune.py`):
      named parameter threads; omitted → `None`
- [ ] workflow unit: restored incumbent initializes
      `chain_formal_incumbent_reference` only; `best_score_overall`
      remains derived solely from the current workflow execution's own
      formal results (formal-only update rule preserved; trial score
      never promotes)
- [ ] **three-iteration separation test (Invariant II, operator-
      specified)**: iter 1 commits a valid formal → iter 2 has NO
      valid formal of its own but consumes iter 1's score as chain
      reference → assert (a) iter 2's manifest
      `best_valid_formal_score` is `None`, (b) iter 2's
      `chain_incumbent_used` equals iter 1's score with
      `chain_incumbent_source.iter_idx == 1` → iter 3's restored
      incumbent still attributes provenance to iter 1 (not iter 2)
- [ ] equivalence: in-process `run_workflow(max_iterations=2)`
      incumbent sequence == two chained single-iteration runs over the
      same workspace
- [ ] flag OFF → gates see `None` even with a restored incumbent
      (rollback semantics) while `chain_incumbent_used` is still
      stamped; flag ON → gates see the restored value
- [ ] `--auto_resume` restart mid-chain reconstructs the same
      incumbent (resume determinism)

**Verification checklist**:

- [ ] `.venv/bin/python -m pytest tests/unit/workflows tests/unit/agent/protocols tests/unit/sdsc_submission_scripts -q` green (counts + wall)
- [ ] ruff + pyright clean

**Test gate**: unit + pseudo integration (P1-V1 covers the chain-level
pseudo run).

---

### P1-C4 — trial incumbent persisted fields (read-only)

**Goal**: `best_valid_trial_*` exists in output + manifest; restored
trial incumbent available on `RestoredState`; nothing consumes it.

**Code**:

- [ ] output selection + serialization beside `:3915-3917`; schema
      fields; manifest mirror; pseudo-data mirrors
- [ ] docstring note: bookkeeping notion ≠ `_best_trial_winner` gate
      predicate (`time_mode` requirement)

**Tests**:

- [ ] trial best selected from valid trial records only; `None` when
      none; formal records never counted
- [ ] manifest round-trip; legacy manifest without the field → `None`

**Verification checklist**:

- [ ] targeted suites green (counts + wall); ruff + pyright clean

**Test gate**: unit only.

---

### P1-C5 — per-file best table (SECONDARY, required, isolated)

**Goal**: §3.7 under the rev-3 determinism contract. Own commit;
touches no decision logic; scope-expansion rule per §0.

**Code**:

- [ ] incremental materialization at iteration commit (atomic write,
      canonical serialization, committed-provenance timestamps)
- [ ] `scripts/rebuild_per_file_best.py` (hash-checked sources,
      backfill mode, `unverified_sources` header count)
- [ ] linear→log conversion + skip counting; formal `eval_portion`
      sourcing rule; raw/valid row separation with record-level
      commit-time validity semantics; metric/transform header
      (`metric_id`, `score_transform`, `log_base`)

**Tests**:

- [ ] rebuild == incremental (BYTE-identical under the canonical
      serialization contract) on a synthetic two-iteration workspace
- [ ] canonical ordering stable under permuted input discovery order
- [ ] atomicity: interrupted write leaves the previous table intact
      (temp+replace verified)
- [ ] timestamps derive from record provenance (two runs at different
      wall-clock times → identical bytes)
- [ ] linear→log conversion correct incl. `-inf`/non-positive skip
      counting
- [ ] phantom record appears ONLY in raw rows, never valid rows;
      `valid` rows use record-level commit-time validity (a record
      with per-file gate variance still classifies at record level)
- [ ] tampered / hash-mismatched `run_output` → rebuild refuses the
      input (error names the artifact); incremental path unreachable
      by construction (§3.6 already stopped the chain)
- [ ] offline real-workspace backfill smoke on a copied V17 iteration
      directory (no GPU/LLM; legacy no-hash sources admitted and
      counted in `unverified_sources`)

**Verification checklist**:

- [ ] targeted suites green (counts + wall); ruff + pyright clean

**Test gate**: unit only.

---

## 7. Validation plan

### P1-V1 — pre-gate sweep (no approval needed)

- [ ] Targeted unit suites listed per commit (NOT the full suite;
      per operator testing policy)
- [ ] Pseudo integration (`tests/integration/workflows/`, dual-mode
      default), **BOTH incumbent branches deterministic** (rev 2 —
      Gate 2 must not depend on a stochastic score outcome):
      - [ ] Branch A (numeric incumbent): iter 1 pseudo data contains
            a valid formal → iter 2's tuner input carries it; banner
            `reference=<value>`; manifest `chain_incumbent_used` +
            `chain_incumbent_source` correct; local
            `best_valid_formal_score` untouched (Invariant II)
      - [ ] Branch B (no incumbent): iter 1 pseudo data has no valid
            formal → iter 2 banner `reference=none`;
            `chain_incumbent_used=null`; gates short-circuit
      - [ ] flag OFF variant: reconstruction + stamps still present,
            gates inert
- [ ] `ruff check` + `ruff format --check` + pyright, full tree

### P1-V2 — Gate 2: standalone smallest canonical smoke — **REQUIRES OPERATOR APPROVAL**

**Operator decision (rev 2): standalone smallest canonical Gate 2
configuration from `docs/gates/gate_testing_standard.md` — NOT a
V18r-adjacent piggyback.** 2 chained iterations, real LLM + real
training, `enable_chain_incumbent_formal_gates` ON. Because BOTH
incumbent branches are already deterministically covered in P1-V1
pseudo, Gate 2 validates **end-to-end artifact consistency and
no-regression for whichever branch the real run produces** — it does
not need to force a particular stochastic score outcome.

- [ ] Pass criterion 1: iter 2 startup banner `reference=…` agrees
      exactly with iter 1's manifest state (numeric value or `none`;
      verbatim quote of the banner line + the manifest
      `chain_incumbent_used`/`chain_incumbent_source` JSON —
      anti-hallucination)
- [ ] Pass criterion 2: `[resume] incumbent carry-over:` line matches
      the iter-1 manifest value exactly, incl. `basis=` and
      `verified=true` (hash present and matching)
- [ ] Pass criterion 3: iter 2's own `best_valid_formal_score` in its
      manifest reflects only iter 2's rounds (Invariant II, verbatim
      JSON)
- [ ] Pass criterion 4: no crash/regression in the standard smoke pass
      criteria of the gate standard
- [ ] Budget estimate (filled before launch per baseline §4.4):
      expected wall ≈ 2 × (one smallest-canonical iteration); LLM
      calls ≈ 2 iterations × per-iteration profile; GPU bounded by
      trial+formal budgets; hard upper bound and stop condition stated
      at launch request
- [ ] Gate 2 result recorded here: __

### Validation budget table (baseline §4.4 — estimates filled at P1-D approval)

```text
layer                | scenarios | samples | LLM calls | training runs | wall | GPU | API cost | hard cap | approval
unit (P1-C1..C5)     | n/a       | n/a     | 0         | 0             | ~min | 0   | 0        | n/a      | none
pseudo chain (P1-V1) | 3 (A/B/off)| 1      | 0         | 0 (stub)      | ~min | 0   | 0        | n/a      | none
backfill smoke (C5)  | 1         | 1       | 0         | 0 (offline)   | ~min | 0   | 0        | n/a      | none
Gate 2 (P1-V2)       | 1         | 1       | ~2 iters  | ~4-6 rounds   | TBD  | TBD | TBD      | TBD      | OPERATOR
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
