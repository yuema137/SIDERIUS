# Evaluation metrics

**Semantic owners**: `execute_tools/evaluation_metric.py`,
`execute_tools/metric_order.py`
**Status**: ✅ Current

---

## Purpose

Own what "better" means: the metric declaration, the one interpretation of
direction, the executable pre-arithmetic scoreability check, and the boundary
between selection-driving and observational quantities.

## Non-responsibilities

- Not the training objective. Losses are a different lifecycle role — and the
  boundary is **typed, not lexical**: `MetricSpec.id` is an *opaque identity*, so
  `log_loss` is as declarable as `accuracy`.
- Not aggregation policy across runs.
- Not health/validity. A metric refusal is not a health verdict.

## `MetricSpec`

Frozen, `extra="forbid"`.

| field | required | notes |
|---|:---:|---|
| `id` | ✅ | opaque identity, validated as a metric identifier |
| `direction` | ✅ | `Literal["higher", "lower"]` — explicit, never inferred |
| `aggregation` | ✅ | |
| `scoreability` | ✅ | a `ScoreabilityContract` (`SerializeAsAny`) |
| `transform`, `transform_params`, `references` | — | default `None` / `{}` / `()` |

There is **no `higher_is_better` boolean anywhere in the repository.**

## `MetricOrder` — the one direction authority

All ordering decisions ask `MetricOrder`; it is the only thing that reads
`spec.direction`. Even prose shown to the agents ("higher is better", "best so
far") is rendered via `direction_words()` rather than written by hand.

A second direction field, or a second interpreter, is the defect this design
exists to prevent. A metric that is negative-valued *and* higher-is-better —
TIDMAD's — breaks every sign-based heuristic, which is why none exists.

The same-loss `final_loss` rank deliberately does **not** ask `MetricOrder`, and
is pinned not to move.

## Scoreability — refusal before arithmetic

```python
class ScoreabilityContract(BaseModel, ABC):
    contract_id: str
    def check(self, deliverables: Mapping[int, str]) -> ScoreabilityVerdict: ...
```

Abstract, frozen, `extra="forbid"`. The check must be **total** — it may never let
a filesystem or HDF5 error escape. `ScoreabilityVerdict.scoreable` is *derived*:
an empty `failures` tuple is the only way to be scoreable.

A refusal produces `NotScoreableResult` (frozen, `extra="forbid"`, carrying
`metric_id`, `direction`, `verdict`; a model validator refuses a *scoreable*
verdict — "a scoreable verdict must yield a `MetricResult`"). Downstream that
becomes an `error_scoring` record with `failure_type="not_scoreable"` and a
`metric_refusal`.

Built-ins: `PresenceScoreabilityContract`, `TidmadScoreabilityContract`.

## Order of operations in production scoring

Load-bearing, in both the in-process route and the scoring subprocess:

```
DataScope validation
  → ScoreabilityContract.check          (structured NotScoreableResult on refusal)
  → scoring_utils.score_vector          (pure arithmetic, untouched 2-tuple)
```

Never re-inline `score_vector` at a call site; never move the contract after the
arithmetic.

## Primary versus secondary

**Secondaries are observational.** The rule is stated on the carrier itself:
*"nothing in this tuple may ever become an operand of an ordering expression"*.

Enforcement is structural, not conventional:

- `metric_order.py`, `persisted_ranking.py` and `per_file_best.py` contain **zero**
  occurrences of `secondary`;
- an AST census over the lifecycle keeps secondaries out of ordering expressions;
- proposer consumption is frozen off
  (`agent/schemas/proposer_evidence.py:92` — `NO_RAW_SECONDARY_CONSUMPTION`).

Evaluation happens only **after** a successful primary result, in
`_evaluate_secondary_metrics`. A secondary refusal leaves the attempt successful.

**The catch order is load-bearing**: `ScopeViolationError` subclasses `ValueError`,
so it is caught **first and re-raised** to the outer handler. An ordinary crash in
a secondary is diagnostic provenance that projects `unavailable` — never a fourth
scientific state.

A run declaring no secondaries writes **no** secondary record key, **no** `_stats`
key and renders zero bytes.

## Fail-closed behaviour

| condition | result |
|---|---|
| implementation is not an `EvaluationMetric` | composition refused |
| implementation rewrites the declared `spec.id` | composition refused |
| duplicate secondary id / collision with primary | composition refused |
| deliverable not scoreable | `NotScoreableError` → `error_scoring` record |
| a score-bearing tuner output carries no `MetricSpec` | interpretation input **fails closed** — a legacy output is a named refusal, never a re-derivation |

## Invariants

- `TIDMAD_METRIC_ID` and the direction vocabulary are declared **once**, in the
  metric module, and guarded.
- The frozen TIDMAD score formula is byte-identical and is never reweighted,
  clipped, or renormalised. New metrics plug in beside it.
- Record field names `denoising_score` / `file_vector` / `score_table` are frozen;
  `metric_result` / `metric_refusal` are additive.

## Source map

| concern | location |
|---|---|
| `MetricDirection` | `execute_tools/evaluation_metric.py:116` |
| `ScoreabilityContract` | `:198-227` |
| built-in contracts | `:230-260+` |
| `MetricSpec` | `:370-402` |
| `MetricResult` | `:405-430` |
| `NotScoreableResult` | `:433-458` |
| `EvaluationMetric` ABC | `:495` |
| `MetricOrder` | `execute_tools/metric_order.py:59-104` |
| `direction_words()` | `:138-147` |
| secondary evaluation | `nodes/ml_hyperparameter_tune_agent/execution.py:755-790`, called `:1030-1043` |
| record transport | `nodes/ml_hyperparameter_tune_agent/records.py:1000-1002, 1163-1165` |
| observational rule | `workflows/task_composition.py:246-249` |

## Related

- [Objectives and metrics, for humans](../../concepts/objectives-and-metrics.md)
- [Composition](composition.md) · [Plugins](plugins.md)
