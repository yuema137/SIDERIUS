# Generic Framework Upgrade — step design documents

Canonical folder for ALL step-level detailed designs under the FROZEN
overall roadmap (`docs/design/siderius_generic_framework_upgrade.md` —
Revisions 1-3 operator approved 2026-08-11, O1 proposer-first confirmed; Revision 4 — §0 rule 10, §20, §21 — READY FOR OPERATOR FREEZE as of 2026-08-15; **Revision 5 — §22 persistent contrast tracks, lifecycle semantics (computation × role × cadence), required train/validation histories + one golden metric, information-flow governance, maturity ladder, per-Step support matrix, multi-track Gate corpus — DRAFTED 2026-08-15; operator review accepted the architecture and required four clarifications, applied as Rev 5.1 (R3 unconditional for fully supported tasks; Step 07/09 consumer-split ownership; secondary metrics in the loop as evidence; dataset selection BLOCKS the Step-07 design freeze). Rev 5.2 fixed the implementation timeline; the persistent tracks are SELECTED (Pets / DAVIS, §22.9a) and D14 placed after Step 07; Rev 5.3 added persistent example-pack governance (§22.23: three fixed roots examples/tidmad|oxford_iiit_pet|davis_future_prediction, projection not authority, separability, data/workspace lifecycle, maturity mapping, DoD extension) and resolved Q2 (PR0 · 07a · 07b · 07c); adversarial self-review done; **FROZEN — Q4 marked by the operator 2026-08-15** (roadmap §22.21)**).

**Sequence after Step 06 (operator, 2026-08-15):** Rev 5 / 5.1 / 5.2 (roadmap §22, architecture accepted) → **persistent tracks SELECTED: Track B = Oxford-IIIT Pet 37-way RGB classification, Track C = DAVIS 2017 RGB 8→4 future-frame prediction (§22.9a; Fashion-MNIST / Moving-MNIST superseded); D14 = dedicated milestone after Step 07 (Q3 resolved)** → Rev 5.3 (persistent example packs §22.23; Q2 RESOLVED: PR0 · 07a · 07b · 07c) → operator review → **Q4 FINAL Rev-5 freeze** → Step 07 detailed design (PR0 first) → D14 → Step 08 … Any test claiming "Track B/C" must use these exact tasks; example packs advance with track maturity.

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
| 03 | [`step_03_model_loss_contract.md`](./step_03_model_loss_contract.md) | Model / Loss Contract — **COMPLETE — MERGED** (PR #205, final head `a8234b0c`, merge `e1181f61`, 2026-08-14). **ONE PR**, **ONE canonical design doc** — Phase A / Phase B were INTERNAL milestones only and no `step_03_*/` child folder was created. Revision 2 plus **Amendment A-1** (dtype ADMISSIBILITY, approved during implementation after baseline A6 refuted the one-concrete-dtype assumption). Checkpoints 0/A/B/C/D PASS; Gate 1 NOT REQUIRED; Gate 2 PASS (`openai_tiered_pro.json`); exact-head CI green. Delivered: one normalized Model-I/O authority with contract-derived model-boundary dtype and cardinality in production, the existing loss authority re-keyed not duplicated, and TIDMAD compatibility preserved |
| 04 | [`step_04_candidate_creation_mechanics.md`](./step_04_candidate_creation_mechanics.md) (parent) | Candidate Creation Mechanics (+ the §13 remainder this step owns) — **Step 04: COMPLETE — MERGED.** Both children merged (04a `6458dd95`, 04b `096f2dbb`); Checkpoint E complete 2026-08-14. Stays a **LIVE governance document** (not frozen), per the Step-02 multi-PR precedent. Decomposition: **TWO PRs** (order 04a → 04b) |
| 04a | [`step_04_candidate_creation_mechanics/pr_04a_contract_derived_candidate_mechanics.md`](./step_04_candidate_creation_mechanics/pr_04a_contract_derived_candidate_mechanics.md) | Contract-derived candidate mechanics — **COMPLETE — MERGED** (PR #207, merge `6458dd95`, 2026-08-14). Design was frozen at `c3d29e73`; §17 is now the implementation ledger and §17.11 its Checkpoint E |
| 04b | [`step_04_candidate_creation_mechanics/pr_04b_task_description_single_source.md`](./step_04_candidate_creation_mechanics/pr_04b_task_description_single_source.md) | Task description single source — collapsed the byte-duplicate in `configs/lit_review_config.yaml`. Rung 13.4-A (lit-review half). **COMPLETE — MERGED** (PR #209, merge `096f2dbb`, final head `fb044f55`, 2026-08-14). Design was frozen at `4282112a`; §14 is the implementation ledger and §14.8 its Checkpoint E. Static builtin model-description prose deferred — not part of the completed child delivery |
| 05 | *(no parent doc — the three submodule designs jointly form Step 05's acceptance entry)* | **Step 05: COMPLETE — all 3 submodules merged** (05a `cfb3b1c7`, 05b `5ce205d3`, 05c `03e00944`). Three PRs, decomposition re-confirmed from post-Step-04 source. The Step-level completion contract is roadmap §15.1a. **Scoring is still NOT generic** — only its launch plumbing is |
| 05a | [`step_05a_tuner_data_selection.md`](./step_05a_tuner_data_selection.md) | Tuner data selection — run-bound `DatasetProfile` residue closure. **COMPLETE — MERGED** (PR #210, merge `cfb3b1c7`, final head `5ae37180`, 2026-08-14). Design was frozen at `425bfac9`; §19 is the implementation ledger and §19.10 its Checkpoint E |
| 05b | [`step_05b_tuner_resource_time.md`](./step_05b_tuner_resource_time.md) | Tuner resource / time planning — contract-derived probe realization + run-bound `DatasetProfile`. **COMPLETE — MERGED** (PR #211, merge `5ce205d3`, final head `649efda0`, 2026-08-15). Design frozen at `ce880124`; §18 is the implementation ledger and §18.5 its Checkpoint E. Gates 1 and 2 both NOT REQUIRED |
| 05c | [`step_05c_tuner_execution_contracts.md`](./step_05c_tuner_execution_contracts.md) | Tuner execution contracts — provisional `DeliverableSpec` for producer-side naming, cleanup matching, channel identity and persisted storage. **COMPLETE — MERGED** (PR #212, merge `03e00944`, final head `89453177`, 2026-08-15). Design was frozen at `fe73f982`; §15 is the implementation ledger and §15.13 its Checkpoint E. Gate 1 NOT REQUIRED, **Gate 2 PASS**. Deliverable-Contract ownership stays **PROVISIONAL / OPEN** — Step 06 is the next mandatory confirm-or-say-why review |
| 06 | [`step_06_metric_interface.md`](./step_06_metric_interface.md) | Metric interface — **COMPLETE — MERGED** (PR #213, squash `02f382eb`, final head `45b0ff7c`, 2026-08-15). ONE PR; C0-C9 internal checkpoints; ledger §20 (§20.0-§20.11). Delivered: `execute_tools/evaluation_metric.py` (MetricSpec / executable ScoreabilityContract / EvaluationMetric handle / MetricResult, NotScoreableResult), the TIDMAD instance derived under Regime A, both scoring routes (tuner live route via `TidmadSandbox.evaluate_metric`, scoring subprocess) THROUGH the handle with scoreability BEFORE arithmetic, additive record payload `metric_result` / `metric_refusal` (persisted, filtered from planner history — agent-facing rendering is Step 07a/09), frozen TIDMAD values byte-identical, argv unchanged. Q1 CONFIRMED (05c producer representation / 06 evaluation-side acceptance). Operator adversarial review → corrective round (planner filter, strict C6a direction-only rung, ledger); **Gate 1 PASS** (corrective), Gate 2 NOT REQUIRED; exact-head CI green (31904320344). Follow-up debt (§20.11): lexical loss-id rule, mandatory-scalar runtime validator, scalar-only `file_vector=[]` semantics, D1 census completeness, schema→data_paths import chain |
| 07 (PR0, 07a-c) | [`step_07_tuner_policy_and_training_diagnostics.md`](./step_07_tuner_policy_and_training_diagnostics.md) (parent — acceptance / decomposition design) + child [`step_07_tuner_policy_and_training_diagnostics/pr0_persistent_example_baseline.md`](./step_07_tuner_policy_and_training_diagnostics/pr0_persistent_example_baseline.md) (**PR0 FROZEN — operator approved 2026-08-15** (rev 2) after the review: maturity-scoped guards with relaxation owners, `resolved/` read-only snapshots + migration rule, DAVIS sequence-level identity only (clips → D14), no production consumer / CI is the validation consumer, SHA-256 = integrity pin, `tools/example_packs` approved as tooling only; three roots MUST exist, more permitted later; commits C1–C4, Gates none); **PR0 IMPLEMENTED 2026-08-15 — C1–C4 landed on branch `step07-pr0-persistent-example-baseline` (`248a227c` · `c78a148b` · `57031cd1` · `f9398056` + docs sync): `examples/tidmad|oxford_iiit_pet|davis_future_prediction/`, `tools/example_packs/`, `tests/unit/examples/` (61 tests); **MERGED — PR #214, squash `79403b44`, 2026-08-15, exact-head CI 31911929243 SUCCESS; PR0 COMPLETE, next = 07a design**; 07a / 07b / 07c child docs follow one at a time | **FROZEN — operator approved 2026-08-15 (rev 2; Step-level contract frozen; doc stays LIVE for status)**; operator review 2026-08-15 APPROVED decomposition / scope / examples strategy / Gate plan with targeted revisions (applied: parent freezes WHAT + acceptance, children freeze HOW — §20; diagnosis minimum capability, calibrated labels never from curve shape alone; R1 = run-resolved objective; **direction = sole ORDER authority, scale-sensitive policy classified per rule, never assumed generic**; invalidated-result outcome semantics; R2/R3 comparability; render only landed authorities). OD-S7-1..9 disposed (§18). Roadmap §7a/§15.1/§16/§20.2 anchors, Gate wording and child names synced in the same revision. Written against Rev 5.3 @ `03225ac9` (Q4 pending) |
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
