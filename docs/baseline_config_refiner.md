# Time-budget-aware baseline_config refinement

**Status**: design (2026-04-17)
**Branch**: `fix/trial-epoch-default` (will likely rename — branch name no longer matches scope)

## Problem

The current workflow burns implement+validate work before discovering that
a baseline_config can't fit the time budget. The first effective time-check
happens inside the tuner, after a full propose → implement → validate cycle
already completed. When the tuner rejects the config on time, the workflow
either (a) re-runs the whole outer loop (re-propose + re-implement +
re-validate), or (b) the tuner spins through round-skips against a
fundamentally infeasible baseline.

The user's read: **the model code itself is fine; only the config needs to
change. We shouldn't re-implement just because the config is too slow.**

## Where today's time-gate actually fires

```
interpret → propose ─┬─ proposer pre-flight time-gate (line 49 of
                     │   nodes/ml_model_proposal_agent.py)
                     │   ❌ silently skipped for new model_types because
                     │      _count_params needs MODEL_REGISTRY[model_type],
                     │      which doesn't exist yet (line 114-119: status=error
                     │      → leaves time_risk=None, returns).
                     │
                     ├─ implement (writes plugin .py)
                     ├─ validate (7 checks)
                     │
                     └→ tune ── per-round time-gate from here on
                                (line 595 of nodes/ml_hyperparameter_tune_agent.py)
                                Each infeasible round becomes a `skipped_time_risk`
                                record. With max_rounds=2, one bad baseline can
                                burn both rounds.
```

So for any **new** plugin model:
- The proposer's gate is effectively dead.
- The first real gate runs in the tuner, after implement + validate already
  paid their cost.
- A bad baseline causes round-skip churn instead of a config retry.

## User's proposal

> Code validation is a step before config proposing. If the config can't
> pass the time requirement, it doesn't mean we need to re-implement. We
> should first validate the code itself, then have ~3 retries for the base
> config. The base config proposer should know the time budget, and on
> retry it should see how much the previous config exceeded the budget and
> adjust.

This separates **code** (model class + schema) from **data** (concrete
baseline values). Code is implemented + validated once. Config is
proposed-and-gated in its own retry loop.

## Proposed workflow

```
interpret
  → propose (architecture + initial baseline_config)
  → implement → validate (inner retry on validator failure)
  → [NEW] config-refine-and-gate loop, max 3 attempts:
        attempt 1: run time-gate against the proposer's baseline_config
                   ✅ feasible → break
                   ❌ infeasible → call MLConfigRefinerAgent with
                                   (validated PLUGIN_CONFIG_CLASS schema,
                                    current config, time-gate verdict,
                                    time-gate suggestion, prior attempts)
                                → refiner emits a new baseline_config
                                  (same architecture, adjusted
                                   segmentation_size / batch_size /
                                   epochs / etc.)
        attempts 2-3: same gate → refine cycle
        exhausted: log warning, proceed with last attempt
                   (tuner's per-round gate is the final safety net)
  → tune (uses refined baseline_config as round-0 starting point)
```

Key invariants preserved:
- The model **class** never changes during the refine loop — only field
  *values* do. The validated class accepts any value matching its Pydantic
  schema (default values are just defaults).
- The tuner's per-round time-gate stays — it's the runtime safety net for
  configs the planner mutates mid-run. The new refine loop is a one-shot
  pre-tune gate, not a replacement.
- The existing proposer-stage time-gate stays for re-used model_types
  (where it's not a no-op) as a sanity check.

## Architectural decision: new agent vs. extend proposer

**Per CLAUDE.md** ("each agent is scoped to one well-defined category of
task"), a new agent is cleaner than overloading `MLModelProposalAgent`.

Proposed: `MLBaselineConfigRefinerAgent` (`ml_` prefix per the convention).

| Field                           | Type / source                                         |
|---------------------------------|-------------------------------------------------------|
| `model_type`                    | str — from validated proposal                         |
| `config_class_source`           | str — the PLUGIN_CONFIG_CLASS source from the plugin |
| `current_config`                | dict — last attempt's baseline_config                 |
| `time_gate_result`              | dict — verdict, estimated_minutes, limit_minutes, suggestion, breakdown |
| `prior_attempts`                | list[dict] — all (config, time_gate_result) pairs so the LLM doesn't repeat past mistakes |
| `time_budget_minutes`           | float                                                 |
| `mode`                          | "trial" or "formal" — which budget is active          |

Output: `RefinedBaselineConfig { baseline_config: dict, rationale: str }`.

The agent's prompt makes the contract explicit:
*"You may change values for any field in the config schema, but you must
not change the architecture. The previous config exceeded the budget by
X min — adjust accordingly. Specifically, the suggestion was Y. Don't
repeat values that already failed (see prior_attempts)."*

Lightweight LLM is fine — this is a numeric optimization task with a tight
schema. Use the validator-tier model (e.g., gpt-5.4-mini) by default.

## Files that change

| File | Change |
|------|--------|
| `agent/schemas/baseline_refiner.py` (new) | `BaselineRefinerInput` + `BaselineRefinerOutput` Pydantic schemas |
| `nodes/ml_baseline_config_refiner_agent.py` (new) | `MLBaselineConfigRefinerAgent` with `run()` method |
| `agent/prompts.py` | New `BASELINE_REFINER_PROMPT` system prompt + user-prompt builder |
| `workflows/model_exploration.py` | Insert refine-and-gate loop between validate and tune; on refine-loop exhaustion, bubble to outer proposer-loop with `previous_failures` carrying the "architecture too expensive" message |
| `agent/schemas/protocols/ml_model_valid_to_ml_baseline_refine.py` (new) | Protocol — validator output → refiner input |
| `agent/schemas/protocols/ml_baseline_refine_to_ml_model_tune.py` (new) | Protocol — refiner output → tuner input (replaces direct `local_validated_model` for the baseline_config field) |
| `tests/unit/agent/ml_baseline_config_refiner_agent/test_*.py` (new) | Unit tests with mocked LLM |
| `tests/unit/agent/protocols/test_*.py` (new) | Two new protocol tests |
| `tests/integration/nodes/test_ml_baseline_config_refiner_agent.py` (new) | Tier 1 real-API test (`@real_run`) |

Per CLAUDE.md's 8-step graph-node checklist, this is a full new node.

## Cleanup commit (separate, lands first)

The proposer's `_apply_time_gate` is dead code — verified 2026-04-17. Both
production callers (`workflows/model_exploration.py:556` and the standalone
CLI at `nodes/ml_model_proposal_agent.py:965`) only ever pass NEW
`model_name` values (line 405 of the proposer's prompt forbids reuse, and
the workflow enforces it via `existing_model_types`). The skill's
`_count_params` always errors at `MODEL_REGISTRY[model_type](config)` →
the gate always takes the silent-no-op branch. The 13 unit tests in
`test_baseline_time_gate.py` mock the skill, so they verify wiring of code
that doesn't fire in production.

Delete in one mechanical commit before the refiner work:
- `_apply_time_gate` function + its call site in `nodes/ml_model_proposal_agent.py`
- `_TIME_GATE_WARNED` module-level flag
- `tests/unit/agent/ml_model_proposal_agent/test_baseline_time_gate.py` (entire file)
- `ProposalOutput.time_risk` field (in `agent/schemas/proposal.py`)
- The `proposal.time_risk` read in `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` (and the prepend-to-expert_advice logic that follows it)

## What we explicitly do NOT change

- `MLModelProposalAgent` keeps emitting `baseline_config` — it's the seed
  for refine-attempt-1, and the no-refine-needed common case still works.
- `MLModelImplementor` is untouched — it still receives baseline_config
  for default-value derivation.
- `evaluate_time_skill` is untouched — it's a pure feasibility checker.
- `MLCodeValidatorAgent` is untouched.
- The tuner's per-round time-gate stays.

## Locked decisions

1. **Proposer pre-flight gate**: delete (dead code in production — see
   cleanup commit above).
2. **Refiner-loop exhaustion (3 attempts fail)**: bubble up to outer
   `max_proposal_attempts` loop. The exhaustion is read as evidence that
   the architecture itself is too expensive — re-propose architecture with
   `previous_failures` carrying *"baseline could not fit time budget after
   3 refine attempts; the architecture is too expensive — try a smaller
   or cheaper architecture family"*.
3. **`trial_max_epochs` knob**: dropped. The refiner sees the time-gate
   verdict and reduces epochs as one of its levers — no separate cap.
4. **Three-loop cascade**:

   | Loop | Trigger | What re-runs |
   |------|---------|---------------|
   | `max_impl_attempts` (existing, default 3) | Validator fails | Implementor only (same proposal) |
   | `max_refine_attempts` (NEW, default 3) | Time-gate fails | Refiner only (same code, same architecture) |
   | `max_proposal_attempts` (existing, default 3) | Either inner loop exhausts | Full propose → implement → validate → refine |

5. **Branch**: stays `fix/trial-epoch-default`.

## Test plan

- Unit tests for the new agent (mocked LLM): refiner respects schema,
  refiner sees prior_attempts, refiner emits valid Pydantic output.
- Unit tests for both new protocols.
- Workflow unit test: `tests/unit/workflows/test_model_exploration.py`
  gains coverage of the refine loop — feasible-on-first-attempt skips the
  refiner; infeasible-on-first triggers refiner; refiner-feasible breaks
  the loop; 3-attempt-exhaustion bubbles to outer proposer-loop with the
  "architecture too expensive" message.
- Tier 1 real-API integration test for the new node.
- The 1-min smoke test we ran for Phase 4 should now show the refiner
  kicking in (configs that were infeasible at 1 min should converge into
  the budget within 3 refine attempts).

## Out of scope

- Changing the architecture-proposer's baseline_config emission (it
  remains the seed for refine-attempt-1).
- Extending the refine loop to also gate on VRAM (`evaluate_resource_skill`).
  The architecture-proposer's existing gate already catches VRAM
  infeasibility before implement. Add only if a real failure mode
  emerges.
