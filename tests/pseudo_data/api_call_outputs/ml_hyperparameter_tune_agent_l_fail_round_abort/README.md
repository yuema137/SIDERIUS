# `ml_hyperparameter_tune_agent_l_fail_round_abort/` — pseudo data for L.8 fail-round abort regression

Canned LLM responses for `tests/integration/workflows/test_l_fail_round_abort_dual_mode.py`,
which exercises the Phase L abort path end-to-end: an iteration that anchors
on one successful round and then collapses into 3 consecutive fail-rounds,
hitting `max_fail_rounds=3` and exiting with
`termination_reason="aborted_fail_rounds"` plus a Trigger B
`gate_exhaustion` summary for the next iteration's proposer.

This folder is used **only** by that test. The standard tuner pseudo-mode
test (`tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/`)
and the K.9 fallback test
(`tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent_k9_invented/`)
are left untouched.

## Why Trigger B (not Trigger A)

The earlier draft of the §11.8 spec called for an "all-9-OOM" choreography
to test the abort path, but that scenario hits **Trigger A** (no-successes
branch) of `_build_gate_exhaustion`, not **Trigger B**. The L.3
implementation gates Trigger B behind `completed_rounds > 0` so the two
triggers are mutually exclusive. To actually validate Trigger B's
"model too large after K successful rounds" framing — the load-bearing
claim of Phase L §11.4 — this fixture inserts a single successful round 1
before the fail-round burst.

## What this folder pairs with

- **Plugin file**: `tests/pseudo_data/plugins/pe_wavenet_delta.py`
  Loaded into `MODEL_REGISTRY` + `PLUGIN_CONFIG_REGISTRY` by the test
  fixture via `SIDERIUS_PLUGIN_DIRS=tests/pseudo_data/plugins` +
  `extend_registries(...)`. Reused from K.9 because the plugin is
  already wired and its 0.1 GB ceiling arithmetic
  (`hidden_dim=128` fits at ~26 MB; `hidden_dim=2048` busts at ~151 MB)
  is exactly what L.8 needs.
- **Sandbox results**: `tests/pseudo_data/train_outputs/pe_wavenet_delta/`
  Each file is a 2-element FIFO array (set up by L.7 for the K.9
  rewrite). L.8 only consumes 1 entry per method (one successful round 1
  attempt). The remaining entry is unused. The 9 OOM-skipped attempts
  in rounds 2-4 never reach the sandbox.

## Choreography (Phase L semantics)

With `max_rounds=4`, `attempts_per_round=3`,
`attempts_per_formal_round=3` (explicit override of default 5,
defensive — formal is never reached here), `max_fail_rounds=3`:

### Round 1, attempt 1 (`generate.json[0]`) — success

- Planner returns `hidden_dim=128`. VRAM gate fits (~26 MB <
  100 MB). Time gate disabled (`trial_time_budget_minutes=None`).
  Sandbox returns the canned training/inference/scoring trio.
  Reflector returns `reflect.json[0]`. Recorded as `success` with
  `round_index=1`, `attempt_in_round=1`. Round 1 succeeds:
  `completed_rounds` advances 0 → 1, `consecutive_fails` stays 0,
  inner loop breaks.

### Rounds 2, 3, 4 — three consecutive fail-rounds (9 OOM-skips total)

Each round runs its full 3-attempt budget on the oversized
`hidden_dim=2048` plan (no successful retries). Per Phase L's
success-counter-derived `round_index` rule, all 9 records carry
`round_index = completed_rounds + 1 = 2` (not 2/3/4) because
`completed_rounds` is stuck at 1.

- **Round 2** (`generate.json[1..3]`): 3 OOM-skips → inner budget
  exhausts → `consecutive_fails = 1`.
- **Round 3** (`generate.json[4..6]`): 3 OOM-skips → inner budget
  exhausts → `consecutive_fails = 2`.
- **Round 4** (`generate.json[7..9]`): 3 OOM-skips → inner budget
  exhausts → `consecutive_fails = 3 == max_fail_rounds` → outer
  loop aborts.

Round 4 does **not** trigger formal-promotion because the gate
condition is `completed_rounds == max_rounds - 1 == 3`, but
`completed_rounds` is still 1. So all 9 fail-attempts use
`attempts_per_round=3`, never `attempts_per_formal_round`.

Total: 10 records (1 success + 9 OOM-skip), 10 plan calls, 1 reflect call.

## Expected output contract

- `output.completed_rounds == 1`
- `output.consecutive_fail_rounds_at_exit == 3`
- `output.termination_reason == "aborted_fail_rounds"`
- `output.gate_exhaustion is not None` with Trigger B framing:
  - `summary_message` contains `"Model too large"` and
    `"3 consecutive rounds"` and `"after 1 successful round"`.

## Why budget = 0.1 GB

Inherited from K.9 — at this ceiling `hidden_dim=128` fits with
~75 MB headroom and `hidden_dim=2048` busts by ~50 MB. Both verdicts
are clean attributions to the params term.
