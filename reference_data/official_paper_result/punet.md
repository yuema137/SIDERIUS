# TIDMAD official band-split PUNet

## Headline

**Canonical `denoising_score` = 3.691752**  
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
- Inference wall time: 54.6 min (3274 s)
- Computed at: 2026-07-23 21:23:42

## Per-file breakdown

`linear` = `file_vector_linear[f]` = `mean_i(per_segment[f,i])` (200 segments/file). `log` = `log_5.27(linear)`. These are the atomic diagnostic values — not aggregated in any way.

| file | checkpoint | inference (s) | linear | log_5.27 |
|-----:|:-----------|--------------:|-------:|---------:|
| 0000 | `PUNet_0_4.pth` | 162.8 | 2.5256e-09 | -11.9112 |
| 0001 | `PUNet_0_4.pth` | 162.2 | 5.5348e-10 | -12.8246 |
| 0002 | `PUNet_0_4.pth` | 160.6 | 4.1543e-08 | -10.2264 |
| 0003 | `PUNet_0_4.pth` | 163.4 | 5.4297e-06 | -7.2945 |
| 0004 | `PUNet_4_10.pth` | 163.4 | 3.8833e-02 | -1.9545 |
| 0005 | `PUNet_4_10.pth` | 164.1 | 2.6849e-01 | -0.7912 |
| 0006 | `PUNet_4_10.pth` | 163.7 | 1.1476e+00 | 0.0828 |
| 0007 | `PUNet_4_10.pth` | 164.3 | 2.3258e+00 | 0.5078 |
| 0008 | `PUNet_4_10.pth` | 164.1 | 4.0409e+00 | 0.8402 |
| 0009 | `PUNet_4_10.pth` | 168.8 | 1.3748e+03 | 4.3477 |
| 0010 | `PUNet_10_15.pth` | 161.4 | 1.7826e-01 | -1.0376 |
| 0011 | `PUNet_10_15.pth` | 160.5 | 7.3587e-01 | -0.1845 |
| 0012 | `PUNet_10_15.pth` | 165.2 | 5.3258e+00 | 1.0063 |
| 0013 | `PUNet_10_15.pth` | 163.3 | 2.5442e+00 | 0.5618 |
| 0014 | `PUNet_10_15.pth` | 170.2 | 2.6776e+01 | 1.9780 |
| 0015 | `PUNet_15_20.pth` | 163.8 | 1.2924e+02 | 2.9252 |
| 0016 | `PUNet_15_20.pth` | 163.4 | 1.8891e+02 | 3.1535 |
| 0017 | `PUNet_15_20.pth` | 166.7 | 1.1098e+03 | 4.2189 |
| 0018 | `PUNet_15_20.pth` | 161.4 | 2.4921e+03 | 4.7056 |
| 0019 | `PUNet_15_20.pth` | 160.4 | 3.9040e+03 | 4.9757 |

## Reproducibility

```bash
scripts/score_tidmad_official_banded.py --models punet \
  --data-dir /workspace/DATA/TIDMAD_DATA \
  --work-dir /workspace/DATA/SIDERIUS_DATA/tidmad_official_banded
```

Source summary JSON: `/workspace/DATA/TIDMAD_DATA` (raw inputs), `tidmad_official_punet_banded_score.json` (this run's outputs).

## HealthGate per-file metrics

Peek window 1,000,000 samples (the reference-table window; production blocking gates peek 100,000). Metric formulas are the production `HealthCheck` classes, imported rather than reimplemented, so a number here means what it means inside a chain.

Thresholds: `unique_int8 > 25`, `std_mv >= 1.0`, `mode_fraction < 0.95`.

**Healthy on 10 of 20 files** (diversity 10/20, std 10/20, amplitude 16/20).

| file | ckpt | target std (mV) | unique_int8 | std (mV) | mode % | pearson | spectral | verdict |
|---:|:---|---:|---:|---:|---:|---:|---:|:---|
| 0000 | `0_4` | 0.2797 | 12 | 0.0756 | 98.01 | +0.2570 | 0.8602 | FAIL (dsa) |
| 0001 | `0_4` | 0.2519 | 12 | 0.0659 | 98.60 | +0.2477 | 0.3977 | FAIL (dsa) |
| 0002 | `0_4` | 0.2483 | 12 | 0.0646 | 98.61 | +0.2428 | 0.2922 | FAIL (dsa) |
| 0003 | `0_4` | 0.2465 | 12 | 0.0559 | 98.94 | +0.0003 | 0.3237 | FAIL (dsa) |
| 0004 | `4_10` | 0.4067 | 9 | 0.9223 | 31.06 | +0.0007 | 2782.4355 | FAIL (dsA) |
| 0005 | `4_10` | 1.4920 | 9 | 0.9221 | 31.02 | +0.0004 | 3144.5751 | FAIL (dsA) |
| 0006 | `4_10` | 2.8800 | 9 | 0.9221 | 31.07 | -0.0031 | 2817.8379 | FAIL (dsA) |
| 0007 | `4_10` | 2.1819 | 9 | 0.9220 | 31.02 | -0.0129 | 3079.9014 | FAIL (dsA) |
| 0008 | `4_10` | 3.0597 | 9 | 0.9222 | 31.05 | -0.0057 | 2859.7434 | FAIL (dsA) |
| 0009 | `4_10` | 3.9596 | 9 | 0.9223 | 31.05 | +0.0357 | 2621.6638 | FAIL (dsA) |
| 0010 | `10_15` | 4.9220 | 53 | 20.5004 | 52.97 | +0.0045 | 44.6810 | PASS (DSA) |
| 0011 | `10_15` | 5.7752 | 51 | 20.4308 | 53.26 | +0.0061 | 40.0377 | PASS (DSA) |
| 0012 | `10_15` | 8.8355 | 50 | 20.4507 | 53.19 | -0.0016 | 36.2570 | PASS (DSA) |
| 0013 | `10_15` | 13.4092 | 51 | 20.4683 | 53.13 | +0.0122 | 42.3077 | PASS (DSA) |
| 0014 | `10_15` | 15.1689 | 51 | 20.4969 | 52.90 | +0.0221 | 38.9549 | PASS (DSA) |
| 0015 | `15_20` | 15.9695 | 93 | 16.1461 | 10.54 | +0.0017 | 77.9629 | PASS (DSA) |
| 0016 | `15_20` | 16.2986 | 95 | 16.1488 | 10.55 | +0.0008 | 76.3168 | PASS (DSA) |
| 0017 | `15_20` | 16.4619 | 99 | 16.1480 | 10.57 | -0.0012 | 80.2790 | PASS (DSA) |
| 0018 | `15_20` | 16.4866 | 95 | 16.1496 | 10.55 | +0.1004 | 79.1367 | PASS (DSA) |
| 0019 | `15_20` | 16.4285 | 95 | 16.1492 | 10.57 | -0.0544 | 80.6220 | PASS (DSA) |

Verdict letters: upper case passed that check (D diversity, S std, A amplitude), lower case failed.

Regenerate:

```bash
python scripts/official_paper_health_scan.py --model punet \
  --denoised-dir /home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/punet/full_20_files \
  --json-out reference_data/official_paper_result/punet_health.json
```
