# Deployment-selected complete candidate evaluation

A deployment may expose inference, scoring and Health through a protected
candidate evaluator. Bind its public client with
`execute_tools.evaluation_execution.bind_candidate_evaluation(executor)` in the
same process that invokes the native tuner. Without that explicit binding, the
original local inference, scoring and round Health path remains active for a
local `EvaluationMetric`. A candidate-only composition requires this binding
before the tuner starts.

## Public composition without private metric source

Keep the original metric declaration and public scoreability contracts. In the
deployment's additional composition manifest, select:

```yaml
metric:
  declaration: /public/task/metric_spec.json
  implementation:
    module: execute_tools.evaluation_metric
    symbol: CandidateEvaluationMetric
```

Retain any task-declared `scoreability_contracts` alongside these fields. The
deployment manifest may reference a frozen public task package without editing
it. Resolve relative task references against their original manifest before
writing an overlay elsewhere.

This metric handle exposes the declared `MetricSpec` without importing private
arithmetic. Complete evaluation execution is part of the composition identity;
the scientific declaration stays unchanged. Composition loading itself needs no
executor, so proposal and implementation can use the task declaration. Native
tuner metric resolution requires an explicit executor and fails before training
if it is absent. Local scoring-child entrypoints refuse this handle. Secondary
metric declarations retain their local implementation contract; the complete
evaluator must still account for every requested secondary metric.

This differs from [per-epoch validation](private-validation-execution.md):
validation returns training-objective observations; complete candidate evaluation
returns the declared scientific metric and Health evidence. Both bindings can be
used together. Neither grants private-data access or authenticates a caller.

## Client contract

Implement `evaluate(CandidateEvaluationRequest) -> CandidateEvaluationResult`.
The request contains the run/attempt/model identity, public workspace and model
location, validated model/training/loss configuration, model I/O contract, requested task scope, metric
specification, declared secondary metrics and Trial/Formal role.

The deployment client owns trained-candidate reconstruction/export, transport,
candidate-byte verification, private evaluator authorization, process deadline
and cancellation. Execute generated model code only inside the research boundary.
The native interface does not start a service or install privileges.

Return the original evaluator's primary metric outcome, detailed typed Health
results, eligibility, refusal reason when ineligible, candidate digest, receipt
path and Health configuration digest. Report an outcome or error for every
requested secondary metric. A transport failure raises; it must not fabricate a
scientific refusal or a successful empty response.

The boundary checks attempt identity, requested scope, primary metric identity
and direction, and complete secondary accounting. Eligible feedback requires a
finite metric and valid Health evidence. A bound client failure never selects
local inference as a fallback.

## Scope, records and timing

Keep `requested_scope` and `evaluated_scope` separate. If an evaluator only
accepts a complete evaluation split, record that actual scope; do not describe
its score as the requested trial subset. This interface does not change the
training scope or the task's scientific evaluation rule.

The tuner retains common training diagnosis, result interpretation, existing
selection policy and output cleanup. A completed evaluation's original facts
are retained on `ExperimentRecord.external_evaluation`, beside the native metric
and Health fields, so later policy transformations do not overwrite the source
metric. Preserve the original receipt at the recorded location.

The external stage's wall time includes export, transport, inference, scoring
and Health and is charged to `scoring_time_s`. There is no separate local
inference invocation (`inference_time_s` is zero). The receipt's
`timing_accounting: combined_under_scoring_time_s` states this explicitly; these
columns must not be interpreted as measured remote inference/metric kernel time.

## Deployment qualification

A client binding alone does not qualify a deployment. Its public task composition
must resolve without private scorer imports. Verify a real trained candidate,
actual evaluator receipt, declared scope and Health, failure cleanup, deadlines,
and immutable task/infra inputs before launch. Full-node admission/preflight and
candidate-export compatibility also need deployed evidence.

When a complete evaluator is bound, the native resource probe still materializes
the public training batch, but does not materialize a local validation input for
inference preflight. The complete evaluator owns inference and its data access.
This does not grant access to private validation data or estimate the evaluator's
resource use. Candidate export and the actual evaluator must qualify the model's
inference interface. Unbound local evaluation retains its original input probe.

The native run also omits its local scoring-reference preload when a complete
evaluator is bound. Task scope construction still owns sampling requirements;
this does not fabricate or substitute sampling metadata. The complete evaluator
owns its scoring references. Local evaluation keeps its original declared
reference-file requirement.
