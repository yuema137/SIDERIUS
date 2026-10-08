# Evaluation metrics

Semantic owners: `src/execute_tools/evaluation_metric.py` and
`src/execute_tools/metric_order.py`. Composition ownership:
`src/workflows/task_composition.py::_compose_metric` and
`_compose_scoreability_contract_types`.

## Scope

A metric evaluates a declared scientific result and supplies the scalar used
for ranking. Training loss is a separate lifecycle role. Metric identity is
opaque: a name such as `log_loss` does not make a metric a training objective.
Health checks are separate validity evidence, not metric arithmetic.

## Declaration and direction

`MetricSpec` is frozen and forbids extra fields. It requires `id`, `direction`
(`higher` or `lower`), `aggregation`, and an executable `scoreability` contract.
Optional transform parameters and reference identifiers retain their declared
values. The composer validates the implementation against the declaration;
a plugin cannot silently replace the declared metric identity.

`MetricOrder` owns interpretation of metric direction. Ranking, best/worst
sentinels and directional prompt language use it instead of guessing from a
metric's name or sign. Same-loss `final_loss` comparisons are a different
operation and do not become scientific metric ranking.

## Scoreability and extension

`ScoreabilityContract` is a frozen Pydantic abstract model. Its
`check(deliverables: Mapping[int, str]) -> ScoreabilityVerdict` returns named
failures instead of incidental filesystem exceptions. `scoreable` is derived
from an empty failure tuple.

The framework supplies `PresenceScoreabilityContract` under
`deliverable_presence`: at least one artifact must be named and every named
path must be a file. This does not validate scientific content. Other acceptance
rules belong to the task. A metric section's `scoreability_contracts` mapping
resolves each contract id to a `ScoreabilityContract` subclass through a
`file:` or `module:` reference. `metric_spec_from_declaration` uses that mapping
to reconstruct the executable contract. Unknown ids and invalid subclasses
refuse at composition. Primary and secondary metric sections use this same
extension boundary.

Selected scoreability plugin bindings participate in the composition fingerprint;
file-backed implementations contribute their captured content identity. Changing
which contract a metric uses is a semantic change, including exchanging
implementations between primary and secondary roles. The
[manifest reference](../../reference/task-composition.md) owns the declaration
format and fingerprint details.

## Production ordering and failure behavior

For deliverable-based metrics, `EvaluationMetric.evaluate` calls the scoreability
contract first. A refusal returns `NotScoreableResult`; `_compute` is not called.
A success calls the task metric's arithmetic and creates `MetricResult`.
The composed scoring child decodes the task payload with `TaskDataPath`, then
passes `evaluation_payload`, `task_scope` and `data_dir` to the metric.
`TaskEvaluationPayload` can explicitly name multiple artifacts for scoreability.
There is no mandatory route through the legacy `score_vector` helper.

The tuner records a scoreability refusal as `error_scoring` with
`failure_type="not_scoreable"` and `metric_refusal`. Successful scoring reaches
the shared Health boundary; an earlier scoring failure does not establish a
Health pass. The [Health mechanism](health-gates.md) owns enablement,
applicability and candidate eligibility.

A separate `CandidateEvaluationMetric` supports declared candidate execution
rather than persisted-deliverable scoring. Its executor, request/result types,
transport and failure contracts are owned by
[candidate evaluation](../../reference/candidate-evaluation-execution.md).
Do not apply the deliverable `_compute` calling convention to that adapter.

## Primary versus secondary

Primary metric direction determines scientific ordering. Secondary metrics
are observational and cannot replace the primary ranking scalar. They are
evaluated only after primary scoring succeeds. A secondary refusal or ordinary
computation failure is recorded as diagnostic unavailability; scope violations
and task-code integrity failures retain their fatal behavior.

A task with no secondary declarations has no secondary evidence to project.
No caller should infer a replacement primary from the order or availability of
secondary results. `evaluate_declared_secondaries` owns common evaluation, while
the scoring child and tuner own transport into persisted records.

## Persisted records and replay

`metric_spec_from_persisted_record` reconstructs data needed to inspect recorded
identity without implicitly importing external task code. Unknown external
contracts become `PersistedScoreabilityContract`: their fields survive, but
calling `check` raises a runtime refusal. Active scoring requires explicit task
composition and the real executable subclass. Readability of a historical
record is not permission to execute its declared contract.

Historical names such as `denoising_score`, `file_vector` and
`TIDMAD_METRIC_ID` remain compatibility vocabulary. They do not select scientific
arithmetic or task data. Scientific TIDMAD implementations belong to siderius-exp.

## Validation owners

- `tests/unit/workflows/test_metric_scoreability_extension.py`: task-owned
  contract binding and metric extension.
- `tests/unit/workflows/test_metric_scoreability_identity.py`: implementation
  changes, primary/secondary selection and resume identity.
- `tests/unit/workflows/test_external_metric_resume.py`: external metric
  declarations survive record reading and resume boundaries.
- `tests/unit/execute_tools/`: metric arithmetic, ordering and refusal cases.

These are test locations, not a claim that a scientific run or the whole suite
was executed for a documentation change.

## Related

[Metric extension](../../guides/bring-your-own-metric.md),
[composition](composition.md), [plugins](plugins.md), and
[objectives and metrics](../../concepts/objectives-and-metrics.md).
