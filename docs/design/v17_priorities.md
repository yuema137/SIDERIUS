# V17 Priority Decisions — Revised 2026-07-17

- **Status**: scope frozen; observation infrastructure feature-complete; awaiting campaign execution
- **Scope**: observation-layer release — HealthGate coverage, typed persistence, unified all-file baselines + 10-round campaigns for FCNet, WaveNet, PUNet
- **Owner**: SIDERIUS operators
- **Related**: [`v17_pregate_baseline_launch_plan.md`](./v17_pregate_baseline_launch_plan.md), [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md), [`v18_priorities.md`](./v18_priorities.md)

## 1. Goal

Establish one consistent, reasonable, auditable model-health standard for both the newly trained all-file baselines and the V17 workflow exploration, without allowing gate failures to interrupt the exploration.

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
- Trains one unified all-file generalist baseline (no frequency splitting) plus exactly ten tuning rounds for each of FCNet, WaveNet, PUNet.
- Reuses a validated same-campaign Phase 1 baseline on resume; requires a fresh baseline for a new campaign.
- Adds only the minimum necessary wiring to the existing `run_comparison.py`; no parallel runner, no artifact-storage redesign.

## 4. What V17 is not

- Not a collapse-detection optimizer. Thresholds are frozen for observation, not proven optimal.
- Not a workflow-adaptation release. Interpreter, proposer, and cross-iteration feedback stay unchanged.
- Not a metric redesign. `denoising_score` computation is untouched; only the score-validity guard (`noise <= 1e-10`) is enforced.
- Not a custom-loss release. V17 relies on registered built-in losses only (advice-enforced); the custom-loss implementor contract redesign is a V18 item.
- Not a forensics deep-dive. Past outliers (e.g., the v15 iter-4/R4 anomaly) are preserved as issues and reopened only if the pattern re-appears during V17.

## 5. Delivered capabilities

All the following are on master and satisfy the V17 contract:

### 5.1 Gate execution + coverage

- Every configured gate fires every round via `after_round: every` (schema-supported; runner delegates to `GateConfig.matches_round`).
- Baseline and tuner rounds load the same observe-mode YAML.
- `scripts/run_comparison.py` refuses to launch the pre-gate baseline unless every gate is `after_round: every` + `continue`/`continue` — invariant enforced at launch, not documentation only.

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

## 6. Remaining V17 work

Small and narrow. All operational or documentation-alignment; no framework changes.

### 6.1 Campaign execution (operational)

Run the three-model observation campaign per [`v17_pregate_baseline_launch_plan.md`](./v17_pregate_baseline_launch_plan.md):

- FCNet: unified all-file baseline + 10 rounds
- WaveNet: unified all-file baseline + 10 rounds
- PUNet: unified all-file baseline + 10 rounds

Same gate standard, same score-validity policy, same file selection throughout. Record completeness validated before proceeding to the next model.

### 6.2 Built-in-loss constraint reaches the tuner (verification)

The built-in-loss-only constraint currently lives as advice narrative in `advice/workflow/v17_pregate_baseline_advice.json`. Verify at launch that:

- The constraint actually reaches the tuner (advice is loaded and applied, not silently dropped).
- The intentional restriction is recorded in per-model run metadata so post-hoc analysis can attribute any missing custom-loss exploration to this campaign choice.

If the tuner does not enforce the constraint on the input plan, add a minimum guard: reject `loss_type: custom` / non-null `custom_loss_spec` at plan validation. Small verification + small guard if needed; not a redesign.

### 6.3 `build_diagnostic_summary.py` schema update

The diagnostic-summary script still infers a binary `passed | failed` from `failure_reason` presence. It has not been updated to consume `PersistedHealthGateResult.execution_status` (four states). Not blocking for the campaign, but should be updated so post-campaign analysis uses the same state vocabulary as the persisted records.

### 6.4 Seed-path documentation

Update seed-path documentation for operator clarity (issue #104). Cosmetic but reduces launch confusion.

## 7. Deferred to V18

See [`v18_priorities.md`](./v18_priorities.md) for the full list with rationale and dependencies. In summary, V18 will cover:

- **Feedback propagation** — collapse signals flowing from tuner into `ModelRunSummary`, interpreter schemas, and proposer prompts.
- **Adaptation** — adaptive thresholds, aggregation-policy search, cross-iteration collapse-fingerprint avoidance.
- **Workflow evolution** — custom-loss implementor contract redesign (unblocks non-built-in losses in tuner planning), bidirectional cross-iteration information flow.
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
- [`../reports/health_metrics_scan.md`](../../reports/health_metrics_scan.md) — 20-file FCNet observation scan
