# Research nodes

Each node carries out one research step, such as proposing a model or checking
its implementation. A workflow chooses which steps run and passes their typed
inputs and outputs. Start here to find the owner of a step.

## Choose a step

| node | class role | contract doc |
|---|---|---|
| `ml_literature_review/` | evidence corpus → expert context | [`ml_literature_review.md`](ml_literature_review/ml_literature_review.md) |
| `result_interpretation_agent/` | prior records → interpretation | [`result_interpretation_agent.md`](result_interpretation_agent/result_interpretation_agent.md) |
| `data_analysis_agent/` | authorized scientific assets → structured analysis report | [`data_analysis_agent.md`](data_analysis_agent/data_analysis_agent.md) |
| `ml_model_proposal_agent/` | interpretation + evidence → architecture proposal | [`ml_model_proposal_agent.md`](ml_model_proposal_agent/ml_model_proposal_agent.md) |
| `ml_model_implementor/` | proposal → model plugin code | [`ml_model_implementor.md`](ml_model_implementor/ml_model_implementor.md) |
| `ml_code_validator_agent/` | plugin code → validation verdict | [`ml_code_validator_agent.md`](ml_code_validator_agent/ml_code_validator_agent.md) |
| `ml_hyperparameter_tune_agent/` | validated model → tuned, scored, health-gated records | [`ml_hyperparameter_tune_agent.md`](ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md) |

## Use or extend a node

For a normal run, choose a [workflow](../workflows/README.md). To integrate one
step into a caller-owned workflow, read that node's linked contract and the
[schema guide](../agent/schemas/README.md) for its input and output types.
Per-node records help inspect or resume work; they are not messages between
nodes.

To add a node, start with the [repository rules](../../CLAUDE.md) and
[node contract template](NODE_TEMPLATE.md). The
[package contract](node-contract.md) explains public boundaries, configuration
inspection, failure records and the relevant tests.

Prompt rendering and provider access belong to [agent support](../agent/README.md).
Training, inference and scoring belong to
[execution tools](../execute_tools/README.md).
