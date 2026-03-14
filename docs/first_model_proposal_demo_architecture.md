# First Model Proposal Demo — Architecture & Plan

## Goal

Demonstrate one complete end-to-end traversal of the SIDERIUS node graph — the first
full model proposal loop:

```
tune_ml_hyperparam_agent  (existing results, starting node)
        ↓  [ml_model_tune_to_ml_result_interp :: local_all_records]
result_interpretation_agent
        ↓  [ml_result_interp_to_ml_model_propose :: local_full_context]
ml_model_proposal_agent
        ↓  [ml_model_propose_to_ml_model_impl :: local_full_spec]
ml_model_implementor
        ↓  [ml_model_impl_to_ml_model_valid :: local_all_fields]
ml_code_validator_agent
        ↓  [ml_model_valid_to_ml_model_tune :: local_validated_model]
tune_ml_hyperparam_agent  (new model, end node)
```

Each arrow is a named protocol — an explicit, typed function that maps one node's output
schema to the next node's input schema, exactly as defined in `architecture.md`.
Protocol naming convention: `{source_code}_to_{target_code}` per file, `{transport}_{data_scope}` per function.

This is a **linear, single-pass path through the graph**. There is no orchestrator and
no retry loop. If any node fails, the path stops. For the demo we need one clean
successful pass.

---

## Scope Decisions

- **No orchestrator** — a flat demo script selects and traverses the path manually.
  This is the human-as-orchestrator principle: a human (or script) applies protocols
  and calls `node.run()` in sequence.
- **No retry loop** — if `ml_code_validator_agent` returns `passed=False`, the demo stops.
  This is acceptable. Retry logic belongs in an orchestrator, which comes after the demo.
- **All nodes follow the standard contract** — each node is a pure function with a
  `run(input) -> output` method, validated Pydantic schemas at entry and exit, and a
  CLI interface. No special-casing for the demo.
- **CoT inside the proposal node** — the demo script never sees intermediate reasoning
  steps. Only the final `ProposalOutput` is returned. The chain of thought is an
  internal implementation detail of the node.
- **Template-constrained code generation** — the implementor node fills in a fixed
  template rather than generating free-form code. This is the key reliability mechanism
  for a single-pass demo. See the section below.

---

## Progress

### Completed

| Step | What was done |
|------|---------------|
| Architecture alignment | Reviewed codebase against `architecture.md`. Identified and resolved all structural gaps before building new nodes. |
| `architecture.md` rewrite | Replaced `AgentCommunicationInterface` abstraction with the correct typed directed graph model. Added Core Principles (7), Agent Dependency Graph, Protocols section, Orchestration Graph. |
| Delete `core/recorder.py` | Removed legacy `TidmadRecorder` class — duplicate of `LocalRecorder` in `sandbox_executor.py`. |
| `LLMBridge.generate()` | Renamed `_generate_json_response` → `generate` (public). All new nodes call `bridge.generate(system_prompt, user_prompt)` directly. `plan()` and `reflect()` on the bridge still work for the existing tuning agent. |
| `agent/schemas/storage.py` | Created `StorageConfig` with `LocalStorageConfig` (implemented) and `PostgresStorageConfig` (placeholder — schema defined, backend not yet wired). Every node's input schema now includes `storage: StorageConfig` so each node knows where to read its inputs and write its outputs, and can be run standalone. |
| Schemas for all 4 new nodes | Created `interpretation.py`, `proposal.py`, `implementor.py`, `validator.py` in `agent/schemas/`. All include `storage: StorageConfig`. |
| `agent/schemas/protocols/__init__.py` | Protocols directory created and ready. |
| `HyperparamTuningInput` updated | Replaced raw `workspace: str` and `run_name: str` fields with `storage: StorageConfig`. Agent code updated to extract `workspace` and `run_name` from `agent_input.storage.local`. |
| Unit tests | Added `test_storage.py` (11 tests), `test_interpretation_schemas.py` (7), `test_proposal_schemas.py` (7), `test_implementor_schemas.py` (7), `test_validator_schemas.py` (7). Fixed `valid_input_dict` fixture in existing hyperparam tests. **233 unit tests passing.** |
| `nodes/result_interpretation_agent.py` | Implemented `ResultInterpretationAgent.run()`. One LLM call: deterministic pre-computation (best score, best config) merged with LLM-generated `key_findings`, `bottlenecks`, `take_home_message`. Writes `interpretation_{run_name}.json`. Unit tests added (`test_interpretation_agent.py`, 8 tests). |
| `LLMBridge.generate_text()` | Added plain-text transport alongside `generate()` (JSON mode). Used for free-form reasoning steps where JSON mode constrains quality. 11 unit tests + 4 integration tests (skip if no API key). |
| Per-model `description.md` files | Added `ml_models/{punet,fcnet,transformer,wavenet,rnn}/description.md` — markdown + math descriptions of each architecture. Added `ml_models/model_descriptions.py` loader: searches `ml_models/{model_type}/description.md` then `agent_generated/models/{model_type}/description.md`; raises `FileNotFoundError` if missing. |
| `InterpretationInput` overhaul | Replaced `summary_records + model_type` with `summaries: List[SummaryGroup]` + `model_types: Optional[List[str]]`. New `SummaryGroup(model_type, run_name, records)`. Validator enforces at least one model reachable (from summaries or explicit `model_types`); empty `[]` for `model_types` is an error. |
| `InterpretationOutput` overhaul | Added `model_types: List[str]`, `model_descriptions: Dict[str, str]`, `per_model_best: Dict[str, Optional[float]]`, `per_model_worst: Dict[str, Optional[float]]`, `worst_denoising_score`. Carries full architecture knowledge forward to the proposal agent. |
| `result_interpretation_agent` rewrite | Now handles multiple summary groups across multiple model types. Computes per-model and overall best/worst deterministically before the LLM call. Loads descriptions for all effective model types (raises `FileNotFoundError` if any missing). Injects all model descriptions + experiment records into the LLM prompt. 20 unit tests (up from 8), organised in `TestSingleGroup`, `TestMultiGroup`, `TestModelTypesOnly`, `TestErrorCases`. |

| `ml_model_proposal_agent` | ✅ done (two-call CoT, human_advice, duplicate guard) |
| Protocol structure + naming convention | ✅ done (one-file-per-edge, `local_*`/`database_*` variants) |
| `ml_model_tune_to_ml_result_interp` protocol | ✅ done (`local_all_records`, `database_all_records` placeholder) |
| `ml_result_interp_to_ml_model_propose` protocol | ✅ done (`local_full_context`, `database_full_context` placeholder) |
| Unit + integration tests for proposal agent | ✅ done (35 unit, Tier 1 + Tier 2 real-API) |
| `ml_model_implementor` | ✅ done (two-call CoT, template assembly, description.md, self-correction loop with 3 pre-write checks) |
| `ml_model_propose_to_ml_model_impl` protocol | ✅ done (`local_full_spec`, `database_full_spec` placeholder) |
| Unit + integration tests for implementor | ✅ done (node unit ×52, schema unit ×10, protocol unit ×9, Tier 1 + Tier 2 real-API) |
| `ml_code_validator_agent` | ✅ done (7 checks: plugin load, pytest, description, config fields, instantiation, gradient flow, LLM code review — prompt calibrated to distinguish bugs from suggestions) |
| `ml_model_impl_to_ml_model_valid` protocol | ✅ done (`local_all_fields`, `database_all_fields` placeholder) |
| `ml_model_valid_to_ml_model_tune` protocol | ✅ done (`local_validated_model`, `database_validated_model` placeholder) |
| Unit + integration tests for validator | ✅ done (85 unit, Tier 1 + Tier 2 real-API) |

### Remaining

| Step | Status |
|------|--------|
| Add `run()` to `tune_ml_hyperparam_agent` + wire `seed_records` | ⬜ next |
| `workflows/model_exploration.py` | ⬜ |

---

## Next Steps in Detail

### Step 1 — `result_interpretation_agent` ⚠️ refactoring to two-phase

**File**: `nodes/result_interpretation_agent.py`.

**What was built (original — single LLM call, being replaced)**:
- `class ResultInterpretationAgent` with `run(input: InterpretationInput) -> InterpretationOutput`
- Accepts multiple summary groups across multiple model types (`summaries: List[SummaryGroup]`)
- Deterministically computes per-model and cross-model best/worst scores before the LLM call
- One LLM call: injects all model descriptions + experiment records; LLM produces
  `key_findings`, `bottlenecks`, `take_home_message` as strict JSON
- Writes output to `{storage.local.workspace}/interpretation_{run_name}.json`
- Validates input at entry and output at exit via Pydantic `model_validate()`
- 20 unit tests + 4 real-API integration tests (Gemini + OpenAI, single-model + multi-model)

**Refactoring to two-phase interpretation**:

The original single-LLM-call design dumps all experiment records from all models into one
prompt. This does not scale — with 20+ records per model and multiple models, the prompt
exceeds token limits and produces poor results. The fix is a two-phase approach:

1. **Phase 1 — Per-model summarization**: for each model type, call the LLM once with
   only that model's records and architecture description. Produces a structured JSON
   summary per model (key findings, best config, score trends, bottlenecks).
2. **Phase 2 — Cross-model synthesis**: take the structured per-model summaries (not
   raw records) and call the LLM once more to produce the final `InterpretationOutput`
   (comparative analysis, overall bottlenecks, take-home message).

This keeps each LLM call focused and within token limits. The per-model summaries are
explicit, inspectable, and stored alongside the final output.

**Current implementation**: Option A — both phases inside `ResultInterpretationAgent.run()`.
The node's input/output schemas are unchanged; the internal logic changes from one LLM
call to N+1 calls (N per-model + 1 synthesis).

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

### Step 5 — Add `run()` to `tune_ml_hyperparam_agent`

**What to build**:
- Extract the core loop logic from `main()` into a shared internal function
- Add `class HyperparamTuningAgent` with `run(input: HyperparamTuningInput) -> HyperparamTuningOutput`
- Wire `seed_records`: if `input.seed_records` is non-empty, write them to the sandbox
  summary file before the loop starts (so the agent treats them as prior memory)
- `main()` becomes a thin CLI wrapper that parses args, constructs `HyperparamTuningInput`,
  and calls `HyperparamTuningAgent().run(agent_input)`

---

### Step 6 — Protocols (all 5)

**Files**: one module per edge in `agent/schemas/protocols/`.

Each protocol is a plain typed function. The tricky one is `validator_to_hyperparam_v1`
which takes both `ValidatorOutput` and `ProposalOutput` as arguments (the validator
only confirms validity; the expert advice comes from the proposal).

| File | Function | Signature |
|------|----------|-----------|
| `ml_model_tune_to_ml_result_interp.py` | `local_all_records` | `(output: HyperparamTuningOutput, storage: StorageConfig) -> InterpretationInput` |
| `ml_result_interp_to_ml_model_propose.py` | `local_full_context` | `(output: InterpretationOutput, storage: StorageConfig) -> ProposalInput` |
| `ml_model_propose_to_ml_model_impl.py` | `local_full_spec` | `(output: ProposalOutput, storage: StorageConfig) -> ImplementorInput` |
| `ml_model_impl_to_ml_model_valid.py` | `local_all_fields` | `(output: ImplementorOutput, storage: StorageConfig) -> ValidatorInput` |
| `ml_model_valid_to_ml_model_tune.py` | `local_validated_model` | `(output: ValidatorOutput, proposal: ProposalOutput, storage: StorageConfig, max_rounds, file_index, llm_provider, llm_model_id) -> HyperparamTuningInput` |

---

### Step 7 — `workflows/model_exploration.py`

A linear script that ties everything together. Accepts CLI args for workspace, run_name,
model_type (for the initial tuning results to read), LLM provider, and max_rounds for
the final tuning run.

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
├── ml_hyperparameter_tune_agent.py       ✅ storage updated, run() ⬜
├── result_interpretation_agent.py        ✅ done (multi-model, cross-run, descriptions)
├── ml_model_proposal_agent.py            ✅ done (two-call CoT, human_advice, duplicate guard)
├── ml_model_implementor.py               ✅ done (two-call CoT, template assembly, description.md, self-correction loop)
└── ml_code_validator_agent.py              ✅ done (7 checks, calibrated LLM review)

workflows/
└── model_exploration.py                 ⬜

tests/
└── unit/
    └── agent/
        ├── tune_ml_hyperparam_agent/     ✅ 38 tests (28 schema + 10 skill)
        ├── result_interpretation_agent/  ✅ 32 tests (18 node + 14 schema)
        ├── test_llm_bridge.py            ✅ 11 tests (generate + generate_text, both providers)
        ├── ml_model_proposal_agent/      ✅ 35 tests (23 node + 12 schema)
        ├── ml_model_implementor/         ✅ 62 tests (52 node + 10 schema)
        ├── ml_code_validator_agent/      ✅ 85 tests (55 node + 30 schema)
        └── protocols/                    ✅ 56 tests (5 protocol modules)

tests/integration/nodes/              ✅ Tier 1 — single node, real API
    ├── test_llm_bridge.py                ✅ 4 tests (Gemini + OpenAI, generate + generate_text)
    ├── test_result_interpretation_agent.py ✅ 4 tests (Gemini + OpenAI, single + multi-model)
    ├── test_ml_model_proposal_agent.py   ✅ 2 tests (Gemini + OpenAI)
    ├── test_ml_model_implementor.py      ✅ 2 tests (Gemini + OpenAI, validates plugin + description.md)
    ├── test_ml_code_validator_agent.py   ✅ 18 tests (Gemini API, all-pass + all failure modes)
    └── test_tune_ml_hyperparam_agent.py  ✅ (skip if no API key + data)

tests/integration/protocols/         ✅ Tier 2 — one graph edge end-to-end
    ├── test_tune_to_interpret.py         ✅ 1 test (real fcnet loop → interpretation agent)
    ├── test_interp_to_propose.py         ✅ 2 tests (Gemini + OpenAI, no GPU needed)
    ├── test_propose_to_implement.py      ✅ 2 tests (Gemini + OpenAI, proposal → implementor edge)
    └── test_implement_to_validate.py     ✅ 2 tests (Gemini + OpenAI, full implement → validate chain)

tests/integration/workflows/         ⬜ Tier 3 — multi-hop workflow tests (empty, ready)

tests/unit/core/
    ├── test_storage.py                   ✅ done (11 tests)
    └── ...
```

**Total unit tests: 475 passing.**

---

## Demo Script Outline

```python
# workflows/model_exploration.py
import sys, json
from nodes.result_interpretation_agent import ResultInterpretationAgent
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import local_all_records
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from agent.schemas.storage import StorageConfig, LocalStorageConfig

storage = StorageConfig(backend="local", local=LocalStorageConfig(workspace="<workspace>", run_name="<run_name>"))

# --- Load existing tuning output ---
with open("<workspace>/run_output_<run_name>.json") as f:
    tuning_output = HyperparamTuningOutput.model_validate(json.load(f))

# Edge 1: tune → interpret
interpretation = ResultInterpretationAgent().run(
    local_all_records(tuning_output, storage)
)
print("Take-home:", interpretation.take_home_message)

# Edge 2: interpret → propose
proposal = MLModelProposalAgent().run(
    local_full_context(interpretation, storage)
)
print("Proposed model:", proposal.model_name)

# Edge 3: propose → implement
implementor_output = MLModelImplementor().run(
    local_full_spec(proposal, storage)
)
print("Written to:", implementor_output.model_file_path)

# Edge 4: implement → validate
validation = MLCodeValidatorAgent().run(
    local_all_fields(implementor_output, storage)
)
if not validation.passed:
    print("Validation failed:", validation.error_message)
    sys.exit(1)
print("Model validated.")

# Edge 5: validate → tune (fan-in: validator + proposal)
tuning_output = HyperparamTuningAgent().run(
    local_validated_model(validation, proposal, storage, file_index=6, max_rounds=10)
)
print("Best score:", tuning_output.best_denoising_score)
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

# LLM WRITES: config fields only
class {ModelClass}Config(BaseModel):
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
