# Step 07 — PR 07a: TrainingHistory / TrainingDiagnosis (R2 / R3) — detailed design

| Field | Value |
|---|---|
| Parent | `../step_07_tuner_policy_and_training_diagnostics.md` (revision 2, FROZEN 2026-08-15) §8.2 — the 07a acceptance contract; §3 authority map; §18 OD-S7-1/-3/-4; §20 WHAT/HOW line |
| Roadmap | §20.2 (four concepts, OD-20-3/-4/-5), §22.1–§22.8 (R1–R4, cadence, History ≠ Diagnosis, information-flow governance), §22.9a (frozen track semantics), §22.12 row 07; §15.1 step-7 row (`§7a`) |
| Design base | `838e9cd6` (master; PR0 MERGED `79403b44`) — every source line below was re-read at this head |
| Depends on | PR0 MERGED (example packs exist); Steps 02/05a/05c/06 MERGED (profile transport, run-bound SampleSets, argv oracle, metric handle + planner filter) |
| Decomposition | ONE PR, four commits **C1 → C2 → C3 → C4** (§15) — trainer · transport + test infra · tuner boundary + record + hiding · rungs + packs + Checkpoint E |
| Gates | Gate 1 **NOT REQUIRED** (every rendered byte and kwarg key set exact — a hard criterion, §10) · Gate 2 **REQUIRED, bounded** (real training behaviour changes; launched ONLY with operator approval after C4, §10) |
| Status | **DRAFT — FOR OPERATOR REVIEW** (revision 1, 2026-08-15). Not frozen; no implementation; §14 ledger empty; §16 lists the decisions the operator is asked to confirm |

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**What this child freezes (HOW) once the operator approves it**: the trainer
validation pass and its RNG isolation (§3.2), the R2/R3 comparability
representation (§3.3), the transport IPC (`--eval_sample_set_json`, §3.4),
the `TrainingHistory` payload and the typed trainer→tuner results contract
(§3.5), the `TrainingDiagnosis` fields and rules (§3.6), the hiding mechanism
at both renders (§3.7), the record attachment (§3.8), the runtime-control
accounting rule (§3.9), the test-infra shape (§3.10), the example-pack
projection (§3.11), the rungs (§6), the Gate plan (§10) and the stop
conditions (§13). **What stays the parent's**: the semantic requirements
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

1. **Trajectory parity.** With fixed seeds the train-loss trajectory is
   bit-identical with and without the validation pass (structural RNG
   isolation + the two-arm oracle).
2. **Legacy floor byte-identical.** `final_loss`, `loss_history`,
   `model_params` — values and presence — unchanged in the results JSON, in
   `train_results`, at the reflect merge and on the record.
3. **One declared argv delta.** `--eval_sample_set_json <path>` and nothing
   else; emitted only in streaming mode with an eval set.
4. **R2 ≡ R3 semantics.** Both are the sample-weighted mean of the SAME
   criterion; R2's existing computation is untouched; R3 is exact under an
   unequal last batch.
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
mid-epoch admission rejection has been handled (`:1172-1176`):

```text
model.eval()
with torch.no_grad(), torch.random.fork_rng(devices=<the training device if CUDA else []>):
    (snapshot/restore Python `random` global state around the block as well)
    val_dataset = TIDMADEpochDataset(data_dir, eval_sample_set, seg_size,
                                     train_portion=None,        # NO subsampling → no rng draw
                                     rng=None, profile=profile, file_family="validation")
    val_loader  = DataLoader(val_dataset, batch_size=train_cfg.batch_size, shuffle=False, drop_last=False)
    for input_batch, target_batch in val_loader:
        <same dtype routing as training: resolve_input_dtype(...); get_target_torch_dtype(loss_cfg)>
        loss = criterion(model(input_seq), target_seq)
        accumulate loss.item() × batch_sample_count
    R3[ep] = Σ(loss_i × n_i) / Σ n_i
del val_dataset, val_loader; gc.collect()
model.train() is re-entered by the next epoch's existing `model.train()` (:948)
```

- **RNG isolation is structural**: `eval()` (no dropout, no BatchNorm
  running-stat update), `no_grad`, `shuffle=False` (SequentialSampler draws
  nothing), `train_portion=None` (no `rng.sample`), and `fork_rng` +
  Python-`random` snapshot restore ANY state a model's forward might touch.
  The two-arm oracle (§6, Checkpoint A) proves the trajectory bit-identical;
  the delete-the-hop mutation removes the fork and uses a fixture model whose
  forward consumes torch RNG → oracle RED.
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
  (`eval_portion`, `validation_max_portion` envelope, DataScope).

### 3.3 R2 / R3 comparability (FROZEN on approval)

Audit (§0.1): R2 = `np.mean(batch_losses)` over `drop_last=True` equal
batches = the sample-weighted mean of the per-batch criterion values, which
for a `reduction="mean"` criterion is the mean over all training samples of
the epoch. **R2 is not changed.** R3 = the sample-weighted mean of the
per-batch criterion values over the ENTIRE validation set (`drop_last=False`,
weights = batch sample counts) — the same statistic, exact under an unequal
last batch. Both carry the identity
`reduction = "sample_weighted_mean_of_batch_criterion"` in the payload so the
comparability claim is machine-visible. The comparability test (§6) uses a
validation set whose size is not a multiple of `batch_size` and checks R3
against an independent per-sample reference AND that the unweighted
mean-of-batch-means (the mutation) is REJECTED.

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

### 3.5 `TrainingHistory` and the typed trainer→tuner contract (FROZEN on approval)

`execute_tools/training_history.py`:

```text
TrainingHistory (frozen, extra="forbid")
  cadence:               Literal["per_epoch"] = "per_epoch"
  objective_id:          str            # the run-resolved training objective identity = loss_cfg.loss_type
                                        # (provenance of WHICH computation R2/R3 are; NOT task config)
  reduction:             Literal["sample_weighted_mean_of_batch_criterion"]
  epochs_planned:        int  (train_cfg.epochs)
  epochs_completed:      int  (= len(train_objective))
  train_objective:       list[float]        # R2 — the SAME floats as loss_history
  validation_objective:  list[float] | None # R3 — None when no validation scope (legacy / flag absent)
  validation_samples:    int | None         # ML segments evaluated per epoch (constant across epochs)
  validation_seconds:    list[float] | None # per-epoch wall time of the pass (evidence for the RT follow-up, §3.9)
  observations:          dict[str, list[float]] = {}   # optional checkpointed observations slot (v1 empty)
  validators: len(validation_objective) == len(train_objective) when present; epochs_completed <= epochs_planned;
              values may be non-finite (a diverged run is EVIDENCE, not a schema error) but the list lengths must agree

TrainingResults (the typed trainer→tuner contract; the ONE validation site = the tuner boundary)
  legacy_payload:  dict   — {k: raw[k] for k in ("final_loss","loss_history","model_params") if k in raw}
                            (presence AND values exactly as today; feeds the reflect merge and the record)
  history:         TrainingHistory | None   — None when the producer emitted no `training_history` key
  history_state:   Literal["present","absent"]
  interpret_training_results(raw: dict) -> TrainingResults
      raises TrainingResultsContractError (a ValueError) when `training_history` IS present but schema-invalid,
      or when history.train_objective != raw["loss_history"], or final_loss != train_objective[-1]
      (a producer violating its own contract is a bug → fail closed, never silently downgraded)
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
  final_vs_best_validation_degradation_rel: float | None   (÷ |validation_min| when non-zero)
  train_validation_gap_final: float | None                 (validation_last − train_last, signed)
  train_validation_gap_final_rel: float | None             (÷ |train_last| when non-zero)
  train_trend, validation_trend: Literal["decreasing","increasing","flat","single_point"] | None
      trend = sign(last − first) with an EXPLICIT scale-free deadband: |last − first| ≤ FLAT_REL_TOL × |first|
      → "flat"; FLAT_REL_TOL is a named module constant of the boundary (default 1e-2), recorded on the
      diagnosis as `flat_rel_tol` so a consumer can re-derive; a 1-point history → "single_point"
  validation_degraded_after_best: bool | None   (degradation_rel > FLAT_REL_TOL) — the calibration-free
                                                shape fact behind "overfitting evidence"; NOT labelled overfitting
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
  evidence for the follow-up "runtime model gains a validation term"
  (owner: the runtime-control design / 07c — recorded in §14 as debt, not
  fixed here). Operator confirmation requested (§16 Q-07a-1).
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
  atomic fixture `objective_id="focal"`), Pets (`objective_id="ce"`, CE
  train/validation + `observations={"validation_accuracy": [...]}`), DAVIS
  (`objective_id="mae"`, MAE train/validation + `observations=
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
| validation pass perturbs the training trajectory | two-arm oracle RED → STOP (parent stop: cannot be made RNG-neutral) |
| `--eval_sample_set_json` supplied but unreadable / wrong shape / violates DataScope | trainer `ValueError` (fail closed) / executor `ScopeViolationError` path — never a silent fallback |
| flag absent (legacy / caller predating it) | R3 absent, `validation_state="absent"`, diagnosis `state="ok"` — recorded, never silent |
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
  cost ≈ one more ~2 000-sample epoch. **NOT launched during design; NOT
  launched during implementation without explicit operator approval.**
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

Parent §8.2 stops: the pass cannot be made RNG-neutral; the existing
sample-set machinery cannot express the validation set without a new SPLIT
concept; R2/R3 cannot be made comparable without changing R2; reflector /
planner bytes cannot be held exact; any change to retry / round / timeout /
signal semantics; > ~1 h wall or material cost per attempt. Child stops: a
production file outside §3.1 must change; `run()` needs a new branch; a
consumer must READ the diagnosis for policy (07b); the RT observation schema
must change to record validation time (out of scope — the payload carries
it); a schema must be bent for Pets/DAVIS fixtures; a Gate must be launched
without approval.

---

## 14. Implementation ledger

*(empty until implementation; each commit's evidence lands here — Checkpoint
0 captures, counts, wall time, deviations, tests that could not run and why;
the Gate-2 readiness packet, approval, command, result.)*

---

## 15. Commit plan — per-commit checklists

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
- [ ] Re-read `train_engine_sandbox.py:289-448, 782-1235, 1243-1489`,
      `dataset_config.py:120-145`, `observation_store.py:160-176`,
      `session.py:711-718` immediately before editing (line drift check).
- [ ] Checkpoint 0 capture BEFORE the first production edit (recorded in
      §14): fixed-seed streaming trajectory on the in-process synthetic
      3-file fixture (CPU, `torch.manual_seed`, `train_base_seed`, 3 epochs,
      tiny wavenet) — the values, the loader `len`, the results JSON keys;
      REC-3 field lists (unchanged in C1); WF-1/WF-2/PB-1/PB-2 sha256s.
- [ ] Write Seam 5 in `genericity_contract.md`.
- [ ] Implement `execute_tools/training_history.py` (§3.5) with docstrings
      naming the frozen semantics.
- [ ] Implement the trainer changes (§3.2, §3.3, §3.4 child side, §3.9);
      keep the pass in ONE helper (`_validation_pass(...)` returning
      `(r3_value, n_samples, seconds)`) — the streaming loop gains a
      sequencing call, not a block.
- [ ] Tests (each named for its defect): (a) two-arm trajectory oracle
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
      present / absent / malformed / mismatched cases; (j) `TrainingHistory`
      validators (length agreement; non-finite allowed).

**4. Validation plan.**
- Unit: the families above (`tests/unit/execute_tools/test_step07a_c1_*`).
- Pseudo/integration: RT2-B/RT2-D/RT4/C2 existing suites green (unchanged
  semantics).
- Negative: (b), (e), (i) above; a validation set that violates the profile
  (`file_index ≥ num_files`) → the dataset skips/refuses exactly as the
  training path does today (no new behaviour).
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
  differs from mean-of-batch-means.
- Trainer argv accepts `--eval_sample_set_json` (child side); flag absent →
  behaviour identical to today except the additive key.
- Training ACTUAL excludes validation seconds; `unit_count` unchanged.
- ruff + pyright (CI) clean; Seam 5 present in the contract doc.

**6. Failure and edge cases.**
- Eval SampleSet with a file missing on disk → the dataset skips it exactly
  as training does (`:369-371`); with NO rows at all → R3 for that epoch is
  `nan` (evidence) and `validation_samples=0` — recorded, not raised (a
  scope that resolves to zero rows is a data-side fact, not a trainer bug).
- Non-finite training loss → R2/R3 carry the value; no exception.
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
  `validation_samples`).
- Non-goals: no tuner change; no record change; no golden other than the
  argv pins; the byte form of the sample-set JSON unchanged.
- Dependencies: C1.

**3. Implementation plan.**
- [ ] Re-read `wrapper.py`, `sandbox_executor.py:1268-1430, 2062-2180`,
      `recording_sandbox.py`, the streaming-argv pins (grep
      `--train_base_seed` / `--sample_set_json` in `tests/unit`).
- [ ] Implement wrapper + executor + Stub; upgrade RecordingSandbox +
      pseudo data (a small deterministic generator for the stub; the pseudo
      JSONs edited by hand, values consistent).
- [ ] Tests as listed; UPGRADE the streaming argv pins.
- [ ] Rung B-07a-2.

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
  interpret_training_results(train_status.get("results", {}))`;
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
  record.
- Non-goals: no policy reads the diagnosis; no rendering; no change to the
  same-loss rank; `HyperparamTuningOutput` untouched.
- Dependencies: C1, C2.

**3. Implementation plan.**
- [ ] Re-read `ml_hyperparameter_tune_agent.py:5600-5640, 5740-5770, 5855-5910`, `prompts.py:850-930, 1304-1389`, `hyperparam_tuning.py:360-380, 620-700`, `test_step00_record_baselines.py`, `test_step06_planner_boundary.py`.
- [ ] Implement the diagnosis module (pure) + tests first (TDD on the rules).
- [ ] Record fields + validator; boundary + diagnosis calls in the tuner (sequencing only; pyright complexity of `run()` must not move — verify no new branch).
- [ ] Hidden set + comment; boundary tests.
- [ ] Regenerate REC-2/REC-3 additively (same commit; three-part note); assert PB/WF sha256 unchanged.

**4. Validation plan.**
- Unit: `tests/unit/agent/schemas/test_training_diagnosis.py`, `tests/unit/agent/tune_ml_hyperparam_agent/test_step07a_c3_*`, upgraded boundary tests, record baselines.
- Pseudo: dual-mode tuner integration tests green with records now carrying both fields (`RecordingSandbox` replay).
- Negative: validator negatives; malformed payload → `error_training` record; a hidden key leaking → RED.
- Backward-compat: pre-07a records (no fields) validate unchanged; REC-2 pre-existing keys/values unchanged (the note states so, as Step 06 did).
- Gates: none at C3 (bytes exact).

**5. Acceptance criteria.**
- PB-1 (3), PB-2 (2), WF-1, WF-2 golden files byte-identical to their pre-07a sha256s (recorded in §14).
- The reflect call's `actual_results` key set == the WF-2 golden on a run whose train results carry `training_history`.
- Every success record in a pseudo run carries `training_history` (R2 + R3 lists) and `training_diagnosis` with `state="ok"`; failure/skip records carry `None`.
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
- [ ] Author the three L1 fixture histories with the EXACT §22.9a semantics (objective ids `ce` / `mae`; observations `validation_accuracy` / `validation_psnr`; the TIDMAD atomic fixture `focal`) and their expected diagnoses (literals).
- [ ] Rung test + pack pins; pack docs; node/skill docs.
- [ ] Docs sync; ledger §14 (counts / wall time / rc per commit; PB/WF sha256s; Checkpoint-0 values).
- [ ] Full suite from a clean tree; push; PR; exact-head CI (id in the PR body — no trailing docs-only push).
- [ ] Gate-2 readiness packet → operator approval → launch → record (PASS/FAIL/inconclusive, wall time, cost, the record excerpt).

**4. Validation plan.** rung + pins; full suite once; CI once; Gate 2 once (approved).

**5. Acceptance criteria.**
- Rung green: the same boundary yields the expected verdict shapes for the three fixtures; atomicity diff shows only the history/objective identity varies.
- Packs: STATUS rows present and honest (test pins); PR0 governance guards still green (no `.py`, three roots, banners).
- Full-suite log 0 failed; CI green on the exact final head; Gate 2 PASS with the 07a boundary evidence, or the FAIL recorded with diagnosis (never re-rolled to green).

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

## 16. Decisions the operator is asked to confirm at review (design ambiguity flagged, not silently chosen)

| ID | Question | Recommendation (source-grounded) |
|---|---|---|
| **Q-07a-1** | Runtime accounting: exclude validation seconds from the training ACTUAL (unit-time priors stay per optimizer step) but do NOT model the validation pass in admission / watchdog in this PR; persist `validation_seconds` as evidence for a later RT term | **Yes** — parent §2.1 accepts "bounded by the eval set"; modelling it needs an RT schema change (out of 07a scope) |
| **Q-07a-2** | Diagnosis vocabulary v1 = raw facts + explicit-tolerance trends + `validation_degraded_after_best`; NO overfitting / plateau / converged / underfitting labels | **Yes** — parent §8.2 item 3 / review finding 12 |
| **Q-07a-3** | Validation dataset transient per epoch (rebuilt after the training dataset is released) rather than resident | **Yes** — peak memory `max` not sum; I/O cost accepted and recorded |
| **Q-07a-4** | Gate 2 with `--max_epochs 2` (a bounded deviation from the canonical `1`) so R2/R3 have two points | Decide at launch; either is acceptable functionally |
| **Q-07a-5** | L1 fixture histories + expected diagnoses under `examples/<pack>/expected/` (JSON) consumed by rung B-07a-1 | **Yes** — roadmap §22.23.7 ("the same fixture is what the tests consume"); PR0 pins hold |
| **Q-07a-6** | Fail-closed = a producer that emits a schema-invalid `training_history` turns the attempt into an `error_training` record; ABSENT payload = honest `absent` state | **Yes** — parent "typed / validated / fail-closed"; absence is legacy tolerance |
| **Q-07a-7** | Flag position: immediately after the `--sample_set_json` pair (sibling), upgrading the streaming argv pins in the same commit | **Yes** — the sibling reading of the parent's recommendation; the legacy golden is untouched either way |

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
| 11 | Zero-row validation scope → division by zero | `nan` + `validation_samples=0`, recorded — §15 C1 §6 |
