# Prepare one native candidate

Select an existing task, its data directory and an LLM configuration. This tool
builds the native inputs for a first proposal without calling an LLM. It saves a
bundle that you can inspect and then launch with the [candidate worker](../candidate_worker/README.md).
Python and the CLI call the same operation.

You need Linux with [bubblewrap](../workspace_sandbox/README.md), this checkout's
frozen Python environment, and an existing task package. Keep data, bundles and
run workspaces outside SIDERIUS. The bundle and future run directories must be
absent, have existing parents, and be separate from each other and all inputs.

1. Save your selections as `/projects/my-task/prepare.json`. Replace these
   example paths with canonical absolute paths. `task_read_only` lists the task
   code and dependencies needed by composition and later execution; those paths
   must not contain either output directory.

   ```json
   {
     "task_manifest": "/projects/my-task/package/task.yaml",
     "data_root": "/datasets/my-task",
     "llm_config_file": "/projects/my-task/llm.json",
     "output_dir": "/projects/my-task/bundle-001",
     "candidate_workspace": "/runs/my-task/candidate-001",
     "run_name": "candidate",
     "preparation_timeout_seconds": 60.0,
     "candidate_timeout_seconds": 600.0,
     "task_read_only": ["/projects/my-task/package"],
     "candidate_network": true,
     "candidate_devices": [],
     "candidate_environment_names": ["OPENAI_API_KEY"],
     "proposal_advice": "State the hypothesis clearly.",
     "implementation_advice": null,
     "validation_advice": null
   }
   ```

   Select environment names for the providers in your saved LLM configuration;
   never put credential values in this file. The `candidate_*` fields describe
   the later worker. Preparation always runs without network, devices or passed
   credentials. Its separate timeout bounds the preparation child only.
   Optional `allowed_output_types` restricts proposals to `classifier`,
   `regressor`, or both; omission leaves the native policy unconstrained.

2. Prepare from the installed checkout:

   ```bash
   .venv/bin/python -m tools.candidate_prepare --request /projects/my-task/prepare.json
   ```

   The equivalent Python call is
   `prepare_candidate(CandidatePreparationRequest.model_validate_json(payload))`.
   Preparation runs trusted task imports and composition in a sandbox. Source
   and selected data are mounted read-only; that code can read them. The
   preparation operation requests no data decoding, training or scoring.

3. Check `bundle-001/preparation/receipt.json`. Success is `status: "prepared"`
   and CLI exit zero. Inspect `interpretation.json`, `proposal.json`,
   `preview.json` and `candidate_request.json`. The interpretation explicitly
   contains no prior experiments. The proposal uses the task's declarations,
   native advice handling and the configured reasoning pipeline. The exact
   interpretation input is saved under `preparation/interpretation_input.json`.
   The future run directory remains absent.

4. When you choose to execute, provide the selected credentials through your
   [machine-owned launch environment](../../../../docs/getting-started/installation.md#api-keys)
   and invoke the worker separately:

   ```bash
   .venv/bin/python -m tools.candidate_worker --request /projects/my-task/bundle-001/candidate_request.json
   ```

`prepared` means the inputs were assembled; it does not mean a candidate was
accepted, providers are available, or training resources and costs were approved.
The preview still reports `execution_ready: false`. The worker rechecks inputs
and native task identity before using them. A timeout, interruption or failure
preserves partial files and diagnostics in `preparation/worker.log` when the child
started. Missing terminal receipt means completion is unknown. Choose new output
and run paths for another attempt; this tool does not overwrite or resume bundles.

See the [technical contract](candidate-prepare-contract.md) for exact fields,
artifact ownership and the limits of source identity checks.
