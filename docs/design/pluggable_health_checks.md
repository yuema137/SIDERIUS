# Pluggable Health Check System — HealthGates

**Status:** SHIPPED — the HealthGate migration landed in PR #101
(rev-6 implementation; this document's rev-4 text is the design it was
built from). Since then: PR #119 added the three recording-only checks +
observe-mode config; PR #124 added HealthGate-valid candidate selection;
the DataScope feature (`docs/design/enable_partial_file_list.md`) made
`health_gate_enabled` / `health_gate_files` run-level inputs with a
per-workspace materialized effective config pinned by the run-invariants
lock. `configs/health_checks.yaml` + `execute_tools/health_checks/` are
the shipped source of truth; supersedes revs 1–3 (see §13 change log).

---

## 1. Core Concept

A **HealthGate** is an independently configured checkpoint inserted at a
specific position in the training loop. Gates are not tied to every round
— they fire only at the round and phase they are configured for.

Each gate:

- Triggers after a specific round in a specific phase
- Runs one or more health checks
- Routes to a different action depending on pass or fail

This design separates three concerns:

1. **What to check** — the health check skills (`OutputDiversityCheck`, etc.)
2. **When to check** — the gate's position (`after_round`, `phase`)
3. **What to do** — the gate's `on_pass` / `on_fail` routing

Rounds without a gate proceed normally. Skills are stateless and have no
knowledge of gates or actions — the gate configuration in YAML controls
what action follows a check result.

---

## 2. Mental Model

```
Iteration
  └── round 1 → [Gate: collapse_check_round_1]      → on_fail: skip_iter
  └── round 2 → (no gate)
  └── round 3 → [Gate: quality_check_round_3]       → on_fail: skip_to_formal
              → [Gate: score_check_round_3]         → on_fail: invalidate_round
              → resolved action: most severe of the two
  └── round 4 → (no gate)
  └── round 5 → [Gate: formal_validation_round_5]   → on_fail: invalidate_round
```

**Key properties:**
- Rounds without a gate proceed normally — no overhead
- Multiple gates can fire at the same round (severity resolution applies
  — see §8)
- The tuner knows phase boundaries (which rounds are
  pretrial/finetrial/formal)
- HealthGates are agnostic to phase — they only know `round_index`

The pattern is straightforward: **each gate is a decision point where
the tuner asks "should we keep going, and if so, how?"** The check
skills observe the round output; the gate config decides the
consequences.

---

## 3. Configuration (`configs/health_checks.yaml`)

```yaml
# Each entry is an independent HealthGate.
# Gates are evaluated only at their configured round position (after_round).

health_gates:
  - id: "collapse_check_round_1"
    after_round: 1              # triggers after round 1 (regardless of phase)
    checks:
      - name: output_diversity
        config:
          min_unique_values: 5
      - name: amplitude_collapse
        config:
          collapse_threshold: 0.95
    on_pass:
      action: continue
    on_fail:
      action: skip_iter         # abort iter if round 1 collapses

  - id: "quality_check_round_3"
    after_round: 3
    checks:
      - name: output_diversity
        config:
          min_unique_values: 20  # stricter than round 1
    on_pass:
      action: continue
    on_fail:
      action: skip_to_formal    # skip remaining trial rounds, go to formal

  - id: "formal_validation_round_5"
    after_round: 5              # formal round
    checks:
      - name: output_diversity
        config:
          min_unique_values: 50  # strictest — formal must be reliable
    on_pass:
      action: continue          # tuner knows round 5 is terminal, records score
    on_fail:
      action: invalidate_round  # score = None, does not update best_score

# The mapping of round_index to phase (pretrial/finetrial/formal) is
# defined by the tuner, not by HealthGates. Gates only know round_index.
```

Each gate is independent. Adding a new gate is a YAML edit; removing one
is a comment. Threshold values (`min_unique_values`, `collapse_threshold`)
are gate-scoped — the same check can be run at multiple gates with
different strictness.

---

## 4. Gate Actions

```python
from enum import Enum


class GateAction(str, Enum):
    CONTINUE = "continue"
    # Proceed normally. On on_pass: next round runs (or iter closes if
    # this was the last round — the tuner knows phase boundaries).
    # On on_fail: same as INVALIDATE_ROUND for the current round,
    # then continue.

    SKIP_ITER = "skip_iter"
    # Abort current iteration. Move to next iteration.
    # No further rounds or phases run.

    SKIP_TO_FORMAL = "skip_to_formal"
    # Skip remaining trial rounds. Jump to formal phase.
    # Tuner decides what "formal" means — the gate only signals intent.

    INVALIDATE_ROUND = "invalidate_round"
    # Mark this round's score as None.
    # Does not affect gate decisions or best_score.
    # Continue to next round normally.
```

**Why no `RECORD_SCORE`.** The tuner already knows which round is the
terminal round (e.g. formal is always the last round in the iteration).
When the gate returns `CONTINUE` on the terminal round, the tuner
naturally records the score as it closes out the iteration. There is no
need for the gate to signal "this is terminal" — that is a tuner-level
concern, not a gate concern. Keeping `RECORD_SCORE` out of the enum
preserves the design principle that HealthGates are agnostic to phase
boundaries (§5) and prevents the YAML from having to know which round
is terminal.

---

## 5. Schemas

Location: `execute_tools/health_checks/schemas.py`.

```python
from collections.abc import Callable
from typing import Any

import numpy as np
from pydantic import BaseModel, Field


class HealthCheckContext(BaseModel):
    """Input to each health check skill.

    Checks read what they need. A check that operates on raw int8 output
    prefers ``raw_output`` (in-memory) and falls back to HDF5 via
    ``get_denoised_path``. A check that operates on aggregated per-file
    magnitudes reads ``file_vector``. A check has no obligation to
    consume any specific field — it is expected to introspect the
    context and skip gracefully when its inputs are absent.
    """
    model_config = {"arbitrary_types_allowed": True}

    # --- Identity ---
    model_name: str
    run_name: str
    iter_num: int
    round_index: int            # which round (1-based). Gate config uses this.
                                # Phase concepts (pretrial/finetrial/formal) are
                                # tuner-level concerns, not HealthGate concerns.

    # --- Output data — checks use what they need ---
    raw_output: np.ndarray | None = None
    """In-memory denoised array (int8). Preferred over HDF5 reads when the
    caller has already materialised the output. May be None on hot paths
    where materialisation is prohibitive (see doc note below)."""

    denoised_paths: dict[int, str] = Field(default_factory=dict)
    """file_index → HDF5 path. Used when raw_output is not available."""

    denoised_filename_fn: Callable[[int], str] | None = None
    """Lazy path constructor. Fallback when denoised_paths is not
    pre-built. Signature: (file_index: int) -> str."""

    # --- Scoring context (available at gates triggered after scoring) ---
    file_vector: list[float | None] = Field(default_factory=list)
    denoising_score: float | None = None

    def get_denoised_path(self, file_index: int) -> str | None:
        """Resolve the denoised HDF5 filename for one file_index.

        Order: explicit ``denoised_paths[i]``, then lazy
        ``denoised_filename_fn(i)``, then None.
        """
        if file_index in self.denoised_paths:
            return self.denoised_paths[file_index]
        if self.denoised_filename_fn is not None:
            return self.denoised_filename_fn(file_index)
        return None
```

**Design principle: `HealthCheckContext` has no concept of "phase"
(pretrial / finetrial / formal).** The gate system only knows
`round_index`. Phase boundaries are a tuner-level concern — the tuner
knows "rounds 1–2 are pretrial, round 3 is finetrial, round 5 is
formal", but HealthGates are agnostic to this. Different tasks and
different runs can define phase boundaries differently without changing
any HealthGate code. If a check needs phase-dependent behaviour, express
it via YAML: register the gate at the specific `after_round`, and the
gate's `on_pass` / `on_fail` actions carry the phase-specific
consequences.

```python
class HealthCheckResult(BaseModel):
    """Result from one health check skill."""
    check_name: str
    passed: bool
    reason: str = ""
    metrics: dict[str, float | int | str] = Field(default_factory=dict)


class GateResult(BaseModel):
    """Result from one HealthGate evaluation.

    The gate's ``action`` is the resolved routing outcome — either the
    gate's ``on_pass`` action (all checks passed) or its ``on_fail``
    action (some check failed with short-circuit).
    """
    gate_id: str
    round_index: int            # which round triggered this gate (for logging)
    passed: bool
    action: "GateAction"
    check_results: list[HealthCheckResult]
    failure_reason: str = ""    # empty when passed

    @property
    def should_skip_iter(self) -> bool:
        return self.action == GateAction.SKIP_ITER

    @property
    def should_skip_to_formal(self) -> bool:
        return self.action == GateAction.SKIP_TO_FORMAL

    @property
    def should_invalidate_round(self) -> bool:
        return self.action == GateAction.INVALIDATE_ROUND
```

**Note on `raw_output` and memory.** For TIDMAD, one file's denoised
output is ~2 GB (200 segments × 10M int8 samples), and there are 20 files
per iteration — ~40 GB total, unshippable to hold in memory at once. In
practice `raw_output` should only be populated when the caller has ONE
file (or ONE segment) already loaded and wants to share it — e.g. an
in-process training loop that just finished inference. For the scoring
hot path (all 20 files, streamed), checks must fall back to
`get_denoised_path` and read on demand. See the implementation note in §9.

---

## 6. Health Check Skill Protocol

Location: `execute_tools/health_checks/protocol.py`.

```python
from typing import Any, ClassVar, Protocol, runtime_checkable

from execute_tools.health_checks.schemas import (
    HealthCheckContext,
    HealthCheckResult,
)


@runtime_checkable
class HealthCheckSkill(Protocol):
    """Contract every health check implements.

    Skills are stateless and have no knowledge of gates, actions, or
    the tuner loop. A skill's only job is: given the context and its
    optional gate-scoped config, produce a HealthCheckResult.
    """
    name: ClassVar[str]

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict | None = None,
    ) -> HealthCheckResult:
        # config: per-gate threshold overrides from health_checks.yaml.
        # If None, the skill uses its own defaults.
        # This allows the same skill to run with different thresholds
        # at different round positions (e.g. min_unique_values=5 at
        # round 1, min_unique_values=50 at round 5).
        ...
```

Concrete checks are classes (not free functions) so they can carry
per-instance state if needed. Simple stateless checks are classes with
no `__init__` body. A skill implementation should treat `config=None` as
"use my defaults" and merge any provided keys over those defaults so
partial YAML overrides work naturally.

### 6a. Step 08a — checks declare their inputs (SUPERSEDES the NA convention)

**Amended by Step 08a** (`docs/design/generic_framework_upgrade/
step_08_health_check_task_profile.md` §7 and its child
`step_08_health_check_task_profile/pr_08a_check_input_contract.md`). The
code block above is the rev-6 shape; the Protocol now also carries:

```python
    declaration: ClassVar[CheckInputDeclaration]
```

Two things changed, and the second is the point.

1. **A check publishes what it consumes, as data** — a view capability
   key, which logical context inputs it needs (`denoised_source`,
   `target_source`, `file_vector`, `denoising_score`), which task-fact
   axes it requires, and which config keys are task thresholds.
2. **`evaluate_gate` decides applicability BEFORE calling `run`.** The
   rev-6 instruction — a skill finding its inputs missing returns
   `passed=True` with a `"not applicable"` reason — is **superseded**. It
   made inapplicability indistinguishable from health in every aggregate,
   count and record, and forced persistence to recover the truth by
   string-matching prose. A check that does not apply is now never
   invoked, opens no artifact, and is recorded as
   `CheckVerdict.INAPPLICABLE`, which **never counts as a pass**.

`HealthCheckResult` gains `verdict: CheckVerdict` —
`passed | failed | inapplicable | error`. `passed` keeps its exact
meaning (it is what selects `on_pass` / `on_fail` and drives
`short_circuit`), so gate ACTIONS are unchanged; the honest four-way
statement lives in `verdict` and reaches records as the additive
`PersistedHealthGateResult.check_verdicts`.

Checks written before 08a still work: `evaluate_gate` treats a
declaration-less check as unconditionally applicable, and a result
constructed without `verdict=` has one derived from the legacy fields.
The in-check "not applicable" returns that remain in the shipped checks
are **defensive only** — reachable by a direct caller, never through a
gate.

---

## 7. Registry

Location: `execute_tools/health_checks/registry.py`.

```python
_REGISTRY: dict[str, HealthCheckSkill] = {}


def register(check: HealthCheckSkill) -> None:
    """Register a check under its declared ``name``."""
    if check.name in _REGISTRY:
        raise ValueError(
            f"Health check {check.name!r} is already registered."
        )
    _REGISTRY[check.name] = check


def get(name: str) -> HealthCheckSkill:
    """Look up a registered check by name."""
    if name not in _REGISTRY:
        raise KeyError(
            f"Health check {name!r} not registered. "
            f"Available: {sorted(_REGISTRY)}."
        )
    return _REGISTRY[name]
```

Registration happens at import time as a side effect via
`execute_tools/health_checks/__init__.py`. Tests use `_REGISTRY.clear()`
via a pytest fixture for isolation.

---

## 8. Runner

Location: `execute_tools/health_checks/runner.py`.

> **Step 08a amendment.** The pseudo-code below predates the
> applicability step. `evaluate_gate` now runs, for each configured check
> in config-listed order:
>
> ```text
> declaration present?
>   no  -> invoke the skill (exactly pre-08a behaviour)
>   yes -> applicability(declaration, task facts, ctx)
>            applicable   -> invoke the skill
>            inapplicable -> record CheckVerdict.INAPPLICABLE and DO NOT
>                            invoke it — no artifact is opened
> ```
>
> The task's declared health facts are resolved lazily and once per gate,
> so a gate whose checks carry no declaration resolves nothing at all.
> An inapplicable result has `passed=True`, so it never triggers
> `on_fail` and never stops `short_circuit` — but it is not a pass, and
> counting, persistence and eligibility read the verdict rather than
> `passed`. See §6a and the Step-08 parent design §7.

```python
def get_gates_for_position(round_index: int) -> list[str]:
    """Return all gate_ids configured for this round_index.

    Multiple gates can fire at the same round. The tuner evaluates
    them in config order and resolves actions by severity (see
    "Action severity resolution" below).

    Returns an empty list when no gate is configured for this round —
    the tuner then proceeds normally with no gate overhead.

    Example tuner usage:

        gate_ids = get_gates_for_position(round_index)
        for gate_id in gate_ids:
            gate_result = evaluate_gate(gate_id, ctx)
            # handle gate_result.action (see severity resolution below)
    """
    config = _load_config()
    return [
        g["id"] for g in config.get("health_gates", [])
        if g["after_round"] == round_index
    ]


def evaluate_gate(
    gate_id: str,
    ctx: HealthCheckContext,
) -> GateResult:
    """Evaluate a named gate from configs/health_checks.yaml.

    Loads gate config by id, runs checks sequentially (short-circuit on
    first failure), resolves on_pass or on_fail action, returns a
    GateResult with the routing verdict. ``round_index`` on the returned
    GateResult is propagated from ``ctx.round_index`` for logging.

    The tuner gets ``gate_id`` from ``get_gates_for_position(round_index)``.
    """
    config = _load_config()
    gate_cfg = next(
        (g for g in config.get("health_gates", []) if g["id"] == gate_id),
        None,
    )
    if gate_cfg is None:
        raise ValueError(f"Gate {gate_id!r} not found in health_checks.yaml")

    on_pass_action = GateAction(gate_cfg["on_pass"]["action"])
    on_fail_action = GateAction(gate_cfg["on_fail"]["action"])

    results: list[HealthCheckResult] = []
    for check_cfg in gate_cfg["checks"]:
        skill = get(check_cfg["name"])
        # Gate-scoped config overrides skill defaults. Pass None (not
        # empty dict) when the YAML entry omits ``config`` so the skill
        # uses its own defaults per §6.
        result = skill.run(ctx, config=check_cfg.get("config"))
        results.append(result)
        if not result.passed:
            return GateResult(
                gate_id=gate_id,
                round_index=ctx.round_index,
                passed=False,
                action=on_fail_action,
                check_results=results,
                failure_reason=result.reason,
            )

    return GateResult(
        gate_id=gate_id,
        round_index=ctx.round_index,
        passed=True,
        action=on_pass_action,
        check_results=results,
    )
```

**Implementation notes** (post-commit-3b, shipped `3f07ecd`):

The pseudo-code above uses raw-dict access against the YAML for clarity.
The shipped runner reads a Pydantic-validated `HealthChecksConfig` from
`load_health_gates_config()` (see the config models added in commit-2).
Three deviations from the pseudo-code, all surfaced during commit-3b
implementation:

- **Per-gate `short_circuit`** (D8-A → A): the pseudo-code hard-codes
  short-circuit. The runner honors `gate_cfg.short_circuit` (default
  `True` per commit-2 D4). With `short_circuit=False`, all checks run
  and `failure_reason` records the *first* failing check's reason
  (config-listed order — pinned by
  `test_first_failure_reason_is_config_order`).
- **Empty `CheckRef.config` → `None`** (D8-B → A): `check_ref.config or
  None` — an empty dict from Pydantic's `default_factory=dict` reaches
  the skill as `None`, matching the pseudo-code's `.get("config")`
  None-for-missing semantic and Protocol §6's "None means use defaults"
  wording.
- **`resolve_action([])` → `CONTINUE`**: empty iterable case not spelled
  out in the pseudo-code. The runner returns `CONTINUE` (the identity
  element for max-severity: no gates means proceed normally).

### Action severity resolution

When multiple gates fire at the same round, their actions are resolved
by severity — **most restrictive wins**:

```
SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE
```

The tuner should evaluate all gates for a given round and take the most
severe action:

```python
# Tuner pseudo-code for handling multiple gates at round_index
gate_ids = get_gates_for_position(round_index)
resolved_action = GateAction.CONTINUE
gate_results = []

for gate_id in gate_ids:
    result = evaluate_gate(gate_id, ctx)
    gate_results.append(result)
    if severity(result.action) > severity(resolved_action):
        resolved_action = result.action

# Apply resolved_action
if resolved_action == GateAction.SKIP_ITER:
    break                       # exit iteration loop
elif resolved_action == GateAction.SKIP_TO_FORMAL:
    goto_formal_phase()
elif resolved_action == GateAction.INVALIDATE_ROUND:
    round_score = None
# CONTINUE: proceed normally
```

Severity order is intentional:

- `SKIP_ITER` is the most disruptive (aborts the whole iteration) so it
  takes precedence over everything.
- `CONTINUE` is the least disruptive (do nothing extra) so it never
  overrides a more restrictive action from a sibling gate.
- `SKIP_TO_FORMAL` and `INVALIDATE_ROUND` sit in the middle — a
  finetrial-quality gate that wants to jump to formal should not be
  overridden by a per-round invalidator, but should defer to an
  iter-level abort.

**Discovery pattern.** The tuner does not enumerate all gates
statically — it asks `get_gates_for_position` at each round boundary
and evaluates only the gates that answered. This keeps the tuner in
charge of *when* to check (after each round) and the YAML in charge of
*what* to check (gates listed with `after_round`). A gate whose `id`
reaches `evaluate_gate` but is missing from YAML raises `ValueError` —
fail-loud during dev; a future decorator `@declared_gate` could
pre-validate the set at import time.

---

## 9. Implemented Health Check Skills

Location: `execute_tools/health_checks/checks/`.

### 9.1 `OutputDiversityCheck`

- **Detects:** class-127 collapse and near-constant outputs
  (≤threshold unique int8 values)
- **Input:** HDF5 peek via `ctx.get_denoised_path(file_index)` — reads
  a bounded slice of `channel0001` and counts unique int8 values. No
  in-memory raw-array path (commit-1 D2 dropped `raw_output` — the
  ~40 GB streaming path is not viable).
- **Config:** `min_unique_int8_values: int = 5`,
  `peek_samples: int = 100_000`
- **Metrics on flag:** `unique_count: int`, `peek_samples: int`,
  `file_index: int`, `threshold: int`
- **Metrics on peek error:** `peek_error: str`, `attempted_path: str`,
  `file_index: int`, `threshold: int`, `peek_samples_requested: int`

**Failure-mode taxonomy** (commit-4a implementation):

- `get_denoised_path` returns `None` → `passed=True` with "not
  applicable" reason. The only legitimate silent-pass case.
- `OSError` / `KeyError` on peek → `passed=False` with the attempted
  path baked into the reason. Not silent-pass — caller misconfiguration
  surfaces immediately.
- Peek succeeds and `unique_count <= min_unique_int8_values` →
  `passed=False`.
- Otherwise → `passed=True`.

**Threshold rationale (`min_unique_int8_values`)**

| Unique int8 values | Meaning |
|---|---|
| 1 | Class-127 collapse (or any other constant-output collapse) |
| 2–3 | Near-constant collapse (edge artifacts) |
| 5–20 | Poorly-trained but non-collapsed model |
| 50–200 | Well-trained model on 8-bit ADC data |

The default of 5 gives a safety margin: any model with ≤5 unique values
has clearly failed to learn input-dependent predictions. A gate can
override with a stricter value (e.g. `min_unique_int8_values: 50` at
the formal gate).

### 9.2 `AmplitudeCollapseCheck`

- **Detects:** single-bin dominance in the int8 output (dominant
  class's fraction of the peek exceeds threshold)
- **Input:** HDF5 peek via `ctx.get_denoised_path(file_index)` — same
  bounded read as `OutputDiversityCheck`, then histogram via
  `np.unique(samples, return_counts=True)`. No in-memory raw-array
  path (see §9.1 for rationale).
- **Config:** `collapse_threshold: float = 0.95`,
  `peek_samples: int = 100_000`
- **Metrics on flag:** `dominant_class: int`, `dominant_fraction:
  float`, `peek_samples: int`, `file_index: int`, `threshold: float`
- **Predicate:** `dominant_fraction > collapse_threshold` (strict `>`
  per commit-4b — exactly at threshold does NOT trip)

**Failure-mode taxonomy** — identical to `OutputDiversityCheck` (§9.1).
Additionally, an empty peek (0 samples — caller passed
`peek_samples=0` or the dataset is truncated) returns `passed=False`
with an "empty peek" reason, following the same "don't silent-pass
caller misconfig" principle (AMB-4b-EMPTY → A).

**Not to be confused with the v7 magnitude-ratio check.** The v7
(2026-04-26) collapse pattern was detected via a ratio of
`mean(|file_vector|)` vs. a reference, which required a
`reference_file_vector` in the context. That predicate was **removed
entirely** in commit-4b: the shim `execute_tools/squid_health_checks.py`
was deleted (zero non-test callers), and the rev-6 `HealthCheckContext`
no longer carries `reference_file_vector` (commit-1 D2). This class
operates on the int8 distribution directly — no reference needed.

### 9.3 `SampleDispersionFloorCheck` (FIXTURE-SCOPED — not in production)

Added by Step 08a C6 as roadmap §8.4-C's **negative control**, and
deliberately referenced by **no production YAML**. It is registered like
any other built-in — being registered is not being configured, and a test
asserts it appears in neither shipped config.

Its declaration requires `encoding_family == "continuous_float"`, so it is
`inapplicable` under TIDMAD while the six TIDMAD checks are `inapplicable`
under a declared-float task. That symmetry is the whole point: it proves
that inapplicability is a statement about ONE family and never an
exemption from health evaluation — on the same declared-float output where
the int8 family reports `inapplicable`, this check FIRES, can FAIL, and can
block a round.

Mechanism: population standard deviation of the supplied samples against a
floor; an empty sample set is `error`, not a pass. Samples arrive through
its own config because 08a has no view-provider mechanism yet (08b), and
its view key `step08.fixture_continuous_samples` is spelled in the
plugin-local style to demonstrate §6.3's claim that the engine never
interprets a view key. The real generic continuous family is 08c.

---

## 10. Adding a New Health Check

1. Create `execute_tools/health_checks/checks/my_check.py`
2. Implement the `HealthCheckSkill` protocol: a `name: ClassVar[str]`
   attribute, a `declaration: ClassVar[CheckInputDeclaration]` stating
   what the check consumes (Step 08a, §6a), and a `run(ctx, config)`
   method returning `HealthCheckResult`. State the `verdict=` explicitly
   rather than relying on the legacy derivation.
3. Call `register(MyCheck())` at module scope.
4. Import the module in `execute_tools/health_checks/checks/__init__.py`
   so registration fires at package import.
5. Add a gate entry (or extend an existing one) in
   `configs/health_checks.yaml` that references your check name and
   supplies its config.

No pipeline code changes required.

### Future check candidates

- `FrequencyDiversityCheck` — verify PSD energy spans multiple bands
  (catches spectral collapse that a bin-based check misses).
- `SignalCorrelationCheck` — correlate raw input with denoised output.
  Too low → predicting noise; too high → identity passthrough.
- `PerFileVarianceCheck` — variance of `file_vector` across the 20
  files (low variance = artifact or memorisation).
- `TrainingLossConsistencyCheck` — flag suspiciously low `final_loss`
  (< 0.05 for CE) as a degenerate-loss-landscape signal.

Each new check is an independent PR touching one file under
`execute_tools/health_checks/checks/` and one YAML entry.

---

## 11. The Class-127 Collapse Attractor

This is the motivating incident for `OutputDiversityCheck`.

### What happened

All v15/v16 formal scores that appeared to "match the WaveNet baseline"
(`5.5762667`) were artifacts of mode collapse, not genuine denoising.
Under-training (`train_portion=0.1, max_epochs=1`) gave models only
~0.4% of training data — insufficient to escape the degenerate optimum
of predicting class 127 (int8=-1, the median ADC bin) for every input.

### The 2^17 artifact mechanism

When the denoised output is constant int8=-1 (−0.3125 V), FFT produces
subnormal PSD values (~1e-40) at all non-DC frequencies. The ±50-bin
noise window and ±1-bin signal window both consist of subnormals of
similar magnitude:

```
signal = PSD[center-1 : center+2].sum()               ≈ 1.522e-40
noise  = PSD[center-50 : center+51].sum() - signal    ≈ 1.161e-45
SNR    = 1.522e-40 / 1.161e-45 = 131,072 = 2^17 (exact)
```

This propagates through scoring to produce exactly `5.5762667` for every
collapsed model, regardless of architecture, loss function, or training
duration. It is a deterministic function of float64 arithmetic on
constant input — not a measure of denoising ability.

### Fixes

1. **`OutputDiversityCheck` at the pretrial gate** — catches the
   collapse before scoring runs. The round's score is invalidated
   (`INVALIDATE_ROUND`) or, at the pretrial gate, the entire iteration
   is skipped (`SKIP_ITER`).
2. **SNR noise floor guard** — `get_snr` returns `NaN` when
   `noise < 1e-10` (subnormal territory). Downstream `_collect_raw_pairs`
   and `score_vector` filter NaN pairs. Prevents the 2^17 ratio from
   ever forming, even if the diversity check is disabled.
3. **Schema default corrected** — `current_run_best_formal_score`
   changed from `5.5763` (the collapse artifact) to `1.0007` (the raw
   pass-through baseline) in `feat/v16-fixes`. V17 subsequently replaced
   that default with the fixed per-iteration formal reference `0.0`; the
   dynamic committed best-valid-formal incumbent is deferred to V18. The
   value `5.5763` must never be used as a performance baseline; it is a
   hardware-level FP fingerprint, achievable by any model outputting
   constant int8=-1 with zero training.

### Why this required pluggability

The class-127 attractor is TIDMAD-specific (median ADC bin for SQUID
magnetometer data). Other tasks will have different attractors:

- Audio denoising: silence (class 0)
- Image denoising: gray (class 128 in 8-bit)
- Speech enhancement: most common phoneme embedding

Hardcoding TIDMAD-specific detectors into the pipeline would make the
system non-portable. The HealthGate architecture lets each task
register its own degenerate-output detectors in
`configs/health_checks.yaml` without touching pipeline code.

Numerical verification and forensic audit: `reports/v16_20260630.md` §9.

---

## 12. Back-compatibility

**The back-compat shim was removed in commit-4b (SHA `1250137`).** It
lived at `execute_tools/squid_health_checks.py` and delegated to the
legacy magnitude-ratio check for pre-refactor callers. By the time
commit-4b landed the shim was triply broken:

- The shim's `HealthCheckContext` construction had been broken since
  commit-1 (missing the three required identity fields
  `model_name` / `run_name` / `round_index`).
- Its `run_health_checks` import target was gone since commit-3a
  (Option L retirement).
- The predicate it delegated to had been fully replaced with the
  distribution-based one (commit-4b, §9.2) — no way to reconstruct the
  old magnitude-ratio semantic even in principle.

Zero non-test callers were found at removal time. Two test files that
exercised the shim
(`tests/unit/execute_tools/health_checks/test_legacy_shim.py` and
`tests/unit/execute_tools/test_squid_health_checks.py`) were also
deleted.

**Adding a new check.** Add `HealthCheckSkill` implementations directly
under `execute_tools/health_checks/` and register them per §10. Do not
reintroduce a back-compat shim: the rev-6 context, protocol, and
predicates all changed together in a way that cannot be shimmed
compatibly against the pre-rev-6 API.

---

## 13. Change log

- **rev 6 (2026-07-08)** — Five follow-on corrections to the rev-5
  design. The rev-5 helper signature and the `RECORD_SCORE` action
  turned out to be wrong on further review:
  1. `get_gate_for_position(round_index) → str | None` renamed to
     `get_gates_for_position(round_index) → list[str]`. Multiple gates
     can legitimately share a round (`quality_check_round_3` +
     `score_check_round_3`); the earlier "first match wins" rule was a
     silent failure mode (§8).
  2. `RECORD_SCORE` removed from `GateAction`. The tuner already knows
     which round is terminal (last round of the iteration) and records
     the score naturally on `CONTINUE`. Keeping the gate agnostic to
     phase boundaries is the whole design principle (§4, §5).
  3. `GateResult.round_index` added — propagated from
     `ctx.round_index` at construction time in `evaluate_gate`.
     Logging + Run Monitor need to know which round produced which
     verdict; adding the field is cheaper than looking it up (§5).
  4. Action severity resolution formalised
     (`SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE`) so
     multiple gates at the same round have deterministic combined
     behaviour (§8).
  5. §2 Mental Model diagram redrawn to show two gates sharing
     round 3 + the severity-resolution property, and to drop the
     phase-tree structure (the rev-5 diagram implicitly reintroduced
     phases via the `Pretrial / Finetrial / Formal` branches).
- **rev 5 (2026-07-08)** — Five targeted corrections to the rev-4
  HealthGate design. Superseded by rev 6 on points 1 (helper signature)
  and 5 (`RECORD_SCORE`). See rev-6 above for rationale.
  1. `HealthCheckContext.phase` removed → `round_index` only. Phase
     boundaries (pretrial / finetrial / formal) are tuner-level; gates
     are agnostic (§5 design principle).
  2. `configs/health_checks.yaml` `phase:` field removed. Gates fire on
     `after_round` alone (§3).
  3. `HealthCheckSkill.run(ctx, config=None)` — `config` is now
     optional; `None` means "skill defaults" so partial YAML overrides
     work naturally (§6).
  4. ~~`get_gate_for_position(round_index) → gate_id | None`~~
     superseded by rev-6 point 1 (plural helper).
  5. ~~`RECORD_SCORE` vs `CONTINUE` clarified~~ superseded by rev-6
     point 2 (`RECORD_SCORE` removed entirely).
- **rev 4 (2026-07-08)** — Design pivot to HealthGate model. Previous
  revs (1–3) had the wrong mental model: checks running automatically
  after every round via `run_health_checks(ctx)`. That design conflated
  "when to check" with "what to check" and had no natural home for
  routing decisions (skip iteration, skip to formal, invalidate score).
  This rev separates concerns cleanly: gates own position + routing;
  skills own the checks themselves. See §1 and §4 for the new action
  model.
- **rev 3 (2026-07-08)** — Class-127 attractor section, threshold
  rationale bullets, schema default fix, future checks list. See git
  history for content.
- **rev 2 (2026-07-08)** — Operator approval + `denoised_filename_fn`
  clarifications + collapse-into-one-commit note.
- **rev 1 (2026-07-08)** — Initial design proposal.

---

## 14. Implementation state (as of this rev)

**Status: Implemented.** The pluggable HealthGate framework migration
is complete as of commit-6 (SHA backfilled after commit). §14 is
retained as a historical decision-context record — the "Found during
implementation" notes on each bullet capture design decisions that
shaped the shipped framework and should not be lost. The final bullet
below ("Update this doc to remove §14…") is marked done via this status
marker rather than by deletion, per the §14-KEEP decision in commit-6.

**Historical snapshot (pre-migration, feat/v16-fixes at commit-1):**
the shipped implementation followed the rev-3 model —
`run_health_checks(ctx)` was called from inside
`execute_tools/scoring_utils.py::score_vector` at two phases (pre-FFT
and post-PSD). This worked for the class-127 case but did not support
the HealthGate routing model above.

**Migration to HealthGate design (completed in commits 1-6):**

- [x] Introduce `HealthCheckResult` (field: `passed` instead of
      `is_degenerate`, `reason` instead of `failure_reason`). **Found
      during implementation:** this is NOT a rename — Option A migration
      keeps legacy `HealthCheckOutput` alive alongside the new class
      until commit-6 because score_vector's Phase 0/3 blocks and the two
      shipped check files still return `HealthCheckOutput`. The polarity
      inversion (True=bad → True=good) is a footgun during migration;
      `test_semantics_inverted_from_legacy` pins the mapping so a future
      refactor cannot silently swap it back. Landed commit `29edb68`
      (commit-1). 4 unit tests in `test_schemas.py`.
- [x] Introduce `GateResult` with `action`, three `should_*` properties
      (`should_skip_iter`, `should_skip_to_formal`, `should_invalidate_round`),
      and `check_results`. Alongside legacy `HealthCheckPanelOutput`
      until commit-6. **Found during implementation:** deliberately no
      `should_continue` property — CONTINUE is the identity/default;
      exposing a "should_continue" flag would tempt callers into
      `if not should_continue: skip` logic that's harder to reason
      about than checking specific actions.
      `test_continue_action_has_no_should_flag` pins this. Landed commit
      `29edb68` (commit-1). 8 unit tests in `test_schemas.py`.
- [x] Introduce `GateAction` enum (§4) — landed commit `29edb68`
      (commit-1). Four StrEnum members: `CONTINUE`, `SKIP_ITER`,
      `SKIP_TO_FORMAL`, `INVALIDATE_ROUND` (no `RECORD_SCORE` per
      rev-6 point 2). 4 unit tests in `test_schemas.py`.
- [x] Extend `HealthCheckContext` with `iter_num` (optional per D3),
      `round_index`, `denoising_score`; drop `reference_file_vector`,
      `data_dir`, `model_type`, `exp_id`. Also drop `raw_output` per
      D2 (~40 GB streaming path not viable). **No `phase` field** —
      phase mapping is tuner-level, see §5 design principle. Landed
      commit `29edb68` (commit-1). 10 unit tests in `test_schemas.py`.
- [x] Rename `base.py` → `protocol.py`, `_registry.py` → `registry.py`.
      New Protocol drops `is_applicable` per §6 — skills always run and
      return `passed=True` with a "not applicable" reason when inputs
      are missing. **Found during implementation (Option L):** keeping
      the rev-3 `run_health_checks` alive alongside the new Protocol
      produced 4 unavoidable pyright errors (`skill.is_applicable` no
      longer on Protocol, `HealthCheckResult` vs `HealthCheckOutput`
      return type mismatch). No path to make both work simultaneously,
      so `run_health_checks` + `test_runner.py` were retired in 3a
      (not commit-6 as originally planned). Its sole production caller
      (`scoring_utils.py::score_vector` Phase 0/3 blocks) was already
      broken at construct-time by commit-1's schema change, so the
      retirement changed the failure mode from runtime `AttributeError`
      to import-time `ImportError` — not a regression on a working code
      path. One residual pyright error remains at `__init__.py:50`
      `register(check)` — the two legacy check classes still don't
      conform to the new Protocol structurally. Clears in commit-4 when
      the checks are rewritten. Landed commit `fc590d0` (commit-3a).
      No new tests; 65 pre-existing tests remained green.
- [x] Rewrite `OutputDiversityCheck` + `AmplitudeCollapseCheck`
      against the rev-6 Protocol (no `is_applicable`,
      `run(ctx, config=None) -> HealthCheckResult`) and the current
      `HealthCheckContext` fields (`get_denoised_path` — no
      `data_dir`, no `reference_file_vector`, no `raw_output`). Landed
      in two commits:
      * **commit-4a** (`32552ff`): shared `_peek` helper
        (`choose_peek_file_index` + `peek_int8_at_path`, split so the
        peek primitive is pure I/O and each check owns its
        "not applicable" vs. "peek failed" policy) +
        `OutputDiversityCheck` rewrite. Path contract locked
        (AMB-4-3 → A): paths from `get_denoised_path` used verbatim,
        callers do their own base-dir composition. 20 unit tests
        (9 peek + 11 output_diversity).
      * **commit-4b** (`1250137`): `AmplitudeCollapseCheck` full
        rewrite — magnitude-ratio predicate replaced with
        distribution-based (`np.unique` histogram +
        `dominant_fraction > collapse_threshold` strict `>`). Reuses
        `_peek`. Empty-peek treated as `passed=False`
        (AMB-4b-EMPTY → A). 13 unit tests.

      **Failure-mode taxonomy** (both checks): `get_denoised_path ==
      None` → `passed=True` with "not applicable" reason (the only
      silent-pass case); `OSError` / `KeyError` on peek → `passed=False`
      with attempted path in reason (caller misconfig, don't
      silent-pass); predicate fires → `passed=False` with structured
      metrics.

      **Found during implementation:** initial dominance-fraction
      tests used `np.arange(-20, 20)` for the "variety" tile — includes
      0, inflating the dominant-class count. Fixed to `np.arange(1, 41)`
      so the arithmetic is exact. Diagnosed as test bug, not production
      bug, before any fix (rule 7).
- [ ] Move checks to `execute_tools/health_checks/checks/` subdir
      (design §10 line). Not required for the migration; deferred to
      a later cleanup pass.
- [x] Change YAML schema from `checks:` list to `health_gates:` list with
      `after_round` / `on_pass` / `on_fail` fields (no `phase` field).
      Landed commit `6cdd529` (commit-2). New shape: `health_gates:
      list[GateConfig]` with per-gate `id`, `after_round`,
      `short_circuit=True` (default per D4), `checks: min_length=1`
      (per D2), `on_pass: ActionConfig`, `on_fail: ActionConfig` (both
      required per D1), optional `reason`. Root `HealthChecksConfig`
      rejects duplicate `id` values (per D3) with the list of dupes in
      the message. Legacy `HealthCheckConfig` + `CheckConfig` kept
      alongside until commit-6. 27 unit tests in `test_config_loader.py`.
- [x] Implement `get_gates_for_position(round_index) → list[str]` per
      §8 so the tuner can look up all gates that fire at a round
      boundary. Also lands `evaluate_gate(gate_id, ctx) → GateResult`,
      the public `severity_of(action) → int` helper (decision A.1), and
      `resolve_action(gate_results: Iterable[GateResult]) → GateAction`
      that picks the most-severe action (decision B.1). **Found during
      implementation — three doc/spec gaps surfaced:**
        (1) The §8 pseudo-code uses raw-dict access against the YAML;
            the shipped runner reads a Pydantic-validated
            `HealthChecksConfig` (commit-2's models). Semantics
            identical, but a note in §8 flags this.
        (2) **D8-A**: the pseudo-code hard-codes short-circuit but
            commit-2's D4 made `short_circuit` per-gate with default
            `True`. Runner honors `gate_cfg.short_circuit` — decision A.
        (3) **D8-B**: the pseudo-code uses `check_cfg.get("config")`
            (None if missing) but Pydantic's `default_factory=dict`
            always returns `{}`. Runner converts empty dict to `None`
            with `check_ref.config or None` so the skill sees "no
            override" per §6 semantic — decision A.
      Also: `resolve_action` on an empty iterable returns `CONTINUE`
      (identity for max-severity — no gates means proceed normally);
      pseudo-code did not spell out this edge case. `failure_reason`
      records the FIRST failing check's reason (config-listed order)
      when `short_circuit=False` — a choice not spelled out in §8,
      pinned by `test_first_failure_reason_is_config_order`. Observer
      gates (`on_pass == on_fail`, decision C.1) are allowed — tested.
      Landed commit `3f07ecd` (commit-3b). 22 unit tests in
      `test_runner.py`.
- [x] Implement action severity resolution helper per §8 so the tuner
      can pick the most-restrictive action when multiple gates fire at
      the same round. See `severity_of` + `resolve_action` above.
      Landed commit `3f07ecd` (commit-3b).
- [x] Replace `run_health_checks(ctx)` call sites in
      `scoring_utils.py` with tuner-side `evaluate_gate(gate_id, ctx)`
      calls at explicit control points. Landed as a three-commit sequence:
      * **commit-5a** (`203212d`): `score_vector` becomes pure scoring.
        Phase 0 pre-FFT short-circuit and Phase 3 post-scoring panel
        removed entirely per Option A. Signature simplified from
        `(fv, scalar, is_degen, reason)` → `(fv, scalar)`. Dropped
        `reference_file_vector` + `degeneracy_threshold_ratio` params.
        7 call sites updated (tuner, `run_comparison.py`, StubSandbox,
        RecordingSandbox, 3 test files). Coverage relocation:
        `test_score_vector_diversity_integration.py` deleted — its
        defense-inside-score_vector premise is incompatible with
        Option A; equivalent regression coverage relocates to the
        tuner-side gate wiring in 5b.
      * **commit-5b** (`16a59e2`): tuner main-loop integration. All
        four `GateAction` semantics implemented (no `NotImplementedError`):
        `CONTINUE` proceeds normally, `INVALIDATE_ROUND` maps to the
        legacy `is_degenerate=True` path (which
        `_apply_degeneracy_reaction` already handles with
        trial-immunity, AMB-5b-A → A), `SKIP_TO_FORMAL` sets
        `completed_rounds = max_rounds - 1` guarded on
        `is_formal_round`, `SKIP_ITER` breaks the outer while. Three
        module-level helpers introduced for testability:
        `_gate_results_to_score_meta` (mapping to legacy contract,
        AMB-5b-B → A pipe-concat failure_reason format),
        `_should_break_iteration`, `_should_skip_to_formal`. Schema
        addition: `ExperimentRecord.gate_action: str | None` for
        observability (AMB-5b-C → B). Gate evaluation inserted
        immediately after `sandbox.score_vector()` returns
        (AMB-5b-D → A). 20 unit tests in `test_gate_integration.py`.
      * **commit-5b follow-up** (`f735b73`): three propagation gaps
        found during the post-5b audit. See "Found during
        implementation" below.

      **Found during implementation (5b audit):** commit-5b landed
      the gate machinery correctly at the tuner-round boundary but the
      collapse signal was silently dropped at three downstream points:
        1. `final_record["failure_reason"]` was guarded by
           `_is_degenerate_formal` (formal + degenerate). Trial-round
           SKIP_ITER at round 1 — the shipped YAML's most important
           case — never propagated its reason string to the record even
           though the phantom score was written. Fixed by unconditional
           write when non-None.
        2. `ExperimentRecord.gate_action: str | None` was defined by
           5b's schema addition but the tuner never wrote it — every
           record shipped with `gate_action = None` regardless of what
           gate fired. Fixed by adding
           `"gate_action": score_results.get("gate_action")` at the
           `final_record` construction site.
        3. `HyperparamTuningOutput.termination_reason` had no
           `"aborted_by_gate"` state. SKIP_ITER breaking the while loop
           fell through to `"completed"` — falsely reporting the
           iteration ended normally. Fixed by extending the `Literal`
           and adding a `_gate_aborted` flag +
           `_compute_termination_state` helper with a precedence table
           (gate > completed > fail-rounds > fallback). 5 new tests in
           `TestComputeTerminationState`.

      **Deferred (audit Gaps #4/#5/#6):** `HyperparamTuningOutput`
      still lacks a top-level structured gate-abort payload;
      `ModelRunSummary` still has no collapse-signal fields; interpreter
      and proposer still have no code paths reading `failure_reason` /
      `gate_action` / `termination_reason`. Structured collapse signals
      stop at the `ExperimentRecord`. Cross-iteration propagation is
      out of scope for the health-check migration; natural fit for a
      Run Monitor design pass.
- [x] Preserve or replace the Phase 0 pre-FFT short-circuit — decided
      in commit-5a as **Option A**: remove Phase 0 entirely and accept
      the ~5-min FFT regression on collapsed models. The
      `after_round: 1` `collapse_check_round_1` gate catches
      class-127 collapse after FFT runs; SKIP_ITER breaks the whole
      iteration so the phantom `5.5762667` never surfaces as an
      accepted best-score (verified via the 5b follow-up's Gap #1 fix
      which ensures the round-1 failure_reason string propagates to
      the record even on a trial round). Options B (internal fast-path)
      and C (new pre-scoring gate mechanism in the framework) were
      considered and rejected in favor of the clean layer separation
      Option A gives: `score_vector` = pure scoring, health checks =
      tuner-side gates. Landed with commit-5a (`203212d`) as part of
      the score_vector rewire.

      **Found during implementation:** the ~5-min FFT regression is
      real but bounded — class-127 collapse historically happens ≤1×
      per iteration on undertrained models, so the cost is one FFT
      sweep per collapsed iteration. Multi-iteration explores can eat
      GPU time on this; if that becomes measurable, revisit Option C
      (add `after_round: 0` sentinel or a `before_score` slot to the
      framework so a pre-FFT gate can fire before
      `sandbox.score_vector()` is even invoked).
- [x] Update all existing health-check tests to the new schemas + add
      gate-routing tests (`should_skip_iter`, `should_skip_to_formal`,
      `should_invalidate_round`). The stale "14 existing tests"
      phrasing predated commit-1 — actual scope by end of commit-4b
      is 32 schemas + 27 config_loader + 6 registry + 22 runner + 9
      peek + 12 output_diversity + 13 amplitude_collapse = **121 unit
      tests** in `tests/unit/execute_tools/health_checks/`.
      Gate-routing property tests live in
      `test_schemas.py::TestGateResult` (8 tests, landed with
      `29edb68` commit-1); action severity + gate evaluation tests
      live in `test_runner.py` (22 tests, landed with `3f07ecd`
      commit-3b).
- [x] Legacy shim disposition — **removed entirely** in commit-4b
      (`1250137`, B-extended path). Zero non-test callers were found
      at removal time. The shim had been dead code since commit-3a
      (referenced removed `run_health_checks`) and semantically dead
      since commit-4b (delegated to a predicate that no longer
      matched the shim's contract). Both test files that exercised
      it (`test_legacy_shim.py`, `test_squid_health_checks.py`) were
      also deleted. See §12 for the removal record.
- [x] Update this doc to remove §14 (migration checklist) and flip §
      Status to "Implemented". **§14-KEEP decision (commit-6):** §14 is
      retained verbatim as a historical decision-context record; the
      status marker at the top of §14 signals migration completion
      without losing the "Found during implementation" annotations that
      captured design decisions (AMB-* series, Option A/L, D8-A/B, D1,
      §14-KEEP itself). SHA backfill after commit-6 lands.

Each unchecked item is a real cost; the design will bake before
implementation starts.

---

## 15. Gates

Test-gate assignments for the six-commit migration, per the canonical
definitions in `docs/gates/gate_testing_standard.md`.

### 15.1 Assignment table

| Commit | What lands | Test gate | Approval? |
|---|---|---|---|
| commit-1 | `schemas.py` — `HealthCheckContext`, `HealthCheckResult`, `GateResult`, `GateAction` (legacy `HealthCheckOutput` / `HealthCheckPanelOutput` kept) | **Unit only** | No |
| commit-2 | `config.py` + `configs/health_checks.yaml` (new `health_gates` YAML) | **Unit only** | No |
| commit-3 | `protocol.py` (from `base.py`) + `registry.py` (from `_registry.py`) + `runner.py` (`get_gates_for_position`, `evaluate_gate`, severity resolution) | **Unit only** | No |
| commit-4 | Rewrite `output_diversity.py` + `amplitude_collapse.py` to the new `HealthCheckSkill` Protocol (returns `HealthCheckResult`, distribution-based `AmplitudeCollapseCheck` per D1) | **Unit only** | No |
| commit-5 | Tuner integration — wire `get_gates_for_position` + `evaluate_gate` into the round loop of `ml_hyperparameter_tune_agent.py`; remove Phase 0/3 `run_health_checks` blocks from `score_vector` | **Unit only** | No |
| commit-6 | Remove legacy `HealthCheckOutput` / `HealthCheckPanelOutput` / `run_health_checks` / `base.py` / `_registry.py`; deprecate `squid_health_checks.py` shim; update §14 checklist | **Unit only** | No |
| **Checkpoint (after commit-6)** | End-of-feature smoke test | **Gate 2 — real LLM + real training** | **Yes** (operator confirms before running) |

**Rationale for no Gate 1.** Gate 1 exists to verify that a real LLM,
given a changed prompt or schema, still produces structurally valid
output. The HealthGate system has no LLM-facing prompts, no
LLM-facing schemas, and does not add or change any tool-call surface.
Every code path in commits 1–6 is exercised by deterministic Python
inputs; a real-LLM smoke would not test anything the unit tests miss.

### 15.2 Unit test scope per commit (rule of thumb)

- **commit-1**: `test_schemas.py` — `GateAction` enum members, `HealthCheckContext` required-field validation, `HealthCheckContext.get_denoised_path` precedence, `HealthCheckResult` inverted semantics, `GateResult.should_*` properties. Do NOT run tests that transitively invoke `score_vector` until commit-5 lands.
- **commit-2**: `test_config_loader.py` — YAML parses, `after_round` / `checks` / `on_pass` / `on_fail` fields, unknown-field rejection (Pydantic strict), missing-field errors.
- **commit-3**: `test_registry.py` (register / get / duplicate raises / `_REGISTRY.clear()` fixture); `test_runner.py` (`get_gates_for_position` returns list, `evaluate_gate` short-circuit, severity resolution: `SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE`).
- **commit-4**: `test_output_diversity_check.py` (constant/near-constant/healthy input, config threshold override); `test_amplitude_collapse_check.py` (distribution-based predicate, `collapse_threshold` override, no reference-vector dependency).
- **commit-5**: `test_tuner_gate_integration.py` (mocked sandbox: `SKIP_ITER` breaks round loop, `INVALIDATE_ROUND` sets `round_score=None`, `SKIP_TO_FORMAL` skips to formal); regression check on the existing test set that transitively invokes `score_vector`.
- **commit-6**: back-compat shim test (deprecation warning, tuple return preserved for `denoising_score_single.py`).

### 15.3 Gate 2 command at the Checkpoint

Verbatim canonical command from `docs/gates/gate_testing_standard.md`:

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/checkpoint_$(date +%s) \
    --run_name checkpoint_smoke \
    --num_iterations 2 \
    --max_rounds 2 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --trial_portion 0.02 \
    --train_portion 0.02 \
    --eval_portion 0.02 \
    --trial_time_budget_minutes 5 \
    --no-force_formal_round \
    --formal_time_budget_minutes 30 \
    --llm_config llm_configs/openai_tiered_v1.json \
    --seed_paths \
        /home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
        /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
```

**Do NOT use `tee`** to capture chain stdout (harness capture file is
sufficient; `tee` fills `/tmp`).

**Estimated cost**: ~$1.50–2.50, ~30–60 min wall time.

**Feature-specific pass criteria** (in addition to the standard's
"chain exits 0" and "non-null finite `denoising_score`"):

- No `pydantic.ValidationError` from `HealthCheckContext` construction anywhere in the chain log
- At least one `evaluate_gate(...)` call fires during the run (grep the chain log for `[Gate ` or the specific gate ids in `configs/health_checks.yaml`)
- If a class-127-collapsed run is intentionally seeded during the smoke, the `output_diversity` gate fires and produces `INVALIDATE_ROUND` (score becomes None, chain continues)

### 15.4 What we intentionally are NOT gating

- **No inference-time diversity peek** — the pre-FFT short-circuit was
  removed per D4. Gates fire only at round boundaries (after inference
  + scoring finish). If a class-127 collapse happens, its score enters
  the file_vector, and the round-boundary `output_diversity` gate
  catches it via `INVALIDATE_ROUND`. The FFT compute is spent, but the
  bad score never poisons `best_score` / `skip_formal_min_delta`
  / `bypass_formal_time_budget_min_delta`.
- **No Gate 1** — no LLM-facing surface is touched.
- **No CI job for Gate 2** — Gate 2 costs real money and takes wall
  time; it is operator-run at the Checkpoint, not on every commit.
