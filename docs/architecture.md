# SIDERIUS Multi-Agent Architecture Design

## Vision

SIDERIUS is a large-scale multi-agent research platform built on a single unifying idea:
**the whole system is a typed, directed graph**. Every component — whether it uses an LLM,
runs a GPU training loop, writes code, or orchestrates other components — is a node in
this graph. Data flows between nodes through explicit, typed edges. No node ever calls
another node directly.

---

## Core Principles

### 1. The system is a directed graph

The entire SIDERIUS system is a **directed graph** where:

- **Nodes** are any module with a defined input schema and output schema — agents,
  orchestrators, validators, data loaders, scorers. The distinction between "agent" and
  "non-agent" is irrelevant at this level; what matters is that a node has a contract.
- **Edges** are directed connections between nodes. An edge `A → B` means B can consume
  A's output. The direction represents **data dependency**, not execution order.
- **Cycles are allowed.** A cycle such as `tune → interpret → propose → tune` is valid.
  Each traversal of an edge is always a finite, one-way data transformation. Cycles only
  become loops when an orchestrator chooses to traverse them repeatedly.

### 2. Every node is a pure function

Each node receives a validated input, performs its work, and returns a validated output.
It does not know what came before it or what comes after it. It does not call other nodes.

```python
class MyNodeInput(BaseModel):
    ...  # well-defined, validated fields

class MyNodeOutput(BaseModel):
    ...  # well-defined, validated fields

class MyNode:
    def run(self, input: MyNodeInput) -> MyNodeOutput:
        ...
```

This applies to every node without exception — leaf agents, orchestrators, validators,
and utility modules alike.

### 3. Edges require a protocol

Two nodes can only be connected if a **protocol** exists on that edge. A protocol is a
named, versioned, explicit function that maps the source node's output schema to the
target node's input schema:

```python
def protocol_name(output: NodeAOutput) -> NodeBInput:
    ...
```

A protocol is **strictly directional**: `A → B` and `B → A` are two separate protocols.
There is no bidirectional or symmetric protocol. Each protocol arrow has one source and
one target, and data always flows in one direction per traversal.

A protocol is also **transparent on both ends**: the function signature explicitly names
what it reads from the source (`NodeAOutput`) and what it produces for the target
(`NodeBInput`). There is no implicit field mapping or automatic wiring — every field
consumed and every field populated is visible in the function body.

**Loops are allowed**, but they do not change the directionality of individual protocols.
When a cycle exists in the graph (e.g. `A → B → C → A`), each edge in the cycle is
still a one-way protocol. The loop is created by an orchestrator repeatedly traversing
the same directed edges — not by any protocol becoming bidirectional.

- Output and input schemas do **not** need to match exactly. The protocol is the
  translation layer between them.
- **Multiple protocols can exist on the same edge.** Different orchestrators, or
  different stages of the same workflow, may apply different protocols between the same
  two nodes. Each protocol is a distinct, named function.

### 4. Protocols are independent of orchestrators

A protocol between two nodes exists as a standalone function in `agent/schemas/protocols/`.
It is not embedded inside any orchestrator. Any orchestrator — or a human — can use it
without touching either node. Adding a new orchestrator never requires modifying an
existing protocol or node.

**Current role — explicit documentation and canonical wiring.**
Today, protocols are called explicitly by humans, demo scripts, or integration tests.
Their primary value is making the data transformation between two nodes typed, visible,
and independently testable. Calling the protocol is the preferred way to wire nodes —
even when a caller could technically construct the target input by hand, using the
protocol is the correct practice because it expresses the intended edge and keeps
wiring consistent across the codebase.

**Future role — programmatic discovery by orchestrators.**
As orchestrators are implemented, they will query the protocol registry
(`agent/schemas/protocols/`), select a protocol by name for each edge, and call it.
At that point the protocol transitions from documentation to an executable contract
that the orchestrator discovers and applies automatically. The registry is the
interface through which orchestrators learn what transformations are available on
each edge and which transport variants exist.

### 5. Orchestrators are nodes too

An orchestrator has its own input schema, output schema, and `run()` method. It is a
node in the graph and can itself be connected to other nodes via protocols. This makes
the hierarchy **recursive**: an orchestrator can be called by a higher-level
orchestrator, which is also a node, and so on.

The only thing that distinguishes an orchestrator from a leaf node is behaviour, not
structure:

| | Leaf node | Orchestrator node |
|---|---|---|
| Has `run(input) -> output` | ✅ | ✅ |
| Has CLI interface | ✅ | ✅ |
| Governed by input/output schema | ✅ | ✅ |
| Makes LLM calls internally | may | no |
| Calls other nodes via `run()` | no | yes |
| Selects and applies protocols on edges | no | yes |
| Can loop or branch | no | yes |
| Stateless between calls | yes | yes |

### 6. Orchestrators select paths and choose protocols

An orchestrator does not define the graph — the graph is defined by the nodes and their
protocols, and is fixed. The orchestrator has two distinct responsibilities:

1. **Select a path** — decide which nodes to visit and in what order.
2. **Choose the protocol on each edge** — since multiple protocols can exist between the
   same two nodes, the orchestrator selects which protocol to apply at each traversal.
   This is not a passive lookup; it is an active decision. The same edge can be crossed
   with a different protocol on the next iteration of a loop, or by a different
   orchestrator entirely.

This is a strict separation:
- **Graph topology** (which nodes exist, which edges exist, which protocols are defined)
  is static and declared independently of any orchestrator.
- **Execution** (which path to take, which protocol to apply, how many times to traverse
  a cycle, what to do on failure) is the orchestrator's responsibility alone.

### 7. Cycles are driven by orchestrators, not nodes

A node is always stateless. It has no memory of previous calls. Cycles in the graph
exist as potential paths — they become actual loops only when an orchestrator explicitly
traverses them repeatedly, passing updated inputs on each iteration. The nodes in the
cycle are unaware that a loop is happening.

### 8. Schemas define format; storage defines location

Input and output schemas define the **data contract** — what a node receives and
produces. They specify types, field names, and validation rules. They are completely
**transport-agnostic**: a node does not know or care whether its input arrived from
memory, a local file, or a database.

`StorageConfig` is a separate concern. It specifies **where** data is persisted and
**how** to retrieve or write it. It is passed through the system by the orchestrator
and injected into each node's input at traversal time.

This separation has one critical implication for protocols: **a protocol must always
return a fully populated input schema**, regardless of the transport it uses. A
`database_*` protocol reads from the database and populates the schema completely
before handing it to the node. The node on the receiving end never sees a half-empty
schema or a storage handle — it always receives the full, validated data contract.

```
Node A output schema  ──► protocol (local or database) ──► Node B input schema (fully populated)
                                         ▲
                                  StorageConfig
                              (injected by orchestrator)
```

### 9. Inter-node communication uses exactly three mechanisms

Nodes communicate exclusively through **schema**, **storage**, and **protocols**. No other
form of inter-node communication is permitted.

- **Schema**: the input and output `BaseModel` of each node is the complete, explicit
  contract for what data flows in and out. Every field that a downstream node needs must
  appear in the upstream node's output schema and be mapped by the protocol. There are no
  hidden contracts or implicit field sharing.
- **Storage**: each node writes its own output record to the workspace for persistence and
  recovery. This is a **log**, not a communication channel. Downstream nodes never read the
  upstream node's output file to discover their input — they receive data through the
  protocol function in memory.
- **Protocols**: the only place field mapping happens. The protocol function receives the
  full upstream `*Output` object and constructs the fully populated downstream `*Input`.
  No field should be silently dropped.

This constraint is what keeps the graph clean as it grows. Any shortcut — reading a file
by naming convention, sharing state through the filesystem, passing a path as a proxy for
data — creates a hidden dependency invisible to the protocol system. Such shortcuts make
nodes untestable in isolation and fragile when the graph is rearranged.

---

## Node Contract

Every node (leaf or orchestrator) must satisfy:

- **Programmatic interface**: `run(input: NodeInput) -> NodeOutput` — called by
  orchestrators, demo scripts, and tests.
- **CLI interface**: `argparse` entry point — called by humans for standalone use or
  debugging.
- **Schema validation**: input is validated via `model_validate()` at entry; output is
  validated via `model_validate()` before returning.
- **Stateless w.r.t. other nodes**: does not import, call, or depend on any other node.
- **Individually testable**: can be run and validated in isolation without standing up
  any other part of the system.

---

## The Graph (current nodes and edges)

```
data_analysis_agent ──────────────────────────────────► result_interpretation_agent
data_analysis_agent ──────────────────────────────────► ml_model_proposal_agent

tune_ml_hyperparam_agent ─────────────────────────────► result_interpretation_agent

result_interpretation_agent ──────────────────────────► ml_model_proposal_agent

ml_model_proposal_agent ──────────────────────────────► tune_ml_hyperparam_agent
ml_model_proposal_agent ──────────────────────────────► ml_model_implementor

ml_model_implementor ─────────────────────────────────► ml_code_validator_agent
ml_code_validator_agent ─────────────────────────────────► tune_ml_hyperparam_agent
```

Each edge has at least one named protocol. The cycle
`tune → interpret → propose → implement → validate → tune`
is the core research loop, traversed by an orchestrator.

---

## Protocols

Protocols live in `agent/schemas/protocols/`. Each is a plain Python function, named
and versioned, with fully typed arguments and return value.

### Current and planned protocols

| Edge | Protocol | Consumes from source | Populates in target |
|------|----------|----------------------|---------------------|
| `tune → result_interpretation` | `hyperparam_to_interpretation_full_v1` | full `HyperparamTuningOutput` | all experiment records, model type, file index |
| `tune → result_interpretation` | `hyperparam_to_interpretation_summary_v1` | `best_exp_id`, `best_denoising_score`, `best_config` | summary-only view |
| `result_interpretation → ml_model_proposal` | `interpretation_to_proposal_v1` | bottlenecks, patterns, saturation signals | `prior_analysis`, `suggested_focus` |
| `ml_model_proposal → tune` | `proposal_to_hyperparam_advice_v1` | proposal rationale + architecture description | `expert_advice: ExpertAdvice` |
| `ml_model_proposal → tune` | `proposal_to_hyperparam_seeded_v1` | proposal + known baselines | `expert_advice` + `seed_records` |
| `ml_model_proposal → ml_model_implementor` | `proposal_to_implementor_v1` | architecture spec, forward contract | `model_spec`, `test_requirements` |
| `code_validator → tune` | `validator_to_hyperparam_v1` | validated model type, plugin path | `model_type`, updated `expert_advice` |
| `data_analysis → result_interpretation` | `data_to_interpretation_v1` | dataset statistics, shift signals | `dataset_context` |
| `data_analysis → ml_model_proposal` | `data_to_proposal_v1` | distribution properties | `data_constraints` |

---

## Orchestration

An orchestrator selects a path through the graph, applies protocols on each edge,
and calls `node.run()` at each step. It introduces control flow — sequential execution,
conditional branching, and loops by re-traversing cycles.

### Example: model exploration loop (Level 1 orchestrator)

```
1. tune_ml_hyperparam_agent    → initial tuning run (N rounds)
2. result_interpretation_agent → identify bottlenecks              [hyperparam_to_interpretation_full_v1]
3. ml_model_proposal_agent     → propose new architecture          [interpretation_to_proposal_v1]
4. ml_model_implementor        → write model code + tests          [proposal_to_implementor_v1]
5. ml_code_validator_agent        → run tests, confirm valid          [implementor_to_validator_v1]
6. tune_ml_hyperparam_agent    → tune the new model                [validator_to_hyperparam_v1]
7. goto 2                      → repeat until convergence
```

### Recursive hierarchy

```
Human / Top-level CLI
└── research_campaign_orchestrator          ← Level 2
    ├── model_exploration_orchestrator      ← Level 1
    │   ├── tune_ml_hyperparam_agent        ← Level 0
    │   ├── result_interpretation_agent     ← Level 0
    │   ├── ml_model_proposal_agent         ← Level 0
    │   ├── ml_model_implementor            ← Level 0
    │   └── ml_code_validator_agent            ← Level 0
    ├── data_analysis_agent                 ← Level 0
    └── result_interpretation_agent         ← Level 0 (final cross-model summary)
```

A human can substitute for any orchestrator at any level by manually applying protocols
and calling nodes via CLI.

---

## Existing Nodes

### `tune_ml_hyperparam_agent` (`ml_hyperparameter_tune_agent.py`)

**Role**: Optimize hyperparameters for a given ML model architecture.

**Internal loop** (runs entirely within a single `run()` call):
```
Load memory → Propose hypothesis + config (LLM) → Resource check
→ Train → Infer → Score → Reflect (LLM) → Save record → repeat
```

**Input schema** (`HyperparamTuningInput`):
- `model_type`: architecture to tune, or `"auto"` for LLM-driven selection
- `run_name`: experiment run identifier
- `file_index`: training/validation file index (default: 6)
- `max_rounds`: number of completed experiment rounds
- `expert_advice`: `str` (human CLI) or `ExpertAdvice` object (agent-to-agent protocol)
- `seed_records`: pre-existing records injected into memory before round 1
- `llm_provider`, `llm_model_id`: LLM configuration

**Output schema** (`HyperparamTuningOutput`):
- `status`: `completed | partial | failed`
- `completed_rounds`, `total_attempts`
- `best_exp_id`, `best_denoising_score`, `best_config`
- `all_records`: full experiment history (params, results, timing, LLM memory)
- `started_at`, `finished_at`

---

## Node Taxonomy

| Node | Role | GPU? | Writes code? | LLM? |
|------|------|------|--------------|------|
| `tune_ml_hyperparam_agent` | Trains, infers, scores a model with a given config | yes | no | yes |
| `result_interpretation_agent` | Synthesizes experiment results, surfaces bottlenecks and patterns | no | no | yes |
| `ml_model_proposal_agent` | Reads interpretation → proposes new model architecture + expert advice | no | no | yes |
| `ml_model_implementor` | Takes a model proposal → writes PyTorch code + unit tests | no | yes | yes |
| `ml_code_validator_agent` | Runs generated tests, verifies plugin interface | no | no | no |
| `data_analysis_agent` | Profiles dataset properties, detects distribution shifts | no | no | yes |

---

## Plugin System

Agent-generated models (`ml_model_implementor` outputs) are dropped into
`agent_generated/models/` as `.py` files. Each plugin must define:

- `PLUGIN_MODEL_TYPE: str` — unique model type key
- `PLUGIN_CONFIG_CLASS: BaseModel` — Pydantic config schema
- `PLUGIN_MODEL_CLASS: nn.Module` — model class with forward contract `[B, T] int → [B, 256, T] float`

`ml_models/plugin_loader.py` scans this directory at import time and extends `MODEL_REGISTRY`
and `PLUGIN_CONFIG_REGISTRY` in-place. The core codebase is never modified by agents.
Agent-generated tests live in `agent_generated/tests/` and are excluded from the main
test suite.

---

## Data Paths (current)

```
/home/klz/Data/TIDMAD/                          # raw input data (read-only)
/home/klz/Data/SIDEREIS_DATA/
├── {model}/
│   ├── baseline/                               # baseline run (shared across run_names)
│   └── {run_name}/agent/                       # agent run outputs
│       ├── run_config_{run_name}.json          # startup config (includes file_index)
│       ├── summary_{run_name}.json             # all experiment records (agent memory)
│       ├── run_output_{run_name}.json          # validated HyperparamTuningOutput
│       ├── records/{run_name}/                 # per-experiment detail JSONs
│       ├── configs/                            # model/train/loss configs per exp_id
│       └── cached_models/                      # trained model checkpoints (.pth)
└── raw_baseline/
    └── raw_baseline_score_file_{index:04d}.json  # undenoised reference scores
```

---

## Testing Strategy

Agent tests have four categories. Unit tests run on every commit. The three integration
tiers require external resources and are always gated by `pytest.mark.real_run` — they
must never run in CI.

### Unit tests

**What**: Test a single node in complete isolation. All LLM calls are mocked (e.g.
`patch("nodes.foo.LLMBridge")`). No GPU, no real data, no API key required.

**What to test**:
- Deterministic pre-computation is correct (score extraction, record counting, etc.)
- LLM response is merged into the output schema correctly
- Output validates against the Pydantic schema
- Output file is written to the correct path
- Error cases raise the expected exceptions

**Location**: `tests/unit/agent/{node_name}/`

**Rule**: 100% of unit tests must always pass. Adding a node means adding unit tests
before merging.

---

### Integration Tier 1 — Individual node

**What**: Call a single node end-to-end with a real LLM. No other nodes involved.

**What to test**:
- Node produces a valid, non-empty output with a real API response
- Output validates against the Pydantic schema
- Output file is written correctly
- Both Gemini and OpenAI providers work (where applicable)

**Location**: `tests/integration/nodes/test_{node_name}.py`

**Rule**: One file per node. Tests skip automatically when the required API key or
data is missing. Do NOT parametrise over every model/loss combination — one or two
representative configs are enough.

---

### Integration Tier 2 — Protocol (predecessor → successor)

**What**: Test one directed edge in the graph. Run the source node for real, apply the
protocol function, then run the target node for real. Both nodes run; all others absent.

**What to test**:
- The protocol function correctly maps source output to target input
- The target node accepts the protocol output without validation errors
- Key fields in the target output are non-empty and structurally correct

**Location**: `tests/integration/protocols/test_{source}_to_{target}.py`

**Rule**: One file per directed edge in the graph. One representative config per file.

---

### Integration Tier 3 — Orchestrator (critical loops)

**What**: Test a critical multi-hop path through the graph — two or more protocol
edges traversed in sequence, representing a real research workflow.

**What to test**:
- A full traversal of the core research loop produces coherent outputs at every stage
- The orchestrator's control logic (loop termination, error handling) works on a real run

**Location**: `tests/integration/orchestrator/test_{loop_name}.py`

**Rule**: Test only the critical paths, not every combination. Combinatorial coverage
belongs in unit tests. A Tier 3 test that takes more than ~10 minutes is doing too much
— break it into smaller Tier 2 tests instead. One representative config per loop.

---

### Summary

| Category | Scope | LLM | GPU | Location | When to run |
|----------|-------|-----|-----|----------|-------------|
| Unit | Single node, mocked LLM | mock | no | `tests/unit/` | Every commit |
| Integration Tier 1 | Single node, real API | real | depends | `tests/integration/nodes/` | On demand |
| Integration Tier 2 | One edge (source → target) | real | depends | `tests/integration/protocols/` | On demand |
| Integration Tier 3 | Critical multi-hop loop | real | yes | `tests/integration/orchestrator/` | Before releases |

---

## TODO: Multi-Dataset Support

The current execution layer (`execute_tools/`, `core/sandbox_executor.py`, `ml_models/`) is
tightly coupled to the TIDMAD dataset (HDF5 format, ADC 0–255 values, denoising score metric,
`file_index` split scheme). The agent layer above it is already dataset-agnostic.

When a second dataset is introduced, extract a backend interface:

- Move TIDMAD-specific code into `backends/tidmad/`
- Define a thin `DatasetBackend` protocol that `sandbox_executor` calls
- Each new dataset implements its own backend (data loading, scoring metric, split scheme)
- The agent nodes and schemas remain unchanged

**Do not design this abstraction speculatively.** Extract it when there is a second concrete
use case — at that point the right interface boundary will be obvious.
