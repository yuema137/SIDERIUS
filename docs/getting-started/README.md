# Get started with your coding agent

This page takes you from an installed checkout to a finished SIDERIUS run and
its result. SIDERIUS 1.1 has two main ways of working, and both use a coding
agent (for example Claude Code or Codex) opened in this checkout:

- **Professional**: you lead the research plan. The agent reads the contracts,
  writes the files you ask for and checks the setup.
- **Assistant**: you describe your problem and data in one sentence. The agent
  follows the [setup skill](../agent-reference/siderius-setup-review/SKILL.md)
  and guides you through each choice. For example: "I have MNIST images and
  labels in `/data/mnist`; help me build and evaluate a digit classifier."

Both produce the same files in a project folder you own, and both run them with
the same command-line tools. These names do not select a CLI flag or force a
review. Writing the files by hand is also supported. The files are:

- a **task package** (`task.yaml` and its plugins): your data, splits, model
  input and output, main score and Health checks;
- a **workflow declaration** (`workflow.py`): which research steps run, how
  results pass between them, your advice, budgets and loop settings. SIDERIUS
  reads this file without running it as a program; see
  [how a workflow.py is built](../../examples/workflow_declarations/README.md#how-a-workflowpy-is-built);
- an **LLM profile** (`llm.json`): which model serves each role;
- a **preparation request** (`reusable-request.json`): the settings of one run.

This page follows the **workflow** route, where `workflow.py` fixes the path in
advance. To let your coding agent choose each research step at run time
instead, see [workflow or orchestration](../../README.md#choose-the-execution-workflow-or-orchestration).

A browser console is also included. It is **experimental** in this release:
see [Try the browser console (experimental)](#try-the-browser-console-experimental).

## Prepare your project

1. Follow [installation](installation.md): use Python 3.12+ (this checkout pins
   3.12) and uv, run
   `uv sync --group dev --frozen` in this checkout, and use its `.venv/bin/python`.
2. Open the checkout in your coding agent. Describe your research question,
   dataset location and an external project directory. You do not need a
   prepared manifest. Agree on the prediction target, splits, score and budgets;
   the agent creates your [task package](../concepts/task-package.md) and
   experiment files there. For an existing scientific task, start from a
   [companion tutorial](https://github.com/yuema137/siderius-exp/blob/main/tutorials/README.md).
3. Save a reviewed [LLM profile](../../configs/llm/README.md) in your project as
   `llm.json`. This JSON file selects the experiment's providers and models by
   role; your coding agent's own model is a separate choice. Supply only
   credentials required by those selected routes, using the launch route below.

For example, keep task inputs, the workflow and run outputs in your external
project. These are example names, not a layout the tools require:

```text
/absolute/project/                 # outside the SIDERIUS checkout
  task.yaml                        # task manifest (named by manifest= in workflow.py)
  task_plugins/                    # dataset/model/metric implementations
  data/                            # dataset (named by data_root= in workflow.py)
  workflow.py                      # workflow declaration: steps, advice, budgets, loop
  llm.json                         # saved provider/model profile
  reusable-request.json            # preparation request for one run
  store.json                       # where launched operations keep their records
/absolute/runs/                    # create it first; one folder per prepared run
/absolute/operations/              # operation records; created by the first submit
```

The task manifest defines the science; `workflow.py` defines the experiment.
Keep private key files outside version control, for example in a separate
machine-owned directory.

## Write and run a workflow declaration

This is the recommended route for your own research runs. Your coding agent
can do each step for you; the commands below are what it runs, so you can
check them. You need Linux with bubblewrap, this checkout's `.venv/bin/python`,
a task package and an NVIDIA GPU with CUDA for the training step.

### 1. Start `workflow.py` from an example

Copy one file from
[`examples/workflow_declarations/`](../../examples/workflow_declarations/README.md)
into your project as `workflow.py`:

- [`reusable_training.py`](../../examples/workflow_declarations/reusable_training.py)
  runs Propose → Implement → Validate → Train & tune once;
- [`research_loop_request_input.py`](../../examples/workflow_declarations/research_loop_request_input.py)
  runs Interpret → Propose → Implement → Validate → Train & tune as a research
  loop of up to three iterations, with a stop condition;
- [`managed_reusable_candidate.py`](../../examples/workflow_declarations/managed_reusable_candidate.py)
  stops after validation, without training.

Point its `ReusableTaskReferences(manifest=..., data_root=...)` at your task
package and data (relative paths resolve against the `project_root` you choose
in step 2, normally your project folder) and set the advice and training
settings you want. [How a workflow.py is built](../../examples/workflow_declarations/README.md#how-a-workflowpy-is-built)
explains each part. To check the file offline, without running anything:

```bash
.venv/bin/python -m workflows.definition to-json --input /absolute/project/workflow.py
```

Success: it prints the declaration as JSON and exits 0. A mistake prints a
diagnostic naming the line or field, and exits 2.

### 2. Save the preparation request

Your agent writes `/absolute/project/reusable-request.json` with the
[request recipe](../../src/tools/candidate_prepare/candidate-prepare-contract.md#reusable-request-recipe).
It records, for one run:

- `source_path`, `project_root` and `expected_source_sha256`: which
  `workflow.py` to run, and its exact content (preparation refuses a file that
  changed after the request was written);
- `llm_config_file`: your `llm.json` (required: there is no implicit profile on
  this route);
- `runs_root`, `run_id` and `run_name`: the folder that receives one new
  subfolder per run, a fresh UUID for this run and a readable name;
- `preparation_timeout_seconds` and `candidate_timeout_seconds`: time limits
  for preparation and for the run;
- `task_read_only`: folders the run may read (your task package and data);
- `candidate_network`: whether the run may use the network (provider calls
  need it);
- `candidate_devices`: the GPU device paths the run may use, for example
  `/dev/nvidia0`. Leave it empty only for a workflow without training: a run
  that trains a model without a GPU is refused;
- `candidate_environment_names`: the *names* of the provider key variables,
  never the key values.

For example:

```json
{
  "source_path": "/absolute/project/workflow.py",
  "project_root": "/absolute/project",
  "expected_source_sha256": "<SHA-256 of workflow.py, computed by the recipe>",
  "runs_root": "/absolute/runs",
  "run_id": "3f2b6c1e-8d4a-4e2f-9b7c-5a1d0e6f4c21",
  "run_name": "first_run",
  "llm_config_file": "/absolute/project/llm.json",
  "preparation_timeout_seconds": 600.0,
  "candidate_timeout_seconds": 7200.0,
  "task_read_only": ["/absolute/project"],
  "candidate_network": true,
  "candidate_devices": ["/dev/nvidia0"],
  "candidate_environment_names": ["OPENAI_API_KEY"]
}
```

The runs folder (`/absolute/runs` above) must already exist, outside your task
and data folders. You will list it in `store.json` in step 4.

### 3. Prepare the run

This step is offline: no model is called and nothing is trained.

```bash
.venv/bin/python -m tools.candidate_prepare \
  --reusable-request /absolute/project/reusable-request.json
```

Success: exit status 0, and the printed JSON receipt includes
`"status": "prepared"` and `"envelope": "/absolute/runs/<run_id>"`. That
envelope is the new run folder. This **preparation receipt** is saved as
`/absolute/runs/<run_id>/receipt.json`, and `workflow.py.snapshot` beside it is the exact workflow that
will run; later edits to `workflow.py` only affect future runs. A request that
cannot be prepared exits non-zero, and the error (or the receipt's `error`
field) names the problem.

### 4. Launch it

First save `store.json`. It tells the operations tool where prepared runs may
live and where to keep its own records:

```json
{
  "state_root": "/absolute/operations",
  "preparation_roots": ["/absolute/runs"],
  "candidate_roots": ["/absolute/runs"]
}
```

For `state_root`, name a separate folder that does not exist yet (its parent
must). The first submit creates it with private permissions, and later submits
reuse it. Do not create it yourself.
Then your agent turns the prepared run folder into a launch request,
`reusable-submission.json`, with the short Python
[operation recipe](../../src/tools/candidate_operations/candidate-operations-contract.md#shared-python-and-cli-recipe):

```python
from pathlib import Path
from uuid import uuid4

from tools.candidate_operations import OperationStoreConfig, build_reusable_operation
from tools.candidate_prepare import select_reusable_preparation

config = OperationStoreConfig.model_validate_json(Path("/absolute/project/store.json").read_bytes())
selection = select_reusable_preparation("/absolute/runs/<run_id>")
submission = build_reusable_operation(config, selection, uuid4())
Path("/absolute/project/reusable-submission.json").write_text(submission.model_dump_json(indent=2))
```

Read the task, workflow steps, models, time limits and advice in that file
before you continue. Then make your provider keys available in this shell (see
[API keys](installation.md#api-keys)) and submit. This step calls paid APIs and
uses the GPU:

```bash
.venv/bin/python -m tools.candidate_operations submit \
  --store-config /absolute/project/store.json \
  --request /absolute/project/reusable-submission.json
```

Save the `operation_id` it prints. Exit status 0 means the run was admitted,
not that it succeeded. If the response is lost, submit the same file again: you
get the same operation back, not a second run.

### 5. Follow it

Read the state and the log with the operation ID:

```bash
.venv/bin/python -m tools.candidate_operations status \
  --store-config /absolute/project/store.json --operation-id OPERATION_UUID
.venv/bin/python -m tools.candidate_operations log \
  --store-config /absolute/project/store.json --operation-id OPERATION_UUID \
  --kind native --offset 0 --limit 65536
```

`status` prints JSON whose `state` moves from `active` to `completed` (or
`operation_failed`); `queued` means it is waiting for room in a shared GPU
budget. [Read status and logs](../../src/tools/candidate_operations/README.md#read-status-and-logs)
explains each value.

For a research loop, `stop-loop` and `pause-loop` act at the next iteration
boundary. To resume a paused loop, `write-loop-resume --output resume.json`
(with an optional `--advice-file`) writes a resume request, which you then
`submit`; see
[Stop, pause or resume a research loop](../../src/tools/candidate_operations/README.md#stop-pause-or-resume-a-research-loop).

### 6. Read the result

A finished run is a record, not a verdict. Read it in three layers:

1. **Did the run finish?** In the `status` output, `state` is `completed` and
   the **run receipt** (the `receipt` in the `status` output, saved as
   `/absolute/runs/<run_id>/workspace/candidate_run/receipt.json`) has a
   `status` that says what the run reported: `completed` (training
   returned), `stopped` or `paused` (a research loop), `accepted` or
   `rejected` (a workflow without training), `cancelled` (stopped at once
   with `cancel`), or `failed` / `timed_out` / `interrupted` (read the native
   log). For a research loop, its `loop_trace` lists each iteration and why
   the loop stopped or paused.
2. **What score did training reach, and did Health pass?** Each training step
   saves its report as a file named `run_output_<run_name>.json` inside the run
   folder: one per iteration for a research loop. List them with

   ```bash
   find /absolute/runs/<run_id>/workspace -name 'run_output_*.json'
   ```

   (For a single pass, the run receipt's `native_output_paths` also lists
   every step's record.) The number to compare is
   `best_valid_formal_denoising_score`: the best main-score value among Formal
   results that passed Health (`null` means no Formal result passed Health, or
   none ran). The supporting fields are:
   - `all_records` lists every training attempt with its `status`, score,
     `health_gate_results` (each Health check's outcome) and, on Formal
     records, `scientific_authority` (whether that result may count, and if
     not, `blocking_reasons`);
   - `termination_reason` says why training stopped.

   Fields such as `best_denoising_score` and `best_formal_denoising_score`
   include results that failed Health; treat them as progress reports. (The
   `denoising_score` field names are historical: they hold your task's main
   score, whatever the metric.)
3. **Does the result count scientifically?** Only when `workflow.py` declares
   `training_settings["launch"]["healthgate_mode"] = "blocking"` and
   `"result_authority": "scientific"`, the score could be computed, and every
   **Blocking** Health check passed. On a Formal record,
   `scientific_authority.authoritative` is `true` only when all of this holds;
   otherwise `blocking_reasons` says why (`declared_diagnostic`,
   `non_blocking_mode`, `gate_invalidated`, ...). A run declared `diagnostic`
   (as the training examples are) reports scores for exploration only. A
   failing **Recording** check is stored but does not invalidate the model.

In the browser console, open the run on **Monitor**. When a workflow run has
finished, **Workflow training results** shows each iteration's training report
separately, including **Best valid formal score**, and **Train & tune outcome**
says what training achieved.

## Launch a native chain from the CLI

The older chain launcher `scripts/launch/run_chain.sh` remains supported. The
[companion tutorials](https://github.com/yuema137/siderius-exp/blob/main/tutorials/README.md)
and paper tasks use it through saved launch scripts. For this route, use
[first-run checks](first-run.md) and your external project's saved launch
script. Have your agent show the saved settings, command and output directory
before execution. An optional
[setup review](../../src/tools/setup_review/README.md) produces an HTML report.

This route reads credentials from the launch process: use a trusted external
shell-compatible credential file or managed injection, with the name-only check
in the [API-key procedure](installation.md#api-keys).

Optionally, [capture a native chain](../../src/tools/native_chain/README.md)
to record the settings for a fresh foreground multi-iteration CLI run before
explicitly launching it. The original declaration and configuration files remain
authoritative; capture does not certify scientific success. Follow the linked
guide for prerequisites and path requirements.

## Check your installation and other routes

The [Quickstart pack](../../examples/quickstart/README.md) offers synthetic data
preparation and component checks that run on CPU without provider calls. They
check installation and task contracts, not scientific hardware or model
performance. Its [tutorial notebook](../../examples/quickstart/quickstart.ipynb)
walks through the task package, a workflow and its preparation offline. A real
run that trains, including a Quickstart research loop, needs an NVIDIA GPU with
CUDA; on a machine without one it is refused before any model call.

To let your coding agent choose the research steps at run time instead of a
fixed `workflow.py`, use the [external orchestration guide](../../src/tools/orchestration_setup/README.md).
Choosing that execution route is separate from choosing Professional or
Assistant collaboration. See [the documentation map](../README.md) for deeper
references.

## Try the browser console (experimental)

The browser console is **experimental** in SIDERIUS 1.1: its pages and
settings may change between releases, and it does not show every workflow
feature (for example, literature-review aggregation is not drawn). Use it to
see the steps once on a small example, or to view and run a `workflow.py` your
agent wrote; the file stays the authority for what runs. Packaging a task still
happens with your coding agent.

### Your first hour: from the example to your own task

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

#### Before you start

- **A Linux machine with an NVIDIA GPU and CUDA** for the run itself. Every
  step before Launch works on CPU, but a launched run that trains is refused
  without a GPU. See [installation](installation.md#prerequisites).
- **bubblewrap**, the Linux sandbox the console runs tasks in. Run the one-line
  [bubblewrap check](../../src/tools/workspace_sandbox/README.md#check-that-bubblewrap-works)
  once on this machine.
- **Python 3.12+ and [uv](https://docs.astral.sh/uv/)**, and an OpenAI API key
  (the standard model profile uses OpenAI models).

#### Stage 1: run the example

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
   mkdir -p /absolute/downloads
   .venv/bin/python -m tools.release.build_example_bundle --output-dir /absolute/downloads
   unzip /absolute/downloads/siderius-example-quickstart-<version>.zip -d /absolute/downloads
   ```

   Success: the build prints the zip's path, for example
   `/absolute/downloads/siderius-example-quickstart-1.0.0.zip`, and `unzip`
   creates `/absolute/downloads/siderius-example-quickstart-<version>/`. The
   bundle holds a small synthetic task package and a ready experiment setup.
   The number in the name is the package version from `pyproject.toml`; it may
   differ from the release name.

3. **Create your private key file and the console workspace.** The first
   command creates an empty key file that only you can read (mode `600`; its
   folder must exist); skip it if the file already exists. The second creates
   the workspace and records that file's path:

   ```bash
   (umask 077 && touch /absolute/private/credentials.json)
   .venv/bin/python -m tools.candidate_console init --workspace /absolute/project \
     --credential-file /absolute/private/credentials.json
   ```

   Success: the output starts with
   `Workspace configuration: /absolute/project/siderius_workspace/settings/console.json`,
   then prints the console address and how to connect. Now open the key file in
   your editor and write `{"OPENAI_API_KEY": "your key"}`; a run reads it only
   when you launch. `init` refuses the key file unless it is a regular file you
   own with mode `600`, and never prints its contents.
   [Credentials](../../src/tools/candidate_console/README.md#credentials) explains
   the file formats and what happens when `console.json` already exists.
   The workspace's parent folder (`/absolute/project` above) must be owned by you
   and not writable by group or others, or `init` refuses it. For a folder meant
   only for you, use `chmod 700 /absolute/project`. On a shared HPC filesystem,
   keep collaborators' access to the shared folder: create a private subfolder
   with `mkdir -m 700 /absolute/project/siderius`, then rerun `init` with
   `--workspace /absolute/project/siderius` and use
   `/absolute/project/siderius/siderius_workspace` in the steps below.

4. **Write the example data into the workspace.**

   ```bash
   .venv/bin/python /absolute/downloads/siderius-example-quickstart-<version>/fetch_data.py \
     --workspace /absolute/project/siderius_workspace
   ```

   Success: the last line is
   `Data ready in /absolute/project/siderius_workspace/data/quickstart`. Write the
   data before the next step, because the next step ends with a check that
   needs this folder.

5. **Register the task and its experiment setup.**
   `add-task` finds this machine's NVIDIA GPUs (`/dev/nvidia<N>`) and passes
   them to runs. On a machine without one it passes none: you can still
   register, prepare and check the task, but a run that trains is refused
   (SIDERIUS 1.1 has no CPU mode). `--no-gpu` withholds the GPU even when one
   exists, for a workflow that stops before training:

   ```bash
   .venv/bin/python -m tools.candidate_console add-task \
     --config /absolute/project/siderius_workspace/settings/console.json \
     --from-bundle /absolute/downloads/siderius-example-quickstart-<version>
   ```

   Success: the output names the copied package
   (`siderius_workspace/tasks/quickstart`), prints `candidate_devices: /dev/nvidia0
   (NVIDIA GPU found on this machine; ...)` and the task entry it added,
   reports `Created experiment setup 'quickstart-research-loop'` and ends with
   `Restart the console to load the new task.` The
   [bundle README](../../examples/console_bundle/README.md#run-the-example)
   explains each refusal.

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
   `cat /absolute/project/siderius_workspace/settings/console-token`, paste it
   into **Console token** at the top of the page and select **Connect**. This
   token only unlocks the page; it is not your API key.

8. **Follow the tabs in order: Task, Workflow, Run, Monitor.** Select the
   quickstart task on **Task**, open its setup on **Workflow**, prepare, review
   and launch on **Run**, then follow the run on **Monitor** until it finishes.
   The bundle README's
   [What to do in the browser](../../examples/console_bundle/README.md#what-to-do-in-the-browser)
   describes each tab. Success: Monitor shows the run's final status and what
   each step reported; [Read the result](#6-read-the-result) explains the
   training results. The example proves the path works end to end, not model
   quality.

#### Stage 2: bring your own task

1. **Package your task with your coding agent.** Open this checkout in your
   coding agent and describe your data and question, for example: "Use SIDERIUS
   in Assistant style. Package my CSV dataset in `/data/wine` as a console task
   package in `/absolute/project/siderius_workspace/tasks/wine/`." The agent
   follows the
   [setup skill](../agent-reference/siderius-setup-review/SKILL.md) and the
   [task definition guide](../guides/define-a-task.md), and asks you to agree on
   the prediction target, splits and main score. For a classification dataset
   in CSV files, the agent starts from the
   [CSV classification template](../../examples/task_templates/csv_classification/README.md),
   which you can also copy and edit yourself; its README lists every line to
   change. Success: a folder holding `task.yaml` and the files it names.

2. **Place the package and its data in the workspace.** The package belongs in
   `siderius_workspace/tasks/<id>/` (for example `tasks/wine/task.yaml`) and the
   data in `siderius_workspace/data/<id>/`; move them there if your agent built
   them elsewhere. The folder name becomes the task ID.

3. **Register the task.**

   ```bash
   .venv/bin/python -m tools.candidate_console add-task \
     --config /absolute/project/siderius_workspace/settings/console.json \
     --manifest /absolute/project/siderius_workspace/tasks/wine/task.yaml
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
   the research-loop template, add your advice, tuning rounds per iteration and stop conditions, and
   save a version. [Create an experiment setup and run it](../../src/tools/candidate_console/README.md#create-an-experiment-setup-and-run-it)
   walks through each control.

6. **Run it** as in stage 1: **Run**, then **Monitor**.

To change the package later, edit it with your coding agent and press
**Refresh** on **Task**. To change time limits, network access or devices,
edit the task's entry in `console.json` and restart the console.

### Other console routes

The browser console can prepare, review and launch a saved workflow, from **one
candidate model** (Propose → Implement → Validate) up to an interpreted training workflow
(Interpret → Propose → Implement → Validate → Train & tune) repeated as a research
loop. Use the [training inspector guide](../../src/tools/candidate_console/README.md#edit-reusable-training-settings)
to configure the training stage. Completion is not a scientific success verdict.
Package your task with your coding agent first: the browser creates experiment
setups, but it does not create or edit task packages or the console's task
entries. It can also launch an
externally configured native chain for multiple iterations, using the same
backend as the CLI. Both routes work the same whichever way of working
(Professional or Assistant) you chose.

Set up the console with the
[first-hour path](#your-first-hour-from-the-example-to-your-own-task) above
(`init --credential-file`, task data in `data/<task_id>/`, `add-task`, then
`serve`). The
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
  **Launch candidate**. This route is independent of edits on the **Workflow** tab.
- **Saved reusable workflow:** on the **Workflow** tab, save your changes and select
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

To bind a reusable workflow on the **Workflow** tab:

1. Choose a configured task package/version and **Update workflow references**.
2. Press **Save**, inspect the task findings (and, with advanced tools on, the Python diff), confirm them and **Save version**.
3. Select **Next: Run**, prepare on the Run page, review its captured inputs, then explicitly launch.

Save pending edits before Update.
An unbound workflow needs an explicit current-snapshot adoption confirmation.
Bound edits need their matching configured choice for review. This flow is the
same for Professional and Assistant work; see the [task-version guide](../../src/tools/candidate_console/README.md#bind-a-task-version).

Follow the [saved-source recipe](../../src/tools/candidate_console/README.md#prepare-saved-source-or-open-an-existing-run)
for the second route. Saving and preparation never launch automatically.
Launching runs code and may make paid calls. Configuration checks and offline
preparation do not prove provider access or candidate success. Keep the
operation ID to reopen status and logs without selecting an editor project.
