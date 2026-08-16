# STATUS — `oxford_iiit_pet` (honest maturity; MIRROR of roadmap §15.1 / §22.12)

The roadmap (`docs/design/siderius_generic_framework_upgrade.md`) is the ONE
status authority; this file mirrors it for a reader of the pack.

## Maturity: **L0 / L1** (identity fixed; declarable contracts declared through the real schemas; NO executable path)

This pack does not run. It claims exactly what has landed:

| contract / seam | representable today? | status in this pack | evidence |
|---|---|---|---|
| identity manifests (train / validation / final) | yes — from official metadata | **LANDED** (PR0): `data/manifests/*.csv` + `SHA256SUMS`, frozen rule (`PROVENANCE.md`) | `tests/unit/examples/test_oxford_iiit_pet_pack.py` (integrity pins, counts 2 946 / 734 / 3 669, disjointness, 37 classes in train and validation, rule re-derived on a synthetic list) |
| `ModelIOContract` | **DECLARABLE** (rank-agnostic schema; `class` role fixed 37) | **DECLARED** (L0/L1): `declared/model_io_contract.json` — `[B, 3, 144, 144] float32 → [B, 37] float32`, `output_semantic == categorical`, `class_cardinality == 37` | constructs through `agent/schemas/model_io_contract.py`; derived properties asserted |
| `MetricSpec` accuracy (higher) | **DECLARABLE** (scalar-only, `PresenceScoreabilityContract`) | **DECLARED**: `declared/metric_accuracy.json` | constructs through `execute_tools/evaluation_metric.py`; `direction == higher` |
| `MetricSpec` macro_f1 (higher) | **DECLARABLE** | **DECLARED**: `declared/metric_macro_f1.json` | same |
| `MetricSpec` log_loss (lower) | **NOT declarable — blocked by D16**: the Step-06 lexical rule (`_is_loss_shaped`) refuses any identity whose tokens include `loss`; the identity is INTENTIONAL (§22.9a) and forces D16 to be resolved before it crosses the production metric-declaration path | documented only; NOT declared through the schema | the test asserts `MetricSpec(id="log_loss", …)` RAISES today — the day D16 is narrowed, this documentation is forced to change |
| `DatasetProfile` | **NOT representable**: `DatasetConfig` / `ChannelIdentity` / `ValueEncoding` are 1-D-segment, two-channel HDF5 semantics | named as a seam | — |
| `DeliverableSpec` | **NOT representable**: per-file HDF5 naming / storage | named as a seam | — |
| reader / preprocessing (decode, resize 160, center-crop 144, /255) | not representable as a declaration | EXECUTION-level manifest, decoder, interpolation rule | **D14** |
| reference plugin (small CNN) | no consumer path for an example plugin yet | none (a schema-only plugin would be an L1 fixture, labelled so — none shipped) | **D14** |
| Gate-1 / Gate-2 / persistent NESTED subsets | sized by the D14 design | none | **D14** |
| pack-level runtime task binding | single-task authority `configs/task_config.yaml` | not representable | **Step 12** |
| health applicability | `configs/health_checks.yaml` is TIDMAD-shaped policy | not representable | **Step 08** |
| training history / diagnosis (R2/R3 CE curves + optional validation accuracy) | the framework's `TrainingHistory` / `TrainingDiagnosis` (Step 07a) are task-generic: the schema carries this pack's semantics (`objective_kind="ce"`, `observations={"validation_accuracy": …}`) without change | **L1 — fixture-backed**: `expected/training_history_l1_fixture.json` + `expected/training_diagnosis_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real training output) consumed by rung **B-07a-1** (`tests/unit/examples/test_step07a_b1_diagnosis_structure_rung.py`); real R2/R3 after **D14** | the rung derives the diagnosis from the fixture through the SAME boundary TIDMAD uses and pins the expected verdict shape as literals |
| interpretation evidence | — | — | **Step 09** |

## Maturity pins carried by this pack at PR0 (design §3.5)

- no production `.py` under `examples/` — valid through PR0 / Step 07;
  relaxation owner **D14**;
- no top-level `task_description` / `forward_contract` YAML under `examples/`
  — valid before Step 12; relaxation owner **Step 12**.

## Not in this pack, by design

No images (`images.tar.gz` is never fetched by the framework), no extracted
annotation files, no cache, no loader, no launcher.
