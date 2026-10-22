# Preview a candidate chain

Use this tool to see which local files and model routes a workflow declaration
selects before building an execution integration. It reads files and returns a
report; it does not create the workspace, load task plugins or call a model.

You need an installed SIDERIUS environment and a
[workflow document](../../workflows/definition/README.md) containing exactly one
proposal → implementation → validation chain. The proposal request comes from
an external file; the other two nodes use the native connecting protocols.
A structurally valid document with a different shape is unsupported by this
preview. See the [complete example](preview-contract.md#example-document).

1. Put the document and its referenced files in your external project. For example:

   ```text
   /projects/my-task/
     workflow.json
     task.yaml
     proposal.json
     storage.json
     llm.json
     data/
   ```

   Declare `task.yaml`, `data`, and `workspace` as the task locations. The
   workspace can be absent or empty. Set the external request and storage
   locations to `proposal.json` and `storage.json`.

2. Call the same preview function from Python or with a JSON-decoded request:

   ```python
   from pathlib import Path
   from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
   from workflows.definition import WorkflowDocument

   project = Path("/projects/my-task")  # Change this to your project's absolute path.
   document = WorkflowDocument.model_validate_json(
       (project / "workflow.json").read_text()
   )
   request = WorkflowPreviewRequest(
       document=document,
       project_root=str(project),
       llm_config_file="llm.json",
   )
   # A GUI or other JSON caller decodes the same request type:
   request = WorkflowPreviewRequest.model_validate_json(request.model_dump_json())
   report = preview_workflow(request)
   print(report.model_dump_json(indent=2))
   ```

3. Check `files`, `selected_constructor_routes`, and `pending_checks`. In this
   example, `task.yaml` resolves to `/projects/my-task/task.yaml` even if Python
   starts elsewhere. Route names combine your node ID with its stage, such as
   `candidate.reasoning` or `coder.main`. `inactive_roles` lists the native roles
   outside this preview, whether or not your config supplies them.

Edit `llm.json` to select the three roles' models. Omitting `llm_config_file`
selects the framework's first-run configuration; an explicit partial file keeps
native fallbacks for omitted roles. File content observations describe what was
read during this call; they do not lock a later run to those bytes.

A successful report has `status="bindings_observed"` and always has
`execution_ready=false`. The manifest and external payloads remain opaque:
conflicting task, storage or model values inside them have not been reconciled.
Read the [preview contract](preview-contract.md) for checks still required before
execution and the precise file, configuration and routing rules.
