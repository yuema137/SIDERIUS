# Time-budget-aware baseline_config refinement

**Status**: design v3 — separated responsibilities + tuner→proposer feedback loop (2026-04-17)
**Branch**: `fix/trial-epoch-default`

---

## Progress log

| Date | Event | Commit |
|------|-------|--------|
| 2026-04-17 | ✅ Cleanup landed: dead `_apply_time_gate` removed from proposer. Independent of the refine design — keeps regardless of which architecture we pick. | `35834ca` |
| 2026-04-17 | ❌ **v1 attempt reverted**. Built a standalone `MLBaselineConfigRefinerAgent` between validate and tune (schemas + node + prompt + 36 unit tests). Reverted via `git reset --hard 35834ca` because the refined `baseline_config` was orphan data — `HyperparamTuningInput` carries no `baseline_config` field, so the refiner produced output nothing downstream consumed. | (3 commits dropped) |
| 2026-04-17 | 🔄 **v2 design**: move baseline-config generation + refinement INTO the tuner. Documented but not implemented. Open Q1/Q2/Q3 left unresolved. | `9fd1c04` |
| 2026-04-17 | 🔄 **v3 design active** (this doc): v2 + the missing piece — explicit feedback edge from tuner exhaustion back to the proposer, so a too-heavy architecture causes a re-roll, not silent round-skip churn. Resolves Q1 (proposer drops `baseline_config`), Q2 (tuner generates its own), and adds Q4 (feedback channel). | — |

What's reusable from the reverted v1 work (will re-introduce inside the tuner):
- The **exceedance_ratio** idea — a quantitative time-gate signal (`estimated_minutes / limit_minutes`) so the LLM scales its cuts by overshoot magnitude (1.5x = light tweak, 10x = drastic surgery).
- The **system-prompt structure** for the refine call — architecture OFF-LIMITS, ratio-scaled cuts, ordered lever list (epochs → width → depth → batch_size), strict JSON output.
- The **typed `TimeGateResult` / `RefineAttempt` schemas** — Pydantic mirrors of the skill's return shape so the tuner fails loudly at the schema layer if `evaluate_time_skill` changes its keys.

---

## Problem statement

Three concrete gaps exist in today's pipeline:

1. **Orphan baseline_config from the proposer.** `ml_model_proposal_agent` emits a `baseline_config` field as part of `ProposalOutput`. The implementor reads it (to set plugin defaults so the validator can instantiate), but the tuner does NOT — `HyperparamTuningInput` has no `baseline_config` field. The proposer is also responsible for *picking starting hyperparameters* even though it is an architecture-design agent. This conflates responsibilities and produces data that is never time-checked nor consumed by the agent that would actually use it.

2. **No escape hatch from the tuner when the architecture is fundamentally too slow.** The tuner's per-round time-gate (`nodes/ml_hyperparameter_tune_agent.py:595`) emits a `skipped_time_risk` record and `continue`s the loop when a config exceeds the budget. The loop bails only at `total_attempts >= max_rounds * 3`. For a heavy architecture (e.g. RNN with sequence length 200k), every config the planner produces will overshoot, so the tuner burns 9 attempts (for `max_rounds=3`) on a fundamentally infeasible architecture before giving up.

3. **No feedback loop from tuner failures to the proposer.** When the tuner exits with `status="partial"` and `completed_rounds=0`, `workflows/model_exploration.py` (line 700) just appends the result and moves to the next iteration. The proposer's `previous_failures` list (line 519) is populated only by validation/proposal errors, never by tuner outcomes. So the next iteration's proposer has no signal that "the previous architecture was untunable in any feasible config" and may propose another equally heavy architecture for the same reason.

The user's framing: **the proposer should not worry about the config start point. The tuner should propose its own config when none is provided. When the tuner exhausts its attempts, the proposer needs to hear about it so it knows the architecture itself is too complex/slow given the time budget** (e.g. RNN at full sequence length).

---

## Flow chart

### Current state — gaps annotated

```
┌─────────────────────────────────────────────────────────────────────┐
│ workflows/model_exploration.py — outer architecture loop            │
│                                                                     │
│   for iteration in range(max_iterations):                           │
│                                                                     │
│     ml_result_interpretation_agent                                  │
│              │                                                      │
│              ▼                                                      │
│     ml_model_proposal_agent                                         │
│       emits architecture (model class)                              │
│       emits baseline_config ◀── ❶ ORPHAN: never time-checked,       │
│                                  not consumed by the tuner.         │
│              │                                                      │
│              ▼                                                      │
│     ml_model_implementor                                            │
│       (uses baseline_config only to set plugin defaults)            │
│              │                                                      │
│              ▼                                                      │
│     ml_code_validator_agent  (no time-check)                        │
│              │                                                      │
│              ▼                                                      │
│     ┌─ tune_ml_hyperparam_agent — INNER ROUND LOOP ─────────────┐   │
│     │  while completed < max_rounds                             │   │
│     │     and total_attempts < max_rounds * 3:                  │   │
│     │                                                           │   │
│     │     planner LLM → active_params (fresh per round)         │   │
│     │              │                                            │   │
│     │              ▼                                            │   │
│     │     evaluate_time_skill (line 595)                        │   │
│     │       feasible? ── yes → train + score                    │   │
│     │              │                                            │   │
│     │              no → emit skipped_time_risk + continue       │   │
│     │                   ❷ no escape hatch — burns 9 attempts    │   │
│     │                      on a too-heavy architecture          │   │
│     └───────────────────────────────────────────────────────────┘   │
│              │                                                      │
│              ▼                                                      │
│     iteration_results.append(tune_output)                           │
│     ❸ workflow does NOT inspect tune_output.status / completed_rounds│
│        does NOT append "tuner exhausted" to previous_failures        │
│                                                                     │
│     next iteration → proposer sees no signal → may re-propose       │
│       another architecture that's just as time-infeasible           │
└─────────────────────────────────────────────────────────────────────┘
```

### Target state (v3) — separated responsibilities + feedback edge

```
┌─────────────────────────────────────────────────────────────────────┐
│ workflows/model_exploration.py — outer architecture loop            │
│                                                                     │
│   for iteration in range(max_iterations):                           │
│                                                                     │
│     ml_result_interpretation_agent                                  │
│              │                                                      │
│              ▼                                                      │
│     ml_model_proposal_agent                                         │
│       emits architecture (model class) ONLY                         │
│       ✂ baseline_config DROPPED from ProposalOutput contract        │
│       reads previous_failures, which now includes                   │
│         "TUNER_EXHAUSTED: architecture <X> infeasible under         │
│          <budget> min — exceedance_ratio peaked at <r>x"            │
│              │                                                      │
│              ▼                                                      │
│     ml_model_implementor                                            │
│       (sets plugin defaults from PLUGIN_CONFIG_CLASS schema         │
│        defaults — no baseline_config dependency)                    │
│              │                                                      │
│              ▼                                                      │
│     ml_code_validator_agent                                         │
│              │                                                      │
│              ▼                                                      │
│     ┌─ tune_ml_hyperparam_agent ──────────────────────────────────┐ │
│     │                                                             │ │
│     │  PRE-LOOP: find_feasible_baseline()                         │ │
│     │     ┌─ generate seed config (LLM call from architecture +   │ │
│     │     │   PLUGIN_CONFIG_CLASS schema + budget)                │ │
│     │     ▼                                                       │ │
│     │  ┌─→ evaluate_time_skill                                    │ │
│     │  │   feasible?                                              │ │
│     │  │     yes → return baseline_config                         │ │
│     │  │     no  → refine LLM call (architecture OFF-LIMITS,      │ │
│     │  │           sees exceedance_ratio + prior attempts)        │ │
│     │  └───── back to gate                                        │ │
│     │     after max_refine_attempts (default 3) all infeasible:   │ │
│     │       return (None, history)                                │ │
│     │              │                                              │ │
│     │              ▼                                              │ │
│     │     baseline is None? ─── yes → return                      │ │
│     │                              HyperparamTuningOutput(        │ │
│     │                                status="architecture_too_   │ │
│     │                                       expensive",          │ │
│     │                                refine_history=...)         │ │
│     │              │ no                                          │ │
│     │              ▼                                              │ │
│     │  MAIN LOOP: planner seeded with the feasible baseline       │ │
│     │    while completed < max_rounds:                            │ │
│     │      planner → active_params → time-gate (existing) →       │ │
│     │      train + score                                          │ │
│     └─────────────────────────────────────────────────────────────┘ │
│              │                                                      │
│              ▼                                                      │
│     workflow inspects tune_output.status:                           │
│       if status == "architecture_too_expensive":                    │
│         previous_failures.append(                                   │
│           f"TUNER_EXHAUSTED: <model_type> infeasible under "        │
│           f"<budget> min — peak exceedance_ratio <r>x. "            │
│           f"Try a smaller architecture family.")                    │
│         continue  # re-roll architecture in the next iteration      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## v3 architecture: separated responsibilities

### Three locked principles (driving the design)

1. **Proposer's job is architecture, not hyperparameters.** `ml_model_proposal_agent` proposes the model class (layers, activations, structural choices). It must NOT pick a starting `baseline_config` for the tuner. `ProposalOutput.baseline_config` is dropped.
2. **Tuner generates its own starting config when none is provided.** `HyperparamTuningAgent` gains a pre-loop `find_feasible_baseline()` phase: produce a seed config from the architecture + `PLUGIN_CONFIG_CLASS` schema + budget, then refine until feasible (or exhaust).
3. **Tuner exhaustion bubbles back to the proposer.** When `find_feasible_baseline()` returns `None`, the tuner exits with `status="architecture_too_expensive"`. The workflow recognizes this status, appends a diagnostic line to `previous_failures`, and the proposer's next iteration sees "the prior architecture was infeasible — try a smaller family" (e.g. RNN at sequence length 200k → maybe a TCN with stride-4 instead).

### Why the feedback edge matters (the RNN example)

Suppose the proposer emits an RNN over the full audio sequence. Every config the tuner tries — even at 1 epoch, batch=1, hidden=8 — will exceed a 1-minute trial budget because the per-step cost is dominated by sequence length (a structural property of the architecture). Without the feedback edge, the tuner burns 9 round-attempts on the RNN, then the workflow moves on. The next iteration's proposer, seeing no failure signal, might propose another full-sequence RNN with slightly different attention. With the feedback edge, the proposer's `previous_failures` carries a clear "TUNER_EXHAUSTED: <model_type> infeasible under <budget>" line, telling the LLM to pick a fundamentally lighter architecture.

### What changes in each module

| Module | Change |
|--------|--------|
| `agent/schemas/proposal.py` | **Drop `baseline_config` from `ProposalOutput`** (and from the proposer's output gate). Update the proposer's system prompt to stop emitting it. |
| `nodes/ml_model_implementor.py` | Stop reading `baseline_config`. Use `PLUGIN_CONFIG_CLASS` field defaults to make the plugin instantiable for the validator. |
| `agent/schemas/hyperparam_tuning.py` | Add `status="architecture_too_expensive"` to `HyperparamTuningOutput.status` Literal; add optional `refine_history: list[RefineAttempt]` field for traceability; add optional `seed_config: dict \| None` input field (for tests / future override — defaults to `None` so the tuner generates its own). |
| `nodes/ml_hyperparameter_tune_agent.py` | Add `find_feasible_baseline()` private method (or skill — see Q3 below). Wire into `run()` BEFORE the main loop. On exhaustion, return early with `status="architecture_too_expensive"` and `refine_history` populated. The pre-loop baseline becomes the seed for the planner's first round. |
| `workflows/model_exploration.py` | After `tune_output = HyperparamTuningAgent().run(tune_input)` (line 699), inspect `tune_output.status`. If `"architecture_too_expensive"`, append a structured line to `previous_failures` and `continue` to the next iteration. Otherwise proceed as today. |
| `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` | No protocol changes (no new field on the input side — tuner generates its own seed). |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | No change — `previous_failures` is already a `list[str]` populated by the workflow. |

### Open design questions

**Q3 — `find_feasible_baseline` location: agent method or separate skill?**

- **Inside `HyperparamTuningAgent`** — simpler wiring, no new file tree. Bloats the agent slightly.
- **Separate skill in `agent/skills/baseline_refine_skill/`** — testable in isolation, mockable per-attempt, symmetric with `evaluate_time_skill`. Slight overhead (manifest + wrapper).

**Lean: separate skill.** Reasons: (a) the refine loop is independently testable (mocked LLM + mocked `evaluate_time_skill`); (b) symmetry with the existing skill registry pattern; (c) keeps the tuner agent focused on planning. Skill signature:

```python
class BaselineRefineSkillInput(BaseModel):
    model_type: str
    plugin_config_class_source: str   # the plugin's PLUGIN_CONFIG_CLASS Pydantic source
    architecture_description: str     # from ProposalOutput
    time_budget_minutes: float
    mode: Literal["trial", "formal"]
    data_dir: str | None
    max_attempts: int = 3
    seed_config: dict | None = None   # optional caller-supplied starting point

class BaselineRefineSkillOutput(BaseModel):
    feasible_config: dict | None      # None if exhausted
    refine_history: list[RefineAttempt]
    final_exceedance_ratio: float | None
```

**Q4 (NEW) — Diagnostic format for the `previous_failures` line.**

The proposer's LLM consumes `previous_failures` as plain strings. The line needs to be (a) parseable enough that the LLM understands "this was a tuner-stage failure, not a validation failure", and (b) carry enough quantitative signal for the LLM to scale its response.

Proposed format:

```
TUNER_EXHAUSTED: <model_type> infeasible under <budget> min budget
(<mode> mode). Refine attempts: <N>. Peak exceedance_ratio: <r>x.
Last config tried: <one-line summary>. Recommend a lighter
architecture family (e.g. fewer layers, smaller hidden dim,
strided/pooled processing, or a different model class).
```

Lean: **commit to the format above** — it's structured enough to be consumed by the LLM without parsing, and the `TUNER_EXHAUSTED:` prefix lets the proposer distinguish it from validation failures.

---

## What we explicitly do NOT change

- `MLModelImplementor`'s overall flow is untouched; only the source of plugin-default values changes (schema defaults instead of proposer's baseline_config).
- `evaluate_time_skill` is untouched — pure feasibility checker.
- `MLCodeValidatorAgent` is untouched.
- The tuner's per-round time-gate stays — it's the runtime safety net for configs the planner mutates mid-run after the pre-loop seeds a feasible starting point.
- No new outer-graph node — the feedback edge reuses the existing `previous_failures` channel that the proposer already reads.

---

## Locked decisions (carried forward)

1. **Proposer pre-flight gate**: deleted (dead code in production — landed in `35834ca`).
2. **Quantitative time-gate signal**: the refine call must see an `exceedance_ratio` (estimated/limit), not just totals. A 1.5x overshoot vs a 10x overshoot demand very different cuts.
3. **Architecture is OFF-LIMITS during refine**: only field VALUES inside the config may change. The validated model class accepts any value matching its Pydantic schema.
4. **Refine-loop exhaustion (3 attempts fail)**: bubble up as `status="architecture_too_expensive"` so the workflow re-rolls a smaller architecture family on the next iteration.
5. **`trial_max_epochs` knob**: dropped. The refine LLM sees the exceedance_ratio and reduces epochs as one of its levers — no separate cap.
6. **Lightweight LLM is fine** for refine — numeric optimization with a tight schema. `gpt-5.4-mini` by default; routable via `WorkflowLLMConfig`.
7. **Q1 RESOLVED**: proposer drops `baseline_config` entirely. Implementor uses `PLUGIN_CONFIG_CLASS` schema defaults for instantiation.
8. **Q2 RESOLVED**: tuner generates its own round-0 seed via `find_feasible_baseline()`. No reliance on proposer output.

---

## Implementation plan (v3) — checklists

Each step below ships as its own commit and leaves the tree green. Run only the tests for the modules you touch (per memory `feedback_run_relevant_tests_only`).

### Step 1 — Resolve open questions
- [ ] Confirm Q3 lean (separate skill) with user
- [ ] Confirm Q4 lean (diagnostic format) with user
- [ ] Confirm the implementor can instantiate plugins from `PLUGIN_CONFIG_CLASS` defaults alone (smoke-test on 2-3 existing plugins)

### Step 2 — Drop `baseline_config` from the proposer
- [ ] Remove `baseline_config` from `agent/schemas/proposal.py` `ProposalOutput`
- [ ] Remove the model_validator that sanity-checks baseline_config (lines ~715-720 in proposal.py)
- [ ] Update proposer system prompt to stop emitting it
- [ ] Update implementor (`nodes/ml_model_implementor.py`) to use `PLUGIN_CONFIG_CLASS` defaults instead of `proposal.baseline_config`
- [ ] Update unit tests for `MLModelProposalAgent` (drop baseline_config assertions)
- [ ] Update unit tests for `MLModelImplementor` (cover the schema-defaults path)
- [ ] Run: `tests/unit/agent/ml_model_proposal_agent/`, `tests/unit/agent/ml_model_implementor/`

### Step 3 — Scaffold `baseline_refine_skill` (assumes Q3 = separate skill)
- [ ] Create `agent/skills/baseline_refine_skill/`
  - [ ] `manifest.json`
  - [ ] `wrapper.py`
  - [ ] `schema.py` — re-introduce `TimeGateResult` + `RefineAttempt` from reverted v1 work, add `BaselineRefineSkillInput` / `BaselineRefineSkillOutput`
  - [ ] `system_prompt.py` — re-use ratio-scaled refine prompt from v1
- [ ] Schema unit tests in `tests/unit/agent/baseline_refine_skill/test_schema.py`
- [ ] Run: `tests/unit/agent/baseline_refine_skill/`

### Step 4 — Implement `find_feasible_baseline` logic in the skill wrapper
- [ ] Generate seed config (LLM call from architecture + PLUGIN_CONFIG_CLASS schema + budget)
- [ ] Loop: call `evaluate_time_skill` → if feasible return; if not, refine LLM call
- [ ] Return `(feasible_config, refine_history)` or `(None, refine_history)` on exhaustion
- [ ] Unit tests: feasible-on-attempt-1, feasible-on-attempt-3, exhaustion-on-attempt-4, exceedance_ratio surfaced in prompt, prior_attempts surfaced in prompt
- [ ] Use `RecordingLLMBridge` for LLM mocking (per existing test patterns)
- [ ] Run: `tests/unit/agent/baseline_refine_skill/`

### Step 5 — Wire skill into `HyperparamTuningAgent`
- [ ] Add `status="architecture_too_expensive"` to `HyperparamTuningOutput.status` Literal
- [ ] Add optional `refine_history` field to `HyperparamTuningOutput`
- [ ] In `run()`, before the main loop: call `BaselineRefineSkill` with the active budget (trial vs formal)
- [ ] If returned config is `None`: build and return `HyperparamTuningOutput(status="architecture_too_expensive", refine_history=...)`
- [ ] Otherwise: pass the feasible baseline to the planner as the round-0 seed
- [ ] Existing tuner unit tests stay green
- [ ] New tests: pre-loop returns feasible → main loop runs; pre-loop exhausts → tuner returns early with right status
- [ ] Run: `tests/unit/agent/tune_ml_hyperparam_agent/`

### Step 6 — Wire feedback edge into the workflow
- [ ] After `tune_output = HyperparamTuningAgent().run(tune_input)` (model_exploration.py:699), inspect `tune_output.status`
- [ ] If `"architecture_too_expensive"`: format the `TUNER_EXHAUSTED:` line per Q4 and append to `previous_failures`, then `continue` (skip the rest of this iteration's bookkeeping)
- [ ] Workflow unit test exercising the bubble-back path with a stub tuner that returns the new status
- [ ] Run: `tests/unit/workflows/`

### Step 7 — Tier 1 integration test for the tuner with a real refine path
- [ ] Synthetic infeasible-then-feasible scenario with a real LLM call
- [ ] `@real_run`, gated on API key
- [ ] Run: `tests/integration/nodes/test_ml_hyperparameter_tune_agent.py -m real_run`

### Step 8 — Connection audit (CLAUDE.md step 7)
- [ ] No orphan fields anywhere in the chain (proposer → implementor → validator → tuner)
- [ ] `previous_failures` round-trip: tuner exhaustion → workflow → proposer's next iteration sees the line
- [ ] Run the full unit suite for touched modules — all green
- [ ] Smoke test (3 iterations, 1-min budget, RNN-like architecture) demonstrates the feedback loop end-to-end

---

## Out of scope

- Changing the proposer's architecture-emission contract beyond dropping `baseline_config`.
- Extending the refine loop to also gate on VRAM (`evaluate_resource_skill`). The architecture-proposer's existing gate catches VRAM infeasibility before implement. Add only if a real failure mode emerges.
- Splitting `HyperparamTuningAgent` into "baseline" + "tune" sub-agents. The whole point of v2/v3 is that one agent owns config decisions; splitting it would re-create the v1 problem.
- Auto-suggesting concrete alternative architectures inside the `TUNER_EXHAUSTED:` line. The proposer's LLM already knows the model zoo; we just give it the signal that the previous one was too heavy.
