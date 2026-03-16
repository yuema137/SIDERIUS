# First Model Proposal Demo — Architecture & Implementation

## Status: COMPLETE

The first model exploration demo is **fully implemented, tested, and running in
production**. All 5 nodes conform to the `run(input) -> output` node contract,
all 5 protocols are wired, and the workflow chains them in an iterative closed-loop.
519 unit tests passing. A full exploration run (50 iterations, 20 rounds/iteration,
target score 10.0) is running with punet + wavenet + fcnet as input models.

## Architecture

The workflow implements an iterative closed-loop traversal of the SIDERIUS node graph:

```
for each iteration:
    result_interpretation_agent  (all accumulated results)
            ↓  [ml_model_tune_to_ml_result_interp :: local_all_records]
    for each attempt (up to max_proposal_attempts):
        ml_model_proposal_agent  (with previous failure feedback)
                ↓  [ml_result_interp_to_ml_model_propose :: local_full_context]
        ml_model_implementor
                ↓  [ml_model_propose_to_ml_model_impl :: local_full_spec]
        ml_code_validator_agent
                ↓  [ml_model_impl_to_ml_model_valid :: local_all_fields]
        if passed → break
    tune_ml_hyperparam_agent  (fan-in: validator + proposal)
            ↓  [ml_model_valid_to_ml_model_tune :: local_validated_model]
    accumulate results → next iteration
```

Stop conditions: `max_iterations` count OR `target_score` threshold.

## Design Decisions

- **Workflow, not orchestrator** — the path is fixed and deterministic. LLM-driven
  path selection (orchestrator) is deferred to a future phase.
- **Validation retry with feedback** — on validation failure, the workflow retries
  propose→implement→validate with the error message fed back to the proposal agent
  via `previous_failures`. Node exceptions are caught and treated as failures.
- **All nodes follow the standard contract** — each node is a pure function with a
  `run(input) -> output` method, validated Pydantic schemas at entry and exit, and a
  CLI interface.
- **Two-phase interpretation** — Phase 1: per-model LLM summarization from condensed
  `ModelRunSummary` (not raw records). Phase 2: cross-model synthesis. Keeps each LLM
  call focused and within token limits.
- **Template-constrained code generation** — the implementor node fills in a fixed
  template rather than generating free-form code. Self-correction loop (4 checks:
  config consistency, scalar fields, syntax, smoke test) retries before writing files.
- **Fan-in protocol** — `validate→tune` consumes both `ValidatorOutput` and
  `ProposalOutput`. The workflow holds all intermediate outputs and passes them to
  the protocol.
- **Per-node LLM config** — `WorkflowLLMConfig` allows each node to use a different
  LLM provider/model. The implementor defaults to `gemini-3.1-pro-preview` (stronger
  for code generation); others default to `gemini-3.1-flash-lite-preview`.
- **Human advice** — every node accepts optional `human_advice: str` to steer its
  LLM prompt. Separate from `expert_advice` (agent-to-agent structured guidance).
- **Plugin registration** — after validation passes, plugin files are copied to
  `agent_generated/models/` and `MODEL_REGISTRY` is extended at runtime so the
  tuning subprocess can find the new model.

---

## Implementation Summary

| Component | Status | Details |
|-----------|--------|---------|
| **Nodes (5/5)** | ✅ | All conform to `run(input) -> output` contract |
| **Protocols (5/5)** | ✅ | All with `local_*` + `database_*` placeholder; fan-in on `validate→tune` |
| **Workflow** | ✅ | Iterative closed-loop with retry, per-node LLM config, human advice, plugin registration |
| **Schemas** | ✅ | `ModelRunSummary` (condensed, no raw records), `WorkflowLLMConfig`, `human_advice` on all nodes |
| **Unit tests** | ✅ | 519 passing |
| **Integration tests** | ✅ | Tier 1 (all nodes) + Tier 2 (tune→interpret edge) with real API + GPU |
| **End-to-end tests** | ✅ | Single-loop and 2-iteration closed-loop verified |
| **Production run** | ✅ | 50-iteration exploration running with punet + wavenet + fcnet |

### Bugs found and fixed during end-to-end testing

| Bug | Root cause | Fix |
|-----|-----------|-----|
| `models_format_sandbox` import error | `ml_models/` not on `sys.path` in workflow | Added to `sys.path` at workflow startup |
| Plugin not loadable by tuning subprocess | Plugin only in attempt dir, not in `agent_generated/models/` | Copy plugin after validation; extend `MODEL_REGISTRY` at runtime |
| `model_type` missing on plugin config | Plugin template didn't include `model_type` field | Added `model_type` to template config class |
| Training crash: `nn.Embedding` got float | Hardcoded model type whitelist for int input | Flipped default: all models get int, only fcnet gets float |
| LLM planner ignored `force_model` | Planner picked built-in model types from config manual | Override `model_type` in code after `brain.plan()` returns |
| Non-scalar config fields | LLM added `activation: str` despite prompt rule | Added scalar check to implementor self-correction loop |
| Empty `model_name` from LLM | Proposal agent accepted `""` | Added `min_length=1` to `ProposalOutput.model_name` |
| Gemini SDK deprecation | `google.generativeai` deprecated | Migrated to `google.genai` |

---

## Next Steps in Detail

### Step 1 — `result_interpretation_agent` ✅ done (two-phase)

**File**: `nodes/result_interpretation_agent.py`.

**What was built**:
- `class ResultInterpretationAgent` with `run(input: InterpretationInput) -> InterpretationOutput`
- **Two-phase LLM interpretation** (replaces the original single-call design):
  1. **Phase 1 — Per-model summarization**: one LLM call per model type, receiving a
     condensed `ModelRunSummary` (scores, trajectory, conclusions — NOT raw experiment
     records). Produces structured JSON: `key_findings`, `bottlenecks`,
     `best_config_analysis`, `score_trend`.
  2. **Phase 2 — Cross-model synthesis**: one LLM call consuming all per-model summaries
     to produce the final `InterpretationOutput`. Skipped for single-model input.
- Input schema uses `ModelRunSummary` (not raw records): `model_type`, `run_name`,
  `status`, `completed_rounds`, `best/worst_denoising_score`, `best_config`,
  `round_scores: List[float]`, `round_conclusions: List[str]`,
  `model_description: Optional[str]` (inline for agent-generated models).
- `tuning_output_to_model_run_summary()` utility converts `HyperparamTuningOutput` →
  `ModelRunSummary`, extracting aggregates and discarding raw records.
- Descriptions loaded from disk for built-in models, inline from `ModelRunSummary` for
  agent-generated models (enables closed-loop iteration without filesystem coupling).
- 35 unit tests + Tier 1 and Tier 2 real-API integration tests.

**Future evolution**: Option B — split into two separate nodes (`per_model_summarizer`
and `cross_model_interpreter`) with a protocol between them. This gives the orchestrator
the ability to run per-model summarization in parallel, cache individual summaries, and
re-synthesize without re-summarizing. The split should happen when:
- Parallelism matters (many models, slow LLM)
- The orchestrator needs to selectively re-summarize specific models
- The per-model summary becomes a reusable artefact consumed by multiple downstream nodes

---

### Step 2 — `ml_model_proposal_agent` ✅ done

**File**: `nodes/ml_model_proposal_agent.py`.

**What was built**:
- `class MLModelProposalAgent` with `run(input: ProposalInput) -> ProposalOutput`
- Two LLM calls (chain of thought):
  1. **Reasoning call** (`generate_text()`): unconstrained architectural reasoning — no JSON
     constraints, so the LLM can think deeply about bottlenecks, architecture families, and
     tradeoffs. Covers: structural weakness, architecture families, tradeoff analysis, design
     choices, and likely failure modes.
  2. **Commit call** (`generate()`): given the reasoning text, commit to a specific design
     as strict JSON matching `ProposalOutput`.
- `mathematical_definition` is **abstract** — describes the computational stages and
  mathematical principles (e.g. SSM state update, gated convolution). Concrete layer
  dimensions and channel counts belong only in `baseline_config`.
- Duplicate model name guard: raises `ValueError` if the LLM proposes a name already
  in `existing_model_types`.
- `ProposalInput.human_advice`: optional `ExpertAdviceInput` (plain string or structured
  `ExpertAdvice`) — injected into the reasoning prompt as high-priority guidance, enabling
  human-in-the-loop steering of the proposal.
- Writes output to `{storage.local.workspace}/proposal_{run_name}.json`
- 35 unit tests (18 node + 13 schema + 4 human_advice injection) + Tier 1 real-API integration test (Gemini + OpenAI)

**Key design insight — abstract mathematical definition**:
Early prompting produced mathematical definitions with concrete layer shapes
(e.g. `Conv1d(1, 64, kernel_size=7)`). This was corrected: the definition should describe
the *architectural principles* (what mathematical operations, how data flows, what structural
novelty), while concrete dimensions live exclusively in `baseline_config.model_config`.
This keeps the definition stable across hyperparameter searches and makes it more useful
for the implementor.

---

### Step 2b — Protocol structure ✅ done

**Files**: `agent/schemas/protocols/`

Formalised one-file-per-directed-edge naming convention with hierarchical node codes
(`ml-model-tune`, `ml-result-interp`, `ml-model-propose`, etc.) and transport-scoped
function names (`local_*`, `database_*`).

- `ml_model_tune_to_ml_result_interp.py`: `local_all_records` (serialises `all_records`
  into a `SummaryGroup`), `database_all_records` (NotImplementedError placeholder)
- `ml_result_interp_to_ml_model_propose.py`: `local_full_context` (serialises full
  `InterpretationOutput` dict into `ProposalInput`), `database_full_context` placeholder
- `__init__.py`: registry with flat aliases for all edge-protocol combinations

**Key design insight — protocols as documentation today, discovery tomorrow**:
Protocols currently serve as explicit documentation of the canonical wiring between nodes.
Calling a protocol is preferred over constructing inputs by hand, but not strictly required —
a human can pass arguments directly. In the future, orchestrators will query the protocol
registry programmatically to select edges at traversal time. This two-phase design means
the same protocol files serve both roles without change.

**Key design insight — `database_*` placeholders enforce Principle 8**:
The `database_*` variants raise `NotImplementedError` but their docstrings specify that,
when implemented, they will read from the database and return a *fully populated schema* —
never a partially filled one. This enforces Principle 8: the calling node never knows or
cares which transport was used.

---

### Step 3 — `ml_model_implementor` ✅ done

**File**: `nodes/ml_model_implementor.py`.

**What was built**:
- `class MLModelImplementor` with `run(input: ImplementorInput) -> ImplementorOutput`
- Two LLM calls (chain of thought):
  1. **Reasoning call** (`generate_text()`): free-text reasoning covering submodules needed,
     tensor shape trace through the full forward pass, config fields, import requirements,
     and potential shape alignment issues. No JSON constraints so the model can reason freely.
  2. **Code commit call** (`generate()`): given the reasoning, outputs a strict JSON object
     with exactly five fields: `extra_imports`, `config_fields_code`, `config_fields`,
     `init_body`, `forward_body`.
- Template assembly: the five LLM sections are substituted into a fixed `PLUGIN_TEMPLATE`;
  all boilerplate (`PLUGIN_MODEL_TYPE`, `PLUGIN_CONFIG_CLASS`, `PLUGIN_MODEL_CLASS`,
  forward contract comment, class scaffolding) is pre-written and never generated.
- `_class_name()` helper: `gated_dilated_tcn` → `GatedDilatedTcn`.
- Post-generation patch: replaces `self.embedding(input)` with `self.embedding(x)` after
  the LLM commit — a recurring LLM mistake that the hard constraint in the code prompt
  alone was not always sufficient to prevent.
- **Three pre-write validation checks** (run before any files are written to disk):
  1. **Config field consistency** — regex-parses `init_body` for all `config.X` references
     and verifies each has a matching Pydantic Field declaration in `config_fields_code`.
  2. **Syntax check** — `ast.parse()` on the assembled plugin source.
  3. **Smoke test** — dynamically loads the assembled plugin in a temp file, instantiates
     the model with default config, and runs a `[1, 64] int64 → [1, 256, 64] float32`
     forward pass with NaN check.
- **Self-correction loop** — if any validation check fails, the error message + previous
  code are sent back to the LLM via a repair prompt. The LLM produces a targeted fix.
  Up to `max_retries` repair attempts (default 2, configurable via `ImplementorInput`).
  The reasoning call runs once; only the code-commit step is retried.
- Writes three files:
  - `{plugin_dir}/{model_name}.py` — the plugin file
  - `{plugin_dir}/{model_name}/description.md` — architecture description for the interpretation pipeline
  - `{test_dir}/test_{model_name}.py` — test skeleton (fully fixed, no LLM generation)
- Writes output record to `{storage.local.workspace}/implementor_{run_name}.json`
- Returns `ImplementorOutput` with absolute paths, `config_fields` summary, and `description_file_path`
- 52 node unit tests + 10 schema unit tests + Tier 1 real-API integration tests (Gemini + OpenAI)

**Key design insight — description.md for agent-generated models**:
The `result_interpretation_agent` calls `get_model_description(model_type)`, which raises
`FileNotFoundError` if no description exists. The loader already searched
`agent_generated/models/{model_type}/description.md` as a fallback path, but nothing wrote
it. The implementor now writes this file alongside the plugin, populated from
`ImplementorInput.model_description` and `mathematical_definition`. This closes the gap:
a model proposed and implemented by agents can be interpreted by the interpretation agent
in the next iteration of the loop, without any human-written description.

**Key design insight — import deduplication and sanitisation**:
The LLM frequently included `import torch`, `import torch.nn as nn`, etc. in `extra_imports`
even though the fixed template already contains them. The assembler filters these out by
comparing each line against a set of already-present imports. Beyond deduplication, the
filter also drops any line that is not a valid import statement (does not start with
`import` or `from`) — some models emit partial fragments like `torch.nn.functional as F`
which would cause a `SyntaxError`. Trailing `$` characters (a JSON/markdown artifact
from some models) are stripped from all code lines.

**Key design insight — self-correction vs. downstream validation**:
The implementor's three pre-write checks are **minimum viability** — "can this code run at
all?" They catch missing config fields, syntax errors, and runtime crashes. These are
failures an LLM can reliably fix when given the exact error message, so self-correction is
effective here. The downstream `ml_code_validator_agent` performs deeper semantic checks
(gradient flow, LLM code review against the mathematical spec) that require judgement and
are not self-healable within the implementor. This separation keeps each node focused:
the implementor ensures runnable code, the validator ensures correct code.

**Template rendering**: the implementor holds the template as a string in the module,
substitutes `{model_name}`, `{ModelClass}`, then fills LLM-generated sections.

---

### Step 4 — `ml_code_validator_agent` ✅ done

**File**: `nodes/ml_code_validator_agent.py`.

**What was built**:
- `class MLCodeValidatorAgent` with `run(input: ValidatorInput) -> ValidatorOutput`
- Seven checks in sequence, with short-circuit logic:
  1. **Plugin load** — importlib loads the file, verifies `PLUGIN_MODEL_TYPE`, `PLUGIN_CONFIG_CLASS`, `PLUGIN_MODEL_CLASS` are all present.
  2. **Pytest** — subprocess pytest on the generated test file, stdout/stderr captured on both pass and fail.
  3. **Description valid** — `description.md` exists and has >50 characters of content.
  4. **Config fields scalar** — all `config_fields` values are `int`, `float`, or `bool`. Rejects `List`, `Dict`, `None`.
  5. **In-process instantiation** — loads plugin, calls `PLUGIN_CONFIG_CLASS()` and `PLUGIN_MODEL_CLASS(config)`, runs a small dummy forward pass `[1, 64] int64 → [1, 256, 64] float32`. Shape-checked.
  6. **Gradient flow** — `loss.backward()` on the forward output; verifies all trainable parameters received non-None gradients.
  7. **LLM code review** — passes plugin source, model description, mathematical definition, and (when present) runtime errors to the LLM. Returns a structured `LLMCodeReview` with `spec_alignment`, `trainability_concerns`, `implementation_issues`, `passed`, `notes`.
- Checks 5+6 only run if check 1 passed (plugin loaded). LLM review runs if the plugin file is readable.
- When runtime errors are present (failed pytest output or instantiation error), they are injected directly into the LLM review prompt so the LLM diagnoses the precise root cause rather than speculating from static analysis.
- Writes `validation_{run_name}.json` to workspace.
- 85 unit tests + Tier 1 (18 tests, real Gemini API) + Tier 2 (real Gemini + OpenAI, full implement→validate chain).

**Key design insight — calibrated LLM review prompt**:
The LLM review prompt explicitly distinguishes **concrete bugs** (spec contradiction, shape
errors, gradient-breaking ops — hard fail) from **theoretical concerns** (edge-case worries,
style suggestions, hyperparameter range concerns — put in `trainability_concerns`/`notes`,
not in `passed`). Without this calibration, smarter LLMs tend to over-reject working
implementations for theoretical concerns that don't affect correctness. The prompt also
clarifies that the `[B,T] int64` input format with `nn.Embedding` is system-specified and
always correct, preventing the LLM from questioning it.

**Key design insight — runtime evidence for LLM review**:
Static code analysis by the LLM often misidentifies the root cause of subtle bugs (e.g.
flagging `x * residual` as wrong when the actual fault is incorrect dilated convolution
padding). By injecting the exact `RuntimeError` and pytest traceback into the review
prompt, the LLM shifts from speculation to diagnosis — it receives the evidence needed to
pinpoint the precise failure (e.g. `padding=kernel_size//2` vs. the correct
`dilation*(kernel_size-1)//2`). This makes `implementation_issues` an actionable fix list
for the orchestrator's retry loop rather than a guessed critique.

**Key design insight — validator as a diagnostic, not a gatekeeper**:
The validator's `passed=False` output is not a terminal failure — it is structured
diagnostic data for the orchestrator. `error_message` summarises all failures in one
string; individual boolean fields (`tests_passed`, `instantiation_passed`, etc.) indicate
which checks failed; `llm_review_implementation_issues` provides a targeted fix list. The
orchestrator retry loop will feed this directly back to the implementor.

---

### Step 5 — `tune_ml_hyperparam_agent` refactor ✅ done

**File**: `nodes/ml_hyperparameter_tune_agent.py`.

**What was built**:
- `class HyperparamTuningAgent` with `run(input: HyperparamTuningInput) -> HyperparamTuningOutput`
- `main()` is now a thin CLI wrapper that parses args and calls `run()`
- `_serialize_expert_advice()`: converts structured `ExpertAdvice` objects to
  LLM-readable strings for `brain.plan()` and experiment record storage
- `human_advice` field: appended alongside `expert_advice` with clear labeling
- `force_model` override: when not `"auto"`, the agent overrides the LLM planner's
  `model_type` choice in code (not just in the prompt), ensuring agent-generated
  models are used correctly
- `model_config["model_type"]` is explicitly set to match the forced model type
- `MODEL_REGISTRY` import moved to `main()` only (class is cleanly importable
  without PYTHONPATH dependency)
- 21 unit tests (serialize, run success, run OOM, expert advice passthrough)

---

### Step 6 — Protocols (all 5) ✅ done

**Files**: one module per edge in `agent/schemas/protocols/`.

Each protocol is a plain typed function. The `validate→tune` protocol is a fan-in:
it takes both `ValidatorOutput` and `ProposalOutput` as arguments (the validator
only confirms validity; the expert advice and baseline config come from the proposal).

| File | Function | Signature |
|------|----------|-----------|
| `ml_model_tune_to_ml_result_interp.py` | `local_all_records` | `(output: HyperparamTuningOutput, storage: StorageConfig) -> InterpretationInput` |
| `ml_result_interp_to_ml_model_propose.py` | `local_full_context` | `(output: InterpretationOutput, storage: StorageConfig) -> ProposalInput` |
| `ml_model_propose_to_ml_model_impl.py` | `local_full_spec` | `(output: ProposalOutput, storage: StorageConfig) -> ImplementorInput` |
| `ml_model_impl_to_ml_model_valid.py` | `local_all_fields` | `(output: ImplementorOutput, storage: StorageConfig) -> ValidatorInput` |
| `ml_model_valid_to_ml_model_tune.py` | `local_validated_model` | `(output: ValidatorOutput, proposal: ProposalOutput, storage: StorageConfig, max_rounds, file_index, llm_provider, llm_model_id) -> HyperparamTuningInput` |

---

### Step 7 — `workflows/model_exploration.py` ✅ done

**File**: `workflows/model_exploration.py`.

**What was built**:
- Iterative closed-loop workflow: interpret → (propose → implement → validate) → tune → accumulate → repeat
- **Stop conditions**: `max_iterations` count OR `target_score` threshold (whichever first)
- **Validation retry**: on failure, retries propose→implement→validate up to `max_proposal_attempts`,
  feeding `previous_failures` error messages back to the proposal agent
- **Node exception handling**: `try/except` wraps the inner loop — node crashes (e.g. implementor
  `ValueError`) are caught, added to `previous_failures`, and retried
- **Per-node LLM config** via `WorkflowLLMConfig`: each node can use a different provider/model.
  Loaded from JSON file or constructed programmatically. Nodes not configured use built-in defaults.
- **Human advice** per node: `human_advice_interpret`, `human_advice_propose`,
  `human_advice_implement`, `human_advice_validate`, `human_advice_tune`
- **Storage layout**: `{workspace}/{run_name}/iteration_NNN/attempt_NNN_{model_name}/` for
  propose/implement/validate, `{workspace}/{run_name}/iteration_NNN/{model_name}/` for tuning.
  Consistent `run_name` across all files.
- **Plugin registration**: after validation passes, plugin files are copied to
  `agent_generated/models/` and `MODEL_REGISTRY` is extended at runtime
- **Summary accumulation**: `ModelRunSummary` with inline `model_description` enables
  iteration N+1 to see all prior models without filesystem coupling
- **Data loading**: `load_tuning_outputs()` loads one specific run per model via
  `source_run_name` (not globbing all runs)
- 22 unit tests (single iteration, multi-iteration, target score, validation retry, storage layout)
- Successfully tested: single-loop and 2-iteration closed-loop with real API + GPU

---

## Nodes

### 1. `result_interpretation_agent`

**Input schema** (`InterpretationInput`):
- `summaries: List[SummaryGroup]` — experiment records grouped by `(model_type, run_name)`; can be empty if `model_types` is set
- `model_types: Optional[List[str]]` — explicit list of model types whose descriptions to include; `None` = derive from summaries; empty list `[]` is an error
- `max_records_per_group: int` (default: 50) — most-recent records preferred when truncating
- `storage: StorageConfig`

`SummaryGroup` fields: `model_type: str`, `run_name: str`, `records: List[Dict]`.

At least one model type must be reachable (via `summaries` or `model_types`); otherwise validation raises.

**Output schema** (`InterpretationOutput`):
- `model_types: List[str]` — all model types analysed
- `model_descriptions: Dict[str, str]` — full markdown descriptions loaded from `description.md`; carried forward to proposal agent
- `total_experiments: int` — all records across all groups (including OOM-skipped)
- `per_model_best: Dict[str, Optional[float]]` — best denoising score per model
- `per_model_worst: Dict[str, Optional[float]]` — worst denoising score per model
- `best_denoising_score: Optional[float]` — cross-model maximum
- `worst_denoising_score: Optional[float]` — cross-model minimum
- `best_config: Optional[Dict]` — params dict that produced the overall best score
- `key_findings: List[str]`
- `bottlenecks: List[str]`
- `take_home_message: str`

---

### 2. `ml_model_proposal_agent`

**Input schema** (`ProposalInput`):
- `interpretation: Dict` — serialised `InterpretationOutput`
- `existing_model_types: List[str]`
- `constraints: List[str]`
- `human_advice: Optional[ExpertAdviceInput]` — plain string or structured `ExpertAdvice`; injected as high-priority guidance into the reasoning prompt
- `storage: StorageConfig`

**Output schema** (`ProposalOutput`):
- `model_name: str`
- `model_description: str`
- `mathematical_definition: str`
- `motivation: str`
- `expert_advice: ExpertAdvice`
- `baseline_config: Dict`

---

### 3. `ml_model_implementor`

**Input schema** (`ImplementorInput`):
- `model_name: str`
- `mathematical_definition: str`
- `model_description: str`
- `baseline_config: Dict`
- `plugin_dir: str` (default: `agent_generated/models`)
- `test_dir: str` (default: `agent_generated/tests`)
- `max_retries: int` (default: 2, ge=0) — self-correction attempts after initial code commit; total attempts = 1 + max_retries
- `storage: StorageConfig`

**Output schema** (`ImplementorOutput`):
- `model_type: str`
- `description_file_path: str` — absolute path to the written `description.md`
- `model_file_path: str`
- `test_file_path: str`
- `config_fields: Dict`
- `model_description: str` — pass-through from `ImplementorInput`; forwarded to validator via protocol
- `mathematical_definition: str` — pass-through from `ImplementorInput`; forwarded to validator via protocol

---

### 4. `ml_code_validator_agent`

**Input schema** (`ValidatorInput`):
- `model_type: str`
- `model_file_path: str` — from `ImplementorOutput` via protocol
- `test_file_path: str` — from `ImplementorOutput` via protocol
- `description_file_path: str` — from `ImplementorOutput` via protocol
- `config_fields: Dict[str, Any]` — from `ImplementorOutput` via protocol; used to verify all fields are scalar
- `model_description: str` — pass-through from `ImplementorOutput`; injected into LLM review prompt
- `mathematical_definition: str` — pass-through from `ImplementorOutput`; injected into LLM review prompt
- `llm_provider: Literal["gemini", "openai"]` (default: `"gemini"`)
- `llm_model_id: str` (default: `"gemini-3.1-flash-lite-preview"`)
- `storage: StorageConfig`

All file paths come directly from `ImplementorOutput` mapped by the protocol — the validator
never reads from storage to discover them (inter-node communication principle).
`model_description` and `mathematical_definition` travel as pass-through fields through
`ImplementorOutput`, avoiding a fan-in edge from the proposal node.

**Output schema** (`ValidatorOutput`):
- `passed: bool` — True only if all seven checks pass
- `model_type: str`
- `plugin_registered: bool` — plugin loads and exposes all three required attributes
- `tests_passed: bool` — all pytest tests in the generated test file pass
- `description_valid: bool` — `description.md` exists and is non-empty (>50 chars)
- `config_fields_valid: bool` — all config fields are scalar types (int, float, bool)
- `instantiation_passed: bool` — in-process forward pass produces shape `[1, 256, 64]`
- `gradient_check_passed: bool` — backward pass succeeds; all trainable params have non-None gradients
- `llm_review_passed: bool` — LLM code review concludes implementation is sound
- `test_output: Optional[str]` — full pytest stdout/stderr on both pass and fail
- `llm_review_spec_alignment: Optional[bool]`
- `llm_review_trainability_concerns: Optional[List[str]]`
- `llm_review_implementation_issues: Optional[List[str]]` — precise root-cause diagnosis when runtime errors provided
- `llm_review_notes: Optional[str]`
- `error_message: Optional[str]` — combined summary of all failures; None if passed

---

### 5. `tune_ml_hyperparam_agent` (existing, `run()` to be added)

Input/output schemas already defined in `agent/schemas/hyperparam_tuning.py`.
`HyperparamTuningInput` now uses `storage: StorageConfig` instead of raw
`workspace` and `run_name` strings.

---

## Protocols

| Edge | Module | Function | Status |
|------|--------|----------|--------|
| `tune → interpret` | `ml_model_tune_to_ml_result_interp` | `local_all_records` | ✅ done |
| `interpret → propose` | `ml_result_interp_to_ml_model_propose` | `local_full_context` | ✅ done |
| `propose → implement` | `ml_model_propose_to_ml_model_impl` | `local_full_spec` | ✅ done |
| `implement → validate` | `ml_model_impl_to_ml_model_valid` | `local_all_fields` | ✅ done |
| `validate → tune` | `ml_model_valid_to_ml_model_tune` | `local_validated_model` | ✅ done |

---

## File Structure

```
agent/
├── schemas/
│   ├── storage.py                        ✅ done
│   ├── hyperparam_tuning.py              ✅ done (storage added, file_index default=6)
│   ├── interpretation.py                 ✅ done (SummaryGroup, multi-model overhaul)
│   ├── proposal.py                       ✅ done
│   ├── implementor.py                    ✅ done
│   ├── validator.py                      ✅ done
│   └── protocols/
│       ├── __init__.py                               ✅ done (registry with edge aliases)
│       ├── ml_model_tune_to_ml_result_interp.py      ✅ done (local_all_records)
│       ├── ml_result_interp_to_ml_model_propose.py   ✅ done (local_full_context)
│       ├── ml_model_propose_to_ml_model_impl.py      ✅ done (local_full_spec)
│       ├── ml_model_impl_to_ml_model_valid.py        ✅ done (local_all_fields)
│       └── ml_model_valid_to_ml_model_tune.py        ✅ done (local_validated_model)
├── skills/                               ✅ unchanged
├── prompts.py                            ✅ exists (new prompts to be added)
└── llm_bridge.py                         ✅ done (generate() JSON mode + generate_text() plain text)

ml_models/
├── model_descriptions.py                 ✅ done (loader, raises FileNotFoundError if missing)
├── punet/description.md                  ✅ done
├── fcnet/description.md                  ✅ done
├── transformer/description.md            ✅ done
├── wavenet/description.md                ✅ done
├── rnn/description.md                    ✅ done
└── plugin_loader.py                      ✅ done (moved from core/)

nodes/
├── ml_hyperparameter_tune_agent.py       ✅ done (run() refactor, force_model override, human_advice)
├── result_interpretation_agent.py        ✅ done (two-phase: per-model + synthesis, ModelRunSummary)
├── ml_model_proposal_agent.py            ✅ done (two-call CoT, human_advice, duplicate guard, previous_failures)
├── ml_model_implementor.py               ✅ done (two-call CoT, template with model_type, 4 self-correction checks)
└── ml_code_validator_agent.py            ✅ done (7 checks, calibrated LLM review)

workflows/
├── __init__.py
├── llm_config.py                        ✅ done (WorkflowLLMConfig, per-node LLM config)
└── model_exploration.py                 ✅ done (iterative closed-loop, validation retry, plugin registration)

tests/
├── unit/
│   ├── agent/
│   │   ├── tune_ml_hyperparam_agent/    ✅ 59 tests (28 schema + 10 skill + 21 run/serialize)
│   │   ├── result_interpretation_agent/ ✅ 35 tests (22 node + 13 schema)
│   │   ├── test_llm_bridge.py           ✅ 11 tests (generate + generate_text, both providers)
│   │   ├── ml_model_proposal_agent/     ✅ 35 tests (23 node + 12 schema)
│   │   ├── ml_model_implementor/        ✅ 62 tests (52 node + 10 schema)
│   │   ├── ml_code_validator_agent/     ✅ 85 tests (55 node + 30 schema)
│   │   └── protocols/                   ✅ 56 tests (5 protocol modules)
│   └── workflows/
│       └── test_model_exploration.py    ✅ 22 tests (single/multi iteration, retry, storage)
│
├── integration/
│   ├── nodes/                           ✅ Tier 1 — single node, real API
│   │   ├── test_llm_bridge.py               ✅ 4 tests (Gemini + OpenAI)
│   │   ├── test_result_interpretation_agent.py ✅ 4 tests (Gemini + OpenAI)
│   │   ├── test_ml_model_proposal_agent.py  ✅ 2 tests (Gemini + OpenAI)
│   │   ├── test_ml_model_implementor.py     ✅ 2 tests (Gemini + OpenAI)
│   │   ├── test_ml_code_validator_agent.py  ✅ 18 tests (Gemini API)
│   │   └── test_tune_ml_hyperparam_agent.py ✅ uses HyperparamTuningAgent.run()
│   ├── protocols/                       ✅ Tier 2 — one graph edge end-to-end
│   │   ├── test_tune_to_interpret.py        ✅ uses ModelRunSummary + real API + GPU
│   │   ├── test_interp_to_propose.py        ✅ 2 tests (Gemini + OpenAI)
│   │   ├── test_propose_to_implement.py     ✅ 2 tests (Gemini + OpenAI)
│   │   └── test_implement_to_validate.py    ✅ 2 tests (Gemini + OpenAI)
│   └── workflows/                       ✅ Tier 3 — tested manually (single-loop + 2-iteration)
│
└── unit/core/
    ├── test_storage.py                  ✅ done (11 tests)
    └── ...
```

**Total unit tests: 519 passing.**

---

## Workflow Usage

```python
# Programmatic usage
from workflows.llm_config import WorkflowLLMConfig, NodeLLMConfig
from workflows.model_exploration import run_workflow

llm_config = WorkflowLLMConfig(
    implement=NodeLLMConfig(provider="gemini", model_id="gemini-3.1-pro-preview"),
    # all others use node defaults (gemini-3.1-flash-lite-preview)
)

results = run_workflow(
    data_dir="/home/klz/Data/SIDEREIS_DATA",
    model_types=["punet", "wavenet", "fcnet"],
    source_run_name="v3_file6",
    workspace="/home/klz/Data/SIDEREIS_DATA/exploration",
    run_name="explore_v1",
    max_iterations=20,
    max_rounds=20,
    max_proposal_attempts=10,
    target_score=10.0,
    llm_config=llm_config,
    human_advice_propose="Propose simple, easy-to-implement models...",
    human_advice_tune="Use batch_size=1.",
)
```

```bash
# CLI usage
python workflows/model_exploration.py \
    --data_dir /home/klz/Data/SIDEREIS_DATA \
    --models punet wavenet fcnet \
    --source_run_name v3_file6 \
    --workspace ./exploration \
    --run_name explore_v1 \
    --max_iterations 20 \
    --max_rounds 20 \
    --target_score 10.0 \
    --llm_config llm_config.json \
    --advice_propose "Propose simple models..." \
    --advice_tune "Use batch_size=1."
```

**Storage layout:**
```
{workspace}/{run_name}/
├── workflow_{run_name}.json
├── iteration_001/
│   ├── interpretation_{run_name}.json
│   ├── attempt_001_{model_name}/
│   │   ├── proposal_{run_name}.json
│   │   ├── implementor_{run_name}.json
│   │   ├── validation_{run_name}.json
│   │   ├── models/{model_name}.py
│   │   ├── models/{model_name}/description.md
│   │   └── tests/test_{model_name}.py
│   └── {model_name}/
│       ├── run_output_{run_name}.json
│       ├── summary_{run_name}.json
│       ├── run_config_{run_name}.json
│       ├── cached_models/
│       ├── configs/{run_name}/
│       └── records/{run_name}/
├── iteration_002/
│   └── ...
```

---

## Key Reliability Decision: Template-Constrained Code Generation

The implementor node fills in a fixed Python template. The LLM writes only the marked
sections; everything else is pre-written and never touched.

```python
# FIXED — never generated
import torch
import torch.nn as nn
from pydantic import BaseModel, Field

# OPTIONAL — LLM may add standard-library or torch imports here
# e.g.: from torch.nn import functional as F
# e.g.: import math
# Do NOT add packages not already in pyproject.toml

PLUGIN_MODEL_TYPE = "{model_name}"        # substituted from ProposalOutput.model_name

# LLM WRITES: config fields only (must be scalar: int, float, bool)
class {ModelClass}Config(BaseModel):
    model_type: str = Field(default="{model_name}")   # FIXED — auto-set from model name
    segmentation_size: int = Field(default=40000, ge=1)
    batch_size: int = Field(default=1, ge=1)
    # <LLM adds architecture-specific fields here>

PLUGIN_CONFIG_CLASS = {ModelClass}Config  # FIXED

# LLM WRITES: __init__ body and forward body only
class {ModelClass}(nn.Module):
    def __init__(self, config: {ModelClass}Config):
        super().__init__()
        # <LLM writes layer definitions here>

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # contract — FIXED, must not change:
        #   input:  [B, T]        int64
        #   output: [B, 256, T]   float32
        # <LLM writes forward pass here>

PLUGIN_MODEL_CLASS = {ModelClass}         # FIXED
```

The test file has an equivalent fixed skeleton:

```python
# FIXED — never generated
import torch, pytest
from {model_name} import PLUGIN_MODEL_CLASS, PLUGIN_CONFIG_CLASS

def test_forward_shape():
    config = PLUGIN_CONFIG_CLASS()
    model = PLUGIN_MODEL_CLASS(config)
    x = torch.randint(0, 256, (2, config.segmentation_size))
    out = model(x)
    assert out.shape == (2, 256, config.segmentation_size)

def test_forward_no_nan():
    config = PLUGIN_CONFIG_CLASS()
    model = PLUGIN_MODEL_CLASS(config)
    x = torch.randint(0, 256, (1, config.segmentation_size))
    out = model(x)
    assert not torch.isnan(out).any()

def test_config_instantiation():
    config = PLUGIN_CONFIG_CLASS()
    assert config.segmentation_size > 0
```

### What the template constrains vs. what the task constrains

The template does **not** limit architectural creativity. The LLM can write arbitrary
layers, submodules, attention mechanisms, positional encodings, multi-stage processing,
nested modules — anything — inside `__init__` and `forward`.

The real constraint is the **forward contract**, which is a task definition, not a
template decision:

```
input:  [B, T]       int64   — raw signal, integer class indices
output: [B, 256, T]  float32 — per-timestep logits over 256 denoising classes
```

| Proposal type | Works? | Limiting factor |
|---|---|---|
| Novel attention mechanism, new U-Net variant, custom convolution | ✅ | — |
| Mixture of experts, multi-scale processing, custom positional encoding | ✅ | — |
| Model needing iterative inference (e.g. diffusion) | ❌ | Training loop, not the template |
| Model with multiple inputs (signal + auxiliary features) | ❌ | Forward contract — task definition |
| Model requiring adversarial training | ❌ | Training loop, not the template |
| Model using a library not in `pyproject.toml` | ⚠️ | Missing dependency |

**Implication for the proposal node**: `ml_model_proposal_agent` must be prompted to
treat the forward contract as a hard constraint. Any architecture that respects it —
however novel internally — will work through the template.
