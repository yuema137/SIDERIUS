# STATUS — `oxford_iiit_pet` (honest maturity; MIRROR of roadmap §15.1 / §22.12)

The roadmap (`docs/design/siderius_generic_framework_upgrade.md`) is the ONE
status authority; this file mirrors it for a reader of the pack.

## Maturity: **L2/L3 EXECUTABLE (D14-2)** — identity fixed; contracts declared; the REAL data path, reference plugin, bounded training/validation/inference/scoring all executed

Since D14-2 this track RUNS: real official JPEGs → `execute_tools/pets_data_path.py` (frozen transform, manifest scope) → the production training engine (real R2+R3) → inference → the classification deliverable → `accuracy` through the Step-06 handle. Gate-2 PASS evidence: `docs/design/generic_framework_upgrade/d14_executable_data_path/pr_d14_2_pets_executable.md` §6 C6 (workspace `/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818/`). The rows below record each seam honestly:

| contract / seam | representable today? | status in this pack | evidence |
|---|---|---|---|
| identity manifests (train / validation / final) | yes — from official metadata | **LANDED** (PR0): `data/manifests/*.csv` + `SHA256SUMS`, frozen rule (`PROVENANCE.md`) | `tests/unit/examples/test_oxford_iiit_pet_pack.py` (integrity pins, counts 2 946 / 734 / 3 669, disjointness, 37 classes in train and validation, rule re-derived on a synthetic list) |
| `ModelIOContract` | **DECLARABLE** (rank-agnostic schema; `class` role fixed 37) | **DECLARED** (L0/L1): `declared/model_io_contract.json` — `[B, 3, 144, 144] float32 → [B, 37] float32`, `output_semantic == categorical`, `class_cardinality == 37` | constructs through `agent/schemas/model_io_contract.py`; derived properties asserted |
| `MetricSpec` accuracy (higher) | **DECLARABLE** (scalar-only, `PresenceScoreabilityContract`) | **DECLARED**: `declared/metric_accuracy.json` | constructs through `execute_tools/evaluation_metric.py`; `direction == higher` |
| `MetricSpec` macro_f1 (higher) | **DECLARABLE** | **DECLARED**: `declared/metric_macro_f1.json` | same |
| `MetricSpec` log_loss (lower) | **NOT declarable — blocked by D16**: the Step-06 lexical rule (`_is_loss_shaped`) refuses any identity whose tokens include `loss`; the identity is INTENTIONAL (§22.9a) and forces D16 to be resolved before it crosses the production metric-declaration path | documented only; NOT declared through the schema | the test asserts `MetricSpec(id="log_loss", …)` RAISES today — the day D16 is narrowed, this documentation is forced to change |
| `DatasetProfile` | **NOT representable**: `DatasetConfig` / `ChannelIdentity` / `ValueEncoding` are 1-D-segment, two-channel HDF5 semantics | named as a seam | — |
| `DeliverableSpec` | **NOT representable**: per-file HDF5 naming / storage | named as a seam | — |
| reader / preprocessing (decode, resize 160 BILINEAR, center-crop 144, /255) | executable CODE + committed execution manifest | **LANDED (D14-2)**: `execute_tools/pets_data_path.py::decode_and_transform` (ONE authority) + `data/manifests/execution.json` (37 class-covering probe hashes, byte-pinned) | `tests/unit/examples/test_pets_execution_manifest.py` (pins, synthetic transform behaviour, REAL two-process probe parity); `tests/unit/execute_tools/test_pets_data_path.py` (probes THROUGH the seam reader) |
| reference plugin (small CNN) | loads through the real plugin mechanism (`SIDERIUS_PLUGIN_DIRS`) | **LANDED (D14-2)**: `plugins/pets_reference_cnn.py` (61 509 params, `[B,3,144,144]f32 → [B,37]f32`) — sanctioned plugin SOURCE, dynamically loaded, never imported | `tests/unit/examples/test_pets_reference_plugin.py` |
| Gate-1 / Gate-2 / persistent NESTED subsets | committed, derived first-N-per-class from the frozen manifests | **LANDED (D14-2)**: `data/manifests/gate2_{train,validation,final}.csv` (370/74/370, byte-pinned, re-derivation exact) | `tests/unit/examples/test_pets_execution_manifest.py`; Gate-2 PASS at the D14-2 ledger §6 C6 |
| pack-level runtime task binding | single-task authority `configs/task_config.yaml` | not representable | **Step 12** |
| health applicability | since **Step 08b** `configs/health_checks.yaml` is FRAMEWORK POLICY ONLY (disposition → gate role/cadence/actions); TIDMAD's roster, thresholds, peek set and mV scale moved to its own `configs/task_health/tidmad.yaml` | **Step 08b — explicitly NO Health binding.** This pack declares no task Health config and its runner (`scripts/run_pets_gate2.py`) never enters Health composition, so it cannot inherit TIDMAD's family: the legacy-omitted → TIDMAD default lives in `materialize_effective_config`, which the runner neither calls nor imports. Pinned by `tests/unit/guardrails/test_step08b_cross_task_compatibility.py`. Its metric is scalar-only (`per_sample is None`), which Step 08b D18 preserves as a typed statement rather than an empty list | a task-owned Health family for this pack is **Step 08c** |
| training history / diagnosis (R2/R3 CE curves + optional validation accuracy) | the framework's `TrainingHistory` / `TrainingDiagnosis` (Step 07a) are task-generic: the schema carries this pack's semantics (`objective_kind="ce"`, `observations={"validation_accuracy": …}`) without change | **L1 — fixture-backed**: `expected/training_history_l1_fixture.json` + `expected/training_diagnosis_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real training output) consumed by rung **B-07a-1** (`tests/unit/examples/test_step07a_b1_diagnosis_structure_rung.py`) — KEPT verbatim (cumulative corpus), and since **D14-2** the ADDED real-component pair `expected/training_history_real_component_fixture.json` / `expected/training_diagnosis_real_component_fixture.json` carries the REAL bounded gate run's R2/R3 through the same rung | the rung derives the diagnosis from the fixture through the SAME boundary TIDMAD uses and pins the expected verdict shape as literals |
| metric-direction policy / planner-reflector rendering (Step 07 PR 07b) | the tuner's ordering authority and the prompt renderers consume a `MetricSpec` — this pack's `declared/metric_accuracy.json` (`accuracy`, `higher`-is-better) is consumed unchanged | **L1 — declaration-backed**: rungs **B-07b-1** (ordering inverts exactly under the declared direction) and **B-07b-2** (the planner/reflector blocks render this pack's metric identity and direction words, and its `expected/training_diagnosis_l1_fixture.json` renders as a compact dynamics line) — `tests/unit/agent/llm_bridge/test_step07b_c5_rendering.py`; no executable path | the rungs load the pack's OWN declared spec and 07a fixture; **no real oxford_iiit_pet execution — that is D14** |
| interpretation evidence | — | — | **Step 09** |

## Maturity pins carried by this pack at PR0 (design §3.5)

- `.py` under `examples/` is sanctioned ONLY as pack plugin source at
  `examples/<pack>/plugins/*.py` (D14-2 exercised its named relaxation
  ownership; production imports of `examples.*` remain forbidden);
- no top-level `task_description` / `forward_contract` YAML under `examples/`
  — valid before Step 12; relaxation owner **Step 12**.

## Not in this pack, by design

No images and no archives in the TREE — `images.tar.gz` (SHA-pinned in
`PROVENANCE.md`) lives machine-local via
`tools/example_packs/fetch_oxford_iiit_pet.py`; the framework receives the
root as the data-path seam's `data_dir`. No cache, no launcher.
