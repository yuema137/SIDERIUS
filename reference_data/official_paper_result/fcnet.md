# TIDMAD official band-split FCNet

## Headline

**Canonical `denoising_score` = 6.434801**  
(log base 5.27; raw-baseline floor = 1.0007, ground-truth ceiling = 10.1134)

Definition (from `execute_tools/scoring_utils.py` §3):

```
denoising_score = log_5.27( Σ_(f,i) per_segment[f,i] / Σ_f |S_f| )
```

Grand mean over every sampled segment across every sampled file, then log. **Per-band or per-subset aggregates are NOT reported** — they are not comparable to this scalar and averaging them is not a valid substitute (see §3 for the three excluded patterns).

## Run configuration

- Full scope: **True** (files [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
- Segment size: 40,000 samples
- Batch size: 25
- Device: `cuda:0`
- s_max: 295715680.142483 (canonical `segment_anchors.json`)
- Inference wall time: 42.3 min (2538 s)
- Computed at: 2026-07-23 20:15:21

## Per-file breakdown

`linear` = `file_vector_linear[f]` = `mean_i(per_segment[f,i])` (200 segments/file). `log` = `log_5.27(linear)`. These are the atomic diagnostic values — not aggregated in any way.

| file | checkpoint | inference (s) | linear | log_5.27 |
|-----:|:-----------|--------------:|-------:|---------:|
| 0000 | `FCNet_0_4.pth` | 141.4 | 8.3189e-08 | -9.8086 |
| 0001 | `FCNet_0_4.pth` | 121.7 | 1.6348e-08 | -10.7875 |
| 0002 | `FCNet_0_4.pth` | 136.8 | 3.1747e-05 | -6.2320 |
| 0003 | `FCNet_0_4.pth` | 119.4 | 1.5801e-03 | -3.8810 |
| 0004 | `FCNet_4_10.pth` | 123.7 | 9.6483e-02 | -1.4069 |
| 0005 | `FCNet_4_10.pth` | 102.1 | 3.8644e+00 | 0.8133 |
| 0006 | `FCNet_4_10.pth` | 128.3 | 1.5519e+00 | 0.2644 |
| 0007 | `FCNet_4_10.pth` | 124.0 | 3.6465e+00 | 0.7784 |
| 0008 | `FCNet_4_10.pth` | 126.2 | 5.1327e+02 | 3.7549 |
| 0009 | `FCNet_4_10.pth` | 119.9 | 5.1596e+02 | 3.7581 |
| 0010 | `FCNet_10_15.pth` | 123.0 | 3.3017e+02 | 3.4895 |
| 0011 | `FCNet_10_15.pth` | 124.9 | 5.5822e+02 | 3.8054 |
| 0012 | `FCNet_10_15.pth` | 130.4 | 9.0548e+03 | 5.4819 |
| 0013 | `FCNet_10_15.pth` | 129.8 | 4.0258e+04 | 6.3796 |
| 0014 | `FCNet_10_15.pth` | 134.1 | 2.8199e+05 | 7.5508 |
| 0015 | `FCNet_15_20.pth` | 123.9 | 5.8057e+03 | 5.2145 |
| 0016 | `FCNet_15_20.pth` | 124.9 | 1.7259e+03 | 4.4846 |
| 0017 | `FCNet_15_20.pth` | 127.5 | 8.3272e+04 | 6.8169 |
| 0018 | `FCNet_15_20.pth` | 130.1 | 1.5994e+05 | 7.2096 |
| 0019 | `FCNet_15_20.pth` | 145.8 | 2.9857e+05 | 7.5852 |

## Reproducibility

```bash
scripts/score_tidmad_official_banded.py --models fcnet \
  --data-dir /workspace/DATA/TIDMAD_DATA \
  --work-dir /workspace/DATA/SIDERIUS_DATA/tidmad_official_banded
```

Source summary JSON: `/workspace/DATA/TIDMAD_DATA` (raw inputs), `tidmad_official_fcnet_banded_score.json` (this run's outputs).

## HealthGate per-file metrics

Peek window 1,000,000 samples (the reference-table window; production blocking gates peek 100,000). Metric formulas are the production `HealthCheck` classes, imported rather than reimplemented, so a number here means what it means inside a chain.

Thresholds: `unique_int8 > 25`, `std_mv >= 1.0`, `mode_fraction < 0.95`.

**Healthy on 20 of 20 files** (diversity 20/20, std 20/20, amplitude 20/20).

| file | ckpt | target std (mV) | unique_int8 | std (mV) | mode % | pearson | spectral | verdict |
|---:|:---|---:|---:|---:|---:|---:|---:|:---|
| 0000 | `0_4` | 0.2797 | 103 | 3.9845 | 2.98 | -0.0062 | 0.0001 | PASS (DSA) |
| 0001 | `0_4` | 0.2519 | 61 | 2.3364 | 5.07 | -0.0080 | 0.0000 | PASS (DSA) |
| 0002 | `0_4` | 0.2483 | 56 | 2.1471 | 5.51 | -0.0073 | 1.8385 | PASS (DSA) |
| 0003 | `0_4` | 0.2465 | 52 | 2.0120 | 5.89 | -0.0106 | 1.8108 | PASS (DSA) |
| 0004 | `4_10` | 0.4067 | 81 | 2.8646 | 4.37 | -0.0082 | 7.7337 | PASS (DSA) |
| 0005 | `4_10` | 1.4920 | 75 | 2.8185 | 4.39 | -0.0032 | 7.5892 | PASS (DSA) |
| 0006 | `4_10` | 2.8800 | 79 | 2.8926 | 4.28 | +0.0035 | 0.0007 | PASS (DSA) |
| 0007 | `4_10` | 2.1819 | 77 | 2.7046 | 4.64 | +0.0107 | 7.7385 | PASS (DSA) |
| 0008 | `4_10` | 3.0597 | 79 | 3.0024 | 4.06 | +0.0062 | 7.5672 | PASS (DSA) |
| 0009 | `4_10` | 3.9596 | 80 | 2.9465 | 4.23 | -0.0049 | 7.7064 | PASS (DSA) |
| 0010 | `10_15` | 4.9220 | 127 | 7.3568 | 3.15 | +0.0001 | 38690.8068 | PASS (DSA) |
| 0011 | `10_15` | 5.7752 | 128 | 7.3551 | 3.16 | +0.0026 | 38183.3286 | PASS (DSA) |
| 0012 | `10_15` | 8.8355 | 127 | 7.3563 | 3.15 | -0.0028 | 41761.4299 | PASS (DSA) |
| 0013 | `10_15` | 13.4092 | 128 | 7.3561 | 3.15 | +0.0268 | 37222.7004 | PASS (DSA) |
| 0014 | `10_15` | 15.1689 | 127 | 7.3524 | 3.18 | +0.0846 | 38535.8663 | PASS (DSA) |
| 0015 | `15_20` | 15.9695 | 156 | 7.5132 | 2.72 | -0.0039 | 331.7435 | PASS (DSA) |
| 0016 | `15_20` | 16.2986 | 151 | 7.2231 | 2.65 | +0.0069 | 729.0212 | PASS (DSA) |
| 0017 | `15_20` | 16.4619 | 143 | 7.0802 | 2.68 | +0.0002 | 960.4439 | PASS (DSA) |
| 0018 | `15_20` | 16.4866 | 159 | 7.7977 | 2.72 | -0.0553 | 832.4629 | PASS (DSA) |
| 0019 | `15_20` | 16.4285 | 153 | 7.4428 | 2.66 | -0.1828 | 557.9188 | PASS (DSA) |

Verdict letters: upper case passed that check (D diversity, S std, A amplitude), lower case failed.

Regenerate:

```bash
python scripts/official_paper_health_scan.py --model fcnet \
  --denoised-dir /home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/fcnet/full_20_files \
  --json-out reference_data/official_paper_result/fcnet_health.json
```
