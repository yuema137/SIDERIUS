# Local candidate console

Prepare, review and explicitly launch one candidate from a configured scientific
task, then reopen its native status, logs and reported LLM tokens by operation ID.
The candidate runs Propose → Implement → Validate. This page does not train models or report scientific
scores.

You need a synced checkout, a working [workspace sandbox](../workspace_sandbox/README.md),
an existing task manifest, data directory and LLM profile. Keep configuration,
credentials and outputs in your external project. Run commands from this checkout
using its own `.venv/bin/python`.

1. Create separate preparation and candidate output directories. Write an absolute
   path configuration file using the [configuration example](console-contract.md#configuration).
   Select the task paths, profile, resource policy and time limits there. Browser
   users can change the native run name and three advice fields.
2. Create the access token file at the path selected by `auth_token_file`:

   ```bash
   .venv/bin/python -c 'import os,secrets; p=input("Token file absolute path: "); fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(fd,secrets.token_urlsafe(32).encode()); os.close(fd)'
   ```

   If the profile needs provider credentials, place the required name/value pairs
   in the configured `credential_file`, a JSON string map with owner-only mode 600.
   Never put secrets in command arguments or the console configuration.
3. Check the configuration, then start the server in a persistent terminal/session:

   ```bash
   .venv/bin/python -m tools.candidate_console check --config /absolute/project/console.json
   .venv/bin/python -m tools.candidate_console serve --config /absolute/project/console.json
   ```

   A successful check prints the browser address and token file location. It does
   not test provider access or task execution. Only `127.0.0.1` binding is supported.
4. For a remote host, keep the server session running and open an SSH tunnel:

   ```bash
   ssh -N -L 127.0.0.1:8740:127.0.0.1:8740 YOUR_HOST
   ```

   Open `http://127.0.0.1:8740`. If the local forwarding port differs, configure
   `browser_origin` to that exact local address before starting the server.
5. Paste the token from your private file into the page. Select a task, fill the
   run name/advice, and click **Prepare**. Review the task, paths, models and
   resource policy. **Launch candidate** starts code execution and may call paid
   APIs. Preparation never launches automatically.
6. Copy the operation ID to reopen status, logs and the **Reported LLM tokens**
   table later, including operations created through Python or the operation CLI. Reenter the token after reload;
   the page retains IDs but does not store the token.

The table groups provider reports by requested and served model. A missing field
shows **Unavailable**; a known value shows its reported sum and any missing-row
count. Partial or stale observations remain labeled. These are observed provider
reports; missing or unrecorded usage may exist, so the table does not establish
complete billing. Preparation has no applicable token table. Known operation IDs
can be read even when the current task choices differ; the admitted operation
store configuration must still match. Direct runs without an operation ID use the
[native Python reader](../candidate_worker/README.md).

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
review/save flow. Saving a declaration does not change what native Prepare executes.
Existing console configurations need no editor project to monitor operations.
