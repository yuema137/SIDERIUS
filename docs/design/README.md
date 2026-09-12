# Design and decision history

**This is an archive, not a manual.**

These documents record *how and why* SIDERIUS became what it is: audited designs,
frozen decisions, per-commit ledgers, gate evidence and operator rulings. They are
kept because the rationale and the evidence are genuinely valuable — a future
change that re-breaks a rule should be able to find out why the rule exists.

They are **not** a description of current behaviour. A design document is evidence
of *intent*; landed source and its tests are evidence of *capability*. Several
documents here describe work that is frozen but not implemented, and a few
describe intent that was later amended.

**For how the framework works today, start at
[`docs/README.md`](../README.md).**

---

## How the archive is organised

### The generic framework upgrade

`generic_framework_upgrade/` — the campaign that reshaped SIDERIUS from a
TIDMAD-only system into a task-generic framework. The roadmap
[`siderius_generic_framework_upgrade.md`](siderius_generic_framework_upgrade.md)
is the parent; each step has a design document and, where a step was decomposed,
a subdirectory of child-PR designs whose `§` ledgers record what actually landed.

| step | subject |
|---|---|
| 00 | golden baseline harness |
| 01 | proposer hypothesis space and prompt surfaces |
| 02 | dataset sample topology |
| 03 | model / loss contract |
| 04 | candidate creation mechanics |
| 05a–05c | tuner data selection, resource/time, execution contracts |
| 06 | evaluation metric interface |
| 07 | tuner policy and training diagnostics |
| 08 | health check task profile |
| 09 | interpretation task blocks |
| 09.5 | structural and test-topology audit |
| 10 | orchestration and task binding |
| 11 | execution infrastructure |
| 12 | external extensibility graduation |
| D14 | executable data path (three tasks, one execution architecture) |

The following milestone statement is a historical snapshot from the design
freeze, not a current implementation status: Steps 00–11 were recorded as
complete and merged, while Step 12's first two children had merged and two
remained open at that time. For current support, check Git and
[supported tasks and current maturity](../concepts/supported-tasks.md) for what
that means in practice, and verify any status claim against git rather than
against a document's header.

### Priority campaigns

`v17_priorities.md`, `v18_priorities.md`, `v19_priorities/`, `v20_priorities/`,
`v21_priorities/` — release-scoped work planning, each with per-PR designs. Older
campaigns are largely historical.

### Standalone subsystem designs

| document | subject |
|---|---|
| [`pluggable_health_checks.md`](pluggable_health_checks.md) | the HealthGate framework |
| [`collapse_detection_framework_generic.md`](collapse_detection_framework_generic.md) | task-agnostic collapse detection |
| [`enable_partial_file_list.md`](enable_partial_file_list.md) | DataScope — partial-file runs |
| [`enable_global_task_config.md`](enable_global_task_config.md) | de-hardcoding task description / forward contract |
| [`enable_loss_inventory.md`](enable_loss_inventory.md) | custom loss plugins |
| [`runtime_estimation_and_watchdog.md`](runtime_estimation_and_watchdog.md) | runtime prediction and the watchdog |
| [`runtime_estimation_and_calibration.md`](runtime_estimation_and_calibration.md) | calibration data model |
| [`agent_composition_architecture.md`](agent_composition_architecture.md) | the node / protocol / orchestrator layering |
| [`genericity_contract.md`](genericity_contract.md) | the genericity seams |
| [`tidmad_coupling_ledger.md`](tidmad_coupling_ledger.md) | where TIDMAD assumptions lived |
| [`pruning_test_rule.md`](pruning_test_rule.md) | the test-ownership rules |
| [`framework_experiment_repository_separation.md`](framework_experiment_repository_separation.md) | historical decisions/evidence and a local-only P0 ledger for separating generic framework infrastructure from caller-owned tasks and campaigns |

### Task-specific analysis

[`tidmad_collapse_advice_and_forensics.md`](tidmad_collapse_advice_and_forensics.md),
[`paper_and_collapse_reference_baselines.md`](paper_and_collapse_reference_baselines.md)
— TIDMAD-specific empirical work. Useful as method; not generalisable as content.

## Reading an archived design safely

1. **Check its status header, then check git.** A header saying "FROZEN" means the
   design is settled, not that it is implemented.
2. **Prefer the ledger section.** Most child-PR designs end with a per-commit
   checklist recording what landed and what evidence supported it. That section
   is the most reliable part of the document.
3. **Never take a current-behaviour claim from prose.** Confirm against source.
4. **Amendments live in the parent.** Where a child's scope was reduced or a
   decision reversed, the parent design and the roadmap carry the amendment; the
   child may still read as originally frozen.

## Conventions in these documents

- `Q-xx-n` — an operator question, and its frozen answer
- `F-xx-n` — a finding, usually a defect discovered during implementation
- `§` references — sections within the same or a named document
- Gate 1 / Gate 2 — real-LLM and real-training acceptance runs; see
  [the gate testing standard](../gates/gate_testing_standard.md)
