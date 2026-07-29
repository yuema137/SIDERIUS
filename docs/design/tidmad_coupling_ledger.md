# TIDMAD Coupling Ledger

**Status**: living inventory — seeded 2026-07-28 (V19 PR 2, commit A).
**Purpose**: the progress meter for the gradual genericization
(`docs/design/genericity_contract.md`). Every entry is grep-able and marked
`DECOUPLED`, `REMAINING`, `PARTIAL`, or `FROZEN`.

**How to use this file**: when a PR touches a module holding a `REMAINING`
entry, that PR decouples it toward the seam named in the contract and updates
the entry here — in the same commit as the refactor. New coupling discovered
during any work is added here even when it is not decoupled in that PR.

Line numbers are anchors from the seeding audit, not guarantees; re-grep the
pattern if a line has moved.

---

## 1. Filename templates

The dataset filename template is Seam 1 in the contract:
`DatasetConfig.training_file_name(file_index)` /
`DatasetConfig.training_file_pattern`.

| Status | Site | Note |
|---|---|---|
| `DECOUPLED` | `execute_tools/train_engine_sandbox.py` — 4 sites (`TIDMADDataset._pull_events_from_sample_set`, `TIDMADEpochDataset.__init__`, the RT2 storage-provenance path list, the legacy single-file `main()` branch) | V19 PR 2 commit A. Now `TIDMAD.training_file_name(...)`. Guarded by `test_dataset_contract.py::test_training_engine_has_no_inlined_training_filename_literal`. |
| `REMAINING` | `execute_tools/build_anchor_map.py:52` | `f"abra_validation_{file_index:04d}.h5"` — validation side; no `validation_file_name` helper exists yet (adding one before a consumer would be dead code). |
| `REMAINING` | `execute_tools/denoising_score_single.py:139,141,144` | Raw + denoised validation filenames. |
| `REMAINING` | `execute_tools/array2h5.py:25` | `create_abra_file` — TIDMAD vocabulary in a public function NAME, not just a literal. Rename requires updating call sites. |
| `REMAINING` | `scripts/` — 47 `abra_*` literals across `run_comparison.py`, `compute_raw_baseline.py`, `score_tidmad_official_*.py`, `fcnet_*.py`, `investigate_pearson_feasibility.py`, `finalize_recovered_diagnostic_round.py` | Operator/analysis scripts. Lower priority than library code; several are deliberately TIDMAD-specific one-off analyses. |

**Denoised-output naming** (`abra_validation_denoised_{model}_{run}_{exp}_{i:04d}.h5`,
e.g. `scripts/run_comparison.py:445`) is a second, distinct template family —
it names artifacts SIDERIUS produces rather than files it reads. It needs its
own contract decision (does a generic task even produce per-file denoised
HDF5?) before it can be decoupled. Flagged, not scheduled.

---

## 2. Scoring constants and formula

Seam 4 in the contract. **The TIDMAD score formula is a FROZEN exception** —
it stays byte-identical for paper comparability; new metrics plug in beside
it.

| Status | Site | Note |
|---|---|---|
| `FROZEN` | `execute_tools/scoring_helpers.py:36` — `_LOG_BASE = 5.27` | The project-wide log base. |
| `FROZEN` | `execute_tools/scoring_utils.py:655` — `math.log(grand_mean, 5.27)` | Production scalar aggregation. |
| `FROZEN` | `execute_tools/denoising_score_single.py:15`, `scoring_utils.py:17-21,490,532` | Formula prose in docstrings — must track the frozen implementation. |
| `FROZEN` | `scripts/compute_ground_truth.py` — global `s_max` convention (`:53-100`) | The ceiling/ruler definition. |
| `REMAINING` | `execute_tools/per_file_best.py:62` — `LOG_BASE = 5.27` (used at `:362`, `:499`) (V19 PR 1) | A second copy of the same constant. Not a formula change, but a duplicated literal; consolidating to one source is safe and cheap when that module is next touched. |

---

## 3. Dataset-size assumptions (20 files / 200 segments)

| Status | Site | Note |
|---|---|---|
| `PARTIAL` | `execute_tools/dataset_config.py` — `SEGMENT_LENGTH`, `SEGMENTS_PER_FILE`, `NUM_FILES` back-compat module constants | The values live on `DatasetConfig` (good), but are re-exported as bare module constants that consumers import directly — which hardcodes "the one dataset" at every import site. |
| `REMAINING` | `execute_tools/scoring_helpers.py:33,204,266-267,315-316` | `NUM_FILES` used to size per-file arrays. |
| `REMAINING` | `execute_tools/build_anchor_map.py:34-35` | Imports both constants. |
| `REMAINING` | `execute_tools/denoising_score_single.py:159,169` | `SEGMENTS_PER_FILE` builds a full-file sample set. |
| `REMAINING` | `configs/task_config.yaml` "Future extensions" block | Already names `num_files`, `data_dir`, `metric_name` as pending moves to task config — the intended destination for these. |

---

## 4. Task wording in prompts

Seam 3 in the contract. Partially decoupled already: `configs/task_config.yaml`
supplies `task_description` + `forward_contract` to agent system prompts.

| Status | Site | Note |
|---|---|---|
| `PARTIAL` | `configs/task_config.yaml` | Single source for task description + forward contract; injected into implementor, proposer, and lit-review prompts. |
| `REMAINING` | `nodes/scoring_reference.py` | TIDMAD/SQUID wording in scoring reference prose shown to agents. |
| `REMAINING` | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` | Task-specific prose beyond the injected placeholders. |
| `REMAINING` | `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | Same. |

---

## 5. Data-path configuration

| Status | Site | Note |
|---|---|---|
| `REMAINING` | `execute_tools/data_paths.py` — `tidmad_data_config.yaml` | Machine-specific path config named after the dataset. Renaming is cheap but touches deployment docs and both servers' untracked configs; do it with a deployment-touching PR, not opportunistically. |
| `REMAINING` | `execute_tools/train_engine_sandbox.py:779` | CLI help text references `tidmad_data_config.json`. |
| `REMAINING` | `dashboard/settings.py:31` | Same config name in a comment. |

---

## 6. Configuration migration inventory (proposed / override / resolved)

Seam 2 in the contract. **Nothing here is migrated by V19 PR 2** — ordering is
the only implementation. This is the candidate list, with the permissions class
each is EXPECTED to take. The class is confirmed by the PR that migrates it,
not by this table.

| Option | Today | Expected class |
|---|---|---|
| `order_strategy` / `file_order` | **IMPLEMENTED** (V19 PR 2) | agent-settable, operator-overridable, override chain-locked |
| Sampling strategy (`trial_strategy`, `eval_strategy`) | Agent-planned; operator-forced on formal rounds; normalized to `snapshot` under partial scope | agent-settable, operator-overridable |
| `train_portion` / `trial_portion` / `formal_*_portion` | Agent-planned (trial) or operator-set (formal) | agent-settable, operator-overridable |
| Learning rate / optimizer settings | Agent-planned via `train_cfg` | agent-settable, operator-overridable |
| `DataScope` | Operator-only; already chain-locked in `run_invariants_lock.json` | operator-overridable, chain-locked (NOT agent-settable) |
| Resource budgets / watchdog policy | Operator-only | operator-overridable, chain-locked — **not** agent-settable (safety limit) |
| HealthGate policy inputs (`health_gate_enabled`, `health_gate_files`) | Operator-only; chain-locked | operator-overridable, chain-locked — **not** agent-settable (safety limit) |
| Score formula / log base / `s_max` ruler | Hardcoded | **frozen** — never agent- or operator-settable |

---

## Ledger changelog

- **2026-07-28** — seeded (V19 PR 2 commit A). Training filename template
  decoupled; everything else recorded as remaining/partial/frozen.
