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

*(empty — filled per commit, immediately after each implementation and test
checkpoint, per the incremental-doc rule. Every `[ ]` above becomes `[x]` only
with recorded evidence: exact command, counts, wall time, return code. A test
that could not be run is recorded as not run, with the reason, and never
claimed as passed.)*
