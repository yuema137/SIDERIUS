# Local candidate console

Prepare, review and explicitly launch one candidate from a configured scientific
task, or launch an externally reviewed native iteration chain. Reopen status and
logs and reported LLM tokens by operation ID, or view an explicitly configured
read-only candidate-validation example.
The candidate runs Propose → Implement → Validate, with optional native Tune
when the saved reusable source declares it. Inspect native outputs for scientific
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

1. Create separate preparation and candidate output directories. Write an absolute
   path configuration file using the [configuration example](console-contract.md#configuration).
   Select the existing task manifest, data directory, LLM profile, resource policy
   and time limits there. All resource paths must be absolute and canonical,
   without symlinks. Create the output parents, but leave per-operation child
   directories for the console to create. Browser users can change the native
   run name and three advice fields.
2. Create the access token file at the path selected by `auth_token_file`:

   ```bash
   .venv/bin/python -c 'import os,secrets; p=input("Token file absolute path: "); fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(fd,secrets.token_urlsafe(32).encode()); os.close(fd)'
   ```

   This token unlocks the console; it is separate from any model provider API key.
   Follow [Credentials](#credentials) below to bind provider keys before Launch.
3. Check the configuration, then start the server in a persistent terminal/session:

   ```bash
   .venv/bin/python -m tools.candidate_console check --config /absolute/project/console.json
   .venv/bin/python -m tools.candidate_console serve --config /absolute/project/console.json
   ```

   A successful check prints the browser address and token file location. It
   checks configuration paths, file shape and permissions, without proving task
   composition, required key presence, sandbox availability or provider access.
   Only `127.0.0.1` binding is supported.
4. For a remote host, keep the server session running and open an SSH tunnel:

   ```bash
   ssh -N -L 127.0.0.1:8740:127.0.0.1:8740 YOUR_HOST
   ```

   Open `http://127.0.0.1:8740`. If the local forwarding port differs, configure
   `browser_origin` to that exact local address before starting the server.
5. Open **Home**, paste the console token, and select **Connect**. The connection
   stays available while you switch between Home, Workflow Editor and Slow control,
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
   Configured **Recorded examples** appear in Slow control. They show verified
   proposal, implementation, validation and reported-token evidence only; they
   are not live operations, training results, scientific scores or billing
   records. Configure `recorded_examples` only for fixed canonical workspaces
   under `operation_store.candidate_roots`, with the expected native run ID.
   The view has no operation import or execution controls, and a missing saved
   source is shown as unavailable.
8. To author a configured declaration, choose **Workflow Editor**. Select a node
   to inspect its supported bindings; expand **References** for task and external
   locations, or **Advanced → Source** for exact Python bytes. Review opens the
   exact diff; Save writes those reviewed bytes. Switching views retains pending
   edits and review state. A real page exit with pending edits uses the browser's
   unsaved-change guard. Saving does not run the declaration.
   The **Research loop** panel adds or removes the loop, its iteration limit and its stop conditions.
   For reusable task packages, [bind a task version](#bind-a-task-version) first.

The entry URLs are `/#home`, `/#workflow` and `/#slow-control`. An old
`/editor.html` link redirects to `/#workflow` before asking for credentials.
Connection sharing applies within one document; separate tabs/windows connect
independently.

## Edit existing circuit connections

In Workflow builder, select a node to open its inspector. To change a connection,
select a **result** output socket, then a highlighted named input. Press Escape
or right-click to cancel. The inspector offers the same binding choices, including
external inputs such as storage. Only existing inputs can be rewired here.

Drag a node heading to move it, or focus the heading and use Alt + arrow keys.
These edits stay local until **Review changes** and **Save reviewed source**.
For a bound workflow, choose its matching configured task version and acknowledge
the findings. Prepare a new run separately to check its supported execution profile.
New nodes and optional input changes still use Advanced → Source.

## Bind a task version

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
   any source conflict before continuing.
2. In **New run**, explicitly choose the configured task and resources, enter a
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
later editor changes. Resume is not available in this reusable GUI flow.

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
| `credential_file` | JSON object of string names and values | Supply selected provider keys and other declared runtime variables to a candidate |

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

Use only the keys required by your selected providers, plus any other explicitly
declared runtime variables. The current credential variable names are
`OPENAI_API_KEY`, `GEMINI_API_KEY` and `DEEPSEEK_API_KEY`. Match the names in the private JSON file
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
project `.env` do not satisfy this console binding. Downstream dotenv loading is
legacy compatibility, not a setup step or a reliable credential source.
Preparation is offline and does not need provider keys.

Restart the server after changing `console.json`, including task paths, model
profile selection, resource policy, allowed names or private-file paths. Such
changes can require a fresh Prepare. Updating values at the same credential-file
path takes effect on the next Launch without restart; the file must still pass
the private-file checks. For a changed model profile, prepare and review again
before launching.

For direct CLI or coding-agent launches, use the separate
[API-key procedure](../../../docs/getting-started/installation.md#api-keys):
trusted shell-compatible external files or managed environment injection are
supported there. Console JSON is not a shell/dotenv file.

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
budget minutes, epoch ceilings, portions, sampling seed, training base seed and
retention flags. **Use native default** removes the key; **None** explicitly stores
null where supported. Empty numbers block review; zero is validated by the native
owner. Sampling and training seeds are independent. Epoch ceilings constrain native
planning rather than specifying final epochs. Outer candidate timeout remains seconds.

Review shows inherited values and supplied parameter rules. Edit advanced controls
and rules in Source; unrelated inspector changes preserve them. Review and Save,
then use **New run** and **Launch captured run** as described above. Each capture
keeps its own settings; edits affect future captures.

External Health configuration files are not captured by reusable training.
Task-composed Health and native startup controls remain available. After completion,
inspect scores, Health and termination reason in the
[native outputs](../candidate_worker/README.md); completion means the tuner returned.
See the [contract](console-contract.md) for exact field semantics and qualification limits.
