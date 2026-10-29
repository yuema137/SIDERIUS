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

## Your first hour: from the example to your own task

This path has two stages. Stage 1 runs a small ready-made example in the browser
console, so you see every step once. Stage 2 repeats the same steps with your
own task. Three terms matter, each nested in the one before:

- **Task**: your scientific problem as a *task package*, a folder holding the
  task manifest (`task.yaml`) and the plugins and declarations it names: data
  access, splits, model input and output, the main score and the Health checks.
- **Experiment setup**: one workflow bound to exactly one task, for example a
  research loop. A task can have several.
- **Run**: one execution of an experiment setup, with its own seed, resources
  and results.

The commands use three example paths. Replace them with your own absolute paths:
`/absolute/downloads` (where the example zip goes), `/absolute/project` (a folder
you own; the console workspace is created inside it) and
`/absolute/private/credentials.json` (your private API key file).

### Before you start

- **A Linux machine with an NVIDIA GPU and CUDA** for the run itself. Every
  step before Launch works on CPU, but a launched run without a GPU stops
  instead of training. See [installation](installation.md#prerequisites).
- **bubblewrap**, the Linux sandbox the console runs tasks in. This check must
  finish without an error message: `bwrap --unshare-all --ro-bind / / true`.
  If it fails, see
  [If the check fails](../../src/tools/workspace_sandbox/README.md#if-the-check-fails).
- **Python 3.12+ and [uv](https://docs.astral.sh/uv/)**, and an OpenAI API key
  (the standard model profile uses OpenAI models).

### Stage 1: run the example

1. **Install SIDERIUS.**

   ```bash
   git clone https://github.com/yuema137/SIDERIUS.git
   cd SIDERIUS
   uv sync --group dev --frozen
   ```

   Success: the sync ends without an error and `.venv/bin/python` exists. Run
   every later command from this folder. [Installation](installation.md) covers
   problems and the supported environment.

2. **Get the example bundle.** Download
   `siderius-example-quickstart-<version>.zip` from the
   [releases page](https://github.com/yuema137/SIDERIUS/releases) when the
   release lists it. Until then, build it from your checkout:

   ```bash
   .venv/bin/python -m tools.release.build_example_bundle --output-dir /absolute/downloads
   unzip /absolute/downloads/siderius-example-quickstart-<version>.zip -d /absolute/downloads
   ```

   Success: the build prints the zip's path, for example
   `/absolute/downloads/siderius-example-quickstart-1.0.0.zip`, and `unzip`
   creates `/absolute/downloads/siderius-example-quickstart-<version>/`. The
   bundle holds a small synthetic task package and a ready experiment setup.

3. **Create your private key file and the console workspace.** The first
   command creates an empty key file that only you can read (mode `600`; its
   folder must exist). The second creates the workspace and records that file's
   path:

   ```bash
   install -m 600 /dev/null /absolute/private/credentials.json
   .venv/bin/python -m tools.candidate_console init --workspace /absolute/project \
     --credential-file /absolute/private/credentials.json
   ```

   Success: the output starts with
   `Workspace configuration: /absolute/project/siderius_workspace/settings/console.json`,
   then prints the console address and how to connect. Now open the key file in
   your editor and write `{"OPENAI_API_KEY": "your key"}`; a run reads it only
   when you launch. `init` refuses a key file that is not yours with mode `600`
   and never prints its contents.
   [Credentials](../../src/tools/candidate_console/README.md#credentials) explains
   the file formats and what happens when `console.json` already exists.

4. **Write the example data into the workspace.**

   ```bash
   .venv/bin/python /absolute/downloads/siderius-example-quickstart-<version>/fetch_data.py \
     --workspace /absolute/project/siderius_workspace
   ```

   Success: the last line is
   `Data ready in /absolute/project/siderius_workspace/data/quickstart`. Write the
   data before the next step, because the next step ends with a check that
   needs this folder.

5. **Register the task and its experiment setup.** Pass the GPU device files
   runs may use (list yours with `ls /dev/nvidia*`):

   ```bash
   .venv/bin/python -m tools.candidate_console add-task \
     --config /absolute/project/siderius_workspace/settings/console.json \
     --from-bundle /absolute/downloads/siderius-example-quickstart-<version> \
     --device /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm
   ```

   Success: the output names the copied package
   (`siderius_workspace/tasks/quickstart`), prints the task entry it added,
   reports `Created experiment setup 'quickstart-research-loop'` and ends with
   `Restart the console to load the new task.` The
   [bundle README](../../examples/console_bundle/README.md#run-the-example)
   explains each refusal and the GPU warning you may see.

6. **Start the console** in a terminal that stays open (on a remote server, a
   `tmux` or `screen` session):

   ```bash
   .venv/bin/python -m tools.candidate_console serve \
     --config /absolute/project/siderius_workspace/settings/console.json
   ```

   Success: it prints `Console address: http://127.0.0.1:8740` and keeps
   running. To restart it later, press Ctrl+C and run the same command.

7. **Open the console.** On the same machine, open the console address in your
   browser. On a remote server, first run the `ssh -N -L ...` command that
   `serve` printed on your own computer, then open the address there. Show the
   access token with
   `cat /absolute/project/siderius_workspace/settings/console-token`, paste it on
   **Home** and select **Connect**. This token only unlocks the page; it is not
   your API key.

8. **Follow the tabs in order: Task, Workflow, Run, Monitor.** Select the
   quickstart task on **Task**, open its setup on **Workflow**, prepare, review
   and launch on **Run**, then follow the run on **Monitor** until it finishes.
   The bundle README's
   [What to do in the browser](../../examples/console_bundle/README.md#what-to-do-in-the-browser)
   describes each tab. Success: Monitor shows the run's final status and what
   each step reported. The example proves the path works end to end, not model
   quality.

### Stage 2: bring your own task

1. **Package your task with your coding agent.** Open this checkout in your
   coding agent and describe your data and question, for example: "Use SIDERIUS
   in Assistant style. Package my CSV dataset in `/data/wine` as a console task
   package in `/absolute/project/siderius_workspace/tasks/wine/`." The agent
   follows the
   [setup skill](../agent-reference/siderius-setup-review/SKILL.md) and the
   [task definition guide](../guides/define-a-task.md), and asks you to agree on
   the prediction target, splits and main score. The example's
   `siderius_workspace/tasks/quickstart/` folder is a complete package to compare
   with. Success: a folder holding `task.yaml` and the files it names.

2. **Place the package and its data in the workspace.** The package belongs in
   `siderius_workspace/tasks/<id>/` (for example `tasks/wine/task.yaml`) and the
   data in `siderius_workspace/data/<id>/`; move them there if your agent built
   them elsewhere. The folder name becomes the task ID.

3. **Register the task.**

   ```bash
   .venv/bin/python -m tools.candidate_console add-task \
     --config /absolute/project/siderius_workspace/settings/console.json \
     --manifest /absolute/project/siderius_workspace/tasks/wine/task.yaml \
     --device /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm
   ```

   Success: it prints the entry it added and ends with
   `Restart the console to load the new task.` If `check` fails, the output
   names the field or file to fix. Step 2 of
   [Set up and open the console](../../src/tools/candidate_console/README.md#set-up-and-open-the-console)
   lists the starting time limits and options.

4. **Restart the console** (Ctrl+C in its terminal, then the `serve` command
   from stage 1) and connect again.

5. **Build a workflow for it.** On **Task**, select your task and read the panel:
   it shows the splits, model input and output, main score and Health checks
   read from your package. On **Workflow**, select **New setup…**, start from
   the research-loop template, add your advice, rounds and stop conditions, and
   save a version. [Create an experiment setup and run it](../../src/tools/candidate_console/README.md#create-an-experiment-setup-and-run-it)
   walks through each control.

6. **Run it** as in stage 1: **Run**, then **Monitor**.

To change the package later, edit it with your coding agent and press
**Refresh** on **Task**. To change time limits, network access or devices,
edit the task's entry in `console.json` and restart the console.

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
to configure the training stage. Completion is not a scientific success verdict. Package
your task with your coding agent first: the browser creates experiment setups,
but it does not create or edit task packages or the console's task entries. It can also launch an
externally configured native chain for multiple iterations, using the same
backend as the CLI. Both routes are available whether you work in Professional
or Assistant mode.

The [first-hour path](#your-first-hour-from-the-example-to-your-own-task) above
sets up the console in order: `init --credential-file`, task data in
`data/<task_id>/`, `add-task`, then `serve`. The
[console setup](../../src/tools/candidate_console/README.md#set-up-and-open-the-console)
describes every option, and the
[configuration example](../../src/tools/candidate_console/console-contract.md#configuration)
lists all fields. The console access token unlocks the page, while provider keys
are read only from the configured `credential_file`; shell exports or a project
`.env` do not satisfy that console binding (see
[Credentials](../../src/tools/candidate_console/README.md#credentials)).

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

The [Quickstart pack](../../examples/quickstart/README.md) offers synthetic data
preparation and component checks that run on CPU without provider calls. They
check installation and task contracts, not scientific hardware or model
performance. A real run, including a Quickstart research chain, needs an NVIDIA
GPU with CUDA; the chain header and the console run review say so, and a launch
on a machine without one stops before any model call.

The optional reviewed-launch route covers a fresh standard single iteration.
For your own caller, use the [external orchestration guide](../../src/tools/orchestration_setup/README.md).
Choosing that execution route is separate from choosing Professional or
Assistant collaboration. See [the documentation map](../README.md) for deeper
references.
