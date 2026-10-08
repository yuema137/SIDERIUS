# Get started with your coding agent

We recommend preparing your task and experiment with a coding agent. In
**Assistant** mode, ask it to follow the [setup skill](../agent-reference/siderius-setup-review/SKILL.md)
and guide you through the missing decisions. In **Professional** mode, you lead
the choices and use your agent to read contracts, edit files and check the setup.
Both use the same framework; these names do not select a CLI flag or force a
review. Handwritten setup is supported, but is not the recommended first route.

1. Open the repository in your coding agent and give it your task, data location
   and intended external project directory. The [homepage example](../../README.md#start-with-your-coding-agent)
   gives a starting request.
2. Follow [installation](installation.md) for the exact environment and provider
   keys. Keep credentials outside the repositories and notebooks.
3. Prepare the task and experiment in your own project. Use
   [first-run checks](first-run.md) to inspect the command and configuration.
   For an existing scientific task, follow a
   [companion tutorial](https://github.com/yuema137/siderius-exp/blob/main/tutorials/README.md).
4. Have your agent show the saved settings, command and output directory before
   the first real run. You can optionally inspect an HTML report through
   [setup review](../../src/tools/setup_review/README.md).

The [Quickstart pack](../../examples/quickstart/README.md) offers a synthetic CPU
check without provider calls. It checks installation and task contracts, not
scientific hardware or model performance.

The optional reviewed-launch route covers a fresh standard single iteration.
For your own caller, use the [external orchestration guide](../../src/tools/orchestration_setup/README.md).
Choosing that execution route is separate from choosing Professional or
Assistant collaboration. See [the documentation map](../README.md) for deeper
references.
