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

## Prepare your project

1. Follow [installation](installation.md): use Python 3.12+ (this checkout pins
   3.12) and uv, run
   `uv sync --group dev --frozen` in this checkout, and use its `.venv/bin/python`.
2. Open the checkout in your coding agent. Describe your research question,
   dataset location and an external project directory. You do not need a
   prepared manifest. Agree on the prediction target, splits, score and budgets;
   the agent creates your [task package](../reference/task-composition.md) and
   experiment files there. For an existing scientific task, start from a
   [companion tutorial](https://github.com/yuema137/siderius-exp/blob/main/tutorials/README.md).
3. Save a reviewed [LLM profile](../../configs/llm/README.md) in your project.
   This JSON file selects the experiment's providers and models by role;
   your coding agent's own model is a separate choice. Supply only credentials
   required by those selected routes, using the launch route below.

For example, keep task inputs and run outputs in your external project. These
are example names; the browser does not generate this layout:

```text
/absolute/project/                 # outside the SIDERIUS checkout
  task.yaml                        # task manifest; references your task plugins
  task_plugins/                    # dataset/model/metric implementations
  data/                            # existing dataset, or configure another external root
  llm.json                         # saved provider/model profile
  scripts/                         # reviewed experiment launch scripts
  workspaces/                      # scientific run outputs
  console.json                     # optional console paths, resources and time limits
  preparations/                    # console only: create this output parent
  candidates/                      # console only: create this separate output parent
  operation-state/                 # console only: configured operation records
```

The task manifest defines the science; `console.json` connects those existing
inputs to the console. The console creates fresh per-operation directories
inside `preparations/` and `candidates/`; do not create those child workspaces
yourself. Keep private token/key files outside version control, for example in
a separate machine-owned directory.

## Launch a research workflow from the CLI

For training and scientific scores, use [first-run checks](first-run.md) and
your external project's saved launch script. This route reads credentials from
the launch process: use a trusted external shell-compatible credential file or
managed injection, with the name-only check in the
[API-key procedure](installation.md#api-keys). The console's JSON credential
file is a different format. Have your agent show the saved settings, command
and output directory before execution. An optional
[setup review](../../src/tools/setup_review/README.md) produces an HTML report.

## Open the optional candidate console

The browser console prepares, reviews and launches **one candidate:
Propose → Implement → Validate**. It does not train or score models. Create the
external project with your coding agent first: the browser does not create
projects or edit the console's task configuration.

Follow the [console setup](../../src/tools/candidate_console/README.md) in order:
check the Linux sandbox, configure existing task/data/profile paths and output
parents, create private token/key files, then run `check` and `serve`. The
[configuration example](../../src/tools/candidate_console/console-contract.md#configuration)
lists all fields. The [credential instructions](../../src/tools/candidate_console/README.md#credentials)
show the required JSON format: the console access token unlocks the page, while
provider keys are read from its configured private file. Shell exports or a
project `.env` do not satisfy that console binding.

Open the printed address, enter the token and connect. Choose the route that
matches your starting point:

- **Configured task:** on Home, expand **Prepare configured task**, select the
  task and prepare its inputs. Review models and resources, then explicitly
  **Launch candidate**. This route is independent of Workflow Editor edits.
- **Saved reusable workflow:** in Workflow Editor, save your changes and use
  **New run** to select the configured task/resources, review and prepare the
  saved source. Open the prepared run, review it and explicitly launch. Each run
  has separate captured inputs and a workspace; later edits affect future runs.

Follow the [saved-source recipe](../../src/tools/candidate_console/README.md#prepare-saved-source-or-open-an-existing-run)
for the second route. Saving and preparation never launch automatically.
Launching runs code and may make paid calls. Configuration checks and offline
preparation do not prove provider access or candidate success. Keep the
operation ID to reopen status and logs without selecting an editor project.

The [Quickstart pack](../../examples/quickstart/README.md) offers a synthetic CPU
check without provider calls. It checks installation and task contracts, not
scientific hardware or model performance.

The optional reviewed-launch route covers a fresh standard single iteration.
For your own caller, use the [external orchestration guide](../../src/tools/orchestration_setup/README.md).
Choosing that execution route is separate from choosing Professional or
Assistant collaboration. See [the documentation map](../README.md) for deeper
references.
