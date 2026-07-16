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
| **M1** | ~~File-vector byte-identity dedup~~ — **DROPPED 2026-07-16**. Superseded by **M8**. Rationale: hash-based dedup matches specific byte-identical outputs; a phantom that shifts by one LSB in one segment evades it, and the defense requires two rounds to prime. Output-diversity metrics defend against the collapse *mechanism* on the first round with 10×-1000× separation between real learning (FCNet unique_int8=127+) and collapse variants (unique_int8 ≤ 15). Empirical: Pearson feasibility experiment 2026-07-16. Issue **#108** to be closed with a pointer to M8. | ~~1 day~~ | n/a — plan file deleted |
| **M2** | **Wire `is_degenerate` / `failure_reason` / `gate_action` into `ModelRunSummary`**. Without this, the interpreter never learns from collapse; even if we detect it, the signal dies at the tuner boundary (Drop #1 in the signal-flow trace: `HyperparamTuningOutput` → `ModelRunSummary`). | **1 day** | `agent/schemas/interpretation.py` (add per-round fields to `ModelRunSummary`); `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py` (map fields); interpretation prompt template (surface fields) |
| **M3** | **Adopt v15 §6.9 mitigation #1: increase formal-round training**. Set `--max_epochs 3` (or 5) for formal rounds AND `formal_train_portion=1.0` (already default). Trivial config change but structurally required for collapse escape. Note: `--max_epochs` is currently the tuner CLI cap; there is no separate `--formal_max_epochs` today, so this would apply to trial rounds too — either accept that or add the separate flag. | **0.5 day** (config only) OR **1 day** (add `--formal_max_epochs` CLI flag) | `scripts/run_comparison.py` argparse + launch commands. Optionally add `--formal_max_epochs` flag to tuner |
| **M4** | ~~Precomputed phantom table for known K values~~ — **DROPPED 2026-07-16**. Superseded by **M8**. Rationale: table-based lookup matches specific numeric scalars (5.5763, 6.3556); a new phantom that produces a novel scalar slips through, and the table needs manual curation. Output-diversity checks catch collapse regardless of the resulting scalar. Issue **#109** to be closed with a pointer to M8. | ~~1 day~~ | n/a — plan file deleted |
| **M5** | **Resolve v15 §6.9 outlier** (iter 4 R4: `final_loss=5.03` untrained but produced 5.5763 phantom). This suggests a **second mechanism** beyond mode collapse — possibly silent inference crash reading stale HDF5. Must be understood or v17 formal rounds may still produce untraceable phantoms. | **1-2 days** forensic investigation | forensic: reproduce iter 4 R4 conditions, add file-existence + write-timestamp assertions to `execute_tools/inference_single.py` around `create_abra_file` |
| **M6** | **Execute Gate 2** (issue #102) — HealthGate PR #101 has never had its end-to-end real-LLM smoke run. Blocks any v17 launch. **DONE** 2026-07-15 (PR #101 merged at `a595fcc`). | ~~1h~~ | closed |
| **M7** | **Loss-implementor contract violation** (issue #112) — proposer specifies custom loss name, but implementor is not invoked to generate the plugin file before the training subprocess runs. Every training attempt aborts with `ValueError: Custom loss '...' not found in LOSS_REGISTRY or agent_generated/losses/`. Discovered during Gate 2 execution on 2026-07-15; caused Gate 2 to fail with 0 rounds completed. Root-cause candidate: capability index advertises losses whose file paths point to old run-workspaces, not to `agent_generated/losses/`, and `render_available_losses` lacks the phantom filter that `render_available_models` has. Execution plan: [`m7_loss_implementor_contract_execution_plan.md`](./m7_loss_implementor_contract_execution_plan.md) | **1-2 days** (needs investigation of proposer → implementor → training subprocess handoff) | TBD — investigation required. Candidates: `nodes/ml_model_implementor/`, `agent/prompt_templates/proposal/__init__.py::render_available_losses`, workflow orchestration, subprocess launch path. |
| **M8** | **Complete gate coverage + output-diversity metrics** (issue **#118**). Adds `after_round: every` schema extension so gates fire on every round (fixes the round-7 agent_012 escape), adds `OutputStdCheck` blocking (min_std_mv: 1.0), adds three recording-only checks (pearson_correlation, spectral_peak_ratio, per_file_output_std), tightens `output_diversity` threshold to 30, and fixes `build_diagnostic_summary.py` semantics to distinguish `passed / failed / not_run`. Replaces M1 and M4. Empirical basis: 6.3556 investigation + Pearson feasibility experiment 2026-07-16. Execution plan: [`m8_gate_coverage_and_diversity_metrics_execution_plan.md`](./m8_gate_coverage_and_diversity_metrics_execution_plan.md) | **2-3 days** | new `execute_tools/health_checks/output_std.py`, `pearson_correlation.py`, `spectral_peak_ratio.py`, `per_file_output_std.py`; extend `HealthCheckContext` with `target_path_fn`; extend `HealthGateConfig.after_round` to `int \| Literal["every"]`; rewrite `configs/health_checks.yaml`; update `scripts/build_diagnostic_summary.py` |

**Total MUST effort: ~5-7 days** (M2 + M3 + M5 + M7 + M8; M1 + M4 dropped; M6 done).

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

## Dependency graph (revised 2026-07-16 — M1/M4 dropped, M8 added)

```
                    ┌─────────────────────────────────────────────┐
                    │  v17 GOAL: produce ≥1 real, non-phantom score│
                    └─────────────────────────────────────────────┘
                                        ▲
                                        │  needs all of
      ┌──────────────────┬──────────────┴──────────────┬──────────────────┐
      │                  │                             │                  │
┌─────┴─────┐   ┌────────┴─────────────┐   ┌───────────┴──────┐   ┌───────┴────────┐
│ M3:       │   │ M8: complete gate    │   │ M7: loss         │   │ (S* items       │
│ training  │   │ coverage + output    │   │ implementor      │   │  land during    │
│ regime    │   │ diversity metrics    │   │ contract bug     │   │  v17, not       │
│ unblocks  │   │ (blocking + record-  │   │ (#112 — custom   │   │  blocking)      │
│ real      │   │ ing checks; every    │   │ loss materializ- │   │                 │
│ converge  │   │ round gated).        │   │ ation)           │   │                 │
│ (epochs,  │   │ SUPERSEDES M1 + M4.  │   │                  │   │                 │
│  data)    │   │                      │   │                  │   │                 │
└─────┬─────┘   └────────┬─────────────┘   └───────┬──────────┘   └───────┬────────┘
      │                  │                         │                      │
      │                  ▼                         │                      │
      │       ┌────────────────────┐               │                      │
      │       │ M2: MRS carries    │               │                      │
      │       │ collapse signal    │               │                      │
      │       │ (unblocks feedback │               │                      │
      │       │  loop for interp/  │               │                      │
      │       │  proposer)         │               │                      │
      │       └─────────┬──────────┘               │                      │
      │                 │                          │                      │
      │       ┌─────────┴──────────┐               │                      │
      │       │ S6 (interp prompt) │               │                      │
      │       │ S7 (proposer prom) │               │                      │
      │       │ S1 (n_unique_int8) │               │                      │
      │       │ S3 (corr guard)    │               │                      │
      │       └─────────┬──────────┘               │                      │
      │                 │                          │                      │
      │       ┌─────────┴──────────┐               │                      │
      │       │ S5 (v17 advice)    │               │                      │
      │       │ S8 (seed path docs)│               │                      │
      │       └─────────┬──────────┘               │                      │
      │                 │                          │                      │
      └─────────────────┴──────────────────────────┴──────────────────────┘
                                       ▼
                                 V17 LAUNCH
                                       │
                                       ▼
                              (post-v17 deferred)
                                       │
                       ┌───────────────┼────────────────┐
                       ▼               ▼                ▼
                    D1 (Run       D2 (bidir        D3 (metric
                    Monitor)      cross-iter        redesign)
                                  flow)
```

Notes on graph changes:
- **M1 (file-vector dedup) and M4 (phantom lookup) boxes REMOVED** — replaced by **M8**.
- **M6 (Gate 2) DONE** — no longer in the critical path.
- **S2 (tighten OutputDiversityCheck) folded into M8** (which does exactly this and more) — no longer listed as separate.
- **S4 (yaml positions per max_rounds) folded into M8** (`after_round: every` obviates round-specific tuning) — no longer listed as separate.

## Critical path (revised 2026-07-16)

M8 (2-3d, includes gate coverage + diversity metrics + summary fix) ∥ M7 (1-2d, custom loss materialization) ∥ M3 (0.5d, formal training regime) → M2 (1d, wire collapse signal to interpreter) → M5 (1-2d forensic on iter-4-R4 outlier, overlapping) → **V17 LAUNCH**

Total remaining critical-path effort: **~5-7 days** (M6 done; M1/M4 dropped).
