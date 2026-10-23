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
   [machine-owned launch environment](../../../docs/getting-started/installation.md#api-keys)
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

## Prepare several runs from one workflow

Use this route when you want to keep one authored workflow and create a fresh
set of inputs for each run. Both Professional users and coding assistants use
`prepare_reusable_candidate` or the same `--reusable-request` CLI. The assistant
helps write your external project files; it does not use a different backend.

1. Copy the [managed reusable example](../../../examples/workflow_declarations/managed_reusable_candidate.py)
   to your external project as `workflow.py`. Edit its task manifest and data
   references and its `preparation_options`. Relative task references resolve
   against the `project_root` you select below. This first preparation route
   accepts managed proposal/storage bindings only; optional literal bindings
   remain unsupported and fail before any run directory is created.
2. Choose a runs directory outside the framework and outside your task/data
   mounts, a run name, an LLM configuration and the future execution limits.
   Have your coding assistant or Python integration create
   `/projects/my-task/reusable-request.json` using the
   [request construction recipe](candidate-prepare-contract.md#reusable-request-recipe).
   It records those choices and the selected source automatically. Advice stays
   in `workflow.py`; credential values stay in the launch environment.
3. Prepare without launching:

   ```bash
   .venv/bin/python -m tools.candidate_prepare --reusable-request /projects/my-task/reusable-request.json
   ```

   To let the submitting command exit while preparation continues, use the
   [detached operation route](../candidate_operations/README.md#prepare-a-reusable-workflow-in-the-background).

   The Python equivalent is
   `prepare_reusable_candidate(ReusableCandidatePreparationRequest.model_validate_json(payload))`.
   `preflight_reusable_candidate(request)` performs read-only admission, without
   task imports or directory creation; preparation always repeats it freshly.
4. Check the top-level `receipt.json` in the newly reported run directory.
   Success is `status: "prepared"` and CLI exit zero. `workflow.py.snapshot`
   contains your exact authored v2 bytes; `binding.json` identifies their selected
   project base and native inputs. `inputs/workflow.resolved.py` is generated v1
   input for the existing worker. Edit your authored source for future runs,
   never the generated files. `workspace/` remains absent.

For another preparation, keep the source unchanged and have the caller create
a fresh run request. Reusing an existing run refuses without modifying its
directory, even after failure.
Failures preserve diagnostic evidence; partial candidate requests are not proof
of successful reusable preparation. A missing receipt means unknown completion.
An edit during preparation fails; an edit after success affects future captures.

To execute one of these prepared runs, follow the
[reusable operation steps](../candidate_operations/README.md#run-a-prepared-reusable-workflow).
The shared builder checks the captured workflow and returns a submission for you
to save and retry safely. An edit to your current source does not change that selected run.
Direct worker launch checks only the generated v1 inputs; use the operation route
when launching a retained reusable capture. Preparing alone does not launch,
resume, or accept a scientific candidate. To select and launch an existing capture
in the browser, configure the [console prepared-run flow](../candidate_console/README.md#open-a-prepared-reusable-workflow).
Automatic GUI preparation, training and resume remain unavailable.
