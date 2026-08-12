# SIDERIUS Documentation Index

This is the master table of contents for all design docs, gate standards,
reports, and audit docs. Every doc under `docs/` should be listed here.

## How to use this index

- **Status** values: `draft` | `active` | `superseded` | `archived`
- **Scope** values: `generic` | `task-specific` | `mixed`
- Add a row here whenever a new doc is created
- Update `Last Updated` when meaningfully changed (not for typo fixes)
- If Created / Owner is unknown, leave `unknown` — do not guess

## Design docs

Living design documents. If a doc becomes obsolete, mark it `superseded`
and add a link in its "Superseded by" note; do not delete the row.

| Path | Title | Status | Created | Last Updated | Scope | Depends On | Referenced By | Owner | Summary |
|------|-------|--------|---------|--------------|-------|------------|---------------|-------|---------|
| `docs/design/siderius_generic_framework_upgrade.md` | SIDERIUS Generic Framework Upgrade — overall roadmap | FROZEN Rev 3 (operator approved 2026-08-11; O1 confirmed) | 2026-08-10 | 2026-08-11 | generic | genericity_contract, tidmad_coupling_ledger, v17–v21 priorities | docs/design/generic_framework_upgrade/* | operator | Audited module-by-module genericization roadmap: philosophy, per-surface TIDMAD compatibility contract, 15 variation axes, 10 module sections incl. tuner submodule decomposition, convergence ledger, migration order |
| `docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md` | Step 00 — Golden Baseline Harness — detailed design | COMPLETE — merged (PR #198, 2026-08-12) | 2026-08-11 | 2026-08-11 | mixed | siderius_generic_framework_upgrade | (future) all step 01-12 designs | operator | Six-area audited baseline design: taxonomy (6 types), ~35-entry baseline inventory (prompts/config/records/resume/plugins/scorer/choreography), coverage manifest steps 01-12, golden update policy, mutation battery, Checkpoints 0/D/E, OD-1..5 operator decisions |
| `docs/design/generic_framework_upgrade/step_01_proposer_hypothesis_space.md` | Step 01 — 6-P Proposer Hypothesis Space & Prompt Surfaces — detailed design | ready for operator review (design only; OD-S1-1..8 pending) | 2026-08-12 | 2026-08-12 | mixed | siderius_generic_framework_upgrade, step_00_golden_baseline_harness | (future) step 02-04 designs | operator | Audited 6-P design: production proposer flow + legacy reachability, TIDMAD coupling inventory, authority/ownership map, rank-agnostic flexible-input boundary (§6A: capability matrix, Mode A/B presets, Outcome B fail-closed), ONE-PR decision, Stage-A Step-00 baseline map, atomic contrasts, test-disposition table, per-commit checklists, two adversarial review records |
| `docs/design/v17_priorities.md` | V17 Priority Decisions | active | 2026-07-14 | 2026-07-16 | mixed | — | many | TBD | MUST / SHOULD / DEFER classification for v17 launch; M1/M4 DROPPED, M6 DONE, M8 ADDED (see execution plans) |
| `docs/design/pluggable_health_checks.md` | Pluggable Health Checks | active | unknown | 2026-07-15 | generic | — | v17_priorities, collapse_detection_framework_generic | TBD | HealthGate framework design (rev-6 migration, PR #101); §16 backlog table |
| `docs/design/collapse_detection_framework_generic.md` | Collapse Detection Framework (Generic) | active | 2026-07-15 | 2026-07-16 | generic | pluggable_health_checks | tidmad_collapse_advice_and_forensics, structured_feedback_loop_experiment_to_proposer | TBD | Task-agnostic collapse-detection mechanisms and acceptance criteria for framework purity |
| `docs/design/structured_feedback_loop_experiment_to_proposer.md` | Structured Feedback Loop (Experiment → Proposer) | active | 2026-07-15 | 2026-07-16 | generic | pluggable_health_checks | tidmad_collapse_advice_and_forensics | TBD | Signal flow from ExperimentRecord through ModelRunSummary to Interpreter to Proposer; drop-point trace and target contract |
| `docs/design/tidmad_collapse_advice_and_forensics.md` | TIDMAD Collapse — Advice and Forensics | active | 2026-07-15 | 2026-07-16 | task-specific | collapse_detection_framework_generic, structured_feedback_loop_experiment_to_proposer | — | TBD | TIDMAD-specific phantom fingerprints (5.5763, 6.3556), loss-collapse tendencies, model regime advice, open forensic items |
| `docs/design/m7_loss_implementor_contract_execution_plan.md` | M7 — Loss-Implementor Contract Fix — Execution Plan | draft | 2026-07-16 | 2026-07-16 | generic | (bug fix, no single parent design) | v17_priorities | TBD | Execution roadmap for M7 (issue #112): investigation-first bug-fix shape with 3 options, real-run Gate-2-without-workaround validation |
| `docs/design/m8_gate_coverage_and_diversity_metrics_execution_plan.md` | M8 — Complete Gate Coverage + Output-Diversity Metrics — Execution Plan | draft | 2026-07-16 | 2026-07-16 | mixed | collapse_detection_framework_generic, tidmad_collapse_advice_and_forensics, paper_and_collapse_reference_baselines | v17_priorities | TBD | Execution roadmap for M8 (issue #118): every-round gate coverage, new OutputStdCheck, three recording-only checks; supersedes M1 (#108, dropped) and M4 (#109, dropped) |
| `docs/design/paper_and_collapse_reference_baselines.md` | Paper-Quality vs Collapse Reference Baselines | active | 2026-07-16 | 2026-07-16 | task-specific | m8_gate_coverage_and_diversity_metrics_execution_plan, tidmad_collapse_advice_and_forensics | m8, m9, tidmad_collapse_advice | TBD | Three-way per-file scan (FCNet real learning / paper-spec baseline collapse / agent_012 near-constant phantom) across all 20 TIDMAD files; empirical basis for M8 thresholds; canonical FCNet reference data location; §6.4 records M9 peek strategy decision |
| `docs/design/m9_multi_file_peek_execution_plan.md` | M9 — Multi-File Peek (Strategy C) — Execution Plan | active | 2026-07-16 | 2026-07-16 | mixed | collapse_detection_framework_generic, paper_and_collapse_reference_baselines, m8_gate_coverage_and_diversity_metrics_execution_plan | v17_priorities | TBD | Execution roadmap for M9: shared `_multi_file_peek` helper + 3-way blocking check refactor + YAML `peek_file_indices` + `aggregation` per gate; supersedes M8's single-file peek |
| `docs/design/agent_composition_architecture.md` | Agent Composition Architecture | active | 2026-06-29 | unknown | generic | — | v17_priorities | TBD | Three-layer node/protocol/orchestrator design; Run Monitor vision (issue #100); v15/v16 incident log |
| `docs/design/enable_global_task_config.md` | Enable Global Task Config | active | unknown | unknown | generic | — | many prompt templates | TBD | Design for `configs/task_config.yaml` de-hardcoding across implementor / proposer / tuner / lit-review (T1–T4) |
| `docs/design/enable_loss_inventory.md` | Enable Loss Inventory | active | unknown | unknown | generic | — | issue #112 | TBD | Custom-loss plugin proposal + generation + registry contract (L1–L6) |

## Top-level `docs/` — non-design docs

Reference docs, runbooks, subsystem specs, and specific-feature designs
that live outside `docs/design/`.

| Path | Title / Topic | Status | Scope | Summary |
|------|---------------|--------|-------|---------|
| `docs/architecture.md` | Architecture overview | active | generic | Full system design (graph, nodes, protocols, skills) — canonical entry point for new contributors |

## Gate standards

| Path | Title | Status | Created | Last Updated | Scope | Summary |
|------|-------|--------|---------|--------------|-------|---------|
| `docs/gates/gate_testing_standard.md` | Gate Testing Standard | active | unknown | 2026-07-15 | generic | Canonical Gate 1 / Gate 2 / Gate 3 commands and pass criteria (Gate 2 updated to 5-criterion HealthGate scope on 2026-07-15) |

## Audit docs

| Path | Title | Status | Scope | Summary |
|------|-------|--------|-------|---------|
| `docs/audit/unit_tests_rubric_audit.md` | Unit tests rubric audit | active | generic | Per-test-file inventory of what's covered, gaps, and rubric alignment |

## Memories

`docs/memories/` holds shared, version-controlled per-project memory
snapshots. These are pointers auto-loaded via
`docs/memories/README.md`. Not design documents — do NOT extend the
design-doc table with these.

| Path | Purpose |
|------|---------|
| `docs/memories/README.md` | Index for shared memories |
| `docs/memories/feedback_design_first.md` | Design-doc-first workflow preference |
| `docs/memories/project_formal_strategy_refactor.md` | Formal-round strategy refactor context |
| `docs/memories/project_gemini_quota_split.md` | Gemini quota + planner/reflector split |
| `docs/memories/project_phase3b_validation_report.md` | Phase 3b validation report |
| `docs/memories/project_run_comparison_lies_about_gpu.md` | run_comparison.py GPU-name lie |
| `docs/memories/project_sdsc_chain_afterany.md` | SDSC chain afterany+48G |
| `docs/memories/reference_sdsc_workspace_paths.md` | SDSC workspace paths reference |

## Reports

Historical run reports. **Reports are typically `archived` status** —
they document a point-in-time run and are not updated afterward.

| Path | Date | Summary |
|------|------|---------|
| `reports/v4_pr61_20260425_222622.md` | 2026-04-25 | v4 run report |
| `reports/v5_pr62_20260427_110747.md` | 2026-04-27 | v5 run — Phase 6.7 fixes shipped; HOST_OOM emerged as new failure mode |
| `reports/v6_pr63_20260428.md` | 2026-04-28 | v6 run report |
| `reports/v9_20260502.md` | 2026-05-02 | v9 run report |
| `reports/v11_20250503_token_usage.md` | 2026-05-03 | v11 token-usage report |
| `reports/v12_20260504.md` | 2026-05-04 | v12 run report |
| `reports/v12_token_baseline.md` | 2026-05 | v12 token baseline analysis |
| `reports/v12_top3_bloat.md` | 2026-05 | v12 top-3 bloat sources |
| `reports/v15_20260628.md` | 2026-06-28 | v15 exploration chain report; §6 contains the ghost-score forensic investigation (5.5763 + 6.3556 clusters) |
| `reports/v16_20260630.md` | 2026-06-30 | v16 exploration chain report; §9 documents Gate 2 arch-chain ghost-score reappearance |
| `reports/phase68_sdsc_chain_evaluation_20260427.md` | 2026-04-27 | Phase 6.8 SDSC chain evaluation |

## Dependency notes

- `v17_priorities.md` is the current planning document; every open v17
  work item traces back to an M / S / D entry there
- `pluggable_health_checks.md` is the HealthGate framework design;
  `collapse_detection_framework_generic.md` extends it with the
  generic-detection perspective
- Task-specific advice content lives in `advice/workflow/*.json` (not
  tracked here — advice is data, not design)
- Reports under `reports/` are frozen point-in-time artifacts (not
  updated after publication)
- Design docs under `docs/design/` are living; docs under `docs/`
  top-level are a mix of design docs, reference docs, and archived
  historical notes

## Coverage caveats

- **Created** and **Owner** fields are filled with `unknown` for docs
  that predate this index. When authoring a new doc, set both.
- **Last Updated** is best-effort — the source of truth is git blame on
  the file. Use this column as a hint for "when was this last
  materially edited", not as authoritative metadata.
- `docs/memories/*.md` files are pointers into the shared memory
  system; they are not design docs and are listed separately.
