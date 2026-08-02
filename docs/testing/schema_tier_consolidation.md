# Schema-tier consolidation — evidence

**2026-08-02.** Branch `chore/schema-tier-consolidation`, from master
`662e4f6`.

## What changed and why

The schema suite was written **per-field-as-declared**: one test per
field, asserting what that field's own `Field(...)` already says. That
shape produces two failures at once — a large number of tests that
cannot fail for any realistic change, and no coverage of the rules the
system actually relies on, because those rules span models.

The retention rule applied to every test:

> If this test is removed, which real defect would no longer be caught
> by Pydantic, pyright, ruff, another existing test, or a Gate?

## Removed — 54 functions (`test_hyperparam_schemas.py` 128 → 68 cases)

All fell into patterns where the declaration *is* the enforcement:

| Pattern | Why removal loses nothing |
|---|---|
| optional field defaults to `None` | the default is the declaration |
| declared `Literal` rejects an unknown string | Pydantic enforces the Literal |
| declared type accepts its own type | pyright + Pydantic |
| required field is required | Pydantic |
| scalar JSON round-trip, no custom serializer | Pydantic |
| construct-then-read-back a plain field | tests the test |

Two class shells lost every method and were removed with them.

## Replaced by three contract tables

`TestProductionDefaults`, `TestDeclaredBoundsStillHold`,
`TestBackwardCompatibleLoading`.

**Every expected value is hardcoded, never read back from
`model_fields`.** Reading it back is the tautology that let the previous
`file_index` tests pass for *any* default — the test compared the schema
to itself. That trap is what makes a contract table worthless if built
carelessly.

The defaults table also picked up two defaults pinned by nothing at all:
`force_formal_round=True` (the cross-architecture comparability
contract) and `health_gate_enabled=True` (a default-on safety
subsystem).

## Added — cross-schema invariants

`tests/unit/agent/schemas/test_cross_schema_invariants.py`. Each test
names the **concept**, not the field, and asserts across every model
declaring it. Committed red first, so the gap is visible in history.

| Invariant | The divergence |
|---|---|
| `trial_portion` | three schemas required `ge=0.01`; intake allowed `ge=0.0`, i.e. **no training data** |
| attempt budgets | outputs documented as "Echo of the input" but unbounded, so a record could claim `attempts_per_round=0` |
| `file_index` | `PerFileRow` bounds at `NUM_FILES-1`; intake unbounded above, description claiming "(0-39)" for a 20-file dataset |
| seed alignment | a validator no test could distinguish from its own absence — every fixture passed both seeds as `42` |
| enforcement vocabulary | declared twice: a `Literal` in the policy, a bare `str` at intake |

The seed-alignment set includes a **negative control**; without it, a
validator that rejected *every* seed pair would still have passed.

## Production corrections

Four, each enforcing an existing contract earlier or consistently. None
changes scientific, retry, scheduler, timeout or resource policy.

1. `trial_portion` intake floor `0.0` → `0.01`.
2. Attempt-budget echoes gain `ge=1`.
3. `file_index` description corrected; the bound stays dataset-owned
   rather than restated as a literal, so no TIDMAD file count enters a
   schema being made task-generic.
4. `gpu_admission_enforcement` uses the shared `AdmissionEnforcement`
   Literal. Previously a typo passed intake and failed inside the
   tuner's attempt loop, after a planning call had been spent.

**One correction to the audit that produced this work:** it reported
that a typo'd enforcement value would silently mean "never enforce,
forever". Verified false — the inner `Literal` does reject it. The
defect was real; the severity was not. The failure was loud and *late*,
not silent.

## Evidence

| | before | after |
|---|---|---|
| collected cases | 6,562 | 6,528 |
| test functions | 5,699 | 5,668 |

The net is small because 54 removals were offset by 26 new invariant
tests plus the contract tables. **Count was never the goal** — the suite
now covers five rules it did not cover at all, and lost nothing that
could fail.

Mutation proofs, all confirmed:

| Mutation | Result |
|---|---|
| `attempts_per_round` 3 → 2 | fails 2 |
| `force_formal_round` True → False | fails 1 *(previously failed nothing)* |
| `health_gate_enabled` True → False | fails 1 *(previously failed nothing)* |
| drop `ge=1` from `max_fail_rounds` | fails 2 |
| revert `trial_portion` floor to `0.0` | fails 1 |
| drop `ge=1` from an echo | fails 1 |
| enforcement back to bare `str` | fails 2 |
| the two vocabularies disagree | fails 1 |

Clean-tree sweep: 6,373 passed, only the pre-existing unrelated
`FU-B-14`.

## Not done in this tier

`test_phase_b_schemas.py`, `test_score_table.py` and
`test_literature_review_schemas.py` — a further ~130 prunable functions
by the same rule. Agent-behaviour consolidation and gate-duplicate
pruning are untouched.

Five audited divergences remain **open**, because the authoritative
contract is genuinely ambiguous and should not be guessed:

- `eval_portion` — the same `ge=0.0` vs `ge=0.01` split as
  `trial_portion`, but no equivalent evidence that zero is meaningless.
- `formal_portion` (`ge=0.0`) vs `formal_eval_portion` (`gt=0.0`) —
  adjacent fractions with different zero-handling.
- `llm_provider` — a `Literal` on two models, a bare `str` on two
  others; tightening could reject a provider someone routes today.
- `model_type` — `min_length=1` on `CacheEntry` only; `""` reaches a
  plugin lookup elsewhere.
- `ConfidenceRubric.abstract_only_ceiling` — documented as the top of
  the highest non-deep-read band, but declared as an independent
  literal, so retuning the band silently detaches it.
