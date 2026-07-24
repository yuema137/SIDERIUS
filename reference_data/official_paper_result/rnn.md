# TIDMAD official band-split RNN

## Headline

**Canonical `denoising_score` = 1.505558**  
(log base 5.27; raw-baseline floor = 1.0007, ground-truth ceiling = 10.1134)

Definition (from `execute_tools/scoring_utils.py` §3):

```
denoising_score = log_5.27( Σ_(f,i) per_segment[f,i] / Σ_f |S_f| )
```

Grand mean over every sampled segment across every sampled file, then log. **Per-band or per-subset aggregates are NOT reported** — they are not comparable to this scalar and averaging them is not a valid substitute (see §3 for the three excluded patterns).

## Run configuration

- Full scope: **True** (files [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
- Segment size: 40,000 samples
- Batch size: 250
- Device: `cuda:0`
- s_max: 295715680.142483 (canonical `segment_anchors.json`)
- Inference wall time: 133.9 min (8036 s)
- Computed at: 2026-07-23 23:50:38

## Per-file breakdown

`linear` = `file_vector_linear[f]` = `mean_i(per_segment[f,i])` (200 segments/file). `log` = `log_5.27(linear)`. These are the atomic diagnostic values — not aggregated in any way.

| file | checkpoint | inference (s) | linear | log_5.27 |
|-----:|:-----------|--------------:|-------:|---------:|
| 0000 | `RNN_0_4.pth` | 357.2 | — | — |
| 0001 | `RNN_0_4.pth` | 364.3 | — | — |
| 0002 | `RNN_0_4.pth` | 362.0 | — | — |
| 0003 | `RNN_0_4.pth` | 359.5 | — | — |
| 0004 | `RNN_4_10.pth` | 367.4 | 3.7024e-03 | -3.3686 |
| 0005 | `RNN_4_10.pth` | 367.4 | 6.7371e-02 | -1.6230 |
| 0006 | `RNN_4_10.pth` | 369.1 | 1.0332e-01 | -1.3658 |
| 0007 | `RNN_4_10.pth` | 366.4 | 9.6730e-02 | -1.4054 |
| 0008 | `RNN_4_10.pth` | 364.3 | 4.1418e-01 | -0.5303 |
| 0009 | `RNN_4_10.pth` | 373.5 | 7.6888e-01 | -0.1581 |
| 0010 | `RNN_10_15.pth` | 791.7 | 1.6052e+01 | 1.6701 |
| 0011 | `RNN_10_15.pth` | 373.0 | 1.8834e+01 | 1.7663 |
| 0012 | `RNN_10_15.pth` | 389.3 | 5.0735e+01 | 2.3625 |
| 0013 | `RNN_10_15.pth` | 415.6 | 3.2434e+01 | 2.0934 |
| 0014 | `RNN_10_15.pth` | 370.4 | 5.4954e+01 | 2.4106 |
| 0015 | `RNN_15_20.pth` | 400.9 | 7.8191e+00 | 1.2374 |
| 0016 | `RNN_15_20.pth` | 398.7 | 7.6793e+00 | 1.2265 |
| 0017 | `RNN_15_20.pth` | 366.7 | 6.9318e+00 | 1.1649 |
| 0018 | `RNN_15_20.pth` | 367.0 | 1.1004e+00 | 0.0576 |
| 0019 | `RNN_15_20.pth` | 511.4 | 9.5640e-02 | -1.4122 |

## Reproducibility

```bash
scripts/score_tidmad_official_banded.py --models rnn \
  --data-dir /workspace/DATA/TIDMAD_DATA \
  --work-dir /workspace/DATA/SIDERIUS_DATA/tidmad_official_banded
```

Source summary JSON: `/workspace/DATA/TIDMAD_DATA` (raw inputs), `tidmad_official_rnn_banded_score.json` (this run's outputs).
