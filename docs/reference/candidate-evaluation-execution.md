# Deployment-selected complete candidate evaluation

A deployment may expose inference, scoring and Health through a protected
candidate evaluator. Bind its public client with
`execute_tools.evaluation_execution.bind_candidate_evaluation(executor)` in the
same process that invokes the native tuner. Without that explicit binding, the
original local inference, scoring and round Health path remains active.

This differs from [per-epoch validation](private-validation-execution.md):
validation returns training-objective observations; complete candidate evaluation
returns the declared scientific metric and Health evidence. Both bindings can be
used together. Neither grants private-data access or authenticates a caller.

## Client contract

Implement `evaluate(CandidateEvaluationRequest) -> CandidateEvaluationResult`.
The request contains the run/attempt/model identity, public workspace and model
location, validated model/training configuration, requested task scope, metric
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
