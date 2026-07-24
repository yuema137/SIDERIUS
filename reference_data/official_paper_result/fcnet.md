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
