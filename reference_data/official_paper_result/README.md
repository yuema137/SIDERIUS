# TIDMAD Official Paper-Model Denoising Scores

Denoising scores for the official band-split TIDMAD paper checkpoints, evaluated with the SIDERIUS `score_vector` pipeline on the canonical anchor map.

## Aggregation

Every headline number below is the CANONICAL `denoising_score`:

```
denoising_score = log_5.27( Σ_(f,i) per_segment[f,i] / Σ_f |S_f| )
```

Grand mean over every sampled segment across every sampled file, then log. See `execute_tools/scoring_utils.py` module docstring §3 for the full contract and the three aggregation patterns that MUST NOT be substituted.

## Ruler

- Raw baseline (no denoising): **1.0007** — floor
- Ground-truth ceiling (perfect denoiser): **10.1134**

All scores are on the same log_5.27 scale, using the global s_max (295715680.14) from the committed `reference_data/segment_anchors.json`.

## Band-checkpoint mapping (from `train.py::ifile_checkpoint`)

| Band | Frequency range | Validation files | Checkpoint |
|:-----|:----------------|:-----------------|:-----------|
| 0-3   | low          | 0, 1, 2, 3         | `{Model}_0_4.pth`   |
| 4-9   | mid          | 4, 5, 6, 7, 8, 9   | `{Model}_4_10.pth`  |
| 10-14 | mid-high     | 10, 11, 12, 13, 14 | `{Model}_10_15.pth` |
| 15-19 | high         | 15, 16, 17, 18, 19 | `{Model}_15_20.pth` |

*Wavenet is intentionally excluded* (per the request that spawned this evaluation); the paper's official wavenet is a single generalist checkpoint scored separately by `scripts/score_tidmad_official_wavenet.py`.

## Summary

| Model | denoising_score | vs raw floor | vs GT ceiling | Details |
|:------|----------------:|-------------:|--------------:|:--------|
| fcnet | **6.4348** | 5.4341 | -3.6786 | [`fcnet.md`](fcnet.md) |
| punet | **3.6918** | 2.6911 | -6.4216 | [`punet.md`](punet.md) |
| rnn | **1.5056** | 0.5049 | -8.6078 | [`rnn.md`](rnn.md) |
| transformer | *pending* | — | — | *pending* |

## Reproducibility

Rebuild this whole directory (idempotent, reads the summary JSONs):

```bash
scripts/render_official_paper_result.py
```
