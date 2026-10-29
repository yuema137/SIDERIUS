# Task and run guides

Choose the operation you want to perform. Each linked technical guide identifies
the declarations, source owners and validation needed for that operation.

| Goal | Guide |
| --- | --- |
| Build a task package | [Define a task](define-a-task.md) |
| Add scientific evaluation | [Metric](bring-your-own-metric.md), [Health checks](bring-your-own-health-checks.md) |
| Change data membership | [Train/validation split](bring-your-own-split.md) |
| Write, prepare and run a `workflow.py` (steps, advice, training budgets, research loop, literature judges) | [Workflow declarations](workflow-declarations.md) |
| Choose another research sequence | [Custom workflow](custom-workflow.md) |
| Supply expert instructions | [Advice](advice.md) |
| Launch and inspect a run | [Operating a run](operating-a-run.md), [dashboard](dashboard.md) |
| Continue earlier work | [Workspaces and resume](workspaces-and-resume.md) |
| Diagnose a refusal | [Troubleshooting](troubleshooting.md) |

In SIDERIUS 1.1 you declare an experiment's research steps, advice and
budgets in a Python workflow file (`workflow.py`) that you write with your
coding agent. [Workflow declarations](workflow-declarations.md)
lists what you can set in it, the commands that prepare and run it, how to
stop, pause and resume a research loop, and which features can be combined.
The browser console can show the same file but is experimental.

Start with [getting started](../getting-started/README.md) if this is your first
checkout. Use the [reference index](../reference/README.md) for exact fields.
