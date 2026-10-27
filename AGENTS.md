# SIDERIUS — entry point for coding agents

Read [CLAUDE.md](CLAUDE.md) first. It owns repository contribution policy;
the linked subsystem contracts and source own detailed behavior. This file
provides navigation only; boundary rules and their single owners stay in CLAUDE.md's
single-authorities table.

SIDERIUS is a task-generic closed-loop research framework for supervised
scientific machine learning. Tasks supply scientific semantics through
composition manifests and plugins in external projects.

## Contribution policy

| Need | Start here |
| --- | --- |
| Contribution scope, planning, review and merge | [PR scope and structured-coding workflow](CLAUDE.md#pull-request-scope-and-structured-coding-workflow) |
| Environment binding and launch credentials | [Environment](CLAUDE.md#environment-and-launch-credentials) |
| Coding standards and deterministic subsystem owners | [Standards](CLAUDE.md#coding-standards), [single authorities](CLAUDE.md#architecture-and-single-authorities) |
| Documentation audiences and review | [Documentation rules](CLAUDE.md#documentation-audience-and-review) |
| Help a user configure their own task from a brief request | [Coding-agent setup route](README.md#start-with-your-coding-agent), [repository setup skill](docs/agent-reference/siderius-setup-review/SKILL.md) |

## Capability map

One line per area; each link is the owning document. Intent-level lookup lives
in the [reference index](docs/agent-reference/index.md), and source locations in
the [repository map](docs/repository-map.md).

| Area | Owning documents |
| --- | --- |
| Fixed workflow chain and CLI launch | [workflow contract](src/workflows/workflow-contract.md), [launch scripts](scripts/launch/README.md), [entrypoints](docs/reference/entrypoints.md) |
| Native chain capture and launch | [native chain contract](src/tools/native_chain/native-chain-contract.md) |
| Workflow declarations and authoring | [declaration contract](src/workflows/definition/definition-contract.md), [authoring contract](src/tools/workflow_authoring/authoring-contract.md), [custom workflow guide](docs/guides/custom-workflow.md) |
| Agent-driven orchestration in an external project | [orchestrator toolkit](docs/agent-reference/orchestrator-toolkit/README.md), [orchestration setup](src/tools/orchestration_setup/README.md) |
| Graph, nodes and protocols | [architecture](docs/architecture.md), [node contract](src/nodes/node-contract.md), [node template](src/nodes/NODE_TEMPLATE.md) |
| Typed schemas | [schema contract](src/agent/schemas/schema-contract.md) |
| Literature review and paper resolver | [literature review node](src/nodes/ml_literature_review/ml_literature_review.md), [paper resolver skill](src/agent/skills/paper_resolver_skill/paper_resolver_skill.md) |
| Task composition and manifests | [task composition reference](docs/reference/task-composition.md), [composition mechanism](docs/agent-reference/mechanisms/composition.md), [define a task](docs/guides/define-a-task.md) |
| Data path and scope | [data-path and scope](docs/agent-reference/mechanisms/data-path-and-scope.md) |
| Metrics | [metric mechanism](docs/agent-reference/mechanisms/metrics.md) |
| Health checks and validity | [Health contract](src/execute_tools/health_checks/health-contract.md), [Health mechanism](docs/agent-reference/mechanisms/health-gates.md) |
| Training objectives and diagnosis | [training mechanism](docs/agent-reference/mechanisms/training-objective-and-diagnosis.md), [model contract](src/ml_models/model-contract.md) |
| Data analysis agent | [data analysis node](src/nodes/data_analysis_agent/data_analysis_agent.md) |
| Execution, sandbox and resource control | [execution mechanism](docs/agent-reference/mechanisms/execution.md), [execution contract](src/execute_tools/execution-contract.md), [core contract](src/core/core-contract.md), [workspace sandbox](src/tools/workspace_sandbox/README.md) |
| Plugins | [plugin mechanism](docs/agent-reference/mechanisms/plugins.md) |
| Persistence, run invariants and resume | [persistence mechanism](docs/agent-reference/mechanisms/persistence-and-resume.md), [workspace guide](docs/guides/workspaces-and-resume.md) |
| Run report and runtime replay | [run report README](src/tools/run_report/README.md), [runtime replay](docs/reference/runtime-replay.md) |
| Dashboard and run monitoring | [dashboard guide](docs/guides/dashboard.md), [operating a run](docs/guides/operating-a-run.md) |
| Candidate console (browser GUI) | [console contract](src/tools/candidate_console/console-contract.md) |
| Candidate preparation, operations and worker | [prepare contract](src/tools/candidate_prepare/candidate-prepare-contract.md), [operations contract](src/tools/candidate_operations/candidate-operations-contract.md), [worker contract](src/tools/candidate_worker/candidate-worker-contract.md) |
| Setup review | [setup review](src/tools/setup_review/README.md), [setup skill](docs/agent-reference/siderius-setup-review/SKILL.md) |
| Examples and Quickstart | [examples](examples/README.md) |
| LLM routing and providers | [agent contract](src/agent/agent-contract.md), [transport contract](src/agent/llm_transport/transport-contract.md), [LLM defaults](docs/reference/llm-defaults.md) |
| Credentials: which entry point reads keys from where | [API keys](docs/getting-started/installation.md#api-keys) |
| Configuration ownership | [configuration map](docs/reference/configuration-map.md), [configuration contract](configs/configuration-contract.md) |
| CI and testing | [CI contract](docs/testing/ci_parity.md), [CI workflow](.github/workflows/ci.yml), [gate standard](docs/gates/gate_testing_standard.md) |
| Framework / siderius-exp boundary | [external consumer](docs/repository-map.md#external-consumer-and-evidence), [ownership rules](CLAUDE.md#repository-and-scientific-ownership) |

User task setup belongs in the user's external project. Repository contribution
work follows CLAUDE.md. Verify behavior from the selected source revision and
tests before claiming a capability or successful validation.
