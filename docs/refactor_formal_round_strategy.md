# Refactor: Formal-Round Inheritance → Strategy-Based Dispatch

> **Status**: **CLOSED — all 4 phases landed 2026-05-02 on `fix/cognitive-alignment-v9`**.
> **Author**: Yue + Claude · **Date**: 2026-05-02
> **Phase commits**: Phase 1 `7bc2ea8` · Phase 2 `4b44a78` · Phase 3 `934ddb9` · Phase 4 `26da0fa`.
> **Reference for future sessions**: `docs/memories/project_formal_strategy_refactor.md`.

---

## 1. Observation & Motivation

### 1.1 Current state (post-Commit A, 2026-05-01)

`_apply_mode_override_chain` in `nodes/ml_hyperparameter_tune_agent.py:166`
accepts a `formal_round_strategy: str` parameter with the literal type
`Literal["inherit_best_trial", "llm_propose"]` (schema:808). The current
implementation has two arms:

| Strategy           | What gets inherited from the trial winner                                   |
|--------------------|------------------------------------------------------------------------------|
| `inherit_best_trial` (default) | `model_cfg`, `loss_cfg`, `train_cfg.lr`, `train_cfg.epochs`, `train_cfg.batch_size` (5 fields, the **full clone**) |
| `llm_propose`      | Nothing — planner's choices survive verbatim (only `is_trial=False` is forced) |

### 1.2 Problems with the current state

1. **The `inherit_best_trial` literal is a misnomer post-Commit A**. Commit
   A (2026-04-30) widened inheritance from `loss_cfg + lr` only to all five
   fields. The literal name still suggests the older semantics, and the
   schema docstring at `agent/schemas/hyperparam_tuning.py:812-817` still
   describes the pre-Commit A behavior. Audit logs reading the strategy
   name are misleading.
2. **No middle ground is reachable**. We have full clone or zero inheritance.
   The historical V7/V8 design (`loss_cfg + lr` only, planner chooses the
   rest) is no longer expressible — Commit A removed it.
3. **`if/elif` chain inside `_apply_mode_override_chain` will not scale**.
   At three strategies the in-line branches cross the threshold where a
   registry pattern earns its keep — each strategy becomes independently
   testable, and adding a fourth (e.g. `inherit_loss_only` for spectral
   ablation) is a one-line registry addition.

### 1.3 Goal

Replace the implicit two-mode strategy with an **explicit three-mode
registry**: `full_clone`, `hybrid_params`, `independent`. Aliasing keeps
old configs working. Logging at each round lets the post-mortem audit
read the active strategy at a glance.

---

## 2. Three Strategies — Semantic Contract

| Strategy        | Inherits from trial winner                                | Equivalent legacy name | Use case |
|-----------------|-----------------------------------------------------------|------------------------|----------|
| `full_clone`    | `model_cfg`, `loss_cfg`, `lr`, `epochs`, `batch_size`     | post-Commit A `inherit_best_trial` (alias) | Production. Maximum execution certainty. Trial measurement reuse for the time gate (Commit B–D) requires this. |
| `hybrid_params` | `loss_cfg`, `lr` only — planner keeps `model_cfg`, `epochs`, `batch_size` | pre-Commit A `inherit_best_trial` (no current implementation) | Audit/exploration. Lock evaluation (loss + lr) but let LLM scale capacity for the full-data pass. **Time gate may reject; that is the trade-off.** |
| `independent`   | Nothing — planner's full plan honored verbatim            | `llm_propose` (alias)  | Free exploration; sandbox runs. Hyperparameter measurements from trial are NOT reused. |

**Contract for all three**:
- `is_trial` is always flipped to `False` on the formal round.
- If no trial winner exists in `memory_history` (e.g. all trial rounds
  failed), every strategy falls back to "planner's plan unchanged" and
  emits the same WARNING. The strategy name only controls *what to copy
  when there IS a winner* — it does not change the no-winner behavior.
- Defensive `.get()` reads on `winner["params"]["train_config"]` keys —
  any missing key falls back to the planner's value rather than raising
  `KeyError`. Currently enforced for `epochs`/`batch_size`; we extend the
  same discipline to `loss_config` and `model_config` reads.

### 2.1 Backward-compat aliasing

| Legacy literal       | Alias resolves to | Where the alias lives |
|----------------------|-------------------|----------------------|
| `inherit_best_trial` | `full_clone`      | Pydantic validator on `formal_round_strategy` (canonicalises before validation) |
| `llm_propose`        | `independent`     | same |

Old `advice/workflow/*.json` and SDSC `_chain_common.sh` defaults continue
to validate without a code change. The canonicalisation happens once at
schema validation; downstream code (`_apply_mode_override_chain`,
registry lookup) only ever sees the canonical name.

---

## 3. Logging Contract

Two log lines per formal round, always emitted (no conditional silence):

```
[STRATEGY] formal_round_strategy=<canonical> (source=<default|cli|alias_of:<legacy>>)
[FORMAL OVERRIDE] strategy=<canonical> winner=<exp_id|none> inherited=<comma-list-of-fields>
```

- `source=default` — operator did not pass the flag.
- `source=cli` — operator explicitly set the canonical name.
- `source=alias_of:inherit_best_trial` — operator passed legacy name; we resolved the alias.

This makes the post-mortem trivially greppable: `grep "STRATEGY"
workflow_log.txt` shows every formal round's strategy + provenance.

---

## 4. File-Level Surface Map

| # | File | Change |
|---|------|--------|
| 1 | `agent/schemas/hyperparam_tuning.py:808` | `Literal[...]` → all 3 canonical values + Pydantic `@field_validator` for legacy aliases. Update docstring to match post-refactor semantics. |
| 2 | `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py:67,199` | Update `Literal[...]` to mirror the schema. Protocol passes the canonical value through (legacy resolution happens in the schema). |
| 3 | `nodes/ml_hyperparameter_tune_agent.py:166-265` | Replace `if/elif` with `_FORMAL_STRATEGY_REGISTRY` dict + 3 small handlers (`_strategy_full_clone`, `_strategy_hybrid_params`, `_strategy_independent`). Add the two-line `[STRATEGY]` log. |
| 4 | `nodes/ml_hyperparameter_tune_agent.py:1159-1165` | Call site stays mostly the same (already passes `agent_input.formal_round_strategy`). Strategy name is already canonical post-validation. |
| 5 | `workflows/model_exploration.py:583,1166` | Update default + Literal hint; legacy values resolved upstream. |
| 6 | `run_exploration_adaptive.py:230-239,372` | Update `--formal_round_strategy` `choices` to `[full_clone, hybrid_params, independent]`. Help text rewrite. Keep accepting legacy values via `argparse` `choices` extension OR delegate alias resolution to the schema (preferred — single source of truth). |
| 7 | `sdsc_submission_scripts/run_one_iteration.py:317-326,674` | Same as #6. |
| 8 | `sdsc_submission_scripts/_chain_common.sh:67,150,227` | Update default literal in shell + comment. Bash side does NOT alias-resolve; it passes whatever string the user gave. Schema canonicalises. |
| 9 | `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py` | New: `hybrid_params` tests (4 cases). Update existing `inherit_best_trial`/`llm_propose` tests to canonical names + add 2 alias-resolution tests. |
| 10 | `tests/unit/agent/protocols/test_ml_model_valid_to_ml_model_tune.py:454+` | Update fan-out tests to use canonical names + add 1 alias test. |
| 11 | `tests/unit/workflows/test_model_exploration.py:1248-1300` | Same as #10. |
| 12 | `tests/unit/scripts/test_chain_consistency.py` | Confirm Bash/Python literal lists are consistent (regenerate the assertion against the canonical+legacy union). |
| **NEW** | `docs/memories/project_formal_strategy_refactor.md` | Record the alias mapping as a project memory so future sessions don't trip on the legacy name. |

12 files touched, 1 new memory file. Source-only LoC delta is small;
test additions dominate.

---

## 5. Implementation — Strategy Registry Snippet

```python
# nodes/ml_hyperparameter_tune_agent.py

from typing import Callable, Optional, Sequence

# --------------------------------------------------------------------- #
# Formal-round inheritance strategies
# --------------------------------------------------------------------- #

_LEGACY_STRATEGY_ALIASES: dict[str, str] = {
    "inherit_best_trial": "full_clone",
    "llm_propose":        "independent",
}

def _canonical_strategy(name: str) -> str:
    """Resolve legacy literal to canonical name. Schema validator calls
    this before validation; runtime callers should already see canonical."""
    return _LEGACY_STRATEGY_ALIASES.get(name, name)


# Each handler mutates ``plan`` in place using the trial ``winner`` record
# and returns the list of inherited field names (for the log line).
# Signature is uniform so the registry can dispatch without special-casing.

def _strategy_full_clone(plan: ExperimentPlan, winner: dict) -> Sequence[str]:
    p = winner["params"]
    plan.model_cfg = dict(p.get("model_config") or {})
    plan.loss_cfg  = dict(p["loss_config"])
    plan.train_cfg["lr"] = p["train_config"]["lr"]
    inherited = ["model_cfg", "loss_cfg", "lr"]
    if (e := p["train_config"].get("epochs")) is not None:
        plan.train_cfg["epochs"] = e
        inherited.append("epochs")
    if (b := p["train_config"].get("batch_size")) is not None:
        plan.train_cfg["batch_size"] = b
        inherited.append("batch_size")
    return inherited

def _strategy_hybrid_params(plan: ExperimentPlan, winner: dict) -> Sequence[str]:
    # V7/V8 historical intent: lock loss + lr, let planner pick capacity.
    p = winner["params"]
    plan.loss_cfg = dict(p["loss_config"])
    plan.train_cfg["lr"] = p["train_config"]["lr"]
    return ["loss_cfg", "lr"]

def _strategy_independent(plan: ExperimentPlan, winner: dict) -> Sequence[str]:
    # No-op. Planner's full plan survives. Winner is unused but kept in
    # the signature for registry-uniformity.
    return []

_FORMAL_STRATEGY_REGISTRY: dict[str, Callable[[ExperimentPlan, dict], Sequence[str]]] = {
    "full_clone":    _strategy_full_clone,
    "hybrid_params": _strategy_hybrid_params,
    "independent":   _strategy_independent,
}


def _apply_mode_override_chain(
    plan: ExperimentPlan,
    *,
    trial_allowed: bool,
    is_formal_round: bool,
    force_formal_round: bool,
    formal_round_strategy: str = "full_clone",
    memory_history: Optional[list] = None,
) -> ExperimentPlan:
    if not trial_allowed:
        plan.is_trial = False
    if not (is_formal_round and force_formal_round):
        return plan

    plan.is_trial = False
    canonical = _canonical_strategy(formal_round_strategy)
    handler = _FORMAL_STRATEGY_REGISTRY.get(canonical)
    if handler is None:
        # Defensive — should be unreachable post-validation, but log loudly
        # if the schema layer is bypassed.
        print(f"  [STRATEGY] WARNING: unknown strategy {formal_round_strategy!r} — "
              "treating as 'independent' (no inheritance).")
        return plan

    print(f"  [STRATEGY] formal_round_strategy={canonical}"
          + (f" (alias_of:{formal_round_strategy})"
             if canonical != formal_round_strategy else ""))

    winner = _best_trial_winner(memory_history or [])
    if winner is None:
        print("  [FORMAL OVERRIDE] WARNING: no successful trial round in this "
              "iteration — planner's plan unchanged. Score may be unreliable.")
        return plan

    inherited = handler(plan, winner)
    print(f"  [FORMAL OVERRIDE] strategy={canonical} "
          f"winner={winner['exp_id']!r} score={winner['denoising_score']:.4f} "
          f"inherited={','.join(inherited) if inherited else '(none)'}")
    return plan
```

### 5.1 Pydantic alias resolution

```python
# agent/schemas/hyperparam_tuning.py

from pydantic import field_validator

class HyperparamTuningInput(BaseModel):
    formal_round_strategy: Literal["full_clone", "hybrid_params", "independent"] = Field(
        default="full_clone",
        description=(...),  # rewritten to describe all three canonical strategies
    )

    @field_validator("formal_round_strategy", mode="before")
    @classmethod
    def _canonicalise_legacy_strategy(cls, v):
        # Legacy → canonical resolution. Runs before Literal-validation.
        legacy = {"inherit_best_trial": "full_clone",
                  "llm_propose":        "independent"}
        return legacy.get(v, v) if isinstance(v, str) else v
```

### 5.2 CLI alias acceptance

```python
# run_exploration_adaptive.py + sdsc_submission_scripts/run_one_iteration.py

CANONICAL = ["full_clone", "hybrid_params", "independent"]
LEGACY    = ["inherit_best_trial", "llm_propose"]
parser.add_argument(
    "--formal_round_strategy",
    type=str,
    choices=CANONICAL + LEGACY,  # accept both; schema canonicalises
    default="full_clone",
    help="Formal-round inheritance strategy. Legacy names "
         "(inherit_best_trial → full_clone; llm_propose → independent) "
         "are aliased and emit a one-line resolution note in workflow_log.",
)
```

---

## 6. Phased Implementation Checklist

Each phase is independently committable; verification step at the end of
each. Stop and update this doc after each phase before moving to the
next.

### Phase 1 — Schema layer + alias resolution + node-side shim

**Important ordering note**: Phase 1 deliberately defers `hybrid_params` to
Phase 2. If Phase 1 added `hybrid_params` to the schema, users could select
it before the node-code registry (Phase 2) knows how to dispatch it, and
the existing `else`-branch would silently treat it as `independent` — a
hidden footgun. So Phase 1's schema accepts only the **2 new canonical
names that map 1:1 to existing legacy behavior** (`full_clone` ↔
`inherit_best_trial`, `independent` ↔ `llm_propose`). `hybrid_params`
lands in Phase 2 atomically with its handler.

The schema validator canonicalises legacy → canonical, so post-Phase-1
the node code sees `full_clone` instead of `inherit_best_trial`. The
existing `if formal_round_strategy == "inherit_best_trial":` would then
fall through to the `else` branch (no inheritance) — breaking production
behavior between Phase 1 and Phase 2. Phase 1 therefore includes a
**1-line transitional shim** in `_apply_mode_override_chain`: `if
_canonical_strategy(strategy) == "full_clone":`. Phase 2 deletes the
shim when the registry replaces the `if/elif`.

- [x] Add `_LEGACY_STRATEGY_ALIASES` constant + `_canonical_strategy` helper to `nodes/ml_hyperparameter_tune_agent.py` (just above `_apply_mode_override_chain`). Also added `Dict` to the typing import.
- [x] **Apply the transitional shim**: changed the `if formal_round_strategy == "inherit_best_trial":` branch in `_apply_mode_override_chain` to compute `canonical_strategy = _canonical_strategy(formal_round_strategy)` once, then `if canonical_strategy == "full_clone":`. Updated the `else`-branch print to surface both the canonical name and the input value (e.g. `strategy='independent' (input='llm_propose')`).
- [x] Updated `agent/schemas/hyperparam_tuning.py:808` Literal to `{full_clone, independent, inherit_best_trial, llm_propose}` (4 values, `hybrid_params` deferred to Phase 2) + added `@field_validator("formal_round_strategy", mode="before")` named `_canonicalise_legacy_strategy`. Default flipped to `full_clone`. Description block rewritten to describe both canonical strategies, the alias mapping, and a forward-reference to the Phase 2 reservation of `hybrid_params`.
- [x] Updated `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py:67` Literal to mirror the 4-value union + default to `full_clone`.
- [x] Added unit tests covering (a)-(f) as planned. Specifically: `test_strategy_default_is_full_clone`, `test_strategy_accepts_canonical_full_clone`, `test_strategy_accepts_canonical_independent`, `test_strategy_legacy_inherit_best_trial_aliases_to_full_clone`, `test_strategy_legacy_llm_propose_aliases_to_independent`, `test_strategy_hybrid_params_rejected_in_phase_1` (regression guard), and three shim tests (`test_shim_canonical_full_clone_inherits_like_legacy`, `test_shim_canonical_independent_skips_inheritance`, `test_shim_legacy_inherit_best_trial_still_works`). Also updated existing protocol-fan-out and workflow-forwarding tests to assert the canonicalised default.
- [x] **Verify**: targeted suite `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py + test_hyperparam_schemas.py + tests/unit/agent/protocols/test_ml_model_valid_to_ml_model_tune.py + tests/unit/workflows/test_model_exploration.py` → **272 passed in 3.23s**. Wider scope (`tests/unit/agent/tune_ml_hyperparam_agent/ + tests/unit/agent/protocols/ + tests/unit/workflows/ + tests/unit/scripts/`) → **754 passed, 3 failed in 225.10s**. All 3 failures are pre-existing on a clean tree (verified via `git stash`): 2 are the `SAFETY_MULTIPLIER==2.0` stale-constant assertions inherited from commit `5ac6a53` (V7 recalibration), 1 is a chain-resume kwargs drift in `test_chain_consistency::test_kwargs_match_modulo_documented_exemptions` between `run_exploration_adaptive.py` and `sdsc_submission_scripts/run_one_iteration.py` — unrelated to `formal_round_strategy`.
- [x] **Commit**: `refactor(schema): formal_round_strategy accepts canonical names + aliases legacy {inherit_best_trial, llm_propose}` → `7bc2ea8`.

### Phase 2 — Strategy registry + logic refactor + hybrid_params introduction

- [x] Add `hybrid_params` to the schema Literal (`agent/schemas/hyperparam_tuning.py:808` and `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py:67`). Both now accept 5 values: 3 canonical (`full_clone`, `hybrid_params`, `independent`) + 2 legacy aliases (`inherit_best_trial`, `llm_propose`). Description block in the schema rewritten to describe all 3 canonical strategies and the no-winner fallback. Removed the pre-Phase-2 "reserved — passing it raises ValidationError" reference and the matching exclusion comment in `_canonicalise_legacy_strategy`.
- [x] Add `_strategy_full_clone`, `_strategy_hybrid_params`, `_strategy_independent` handlers + `_FORMAL_STRATEGY_REGISTRY` dict to `nodes/ml_hyperparameter_tune_agent.py`. Uniform signature `(plan, winner) -> List[str]` returning the inherited field names for the audit log. `Callable` added to the typing import.
- [x] Replace the Phase-1 transitional shim (`if _canonical_strategy(...) == "full_clone":`) and the `else` branch with the registry dispatch. Inverted the outer guard (`if not (is_formal_round and force_formal_round): return plan`) to flatten one level of nesting. The unknown-strategy branch is defensive only — schema validation should reject unknowns before this point — but logs loudly and falls through to `independent` behavior to avoid silent mis-inheritance if a test fixture bypasses the schema.
- [x] Add the two-line `[STRATEGY]` + `[FORMAL OVERRIDE]` log contract from §3. ``[STRATEGY]`` shows `formal_round_strategy=<canonical>` with optional ` (alias_of:<legacy>)` when the input differed. ``[FORMAL OVERRIDE]`` shows `strategy=<canonical> winner=<exp_id|none> [score=<f>] inherited=<comma-list|(none)>`, OR the WARNING line on the no-winner path for `full_clone`/`hybrid_params`. **§2 contract reconciliation**: §2 said "every strategy emits the same WARNING" on no-winner; §7.2's `test_no_winner_no_warning` said `independent` should stay silent. The implementation follows §7.2's user-aligned reasoning (`independent` users explicitly disclaim inheritance — warning about a missing winner contradicts their intent), and instead emits a structured `[FORMAL OVERRIDE] strategy=independent winner=none inherited=(none)` line so the audit trail stays uniform. §2's "every strategy emits the same WARNING" line is now superseded by this implementation note — when the doc body next sees a real edit, it should be tightened in place.
- [x] Update existing tests in `test_force_formal_round.py` to use canonical names where they read the strategy literal. Updated 4 tests to the new audit-log format:
  - `test_strategy_hybrid_params_rejected_in_phase_1` → `test_strategy_hybrid_params_validates` (Phase 1 regression guard inverted to a Phase 2 acceptance test).
  - `test_inheritance_logs_winner_identity` — replaced legacy log assertions (`loss='focal'`, `lr=5e-5`, etc.) with the new `[STRATEGY] formal_round_strategy=full_clone` + `[FORMAL OVERRIDE] ... winner='r2' score=5.4523 inherited=model_cfg,loss_cfg,lr,epochs,batch_size` shape.
  - `test_strategy_llm_propose_keeps_planner_choices` — replaced "honored verbatim" string with the new `[STRATEGY] formal_round_strategy=independent (alias_of:llm_propose)` + `[FORMAL OVERRIDE] strategy=independent winner='r2' inherited=(none)` assertions.
  - `test_shim_canonical_independent_skips_inheritance` — same audit-log update without the `alias_of` annotation (caller passed canonical).
- [x] Add new tests: `hybrid_params` inherits exactly `loss_cfg + lr`, no-winner path, `independent` ignores winner, alias-resolution + `alias_of:` log line. Added a new "5c. Phase 2 — strategy registry tests" section to `test_force_formal_round.py` with 14 tests across 5 classes mirroring §7.2:
  - `TestFullCloneStrategy` (2 tests): `test_inherits_all_five_fields_from_winner`, `test_falls_back_to_planner_when_no_winner`.
  - `TestHybridParamsStrategy` (4 tests): `test_inherits_only_loss_cfg_and_lr`, `test_does_not_touch_model_cfg`, `test_falls_back_to_planner_when_no_winner`, `test_log_lists_inherited_fields`.
  - `TestIndependentStrategy` (2 tests): `test_planner_choices_survive_verbatim`, `test_no_winner_no_warning` (verifies the no-warning + uniform `[FORMAL OVERRIDE]` line decision from §2 reconciliation).
  - `TestAliasResolution` (3 tests): `test_inherit_best_trial_behaves_as_full_clone`, `test_llm_propose_behaves_as_independent`, `test_alias_log_line_emitted`.
  - `TestRegistryShape` (3 tests): `test_registry_has_three_canonical_strategies`, `test_all_strategies_uniform_signature` (smoke-calls each handler), `test_registry_directly_exposes_handler_callables`.
- [x] **Verify**: targeted file `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py -q` → **51 passed in 0.99s** (37 pre-existing + 14 new tests across the 5 §7.2 classes). Wider scope `tests/unit/agent/tune_ml_hyperparam_agent/ + tests/unit/agent/protocols/ + tests/unit/workflows/` → **735 passed, 2 failed in 226.13s**. The 2 failures (`test_estimator_static_patch::test_safety_multiplier_raised`, `test_warmup_activation::test_static_formula_uses_patched_constants`) are the same pre-existing `SAFETY_MULTIPLIER==2.0` stale-constant assertions documented in Phase 1 (now reading 1.3) — unrelated to this refactor and confirmed pre-existing on the clean tree.
- [x] **Commit**: `refactor(formal-round): strategy-registry dispatch + hybrid_params mode + audit logging` → `4b44a78`.

### Phase 3 — CLI + chain wrapper + workflow

- [x] Update `run_exploration_adaptive.py:230-247` `--formal_round_strategy` `choices` to the 5-value union (3 canonical + 2 legacy aliases), default flipped from `inherit_best_trial` to `full_clone`, help-text rewritten to describe all 3 canonical strategies and call out the alias resolution.
- [x] Update `sdsc_submission_scripts/run_one_iteration.py:316-336` identically (mirror change). Both CLIs now expose the same 5-value choice + same help text.
- [x] Update `sdsc_submission_scripts/_chain_common.sh:67` default literal flipped to `full_clone` + comment rewritten to list canonical names and note alias acceptance. Lines 150 (case arm) and 227 (APP_ARGS thread-through) need no change — they pass whatever string the user gave; schema canonicalises downstream.
- [x] Update `workflows/model_exploration.py:583` default flipped from `inherit_best_trial` to `full_clone`. Type stays `str` (not `Literal[...]`) for consistency with the sibling `formal_strategy: str = "snapshot"` parameter; the schema is the source of truth.
- [x] Update `tests/unit/scripts/test_chain_consistency.py` — added `formal_round_strategy` to `SHARED_FLAGS`, `THREE_WAY_FLAGS`, `_COMMON_ARGV` (`--formal_round_strategy full_clone`), and `EXPECTED_KWARG_NAMES`. Now both Python-Python parity (`TestDefaultParity`) and three-way Python↔shell parity (`TestThreeWayConsistency`) lock in the `full_clone` default across all three layers.
- [x] Update `tests/unit/workflows/test_model_exploration.py:TestOrchestrationParamForwarding` — added two new tests symmetric to the existing canonical/alias coverage:
  - `test_formal_round_strategy_canonical_hybrid_params_reaches_tuning_input` (Phase 2's new mode).
  - `test_formal_round_strategy_legacy_inherit_best_trial_canonicalised` (legacy alias → `full_clone`).
- [x] **Verify**: targeted suite `.venv/bin/python -m pytest tests/unit/workflows/test_model_exploration.py tests/unit/scripts/test_chain_consistency.py -q` → **79 passed in 3.54s**. Smoke checks: `--help` text on both CLIs shows the 5-value union and the rewritten help block; `bash -n sdsc_submission_scripts/_chain_common.sh` passes (shell syntax clean).
- [x] **Commit**: `refactor(cli): formal_round_strategy canonical names plumbed through CLI + chain wrapper + workflow` → `934ddb9`.

### Phase 4 — Documentation + memory + smoke

- [x] **Schema docstring audit**: re-read `agent/schemas/hyperparam_tuning.py:808-857`. The Phase 1+2 docstring already covers all 3 canonical strategies, the no-winner fallback, and the legacy alias mapping with the explicit "canonicalises legacy literals to their canonical form before downstream code sees the value" line. No re-edit needed.
- [x] **Project memory**: created `docs/memories/project_formal_strategy_refactor.md` capturing the canonical names, the alias mapping, the rename date (2026-05-02), the per-phase commit SHAs (`7bc2ea8`, `4b44a78`, `934ddb9`), and "how to apply going forward" guidance (use canonical in new configs; don't reintroduce `inherit_best_trial` as a primary; preserve the `[STRATEGY]` / `[FORMAL OVERRIDE]` log shape contract). Indexed in `docs/memories/README.md`. **Note**: `docs/memories/` is gitignored (per-developer local memory store) — the file lives on disk and is loaded via the auto-memory pointer in `~/.claude/projects/.../memory/MEMORY.md`, but is NOT pushed in this commit. The README index update is similarly local-only.
- [x] **`docs/V8_Gap_Report.md` updates**: surgical inline annotations at all 4 references (lines 17, 19, 133, 171) noting the 2026-05-02 rename and that semantics are unchanged. The audit verdict (Domain 4 = ALL CORRECT) is preserved verbatim — historical record stays intact.
- [x] **Smoke test**:
  - `--help` on both CLIs shows the 5-value union (verified in Phase 3 verify).
  - `bash -n sdsc_submission_scripts/_chain_common.sh` syntax check clean (verified in Phase 3 verify).
  - One short trial-mode dry run with each of the 3 strategies: the equivalent contract is already covered by `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py` — `TestFullCloneStrategy`, `TestHybridParamsStrategy`, `TestIndependentStrategy`, and `TestAliasResolution::test_alias_log_line_emitted` collectively assert the `[STRATEGY]` line content for all 3 canonical strategies + 2 aliases without burning LLM/GPU time. Live dry-run skipped as redundant.
- [x] **Verify**: `.venv/bin/python -m pytest tests/unit/agent/ -q` → **1730 passed, 6 failed in 229.94s**. The 6 failures are pre-existing on a clean tree (verified via `git stash` → same 6 fail in `test_estimator.py`, `test_proposer_preflight.py`, `test_estimator_static_patch.py`, `test_warmup_activation.py`). All 6 are estimator-constant drift unrelated to this refactor: 2 are the `SAFETY_MULTIPLIER==2.0` stale assertions documented from Phase 1+2, 2 are `_ligroup` ms_per_step / unknown-host fallback assertions hardcoded against an older calibration, and 2 are `proposer_preflight` feasibility verdicts that flip due to the same recalibrated coefficients. None touch `formal_round_strategy` or its dispatch surface.
- [x] **Commit**: `docs(formal-round): record canonical strategy names + alias mapping` → `26da0fa`.

---

## 7. Test Plan (Concrete Cases)

### 7.1 Schema-layer tests (Phase 1)

```python
# tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py

def test_strategy_full_clone_validates(): ...
def test_strategy_hybrid_params_validates(): ...
def test_strategy_independent_validates(): ...
def test_strategy_alias_inherit_best_trial_resolves_to_full_clone(): ...
def test_strategy_alias_llm_propose_resolves_to_independent(): ...
def test_strategy_unknown_literal_raises(): ...
def test_strategy_default_is_full_clone(): ...
```

### 7.2 Registry-dispatch tests (Phase 2)

```python
# tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py — new section

class TestFullCloneStrategy:
    def test_inherits_all_five_fields_from_winner(self): ...
    def test_falls_back_to_planner_when_no_winner(self, capsys):
        # Asserts WARNING log line, plan untouched.

class TestHybridParamsStrategy:
    def test_inherits_only_loss_cfg_and_lr(self):
        # planner's model_cfg / epochs / batch_size survive verbatim.
    def test_does_not_touch_model_cfg(self):
        # Pin: hybrid_params must NOT clone model_cfg even if winner has one.
    def test_falls_back_to_planner_when_no_winner(self, capsys): ...
    def test_log_lists_inherited_fields(self, capsys):
        # "inherited=loss_cfg,lr" in the log line.

class TestIndependentStrategy:
    def test_planner_choices_survive_verbatim(self): ...
    def test_no_winner_no_warning(self, capsys):
        # Pin: independent shouldn't warn about the missing winner — by
        # design it never wanted one.

class TestAliasResolution:
    def test_inherit_best_trial_behaves_as_full_clone(self): ...
    def test_llm_propose_behaves_as_independent(self): ...
    def test_alias_log_line_emitted(self, capsys):
        # "alias_of:inherit_best_trial" present in the [STRATEGY] log.

class TestRegistryShape:
    def test_all_strategies_uniform_signature(self):
        # Every handler in _FORMAL_STRATEGY_REGISTRY accepts (plan, winner)
        # and returns Sequence[str]. Catches future drift if someone adds
        # a 4th strategy with a different signature.
```

### 7.3 CLI / chain-wrapper consistency (Phase 3)

- Existing `tests/unit/scripts/test_chain_consistency.py` already enforces Bash↔Python literal-list parity. Update its expected list to `{full_clone, hybrid_params, independent, inherit_best_trial, llm_propose}` (canonical + legacy union).
- Add to `tests/unit/workflows/test_model_exploration.py`: legacy literal passed to the workflow → `tune_input.formal_round_strategy == "full_clone"` (canonical resolution happens inside the schema).

---

## 8. Risks & Edge Cases

1. **Live V9 chain with `inherit_best_trial` config in flight**. Alias resolution at the schema layer means the running chain keeps working — schema sees `inherit_best_trial`, hands `full_clone` to `_apply_mode_override_chain`, behavior identical to today. Verified by: `test_alias_resolution_unchanged_behavior`.
2. **Pydantic v1 vs v2 `field_validator`**. Repo uses Pydantic v2 (verified by `from pydantic import field_validator` already in use elsewhere). `mode="before"` is the v2 spelling.
3. **`hybrid_params` blowing the time gate**. Documented behavior. The time gate is the safety net; the user-supplied `formal_train_portion` and `formal_portion` already reduce data volume on formal rounds, but `hybrid_params` keeping the planner's `batch_size` could still bust the budget. The strategy is for explicit experimental use — not a default.
4. **Stale schema description after Phase 2**. Docstring is rewritten in Phase 1 to describe all 3 strategies. Phase 2 verifies behavior matches the description (no implicit re-description needed).
5. **Test files referencing `inherit_best_trial` in test names**. We rename the test functions to `test_strategy_full_clone_*` patterns in Phase 2 (test names should describe canonical behavior, not legacy aliases). The alias-resolution tests get their own dedicated names (`test_alias_inherit_best_trial_*`).
6. **Memory file `project_phase68_chain_resume_status.md` mentions `inherit_best_trial`**. Out of scope — those are historical chain-state notes; updating them retroactively would erase the timeline. We leave them as-is and rely on the new memory file (Phase 4) to record the rename.

---

## 9. Rollback Plan

Each phase is committed independently. If Phase 2 (the logic refactor)
introduces a regression that's not caught by the unit tests, `git revert
<phase-2-commit>` returns to the post-Phase-1 state — schema accepts new
literals, but logic still runs the old `if/elif`. The schema change in
Phase 1 is forward-compatible (legacy values still validate), so the
Phase-1 commit is safe to keep even if Phase 2 is reverted.

If we need to fully revert to pre-refactor: revert Phase 1 last
(reverting it first would break old configs that say
`inherit_best_trial`). Phases revert in reverse order: 4 → 3 → 2 → 1.

---

## 10. Out of Scope

- Changing the trial-winner selection logic (`_best_trial_winner`).
- Adding a 4th strategy (e.g. `inherit_loss_only`).
- Touching the time-gate (Commits B–D of `refine_inference_time_estimator.md`).
- Migrating any historical data files; the rename is forward-only with alias support.

---

## 11. Sign-off

- [x] User reviewed §2 (semantic contract) and §6 (phased checklist).
- [x] User confirmed branch target: continued on `fix/cognitive-alignment-v9`.
- [x] User confirmed commit cadence: 4 commits as in §6 (one per phase).
- [x] Phase 1 started after sign-off.

---

## 12. Closeout (2026-05-02)

All four phases landed on `fix/cognitive-alignment-v9`. The end-state
matches the §1.3 goal: an explicit three-mode registry (`full_clone`,
`hybrid_params`, `independent`) with legacy literals (`inherit_best_trial`,
`llm_propose`) accepted as schema-level aliases.

### 12.1 Per-phase commits

| Phase | SHA       | Headline                                                                |
|-------|-----------|-------------------------------------------------------------------------|
| 1     | `7bc2ea8` | `refactor(schema): formal_round_strategy accepts canonical names + aliases legacy {inherit_best_trial, llm_propose}` |
| 2     | `4b44a78` | `refactor(formal-round): strategy-registry dispatch + hybrid_params mode + audit logging` |
| 3     | `934ddb9` | `refactor(cli): formal_round_strategy canonical names plumbed through CLI + chain wrapper + workflow` |
| 4     | `26da0fa` | `docs(formal-round): record canonical strategy names + alias mapping`   |

### 12.2 What landed

- **Schema** (`agent/schemas/hyperparam_tuning.py`): `Literal[...]` widened
  to 5 values (3 canonical + 2 legacy); `@field_validator(mode="before")`
  named `_canonicalise_legacy_strategy` resolves legacy → canonical
  before Literal-validation runs. Default flipped from `inherit_best_trial`
  to `full_clone`. Description block rewritten.
- **Protocol** (`agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py`):
  matching 5-value Literal in the `local_validated_model` parameter list.
- **Node** (`nodes/ml_hyperparameter_tune_agent.py`): if/elif replaced by
  `_FORMAL_STRATEGY_REGISTRY` dict + 3 small handlers
  (`_strategy_full_clone`, `_strategy_hybrid_params`, `_strategy_independent`).
  Two-line `[STRATEGY]` + `[FORMAL OVERRIDE]` audit log emitted on every
  formal round per §3 contract. The §2 vs §7.2 reconciliation: `independent`
  emits a structured `winner=none inherited=(none)` line on the no-winner
  path (no WARNING) — see Phase 2 checkbox notes for the rationale.
- **CLIs** (`run_exploration_adaptive.py`, `sdsc_submission_scripts/run_one_iteration.py`):
  `choices` widened to the 5-value union; default flipped to `full_clone`;
  help text rewritten.
- **Chain wrapper** (`sdsc_submission_scripts/_chain_common.sh:67`):
  `FORMAL_ROUND_STRATEGY="full_clone"` default; case-arm + APP_ARGS unchanged
  (pass-through; schema canonicalises downstream).
- **Workflow** (`workflows/model_exploration.py:583`): default flipped to
  `full_clone`. Type stays `str` (sibling-flag consistency).
- **Tests**: `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py`
  gained 14 new tests across 5 §7.2 classes (51 pass total in the file);
  `tests/unit/scripts/test_chain_consistency.py` extended with
  `formal_round_strategy` in `SHARED_FLAGS` / `THREE_WAY_FLAGS` /
  `_COMMON_ARGV` / `EXPECTED_KWARG_NAMES`; `tests/unit/workflows/test_model_exploration.py`
  gained `hybrid_params` + `inherit_best_trial`-alias workflow-surface tests.
- **Docs**: V8 Gap Report inline-annotated at the 4 references to
  `inherit_best_trial`; project memory at
  `docs/memories/project_formal_strategy_refactor.md` (local-only —
  directory is gitignored, file is loaded via the auto-memory pointer).

### 12.3 Verification at close

- Phase 3 targeted: `tests/unit/workflows/test_model_exploration.py +
  tests/unit/scripts/test_chain_consistency.py` → **79 passed in 3.54s**.
- Phase 4 wide: `tests/unit/agent/` → **1730 passed, 6 failed in 229.94s**.
  All 6 failures are pre-existing estimator-constant drift on the clean
  tree (verified via `git stash`): 2 × `SAFETY_MULTIPLIER==2.0` stale
  assertions, 2 × `_ligroup`/unknown-host estimator-coefficient drift,
  2 × `proposer_preflight` feasibility verdicts hitting the same
  recalibrated coefficients. None touch `formal_round_strategy` or its
  dispatch surface.
- Smoke: `--help` on both CLIs shows the 5-value union + rewritten help
  block; `bash -n sdsc_submission_scripts/_chain_common.sh` clean.

### 12.4 What's NOT in scope of this refactor

- No live-chain migration. V9 chains running with `inherit_best_trial`
  in their config keep working — schema canonicalises at validation time.
  The audit log surfaces `(alias_of:inherit_best_trial)` so post-mortems
  can grep for chains still on legacy configs.
- The 6 pre-existing test failures listed in §12.3 are tracked separately
  (estimator recalibration follow-up); they were pre-existing before this
  refactor began and remain pre-existing after it closes.
