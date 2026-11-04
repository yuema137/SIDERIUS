# Workflows and task composition

This package connects the research steps of a workflow: interpret earlier
results, gather selected evidence, propose, implement, validate and tune a model.
It reads `workflow.py` declarations, runs the older fixed chain, and resolves the
task manifest so every step uses the same declarations. The caller chooses
settings and order; individual nodes own their reasoning.

## Find the right part

| Need | Start here |
| --- | --- |
| Prepare and run a `workflow.py` (recommended) | [Write and run a workflow declaration](../../docs/getting-started/README.md#write-and-run-a-workflow-declaration) |
| Write a `workflow.py` | [How a workflow.py is built](../../examples/workflow_declarations/README.md#how-a-workflowpy-is-built) |
| Run a chain with the older launcher | [Launch scripts](../../scripts/launch/README.md) |
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

The in-process workflow accepts `--target_score`. Before each iteration it checks
whether the best formal result that passes Health validity meets the target,
using the metric's declared direction. If a resumed run already meets the target,
it skips new iterations. Startup validation still runs.

The final summary reports the valid score and why the run stopped. The separate
“Best formal (unfiltered, this execution)” line and trial/formal iteration scores
include invalid results and are only progress reports.
