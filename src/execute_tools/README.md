# Training, inference and scoring

These modules execute the work requested by the research workflow. A task
supplies how to read its data, write predictions and calculate its metric.
The framework runs those operations with explicit data scope and typed inputs.
Start here when connecting a new task or investigating an execution failure.

## Find the right part

| Need | Start here |
| --- | --- |
| Supply data access | [Data-path contract](../../docs/agent-reference/mechanisms/data-path-and-scope.md) |
| Define a metric or scoreability check | [Metric extension](../../docs/guides/bring-your-own-metric.md) |
| Understand child processes | [Execution and transport](../../docs/agent-reference/mechanisms/execution.md) |
| Add validity checks | [Health checks](health_checks/README.md) |

## Calling training from Python

Both `run_experiment_streaming` and the legacy `run_experiment` require a
`TrainingSeedPlan`. Build it from the run's recorded `SeedContext` and pass it
as the required keyword argument `seed_plan=plan`. Omitting it raises
`TypeError`; passing `None` raises `MissingRunSeed`. Both stop before model
construction. The trainer CLI resolves its seed context for you. See the
[seed contract](../../docs/agent-reference/mechanisms/seeding.md#trainer-seeding)
for seed transport and reproducibility limits.

## Technical detail

The [training, inference and scoring contract](execution-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
