# V19 Priority Decisions

- **Status**: forward-planning draft; not yet scheduled
- **Scope**: workflow-adaptation release — the feedback/adaptation agenda
  originally drafted for V18 (carried over after V18 pivoted to the
  split-mode + runtime-control release), plus runtime-control follow-ups
  from the V18r campaign
- **Owner**: TBD
- **Prerequisites**: V18r split-mode campaign completed (Waves 1–2);
  runtime-control observation stores populated with production data
- **Related**: [`v18_priorities.md`](./v18_priorities.md) (what actually
  shipped in V18 and why these items moved),
  [`runtime_estimation_and_watchdog.md`](./runtime_estimation_and_watchdog.md),
  GitHub issue #136
- **Frozen protocol note (operator, 2026-07-24)**: none of this changes
  mid-V18r — the running campaign finishes under its committed protocol.

## 1. Goal

V17 built the health-observation substrate. V18 was planned to make it
actionable, but pivoted to split-mode exploration + calibrated runtime
control after the Wave-1 runtime incident. V19 answers the deferred
question: **"Can SIDERIUS use structured health and runtime information
to adapt its future proposals and workflow decisions?"**

## 2. Carried-over capability groups (from the V18 draft)

### 2.1 Feedback propagation — REMAINDER

Landed in V18: condensed health-validity propagation
(`best_raw_health_validity`, `per_model_raw_best_health_validity`,
HealthGate-valid candidate selection — PR #124).

Remaining:

- **Per-round structured gate fields in `ModelRunSummary`** — per-round
  `is_degenerate`, `failure_reason`, `gate_action`, counterfactual
  production-verdict fields; protocol update in
  `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py` (today
  the protocol carries no gate fields).
- **Interpreter prompt template** — surface the structured collapse
  fields; drop text-only interpretations.
- **Proposer prompt template** — explicit collapse-fingerprint avoidance
  from the propagated fields.

Dependencies: none. Blocks: 2.2 (fingerprints), 2.5 (cross-iteration flow).

### 2.2 Adaptation

Unchanged from the V18 draft — none of it landed (V18r still runs the
frozen observe-mode policy):

- **Threshold study** — now with V17 campaign + legacy-V18 + V18r
  evidence: do `min_unique_int8_values=25`, `min_std_mv=1.0`,
  `collapse_threshold=0.95` hold per-architecture? Escalates
  `production_disposition: undetermined` → concrete values.
- **Aggregation-policy search** — `any_pass` vs `all_pass` vs numeric,
  against real campaign data.
- **Adaptive routing** — blocking-style checks route to
  `invalidate_round` / `skip_to_formal` once evidence supports the
  threshold.
- **Cross-iteration collapse-fingerprint avoidance** — proposer seeded
  with prior rounds' fingerprints.

Dependencies: 2.1. V18r produces additional evidence (e.g. the observed
20-unique-int8 near-threshold cases on files 4-9).

### 2.3 Independent stateful stop policies

Carried verbatim from the V18 draft (nothing landed; the `gate-exhaustion`
surfacing that exists today is not the typed circuit breaker):

An optional, tuner-scoped circuit breaker evaluates persisted
completed-round observations without changing scorer mathematics or
per-gate routing:

```text
score validity → HealthGate observation → round-health classification
  → independent tuner stop policies → routing decision
```

Candidate policies: repeated model collapse, repeated invalid score —
independent consecutive-round counters, OR aggregation, every blocking
policy recorded. Scorer stays stateless; only the policy layer may
resolve `stop_remaining_rounds`. Streaks are tuner-local (never spanning
workflow iterations, models, or chains); baselines and failed attempts
do not seed counters.

Implementation goals: typed `ScoreValidityResult` (independent of
HealthGate); typed `RoundHealthClassification`
(`healthy`/`collapsed`/`indeterminate`); tuner-level stop-policy
evaluator; OR-aggregated typed routing results; deterministic
reconstruction from persisted history; policy-result persistence and
audit metadata; a successful `completed_early` terminal state
(new tuner/wrapper/resume/monitoring contracts, without weakening
PR #121's partial-campaign protection); default-disabled operational
circuit breaker enabled only after campaign policy review.

### 2.4 Chain-wide best valid formal incumbent  *(tracked: issue #136)*

Confirmed still-live in V18r production (2026-07-24): the formal-gate
reference `current_run_best_formal_score` is fixed at 0.0 every
iteration because the per-iteration subprocess boundary discards
`best_score_overall` (`RestoredState` restores plugins/vocab/proposal
but not the best score).

Replace the fixed `0.0` with committed, chain-local state:

```text
chain_best_valid_formal_score: float | None
chain_best_valid_formal_record: provenance | None
```

Only formal, HealthGate-valid results eligible. Loss and architecture
chains keep independent incumbents. **Scope-keyed (DS8 note
2026-07-23): aggregate scalars are only comparable within one resolved
`data_scope` — key the committed state by resolved scope / the
run-invariants lock identity.** Reconstructed from committed
prior-iteration manifests (`best_valid_formal_score` is already
persisted there), frozen at iteration start, updated only after a
successful iteration commit, active next iteration. The design must
specify: no-incumbent initialization, partial-campaign eligibility,
legacy records with missing HealthGate metadata, stable tie-breaking,
interrupted iterations, duplicate/replayed artifacts, `--auto_resume`,
equivalence with in-process `run_workflow(max_iterations>1)`, and an
explicit deterministic migration from the fixed `0.0` reference.
Design decision to make deliberately: a rising incumbent bar saves
formal budget but reduces formal sampling
(`skip_formal_min_delta` / `bypass_formal_time_budget_min_delta`
measure against it).

### 2.5 Workflow evolution

Unchanged from the V18 draft: bidirectional cross-iteration information
flow (beyond the vocab/previous-proposal restoration that exists);
iteration-level meta-planner; Run Monitor agent; modular orchestration
(multi-week rework).

### 2.6 Metric refinement — REMAINDER

Landed in V18 (modified form): the correlation guard shipped as the
`pearson_dispersion_recording` HealthGate check (M8 §3.4 — dispersion of
per-file pearson, at the gate layer, recording-only), NOT as a
`score_vector`-internal gate.

Remaining: decide whether an in-`score_vector` integrity gate adds
signal beyond the HealthGate check (now answerable with campaign data);
collapse-resistant score formula variants (governance decision —
paper-comparability).

### 2.7 Deferred forensic backlog

- **v15 iter-4/R4 outlier** — the `final_loss=5.03` untrained run that
  produced a 5.5763 phantom. The class-127 fingerprint mechanism is now
  fully documented (`pluggable_health_checks.md` §7.1); the specific
  historical revisit with modern diagnostics has not been done.

### 2.8 Reclassified DEFER-tier items (carried table)

| Item | Prior | V19 disposition |
|------|-------|-----------------|
| Run Monitor agent | D1 | Under 2.5 workflow evolution |
| Bidirectional cross-iteration flow | D2 | Under 2.5 |
| Collapse-resistant score redesign | D3 | Under 2.6 |
| Multi-condition stop gates | D4 | Refined into 2.3 |
| Modular agent orchestration | D5 | Under 2.5 |
| ModelConfig typed Pydantic | D6 | Tech-debt; not V19-blocking |
| Info-source weighting | D7 | Follows 2.2 |

## 3. New runtime-control follow-ups (from the V18r campaign, 2026-07-24)

*(also in issue #136)*

1. **Adaptive runtime margins / drift root-cause** — Wave 1A measured a
   systematic ~1.55–1.6× post-verification slowdown, uniform across a
   50× parameter range (design doc §12 Wave-1A entry; fixed
   operationally by the trial 2.0 / formal 1.5 split, `43212fe`).
   V19: record GPU clocks/utilization in observation provenance to
   separate sustained-load clock decay from neighbor contention;
   consider periodic re-verification or error-ledger-driven per-phase
   safety factors instead of fixed operator constants.
2. **Launcher single-chain selector** — `launch_v18_wave1.sh {1a|1b}`
   cannot restart one chain of a pair (the Wave-1A loss restart needed a
   hand-mirrored `run_chain.sh` command). Add `--only <run_name>`.

## 4. Sequencing hypothesis

Not committed — starting point once V18r data is in hand:

1. Feedback propagation remainder (2.1) — smallest surface, unblocks 2.2/2.5
2. Chain-wide incumbent (2.4) — contained, high operational value, issue #136
3. Metric refinement remainder (2.6) — parallel; independent
4. Adaptation (2.2) — needs 2.1 + campaign data
5. Runtime-control follow-ups (§3) — parallel; provenance first
6. Independent stop policies (2.3) — after completion/resume design
7. Workflow evolution (2.5) — largest surface, last
8. Forensic backlog (2.7) — throughout

## 5. Related docs

- [`v18_priorities.md`](./v18_priorities.md) — the original draft and
  V18's actual delivery record
- [`v17_priorities.md`](./v17_priorities.md) — the substrate
- [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md)
  — the frozen policy 2.2 reevaluates
- [`runtime_estimation_and_watchdog.md`](./runtime_estimation_and_watchdog.md)
  — runtime-control design (§12 Wave-1A evidence)
- [`collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md),
  [`pluggable_health_checks.md`](./pluggable_health_checks.md)
