# Agent reference — technical documentation index

**Audience**: framework contributors and automated coding tools.
**Purpose**: get from an implementation intent to the 1–3 documents that let
you work safely,
without reading the 170,000-line design archive.

The mechanism index was established at `23276743`. The
[repository map](../repository-map.md) records the P0 source audit at `2091acdf`,
including current ownership and remaining exceptions. Adding this navigation
does not re-audit every linked mechanism document.

---

Package-relative source citations in the mechanism guides map under `src/`.
Python imports keep their existing names; see the [source guide](../../src/README.md).

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
| locate current modules, entrypoints and the external consumer | [repository map](../repository-map.md) |
| add or change a task's declarations | [reference/task-composition](../reference/task-composition.md) → [mechanisms/composition](mechanisms/composition.md) |
| add a new evaluation metric | [mechanisms/metrics](mechanisms/metrics.md) → [mechanisms/plugins](mechanisms/plugins.md) |
| add a health check | [mechanisms/health-gates](mechanisms/health-gates.md) → [mechanisms/plugins](mechanisms/plugins.md) |
| understand `TaskDataPath` | [mechanisms/data-path-and-scope](mechanisms/data-path-and-scope.md) |
| understand or debug scope transport | [mechanisms/data-path-and-scope](mechanisms/data-path-and-scope.md) → [mechanisms/execution](mechanisms/execution.md) |
| debug child-subprocess plugin loading | [mechanisms/execution](mechanisms/execution.md) → [mechanisms/plugins](mechanisms/plugins.md) |
| change tuner behaviour | [tuner node doc](../../src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md) → [mechanisms/metrics](mechanisms/metrics.md) |
| understand `TrainingHistory` / `TrainingDiagnosis` | [mechanisms/training-objective-and-diagnosis](mechanisms/training-objective-and-diagnosis.md) |
| change what the interpreter reads | [interpreter node doc](../../src/nodes/result_interpretation_agent/result_interpretation_agent.md) |
| understand or extend scientific data analysis | [data analysis node doc](../../src/nodes/data_analysis_agent/data_analysis_agent.md) → [reference/task-composition](../reference/task-composition.md#optional-data-analysis-capability) |
| change what the proposer reads | [proposer node doc](../../src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.md) |
| find which manifest sections are required | [reference/task-composition](../reference/task-composition.md) |
| create a new external task package | [guides/define-a-task](../guides/define-a-task.md) → [reference/task-composition](../reference/task-composition.md) |
| understand plugin identity / provenance | [mechanisms/plugins](mechanisms/plugins.md) |
| understand resume / why a workspace refuses | [mechanisms/persistence-and-resume](mechanisms/persistence-and-resume.md) |
| add a node to the graph | [nodes/NODE_TEMPLATE.md](../../src/nodes/NODE_TEMPLATE.md) → [architecture](../architecture.md) |
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
| [`result_interpretation_agent`](../../src/nodes/result_interpretation_agent/result_interpretation_agent.md) | synthesise evidence across records; state what it supports | ✅ | `src/nodes/result_interpretation_agent/result_interpretation_agent.py:1366` |
| [`data_analysis_agent`](../../src/nodes/data_analysis_agent/data_analysis_agent.md) | execute authorized scientific-analysis skills and synthesize a bounded report | ✅ | Python capability API only |
| [`ml_literature_review`](../../src/nodes/ml_literature_review/ml_literature_review.md) | surface papers as soft priors (optional stage) | ✅ | `src/nodes/ml_literature_review/ml_literature_review.py:1153` (standalone CLI; the workflow supplies typed evidence) |
| [`ml_model_proposal_agent`](../../src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.md) | propose an architecture and an explicit prediction | ✅ | `src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:2501` |
| [`ml_model_implementor`](../../src/nodes/ml_model_implementor/ml_model_implementor.md) | write the model plugin (and optional loss plugin) | ✅ | `src/nodes/ml_model_implementor/ml_model_implementor.py:2329` |
| [`ml_code_validator_agent`](../../src/nodes/ml_code_validator_agent/ml_code_validator_agent.md) | deterministic checks + LLM review of generated code | ✅ | `src/nodes/ml_code_validator_agent/ml_code_validator_agent.py:945` |
| [`ml_hyperparameter_tune_agent`](../../src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md) | N rounds of plan → train → infer → score → health → reflect | ✅ | `src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:1849` (parser and input builder in `cli.py`) |

Six nodes currently have a CLI entry: each exposes an `argparse` `main()`
behind `if __name__ == "__main__":` at the line cited
(`ml_literature_review`'s CLI landed with #303/#305). The marker and source
citations are structural facts only; they do not certify that an invocation
has all task context needed for a successful run. Invocation boundaries and
limitations live in each node's own `.md`. `data_analysis_agent` is the seventh
node and currently exposes a typed Python capability API rather than a CLI.

Adding a node: [`nodes/NODE_TEMPLATE.md`](../../src/nodes/NODE_TEMPLATE.md) — all
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
