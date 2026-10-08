# Models, losses and plugins

This package loads built-in and task-supplied models and losses. Each model
has a validated configuration and a declared input/output contract. Research
agents can generate plugins, and task authors can provide their own; both use
the same loading interfaces. Training itself is owned by the execution tools.

## Find the right part

| Need | Start here |
| --- | --- |
| Add or inspect a plugin | [Plugin contracts](../../docs/agent-reference/mechanisms/plugins.md) |
| Define the scientific input/output shape | [Task definition](../../docs/guides/define-a-task.md) |
| Find generated models for a run | [Workspace reference](../../docs/guides/workspaces-and-resume.md) |
| Understand model execution | [Execution tools](../execute_tools/README.md) |

## Technical detail

The [models, losses and plugins contract](model-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.

<a id="inputs"></a>
For generated-library and plugin-directory resolution, see
[inputs and precedence](model-contract.md#inputs).
