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
        ↓  [ml_model_impl_to_ml_model_valid :: local_files]
ml_code_validator_agent
        ↓  [ml_model_valid_to_ml_model_tune :: local_with_advice]
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
| `ml_model_implementor` | ✅ done (two-call CoT, template assembly, description.md) |
| `ml_model_propose_to_ml_model_impl` protocol | ✅ done (`local_full_spec`, `database_full_spec` placeholder) |
| Unit + integration tests for implementor | ✅ done (node unit ×34, schema unit ×7, protocol unit ×9, Tier 1 + Tier 2 real-API) |

### Remaining

| Step | Status |
|------|--------|
| Implement `ml_code_validator_agent` | ⬜ next |
| Add `run()` to `tune_ml_hyperparam_agent` + wire `seed_records` | ⬜ |
| `ml_model_impl_to_ml_model_valid` protocol | ⬜ |
| `ml_model_valid_to_ml_model_tune` protocol | ⬜ |
| `demo/run_model_proposal_demo.py` | ⬜ |

---

## Next Steps in Detail

### Step 1 — `result_interpretation_agent` ✅ done

**File**: `nodes/result_interpretation_agent.py`.

**What was built**:
- `class ResultInterpretationAgent` with `run(input: InterpretationInput) -> InterpretationOutput`
- Accepts multiple summary groups across multiple model types (`summaries: List[SummaryGroup]`)
- Deterministically computes per-model and cross-model best/worst scores before the LLM call
- Loads architecture descriptions from `ml_models/{model_type}/description.md` for all models;
  raises `FileNotFoundError` if any description is missing
- One LLM call: injects all model descriptions + experiment records; LLM produces
  `key_findings`, `bottlenecks`, `take_home_message` as strict JSON
- Writes output to `{storage.local.workspace}/interpretation_{run_name}.json`
- Validates input at entry and output at exit via Pydantic `model_validate()`
- 20 unit tests + 4 real-API integration tests (Gemini + OpenAI, single-model + multi-model)

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
- Writes three files:
  - `{plugin_dir}/{model_name}.py` — the plugin file
  - `{plugin_dir}/{model_name}/description.md` — architecture description for the interpretation pipeline
  - `{test_dir}/test_{model_name}.py` — test skeleton (fully fixed, no LLM generation)
- Writes output record to `{storage.local.workspace}/implementor_{run_name}.json`
- Returns `ImplementorOutput` with absolute paths, `config_fields` summary, and `description_file_path`

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

**Key design insight — early syntax validation**:
The assembled plugin source is passed through `ast.parse()` before any file is written.
This catches undefined helper classes, malformed expressions, and other LLM mistakes with
a clear error message rather than silently writing broken code to disk.

**Key design insight — prompt constraints vs. validation layers**:
Prompt constraints (no helper classes, scalar config fields, Pydantic V2 kwargs, `config`
not in scope in `forward`) are best-effort guidance — LLMs do not always honour them. This
is expected. Constraints reduce the failure rate but are not the enforcement mechanism.
Programmatic validation in the `ml_code_validator_agent` (Node 5) is the correct place to
enforce correctness. The implementor's early `ast.parse()` check is a lightweight pre-flight
only; deep semantic validation belongs downstream.

**Template rendering**: the implementor holds the template as a string in the module,
substitutes `{model_name}`, `{ModelClass}`, then fills LLM-generated sections.

---

### Step 4 — `ml_code_validator_agent`

**File**: `nodes/ml_code_validator_agent.py`.

**What to build**:
- `class MLCodeValidatorAgent` with `run(input: ValidatorInput) -> ValidatorOutput`
- Step 1 — plugin registration check: call `ml_models/plugin_loader._load_plugin(model_file_path)`
  and verify it returns a non-None result with correct attributes
- Step 2 — run tests: `subprocess.run(["pytest", test_file_path, "-v"])` and capture
  stdout/stderr
- Returns `ValidatorOutput(passed=..., plugin_registered=..., error_message=...)`
- Writes output to `{storage.local.workspace}/validation_{run_name}.json`
- No LLM calls. Fully deterministic.

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

| File | Protocol | Signature |
|------|----------|-----------|
| `hyperparam_to_interpretation.py` | `hyperparam_to_interpretation_v1` | `(output: HyperparamTuningOutput, storage: StorageConfig) -> InterpretationInput` |
| `interpretation_to_proposal.py` | `interpretation_to_proposal_v1` | `(output: InterpretationOutput, storage: StorageConfig) -> ProposalInput` |
| `proposal_to_implementor.py` | `proposal_to_implementor_v1` | `(output: ProposalOutput, storage: StorageConfig) -> ImplementorInput` |
| `implementor_to_validator.py` | `implementor_to_validator_v1` | `(output: ImplementorOutput, storage: StorageConfig) -> ValidatorInput` |
| `validator_to_hyperparam.py` | `validator_to_hyperparam_v1` | `(validation: ValidatorOutput, proposal: ProposalOutput, storage: StorageConfig, file_index: int, max_rounds: int) -> HyperparamTuningInput` |

---

### Step 7 — `demo/run_model_proposal_demo.py`

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
- `storage: StorageConfig`

**Output schema** (`ImplementorOutput`):
- `model_type: str`
- `description_file_path: str` — absolute path to the written `description.md`
- `model_file_path: str`
- `test_file_path: str`
- `config_fields: Dict`

---

### 4. `ml_code_validator_agent`

**Input schema** (`ValidatorInput`):
- `model_type: str`
- `model_file_path: str`
- `test_file_path: str`
- `storage: StorageConfig`

**Output schema** (`ValidatorOutput`):
- `passed: bool`
- `model_type: str`
- `plugin_registered: bool`
- `error_message: Optional[str]`

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
| `implement → validate` | `ml_model_impl_to_ml_model_valid` | `local_files` | ⬜ |
| `validate → tune` | `ml_model_valid_to_ml_model_tune` | `local_with_advice` | ⬜ |

Note: `ml_model_valid_to_ml_model_tune::local_with_advice` takes both `ValidatorOutput`
and `ProposalOutput` as arguments — the validator only confirms the plugin is valid;
expert advice comes from the proposal node.

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
│       ├── ml_model_impl_to_ml_model_valid.py        ⬜
│       └── ml_model_valid_to_ml_model_tune.py        ⬜
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
├── ml_model_implementor.py               ✅ done (two-call CoT, template assembly, description.md)
└── ml_code_validator_agent.py              ⬜

demo/
└── run_model_proposal_demo.py            ⬜

tests/
└── unit/
    └── agent/
        ├── tune_ml_hyperparam_agent/     ✅ 35 tests (storage tests added)
        ├── result_interpretation_agent/  ✅ 32 tests (20 node tests + 12 schema tests)
        ├── test_llm_bridge.py            ✅ 11 tests (generate + generate_text, both providers)
        ├── ml_model_proposal_agent/      ✅ 26 tests (18 node + 8 schema)
        ├── protocols/                    ✅ 22 tests (11 per protocol module)
        ├── ml_model_implementor/         ✅ done (34 node tests + 7 schema tests)
        ├── protocols/                    ✅ done (9 tests for propose→implement protocol)
        └── ml_code_validator_agent/         ✅ schema tests done, node tests ⬜

tests/integration/nodes/              ✅ Tier 1 — single node, real API
    ├── test_llm_bridge.py                ✅ 4 tests (Gemini + OpenAI, generate + generate_text)
    ├── test_result_interpretation_agent.py ✅ 4 tests (Gemini + OpenAI, single + multi-model)
    ├── test_ml_model_proposal_agent.py   ✅ 2 tests (Gemini + OpenAI)
    ├── test_ml_model_implementor.py      ✅ 2 tests (Gemini + OpenAI, validates plugin + description.md)
    └── test_tune_ml_hyperparam_agent.py  ✅ (skip if no API key + data)

tests/integration/protocols/         ✅ Tier 2 — one graph edge end-to-end
    ├── test_tune_to_interpret.py         ✅ 1 test (real fcnet loop → interpretation agent)
    ├── test_interp_to_propose.py         ✅ 2 tests (Gemini + OpenAI, no GPU needed)
    └── test_propose_to_implement.py      ✅ 2 tests (Gemini + OpenAI, proposal → implementor edge)

tests/integration/orchestrator/      ⬜ Tier 3 — multi-hop critical loops (empty, ready)

tests/unit/core/
    ├── test_storage.py                   ✅ done (11 tests)
    └── ...
```

**Total unit tests: 350 passing.**

---

## Demo Script Outline

```python
# demo/run_model_proposal_demo.py
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
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_files
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_with_advice
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
    local_files(implementor_output, storage)
)
if not validation.passed:
    print("Validation failed:", validation.error_message)
    sys.exit(1)
print("Model validated.")

# Edge 5: validate → tune (expert_advice from proposal, not validator)
tuning_output = HyperparamTuningAgent().run(
    local_with_advice(validation, proposal, storage, file_index=6, max_rounds=10)
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
