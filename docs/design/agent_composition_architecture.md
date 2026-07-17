# SIDERIUS Agent Composition Architecture

**Authoritative reference for the three-layer architecture vision, current state, and roadmap.**

This document is a design spec, not a code-level reference. For the foundational principles (graph topology, fan-in protocols, transport-agnostic schemas) see `docs/architecture.md` — that doc is the source of truth for those principles. This doc layers the **three-layer audit** + **roadmap** on top.

Cross-references throughout cite concrete file paths from the codebase audit on 2026-06-29.

---

## 1. Vision

### The core idea

Every callable in SIDERIUS — agents, skills, orchestrators, even external services — should be **composable**: described by the same typed contract, connected by the same protocol pattern, executable by any orchestrator (human-defined DAG, Run Monitor, LLM-driven, hybrid).

A **node** is a stateless unit with a typed input schema, a typed output schema, and a self-description. A **protocol** is a typed function that maps one node's output into another node's input. An **orchestrator** is any agent — human or LLM — that selects which nodes to run in what order, supplying outputs to protocols and consuming the results.

When that contract is enforced consistently across the codebase, the same set of nodes can be re-composed into different workflows without changing the nodes themselves. The substrate stays fixed; the strategy varies.

### Why this matters

Every significant problem in v15/v16 required human post-hoc intervention:

| Incident | Required for detection | Required for response |
|---|---|---|
| v15 ghost scores (14/22 byte-identical formal scores) | Cross-iteration memory of file_vector outputs | Bump `--max_epochs` / `--train_portion` operator-side |
| v15 arch chain time-gated 17/20 iters | Cross-iteration cost profile per architecture family | Insert advice to constrain segmentation_size operator-side |
| v16 anchor strategy producing 7.25 trial that triggered bypass-time-budget | Strategy-aware understanding of score commensurability | Suppress bypass gate operator-side |
| v15 mode collapse on under-trained models | Output-diversity inspection across files | Operator manually inspects file_vectors and decides |

None of these were detectable by any single iteration. None could be fixed inside any single node. **An observer agent with cross-iteration memory and orchestrator-level intervention rights would have caught all of them.** That observer is the Run Monitor (issue #100), and it cannot exist without the three-layer substrate this document defines.

### The end state

The same set of nodes, composed by **multiple orchestrator types**:

- **Human-defined DAG** (today): `workflows/model_exploration.py` calls each agent in a hardcoded sequence.
- **Adaptive monitor** (near-term, issue #100): Run Monitor observes cross-iteration patterns and intervenes at control points (skip_formal gate, bypass-time-budget gate, max_epochs adjustment).
- **LLM orchestrator** (future): an LLM reads the node registry, sees what's available, composes a sequence for a given goal, runs it under operator approval.
- **Hybrid** (long-term): an LLM orchestrator proposes; a Run Monitor adapts; a human can intervene at any control point.

The architecture must support all four without re-implementing the nodes. That is the design objective.

---

## 2. Three-Layer Architecture

### Layer 1: Node Registry

**What a node is.** A stateless unit with a `def run(input: NodeInput) → NodeOutput` method, where `NodeInput` / `NodeOutput` are Pydantic `BaseModel` subclasses. The contract is the schema; the implementation is opaque.

**Self-description: SkillSpec.** `agent/schemas/skill_spec.py` already defines a `SkillSpec` model:

```python
class SkillSpec(BaseModel):
    name: str            # unique identifier (e.g. "tune_ml_hyperparam")
    description: str     # shown to LLM in tool-calling mode
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    def to_openai_tool(self) -> dict[str, Any]: ...  # OpenAI function-calling spec
```

The `to_openai_tool()` method auto-generates a JSON Schema from `input_schema.model_json_schema()`. Any LLM with tool-calling support can be handed a list of `SkillSpec.to_openai_tool()` dicts and call them by name.

**NodeRegistry: how nodes register and become discoverable.** A `NODE_REGISTRY: dict[str, SkillSpec]` populated at import time (via decorator or `__init_subclass__`). Any orchestrator — including an LLM — can enumerate registered nodes, look up their schemas, and dispatch by name.

**Current state.** `SkillSpec` exists and is well-designed. Zero production nodes adopt it. `agent/skills/__init__.py` is **empty** (no exports, no registry). The 6 main agents (`MLLiteratureReviewAgent`, `MLModelProposalAgent`, `MLModelImplementor`, `MLCodeValidatorAgent`, `HyperparamTuningAgent`, `ResultInterpretationAgent`) only have `def run(self, inp) → Output` methods — no `spec` class attribute, no `name` field exposed at the class level.

**Gap.** The infrastructure exists but adoption is zero. Closing this requires: (1) add `spec: SkillSpec` class-attribute to each node, (2) populate `agent/skills/__init__.py` with re-exports, (3) build the `NODE_REGISTRY` with register-on-import. Estimated at 1-2 days.

### Layer 2: Protocol Layer (BUILT)

**What a protocol is.** A typed, validated data transformation between two nodes. From `docs/architecture.md`:

> A protocol is a named, typed function that assembles a fully populated input schema for a target node from one or more upstream node outputs. It is the only place where field mapping between nodes happens.

A protocol's function signature is the public contract:

```python
def local_full_spec(output: ProposalOutput, storage: StorageConfig) -> ImplementorInput:
    """Map ProposalOutput → ImplementorInput in-memory."""
    return ImplementorInput(
        model_name=output.model_name,
        model_description=output.model_description,
        mathematical_definition=output.mathematical_definition,
        baseline_config=output.baseline_config,
        custom_loss_spec=output.custom_loss_spec,
        storage=storage,
    )
```

**Six existing protocols** in `agent/schemas/protocols/`, one per directed edge of the current 6-node graph:

| Protocol file | Direction |
|---|---|
| `ml_result_interp_to_ml_model_propose.py` | interpretation → proposer |
| `ml_literature_review_to_ml_model_propose.py` | lit-review → proposer (fan-in with interp) |
| `ml_model_propose_to_ml_model_impl.py` | proposer → implementor |
| `ml_model_impl_to_ml_model_valid.py` | implementor → validator |
| `ml_model_valid_to_ml_model_tune.py` | validator → tuner |
| `ml_model_tune_to_ml_result_interp.py` | tuner → interpretation (cycle close) |

**Why this is the architectural success story.** Layer 2 is **complete and used in production**:

- Every edge in the current DAG has a named protocol function.
- Each protocol has `local_*` (in-process) and `database_*` (transport stub) variants.
- All 6 protocols have unit tests in `tests/unit/agent/protocols/`.
- All 6 protocols have integration tests in `tests/integration/protocols/`.
- The workflow at `workflows/model_exploration.py` imports and calls these by name — no field-mapping happens elsewhere.

**Protocol conventions.**
- File: `agent/schemas/protocols/{source_node_short}_to_{target_node_short}.py`
- Functions: `{transport}_{data_scope}` — e.g. `local_full_spec`, `database_validated_model`. Always add a `database_*` stub raising `NotImplementedError` alongside every `local_*` so future distributed execution has a designated extension point.
- One protocol file per directed edge. A reverse edge gets its own file.

**Adding a new protocol.** Mechanical pattern: create a new file under `agent/schemas/protocols/`, define `local_*` (and `database_*` stub), unit-test the field mapping, integration-test the round trip. No changes to nodes — protocols are independent of node implementation.

### Layer 3: Orchestrator

**What an orchestrator is.** An agent that decides which nodes to run in what order, supplies outputs to protocols, and consumes the results. Per `docs/architecture.md` §5, orchestrators are themselves nodes — they have `run(input) → output` interfaces and can be composed into higher-level orchestrators recursively.

The orchestrator has **three** distinct responsibilities (from `docs/architecture.md` §6):
1. **Select a path** through the node graph.
2. **Choose the protocol** to apply on each edge (multiple protocols may exist on an edge).
3. **Supply fan-in outputs** when a protocol aggregates multiple sources.

**Three orchestrator types.**

#### 3a. Human-defined DAG (current)

Today's orchestrator is `workflows/model_exploration.py` — a **2608-line file** that:

- Hardcodes imports of the 6 agent classes at top (lines 87, 92-94, 96).
- Directly instantiates each agent (5 call sites: 1773, 1808, 1969, 2069, 2246).
- Calls `agent.run(input)` in fixed sequence — interpret → lit-review (gated) → propose → impl → validate → tune.
- Knows every node's input fields by name (lines 1942-1957 set ~15 attributes on `propose_input` directly).
- Is also responsible for retry loops, attempt directories, registry promotion, vocab updates, lit-review wiring, gate exhaustion propagation, and persistence.

The DAG topology is **encoded as Python call order**. Swapping the topology means editing the file.

#### 3b. Adaptive / Monitor (near-term, issue #100)

A **Run Monitor** sits above the per-iteration loop. It:
- Observes every `tune_output` and updates `cost_profiles[architecture_family]`.
- Detects ghost scores (byte-identical formal scores), mode collapse signatures, anchor-strategy commensurability problems.
- Decides at each control point (skip_formal, bypass-time-budget, retry-with-larger-budget, prune-candidate, request-revalidation) whether to permit the workflow's default or override it.

The Run Monitor is its own node with its own `run()` method and is composed *with* the human-defined DAG (3a), not as a replacement.

#### 3c. LLM orchestrator (future)

The LLM reads the populated `NODE_REGISTRY` (after Phase 1), reads a `WorkflowConfig` for the active workflow, and proposes node sequences for a given goal. The orchestrator becomes a runtime, not a hardcoded file.

**WorkflowConfig: DAG-as-data.** A Pydantic schema like:

```python
class NodeStep(BaseModel):
    node_name: str                # → NODE_REGISTRY lookup
    protocol_from_upstream: str   # → agent/schemas/protocols/ lookup
    gate_condition: str | None    # optional predicate

class WorkflowConfig(BaseModel):
    steps: list[NodeStep]
    retry_policy: dict
    persistence_layer: str
```

A `default_workflow.json` (extracted from the current model_exploration.py) becomes the canonical DAG for the current chain workflow. Variants (`v16_loss_explorer_workflow.json`, `v16_arch_explorer_workflow.json`) live alongside it as data, not code.

**Current state.** No `Workflow` abstraction exists. No `WorkflowConfig` schema. Branching is `if force_formal_round` / `if lit_review_enabled` boolean gates, not dynamic dispatch. The 2608-line file IS the orchestrator.

**Gap.** Extract DAG topology into `WorkflowConfig`, introduce an `Orchestrator` class whose state is the `steps` list. Move retry/persistence concerns into named layers. Estimated at 1 week for Phase 3 + 2 weeks for Phase 4 (stateless nodes).

---

## 3. Current State Audit (2026-06-29)

Verbatim gap-analysis table from the read-only audit performed on 2026-06-29 against the codebase at master tip:

| Capability | Three-layer ideal | Current state | Gap |
|---|---|---|---|
| **Node self-description** | Each node declares name, description, input/output schema as a single discoverable object | `SkillSpec` class exists at `agent/schemas/skill_spec.py` with `to_openai_tool()` support. **Zero production nodes adopt it.** All 6 main agents only have `def run(inp: XxxInput) → XxxOutput`. `agent/skills/__init__.py` is empty. | **Large.** Infrastructure designed, adoption zero. |
| **Node registry / catalog** | Central registry an LLM can query | None. `grep NodeRegistry\|node_registry\|SkillRegistry\|skill_catalog` returned zero matches. Workflow hardcodes imports at lines 87, 92-94, 96. | **Maximal.** Nothing exists. |
| **Typed protocols between nodes** | Schema-validated connections, one protocol per directed edge | **Complete.** 6 protocols in `agent/schemas/protocols/`, each with `local_*` + `database_*` stubs, unit + integration tests. The workflow uses them as the only field-mapping mechanism. | **None — production grade.** |
| **Dynamic routing** | Next node decided at runtime based on context | None. `grep route\|dispatch\|select.*node` returned 2 false-positive matches in workflows/. Branching is boolean gates only (`force_formal_round`, `lit_review_enabled`). | **Maximal.** No dispatch primitive. |
| **Orchestrator abstraction** | Workflow logic separate from node logic | Minimal. The 2608-line workflow IS the orchestrator — DAG, node instantiation, attribute injection, retry, persistence all conflated. | **Large.** |
| **LLM-readable node catalog** | LLM can enumerate available nodes and their contracts | None. No JSON/YAML catalog. `agent/skills/__init__.py` empty. `SkillSpec.to_openai_tool()` exists but unused. | **Maximal — but unblocked once Layer 1 lands.** |
| **Human-replaceable orchestrator** | Can swap DAG without changing node code | No. No DAG-as-data exists. Swapping topology requires editing the 2608-line file. | **Maximal.** |
| **Stateless nodes** | Nodes have no side effects outside their output | Partial. All 6 agents have `run(inp) → Output` interfaces (stateless at the call level), **but** they write to filesystem (run_output.json, plugin .py files, description.md) and mutate `agent_generated/_capability_index.json` from inside `run()`. | **Medium.** Outputs are part data, part filesystem mutation. |

**Summary:**
- **Layer 2: 100% complete.** Protocols are the architectural success story.
- **Layer 1: ~10% complete.** Scaffolding exists (`SkillSpec`), adoption is zero.
- **Layer 3: ~0% complete.** Vision is documented in `docs/architecture.md`; no `Orchestrator` class, no `WorkflowConfig`, no dispatch primitive.

---

## 4. Why This Architecture

### The problems it solves

**I9 / I12 / I13–I16: registry-asymmetry bugs.** Each of these (and PR #98's I13–I16 fixes) had the same shape: a downstream consumer hardcoded a list of accepted values (e.g. `loss_type in {"ce", "focal", "focal_cw"}`) instead of declaring its requirement via the schema and querying the registry. When a new value was added (custom loss types), the consumer broke silently. A registry-driven node-and-schema architecture makes this class of bug structurally impossible — the consumer reads the registry; the registry is the source of truth.

**v15 ghost scores / mode collapse (14 of 22 byte-identical formal file_vectors).** No node was positioned to observe the cross-iteration pattern. A Run Monitor with cross-iteration memory would have detected it within 3 occurrences and either bumped `max_epochs` or flagged the loss family. See issue #93 and v15 report §6.9.

**v15 anchor strategy artifact (iter_19 trial 7.25 vs formal 5.576).** The trial used `trial_strategy='anchors'` (3 files), the formal used `trial_strategy='snapshot'` (20 files). These produce incommensurable scalars, but the workflow treated them as comparable when deciding whether to fire `bypass_formal_time_budget_min_delta`. A strategy-aware Run Monitor would have suppressed the bypass gate. See v16 report §8.1.

**Loss chain design violation: model-as-control-variable not enforceable.** The v16 loss-explorer advice says "iter_002 onward: model Branch B REQUIRED." Today this is enforced by **proposer prompt language** and the `_validate_branch_b_model_registry_membership` validator. With a graph-aware orchestrator, the rule could be expressed structurally: "this workflow disallows the model-proposing edge after iter_001."

### The principle

Each bug fixed manually in v15/v16 had the same three-part structure:

1. **A pattern emerged across iterations** that no single iteration could see.
2. **The response required adjusting run-level parameters** (max_epochs, advice, gate thresholds) — beyond any one node's authority.
3. **The orchestrator-level observation-and-action loop didn't exist** to do this without human review.

A graph-aware orchestrator with cross-iteration memory and per-control-point policy decisions catches all of these automatically. The Run Monitor (issue #100) is the first instance of that pattern.

### Health checks as first pluggable skill (v16)

The class-127 collapse attractor discovery (see
`docs/design/pluggable_health_checks.md` § Motivation) demonstrated why
health checks cannot be hardcoded: different tasks have different collapse
attractors. The `execute_tools/health_checks/` system is the first
concrete implementation of a pluggable skill following the three-layer
pattern — typed Protocol, YAML config, import-time registry — and serves
as the reference implementation for all future skills.

### Incident log (v15/v16)

These concrete failures motivated each architectural decision:

| Incident | Root cause | Fix | Architectural lesson |
|---|---|---|---|
| Ghost scores (5.5763) | Class-127 collapse + 2^17 FP artifact | `OutputDiversityCheck` + SNR noise-floor guard + corrected schema default (commit `6fcc87f`) | Health checks must be pluggable and run before scoring |
| Registry timing race | `_capability_index.json` written before validation | #92 fix: write after validation (commit `f1e1ba8`, loss surface) | Registry write and file promotion must be atomic |
| Phantom Branch B model | Model written to index before validation passes | Mirror #92 fix for models (commit `8c5ff23`) | Same timing invariant applies to all component types |
| Loss chain design violation | No "model Branch B" concept existed | Model Branch B (commit `408838d`) | Component symmetry: every pluggable type needs A/B/C |
| Arch chain time-gate blocks | Trial scores not comparable to formal anchor | Narrow-coverage suppression (planned for v17; see `reports/v16_20260630.md` §8.1) | Scores from different sampling strategies are incommensurable |
| Vocab promotion zero | Proposer invented new names every iter | Three vocab fixes (commit `9592494`) | Naming discipline must be enforced at prompt level |
| I13–I16 registry asymmetry | Consumers hardcoded loss_type lists | `get_target_torch_dtype()` helper | Protocol is the boundary — consumers must not hardcode capability lists |

---

## 5. Node Catalog (current nodes)

The 6 main agent nodes + 6 production skills. SkillSpec adoption status: **none**.

### Main agents

| Class | File | Input → Output | Side effects |
|---|---|---|---|
| `MLLiteratureReviewAgent` | `nodes/ml_literature_review/ml_literature_review.py:274` | `LiteratureReviewInput` → `LiteratureReviewOutput` | Writes `ml_literature_review_{iter}.json`; reads/writes the lit-review cache. |
| `MLModelProposalAgent` | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:907` | `ProposalInput` → `ProposalOutput` | Writes `proposal_{iter}.json` per attempt. |
| `MLModelImplementor` | `nodes/ml_model_implementor/ml_model_implementor.py:1242` | `ImplementorInput` → `ImplementorOutput` | Writes plugin `.py`, `description.md`, test file; mutates `agent_generated/_capability_index.json`. |
| `MLCodeValidatorAgent` | `nodes/ml_code_validator_agent/ml_code_validator_agent.py:390` | `ValidatorInput` → `ValidatorOutput` | Writes `validation_{iter}.json`; runs subprocess pytest. |
| `HyperparamTuningAgent` | `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:916` | `HyperparamTuningInput` → `HyperparamTuningOutput` | Writes per-round config + run_output JSON; orchestrates training/inference/scoring subprocesses. |
| `ResultInterpretationAgent` | `nodes/result_interpretation_agent/result_interpretation_agent.py:705` | `InterpretationInput` → `InterpretationOutput` | Writes `interpretation_{iter}.json`. |

All 6 share the consistent `def run(self, inp: XxxInput) → XxxOutput` interface — Layer 2's protocols and Layer 1's `SkillSpec` adoption are blocked only by the explicit `spec` class attribute and registry registration, not by interface drift.

### Skill nodes

`agent/skills/` contains 7 entries (6 subdirectories + 1 flat file), with **non-uniform** interfaces:

| Skill | Layout | Interface | Comment |
|---|---|---|---|
| `evaluate_time_skill` | subdir with `wrapper.py`, `estimator.py`, `calibration.py` | `wrapper.py` exposes `run_skill(sandbox, **kwargs)` | Used by tuner planner pre-flight |
| `evaluate_vram_skill` | subdir | `run_skill(sandbox, **kwargs)` | Same pattern |
| `training_skill` | subdir with `wrapper.py`, `estimator.py` | `run_skill(...)` | Tuner per-round training |
| `inference_skill` | subdir | `run_skill(...)` | Tuner per-round inference |
| `denoising_score_skill` | subdir | wrapper-style | Tuner per-round scoring |
| `check_config_format_skill` | subdir | `def run_skill(sandbox, **kwargs)` at `wrapper.py:8` | Used by validator |
| `forbidden_pattern_skill.py` | **flat file** | Module-level `check_file()` + `ForbiddenLoopHit` dataclass | Used by validator |
| `paper_resolver_skill` | subdir with `wrapper.py`, `arxiv_source.py` | wrapper-style | Used by lit-review |

The `wrapper.py` naming pattern indicates skills were retrofitted into a module shape rather than designed as `SkillSpec`-compliant nodes from day one. The flat `forbidden_pattern_skill.py` is an interface outlier — useful as a target for the Phase 1 normalization.

### Health check skills (`execute_tools/health_checks/`)

The first pluggable skill family in production — `HealthCheckSkill`
Protocol + import-time registry + `configs/health_checks.yaml`. Two
checks currently registered (`OutputDiversityCheck`,
`AmplitudeCollapseCheck`), called from
`execute_tools/scoring_utils.py::score_vector`. Reference implementation
for main-agent `SkillSpec` adoption in the rest of Phase 1.

Full spec: **`docs/design/pluggable_health_checks.md`**.

---

## 6. Implementation Roadmap

### Phase 1: Complete Layer 1 (Node self-description) — IN PROGRESS

**Goal:** Every node has a discoverable `SkillSpec`.

**Phase 1 progress (as of `feat/v16-fixes`):**
- ✅ Health check skills: first pluggable skill with typed Protocol + YAML config
- ✅ Model Branch B: `MODEL_REGISTRY` + `register_model_in_memory()`
- ✅ Loss Branch B: `LOSS_REGISTRY` (`feat/enable-loss-inventory`)
- ⬜ `SkillSpec` adoption on 6 main nodes
- ⬜ `NODE_REGISTRY` with register-on-import
- ⬜ `agent/skills/__init__.py` populated

**Remaining tasks (detail):**
- Add `spec: ClassVar[SkillSpec] = SkillSpec(...)` to each of the 6 main agents.
- Normalize skill nodes to a uniform interface (`def run_skill(input: SkillInput) → SkillOutput` with Pydantic input/output schemas, replacing the current `**kwargs` pattern). Convert `forbidden_pattern_skill.py` from flat module to subdirectory layout.
- Populate `agent/skills/__init__.py` and `nodes/__init__.py` with re-exports.
- Build `NODE_REGISTRY: dict[str, SkillSpec]` via decorator or `__init_subclass__`. One canonical location: `agent/node_registry.py`.

**Estimated effort:** ~1 day for the main-agent adoption. Skill-node
normalization can be deferred until an actual consumer (the LLM
orchestrator in Phase 5) needs it.
**Unlocks:** LLM can enumerate available nodes via `[spec.to_openai_tool() for spec in NODE_REGISTRY.values()]`. The Run Monitor (Phase 2) can discover what nodes exist without hardcoded knowledge.
**De-risked by:** the health-check registry is empirical proof that the
Protocol + registry + config pattern works in production, not just
in theory.

### Phase 2: Run Monitor (First non-human orchestrator)

**Goal:** A cross-iteration observer that detects patterns and adjusts strategy.

**Tasks:**
- Implement `RunMonitor` class per issue #100 with `observe(iter_record)` and `policy(context) → PolicyDecision`.
- Detection routines: ghost-score detection (byte-identical formal scores across iters), mode-collapse signatures (file_vector zero-dominance), anchor-strategy commensurability (suppress bypass when `trial_strategy != 'snapshot'`), cost profile learning per `(model_family, segmentation_size)`, stagnation detection.
- Policy outputs: `suppress_bypass`, `suggested_max_epochs`, `suggested_trial_strategy`, `prune_candidate`, `revalidation_required`.
- Wire into `workflows/model_exploration.py` at each control point (skip_formal / bypass_time_budget / formal_round_strategy / max_fail_rounds). Decisions are advisory until validated; promote to enforcing after.

**Estimated effort:** 1–2 weeks.
**Subsumes:** issue #96 (already closed in favor of #100).
**References:** issue #93 (the "adaptive training budget" sub-bullet becomes a Run Monitor policy), issue #95 (Run Monitor consumes the bidirectional info-flow channel).

### Phase 3: WorkflowConfig (DAG-as-data)

**Goal:** The DAG topology is data, not Python call order.

**Tasks:**
- Define `WorkflowConfig` Pydantic schema (`steps: list[NodeStep]`, `retry_policy`, `persistence_layer`).
- Extract current DAG from `workflows/model_exploration.py` into `configs/workflows/default_chain.json`.
- Introduce `Orchestrator` class whose `run()` reads a `WorkflowConfig` and walks the steps generically: for each step, look up `node = NODE_REGISTRY[step.node_name]`; look up `protocol = PROTOCOL_REGISTRY[step.protocol_from_upstream]`; call `node.run(protocol(prev_output, storage))`.
- Move retry, persistence, attempt-dir management out of the workflow file into the orchestrator's `RetryPolicy` and `Persistence` layers.

**Estimated effort:** 1 week.
**Unlocks:** Swapping the DAG without editing Python code. A v17 alt-workflow that injects the Run Monitor at the gate-decision sites becomes a JSON edit, not a code change.

### Phase 4: Stateless nodes (Persistence layer)

**Goal:** Node `run()` returns pure data; the orchestrator's `Persistence` layer handles all I/O.

**Tasks:**
- Refactor each node's `run()` to return its `Output` schema without filesystem writes.
- Move `register(CapabilityMetadata)` and plugin-file writes from the implementor into an `ImplementorPersistence` layer invoked by the orchestrator.
- Move per-iter JSON dumps (run_output, validation, interpretation) into a generic `Persistence.write(node_name, iter, output)` step.

**Estimated effort:** 2 weeks.
**Required for:** distributed execution (multiple workers on the same chain), reliable replay (re-run a node from its input alone), test isolation (no `tmp_path` ceremony per node).

### Phase 5: LLM Orchestrator

**Goal:** An LLM can propose node sequences for a given goal, reading the registry and choosing protocols.

**Tasks:**
- LLM reads `NODE_REGISTRY` (built in Phase 1).
- LLM reads `WorkflowConfig` schema (built in Phase 3).
- LLM proposes a `WorkflowConfig` for a goal ("explore loss surface holding architecture fixed"); operator approves; orchestrator executes.
- Failure escalation: when a workflow fails, the LLM orchestrator can propose a modified `WorkflowConfig` based on the failure.

**Estimated effort:** 1–2 weeks (after Phases 1 + 3).
**End state:** Humans and LLMs use the same orchestrator surface. The substrate is fixed; the strategy is composed at runtime.

---

## 7. Design Principles

1. **Protocol is the boundary.** Nodes communicate only through typed schemas via named protocol functions. No shared state, no implicit contracts, no field mapping outside `agent/schemas/protocols/`.
2. **Nodes don't know the graph.** A node only knows its own input/output contract. It doesn't know what comes before or after, what orchestrator is running it, or whether it's inside a cycle.
3. **Orchestrators are swappable.** The same set of nodes can be composed by a human-defined DAG, a Run Monitor, or an LLM. The substrate is identical.
4. **Registry is the single source of truth.** What nodes exist, what plugins are available, what's been validated — all in registries (`NODE_REGISTRY`, `agent_generated/_capability_index.json`, `MODEL_REGISTRY`, `LOSS_REGISTRY`). Consumers query; nobody hardcodes.
5. **Component symmetry.** Every pluggable component type follows the same Branch A/B/C pattern and registry contract:

    | | Loss | Model | Health Check |
    |---|---|---|---|
    | Branch A | built-in (ce/focal) | built-in (wavenet/punet) | built-in check |
    | Branch B | reuse registered | reuse registered | reuse config |
    | Branch C | generate new plugin | generate new plugin | implement new skill |
    | Registry | `LOSS_REGISTRY` | `MODEL_REGISTRY` | `_HEALTH_CHECK_REGISTRY` |
    | Config | `LossConfig` | `ModelConfig` (dict, #97) | `health_checks.yaml` |

    Issue #97 tracks completing schema-level symmetry (typed `ModelConfig`).
6. **Transport-agnostic schemas.** Per `docs/architecture.md` §8: schemas define data format; `StorageConfig` defines location. A protocol's `local_*` and `database_*` variants populate the same schema differently.
7. **Cycles are orchestrator-driven, not node-driven.** A node doesn't know it's in a loop. Per `docs/architecture.md` §7: an orchestrator traverses cycles repeatedly; nodes are stateless on each traversal.

---

## 8. Relationship to Existing Issues

| Issue | Status | Relationship |
|---|---|---|
| **#91** (modular agent orchestration) | OPEN | This document is the detailed spec for the three-layer framing #91 calls out. Themes A–I in #91 map onto specific phases here: A → Phase 3, B → Phase 1, C → Phase 1, D → Phase 1, E → Phase 5 (tool-calling for LLM orchestrator), F → adjacent (corpus/retrieval), G → Phase 1 (validator check registry), H → Phase 2 (Run Monitor retry policy), I → Phase 1 (typed schema instead of free-text). |
| **#92** (registry timing) | CLOSED | Loss surface closed by commit `f1e1ba8`. Model surface closed by commit `8c5ff23` on `feat/v16-fixes` — the earlier belief that PR #98 closed both was incorrect; PR #98 was the symmetric-Branch-B feature and left the model registry-write timing untouched. |
| **#93** (adaptive training regime) | OPEN | Phase 2 subsumes the "adaptive training budget" sub-bullet (Run Monitor policy: detect collapse → next iter gets higher `max_epochs`). The training-skill-internal diversity gates (#93 items 1, 3) remain separate. The class-127 audit (in `docs/design/pluggable_health_checks.md`) makes this concrete: the collapse signal is `output_diversity → is_degenerate=True`, and the Run Monitor's cross-iter policy consumes it directly. |
| **#94** (info source weighting) | OPEN | Phase 5 (LLM orchestrator) is the natural home — the orchestrator decides the proposer's information mix per goal. |
| **#95** (bidirectional info flow) | OPEN | Phase 2 prerequisite — Run Monitor consumes the structured tuner-findings channel #95 establishes. |
| **#96** (dynamic resource allocation) | CLOSED | Subsumed by Run Monitor (#100). |
| **#97** (ModelConfig typed schema) | OPEN | Phase 4 (stateless nodes) — part of the same typed-boundary effort. The current dict-based `baseline_config["model_config"]["model_name"]` works but is a category violation; a `ModelConfig` Pydantic class makes the contract explicit. |
| **#100** (Run Monitor) | OPEN | Phase 2 detailed spec. |

---

## 9. Sequencing and dependencies

```
        Phase 1 (Layer 1)
       /          \
      v            v
  Phase 2     Phase 3 (Layer 3)
  (Run         /
  Monitor)    /
       \     /
        v   v
       Phase 4 (Stateless)
            |
            v
       Phase 5 (LLM Orchestrator)
```

- **Phase 1 unblocks both Phase 2 and Phase 3.** Run Monitor and WorkflowConfig both need a discoverable node registry.
- **Phase 2 is independent of Phase 3.** A Run Monitor can be wired into the current hardcoded workflow without DAG-as-data.
- **Phase 4 depends on Phase 3.** Moving filesystem writes out of nodes requires the orchestrator's `Persistence` layer to exist.
- **Phase 5 depends on Phase 1 + Phase 3.** An LLM orchestrator needs both the registry to read from and the `WorkflowConfig` schema to write into.

This sequencing lets each phase deliver value independently and validates the design incrementally before committing to the next phase.

---

## 10. References

- `docs/architecture.md` — foundational principles (graph topology, fan-in protocols, transport-agnostic schemas, orchestrator-as-node).
- `docs/design/pluggable_health_checks.md` — the pluggable-skill pattern's design spec (Phase 1 proof-of-concept, §5 in this doc).
- `agent/schemas/skill_spec.py` — the `SkillSpec` class designed for Layer 1 self-description.
- `agent/schemas/protocols/` — the 6 production protocols (Layer 2, complete).
- `execute_tools/health_checks/` — first pluggable-skill family in production; blueprint for main-agent adoption.
- `workflows/model_exploration.py` — the de-facto Layer 3 orchestrator (~2660 lines, refactor target).
- `reports/v16_20260630.md` §§8–9 — anchor-strategy commensurability and the class-127 forensic audit that motivated the health-check framework (see `docs/design/pluggable_health_checks.md`).
- v15 final report — ghost-score audit, mode-collapse signatures, anchor-strategy artifacts.
- Issues #91, #93, #94, #95, #97, #100 — feature work that depends on this architecture.
