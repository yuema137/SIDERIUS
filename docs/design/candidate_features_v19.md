# V19 Candidate Features

**Status**: unscheduled candidates. Created 2026-07-28 by operator
decision narrowing the required V19 scope to PR 1-3.

**"V19" in this title identifies the planning context in which these
ideas were collected — it is NOT a commitment to implement them during
V19.**

> **Candidate status does not imply planned implementation in V19, V20,
> or any specific future release. A candidate is promoted into a release
> only after an explicit operator decision based on demonstrated need,
> expected value, dependencies, and validation cost.**

These are useful ideas with real reasoning behind them. They were moved
here because they are **not required to address the currently
demonstrated blockers**, which are covered by the required V19 ladder
(`v19_priorities.md`):

- the workflow forgot prior best results → **PR 1**
- ordering was unavailable as a search variable → **PR 2**
- structured failure evidence did not reliably reach downstream agents
  → **PR 3**

Nothing here is deferred "to V20". Nothing here is scheduled at all.

## Where each candidate came from

| Former label | Candidate | Topic |
|---|---|---|
| PR 4a | **Candidate A** | Threshold and aggregation study |
| PR 4b | **Candidate B** | Adaptive routing and collapse-fingerprint avoidance |
| PR 5 | **Candidate C** | Metric integrity and score-variant analysis |
| PR 6 | **Candidate D** | Stateful stop policies |
| PR 7+ | **Candidate E** (epic) | Larger workflow evolution |

The former `PR 4a/4b/5/6/7+` labels are retired. They implied a
scheduled position in a ladder; these items have none.

## Promotion criteria

A candidate may be promoted into a named release only when:

- [ ] A concrete observed problem is documented
- [ ] Existing V19 functionality is shown to be insufficient
- [ ] Expected benefit is tied to score, valid-round rate, reliability,
      or meaningful resource savings
- [ ] Scope and dependencies are audited
- [ ] Validation requirements are defined
- [ ] Expected runtime, GPU usage, and API cost are estimated
- [ ] The operator explicitly approves promotion into a named release

Release numbers are **not** assigned automatically. Promotion is an
explicit operator decision with a documented revision.

## Progress semantics

**Checkboxes in this document record investigation and readiness only.
An unchecked or partially investigated candidate does not block V19
completion.** Where work has already occurred, the evidence is preserved
accurately below — but a candidate is never marked implemented merely
because the idea has been described.

## Validation discipline (unchanged by the move)

Moving an item here does **not** weaken its future validation
requirements. The canonical standard remains `v19_priorities.md` §4:

- deterministic functionality needs exact tests;
- agent-behavior claims require repeated real-LLM synthetic evaluation
  (§4.2 Layer 2);
- agent-behavior claims also require a bounded real-LLM + real-training
  confirmation (§4.2 Layer 3);
- time, GPU-time, and API cost must be estimated before launch (§4.4);
- merge and production activation remain separate decisions (§4.5).

---

## Candidate A — Threshold and aggregation study

*(formerly PR 4a)*

- Must produce a **versioned policy proposal with evidence and
  uncertainty**, not exploratory plots. No LLM-behavior claim is
  necessary unless LLM interpretation is part of the analysis.
- Required outputs: empirical gate distributions;
  architecture-family dependence; threshold candidates; aggregation
  comparison (`any_pass`/`all_pass`/numeric); false-positive/
  false-negative (or equivalent) tradeoffs; impact on retention of
  valid formal rounds; a disposition for every gate — activate,
  remain recording-only, or insufficient evidence.

##### PR 4a progress checkpoints

- [ ] Campaign datasets and eligibility rules frozen
- [ ] Gate distributions computed
- [ ] Architecture-family dependence analyzed
- [ ] Threshold candidates evaluated
- [ ] `any_pass`, `all_pass`, and numeric aggregation compared
- [ ] False-positive and false-negative tradeoffs estimated
- [ ] Valid-formal retention impact estimated
- [ ] Missing or insufficient evidence identified
- [ ] Every gate assigned a preliminary disposition
- [ ] Versioned policy proposal written
- [ ] Uncertainty and limitations reported
- [ ] Policy proposal reviewed
- [ ] No behavior change confirmed

**Why this is not required now.** There is not yet sufficient
evidence that threshold recalibration is the next strongest constraint
on score. The current thresholds have not been shown to systematically
reject useful models or accept harmful ones.

**What would justify promotion.** Evidence that current thresholds
systematically reject useful models, or admit harmful ones, in a way
that measurably costs valid-formal retention.

**Source material preserved**: `v19_priorities.md` §2.2 (adaptation),
`docs/design/v17_pregate_threshold_review.md`, and the HealthGate design
`docs/design/pluggable_health_checks.md`.

---

## Candidate B — Adaptive routing and collapse-fingerprint avoidance

*(formerly PR 4b)*

- Deterministic routing logic: exact tests (action resolution,
  severity, persistence).
- Collapse-fingerprint avoidance and proposer adaptation: true-LLM
  pseudo (§4.2 L2) and bounded true-training (§4.2 L3) validation.
- Activation is a separate operator decision with rollback to
  observe-only.

##### PR 4b progress checkpoints

*Deterministic routing*

- [ ] PR 4a policy version selected
- [ ] Routing schema approved
- [ ] Action-resolution tests passed
- [ ] Severity and aggregation tests passed
- [ ] Persistence and resume tests passed
- [ ] Observe-only rollback verified

*Agent behavior*

- [ ] Fingerprint-avoidance behavioral contract defined
- [ ] Relevant synthetic scenario subset selected
- [ ] Layer-2 control/treatment evaluation completed
- [ ] Repeated sampling and uncertainty reported
- [ ] Layer-3 real-training validation approved
- [ ] Layer-3 validation completed
- [ ] Unintended over-avoidance evaluated

*Activation*

- [ ] Merge approved
- [ ] PR merged with behavior disabled or recording-only, if appropriate
- [ ] Production activation separately approved
- [ ] Post-activation routing outcomes reviewed
- [ ] Rollback readiness confirmed

**Why this is not required now.** PR 3 must first establish that
structured feedback is correctly delivered and measurably used. Routing
on gate results is only worth building once passive feedback has been
shown to be insufficient.

**What would justify promotion.** Evidence that passive feedback alone
does not change behavior, AND that automatic routing is likely to
improve valid-round rate or resource use.

**Dependency**: PR 3 (required V19 scope). This dependency is recorded
here rather than in the required ladder — **PR 3 does not block a
required PR 4**, because no required PR 4 exists.

---

## Candidate C — Metric integrity and score-variant analysis

*(formerly PR 5)*

**PR 5 — Metric integrity & score-variant analysis (analysis/policy,
parallel, non-blocking)**

- Runs beside the ladder; escalates only on discovery of a critical
  metric flaw that HealthGate cannot mitigate.
- Validation focuses on offline metric integrity, HealthGate overlap,
  and score comparability; no agent-behavior testing unless the metric
  is surfaced to agents and a behavioral claim is made.

##### PR 5 progress checkpoints

- [ ] Existing metric and HealthGate overlap audited
- [ ] Collapse and phantom families included in the analysis
- [ ] Canonical metric byte-identity confirmed
- [ ] Integrity-gate incremental value evaluated
- [ ] Score-variant candidates defined, if justified
- [ ] Paper comparability impact analyzed
- [ ] Offline experiments completed
- [ ] Governance recommendation written
- [ ] Critical flaw escalation decision made
- [ ] Main V19 ladder remains unblocked unless a critical flaw is confirmed

**Why this is not required now.** Non-blocking unless analysis
identifies a critical flaw that HealthGate cannot mitigate.

**Explicit non-goal.** Nothing here implies V19 intends to replace the
canonical TIDMAD score. The frozen score formula stays byte-identical
for paper comparability (`docs/design/genericity_contract.md` Seam 4);
any new metric plugs in BESIDE it.

**Related open issue**: #138 (reference artifacts vs current formula —
a concrete integrity question already filed).

---

## Candidate D — Stateful stop policies

*(formerly PR 6)*

- Counters, reconstruction, terminal states, resume: deterministic
  exact tests (incl. deterministic reconstruction from persisted
  history).
- Any claim that planner behavior improves because of the surfaced
  stop reason is agent-behavior and triggers §4.2/§4.3 — otherwise do
  not make the claim.

##### PR 6 progress checkpoints

- [ ] Stop-policy state model approved
- [ ] `ScoreValidityResult` implemented
- [ ] `RoundHealthClassification` implemented
- [ ] Independent counters implemented
- [ ] OR aggregation implemented
- [ ] Persisted-history reconstruction implemented
- [ ] Resume and replay tests passed
- [ ] `completed_early` terminal-state contracts implemented
- [ ] Monitoring and wrapper compatibility verified
- [ ] Default-disabled behavior verified
- [ ] Synthetic deterministic stop scenarios passed
- [ ] Agent-behavior validation completed only if planner-improvement claims are made
- [ ] Activation policy reviewed
- [ ] PR merged
- [ ] Production activation separately approved

**Why this is not required now.** Early stopping is a
resource-efficiency improvement. It has not been demonstrated as
necessary for reaching the V19 score target.

**What would justify promotion.** Evidence that repeated hopeless rounds
consume enough budget to justify the added state and routing
complexity.

---

## Candidate epic — Larger workflow evolution

*(formerly PR 7+)*

**This is a long-term candidate AREA, not one planned PR.** It must be
decomposed into concrete, individually-justified pieces before any part
of it can be promoted.

- Every behavioral claim requires its OWN explicit §4.3 evaluation
  contract, controls, repeated sampling, and bounded Gate-style
  real-system validation. One broad epic-level demonstration must not
  be allowed to validate multiple unrelated claims — no epic-level
  exit without per-claim evidence.

##### PR 7+ epic checkpoints

(no single checklist for the whole epic — each sub-PR uses the
standard agent-behavior checklist)

- [ ] Epic decomposed into independent behavioral claims
- [ ] Each claim assigned its own PR/design document
- [ ] Each claim has a separate evaluation contract
- [ ] Shared infrastructure separated from behavior-changing logic
- [ ] Merge and activation boundaries defined per sub-PR
- [ ] No epic-level behavioral claim accepted from one broad demo

**Why this is not required now.** Nothing in this area addresses a
currently demonstrated blocker, and its scope is too large to evaluate
as a single unit.

**Promotion requires decomposition first.** A single "workflow
evolution" promotion decision is not possible; each sub-piece needs its
own observed problem, expected benefit, and validation plan.

---

## Source capability groups (preserved verbatim from v19_priorities.md §2)

These are the original capability-group entries that fed the
candidates above. They are kept here so the underlying reasoning,
evidence, and non-goals are not lost from the move.

### 2.2 Adaptation  *(→ PR 4a study / PR 4b activation)*

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

### 2.3 Independent stateful stop policies  *(→ PR 6)*

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


### 2.5 Workflow evolution  *(→ PR 7+ — multi-PR epic, last)*

Unchanged from the V18 draft: bidirectional cross-iteration information
flow (beyond the vocab/previous-proposal restoration that exists);
iteration-level meta-planner; Run Monitor agent; modular orchestration
(multi-week rework).

### 2.6 Metric refinement — REMAINDER  *(→ PR 5 — parallel, non-blocking research track)*

Landed in V18 (modified form): the correlation guard shipped as the
`pearson_dispersion_recording` HealthGate check (M8 §3.4 — dispersion of
per-file pearson, at the gate layer, recording-only), NOT as a
`score_vector`-internal gate.

Remaining: decide whether an in-`score_vector` integrity gate adds
signal beyond the HealthGate check (now answerable with campaign data);
collapse-resistant score formula variants (governance decision —
paper-comparability).

