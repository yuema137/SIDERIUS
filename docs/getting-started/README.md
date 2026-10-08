# Get started with your coding agent

We recommend preparing your task and experiment with a coding agent. In
**Assistant** mode, describe your problem and data in one sentence; the agent
follows the [setup skill](../agent-reference/siderius-setup-review/SKILL.md)
and guides you from environment setup to saved task and experiment files.
For example: "I have MNIST images and labels in `/data/mnist`; help me build and
evaluate a digit classifier." In **Professional** mode, you lead
the choices and use your agent to read contracts, edit files and check the setup.
Both use the same framework; these names do not select a CLI flag or force a
review. Handwritten setup is supported, but is not the recommended first route.

1. Open the repository in your coding agent and describe your task and data
   location. You do not need a prepared manifest or project layout.
2. Let the agent follow [installation](installation.md), check the environment
   and explain the provider keys you need to supply. Keep credentials outside
   the repositories and notebooks.
3. Agree on the prediction target, data splits, score and experiment budgets.
   The agent creates the task and experiment in an external project and uses
   [first-run checks](first-run.md) to inspect its saved command and configuration.
   For an existing scientific task, it can start from a
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
