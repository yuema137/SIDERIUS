# Generic Framework Upgrade — step design documents

Canonical folder for ALL step-level detailed designs under the FROZEN
overall roadmap (`docs/design/siderius_generic_framework_upgrade.md` —
operator approved 2026-08-11; O1 proposer-first confirmed).

**This README is an INDEX plus a one-line mirror of the overall
roadmap's status. It is NEVER an independent progress tracker — the
roadmap's §15.1 completion-contract matrix is the single status
authority.**

Naming convention (operator-frozen, 2026-08-11):
`step_<two-digit-step-number>_<roadmap-step-name>.md` — one canonical
step-level document per roadmap step; subordinate `step_NNa_*` names
where a step genuinely comprises multiple submodule designs (steps 5
and 7), jointly constituting that step's acceptance entry.

| Step | Document | Status (mirror of §15.1) |
|---|---|---|
| 00 | [`step_00_golden_baseline_harness.md`](./step_00_golden_baseline_harness.md) | COMPLETE — merged (PR #198, 2026-08-12) |
| 01 | [`step_01_proposer_hypothesis_space.md`](./step_01_proposer_hypothesis_space.md) (parent) | **COMPLETE** — FROZEN (OD-S1-5); both children merged (01a → PR #199, 01b → PR #201) |
| 01a | [`step_01_proposer_hypothesis_space/pr_01a_contract_derived_prompt_extraction.md`](./step_01_proposer_hypothesis_space/pr_01a_contract_derived_prompt_extraction.md) | **COMPLETE — merged (PR #199, 2026-08-12, merge commit `39f89f52`)** |
| 01b | [`step_01_proposer_hypothesis_space/pr_01b_task_description_join.md`](./step_01_proposer_hypothesis_space/pr_01b_task_description_join.md) | intentional task-description JOIN — **COMPLETE — merged (PR #201, 2026-08-13, merge commit `fe05f5f7`)**. CP1/CP2/CP3, Checkpoint C, Gate 1 and Gate 2 all PASS; terminal suite green; exact-head CI green |
| 02 | [`step_02_dataset_sample_topology.md`](./step_02_dataset_sample_topology.md) (parent) | **Step 02 — COMPLETE.** All three children MERGED in the order 02a → 02b → 02c. Step-level terminal suite and the ONE Gate 2 both PASS; Checkpoints 0/A/B/C/D/E complete. The parent stays the LIVE governance/status authority |
| 02a | [`step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md`](./step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md) | Dataset Profile injection (topology · geometry+legality · encoding · channel identity) — **COMPLETE / MERGED** (PR #202, merge `47359538`). Now an immutable implementation ledger |
| 02b | [`step_02_dataset_sample_topology/pr_02b_selection_sampleset.md`](./step_02_dataset_sample_topology/pr_02b_selection_sampleset.md) | Selection & SampleSet semantics — **COMPLETE / MERGED** (PR #203, merge `c17469ec`). Now an immutable implementation ledger |
| 02c | [`step_02_dataset_sample_topology/pr_02c_systematic_groups.md`](./step_02_dataset_sample_topology/pr_02c_systematic_groups.md) | **Task-owned file-set semantics** (renamed from "systematic groups" at revision 3; filename kept to preserve links from the merged 02a/02b ledgers) + Step FINALIZER — the 4.8-C rung, the one Step-level Gate 2, Checkpoint E. **MERGED** — PR #204, merge `1807054b`. Design frozen at `0fbe3556`; §24 is the implementation ledger. Final contract: anchor-selection DECLARED · health-peek DECLARED · all-files DERIVED from topology |
| 03 | [`step_03_model_loss_contract.md`](./step_03_model_loss_contract.md) | Model / Loss Contract — **DESIGN DRAFTED, READY FOR OPERATOR REVIEW (not frozen)**. Two proposed children: 03a normalized model-I/O contract + presets + fail-closed consistency (inherits FX-3/FX-4 from D13); 03b contract-keyed dtype routing + class-count derivation |
| 04 | `step_04_candidate_creation_mechanics.md` | not created |
| 05a-c | `step_05a_tuner_data_selection.md`, `step_05b_tuner_resource_time.md`, `step_05c_tuner_execution_contracts.md` | not created |
| 06 | `step_06_metric_interface.md` | not created |
| 07a-b | `step_07a_tuner_policy.md`, `step_07b_tuner_measurement.md` | not created |
| 08 | `step_08_health_check_task_profile.md` | not created |
| 09 | `step_09_interpretation_task_blocks.md` | not created |
| 10 | `step_10_orchestration_task_binding.md` | not created |
| 11 | `step_11_execution_infrastructure.md` | not created |
| 12 | `step_12_task_composition_binding.md` | not created |

## Step design kickoff protocol (operator-frozen, 2026-08-12)

Every step design follows:

```text
frozen overall roadmap review
  -> prerequisite design/evidence review
  -> preliminary PR-decomposition hypothesis
  -> focused source audit for the step
  -> source-grounded FINAL one-PR vs multi-PR decision
  -> parent (+ child PR) detailed designs
  -> adversarial review
  -> operator review / design freeze
  -> implementation only after prerequisite merges + authorization
```

The PR split is never frozen before the source audit. Default:
one step = one PR. **One PR = one design doc**: when one PR suffices,
the parent `step_NN_<name>.md` IS the PR doc; a real multi-PR split
adds `step_NN_<name>/pr_NNa_<unit>.md` children, each owning one
independently mergeable behavioral outcome. Per-PR docs carry the
operator's per-commit 8-section checklists ([ ]/[x]).
