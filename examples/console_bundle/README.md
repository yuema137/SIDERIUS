# SIDERIUS example bundle: quickstart

This bundle gives you a small ready-made task and a ready experiment setup, so
you can run SIDERIUS once from the browser console and see each step (Task,
Workflow, Run and Monitor) before you bring your own task. The task is
synthetic: it classifies 256 seeded four-feature rows into two classes. It
demonstrates the workflow, not scientific quality.

## Before you start

- **A run needs an NVIDIA GPU with CUDA on Linux.** Writing the data, importing
  the task and reviewing a run all work on CPU, but training does not: without
  a GPU passed to runs, a launched run stops instead of training.
- A SIDERIUS checkout installed with `uv sync --group dev --frozen`
  ([installation](https://github.com/yuema137/SIDERIUS/blob/master/docs/getting-started/installation.md)).
  Run every command below from that checkout's root folder; they use its
  `.venv/bin/python`.
- A working run sandbox
  ([workspace sandbox](https://github.com/yuema137/SIDERIUS/blob/master/src/tools/workspace_sandbox/README.md)).
- An API key for the model provider. The standard model profile uses OpenAI,
  so runs need `OPENAI_API_KEY`. No command below reads or prints the key;
  only a launched run receives it.
- The zip, `siderius-example-quickstart-<version>.zip`. Download it from the
  [SIDERIUS releases page](https://github.com/yuema137/SIDERIUS/releases) when
  the release lists it. Until then, build it from your checkout with the
  command in [Building this bundle](#building-this-bundle-maintainers); it
  prints the path of the zip it wrote.

The examples use `/absolute/downloads` for the folder holding the downloaded
zip, `/absolute/project` for a folder you own where the console workspace
will live, and `/absolute/private/credentials.json` for your private key file.
Replace them with your own absolute paths, and replace `<version>` with the
version in the zip's name.

## What the bundle contains

| Path | What it is |
| --- | --- |
| `task/` | The task package: `task.yaml` (the task composition manifest), `declared/` (dataset, metric and task declarations) and `plugins/` (data access, metric and the reference model). Every path in `task.yaml` is relative to `task/`. |
| `setup/setup.json` | The first experiment setup to create: the `single-loop-with-advice` workflow template and its label. It names a template; it holds no workflow code. |
| `fetch_data.py` | Writes the task's data into your workspace. The data is generated from a fixed seed and checked against `task/declared/data_manifest.json`, so nothing is downloaded. |
| `console-task.json` | The task ID (`quickstart`) and label the import uses, and for reference the starting time limits and network setting it writes. |
| `SHA256SUMS` | The SHA-256 of every other file. The import checks it. |

## Run the example

1. Unpack the bundle:

   ```bash
   unzip /absolute/downloads/siderius-example-quickstart-<version>.zip -d /absolute/downloads
   ```

   This creates `/absolute/downloads/siderius-example-quickstart-<version>/`.
   To check the download yourself, run `sha256sum -c SHA256SUMS` inside it;
   every line should end in `OK`. Step 4 makes the same check.

2. Create your private key file and the console workspace. The first command
   creates an empty key file that only you can read (mode `600`; its folder must
   exist). The second creates the workspace and records that file's path:

   ```bash
   install -m 600 /dev/null /absolute/private/credentials.json
   .venv/bin/python -m tools.candidate_console init --workspace /absolute/project \
     --credential-file /absolute/private/credentials.json
   ```

   `init` creates `/absolute/project/siderius_workspace/` and prints
   `Workspace configuration: /absolute/project/siderius_workspace/settings/console.json`.
   It refuses a key file that is not yours with mode `600`, never prints its
   contents, and records its path as `credential_file` in the new
   `console.json`. If `console.json` already exists, `init` leaves it unchanged
   and prints the one `"credential_file": ...` line to add yourself. Now open
   the key file in your editor and write `{"OPENAI_API_KEY": "your key"}`; a run
   reads it only when you launch. The
   [console guide](https://github.com/yuema137/SIDERIUS/blob/master/src/tools/candidate_console/README.md#set-up-and-open-the-console)
   lists the folders `init` creates, and its
   [Credentials section](https://github.com/yuema137/SIDERIUS/blob/master/src/tools/candidate_console/README.md#credentials)
   shows the dotenv format you may use instead.

3. Write the task data into the workspace:

   ```bash
   .venv/bin/python /absolute/downloads/siderius-example-quickstart-<version>/fetch_data.py \
     --workspace /absolute/project/siderius_workspace
   ```

   It writes four CSV files to `siderius_workspace/data/quickstart/`, readable
   only by you, and ends with `Data ready in .../data/quickstart`. It refuses a
   workspace or data folder that is a symlink, belongs to another user, or that
   your group or others can write to. Running it again keeps identical files and
   never overwrites a different one.

   Write the data before step 4. Step 4 ends by running `check`, and `check`
   fails while `data/quickstart/` is missing. If you ran step 4 first and it
   reported that check failed, the task is already added, so do not import it
   again: run this step, then `.venv/bin/python -m tools.candidate_console check
   --config /absolute/project/siderius_workspace/settings/console.json`. If you
   import with `--task-id NAME` in step 4, run this step with the same
   `--task-id NAME`, because the data folder is then `data/NAME/`.

4. Import the task and its experiment setup. Pass the GPU device files that runs
   may use (these are the usual ones; list yours with `ls /dev/nvidia*`):

   ```bash
   .venv/bin/python -m tools.candidate_console add-task \
     --config /absolute/project/siderius_workspace/settings/console.json \
     --from-bundle /absolute/downloads/siderius-example-quickstart-<version> \
     --device /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm
   ```

   The command checks every file against `SHA256SUMS`, copies `task/` to
   `siderius_workspace/tasks/quickstart/`, adds the task to `console.json` and
   creates the experiment setup from the template. Success looks like this:

   ```text
   Copied the verified task package to /absolute/project/siderius_workspace/tasks/quickstart
   Added task quickstart to /absolute/project/siderius_workspace/settings/console.json:
   ...
   Created experiment setup 'quickstart-research-loop' (Quickstart research loop) from template single-loop-with-advice in /absolute/project/siderius_workspace/projects/quickstart-research-loop
   ...
   Restart the console to load the new task.
   ```

   If the output also warns `GPU devices are passed but /sys is not mounted
   read-only`, read **GPU runs** in the
   [console guide](https://github.com/yuema137/SIDERIUS/blob/master/src/tools/candidate_console/README.md#set-up-and-open-the-console)
   before your first run.

   A file that does not match `SHA256SUMS` stops the command before anything
   is copied: unpack the zip again. An existing `tasks/quickstart/` folder is
   never overwritten; pass `--task-id` with another name instead, and write the
   data again with that name (step 3). To change the
   starting time limits or network access, add the `add-task` options the
   [console guide](https://github.com/yuema137/SIDERIUS/blob/master/src/tools/candidate_console/README.md#set-up-and-open-the-console)
   describes, or edit the task's entry in `console.json` afterwards.

5. Start the console in a terminal that stays open (on a remote server, a
   `tmux` or `screen` session):

   ```bash
   .venv/bin/python -m tools.candidate_console serve \
     --config /absolute/project/siderius_workspace/settings/console.json
   ```

   It prints the console address (`http://127.0.0.1:8740`) and keeps running.
   On a remote server, it also prints the `ssh -N -L ...` command to run on
   your own computer.

6. In another terminal, show the access token the console asks for:

   ```bash
   cat /absolute/project/siderius_workspace/settings/console-token
   ```

   Open the console address in your browser and paste the token.

## What to do in the browser

1. **Task**: select *Quickstart (synthetic classification)*. The panel shows the
   task read from its package: its data folder, model input and output, and its
   main score (accuracy, higher is better).
2. **Workflow**: the experiment setup select in the page bar lists this task's
   setups; *Quickstart research loop* (`quickstart-research-loop`) opens by
   itself when it is the only one. It is a research loop: interpret results,
   propose, implement, validate, train and tune, then feed back. You can add your
   own advice for the proposal step; save it, then select **Next: Run**.
3. **Run**: the page header reads "Setup: Quickstart research loop · Task: …";
   the task is fixed by the setup. Check the inputs and prepare, then review the
   run. The review lists the task, its data folder, the GPU devices from step 4
   and whether your API key name is set. Launch it. **Runs of this setup** at the
   bottom of the page lists it, with a link to Monitor.
4. **Monitor** (Results): follow the run's steps, logs and reported token usage
   until it finishes.

When the run ends, Monitor shows its final status and what each step reported.
This example declares no Health checks, so a finished run shows that the
workflow ran end to end; it makes no claim about model quality.

## Next steps

To bring your own task, follow stage 2 of the
[first-hour path](https://github.com/yuema137/SIDERIUS/blob/master/docs/getting-started/README.md#stage-2-bring-your-own-task):
package it with your coding agent, place it in `siderius_workspace/tasks/<id>/`,
register it with `add-task --manifest`, restart the console and build a workflow
for it. The `tasks/quickstart/` folder this import created is a complete example
of the package layout.

## Building this bundle (maintainers)

The zip is built from the SIDERIUS checkout, never edited by hand: the task
package comes from `examples/quickstart/` and
`configs/task_composition/quickstart.yaml`, and this folder supplies
`README.md`, `fetch_data.py` and `setup/setup.json`:

```bash
.venv/bin/python -m tools.release.build_example_bundle --output-dir /absolute/output
```

It prints the path of `siderius-example-quickstart-<version>.zip` (version from
`pyproject.toml`, or `--version`). Two builds of the same checkout are byte for
byte identical. The format is specified in the
[console contract](https://github.com/yuema137/SIDERIUS/blob/master/src/tools/candidate_console/console-contract.md#example-bundles-add-task---from-bundle).
