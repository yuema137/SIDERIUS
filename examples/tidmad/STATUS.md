# STATUS — `tidmad` (honest maturity; MIRROR of roadmap §15.1 / §22.12)

The roadmap (`docs/design/siderius_generic_framework_upgrade.md`) is the ONE
status authority; this file mirrors it for a reader of the pack.

## Maturity: **production-backed resolved projection** (Track A is executed by production at L4 through the existing operator surface; this PACK projects L0/L1 read-only)

| projected in this pack (PR0) | how | verified by |
|---|---|---|
| `DatasetProfile` | `resolved/dataset_profile.json` — GENERATED, DO NOT EDIT | `tests/unit/examples/test_tidmad_projection.py` (deep-compare vs `resolve_dataset_profile()`) |
| `ModelIOContract` | `resolved/model_io_contract.json` — GENERATED | deep-compare vs `run_bound_model_io_contract()`; class axis fixed 256 pinned |
| `DeliverableSpec` | `resolved/deliverable_spec.json` — GENERATED | deep-compare vs `derive_tidmad_deliverable_spec()` |
| `MetricSpec` (golden metric) | `resolved/metric_spec.json` — GENERATED | deep-compare vs `derive_tidmad_metric_spec()`; `id == tidmad_denoising_score`, `direction == higher` pinned as literals |
| identity (file indices + file families) | `resolved/identity.json` — GENERATED | deep-compare |
| task description / forward contract | REFERENCE to `configs/task_config.yaml` | README cites the owning path |
| health policy | REFERENCE to `configs/health_checks.yaml` | README cites the owning path |
| data root | REFERENCE to the `tidmad_data_config.yaml` mechanism | `data/README.md` |
| run entrypoint (Step 12 / PR-12e) | `quickstart.sh` — a thin adapter that supplies `configs/task_composition/tidmad.yaml` plus a bounded posture and then executes `sdsc_submission_scripts/run_chain.sh`; it contains no framework code | `tests/unit/examples/test_step12_pr12e_tidmad_quickstart.py` |

**Nothing under `examples/tidmad/` is an authoring surface: the runtime does
not read these snapshots as a task authority.** They are generated
projections, and editing one changes nothing you want changed (design §3.6).
The one nuance: the shipped composition manifest
`configs/task_composition/tidmad.yaml` binds `resolved/dataset_profile.json`
and `resolved/metric_spec.json` as declaration references, so a composed run
does load those two — which is exactly why a hand edit is caught as a red
test rather than being harmless.

## NOT projected here (and who owns it)

| seam | status | owner |
|---|---|---|
| task-owned data preparation | not projected — TIDMAD's acquisition is owned by the paper's own repository, and this pack ships no fetcher (`PROVENANCE.md`, `data/README.md`) | upstream (the TIDMAD distribution) |
| model / loss plugins, skills, `configs/` inside the pack | not projected (no consumer-less files, roadmap §22.23.3) | Step 12 (composition) |
| task binding of the pack as a whole | `configs/task_config.yaml` remains the single runtime task authority | Step 12 |
| training-history / diagnosis semantics | **production-backed from 07a** (Step 07 PR 07a): the production trainer emits R2 + R3 (`training_history`) and the tuner persists the derived `training_diagnosis` on every `ExperimentRecord` (`run_output_*.json`); NO new `resolved/` snapshot — the history is per-run evidence, not task config; hidden from both LLM-facing renders until 07b | landed (07a); rendering 07b; interpretation Step 09 |
| metric-direction policy / planner-reflector rendering | **production-backed from 07b** (Step 07 PR 07b): the tuner's every golden-metric ordering decision — trial winner, skip/bypass orientation and their disabled sentinels, the bootstrap sentinel, the planner's score-table incumbent, the reflector's best/rank/new-best/efficiency band, and all five `best_*` finalization tracks — flows from ONE `MetricOrder` derived from this pack's `direction: higher`; the planner and reflector prompts render this pack's task content, direction wording, metric identity and compact `TrainingDiagnosis` lines from their landed authorities | landed (07b); peripheral direction consumers (chain / resume / `per_file_best` / dashboard) remain **Steps 09/10/M2** |
| measurement / verification data feeding | not yet landed | Step 07c |
| generic health applicability declaration | `configs/health_checks.yaml` referenced only | Step 08 |
| interpretation evidence | — | Step 09 |

## Maturity pins carried by this pack at PR0 (design §3.5)

- no production `.py` under `examples/` — valid through PR0 / Step 07;
  relaxation owner **D14**;
- no top-level `task_description` / `forward_contract` YAML under `examples/`
  — valid before Step 12; relaxation owner **Step 12**;
- `resolved/` snapshots must never coexist with a later real task binding as
  a second authoritative-looking config — migration owner Step 12 / D14.
