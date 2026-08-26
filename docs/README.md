# SIDERIUS documentation

Two audiences, two paths through the same material. Pick yours.

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
- [Supported tasks and current maturity](concepts/supported-tasks.md)
- [Glossary](concepts/glossary.md)

**Bring your own task**
- [Define your own task](guides/define-a-task.md)
- [Task composition reference](reference/task-composition.md) — required vs optional
- [Configuration map](reference/configuration-map.md) — who owns which file

**Operate it**
- [Operating a run](guides/operating-a-run.md) — scope, budgets, resume, refusals
- [Workspaces and resume](guides/workspaces-and-resume.md) — what is in the run directory, fresh vs resume
- [Entrypoints and CLI](reference/entrypoints.md)
- [Troubleshooting](guides/troubleshooting.md) — symptom-first diagnosis
- [Browsing results with the dashboard](guides/dashboard.md)

## For coding agents and framework developers

- **[Agent reference](agent-reference/README.md)** — start here. Maps an intent
  to the 1–3 documents that let you work safely.
- [Architecture](architecture.md) — the graph, node contract, protocols, skills,
  testing strategy
- [`CLAUDE.md`](../CLAUDE.md) — binding coding standards and subsystem invariants
- [`nodes/NODE_TEMPLATE.md`](../nodes/NODE_TEMPLATE.md) — the eight-step contract
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
[`workflows/`](../workflows/README.md) · [`core/`](../core/README.md) ·
[`execute_tools/`](../execute_tools/README.md) ·
[`execute_tools/health_checks/`](../execute_tools/health_checks/README.md) ·
[`ml_models/`](../ml_models/README.md) ·
[`agent/schemas/`](../agent/schemas/README.md).
Point-in-time UX audit:
[dashboard first-run UX](agent-reference/dashboard_ux_audit.md).

Node contracts:
[interpreter](../nodes/result_interpretation_agent/result_interpretation_agent.md) ·
[literature review](../nodes/ml_literature_review/ml_literature_review.md) ·
[proposer](../nodes/ml_model_proposal_agent/ml_model_proposal_agent.md) ·
[implementor](../nodes/ml_model_implementor/ml_model_implementor.md) ·
[validator](../nodes/ml_code_validator_agent/ml_code_validator_agent.md) ·
[tuner](../nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md)

## Example task packages

[TIDMAD](../examples/tidmad/README.md) ·
[Oxford-IIIT Pet](../examples/oxford_iiit_pet/README.md) ·
[DAVIS 2017](../examples/davis_future_prediction/README.md)

Each carries a `STATUS.md` declaring its maturity and a `PROVENANCE.md`
recording its dataset source and licence.

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
| [`docs/audit/documentation_gap_audit.md`](audit/documentation_gap_audit.md) | the source-grounded audit this documentation system was built from |
| [`docs/audit/unit_tests_rubric_audit.md`](audit/unit_tests_rubric_audit.md) | ⚠ point-in-time unit-test rubric audit (2026-05-25) |
| [`docs/development/claude_context_continuity.md`](development/claude_context_continuity.md) | how a coding session survives context compaction |
| [`docs/testing/schema_tier_consolidation.md`](testing/schema_tier_consolidation.md) | evidence record for a schema-test consolidation |
| [`tests/pseudo_data/README.md`](../tests/pseudo_data/README.md) | pseudo-mode fixtures for dual-mode tests |
| [`dashboard/README.md`](../dashboard/README.md) | the result browser |
| [`advice/README.md`](../advice/README.md) | human advice JSON schema and injection points |
| [`sdsc_submission_scripts/README.md`](../sdsc_submission_scripts/README.md) | chain launcher internals |
| [`reports/`](../reports/) | frozen point-in-time run reports |

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
