# V17 Priority Decisions — Revised 2026-07-17

- **Status**: scope frozen; core observation infrastructure complete; final launch plumbing pending
- **Scope**: observation-layer release — HealthGate coverage, typed persistence, score validity, and a unified observation standard for V17 workflow exploration
- **Owner**: SIDERIUS operators
- **Related**: [`v17_pregate_baseline_launch_plan.md`](./v17_pregate_baseline_launch_plan.md), [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md), [`v18_priorities.md`](./v18_priorities.md)

## 1. Goal

Establish one consistent, reasonable, auditable model-health standard for V17
workflow exploration, using the retained all-file pre-gate diagnostics as
reference evidence without treating them as V17 workflow runs or replaying
them as a launch prerequisite.

## 2. Guiding principle — stability over optimality

**V17 intentionally prioritizes a stable and consistent observation standard over optimal collapse detection.** The purpose is to apply one shared HealthGate policy to the unified baselines and the workflow exploration. Threshold optimization, adaptive routing, feedback propagation, and workflow adaptation are deferred to V18.

Consistency between baseline and workflow-exploration runs matters more than theoretical optimality. Anything that would improve the gate's discriminative power at the cost of changing behavior mid-campaign is out of scope.

## 3. What V17 is

An observation layer that:

- Runs every configured HealthGate after the baseline and after every completed tuning round.
- Uses the same YAML config, same thresholds, same file selection (`peek_file_indices: [3, 10, 17]`), same aggregation (`any_pass`), and same score-validity policy (`noise <= 1e-10 → invalid`) for baseline and tuner rounds.
- Routes every successfully executed gate to `continue`, regardless of whether the check passes or fails. Nothing invalidates a round mid-campaign.
- Persists complete typed per-file metrics, aggregate results, recording metrics, execution status, counterfactual production verdict, and resolved observe-mode action for every gate execution.
- Distinguishes four execution states — `passed`, `failed`, `not_run`, `error` — with `not_run` and `error` marked as observability / infrastructure states, not model-collapse verdicts.
- Uses the completed pre-gate diagnostics as evidence, while keeping those diagnostic campaigns distinct from the V17 workflow exploration.
- Retains the existing implemented three-branch loss exploration framework: Branch A built-ins, Branch B currently available reusable plugins, and Branch C / Option C newly generated custom losses.
- Retains the V16 execution topology: concurrent loss-explorer and
  architecture-explorer chains, 20 workflow iterations per chain, and three
  tuner rounds per iteration.
- Persists structured failed attempts in planner history and treats an
  unexpected partial tuner campaign as a non-zero workflow failure.

## 4. What V17 is not

- Not a collapse-detection optimizer. Thresholds are frozen for observation, not proven optimal.
- Not a workflow-adaptation release. Interpreter, proposer, and cross-iteration feedback stay unchanged.
- Not a complete typed HealthGate-feedback release. Gate observations are
  authoritative in persisted records but are not yet a full structured input
  contract for the interpreter and proposer.
- Not a stateful-routing release. Consecutive-collapse/invalid-score circuit breakers and a `completed_early` terminal state were reviewed and intentionally deferred to V18.
- Not a metric redesign. `denoising_score` computation is untouched; only the score-validity guard (`noise <= 1e-10`) is enforced.
- Not a custom-loss redesign. V17 retains the existing
  proposer → implementor → registry → tuner path. PR #122 only prevents stale
  or unavailable Branch B plugins from being advertised or accepted as reusable.
- Not a forensics deep-dive. Past outliers (e.g., the v15 iter-4/R4 anomaly) are preserved as issues and reopened only if the pattern re-appears during V17.

## 5. Delivered capabilities

The following core capabilities are on master and satisfy the V17 contract.
The remaining production launch-path pass-through is listed in §6.

### 5.1 Gate execution + coverage

- Every configured gate fires every round via `after_round: every` (schema-supported; runner delegates to `GateConfig.matches_round`).
- The pre-gate `run_comparison.py` campaign loads and validates the observe-mode YAML.
- The tuner accepts an optional `health_checks_config`; the production chain still needs the narrow pass-through listed in §6.1 before V17 launch.

Evidence: `configs/health_checks_baseline_observe_mode.yaml`, `execute_tools/health_checks/runner.py`, `scripts/run_comparison.py` launch-time check.

### 5.2 Blocking-style checks (routed as observation-only)

Three checks compute per-file metrics + apply per-file thresholds, but under V17 both `on_pass` and `on_fail` route to `continue`:

- `output_diversity` — unique_int8 > 25
- `output_std` — std_mv >= 1.0
- `amplitude_collapse` — dominant_fraction <= 0.95

Multi-file peek at `peek_file_indices: [3, 10, 17]` with `aggregation: any_pass` via the shared `_multi_file_peek` helper.

### 5.3 Recording checks

Three no-threshold observations run every round without ever influencing routing:

- `pearson_dispersion` — stdev of per-file pearson (24× empirical separation between real learning and collapse)
- `spectral_peak_ratio` — PSD peak / neighborhood ratio
- `per_file_output_std` — full per-file std distribution

### 5.4 Typed persistence contract

Every gate execution serialises to a `PersistedHealthGateResult` with the exact V17 field set:

```
gate_name
execution_status              # Literal["passed", "failed", "not_run", "error"]
check_passed                  # bool | None  (null for recording-only)
would_invalidate_under_production_policy  # counterfactual verdict
resolved_action               # observe-mode: always continue
failure_reason
threshold
aggregation
metrics
gate_runtime_seconds
```

The counterfactual verdict is derived by loading a separate production-policy YAML at evaluation time and mapping per-gate `on_fail` action; it is not inferred from gate names.

Evidence: `execute_tools/health_checks/schemas.py::PersistedHealthGateResult`, `execute_tools/health_checks/evaluation.py::evaluate_and_persist_health_gates`.

### 5.5 Score-validity policy

`noise <= 1e-10 → NaN` guard in `execute_tools/scoring_utils.py::get_snr` (inclusive at the boundary). `nodes/ml_hyperparameter_tune_agent::_merge_score_validity_failure` treats `None` / non-finite scorer results as collapse independently of any gate — belt-and-suspenders coverage.

### 5.6 Resumable pre-gate baseline campaign

- Fresh baseline required per new campaign identity.
- Same-campaign Phase 1 reuse validated via `core/campaign_artifacts.py::validate_phase1_baseline` + `decide_phase1_reuse`.
- `--resume` flag in `scripts/run_comparison.py` triggers reuse-with-validation.
- Record completeness check refuses to proceed to the next model when validation fails.

### 5.7 Threshold freeze

Per-check disposition documented and frozen for the campaign in [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md). Three blocking-style thresholds `retain`; three recording-only checks `provisional recording-only`. Production disposition remains `undetermined` — the campaign provides evidence for a later production decision, not a mid-campaign edit.

### 5.8 Loss exploration and runtime inventory

V17 retains all three implemented loss branches:

- **Branch A** — registered built-in losses.
- **Branch B** — reusable loss plugins that are currently present and loadable
  in the execution context.
- **Branch C / Option C** — a new loss with a complete `custom_loss_spec`,
  materialized through the existing proposer → implementor → registry → tuner
  workflow.

PR #122 centralizes the live reusable-loss inventory used by prompt rendering
and proposal validation. Historical, workspace-only, stale, or missing plugins
are no longer advertised or accepted as Branch B. Option C remains unchanged
and was verified by deterministic tests and Gate 1; the unrestricted Gate 2
also passed.

### 5.9 Completed pre-gate diagnostic evidence

These campaigns are diagnostic evidence, not the V17 workflow exploration and
not a completion requirement to be replayed before launch:

| Model | Diagnostic result | Disposition |
|---|---|---|
| FCNet | Baseline completed; tuning stopped at `6/10` after the collapse pattern was established | Partial evidence retained; no rerun required |
| PUNet | Baseline completed; tuning ended partial at `3/10` after repeated `bilinear=False` structural failures | Partial evidence retained exactly as recorded; PR #121 repaired the defect; no rerun required |
| WaveNet | Baseline and `10/10` tuning rounds completed | Completed evidence retained; nominal best score remained HealthGate-collapsed |

The diagnostics established the observation and continuation behavior used to
prepare V17. V17 itself remains the two-chain workflow exploration described in
the launch report, with three tuner rounds per workflow iteration.

## 6. V17 launch readiness

The launch-readiness PR completes the remaining narrow operational work without
changing HealthGate, scoring, or exploration architecture.

### 6.1 Observe-mode HealthGate launch plumbing — implemented

The optional `health_checks_config` value now propagates through:

```text
run_chain.sh / _chain_common.sh
  → run_one_iteration.py
  → workflows.model_exploration.run_workflow
  → local_validated_model protocol
  → HyperparamTuningInput.health_checks_config
```

When omitted, existing callers retain the shipped default. When supplied, the
exact path is persisted in the tuner output and iteration manifest. The final
Gate 2 demonstrated consumption of
`configs/health_checks_baseline_observe_mode.yaml` on every completed round.

### 6.2 V17 advice files — implemented

`advice/workflow/v17_loss_explorer.json` and
`advice/workflow/v17_arch_explorer.json` preserve the V16 control-variable
strategy while explicitly retaining Branch A, live Branch B, and Option C.
They also state the model/task output-contract constraint and the limits of
V17's observe-only feedback path.

### 6.3 V17 workflow execution — operator approval required

The production command has been dry-run with both advice files and the explicit
observe-mode config. Run the two V17 workflow chains only from merged, clean
`master`, after the post-merge preflight and explicit operator approval. This
is the actual V17 campaign; it must not be conflated with the completed
pre-gate diagnostics in §5.9.

### 6.4 `build_diagnostic_summary.py` schema update

The diagnostic-summary script still infers a binary `passed | failed` from `failure_reason` presence. It has not been updated to consume `PersistedHealthGateResult.execution_status` (four states). Not blocking for the campaign, but should be updated so post-campaign analysis uses the same state vocabulary as the persisted records.

### 6.5 Seed-path documentation

Update seed-path documentation for operator clarity (issue #104). Cosmetic but reduces launch confusion.

### 6.6 V17 valid-candidate selection and fixed formal reference

Execution-affecting trial selection is HealthGate-valid-only. Observe-mode
`resolved_action=continue` is not itself evidence of validity: successful,
finite records must contain all required blocking-style gate results, all must
execute and pass, and no counterfactual production invalidation or collapse
marker may be present. Legacy records lacking typed gate evidence remain raw
historical evidence but have unknown validity and are ineligible as viable
candidates.

V17 preserves raw-best reporting and adds explicit best-valid and
best-valid-formal fields. Each production iteration uses the fixed formal
comparison reference `0.0`; with the approved deltas, the skip threshold is
`0.0` and the formal-time-budget bypass threshold is `0.5`. This fixed value is
not a chain-wide incumbent. Dynamic committed incumbent restoration is
deferred to V18.

## 7. Deferred to V18

See [`v18_priorities.md`](./v18_priorities.md) for the full list with rationale and dependencies. In summary, V18 will cover:

- **Feedback propagation** — collapse signals flowing from tuner into `ModelRunSummary`, interpreter schemas, and proposer prompts.
- **Adaptation** — adaptive thresholds, aggregation-policy search, cross-iteration collapse-fingerprint avoidance.
- **Stateful tuner stop policies** — independent repeated-collapse and
  repeated-invalid-score counters, tuner-level routing, persistence/resume,
  and a successful `completed_early` terminal state. Reviewed before V17 and
  intentionally deferred because V17 is observational and uses only three
  rounds per tuner invocation.
- **Workflow evolution** — bidirectional cross-iteration information flow and
  larger orchestration/monitoring changes.
- **Metric refinement** — correlation-based score-modification exploration, other post-observation-data-informed changes.
- **Forensic backlog** — v15 iter-4/R4 outlier + related historical anomalies, revisited if V17 observation data warrants.

## 8. Historical items

Items dropped or absorbed during the M8/M9/PR#117/PR#119 landings — retained here as a compact record so future readers understand the trajectory:

| Item | Disposition |
|------|------------|
| File-vector byte-identity dedup | Dropped — mechanism-based diversity checks supersede |
| Precomputed phantom-score table | Dropped — mechanism-based checks supersede |
| Tighten `OutputDiversityCheck` thresholds | Absorbed — threshold=25 landed with empirical calibration |
| YAML gate positions per `max_rounds` | Absorbed — `after_round: every` obviates round-specific tuning |
| Formal-round training regime research | Reclassified — epochs / train_portion / formal settings are campaign launch configuration; frozen in the launch plan, not V17 feature work |
| Gate 2 execution | Done — landed via PR #101 |

## 9. Related docs

- [`v17_pregate_baseline_launch_plan.md`](./v17_pregate_baseline_launch_plan.md) — operational launch plan, threshold freeze, record contract, per-model checklists
- [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md) — frozen threshold decision + per-check disposition
- [`paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md) — empirical basis for the frozen thresholds
- [`v18_priorities.md`](./v18_priorities.md) — deferred items with rationale and dependencies
- [`pluggable_health_checks.md`](./pluggable_health_checks.md) — HealthGate framework reference
- [`collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md) — generic framework contract
- [Experiment report: health_metrics_scan.md](https://github.com/Galileo-Sandbox/siderius-exp/blob/e9e5063b/reports/health_metrics_scan.md) — 20-file FCNet observation scan
