# Paper-Quality vs Collapse Reference Baselines

- **Status**: active
- **Scope**: task-specific (TIDMAD forensic reference)
- **Owner**: TBD
- **Created**: 2026-07-16
- **Related**:
  - [`docs/design/m8_gate_coverage_and_diversity_metrics_execution_plan.md`](./m8_gate_coverage_and_diversity_metrics_execution_plan.md)
  - [`docs/design/tidmad_collapse_advice_and_forensics.md`](./tidmad_collapse_advice_and_forensics.md)
  - [experiment reports/health_metrics_scan.md](https://github.com/Galileo-Sandbox/siderius-exp/blob/e9e5063b/provenance/legacy_siderius/p0_03c1/reports/health_metrics_scan.md) — full scan methodology and raw log

## 1. Purpose

Empirical reference for what different points on the "real learning ↔ collapse" spectrum look like on TIDMAD validation data, across all 20 files. Used to calibrate M8 collapse-detection thresholds and as a permanent comparison basis for V17 and future runs.

Three baselines are held simultaneously so a future model's health can be classified into a regime instead of just pass/fail:

| Regime | Reference | Files | Signature |
|--------|-----------|-------|-----------|
| **Real learning** | FCNet paper reproduction | 0-19 (all 20) | `unique_int8` ≥ 52, `std_mv` ≥ 2.0, `mode_fraction` ≤ 6% |
| **Trained-but-collapsed** | Paper-spec wavenet baseline `1784177030` (short focal training) | 0-19 (all 20) | `unique_int8` ∈ [9, 15], `std_mv` ∈ [0.08, 0.20], `mode_fraction` ≥ 99.4% |
| **Near-constant tuning winner** | `agent_012` (round 7 of `diagnostic_baseline_pre_v17`, HG "passed", score +1.05) | 12-19 (formal set only; files 0-11 were not scored) | `unique_int8` = 2, `std_mv` ≈ 0.008, `mode_fraction` ≈ 99.99% |

Compare a new run's per-file distribution against these three columns. If it lands to the left of FCNet on any diversity metric, it belongs in the "learning" regime; if it lands to the right of the paper-spec baseline, it is "trained-but-collapsed"; if it lands at agent_012's numbers, it is a "near-constant phantom" (the 6.3556-family failure mode).

## 2. Source data

### 2.1 FCNet paper reproduction (real learning)

- **Model files**: paper's `FCNet_0_4.pth`, `FCNet_4_10.pth`, `FCNet_10_15.pth`, `FCNet_15_20.pth`
- **Original archive**: https://drive.google.com/drive/folders/16ORX1b2zo1_lOYYAcRBgddBuYImj0Bxs (downloaded 2026-07-16)
- **Local mirror**: `/home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/paper_models_archive/` (5.7 GB; includes PUNet ×4, RNN ×4, Transformer ×4, WaveNet ×1 for future extensions)
- **Inference recipe**: verbatim from paper's `/home/tidmad/TIDMAD/inference.py:80-128` — `input_size=40000`, `batchsize=25`, `input_seq.float()` (no +128 shift at inference), `np.int8(output_seq - 128).flatten()`. See `reports/health_metrics_scan.md` §1.2 for the full recipe.
- **Denoised outputs**: `/home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/fcnet/full_20_files/` (20 files × ~4 GB each = 75 GB; canonical location, do not delete)
- **Wall time**: ~22 s/file on RTX 5090; 5.7 min total for the 15 new files

### 2.2 Paper-spec wavenet baseline (trained-but-collapsed)

- **exp_id**: `1784177030`
- **Location**: `/home/klz/Data/SIDEREIS_DATA/wavenet/diagnostic_baseline_pre_v17_baseline_trial/`
- **Config**: paper-spec (focal, alpha=0.5, gamma=2.0, Adam lr=5e-4, 1 epoch)
- **Diagnostic verdict** (`diagnostic_summary.json`): `status: failed_mode_collapse`, `scalar_score: -2.973`
- **Character**: the run that motivated the whole M8 investigation. Producing not-quite-constant output (9-15 unique values per file) but tightly clustered around a mode at 99.4-99.7%. This is what a normally-trained wavenet does when it collapses onto a signal-independent output.

### 2.3 agent_012 (near-constant tuning winner)

- **exp_id**: `wavenet_diagnostic_baseline_pre_v17_agent_012`
- **Round**: 7 of `diagnostic_baseline_pre_v17` chain (out of 10)
- **Location**: `/home/klz/Data/SIDEREIS_DATA/wavenet/diagnostic_baseline_pre_v17/agent/abra_validation_denoised_wavenet_diagnostic_baseline_pre_v17_agent_wavenet_diagnostic_baseline_pre_v17_agent_012_00{12..19}.h5`
- **Config**: 32/64/32 WaveNet with k=12, 10 blocks, focal_cw (α=0.5, γ=1.5, class_weights=True), AdamW lr=3e-4, batch 16
- **Tuner verdict**: `status: success`, `denoising_score: 1.0506`, `gate_action: continue`, `failure_reason: null`, `healthgate_result: passed` (per `build_diagnostic_summary.py`'s pre-M8 inference)
- **Reality**: **collapsed** — 99.99% of samples equal int8=-65, 0.007% at int8=-68. **Two unique values across all files 12-19.** Only "scored well" because SNR-at-peak on a mostly-constant PSD is a deterministic FP artifact (6.3556-family phantom). This IS the case that motivated the round-7 coverage gap fix.
- **File coverage**: files 12-19 only. Files 0-11 have no denoised outputs in this run (formal_portion selected only files 12-19 for scoring). **All metrics below are computed on files 12-19 exclusively.**

## 3. Per-file scan — three-way (peek 1M samples, mV = int8 × 40/128)

| file | target_std_mv | | FCNet uniq | FCNet std_mv | FCNet mode% | FCNet pearson | | Baseline uniq | Baseline std_mv | Baseline mode% | Baseline pearson | | agent_012 uniq | agent_012 std_mv | agent_012 mode% | agent_012 pearson |
|------|---------------|-|------------|--------------|-------------|---------------|-|---------------|-----------------|----------------|------------------|-|----------------|------------------|-----------------|--------------------|
| 0  | 0.2797 | | 103 | 3.9845 | 2.98% | -0.0062 | | 14 | 0.0948 | 99.71% | +0.0040 | | — | — | — | — |
| 1  | 0.2519 | |  61 | 2.3364 | 5.07% | -0.0080 | | 14 | 0.1265 | 99.47% | +0.0040 | | — | — | — | — |
| 2  | 0.2483 | |  56 | 2.1471 | 5.51% | -0.0073 | | 11 | 0.1358 | 99.41% | +0.0052 | | — | — | — | — |
| 3  | 0.2465 | |  52 | 2.0120 | 5.89% | -0.0106 | | 10 | 0.1179 | 99.40% | -0.0004 | | — | — | — | — |
| 4  | 0.4067 | |  81 | 2.8646 | 4.37% | -0.0082 | |  9 | 0.0930 | 99.60% | +0.0019 | | — | — | — | — |
| 5  | 1.4920 | |  75 | 2.8185 | 4.39% | -0.0032 | | 10 | 0.0957 | 99.65% | +0.0033 | | — | — | — | — |
| 6  | 2.8800 | |  79 | 2.8926 | 4.28% | +0.0035 | |  9 | 0.0885 | 99.66% | -0.0005 | | — | — | — | — |
| 7  | 2.1819 | |  77 | 2.7046 | 4.64% | +0.0107 | |  9 | 0.0927 | 99.63% | +0.0028 | | — | — | — | — |
| 8  | 3.0597 | |  79 | 3.0024 | 4.06% | +0.0062 | |  9 | 0.0830 | 99.65% | -0.0006 | | — | — | — | — |
| 9  | 3.9596 | |  80 | 2.9465 | 4.23% | -0.0049 | | 10 | 0.0788 | 99.69% | +0.0025 | | — | — | — | — |
| 10 | 4.9220 | | 127 | 7.3568 | 3.15% | +0.0001 | | 13 | 0.1135 | 99.66% | +0.0027 | | — | — | — | — |
| 11 | 5.7752 | | 128 | 7.3551 | 3.16% | +0.0026 | | 12 | 0.1478 | 99.51% | +0.0025 | | — | — | — | — |
| 12 | 8.8355 | | 127 | 7.3563 | 3.15% | -0.0028 | |  9 | 0.0961 | 99.49% | -0.0004 | | 2 | 0.0080 | 99.99% | +0.0107 |
| 13 | 13.4090 | | 128 | 7.3561 | 3.15% | +0.0268 | | 15 | 0.1918 | 99.67% | +0.0001 | | 2 | 0.0082 | 99.99% | +0.0024 |
| 14 | 15.1687 | | 127 | 7.3524 | 3.18% | +0.0846 | | 10 | 0.0895 | 99.71% | +0.0006 | | 2 | 0.0075 | 99.99% | -0.0094 |
| 15 | 15.9695 | | 156 | 7.5132 | 2.72% | -0.0039 | | 12 | 0.0851 | 99.62% | +0.0003 | | 2 | 0.0079 | 99.99% | +0.0099 |
| 16 | 16.2988 | | 151 | 7.2231 | 2.65% | +0.0069 | |  9 | 0.0766 | 99.74% | -0.0015 | | 2 | 0.0080 | 99.99% | +0.0070 |
| 17 | 16.4617 | | 143 | 7.0802 | 2.68% | +0.0002 | | 10 | 0.0914 | 99.66% | -0.0015 | | 2 | 0.0082 | 99.99% | -0.0048 |
| 18 | 16.4874 | | 159 | 7.7977 | 2.72% | -0.0553 | |  9 | 0.0865 | 99.64% | -0.0012 | | 2 | 0.0082 | 99.99% | +0.0057 |
| 19 | 16.4283 | | 153 | 7.4428 | 2.66% | -0.1828 | | 14 | 0.1897 | 99.72% | +0.0004 | | 2 | 0.0083 | 99.99% | +0.0019 |

*"agent_012" column blank on files 0-11: the round-7 formal set only scored files 12-19; no denoised outputs exist for the lower band.*

## 4. Aggregate statistics

### 4.1 Diversity + std + mode

| Metric | FCNet (n=20) | Baseline (n=20) | agent_012 (n=8, files 12-19) |
|--------|--------------|-----------------|-------------------------------|
| `unique_int8` — min | **52** (file 3) | 9 | 2 |
| `unique_int8` — median | 115 | 10 | 2 |
| `unique_int8` — max | 159 (file 18) | **15** (file 13) | 2 |
| `unique_int8` — mean | 107.1 | 10.9 | 2 |
| `std_mv` — min | **2.01** (file 3) | 0.077 | 0.0075 |
| `std_mv` — median | 5.53 | 0.094 | 0.0081 |
| `std_mv` — max | 7.80 (file 18) | **0.192** (file 13) | 0.0083 |
| `std_mv` — mean | 5.08 | 0.109 | 0.0080 |
| `mode_fraction` — min | 0.026 | 0.994 | 0.9999 |
| `mode_fraction` — median | 0.032 | 0.997 | 0.9999 |
| `mode_fraction` — max | 0.059 | 0.997 | 0.9999 |

### 4.2 Pearson (time-domain vs CH2)

| Metric | FCNet (n=20) | Baseline (n=20) | agent_012 (n=8) |
|--------|--------------|-----------------|-------------------|
| `pearson` — min | -0.183 (file 19) | -0.002 | -0.0094 |
| `pearson` — median | -0.003 | +0.0005 | +0.0038 |
| `pearson` — max | +0.085 (file 14) | +0.005 | +0.0107 |
| `pearson` — mean | -0.008 | +0.001 | +0.0029 |
| **`pearson_dispersion` (stdev)** | **0.0480** | **0.0020** | **0.0070** |

### 4.3 Discrimination ratios

| Comparison | Metric | Ratio | Interpretation |
|------------|--------|-------|----------------|
| FCNet vs Baseline | `unique_int8` (min/max) | **3.5×** | Direct diversity gap |
| FCNet vs Baseline | `std_mv` (min/max) | **10.5×** | Amplitude gap |
| FCNet vs Baseline | `mode_fraction` (max/min) | **~38×** (baseline / FCNet) | Single-value dominance — strongest single-metric discriminator |
| FCNet vs Baseline | `pearson_dispersion` | **24×** (0.048 / 0.002) | Recording metric — see §6.3 |
| FCNet vs agent_012 | `unique_int8` | **26×** (min 52 / max 2) | Near-constant regime is very distinct |
| FCNet vs agent_012 | `std_mv` | **268×** (min 2.01 / max 0.008) | " |
| Baseline vs agent_012 | `unique_int8` | **4.5×** (min 9 / max 2) | Two collapse regimes are still distinct |

## 5. Aggregate discussion

- **`mode_fraction` is the strongest single discriminator.** FCNet's max is 5.89%; both collapse regimes are ≥99.4%. The existing `amplitude_collapse` gate (threshold 0.95) exploits this — FCNet is 16× below threshold, both collapse regimes are 1.05× above → **1000× gap in relative terms**.
- **`unique_int8` and `std_mv` are corroborating checks.** They provide independent signal and would catch a hypothetical failure mode where an output has moderate mode_fraction (~90%) but very few unique values. Neither of the observed collapse cases test that regime, so they're insurance rather than primary detection.
- **Time-domain `pearson` per-file is noise-limited** on files 0-9 for all three regimes and can produce sign-inverted values even for real learning (file 19 shows FCNet pearson = -0.18). It is **not** a useful per-file discriminator.
- **`pearson_dispersion` (stdev across per-file pearsons)** does discriminate meaningfully: FCNet 0.048 vs baseline 0.002 (**24× ratio**). This is a modest signal — worth recording, not sufficient as a primary defense. See §6.3.

## 6. Implications for M8

### 6.1 `unique_int8` threshold

Chosen: **`min_unique_int8_values: 25`**.

| Threshold | FCNet safety (min 52) | Baseline rejection (max 15) | agent_012 rejection (max 2) |
|-----------|-----------------------|-----------------------------|------------------------------|
| 25 | **2.08×** (strict 2×) | 40% distance above | 12.5× rejection |
| 30 (rejected) | 1.73× | 100% distance above | 15× rejection |

Rationale for 25 over 30: V17 models may be lower quality than FCNet; wider FCNet margin protects edge cases. Baseline max (15) still cleanly rejects at 40% headroom.

### 6.2 `output_std` threshold

Chosen: **`min_std_mv: 1.0`**.

- FCNet safety: 2.01× (min 2.01 mV)
- Baseline rejection: 5.21× (max 0.192 mV)
- agent_012 rejection: 133× (max 0.0083 mV)

Comfortable across the board.

### 6.3 `pearson_dispersion_recording`

**Kept**, replacing the earlier per-file `pearson_correlation_recording` design.

Metric definition (canonical): `pearson_dispersion = stdev(per_file_pearsons)` — sample standard deviation (ddof=1) across each round's per-file pearson values.

Recording semantics: internally the check computes per-file pearsons; externally it exposes only:
- `pearson_dispersion` (scalar) — the discriminator
- `pearson_mean`, `pearson_range` — context (not discriminative)
- `n_files_measured`, `n_files_io_failed` — hygiene

Expected ranges (from this scan):
- **Real learning** (FCNet): `pearson_dispersion ≈ 0.05`
- **Trained-but-collapsed** (paper-spec baseline): `pearson_dispersion ≈ 0.002`
- **Near-constant phantom** (agent_012): `pearson_dispersion ≈ 0.007` (files 12-19 only)

The 24× separation between real learning and paper-spec baseline is smaller than the 38× on `mode_fraction`, but pearson_dispersion sees signal correlation directly — a check that adds a fundamentally different perspective, cheap enough to keep even though not on the critical path.

### 6.4 Peek strategy

**Adopted for V17 (M9).** Multi-file peek at `[3, 10, 17]` with `any_pass` aggregation provides robustness across frequency bands without relying on single-file diversity, which the FCNet scan showed varies substantially (unique_int8: 52 on file 3, 143 on file 17). Any_pass semantics: a real learning model passes if any single peeked file shows healthy diversity; collapse fails only when all three peeked files degrade together. See [`docs/design/m9_multi_file_peek_execution_plan.md`](./m9_multi_file_peek_execution_plan.md) for execution details.

Triplet rationale:

- **File 3** — low-freq band, narrowest FCNet safety margin (52 unique). Including the worst-case file in the peek means the gate remains calibrated against the empirical floor.
- **File 10** — first mid-high-signal file (127 unique). Sanity anchor for the mid band.
- **File 17** — high-freq band exemplar (143 unique). Sanity anchor for the high band.

Empty `peek_file_indices` in a check's YAML config still falls back to the pre-M9 single-file `min(denoised_paths)` semantic for backward compat — existing test fixtures and stubs don't need updating.

## 7. Files 0-3 special note

The low-frequency band is the natural weak point for any real-learning model on TIDMAD (least injected DM signal to recover). FCNet's diversity holds (unique 52-103) but the margin is narrowest here. Consequences:

- **A V17 model with lower quality than FCNet will trigger `output_diversity_blocking` on files 0-3 first**, even if the model has real learning on high-signal bands. Do NOT rescue such runs by loosening the M8 threshold — the threshold is calibrated against the paper's best-in-class model, and any regression from that is diagnostic.
- **Time-domain pearson is uninformative on files 0-3** for ALL three regimes (noise-floor magnitude ~10⁻² for FCNet, baseline, and agent_012 alike). Do not attempt to use per-file pearson as a validation metric on these files.
- **The `agent_012` column is blank on files 0-11** because that formal-round only scored files 12-19. This is not an indictment of agent_012's low-band performance — no measurement exists. Future forensic runs should aim to score all 20 files whenever practical to fill this gap.

## 8. Related docs

- [`docs/design/m8_gate_coverage_and_diversity_metrics_execution_plan.md`](./m8_gate_coverage_and_diversity_metrics_execution_plan.md)
- [`docs/design/tidmad_collapse_advice_and_forensics.md`](./tidmad_collapse_advice_and_forensics.md)
- [`docs/design/collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md)
- [experiment reports/health_metrics_scan.md](https://github.com/Galileo-Sandbox/siderius-exp/blob/e9e5063b/provenance/legacy_siderius/p0_03c1/reports/health_metrics_scan.md) — full scan methodology, raw logs, audit trail
- `reports/v16_20260630.md` — earlier v16 forensic (5.5763 phantom); **unpublished** — the v16 report was never committed to the repository.
