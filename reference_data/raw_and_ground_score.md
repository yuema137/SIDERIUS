# Raw baseline and ground-truth reference — Option B, global s_max

**Scoring convention:** Option B (`TS.astype(np.float64)` before `np.fft.rfft`),
TIDMAD `round(·, 2) + 1e-10` before `log_{5.27}`, **global s_max** from the
anchor map. Model, baseline, and ceiling all live on one ruler and are
directly comparable at every index.

- **Anchor map:** `{TIDMAD_DATA_DIR}/segment_anchors.json`
- **Global s_max:** `295_715_680.1425` (identical across all 41 reference JSONs)
- **Raw baseline JSONs:** `{SIDERIUS_DATA_DIR}/raw_baseline/raw_baseline_score_file_XXXX.json`
- **Ground-truth JSONs:** `{SIDERIUS_DATA_DIR}/ground_truth/ground_truth_score_file_XXXX.json`
- **Scalar baseline:** `{SIDERIUS_DATA_DIR}/raw_baseline/scalar_anchor_normalized.json`
- **Scalar ceiling:** `{SIDERIUS_DATA_DIR}/ground_truth/ceiling_anchor_normalized.json`
- **Generators:** `compute_raw_baseline.py`, `compute_ground_truth.py`
- **Regenerated:** 2026-04-21

## Per-file scores (all under global s_max)

```
per_segment  = (snr_sg_fi / s_max_GLOBAL) · snr_squid_fi            # snr_squid = raw CH1 for baseline, = CH2 anchor for ceiling
per_file_lin = mean_i(per_segment)                                  # n = 200 (fine)
per_file_log = log_{5.27}(round(per_file_lin, 2) + 1e-10)
```

| file | raw_baseline | ground_truth | headroom (gt − raw) |
|-----:|-------------:|-------------:|--------------------:|
|    0 |     −13.8540 |     −13.8540 |               0.0000 |
|    1 |     −13.8540 |     −13.8540 |               0.0000 |
|    2 |     −13.8540 |     −13.8540 |               0.0000 |
|    3 |     −13.8540 |       0.0945 |              13.9485 |
|    4 |      −2.7708 |       4.9414 |               7.7122 |
|    5 |      −1.8025 |       7.4617 |               9.2641 |
|    6 |      −0.4804 |       6.5623 |               7.0427 |
|    7 |      −0.0060 |       6.9212 |               6.9272 |
|    8 |       0.2976 |       7.7324 |               7.4347 |
|    9 |       0.4717 |       8.1803 |               7.7086 |
|   10 |       0.6749 |       8.6519 |               7.9770 |
|   11 |      −0.0634 |       8.8088 |               8.8722 |
|   12 |       0.3603 |      10.1165 |               9.7562 |
|   13 |       1.3153 |       9.7085 |               8.3932 |
|   14 |       1.6727 |      10.1949 |               8.5222 |
|   15 |       1.5109 |      10.3205 |               8.8095 |
|   16 |       1.5428 |      10.7090 |               9.1662 |
|   17 |       1.8327 |      11.2213 |               9.3886 |
|   18 |       1.7313 |      11.0215 |               9.2902 |
|   19 |       1.0023 |      10.5676 |               9.5654 |

**Reading the table.** Files 0–2 clip both baseline and ceiling to the
`log_{5.27}(1e-10) = −13.854` floor — the CH2 signal is so small at those
injection levels that `(anchor / s_max) · anchor` rounds to 0 at 2 dp even
under the perfect-denoiser substitution. File 3 is the first file where the
ceiling lifts off the floor; the baseline catches up a couple of files later
as the raw SQUID channel starts to carry recoverable signal above the round
threshold. Headroom (gt − raw) grows monotonically past that point because
the perfect denoiser benefits more from increasing injection than the
unfiltered CH1 does.

## Aggregated scalar

Anchor-normalized grand mean — **not** the arithmetic mean of the per-file
log-space scores above.

```
per_segment  = (snr_sg[f][i] / s_max) · snr_squid[f][i]             # or anchor[f][i]² / s_max for the ceiling
grand_mean   = ( Σ_f Σ_i per_segment ) / ( Σ_f |S_f| )               # |S_f| = 200 per file
scalar_score = log_{5.27}(round(grand_mean, 2) + 1e-10)
```

| metric                         | scalar_score | source                                                   |
|--------------------------------|-------------:|----------------------------------------------------------|
| ground-truth ceiling           |      10.1134 | `ground_truth/ceiling_anchor_normalized.json`            |
| raw baseline (grand mean)      |       1.0011 | `raw_baseline/scalar_anchor_normalized.json`             |
| headroom (ceiling − baseline)  |       9.1123 | derived                                                   |

Both scalars are computed by the same anchor-normalized grand-mean path —
`compute_raw_baseline._maybe_write_anchor_normalized_scalar` and
`compute_ground_truth._anchor_normalized_ceiling` are symmetric aggregators
that sum `linear_sum` and `n_segments` across the 20 fine files before the
TIDMAD `round(·, 2) + 1e-10` and `log_{5.27}`. The production scorer
`execute_tools.scoring_utils.score_vector` uses this exact same grand-mean
path for model evaluations, so the three numbers sit on one ruler.

Under trial-mode non-uniform sampling (`|S_f|` differs across files), the
grand mean does not equal `mean_f(per_file_log)` — which is why averaging
the per-file log scores is misleading and not shown here.

See `docs/align_denoising_score.md` §4 and §C.2 for the full derivation.
