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

- The protocol is **dual-sided**: it explicitly documents what it consumes from the
  source and what it populates in the target. Both sides are typed and visible.
- Output and input schemas do **not** need to match exactly. The protocol is the
  translation layer. What is required is that a valid, explicit protocol exists — there
  is no implicit or automatic wiring.
- **Multiple protocols can exist on the same edge.** Different orchestrators, or
  different stages of the same workflow, may apply different protocols between the same
  two nodes. Each protocol is a distinct, named function.

### 4. Protocols are independent of orchestrators

A protocol between two nodes exists as a standalone function in `agent/schemas/protocols/`.
It is not embedded inside any orchestrator. Any orchestrator — or a human — can use it
without touching either node. Adding a new orchestrator never requires modifying an
existing protocol or node.

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
| Applies protocols to wire nodes | no | yes |
| Can loop or branch | no | yes |
| Stateless between calls | yes | yes |

### 6. Orchestrators select and traverse paths

An orchestrator does not define the graph — the graph is defined by the nodes and their
protocols, and is fixed. The orchestrator's job is to **select a path** (or multiple
paths) through the graph, apply the relevant protocol on each edge, call each node's
`run()` method, and decide when to stop.

This is a strict separation:
- **Graph topology** (which nodes exist, which edges exist, which protocols are defined)
  is static and declared independently of any orchestrator.
- **Execution** (which path to take, how many times to traverse a cycle, what to do on
  failure) is the orchestrator's responsibility alone.

### 7. Cycles are driven by orchestrators, not nodes

A node is always stateless. It has no memory of previous calls. Cycles in the graph
exist as potential paths — they become actual loops only when an orchestrator explicitly
traverses them repeatedly, passing updated inputs on each iteration. The nodes in the
cycle are unaware that a loop is happening.

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

ml_model_implementor ─────────────────────────────────► code_validator_agent
code_validator_agent ─────────────────────────────────► tune_ml_hyperparam_agent
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
5. code_validator_agent        → run tests, confirm valid          [implementor_to_validator_v1]
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
    │   └── code_validator_agent            ← Level 0
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
| `code_validator_agent` | Runs generated tests, verifies plugin interface | no | no | no |
| `data_analysis_agent` | Profiles dataset properties, detects distribution shifts | no | no | yes |

---

## Plugin System

Agent-generated models (`ml_model_implementor` outputs) are dropped into
`agent_generated/models/` as `.py` files. Each plugin must define:

- `PLUGIN_MODEL_TYPE: str` — unique model type key
- `PLUGIN_CONFIG_CLASS: BaseModel` — Pydantic config schema
- `PLUGIN_MODEL_CLASS: nn.Module` — model class with forward contract `[B, T] int → [B, 256, T] float`

`core/plugin_loader.py` scans this directory at import time and extends `MODEL_REGISTRY`
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
