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
[API-key procedure](installation.md#api-keys). The browser console instead
reads the `credential_file` named in its configuration. Have your agent show the saved settings, command
and output directory before execution. An optional
[setup review](../../src/tools/setup_review/README.md) produces an HTML report.

Optionally, [capture a native chain](../../src/tools/native_chain/README.md)
to record the settings for a fresh foreground multi-iteration CLI run before
explicitly launching it. The original declaration and configuration files remain
authoritative; capture does not certify scientific success. Follow the linked
guide for prerequisites and path requirements.

## Open the optional workflow console

The browser console can prepare, review and launch a saved workflow, from **one
candidate: Propose → Implement → Validate** up to an interpreted training workflow
(Interpret → Propose → Implement → Validate → Train & Tune) repeated as a research
loop. Use the [training inspector guide](../../src/tools/candidate_console/README.md#edit-reusable-training-settings)
to configure the training stage. Completion is not a scientific success verdict. Create the
external project with your coding agent first: the browser does not create
projects or edit the console's task configuration. It can also launch an
externally configured native chain for multiple iterations, using the same
backend as the CLI. Both routes are available whether you work in Professional
or Assistant mode.

Follow the [console setup](../../src/tools/candidate_console/README.md) in order:
check the Linux sandbox, run `init` to create the console workspace and its
access token, add your task's manifest, LLM profile and resource policy to the
created `console.json`, place task data in `data/<task_id>/`, create a private
provider-key file, then run `check` and `serve`. The
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
- **Saved reusable workflow:** in Workflow Editor, save your changes and select
  **Next: Run**. On the Run page, use **New run** to select the
  configured task/resources, review and prepare the saved source. Open the
  prepared run, review it and explicitly launch. Each run has separate captured
  inputs and a workspace; later edits affect future runs. For a research loop,
  Monitor shows each iteration's training results and can stop or pause the
  loop after a completed iteration; a paused loop can be resumed later.
- **Configured native chain:** have your coding agent prepare a capture and
  add it to the console configuration using the
  [native-chain instructions](../../src/tools/candidate_console/README.md#run-a-configured-native-chain).
  On Home, select it, review the run destination and execution policy, then
  explicitly launch. Check the original capture for the full scientific
  settings; this panel does not edit the chain or provide pause/resume (a saved
  workflow's research loop can be paused instead).

To bind a reusable workflow in **Workflow builder**:

1. Choose a configured task package/version and **Update workflow references**.
2. Press **Save**, inspect the task findings (and, with advanced tools on, the Python diff), confirm them and **Save version**.
3. Select **Next: Run**, prepare on the Run page, review its captured inputs, then explicitly launch.

Save pending edits before Update.
An unbound workflow needs an explicit current-snapshot adoption confirmation.
Bound edits need their matching configured choice for review. Professional and
Assistant modes share this flow; see the [task-version guide](../../src/tools/candidate_console/README.md#bind-a-task-version).

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
