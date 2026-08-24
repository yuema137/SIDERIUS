# Training objective, history and diagnosis

**Semantic owners**: `execute_tools/training_history.py` (the observation
payload), `agent/schemas/training_diagnosis.py` (the derived facts)
**Status**: ✅ Current

---

## Purpose

Carry what happened *during* training — per-epoch curves and a compact,
deterministic reading of them — from the trainer subprocess to the tuner, the
interpreter and the proposer, without any consumer re-deriving it.

## Non-responsibilities

- **Not the evaluation metric.** These are the objective's curves; model
  selection reads the primary metric. See [metrics](metrics.md).
- **Not calibrated judgement.** The diagnosis reports *facts with explicit
  tolerances*, never labels like "overfitting" or "converged".
- Not health validity. A degraded curve is not a health verdict.

## Position

```
training subprocess  →  TrainingHistory (R2 + optional R3)
                     →  interpret_training_results (tuner)
                     →  TrainingDiagnosis (derived ONCE)
                     →  ExperimentRecord  →  interpreter, proposer
```

The diagnosis is derived **once**, in the tuner, and persisted. Consumers read
it; they never recompute it.

## `TrainingHistory` — the observation payload

Frozen, `extra="forbid"` — a producer adding an undeclared key fails at the tuner
boundary rather than leaking through.

| field | meaning |
|---|---|
| `cadence` | `per_epoch` |
| `objective_kind` | the resolved objective family — **a label, not an identity** |
| `objective_config_fingerprint` | sha256 of the canonical resolved `LossConfig`; the configuration surface only, **not** a hash of custom plugin code |
| `objective_reduction` | `mean` \| `sum` |
| `epoch_statistic` | sample-count-weighted mean of the batch criterion |
| `comparability` + `comparability_reason` | see below |
| `epochs_planned` / `epochs_completed` | truncation is derivable |
| `train_objective` | **R2** — the same floats as the legacy loss history |
| `validation_objective` | **R3** — `None` only when no validation scope was given |
| `validation_requested_samples{,_before_limit}`, `validation_samples` | scope provenance |

### Comparability

Whether two runs' objective curves may be compared at all:

| condition | verdict |
|---|---|
| a custom objective | `not_established` |
| reduction is `sum` | `not_established` |
| an audited built-in kind with `mean` reduction | `established` |
| a future built-in kind not yet audited | `not_established` — **honest by default** |

The default matters. A new built-in objective is *not* silently assumed
comparable; it must be audited into the established set.

### Why `_before_limit` is an explicit field

The clamp's provenance is otherwise unrecoverable. A ceiling of 2,000 with a
requested scope of 2,000 reads identically whether the natural scope was 2,000
and the ceiling did not bind, or was 12,000 and the ceiling clamped it. Recording
the pre-limit count makes `was_limited` derivable with certainty, and is strictly
more informative than a boolean.

## `TrainingDiagnosis` — the derived facts

Frozen, `extra="forbid"`. Deterministic, compact, **calibration-free**.

Every optional field is `None` *exactly when* the history cannot support it —
this is a contract, not an accident:

| state | meaning |
|---|---|
| `state: ok` | a finite history |
| `state: absent` | no history payload — a legacy trainer or a crash |
| `state: invalid` | empty R2, or any non-finite value in R2/R3 (divergence evidence; raw values stay on the record) |
| `validation_state: absent` | "not fully supported" — the legacy tolerance |

Facts carried: first/last/min of the train and validation curves with their
epochs, `truncated`, the final-versus-best validation degradation (absolute and
relative), and trend readings.

`comparability` is **copied onto the diagnosis** so that a consumer holding only
the diagnosis knows *why* a gap is `None` rather than guessing.

Trends are computed against an explicit tolerance: fewer than two points is
`single_point`; a symmetric relative change within tolerance is `flat`;
otherwise `decreasing` or `increasing`. There is no hidden smoothing.

## Invariants

- The diagnosis is derived once and never recomputed downstream.
- Facts, not labels. Any calibrated interpretation belongs to the agents reading
  it, not to this schema.
- `objective_kind` is a **label**; identity is the fingerprint. Two runs with the
  same kind and different configs are not the same objective.
- R2 stays byte-identical to the legacy loss history — the additive R3 and the
  diagnosis do not change what R2 means.
- The history is **hidden from the planner and reflector prompts** at the
  renders where it was hidden before; only declared deltas reach them.
- A missing R3 where validation was expected is an `error_training` outcome, not
  a silently absent field.

## Fail-closed behaviour

| condition | result |
|---|---|
| trainer emits an undeclared key | rejected at the tuner boundary |
| expected validation, missing R3 | `error_training` |
| non-finite value in R2 or R3 | `state: invalid`; raw values preserved on the record |
| custom or `sum`-reduced objective | `comparability: not_established`, with a reason |

## Source map

| concern | location |
|---|---|
| `TrainingHistory` | `execute_tools/training_history.py:123` |
| comparability resolution | `:110-120` |
| `TrainingDiagnosis` | `agent/schemas/training_diagnosis.py:68` |
| trend computation | `:55-62` |
| tuner interpretation | `nodes/ml_hyperparameter_tune_agent/` (`interpret_training_results`) |
| interpreter consumption | `nodes/result_interpretation_agent/evidence.py` |
| rendering | `agent/prompt_templates/{tuner,interpretation}/rendering.py` |

## Related

- [Metrics](metrics.md) — the other kind of number
- [Objectives and metrics, for humans](../../concepts/objectives-and-metrics.md)
- [Tuner node](../../../nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md)
