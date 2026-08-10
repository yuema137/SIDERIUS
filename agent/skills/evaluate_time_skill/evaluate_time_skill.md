# evaluate_time_skill

Pre-flight wall-time estimator and gate. Called by
`ml_hyperparameter_tune_agent` once per attempt (Pre-flight 2/2, after
`evaluate_vram_skill`), and by `ml_model_proposal_agent` indirectly
through `agent/utils/proposer_preflight.py`.

The skill sums three sequential phases — training, inference, scoring —
and asks the **shared runtime decision policy** whether the projection
may gate the round. Since C8c (2026-07-30) the skill no longer decides
that itself.

## Position in the pipeline

```text
ml_hyperparameter_tune_agent
  -> _run_skill("evaluate_time_skill", sandbox, **active_params,
                time_budget_minutes=..., runtime_phase="trial"|"formal")
     -> training_skill/estimator.estimate_wall_time_seconds
     -> inference_skill/estimator.estimate_wall_time_seconds
     -> denoising_score_skill/estimator.estimate_wall_time_seconds
     -> core.runtime_control.decision_policy.RuntimeDecisionPolicy.decide
```

## Input

`run_skill(sandbox, **kwargs)` — keys read from `kwargs`:

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `model_type` | `str` | Yes | — | Architecture key. Non-empty `str` enforced. |
| `model_config` | `dict` | Yes | `{}` | Needs `segmentation_size`. |
| `train_config` | `dict` | Yes | `{}` | Needs `batch_size`, `epochs`. |
| `loss_config` | `dict` | Yes | `{}` | Needs `loss_type`. |
| `sample_set` | `dict` | Yes | `{}` | Training scope `{file_index: [segments]}`. |
| `eval_sample_set` | `dict` | No | `sample_set` | Inference + scoring scope. Formal rounds train on ~10 % but evaluate on 100 %, so passing only `sample_set` under-projects ~10×. |
| `train_portion` | `float` | No | `1.0` | Per-epoch subsample fraction. |
| `time_budget_minutes` | `float` | No | `0.0` | The active-mode budget. |
| `data_dir` | `str \| None` | No | `None` | Enables the real-dataset warmup (3 warmup + 7 timed steps). Without it the estimate falls back to the static formula. |
| `inference_per_psd_seg_ms_hint` | `float \| None` | No | `None` | Measured per-PSD-segment cost from an earlier trial round. Enables the measured inference branch and its 10 % slack. |
| `inference_batch` | `int \| None` | No | `None` | **V21 PR G.** The probe-derived batch inference will actually run at. On the agent path it arrives automatically: the tuner sets `active_params["inference_batch"]` from the feasible `resource_check` (tuner `:4696`) before this gate fires, and `_run_time_preflight` splats `**active_params`. The SAME value drives the hint→ms/step conversion AND the inference estimator, so the forecast prices at the batch that will run (two-sided correction on the `training_warmup_x2.7_fallback` branch: no more false `skipped_time_risk` at probed B > 25, no more false admission at probed B < 25). `None` (baselines, legacy callers) → registry-table pricing, byte-identical to pre-G. Must be a positive `int`; anything else → `status: "error"` (fail-closed, no clamp). |
| `allow_store_reuse` | `bool` | No | `False` | RT3: trial rounds may reuse a valid observation-store unit time instead of warming up. Formal rounds never. |
| `observation_store_root` | `str \| None` | No | `None` | Root of the run's observation store, required by `allow_store_reuse`. |
| `runtime_phase` | `str` | No | `"trial"` | **C8c.** The phase the shared policy decides under (`"trial"` / `"formal"` / `"proposal"`). |
| `probe_record_available` | `bool` | No | `False` | **C8c.** Whether a valid bounded-live-probe record exists for this candidate. False today: no C6 probe feeds this pre-flight. |

## Output

`{status, feasible, verdict, suggestion, estimated_minutes,
limit_minutes, breakdown, dominant_phase, phase_breakdown,
inference_batch_uncalibrated}`, or `{status: "error", message}`.

**`feasible` is the POLICY's verdict** (`decision.kind != "REJECT"`), not
a local budget comparison.

Breakdown keys added by C8c:

| Key | Meaning |
|---|---|
| `over_effective_budget` | The OBSERVATION: `total_minutes > effective_budget_minutes`. Drives the verdict text and the improvement suggestion. Independent of authority. |
| `runtime_decision` | `ALLOW` / `ADVISORY` / `REQUEST_PROBE` / `REJECT`. |
| `runtime_decision_reasons` | The policy's reasons, verbatim. |
| `runtime_decision_provenance` | Evidence provenance the decision rested on. |
| `runtime_policy_identity` | `runtime_decision_policy@<semver>+<hash>`. |

## Authority rules (C8c)

| Evidence (`breakdown.source`) | Provenance | Over budget → |
|---|---|---|
| `real_dataset_warmup` | measurement-backed | **REJECT** — the round is skipped (`skipped_time_risk`), same arithmetic as before C8 |
| `static_uncalibrated` | tier-0 prior | **ADVISORY** — reported, never gates |
| `store` (RT3 reuse) | `historical_observation_prior`, tier 1 | **ADVISORY** — reported, never gates |
| any of the above, `runtime_phase="formal"`, no probe record | — | **REQUEST_PROBE** — proceed into the authoritative RT2 in-subprocess verification |
| unrecognized source | — | **ABORT** → `status="error"`; the tuner raises. Never a candidate verdict. |

Rationale: an uncalibrated formula holding blocking authority is the V19
wave-1 failure. See `docs/design/runtime_estimation_and_calibration.md`
§7.4 (decision matrix) and §23-C8 (implementation record).

## Effective budget and the 10 % slack

```text
effective_budget = budget × 1.10   iff inference_ms_source == "trial_inference_warmup"
effective_budget = budget          otherwise
```

The slack applies only to the measured inference branch, whose estimate
is precise to roughly ±10 % in practice; the fallback branches keep the
strict comparison. The policy is asked about the EFFECTIVE budget, so
the slack behaves exactly as it did before C8.

## Failure modes

- **No CUDA / no `data_dir` / dataset too small** → warmup skipped,
  static formula, advisory-only authority.
- **Warmup fast-fail** (step 0 ≥ 5000 ms) → the warmup aborts and
  reports that step's cost as a worst-case-conservative measurement.
- **Unknown `model_type`** → `_count_params` raises; caught by the
  top-level handler and returned as `status="error"`.
