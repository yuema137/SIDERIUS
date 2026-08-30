# SIDERIUS Multi-Agent Architecture Design

## Vision

SIDERIUS is a large-scale multi-agent research platform built on a single unifying idea:
**the whole system is a typed, directed graph**. Every component — whether it uses an LLM,
runs a GPU training loop, writes code, or orchestrates other components — is a node in
this graph. Data flows between nodes through explicit, typed edges. No node ever calls
another node directly.

---

## Core Principles

### 0. No component may be smuggled into another component's function

**Binding, operator decision 2026-08-01.** A function that coordinates
multiple phases, builds records, handles errors, mutates state, performs
I/O and decides control flow is not one component — it is several
sharing a scope, and the graph architecture below stops describing the
code the moment that happens.

New work must not add substantial branching, record construction,
persistence or task logic to an already oversized function. Extract a
typed, independently testable boundary first, prove behavioural parity,
then put the new logic inside it. Split by responsibility, never by line
count, and decompose in passing as touched work requires — never as a
repository-wide rewrite.

An extracted unit is only complete when it has explicit inputs, a typed
result, bounded side effects, focused tests, and a reachability test
that fails if production bypasses it. A helper that still reads and
mutates arbitrary outer state has relocated complexity, not reduced it.

Full rule and rationale: `docs/design/v20_priorities.md` §1.5 and
`CLAUDE.md`.

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

### 3. Protocols assemble node inputs

A **protocol** is a named, typed function that assembles a fully populated input schema
for a target node from one or more upstream node outputs. It is the only place where
field mapping between nodes happens.

```python
# Simple protocol — one source
def protocol_name(output: NodeAOutput, storage: StorageConfig) -> NodeBInput:
    ...

# Aggregation protocol — multiple sources (fan-in)
def protocol_name(output_a: NodeAOutput, output_c: NodeCOutput, storage: StorageConfig) -> NodeBInput:
    ...
```

The **target node's input schema is the completeness contract**. It defines what fields
are required, with Pydantic validation. The protocol's job is to satisfy that contract
— the target node does not know or care how many sources contributed to its input.

A protocol is **strictly directional**: it always produces a specific target node's
input. `A → B` and `B → A` are two separate protocols. Data always flows in one
direction per traversal.

A protocol is also **transparent**: the function signature explicitly names every
source output it reads from and the target input it produces. There is no implicit
field mapping or automatic wiring — every field consumed and every field populated is
visible in the function body.

**Fan-in** — when a target node needs data from multiple non-adjacent sources, the
protocol takes multiple output arguments. The workflow (or orchestrator) holds all
intermediate outputs and passes them to the protocol. The protocol file is named by
the **primary triggering edge** (the adjacent upstream node), with fan-in sources
documented in the function signature and docstring.

```
Node A output ──┐
                 ├──► protocol ──► Node B input (fully populated)
Node C output ──┘        ▲
                    StorageConfig
```

**Fan-out** — a node's output can be consumed by multiple downstream protocols. Each
protocol reads the fields it needs from the same output object. No special mechanism
is required; this is just multiple protocols referencing the same source type.

**Loops are allowed**, but they do not change the directionality of individual protocols.
When a cycle exists in the graph (e.g. `A → B → C → A`), each edge in the cycle is
still a one-way protocol. The loop is created by a workflow or orchestrator repeatedly
traversing the same directed edges — not by any protocol becoming bidirectional.

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
protocols, and is fixed. The orchestrator has three distinct responsibilities:

1. **Select a path** — decide which nodes to visit and in what order.
2. **Choose the protocol on each edge** — since multiple protocols can exist between the
   same two nodes, the orchestrator selects which protocol to apply at each traversal.
   This is not a passive lookup; it is an active decision. The same edge can be crossed
   with a different protocol on the next iteration of a loop, or by a different
   orchestrator entirely.
3. **Supply fan-in outputs** — when a protocol aggregates multiple sources, the
   orchestrator (or workflow) holds all intermediate outputs and passes the required
   ones to the protocol. The orchestrator is the only component that has visibility
   across the full traversal path.

This is a strict separation:
- **Graph topology** (which nodes exist, which edges exist, which protocols are defined)
  is static and declared independently of any orchestrator.
- **Execution** (which path to take, which protocol to apply, which outputs to pass to
  fan-in protocols, how many times to traverse a cycle, what to do on failure) is the
  orchestrator's responsibility alone.

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
return a fully populated input schema**, regardless of the transport it uses or how
many sources it aggregates. A `database_*` protocol reads from the database and
populates the schema completely before handing it to the node. The node on the
receiving end never sees a half-empty schema or a storage handle — it always receives
the full, validated data contract.

```
Node A output ──┐
                 ├──► protocol (local or database) ──► Node B input schema (fully populated)
Node C output ──┘              ▲
(optional fan-in)        StorageConfig
                     (injected by workflow)
```

### 9. Inter-node communication uses exactly three mechanisms

Nodes communicate exclusively through **schema**, **storage**, and **protocols**. No other
form of inter-node communication is permitted.

- **Schema**: the input and output `BaseModel` of each node is the complete, explicit
  contract for what data flows in and out. Every field that a downstream node needs must
  be present in one or more upstream node output schemas and mapped by the protocol. There
  are no hidden contracts or implicit field sharing.
- **Storage**: each node writes its own output record to the workspace for persistence and
  recovery. This is a **log**, not a communication channel. Downstream nodes never read the
  upstream node's output file to discover their input — they receive data through the
  protocol function in memory.
- **Protocols**: the only place field mapping happens. The protocol function receives one
  or more upstream `*Output` objects and constructs the fully populated downstream `*Input`.
  No field should be silently dropped.

This constraint is what keeps the graph clean as it grows. Any shortcut — reading a file
by naming convention, sharing state through the filesystem, passing a path as a proxy for
data — creates a hidden dependency invisible to the protocol system. Such shortcuts make
nodes untestable in isolation and fragile when the graph is rearranged.

### 9a. Every external dependency is mockable

The system has exactly two classes of external dependency: **LLM API calls** (through
`LLMBridge`) and **subprocess execution** (through `TidmadSandbox`). Both are hidden
behind constructor-injected factory parameters on every node, so a test can substitute
recording fakes (`RecordingLLMBridge`, `RecordingSandbox`) without touching production
code. This is what makes dual-mode testing possible: the same integration test runs
against real dependencies or recording fakes, selected by a pytest fixture.

The `LLMBridge` singleton invariant (enforced by
`tests/unit/agent/test_llm_bridge_singleton.py`) guarantees no code outside
`agent/llm_bridge.py` constructs an `OpenAI()` client. Combined with the DI factories,
this means a single `--real-api-call` flag controls whether the entire system talks to
real APIs or to recording fakes. See [`tests/pseudo_data/README.md`](../tests/pseudo_data/README.md)
for the pseudo-mode fixtures.

---

## Node Contract

Every node (leaf or orchestrator) must satisfy:

- **Programmatic interface**: `run(input: NodeInput) -> NodeOutput` — called by
  orchestrators, demo scripts, and tests.
- **CLI interface**: `argparse` entry point — called by humans for standalone use or
  debugging. All six built nodes expose one (`main()` behind
  `if __name__ == "__main__":`); `ml_literature_review`'s landed last (#303/#305),
  reading its upstream record from disk by naming convention. The per-node
  `main()` locations are tabulated in
  [`docs/agent-reference/README.md`](agent-reference/README.md).
- **Schema validation**: input is validated via `model_validate()` at entry; output is
  validated via `model_validate()` before returning.
- **Stateless w.r.t. other nodes**: does not import, call, or depend on any other node.
- **Individually testable**: can be run and validated in isolation without standing up
  any other part of the system.

---

## The Graph (current nodes and edges)

Six nodes are built: `ml_hyperparameter_tune_agent`, `result_interpretation_agent`,
`ml_literature_review`, `ml_model_proposal_agent`, `ml_model_implementor`,
`ml_code_validator_agent` (one directory each under `nodes/`).
`data_analysis_agent` is **planned — not built**: no node directory, no schema,
no protocol module exists for it yet.

```
Built:

ml_hyperparameter_tune_agent ─────────────────────────► result_interpretation_agent
result_interpretation_agent ──────────────────────────► ml_model_proposal_agent
result_interpretation_agent ──────────────────────────► ml_literature_review      (input assembled by the workflow; no protocol module)
ml_literature_review ─────────────────────────────────► ml_model_proposal_agent   (fan-in with the interpretation edge)
ml_model_proposal_agent ──────────────────────────────► ml_model_implementor
ml_model_implementor ─────────────────────────────────► ml_code_validator_agent
ml_code_validator_agent + ml_model_proposal_agent ────► ml_hyperparameter_tune_agent   (fan-in)

Planned — not built (data_analysis_agent does not exist yet):

data_analysis_agent ··································► result_interpretation_agent
data_analysis_agent ··································► ml_model_proposal_agent
```

Every built edge except interpretation → literature review has a protocol
module (table below); that one input is assembled directly by
`workflows/model_exploration.py:615-668` (`LiteratureReviewInput.model_validate`
over the parsed YAML plus workflow state). The cycle
`tune → interpret → propose → implement → validate → tune`
is the core research loop, traversed by an orchestrator.

---

## Protocols

Protocols live in `agent/schemas/protocols/`. Each is a plain Python function, named
and versioned, with fully typed arguments and return value. A protocol assembles a
complete input for a target node from one or more source outputs. Most protocols are
simple (one source), but fan-in protocols aggregate multiple sources when the target
node needs data from non-adjacent nodes in the graph.

### Implemented protocols

Naming convention: one file per primary directed edge, named `{source_code}_to_{target_code}.py`.
Each file contains `local_*` (in-memory) and `database_*` (NotImplementedError placeholder)
variants. Fan-in sources are additional function parameters beyond the primary source.

This table is the ONE authoritative inventory (issue #262); the package
docstring in `agent/schemas/protocols/__init__.py` and every node `.md` defer to
it, and `tests/unit/docs/test_node_docs_contract.py` fails when a node doc or
this file cites a protocol name that is not a module here. Six modules exist —
the earlier "five" omitted the literature-review edge. Every `local_*` has a
`database_*` sibling that raises `NotImplementedError`.

| protocol module (`agent/schemas/protocols/`) | producer → consumer | function | status | consumes → populates |
|---|---|---|---|---|
| `ml_model_tune_to_ml_result_interp.py` | `ml_hyperparameter_tune_agent` → `result_interpretation_agent` | `local_all_records` / `database_all_records` | built; unit-tested. **Not called by `workflows/model_exploration.py`**, which converts tuner output with the interpreter-owned `tuning_output_to_model_run_summary` (`:356`) instead | full `HyperparamTuningOutput` → all experiment records as `SummaryGroup`, model type |
| `ml_result_interp_to_ml_model_propose.py` | `result_interpretation_agent` → `ml_model_proposal_agent` | `local_full_context` / `database_full_context` | built; used by the workflow (`model_exploration.py:2543`) | full `InterpretationOutput` (+ external-agent channels, chain state) → `ProposalInput` (`interpretation_evidence`, existing model types, constraints) |
| `ml_literature_review_to_ml_model_propose.py` | `ml_literature_review` → `ml_model_proposal_agent` (fan-in with the interpretation edge) | `local_all_channels` / `database_all_channels` | built; used by the workflow (`model_exploration.py:576-587`, imported directly — not re-exported by `protocols/__init__.py`); unit-tested; **no integration test** | `LiteratureReviewOutput` → the four kwargs (`expert_context`, `agent_cards`, `mindset`, `vocab_seed`) spread into `local_full_context` |
| `ml_model_propose_to_ml_model_impl.py` | `ml_model_proposal_agent` → `ml_model_implementor` | `local_full_spec` / `database_full_spec` | built; used by the workflow (`model_exploration.py:2666`) | `ProposalOutput` → candidate id, model name, output type, description, math definition, baseline config, custom loss spec (`reference_code` is attached afterwards by the workflow, `:2696`) |
| `ml_model_impl_to_ml_model_valid.py` | `ml_model_implementor` → `ml_code_validator_agent` | `local_all_fields` / `database_all_fields` | built; used by the workflow (`model_exploration.py:2713`) | `ImplementorOutput` → file paths, config fields, model description, math definition, model I/O contract |
| `ml_model_valid_to_ml_model_tune.py` | `ml_code_validator_agent` + `ml_model_proposal_agent` (fan-in) → `ml_hyperparameter_tune_agent` | `local_validated_model` / `database_validated_model` | built; used by the workflow (`model_exploration.py:2866`); the ONLY protocol that carries a proposal into the tuner | `ValidatorOutput` + `ProposalOutput` → validated model type, expert advice (deviation notes prepended), baseline config, budgets, scope, health posture, LLM config, task composition |

Names that appear in older documents and were never defined anywhere —
`proposal_to_implementor_v1`, `proposal_to_hyperparam_seeded_v1`,
`interpretation_to_proposal_v1`, `implementor_to_validator_v1`,
`hyperparam_to_interpretation_full_v1`, `validator_to_hyperparam_v1` — were
placeholders from the original design sketch; the modules above are what
exists.

### Planned protocols (not built)

`data_analysis_agent` does not exist; no module under `agent/schemas/protocols/`
implements either edge below. They are kept as the intended design.

| Edge | Description |
|------|-------------|
| `data_analysis → result_interpretation` | dataset statistics, shift signals → `dataset_context` |
| `data_analysis → ml_model_proposal` | distribution properties → `data_constraints` |

---

## Orchestration

An orchestrator selects a path through the graph, applies protocols on each edge,
and calls `node.run()` at each step. It introduces control flow — sequential execution,
conditional branching, and loops by re-traversing cycles.

### Example: model exploration loop (Level 1 workflow)

```
1. ml_hyperparameter_tune_agent → initial tuning run (N rounds)
2. result_interpretation_agent  → identify bottlenecks        [ml_model_tune_to_ml_result_interp.py::local_all_records]
3. ml_model_proposal_agent      → propose new architecture    [ml_result_interp_to_ml_model_propose.py::local_full_context]
4. ml_model_implementor         → write model code + tests    [ml_model_propose_to_ml_model_impl.py::local_full_spec]
5. ml_code_validator_agent      → run tests, confirm valid    [ml_model_impl_to_ml_model_valid.py::local_all_fields]
6. ml_hyperparameter_tune_agent → tune the new model          [ml_model_valid_to_ml_model_tune.py::local_validated_model]
7. goto 2                       → repeat until convergence
```

(The bracketed names are the real `module::function` pairs under
`agent/schemas/protocols/`; the optional literature-review stage between 2 and
3 adds `ml_literature_review_to_ml_model_propose.py::local_all_channels`.)

### Recursive hierarchy

```
Human / Top-level CLI
└── research_campaign_orchestrator          ← Level 2 (orchestrator)
    ├── model_exploration_workflow          ← Level 1 (workflow)
    │   ├── ml_hyperparameter_tune_agent    ← Level 0
    │   ├── result_interpretation_agent     ← Level 0
    │   ├── ml_literature_review            ← Level 0 (optional stage)
    │   ├── ml_model_proposal_agent         ← Level 0
    │   ├── ml_model_implementor            ← Level 0
    │   └── ml_code_validator_agent         ← Level 0
    ├── data_analysis_agent                 ← Level 0 (planned — not built)
    └── result_interpretation_agent         ← Level 0 (final cross-model summary)
```

A human can substitute for any workflow or orchestrator at any level by manually
applying protocols and calling nodes via CLI — all six nodes expose one
(#303 gave `ml_literature_review` its `main()`; upstream records are read
from disk by the same naming convention the other CLIs use).

### Workflows vs. Orchestrators

There are two distinct levels of control in the system:

**Workflows** execute a pre-designed path through the graph. The sequence of nodes and
protocols is hardcoded — the workflow's only runtime decisions are when to stop and how
to handle errors. Workflows are deterministic and predictable. The first model proposal
demo is an example: it traverses `tune → interpret → propose → implement → validate →
tune` exactly once. Workflows are scripts, not agents.

**Orchestrators** are LLM-powered agents that choose their own path through the graph
at runtime. Given a goal (e.g. "achieve denoising score > X on dataset Y"), the
orchestrator inspects the available skills and protocols, decides which to invoke next,
observes the result, and adapts. This is the long-term target — a research agent that
autonomously navigates the full graph to pursue scientific hypotheses.

Workflows are the right starting point. They validate that all nodes, schemas, and
protocols work end-to-end before introducing LLM-driven path selection. Orchestrators
will be built on top of the same graph infrastructure — same nodes, same protocols,
same registry — with an LLM replacing the hardcoded traversal logic. An orchestrator
may invoke workflows as sub-skills when a known-good sequence is appropriate.

### Skill architecture (universal callable contract)

**High-level principle**: every callable in the system — whether it is an atomic tool
(training, inference, scoring), an LLM-powered agent (proposal, implementor), or an
orchestrator — conforms to a single **skill contract**: `{name, description,
input_schema, output_schema}`. This is the same uniform interface used by modern
tool-use APIs (OpenAI function calling, Anthropic tool use, MCP). From the caller's
perspective, there is no structural difference between invoking a deterministic
function and invoking a full agent — both are skills with typed inputs and outputs.

This matters for orchestrators: they see a flat catalogue of skills and select which
to invoke based on descriptions and schemas, without needing to know whether a skill
is a 3-line function, a full agent, or a workflow. The graph topology (which skills
can follow which) and the protocol registry (how to transform one skill's output into
the next skill's input) constrain the orchestrator's choices, but the invocation
mechanism is uniform.

**Tool-calling path**: the orchestrator will use **native LLM tool calling** (not
free-form JSON prompting) to select skills. Each skill's `SkillSpec` is converted to
an OpenAI-format tool definition and passed to `LLMBridge.tool_call()`. The LLM
outputs a structured tool call (skill name + arguments), and the orchestrator dispatches
it. This is structurally more reliable than asking the LLM to output JSON and parsing
it — the model is constrained to emit valid calls matching the declared schemas.
See "TODO: Skill Architecture Refactor" for the implementation roadmap.

**Current naming conflict and planned resolution**:
The directory `agent/skills/` currently holds a specific subset of atomic tools used
internally by the tuning agent (training, inference, scoring, config check, resource
evaluation). These are skills in the universal sense, but the directory name suggests
they are the *only* skills. The planned resolution (deferred until after the first
demo):

1. Rename `agent/skills/` → `agent/tools/` to clarify these are atomic,
   non-LLM operations used internally by agents.
2. Reserve "skill" for the universal interface contract that all callables satisfy.
3. Introduce a **skill registry** that indexes all available skills (tools, agents,
   workflows, orchestrators) with their names, descriptions, and schemas. Workflows
   do not need this registry (they hardcode the path), but orchestrators will query
   it to discover what they can invoke.

The hierarchy is:

```
Orchestrator  (LLM-powered, goal-driven, selects skills autonomously)
  └── Workflows  (pre-designed paths through the graph, deterministic)
       └── Agents  (LLM-powered, run(input)->output, may use tools internally)
            └── Tools  (atomic operations: training, inference, scoring)
```

All three levels satisfy the same skill contract. The hierarchy describes *internal
composition*, not the external interface.

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
| `ml_code_validator_agent` | 7 checks: plugin load, pytest, description, config fields, instantiation, gradient flow, LLM code review with runtime diagnosis | no | no | yes |
| `ml_literature_review` | Resolves root papers, searches Semantic Scholar around the current bottlenecks, synthesises findings as soft priors (optional stage) | no | no | yes |
| `data_analysis_agent` (**planned — not built**) | Profiles dataset properties, detects distribution shifts | no | no | yes |

Six of these are built; `data_analysis_agent` is the intended data-analysis
advisor and does not exist yet.

---

## Plugin System

Agent-generated models (`ml_model_implementor` outputs) are written into
per-attempt workspace directories and, once validated, *promoted* into the
resolved **generated-capability library**
(`{workspace}/generated_library` for supported workflow and standalone-node
entry points; `core/generated_library.py`) under `models/` as `.py` files. Each
plugin must define:

- `PLUGIN_MODEL_TYPE: str` — unique model type key
- `PLUGIN_CONFIG_CLASS: BaseModel` — Pydantic config schema
- `PLUGIN_MODEL_CLASS: nn.Module` — model class with forward contract `[B, T] int → [B, 256, T] float`
- `description.md` — plain-English + math description alongside the plugin file (at
  `{library}/models/{model_type}/description.md`); required by the interpretation agent
  to include the model in cross-model analysis

`ml_models/plugin_loader.py` scans the resolved plugin directories at import
time (run-scoped binding / `SIDERIUS_PLUGIN_DIRS` / the library `models/`
dir, with the checkout's `agent_generated/models/` as a read-only legacy
fallback) and extends `MODEL_REGISTRY` and `PLUGIN_CONFIG_REGISTRY`
in-place. The core codebase — and the repository checkout — is never
modified by agents.

---

## Data Paths (current)

Roots are machine-specific and resolved by the config layer
(`tidmad_data_config.yaml` → `execute_tools/data_paths.py`; PR #125/#127
made scoring reference data committed + package-relative, so a new server
needs config edits only). lilab example below; on the H100 box the roots
are `/workspace/DATA/TIDMAD_DATA/` and `/workspace/DATA/SIDERIUS_DATA/`.

```
/home/klz/Data/TIDMAD/                          # raw input data (read-only)
/home/klz/Data/SIDEREIS_DATA/
├── {model}/
│   ├── baseline/                               # baseline run (shared across run_names)
│   └── {run_name}/agent/                       # agent run outputs
│       ├── run_config_{run_name}.json          # startup config (includes file_index)
│       ├── summary_{run_name}.json             # DERIVED view: latest-wins-by-exp_id projection of records.jsonl
│       ├── run_output_{run_name}.json          # validated HyperparamTuningOutput (published atomically)
│       ├── records/{run_name}/                 # per-experiment detail JSONs
│       │   └── records.jsonl                   # CANONICAL append-only record history (S2 / U5)
│       ├── configs/                            # model/train/loss configs per exp_id
│       ├── cached_models/                      # trained model checkpoints (.pth)
│       ├── run_invariants_lock.json            # immutable run invariants (scope + gate policy)
│       └── health_checks_effective.yaml        # materialized HealthGate config (sha lock-pinned)
└── raw_baseline/
    └── raw_baseline_score_file_{index:04d}.json  # undenoised reference scores
```

---

## Dataset Profile (profile-driven data path — shipped 2026-08, PR 02a)

The production data path resolves its dataset semantics from a **resolved
Dataset Profile** rather than module-level constants.
`DatasetProfile` (`execute_tools/dataset_config.py`) composes three
declarations:

```text
dataset   DatasetConfig — file topology (patterns, count, index space),
          sample geometry (psd_segment_length, segments_per_file) and the
          sample-shape legality rule
channels  ChannelIdentity — which in-file channel is the model INPUT and
          which is the TRUTH
encoding  ValueEncoding — storage/compute dtype, value offset, class count
```

It **composes** `DatasetConfig` rather than extending it, so the shipped
`TIDMAD` object and its `model_dump()` are unchanged and the Step-00
golden keeps pinning the object production reads.

**Resolution has two regimes**, and confusing them is the failure the
design guards against:

| Situation | Behaviour |
|---|---|
| an explicit profile path is supplied but is missing / unreadable / not JSON / schema-invalid | **FAIL CLOSED**, with a diagnostic naming the path. Never falls back to the singleton — a fallback would run a bound task against TIDMAD's topology and produce plausible, wrong numbers |
| a caller omits the transport entirely | **Regime-A compatibility adapter** — resolve the shipped TIDMAD profile exactly, preserving pre-profile behaviour |

`TIDMAD_PROFILE` is that adapter. It is **not** a universal framework
default; every value in it is a property of the TIDMAD dataset.

**Transport across the subprocess boundary** reuses the existing
config-file + argv-flag pattern (`--model_cfg`, `--train_cfg`,
`--loss_cfg`). `TidmadSandbox._write_dataset_profile_config(exp_id)`
writes `dataset_profile_{exp_id}.json` into the run's `configs/` directory
and all three entry points receive its path:

```text
execute_tools/train_engine_sandbox.py   --dataset_profile_json PATH
execute_tools/inference_single.py       --dataset_profile_json PATH
execute_tools/denoising_score_single.py --dataset_profile_json PATH
```

Omitting the flag is legal and means Regime-A.

**In-process consumers** take the profile as an argument. Two consume it at
import time — `agent/schemas/score_table.py`'s row/index bounds and
`nodes/scoring_reference.py`'s file-index tuple — and use
`resolve_dataset_profile()`, with `bind_dataset_profile()` (a scoped
`ContextVar`) for tests and future task binding.

**Not owned here**: SampleSet/selection semantics, systematic groups, and
the Deliverable Contract (denoised naming/layout/attrs). The raw
validation filename is Step-02 input topology and comes from the profile;
every denoised name still comes from `denoised_filename_fn`.

---

## Evaluation Metric Interface (shipped 2026-08, Step 06)

Production scoring invokes the frozen TIDMAD scorer **through a generic
metric handle** (`execute_tools/evaluation_metric.py`). The interface is
extracted FROM the TIDMAD instance and extends the `metric_id:
"tidmad_denoising_score"` precedent `per_file_best` already emitted; the
frozen formula (`scoring_utils.score_vector`, `_LOG_BASE`, `s_max`,
anchor normalisation, grand-mean) is referenced, never re-implemented, and
its 2-tuple return is untouched.

```text
MetricSpec           id · direction ("higher" | "lower") · aggregation id ·
                     transform (+params) · references · scoreability
ScoreabilityContract abstract, EXECUTABLE: check({input_identity: path}) ->
                     ScoreabilityVerdict (structured failures, never an h5py
                     traceback). Declared PER METRIC INSTANCE against the
                     producer-side DeliverableSpec — there is no universal
                     completeness/channel/shape schema.
EvaluationMetric     the handle: evaluate(deliverables, **kwargs) runs the
                     contract FIRST, then the instance's arithmetic ->
                     MetricResult | NotScoreableResult
MetricResult         metric_id · direction · scalar (mandatory) · optional
                     per_sample evidence · references_used
```

**Instance #1 — TIDMAD** is DERIVED under Regime A with no declaration
(`derive_tidmad_metric(profile, deliverable_spec)`): identity
`tidmad_denoising_score`, direction `higher`, aggregation = `score_vector`,
transform `log` (base 5.27, imported — one contract, four expressions),
references `anchor_map` / `raw_baseline` / `ground_truth`, and a
`TidmadScoreabilityContract` requiring exactly what the live scorer reads
of the deliverable: file-level completeness, the input channel dataset
(`ch=1`), the `voltage_range_mV` / `sampling_frequency` attrs, the declared
storage dtype. Task-level metric DECLARATION for other tasks is Step 12
(an additive block in the existing task configuration — no new hierarchy).

**Ownership split** (design §4, operator-confirmed): `DeliverableSpec`
(Step 05c) owns producer-side REPRESENTATION — naming, cleanup identity,
channel-group identity, layout, storage dtype/offset. The metric owns
evaluation-side ACCEPTANCE — what THIS metric requires of that artifact —
and REFERENCES the deliverable spec (channel group and dtype are read from
it). `_is_complete_trial_output` stays a crash-resume REUSE guard; it is
not the scoreability mechanism.

**Two routes, one handle.** The tuner binds `run_metric` once at run scope
(beside `run_profile`, `run_model_io`, `run_deliverable_spec`) and scores
through `TidmadSandbox.evaluate_metric(run_metric, …)` — DataScope
validation first (unchanged), then scoreability, then `score_vector` with
its previous keyword arguments; a refused deliverable raises the typed
`NotScoreableError` (carrying the structured result) into the tuner's
scoring failure path (`error_scoring`, `failure_type="not_scoreable"`).
`TidmadSandbox.score_vector` remains as the legacy 2-tuple wrapper. The
scoring subprocess (`execute_tools/denoising_score_single.py`) RECONSTRUCTS
the same instance from `--dataset_profile_json` (05c Option A — no new argv),
names the deliverable through the deliverable spec, evaluates through the
handle, and on refusal exits 1 with the structured payload on stderr and in
`--output_json` (`not_scoreable`); the parent's classifier is unchanged.
The two routes are pinned equal on one deliverable (Checkpoint 0 / C).

**Record payload (additive).** `ExperimentRecord.metric_result`
(`MetricResult`, `per_sample` stored as a pointer to `file_vector`) and
`ExperimentRecord.metric_refusal` (`NotScoreableResult`) sit beside the
untouched `denoising_score` / `file_vector` / `score_table`; historical
records validate unchanged; on a `success` record the payload is validated
to agree with the frozen fields (the `failed_mode_collapse` penalty is the
documented exception).

**Losses are not metrics.** Train/validation loss have no deliverable, no
reference and no task-independent direction (roadmap §20.2); surfacing losses
is Step 07's `TrainingHistory` / `TrainingDiagnosis`.

**Step 12 / PR-12a C5 (D16) changed HOW that is enforced.** Step 06 enforced
it LEXICALLY — `_is_loss_shaped` refused any identity whose *name* looked
like a loss. That rule was wrong in both directions: it refused a legitimate
declared metric called `log_loss` (Oxford-IIIT Pet's, deliberately named to
force this), and it would have accepted a genuine training objective under
any other name. **`MetricSpec.id` is now an OPAQUE identifier**: meaning and
direction come from the declaration, and the boundary is enforced where the
real distinction lives — the metric types still forbid extra keys and carry
no loss field, and a loss has no deliverable to score. Naming is validated
for hygiene only, never for semantics.

**Not reached by Step 06** (enumerated and asserted, D1 / Step 07a debt):
incumbent/best selection in the tuner, `workflows/model_exploration.py`,
`core/resume.py`, `per_file_best._row_beats`, dashboard ordering — they
still encode higher-is-better literally.

---

## Data Scoping (partial-file runs — shipped 2026-07)

`DataScope` (`execute_tools/dataset_config.py`) restricts a run to a
validation-file subset (`--data_scope 4-9` or `4,5,6,7,8,9`). Enforcement
is layered and never prompt-based:

1. **Constructive** — `build_sample_set(scope=…)` only produces in-scope
   SampleSets; partial scopes are snapshot-only (operator config errors at
   startup; LLM plans normalize with recorded provenance). The scope is
   resolved against the run's **Dataset Profile**, which the caller
   supplies explicitly: `build_sample_set(scope=…, profile=…)`
   (Step-02b). The tuner resolves that profile once per round and passes
   it to both the training and validation construction sites, so a run
   bound to a non-default topology cannot silently select against the
   ambient one. `profile=None` keeps ambient resolution (Regime-A) for
   callers that have no run-bound profile — `scripts/run_comparison.py`
   and the proposer pre-flight.
2. **Boundary** — `validate_sample_set` runs at the sandbox before ALL
   file I/O (train / inference / `score_vector`); a violation terminates
   the run, non-retryable.
3. **Direct access** — HealthGate monitored files (`--health_gate_files`)
   must be ⊆ scope; the effective config is materialized per workspace.

**Run-invariants lock** (`core/run_invariants.py`,
`{workspace}/run_invariants_lock.json`): resolved scope +
`health_gate_enabled` + effective-config sha256 are immutable per
workspace; every resume/seed/reuse entry point validates against it (and
legacy history is stamp-checked before a lock-less workspace is ever
locked). **Aggregate scalars are comparable only within one scope**;
cross-scope analysis uses per-file vectors. Default (no scope) is
behaviorally identical to pre-feature runs. Full design:
`docs/design/enable_partial_file_list.md`. Operator surface:
[`docs/reference/entrypoints.md`](reference/entrypoints.md).

---

## Testing Strategy

Agent tests have five categories. Unit tests and pseudo-full-loop tests run on every
commit (no external resources needed). The three real-API integration tiers require
API keys and/or GPU and are gated by `pytest.mark.real_run` + the `--real-api-call`
flag — they never run in CI. See [`tests/pseudo_data/README.md`](../tests/pseudo_data/README.md)
for the dual-mode fixtures.

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

**Location**: `tests/integration/workflows/test_{workflow_name}.py`

**Rule**: Test only the critical paths, not every combination. Combinatorial coverage
belongs in unit tests. A Tier 3 test that takes more than ~10 minutes is doing too much
— break it into smaller Tier 2 tests instead. One representative config per loop.

---

### Pseudo-full-loop tests (dual-mode)

**What**: Run the same integration test (Tier 1, 2, or 3) in **two modes** selected by
a fixture:

- **Pseudo mode (default)**: `RecordingLLMBridge` returns predefined LLM responses
  from `tests/pseudo_data/api_call_outputs/`. `RecordingSandbox` returns predefined
  subprocess results from `tests/pseudo_data/train_outputs/`. No real API calls, no
  real training, no GPU. Runs in milliseconds. The test asserts on prompt content,
  record structure, and call sequence — everything except real LLM behavior.
- **Real mode** (`--real-api-call`): real `LLMBridge` + real `TidmadSandbox`. Same
  assertions plus whatever the real API returns. Requires API keys + GPU. Slow.

**Markers**:
- `@pytest.mark.dual_mode`: the test supports both modes. Default = pseudo mode.
  Switches to real mode when `--real-api-call` is passed.
- `@pytest.mark.real_run`: the test only works in real mode (no pseudo equivalent).
  Skipped by default; requires both `-m real_run` AND `--real-api-call`.

**Predefined data**: `tests/pseudo_data/` holds JSON files shaped exactly like the
real API outputs. These are the test's "expected inputs" from external systems.
**Schema fidelity is the contributor's responsibility**: when a schema changes, the
corresponding pseudo data must change in the same commit. See
`tests/pseudo_data/README.md` for the invariant.

**Location**: dual-mode tests live alongside real-only tests in the same files under
`tests/integration/`. They are distinguished by the `dual_mode` marker.

**Rule**: new integration tests should be dual-mode by default. Real-only tests are
reserved for cases where no predefined response can meaningfully validate the behavior.

See [`tests/pseudo_data/README.md`](../tests/pseudo_data/README.md) for the fixture
format and how to add a predefined response.

---

### Summary

| Category | Scope | LLM | GPU | Location | When to run |
|----------|-------|-----|-----|----------|-------------|
| Unit | Single node, mocked LLM | mock | no | `tests/unit/` | Every commit |
| Pseudo-full-loop | Full orchestration, predefined responses | predefined | no | `tests/integration/` (`dual_mode`) | Every commit |
| Integration Tier 1 | Single node, real API | real | depends | `tests/integration/nodes/` (`real_run`) | On demand |
| Integration Tier 2 | One edge (source → target) | real | depends | `tests/integration/protocols/` (`real_run`) | On demand |
| Integration Tier 3 | Critical multi-hop loop | real | yes | `tests/integration/workflows/` (`real_run`) | Before releases |

---

## Design Direction: Gradual Genericization (Multi-Dataset / Multi-Task / Multi-Metric)

**Operator decision (2026-07-27)** — supersedes the previous "do not design this
abstraction until a second dataset exists" stance in this section.

SIDERIUS is being reshaped from a TIDMAD-only repo into a generic framework that
accommodates different datasets, tasks, and metrics. The current execution layer
(`execute_tools/`, `core/sandbox_executor.py`, `ml_models/`) is tightly coupled to
TIDMAD (HDF5 format, ADC 0–255 values, `abra_*` filename templates, denoising score
metric, `file_index` split scheme); the agent layer above it is already largely
dataset-agnostic.

**Mechanism — in-passing refactoring, never a big-bang**: when a PR touches a
module, that PR also refactors the touched module toward the generic seams (as its
own commit; skippable for urgent fixes). There is no dedicated mega-refactor PR;
the reshaping rides on the normal development ladder.

The target shape is unchanged from the original TODO:

- TIDMAD-specific code migrates toward `backends/tidmad/` (or equivalent seam)
- A thin dataset contract (`file_index → segments`, resolvable to readable files)
  that the execution layer calls
- Each dataset implements its own backend (data loading, scoring metric, split
  scheme); agent nodes and schemas remain unchanged

Guardrails (full version: `docs/design/v19_priorities.md` §1.3, canonical once the
genericity-contract doc exists):

1. Seams are defined ONCE in a genericity-contract doc (extending
   `configs/task_config.yaml`, the declared porting entry point) — in-passing
   refactors converge to those seams and never invent ad-hoc abstractions.
2. A coupling ledger tracks TIDMAD residue (decoupled vs remaining) as the
   progress meter.
3. Every genericized seam gets a contract test against a minimal synthetic
   second-dataset fixture — the fixture plays the "second concrete use case"
   role the old stance waited for.
4. The frozen TIDMAD metric instance (score formula, paper comparability) stays
   byte-identical; metric pluggability means new metrics plug in beside it.
5. **Rev 5 / 5.1 (2026-08-15, roadmap §22 — architecture accepted, final freeze after the dataset selection)**: computation ×
   lifecycle role × cadence are orthogonal (a name never makes a computation a
   loss or a metric); every fully supported task requires one training
   objective, per-epoch train- and validation-objective histories, and one
   golden evaluation metric; persistence never implies prompt visibility;
   genericity is validated against three PERSISTENT tracks — TIDMAD (control),
   a fixed image/classification task and a fixed spatiotemporal/regression
   task — each at the highest honest maturity level, with a required Gate's
   corpus covering every executable track; secondary metrics are first-class
   downstream evidence but never the incumbent objective; agent-facing
   rendering is owned by consumer (Step 07 tuner planner/reflector, Step 09
   interpreter/proposer). The two contrast tracks are SELECTED (2026-08-15):
   Track B = Oxford-IIIT Pet 37-way RGB breed classification ([3,144,144],
   CE → accuracy↑), Track C = DAVIS 2017 RGB 8→4 future-frame prediction
   ([3,8,128,224] → [3,4,128,224], MAE → MSE↓); D14 (executable data path)
   is a dedicated milestone right after Step 07 (roadmap §22.9a, §22.11a).
   Each track is also a user-facing PERSISTENT EXAMPLE PACK
   (`examples/tidmad/`, `examples/oxford_iiit_pet/`,
   `examples/davis_future_prediction/`) that grows with track maturity and
   consumes — never duplicates — the module-owned contracts (roadmap §22.23).

---

## TODO: Skill Architecture Refactor

The long-term goal is an LLM-powered orchestrator that sees every node, tool, and workflow
as a callable **skill** and uses **native LLM tool calling** (not free-form JSON prompting)
to select and invoke them. This is more reliable than prompting the LLM and parsing its
output — the model is structurally constrained to emit valid tool calls with typed arguments.

The roadmap is split into layers. Each layer is independently useful and testable.
Do not skip ahead — each layer depends on the one before it.

### Layer 0: Unified LLM transport (DONE)

`agent/llm_bridge.py` uses a single `openai.OpenAI` client for all providers (OpenAI,
Gemini, any OpenAI-compatible endpoint). This was completed in the Phase 1 refactor.

### Layer 1: Tool-calling foundation (DONE)

Two isolated pieces that prepare for the orchestrator without touching existing nodes:

1. **`LLMBridge.tool_call(system_prompt, user_prompt, tools) → ToolCallResult`**
   (`agent/llm_bridge.py`) — calls `chat.completions.create` with `tools=...` and
   `tool_choice="auto"`. Returns a `ToolCallResult` (frozen dataclass) with:
   - `name: str` — the tool the LLM chose to invoke
   - `arguments: dict` — parsed from the JSON string (ready for `model_validate()`)
   - `call_id: str` — API-level ID for multi-turn tool-result messages
   Raises `ValueError` if the model responds with text instead of a tool call.

2. **`SkillSpec`** (`agent/schemas/skill_spec.py`) — Pydantic model wrapping
   `{name, description, input_schema, output_schema}`. Holds the actual Pydantic
   **classes** (not pre-generated JSON), so the same class serves for:
   - Generating OpenAI tool definitions: `spec.to_openai_tool()` calls
     `input_schema.model_json_schema()` on the fly
   - Validating tool-call arguments: `spec.input_schema.model_validate(result.arguments)`
   - Validating node output: `spec.output_schema.model_validate(output)`

Full `LLMBridge` public interface after Layer 0 + 1:
- `generate(system_prompt, user_prompt) → dict` — JSON mode
- `generate_text(system_prompt, user_prompt) → str` — plain text
- `tool_call(system_prompt, user_prompt, tools) → ToolCallResult` — native tool calling
- `list_models() → list[str]` — available model IDs

These pieces are the **minimum bridge** between the current node-based architecture
and the future orchestrator. They do not change how existing nodes or workflows operate.

### Layer 2: Skill registry (LATER)

A module that discovers and indexes all available skills from `nodes/`, `agent/tools/`,
`workflows/`, and `orchestrators/`. It collects their `SkillSpec` definitions and
provides query methods (e.g. "list all skills that don't require GPU").

Prerequisite: Layer 1 is done. Next step is to have at least 2-3 nodes expose a
`SkillSpec`, then build the registry around them.

### Layer 3: Orchestrator (LATER)

An LLM-powered agent that receives a goal, queries the skill registry for available
`SkillSpec`s, converts them to OpenAI tool definitions, and uses `LLMBridge.tool_call()`
to select which skill to invoke next. It applies protocols between skills, observes
results, and iterates until the goal is met or a budget is exhausted.

Prerequisite: Layer 2 (registry) and a working end-to-end workflow to validate against.

### Housekeeping (deferred)

- **Rename `agent/skills/` → `agent/tools/`** — update all imports and references.
  These are atomic, non-LLM operations (training, inference, scoring, config check,
  resource evaluation) used internally by agents. "Skill" is reserved for the universal
  contract.
- **Add metadata to `SkillSpec`** — `requires_gpu`, `requires_llm`, `estimated_cost`,
  etc. Not needed until the orchestrator is making cost-aware decisions.

---

## TODO: Structured Node Failure Outputs

Currently, when a node fails (e.g. `ml_model_implementor` exhausts its self-correction
retries), it raises a Python exception. The workflow catches this in a `try/except` and
treats it as a failed attempt. This works but has limitations:

- The error message is unstructured (a string extracted from the exception)
- The workflow cannot distinguish between different failure modes
- Downstream retry logic (proposal agent's `previous_failures`) receives a raw error
  string rather than structured diagnostic data

**Long-term solution**: each node's output schema should support a failure mode. For
example, `ImplementorOutput` could include:

```python
class ImplementorOutput(BaseModel):
    status: Literal["success", "failed"] = "success"
    error_message: Optional[str] = None
    error_category: Optional[str] = None  # e.g. "syntax_error", "shape_mismatch"
    # ... existing fields (only populated when status="success")
```

This mirrors how `ValidatorOutput` already works (`passed: bool` + `error_message`).
With structured failure outputs:
- The workflow never needs `try/except` around node calls — it checks `output.status`
- The proposal agent receives categorised failure data, not raw tracebacks
- Failure modes are part of the schema contract, not implicit exceptions

**When to implement**: after the first demo workflow runs successfully end-to-end.
Start with `ImplementorOutput`, then consider `ProposalOutput` (for cases like empty
`model_name` or duplicate name detection).


## Future Evolution: Toward a Global Science Mesh

To achieve the vision of weaving a global network of scientific tools across domains (Physics, Biology, Chemistry), the architecture will evolve from a local graph to a federated, responsive mesh.

### 10. Three-Layer Isolation for Scalability
To prevent dependency bloat and allow massive-scale tool discovery, the system enforces a strict isolation between a node's definition and its execution:

- **Schema Layer (Pure Logic)**: Lightweight Pydantic definitions only. This layer is indexed by orchestrators for path selection and LLM native tool calling, requiring zero heavy dependencies.
- **Protocol Layer (Mapping)**: Standalone data transformation logic. It mediates between nodes without knowing their internal implementation.
- **Runtime Layer (Heavy Compute)**: The actual execution environment (Docker, Remote gRPC, or GPU-bound Python). This layer is only initialized/activated when a node is explicitly triggered.

### 11. Federated Graph Discovery
SIDERIUS will support "Graphs of Graphs." A domain-specific graph (e.g., a Chemistry Synthesis Graph) can be registered as a single **Node** within a higher-level research graph.
- **Recursive Discovery**: Orchestrators can query a global **Skill Registry** to "hook" remote nodes into the local workflow on-the-fly.
- **Unit-Aware Protocols**: Protocols will move beyond basic type-checking to include **Dimensional Analysis**. The system will automatically detect unit mismatches (e.g., keV vs. Joule) and insert conversion units into the edge.

### 12. From Edge-Protocols to Ingress-Contracts (Reactive Fan-in)
To handle complex data dependencies where a node requires inputs from multiple asynchronous sources, the "Edge-Protocol" model evolves into an **Ingress Controller**:

- **Input Buffering**: Each node maintains a persistent `PendingInputBuffer`.
- **Completeness Contract**: Instead of being "called" by an upstream node, a node is **activated** when its Ingress Controller determines that the collective inputs (from one or many sources) satisfy its schema.
- **Aggregation Protocols**: The protocol logic shifts from `A → B` to `f({A, C, ...}) → B`, allowing for sophisticated data fusion, timestamp alignment, and conflict resolution at the target node's doorstep.

### 13. LLM-Native "Intent" Mapping
The system will natively map the **Schema Layer** to LLM Tool-Calling formats (OpenAI/Gemini function specs).
- **Decoupled Invocation**: The LLM expresses an "Intent" based on the Schema. The Orchestrator resolves this Intent by selecting the appropriate Protocol and dispatching the task to the correct Runtime (Local, Container, or Remote).

---

## Node Directory Structure (refactor DONE)

Nodes are one-directory-per-node (landed after this section was first
written; the layout differs slightly from the original plan — the module
keeps the node's own name instead of `agent.py`):

```
nodes/
├── ml_hyperparameter_tune_agent/
│   ├── __init__.py                        (re-exports the agent class)
│   ├── ml_hyperparameter_tune_agent.py    (the run() logic)
│   └── ml_hyperparameter_tune_agent.md    (node documentation)
├── result_interpretation_agent/
├── ml_model_proposal_agent/
├── ml_model_implementor/
├── ml_code_validator_agent/
├── ml_literature_review/
└── (shared helpers at package root: agent_data_stream.py,
     interpretation_helpers.py, proposal_helpers.py, scoring_reference.py
     — candidates for relocation, see the repo audit 2026-07-23)
```

Convention for new nodes: `nodes/{node_name}/{node_name}.py` with
`__init__.py` re-exporting the class (imports stay
`from nodes.{node_name} import …`), documentation co-located in the same
directory.
