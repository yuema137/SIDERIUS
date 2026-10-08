# Health checks

Health checks examine model outputs for declared failures such as collapsed
predictions. They answer whether a result meets the task's validity rules;
the metric separately measures quality. The task supplies checks and thresholds,
and framework policy determines the consequences of their verdicts.

## Find the right part

| Need | Start here |
| --- | --- |
| Understand the decisions | [Health concepts](../../../docs/concepts/health-gates.md) |
| Add a task-owned check | [Extension reference](../../../docs/guides/bring-your-own-health-checks.md) |
| Inspect evaluation and eligibility | [Health mechanism](../../../docs/agent-reference/mechanisms/health-gates.md) |
| Choose framework policy | [Policy configuration](../../../configs/health/README.md) |

## Technical detail

The [health checks contract](health-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
