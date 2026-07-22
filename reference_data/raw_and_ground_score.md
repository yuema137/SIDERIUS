# Raw baseline and ground-truth reference — Option B, global s_max

**Scoring convention:** Option B (`TS.astype(np.float64)` before `np.fft.rfft`),
`log_{5.27}(per_file_lin)` over the linear per-file mean — `-inf` when the mean
is `<= 0`. No `+ 1e-10` offset and no `round(·, 2)`: both were outdated and are
removed so this matches `scoring_utils.score_vector` exactly. **Global s_max**
from the anchor map. Model, baseline, and ceiling all live on one ruler and are
directly comparable at every index.

- **Anchor map:** `{TIDMAD_DATA_DIR}/segment_anchors.json`
- **Global s_max:** `295_715_680.1425` (identical across all 41 reference JSONs)
- **Raw baseline JSONs:** `reference_data/raw_baseline/raw_baseline_score_file_XXXX.json`
- **Ground-truth JSONs:** `reference_data/ground_truth/ground_truth_score_file_XXXX.json`
- **Scalar baseline:** `reference_data/raw_baseline/scalar_anchor_normalized.json`
- **Scalar ceiling:** `reference_data/ground_truth/ceiling_anchor_normalized.json`
- **Generators:** `compute_raw_baseline.py`, `compute_ground_truth.py`
- **Regenerated:** 2026-07-22 (removed the outdated `+ 1e-10` offset and `round(·, 2)`)

## Per-file scores (all under global s_max)

```
per_segment  = (snr_sg_fi / s_max_GLOBAL) · snr_squid_fi            # snr_squid = raw CH1 for baseline, = CH2 anchor for ceiling
per_file_lin = mean_i(per_segment)                                  # n = 200 (fine)
per_file_log = log_{5.27}(per_file_lin)                             # -inf if per_file_lin <= 0
```

| file | raw_baseline | ground_truth | headroom (gt − raw) |
|-----:|-------------:|-------------:|--------------------:|
|    0 |     −11.4402 |      −8.2610 |              3.1792 |
|    1 |     −11.9486 |      −9.3737 |              2.5749 |
|    2 |     −10.3080 |      −4.6847 |              5.6233 |
|    3 |      −6.6794 |       0.0919 |              6.7713 |
|    4 |      −2.9261 |       4.9414 |              7.8674 |
|    5 |      −1.8656 |       7.4617 |              9.3272 |
|    6 |      −0.4838 |       6.5623 |              7.0461 |
|    7 |      −0.0084 |       6.9212 |              6.9296 |
|    8 |       0.2964 |       7.7324 |              7.4359 |
|    9 |       0.4708 |       8.1803 |              7.7095 |
|   10 |       0.6754 |       8.6519 |              7.9765 |
|   11 |      −0.0654 |       8.8088 |              8.8742 |
|   12 |       0.3610 |      10.1165 |              9.7556 |
|   13 |       1.3150 |       9.7085 |              8.3935 |
|   14 |       1.6727 |      10.1949 |              8.5222 |
|   15 |       1.5108 |      10.3205 |              8.8096 |
|   16 |       1.5429 |      10.7090 |              9.1660 |
|   17 |       1.8326 |      11.2213 |              9.3887 |
|   18 |       1.7314 |      11.0215 |              9.2902 |
|   19 |       1.0027 |      10.5676 |              9.5649 |

**Reading the table.** With both the `round(·, 2)` quantization and the
`+ 1e-10` offset removed, every per-file value is simply `log_{5.27}` of the
true linear mean of `per_segment` (`-inf` only for a mean of `<= 0`, which does
not occur here). The weakest-injection files (0–2) sit deep in the negatives
because their linear means are tiny but non-zero; the perfect-denoiser ceiling
(`gt`) already lifts off the noise floor at file 0 (gt = −8.26 vs. raw =
−11.44, ~3 log-units of headroom available even at the lowest
injection). File 3 is the first file where the ceiling crosses zero
(gt = +0.09); the baseline catches up a couple of files later as the
raw SQUID channel starts to carry recoverable signal. Headroom (gt −
raw) grows from ~2.5 log-units in the dead-zone to ~9.5 log-units in
the strong-signal band, because the perfect denoiser benefits more
from increasing injection than the unfiltered CH1 does.

**Operational note for the score-table consumer.** Files 0–2 do not
have "zero recoverable signal" in this convention — their `gt` values
are finite and several log-units above the raw baseline. The
"information dead zone" partition used by the V9 interpreter is
therefore expressed as a magnitude threshold on `gt` (e.g.
`gt < some_low_threshold`), not as equality to a clip floor. See
Phase 8 in `docs/aggregated_score_table_awareness.md`.

## Aggregated scalar

Anchor-normalized grand mean — **not** the arithmetic mean of the per-file
log-space scores above.

```
per_segment  = (snr_sg[f][i] / s_max) · snr_squid[f][i]             # or anchor[f][i]² / s_max for the ceiling
grand_mean   = ( Σ_f Σ_i per_segment ) / ( Σ_f |S_f| )               # |S_f| = 200 per file
scalar_score = log_{5.27}(grand_mean)                               # -inf if grand_mean <= 0
```

| metric                         | scalar_score | source                                                   |
|--------------------------------|-------------:|----------------------------------------------------------|
| ground-truth ceiling           |      10.1134 | `ground_truth/ceiling_anchor_normalized.json`            |
| raw baseline (grand mean)      |       1.0007 | `raw_baseline/scalar_anchor_normalized.json`             |
| headroom (ceiling − baseline)  |       9.1127 | derived                                                   |

Both scalars are computed by the same anchor-normalized grand-mean path —
`compute_raw_baseline._maybe_write_anchor_normalized_scalar` and
`compute_ground_truth._anchor_normalized_ceiling` are symmetric aggregators
that sum `linear_sum` and `n_segments` across the 20 fine files before
applying `log_{5.27}(grand_mean)`. The production scorer
`execute_tools.scoring_utils.score_vector` uses this exact same grand-mean
path for model evaluations, so the three numbers sit on one ruler.

Under trial-mode non-uniform sampling (`|S_f|` differs across files), the
grand mean does not equal `mean_f(per_file_log)` — which is why averaging
the per-file log scores is misleading and not shown here.

See `docs/align_denoising_score.md` §4 and §C.2 for the full derivation.
