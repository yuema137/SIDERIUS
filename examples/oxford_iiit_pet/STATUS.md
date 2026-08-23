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
| `MetricSpec` log_loss (lower) | **DECLARABLE — D16 CLOSED by Step 12 / PR-12a C5.** The Step-06 lexical rule (`_is_loss_shaped`) is gone: a metric identity is OPAQUE, and meaning and direction come from the declaration. The identity was INTENTIONAL (§22.9a) precisely to force this, and it did | still NOT shipped as a declaration — what Pets is evaluated on is a scientific choice, not a side effect of a schema change | the test now asserts `MetricSpec(id="log_loss", …)` CONSTRUCTS, and that no `metric_log_loss.json` is shipped |
| `DatasetProfile` | **NOT representable**: `DatasetConfig` / `ChannelIdentity` / `ValueEncoding` are 1-D-segment, two-channel HDF5 semantics | named as a seam | — |
| `DeliverableSpec` | **NOT representable**: per-file HDF5 naming / storage | named as a seam | — |
| reader / preprocessing (decode, resize 160 BILINEAR, center-crop 144, /255) | executable CODE + committed execution manifest | **LANDED (D14-2)**: `execute_tools/pets_data_path.py::decode_and_transform` (ONE authority) + `data/manifests/execution.json` (37 class-covering probe hashes, byte-pinned) | `tests/unit/examples/test_pets_execution_manifest.py` (pins, synthetic transform behaviour, REAL two-process probe parity); `tests/unit/execute_tools/test_pets_data_path.py` (probes THROUGH the seam reader) |
| reference plugin (small CNN) | loads through the real plugin mechanism (`SIDERIUS_PLUGIN_DIRS`) | **LANDED (D14-2)**: `plugins/pets_reference_cnn.py` (61 509 params, `[B,3,144,144]f32 → [B,37]f32`) — sanctioned plugin SOURCE, dynamically loaded, never imported | `tests/unit/examples/test_pets_reference_plugin.py` |
| Gate-1 / Gate-2 / persistent NESTED subsets | committed, derived first-N-per-class from the frozen manifests | **LANDED (D14-2)**: `data/manifests/gate2_{train,validation,final}.csv` (370/74/370, byte-pinned, re-derivation exact) | `tests/unit/examples/test_pets_execution_manifest.py`; Gate-2 PASS at the D14-2 ledger §6 C6 |
| pack-level runtime task binding | single-task authority `configs/task_config.yaml` | not representable | **Step 12** |
| health applicability | since **Step 08b** `configs/health_checks.yaml` is FRAMEWORK POLICY ONLY (disposition → gate role/cadence/actions); task science lives in task-owned configs | **LANDED (Step 08c C3) — task-owned Health family through the EXTERNAL interface.** `declared/task_health.yaml` (facts: `encoding_family=categorical_labels`, `symbol_cardinality=37`; two BLOCKING gates: `pets_distinct_symbols_blocking` `min_distinct_symbols=5`, `pets_dominant_fraction_blocking` `max_dominant_fraction=0.95` — FROZEN safety floors against the preserved D14 collapse) + `plugins/_pets_health_views.py` (provider `pets.prediction_views` exposing the standard `categorical_predictions` view from the deliverable CSV; underscore-prefixed so directory scanners never exec it — the config's explicit `kind: file` ref is its only loading path) + the committed REAL collapse fixture-of-record `expected/d14_gate2_collapse_predictions.csv` (sha256 `cc847026…f752c`, 6 812 B: n=370, distinct=2, occupancy=2/37, dominant=369/370). Binds state C — never the legacy-omitted TIDMAD default. Its metric stays scalar-only (D18). Runner Health-evidence stage **LANDED (08c C5)**: `scripts/run_pets_gate2.py` evaluates this family on each run's FRESH deliverable through the ONE shared `scripts/_gate2_health_stage.py` (explicit state-C binding, additive `health` block). 08c Gate-2 PASS at `ede11fd5`: the fresh seed-11 run reproduced the collapse byte-identically and BOTH gates FAILED with numerically consistent evidence | `tests/unit/examples/test_pets_health_family.py` (fixture immutability pin; full state-C chain → both gates FAIL with the §2.5 evidence; healthy counterfactual PASSES; §2.12 codec parity both directions; fail-closed pair; provider ERROR paths; pack-identifier census) |
| training history / diagnosis (R2/R3 CE curves + optional validation accuracy) | the framework's `TrainingHistory` / `TrainingDiagnosis` (Step 07a) are task-generic: the schema carries this pack's semantics (`objective_kind="ce"`, `observations={"validation_accuracy": …}`) without change | **L1 — fixture-backed**: `expected/training_history_l1_fixture.json` + `expected/training_diagnosis_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real training output) consumed by rung **B-07a-1** (`tests/unit/examples/test_step07a_b1_diagnosis_structure_rung.py`) — KEPT verbatim (cumulative corpus), and since **D14-2** the ADDED real-component pair `expected/training_history_real_component_fixture.json` / `expected/training_diagnosis_real_component_fixture.json` carries the REAL bounded gate run's R2/R3 through the same rung | the rung derives the diagnosis from the fixture through the SAME boundary TIDMAD uses and pins the expected verdict shape as literals |
| metric-direction policy / planner-reflector rendering (Step 07 PR 07b) | the tuner's ordering authority and the prompt renderers consume a `MetricSpec` — this pack's `declared/metric_accuracy.json` (`accuracy`, `higher`-is-better) is consumed unchanged | **L1 — declaration-backed**: rungs **B-07b-1** (ordering inverts exactly under the declared direction) and **B-07b-2** (the planner/reflector blocks render this pack's metric identity and direction words, and its `expected/training_diagnosis_l1_fixture.json` renders as a compact dynamics line) — `tests/unit/agent/llm_bridge/test_step07b_c5_rendering.py`; no executable path | the rungs load the pack's OWN declared spec and 07a fixture; **no real oxford_iiit_pet execution — that is D14** |
| interpretation evidence (Step 09 PR 09a) | the interpreter's ordering, metric identity, prediction band and secondary-metric contract are task-generic: this pack's `declared/metric_accuracy.json` (`accuracy`, **higher**, scalar-only) and `declared/metric_macro_f1.json` (`macro_f1`, higher) are consumed unchanged | **L1 — fixture-backed**: `expected/interpretation_evidence_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real tuning output) consumed by rung **B-09a-1** (`tests/unit/examples/test_step09a_interpretation_evidence_rung.py`), which drives the REAL `tuning_output_to_model_run_summary` / `ordering.precompute_evidence` / `prediction.evaluate_prediction` and pins hand-computed literals. The `macro_f1` secondary is rendered present-when-present and is proven unable to affect any ordering | the production workflow does **not** evaluate secondary metrics — tuner-side evaluation, `ExperimentRecord` persistence and workflow transport are **Step 10**'s (Q-09-7 = B); **no real oxford_iiit_pet interpretation run** |

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


## Runner role and L3 evidence freshness (Step 10 / P5+P6 C7)

**`scripts/run_pets_gate2.py` is an L3 REAL-EXECUTION EVIDENCE HARNESS**,
not an alternate way this task "runs". Its ORCHESTRATION claims (binding
resolves · direction correct · secondaries observational · Health binds
state C) were TRANSFERRED to the generic-loop closure tests
(`tests/unit/workflows/test_step10_p56_c6_three_task_closure.py`), which drive
all three tasks through the ONE production `run_workflow`. What survives here
is the distinct real-execution failure class nothing cheaper owns. Full
retirement is blocked on **CAP-SCOPE** (design §10.2): until task-owned scope
construction exists, the generic loop cannot execute real contrast-task
training, so those claims have no generic owner to move to.

**§10.6 freshness audit — RERUN TRIGGERED, evidence now CURRENT.**

| | |
|---|---|
| prior evidence | `/home/klz/Data/SIDEREIS_DATA/step08c_pets_gate2_20260818/gate_evidence.json` at `ede11fd5` — verdict PASS |
| dependency diff | `ede11fd5..HEAD` over the runner's real-execution surface changed **semantics-bearing** files, including the very Health checks this pack exercises (`categorical_distinct_symbols`, `categorical_dominant_fraction`), plus `evaluation_metric.py` and `task_data_path.py` |
| verdict | prior evidence NOT assumed current → bounded rerun REQUIRED (no LLM, GPU only) |
| rerun | `/home/klz/Data/SIDEREIS_DATA/step10_p56_c7_pets_20260821/gate_evidence.json` at `c9031369` — verdict **PASS** |
| comparison | accuracy **BIT-EQUAL** (`0.02702702702702703`, = chance 1/37); both blocking gates same `check_verdicts` and same `resolved_action` (`invalidate_round`) — the real collapse reproduced exactly |

The changed dependencies were therefore behaviour-preserving for this track —
established by rerunning, not by inspection.
