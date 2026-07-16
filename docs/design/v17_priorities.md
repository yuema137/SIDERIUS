# V17 Priority Decisions — 2026-07-15

## Primary Goal

Produce at least one real, non-phantom denoising score.

## Context

The v15/v16 exploration chains produced numerous "beats over baseline" that
were later revealed to be **mode-collapse phantoms**: constant-output models
whose scoring artifacts happened to sit above the wavenet baseline. Forensic
analysis (`reports/v15_20260628.md` §6, `reports/v16_20260630.md` §9)
identified two distinct phantom clusters:

- **5.5763 phantom (class-127, subnormal-FP mechanism)**: when a classifier
  model collapses to constant `int8 = -1`, the PSD noise window sums to
  ~1e-40 (floating-point subnormals). `signal / noise` produces a
  deterministic `2^17 = 131,072` ratio → grand_mean ≈ 10,593 →
  `log_{5.27}(10593) = 5.5763`. **Fixed** in commit `6fcc87f` via a
  `noise < 1e-10` guard in `execute_tools/scoring_utils.py::get_snr` that
  returns `NaN`, which `_collect_raw_pairs` then filters. Verified
  empirically to eliminate the 5.5763 phantom.

- **6.3556 phantom (mostly-constant with tiny variation)**: same failure
  class (collapse to a different constant K), but the tiny stochastic
  variation lifts the PSD noise window above subnormal (`noise > 1e-10`).
  The existing guard **does not fire**. Detected only via byte-identical
  `file_vector` evidence across 5 different (model, loss) combinations in
  v15 formal rounds (v15 §6.1, §6.9). **No code, test, or design doc
  currently covers this pattern.**

**Why both loss and score metrics can reward collapse:**

- **Focal / EMD losses on classifier outputs have degenerate optima at
  "predict bin distribution mode"**, giving `final_loss ∈ [0.047, 0.087]`
  for constant-K outputs — indistinguishable from a well-trained model by
  loss value alone (v15 §6.9).
- **Anchor-normalized denoising_score is agnostic to signal-independence**
  — a constant output produces a fixed spurious SNR pattern that reflects
  the SQUID reference channel's file-to-file variance, NOT any real
  denoising performance. The scoring formula is deterministic: same
  constant K → same file_vector → same score (across any model / loss
  combination that reaches that K).

**References**:
- `reports/v15_20260628.md` §6 (dedicated "6.3556 / 5.5763 ghost score
  investigation" — 5-point mitigation plan in §6.9, all currently
  unimplemented)
- `reports/v16_20260630.md` §9 (v16 forensic confirmation — all three v16
  arch-chain formal completions landed on 5.5763)
- `docs/design/pluggable_health_checks.md` §11 (documents 5.5763 fix; does
  not mention 6.3556)

**Discovered during Gate 2 execution (2026-07-15):** A separate
loss-implementor contract bug (**M7**, issue #112) blocks any chain that
proposes a custom loss — the capability index advertises losses whose
files live in old run-workspaces, not in `agent_generated/losses/`, so
`_load_custom_loss()` raises at training start. Gate 2 was completed
under Option B (built-in loss constraint via
`advice/workflow/gate2_smoke_advice.json`) to unblock PR #101 merge, but
M7 must be resolved before v17 launch because v17 will heavily explore
custom losses (per S5 v17 chain advice content).

## MUST fix before v17 launch

| # | Gap | Effort | Files to change |
|---|-----|--------|-----------------|
| **M1** | **File-vector byte-identity dedup** as a new `HealthCheckSkill`. Registers every file_vector's hash; on repeat within the same chain, returns `INVALIDATE_ROUND`. Catches 5.5763 AND 6.3556 AND any future collapse constant. | **1 day** | new `execute_tools/health_checks/file_vector_dedup.py`; register in `execute_tools/health_checks/__init__.py`; add YAML entry to `configs/health_checks.yaml` |
| **M2** | **Wire `is_degenerate` / `failure_reason` / `gate_action` into `ModelRunSummary`**. Without this, the interpreter never learns from collapse; even if we detect it, the signal dies at the tuner boundary (Drop #1 in the signal-flow trace: `HyperparamTuningOutput` → `ModelRunSummary`). | **1 day** | `agent/schemas/interpretation.py` (add per-round fields to `ModelRunSummary`); `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py` (map fields); interpretation prompt template (surface fields) |
| **M3** | **Adopt v15 §6.9 mitigation #1: increase formal-round training**. Set `--max_epochs 3` (or 5) for formal rounds AND `formal_train_portion=1.0` (already default). Trivial config change but structurally required for collapse escape. Note: `--max_epochs` is currently the tuner CLI cap; there is no separate `--formal_max_epochs` today, so this would apply to trial rounds too — either accept that or add the separate flag. | **0.5 day** (config only) OR **1 day** (add `--formal_max_epochs` CLI flag) | `scripts/run_comparison.py` argparse + launch commands. Optionally add `--formal_max_epochs` flag to tuner |
| **M4** | **Precomputed phantom table** for known K values. Provides deterministic rejection of the two known phantoms (5.5763, 6.3556) plus any others discovered by simulation. Complements M1 (dedup catches WITHIN-run repeats; phantom table catches FIRST occurrence). | **1 day** | new `reference_data/collapse_phantoms.json`; new HealthCheckSkill `execute_tools/health_checks/phantom_score_check.py`; register in YAML |
| **M5** | **Resolve v15 §6.9 outlier** (iter 4 R4: `final_loss=5.03` untrained but produced 5.5763 phantom). This suggests a **second mechanism** beyond mode collapse — possibly silent inference crash reading stale HDF5. Must be understood or v17 formal rounds may still produce untraceable phantoms. | **1-2 days** forensic investigation | forensic: reproduce iter 4 R4 conditions, add file-existence + write-timestamp assertions to `execute_tools/inference_single.py` around `create_abra_file` |
| **M6** | **Execute Gate 2** (issue #102) — HealthGate PR #101 has never had its end-to-end real-LLM smoke run. Blocks any v17 launch. | **~1h wall time**, ~$2 cost | run canonical Gate 2 command from `docs/design/pluggable_health_checks.md` §15.3 |
| **M7** | **Loss-implementor contract violation** (issue #112) — proposer specifies custom loss name, but implementor is not invoked to generate the plugin file before the training subprocess runs. Every training attempt aborts with `ValueError: Custom loss '...' not found in LOSS_REGISTRY or agent_generated/losses/`. Discovered during Gate 2 execution on 2026-07-15; caused Gate 2 to fail with 0 rounds completed. Root-cause candidate: capability index advertises losses whose file paths point to old run-workspaces, not to `agent_generated/losses/`, and `render_available_losses` lacks the phantom filter that `render_available_models` has. | **1-2 days** (needs investigation of proposer → implementor → training subprocess handoff) | TBD — investigation required. Candidates: `nodes/ml_model_implementor/`, `agent/prompt_templates/proposal/__init__.py::render_available_losses`, workflow orchestration, subprocess launch path. |

**Total MUST effort: ~6-9 days + Gate 2 run.**

## SHOULD fix during v17

| # | Gap | Effort | Notes |
|---|-----|--------|-------|
| **S1** | Add `n_unique_int8` + `unique_value_top3` to ExperimentRecord (v15 §6.9 rec #3) | 0.5 day | Makes collapse diagnosable from JSON alone |
| **S2** | Tighten `OutputDiversityCheck` thresholds — empirically calibrate against known-collapsed vs known-honest runs | 1 day | Currently permissive; may miss 6.3556-style near-constant |
| **S3** | Correlation-based scoring guard (Layer 4) — `pearson_correlation(denoised, target) < eps` inside `score_vector` | 2 days | Makes raw `denoising_score` value honest, not just flagged |
| **S4** | Update `configs/health_checks.yaml` gate positions for v17 `max_rounds` (issue #105) | 0.5 day | Ensures gates fire at the right rounds |
| **S5** | Create v17 chain advice file (issue #103) | 1 day | Content: focal-loss policy, HealthGate expectations, known phantom fingerprints, collapse-avoidance guidance |
| **S6** | Interpreter prompt template update: surface collapse info structurally, not just as text | 0.5 day | Depends on M2 |
| **S7** | Proposer prompt update: instruct explicit collapse-fingerprint avoidance | 0.5 day | Depends on M1 (proposer needs the fingerprint set to reference) |
| **S8** | Update seed paths in docs (issue #104) | 0.5 day | Cosmetic but blocks operator confusion |

## DEFER post-v17

| # | Item | Reason |
|---|------|--------|
| **D1** | Run Monitor agent (issue #100) | Umbrella for M1-M2 done at orchestrator level. Bigger re-architecture — 2-3 weeks. |
| **D2** | Bidirectional cross-iteration flow (issue #95) | Long-term architectural rework. |
| **D3** | Metric redesign — collapse-resistant score formula (Layer 5) | Governance decision + paper-comparability concerns. Not needed if M1+M2+M4 are in place. |
| **D4** | Multi-condition stop gates (issue #106) | Nice-to-have; single-condition gates cover v17 needs. |
| **D5** | Modular agent orchestration (issue #91) | Architecture-level, not blocking. |
| **D6** | ModelConfig typed Pydantic (issue #97) | Tech-debt, unrelated to collapse. |
| **D7** | Info-source weighting (issue #94) | Optimization on top of a working proposer. |

## Dependency graph

```
                    ┌─────────────────────────────────────────────┐
                    │  v17 GOAL: produce ≥1 real, non-phantom score│
                    └─────────────────────────────────────────────┘
                                        ▲
                                        │  needs all of
      ┌──────────────────┬──────────────┼──────────────┬──────────────────┐
      │                  │              │              │                  │
┌─────┴─────┐   ┌────────┴────────┐  ┌──┴───┐   ┌──────┴──────┐   ┌───────┴────────┐
│ M3:       │   │ M1+M4+M5: score │  │ M6:  │   │ M7: loss    │   │ (S* items       │
│ training  │   │ guards prevent  │  │ Gate │   │ implementor │   │  land during    │
│ regime    │   │ phantom from    │  │ 2    │   │ contract    │   │  v17, not       │
│ unblocks  │   │ being counted   │  │ pass │   │ bug         │   │  blocking)      │
│ real      │   │ as beat         │  │ (#102│   │ (#112 —     │   │                 │
│ converge  │   │                 │  │ )    │   │ custom loss │   │                 │
│ (epochs,  │   │                 │  │      │   │ materializ- │   │                 │
│  data)    │   │                 │  │      │   │ ation)      │   │                 │
└─────┬─────┘   └────────┬────────┘  └──┬───┘   └──────┬──────┘   └───────┬────────┘
      │                  │              ▲              │                  │
      │                  ▼              │              │                  │
      │       ┌────────────────────┐    │              │                  │
      │       │ M2: MRS carries    │    │              │                  │
      │       │ collapse signal    │    │              │                  │
      │       │ (unblocks feedback │    │              │                  │
      │       │  loop for interp/  │    │              │                  │
      │       │  proposer)         │    │              │                  │
      │       └─────────┬──────────┘    │              │                  │
      │                 │               │              │                  │
      │       ┌─────────┴──────────┐    │              │                  │
      │       │ S6 (interp prompt) │    │              │                  │
      │       │ S7 (proposer prom) │    │              │                  │
      │       │ S1 (n_unique_int8) │    │              │                  │
      │       │ S2 (tighten checks)│    │              │                  │
      │       │ S3 (corr guard)    │    │              │                  │
      │       └─────────┬──────────┘    │              │                  │
      │                 │               │              │                  │
      │       ┌─────────┴──────────┐    │              │                  │
      │       │ S4 (yaml positions)│    │              │                  │
      │       │ S5 (v17 advice)    │    │              │                  │
      │       │ S8 (seed path docs)│    │              │                  │
      │       └─────────┬──────────┘    │              │                  │
      │                 │               │              │                  │
      └─────────────────┼───────────────┴──────────────┴──────────────────┘
                        ▼
                   V17 LAUNCH
                                        │
                                        ▼
                                (post-v17 deferred)
                                        │
                       ┌────────────────┼────────────────┐
                       ▼                ▼                ▼
                    D1 (Run       D2 (bidir           D3 (metric
                    Monitor)      cross-iter flow)     redesign)
```

## Critical path

M6 (Gate 2 under Option B, ~1h) → M3 (config, 0.5d) → M1+M2+M4+M7 in parallel (M1+M2+M4=3d, M7=1-2d, so M7 does not extend critical path) → M5 (2d, overlap) → v17 launch
