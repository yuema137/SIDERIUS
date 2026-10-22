# Run one native candidate

This developer tool runs one proposal → implementation → validation chain in a
fresh workspace and leaves the native node records for inspection. Python and
the synchronous CLI use the same launch boundary. It requires Linux,
[bubblewrap](../workspace_sandbox/README.md), an installed SIDERIUS environment,
and an explicitly prepared native proposal seed.

Prepare a [supported workflow document](../workflow_preview/preview-contract.md#example-document),
its complete `ProposalInput` JSON, and its protocol storage JSON in your external
project. The seed must match the selected task composition and physical data
root. The downstream storage file must name
`<workspace>/<run_name>/iteration_001/attempt_001/impl_001`. A seed that omits
`storage` will receive managed proposal storage when you explicitly select
`managed_fresh` below. An explicitly supplied storage must already agree.

Inspect the workflow with [workflow preview](../workflow_preview/README.md) and
save both its request and report. Construct the launch request from those
reviewed observations. In the linked layout, `project/workspace` is writable,
while `project/task.yaml`, `proposal.json`, `storage.json` and `data/` are separate
read-only inputs. Mount those selected paths individually. Any additional task
code, profiles or dependencies need their own canonical read-only paths that do
not contain the workspace; do not mount the whole project as read-only.

```python
from pathlib import Path

from tools.candidate_worker import CandidateRunRequest
from tools.workflow_preview.models import WorkflowPreview, WorkflowPreviewRequest

project = Path("/projects/my-task")  # Your external project, outside SIDERIUS.
preview_request = WorkflowPreviewRequest.model_validate_json(
    (project / "preview_request.json").read_bytes()
)
reviewed = WorkflowPreview.model_validate_json((project / "preview.json").read_bytes())
request = CandidateRunRequest(
    preview=preview_request,
    declaration_digest=preview_request.document.definition.declaration_digest(),
    files=reviewed.files,
    selected_constructor_routes=reviewed.selected_constructor_routes,
    storage_policy="managed_fresh",
    run_name="candidate",
    timeout_seconds=600.0,
    network=True,  # Explicit permission for the configured remote providers.
    devices=(),
    read_only=(
        reviewed.data_root,
        *(item.path for item in reviewed.files),
        # Add canonical task code/profile/dependency paths here when required.
    ),
    environment_names=("OPENAI_API_KEY",),  # Names required by your selected providers.
)
(project / "candidate_request.json").write_text(request.model_dump_json(indent=2))
```

Use credentials from your machine-owned launch environment, following the
[installation instructions](../../../../docs/getting-started/installation.md#api-keys).
The request carries variable names, never credential values. Launch from this
checkout's frozen environment:

```bash
.venv/bin/python -m tools.candidate_worker --request /projects/my-task/candidate_request.json
```

The equivalent Python call is `launch_candidate(request)`. Inspect
`<workspace>/candidate_run/receipt.json` and `worker.log`; the receipt identifies
the three native output files and the native usage-ledger location. `accepted`
and `rejected` both mean candidate validation completed, and the CLI exits zero
for both. Check `validation_passed` before treating the candidate as accepted.
Other terminal statuses exit nonzero. An absent terminal receipt means completion
is unknown; the workspace is preserved and cannot be automatically replayed.

A fresh workspace generates a new candidate through native eligibility rules.
Merely declaring a model plugin does not make it an already validated reuse
offer. This tool does not seed a capability index, invent descriptions or tests,
or promote candidates. It also does not train, score, iterate, resume or prepare
the seed for you. Native schema/provider retries can make more than one request;
the worker timeout bounds the entire child process, not API cost or memory.
See the [execution contract](candidate-worker-contract.md) for exact checks,
artifact ownership, provenance and limitations.
