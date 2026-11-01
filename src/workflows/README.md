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
| Check a workflow declaration offline (not execute it) | [Declaration foundation](definition/README.md) |
| Check and admit your own adaptor code (not run it in a workflow yet) | [Custom adaptor contract](custom_adaptors/custom-adaptor-contract.md) |
| Declare a task | [Task composition](../../docs/reference/task-composition.md) |
| Inspect startup settings | [Launch resolution](../../docs/agent-reference/standard-launch-resolution.md) |

## Technical detail

The [workflows and task composition contract](workflow-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.

## Stop at a target score

The in-process workflow accepts `--target_score`. It stops after an iteration
when a formal result that passes Health validity meets the target, using the
metric's declared direction. A high score from an invalid result cannot stop
the run. The final “Best formal (unfiltered, this execution)” line includes
invalid results and is only a progress report.
