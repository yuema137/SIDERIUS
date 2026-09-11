# V17 Pre-Gate Baseline Launch Plan

- **Status**: approved — shared preflight passed; FCNet launch authorized
- **Scope**: post-M9 observation campaign for unified all-file WaveNet, PUNet, and FCNet models
- **Owner**: TBD
- **Created**: 2026-07-16
- **Last Updated**: 2026-07-17
- **Related design docs**:
  - [`v17_priorities.md`](./v17_priorities.md) — V17 scope authority; this launch plan is the operational execution of §6.1 of that doc
  - [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md) — frozen threshold decisions applied here
  - [`v18_priorities.md`](./v18_priorities.md) — deferred workflow-adaptation items (post-campaign)
  - [`collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md)
  - [`m8_gate_coverage_and_diversity_metrics_execution_plan.md`](./m8_gate_coverage_and_diversity_metrics_execution_plan.md)
  - [`m9_multi_file_peek_execution_plan.md`](./m9_multi_file_peek_execution_plan.md)
  - [`paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md)
  - [`tidmad_collapse_advice_and_forensics.md`](./tidmad_collapse_advice_and_forensics.md)
  - [experiment report: `reports/health_metrics_scan.md`](https://github.com/Galileo-Sandbox/siderius-exp/blob/e9e5063b/provenance/legacy_siderius/p0_03c1/reports/health_metrics_scan.md)

## 1. Purpose and final campaign decisions

This campaign produces a reliable post-M9 observation dataset for the current
SIDERIUS generalist workflow. It is not a paper reproduction and must not be
described as paper-equivalent.

For each of WaveNet, PUNet, and FCNet:

- Train one **all-file unified SIDERIUS baseline** over all 20 training files.
- Produce one baseline checkpoint.
- Run exactly ten tuner rounds with the same unified topology.
- Produce one checkpoint per completed tuning round.
- Use the intended full validation scope for the baseline and final formal
  evaluation.
- Evaluate every configured HealthGate after the baseline and after every
  completed tuner round.
- Route every successfully executed gate to `continue`, whether its check
  passes or fails.
- Persist enough structured data to reconstruct production-policy
  invalidation without rerunning a model or parsing logs.

No frequency splitting, composite aggregation, or split-specific routing is
in scope. Historical split-model artifacts may be used only as external
threshold evidence.

The campaign is intended to answer:

1. Which gate metrics distinguish healthy learning from collapse?
2. Which current thresholds produce false positives or false negatives?
3. How do metric distributions differ across FCNet, WaveNet, and PUNet?
4. Can every gate execute and persist results after every experiment?
5. Can all gate failures remain observe-only while all ten rounds complete?
6. Can production-policy invalidation be reconstructed afterward without
   rerunning models?

## 2. Scope and hard invariants

### 2.1 Run identity and ordering

Use the run name `v17_pregate_baseline` and one isolated root per model:

```text
/home/klz/Data/SIDEREIS_DATA/<model>/v17_pregate_baseline/
```

Recommended sequential order:

1. **FCNet** — fastest inference and the strongest existing healthy reference;
   it gives the quickest feedback on persistence and threshold behavior.
2. **WaveNet** — known collapse-prone case; it tests that failed gates remain
   visible while all ten rounds continue.
3. **PUNet** — historically slower inference and recently affected by a CUDA
   Xid/launch-timeout incident; run it after the pipeline is proven twice.

Do not run models in parallel on the single RTX 5090. Concurrent training or
inference would contend for VRAM, host RAM, HDF5 I/O, and CUDA context state,
invalidate timing comparisons, and increase OOM/Xid risk.

### 2.2 Invariants

- Do not change `execute_tools/scoring_utils.py` or the score formula.
- Preserve `noise <= 1e-10 -> invalid`; do not add epsilon or floor the
  denominator.
- Do not change gate thresholds during the three-model campaign.
- Freeze the reviewed observe-mode YAML before FCNet launches; record its path
  and SHA-256 in every model's metadata.
- Do not overwrite `configs/health_checks.yaml`; use a separate campaign YAML.
- Do not pass `--cleanup_denoised`.
- Do not overwrite or silently reuse prior baseline/tuner artifacts.
- Do not launch without explicit operator approval after Section 13 passes.

## 3. Unified baseline definition

### 3.1 Topology and data scope

Every baseline and tuner round uses one unified model:

- One model instance and one checkpoint.
- Training scope spans all training files `0-19`.
- Baseline sampling uses snapshot scope `1.0`, with per-epoch
  `train_portion=0.1` under the current baseline runner.
- Baseline validation/inference covers all validation files `0-19` and all
  configured evaluation segments.
- Tuner trial rounds use their validated trial sample sets; the final formal
  round uses the configured full formal validation scope.

The baseline record must serialize the exact training-file inventory and the
actual number of selected and processed segments. A statement such as “all 20
files” is not sufficient without the explicit list and counts.

### 3.2 Effective baseline configurations

| Model | Architecture | Loss | Optimizer | LR | Weight decay | Batch | Epochs | Segment length |
|---|---|---|---|---:|---:|---:|---:|---:|
| WaveNet | input 16, residual 32, gate 64, skip 32, kernel 12, 10 blocks | focal, alpha 0.5, gamma 2.0 | Adam | `5e-4` | 0 | 1 | 1 | 40,000 |
| PUNet | multi 40, depth 4, bilinear, PE 1.0, kernel 9, embedding 32 | focal, alpha 0.5, gamma 2.0 | Adam | `5e-4` | 0 | 1 | 1 | 40,000 |
| FCNet | latent dimensions `[4000, 400, 40]`, dropout 0 | smooth-L1, beta 1.0 | Adam | `5e-4` | 0 | 1 | 1 | 40,000 |

`legacy_baseline_configs.json` currently contains `epochs: 10`, while
`run_baseline_trial()` explicitly overrides the effective baseline epoch count
and defaults it to one. The campaign uses the effective one-epoch execution
shown above. Metadata must record both the source config hash and the final
validated config actually executed; reports use only the latter when
describing the run.

### 3.3 Required baseline provenance

The baseline record must persist:

- Complete ordered training-file list and dataset inventory identifiers.
- Sampling strategy, scope portion, `train_portion`, and random-selection
  algorithm/version.
- Selected segments per file, total selected segments, processed segments per
  epoch, total processed segments, and optimizer-step count.
- Batch size, epochs, optimizer, learning rate, weight decay, and loss config.
- Complete architecture config and segment length.
- Every random seed used by sample selection, initialization, training, and
  data-loader workers.
- Checkpoint path, size, SHA-256, creation timestamp, and model type.
- Validation-file list, evaluation sample-set inventory, and full/sparse scope.
- Exact command, Git SHA/dirty state, Python/PyTorch/CUDA/driver/GPU versions,
  anchor-map path/hash/`s_max`, HealthGate-config path/hash, and timestamps.

Use the term **all-file unified SIDERIUS baseline** or **generalist baseline**.

### 3.4 Fresh training and same-campaign Phase 1 reuse

FCNet, WaveNet, and PUNet must each train a new Phase 1 baseline on their first
`v17_pregate_baseline` execution. Historical `baseline_trial`, paper-model,
pre-M8, pre-M9, and diagnostic artifacts are never valid Phase 1 sources.

When no valid Phase 1 artifact exists under the model's campaign root:

1. Train the unified baseline from scratch.
2. Persist its checkpoint, validated config, training provenance, inference
   outputs, score/structured invalid result, file vector/absence reason,
   HealthGate results, record, and manifest.
3. Mark Phase 1 complete only after the baseline completeness validator passes.

On resume, reuse the existing campaign Phase 1 baseline only when all of these
validate:

- Campaign/run identity is exactly `v17_pregate_baseline` and model type
  matches.
- Effective validated training config exactly matches the frozen campaign
  config.
- Ordered training inventory covers files 0-19 and recorded sampling/segment
  counts are complete.
- Training status is successful.
- Checkpoint exists, loads, and matches its recorded path/hash/identity.
- Inference outputs are complete and readable, or the manifest establishes
  that they can be regenerated from the validated checkpoint.
- Scalar score or structured invalid-score result exists.
- Full file vector or structured absence reason exists.
- Every configured HealthGate has a persisted typed result.
- Baseline completeness validation passes.

If any check fails, report every failed validation and retrain Phase 1 for that
model; never silently fall back to a historical workspace. If all checks pass,
reuse Phase 1 without training and continue from the next incomplete phase or
tuning round. Missing inference outputs may be regenerated from the validated
checkpoint without retraining; the manifest must record that regeneration.

“All models must be retrained” means one fresh baseline per model for this
campaign, not repeated retraining of an already valid campaign Phase 1 after an
interruption.

## 4. Chain configuration

| Setting | Value | Rationale |
|---|---:|---|
| completed tuning rounds | 10 | Required campaign horizon |
| topology | one unified model over files 0-19 | Final campaign decision |
| mode | trial exploration with round 10 formal | Current comparison workflow |
| trial strategy | snapshot | Stable current default |
| trial scope / eval portion | 0.1 / 0.1 | Current tuner defaults; persist effective values |
| formal strategy | snapshot | Comparable full-scope promotion |
| formal training scope | 0.1 | Current runner default |
| formal train portion | 1.0 | Full iteration fraction within formal scope |
| formal eval portion | 1.0 | Full validation scope in round 10 |
| maximum epochs | 1 | Prevent planner-selected cost drift |
| trial time budget | 20 minutes/attempt | Bounds pathological plans |
| formal time budget | 120 minutes/attempt | Leaves room above the 13-18 minute scoring floor |
| trial attempts | 3 | Current tuner default |
| formal attempts | 5 | Current tuner default |
| consecutive failed-round brake | 3 | Infrastructure/schema failures only |
| denoised cleanup | disabled | Required forensic retention |

M7 remains open. Tuner plans must use registered built-in losses. The current
`gate2_smoke_advice.json` has a `propose` key, whereas
`run_comparison.py --human_advice_file` requires `tune`. Before launch, use a
validated tuner-compatible built-in-loss constraint or a typed fixed-loss
override; do not assume an undelivered advice file constrains execution.

## 5. HealthGate execution and observe-only policy

### 5.1 Coverage

Every configured gate must declare:

```yaml
after_round: every
```

This applies to:

- Baseline evaluation.
- Tuning rounds 1-9.
- Round 10, including when it is the final formal round.

The current tuner fires gates after tuner scoring, but the baseline path does
not currently evaluate HealthGate. Baseline gate execution is therefore a
pre-launch wiring requirement. It must use the same typed evaluation and
persistence path as tuner rounds; a separate ad hoc baseline implementation is
not acceptable.

Every completed baseline or tuning record must contain one result for every
configured gate. A missing input becomes `not_run`; an implementation failure
becomes `error`. Neither may be silently omitted.

### 5.2 Routing

Create and freeze:

```text
configs/health_checks_baseline_observe_mode.yaml
```

For every gate in that file:

```yaml
on_pass:
  action: continue
on_fail:
  action: continue
```

This includes the normally blocking output-diversity, output-std, and
amplitude-collapse gates. Recording gates also remain `continue` on both
branches. A failed check must never invalidate a round, skip a round, jump to
formal, terminate tuning, or increment the infrastructure-failure counter.

For every gate result, persist these independent concepts:

```text
check_passed
would_invalidate_under_production_policy
resolved_action
```

`resolved_action` is always `continue` for every successfully executed gate in
this campaign. `would_invalidate_under_production_policy` is derived from the
frozen production-policy mapping, not from the observe-mode action.

### 5.3 Alternate-config wiring

`load_health_gates_config(path=...)` supports a path, but production runner
calls currently load the default implicitly. `run_comparison.py` and the tuner
do not expose an alternate HealthGate-config flag.

Before launch, add one validated config-path field (proposed CLI name
`--health_checks_config`) and propagate it through `run_comparison.py`, the
tuner input schema/protocol, baseline evaluation, and gate runner. Record the
resolved absolute path and SHA-256. A test must prove that the campaign process
loaded the observe-mode YAML and that every pass/fail branch resolves to
`continue`.

## 6. Pre-launch threshold review and freeze

Thresholds are not accepted merely because they are present in YAML. Before
FCNet launches, produce both human-readable and machine-readable reviews:

```text
docs/design/v17_pregate_threshold_review.md
/home/klz/Data/SIDEREIS_DATA/fcnet/v17_pregate_baseline/threshold_review.json
```

Copy the identical JSON into the WaveNet and PUNet roots at launch. The review
must include gate/check version, metric, operator, value, unit, aggregation,
files, sample count, evidence, risks, and `retain | revise | provisional`.
Any revision occurs before the YAML freeze and requires targeted tests. No
threshold changes are permitted after FCNet starts.

### 6.1 Draft review table to finalize before launch

| Gate/check | Metric | Current criterion | Unit | Aggregation / files | Historical evidence | Healthy support | Collapsed support | False-positive risk | False-negative risk | Draft decision |
|---|---|---|---|---|---|---|---|---|---|---|
| `output_diversity_blocking` / `output_diversity` | unique int8 count | pass when `n_unique_int8_values > 25` | count in inspected CH1 samples | `any_pass`; files `[3,10,17]`; 100,000 samples/file | `reports/health_metrics_scan.md` and M8/M9 plans | FCNet full scan: minimum 52, including file 3; typical high-band 127-159 | collapsed WaveNet 9-15; agent_012=2; synthetic/class-127 near-constant cases ≤5 | A weak but real model might have ≤25 unique values on every inspected band | Partial collapse passes if one inspected file remains diverse; non-inspected files can collapse | **retain**, but validate on new PUNet/WaveNet data |
| `output_std_blocking` / `output_std` | output standard deviation | pass when `output_std_mv >= 1.0` | mV (`40/128` mV per int8 LSB) | `any_pass`; files `[3,10,17]`; 100,000 samples/file | FCNet/reference scan | FCNet minimum 2.01 mV; typical high-band about 7.35 mV | collapsed WaveNet maximum 0.192 mV; agent_012 about 0.008 mV | Low-amplitude genuine learning might stay below 1 mV across inspected files | One healthy-amplitude file masks collapse in other inspected/non-inspected files | **retain**, cross-model evidence provisional |
| `amplitude_collapse_blocking` / `amplitude_collapse` | dominant int8-mode fraction | pass when `dominant_mode_fraction <= 0.95` | fraction | `any_pass`; files `[3,10,17]`; 100,000 samples/file | FCNet/reference scan and class-127 forensic | FCNet range about 0.026-0.059 | collapsed WaveNet 0.994-0.997; agent_012 about 0.9999; strict class-127=1.0 | A legitimate very-low-signal output could be highly concentrated | `any_pass` misses partial collapse whenever one inspected file is ≤0.95; files outside triplet are not decisive | **retain**, aggregation risk explicitly provisional |
| `pearson_dispersion_recording` / `pearson_dispersion` | sample stdev (`ddof=1`) of per-file Pearson values | **no pass/fail metric threshold**; numeric completion is recorded | dimensionless correlation dispersion | all available validation files; 1,000,000 samples/file | FCNet/reference scan | FCNet approximately 0.048 | collapsed WaveNet approximately 0.002; agent_012 approximately 0.007 on files 12-19 | If promoted later, model/frequency sign changes and low-band noise can misclassify healthy output | Dispersion can be nonzero without learned signal and lacks a validated cutoff | **provisional recording-only** |
| `spectral_peak_ratio_recording` / `spectral_peak_ratio` | `signal_window / noise_window` around auto-detected PSD peak | no health threshold; `noise <= 1e-10` yields NaN as numerical validity | dimensionless ratio | all available validation files; 1,000,000 samples/file | scoring definition and phantom forensics; not fully calibrated in full scan | No campaign-wide healthy distribution yet | Strict-constant/class-127 yields invalid noise; near-constant phantom may remain finite | Auto-detected noise peaks and real narrowband variation may overlap | Finite near-constant phantoms can look strong; NaNs can arise from numerical/input issues | **provisional recording-only** |
| `per_file_output_std_recording` / `per_file_output_std` | per-file output std plus distribution statistics | no pass/fail threshold | mV | all available validation files; 100,000 samples/file | FCNet/reference scan | FCNet 2.01-7.80 mV | collapsed WaveNet 0.077-0.192 mV; agent_012 about 0.008 mV | No threshold today; future cutoff may penalize legitimate low-amplitude bands | Aggregate summaries can hide individual collapsed files unless per-file values are retained | **provisional recording-only** |

The review JSON must not invent thresholds for recording-only metrics. It must
represent `threshold: null`, document numeric-validity conditions separately,
and mark the metric provisional.

### 6.2 Freeze procedure

Before FCNet launch:

1. Recompute cited healthy/collapsed ranges from immutable source artifacts.
2. Verify the code's actual comparison operators. In particular, current
   output diversity is strict `> 25`, output std is `>= 1.0`, and amplitude
   passes at equality (`<= 0.95`).
3. Finalize each decision as retain, revise, or provisional.
4. Generate `configs/health_checks_baseline_observe_mode.yaml` without changing
   `configs/health_checks.yaml`.
5. Validate the YAML through the Pydantic schema and targeted tests.
6. Compute SHA-256 and record it in `threshold_review.json` and run metadata.
7. Freeze the file for all three model runs. Any later change creates a new
   campaign identity rather than mutating this one.

## 7. Typed HealthGate result contract

### 7.1 Required persisted structure

Persist the full typed result for every configured gate. Saving only
`failure_reason`, an overall pass/fail, or final action is insufficient.

Each gate record must contain at least:

```json
{
  "gate_name": "output_diversity_blocking",
  "execution_status": "passed",
  "check_passed": true,
  "would_invalidate_under_production_policy": false,
  "resolved_action": "continue",
  "failure_reason": null,
  "threshold": {
    "metric": "n_unique_int8_values",
    "operator": ">",
    "value": 25,
    "unit": "unique_int8_count"
  },
  "aggregation": {
    "aggregation_rule": "any_pass",
    "files_requested": [3, 10, 17],
    "files_completed": [3, 10, 17],
    "files_passed": [3, 17],
    "files_failed": [10],
    "aggregate_passed": true
  },
  "metrics": {
    "per_file": {}
  }
}
```

Supported execution statuses:

| Status | Meaning |
|---|---|
| `passed` | Check executed and its configured predicate passed |
| `failed` | Check executed and its configured predicate failed |
| `not_run` | Required input or artifact was unavailable |
| `error` | Gate implementation raised or returned an execution error |

`not_run` and `error` are infrastructure/observability states, not model
collapse. A recording-only check's `check_passed` means execution/predicate
completion, not that its measured value is healthy.

### 7.2 Required per-file structure

Use structured mappings, not JSON strings embedded inside JSON fields:

```json
{
  "per_file": {
    "3": {
      "file_index": 3,
      "file_path": "/absolute/path/to/output_0003.h5",
      "passed": true,
      "sample_count_inspected": 100000,
      "sampling_method": "channel0001_prefix_peek",
      "metrics": {
        "n_unique_int8_values": {"value": 84, "unit": "count"}
      },
      "checkpoint_sha256": "...",
      "output_inventory_id": "...",
      "output_sha256": "...",
      "gate_runtime_seconds": 0.0,
      "io_warning": null
    }
  }
}
```

Every multi-file result must contain entries for requested files `[3,10,17]`,
even when an entry is `not_run` or `error`. Record exact path, index,
checkpoint hash, output hash or stable inventory ID, actual sample count,
sampling method, units, runtime, and I/O warning.

The current implementation serializes M9 per-file results into
`metrics["per_file_json"]`; recording checks similarly emit `*_json` strings.
Before launch, replace these with typed mappings in the schema and persisted
record unless an existing typed compatibility boundary requires dual-writing.
Stdout is never authoritative.

### 7.3 Reproducible aggregate

Persist both per-file values and a reproducible aggregate:

```json
{
  "aggregation_rule": "any_pass",
  "files_requested": [3, 10, 17],
  "files_completed": [3, 10, 17],
  "files_passed": [3, 17],
  "files_failed": [10],
  "files_not_run": [],
  "files_error": [],
  "aggregate_value": null,
  "aggregate_passed": true
}
```

The saved aggregate must be reproducible from saved per-file values and the
saved predicate/aggregation definition without parsing logs.

### 7.4 Recording metric requirements

For `pearson_dispersion`, `spectral_peak_ratio`, and
`per_file_output_std`, persist:

- Raw per-file values keyed by validation-file index.
- File path/inventory and provenance described in Section 7.2.
- `count`, `minimum`, `q25`, `median`, `q75`, `maximum`, `mean`, and sample
  standard deviation.
- Missing-file count, failed-I/O count, files requested/completed, actual
  samples per file, units, and calculation-version identifier.
- Explicit `not_run`/`error` entries for unavailable files.

Pearson persistence must include raw per-file Pearson values even though the
current check exposes only dispersion/mean/range. Spectral and per-file std
must expose typed maps rather than `ratio_per_file_json`,
`std_mv_per_file_json`, or `io_failed_json` strings.

### 7.5 Record plumbing prerequisite

The tuner currently computes `GateResult` objects but writes only
`failure_reason` and `gate_action` onto the experiment record. Before launch:

- Extend the typed experiment-record schema with `health_gate_results`.
- Map every baseline/tuner gate result into that field.
- Preserve the field through storage, memory history, summary generation, and
  any downstream protocol consuming experiment results.
- Make the planner see prior failed observe-only checks without treating them
  as infrastructure failure.
- Add schema, unit, protocol, pseudo-integration, and summary tests.

## 8. Deterministic run-level artifact structure

```text
v17_pregate_baseline/
├── baseline/
│   ├── checkpoint/
│   ├── config/
│   ├── denoised/
│   ├── records/
│   │   ├── baseline_record.json
│   │   └── health_gate_results.json
│   └── baseline_summary.json
├── agent/
│   ├── rounds/
│   │   ├── round_01/
│   │   │   ├── checkpoint/
│   │   │   ├── config.json
│   │   │   ├── denoised/
│   │   │   ├── score.json
│   │   │   ├── health_gate_results.json
│   │   │   ├── plan.json
│   │   │   ├── reflection.json
│   │   │   └── attempt_history.json
│   │   ├── round_02/
│   │   └── ...
│   │   └── round_10/
│   ├── memory_trace.jsonl
│   ├── tuner_run_metadata.json
│   └── agent_summary.json
├── launch/
│   ├── exact_command.txt
│   ├── environment.txt
│   ├── checksums.json
│   └── screen.log
├── threshold_review.json
└── postrun_analysis.json
```

Existing internal conventions may be retained, but deterministic authoritative
paths for every score, record, gate result, checkpoint, config, and denoised
output must be documented in a manifest. Users must not search logs or glob
ambiguous filenames to reconstruct a round.

This layout is illustrative, not a repository-wide storage migration. The
implementation should preserve current recorder/sandbox paths where practical
and write an authoritative campaign manifest mapping each logical artifact to
its actual deterministic path and identity.

`run_comparison.py` currently writes trial baselines into the shared
`{model}/baseline_trial/` directory. Before launch, expose or derive a
run-specific baseline workspace under the campaign root and ensure its cache
check cannot reuse prior artifacts.

Preserve all baseline and completed-round checkpoints, denoised HDF5 outputs,
attempt/error records, plans, reflections, memory, configs, score vectors,
gate results, timing/memory probes, logs, and provenance manifests.

## 9. Record completeness validator

Before campaign launch, add a validator and run it against one completed mock
baseline plus one completed mock round. The validator must load typed records,
not infer state from filenames or stdout.

For each record, assert:

- A scalar score exists, or an explicit invalid-score object gives the reason.
- A file-wise score vector exists, or a structured absence reason exists.
- Every configured gate has exactly one result.
- Every gate has `execution_status` and `resolved_action`.
- Every executed gate contains metrics.
- Every configured multi-file gate contains entries for `[3,10,17]`.
- All three recording metrics and their per-file values are persisted.
- Checkpoint/config/output provenance exists and hashes/inventory IDs agree.
- No `success` record has a null scalar without a structured explanation.
- No failed observe-mode gate resolves to anything except `continue`.
- `not_run` and `error` are not labeled model collapse.
- Aggregate verdicts recompute from the persisted per-file values.

At run level, assert:

- Exactly one baseline record exists.
- Exactly ten completed tuner rounds exist with unique indices 1-10.
- One checkpoint exists per baseline/completed round.
- The summary agrees with the underlying records and counts.
- Attempt failures do not replace or increment completed rounds.

Run the same validator after each real model over the baseline, rounds 1-10,
and summary. Do not launch the next model until validation passes.

The same validator supplies the Phase 1 reuse decision. Reuse is allowed only
when validation succeeds against the resolved campaign workspace and frozen
campaign inputs; a summary file's mere existence is never sufficient.

## 10. Collapse versus infrastructure failure

- A gate threshold failure is a completed experimental observation. Save it,
  increment `completed_rounds`, expose it to planner memory, and continue.
- An invalid scalar caused by the frozen score validity rule may still be a
  completed experiment when training/inference/scoring executed and the
  structured explanation is present.
- Schema errors, missing/corrupt artifacts, training/inference/scoring
  exceptions, CUDA OOM/Xid, driver loss, and disk exhaustion are
  infrastructure attempt failures.
- An infrastructure failure gets an attempt record and retry; it does not
  count among the ten completed rounds.
- Stop after three consecutive rounds exhaust all configured retries, or
  immediately for corrupted inputs, unusable GPU state, or insufficient disk.
- Never convert a gate failure into a retry or infrastructure-failure count.

## 11. Storage, runtime, and cost estimates

Current evidence:

- A full 20-file HDF5 output set is approximately 75-86 GB.
- The prior WaveNet diagnostic agent retained 140 HDF5 files in 120 GB because
  trial snapshots are sparse; its baseline occupied 86 GB.
- The historical paper-model archive is 5.7 GB and remains external evidence.
- `/home/klz/Data` had about 1.4 TB free when this plan was drafted.

Budget 150-300 GB per model (450-900 GB total), with at least 20% filesystem
headroom before each launch.

| Model | Baseline estimate | Ten-round estimate | Total wall time | VRAM planning range | Retained disk |
|---|---:|---:|---:|---:|---:|
| FCNet | 1.5-3 h | 4-8 h | **6-11 h** | 8-12 GB; validate warmup | 150-300 GB |
| WaveNet | 2-2.5 h | 2-5 h | **4-8 h** | under 10 GB target | 150-250 GB |
| PUNet | 2-3 h | 5-9 h | **7-12 h** | 10-20 GB; validate batch-1 warmup | 150-300 GB |

Sequential total is approximately 17-31 GPU-hours and 17-31 hours wall time,
excluding infrastructure recovery.

The tuner nominally performs one planner and one reflector call per round: 20
calls/model, 60 total, plus retries. Reserve 0.3-1.2 million aggregate tokens
as a planning envelope. Insert current provider pricing and an operator-approved
currency/token ceiling immediately before launch; capture actual prompt,
completion, and cached tokens after each model. Baseline training has no LLM
cost.

## 12. Success criteria and post-run analysis

### 12.1 Model success criteria

A model campaign succeeds only when:

- The comparison process exits zero.
- Exactly one generalist baseline and ten completed tuner rounds exist.
- Every baseline/round has deterministic artifacts and complete provenance.
- Every configured gate ran after every experiment or recorded explicit
  `not_run`/`error` state.
- Every resolved observe-mode action is `continue`.
- Every gate and recording metric is persisted in typed JSON.
- `completed_rounds == 10`; gate failures counted, infrastructure failures did
  not.
- Baseline and round outputs were retained.
- The completeness validator passes the baseline, rounds 1-10, and summary.

### 12.2 Anomalies to report

- Any `invalidate_round`, skip, abort, or non-`continue` action.
- Missing gate/check result, metric, provenance, or threshold metadata.
- `not_run`/`error` classified as model collapse.
- Missing/duplicated round index or attempt error substituted for a round.
- Null scalar on `success` without a structured invalid-score explanation.
- Aggregate verdict not reproducible from per-file values.
- JSON-encoded strings used where the typed contract requires mappings.
- Custom-loss registry error despite built-in-only constraint.
- CUDA Xid/OOM, driver reset, truncated HDF5, stale output, or disk breach.

### 12.3 Analysis targets

For each model and jointly:

1. Summarize `pearson_dispersion`, spectral peak ratio, and per-file output std
   with count/min/q25/median/q75/max/mean/std and missing/error counts.
2. Recompute which experiments would have been invalidated by the frozen
   production policy.
3. Plot per-file diversity, std, dominant-mode fraction, spectral ratio, and
   Pearson trajectories, emphasizing files 3, 10, and 17.
4. Compare against healthy FCNet, collapsed WaveNet, agent_012, class-127, and
   known `5.5763`/`6.3556` phantom evidence from
   `reports/health_metrics_scan.md` and prior diagnostics.
5. Identify candidate false positives/negatives by model family and frequency
   region without changing thresholds during the campaign.
6. Verify planner memory included prior failed observe-only gates and whether
   later proposals responded.
7. Propose production threshold/policy changes only in a separate reviewed
   document after all three analyses complete.

## 13. Launch-day checklist

### 13.1 Shared preflight

- [ ] Operator approved the final plan.
- [ ] Intended merged master SHA and dirty-tree state captured.
- [ ] Project interpreter is `/home/yuema137/SIDERIUS/.venv/bin/python`.
- [ ] Threshold review finalized, evidence recomputed, decisions explicit.
- [ ] Observe-mode YAML frozen, validated, and hashed.
- [ ] Alternate HealthGate-config wiring is implemented and tested.
- [ ] Baseline and every-round `after_round: every` coverage is tested.
- [ ] Every pass/fail action resolves to `continue` in observe mode.
- [ ] Full typed gate/per-file/aggregate metrics persist without nested JSON
      strings.
- [ ] Recording metrics include raw per-file values and required statistics.
- [ ] Run-specific baseline workspace and deterministic artifact manifest work.
- [ ] Historical baseline locations are excluded from Phase 1 discovery.
- [ ] Fresh-run test trains Phase 1; matching same-campaign resume test reuses
      it without calling training.
- [ ] Mismatched/incomplete Phase 1 test reports validation failures and
      retrains; missing-output test regenerates inference without retraining.
- [ ] Built-in-loss constraint reaches the tuner through validated input.
- [ ] Completeness validator passes a mock baseline and mock round.
- [ ] New run root is empty; prior evidence remains untouched.
- [ ] `nvidia-smi` and CUDA tensor allocation pass; no stale compute process.
- [ ] Dataset, anchor-map, advice, threshold-review, and YAML hashes captured.
- [ ] Disk budget plus 20% headroom is available.
- [ ] Dry-run validates metadata, paths, gate execution, persistence, and no
      cleanup.
- [ ] Exact command and environment saved before launch.

### 13.2 Per-model checklist

For FCNet, then WaveNet, then PUNet:

- [ ] Confirm one unified checkpoint target and training files 0-19.
- [ ] Confirm the model-specific validated config from Section 3.2.
- [ ] Confirm baseline inference/scoring scope covers validation files 0-19.
- [ ] Confirm every baseline gate result and recording metric persisted.
- [ ] Confirm each completed round produced one checkpoint and deterministic
      record/artifact directory.
- [ ] Confirm failed gates remained `continue` and incremented completed rounds.
- [ ] Confirm exactly ten tuner rounds and a valid run summary.
- [ ] Run completeness validator before launching the next model.

For PUNet, repeat host-level GPU/CUDA health checks immediately before launch
because the prior diagnostic inference encountered an Xid/launch-timeout.

## 14. Recovery and rollback

On an infrastructure blocker, stop new subprocesses, preserve all existing
records and logs, and write a structured infrastructure event. Capture
`nvidia-smi`, CUDA tensor test, disk usage, last record, checkpoint hash, and
HDF5 inventory.

Resume only from the next missing completed experiment when persisted history
passes validation. Reuse an output only when checkpoint hash, file index, HDF5
shape/readability, inventory ID/hash, and write-completion evidence all match.
Otherwise rerun only the incomplete attempt from its checkpoint. Never rerun a
completed experiment solely because an observe-mode check failed.

If a threshold appears wrong, do not change it mid-campaign. Continue observing
unless the gate crashes, loses records, or violates `continue` routing. A
policy/threshold change requires a new reviewed YAML and new campaign identity.

## 15. Target command template — not executable until prerequisites close

After the alternate-config and run-specific-baseline interfaces are implemented
and tested, the intended command shape is:

```bash
/home/yuema137/SIDERIUS/.venv/bin/python scripts/run_comparison.py \
    --model <wavenet|punet|fcnet> \
    --provider openai --model_id gpt-5.5 \
    --reflect_provider openai --reflect_model_id gpt-5.5 \
    --max_rounds 10 \
    --max_epochs 1 \
    --trial_time_budget_minutes 20 \
    --formal_time_budget_minutes 120 \
    --formal_strategy snapshot \
    --formal_portion 0.1 \
    --formal_train_portion 1.0 \
    --run_name v17_pregate_baseline \
    --is_trial \
    --progress_bar \
    --human_advice_file advice/workflow/<tuner_builtin_loss_advice>.json \
    --health_checks_config configs/health_checks_baseline_observe_mode.yaml \
    --baseline_workspace /home/klz/Data/SIDEREIS_DATA/<model>/v17_pregate_baseline/baseline \
    --resume
```

Do not include `--cleanup_denoised`. The last two flags are proposed interfaces
and do not exist in the audited runner today. Do not execute this template until
`--help`, targeted tests, dry-run, threshold freeze, and completeness validation
all pass.

`--resume` is opt-in and valid only for the same campaign root. On a first
execution it has no baseline to reuse and therefore trains Phase 1. On a
relaunch it permits validated Phase 1 and completed-round recovery. Omitting
the new optional flags preserves existing runner behavior.

## 16. Minimal implementation change map

Do not replace or substantially rewrite `scripts/run_comparison.py`. Keep its
Phase 1 -> seed memory -> tuner -> formal -> summary flow and make only these
narrow extensions:

| Requirement | Existing code path to reuse | Minimal required change | Focused tests |
|---|---|---|---|
| Alternate HealthGate config | `load_health_gates_config(path)` and existing gate runner | Optional typed/CLI path forwarded to baseline and tuner | Explicit path loads observe YAML; omission loads default |
| Baseline HealthGate | Existing baseline score/vector/HDF5 plus tuner gate evaluation | Extract smallest shared evaluation/persistence adapter; call after baseline score | Baseline has every configured result; no duplicate calculation |
| Full typed gate persistence | `GateResult`, `HealthCheckResult`, `ExperimentRecord`, `LocalRecorder` | Add typed persisted models/field and adapter, preserving compatibility where needed | Typed per-file/aggregate/recording metrics round-trip |
| Campaign Phase 1 workspace | Existing `baseline_workspace` variable/cache lookup | Optional `--baseline_workspace`; default unchanged | Campaign isolation and default-path compatibility |
| Same-campaign Phase 1 reuse | Existing Phase 1 functions and summary | Validate manifest/config/inventory/checkpoint/output/score/gates before skip | Fresh trains; valid reuses; historical/mismatch retrains |
| Resume rounds | Existing summary/history and tuner loop | Optional `--resume`; initialize from unique validated completed rounds | Continue at next missing round without duplication |
| Record completeness | Existing typed record/storage | Small validator used after baseline and each model | Required success/failure fixtures |
| Observe routing | Existing resolver plus campaign YAML | Pass/fail `continue`; persist production counterfactual | Failures complete rounds and never increment infra failures |
| Artifact discovery | Existing sandbox/recorder paths | Write manifest mapping authoritative paths; no storage framework | Every required artifact resolves deterministically |

Implementation rules:

- Optional fields preserve all existing defaults when omitted.
- Reuse baseline training, inference, scoring, recorder, retry, metadata, tuner,
  and summary code; do not create a parallel runner or baseline pipeline.
- Baseline and tuner call the same shared HealthGate adapter.
- Prefer small helpers over main-flow restructuring.
- No unrelated renames, directory migration, or stylistic refactor.
- Every changed behavior maps to a campaign requirement and focused test.
- If an implementation requires replacing a large portion of the runner, stop
  and find a smaller extension point.

## 17. Required focused tests

Before launch, prove:

1. No campaign Phase 1 artifact -> baseline training runs.
2. Complete matching same-campaign Phase 1 -> baseline is reused.
3. Historical baseline outside campaign root -> never reused.
4. Mismatched/incomplete campaign Phase 1 -> rejected and retrained with exact
   validation failures.
5. Reuse does not invoke baseline training.
6. Missing inference outputs may be regenerated from a validated checkpoint
   without retraining.
7. Alternate observe-mode YAML is actually loaded.
8. Baseline and every completed round persist full typed gate results.
9. Every gate pass/fail branch resolves to `continue`.
10. Omitting new optional arguments preserves existing runner behavior.
11. Manifest resolves baseline and round artifacts deterministically.
12. Completeness validator covers scalar/invalid result, vector/absence,
    gates/status/actions/metrics, files `[3,10,17]`, recording metrics,
    provenance, null-success explanation, and aggregate recomputation.

## 18. Remaining operational decisions

Training topology is final and has no open decision. The operator must still
approve before launch:

1. Final threshold-review dispositions and the frozen YAML hash.
2. Tuner-compatible built-in-loss enforcement mechanism while M7 remains open.
3. Provider/model availability, token ceiling, and current monetary budget.
4. Whether to retain checkpoints from failed attempts in addition to all
   baseline/completed-round checkpoints and attempt records.
5. Whether current 3-trial/5-formal retry budgets are acceptable for the disk
   and wall-time envelope.

The operator approved the finalized policy on 2026-07-16. Shared preflight,
threshold freeze, observe-only routing, CUDA allocation, dataset inventory,
disk capacity, and continuation tests passed before the FCNet launch.
