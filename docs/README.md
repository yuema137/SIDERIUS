# SIDERIUS documentation

This is the human route through the documentation. Detailed implementation
contracts have their own gateway below.

[Repository map](repository-map.md): current directories, six nodes, execution
owners, infra/exp entrypoints and evidence boundaries.

---

## For humans

A progressive path. Each level assumes the one before it.

**Understand it** — 5 minutes
- [What SIDERIUS is](concepts/overview.md) — and what it is not

**Run it**
- [Installation](getting-started/installation.md)
- [Your first run](getting-started/first-run.md)

**Understand what it is doing**
- [What a task must provide](concepts/task-package.md)
- [Objectives, metrics, and what "better" means](concepts/objectives-and-metrics.md)
- [Health gates](concepts/health-gates.md) — validity, as distinct from quality
- [Data paths](concepts/data-paths.md) — how a task's data is read, and by whom
- [The execution model](concepts/execution-model.md) — parent, children, and what crosses the boundary
- [Persistence and records](concepts/persistence-and-records.md) — what a run writes and why
- [Plugins and generated code](concepts/plugins-and-generated-code.md) — task code, agent code, and the cross-run library
- [Supported tasks and current maturity](concepts/supported-tasks.md)
- [Glossary](concepts/glossary.md)

**Bring your own task**
- [Define your own task](guides/define-a-task.md)
- [Bring your own metric](guides/bring-your-own-metric.md) — a worked, runnable example
- [Bring your own health checks](guides/bring-your-own-health-checks.md) — a worked, runnable example
- [Bring your own train/test split](guides/bring-your-own-split.md) — split declaration, the scope capability, and the comparability consequences
- [Task composition reference](reference/task-composition.md) — required vs optional
- [Configuration map](reference/configuration-map.md) — who owns which file

**Operate it**
- [Operating a run](guides/operating-a-run.md) — scope, budgets, resume, refusals
- [Workspaces and resume](guides/workspaces-and-resume.md) — what is in the run directory, fresh vs resume
- [Entrypoints and CLI](reference/entrypoints.md)
- [Troubleshooting](guides/troubleshooting.md) — symptom-first diagnosis
- [Browsing results with the dashboard](guides/dashboard.md)

## For framework developers

- **[Agent reference](agent-reference/index.md)** — start here. Maps an intent
  to the 1–3 documents that let you work safely.
- [Architecture](architecture.md) — the graph, node contract, protocols, skills,
  testing strategy
- [`CLAUDE.md`](../CLAUDE.md) — binding coding standards and subsystem invariants
- [`nodes/NODE_TEMPLATE.md`](../src/nodes/NODE_TEMPLATE.md) — the eight-step contract
  for adding a node
- [Gate testing standard](gates/gate_testing_standard.md) — Gate 1 / Gate 2
  commands and pass criteria

Mechanism references, by semantic owner:
[composition](agent-reference/mechanisms/composition.md) ·
[data path and scope](agent-reference/mechanisms/data-path-and-scope.md) ·
[metrics](agent-reference/mechanisms/metrics.md) ·
[training objective and diagnosis](agent-reference/mechanisms/training-objective-and-diagnosis.md) ·
[health gates](agent-reference/mechanisms/health-gates.md) ·
[execution](agent-reference/mechanisms/execution.md) ·
[plugins](agent-reference/mechanisms/plugins.md) ·
[persistence and resume](agent-reference/mechanisms/persistence-and-resume.md)

Module maps (directory-level contracts, one
[template](agent-reference/MODULE_README_TEMPLATE.md)):
[`workflows/`](../src/workflows/README.md) · [`core/`](../src/core/README.md) ·
[`execute_tools/`](../src/execute_tools/README.md) ·
[`execute_tools/health_checks/`](../src/execute_tools/health_checks/README.md) ·
[`ml_models/`](../src/ml_models/README.md) ·
[`agent/schemas/`](../src/agent/schemas/README.md).
Point-in-time UX audit:
[dashboard first-run UX](agent-reference/dashboard_ux_audit.md).

Node contracts:
[interpreter](../src/nodes/result_interpretation_agent/result_interpretation_agent.md) ·
[literature review](../src/nodes/ml_literature_review/ml_literature_review.md) ·
[proposer](../src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.md) ·
[implementor](../src/nodes/ml_model_implementor/ml_model_implementor.md) ·
[validator](../src/nodes/ml_code_validator_agent/ml_code_validator_agent.md) ·
[tuner](../src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md)

## Framework examples

[Quickstart](../examples/quickstart/README.md) and
[synthetic masked regression](../examples/synthetic_masked_regression/README.md)
are the two shipped packages. They specify public framework contracts using
small synthetic inputs, with no scientific-performance claim. Real scientific
tasks and campaigns live in external consumer repositories; see the
[external-consumer map](repository-map.md#external-consumer-and-evidence).

## Design and decision history

[`docs/design/`](design/README.md) records **how and why** the framework evolved:
audited designs, per-commit ledgers, gate evidence and operator decisions.

It is history, not a manual. Current behaviour is described by the documents
above; the archive is where you go for rationale, or when you need to know what
evidence supported a decision. Several of its claims describe intent that has not
landed — read the status markers.

## Other surfaces

| document | topic |
|---|---|
| [`docs/audit/`](audit/README.md) | archived point-in-time audits; evidence, not current behavior |
| [`docs/development/claude_context_continuity.md`](development/claude_context_continuity.md) | how a coding session survives context compaction |
| [`docs/testing/schema_tier_consolidation.md`](testing/schema_tier_consolidation.md) | evidence record for a schema-test consolidation |
| [`tests/pseudo_data/README.md`](../tests/pseudo_data/README.md) | pseudo-mode fixtures for dual-mode tests |
| [`dashboard/README.md`](../src/dashboard/README.md) | the result browser |
| [Human advice guide](guides/advice.md) | human advice JSON schema and injection points |
| [`scripts/launch/README.md`](../scripts/launch/README.md) | chain launcher internals |
| [External reports/ history](https://github.com/Galileo-Sandbox/siderius-exp/tree/e9e5063b/provenance/legacy_siderius/p0_03c1/reports) | frozen point-in-time run reports owned by the experiment repository |

Historical reports are owned by the experiment repository and are not a
framework checkout surface. They are evidence for their named revisions, not
current behavior or reusable task assets.

## Conventions

- **Status markers**: ✅ current · 🟡 partial · 🧭 planned (design frozen) ·
  📝 draft design · ⏳ not implemented · ⚠ legacy / compatibility path.
  Used where maturity ambiguity would otherwise mislead — not on every sentence.
- **Authority**: where a document and the source disagree, the source is right.
  Documents that project a schema or a config say so and name the module.
- **One home per concept.** If you find the same thing explained twice, one of
  them is a bug; link instead of restating.

`docs/memories/` is gitignored — per-developer local notes, not shared
documentation.
