# Step 07 — Tuner Planning & Policy + Training Diagnostics (+ Persistent Example Baseline, + Measurement) — acceptance / decomposition design (parent)

## 0. Status and provenance

| Field | Value |
|---|---|
| Roadmap rows | §15.1 "§7a Tuner planning & policy (+ §20.2 training diagnostics)", step 7; "§7e Tuner measurement/verification", step 7; Rev 5 §22.12 rows **07 / 07b / 07c**; §22.23.6 **PR0** |
| Module sections | roadmap §7a, §7e, §20.2, §22.2–§22.8, §22.9a, §22.11a, §22.23 |
| Design base | `03225ac9` (master; Rev 5.3 **READY FOR OPERATOR FREEZE**, Q4 = operator's mark — this parent is written against that text and becomes actionable only once Q4 is marked; nothing here pre-empts Q4) |
| Depends on | Steps 00–06 all **MERGED** (06 = PR #213, `02f382eb`); Rev 5 §22 (Q1/Q2/Q3 RESOLVED; Q4 pending) |
| Decomposition | **FOUR PRs — `PR0` → `07a` → `07b` → `07c`** (Q2, operator-resolved in Rev 5.3; re-verified from source in §7 below — the split is real, not inherited) |
| Status | **PARENT DRAFT — awaiting operator review.** No child doc exists yet; no implementation authorized. Per the kickoff protocol: parent acceptance/decomposition first → PR0 detailed design → PR0 freeze/implement → 07a … |
| Freeze posture | This parent is a **LIVE governance document** (Step-02/04 multi-PR precedent): it owns Step-level scope, authority map, decomposition, per-PR acceptance contract and the completion contract; each child owns its implementation-ready design and later its ledger. Frozen contracts live in the children |

This document deliberately stops short of per-commit checklists and
field-level schema decisions — those belong to the child docs. What it
freezes is: what each PR must deliver, which parity surfaces it must hold,
which contrast evidence it must produce, which live consumer it must reach,
which Gates it owes, and what it must **not** touch.

---

## 1. Final observable Step effect

> **Training dynamics become first-class typed evidence** (R2 train-objective
> history and R3 validation-objective history are produced by the trainer,
> condensed by the tuner into a deterministic `TrainingDiagnosis`, and
> persisted on the existing record — never prompt-dumped); **the tuner's
> policy is metric-generic** (incumbent / best / threshold / skip / bypass /
> efficiency logic consumes the golden metric's declared direction and identity
> through the Step-06 handle, and the planner/reflector render task content,
> direction wording and diagnosis lines from owned renderers instead of
> hardcoded prose); **pre-phase measurement builds its probe batches from the
> resolved dataset profile** with identity keys byte-stable; and the three
> persistent tracks exist as **user-facing example packs** at their honest
> maturity (`examples/tidmad|oxford_iiit_pet|davis_future_prediction/`) from
> the very first Step-07 PR.

**The precise invariants (not "no literals"):**

1. No comparison, ranking, threshold or "better/worse" wording anywhere in
   the tuner's planning/policy path or its planner/reflector rendering
   independently restates the golden metric's direction or name; every such
   fact resolves from the bound `EvaluationMetric` handle (Step 06).
2. Training observations and training diagnosis are produced ONCE
   (trainer → tuner deterministic layer), carried on the EXISTING transport
   (results JSON → executor → `ExperimentRecord`), and reach an LLM only
   through an explicit, tested renderer (§22.6 item 5) — never because a
   serializer dumped a record.
3. Measurement data-feeding derives from the resolved profile; identity
   hashes, comparability and store keys are unchanged.
4. Under TIDMAD every rendered planner/reflector byte is unchanged **except
   the explicitly owned direction/diagnosis rendering deltas of 07b** (the
   OD-S4-1 pattern: declared upfront, mechanically attributable, nothing
   else moves).

### 1.1 What Step 07 explicitly does NOT claim

- It does **not** build the Interpreter's or Proposer's rendering of
  diagnosis / metrics / health / cross-iteration knowledge — Step 09 (§22.6
  item 5, OD-20-5).
- It does **not** migrate workflow/resume best-score comparisons (Step 10),
  `per_file_best` / dashboard direction literals (M2 peripheral), or the
  interpreter sign-band (Step 09) — the D1 consumer split of §22.18.
- It does **not** make Pets or DAVIS executable — no reader, no loader, no
  data path, no downloads: that is **D14**, the dedicated milestone
  immediately after this Step (§22.11a). Track B/C evidence in Step 07 is
  L1 with the EXACT frozen task semantics (plus L2 through the real trainer
  on a *contrast profile* that is honestly NOT labelled Track B/C).
- It does **not** resolve D16 (lexical `loss` id ban), D17 (mandatory
  scalar) or D18 (`file_vector=[]` semantics) — recorded where they surface
  (PR0's `log_loss` declaration; §18), owned by Step 12 / Step 08.
- It does **not** rename `denoising_score` / migrate record schemas (D1
  row, roadmap §18: not authorized).
- It does **not** design multi-task binding of a whole example pack (Step 12)
  or the example launcher CLI (Steps 10/12, §22.23.11).
- It does **not** change the frozen TIDMAD score formula, loss math,
  retry/round/timeout/signal semantics, or the calibration values.

---

## 2. Current source census (audited at `03225ac9`)

Every row was read at the cited line, not inferred from the roadmap. Where
the roadmap's own anchors are stale, the correct anchor is given and the
correction is listed in §15 for Checkpoint E.

### 2.1 Training-history / validation transport (07a's seam)

| Surface | Current state | Disposition |
|---|---|---|
| `execute_tools/train_engine_sandbox.py:947` (streaming) / `:702` (legacy) | epoch loops; per-epoch mean train loss appended `:1178-1179` / `:758-759`; summary is EXACTLY three keys `final_loss`, `loss_history`, `model_params` (`:1217-1221`, `:763-767`), written raw at `:1479-1489`; **no `model.eval()`, no `torch.no_grad()`, no second loader anywhere** — validation loss does not exist | **07a OWNED — LIVE.** Add the R3 validation pass + a typed additive `TrainingHistory` payload; keep the three legacy keys byte-identical (§8) |
| `criterion = get_criterion(...)` `:884` / `:683`; plain callable `nn.Module` (`ml_models/loss_models_sandbox.py:321-343`) | re-callable under `no_grad` as-is | **KEEP** — no new loss abstraction (§20.2 DECIDED) |
| trainer argparse `:1243-1343` | `--sample_set_json`, `--train_portion`, `--train_base_seed`, `--order_strategy`, `--file_order_json`, `--runtime_observation_out`, `--runtime_policy_json`, `--dataset_profile_json`, `--model_io_json`, … — **no validation/eval sample-set flag** | see OD-S7-1 |
| `TIDMADEpochDataset` `:289/:303-341` | sample-set generic (`{file_index: [segments]}`); filenames via `profile.dataset.training_file_name(...)` `:1011` only | a validation set over the VALIDATION file family (`validation_file_name`, `dataset_config.py:127-142`, today read only by inference/scoring) is buildable with the same class once the filename accessor is parameterized |
| legacy single-file mode `:1466-1477` | no sample set, no eval set | **KEEP valid** without validation history (OD-20-4 legacy tolerance; §22.2 R3 "fully supported" contract does not apply) |
| tuner builds TWO SampleSets `ml_hyperparameter_tune_agent.py:4671-4687` (`train_sample_set`, `eval_sample_set`, comment `:4656` "training and validation") | `eval_sample_set` reaches only segment counting `:4713-4714` and `sandbox.evaluate_metric(..., sample_set=eval_sample_set)` `:5442`; it is placed on `active_params` `:4751` but **`agent/skills/training_skill/wrapper.py:5-23` enumerates kwargs and drops it**; `TidmadSandbox.execute_training` `core/sandbox_executor.py:1268-1282` has no such parameter; argv assembly `:1340-1424` emits none | **07a OWNED.** OD-20-3 asked the audit to prove whether the existing boundary can express a validation subset: the SPLIT exists and is run-bound (no new split concept), but the TRANSPORT to the trainer does not — three signatures + one argv flag are needed (OD-S7-1) |
| `TrialConfig.train_validation_align=True` (`agent/schemas/hyperparam_tuning.py:774-777`, seeds `:4602-4606`) | train and eval select the SAME segment indices; the separation is the FILE FAMILY (`abra_training_*` vs `abra_validation_*`), i.e. physically distinct recordings | validation objective on `eval_sample_set` IS a held-out observation for TIDMAD; record this explicitly in 07a (no new "val split" concept) |
| executor read-back `core/sandbox_executor.py:1552-1571` | forwards the WHOLE results JSON verbatim as `results` (no key enumeration, no schema); `execute_scoring` re-merges the same JSON `:2025-2029` | additive keys flow through unchanged; 07a adds the missing typed boundary (a Pydantic model for the trainer results payload — CLAUDE.md "never pass raw … without validation" applies to the trainer→tuner contract too) |
| `ExperimentRecord` `agent/schemas/hyperparam_tuning.py:368-379` | `final_loss`, `loss_history`, `model_params` — unvalidated; **no `loss_type` field** (the same-loss rank digs `params["loss_config"]["loss_type"]` at tuner `:5749-5750`); `metric_result`/`metric_refusal` `:628-651` with validator `:654-690` | **07a OWNED — additive** typed `training_history` / `training_diagnosis` (names are the child's to freeze); `final_loss` semantics UNCHANGED (last-epoch train loss — six dashboard readers + two scripts depend on it) |
| record write `ml_hyperparameter_tune_agent.py:5900-5904` (roadmap says `:5776`) | copies the three keys | 07a extends here — through an extracted boundary, not inline (§12.3) |
| `loss_history` readers | ZERO programmatic readers (dashboard/interpretation/workflow/per_file_best/resume: none). **BUT it is LLM-visible twice per round**: `reflect_results = {**train_results, **score_results}` `:5865` → `brain.reflect` `:5866` → `agent/prompts.py:1370` `json.dumps(actual_results)`; and the planner's verbatim 3-record window `agent/prompts.py:901-929` (condensed records drop it, `_CONDENSED_KEYS` `:852-864`) | **the parity trap of 07a**: any NEW key that reaches `train_results` changes reflector bytes and the WF-2 kwarg key set → 07a MUST keep both renders byte-identical (§8.2) |
| `nodes/result_interpretation_agent/result_interpretation_agent.py:2006-2137` `tuning_output_to_model_run_summary` | records DISCARDED; per-round condensation precedent = `RoundHealth` `:1936-1970` (`agent/schemas/health_feedback.py:255-268`, deterministic, `provenance` label); **no loss information survives** into `ModelRunSummary` | **NOT Step 07** — the per-round diagnosis condensation onto `ModelRunSummary` is Step 09's transport (OD-20-5); 07a only guarantees the record carries what Step 09 will condense |
| pseudo/stub | `tests/pseudo_data/train_outputs/*/execute_training.json` carry 5-epoch `loss_history`; `StubSandbox.execute_training` `core/sandbox_executor.py:2174-2178` fabricates `loss_history=[final_loss]` (ONE point) | 07a updates BOTH pseudo routes to emit a plausible multi-epoch train + validation history (test infra; needed so pseudo-training Gates/tests can exercise diagnosis) — OD-S7-4 |
| runtime control | the validation pass runs INSIDE the training subprocess: wall time is observed by the RT2 session; adaptive verification counts "the first production steps" | 07a MUST keep admission/verification/timeout/signal semantics unchanged and prove the validation pass is neither counted as training steps nor unbounded (bounded by the already-bounded eval sample set) — §8.2 |
| `docs/design/genericity_contract.md` | four seams; no training-history seam; working rule `:186` "update this doc first when a new abstraction is needed" | 07a adds **Seam 5 — Training observation** (History/Diagnosis) BEFORE implementation |

### 2.2 Metric-direction policy (07b's first half)

The tuner binds `run_metric` ONCE (`:3869`) and uses it ONLY as an opaque
handle to `sandbox.evaluate_metric` (`:5441`). **`grep "run_metric\."` → 0
hits; no executable direction consumer exists in the 7,180-line file.** The
comment at `:3864-3866` ("identity, direction and the acceptance contract …
exactly one source") overclaims — direction is bound, never read.

Direction-bearing sites (all HIGHER-is-better literals unless noted):

| Site | Role |
|---|---|
| `_best_trial_winner` `:1480-1504` (`max(..., key=denoising_score)`) | trial winner → skip / bypass / formal inheritance |
| `_should_skip_formal` `:1507-1543` (`-inf` = disabled `:1541`; `winner < threshold` `:1543`) | skip gate |
| `_should_bypass_formal_time_budget` `:1546-1563` (`+inf` = disabled `:1561`; `winner >= threshold` `:1563`) | bypass gate — **the two disable-sentinels are polarised opposite ways; under LOWER both sentinels AND both operators invert (a two-axis change, §8.3)** |
| `_resolve_formal_comparison_thresholds` `:1566-1611` (`bootstrap = -inf` `:1606`; `reference + delta` `:1608-1613`) | threshold arithmetic; anti-phantom rationale `:1596-1605` |
| skip/bypass call sites `:4304-4342`, `:5099-5117` (banners hardcode `<` / `>=`) | round loop |
| planner score-table incumbent `:4406-4419` (`max`) | decides which table the planner SEES — **missing from the §16 D1 census** |
| collapse penalty `:1987` (`denoising_score = penalty_score`) | a "penalty" is direction-signed — missing from the census |
| reflection block `:5724-5834`: baseline substring `"baseline" in exp_id` `:5732` (roadmap says `:5424`; the same rule is ALSO in the planner prompt `agent/prompts.py:25`), `best_score = max` `:5735`, `rank` via `sorted(reverse=True)` `:5739`, **5 % efficiency band `:5794-5796`** (roadmap says `:5486`), `is_more_efficient` `:5802-5819`, `is_new_best` `:5826-5828` | reflection context — feeds PB-2 / WF-2 |
| `sorted(all_same_loss_finals)` `:5757-5761`, `min(same_loss_finals)` `:5831` | the LOSS rank — genuinely lower-is-better, **NOT a D1 consumer**; a direction-parameterized rewrite must not touch it |
| 4/5-track finalization `:6330-6377` (roadmap says `:6018-6064`) → output projection `:6452-6470`, `:6484` | `best_*` / `best_formal_*` / `best_valid_*` / `best_valid_formal_*` / `best_valid_trial_*` |
| `AttemptTransition` / `AttemptDecision` `:311-360` | ZERO production consumers (only `tests/.../test_control_boundary.py`); the `resolved_action` hazard is fully live: declared round-scoped `:4291`, written 5 levels deep `:5517`/`:5544`, read `:5535`/`:6250` — roadmap §7a finding 16: **WIRE or REMOVE, never leave the third state** → 07b (OD-S7-6) |

Outside the tuner (NOT Step 07, listed so nobody re-scopes them in): `core/resume.py:438,551,637`; `workflows/model_exploration.py:2758-2762` (roadmap says `:2740`); `nodes/interpretation_helpers.py:284-289`; `execute_tools/per_file_best.py:63,310,478-487`; `core/campaign_artifacts.py`; dashboard.

Existing pins that 07b will re-anchor (§14): `test_delta_gates.py` (`negative_infinity_bootstrap`; anti-phantom parametrized over VALUES only — direction is NOT parametrized), `test_formal_launch_decision.py`, `test_valid_trial_winner_drives_formal.py`, `test_valid_candidate_selection.py`, `test_tuning_agent.py:266-269, 381-397`, `test_gate_integration.py`, `test_degeneracy_handling.py`, `test_control_boundary.py`, `test_step06_c2_tuner_metric_binding.py` (direction stubs — scoring route only), `wf2_reflect_call_surfaces.json` (reflection-context KEY SET). No test pins the 5 % band or the baseline substring directly.

### 2.3 Planner / reflector prompt surface (07b's second half)

`agent/prompts.py` (1,389 lines):

| Family | Lines | Content |
|---|---|---|
| direction | `:12` "**maximize** the `denoising_score`", `:37`, `:59-60`, `:246` "GOOD if … HIGHER than the best", `:248` "BAD if … LOWER", `:299` "Better only if it beats the best score", `:1346` "rank (1 = best)" | **07b OWNED — the explicitly authorized byte deltas** |
| metric name | `denoising_score` throughout system + user prompts (`:12`, `:68`, `:108`, `:233`, `:1343`, `:1346`, `:1370-1373`) | 07b: render metric identity from the handle |
| "read the score as validation" | `:107-115` (planner), `:233`, `:1370-1373` (reflector: "final_loss/loss_history above = TRAINING … denoising_score = VALIDATION dataset") — the compensating instruction §20.2 describes | 07b: replaced by rendered diagnosis lines once R3 exists (attributable delta) |
| §13 task-content remainder | 5-model roster `:16-21`; BASELINE REFERENCE RULE `:23-29`; COLLAPSE ADVICE `:66-95` (class-127, gate-name substrings, focal α/γ, lr, Adam→AdamW); EFFICIENCY 5 % `:97-102`, `:288-302`; 4000/200 segment anchors `:169-170`, `:271-275`; loss-type list `:183-186`; CH1/CH2 + log-space `:191-200`; `[B, 256, T]` `:1063-1067` (roadmap says `:1037`), `:1098-1100` | **07b OWNED** — "planner/reflector prompts render from the profile" is the §15.1 step-7 final effect; rendered from profile / handle / model-I/O contract with EXACT byte parity under TIDMAD (Step 01/04 pattern) |
| history filter | `_CONDENSED_KEYS` `:852-864`, `_PLANNER_HIDDEN_RECORD_KEYS` `:886`, `_planner_visible` `:889-899`, `_truncate_memory_history` `:901-929`; comment `:873-885` "removing a key … belongs to Step 07a / 09" | 07a extends the hidden set for its own additive keys (rendering decision it owns); 07b decides what diagnosis IS rendered |
| bridge surface | `LLMBridge.plan` (25 params, `agent/llm_bridge.py:765-793`; tuner call `:4422-4453`), `LLMBridge.reflect` (`:921-926`; tuner call `:5866-5868`) | WF-1 / WF-2 goldens pin the kwarg key sets |

Step-00 goldens: **PB-1** planner (3 files) + **PB-2** reflector (2 files) in `tests/unit/agent/llm_bridge/goldens/`, fixture surface `test_step00_prompt_goldens.py:53-203` (`_HISTORY_3`, `planner_fixture_kwargs`, `_REFLECT_CONTEXT`); **WF-1/WF-2** call surfaces + **REC-2/REC-3** record projections in `tests/unit/agent/tune_ml_hyperparam_agent/goldens/`. `test_pb1_full_window_boundary_is_the_deferral_line` `:261-284` records the OD-1 condensed-branch byte-instability deferral "owned by the step-07a predecessor fix" → 07b (rendering) inherits it. Regeneration rule: Step-00 §17 rule 3 (same commit as the intentional production change; three-part message).

### 2.4 Measurement / verification (07c's seam)

| Surface | Current state | Disposition |
|---|---|---|
| `core/runtime_control/gpu_measurement_data.py:61-66,117,134,156` | `INPUT_CHANNEL="channel0001"`, `TARGET_CHANNEL`, `CLASS_INDEX_OFFSET=128`, `abra_training_*.h5` glob, `int8→int16+128` — module constants; no `DatasetProfile` import | **07c OWNED — DERIVE** channel identity / encoding / filename family from the resolved profile |
| `execute_tools/probe_data.py:20-41` (`load_probe_batch`, `TIDMADDataset`, glob, `.long()`) via `probe_production.py:222`; worker uses `load_bounded_probe_batch` (`gpu_measurement_worker_main.py:279-283`) — two loaders, byte-identical output pinned by `tests/unit/core/test_gpu_measurement_data.py` | the "probe_wiring fix" migrated availability (`probe_wiring.py:63-90`) but NOT the batch builder | **07c OWNED** — one profile-derived batch builder; byte-identical batches under TIDMAD |
| `bootstrap.py:513-520` (`TIDMAD_DATA_DIR` dataset check; remedy string `:233` "readable TIDMAD directory"), `probe_production.py:17, 210-219` (`TIDMAD_DATA_DIR` fallback) | roadmap §7e finding 19 | **07c OWNED** — task-side capability resolution already exists (`execute_tools/data_paths.py:142-181` `resolve_tidmad_measurement_capability`); route these two through it |
| `gpu_measurement_worker_main.py:285` `batch.float() if model_type == "fcnet" else batch.int()` | a MODEL-NAME dtype branch inside the measurement worker; unguarded (`test_no_model_name_branches.py` does not scan `core/runtime_control/`) | **07c OWNED — DERIVE** from the run-bound `ModelIOContract` dtype requirement (Step 03/05b precedent); extend the guard's scan targets |
| planned/worker/probe `seg=40_000` / `batch=1` defaults — `gpu_measurement_identity.py:214-215`, `gpu_measurement_worker_main.py:254,266`, `probe_production.py:220-221` — a COORDINATED TRIPLE (docstring `:206-210`) | hash inputs | **KEEP as one framework-owned recipe** (Step-04 §10 boundary: recipe, not task semantics); 07c may centralize the triple but MUST NOT move it into task config; identity hashes unchanged |
| identity / keys: `MeasurementIdentity.components()` `registry_schemas.py:434-455`; `candidate_config_hash` `calibration_context.py:108-141`; planned hash `gpu_measurement_identity.py:216-224`; `calibration_key` `observation_store.py:78-110`; `data_shape_class` composed in the TASK layer `execute_tools/data_paths.py:168-172` and pinned exact (`test_step00_dataset_baselines.py:103-121` `"psd10000000_seg200_files20"`) | | **KEEP byte-stable** — the PR-G 0.R.12 pin pattern (`test_g3_measurement_identity_batch.py`, `test_measurement_identity_and_envelope.py`, `test_calibration_read_authority.py`, `test_measurement_capability_reachability.py`) |
| other `40000` literals (`campaign.py` C12 configs, `inference_single.py:453`, estimators' `safety_margin`, `SEG_SIZE_BOUNDS`) | outside §7e | **NOT 07c** (05b/§7e/step 7 sites already dispositioned; the rest are §9/§11 or comments) |

### 2.5 Repository conventions relevant to `examples/` (PR0's seam)

- No `examples/` exists; `pyproject.toml:35-41` packages allowlist excludes it (not importable — the §22.23.9 property); **ruff has NO include list** (`:69-81` excludes only) → any `.py` under `examples/` is linted + format-checked in CI; **pyright allowlist** (`pyrightconfig.json:2-13`) excludes it; **CI runs `pytest tests/unit/`** (`.github/workflows/ci.yml:61`) → tests placed under `tests/examples/` would NOT run in CI → **PR0's example tests live under `tests/unit/examples/`** (repository convention resolved from source, §22.23.7).
- Guard tests scanning the tree (`test_no_hardcoded_device_literals`, `test_c12b_legacy_fidelity`, `test_repo_hygiene` (git index), `test_step04b_task_description_single_source` — **`configs/` only: an examples manifest carrying `task_description` must NEVER live under `configs/`**) — none trips on a README/PROVENANCE/STATUS + manifest tree.
- `.gitignore` has no `*.h5`/`*.csv`/`*.json` rule (small manifests are tracked by default) and does ignore `*.pdf`; precedent for a tracked dir with an ignored cache subtree: `reference_data/root_papers_cache/*` + `!README.md`.
- No `PROVENANCE`/`STATUS` file convention exists; nearest precedent `reference_data/official_paper_result/README.md`; `docs/README.md` master index requires a row per new doc (unenforced).
- Data root authority: `execute_tools/data_paths.py:20-60` (`tidmad_data_config.yaml` → `.example.yaml` fallback; keys `tidmad_data_dir`, `siderius_data_dir`; NO env var); per-run `resolve_dataset_dir` `:70-137`; chain validation `sdsc_submission_scripts/run_one_iteration.py:1679-1680`.
- TIDMAD authorities a projection can read + their existing serializers: `TIDMAD_PROFILE` `execute_tools/dataset_config.py:571-587` (writer `core/sandbox_executor.py:1244-1266`); `ModelIOContract` authored in `configs/task_config.yaml:20-45`, bound by `workflows/task_config.py:196-225` (writer `sandbox_executor.py:1214-1242`); `derive_tidmad_deliverable_spec` `execute_tools/deliverable_spec.py:332-363` (no writer by design — derive on both sides); `derive_tidmad_metric_spec` `execute_tools/evaluation_metric.py:549-583`; `configs/health_checks.yaml` (`health_gates:`).

### 2.6 Already closed / owned elsewhere — do NOT redo

| Item | Owner / evidence |
|---|---|
| metric identity, direction, scoreability, both scoring routes, `metric_result` payload, planner filter for it | Step 06 (PR #213) — CONSUMED here |
| resolved profile through training/inference/scoring; SampleSet build from the profile | Steps 02/05a — CONSUMED |
| model-I/O contract transport (`--model_io_json`), probe realization authority | Steps 03/04a/05b — CONSUMED (07c's dtype fix) |
| training/inference argv + deliverable spec | Step 05c — its argv-parity criterion is the surface 07a's new flag must declare against |
| interpreter/proposer rendering, per-round condensation onto `ModelRunSummary`, cross-iteration transport | Step 09 |
| workflow/resume/`campaign_artifacts` comparisons | Step 10 |
| static builtin model-description prose | DEFERRED (Step-04 §20.4) — untouched |

### 2.7 Roadmap anchors found stale (for Checkpoint E, §15)

§20.2 tuner anchors (`:5776`, `:5620-5635`, `:5705-5710`, `:4568-4576`), §7a (`:5486`, `:5424`, "~40 sites" → 45), §16 D1 (`:6018-6064`, `:1435-1449`, `model_exploration.py:2740`), `agent/prompts.py:232-238` (→ `:243-249`) and `:1037` (→ `:1064`), `nodes/result_interpretation_agent.py` (→ `nodes/result_interpretation_agent/result_interpretation_agent.py`), and the D1 census missing four tuner-internal sites (§2.2). None changes an ownership decision.

---

## 3. Authority map

| Concept | Authority | Step-07 role |
|---|---|---|
| golden metric identity / direction / aggregation / scoreability | `EvaluationMetric` handle (**Step 06**) | **DERIVE** — every policy comparison, threshold sentinel, rank, efficiency band, "better/worse" wording (07b) |
| what a lower/higher direction MEANS for skip/bypass/bootstrap sentinels | Step 07b (policy semantics on top of the handle) | **DECLARE** — one direction-aware comparison primitive; never a second direction field |
| training objective (R1) | loss config / Step 03 loss authority | KEEP (07a computes it on validation data; no new loss abstraction) |
| validation scope | the tuner's existing run-bound `eval_sample_set` (Step 05a) over the profile's validation file family (Step 02) | **DERIVE / TRANSPORT** (07a) — no new split concept |
| `TrainingHistory` (R2/R3 + optional checkpointed observations) | **Step 07a — trainer produces** | **DECLARE** the typed additive payload; carried by the existing results JSON → record transport |
| `TrainingDiagnosis` | **Step 07a — tuner's deterministic layer** | **DECLARE**; computed once; never re-derived by an LLM |
| what the planner/reflector SEE of history/diagnosis/direction | **Step 07b** (renderers) | **DECLARE** — explicit renderers + tests; 07a keeps everything hidden |
| planner/reflector §13 task content (roster, collapse advice, anchors, CH1/CH2, `[B, 256, T]`) | task profile / dataset profile / model-I/O contract / health config (Steps 01–04, 08) | **DERIVE** (07b) — rendered blocks, byte-equal under TIDMAD |
| measurement probe data feeding (channels, encoding, filename family, dtype) | resolved `DatasetProfile` + `ModelIOContract` (Steps 02/03) | **DERIVE** (07c) |
| measurement identity / hashes / store keys; `seg=40000/batch=1` recipe | runtime-control framework (RT/PR-G) | **KEEP** byte-stable (07c) |
| example-pack instance data (identity manifests, provenance, checksums) | the pack (§22.23.1 — task-INSTANCE data) | **DECLARE** (PR0) |
| example-pack semantic content (profile, contract, metric, task text) | the module-owned authorities above | **PROJECT, never copy** (PR0: generated/verified-equal projections; prose cites the owning path) |

---

## 4. Approved scope (per child, brief — details in §8)

- **PR0** — three example roots with README / PROVENANCE / STATUS; identity-level manifests (Pets image-id·class·scope from the official annotation lists; DAVIS sequence·scope, clip identity only if the listing is obtainable without committing frames); TIDMAD read-only projection of the existing authorities, verified equal to production; Pets/DAVIS L0/L1 declarations through the real schemas where representable, honest STATUS for the rest; `tests/unit/examples/` acceptance tests. **No production code.**
- **07a** — R3 validation pass in the trainer over the run-bound eval sample set; typed `TrainingHistory` (R2 + R3 + optional checkpointed observations) on the results JSON → record; deterministic `TrainingDiagnosis` in the tuner through an extracted boundary; both persisted, both hidden from planner/reflector renders; Seam 5 in the genericity contract; StubSandbox/pseudo history upgraded; example packs project the history semantics.
- **07b** — direction-aware policy primitive consumed by incumbent/best/threshold/skip/bypass/efficiency/rank/score-table/penalty sites; planner/reflector task content rendered from profile/contract/handle with byte parity; explicitly owned direction + diagnosis rendering deltas; `AttemptTransition`/`AttemptDecision` wired or removed; Gate 1.
- **07c** — profile-derived probe batch builder (one loader), profile-derived dtype in the worker, capability-routed dataset checks in bootstrap/probe_production; identity keys/hashes/store keys byte-stable; Gate 2 bounded.

## 5. Explicit non-goals

See §1.1. Additionally: no new memory store; no `StaticMetric`/`DynamicMetric` ontology (§22.3); no cadence beyond `per_epoch` (v1); no multi-objective policy (§22.7); no `examples/common/`; no launcher/CLI for examples; no `.py` production code in `examples/` (PR0); no fetch of images/frames (only bounded metadata); no widening of `run()` — every new responsibility enters through an extracted, typed, independently testable boundary (CLAUDE.md responsibility-oriented decomposition — the tuner's `run()` is the incident that made it a rule).

## 6. Inherited semantics (consume, do not re-derive)

- Step 06: `MetricSpec.direction ∈ {"higher","lower"}`; the handle is bound once at run scope (`:3869`); the record payload is filtered from the planner (`_PLANNER_HIDDEN_RECORD_KEYS`) — the mechanism 07a extends and 07b renders through.
- Step 05a/05c: two run-bound SampleSets; training argv is pinned by exact ordered equality after documented normalization (05c §4.2) — 07a's added flag is a DECLARED delta.
- Step 02: the resolved profile crosses every subprocess boundary; a 3-file contrast profile fixture exists (rungs 4.8-A/B) — 07a's L2 rung and 07c's rung reuse it.
- Step 00 §17 golden policy: tests never regenerate; regeneration in the same commit as the intentional change with a three-part message.
- Roadmap §17.0/§17.0.1: Gate tiers from the standard's table only; default temporal depth 1×1, ≥2 rounds for multi-round tuner policy; Gate-2 PASS is functional.
- Roadmap §22.11a: no ad-hoc composed tasks — anything labelled Track B/C uses the EXACT Pets/DAVIS semantics; cumulative corpus.

---

## 7. PR decomposition — **FOUR PRs** (`PR0` → `07a` → `07b` → `07c`)

Q2 resolved the lettering; this section verifies the split against the
child-PR criteria FROM SOURCE (kickoff protocol step 5), so it stands on
evidence rather than on the resolution.

| Criterion | PR0 | 07a | 07b | 07c |
|---|---|---|---|---|
| 1. independently useful final effect | user-facing baseline of the three tracks | training dynamics persisted as typed evidence (R2/R3 + diagnosis) | metric-generic policy + profile-rendered prompts | profile-derived measurement feeding |
| 2. real first consumer | production authorities are READ by verified-equal projections + `tests/unit/examples/`; no new seam | trainer→executor→tuner record path in a REAL run (history+diagnosis persisted in `run_output`) — the Step-06 `metric_result` precedent | production rounds select incumbents through the handle; planner/reflector rendered from owned renderers | production pre-phase measurement builds batches from the profile |
| 3. coherent repository after merge alone | yes (docs + manifests + tests) | yes — history persisted, unrendered = the current `metric_result` state | yes | yes |
| 4. own parity surface | tree outside `examples/` unchanged; goldens untouched | trainer 3 legacy keys + train-loss trajectory bit-identical; PB-1/PB-2/WF-1/WF-2 exact; REC-3 additive-only | PB-1/PB-2 exact except attributed deltas; selection replay deep-equal; threshold resolution identical | identity hashes / keys / probe bytes identical |
| 5. own atomic contrast | L0/L1 declarations (Pets/DAVIS through the real schemas) — declaration evidence, not a rung | diagnosis-structure axis (Pets CE/acc, DAVIS MAE/PSNR, TIDMAD focal) + validation-scope axis (real trainer, contrast profile) | metric-direction axis through the WHOLE policy (strict, C6a-style) + rendering phrasing (Pets accuracy↑ / DAVIS MSE↓) | measurement data-feeding axis (contrast profile, keys stable) |
| 6. own live Checkpoint C | deterministic (projection == production authority) | real training subprocess emits R3 (Checkpoint-C instantiation) + Gate 2 | Gate 1 (≥2 rounds) + deterministic replay | Gate 2 bounded (real measurement) |
| 7. independent review / rollback | yes | yes | yes | yes |
| 8. no consumer-less seam | none created | the diagnosis is produced+persisted in production; rendering deliberately 07b (frozen Q2) | consumes 07a + 06 | consumes 02/03 |
| shared code with a sibling | none | trainer/executor/schema/tuner-record boundary | tuner policy/prompts (+ reads 07a's record fields) | `core/runtime_control/` + `execute_tools/probe_data.py` (+ two capability sites) |

**Order and dependencies.** PR0 first (baseline before semantics; no code
dependency). 07a before 07b: 07b's *rendering* half needs 07a's diagnosis;
07b's *direction* half needs only 06 — the child docs may not reorder (Q2
frozen) but 07b must not be blocked by 07a's diagnosis shape beyond the
record fields 07a freezes. 07c is independent of 07a/07b and may be designed
in parallel (never implemented in parallel with an unmerged prerequisite —
kickoff rule 9). **Why not fewer**: 07a and 07b share the tuner but have
different failure classes (execution/RNG parity vs LLM-visible bytes),
different Gates (2 vs 1) and different rollback surfaces; PR0 shares nothing
with any of them; 07c lives in another subsystem. **Why not more**: splitting
07b into "policy" and "prompts" would ship a policy that selects by direction
while the reflector still says "HIGHER … is GOOD" — a half-enabled state
under any non-TIDMAD metric; 07b runs three INTERNAL phases instead (§8.3),
the 05b precedent. Splitting 07a into "trainer emits" / "tuner derives" would
land a consumer-less trainer payload.

---

## 8. Per-PR acceptance contracts

Each child doc instantiates the eight-section per-commit checklists; this
section fixes WHAT must be true, per Checkpoint, and the evidence class.

### 8.0 Common to all four

- Checkpoint 0 captured BEFORE the first production edit (missing baselines
  listed per PR below).
- Checkpoint D: targeted tests per commit; mutation proofs per semantic
  family (delete-the-hop, precedence/direction reversal); exact-head CI green
  once, from a clean tree; the full local suite ONCE at the final executable
  head; never `pytest | tail`.
- Checkpoint E: §15.1 row + `README.md` index + this parent's status, in the
  same PR or an immediately-merged docs follow-up (no trailing docs-only
  pushes for CI ids — record them in the PR body / ledger of the same push).
- Example-pack obligation (§22.23.8): each PR either advances the packs or
  states in its design why the capability is not projectable.
- Every new production responsibility enters through an extracted, typed
  boundary with reachability evidence; `run()` gains sequencing calls only.

### 8.1 PR0 — Persistent Example Baseline (preflight)

**Scope.** `examples/tidmad/`, `examples/oxford_iiit_pet/`,
`examples/davis_future_prediction/` (names subject to PR0's one-time
convention audit, §22.23.2), each with README (task, objective, which
contracts it demonstrates, owning paths), PROVENANCE (source, licence text
as frozen in §22.9a incl. the DAVIS per-artifact wording, checksums of the
metadata artifacts used, acquisition instructions — no downloads performed
into git), STATUS (maturity level, unsupported seams — a MIRROR of
§15.1/§22.12), `data/` with the identity manifests + their SHA-256 pins
and the acquisition/prepare instructions (no prepared data), and for TIDMAD
a read-only projection of `DatasetProfile`, `ModelIOContract`,
`DeliverableSpec`, `MetricSpec`, task description / forward contract, health
config — each either a GENERATED artifact verified equal to the production
authority by test, or a reference to the owning path. Pets/DAVIS: L0/L1
declarations through the REAL schemas where representable (expected:
`MetricSpec` accuracy↑ / MSE↓ scalar-only instances; `ModelIOContract`
`[3,144,144]→37 logits` and `[3,8,128,224]→[3,4,128,224]` if the schema is
rank-agnostic — recorded honestly either way); `DatasetProfile` /
`DeliverableSpec` recorded as D14 seams in STATUS if TIDMAD-shaped. Pets
`log_loss` recorded as blocked by D16 (declared as documentation, NOT
through the metric-declaration path — OD-S7-7). Tests under
`tests/unit/examples/`.

**Checkpoint 0 / A (parity).** No production behaviour changes: no file
outside `examples/`, `tests/unit/examples/`, docs and (if needed) a
`tools/`-side manifest generator changes; every existing golden untouched;
the projection tests prove `examples/tidmad/...` deep-equals
`resolve_dataset_profile().model_dump()`, `run_bound_model_io_contract()`,
`derive_tidmad_deliverable_spec(...)`, `derive_tidmad_metric_spec(...)`,
`load_task_config()` — the machine-checkable "no second authority" of
§22.23.7 L0/L1.

**Checkpoint B.** Not a rung — declaration evidence: Pets/DAVIS L0/L1
declarations validate through the real schemas; manifests validate
(disjoint scopes, expected counts vs the official lists, breed-stratified
80/20 for Pets, sequence-disjoint for DAVIS, SHA-256 pinned); STATUS names
the unsupported seams.

**Checkpoint C.** Deterministic production-path integration — the real
loaders/derivers ARE the consumers; no chain.

**Checkpoint D.** `tests/unit/examples/`: references resolve; identity valid;
projection equality; manifest validity; task-specific values match §22.9a
(the frozen values are pinned as literals in the tests, never read back from
the pack); separability (nothing under `core/agent/nodes/execute_tools/
workflows` imports `examples`); a guard that no `configs/`-guarded key
(`task_description`) appears under `examples/` in a location the
single-source guard scans (it does not — assert the layout stays outside
`configs/`).

**Gates.** Gate 1 NOT REQUIRED · Gate 2 NOT REQUIRED (table row "Config
files, YAML, schema-only | Unit only" is the nearest; PR0 is docs +
manifests + tests). Flip: any production code path or LLM-visible byte.

**Baselines MISSING → capture in PR0.** none of the goldens; the projection
equality tests ARE the new baseline.

**Example obligation.** PR0 IS the example obligation.

**Stop conditions.** A manifest requires data that cannot be obtained
without downloading images/frames (→ D14, never fabricated); a schema must
be bent to represent Pets/DAVIS (→ STATUS records "not representable", D14
seam); any pressure to add a loader/reader.

**Bounded metadata fetches allowed.** Pets `annotations.tar.gz` (~19 MB);
DAVIS: the ImageSets lists and, if obtainable by an HTTP range read of the
archive's central directory or an equivalent bounded listing, per-sequence
frame counts for clip identity — otherwise clip identity → D14. Provenance
of every fetch recorded (URL, date, SHA-256).

**Decisions to freeze in the child doc.** manifest file format (CSV/JSON),
generator location (`tools/` vs test-side; core never depends on it),
`.gitignore` additions (e.g. an ignored `examples/**/cache/` if any local
prepare step is documented), README index rows.

### 8.2 PR 07a — TrainingHistory / TrainingDiagnosis (R2/R3)

**Scope.**
1. Trainer: after each epoch, evaluate the SAME criterion on the run-bound
   validation sample set under `no_grad`/`eval()`, restore `train()`,
   append to a typed `TrainingHistory` (R2 mean train objective, R3 mean
   validation objective, epoch index; optional checkpointed observations
   slot); legacy single-file mode records R2 only (validation scope absent
   — honest, not "fully supported").
2. Transport: the validation sample set reaches the trainer (OD-S7-1); the
   trainer results JSON gains a typed additive payload while `final_loss`,
   `loss_history`, `model_params` stay byte-identical; a Pydantic model
   validates the trainer results at the executor read-back (fail-closed on a
   malformed payload; the three legacy keys remain the compatibility floor).
3. Tuner: an extracted, typed, independently testable boundary derives
   `TrainingDiagnosis` (deterministic; candidate concepts §22.4: converged /
   plateau / overfit / underfit / unstable / best-validation-epoch /
   final-vs-best gap / train-val gap / trend; must cope with histories
   shorter than `epochs` — stability early-exit `:1186-1187`, `:703-704` —
   and with R3 absent) and attaches history + diagnosis to `ExperimentRecord`
   (additive fields; existing fields unchanged; a validator pins internal
   consistency, e.g. `final_loss == history.train[-1]` when both present).
4. Prompt visibility: the new record keys are added to the planner hidden
   set AND kept out of `reflect_results` / the reflector's json dump — PB-1,
   PB-2, WF-1, WF-2 byte-identical (this is the Step-06 filter precedent
   applied at BOTH renders; the mechanism — allowlist at the tuner vs hidden
   set at the renderer — is the child's choice; the invariant is not).
5. Test infra: `StubSandbox` and `tests/pseudo_data` train outputs emit a
   plausible multi-epoch train + validation history (OD-S7-4);
   `RecordingSandbox` mirror.
6. `docs/design/genericity_contract.md` Seam 5 (Training observation)
   written BEFORE implementation.
7. Example packs: each README/STATUS states the pack's R1/R2/R3 + optional
   checkpointed observations per §22.9a (TIDMAD: focal/CE train + validation
   objective; Pets: CE + validation accuracy; DAVIS: MAE + validation PSNR)
   and what the framework produces today (TIDMAD real; Pets/DAVIS declared,
   fixture-backed); an `expected/` diagnosis fixture is legitimate only if
   the same fixture is what the tests consume (§22.23.7).

**Checkpoint 0 (capture BEFORE editing).** (a) a deterministic-seed training
run's `loss_history` on the Step-02 3-file contrast fixture and on the
existing pseudo route — the oracle that the validation pass does not perturb
the training trajectory (RNG isolation: no draw from the training generator,
dataset seeding untouched); (b) the exact training argv list from 05c's
oracle; (c) REC-3 schema field lists / manifest key sets (will be
regenerated additively with provenance); (d) WF-1/WF-2 kwarg key sets and
PB-1/PB-2 (must NOT change).

**Checkpoint A (parity).** train-loss trajectory bit-identical with and
without the validation pass on fixed seeds; the three legacy JSON keys
byte-identical; `ExperimentRecord` existing fields unchanged; PB-1/PB-2/
WF-1/WF-2 exact; training argv equal to the 05c oracle PLUS exactly the
declared new flag (documented delta, OD-S7-1); runtime-control admission /
verification / timeout / signal semantics unchanged (05b/RT tests green;
verification step counting excludes validation batches); dashboard readers
of `final_loss` unaffected.

**Checkpoint B (rungs, declared REQUIRED).**
- **B-07a-1 diagnosis-structure axis (L1, atomic):** the SAME diagnosis
  boundary over three histories carrying the EXACT frozen semantics —
  TIDMAD (focal train + validation), Pets (CE train/validation + validation
  accuracy diagnostic), DAVIS (MAE train/validation + validation PSNR) —
  producing the expected verdict shapes; only the history/objective identity
  varies. No image/video files, no loader.
- **B-07a-2 validation-scope axis (L2, real component):** the REAL trainer
  subprocess on the Step-02 3-file contrast profile emits R2 + R3 over a
  distinct validation sample set through the production argv — honestly
  labelled a contrast-profile rung, NOT Track B/C.
- (Robustness, not a semantic rung) shortened histories, R3 absent, NaN
  epochs.

**Checkpoint C.** A Checkpoint-C instantiation with REAL training (pseudo
LLM allowed) shows the record in `run_output_*.json` carrying history +
diagnosis produced by the production trainer → executor → tuner path.

**Checkpoint D.** targeted families: trainer validation pass (RNG isolation
mutation: consume one training RNG draw inside the validation pass → trajectory
oracle RED), transport (drop the flag → R3 absent → "not fully supported"
recorded, never silent), typed results model (malformed → fail-closed),
diagnosis (delete-the-hop: skip derivation → record lacks it → RED; each
verdict rule mutated → RED), hidden-key filter at BOTH renders (Step-06
planner-boundary test extended to the reflector boundary), StubSandbox
history shape, Seam-5 doc test if the contract doc has one.

**Gates.** Gate 1 **NOT REQUIRED** — table row "Prompt placeholder
substitution / Unit only + optional Gate 1" does not even apply because NO
rendered byte changes (PB/WF exact is a hard criterion). **Flip:** any
planner/reflector byte or kwarg-key change → Gate 1 REQUIRED. Gate 2
**REQUIRED, bounded** — table row "Checkpoint (end of feature) | Gate 2";
07a changes REAL training execution (a validation pass in the production
subprocess) and §17 names bounded real Gates for modules that change real
execution behaviour; PASS = functional (real training emits R2 + R3, tuner
persists the diagnosis, run completes) — bounded canonical command,
`openai_tiered_pro.json`, cold-start. Corpus breadth (§22.13): TIDMAD only
executable; B/C contribute their L1/L2 evidence with the reason recorded.

**Roadmap correction implied (OD-S7-2).** §15.1's pre-Q2 sentence "Because
the reflector prompt will change, Gate 1 becomes REQUIRED for 07a" belongs
to 07b under the resolved lettering.

**Baselines MISSING → capture.** trajectory oracle (a), argv oracle from
05c (reuse), reflector-boundary hidden-key test (new; PB-2 already pins
bytes but not the mechanism).

**Stop conditions.** the validation pass cannot be made RNG-neutral; the
existing sample-set machinery cannot express the validation set without a
new SPLIT concept (a new flag carrying the EXISTING eval set is OD-S7-1, not
a stop); reflector bytes cannot be held exact; any change to retry / round /
timeout / signal semantics; > ~1 h wall or material cost per attempt.

### 8.3 PR 07b — Tuner policy on the golden metric + planner/reflector rendering (Gate 1)

**Scope — three INTERNAL phases (one PR).**
- **P1 direction-aware policy.** One typed comparison primitive built on
  `run_metric.spec.direction` (better-than, best-of, rank, "within band",
  disabled-sentinel resolution) consumed by: `_best_trial_winner`,
  `_should_skip_formal`, `_should_bypass_formal_time_budget`,
  `_resolve_formal_comparison_thresholds` (bootstrap sentinel and delta
  sign), the skip/bypass call sites and banners, the planner score-table
  incumbent `:4406-4419`, the reflection block (best/rank/5 % band/
  `is_more_efficient`/`is_new_best`), the 4/5-track finalization, and the
  collapse penalty's sign convention. Under `higher` every decision is
  identical (replay oracle). The same-loss `final_loss` rank stays
  lower-is-better and untouched. `AttemptTransition`/`AttemptDecision`:
  WIRE (through the extracted attempt-transition boundary that also resets
  `resolved_action` per attempt) or REMOVE — decided in the child doc from
  source, never a third state (OD-S7-6); if wired, retry/round semantics
  provably unchanged.
- **P2 profile-rendered task content.** roster, baseline rule, collapse
  advice (gate names from the effective health config; loss-type advice from
  the loss authority), efficiency band text, 4000/200 anchors (from the
  profile / run-bound sample-set accounting), loss-type list, CH1/CH2 +
  log-space explanation (from the metric handle's references), `[B, 256, T]`
  / regressor / hybrid blocks (from the model-I/O contract) — rendered
  blocks, EXACT bytes under TIDMAD.
- **P3 owned rendering deltas.** direction wording ("maximize", "GOOD if
  HIGHER", rank "(1 = best)", "beats the best") rendered from the handle;
  the "score = validation" compensating instruction replaced by rendered
  `TrainingDiagnosis` lines (compact, structured — never the raw curve);
  metric identity name rendered from the handle. These — and ONLY these —
  are the authorized PB-1/PB-2 byte deltas; declared file-by-file before the
  change; regenerated in the same commit with the three-part message.

**Checkpoint 0.** (a) selection replay oracle: run the current selection/
threshold/reflection-context logic over the recorded `all_records` of
existing `run_output_*.json` artifacts (a checked-in small corpus, incl.
`-inf`/None/penalty cases) and pin `best_*` outputs, thresholds and
reflection-context values; (b) PB-1/PB-2/WF-1/WF-2 (declared deltas listed
per file); (c) the OD-1 condensed-branch byte-instability (`test_pb1_full_
window_boundary_is_the_deferral_line`) — 07b closes it or records why not.

**Checkpoint A.** replay deep-equal under `higher`; threshold resolution
identical (`negative_infinity_bootstrap`, `ref + delta`); PB-1/PB-2 exact
except the declared P3 deltas; WF-1/WF-2 kwarg key sets exact (or additive
and declared); record fields unchanged; no `run()` growth.

**Checkpoint B (declared REQUIRED).**
- **B-07b-1 metric-direction axis (L1, STRICT one-axis, the C6a lesson):**
  identical records/history, only `direction` flips → trial winner, skip and
  bypass verdicts, bootstrap sentinel, best/rank/band, all five `best_*`
  tracks and the score-table choice invert exactly; the loss rank does not.
- **B-07b-2 rendering axis (L1):** planner/reflector rendered for a
  `lower` scalar metric and for the two frozen contrast declarations (Pets
  accuracy↑ classification phrasing; DAVIS MSE↓ regression phrasing) contain
  no higher-is-better residue and carry the diagnosis lines from a Pets/DAVIS
  fixture history — scoped assertions (Step-01 §13.4 residue rule).
- **B-07b-3 task-content axis (L1):** a contrast profile / contract renders
  different roster/anchor/contract blocks with the template layer carrying
  no TIDMAD literal (template-scoped ABSENCE pins, not rendered-output pins).

**Checkpoint C.** Gate 1 with ≥ 2 rounds (multi-round policy: skip/bypass/
incumbent exercised) — real LLM, pseudo training with the 07a multi-epoch
stub history so diagnosis lines render from a real trajectory; plus the
deterministic replay.

**Checkpoint D.** direction mutations per family (flip one comparison →
strict rung RED); sentinel mutation (`-inf`↔`+inf` under `lower`); band
sign mutation; template-literal reintroduction → absence pin RED;
reachability (production path calls the primitive — bypass it → RED);
attempt-transition parity if wired.

**Gates.** Gate 1 **REQUIRED** — table rows "New LLM-facing system prompt |
Gate 1" (P3 changes system-prompt bytes) and OD-20-6; run at ≥ 2 rounds
(§17.0.1). Gate 2 **NOT REQUIRED** — parity of policy is deterministic
(replay) and no real-execution behaviour changes; the standard's governing
principle (gate harness "does NOT own tuner policy") confirms Gate 2 adds no
policy evidence. **Flip:** any change to training/inference/scoring
launches or execution semantics → Gate 2 REQUIRED. Corpus breadth: TIDMAD
executable; B/C L1 rendering evidence recorded.

**Baselines MISSING → capture.** replay oracle corpus + pins; per-file
declared golden deltas; template-scoped absence pins for P2.

**Stop conditions.** direction cannot be expressed without a second
direction field or a metric rename (D1 not authorized); a P2 block needs a
fact no authority declares (→ operator; never a new task-config field by
default); a PB delta appears that is not attributable to P3; retry/round
semantics would change; the primitive would have to live inside `run()`.

### 8.4 PR 07c — Measurement / verification data feeding

**Scope.** one profile-derived probe batch builder (channel identity,
encoding/offset, filename family from `DatasetProfile`; dtype from the
run-bound `ModelIOContract`) used by BOTH the in-process probe path
(`probe_production.py` → today `execute_tools/probe_data.load_probe_batch`)
and the worker's bounded loader (`gpu_measurement_data.load_bounded_probe_
batch`) — the D-C2-12 host-RSS property preserved (bounded read); the
`fcnet` dtype branch in the worker removed in favour of the contract; the
two `TIDMAD_DATA_DIR` fallbacks (`bootstrap.py:513-520` + remedy string,
`probe_production.py:210-219`) routed through the resolved measurement
capability the caller already passes; `test_no_model_name_branches.py` scan
targets extended to `core/runtime_control/`. The `seg=40000/batch=1`
recipe stays framework-owned (may be centralized; values unchanged).

**Checkpoint 0.** probe batch bytes on the small HDF5 fixture (extend
`test_gpu_measurement_data.py`'s byte-identity oracle to the new builder);
identity/hash/key pins already exist (PR-G family) — verify green before
editing.

**Checkpoint A.** probe/measurement batches byte-identical under TIDMAD;
`MeasurementIdentity.components()`, `candidate_config_hash`, planned hash,
inference workload hash, `calibration_key`, `data_shape_class` exact string
unchanged; measurement store readable unchanged; RT admission/verification
behaviour unchanged.

**Checkpoint B (declared REQUIRED).** **B-07c-1 measurement data-feeding
axis (L1/L2):** batches built from the Step-02 3-file contrast profile
(4.8-B geometry) with a non-int8/other-channel declaration → different bytes;
identity keys and comparability byte-stable (the fixture asserts both in one
test so the axis is provably single).

**Checkpoint C.** production pre-phase measurement builds its batch from
the profile in a real run — Gate 2 bounded (the measurement IS real
execution).

**Checkpoint D.** delete-the-hop (builder ignores the profile → contrast
rung RED); dtype-branch reintroduction → guard RED; fallback reintroduction
(`TIDMAD_DATA_DIR` import inside `core/runtime_control/`) → guard RED;
reachability (worker + probe path both call the one builder).

**Gates.** Gate 1 **NOT REQUIRED** (no LLM-facing change; flip: none
expected). Gate 2 **REQUIRED, bounded** — table row "Checkpoint (end of
feature) | Gate 2" and §17's explicit naming of §7e among modules that
change real execution behaviour; PASS = functional (measured admission
reached from a profile-built batch). Corpus: TIDMAD; B/C L0/L1 recorded.

**Example obligation.** measurement is not user-facing; the child states
this (§22.23.8 "why not projectable") — STATUS unchanged.

**Stop conditions.** any identity hash or store key would change; the
bounded-RSS property cannot be kept; a batch fact is not derivable from
profile + contract.

---

## 9. TIDMAD compatibility surfaces (Step level)

| Surface | Criterion | Owner |
|---|---|---|
| training loss trajectory (fixed seed) | bit-identical with/without validation pass | 07a |
| trainer results JSON legacy keys | byte-identical values; payload additive | 07a |
| training argv | 05c exact-list oracle + ONE declared new flag | 07a |
| `ExperimentRecord` existing fields; `HyperparamTuningOutput` | unchanged; additive only | 07a / 07b |
| PB-1 / PB-2 planner & reflector goldens | EXACT (07a); EXACT except declared P3 deltas (07b) | 07a / 07b |
| WF-1 / WF-2 kwarg key sets | EXACT (07a); EXACT or declared-additive (07b) | 07a / 07b |
| REC-2 / REC-3 record projections | additive regeneration with provenance | 07a |
| incumbent / thresholds / reflection context / `best_*` | replay deep-equal | 07b |
| runtime-control admission / verification / timeout / signal | unchanged | 07a / 07c |
| probe batches; identity hashes; store keys; `data_shape_class` | byte-identical | 07c |
| everything outside `examples/` + tests | untouched | PR0 |

## 10. Stage-A baseline inventory

| Surface | Classification |
|---|---|
| PB-1 (3), PB-2 (2), WF-1, WF-2, REC-2, REC-3 | **EXISTING SUFFICIENT ORACLE** |
| 05c training argv exact-list oracle | **EXISTING SUFFICIENT ORACLE** (declared delta in 07a) |
| PR-G measurement identity/key pins; `test_gpu_measurement_data.py` byte identity | **EXISTING SUFFICIENT ORACLE** |
| `test_delta_gates.py` / `test_formal_launch_decision.py` / `test_tuning_agent.py` selection pins | **EXISTING — UPGRADE** to direction-parameterized form in 07b (the anti-phantom pin gains a direction axis) |
| Step-02 3-file contrast profile fixture | **EXISTING** (reused by 07a-B2, 07c-B1) |
| training-trajectory oracle (validation pass RNG-neutral) | **MISSING — CAPTURE BEFORE PRODUCTION EDIT** (07a) |
| selection replay corpus + pins | **MISSING — CAPTURE** (07b) |
| reflector-boundary hidden-key test | **MISSING — CAPTURE** (07a) |
| projection-equality tests for `examples/tidmad/` | **MISSING — CAPTURE** (PR0; they are PR0's baseline) |
| `_PROBE`-style value pins on `max`/`-inf` semantics | **OBSOLETE IMPLEMENTATION PIN — REWRITE** direction-parameterized (07b) |

## 11. Gate disposition — quoted from `docs/gates/gate_testing_standard.md` (read at `03225ac9`)

| Commit type | Typical gate |
|---|---|
| Config files, YAML, schema-only | Unit only |
| New loader/renderer (pure Python) | Unit only |
| Prompt placeholder substitution | Unit only + optional Gate 1 |
| New LLM-facing system prompt | Gate 1 |
| Checkpoint (end of feature) | Gate 2 |

| PR | Gate 1 | Gate 2 | Evidence row / flip |
|---|---|---|---|
| PR0 | NOT REQUIRED | NOT REQUIRED | docs/manifests/tests only; flip: any production code or LLM byte |
| 07a | NOT REQUIRED (bytes exact) | **REQUIRED, bounded** | "Checkpoint (end of feature)"; real training behaviour changes; flip G1: any rendered byte / kwarg key |
| 07b | **REQUIRED, ≥ 2 rounds** | NOT REQUIRED | "New LLM-facing system prompt" + OD-20-6; flip G2: any execution-launch change |
| 07c | NOT REQUIRED | **REQUIRED, bounded** | "Checkpoint (end of feature)" + roadmap §17 (§7e changes real execution) |

All Gates: `llm_configs/openai_tiered_pro.json`, cold-start, the standard's
bounded canonical command (re-audited from source immediately before
launch), operator approval per launch, corpus breadth per §22.13 (B/C
non-executable → highest honest evidence recorded). **No Gate runs during
design.**

## 12. Cross-cutting invariants

### 12.1 Persistence ≠ prompt visibility (§22.6)
07a persists and hides; 07b renders through owned renderers with tests at
the real bridge boundary (`BoundaryRecorderBridge`); Step 09 renders for the
interpreter. No record key reaches an LLM by serialization.

### 12.2 One direction authority
`MetricSpec.direction` is the ONLY direction fact. 07b's primitive
interprets it; no `higher_is_better` flag, no per-site literal, no rename.

### 12.3 Responsibility-oriented decomposition (binding)
`run()` (7,180-line module) receives NO new branching. 07a's diagnosis, its
record attachment and its render filter; 07b's comparison primitive,
renderers and (if wired) attempt-transition; 07c's batch builder — each is a
typed unit with reachability tests. Parity before/after per extraction.

### 12.4 Genericity contract first
07a writes Seam 5 before code; 07b/07c update Seams 1/4 "not yet generic"
lines as they close.

### 12.5 No ad-hoc composed tasks
Anything labelled Track B/C uses the §22.9a semantics; the Step-02 3-file
profile is a contrast fixture and is labelled so.

## 13. Evidence economy

- Deterministic properties (diagnosis rules, direction inversion, byte
  parity, projection equality) are tested deterministically; Gates prove the
  real chain executes, nothing more.
- Existing goldens carry prompt parity — no duplicates; the only new golden
  families are the ones §10 lists as MISSING.
- Full local suite once per PR at the final executable head from a clean
  tree; exact-head CI is the broad regression authority; targeted runs
  during development.
- Gate cadence: 07a and 07c one bounded Gate 2 each; 07b one Gate 1 at
  ≥ 2 rounds; PR0 none.

## 14. Test-disposition policy

KEEP / UPGRADE / MERGE / REWRITE / DELETE by functional intent, per test
body, never because a test fails. Expected: direction/`max`/`-inf` value pins
→ REWRITE direction-parameterized (07b); anti-phantom → UPGRADE with a
direction axis; template ABSENCE pins stay template-scoped; Step-06 planner
boundary test → UPGRADE to cover the reflector boundary and the 07a keys;
`test_control_boundary.py` → REWRITE or DELETE with the wire/remove decision;
`test_gpu_measurement_data.py` → UPGRADE to the one builder.

## 15. Roadmap / doc corrections to apply (Checkpoint E of the first child, or at Q4 if the operator prefers)

1. §15.1 step-7 row: "Gate 1 becomes REQUIRED for 07a" → 07b (OD-S7-2);
   child-doc filenames → this parent + `step_07_tuner_policy_and_training_
   diagnostics/{pr0_persistent_example_baseline, pr_07a_training_history_
   diagnosis, pr_07b_tuner_policy, pr_07c_tuner_measurement}.md`
   (Step-04 layout) — or keep the roadmap's flat names; operator's call
   (OD-S7-8).
2. §20.2 / §7a / §16 stale anchors (§2.7) re-anchored; D1 census gains the
   four tuner-internal sites; "~40" → 45.
3. `agent/prompts.py:873-885` comment "Step 07a / 09" → "Step 07a
   (hiding) / 07b (rendering) / 09".
4. `genericity_contract.md` Seam 4 "(Step 07a / D1)" → "Step 07b".
5. Step-04 parent §2.6/§2.7 "Step 07a" for `[B, 256, T]` / planner prose →
   07b (a one-line historical note; do not rewrite the closed doc).
6. `generic_framework_upgrade/README.md` row 07 → parent + children.

## 16. Stop conditions (Step level)

Any of the per-PR stops in §8; a need to reopen Step 06 semantics; a need
for a second state store; a need to render diagnosis for the interpreter
(Step 09); any Pets/DAVIS data path (D14); D1 rename pressure; any change to
the frozen scorer / loss math / calibration values; Q4 not marked when a
child is about to be frozen.

## 17. Completion / Checkpoint E

Step 07 is COMPLETE when PR0, 07a, 07b, 07c are merged with Checkpoints
0/A/B/C/D each, the required Gates PASSED at the assembled heads (07a G2,
07b G1, 07c G2), exact-head CI green per PR, the §15.1 rows (7a + 7e), the
§22.12 07/07b/07c rows, `README.md` index and this parent synchronized, the
§14 convergence ledger records the direction primitive and Seam 5, and the
example packs' STATUS reflect L1 (Pets/DAVIS) / real (TIDMAD) for history,
policy and rendering. D14 opens only after this.

## 18. Operator decisions — OPEN

| ID | Decision | Recommendation |
|---|---|---|
| **OD-S7-1** | Validation transport into the trainer. Source proves the run-bound eval SampleSet exists but never reaches the trainer (`training_skill/wrapper.py`, `execute_training` signature, argv). Options: (a) a sibling flag `--eval_sample_set_json` (mirrors `--sample_set_json`; the trainer resolves the VALIDATION file family for it) + wrapper/executor kwargs; (b) fold both sets into one JSON payload behind the existing flag | **(a)** — smallest, symmetric with the existing transport, keeps OD-20-3's "no new SPLIT concept" (the set is the one the tuner already builds); declared as 05c's ONE argv delta |
| **OD-S7-2** | Gate re-assignment under Q2 lettering: 07a G1 NOT REQUIRED (bytes exact) + G2 REQUIRED bounded; 07b G1 REQUIRED ≥2 rounds + G2 NOT REQUIRED; 07c G2 REQUIRED bounded; PR0 none | approve; roadmap §15.1 sentence corrected (§15 item 1) |
| **OD-S7-3** | `final_loss` semantics stay "last-epoch train loss"; best-validation values are NEW fields | approve (dashboard/scripts readers) |
| **OD-S7-4** | 07a may change `StubSandbox` / pseudo train outputs to emit multi-epoch train + validation histories (test infra) | approve |
| **OD-S7-5** | Example tests location `tests/unit/examples/` (CI collects only `tests/unit/`); no `.py` production code under `examples/` at PR0; manifest generator (if any) under `tools/` | approve |
| **OD-S7-6** | `AttemptTransition`/`AttemptDecision`: WIRE via an extracted attempt-transition boundary (per-attempt `resolved_action` reset) or REMOVE — decided in 07b's child design from source | let the child decide; parity of retry/round semantics is the acceptance either way |
| **OD-S7-7** | D16 not touched by Step 07; PR0 documents Pets `log_loss` as a declared optional terminal metric BLOCKED by D16 (documentation, not through the metric-declaration path) | approve |
| **OD-S7-8** | Child-doc naming/layout (Step-04 subdir layout vs the roadmap's flat `step_07a_*.md`) | Step-04 layout |
| **OD-S7-9** | DAVIS clip identity at PR0 via a bounded archive-listing fetch (HTTP range read of the zip central directory) if available, else D14 | attempt in PR0, provenance recorded; never fabricated |

## 19. Adversarial self-review (this parent)

| # | Finding | Class | Disposition |
|---|---|---|---|
| 1 | The roadmap says "no new `--val_*` IPC unless source proves the boundary insufficient"; the audit proves the transport (not the split) is missing | design ambiguity | surfaced as OD-S7-1, not silently decided |
| 2 | `loss_history` is already LLM-visible; 07a's "hidden" rule must cover the reflector's raw json dump too, or Gate 1 flips silently | parity trap | hard criterion in §8.2 (PB-2/WF-2 exact) + new reflector-boundary test |
| 3 | The `-inf`/`+inf` disable sentinels invert together with the operators under `lower` — a two-axis change hiding inside "flip the comparison" | correctness risk | strict rung B-07b-1 asserts sentinels + operators + tracks together; sentinel mutation in D |
| 4 | Pre-Q2 "Gate 1 REQUIRED for 07a" contradicts the resolved split | roadmap consistency | OD-S7-2 + §15 |
| 5 | Pseudo training yields a 1-point history → 07b's Gate 1 would render degenerate diagnosis | evidence validity | OD-S7-4 (07a upgrades stub) |
| 6 | Tests under `tests/examples/` would not run in CI | evidence validity | OD-S7-5 |
| 7 | 07b is large (policy + task blocks + rendering); temptation to split | scope | three internal phases, one PR; split rejected because it lands a half-enabled direction state; child may re-raise with evidence |
| 8 | Roadmap anchors stale by ~300 lines in three sections | doc hygiene | §2.7 / §15 |
| 9 | 07a's Checkpoint C "consumer" is production persistence, not rendering | consumer-less risk | accepted by the frozen Q2 split and the Step-06 precedent; stated explicitly, not hidden |
| 10 | Validation pass could perturb training RNG or runtime-control step counting | parity/behaviour | trajectory oracle (07a Checkpoint 0) + RT semantics in Checkpoint A |
