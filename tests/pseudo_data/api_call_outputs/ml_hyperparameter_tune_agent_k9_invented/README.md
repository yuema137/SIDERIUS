# `ml_hyperparameter_tune_agent_k9_invented/` — pseudo data for K.9 fallback regression

Canned LLM responses for `tests/integration/workflows/test_k9_invented_model_dual_mode.py`,
which exercises the K.2.5-8 soft-fallback path (unregistered `model_type` in the
inference estimator) end-to-end through the tuner gate → record → memory pipeline.

This folder is used **only** by that test. The standard tuner pseudo-mode
test (`tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/`) is
left untouched so the existing pseudo-mode coverage continues to use a
registered seed (`punet`).

## What this folder pairs with

- **Plugin file**: `tests/pseudo_data/plugins/pe_wavenet_delta.py`
  Loaded into `MODEL_REGISTRY` + `PLUGIN_CONFIG_REGISTRY` by the test fixture
  via `SIDERIUS_PLUGIN_DIRS=tests/pseudo_data/plugins` +
  `extend_registries(...)`. Without this, `_count_params` crashes at registry
  lookup before the K.2.5-8 path can ever fire.
- **Sandbox results**: `tests/pseudo_data/train_outputs/pe_wavenet_delta/`
  Returned by `RecordingSandbox` for the two non-skipped attempts in this
  choreography: round 1 attempt 2 (trial) and round 2 attempt 1 (formal).
  Each of `execute_training.json`, `execute_inference.json`, and
  `score_vector.json` is therefore a 2-element JSON array (FIFO-popped
  per call). Round 1 attempt 1 never reaches the sandbox — it is gated
  out at the VRAM check, so the queue depth is exactly 2, not 3.
  **Both trial and formal modes use `sandbox.score_vector` (not
  `sandbox.execute_scoring`)** because the tuner takes the anchor-normalised
  path whenever `segment_anchors.json` is present, which `RecordingSandbox`
  stubs at construction time. `execute_scoring.json` is kept alongside the
  others as a single-entry stub for symmetry with the existing
  `train_outputs/punet/` folder, but is unused in this test (the agent
  takes the score_vector branch for both rounds).

## Choreography (Phase L semantics)

Under Phase L (`docs/resource_estimator_implement.md` §11), the outer
loop counts only successes against `max_rounds`; an OOM-skipped attempt
consumes one slot of the inner per-round budget but does not advance
`completed_rounds`. With `max_rounds=2`, `attempts_per_round=3`
(default), `attempts_per_formal_round=5` (default), `max_fail_rounds=3`,
the test produces **3 records** across **2 successful rounds**:

### Round 1, attempt 1 (`generate.json[0]`) — over budget

- Planner returns `hidden_dim=2048` for `pe_wavenet_delta`. Param count
  ≈ 9.4M (`2·H² + 512·H + 256` at H=2048).
- VRAM gate runs and emits `!!! [evaluate_vram_skill]` warning citing
  `pe_wavenet_delta` + the runtime fallback `inference_batch=25`. Predicted
  3-phase peak ≈ 151 MB (training overhead `16·params ≈ 150 MB` dominates;
  activation terms at `seg=1000`, `batch=1` add ~1 MB).
- Verdict: **over budget** (151 MB > 100 MB ceiling). Recorded as
  `skipped_oom_risk` with `inference_batch_uncalibrated=True`,
  `round_index=1`, `attempt_in_round=1`. The reflector is **not** invoked
  on this attempt (per the tuner agent's skipped-record branch). Round 1
  is **not** a success yet — the inner attempt budget continues.

### Round 1, attempt 2 (`generate.json[1]`) — fits, round 1 succeeds

- Planner reacts to the attempt 1 verdict by collapsing `hidden_dim` from
  2048 to 128 — every other lever held constant. Param count ≈ 98k.
- VRAM gate emits the same `!!! [evaluate_vram_skill]` warning (model_type
  still unregistered) but predicted 3-phase peak ≈ 26 MB. Verdict:
  **fits** (26 MB < 100 MB).
- Time gate runs next, also emits `!!! [evaluate_time_skill]` warning,
  and passes (tiny model on a small sample set).
- `RecordingSandbox` returns the canned `train_outputs/pe_wavenet_delta/`
  trio. The reflector is invoked with the canned `denoising_score=0.65`
  and returns `reflect.json[0]`. Recorded as `success` with
  `round_index=1`, `attempt_in_round=2`. Round 1 succeeds:
  `completed_rounds` advances 0 → 1, `consecutive_fails` resets to 0,
  inner loop breaks.

### Round 2, attempt 1 (`generate.json[2]`) — formal promotion

- `completed_rounds == max_rounds - 1 == 1` so the agent forces
  `plan.is_trial = False` regardless of what the canned plan claims.
- Planner returns `hidden_dim=128` (same architecture as round 1's
  successful attempt) for the formal-mode validation.
- Gate emits the K.2.5-8 warning again (still unregistered) and verdicts
  fits at the same ~26 MB peak.
- Sandbox + reflector run with `reflect.json[1]`. Recorded as `success`
  with `round_index=2`, `attempt_in_round=1`. Round 2 succeeds:
  `completed_rounds` 1 → 2, outer loop exits with
  `termination_reason="completed"`.

Total: 3 records (1 OOM-skip + 2 success), 3 plan calls, 2 reflect calls.
The Phase L formal-budget asymmetry (`attempts_per_formal_round=5`) is
unused because round 2 succeeds on attempt 1 — for the
fail-then-abort variant see
`tests/integration/workflows/test_l_fail_round_abort_dual_mode.py` (L.8).

## Why budget = 0.1 GB

Picked so that at `seg=1000, batch=1`:
- `hidden_dim=2048`: 3-phase peak ≈ 151 MB → fails by ~50 MB margin
  (clean attribution to the params term, not activation noise).
- `hidden_dim=128`: 3-phase peak ≈ 26 MB → passes with ~75 MB headroom
  (large enough that K.2.5-8's runtime fallback `inference_batch=25`
  can't accidentally tip the verdict either way).

Tightening to 0.05 GB would block round 2 too; loosening to 1 GB would
let round 1 through and we'd lose the over-budget evidence layer.

## Why `device="cuda"` in `train_config`

The VRAM gate's wrapper short-circuits to `feasible=True` when
`train_config.device != "cuda"` (see `agent/skills/evaluate_vram_skill/wrapper.py`
lines 207–218). The K.2.5-8 warning still fires before that check, but the
over/under-budget verdict path is only reachable with `device="cuda"`. The
K.9.1 test fixture monkeypatches `torch.cuda.is_available()` → True and
`torch.cuda.mem_get_info()` → `(20 GB free, 32 GB total)` so the test is
deterministic and runs on machines without a real GPU. The defensive cap
`0.8 × 20 GB = 16 GB` therefore never binds; the binding ceiling is the
operator budget (0.1 GB).

## Why `loss_type=ce`, not `focal`

Keeps the VRAM breakdown free of the `focal_onehot_bytes` term so the
post-mortem comparison between rounds attributes the entire delta to the
params term and nothing else. The choice has no effect on the K.2.5-8 path
itself — that fires regardless of loss.

## Why `model_type_setting="pe_wavenet_delta"` (set by the test, not here)

The tuner agent overrides `plan["model_type"]` with `model_type_setting` for
the whole run when the latter is not `"auto"` (see
`nodes/ml_hyperparameter_tune_agent.py:690-693`). Both rounds therefore use
`pe_wavenet_delta` regardless of what these canned plans claim. The lever is
purely architectural — there is no model-swap branch in this test.
