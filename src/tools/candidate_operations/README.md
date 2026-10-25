# Run a candidate operation independently of your terminal command

Submit an existing [preparation request](../candidate_prepare/README.md) or
[candidate request](../candidate_worker/README.md), let the command exit, and
inspect its result later. Preparation and candidate execution remain separate
choices. Candidate execution can call providers and execute generated code.

Use Linux, bubblewrap and this checkout's synced `.venv/bin/python`. Keep the
operation in a persistent user session or service: detaching a process does not
protect it from host reboot or a session manager that kills all processes on
logout. Follow the [credential binding instructions](../../../docs/getting-started/installation.md#api-keys)
before candidate execution.

1. Create separate external directories for prepared bundles and candidate
   workspaces. Save `store.json` with their canonical absolute paths and an
   absent state directory whose parent already exists:

   ```json
   {
     "state_root": "/absolute/external/operations",
     "preparation_roots": ["/absolute/external/bundles"],
     "candidate_roots": ["/absolute/external/runs"]
   }
   ```

   Native output paths must be descendants of their configured roots. State
   must be separate from inputs, outputs and framework code. New state is private;
   existing state directories must belong to you and have mode `0700`.

2. Wrap your existing native request JSON in a submission. Choose `prepare`, `prepare_reusable` or
   `candidate` explicitly. This example reads `native-request.json` and writes
   `submission.json`:

   ```sh
   .venv/bin/python - <<'PY'
   import json
   from pathlib import Path
   from uuid import uuid4
   envelope = {
       "kind": "prepare",
       "request_id": str(uuid4()),
       "request": json.loads(Path("native-request.json").read_text()),
   }
   Path("submission.json").write_text(json.dumps(envelope))
   PY
   .venv/bin/python -m tools.candidate_operations submit \
     --store-config store.json --request submission.json
   ```

   Save the returned `operation_id`. Exit zero means the request was admitted
   or already exists; inspect its status to learn the native outcome. Resubmitting
   identical JSON with the same ID returns the same operation without running it
   again. Different content with that ID is refused.

3. Reopen the result and read a bounded log chunk:

   ```sh
   .venv/bin/python -m tools.candidate_operations status \
     --store-config store.json --operation-id OPERATION_UUID
   .venv/bin/python -m tools.candidate_operations log \
     --store-config store.json --operation-id OPERATION_UUID \
     --kind native --offset 0 --limit 65536
   ```

   For preparation and candidate kinds, `completed` means a validated native receipt exists. Read `receipt.status`:
   preparation can be `prepared`, while a candidate can be `accepted` or
   `rejected`; both can fail, time out or be interrupted. Acceptance means native
   candidate validation passed, not training or scientific scoring. A direct
   [four-stage candidate request](../candidate_worker/README.md#add-native-training)
   can instead return native `completed`: the tuner returned, which does not
   establish scientific validity. Read its native output for scores and Health
   results. To execute a
   legacy prepared bundle, review its `candidate_request_path`, wrap that file with
   `kind: "candidate"` and a new UUID, then submit explicitly.

## Prepare a reusable workflow in the background

Create a [reusable preparation request](../candidate_prepare/README.md#prepare-several-runs-from-one-workflow)
from your saved workflow. Include its runs directory in both root lists in
`store.json`; each run contains sibling `inputs/` and `workspace/` directories.
Keep operation state separate. Wrap the request as shown above, using
`"kind": "prepare_reusable"` and a fresh operation UUID, then save and submit it.
The command returns after dispatch. Preparation captures saved source and runs
trusted task composition offline; it does not launch a candidate or need provider
credentials.

Use the same status and log commands. Success is `state: "completed"` with
`receipt.status: "prepared"`; `receipt.envelope` identifies the capture to review
in the steps below or in the console's existing prepared-run selector. Failed,
timed-out and interrupted preparations can also be `completed`, so check the
native status. Missing or contradictory evidence is `unknown`.

Retain the original submission for recovery. Resubmitting it with the same UUID
returns the admitted operation even if source/configuration files disappear; it
does not prepare again. New preparations need fresh operation and run UUIDs.
Python integrations can bind a reviewed set of source/configuration bytes using
the [typed expectation and recovery API](candidate-operations-contract.md#detached-reusable-preparation).
Create the preparation request through Python or the CLI; the console can monitor
this operation UUID.

## Run a prepared reusable workflow

First [prepare your reusable workflow](../candidate_prepare/README.md#prepare-several-runs-from-one-workflow).
Each prepared run has its own directory with captured source, inputs and a future
workspace. You can launch that capture even after editing your source for future
runs. The operation checks that the selected capture and native inputs still agree.

1. In `store.json`, include your runs directory in both `preparation_roots` and
   `candidate_roots`: the prepared inputs and future workspace are siblings inside
   each run directory. Keep `state_root` separate.
2. Use `select_reusable_preparation` and `build_reusable_operation`, following the
   [Python construction recipe](candidate-operations-contract.md#shared-python-and-cli-recipe),
   to select the reported prepared directory and save `reusable-submission.json`
   outside it. Your coding assistant or integration can do this immediately after
   preparation. Review the selected task, workspace, nodes, provider routes and
   execution limits. These describe the captured workflow; current source edits
   belong to later runs.
3. Bind the chosen credentials and submit:

   ```sh
   .venv/bin/python -m tools.candidate_operations submit \
     --store-config store.json --request reusable-submission.json
   ```

Use the status and log commands above with the returned operation ID. If the
response is lost, resubmit the saved file unchanged: the same operation is
returned without a second execution, even if preparation files later disappear.
Changed preparation files refuse a new launch. Preserve run artifacts so status
readers can continue to verify the native result.

`prepared` means inputs exist; `starting` means an operation was admitted. A later
native `accepted` means candidate validation passed and proposal, implementation
and validation outputs are available. It does not mean training or scientific
scoring ran. Professional and Assistant use this same Python/CLI route. Reusable
capture launch uses the console’s prepared-run selector; resuming a previous run
is not available through this route.

For reported LLM tokens, Python callers can use the same stored operation UUID:

```python
from pathlib import Path
from uuid import UUID
from tools.candidate_operations import OperationStoreConfig, read_operation_tokens

config = OperationStoreConfig.model_validate_json(Path("store.json").read_bytes())
snapshot = read_operation_tokens(config, UUID("YOUR_OPERATION_UUID"))
print(snapshot.model_dump_json(indent=2))
```

Replace the UUID with your submitted operation ID. Candidate results group the
observed provider reports by requested and served model; preparation returns
not applicable. Missing fields remain null, partial reads are labeled and repeated
reads replace the snapshot. Missing or unrecorded usage may exist; these sums do
not establish complete billing. You can also paste a code-submitted operation ID
into the [local console](../candidate_console/README.md) to see the table, status
and logs. No matching console task choice is needed for known-ID monitoring;
use the same admitted operation store configuration.

Only one operation may occupy a store. `active` means its wrapper process was
observed alive. `unknown` means evidence is insufficient; it blocks new admission
and is never automatically retried. A new operation cannot reuse an older
operation's receipt at the same output path. Preserve the records for investigation.
A completed operation also keeps its slot until its process is observed exited.
There is no cancellation, queue or recovery command.

Use `--kind operation` for wrapper output. Logs and full native receipts are
trusted local data and may contain sensitive task or plugin output. Byte cursors
advance using `next_offset`; chunks can split UTF-8 characters. An offset beyond
the current file size reports truncation and restarts at zero. Same-size log
replacement cannot be detected by this cursor. The
[technical contract](candidate-operations-contract.md) defines integrity checks,
credential limits and deployment boundaries.

## Run a captured native chain

For a captured native chain, first create a dedicated empty envelope under an
allowed candidate root. Declare its absent `workspace` child in the native-chain
source and create the capture using the [native-chain route](../native_chain/README.md).
The outer directory is the envelope; the native shell creates its `workspace`
child. Ask your coding agent to use the
[complete construction recipe](candidate-operations-contract.md#construct-a-native-chain-operation)
to generate `chain-operation.json` outside the envelope. Review the capture path,
task-input and data directories, timeout, observation limits and sandbox access
with it. The recipe reads the reviewed capture and prepares the operation identity
automatically.

Reuse that saved JSON for retries; do not generate a new request to recover a lost
submission response. For real provider routes, select the required credential
names and bind their values using the credential instructions above.

The sandbox must observe the same hardware facts as the capture. If the reviewed
runtime requires GPU visibility, select the required character devices under
`/dev` and read-only `/sys` access. Empty device access works only when that
captured runtime can be verified without those devices. The operation adapter
supplies the exact checkout, interpreter and Git metadata access.

Review and submit the saved request:

```sh
.venv/bin/python -m tools.candidate_operations review --store-config store.json --request chain-operation.json
.venv/bin/python -m tools.candidate_operations submit --store-config store.json --request chain-operation.json
```

Retain the request UUID for retries. Existing status and log commands keep working
after submission exits. Read shell outcome, cleanup and checkpoint verification
separately: a completed process is not a scientific success. The native shell
schedules iterations; this route does not resume existing workspaces. See the
[operation contract](candidate-operations-contract.md#captured-native-chain-operation)
for request fields, byte limits, recovery and evidence meanings.
