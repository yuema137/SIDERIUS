# TIDMAD Collapse — Advice and Forensics

- **Status**: active
- **Scope**: **task-specific** (TIDMAD / SQUID magnetometer denoising)
- **Owner**: TBD
- **Created**: 2026-07-15
- **Last Updated**: 2026-07-16

## 1. Purpose and scope

This document is the **task-specific companion** to the generic collapse
detection framework and structured feedback loop. It captures
everything empirically observed about TIDMAD collapse behaviour that the
framework must NOT contain: specific phantom scalar values, observed
loss-family attractors, per-model training regime advice, and open
forensic questions.

Content here is consumed by:

- The advice-loading path (`advice/workflow/*.json` files reference it
  or duplicate values from it)
- The precomputed phantom table
  (`reference_data/collapse_phantoms.json` when it exists, per **M4**)
- Human operators reading forensic reports to understand chain
  behaviour

Content here is **NOT** consumed by framework code — the framework knows
nothing about any specific TIDMAD constant. Any change here that
requires touching a `.py` file in `execute_tools/health_checks/` or
`agent/schemas/` signals a framework-purity violation; report and
redesign.

## 2. Known phantom fingerprints

### 2.1 Cluster A: `5.5762667` (class-127 mode-collapse attractor)

| Property | Value |
|---|---|
| **Score value (exact)** | `5.5762667808348825` |
| **Alternate observation** | `5.576266685863386` (differs by ~1e-8, float-precision diff between pre/post `6c3f736` code paths) |
| **Underlying constant** | `int8 = -1` (class-127 in the shifted `[0, 255]` ADC domain) |
| **Mechanism** | Constant int8=-1 output → FFT of constant TS → all non-DC PSD bins are float32 subnormals (~1e-40) → `signal_window / noise_window` sum ratio deterministically equals `2^17 = 131072` → grand_mean ≈ 10593 → `log_{5.27}(10593)` = 5.5763 |
| **grand_mean fingerprint** | 10592.7459... |
| **First observed** | v0 baselines (2026 early, exact date TBD) |
| **Reproduction** | Any classifier trained too briefly with focal or CE loss on TIDMAD `abra_training` data |
| **Framework defence** | `get_snr` noise-floor guard (`noise < 1e-10 → NaN`), implemented commit `6fcc87f` (2026-07-08) — verified to eliminate this specific phantom |
| **Docs** | `docs/design/pluggable_health_checks.md` §11 (documents the fix) |

### 2.2 Cluster B: `6.3556` (mostly-constant with tiny variation, SQUID-dominated)

| Property | Value |
|---|---|
| **Score value (main)** | `6.355558080431343` |
| **Alternate observation** | `6.35555808043049` (last 4 decimals differ — float roundoff) |
| **Underlying pattern** | Model output near-constant but with sufficient stochastic variation that PSD noise stays above subnormal (`> 1e-10`); resulting per-file scores are dominated by SQUID reference channel variance |
| **Mechanism** | Not a strict-constant collapse. Different constant target (candidate: near class-128 / `int8 = 0`) with occasional deviation. `find_peak` returns a spurious peak from FFT noise; `signal/noise` is large-but-finite; grand_mean ≈ 38682 → `log_{5.27}(38682)` = 6.3556 |
| **grand_mean fingerprint** | 38682.0327... |
| **First observed** | v15 formal chain (`reports/v15_20260628.md` §6.1) — 4 iterations (1, 8, 17, 19) with byte-identical file_vectors across different (model, loss) combinations. Also v16 arch chain iter_010, iter_019, iter_020 (`reports/v16_20260630.md` §9.5). |
| **Reproduction** | EMD-family losses in particular tend to produce this cluster; empirically 4/4 iters that landed here in v15 used EMD-derivative losses |
| **Framework defence** | **NOT covered by existing guards.** `noise < 1e-10` doesn't fire (noise stays finite). Requires either file-vector byte-identity dedup (M1) or a phantom table entry (M4). |
| **Docs** | `reports/v15_20260628.md` §6.1, §6.4, §6.9. Issue #110 tracks the coverage gap. |

### 2.3 Phantom table format for machine consumption

Per the authoritative schema in
[`docs/design/collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md)
§4.5, TIDMAD entries in `reference_data/collapse_phantoms.json` are:

```json
[
  {
    "task": "tidmad",
    "output_type": "classifier_argmax_int8",
    "constant_k": -1,
    "resulting_score": 5.5762667808348825,
    "resulting_grand_mean": 10592.7459,
    "resulting_file_vector_hash": "<sha256 to be recorded from reproducer>",
    "notes": "class-127 collapse; 2^17 FP subnormal-noise artifact. Guarded by noise<1e-10 in get_snr."
  },
  {
    "task": "tidmad",
    "output_type": "classifier_argmax_int8",
    "constant_k": null,
    "resulting_score": 6.355558080431343,
    "resulting_grand_mean": 38682.0327,
    "resulting_file_vector_hash": "<sha256 to be recorded from reproducer>",
    "notes": "Mostly-constant with tiny variation. SQUID-dominated scoring. NOT caught by noise<1e-10 guard."
  }
]
```

The `null` for `constant_k` on the 6.3556 entry reflects that we
haven't precisely nailed which class it collapses to (near-constant, not
strict-constant). The `resulting_file_vector_hash` placeholder is
recorded from an actual reproducer at first table population
(pending **M4** implementation).

### 2.4 Open diagnostic: identifying the 6.3556 attractor constant

The `constant_k: null` entry for the 6.3556 phantom in §2.3 reflects
that we have not precisely identified which class value the model
collapses to. Closing this gap is part of the **M5** forensic
investigation in [`docs/design/v17_priorities.md`](./v17_priorities.md).

**Investigation plan**:

1. Reproduce the 6.3556 phantom under controlled conditions (short
   training on TIDMAD with an EMD-family loss).
2. Dump the resulting denoised HDF5 and compute:
   - `np.unique(output, return_counts=True)` → identify the dominant
     class(es)
   - `output.mean()`, `output.std()` → characterize "mostly-constant
     with tiny variation" numerically
   - Histogram of int8 values → visualize the attractor location
3. Update the phantom table entry with the identified `constant_k` and
   move the sub-item under §5.3 from "open" to "closed."

**Success criterion**: the phantom table entry for 6.3556 has a
concrete `constant_k` value (not `null`), and a subsequent SIDERIUS run
that lands on this attractor is flagged by `PhantomScoreCheck`
(planned **M4**).

## 3. Loss-family collapse tendencies (empirical)

Empirical observations from v0/v15/v16 runs. **These are observations,
not framework rules.**

| Loss family | Observed attractor | Evidence |
|---|---|---|
| **Focal loss** | Majority-class collapse — for TIDMAD's noise-dominated targets, that's typically class-127 (int8=-1, the noise mean). Produces the 5.5763 phantom. | Prevalent in v0 baselines and v15/v16 focal-family runs. Docstring of `noise < 1e-10` guard in `scoring_utils.py::get_snr` explicitly cites this. |
| **EMD / ordinal loss** | Median-class collapse. Distance-weighted losses favour predicting the ordinal median rather than the mode. On TIDMAD this tends toward the second-cluster 6.3556 phantom. | v15 loss chain iters 1, 8, 17, 19 all used EMD-derivative losses and all landed on 6.3556 (`reports/v15_20260628.md` §6.1). |
| **MSE / smooth-L1 (regression head)** | Mean-value collapse. Regressor with too little training outputs a constant mean value. Not classifier-collapse but produces the same "signal-independent output" pathology; scoring reflects SQUID variance only. | fcnet baseline in `small_sample_trial_v0` — score=3.1050 with per-file max=745. Not equal to either 5.5763 or 6.3556 but shows the pattern. |
| **Cross-entropy (CE) without focal reweighting** | Fastest path to class-127 collapse on TIDMAD's imbalanced target distribution. Historically the reason wavenet baselines produced the 5.5763 phantom before commit `1035c21` switched wavenet to focal. | `tidmad_collapse_advice.json`: "CE loss + Adam + lr=1e-3: causes class-127 mode collapse". |

## 4. Model-specific training regime advice

### 4.1 WaveNet — paper-aligned baseline (v1)

Per direct communication with paper authors + verified against
`/home/tidmad/TIDMAD/train.py` and `network.py::FocalLoss1D`:

| Hyperparameter | Value | Source |
|---|---|---|
| `loss_type` | `focal` | `network.py::FocalLoss1D` — default alpha=0.5, gamma=2.0 |
| `alpha` | `0.5` | `FocalLoss1D()` default |
| `gamma` | `2.0` | `FocalLoss1D()` default |
| `lr` | `5e-4` | `train.py`: `optimizer = torch.optim.Adam(model.parameters(), lr=0.0005)` |
| `epochs` | `1` per file | `train.py` has no epoch loop — one pass per file. SIDERIUS approximates via `--max_epochs 1`. |
| `train_portion` | `0.1` per epoch | `train.py::read_loader` samples `sample_size=10` random 20-second windows per file per pass. |
| `optimizer_type` | `adam` | `train.py` (Adam, not AdamW) |

Fixed in `ml_models/legacy_baseline_configs.json` at commit `3e119c6`.

### 4.2 Structural mismatch (not addressed by config alone)

Two important divergences between paper methodology and SIDERIUS:

1. **Paper trains 4 separate models per architecture** (one per frequency
   band, `ifile_checkpoint = [0, 4, 10, 15, 20]` in `train.py`).
   SIDERIUS trains **one generalist model** across all 20 files.
2. **Paper re-initializes optimizer per file** (`optimizer = Adam(...)`
   inside the `for ifile` loop). SIDERIUS uses one optimizer per
   subprocess.

Even with paper-aligned `lr` + `alpha`, the generalist wavenet may not
converge on the union of all frequency-band files. This is the reason
the fresh paper-aligned wavenet baseline still returned
`denoising_score: None` in the 2026-07-14 regeneration attempt.

### 4.3 Minimum epochs / data required (experimental design)

Not yet empirically established. Current best guesses from v15
forensic report §6.9 are insufficient without validation.

**Proposed experiment (M3 execution plan)** — tracked as **M3** in
[`v17_priorities.md`](./v17_priorities.md):

Grid search over `--max_epochs ∈ {1, 3, 5, 10}` ×
`--train_portion ∈ {0.1, 0.5, 1.0}` for a paper-aligned wavenet
(`lr=5e-4, alpha=0.5, focal_loss`). For each cell:

1. Run inference on validation data.
2. Compute per-file
   `pearson_correlation(denoised_output, target_signal)`.
3. Record the mean and per-file distribution.

**Pass criterion for a cell**: mean pearson correlation across all 20
validation files ≥ 0.1 (arbitrary threshold; the point is
non-negligible signal recovery, not perfect denoising).

**Expected outcome**: identify the minimum (epochs, train_portion)
combination that escapes the collapse basin. This becomes the
recommended v17 configuration for formal rounds.

**Resource estimate**: 12 grid cells × ~15 min inference each ≈ 3
hours of compute. Justifiable given how many downstream runs the
answer unblocks.

**Recording**: results table appended to this doc under §4.3.1
"Empirical results" once the grid completes.

### 4.4 Known-collapsing configurations to avoid

Compiled from `advice/workflow/tidmad_collapse_advice.json` and the
forensic reports:

| Config | Failure mode |
|---|---|
| `loss_type=ce, optimizer=adam, lr=1e-3` | Class-127 collapse → 5.5763 phantom |
| `loss_type=focal, alpha=0.25, lr=1e-3` (SIDERIUS pre-`3e119c6` wavenet default) | Slower to collapse than CE but still lands in the 5.5763 basin under short training |
| Any classifier `loss_type=custom` referencing a loss NOT in the runtime `LOSS_REGISTRY` | `ValueError: Custom loss X not found in LOSS_REGISTRY` — 0 rounds complete. See issue #112 / v17 **M7** (see [v17_priorities.md](./v17_priorities.md) MUST-fix M7). |

### 4.5 Losses worth testing (open experimental directions)

The following loss functions are hypothesized to be more
collapse-resistant than focal / EMD on TIDMAD, but have not been
empirically validated in SIDERIUS. Listed in order of priority.

| Loss | Rationale | Priority |
|---|---|---|
| **Pearson correlation loss** (`1 - pearson(denoised, target)`) | Directly aligned with the scoring metric. Constant output → correlation undefined → loss = 1, providing gradient. Cannot collapse to any fixed class because loss depends on covariance. | High — most likely to escape the collapse basin |
| **Frequency-domain SNR loss** (differentiable version of the denoising score) | Optimizes exactly what the scoring pipeline measures. Higher training-target alignment than any time-domain loss. | High — but requires custom autograd |
| **Focal + MSE hybrid** (`focal_loss + λ * mse(denoised, target)`) | Combines discrete decision boundary (focal) with continuous signal preservation (MSE). λ balances between the two attractors. | Medium — cheap to try |
| **Ordinal cross-entropy with class-distance weighting** | Weights errors by \|predicted_class - true_class\|, discouraging arbitrary class collapse. | Low — related to EMD which already collapses |

**None of these are required for v17**. They are candidates for the
v17 chain advice (**S5**, see [v17_priorities.md](./v17_priorities.md)
SHOULD-fix S5) to suggest as exploration targets for the proposer.

## 5. Forensic investigations

### 5.1 Open — iter 4 R4 outlier (tracked as v17 M5)

- **Observation**: v15 loss chain iter 4 R4 produced the 5.5763 phantom
  with `final_loss = 5.03` (untrained — model didn't converge).
- **Anomaly**: Pure mode collapse cannot explain this. An untrained
  model's random logits should produce noisy argmax outputs, not a
  clean constant.
- **Hypotheses**:
  1. Silent inference-subprocess crash; scoring read a stale HDF5 from
     an earlier round
  2. Argmax over untrained noisy logits happens to be
     PSD-equivalent to constant int8=-1 with high probability
  3. A third mechanism yet to be characterised
- **Status**: unresolved. Tracked as M5 in `v17_priorities.md`.
- **Priority**: MUST-fix before v17 launch (or the v17 formal rounds
  may still produce untraceable phantoms).
- **Investigation plan**: reproduce iter 4 R4 conditions with
  file-existence and write-timestamp assertions added to
  `execute_tools/inference_single.py` around `create_abra_file`.

### 5.2 Closed — v0 baseline contamination

- **Observation**: v0 `small_sample_trial_v0` baselines for wavenet,
  transformer, and fcnet all scored 5.5763 — the class-127 phantom.
- **Root cause**: Pre-`6fcc87f` scoring had no noise-floor guard. Any
  briefly-trained classifier collapsed to class-127 and got the
  phantom score.
- **Resolution**: Commit `6fcc87f` added the `noise < 1e-10 → NaN`
  guard. Fresh runs on paper-aligned config produce
  `denoising_score: None` (honest collapse signal) instead of 5.5763.
- **Docs**: `docs/design/pluggable_health_checks.md` §11.

### 5.3 Closed — v15 6.3556 ghost score characterisation

- **Observation**: 4 v15 loss-chain iters and 1 arch-chain iter
  independently produced score 6.3556 with byte-identical file_vectors
  across different (model, loss) combinations.
- **Root cause**: Mode collapse to a non-class-127 constant (candidate:
  class near ADC 0). Different mechanism from 5.5763 — noise stays
  above subnormal so the `noise < 1e-10` guard doesn't fire.
- **Resolution**: **Partial.** The mechanism is characterised in
  `reports/v15_20260628.md` §6.9. The framework does NOT yet catch it —
  requires either M1 (byte-identity dedup) or M4 (phantom table). Both
  tracked in `v17_priorities.md`.
- **Open sub-item**: exact identification of the K value that produces
  this collapse (currently `null` in the phantom table entry).

## 6. Advice integration points

TIDMAD-specific content is loaded and consumed at these places in the
codebase:

- `advice/workflow/tidmad_collapse_advice.json` — tuner-level advice
  covering the class-127 attractor, focal-loss policy, and scoring
  reference values. Consumed via `--advice` flag through
  `sdsc_submission_scripts/_chain_common.sh`.
- `advice/workflow/gate2_smoke_advice.json` — smoke-run constraint
  (built-in loss only) to work around **M7** (issue #112) during Gate
  2 validation. Consumed the same way.
- `ml_models/legacy_baseline_configs.json` — paper-aligned baseline
  hyperparameters. Loaded by `scripts/run_comparison.py`.
- `reference_data/collapse_phantoms.json` (**planned — M4**) — will
  hold the phantom table entries from §2.3 above. Consumed by the
  planned `PhantomScoreCheck` HealthCheckSkill.

## 7. Invalidation triggers

Task-specific advice has a shelf life. The content of this document
MUST be re-validated (and possibly updated or discarded) when any of
the following change:

| Trigger | What to re-verify |
|---|---|
| `execute_tools/scoring_utils.py` scoring formula modified | All phantom scalar values in §2 (new scoring may produce different phantoms) |
| Baseline model architecture changed (`ml_models/legacy_baseline_configs.json`) | §4.1 hyperparameter table, §5 forensic case studies |
| TIDMAD dataset upgraded or replaced | Everything — new data likely produces new collapse attractors |
| Paper reference implementation (`/home/tidmad/TIDMAD/`) updated | §4.1 paper-alignment section, §4.2 structural mismatch analysis |
| `FocalLoss1D` signature or defaults change | §3 loss family table, §4.1 wavenet baseline row |
| Advice loading path (`advice/workflow/*.json`) refactored | §6 integration points |

**Update policy**: when a trigger fires, add a short changelog entry
at the top of §5 forensic investigations noting the trigger, the
re-validation done, and any content updated below.

## 8. Non-goals

- This document does **not** define generic detection mechanisms —
  those live in
  [`docs/design/collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md).
- This document does **not** define the structured signal flow — that
  lives in
  [`docs/design/structured_feedback_loop_experiment_to_proposer.md`](./structured_feedback_loop_experiment_to_proposer.md).
- This document does **not** attempt to be exhaustive of all TIDMAD
  failure modes — only those relevant to collapse detection and
  scoring integrity. Broader TIDMAD forensic content lives in the
  numbered reports under `reports/`.

## 9. Related docs

- `docs/design/collapse_detection_framework_generic.md` — the generic
  detection framework this doc parameterises with TIDMAD-specific
  values.
- `docs/design/structured_feedback_loop_experiment_to_proposer.md` —
  the generic signal-flow contract; TIDMAD's failure fingerprints (§2)
  feed into that contract's `known_failure_fingerprints` set.
- `docs/design/pluggable_health_checks.md` §11 — the class-127 collapse
  attractor design doc.
- [`docs/design/v17_priorities.md`](./v17_priorities.md) — tracks all
  open collapse-related work (**M1**, **M2**, **M3**, **M4**, **M5**,
  **M6**, **M7**) plus the SHOULD-fix items **S1**–**S8**.
- `reports/v15_20260628.md` §6 — dedicated ghost-score forensic
  investigation.
- `reports/v16_20260630.md` §9.5 — v16 confirmation that the 5.5763
  pattern reappeared under v16.
- Related issues: **#93** (adaptive training regime), **#110** (6.3556
  coverage gap), **#112** (loss-implementor bug — v17 M7).
