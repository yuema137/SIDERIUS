# Workflows and task composition

This package connects the research steps in a fixed order: interpret earlier
results, gather selected evidence, propose, implement, validate and tune a model.
It also resolves the task manifest so every step uses the same declarations.
The caller chooses settings and order; individual nodes own their reasoning.

## Find the right part

| Need | Start here |
| --- | --- |
| Run a chain | [Launch scripts](../../scripts/launch/README.md) |
| Build another workflow | [Custom workflow reference](../../docs/guides/custom-workflow.md) |
| Declare a task | [Task composition](../../docs/reference/task-composition.md) |
| Inspect startup settings | [Launch resolution](../../docs/agent-reference/standard-launch-resolution.md) |

## Technical detail

The [workflows and task composition contract](workflow-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
