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

## Technical detail

The [training, inference and scoring contract](execution-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
