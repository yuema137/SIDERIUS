# Run one native candidate

This developer tool runs one proposal → implementation → validation chain, optionally followed by native training, in a
fresh workspace and leaves the native node records for inspection. Python and
the synchronous CLI use the same launch boundary. It requires Linux,
[bubblewrap](../workspace_sandbox/README.md), an installed SIDERIUS environment,
and an explicitly prepared native proposal seed.

To compare multiple implementations of one proposal, an advanced caller can select
[the proposal-fanout profile](candidate-worker-contract.md#opt-in-proposal-fanout).
Each implementation gets its own native files and validation. Prepare the explicit
declaration and storage inputs using that contract, then submit through the same
[candidate operation interface](../candidate_operations/README.md). Terminal status
includes the verified per-instance trace. This profile has no training, graph
resume or visual graph editor.

To generate several independent proposal candidates in one run, code callers can
select [proposal families](candidate-worker-contract.md#opt-in-independent-proposal-families)
and supply one native seed per declared proposer. Each family has isolated files
and a verified trace. Execution is serial; this does not aggregate or rank results.
Reusable source/GUI preparation does not yet support this profile.

For a first experiment, use [candidate preparation](../candidate_prepare/README.md)
to build the seed, storage and launch request from task/data/profile selections
without provider calls. The manual path below is for callers that already own
complete native input records.

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
[installation instructions](../../../docs/getting-started/installation.md#api-keys).
The request carries variable names, never credential values. Launch from this
checkout's frozen environment:

```bash
.venv/bin/python -m tools.candidate_worker --request /projects/my-task/candidate_request.json
```

The equivalent Python call is `launch_candidate(request)`. Inspect
`<workspace>/candidate_run/receipt.json` and `worker.log`; the receipt identifies
the native output files and usage-ledger location. `accepted`
and `rejected` both mean candidate validation completed, and the CLI exits zero
for both. Check `validation_passed` before treating the candidate as accepted.
Four-stage `completed` also exits zero; it means the tuner returned. Failure,
timeout and interruption exit nonzero. An absent terminal receipt means completion
is unknown; the workspace is preserved and cannot be automatically replayed.

You can read reported LLM tokens while or after a direct run, without an operation
store or console. Use the run ID from its launch receipt and an existing allowed
root containing the workspace:

```python
from tools.candidate_worker import CandidateTokenReadRequest, read_candidate_tokens

snapshot = read_candidate_tokens(CandidateTokenReadRequest(
    allowed_workspace_root="/projects/my-task",
    workspace="/projects/my-task/workspace",
    expected_run_id="RUN_ID_FROM_LAUNCH",
))
print(snapshot.model_dump_json(indent=2))
```

This read performs no provider calls or task execution. Groups preserve requested
and served model identity. Each token field sums only the values actually reported;
missing values remain null with a missing-row count. An empty table means no
reported responses were observed. Partial evidence is labeled, and missing usage
does not establish zero billing. For a code-submitted operation UUID, use the
[operation reader or console](../candidate_operations/README.md).

A fresh workspace generates a new candidate through native eligibility rules.
Merely declaring a model plugin does not make it an already validated reuse
offer. This tool does not seed a capability index, invent descriptions or tests,
or promote candidates. The three-stage mode stops at validation; the four-stage
mode below trains and scores through the native tuner. Neither mode adds an outer
iteration loop, resumes a run, or prepares the seed for you. Native schema/provider retries can make more than one request;
the worker timeout bounds the entire child process, not API cost or memory.
See the [execution contract](candidate-worker-contract.md) for exact checks,
artifact ownership, provenance and limitations.

## Add native training

The four-stage API accepts a training settings file beside a matching proposal
seed. Start with the portable [synthetic input example](../../../examples/workflow_declarations/native_training.py).
Generate the [Quickstart data](../../../examples/quickstart/README.md) first, then
write inputs into an external directory separate from both data and workspace:

```bash
.venv/bin/python examples/workflow_declarations/native_training.py \
  --project /projects/native-inputs \
  --data /projects/quickstart-data \
  --workspace /projects/native-run
```

This writes `settings.json`, `seed.json`, `storage.json`, `workflow.json`,
`llm.json` and `candidate_request.json`; it makes no provider calls and starts
no training. Edit the example's typed settings and seed together before
generating a new request. In particular, an explicit null budget in an existing
seed cannot be replaced by a non-null settings budget. The example declares
two trial minutes and five formal minutes, diagnostic results and explicit
`native-timing-v1` planning; these are demonstration choices. Review `llm.json`,
resource limits and the captured routes before using the launch command above.

A four-stage `completed` receipt means the native tuner returned. Inspect the
fourth output file for scores, Health results and termination reason before
judging the result. Infrastructure aborts return `failed` and retain that file.
The model directory contains native run settings, records and any requested
retained outputs. Independent operation reads detect missing or replaced native
output after completion. Existing three-stage requests and receipts keep their
serialization. Reusable source and GUI callers can also prepare four-stage requests
with [source-owned settings](../candidate_console/README.md#edit-reusable-training-settings);
preparation derives the matching seed. Direct v1 callers still own seed/settings consistency. See the
[training contract](candidate-worker-contract.md#fresh-native-training-schema-version-1)
for supported controls, inactive defaults and integrity boundaries.
