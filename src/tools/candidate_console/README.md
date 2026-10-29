# Local candidate console

Prepare, review and explicitly launch one candidate from a configured scientific
task, or launch an externally reviewed native iteration chain. Reopen status and
logs and reported LLM tokens by operation ID, or view an explicitly configured
read-only candidate-validation example.
A run executes the saved workflow: Propose → Implement → Validate, optionally
preceded by Interpret and followed by Train & Tune, and repeated as a research
loop when the source declares one. Inspect native outputs for scientific
results; completion alone does not certify them.

You need a synced checkout, a working [workspace sandbox](../workspace_sandbox/README.md),
an existing task manifest, data directory and LLM profile for candidate preparation,
or a reviewed native capture for the native-chain route below. Keep configuration,
credentials and outputs in your external project. Run commands from this checkout
using its own `.venv/bin/python`.

Starting from a dataset? Follow [project setup](../../../docs/getting-started/README.md)
with your coding agent first. The browser uses tasks already listed in your
console configuration; it does not create a project or edit those task settings.
Save an explicit [LLM profile](../../../configs/llm/README.md) for the console,
even when using the default models.

## Start from the example bundle

To see the whole console path once before you package your own task, start from
the quickstart example bundle. It holds a small synthetic task package and a
ready experiment setup. Download `siderius-example-quickstart-<version>.zip`
from the [releases page](https://github.com/yuema137/SIDERIUS/releases) when the
release lists it; until then build it from this checkout:

```bash
mkdir -p /absolute/downloads
.venv/bin/python -m tools.release.build_example_bundle --output-dir /absolute/downloads
```

The build prints the path of the zip. Its [README](../../../examples/console_bundle/README.md)
lists six commands: unpack, `init --credential-file`, write the data, import with
`add-task --from-bundle`, `serve`, and open the console. The import checks every
file against the bundle's `SHA256SUMS`, copies the package to
`siderius_workspace/tasks/quickstart/`, registers it as step 2 below does, and
creates the setup `quickstart-research-loop` from a workflow template. It never
overwrites an existing `tasks/` folder.

## Set up and open the console

1. Create the console workspace inside a directory you own, for example your
   project directory. Pass that parent directory explicitly; there is no default:

   ```bash
   .venv/bin/python -m tools.candidate_console init --workspace /absolute/project
   ```

   This creates `/absolute/project/siderius_workspace/` with these folders, each
   readable only by you (mode 700):

   | Folder | Holds |
   | --- | --- |
   | `settings/` | `console.json`, the access token file `console-token` |
   | `data/` | one folder per task, `data/<task_id>/`, that you fill with task data |
   | `operations/`, `preparations/`, `candidates/`, `runs/` | console state and run outputs |
   | `library/llm/`, `library/advice/` | saved model profiles and advice files; `init` saves the standard model profile as `library/llm/default-<12 hex characters>.json` |
   | `projects/` | a conventional place for workflow editor projects |
   | `tasks/` | one folder per task package, `tasks/<name>/`: its manifest, plugins and declarations |

   On success it prints the configuration file, browser address, token file
   and connection instructions:

   ```text
   Workspace configuration: /absolute/project/siderius_workspace/settings/console.json
   Console address: http://127.0.0.1:8740
   Access token file: /absolute/project/siderius_workspace/settings/console-token
     The console asks for this token when you connect, on this machine or remotely.
     Show it with: cat /absolute/project/siderius_workspace/settings/console-token
     On this machine: open the console address in your browser.
     On a remote server: first run on your own computer
       ssh -N -L 127.0.0.1:8740:127.0.0.1:8740 YOUR_HOST
     then open the console address there.
   ```

   The token locks the console against other users and programs on the machine;
   it is not a model provider API key. Runs read provider keys only from the
   private file named by `credential_file`. To set it while creating the
   workspace, first create that file (see [Credentials](#credentials)), then add
   `--credential-file`:

   ```bash
   .venv/bin/python -m tools.candidate_console init --workspace /absolute/project \
     --credential-file /absolute/private/credentials.json
   ```

   `init` refuses the file unless it is a regular file you own with mode `600`,
   and never prints its contents. It writes the path into a new
   `console.json`; the closing check then reads the file only to confirm it is
   JSON or dotenv text, so an empty file passes and you can add the key later.
   If `console.json` already exists, `init` does not change it: it creates any
   missing folders, prints the exact `"credential_file": ...` line to add or
   substitute and the `check` command to run next, and exits with status 2.

   `init` is safe to run again. It only creates what is missing; it never
   deletes, replaces or follows a symlink. It refuses a folder that is a symlink,
   belongs to another user, or is writable by your group or by others (for
   example a folder someone else made in `/tmp`). It also refuses a
   `settings/console.json` or library file that is a symlink or has unexpected
   content. Each refusal names the folder or file, exits with status 2 and
   changes nothing that already exists.
2. Register your task. A task package is a folder holding the task composition
   manifest together with the plugins and declarations it names. Copy it to
   `siderius_workspace/tasks/<name>/` (for example `tasks/my-task/task.yaml` and
   `tasks/my-task/plugins/`), put the task data in `siderius_workspace/data/<task_id>/`
   (the folder name, unless you pass `--task-id`), then run:

   ```bash
   .venv/bin/python -m tools.candidate_console add-task \
     --config /absolute/project/siderius_workspace/settings/console.json \
     --manifest /absolute/project/siderius_workspace/tasks/my-task/task.yaml
   ```

   `add-task` adds one entry to `tasks` in `console.json` and changes nothing
   else there. The entry contains:

   | Field | Value written |
   | --- | --- |
   | `task_id`, `label` | the folder name (`my-task`); change them with `--task-id` and `--label` |
   | `task_read_only` | the package folder, so the run sandbox can read the plugins and declarations beside the manifest |
   | `preparation_timeout_seconds`, `candidate_timeout_seconds` | starting values 300 and 3600 seconds; change them with `--prepare-timeout` and `--candidate-timeout` |
   | `candidate_network` | `true`; use `--no-network` to run candidates offline |
   | `candidate_devices` | this machine's NVIDIA GPU nodes (`/dev/nvidia0`, `/dev/nvidia1`, ...), found without asking and printed as `candidate_devices: ...`; none when the machine has no NVIDIA GPU. `--no-gpu` writes none; `--device PATH ...` writes exactly the paths you give. Control nodes such as `/dev/nvidia-uvm` are not written: the run sandbox adds the ones present at launch |
   | `candidate_environment_names` | the API key names your selected model profile needs (for example `OPENAI_API_KEY`), plus names you add with `--env` |

   Read the printed entry and edit `console.json` if a starting value does not
   fit your task. Add `--dry-run` to print the entry without writing anything. A
   manifest outside `tasks/` is refused unless you add `--external`; then the
   folders holding the files the manifest names are listed in `task_read_only`
   instead; a folder that is `/`, your home folder or one holding the console's
   settings, token or credentials is refused, so move such files into
   `tasks/<name>/`. A task ID that already exists is refused. If someone else changes
   `console.json` while `add-task` runs, it writes nothing and asks you to run it
   again.

   After writing, `add-task` creates the task's output folders and runs the same
   check as step 3. It ends with `Restart the console to load the new task.`: a
   running console reads `console.json` only when it starts.

   **GPU runs.** List the GPU's device node (for example `/dev/nvidia0`) in the
   task's `candidate_devices`; that is the only GPU setting. When a run's device
   list contains a `/dev/nvidia<N>` node, the run sandbox itself also mounts the
   host's `/sys` read-only and passes the NVIDIA control nodes this machine has
   (`/dev/nvidiactl`, `/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools`,
   `/dev/nvidia-modeset`, `/dev/nvidia-caps/*`). CUDA needs that metadata to start
   (without it, error 304). Tasks without a GPU node get neither; see the
   [sandbox README](../workspace_sandbox/README.md#gpu-tasks) for what becomes
   visible. An older entry that lists `"/sys"` in `task_read_only` keeps working.

   To confirm a GPU task can start CUDA before you launch, run on the machine
   that will run it:

   ```bash
   .venv/bin/python -m tools.candidate_console check --gpu --config /absolute/project/siderius_workspace/settings/console.json
   ```

   Add `--task <task_id>` to probe one task. For each task that lists a
   `/dev/nvidia<N>` node it prints what the sandbox passes, then
   `Task <id>: GPU PASS: 1 CUDA device(s), first: <GPU name>` or
   `Task <id>: GPU FAIL: <cause>`; it exits 0 only when every probed task passes.
   The probe imports PyTorch and allocates one value on the GPU inside the same
   sandbox a candidate run gets, without network or model calls, and stops after
   120 seconds.

   `add-task` refuses a `--device` path that the run sandbox cannot pass (for
   example one that does not exist on this machine). `check` and `serve` only warn
   about such a path, because some nodes such as `/dev/nvidia-uvm` appear only
   after the first CUDA use, and Run review repeats the warning before you launch.
   A run given a `/dev/nvidia<N>` node this machine does not have is refused with
   `GPU device /dev/nvidia<N> is not present on this machine`. When a launch is
   refused for lack of a GPU, the cause line says which of three things is
   missing: no device node was passed; device nodes were passed but `/sys` is not
   mounted (CUDA error 304: the run did not get the automatic passthrough, so check
   that the task lists a `/dev/nvidia<N>` node and run `check --gpu`); or CUDA
   failed to start with both present (check the driver with `nvidia-smi`, and do
   not set `CUDA_VISIBLE_DEVICES` to an empty value).

   You can also write the task entry yourself. A task needs its `task_id`,
   `label`, `task_manifest`, resource policy and time limits; the
   [configuration example](console-contract.md#configuration) shows every field.
   You can leave out:

   | Field | Used when left out |
   | --- | --- |
   | `llm_config_file` | the model profile selected in `settings/global_settings.json`; `init` selects the standard profile in `library/llm/` |
   | `data_root` | the data folder selected for this task in `global_settings.json`, otherwise `data/<task_id>/` |
   | `preparation_root`, `candidate_root`, `reusable_runs_root` | `preparations/<task_id>/`, `candidates/<task_id>/`, `runs/<task_id>/` |

   Any value you write in `console.json` is used instead; the global settings
   only fill fields that `console.json` leaves out. Then run `init` again with
   the same `--workspace`: it creates the task's output folders, but never
   `data/<task_id>/`. Until you put the task data there, this run ends with
   status 2 and lists `Workspace data/<task_id>: missing`; that is expected.
   Create `data/<task_id>/`, add the data, and run `check` (step 3). If no
   source gives a required field, `init` names it instead, for example
   `task my-task needs llm_config_file` when neither `console.json` nor the
   global settings select a model profile. Browser users can change
   the native run name and three advice fields.

   `console.json` reads `settings/global_settings.json` only when it contains a
   `global_settings` block. `init` writes `"global_settings": {"browser_writable":
   true}` into a new `console.json`, which also lets the browser save settings.
   `init` never rewrites an existing `console.json`, so a workspace created
   before this block existed lacks it; add that line yourself (use `false` to
   read the file but keep the browser from changing it) and run `check`.

   To offer other model profiles, advice files or data locations, list them in
   `console.json` under `llm_profiles`, `advice_files` and `data_roots` (see
   [Global settings](console-contract.md#global-settings)). The settings file
   selects among those entries by ID; it never contains a file path. A data
   location may not contain the token, credential file, `settings/`, `library/`
   or any output folder; `check` refuses it and names the entry.

   A `console.json` without `workspace_root` still works as before: write every
   path yourself as an absolute, canonical path without symlinks, create the
   output parents, and create the token file at `auth_token_file`:

   ```bash
   .venv/bin/python -c 'import os,secrets; p=input("Token file absolute path: "); fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(fd,secrets.token_urlsafe(32).encode()); os.close(fd)'
   ```
3. Check the configuration, then start the server in a persistent terminal/session:

   ```bash
   .venv/bin/python -m tools.candidate_console check --config /absolute/project/siderius_workspace/settings/console.json
   .venv/bin/python -m tools.candidate_console serve --config /absolute/project/siderius_workspace/settings/console.json
   ```

   A successful check and `serve` print the same access instructions as step 1,
   starting with `Console address:` and `Access token file:`. The check
   validates configuration paths, file shape and permissions, without proving task
   composition, required key presence, sandbox availability or provider access.
   When a required field has no value, the check names it, for example
   `task my-task needs llm_config_file`. When the manifest names a file the run
   sandbox cannot read (outside the manifest, the data folder, `task_read_only`,
   this checkout and the system folders such as `/usr`), the check names that file; add its package folder to
   `task_read_only`. When a workspace folder is missing or
   unusable, it lists the folder (for example `data/my-task: missing`) and, if
   `init` can create it, prints the `init` command to run.
   Schema errors name the field to fix and the error type, for example:

   ```text
   console.json is invalid at tasks[0].candidate_network (missing)
   ```

   Here `tasks[0]` is the first task in the list. Missing configured source or
   task resource files are reported with the experiment setup/task name and file path.
   Only `127.0.0.1` binding is supported.
4. On your own computer, open the printed console address directly in your browser.
   On a remote server, keep the server session running there and run this SSH
   tunnel command on your own computer first:

   ```bash
   ssh -N -L 127.0.0.1:8740:127.0.0.1:8740 YOUR_HOST
   ```

   Then open `http://127.0.0.1:8740` on your own computer. The first port is the
   one your browser uses (`browser_origin`); the last is the server's `port` on the
   remote machine. If you forward a different local port, set `browser_origin` to that
   exact local address before starting the server; `check` and `serve` print the
   matching tunnel command.
5. On the machine running the console, view the token with:

   ```bash
   cat /absolute/project/siderius_workspace/settings/console-token
   ```

   Open **Home**, paste the console token, and select **Connect**. The token is
   required whether you connect on the same machine or through an SSH tunnel.
   The connection stays available while you switch between Home, Task, Workflow, Run and Monitor,
   and the connect card shrinks to a **Connected** line with **Change token** and
   **Disconnect console**. Reloading or opening a new tab requires Connect again;
   the password field clears immediately and the token stays only in this
   document's memory. Home offers three starting points: **Quick start** (choose a
   task, then create an experiment setup from the ready-made research loop or open an
   existing one; it opens in Workflow, where you set rounds, stop conditions and
   training settings; the first round starts cold, so no earlier results are needed),
   **Open a workflow** and
   **Monitor runs**. Before Workflow and Run open, choose a task on **Task**
   (see [Choose a task](#choose-a-task)). On **Run**, a stepper shows where you are: check the inputs and
   prepare, then review and launch; the page updates the status by itself.
   **Help** in the header reopens the tour at any time.
   Tools a first-time user does not need stay hidden until you turn them on in
   **Settings** (header): **Show advanced tools** adds the source editor,
   references, Reload from disk, protocol mapping details and
   raw contract ids on the canvas and in Selection, the model-hyperparameter
   owner, native chains, configured-task
   preparation, the operation-UUID form and recorded examples; **Show developer
   details** adds operation facts, raw token tables, captured resources and save
   internals. The browser remembers both choices.
6. To generate a candidate from the server's configured task, expand **Prepare
   configured task** on Home (Settings › Show advanced tools). Select a task, fill the run name and optional advice,
   and expand **Configured paths** to inspect the inputs and output parents.
   **Prepare request** creates separate UUID child paths. Review the resolved
   workspace, task, models, credential blockers and resource policy before
   **Launch candidate**, which starts code execution and may call paid APIs.
   Native Prepare generates its configured candidate independently of the declaration
   selected in Workflow. Preparation never launches automatically.
7. To observe an existing operation, choose **Monitor** and select it under
   **Recent operations** (operations this console admitted, newest first), or
   enter its complete operation UUID (Settings › Show advanced tools). You can also open a link such as
   `http://127.0.0.1:8740/#monitor/22222222-2222-4222-8222-222222222222`
   (replace the example UUID), then Connect. No task or editor project selection
   is needed. The optional remembered ID is labelled **Last opened on this browser**;
   it is separate from the Recent operations list. Expand Operation facts, Reported
   token table, or Activity and logs when needed. When a workflow run has
   finished, **Workflow training results** shows the tuner report of each
   verified iteration separately; it never combines or ranks iterations.
   A running authored research loop shows **Stop at next boundary**: the current
   iteration finishes, and status says stopped only once the native receipt does.
   **Pause at next boundary** works the same way; a paused loop can be reviewed and
   resumed, optionally with your advice, as a new segment of the same run, which
   shows its own results.
   A loop ended early by a declared stop condition says why, in plain words.
   A condition set to **Pause and ask me** pauses the loop instead and reads
   "Waiting for your input", followed by what was met, for example "No improvement
   for 3 bodies (best 0.81 at body 4, higher is better). Paused after body 7 of 12."
   Check the per-iteration results, then choose **Review resume** and **Resume loop**
   to continue with the next body. After **Review resume** you can type advice for
   the next bodies (up to 4000 characters). Their proposal step receives it, and it
   replaces any advice an earlier resume gave. The box starts with this segment's
   advice. It locks once you select **Resume loop**, so a retry sends the same text.
   The resumed segment then shows "Resumed with your advice: …". If you pressed Stop while it was waiting, the run
   cannot continue and no Resume is offered.
   A loop with a judge stop condition lists each judge decision under it, with
   the judge's own reason when the call decided.
   To stop a running candidate now, press **Stop run** and confirm. The run
   ends within about 1.5 seconds (half a second to notice, then up to one second
   before it is force-killed), including a model call in progress. It cannot be
   resumed and produces no candidate result; files written so far stay in the run
   folder. A call that was in flight may still be billed without appearing in the
   token report. The page says "Stopping the run…" until the native receipt reads
   `cancelled`, then "Run stopped." If the console loses contact with the server,
   the line starts with "Last observed:". The Run page shows the same button for
   a retained candidate whose last checked status is active.
   Configured **Recorded examples** appear in Monitor. They show verified
   proposal, implementation, validation and reported-token evidence only; they
   are not live operations, training results, scientific scores or billing
   records. Configure `recorded_examples` only for fixed canonical workspaces
   under `operation_store.candidate_roots`, with the expected native run ID.
   The view has no operation import or execution controls, and a missing saved
   source is shown as unavailable.
8. To author a configured declaration, choose **Workflow**. Select a node
   to inspect its supported bindings. With **Show advanced tools** on, expand
   **References** for task and external locations, or **Advanced source** for
   exact Python bytes. Review opens the
   exact diff; Save writes those reviewed bytes. Connections, card moves and
   inspector edits collect in one set of pending edits that you review and save
   together. **Undo**/**Redo** (Ctrl+Z / Ctrl+Shift+Z) step through them;
   **Revert to saved** returns to the workflow as it was last saved (Undo brings your
   edits back), while **Reload from disk** (advanced tools) re-reads the file and asks
   first if edits are pending. A `*` in the tab title, an *Unsaved changes* badge and a
   dot beside the version name in the page bar mark pending edits. Switching views retains pending
   edits and review state. A real page exit with pending edits uses the browser's
   unsaved-change guard. Saving does not run the declaration.
   Moving a card or editing a setting rewrites the whole Python file. If that would
   remove comments you wrote by hand, the Save step says how many and which ones
   before you confirm. Saving into a read-only file is refused ("This file is
   read-only on disk"); make the file writable, then select **Save version** again.
   If the file changed on disk while you edited (for example, you saved it from
   another tab), the page shows **This workflow changed on disk** with what changed.
   Choose **Reapply my changes onto latest** to keep your edits, or **Reload from
   disk** to drop them. **Version history** (`⋯` menu) lists each saved version;
   **View** shows what changed, and **Restore this version as a draft** loads an older
   version as unsaved changes that you save like any other edit.
   The **Research loop** panel adds or removes the loop, its iteration limit and its stop conditions.
   A **Judge** stop condition takes what the judge should look for, the first body it
   judges after, and what a failed judge call does; the judge model and its call limit
   come from the console operator's model settings.
   Each stop condition has **When met**: **Stop** (the default) ends the loop early;
   **Pause and ask me** pauses it and waits for you on Monitor. After you resume, the
   same condition asks again only after a new stretch counted from that pause (a
   no-improvement condition needs its full number of bodies again; a metric threshold
   asks once). Conditions set to Stop are checked first.
   For reusable task packages, [bind a task version](#bind-a-task-version) first.
   Until the canvas has a module, it says what to do next and offers **Start from a
   template**; the 4-step tour is a link below it and under **Help**.
   Save behavior and concurrent-writer notes are under **Details** (Settings ›
   Show developer details). After a successful save, **Next: Run** opens the **Run**
   page; it stays disabled, with the reason in its tooltip, while edits are unsaved or
   the project is not enabled for runs.
   A step line (Task › Workflow › Run › Results) shows where you are.

The entry URLs are `/#home`, `/#workflow`, `/#run` and `/#monitor`. Old
`/#slow-control` links (the page's former name) open Monitor, and an old
`/editor.html` link redirects to `/#workflow` before asking for credentials.
Connection sharing applies within one document; separate tabs/windows connect
independently.

## Choose shared settings in the browser

The **Settings** page chooses, for every task at once, the model profile, an
advice file and each task's data folder. It only offers what the operator listed
in `console.json` (`llm_profiles`, `advice_files`, `data_roots`) or saved in the
workspace library, so the browser never types a server path.

1. Open **Settings** and connect. The page says which server holds the folders:
   paths are on the machine running the console, not on your computer.
2. Under **Models**, pick a profile. Tasks whose `console.json` entry sets
   `llm_config_file` keep their own; the page only fills values that
   `console.json` leaves out. A workflow's own values are used for that workflow.
   Each profile lists the provider key names it needs (never their values);
   **Show routes** lists which provider and model each step uses. To add a
   profile, choose **Import from this computer…** and pick a JSON profile; the
   console checks it first and refuses a misspelled key without saving anything.
3. Under **Advice**, pick a file or **None**. The choice is only saved for
   now: no run uses it, and each workflow keeps the advice written in it.
   **Import from this computer…** accepts an advice file in the command-line
   format, including one you exported earlier. Each file lists which steps it
   advises; keys that workflows cannot use yet (`interpret`, `analysis`,
   `mindset`) are marked.
4. Under **Data folder**, choose a data root for a task, open subfolders, and
   select **Use <folder>**. Links are shown but cannot be selected. A task whose
   `console.json` sets `data_root` shows "Set in console.json" instead.
5. Select **Save settings**. Success reads "Saved; active after server
   restart". Restart the `serve` command to use the new values; until then the
   page lists what is saved but not yet active. **Values in effect** shows each
   value the running console uses, where it comes from and its server path.

Saving and importing need `"global_settings": {"browser_writable": true}` in
`console.json` (`init` writes it); otherwise the page is read-only. Imported
files are copied to `library/llm/` or `library/advice/` on the server under a
name that ends in the first 12 hex characters of their SHA-256. Importing the
same file again reuses that copy; library files are never replaced or deleted.
If someone else saved in the meantime, the page says so; select **Reload** and
choose again. A choice that would fail `check`, such as a folder that no longer
exists, is refused with the reason and nothing is written. If
`settings/global_settings.json` itself becomes unusable, the page says why: run
`chmod 600` on it if its permissions changed, or fix or restore it; when it is
readable but invalid, you can also choose values and **Save** to replace it.
**Workspace** lists missing workspace folders and, when `init` can create them,
the command to run on the server.

### Copy a workflow's model profile and advice to files

On **Settings**, **Export a workflow** copies three plain files into
`siderius_workspace/exported_configs/<export name>/` on the server:

| File | What it is | What reads it |
| --- | --- | --- |
| `llm.json` | the model profile the selected task uses | the command-line `--llm_config` |
| `advice.json` | the advice written in the workflow itself (proposal, implementation, validation and tuning advice), in the command-line advice format | the command-line `--advice` |
| `workflow.py` | the workflow exactly as last saved in Workflow | no command-line flag; keep it as a record or copy it into an editor project |

A workflow without advice of its own gets no `advice.json`. Credentials, the
console token and the credential file path are never exported. The export uses
the values the running console uses; settings saved since the last restart are
not included.

1. Choose the project, the task and an export name, then select **Export**.
2. Success reads "Exported to exported_configs/<name> on the server", followed by
   one **Download** button per file. Downloads save the files to this computer.
3. On the server, pass the files to a command-line run in place of your own
   paths, for example (the other flags are those of
   [your first run](../../../docs/getting-started/first-run.md)):

   ```bash
   bash scripts/launch/run_chain.sh \
       --llm_config /absolute/project/siderius_workspace/exported_configs/my-export/llm.json \
       --advice /absolute/project/siderius_workspace/exported_configs/my-export/advice.json \
       ...
   ```

An export name that is already used is refused with a free name to try; exports
are never overwritten. The export is also refused when the saved workflow
changed on disk while you exported, when it does not parse, or when the task's
model profile would be refused by `--llm_config`; the message says which.
Exporting needs the same `browser_writable` setting as saving.

When you review a new run on the **Run** page, the details also say where the
model profile and data folder come from: `console.json`, this Settings page, or
the workspace folders.

## Edit existing circuit connections

In Workflow builder, select a node to open its inspector. To change a connection,
select an output socket (right side of a card), then a highlighted input. Sockets are
labelled with the kind of data they carry, for example *Model plan*; hover one to see
what it connects with. Press Escape
or right-click to cancel. The inspector offers the same binding choices, including
external inputs such as storage. Only existing inputs can be rewired here.

A large workflow opens zoomed out (never below 75%, so text stays readable; scroll the
canvas for the rest). The controls at the bottom right of the canvas (zoom, **Actual
size**, **Fit to view**) change only the view. Optional inputs that no wire feeds are
folded into a "+N optional" row on each card; expand it to connect one. If saved cards overlap, the canvas says so;
**Tidy up** arranges them (one edit you can undo).

**Check the workflow** (bottom right) sends a small dot along every connection in the
order the modules run, then along the research loop's dashed feedback wire (when there is a loop). If
something is missing, the dot stops there: that socket glows soft red and one sentence
under the card says what is not connected. With reduced motion turned on in your
system settings, the glow appears without the moving dot.

Drag a node heading to move it, or focus the heading and use Alt + arrow keys.
These edits stay local until you press **Save** (it checks the workflow) and then
**Save version** in the row that opens. **Tidy up** (bottom-right of the canvas) lines
the cards up left to right in pipeline order (modules with no wire go in the next
column); it is one edit you can undo. Click a card and press Delete to delete it; Undo
brings it back. Keyboard users can press Tab once on the Workflow page and choose
**Skip to canvas**.
For a bound workflow, choose its matching configured task version and acknowledge
the findings. Prepare a new run on the Run page to check its supported execution profile.

To add nodes, click or drag entries from **Modules**, or hover a card and
press the **+** beside an output that is not connected yet: pick a module and it is
added to the right, already connected. You can add several nodes, move any card and
wire them in any order. A node with a missing required input shows it in red, the
**N problems** chip in the bar above lists every missing input (click a row to jump to
it), and **Save** stays disabled with the reason beside it until all are connected.

When a required input such as `storage` has nothing to connect, select the node.
Under that input, Selection explains what the input is. Open **Create external
input…**, keep or change the suggested id, and type the project-relative path of
the JSON file that will hold the value, for example `inputs/build_store.json`.
In a reusable workflow there is no path to type: the run supplies the input when it
is prepared (reusable preparation accepts only such managed inputs). Then click
**Create and connect**. Undo, Redo and Revert to saved cover all of these edits.

## Choose a task

A task is your scientific problem as a package: its data, the model's input and
output, the training objective, the main score, its Health checks and the settings
it locks. Every workflow and run belongs to one task, so the console asks for the
task first. The Task tab only shows the package; you change the package with your
coding agent, then press **Refresh**.

1. Connect, then open **Task** in the navigation bar (or the first step of the
   Task › Workflow › Run › Results bar).
2. The left list shows every task in your console configuration with its version
   (`task_revision`) or **unversioned**. With exactly one task, the console selects
   it for you. Otherwise select one. The browser remembers your choice for this
   console.
   - **No task is registered** means `siderius_workspace/settings/console.json`
     lists no task. Put your task package in `siderius_workspace/tasks/<id>/`,
     run `add-task` as described in step 2 of
     [Set up and open the console](#set-up-and-open-the-console), then restart the
     console.
   - **Tasks could not be loaded** shows the reason; select **Retry**.
3. The right panel reads the package in the workspace sandbox. While it reads,
   it says **Reading the task package in the sandbox…**; the page updates itself.
   When it is ready, the panel shows these sections:

   | Section | What it tells you |
   | --- | --- |
   | Identity | Label, task id and version. **Fingerprint** (collapsed) holds the package's exact identity. A warning appears when the configured version no longer matches the package on disk. |
   | Data | The data folder, how many files it holds and their total size. The training and evaluation split sizes appear when the task declares them, otherwise "not declared by this task". **Count samples** asks the task to count its samples in the sandbox; this can take a while. |
   | Model input and output | The tensor shapes and meanings a model must accept and produce. |
   | Objective | The training loss the task fixes, or that the planner chooses it. |
   | Main score | The metric that ranks candidates, whether higher or lower is better, and how it is aggregated. Metrics marked **Recording** are only measured and stored. |
   | Health checks | Each gate, its checks and its effect: **Blocking** makes a failing candidate invalid; **Recording** only records the result. |
   | Evaluation and model plugins | The task's code files, their symbols and what each one does. |
   | Locked parameters | Settings no workflow can change, for example a fixed batch size. |
   | Deliverable | How the task names its output files, when it declares this. |
   | Run policy | Time limits, network access, the devices passed into the run sandbox (with a warning when no GPU is passed), and the names of the credentials a run receives. Credential values never appear. |

   If the panel says the package **could not be read**, it names the stage and the
   error: fix the package with your coding agent and press **Refresh**. If it says
   the summary is **not available** (for example, the sandbox or the data folder is
   missing), follow the hint shown and press **Refresh**.
4. Open **Workflow**. Until a task is selected, Workflow and Run are greyed out
   ("Choose a task first") and their pages show a **Choose a task** button.

## Create an experiment setup and run it

An experiment setup is one workflow for one task. A task can have several setups (for
example a research loop and a single step); every run belongs to one setup.

1. Choose the task on **Task**, then open **Workflow**. The select in the page bar lists
   this task's setups. Older workflows from `console.json` that match no configured task
   appear under **Other workflows (no configured task)**.
2. Select **New setup…**. Choose how it starts: a template (the research loop with your
   own advice is preselected) or **Blank**. Enter a label and select **Create setup**.
   The console writes `siderius_workspace/projects/<setup id>/workflow.py` and opens it.
   If the dialog says creating setups is turned off, the console operator adds
   `"experiment_setups": {"browser_creatable": true}` to
   `siderius_workspace/settings/console.json` and restarts the console.
3. Edit the workflow and select **Save**, name the version and **Save version**.
4. Select **Next: Run**. The Run page names the setup and its task ("Setup: … · Task:
   …"); the task is fixed by the setup, so you only check the inputs and prepare.
5. **Runs of this setup** at the bottom of the Run page lists this setup's runs, newest
   first; select one to follow it in **Monitor**.

When you add a **Metric threshold** stop condition, the metric field starts with the
task's main score and suggests the task's other metrics, once the Task tab has read the
task package.

If a setup's task references no longer match its task, the Workflow page shows a
warning with a button that opens **Task version** on the Task tab, where you update them.
**Quick start** on Home does steps 1 and 2 for you with the research-loop template.

The **Task version** card below the panel is where you switch the task version an
open workflow uses; its findings then open in the Workflow save step. See
[Bind a task version](#bind-a-task-version).

## Bind a task version

The task chip in the Workflow page bar shows the setup's task, for example
`Task: Quickstart`, and the pinned version when there is one. Versions are optional:
when the task declares versions and the workflow pins none, a separate
`Task version: not pinned` note appears beside the chip. Click the chip
to open the **Task version** card on the **Task** tab. That card states which task package and
version the open workflow uses. Versions are offered only for configured tasks
that declare `task_revision`; otherwise the panel says that none are configured.

In the **Task version** card, explicitly choose a configured task package/version and
**Update workflow references**. The console returns to **Workflow**, where the save
step shows the Python diff and the task findings; confirm them and **Save version**. An unbound reusable workflow requires a separate
confirmation to adopt its currently observed snapshot; save that binding before
editing its scientific settings.

You can switch checked task versions for a Propose → Implement → Validate workflow,
including one proposal with several implementation branches, or several independent
proposals with their own implementation and validation branches. The switch preserves
those branches and their shared advice. Keep both task directories available and
unchanged.
Review changed data declarations, metrics and guidance, along with retained advice;
Save checks compatible inputs and outputs again. Training workflows and other
unsupported forms explain why the switch is blocked. Existing runs stay unchanged.
See the [exact support boundary](../workflow_authoring/authoring-contract.md#changed-task-versions-for-fresh-candidates).

Save pending source or inspector edits before Update. For bound edits, select the
matching configured choice and use the ordinary **Save** first.
Choosing a version alone never changes source. Both Professional and Assistant
collaboration use this flow. Saving affects future captures; preparation and launch
remain separate, and existing runs keep their captured binding.

## Prepare saved source or open an existing run

Configure the authored project in `editor_projects`, enable its ID in
`runnable_editor_projects`, and set the task's `reusable_runs_root` to an existing
external runs directory. Include that parent in both
`operation_store.preparation_roots` and `candidate_roots`. Restart after changing
configuration. (A workspace console can also create a project for a task, called
an experiment setup, without editing console.json; see "Experiment setups" in the
[console contract](console-contract.md). The browser page for it comes later.
Setup folders live in `projects/` of the workspace, so `check` refuses a task
whose `data_root` or `task_read_only` entry is inside that folder.)
The source task references and output restrictions must agree with
the configured task; the browser does not rewrite them to match your selection.
See the [reusable configuration contract](console-contract.md#reusable-capture-consumption).

1. Connect, choose the task on **Task**, and open **Workflow**. Review and **Save** your source edits.
   An already saved supported reusable declaration needs no extra Save. Resolve
   any source conflict before continuing. Select **Next: Run**; the
   **Run** page states which saved version it will use.
2. On the Run page, in **New run**, explicitly choose the configured task and resources, enter a
   run name, and select **Review preparation**. Check the source, dataset, model
   profile, inputs/workspace destinations and resource limits. To use different
   resources, configure another task choice outside the browser.
3. Select **Prepare saved source**. This captures the saved source and creates
   native inputs in `runs/<UUID>/inputs/`; `workspace/` remains absent. Preparation
   is offline and does not need provider keys. **Check status** or **Monitor
   preparation** shows its outcome. Saving and preparation never launch a candidate.
4. Once preparation reports **prepared**, select **Open prepared run**, then
   **Review capture**. Leave **Seed** (under **Optional settings**) blank; SIDERIUS picks one and records it. Check model routes and credential readiness. Existing runs
   made through Python or CLI can instead be selected from **Prepared run**.
5. Select **Launch captured run** explicitly. This runs Propose → Implement →
   Validate and, when declared, native Tune with the captured inputs. It may call
   paid model APIs and use configured training resources. Current source
   edits remain separate. Follow **Monitor operation** for validation outcome;
   prepared inputs alone do not mean a candidate was accepted.

If a step does not succeed, the line under the Run steps says so in plain words, for
example "The preparation failed. The cause and its log are named below; start over to
try again." or "The run failed. The cause is shown below; open it in Monitor for the
full log." A time limit, an interruption, a stop on request and a worker that never
started each get their own sentence. Below it, the step's status line names the cause:
the last error line of the log, such as "Cause (from the log): TaskCompositionError:
plugin file … does not exist". A failed preparation also names its log file,
`inputs/preparation/worker.log` in the run's folder; Monitor shows the same log under
**Activity and logs** with log source **Native**. Fix the cause, then select **Start
over** and prepare again. A paused research loop is not reported as finished either:
the line says whether it is waiting for your input or was paused by you, and to open
it in Monitor to resume.

The browser retains preparation and candidate intents separately before sending
either effect. Storage failure prevents dispatch. After a lost response or reload,
Connect and use **Check status** or retry the same operation. An unresolved intent
blocks new effects; changing or saving source never removes it. Wait until the process has exited or a launch failure is confirmed before
the console offers dismissal or another effect. An initial request explicitly refused before
admission can be discarded and reviewed again; restored or ambiguous requests retain
their UUID. No automatic retries or replacement IDs are created.

While the server is live, an admitted preparation can be recovered even if its
original source or credential file disappears. Restart still validates configured
resources. Source changes during preparation can make it fail; inspect and preserve
that operation's evidence. A successfully prepared capture remains independent of
later editor changes. Only a paused research loop can be resumed, as a new
segment of the same run; failed, stopped or timed-out runs cannot. A coding agent
can do the same from the
[command line or Python](../candidate_operations/README.md#stop-pause-or-resume-a-research-loop).

## Run a configured native chain

A native capture records reviewed inputs for the original iterative recipe:
Interpret → Propose → Implement → Validate → Tune. Create it through the
[native capture setup](../native_chain/README.md) before opening the console.
The browser launches that configured recipe independently of the editor.

1. Add a `native_chain_choices` entry to your external `console.json`: give it a
   `choice_id`, a readable `label`, and the native operation `request` prepared
   with the capture. Configure its destination, resource limits and forwarded
   credential names there. The [configuration contract](console-contract.md#configured-native-chains)
   specifies these fields. For a native-only console, omit `tasks` and
   `editor_projects`; no dummy candidate task is needed.
2. Check and start the console with the commands above, then Connect. Turn on
   **Settings › Show advanced tools**. On Home,
   choose the capture under **Run a configured native chain** and select
   **Review native capture**. Inspect its run name, final iteration, workspace,
   input identities, resource policy and credential readiness. Consult the
   original capture for complete scientific settings.
3. Select **Launch native chain** explicitly. The operation UUID appears before
   submission. Follow **Open native monitor** to see process state, shell
   outcome, cleanup and each checkpoint's native status and integrity separately.
   A completed process does not establish scientific success; `no_records`,
   unavailable evidence and invalid evidence remain visible. The reported-token
   table covers the whole native run, including continuations.
4. If the response is lost, keep the displayed UUID. Reconnect to check it, or
   use **Retry same native launch** while admission remains unconfirmed. Neither
   navigation nor reconnect launches automatically. Reload the UUID's Monitor
   link to monitor it without selecting a task or editor project. After admission
   is confirmed, **Review another native capture** clears the form for another
   configured destination; it does not stop the previous run.

Each new destination needs a new externally reviewed capture and fresh envelope
(the parent directory reserved for that operation). Pinned source changes may
refuse dispatch. The console does not edit native captures or offer resume/stop.
Unrelated unsaved editor drafts survive navigation. A pending native launch is
retained in page memory; reload retains only the UUID for monitoring.

For a monitor-only server, keep the same operation store and access configuration,
remove task/native choices and editor projects, and omit `credential_file` if its
file is unavailable. Known UUIDs remain readable after capture or source removal.
An explicitly configured credential file must still pass startup checks.

## Credentials

The two private files have different jobs:

| Configuration field | File contents | Purpose |
| --- | --- | --- |
| `auth_token_file` | Random token generated by step 2 | Unlock this local console |
| `credential_file` | JSON object of string names and values, or dotenv `NAME=value` lines | Supply selected provider keys and other declared runtime variables to a candidate |

To share this host's GPUs with runs started elsewhere (for example from the
command line), add a `host_ledger` entry that names the same ledger directory and
budget file those runs use: `"host_ledger": {"ledger_root":
"/absolute/private/host-ledger", "budget_file": "/absolute/host-budget.json"}`.
The [operations guide](../candidate_operations/README.md) explains how to create
both. The console checks them when it starts and refuses to start if either is
wrong, so a mistake never makes runs skip the ledger.

Then, on **Run**, open **Host resources and parallel nodes** before you review:

1. Tick **Declare this run's resources** and enter what the run needs: GPU or no
   GPU, its GPU memory, host memory and CPU slots, and whether it uses a training
   time budget. With a ledger this is required; nothing is filled in for you.
2. Optionally tick the node kinds that may run at the same time, with what one
   node of that kind needs. Kinds you leave unticked run one at a time, as before.
3. Click **Review prepared run**. The review lists what you entered; changing it
   afterwards asks you to review again.

When the host is busy, the run shows **queued** and starts by itself when earlier
runs finish. Stopping a queued run removes it before it starts ("Cancelled before
start"). Native chains always run one step at a time, outside the ledger.

For example, if your saved `llm.json` uses OpenAI routes, set
`candidate_environment_names` in that task's `console.json` entry to
`["OPENAI_API_KEY"]` (`add-task` writes these names for you). Set
`credential_file` to a private absolute path such as
`/absolute/private/credentials.json`, either with `init --credential-file`
(step 1) or by adding the line to `console.json` yourself. Its contents have this
shape (placeholder only; replace it privately with your key):

```json
{
  "OPENAI_API_KEY": "REPLACE_WITH_YOUR_PRIVATE_OPENAI_KEY"
}
```

Create the file privately, owned by the user running the console, with mode
`600`, then edit it locally in your editor. This creates an empty file with that
mode (the folder must already exist); skip it if the file already exists:

```bash
(umask 077 && touch /absolute/private/credentials.json)
```

For an existing file, set that mode with:

```bash
chmod 600 /absolute/private/credentials.json
```

You can instead point `credential_file` at an existing dotenv file owned by you
with mode `600`. Prefer one kept outside the source tree; a checkout's `.env`
also works. A file whose first non-blank character is `{` is read as JSON;
anything else is read as dotenv
(comments, `export` and quotes allowed; `${...}` is not expanded). Only the
declared names are passed to the candidate; other entries are ignored.

Use only the keys required by your selected providers, plus any other explicitly
declared runtime variables. The current credential variable names are
`OPENAI_API_KEY`, `GEMINI_API_KEY` and `DEEPSEEK_API_KEY`. Match the names in the private file
and `candidate_environment_names` to your reviewed profile. Do not put values in
`console.json`, commands, browser fields or version control. A placeholder is not
a working key; presence does not prove authentication, quota or network access.

After Prepare verifies the selected task, review shows the required provider names,
names omitted from `candidate_environment_names`, and names present or missing in
`credential_file`. A known blocker disables **Launch candidate**. Follow the repair
message: changing allowed names needs restart and a new Prepare; changing values
in the same private file needs **Refresh readiness**. No key value goes to the
browser. This check proves name presence only, not provider access or quota.

At Launch, the console rereads `credential_file` and passes only the declared
names; missing or empty declared values block submission. Shell exports and a
project `.env` that `credential_file` does not name do not satisfy this console
binding. Downstream dotenv loading is
legacy compatibility, not a setup step or a reliable credential source.
Preparation is offline and does not need provider keys.

Restart the server after changing `console.json` or saving **Settings**, including task paths, model
profile selection, resource policy, allowed names or private-file paths. Such
changes can require a fresh Prepare. Updating values at the same credential-file
path takes effect on the next Launch without restart; the file must still pass
the private-file checks. For a changed model profile, prepare and review again
before launching.

For direct CLI or coding-agent launches, use the separate
[API-key procedure](../../../docs/getting-started/installation.md#api-keys):
trusted shell-compatible external files or managed environment injection are
supported there. A JSON credential file cannot be sourced by a shell.

## Monitor reported usage

The table groups provider reports by requested and served model. A missing field
shows **Unavailable**; a known value shows its reported sum and any missing-row
count. Partial or stale observations remain labeled. These are observed provider
reports; missing or unrecorded usage may exist, so the table does not establish
complete billing. Preparation has no applicable token table. Known operation IDs
can be read even when the current task choices differ; the admitted operation
store configuration must still match. Direct candidate runs without an operation ID use the
[native Python reader](../candidate_worker/README.md).

For native chains, parent and continuation IDs show the same cumulative usage;
do not add their tables together. Expand the table details for the identity source
and limitations. Token monitoring does not reread scientific result files, and its
counts do not establish scientific validity or complete billing.

Closing the page, tunnel or HTTP server does not cancel an admitted operation.
A disconnected view is stale, not stopped. Native timeouts and sandbox cleanup
still apply; host reboot recovery, cancellation and public hosting are unsupported.
An `unknown` outcome requires investigation and blocks new admission. Only one
operation occupies a store at a time; a completed operation can briefly be
finishing while its wrapper exits.

Logs are private operator data and can contain sensitive output from trusted
plugins. Review and launch require an unchanged preparation matching exactly one
configured task; changing configuration requires restart and can require a fresh
preparation. See the [console contract](console-contract.md) for the Python/API
interface, security boundary and qualification commands.

To edit an ordinary workflow declaration alongside a coding agent, configure the
optional [Workflow Editor](../workflow_authoring/README.md). It has its own source
review/save flow. Saving changes the source available to a subsequent New run;
it never changes an existing captured run.
Existing console configurations need no editor project to monitor operations.

## Edit reusable training settings

Start from the [four-stage source example](../../../examples/workflow_declarations/reusable_training.py)
in your external project. Set its task references and output restriction for your
task; choose an installed planner strategy explicitly in the external LLM profile
(for example the native `tune.planner_strategy: native-timing-v1`). The example's
budgets and diagnostic settings are demonstration choices, not scientific defaults.

Select **fit / tuning** in Workflow. The small inspector edits trial/formal
budget minutes, epoch ceilings, portions and retention flags. Open **Training
settings** (collapsed, with the number of changed fields). **Default** removes the
key; **None** explicitly stores null where supported. Empty numbers block review;
zero is validated by the native owner. There is no seed setting here: each run gets
one recorded seed at launch. Epoch ceilings constrain native planning rather than
specifying final epochs. Outer candidate timeout remains seconds.

Review shows inherited values and supplied parameter rules. Edit advanced controls
and rules in Source; unrelated inspector changes preserve them. Review and Save,
then use **New run** and **Launch captured run** as described above. Each capture
keeps its own settings; edits affect future captures.

External Health configuration files are not captured by reusable training.
Task-composed Health and native startup controls remain available. After completion,
inspect scores, Health and termination reason in the
[native outputs](../candidate_worker/README.md); completion means the tuner returned.
See the [contract](console-contract.md) for exact field semantics and qualification limits.
