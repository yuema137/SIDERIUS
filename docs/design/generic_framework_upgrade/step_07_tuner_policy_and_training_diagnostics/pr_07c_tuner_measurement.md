# Step 07 — PR 07c: Measurement / verification data feeding, and pricing the validation pass

**STATUS — FROZEN — Revision 3. Operator approved 2026-08-17.**

| | |
|---|---|
| Freeze | **FROZEN — Revision 3**, operator approved **2026-08-17** |
| Source-audit base | **`ad176036`** (master, clean tree) — every file:line in §0 was read at this SHA |
| Open questions | **Q-07c-1 … Q-07c-9 ALL CLOSED.** None blocks implementation |
| Code written | **none.** This document is design only |

> The freeze covers the scope, the commit decomposition, the acceptance
> criteria, the three-track validation matrix (§2a), the typed-contract
> inventory (§2.2a), the Gate dispositions (§4) and the stop conditions (§5).
> §17 stays LIVE as the implementation ledger. A change to anything else
> needs a new operator decision, recorded the way the rev-1 → rev-3 review
> trail is recorded here.
>
> Applied before the freeze, consistency-only (operator finalizer,
> 2026-08-17): stale open-option wording removed for the dispositioned
> questions · C6's file scope and commit boundary synchronized with the
> `TrainingHistory` field · the typed/serialized contract inventory corrected
> from "the only two" to all four deltas · "record schemas unchanged"
> replaced by the precise `ExperimentRecord`/`HyperparamTuningOutput`
> invariant · C7's INCONCLUSIVE handling split by cause, with relaunch
> authorization left to the operator. **No semantic or architectural change.**

> **Revision 3 (2026-08-17)** applies the operator's final targeted revision:
> **Q-07c-6 = B** (runtime prediction + watchdog only; admission-side pricing
> formally deferred with a parent correction note, NOT bound to D14) ·
> **Q-07c-9 = (ii)** (an explicit additive `TrainingHistory` field;
> `comparability` is NOT overloaded, and rev 2's claim that it is the right
> home for cross-round scope differences is **RETRACTED** with source
> evidence) · **C6's envelope matrix corrected** — the three landed flags are
> not one dimension, so "tighter wins" was wrong for two of them ·
> **Gate 2's counterfactual now uses EFFECTIVE provider deadlines**, with the
> floor-masking case classified INCONCLUSIVE.
>
> Three-track coverage (§2a), the cold-start temporal test and Q-07c-1..5/7/8
> are CLOSED by the operator and unchanged here.

> **Revision 2 (2026-08-17)** applies the operator's review of revision 1
> (*APPROVE WITH TARGETED REVISION — NOT YET FREEZE*): the five blockers
> (§2a three-track progressive validation matrix · Q-07c-5 → BOTH plus the
> cold-start temporal test · Q-07c-6 parent reconciliation · a
> counterfactual-**discriminative** Gate 2 · C6's sample-identity /
> partial-batch / all-envelope coverage with source-grounded provenance) and
> the four targeted corrections (C1 fixture SKIP→FAIL · C2 bounded-read vs
> peak-RSS wording · Gate-1 schema wording · the open-question count).
> At rev 2 the eight rev-1 questions carried an operator disposition and
> Q-07c-9 was added; §16 records **three revision-2 findings that changed the
> plan**, each with source evidence. (All nine were CLOSED at rev 3.)

| | |
|---|---|
| Parent | [`../step_07_tuner_policy_and_training_diagnostics.md`](../step_07_tuner_policy_and_training_diagnostics.md) — §2.4 (the seam), §8.4 (this PR's frozen contract + the ADDED scope), §9, §11 |
| Position | PR0 ✔ → 07a ✔ → 07b ✔ → trial/formal-identity correction ✔ → **07c** (last of Step 07) |
| Source audit base | `ad176036` (master, clean tree, 2026-08-17) |
| Prerequisites | all merged: PR0 `79403b44` · 07a `65804b3d` · 07b `9ea3755f` · correction `a15d1366` |
| Gates | Gate 1 **NOT REQUIRED** · Gate 2 **REQUIRED, bounded, once at the final executable head** (parent §11 row 07c) |
| Open questions | **§16 — ALL NINE dispositioned and CLOSED as of rev 3.** None blocks freeze |

> **Reviewer's shortcut.** If you read only three sections, read **§2a** (the
> three-track validation matrix, new in rev 2), **§16** (dispositions + the
> three rev-2 findings) and **§8** (the per-commit checklists). §0 is the
> evidence everything else stands on.

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
| `execute_tools/probe_data.py` | **DELETE** `load_probe_batch` (Q-07c-1 = DELETE; no production shim) | C2 |
| `core/runtime_control/probe_production.py` | call the one builder; capability-routed dir | C2, C4 |
| `core/runtime_control/gpu_measurement_worker_main.py` | contract-derived dtype (`:287`) **and** constructor arity (`:235`) — both eliminated (Q-07c-3 = (a)) | C3 |
| `core/runtime_control/gpu_measurement_spec.py` | contract transport field | C3 |
| `core/runtime_control/bootstrap.py` | `_dataset_check` + remedy via capability | C4 |
| `core/sandbox_executor.py` | the `T̂_val` term | C5 |
| `core/runtime_control/phases.py`, `session.py` | `RuntimePhase` gains `"validation"`; the phase component (Q-07c-4 = YES) | C5 |
| `execute_tools/train_engine_sandbox.py` | route 07a's validation evidence into the session | C5 |
| `agent/schemas/hyperparam_tuning.py`, `nodes/ml_hyperparameter_tune_agent/cli.py` | `validation_max_samples` | C6 |
| `execute_tools/training_history.py` | `validation_requested_samples_before_limit` (Q-07c-9 = (ii)) | C6 |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`, `docs/running_chain_test.md` | operator surface | C6, C7 |
| `tests/unit/core/test_gpu_measurement_data.py` + new test modules | oracles and rungs | C1–C7 |

### 2.2 Non-goals (must remain unchanged)

- The `seg=40000 / batch=1` coordinated triple stays **framework-owned**
  (`gpu_measurement_identity.py:214-215`, `gpu_measurement_worker_main.py:254,266`,
  `probe_production.py:220-221`). 07c may centralize it; the values and the
  identity hashes do not move, and it never becomes task config.
- `MeasurementIdentity.components()`, `candidate_config_hash`, the planned and
  inference workload hashes, `calibration_key`, the `data_shape_class` string.
- The bounded-READ property.
- RT **admission** verdicts, verification, timeout and signal behaviour —
  ALL unchanged (Q-07c-6 = B). 07c changes the runtime PREDICTION and the
  watchdog DEADLINE only.
- 07a's training ACTUAL stays validation-EXCLUSIVE. The fix is one layer up.
- Planner exposure and production defaults: every new field defaults to
  parity-preserving `None`. `validation_max_samples` is an operator/runtime
  input, never planner-visible (§4).
- **Pets / DAVIS execution maturity.** §2a.2's obligations read only their
  DECLARED artifacts. No dataset adapter, no `DatasetProfile`, no download,
  no `STATUS.md` change. That is D14.
- 07a's exact-validation-scope invariant (`validation_samples ==
  validation_requested_samples`) is never relaxed; C6 clamps the REQUESTED
  scope instead.
- `TrainingHistory.comparability` / `comparability_reason` semantics are
  unchanged — they own R2-vs-R3 computation comparability and are not
  widened to cross-round scope (§16 retraction).
- **Pre-run ADMISSION pricing of validation is explicitly NOT owned by 07c**
  (Q-07c-6 = B); it is OPEN runtime-control debt, not bound to D14.

### 2.2a Typed / serialized contract deltas — the COMPLETE inventory

Rev 3's "the only two schema changes" was too narrow: it counted the two
Pydantic *field* additions and omitted two other typed/serialized contract
deltas the design already requires. All four, in one place:

| Commit | Contract | Delta | Character |
|---|---|---|---|
| C3 | `GpuMeasurementSpec` | gains an **optional** `ModelIOContract` transport field | runtime-only; **backward-compatible** — a spec serialized before 07c still validates (C3 acceptance) |
| C5 | `RuntimePhase` / `RUNTIME_PHASES` | gains the vocabulary member `"validation"` | creates a NEW phase namespace; every existing phase identity, `calibration_key` and store key is unchanged (C5 acceptance) |
| C6 | `HyperparamTuningInput` | `validation_max_samples: int \| None = None` | operator/runtime input; default preserves parity |
| C6 | `TrainingHistory` | `validation_requested_samples_before_limit: int \| None = None` | additive scope provenance (Q-07c-9 = (ii)) |

**None of the four is LLM-facing.** Evidence, not assertion: the planner drops
the whole `training_history` record key (`agent/prompts.py:944-946` —
`_PLANNER_HIDDEN_RECORD_KEYS` is a top-level key set, so inner fields cannot
leak); `llm_bridge.reflect()` takes `training_diagnosis` only
(`agent/llm_bridge.py:1009,1062`); `GpuMeasurementSpec` and `RuntimePhase` are
runtime-control internals that never cross an LLM boundary; and
`validation_max_samples` is an operator input, never rendered into a prompt.
PB-1/PB-2 and WF-1/WF-2 byte-parity is the standing evidence (C6 validation).
- The measurement path's file selection is scope-unaware today (it globs and
  takes the first). 07c preserves that; making measurement DataScope-aware is
  not in this PR.
- Prompts, PB/WF surfaces, `MetricOrder`, HealthGate.
- **Persisted record surfaces** — `ExperimentRecord`
  (`agent/schemas/hyperparam_tuning.py:298`) existing fields and
  `HyperparamTuningOutput` are **unchanged**, matching the parent §9 row's
  wording ("`ExperimentRecord` existing fields; `HyperparamTuningOutput` —
  unchanged; additive only"). The ONE persisted delta is the additive
  `TrainingHistory.validation_requested_samples_before_limit` declared in
  §2.2a. A blanket "record schemas unchanged" would contradict that field, so
  it is stated as the precise invariant instead:

  > every persisted record surface is unchanged except the explicitly
  > declared additive `TrainingHistory` field.
- `resolved_action` (parent §17.1).

### 2.3 Dependencies

C2 → C1. C3 → C2. C4 independent of C2/C3 but sequenced after for review
clarity. C5 independent of C2–C4 (different subsystem). C6 → C5. C7 → all.

---

## 2a. Three-track progressive validation matrix (NEW in rev 2 — operator blocker 1)

Revision 1 validated on TIDMAD (production) plus the Step-02 synthetic
contrast profile (atomic axis) and mentioned neither persistent track. That
is a gap against the persistent-track philosophy: a synthetic 3-file fixture
proves the builder *reads* the profile; it does not prove the abstraction
holds for data that is not TIDMAD-shaped.

**07c does NOT run Pets or DAVIS end to end.** That is D14. What 07c does is
extend them to *exactly the seam this PR touches* — the rule being "the
persistent tracks are tested as far as the refactor has reached, and no
further".

```text
        ┌────────────────────────────────────────────┐
        │ LAYER 1 — atomic single-axis isolation     │
        │ Step-02 3-file contrast profile (4.8-B)    │
        │ one axis moves → bytes move                │
        │ builder ignores profile → RED              │
        └───────────────────┬────────────────────────┘
                            ▼
        ┌────────────────────────────────────────────┐
        │ LAYER 2 — persistent three-track breadth   │
        │ TIDMAD → executable measurement            │
        │ Pets   → current-maturity capability       │
        │ DAVIS  → current-maturity capability       │
        │ no invented D14 execution                  │
        └───────────────────┬────────────────────────┘
                            ▼
        ┌────────────────────────────────────────────┐
        │ LAYER 3 — real production execution        │
        │ TIDMAD Gate 2, watchdog ON,                │
        │ counterfactual-discriminative              │
        └────────────────────────────────────────────┘
```

### 2a.1 What each track is tested to, and why that is its ceiling

Audited maturity at this base (`ls examples/*/declared/`):

| Track | Landed artifacts | Has a `DatasetProfile`? |
|---|---|---|
| TIDMAD | full production path, `examples/tidmad/resolved/` | **yes** — the shipped `TIDMAD` profile |
| Oxford-IIIT Pet | `declared/model_io_contract.json`, three metric declarations, L1 fixtures | **no** |
| DAVIS | `declared/model_io_contract.json`, three metric declarations, L1 fixtures | **no** |

That table decides the matrix. A commit whose input is a `DatasetProfile`
cannot be exercised by Pets/DAVIS without inventing one — which §22.23
forbids. A commit whose input is a `ModelIOContract` **can** be, today,
because both tracks have declared one.

| Commit | Its task-derived input | TIDMAD | Pets | DAVIS |
|---|---|---|---|---|
| C2 builder | `DatasetProfile` | byte parity, real profile | — *(no profile until D14)* | — *(no profile until D14)* |
| C2 axis | contrast profile | Layer-1 fixture | — | — |
| **C3 dtype** | **`ModelIOContract`** | byte parity | **REQUIRED — declared contract resolves a dtype** | **REQUIRED — declared contract resolves a dtype** |
| **C4 capability** | task capability resolver | available | **REQUIRED — explicit unavailability** | **REQUIRED — explicit unavailability** |
| C5/C6 validation pricing | runtime evidence, task-agnostic | full | — *(no execution)* | — *(no execution)* |
| C7 Gate 2 | real execution | **PASS required** | — | — |

### 2a.2 The Pets / DAVIS obligation, stated exactly

**C3 (breadth of the dtype authority).** Load
`examples/{oxford_iiit_pet,davis_future_prediction}/declared/model_io_contract.json`,
pass each to `resolve_input_dtype`, and assert the resolved concrete dtype is
the one the contract's declared admissibility implies — **not** TIDMAD's.
DAVIS is the valuable case: RGB `[C,T,H,W]` float, the furthest thing from
int8 ADC codes. If the dtype path has a hidden TIDMAD assumption, this is
where it shows. No data is read and no model is built.

**C4 (breadth of capability resolution).** For each track, resolve the
measurement capability and assert the honest current answer:

```text
ResolvedMeasurementCapability(
    task_identity        = <the track's own identity>,
    probe_available      = False,          # correct before D14
    unavailability_reason = <task-owned, non-empty, names the task>,
)
```

**An explicit `False` with a task-owned reason is a PASS, not a gap.** The
failure this catches is the one `measurement_capability.py:1-30` was written
for: generic infrastructure deciding availability from a TIDMAD-specific
fallback and going quiet. The assertion is on the *reason*, never on the
boolean alone.

**Forbidden in 07c**: fabricating a JPEG/video dataset adapter, inventing a
`DatasetProfile` for either track, or downloading data. If a test needs any
of those, it belongs to D14 and is out of scope.

---

## 3. Checkpoints (parent §8.4, item by item)

| Checkpoint | Content | Commit |
|---|---|---|
| **0** | extend `test_gpu_measurement_data.py`'s byte-identity oracle to the new builder; verify the PR-G identity/hash/key pins green BEFORE editing | C1 |
| **A** | batches byte-identical under TIDMAD; identity components, `candidate_config_hash`, planned + inference workload hashes, `calibration_key`, `data_shape_class` exact string unchanged; store readable unchanged; RT admission/verification unchanged | C2–C4 |
| **B** | **B-07c-1** — Step-02 3-file contrast profile (4.8-B geometry) with a non-int8 / other-channel declaration → **different bytes**, while identity keys and comparability stay byte-stable, asserted in ONE test so the axis is provably single. **Rev 2: this is Layer 1 only.** Layer 2 (persistent three-track breadth — Pets/DAVIS at current maturity) is added by §2a and lands in C3 + C4 | C3, C4, C7 |
| **C** | production pre-phase measurement builds its batch from the profile in a real run — **Gate 2, bounded, watchdog ON, and counterfactual-discriminative (§4.1)** | C7 |
| **D** | delete-the-hop (builder ignores the profile → contrast rung RED); dtype-branch reintroduction → guard RED; `TIDMAD_DATA_DIR` import inside `core/runtime_control/` → guard RED; reachability: worker AND probe path both call the one builder | C2–C4, C7 |

---

## 4. Gates

Quoted from `docs/gates/gate_testing_standard.md` at this base, decided
separately (roadmap §17.0).

**Gate 1 — NOT REQUIRED.** 07c **does** change typed contracts — four of
them, inventoried in §2.2a. The standard's trigger is an **LLM-facing**
prompt or schema, and none of the four is one. Rev 1's "07c changes neither
prompt nor schema" was literally false; rev 3's "an operator/runtime Pydantic
schema" was true but incomplete. The frozen wording is:

> 07c changes runtime/operator typed contracts — `GpuMeasurementSpec`,
> `RuntimePhase`, `HyperparamTuningInput`, `TrainingHistory` — but no
> LLM-facing prompt or schema, and no prompt byte.

Evidenced, not asserted: §2.2a's per-contract evidence, plus the existing
PB-1/PB-2 and WF-1/WF-2 goldens remaining byte-identical (C6 acceptance).
**Flip condition**: any of the four becomes planner- or reflector-visible, or
any prompt byte moves.

**Gate 2 — REQUIRED, bounded, once, at the final executable head.** Table row
*"Checkpoint (end of feature) | Gate 2"*, and §17 names §7e among the modules
that change real execution behaviour. The measurement **is** real execution:
no pseudo path exercises a profile-built batch on a device. Corpus: TIDMAD.

### 4.1 Gate 2 must be DISCRIMINATIVE, not merely green (rev 2 — operator blocker 4)

Rev 1's PASS criterion was the standard's functional one: the real path
executed and admission was reached from a profile-built batch. **For a PR
whose purpose is fixing watchdog accounting that is not sufficient** — a run
where the model simply happened to be fast would pass it even if C5 were
entirely absent.

Gate 2 must therefore establish the counterfactual, computed from artifacts
the run already persists:

**The counterfactual must use EFFECTIVE provider deadlines, not raw sums
(rev-3 correction).** `_watchdog_deadline_provider` does not return
`Σ predictions × factor`; it returns

```python
deadline, source = min(candidates)                       # operator_budget,
                                                         # validation_max_phase,
                                                         # verified_components
return max(deadline, policy.watchdog.floor_seconds), source
```

so a raw sum can differ from what would actually have been enforced. Compute
the counterfactual **through the provider's own resolution**:

```text
D_old_eff = provider(sidecar WITHOUT the validation component)   ← what pre-07c would enforce
D_new_eff = provider(sidecar WITH the validation component)      ← what 07c enforces
T_act     = training actual + Σ validation_seconds               ← what the phase really cost

PASS requires BOTH:
    D_old_eff  <  T_act        the old deadline WOULD have killed it
    T_act      ≤  D_new_eff    the new deadline did not
```

**Plus a masking check, or the counterfactual proves nothing.** Assert
`source == "verified_components"` for `D_new_eff`, and confirm that no other
candidate is doing the work:

| Masking case | Verdict |
|---|---|
| `--validation_max_phase_seconds` present | excluded by construction (Q-07c-7 omits it) |
| `operator_budget` is the `min()` winner | **INCONCLUSIVE** — the validation term never bound |
| `watchdog.floor_seconds > T_act` | **INCONCLUSIVE** — the floor alone would have saved the pre-07c code, so the run says nothing about the fix |

`T_act` and the component predictions are recomputable from the persisted
`runtime_verification` sidecar (component predictions + `record_phase_actual`)
and 07a's `TrainingHistory.validation_seconds` — verified present at this
base, so **no new recording is required**; `D_old_eff` / `D_new_eff` are
obtained by replaying the real provider over that sidecar with and without the
validation component.

**The C6 trap, stated explicitly.** `validation_max_samples` can make the
Gate self-defeating: clamp validation hard enough and `D_old_eff ≥ T_act`, so the
Gate passes with C5 reverted. The Gate's bounded validation workload must
stay large enough that the recorded `D_old_eff` **would have been insufficient**.
This does not require burning wall time — it requires that `N_val` not be
clamped below the point where the counterfactual separates. If the run
produces `D_old_eff ≥ T_act` **for this reason**, the Gate is
**INCONCLUSIVE, not PASS**, and a larger bounded validation workload is the
relevant correction. The two masking rows above are a DIFFERENT cause with a
DIFFERENT correction — a Gate posture change, permitted only by the current
standard — and increasing `N_val` does not necessarily fix them. C7's
acceptance tabulates all three causes separately; every inconclusive live
attempt is preserved, and a relaunch needs fresh operator authorization
rather than being folded into the one budgeted run.

Functional criteria from the standard still apply on top (chain exits 0, real
candidate registered, real training/inference/scoring executed, finite score,
`gate_action` recorded). Posture: watchdog **ON**, `--validation_max_phase_seconds`
**omitted** (Q-07c-7 = (a)) — so the enforced deadline is the priced prediction
rather than a flat fuse that would mask it.

**Not launched without operator approval.** No live Gate at design time, none
before C7.


---

## 5. Stop conditions

Parent §8.4's, plus what the audit adds:

- any identity hash or store key would change;
- the bounded-READ property cannot be kept;
- a batch fact is not derivable from profile + contract;
- **promoting the constructor introspection to a shared owner pulls a large
  API refactor** (Q-07c-3 — the operator's explicit STOP);
- **a validation fix turns out to require changing ADMISSION** — Q-07c-6 = B
  scopes admission OUT; a changed admission verdict is a defect, not a
  deliverable;
- `RuntimePhase` extension would change an existing store key or identity;
- the validation term cannot become measurement-backed, so C8d leaves it
  inert and the fix is cosmetic;
- **the cold-start temporal test cannot be satisfied** — the refreshed
  deadline is not visible before the stale training-only one fires;
- the clamp cannot be applied to the REQUESTED scope, so 07a's
  exact-materialization invariant would have to be relaxed (never relax it —
  that guard is 07a's frozen contract);
- recording the clamp would require widening `comparability` or any other
  landed 07a field beyond its declared ownership (§16 retraction);
- **Gate 2 cannot be made discriminative** within the bounded envelope
  (`D_old_eff ≥ T_act` however the validation workload is sized, or the floor/operator budget masks the term);
- a Pets/DAVIS obligation in §2a.2 would require inventing a
  `DatasetProfile`, a dataset adapter, or downloading data — that is D14.

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
- [x] Read `test_gpu_measurement_data.py` in full and record what its existing
      byte-identity oracle compares and on which HDF5 fixture. — it compares
      the two loaders **to each other**, never to a frozen value; §17 records
      the geometry.
- [x] Record the fixture's provenance and geometry; confirm it is committed and
      machine-independent (CLAUDE.md portability rule). — **finding: it is
      GENERATED, not committed**; see §17's C1 audit finding.
- [x] Extend the oracle to a builder-shaped seam that does not exist yet, so
      C2 wires into it rather than inventing a second comparison. —
      `PROBE_BATCH_PRODUCERS`.
- [x] Enumerate the PR-G identity/hash/key pins by test id (`MeasurementIdentity`
      components, `candidate_config_hash`, planned + inference workload hashes,
      `calibration_key`, `data_shape_class`) and record each test's file:line.
      — §17's pin table; 107 passed / 2 pre-existing skips.
- [x] Capture the batch bytes (sha256 of the tensor buffer), the opened
      filename, dtype and shape as a committed golden with `_captured_at`
      naming this base SHA. — `GOLDEN_CAPTURED_AT = "0b92fac9…"`.

**4. Validation plan.**
- Unit: the extended oracle passes against the CURRENT two loaders.
- Negative: mutate the fixture's first segment → the golden fails (proves the
  oracle is not vacuous).
- Backward-compat: the enumerated pins run and pass unmodified.
- Integration/pseudo: none. Gate: none.

**5. Acceptance criteria.**
- [x] `load_probe_batch` and `load_bounded_probe_batch` produce tensors whose
      sha256, dtype (`int64`) and shape are equal to each other and to the
      committed golden.
- [x] The golden records the exact opened filename.
- [x] Every enumerated pin test passes, listed by id with counts.
- [x] Deliberately corrupting one fixture byte turns the oracle RED (recorded).

**6. Failure and edge cases.** Fixture absent → **FAIL with a named message**
(corrected in rev 2; rev 1 said SKIP). This is the Checkpoint-0 byte oracle
and the fixture is committed and machine-independent, so its absence means the
oracle is not running — and a skipped oracle would let every later commit
report green with the one measurement that matters missing. SKIP is reserved
for genuinely external, non-portable resources (a GPU, the real dataset);
a committed fixture is neither. Fixture too small for `batch×seg` → the
existing `RuntimeError` path is asserted, not worked around.

**7. Verification commands and evidence.**
```bash
pytest tests/unit/core/test_gpu_measurement_data.py -q
pytest <enumerated PR-G pin tests> -q
```
- [x] counts / wall time recorded in §17.
- [x] anything unrunnable recorded with the reason; never claimed as passed. —
      nothing was unrunnable; the 2 skips are pre-existing and named.

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
- [ ] **The bounded-READ property is preserved** (renamed in rev 2; rev 1
      called this "peak host RSS stays bounded", which `bytes_read` does not
      prove — a small read says the materialized HDF5 data is bounded, not
      that process RSS is). Asserted as: `bytes_read == batch_size ×
      segment_length × itemsize` **exactly**, `bytes_read ≪ file_sample_count`
      with the ratio recorded, and no `np.array(channel)`-shaped whole-channel
      materialization anywhere in the builder (source assertion). A real peak-RSS
      measurement would need a subprocess and is deliberately not used: it is
      not portable, and the exact-slice assertion is the stronger, cheaper
      statement about this seam.
- [ ] `grep -rn "channel0001\|channel0002\|abra_training_\|+ 128" core/runtime_control/ execute_tools/probe_*.py` returns nothing in live code.
- [ ] Exactly one builder is called by both paths (reachability test named).
- [ ] All PR-G pins green.

**6. Failure and edge cases.**

| Case | Behaviour |
|---|---|
| profile channel absent in the HDF5 | STOP — typed `RuntimeError`, never fall back |
| declared file index missing on disk | Q-07c-2 = (a): walk the declared indices in order and take the FIRST that exists; never substitute an undeclared file found on disk |
| duplicate / ambiguous filename match | deterministic, documented choice; recorded in evidence |
| `data_dir` unreadable | existing explicit failure (C4 makes the reason task-owned) |
| dataset smaller than `batch×seg` | existing `RuntimeError` preserved |
| legacy caller with no profile | REFUSED (Q-07c-1 = DELETE — there is no shim to fall through to); never an implicit TIDMAD default |
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

**2. Scope.** `gpu_measurement_worker_main.py:287` **and** `:235` (Q-07c-3 =
(a) — both branches go); `gpu_measurement_spec.py` (contract transport field);
the worker's argv/spec serialization; the shared introspection owner promoted
from `agent/skills/training_skill/estimator.py:295-321`;
`tests/.../test_no_model_name_branches.py` (scan targets).
Non-goals: changing `resolve_input_dtype` itself; adopting phase-correct
inference dtype (**Q-07c-8**). Depends on C2.

**3. Implementation plan.**
- [ ] Record the CURRENT dtype the worker feeds for every builtin, per phase,
      as a table (the A6-style matrix) — this is the parity target.
- [ ] Add the contract field to `GpuMeasurementSpec` (optional, default `None`
      = Regime-A) and thread it through spec construction and worker parse.
- [ ] Replace `:287` with `resolve_input_dtype(model_type, contract,
      site_preference="int32")` — the MEASUREMENT site preference
      (Q-07c-8), which reproduces today's bytes exactly.
- [ ] Eliminate `:235` too (Q-07c-3 DISPOSED: (a)) — promote the signature
      introspection at `agent/skills/training_skill/estimator.py:295-321` to a
      shared owner and call it here. **Not** an inline copy, and **not**
      leaving the branch behind a narrowed guard. **STOP and re-evaluate as a
      defer if promotion pulls a large API refactor** (operator's explicit
      condition).
- [ ] Extend the guard's `_SCAN_TARGETS` to the measurement files chosen in
      Q-07c-3 — **not** the whole `core/runtime_control/` directory (see the
      failure table).
- [ ] Re-run C1's oracle: bytes unchanged.

**4. Validation plan.**
- Unit: dtype matrix — every builtin × phase → the recorded pre-change dtype.
- Unit: contract present vs `None` (Regime-A) → same dtype under TIDMAD.
- **Unit (three-track breadth, §2a.2 — REQUIRED):** load Pets' and DAVIS'
  `declared/model_io_contract.json` and assert `resolve_input_dtype` returns
  the dtype each contract's declared admissibility implies, **not** TIDMAD's.
  DAVIS (RGB float, `[C,T,H,W]`) is the discriminating case. No data read, no
  model built, no execution maturity added.
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
- [ ] Pets and DAVIS contracts each resolve to their own declared dtype;
      neither resolves to TIDMAD's, and neither raises.
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
| `:235` left in place | not an option in rev 2 (Q-07c-3 = (a)); if it cannot be eliminated, STOP rather than narrow the guard around it |
| introspection promotion pulls a large refactor | STOP and re-evaluate scope — do not inline a private copy |

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
`ResolvedMeasurementCapability` the caller already holds.

**Precisely what is claimed (corrected in rev 2).** Rev 1 said "non-TIDMAD
task → measurement no longer silently disables itself — the point of the
commit". That over-claims: before D14, `probe_available=False` is still the
CORRECT answer for Pets and DAVIS. The honest claim is about *who decides and
whether they say why*:

```text
BAD  (today):   non-TIDMAD → core sees no TIDMAD_DATA_DIR → silently unavailable
GOOD (07c):     non-TIDMAD → task capability resolver
                           → available, OR explicitly unavailable
                             for a task-owned, stated reason
```

Generic runtime-control no longer decides measurement availability from a
TIDMAD-specific fallback. Availability is decided by the task-owned
`ResolvedMeasurementCapability`, whose schema already refuses
`probe_available=False` with no reason.

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
- **Unit (three-track breadth, §2a.2 — REQUIRED):** resolve the measurement
  capability for Pets and for DAVIS and assert the honest current answer —
  `probe_available=False` with a non-empty, task-owned
  `unavailability_reason` naming that task. An explicit `False` with a reason
  is a PASS. The assertion is on the REASON and the task identity, never on
  the boolean alone; asserting only `False` would pass equally for the silent
  TIDMAD fallback this commit removes.
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
| non-TIDMAD task (Pets / DAVIS, pre-D14) | `probe_available=False` is CORRECT; what changes is that a task-owned resolver says so with a reason, instead of generic code inferring it from an absent TIDMAD path |
| `data_dir` explicitly supplied | highest precedence, unchanged |

**7. Verification commands and evidence.**
```bash
pytest tests/unit/core/ -k "bootstrap or capability or probe" -q
```
- [ ] counts / wall time / rc recorded in §17.

**8. Commit boundary.** Availability plumbing only.

---

### C5 — Price the validation pass in the runtime model (ADDED SCOPE, root fix)

> **Rev 3: Q-07c-4, Q-07c-5 and Q-07c-6 are all DISPOSED** — new
> `RuntimePhase="validation"`; BOTH evidence sources; and **admission is
> explicitly NOT in scope** (Q-07c-6 = B). This commit changes the runtime
> PREDICTION and the watchdog DEADLINE only. Admission verdicts are a parity
> assertion here, not a deliverable.

**1. Goal.** Make `T̂_val` a real term so the watchdog deadline covers work the
attempt actually performs. Fixes the 07a Gate-2 finding: 3 of 4 attempts
killed inside validation; the survivor spent 9 s training and 26.45 s
validating, against a deadline built from the 9 s alone.

Separate from C6: this is the root fix; C6 is a cost envelope that does not
make the prediction correct.

**2. Scope.** `core/sandbox_executor.py:446-481`; `core/runtime_control/phases.py`
+ `session.py` (Q-07c-4 = YES); `execute_tools/train_engine_sandbox.py`
(route 07a's per-epoch evidence into the session). Non-goals: 07a's
validation-exclusive training ACTUAL; the pure per-step model; **admission
verdicts — NOT owned by 07c (Q-07c-6 = B)**. Independent of C2–C4.

**3. Implementation plan.**
- [ ] Record the pre-change deadline for a fixed synthetic sidecar as the
      parity baseline (`(deadline, source)` pairs across candidate sets).
- [ ] Add `"validation"` to `RuntimePhase` / `RUNTIME_PHASES` (Q-07c-4
      DISPOSED: yes). The deadline then sums it with **no arithmetic change**.
- [ ] **BOTH evidence sources (Q-07c-5 DISPOSED: (c)), and they are not
      redundant — they serve different runs:**
      - [ ] **first validation batch, measured in-subprocess** → a
            measurement-backed prediction that protects **THIS** run (C8d
            admits it; a static prior would be inert);
      - [ ] **full-pass actual** from 07a's `validation_seconds` /
            `validation_samples`, recorded as the phase ACTUAL + unit count so
            `realized_unit_ms = seconds ÷ samples` calibrates **FUTURE** runs.
- [ ] **Cold-start temporal wiring (rev-2 blocker 2).** Determine from source
      whether `_watchdog_deadline_provider`'s deadline is compared against
      elapsed-from-process-start or remaining-from-now
      (`sandbox_executor.py:952-953` compares `elapsed <= deadline`), and make
      the validation term obey that SAME convention. Record the convention in
      the docstring — it is currently implicit.
- [ ] Ensure the first validation batch's cost is counted **exactly once**:
      it is both the measurement and real elapsed work.
- [ ] Ensure the refreshed deadline becomes visible to the provider **before**
      the old training-only deadline would fire in the 07a failure regime.
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
- **Unit — COLD-START TEMPORAL UPDATE (rev-2 blocker 2, the invariant rev 1
  was missing).** Rev 1 proved only that a validation prediction eventually
  appears in the sidecar. That is not enough: if the term arrives late, or is
  expressed in the wrong clock convention, the process is killed by the stale
  training-only deadline before the fix can apply, and the suite is still
  green. Drive the provider across the real sequence with a controlled clock:

  ```text
  t = 0        watchdog begins, sidecar has training components only
               → deadline == the OLD training-only value  (asserted)
  training runs
  validation batch 1 completes, its measurement lands in the sidecar
               → provider refreshes
               → deadline == the expected TOTAL-allowed wall time under the
                 provider's actual clock convention  (asserted numerically)
  ```

  Three assertions, each naming a distinct defect:
  1. the updated deadline represents the intended total allowed wall time
     under the provider's real convention — catches an elapsed-vs-remaining
     mix-up;
  2. the first validation batch's cost appears **exactly once** — catches
     double-counting it as both measurement and elapsed work;
  3. the refreshed deadline is visible **strictly before** the old
     training-only deadline would have fired, replaying the 07a regime
     (9 s train / 26.45 s validate) — catches "correct but too late".
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
- [ ] **Admission verdicts unchanged for a fixed input set** — asserted as
      parity, not delivered as a feature (Q-07c-6 = B). A changed admission
      verdict is a DEFECT of this commit, not an improvement.

**6. Failure and edge cases.**

| Case | Behaviour |
|---|---|
| first attempt, no prior | covered by the first-batch measurement (Q-07c-5 = BOTH). Residual window: the run is unpriced from process start until validation batch 1 completes — **stated, not hidden**, and bounded by the temporal test above |
| deadline convention mismatch | STOP — the deadline is meaningless if elapsed and budget disagree on their origin |
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

**2. Scope.** `agent/schemas/hyperparam_tuning.py` (`validation_max_samples`),
`nodes/ml_hyperparameter_tune_agent/cli.py` (the flag),
**`execute_tools/training_history.py`
(`validation_requested_samples_before_limit`, Q-07c-9 = (ii))**, the trainer's
validation materialization, the node `.md` and `docs/running_chain_test.md`.
Non-goals: changing `validation_max_portion` / `validation_max_train_samples` /
`validation_max_phase_seconds`; any default change; any deadline math (C5's).
Depends on C5.

**3. Implementation plan.**
- [ ] Read how `validation_max_portion` and `validation_max_train_samples` are
      resolved and applied, and add the row ceiling at the SAME point.
- [ ] Add `validation_max_samples: int | None = None` with a description that
      states it bounds the VALIDATION rows, distinct from the training-row
      ceiling it will sit beside.
- [ ] Add the CLI flag, forwarded like its siblings.
- [ ] Ensure clamping, never rejection (the standard's distinction between a
      sizing mechanism and a rejection guard).
- [ ] **Clamp the REQUESTED SCOPE, never the materialized rows** — see the
      rev-2 finding below. The ceiling must apply where the validation
      SampleSet is BUILT, so `requested == materialized == min(natural,
      ceiling)`.
- [ ] Add `TrainingHistory.validation_requested_samples_before_limit`
      (Q-07c-9 = (ii)) and populate it with the pre-limit natural scope.
- [ ] Do NOT touch `comparability` / `comparability_reason` (rev-3
      retraction) — a guard test asserts the clamp leaves the stamp
      unchanged for an identical `LossConfig`.

> **REV-2 FINDING — post-materialization truncation is ILLEGAL, and
> "provenance" was an abstract bag.** Rev 1 said "record the clamp in
> `TrainingHistory` provenance" while also listing record schemas as a
> non-goal. Source-grounding that (operator correction) found something
> stronger than a wording problem:
>
> ```python
> execute_tools/training_history.py:206-211
> if self.validation_samples != self.validation_requested_samples:
>     raise ValueError(... "the declared validation scope must
>                           materialize exactly (design §3.4b)")
> ```
>
> 07a **fails closed** when requested ≠ materialized. So a ceiling applied
> *after* materialization is not merely bad provenance — it makes every
> clamped run raise. The ceiling must therefore be applied to the REQUESTED
> scope at SampleSet construction, after which `requested == materialized`
> and 07a's invariant holds untouched.
>
> **Consequence: the requested/materialized pair can no longer carry the
> clamp's provenance**, because by construction they are equal — and the
> run-level `validation_max_samples` input cannot recover it either
> (`ceiling=2000, requested=2000` is ambiguous between "did not bind" and
> "clamped from 12000"). **Q-07c-9 = (ii)**, an explicit additive field:
>
> ```python
> TrainingHistory.validation_requested_samples_before_limit: int | None = None
> ```
>
> declared as a **schema change**, not smuggled under the word "provenance".
> `validation_requested_samples` keeps meaning the EFFECTIVE requested scope,
> so `was_limited = before_limit > requested` is derivable with certainty and
> 07a's `requested == materialized` invariant is untouched.
>
> **`comparability` is NOT used for this** — see §16's retraction:
> `stamp_comparability` is a function of the resolved `LossConfig` alone and
> owns R2-vs-R3 computation comparability, not cross-round scope. Whether a
> consumer should discount cross-round comparisons whose validation scopes
> differ is consumer policy, and C6 does not decide it.

**4. Validation plan.**
- Unit: `None` (default) → materialized validation rows byte-identical to
  today.
- Unit: ceiling above the natural size → no clamp.
- Unit: ceiling below → exactly `N` rows, and the clamp is recorded.
- Negative: `0` / negative → schema rejection at startup, before spend.
- **Unit — the envelope matrix, THREE DISTINCT RELATIONSHIPS (rev 3
  correction).** Rev 2 said "for each pair, the tighter bound wins" for all
  three landed flags. That is wrong for two of them: the four controls do not
  share a dimension, and `min()` is only meaningful within one.

  | Pair | Relationship | What the test asserts |
  |---|---|---|
  | `validation_max_portion` × `validation_max_samples` | **same dimension** (validation sample scope) | `N_val = min(N_natural/portion, N_ceiling)` — tighter wins, asserted in both orders |
  | `validation_max_train_samples` × `validation_max_samples` | **ORTHOGONAL** — the first bounds TRAINING rows, the second VALIDATION rows | changing the training ceiling moves the training scope and leaves validation scope untouched; changing the validation ceiling does the converse. **No `min()` between them.** The names differ by one word and bound different sets, which is exactly why this needs a test |
  | `validation_max_phase_seconds` × `validation_max_samples` | **ORTHOGONAL, different units** — seconds vs samples | the sample ceiling determines workload size by sample-space rules; the phase fuse remains independently enforceable as a wall-clock termination. Neither is expressible in the other's units, so there is no `min()` to take |
- **Unit — WHICH samples, not just how many (rev-2 blocker 5).** 07a defines
  R3 as a real validation objective, so a clamp that silently changes *which*
  rows are evaluated changes the science:
  - same input + same config + same ceiling → **identical validation sample
    identities, in identical order** (asserted on the identities, not the
    count);
  - the objective over the clamped set equals an explicit evaluation over
    exactly those N rows.
- **Unit — partial final batch weighting (rev-2 blocker 5).** With a ceiling
  that cuts through the final batch, the epoch statistic must remain
  `sample_count_weighted_mean_of_batch_criterion` — the value 07a already
  DECLARES on `TrainingHistory.epoch_statistic`
  (`training_history.py`, a pinned `Literal`). Assert the computed R3 equals
  the sample-count-weighted expectation and **not** the unweighted
  mean-of-batch-means; those differ precisely when the last batch is partial,
  which is the case a ceiling creates.
- Unit: `requested == materialized` under every ceiling, so 07a's exact-scope
  validator never fires.
- Backward-compat: CLI `--help` diff is exactly one new flag.
- Backward-compat: PB-1/PB-2 and WF-1/WF-2 goldens byte-identical (the Gate-1
  NOT-REQUIRED evidence, §4).
- Gate: covered by C7's Gate 2 — including its discriminative requirement,
  which this commit can defeat (§4.1).

**5. Acceptance criteria.**
- [ ] Default `None` → validation row count and the resulting
      `validation_samples` are identical to a pre-change run on the same input.
- [ ] With the ceiling, `validation_samples == min(natural, ceiling)` exactly,
      **and** `validation_requested_samples == validation_samples` (07a's
      exact-materialization invariant never fires).
- [ ] The clamped validation set's sample identities and order are identical
      across repeated runs with the same config.
- [ ] R3 over a clamped set with a partial final batch equals the
      sample-count-weighted expectation, and differs from the unweighted
      mean-of-batch-means (both numbers recorded, so the test is known to
      discriminate).
- [ ] A clamped run is distinguishable from an unclamped one:
      `before_limit > requested` exactly when the ceiling bound, and
      `before_limit == requested` exactly when it did not — asserted for the
      ambiguous case rev 2 got wrong (`ceiling == natural == 2000` must read
      as NOT limited).
- [ ] `comparability` / `comparability_reason` are byte-identical with and
      without a clamp, for the same `LossConfig`.
- [ ] The three envelope relationships hold as tabulated: `min()` only for
      portion × samples; orthogonality proven in both directions for the
      other two.
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

**8. Commit boundary.** One operator/runtime input
(`validation_max_samples`) plus one additive `TrainingHistory` scope-provenance
field (`validation_requested_samples_before_limit`), and no deadline math.
Both deltas are declared in §2.2's contract inventory; neither is LLM-facing.

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
      (roadmap §22.23.8 "why not projectable"); Pets/DAVIS `STATUS.md`
      **unchanged** — §2a.2's obligations read their DECLARED artifacts and
      add no execution maturity.
- [ ] Roll up the §2a matrix: confirm C3's dtype breadth and C4's capability
      breadth are green for both persistent tracks, and record which layer
      each piece of evidence belongs to.
- [ ] Verify the PR0 governance guards still hold (no `.py` under
      `examples/`, no top-level task YAML) — the mechanical proof that 07c
      did not inflate track maturity.
- [ ] Terminal validation from a CLEAN tree at the final executable head.
- [ ] **Request operator approval, then run the ONE bounded Gate 2**, and
      replay the provider for `D_old_eff` / `D_new_eff` and compute `T_act` from the run’s own artifacts
      (§4.1) — the counterfactual is part of the PASS, not commentary.

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
- [ ] Gate 2 PASS on the standard's functional criteria **and** on §4.1's
      counterfactual, with all three numbers recorded from the run's own
      artifacts: `D_old_eff < T_act ≤ D_new_eff`, and
      `source == "verified_components"`.
- [ ] Any non-PASS counterfactual is classified **INCONCLUSIVE, not PASS**,
      and by its OWN cause — the three causes have different corrections and
      must not be collapsed into "make N_val bigger":

      | Cause | Correction |
      |---|---|
      | `D_old_eff ≥ T_act` because the validation workload was insufficient | a LARGER bounded validation workload is the relevant harness correction |
      | `operator_budget` masks `verified_components` in the `min()` | correct or remove the masking Gate posture, **only if the current Gate standard permits it**. Increasing `N_val` does not necessarily help |
      | `watchdog.floor_seconds` masks the counterfactual | likewise a POSTURE correction, permitted only by the current standard. Increasing `N_val` does not necessarily help |

- [ ] Every inconclusive live attempt is **preserved** (workspace, artifacts,
      diagnosis). A second live launch is NOT pre-authorized by this design:
      the PR budgets **ONE** bounded Gate 2, so any relaunch follows the
      current Gate standard and a fresh operator authorization, and is never
      silently folded into "the same run".
- [ ] Workspace, tested SHA, wall time and cost recorded — or a recorded FAIL
      with diagnosis and no reroll without a substantive in-scope fix.
- [ ] The three-track obligations of §2a.2 are green (C3 dtype breadth, C4
      capability breadth), and no Pets/DAVIS execution maturity was added —
      asserted by the PR0 governance guards.
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

## 16. Open questions — operator dispositions (CLOSED at rev 3)

All nine questions are dispositioned and **none blocks freeze**. Rev 2
dispositioned Q-07c-1..5, 7 and 8 and added Q-07c-9; rev 3 closes the last
two — Q-07c-6 (admission) and Q-07c-9 (clamp provenance) — and records one
**retraction** of a rev-2 claim that did not survive source audit.

| Q | Subject | Disposition (operator, 2026-08-17) |
|---|---|---|
| 1 | unbounded `load_probe_batch` | **DELETE.** No production shim. |
| 2 | which file the builder opens | **(a)** enumerate declared indices, take the first EXISTING declared file — closest to today's "first existing", and it refuses undeclared files on disk. |
| 3 | the second model-name branch | **(a)** eliminate `:235` too, promoting the signature introspection to a shared owner. **(c) is rejected**: narrowing the guard to keep a known name-dispatch would let 07c claim a generic measurement worker while one remains. **STOP if promotion pulls a large API refactor**, then re-evaluate as a defer. |
| 4 | validation as a `RuntimePhase` | **YES** — add `"validation"`. |
| 5 | first `T̂_val` | **(c) BOTH**, not (a). See below. |
| 6 | admission | **B** — runtime prediction + watchdog only; admission-side pricing formally deferred as OPEN runtime-control debt, with a parent correction note and NO binding to D14. |
| 7 | Gate 2 posture | **(a)** watchdog ON, no `--validation_max_phase_seconds`, **plus** §4.1's counterfactual-discriminative acceptance. |
| 8 | measurement dtype site preference | Declare **MEASUREMENT site preference = `int32`**, preserving today's bytes. Phase-correct inference dtype recorded as separate debt. |
| **9** | **clamp provenance (NEW in rev 2)** | **(ii)** — an explicit additive `TrainingHistory.validation_requested_samples_before_limit`, declared as a schema change. `comparability` is NOT overloaded; rev 2's claim to the contrary is RETRACTED below. |

### Q-07c-5 — why BOTH, and a correction to rev 1

Rev 1's preference (a) contradicted its own C5 implementation plan, which
already listed both routes. The operator's disposition is **(c)**, and the
two are not redundant because they serve different runs:

```text
first validation batch  →  measurement-backed prediction  →  protects THIS run
complete validation pass →  full actual                   →  calibrates FUTURE runs
```

C5's checklist and its cold-start temporal test are re-cut accordingly.

### Q-07c-6 — admission: DISPOSED = **B** (operator, rev 3)

Parent §8.4 required the fix to make "the watchdog / admission / prediction"
know the validation cost. The rev-2 audit established that the admission half
is not implementable from the landed measurement lifecycle:

```text
core/runtime_control/admission.py:148-150
    "The prephase measurement covers `phase="training"` only ..."

execute_tools/train_engine_sandbox.py:1474-1490
    the validation pass runs INSIDE the training subprocess,
    forward-only over the eval SampleSet at the training batch size
```

so at pre-run admission time no measurement-backed validation estimate can
exist. Option A (a separate pre-admission validation measurement phase) would
turn 07c from a fix for an observed watchdog defect into a measurement-
orchestration redesign.

**Disposition — B.** 07c's contract is now:

```text
07c OWNS:        validation runtime prediction
                 validation watchdog pricing
                 validation runtime observation / calibration

07c DOES NOT OWN: pre-run admission pricing of the validation workload
```

The reason is structural, not a deferral of convenience:

> At the current architecture boundary there is no measurement-backed
> validation estimate available when pre-run admission executes.

And the escape hatch is closed explicitly: `T̂_val = c · T̂_train` for a fixed
`c` is **forbidden** — that is the hand-calibrated `× 2.7` pattern
`docs/refine_inference_time_estimator.md` exists to remove, and it would
disguise a guess as measurement-backed knowledge, which C8d exists to prevent.

**Parent handling — a correction note beside the clause, never a silent
rewrite.** Parent §8.4 keeps its original text and gains an explicit
post-freeze source correction (added by this revision). The residue is
recorded as an OPEN runtime-control debt with a named owner, and is
deliberately **NOT** attached to D14: D14 owns the generic executable data
path, which is a different semantic owner. If D14's infrastructure later
happens to make pre-admission validation measurement natural, the debt can be
picked up then — it is not pre-bound to that milestone now.

### Q-07c-9 — clamp provenance: DISPOSED = **(ii)** (operator, rev 3)

Rev 2 preferred (i) — "the run-level `validation_max_samples` input is
sufficient provenance". **It is not.** Given

```text
validation_max_samples       = 2000
validation_requested_samples = 2000
```

nothing distinguishes *the natural scope was 2000 and the ceiling did not
bind* from *the natural scope was 12000 and the ceiling clamped it*. The
configured ceiling plus the effective count cannot recover whether a clamp
actually happened.

**Disposition — an explicit additive `TrainingHistory` field**, declared as a
schema change rather than smuggled under the word "provenance":

```python
validation_requested_samples_before_limit: int | None = None
```

`validation_requested_samples` keeps its meaning — the EFFECTIVE requested
scope — so

```text
N_effective  = min(N_before_limit, N_ceiling)
was_limited  = validation_requested_samples_before_limit
                   > validation_requested_samples
```

is derivable with certainty, while 07a's strong invariant
`validation_requested_samples == validation_samples` is untouched and never
relaxed. The full chain becomes legible:

```text
natural scope → operator ceiling → effective requested → exact materialization
```

Preferred over a boolean `was_limited` flag because the pre-limit count is
strictly more informative and cannot go stale relative to the other two.

**Gate 1 is unaffected, with evidence.** The new field cannot reach an LLM:
the planner hides the WHOLE `training_history` key
(`agent/prompts.py:944-946`, `_PLANNER_HIDDEN_RECORD_KEYS` is a top-level
record-key set, so inner fields cannot leak), and `llm_bridge.reflect()`
takes `training_diagnosis` only, never the history (`agent/llm_bridge.py:1009,1062`).

### RETRACTION — `comparability` is not cross-round scope metadata (rev 3)

Revision 2 wrote that a ceiling binding on some rounds and not others makes
those R3 values non-comparable, "exactly what 07a's `comparability` /
`comparability_reason` fields exist to express". **That is withdrawn.**
Source:

```python
execute_tools/training_history.py:104-120
def stamp_comparability(loss_cfg: LossConfig) -> tuple[Comparability, str | None]:
    """Decide the R2/R3 comparability stamp from the RESOLVED LossConfig."""
    if loss_cfg.loss_type == "custom":   return "not_established", ...CUSTOM
    if loss_cfg.reduction != "mean":     return "not_established", ...SUM
    if loss_cfg.loss_type in COMPARABILITY_ESTABLISHED_KINDS:
        return "established", None
```

It is a function of the resolved `LossConfig` alone — objective kind and
reduction. It answers *"can THIS round's train objective and validation
objective be read against each other?"*, not *"can two tuner rounds be read
against each other?"*. Widening it to carry sample-scope metadata would make
it the semantic bag this codebase keeps refusing to create. The two axes stay
separate:

```text
TrainingHistory.comparability                 R2-vs-R3 computation/reduction
validation_requested_samples_before_limit
  + validation_requested_samples              validation SCOPE provenance
```

Whether a consumer should later discount cross-round comparisons whose
validation scopes differ is **consumer policy**, owned by whoever consumes it
— not something C6 may smuggle into an 07a field.

---

## 17. Implementation ledger

*Filled per commit, immediately after each implementation and test checkpoint,
per the incremental-doc rule. Every `[ ]` above becomes `[x]` only with
recorded evidence: exact command, counts, wall time, return code. A test that
could not be run is recorded as not run, with the reason, and never claimed as
passed.*

| | |
|---|---|
| Implementation branch | `step07-pr07c-tuner-measurement` |
| Implementation base | `0b92fac90d5279e2292ffa6551f1e4b572d89c2b` (= `origin/master`, clean tree, verified 2026-08-17) |
| Prerequisites verified merged | PR0 `79403b44` · 07a `65804b3d` · 07b `9ea3755f` · correction `a15d1366` — all present in `git log` from the base |
| Current checkpoint | **GATE 2 PASS (§18.15). Implementation complete; PR next.** |

---

### C1 — Checkpoint 0: byte-identity oracle and pin verification (test-only)

**Status: COMPLETE.** Test-only; no production file changed (`git diff core/
execute_tools/ agent/ nodes/ ml_models/` empty at commit time).

#### C1 audit finding — the Checkpoint-0 fixture is GENERATED, not committed

```text
Previous assumption (design §8/C1 step 2):
  "Record the fixture's provenance and geometry; confirm it is COMMITTED and
  machine-independent (CLAUDE.md portability rule)."

Audit evidence:
  tests/unit/core/test_gpu_measurement_data.py:39-56 (at the base SHA) —
  the `dataset_dir` fixture WRITES the HDF5 file into pytest's `tmp_path` on
  every run, from `np.random.default_rng(20260803)`, 448 int8 samples per
  channel. There is no committed `.h5` anywhere under `tests/`.

Corrected understanding:
  The fixture is machine-independent by REPRODUCIBILITY, not by being
  checked in. numpy's PCG64 stream is stable across versions and platforms,
  so the generated bytes are the same everywhere — and no binary blob enters
  git. This satisfies the portability rule the design cited; only the word
  "committed" was wrong.

Implementation consequence:
  What is COMMITTED is the GOLDEN, not the fixture: `GOLDEN_BATCH_SHA256`,
  dtype, shape, `GOLDEN_SOURCE_FILE` and `GOLDEN_CAPTURED_AT` are frozen
  constants in the test module. A separate pin, `GOLDEN_FIXTURE_INPUT_SHA256`,
  freezes the fixture's own bytes, so an RNG-stream or geometry change fails
  as ITSELF rather than being misread as a loader regression. That
  disambiguation does not exist if the fixture is a committed blob, so this
  is a strictly better oracle, not a workaround.

Validation consequence:
  The design's rev-2 SKIP→FAIL correction still applies, and maps onto the
  generated fixture as "h5py unavailable". `h5py>=3.16.0` is a hard project
  dependency (`pyproject.toml:12`) installed by CI's `uv sync --group dev
  --frozen`, so its absence is a broken environment, never a skippable
  condition. `write_probe_fixture` now calls `pytest.fail` with a named
  message instead of the previous `pytest.importorskip("h5py")`.
```

#### The builder-shaped seam C2 wires into

`PROBE_BATCH_PRODUCERS: dict[str, ProbeBatchProducer]` — a registry of
adapters `(data_dir, batch_size, segment_length) -> ProbeBatchObservation
(tensor, source_file | None)`. At C1 it holds `bounded_loader` and
`unbounded_loader`. C2 deletes the unbounded entry and registers the one
profile-derived builder **here**, so the new builder is measured against the
same frozen golden instead of growing a second, independently-drifting
comparison.

#### The frozen golden (captured at `0b92fac9`, pre-edit)

| Fact | Value |
|---|---|
| batch sha256 (buffer, byte order pinned `<i8`) | `dd96e8a1eb32c0ae9ba2c17235a5b98a9f5c1a6b11b79a43988912c5f512f1a7` |
| dtype / shape | `torch.int64` / `(4, 64)` |
| file actually opened (from `BoundedReadEvidence.source_file`) | `abra_training_0000.h5` |
| channel | `channel0001` |
| `bytes_read` / `file_sample_count` | `256` / `448` |
| fixture input-channel sha256 | `326c7bd699048c55cfe0ca6f273d56830b815ed89dcffa472956f21bccb10018` |

**Both pre-existing loaders produce this same sha256** — verified directly, so
the golden is a property of the batch, not of one loader.

#### PR-G identity / hash / key pins — enumerated and verified GREEN before editing

| Pin family | Module | Cases |
|---|---|---|
| planned + inference workload hash, prephase payload | `tests/unit/core/test_g3_measurement_identity_batch.py` | 9 |
| `MeasurementIdentity.components()` + envelope | `tests/unit/core/test_measurement_identity_and_envelope.py` | 19 (2 deliberately skipped — closed-vocabulary parametrization, `:137`) |
| `calibration_key` read authority | `tests/unit/core/test_calibration_read_authority.py` | 12 |
| measurement capability reachability | `tests/unit/core/test_measurement_capability_reachability.py` | 15 |
| `data_shape_class` exact string `"psd10000000_seg200_files20"` | `tests/unit/execute_tools/test_step00_dataset_baselines.py:103-131` | in-module |
| model-name-branch guard (`_SCAN_TARGETS`, `:47`) | `tests/unit/guardrails/test_no_model_name_branches.py` | in-module |

#### Validation

```text
command:  ./.venv/bin/python -m pytest \
            tests/unit/core/test_gpu_measurement_data.py \
            tests/unit/core/test_g3_measurement_identity_batch.py \
            tests/unit/core/test_measurement_identity_and_envelope.py \
            tests/unit/core/test_calibration_read_authority.py \
            tests/unit/core/test_measurement_capability_reachability.py \
            tests/unit/execute_tools/test_step00_dataset_baselines.py \
            tests/unit/guardrails/test_no_model_name_branches.py -q
purpose:  PR-G pins green BEFORE any production edit
result:   107 passed, 2 skipped, 1.97s, rc=0
skips:    both are pre-existing and deliberate —
          test_measurement_identity_and_envelope.py:137 "closed vocabularies;
          a blank is already not a member"

command:  ./.venv/bin/python -m pytest tests/unit/core/test_gpu_measurement_data.py -q
purpose:  the extended oracle (15 pre-existing + 5 new cases)
result:   20 passed, 1.38s, rc=0
```

#### Mutation proof — the oracle discriminates (hygiene applied)

```text
target site:   core/runtime_control/gpu_measurement_data.py:66
               CLASS_INDEX_OFFSET = 128  ->  127
site count:    1 (grep -c, asserted before mutating)
caches:        all __pycache__ removed before AND after
observed:      FAILED test_every_producer_matches_the_committed_golden[bounded_loader]
               dd96e8a1... -> 06d3092852...   rc=1
restored:      by edit, not git checkout; `git diff core/ execute_tools/ agent/
               nodes/ ml_models/` empty afterwards
baseline re-run: 20 passed, 2.30s, rc=0
verdict:       BEHAVIOUR-CHANGING — the oracle is not vacuous
```

`test_a_corrupted_fixture_turns_the_oracle_red` keeps that property in the
suite permanently, as a data-side mutation (one fixture sample `+1`).

#### C1 acceptance criteria

- [x] Both loaders produce tensors whose sha256, dtype (`torch.int64`) and
      shape are equal to each other and to the committed golden.
- [x] The golden records the exact opened filename, asserted from the
      producer's own evidence and guarded against vacuity (`reported >= 1`).
- [x] Every enumerated pin test passes — 107 passed / 2 pre-existing skips.
- [x] Deliberately corrupting one fixture byte turns the oracle RED —
      recorded above, both as a live test and as a production mutation.

---

### C2 — One profile-derived bounded probe-batch builder

**Status: COMPLETE.**

#### C2 audit — the four questions the design delegated to source

**1. Which callers can supply a resolved `DatasetProfile`, and how does one
reach the worker subprocess?**

```text
nodes/ml_hyperparameter_tune_agent/contracts.py:108
    RunBindings.run_profile   -> "The resolved DatasetProfile (Step 05a)."

nodes/ml_hyperparameter_tune_agent/execution.py:145
    run_profile = bindings.run_profile      # already unpacked, in scope at
                                            # the prephase call site (:594)
```

So the tuner **already holds the object** and no caller has to invent one.
It does NOT reach the worker: `GpuMeasurementSpec`
(`core/runtime_control/gpu_measurement_spec.py:77-195`) carries
`model_config_payload`, `train_config`, `loss_config`, `data_dir`,
`plugin_dir`, `loss_dir`, phases, batches, deadlines and paths — and no
profile.

The ambient seam cannot substitute. `resolve_dataset_profile()`
(`execute_tools/dataset_config.py:596-613`) reads a **ContextVar**, which does
not cross a process boundary, so inside the clean worker it would ALWAYS
answer the shipped TIDMAD profile — "a task assumption expressed by omission
inside generic infrastructure", the exact defect class
`measurement_capability.py:1-30` names. Its own docstring settles the
convention: *"the subprocess entry points load it from their own explicit
config file and pass it down."* Confirmed by grep:
`bind_dataset_profile` has **no production caller** — it is used only in tests.

**2. Are the profile's declarations sufficient, and do they match today's
constants?** Verified by execution, not by reading:

| Needed | Declared | Value | Old constant |
|---|---|---|---|
| input channel | `channels.input_channel` | `channel0001` | `INPUT_CHANNEL` |
| target channel | `channels.target_channel` | `channel0002` | `TARGET_CHANNEL` |
| storage → compute dtype | `encoding.storage_dtype/.compute_dtype` | `int8` → `int16` | inline `np.int8`/`np.int16` |
| value offset | `encoding.value_offset` | `128` | `CLASS_INDEX_OFFSET` |
| filename | `dataset.training_file_name(i)` | `abra_training_0000.h5` | glob literal |
| topology | `dataset.num_files` | `20` | — |

Every fact matches exactly, so byte parity was achievable rather than hoped
for.

**3. Who consumes the three constants?** `grep -rn` over the repository: **no
production consumer outside `gpu_measurement_data.py` itself.** Only tests, and
those were switched to read the profile — a test holding its own copy of the
value could agree with a builder that had stopped reading the profile at all.

**4. What does the evidence model's home imply?** `BoundedReadEvidence` /
`BoundedProbeBatch` have exactly one external consumer
(`tests/unit/core/test_gpu_measurement_worker.py:92-96`). They stay DEFINED in
`gpu_measurement_data.py` as the design requires; `probe_batch.py` imports
them at module level (the direction `train_engine_sandbox` and
`inference_single` already use), and `gpu_measurement_data` imports the
builder INSIDE the function — the style that module already uses for h5py /
numpy / torch. No import cycle, and the evidence contract did not move.

#### C2 DEVIATION — a fifth typed contract delta (`GpuMeasurementSpec.dataset_profile`)

```text
Deviation:
  `GpuMeasurementSpec` gains `dataset_profile: DatasetProfile | None = None`.
  §2.2a's "COMPLETE inventory" lists four typed/serialized deltas and assigns
  `GpuMeasurementSpec` only C3's `ModelIOContract` transport. This is a fifth.

Reason:
  C2's frozen semantics ("the measurement worker derives its data facts from
  the resolved DatasetProfile") are not satisfiable in the worker without a
  transport. See audit question 1: the ContextVar does not cross the process
  boundary, so an ambient resolution there always answers TIDMAD and C2 would
  be cosmetic — the refactor would move the literals without moving the
  authority.

Authority:
  The frozen design DELEGATED this determination to the source audit. C2's
  implementation plan, step 1: "Confirm from source which callers can supply a
  resolved DatasetProfile and how it reaches the worker subprocess (a profile
  is already transported for scoring via `--dataset_profile_json`; verify the
  measurement spec's situation and RECORD IT)." That instruction only has
  content if the answer may be "the spec needs a field".

Classification: BOUNDED.
  Same schema, same character and same backward-compatibility contract as the
  C3 delta the design already authorizes on this very object: runtime-only,
  never LLM-facing, optional, default `None` = parity. `GpuMeasurementSpec` is
  a transient parent→worker JSON file
  (`gpu_measurement_runner.py:244`), not a public or persisted surface, and it
  is hashed into no identity — grep confirms it is only `model_dump_json`'d to
  a temp path.

Impact on frozen invariants: NONE.
  No MeasurementIdentity component, no `candidate_config_hash`, no planned or
  inference workload hash, no `calibration_key`, no `data_shape_class`.

Validation:
  a spec serialized before 07c (the key deleted from its JSON) still validates
  and yields `dataset_profile is None`; a spec carrying the profile
  round-trips to an equal `DatasetProfile`. Both executed, both true.
```

`§2.2a`'s frozen table is left untouched; this row is recorded here rather
than edited into it, so the freeze trail stays readable.

#### C2 decisions

1. **The builder requires an explicit profile; the CALL SITES resolve one.**
   `build_bounded_probe_batch(profile=...)` has no default, so it can never
   assume a task by omission — that is where Q-07c-2's "never an implicit
   TIDMAD default" binds. The worker seam
   (`load_bounded_probe_batch`) resolves `profile or resolve_dataset_profile()`
   because a spec serialized before the transport must still run, and
   `probe_production._setup` resolves the ambient profile because it is
   in-process, exactly as `TIDMADDataset` does
   (`train_engine_sandbox.py:98` — "`None` resolves the Regime-A adapter, so a
   caller predating the transport is unaffected").
2. **`production_probe_executors` did NOT gain a `profile` parameter.** Its
   seven callers (`bootstrap`, `probe_worker_main`, `probe_wiring`, two
   scripts, tests) hold no profile, so the parameter would be a
   seam-without-a-consumer — the §0.8 anti-pattern this codebase names.
3. **`execute_tools/probe_data.py` was DELETED entirely**, not emptied: the
   module contained only `load_probe_batch` (Q-07c-1 = DELETE, no shim).

#### Files changed

| File | Change |
|---|---|
| `execute_tools/probe_batch.py` *(new, 178 lines)* | the ONE builder + `resolve_declared_source_file` |
| `execute_tools/probe_data.py` | **DELETED** |
| `core/runtime_control/gpu_measurement_data.py` | keeps `BoundedReadEvidence` / `BoundedProbeBatch`; `load_bounded_probe_batch` delegates; the three constants and the glob are gone |
| `core/runtime_control/probe_production.py` | `_setup` calls the builder (bounded now, was unbounded) |
| `core/runtime_control/gpu_measurement_spec.py` | `dataset_profile` transport |
| `core/runtime_control/gpu_measurement_worker_main.py` | passes `spec.dataset_profile` |
| `nodes/ml_hyperparameter_tune_agent/runtime.py` | `run_profile` param → `dataset_profile=` on the spec |
| `nodes/ml_hyperparameter_tune_agent/execution.py` | threads `run_profile` (already unpacked) |

#### Test disposition

| Test | Verdict | Why |
|---|---|---|
| `test_the_tensors_are_identical` | **DELETE** | compared the bounded loader to the deleted unbounded one. Subsumed by the golden, which is strictly stronger — two implementations can drift together, a captured hash cannot |
| `test_shape_and_dtype_match` | **DELETE** | same comparison target; dtype/shape are asserted by the golden oracle |
| `test_they_agree_across_shapes` (3 cases) | **REWRITE** → `test_the_golden_holds_across_geometries` | its failure class — "a swapped offset or transposed reshape shows up as soon as the geometry changes" — is preserved by pinning `(1,16)`, `(2,32)`, `(5,8)` and `(4,64)`. **All four goldens were captured by executing the loader from `git show 0b92fac9:` , not from the refactored code**, so they remain pre-refactor captures |
| `test_it_never_materializes_the_whole_channel` | **UPGRADE** | now parametrized over `probe_batch.py` (where the read lives) AND `gpu_measurement_data.py` (so it cannot grow one back) |
| `test_a_missing_dataset_raises` | **KEEP**, regex updated | intent unchanged; the message is now profile-derived |
| `test_it_never_calls_the_unbounded_loader` | **UPGRADE** → `test_the_unbounded_loader_no_longer_exists` | it patched the function with a raiser; there is now nothing to patch, so the guard asserts the module is gone. Reintroducing it IS the c1 failure returning |
| `_patch_bounded_loader` fixture | **UPGRADE** | accepts `profile=`, and reads the channel from the profile |

New in `tests/unit/execute_tools/test_probe_batch.py` (11 cases), each with a
distinct failure class: declared-index enumeration on a gappy directory ·
lowest declared index wins · **an undeclared file on disk is never
substituted** (the real behaviour change vs the glob) · the refusal names the
declared range · bounded-read exactness including `itemsize` · no
channel/filename literal survives in any of the three measurement modules ·
`+128` is not an operative literal · **reachability: the worker seam AND the
in-process probe path each call the one builder exactly once** (the probe path
executed for real on CPU, not asserted from source — the whole failure mode
was a path that looked right and ran something else).

#### Validation

```text
tests/unit/core/test_gpu_measurement_data.py            20 passed   0.92s  rc=0
tests/unit/execute_tools/test_probe_batch.py            11 passed   1.53s  rc=0
+ test_gpu_measurement_worker.py + test_probe_production.py
                                                        61 passed   3.35s  rc=0
tests/unit/core/ + tests/unit/execute_tools/          3528 passed, 3 skipped
                                                                  167.33s  rc=0
tests/unit/nodes/ + tests/unit/guardrails/             126 passed   4.73s  rc=0
tests/unit/agent/tune_ml_hyperparam_agent/            1225 passed  455.63s  rc=0
ruff check . && ruff format --check .                    clean, 948 files
```

Backward-compat, executed: a `GpuMeasurementSpec` JSON with the
`dataset_profile` key removed validates and yields `None`; a spec carrying the
profile round-trips to an equal `DatasetProfile`.

#### C2 acceptance criteria

- [x] Batch sha256, dtype and shape equal C1's golden — **the bytes**, across
      all four pinned geometries.
- [x] The **file actually opened** equals C1's recorded filename, asserted from
      `BoundedReadEvidence.source_file`.
- [x] **The bounded-READ property is preserved** — `bytes_read == batch_size ×
      segment_length × itemsize` exactly (`itemsize` read from the profile's
      declared `storage_dtype`), `fraction_of_file_read < 0.1` recorded, and
      the AST guard proves no whole-channel materialization in either module.
      Not claimed as peak-RSS evidence.
- [x] `grep -rn "channel0001\|channel0002\|abra_training_\|+ 128"
      core/runtime_control/ execute_tools/probe_*.py` returns nothing **in
      live code**. Three hits remain and are all DOCSTRING text in
      `probe_batch.py` explaining the literals it removed. Enforcement is
      therefore the AST guard
      (`TestTheMeasurementPathHoldsNoTaskLiterals`), which scans string and
      integer CONSTANTS — the same instrument, and for the same stated reason,
      as the pre-existing bounded-read guard: *"a substring scan cannot tell an
      explanation from an instruction."* Deleting the explanations to satisfy a
      text grep would trade a real guard for a cosmetic one.
- [x] Exactly one builder is called by both paths —
      `TestBothProductionPathsReachTheOneBuilder`, two cases, `len(calls) == 1`
      each.
- [x] All PR-G pins green (inside the 3,528-case run).

---

### C3 — Contract-derived model-boundary dtype (and contract transport)

**Status: COMPLETE.**

#### The pre-change dtype matrix — the parity target, recorded by execution

The deleted branch was `batch.float() if model_type == "fcnet" else
batch.int()`, which is phase-INDEPENDENT, so each builtin has one row rather
than two. Computed by running both the old expression and the new resolution
side by side:

| model | phase | OLD `:287` | NEW, no contract | NEW, + TIDMAD contract |
|---|---|---|---|---|
| punet | training / inference | `int32` | `int32` | `int32` |
| **fcnet** | training / inference | **`float32`** | **`float32`** | **`float32`** |
| transformer | training / inference | `int32` | `int32` | `int32` |
| wavenet | training / inference | `int32` | `int32` | `int32` |
| rnn | training / inference | `int32` | `int32` | `int32` |
| gated_fno | training / inference | `int32` | `int32` | `int32` |

**FULL PARITY: True**, all twelve rows, both regimes.

Why it holds, from source rather than by luck: the run-bound TIDMAD contract
declares `input.dtype.admissible = ("int64", "int32")`, so the measurement
site's `int32` preference IS admissible and
`resolve_model_input_dtype` returns it unchanged
(`model_input_dtype.py:117-120`, "the compatibility path"). `fcnet` overrides
via `BUILTIN_INPUT_DTYPES` (`models_sandbox.py:779-781`), whose `float32`-only
declaration makes `int32` inadmissible, so it takes the §24.9-Q7 fall-through
to `admissible[0]` — `float32`, exactly what `.float()` produced. **This is
precisely why Q-07c-8 fixed the site preference at `int32`**: any other choice
would have moved the tensor.

#### Q-07c-3 — the promotion, and why it is not a large API refactor

The shared owner is **`ml_models.models_sandbox.construct_registered_model`**,
placed beside `MODEL_REGISTRY` (`:732`) and `BUILTIN_INPUT_DTYPES` (`:779`),
because *how a registered model is constructed* is a property of the registry,
not of any one caller. The introspection body moved verbatim from
`agent/skills/training_skill/estimator.py:295-321`, including its
`(TypeError, ValueError)` fall-back for un-introspectable callables.

```text
BEFORE   estimator._instantiate_for_param_count   inspect.signature -> loss_type?
         gpu_measurement_worker_main:235          if model_type == "fcnet"
             two answers to one question, and the worker's was WRONG for any
             generated plugin whose head shape depends on the loss

AFTER    models_sandbox.construct_registered_model      the one answer
             estimator._instantiate_for_param_count  -> delegates
             gpu_measurement_worker_main             -> calls it
```

**Scope of the promotion: one new public function, one delegation, one branch
deleted, no signature of any existing public API changed.** Not a large API
refactor, so the operator's STOP condition was not reached.

#### Files changed

| File | Change |
|---|---|
| `ml_models/models_sandbox.py` | `construct_registered_model` (the shared owner) + `Any` import |
| `agent/skills/training_skill/estimator.py` | `_instantiate_for_param_count` delegates; keeps its own responsibility |
| `core/runtime_control/gpu_measurement_worker_main.py` | **both** branches gone; `_MEASUREMENT_DTYPE_PREFERENCE = "int32"` declared once; docstring corrected to describe the authorities |
| `core/runtime_control/gpu_measurement_spec.py` | `model_io_contract` transport |
| `nodes/ml_hyperparameter_tune_agent/runtime.py` · `execution.py` | thread `run_model_io` (already unpacked at `execution.py:141`) |
| `tests/unit/guardrails/test_no_model_name_branches.py` | `_SCAN_TARGETS` gains the worker FILE |

The guard targets the **file**, not `core/runtime_control/`: the directory
contains `campaign.py`, whose `"family": "wavenet"` entries are legitimate
config data naming a candidate to run rather than a branch on a model's
identity. Pointing the guard at the directory would report that as a violation
and the guard would have to be weakened to survive — the design's own failure
table calls this out, and it is why the entry is a path to one file.

#### Validation

```text
tests/unit/core/test_pr07c_measurement_boundary.py (new, 37 cases)
                                                        37 passed  0.96s  rc=0
+ worker + data + probe_batch + guardrails             198 passed  5.06s  rc=0
tests/unit/{core,execute_tools,ml_models,agent,guardrails,workflows}/
                                                      8402 passed, 3 skipped
                                                                  783.39s  rc=0
ruff check . && ruff format --check .                    clean, 949 files
```

New cases, each with a distinct failure class: the twelve-row dtype matrix ×
{no contract, TIDMAD contract} · `fcnet` float32 on both sides of the transport
· **Pets and DAVIS declared contracts resolve their own dtype and NOT
TIDMAD's** · DAVIS's five-axis RGB shape recorded as the discriminating case ·
a contract admitting nothing runtime-supported fails closed rather than
coercing · the estimator DELEGATES rather than reimplementing · a constructor
declaring `loss_type` receives it · a plugin-shaped constructor does not ·
`fcnet` still receives its `loss_type` · a spec serialized before either 07c
transport still loads with both fields `None` · a transported contract
round-trips equal.

#### Mutation proofs (hygiene applied: caches cleared, one site each, restored, baseline re-run)

```text
MUTATION 1 — reintroduce the dtype name branch in a scanned file
  site:      gpu_measurement_worker_main.py, `model_input = batch.to(...)`
             -> `batch.float() if model_type == "fcnet" else batch.int()`
  observed:  FAILED test_no_model_name_branches[gpu_measurement_worker]
             "Principle 2 violations — model-name branching in live code:
              ...:319: model_input = batch.float() if model_type == "fcnet"..."
             rc=1
  verdict:   BEHAVIOUR-CHANGING. The extended scan target works.

MUTATION 2 — inline-copy the introspection instead of delegating
  site:      estimator._instantiate_for_param_count, body replaced with its
             own `inspect.signature(...)` copy
  observed:  FAILED test_the_estimator_delegates_rather_than_reimplementing
             "assert 'construct_registered_model' in {'model_cls','signature'}"
             rc=1
  verdict:   BEHAVIOUR-CHANGING. Q-07c-3's "not an inline copy" is enforced,
             not merely stated — an inline copy passes every functional test.

both restored; `agent/.../estimator.py` and the worker verified back at the
delegating form; baseline re-run 134 passed rc=0.
```

One test bug found and fixed during C3, recorded rather than silently
corrected: the first version of
`test_the_estimator_delegates_rather_than_reimplementing` asserted `"signature"
not in ast.dump(node)`, which failed because the function's DOCSTRING contains
the word while explaining where the introspection went. Diagnosed as a TEST
defect (production was correct), and rewritten to assert over CALL nodes — the
same "a text scan cannot tell an explanation from an instruction" lesson the
bounded-read guard already records.

#### C3 acceptance criteria

- [x] For every builtin and both phases, the concrete dtype fed to the forward
      is **identical** to the pre-change table, asserted per row.
- [x] `fcnet` → `float32` **with and without** a transported contract.
- [x] Pets and DAVIS contracts each resolve to their own declared dtype
      (`float32`); neither resolves to TIDMAD's `int32`, and neither raises.
- [x] Batch sha256 unchanged from C1's golden — C2's oracle re-run green in the
      198-case run; C3 changes the dtype at the MODEL boundary, not the batch.
- [x] No `model_type ==` string comparison remains in the scanned measurement
      file, with the mutation proof recorded.
- [x] A spec JSON captured before this commit still loads.

---

### C4 — Capability-routed dataset availability inside `core/runtime_control/`

**Status: COMPLETE.**

#### C4 audit — who holds what

| Site | Before | Caller | Holds a root/capability? |
|---|---|---|---|
| `bootstrap.py:513-520` `_dataset_check` | imported `TIDMAD_DATA_DIR` and read `os.path.isdir` | `production_dependencies()`, whose ONE caller is `scripts/runtime_bootstrap.py:136` | **yes** — the script is the task-aware launcher and already parses `--data-dir` |
| `bootstrap.py:233` remedy | hardcoded *"Point the run at a readable TIDMAD directory"* | same | — |
| `probe_production.py:208-212` | `resolved_dir = data_dir or TIDMAD_DATA_DIR` | 7 callers (`bootstrap`, `probe_worker_main`, `probe_wiring`, 2 scripts, tests) | callers pass `data_dir` explicitly |

**No caller had to invent a dataset root it did not already hold** — the C4
stop condition ("caller holds no capability") was not reached.

#### The typed shape — why `(ok, detail)` was NOT kept

The design allowed keeping the tuple *"unless source shows the caller can take
the typed object"*. Source shows it can, and the tuple could not carry the
required remedy:

> acceptance: "an unavailable capability yields a non-empty remedy **naming
> the task and the reason**".

`(bool, str)` has one string. Naming both would have meant embedding `detail`
inside `remedy` and printing the same sentence twice. The typed object exists
for exactly this — `measurement_capability.py:40-46`: *"Typed rather than a
`(bool, str)` tuple because the identity travels with the verdict."* So
`BootstrapDependencies.dataset_check: Callable[[], tuple[bool, str]]` became
`measurement_capability: Callable[[], ResolvedMeasurementCapability | None]`,
and the report derives detail from `capability.detail` and the remedy from
`task_identity` + `unavailability_reason` + `dataset_adapter`.

Three call-shapes, all fail-closed-preserving:

```text
capability is None          -> ok=False, "no measurement capability was
                               resolved by the caller"   (same wording
                               probe_runner_availability(None) already uses,
                               so "nobody supplied one" stays distinguishable
                               from "the task says no")
probe_available is True     -> ok=True,  capability.detail
probe_available is False    -> ok=False, remedy names task + reason + adapter
```

Threading the capability in never becomes a way to SKIP the check — that is
its own test.

#### Files changed

| File | Change |
|---|---|
| `core/runtime_control/bootstrap.py` | `dataset_check` → typed `measurement_capability`; step 4 builds detail + remedy from it; `_dataset_check` and its `TIDMAD_DATA_DIR` import DELETED; `production_dependencies(measurement_capability=None)` |
| `core/runtime_control/probe_production.py` | the `TIDMAD_DATA_DIR` fallback DELETED — an absent `data_dir` is now an explicit refusal naming what the caller must supply; stale module docstring corrected |
| `core/runtime_control/probe.py` | stale F-1a docstring corrected (it still described the removed fallback as current behaviour) |
| `scripts/runtime_bootstrap.py` | the TASK-AWARE launcher resolves and passes `resolve_tidmad_measurement_capability(args.data_dir)`, forwarding the operator's `--data-dir` |

#### Test disposition

| Test | Verdict | Why |
|---|---|---|
| `test_c10_bootstrap.py` `base` fixture | **UPGRADE** | supplies a constructed `ResolvedMeasurementCapability` the way a task-aware launcher does. Constructed, NOT resolved — `resolve_measurement_capability` checks CUDA first, so resolving here would make the fixture's verdict depend on whether the host has a GPU (the machine-dependent-assertion defect the portability rule names) |
| `test_no_dataset` | **UPGRADE** | asserted `"TIDMAD" in failure.remedy` — the exact hardcoding C4 removes. Now asserts the remedy names the TASK and the REASON |
| `test_an_environment_problem_is_a_verdict_not_an_exception` | **KEEP**, double updated | intent unchanged |
| `test_default_resolves_through_canonical_source` | **REWRITE** → `test_no_data_dir_is_refused_rather_than_defaulted` | it asserted the OPPOSITE of C4's rule. Its intent ("never a second convention, never a silent fallback") survives; the correct destination changed from "the canonical path" to "an explicit refusal". Recorded in the test's own docstring so a future reader sees the inversion was deliberate |
| `test_empty_dataset_dir_raises` | **KEEP**, regex updated | C2 changed the message to the profile-derived one |

New in `tests/unit/core/test_pr07c_capability_routing.py` (9 cases): the
AST import guard over every module under `core/runtime_control/` · the guard's
own non-vacuity check (a planted file must be detected) · the launcher
resolves and passes one · `production_dependencies` accepts rather than
resolves · `--data-dir` reaches the resolver · **Pets and DAVIS each report an
honest unavailability with a task-owned reason, their own identity and their
own shape class** · neither is answered as TIDMAD · the two tracks do not share
an identity · no execution maturity was added.

#### Why the guard is an AST IMPORT scan, not a text grep

`grep -rn "TIDMAD_DATA_DIR" core/runtime_control/` returns **6 hits, all
comments or docstrings** — `measurement_capability.py:5` and
`probe_wiring.py:70-76` record earlier migrations away from it, and
`bootstrap.py` / `probe_production.py` now explain what 07c removed and why.
Two of those docstrings were STALE (they described the fallback as current
behaviour) and were corrected as part of this commit; the rest are accurate
history.

The executable guard therefore scans **imports**, over the AST: a comment is
not an import, and an import is what makes generic code depend on one task's
data layer. Same instrument and same reason as C2's literal guard and the
pre-existing bounded-read guard — *a substring scan cannot tell an explanation
from an instruction.* Deleting accurate history to satisfy a text grep would
trade a real guard for a cosmetic one.

#### Validation

```text
tests/unit/core/test_c10_bootstrap.py                   22 passed  0.23s  rc=0
tests/unit/core/test_probe_production.py + bootstrap    30 passed  1.65s  rc=0
tests/unit/core/test_pr07c_capability_routing.py (new)   9 passed  0.95s  rc=0
```

Portability note: the Pets/DAVIS assertions are on the reason being non-empty,
task-owned and present in `capability.detail`, **never on a specific reason
string**. `resolve_measurement_capability` checks CUDA before the dataset root,
so the concrete reason differs between the GPU host ("no dataset root was
supplied by the caller") and CI ("no CUDA device is visible"). Pinning either
would be a green local run proving nothing about CI.

#### Mutation proof

```text
MUTATION 3 — reintroduce the fallback import inside core/runtime_control/
  site:      probe_production.py, `resolved_dir = data_dir`
             -> `from execute_tools.data_paths import TIDMAD_DATA_DIR`
                `resolved_dir = data_dir or TIDMAD_DATA_DIR`
  caches:    cleared before and after
  observed:  FAILED test_no_module_under_runtime_control_imports_the_task_data_layer
             "generic runtime-control imports a task's data layer:
              {'core/runtime_control/probe_production.py':
               {'execute_tools.data_paths',
                'execute_tools.data_paths.TIDMAD_DATA_DIR'}}"   rc=1
  verdict:   BEHAVIOUR-CHANGING; restored, baseline re-run green
```

#### C4 acceptance criteria

- [x] `grep -rn "TIDMAD_DATA_DIR" core/runtime_control/` returns nothing **in
      live code** — no import, no reference in an expression. The 6 remaining
      hits are comments/docstrings; enforcement is the AST import guard, and
      the two stale ones were corrected.
- [x] The bootstrap step list — names, order, `ok` values — is unchanged on a
      healthy environment (`test_every_step_runs_in_order` and the happy-path
      cases green, unmodified in intent).
- [x] An unavailable capability yields a non-empty remedy naming the task and
      the reason; the assertion is on the reason, not on truthiness.
- [x] No caller had to invent a dataset root it did not already hold.
---

### C5 — Price the validation pass in the runtime model (ADDED SCOPE, root fix)

**Status: COMPLETE.**

#### C5 audit — four facts that decided the implementation

**1. The clock convention is TOTAL ELAPSED FROM SUBPROCESS START.**
`core/sandbox_executor.py:944-953` — `t_start = time.perf_counter()` taken
immediately after `Popen`, then `elapsed = time.perf_counter() - t_start;
if deadline is None or elapsed <= deadline: continue`. A deadline is therefore
the whole wall-clock budget for the child, which is exactly what
`sum(predicted) * watchdog_factor` already expresses. **So the validation term
required NO arithmetic edit** — the design predicted this and the audit
confirms it. The convention was implicit and is now stated in the provider's
docstring; an implicit convention is how an elapsed-vs-remaining mix-up
happens.

**2. `PredictionSource` had no validation member, and the watchdog filters on
it.** `records.py:41-67` is a closed `Literal`; `MEASUREMENT_BACKED_SOURCES`
(`:71-90`) is what C8d filters against at `sandbox_executor.py:~473`. A
validation prediction carrying a non-member source is **inert** — the deadline
ignores it and the whole commit would be cosmetic.

**3. Admission parity is STRUCTURAL, not incidental.** The single largest risk
in C5 was that a validation prediction would enlarge `decide_admission`'s
`known_cost` (`session.py:586-589`) and change a verdict, which Q-07c-6 = B
calls a DEFECT. It cannot:

```text
decide_admission is reachable from the trainer at exactly two places:
  :1361  before the epoch loop (post-setup)
  :1231  inside _finish_training_verification

_finish_training_verification is guarded by `if verifier is not None` at BOTH
call sites (:1420 mid-epoch, :1455 end-of-epoch-0) and each sets
`verifier = None` immediately after. `verifier` is assigned from
`start_phase_verification("training", …)` EXACTLY ONCE, before the loop.

  => at most one admission decision per run, always inside or at the end of
     epoch 0's batch loop
  => strictly before the first `_validation_pass`, which runs after that loop
  => no admission decision can ever see a validation prediction
```

**4. `assess_total` would raise on an unaccounted prediction-bearing phase**
(`session.py:694-699`) — but it has **no production caller** (only
`session.py` defines it; `total_assembly.assemble_total` is a different
function). Likewise `observation_formal_eligible` → `record_is_formal_verified`
is reachable only from the package `__init__` export and tests. Verified by
repository-wide grep. So neither is a production crash or verdict risk.

#### C5 DEVIATION — a sixth typed contract delta (`PredictionSource`)

```text
Deviation:
  `PredictionSource` and `MEASUREMENT_BACKED_SOURCES` gain
  "real_validation_verification". §2.2a's inventory lists C5's delta as the
  `RuntimePhase` vocabulary member only.

Reason:
  Audit fact 2. Without a measurement-backed source the prediction is filtered
  out by C8d and the deadline never grows — the STOP condition "the validation
  term cannot become measurement-backed, so C8d leaves it inert and the fix is
  cosmetic" would fire. Reusing `real_training_verification` was rejected: it
  would label every validation record as a training measurement, which is a
  false provenance claim in a store whose entire purpose is provenance.

Authority / precedent:
  The same module documents this exact pattern for its own C3 extension —
  "Additive — no existing value changes meaning; nothing produces these until
  C6/C7." It is a vocabulary extension of identical character to the
  `RuntimePhase` one the design DOES authorize in this commit.

Classification: BOUNDED.
  Additive, runtime-internal, never LLM-facing. No existing member changes
  meaning; no existing prediction changes source; no identity, hash or store
  key moves.

Validation:
  the phase-vocabulary and source-vocabulary pins below, plus the real-trainer
  reachability test asserting the emitted source is exactly this member.
```

#### Files changed

| File | Change |
|---|---|
| `core/runtime_control/phases.py` | `RuntimePhase` / `RUNTIME_PHASES` gain `"validation"`, with the reason recorded at the declaration |
| `core/runtime_control/records.py` | `PredictionSource` + `MEASUREMENT_BACKED_SOURCES` gain `"real_validation_verification"` |
| `core/sandbox_executor.py` | **docstring only** — the clock convention, and why the term needed no arithmetic change |
| `execute_tools/train_engine_sandbox.py` | validation workload recorded; `_validation_pass` gains an optional verifier and feeds per-SAMPLE ms; prediction completed as soon as terminal; `record_phase_actual("validation", …)` after the loop |

**Both Q-07c-5 evidence sources, and they are not redundant:**

```text
first validation batches, timed in-subprocess
    -> complete_phase_verification("validation", source="real_validation_verification")
    -> a measurement-backed prediction that protects THIS run

full pass, 07a's accumulated validation_seconds
    -> record_phase_actual("validation", …) with the phase's unit_count
    -> realized_unit_ms = actual ÷ units, which calibrates FUTURE runs
```

The unit is one validation **sample**, not one batch, so a partial final batch
cannot bias the rate — which is also what makes C6's clamp safe.

**Counted exactly once.** `extra_predicted_seconds` is deliberately left at 0:
the prediction is `unit_count × ms_per_unit` over EVERY validation row of every
epoch, and the measured batches are among those rows. Adding their measured
cost on top would count the first batch twice. Asserted arithmetically against
the emitted prediction.

#### Validation

```text
tests/unit/core/test_pr07c_validation_pricing.py (new)  26 passed  16.34s  rc=0
tests/unit/core/ -k "runtime_control or watchdog or observation or
  sandbox_executor or phases or session or total_assembly"
                                                       331 passed  10.33s  rc=0
```

The 26 cases, by the defect each names:

*Vocabulary* — validation is a phase · no existing phase moved or was dropped ·
the validation `calibration_key` is a NEW namespace while the other five are
byte-identical apart from the phase segment · the source is measurement-backed
· the `Literal` and the tuple agree.

*Deadline parity (no validation evidence)* — five candidate combinations
(`verified_components` alone, `operator_budget` tightening,
`validation_max_phase` tightening, the floor raising `min()`, the watchdog
factor override) each against a hardcoded expected number · `min()` precedence
unchanged · **a non-measurement-backed validation prediction is ignored**
(C8d).

*The term itself* — the deadline is exactly `(10 + 30) × 1.5 = 60` ·
**the 07a regime replay: the pre-07c provider yields a deadline BELOW the
observed 35.45 s and would have killed the attempt; with the validation
component it does not** · a `None` prediction produces no term rather than a
`nan` (`nan <= deadline` is False, which would kill every attempt instantly).

*Cold-start temporal update* — at t=0 the provider sees the OLD training-only
deadline · **the refreshed deadline arrives strictly before the stale one
fires** (the first batch lands at 9 + 0.88 s against a 10.8 s stale deadline) ·
the refreshed value is a TOTAL, not a remainder (the remainder form,
33.54 s, is close enough to look plausible and wrong enough to kill the run) ·
the convention is documented at the provider.

*Admission parity* — the structural argument checked against source: exactly
two `decide_admission` call sites, exactly one training `start_phase_
verification`, exactly two guarded `_finish_training_verification` calls, and
no admission call inside a validation block.

*Real-trainer reachability* — the REAL `train_engine_sandbox.py` subprocess via
the production `execute_training`, CPU, seconds, over the committed two-family
fixture (the 07a rung's own harness and config, reused so a config difference
can never be mistaken for a C5 defect):
the validation evidence reaches `RuntimeSession` (workload + actual +
measurement) · a stabilised pass lands a measurement-backed prediction with the
right source and the whole-phase `unit_count` · **the first measured batch is
counted exactly once**, asserted arithmetically · the training ACTUAL still
excludes validation (07a parity).

#### An honest limitation, pinned rather than hidden

`test_a_pass_too_short_to_stabilise_yields_no_prediction`. Under the
PRODUCTION verification policy (`min_timed_ms=500`, `window=8 ×
stable_windows=4`) the 8-row fixture cannot reach steady state: the verifier
ends `failed_no_steady_state`, §2.11 gives no prediction, and the watchdog
therefore gets no validation term.

Found by the reachability test failing, and diagnosed before being "fixed": it
is a FIXTURE-SCALE artifact, not a production defect — the 07a regime's 15 000
rows produce thousands of units. And the behaviour is CORRECT: a prediction
extrapolated from eight noisy sub-millisecond samples would be worse than
none, which is what C8d exists to prevent. So it is pinned as a decision
rather than worked around, and the prediction claim is proved separately under
a bounded verification policy — a HARNESS bound on an operator input, with the
production defaults still covered by the test above it.

#### Three failures the broad suite found, each diagnosed before any fix

```text
1. test_estimate_types.py::test_every_source_has_exactly_one_tier
   ::test_lower_rank_never_outranks_measurement

   CLASSIFICATION: PRODUCTION DEFECT in my own C5 edit.
   The source vocabulary has a SECOND declaration —
   `estimate_types.py:78-98 _EVIDENCE_TIER` — and the guard asserts the two
   cover exactly the same values ("one vocabulary, §7.3"). I added the member
   to `PredictionSource` and `MEASUREMENT_BACKED_SOURCES` and missed the tier
   map, so `evidence_rank("real_validation_verification")` would have raised
   `ValueError` at the first ranking call.
   FIX: tier 4, beside its in-process-verification siblings — the same KIND of
   evidence; the phase is what distinguishes it.
   NOTE: this is exactly the cross-schema guard CLAUDE.md describes ("test the
   concept, not the field"). A per-field test would not have caught it.

2. test_step07a_c1_validation_pass.py::TestRuntimeAccounting
   ::test_training_actual_excludes_the_recorded_validation_seconds

   CLASSIFICATION: TEST too narrow; production CORRECT.
   Observed `[-297.99, 300.0]` where the test asserted `len(raw_actuals) == 1`.
   The training actual is still deeply negative — 07a's property holds exactly
   — and the second value is C5's validation actual, 3 x 100.0, precisely
   right. `len == 1` was an incidental fact of 07a's world, not the property.
   FIX (disposition UPGRADE): the spy keys by PHASE; the original claim is
   asserted unchanged on the training actual, and the validation actual is
   pinned beside it. The test is now STRONGER — it proves both halves of the
   split, and would fail if either phase were recorded twice.
```

Nothing was weakened to make anything pass, and no guard was relaxed.

#### C5 acceptance criteria

- [x] With no validation evidence, the provider returns a `(deadline, source)`
      pair identical to the recorded baseline for every enumerated candidate
      set.
- [x] With validation evidence, the deadline equals the exact expected number,
      hardcoded rather than recomputed from the implementation.
- [x] The 07a Gate-2 replay (9 s train / 26.45 s validate) yields a deadline
      ≥ the observed 35.45 s, whereas the pre-change provider yields < it.
      **The commit's headline assertion.**
- [x] The training ACTUAL for the same replay is unchanged
      (validation-exclusive), asserted on a real run.
- [x] `RUNTIME_PHASES` gains exactly one value; every existing
      `calibration_key` is unchanged, asserted against captured keys.
- [x] **Admission verdicts unchanged for a fixed input set** — established
      structurally (no admission decision can follow a validation prediction),
      which is stronger than a value comparison because it holds for every
      input rather than for the ones enumerated.
---

### C6 — Interim validation-scope envelope (`validation_max_samples`)

**Status: COMPLETE.**

#### C6 audit — placement, decided from the sibling

`validation_max_train_samples` — the field this one is the counterpart of — is
resolved and applied like this:

```text
HyperparamTuningInput.validation_max_train_samples   (operator input)
  -> runtime.py's policy dict                        (:1093)
  -> RuntimeControlPolicy.validation_max_train_samples (session.py:215)
  -> train_engine_sandbox.py:1213, applied where the EPOCH IS BUILT
```

`validation_max_samples` follows exactly that path. Two consequences worth
stating:

* **No new training argv flag.** The runtime-policy JSON is the established
  transport for this class of ceiling, so 07a's 05c exact-argv oracle is
  untouched — which an `--validation_max_samples` child flag would have broken.
* **The clamp lives in the TRAINER**, symmetric with its sibling, applied to
  `eval_sample_set` immediately before `_preflight_validation_scope` measures
  it. So the pre-flight measures the CLAMPED scope, which makes
  `validation_requested_samples` the EFFECTIVE request and keeps 07a's
  `requested == materialized` invariant untouched by construction.

The natural scope is measured FIRST (a second, cheap HDF5-metadata pre-flight)
so the pre-limit count survives as the provenance the effective count can no
longer recover.

#### C6 DEVIATIONS (two, both bounded)

```text
1. A SEVENTH typed delta: RuntimeControlPolicy.validation_max_samples.
   §2.2a names `HyperparamTuningInput` only. The policy field is the
   TRANSPORT that operator input needs to reach the trainer, and it is the
   one the declared sibling already uses. The alternative — a new child argv
   flag — would have broken a frozen oracle. Bounded; same character as the
   declared field; default None = parity.

2. The CLI flag is NOT in `nodes/ml_hyperparameter_tune_agent/cli.py`.
   §2.1 named that file; source shows the validation-posture flags live in
   `sdsc_submission_scripts/run_one_iteration.py` (argparse) and
   `_chain_common.sh` (the chain wrapper), with `workflows/model_exploration.py`
   and `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` threading
   them. `cli.py` carries none of the three siblings. The flag was added to the
   real operator surface, all four hops, so it is reachable from the documented
   entry point.
```

#### The granularity decision, and why `min(natural, ceiling)` needs one word of qualification

A SampleSet expresses whole **PSD segments**; a row is
`psd_segment_length // seg_size` of them. So a ceiling that falls between two
PSD segments cannot be hit exactly.

```text
resolved rows = largest multiple of ml_segs_per_psd that is <= ceiling
              = min(natural, ceiling)   exactly, when the ceiling is aligned
```

**Rounds DOWN, never up** — this is a MAXIMUM, and a bound that can be exceeded
is not one. A ceiling below ONE PSD segment's rows is refused with a named
error rather than resolving to an empty scope: R3 does not exist for an empty
scope, and 07a's whole posture on validation scope is fail-closed. Under TIDMAD
at seg 40 000 one PSD segment is 250 ML rows, so this is a real operator case,
not a fixture artefact — pinned as such.

#### Files changed

| File | Change |
|---|---|
| `agent/schemas/hyperparam_tuning.py` | `validation_max_samples: int \| None = None`, `ge=1` |
| `core/runtime_control/session.py` | the policy transport field |
| `nodes/ml_hyperparameter_tune_agent/runtime.py` | policy dict entry |
| `execute_tools/training_history.py` | `validation_requested_samples_before_limit` + the "a ceiling may only REDUCE" validator |
| `execute_tools/train_engine_sandbox.py` | `clamp_validation_scope` (new, public); applied before the pre-flight; the pre-limit count threaded into the history |
| `sdsc_submission_scripts/run_one_iteration.py` · `_chain_common.sh` · `workflows/model_exploration.py` · `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` | the operator flag, all four hops |

#### Validation

```text
tests/unit/execute_tools/test_pr07c_validation_envelope.py (new)
                                                        42 passed  16.42s  rc=0
+ test_step07a_c1_validation_pass.py + C5 pricing        48 passed  45.09s  rc=0
```

42 cases: `None` is exact parity (and returns the scope OBJECT, so a rebuild
cannot quietly change key types or order) · above-natural and equal-to-natural
do not clamp · four aligned ceilings resolve exactly · three unaligned ceilings
round DOWN and never overshoot · a sub-PSD ceiling is refused, not zeroed ·
files that lose every segment are dropped rather than left empty.

*Which samples* — identical identities AND order across repeats · the concrete
selection asserted (`{0: [0,1,2,3], 1: [0]}`), not merely "it is deterministic",
because a stable-but-wrong rule is also deterministic · insertion order does not
matter · **string keys order NUMERICALLY** (the SampleSet crosses a JSON
boundary, and lexicographic order would put file 10 before file 2).

*The envelope matrix, three DIFFERENT relationships* — portion × samples share
a dimension, so the tighter wins, asserted in both directions · the training
ceiling is ORTHOGONAL, asserted from the policy object in both directions so a
future edit that fused them fails here · the phase fuse is orthogonal AND in
different units.

*Schema refusal* — 0 and negatives rejected on both the policy and the
operator input, at startup, before spend.

*Provenance* — a clamped run is distinguishable · **the ambiguous case
(`ceiling == natural == 2000`) reads as NOT limited**, which is what rev 2 got
wrong · no ceiling leaves the field `None` · a `before_limit` below the
effective count is refused (it would invert `was_limited` for every consumer) ·
07a's exact-materialization validator still fires · **`comparability` is
byte-identical with and without a clamp**, the rev-3 retraction as an
executable guard.

*Not planner-visible* — the planner drops the whole `training_history` key, so
an inner field cannot leak.

*Real runs* (CPU, seconds, the 07a two-family harness) — no ceiling is exact
parity · a binding ceiling clamps to 10 rows and **still materializes
exactly**, with `before_limit == 24` · a non-binding ceiling records
`before_limit == requested` · comparability unchanged across two real runs ·
**R3 over a partial final batch is sample-count weighted**.

The weighting test is known to discriminate, both numbers recorded:

```text
[C6] r3=2.760197973251343  weighted=2.760197973251343  unweighted=2.7600955168406167
```

10 clamped rows at batch 4 gives batches of 4, 4, 2 — the partial final batch a
ceiling creates — and R3 matches the sample-count-weighted mean to 1e-5 while
differing from the unweighted mean-of-batch-means. The test asserts the two
statistics are NOT equal, so it can never pass vacuously on data where they
happen to coincide.

*Operator surface* — the launcher's `--validation_max*` flag set is exactly the
four expected names (so `--help` gained exactly one) and the chain wrapper both
parses and forwards it, because a flag the launcher accepts but the wrapper
drops is unreachable from the documented entry point.


#### Four failures the full suite found, each diagnosed before any fix

```text
1-3. test_watchdog_admission_split.py (3 cases)
     CLASSIFICATION: TEST FIXTURE incomplete; production CORRECT.
     `AttributeError: 'SimpleNamespace' object has no attribute
     'validation_max_samples'`. `_build_runtime_policy` reads the field by
     ATTRIBUTE, as it reads the sibling, and the stub hand-lists what the
     helper reads. The fixture's own docstring says so: "every new field it
     reads breaks all three at once — which is how CI went red on 2026-08-14".
     The guard worked exactly as designed.
     FIX: `"validation_max_samples": None` added to the stub.

4a.  test_step07a_c3_tuner_boundary.py::test_success_with_history_...
     CLASSIFICATION: EXPECTED, AUTHORIZED delta.
     `_HISTORY` is a whole-payload golden and gained exactly one key with
     value None. §2.2 declares this the ONE persisted delta 07c may make.
     FIX (disposition UPGRADE): the key added to the golden, with a comment
     naming it as the single authorized addition, so the whole-dict
     comparison keeps proving "nothing else moved".

4b.  test_step00_record_baselines.py::test_formal_success_record_projection
     CLASSIFICATION: same delta, one layer out (REC-2 record projection).
     The reported diff was ONE added line — `"validation_requested_samples_
     before_limit": null` — inside `training_history`, with every other key
     and value unchanged.
     FIX: the golden was edited SURGICALLY as text, not regenerated. The
     helper's contract is explicit ("tests never write goldens", design §17
     rule 3), and a `json.dumps` round-trip would have silently re-escaped
     unrelated Unicode across a 400-line rendered-markdown value. The
     `_captured_at` provenance block was updated in place, naming the prior
     capture, so the final diff is the provenance block plus one key.
```

Nothing was weakened, no assertion was loosened, and no guard was relaxed.

#### C6 acceptance criteria

- [x] Default `None` → validation row count identical to a pre-change run
      (real run, 24 rows, `before_limit is None`).
- [x] With the ceiling, `validation_samples == min(natural, ceiling)` — exactly
      for an aligned ceiling, and the largest non-overshooting multiple
      otherwise (granularity decision above) — **and**
      `validation_requested_samples == validation_samples`, so 07a's validator
      never fires.
- [x] The clamped set's sample identities and order are identical across
      repeated runs with the same config.
- [x] R3 over a clamped set with a partial final batch equals the
      sample-count-weighted expectation and differs from the unweighted
      mean-of-batch-means; both numbers recorded.
- [x] A clamped run is distinguishable from an unclamped one, including the
      ambiguous `ceiling == natural` case.
- [x] `comparability` / `comparability_reason` byte-identical with and without
      a clamp, for the same `LossConfig`.
- [x] The three envelope relationships hold as tabulated.
- [x] `--help` gains exactly one flag; the chain wrapper forwards it.
- [x] The schema refuses `0` and negatives, naming the field.
---

### C7 — Checkpoint B rung, Checkpoint D mutations, docs, terminal validation, Gate 2

**Status: IMPLEMENTATION COMPLETE; Gate 2 AWAITING OPERATOR APPROVAL.**

#### B-07c-1 — the measurement data-feeding axis

Built on the EXISTING Step-02 3-file contrast fixture
(`tests/helpers/two_family_profile.py`, 4.8-B geometry) — reused, not
re-created, per the design.

Three contrasts, each moving exactly one DECLARATION, each asserting the bytes
MOVE and the identity keys + comparability stay byte-stable **in the same
test**, so the axis is provably single:

| Contrast | What moves | Why this one |
|---|---|---|
| `other_channel` | `channels.input_channel` / `.target_channel` swapped | a swap keeps shape, dtype and value range and changes every measured number — the failure a same-shape check cannot see |
| `non_int8_storage` | `encoding.storage_dtype` int8 → uint8 (offset 0) | the fixture holds int8 payloads, so reading them as uint8 wraps every negative sample: the cast chain is genuinely taken from the declaration |
| `value_offset` | `encoding.value_offset` 128 → 200 (num_classes 328) | the one fact whose reintroduction as a literal keeps shape and dtype correct and changes every value |

Plus a **negative control** — a geometry-only contrast (`num_files` 3 → 4)
moves the identity and must NOT move the bytes, because the probe reads the
first declared file's leading samples — and a **reproducibility check**, so the
three `!=` assertions cannot pass because the builder is nondeterministic.

**The unit of contrast is a DECLARATION, not a field, and that is enforced
rather than chosen.** `ValueEncoding._alphabet_covers_the_shifted_range`
refuses an incoherent triple: for int8 data in a 256-class alphabet, **128 is
the ONLY legal offset**. A field-only contrast would not be a stricter test —
it would be an invalid profile the production path could never receive.
(`num_files` shrinking is refused for the same reason: the declared
anchor/peek file sets live inside the index space, so the control GROWS it.)

Two more cases pin the third removed constant: a different
`training_file_pattern` must open another file or refuse (never fall back to
the old glob), and the evidence must name the file the declaration chose.

#### Checkpoint D — the complete mutation set

```text
MUTATION 4 — delete-the-hop: the builder ignores its profile
  site:      probe_batch.py, `channel_name = profile.channels.input_channel`
             + `encoding = profile.encoding`  ->  hardcoded back to
             "channel0001" / TIDMAD_PROFILE.encoding   (1 site each)
  caches:    cleared before and after
  observed:  B-07c-1  RED on all three contrasts, rc=1
             C1/C2 byte oracle  STILL GREEN, 20 passed
  verdict:   BEHAVIOUR-CHANGING — and the second line is the whole argument
             for Checkpoint B existing. Byte parity CANNOT detect this defect,
             because under TIDMAD the profile's declarations and the deleted
             constants are the same values.
  restored:  production diff empty; baseline re-run 39 passed
```

The full Checkpoint-D set, with where each was proved:

| Row | Mutation | Guard that went RED | Recorded in |
|---|---|---|---|
| builder ignores the profile | channel + encoding hardcoded | B-07c-1, 3 contrasts | C7 |
| dtype-branch reintroduction | `batch.float() if model_type == "fcnet"` | `test_no_model_name_branches[gpu_measurement_worker]` | C3 |
| constructor introspection inline-copied | private `inspect.signature` restored | `test_the_estimator_delegates_rather_than_reimplementing` | C3 |
| `TIDMAD_DATA_DIR` reintroduced under `core/runtime_control/` | import restored in `probe_production` | `test_no_module_under_runtime_control_imports_the_task_data_layer` | C4 |
| oracle vacuity | `CLASS_INDEX_OFFSET` 128 → 127 | the Checkpoint-0 golden | C1 |
| **reachability** | — | worker seam AND in-process probe path each call the one builder exactly once, the probe path executed for real on CPU | C2 |

#### Three-track roll-up (§2a matrix)

| Layer | Track | Evidence | Commit |
|---|---|---|---|
| 1 — atomic single-axis | Step-02 contrast profile | B-07c-1: one declaration moves → bytes move; identity stable | C7 |
| 2 — persistent breadth | TIDMAD | byte parity across four geometries; real-trainer runs | C1–C6 |
| 2 | Oxford-IIIT Pet | declared `ModelIOContract` resolves float32, NOT TIDMAD's int32; capability unavailable with a task-owned reason | C3, C4 |
| 2 | DAVIS | same, and the strongest contrast — 5-axis RGB `[B,C,T,H,W]` float | C3, C4 |
| 3 — real execution | TIDMAD | **Gate 2 — AWAITING OPERATOR APPROVAL** | C7 |

**No Pets/DAVIS execution maturity was added**, asserted mechanically: PR0's
governance guards are green (80 passed — no `.py` under `examples/`, no
`resolved/` tree for either track), and the C4 test asserts it directly.

#### Documentation

`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`:
the `validation_max_samples` row beside its three siblings; the orthogonality
with `validation_max_phase_seconds` stated on both rows; the "07a's validation
pass is missing from the watchdog deadline" known-defect entry struck through
and marked **FIXED by C5**; and the admission-side pricing recorded as
**STILL OPEN** with its owner, its non-binding to D14, and the forbidden
fixed-ratio approximation.

Every documented value was quoted against merged source by execution, not
recall: `validation_max_samples` default `None` / `Ge(ge=1)` on BOTH
`HyperparamTuningInput` and `RuntimeControlPolicy`;
`validation_requested_samples_before_limit` default `None`;
`clamp_validation_scope(eval_sample_set, *, max_samples, ml_segs_per_psd)`;
TIDMAD `psd_segment_length // 40000 == 250`.

```text
DEVIATION (bounded): `docs/running_chain_test.md` DOES NOT EXIST.
  The design's C6/C7 scope names it. The operator surface for the sibling
  validation-posture flags is `sdsc_submission_scripts/run_one_iteration.py`
  (argparse) + `_chain_common.sh` (chain wrapper), both updated in C6, and the
  node `.md`, updated here.

DELIBERATE NON-EDIT: `docs/gates/gate_testing_standard.md` documents the
  canonical Gate command and its bounds table. Adding `--validation_max_samples`
  to it is a Gate POSTURE change, and Q-07c-7 froze the 07c posture. It is
  raised in the pre-Gate packet for the operator instead of being edited in.
```

#### Terminal validation — CLEAN TREE, FINAL EXECUTABLE HEAD

```text
head          3cb6eef1be0bec9d5f5c5d262197be909cab3ebc
tree          clean (git status --short empty before launch)

command       ./.venv/bin/python -m pytest tests/unit/ -m "not real_run" -q
result        9967 passed, 3 skipped, 0 failed
wall time     951.04s (15:51)
return code   0            (read from the redirected log, not from a pipe)

command       ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
result        All checks passed! - 953 files already formatted
return code   0

pyright       NOT RUN LOCALLY. Node v10.19.0 cannot execute the vendored
              pyright bundle - verified this session by invoking it, not
              assumed. Exact-head CI owns this check.
```

The 3 skips are pre-existing and named, all present at the base SHA.

#### PRE-GATE ANALYSIS - the canonical bounds would NOT be discriminative

Performed BEFORE requesting the launch, which is what §4.1 exists for: a Gate
whose counterfactual cannot separate is INCONCLUSIVE, and discovering that
after the run wastes the one budgeted launch.

Resolved posture under the canonical command minus
`--validation_max_phase_seconds` (Q-07c-7), watchdog ON:

```text
watchdog_factor        1.0     (runtime_safety_factor default; no override)
floor_seconds          60.0    (runtime_watchdog_floor_seconds default)
operator_budget        None    (trial round, no --*_time_budget_minutes)
validation_max_phase   omitted (Q-07c-7)

  =>  D = max(60.0, SUM of measurement-backed predictions x 1.0)
```

Expected workload from the canonical bounds, using 07a's own Gate-2
measurements as the rate (2,000 training rows -> 9 s; 15,000 validation rows
-> 26.45 s, i.e. ~1.76 ms/row):

```text
training    <= 2,000 ML rows  (--validation_max_train_samples 2000)   ~9 s
validation  --validation_max_portion 0.01 of scope 4-9
            = 6 files x 200 PSD x 0.01 ~ 12 PSD x 250 rows = ~3,000   ~5 s
T_act       ~14 s
```

**`T_act` ~14 s is BELOW the 60 s floor**, so `D_old_eff = D_new_eff = 60` and
the counterfactual does not separate — §4.1's `watchdog.floor_seconds > T_act`
row, i.e. **INCONCLUSIVE, not PASS**.

The correction is a POSTURE change, and posture is the operator's: Q-07c-7
froze "watchdog ON, fuse omitted" and says nothing about the floor or the
factor. The recommended posture and its arithmetic are in the pre-Gate packet
handed to the operator; nothing is launched until it is approved.

Note also, per §4.1's "C6 trap": `--validation_max_samples` (this PR's own new
flag) must NOT be passed to Gate 2. Clamping validation is precisely what makes
the counterfactual stop separating.

#### Gate 2

**NOT LAUNCHED.** Stopped at the PRE-GATE REVIEW checkpoint as the
implementation contract requires. The packet — final executable SHA, the exact
canonical command, watchdog/validation posture, expected wall time, why the run
should be counterfactual-discriminative, and how `D_old_eff` / `D_new_eff` /
`T_act` will be reconstructed — is in the operator hand-off.

---

## 18. OPERATOR PRE-GATE RULING (2026-08-17)

Recorded before the live Gate. **No executable change is authorized by this
ruling**, and none was made: the executable tree is unchanged from the
terminal-validated head `3cb6eef1`.

### 18.1 Gate 2 — AUTHORIZED, exactly ONE bounded live launch

The canonical posture would have been INCONCLUSIVE by construction (§17's
pre-Gate analysis: a 60 s floor with `T_act ~14 s` makes
`D_old_eff = D_new_eff = 60`). The operator approved three **Gate-HARNESS**
posture changes — *not* production-default changes:

| Change | From | To | Why |
|---|---|---|---|
| `--validation_max_portion` | 0.01 | **0.05** | raises the validation workload until the counterfactual can separate; §4.1's own warning is that an over-clamped validation makes `D_old_eff >= T_act` |
| `--runtime_watchdog_safety_factor` | (unset → 1.0) | **1.5** | margin on both sides of the inequality; an existing operator surface, and watchdog-specific so admission is untouched |
| `--runtime_watchdog_floor_seconds` | 60 | **5** | the 60 s floor alone would rescue the pre-07c code, which §4.1 classifies as INCONCLUSIVE |

Held per Q-07c-7 and §4.1: watchdog **ON**, `--validation_max_phase_seconds`
**omitted**, `--validation_max_samples` **omitted** (the C6 trap — clamping
validation is exactly what stops the counterfactual separating), no operator
time budget, cold-start (no `--seed_paths`).

> This is not "changing the algorithm so a test passes". It is choosing an
> experimental condition under which the causal effect under test is
> observable — which is what a discriminative Gate requires.

**PASS is artifact-derived, never projection-derived.** The `~13.5 / ~35 / ~52`
figures in §17 are a launch projection and carry no acceptance weight. The
verdict comes only from this run's own artifacts:

```text
D_old_eff = real provider replay over the sidecar WITHOUT the validation component
D_new_eff = real provider replay over the sidecar WITH it
T_act     = components.training.actual_seconds + sum(TrainingHistory.validation_seconds)

PASS iff   D_old_eff < T_act <= D_new_eff
     AND   D_new source == "verified_components"
     AND   operator budget did not win the min()
     AND   the watchdog floor did not mask

D_old_eff >= T_act ............................. INCONCLUSIVE
floor or operator budget masks ................. INCONCLUSIVE
validation prediction arrives too late and the
  stale deadline actually fires ................ FAIL (cold-start defect),
                                                 NOT a workload problem
```

Every artifact and workspace is preserved whatever the outcome. **This
authorizes ONE live launch.** A second requires a fresh operator ruling.

### 18.2 The three implementation deviations — ALL APPROVED

Recorded as source-grounded deviations, and folded into the corrected inventory
in §18.3. Gate 1 remains **NOT REQUIRED**: none is LLM-facing and no prompt
byte moves.

1. **`GpuMeasurementSpec.dataset_profile`** — the worker is an isolated
   subprocess, so without transport "the builder constructs the batch from the
   profile" holds only in the parent and the worker keeps no semantic
   authority. The frozen C3 already authorises the same class of transport on
   the same object with the same backward-compatibility requirement.
2. **`PredictionSource += "real_validation_verification"`** — near-inevitable
   from C5: a non-measurement-backed prediction is ignored by C8d, and the
   landed vocabulary had no truthful way to say *this came from real validation
   verification*. A new member is more correct than disguising it as a training
   measurement. Old values unchanged, old serialized observations readable.
3. **`RuntimeControlPolicy.validation_max_samples`** — a transport for an
   already-declared operator ceiling, not an independent semantic authority.
   Preferred over a new child argv, which would disturb 07a's frozen argv
   surface.

### 18.3 Typed / serialized contract inventory — CORRECTED AND COMPLETE

§2.2a's inventory is superseded by this table. It listed four deltas and
described itself as complete; the implementation required three more, each
approved above.

| # | Commit | Contract | Delta | Character |
|---|---|---|---|---|
| 1 | C2 | `GpuMeasurementSpec` | + optional `DatasetProfile` transport | runtime-only, backward-compatible |
| 2 | C3 | `GpuMeasurementSpec` | + optional `ModelIOContract` transport | runtime-only, backward-compatible |
| 3 | C5 | `RuntimePhase` / `RUNTIME_PHASES` | + `"validation"` | new namespace; existing keys unmoved |
| 4 | C5 | `PredictionSource` / `MEASUREMENT_BACKED_SOURCES` / `_EVIDENCE_TIER` | + `"real_validation_verification"` | additive vocabulary; no existing member changes meaning |
| 5 | C6 | `HyperparamTuningInput` | + `validation_max_samples` | operator input; default preserves parity |
| 6 | C6 | `RuntimeControlPolicy` | + `validation_max_samples` | transport only |
| 7 | C6 | `TrainingHistory` | + `validation_requested_samples_before_limit` | additive scope provenance |

**None is LLM-facing.** The planner drops the whole `training_history` record
key; `reflect()` takes `training_diagnosis` only; `GpuMeasurementSpec`,
`RuntimePhase`, `PredictionSource` and `RuntimeControlPolicy` are
runtime-control internals; `validation_max_samples` is never rendered into a
prompt.

### 18.4 C6 — POST-FREEZE SEMANTIC SOURCE CORRECTION (operator, 2026-08-17)

Frozen C6 said `N_effective = min(N_natural, N_ceiling)`, "exactly N rows".
Source shows that assumes every integer row count is representable, which a
`SampleSet` cannot express: its native unit is the task's own sample identity,
and one such unit expands into several ML segments. **The frozen wording made a
granularity assumption that is wrong in general.** Corrected contract:

```text
N_effective = the LARGEST task-representable non-empty validation scope
              that is <= min(N_natural, N_ceiling)
```

i.e. `validation_max_samples` is an UPPER BOUND over the task's legally
representable validation scopes — not a promise that any integer row count is
reachable. This is strictly MORE generic than the frozen wording: it respects
task-owned sample identity instead of assuming universal row-level
truncatability. A ceiling below the smallest legal non-empty scope **fails
closed before spend**; a task-owned atomic grouping is never split.

**The operator's hard condition, verified from source before the Gate:**

```text
requirement  granularity must come from the landed DatasetProfile / SampleSet
             authority, NEVER hardcoded PSD/TIDMAD knowledge in generic code

evidence     clamp_validation_scope body: numeric literals == [0, 0] (the <= 0
             guards only). No psd_segment_length, no 250, no 10_000_000, no
             TIDMAD reference, no task branch. The only attribute it reads is
             `.keys()`; granularity arrives as the `ml_segs_per_psd` PARAMETER.

             The caller supplies it from the landed authority:
               ml_segs_per_psd=profile.dataset.psd_segment_length // seg_size
             — the identical expression 07a's own _preflight_validation_scope
             already uses.

             C6's ENTIRE contribution to core/runtime_control/ is one Pydantic
             Field declaration, zero logic. The two "PSD" strings there are
             pre-existing prose (session.py:225 blames to 3f6e1389, the
             sibling's description, 2026-08-13).

verdict      SATISFIED. Gate not blocked.
```

`TrainingHistory.comparability` is NOT overloaded (rev-3 retraction upheld).

### 18.5 `docs/running_chain_test.md` — source correction APPROVED

```text
The frozen design's expected path DID NOT EXIST at the implementation base.
Actual operator surfaces updated instead:
    sdsc_submission_scripts/run_one_iteration.py   (argparse)
    sdsc_submission_scripts/_chain_common.sh       (chain wrapper)
    nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md
No replacement documentation file was invented.
Current repository truth > frozen doc-path assumption.
```

### 18.6 NEW DEBT — Milestone-1 global genericity residual audit (operator, 2026-08-17)

Raised by the operator while reviewing this PR, recorded here so it survives to
the finalizer. **Not 07c scope, and deliberately not actioned here.**

The end-state acceptance is sharpened:

> **Not** "the string TIDMAD must not appear in the repository."
> **Instead:** generic framework/core production code must hold no
> TIDMAD-specific semantic authority and no task-identity branch. TIDMAD must
> be a task instance registered through config / contracts / plugins / task
> pack, exactly like Pets and DAVIS.

Residue is dispersed by OWNERSHIP — 07c measurement, D14 the executable data
path, Step 08 HealthGate, Step 09 interpretation, Step 10 orchestration,
Step 11 execution infrastructure (`TidmadSandbox`, `dirs["data"] =
TIDMAD_DATA_DIR`, `tidmad_db`, cleanup globs), Step 12 task composition. The
governance risk is that every owner correctly says "not my scope" and a
residue survives with no owner at all.

So Milestone 1 closeout must carry an explicit acceptance: a global scan
(`TIDMAD`, `tidmad`, `abra_`, `denoising_score`, `channel000*`,
`CLASS_INDEX_OFFSET`, `file_index=6`, `range(20)`, `[3,10,17]`, `[0,10,19]`,
`256`, `+128`, …) in which **every production-code match is classified**:

```text
1 generic framework semantic dependency ....... FAIL
2 legacy Regime-A adapter ..................... must be bounded and unreachable
                                                from a bound Regime-B task
3 task-specific implementation ................ must live under TIDMAD task /
                                                plugin / example ownership
4 comment / test / historical doc ............. allowed
5 generic numeric coincidence ................. source-proven non-TIDMAD meaning
```

Target:

```text
generic-framework semantic dependencies ........ 0
task-identity branches in generic production ... 0
bound tasks requiring a core source edit ....... 0
```

**Two concrete findings already banked**, both out of 07c scope:

* `core/sandbox_executor.py` — `TidmadSandbox`, `dirs["data"] =
  _tidmad_data_dir()`, `MongoRecorder(..., "tidmad_db")`, and
  `derive_tidmad_metric(resolve_dataset_profile())` as a Regime-A metric
  fallback. Owners: Step 11 (infrastructure) and Step 12 (binding / fail-closed
  default).
* `DatasetConfig.psd_segment_length` — the generic dataset declaration's own
  vocabulary is TIDMAD-flavoured. Pre-existing Step-02-seam debt, surfaced by
  C6's granularity audit; C6 consumes it and introduces nothing new.

**Open operator decision:** whether this acceptance is promoted into the FROZEN
roadmap (Rev 5.3 §22 / Milestone-1 acceptance) or stays as tracked debt. The
roadmap is frozen and 07c does not own it, so the promotion belongs to the
post-merge finalizer or a dedicated roadmap revision — not to this PR.

### 18.7 PRE-LAUNCH HALT — 07a's measured Gate-2 data revises the approved posture

Discovered while performing the final pre-launch checks, BEFORE consuming the
one authorized launch. Source: 07a's preserved Gate-2 record
(`pr_07a_training_history_diagnosis.md` §14.4), which ran the SAME canonical
posture on the SAME host.

**Finding 1 — `floor_seconds 5` would very likely produce a SPURIOUS KILL.**

The floor is not only a masking risk; it is also the **cold-start guard**.
`complete_setup` writes a `real_dataset_setup` prediction whose
`predicted_seconds` IS the measured setup time (`session.py:357-362`), and it is
measurement-backed — so the watchdog arms the moment setup ends:

```text
at setup completion, elapsed ~= S:      D = max(floor, S x factor)
```

Between that instant and the training prediction landing, the trainer must
build the epoch-0 dataset and run ~40 steps for the verifier to stabilise.
07a's attempt 004 measured that window: 125 steps ~9 s of stepping inside a
`train_time_s` of 38.9 s that also holds 26.45 s of validation — leaving
**~3.5 s of epoch-0 dataset construction**, on top of setup.

```text
floor = 5:   setup ends at ~2 s  ->  D = max(5, 3) = 5 s
             dataset construction ~3.5 s  ->  elapsed ~5.5 s  >  D = 5 s
             => KILLED during dataset construction
```

That kill would look exactly like a C5 cold-start FAIL and would in fact be a
posture artifact. 07a's attempts 002/003 corroborate the floor's role: their
enforced deadline was **60.0 s = the floor itself**, i.e. their predicted sum
was below 60 and only the floor carried them that far.

**Finding 2 — `validation_max_portion 0.05` is unnecessary; §17's workload
estimate was wrong for the right answer.**

§17 projected ~3 000 validation rows at portion 0.01 (12 PSD x 250). 07a
MEASURED **15 000 rows** at portion 0.01 — because `ml_segs_per_psd` is
`psd_segment_length // seg_size` and the PLANNER chooses `seg_size`; it chose
8 000, not 40 000, giving 1 250 rows per PSD. The `T_act ~35 s` figure was right
by coincidence, not by derivation.

So the canonical 0.01 ALREADY yields validation = 26.45 s against training
9 s — 2.9x — which is ample separation. Raising to 0.05 would multiply
validation ~5x (~130 s), inflating wall time and the envelope for no gain.

**Finding 3 — GPU contention is NOT a blocker.** Two jobs from another user
(`wenyu`) hold 12.4 GiB of the 32.6 GiB card, one running 27 h. 07a's Gate 2
passed on this host "shared with three other users' processes (~7 GB / 85 %
util at launch)". Comparable and precedented; the 24 GiB budget is an admission
ceiling, not a reservation. Recorded, not escalated — and the other users' jobs
must not be disturbed.

**Revised recommendation, derived from measured values (factor 1.5):**

```text
T_hat_train ~ 9 s      T_hat_val ~ 26.45 s      setup ~2 s      T_act ~35.45 s

floor = 15:
    D_old_eff = max(15, (2 + 9) x 1.5)      = 16.5 s   <- the TRAINING term wins,
                                                          not the floor
    T_act                                    = 35.45 s
    D_new_eff = max(15, (2 + 9 + 26.45)x1.5) = 56.2 s

    16.5 < 35.45 <= 56.2                     separation holds
    floor 15 < T_act 35.45                   no floor masking (§4.1)
    cold-start grace 15 s vs ~8.4 s needed   no spurious kill
```

Strictly better than the approved posture on three axes: it keeps 07a's
measured ~13 min wall time instead of inflating it, it removes the
spurious-kill hazard, and `D_old_eff` comes from the training prediction rather
than from the floor — which is the cleaner attribution for the counterfactual.

**HALTED. No launch.** The operator approved `floor 5` / `portion 0.05`;
launching a different posture would substitute my judgement for theirs, and
launching the approved one knowing it will probably die in dataset construction
would waste the single authorized run. Awaiting a revised ruling.

### 18.8 OPERATOR RULING — REVISED GATE POSTURE (2026-08-17, SUPERSEDES §18.1)

The §18.1 posture (`floor 5` / `portion 0.05`) is **VOID**. Authorized instead,
exactly ONE launch:

```text
--validation_max_portion 0.01        --runtime_watchdog
--validation_max_train_samples 2000  --runtime_watchdog_safety_factor 1.5
omit --validation_max_samples        --runtime_watchdog_floor_seconds 15
omit --validation_max_phase_seconds
--no-force_formal_round  --num_iterations 1  --max_rounds 1  --max_epochs 1
--data_scope 4-9  --health_gate_files 4,5,6,7,8,9
--trial_vram_budget_gb 24  --formal_vram_budget_gb 24
cold start (no --seed_paths)  ·  real tiered-pro LLM  ·  real execution
```

`floor 15` is a **cold-start guard**, sized to cover
`subprocess start -> setup prediction -> dataset/loader construction ->
training verification` while staying below the expected validation-completion
elapsed. `D_old_eff == 15` (the floor winning the raw comparison) does NOT by
itself make the Gate inconclusive; floor masking is `floor >= T_act_elapsed`.

#### 18.8.1 CORRECTION TO THE GATE EVIDENCE CONTRACT — the clock basis

A frozen-design bug the operator caught at consistency check. §4.1 defines

```text
T_act = training actual + SUM(validation actual)
```

but the deadline is **TOTAL ELAPSED SINCE SUBPROCESS START**, and `D_old`
already contains the setup prediction, so the two sides had different time
origins. 07a further pins the training ACTUAL as *admission -> last optimizer
step, validation subtracted* — not subprocess elapsed. Corrected:

```text
T_act_elapsed = actual wall elapsed from subprocess start
                through validation completion
```

usable as `setup + training + validation` **only if those exactly partition
the interval**.

**They do not.** Verified from source before the run: `t_train_start` is set
AFTER epoch-0 dataset construction (`train_engine_sandbox.py` — the loader
already exists when the admission block runs), so construction lies in neither
`setup_actual` nor `training_actual`. 07a's attempt 004 measures the residue:

```text
train_time_s 38.9  -  validation 26.45  -  training ~9  =  ~3.45 s unaccounted
```

So a same-origin elapsed cannot be reconstructed EXACTLY from the persisted
actuals. Rather than invent the gap or add recording — both forbidden — the
verdict is taken on a BRACKET, and the ambiguity must not change it:

```text
L = setup_actual + training_actual + SUM(validation_actual)
        lower bound: omits the construction gap and the post-validation tail

U = timing.train_time_s
        upper bound: the PARENT's wall measurement around the whole training
        skill (execution.py:662-664) — same wall clock as the watchdog, but
        opening before Popen and closing after exit

PASS requires the verdict to hold on BOTH:
        D_old_eff < L          old deadline beaten on the most CONSERVATIVE reading
        U <= D_new_eff         new deadline covers the most GENEROUS reading

If the two bounds disagree, the same-origin elapsed is not recoverable to the
precision the verdict needs  ->  INCONCLUSIVE.
```

Projected: `L ~37.5`, `U ~38.9`, `D_old_eff ~16.5`, `D_new_eff ~56.2` — the
bracket is expected to be far from both thresholds, so the gap should not
matter. Projection only; it carries no acceptance weight.

#### 18.8.2 Verdict taxonomy (operator, binding)

| Observation | Verdict |
|---|---|
| `D_old_eff < T_act_elapsed <= D_new_eff`, source `verified_components`, no budget masking, `floor < T_act_elapsed` | **PASS** |
| the 15 s floor fires BEFORE a training prediction is established | **INCONCLUSIVE** — posture/cold-start guard insufficient; **NOT** a C5 semantic failure |
| training pricing established, validation begins, the first validation measurement fails to refresh the stale training-only deadline before it fires | **FAIL** — the C5 cold-start temporal defect |
| `D_old_eff >= T_act_elapsed` | **INCONCLUSIVE** — workload did not discriminate |
| `floor >= T_act_elapsed`, or operator budget masks `verified_components` | **INCONCLUSIVE** |
| external GPU contention / peer-induced OOM, source-supported | **INCONCLUSIVE** — infrastructure-contaminated; never interfere with peer processes |

#### 18.8.3 Pre-launch state

```text
GPU snapshot        /tmp/gate2_gpu_snapshot.txt (captured at launch time)
executable HEAD     3cb6eef1  — byte-identical, re-verified below
executable edits    NONE made by this ruling
C6 source correction  formally ACCEPTED by the operator; no executable change
Milestone-1 audit     BANKED here; PROMOTED to the frozen roadmap by the
                      POST-MERGE 07c finalizer. 07c scope NOT expanded.
```

### 18.9 GATE 2 — RUN 1 RESULT: **FAIL** (C5 cold-start temporal defect, verdict category 2)

```text
launched     2026-08-17, revised posture (§18.8), operator-approved, ONE launch
head         3cb6eef1 executable (repo HEAD 83e2d384; docs-only commits above it)
workspace    /tmp/gate2_07c_1786989517          PRESERVED
gpu snapshot /tmp/gate2_gpu_snapshot.txt        RTX 5090, 12 410 / 32 607 MiB
                                                used by two peer processes (user
                                                `wenyu`) — never touched
chain log    /tmp/gate2_07c.log                 PRESERVED
```

The Gate found a real defect that the entire unit suite missed. That is the
Gate working, not the Gate failing.

#### The decisive artifact

Attempt 1's sidecar at the moment of the kill
(`.../configs/iter_001/runtime_verification_..._iter_001_001.json`):

| component | workload | prediction | actual |
|---|---|---|---|
| setup | — | **1.384 s**, `real_dataset_setup` | 1.384 s |
| training | `optimizer_step` 500 | **55.371 s**, `real_training_verification` (110.74 ms/step) | `None` |
| validation | `validation_sample` **7 500** | **`None`** | `None` |

```text
(1.384 + 55.371) x 1.5 = 85.133 s   ==   the observed deadline, EXACTLY
killed at 86.097 s
```

So the deadline was **training-only**: the validation workload was recorded,
the validation term was not. Attempt 2 reproduced it (75.085 s vs 74.208 s).

#### Root cause — a real C5 implementation defect

`_validation_pass` feeds per-sample timings to the verifier and, when it goes
terminal, executes only:

```python
if verifier.is_terminal:
    verifier = None          # a LOCAL rebinding. Writes nothing.
```

`complete_phase_verification("validation", …)` — the call that actually writes
the sidecar — is at **line 1661**, reached only after `_validation_pass`
RETURNS (line 1628). **The TRAINING path does the opposite and is correct**: at
lines 306-309 it calls `_finish_training_verification(...)` *inside* the batch
loop, so its prediction reaches the sidecar the moment it exists. That is
precisely why the training term landed in time here and the validation term did
not.

Consequence in the 07a regime — the regime 07c exists to fix, where validation
is long by construction — the pass cannot complete before the stale
training-only deadline fires, so the refreshed deadline is never written and
the attempt dies exactly as it did in 07a.

Reconstructed timeline (rates from this run's own measurements):

```text
t~0.0    setup ends, prediction 1.384 s written  ->  D = max(15, 2.1) = 15 s
t~1-5    epoch-0 dataset construction
t~5-60   500 optimizer steps @ 110.74 ms; the training prediction lands early
                                          ->  D = 85.133 s
t~60     validation begins (7 500 rows, batch 4 = 1 875 forward-only batches)
t~61     the validation verifier reaches steady state  ->  BUT NOTHING IS WRITTEN
t 86.1   the stale training-only deadline fires; killed ~26 s into validation
```

Had the prediction been written when it existed, `T_hat_val ~69 s` would have
given `D ~188 s` and the attempt would have survived. **The design is right;
the implementation lands the value too late.**

#### Verdict, against the operator's binding taxonomy (§18.8.2)

> *"training pricing established, validation begins, and the first real
> validation measurement fails to refresh the stale training-only deadline
> before it fires → **FAIL** — the C5 cold-start temporal defect."*

Row 2 matches exactly: training pricing WAS established (`verified_components`,
55.371 s), validation DID begin, and the refresh did not arrive. Explicitly NOT
the other rows — the 15 s floor never fired (the deadline was 85.133 s, well
above it), no operator budget existed, and the peer GPU load did not cause the
kill (the deadline arithmetic matches the predictions to the millisecond).

**Verdict: FAIL.**

#### Why the unit suite missed it, and what that costs

C5's cold-start test asserted assertion 3 ("visible strictly BEFORE the old
deadline fires") against a **hand-written sidecar** — it proved the provider's
arithmetic, never the production WRITE TIMING. The real-trainer reachability
test used the two-family fixture, whose validation pass finishes in
milliseconds, so the post-pass completion always ran in time. Neither could
observe "the value exists but has not been persisted yet".

The missing test is a production-path one: *while a validation pass is still
running, the sidecar already contains a measurement-backed validation
prediction.*

#### Disposition

The fix is small, in-scope and substantive — move the completion inside the
pass, matching the training path's proven pattern — but **any executable change
invalidates this Gate's evidence**, and a second live launch requires a fresh
operator ruling. Halted here; workspace, log, sidecars and GPU snapshot all
preserved.

### 18.10 GATE 2 RUN 1 — FINAL TALLY AND OPERATOR CLARIFICATION APPLIED

```text
launched   2026-08-17T18:18:21Z      stopped 2026-08-17T18:58Z (~40 min)
attempts   9 started
kills      7 watchdog kills, every one just past a `verified_components` deadline
           86.1/85.1 · 75.1/74.2 · 75.1/74.9 · 66.1/65.1 · 41.1/40.6 · 44.1/43.5 · 35.0/34.5
validation 0 passes completed, across all 9 attempts
sidecars   9 preserved
```

**Stopped deliberately at ~40 min**, past the approved 15–30 min envelope. The
failure is DETERMINISTIC — 7/7 identical — so further attempts bought no
information and only spent LLM and GPU. Evidence is on disk; nothing was lost.
Peer processes (user `wenyu`, 12.4 GiB, 28 h and 24 h old) were never signalled
and remained alive throughout; after the stop the GPU showed only their two
PIDs, which is the decisive proof my chain released the device.

#### Why the bracketed-elapsed clarification does not apply to THIS run

The operator's §18.8.1 correction — replacing an exact `T_act` with a rigorous
interval `L <= T_true <= U` — is **accepted and recorded**, and it is the right
discipline. It is simply **moot for this run**: computing `L` and `U` presumes
an attempt that COMPLETED validation, and none did. The verdict here needs no
elapsed quantity at all. It is read directly off the sidecar:

```text
the deadline at the moment of the kill = (setup 1.384 + training 55.371) x 1.5
                                       = 85.133 s   EXACTLY as observed
the validation component  ->  workload 7 500 recorded, prediction ABSENT
```

The validation term was never in the deadline while validation was running.
That is verdict category 2, decided by presence/absence, not by arithmetic.

**The bracket method carries forward to the RE-RUN**, together with its
unmet precondition: `train_time_s` may serve as `U` only once source PROVES its
timer opens no later than `Popen` and closes no earlier than validation
completion. That proof was not needed here and has NOT been done.

#### NEW DEBT — runtime accounting completeness (operator, 2026-08-17)

> Runtime component actuals do not yet form a complete partition of subprocess
> wall time. In particular, epoch-0 dataset/loader construction, between setup
> completion and the start of training timing, is currently unattributed
> (~3.5 s in 07a's measured attempt 004).

**Owner: Step 11 — Execution Infrastructure. Banked now; deliberately NOT
fixed in 07c.** The operator's sequencing, recorded because the reasoning
matters more than the item:

```text
07c    bank the debt only
D14    observe Pets/DAVIS as genuinely executable paths and collect
       cross-task lifecycle evidence — HDF5/PSD construction vs image
       loading/batching vs video-window construction — WITHOUT fixing it
Step11 the formal complete-accounting audit
```

Deferring to after D14 is the substantive point: inventing a
`dataset_construction` phase now, from TIDMAD's 3.5 s alone, would freeze one
task's execution pattern into framework semantics — the exact error this whole
upgrade exists to undo. The alternative (redefining where `setup` ends) can
only be judged once more than one task is really executable.

Step 11's audit should check BOTH directions and aim at an invariant:

```text
coverage gap     no interval owned by no phase
double counting  no interval owned by two phases

  =>  every material interval of subprocess execution is owned exactly once,
      or explicitly classified as bounded orchestration overhead
```

### 18.11 C5 PERSISTENCE-TIMING FIX (operator-authorized, narrow)

The Gate-2 attempt-1 defect, fixed inside C5 and nowhere else.

**What changed.** `_validation_pass` gains an `on_verified` callback, invoked
the INSTANT the verifier reaches a verdict — mid-pass, with batches still to
run. The completion itself goes through the existing owner: a single closure
`_finish_validation_verification()` that calls
`RuntimeSession.complete_phase_verification(...)`, whose own `_write_sidecar()`
does the persisting. No second write path was created, and no arbitrary write
was moved.

```text
validation batch 1..k finishes
      -> verifier reaches a verdict
      -> on_verified()  ->  complete_phase_verification  ->  sidecar written
      -> the watchdog can now see a refreshed deadline
      -> batches k+1..N continue
      -> pass ends  ->  full validation ACTUAL recorded (future calibration)
```

One owner, three idempotent call sites (inside the pass; after the pass, for a
verifier that never reached a verdict; at the tail). This is exactly the
pattern the TRAINING path has always used — it completes inside its batch loop,
which is why its term landed in time in attempt 1 while validation's did not.

**Unchanged, as required:** watchdog arithmetic, the deadline provider,
admission, validation workload semantics, C6, runtime phase ownership, and the
training ACTUAL's validation-exclusive definition.

#### The regression, and why it is TWO tests and not twelve

`tests/unit/execute_tools/test_pr07c_validation_persistence_timing.py`. A real
in-process `run_experiment_streaming` with a real `RuntimeVerificationSession`;
the observation is made by a model registered into the live `MODEL_REGISTRY`
whose `forward` reads the REAL sidecar off disk when `self.training` is False —
so nothing in the production path is patched to judge the production path.

```text
The observer records EVERY validation batch (24 of them, batch_size 1), and
the assertion is on the ORDER of events:

    a prediction appeared at batch i,  and  i < total

i.e. batches still ran after it landed — which is exactly "persisted while the
pass was running", with no assumption about WHEN the verifier stabilises.
```

**Corrected after the terminal suite caught it.** The first version observed
from a hard-coded batch 6, chosen from a measured verdict at batch 5. It passed
in isolation and in the affected-suite run, then FAILED in the full suite: under
load the verifier's timings are noisier and the verdict arrives later. That made
it a flaky test of the HOST, not of the code — the same defect class as the 07a
rung diagnosed above, authored by me while diagnosing that one. Re-verified
after the redesign: mutation still RED, and green under the full 1,159-case
`tests/unit/execute_tools/` load.

1. **the regression** — mid-pass the sidecar already holds a validation
   prediction whose source is `real_validation_verification` and is in
   `MEASUREMENT_BACKED_SOURCES`. The source check is part of the same property,
   not a separate one: a prediction C8d filters out is worth exactly as much as
   none.
2. **the fix moved only the write timing** — the four preservation assertions
   the ruling required, on the SAME run rather than as four more tests: the
   full-pass ACTUAL still lands and matches `sum(validation_seconds)`; the
   measured batches are counted exactly once (`predicted == unit_count × rate ×
   safety`, no extra term); the training ACTUAL is still recorded and
   validation-exclusive; no admission verdict moved.

Everything else about validation lifecycle correctness belongs to Gate 2 —
which is what caught this. Deriving a dozen first-batch / sidecar-timing /
validation-length variants here would rebuild the duplication the suite already
suffers from (§18.12).

#### Mutation proof

```text
MUTATION 5 — restore the post-pass-only completion
  site:      _validation_pass, delete the `on_verified()` call (1 site)
  caches:    cleared before and after
  observed:  FAILED test_the_sidecar_holds_a_measurement_backed_prediction_mid_pass
             "the validation pass is STILL RUNNING and the sidecar holds NO
              validation prediction"                                    rc=1
  verdict:   BEHAVIOUR-CHANGING. The regression genuinely pins the timing;
             restored, re-verified 2 passed.
```

A diagnostic run recorded the mechanism directly, batch by batch:

```text
(batch, prediction_present, measured_units)
 (1,False,-) (2,False,-) (3,False,-) (4,False,-)
 (5,True,3) (6,True,3) ... (12,True,3)      verifier state: "verified"
```

#### A pre-existing flaky rung, proven not caused by this fix

The affected-suite run showed one failure —
`test_step07a_c2_transport.py::TestRungB07a2ValidationScopeAxis::
test_real_trainer_emits_r2_and_r3_over_the_validation_family` — at
`assert abs(r3 - train_ref) > 1e-4`, observed `6.38e-05`.

Diagnosed before touching anything, and **proven pre-existing** rather than
asserted: the pre-fix production file was checked out from `1ecd448e` and the
rung run six times against it.

```text
PRE-FIX BASELINE, |r3 - train_ref| across six runs:
    9.38e-4 · 3.99e-3 · 1.76e-3 · 1.84e-3 · 7.68e-4 · 1.52e-4
                                                      ^^^^^^^
                                          only 1.5x the 1e-4 threshold,
                                          with this fix nowhere in the picture
```

The rung's discriminating margin is nondeterministic run to run and routinely
lands within a small factor of its own threshold; `6.38e-5` is inside that
natural spread. The fix cannot influence it either: it adds a callback that
writes a sidecar file and touches no tensor, no RNG, no data order and no
weight, so `r3` is not a function of it.

**Not fixed here.** Loosening a threshold to make a suite green is exactly the
move the standing rules forbid, and the honest correction — a marginal
statistical assertion that probably wants to be Gate-owned or made robust —
belongs to the Test Architecture & Suite Pruning PR (§18.12), where it is now
banked as a concrete example.

### 18.12 NEW DEBT — test architecture and suite pruning (operator, 2026-08-17)

Raised while reviewing this Gate. **Explicitly NOT 07c scope**, and the
sequencing is the operator's:

```text
07c   narrow C5 fix -> regression -> corrective Gate 2 -> PASS -> MERGE
next  a dedicated Test Architecture & Suite Pruning PR
then  D14
```

Not folded into 07c: this PR already carries a real Gate FAIL and its
corrective evidence, and mixing a multi-thousand-case deletion in would wreck
review and attribution. Before D14 specifically, because D14 makes Pets/DAVIS
executable and will induce a fresh wave of tests — 10k becomes 12–15k unless
the philosophy is fixed first.

**This Gate is the argument.** 9,967 unit cases were green, including a
purpose-written cold-start temporal test, and the defect still shipped: the
unit test asserted against a hand-written sidecar that was ALREADY updated, so
it could not see a lifecycle bug about WHEN production writes. One real
subprocess found it immediately.

The three-layer ownership to be formalised:

| Failure class | Authority |
|---|---|
| syntax / lint | Ruff |
| typing | Pyright |
| ordinary schema type / range / default | Pydantic |
| deterministic local semantics, identity/hash/serialisation, arithmetic, named regressions | Unit |
| prompt → real LLM structured behaviour | **Gate 1** |
| real data / GPU / subprocess / sidecar timing / lifecycle | **Gate 2** |

Every new test must answer: *if I delete this, which concrete bug escapes that
Ruff, Pyright, Pydantic, another unit test, Gate 1 and Gate 2 all miss?* No
answer ⇒ do not add it. And no new PR may default to "add a few more unit tests
to be safe" — the design must name the owning layer first.

Working target ~5,500–6,500 collected cases (a 35–45 % reduction), but the
merge criterion is NOT the number: every deleted class must name its
replacement authority. Prior audit evidence to reuse: ~725 cases already
identified as losslessly removable (428 parametrised cases with no independent
risk, 185 duplicating Pydantic/type-system guarantees, 66 direct Gate replicas),
the launcher guardrail parametrised across 383 files where 322 cases only
re-prove "this file contains no subprocess call", and 62 real-LLM/real-GPU
tests that only assert `status == "completed"`.

Two phases: mechanical deletion first (static-tool duplicates, vacuous
assertions, Gate replicas, superseded historical tests), then behavioural
consolidation — which must preserve genuinely distinct equivalence classes. The
tuner's pre-flight resource refusal, runtime admission refusal and post-hoc OOM
look alike and are three different semantics; collapsing them into one
"resource failure" test would be a loss, not a saving.

### 18.13 GATE 2 ATTEMPT 2 — **INCONCLUSIVE (infrastructure-contaminated)**

Not a 07c result. The run never reached the phase the Gate exists to test.

```text
launched   2026-08-17T19:56:52Z at 494a90aa (fix + robust regression)
workspace  /tmp/gate2b_07c_1786996612        PRESERVED (fresh; attempt 1 untouched)
log        /tmp/gate2b_07c.log               PRESERVED
stopped    ~30 min, by decision, with zero progress for the last ~13 min
posture    exactly as authorized in §18.8 — floor 15, factor 1.5, portion 0.01
```

Progress: proposer succeeded (candidate `compact_spectral_gated_tcn_coldstart_v1`)
after 4 API timeouts; the IMPLEMENTOR call then timed out **10 consecutive
times**, backoff capped at 60 s, and the chain never reached training. No
training, no validation, no sidecar — nothing the counterfactual needs.

**Diagnosed, not assumed.** An independent probe with the project's own key:

```text
gpt-5.5, small prompt, timeout=120s   ->   OK in 1.3 s
```

So the API is up and fast. The failure is specific to the implementor's LARGE
code-generation request exceeding `llm_bridge`'s 120 s client timeout
(`agent/llm_bridge.py:375,382,417`) against a reasoning-heavy model. The
proposer beat the same timeout after 4 tries; the implementor's prompt is
bigger and did not.

Verdict per the operator's taxonomy row 5: **INCONCLUSIVE —
infrastructure-contaminated**, source-supported. NOT a C5 failure and NOT a
posture failure: the priced-deadline code under test never executed.

Stopped rather than left retrying, because `max_retries=None` is infinite by
design and each timed-out attempt still bills reasoning tokens against a run
that had made no progress in 13 minutes. Peer GPU jobs untouched throughout.

**Open operator decision.** A relaunch on the SAME SHA after a PROVEN external
transient is what the standing rules contemplate, but §18.8 authorized exactly
one corrective launch, so it needs a fresh ruling. Worth noting for that
decision: 07a's Gate 2 ran this same config end to end in 13 min on 2026-08-16,
so this is today's API latency rather than a standing configuration defect —
and the 120 s implementor timeout is a candidate contributing factor that is
NOT 07c's to change.

### 18.14 INFRA PR #218 MERGED, 07c REBASED — Gate 2 attempt 3 pre-flight

#### PR #218 (the attempt-2 blocker)

```text
merged      2026-08-17T21:47:36Z, squash 2e3359df00dab2440b30097028c18158895d9173
scope       request timeout 120s -> 600s (the SDK's own default) + a bounded,
            SEPARATE timeout-retry budget (3 total attempts)
unchanged   429/quota retry stays unbounded — the documented operator semantics
            (top up the balance, the chain resumes) is not touched
evidence    exact-head CI 32068881538 SUCCESS on 2e35aa91
            local full suite at 2e35aa91: 9,832 passed / 3 skipped / rc=0
            mutation: removing the bounded budget makes the regression HANG,
            literally reproducing the production symptom
```

#### 07c rebase

```text
rebase      1296726e -> 8ac03e7e onto master 2e3359df
conflicts   NONE (rc=0, 15 commits replayed)
forecast    a disposable worktree predicted exactly this before #218's CI
            finished, so the outcome was known rather than discovered
```

**Executable delta, proven byte-exact:**

```text
git diff 494a90aa <rebased> -- (excluding docs/*.md/reports)
    agent/llm_bridge.py                                  118 +-
    tests/.../test_request_timeout_and_bounded_retry.py  150 +

    15,712 bytes  ==  the merged #218 patch, byte for byte (cmp -s)
```

So the previous 9,969-case terminal evidence at `494a90aa` remains evidence for
the 07c portion, and the full suite was NOT re-run — per the evidence-economy
rule and the operator's explicit instruction.

#### The six pre-authorized Gate conditions — VERIFIED

| # | Condition | Evidence |
|---|---|---|
| 1 | #218 semantics = transport timeout/retry only | 2 files, both #218's; quota semantics asserted unchanged at closeout |
| 2 | no substantive rebase conflict | rebase rc=0, zero conflicts |
| 3 | executable diff vs `494a90aa` == exactly the #218 delta | `cmp -s` byte-identical, 15,712 B |
| 4 | focused + infra tests + lint green | 454 passed rc=0; ruff clean, 955 files |
| 5 | Gate posture unchanged | portion 0.01 · train 2000 · factor 1.5 · floor 15 · both ceilings omitted · cold start |
| 6 | fresh workspace | new path; attempts 1 and 2 preserved under `reports/gate2_evidence_pr07c/` |

#### Evidence preserved out of /tmp

`reports/gate2_evidence_pr07c/` (gitignored, durable): attempt 1 (148 files,
806,391 B) and attempt 2 (9 files, 42,786 B), byte-verified against their
sources, plus both chain logs, both GPU snapshots, and `gate_verdict.py`.

#### The verdict analyzer, validated before use

`gate_verdict.py` replays the REAL `_watchdog_deadline_provider` over a sidecar
with and without the validation component. Validated against attempt 1 BEFORE
attempt 3 existed: from the sidecar alone it reproduced that run's exact
enforced deadline — **85.133 s**, matching the chain log to the millisecond —
and returned FAIL on the absent validation prediction.

#### `U` upper bound, source-proven

`timing.train_time_s` opens at `execution.py:660`, before `_run_skill` reaches
`Popen`, and closes at `:662`, after `execute_training` returns — which happens
only after `proc.communicate()` sees the child exit, and validation completes
inside the child before exit. Therefore `T_true <= train_time_s = U`. The
`round(..., 1)` shaves at most 0.05 s, two orders below the ~3.45 s pre-Popen +
tail margin measured in 07a.

### 18.15 GATE 2 ATTEMPT 3 — **PASS**

```text
launched   2026-08-17T22:03:22Z    executable head 8ac03e7e (07c rebased onto 2e3359df)
workspace  /tmp/gate2c_07c_1787004202     chain rc = 0     wall ~17 min
posture    exactly §18.8: portion 0.01 · train 2000 · watchdog ON · factor 1.5 ·
           floor 15 · both validation ceilings OMITTED · cold start · tiered-pro
candidate  wavenet24_fullspectrum_ce_coldstart (real proposer/implementor/validator)
preserved  reports/gate2_evidence_pr07c/attempt3_PASS/ (44 files) + chain log + GPU snapshot
```

The full real path executed: **training → validation → inference → scoring**.
Neither earlier attempt reached even the first of those transitions.

#### The C5 fix, observed live

At **5:47 elapsed**, with the pass still running, the live sidecar read:

```text
final_status: verified_validation
  setup       pred   2.15   real_dataset_setup
  training    pred 189.59   real_training_verification
  validation  pred 187.13   real_validation_verification      <-- PRESENT, mid-pass
  (no inference component yet)
```

That is precisely what attempt 1 could not do. And the run was, at that moment,
**347 s in — already past the 287.61 s deadline the pre-07c code would have
enforced.** The counterfactual demonstrated itself in real time before the run
even finished.

#### Verdict, computed from the run's own artifacts

Replaying the REAL `_watchdog_deadline_provider` over the persisted sidecar:

```text
D_old_eff  = (2.15 + 189.59)          x 1.5 = 287.61 s   source verified_components
D_new_eff  = (2.15 + 189.59 + 187.13) x 1.5 = 568.31 s   source verified_components

L = setup 2.15 + training 189.45 + validation 190.99      = 382.59 s
U = timing.train_time_s                                    = 384.30 s

    D_old_eff 287.61  <  L 382.59  <=  T_true  <=  U 384.30  <=  D_new_eff 568.31
```

| PASS condition | Result |
|---|---|
| `D_old_eff < L` | 287.61 < 382.59 ✓ |
| `U <= D_new_eff` | 384.30 ≤ 568.31 ✓ |
| `D_new` source == `verified_components` | ✓ |
| watchdog floor < L | 15.0 < 382.59 ✓ — no floor masking |
| no operator-budget masking | budget is `None` ✓ |
| validation persisted early enough to refresh the deadline | ✓ observed live at 5:47 |
| functional criteria | chain rc=0; real candidate; train/infer/score all executed; `gate_action` recorded |

**VERDICT: PASS.** The bracket is only 1.71 s wide and both bounds sit on the
same side of both deadlines, so the unattributed epoch-0 construction gap cannot
change the conclusion.

#### An analyzer defect found and corrected — disclosed, because the correction came after seeing a result

The first run of `gate_verdict.py` returned INCONCLUSIVE with
`D_old_eff = 501.41`. Diagnosis: it computed the counterfactual over the FINAL
sidecar, which by then also held an `inference` component (pred 142.53) written
later by a SEPARATE subprocess. The training-phase watchdog never saw it, so
including it inflates `D_old_eff` with a term that did not exist at the moment
in question.

Changing an analysis after seeing its output is a bias risk, so the
justification is stated on principle and on contemporaneous evidence, not on the
outcome:

* **Principle** — the counterfactual asks what the TRAINING-phase watchdog would
  have enforced. Only components present during training may contribute. This is
  correct regardless of which verdict it produces.
* **Contemporaneous evidence** — the live sidecar read at 5:47, *before the run
  finished*, contained setup + training + validation and no inference, and the
  `D_old_eff = 287.61` computed from it then is exactly the value the corrected
  analyzer produces now.
* **Regression** — attempt 1 still reads **FAIL** through the corrected
  analyzer, so the change did not simply make everything pass.

The analyzer now scopes the counterfactual to `{setup, training, validation}`.

#### Peer GPU jobs

Four `wenyu` processes were present throughout and none was signalled; all four
were still running after the Gate completed. The Gate's own process released the
device on exit.
