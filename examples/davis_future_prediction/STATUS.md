# STATUS — `davis_future_prediction` (honest maturity; MIRROR of roadmap §15.1 / §22.12)

The roadmap (`docs/design/siderius_generic_framework_upgrade.md`) is the ONE
status authority; this file mirrors it for a reader of the pack.

## Maturity: **L0 / L1** (sequence identity fixed; declarable contracts declared through the real schemas; NO executable path)

This pack does not run. It claims exactly what has landed:

| contract / seam | representable today? | status in this pack | evidence |
|---|---|---|---|
| sequence-level identity (60 / 15 / 15) | yes — from official metadata (`db_info.yaml`) | **LANDED** (PR0): `data/manifests/sequences.csv` + `SHA256SUMS`, frozen rule (`PROVENANCE.md`) | `tests/unit/examples/test_davis_future_prediction_pack.py` (integrity pin, exactly 90 rows 60/15/15, pairwise disjoint, rule re-derived over the tracked val ∪ final, synthetic-rule test) |
| **clip identity `(sequence_name, start_frame)`** | needs per-sequence frame counts + the executable window rule | **NOT in this pack — clip identity → D14** (operator decision 2026-08-15); no clip manifest, no archive listing | test asserts no clip manifest exists under the pack |
| `ModelIOContract` | **DECLARABLE** (rank-agnostic; differing fixed T extents; only `B` shared) | **DECLARED** (L0/L1): `declared/model_io_contract.json` — `[B, 3, 8, 128, 224] float32 → [B, 3, 4, 128, 224] float32`, `output_semantic == continuous`, `class_cardinality is None` | constructs through `agent/schemas/model_io_contract.py`; derived properties asserted |
| `MetricSpec` mse (lower, golden) | **DECLARABLE** (scalar-only, `PresenceScoreabilityContract`); aggregation named as the FROZEN global mean over clips × C × T × H × W | **DECLARED**: `declared/metric_mse.json` | constructs through `execute_tools/evaluation_metric.py`; `direction == lower` |
| `MetricSpec` psnr (higher, optional) | **DECLARABLE** — the same global-MSE aggregation with transform `psnr_db`, `transform_params.data_range = 1.0` | **DECLARED**: `declared/metric_psnr.json` | `direction == higher`, `data_range == 1.0` |
| `MetricSpec` mae (lower, optional) | **DECLARABLE** (`mae` is not loss-shaped: what makes an id a loss is that it names the training objective, not its formula — `evaluation_metric.py`) | **DECLARED**: `declared/metric_mae.json` | `direction == lower` |
| `DatasetProfile` | **NOT representable**: 1-D-segment, two-channel HDF5 semantics | named as a seam | — |
| `DeliverableSpec` | **NOT representable**: per-file HDF5 naming / storage | named as a seam | — |
| frame reader / decode / resize 128×224 / window materialization / tensor hashes | EXECUTION-level manifest | not representable as a declaration | **D14** |
| reference plugin (small conv/recurrent predictor) | no consumer path for an example plugin yet | none | **D14** |
| Gate-1 / Gate-2 / persistent NESTED clip subsets | sized by the D14 design | none | **D14** |
| licence terms of the downloaded TrainVal-480p artifact | to be verified and pinned | recorded per artifact in `PROVENANCE.md` (frozen wording); executable provenance incomplete by design | **D14** |
| pack-level runtime task binding | single-task authority `configs/task_config.yaml` | not representable | **Step 12** |
| health applicability | `configs/health_checks.yaml` is TIDMAD-shaped policy | not representable | **Step 08** |
| training history / diagnosis (R2/R3 MAE curves + optional validation PSNR) | the framework's `TrainingHistory` / `TrainingDiagnosis` (Step 07a) are task-generic: the schema carries this pack's semantics (`objective_kind="mae"`, `observations={"validation_psnr": …}`) without change | **L1 — fixture-backed**: `expected/training_history_l1_fixture.json` + `expected/training_diagnosis_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real training output; validation identity = the 15 sequences, clip identity D14) consumed by rung **B-07a-1** (`tests/unit/examples/test_step07a_b1_diagnosis_structure_rung.py`); real R2/R3 after **D14** | the rung derives the diagnosis from the fixture through the SAME boundary TIDMAD uses and pins the expected verdict shape as literals |
| metric-direction policy / planner-reflector rendering (Step 07 PR 07b) | the tuner's ordering authority and the prompt renderers consume a `MetricSpec` — this pack's `declared/metric_mse.json` (`mse`, `lower`-is-better) is consumed unchanged | **L1 — declaration-backed**: rungs **B-07b-1** (ordering inverts exactly under the declared direction) and **B-07b-2** (the planner/reflector blocks render this pack's metric identity and direction words, and its `expected/training_diagnosis_l1_fixture.json` renders as a compact dynamics line) — `tests/unit/agent/llm_bridge/test_step07b_c5_rendering.py`; no executable path | the rungs load the pack's OWN declared spec and 07a fixture; **no real davis_future_prediction execution — that is D14** |
| interpretation evidence | — | — | **Step 09** |

## Maturity pins carried by this pack at PR0 (design §3.5)

- no production `.py` under `examples/` — valid through PR0 / Step 07;
  relaxation owner **D14**;
- no top-level `task_description` / `forward_contract` YAML under `examples/`
  — valid before Step 12; relaxation owner **Step 12**.

## Not in this pack, by design

No frames, no archive, no archive listing, no clip manifest, no cache, no
loader, no launcher.
