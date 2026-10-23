# Capture a native chain

This tool records the settings selected by the native shell launcher. It checks
the task in an isolated process and saves a capture without running an iteration.
Use a clean checkout with its own environment (`uv sync --group dev --frozen`),
a working bubblewrap sandbox, and external directories for inputs, data and runs.

1. In your external project, save a declaration JSON with `working_directory`
   set to the absolute checkout path, `run` containing `workspace`, `run_name`
   and `final_iteration`, and `chain_args` containing the native scientific CLI
   tokens. For example, `chain_args` can contain `--task_composition`, its path,
   `--data_dir`, and the separate data directory path. The workspace must not exist.
2. Save a request JSON containing `source` (the declaration path), `output`
   (a new review directory), `read_only` (task code/configuration roots),
   `task_check: {"timeout_seconds": 60}`, and `input_max_bytes: 16777216`.
   Use canonical absolute paths; create each destination's parent first.
3. From the selected checkout, run:

   ```bash
   .venv/bin/python -m tools.native_chain review --request /external/project/request.json
   ```

Success publishes `capture.json` last in the review directory. Failed checks can
leave diagnostic reports there; choose a new output path after correcting inputs.
The original declaration and configuration files remain authoritative: changing
them invalidates the capture. Copied bytes are an audit record, not portable replay.
Data contents, credentials and successful scientific execution are not certified.

See [the contract](native-chain-contract.md) for the typed boundary and limitations.

To launch the captured chain, use exactly `shell_argv` from `capture.json` as
arguments to `bash scripts/launch/run_chain.sh`, then add:

```text
--expected_chain_capture /external/review/capture.json
--expected_chain_capture_sha256 <SHA-256 of that file's exact bytes>
--chain_capture_input_max_bytes 16777216
```

Keep the same input limit as the review request. Run from the captured checkout.
Add `--dry-run` to verify and print commands without creating run artifacts.
The launcher checks the capture before the first dispatch and again before each
iteration. It also checks the settings actually resolved inside each native
child before agent work. A mismatch exits 78 and stops the chain; earlier
iterations remain intact. An in-child mismatch may leave an iteration directory
or token file. Existing workspaces, including empty ones, require a different
launch route; captured mode does not resume them.
