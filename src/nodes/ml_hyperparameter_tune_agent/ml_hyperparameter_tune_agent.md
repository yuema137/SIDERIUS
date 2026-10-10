# HyperparamTuningAgent

> Optimizes hyperparameters for a given model architecture over N rounds. Each round runs **plan (LLM) → resource check → train → infer → score → reflect (LLM)** in a sandbox subprocess. Supports two modes (trial = sparse sampling for fast exploration, formal = full data for canonical scoring) and uses two LLM sub-calls per round — a planner (proposes hyperparameters) and a reflector (analyses results, drives the next plan). Returns the best run + a full audit trail of every successful, OOM-skipped, and gate-rejected attempt.

## Position in the pipeline

### Optional snapshot for training validation

`training_validation_portion` (`None` by default, otherwise `0 < value <= 1`)
selects a task-owned random snapshot for per-epoch validation loss in composed
Trial/Formal attempts. It is a fraction of the task's eligible validation
population within the run's declared scope, not a fraction of an already
sampled final-evaluation scope. Task sampling granularity determines rounding.
The attempt's recorded evaluation seed selects the snapshot once; every epoch
reuses it. No task or hardware geometry is implemented by the framework.

Final inference, metric scoring and Health retain the original evaluation
scope. Omitting the setting preserves the previous shared scope and artifact
names. The training child receives `task_training_validation_scope_<exp_id>.json`
with its digest and exact requested row count; final evaluation retains
`task_eval_scope_<exp_id>.json`. Training history and runtime prediction count
the selected validation rows. Unsupported legacy/single-file routes and missing
snapshot seeds refuse explicitly. The setting is locked across workspace
resume, so changing it requires a new workspace.

Trial anchor maps are explicit caller/task-owned JSON inputs. This framework
reads them through `execute_tools.trial_anchor_map.load_anchor_map`; the former
task-specific builder, checkout default, and root `reference_data/` anchor are
retired. TIDMAD task construction/default lookup lives in the experiment
repository at `tasks/tidmad/runtime/anchor_map`; other tasks prepare and pass
their own artifact path.

- **CLI entry**: **present** — the module exposes `main()` and builds a `HyperparamTuningInput`, but composed CLI runs require explicit task composition and data inputs; presence does not mean an unbound invocation is supported.
- **Upstream**: `ml_code_validator_agent` and `ml_model_proposal_agent`, through ONE fan-in protocol — `local_validated_model` in `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` — which takes the validator's `ValidatorOutput` (the validated `model_type`; the workflow traverses this edge only when `passed=True`) beside the `ProposalOutput` (which supplies `expert_advice`, with the validator's deviation notes prepended, and `baseline_config`). There is no separate proposal→tuner protocol module.
- **Downstream**: `result_interpretation_agent` (consumes `HyperparamTuningOutput` per model, converted via `tuning_output_to_model_run_summary` into a `ModelRunSummary` that feeds the next interpretation iteration; the edge's protocol module is `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py::local_all_records`).
- **Protocol (upstream)**: `ml_model_valid_to_ml_model_tune.py::local_validated_model` — builds this node's `HyperparamTuningInput` from `ValidatorOutput.model_type` + `ProposalOutput.{expert_advice, baseline_config}` plus the run posture the workflow passes (budgets, scope, health, LLM config, task composition).

## Input

**Schema**: `HyperparamTuningInput` in `agent/schemas/hyperparam_tuning.py`

### Core (model + LLM routing + guidance)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model_type` | `str` | Yes | — | Architecture to tune. One of the registered model keys (`punet`, `wavenet`, `fcnet`, `transformer`, `rnn`), or `"auto"` to let the planner pick. Composition-declared models use their current binding; an explicit single-file seed can be supplied through `seed_plugin_path`. |
| `seed_plugin_path` | `str \| None` | No | `None` | Optional single-file seed path. When supplied, the tuner copies it into `{workspace}/plugins/{run_name}/`; its top-level `PLUGIN_MODEL_TYPE` must equal `model_type`. A composition-declared package model uses its current binding and does not need this copy. Explicit seed staging remains a single-file operation, not package staging. |
| `expert_advice` | `str \| ExpertAdvice` | No | `""` | Structured guidance from upstream agents (typically `ml_model_proposal_agent.expert_advice`). Accepts a plain string or a structured `ExpertAdvice` object. Injected into the planner prompt. |
| `human_advice` | `str \| None` | No | `None` | Optional human-provided guidance. Injected into the planner prompt alongside `expert_advice` under a `[Human Guidance (high priority)]` header. |
| `seed_records` | `list[dict[str, Any]]` | No | `[]` | Pre-existing experiment records injected into the agent's memory before round 1. Typically contains the baseline result so the planner has prior history to reason from. |
| `llm_provider` | `Literal["gemini", "openai", "deepseek"]` | No | `"gemini"` | Provider for the planner sub-call (and default for the reflector when not overridden). |
| `llm_model_id` | `str` | No | `"gemini-3.1-flash-lite-preview"` | Model ID for the planner sub-call (and default for the reflector). |
| `reflect_provider` | `Literal["gemini", "openai", "deepseek"] \| None` | No | `None` | Optional separate provider for the reflector sub-call. When `None`, the reflector uses `llm_provider`. Enables planner/reflector split (e.g. cheap planner + smarter reflector). |
| `reflect_model_id` | `str \| None` | No | `None` | Optional separate model ID for the reflector. When `None`, falls back to `llm_model_id`. |
| `max_retries` | `int \| None` | No | `None` | Maximum retry attempts for transient API errors (429, 5xx). `None` = retry indefinitely; the process owner (Slurm wall time / operator interrupt) is expected to terminate stalled runs. |
| `plan_overrides` | `dict[str, Any]` | No | `{}` | Hard overrides applied to every `ExperimentPlan` after the LLM produces it. Keys must be valid `ExperimentPlan` field names. Used to force-pin specific hyperparameters that the LLM is incorrectly drifting on. Since Lane F2 this lock is ALSO how a chain launch freezes campaign portions: typed `--trial_portion` / `--train_portion` / `--eval_portion` merge in via `frozen_portion_overrides` (typed = EXPERIMENT_FIXED, omitted = AGENT_CONTROLLED; a conflicting explicit JSON entry for the same key refuses). **Trial-scoped keys (`is_trial` / `trial_portion` / `eval_portion` — the `--is_trial` CLI bundle) constrain TRIAL rounds only**: a formal round's workload always comes from the `formal_*` knobs (`_resolve_sample_set_cfg`), and the resolved-formal round prints a per-round `[plan_overrides] NOTE:` naming any discarded trial-scoped keys (Lane F / F14). The combination `max_rounds=1` + `force_formal_round=True` (its default) + trial-scoped overrides is **refused at input construction** — the override would apply to zero rounds. Remedies, in reachability order (F-316: a remedy must be reachable from the surface that names it): raise `max_rounds`, or drop the trial-scoped request; `--no-force_formal_round` exists on the CHAIN launcher only — this node's CLI has no force-formal flag. Note the two surfaces' same-named `--is_trial` flags differ: this node's CLI is `store_true` (default False; typing it is what auto-bundles the trial clamp into `plan_overrides`), while the chain launcher's is BooleanOptionalAction default True and never auto-bundles — so a chain-shaped `max_rounds=1` run with no explicit overrides is immune (test-pinned). With `is_trial=False` (single-file mode) there is NO refusal at any `max_rounds`: the single_file branch READS the overridden `trial_portion`/`train_portion`, so the override applies (review B1). The guarded key set is `TRIAL_SCOPED_OVERRIDE_KEYS` (schema-exported, six keys) — the resolver's FULL formal-branch replacement set, a superset of this CLI's three-key bundle (review C4). **Record-key truth (review B2)**: the top-level record key `trial_portion` is written ONLY on trial rounds (`absence == formal`, the `BestTracks` authority); a formal round's resolved workload appears at `validation_workload_ceiling.resolved.trial_portion`, in the reflector's `actual_results`, and in the planning printout — never at the top-level key. Single-file rounds disclose too: the single_file branch forces `trial_strategy`/`eval_strategy` to `snapshot` and `eval_portion` to 1.0, so overrides on those three keys are named per round while `trial_portion`/`train_portion` apply. |

### Round / attempt budgets

Completed attempts retain the trainer's typed `training_budget` receipt when
present, including its stopping decision, completed epochs and optimizer steps.
It travels alongside `runtime_verification` through `ExperimentRecord`; neither
receipt changes selection, admission or training policy. Malformed budget
receipts fail at the existing training-results validation boundary. Composed
opaque scopes do not fall back to whole-file geometry for selected PSD counts;
those legacy counts remain unknown unless the legacy sampling path establishes
them. Dataset row counts are separate from physical-segment counts.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `max_rounds` | `int` | No | `50` | Maximum number of **completed** experiment rounds (OOM-skipped attempts do not count). |
| `attempts_per_round` | `int` | No | `3` | Per-round attempt budget for trial rounds. Each round retries up to this many times after a gate-skip or error before the round is recorded as a failure. |
| `attempts_per_formal_round` | `int` | No | `5` | Per-round attempt budget for the formal-promotion round. Higher than trial (5 vs 3) because the formal round runs on the full dataset and a single retry is much more expensive. |
| `max_fail_rounds` | `int` | No | `3` | Consecutive-failed-round abort trigger. When this many rounds in a row exhaust their attempt budget without a success, the tuner exits with `termination_reason="aborted_fail_rounds"`. |
| `max_epochs` | `int \| None` | No | `None` | Hard cap on epochs per round. When set, the tuner clamps the LLM's planned epochs to `min(planned_epochs, max_epochs)`. Mode-agnostic fallback: `trial_max_epochs` / `formal_max_epochs` take precedence for their round role when provided (D-BUD-6). |
| `trial_max_epochs` | `int \| None` | No | `None` | TRIAL-role epoch ceiling (campaign decision D-BUD-6; frozen campaign posture trial 2 / formal 1). Precedence for a trial round: this value → `max_epochs` → no clamp; formal rounds never read it. `ge=1` — zero/negative refuse at validation. Resolution happens only in `HyperparamTuningInput.resolve_epoch_cap(is_trial=...)`, keyed on `plan.is_trial` **after** the mode-override chain — the same authority that stamps `record.is_trial` (see "Candidate role identity"). |
| `formal_max_epochs` | `int \| None` | No | `None` | FORMAL-role epoch ceiling (D-BUD-6). Precedence for a formal round: this value → `max_epochs` → no clamp; trial rounds never read it. `ge=1`. |
| `force_formal_round` | `bool` | No | `True` | When `True` (default), the **last** round of every iteration forces `plan.is_trial = False` so it always runs in formal mode (full dataset) regardless of what the planner picked. |
| `formal_round_strategy` | `Literal["full_clone", "hybrid_params", "independent", "inherit_best_train_plus_formal_eval"]` | No | `"full_clone"` | Orchestration policy for the forced formal round: `full_clone` re-runs the best trial verbatim on full data; `hybrid_params` carries trial-winner hyperparams + formal sampling; `independent` lets the planner propose a fresh formal config. |
| `degenerate_penalty_score` | `float \| None` | No | `None` | Operator policy for the agent's reaction when scoring flags a degenerate output on a formal round (e.g. all-zeros prediction). When set, the degenerate run gets this penalty score and the tuner continues; when `None`, the run is recorded as-is. |

### Trial mode sampling

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `is_trial` | `bool` | No | `False` | When `True`, run in trial-explore mode with sparse multi-file sampling for fast exploration. The default (`False`) means rounds run in formal mode unless the planner picks trial. |
| `trial_strategy` | `Literal["snapshot", "anchors", "target"]` | No | `"snapshot"` | Sampling strategy: `snapshot` (all 20 files), `anchors` (files 0/10/19), `target` (specific files via `target_files`). |
| `trial_portion` | `float \| None` | No | `None` (schema); CLI flag default `0.1` | Fraction of segments per file for the training scope. **TRANSIT ONLY (Lane F2)**: the tuner's executed trial workload never reads this input field — it reads the (possibly overridden) plan; the operator lock for portions is `plan_overrides` (this node's CLI bundles it under `--is_trial`; the chain's typed `--trial_portion` merges via `frozen_portion_overrides`). Its one real consumer chain is the proposer's resource-estimation preflight. The old `0.1` default shown here was doc drift — the schema default was always `None`. |
| `target_files` | `list[int]` | No | `[]` | File indices to sample from. Required when `trial_strategy="target"`. |
| `train_portion` | `float \| None` | No | `None` (schema); CLI flag default `0.1` | Per-epoch subsample fraction from the training scope. **TRANSIT ONLY (Lane F2)** — same truth as `trial_portion` above. |
| `eval_strategy` | `Literal["snapshot", "anchors", "target"]` | No | `"snapshot"` | Sampling strategy for validation. |
| `eval_portion` | `float \| None` | No | `None` (schema); CLI flag default `0.1` | Fraction of segments per file for the validation scope. **TRANSIT ONLY (Lane F2)** — same truth as `trial_portion` above. |
| `train_validation_align` | `bool` | No | `True` | When `True`, train and eval scopes use the same segment indices (different physical files). |
| `file_index` | `int` | No | `6` | Validation/training file index (0-39). Default 6 matches the paper's standard split. **Ignored when `is_trial=True`.** |

### Formal mode sampling

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `formal_strategy` | `Literal["snapshot", "anchors", "target"]` | No | `"snapshot"` | Training-side sampling strategy in formal mode. Overrides the planner's `trial_strategy` on any round promoted to formal. |
| `formal_training_scope_source` | `Literal["operator", "agent"]` | No | `"operator"` | Generic ownership switch for Formal training strategy and portions. `operator` uses the `formal_*` fields; `agent` uses the validated plan's `trial_strategy`, `trial_portion`, and `train_portion`. It never changes Formal evaluation ownership. |
| `formal_portion` | `float` | No | `0.1` | Fraction of segments per file for training scope in formal mode. |
| `formal_train_portion` | `float` | No | `1.0` | Per-epoch iteration fraction from the formal training scope. |
| `formal_eval_portion` | `float` | No | `1.0` | Fraction of segments per file used for formal-mode eval scope (`snapshot` strategy). Default `1.0` reproduces the legacy full-clone behavior. |

### Data ordering (V19 PR 2)

Ordering is the **sequence** in which the selected samples are visited
during training. It never changes *which* samples are selected — that is
`DataScope` + the sampling strategies above.

Ordering follows the project's proposal / override / resolution pattern
(`docs/design/genericity_contract.md` Seam 2): the **agent proposes**
(via `ExperimentPlan`), the **operator may override** for a whole chain
(the fields below), and the execution system **resolves** the value that
actually runs. Precedence is fixed:

```text
operator override  >  agent proposal  >  default ("shuffle")
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `order_strategy_override` | `Literal["shuffle", "sequential"] \| None` | No | `None` | Force the visitation order for every round, overriding any agent proposal. `None` = the agent decides, falling back to `"shuffle"` (the pre-V19 behavior). Pinned in the run-invariants lock — changing it mid-chain is a violation. |
| `file_order_override` | `list[int] \| None` | No | `None` | Operator-forced file visitation order, valid only with `order_strategy_override="sequential"`. Must be a **full permutation** of the resolved `DataScope` — same files, different order. `None` = ascending file index. |

Strategies:

- **`shuffle`** (default) — global uniform shuffle across the epoch's
  concatenated dataset. Byte-for-byte the pre-V19 behavior.
- **`sequential`** — file blocks visited in `file_order`, with samples
  **shuffled within each file**. One global DataLoader with the global
  `drop_last`, so batches may span a file boundary and the optimizer-step
  count is identical to `shuffle` for the same selection.

### Sampling seeds

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `sampling_seed` | `int \| None` | No | `None` | Seed for `build_sample_set()` — determines which PSD segments form the data scope. When `None`, auto-generated from `SHA-256(run_name + model_type)`. |
| `train_base_seed` | `int \| None` | No | `None` | Base seed for per-epoch training subsampling. Epoch `n` uses `train_base_seed + n`. When `None`, auto-generated. |

### Selection topology (Step-02b)

Not an input field — a behavioural contract worth stating, because it
determines which files a round can select at all.

Each trial/formal round resolves the run's **Dataset Profile once** and
passes it explicitly to **both** `build_sample_set()` calls (training and
validation):

```python
run_profile = resolve_dataset_profile()
train_sample_set = build_sample_set(..., scope=..., profile=run_profile)
eval_sample_set  = build_sample_set(..., scope=..., profile=run_profile)
```

Two properties follow, and both are pinned by tests:

- the file population and index space come from the run's profile, not
  from an ambient default, so a run bound to a non-TIDMAD topology
  selects against that topology;
- training and validation provably share one topology, because the
  profile is resolved once per round rather than once per call site.

`build_sample_set(profile=None)` still resolves ambiently, which is what
callers without a run-bound profile (for example, an external experiment's
legacy comparison tool or the proposer pre-flight) continue to do.

#### Task-built scopes on the composed path (Step 12 / PR-12bc, CAP-SCOPE)

The two `build_sample_set()` calls above construct a **TIDMAD** `SampleSet`.
That is correct for an un-composed run and is unchanged; it is not correct for
a task whose data has a different shape, and it was the reason a composed
contrast run could not train (Q-P56-1 = B, carried since Step 10).

A task may now declare an **optional sibling capability**,
`TaskScopeCapability` (`execute_tools/task_data_path.py`) — four methods
(`build_training_scope`, `build_eval_scope`, `serialize_scope`,
`deserialize_scope`). The frozen four-method `TaskDataPath` protocol is
**unchanged**; a task that declares no scope capability behaves exactly as
before.

```text
un-composed caller with legacy physical geometry
              -> the legacy build_sample_set path, byte-identical
composed task -> the tuner asks the TASK to build the attempt's scopes
                  (nodes/ml_hyperparameter_tune_agent/scope_acquisition.py)
                  -> the task serializes them
                  -> the parent writes a scope ARTIFACT + sha256 digest
                  -> the child verifies the digest, then asks the TASK to
                     deserialize
```

The framework never inspects a scope's contents. What crosses the process
boundary is the artifact **path and digest**, never raw scope JSON on argv;
the parent writes the artifact atomically, and the child verifies **before**
deserializing. `ScopeBuildRequest` carries only framework vocabulary —
`round_kind`, `selection_strategy`, `portion`, `seed`, `max_samples`,
`target_partitions`, `subset_ref` — plus one opaque per-attempt
`task_parameters` payload the framework transports and never reads
(`seg_size` travels there: it is the planner's per-attempt model choice, not
framework vocabulary).

An external task may additionally implement the optional frozen-training-pool
capability (`execute_tools.training_pool`). When present, the task constructs
one content-pinned parent scope per selected partition set. A Formal round
uses that parent exactly; its configured `formal_portion` must equal the
parent's declared source fraction. A Trial round interprets the planner's
`trial_portion` relative to that parent. The task proves child containment
before training starts. Evaluation scope construction is unchanged and may
still cover the full validation population. Without this optional capability,
the existing independent per-round scope builders remain authoritative.

Related: `DatasetProfile` now separates **generic identity**
(`partition_count`, `anchor_selection_files`, `health_peek_files`) from an
**opaque `topology`** dict the framework carries and never interprets
(Q-12-4). TIDMAD's `dataset` / `channels` / `encoding` sections live inside
that payload; the legacy wire form is still accepted and still emitted.

#### Consolidated physical-topology projection (Step 12 / PR-12d, seam B)

Five sites in this package used to decode TIDMAD's topology directly —
`planning.py` (data-config validation, SampleSet construction, segment
counts), `ml_hyperparameter_tune_agent.py` (the task-render dataset fact) and
`execution.py` (the raw validation-file peek path) — and each independently
killed a composed contrast run before any training, because a task whose
profile carries no `dataset`/`channels`/`encoding` sections has nothing for
`tidmad_topology()` to decode.

`scope_acquisition.py::project_attempt_topology_facts(run_profile)` is now the
ONE place this package asks. It returns an `AttemptTopologyFacts` — a single
`physical_dataset: DatasetConfig | None` plus a `declares_physical_geometry`
property and a `require_physical_dataset(purpose)` accessor that raises
`TaskTopologyUnavailableError` naming what was unavailable. The decision is a
**membership test** (`declares_tidmad_topology`), never a caught exception: a
profile that declares TIDMAD's sections but carries a malformed payload still
raises out of `tidmad_topology()` rather than being reclassified as "declares
none".

Two consumers now SKIP rather than fabricate instead of dying:

- `_validate_data_config` (PSD-segment divisibility / per-file segment
  counts) — skipped; per the D-BC-8 precedent, this is TASK topology, not the
  generic partition-count bound.
- the two legacy `build_sample_set()` calls (training + validation
  SampleSets) — skipped for every composed task in favour of `AttemptScopes`,
  the task-owned scopes acquired separately by `acquire_attempt_scopes`
  (PR-12bc B5). A composed task that also declares legacy physical geometry
  does not receive both representations: doing so would create two scope
  authorities and the task-generic training engine correctly refuses it.

Under an un-composed legacy physical-data caller, every fact
`AttemptTopologyFacts` reports and both legacy SampleSets remain unchanged.
Composition presence, never a task name, selects the task-owned scope path.

### Resource and time planning (Step-05b)

The same run-binding rule now governs what the pre-flight gates are allowed
to *price*. Two values are bound ONCE per run, at the top of `run()`, and
passed explicitly to every consumer:

```python
run_profile   = resolve_dataset_profile()          # Step 02 — topology
run_model_io  = run_bound_model_io_contract()      # Step 03 — Model-I/O
```

| Bound value | Reaches | Why it is passed rather than resolved |
|---|---|---|
| `run_profile` | `_run_time_preflight` → `evaluate_time_skill.run_skill` (a **required** kwarg), and the §5 step guardrails | a time gate that re-read an ambient topology prices the run against a dataset it is not using |
| `run_model_io` | `run_production_preflight` → `IsolatedProbeSpec` → the isolated worker → `evaluate_vram_skill.run_skill` | the capacity probe must realize the target the run will actually train against, not a `[B, 256, T]` literal |
| composed attempt training/evaluation scopes | `build_task_probe_data` → `TaskProbeDataSpec` → the isolated worker → `TaskDataPath.training_dataset` / `validation_dataset` | The training probe consumes task-semantic inputs/targets. Before training measurement, one validation sample also runs through the shared production inference input boundary; this catches input-interface failures before fitting a candidate. The task's forward contract must explicitly declare `segmentation_applicability` as `temporal` or `not_applicable`; omission refuses before measurement rather than borrowing a temporal default. |
| optional task inference batch ceiling | `TaskInferenceBatching` → `TaskProbeDataSpec` → isolated VRAM resolver → `active_params["inference_batch"]` → inference child | a memory-feasible synthetic batch is not proof that variable-shaped task samples can be collated; resource selection and execution must use one task-semantic maximum |

`run_bound_model_io_contract()` (`workflows/task_config.py`) is the **one**
acquisition point: `SandboxExecutor._write_model_io_config` uses it too, so
the contract the pre-flight prices against and the contract materialized to
`--model_io_json` for the training and inference children cannot diverge.
Resolution (preset + dataset cross-check) already happened inside
`load_task_config`; nothing here re-resolves.

A task declaring no `model_io` binds `None`, and every consumer takes its
legacy no-contract path. Model-I/O itself adds no CLI argument or config
field; the separately documented preflight watchdogs are workflow execution
configuration and do not alter the model-I/O declaration.

One behavioural consequence, stated because it is a change: binding the
contract at startup makes an unreadable `configs/task_config.yaml` fatal
there rather than at the first training launch. No run that would have
succeeded can now fail — every run that trains already evaluates that same
expression — and failing before any GPU work is the fail-closed direction.

### Pre-flight gates (resource budgets)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `trial_time_budget_minutes` | `float \| None` | No | `None` | Trial wall-time ceiling. `None` disables Trial time admission regardless of source. |
| `formal_time_budget_minutes` | `float \| None` | No | `None` | Formal wall-time ceiling. `None` disables Formal time admission regardless of source. |
| `trial_time_admission_source` | `forecast \| measured` | No | `measured` | Trial's sole time-admission authority. `measured` enforces executing-device evidence and skips advance forecast admission; `forecast` does the reverse. |
| `formal_time_admission_source` | `forecast \| measured` | No | `measured` | Formal's independent sole time-admission authority, with the same mutually exclusive semantics. |
| `runtime_completion_policy` | `completed-workload-v1 \| verified-prediction-v1` | No | `completed-workload-v1` | Completed phase actual costs govern the current attempt; incomplete phases still require conservative verification. Explicit strict mode retains the pre-completion admission rule. Compared in run identity and forwarded unchanged to training and inference. Historical experiment selection belongs to the consumer repository. |
| `runtime_verifier` | `str \| None` | No | `None` | Optional installed runtime-verifier provider. Omitted constructs the native verifier. Selection resolves before work and never silently falls back. |
| `runtime_verifier_identity` | `RuntimeVerifierIdentity \| None` | No | `None` | Resolved source and qualified-assembly identity, compared in workspace locks and verified in the executor environment. Ordinarily resolved from `runtime_verifier`; an explicit expected identity must match. |
| `trial_vram_budget_gb` | `float \| None` | No | `None` | VRAM budget against which `evaluate_vram_skill` gates trial rounds. `None` = trial VRAM-gate disabled. |
| `formal_vram_budget_gb` | `float \| None` | No | `None` | VRAM budget against which `evaluate_vram_skill` gates formal rounds. `None` = formal VRAM-gate disabled. |
| `vram_probe_step_timeout_seconds` | `float` | No | `180.0` | Watchdog for one training-mode or inference footprint forward during VRAM preflight. It runs no optimizer update and does not bound an epoch or candidate run. |
| `vram_preflight_total_timeout_seconds` | `float` | No | `900.0` | End-to-end watchdog for the isolated VRAM preflight worker, including model construction, footprint measurement, and inference-batch search. Independent of Trial/Formal training budgets. |
| `vram_preflight_host_memory_limit_gb` | `float \| None` | No | `None` | Resident host-memory limit for the complete isolated VRAM-preflight process tree. `None` preserves the deployment default, normally 24 GiB. Independent of the GPU VRAM ceiling; a breach is inconclusive rather than model-capacity evidence. |
| `data_dir` | `str \| None` | No | `None` | Caller-selected physical dataset root forwarded to runtime measurement and child execution. Supported composed launches require an explicit root; the framework never substitutes a scientific-task or machine-local default. |
| `measurement_capability` | `ResolvedMeasurementCapability \| None` | No | `None` | Caller-resolved measurement identity and availability. The workflow transports this typed value through the validator-to-tuner protocol so tuning and calibration never infer a scientific task identity from `data_dir`. `None` records an unavailable measurement path and cannot authorize a formal scientific decision that requires measured evidence. |

**The time budgets above are forecast/admission inputs, not runtime
limits.** They gate whether a round is admitted, using an estimate; the
epoch that is admitted then runs to completion. A round once ran 33m53s
under a 5-minute budget. For an actual bound, see the validation-posture
fields below.

### Validation posture (Gate harness only — `None`/off in every campaign)

These exist so a Gate can bound how much real work a normal plan
executes, without distorting what the planner is allowed to decide. See
`docs/gates/gate_testing_standard.md`.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `validation_max_portion` | `float \| None` | No | `None` | Hard ceiling on the RESOLVED `trial_portion` / `train_portion` / `eval_portion`, applied as `min(planned, ceiling)` after the planner, after `plan_overrides` and after the formal-round override chain. Governs formal rounds too — that is what stops `formal_eval_portion`'s 1.0 default pulling full scope into a smoke test. |
| `validation_max_train_samples` | `int \| None` (`>= 1`) | No | `None` | Absolute ceiling on the ML segments one training epoch may contain, applied where the epoch is BUILT (`TIDMADEpochDataset`), so fewer segments are read and fewer optimizer steps exist before any run. Needed beside the portion because a fraction's base is not harness-owned: samples per PSD segment are `psd_segment_length // seg_size`, and `seg_size` is the planner's model config. CLAMPS, never rejects — unlike `max_steps_per_attempt`, whose refusal skipped every round of a Gate attempt. `resolve_training_workload(..., max_samples=)` mirrors it exactly, so the executed step count is knowable before launch. |
| `validation_max_samples` | `int \| None` (`>= 1`) | No | `None` | Absolute ceiling on the ML segments one VALIDATION pass may contain — the validation-row counterpart of `validation_max_train_samples`, which bounds TRAINING rows. **The two names differ by one word and bound different sets**, which is why both exist: 07a's Gate 2 capped the training epoch at 2,000 rows while validation ran the full 15,000-row eval SampleSet, 7.5× the training work, every epoch. Applied to the REQUESTED scope before it materializes (`clamp_validation_scope`), so 07a's `validation_samples == validation_requested_samples` invariant is never relaxed — a ceiling applied afterwards would make every clamped run raise. CLAMPS to whole PSD segments and never overshoots: the resolved count is the largest multiple of `psd_segment_length // seg_size` at or below the ceiling. A ceiling below one PSD segment's rows is REFUSED (under TIDMAD at `seg_size` 40,000 that is 250 rows), because R3 does not exist for an empty scope. INTERIM cost bounding, not the root fix — the priced watchdog deadline is. `TrainingHistory.validation_requested_samples_before_limit` records the pre-limit natural scope, so `was_limited` is recoverable. Reaches the trainer through the runtime policy, not a new training argv flag. |
| `validation_max_phase_seconds` | `float \| None` | No | `None` | Emergency wall-clock fuse for one execution phase, enforced by the RT4 watchdog as an extra deadline candidate — never by admission, so it cannot skip the attempt. Requires `runtime_watchdog_enabled` (refused otherwise). Not a sizing mechanism: a run killed at the deadline yields no evidence. Effective ceiling is `max(this, runtime_watchdog_floor_seconds)`. **Orthogonal to `validation_max_samples`**: seconds versus samples, so there is no `min()` between them — the sample ceiling sizes the workload, this remains an independent wall-clock termination. |

### Workflow-populated fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `storage` | `StorageConfig` | Yes | — | Where this node reads its inputs and writes its outputs. Supports the local filesystem backend; populated by `main()` in CLI mode or by `workflows/model_exploration.py` in workflow mode. |
| `cleanup_denoised` | `bool` | No | `False` | Legacy request for output cleanup. Since the default is now cleanup, this does not grant a second policy. It is refused when combined with `retain_model_outputs=True`. |
| `retain_model_outputs` | `bool` | No | `False` | Run-wide output lifetime policy. `False` retires exact task-declared per-sample outputs after scoring and Health; `True` retains them. The value is locked for resume. Certified models, aggregate evidence, and retention receipts remain. See [model-output retention](../../../docs/reference/model-output-retention.md). |
| `retain_training_checkpoints` | `bool` | No | `False` | Retire each attempt's original `.pth` after the tuner iteration and its output finish. `True` keeps the originals. All certified scored-candidate `.pt` blobs remain; the value is locked for resume. See [training-checkpoint retention](../../../docs/reference/training-checkpoint-retention.md). |
| `progress_bar` | `bool` | No | `False` | Stream live tqdm progress bars from training/inference subprocesses. |
| `current_run_best_formal_score` | `float \| None` | No | `None` | Chain formal-incumbent reference (from `core/resume.py`). See "Chain formal-incumbent reference" under Key behavioral notes. |
| `enable_chain_incumbent_formal_gates` | `bool` | No | `False` | Consumption-only switch for the two formal delta gates. See "Chain formal-incumbent reference" under Key behavioral notes. |
| `enable_structured_health_feedback` | `bool` | No | `False` | V19 PR 3 chain-policy PASS-THROUGH. The tuner has NO PR 3 behavior of its own: it passes this value into its run-invariants lock call and stamps it into `run_config` — nothing else reads it (a source regression test pins exactly two references). The flag's behavioral effect lives in the interpreter/proposer prompts. |
| `health_feedback_history_window_iterations` | `int` (`>= 1`) | No | `3` | V19 PR 3 retention-policy pass-through (locked + stamped only; consumed by the interpreter's history merge, not by the tuner). |
| `health_feedback_history_max_entries_per_model` | `int` (`>= 1`) | No | `8` | V19 PR 3 retention-policy pass-through (locked + stamped only). |
| `experiment_arm` | `str \| None` | No | `None` | **arXiv U1 (#254)** — OPAQUE experiment-arm PASS-THROUGH. Locked into the per-model `run_invariants_lock.json` and stamped on every record (at `_emit_record`, ONLY when not `None`) and on the output (both exit paths). Never read to decide behaviour (ruling R2 — an AST census refuses any test expression in the node that mentions it). `None` = unlabelled legacy run. |
| `lit_review_enabled` | `bool` | No | `False` | **arXiv U1 (#253)** — workflow-topology pass-through: whether the chain's `ml_literature_review` node ran. Locked only; the tuner has no lit-review behaviour. |
| `data_analysis_enabled` | `bool \| None` | No | `None` | Workflow Data Analysis treatment pass-through. Locked only; the tuner receives no analysis data authority from it. |
| `lit_review_config_sha256` | `str \| None` | No | `None` | **arXiv U1 (#253)** — sha256 of the resolved lit-review YAML when enabled, else `None`. Locked only; the lock refuses `lit_review_enabled=True` without it, and a pin without the flag. |
| `baseline_isolation` | `bool` | No | `False` | **arXiv U3 (#260)** — the WITHOUT arm's explicit isolation flag. Locked into the per-model lock and forwarded to `get_model_description(...)`, which then refuses a BUNDLED `ml_models/*/description.md`; the tuner has no other behaviour under it (a built-in candidate is refused upstream, before tuning). |

## Output

**Schema**: `HyperparamTuningOutput` in `agent/schemas/hyperparam_tuning.py`

| Field | Type | Description |
|---|---|---|
| `run_name` | `str` | Echoed from `storage.local.run_name`. |
| `model_type` | `str` | The architecture that was tuned. |
| `file_index` | `int` | Validation file index used (formal mode only — ignored under trial). |
| `status` | `Literal["completed", "partial", "failed"]` | `completed` = reached `max_rounds`. `partial` = hit attempt limit before `max_rounds`. `failed` = unrecoverable error. |
| `completed_rounds` | `int` | Number of rounds that produced a valid experiment record. |
| `total_attempts` | `int` | Total attempt count across all rounds (includes OOM-skipped + gate-rejected). |
| `best_exp_id` | `str \| None` | `exp_id` of the experiment with the highest `denoising_score`. |
| `best_denoising_score` | `float \| None` | Highest `denoising_score` achieved across all completed rounds. |
| `best_config` | `dict[str, Any] \| None` | `model_config` + `train_config` + `loss_config` that produced `best_denoising_score`. |
| `best_file_vector` | `list[float \| None] \| None` | Length-20 score vector from the best experiment. `None` for files not included. |
| `best_score_table` | `ScoreComparisonTable \| None` | Score comparison table from the best experiment. Enriches `best_file_vector` with raw_baseline + ground_truth columns. |
| `formal_score_table` | `ScoreComparisonTable \| None` | Score comparison table from the most recent successful formal (full 20-file) round. Distinct from `best_score_table` because the best run might be a trial, not the formal canonical. |
| `all_records` | `list[ExperimentRecord]` | Complete experiment history including successful, failed, OOM-skipped, and (V20 PR B) admission-refused rounds — the last are phases that never started, so they carry no score and are not candidate failures. Each record contains params, results, timing, and any error message. **The dominant payload by size.** |
| `gate_exhaustion` | `GateExhaustionInfo \| None` | Populated when **either** trigger fires. **Trigger A**: no attempt reached `status == "success"` AND ≥1 attempt was rejected by the pre-flight resource gate. **Trigger B**: the outer loop aborted on the consecutive-failure brake after `completed_rounds > 0` — so under Trigger B earlier rounds **did** succeed. Used by the downstream proposer's `recent_gate_exhaustions` field to learn from prior tuner-side gate failures. C12-P: the rendered `summary_message` and log line now state how many attempts **reached training**, because Trigger A's predicate ("no *successful* outcome") was being rendered as "never trained" — false for an attempt that trained and then failed HealthGate, and false unconditionally under Trigger B. |
| `trial_validity_feedback` | `TrialValidityFeedback \| None` | **V20 PR D (D-C6)** — populated only when the iteration ran trial rounds but produced NO HealthGate-valid winner. Reaches the next proposer via `ProposalInput.recent_trial_validity`. Deliberately SEPARATE from `gate_exhaustion`, which reports BUDGET exhaustion: these trials ran and succeeded and then failed their scientific gates, so `gate_exhaustion`'s triggers never fire for them, and the two call for opposite responses (propose lighter vs propose something that does not collapse). `None` whenever any trial is valid. |
| `experiment_arm` | `str \| None` | **arXiv U1 (#254)** — the opaque arm label echoed from the input on BOTH the healthy and the degraded exit path (the `candidate_id` precedent), so a later resume can certify the output it restores. `None` for an unlabelled run and for every pre-U1 output. |
| `formal_comparison_reference_source` | `str \| None` | **V20 PR D (D-C3)** — provenance of `formal_reference_score`: `restored_valid_formal_incumbent`, `negative_infinity_bootstrap` (no incumbent existed; the reference resolved to `-inf` internally) or `gates_disabled`. Read it WITH the reference: `null` alone is ambiguous across all three. `-inf` is never serialised. |
| `scientific_authority` (per record) | `dict \| None` | **V20 PR D (D-C2b/D-C4)** — on FORMAL records only, the authority verdict with its three facts beside its conclusions, so it is recomputable and therefore tamper-EVIDENT. Consumers must re-derive via `resolve_record_authority()` rather than trusting the stored conclusions. |
| `metric_result` (per record) | `MetricResult \| None` | **Step 06 (2026-08)** — the evaluation metric's own result for the attempt, written by the metric handle on the live scoring route: `metric_id` (`tidmad_denoising_score`), `direction` (`higher`), `scalar` (== `denoising_score` on a `success` record — validated), `references_used`; `per_sample` is a POINTER to `file_vector` on the same record (not stored twice). `None` on records written before Step 06, on attempts that never reached scoring, and on the legacy single-file skill route. On a `failed_mode_collapse` record it is the metric's RAW value while `denoising_score` carries the gate policy's penalty. |
| `metric_refusal` (per record) | `NotScoreableResult \| None` | **Step 06** — the structured not-scoreable result when the produced deliverable failed the metric's scoreability contract BEFORE any scorer arithmetic ran (record `status='error_scoring'`, `failure_stage='scoring'`, `failure_type='not_scoreable'`): contract id, every violated requirement (`completeness` / `required_channels` / `required_attrs` / `required_dtype`), input identity, detail. Never set together with `metric_result`. |
| `training_history` (per record) | `TrainingHistory \| None` | **Step 07a (2026-08)** — the trainer's typed per-epoch observation payload (`execute_tools/training_history.py`): `objective_kind` (= `loss_config.loss_type`, a family label) + `objective_config_fingerprint` (SHA-256 of the canonical resolved `LossConfig` — configuration surface, not plugin code) + `objective_reduction`; `epoch_statistic` (R2 and R3 share ONE estimator: the sample-count-weighted mean of the criterion's batch scalar); `comparability` (`established` only for the audited built-in mean-reduced kinds `focal` / `focal_cw` / `ce` / `smooth_l1`; `sum` → `reduction=sum`, custom → `custom_objective_undeclared`); `epochs_planned` / `epochs_completed`; `train_objective` (R2 == `loss_history`, `final_loss` == last entry, validated); `validation_objective` (R3 — the SAME objective on the run-bound eval SampleSet, VALIDATION file family, no backprop; `None` ONLY when no validation was expected, i.e. legacy single-file); `validation_requested_samples == validation_samples > 0` (the declared scope materialized EXACTLY); `validation_seconds` (per epoch; excluded from the training ACTUAL); `observations` (**`R-OBS-1` (2026-08)** — the run's DECLARED DYNAMIC observables, one value per completed epoch, keyed by the name the task's manifest declared under `dynamic_observables:`. Produced by the trainer on the SAME per-epoch validation pass that yields R3, so a declaration costs no extra forward pass. Every series is guaranteed `epochs_completed` long — an observable that failed in some epochs only yields a short series, which is dropped WHOLE rather than padded. `{}` for every run that declares none, which is every run before this family). `None` on failure / skip records and on pre-07a records. **The objective series are `list[float \| None]`** — an ELEMENT is `None` where that epoch's objective was non-finite and the record has crossed the storage boundary, because `coerce_nonfinite_to_none` (`LocalRecorder.save_record`) writes JSON `null` for `NaN`/`±inf`; the same is true of the record's own `loss_history`. Positions are preserved, so the epoch-count and R2/R3 length invariants are unaffected, and `_all_finite` judges a `None` element exactly as the non-finite value it stands for (F-12e-G2: a strict element type previously made a diverged run's record fail re-validation and discarded the whole scored attempt). **Expected validation ≠ optional validation**: an attempt that BUILT an eval SampleSet whose results carry no R3 is recorded as `error_training` (`error_type='training_results_contract'`), never as a success with `validation_state='absent'`. |
| `training_diagnosis` (per record) | `TrainingDiagnosis \| None` | **Step 07a** — derived ONCE from `training_history` at the tuner boundary (`agent/schemas/training_diagnosis.py::derive_training_diagnosis`, pure / deterministic / no I/O): `state` (`ok` / `absent` = no payload / `invalid` = empty or non-finite R2/R3 — raw values stay on the history), `validation_state`, `comparability`, epoch counts + `truncated`, train / validation first / last / min + `train_min_epoch` / `best_validation_epoch` (argmin R3), `validation_degradation_verdict` (**F-SCANE-2**, operator ruling 2026-08-26 — `observed` / `insufficient_history` / `not_applicable`), `final_vs_best_validation_degradation` (+ `_rel`), `validation_degraded_after_best` (**all three are `None` unless the verdict is `observed`**: at `epochs_completed == 1` the validation series has ONE entry, so `r3[-1] − r3[best]` is `x − x` and the old `0.0` / `False` read as measured evidence of no degradation on the record and in the operator report. The campaign freezes `formal_max_epochs = 1`, so this is EVERY formal round. `validation_trend` is NOT gated — `single_point` already says it honestly), `train_validation_gap_final` (+ `_rel`; `None` unless `comparability == established`), `train_trend` / `validation_trend` (`decreasing` / `increasing` / `flat` / `single_point` with the symmetric scale-free deadband `r(a,b)=|b−a|/max(|a|,|b|) ≤ flat_rel_tol`, `flat_rel_tol=0.01` recorded). NO overfitting / underfitting / converged / plateau labels (07b renders selected facts; Step 09 may derive calibrated labels). `state='absent'` beside a `None` history on legacy producers. **Both fields are persisted evidence and HIDDEN from both LLM-facing renders in 07a** — the planner's history serialization drops them (`agent/prompts.py::_PLANNER_HIDDEN_RECORD_KEYS`) and the reflector's `actual_results` receives the legacy payload only (`final_loss` / `loss_history` / `model_params`), so PB-1/PB-2/WF-1/WF-2 are byte-identical to pre-07a. |
| `physical_rejections` | `list[PhysicalRejection]` | One entry per resource-preflight refusal captured in this run. Optional typed static evidence distinguishes structural and compute-intensity refusals from measured GPU failures; the historical name does not establish a physical measurement. Empty when no infeasible attempts are captured. |
| `attempts_per_round` | `int` | Echo of the input value used for this run. |
| `attempts_per_formal_round` | `int` | Echo of the input value used for this run. |
| `max_fail_rounds` | `int` | Echo of the input value used for this run. |
| `static_observations` (per record) | `dict[str, float]` | **`R-OBS-1` (2026-08)** — the run's DECLARED STATIC observables (`static_observables:` in the task manifest), each read off the TRAINED model once after the final optimizer step and before it is serialized. Its DYNAMIC sibling is not here: a per-epoch series lives on `training_history.observations`, beside the R2/R3 series it is aligned to. An implementation that raises or returns a non-finite value is ABSENT — never a sentinel, and never a failed training attempt. The key is written only when non-empty, so a run that declares no static observable produces its pre-`R-OBS-1` record verbatim. **OBSERVATIONAL**: never an operand of an ordering expression, and hidden from both LLM-facing renders (`D-BUD-16`). |
| `secondary_metric_results` (per record) | `list[MetricResult]` | **Step 10 / P2b (2026-08)** — one entry per DECLARED observational secondary that produced a value, each with its OWN id and direction (DAVIS declares `psnr` higher beside a `mse` primary that is lower-is-better). Evaluated wherever the PRIMARY evaluates — both trial and formal scoring, no round-type branch — and only after a successful primary result, so an `error_scoring` record carries none by construction. The key is written only when non-empty, so a run that declares no secondary produces its pre-P2b record verbatim. |
| `secondary_metric_refusals` (per record) | `list[NotScoreableResult]` | **Step 10 / P2b** — one entry per declared secondary whose deliverable failed THAT metric's scoreability contract. A scientific refusal, structured exactly as the primary's `metric_refusal`; the attempt stays successful, because the primary already produced its result. |
| `secondary_metric_errors` (per record) | `dict[str, str]` | **Step 10 / P2b** — diagnostic PROVENANCE for a declared secondary whose evaluation CRASHED: metric id → a concise one-line diagnostic, also printed. Deliberately NOT a scientific state — a crash produced no contract verdict, so recording a `NotScoreableResult` would fabricate a measurement. The interpreter projects such a secondary as `unavailable`. A `ScopeViolationError` is NEVER recorded here: it is re-raised so the existing outer handler terminates the run, because "observational" bounds ordinary secondary outcomes, not framework-integrity failures. |
| `per_sample_evidence` (HealthGate context) | `PerSampleEvidence` | **Step 08b C6 / D18 (2026-08-18)** — whether the round's metric produces per-sample evidence at all, carried into `HealthCheckContext` beside `file_vector` rather than collapsed into it. Derived once, by `PerSampleEvidence.for_per_sample(metric_result.per_sample)`: `None` → `scalar_only`, a list (even an empty one) → `available`, and the default `undeclared` for every pre-scoring gate. Before this, a scalar-only metric presented per-file checks with `[]`, which reads as "no files" and PASSES — inapplicability recorded as health. Health consumes this CAPABILITY only and never the metric scalar. Two of the three executable tracks (Pets accuracy, DAVIS global MSE) are scalar-only; TIDMAD is not, so TIDMAD behaviour is unchanged. |
| `consecutive_fail_rounds_at_exit` | `int` | Terminal value of the loop's consecutive-failure counter. `0` on a healthy completion; equals `max_fail_rounds` when the loop aborted on the trigger. |
| `termination_reason` | `Literal["completed", "aborted_fail_rounds", "aborted_by_gate", "scope_violation", "infrastructure_abort"]` | Why the loop exited. `"aborted_by_gate"` is HISTORICAL (pre-F-SCANC-1 records only; the SKIP_ITER producer was retired 2026-08-26 and the member stays so old records deserialize). `"infrastructure_abort"` (C9c, 2026-07-30) means the runtime EVIDENCE CHANNEL failed — registry, persistence, schema/protocol, probe executor, telemetry, communication, or a policy invariant. It outranks every other reason and halts the CHAIN: `run_one_iteration.py` writes the `.chain_halted` sentinel with `reason="infrastructure_abort"` and exits 3, so neither the foreground loop nor a queued SDSC `afterany` job runs another candidate on the same broken environment. A candidate-class rejection stays attempt-local. |
| `started_at` | `str` | ISO-8601 UTC timestamp at `agent.run(inp)` entry. |
| `finished_at` | `str` | ISO-8601 UTC timestamp at `agent.run(inp)` exit. |

## CLI usage

```bash
.venv/bin/python src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py \
    --provider gemini \
    --model_id gemini-3.1-flash-lite-preview \
    --force_model wavenet \
    --max_rounds 10 \
    --is_trial \
    --trial_strategy snapshot \
    --trial_portion 0.1 \
    --train_portion 0.1 \
    --run_name v1 \
    --workspace ./siderius_workspace \
    --file_index 6 \
    --task_composition /path/to/task/composition.yaml \
    --data_dir /path/to/task/data
```

The CLI is a standalone invocation surface with a broad flag set; it does not
replace the composed chain. `--task_composition` and `--data_dir` are required;
the task's metric/data/Health bindings are resolved before any LLM call. The
former scientific comparison caller belongs to the external experiment
repository. Result lands at `{workspace}/run_output_{run_name}.json`.

**Limitations of standalone CLI use** (vs workflow-driven):

- **No `seed_records`** — the CLI has no flag to inject prior experiment history, so round 1 starts cold.
- **No `expert_advice` structured object** — the `--expert_advice` flag takes a string only; structured `ExpertAdvice` requires the Python API.
- **No `plan_overrides`** — the CLI cannot force-pin specific hyperparameters.

### CLI arguments (key subset — full list via `--help`)

| Argument | Type | Default | Description |
|---|---|---|---|
| `--provider` | `str` (`gemini` \| `openai`) | `gemini` | LLM provider for the planner sub-call. |
| `--model_id` | `str` | `gemini-3.1-flash-lite-preview` | Model ID for the planner. |
| `--reflect_provider` | `str` (optional) | `None` | Optional separate provider for the reflector. |
| `--reflect_model_id` | `str` (optional) | `None` | Optional separate model for the reflector. |
| `--expert_advice` | `str` | `"None"` | Initial human-expert advice as a string (legacy CLI shape). |
| `--max_rounds` | `int` | `10` | Maximum rounds. |
| `--force_model` | `str` (registry key \| plugin type \| `"auto"`) | `"auto"` | Force a specific architecture. |
| `--seed_plugin_path` | `str` (optional) | `None` | Path to a plugin `.py` for plugin model_types. |
| `--run_name` | `str` | `"test_run"` | Run name. |
| `--workspace` | `str` | `./siderius_workspace` | Workspace root. |
| `--is_trial` | flag | `False` | Enable trial-explore mode. |
| `--trial_strategy` / `--trial_portion` / `--train_portion` / `--target_files` / ... | various | various | Mirror the schema fields above. |
| `--file_index` | `int` | `6` | Validation file index (formal mode). Ignored under `--is_trial` per `feedback_no_file_index_in_trial`. |
| `--order_strategy_override` | `str` (`shuffle` \| `sequential`) | `None` | Force the training sample visitation order for every round, overriding any agent proposal. Omit = the agent decides, falling back to `shuffle`. |
| `--file_order_override` | `str` (comma-separated) | `None` | File visitation **order** for `--order_strategy_override sequential`, e.g. `4,6,5,9,7,8`. Order is preserved as written; must be a full permutation of the resolved `DataScope`. Range syntax (`4-9`) is rejected — a range cannot express an order. Omit for ascending file index. |
| `--progress_bar` | flag | `False` | Stream subprocess tqdm output. |
| `--task_composition` | `str` (path) | required | YAML task-composition manifest. It binds this run's task data path, dataset profile, metric, declared secondaries, Health family and task context before any LLM call; the manifest is composed once and shared with the run-scoped binding. `--data_dir` is also required. |

## Python API usage

```python
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig

inp = HyperparamTuningInput(
    model_type="attn_unet",  # from upstream proposal
    seed_plugin_path="/abs/path/to/agent_generated/models/attn_unet.py",
    expert_advice=proposal_output.expert_advice,  # structured ExpertAdvice
    seed_records=[baseline_record],  # prior experiments
    max_rounds=10,
    attempts_per_round=3,
    attempts_per_formal_round=5,
    max_fail_rounds=3,
    # Trial mode + sampling:
    is_trial=True,
    trial_strategy="snapshot",
    trial_portion=0.1,
    train_portion=0.1,
    # Pre-flight gates:
    trial_time_budget_minutes=20.0,
    trial_vram_budget_gb=8.0,
    data_dir="/home/klz/Data/TIDMAD",
    # LLM routing:
    llm_provider="gemini",
    llm_model_id="gemini-3.1-flash-lite-preview",
    reflect_provider="openai",  # split planner / reflector
    reflect_model_id="gpt-5-mini",
    # Storage:
    storage=StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="./workspace", run_name="iter_001"),
    ),
)

agent = HyperparamTuningAgent()  # bridge_factory + sandbox_factory inferred
output = agent.run(inp)  # -> HyperparamTuningOutput
```

This is an illustrative typed input, not a standalone runnable launch: the
caller must establish the task-composition and bound metric context before
`agent.run(inp)`; the CLI/workflow examples above perform that binding.
The constructor accepts `bridge_factory` and `sandbox_factory` (for test injection — both default to the real `LLMBridge` and `TidmadSandbox` classes; pseudo-mode tests inject `RecordingLLMBridge` / `RecordingSandbox`). The LLM bridge is built **lazily inside `run()`** (not at construction) because it depends on input-field LLM routing — the workflow uses `agent.set_run_context(...)` to deposit token-usage audit args that get applied right after the lazy bridge build.

## Storage outputs

- **Run output JSON**: `{storage.local.workspace}/run_output_{run_name}.json` — the validated `HyperparamTuningOutput` dumped at the end of `run()`. Contains `all_records` (the full per-round audit trail) plus the best run + score tables + gate-exhaustion / physical-rejection info. The workflow reads this and converts it to `ModelRunSummary` via `tuning_output_to_model_run_summary` for the next interpretation pass.
- **Run config snapshot**: `{workspace}/run_config_{run_name}.json` — the resolved input config (after defaults + plan-overrides). Audit log for reproducibility. Since V19 PR 3 it also stamps the structured-health-feedback CONTROL POLICY (`enable_structured_health_feedback`, `health_feedback_history_window_iterations`, `health_feedback_history_max_entries_per_model`) — policy only: per-round gate evidence stays in the experiment records and the interpretation digest, never duplicated here. The same three values join the run-invariants lock at all three lock sites (tuner / workflow / chain runner); a changed value on the same workspace fails startup with a `RunInvariantsViolation` naming the field and both values, and a legacy (pre-PR3) lock resolves to `False` / `3` / `8`.
- **Per-round trial config**: `{workspace}/trial_config_{run_name}_round{N}.json` — the resolved `TrialConfig` for round N, written before the training subprocess starts. Used by `core.resume.restore_prior_state` for crash-recovery.
- **Token usage**: `{workspace}/token_usage.jsonl` (when `set_run_context` is called by the workflow) — append-only log of every LLM call's token cost.
- **Output-retention receipts**: `{workspace}/model_output_retention_receipts.jsonl` — append-only exact-attempt file identities, digests, sizes and retained/retired dispositions. A missing or invalid task inventory is a fail-closed infrastructure stop, not a model verdict.
- **Training-checkpoint receipts**: `{workspace}/training_checkpoint_retention_receipts.jsonl` — append-only exact-attempt `.pth` dispositions, written after the tuner run output. The certified `.pt` blob and scored record remain for offline review.
- **Per-run plugin dir**: `{workspace}/plugins/{run_name}/` — copy of `seed_plugin_path` written at run start so the training subprocess can find the plugin via `SIDERIUS_PLUGIN_DIRS`. Only populated when `seed_plugin_path` is set.
- **Per-sample model outputs** (intermediate): the task's `TaskOutputArtifactCapability` enumerates exact attempt-owned paths, including sidecars. The parent validates containment, measures hashes, and applies `retain_model_outputs` in the inference/scoring/Health `finally` block. A composed task without this capability refuses rather than silently skipping cleanup. Only an uncomposed indexed compatibility run uses the existing naming authority's *attempt-scoped* pattern; the old experiment-wide cleanup glob is not used. The output policy does not affect model checkpoints or scored evidence. See [model-output retention](../../../docs/reference/model-output-retention.md).
- **Evaluation metric** (Step 06, runtime-only; bound seam Step 10 P1): the run's `EvaluationMetric` handle (`execute_tools/evaluation_metric.py`) is acquired ONCE at run scope by the zero-argument `resolve_run_metric()` resolver. A **composed** run (launched with this node's own `--task_composition <manifest>`, or with the chain launcher's) supplies the metric declaration at the composition edge, so a composed classification or regression run never infers a scientific task from legacy geometry. A run with no bound metric is refused (`NoRunMetricError`) rather than silently inventing one. Still no config file read here; the scoring subprocess reconstructs the same instance from its `args.task_manifest` input. What reaches storage is the additive per-record payload above (`metric_result` / `metric_refusal`).

- **Observational secondary metrics** (Step 10 / P2b, runtime-only): acquired at the SAME site as the primary, as `run_secondary_metrics = resolve_bound_run_secondary_metrics()`. Unlike the primary there is NO legacy branch — nothing to fall back to, because "this run declared no secondary" is the answer rather than a default — so an un-composed run gets `()` and nothing anywhere derives a secondary from task identity. A composed run gets what its manifest's optional `secondary_metrics:` section declared, resolved at the composition edge by the same `_compose_metric` authority the primary uses. They are evaluated by `_evaluate_secondary_metrics` immediately after the primary result inside the same scoring `try`, transported onto the record by the three carriers above, and stamped onto the output as `secondary_metric_specs` (the DECLARED set, in manifest order, written by the same single writer as `metric_spec` — and on the degraded partial-output branch too, because which secondaries a run declared is a launch fact that does not stop existing because the tuner later failed). They are OBSERVATIONAL: `run_order` is the run's ONE order authority and it interprets the PRIMARY spec only, which an AST census over the whole lifecycle enforces. **Step 12 / PR-12d**: on the `TASK_OWNED` scoring route (see *Scoring routes* under Round-loop structure below) the tuner cannot evaluate them in-process — the deliverable and evaluation scope live only in the scoring child — so the child computes them and reports them in its output; `_adopt_child_secondaries` (`execution.py`) re-types them into the same `MetricResult` / `NotScoreableResult` carriers. Total by construction: anything the anchor route already produced wins unconditionally, so the record has one shape regardless of which route ran.

## Key behavioral notes

### Execution infrastructure the tuner depends on (Step 11)

Four things changed underneath this node. None alters its interface, and an
un-composed run behaves exactly as before; they are recorded here because
they change what its subprocesses read and what its records carry.

* **The physical data root is transported** (C4). Training and inference
  receive `--data_dir`, and scoring receives `--raw_data_dir`, emitted ONLY
  when the run bound a root. Before this, none of the three carried one and
  every child fell back to the import-time `TIDMAD_DATA_DIR` — so a composed
  run read TIDMAD's data whatever it had declared. A composed run with no
  declared root is now refused at the binding edge.

* **The scoring child composes the run's DECLARED metric** (C5). It receives
  `--task_manifest` when composed and re-composes the metric section through
  the same authority the parent used, instead of unconditionally deriving
  TIDMAD's. There is no fallback: a metric that cannot be composed terminates
  the scoring subprocess rather than silently scoring with TIDMAD's.

  **Step 12 / PR-12bc C3 widened the manifest transport to all three
  children.** Step 11 emitted `--task_manifest` to scoring alone, which was
  right for the METRIC and wrong for the task data path: training and
  inference resolve a transported `--task_data_path_id` through the process
  registry, and that registry holds only what the child's own bootstrap
  imported — the three built-in implementations. An out-of-tree task therefore
  resolved in the parent and was unresolvable in every child the parent
  spawned. All three children now resolve through one authority
  (`workflows.task_composition.resolve_child_task_data_path`), which composes
  the declaration from the transported manifest when the id is not built in.
  The emitter is still keyed on the binding, so an **un-composed** run's child
  argv is unchanged.

* **A host-RAM OOM is no longer invisible** (C2). `oom_host_ram` was produced
  by the sandbox and read by nobody, so a host-OOM training failure fell
  through every failure branch and was carried on as a normal outcome. It now
  reaches the ordinary `error_training` / `error_inference` records and
  `next_attempt()`. **Planner-facing prompt bytes are unchanged**: the record
  carries no `_oom` suffix, so the "OUT-OF-MEMORY NOT ATTRIBUTED" note does
  not render for it.

* **Declared task-code integrity is terminal, not an attempt outcome.** A named
  `LocalCodeError` (also through an explicit exception cause) propagates through
  framework-owned skill/attempt catches. The root workflow writes
  `.chain_halted` with reason `code_package_integrity` and exits 3 before retry,
  next iteration or scoring promotion. It does not invent a tuner status or
  reuse the evidence-channel-specific `infrastructure_abort` category. Ordinary
  candidate errors, provider retries, Health policy and budgets are unchanged.
  See [package transport and limits](../../core/local_code/README.md).

* **Every record carries `task_composition_fingerprint`** (C8). Stamped at
  `_emit_record`, the single validate-and-persist seam. `None` for an
  un-composed run. A composed run refuses at ingress any restored record or
  seed it cannot certify as its own.

* **Every record of a LABELLED run carries `experiment_arm`** (arXiv U1,
  #254). Stamped at the same `_emit_record` seam, but ONLY when the input
  carries a label, so an unlabelled run's on-disk summary entries are
  byte-identical to pre-U1. Every emission site passes it explicitly
  (`experiment_arm=agent_input.experiment_arm` — the `candidate_id`
  precedent; a census over the whole node refuses a site that omits it),
  and the per-model lock pins the same value. A labelled run refuses at
  ingress any restored record or seed that carries no label or a different
  one; an unlabelled run is untouched by the rule. The label is opaque: the
  tuner never reads its value.


### GPU admission and failure attribution (V20 PR B)

Two related changes, both about **not blaming a candidate for something
it did not cause**. V19 told the planner to shrink a model that was the
right size, because a CUDA OOM raised while a neighbouring chain held
the card was read as a statement about the candidate.

**A GPU phase can now be refused before it starts.** Before training and
before inference, driver-visible occupancy is measured and the phase is
admitted or refused. A refusal is an *environment* condition:

| Record | Meaning |
|---|---|
| `status = "skipped_resource_admission"` | the environment did not permit starting this phase |
| `memory.resource_type` | `"gpu_memory"` |
| `memory.reason_code` | `insufficient_headroom` \| `measurement_unavailable` \| `policy_unavailable` |
| `memory.admission_evidence` | every figure the decision used, for audit |

Deliberately **not** `skipped_time_risk`: that status already carries
three distinct meanings and feeds the time-factor statistics, so a
fourth producer would pollute numbers that mean something else.

**Posture is `trial | formal`** (`admission_mode`, default `trial` — the
same spelling as `time_mode` and `active_mode`; an unrecognised value is
rejected as a misconfiguration rather than assumed):

| | `trial` | `formal` |
|---|---|---|
| measurement unavailable | warn, proceed | refuse |
| policy unavailable | warn, proceed | refuse |
| **insufficient headroom** | **refuse** | **refuse** |

Headroom is a measured fact, not a posture — a trial run does not get to
disbelieve arithmetic.

**An LLM or provider failure is infrastructure too** (F-SCANF-2). The
`skipped_infrastructure_failure` status and its reason vocabulary existed
and were correct, but the map covered only admission reasons, so a provider
outage reaching the planner or the reflector was recorded as an ordinary
candidate failure — budget consumed, and a memory narrative telling the next
planner "Do not repeat the failing configuration unchanged". An API timeout
arrived at the model as a verdict on the candidate, which frozen `D-FAIL-1`
/ `D-FAIL-5` forbid.

The attempt handler now asks `records.classify_attempt_failure_disposition`
for the record's posture. Anything that is not a declared provider transport
failure keeps its previous posture exactly:

| Record | LLM / provider transport failure | any other exception |
|---|---|---|
| `status` | `skipped_infrastructure_failure` | `error` |
| `counts_toward_attempt_budget` | `False` | `True` |
| `memory.reason_code` | `llm_provider_unavailable` | *(key absent)* |
| `memory.memory_update` | "Do NOT change the configuration in response to this…" | "Do not repeat the failing configuration unchanged…" (unchanged wording) |

The transport surface is declared by the module that owns it —
`agent.llm_bridge.LLM_PROVIDER_TRANSPORT_ERRORS`, matched by `isinstance`
so a provider-SDK subclass nobody enumerated still classifies correctly.

**Scope**: this is the REPORTING half of "an infrastructure failure must not
consume scientific opportunity". Whether such a failure should also be
RETRIED into the same scientific opportunity is `D-FAIL-2`'s accounting
half, which lives in the attempt loop's control flow and is unchanged here.

**Accounting.** A refusal consumes the current attempt slot (planning,
pre-flight and admission really ran, and not consuming it risks refusing
forever while the device stays busy) but is **not** a candidate failure:
no score, no negative planner evidence, no incumbent update, no retry.
If every attempt in a round is refused, the round produces no
authoritative result and no candidate is blamed.

### Pre-phase GPU measurement (V20 PR C2)

**PR B's gate could refuse, but had nothing to refuse on.** It read the
requirement through `getattr(sandbox, "measured_requirements", None)`, and
no production code set it — so formal admission reported
`policy_unavailable` on every run. C2 produces that requirement.

**On every FORMAL attempt, before any formal GPU work**, the tuner runs a
bounded, isolated measurement of the exact candidate on the current card
and consumes a single typed disposition:

```text
formal attempt
  -> planned identity + request nonce
  -> isolated worker (real model, optimizer, forward, backward, step)
  -> parent-side driver-visible process-tree sampling
  -> realized identity returned and checked against the planned one
  -> typed classification
  -> authoritative requirement, or refusal with a named reason
  -> PR B admission
  -> ONE disposition
```

The tuner calls `_handle_prephase_gpu_measurement` and reads only the
disposition; identity comparison, classification, authority validation and
admission all live in `core/runtime_control/prephase_admission.py`.

**When it does NOT run**, and these are the only two cases:

| Condition | Behaviour |
|---|---|
| trial round | not measured — O-7 governs formal execution, and trial admission already proceeds while recording what it could not prove |
| `sandbox.device_identity` is not a `DeviceIdentity` | not measured — no card means nothing to measure and nothing for admission to decide, the same conclusion `_admission_refusal` reaches. CPU and pseudo runs are unaffected. |

A composed external task supplies a typed `TaskProbeDataSpec`. The isolated
worker verifies the task-composition fingerprint, rehydrates the task-owned
training scope, and obtains one real batch through `TaskDataPath`. The same
projection feeds both the lightweight VRAM preflight and this authoritative
Formal measurement. Legacy un-composed runs keep their existing physical-array
loader. A composed task with an invalid or unavailable projection fails closed;
it is never silently measured with TIDMAD data or a synthetic batch.

There is **no flag**. It is not optional on a formal attempt with a real
device.

**Dispositions**, each filed under one of PR B's three existing refusal
lanes, with the disposition itself preserved in `memory.admission_evidence`:

| Disposition | Lane |
|---|---|
| `PROCEED` | — the requirement is attached and training starts |
| `STOP_OVER_CAP` | `insufficient_headroom` |
| `STOP_MEASURED_OOM` | `insufficient_headroom` |
| `STOP_TIMEOUT` | `measurement_unavailable` |
| `STOP_MEASUREMENT_UNAVAILABLE` | `measurement_unavailable` |
| `STOP_PROBE_HOST_MEMORY_EXCEEDED` | `measurement_unavailable` |
| `STOP_INFRASTRUCTURE_FAILURE` | `measurement_unavailable` |

`STOP_PROBE_HOST_MEMORY_EXCEEDED` is named for the **probe**, not the run.
It means the measurement process exceeded its host-RSS allowance, which is a
CPU fact and never a VRAM verdict — it produces no GPU requirement and PR B's
capacity gate is not called at all.

**Accounting on every stop** — identical across all six, and the same rules
the PR B refusal already follows: the attempt is consumed, no completed
round is recorded, no scientific blame attaches to the candidate, no
proposal shrinking is advised, and there is no same-attempt retry. Only the
existing outer attempt budget may produce another attempt.

**Data access is bounded (V20 PR C2 / D-C2-12).** The worker reads exactly
the `batch_size x segmentation_size` samples its batch needs, by HDF5
slicing — **not** through `load_probe_batch`, which materializes the whole
2,010,000,000-sample channel before `max_segments` applies and cost 24.10
GiB of host RSS in the first gate attempt. The tensor delivered to the
device is byte-identical to the production loader's; only the host-side
path differs, and the host path is not the GPU requirement. There is no
fallback: bounded access failing is reported as an infrastructure condition.

**Formal training has no stop rule, and none can be configured.** A Gate's
formal arm stops when its driver-visible peak has settled (V20 PR C2 /
D-C2-20), but that control lives entirely in the validation harness. A
production round trains for its planned epochs over its planned sample set,
exactly as before: no step event is written, no stop signal is read, and no
CLI flag or config key exposes the mechanism. If you are looking for a way
to bound a production round's training, it is the epoch ceilings
(`--max_epochs`, or the per-role `--trial_max_epochs` /
`--formal_max_epochs`, D-BUD-6) and the sample set — not anything in C2.

**Short phases are made observable (V20 PR C2 / D-C2-13).** A phase shorter
than the driver-sampling cadence yields **zero** in-phase samples and is
unmeasurable at any candidate speed — Gate 2 Lite-A c7 ran an inference
phase in 0.138 s against a 0.25 s cadence. Two rules close that:

* the worker waits for the parent to confirm sampling is **active** — proved
  by a real driver sample having succeeded — before opening a timed phase;
* the phase repeats its **exact** workload (same model, batch, dtype and
  semantics) until the **parent** signals that enough readings have landed.

**The parent owns the stop condition**, because it is the only component
that knows how many valid in-phase samples were actually captured. There is
deliberately **no** maximum-repetition setting: a repetition count cannot
express a duration target when the per-repetition cost is unknown, and a
40-repetition ceiling once ended an inference phase after 0.344 s still
holding one sample. The same phase now needs ~135 repetitions and gets
them. The bounds are `max_phase_seconds` (60) and the global deadline.

Repetition is measurement protocol, not candidate identity, and it happens
only inside the disposable measurement worker — formal execution is
untouched. An authoritative phase now requires at least **3** valid in-phase
samples (`MINIMUM_AUTHORITATIVE_SAMPLES`); zero, one or two fail closed as
`INCONCLUSIVE_MEASUREMENT`. Reaching a bound without enough samples is also
`INCONCLUSIVE` — never a manufactured result, and never zero MiB.

Every phase record carries the observation evidence through the typed
result: `repetitions`, `required_samples`, `observed_in_phase_samples`,
`completion_reason` (`sample_target_reached` | `duration_bound` |
`deadline` | `single_pass` | `failed`), `max_phase_seconds`,
`observation_bound_reached`, `sampler_ready` and `sampler_ready_at`. An
artifact missing them is incomplete and its result carries no authority.

**Task inference measurement uses the production prediction stream (#615).**
When explicitly requested with `phase="inference"`, the worker requires a
composed task's evaluation scope. It constructs the model through
`execute_tools.inference_model.construct_inference_model`, including the
production task-cardinality resolution and existing constructor convention.
It creates no loss criterion, optimizer or device-resident target.
`task_inference_probe_batches` reads at most `inference_batches` real evaluation
batches at the declared inference batch size, preserving incomplete tail batches
and the task's batch ceiling. Missing or empty evaluation scope, a changed task
binding/fingerprint or a changed batch ceiling refuses; training data are never
substituted. Bounded refusal verification additionally binds the complete request,
source assembly, plugin sources, runtime and explicit device identity.

`execute_tools.inference_stream.prediction_stream` owns the forward, dtype
conversion, ordered CPU consumption and tensor lifetimes in both the measurement
and task execution. In particular, the previous output tensor and its last item
view can remain live at the next forward, matching the existing task execution
loop. `outputs_released` remains a historical diagnostic; zero no longer means
an incorrect lifecycle. `realism.inference_data` records actual storage/input
dtypes, input/output shapes and selected/consumed sample counts. A sampling hold
observes a resident real output; it does not repeat the dataset to manufacture
coverage.

This bounded, pretraining measurement does not certify all data-dependent
branches or trained-weight behavior. Driver samples and allocator high-water
marks remain different instruments. Native `inference_preflight` policy now
measures the final refused inference batch when training passed and only the
inference VRAM estimate refused. Trial and Formal use the same adapter. The
original static evidence is immutable; a separate `inference_verification`
observation decides whether bounded evidence permits execution. Unknown evidence
stops as inconclusive; measured capacity refusal permits another attempt.

Setup and every evaluation forward use a synchronized reservation hold,
acknowledged by driver samples identified by request, phase and hold sequence.
Byte-exact peak reserved memory must still be resident during an acknowledged
hold; driver context overhead cannot mask an allocator peak released before
sampling. This cannot exclude arbitrary non-allocator transients or unseen
inputs. Source continuity is checked before/after structural inspection and
before/after measurement; trusted plugin mutation invalidates the observation.
Raw observations remain in the workspace, compact evidence in typed records.
The single extra worker consumes remaining preflight time, uses existing
RSS/cleanup bounds, and never overwrites the training requirement table.

Historical exp configurations explicitly select `mode: static_only`; there is
no task-name or provider-name fallback in infra. Training measurement identity
and repetition are unchanged. CUDA statistics and synchronization select the
actual device in both phases.

**Validation-only lifecycle trace (V20 PR C2).** The measurement worker and
the formal inference process can each record a set of named lifecycle
milestones — process start, imports, CUDA initialization, model
construction, model transfer, checkpoint load, per-batch input transfer,
the synchronized post-forward state with the output still GPU-resident, the
transfer to host, cleanup, and exit. Each milestone records the
driver-visible candidate-owned process-tree total through the **same**
`gpu_accounting.sample` primitive the production sampler uses, alongside
the allocator figures, the live input/output shapes and dtypes, the GPU
UUID, the candidate identity, the inference batch size and the exact Git
SHA.

It exists to locate a fixed **208 MiB (5.7 %)** difference between the
pre-phase inference measurement (3434 MiB) and formal inference (3642 MiB),
reproduced with zero spread across three alternating runs.

**It is off unless explicitly switched on, and production never switches it
on.** There is **no CLI flag** and no config key. The only way to enable it
is the environment variable `SIDERIUS_C2_INFERENCE_MILESTONE_TRACE`, whose
value must be a JSON channel naming an explicitly writable artifact path,
the device UUID and a run id — never a bare boolean:

```text
SIDERIUS_C2_INFERENCE_MILESTONE_TRACE='{"path": "/tmp/.../trace.ndjson",
                                        "device_uuid": "GPU-...",
                                        "run_id": "...",
                                        "max_traced_batches": 2}'
```

With the variable absent no channel is parsed, no file is created, no
driver query is made, and neither process holds a tracer at all — the
absence of the tracer **is** the disabled state, so there is no "enabled"
flag to get wrong. Tracing **does not alter admission authority**: it
produces no requirement, feeds no gate, and changes no disposition. An
unwritable path fails as validation infrastructure
(`MilestoneTraceUnavailable`), never as a measurement outcome and never as
a property of the candidate.

**Resource cost.** One extra bounded GPU execution per formal attempt:
setup plus 4 training steps, deadline 600 s (`PREPHASE_MEASUREMENT_DEADLINE_SECONDS`),
worker soft budget 480 s, host-RSS ceiling shared with PR A's pre-flight.

**Failure attribution.** When a phase *does* fail on device memory, the
record may carry `failure_attribution` — one of
`candidate_gpu_capacity`, `gpu_contention`, `host_memory_pressure`,
`external_termination`, `unknown`. **Only `candidate_gpu_capacity`
authorises advice to reduce model size, batch size or segmentation
size.** Absent means `unknown`, which carries no such authority, so every
record written before V20 PR B behaves conservatively. The planner
prompt suppresses shrink instructions for any out-of-memory the
measurement did not attribute to the configuration.

**Cold start (D-B5).** PR B consumes an applicable authoritative
measurement; it does not produce or promote one — that is PR C. So in
`formal` mode a candidate with no applicable measurement is refused with
`measurement_unavailable`. This is the documented cost of keeping one
measurement authority rather than two.

**On a new GPU host.** Measurements are bound to a GPU UUID, so nothing
measured on another card is applicable — a fresh machine legitimately has
no authoritative measurement for any candidate. Consequences:

- `trial` proceeds and records that it proved nothing, so a new host is
  usable immediately for exploration.
- `formal` refuses every candidate with
  `reason_code="measurement_unavailable"` until an applicable measurement
  exists. **This is the guard working, not a failure**, and it is not a
  statement about any candidate.
- Getting to a working `formal` run means: resolve the new UUID,
  obtain applicable phase-specific measurement evidence, and resolve the
  aggregate ceiling against actual device capacity. An omitted operator ceiling
  uses measured capacity; an explicit/environment ceiling and declared host
  quota can tighten it. No local-machine numeric default is assumed. See
  [the aggregate ceiling contract](../../core/runtime_control/gpu-ceilings.md).
  The operator sequence is [`docs/getting-started/installation.md`](../../../docs/getting-started/installation.md)
  → "Moving to a different machine or GPU".

**No CLI argument was added or changed by V20 PR B.** Admission is
configured on the run rather than through a flag, and no default moved:
`admission_mode` defaults to `trial`, which admits and records that it
asserted nothing.

### Data-ordering resolution (V19 PR 2)

Ordering has three levels, and only one of them describes execution.
This node is where they are combined — **exactly once**, by
`agent/schemas/ordering.py::resolve_ordering`. Nothing downstream
re-derives precedence: the training subprocess receives the resolved
values and has no knowledge of how they were reached.

**The governing invariant:**

> Only resolved configuration values describe the executed experiment.
> Proposed values describe agent intent; override values describe
> operator control. Downstream attribution and interpretation must use
> the resolved values.

Four-part contract:

1. **Resolution.** Each round, the agent's `ExperimentPlan` proposal is
   combined with the operator's chain override under
   `operator override > agent proposal > default ("shuffle")`. The
   decision is printed as a `[data_order]` line naming all three
   levels; the engine prints its own per-epoch `[data_order]` line with
   the resolved values and epoch seed.

2. **File-order semantics.** `file_order` is meaningful only for
   `sequential`, and only alongside an explicit `sequential` strategy at
   the same level. The resolved order must be a **full permutation** of
   the resolved `DataScope` — ordering reorders the scope, never changes
   it. A subset, an out-of-scope index, or a duplicate is a hard error,
   not something to normalize. When `shuffle` resolves,
   `resolved_file_order` is `None`; a proposed sequential order is *not*
   silently retained.

3. **Rejected proposals are recorded, never dropped.** A structurally
   invalid ordering proposal from the LLM does not kill the round — it
   falls back, matching the established `ExperimentPlan.with_defaults`
   treatment of any bad trial field. But the fallback is **not silent**:
   the record keeps the proposal, `ordering_proposal_rejected=True`, and
   a reason that distinguishes *"the ordering itself was invalid"* from
   *"the ordering was fine but another plan field failed"*. A rejected
   proposal is materially different from agent silence, and
   `ordering_resolution_source` is never `agent_proposal` for one — so
   an override is never attributed to the agent.

4. **What is persisted where.** Three artifacts, three jobs:
   `run_config_{run}.json` holds the run-level **override policy**;
   each `ExperimentRecord` holds **that round's** resolved ordering plus
   full provenance; the iteration manifest holds
   `ordering_by_experiment`, a **round-keyed list**. Ordering may
   legitimately differ between rounds when no override is in force, so
   none of these collapse to a single iteration-level value. The
   operator override — not the resolved value — is pinned in the
   run-invariants lock.

5. **Five provenance states**, exposed by the ordering reader. The first
   three identify selected effective configuration, not proof that any or all
   samples were visited. `ordering_resolution_source` retains the selection
   on success, mode collapse, and training/inference/scoring errors, including
   CUDA/host OOM and malformed training results. Outer attempt errors retain it
   once resolution has happened, even when later preparation raises before
   training. Each attempt starts with no captured ordering.

   | Source | Meaning | `resolved_order_strategy` |
   |---|---|---|
   | `operator_override` | operator-forced ordering selected | the forced value |
   | `agent_proposal` | validated agent proposal selected | the proposed value |
   | `default` | default selected, no usable proposal or override | `shuffle` |
   | `legacy_default` | unstamped non-preflight record; compatibility fallback, not observed traversal | `shuffle` (reconstructed) |
   | `not_executed` | named preflight skip: `skipped_oom_risk`, `skipped_time_risk`, or `skipped_schema_violation` | `None` |

   `not_executed` never fabricates a `shuffle` value: inventing one for
   an attempt that visited no data would misreport the run. The three named
   preflight producers remain unstamped; the reader preserves any proposal or
   override context already present without inventing it. Post-resolution error
   records preserve rejected proposals and operator overrides as distinct facts.

   Known limitation ([#447](https://github.com/Galileo-Sandbox/SIDERIUS/issues/447)):
   pre-resolution failures and resource/infrastructure admission skips remain
   unstamped and can still read as `legacy_default`, as can historical errors.
   Resource admission can refuse before training or before inference after
   training, so its status alone cannot establish `not_executed`. No historical
   record is rewritten, no ordering is guessed from params, and no new record
   is created for terminal paths that did not previously emit one.

Design: `docs/design/v19_priorities/pr2_data_ordering.md` §3.6–§3.9.

### Chain formal-incumbent reference

Two related inputs govern how the tuner's two formal delta gates
(``skip_formal_min_delta``, ``bypass_formal_time_budget_min_delta``)
compute their reference score:

- ``current_run_best_formal_score`` (``float | None``, default
  ``None``) — the chain-level best HealthGate-VALID FORMAL score
  reconstructed from prior committed iterations of the same workspace
  by ``core/resume.py::restore_prior_state`` and delivered here
  through the ``local_validated_model`` protocol. ``None`` = no
  eligible incumbent exists (fresh chain, or nothing commit-time
  valid).
- ``enable_chain_incumbent_formal_gates`` (``bool``, default
  ``False``) — a **consumption-only** switch. It does NOT control
  reconstruction or persistence.

Three-part contract:

1. **The reconstructed chain incumbent.** Regardless of the flag,
   ``core/resume.py`` walks committed iterations, verifies
   ``run_output_sha256`` when present (fail-closed on mismatch), and
   selects the best commit-time-VALID formal score under the §3.3
   rules. The reconstructed value + full provenance is delivered on
   this node's input, printed at ``[resume] incumbent carry-over
   …``, echoed on the tuner startup ``[chain_incumbent]`` line, and
   persisted in every iteration's manifest under
   ``chain_incumbent_source``.

2. **Coupling ON (flag=True).** The two formal delta gates use
   ``chain_incumbent + fixed_delta`` as their thresholds:
   ``resolved_skip_formal_threshold = current_run_best_formal_score +
   skip_formal_min_delta`` (and symmetrically for bypass). A trial
   winner falling below skip → skip the formal round; a trial winner
   crossing bypass → bypass the time-budget gate on the formal.

3. **Coupling OFF (flag=False; DEFAULT).** The reconstructed
   incumbent is still delivered on the input and still stamped in
   ``run_config`` / manifest / provenance — but the resolver treats
   the reference as ``None``, so both resolved thresholds are
   ``None`` and neither incumbent-based gate can fire. **OFF is
   NOT a fixed-``0.0`` reference mode** — the pre-V19 default of
   ``0.0`` is unrepresentable in this schema and unreachable via any
   supported configuration; OFF simply skips consumption of the
   reconstructed value.

Rollback path: omit ``--enable_chain_incumbent_formal_gates`` on
any launcher (equivalently: leave the schema field at its default
``False``). Reconstruction and audit trails keep working; only gate
consumption stops. See
``docs/design/v19_priorities/pr1_chain_incumbents.md`` §3.2 / §3.4
for the full design rationale.

- **Round-loop structure**: each round runs **plan → resource check → train → infer → score → reflect**:
  1. **Plan** — `bridge.plan(...)` produces an `ExperimentPlan` (hyperparameters + `is_trial` choice). Subject to `plan_overrides`.
  2. **Resource check** — `evaluate_vram_skill` plus the selected time-admission authority. ``forecast`` invokes `evaluate_time_skill`; ``measured`` defers the decision to executing-device runtime verification. A refusal counts as an *attempt* (not a *round*); the round retries up to its budget.
     For a composed attempt, the VRAM worker materializes one full task-valid
     batch from the already-resolved training scope. It verifies the task
     composition fingerprint before reading data. Legacy un-composed attempts
     retain the shape-and-dtype synthetic batch.
  2b. **Pre-phase GPU measurement** (V20 PR C2, **formal attempts with a real device only**) — a bounded isolated measurement of the exact candidate on the current card, feeding PR B's admission gate. A stop consumes the attempt and starts no GPU work. See *Pre-phase GPU measurement* above.
  3. **Train** — `training_skill` runs as a subprocess via `TidmadSandbox`. Writes the trained model + denoised outputs. **Step 07a**: the tuner's `eval_sample_set` reaches the trainer (`--eval_sample_set_json`), which evaluates the same run-resolved objective on it after every completed epoch (R3, transactional: model / optimizer / objective state and every RNG restored) and emits `training_history` beside the three legacy keys; the tuner interprets the results through the typed boundary `_interpret_training_status` → `interpret_training_results(raw, expected_validation=eval_sample_set is not None)` (a contract violation → the existing `error_training` record path) and derives `training_diagnosis` once.
  4. **Infer** — `inference_skill` runs as a subprocess. Writes denoised HDF5s.
  5. **Score** — the frozen TIDMAD scorer runs **through the run's evaluation-metric handle** (Step 06): `sandbox.evaluate_metric(run_metric, …)` validates the DataScope, runs the metric's scoreability contract over the deliverables the scorer would open, and only then calls `scoring_utils.score_vector` (unchanged arithmetic) → `denoising_score` / `file_vector` / `metric_result`. A deliverable the contract refuses never reaches the scorer: it becomes an `error_scoring` record with `failure_type='not_scoreable'` and a structured `metric_refusal`. **Scoring routes (Step 12 / PR-12d, D4b)** — `policy.py::ScoringRoute` / `resolve_scoring_route` NAME which of three paths an attempt actually takes: `TASK_OWNED` when a composed task supplied its opaque evaluation scope, even if it also supplied an anchor artifact; `ANCHOR_NORMALIZED` for an uncomposed compatibility run with a legacy `SampleSet` and anchor map; or `SUBPROCESS_LEGACY` when neither authority is present. Exact per-attempt outputs are retired after scoring and Health unless `retain_model_outputs=True`.
  6. **Reflect** — `bridge.reflect(...)` analyses the round's result and updates memory for the next plan call.
- **Two LLM sub-calls per round** (planner + reflector). When `reflect_provider` / `reflect_model_id` are set, the two go through separate `LLMBridge` instances — enables splits like "cheap planner + smarter reflector" or "small planner + large reflector" without changing prompts.
- **Attempt vs round distinction.** A *round* is a slot in the optimization history that produces a final record. An *attempt* is one LLM-plan + downstream-execution attempt. Each round can consume up to `attempts_per_round` (or `attempts_per_formal_round` for the forced-formal round) attempts before being marked failed. Attempts that fail at the pre-flight gate cost LLM tokens but no GPU time; attempts that reach training but fail (OOM, training error) cost both.
- **`max_fail_rounds` termination trigger.** When this many *consecutive* rounds exhaust their attempt budget without producing a successful record, the tuner exits with `termination_reason="aborted_fail_rounds"`. The downstream interpreter reads `consecutive_fail_rounds_at_exit` to recognize this exit.
- **Force-formal-round mechanic.** When `force_formal_round=True` (default), the **last** round in the loop has `plan.is_trial` forcibly set to `False` so it runs on the full dataset. The `formal_round_strategy` controls how that round's config is built: `full_clone` (re-run best trial verbatim), `hybrid_params` (best-trial hyperparams + formal sampling), `independent` (planner proposes fresh), or `inherit_best_train_plus_formal_eval` (best train + formal eval scope).
- **Wall-time admission has one authority per role.** Trial and Formal independently select ``forecast`` or ``measured``. The default ``measured`` posture skips advance time admission and enforces the budget from executing-device verification. ``forecast`` invokes `evaluate_time_skill` and leaves in-process verification record-only. An unavailable selected authority refuses; the system never falls back to the other authority.
  - ``runtime_verification_max_wall_seconds`` optionally extends the adaptive verifier's observation window for workloads with slow individual optimizer steps. It does not change Trial or Formal budgets, and the observed verification steps are the first production training steps rather than a duplicate probe. Omit it to preserve the verifier's default window.
  - **C8c (2026-07-30) — standalone time evaluation still classifies evidence through the shared `RuntimeDecisionPolicy`.** When a workflow explicitly selects `forecast` admission, that workflow-level selection accepts the skill's already-computed `over_effective_budget` comparison as authoritative and does not resolve `REQUEST_PROBE`; otherwise measurement would become an undeclared second authority. Under `measured`, the advance skill is not called and RT2 verification owns admission. An uninterpretable selected channel is an execution-system failure, never a candidate-level "infeasible". `evaluate_vram_skill` remains independent and uses architectural pattern tagging (`TIME_FACTOR_THRESHOLD`, `VRAM_FACTOR_THRESHOLD`) and a per-pattern memory budget.
  - **V21 PR G (2026-08-10) — the time gate prices inference at the batch that will actually run.** The feasible VRAM-gate return's probe-derived `inference_batch` is captured into `active_params` (`:4696`) before the time gate fires, and `_run_time_preflight` forwards it (the `**active_params` splat) into `evaluate_time_skill`, which uses the SAME value for the hint→ms/step conversion and the inference estimator. This is a two-sided correction on the `training_warmup_x2.7_fallback` forecast branch: a plan is no longer falsely `skipped_time_risk` when the probed batch > 25, and no longer falsely admitted when it is < 25. No-hint callers (baselines, legacy scripts) keep registry-table pricing unchanged. `active_params` is rebuilt per attempt, so a stale hint cannot leak between attempts (0.R.4).
- **Sandbox subprocess for skill execution.** Each skill runs in a fresh subprocess via `TidmadSandbox` for memory isolation (PyTorch's CUDA context doesn't reliably release VRAM in-process). The sandbox communicates via JSON files in a temp dir and reports back through `get_summary()`. Pseudo-mode tests replace the sandbox with a `RecordingSandbox` that returns canned results without subprocess overhead.
- **Per-run plugin dir** isolates agent-generated plugins. When `seed_plugin_path` is set, the file is copied into `{workspace}/plugins/{run_name}/` and the training subprocess sees this via `SIDERIUS_PLUGIN_DIRS`. Plugins from one run don't pollute another's `MODEL_REGISTRY`. See [`docs/agent-reference/mechanisms/plugins.md`](../../../docs/agent-reference/mechanisms/plugins.md).
- **Hardware context per run.** `core.hardware_context.get_or_create(workspace, run_name)` writes a per-run manifest (device, total memory, hostname, availability). Subprocess children read this via file IPC instead of probing CUDA themselves. See Phase 6.6 §3.9.
- **OOM-skipped attempts are saved to memory but don't count as rounds.** This is deliberate: the LLM needs to see the OOM failure to avoid proposing the same config again, but it shouldn't burn round budget on a config that never trained.
- **Run-scoped plugins are NOT cached across iterations.** Each iteration starts with an empty `{workspace}/plugins/{run_name}/`. If the workflow needs to chain plugins, it re-copies `seed_plugin_path` each time. (See `feedback_no_file_index_in_trial` — `--file_index` is silently ignored in trial mode.)

## Dependencies

- **LLM**: two call signatures per round, both via `LLMBridge`:
  - **Planner** — `bridge.plan(...)` (internally a `bridge.generate(...)` against the planner system prompt). One call per attempt; total per run = `total_attempts`.
  - **Reflector** — `bridge.reflect(...)` (internally a `bridge.generate(...)` against the reflector system prompt). One call per *successful* round; total per run = `completed_rounds`.
  - Worst-case total LLM calls per run = `max_rounds × max(attempts_per_round, attempts_per_formal_round) + max_rounds = 50 × 5 + 50 = 300` planner calls + 50 reflector calls under the default budget envelope.
- **GPU**: **required** for the training and inference skills. The pre-flight `evaluate_vram_skill` uses architectural pattern tagging to estimate VRAM need; rejected configs never reach the GPU. The training subprocess respects `hardware_context.usable_cap_gb` as a hard ceiling.
- **External services**: none directly. The tuner is the only node that reads the TIDMAD dataset directly (via the training/inference subprocesses); `data_dir` must point at a real TIDMAD root for any GPU run. The `evaluate_time_skill` real-dataset warmup also reads 1 PSD from `data_dir` when set. No network calls outside `LLMBridge`. Filesystem: writes `run_output_{run_name}.json` + intermediate configs + token usage log + per-run plugin dir under the workspace; reads `data_dir` for TIDMAD HDF5s; spawns subprocesses via `TidmadSandbox`.

---

## Dataset Profile dependency (PR 02a, 2026-08)

`_validate_data_config` no longer restates the sample-shape legality rule.
It previously re-derived the legal `segmentation_size` list itself:

```python
sorted(d for d in range(100, psd + 1) if psd % d == 0 and d <= 100_000)
```

Under TIDMAD that is a **10,000,000-iteration loop on the error path**, and
a second place the rule could drift from the authority. It now calls
`dataset_config.valid_segmentation_sizes()` (sqrt enumeration).

**No CLI argument, default value or rejection behaviour changed.** The two
derivations produce the identical 36-entry list, so the error message —
which prints the legal values — is byte-identical. Pinned by
`tests/unit/execute_tools/test_step02a_c5_legality_dedup.py`.

### `segmentation_size` is the PLAN's, never the framework's (C12-P / B11)

`prepare_attempt` used to fill an absent `model_config.segmentation_size`
with a literal `10000` at two sites. It no longer fills it at all:

- **`_validate_data_config`** is given the size the plan STATED. A plan that
  states none has nothing here to check, and the call is skipped. Previously
  the geometry rule was applied to `10000` while the model was CONSTRUCTED at
  its config class's declared default (`config_cls(**model_config)` — wavenet
  40000, transformer 20000). Under TIDMAD both divide `psd_segment_length`
  evenly, so the check passed and the disagreement was silent.
- **`ScopeBuildRequest.task_parameters["seg_size"]`** carries the plan's
  stated value or `None`. That channel is OPAQUE to the framework, and
  `execute_tools/tidmad_data_path.py` explicitly REFUSES to guess this key;
  the literal defeated that refusal from outside, so the refusal was
  unreachable. It is reachable now.

**Behaviour change, not a preservation.** A plan that STATES the field — every
production plan — is unaffected. A legacy TIDMAD plan that OMITS it used to
scope its data at 10000 while training at 40000; it now fails loudly with the
task's own message. Falsifiers:
`tests/unit/nodes/ml_hyperparameter_tune_agent/test_c12p_b11_composed_seg_size_authoring.py`.

The paired probe-provenance sites moved with it: `runtime.py`'s `ProbeRequest`
and `core/runtime_control/bootstrap.py` recorded `segment_length: 0` for an
omitted key while `production_probe_executors` ran the probe at the declared
default. Both now resolve through `resolve_model_field`, because a recorded
`0` drags `ApplicabilityEnvelope`'s `observed_min` to zero and grants far
smaller candidates an `"interpolation"` label no probe ever earned.

### `--max_steps_per_attempt` now applies to a composed run too (C12-P / B7)

`--max_steps_per_attempt` applies to composed and legacy data scopes when
explicitly enabled. Its current CLI default is `0` (disabled), mapped to
schema `None`; a supplied positive limit remains an opt-in harness guard.
`--min_formal_batch_size` also defaults to `0` (disabled).
The former provisional 150,000-step default has been removed: step counts
alone do not establish runtime across models, tasks or hardware.

What changed is **where the bound can be evaluated**. The §5 step count came
only from the legacy TIDMAD `SampleSet`, and `_resolve_guardrail_steps`
returned `None` the moment there was none. PR-12d's planning seam B made that
state normal: a composed task that declares no physical partition geometry
builds no `SampleSet` at all (`planning.py:524-565`). `_evaluate_step_guardrails`
then short-circuits on the `None`, so the bound decided nothing — and it did
so **silently**, because the early return is taken before the `except` that
would have printed a line. An operator hard bound was inert for a whole class
of runs with zero output.

The count is now derived from the attempt's **task-owned** scope:

```text
run_admission_preflight   passes prepared.task_scopes + bindings.time_data_dir
                          (applicability decided by the layer holding them)
_resolve_guardrail_steps  no legacy SampleSet -> the task-scope leg
                          no task scope either -> None, legacy regime unchanged
resolve_task_scope_       len(TaskDataPath.training_dataset(scope, params))
  training_workload       steps = (len // batch_size) * epochs
```

`TaskDataPath.training_dataset` is one of the four FROZEN contract methods —
the training sibling of the `validation_dataset` leg already in production at
`execute_tools/scope_artifact.py::validation_rows_argv`. **No new capability,
no new protocol method, no task name**, and nothing TIDMAD-physical on this
leg: unlike the legacy resolver it needs no `segmentation_size`, so it does
not touch the plan-owned field the section above governs. `train_portion` and
`max_samples` travel on `EpochSamplingParams` into the implementation's own
materialization rather than being re-applied by the framework.

Both legs stay **best-effort** — an unresolvable count returns `None` and
leaves the primary runtime criterion to protect the attempt — but the
task-scope leg now PRINTS `[guardrails] task-owned step resolution failed
(non-fatal): …` instead of returning in silence. Falsifiers:
`tests/unit/nodes/ml_hyperparameter_tune_agent/test_c12p_b7_composed_step_guardrail.py`.

### Which profile the tuner asks (PR 05a, 2026-08)

02a fixed *the rule*; 05a fixes *the object the rule is applied to*.

`run()` resolves the run's `DatasetProfile` **once**, at the start, and
passes it explicitly to every consumer that needs a dataset fact:

| Consumer | Dataset fact | Receives |
|---|---|---|
| `_validate_data_config` | `psd_segment_length` (legality) | `dataset_config` — **required**, no default |
| `validate_runtime_config` | `num_files` (DataScope resolution) | `dataset` — passed by the tuner |
| `scope_is_partial` | `num_files` | the run-bound profile |
| `_validate_history_and_lock` | `num_files` (legacy `full_scope`) | `dataset` — **required**, keyword-only |
| legacy `single_file` accounting | `segments_per_file` | the run-bound profile |
| `build_sample_set` (train + eval) | whole profile | unchanged since 02b |

The module-level `from execute_tools.dataset_config import TIDMAD as
DATASET_CONFIG` import is **gone**; the tuner has no ambient dataset
authority left. The two required-parameter choices are deliberate — a
default would silently restore the ambient read.

**No CLI argument, default value, schema field or operator-visible
behaviour changed under TIDMAD.** Under TIDMAD every migrated site produces
exactly the value it produced before, including the legacy `single_file`
segment counts (200/200) and the byte-identical legality diagnostic. What
changed is what happens under a *bound non-TIDMAD topology*: the tuner can
no longer validate, scope or account an attempt against TIDMAD's numbers
while selecting against the run's own.

Pinned by `tests/unit/agent/tune_ml_hyperparam_agent/
test_step05a_{checkpoint0_baselines,run_bound_profile,checkpoint_a_replay}.py`.
Design: `docs/design/generic_framework_upgrade/
step_05a_tuner_data_selection.md`.


## Evaluation metric handle (Step 06, 2026-08)

Production scoring invokes the frozen TIDMAD scorer **through a generic
metric interface** — the metric's identity, direction and scoreability
contract have exactly one source for the whole run.

| Element | Where | What |
|---|---|---|
| binding | `run()`, run scope, after the composition binding | `run_metric = resolve_run_metric()` — the zero-argument resolver is the single acquisition site. A composed run uses its declared metric; missing required declaration is refused (`NoRunMetricError`) rather than falling through to an unbound legacy derivation. Exactly ONE acquisition site is pinned by the workflow census, so composed runs cannot execute a different metric path first |
| live route (`ANCHOR_NORMALIZED`) | an uncomposed compatibility run with an anchor map and legacy `SampleSet` | `metric_result = sandbox.evaluate_metric(run_metric, sample_set=eval_sample_set, anchor_map=…, s_max=…, denoised_filename_fn=_denoised_fn)`; `file_vector, final_scalar = metric_result.per_sample, metric_result.scalar` — `score_res`, reflector and record unchanged. **HealthGates are no longer part of this branch** (F2, below): they fire once per round for every route |
| task-owned route (`TASK_OWNED`, **Step 12 / PR-12d**) | scoring subprocess — every composed run with an opaque evaluation scope, including a task that also declares an anchor artifact | the child scores its OWN deliverable through the SAME composed metric and reports `metric_result` (plus declared secondaries) in its JSON output; the tuner ADOPTS them (`_adopt_child_metric_result`, `_adopt_child_secondaries` in `execution.py`) because only the child holds the deliverable and the evaluation scope. A multi-artifact task may return `TaskEvaluationPayload` so scoreability checks every artifact before arithmetic. |
| order inside the seam | `TidmadSandbox.evaluate_metric` | DataScope `validate_sample_set` (unchanged, first) → `TidmadScoreabilityContract.check({file_index: path})` → `scoring_utils.score_vector(**the same kwargs as before)` |
| refusal | `NotScoreableError` from the seam → the scoring `except` → `_build_scoring_failure_record` | `status='error_scoring'`, `failure_stage='scoring'`, `failure_type='not_scoreable'`, `metric_refusal=<NotScoreableResult>`, memory prose naming contract + requirement (never "crashed"); round outcome unchanged (next attempt) |
| record | success record | `metric_result` (identity / direction / scalar / references; `per_sample` = pointer to `file_vector`) |
| what the LLMs see | planner history dump / reflector `actual_results` | NOTHING new. The reflector's `score_results` is unchanged (the payload never enters it); the planner's history serialization (`agent/prompts.py::_truncate_memory_history`) drops `metric_result` / `metric_refusal` from the verbatim window (`_PLANNER_HIDDEN_RECORD_KEYS`), so planner message bytes are identical to pre-Step-06 for the same run. The payload is persisted for Steps 07a / 09, which own agent-facing rendering. No prompt template changed |
| legacy 2-tuple seam | `TidmadSandbox.score_vector` | still callable; Regime A resolves TIDMAD through the handle; values identical |
| pseudo mode | `StubSandbox.evaluate_metric` | synthesises the same 2-tuple stream under the run's real identity/direction |

### HealthGates fire at the ROUND boundary, on every scoring route (F2)

`--health_checks_config` defaults to `None`, selecting the packaged generic
policy; a nonempty explicit override is loaded directly and invalid/missing
input refuses. The comparison argument at the existing round-boundary call
uses `execute_tools.health_checks.config.default_health_policy_path()` even
without a checkout, carrying the same external task Health binding. Thus an
observe policy may continue while persisting production would-invalidate
evidence. The accessor performs no I/O, so disabled Health remains inert.
`--healthgate_mode observe_only` is a posture declaration, not file selection;
select an observe policy explicitly with `--health_checks_config`.

`docs/design/pluggable_health_checks.md` §8 and `CLAUDE.md` both specify that
gates fire at tuner round boundaries. Until this repair the code did not: the
tuner's only production gate call sat INSIDE the `ANCHOR_NORMALIZED` scoring
branch, which requires an anchor map, so

```text
un-composed + --is_trial     -> ANCHOR_NORMALIZED  -> gates evaluated
un-composed + --no-is_trial  -> SUBPROCESS_LEGACY  -> gates NEVER evaluated
composed (any task)          -> TASK_OWNED         -> gates NEVER evaluated
```

A composed task could declare a roster, materialize it into
`health_checks_effective.yaml`, have its sha pinned by the run-invariants lock
and pass `--healthgate_mode blocking` — and nothing was evaluated. The record
carried `health_gate_results: []` beside `health_gate_enabled: true`, which is
indistinguishable from a clean pass. **`blocking` was inert on exactly the runs
it exists to block.**

| Element | Where | What |
|---|---|---|
| boundary | `nodes/ml_hyperparameter_tune_agent/round_health.py` | `evaluate_round_health(...) -> RoundHealthOutcome`. A total function with explicit inputs: it resolves the round's gate set, builds the `HealthCheckContext`, calls the engine and projects the score-meta. Extracted rather than widening the `if`, because `run_inference_scoring_health` is already a phase orchestrator and the decomposition rule forbids adding branching to one |
| call site | `execution.py`, AFTER the scoring `try/except`, before the record is built | Reached on ALL THREE routes. Both routes arrive carrying the same three round facts (`file_vector`, `final_scalar`, `per_sample_evidence`); the task-owned route transports them from the child's payload, where `file_vector = MetricResult.per_sample` gives D18's mapping verbatim. A payload omitting the key entirely yields `PerSampleEvidence.UNDECLARED` — absence is never read as `scalar_only` |
| task-owned Health payload | `HealthCheckContext.load_evaluation_payload()` | Lazily calls the run-bound `TaskDataPath.read_evaluation_payload` with the current attempt identity. A view provider consumes the task's decoded payload and never reconstructs indexed filenames or storage layout. The callback is built at the round boundary and excluded from serialization; missing wiring raises rather than falling back to another task's naming convention. |
| scoring failure | `execution.py::_require_successful_scoring_result` immediately after the child boundary | A scoring exception or a child response whose status is not explicit `success` takes the `error_scoring` path before result unpacking and never reaches a gate. A successful scorer may still return scientifically invalid/non-finite evidence for the existing validity policy to classify. A gate that could not be evaluated is not a gate that passed. |
| gates disabled | `health_gate_enabled=False` (DataScope DS5) | `evaluated=False`, no engine call, no I/O. Score-validity classification stays active, exactly as before |
| structural guard | `tests/unit/nodes/test_f2_round_boundary_health.py` | Asserts by AST that the gate call has no `ScoringRoute` condition among its ancestors, and that `execution.py` contains no second gate call. The detector is itself proved to fire on the original defect shape, so the guard cannot pass vacuously |

**Known residual, tracked as follow-up debt.** `RoundHealthOutcome.evaluated`
answers "did gates RUN?" but is deliberately NOT persisted. `health_gate_results:
[]` therefore still cannot distinguish "ran, found nothing" from "never
invoked". Surfacing it means adding a key to `score_results`, which is the
transport for BOTH the record and the reflector's `actual_results` merge — and
that key list is a pinned LLM-facing surface (WF-2 golden, frozen at 9). Moving
a prompt surface is a declared Gate-1 change and did not belong in this repair.
The typed field exists so the follow-up is a wiring change, not a re-derivation.

**Scoreability (TIDMAD instance)** requires of the DELIVERABLE exactly what the
live scorer reads: file-level completeness (every in-scope file has an HDF5 that
opens), the input channel dataset (`ch=1` — the target channel is read from the
RAW file), the `voltage_range_mV` / `sampling_frequency` attrs on the input
group, and the declared storage dtype (`int8`). Channel group and dtype are
READ from the run's `DeliverableSpec` (05c keeps producer-side representation;
Step 06 owns evaluation-side acceptance). `_is_complete_trial_output` stays a
crash-resume reuse guard, not this mechanism.

**Reached by Step 07 PR 07b** — the tuner's incumbent/best selection no longer
encodes higher-is-better literally; see the next section. The chain / resume /
`per_file_best` / dashboard consumers still do (Steps 09 / 10 / M2), and the
asserted list in `tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py`
still holds them.

Design: `docs/design/generic_framework_upgrade/step_06_metric_interface.md`.

---

## Metric-direction policy and prompt rendering (Step 07 PR 07b, 2026-08)

### The order authority

`execute_tools/metric_order.py::MetricOrder` is constructed ONCE per run, at
run scope, from `run_metric.spec`, and is the ONLY place `MetricSpec.direction`
is interpreted. Every golden-metric ORDERING decision asks it:

| Decision | Member used |
|---|---|
| trial winner (`_best_trial_winner`) | `best` (ties → first, as `max()` did) |
| skip gate + its disabled sentinel | `is_better`, `worst_sentinel` |
| bypass gate + its disabled sentinel | `is_at_least`, `best_sentinel` |
| bootstrap reference | `worst_sentinel` |
| resolved skip / bypass thresholds | `toward_better(reference, declared_delta)` |
| planner score-table incumbent | `best` |
| reflector best / worst / rank / new-best | `best`, `worst`, `rank`, `is_better` |
| efficiency band | `toward_worse`, `is_at_least` |
| the five `best_*` finalization tracks | `best` (per track, same filters) |
| the `[SkipFormal]` / `[BypassTimeBudget]` banners | `comparison_symbol`, `at_least_symbol` |

**Deliberately NOT routed through it**: `same_loss_loss_rank` and
`best_same_loss_final_loss`. A training loss is lower-is-better *by definition
of a loss* and is unrelated to the golden metric; a test flips the metric
direction and asserts these two do not move.

### Scale-sensitive rules — classified, not sign-flipped

| Rule | Classification | Behaviour |
|---|---|---|
| `skip_formal_min_delta`, `bypass_formal_time_budget_min_delta` | DECLARED by the operator, in the golden metric's units | a COORDINATE on the better-direction axis: negative loosens, positive tightens, under both directions. The documented disable values (`-inf` skip, `+inf` bypass) still resolve to that metric's worst / best sentinel, so there is no second convention to learn |
| `bypass_formal_time_budget_minutes` | `float \| None`, default `None` | **Lane F3 / F-BYPASS-WD-1**: the ELEVATED wall-time ceiling (minutes) a score-QUALIFIED bypass formal attempt may use. ONE resolved value feeds BOTH consumers — admission RE-EVALUATES the forecast against it (a forecast past even this ceiling is REFUSED under bypass; the flag is never forced), and the same value becomes the attempt's `chosen_time_budget`, so the runtime watchdog's `operator_budget_seconds` moves WITH the admission verdict. `None` (default) = a qualified bypass grants NO extension — the elevated ceiling must be explicitly typed at launch (campaign: 200; normal formal: `formal_time_budget_minutes` 120), so it can never become a global raise through a schema default. The watchdog is never disabled by this value. Fresh-chain note: with `enable_chain_incumbent_formal_gates` ON and no incumbent, the −inf bootstrap makes the SCORE side unconditional (V20 §16.C) — the reachable unqualified state is the absence of a HealthGate-valid trial winner. |
| bootstrap and disabled sentinels | generic ORDER facts | `worst_sentinel` / `best_sentinel` |
| the efficiency band | generic, metric-independent by definition | ONE named `EFFICIENCY_BAND_FRACTION` (0.05), applied to the run's OBSERVED score range and moved toward worse — never a raw `best − 0.05` |
| `degenerate_penalty_score` | DECLARED, and INAPPLICABLE under a minimised metric | a finite float is **REFUSED at startup** with a recorded reason. It is not negated and not reinterpreted: the "large negative, strictly below any healthy success" convention describes a maximised metric, and under a minimised one the same number is the run's best score. `None` (the default) is direction-free and always accepted |

Under TIDMAD every resolved value is numerically identical to pre-07b.

### What the LLMs see

The planner and reflector prompts render, from landed authorities:

* **task content** — the built-in model roster (`MODEL_REGISTRY`), the
  full-scope segment count (the run-bound `DatasetConfig`), the output-contract
  shape (the run-bound `ModelIOContract`), the focal defaults (`LossConfig`),
  the health-check NAMES (the run's EFFECTIVE health config — advice about a
  check the run does not run is OMITTED), and the efficiency band percentage;
* **direction wording and metric identity** — "maximize"/"minimize", "GOOD if
  HIGHER"/"LOWER", and a `golden metric \`<id>\` (<direction> is better)` line.
  The record FIELD stays `denoising_score` (renaming it is D1's decision); what
  it measures is now stated rather than assumed;
* **training dynamics** — one compact, calibration-free line per recent
  experiment for the planner (with the objective family label) and one for the
  current attempt at the reflector (without it). Facts only: first→last values,
  trends, best validation epoch, drift after it, and the train–validation gap
  when the two were comparable. **No calibrated label** — no "overfitting",
  "converged" or "plateau" — because 07a deliberately derived none, and a
  renderer that supplied one would silently pick a threshold nobody declared.

What they do NOT see: the raw `training_history`, `training_diagnosis`, `static_observations`,
`metric_result` and `metric_refusal` record keys — and, since Step 10 / P2b,
the three `secondary_metric_*` keys. Showing the planner a second,
differently-directed number beside the one it is optimising invites it to
trade the two off, which is exactly the vote an observational metric must
never get; the crash carrier is additionally an operator-facing diagnostic
about the implementation, not a fact about the science. Widening the hidden
set moved no existing prompt byte: the keys are written onto a record only
when the run DECLARED secondaries, and a record carrying none of them takes
the filter's identity branch unchanged. The
planner's dynamics block is built from the window BEFORE those keys are
stripped, so the LLM gets an owned summary while the payloads stay out of the
history JSON. The reflector receives the `TrainingDiagnosis` only — never the
`TrainingHistory`.

### Bridge surface

```text
brain.plan(...,  task_render=<TunerTaskRender>,   # built once at run scope
                 metric_spec=run_metric.spec)
brain.reflect(..., metric_spec=run_metric.spec,
                   training_diagnosis=<the attempt's 07a diagnosis>)
```

All four are REQUIRED at a real render; the bridge raises `ValueError` rather
than falling back to the shipped TIDMAD values, because a fallback would
hardcode one task's facts — and one task's *goal* — into the framework's prompt
layer.

### Removed

`AttemptTransition` and `AttemptDecision` had zero production consumers and
could not be wired without changing round outcomes, which 07b is not permitted
to do. They are deleted; the `resolved_action` hazard they documented was
recorded as a KNOWN DEFECT beside its declaration inside `run()`. [F-SCANC-1
closure, 2026-08-26: the hazard was in fact SEVERED, not stale — the C7
decomposition left the verdict a local in `execution.py` — and the operator
ruling (decision packet v1) RETIRED the surface for v1: the declaration, the
skip branches, the `gate_aborted` carrier and the `SKIP_ITER` /
`SKIP_TO_FORMAL` vocabulary members are gone; `RoundDecision` /
`_decide_round_outcome` survive as the non-retryable-termination arbiter.]

Design: `docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/pr_07b_tuner_policy.md`.


---

## Candidate role identity (Step 07 correction, 2026-08)

### One authority: `is_trial`

Whether a plan or a record is a **TRIAL** or a **FORMAL** candidate is owned by
one field:

| Carrier | Field | Written |
|---|---|---|
| the round's plan | `plan.is_trial` | by the planner, then by the run-level / forced-formal override chain |
| the emitted record | `record.is_trial` | unconditionally from `trial_config.is_trial`, which IS `plan.is_trial` |

`core/resume.py` already reconstructs chain incumbents from `record.is_trial`
alone, across runs. Trial-winner selection (`_best_trial_winner`) and the
all-trials-invalid planner report (`_build_trial_validity_feedback`) now use
the same field and nothing else, so there is exactly one role authority in the
node.

The D-BUD-6 mode-aware epoch ceilings key on this same authority: the
planning clamp resolves the round's cap via
`HyperparamTuningInput.resolve_epoch_cap(is_trial=plan.is_trial)` — read
AFTER the mode-override chain, i.e. the exact value that becomes
`record.is_trial` — never a parallel derivation and never
`memory.time_mode`.

### `timing.validation_time_s` — the term the planner is asked to attribute (F-SCANE-3)

`timing.train_time_s` is the wall time of the **whole** training subprocess,
admission to exit, and it **includes the 07a validation pass**. It is
unchanged: the time budget is measured against it, so it must not be
narrowed.

`timing.validation_time_s` is that validation term — the per-epoch
`training_history.validation_seconds`, summed and rounded to 0.1 s. The
subprocess has always computed the split (`train_engine_sandbox` subtracts
`validation_seconds_total` from the training ACTUAL so the calibration store
is not inflated), but `training_history` is planner-hidden
(`agent/prompts.py::_PLANNER_HIDDEN_RECORD_KEYS`), so the split reached only
the calibration store. The planner was then shown `train=… min` and told *"If
the last run exceeded it, reduce model complexity"* — a candidate could be
shrunk for time spent validating it.

```text
training + fixed subprocess overhead = train_time_s − validation_time_s
```

**N-4 — what the split does NOT mean.** As first shipped, F-SCANE-3 told the
planner two things the code contradicts, in four places at once:

* *"Validation time … does not shrink when the model shrinks."* The
  validation pass runs `output_seq = model(input_seq)` per batch
  (`execute_tools/train_engine_sandbox.py::_validation_pass`) — a forward pass
  of the model under test.
* *"the architecture's own cost is `train_time_s − validation_time_s`."*
  `train_time_s` is the PARENT's wall clock around the whole subprocess
  (`execution.py`), while the trainer's own analogue starts at
  `t_train_start`, set **after** setup. The residual therefore also carries
  process spawn, CUDA init, model/optimizer construction, epoch-0 dataset
  materialization and checkpoint save — fixed overhead no design change
  removes. It is an **upper bound** on the architecture's training cost.

Under a hard budget those two together told the planner to ignore the one term
that does respond to shrinking the model and to attribute to its own design a
residual containing cost no design removes — under-pricing large candidates
and over-pricing small ones. The corrected wording, both renderers and the
coherence rule now live in **one** authority,
`agent/prompt_templates/timing_attribution.py`; the planner block, the
interpreter's timing discovery and both `timing` field descriptions consume it
rather than restating it. The residual is rendered as `training+overhead`,
never `architecture cost` — a label is read far more often than a note.

**N-4b — the first correction was itself false, in the half it rewrote.** It
replaced bullet 1 with *"a forward pass of the model under test over a FIXED
evaluation scope, so it shrinks with a smaller model but not with fewer epochs
or less training data."* Both clauses are wrong:

* **The evaluation scope is not fixed in a trial round — it is the planner's
  own lever.** `policy._resolve_sample_set_cfg`'s `trial` branch returns
  `"eval_portion": plan.eval_portion`; that value reaches
  `scope_acquisition.build_eval_scope(portion=…)`, becomes the attempt's
  `eval_sample_set`, crosses to the trainer as `--eval_sample_set_json` and is
  materialized as the validation dataset. `agent/prompts.py` asks the model
  for `eval_portion` by name (*"fraction of segments per file for
  validation"*) and tells it to increase it; on the campaign path the value is
  `AGENT_CONTROLLED`. Only a **formal** round fixes it — strategy locked to
  `snapshot`, portion from the operator's `formal_eval_portion`. The optional
  `validation_max_samples` ceiling (07c C6, default `None`) caps the eval leg
  but does not make it fixed.
* **It is paid once per epoch.** `_validation_pass` runs INSIDE
  `for ep in range(train_cfg.epochs)`, appending `validation_seconds` per
  epoch, and `records._validation_time_s` reports the SUM. `max_epochs=1` on
  the real path today, so this clause names a lever with no range until
  D-BUD-6's frozen `trial_max_epochs: 2` lands; the trial-scope clause carries
  the finding on its own.

This mattered because the planner reads the sentence immediately before *"the
time budget is a HARD UPPER LIMIT … reduce model complexity"*: telling it that
the one cost component it directly authors in trial rounds is fixed steers a
large overrunning candidate toward capacity reduction instead of the cheap,
agent-owned eval reduction. That is F-SCANE-3's own failure class — *the agent
is told to attribute to architecture a cost it cannot see* — reproduced by
F-SCANE-3's remediation, one lever over. What validation genuinely does **not**
respond to is `trial_portion` / `train_portion`, which size the training scope
only.

`None` means the producer recorded **no split** — a legacy record, a failure
record, or an attempt that ran no validation pass. It never means the pass
took zero seconds, and the two renderers that consume it (the planner's
`LAST EXPERIMENT TIMING` block and the interpreter's timing discovery) render
their pre-F-SCANE-3 bytes when it is `None`. They also refuse an
**incoherent** split — negative, or larger than `train_time_s` — which
production cannot produce, rather than printing a negative residual.

For a successful record with coherent `params.train_config.epochs` and
`runtime_verification.components.training.workload.detail.epochs`, the
planner's same timing block also states the measured training-phase seconds
and steps per epoch. This is distinct from `timing.train_time_s`, which is
the whole subprocess. Missing or conflicting measurements produce no new
claim; no runtime or budget admission semantics change. At fixed model,
training scope and batch size, additional epochs add roughly proportional
optimizer steps. Validation may run each epoch too, so the prompt explicitly
does not extrapolate whole-attempt time from training-phase time alone.

### `memory.time_mode` is timing metadata, not a second authority

`memory.time_mode` records **which wall-time budget was active** for a round.
It is stamped only when the time gate actually ran — that is, when the active
mode's `--trial_time_budget_minutes` / `--formal_time_budget_minutes` was set
— alongside `time_estimate_minutes` and `time_budget_minutes`. Its population
is unchanged by this correction: on a run with no time budgets the key is
still absent from `memory`, and the planner's resource block and the
trial→formal inference-measurement reuse read it exactly as before.

```text
candidate role identity        ⟂        time-budget enforcement state
```

Enabling or disabling the trial/formal time budgets may change time admission,
timing evidence and time-related refusal. It must NOT change whether a record
is classified as a trial or a formal candidate.

### What this corrects

Trial eligibility used to require the two fields to AGREE. Because
`memory.time_mode` exists only when the time gate ran, a campaign launched
with incumbent formal gates ON and both time budgets unset produced valid
trials that no gate could see:

```text
enable_chain_incumbent_formal_gates=True, budgets unset
  -> time gate skipped        -> memory.time_mode absent
  -> _best_trial_winner None  -> _should_skip_formal reads "no evidence"
  -> [SkipFormal] reason=no_valid_trial_winner
  -> the forced formal round never runs
```

Surfaced by 07b's Gate 1, which worked around it by temporarily enabling both
budgets. The coupling predates 07b. Everything else at the formal boundary is
unchanged: candidate-validity filtering, `MetricOrder`, the skip/bypass
threshold mathematics and their disabled sentinels, the no-winner-still-skips
rule (a genuinely empty or all-invalid trial stage still skips formal), and
all retry / round / attempt semantics.

---

## Reference science is never selected implicitly

The tuner carries no task reference dataset and resolves no comparison path.
When the caller declares no reference evidence, `load_reference_scores()`
returns `None`, the run records a named absence, and the optional comparison
table is omitted. This rule applies equally to composed and isolated node
invocations.

Task-specific baselines, ceilings, and published-result tables belong to the
external task package. Tests may inject synthetic evidence through the narrow
`load_reference_scores` dependency seam to exercise downstream table
construction, but production never imports a task loader or examines a task
name, metric identity, environment variable, or checkout-relative data path to
choose that evidence.

Downstream, `reference_scores` may therefore be `None`, and the score-table
guard in `execution.py` tests for it. Carried debt: `contracts.py` still
declares the field as `Any`, so that `None` is invisible to pyright.

## Task-declared training objective overrides the planner's choice (Step 12 / PR-12d, F-12d-31)

A task may declare an authoritative training objective on its composition
manifest (`objective:`, a validated `LossConfig`, carried on
`task_composition_ref.objective`). When declared,
`planning.py::_apply_declared_objective` overwrites `plan.loss_cfg` with it —
an ordinary validated `LossConfig` on the pre-existing `custom` + `loss_name`
route; no new enum value, and nothing here reads a task name. The
discriminator is only whether the RUN declared an objective.

**Why**: without it, the planner chooses the loss from what its prompt tells
it is valid — and two real composed DAVIS runs trained with `smooth_l1`
because the planner was never shown DAVIS's own exact-L1 objective. A task
declaring its own objective removes that as a planner decision.

**Applied AFTER the mode-override chain** (`_apply_mode_override_chain`,
`policy.py`) deliberately: that chain's forced-formal branch copies the
winning trial's `loss_config` wholesale, so an objective applied earlier
would be silently overwritten by whatever the trial happened to run. Last
writer on the plan wins, and the declared objective is the last writer.

**No-op when no objective is declared**: `composition_ref` is
`None` for an un-composed run, and `objective` is `None` for a composed task
that declares none — in both cases the plan is returned unchanged. A
substitution that does happen is announced with a `[objective]` print line
naming the planner's choice and the value that replaced it.

### Planner builtin loss offers

For composed runs, the planner's system instructions, user constraint and JSON
example derive builtin offers from the same semantic/temporal compatibility
authority used by execution. A categorical output without a temporal axis offers
`ce`; a categorical temporal output offers `focal`, `focal_cw`, `ce`; a continuous
output offers `smooth_l1`. These are the existing framework checks, not proof of
arbitrary target-layout compatibility or scientific suitability.

A composed run must declare normalized ModelIO facts. Missing facts, no eligible
builtin (unless an explicit custom objective supplies the independent route), an
incompatible builtin objective, or a concrete fixed-model output declaration
contradicting the task output refuses before the planner call. Reconcile the task
and model declarations rather than relying on an inferred default. Legacy
uncomposed prompt bytes remain unchanged.

An explicit task objective is displayed as the exact `LossConfig`; baseline,
exploration and collapse guidance do not tell the planner to replace it. The
last-writer enforcement described above is unchanged. Custom losses are offered
only from the invocation's task-compatible inventory. The task's
prediction/target applicability becomes one immutable snapshot, shared by the
system/user prompt surfaces and carried on `PreparedAttempt` through time/VRAM
measurement and both training paths. Locked builtin objectives expose no custom
route; locked custom objectives expose exactly their compatible registered
plugin and never fall back to a builtin. This certifies declared tensor
compatibility and bounded numerical execution, not scientific quality.

## Task-composed parameter rules

A composition may declare `parameter_rules` over dotted `ExperimentPlan`
paths. `exact` is a hard lock; `range`, `allowed`, and a registered
`predicate` leave the choice with the planner and validate the final effective
value. Enforcement runs after round-mode inheritance, the declared objective,
and the epoch bound, so Formal cannot replace a locked Trial parameter and a
rule cannot silently weaken the safety ceiling. Rules are
fingerprinted with the task composition and every changed field is attributed
to `composition-declared parameter rules` in execution provenance. A rule may not
target `loss_config` when the task declares an objective, because the objective
is the sole authority for loss semantics.

## The reflector is told what RESOLVED, not what was proposed (Lane D / F15)

`plan.hypothesis` is free prose the planner authors **before** the framework
resolves the plan. Seven steps then overrule parts of it — operator
`plan_overrides`, the mode-override chain, the task-declared objective,
task-composed parameter rules,
partial-scope strategy normalization, the mode-aware epoch bound
(`--max_epochs` / `--trial_max_epochs` / `--formal_max_epochs`, D-BUD-6), and
the forced model type — and none of them revisits the prose. The reflector received that
prose under the heading "Original Hypothesis" as the only description of the
configuration, so it narrated proposals as though they had run: a research
memory entry reported "custom Smooth L1 beta=0.5" for a run whose declared
objective executed and whose `beta` was null.

`provenance.py::ResolutionTracker` watches the whole planning window and emits
a typed `ExecutionProvenance` (`agent/schemas/execution_provenance.py`) — one
`ResolutionEvent` per plan field whose AUTHORED value differs from the EXECUTED
one. It rides `PreparedAttempt.execution_provenance` to the one `brain.reflect`
call site, and `render_execution_provenance_block` renders it above the
hypothesis, which is relabelled a PROPOSAL when it was overruled.

**Detection is structural, attribution is best-effort.** The tracker DIFFS the
authored plan against the final execution projection rather than recording at each known
override site, so a seventh resolution step added later is still reported —
as `unattributed`, never as agreement. A hand-written recorder at each site
would go silently blind, which is the census-blindness shape this repository
has repeatedly been bitten by.

**Nothing is rendered when nothing was overruled**, so an un-overruled run's
reflector prompt is byte-identical to before. A key the planner never authored
that resolves to a falsy schema default is suppressed as default
materialization; one that resolves to a real value (`loss_name`) is kept.

Production supplies the persisted `TrialConfig` to `finish_with_model`.
Its training/validation strategies and fractions, target files, alignment and
trial status supersede the intermediate plan; explicit ordering proposals use
the resolved ordering aliases. This projection reads existing resolution
results and does not repeat policy or ceiling logic. A superseding workload
change is attributed to `resolved_round_workload`. If it restores the authored
value, no disagreement is emitted. Neither input is mutated. Generated seeds
and ordering defaults with no authored proposal are not proposal overrides.

`ExecutionProvenance.events` and `.diverged` describe final execution only.
`plan_resolution_events` is a separate, optional intermediate-plan checkpoint
for explicit historical rendering providers: `None` means unavailable, an empty
tuple means available with no differences. Native rendering ignores it. The
`tuner.execution_provenance` prompt boundary permits an experiment-owned provider
to restore a qualified historical block without altering execution. The tuner
producer source is included in rendering assembly identity. Changed identities
require a new workspace; archived records are not rewritten.

**Known limit**: a claim in free prose about a field the plan never declared
structurally cannot be detected by a plan diff.

## Composed run's own scientific gate set governs best-track selection (Step 12 / PR-12d, F-12d-30)

`finalize_run_output`'s `_select_best_records` (`policy.py`) resolves the
five `best_*` tracks (including `valid_top_record`, which feeds
`best_exp_id` / `best_denoising_score`) through
`is_valid_candidate(record, required_gate_ids=...)`. Before this PR the call
site never passed `required_gate_ids`, so every run — composed or not — was
scored against the zero-argument default, which composes with
`LEGACY_OMITTED`: TIDMAD's scientific gate set. Correct for an un-composed
run; for a composed one it bound TIDMAD's Health family into a process that
had already bound the run's own, and the Step-08b run-scope guard then
refused an otherwise-complete run at finalize.

`run()` now resolves `run_scientific_gate_ids` ONCE, at run scope
(`_resolve_run_gate_ids`, `ml_hyperparameter_tune_agent.py`, via
`resolve_run_scientific_gate_ids` — Step 10 / P5+P6 W6, finding F-P56-2), and
carries it on `RunBindings.run_scientific_gate_ids`.
`records.py::finalize_run_output` reads it off the BINDING, never off
`task_composition_ref` — the F-11-C10-a lesson, where a stamp reading the
input projection instead of the run's own authority made a composed chain
refuse its own output. Uncomposed runs resolve their actual effective
`health_checks_config` through `resolve_scientific_gate_ids`, including an
explicit empty roster. A missing path uses the current neutral run-level
default. `None` returned by the resolver means unknown roles; classifiers never
reload defaults or infer roles from historical hashes. Unknown candidates are
excluded from valid-best and trial winners, and reported as unknown in feedback.
Explicit `health_gate_enabled=False` waives Health only for finite successes.
The forced-Formal boundary uses the same value when `_best_trial_winner`
classifies Trial records; otherwise a valid task-owned Trial can be followed
by an accidental attempt to bind the legacy/default Health family before
Formal begins.

## The run's FIRST health resolution uses the run's own binding (F-C12P-CP12-1)

The same mechanism, one step earlier in `run()`. Building the planner/reflector
task render needs the roster the run will actually evaluate, and that call —
now `_resolve_run_health_config(agent_input)` — is the tuner's FIRST health
resolution. The first resolution in a process is authoritative: it binds the
task's Health plugin set into the run scope, and the Step-08b guard refuses
every later, differing bind.

`load_health_gates_config` takes no binding, so given no explicit config path
it composes `LEGACY_OMITTED` — TIDMAD's family. That path is reachable exactly
when the run materialized no effective config, i.e.
**`health_gate_enabled=False`**; with gates enabled `build_run_invariants` has
already composed and bound the run's own family and the swapped-in effective
path carries its roster. A composed gates-off run therefore bound TIDMAD here
and had its OWN family refused moments later at `_resolve_run_gate_ids`.

`_resolve_run_health_config` asks the same authority
(`load_composed_health_config`) with the run's declared
`task_composition_ref.task_health_binding`. An un-composed run takes the
identical call it always took, so legacy behaviour is unchanged.

This was masked until `execute_tools/health_checks/config.py` keyed its
process-wide cache on the resolved binding: whether the wrong family got bound
used to depend on whether `_CACHED_GATES` happened to be warm, so the failure
appeared only in a cold process. The memo still short-circuits — it just
cannot short-circuit across a *change* of binding any more, which is the only
case in which skipping composition changed the answer.

## Watchdog kills reach the architectural-feedback trigger (F-RC-6)

`_collect_disallowed_patterns` tells the next proposer "this architecture
is too expensive". It considered only PREDICTED admission skips
(`status in {"skipped_oom_risk", "skipped_time_risk"}`). An attempt that
was admitted, ran, and was then killed by the watchdog is recorded with
`status="error"`, so the one structured signal designed to end a
"too slow" loop was unavailable for the very failure that proves the
candidate is too slow.

The discriminator is the **typed `failure_type == "wall_clock_timeout"`**,
never `status == "error"`: a code bug, a schema violation and an OOM all
carry that same status, and reading them as architectural evidence would
teach the proposer to shrink a model over a `ValueError`. The timeout path
is categorical rather than factor-tested, because the watchdog kills AT
the deadline — the observed `elapsed / deadline` ratio is ~1.003 and could
never clear `TIME_FACTOR_THRESHOLD = 5.0`.

## Node structure and public boundary (Step 07 PR 07b, C7 / C7d, 2026-08)

### The public interface is exactly two files

```text
nodes/ml_hyperparameter_tune_agent/
    ml_hyperparameter_tune_agent.py   PUBLIC  — HyperparamTuningAgent, run(), main(), the CLI
    ml_hyperparameter_tune_agent.md   PUBLIC  — this file: what the node promises
    *.py                              PRIVATE — implementation, serving the main module only
```

Operator architecture rule (2026-08-16), and it is executable, not advisory:
`tests/unit/nodes/test_node_public_boundary.py` fails if production code outside
this directory imports one of the private modules, if a private module imports
the main module, if the private graph acquires a cycle, or if `__all__` grows a
private name. **Import the node, not its internals.** Nothing in here is
contract except `HyperparamTuningAgent`, `run()`, `main()`, the CLI and the
schemas.

`_COMPATIBILITY_REEXPORTS` in the main module is scaffolding, not interface: it
keeps pre-decomposition importers and `mock.patch` targets working. It is closed
to new consumers.

### Internal module map

| Module | Responsibility |
|---|---|
| `contracts.py` | typed carriers only — no policy, execution, persistence or rendering |
| `provenance.py` | what planning RESOLVED away from the authored plan (`ResolutionTracker`) |
| `scope_acquisition.py` | task-owned scope acquisition (PR-12bc B5) and the package's ONE physical-topology decode (`AttemptTopologyFacts`, PR-12d seam B) |
| `planning.py` | observe -> plan (LLM) -> overrides -> strategy/epoch clamps -> the round's sample sets |
| `execution.py` | the physical work, in three coarse phases (admission/preflight, training, inference+scoring+health) |
| `records.py` | BUILDS records and the run output |
| `runtime.py` | EMITS records and runtime observations; runtime-control helpers |
| `policy.py` | ordering, thresholds, termination and selection decisions |
| `feedback.py` | what the next agent is told |
| `cli.py` | argument surface and input construction |

Dependency direction is one-way and acyclic:

```text
main ──> planning ──┐
     ├─> execution ─┼─> records ──> policy, feedback
     ├─> runtime ───┘        └────> contracts   (a leaf)
     └─> cli
```

`scope_acquisition.py` is a second leaf, not shown above: imported directly
by `main`, `planning` and `execution`, and importing nothing from its
siblings.

`records` BUILDS, `runtime` EMITS. That is the rule that decides which of the
two owns a helper, and it is why `runtime` may import `records` and never the
reverse.

### The lifecycle, as `run()` performs it

```python
run_bindings = RunBindings(...)          # authorities + services, resolved once
while completed_rounds < max_rounds:
    for attempt_in_round in ...:
        identity = AttemptIdentity(round_index, attempt_in_round, is_formal_round)
        prepared  = prepare_attempt(bindings, identity=identity, ...)  # planning.py
        admission = run_admission_preflight(...)            # execution.py
        trained   = run_training(...)                       # execution.py
        executed  = run_inference_scoring_health(...)       # execution.py
        reflection = brain.reflect(...)                     # visible here on purpose
        record = build_attempt_record(...)                  # records.py
        _records._emit_record(...)                          # runtime/records
return finalize_run_output(bindings, RunExitSnapshot(...))  # records.py
```

Each execution phase returns an `AttemptSignal` — `PROCEED`, `NEXT_ATTEMPT`
(was `continue`) or `END_ROUND` (was `break`) — and **`run()` performs the jump**.
The translation is 1:1 against the pre-refactor code; retry counts, round
transitions and phase order are unchanged. `raise` is not translated: exceptions
propagate into `run()`'s handler exactly as before.

### Run-scoped authorities vs. lifecycle state

`RunBindings` is frozen and carries only what startup resolved once — the
authorities (`run_profile`, `run_model_io`, `run_deliverable_spec`,
`run_deliverable_naming`, `run_metric`, `run_order`, `run_task_render`,
`run_scientific_gate_ids`, `registry`), the services (`sandbox`, `brain`,
`agent_input`) and the stable resolved facts (budgets, scope, thresholds,
hardware and provenance).

It carries **no** counters, no current plan, no current results and no
termination flags. That is enforced at construction by
`FORBIDDEN_BINDING_FIELDS`, not by convention, because a widely-passed object is
exactly the thing a future change adds a field to "just this once". The
end-of-loop values travel separately, in `RunExitSnapshot`.

`AttemptIdentity` is immutable and carries the round index, attempt index and
formal-round flag through preparation and execution. It does not decide the
resolved trial/formal role. `AttemptStage`, `AttemptRoleState` and
`AttemptOrdering` retain separate phase, resolved-role and selected-ordering
evidence for exception handling: a raising preparation call has no return
value. Each mutable carrier is created anew for each attempt.

### Extending the node

* New behaviour inside a phase -> the phase module. New phase -> a new function
  in `execution.py` returning an outcome, dispatched from `run()`.
* New data crossing a phase boundary -> a field on the existing carrier if it
  belongs to that lifecycle concept; a new carrier in `contracts.py` if it does
  not. Never a new mutable bag.
* Do not add a new responsibility to `run()`. It sequences; it does not
  implement.

### Stubbing internals in tests

Patch the module that makes the call, not the node's public path. `_run_skill`
and `_emit_record` are resolved through their owning modules
(`runtime`, `records`) precisely so ONE stub intercepts every caller;
`run_production_preflight`, `get_gates_for_position`, `build_sample_set` and
`derive_training_diagnosis` are stubbed where they are called. A stub aimed at
the wrong module does not raise — it lets the real thing run.

Source-scanning tests should read `tests/helpers/tuner_source.py`:
`tuner_node_source()` for claims about the node, `tuner_lifecycle_source()` for
reachability claims about the run loop.

### Known defects carried, deliberately not fixed by the decomposition

* ~~`memory.time_mode` is only stamped when a time budget is configured, so
  without `--trial_time_budget_minutes` / `--formal_time_budget_minutes` the
  two-field winner rule is unsatisfiable and the skip gate takes its
  "no evidence" branch.~~ **RESOLVED** by the Step 07 trial/formal-identity
  correction — PR #217, squash `a15d1366`, 2026-08-17. See the
  "Candidate role identity" section above.
* ~~The `resolved_action` round-scoped hazard (recorded as "staleness"
  beside its declaration in `run()`; the mechanism was actually a SEVERED
  carrier — C7d left the gate verdict a local in `execution.py`, so the
  variable was never written at all).~~ **RESOLVED** by the F-SCANC-1
  retirement — operator decision packet v1, 2026-08-26, RETIRE for v1:
  the declaration, the skip loop-control branches, the `gate_aborted`
  carrier and the `SKIP_ITER` / `SKIP_TO_FORMAL` action-vocabulary
  members are removed; a config declaring a retired action refuses at
  validation. Re-opening gate-driven loop control is ICLR-track work and
  needs its own operator decision plus a witness cycle.
* ~~07a's validation pass is missing from the watchdog deadline prediction
  (`T_deadline` needs a `T_val` term) — ADDED 07c scope. Until 07c lands,
  `--runtime_watchdog`-enabled real campaigns are not a reliable
  configuration.~~ **FIXED by 07c C5.** `RuntimePhase` gained `"validation"`;
  the first real validation batches are timed in-subprocess into a
  measurement-backed prediction (`real_validation_verification`) that the
  existing deadline provider sums with no arithmetic change, and 07a's
  per-epoch `validation_seconds` become the phase ACTUAL so future runs
  calibrate against it. The training ACTUAL stays validation-EXCLUSIVE — the
  per-optimizer-step model is unchanged, and the fix is one layer up.
* **STILL OPEN — pre-run ADMISSION pricing of the validation workload**
  (Q-07c-6 = B, operator decision 2026-08-17). 07c prices validation for
  runtime PREDICTION and the WATCHDOG only. `admission.py:148-150` states the
  prephase measurement covers `phase="training"` only, and 07a's validation
  pass runs INSIDE the training subprocess, so no measurement-backed
  validation estimate exists when admission executes. Owner:
  admission / runtime-control (§7e); NOT bound to D14. It must never be
  approximated from the training measurement by a fixed ratio — that is the
  hand-calibrated `× 2.7` pattern that the (now removed)
  `refine_inference_time_estimator` design existed to eliminate.

Design: `docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/pr_07b_tuner_policy.md` §14.9 - §14.9.5.

### Cooperative training allocation (opt in)

`training_budget_reserve_fraction: float | None = None` is forwarded from
`--training_budget_reserve_fraction`. When supplied, it must be in `(0,1)`;
both role time budgets and explicit positive integer effective epoch caps are
required. Initial proposed epochs no longer fix the executed horizon. The
trainer adds complete epochs while the role allowance, downstream reserve
and epoch cap permit. Formal retains its independent allowance under
`full_clone`. No scientific early stopping or best-checkpoint restoration is
performed; final completed weights are retained. Forecast versus measured
admission authority and watchdog policy remain independent. See
[execution/accounting contract](../../../docs/reference/cooperative-training-budget.md).

### Failed Formal evidence across iterations

When Formal attempts exist but no Health-valid Formal candidate exists, the tuner emits `formal_validity_feedback`: model identity, counts distinguishing execution failure from negative/unknown Health evidence, and the last eight factual outcomes. The classifier is shared with Trial feedback; Formal records are never relabeled Trial. The no-records manifest and typed resume path retain this summary without restoring the model, weights, plugin, score or incumbent. The workflow forwards the most recent three summaries to interpretation and both proposer paths. A cold start with failed Formal evidence means no valid incumbent, not no previous experiment. Existing healthy runs and manifests without this optional field remain supported. No task-specific remedy is inserted.

### Deployment-owned complete evaluation

A caller can bind a public candidate-evaluation client around the node invocation
when private inference/scoring/Health are owned by a deployment. See the
[complete evaluation execution contract](../../../docs/reference/candidate-evaluation-execution.md)
for request/result fields, actual scope, timing, failure behavior and qualification
requirements. Unbound calls retain native local evaluation. This binding is
separate from per-epoch validation and does not make an unresolved public task
composition executable.
The complete evaluator owns prediction-output retention; the tuner does not
request a local inference-output inventory for that route. Local evaluation's
inventory and cleanup remain unchanged.

### Formal resource retry inheritance

`full_clone` inherits the Trial winner on the first Formal attempt. Following
a same-round time or explicitly enabled step guardrail refusal, the next
planner's batch size and proposed epochs survive inheritance; model, loss and
learning rate remain the winner's. Existing OOM recovery also permits capacity
adjustment. A missing probe, infrastructure verification failure, Trial failure
or previous-round failure does not trigger this resource recovery. The current
round is supplied by the planning caller, not inferred from the winner.

Preflight memory's `verification_stage` distinguishes `preflight_time_budget`
from `preflight_evidence`, extending the existing structured stage convention.
Existing configuration-resolution receipts and `[FORMAL RECOVERY]` logs show
which proposed execution adjustments survived. The Formal time/VRAM
allowances, cooperative training policy, epoch cap and scientific checks remain
authoritative. In-process admission uses `AdmissionRecord.reason_code`; only
`budget_exceeded` and `training_allocation_exceeded` enable this recovery, so a
generic candidate verification failure cannot be mistaken for a time refusal.
See [cooperative budget](../../../docs/reference/cooperative-training-budget.md).

## Native training lifecycle boundary

See [checkpoint selection](../../../docs/reference/checkpoint-selection.md) for
`train_config.checkpoint_selection`, the unchanged default, fixed-validation
requirements and exported-epoch receipts. Proposal, implementation and review
prompts share the native training capability disclosure. It distinguishes
uninitialized target transforms and unsupported lifecycle requests from
executed interventions; trainability and specification alignment remain separate.

The optional [scoped target standardization](../../../docs/reference/target-standardization.md)
policy fits training-only statistics, exports original-unit predictions and
persists a reconstruction-bound transform. It defaults to `none`.

The optional [training batch policy](../../../docs/reference/training-batches.md)
keeps selected tail rows when `train_config.drop_last=false`; guardrails and
training use matching step arithmetic. Completed-epoch row counts are recorded.

### Planner strategy and timing disclosure (#372, under review)

`HyperparamTuningInput.planner_strategy` selects a declared planner provider.
The startup identity is pinned in the run invariant lock and forwarded to the
planner call. The timing context reads the same role-source and inheritance
owners as execution; it supplies facts without selecting a search schedule.
See [the planner strategy contract](../../../docs/reference/planner-strategies.md)
for provider selection, installation defaults, missing-context behavior and
historical-workspace migration limits.

## Attempt role and validation-limit identity (#369)

Current producers stamp `ExperimentRecord.attempt_role` as `trial`, `formal`, or
`unresolved` through `records._emit_record`. A resolved role comes from the
validated plan after override/parameter resolution, including preflight skips,
phase admission refusals, training/inference/scoring failures and completed
records. The exception carrier is reset before each attempt. Before resolution,
an outer failure is explicitly `unresolved`; it must not inherit a previous
attempt's role or infer one from `memory.time_mode`, score or round number.
`is_trial` agrees with a resolved observation. The schema refuses contradictions.

`core.record_role.is_formal_role` remains the role authority. An explicitly
unresolved attempt contributes to total records but not formal attempts.
Failed formal attempts still contribute to `formal_record_count`, while
`formal_success_count` requires success. Historical records without
`attempt_role` retain their existing interpretation; no archive is rewritten.
Newly correct role facts may change subsequent planner history. An experiment
may explicitly select a historical input renderer through the existing planner
strategy interface; the framework does not restore old role mistakes by default.

`validation_max_portion` and `validation_max_samples` travel through
`LockLaunchIdentity` and the shared invariant builder at all three launch paths.
The former limits resolved workload portions; the latter limits the training
validation pass, not the final metric's evaluation scope. New locks record both
values, including explicit null for disabled, with `validation_limits_recorded`.
Resume refuses any changed limit. A legacy lock lacking this evidence stays
readable but cannot certify continuation under the new builder. Retain the old
workspace/revision or start a new workspace using verified experiment settings.
Copying or editing the old lock does not constitute verification. No training,
scoring, Health, scheduling or scientific defaults are changed by locking them.

## Independent reflector retry selection

`reflect_retry_policy` is an optional typed transport override. Its absence retains
planner retry inheritance; its explicit `max_retries` value, including None,
governs reflector requests independently. Workflow JSON uses the existing
`tune.reflector.max_retries` leaf. This does not change tuning attempt/round counts.
See the [shared retry contract](../../agent/retry-policy.md).
