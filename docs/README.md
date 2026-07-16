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
| `docs/adaptive_new_model_proposer.md` | Adaptive New Model Proposer | active | mixed | Cumulative negative feedback for proposer (`disallowed_architectural_patterns`) |
| `docs/adaptive_new_model_proposer_overall_review.md` | Overall review of adaptive proposer | archived | mixed | Historical review notes |
| `docs/adaptive_new_model_proposer_phase_C_review.md` | Phase C review | archived | mixed | Historical review notes |
| `docs/aggregated_score_table_awareness.md` | Aggregated score-table awareness | active | mixed | Score-table rendering for LLM prompts |
| `docs/align_denoising_score.md` | Align denoising score | active | task-specific | Canonical scoring formula (anchor-normalized) + legacy parity proof |
| `docs/audit_and_optimize_token_usage_and_growth.md` | Token-usage audit | active | generic | Token-consumption profile per agent + growth analysis |
| `docs/break_tuner_agent.md` | Planner/reflector split | active | generic | Tuner LLM cost-splitting design |
| `docs/chain_skip_unproductive_iters_design.md` | Chain skip unproductive iters | active | generic | Delta-based skip-formal / bypass-time-budget gates |
| `docs/checkpoint_l_sign_off.md` | Checkpoint L sign-off | archived | mixed | Loss inventory (L1–L6) Gate 2 + Gate 3 sign-off |
| `docs/checkpoint_t_sign_off.md` | Checkpoint T sign-off | archived | mixed | Task config (T1–T4) sign-off |
| `docs/commit_plan_ml_literature_review.md` | Lit-review commit plan | active | mixed | Execution log for the ml_literature_review node |
| `docs/Consistent_growing_vocab_list.md` | Consistent growing vocab | active | generic | Cross-iteration knowledge accumulation (vocab, findings, cache, negatives, previous proposal) |
| `docs/dynamic_search_pilot.md` | Dynamic search pilot | active | generic | Multi-round paper search loop for the lit-review node |
| `docs/external_agents_architecture.md` | External agents architecture | active | generic | Vision doc for external-agent interoperability |
| `docs/external_agents_for_proposer.md` | External agents for proposer | active | generic | Delegating proposer decisions to external agent implementations |
| `docs/first_model_proposal_demo_architecture.md` | First model-proposal demo | archived | generic | Historical demo architecture |
| `docs/full_loop_5_agents.md` | Full loop with 5 agents | active | generic | End-to-end loop across proposer / implementor / validator / tuner / interpreter |
| `docs/hyperparameter_tuner_features.md` | Tuner prompt features | active | generic | Tuner prompt affordances and constraints |
| `docs/improving_validation_awareness.md` | Improving validation awareness | active | generic | Validator improvements (7-check pipeline) |
| `docs/learning_from_sota_agents.md` | Learning from SOTA agents | active | generic | Cross-project comparison notes |
| `docs/optimize_inference_and_scoring.md` | Optimize inference + scoring | active | mixed | Fix-1 (RSS ceiling), Fix-2 (subprocess spawn), Fix-3 (sentinel) — historical hardening |
| `docs/paper_extract_pilot.md` | Paper extract pilot | active | generic | Lit-review compression pilot |
| `docs/paper_resolver_pilot.md` | Paper resolver pilot | active | generic | Semantic Scholar + arXiv resolver pilot |
| `docs/phase66_deterministic_vram_and_hardening.md` | Phase 6.6 hardening | archived | generic | Historical hardening pass |
| `docs/phase66_ws_a_refactor_and_cleanup.md` | Phase 6.6 workstream A | archived | generic | Historical refactor notes |
| `docs/phase66_ws_b_proposer_hardening.md` | Phase 6.6 workstream B | archived | generic | Historical proposer hardening |
| `docs/phase67_infra_hardening_and_feedback_integrity.md` | Phase 6.7 infra hardening | archived | generic | Historical Phase 6.7 |
| `docs/phase68_orchestrator_memory_and_resume.md` | Phase 6.8 memory + resume | archived | generic | Orchestrator memory hygiene + resume design |
| `docs/phase68_task1_memory_diagnostic_20260427.md` | Phase 6.8 memory diagnostic | archived | generic | Diagnostic report dated 2026-04-27 |
| `docs/pr_description_loss_inventory.md` | PR description — loss inventory | archived | generic | Historical PR write-up |
| `docs/proposer_prompt_audit.md` | Proposer prompt audit | active | generic | Audit of proposer prompt structure |
| `docs/pseudo_test_infra.md` | Pseudo test infra | active | generic | Dual-mode pseudo/real integration test design |
| `docs/refactor_formal_round_strategy.md` | Formal round strategy | active | generic | Strategy-based formal-round dispatch |
| `docs/refactor_llm_bridge.md` | LLM Bridge refactor | active | generic | LLMBridge design + retry policy |
| `docs/refine_inference_time_estimator.md` | Inference time estimator | active | generic | Inference-time gate / estimator refinement |
| `docs/reliable_resource_proposer.md` | Reliable resource proposer | active | generic | VRAM/RSS budget-aware proposal design |
| `docs/resource_estimator_implement.md` | Resource estimator impl | active | generic | Formal-round eval scope (Phase R) |
| `docs/running_chain_test.md` | Chain runbook | active | mixed | Operational runbook for lilab + SDSC chain runs |
| `docs/run_scoped_plugins.md` | Run-scoped plugins | active | generic | Per-run plugin isolation |
| `docs/search_quality_validation.md` | Search quality validation | active | generic | Checkpoint S sign-off for lit-review search |
| `docs/small_sample_trial_dependencies_improve.md` | Small sample trial deps | active | mixed | Trial-mode dependency improvements |
| `docs/small_sample_trial.md` | Small sample trial | active | mixed | Multi-fidelity trial/formal mode |
| `docs/soft_edge_for_all_nodes.md` | Soft edge for all nodes | active | generic | Graph edge soft-error handling |
| `docs/training_scale.md` | Training scale | active | task-specific | TIDMAD training data scale analysis |
| `docs/trial_epoch_default.md` | Trial epoch default | active | mixed | Rationale for `--max_epochs 1` trial default |
| `docs/V8_Gap_Report.md` | V8 Gap Report | archived | mixed | Historical v8 gap analysis |
| `docs/validation_suite_runs.md` | Validation suite runs | active | generic | Validator suite documentation |

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
