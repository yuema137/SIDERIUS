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

2. Wrap your existing native request JSON in a submission. Choose `prepare` or
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

   `completed` means a validated native receipt exists. Read `receipt.status`:
   preparation can be `prepared`, while a candidate can be `accepted` or
   `rejected`; both can fail, time out or be interrupted. Acceptance means native
   candidate validation passed, not training or scientific scoring. To execute a
   prepared bundle, review its `candidate_request_path`, wrap that file with
   `kind: "candidate"` and a new UUID, then submit explicitly.

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
