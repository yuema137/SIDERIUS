# Agent reference — technical documentation index

**Audience**: a coding agent (or engineer) about to modify SIDERIUS.
**Purpose**: get from an intent to the 1–3 documents that let you work safely,
without reading the 170,000-line design archive.

**Reflects landed `master` at `23276743`.** Where a mechanism is in flight, the
document says so and names the owner.

---

## Rules of engagement

1. **The source is the authority.** These documents are projections of it. Where
   a document and the module disagree, the module is right — fix the document.
2. **Design documents are history.** `docs/design/**` records *why* decisions
   were made and what evidence supported them. It is not a description of current
   behaviour, and several of its claims describe intent that has not landed.
3. **Read [`CLAUDE.md`](../../CLAUDE.md) before editing.** It carries the binding
   coding standards, the responsibility-decomposition rule, the test-economy
   rules and the subsystem invariants.

## By intent

| I want to… | read |
|---|---|
| understand what SIDERIUS is | [concepts/overview](../concepts/overview.md) |
| add or change a task's declarations | [reference/task-composition](../reference/task-composition.md) → [mechanisms/composition](mechanisms/composition.md) |
| add a new evaluation metric | [mechanisms/metrics](mechanisms/metrics.md) → [mechanisms/plugins](mechanisms/plugins.md) |
| add a health check | [mechanisms/health-gates](mechanisms/health-gates.md) → [mechanisms/plugins](mechanisms/plugins.md) |
| understand `TaskDataPath` | [mechanisms/data-path-and-scope](mechanisms/data-path-and-scope.md) |
| understand or debug scope transport | [mechanisms/data-path-and-scope](mechanisms/data-path-and-scope.md) → [mechanisms/execution](mechanisms/execution.md) |
| debug child-subprocess plugin loading | [mechanisms/execution](mechanisms/execution.md) → [mechanisms/plugins](mechanisms/plugins.md) |
| change tuner behaviour | [tuner node doc](../../nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md) → [mechanisms/metrics](mechanisms/metrics.md) |
| understand `TrainingHistory` / `TrainingDiagnosis` | [mechanisms/training-objective-and-diagnosis](mechanisms/training-objective-and-diagnosis.md) |
| change what the interpreter reads | [interpreter node doc](../../nodes/result_interpretation_agent/result_interpretation_agent.md) |
| change what the proposer reads | [proposer node doc](../../nodes/ml_model_proposal_agent/ml_model_proposal_agent.md) |
| find which manifest sections are required | [reference/task-composition](../reference/task-composition.md) |
| create a new external task package | [guides/define-a-task](../guides/define-a-task.md) → [reference/task-composition](../reference/task-composition.md) |
| understand plugin identity / provenance | [mechanisms/plugins](mechanisms/plugins.md) |
| understand resume / why a workspace refuses | [mechanisms/persistence-and-resume](mechanisms/persistence-and-resume.md) |
| add a node to the graph | [nodes/NODE_TEMPLATE.md](../../nodes/NODE_TEMPLATE.md) → [architecture](../architecture.md) |
| know what is landed vs planned | [concepts/supported-tasks](../concepts/supported-tasks.md) |

## Mechanisms

Cross-node concepts, documented by **semantic owner** rather than by file.

| document | owns |
|---|---|
| [composition](mechanisms/composition.md) | the manifest, its resolution, run-scoped binding, the semantic fingerprint |
| [data-path-and-scope](mechanisms/data-path-and-scope.md) | `TaskDataPath`, `TaskScopeCapability`, `DatasetProfile`, `DataScope`, scope artifacts |
| [metrics](mechanisms/metrics.md) | `MetricSpec`, `MetricOrder`, scoreability, primary vs secondary |
| [training-objective-and-diagnosis](mechanisms/training-objective-and-diagnosis.md) | `TrainingHistory`, comparability, `TrainingDiagnosis` |
| [health-gates](mechanisms/health-gates.md) | check protocol, verdicts, gate actions, policy composition |
| [execution](mechanisms/execution.md) | the three child subprocesses, argv transport, deliverables, resource ceilings |
| [plugins](mechanisms/plugins.md) | every plugin family, how each is loaded, identity and provenance |
| [persistence-and-resume](mechanisms/persistence-and-resume.md) | records, the invariants lock, carried state, auto-resume |

## Nodes

Each node owns one stage. Its `.md` is the contract.

| node | role | LLM | CLI (`main()`) |
|---|---|:---:|---|
| [`result_interpretation_agent`](../../nodes/result_interpretation_agent/result_interpretation_agent.md) | synthesise evidence across records; state what it supports | ✅ | `nodes/result_interpretation_agent/result_interpretation_agent.py:1278` |
| [`ml_literature_review`](../../nodes/ml_literature_review/ml_literature_review.md) | surface papers as soft priors (optional stage) | ✅ | `nodes/ml_literature_review/ml_literature_review.py:1055` (upstream record read from disk by naming convention — #303) |
| [`ml_model_proposal_agent`](../../nodes/ml_model_proposal_agent/ml_model_proposal_agent.md) | propose an architecture and an explicit prediction | ✅ | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:2352` |
| [`ml_model_implementor`](../../nodes/ml_model_implementor/ml_model_implementor.md) | write the model plugin (and optional loss plugin) | ✅ | `nodes/ml_model_implementor/ml_model_implementor.py:2362` |
| [`ml_code_validator_agent`](../../nodes/ml_code_validator_agent/ml_code_validator_agent.md) | deterministic checks + LLM review of generated code | ✅ | `nodes/ml_code_validator_agent/ml_code_validator_agent.py:896` |
| [`ml_hyperparameter_tune_agent`](../../nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md) | N rounds of plan → train → infer → score → health → reflect | ✅ | `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:1764` (parser and input builder in `cli.py`) |

All six nodes are standalone-capable — each exposes an `argparse` `main()`
behind `if __name__ == "__main__":` at the line cited
(`ml_literature_review`'s CLI landed with #303/#305). The CLI column is
verified by `tests/unit/docs/test_node_docs_contract.py`: exactly six
`file:line` citations, each pointing at a `def main` line, and every node
doc's declared type must match its module's `__main__` reality. Invocation
details live in each node's own `.md`.

Adding a node: [`nodes/NODE_TEMPLATE.md`](../../nodes/NODE_TEMPLATE.md) — all
eight steps, including the connection audit.

## Architecture and standards

| document | purpose |
|---|---|
| [`docs/architecture.md`](../architecture.md) | the graph, node contract, protocols, skills, testing strategy |
| [`CLAUDE.md`](../../CLAUDE.md) | binding coding standards and subsystem invariants |
| [`docs/gates/gate_testing_standard.md`](../gates/gate_testing_standard.md) | Gate 1 / Gate 2 commands and pass criteria |
| [`tests/pseudo_data/README.md`](../../tests/pseudo_data/README.md) | pseudo-mode fixtures for dual-mode tests |
| [`docs/design/README.md`](../design/README.md) | the design archive — history and rationale, not current behaviour |

## Three invariants worth knowing before you touch anything

- **Nodes communicate only through schemas, storage and protocols.** Storage is a
  log, not a channel. Reading a peer node's output file is a defect.
- **No raw LLM output reaches execution.** Everything passes a Pydantic schema
  first, and execution reads the validated object, never the raw dict.
- **One authority per rule.** Metric direction has exactly one interpreter;
  key-finding union has exactly one function; deliverable naming has one owner.
  Re-inlining any of them is the defect these guards exist to catch.
