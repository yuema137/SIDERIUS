# HyperparamTuningAgent

> Optimizes hyperparameters for a given model architecture over N rounds. Each round runs **plan (LLM) → resource check → train → infer → score → reflect (LLM)** in a sandbox subprocess. Supports two modes (trial = sparse sampling for fast exploration, formal = full data for canonical scoring) and uses two LLM sub-calls per round — a planner (proposes hyperparameters) and a reflector (analyses results, drives the next plan). Returns the best run + a full audit trail of every successful, OOM-skipped, and gate-rejected attempt.

## Position in the pipeline

- **Node type**: **standalone-capable** — `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` exposes a CLI `main()` that takes the model + budgets + LLM config as flags, builds a `HyperparamTuningInput`, runs the full optimization loop, and writes `run_output_{run_name}.json` to the workspace. The CLI is the historical TIDMAD-style invocation and is what `scripts/run_comparison.py` calls.
- **Upstream**: `ml_model_proposal_agent` (provides `model_type`, `expert_advice`, `baseline_config`, `parameter_count_estimate` via the `proposal_to_hyperparam_seeded_v1` protocol). Plus `ml_code_validator_agent` gates whether a plugin reaches the tuner (only `passed=True` plugins get tuned).
- **Downstream**: `result_interpretation_agent` (consumes `HyperparamTuningOutput` per model, converted via `tuning_output_to_model_run_summary` into a `ModelRunSummary` that feeds the next interpretation iteration).
- **Protocol (upstream)**: `proposal_to_hyperparam_seeded_v1` — maps `ProposalOutput.{model_name, expert_advice, baseline_config, parameter_count_estimate}` into this node's seed.

## Input

**Schema**: `HyperparamTuningInput` in `agent/schemas/hyperparam_tuning.py`

### Core (model + LLM routing + guidance)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model_type` | `str` | Yes | — | Architecture to tune. One of the registered model keys (`punet`, `wavenet`, `fcnet`, `transformer`, `rnn`), or `"auto"` to let the planner pick. Plugin types (from `ml_model_implementor`) require `seed_plugin_path`. |
| `seed_plugin_path` | `str \| None` | No | `None` | Optional path to a plugin `.py` file used as the seed model. Required when `model_type` is a plugin (not built-in). The tuner copies the file into `{workspace}/plugins/{run_name}/` at run start so the training subprocess sees it via `SIDERIUS_PLUGIN_DIRS`. The file's `PLUGIN_MODEL_TYPE` must equal `model_type`. |
| `expert_advice` | `str \| ExpertAdvice` | No | `""` | Structured guidance from upstream agents (typically `ml_model_proposal_agent.expert_advice`). Accepts a plain string or a structured `ExpertAdvice` object. Injected into the planner prompt. |
| `human_advice` | `str \| None` | No | `None` | Optional human-provided guidance. Injected into the planner prompt alongside `expert_advice` under a `[Human Guidance (high priority)]` header. |
| `seed_records` | `list[dict[str, Any]]` | No | `[]` | Pre-existing experiment records injected into the agent's memory before round 1. Typically contains the baseline result so the planner has prior history to reason from. |
| `llm_provider` | `Literal["gemini", "openai", "deepseek"]` | No | `"gemini"` | Provider for the planner sub-call (and default for the reflector when not overridden). |
| `llm_model_id` | `str` | No | `"gemini-3.1-flash-lite-preview"` | Model ID for the planner sub-call (and default for the reflector). |
| `reflect_provider` | `Literal["gemini", "openai", "deepseek"] \| None` | No | `None` | Optional separate provider for the reflector sub-call. When `None`, the reflector uses `llm_provider`. Enables planner/reflector split (e.g. cheap planner + smarter reflector). |
| `reflect_model_id` | `str \| None` | No | `None` | Optional separate model ID for the reflector. When `None`, falls back to `llm_model_id`. |
| `max_retries` | `int \| None` | No | `None` | Maximum retry attempts for transient API errors (429, 5xx). `None` = retry indefinitely; the process owner (Slurm wall time / operator interrupt) is expected to terminate stalled runs. |
| `plan_overrides` | `dict[str, Any]` | No | `{}` | Hard overrides applied to every `ExperimentPlan` after the LLM produces it. Keys must be valid `ExperimentPlan` field names. Used to force-pin specific hyperparameters that the LLM is incorrectly drifting on. |

### Round / attempt budgets

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `max_rounds` | `int` | No | `50` | Maximum number of **completed** experiment rounds (OOM-skipped attempts do not count). |
| `attempts_per_round` | `int` | No | `3` | Per-round attempt budget for trial rounds. Each round retries up to this many times after a gate-skip or error before the round is recorded as a failure. |
| `attempts_per_formal_round` | `int` | No | `5` | Per-round attempt budget for the formal-promotion round. Higher than trial (5 vs 3) because the formal round runs on the full dataset and a single retry is much more expensive. |
| `max_fail_rounds` | `int` | No | `3` | Consecutive-failed-round abort trigger. When this many rounds in a row exhaust their attempt budget without a success, the tuner exits with `termination_reason="aborted_fail_rounds"`. |
| `max_epochs` | `int \| None` | No | `None` | Hard cap on epochs per round. When set, the tuner clamps the LLM's planned epochs to `min(planned_epochs, max_epochs)`. |
| `force_formal_round` | `bool` | No | `True` | When `True` (default), the **last** round of every iteration forces `plan.is_trial = False` so it always runs in formal mode (full dataset) regardless of what the planner picked. |
| `formal_round_strategy` | `Literal["full_clone", "hybrid_params", "independent", "inherit_best_train_plus_formal_eval"]` | No | `"full_clone"` | Orchestration policy for the forced formal round: `full_clone` re-runs the best trial verbatim on full data; `hybrid_params` carries trial-winner hyperparams + formal sampling; `independent` lets the planner propose a fresh formal config. |
| `degenerate_penalty_score` | `float \| None` | No | `None` | Operator policy for the agent's reaction when scoring flags a degenerate output on a formal round (e.g. all-zeros prediction). When set, the degenerate run gets this penalty score and the tuner continues; when `None`, the run is recorded as-is. |

### Trial mode sampling

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `is_trial` | `bool` | No | `False` | When `True`, run in trial-explore mode with sparse multi-file sampling for fast exploration. The default (`False`) means rounds run in formal mode unless the planner picks trial. |
| `trial_strategy` | `Literal["snapshot", "anchors", "target"]` | No | `"snapshot"` | Sampling strategy: `snapshot` (all 20 files), `anchors` (files 0/10/19), `target` (specific files via `target_files`). |
| `trial_portion` | `float` | No | `0.1` | Fraction of segments per file for the training scope. |
| `target_files` | `list[int]` | No | `[]` | File indices to sample from. Required when `trial_strategy="target"`. |
| `train_portion` | `float` | No | `0.1` | Per-epoch subsample fraction from the training scope. Matches legacy TIDMAD default. |
| `eval_strategy` | `Literal["snapshot", "anchors", "target"]` | No | `"snapshot"` | Sampling strategy for validation. |
| `eval_portion` | `float` | No | `0.1` | Fraction of segments per file for validation. Set to `1.0` for formal mode. |
| `train_validation_align` | `bool` | No | `True` | When `True`, train and eval scopes use the same segment indices (different physical files). |
| `file_index` | `int` | No | `6` | Validation/training file index (0-39). Default 6 matches the paper's standard split. **Ignored when `is_trial=True`.** |

### Formal mode sampling

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `formal_strategy` | `Literal["snapshot", "anchors", "target"]` | No | `"snapshot"` | Training-side sampling strategy in formal mode. Overrides the planner's `trial_strategy` on any round promoted to formal. |
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

### Pre-flight gates (resource budgets)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `trial_time_budget_minutes` | `float \| None` | No | `None` | Wall-time budget against which `evaluate_time_skill` gates rounds where the planner picks trial mode. `None` = trial time-gate disabled. |
| `formal_time_budget_minutes` | `float \| None` | No | `None` | Wall-time budget against which `evaluate_time_skill` gates rounds where the planner picks formal mode. `None` = formal time-gate disabled. |
| `trial_vram_budget_gb` | `float \| None` | No | `None` | VRAM budget against which `evaluate_vram_skill` gates trial rounds. `None` = trial VRAM-gate disabled. |
| `formal_vram_budget_gb` | `float \| None` | No | `None` | VRAM budget against which `evaluate_vram_skill` gates formal rounds. `None` = formal VRAM-gate disabled. |
| `data_dir` | `str \| None` | No | `None` | Filesystem path to the TIDMAD data directory. Forwarded to `evaluate_time_skill` so the real-dataset warmup can read 1 PSD from disk. |

### Workflow-populated fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `storage` | `StorageConfig` | Yes | — | Where this node reads its inputs and writes its outputs. Supports the local filesystem backend; populated by `main()` in CLI mode or by `workflows/model_exploration.py` in workflow mode. |
| `cleanup_denoised` | `bool` | No | `False` | Delete denoised HDF5 files after scoring each round. Saves disk space (~4 GB per file × 20 files = 80 GB per formal round). Scores have already been computed by the time cleanup runs. |
| `progress_bar` | `bool` | No | `False` | Stream live tqdm progress bars from training/inference subprocesses. |
| `current_run_best_formal_score` | `float \| None` | No | `None` | Chain formal-incumbent reference (from `core/resume.py`). See "Chain formal-incumbent reference" under Key behavioral notes. |
| `enable_chain_incumbent_formal_gates` | `bool` | No | `False` | Consumption-only switch for the two formal delta gates. See "Chain formal-incumbent reference" under Key behavioral notes. |
| `enable_structured_health_feedback` | `bool` | No | `False` | V19 PR 3 chain-policy PASS-THROUGH. The tuner has NO PR 3 behavior of its own: it passes this value into its run-invariants lock call and stamps it into `run_config` — nothing else reads it (a source regression test pins exactly two references). The flag's behavioral effect lives in the interpreter/proposer prompts. |
| `health_feedback_history_window_iterations` | `int` (`>= 1`) | No | `3` | V19 PR 3 retention-policy pass-through (locked + stamped only; consumed by the interpreter's history merge, not by the tuner). |
| `health_feedback_history_max_entries_per_model` | `int` (`>= 1`) | No | `8` | V19 PR 3 retention-policy pass-through (locked + stamped only). |

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
| `gate_exhaustion` | `GateExhaustionInfo \| None` | Populated only when the iteration ended without ever training successfully AND ≥1 attempt was rejected by the pre-flight resource gate. Used by the downstream proposer's `recent_gate_exhaustions` field to learn from prior tuner-side gate failures. |
| `trial_validity_feedback` | `TrialValidityFeedback \| None` | **V20 PR D (D-C6)** — populated only when the iteration ran trial rounds but produced NO HealthGate-valid winner. Reaches the next proposer via `ProposalInput.recent_trial_validity`. Deliberately SEPARATE from `gate_exhaustion`, which reports BUDGET exhaustion: these trials ran and succeeded and then failed their scientific gates, so `gate_exhaustion`'s triggers never fire for them, and the two call for opposite responses (propose lighter vs propose something that does not collapse). `None` whenever any trial is valid. |
| `formal_comparison_reference_source` | `str \| None` | **V20 PR D (D-C3)** — provenance of `formal_reference_score`: `restored_valid_formal_incumbent`, `negative_infinity_bootstrap` (no incumbent existed; the reference resolved to `-inf` internally) or `gates_disabled`. Read it WITH the reference: `null` alone is ambiguous across all three. `-inf` is never serialised. |
| `scientific_authority` (per record) | `dict \| None` | **V20 PR D (D-C2b/D-C4)** — on FORMAL records only, the authority verdict with its three facts beside its conclusions, so it is recomputable and therefore tamper-EVIDENT. Consumers must re-derive via `resolve_record_authority()` rather than trusting the stored conclusions. |
| `physical_rejections` | `list[PhysicalRejection]` | One entry per VRAM-gate rejection in this run. Empty list on iterations with no infeasible attempts. |
| `attempts_per_round` | `int` | Echo of the input value used for this run. |
| `attempts_per_formal_round` | `int` | Echo of the input value used for this run. |
| `max_fail_rounds` | `int` | Echo of the input value used for this run. |
| `consecutive_fail_rounds_at_exit` | `int` | Terminal value of the loop's consecutive-failure counter. `0` on a healthy completion; equals `max_fail_rounds` when the loop aborted on the trigger. |
| `termination_reason` | `Literal["completed", "aborted_fail_rounds", "aborted_by_gate", "scope_violation", "infrastructure_abort"]` | Why the loop exited. `"infrastructure_abort"` (C9c, 2026-07-30) means the runtime EVIDENCE CHANNEL failed — registry, persistence, schema/protocol, probe executor, telemetry, communication, or a policy invariant. It outranks every other reason and halts the CHAIN: `run_one_iteration.py` writes the `.chain_halted` sentinel with `reason="infrastructure_abort"` and exits 3, so neither the foreground loop nor a queued SDSC `afterany` job runs another candidate on the same broken environment. A candidate-class rejection stays attempt-local. |
| `started_at` | `str` | ISO-8601 UTC timestamp at `agent.run(inp)` entry. |
| `finished_at` | `str` | ISO-8601 UTC timestamp at `agent.run(inp)` exit. |

## CLI usage

```bash
.venv/bin/python nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py \
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
    --file_index 6
```

The CLI is the historical TIDMAD-style invocation and is what `scripts/run_comparison.py` calls. It supports the full range of input fields via flags (the schema's 38 fields map to ~30 CLI args). Result lands at `{workspace}/run_output_{run_name}.json`.

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

The constructor accepts `bridge_factory` and `sandbox_factory` (for test injection — both default to the real `LLMBridge` and `TidmadSandbox` classes; pseudo-mode tests inject `RecordingLLMBridge` / `RecordingSandbox`). The LLM bridge is built **lazily inside `run()`** (not at construction) because it depends on input-field LLM routing — the workflow uses `agent.set_run_context(...)` to deposit token-usage audit args that get applied right after the lazy bridge build.

## Storage outputs

- **Run output JSON**: `{storage.local.workspace}/run_output_{run_name}.json` — the validated `HyperparamTuningOutput` dumped at the end of `run()`. Contains `all_records` (the full per-round audit trail) plus the best run + score tables + gate-exhaustion / physical-rejection info. The workflow reads this and converts it to `ModelRunSummary` via `tuning_output_to_model_run_summary` for the next interpretation pass.
- **Run config snapshot**: `{workspace}/run_config_{run_name}.json` — the resolved input config (after defaults + plan-overrides). Audit log for reproducibility. Since V19 PR 3 it also stamps the structured-health-feedback CONTROL POLICY (`enable_structured_health_feedback`, `health_feedback_history_window_iterations`, `health_feedback_history_max_entries_per_model`) — policy only: per-round gate evidence stays in the experiment records and the interpretation digest, never duplicated here. The same three values join the run-invariants lock at all three lock sites (tuner / workflow / chain runner); a changed value on the same workspace fails startup with a `RunInvariantsViolation` naming the field and both values, and a legacy (pre-PR3) lock resolves to `False` / `3` / `8`.
- **Per-round trial config**: `{workspace}/trial_config_{run_name}_round{N}.json` — the resolved `TrialConfig` for round N, written before the training subprocess starts. Used by `core.resume.restore_prior_state` for crash-recovery.
- **Token usage**: `{workspace}/token_usage.jsonl` (when `set_run_context` is called by the workflow) — append-only log of every LLM call's token cost.
- **Per-run plugin dir**: `{workspace}/plugins/{run_name}/` — copy of `seed_plugin_path` written at run start so the training subprocess can find the plugin via `SIDERIUS_PLUGIN_DIRS`. Only populated when `seed_plugin_path` is set.
- **Denoised HDF5s** (intermediate): written by the training/scoring skill subprocesses. Cleaned up after scoring when `cleanup_denoised=True`.

## Key behavioral notes

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
to bound a production round's training, it is `--max_epochs` and the sample
set — not anything in C2.

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

**One inference output is resident at a time (V20 PR C2).** The inference
loop releases each output **before** the next forward begins:

```text
forward -> synchronize -> hold the output while the parent samples
        -> parent confirms -> release the output
        -> only then the next forward
```

Without the release, `output = model(input)` on the next iteration computed
a second full output while the previous one was still bound. At the
production batch of 25 each is 976 MiB; the measured effect was the
allocator pool growing 2830 → 4266 MiB and the driver figure reaching
**4870 MiB against a real 3434**.

That peak was **invisible**, not absent: the parent stops sampling once its
hold is satisfied, so batches after the first ran unobserved and the
reported figure happened to be the correct one. **An authoritative
measurement must not depend on observation stopping early**, so the
two-resident state is removed rather than left to be missed. The release is
unconditional — it does not wait on the parent's answer, because the
batches that leaked were exactly the ones the parent had stopped watching.

`outputs_released` on the phase record equals `inference_batches` when the
lifecycle is correct; a shortfall in a persisted artifact means an output
survived into a later forward. Formal inference has no such state —
`process_batch` returns between batches and its locals die with the frame —
so this makes the probe's loop match production rather than invent a
heavier lifecycle.

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
  configure the host's ceilings (the `28.0` GiB default suits a ~32 GiB
  card and would badly under-serve a larger one), collect a bounded
  driver-visible measurement, and have PR C validate and promote it.
  The operator sequence is `docs/running_chain_test.md` → "New GPU host".

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

5. **Five provenance states**, recorded in
   `ordering_resolution_source`. Three mean an ordering actually ran;
   two mean none did, and they are deliberately distinct because they
   mean different things:

   | Source | Meaning | `resolved_order_strategy` |
   |---|---|---|
   | `operator_override` | training ran the operator-forced ordering | the forced value |
   | `agent_proposal` | training ran the validated agent proposal | the proposed value |
   | `default` | training ran the default, no usable proposal or override | `shuffle` |
   | `legacy_default` | a **pre-PR2 artifact** has no ordering fields because it predates the feature; the reader reconstructs the historical default | `shuffle` (reconstructed) |
   | `not_executed` | a **current-code attempt** was rejected before training and never applied an ordering — at pre-flight (`skipped_oom_risk` / `skipped_time_risk` / `skipped_schema_violation`) or, since V20 PR B, at GPU admission (`skipped_resource_admission`) | `None` |

   `not_executed` never fabricates a `shuffle` value: inventing one for
   an attempt that visited no data would misreport the run. Proposal and
   override context is still preserved on such an attempt — what the
   agent *did* is independent of whether the attempt was admitted — but
   the source describes what **executed**, never what would have been
   selected had it passed admission.

   Known residual: current-run ERROR records (`error_training`,
   `error_inference`, `error_scoring`, …) fail before the stamping site
   and so still read as `legacy_default`. Tracked in issue #139; the
   preferred fix is to stamp resolved ordering immediately after
   resolution and before training dispatch.

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
  2. **Resource check** — `evaluate_vram_skill` + `evaluate_time_skill` pre-flight gates. A failure here counts as an *attempt* (not a *round*); the round retries up to its budget.
  2b. **Pre-phase GPU measurement** (V20 PR C2, **formal attempts with a real device only**) — a bounded isolated measurement of the exact candidate on the current card, feeding PR B's admission gate. A stop consumes the attempt and starts no GPU work. See *Pre-phase GPU measurement* above.
  3. **Train** — `training_skill` runs as a subprocess via `TidmadSandbox`. Writes the trained model + denoised outputs.
  4. **Infer** — `inference_skill` runs as a subprocess. Writes denoised HDF5s.
  5. **Score** — `scoring_skill` computes `denoising_score`. Cleanup runs after if `cleanup_denoised=True`.
  6. **Reflect** — `bridge.reflect(...)` analyses the round's result and updates memory for the next plan call.
- **Two LLM sub-calls per round** (planner + reflector). When `reflect_provider` / `reflect_model_id` are set, the two go through separate `LLMBridge` instances — enables splits like "cheap planner + smarter reflector" or "small planner + large reflector" without changing prompts.
- **Attempt vs round distinction.** A *round* is a slot in the optimization history that produces a final record. An *attempt* is one LLM-plan + downstream-execution attempt. Each round can consume up to `attempts_per_round` (or `attempts_per_formal_round` for the forced-formal round) attempts before being marked failed. Attempts that fail at the pre-flight gate cost LLM tokens but no GPU time; attempts that reach training but fail (OOM, training error) cost both.
- **`max_fail_rounds` termination trigger.** When this many *consecutive* rounds exhaust their attempt budget without producing a successful record, the tuner exits with `termination_reason="aborted_fail_rounds"`. The downstream interpreter reads `consecutive_fail_rounds_at_exit` to recognize this exit.
- **Force-formal-round mechanic.** When `force_formal_round=True` (default), the **last** round in the loop has `plan.is_trial` forcibly set to `False` so it runs on the full dataset. The `formal_round_strategy` controls how that round's config is built: `full_clone` (re-run best trial verbatim), `hybrid_params` (best-trial hyperparams + formal sampling), `independent` (planner proposes fresh), or `inherit_best_train_plus_formal_eval` (best train + formal eval scope).
- **Pre-flight gates use static-formula estimates + brief warmup.** `evaluate_time_skill` uses a static formula by default; when `data_dir` is set, it adds a brief real-dataset warmup that reads 1 PSD from disk.
  - **C8c (2026-07-30) — the time gate's authority now comes from the shared `RuntimeDecisionPolicy`, not from the skill.** The tuner passes `runtime_phase="trial"|"formal"`; the skill returns `feasible` DERIVED from the policy decision, plus `breakdown.runtime_decision` / `runtime_decision_reasons` / `runtime_decision_provenance` / `runtime_policy_identity` / `over_effective_budget`. Consequences: a **measured** (warmup-backed) projection over budget still emits `skipped_time_risk` with identical arithmetic (including the 10 % measured-inference slack); a **static** or **store-reused** projection no longer can — it is reported (verdict text, suggestion, `over_effective_budget=True`) but cannot gate the round, because prior-tier evidence has no blocking authority (`docs/design/runtime_estimation_and_calibration.md` §7.4). In **formal** mode with prior-tier evidence and no probe record the decision is `REQUEST_PROBE`, which lets the round proceed into the authoritative in-subprocess (RT2) verification instead of pricing it from a prior. An **uninterpretable** evidence source is an evidence-channel failure: the skill returns `status="error"` and the tuner raises — never a candidate-level "infeasible". `evaluate_vram_skill` uses architectural pattern tagging (`TIME_FACTOR_THRESHOLD`, `VRAM_FACTOR_THRESHOLD`) and a per-pattern memory budget. Both gates emit a `GateExhaustionInfo` payload when they reject all attempts in a round.
- **Sandbox subprocess for skill execution.** Each skill runs in a fresh subprocess via `TidmadSandbox` for memory isolation (PyTorch's CUDA context doesn't reliably release VRAM in-process). The sandbox communicates via JSON files in a temp dir and reports back through `get_summary()`. Pseudo-mode tests replace the sandbox with a `RecordingSandbox` that returns canned results without subprocess overhead.
- **Per-run plugin dir** isolates agent-generated plugins. When `seed_plugin_path` is set, the file is copied into `{workspace}/plugins/{run_name}/` and the training subprocess sees this via `SIDERIUS_PLUGIN_DIRS`. Plugins from one run don't pollute another's `MODEL_REGISTRY`. See `docs/run_scoped_plugins.md` Phase 3.
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
