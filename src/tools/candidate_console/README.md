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

   On success it prints two lines, the configuration file and the browser
   address with the token file:

   ```text
   Workspace configuration: /absolute/project/siderius_workspace/settings/console.json
   Console: http://127.0.0.1:8740; access token file: /absolute/project/siderius_workspace/settings/console-token
   ```

   The token unlocks the console;
   it is separate from any model provider API key. Follow [Credentials](#credentials)
   below to bind provider keys before Launch.

   `init` is safe to run again. It only creates what is missing; it never
   deletes, replaces or follows a symlink. It refuses a folder that is a symlink,
   belongs to another user, or is writable by your group or by others (for
   example a folder someone else made in `/tmp`). It also refuses a
   `settings/console.json` or library file that is a symlink or has unexpected
   content. Each refusal names the folder or file, exits with status 2 and
   changes nothing that already exists.
2. Add your task to `siderius_workspace/settings/console.json`. A task needs its
   `task_id`, `label`, `task_manifest`, resource policy and time limits; the
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

   A successful check prints the browser address and token file location. It
   checks configuration paths, file shape and permissions, without proving task
   composition, required key presence, sandbox availability or provider access.
   When a required field has no value, the check names it, for example
   `task my-task needs llm_config_file`. When a workspace folder is missing or
   unusable, it lists the folder (for example `data/my-task: missing`) and, if
   `init` can create it, prints the `init` command to run.
   Only `127.0.0.1` binding is supported.
4. For a remote host, keep the server session running and open an SSH tunnel:

   ```bash
   ssh -N -L 127.0.0.1:8740:127.0.0.1:8740 YOUR_HOST
   ```

   Open `http://127.0.0.1:8740`. If the local forwarding port differs, configure
   `browser_origin` to that exact local address before starting the server.
5. Open **Home**, paste the console token, and select **Connect**. The connection
   stays available while you switch between Home, Workflow Editor, Run and Slow control,
   and the connect card shrinks to a **Connected** line with **Change token** and
   **Disconnect console**. Reloading or opening a new tab requires Connect again;
   the password field clears immediately and the token stays only in this
   document's memory. Home's main path is **Open workflow**: edit and review the
   workflow, prepare a new run, then launch and monitor it.
6. To generate a candidate from the server's configured task, expand **Prepare
   configured task** on Home. Select a task, fill the run name and optional advice,
   and expand **Configured paths** to inspect the inputs and output parents.
   **Prepare request** creates separate UUID child paths. Review the resolved
   workspace, task, models, credential blockers and resource policy before
   **Launch candidate**, which starts code execution and may call paid APIs.
   Native Prepare generates its configured candidate independently of the declaration
   selected in Workflow Editor. Preparation never launches automatically.
7. To observe an existing operation, choose **Slow control** and select it under
   **Recent operations** (operations this console admitted, newest first), or
   enter its complete operation UUID. You can also open a link such as
   `http://127.0.0.1:8740/#slow-control/22222222-2222-4222-8222-222222222222`
   (replace the example UUID), then Connect. No task or editor project selection
   is needed. The optional remembered ID is labelled **Last opened on this browser**;
   it is separate from the Recent operations list. Expand Operation facts, Reported
   token table, or Activity and logs when needed. When a workflow run has
   finished, **Workflow training results** shows the tuner report of each
   verified iteration separately; it never combines or ranks iterations.
   A running authored research loop shows **Stop at next boundary**: the current
   iteration finishes, and status says stopped only once the native receipt does.
   **Pause at next boundary** works the same way; a paused loop can be reviewed and
   resumed as a new segment of the same run, which shows its own results.
   A loop ended early by a declared stop condition says why, in plain words.
   To stop a running candidate now, press **Stop run** and confirm. The run
   ends within about 1.5 seconds (half a second to notice, then up to one second
   before it is force-killed), including a model call in progress. It cannot be
   resumed and produces no candidate result; files written so far stay in the run
   folder. A call that was in flight may still be billed without appearing in the
   token report. The page says "Stopping the run…" until the native receipt reads
   `cancelled`, then "Run stopped." If the console loses contact with the server,
   the line starts with "Last observed:". The Run page shows the same button for
   a retained candidate whose last checked status is active.
   Configured **Recorded examples** appear in Slow control. They show verified
   proposal, implementation, validation and reported-token evidence only; they
   are not live operations, training results, scientific scores or billing
   records. Configure `recorded_examples` only for fixed canonical workspaces
   under `operation_store.candidate_roots`, with the expected native run ID.
   The view has no operation import or execution controls, and a missing saved
   source is shown as unavailable.
8. To author a configured declaration, choose **Workflow Editor**. Select a node
   to inspect its supported bindings; expand **References** for task and external
   locations, or **Advanced source** for exact Python bytes. Review opens the
   exact diff; Save writes those reviewed bytes. Connections, card moves and
   inspector edits collect in one set of pending edits that you review and save
   together. **Undo**/**Redo** (Ctrl+Z / Ctrl+Shift+Z) step through them;
   **Discard changes** returns to the workflow as it was loaded, while **Refresh
   from disk** re-reads the file and asks first if edits are pending. A `*` in
   the tab title and an *Unsaved changes* badge mark pending edits. Switching views retains pending
   edits and review state. A real page exit with pending edits uses the browser's
   unsaved-change guard. Saving does not run the declaration.
   The **Research loop** panel adds or removes the loop, its iteration limit and its stop conditions.
   For reusable task packages, [bind a task version](#bind-a-task-version) first.
   Until a workflow is open, the page shows **Start from a task example**: select a
   task, edit, save, run. Save behavior and concurrent-writer notes are under
   **Details**. After a successful save, **Next: prepare a run** opens the **Run**
   page; it stays disabled, with the reason beside it, while edits are unsaved or
   the project is not enabled for runs.
   A step line (Task › Workflow › Run › Results) shows where you are.

The entry URLs are `/#home`, `/#workflow`, `/#run` and `/#slow-control`. An old
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

## Edit existing circuit connections

In Workflow builder, select a node to open its inspector. To change a connection,
select a **result** output socket, then a highlighted named input. Press Escape
or right-click to cancel. The inspector offers the same binding choices, including
external inputs such as storage. Only existing inputs can be rewired here.

A large workflow opens zoomed out so every node is visible; **Fit to view**, the
zoom buttons and **Actual size** change only the view. Optional inputs that are
not connected are folded into an "N optional inputs" row on each card; expand it
to connect one. If saved cards overlap, **Arrange view** shows a non-overlapping
layout without changing the file.

Drag a node heading to move it, or focus the heading and use Alt + arrow keys.
These edits stay local until **Review changes** and **Save reviewed source**.
For a bound workflow, choose its matching configured task version and acknowledge
the findings. Prepare a new run on the Run page to check its supported execution profile.
New nodes and optional input changes still use Advanced source.

## Bind a task version

The **Task package and version** panel always states which task package and
version the open workflow uses. Versions are offered only for configured tasks
that declare `task_revision`; otherwise the panel says that none are configured.

In Workflow builder, explicitly choose a configured task package/version and
**Update workflow references**. Inspect the Python diff and task findings, confirm
them and **Save reviewed source**. An unbound reusable workflow requires a separate
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
matching configured choice and use ordinary **Review changes** and Save first.
Choosing a version alone never changes source. Both Professional and Assistant
collaboration use this flow. Saving affects future captures; preparation and launch
remain separate, and existing runs keep their captured binding.

## Prepare saved source or open an existing run

Configure the authored project in `editor_projects`, enable its ID in
`runnable_editor_projects`, and set the task's `reusable_runs_root` to an existing
external runs directory. Include that parent in both
`operation_store.preparation_roots` and `candidate_roots`. Restart after changing
configuration. The source task references and output restrictions must agree with
the configured task; the browser does not rewrite them to match your selection.
See the [reusable configuration contract](console-contract.md#reusable-capture-consumption).

1. Connect and open **Workflow Editor**. Review and **Save** your source edits.
   An already saved supported reusable declaration needs no extra Save. Resolve
   any source conflict before continuing. Select **Next: prepare a run**; the
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
   **Review capture**. Check model routes and credential readiness. Existing runs
   made through Python or CLI can instead be selected from **Prepared run**.
5. Select **Launch captured run** explicitly. This runs Propose → Implement →
   Validate and, when declared, native Tune with the captured inputs. It may call
   paid model APIs and use configured training resources. Current source
   edits remain separate. Follow **Monitor operation** for validation outcome;
   prepared inputs alone do not mean a candidate was accepted.

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
2. Check and start the console with the commands above, then Connect. On Home,
   choose the capture under **Run a configured native chain** and select
   **Review native capture**. Inspect its run name, final iteration, workspace,
   input identities, resource policy and credential readiness. Consult the
   original capture for complete scientific settings.
3. Select **Launch native chain** explicitly. The operation UUID appears before
   submission. Follow **Open native Slow control** to see process state, shell
   outcome, cleanup and each checkpoint's native status and integrity separately.
   A completed process does not establish scientific success; `no_records`,
   unavailable evidence and invalid evidence remain visible. The reported-token
   table covers the whole native run, including continuations.
4. If the response is lost, keep the displayed UUID. Reconnect to check it, or
   use **Retry same native launch** while admission remains unconfirmed. Neither
   navigation nor reconnect launches automatically. Reload the UUID's Slow control
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

For example, if your saved `llm.json` uses OpenAI routes, set
`candidate_environment_names` in that task's `console.json` entry to
`["OPENAI_API_KEY"]`. Set `credential_file` to a private absolute path such as
`/absolute/private/credentials.json`. Its contents have this shape (placeholder
only; replace it privately with your key):

```json
{
  "OPENAI_API_KEY": "REPLACE_WITH_YOUR_PRIVATE_OPENAI_KEY"
}
```

Create the file privately, owned by the user running the console, with mode
`600`, then edit it locally. For an existing file, set that mode with:

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

Select **fit / tuning** in Workflow Editor. The small inspector edits trial/formal
budget minutes, epoch ceilings, portions and retention flags. **Use native default**
removes the key; **None** explicitly stores null where supported. Empty numbers block
review; zero is validated by the native owner. There is no seed setting here: each
run gets one recorded seed at launch. Epoch ceilings constrain native planning
rather than specifying final epochs. Outer candidate timeout remains seconds.

Review shows inherited values and supplied parameter rules. Edit advanced controls
and rules in Source; unrelated inspector changes preserve them. Review and Save,
then use **New run** and **Launch captured run** as described above. Each capture
keeps its own settings; edits affect future captures.

External Health configuration files are not captured by reusable training.
Task-composed Health and native startup controls remain available. After completion,
inspect scores, Health and termination reason in the
[native outputs](../candidate_worker/README.md); completion means the tuner returned.
See the [contract](console-contract.md) for exact field semantics and qualification limits.
