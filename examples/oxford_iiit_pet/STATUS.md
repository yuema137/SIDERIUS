# STATUS — `oxford_iiit_pet` (honest maturity; MIRROR of roadmap §15.1 / §22.12)

The roadmap (`docs/design/siderius_generic_framework_upgrade.md`) is the ONE
status authority; this file mirrors it for a reader of the pack.

## Maturity: **L4** (Step 12 / PR-12d D-FINAL, on `G-12d` evidence) — on top of **L2/L3 EXECUTABLE (D14-2)**

**Promoted, and only now.** Until D-FINAL this heading read *"L4 DECLARATIONS
COMPLETE / L4 EXECUTION PENDING"*, because the pack declared everything a
composed run needs but had never executed the composed production
train → infer → score path even once. `G-12d` executed it.

| `G-12d` Pets witness | value, read from the persisted run record |
|---|---|
| workspace | `siderius_workspace/pets_ws_a7/run_output_g12d_pets_track1.json` |
| composition fingerprint | `2a5940a49d3709c2fb6d867b15807c0fb0dda5ce2d3b2d58f229583fb74478fc` |
| round | 1 formal round (`is_trial: false`), `status: completed` |
| record | `pets_reference_cnn_g12d_pets_track1_001`, `status: success` |
| primary | `metric_result` = `accuracy` / **higher** / `0.0945945945945946` — the identity crossed the child boundary with the value |
| secondaries | `macro_f1` / higher / `0.08030888030888031` · `log_loss` / **lower** / `8.009310892635284` — mixed direction, observational |
| training | `objective_kind: ce`, 30 epochs planned, `final_loss 0.172149258852005` |
| diagnosis | `state: ok`, `validation_state: present`, `comparability: established` |

**What this promotion does NOT claim.** Three things, stated here because a
maturity label is exactly where they would otherwise be quietly assumed:

1. **No scientific claim.** `accuracy 0.0946` against a 37-way chance of
   `0.027` is an OBSERVATION, not a result. §I excludes model quality,
   HealthGate PASS and score magnitude from `G-12d`'s PASS criteria, and the
   large campaign is later work.
2. **The pack's Health family did NOT run on the composed path.**
   `health_gate_results` is `[]` in this record — HealthGate evaluation still
   lives only inside the `ANCHOR_NORMALIZED` branch, so a composed run fires
   ZERO gates. Step 08c demonstrated this pack's Health family through the
   D14 direct-execution runner, and that claim stands **as a runner claim**;
   it must never be restated as a composed-path claim.
3. **One round, not a chain.** Multi-iteration composed behaviour for this
   pack is not evidenced here.

### What D5 declared, and the three things that still block execution

| declared | file |
|---|---|
| composition manifest (operator entrypoint / pointer only) | `configs/task_composition/pets.yaml` |
| dataset profile (Q-12-4 generic identity + opaque topology) | `declared/dataset_profile.json` |
| task description + forward contract | `declared/task_config.yaml` |
| primary metric `accuracy` / HIGHER | `declared/metric_accuracy.json` |
| secondary `macro_f1` / HIGHER, `log_loss` / LOWER | `declared/metric_macro_f1.json`, `declared/metric_log_loss.json` |

**Blocker 1 — `log_loss` is DECLARED but not yet COMPUTABLE.**
`plugins/_pets_metrics.py::PetsLogLossMetric` consumes a probability vector
per image; the shipped deliverable codec
(`execute_tools/pets_data_path.py`) writes `image_id,predicted_class_index`
— arg-max labels with no distribution — so the metric REFUSES the payload BY
NAME rather than reading a class index as a probability. D5 deliberately did
NOT change the codec: no production path evaluates a secondary metric on the
task-owned scoring route at all (blocker 2), so emitting the distribution
today would have changed a byte-pinned artifact format for a consumer that
does not exist. The declaration is honest about what Pets is evaluated on;
the codec obligation is open and named here.

**Blocker 2 — nothing evaluates a secondary metric on the composed route.**
`_evaluate_secondary_metrics` is called from exactly one site, inside the
tuner's `ScoringRoute.ANCHOR_NORMALIZED` branch. A composed Pets run takes
`ScoringRoute.TASK_OWNED`, whose scoring child evaluates the PRIMARY only.
So neither `macro_f1` nor `log_loss` can reach a terminal report yet.

**Blocker 3 — the primary's bound implementation cannot accept the composed
call.** `denoising_score_single.py::_emit_task_owned_score` invokes the
metric with `evaluation_payload` / `task_scope` / `data_dir` — the three
values the framework owns — while `AccuracyMetric._compute` is keyword-only
over `{predictions, truth}` and derives neither. All three blockers live in
the generic scoring/tuner surface, not in this pack.

**Known scope limitation, declared rather than hidden**: `PetsTaskDataPath`
takes ONE manifest and serves both `build_training_scope` and
`build_eval_scope` from it, so a composed Pets run's evaluation is
**in-sample**. The shipped manifest names `gate2_train.csv`, so the frozen
final-eval scope is never contaminated — but the resulting accuracy is a
plumbing observation, never a generalization claim.

### Executable maturity carried forward from D14-2

Since D14-2 this track RUNS: real official JPEGs → `execute_tools/pets_data_path.py` (frozen transform, manifest scope) → the production training engine (real R2+R3) → inference → the classification deliverable → `accuracy` through the Step-06 handle. Gate-2 PASS evidence: `docs/design/generic_framework_upgrade/d14_executable_data_path/pr_d14_2_pets_executable.md` §6 C6 (workspace `/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818/`). The rows below record each seam honestly:

| contract / seam | representable today? | status in this pack | evidence |
|---|---|---|---|
| identity manifests (train / validation / final) | yes — from official metadata | **LANDED** (PR0): `data/manifests/*.csv` + `SHA256SUMS`, frozen rule (`PROVENANCE.md`) | `tests/unit/examples/test_oxford_iiit_pet_pack.py` (integrity pins, counts 2 946 / 734 / 3 669, disjointness, 37 classes in train and validation, rule re-derived on a synthetic list) |
| `ModelIOContract` | **DECLARABLE** (rank-agnostic schema; `class` role fixed 37) | **DECLARED** (L0/L1): `declared/model_io_contract.json` — `[B, 3, 144, 144] float32 → [B, 37] float32`, `output_semantic == categorical`, `class_cardinality == 37` | constructs through `agent/schemas/model_io_contract.py`; derived properties asserted |
| `MetricSpec` accuracy (higher) | **DECLARABLE** (scalar-only, `PresenceScoreabilityContract`) | **DECLARED**: `declared/metric_accuracy.json` | constructs through `execute_tools/evaluation_metric.py`; `direction == higher` |
| `MetricSpec` macro_f1 (higher) | **DECLARABLE** | **DECLARED**: `declared/metric_macro_f1.json` | same |
| `MetricSpec` log_loss (lower) | **DECLARABLE — D16 CLOSED by Step 12 / PR-12a C5.** The Step-06 lexical rule (`_is_loss_shaped`) is gone: a metric identity is OPAQUE, and meaning and direction come from the declaration. The identity was INTENTIONAL (§22.9a) precisely to force this, and it did | **DECLARED (D5)**: `declared/metric_log_loss.json` — `log_loss`, **LOWER**, bound in the shipped manifest to `plugins/_pets_metrics.py::PetsLogLossMetric`. NOT yet computable — see blockers 1 and 2 above | `tests/unit/examples/test_oxford_iiit_pet_pack.py` (identity + LOWER, hardcoded); `tests/unit/examples/test_step12_pr12d_d5_pets_declarations.py` (the shipped composition resolves it as a secondary) |
| `DatasetProfile` | **REPRESENTABLE since Step 12 / PR-12bc B2 (Q-12-4)**: the profile split into a generic identity (`partition_count`, `anchor_selection_files`, `health_peek_files`) plus an OPAQUE task-owned `topology`. Before that it was `DatasetConfig` / `ChannelIdentity` / `ValueEncoding` — 1-D-segment, two-channel HDF5 semantics a 37-way image classifier cannot honestly fill | **DECLARED (D5)**: `declared/dataset_profile.json`. No PSD length, no segments-per-file, no sampling frequency, no `.h5` shard pattern — the fabricated fixture values F-12d-4 condemned are DELETED, not carried | `tests/unit/examples/test_step12_pr12d_d5_pets_declarations.py` (field-by-field absence, and `declares_tidmad_topology` False) |
| `DeliverableSpec` | **NOT representable** — and after PR-12d seam E it is NOT APPLICABLE rather than absent: `DeliverableNaming` is a TIDMAD implementation detail plus an optional task capability, and this pack's codec names its own artifact | named as a seam; the absence must never resolve TIDMAD's template (F-A4-1) | `tests/unit/workflows/test_step12_pr12d_checkpoint_a.py` (naming REFUSES for a composed contrast run) |
| reader / preprocessing (decode, resize 160 BILINEAR, center-crop 144, /255) | executable CODE + committed execution manifest | **LANDED (D14-2)**: `execute_tools/pets_data_path.py::decode_and_transform` (ONE authority) + `data/manifests/execution.json` (37 class-covering probe hashes, byte-pinned) | `tests/unit/examples/test_pets_execution_manifest.py` (pins, synthetic transform behaviour, REAL two-process probe parity); `tests/unit/execute_tools/test_pets_data_path.py` (probes THROUGH the seam reader) |
| reference plugin (small CNN) | loads through the real plugin mechanism (`SIDERIUS_PLUGIN_DIRS`) | **LANDED (D14-2)**: `plugins/pets_reference_cnn.py` (61 509 params, `[B,3,144,144]f32 → [B,37]f32`) — sanctioned plugin SOURCE, dynamically loaded, never imported | `tests/unit/examples/test_pets_reference_plugin.py` |
| Gate-1 / Gate-2 / persistent NESTED subsets | committed, derived first-N-per-class from the frozen manifests | **LANDED (D14-2)**: `data/manifests/gate2_{train,validation,final}.csv` (370/74/370, byte-pinned, re-derivation exact) | `tests/unit/examples/test_pets_execution_manifest.py`; Gate-2 PASS at the D14-2 ledger §6 C6 |
| pack-level runtime task binding | **representable since Step 10 / P1** — a composition manifest resolves every semantic family; `configs/task_config.yaml` is no longer the single runtime authority for a composed run | **DECLARED (D5)**: `declared/task_config.yaml` (task description + forward contract) bound by `configs/task_composition/pets.yaml`, which is a POINTER carrying no second copy of any task semantics (Q-12d-1) | `tests/unit/examples/test_step12_pr12d_d5_pets_declarations.py`; the re-scoped governance guard `tests/unit/examples/test_pack_governance.py` (a pack task config is legitimate only while a shipped manifest BINDS it) |
| health applicability | since **Step 08b** `configs/health_checks.yaml` is FRAMEWORK POLICY ONLY (disposition → gate role/cadence/actions); task science lives in task-owned configs | **LANDED (Step 08c C3) — task-owned Health family through the EXTERNAL interface.** `declared/task_health.yaml` (facts: `encoding_family=categorical_labels`, `symbol_cardinality=37`; two BLOCKING gates: `pets_distinct_symbols_blocking` `min_distinct_symbols=5`, `pets_dominant_fraction_blocking` `max_dominant_fraction=0.95` — FROZEN safety floors against the preserved D14 collapse) + `plugins/_pets_health_views.py` (provider `pets.prediction_views` exposing the standard `categorical_predictions` view from the deliverable CSV; underscore-prefixed so directory scanners never exec it — the config's explicit `kind: file` ref is its only loading path) + the committed REAL collapse fixture-of-record `expected/d14_gate2_collapse_predictions.csv` (sha256 `cc847026…f752c`, 6 812 B: n=370, distinct=2, occupancy=2/37, dominant=369/370). Binds state C — never the legacy-omitted TIDMAD default. Its metric stays scalar-only (D18). Runner Health-evidence stage **LANDED (08c C5)**: `scripts/run_pets_gate2.py` evaluates this family on each run's FRESH deliverable through the ONE shared `scripts/_gate2_health_stage.py` (explicit state-C binding, additive `health` block). 08c Gate-2 PASS at `ede11fd5`: the fresh seed-11 run reproduced the collapse byte-identically and BOTH gates FAILED with numerically consistent evidence | `tests/unit/examples/test_pets_health_family.py` (fixture immutability pin; full state-C chain → both gates FAIL with the §2.5 evidence; healthy counterfactual PASSES; §2.12 codec parity both directions; fail-closed pair; provider ERROR paths; pack-identifier census) |
| training history / diagnosis (R2/R3 CE curves + optional validation accuracy) | the framework's `TrainingHistory` / `TrainingDiagnosis` (Step 07a) are task-generic: the schema carries this pack's semantics (`objective_kind="ce"`, `observations={"validation_accuracy": …}`) without change | **L1 — fixture-backed**: `expected/training_history_l1_fixture.json` + `expected/training_diagnosis_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real training output) consumed by rung **B-07a-1** (`tests/unit/examples/test_step07a_b1_diagnosis_structure_rung.py`) — KEPT verbatim (cumulative corpus), and since **D14-2** the ADDED real-component pair `expected/training_history_real_component_fixture.json` / `expected/training_diagnosis_real_component_fixture.json` carries the REAL bounded gate run's R2/R3 through the same rung | the rung derives the diagnosis from the fixture through the SAME boundary TIDMAD uses and pins the expected verdict shape as literals |
| metric-direction policy / planner-reflector rendering (Step 07 PR 07b) | the tuner's ordering authority and the prompt renderers consume a `MetricSpec` — this pack's `declared/metric_accuracy.json` (`accuracy`, `higher`-is-better) is consumed unchanged | **L1 — declaration-backed**: rungs **B-07b-1** (ordering inverts exactly under the declared direction) and **B-07b-2** (the planner/reflector blocks render this pack's metric identity and direction words, and its `expected/training_diagnosis_l1_fixture.json` renders as a compact dynamics line) — `tests/unit/agent/llm_bridge/test_step07b_c5_rendering.py`; no executable path | the rungs load the pack's OWN declared spec and 07a fixture; **no real oxford_iiit_pet execution — that is D14** |
| interpretation evidence (Step 09 PR 09a) | the interpreter's ordering, metric identity, prediction band and secondary-metric contract are task-generic: this pack's `declared/metric_accuracy.json` (`accuracy`, **higher**, scalar-only) and `declared/metric_macro_f1.json` (`macro_f1`, higher) are consumed unchanged | **L1 — fixture-backed**: `expected/interpretation_evidence_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real tuning output) consumed by rung **B-09a-1** (`tests/unit/examples/test_step09a_interpretation_evidence_rung.py`), which drives the REAL `tuning_output_to_model_run_summary` / `ordering.precompute_evidence` / `prediction.evaluate_prediction` and pins hand-computed literals. The `macro_f1` secondary is rendered present-when-present and is proven unable to affect any ordering | the production workflow does **not** evaluate secondary metrics — tuner-side evaluation, `ExperimentRecord` persistence and workflow transport are **Step 10**'s (Q-09-7 = B); **no real oxford_iiit_pet interpretation run** |

## Maturity pins carried by this pack at PR0 (design §3.5)

- `.py` under `examples/` is sanctioned ONLY as pack plugin source at
  `examples/<pack>/plugins/*.py` (D14-2 exercised its named relaxation
  ownership; production imports of `examples.*` remain forbidden);
- no top-level `task_description` / `forward_contract` YAML under `examples/`
  — **RE-SCOPED by Step 12 / PR-12d D5, its named relaxation owner**: such a
  YAML is legitimate exactly while a shipped composition manifest RESOLVES
  it. An unbound one is still the hand-written parallel copy the pin was
  written against, and the guard computes its exemption from the manifests
  rather than from a filename allowlist.

## Not in this pack, by design

No images and no archives in the TREE — `images.tar.gz` (SHA-pinned in
`PROVENANCE.md`) lives machine-local via
`tools/example_packs/fetch_oxford_iiit_pet.py`; the framework receives the
root as the data-path seam's `data_dir`. No cache.

**Corrected at PR-12d D-FINAL**: this line also said "no launcher", which
became false when the composed entrypoint landed —
`--task_composition configs/task_composition/pets.yaml`. See the README.


## Runner role and L3 evidence freshness (Step 10 / P5+P6 C7)

**`scripts/run_pets_gate2.py` is an L3 REAL-EXECUTION EVIDENCE HARNESS**,
not an alternate way this task "runs". Its ORCHESTRATION claims (binding
resolves · direction correct · secondaries observational · Health binds
state C) were TRANSFERRED to the generic-loop closure tests
(`tests/unit/workflows/test_step10_p56_c6_three_task_closure.py`), which drive
all three tasks through the ONE production `run_workflow`. What survives here
is the distinct real-execution failure class nothing cheaper owns.

**Retirement disposition — Step 12 / PR-12d D8b.** This paragraph used to end
*"Full retirement is blocked on **CAP-SCOPE**: until task-owned scope
construction exists, the generic loop cannot execute real contrast-task
training, so those claims have no generic owner to move to."* Both halves are
now false — CAP-SCOPE landed at PR-12bc, and `G-12d` executed this pack's real
training, inference and scoring children through the composed chain. The runner
is nonetheless **RETAINED, not retired**: it is the only harness that runs the
pack's real data path WITHOUT the composed chain, so it is what separates *the
pack is broken* from *the composition is broken*. See the runner's own
docstring for the full decision.

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

**§10.6 freshness, re-audited at PR-12d D8b — SUPERSEDED, not refreshed.**

| | |
|---|---|
| dependency diff | `c9031369..HEAD` over the runner's real-execution surface touches **46 files**, including `train_engine_sandbox.py`, `inference_single.py`, `denoising_score_single.py`, `evaluation_metric.py`, `deliverable_spec.py`, `scope_artifact.py` and both `*_data_path.py` |
| verdict | the L3 rerun evidence above is **NOT current**; under §10.6 alone a further bounded rerun would be required |
| disposition | **NOT refreshed by rerunning the harness. SUPERSEDED by `G-12d`**, which executed the SAME real-execution failure class — real decode → production training engine → inference → deliverable codec → metric handle — through the composed chain at a LATER SHA. Newer real execution of the same class is stronger evidence than re-running the older harness, so no rerun was performed |
| the exception | `pets.pack_health_family_on_a_fresh_deliverable` is the ONE claim `G-12d` does **not** supersede: the composed run fired zero gates (`health_gate_results: []`). For that claim the freshest evidence remains the `c9031369` runner rerun above, and it is stale by this diff. Recorded as **OPEN**, owned by whoever next routes composed runs through Health |

The honest summary: five of this runner's six claims are superseded by better
evidence; one is stale and named. Neither is the same as "current".
