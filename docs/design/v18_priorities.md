# V18 Priority Decisions

- **Status**: forward-planning draft; not yet scheduled
- **Scope**: workflow-adaptation release — turning V17 observation data into structured feedback and future proposal decisions
- **Owner**: TBD
- **Prerequisites**: V17 landed and observation campaign completed for FCNet, WaveNet, PUNet
- **Related**: [`v17_priorities.md`](./v17_priorities.md), [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md)

## 1. Goal

V17 asks: "Can SIDERIUS consistently detect, record, and compare model-health behavior under one shared gate policy without interrupting exploration?"

V18 answers: **"Can SIDERIUS use that structured health information to adapt its future proposals and workflow decisions?"**

V17 built the observation substrate. V18 makes it actionable.

## 2. Prerequisites

Before V18 kickoff:

1. V17 observation infrastructure and final production launch plumbing landed on master.
2. V17 workflow exploration completed with valid typed observation records;
   the retained FCNet, PUNet, and WaveNet pre-gate diagnostics remain reference
   evidence rather than substitutes for this campaign.
3. Post-campaign analysis available — enough data to reclassify some post-V17 items with evidence rather than speculation.
4. Threshold disposition finalized — the campaign's `production_disposition: undetermined` becomes an actual production decision.

## 3. Capability groups

Each group is a coherent slice of workflow change. Sequencing between groups is a hypothesis (§4) rather than a hard order.

### 3.1 Feedback propagation

**Capability**: collapse signals recorded by V17 flow from the tuner boundary into `ModelRunSummary`, interpreter schemas, and downstream agent protocols. Interpreter and proposer prompts consume the structured signal rather than free-text reasoning about it.

Concrete work:

- **`ModelRunSummary` schema extension** — per-round `is_degenerate`, `failure_reason`, `gate_action`, plus the counterfactual production verdict fields already persisted at the tuner side. Protocol update in `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py`.
- **Interpreter prompt template** — surface the structured collapse fields; drop text-only interpretations.
- **Proposer prompt template** — instruct explicit collapse-fingerprint avoidance using the fields propagated through `ModelRunSummary`.

Dependencies: nothing on V17 code. Blocks: 3.4 (cross-iteration flow uses the same fields).

### 3.2 Adaptation

**Capability**: gate thresholds, aggregation policy, and file-selection are informed by V17 observation data rather than frozen defaults. Cross-iteration feedback lets the proposer learn from prior rounds' collapse fingerprints.

Concrete work:

- **Threshold study** — use V17 campaign records to answer whether the currently-frozen thresholds (`min_unique_int8_values=25`, `min_std_mv=1.0`, `collapse_threshold=0.95`) hold across FCNet / WaveNet / PUNet or need per-architecture tuning. Escalates `production_disposition: undetermined` → concrete values.
- **Aggregation-policy search** — evaluate `any_pass` vs `all_pass` vs numeric aggregations against real campaign data.
- **Adaptive routing** — allow blocking-style checks to route to `invalidate_round` (or `skip_to_formal`) after enough evidence supports the threshold. This is where V17's `_blocking` gate IDs regain their name.
- **Cross-iteration collapse-fingerprint avoidance** — the proposer, seeded with fingerprints from prior rounds, avoids proposing configurations that map to known collapse regions.

Dependencies: 3.1 (needs feedback flow to compute fingerprints). Blocked by: V17 campaign data availability.

### 3.3 Independent stateful stop policies

**Capability**: an optional, tuner-scoped circuit breaker evaluates persisted
completed-round observations without changing scorer mathematics or per-gate
routing.

Conceptual separation:

```text
score validity
  ↓
HealthGate observation
  ↓
round-health classification
  ↓
independent tuner stop policies
  ↓
routing decision
```

Candidate policies include repeated model collapse and repeated invalid score.
Each policy owns an independent consecutive-round counter; the routing decision
uses OR aggregation and records every policy that blocks. The scorer remains
stateless, HealthGate continues to report observations and its configured
action, and the policy layer alone may resolve `stop_remaining_rounds`.

The initial policy scope is tuner-local. Streaks must not span workflow
iterations, models, or concurrent chains; baseline observations and failed
attempts do not seed the counter. Trial and formal completed rounds may share a
tuner-local streak only under an explicitly reviewed policy configuration.

This framework was reviewed before V17 and deliberately deferred:

- V17 schedules three rounds per tuner invocation, so a threshold of three
  saves no work inside that invocation.
- Lowering the threshold to two would increase false-stop risk and bias V17's
  measurement of whether later proposals recover from collapse by censoring
  those recovery observations.
- A successful `completed_early` state requires new tuner, wrapper, resume, and
  monitoring contracts without weakening PR #121's protection against genuine
  partial campaigns.
- V17's purpose is unified observation, not adaptive or stateful routing.

Future implementation goals:

- typed `ScoreValidityResult` independent of HealthGate;
- typed `RoundHealthClassification` (`healthy`, `collapsed`, `indeterminate`);
- a tuner-level stop-policy evaluator with independent collapse and
  invalid-score policies;
- OR-aggregated typed routing results;
- deterministic reconstruction from persisted completed-round history;
- policy-result persistence and audit metadata;
- a successful `completed_early` terminal state; and
- a default-disabled operational circuit breaker enabled only after campaign
  policy review.

Dependencies: V17 observation data and explicit completion/resume contract
design. Independent of the existing Option C custom-loss workflow.

### 3.4 Chain-wide best valid formal incumbent

V18 will replace V17's fixed `0.0` comparison reference with committed,
chain-local state:

```text
chain_best_valid_formal_score: float | None
chain_best_valid_formal_record: provenance | None
```

Only formal, HealthGate-valid results are eligible. Loss and architecture
chains maintain independent incumbents. **The incumbent must be scope-keyed
(DataScope, DS8 note 2026-07-23): aggregate scalars are only comparable
within one resolved `data_scope`, so an incumbent recorded under scope A
must never serve as the comparison reference for a chain running scope B —
key the committed state by the resolved scope (or equivalently by the
run-invariants lock identity).** The incumbent is reconstructed from
committed prior-iteration manifests and tuner outputs, frozen at iteration
start, and updated only after a successful iteration commit; the new value
becomes active in the next iteration. Raw scores remain separately preserved.

The design must specify no-incumbent initialization, partial-campaign
eligibility, legacy records with missing HealthGate metadata, stable
tie-breaking, interrupted iterations, duplicate/replayed artifacts,
`--auto_resume`, and equivalence with in-process
`run_workflow(max_iterations>1)`. Uncommitted outputs are ignored. Migration
from V17's fixed `0.0` reference must be explicit and deterministic.

Delta thresholds (`skip_formal_min_delta` and
`bypass_formal_time_budget_min_delta`) will be evaluated against this restored
incumbent only after commit-boundary activation.

### 3.5 Workflow evolution

**Capability**: broader workflow changes that were deferred out of V17 because they touch agent contracts or long-lived infrastructure.

Concrete work:

- **Bidirectional cross-iteration information flow** — a fuller feedback substrate beyond one-shot `ModelRunSummary` propagation: cross-iteration memory, structured cross-run comparisons, iteration-level meta-planner.
- **Larger orchestration + monitoring architecture** — Run Monitor agent, modular orchestration; likely a multi-week rework.

Dependencies: 3.1 for the feedback substrate; independent of 3.2.

The existing Branch A / live Branch B / Option C custom-loss framework is not
a deferred V18 feature. PR #122 preserved that workflow and removed stale or
unavailable Branch B inventory entries.

### 3.6 Metric refinement

**Capability**: the `denoising_score` computation itself gains additional safeguards or collapse-resistant variants, informed by campaign data.

Concrete work:

- **Correlation-based scoring guard** — `pearson_correlation(denoised, target)` gate inside `score_vector` for post-hoc score integrity, distinct from the diversity-based checks. Empirical basis for whether this adds signal is a V17 campaign question.
- **Collapse-resistant score formula variants** — governance decision (paper-comparability concerns) informed by campaign observations.

Dependencies: V17 campaign data. Blocked by: nothing until data is in hand.

### 3.7 Deferred forensic backlog

**Capability**: revisit historical anomalies with post-V17 tools.

Concrete work:

- **v15 iter-4/R4 outlier** — the `final_loss=5.03` untrained run that produced a 5.5763 phantom. Preserved as a forensic issue. If a similar pattern appears during V17, escalate immediately; if not, revisit with V17 diagnostic infrastructure available.

Dependencies: V17 campaign completion (for occurrence data).

## 4. Reclassified DEFER-tier items

Compact re-classification. Full evaluation post-V17 with observation data in hand.

| Item | Prior classification | V18 disposition | Notes |
|------|---------------------|-----------------|-------|
| Run Monitor agent | D1 | Retained under 3.4 workflow evolution | Umbrella for feedback + adaptation at orchestrator level |
| Bidirectional cross-iteration flow | D2 | Retained under 3.4 workflow evolution | Follows 3.1 |
| Metric redesign — collapse-resistant score | D3 | Retained under 3.5 metric refinement | Requires paper-comparability governance decision |
| Multi-condition stop gates | D4 | Refined into 3.3 independent tuner stop policies | Default-disabled circuit breaker; no scorer or HealthGate routing change |
| Modular agent orchestration | D5 | Retained under 3.4 workflow evolution | Architecture-level; long-tail |
| ModelConfig typed Pydantic | D6 | Tech-debt; not V18-blocking | Independent of feedback/adaptation |
| Info-source weighting | D7 | Follows 3.2 adaptation | Only meaningful after cross-iteration feedback exists |

## 5. Sequencing hypothesis

Not committed — proposed as a starting point once V17 data is in hand:

1. **Feedback propagation (3.1)** — smallest surface change, unblocks the rest
2. **Metric refinement (3.5)** — parallel; independent
3. **Adaptation (3.2)** — needs 3.1 for fingerprints; needs V17 data for thresholds
4. **Independent stop policies (3.3)** — after completion/resume semantics are designed; default disabled
5. **Workflow evolution (3.4)** — larger surface; Run Monitor / orchestration
6. **Forensic backlog (3.6)** — throughout, as evidence accumulates

## 6. Related docs

- [`v17_priorities.md`](./v17_priorities.md) — what V18 builds on
- [`v17_pregate_baseline_launch_plan.md`](./v17_pregate_baseline_launch_plan.md) — the campaign that produces V18's evidence base
- [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md) — the frozen policy V18 will reevaluate
- [`collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md) — framework contract that 3.2 will exercise adaptively
- [`pluggable_health_checks.md`](./pluggable_health_checks.md) — health-check architecture reference
