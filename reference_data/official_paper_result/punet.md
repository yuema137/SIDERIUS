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
