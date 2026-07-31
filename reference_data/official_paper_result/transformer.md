# TIDMAD official band-split transformer

## Headline

**Canonical `denoising_score` = _pending_** — the banded scoring run has not produced a summary JSON for this model yet. The HealthGate metrics below stand on their own: they describe the denoised outputs that do exist, and they do not depend on the score.

## HealthGate per-file metrics

Peek window 1,000,000 samples (the reference-table window; production blocking gates peek 100,000). Metric formulas are the production `HealthCheck` classes, imported rather than reimplemented, so a number here means what it means inside a chain.

Thresholds: `unique_int8 > 25`, `std_mv >= 1.0`, `mode_fraction < 0.95`.

**Healthy on 0 of 18 files** (diversity 0/18, std 6/18, amplitude 6/18).

> **Partial scan — 18 of 20 files.** Missing denoised outputs: `0018`, `0019`. Absent files are neither scored nor inferred.

| file | ckpt | target std (mV) | unique_int8 | std (mV) | mode % | pearson | spectral | verdict |
|---:|:---|---:|---:|---:|---:|---:|---:|:---|
| 0000 | `0_4` | 0.2797 | 1 | 0.0000 | 100.00 | — | — | FAIL (dsa) |
| 0001 | `0_4` | 0.2519 | 1 | 0.0000 | 100.00 | — | — | FAIL (dsa) |
| 0002 | `0_4` | 0.2483 | 1 | 0.0000 | 100.00 | — | — | FAIL (dsa) |
| 0003 | `0_4` | 0.2465 | 1 | 0.0000 | 100.00 | — | — | FAIL (dsa) |
| 0004 | `4_10` | 0.4067 | 4 | 1.0159 | 68.33 | +0.0091 | 0.6642 | FAIL (dSA) |
| 0005 | `4_10` | 1.4920 | 4 | 1.0182 | 68.07 | +0.0043 | 0.6925 | FAIL (dSA) |
| 0006 | `4_10` | 2.8800 | 4 | 1.0170 | 68.21 | -0.0051 | 0.7038 | FAIL (dSA) |
| 0007 | `4_10` | 2.1819 | 4 | 1.0123 | 68.75 | +0.0285 | 0.6821 | FAIL (dSA) |
| 0008 | `4_10` | 3.0597 | 4 | 1.0188 | 68.00 | -0.0279 | 0.6938 | FAIL (dSA) |
| 0009 | `4_10` | 3.9596 | 4 | 1.0101 | 68.99 | +0.0120 | 0.6371 | FAIL (dSA) |
| 0010 | `10_15` | 4.9220 | 2 | 0.0300 | 100.00 | -0.0014 | 0.0306 | FAIL (dsa) |
| 0011 | `10_15` | 5.7752 | 2 | 0.0312 | 100.00 | -0.0007 | 0.0000 | FAIL (dsa) |
| 0012 | `10_15` | 8.8355 | 3 | 0.0804 | 100.00 | +0.0027 | 0.0462 | FAIL (dsa) |
| 0013 | `10_15` | 13.4092 | 2 | 0.0520 | 100.00 | -0.0009 | 0.0025 | FAIL (dsa) |
| 0014 | `10_15` | 15.1689 | 1 | 0.0000 | 100.00 | — | — | FAIL (dsa) |
| 0015 | `15_20` | 15.9695 | 1 | 0.0000 | 100.00 | — | — | FAIL (dsa) |
| 0016 | `15_20` | 16.2986 | 1 | 0.0000 | 100.00 | — | — | FAIL (dsa) |
| 0017 | `15_20` | 16.4619 | 1 | 0.0000 | 100.00 | — | — | FAIL (dsa) |

Verdict letters: upper case passed that check (D diversity, S std, A amplitude), lower case failed.

Regenerate:

```bash
python scripts/official_paper_health_scan.py --model transformer \
  --denoised-dir /home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/transformer/full_20_files \
  --json-out reference_data/official_paper_result/transformer_health.json
```