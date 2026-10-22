# Native candidate preparation contract

`CandidatePreparationRequest` and `prepare_candidate(request) ->
CandidatePreparationReceipt` are the shared Python/JSON operation. The CLI
`python -m tools.candidate_prepare --request PATH` decodes the same request and
returns zero only for `prepared`. It never launches the worker.

## Admission

The request is strict, frozen and rejects extra fields. Required selections:
`task_manifest`, `data_root`, `llm_config_file`, `output_dir`,
`candidate_workspace`, `run_name`, `preparation_timeout_seconds`,
`candidate_timeout_seconds`, `task_read_only`, `candidate_network`,
`candidate_devices`, `candidate_environment_names`. Optional strings
`proposal_advice`, `implementation_advice`, `validation_advice` default to None.
Optional `allowed_output_types` is the native nonempty classifier/regressor tuple;
None leaves output policy unconstrained. Timeouts are finite positive seconds.

Paths must be canonical absolute local paths. Manifest/profile are existing
regular files; data is an existing directory. Output and future workspace must
be absent (including symlinks), with existing directory parents. They cannot
overlap each other, input data/files/source mounts or protected runtime roots.
Sandbox device/environment-name and mount rules apply before ownership claim;
preparation does not require values for future environment names.

`admission` reads original manifest/profile bytes, validates the profile using
`workflow_preview.config.parse_config`, and makes no writes. The parent claims
output with exclusive mkdir; losing callers write nothing. After claim, errors
preserve partial state and attempt a failed receipt. No recursive cleanup or reuse.
Neither preparation nor the pure candidate layout helper creates the future run.

## Process and native owners

The parent imports only inert declarations, routing, observations and selected
configuration models. It never composes a task or imports native request/node
modules. `child` checks source/snapshot identity, binds generated library to the
preparation output, then imports `native`. Ambient generated models are excluded
by the existing bound-library mechanism.

The actual sandbox uses output as writable workspace, network false, no devices,
and no passed environment names. Selected manifest/profile/data and explicitly
selected dependencies are read-only mounts. Runtime mounts come from the active
checkout/environment owner. Composition executes trusted Python and can read
mounted data; preparation requests no decoding, evaluation or training. Provider
clients are never constructed by the framework preparation route. This is not
an attestation about arbitrary selected plugin behavior.

`compose_run_task_bindings`, `bind_run_task_composition` and
`build_task_composition_ref` own task resolution, physical directory admission and
identity. Native InterpretationInput uses composed task description/task blocks,
metric spec, COMPOSED description policy, explicit cold_start=True, model_types=None,
empty summaries/cache/history and no analysis request. The public node-owned
`build_cold_start_interpretation` creates InterpretationOutput without a bridge.
The native `local_full_context` protocol owns evidence/advice/contributor mapping;
`get_reasoning_pipeline` supplies the same configured stages as the Professional
workflow. Composed description/forward contract/proposal blocks and the optional
caller output restriction are validated in ProposalInput. All unexposed fields
retain native defaults. No training budget, sampling or hardware policy is inferred.

`candidate_worker.layout.candidate_proposal_dir` computes the future
`workspace/run_name/iteration_001/attempt_001`; `impl_attempt_storage` owns impl_001.
The fixed WorkflowDocument contains proposal, implementation and validation with
the two native protocols, external proposal JSON and shared implementation storage.

## Artifacts and reconciliation

Fixed bundle files: `interpretation.json`, `proposal.json`, `storage.json`,
`llm.json`, `workflow.json`, `preview_request.json`, `preview.json`,
`candidate_request.json`. Fixed control subtree: `preparation/request.json`,
`manifest.snapshot`, `llm.snapshot`, `interpretation_input.json`, `child.json`,
`receipt.json`, `worker.log` (created by the child). JSON/snapshot publications use
`publish_bytes_write_once`; the child log opens exclusively. `request.json` is a
PreparationControl envelope containing the immutable selection, preparation UUID
and original FileObservations. The child index carries control hash, native
composition fingerprint and the exact native artifact observations.

Parent reconciliation rejects non-completed process status regardless of child
files, changed sources/control/native file hashes, wrong preparation identity,
wrong fixed declaration/profile bytes, a fingerprint inconsistent with the saved
proposal reference, or a newly occupied future workspace. A narrow inert identity
projection checks the fingerprint; full native payload validation remains in the
child and later worker. Hostile-child attestation is not promised.

The parent obtains observations/routes from `preview_workflow` and emits
CandidateRunRequest with managed_fresh storage, future timeout/network/devices/
environment names and downstream advice. Future read_only is the sorted unique
union of output, data, original manifest and explicit dependencies. The profile
bytes are copied unchanged to llm.json. Successful receipt paths point only to
fixed filenames. Receipt is an index, not a new task schema or execution receipt.
The preview's execution_ready remains false. No token ledger/usage is synthesized.

Receipt status is prepared, failed, timed_out or interrupted. Failure after claim
retains evidence; failure before claim raises without writes. Parent death can
leave no terminal receipt. No automatic retry/resume or future-workspace reservation
exists. Callers must not treat partial files as a successful bundle.

## Identity and qualification limits

FileObservation hashes selected bytes, not complete dependency closure. Native
captured code packages identify their finite member set; legacy file refs hash
selected files rather than arbitrary imports, and module references have their
existing weaker coverage. Worker recomposition compares represented native facts
before providers. This operation does not broaden those guarantees or migrate tasks.
The cold-start owner move changes rendering assembly identity, and the proposal
pipeline owner is included in preflight source closure. Historical accepted hashes
are not repinned; exp-owned historical qualification remains separate.

Validation owners: frozen pre-extraction oracle and reachability tests for native
owners; scoped admission/reconciliation tests; real sandbox checks for offline
mounts/import order, timeout and prepared-bundle worker integration. Fake provider
worker checks prove native plumbing and CPU validation, not real model quality.
No paid LLM, training, scoring, GPU or full GUI claim follows from preparation.
