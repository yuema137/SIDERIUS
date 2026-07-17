# V17 Pre-Gate Baseline Threshold Review

- **Status**: frozen for `v17_pregate_baseline`
- **Scope**: observe-only HealthGate campaign for unified FCNet, WaveNet, and PUNet
- **Owner**: SIDERIUS operators
- **Created**: 2026-07-16
- **Last Updated**: 2026-07-16
- **HealthGate config**: `configs/health_checks_baseline_observe_mode.yaml`
- **HealthGate config SHA-256**: `7b67c8dcbdab7689050cbd30dccb382772a15aed0c58263770357ac84af302b3`
- **Primary evidence**: `reports/health_metrics_scan.md`
- **Evidence SHA-256**: `67ed7f17065350fb808501d9ac9a212f0e73e1ec30bfd565ed7fb0ca2c4b8323`

## Decision

The following policy is frozen before the first FCNet launch. It remains
unchanged through FCNet, WaveNet, and PUNet. All gates are observe-only:
`on_pass=continue`, `on_fail=continue`, and `after_round=every`.

| Gate | Metric | Criterion | Unit | Aggregation / files | Healthy evidence | Collapsed evidence | False-positive risk | False-negative risk | Decision |
|---|---|---|---|---|---|---|---|---|---|
| `output_diversity_blocking` | `n_unique_int8_values` | `> 25` | unique int8 count | `any_pass`, `[3,10,17]`, 100k samples/file | FCNet minimum 52; files 3/10/17 = 52/127/143 | collapsed WaveNet 9–15; agent_012=2; strict constant=1 | A weak but genuine model may remain at or below 25 on all inspected bands | One healthy file can mask partial collapse elsewhere | **retain**; cross-model validation remains provisional |
| `output_std_blocking` | `output_std_mv` | `>= 1.0` | mV | `any_pass`, `[3,10,17]`, 100k samples/file | FCNet minimum 2.012 mV | collapsed WaveNet maximum 0.192 mV; agent_012 about 0.008 mV | Genuine low-amplitude learning may stay below 1 mV | One healthy-amplitude file can mask partial collapse | **retain**; cross-model validation remains provisional |
| `amplitude_collapse_blocking` | `dominant_mode_fraction` | `<= 0.95` | fraction | `any_pass`, `[3,10,17]`, 100k samples/file | FCNet range 0.026–0.059 | collapsed WaveNet 0.994–0.997; class-127 constant=1.0 | Legitimate highly concentrated output could be flagged | One non-collapsed file can mask partial collapse | **retain**; strongest observed discriminator |
| `pearson_dispersion_recording` | sample standard deviation of per-file Pearson values | no threshold | dimensionless | all available validation files, 1M samples/file | FCNet dispersion about 0.048–0.06 | collapsed WaveNet about 0.002; agent_012 about 0.007 | Correlation sign and low-band noise vary in healthy output | Dispersion may be nonzero without learned signal | **provisional recording-only** |
| `spectral_peak_ratio_recording` | signal-window/noise-window PSD ratio | no threshold; noise `<=1e-10` is numerically invalid | dimensionless | all available validation files, 1M samples/file | No validated campaign-wide healthy distribution | Strict constants are invalid; near constants may remain finite | Real narrowband and peak-selection variation may overlap | Finite near-collapse output may look strong | **provisional recording-only** |
| `per_file_output_std_recording` | per-file output standard deviation | no threshold | mV | all available validation files, 100k samples/file | FCNet 2.012–7.798 mV | collapsed WaveNet 0.077–0.192 mV | A future threshold could penalize legitimate low-amplitude bands | Aggregate summaries can hide individual collapsed files | **provisional recording-only** |

## Evidence and limitations

- Healthy evidence is the archived 20-file official FCNet scan. It is external
  threshold evidence, not a Phase 1 baseline source.
- Collapse evidence includes the one-epoch unified WaveNet diagnostic,
  agent_012, class-127 constant output, and pre-HealthGate phantom-score cases.
- The threshold `25` intentionally gives the weakest healthy FCNet file a
  greater than 2× margin. The dominant-mode check provides substantially wider
  separation and remains the primary collapse signal.
- `any_pass` is deliberately permissive for this observation campaign. Saved
  per-file metrics are authoritative for reconstructing stricter policies.
- Recording-only checks have `threshold: null`; no unvalidated numeric cutoff
  is implied.

## Freeze rule

Changing a threshold, comparison operator, aggregation rule, peek file, or
sample count after the first FCNet launch creates a new campaign identity. No
mid-campaign threshold edits are allowed.
