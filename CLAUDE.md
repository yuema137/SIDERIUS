# SIDERIUS Project Rules

## Context
- SIDERIUS is a project that utilizes LLM agent to explore advanced denoising algorithms (stage 0), propose new hypothesis and conduct experiment to investigate (stage 1). 

## Coding Standards:
- **Logic First**: Before every modification, we need to review the current structure of the whole project, think about if the structure is appropriate, rather than just adding the desired feasure. We need to keep the code clean and elegant.
- **Slow is Smooth, Smooth is Fast**: Never be greedy when we try to add a new feature, or when we refactor the code. Fix the bug is always the priority, then comes the elegancy of the structure. Focus on the current problem at each step and don't over optimize.
- **Clear docstring and comments**: we need to write correct type for inputs and outputs. Pydantic validation and appropriate error message is highly recommanded for every function and class
- **Avoid deep dependency between modules**: we always want each module could be tested indivially, and be pluggable and decoupled.
- **Always think what test we can add for each single module**: pytest is a powerful tool. We should always equip our code with that. 
- **Be humble and curious**: if you are not sure about something, for example the detail of the desired feature, or the format of data, please don't guess by yourself, but ASK the user explicitely.
- **Be strict to the user and always double check**: what I say is not always correct. If you feel that are some wrong statement made by me, or some ideas are not pratically, you need to ask for clarification and state your objection clearly.

## Graph Architecture — Adding a New Node

SIDERIUS has a **directed graph structure** where nodes are agents or processing modules
and edges are typed protocols. When adding any new node, work through all 8 steps below.
Do not consider a node "done" until all 8 are complete.

| Step | Artefact | Location |
|------|----------|----------|
| 0 | **Graph placement** — decide which existing nodes feed into this node (upstream) and which nodes consume its output (downstream). Draw or write out the directed edges explicitly: `A → new_node → B`. Confirm the input schema can be fully populated from the upstream node's output schema, and that the output schema covers everything the downstream node needs. No file is generated at this step. | (design only) |
| 1 | Node implementation | `nodes/{node_name}.py` |
| 2 | Protocol(s) for each edge this node participates in | `agent/schemas/protocols/{source}_to_{target}.py` |
| 3 | Node unit tests (mocked LLM) | `tests/unit/agent/{node_name}/test_{node_name}.py` |
| 4 | Protocol unit tests | `tests/unit/agent/protocols/test_{source}_to_{target}.py` |
| 5 | Node integration test (real API, Tier 1) | `tests/integration/nodes/test_{node_name}.py` |
| 6 | Protocol integration test (real API, Tier 2) | `tests/integration/protocols/test_{source}_to_{target}.py` |
| 7 | **Connection audit** — verify end-to-end schema compatibility: every field required by the downstream node's input schema is present in this node's output schema, and every field required by this node's input schema is present in the upstream node's output schema. Check that each protocol function correctly maps all fields without silent defaults or missing keys. Run the full unit test suite to confirm nothing is broken. | (no new file — audit existing files) |

**Agent design principle**: each agent is scoped to one well-defined category of task within
its module, and should be flexible enough to handle that task well. Cross-task and cross-module
flexibility is the responsibility of the infrastructure (orchestrators, protocols) — not the
agent. An agent that tries to be general-purpose becomes unpredictable and hard to test.
Concretely: `ml_code_validator_agent` validates ML model plugin code — it does not validate
arbitrary code, and it knows about the ML plugin interface contract specifically.

**Agent naming convention**: agent names are prefixed by the module they belong to, followed
by a concise, specific descriptor of their task. The prefix is not universal — it reflects
which module the agent lives in. As new modules are added (e.g. a data module, a reporting
module), they will introduce their own prefixes. Do not use a prefix from a different module
just because it sounds close.

| Prefix | Module | Example agents |
|--------|--------|----------------|
| `ml_` | Machine learning pipeline | `ml_hyperparameter_tune_agent`, `ml_model_proposal_agent`, `ml_model_implementor`, `ml_code_validator_agent` |
| `data_` | Data processing / analysis | `data_analysis_agent` |

When naming a new agent: identify which module it belongs to, use that module's prefix, then
add a short snake_case descriptor of the specific task. Avoid generic suffixes like `_processor`
or `_handler` — be specific. A name like `code_validator_agent` (no prefix) is wrong because it
implies generality across modules; `ml_code_validator_agent` is correct because it is explicitly
scoped to the ML pipeline.

**Protocol naming convention**: one file per directed edge, named `{source_code}_to_{target_code}.py`.
Node codes: `ml_model_tune`, `ml_result_interp`, `ml_model_propose`, `ml_model_impl`, `ml_model_valid`.
Functions inside the file: `{transport}_{data_scope}` (e.g. `local_all_records`, `database_full_context`).
Always add a `database_*` placeholder (raises `NotImplementedError`) alongside every `local_*` function.

**Integration test tiers** — tiers describe how many nodes are exercised in a single real-API test,
not API load or cost. All tiers skip automatically if the required API key is not set.

| Tier | Scope | Location | What it tests |
|------|-------|----------|---------------|
| **Tier 1** | One node in isolation | `tests/integration/nodes/` | A hand-crafted synthetic input is passed directly to `node.run()`. Validates that the node itself works end-to-end with a real LLM call. No other node is involved. |
| **Tier 2** | One directed edge (two nodes) | `tests/integration/protocols/` | The upstream node runs with a real LLM call, the protocol function maps its output to the downstream node's input, and the downstream node runs. Validates that the wiring between two specific nodes is correct. |
| **Tier 3** | Multi-hop path (3+ nodes) | `tests/integration/orchestrator/` | A sequence of nodes traversed end-to-end. Validates that a complete sub-path of the graph works correctly. Not yet implemented. |

Steps 5 and 6 in the node checklist correspond to Tier 1 and Tier 2 respectively.

## Reference Project Guidelines
- You have read access to `legacy_repo`: /home/tidmad/TIDMAD. 
- **CRITICAL**: The legacy project is unoptimized and contains deprecated patterns. 
- Do NOT replicate the legacy project's structure. 
- Only reference it for specific physics formulas or data-loading logic as requested. Don't go beyond the required file or module.
- Prioritize modern, PEP 8, and modular standards for SIDERIUS.