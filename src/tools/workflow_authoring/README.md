# Edit an ordinary workflow file

Open a dedicated `workflow.py`, edit its supported declaration in the console,
review the Python diff, and save back to the same file used by your coding agent.
This editor checks declaration structure. It does not execute a workflow or check
whether referenced manifests, data or plugins exist.

1. Keep the file in your external project. Use the restricted Python format
   supported by [workflow definitions](../../workflows/definition/README.md).
   The source must be UTF-8, at most 32 KiB, owned by the current user and a regular
   file. Symlinks, hardlinks and special permission bits are unsupported.
2. Create an existing owner-only recovery directory inside the same project,
   separate from preparation and candidate output directories:

   ```bash
   mkdir -m 700 /absolute/project/editor-recovery
   ```

3. Add an optional `editor_projects` entry to your existing
   [console configuration](../candidate_console/README.md):

   ```json
   {
     "editor_projects": [{
       "project_id": "my-project",
       "project_root": "/absolute/project",
       "source_file": "/absolute/project/workflow.py",
       "recovery_directory": "/absolute/project/editor-recovery"
     }]
   }
   ```

   This is an addition to the console's other required fields. All three paths
   must be explicit absolute paths with existing parents. Restart the console
   after changing its configuration.
4. Follow **Workflow Editor** from the console, enter its access token and choose
   a project. Select a node to edit a supported binding, or edit task/external
   locations. The Python panel also accepts supported source changes, including
   adding nodes. Click **Save** to validate the graph; a save row opens (with
   Settings › Show advanced tools it also shows the exact generated Python diff).
   After inspector edits, press **Save** (then **Cancel**) first to update
   the Python panel before typing source changes. Inspector changes can rewrite formatting and
   comments; the diff shows that rewrite. The **Research loop** section of Selection adds or
   removes the research loop, its iteration limit and stop conditions; a loop your
   coding agent wrote in `workflow.py` appears there, and the diff shows the
   resulting Python.
5. In the save row, keep the suggested **Version name** (`v1`, `v2`, ...) or type your own, then
   click **Save version**. Success means the reviewed bytes were saved
   and read back, and `workflow.py.versions.json` beside the source records the
   name, time and SHA-256. **Version history** lists saved versions, marks the
   current one and opens each read-only with its diff from the previous one. Exact previous/proposed bytes are kept as separate
   recovery copies; the ordinary `workflow.py` remains authoritative. Its
   ordinary permission bits are preserved.
6. After your coding agent edits that file normally, click **Refresh from disk**.
   Refresh asks before discarding pending edits. If source changed before Save,
   inspect the conflict and either discard your edits or explicitly choose the
   current source as the base, reconcile your proposal, review and save again.
   A second source change causes another refusal.

API clients can use `WorkflowAuthoring(Project(...))` with typed `ReviewRequest`
and `SaveRequest` from `models.py`. Saves serialize clients using the same adjacent
advisory lock. Ordinary editors do not take that lock: an external write after the
last comparison can be overwritten and may be missing from recovery copies.
Use trusted local project directories. A lost connection leaves a save unconfirmed
until you inspect disk again. See the [authoring contract](authoring-contract.md)
for exact limits, refusals and concurrency behavior.
