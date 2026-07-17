# Structured Feedback Loop — Experiment Results → Proposer

- **Status**: active
- **Scope**: **generic** (applies to any structured feedback flowing from experiment execution back to the proposer, not just collapse signals)
- **Owner**: TBD
- **Created**: 2026-07-15
- **Last Updated**: 2026-07-16

## 1. Purpose and scope

This document specifies the **generic contract** for structured signals
that flow from experiment execution back through the interpretation node
to the proposer, and how the proposer must consume those signals to
avoid repeating known failures.

**In scope**:

- The complete signal-flow trace with named drop points
- The target-state contract: which fields must survive each hand-off
- Structured field types and semantics (not free-text prose)
- The proposer's `known_failure_fingerprints` avoidance mechanism
- Extension points for new structured failure categories

**Out of scope**:

- Specific failure fingerprint values (task-specific — live in advice)
- Task-specific avoidance heuristics (e.g. "for TIDMAD class-127
  collapse, prefer `alpha=0.5`") — advice, not framework
- Free-text prose feedback (already handled by the existing interpreter
  `narrative` / `take_home_message` fields; this doc adds STRUCTURED
  channels alongside those, doesn't replace them)

## 2. Current signal flow trace (with drop points)

Verbatim from `docs/design/v17_priorities.md`, the current signal path
from a completed round to the next iteration's proposer:

```
1. score_vector(...)  →  (file_vector, scalar)      ✓ pure — carries NO collapse signal
                                ↓
2. tuner: evaluate_gate(...)  →  gate_results       ✓ HealthGate result
                                ↓
3. _gate_results_to_score_meta(...)  →  (is_degenerate, failure_reason,
                                          gate_action_str)                                ✓
                                ↓
4. score_results dict merge: {"denoising_score", "file_vector",
                              "is_degenerate", "failure_reason",
                              "gate_action"}                                              ✓
                                ↓
5. ExperimentRecord written to disk
   (status='failed_mode_collapse' when appropriate)                                       ✓
                                ↓
6. HyperparamTuningOutput  →  has 'status' + per-round records                            ✓
                                ↓
7. build_model_run_summary(HyperparamTuningOutput)  →  ModelRunSummary                    ✗ DROP #1
                                ↓
   ModelRunSummary has: best_file_vector, formal_file_vector,
                        best/formal_score_table, round_scores,
                        round_conclusions, best_config, model_description
                        BUT NO: is_degenerate, failure_reason,
                                gate_action, per-round collapse flags,
                                phantom_score_hits
                                ↓
8. Interpretation agent prompt  →  interpreter sees ModelRunSummary                       ✗ NO collapse
                                                                                             signal
                                ↓
9. Interpretation output  →  key_findings, take_home_message
                             (text only)                                                  ✗ Text-only,
                                                                                             no structured
                                                                                             collapse flag
                                ↓
10. Proposer prompt  →  ExperimentHistory (interpretation) +
                        file_vector patterns                                              ✗ Sees file_vector
                                                                                             shape but no
                                                                                             explicit "this
                                                                                             = collapse"
                                                                                             annotation
                                ↓
11. Next iter's ExperimentPlan  →  configs proposed based on scalar
                                   score + text prose                                     ✗ No mechanism
                                                                                             to avoid known-
                                                                                             collapse config
                                                                                             space
```

Three drop points, all pointing at the same root cause: **structured
signals are collected at the tuner but never survive the hand-off to the
interpreter or proposer.**

## 3. Target signal flow

Same 11 steps, with the drops closed:

```
5. ExperimentRecord           ✓ (unchanged)
        ↓
6. HyperparamTuningOutput     ✓ (unchanged)
        ↓
7. ModelRunSummary            ← ADD structured fields (see §4)
        ↓ (M2 — tracked in v17_priorities.md)
8. Interpretation prompt      ← surface structured fields alongside prose
        ↓
9. InterpretationOutput       ← ADD structured_findings field (typed enum + fingerprint list)
        ↓
10. Proposer prompt           ← ADD known_failure_fingerprints block + avoidance rule
        ↓ (S6, S7, and proposer-side avoidance logic)
11. ExperimentPlan            ← MUST NOT match any fingerprint in the known-failures set
        ↓ (validated by a schema-level check similar to the phantom Branch B validator)
```

## 4. Structured field contracts

### 4.1 `ExperimentRecord` (already implemented)

The tuner already writes these fields at PR #101 (rev-6 HealthGate
migration):

| Field | Type | Semantics |
|---|---|---|
| `is_degenerate` | `bool` | True if any gate failed for this round |
| `failure_reason` | `str \| None` | Free-text reason from the gate that fired |
| `gate_action` | `str` (serialised `GateAction` value) | One of `"continue"`, `"invalidate_round"`, `"skip_to_formal"`, `"skip_iter"` — the **lowercase string value** of the StrEnum, NOT the uppercase member name. See `execute_tools/health_checks/schemas.py::GateAction` for the authoritative definition. |
| `status` | `str` | Includes `'failed_mode_collapse'` when applicable |

### 4.2 `ModelRunSummary` (proposed additions — **M2**, see [v17_priorities.md](./v17_priorities.md) MUST-fix M2)

Add per-round structured fields alongside the existing free-text
`round_conclusions`:

| Field | Type | Semantics |
|---|---|---|
| `per_round_gate_actions` | `list[str \| None]` | One entry per round; the resolved `GateAction` string value (`"continue"` / `"invalidate_round"` / `"skip_to_formal"` / `"skip_iter"`) for each round. `None` for rounds that did not exercise any gate. |
| `per_round_is_degenerate` | `list[bool]` | Chronological flag per round |
| `per_round_failure_reasons` | `list[str \| None]` | Chronological reason strings |
| `failed_fingerprints` | `list[dict]` | Distilled failure fingerprints — see §4.4 |
| `terminated_early_reason` | `str \| None` | Enum: `completed` \| `aborted_by_gate` \| `aborted_fail_rounds` \| `partial` |

Existing free-text fields (`round_conclusions`, `best_config`, etc.) are
preserved unchanged for back-compat.

### 4.3 `InterpretationOutput` (proposed additions)

Add a `structured_findings` block alongside the existing prose
`take_home_message` / `key_findings`:

```python
class StructuredFinding(BaseModel):
    finding_type: Literal[
        "collapse_detected",
        "training_divergence",
        "resource_exhausted",
        "no_learning_signal",
        "other",
    ]
    fingerprint: dict  # hashable config signature; see §4.4
    evidence: str      # short prose reference to which round/artifact
    severity: Literal["blocking", "warning", "informational"]

class InterpretationOutput(BaseModel):
    # ... existing fields ...
    structured_findings: list[StructuredFinding] = Field(default_factory=list)
    narrative: str  # renamed from take_home_message for clarity (kept as alias)
```

The interpreter agent's prompt template gains a section instructing it
to fill `structured_findings` with typed entries for every actionable
signal (including collapse), in addition to the existing free-text
narrative.

### 4.4 Fingerprint contract

A **fingerprint** is a hashable dict summarising a configuration
signature that produced an observed failure. Format:

```python
{
    "model_config": {"model_type": "...", <arch params>},
    "train_config": {"lr": ..., "epochs": ..., "optimizer_type": "..."},
    "loss_config":  {"loss_type": "...", <loss params>},
    # Task-specific extensions live under "task_specific" and are
    # opaque to the framework:
    "task_specific": {...},
}
```

Two fingerprints "match" iff every key in the first is present in the
second with equal value (subset-match, so proposer can specify wildcards
by omission). **The definition of match is generic;** task-specific
"which fields matter for match" belongs in advice.

### 4.4.1 Fingerprint generation vs. matching (conservative producer, lenient consumer)

**Producer contract** (fingerprint generation, done at the tuner or
interpreter side after a failure): the fingerprint MUST include every
non-default field of `model_config`, `train_config`, and `loss_config`
that was actually used in the failed run. Do not omit fields on the
assumption that they are irrelevant. When in doubt, include the field.

**Consumer contract** (fingerprint matching, done at the proposer's
Pydantic validator): a proposal matches a stored fingerprint iff every
key in the stored fingerprint is present in the proposal with equal
value (subset-match). Extra keys in the proposal are allowed.

**Why this asymmetry**: incomplete generation produces false negatives
(the proposer re-explores the failed config with one field changed and
the fingerprint doesn't match). Conservative generation + lenient
matching converts the failure-avoidance guarantee from "exact repeat"
to "any config that satisfies the failed pattern," which is what we
want.

**Match responsibility**: the producer decides what's in the
fingerprint; the framework matches by subset. Task-specific rules about
"which fields matter" are enforced by the producer's fingerprint
content, not by a separate config the matcher reads.

## 5. Proposer avoidance mechanism

### 5.1 Generic contract

The proposer receives, as part of its prompt context, a
`known_failure_fingerprints` list — accumulated across all previous
iterations of the chain. For each proposal it generates, it MUST verify
no fingerprint in that list subset-matches the proposal.

At the schema layer, `ProposalOutput` gains a Pydantic validator
`_validate_no_known_failure_fingerprint_match` symmetric to the existing
`_validate_branch_b_registry_membership` (see
`agent/schemas/proposal.py:1105`, decorated
`@model_validator(mode="after")` with `(self, info)` signature reading
Pydantic context) — activated by passing
`context={"known_failure_fingerprints": [...]}` to `model_validate`. If
a proposal matches, the validator raises with actionable text, and the
proposer's schema-retry loop (`LLMBridge.generate` with structured
output) re-prompts immediately.

### 5.1.1 Retry limits and fallback

The `_validate_no_known_failure_fingerprint_match` validator interacts
with `LLMBridge.generate`'s schema-retry loop. To prevent unbounded
retries:

- **Max retries per proposal request**: 3 (inherit the existing
  `LLMBridge.generate` default).
- **Fallback on exhaustion**: if 3 successive proposals all match
  known-failure fingerprints, the proposer emits a `ProposalOutput`
  with `status=exhausted_avoidance` and an empty proposal list. The
  tuner then either (a) skips to next iteration if `--force_formal_round`
  is set, or (b) terminates the chain with `termination_reason='avoidance_exhausted'`.
- **Fingerprint retirement**: a fingerprint that has caused N (default
  N=5) successive avoidance rejections without being matched by any
  accepted proposal SHOULD be marked `retired: true` in its stored
  entry. Retired fingerprints are still visible in the proposer
  context (for LLM narrative reasoning) but no longer enforced by the
  validator. This handles the case where a fingerprint has grown
  overly broad and is blocking exploration.

### 5.2 Task-specific avoidance heuristics

The generic rule is: don't propose a config that matches a known
failure. Task-specific advice (e.g. "if the failure was class-127
collapse, prefer `alpha=0.5` and lower `lr`") lives in
`advice/workflow/<task>_*.json` under a `propose` block, exactly like
the existing `tidmad_collapse_advice.json`. **The framework never encodes
per-task recovery heuristics.**

## 6. Acceptance criteria

The signal flow is generic iff **all** of the following hold:

1. A new failure category (e.g. `training_divergence`, not collapse)
   can be added by:
   - Adding a `HealthCheckSkill` that sets `passed=False` with a new
     `failure_reason` prefix
   - Adding the enum value to `StructuredFinding.finding_type`
   - No changes to the interpreter or proposer node code
2. Unit tests prove **every** structured field survives every hand-off
   from tuner → tuning output → summary → interpreter → proposer.

   **Golden fixture test** (required):
   - Input: a synthetic `ExperimentRecord` with
     `is_degenerate=True`,
     `failure_reason='amplitude_collapse: 99% class-127'`,
     `gate_action='invalidate_round'` (lowercase — the serialised
     `GateAction` value, not the uppercase member name).
   - Assertion at each downstream stage:
     - After `build_model_run_summary`:
       `summary.per_round_is_degenerate[-1] == True`,
       `summary.per_round_failure_reasons[-1]` contains
       `'amplitude_collapse'`,
       `summary.per_round_gate_actions[-1] == 'invalidate_round'`.
     - After interpretation node:
       `interpretation.structured_findings` contains at least one
       entry with `finding_type='collapse_detected'`.
     - After proposer prompt assembly: the prompt context contains a
       `known_failure_fingerprints` entry whose
       `fingerprint["model_config"]` equals the failed round's model
       config.
   - Location: `tests/integration/feedback_loop/test_collapse_signal_survives_handoffs.py`.

3. A proposer receiving a known-failure-fingerprint context cannot
   produce a proposal that subset-matches any entry — validation at the
   schema layer forces re-generation.
4. Zero task-specific fields exist in `ModelRunSummary`,
   `InterpretationOutput`, or `ProposalOutput`. All task specificity
   lives inside `fingerprint["task_specific"]` or in advice files.

### 6.5 Backward compatibility with pre-M2 records

`ExperimentRecord` entries produced before M2 lands may lack the new
structured fields. To avoid crashes when the interpreter or proposer
reads legacy data:

- All new fields on `ModelRunSummary`, `InterpretationOutput`, and
  `ProposalOutput` MUST have safe defaults (`None` for scalars,
  `list` factory for lists, `dict` factory for dicts).
- Downstream nodes MUST treat `None` and empty collections as "no
  structured signal available; fall back to prose interpretation."
- No downstream code path may hard-require any new field to exist.
  This is verified by a unit test that loads a golden pre-M2 record
  and runs it through the interpretation and proposer nodes without
  error.

## 7. Extension points

### 7.1 Adding a new structured failure category

1. In `agent/schemas/interpretation.py`, add the enum value to
   `StructuredFinding.finding_type`.
2. (Optional) In `execute_tools/health_checks/`, add a
   `HealthCheckSkill` that surfaces the new category with a
   distinguishable `failure_reason` prefix.
3. In the interpreter prompt template, mention the new category in the
   list of `finding_type` values the model may emit.

No changes required to the tuner, proposer, or workflow orchestration.

### 7.2 Adding new fields to `ModelRunSummary`

Route:

1. Add the field to `agent/schemas/interpretation.py::ModelRunSummary`
   with `default=None` or `default_factory=list` for back-compat.
2. Populate it in
   `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py`
   (the tuner→interpreter protocol function).
3. Reference it in the interpreter prompt template.

Add a round-trip unit test asserting the field survives; ban silent drops
by making the protocol function raise on any missing key required by the
downstream schema.

## 8. What lives in advice, not here

- Specific fingerprint values that a task considers "known failure"
- Task-specific match rules ("for TIDMAD, `loss_type` matters but
  `weight_decay` doesn't")
- Task-specific recovery heuristics ("if class-127 collapse, try
  `alpha=0.5`")
- Task-specific narrative templates the interpreter should use for
  prose

See `docs/design/tidmad_collapse_advice_and_forensics.md` for the
TIDMAD-specific instantiation of these hooks.

## 9. Related docs

- `docs/design/collapse_detection_framework_generic.md` — the detection
  side (upstream of this doc). This doc picks up at the point where a
  detector has fired and specifies how that signal flows onward.
- `docs/design/tidmad_collapse_advice_and_forensics.md` — the
  task-specific bindings of the mechanisms described here (fingerprint
  values, avoidance heuristics, forensic case studies).
- `docs/design/pluggable_health_checks.md` — the HealthGate framework
  that produces the structured signals this doc threads onward.
- [`docs/design/v17_priorities.md`](./v17_priorities.md) — this work is
  tracked as **M2** in the v17 MUST-fix list. Related items: **M1**
  (dedup produces the fingerprints this doc threads onward), **M4**
  (phantom table provides one class of known-failure fingerprint),
  **S6** (interp prompt template update), **S7** (proposer prompt
  update to reference `known_failure_fingerprints`).
- `docs/design/agent_composition_architecture.md` — the Run Monitor
  agent (issue #100) is the eventual orchestrator-level umbrella for
  the signal flow specified here; short-term this doc addresses the
  gap at the tuner→interpreter→proposer boundary.
- Related open issues: **#95** (bidirectional cross-iteration
  information flow), **#107** (design: collapse signal propagation
  full-cycle), **#100** (Run Monitor agent — long-term umbrella).
