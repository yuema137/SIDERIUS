# Step 07 — PR 07c: Measurement / verification data feeding, and pricing the validation pass

**STATUS — DRAFT revision 1, FOR OPERATOR REVIEW. Not frozen. No code written.**

| | |
|---|---|
| Parent | [`../step_07_tuner_policy_and_training_diagnostics.md`](../step_07_tuner_policy_and_training_diagnostics.md) — §2.4 (the seam), §8.4 (this PR's frozen contract + the ADDED scope), §9, §11 |
| Position | PR0 ✔ → 07a ✔ → 07b ✔ → trial/formal-identity correction ✔ → **07c** (last of Step 07) |
| Source audit base | `ad176036` (master, clean tree, 2026-08-17) |
| Prerequisites | all merged: PR0 `79403b44` · 07a `65804b3d` · 07b `9ea3755f` · correction `a15d1366` |
| Gates | Gate 1 **NOT REQUIRED** · Gate 2 **REQUIRED, bounded, once at the final executable head** (parent §11 row 07c) |
| Open questions | **§16 — Q-07c-1 … Q-07c-8, seven of which are BLOCKING.** Three were surfaced by the audit and are NOT anticipated by the parent |

> **Reviewer's shortcut.** If you read only two sections, read **§16** (the
> open questions — three of them change the commit plan) and **§15** (the
> per-commit checklists). §0 is the evidence everything else stands on.

---

## 0. Pre-design source audit (at `ad176036`)

Every line reference below was read, not recalled.

### 0.1 The two probe-batch loaders

| Fact | Site |
|---|---|
| `INPUT_CHANNEL = "channel0001"`, `TARGET_CHANNEL = "channel0002"` | `core/runtime_control/gpu_measurement_data.py:61-62` |
| `CLASS_INDEX_OFFSET = 128` | `core/runtime_control/gpu_measurement_data.py:66` |
| filename family hardcoded as a glob, twice | `gpu_measurement_data.py:117,119`; `execute_tools/probe_data.py:22,24` |
| the cast chain `astype(int8).astype(int16) + OFFSET` | `gpu_measurement_data.py:156` |
| bounded read — the D-C2-12 host-RSS property | `gpu_measurement_data.py:150` (`raw = channel[0:needed]`), evidence model `:69-98` |
| the OTHER loader materializes the whole channel via `TIDMADDataset` | `execute_tools/probe_data.py:29-38` |
| neither module imports `DatasetProfile` | verified: no import in either file |

Two loaders, byte-identical output, pinned by
`tests/unit/core/test_gpu_measurement_data.py`. The worker uses the bounded
one (`gpu_measurement_worker_main.py:204,282`); the in-process probe path uses
the unbounded one (`probe_production.py:222,224`).

**The bounded loader is not a duplicate to delete.** Its docstring
(`gpu_measurement_data.py:1-50`) records that `load_probe_batch` was killed at
24.10 GiB host RSS producing a 0.31 MiB batch. Whatever 07c builds, the
bounded read is the property that must survive; the unbounded path is the one
that must go.

### 0.2 The model-name branches in the measurement worker

```python
gpu_measurement_worker_main.py:235   if model_type == "fcnet":            # constructor arity
gpu_measurement_worker_main.py:236       model = model_class(model_cfg, loss_type=loss_cfg.loss_type)
gpu_measurement_worker_main.py:287   model_input = batch.float() if model_type == "fcnet" else batch.int()
```

**The parent (§2.4) names only the dtype branch.** The audit found a
**second** one, four dozen lines above it, in the same file. This matters
because the parent also requires extending
`test_no_model_name_branches.py`'s scan targets — and a guard pointed at that
file fails on `:235` too. See **Q-07c-3**.

Landed authorities that already answer both:

| Branch | Authority | Site |
|---|---|---|
| dtype (`:287`) | `resolve_input_dtype(model_type, task_contract, site_preference=...)` | `execute_tools/model_input_dtype.py:158-192` |
| — its fallback when no contract is transported | `BUILTIN_INPUT_DTYPES = {"fcnet": DtypeAdmissibility(admissible=("float32",))}` | `ml_models/models_sandbox.py:779-781` |
| constructor arity (`:235`) | signature introspection — but it is **private** to one skill, not a shared authority | `agent/skills/training_skill/estimator.py:295-321` |

`resolve_input_dtype(..., task_contract=None)` resolves `fcnet` → `float32`
and everything else → the site preference. With a site preference of
`"int32"` it reproduces `:287` exactly, contract or no contract.

### 0.3 Contract transport does not reach the worker

`GpuMeasurementSpec` (`core/runtime_control/gpu_measurement_spec.py:77-195`)
carries `model_config_payload`, `train_config`, `loss_config`, `data_dir`,
`plugin_dir`, `loss_dir`, phase, batch sizes, deadlines, paths — and **no
Model-I/O contract field**. Parent §6 lists the contract as "CONSUMED (07c's
dtype fix)", so 07c must add the transport. Declared scope, not a surprise.

### 0.4 The two `TIDMAD_DATA_DIR` fallbacks, and the capability that replaces them

| Site | What it does |
|---|---|
| `core/runtime_control/bootstrap.py:513-520` | `_dataset_check()` imports `TIDMAD_DATA_DIR` inside `core/` |
| `core/runtime_control/bootstrap.py:233` | remedy string: "Point the run at a readable TIDMAD directory" |
| `core/runtime_control/probe_production.py:210-212` | `resolved_dir = TIDMAD_DATA_DIR` when `data_dir` is falsy |

The task-side replacement already exists and is already used elsewhere:
`execute_tools/data_paths.py:142-181` `resolve_tidmad_measurement_capability()`
→ `core/runtime_control/measurement_capability.py` `ResolvedMeasurementCapability`
(task identity, dataset adapter, `data_shape_class`, `probe_available`, and a
mandatory `unavailability_reason` when unavailable). Its own module docstring
(`measurement_capability.py:1-30`) names this exact defect class: "a task
assumption expressed by *omission* inside generic infrastructure".

### 0.5 What the profile already declares (nothing needs inventing)

| Needed by the builder | Declared at |
|---|---|
| input / target channel | `DatasetProfile.channels` → `ChannelIdentity.input_channel/.target_channel`, `execute_tools/dataset_config.py:338-360` |
| storage dtype, compute dtype, `+128`, alphabet | `DatasetProfile.encoding` → `ValueEncoding`, `dataset_config.py:381-409` |
| filename | `DatasetConfig.training_file_name(file_index)`, `dataset_config.py:119-124`; pattern `abra_training_{file_index:04d}.h5`, `:323` |
| file topology | `DatasetConfig.num_files` |

**There is no glob helper.** The loaders glob; the profile declares a
`{file_index}` pattern and a per-index name builder. Reproducing
`sorted(glob(...))[0]` from the profile is a real decision, not a rename —
see **Q-07c-2**.

### 0.6 Identity / hash surfaces that must not move

`MeasurementIdentity` (`core/runtime_control/registry_schemas.py:383-450`)
components, in order: `measurement_kind, task_identity, data_shape_class,
model_family, candidate_config_hash, phase, hardware_uuid,
runtime_stack_identity`. **`dtype` is not an identity component**, and neither
is any batch content — so a dtype or batch change does not rename a key, it
silently changes the *values* stored under an unchanged key. That is worse,
not better, and it is why Checkpoint A is byte-identity of the batch rather
than equality of the key alone.

`observation_store.calibration_key(phase, ...)` embeds `f"phase={phase}"`
(`observation_store.py:78-100`), so a NEW phase creates a NEW key namespace
and leaves every existing key untouched.

### 0.7 The watchdog deadline — the ADDED scope's exact site

```python
core/sandbox_executor.py:446-481   def provider() -> tuple[float | None, str]:
    candidates = []
    if policy.operator_budget_seconds is not None:        # "operator_budget"
    if policy.watchdog.max_phase_seconds is not None:     # "validation_max_phase"
    block = _read_runtime_observation_sidecar(rv_sidecar_path)
    predicted = [c["prediction"]["predicted_seconds"] for c in components
                 if ... c["prediction"]["source"] in MEASUREMENT_BACKED_SOURCES]
    if predicted:
        estimate = sum(predicted) * watchdog_factor      # "verified_components"
    deadline, source = min(candidates, ...)
    return max(deadline, policy.watchdog.floor_seconds), source
```

Two properties decide the whole design of C5:

1. **The deadline already sums *every* measurement-backed component
   prediction.** If validation were a component with a measurement-backed
   prediction, `sum(predicted)` would price it with **zero change to this
   arithmetic**.
2. **C8d forbids a non-measurement-backed prediction from setting a kill
   deadline** (`:460-467`). So a static prior for `T̂_val` is inert here by
   construction — which is the cold-start problem in **Q-07c-5**.

The debt is already written down at the source:

```python
execute_tools/train_engine_sandbox.py:1512-1515
#   The pass is not priced by admission / prediction / the watchdog in
#   07a — 07c / runtime-control debt; ``validation_seconds`` in the
#   payload is the evidence.
runtime_session.record_phase_actual(
    "training", (time.perf_counter() - t_train_start) - validation_seconds_total)
```

07a's evidence exists and is per-epoch: `validation_seconds: list[float]`,
`validation_samples: int` (`train_engine_sandbox.py:1202-1203,1493,1555-1556`)
— but it lands in the **trainer results payload**, not in the runtime
observation store. Nothing routes it into `RuntimeSession`.

`RuntimePhase` is a closed 5-value `Literal` (`core/runtime_control/phases.py:18-26`)
whose own docstring says new phases "extend this vocabulary without changing
the framework". 59 references across `core/`, `execute_tools/`, `nodes/`,
`agent/`; the one exhaustive loop (`records.py:575`) is guarded by
`p in components`.

### 0.8 Existing validation envelope flags

`validation_max_portion`, `validation_max_train_samples`,
`validation_max_phase_seconds` — `agent/schemas/hyperparam_tuning.py:1885,
1916,1942`; the last is fused to `runtime_watchdog_enabled` by
`_validate_validation_wall_clock` (`:2118-2128`). There is **no**
`validation_max_samples` (a ceiling on the VALIDATION row count, as opposed to
the training row count). The parent's interim envelope is therefore a new
field, not a rename.

---

## 1. Capability / final effect

Two effects, one PR (the parent's decomposition is frozen at four PRs; §8.4
puts both here).

**A — measurement feeding becomes task-derived.** One profile-derived probe
batch builder, used by both the in-process probe path and the worker's bounded
loader, deriving channel identity, encoding/offset and filename family from the
resolved `DatasetProfile` and the model-boundary dtype from the run-bound
`ModelIOContract`. Dataset availability inside `core/runtime_control/` is
answered by the task-owned `ResolvedMeasurementCapability` the caller already
holds. Under TIDMAD every byte, hash and store key is unchanged.

**B — the runtime model prices the validation pass.**

```text
T_deadline = T̂_train + T̂_val + T_overhead + margin
T̂_train   = N_train_steps × t̂_train_step        (existing pure step model, UNCHANGED)
T̂_val     = N_val_samples × t̂_val_sample
```

so the watchdog stops killing attempts inside work it never budgeted for. Left
unfixed this is a **bias**, not just lost attempts: validation cost grows with
model size, so large candidates die in validation while small ones survive and
the tuner learns a false regularity.

**Non-effect, stated once:** 07c does not change what the LLM sees, does not
change scoring, and does not change the pure per-optimizer-step cost model
07a deliberately kept clean.

---

## 2. Scope

### 2.1 Files expected to change

| File | Change | Commit |
|---|---|---|
| `execute_tools/probe_batch.py` *(new)* | the ONE profile-derived bounded builder | C2 |
| `core/runtime_control/gpu_measurement_data.py` | delegate to the builder; keep `BoundedReadEvidence`; drop the three constants | C2 |
| `execute_tools/probe_data.py` | delete `load_probe_batch` or reduce it to a shim | C2 |
| `core/runtime_control/probe_production.py` | call the one builder; capability-routed dir | C2, C4 |
| `core/runtime_control/gpu_measurement_worker_main.py` | contract-derived dtype (`:287`), constructor arity (`:235`, pending Q-07c-3) | C3 |
| `core/runtime_control/gpu_measurement_spec.py` | contract transport field | C3 |
| `core/runtime_control/bootstrap.py` | `_dataset_check` + remedy via capability | C4 |
| `core/sandbox_executor.py` | the `T̂_val` term | C5 |
| `core/runtime_control/phases.py`, `session.py` | validation phase/component (pending Q-07c-4) | C5 |
| `execute_tools/train_engine_sandbox.py` | route 07a's validation evidence into the session | C5 |
| `agent/schemas/hyperparam_tuning.py`, `nodes/ml_hyperparameter_tune_agent/cli.py` | `validation_max_samples` | C6 |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`, `docs/running_chain_test.md` | operator surface | C6, C7 |
| `tests/unit/core/test_gpu_measurement_data.py` + new test modules | oracles and rungs | C1–C7 |

### 2.2 Non-goals (must remain unchanged)

- The `seg=40000 / batch=1` coordinated triple stays **framework-owned**
  (`gpu_measurement_identity.py:214-215`, `gpu_measurement_worker_main.py:254,266`,
  `probe_production.py:220-221`). 07c may centralize it; the values and the
  identity hashes do not move, and it never becomes task config.
- `MeasurementIdentity.components()`, `candidate_config_hash`, the planned and
  inference workload hashes, `calibration_key`, the `data_shape_class` string.
- The bounded-read (host-RSS) property.
- RT admission / verification / timeout / signal behaviour — except exactly as
  Q-07c-6 disposes for the deadline.
- 07a's training ACTUAL stays validation-EXCLUSIVE. The fix is one layer up.
- Planner exposure and production defaults: every new field defaults to
  parity-preserving `None`.
- The measurement path's file selection is scope-unaware today (it globs and
  takes the first). 07c preserves that; making measurement DataScope-aware is
  not in this PR.
- Prompts, PB/WF surfaces, record schemas, `MetricOrder`, HealthGate.
- `resolved_action` (parent §17.1).

### 2.3 Dependencies

C2 → C1. C3 → C2. C4 independent of C2/C3 but sequenced after for review
clarity. C5 independent of C2–C4 (different subsystem). C6 → C5. C7 → all.

---

## 3. Checkpoints (parent §8.4, item by item)

| Checkpoint | Content | Commit |
|---|---|---|
| **0** | extend `test_gpu_measurement_data.py`'s byte-identity oracle to the new builder; verify the PR-G identity/hash/key pins green BEFORE editing | C1 |
| **A** | batches byte-identical under TIDMAD; identity components, `candidate_config_hash`, planned + inference workload hashes, `calibration_key`, `data_shape_class` exact string unchanged; store readable unchanged; RT admission/verification unchanged | C2–C4 |
| **B** | **B-07c-1** — Step-02 3-file contrast profile (4.8-B geometry) with a non-int8 / other-channel declaration → **different bytes**, while identity keys and comparability stay byte-stable, asserted in ONE test so the axis is provably single | C7 |
| **C** | production pre-phase measurement builds its batch from the profile in a real run — **Gate 2, bounded** | C7 |
| **D** | delete-the-hop (builder ignores the profile → contrast rung RED); dtype-branch reintroduction → guard RED; `TIDMAD_DATA_DIR` import inside `core/runtime_control/` → guard RED; reachability: worker AND probe path both call the one builder | C2–C4, C7 |

---

## 4. Gates

Quoted from `docs/gates/gate_testing_standard.md` at this base, decided
separately (roadmap §17.0).

**Gate 1 — NOT REQUIRED.** Trigger is "a commit that changes an LLM-facing
system prompt or schema"; 07c changes neither. Flip condition: none expected.

**Gate 2 — REQUIRED, bounded, once, at the final executable head.** Table row
*"Checkpoint (end of feature) | Gate 2"*, and §17 names §7e among the modules
that change real execution behaviour. The measurement **is** real execution:
no pseudo path exercises a profile-built batch on a device. PASS = functional
— a measured admission reached from a profile-built batch, per the standard's
functional criteria. Corpus: TIDMAD.

**Gate 2 and the watchdog debt this PR is fixing.** The standard's current
posture (§"If a Gate omits `--runtime_watchdog`…") permits omitting the
watchdog together with `--validation_max_phase_seconds`. Whether 07c's Gate 2
must run **with** the watchdog enabled — to demonstrate the very fix — is
**Q-07c-7**.

**Not launched without operator approval.** No live Gate is run at design
time, and none before C7.

---

## 5. Stop conditions

Parent §8.4's, plus what the audit adds:

- any identity hash or store key would change;
- the bounded-RSS property cannot be kept;
- a batch fact is not derivable from profile + contract;
- **the guard extension cannot be scoped without either an exclusion list or
  an unrelated refactor** (Q-07c-3);
- **pricing validation cannot be done without changing admission verdicts**
  and the operator has not authorized that (Q-07c-6);
- `RuntimePhase` extension would change an existing store key or identity;
- the validation term cannot become measurement-backed, so C8d leaves it inert
  and the fix is cosmetic (Q-07c-5).

---

## 6. Test-economy note

Per the repository's evidence-economy rule: the full unit suite is a
**terminal** gate run once at the final executable head, not per commit. Each
commit below lists targeted tests only. Broad regression is exact-head CI's
job.

---

## 7. A note on the reviewer template

The per-commit template supplied for this doc includes two clauses inherited
from the data-ordering work — *"for ordering behavior, validate the actual
visited sample/file sequence"* and *"for the default `shuffle` path, prove
that selection, random-seed behavior, visited sequence, and step count remain
unchanged"*. 07c has no `shuffle` path and no `file_order`. The **intent**
behind them — *assert the observed sequence, not the configuration value* — is
kept and instantiated as: assert the **bytes of the produced batch and the
file actually opened**, never merely that the builder was handed a profile.
C2's acceptance criteria are written that way.

---

## 8. Commit plan

Seven commits, two independently reviewable blocks: **C1–C4 measurement
feeding**, **C5–C6 validation pricing**, **C7 rung + Gate + docs**.

---

### C1 — Checkpoint 0: byte-identity oracle and pin verification (test-only)

**1. Goal.** Establish the oracle that every later commit is measured against,
while production is still untouched. The claim "batches are byte-identical" is
worthless if captured after the edit.

Belongs here because a baseline captured on a dirty tree proves nothing, and
because the PR-G identity pins must be seen green before anyone can say 07c
kept them green.

**2. Scope.** `tests/unit/core/test_gpu_measurement_data.py` (extend);
possibly one new fixture module. No production file. Non-goal: no new builder
yet. No dependencies.

**3. Implementation plan.**
- [ ] Read `test_gpu_measurement_data.py` in full and record what its existing
      byte-identity oracle compares and on which HDF5 fixture.
- [ ] Record the fixture's provenance and geometry; confirm it is committed and
      machine-independent (CLAUDE.md portability rule).
- [ ] Extend the oracle to a builder-shaped seam that does not exist yet, so
      C2 wires into it rather than inventing a second comparison.
- [ ] Enumerate the PR-G identity/hash/key pins by test id (`MeasurementIdentity`
      components, `candidate_config_hash`, planned + inference workload hashes,
      `calibration_key`, `data_shape_class`) and record each test's file:line.
- [ ] Capture the batch bytes (sha256 of the tensor buffer), the opened
      filename, dtype and shape as a committed golden with `_captured_at`
      naming this base SHA.

**4. Validation plan.**
- Unit: the extended oracle passes against the CURRENT two loaders.
- Negative: mutate the fixture's first segment → the golden fails (proves the
  oracle is not vacuous).
- Backward-compat: the enumerated pins run and pass unmodified.
- Integration/pseudo: none. Gate: none.

**5. Acceptance criteria.**
- [ ] `load_probe_batch` and `load_bounded_probe_batch` produce tensors whose
      sha256, dtype (`int64`) and shape are equal to each other and to the
      committed golden.
- [ ] The golden records the exact opened filename.
- [ ] Every enumerated pin test passes, listed by id with counts.
- [ ] Deliberately corrupting one fixture byte turns the oracle RED (recorded).

**6. Failure and edge cases.** Fixture absent → the test must SKIP with a
named reason, never silently pass. Fixture too small for `batch×seg` → the
existing `RuntimeError` path is asserted, not worked around.

**7. Verification commands and evidence.**
```bash
pytest tests/unit/core/test_gpu_measurement_data.py -q
pytest <enumerated PR-G pin tests> -q
```
- [ ] counts / wall time recorded in §17.
- [ ] anything unrunnable recorded with the reason; never claimed as passed.

**8. Commit boundary.** Test-only; reviewable alone; contains no production
change and no cleanup. Diff summary + staged file list shown before commit.

---

### C2 — One profile-derived probe batch builder

**1. Goal.** Remove the three hardcoded TIDMAD facts (channel, `+128` offset,
`abra_training_*.h5`) from the measurement path by deriving them from the
resolved `DatasetProfile`, and collapse two loaders into one that keeps the
bounded read.

Belongs here, separate from C3, because this commit changes **where facts come
from** while producing identical bytes; C3 changes **which dtype the model is
handed**. Merging them would make a byte diff ambiguous between the two.

**2. Scope.** New `execute_tools/probe_batch.py`;
`gpu_measurement_data.py` (delegate, keep `BoundedReadEvidence`);
`probe_data.py` (remove/shim); `probe_production.py:222-224` (call the one
builder). Non-goals: the `seg/batch` triple; the dtype branch; DataScope
awareness; the evidence model's shape. Depends on C1.

**3. Implementation plan.**
- [ ] Confirm from source which callers can supply a resolved `DatasetProfile`
      and how it reaches the worker subprocess (a profile is already
      transported for scoring via `--dataset_profile_json`; verify the
      measurement spec's situation and record it).
- [ ] Define the builder signature — profile + `data_dir` + `batch_size` +
      `segment_length` → tensor + `BoundedReadEvidence`.
- [ ] Derive the channel from `profile.channels.input_channel`.
- [ ] Derive the cast chain from `profile.encoding` (`storage_dtype`,
      `compute_dtype`, `value_offset`) instead of the module constants.
- [ ] Resolve the source file per **Q-07c-2**'s disposition, preserving which
      file is actually opened.
- [ ] Keep the bounded slice `channel[0:needed]` — no `np.array(channel)`.
- [ ] Point `gpu_measurement_data.load_bounded_probe_batch` at the builder.
- [ ] Point `probe_production.py` at the builder; delete `load_probe_batch` or
      reduce it to a deprecation shim per **Q-07c-1**.
- [ ] Remove `INPUT_CHANNEL` / `TARGET_CHANNEL` / `CLASS_INDEX_OFFSET` (or
      re-export them if a consumer outside the audit needs them — grep first).

**4. Validation plan.**
- Unit: C1's oracle, now against the builder — bytes, dtype, shape, filename.
- Unit: evidence model still reports the true `bytes_read` / `first_sample` /
  `last_sample`.
- Negative: profile declaring a missing channel → typed `RuntimeError`, no
  fallback to the unbounded loader (the module's NO FALLBACK contract).
- Negative: dataset too small → existing error preserved.
- Reachability (Checkpoint D): a test that fails if either the worker or the
  probe path stops calling the builder.
- Delete-the-hop (Checkpoint D): builder ignores the profile → C7's contrast
  rung RED.
- Backward-compat: PR-G pins unchanged.
- Gate: none in this commit.

**5. Acceptance criteria.**
- [ ] Batch sha256, dtype and shape equal C1's golden — **the bytes, not the
      fact that a profile was passed**.
- [ ] The **file actually opened** equals C1's recorded filename (asserted from
      `BoundedReadEvidence.source_file`, not from the config).
- [ ] Peak host RSS during a builder call stays bounded — asserted via
      `bytes_read` ≪ `file_sample_count`, with the ratio recorded.
- [ ] `grep -rn "channel0001\|channel0002\|abra_training_\|+ 128" core/runtime_control/ execute_tools/probe_*.py` returns nothing in live code.
- [ ] Exactly one builder is called by both paths (reachability test named).
- [ ] All PR-G pins green.

**6. Failure and edge cases.**

| Case | Behaviour |
|---|---|
| profile channel absent in the HDF5 | STOP — typed `RuntimeError`, never fall back |
| declared file index missing on disk | per Q-07c-2; must not silently substitute another file |
| duplicate / ambiguous filename match | deterministic, documented choice; recorded in evidence |
| `data_dir` unreadable | existing explicit failure (C4 makes the reason task-owned) |
| dataset smaller than `batch×seg` | existing `RuntimeError` preserved |
| legacy caller with no profile | per Q-07c-1 — either refused or an explicit shim; never an implicit TIDMAD default |
| partial `--data_scope` | unchanged behaviour, documented as a known non-goal |

**7. Verification commands and evidence.**
```bash
pytest tests/unit/core/test_gpu_measurement_data.py tests/unit/execute_tools/ -q
pytest <PR-G pin tests> -q
ruff check . && ruff format --check .
```
- [ ] counts / wall time / rc recorded in §17 immediately after the run.

**8. Commit boundary.** One responsibility: the data-fact source. No dtype
change, no capability routing, no unrelated cleanup. Diff summary shown before
commit.

---

### C3 — Contract-derived model-boundary dtype (and contract transport)

**1. Goal.** Replace `batch.float() if model_type == "fcnet" else batch.int()`
with the landed dtype authority, and transport the contract to the worker so
the authority has its input.

Separate from C2 because it is the only commit permitted to change what the
model is handed; keeping it alone makes a byte regression attributable.

**2. Scope.** `gpu_measurement_worker_main.py:287` (and `:235` iff Q-07c-3
says so); `gpu_measurement_spec.py` (contract field); the worker's argv/spec
serialization; `tests/.../test_no_model_name_branches.py` (scan targets).
Non-goals: changing `resolve_input_dtype` itself; adopting phase-correct
inference dtype (**Q-07c-8**). Depends on C2.

**3. Implementation plan.**
- [ ] Record the CURRENT dtype the worker feeds for every builtin, per phase,
      as a table (the A6-style matrix) — this is the parity target.
- [ ] Add the contract field to `GpuMeasurementSpec` (optional, default `None`
      = Regime-A) and thread it through spec construction and worker parse.
- [ ] Replace `:287` with `resolve_input_dtype(model_type, contract,
      site_preference=<per Q-07c-8>)`.
- [ ] Dispose `:235` per Q-07c-3 (leave, or move signature introspection to a
      shared authority and use it).
- [ ] Extend the guard's `_SCAN_TARGETS` to the measurement files chosen in
      Q-07c-3 — **not** the whole `core/runtime_control/` directory (see the
      failure table).
- [ ] Re-run C1's oracle: bytes unchanged.

**4. Validation plan.**
- Unit: dtype matrix — every builtin × phase → the recorded pre-change dtype.
- Unit: contract present vs `None` (Regime-A) → same dtype under TIDMAD.
- Negative: a contract admitting no runtime-supported dtype →
  `UnsupportedModelInputDtypeError`, fail closed, not a silent coercion.
- Negative (Checkpoint D): reintroduce `if model_type == "fcnet"` in a scanned
  file → guard RED (recorded as a real mutation, caches cleared).
- Backward-compat: a spec without the contract field still validates.
- Gate: none.

**5. Acceptance criteria.**
- [ ] For every builtin and both phases, the concrete dtype fed to the forward
      is **identical** to the pre-change table, asserted per row.
- [ ] `fcnet` → `float32` **with and without** a transported contract.
- [ ] Batch sha256 unchanged from C1's golden.
- [ ] No `model_type ==` string comparison remains in the scanned measurement
      files (asserted by the guard, with the mutation proof recorded).
- [ ] A spec JSON captured before this commit still loads.

**6. Failure and edge cases.**

| Case | Behaviour |
|---|---|
| no contract transported (legacy spec, ad-hoc test) | Regime-A: model's own declaration, else site preference — never a fabricated TIDMAD contract |
| contract ∩ runtime-supported = ∅ | STOP, typed error |
| plugin model with no declaration | site preference, exactly as today |
| guard pointed at the whole directory | **fails on `campaign.py`'s legitimate `"family": "wavenet"` config data** — the guard must target files, not the directory |
| `:235` left in place | the guard must not be pointed at a file that still contains it, or the commit is red by construction |

**7. Verification commands and evidence.**
```bash
pytest tests/unit/core/ -k "measurement or dtype or model_name" -q
pytest tests/unit/core/test_gpu_measurement_data.py -q
```
- [ ] counts / wall time / rc recorded in §17.
- [ ] mutation proof recorded per the mutation-hygiene rule (clear `.pyc`,
      assert exactly one target site, re-run the baseline).

**8. Commit boundary.** Dtype + its transport + its guard. No data-fact
changes (C2), no capability routing (C4).

---

### C4 — Capability-routed dataset availability inside `core/runtime_control/`

**1. Goal.** Remove the last two `TIDMAD_DATA_DIR` imports from generic
infrastructure by routing them through the task-owned
`ResolvedMeasurementCapability` the caller already holds, so the measured
path does not disable itself on a non-TIDMAD task.

Separate commit: it changes *availability decisions and their reasons*, not
bytes. A failure here looks nothing like a batch regression.

**2. Scope.** `bootstrap.py:233,513-520`; `probe_production.py:210-212`; a new
guard test. Non-goals: changing `resolve_tidmad_measurement_capability`;
changing what `probe_available=False` does downstream. Independent of C2/C3.

**3. Implementation plan.**
- [ ] Trace every caller of `production_dependencies()` and record whether it
      already holds a capability or a dataset root.
- [ ] Change `_dataset_check` to consume the capability; keep the
      `(ok, detail)` shape unless source shows the caller can take the typed
      object.
- [ ] Replace the remedy string with the capability's
      `unavailability_reason` (which is mandatory when unavailable).
- [ ] Remove `probe_production.py`'s `TIDMAD_DATA_DIR` fallback; a missing
      `data_dir` becomes an explicit typed failure.
- [ ] Add a guard test: no `TIDMAD_DATA_DIR` / `execute_tools.data_paths`
      import anywhere under `core/runtime_control/`.

**4. Validation plan.**
- Unit: available → same `(True, path)` verdict and same bootstrap step
  outcome as today.
- Unit: unavailable → `ok=False` and a remedy that **names the reason**.
- Negative (Checkpoint D): reintroduce the import → guard RED (mutation
  recorded).
- Backward-compat: bootstrap step names, order and pass/fail unchanged on a
  healthy TIDMAD environment.
- Gate: none.

**5. Acceptance criteria.**
- [ ] `grep -rn "TIDMAD_DATA_DIR" core/runtime_control/` returns nothing.
- [ ] The bootstrap step list — names, order, `ok` values — is byte-identical
      on a healthy environment (asserted against a captured projection).
- [ ] An unavailable capability yields a non-empty remedy naming the task and
      the reason; the assertion is on the reason, not on truthiness.
- [ ] No caller had to invent a dataset root it did not already hold.

**6. Failure and edge cases.**

| Case | Behaviour |
|---|---|
| capability unavailable | bootstrap FAILS as today, with a better reason — not a warning |
| caller holds no capability | STOP and report: this contradicts `measurement_capability.py`'s premise that every caller already holds the values |
| non-TIDMAD task | measurement no longer silently disables itself — the point of the commit |
| `data_dir` explicitly supplied | highest precedence, unchanged |

**7. Verification commands and evidence.**
```bash
pytest tests/unit/core/ -k "bootstrap or capability or probe" -q
```
- [ ] counts / wall time / rc recorded in §17.

**8. Commit boundary.** Availability plumbing only.

---

### C5 — Price the validation pass in the runtime model (ADDED SCOPE, root fix)

> **BLOCKED on Q-07c-4, Q-07c-5, Q-07c-6.** The checklist below is written
> against the *preferred* answers and must be re-cut if the operator decides
> otherwise. Do not start C5 before they are disposed.

**1. Goal.** Make `T̂_val` a real term so the watchdog deadline covers work the
attempt actually performs. Fixes the 07a Gate-2 finding: 3 of 4 attempts
killed inside validation; the survivor spent 9 s training and 26.45 s
validating, against a deadline built from the 9 s alone.

Separate from C6: this is the root fix; C6 is a cost envelope that does not
make the prediction correct.

**2. Scope.** `core/sandbox_executor.py:446-481`; `core/runtime_control/phases.py`
+ `session.py` (per Q-07c-4); `execute_tools/train_engine_sandbox.py`
(route 07a's per-epoch evidence into the session). Non-goals: 07a's
validation-exclusive training ACTUAL; the pure per-step model; admission
verdicts unless Q-07c-6 authorizes it. Independent of C2–C4.

**3. Implementation plan.**
- [ ] Record the pre-change deadline for a fixed synthetic sidecar as the
      parity baseline (`(deadline, source)` pairs across candidate sets).
- [ ] Implement the validation component per Q-07c-4 (new `RuntimePhase`
      preferred: the deadline then sums it with **no arithmetic change**).
- [ ] Route 07a's `validation_seconds` / `validation_samples` into the session
      as the phase ACTUAL + unit count, so `realized_unit_ms` is
      `seconds ÷ samples`.
- [ ] Establish the first prediction per Q-07c-5 (in-subprocess measurement of
      the first validation batch is preferred — it mirrors RT2's "verification
      = the first production steps" and is measurement-backed, so C8d admits
      it).
- [ ] Confirm from source that the deadline arithmetic needs **no** edit if
      the component exists; if an edit is needed, state exactly why.
- [ ] Assert `T_deadline` grows by the validation term and by nothing else.

**4. Validation plan.**
- Unit: deadline parity — with no validation component, `(deadline, source)`
  is identical to the baseline for every candidate combination.
- Unit: with a measurement-backed validation prediction, the deadline is
  `(ΣT̂_train + T̂_val) × factor`, floored — asserted numerically, not
  "greater than".
- Unit: a NON-measurement-backed validation prediction is ignored (C8d).
- Unit: `min(...)` precedence unchanged — `operator_budget` and
  `validation_max_phase` still tighten.
- Unit: the training ACTUAL still excludes validation seconds (07a parity).
- Unit: `calibration_key` for existing phases unchanged; the validation key is
  a NEW namespace.
- Pseudo: a bounded pseudo training run emits a validation component with a
  finite actual.
- Negative: zero validation samples, `None` evidence, validation disabled →
  the term is absent, never `0/0` or `nan`.
- Backward-compat: an observation store written before this commit is read
  without error and its records keep their phases.
- Gate: deferred to C7 (one bounded Gate 2 for the whole PR).

**5. Acceptance criteria.**
- [ ] With no validation evidence, `_watchdog_deadline_provider` returns a
      `(deadline, source)` pair **identical** to the recorded baseline for
      every enumerated candidate set.
- [ ] With validation evidence, the deadline equals the exact expected number
      (hardcoded, not recomputed from the implementation).
- [ ] A replay of the 07a Gate-2 numbers (9 s train / 26.45 s validate,
      125 steps, 15 000 rows) yields a deadline ≥ the observed 35.45 s wall
      time, whereas the pre-change provider yields < it. **This is the
      commit's headline assertion.**
- [ ] The training ACTUAL for the same replay is unchanged (validation-exclusive).
- [ ] `RUNTIME_PHASES` gains at most one value; every existing
      `calibration_key` string is unchanged (asserted against captured keys).
- [ ] Admission verdicts unchanged for a fixed input set, unless Q-07c-6
      authorized otherwise — in which case the changed verdicts are enumerated.

**6. Failure and edge cases.**

| Case | Behaviour |
|---|---|
| first attempt, no prior | per Q-07c-5. If the term cannot be measurement-backed, C8d ignores it and the watchdog can still kill inside validation — this must be stated, not hidden |
| validation disabled / R3 absent | no term; deadline exactly as today |
| `validation_samples == 0` | no term; never a division by zero |
| evidence present but `validation_seconds` empty | treated as absent |
| store written by an older build | read unchanged; missing phase is not an error |
| validation slower per sample than any prior | the deadline is a *bound*, not a promise; the watchdog may still fire, and that is correct behaviour, recorded as such |
| watchdog disabled | nothing changes (default posture) |

**7. Verification commands and evidence.**
```bash
pytest tests/unit/core/test_sandbox_executor*.py -q
pytest tests/unit/core/ -k "runtime_control or watchdog or observation" -q
pytest tests/unit/execute_tools/ -k "train_engine or training_history" -q
```
- [ ] counts / wall time / rc recorded in §17.

**8. Commit boundary.** The prediction term and its evidence route. No CLI, no
envelope, no measurement-feeding change.

---

### C6 — Interim validation-scope envelope (`validation_max_samples`)

**1. Goal.** Bound `N_val` for Gates and small campaigns so validation cannot
be 7.5× the training epoch, as it was in 07a's Gate 2. Explicitly the
**interim** cost bound, not the root fix — a slow model can still be misjudged
at 2 000 validation rows.

After C5 because a ceiling that hides a mispriced deadline would remove the
evidence C5 needs.

**2. Scope.** `agent/schemas/hyperparam_tuning.py` (new field),
`nodes/ml_hyperparameter_tune_agent/cli.py`, the trainer's validation
materialization, the node `.md` and `docs/running_chain_test.md`. Non-goals:
changing `validation_max_portion` / `validation_max_train_samples` /
`validation_max_phase_seconds`; any default change. Depends on C5.

**3. Implementation plan.**
- [ ] Read how `validation_max_portion` and `validation_max_train_samples` are
      resolved and applied, and add the row ceiling at the SAME point.
- [ ] Add `validation_max_samples: int | None = None` with a description that
      states it bounds the VALIDATION rows, distinct from the training-row
      ceiling it will sit beside.
- [ ] Add the CLI flag, forwarded like its siblings.
- [ ] Ensure clamping, never rejection (the standard's distinction between a
      sizing mechanism and a rejection guard).
- [ ] Record the clamp in `TrainingHistory` provenance so a clamped run is not
      mistaken for a full one.

**4. Validation plan.**
- Unit: `None` (default) → materialized validation rows byte-identical to
  today.
- Unit: ceiling above the natural size → no clamp.
- Unit: ceiling below → exactly `N` rows, and the clamp is recorded.
- Negative: `0` / negative → schema rejection at startup, before spend.
- Unit: interaction with `validation_max_portion` → the tighter wins,
  asserted both ways.
- Backward-compat: CLI `--help` diff is exactly one new flag.
- Gate: covered by C7's Gate 2.

**5. Acceptance criteria.**
- [ ] Default `None` → validation row count and the resulting
      `validation_samples` are identical to a pre-change run on the same input.
- [ ] With the ceiling, `validation_samples == min(natural, ceiling)` exactly.
- [ ] The clamp is visible in persisted provenance; a clamped run is
      distinguishable from an unclamped one.
- [ ] `--help` gains exactly one line; every other byte unchanged.
- [ ] Schema refuses `0` and negatives with a message naming the field.

**6. Failure and edge cases.** Ceiling below one batch → at least one batch or
an explicit refusal (decide from source; never silently zero). Ceiling set
without the watchdog → legal, independent of it, unlike
`validation_max_phase_seconds`. Ceiling on a run with no validation → inert.

**7. Verification commands and evidence.**
```bash
pytest tests/unit/agent/tune_ml_hyperparam_agent/ -k "validation or cli" -q
pytest tests/unit/execute_tools/ -k "train_engine or sample_set" -q
```
- [ ] counts / wall time / rc recorded in §17; `--help` diff recorded.

**8. Commit boundary.** One operator-surface field. No deadline math.

---

### C7 — Checkpoint B rung, Checkpoint D reachability, docs, and Gate 2

**1. Goal.** Prove the measurement axis is genuinely task-derived (not merely
refactored), complete the mutation/reachability set, synchronize the operator
surface, and run the one bounded Gate 2 at the final executable head.

**2. Scope.** New rung test (B-07c-1); Checkpoint D mutations not already
committed; example packs; node `.md`; `docs/running_chain_test.md`; this
document's §17 ledger. Depends on C1–C6.

**3. Implementation plan.**
- [ ] Build B-07c-1 on the EXISTING Step-02 3-file contrast profile fixture
      (4.8-B geometry) — reused, not re-created.
- [ ] Assert in ONE test that a non-int8 / other-channel declaration changes
      the **bytes** while identity keys and comparability stay byte-stable, so
      the axis is provably single.
- [ ] Add the delete-the-hop mutation (builder ignores the profile → RED).
- [ ] Add reachability: worker AND probe path both call the one builder.
- [ ] Update the node `.md` and `docs/running_chain_test.md` for
      `validation_max_samples`, quoting each flag/default against merged source
      (the doc-sync rule) — last step before merge.
- [ ] State the example obligation: measurement is not user-facing
      (roadmap §22.23.8 "why not projectable"); STATUS unchanged.
- [ ] Terminal validation from a CLEAN tree at the final executable head.
- [ ] **Request operator approval, then run the ONE bounded Gate 2.**

**4. Validation plan.**
- Unit: B-07c-1 as above.
- Mutation: each Checkpoint D row, with hygiene (caches cleared, exactly one
  target site, baseline re-run).
- Terminal: full unit suite once, clean tree, CI-exact invocation.
- Static: `ruff check`, `ruff format --check`; pyright via exact-head CI
  (local Node 10.19 cannot run it — verified this session, not assumed).
- **Gate 2 (bounded, operator-approved, listed separately and NOT launched
  without approval)** — per the standard's canonical command and the
  Q-07c-7 watchdog posture.

**5. Acceptance criteria.**
- [ ] B-07c-1 RED when the builder ignores the profile; GREEN otherwise; and
      the identity keys asserted byte-stable in the same test.
- [ ] Every Checkpoint D mutation recorded RED with its proof.
- [ ] Full unit suite green from a clean tree at the final executable head,
      counts/skips/wall time recorded from the LOG file.
- [ ] Every documented flag and default quoted against merged source.
- [ ] Gate 2 PASS on the standard's functional criteria, with the workspace,
      tested SHA, wall time and cost recorded — or a recorded FAIL with
      diagnosis and no reroll without a substantive in-scope fix.
- [ ] Exact-head CI SUCCESS at the final PR head.

**6. Failure and edge cases.** Gate 2 killed by the watchdog inside validation
→ that is the 07a symptom; if it recurs AFTER C5, C5 is wrong and this is a
STOP, not a reroll. Gate 2 unavailable (no GPU / no dataset) → record as not
run; never claim it passed. Any executable change after Gate 2 invalidates it.

**7. Verification commands and evidence.**
```bash
pytest tests/unit/ -m "not real_run" -q      # terminal, clean tree
ruff check . && ruff format --check .
# Gate 2: canonical command from docs/gates/gate_testing_standard.md,
#         re-read and re-audited from source immediately before launch.
```
- [ ] all counts / wall times / SHAs recorded in §17.

**8. Commit boundary.** Rung + mutations + docs + Gate evidence. Any post-Gate
executable fix gets its own narrowly named commit, never hidden here.

---

## 16. Open questions (operator disposition required)

**Q-07c-1 — `load_probe_batch`: delete or shim? (BLOCKING, small)**
`execute_tools/probe_data.py` is the unbounded loader whose only production
caller is `probe_production.py:222`. Once C2 routes that to the bounded
builder, nothing production calls it. Delete it, or keep a shim? *Preference:
delete — the module docstring in `gpu_measurement_data.py` argues the
unbounded path must not remain reachable.*

**Q-07c-2 — which file does the builder open? (BLOCKING)**
Both loaders do `sorted(glob("abra_training_*.h5"))[0]`. The profile declares
`training_file_name(file_index)` and `num_files`, with **no glob helper**
(§0.5). Options: (a) enumerate declared indices and take the first that
exists; (b) add a `training_file_glob()` to `DatasetConfig`; (c) take the
lowest declared index unconditionally and fail if absent. These differ when
file 0 is absent — e.g. under a partial `--data_scope`, where today's glob
silently picks a different file. Byte-identity (Checkpoint A) requires
choosing the option that opens the same file on the Gate fixture, and the
divergence must be stated rather than discovered.

**Q-07c-3 — the second model-name branch, and the guard's scope (BLOCKING;
NOT anticipated by the parent)**
`gpu_measurement_worker_main.py:235` (`if model_type == "fcnet"` for
constructor arity) is a second name branch the parent's §2.4 does not name.
The parent also requires extending `test_no_model_name_branches.py`'s scan
targets to `core/runtime_control/`. Two facts collide: pointing the guard at
the *directory* fails on `campaign.py`'s legitimate `"family": "wavenet"`
campaign config (data, not a branch), and pointing it at the *worker file*
fails on `:235` unless that branch is also fixed. Options: (a) fix `:235` too
by promoting `training_skill/estimator.py:295-321`'s signature introspection
to a shared authority — correct, but widens 07c; (b) scan the worker file and
fix `:235` inline without a shared authority; (c) scan only the dtype-bearing
lines and leave `:235` as declared debt. *Preference: (a), if the operator
accepts the widening; otherwise (c) with the debt recorded.*

**Q-07c-4 — is validation a new `RuntimePhase`? (BLOCKING)**
Evidence for yes: `phases.py:6-11` says new phases extend the vocabulary
without changing the framework; `calibration_key` embeds `phase=` so existing
keys are untouched; `records.py:575` is `p in components`-guarded; and
critically, `_watchdog_deadline_provider` already sums **every**
measurement-backed component prediction, so a validation component is priced
with **zero change to the deadline arithmetic**. Evidence for caution:
`MeasurementIdentity.phase` is an identity dimension, so validation becomes a
measurement identity too, and 59 references mention the vocabulary.
*Preference: yes — it is the option that changes the least code.*

**Q-07c-5 — where does the FIRST `T̂_val` come from? (BLOCKING)**
C8d (`sandbox_executor.py:460-467`) admits only measurement-backed sources
into a kill deadline, so a static prior is inert. 07a's evidence lands in the
trainer payload, not the observation store. Options: (a) measure the first
validation batch in-subprocess and predict the rest — mirrors RT2's
"verification = the first production steps", and is measurement-backed;
(b) route 07a's persisted per-epoch evidence into the store and accept that
attempt 1 of a fresh candidate is unpriced; (c) both. **Under (b) alone the
07a Gate-2 failure can still recur on a cold start** — this must be stated in
the PR, not discovered in a Gate. *Preference: (a).*

**Q-07c-6 — does 07c change ADMISSION, or only the watchdog? (BLOCKING)**
Parent §8.4 says "the watchdog / admission / prediction know". Pricing
validation in admission means attempts previously admitted may now be
rejected — a production behavioural change needing its own evidence and, by
the repository's rules, its own operator decision. Options: (a) deadline +
prediction only, admission unchanged, admission deferred with a named owner;
(b) all three in 07c, with enumerated verdict changes. *Preference: (a) —
it fixes the observed failure while keeping the behavioural surface reviewable.*

**Q-07c-7 — Gate 2 posture for a watchdog fix (BLOCKING)**
The current standard permits omitting `--runtime_watchdog` (paired with
omitting `--validation_max_phase_seconds`). But 07c exists to fix watchdog
accounting, and a Gate that omits the watchdog cannot demonstrate the fix.
Options: (a) run Gate 2 **with** `--runtime_watchdog` and no
`--validation_max_phase_seconds`, so the deadline comes from the priced
prediction — the honest demonstration; (b) two bounded Gate 2 runs
(with/without) — exceeds "one bounded Gate"; (c) standard posture, and prove
the fix by deterministic replay only. *Preference: (a), as a single bounded
run.* This needs an explicit decision because it is a deviation from the
standard's default Gate shape.

**Q-07c-8 — the measurement site's dtype preference (BLOCKING, small)**
Today the worker feeds `int32` (or `float32` for fcnet) in **both** training
and inference phases (`:287`). `execute_tools/model_input_dtype.py:70-77`
declares `TRAINING_SITE_DTYPE="int32"` and `INFERENCE_SITE_DTYPE="int64"`.
Adopting the phase-correct preference would make measurement match production
inference — and would change the measured tensor, i.e. break Checkpoint A's
byte-identity and shift every stored observation value under an unchanged key
(§0.6). *Preference: declare a MEASUREMENT site preference of `"int32"`,
preserving today's bytes exactly, and record the training/inference divergence
as a separate finding for the runtime-control owner.*

---

## 17. Implementation ledger

*(empty — filled per commit, immediately after each implementation and test
checkpoint, per the incremental-doc rule. Every `[ ]` above becomes `[x]` only
with recorded evidence: exact command, counts, wall time, return code. A test
that could not be run is recorded as not run, with the reason, and never
claimed as passed.)*
