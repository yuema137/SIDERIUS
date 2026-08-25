# STATUS — `davis_future_prediction` (honest maturity; MIRROR of roadmap §15.1 / §22.12)

The roadmap (`docs/design/siderius_generic_framework_upgrade.md`) is the ONE
status authority; this file mirrors it for a reader of the pack.

## Maturity: **L4** (Step 12 / PR-12d D-FINAL, on `G-12d` evidence) — the composed production loop has now executed this task end to end

**Promoted, and only now.** Until D-FINAL this heading read *"L4 DECLARATIONS COMPLETE / L4 EXECUTION PENDING … the real composed run has NOT happened yet"*, and the pack was deliberately not labelled L4 because declaring is not executing. `G-12d` executed it.

| `G-12d` DAVIS witness | value, read from the persisted run record |
|---|---|
| workspace | `siderius_workspace/davis_ws_a4/run_output_g12d_davis_track1.json` |
| composition fingerprint | `e1c1fa2382405bda7809358deeaed4525ee67be61b34655d708b0d6879aee3ef` |
| round | 1 formal round (`is_trial: false`), `status: completed` |
| record | `davis_reference_predictor_g12d_davis_track1_001`, `status: success` |
| primary | `metric_result` = `mse` / **lower** / `0.016067206249898398` — identity crossed the child boundary with the value |
| secondaries | `psnr` / **higher** / `17.940596313717787` · `mae` / **lower** / `0.07021516840149943` — mixed direction, observational |
| **objective** | the run log records `[objective] task-declared objective applied: 'smooth_l1'/None -> 'custom'/'davis_exact_l1' (the task declares this; the planner does not choose it)`. `training_history.objective_kind` is `custom`, fingerprint `78c7740b…`. **The planner chose `smooth_l1`; the task's declaration overrode it** — which is the whole point of F-12d-31, observed live |
| training | 20 epochs planned, `final_loss 0.07432091981172562` |
| diagnosis | `state: ok`, `validation_state: present`, `comparability: established` |

**What this promotion does NOT claim.**

1. **No scientific claim.** `mse 0.016067` is an OBSERVATION. §I excludes model
   quality, benchmark improvement and score magnitude from `G-12d`'s PASS
   criteria. Note also that the run's own reflection prose called the loss
   *"smooth_l1/custom"* — LLM narration is not authority about what executed;
   the applied objective is `davis_exact_l1`, per the objective line and the
   persisted `objective_kind`.
2. **The pack's Health family did NOT run on the composed path.**
   `health_gate_results` is `[]` in this record — a composed run fires ZERO
   gates. Step 08c's demonstration of this pack's Health family through the
   D14 direct-execution runner stands **as a runner claim** and must never be
   restated as a composed-path claim.
3. **One round, not a chain**, and no last-frame-copy baseline comparison was
   computed by the composed run.

Since D14-3 this track RUNS: real DAVIS frames → `execute_tools/davis_data_path.py` (frozen window transform, clip-manifest scope) → the production training engine (real R2+R3) → inference → the npz deliverable → global **MSE** through the Step-06 handle. Gate-2 PASS evidence: `docs/design/generic_framework_upgrade/d14_executable_data_path/pr_d14_3_davis_executable.md` §6 C7 (workspace `/home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_20260818b/`). The rows below record each seam honestly:

| contract / seam | representable today? | status in this pack | evidence |
|---|---|---|---|
| sequence-level identity (60 / 15 / 15) | yes — from official metadata (`db_info.yaml`) | **LANDED** (PR0): `data/manifests/sequences.csv` + `SHA256SUMS`, frozen rule (`PROVENANCE.md`) | `tests/unit/examples/test_davis_future_prediction_pack.py` (integrity pin, exactly 90 rows 60/15/15, pairwise disjoint, rule re-derived over the tracked val ∪ final, synthetic-rule test) |
| **clip identity `(sequence_name, start_frame)`** | derived by a PURE rule from on-disk frame counts | **LANDED (D14-3)**: `data/manifests/clips.csv` — 600 clips (60×8 / 15×4 / 15×4), byte-pinned; rule `clip_starts` in `execute_tools/davis_data_path.py` | `tests/unit/execute_tools/test_davis_clip_rule.py` (31 hand-computed cases); `tests/unit/examples/test_davis_execution_manifest.py` (pins, per-sequence re-derivation, **sequence-scope disjointness**) |
| `ModelIOContract` | **DECLARABLE** (rank-agnostic; differing fixed T extents; only `B` shared) | **DECLARED** (L0/L1): `declared/model_io_contract.json` — `[B, 3, 8, 128, 224] float32 → [B, 3, 4, 128, 224] float32`, `output_semantic == continuous`, `class_cardinality is None` | constructs through `agent/schemas/model_io_contract.py`; derived properties asserted |
| `MetricSpec` mse (lower, golden) | **DECLARABLE** (scalar-only, `PresenceScoreabilityContract`); aggregation named as the FROZEN global mean over clips × C × T × H × W | **DECLARED**: `declared/metric_mse.json` | constructs through `execute_tools/evaluation_metric.py`; `direction == lower` |
| `MetricSpec` psnr (higher, optional) | **DECLARABLE** — the same global-MSE aggregation with transform `psnr_db`, `transform_params.data_range = 1.0` | **DECLARED**: `declared/metric_psnr.json` | `direction == higher`, `data_range == 1.0` |
| `MetricSpec` mae (lower, optional) | **DECLARABLE** (`mae` is not loss-shaped: what makes an id a loss is that it names the training objective, not its formula — `evaluation_metric.py`) | **DECLARED**: `declared/metric_mae.json` | `direction == lower` |
| `DatasetProfile` | **DECLARABLE since PR-12bc B2 (Q-12-4)**: the profile is generic identity (`partition_count`) plus an OPAQUE task-owned `topology` plus the two REQUIRED declared file sets — the pre-B2 shape that forced 1-D-segment, two-channel HDF5 semantics is gone | **DECLARED (D6)**: `declared/dataset_profile.json` — `partition_count: 60` (the committed Gate-2 train clip subset the shipped manifest binds), a DAVIS `topology` (clip identity `(sequence_name, start_frame)`, the frozen frame transform, and the DIFFERING temporal extents 8 in / 4 out), `anchor_selection_files: [0]`, `health_peek_files: [0]`. **No PSD, segment, sampling-frequency or `.h5`-pattern field exists** — the fabricated fixture values F-12d-4 condemned were DELETED, not carried. Both file sets are declarations of LEGALITY, not science claims: DAVIS' scope authority refuses the `anchors` strategy by name, and its Health family declares no `peek_file_indices`, so neither set has a consumer today and neither was invented to look meaningful | `tests/unit/examples/test_step12_pr12d_d6_davis_declarations.py` (field-by-field absence on BOTH the composed wire form and the bytes on disk; the differing temporal extents asserted twice — in the opaque topology and in the TYPED `ModelIOContract`) |
| `DeliverableSpec` | **NOT representable**: per-file HDF5 naming / storage | named as a seam | — |
| frame reader / decode / resize 128×224 / window materialization / tensor hashes | executable CODE + committed execution manifest | **LANDED (D14-3)**: `decode_frame` / `load_window` (ONE authority) + `data/manifests/execution.json` (transform + window + clip-rule declarations, 10 window probe hashes) | `test_davis_execution_manifest.py` (synthetic exact-slice identity; REAL two-process probe parity); `tests/unit/execute_tools/test_davis_data_path.py` (probes THROUGH the seam) |
| reference plugin (small conv/recurrent predictor) | loads through the real plugin mechanism | **LANDED (D14-3)**: `plugins/davis_reference_predictor.py` — Conv3d residual over the last context frame, `[B,3,8,128,224] → [B,3,4,128,224]`, sanctioned plugin SOURCE (dynamically loaded, never imported) | `tests/unit/examples/test_davis_reference_plugin.py` (incl. the zero-head last-frame-copy property) |
| Gate-1 / Gate-2 / persistent NESTED clip subsets | committed first-clip-per-sequence subsets | **LANDED (D14-3)**: `data/manifests/gate2_{train,validation,final}.csv` (60/15/15, byte-pinned, strict nested subsets) | `test_davis_execution_manifest.py`; Gate-2 PASS at the D14-3 ledger §6 C7 |
| licence terms of the downloaded TrainVal-480p artifact | verifiable from primary sources | **VERIFIED AND PINNED (D14-3)**: `PROVENANCE.md` §D14-3 VERIFICATION — four primary sources quoted, verdict COMPATIBLE, zero redistribution, annotations not consumed; archive SHA-256 pinned | `tests/unit/examples/test_davis_future_prediction_pack.py` (licence pins); `tests/unit/examples/test_fetch_davis_tool.py` (pin ↔ PROVENANCE mirror) |
| pack-level runtime task binding | **REPRESENTABLE since Step 10 / P1**: a composed run reads the task config its manifest NAMES | **DECLARED (D6)**: `declared/task_config.yaml` — DAVIS' own `task_description` + prose `forward_contract` (`[B, 3, 8, 128, 224] float32` -> `[B, 3, 4, 128, 224] float32`, `num_classes: 0`). Regime-A prose deliberately: `declared/model_io_contract.json` is this pack's TYPED forward declaration and no composition family references it (§A.2), so authoring a second `model_io:` block here would be a duplicate authority | the D6 module asserts the composed description and contract come from the PACK, never from `configs/task_config.yaml` |
| composed task binding (the operator entrypoint) | the ten-plus-two manifest families | **DECLARED (D6)**: `configs/task_composition/davis.yaml` — an ENTRYPOINT POINTER (Q-12d-1) holding refs into this pack and no second copy of any task semantics. Binds the data path with `config: {clips_path: ...}` (**not** `sequences_path` — `load_davis_clips` refuses a sequences manifest by header, PR-12bc B8), the pack's Health family, the pack's model-plugin root and its `loss_plugins` objective root; `interpretation_blocks` / `proposal_blocks` / `implementor_blocks` are NAMED absences, so a composed DAVIS run renders no science rather than TIDMAD's | the D6 module composes the SHIPPED manifest through `compose_run_task_bindings` and builds a real 60-clip scope from it |
| training objective (R1) | §22.9a freezes exact MAE / L1; the built-in `smooth_l1` cannot express it (`LossConfig.beta` is constrained to `[0.1, 10.0]`, so the `beta=0.01` approximation is REFUSED by the schema — and widening a production constraint to fit one task is forbidden) | **DECLARED (D4c) + REACHABLE (D6)**: `plugins/davis_exact_l1_loss.py` (`PLUGIN_LOSS_TYPE = "davis_exact_l1"`), reached by `LossConfig(loss_type="custom", loss_name="davis_exact_l1")` through the shipped manifest's `loss_plugins:` root | the D6 module asserts the refusal of `smooth_l1(beta=0.01)` and the presence of the declared objective root |
| the SAME MAE computation in THREE lifecycle roles (§22.9a) | training objective (R1) · validation observation (R3) · terminal secondary metric — one quantity, three roles | **DECLARED AND KEPT DISTINCT (D6)**: three different carriers with three different authorities — `LossConfig`/`davis_exact_l1` (no direction, no aggregation), `TrainingHistory.objective_kind = "mae"` with a per-epoch `validation_objective` (no metric identity), and `MetricSpec(id="mae", direction="lower")` bound to `DavisMaeMetric` as an OBSERVATIONAL secondary beside the `mse` primary. The string `mae` coincides across two of them, which is exactly §22.9a's point — the distinctness is in the carriers, not the name | the D6 module asserts no carrier plays two roles, and that the objective's name (`davis_exact_l1`) is not any declared metric id |
| health applicability | since **Step 08b** `configs/health_checks.yaml` is FRAMEWORK POLICY ONLY (disposition → gate role/cadence/actions); task science lives in task-owned configs | **LANDED (Step 08c C4) — task-owned Health family through the EXTERNAL interface.** `declared/task_health.yaml` (facts: `encoding_family=continuous_float`; ONE BLOCKING gate `davis_dispersion_blocking`, `min_dispersion=0.04` — FROZEN, measured ONCE against the single preserved healthy artifact: dispersion 0.2156402715035823 over 5,160,960 float32 samples, ≈5.4× above the floor; single-artifact caveat carried in the config) + `plugins/_davis_health_views.py` (provider `davis.sample_views` exposing the standard `continuous_samples` view as the FULL decoded stream — sorted clip keys → C-order ravel → concat, native float32, NO cap/sampling; underscore-prefixed so directory scanners never exec it — the config's explicit `kind: file` ref is its only loading path). Binds state C — never the legacy-omitted TIDMAD default. Its metric stays scalar-only (D18). Runner Health-evidence stage **LANDED (08c C5)**: `scripts/run_davis_gate2.py` evaluates this family on each run's FRESH npz through the ONE shared `scripts/_gate2_health_stage.py` (explicit state-C binding, additive `health` block). 08c Gate-2 PASS at `ede11fd5`: the fresh npz reproduced the preserved artifact byte-identically and the full 5,160,960-sample view PASSED at the frozen floor with the frozen dispersion persisted | `tests/unit/examples/test_davis_health_family.py` (state-C chain; hand-computed synthetic FAILED/PASSED pair + §2.9 near-collapse control; §2.12 codec parity on production-written bytes; skip-guarded machine-local real-npz evidence reproducing the frozen dispersion EXACTLY; provider ERROR paths incl. unequal-shape refusal; fail-closed pair; DAVIS identifier census) |
| training history / diagnosis (R2/R3 MAE curves + optional validation PSNR) | the framework's `TrainingHistory` / `TrainingDiagnosis` (Step 07a) are task-generic: the schema carries this pack's semantics (`objective_kind="mae"`, `observations={"validation_psnr": …}`) without change | **L1 — fixture-backed**: `expected/training_history_l1_fixture.json` + `expected/training_diagnosis_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real training output; validation identity = the 15 sequences, clip identity D14) consumed by rung **B-07a-1** (`tests/unit/examples/test_step07a_b1_diagnosis_structure_rung.py`) — KEPT verbatim (cumulative corpus), and since **D14-3** the ADDED real-component pair `expected/training_history_real_component_fixture.json` / `expected/training_diagnosis_real_component_fixture.json` carries the REAL bounded gate run's R2/R3 (`objective_kind="smooth_l1"`, the MAE-family realization the frozen LossConfig admits) through the same rung | the rung derives the diagnosis from the fixture through the SAME boundary TIDMAD uses and pins the expected verdict shape as literals |
| metric-direction policy / planner-reflector rendering (Step 07 PR 07b) | the tuner's ordering authority and the prompt renderers consume a `MetricSpec` — this pack's `declared/metric_mse.json` (`mse`, `lower`-is-better) is consumed unchanged | **L1 — declaration-backed**: rungs **B-07b-1** (ordering inverts exactly under the declared direction) and **B-07b-2** (the planner/reflector blocks render this pack's metric identity and direction words, and its `expected/training_diagnosis_l1_fixture.json` renders as a compact dynamics line) — `tests/unit/agent/llm_bridge/test_step07b_c5_rendering.py`; no executable path | the rungs load the pack's OWN declared spec and 07a fixture; **no real davis_future_prediction execution — that is D14** |
| interpretation evidence (Step 09 PR 09a) | the same task-generic interpreter surface, on the pack that actually inverts it: `declared/metric_mse.json` is **lower**-is-better, so "best" is the SMALLEST value; `declared/metric_psnr.json` (higher) and `declared/metric_mae.json` (lower) are its declared secondaries | **L1 — fixture-backed**: `expected/interpretation_evidence_l1_fixture.json` (hand-authored, labelled `l1_fixture`, NOT a real tuning output) consumed by rung **B-09a-1** (`tests/unit/examples/test_step09a_interpretation_evidence_rung.py`). This is the load-bearing row of that rung: a direction literal anywhere on the interpreter's path would report the worst model as the best, and every expectation is a hand-computed literal. `psnr` is scored; `mae` is DECLARED BUT UNAVAILABLE — the contract's third state, a named absence that must never render as a number | the production workflow does **not** evaluate secondary metrics (**Step 10**, Q-09-7 = B); **no real DAVIS interpretation run** |

## Maturity pins carried by this pack at PR0 (design §3.5)

- no production `.py` under `examples/` — valid through PR0 / Step 07;
  — since **D14-3**, `.py` under `examples/` is sanctioned ONLY as pack plugin source at `examples/<pack>/plugins/*.py`; production imports of `examples.*` remain forbidden;
- no top-level `task_description` / `forward_contract` YAML under `examples/`
  — **RE-SCOPED by Step 12 / PR-12d D6**, the pin's own named relaxation owner: a
  pack's bound task config is sanctioned at exactly
  `examples/<pack>/declared/task_config.yaml`; anywhere else under a pack is still a
  parallel copy no composition manifest binds.

## Not in this pack, by design

No frames, no archive, no archive listing, no cache.

**Corrected at PR-12d D-FINAL.** This list previously also claimed "no clip
manifest, no loader, no launcher". All three had become false and the line was
never revisited:

* **clip manifest** — `data/manifests/clips.csv` ships (11,537 bytes) and its
  digest is pinned in `SHA256SUMS`. `davis.yaml` binds it as the scope
  authority via `clips_path`.
* **loader** — `execute_tools/davis_data_path.py` implements the frozen
  four-method `TaskDataPath`, including `training_dataset` /
  `validation_dataset`.
* **launcher** — the composed entrypoint is
  `--task_composition configs/task_composition/davis.yaml`; see the README.

A "by design" absence list is exactly the kind of prose that keeps reading as
true after the thing it denies has landed, which is why the D-FINAL doc-sync
step checks it against the shipped tree rather than against memory.


## Runner role and L3 evidence freshness (Step 10 / P5+P6 C7)

**`scripts/run_davis_gate2.py` is an L3 REAL-EXECUTION EVIDENCE HARNESS**,
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
training, inference and scoring children through the composed chain with its
declared exact-L1 objective. The runner is nonetheless **RETAINED, not
retired**: it is the only harness that runs the pack's real data path WITHOUT
the composed chain, so it is what separates *the pack is broken* from *the
composition is broken*. One claim —
`davis.last_frame_copy_baseline_comparison` — is **intentionally not
transferred**; see the runner's docstring for the full decision.

**§10.6 freshness audit — RERUN TRIGGERED, evidence now CURRENT.**

| | |
|---|---|
| prior evidence | `/home/klz/Data/SIDEREIS_DATA/step08c_davis_gate2_20260818/gate_evidence.json` at `ede11fd5` — verdict PASS |
| dependency diff | `ede11fd5..HEAD` over the runner's real-execution surface changed **semantics-bearing** files, including the very Health checks this pack exercises (`sample_dispersion_floor`), plus `evaluation_metric.py` and `task_data_path.py` |
| verdict | prior evidence NOT assumed current → bounded rerun REQUIRED (no LLM, GPU only) |
| rerun | `/home/klz/Data/SIDEREIS_DATA/step10_p56_c7_davis_20260821/gate_evidence.json` at `c9031369` — verdict **PASS** |
| comparison | `mse` **BIT-EQUAL** (`0.017289766656259548`, still under the last-frame-copy baseline `0.017392322972086136`) and the dispersion **BIT-EQUAL** (`0.2156402715035823`); same gate verdict and action (`continue`) |

The changed dependencies were therefore behaviour-preserving for this track —
established by rerunning, not by inspection.

**§10.6 freshness, re-audited at PR-12d D8b — SUPERSEDED, not refreshed.**

| | |
|---|---|
| dependency diff | `c9031369..HEAD` over the runner's real-execution surface touches **46 files**, including `train_engine_sandbox.py`, `inference_single.py`, `denoising_score_single.py`, `evaluation_metric.py`, `deliverable_spec.py`, `scope_artifact.py` and both `*_data_path.py` |
| verdict | the L3 rerun evidence above is **NOT current**; under §10.6 alone a further bounded rerun would be required |
| disposition | **NOT refreshed by rerunning the harness. SUPERSEDED by `G-12d`**, which executed the SAME real-execution failure class — real frame decode → production training engine → inference → npz deliverable codec → metric handle — through the composed chain at a LATER SHA. Newer real execution of the same class beats re-running the older harness, so no rerun was performed |
| the exceptions | TWO claims `G-12d` does **not** supersede: `davis.pack_health_family_on_a_fresh_deliverable` (the composed run fired zero gates — `health_gate_results: []`) and `davis.last_frame_copy_baseline_comparison` (not computed by the composed run, and INTENTIONALLY NOT TRANSFERRED per D8b). For the Health claim the freshest evidence remains the `c9031369` rerun above and is stale by this diff — recorded **OPEN** |

The honest summary: four of this runner's six claims are superseded by better
evidence, one is stale and named, one is a decided non-transfer. None of those
three states is "current".
