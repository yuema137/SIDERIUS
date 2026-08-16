# Step 07 — PR 07a: TrainingHistory / TrainingDiagnosis (R2 / R3) — detailed design

| Field | Value |
|---|---|
| Parent | `../step_07_tuner_policy_and_training_diagnostics.md` (revision 2, FROZEN 2026-08-15) §8.2 — the 07a acceptance contract; §3 authority map; §18 OD-S7-1/-3/-4; §20 WHAT/HOW line |
| Roadmap | §20.2 (four concepts, OD-20-3/-4/-5), §22.1–§22.8 (R1–R4, cadence, History ≠ Diagnosis, information-flow governance), §22.9a (frozen track semantics), §22.12 row 07; §15.1 step-7 row (`§7a`) |
| Design base | `838e9cd6` (master; PR0 MERGED `79403b44`) — every source line below was re-read at this head; revision 2 adds the loss-module audit at `066d6b45` (`ml_models/loss_models_sandbox.py:135-216, 218-278, 321-345`, `models_format_sandbox.py:637-651`) |
| Depends on | PR0 MERGED (example packs exist); Steps 02/05a/05c/06 MERGED (profile transport, run-bound SampleSets, argv oracle, metric handle + planner filter) |
| Decomposition | ONE PR, four commits **C1 → C2 → C3 → C4** (§15) — trainer · transport + test infra · tuner boundary + record + hiding · rungs + packs + Checkpoint E |
| Gates | Gate 1 **NOT REQUIRED** (every rendered byte and kwarg key set exact — a hard criterion, §10) · Gate 2 **REQUIRED, bounded** (real training behaviour changes; launched ONLY with operator approval after C4, §10) |
| Status | **FROZEN — OPERATOR APPROVED 2026-08-15 — Revision 2. IMPLEMENTATION 2026-08-15 under the Implementation Working Rules contract: C1 `ece67fa0` · C2 `83987b21` · C3 `ecc5ddf8` · C4 (rung + packs + docs) landed on branch `step07-pr07a-training-history-diagnosis`; §14 is the live ledger (Gate 2 / PR / CI recorded there); merge pending operator review.** Revision 1 reviewed (APPROVE WITH TARGETED REVISION); revision 2 applied the two validation blockers, three genericity/robustness corrections and the diagnosis math (§0.5) plus one final non-architectural consistency pass at freeze (§1 R2/R3 invariant made precise; `objective_config_fingerprint`; Gate-2 completion semantics; `objective_kind` wording; training-state-neutral stop wording); §16 records the operator's dispositions of Q-07a-1..7. **Implementation COMPLETE (C1–C4 `ece67fa0` · `83987b21` · `ecc5ddf8` · `aee1e362`; ledger `889f7cfa`); Gate 2 PASS 2026-08-16 (§14.4, with the recorded 07c-debt watchdog finding); PR #215; exact-head CI 31919470205 SUCCESS; operator verdict 2026-08-16: APPROVE IMPLEMENTATION WITH DOC-ONLY CLOSEOUT BEFORE MERGE; **MERGED — PR #215, squash `65804b3d83d67eac5e8821f012bfb2f9f1fbffec` (`65804b3d`), 2026-08-16; final PR head `752f8f0e`, exact-head CI 31927638592 SUCCESS; parity `git diff 752f8f0e 65804b3d` empty. 07a COMPLETE.** |

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**What this child FREEZES (HOW) — operator approved 2026-08-15**: the trainer
validation pass and its STATE isolation (§3.2), the R2/R3 comparability
representation (§3.3), the transport IPC (`--eval_sample_set_json`, §3.4),
the `TrainingHistory` payload and the typed trainer→tuner results contract
(§3.5), the `TrainingDiagnosis` fields and rules (§3.6), the hiding mechanism
at both renders (§3.7), the record attachment (§3.8), the runtime-control
accounting rule (§3.9), the test-infra shape (§3.10), the example-pack
projection (§3.11), the rungs (§6), the Gate plan (§10) and the stop
conditions (§13); revision 2 adds the **expected-validation contract**
(§3.4a), the **validation-scope materialization contract** (§3.4b), the
**R2/R3 comparability precondition and its audit** (§3.3), **state
isolation** (§3.2) and the objective provenance fields (`objective_kind`, `objective_config_fingerprint`, §3.5). **What stays the parent's**: the semantic requirements
(§8.2 items 1–7) — this child instantiates them and does not reinterpret
them. **NOT frozen**: exact test-file decomposition, helper names, source
line numbers (reading aids at `838e9cd6`; re-read before each commit).

---

## 0. Pre-design source audit (at `838e9cd6`)

Every fact below was read at the cited line. The parent's census (§2.1 at
`03225ac9`) is CONFIRMED unchanged for every production line it cites — PR0
touched no production module.

### 0.1 The trainer (`execute_tools/train_engine_sandbox.py`)

| Fact | Evidence | Consequence |
|---|---|---|
| Streaming loop `run_experiment_streaming` `:782-1235`: per epoch a fresh `TIDMADEpochDataset` over the **training** file family (`dataset.training_file_name` inside the dataset `:368`), `DataLoader(shuffle=True, drop_last=True)` `:991-993` (or the sequential sampler `:984-989`), then the batch loop `:1095-1157`; per-epoch statistic `avg_loss = np.mean(batch_losses)` `:1178` appended to `history` `:1179`; summary = EXACTLY `final_loss` / `loss_history` / `model_params` `:1217-1221`; written raw with `json.dump(results, indent=4)` `:1487-1488` | | R2 today = **unweighted mean of per-batch criterion values over EQUAL-SIZE batches** (`drop_last=True`), i.e. the sample-weighted mean of the criterion for `reduction="mean"` criteria. R2's semantics are UNCHANGED by this PR (§3.3) |
| Legacy single-file `run_experiment` `:652-779` (`TIDMADDataset`, `:1466-1477`): same statistic `:758-759`; NO sample set, NO validation scope | | records R2 only; R3 honestly ABSENT (OD-20-4 legacy tolerance; not "fully supported") |
| **No `model.eval()`, no `torch.no_grad()`, no second loader, no validation family read anywhere** in the trainer (grep) | | R3 does not exist; this PR creates it |
| `criterion = get_criterion(loss_cfg, class_weights=None)` `:884` (streaming); plain callable `nn.Module` | | re-callable under `no_grad` — no new loss abstraction (§20.2 DECIDED) |
| RNG in the training path: `epoch_rng = random.Random(epoch_seed)` `:954` (subsampling, PRIVATE instance); `order_rng = random.Random(f"order:{epoch_seed}")` `:978`; the SHUFFLE loader `:991-993` draws its permutation from **torch's GLOBAL RNG** at each `__iter__` (RandomSampler without a generator) — the ONLY global-RNG consumer of the training trajectory | | a validation pass that consumed torch's global RNG (a stochastic forward, a `shuffle=True` loader) or updated BatchNorm running stats (a `train()`-mode forward) WOULD perturb epoch ≥ 1 → §3.2 isolates structurally (`model.eval()` + `torch.no_grad()` + `shuffle=False` + `torch.random.fork_rng`) and the two-arm oracle proves it |
| Runtime control: verifier fed ONLY inside the batch loop `:1125-1133`; resolved at loop end `:1159-1167`; training ACTUAL = `time.perf_counter() - t_train_start` `:1189-1193` (spans admission → last optimizer step **incl. epoch ≥ 1 dataset reconstruction**, docstring `:1190-1192`); realized peak memory `:1199-1214`; `runtime_session.finalize` `:1230` | | the ACTUAL feeds `observation_store.py:160-176` as **unit ms = actual ÷ optimizer steps** — a validation pass inside that window would inflate every training prior; verification counting is untouched if the pass sits OUTSIDE the batch loop (§3.9) |
| Stability stop (V20 C2, validation posture) `:1148-1157`, `:1186-1187` and mid-epoch admission rejection `:1172-1176` shorten or abort the history | | `TrainingHistory` copes with `epochs_completed < epochs_planned`; a rejected attempt writes NO results (`:1459-1465`) — nothing to attach |
| `TIDMADEpochDataset.__init__` `:303-438`: `train_portion=None` → **no `rng.sample` call** `:378-382`; the `rng` default `random.Random()` `:340-341` is a private, unseeded instance (never the module-global generator); reads `dataset.training_file_name(file_index)` `:368` — the family is NOT a parameter | | a validation dataset over the eval SampleSet is buildable with the SAME class once the file family is parameterized (`file_family="training"` default → parity); with `train_portion=None` it draws nothing |
| argparse `:1243-1343`: `--sample_set_json`, `--train_portion`, `--train_base_seed`, `--order_strategy`, `--file_order_json`, `--runtime_observation_out`, `--runtime_policy_json`, `--dataset_profile_json`, `--model_io_json` — **no validation flag** | | §3.4 adds ONE sibling flag |
| `DatasetConfig.validation_file_name` `execute_tools/dataset_config.py:127-142` — the raw VALIDATION family accessor (today read by inference/scoring only) | | the validation dataset addresses `abra_validation_{i:04d}.h5` through it — no literal |

### 0.2 The transport (tuner → wrapper → executor → argv → trainer → results → tuner)

| Fact | Evidence | Consequence |
|---|---|---|
| The tuner builds TWO run-bound SampleSets per attempt — `train_sample_set` and `eval_sample_set` (`ml_hyperparameter_tune_agent.py:4671-4687`, comment "training and validation"), both from `run_profile`, `data_scope`, `TrialConfig.eval_strategy/eval_portion/eval_sampling_seed`; `train_validation_align=True` (`agent/schemas/hyperparam_tuning.py:774-777`) makes them select the SAME segment indices — the separation is the FILE FAMILY (`abra_training_*` vs `abra_validation_*`) | | the validation scope EXISTS and is run-bound (OD-S7-1: no second split concept); under TIDMAD the R3 observation is on physically distinct recordings of the same segments |
| `eval_sample_set` is placed on `active_params` `:4751` and reaches ONLY segment counting `:4713-4714` and `sandbox.evaluate_metric(..., sample_set=eval_sample_set)`; **`agent/skills/training_skill/wrapper.py:5-23` enumerates kwargs and DROPS it**; `TidmadSandbox.execute_training` `core/sandbox_executor.py:1268-1282` has no such parameter; argv assembly `:1340-1424` emits none | | §3.4: wrapper forwards `eval_sample_set`, executor validates (`validate_sample_set(scope=self.data_scope)`, the SAME rule the train set obeys `:1382-1389`), writes `eval_sample_set_{exp_id}.json` in the SAME compact `json.dump` byte form (`:1373-1381`), appends `--eval_sample_set_json <path>` |
| Executor read-back `:1552-1571` forwards the WHOLE results JSON verbatim (`results = json.load(f)`), no schema | | additive keys flow through; the typed contract is applied at the TUNER boundary (§3.5) — one validation site, the executor stays a verbatim forwarder |
| Tuner: `train_results = train_status.get("results", {})` `:5619`; `final_loss` / `model_params` read `:5753`, `:5763`; **`reflect_results = {**train_results, **score_results}` `:5865` → `brain.reflect` `:5866` → `agent/prompts.py:1370` `json.dumps(actual_results)`**; record write copies the three keys `:5902-5904` | | the parity trap: `train_results` must keep EXACTLY its legacy keys at the reflect merge (§3.7); the record gains additive fields (§3.8) |
| WF-2 golden `tests/unit/agent/tune_ml_hyperparam_agent/goldens/wf2_reflect_call_surfaces.json` pins **`actual_results_keys` = 9 keys** (`denoising_score, failure_reason, file_vector, final_loss, gate_action, health_gate_results, is_degenerate, loss_history, model_params`) at the `brain.reflect` call | | hiding MUST happen tuner-side BEFORE the call (a prompts-only filter would keep bytes but change the pinned kwarg key set) |
| Planner: `_PLANNER_HIDDEN_RECORD_KEYS = {"metric_result","metric_refusal"}` `agent/prompts.py:886`, `_planner_visible` `:889-899`, `_truncate_memory_history` `:901-929`; comment `:873-885` "Removing a key here is a rendering decision that belongs to Step 07a / 09" | | §3.7 extends the set with the two new record keys (07a owns hiding; 07b owns rendering); comment re-worded per parent §15 item 3 |
| Step-06 planner-boundary test `tests/unit/agent/llm_bridge/test_step06_planner_boundary.py` (byte-identical planner prompt with/without the hidden payload; `BoundaryRecorderBridge`) | | UPGRADE to cover the 07a keys + a NEW reflector-boundary test (parent §10 "MISSING — CAPTURE") |
| `ExperimentRecord` `agent/schemas/hyperparam_tuning.py:368-379` (`final_loss`, `loss_history`, `model_params`, unvalidated), `metric_result` / `metric_refusal` `:628-651` + validator `:654-690` (`_same_score`) | | §3.8 adds `training_history` / `training_diagnosis` ADDITIVELY beside them + an internal-consistency validator; `final_loss` semantics unchanged (OD-S7-3) |
| REC-2/REC-3 goldens (`rec2_*_projection.json`, `rec3_schema_field_lists.json`, `rec3_manifest_key_sets.json`, `rec3_summary_entry_key_lists.json`; `test_step00_record_baselines.py`) — Step 06 precedent: regenerated ADDITIVELY in the C4 commit with a three-part `_captured_at.note` | | same procedure in C3 (§15 C3) |
| 05c training argv ordered golden `tests/unit/core/test_step05c_c0_launch_cleanup_baseline.py:213-249` — the LEGACY (no sample set) argv; streaming-argv pins: `test_step02b_b1_sampleset_roundtrip.py`, `test_rt2b_streaming_preamble.py`, `test_rt2d_inference_verification.py`, `test_step02b_checkpoint_c_live_integration.py` (grep) | | the declared delta is ONE flag pair `--eval_sample_set_json <path>` emitted ONLY when a sample set AND an eval set are given; the legacy golden is unchanged; any streaming pin that lists the full argv is UPGRADED with the declared delta in the SAME commit |
| Layering: the trainer already imports `agent.schemas.*` (`:16-17`); `agent/schemas/hyperparam_tuning.py` imports `execute_tools.evaluation_metric` (`:37`); Step-06 precedent puts the producer-side schema in `execute_tools/`; `agent/schemas/model_io_resolution.py` holds pure derivation logic beside a schema | | `TrainingHistory` + the trainer→tuner results contract live in `execute_tools/training_history.py` (producer side); `TrainingDiagnosis` (schema + pure derivation) in `agent/schemas/training_diagnosis.py` — importable by `ExperimentRecord`, never `nodes` (layering) |

### 0.3 Test infrastructure

| Fact | Evidence | Consequence |
|---|---|---|
| `StubSandbox.execute_training` `core/sandbox_executor.py:2150-2178` fabricates `loss_history=[final_loss]` (ONE point); `RecordingSandbox` (`tests/helpers/recording_sandbox.py`) replays `tests/pseudo_data/train_outputs/{model}/execute_training.json` (5-epoch `loss_history`, no validation) | | OD-S7-4: BOTH emit a plausible multi-epoch train + validation history + the additive `training_history` payload (§3.10) — needed so pseudo runs and 07b's Gate 1 exercise a real diagnosis |
| In-process synthetic trainer harness: `tests/conftest.py:180` `synthetic_h5` writes `abra_training_0000.h5` (1 segment); `test_rt2b_streaming_preamble.py:30-93` binds a tiny profile and calls `run_experiment_streaming` directly on CPU (seconds); the Step-02 contrast fixtures vary `num_files` (`test_step02a_c6_contrast_rungs.py:137,198` `num_files=3`; `test_step02b_b4_topology_contrast.py:42` `num_files=7`) | | the trajectory oracle, the comparability fixture and rung B-07a-2 build on this harness with BOTH file families written (`abra_training_000i.h5` + `abra_validation_000i.h5`, 3 files) — honestly labelled a contrast-profile rung, NOT Track B/C |
| Gate standard `docs/gates/gate_testing_standard.md` §"Gate 2" `:79-235`: canonical bounded cold-start command `:100-121` (`--max_epochs 1`, `--validation_max_train_samples 2000`, `--data_scope 4-9` + `--health_gate_files 4,5,6,7,8,9`, `openai_tiered_pro.json`), PASS = functional `:206-233`, needs operator approval `:235`; assignment table `:371` "Checkpoint (end of feature) → Gate 2" | | §10 |

### 0.4 What the parent already decided (consumed, not re-derived)

R1 = the run-resolved training objective (no loss family frozen per task);
R3 = the SAME resolved computation on the validation scope, no backprop;
R2/R3 comparable; history persisted, hidden at BOTH renders; diagnosis
deterministic / compact / declared-observations-only / computed once;
calibrated labels never from curve shape alone; the EXISTING eval SampleSet
reaches the trainer (typed / fail-closed; no second split); `final_loss`
stays last-epoch train loss (OD-S7-3); Stub/pseudo upgraded (OD-S7-4);
Seam 5 written BEFORE code; example packs advanced honestly.

### 0.5 Operator review of revision 1 (2026-08-15) — corrections applied in this revision

Verdict: **APPROVE WITH TARGETED REVISION — NOT YET FREEZE.** Decomposition
and the four commits stand; the validation main path (train SampleSet →
training family; eval SampleSet → validation family; same criterion under
`eval()` / `no_grad` / `shuffle=False`; RNG isolation; two-arm oracle;
Gate 2 at the final head) is accepted.

| # | Class | Correction | Where |
|---|---|---|---|
| 1 | **BLOCKER** | **Fully-supported validation must not silently degrade to `absent`.** `absent` is a valid compatibility state ONLY when validation was not expected (legacy single-file caller). When the tuner supplied an `eval_sample_set` and the history carries no R3, that is a CONTRACT FAILURE → `error_training`, never a success record with `validation_state="absent"`. Decided at the tuner boundary (`expected_validation = eval_sample_set is not None`); mutation "drop the transport while expected → RED / `error_training`" | §3.4a, §3.5, §8, C2/C3 tests |
| 2 | **BLOCKER** | **A declared validation scope that resolves to zero or PARTIAL samples is a validation EXECUTION failure, not `nan` evidence.** `NaN` is reserved for numerical evidence (divergence / non-finite criterion). The materialized validation identity MUST equal the requested `eval_sample_set` (`N_evaluated == N_requested`, per file); the training path keeps its legacy skip semantics; the validation contract does not inherit silent shrink. Negative test: 5 requested, 4 materialize → no R3, structured training failure | §3.4b, §3.2, §8, C1 tests |
| 3 | SHOULD FIX | **R2/R3 comparability needs the objective-side precondition stated and source-audited**: the contract holds for objectives whose returned batch scalar is mean-normalized / sample-mean-compatible under the framework's batching (not for `sum`-reduced or batch-coupled objectives). Audited: built-ins under `reduction="mean"` satisfy it; `reduction="sum"` and custom plugin losses cannot be proven → `comparability="not_established"` recorded (never assumed); the reduction identity is not claimed for all future objectives | §3.3, §3.5, §3.6, §13 |
| 4 | SHOULD FIX | **State isolation, not only RNG isolation**: transactional `model.eval()` with `try/finally: model.train(was_training)`; the criterion is an `nn.Module` — freeze "validation MUST NOT mutate model, optimizer or training-objective state", audit the criterion classes, restore/verify; NumPy global RNG added to the isolation census; acceptance = state-neutral (model state_dict, optimizer state, objective module state, Python / NumPy / torch CPU+CUDA RNG identical before/after) | §3.2, C1 tests |
| 5 | SHOULD FIX | **`objective_id = loss_cfg.loss_type` is a family label, not a computation identity** (`focal(γ=1)` ≠ `focal(γ=4)`). Renamed `objective_kind` + a deterministic `objective_config_fingerprint` of the RESOLVED objective configuration surface (not a hash of plugin code); no new `TrainingObjective` class | §3.5 |
| 6 | SHOULD FIX | Trend deadband has a zero-reference pathology → symmetric scale-free relative change `r = |b−a| / max(|a|,|b|)` (0 when both 0); `observations` lists and `validation_seconds` must have `len == epochs_completed`, seconds non-negative | §3.6, §3.5 |
| 7 | disposition | Gate 2 placement confirmed (after C4 at the final executable head; 07c owes its own Gate 2; 07b Gate 1). **Q-07a-4 APPROVED: `--max_epochs 2`** — an upper bound only; PASS does NOT require two points | §10 |
| 8 | disposition | Q-07a-1 APPROVED (validation time excluded from the optimizer-step prior; the un-priced validation phase is recorded as **07c / runtime-control debt**); Q-07a-2, -3, -5, -7 APPROVED; **Q-07a-6 APPROVED WITH CORRECTION** (legacy absence OK; expected absence NOT OK — item 1) | §16 |

---

## 1. Capability / final effect

> The production trainer evaluates the run-resolved training objective on
> the run-bound validation scope after every epoch (R3) without perturbing
> the training trajectory, and emits a typed `TrainingHistory` (R2 + R3 +
> an optional checkpointed-observations slot) beside the three legacy keys;
> the eval SampleSet the tuner already builds reaches the trainer through
> ONE declared argv flag; the tuner interprets training results through a
> typed, fail-closed boundary, derives a deterministic `TrainingDiagnosis`
> ONCE, and persists both on `ExperimentRecord` — while the planner window
> and the reflector dump stay BYTE-IDENTICAL (PB-1/PB-2/WF-1/WF-2 exact).
> Pseudo routes emit multi-epoch histories; the three example packs state
> their R1/R2/R3 semantics and what the framework produces today.

The precise invariants:

1. **Trajectory and STATE parity.** With fixed seeds the train-loss
   trajectory is bit-identical with and without the validation pass, and
   the pass leaves model, optimizer, objective-module state and every RNG
   (Python / NumPy / torch CPU+CUDA) exactly as it found them (structural
   isolation + the two-arm oracle + the state census).
2. **Legacy floor byte-identical.** `final_loss`, `loss_history`,
   `model_params` — values and presence — unchanged in the results JSON, in
   `train_results`, at the reflect merge and on the record.
3. **One declared argv delta.** `--eval_sample_set_json <path>` and nothing
   else; emitted only in streaming mode with an eval set.
4. **R2 / R3 estimator and comparability.** R2 and R3 ALWAYS use the same
   declared epoch estimator formula (the sample-count-weighted mean of the
   criterion's batch scalar; R2's existing computation untouched; R3 exact
   under an unequal last batch). They are claimed mathematically comparable
   as observations of the SAME objective statistic ONLY when
   `comparability == "established"` (§3.3). When comparability is
   `not_established`, both histories may still be persisted as honest
   evidence, but the cross-curve diagnosis fields remain unavailable and
   that run MUST NOT claim the fully-supported R2/R3 comparability contract.
5. **Persisted, hidden.** Two additive record keys; both renders exact; the
   record is the only place they live.
6. **Diagnosis is a pure function** of `TrainingHistory` (deterministic,
   no I/O, no LLM); minimum capability per parent §8.2 item 3; no
   calibrated labels.
7. **Runtime-control semantics unchanged**: admission / verification /
   timeout / signal untouched; the validation pass is neither counted as
   optimizer steps nor included in the training ACTUAL; bounded by the eval
   set.
8. **`run()` gains sequencing calls only** (CLAUDE.md responsibility rule).
9. **Expected validation ≠ optional validation.** When the tuner supplied an
   eval SampleSet, a history without R3 is a contract failure
   (`error_training`); `absent` is legal only when no validation was expected.
10. **Declared validation scope ≠ whatever subset existed on disk.** The
    materialized validation identity equals the requested eval SampleSet or
    the attempt fails closed — never a shrunk R3.

---

## 2. Source evidence for the design decisions

§0 tables. Frozen semantics: parent §8.2, roadmap §20.2 / §22.1–§22.8 /
§22.9a. Gate table: standard `:371`. Test-infra rule: OD-S7-4. Example rule:
roadmap §22.23.7 / §22.23.8 (an `expected/` fixture only if the tests
consume it).

---

## 3. Scope

### 3.1 Files expected to change (categories fixed; names are this child's)

```text
execute_tools/train_engine_sandbox.py       R3 validation pass (streaming), TIDMADEpochDataset file_family,
                                            --eval_sample_set_json, additive `training_history` in the summary,
                                            RT accounting rule (§3.9)
execute_tools/training_history.py           NEW — TrainingHistory schema; TrainingResults typed contract
                                            (`interpret_training_results`); reduction identities
agent/schemas/training_diagnosis.py         NEW — TrainingDiagnosis schema + `derive_training_diagnosis()` (pure)
agent/schemas/hyperparam_tuning.py          ExperimentRecord: + `training_history`, + `training_diagnosis`
                                            (additive) + consistency validator
agent/skills/training_skill/wrapper.py      forward `eval_sample_set`
core/sandbox_executor.py                    execute_training(eval_sample_set=None): validate → write → argv;
                                            StubSandbox multi-epoch history payload
nodes/ml_hyperparameter_tune_agent/
    ml_hyperparameter_tune_agent.py         sequencing only: boundary call, diagnosis call, two record fields
agent/prompts.py                            _PLANNER_HIDDEN_RECORD_KEYS += 2 keys; comment :873-885 re-worded
tests/helpers/recording_sandbox.py, tests/pseudo_data/train_outputs/*/execute_training.json
                                            multi-epoch train + validation histories (test infra)
tests/unit/...                              new families (§9); REC-2/REC-3 goldens regenerated additively;
                                            planner-boundary test UPGRADED; new reflector-boundary test;
                                            any streaming-argv pin UPGRADED with the declared delta
docs/design/genericity_contract.md          Seam 5 — Training observation (BEFORE code, C1)
examples/{tidmad,oxford_iiit_pet,davis_future_prediction}/README.md, STATUS.md
                                            R1/R2/R3 + optional statements; what is produced today
examples/{oxford_iiit_pet,davis_future_prediction}/expected/   L1 fixture histories + expected diagnoses (JSON;
                                            consumed by rung B-07a-1) — labelled `l1_fixture`, no .py (PR0 pin)
nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md, agent/skills/training_skill/training_skill.md,
docs (README index rows, this ledger, parent §0/§8.2 status, roadmap §15.1/§22.12 at Checkpoint E)
```

### 3.2 The validation pass (FROZEN on approval)

Streaming mode only, after each training epoch, at the point where the
training dataset/loader have been released (`:1169-1170`) and the
mid-epoch admission rejection has been handled (`:1172-1176`).
**The pass is a transactional observation: it must leave every piece of
observable training state exactly as it found it.**

```text
PRE-FLIGHT (once, before epoch 0, before any optimizer step — §3.4b):
    every requested VALIDATION-family file exists AND every requested segment index is within it
    → otherwise ValidationScopeError (fail closed; no training time spent)

PER EPOCH:
was_training = model.training
snapshot: py_state = random.getstate(); np_state = np.random.get_state();
          criterion_state = deepcopy(criterion.state_dict())
try:
    model.eval()
    with torch.no_grad(), torch.random.fork_rng(devices=<[device.index] if CUDA else []>):
        val_dataset = TIDMADEpochDataset(data_dir, eval_sample_set, seg_size,
                                         train_portion=None,        # NO subsampling → no rng draw
                                         rng=None, profile=profile, file_family="validation")
        materialized rows == requested rows, per file (§3.4b) else ValidationScopeError
        val_loader  = DataLoader(val_dataset, batch_size=train_cfg.batch_size, shuffle=False, drop_last=False)
        for input_batch, target_batch in val_loader:
            <same dtype routing as training: resolve_input_dtype(...); get_target_torch_dtype(loss_cfg)>
            loss = criterion(model(input_seq), target_seq)
            accumulate loss.item() × batch_sample_count
        R3[ep] = Σ(loss_i × n_i) / Σ n_i           (Σ n_i > 0 guaranteed by the materialization contract)
finally:
    model.train(was_training)                     # never rely on the next epoch to restore mode
    random.setstate(py_state); np.random.set_state(np_state)
    if criterion.state_dict() != criterion_state → ObjectiveStateMutationError (fail closed: the objective
        module mutated itself under validation — a plugin violating the contract; never restored silently)
del val_dataset, val_loader; gc.collect()
```

- **State neutrality is structural**: `eval()` (no dropout, no BatchNorm
  running-stat update) + `no_grad` (no grads, no optimizer effect) +
  `shuffle=False` (SequentialSampler draws nothing) + `train_portion=None`
  (no `rng.sample`) + `fork_rng` (torch CPU/CUDA RNG) + Python-`random` and
  NumPy global-state restore + transactional mode restore + criterion
  state check. **Frozen rule: validation MUST NOT mutate model state,
  optimizer state or training-objective state.** Audit at `066d6b45`: the
  built-in criteria are stateless in `forward` — `FocalLoss1D` /
  `FocalLoss1DCW` hold immutable attributes (+ a `class_weights` buffer read
  only), `nn.CrossEntropyLoss` / `nn.SmoothL1Loss` are stateless
  (`loss_models_sandbox.py:135-216, 337-341`); custom plugin losses are
  arbitrary `nn.Module`s (`:218-278`; contract `PLUGIN_LOSS_CLASS /
  _CONFIG_CLASS / _TARGET_DTYPE / _TYPE` only) → the runtime state check
  above is what makes the rule executable for them.
- The two-arm oracle (§6, Checkpoint A) proves the trajectory bit-identical
  AND the state census equal (model `state_dict`, optimizer `state_dict`,
  criterion `state_dict`, `random.getstate()`, `np.random.get_state()`,
  `torch.get_rng_state()` / CUDA state) before vs after each pass; the
  delete-the-hop mutation removes the fork with a fixture model whose
  forward consumes torch RNG → oracle RED; a fixture criterion that
  increments a buffer in `forward` → `ObjectiveStateMutationError`.
- **Transient, not resident**: the validation dataset is rebuilt each epoch
  AFTER the training dataset is released, so peak resident memory is
  `max(train_epoch, validation)` not their sum (formal `train_portion=0.1`
  already holds ~8 GB of int8 rows; under `train_validation_align` the eval
  set is the same size). Cost: one extra HDF5 read of the eval scope per
  epoch — the engine's existing per-epoch reconstruction pattern. Recorded
  as `validation_seconds` per epoch in the payload (§3.5).
- **Never in legacy single-file mode** (no validation scope) and never on
  an attempt the runtime verification rejected (no results at all).
- **Cadence** = per epoch (v1, roadmap §22.3); a 1-epoch run yields a
  1-point R3 — legitimate.
- **Bounded** by the tuner's already-bounded eval SampleSet
  (`eval_portion`, `validation_max_portion` envelope, DataScope) — and by
  §3.4b never smaller than requested.

### 3.3 R2 / R3 comparability — statistic, PRECONDITION and audit (FROZEN on approval)

Audit (§0.1): R2 = `np.mean(batch_losses)` over `drop_last=True` equal
batches — the **sample-count-weighted mean of the criterion's batch
scalar** (equal weights). **R2 is not changed.** R3 = the SAME estimator
over the ENTIRE validation set (`drop_last=False`, weights = batch sample
counts): `Σ n_i·L_i / Σ n_i`. Both carry the identity
`epoch_statistic = "sample_count_weighted_mean_of_batch_criterion"`.

**Precondition P (frozen, stated honestly — the operator's correction 3).**
The two statistics are comparable AS THE SAME OBJECTIVE ONLY when the
criterion's batch scalar is mean-normalized over the batch's samples /
elements — i.e. `L(B) = (1/|B|)·Σ_{i∈B} ℓ_i` so that
`Σ_b |B_b|·L(B_b) / Σ_b |B_b| = Σ_i ℓ_i / N`. A `sum`-reduced objective
(`L(B) = Σ ℓ_i`) or a batch-coupled objective (`L(B) ≠ (1/|B|)Σ ℓ_i`,
e.g. contrastive) does NOT satisfy P; for those R2 and R3 are still the
same estimator formula but they are NOT claimed to be the same objective
statistic. 07a invents no `TrainingObjective` abstraction; it RECORDS
whether P is established:

| Objective (run-resolved) | Batch scalar under the framework's batching | P |
|---|---|---|
| `focal` (`FocalLoss1D`, `reduction="mean"`) | element-wise focal term summed over the class axis, then `.mean()` over B×T (`:147-168`); fixed T per sample → per-sample-mean-decomposable | **established** |
| `focal_cw` (`FocalLoss1DCW`, `reduction="mean"`) | same shape; class weights are per-element multipliers (NO normalization by weight sum) then `.mean()` (`:191-216`) | **established** |
| `ce` (`nn.CrossEntropyLoss(weight=None, reduction="mean")`) — the streaming path ALWAYS passes `class_weights=None` (`train_engine_sandbox.py:884`) | element mean | **established** (streaming); legacy single-file may pass `weight` → weight-normalized mean, but legacy has no R3 anyway |
| `smooth_l1` (`nn.SmoothL1Loss(reduction="mean")`) | element mean | **established** |
| any built-in with `LossConfig.reduction="sum"` (`models_format_sandbox.py:646` allows it) | batch SUM — not mean-normalized | **not_established** (`reason="reduction=sum"`) |
| `custom` plugin loss (`_load_custom_loss` `:218-278`; the plugin contract declares no reduction / normalization) | unknown | **not_established** (`reason="custom_objective_undeclared"`) — follow-up: the plugin loss contract may later declare mean-normalization (owner: Step 12 / loss-plugin contract), then this row flips by declaration, never by assumption |

The trainer computes R3 with the same formula in EVERY case (the estimator
is well-defined) and stamps `comparability` on the payload
(`"established"` iff `reduction=="mean"` AND the objective is in the
audited built-in set at that head; otherwise `"not_established"` with the
reason). The diagnosis's CROSS-curve fields (train–validation gap) are
`None` when comparability is not established (§3.6); within-curve facts
(best epoch, trends, degradation) remain valid. **Stop condition (parent):**
if the audited built-in mean-reduced set could NOT be proven decomposable
from source, R2/R3 could not be made comparable without changing R2 →
STOP. (It is proven above; sum/custom are LABELLED, which is the honest
generic path.)

The comparability test (§6) uses a validation set whose size is not a
multiple of `batch_size` and checks R3 against an independent per-sample
reference AND that the unweighted mean-of-batch-means (the mutation) is
REJECTED; a `reduction="sum"` fixture and a custom-loss fixture must yield
`comparability="not_established"` with the right reason.

### 3.4 Transport (FROZEN on approval — instantiates OD-S7-1)

```text
tuner active_params["eval_sample_set"]  (exists, :4751)
  → wrapper.py forwards eval_sample_set=kwargs.get("eval_sample_set")
  → TidmadSandbox.execute_training(..., eval_sample_set: dict | None = None)
      if sample_set is not None and eval_sample_set is not None:
          eval_sample_set = validate_sample_set(eval_sample_set, scope=self.data_scope)   # same rule as train
          write configs/<run>/eval_sample_set_<exp_id>.json (compact json.dump — the pinned byte form)
          cmd += ["--eval_sample_set_json", <path>]        # DECLARED delta; position: immediately after
                                                          # the --sample_set_json pair (its sibling)
  → trainer main(): --eval_sample_set_json → json.load → run_experiment_streaming(eval_sample_set=...)
```

- Legacy mode (`sample_set is None`) never emits the flag → the 05c legacy
  argv golden is unchanged. Streaming argv pins that list the full list are
  UPGRADED with exactly this pair, in the same commit, with the delta named
  in the test docstring (05c §4.2 "documented normalization" pattern).
- **Fail-closed at the child**: `--eval_sample_set_json` SUPPLIED but
  unreadable / not a `{file: [segments]}` mapping → `ValueError` naming the
  path (the profile / model-I/O two-case rule `:1345-1356`). ABSENT → no
  validation pass (legacy tolerance; R3 absent, recorded as such).
- **No second split concept**: the flag carries the tuner's EXISTING eval
  SampleSet unchanged; the trainer does not derive, resample or re-split.
- StubSandbox / RecordingSandbox accept `eval_sample_set` for signature
  parity (V19-PR2 / RT2-B precedent) and validate scope like the executor.

### 3.4a Expected validation ≠ optional validation (FROZEN — operator blocker 1)

```text
LEGACY / validation NOT expected      (no eval SampleSet: legacy single-file caller, a caller predating the flag)
    validation absent  → valid compatibility state: history.validation_objective = None,
                         diagnosis.validation_state = "absent"  ("not fully supported", recorded)

FULLY-SUPPORTED / validation EXPECTED (the tuner built an eval SampleSet for this attempt)
    validation absent  → CONTRACT FAILURE: TrainingResultsContractError at the tuner boundary
                         → the attempt is recorded through the EXISTING training-failure path
                           (`error_training`) — NEVER a success record with validation_state="absent"
```

The judgement is made where the expectation is known — the tuner:
`interpret_training_results(raw, expected_validation=(eval_sample_set is
not None))`. This closes the wrapper/executor-drop class of defect (the
exact bug that motivated OD-S7-1) permanently: a re-dropped eval set can
no longer produce a quiet success. The trainer stays backward-compatible
(flag absent → no pass). Acceptance + mutation: drop the eval transport
while the tuner expected validation → RED / `error_training` (C2/C3).

### 3.4b Declared validation scope must materialize EXACTLY (FROZEN — operator blocker 2)

`R3 = Σ n_i·L_i / Σ n_i` does not exist when `Σ n_i = 0`, and a scope that
quietly lost a file has CHANGED the validation identity. Therefore, for the
validation pass (NOT for the training path, which keeps its legacy
skip-a-missing-file semantics `:369-371`):

```text
requested = the eval SampleSet: {file_index: [psd_segments]}
pre-flight (before epoch 0, before any optimizer step):
    for each requested file: the VALIDATION-family file exists AND every requested
    segment index < the file's segment count → else ValidationScopeError (fail closed, cheap)
per epoch:
    materialized rows == Σ_files len(segments) × ml_segs_per_psd, per file (file_row_ranges)
    → else ValidationScopeError (defense in depth: the disk changed mid-run)
```

`ValidationScopeError` is a trainer failure (non-zero exit → the executor's
existing subprocess-error path → `error_training` at the tuner). NO R3 is
emitted, `NaN` is never used for a missing scope — `NaN` stays reserved for
numerical evidence (divergence, a non-finite criterion). Negative test:
5 requested validation segments, 4 materialize (one file missing / one
index out of range) → no results JSON, structured failure; also `Σ n_i = 0`.
`TrainingHistory.validation_samples` records the materialized count and the
schema validator requires it to equal the requested count carried in the
payload (`validation_requested_samples`).

### 3.5 `TrainingHistory` and the typed trainer→tuner contract (FROZEN on approval)

`execute_tools/training_history.py`:

```text
TrainingHistory (frozen, extra="forbid")
  cadence:                Literal["per_epoch"] = "per_epoch"
  objective_kind:         str        # the run-resolved objective FAMILY = loss_cfg.loss_type (a label — NOT an identity)
  objective_config_fingerprint: str  # deterministic SHA-256 of the canonical serialized RESOLVED LossConfig
                                     # (loss_type, loss_name, alpha, gamma, beta, reduction, use_class_weights …).
                                     # A fingerprint of the resolved objective CONFIGURATION surface: it distinguishes
                                     # e.g. focal(γ=1) from focal(γ=4) within that surface; it does NOT hash or fully
                                     # identify arbitrary custom plugin implementation code (no plugin provenance
                                     # mechanism in 07a); no new class introduced
  objective_reduction:    Literal["mean", "sum"]      # LossConfig.reduction as resolved
  epoch_statistic:        Literal["sample_count_weighted_mean_of_batch_criterion"]   # R2 and R3 formula
  comparability:          Literal["established", "not_established"]                  # §3.3 precondition P
  comparability_reason:   str | None                  # "reduction=sum" | "custom_objective_undeclared" | None
  epochs_planned:         int  (train_cfg.epochs)
  epochs_completed:       int  (= len(train_objective))
  train_objective:        list[float]        # R2 — the SAME floats as loss_history
  validation_objective:   list[float] | None # R3 — None ONLY when no validation scope was given (§3.4a)
  validation_requested_samples: int | None   # ML segments requested by the eval SampleSet
  validation_samples:     int | None         # ML segments materialized (== requested, §3.4b)
  validation_seconds:     list[float] | None # per-epoch wall time of the pass (≥ 0; len == epochs_completed)
  observations:           dict[str, list[float]] = {}   # optional checkpointed observations (v1 empty);
                                                        # each list len == epochs_completed
  validators: len(validation_objective) == len(train_objective) when present; epochs_completed <= epochs_planned;
              validation_samples == validation_requested_samples when present, and > 0;
              every observations[*] and validation_seconds has len == epochs_completed; seconds >= 0;
              values may be non-finite (a diverged run is EVIDENCE, not a schema error) but lengths must agree

TrainingResults (the typed trainer→tuner contract; the ONE validation site = the tuner boundary)
  legacy_payload:  dict   — {k: raw[k] for k in ("final_loss","loss_history","model_params") if k in raw}
                            (presence AND values exactly as today; feeds the reflect merge and the record)
  history:         TrainingHistory | None   — None when the producer emitted no `training_history` key
  history_state:   Literal["present","absent"]
  interpret_training_results(raw: dict, *, expected_validation: bool) -> TrainingResults
      raises TrainingResultsContractError (a ValueError) when:
        • `training_history` IS present but schema-invalid;
        • history.train_objective != raw["loss_history"], or final_loss != train_objective[-1];
        • expected_validation and (history is None or history.validation_objective is None)   ← §3.4a
      (a producer violating its own contract, or an expected R3 that did not arrive, is a bug → fail closed,
       never silently downgraded)
```

The trainer's summary becomes `{final_loss, loss_history, model_params,
training_history: <dump>}` — legacy keys first, byte-identical values.

### 3.6 `TrainingDiagnosis` (FROZEN on approval — instantiates parent §8.2 item 3)

`agent/schemas/training_diagnosis.py` — a PURE function of `TrainingHistory | None`:

```text
TrainingDiagnosis (frozen, extra="forbid")
  state:                 Literal["ok", "absent", "invalid"]
                           absent  — no history payload (legacy trainer / pseudo route not upgraded / crash)
                           invalid — empty train_objective, or any non-finite value in R2/R3 (divergence
                                     evidence; the raw values stay on the record), or length mismatch
  validation_state:      Literal["present", "absent"]      # absent → "not fully supported" (OD-20-4 tolerance)
  epochs_planned, epochs_completed: int;  truncated: bool  (completed < planned — stability stop / early exit)
  train_first, train_last, train_min: float | None;  train_min_epoch: int | None   (0-based, the trainer's epoch numbering)
  validation_first, validation_last, validation_min: float | None;  best_validation_epoch: int | None (argmin R3)
  final_vs_best_validation_degradation: float | None       (validation_last − validation_min ≥ 0)
  final_vs_best_validation_degradation_rel: float | None   (r(validation_min, validation_last), below)
  train_validation_gap_final: float | None                 (validation_last − train_last, signed) — None unless
                                                           history.comparability == "established" (§3.3)
  train_validation_gap_final_rel: float | None             (symmetric relative change, below) — same gating
  comparability: Literal["established","not_established"]  (copied from the history, so a consumer of the
                                                           diagnosis alone knows why the gap is None)
  train_trend, validation_trend: Literal["decreasing","increasing","flat","single_point"] | None
      trend = sign(last − first) with an EXPLICIT scale-free SYMMETRIC deadband:
          r(a, b) = 0                       if |a| = |b| = 0
                  = |b − a| / max(|a|, |b|) otherwise           (scale-invariant; no zero-reference pathology)
          r(first, last) ≤ FLAT_REL_TOL → "flat"; else the sign decides; a 1-point history → "single_point"
      FLAT_REL_TOL is a named module constant of the boundary (default 1e-2), recorded on the diagnosis as
      `flat_rel_tol` so a consumer can re-derive; the raw endpoints are on the diagnosis too
  final_vs_best_validation_degradation_rel and train_validation_gap_final_rel use the SAME r(·,·)
  validation_degraded_after_best: bool | None   (r(validation_min, validation_last) > FLAT_REL_TOL AND
                                                validation_last > validation_min) — the calibration-free shape
                                                fact behind "overfitting evidence"; NOT labelled overfitting
  flat_rel_tol: float
```

- **No `overfitting` / `converged` / `plateau` / `underfitting` labels in
  v1** — each needs a window, a tolerance policy or an "is this good enough"
  scale that curve shape alone cannot supply (parent §8.2 item 3, review
  finding 12). 07b renders SELECTED facts; Step 09 may derive higher-level
  labels later with declared calibration. The vocabulary above is the
  parent's minimum capability made exact.
- Deterministic; no I/O; no LLM; computed ONCE at the tuner boundary and
  never re-derived; identical output for identical input (pinned by test).

### 3.7 Hidden at BOTH renders (FROZEN on approval — instantiates parent §8.2 item 4)

- Reflector: `train_results = results.legacy_payload` (exactly the legacy
  keys) feeds `reflect_results = {**train_results, **score_results}` — the
  `actual_results` dict at `brain.reflect` carries NO new key (WF-2 exact),
  hence `json.dumps(actual_results)` in the reflector prompt is byte-identical
  (PB-2 exact).
- Planner: `_PLANNER_HIDDEN_RECORD_KEYS = {"metric_result", "metric_refusal",
  "training_history", "training_diagnosis"}` (the Step-06 mechanism, extended;
  PB-1 / WF-1 exact). The record is untouched — a rendering decision.
- Guarded by: the UPGRADED planner-boundary test (both new keys), the NEW
  reflector-boundary test (a record/train result WITH history → the recorded
  `actual_results` key set equals the WF-2 golden and the rendered user
  prompt is byte-identical to the no-history render), PB-1/PB-2/WF-1/WF-2
  unchanged files.

### 3.8 Record attachment (FROZEN on approval)

`ExperimentRecord` (additive, default `None`): `training_history:
TrainingHistory | None`, `training_diagnosis: TrainingDiagnosis | None`.
Validator (`mode="after"`, the `metric_result` precedent): when both
`training_history` and `loss_history` are present they are equal; when
`final_loss` and the history are present, `final_loss` equals
`train_objective[-1]`; when `training_diagnosis` is present its
`epochs_completed` equals `len(training_history.train_objective)` (or the
diagnosis is `absent`/`invalid` consistently). `final_loss` semantics
unchanged (OD-S7-3): dashboard readers (`dashboard/*`, 6 sites — grep) and
scripts see the same value. Failure / skip records carry `None` for both.
`HyperparamTuningOutput` unchanged (records carry the fields).

### 3.9 Runtime-control accounting (FROZEN on approval)

- The verifier is fed ONLY inside the training batch loop (`:1125-1133`);
  the validation pass sits after the epoch's loop and after `del dataset,
  loader` — validation batches are NEVER counted as optimizer steps
  (`unit="optimizer_step"` stays true).
- The training ACTUAL keeps its definition (admission → last optimizer step,
  incl. epoch reconstruction) by **subtracting the accumulated validation
  seconds** before `record_phase_actual("training", …)` — otherwise the
  observation store's realized unit ms (`actual ÷ unit_count`,
  `observation_store.py:160-176`) would inflate every training prior by the
  validation share, and prediction errors would be misattributed.
- The validation pass is NOT modelled by admission / prediction / the
  watchdog deadline in this PR (parent §2.1 accepts this: it is bounded by
  the eval set). `validation_seconds` is persisted in the payload as the
  evidence for the follow-up "runtime model gains a validation term" —
  **recorded as 07c / runtime-control debt** (operator disposition of
  Q-07a-1: APPROVED; the un-priced validation phase is explicitly a debt
  entry in §14 and in the parent §14 convergence ledger at Checkpoint E).
- Admission, verification, timeout, signal, watchdog kill, stability stop,
  sidecar shapes: UNTOUCHED (existing RT2/RT4/C2 tests green = the evidence).

### 3.10 Test infrastructure (OD-S7-4)

- `StubSandbox.execute_training`: deterministic (seeded by the stub's rng)
  5-epoch train history (monotone-ish decreasing) + validation history
  (decreasing then slightly rising) + the `training_history` payload;
  `final_loss` = last train value; `loss_history` = the train list.
- `tests/pseudo_data/train_outputs/*/execute_training.json`: `results`
  gains `training_history` consistent with the existing 5-epoch
  `loss_history` (values unchanged) + a validation list.
- `RecordingSandbox.execute_training`: accepts `eval_sample_set`
  (signature parity), replays the upgraded canned results.
- No test may READ the diagnosis back to assert its own inputs (CLAUDE.md
  test rule): rung fixtures pin expected diagnoses as literals.

### 3.11 Example packs (parent §8.2 item 7; roadmap §22.23.7/§22.23.8)

- `examples/tidmad/`: README/STATUS gain the row "training observation:
  R1 = the run-resolved training objective (`loss_config.loss_type`; a loss
  family is a run choice, not task semantics); R2 = per-epoch mean training
  objective; R3 = the same computation on the run-bound validation scope
  (`eval_sample_set`, VALIDATION file family) — **production-backed from
  07a**; optional checkpointed observations: none declared". No new
  `resolved/` snapshot (nothing new is a production authority to project;
  the history is per-run evidence, not task config).
- `examples/oxford_iiit_pet/`, `examples/davis_future_prediction/`:
  README/STATUS state R1/R2/R3 + optional per §22.9a (Pets: CE objective,
  CE validation curve, optional validation accuracy; DAVIS: MAE objective,
  MAE validation curve, optional validation PSNR); STATUS row "training
  history/diagnosis: L1 — fixture-backed (`expected/training_history_l1_fixture.json`,
  `expected/training_diagnosis_l1_fixture.json`) consumed by rung B-07a-1;
  real R2/R3 after D14". JSON only (PR0 `.py` pin), labelled `l1_fixture`,
  never presented as a real training result.
- Guard (C4): the L1 fixtures ARE what the rung test loads (no
  consumer-less files) — the test reads them from the packs.

### 3.12 Non-goals (must remain unchanged)

No planner/reflector byte or kwarg key (07b renders); no interpreter /
proposer transport (Step 09); no `TrainingObjective` type / loss abstraction;
no cadence beyond `per_epoch`; no multi-objective; no new memory store; no
change to `final_loss` / `loss_history` / `model_params` semantics or the
same-loss rank (`:5746-5761`, `:5831`); no change to retry / round / timeout
/ signal / admission / verification / watchdog semantics; no change to
scoring, metric, deliverable, argv other than the ONE declared pair; no
Pets/DAVIS data path (D14); no D16/D17/D18; no `run()` branching; no
production `.py` under `examples/`; no policy consumption of the diagnosis
(07b decides what, if anything, policy reads).

---

## 4. Consumers — production persistence IS the first consumer (parent §7 row 2)

```text
trainer (R2/R3 → TrainingHistory in results JSON)
   → executor (verbatim forwarder)
   → tuner boundary interpret_training_results (typed, fail-closed)
   → derive_training_diagnosis (pure, once)
   → ExperimentRecord.training_history / training_diagnosis  (persisted: records JSONL, run_output_*.json)
        ↳ hidden from planner window + reflector dump (07a)
        ↳ rendered SELECTIVELY by 07b; condensed for the interpreter by Step 09
```

Real consumer of the transport hop: `TIDMADEpochDataset(file_family=
"validation")` in the production trainer reading the eval SampleSet the
executor wrote (rung B-07a-2 through the production argv). The diagnosis's
consumer is the persisted record (Checkpoint C) — the Step-06 `metric_result`
precedent; no consumer-less seam is created (frozen Q2 split).

## 5. Stage-A parity (Checkpoint 0 / A)

- Checkpoint 0 (BEFORE the first production edit, recorded in §14): (a) the
  fixed-seed train trajectory of the in-process synthetic 3-file streaming
  fixture (values recorded in the ledger; the CI oracle is the two-arm test,
  not a cross-machine float golden); (b) the 05c argv oracle (reuse); (c)
  REC-3 field lists / manifest key sets (to be regenerated additively); (d)
  WF-1/WF-2 key sets and PB-1/PB-2 files (must NOT change).
- Checkpoint A: two-arm oracle bit-identical (`loss_history` with the flag ==
  without, fixed `train_base_seed`, fixed torch seed, CPU); three legacy
  JSON keys byte-identical (values and presence); `ExperimentRecord`
  existing fields unchanged; PB-1/PB-2/WF-1/WF-2 files unchanged; training
  argv == 05c oracle (legacy) and == streaming pins PLUS exactly the
  declared pair; R2/R3 comparability on the unequal-last-batch fixture;
  RT2-B/RT2-D/RT4/C2 tests green; verification unit count unchanged;
  training ACTUAL excludes validation seconds (test); dashboard readers of
  `final_loss` unaffected (value identity).

## 6. Stage-B rungs (declared REQUIRED by the parent)

- **B-07a-1 diagnosis-structure axis (L1, atomic)** — the SAME
  `derive_training_diagnosis` over three `TrainingHistory` fixtures carrying
  the EXACT frozen semantics: TIDMAD (run-resolved objective; representative
  atomic fixture `objective_kind="focal"`), Pets (`objective_kind="ce"`, CE
  train/validation + `observations={"validation_accuracy": [...]}`), DAVIS
  (`objective_kind="mae"`, MAE train/validation + `observations=
  {"validation_psnr": [...]}`) → the expected verdict shapes (best epoch,
  degradation, gap, trends) pinned as literals; only the history / objective
  identity varies (atomicity machine-checked by diffing the fixtures'
  non-value fields). Fixtures live in the packs' `expected/` (§3.11) and are
  loaded from there. No image/video, no loader.
- **B-07a-2 validation-scope axis (L2, real component)** — the REAL trainer
  entry (`run_experiment_streaming` through `main()` argv, or the executor's
  `execute_training` with `_run_observed_subprocess` un-mocked on CPU) on a
  synthetic 3-file contrast profile (`num_files=3`, both families written)
  emits R2 + R3 over a DISTINCT validation sample set through the production
  argv — labelled a contrast-profile rung, NOT Track B/C.
- Robustness (not rungs): shortened history (`epochs_completed <
  epochs_planned`), R3 absent, NaN epoch → `state="invalid"` with raw values
  preserved.

## 7. Checkpoint C — real training through the production path

A bounded real-training run (pseudo LLM allowed) whose `run_output_*.json`
record carries `training_history` (R2 + R3) and `training_diagnosis`
produced by trainer → executor → tuner. Instantiated by the Gate-2 run
(§10) — the same run serves both — or, if the operator prefers a cheaper
instantiation first, by the existing pseudo-LLM + real-training route with
the Gate's bounds; either requires operator approval (real training).

## 8. Failure classes (each has a test or a stop rule)

| Failure | Behaviour |
|---|---|
| validation pass perturbs the training trajectory or any training state (model / optimizer / objective / Python / NumPy / torch RNG) | two-arm oracle or state census RED → STOP (parent stop, revision-2 wording: cannot be made training-state-neutral) |
| `--eval_sample_set_json` supplied but unreadable / wrong shape / violates DataScope | trainer `ValueError` (fail closed) / executor `ScopeViolationError` path — never a silent fallback |
| flag absent AND validation NOT expected (legacy / caller predating it) | R3 absent, `validation_state="absent"`, diagnosis `state="ok"` — recorded, never silent |
| validation EXPECTED (tuner built an eval SampleSet) but the history carries no R3 (transport dropped, producer regressed) | `TrainingResultsContractError` at the tuner boundary → `error_training` record — NEVER a success record (§3.4a) |
| declared validation scope materializes to zero or PARTIAL samples (missing validation file / index out of range / rows ≠ requested) | `ValidationScopeError` in the trainer (pre-flight before epoch 0; per-epoch defense) → subprocess error → `error_training`; NO R3, never `nan` (§3.4b) |
| the objective module mutates its own state under validation (custom loss) | `ObjectiveStateMutationError` → `error_training` (§3.2) |
| `reduction="sum"` or a custom objective | R3 computed by the same estimator; `comparability="not_established"` + reason; cross-curve diagnosis fields `None` — recorded, never assumed comparable (§3.3) |
| producer emits `training_history` that violates the contract (schema, R2 ≠ `loss_history`, `final_loss` ≠ last R2) | `TrainingResultsContractError` at the tuner boundary → the attempt is recorded through the EXISTING training-failure record path (`error_training`); never downgraded to "absent" |
| history shorter than planned (stability stop / early exit) | `truncated=True`; diagnosis over the completed prefix |
| non-finite R2/R3 value | `state="invalid"`, raw values persisted |
| a new key reaches `actual_results` or the planner window | WF-2 / PB-1 / PB-2 / boundary tests RED → Gate 1 would flip → STOP until hidden |
| validation seconds leak into the training ACTUAL | RT accounting test RED |
| memory: validation dataset resident beside the training dataset | design forbids (transient after release); test asserts construction order |
| eval SampleSet violates scope | existing `validate_sample_set` refusal (same rule as train) |
| pseudo/stub history missing → downstream 07b Gate 1 renders degenerate | OD-S7-4 tests on StubSandbox / pseudo data shape |

## 9. Test disposition

New families (each names the defect only it catches): trainer validation
pass + RNG oracle (+ fork mutation); comparability (+ reversal mutation);
transport (flag emitted only in streaming with eval set; fail-closed child;
argv delta declared); typed results contract (+ malformed → error);
diagnosis rules (each rule mutated → RED; determinism pin; robustness);
record attachment + validator; hidden-key filter at BOTH renders; Stub /
pseudo history shape; Seam-5 doc presence; rungs B-07a-1/-2; pack STATUS
pins; RT accounting. UPGRADED: Step-06 planner-boundary test (two keys);
streaming-argv pins (declared delta); REC-2/REC-3 goldens (additive
regeneration, three-part note). KEPT: everything else. DELETED: none.
Existing pins the parent lists (`test_delta_gates`, selection pins) are
07b's — untouched here.

## 10. Gates — from the standard's table (`docs/gates/gate_testing_standard.md:371`)

| Commit type | Typical gate |
|---|---|
| Config files, YAML, schema-only | Unit only |
| Prompt placeholder substitution | Unit only + optional Gate 1 |
| Checkpoint (end of feature) | Gate 2 |

- **Gate 1 NOT REQUIRED**: no rendered byte, no kwarg key changes (PB/WF
  exact is a hard acceptance criterion). Flip: any planner/reflector byte or
  key → Gate 1 REQUIRED (and this design is wrong — STOP).
- **Gate 2 REQUIRED, bounded, ONCE at the final executable head after C4**:
  the standard's canonical cold-start command (`:102-121`),
  `openai_tiered_pro.json`, DS8 pairing, no `--seed_paths`. PASS =
  functional (`:206-233`) **plus** the 07a boundary evidence (`:221-222`
  item 9): the run's `run_output_*.json` record carries `training_history`
  with R2 and R3 lists and a `training_diagnosis` with `state="ok"`,
  `validation_state="present"`. **Proposed bounded deviation for operator
  decision at launch (Q-07a-4)**: `--max_epochs 2` instead of `1`, so R2/R3
  carry two points and `best_validation_epoch` / trends are non-degenerate;
  cost ≈ one more ~2 000-sample epoch. **Operator disposition (2026-08-15):
  APPROVED — `--max_epochs 2` is an upper bound only; the planner may still
  elect 1 epoch and a 1-point R2/R3 is a legitimate functional PASS.**
  Sequence: 07a Gate 2 (this) · 07b Gate 1 · 07c its own bounded Gate 2
  (measurement / data-feeding changes real execution). **NOT launched during
  design; NOT launched during implementation without explicit operator
  approval at launch.**
- Corpus breadth (§22.13): TIDMAD executable; Pets/DAVIS contribute B-07a-1
  (L1) with the reason recorded (D14 not landed).

## 11. Validation budget

Targeted unit families per commit (seconds each; the in-process trainer
oracle a few seconds on CPU); the full unit suite ONCE at the final
executable head from a clean tree; exact-head CI once; ONE bounded Gate 2
(~10–20 min, ~$1–2) with operator approval; no other real LLM / real
training / real inference.

## 12. Rollback boundary

Reverting the PR removes the validation pass, the flag, the two schemas, the
two record fields, the hidden keys, the test infra upgrade, Seam 5 and the
pack rows; the goldens revert to their pre-07a captures. Nothing else
depends on them (07b is designed against the record fields this child
freezes and lands after).

## 13. Stop conditions

Parent §8.2 stops: the pass cannot be made training-state-neutral (training state = the frozen model / optimizer / training-objective / Python / NumPy / torch RNG invariants of §3.2); the existing
sample-set machinery cannot express the validation set without a new SPLIT
concept; R2/R3 cannot be made comparable without changing R2 (§3.3: the built-in mean-reduced set is proven; `sum` / custom are LABELLED not_established, which is not a stop); reflector /
planner bytes cannot be held exact; any change to retry / round / timeout /
signal semantics; > ~1 h wall or material cost per attempt. Child stops: a
production file outside §3.1 must change; `run()` needs a new branch; a
consumer must READ the diagnosis for policy (07b); the RT observation schema
must change to record validation time (out of scope — the payload carries
it); a schema must be bent for Pets/DAVIS fixtures; a Gate must be launched
without approval.

---

## 14. Implementation ledger

Implementation under the Implementation Working Rules contract of
2026-08-15 (autonomous C1→C4, ONE pre-authorized bounded Gate 2, PR, CI,
then READY FOR OPERATOR REVIEW; never merge). Implementation branch
`step07-pr07a-training-history-diagnosis` from base `5f10b7f5`
(`5f10b7f582dad2dd9e3ca7b4ad30e18be144f268`, == `origin/master`, tree
clean at start). Handoff re-initialised for THIS PR via
`tools/claude_hooks/init_pr_handoff.py`.

### 14.0 Checkpoint 0 — Stage-A baseline captured BEFORE the first production edit

Source drift check at `5f10b7f5`: every line cited in §0 re-read; the
trainer (`train_engine_sandbox.py:289-448, 652-779, 782-1235, 1243-1489`),
`dataset_config.py:127-142`, `loss_models_sandbox.py:135-216, 218-278,
321-345`, `models_format_sandbox.py:637-651`, `observation_store.py:160-176`
are UNCHANGED versus the §0 audit (PR0 and the freeze commits touched no
production module) — no drift.

**(a) Fixed-seed streaming trajectory** — in-process harness (scratch
`ckpt0_capture.py`, reproduced by the C1 test fixture): 3-file synthetic
contrast profile (`num_files=3`, `psd_segment_length=2000`,
`segments_per_file=4`, `seg_size=1000` → 2 ML segs/PSD, 8 rows/file, 24 rows
total), BOTH families written (`abra_training_000i.h5` /
`abra_validation_000i.h5`, distinct payloads), tiny wavenet
(`input_channels=4, residual=gate=skip=8, kernel=2, blocks=1`, 3 696 params),
`TrainConfig(lr=1e-3, epochs=3, batch_size=2, adam, cpu)`, `LossConfig()`
(focal, mean), `random.seed(7); np.random.seed(7); torch.manual_seed(0)`,
`train_base_seed=123`, `train_portion=None`, `sample_set={0,1,2: [0..3]}`:

```text
loss_history   = [2.763463576634725, 2.7615448435147605, 2.7601086099942527]
final_loss     = 2.7601086099942527        model_params = 3696
summary keys   = ["final_loss", "loss_history", "model_params"]     (exactly three)
legacy json    = {"final_loss": 2.7601086099942527, "loss_history": [2.763463576634725,
                  2.7615448435147605, 2.7601086099942527], "model_params": 3696}
loader len     = 12 per epoch (24 rows / batch 2, drop_last)  ×3 epochs
model state    sha256 fa1ca3a4593f546b57e55fe5a37b5e5b9a593757d89a8c2c309c8e5392de6106
py RNG after   sha256 7e3ca2de8f7a…6d650849   torch RNG after sha256 529bbf1152a8…5790211
wall           3.3 s (incl. plugin import)   — run TWICE in separate processes: every field SAME
```

**(b) argv oracle**: 05c legacy golden
`tests/unit/core/test_step05c_c0_launch_cleanup_baseline.py:213-249` reused
unchanged (C2 asserts it stays green).

**(c) REC-2 / REC-3 goldens (to be regenerated additively in C3)** and
**(d) PB-1 / PB-2 / WF-1 / WF-2 (must NOT change)** — sha256 at `5f10b7f5`:

```text
a691a7f5eecce5a81cb5e802110bc8c9708d2ab4a69e52c850a2f61d9e4c8e62  pb1_planner_auto_system.txt
3b8677e8861aa0b01d1684fe684b5f23f85c0d5f752e75b89602597cffff198e  pb1_planner_auto_user.txt
b0cb4d90933cefe950154e9ab0ecc701974e9ee52150e0214aa281f9957f3aba  pb1_planner_force_punet_user.txt
3566caec033e4a42c137ef2c39960e4e98177676ce6c1a89f38abc125e1f95ac  pb2_reflector_system.txt
81fa5f496a412a1118dfd141b670da335206594ecb65c83cc56f65f3000e3e06  pb2_reflector_user.txt
5e8943f68de20209a84e0b349466e1dc0d9bac740b142ae9ada829e294682c53  wf1_plan_call_round1_surface.json
ee7403bd6d6e12620789e3da6b24dbb3b168fc04fc2e98cf54efe1600425b530  wf1_plan_kwarg_key_set.json
bbf33b097b999f6ec1bf643d8438bcb629bc8106109fd154c661241dffe8868b  wf2_reflect_call_surfaces.json
8e3f3134655bfc5209613c165b5211ea43862e15bda5b87d558b8f343a226221  rec2_formal_success_projection.json
de89a27a24abc12c02e92c9646481aa12b2d658a7d9f13e31d1c8c0844762608  rec2_oom_skip_projection.json
d2c319a9c084e5ce8be1b6a375356434990af4326d561db6fbc51734801dff97  rec3_manifest_key_sets.json
7d7be2396bb845f2e3b8d0487516124a174fd5168932be8c32415a7c4672b645  rec3_schema_field_lists.json
3c3eb62e5d1aae63f7cd863236ff9aa96bbd973f81a234239bc8ce62904b68af  rec3_summary_entry_key_lists.json
```

### 14.1 C1 — Trainer R3 pass, `TrainingHistory`, typed contract, Seam 5 — evidence

**Files (staged for the C1 commit).**
`docs/design/genericity_contract.md` (+Seam 5, written BEFORE code) ·
`execute_tools/training_history.py` (NEW, 300 lines: `TrainingHistory`,
`TrainingResults`, `TrainingResultsContractError`,
`interpret_training_results`, `LEGACY_TRAINING_RESULT_KEYS`,
`TRAINING_HISTORY_KEY`, `EPOCH_STATISTIC`, `COMPARABILITY_ESTABLISHED_KINDS`,
`objective_config_fingerprint`, `stamp_comparability`) ·
`execute_tools/train_engine_sandbox.py` (+~400/−8: `TIDMADEpochDataset(file_family=)`,
`ValidationScopeError`, `ObjectiveStateMutationError`,
`_preflight_validation_scope`, `_validation_pass`, `_build_training_history`,
`run_experiment_streaming(eval_sample_set=None)` with ONE sequencing call
per epoch + pre-flight before the loop + ACTUAL subtraction, legacy
`run_experiment` summary + additive key, `main()` `--eval_sample_set_json`
+ `_load_eval_sample_set_arg`) · `tests/helpers/two_family_profile.py`
(NEW, shared two-family contrast fixture) ·
`tests/unit/execute_tools/test_step07a_c1_training_history.py` (NEW, 39
tests) · `tests/unit/execute_tools/test_step07a_c1_validation_pass.py`
(NEW, 22 tests) · this ledger. The eight removed trainer lines are exactly:
the `typing` import, the family-resolved `file_path` line, two comment
lines, three docstring lines and the `record_phase_actual` line — **R2's
computation, seeding, batching, ordering, `drop_last`, step counting,
verification, admission, watchdog, stability stop are byte-untouched.**

**Two-arm oracle vs Checkpoint 0 (post-edit, same harness, two arms):**
`loss_history`, `final_loss`, `model_params`, the legacy JSON string, loader
lengths, model-state sha256 (`fa1ca3a4…6106`), Python-RNG-after and
torch-RNG-after sha256 are ALL identical to §14.0(a) in BOTH arms
(`eval_sample_set=None` and the full 24-row validation set); summary keys
= `[final_loss, loss_history, model_params, training_history]`. R3 with the
eval set: `[2.760…, 2.759414, 2.758428]` on 24 materialized ML segments
(distinct from R2 — the VALIDATION family was read).

**Bounded decisions (§7 policy).**
- The §3.4b pre-flight runs before the epoch loop, i.e. inside the RT2-B
  measured setup window when a session exists (HDF5 metadata only —
  honest setup cost, no dataset construction; RT2-B constructor-count and
  setup pins stay green).
- `validation_samples` records the LAST pass's materialized count (equal to
  the request by the per-epoch equality; the pre-flight's on-disk count
  before any pass).
- `stamp_comparability` precedence: `custom` → `custom_objective_undeclared`
  (regardless of reduction), then `reduction != "mean"` → `reduction=sum`,
  then the audited set → `established`.
- The fingerprint hashes `LossConfig.model_dump(mode="json")` with sorted
  keys and compact separators (stable across processes — pinned by test).

**Tests (all named for their defect; log `07a_c1.log`).**
`tests/unit/execute_tools/test_step07a_c1_training_history.py` — 39 passed
(0.2 s): (j) validators incl. 11 parametrized violations, NaN/inf allowed,
extra key refused; (i) boundary present/absent/expected-missing (both
halves)/schema-invalid/R2-mismatch/final_loss-mismatch/NaN-aware/non-mapping;
(m) stamping for the four built-ins × mean/sum + custom; (n) fingerprint
separates γ=1/γ=4, stable across a subprocess, surface-only; Seam-5 doc
presence. `test_step07a_c1_validation_pass.py` — 22 passed (32.6 s):
(a) two-arm oracle (trajectory + model state + legacy JSON + key order +
R3 ≠ R2 + boundary acceptance); (b) fork mutation — stochastic forward
GREEN with the fork, RED (epoch ≥ 1 diverges, epoch 0 equal) with
`fork_rng` monkeypatched to a no-op; (c) unequal last batch (5 rows,
batch 2 → 2/2/1): R3 == per-sample reference to 1e-12 and ≠ mean-of-batch-
means; (e) child flag fail-closed (missing / list / bad values, path named),
absent → None, `main()` reachability (kwarg arrives on
`run_experiment_streaming`); (f) legacy single-file → history with R3 None,
accepted when not expected; (g) ACTUAL subtraction (passes reporting 100 s
→ raw actual in [−300, −290)), `unit_count` 36 with and without; (h)
validation dataset built only when no training dataset is alive
(events `[training, validation] × 3`); (k) state census equal before/after
each of 3 passes (model, optimizer, criterion, mode, Python/NumPy/torch/CUDA
RNG), objective buffer increment → `ObjectiveStateMutationError`, mode
restored under an exception raised in eval; (l) missing validation file →
`ValidationScopeError` at pre-flight with ZERO epoch datasets built and no
model saved while the TRAINING path still skips the same missing file;
index beyond file; zero rows; index outside topology; disk change after
epoch 0 caught per-epoch ("materialized 16 ML rows"); (m) `reduction="sum"`
through the trainer → `not_established` / `reduction=sum`, R3 still computed.

**Regression sweeps.** `tests/unit/execute_tools` + `tests/unit/core/test_formal_stability.py`:
1118 passed, 1 skipped, rc=0, 79 s (RT2-B, RT2-D, 02a/02b, 05c pins incl.).
RT2-B/RT2-D executor + RT4 watchdog: 46 passed, rc=0, 3 s. `ruff check`
clean; `ruff format --check` clean (127 files). **pyright: NOT runnable on
this host** (`.venv/bin/pyright` needs Node ≥ 14; host Node v10.19 →
`SyntaxError` in the vendored bundle) — pyright is CI's (basic mode,
`tests/` excluded); recorded per CLAUDE.md "Environment assumptions".

**Deviations from the frozen design: NONE.** (Line numbers drifted only by
the additions themselves.)

**Debt entry (Q-07a-1 disposition, §3.9).** The validation pass is NOT
priced by admission / prediction / the watchdog; `validation_seconds` is
persisted per epoch as evidence — **owner: 07c / runtime-control follow-up**.

**C1 commit: `ece67fa0599f8c47cc48a11f2a1c381cbe506064` (`ece67fa0`).**

### 14.2 C2 — Transport (`eval_sample_set` → argv), signature parity, rung B-07a-2 — evidence

**Files.** `agent/skills/training_skill/wrapper.py` (+`eval_sample_set=`
forwarded — the OD-S7-1 drop site closed) · `core/sandbox_executor.py`
(`TidmadSandbox.execute_training(eval_sample_set=None)`: validate by the
SAME rule as the train set → `configs/<run>/eval_sample_set_<exp_id>.json`
compact `json.dump` → `--eval_sample_set_json <path>` immediately after the
`--sample_set_json` pair, ONLY when both sets are given;
`StubSandbox.execute_training(eval_sample_set=None)` accepted + scope-
validated) · `tests/helpers/recording_sandbox.py` (+`training_kwargs`
recorded per call — signature parity already held via `**kwargs`) ·
`tests/helpers/two_family_profile.py` (profile now built via
`model_validate` so it round-trips through the subprocess boundary — the
`model_copy` form only validated in-process; anchor/peek sets re-declared
inside the 3-file index space) · `tests/unit/core/test_step07a_c2_transport.py`
(NEW, 9 tests).

**Deviation (bounded, §7 / Working Rules §15) — pseudo-route PAYLOAD
upgrade moved from C2 to C3.** Previous assumption (§15 C2 scope): Stub /
pseudo JSON gain the multi-epoch train + validation `training_history`
payload in C2. Audit evidence: the tuner forwards RAW `train_results` into
`reflect_results = {**train_results, **score_results}`
(`ml_hyperparameter_tune_agent.py:5865`) until C3 introduces
`legacy_payload`; the WF-2 baseline replays
`tests/pseudo_data/train_outputs/pe_wavenet_delta/execute_training.json`
through `RecordingSandbox`, so a payload added at C2 would flip the WF-2
`actual_results_keys` golden and the PB-2 reflector bytes AT C2 — contradicting
the frozen "each commit leaves the tree green" rule (§15 preamble).
Corrected understanding: the payload upgrade and the hiding are ONE
green-preserving unit. Implementation consequence: C2 delivers transport +
SIGNATURE parity (Stub accepts and scope-validates `eval_sample_set`;
RecordingSandbox records it) + rung B-07a-2; the multi-epoch payload for
StubSandbox / RecordingSandbox pseudo JSONs lands in C3 together with the
tuner-side hiding. Validation consequence: none lost — the C3 acceptance
"every success record in a pseudo run carries `training_history`" covers the
payload; the C2 acceptance "Stub/pseudo yield ≥ 3 epochs of R2 and R3" is
therefore satisfied at C3 (recorded there). Final tree after C3 is identical
to the design's.

**Streaming-argv pins audit.** No existing test lists the FULL streaming
training argv (grep `--sample_set_json` in `tests/unit`: 02b-B1/B3, RT2-B/D,
the 02b live integration and the 05c legacy golden assert by value or pin
the LEGACY list) → nothing to UPGRADE; the new C2 test IS the ordered
streaming golden with the declared pair (`test_streaming_argv_with_an_eval_set_is_the_pre_c2_list_plus_exactly_the_declared_pair`).
The 05c legacy golden `test_c0_training_argv_ordered_golden` is unchanged
and green.

**Note (source audit).** `execute_inference` already writes
`configs/<run>/eval_sample_set_<exp_id>.json` for its own `--sample_set_json`
(`sandbox_executor.py:1735`) — the SAME tuner-owned eval set for the attempt
(`active_params["eval_sample_set"]` feeds both, `:4751` / `:5442`), same
validation rule, same byte form. Training writes it first; the frozen file
name (§3.4) is kept — one eval set per attempt, one file. Recorded in the
executor docstring.

**Tests (`07a_c2.log`).** `test_step07a_c2_transport.py` 9 passed (5.0 s):
ordered streaming argv golden (pre-C2 list + exactly the pair, position
after `--sample_set_json`); no eval set → no flag; legacy + eval set → no
flag; written eval JSON == `json.dumps(validate_sample_set(EVAL_SS))` bytes,
≠ the train file, accepted by the child loader; eval set outside DataScope
→ scope refusal, launch primitive never called; wrapper reachability through
the tuner's `_run_skill` (RecordingSandbox saw the set); **delete-the-hop
half 1**: the pre-07a wrapper re-introduced by monkeypatch → executor saw
`None` and the expecting boundary refuses the result; Stub parity (accepts,
scope-validates); **rung B-07a-2** (`@allow_real_subprocess`, real
`train_engine_sandbox.py` child launched by the production `execute_training`
with the ONE test seam `--data_dir <fixture>` appended to the executor's
argv; CPU): status success, `--eval_sample_set_json` in the launched argv,
R2 and R3 lists of length 2, `validation_requested_samples ==
validation_samples == 8` on a scope DISTINCT from the train set,
`comparability=established`, R3[-1] == the in-process reference over the
VALIDATION family (|Δ| 3e-8, cross-process float32) and ≠ the training-family
reference (|Δ| 1.7e-3) — R3 is observed on the validation family.

**Sweeps.** `tests/unit/core tests/helpers tests/unit/agent/skills`: 2534
passed, 2 skipped, rc=0, 69 s. `tests/unit/agent/tune_ml_hyperparam_agent`
(WF-1/WF-2/PB/REC pins): 1101 passed, rc=0, 243 s. `ruff check` + `ruff
format --check` clean (254 files). pyright → CI (host limitation, §14.1).

**C2 commit: `83987b216dd35d4dbc6132f5221bbdd68729099e` (`83987b21`).**

### 14.3 C3 — Tuner typed boundary, `TrainingDiagnosis`, record attachment, hidden at BOTH renders, goldens — evidence

**Files.** `agent/schemas/training_diagnosis.py` (NEW: `TrainingDiagnosis`,
`derive_training_diagnosis`, `symmetric_relative_change`, `FLAT_REL_TOL=1e-2`)
· `agent/schemas/hyperparam_tuning.py` (`ExperimentRecord.training_history` /
`.training_diagnosis` additive beside the legacy training keys +
`_training_history_agrees_with_the_legacy_keys` validator) ·
`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
(module-level typed boundary `_interpret_training_status(train_status, *,
expected_validation) -> (train_status, TrainingResults)`; `run()` gains
THREE sequencing edits: the boundary call after the admission / rejection
handlers and BEFORE the existing `status == "error"` branch, `train_results
= training_results.legacy_payload` + `training_diagnosis =
derive_training_diagnosis(training_results.history)` at the result-extraction
site, and two record entries — `training_results.history_payload()` /
`training_diagnosis.model_dump()`) · `agent/prompts.py`
(`_PLANNER_HIDDEN_RECORD_KEYS` += the two keys; comment re-worded "07a hides ·
07b renders · 09 interprets") · `execute_tools/training_history.py`
(+`TrainingResults.history_payload()`) · `core/sandbox_executor.py`
(`StubSandbox.execute_training` emits the OD-S7-4 5-epoch train + validation
history and the `training_history` payload — R3 ONLY when an eval set was
supplied, the production rule; objective identity from the validated
`LossConfig(**l_cfg)`) · `tests/pseudo_data/train_outputs/{wavenet,punet,pe_wavenet_delta}/execute_training.json`
(+`training_history` consistent with the EXISTING 5-epoch `loss_history`,
values unchanged; `objective_kind=focal`, fingerprint of the default
`LossConfig` `f90b6486…fc05`) · goldens REGENERATED ADDITIVELY
(`rec2_formal_success_projection.json`, `rec2_oom_skip_projection.json`,
`rec3_summary_entry_key_lists.json`; three-part `_captured_at.note`,
commit = C2 head `83987b21`; the diff replaces ONLY the provenance lines and
adds the two keys — reviewed line by line) · REC-1 inline list `_56 → _58`
(annotated) · `tests/unit/agent/llm_bridge/test_step06_planner_boundary.py`
UPGRADED (both 07a keys on every input record; hidden set pinned at four
keys) · NEW `tests/unit/agent/llm_bridge/test_step07a_reflector_boundary.py`
(3) · NEW `tests/unit/agent/schemas/test_training_diagnosis.py` (26) · NEW
`tests/unit/agent/tune_ml_hyperparam_agent/test_step07a_c3_tuner_boundary.py`
(18) · `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py`
`FAKE_TRAIN_RESULT` UPGRADED (see disposition below).

**Bounded decision — where the contract error is routed (design C3 §2 "audit
at implementation").** `_interpret_training_status` rewrites a
`TrainingResultsContractError` into the EXISTING training-error status shape
(`status="error"`, `error_type="training_results_contract"`, message
`error_training: training results contract violated: …`,
`runtime_verification` preserved) so the orchestrator's pre-existing
`if train_status.get("status") == "error"` branch records it through
`_build_execution_failure_record(phase="training")` → status `error_training`
(`_PHASE_FAILURE_TEXT["training"]["status_ok"]`), evidence attached by
`_emit_record(status=train_status)`. Placement: immediately after training
returns (before inference / scoring) — a contract-violating attempt fails
closed without spending inference or scoring. `run()` gains sequencing calls
only: **AST branch-node count of `HyperparamTuningAgent.run` = 244 at the base
`5f10b7f5` and 244 now** (If/For/While/Try/With/IfExp/BoolOp/comprehension/
Match/ExceptHandler nodes; the record entries use `history_payload()` instead of
a conditional expression precisely to keep this true).

**Test disposition — `FAKE_TRAIN_RESULT` UPGRADE (fixture rot, design §19.3
triage).** After C3, 21 tuner tests in four modules (`test_tuning_agent.py`,
`test_ordering_formal_branch.py`, `test_step02b_tuner_supplies_profile.py`,
`test_step05a_run_bound_profile.py`) went RED: all route training through
`_mock_run_skill` → `FAKE_TRAIN_RESULT`, a pre-07a canned success with NO
`training_history`, replayed on TRIAL-mode attempts that build an eval
SampleSet — the new §3.4a boundary correctly recorded `error_training`
("validation was EXPECTED … no training_history payload"), and the tests'
success-record expectations failed. Classification: test fixture (the fake
producer predates the contract), not production. Fix: the fixture now
honours the trainer→tuner contract as the real trainer does (R2 == a 3-epoch
`loss_history` ending at the existing `final_loss=0.5`, R3 present); the
pre-07a shape is now the explicit SUBJECT of the C3 mutation test, not a
background assumption. Re-run: 95 passed (185 s).

**Tests (`07a_c3.log`, `07a_c3_fix.log`, `07a_c3_pins.log`).**
`test_training_diagnosis.py` 26 passed: symmetric `r` (0,0→0; 0,x→1;
symmetric; scale-free), argmin best epoch + degradation sign + `train_min`
side, no degradation when last is best, degradation inside the deadband not
flagged, gap signed & gated on comparability (within-curve facts stay for
`not_established`), trend on first/last with the deadband on BOTH sides
(`r=1/100` exactly on → flat; 98.9 → decreasing; 101.2 → increasing; both
zero → flat; 0→0.5 → increasing; non-monotone endpoints), truncated,
validation absent, non-finite → `invalid` with counts only, empty →
`invalid`, determinism / purity, `flat_rel_tol` recorded & re-derivable, no
calibrated-label field names, dump round-trip. `test_step07a_c3_tuner_boundary.py`
18 passed (2.3 s): boundary success/expected-missing/legacy-absent/
malformed/pass-through; record attachment (pre-07a unchanged, round-trip,
history≠loss_history, final_loss≠last R2, diagnosis epoch mismatch, ok
diagnosis without history, resume-style mix); LIVE pseudo path — every
success record carries a 5-epoch R2+R3 history and `state="ok"` /
`validation_state="present"` (`best_validation_epoch=4`), skip records
None, the tuner-built eval SampleSet reached the executor on every training
call (`RecordingSandbox.training_kwargs`), records on disk carry both keys;
**delete-the-hop**: `derive_training_diagnosis` monkeypatched at the tuner →
the persisted records carry the sentinel; **§3.4a mutation half 2 (LIVE)**:
`training_history` stripped from the canned results → NO success record,
every trained attempt `error_training` with "contract violated" in
`memory.conclusion`, both fields None. `test_step07a_reflector_boundary.py`
3 passed: `legacy_payload` ⊕ score keys == the WF-2 golden's
`actual_results_keys` (9 keys); reflector user prompt BYTE-IDENTICAL to the
pre-07a render; MUTATION control — the raw results dict changes the bytes.
`test_step06_planner_boundary.py` (UPGRADED) 5 passed. Baseline pins after
regeneration: `test_step00_choreography_baselines.py` (WF-1/WF-2) +
`test_step00_record_baselines.py` (REC-1..4) + `tests/unit/agent/llm_bridge`
(PB-1/PB-2) — green; **PB-1 (3) / PB-2 (2) / WF-1 (2) / WF-2 files
byte-identical to §14.0(d)** (sha256 re-listed at the C3 commit below).

**Sweeps.** `tests/unit/agent tests/unit/nodes tests/unit/core tests/helpers`
(pre-fixture-upgrade run): 6475 passed, 21 failed (the fixture-rot set above),
2 skipped, 289 s → the four modules re-run green (95 passed). Remaining
`tests/unit` dirs (`--ignore agent/nodes/core`): 3126 passed, 1 skipped, 1
failed = `test_pr3_l2p_preflight.py::test_preflight_all_invariants`
(`no_production_file_modified` on the DIRTY working tree — the guard working;
it runs from the clean tree in the terminal full suite). `ruff check` +
`ruff format --check` clean (556 files). pyright → CI.

**Storage-boundary observation (pre-existing, NOT changed).** `save_record`
→ `coerce_nonfinite_to_none` writes non-finite floats as `null`; a diverged
run's persisted `loss_history` (`list[float]`) already could not be reloaded
through `ExperimentRecord` before 07a; `training_history.train_objective`
inherits the same storage image. In memory (the tuner, `run_output_*.json`
before coercion) NaN is evidence and validates. Recorded; owner: outside 07a.

**C3 commit: `ecc5ddf8b7fbc1ee9817e8077177898aabadd75c` (`ecc5ddf8`).**

### 14.4 C4 — Rung B-07a-1, example packs, docs / Checkpoint E — evidence

**Files.** `examples/oxford_iiit_pet/expected/{training_history,training_diagnosis}_l1_fixture.json`
and `examples/davis_future_prediction/expected/{…}` (NEW, JSON only — PR0
`.py` / YAML pins hold; each wrapped in a `_fixture` block labelled
`l1_fixture` with the note "NOT a real training output", the fingerprint
provenance = sha256 of the fixture declaration string, `comparability`
DECLARED by the fixture) · `tests/unit/examples/test_step07a_b1_diagnosis_structure_rung.py`
(NEW, 6 tests: the same boundary over TIDMAD focal (atomic fixture with the
test) / Pets `ce` + `validation_accuracy` / DAVIS `mae` + `validation_psnr` →
hand-computed expected verdicts (best epoch, degradation, gap, trends;
floats to 1e-12), machine-checked atomicity (only `objective_kind` /
fingerprint / values / observation NAME vary), fixture consumption + label,
pack STATUS / README pins) · pack docs: `examples/tidmad/README.md` (+
training-observation row: R1/R2/R3, "production-backed from 07a", no
`resolved/` snapshot) + `STATUS.md` (row landed); `examples/oxford_iiit_pet/`
and `examples/davis_future_prediction/` `README.md` (+`expected/` lines) +
`STATUS.md` ("L1 — fixture-backed … consumed by rung B-07a-1; real R2/R3
after D14") · `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
(record rows `training_history` / `training_diagnosis`; pipeline step 3) ·
`agent/skills/training_skill/training_skill.md` (`eval_sample_set` kwarg,
output payload, stub parity) · governance: parent §8.2 status, README index
row 07a, `docs/README.md` row, roadmap §15.1 `§7a` + §22.12 row 07,
`CLAUDE.md` current state (all "IMPLEMENTED — Gate 2 / PR / CI in the child
§14; merge pending operator review"; the finalizer records the merge SHA
after the operator merges) · this ledger. Operator docs enumerating trainer
flags: audit — `docs/architecture.md` does not enumerate trainer argv (grep
`sample_set_json` → only the design docs, `docs/README.md`, the node and
skill docs above); nothing else to update.

**Tests.** `tests/unit/examples` 67 passed (0.6 s) = 61 PR0 governance /
pack tests + the 6 rung tests — PR0 pins intact with the new `expected/`
JSON. `ruff check .` clean; `ruff format --check .` clean (925 files).

**Terminal non-Gate validation** — recorded below at the final executable
head (full unit suite ONCE from a clean tree; ruff; format; pyright via CI).

**Gate-2 readiness packet (design §10 / Working Rules "before real
training").**
- Property: the production path trainer → executor → tuner emits R2 + R3
  and persists `training_history` + `training_diagnosis` on the real
  run's `run_output_*.json` record (Checkpoint C), under real LLM planning,
  real training, real inference, real scoring — the functional Gate-2 PASS
  criteria (standard `:206-233`) PLUS the 07a boundary evidence.
- What synthetic execution cannot prove: the argv assembled by the REAL
  executor under the REAL tuner's `active_params`, consumed by the REAL
  child on real TIDMAD HDF5, at a real workload (rung B-07a-2 proved the
  component on a synthetic profile; the pseudo path proved the tuner
  wiring with canned results).
- Approval provenance: **the Implementation Working Rules contract of
  2026-08-15 pre-authorizes this ONE bounded Gate 2** (no second approval
  at launch).
- Command: the standard's canonical cold-start command (`:100-121`) with
  the frozen 07a settings — `openai_tiered_pro.json`, DS8 pairing
  (`--data_scope 4-9` + `--health_gate_files 4,5,6,7,8,9`), no
  `--seed_paths`, **`--max_epochs 2`** (upper bound only; a 1-epoch plan
  is still a functional PASS).
- Bounds owned by the harness: `--num_iterations 1 --max_rounds 1
  --max_proposal_attempts 3 --validation_max_portion 0.01
  --validation_max_train_samples 2000 --validation_max_phase_seconds 900
  --runtime_watchdog --trial_vram_budget_gb 24 --formal_vram_budget_gb 24`.
- Expected wall time ~10–20 min; expected cost ~$1–2 (design §11).
- PASS artifact: the workspace's `run_output_*.json` record with
  `training_history.train_objective` (R2 list) + `.validation_objective`
  (R3 list) and `training_diagnosis.state == "ok"`,
  `.validation_state == "present"`; plus the standard's functional criteria.
- Failure classification decided in advance: chain exit ≠ 0 / no
  candidate / training-inference-scoring not executed → functional FAIL
  (standard); record present but boundary fields missing → 07a semantic
  FAIL (blocks; diagnose; no reroll); admission rejection before training
  → inconclusive for the 07a criterion (rerun ONCE only if a harness
  transient — standard rules); LLM proposal failures → LLM-quality issue
  per the standard's partial-scope rules.

**C4 commit: `aee1e362a1983365a2c260b8a67ac2be59916634` (`aee1e362`) — the
FINAL EXECUTABLE HEAD** (every later commit on the branch is ledger /
docs only).

**Terminal non-Gate validation at `aee1e362` (clean tree).**
`.venv/bin/python -m pytest tests/unit -m "not real_run" -q` from the clean
tree → **9605 passed, 3 skipped, 405 warnings, 687.71 s (11:27), rc=0**
(the log's own rc line — incl. `test_pr3_l2p_preflight.py::test_preflight_all_invariants`,
green on the clean tree). `ruff check .` clean; `ruff format --check .`
clean (925 files). pyright: CI (host Node v10, §14.1).

**Gate-2 run (ONE, pre-authorized; standard's canonical cold-start command).**

```text
approval     Implementation Working Rules contract (operator, 2026-08-15) — pre-authorized
head         aee1e362a1983365a2c260b8a67ac2be59916634  (final executable head; clean tree)
command      bash sdsc_submission_scripts/run_chain.sh --mode lilab --workspace /tmp/gate2_07a_1786841866
               --run_name gate2_07a --num_iterations 1 --max_rounds 1 --max_proposal_attempts 3
               --max_epochs 2 --data_scope 4-9 --health_gate_files 4,5,6,7,8,9
               --validation_max_portion 0.01 --validation_max_train_samples 2000
               --validation_max_phase_seconds 900 --runtime_watchdog --no-force_formal_round
               --trial_vram_budget_gb 24 --formal_vram_budget_gb 24
               --llm_config llm_configs/openai_tiered_pro.json          (no --seed_paths; cold start)
workspace    /tmp/gate2_07a_1786841866  (preserved)
wall         2026-08-16T00:57:46Z → 01:11:01Z = 13 min 15 s      chain rc = 0
cost         not metered by the chain; design estimate ~$1–2 (gpt-5.5 tiers, 5 planner rounds + proposer)
host         lilab RTX 5090 shared with three other users' processes (~7 GB / 85 % util at launch)
```

Run: candidate `causal_spectral_wavenet27_hf_coldstart` generated, validated,
registered (real proposer + implementor + validator). ROUND 1 = 4 training
attempts (`iter_001_001..004`), all through the REAL executor argv carrying
`--eval_sample_set_json` (`configs/iter_001/eval_sample_set_*.json` written,
12 PSD segments over files 4–9 = 15 000 ML rows at `segmentation_size 8000`;
train set 12 PSD segments, epoch capped at 2 000 rows):

| attempt | plan | training | outcome |
|---|---|---|---|
| 001 | 2 epochs, bs 4 (500 steps/epoch, verified 62 ms/step) | epoch 0 done (~31 s), validation pass started | **watchdog kill at 64.07 s (deadline 63.97 s, source=verified_components)** → `error` record |
| 002 | 1 epoch, bs 4 | epoch 0 done, validation pass started | watchdog kill at 60.07 s (deadline 60.0 s = floor) → `error` |
| 003 | 1 epoch, bs 8 | same | watchdog kill at 60.07 s → `error` |
| 004 | 1 epoch, bs 16, NARROWER model, CE-only | epoch 0 (125 steps ≈ 9 s) + **validation pass 26.45 s over 15 000 rows** → completed | real inference (32.2 s) → real scoring (12.5 s) → HealthGates fired (output_diversity / output_std / amplitude_collapse) → `failed_mode_collapse`, `gate_action=invalidate_round`, `denoising_score=None`, `metric_result.scalar=None` (raw non-finite), phantom `5.5762667` NAMED by the gate as blocked, never accepted |

**07a boundary evidence (PASS artifact) — `run_output_iter_001.json` record `iter_001_004`:**

```json
"training_history": {"objective_kind": "ce", "objective_reduction": "mean", "comparability": "established",
                     "epochs_planned": 1, "epochs_completed": 1,
                     "train_objective": [2.855780694961548], "validation_objective": [4.452557017008464],
                     "validation_requested_samples": 15000, "validation_samples": 15000,
                     "validation_seconds": [26.452381853945553], "observations": {}}
"training_diagnosis": {"state": "ok", "validation_state": "present", "comparability": "established",
                       "best_validation_epoch": 0, "train_trend": "single_point", "validation_trend": "single_point",
                       "train_validation_gap_final": 1.5967763220469156, ...}
"final_loss": 2.855780694961548   (== train_objective[-1])       "timing": {"train_time_s": 38.9, ...}
```

The three `error` records (watchdog kills) carry `training_history: null` /
`training_diagnosis: null` — attempts that produced no results, exactly as
designed. R2/R3 are ONE point each because the planner elected 1 epoch after
the 2-epoch kill (`--max_epochs 2` is an upper bound; Q-07a-4 disposition:
a one-point history is a legitimate functional PASS). The pseudo/stub path
was NOT involved: the child that wrote this history is the real
`train_engine_sandbox.py` on real TIDMAD HDF5, launched by the real
`TidmadSandbox.execute_training` under the real tuner.

**Verdict against the standard's PASS criteria (`:206-233`) + item 9:**
1 chain exit 0 ✓ · 2 real candidate generated / validated / registered ✓ ·
3 real training executed ✓ (`train_time_s 38.9`, model + `_OK_` sentinel) ·
4 real inference ✓ (32.2 s) · 5/7 scoring executed (12.5 s); the scalar is
`None` WITH `gate_action=invalidate_round` in the round's record — the
standard's explicit carve-out (criterion 7; "a model may be collapsed or
scientifically worthless while the functional Gate correctly proves the
real path executed") ✓ · 6 the round's final record carries `gate_action` ✓
· 8 no phantom `5.5762667` accepted (the HealthGate BLOCKED it) ✓ · 9 the
07a boundary evidence present with `state="ok"`,
`validation_state="present"` ✓. **GATE 2: PASS (functional + 07a boundary
evidence).** Not rerolled; the workspace is preserved.

**MATERIAL FINDING (recorded honestly; surfaced to the operator at review).**
Three of the four attempts were killed by the RT4 watchdog **inside the
un-priced validation pass**. Mechanism (from the sidecars + the child logs):
the watchdog's `verified_components` deadline for the training phase is the
verified prediction (optimizer steps × measured unit ms + reconstruction
terms; floor 60 s) — 07a's validation pass sits INSIDE that phase window and
is, by the frozen design (§3.9, Q-07a-1), NOT priced by admission /
prediction / the watchdog. Under the Gate envelope the asymmetry is large:
`validation_max_train_samples 2000` caps the TRAINING epoch (2 000 rows) but
NOT the validation scope (the eval SampleSet: 12 PSD × 1 250 = 15 000 rows),
so validation work was 7.5× the epoch's forward work; the wide candidate's
pass exceeded the ~30 s slack and was killed on every attempt; the narrow
candidate's pass (26.5 s) fit under the 60 s floor. **This is the
un-priced-validation debt (07c / runtime-control) manifesting as watchdog
kills — not a 07a semantic defect** (retry / round / timeout / signal /
admission / verification / watchdog CODE and semantics are untouched; the
validation pass is transactional and exact-scope; the boundary evidence is
correct), **but it is a real operational consequence for any
`--runtime_watchdog`-enabled run whose eval SampleSet is large relative to
the per-epoch training work.** Two design premises corrected:

```text
Previous assumption (§3.2/§3.9): "bounded by the tuner's already-bounded eval SampleSet …
  under train_validation_align the eval set is the same size" as the epoch's train set.
Audit evidence: eval_sample_set = eval_portion of the SCOPE (== the train SampleSet under align);
  the per-epoch TRAINING set = train_portion × that scope, further capped by
  validation_max_train_samples (training only). Validation rows / epoch-training rows =
  1 / train_portion (10× at the formal default 0.1; 7.5× under the Gate envelope).
Corrected understanding: the pass IS bounded (by the eval set) but its wall time is
  comparable to or larger than the training epoch's, and the watchdog prices only the latter.
Implementation consequence (07a): NONE within frozen scope — pricing validation into
  admission / prediction / the watchdog deadline changes runtime-control semantics
  (forbidden here; a §13 stop if attempted); capping the validation scope would violate
  §3.4b (exact materialization). `validation_seconds` is persisted per epoch precisely so
  07c can price it from evidence.
Validation consequence: Gate 2 still PASSED functionally (attempt 4); the kills are recorded
  as `error` records with `error_type`-less watchdog messages, exactly the pre-07a shape.
Operator decision surfaced (NOT taken here): whether watchdog-enabled campaigns may run on
  07a before 07c prices validation, and whether the Gate envelope should ALSO bound the
  validation scope (`validation_max_train_samples`-style) — both outside 07a's frozen scope.
```

**Why the readiness audit missed it (Working Rules "when an expensive run
exposes something an audit could have caught").** The audit priced the pass
as "bounded by the eval set" and checked that admission / verification /
watchdog CODE was untouched; it did not compute the validation-to-training
work RATIO under the Gate envelope, nor trace that the watchdog deadline is
the verified TRAINING prediction while the pass runs inside the same window.
Strengthening the audit: every future PR that adds wall time inside a
watchdog-monitored phase must state the ratio of the added work to the
priced work under the canonical Gate envelope BEFORE the Gate.

**Closeout.** Final PR HEAD `889f7cfa` (ledger, docs only) → PR #215
(https://github.com/Galileo-Sandbox/SIDERIUS/pull/215) → exact-head CI run
**31919470205 SUCCESS**. **Operator verdict (2026-08-16): APPROVE
IMPLEMENTATION WITH DOC-ONLY CLOSEOUT BEFORE MERGE** — no production
change, no Gate-2 rerun, no watchdog change; the watchdog finding stays a
high-priority 07c debt ("07a merge blocker: NO; broad watchdog-enabled
campaign blocker before 07c: YES"). This closeout commit clears the three
stale status statements the operator named (header "NOT started / ledger
empty", the C4 checklist boxes, §16 "remaining: freeze"); the merge SHA is
the finalizer's.

**Operator analysis and decision (2026-08-16).** The operator confirmed the
diagnosis and sharpened it: this is *not* estimation noise — the runtime
model's prediction OBJECT is defined too narrowly (training only) while the
watchdog uses it to bound a wider execution scope (training + validation);
07a's exclusion of `validation_seconds` from the training ACTUAL is correct
(the per-step cost model stays pure), the missing term is one layer up in
the phase deadline. Consequence if unfixed: a model-size-dependent bias
(larger candidates die in validation, smaller ones survive → the tuner
learns a false regularity). Fix owner: **07c** — `T_deadline = T̂_train +
T̂_val + T_overhead + margin` with `T̂_val` calibrated from the
`validation_seconds` / `validation_samples` 07a persists (first point:
15 000 rows → 26.45 s); interim Gate/campaign bounding via a
validation-scope ceiling paired with `validation_max_train_samples` (cost
bounding, not the root fix). Recorded as ADDED 07c scope in the parent §8.4.
**Operator verdict: 07a merge blocker NO; broad `--runtime_watchdog`
campaign before 07c: NOT reliable. Merge of PR #215 AUTHORIZED by the
operator (2026-08-16, in their own words) after the doc-only closeout.**

**MERGE (finalizer).** MERGED — PR #215, squash `65804b3d83d67eac5e8821f012bfb2f9f1fbffec` (`65804b3d`), 2026-08-16; final PR head `752f8f0e`, exact-head CI 31927638592 SUCCESS; parity `git diff 752f8f0e 65804b3d` empty. Doc-only closeout commits `2b664ac5` (stale status bookkeeping) and `752f8f0e` (operator analysis + parent §8.4 ADDED 07c scope) preceded the merge; executable head `aee1e362` unchanged since the terminal validation and Gate 2. 07a COMPLETE; next = 07b (fresh Implementation Working Rules contract; Gate 1 required there); 07c carries the validation-pricing requirement.

**Debt entries.** (1) 07c / runtime-control: price the validation pass into
prediction / admission / the watchdog deadline from `validation_seconds`
evidence (existing §3.9 debt, now with a measured instance: 26.45 s for
15 000 rows vs a 9 s epoch); (2) Gate standard / harness: consider a
validation-scope ceiling paired with `validation_max_train_samples` (owner:
runtime-control design / Gate standard, NOT 07a); (3) roadmap §14
convergence ledger row added (Seam 5 + this pricing gap).

**Four commits.** C1 trainer + schema + Seam 5 (+ trajectory oracle,
comparability) · C2 transport + test-infra parity (+ B-07a-2) · C3 tuner
boundary + diagnosis + record + hiding (+ goldens) · C4 rungs + packs +
docs / Checkpoint E (+ Gate 2 with approval). Each leaves the tree green
and independently reviewable.

Before every commit: stop and show the exact diff summary, staged file list,
tests run (counts / wall time from the log, never a wrapper's exit code) and
any deviation from this design — unless an Implementation Working Rules
contract overrides the interactive cadence (as PR0's did), in which case the
same evidence is recorded in §14 before each autonomous commit.

---

### C1 — Trainer: R3 validation pass, `TrainingHistory`, typed results contract, Seam 5

**1. Goal.**
Make the production trainer emit R3 beside R2 as a typed additive payload
without perturbing the training trajectory or the three legacy keys, with
the R2/R3 comparability representation fixed and the RT accounting rule
applied — the physical capability everything else consumes.
*Why this commit and not another*: it is the only commit that changes real
training execution; isolating it lets the two-arm oracle and the RT
semantics be proved on the trainer alone before any transport or tuner
change can confound them; Seam 5 is written first because the contract doc
rule says so.

**2. Scope.**
- Docs first: `docs/design/genericity_contract.md` **Seam 5 — Training
  observation** (History / Diagnosis: what is generic, what is TIDMAD-shaped
  today, the contract test that will pin it, owner Step 07a → 07b/09).
- NEW `execute_tools/training_history.py` (§3.5): `TrainingHistory`,
  `TrainingResults`, `TrainingResultsContractError`,
  `interpret_training_results`, `LEGACY_TRAINING_RESULT_KEYS`, reduction id.
- `execute_tools/train_engine_sandbox.py`: `TIDMADEpochDataset(file_family:
  Literal["training","validation"]="training")` (accessor chosen by family;
  default parity); `run_experiment_streaming(eval_sample_set: dict | None =
  None)` — the §3.2 pass after `del dataset, loader` and after the mid-epoch
  rejection return; R3 accumulation (§3.3); `validation_seconds`; summary
  gains `training_history`; training ACTUAL subtracts validation seconds
  (§3.9); `main()` gains `--eval_sample_set_json` (fail-closed load, §3.4)
  and forwards it. Legacy `run_experiment` unchanged except that its summary
  ALSO gains `training_history` with `validation_objective=None`
  (`validation_state` absent — honest).
- Non-goals: no wrapper/executor change (C2); no tuner change (C3); no
  change to R2's computation, seeding, batching, ordering, `drop_last`,
  step counting, verification, admission, watchdog, stability stop; the
  results JSON keeps `indent=4` and the legacy keys first.
- Dependencies: none (PR0 merged).

**3. Implementation plan.**
- [x] Re-read `train_engine_sandbox.py:289-448, 782-1235, 1243-1489`,
      `dataset_config.py:120-145`, `observation_store.py:160-176`,
      `session.py:711-718` immediately before editing (line drift check).
- [x] Checkpoint 0 capture BEFORE the first production edit (recorded in
      §14): fixed-seed streaming trajectory on the in-process synthetic
      3-file fixture (CPU, `torch.manual_seed`, `train_base_seed`, 3 epochs,
      tiny wavenet) — the values, the loader `len`, the results JSON keys;
      REC-3 field lists (unchanged in C1); WF-1/WF-2/PB-1/PB-2 sha256s.
- [x] Write Seam 5 in `genericity_contract.md`.
- [x] Implement `execute_tools/training_history.py` (§3.5) with docstrings
      naming the frozen semantics.
- [x] Implement the trainer changes (§3.2, §3.3, §3.4 child side, §3.9);
      keep the pass in ONE helper (`_validation_pass(...)` returning
      `(r3_value, n_samples, seconds)`) — the streaming loop gains a
      sequencing call, not a block; the pass is transactional (§3.2:
      `try/finally` mode restore, Python/NumPy RNG restore, `fork_rng`,
      criterion state check); the §3.4b pre-flight runs once before
      epoch 0 and the per-epoch materialization equality inside the pass;
      `ValidationScopeError` / `ObjectiveStateMutationError` are typed
      trainer errors (non-zero exit).
- [x] Compute `objective_config_fingerprint` (deterministic SHA-256 of the
      canonical serialized resolved `LossConfig`), `objective_reduction`, `comparability` +
      reason from the §3.3 audited set (a module-level frozenset of the
      built-in kinds proven mean-normalized; custom → not_established).
- [x] Tests (each named for its defect): (a) two-arm trajectory oracle
      (`eval_sample_set=None` vs a distinct validation set) → `loss_history`
      lists equal element-wise (`==` on floats) AND the model state dicts
      equal after training; (b) RNG-isolation mutation: monkeypatch a fixture
      model whose forward calls `torch.rand` → WITH the fork the oracle
      stays green; with the fork removed (test-local monkeypatch of the
      helper) → RED — proves the isolation is the mechanism; (c) R2/R3
      comparability: validation set of 5 ML segments with `batch_size=2` →
      R3 equals the sample-weighted per-sample reference to 1e-12 and does
      NOT equal the unweighted mean of batch means; (d) legacy keys
      byte-identical: the summary's three keys and their JSON serialization
      equal the pre-change form (Checkpoint 0 capture); the additive key is
      last; (e) `--eval_sample_set_json` fail-closed (missing / non-mapping
      → `ValueError` naming the path) and absent → `validation_objective is
      None`; (f) legacy single-file → history with R3 `None`; (g) RT
      accounting: with a session, the recorded training `actual_seconds` <
      total loop wall time by ≥ the recorded `validation_seconds` sum
      (assert equality within tolerance via monkeypatched `perf_counter`),
      verification `unit_count` unchanged vs Checkpoint 0; (h) memory
      order: the validation dataset is constructed only after the training
      dataset of that epoch is deleted (instrumented constructor + `del`
      order via a recording subclass); (i) `interpret_training_results`:
      present / absent / malformed / mismatched cases AND the
      `expected_validation` axis (expected + R3 missing → RED, §3.4a;
      not expected + missing → `absent`); (j) `TrainingHistory` validators
      (length agreement incl. `observations[*]` and `validation_seconds`;
      seconds ≥ 0; `validation_samples == validation_requested_samples > 0`;
      non-finite values allowed); (k) **state census**: model `state_dict`,
      optimizer `state_dict`, criterion `state_dict`, `random.getstate()`,
      `np.random.get_state()`, torch CPU (and CUDA when available) RNG state
      identical before/after each pass; a fixture criterion whose `forward`
      increments a buffer → `ObjectiveStateMutationError`; a fixture model
      that leaves `eval()` mode raised inside the pass → the `finally`
      restores `training=True` (mode restore under exception); (l)
      **materialization contract**: eval SampleSet requesting 5 validation
      segments with one file missing (4 materialize) → `ValidationScopeError`
      BEFORE epoch 0 (no optimizer step ran, no results JSON); an index
      beyond the file's segments → same; `Σ n_i = 0` → same; the TRAINING
      path with the same missing file still skips (legacy semantics
      unchanged — asserted side by side); (m) **comparability stamping**:
      `reduction="sum"` fixture → `comparability="not_established"`,
      `reason="reduction=sum"`; a custom-loss fixture → `"custom_objective_undeclared"`;
      each built-in mean-reduced kind → `"established"`; (n)
      `objective_config_fingerprint` differs between `focal(γ=1)` and `focal(γ=4)`
      and is stable across processes (a configuration-surface fingerprint —
      the test does NOT claim it identifies plugin code).

**4. Validation plan.**
- Unit: the families above (`tests/unit/execute_tools/test_step07a_c1_*`).
- Pseudo/integration: RT2-B/RT2-D/RT4/C2 existing suites green (unchanged
  semantics).
- Negative: (b), (e), (i), (k), (l), (m) above; a validation set that
  violates the profile (`file_index ≥ num_files`) → `ValidationScopeError`
  at pre-flight (the validation contract is strict; the training path's
  legacy behaviour is unchanged and asserted side by side).
- Backward-compat: (d), (f); every existing trainer test green.
- Gates: none at C1 (real training changes are Gate-2'd once, after C4).

**5. Acceptance criteria.**
- The two-arm oracle passes bit-identically for 3 epochs on the fixture
  (values recorded in §14 equal the Checkpoint-0 capture); the fork
  mutation is RED without the fork and GREEN with it.
- `json.dumps` of the three legacy keys is unchanged versus Checkpoint 0;
  the results JSON has exactly one additional top-level key
  `training_history` that validates through `TrainingHistory`.
- R3 on the unequal-last-batch fixture equals the per-sample reference and
  differs from mean-of-batch-means; `comparability` is stamped exactly per
  the §3.3 table (established for the four built-in mean-reduced kinds;
  not_established with the right reason for `sum` and custom).
- The state census (k) is equal before/after every pass; the objective
  state mutation and mode-restore-under-exception cases behave as §3.2.
- Zero / partial validation materialization fails closed BEFORE epoch 0
  with no results JSON; NO `nan` R3 is ever produced for a missing scope.
- Trainer argv accepts `--eval_sample_set_json` (child side); flag absent →
  behaviour identical to today except the additive key.
- Training ACTUAL excludes validation seconds; `unit_count` unchanged.
- ruff + pyright (CI) clean; Seam 5 present in the contract doc.

**6. Failure and edge cases.**
- Eval SampleSet with a validation file missing on disk, an index out of
  range, or ZERO rows → `ValidationScopeError` at pre-flight (before any
  optimizer step) — a validation execution failure, never a shrunk or `nan`
  R3 (§3.4b). The TRAINING path keeps its legacy skip (`:369-371`).
- Non-finite training / validation loss (divergence, non-finite criterion)
  → R2/R3 carry the value; no exception — `NaN` is numerical evidence only.
- The disk changes mid-run (a validation file disappears after pre-flight)
  → the per-epoch materialization equality raises `ValidationScopeError`.
- A custom criterion mutating its state under validation →
  `ObjectiveStateMutationError` (fail closed).
- Stability stop / mid-epoch rejection: validation runs after a COMPLETED
  epoch only; a rejected attempt returns `None` before any pass.
- `epochs=1`: one R3 point.
- Very large eval sets: bounded upstream; the pass is `no_grad`; the
  transient rebuild keeps peak memory at `max`, not sum.

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/execute_tools -q > /tmp/07a_c1.log 2>&1; rc=$?; tail -20 /tmp/07a_c1.log`
- `.venv/bin/python -m pytest tests/unit/execute_tools/test_rt2b_streaming_preamble.py tests/unit/execute_tools/test_rt2d_inference_verification.py tests/unit/core/test_formal_stability.py -q`
- `.venv/bin/ruff check execute_tools tests/unit/execute_tools && .venv/bin/ruff format --check execute_tools tests/unit/execute_tools`; pyright on CI (host limitation recorded).
- Evidence in §14: Checkpoint-0 values, counts, wall time, rc.

**8. Commit boundary.** One module + one new module + one doc + tests; no
transport, no tuner, no golden regeneration; stop and show (or record per
the Working Rules override).

---

### C2 — Transport (`eval_sample_set` → argv) + test-infra parity + rung B-07a-2

**1. Goal.**
Deliver the EXISTING eval SampleSet to the trainer through the production
path (wrapper → executor → argv), declare the ONE argv delta, and give
every pseudo route a multi-epoch train + validation history so the tuner
work in C3 and 07b's Gate 1 have realistic inputs.
*Why this commit and not another*: it is the only commit that changes the
executor's launch surface (argv parity is its own failure class); the
Stub/pseudo upgrade rides with it because it is the same "what reaches the
consumer" concern on the pseudo side (OD-S7-4).

**2. Scope.**
- `agent/skills/training_skill/wrapper.py`: forward `eval_sample_set`.
- `core/sandbox_executor.py::execute_training(eval_sample_set: dict | None =
  None)`: validate → write `eval_sample_set_{exp_id}.json` → append the pair
  after `--sample_set_json` (§3.4); docstring names the delta.
- `StubSandbox.execute_training`: accept `eval_sample_set` (validate scope);
  emit the §3.10 histories + `training_history` payload.
- `tests/helpers/recording_sandbox.py`: accept `eval_sample_set`;
  `tests/pseudo_data/train_outputs/*/execute_training.json`: `training_history`
  added, existing values unchanged.
- Tests: argv delta (executor emits the pair iff sample set AND eval set;
  legacy path emits nothing — 05c legacy golden unchanged); streaming argv
  pins UPGRADED with the declared pair (docstring names the delta and this
  design); wrapper forwards the kwarg (reachability: a wrapper that drops it
  → executor sees `None` → test RED); Stub/pseudo history shape; rung
  B-07a-2 (real trainer through `execute_training` un-mocked on CPU with a
  synthetic 3-file contrast profile: R2 + R3 present, R3 evaluated over the
  validation family — asserted via the file names opened / the recorded
  `validation_samples`); **expected-validation reachability (§3.4a,
  half 1)**: through `RecordingSandbox`/`StubSandbox`, a run whose eval
  set is dropped between wrapper and executor yields a training result
  WITHOUT R3 — the C2 test asserts the executor received `None` (RED if the
  wrapper forwards) and the C3 test asserts the tuner then records
  `error_training` (the two halves of the delete-the-hop mutation).
- Non-goals: no tuner change; no record change; no golden other than the
  argv pins; the byte form of the sample-set JSON unchanged.
- Dependencies: C1.

**3. Implementation plan.**
- [x] Re-read `wrapper.py`, `sandbox_executor.py:1268-1430, 2062-2180`,
      `recording_sandbox.py`, the streaming-argv pins (grep
      `--train_base_seed` / `--sample_set_json` in `tests/unit`).
- [x] Implement wrapper + executor + Stub (signature parity + scope validation);
      RecordingSandbox records the kwargs. *(Pseudo-data / Stub PAYLOAD
      upgrade moved to C3 — bounded deviation, §14.2: it would flip WF-2/PB-2
      before C3 hides the keys.)*
- [x] Tests as listed; no full-list streaming argv pin existed to upgrade (§14.2) — the C2 test is the ordered streaming golden.
- [x] Rung B-07a-2.

**4. Validation plan.**
- Unit: `tests/unit/core/test_step07a_c2_*`, upgraded pins, `tests/helpers/test_recording_fakes.py`.
- Pseudo: the existing pseudo-mode tuner tests green (they now see multi-epoch histories; the record does not yet carry them — C3).
- Negative: eval set violating DataScope → the executor's existing scope-violation result; eval set given without a sample set → flag NOT emitted (legacy path has no validation scope).
- Backward-compat: 05c legacy argv golden byte-identical; sample-set JSON bytes pinned by `test_step02b_b3_boundary_byte_parity.py` unchanged.
- Gates: none at C2.

**5. Acceptance criteria.**
- `execute_training` argv == the pre-C2 list PLUS exactly `["--eval_sample_set_json", <configs/<run>/eval_sample_set_<exp_id>.json>]` immediately after the `--sample_set_json` pair, only in streaming mode with an eval set; the legacy golden test unchanged and green.
- The written eval JSON is `validate_sample_set`-clean and byte-formed like the train set's.
- StubSandbox and the pseudo JSONs yield `interpret_training_results(...).history` with ≥ 3 epochs of R2 and R3.
- Rung B-07a-2 green: R2 and R3 lists present, R3 over the validation family.

**6. Failure and edge cases.**
- Executor: eval set present but train set absent → no flag (documented).
- Stale `eval_sample_set_<exp_id>.json` from a previous attempt → overwritten (same as the train set file).
- Stub under `data_scope`: validated like production.

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/core tests/unit/agent/skills tests/helpers -q > /tmp/07a_c2.log 2>&1; rc=$?; tail -20 /tmp/07a_c2.log`
- ruff / format; pyright on CI. Evidence in §14.

**8. Commit boundary.** transport + test infra + one rung; no tuner logic; stop and show / record.

---

### C3 — Tuner: typed boundary, `TrainingDiagnosis`, record attachment, hidden at both renders, goldens

**1. Goal.**
Consume the typed training results at the tuner, derive the diagnosis once,
persist both on the record, and keep the planner window and the reflector
dump byte-identical — the "persisted, hidden" state the parent freezes for
07a.
*Why this commit and not another*: it is the only commit touching the
tuner, the record schema, the prompt filter and the record goldens; its
failure classes (LLM-visible bytes, record shape) are distinct from C1/C2's
(execution, argv).

**2. Scope.**
- NEW `agent/schemas/training_diagnosis.py` (§3.6).
- `agent/schemas/hyperparam_tuning.py`: `ExperimentRecord` + two fields +
  validator (§3.8).
- `ml_hyperparameter_tune_agent.py`: at `:5619` `results =
  interpret_training_results(train_status.get("results", {}),
  expected_validation=eval_sample_set is not None)` (§3.4a — the tuner is
  where the expectation is known);
  `train_results = results.legacy_payload`; `diagnosis =
  derive_training_diagnosis(results.history)`; the record dict gains
  `"training_history": ..., "training_diagnosis": ...` beside the three
  keys — sequencing calls only; the `TrainingResultsContractError` is
  routed through the EXISTING training-failure record path (audit at
  implementation which helper — `_build_execution_failure_record` `:160` or
  the scoring-failure precedent — carries `error_training`; record the
  choice in §14).
- `agent/prompts.py`: hidden set += the two keys; comment `:873-885`
  re-worded ("07a hides · 07b renders · 09 interprets" — parent §15 item 3).
- Goldens: REC-2 projections + REC-3 field lists / manifest key sets /
  summary entry key lists REGENERATED ADDITIVELY in this commit with the
  three-part `_captured_at.note` (Step-00 §17 rule 3; Step-06 precedent);
  PB-1/PB-2/WF-1/WF-2 UNCHANGED (asserted by sha256 in the test log).
- Tests: diagnosis rules (each rule mutated → RED: argmin, degradation,
  gap, trends incl. deadband boundary, truncated, absent, invalid,
  determinism pin, single-point); record attachment + validator negatives
  (history ≠ loss_history; final_loss ≠ last R2; diagnosis/epochs mismatch);
  hidden-key filter: UPGRADED planner-boundary test (both keys, verbatim +
  condensed) + NEW reflector-boundary test (recorded `actual_results` keys
  == WF-2 golden; rendered user prompt byte-identical with/without history);
  delete-the-hop reachability: a tuner run through `RecordingSandbox` whose
  saved record LACKS `training_diagnosis` when the derivation call is
  monkeypatched away → RED; contract-error routing → an `error_training`
  record; **expected-validation mutation (§3.4a, half 2)**: a canned
  training result WITHOUT `validation_objective` on an attempt that built an
  `eval_sample_set` → `error_training` record, NEVER a success record with
  `validation_state="absent"`; the same result on a legacy attempt (no eval
  set) → success record with `validation_state="absent"`; diagnosis
  cross-curve fields `None` when `comparability="not_established"`; the
  symmetric relative change: `r(0,0)=0`, `r(0,x)=1`, `r(a,b)=r(b,a)`, the
  deadband boundary on both sides of `FLAT_REL_TOL`.
- Non-goals: no policy reads the diagnosis; no rendering; no change to the
  same-loss rank; `HyperparamTuningOutput` untouched.
- Dependencies: C1, C2.

**3. Implementation plan.**
- [x] Re-read `ml_hyperparameter_tune_agent.py:5600-5640, 5740-5770, 5855-5910`, `prompts.py:850-930, 1304-1389`, `hyperparam_tuning.py:360-380, 620-700`, `test_step00_record_baselines.py`, `test_step06_planner_boundary.py`.
- [x] Implement the diagnosis module (pure) + tests first (TDD on the rules).
- [x] Record fields + validator; boundary + diagnosis calls in the tuner (sequencing only; pyright complexity of `run()` must not move — verify no new branch).
- [x] Hidden set + comment; boundary tests.
- [x] Regenerate REC-2/REC-3 additively (same commit; three-part note); assert PB/WF sha256 unchanged.

**4. Validation plan.**
- Unit: `tests/unit/agent/schemas/test_training_diagnosis.py`, `tests/unit/agent/tune_ml_hyperparam_agent/test_step07a_c3_*`, upgraded boundary tests, record baselines.
- Pseudo: dual-mode tuner integration tests green with records now carrying both fields (`RecordingSandbox` replay).
- Negative: validator negatives; malformed payload → `error_training` record; a hidden key leaking → RED.
- Backward-compat: pre-07a records (no fields) validate unchanged; REC-2 pre-existing keys/values unchanged (the note states so, as Step 06 did).
- Gates: none at C3 (bytes exact).

**5. Acceptance criteria.**
- PB-1 (3), PB-2 (2), WF-1, WF-2 golden files byte-identical to their pre-07a sha256s (recorded in §14).
- The reflect call's `actual_results` key set == the WF-2 golden on a run whose train results carry `training_history`.
- Every success record in a pseudo run carries `training_history` (R2 + R3 lists) and `training_diagnosis` with `state="ok"`, `validation_state="present"`; failure/skip records carry `None`.
- An attempt that expected validation but received none is an `error_training` record (mutation RED); a legacy attempt records `validation_state="absent"` on a success record.
- Each diagnosis rule has a RED mutation recorded; determinism pin green.
- `run()`'s pyright complexity unchanged (no new branch — CI pyright green; a local AST branch count recorded in §14).

**6. Failure and edge cases.**
- Legacy child JSON without the payload → `absent` (never an error).
- Records loaded from disk before 07a → both fields `None`; validator inert.
- Collapse (`failed_mode_collapse`) records → fields attached exactly as on success (the diagnosis is training evidence, independent of the gate verdict).
- Resume: `core/resume.py` reloads records through `ExperimentRecord` — additive fields round-trip; a resumed pre-07a run mixes records with and without them (both valid).

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/agent tests/unit/nodes -q > /tmp/07a_c3.log 2>&1; rc=$?; tail -20 /tmp/07a_c3.log`
- `sha256sum tests/unit/agent/llm_bridge/goldens/* tests/unit/agent/tune_ml_hyperparam_agent/goldens/wf*` before/after (recorded).
- ruff / format; pyright on CI. Evidence in §14.

**8. Commit boundary.** tuner + schema + prompts filter + goldens; no execution change; stop and show / record.

---

### C4 — Rung B-07a-1, example packs, docs / Checkpoint E, Gate 2 (with approval)

**1. Goal.**
Prove the diagnosis boundary is task-generic over the three frozen
semantics (L1 rung), advance the three example packs honestly, synchronize
the governance surfaces, run the terminal validation, and — with operator
approval — the one bounded Gate 2 that instantiates Checkpoint C.
*Why this commit and not another*: rung B-07a-1 and the packs are
consumers of the finished boundary; the docs sync is Checkpoint E.

**2. Scope.**
- Fixtures: `examples/oxford_iiit_pet/expected/{training_history_l1_fixture,training_diagnosis_l1_fixture}.json`,
  `examples/davis_future_prediction/expected/...` (JSON, `l1_fixture`
  labelled; PR0 pins hold: no `.py`, no top-level task_description YAML);
  the TIDMAD fixture (focal, representative) lives with the test (TIDMAD's
  history is production-backed, not fixture-backed).
- `tests/unit/examples/test_step07a_b1_diagnosis_structure_rung.py`
  (loads the pack fixtures; atomicity diff; expected verdicts as literals);
  pack STATUS/README string pins (R1/R2/R3 rows present; "production-backed
  from 07a" for TIDMAD; "L1 fixture-backed" for Pets/DAVIS).
- Pack docs (§3.11); `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
  (record fields), `agent/skills/training_skill/training_skill.md`
  (`eval_sample_set`), operator docs that list trainer flags (audit at
  implementation: `docs/architecture.md` mentions the trainer — verify
  whether flags are enumerated there).
- Docs: this child's header + §14; parent §0 status + §8.2 "landed"; README
  index row 07a; `docs/README.md` row; roadmap §15.1 `§7a` row + §22.12
  row 07 ("07a landed …", merge SHA by the finalizer).
- Terminal validation: full unit suite ONCE at the final executable head
  from a clean tree; ruff / format repo-wide; exact-head CI.
- **Gate 2** (§10) — readiness packet in §14 (property, command, bounds,
  expected wall time, PASS artifact = the record fields in
  `run_output_*.json`), operator approval, launch, result recorded.
- Non-goals: no production code beyond doc-string touch-ups; no new golden.
- Dependencies: C1–C3.

**3. Implementation plan.**
- [x] Author the three L1 fixture histories with the EXACT §22.9a semantics (`objective_kind` values `ce` / `mae`; observations `validation_accuracy` / `validation_psnr`; the TIDMAD atomic fixture `focal`) and their expected diagnoses (literals).
- [x] Rung test + pack pins; pack docs; node/skill docs.
- [x] Docs sync; ledger §14 (counts / wall time / rc per commit; PB/WF sha256s; Checkpoint-0 values).
- [x] Full suite from a clean tree (9605 passed / 3 skipped / rc=0 at `aee1e362`); push; PR #215; exact-head CI 31919470205 SUCCESS on `889f7cfa` (id in the PR body — §14.4).
- [x] Gate-2 readiness packet → pre-authorized by the Implementation Working Rules contract → launched at `aee1e362` → recorded (PASS, 13 min 15 s, cost not metered, record excerpt + the watchdog finding — §14.4).

**4. Validation plan.** rung + pins; full suite once; CI once; Gate 2 once (approved).

**5. Acceptance criteria.**
- Rung green: the same boundary yields the expected verdict shapes for the three fixtures; atomicity diff shows only the history/objective identity varies.
- Packs: STATUS rows present and honest (test pins); PR0 governance guards still green (no `.py`, three roots, banners).
- Full-suite log 0 failed; CI green on the exact final head.
- **Gate 2 completion semantics (frozen):** READY FOR OPERATOR REVIEW / merge eligibility REQUIRES Gate 2 PASS with the required 07a boundary evidence (§10). A Gate 2 FAIL is preserved and diagnosed and BLOCKS 07a completion; it may be rerun ONLY after a substantive in-scope fix, or under the gate standard's explicitly permitted inconclusive / transient rerun rule (§15 C4 §6 admission-rejection handling stays as written). Never reroll an unchanged semantic failure merely to obtain green.

**6. Failure and edge cases.**
- Gate 2 planner elects a 1-epoch plan even with `--max_epochs 2` → R3 has one point; still PASS (functional) — record.
- Gate 2 admission rejects the attempt (runtime verification) → no results → the run's record is a rejection record without history — evidence that the boundary is NOT reached; classify as inconclusive for the 07a criterion, rerun ONCE only if the cause is a harness transient (standard rules).

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit -m "not real_run" -q > /tmp/07a_full.log 2>&1; rc=$?; tail -20 /tmp/07a_full.log`
- Gate 2: the standard's canonical command (`:102-121`) with the approved `--max_epochs`; artifacts read from the workspace; recorded in §14.

**8. Commit boundary.** rung + packs + docs; the Gate is evidence, not code; stop and show / record.

---

### Deferred to later PRs (NOT in 07a)

- Rendering SELECTED diagnosis lines / direction wording to planner and reflector; policy consumption of the diagnosis; `AttemptTransition` wire-or-remove — **07b**.
- Diagnosis condensation onto `ModelRunSummary`, interpreter rendering, cross-iteration knowledge — **Step 09**.
- Higher-level calibrated labels (overfitting / plateau / converged) with declared windows / tolerances — **Step 09** (or a later 07 revision by explicit act).
- A validation term in the runtime-control model (admission / watchdog) — **runtime-control design / 07c** (evidence: `validation_seconds` in the payload).
- Real Pets/DAVIS R2/R3 (executable tracks) — **D14**.
- Cadence beyond `per_epoch`; optional checkpointed observations produced by the trainer (validation accuracy / PSNR) — the slot exists; producers land with **D14 / Step 12** task declarations.

### Explicitly NOT re-opened

Step 06 semantics (metric ≠ loss; the planner filter mechanism is extended, not replaced); `final_loss` semantics (OD-S7-3); the eval-set split semantics (05a); the argv byte forms (02b/05c); the frozen §22.9a task semantics; the D14 placement; the PR0 packs' identity manifests.

---

## 16. Operator decisions — DISPOSED at the revision-1 review (2026-08-15)

| ID | Question | Recommendation (rev 1) | **Operator disposition** |
|---|---|---|---|
| **Q-07a-1** | Runtime accounting: exclude validation seconds from the training ACTUAL (unit-time priors stay per optimizer step) but do NOT model the validation pass in admission / watchdog in this PR; persist `validation_seconds` as evidence | Yes — parent §2.1 accepts "bounded by the eval set" | **APPROVED**; the un-priced validation phase is recorded as **07c / runtime-control debt** (§3.9, §14 at Checkpoint E) |
| **Q-07a-2** | Diagnosis vocabulary v1 = raw facts + explicit-tolerance trends + `validation_degraded_after_best`; NO overfitting / plateau / converged / underfitting labels | Yes | **APPROVED** (deadband made symmetric / scale-free — §0.5 item 6) |
| **Q-07a-3** | Validation dataset transient per epoch rather than resident | Yes | **APPROVED** |
| **Q-07a-4** | Gate 2 with `--max_epochs 2` | decide at launch | **APPROVED** — an upper bound only; PASS does not require two points (§10) |
| **Q-07a-5** | L1 fixture histories + expected diagnoses under `examples/<pack>/expected/` (JSON) consumed by rung B-07a-1 | Yes | **APPROVED** |
| **Q-07a-6** | Fail-closed = schema-invalid `training_history` → `error_training`; ABSENT payload = honest `absent` | Yes | **APPROVED WITH CORRECTION**: absence is honest ONLY when validation was not expected; an EXPECTED R3 that is missing is a contract failure → `error_training` (§3.4a) |
| **Q-07a-7** | Flag position: immediately after the `--sample_set_json` pair | Yes | **APPROVED** |

Three further corrections were required WITHOUT new operator decisions and
are applied in this revision: (1) declared validation scope → zero / partial
materialization = fail closed (§3.4b); (2) the objective reduction /
comparability precondition is source-grounded and stamped, never assumed
(§3.3); (3) validation restores the complete observable training state
immediately (§3.2). Revision 2 was FROZEN by the operator on 2026-08-15 and implemented (§14); the operator's post-implementation verdict (2026-08-16) is recorded in the Status row above.

## 17. Adversarial self-review (this child)

| # | Finding | Disposition |
|---|---|---|
| 1 | A prompts-only filter would keep PB-2 bytes but change the WF-2 pinned `actual_results` key set | hiding is tuner-side (`legacy_payload`) — §3.7 |
| 2 | Keeping the validation set resident would double peak memory under align | transient per epoch — §3.2 / Q-07a-3 |
| 3 | The validation pass inside the ACTUAL window would inflate unit-time priors for every later admission | subtract; persist `validation_seconds` — §3.9 / Q-07a-1 |
| 4 | A stochastic forward or a `train()`-mode BatchNorm would perturb epoch ≥ 1 | `eval()` + `no_grad` + `shuffle=False` + `fork_rng` + Python-random restore; oracle + fork mutation — §3.2 |
| 5 | Mean-of-batch-means on `drop_last=False` would silently change R3's meaning vs R2 | sample-weighted R3; comparability test with reversal mutation — §3.3 |
| 6 | Cross-machine float goldens for the trajectory would be brittle | two-arm in-process oracle; Checkpoint-0 values recorded in the ledger only |
| 7 | Deriving diagnosis labels (overfit/plateau) from shape would violate the parent | facts + explicit tolerance only — §3.6 |
| 8 | An `expected/` fixture nobody consumes would be a consumer-less file (§22.23.3) | the rung loads it from the pack — §3.11 / C4 |
| 9 | REC goldens regenerated in a later commit would break Step-00 §17 rule 3 | regenerated in C3, the commit that adds the fields |
| 10 | The tuner's `run()` must not gain branching | three sequencing calls; contract errors routed through an EXISTING failure path; branch count recorded |
| 11 (rev 1) | Zero-row validation scope → division by zero | rev 1 recorded `nan`; **superseded by the operator's blocker 2**: zero / partial materialization is a validation execution failure (§3.4b) |
| 12 (operator) | Expected validation could silently degrade to `absent` through a re-dropped transport | `expected_validation` at the tuner boundary → `error_training` (§3.4a) |
| 13 (operator) | "Same criterion object" ≠ mathematically comparable epoch statistic for `sum`-reduced / batch-coupled objectives | precondition P + built-in audit + `comparability` stamp (§3.3) |
| 14 (operator) | Mode restore relied on the next epoch; criterion statefulness and NumPy RNG were outside the isolation census | transactional pass, criterion state check, NumPy restore, state census in tests (§3.2) |
| 15 (operator) | `objective_id = loss_type` over-claimed identity | `objective_kind` + `objective_config_fingerprint` (§3.5) |
| 16 (operator) | Relative deadband had a zero-reference pathology; observation lists could be ragged | symmetric `r(a,b)`; length validators (§3.6, §3.5) |
