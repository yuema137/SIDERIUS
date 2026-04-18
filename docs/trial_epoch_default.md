# Time-budget-aware baseline_config refinement

**Status**: design v2 — tuner-owned baseline + refinement (2026-04-17)
**Branch**: `fix/trial-epoch-default`

---

## Progress log

| Date | Event | Commit |
|------|-------|--------|
| 2026-04-17 | ✅ Cleanup landed: dead `_apply_time_gate` removed from proposer. Independent of the refine design — keeps regardless of which architecture we pick. | `35834ca` |
| 2026-04-17 | ❌ **v1 attempt reverted**. Built a standalone `MLBaselineConfigRefinerAgent` between validate and tune (schemas + node + prompt + 36 unit tests). Reverted via `git reset --hard 35834ca` because the refined `baseline_config` was orphan data — `HyperparamTuningInput` carries no `baseline_config` field, so the refiner produced output nothing downstream consumed. Pushing it into the tuner would have required adding the field AND changing the tuner's planner to seed from it — at which point the tuner already owns the responsibility. | (3 commits dropped) |
| 2026-04-17 | 🔄 **v2 design active**: move baseline-config generation + refinement INTO the tuner. Documented below. Implementation not yet started. | — |

What's reusable from the reverted v1 work (will re-introduce inside the tuner):
- The **exceedance_ratio** idea — a quantitative time-gate signal (`estimated_minutes / limit_minutes`) so the LLM scales its cuts by overshoot magnitude (1.5x = light tweak, 10x = drastic surgery).
- The **system-prompt structure** — architecture OFF-LIMITS, ratio-scaled cuts, ordered lever list (epochs → width → depth → batch_size), strict JSON output.
- The **typed `TimeGateResult` / `RefineAttempt` schemas** — Pydantic mirrors of the skill's return shape so the tuner fails loudly at the schema layer if `evaluate_time_skill` changes its keys.

---

## Problem (unchanged)

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
interpret → propose ─┬─ proposer pre-flight time-gate
                     │   ❌ deleted in 35834ca (was dead code — silently
                     │      skipped for new model_types because _count_params
                     │      needs MODEL_REGISTRY[model_type], which doesn't
                     │      exist yet for a freshly proposed model).
                     │
                     ├─ implement (writes plugin .py)
                     ├─ validate (7 checks)
                     │
                     └→ tune ── per-round time-gate from here on
                                Each infeasible round becomes a
                                `skipped_time_risk` record. With
                                max_rounds=2, one bad baseline can
                                burn both rounds.
```

So today, the first real gate runs in the tuner, after implement +
validate already paid their cost. A bad baseline causes round-skip churn
instead of a config retry.

---

## v2 architecture: tuner owns baseline gen + refine

### The core move

`HyperparamTuningAgent` gains a **pre-loop "find a feasible round-0 config"
phase** that runs before its main planning loop:

```
tune.run(input):
    # NEW: pre-loop baseline-and-gate phase
    baseline_config, refine_history = find_feasible_baseline(
        model_type, plugin_config_class_source,
        time_budget, mode, max_refine_attempts=3,
    )
    if baseline_config is None:
        # exhausted — bubble back as "architecture too expensive"
        return HyperparamTuningOutput(status="architecture_too_expensive", ...)

    # EXISTING: main planning loop, now seeded with the feasible baseline
    for round in range(max_rounds):
        plan = planner(memory_history, baseline_config=baseline_config, ...)
        ...
```

Inside `find_feasible_baseline`:
1. Generate a starting baseline_config (LLM call from the architecture +
   PLUGIN_CONFIG_CLASS schema, or a deterministic default).
2. Run `evaluate_time_skill` against it.
3. If feasible → return.
4. If infeasible → call the refine LLM (architecture OFF-LIMITS, given
   exceedance_ratio + prior_attempts) → goto step 2.
5. After `max_refine_attempts`, return `(None, history)` so `tune.run`
   bubbles back to the workflow.

### Why this fits cleanly

- The tuner already owns config decisions every round; round-0 is just
  the first such decision.
- No protocol layer needed — `HyperparamTuningInput` doesn't change
  shape (no new orphan field).
- The refine loop's outputs are consumed by the same agent that produces
  them — locality of control.
- Bubble-back to "re-propose architecture" goes through an existing
  channel (`HyperparamTuningOutput.status`) instead of a new workflow
  branch.

### What changes in each module

| Module | Change |
|--------|--------|
| `agent/schemas/hyperparam_tuning.py` | (open Q1 below) — possibly add `time_budget_minutes` / `max_refine_attempts` if not already present; possibly capture `refine_history` in `HyperparamTuningOutput` for traceability. |
| `nodes/ml_hyperparameter_tune_agent.py` | Add `find_feasible_baseline()` private method + `_baseline_gen_prompt` + `_baseline_refine_prompt`. Wire into `run()` before the main loop. Handle exhaustion → return early with a status the workflow recognizes. |
| `nodes/ml_model_proposal_agent.py` | (open Q2 below) — proposer's `baseline_config` either stays purely for plugin defaults (implementor reads it, tuner ignores it) or drops entirely. |
| `workflows/model_exploration.py` | Recognize the new tuner exhaustion status and bubble it through the existing outer proposer-loop with `previous_failures` carrying *"architecture too expensive — try a smaller family"*. |
| Tests | Unit tests for `find_feasible_baseline` (mocked LLM + mocked skill); integration test (Tier 1) for the tuner exercising the refine path. |

### Open design questions (block implementation)

**Q1 — Does the proposer keep emitting `baseline_config`?**

Two options:

- **(a) Keep, demote to "plugin-defaults seed only"**: implementor reads
  it to set PLUGIN_CONFIG_CLASS field defaults so the validator can
  instantiate. Tuner ignores it and generates its own. *Smaller change,
  preserves the existing implementor flow.*
- **(b) Drop entirely**: implementor picks reasonable defaults itself
  based on the architecture description. *Cleaner conceptually but pushes
  more work into the implementor and may produce defaults that don't
  match the proposer's intent.*

Lean: **(a)** for the first cut — minimal blast radius, easy to revisit.

**Q2 — Where does the initial round-0 config come from inside the tuner?**

Three options:

- **(a) LLM call** with PLUGIN_CONFIG_CLASS + architecture description +
  budget. Symmetric with the refine call. Costs 1 extra LLM call per
  tune.
- **(b) Reuse the proposer's `baseline_config`** as the round-0 starting
  point (assumes Q1=(a)). Free; tuner only burns LLM calls when refining.
- **(c) Just the schema defaults** from PLUGIN_CONFIG_CLASS. Free, but
  dumb — defaults may already be infeasible for the active budget, so
  the refine loop runs almost every time.

Lean: **(b)** if Q1=(a) — uses the proposer's intent as the seed and
only refines when needed. Falls back to **(a)** if Q1=(b).

**Q3 — Does `find_feasible_baseline` belong inside `HyperparamTuningAgent`
or as a separate skill?**

- **Inside the agent** — simpler, but bloats the tuner.
- **Skill in `agent/skills/baseline_refine_skill/`** — testable in
  isolation, reusable if another agent ever needs it. Symmetric with
  `evaluate_time_skill` and `evaluate_resource_skill`.

Lean: **separate skill**, called from the tuner. The skill's `run()`
takes `(model_type, config_class_source, time_budget, mode, max_attempts,
seed_config?)` and returns `(feasible_config, refine_history)`.

---

## What we explicitly do NOT change

- `MLModelImplementor` is untouched (modulo Q1 fallout).
- `evaluate_time_skill` is untouched — pure feasibility checker.
- `MLCodeValidatorAgent` is untouched.
- The tuner's per-round time-gate stays — it's the runtime safety net for
  configs the planner mutates mid-run.

---

## Locked decisions (carried from v1)

1. **Proposer pre-flight gate**: deleted (dead code in production — landed
   in `35834ca`).
2. **Quantitative time-gate signal**: the refine call must see an
   `exceedance_ratio` (estimated/limit), not just totals. A 1.5x overshoot
   vs a 10x overshoot demand very different cuts.
3. **Architecture is OFF-LIMITS during refine**: only field VALUES inside
   the config may change. The validated model class accepts any value
   matching its Pydantic schema.
4. **Refine-loop exhaustion (3 attempts fail)**: bubble up as
   "architecture too expensive" so the outer proposer-loop re-rolls a
   smaller architecture family.
5. **`trial_max_epochs` knob**: dropped. The refine LLM sees the
   exceedance_ratio and reduces epochs as one of its levers — no separate
   cap.
6. **Lightweight LLM is fine** for refine — numeric optimization with a
   tight schema. `gpt-5.4-mini` by default; routable via `WorkflowLLMConfig`.

---

## Implementation plan (v2)

Steps are ordered for incremental landing — each step ships in its own
commit and leaves the tree green.

| # | Step | Verification |
|---|------|--------------|
| 1 | **Resolve Q1, Q2, Q3** above. | (design — no code) |
| 2 | If Q3 = separate skill: scaffold `agent/skills/baseline_refine_skill/` (manifest + wrapper + schema). Re-introduce the typed `TimeGateResult` / `RefineAttempt` from the reverted v1 work. | Schema unit tests. |
| 3 | Implement `find_feasible_baseline()` (skill or method). Mock both the LLM and `evaluate_time_skill`. | Unit tests: feasible-on-attempt-1, feasible-on-attempt-3, exhaustion-on-attempt-4, ratio surfaced in prompt, prior_attempts surfaced. |
| 4 | Wire into `HyperparamTuningAgent.run()` before the main loop. Add status field for exhaustion. | Existing tuner unit tests stay green; new tests for the pre-loop phase. |
| 5 | Update workflow to recognize the new exhaustion status and feed it back to the proposer. | Workflow unit test exercising the bubble-back path. |
| 6 | Tier 1 integration test for the tuner exercising the full refine path with a real LLM call. | `@real_run`, gated on API key. |
| 7 | Connection audit per CLAUDE.md step 7 — confirm no orphan fields, no silent defaults. | Run full unit suite. |

---

## Out of scope

- Changing the proposer's architecture-emission contract beyond Q1.
- Extending the refine loop to also gate on VRAM
  (`evaluate_resource_skill`). The architecture-proposer's existing gate
  catches VRAM infeasibility before implement. Add only if a real failure
  mode emerges.
- Splitting `HyperparamTuningAgent` into "baseline" + "tune" sub-agents.
  The whole point of v2 is that one agent owns config decisions; splitting
  it would re-create the v1 problem.
