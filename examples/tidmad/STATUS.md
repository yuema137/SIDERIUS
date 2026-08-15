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

**The runtime does not read anything under `examples/tidmad/`.** The
snapshots are read-only projections; editing them changes nothing at run
time (design §3.6).

## NOT projected here (and who owns it)

| seam | status | owner |
|---|---|---|
| launcher / run instructions inside the pack | not projected — runs go through the existing operator docs and `scripts/` | Steps 10 / 12 (binding + launcher interface) |
| model / loss plugins, skills, `configs/` inside the pack | not projected (no consumer-less files, roadmap §22.23.3) | Step 12 (composition) |
| task binding of the pack as a whole | `configs/task_config.yaml` remains the single runtime task authority | Step 12 |
| training-history / diagnosis semantics | not yet landed | Step 07a |
| metric-direction policy / planner-reflector rendering | not yet landed | Step 07b |
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
