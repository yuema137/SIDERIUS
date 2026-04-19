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
  Returned by `RecordingSandbox` for round 2's `execute_training` /
  `execute_inference` / `execute_scoring` calls. Round 1 never reaches the
  sandbox — it is gated out at the VRAM check.

## Choreography

### Round 1 (`generate.json[0]`) — over budget

- Planner returns `hidden_dim=2048` for `pe_wavenet_delta`. Param count
  ≈ 9.4M (`2·H² + 512·H + 256` at H=2048).
- VRAM gate runs and emits `!!! [evaluate_vram_skill]` warning citing
  `pe_wavenet_delta` + the runtime fallback `inference_batch=25`. Predicted
  3-phase peak ≈ 151 MB (training overhead `16·params ≈ 150 MB` dominates;
  activation terms at `seg=1000`, `batch=1` add ~1 MB).
- Verdict: **over budget** (151 MB > 100 MB ceiling). Round 1 is recorded as
  `skipped_oom_risk` with `inference_batch_uncalibrated=True`. The reflector
  is **not** invoked on this round (per the tuner agent's skipped-record
  branch).

### Round 2 (`generate.json[1]`) — fits

- Planner reacts to the round 1 verdict by collapsing `hidden_dim` from 2048
  to 128 — every other lever held constant. Param count ≈ 98k.
- VRAM gate emits the same `!!! [evaluate_vram_skill]` warning (model_type is
  still unregistered) but predicted 3-phase peak ≈ 26 MB. Verdict: **fits**
  (26 MB < 100 MB).
- Time gate runs next, also emits `!!! [evaluate_time_skill]` warning, and
  passes (tiny model on a small sample set).
- `RecordingSandbox` returns the canned `train_outputs/pe_wavenet_delta/`
  trio. The reflector is invoked with the canned `denoising_score=0.65` and
  returns `reflect.json`.

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
