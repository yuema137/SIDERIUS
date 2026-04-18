# Resource Estimator (Time + VRAM Budgets)

**Status**: time skill implemented + smoke-tested on lilab (Phases A–G complete; H1a lilab direct-skill smoke verified 2026-04-16; **Phase I — trial/formal budget split — landed 2026-04-16 across 5 commits**; **Phase J — success-path time info to planner — landed 2026-04-16 across 3 commits**; **H1b lilab tuner-integration smoke verified 2026-04-16 on RTX 5090, k(wavenet)=4.22**; H2 SDSC deferred). **Phase K — VRAM budget gate alongside the time gate — design landed 2026-04-18; K.0–K.2 implemented 2026-04-18; K.2.5 (3-phase × 2-resource estimator distribution: training/inference/scoring × VRAM/time) and K.3+ pending.**
**Author**: design discussion 2026-04-16; Phase K extension 2026-04-18.
**Motivation**: two trial-mode runs (`exploit_cnn_v1`, `explore_novel_v1`) stalled in Round 1 for 1h 50min and 2h 27min respectively, both blowing past the 1-hour trial budget stated in the expert advice. Neither was blocked, because the planner has no pre-flight wall-time estimate — only a VRAM check. **Phase K motivation (2026-04-17)**: `explore_novel_v1` iterations 3 and 4 burned 9/9 attempts each to `"GPU has only 0.01 GB free"` because the existing VRAM gate uses momentary `free_bytes × 0.8` as its limit and another process held 25.7 GB on the shared 32 GB card. The planner has no operator-supplied VRAM ceiling to optimise against — symmetric to the time-gate gap §1.2 fixed.

## Progress log

| Phase | Date | Commit | Tests |
|---|---|---|---|
| A — scaffold + design doc | 2026-04-16 | `ca283cf` | n/a |
| B — step-count math + static ms/step | 2026-04-16 | `2166c13` | 22 evaluate_time_skill unit tests |
| C — real-dataset GPU warmup | 2026-04-16 | `380e82c` | warmup path covered via monkeypatch |
| D — workflow + CLI (`f7d2f04`) | 2026-04-16 | `f7d2f04` | n/a (wiring) |
| E0 — schemas + protocols (interp→prop, prop→impl, valid→tune) | 2026-04-16 | `f76bb8a`, `6d8c104`, `3ba870c`, `7c0e107` | covered by per-protocol suites |
| E1 — tuner [Step 0.5/3] gate | 2026-04-16 | `458361d` | 6 new TestTimeBudgetGate tests (140 tuner total) |
| E2 — proposer baseline gate | 2026-04-16 | `f6e3b19` | 11 new tests (240 proposer total) |
| F — per-GPU calibration (asymmetric EMA) | 2026-04-16 | `12813a0` | 29 new calibration tests (409 tuner+proposer total) |
| G — `.gitignore` housekeeping | 2026-04-16 | (this commit) | n/a |
| H1a — lilab direct skill smoke (RTX 5090) | 2026-04-16 | (no commit — `/tmp/smoke_h1a.py`) | wavenet+punet real warmup, k=1.25 EMA round-trip from disk |
| I — trial/formal budget split (schema + CLI rename) | 2026-04-16 | `29cd956`, `485250e`, `358dded`, `b6b680d`, `b51be8e` | 53 protocol + 17 proposer-gate + 36 tuner-gate Phase-I tests pass |
| J — success-path time info to planner | 2026-04-16 | `bbbc174`, `265bfb5`, `4b8fb94` | 5 schema + 3 success-path + 1 skipped-record Phase-J tests pass (182 tuner total) |
| H1b — lilab tuner-integration smoke | 2026-04-16 | `17ab26e` (CLI fix) + this commit (doc) | RTX 5090, run_name=h1b_test_a, k(wavenet)=4.22 after 2 history entries; Test A composite covered Tests B+C |
| H2 — SDSC smoke run (Slurm batch, chained) | deferred | — | gated on H1b passing; tests batch-system specifics (env-var override, GPU stability across restarts, concurrent-writer safety) |
| **K — VRAM budget gate (design)** | 2026-04-18 | (this commit) | design only; **tuner-side only**; sub-phases K.0–K.7 below |
| K.0 — skill rename `evaluate_resource_skill` → `evaluate_vram_skill` | 2026-04-18 | `7bb167e` | mechanical rename + caller update |
| K.1 — schema additions on `HyperparamTuningInput` + `ExperimentMemory` (no proposer-side fields) | 2026-04-18 | `7104993` | mirrors Phase I.1 + J.4, tuner-only scope |
| K.2 — skill `vram_budget_gb` kwarg + contention-detection log | 2026-04-18 | `888dd61` | budget vs free-VRAM `min`; 18/18 skill tests |
| K.2.5 — distribute per-phase estimators to owning skills (3 phases × 2 resources) | pending | — | per-phase `estimator.py` in training/inference/scoring skills exporting both `estimate_peak_bytes` and `estimate_wall_time_seconds`; `core/inference_defaults.py` + `core/scoring_defaults.py`; both resource wrappers become thin aggregators (VRAM=peak, time=sum) |
| K.3 — tuner per-mode pick + `vram_estimate_gb` in success/skipped memory | pending | — | mirrors I.2 + J |
| K.4 — protocol pass-through (`valid→tune` budget kwargs only; **no** proposer-side `vram_risk` plumbing) | pending | — | mirrors I.3, narrowed scope |
| K.5 — CLI + workflow fan-out (tuner-side only) | pending | — | mirrors I.4 |
| K.6 — planner prompt: numeric budget block + decision tree | pending | — | new prompt section, replaces abstract "GPU MEMORY RULES" |
| K.7 — iteration-boundary gate-exhaustion feedback to proposer | pending | — | new schema `GateExhaustionInfo`; surfaces to next-iteration proposer when no attempt ever trained |
| K.8 — explore_novel re-launch under contention | pending | — | acceptance: rejects against budget not free-VRAM; gate-exhaustion path also exercised by deliberately under-budgeting one iteration |
| K.deferred — proposer `_apply_vram_gate` + `vram_risk` field + retire `time_risk` redundancy on `ProposalOutput` | deferred | — | gated on registering plugins pre-validation; tracked in §10.17 |

---

## 1. Problem Statement

### 1.1 What happened

Both runs were killed mid-training on 2026-04-16 with no experiment completed. Step-count arithmetic (at `batch_size=1, train_portion=1.0, epochs=1`, sample_set of 400 PSD segments):

| Run | `seg_size` | ml_segs/PSD | total steps | observed ms/step | projected train time |
|---|---|---|---|---|---|
| `exploit_cnn_v1` | 16000 | 625 | 250,000 | ~26 ms | ~1.8 h (unfinished) |
| `explore_novel_v1` | 1250 | 8000 | 3,200,000 | ~2.7 ms | ~2.4 h (unfinished) |

The explore run chose `seg_size=1250` to stay under the 4 GB VRAM ceiling, which inflated step count 12.8×. `evaluate_resource_skill` returned `Feasible: YES` in both cases because it only checks VRAM.

### 1.2 Root cause

`agent/skills/evaluate_resource_skill/wrapper.py` returns only a VRAM verdict. Time cost is absent from the planning gate. The LLM's expert-advice prose says "each trial must complete within 1 hour" but nothing enforces it — the planner is free to pick configs whose step count × ms-per-step exceeds the budget by an order of magnitude.

### 1.3 Secondary issue (out of scope here — tracked separately)

`run_exploration_adaptive.py:187-191` forces `is_trial/trial_portion/train_portion/eval_portion` via `plan_overrides`, but the LLM is never told this in the planning prompt. It keeps proposing values for those fields that get silently replaced. Fix is a prompt-only change and is addressed in a separate follow-up (not this doc).

---

## 2. Solution

Add a new atomic skill `evaluate_time_skill` that:

1. Computes **exact step counts** for training (and, in phase 2, inference) from `sample_set`, `PSD_SEGMENT_LENGTH`, `seg_size`, `train_portion`, `batch_size`, `epochs`.
2. Measures **ms-per-step** by running a 3-batch GPU micro-warmup with the actual model, loss, and optimizer on synthetic tensors of the correct shape.
3. Projects **total wall-time** = steps × ms-per-step, compares against a configurable budget, returns `feasible` / `verdict` / `suggestion` in the same shape as `evaluate_resource_skill`.
4. Is invoked as `[Step 0.5/3]` in the tune agent — after VRAM check passes, before training. On time-budget failure, skip the attempt and record `skipped_time_risk` (parallel to `skipped_oom_risk`).

### 2.1 Design choices

| Decision | Chosen | Rationale |
|---|---|---|
| Skill or extend `evaluate_resource_skill`? | **New skill** (`evaluate_time_skill`) | Clean separation: one checks VRAM, one checks wall-time. Easier to toggle, test, extend. Matches user's "add it as a skill" preference. |
| Static formula vs live warmup? | **Live warmup** (3 fwd+bwd batches, discard first as warmup, average last two) | Step count varies 12× between configs; models introduce spectral/attention ops a static formula can't capture. Overhead ~2–5 s per plan — cheap relative to 2-hour blowups. Also makes the estimate **self-calibrating per server** (see §2.6). |
| Budget source? | **CLI flag** `--time_budget_minutes` on `run_exploration_adaptive.py`, default 60 | Decouples enforcement from advice prose. Advice stays human-readable; the number is a system constant. |
| Include inference estimate? | **Phase 2** — train-only in phase 1 | Train was the sole cause of the 1h 50min / 2h 27min blowups. Inference adds code surface for a smaller effect. Phase 2 extends the same skill. |
| Placement in tune loop? | `[Step 0.5/3]` between VRAM check and training | Matches existing gate pattern. Both gates use the same `skipped_*` record format and don't burn a tuning round. |
| Cross-server accuracy? | **Live warmup + safety multiplier + post-hoc calibration file** | No hand-maintained per-server constants; see §2.6 for details. |

### 2.2 Step-count formulae

```
train_steps_per_epoch = ceil(
    n_train_psd_segs × (PSD_SEGMENT_LENGTH // seg_size) × train_portion / train_batch_size
)
total_train_steps     = train_steps_per_epoch × epochs

inference_steps       = ceil(                                       # phase 2
    n_eval_psd_segs × (PSD_SEGMENT_LENGTH // seg_size) / inference_batch_size
)
```

Where `n_train_psd_segs = sum(len(v) for v in train_sample_set.values())`, `PSD_SEGMENT_LENGTH = 10_000_000` (from `execute_tools.dataset_config`). `inference_batch_size` uses the per-model defaults from `sandbox_executor.py` (phase 2).

### 2.3 Skill output schema

```python
{
    "status":           "success" | "error",
    "feasible":         bool,
    "verdict":          str,    # "✅ FITS" / "❌ OVER BUDGET" with numbers
    "suggestion":       str,    # e.g. "Reduce num_blocks" or "Increase seg_size to X"
    "estimated_minutes": float,
    "limit_minutes":     float,
    "breakdown": {
        "total_train_steps":   int,
        "ms_per_step":         float,
        "warmup_batches":      int,
        "train_minutes":       float,
    },
    "message":           str,   # on error only
}
```

### 2.4 Suggestion logic

On over-budget, pick the dominant lever:

1. If `seg_size < 10_000` and `train_batch_size == 1` → suggest raising `batch_size` first (amortizes fixed per-step cost without changing model capacity).
2. Else if `ms_per_step > 50 ms` → suggest reducing model depth/width (`num_blocks`, `hidden_channels`, `embedding_dim`).
3. Else (many cheap steps) → suggest raising `seg_size` to the next valid divisor of 10,000,000.

The tuner surfaces this to the reflector as `memory_update` on the `skipped_time_risk` record, the same way the VRAM gate does today.

### 2.5 Safety multiplier

Projected wall-time is multiplied by `SAFETY_MULTIPLIER = 1.1` before comparison with the budget. Tight (10%) because the real-dataset warmup in §2.6.3 already measures the DataLoader / HDF5 path — the multiplier only has to absorb first-step autotune and minor variance. Declared at the top of `wrapper.py` so it's trivial to tune.

### 2.6 Cross-server accuracy & learning from experience

#### 2.6.1 Why this matters

We run on **at least two substantially different GPUs**, with different disks and contention profiles:

| Server | GPU | Peak FP32 | Filesystem | Notes |
|---|---|---|---|---|
| lilab | RTX 5090 (32 GB) | ~50 TFLOPS | local SSD | single-user |
| SDSC Expanse `gpu-shared` | V100 (16 GB) or A100 (40/80 GB) | 15.7 / 19.5 TFLOPS | Lustre (shared) | shared node; thermal + I/O contention |

A given config can be 2–3× slower on V100 than on RTX 5090. Hand-maintained per-server constants would rot on every upgrade or partition reassignment. Design imperative: **every signal that affects wall-time enters the estimate measurably, and every past run teaches the estimator for next time.**

#### 2.6.2 Signals in → estimate out

Every factor that changes wall-time has an explicit path into the estimate. Nothing is assumed constant across servers.

| Signal | Where it enters | How it enters |
|---|---|---|
| **GPU hardware** (FLOPs, VRAM bandwidth) | live warmup | real CUDA kernel runs on the actual device |
| **Kernel launch / PCIe latency** | live warmup | `.to(device)` on each warmup batch |
| **Model class + ops** (FFT, attention, conv) | live warmup | warmup instantiates the actual `MODEL_REGISTRY[model_type]` |
| **Model config** (seg_size, channels, depth) | live warmup + step count | warmup uses real model; step count formula uses real seg_size |
| **Batch size, loss type** | live warmup | real optimizer.step() with real criterion |
| **Sample set size** (number of PSD segments) | step count | `sum(len(v) for v in sample_set.values())` |
| **Epochs, train_portion** | step count | scales total step count |
| **Disk / filesystem** (lilab SSD vs SDSC Lustre) | live warmup | warmup reads 1 real PSD from the real `data_dir` via `TIDMADEpochDataset` |
| **DataLoader overhead** (num_workers, collate) | live warmup | warmup iterates the real `DataLoader` object, same constructor args as training |
| **HDF5 dataset build per epoch** | learned correction `k` | amortised over a full epoch, so not captured per-step by warmup; absorbed into `k` from past runs |
| **Thermal / shared-node contention** | learned correction `k` | past runs on the same GPU reveal systematic slowdown |
| **cuDNN autotune first-step spikes** | safety multiplier | absorbed by the 1.1× multiplier (tight because warmup uses real data) |
| **Past accuracy / mistakes on this hardware** | learned correction `k` (asymmetric EMA) | every completed run updates `k`; violations correct faster than accurate estimates (§2.6.5) |

Put differently: server, loader, model, and past accuracy all feed in — the first three via a real measurement taken seconds before the gate decision, the last via a persistent learned correction per (GPU, model_type).

#### 2.6.3 Real-dataset warmup (not synthetic tensors)

Original draft proposed synthetic tensors. Switching to a **real-dataset warmup** so disk + DataLoader + HDF5 path are directly measured rather than formula-estimated.

```python
# Mini sample_set: 1 PSD segment from 1 file (~10 MB read, ~100 ML batches at seg=100_000 or fewer at larger seg)
mini_sample_set = {next(iter(sample_set)): sample_set[next(iter(sample_set))][:1]}

dataset = TIDMADEpochDataset(data_dir, mini_sample_set, seg_size, train_portion=1.0, rng=Random(0))
loader  = DataLoader(dataset, batch_size=train_cfg.batch_size, shuffle=False, drop_last=True)

# 3 fwd+bwd steps: discard step 0 (allocator/autotune), time steps 1 and 2
it = iter(loader)
for step in range(3):
    x, y = next(it)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    # standard train step ...
    torch.cuda.synchronize()
    if step > 0: timings.append(time.perf_counter() - t0)

ms_per_step_warmup = 1000 * mean(timings)
```

Cost: one HDF5 file open, ~20 MB read, 3 GPU steps. Total ~1–3 s on either server. This replaces the formula-based DataLoader guess with a direct measurement, tightening the safety multiplier from 1.25× to 1.1×.

Fallback path for CPU / no-data-dir: static formula `ms_per_step ≈ params × seg_size × 1e-9 s` with a printed warning. Used only in unit tests.

#### 2.6.4 GPU / server identification

Identify by the **GPU, not the hostname**. Use `torch.cuda.get_device_name(0)`, which yields stable portable keys (`"NVIDIA GeForce RTX 5090"`, `"Tesla V100-SXM2-16GB"`) that survive SDSC node reassignment.

The calibration file is keyed on this GPU name, slugified:

```
{HOME}/.siderius/time_calibration_{gpu_slug}.json   # e.g. time_calibration_nvidia_geforce_rtx_5090.json
```

Lives outside the workspace so it persists across runs. Ignored by git — each machine builds its own.

#### 2.6.5 Learning from experience (asymmetric EMA)

Every experiment that completes training writes a record linking prediction to reality:

```json
{
  "gpu_name":             "NVIDIA GeForce RTX 5090",
  "model_type":           "dual_context_skip_fuser",
  "seg_size":             16000,
  "batch_size":            1,
  "total_steps":          250000,
  "warmup_ms_per_step":    21.2,    // what we measured at pre-flight
  "actual_ms_per_step":    26.05,   // train_time_s * 1000 / total_steps
  "ratio":                 1.229,   // actual / warmup
  "estimated_minutes":     110.4,   // what the gate predicted
  "actual_minutes":        108.5,   // ground truth
  "estimate_violated":     false,   // actual / estimated > 1.0
  "timestamp":             "2026-04-16T13:45:00Z"
}
```

The correction factor `k(gpu, model_type)` is maintained by an **asymmetric EMA**:

```
r = actual_ms_per_step / warmup_ms_per_step

if actual_minutes > estimated_minutes:   # we under-predicted → punish hard
    k_new = α_up   * r + (1 - α_up)   * k_old      # α_up   = 0.5
else:                                     # we over-predicted → drift gently
    k_new = α_down * r + (1 - α_down) * k_old      # α_down = 0.1

k_new = clip(k_new, 0.5, 5.0)                      # prevent pathological runs from poisoning
```

Rationale: a missed budget (estimate too low) is the expensive failure mode — it wastes hours. An over-cautious estimate only costs the LLM a slightly smaller config. So learning asymmetrically toward safety is the right bias. `α_up > α_down` makes every mistake correct 5× faster than every success. The clip prevents a single broken run (e.g. segfault mid-training) from corrupting the table.

Lookup falls back in order: `(gpu, model_type)` → `(gpu, *)` → `1.0`.

Final estimate:

```
ms_per_step_estimate = warmup_ms_per_step × k(gpu, model_type) × 1.1       # safety multiplier
total_minutes        = ms_per_step_estimate × total_steps / 60000
```

#### 2.6.6 Drift detection

If three consecutive runs on the same GPU violate their estimates (`actual_minutes > estimated_minutes`) — even after the EMA has had a chance to correct — emit a warning. This catches qualitative changes the EMA can't track smoothly: driver upgrade, partition switch (gpu-shared → gpu-debug), a neighboring job hogging the node. User intervention: clear the calibration file or investigate the environment.

#### 2.6.7 Calibration timing invariant

`actual_ms_per_step` is computed as `train_time × 1000 / total_train_steps`, so the EMA's accuracy depends on `train_time` being the wall-time of training **and nothing else**. Audited 2026-04-16: in `nodes/ml_hyperparameter_tune_agent.py` the timer is captured tightly around the training subprocess (3 adjacent lines: `t0 = time.time()` → `_run_skill("training_skill", ...)` → `train_time = time.time() - t0`). The skill's wrapper resolves directly to `sandbox.execute_training()` → `subprocess.run(["python", "execute_tools/train_engine_sandbox.py", ...])` — pure subprocess, no LLM call. Inference and scoring are timed in their own separate `t0 → call → t1` blocks; the LLM `brain.reflect()` call runs **after** all three timers are already captured, so its latency cannot pollute any of them. The F3 calibration update (which only consumes `train_time`) therefore sees an uncontaminated measurement.

**Invariant for future edits**: the three timer blocks for train / inference / scoring must remain LLM-free between their `t0` and the matching `time.time() - t0`. Any new LLM call must be placed strictly after all three timers are captured (i.e. in the reflect / commit phase). Adding a `_run_skill` call between `t0` and the timer-end is also safe only if that skill is itself LLM-free (e.g. `evaluate_*_skill` are fine; a future LLM-backed skill would not be).

#### 2.6.8 Accuracy layers summary

| Layer | Captures | Phase |
|---|---|---|
| Real-dataset live warmup | GPU, disk, DataLoader, HDF5 path, model class — all at once | 1 (Phase C) |
| × 1.1 safety multiplier | First-step autotune, minor variance | 1 (Phase D) |
| × learned `k(gpu, model_type)` via asymmetric EMA | Per-epoch HDF5 overhead, thermal drift, systematic mistakes | 1 (Phase F) |
| Drift-detection warning | Hardware/partition changes | 1 (Phase F) |

All four layers are in phase 1. The calibration file is not deferred to "phase 2" — user emphasised *learning from mistake* should be a first-class feature, not a follow-up.

### 2.7 Skill callers: proposer AND tuner

The skill is shared infrastructure, not tuner-internal. Two agents must call it at two distinct decision points:

| Caller | When | What it gates | On failure |
|---|---|---|---|
| `ml_model_proposal_agent` | Before emitting `ProposalOutput.baseline_config` | The proposer's own starting config — the architecture + baseline hyperparameters it's about to hand off | Attach a `time_risk` note to the proposal so the tuner knows round 0 starts tight (see §2.7.4 for the gate-vs-annotate fork) |
| `tune_ml_hyperparam_agent` | `[Step 0.5/3]` each round, after VRAM check | The LLM-planner's per-round `TrialConfig` / formal config | Emit `skipped_time_risk` record, no round consumed |

**Why both**: if only the tuner gates, an infeasible baseline poisons round 0 — the tuner either wastes a round rejecting it or the user has to override. If only the proposer gates, the LLM's per-round edits (e.g. widening `hidden_channels`) can still blow the budget. Gating at both ends closes the loop.

**Why one skill**: a single implementation, calibration file, and test surface. The two call sites differ only in who constructs the input dict — the skill itself is identical.

**Why share the calibration file**: the proposer's estimate benefits directly from the tuner's post-flight learning. A wavenet baseline that proved 30% slower than predicted last run will be adjusted automatically when the proposer estimates the next wavenet baseline. Both agents read from, and the tuner writes to, the same `~/.siderius/time_calibration_{gpu_slug}.json` (§2.6.4). The proposer is read-only against it.

#### 2.7.1 Current state of the relevant schemas (verified 2026-04-16; updated after Phase E0 schema work)

Audit of `agent/schemas/proposal.py` and `agent/schemas/hyperparam_tuning.py`. The training-side trial-mode set on `ProposalInput` **mirrors `HyperparamTuningInput` exactly** — by design, since both nodes' evaluate_time_skill gates must construct the same `sample_set`. Legacy single-file mode (`file_index`, `is_trial=False`) is intentionally absent from `ProposalInput`: modern usage uses `is_trial=True` + `trial_strategy='target'` + `target_files=[N]` when a single file is wanted.

| Field | In `ProposalInput`? | In `HyperparamTuningInput`? |
|---|---|---|
| `file_index` | ❌ no (legacy single-file mode is covered by trial-mode `target` strategy) | ✅ yes (default `6`; ignored when `is_trial=True`) |
| `is_trial` | ✅ yes (default `False`) | ✅ yes (default `False`) |
| `trial_strategy` | ✅ yes (default `"snapshot"`) | ✅ yes (default `"snapshot"`) |
| `trial_portion` | ✅ yes (default `0.1`) | ✅ yes (default `0.1`) |
| `target_files` | ✅ yes (default `[]`) | ✅ yes (default `[]`) |
| `train_portion` | ✅ yes (default `0.1`, matches tuner) | ✅ yes (default `0.1`) |
| `sampling_seed` | ✅ yes (default `None`) | ✅ yes (default `None`) |
| `sample_set` | ❌ no (built inside the node from the trial-mode set) | ❌ no (built inside the node via `build_sample_set()`) |
| `trial_time_budget_minutes` (Phase I) | ✅ yes (default `None`, gate disabled for trial rounds) | ✅ yes (default `None`, gate disabled for trial rounds) |
| `formal_time_budget_minutes` (Phase I) | ✅ yes (default `None`, gate disabled for formal rounds) | ✅ yes (default `None`, gate disabled for formal rounds) |
| `data_dir` | ✅ yes (default `None`) | ✅ yes (default `None`) |

> **Phase I rename**: prior to Phase I both schemas carried a single `time_budget_minutes: Optional[float]`. The single field was applied identically per round regardless of whether the LLM picked trial or formal — so a budget sized for trial would reject every formal round, and a budget sized for formal would let every trial round through unchecked. Phase I splits it into two so each mode has its own ceiling. The skill (`evaluate_time_skill/wrapper.py`) is unchanged: it still takes a single `time_budget_minutes` kwarg; the *caller* picks which budget to pass based on `is_trial`.

The `constraints: List[str]` field on `ProposalInput` holds free-text prose like `'VRAM < 10 GB'`; the numeric channel now lives in the fields above. The `ProposalOutput.time_risk: Optional[str]` field (added in Phase E0) carries the gate-and-annotate suggestion text — see §2.7.4.

#### 2.7.2 Fan-in origin: workflow orchestrator

The trial-mode data-sampling set (`is_trial`, `trial_strategy`, `trial_portion`, `target_files`, `train_portion`, `sampling_seed`) and the budget set (`trial_time_budget_minutes`, `formal_time_budget_minutes`, `data_dir`) are **run-level parameters** — they do not originate in the interpretation agent (upstream of the proposer) or the proposer (upstream of the tuner). They originate at the workflow/CLI entry point (`run_exploration_adaptive.py`) and fan out:

```
CLI args ──► workflow runner ─┬─► ProposalInput(is_trial, trial_strategy, trial_portion, target_files,
                              │                 train_portion, sampling_seed,
                              │                 trial_time_budget_minutes,
                              │                 formal_time_budget_minutes,
                              │                 data_dir)
                              │
                              └─► HyperparamTuningInput(is_trial, trial_strategy, trial_portion, target_files,
                                                       train_portion, sampling_seed,
                                                       trial_time_budget_minutes,
                                                       formal_time_budget_minutes,
                                                       data_dir, ...)
```

The two protocols that carry these fields — `ml_result_interp_to_ml_model_propose.local_full_context` (into the proposer) and `ml_model_valid_to_ml_model_tune.local_validated_model` (into the tuner) — forward them untouched as caller-supplied kwargs. The interpretation agent and the validator never read or modify them; in schema-first terms, they are **workflow context** that both gates must see identically so the proposer's baseline estimate and the tuner's per-round estimate construct the same `sample_set`.

#### 2.7.3 Skill-input construction at each call site

Each caller assembles the same skill input dict from the fields now available on its input schema. Because `ProposalInput` mirrors the tuner's trial-mode set exactly, the two call sites differ only in where `sample_set` comes from:

```python
# In ml_model_proposal_agent, right before returning ProposalOutput:
sample_set = build_sample_set(
    is_trial=input.is_trial,
    file_index=6,                       # ignored when is_trial=True
    trial_strategy=input.trial_strategy,
    trial_portion=input.trial_portion,
    target_files=input.target_files or None,
    seed=input.sampling_seed,
)
# Phase I: pick the budget that matches the mode the proposer is estimating against.
chosen_budget = (input.trial_time_budget_minutes
                 if input.is_trial
                 else input.formal_time_budget_minutes)
result = run_skill(sandbox, **{
    "model_type":          output.model_name,          # proposed name
    "model_config":        output.baseline_config["model_config"],
    "train_config":        output.baseline_config["train_config"],
    "loss_config":         output.baseline_config["loss_config"],
    "sample_set":          sample_set,
    "train_portion":       input.train_portion,
    "time_budget_minutes": chosen_budget,              # Phase I: per-mode pick
    "data_dir":            input.data_dir,
})
# Act on result.feasible per §2.7.4 policy. When chosen_budget is None the gate is skipped
# (one-time warning), same as before but evaluated per-mode instead of globally.

# In ml_hyperparameter_tune_agent, at [Step 0.5/3] each round:
# Phase I: the per-round plan decides trial vs formal, so the budget pick is per-round too.
chosen_budget = (input.trial_time_budget_minutes
                 if plan.is_trial
                 else input.formal_time_budget_minutes)
result = run_skill(sandbox, **{
    "model_type":          input.model_type,
    "model_config":        trial.model_config,
    "train_config":        trial.train_config,
    "loss_config":         trial.loss_config,
    "sample_set":          self.sample_set,                           # already built in __init__
    "train_portion":       input.train_portion,
    "time_budget_minutes": chosen_budget,              # Phase I: per-mode pick
    "data_dir":            input.data_dir,
})
# Act on result.feasible per existing VRAM-gate pattern.
```

Identical shape, identical skill body, identical trial-mode parameterisation of `sample_set` — the only difference is that the tuner caches `self.sample_set` for reuse across rounds, while the proposer builds it once for its single baseline estimate. Both call sites carry **two** budget fields and pick one per call based on the mode the gate is being evaluated against (Phase I).

#### 2.7.4 Design fork: gate-and-revise vs gate-and-annotate

The proposer's failure-mode response is the non-trivial design decision. Two options:

| Option | How it works | Pros | Cons |
|---|---|---|---|
| **Gate-and-annotate** (v1 choice) | Run the skill once. If infeasible, add `time_risk: str` to `ProposalOutput` with the suggestion text. Let the tuner decide: it either accepts and round-0-gates it (emitting `skipped_time_risk`), or overrides. | One call site, no retry loop, proposer stays pure-reasoning. Tuner's existing gate handles the enforcement. | A provably-infeasible baseline still propagates to the implementor + first tuner round — one wasted round in the worst case. |
| **Gate-and-revise** (deferred to v2) | Run the skill inside the proposer. If infeasible, reduce `hidden_channels` / `num_blocks` / raise `seg_size` per the suggestion, re-run the skill, emit only after feasible. | Round 0 of the tuner always starts from a feasible baseline — no wasted round. | Retry loop in the proposer; hard to bound iterations; couples proposer to hyperparameter knobs it otherwise doesn't touch. Requires the proposer to re-instantiate and re-warm-up the model per retry — several GPU seconds × N retries. |

**v1 picks gate-and-annotate**. The extra wasted tuner round is cheap; the retry loop's code complexity + GPU cost is not. If the telemetry later shows >20% of baselines being rejected in round 0, revisit with gate-and-revise.

The new field on `ProposalOutput`:

```python
time_risk: Optional[str] = Field(
    default=None,
    description="Non-None when the pre-flight time estimate exceeds the budget. "
                "Carries the suggestion text (from _suggest_lever) so the tuner "
                "can surface it to the planner as first-round guidance. "
                "None = baseline fits budget.",
)
```

#### 2.7.5 Sample-set construction inside the proposer

The proposer doesn't currently build a `sample_set` — it emits a config and hands off. For the skill call, the proposer needs either:

**Option A (chosen)**: call `execute_tools.sample_set_builder.build_sample_set(...)` directly — the same helper the tuner uses — and pass the result to the skill. Forwarded args are exactly the trial-mode mirror set on `ProposalInput` (`is_trial`, `trial_strategy`, `trial_portion`, `target_files`, `sampling_seed`). Costs nothing; same code path; the skill sees the identical `sample_set` shape the tuner will build for the same workflow context.

**Option B**: skip `sample_set` and pass only `n_train_psd_segs` as a scalar. Requires the skill to accept either shape. Simpler for the proposer; adds a branch inside the skill that exists only to serve one caller. Rejected.

Going with Option A. `build_sample_set` already lives in `execute_tools/sample_set_builder.py` (a neutral, non-circular location), so no relocation is needed — the proposer imports it directly. The trial-mode mirror on `ProposalInput` is what guarantees the two `sample_set` instances are equivalent: same `is_trial`, same `trial_strategy`, same `trial_portion`, same `target_files`. The `sampling_seed` may differ across the two call sites (each auto-generates its own when `None`), but the time estimate is robust to which exact PSD segments are picked, so seed identity across the two gates is not required.

### 2.8 Placement against `ml_model_validator_agent` — code validation vs config feasibility

The time estimator is **not** part of the validator. It is a separate atomic skill, sibling to `evaluate_resource_skill` (the VRAM gate), called at the same two decision points the VRAM check is called at. The validator and the time estimator answer different questions, on different inputs, with different runtime requirements:

| Component | Question it answers | Operates on | Runtime cost | When it runs |
|---|---|---|---|---|
| `ml_model_validator_agent` | Is the proposed plugin code valid? (interface contract, inheritance, importability, schema correctness) | The implemented Python code (one artefact) | LLM call + `importlib` smoke; no GPU | **Once**, after `ml_model_implementor` |
| `evaluate_resource_skill` | Will this config fit in VRAM? | A `(model_config, train_config, loss_config)` triple | CPU model instantiation + memory accounting | **Per-config**: proposer baseline + tuner round |
| `evaluate_time_skill` | Will this config finish within the wall-time budget? | A `(model_config, train_config, loss_config, sample_set, data_dir)` bundle | Real-dataset GPU warmup (~1–3 s) | **Per-config**: proposer baseline + tuner round |

The workflow placement, end to end:

```
Interp → Proposer ─[time + VRAM gate on baseline]─► Implementor → Validator → Tuner ─[time + VRAM gate per round]─► Train
```

#### 2.8.1 Why not fold the time gate into the validator

Three reasons, in order of weight:

1. **Different cardinality.** The validator runs **once** per proposed model; the time gate runs **per-config**. The same validated code can have dozens of configs across tuning rounds, only some of which fit the budget. Merging would either re-run the validator unnecessarily, or split its responsibilities into "code" and "config" halves that no longer match its name.
2. **Different runtime surface.** The validator is deterministic, GPU-free, and runs on every code emission. The time gate needs CUDA + a real `data_dir` to be accurate, with a static-formula fallback for CPU. Coupling them means the validator suddenly inherits a GPU dependency, breaking its current testability and slowing the no-GPU path.
3. **Agent-scoping rule (CLAUDE.md).** "Each agent is scoped to one well-defined category of task." The validator is scoped to **plugin code correctness**; the time estimator is scoped to **config-level wall-time feasibility**. Two well-defined skills are easier to toggle, test, and extend than one fused agent that does both.

#### 2.8.2 Why not fold it into `evaluate_resource_skill` (the VRAM gate)

Even though both are config-level resource gates called at the same two call sites, keep them separate:

- **Different signals.** VRAM is a static accounting calculation against a hardware ceiling; wall-time is a measured + learned quantity with cross-server calibration (§2.6). The two have almost no shared internals.
- **Independent toggling.** A user might disable the time gate (e.g. on formal-mode runs that are *expected* to be long) while keeping the VRAM gate on. Fusing them would force an all-or-nothing flag.
- **Cleanest test surfaces.** The VRAM skill needs no GPU for its unit tests; the time skill's calibration logic is independently testable from its warmup logic. Fusion would entangle three test surfaces (VRAM accounting, warmup, EMA).

The cost of keeping them separate is one extra skill call at each gate site (the proposer baseline and the tuner round). Both are cheap — sub-second for the gate logic — and are called sequentially (`evaluate_resource_skill` first, then `evaluate_time_skill`) so a VRAM failure short-circuits before the more expensive GPU warmup runs. This ordering is intentional: VRAM failures are cheaper to detect and more common in early exploration.

#### 2.8.3 Failure semantics across the two gates

To keep the record schema consistent:

| Gate fails | Tuner emits | Round consumed? |
|---|---|---|
| `evaluate_resource_skill` (VRAM) | `skipped_oom_risk` (existing) | No |
| `evaluate_time_skill` (wall-time) | `skipped_time_risk` (new, §3.1) | No |

Both records carry the same `suggestion` text from their respective skills, surfaced to the planner on the next round so the LLM has explicit feedback rather than a silent rejection. The proposer's analogous failure path is the `time_risk` annotation on `ProposalOutput` (§2.7.4) — there is no `vram_risk` field today because the proposer doesn't currently call the VRAM skill, but adding one is the obvious symmetric extension if/when it does.

---

## 3. Scope

### 3.1 In scope (phase 1)

- New skill `agent/skills/evaluate_time_skill/` with `wrapper.py`, `skill_config.json`.
- **Real-dataset micro-warmup** (1 PSD × 1 file × 3 fwd+bwd batches) for ms-per-step measurement. Falls back to static formula on CPU with a warning.
- **Per-GPU learned calibration file** `~/.siderius/time_calibration_{gpu_slug}.json` with asymmetric-EMA correction factor `k(gpu, model_type)` and drift detection. **Read by both the proposer and the tuner; written only by the tuner** (see §2.7).
- Post-training hook that records `(warmup, actual, estimated, violated)` to the calibration file and updates `k`.
- **Tuner integration** (`[Step 0.5/3]` in `nodes/ml_hyperparameter_tune_agent.py`) — fail → `skipped_time_risk` record, no round consumed.
- **Proposer integration** (gate-and-annotate, §2.7.4) — `nodes/ml_model_proposal_agent.py` runs the skill on its own baseline before returning, attaching a `time_risk` note to `ProposalOutput` when infeasible; no in-place revision in v1.
- **Schema additions** to carry the run-level parameters end-to-end:
  - `ProposalInput` gains the training-side trial-mode mirror (`is_trial`, `trial_strategy`, `trial_portion`, `target_files`, `train_portion`, `sampling_seed`) plus **`trial_time_budget_minutes: Optional[float]`**, **`formal_time_budget_minutes: Optional[float]`** (Phase I), and `data_dir: Optional[str]`. Defaults match `HyperparamTuningInput` so an omitted CLI arg behaves identically across the two gates. Legacy single-file mode (`file_index`, `is_trial=False`) is intentionally not surfaced here — modern usage uses `is_trial=True` + `trial_strategy='target'` + `target_files=[N]`.
  - `ProposalOutput` gains `time_risk: Optional[str]` (gate-and-annotate, §2.7.4).
  - `HyperparamTuningInput` gains **`trial_time_budget_minutes: Optional[float]`** + **`formal_time_budget_minutes: Optional[float]`** (Phase I) and `data_dir: Optional[str]` (the trial-mode set already exists).
- **Workflow fan-out** in `run_exploration_adaptive.py` / `workflows/model_exploration.py`: a single CLI args block populates both `ProposalInput` and `HyperparamTuningInput` with the same trial-mode + budget set (§2.7.2 fan-in diagram).
- **Protocol pass-through**: `ml_result_interp_to_ml_model_propose.local_full_context` accepts the new fields as caller-supplied kwargs and forwards them into `ProposalInput`. `ml_model_valid_to_ml_model_tune.local_validated_model` accepts `trial_time_budget_minutes` / `formal_time_budget_minutes` / `data_dir` (the trial-mode set was already wired) and surfaces `proposal.time_risk` to the tuner's `expert_advice` as round-0 guidance, ordered after spec/inheritance deviation notes.
- CLI flags `--trial_time_budget_minutes` and `--formal_time_budget_minutes` on `run_exploration_adaptive.py` and on each node CLI (`nodes/ml_hyperparameter_tune_agent.py`, `nodes/ml_model_proposal_agent.py`). The single `--time_budget_minutes` flag from Phases D–G is removed in Phase I (no compat shim, per project rules).
- Unit tests: skill in isolation with mocked torch, asymmetric-EMA math, calibration-file I/O, proposer baseline-gate (annotate path). Integration test with a tiny real model on GPU; pseudo-mode test that an over-budget baseline yields a non-None `time_risk`. Phase I adds tests asserting per-mode budget selection at both call sites.

### 3.2 Out of scope (deferred)

- Inference-time estimate (phase 2 — additive, same skill).
- Override-disclosure prompt change (separate doc/PR).
- ~~Budget enforcement in formal (non-trial) mode~~ — **moved into scope by Phase I**: a separate `formal_time_budget_minutes` is now a first-class field. Formal-mode gating remains opt-in (the field defaults to `None` → gate skipped for formal rounds), so existing formal runs see no behaviour change unless the flag is set.
- Cross-user calibration sharing (each SDSC user builds their own file; no central store).

---

## 4. Files Touched

| Path | Change |
|---|---|
| `agent/skills/evaluate_time_skill/wrapper.py` | **new** — skill implementation (warmup + estimate + suggestion) |
| `agent/skills/evaluate_time_skill/skill_config.json` | **new** — JSONSchema describing inputs |
| `agent/skills/evaluate_time_skill/calibration.py` | **new** — load / update / lookup of the per-GPU calibration file (asymmetric EMA math) |
| `agent/skills/evaluate_time_skill/__init__.py` | **new** — empty module marker |
| `~/.siderius/time_calibration_{gpu_slug}.json` | **new** — persistent per-GPU learned correction factors (gitignored, auto-created) |
| `nodes/ml_hyperparameter_tune_agent.py` | add `[Step 0.5/3]` call + `skipped_time_risk` branch; add post-training hook that writes back to calibration file. **Phase I**: per-round budget pick by `plan.is_trial`; add `--trial_time_budget_minutes` / `--formal_time_budget_minutes` to argparse; remove `--time_budget_minutes`. |
| `nodes/ml_model_proposal_agent.py` | add baseline-gate skill call right before returning `ProposalOutput`; populate `time_risk` per §2.7.4. **Phase I**: budget pick by `inp.is_trial`; same CLI rename. |
| `agent/schemas/proposal.py` | add the trial-mode mirror (`is_trial`, `trial_strategy`, `trial_portion`, `target_files`, `train_portion`, `sampling_seed`) + **`trial_time_budget_minutes`** + **`formal_time_budget_minutes`** (Phase I) + `data_dir` to `ProposalInput`; add `time_risk: Optional[str]` to `ProposalOutput`. Defaults track `HyperparamTuningInput` exactly. |
| `agent/schemas/hyperparam_tuning.py` | add optional **`trial_time_budget_minutes: float`**, **`formal_time_budget_minutes: float`** (Phase I), `data_dir: Optional[str]` to `HyperparamTuningInput` (trial-mode set already present). |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | accept the trial-mode mirror + **`trial_time_budget_minutes` / `formal_time_budget_minutes`** (Phase I) / `data_dir` as caller-supplied kwargs (each falls through to the schema default when `None`) and forward them into `ProposalInput`. Conditional-inclusion pattern: only added to the result dict when the caller supplied them, so partial workflow plumbing doesn't silently reset a field. |
| `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` | accept **`trial_time_budget_minutes` / `formal_time_budget_minutes`** (Phase I) / `data_dir` as caller-supplied kwargs (the trial-mode set was already wired); read `proposal.time_risk` and prepend it to `expert_advice` after `spec_deviation_notes` / `inheritance_deviation_notes` (order: spec → inheritance → time_risk → base advice). |
| ~~`agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py`~~ | **no change** — `ImplementorInput` does not need any of these fields; the validator→tuner fan-in protocol reads `time_risk` from `ProposalOutput` directly |
| `run_exploration_adaptive.py` | add **`--trial_time_budget_minutes` / `--formal_time_budget_minutes`** (Phase I) CLI args; forward the trial-mode + budget set into the workflow context. |
| `workflows/model_exploration.py` (or equivalent entry) | fan out the trial-mode + budget set to **both** `ProposalInput` and `HyperparamTuningInput` (§2.7.2). |
| (no relocation needed) `execute_tools/sample_set_builder.py` | already in a neutral location; the proposer imports `build_sample_set` directly — see §2.7.5 |
| `~/.siderius/time_calibration_{gpu_slug}.json` | **new** — persistent per-GPU learned correction factors (gitignored, auto-created) |
| `.gitignore` | add `time_calibration_*.json` (if stored anywhere reachable by git) |
| `tests/unit/agent/skills/test_evaluate_time_skill.py` | **new** — step-count math, suggestion logic |
| `tests/unit/agent/skills/test_time_calibration.py` | **new** — asymmetric EMA update rule, clip, lookup fallback, drift detection |
| `tests/unit/agent/ml_model_proposal_agent/test_baseline_time_gate.py` | **new** — proposer's gate-and-annotate path with mocked skill: feasible → `time_risk is None`; infeasible → `time_risk` carries suggestion text |
| `tests/integration/agent/test_evaluate_time_skill.py` | **new** — integration test with a real tiny model on GPU (`@real_run`) |
| `tests/integration/protocols/test_ml_result_interp_to_ml_model_propose.py` | extend (or new) — assert the four new fields survive the protocol mapping |

---

## 5. Backward Compatibility

- The skill is purely additive. Existing flows that don't pass any budget field see no behavior change — both gates treat a missing budget as "skip" (feasible=True, warning printed once).
- Both `trial_time_budget_minutes` and `formal_time_budget_minutes` (Phase I) are optional with default `None`. The gate is per-mode: setting only the trial budget gates trial rounds and skips formal rounds; setting only the formal budget does the inverse.
- No changes to record schemas except adding `"skipped_time_risk"` as an allowed `status` value in `ExperimentRecord` (mirrors existing `"skipped_oom_risk"`).
- **Phase I breaking rename** (no compat shim, per project rules):
  - The single field `time_budget_minutes` on `HyperparamTuningInput` and `ProposalInput` is **removed** and replaced with two fields. Any caller (workflow runner, CLI, tests) that constructs these schemas with the old field name will fail Pydantic validation.
  - The single CLI flag `--time_budget_minutes` is **removed** from `run_exploration_adaptive.py` and node CLIs, replaced by `--trial_time_budget_minutes` and `--formal_time_budget_minutes`.
  - The skill (`evaluate_time_skill.run_skill`) keeps its single `time_budget_minutes` kwarg unchanged — only the upstream schema/CLI surface changes.
  - Phase E1's existing pseudo-mode tests, integration tests, and any saved workspace JSON that mentions `time_budget_minutes` are updated as part of Phase I.

---

## 6. Testing Approach

### 6.1 Unit (phase 1)

- `tests/unit/agent/skills/test_evaluate_time_skill.py`:
  - Step-count math is correct for `seg_size ∈ {1000, 16000, 50000}`, `batch_size ∈ {1, 4}`, `train_portion ∈ {0.1, 1.0}`.
  - Returns `feasible=True` when estimate < budget, `feasible=False` when estimate > budget.
  - Suggestion logic picks the expected lever for each of the three branches.
  - `status="error"` on malformed model config or missing required keys.
  - Warmup is mocked so the test runs without GPU.

### 6.2 Integration (phase 1)

- `tests/integration/agent/test_evaluate_time_skill.py` (`@real_run`):
  - Tiny `tinynet` model on real GPU, confirm skill returns a plausible `ms_per_step` (sanity: 0.5 ms < ms/step < 500 ms).
  - End-to-end: call tune agent in pseudo mode with a config known to exceed budget, confirm `skipped_time_risk` record is emitted and no training runs.

### 6.3 Smoke

- Re-run a shortened `exploit_cnn_v1` config with `--time_budget_minutes 30` and confirm the skill blocks it with a reasonable suggestion, instead of starting the 2-hour training.

---

## 7. Phased Implementation Checklist

Each phase ends with `.venv/bin/python -m pytest tests/unit/agent/skills/ -q` (or the phase-specific target) and a committable state.

**Recommended order after Phase D**: `E0 → E1 → F → E2 → G → H`. Rationale:

- **E0 → E1** lands the tuner round-gate end-to-end before any proposer code touches the skill — the skill is exercised in a real workflow before it's depended on at a second call site.
- **F before E2** so the proposer benefits from the learned `k(gpu, model_type)` from the moment it starts gating its baseline. Otherwise the proposer would run for some weeks at `k=1.0`, then suddenly get a (potentially large) shift in its estimates once F lands — annoying to debug.
- **G after E2** because the CLI flag's only purpose is to feed both gates; landing it before either gate exists wires it to nothing.

### Phase A — Skill scaffold [x]

- [x] Create `agent/skills/evaluate_time_skill/{__init__.py, skill_config.json, wrapper.py}`.
- [x] `wrapper.py` returns a stub dict matching the full output contract — no real computation yet.
- [x] `skill_config.json` describes inputs (`model_type, model_config, train_config, loss_config, sample_set, train_portion, time_budget_minutes, data_dir`).
- [x] Confirm `_run_skill("evaluate_time_skill", ...)` discoverable from the tune agent.
- **Verified** (2026-04-16): `importlib.import_module("agent.skills.evaluate_time_skill.wrapper")` succeeds; `run_skill()` returns `{status, feasible, verdict, suggestion, estimated_minutes, limit_minutes, breakdown}` with the expected keys.

### Phase B — Step-count math + static fallback [x]

- [x] Implement the step-count formulae from §2.2 in `wrapper.py` (`_total_train_steps`).
- [x] Add static `ms_per_step` fallback (`_static_ms_per_step`, ~6 FLOPs per param per sample / 1e10 flops/ms).
- [x] Suggestion-lever routing (`_suggest_lever`, 3 branches from §2.4).
- [x] Full `run_skill` entry point wired up on top of the helpers with the static formula; warmup + calibration still stubs.
- [x] Unit tests (19 tests in `tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py`): step-count math over 6 parametrised cases + ceil edge-case, static-formula linearity, 3 suggestion branches, contract-shape assertion, feasible/infeasible branches via monkeypatched `_count_params`, error path.
- **Verified** (2026-04-16): `pytest tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py -q` → **19 passed**. Sanity: step-count for the two real blown-budget runs reproduces the quoted 3,200,000 / 250,000 exactly.

### Phase C — Real-dataset live warmup [x]

- [x] In `wrapper.py`, add `_measure_ms_per_step(model_type, model_config, train_config, loss_config, data_dir, sample_set)`: build a mini `TIDMADEpochDataset` from a minimal slice of `sample_set` → real `DataLoader` → run `n_warmup_batches + n_timed_batches` fwd+bwd steps with `torch.cuda.synchronize()`, discard the warmup steps, average the rest.
- [x] Guard with `torch.cuda.is_available()` and `os.path.isdir(data_dir)`; return `None` so `run_skill` falls back to the static formula. Any exception in the warmup body is caught and downgraded to `None` with a printed trace — the skill never crashes the tuner.
- [x] Instantiate the real model / criterion / optimizer (matching `train_engine_sandbox`'s dtype conventions — `x.int()` vs `x.float()` for fcnet, `y.long()` vs `y.float()` based on loss_type). The warmup model is disposed (`del model, optimizer, criterion, dataset, loader; torch.cuda.empty_cache(); gc.collect()`) before returning.
- [x] `run_skill` now prefers the warmup measurement when `data_dir` is passed and the call returns a positive float; otherwise falls back to `_static_ms_per_step`. The chosen path is reflected in `breakdown["source"]` (`real_dataset_warmup` vs `static_formula_phase_b`).
- [x] Unit-test coverage for the routing: 3 new tests monkeypatching `_measure_ms_per_step` to verify (a) warmup value is used when non-None, (b) fallback when None, (c) warmup is not invoked at all when `data_dir` is missing.
- **Verified** (2026-04-16): `pytest tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py -q` → **22 passed**. Inline real-GPU smoke on `wavenet` with `/home/klz/Data/TIDMAD/` pending user approval.

### Phase D — Suggestion logic + verdict formatting [x]

Functionally absorbed into Phase B. All four items below were implemented while wiring the static-formula `run_skill` entry point, since the suggestion + verdict + safety-multiplier code paths sit on top of `_total_train_steps` and `_static_ms_per_step` and would have been awkward to defer.

- [x] 3-branch suggestion logic from §2.4 — `_suggest_lever` at `wrapper.py:78`.
- [x] Verdict formatted to match `evaluate_resource_skill` style (✅/❌ prefix, minutes instead of GB) — `wrapper.py:347-352`.
- [x] `SAFETY_MULTIPLIER = 1.1` constant at module top — `wrapper.py:34`.
- [x] Unit tests for each suggestion branch — covered by the "3 suggestion branches" tests landed in Phase B.
- **Verified** (2026-04-16): `pytest tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py -q` → **22 passed** (same suite as Phase C).

### Phase E — Agent integration [x]

All three sub-phases (E0 schema/protocol/workflow, E1 tuner round-gate, E2 proposer baseline-gate) are landed. The skill is now wired at both call sites with consistent input shape and the `time_risk` annotation flows end-to-end (proposer → validator → tuner protocol → planner expert_advice).

The skill is shared infrastructure (§2.7), so this phase has two call sites. They are independent and can land in either order, but **E1 first** is recommended because it exercises the skill end-to-end before the proposer starts depending on it. Both sub-phases share the schema additions in E0.

#### E0. Shared schema + workflow plumbing [x]

Schemas:

- [x] `HyperparamTuningInput` gains `time_budget_minutes: Optional[float] = None` and `data_dir: Optional[str] = None`. When `time_budget_minutes is None`, the gate is skipped with a one-time printed warning. (Trial-mode set + `train_portion` already existed.) — committed `f76bb8a`.
- [x] `ProposalInput` gains the **training-side trial-mode mirror** (`is_trial: bool = False`, `trial_strategy: Literal[...] = "snapshot"`, `trial_portion: float = 0.1`, `target_files: List[int] = []`, `train_portion: float = 0.1`, `sampling_seed: Optional[int] = None`) plus `time_budget_minutes: Optional[float] = None` and `data_dir: Optional[str] = None`. Defaults track `HyperparamTuningInput` so the two gates stay aligned. Legacy `file_index` is intentionally absent — see §2.7.1. — committed `3ba870c`.
- [x] `ProposalOutput` gains `time_risk: Optional[str] = None` per §2.7.4. — committed `3ba870c`.

Protocols (only the two that actually carry the new fields — `ml_model_propose_to_ml_model_impl` is intentionally untouched, see §4 note):

- [x] `ml_result_interp_to_ml_model_propose.local_full_context` — accept the trial-mode mirror + `time_budget_minutes` + `data_dir` as caller-supplied kwargs (mirroring the existing `expert_context`/`vocab_seed`/`reasoning_pipeline` pattern); forward each into `ProposalInput` only when the caller supplied it (so partial workflow plumbing doesn't reset a field the caller didn't touch). — committed `3ba870c`.
- [x] `ml_model_valid_to_ml_model_tune.local_validated_model` — add `time_budget_minutes` and `data_dir` to the caller-supplied kwargs (alongside the existing trial-mode / `file_index` / `train_portion` kwargs). Read `proposal.time_risk` and prepend it to `expert_advice` in the same place where `spec_deviation_notes` and `inheritance_deviation_notes` are already prepended. Order: spec-deviation → inheritance-deviation → time-risk → base advice. — committed `7c0e107`.

Workflow:

- [x] Workflow runner (`run_exploration_adaptive.py` + `workflows/model_exploration.py`) fans the same trial-mode + budget set out to both `ProposalInput` and `HyperparamTuningInput` via the two protocols above (§2.7.2 diagram). Single source of truth: the CLI args block. CLI surface: `--trial_strategy`, `--target_files`, `--sampling_seed`, `--time_budget_minutes`, `--data_dir` (all default `None` so the gate stays off until opted in). — committed `f7d2f04`.

**Verify**: protocol unit tests assert the new fields survive each hop, and that `time_risk` lands in `HyperparamTuningInput.expert_advice` when set on the proposal. `.venv/bin/python -m pytest tests/unit/agent/protocols/ -q` → **50 passed** (2026-04-16).

#### E1. Tuner round-gate [x]

- [x] Add `[Step 0.5/3]` call in `nodes/ml_hyperparameter_tune_agent.py` after the existing VRAM check. Follow the exact structure of the VRAM gate (error check, feasible check, record emission).
- [x] Define `skipped_time_risk` status and wire it into `ExperimentRecord` if not already accepted.
- [x] Forward `time_budget_minutes` and `data_dir` from `HyperparamTuningInput` down to the skill's `run_skill` call.
- [x] If the upstream `ProposalOutput.time_risk` is non-None, surface it to the planner prompt as round-0 guidance (so the LLM doesn't immediately re-propose the rejected baseline). **Already handled by the protocol** (`ml_model_valid_to_ml_model_tune.local_validated_model`, commit `7c0e107`): `proposal.time_risk` is prepended to `expert_advice` and the tuner's existing `_serialize_expert_advice` plumbing carries it into the planner prompt — no extra wiring inside the agent was needed.
- [x] One-time startup warning when `time_budget_minutes is None` (gate disabled). Mirrors the "additive, opt-in" stance in §5.
- **Verify**: 6 new unit tests in `TestTimeBudgetGate` cover feasible passthrough, kwarg forwarding (budget + `data_dir`), infeasible → `skipped_time_risk` record, suggestion content, `status="error"` propagation, and `time_budget_minutes=None` skipping the skill entirely. `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py -q` → **34 passed** (2026-04-16).

#### E2. Proposer baseline-gate [x]

- [x] In `nodes/ml_model_proposal_agent.py`, right after the proposing pipeline returns and before persistence, call the skill via a new `_apply_time_gate(output, inp)` helper. The skill module is imported directly (`agent.skills.evaluate_time_skill.wrapper`) and invoked with `sandbox=None` since `evaluate_time_skill` doesn't read its sandbox arg.
- [x] Build `sample_set` via `execute_tools.sample_set_builder.build_sample_set(...)` (§2.7.5 Option A). The helper already lives in a neutral location — no relocation needed.
- [x] On `feasible=True` → leave `time_risk=None`. On `feasible=False` → set `time_risk = result["suggestion"]` (with `verdict` as fallback when the suggestion is empty). On `status="error"` → leave `time_risk=None` and print a warning; the proposer never blocks on a skill failure.
- [x] When `time_budget_minutes is None`, skip the call entirely. Module-level `_TIME_GATE_WARNED` flag → one-time process warning, mirrors the tuner gate's startup-once policy.
- [x] Read-only access to the calibration file — proposer never calls `update_k`. (Wired in Phase F2: `wrapper.run_skill` calls `calibration.load_table` + `lookup_k` only; the proposer-side gate inherits this behavior transitively. The tuner is the sole writer.)
- **Practical caveat**: a brand-new `model_name` proposed by the LLM will not be in `MODEL_REGISTRY` yet (the implementor only registers it later), so the skill's `_count_params` will raise → `status="error"` → gate degrades gracefully via the warn-and-proceed path. The wiring and `time_risk` propagation through the validator→tuner protocol are still valuable: the gate becomes useful the moment a future revision lets the proposer instantiate its proposal pre-validation, and the protocol path is exercised end-to-end now (not retrofitted later).
- **Verify**: 11 new unit tests in `tests/unit/agent/ml_model_proposal_agent/test_baseline_time_gate.py` cover all four branches (feasible / infeasible / error / disabled), skill-kwarg shape, sample-set construction from the trial-mirror, suggestion-vs-verdict fallback, and end-to-end wiring through `MLModelProposalAgent.run()` including JSON round-trip of `time_risk`. `.venv/bin/python -m pytest tests/unit/agent/ml_model_proposal_agent/ -q` → **240 passed** (2026-04-16).

### Phase F — Learned calibration (asymmetric EMA) [x]

This is where "learning from mistakes" lands. Splits into three sub-steps.

- [x] **F1. Calibration module.** `agent/skills/evaluate_time_skill/calibration.py` exposes:
  - `load_table(gpu_name) -> dict` — defensive against missing/corrupt JSON; returns an empty `{"gpu_name", "k_values", "history"}` skeleton on either failure path.
  - `lookup_k(table, model_type) -> float` with fallback chain `(gpu, model_type) → (gpu, *) → 1.0`.
  - `update_k(table, entry) -> dict` implementing the asymmetric EMA from §2.6.5 (`α_up=0.5`, `α_down=0.1`, clip `[0.5, 5.0]`); mutates `table` in place and appends to `history`.
  - `save_table(gpu_name, table)` with atomic write (`tempfile.mkstemp` + `os.replace`).
  - `detect_drift(table, last_n=3) -> Optional[str]` warns when the last N entries all violated.
  - `make_entry(...)` packages a finished run into the canonical history dict (computes `ratio` and `estimate_violated`, emits a UTC ISO timestamp).
  - Path resolution: `SIDERIUS_CALIBRATION_DIR` env var, falling back to `~/.siderius/`. GPU-name slugged via `gpu_slug()` so `"NVIDIA RTX 5090"` → `time_calibration_nvidia_rtx_5090.json`.
- [x] **F2. Pre-flight use.** `wrapper.py` now calls `_detect_gpu_name()` and, when the warmup path was used, looks up `k` via `calibration.load_table` + `lookup_k`. The static-formula path stays at `k=1.0` (no warmup signal to calibrate against). The breakdown gains `k_correction` and `gpu_name`. The 22 existing skill tests still pass — `k=1.0` keeps the static path identical.
- [x] **F3. Post-flight update.** `nodes/ml_hyperparameter_tune_agent.py` stashes the gate's `time_check` result; after the success record is built, it computes `actual_ms_per_step = train_time × 1000 / total_steps`, builds a `make_entry`, calls `update_k`, saves the table atomically, and prints either the new `k` or the drift warning. Update is gated on `source == "real_dataset_warmup"` and a non-None `gpu_name`, so CPU-only / static-formula runs are silently skipped.
- [x] Unit tests in `tests/unit/agent/tune_ml_hyperparam_agent/test_time_calibration.py` (29 tests): EMA up/down asymmetry, K_MIN/K_MAX clipping, lookup fallback chain, drift detection (positive/negative/short-history), atomic write semantics, env-var override, slug determinism, defensive load against corrupt JSON, `make_entry` ratio + zero-warmup safety. Located alongside the tuner tests so the per-agent folder convention holds.
- **Verify**: `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ tests/unit/agent/ml_model_proposal_agent/ -q` → **409 passed** (2026-04-16). Inline smoke is deferred to Phase H.

### Phase G — .gitignore housekeeping [x]

The CLI surface (`--time_budget_minutes`, `--trial_strategy`, `--target_files`, `--sampling_seed`, `--data_dir`) and the startup-print block both landed in E0 (commit `f7d2f04`). The default for `--time_budget_minutes` is `None`, not 60 — this keeps the gate off until the user explicitly opts in, matching the "additive, opt-in" stance in §5. **Note**: Phase I supersedes the single `--time_budget_minutes` flag with two per-mode flags; this paragraph is preserved for historical accuracy.

What remains here is just the gitignore housekeeping:

- [x] `time_calibration_*.json` added to `.gitignore` (defensive — the file lives at `~/.siderius/` by default per §2.6.4, but the `SIDERIUS_CALIBRATION_DIR` env-var override could land it inside the repo tree).
- **Verified**: `git check-ignore time_calibration_test.json` → matches `.gitignore:47`.

### Phase H — First real-GPU smoke run

H is **two separate runs on two separate environments**. They test different things and the acceptance criteria only partially overlap. Do H1 first (faster iteration, no queue wait); only move to H2 once H1's calibration entries look sane.

---

#### Phase H1 — lilab (local interactive GPU)

Lilab is a single-host interactive GPU box. The skill runs in-process, the calibration file lives at `~/.siderius/time_calibration_<gpu>.json`, and the `_measure_ms_per_step` warmup path is fully exercised. This is where we catch code-level bugs — torch device placement, DataLoader worker count, HDF5 access, `_count_params` for each real model class, the atomic-write race on a hot filesystem.

H1 splits into two stages because they have very different costs:

##### H1a — direct skill smoke (no LLM cost) [x]

Drove `evaluate_time_skill.run_skill()` directly on lilab with `data_dir=/home/klz/Data/TIDMAD/`, isolated calibration dir under `/tmp` so the real `~/.siderius` was untouched (smoke script `/tmp/smoke_h1a.py`, 2026-04-16):

- [x] `_detect_gpu_name()` → `'NVIDIA GeForce RTX 5090'`.
- [x] `wavenet` real-warmup completes: 35,008 params, **3.09 ms/step**, `source=real_dataset_warmup`, breakdown shape correct (gpu_name + k_correction present).
- [x] Synthetic post-flight: `make_entry(ratio=1.5, violated=True)` + `update_k` → **k=1.25 exactly**, matching the closed-form `α_up=0.5 × 1.5 + 0.5 × 1.0`.
- [x] Atomic save→reload round-trip: a second `run_skill()` call reads **k=1.25 from disk** (no in-process cache).
- [x] `punet` real-warmup completes: 412,392 params, 3.01 ms/step, k=1.0 from its own per-model entry (never calibrated).

H1a acceptance = the skill, the model-class instantiation, the GPU warmup, and the calibration round-trip all work end-to-end on real RTX 5090 + real HDF5. The remaining failure modes are tuner-integration ones, covered by H1b. Phase I (the structural-flaw fix surfaced by H1a-prep) landed 2026-04-16; Phase J (success-path time info to the planner) landed 2026-04-16; H1b is now unblocked.

---

### Phase I — Two-budget split (trial vs formal) [x] (2026-04-16)

**Background.** Phase E1 landed a single `time_budget_minutes` field that both the proposer's baseline gate and the tuner's `[Step 0.5/3]` gate compare against. The skill correctly computes `estimated_minutes` as a function of the active mode (trial vs formal) — `total_train_steps` shrinks when `trial_portion` is small — but the **budget being compared against is the same constant** regardless of mode. Two failure modes follow:

1. **Budget sized for trial → every formal round rejected.** A 5-min budget that's comfortable for trial rounds will fail every formal round (which uses the full dataset and runs 50–100× longer).
2. **Budget sized for formal → trial gate effectively disabled.** A 4-hour budget set to permit formal runs lets every trial round through unchecked, defeating the original purpose of the gate (catching the 1h 50min / 2h 27min trial blowups from §1.1).

There is no single budget value that correctly gates both modes. They are different ceilings on different things.

**The fix.** Replace one field with two — `trial_time_budget_minutes` and `formal_time_budget_minutes`, both `Optional[float]` defaulting to `None`. The per-round gate selects the matching one based on the mode that round will run in. The skill is **unchanged**: it still takes a single `time_budget_minutes` kwarg; the *caller* picks which budget to pass.

#### I.1 Schema rename [x]

- [x] `agent/schemas/hyperparam_tuning.py` — `HyperparamTuningInput`: remove `time_budget_minutes`, add `trial_time_budget_minutes: Optional[float] = None` and `formal_time_budget_minutes: Optional[float] = None`. Field docstrings describe the per-mode behaviour and the gate-skip semantics when one is `None`. — committed `29cd956`.
- [x] `agent/schemas/proposal.py` — `ProposalInput`: same rename. Defaults track `HyperparamTuningInput` exactly so the two gates stay aligned. `ProposalOutput.time_risk` description updated to reflect the per-mode disabling. — committed `29cd956`.
- [x] No compat shim — the old field name is removed cleanly. Any caller still passing `time_budget_minutes=` will fail Pydantic validation, surfacing the rename as a hard error rather than silent drift.

#### I.2 Per-mode pick at the call sites [x]

- [x] `nodes/ml_hyperparameter_tune_agent.py`: at `[Step 0.5/3]`, computes `chosen_budget = trial_time_budget_minutes if plan.is_trial else formal_time_budget_minutes` and passes it to the skill as `time_budget_minutes=chosen_budget`. Skips the gate (one-time warning) when `chosen_budget is None`. The `time_check` stash for the F3 post-flight calibration update is unchanged. — committed `358dded`.
- [x] `nodes/ml_model_proposal_agent.py`: `_apply_time_gate` computes `chosen_budget = inp.trial_time_budget_minutes if inp.is_trial else inp.formal_time_budget_minutes`. Same skip-when-None semantics; disabled-warning text updated. — committed `485250e`.

#### I.3 Protocol pass-through [x]

- [x] `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` — `local_full_context`: `time_budget_minutes` kwarg replaced with `trial_time_budget_minutes` + `formal_time_budget_minutes`. Conditional-inclusion pattern preserved. — committed `29cd956`.
- [x] `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` — `local_validated_model`: same kwarg replacement. — committed `29cd956`.
- [x] `agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py`: confirmed no change — the implementor protocol does not carry budget fields.

#### I.4 CLI surface [x]

- [x] `run_exploration_adaptive.py` + `workflows/model_exploration.py`: `--time_budget_minutes` replaced with `--trial_time_budget_minutes` and `--formal_time_budget_minutes`; both default `None` (gate-off-until-opted-in). Startup banner prints both per-mode budgets. Workflow runner fans each one out to BOTH `ProposalInput` (via `local_full_context`) and `HyperparamTuningInput` (via `local_validated_model`). — committed `b6b680d`.
- [x] `nodes/ml_hyperparameter_tune_agent.py` argparse: same rename, plus `--data_dir` (was deferred under H1b). — committed `358dded`.
- [x] `nodes/ml_model_proposal_agent.py` argparse: **no change** — the proposer node CLI is a minimal debug entry point (only `--workspace`, `--run_name`, `--provider`, `--model_id`); it never accepted `--is_trial`, `--trial_strategy`, or `--time_budget_minutes`, so it constructs `ProposalInput` with all trial-mode and budget fields at their schema defaults (`is_trial=False`, both budgets `None`, `data_dir=None`). The baseline gate is therefore always disabled when invoked via this CLI. Production usage flows through `run_exploration_adaptive.py` → `workflows/model_exploration.py` → `local_full_context` protocol → `ProposalInput`, where the budget flags are wired. Adding the budget flags here in isolation would be partial wiring with no real gate exercise. H1a (the lilab smoke) confirmed this scoping by calling the skill directly via `/tmp/smoke_h1a.py` rather than the proposer node CLI.

#### I.5 Test surface [x]

- [x] `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py` (`TestTimeBudgetGate`): kwargs renamed; `_make_input_with_budget` helper takes `trial_budget`/`formal_budget`/`is_trial` explicitly; `_make_agent` extended with `enable_trial_mode=True` to patch `load_anchor_map` + `os.path.exists` and stub `sandbox.dirs["data"]` + `sandbox.score_vector` so trial-mode rounds reach the gate without crashing. New per-mode-pick tests use `max_rounds=2` because the final round is forced to formal regardless of the planner's choice. — committed `358dded`.
- [x] `tests/unit/agent/ml_model_proposal_agent/test_baseline_time_gate.py`: same per-mode pick assertions at the proposer gate; `_make_input` helper signature updated. — committed `485250e`.
- [x] `tests/unit/agent/protocols/test_ml_result_interp_to_ml_model_propose.py` and `test_ml_model_valid_to_ml_model_tune.py`: kwargs renamed; both fields independently asserted to survive the protocol mapping. — committed `29cd956`.
- [x] `tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py`: confirmed unchanged — the skill kwargs (`time_budget_minutes`) are unaffected by the schema rename, only the upstream callers pick which budget to pass.
- [x] Pseudo-mode integration tests (`tests/integration/`): no fixture references to `time_budget_minutes=` found; nothing to update.

#### I.6 Acceptance [x]

- [x] **Verified** (2026-04-16): targeted Phase-I test surface passes: `pytest tests/unit/agent/protocols/ tests/unit/agent/ml_model_proposal_agent/test_baseline_time_gate.py tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py -q` → 53 protocol + 17 proposer-gate + 36 tuner-gate = **106 passed**. CLI `--help` confirms the two new flags are wired with per-mode help text. Both `workflows.model_exploration` and `run_exploration_adaptive` import cleanly.
- **Deferred to H1b**: real-mode tuner launch with `--trial_time_budget_minutes 5 --max_rounds 3` (and the negative-path `--trial_time_budget_minutes 0.01` rejection check) requires real LLM cost and is folded into the H1b smoke acceptance — not a separate Phase I gate.
- [x] Marked I `[x]` in the Progress log with all 5 commit hashes.

H1b is now unblocked — Phase J landed 2026-04-16.

---

### Phase J — Success-path time info to the planner [x] (2026-04-16)

**Background.** Phases E1 and I wire the time estimator into the round-loop and the dual-budget split, but the LLM only ever hears from the gate **on rejection**. When the gate passes, the round becomes a success record with no time-related field — the planner gets a silent green light. The LLM has to *crash into the boundary* to learn it. Two consequences:

1. **Reactive boundary discovery.** The planner can't make "I had 2 of my 5 min last round, room to grow" or "I used 4.8 of 5, stay near here" decisions. It must propose, get rejected, then back off.
2. **Wasted rounds near the ceiling.** A planner that knew it was at 96% budget last round could choose to widen `seg_size` (cheap, fewer steps) instead of `hidden_channels` (expensive, slower steps). Without that signal, it picks blindly.

**The fix.** When the gate passes, attach a small block to the success record's `memory` so the existing reflector-then-planner channel carries it forward. No new schema for the planner side, no prompt rewrites, no new LLM call.

#### J.1 What gets surfaced

Add three fields to the **success record's `memory` block** (next to the existing `expert_advice_followed`, `hypothesis`, `conclusion`, `discovery`, `memory_update`):

```python
"memory": {
    ...existing fields...,
    "time_estimate_minutes": float,   # what evaluate_time_skill predicted pre-flight
    "time_budget_minutes":   float,   # the budget that was checked against (mode-dependent)
    "time_mode":             str,     # "trial" or "formal" — which budget was active
}
```

Computed source: the `time_check` dict that's already stashed for Phase F3's calibration update. No new computation; just lift three fields out and put them in the record.

**Explicit non-goals (deferred):**
- `k_correction` — too internal; the LLM doesn't know what to do with a multiplier. The pre-flight estimate already incorporates `k`, so the planner sees the corrected number.
- `ms_per_step_warmup` / `total_train_steps` — same reason. The aggregated `estimate_minutes` is what matters for budget decisions.
- `time_actual_minutes` (what training actually took) — useful, but lives on a different axis (post-flight, vs pre-flight estimate). Could be added later as `memory.time_actual_minutes` from the `train_time` already recorded; defer to keep Phase J a one-shot edit.
- Proposer-side history exposure — proposer is one-shot, gets only one config, no iteration loop to feed back into. Defer indefinitely unless we move to gate-and-revise (§2.7.4).

#### J.2 Where the LLM picks it up

No new wiring needed. The reflector summarises round records into the `experiment_history` block of the next planner prompt; the planner already sees `memory.conclusion` / `memory.discovery` / `memory.memory_update` for past rounds. Adding three more keys to `memory` propagates automatically through the same pipeline.

The planner prompt does NOT need a dedicated "time budget guidance" section — the reflector's existing summary will surface "Round 1: estimated 2.3 min vs 5 min budget (trial)" alongside the architecture choices, which is enough context for the planner to reason about headroom.

If telemetry later shows the planner is ignoring the new fields (still proposes ceiling-blowing configs), revisit with an explicit prompt section. Cheap to retrofit; not worth pre-empting.

#### J.3 Skipped-record consistency

The existing `skipped_time_risk` record's `memory.conclusion` already includes `estimated_minutes` and `limit_minutes` in human-readable form ("Skipped: estimated wall-time (X min) exceeds budget (Y min)"). For consistency post-Phase J, **also** add the same three structured fields (`time_estimate_minutes`, `time_budget_minutes`, `time_mode`) to the skipped record's memory. Cost is two extra dict keys; payoff is the planner sees the same shape regardless of pass/fail.

#### J.4 Files touched

- [x] `agent/schemas/hyperparam_tuning.py`: extend `ExperimentMemory` with three optional fields (`time_estimate_minutes: Optional[float]`, `time_budget_minutes: Optional[float]`, `time_mode: Optional[Literal["trial", "formal"]]`). Defaults to `None` so pre-Phase-J records still validate. Committed `bbbc174`.
- [x] `nodes/ml_hyperparameter_tune_agent.py`:
  - Final success-record assembly (around `:782`): inject the three `memory` fields from the stashed `time_check` dict, guarded by `if time_check is not None` so runs with the gate disabled emit records without the keys. Committed `265bfb5`.
  - `skipped_time_risk` record (around `:528`): add the same three fields unconditionally (the gate just ran by definition). Committed `4b8fb94`.
- [x] `nodes/ml_model_proposal_agent.py`: **no change**. Proposer is one-shot; no next-round to feed back into.

#### J.5 Test surface

- [x] `tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py`: new `TestExperimentMemoryTimeFields` class — 5 tests covering schema defaults, concrete values, `Literal` rejection, and round-trip of pre-Phase-J records (committed `bbbc174`).
- [x] `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py`: 3 new success-path tests in `TestTimeBudgetGate`:
  - `test_success_record_memory_carries_time_fields_formal` — gate-pass formal mode populates all three fields.
  - `test_success_record_memory_time_mode_trial` — gate-pass trial mode → `time_mode == "trial"`.
  - `test_success_record_omits_time_fields_when_gate_disabled` — both budgets `None` → keys absent (not `None`).
  - (committed `265bfb5`)
- [x] Same file: 1 new consistency test:
  - `test_skipped_time_risk_record_carries_time_fields` — skipped record's `memory` carries the same three fields with values from the over-budget `time_check` (committed `4b8fb94`).

#### J.6 Acceptance

- **Verified** (2026-04-16): `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q` → **182 passed** (9 new Phase-J tests, 0 regressions).
- **Verify (during H1b)**: in the post-run workspace records for the H1b 3-round trial, confirm rounds 2 and 3 carry the round-1 time fields in their `experiment_history` block visible to the planner (inspect the actual prompt or the planner trace).

---

##### H1b — tuner-integration smoke (real LLM cost) [done, 2026-04-16]

Phases I and J both landed 2026-04-16; H1b is now unblocked. Ran a real multi-round tuner job to exercise the per-round calibration update path AND the Phase-J success-path feedback channel under real LLM planning.

**Result.** Test A passed on lilab (NVIDIA GeForce RTX 5090, `run_name=h1b_test_a`). 2 successful trial rounds (`_001`, `_004`) + 2 skipped trial attempts (`_002`, `_003`) + 5 skipped formal attempts (`_005`–`_009`); run terminated cleanly at the 9-attempt cap with `completed_rounds=2`. Calibration learned `k(wavenet)=4.2171` over 2 history entries (warmup ~10 ms/step underestimated actual ~50 ms/step by ~5×; ratios 5.241 and 5.314, both `estimate_violated=true`). Tests B and C de-scoped as redundant — Test A's composite already exercised every Phase J/I/F3 codepath those two would have probed.

**CLI fix discovered during smoke.** The direct tuner CLI (`nodes/ml_hyperparameter_tune_agent.py`) didn't wire `--trial_portion`/`--train_portion`/`--eval_portion` into `HyperparamTuningInput.plan_overrides`. The LLM was therefore free to override the operator's per-round portion choices and consistently blew the 5-min trial budget. Fixed by mirroring `run_exploration_adaptive.py:250-255`'s `plan_overrides` population — committed `17ab26e`.

**Worth noting (not a blocker).** Real `actual_ms_per_step` was ~5× higher than `warmup_ms_per_step` on this GPU. The asymmetric EMA absorbs it correctly (k=4.22 after 2 trainings), but new-config / new-GPU first runs will systematically over-promise the gate until calibration kicks in. Could be a follow-up for §2.6 / Open Questions: warmup may be skipping data-loader / grad-accum overhead.

- [x] **Test A — positive trial path + protected from formal blowup.** Tuner run with `--max_rounds 3 --is_trial --trial_portion 0.01 --train_portion 0.1 --force_model wavenet --trial_time_budget_minutes 5 --formal_time_budget_minutes 1 --data_dir /home/klz/Data/TIDMAD/ --provider openai --model_id gpt-5-mini` (per `feedback_prefer_openai_for_smoke.md`). The `--formal_time_budget_minutes 1` is intentionally tight: only `eval_portion` is mode-forced, training-side `trial_portion`/`train_portion` come from the LLM plan, so a 5-min formal budget would pass trivially under common LLM choices (~2 min for `tp=0.1, train_p=1.0` on wavenet/RTX 5090). Setting it to 1 deterministically rejects any formal round the LLM chooses, exercising the gate path under both behaviours. Acceptance:
  - [x] Gate passes for trial rounds, training completes — `_001` (Est 3.5/5 min) and `_004` (Est 4.81/5 min) both ran to completion.
  - [x] `~/.siderius/time_calibration_nvidia_geforce_rtx_5090.json` gained 2 history entries with finite `ratio` (5.241, 5.314) and consistent `estimate_violated=true`.
  - [x] **(Phase J)** Both success records' `memory` carries `time_estimate_minutes`, `time_budget_minutes=5.0`, `time_mode='trial'`. The skipped-trial record `_002` carries `time_budget_minutes=5.0, time_mode='trial'`. Round-2's planner prompt sees round-1's fields via `experiment_history` (auto-flowed via `ExperimentRecord.memory`).
  - [x] Round 3 (forced formal by `is_last_needed_round`) deterministically rejected all 5 attempts with `time_mode='formal'` and `time_budget_minutes=1.0` — `_005` carries `time_estimate_minutes=17.85, time_budget_minutes=1.0, time_mode='formal'`.
- [~] **Test B — negative trial path.** De-scoped — Test A's skipped trial attempts (`_002`/`_003`) already produced records with `time_mode='trial'` and the active trial budget, exercising the identical Phase J.C trial-mode codepath.
- [~] **Test C — explicit formal-only rejection (optional).** De-scoped — Test A's round 3 formal attempts (`_005`–`_009`) already produced records with `time_mode='formal'` and the active formal budget, exercising the identical Phase J.C formal-mode codepath.
- [x] H1b marked `[x]` in the Progress log: RTX 5090, `run_name=h1b_test_a`, `k(wavenet)=4.22`.

---

#### Phase H2 — SDSC Expanse (Slurm batch, job-chained) [deferred, after H1]

SDSC is structurally different from lilab: jobs are Slurm-submitted with `afterany+48G` chaining, walltime is a hard kill (not a soft budget), `$HOME`/`$SCRATCH` have separate quotas, and a single logical run can span multiple physical nodes (each restart lands in a new job). The skill's behaviour changes in ways H1 can't catch:

1. **Calibration file location.** `~/` on SDSC is quota-constrained — the user may prefer `$SCRATCH` via `SIDERIUS_CALIBRATION_DIR`. Confirm the env override resolves correctly inside the Slurm job's environment, not just the login shell.
2. **GPU-name stability across restarts.** The design claim (§2.6.4) is that `torch.cuda.get_device_name(0)` is stable even when Slurm reassigns the job to a different node with the same GPU model. H1 can't test this. H2 must.
3. **Budget sizing against walltime.** `--time_budget_minutes` must be set **strictly less than** the Slurm `--time` flag so the gate fires before Slurm does. Confirm the rejection path produces a clean `skipped_time_risk` record and the job exits gracefully rather than being killed mid-training.
4. **Concurrent-writer safety.** Two chained jobs on the same GPU model may overlap briefly during handoff. The atomic `tmp + rename` in `save_table` should hold, but H2 is the first time it's tested under real concurrency.

Acceptance criteria:

- [ ] Submit an over-budget sbatch job with `--time_budget_minutes 10` below the `--time` walltime → gate fires, `skipped_time_risk` lands, job exits clean before walltime kill.
- [ ] Submit an under-budget job → training completes, calibration entry lands in whichever directory `SIDERIUS_CALIBRATION_DIR` resolved to inside the job.
- [ ] Submit a **chained** pair of jobs (job B `--dependency=afterany:<job_A>`) on the same GPU model → confirm B reads A's calibration file correctly and appends (doesn't overwrite) the history.
- [ ] If Slurm lands the two jobs on different physical nodes, confirm both produce the same filename (same GPU → same slug).
- [ ] Update Status line to `implemented + smoke-tested (lilab + SDSC)`; append H2 row to Progress log with SDSC job IDs.

H2 acceptance = the skill is safe to leave on by default in the production SDSC workflow.

---

## 8. Rollback Plan

The skill is additive and gated on `time_budget_minutes is not None`. To disable at any point:

- **Fastest**: set `--time_budget_minutes 0` or omit it → gate is bypassed (or, treat 0/None identically).
- **Per-run**: remove the CLI flag from the invocation.
- **Codebase rollback**: revert the commit(s) for phases E–F; phases A–D are self-contained and safe to leave in place as a dormant skill.

No data-layer changes, no schema changes that block older records from loading (the new `skipped_time_risk` value is additive to the enum).

---

## 9. Open Questions

1. **Warmup batch count**: 3 (1 warmup + 2 timed) vs 5? I'll start with 3 in Phase C and revisit if variance on SDSC shared nodes is high.
2. **Budget defaults**: both `trial_time_budget_minutes` and `formal_time_budget_minutes` default to `None` (gate-off-until-opted-in) post-Phase I. If we want non-`None` defaults later: trial ≈ 60 min (matches the original expert-advice prose); formal ≈ 4 h (educated guess; revisit once a few formal runs have completed and the calibration history can inform it).
3. **EMA α constants**: `α_up=0.5, α_down=0.1` are educated guesses. Once a few real entries accumulate, sanity-check these by replay — do we converge too slow/fast? Tune then.
4. **Calibration file location**: `~/.siderius/` by default; override with `SIDERIUS_CALIBRATION_DIR` env var so SDSC users can point to `$HOME` or `$SCRATCH` depending on quota.
5. **`skipped_time_risk` enum location**: wherever `skipped_oom_risk` lives in the record schema — confirm path in Phase E1.
6. **Gate-and-revise switch threshold (§2.7.4)**: v1 ships gate-and-annotate. Concrete trigger to revisit: if >20% of baselines across a 2-week window get rejected by the tuner's round-0 gate, switch the proposer to gate-and-revise. Need a small telemetry counter on `ProposalOutput.time_risk is not None` to measure this — open whether that lives in the workspace records or a separate log.
7. **`build_sample_set` location (§2.7.5)**: currently inside `nodes/ml_hyperparameter_tune_agent.py`. Cleanest is to relocate to `agent/skills/evaluate_time_skill/sample_set_util.py` (or `agent/utils/`) so both nodes import from a neutral place. Defer the call: if Phase E2 finds the import works without circularity, leave it where it is; otherwise relocate. Decide in E2.
8. **Proposer's response to skill `status="error"`**: v1 silently warns and proceeds (no `time_risk` set). Alternative: hard-fail the proposal so the workflow can't silently emit an unestimated baseline. Lean toward warn-and-proceed because skill errors are usually environmental (no `data_dir`, CUDA hiccup) rather than the baseline being broken — but worth confirming in smoke testing.

---

## 10. Phase K — VRAM Budget Extension (design 2026-04-18)

Phase K extends the per-round resource gate to enforce a configurable VRAM
budget alongside the time budget that landed in Phases I + J. The two gates
share the same call sites (proposer baseline + tuner per-round), the same
two-budget split (trial vs formal), the same skipped-record semantics, and
the same workflow fan-out plumbing — all of which is already in place from
the time work. Phase K's net new surface is one renamed skill, four schema
fields, two protocol kwargs, two CLI flags, and one planner-prompt section.

### 10.1 Why this is needed

`agent/skills/evaluate_resource_skill/wrapper.py` (the existing VRAM gate)
sets its limit as `free_bytes × 0.8` — i.e. whatever happens to be free on
the GPU at the instant of the check. Three problems:

1. **Contention pathology.** On 2026-04-17, `explore_novel_v1` iterations
   3 and 4 burned 9/9 attempts each to the message
   `"GPU has only 0.01 GB free"` — another process held 25.7 GB on the
   shared 32 GB card. The configs being checked were no larger than ones
   that had run successfully in iteration 1; only the moment-to-moment free
   VRAM had moved. **The gate moved with the contention.**
2. **No numeric ceiling for the LLM.** The planner prompt section
   "GPU MEMORY RULES" (`agent/prompts.py:74-82`) names no GB ceiling. The
   LLM is told reactively about `skipped_oom_risk` records, never given a
   forward target. The expert-advice block says *"VRAM CEILING: 4 GB"* in
   prose, but nothing programmatic enforces a 4 GB number end-to-end.
3. **No mode split.** Trial and formal rounds have meaningfully different
   VRAM profiles (DataLoader buffer sizes scale with `train_portion`;
   formal often runs higher batch). One global ceiling can't gate both.

The fix mirrors Phase I exactly: replace one effective ceiling with two
operator-supplied budgets (`trial_vram_budget_gb`, `formal_vram_budget_gb`),
pick per-round based on `plan.is_trial`, fall through to None → gate
disabled. The defensive `free_bytes × 0.8` floor stays as a contention
guard but is no longer the operating budget.

### 10.2 Two skills, not one fused "evaluate_resources_skill"

Confirmed 2026-04-18: keep `evaluate_vram_skill` (renamed from
`evaluate_resource_skill`) and `evaluate_time_skill` as two siblings,
called sequentially at the same gate sites. Reasoning matches §2.8.2:

- VRAM is a static accounting calculation against a hardware ceiling;
  time is a measured + learned quantity with cross-server EMA calibration
  (§2.6). Almost no shared internals.
- Independent toggling — a user may set only one budget; the other defaults
  to None and skips that gate.
- Cleanest test surfaces (VRAM tests need no GPU; time tests cover warmup +
  calibration paths). Fusion would entangle three test surfaces.

The "joint" behaviour is at the **call site**, not inside either skill:
the tuner runs VRAM first (cheap, no GPU runtime), then time (~1–3 s
warmup) only if VRAM passed.

### 10.3 The lever-decision logic lives in the planner prompt

The skill's responsibility is to **return estimations**, not to prescribe
the fix. The current time skill's `_suggest_lever` (§2.4) bakes a
3-branch decision into the skill output — branch 1 (*"raise batch_size
first"*) explicitly trades time for VRAM, which is counterproductive once
both budgets exist. Phase K removes the prescription from both skills'
output (downgrade `suggestion` to a verdict-style summary such as
`"VRAM over budget; time within budget"`) and moves the lever logic into
the planner prompt where the LLM has full context to reason about both
axes at once.

Two design rules for the prompt block:

1. **Provide information, not prescriptions.** Surface the raw numbers
   (estimate, budget, factor over/under, current batch_size) and let the
   LLM reason. Do not encode "if batch_size > 1" or any other
   precondition as static rules — the LLM can read those conditions off
   the inputs directly.
2. **One channel only.** The planner sees resource information **only**
   from this prompt block (and from `experiment_history`'s memory fields
   for previous rounds). Do not also surface VRAM verdicts via
   `expert_advice` — that creates a duplicated, potentially-conflicting
   second channel. (Time's `time_risk → expert_advice` route is kept for
   Phase K to avoid retroactively breaking Phase J, but is marked for
   retirement in §10.17.)

Per-round numeric block fed by the four budget fields, the active mode,
and the current/previous round estimates:

```
[ACTIVE RESOURCE BUDGETS — round 3, mode=trial]
  VRAM:  estimate 5.20 GB   budget 4.00 GB   factor 1.30  (over)
  Time:  estimate 8.40 min  budget 20.0 min  factor 0.42  (under)
  Current batch_size: 4
```

When either budget is `None`, that line reads
`"(no budget — gate disabled)"` and `factor` is omitted, so the LLM
knows it doesn't need to consider that axis.

Static guidance block, appended once near the existing exploration
checklist:

```
[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]

You will be shown vram_estimate_gb, time_estimate_minutes, the matching
budgets, the resulting factors (>1 = over budget, <1 = under), and the
current batch_size.

When deciding the next config:

  - If both factors are ≤ 1: continue per the exploration plan.
  - Otherwise, first consider whether changing batch_size alone can bring
    BOTH factors ≤ 1.
      - Lowering batch_size reduces vram_factor and raises time_factor.
      - Raising batch_size does the opposite.
      - batch_size cannot go below 1; whether you have room to lower or
        raise depends on the current batch_size shown above.
  - If batch_size adjustment alone cannot satisfy both budgets
    simultaneously, reduce model depth/width (num_blocks,
    hidden_channels, embedding_dim, etc.). Both axes shrink together.

Constraint: do NOT change segmentation_size to fit either budget. It is
pinned by frequency-resolution physics (must divide PSD_SEGMENT_LENGTH;
the valid divisor list is in your expert advice). Lowering seg_size to
escape the time gate inflates step count and typically makes the overrun
worse, not better.

The gates run again before training, so a misjudgement just costs one
skipped attempt (no round consumed). Prefer the cheaper lever first.
```

### 10.4 Schema additions (tuner-side only; mirrors Phase I.1 + J.4)

| Schema | Field | Type | Default | Mirrors |
|---|---|---|---|---|
| `HyperparamTuningInput` | `trial_vram_budget_gb` | `Optional[float]` | `None` | `trial_time_budget_minutes` |
| `HyperparamTuningInput` | `formal_vram_budget_gb` | `Optional[float]` | `None` | `formal_time_budget_minutes` |
| `ExperimentMemory` | `vram_estimate_gb` | `Optional[float]` | `None` | `time_estimate_minutes` (J.1) |
| `ExperimentMemory` | `vram_budget_gb` | `Optional[float]` | `None` | `time_budget_minutes` (J.1) |

**Not added in Phase K** (deferred per §10.17): `ProposalInput.{trial,formal}_vram_budget_gb`
and `ProposalOutput.vram_risk`. The proposer-side gate would degrade to a
warn-and-proceed no-op for the same reason Phase E2's time gate does
(brand-new `model_name` not yet in `MODEL_REGISTRY` when the proposer
runs), so the plumbing is dead code today.

`ExperimentMemory.time_mode` (already added in J.1) now describes both
gates' active mode for the round — no second `vram_mode` field needed,
they always agree.

### 10.5 VRAM + time skills — distributed per-phase estimators

The VRAM skill has two responsibilities: a **budget gate** (K.2, shipped
2026-04-18 — `min(defensive, budget)` with contention log) and
**multi-phase aggregation** (K.2.5). K.2.5 also applies the same
distribution pattern to the time skill, because a round's wall-time has
exactly the same structure: three phases run sequentially, each on a
different resource axis, each with its own memory + time profile.

**Three phases, two resources, per-phase adjustability:**

| Phase | VRAM | Time | Adjustability |
|---|---|---|---|
| Training | `num_params × 16 B` + backward activations + focal one-hot + attention | step-count × ms/step × `k(gpu, model_type)` | **Direct** — planner's `train_config` / `loss_config` / `model_config` levers all act here |
| Inference | `num_params × 4 B` + one forward at `inference_batch` + attention at `inference_batch` | forward-step-count × inference-ms/step | **Dependent on training** — no dedicated lever; `inference_batch` is fixed in `core/inference_defaults.py`; architecture is the *same* trained model. Moves only through the `model_config` the planner already adjusted for training. |
| Scoring | **0 GB** — `execute_tools/denoising_score_single.py` is pure NumPy/FFT, no `torch.cuda` imports | `segments × per_segment_seconds / num_workers × server_factor` | **Independent + non-adjustable** — fixed evaluation protocol, runs after training + inference; the planner sees its cost but has no lever to shrink it. |

**Aggregation rules:**

- **VRAM: peak across phases.** Phases run in *isolated subprocesses*
  via `core.sandbox_executor.execute_{training,inference,scoring}`, so
  allocator caches are reclaimed between phases. They compete against
  the same ceiling one at a time; the binding constraint is the phase
  with the highest peak. `feasible = max(phase_peaks) ≤ limit`.
- **Time: sum across phases.** Phases run sequentially, so the total
  wall-time is the sum. `feasible = Σ phase_seconds ≤ budget × 60`.

**File layout after K.2.5:**

```
agent/skills/
  training_skill/
    wrapper.py             # existing — dispatches to sandbox_executor
    estimator.py           # NEW — estimate_peak_bytes + estimate_wall_time_seconds
  inference_skill/
    wrapper.py             # existing
    estimator.py           # NEW — no grads/Adam/focal/backward; uses inference batch
  denoising_score_skill/
    wrapper.py             # existing
    estimator.py           # NEW — VRAM trivially 0; CPU-FFT time with hostname factor
  evaluate_vram_skill/
    wrapper.py             # thin peak aggregator
  evaluate_time_skill/
    wrapper.py             # thin sum aggregator (was monolithic training-only)
    calibration.py         # UNCHANGED — used only by training_skill/estimator.py

core/
  inference_defaults.py    # NEW — inference_batch_for(model_type).
                           #       Source of truth shared between
                           #       sandbox_executor.execute_inference and
                           #       inference_skill/estimator.py.
  scoring_defaults.py      # NEW — server_cpu_factor(hostname) for
                           #       scoring-time cross-server variance.
                           #       Static table in v1; EMA deferred (Q-K-5).
```

**Aggregator contracts (final shape, post K.2.5):**

```python
# evaluate_vram_skill/wrapper.py — peak-VRAM aggregator
def run_skill(sandbox, *, model_type, model_config, train_config, loss_config,
              vram_budget_gb: Optional[float] = None):
    num_params = _count_params(model_type, model_config, loss_config["loss_type"])
    phases = [
        training_estimator.estimate_peak_bytes(model_config, train_config, loss_config, num_params),
        inference_estimator.estimate_peak_bytes(model_type, model_config, num_params),
        denoising_score_estimator.estimate_peak_bytes(),          # returns {"phase": "scoring", "total_bytes": 0}
    ]
    dominant = max(phases, key=lambda p: p["total_bytes"])
    # limit selection + contention log: unchanged from K.2
    feasible = dominant["total_bytes"] <= limit_bytes
    return {
        "estimated_gb":    dominant["total_bytes"] / GB,
        "limit_gb":        limit_bytes / GB,
        "vram_budget_gb":  vram_budget_gb,
        "dominant_phase":  dominant["phase"],
        "phase_breakdown": {p["phase"]: p for p in phases},     # all 3 phases
        "feasible":        feasible,
        ...,
    }

# evaluate_time_skill/wrapper.py — sum-time aggregator
def run_skill(sandbox, *, model_type, model_config, train_config, loss_config,
              sample_set, time_budget_minutes: Optional[float] = None, **kwargs):
    phases = [
        training_estimator.estimate_wall_time_seconds(model_type, model_config, train_config, sample_set, **kwargs),
        inference_estimator.estimate_wall_time_seconds(model_type, model_config, sample_set),
        denoising_score_estimator.estimate_wall_time_seconds(sample_set, num_workers=8),
    ]
    total_sec = sum(p["seconds"] for p in phases)
    feasible  = (time_budget_minutes is None) or (total_sec / 60.0 <= time_budget_minutes)
    return {
        "estimated_minutes":     total_sec / 60.0,
        "budget_minutes":        time_budget_minutes,
        "phase_breakdown":       {p["phase"]: p for p in phases},
        "dominant_phase":        max(phases, key=lambda p: p["seconds"])["phase"],
        "feasible":              feasible,
        ...,
    }
```

**Properties:**

- **Per-phase ownership (drift prevention).** Each estimator lives next
  to the tensor-allocation or execution code that produces the peak —
  `training_skill/estimator.py` next to the training dispatcher,
  `inference_skill/estimator.py` next to the inference dispatcher, etc.
  If `execute_tools/inference_single.py` is later changed to use
  `train_cfg.batch_size` or accumulate outputs on GPU, the forecast MUST
  be updated in the *same* commit in `inference_skill/estimator.py`.
  The invariant "training-peak-VRAM ≥ inference-peak-VRAM" is enforced
  *structurally* by colocation, not by a docstring comment.
- **Inference is dependent, not independent.** The planner sees
  inference's VRAM and time estimates in the `[ACTIVE RESOURCE BUDGETS]`
  block (K.6), but has no direct lever to shrink them — inference
  architecture IS training architecture. This avoids misleading the
  planner into thinking `inference_batch` is tunable when it is not.
- **Scoring is independent + non-adjustable.** Planner sees the cost but
  cannot touch it. Scoring's VRAM estimator always returns 0; its time
  estimator uses a hostname-keyed CPU factor (v1 lilab-calibrated) to
  handle the cross-server variance between local and eventual SDSC
  runs. Full EMA calibration for scoring time is deferred (**Q-K-5**).
- **Time-calibration infrastructure (Phase F) stays put.**
  `evaluate_time_skill/calibration.py` continues to own the asymmetric
  EMA for `k(gpu, model_type)`. After K.2.5 it is imported only by
  `training_skill/estimator.py` (the only phase the EMA was learned
  for). Inference time uses a deterministic forward-only formula;
  scoring time uses the hostname factor.
- **Interface preservation.** The VRAM wrapper's existing return fields
  (`estimated_gb`, `limit_gb`, `vram_budget_gb`, `feasible`,
  `suggestion`, `verdict`) remain unchanged so K.3 / K.4 / K.5 / K.7 /
  K.8 are unaffected. The time wrapper's existing fields
  (`estimated_minutes`, `budget_minutes`, `feasible`, …) likewise.
  Both skills gain `dominant_phase` + `phase_breakdown` — new fields K.6
  may optionally surface in the prompt.

### 10.6 No VRAM calibration file in v1; scoring-time uses a static hostname table

**VRAM** is deterministic from the bytes formulae in the per-phase
estimators (§10.5: `training_skill/estimator.py` for weights + grads +
Adam + backward activations + focal one-hot + transformer attention;
`inference_skill/estimator.py` for weights + one forward pass at
`inference_batch`; `denoising_score_skill/estimator.py` trivially 0).
No learned correction in Phase K.

If post-Phase-K telemetry shows systematic VRAM-estimation drift (e.g.
cuDNN workspace allocations the formula misses), revisit with a
calibration file shaped like time's. Not pre-empted in v1.
**Open Q-K-1**: post-K smoke runs should log
`(estimated_gb, peak_vram_actual_gb)` per completed training so this
question can be answered with data.

**Training time** continues to use the asymmetric-EMA `k(gpu, model_type)`
from Phase F, owned by `evaluate_time_skill/calibration.py` and imported
only by `training_skill/estimator.py` after K.2.5. No change.

**Scoring time** is CPU-bound and therefore server-dependent (lilab vs
SDSC have very different CPU profiles). K.2.5 introduces a static
hostname-keyed multiplier table in `core/scoring_defaults.py`:

```python
_SERVER_CPU_FACTOR = {
    "lilab":   1.0,   # reference; base formula calibrated here
    "expanse": 2.5,   # SDSC — bootstrap guess until real telemetry
}
# unknown hostname → 1.0 + one-time warning, same pattern as unknown GPU in Phase F
```

This captures the coarse cross-server variance without introducing the
full EMA machinery. Scoring is ~5–20% of total wall-time today, so a
~2× error on scoring is a ~10–40% error on the summed-time budget —
tolerable for a v1 gate. Full EMA (k_scoring learned per hostname,
updated per completed round) is deferred as **Q-K-5**, to be revisited
once post-K smoke shows whether the static factors are accurate enough.

### 10.7 Joint orchestration at the call sites

Renumber the tuner round-loop from the current 3-step (VRAM-check + Train
+ Score + Reflect, with VRAM mislabeled as `[Step 1/3]`) to a clean
two-block structure: **two pre-flight gates**, then **three execution
steps**. This avoids fractional numbering and surfaces the gate-vs-work
distinction in the log:

```
[Pre-flight 1/2] VRAM check  ──► skipped_oom_risk on fail
[Pre-flight 2/2] Time check  ──► skipped_time_risk on fail (skipped if VRAM failed)
[Step 1/3]       Train
[Step 2/3]       Score
[Step 3/3]       Reflect
```

VRAM short-circuits time so the more expensive warmup (~1–3 s) doesn't
run on a config that's already failing the cheap check.

| VRAM gate | Time gate | Outcome |
|---|---|---|
| pass | pass | proceed to training |
| fail | not run (short-circuited) | `skipped_oom_risk` record, continue (no round consumed) |
| pass | fail | `skipped_time_risk` record, continue (no round consumed) |
| pass (no budget set) | pass (no budget set) | proceed to training (both gates disabled) |

One skipped record per attempt, never two — keeps the
`max_attempts = max_rounds × 3` accounting clean.

### 10.8 Per-mode pick (mirror Phase I.2)

Tuner `[Pre-flight 1/2]`:
```python
chosen_vram_budget = (input.trial_vram_budget_gb if plan.is_trial
                      else input.formal_vram_budget_gb)
```

Identical structure to the time gate's per-mode pick (§2.7.3 + Phase I.2).
No proposer-side per-mode pick in Phase K (deferred per §10.17).

### 10.9 Protocol pass-through (mirror Phase I.3, narrowed)

- `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.local_validated_model`:
  add `trial_vram_budget_gb` + `formal_vram_budget_gb` as caller kwargs;
  conditional-inclusion pattern preserved (only added to the result dict
  when the caller supplied them). **No `vram_risk` surfacing** —
  resource info reaches the planner via the prompt block (§10.11) only
  (single-channel rule, §10.3).
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`:
  **no change in Phase K** (no proposer-side VRAM gate; deferred per
  §10.17).
- `agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py`: no
  change (implementor doesn't need budget fields).

### 10.10 CLI surface (mirror Phase I.4, narrowed)

- `run_exploration_adaptive.py`: `--trial_vram_budget_gb`,
  `--formal_vram_budget_gb`. Default `None`. Startup banner extends to
  print both per-mode VRAM budgets next to the time budgets.
- `workflows/model_exploration.py`: fan out both fields to
  `HyperparamTuningInput` (via `local_validated_model`) only. **No
  `ProposalInput` fan-out** (no proposer-side gate in Phase K).
- `nodes/ml_hyperparameter_tune_agent.py` argparse: add the two flags.
- `nodes/ml_model_proposal_agent.py` argparse: **no change** (debug-only
  entry point + no proposer-side gate).

### 10.11 Planner prompt update

`agent/prompts.py` planner sections change as follows:

1. **Remove** the abstract "GPU MEMORY RULES" section (lines 74–82). It
   has no numeric ceiling and is now strictly less informative than
   §10.3's two new blocks.
2. **Add** the `[ACTIVE RESOURCE BUDGETS]` block (numeric, per-round),
   fed by the two tuner-input budget fields and the active mode. Renders
   `vram_estimate_gb`, `time_estimate_minutes`, the matching budgets,
   the resulting factors, and the current `batch_size` so the LLM can
   reason about both axes at once.
3. **Append** the `[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]`
   guidance block (static text from §10.3), positioned near the existing
   exploration checklist.

Both blocks are static-text injections from the planner-side prompt
builder; no per-round LLM parameter changes. The `experiment_history`
block already carries `time_estimate_minutes` and `time_budget_minutes`
per round (Phase J); §10.4's `vram_estimate_gb` + `vram_budget_gb`
additions extend the same memory channel so previous rounds' estimates
are visible automatically.

**Single-channel rule (§10.3 rule 2).** The planner sees resource
information **only** via these two prompt blocks plus the
`experiment_history` memory fields. Phase K does not surface any
`vram_risk` text via `expert_advice`. Time's existing `time_risk →
expert_advice` route is preserved for now to avoid retroactively breaking
Phase J, and is queued for retirement in §10.17.

### 10.12 Files touched

| Path | Change |
|---|---|
| `agent/skills/evaluate_resource_skill/` → `agent/skills/evaluate_vram_skill/` | **K.0+K.2+K.2.5**: rename directory; update `wrapper.py` to accept `vram_budget_gb` kwarg + emit contention-detection log + downgrade `suggestion` to verdict-style summary (K.2); then delete `_estimate_bytes`, become a peak aggregator over 3 per-phase estimators (training + inference + scoring), expose `dominant_phase` + `phase_breakdown` (K.2.5) |
| `agent/skills/evaluate_time_skill/wrapper.py` | **K.2.5**: delete monolithic training-only step-count + ms/step body; become a sum aggregator over 3 per-phase `estimate_wall_time_seconds` calls; preserve existing return fields (`estimated_minutes`, `budget_minutes`, `feasible`); expose `dominant_phase` + `phase_breakdown` |
| `agent/skills/evaluate_time_skill/calibration.py` | **K.2.5**: unchanged in substance (asymmetric EMA of `k(gpu, model_type)` from Phase F stays); imported only by `training_skill/estimator.py` after refactor |
| `agent/skills/evaluate_vram_skill/skill_config.json` | add `vram_budget_gb` to parameters block (optional) |
| `core/inference_defaults.py` | **K.2.5 NEW**: `inference_batch_for(model_type) -> int` — one source of truth shared between `sandbox_executor.py` and `inference_skill/estimator.py` |
| `core/scoring_defaults.py` | **K.2.5 NEW**: `server_cpu_factor(hostname) -> float` — static hostname-keyed multiplier for scoring-time cross-server variance (lilab=1.0; others bootstrap 1.0 + warn). EMA deferred to Q-K-5. |
| `core/sandbox_executor.py` | **K.2.5**: refactor the hard-coded inference-batch dict (~L346–L350) to call `inference_defaults.inference_batch_for` |
| `agent/skills/training_skill/estimator.py` | **K.2.5 NEW**: `estimate_peak_bytes(...)` — training-phase memory (weights × 16 B + output logits + backward activations + focal one_hot + transformer attention); `estimate_wall_time_seconds(...)` — step-count × ms/step × `k(gpu, model_type)` (Phase F calibration carried over) |
| `agent/skills/inference_skill/estimator.py` | **K.2.5 NEW**: `estimate_peak_bytes(...)` — weights × 4 B + one batch's forward activations + attn at `inference_batch`; no grads / Adam / focal; `estimate_wall_time_seconds(...)` — forward-only step count at `inference_batch` × inference-ms/step |
| `agent/skills/denoising_score_skill/estimator.py` | **K.2.5 NEW**: `estimate_peak_bytes(...)` returns `{phase: "scoring", total_bytes: 0}` (CPU-only by design); `estimate_wall_time_seconds(...)` = `segments × per_segment_seconds / num_workers × server_cpu_factor(hostname)` |
| `tests/unit/core/test_inference_defaults.py` | **K.2.5 NEW**: model-type → batch-size contract |
| `tests/unit/core/test_scoring_defaults.py` | **K.2.5 NEW**: hostname → factor contract (known hosts return non-1.0, unknown hosts return 1.0 with warning) |
| `tests/unit/agent/training_skill/test_estimator.py` | **K.2.5 NEW**: VRAM numeric correctness (CE vs focal, RNN vs transformer, batch scaling); time numeric correctness against Phase B-F regression (same inputs → same ms output as pre-refactor) |
| `tests/unit/agent/inference_skill/test_estimator.py` | **K.2.5 NEW**: VRAM numeric correctness + `training ≥ inference` invariant for a representative config (+ monkeypatched inversion test); time monotone in `segments` and `inference_batch` |
| `tests/unit/agent/denoising_score_skill/test_estimator.py` | **K.2.5 NEW**: VRAM always 0; time scales with segments and inversely with num_workers; hostname factor applied |
| `tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py` | **K.2.5**: extend — sum-aggregation regression (training-only input preserves today's estimate), 3-phase breakdown presence, dominant_phase = "training" in typical case |
| `agent/schemas/hyperparam_tuning.py` | add `trial_vram_budget_gb` + `formal_vram_budget_gb` to `HyperparamTuningInput`; add `vram_estimate_gb` + `vram_budget_gb` to `ExperimentMemory`; **K.7**: add `GateExhaustionInfo` model + `HyperparamTuningOutput.gate_exhaustion` field |
| `agent/schemas/proposal.py` | **K.7**: add `ProposalInput.prior_iteration_gate_exhaustion: Optional[GateExhaustionInfo]` (proposer-side VRAM gate fields remain deferred per §10.17) |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | **K.7**: add `prior_tune_output` kwarg; surface its `gate_exhaustion` into `ProposalInput.prior_iteration_gate_exhaustion` (other proposer-side VRAM kwargs deferred per §10.17) |
| `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` | accept the two VRAM budget kwargs (conditional-inclusion pattern); forward into `HyperparamTuningInput` |
| `nodes/ml_hyperparameter_tune_agent.py` | rename skill name in `_run_skill` calls; renumber the round-loop to `[Pre-flight 1/2]` + `[Pre-flight 2/2]` + `[Step 1/3]..[Step 3/3]`; pass `chosen_vram_budget` per-round; emit `vram_estimate_gb` + `vram_budget_gb` in success-record memory (mirroring Phase J for time); same fields on `skipped_oom_risk` record; add `--trial_vram_budget_gb` / `--formal_vram_budget_gb` to argparse; **K.7**: implement `_build_gate_exhaustion` and populate `HyperparamTuningOutput.gate_exhaustion` at finalisation |
| `nodes/ml_model_proposal_agent.py` | **no change in Phase K** for the proposer-side VRAM gate (deferred per §10.17). The proposer's *prompt* changes via `agent/prompts.py` for K.7 — no node logic touched. |
| `agent/prompts.py` | remove abstract "GPU MEMORY RULES" section; add `[ACTIVE RESOURCE BUDGETS]` block (per-round, numeric, includes vram/time estimates + factors + current batch_size); append `[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]` guidance block (static); **K.7**: add conditional `[PRIOR ITERATION GATE EXHAUSTION]` block in the proposer template |
| `run_exploration_adaptive.py` | add `--trial_vram_budget_gb` / `--formal_vram_budget_gb`; extend startup banner |
| `workflows/model_exploration.py` | fan out both VRAM budget fields to `HyperparamTuningInput` only (via `local_validated_model`); **K.7**: retain previous tuner output and pass as `prior_tune_output` to next-iteration `local_full_context` |
| `tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_vram_skill.py` | **K.2**: new — budget kwarg routing, defensive-floor + budget min, contention-detection log, None-pass-through behaviour. **K.2.5**: training-dominant regression, inference-dominant crossover, `phase_breakdown` presence (all 3 phases incl. scoring=0) |
| `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py` | new tests — per-mode VRAM pick, joint short-circuit (VRAM fail → time skill not invoked), `vram_estimate_gb` in success-record memory; **K.7**: `_build_gate_exhaustion` truth-table tests |
| `tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py` | extend with `TestGateExhaustionInfo` for K.7 schema |
| `tests/unit/agent/protocols/test_ml_model_valid_to_ml_model_tune.py` | extend — assert two new VRAM budget kwargs survive |
| `tests/unit/agent/protocols/test_ml_result_interp_to_ml_model_propose.py` | **K.7**: extend — assert `prior_tune_output.gate_exhaustion` lands as `ProposalInput.prior_iteration_gate_exhaustion` |
| `tests/unit/agent/ml_model_proposal_agent/test_prompt_builder.py` (or equivalent) | **K.7**: assert prompt builder includes `[PRIOR ITERATION GATE EXHAUSTION]` block when field is set, omits when None |
| (cross-ref doc-pointer comments in 12 source files) | `docs/time_estimator_implement.md` → `docs/resource_estimator_implement.md` |

### 10.13 Iteration-boundary gate-exhaustion feedback to the proposer

Phase K's per-round gate (§10.7) protects the *current* tuner iteration:
oversize attempts are skipped and the round is not consumed. But it
does nothing across iteration boundaries. If the proposer's baseline is
fundamentally too heavy for the active budgets, every attempt the tuner
generates from that baseline can hit the gate, the tuner exits with no
trained model, and the next iteration's proposer has no idea this
happened — it sees no `experiment_history` entries with useful scores
and may propose another over-budget architecture for the same reason.

§10.13 closes that loop: when a tuner iteration ends without ever
training successfully, package a structured `GateExhaustionInfo` and
surface it to the next iteration's proposer as a hard learning signal.

#### 10.13.1 Detection criterion

Trigger the signal when **all of the following** hold for the finished
tuner iteration:

- `total_attempts > 0` (the tuner actually ran).
- `ever_trained == False` — no record has `status="success"`.
- `gate_skip_count > 0` — at least one attempt was rejected by either
  `evaluate_vram_skill` or `evaluate_time_skill`
  (`status in {"skipped_oom_risk", "skipped_time_risk"}`).

The third clause filters out unrelated all-failure modes (e.g. every
attempt errored during training due to a code bug). When `ever_trained
== False` but no attempt was gate-rejected, leave `gate_exhaustion =
None` — the proposer doesn't need the budget-related learning signal
because the failure wasn't budget-related.

#### 10.13.2 Schema additions

```python
# agent/schemas/hyperparam_tuning.py

class GateExhaustionInfo(BaseModel):
    """
    Populated by the tuner when an iteration ends without ever training
    successfully AND at least one attempt was rejected by the pre-flight
    resource gate. Surfaced to the next iteration's proposer so it can
    learn the architecture was too heavy for the active budgets.
    """
    total_attempts: int
    vram_gated_attempts: int
    time_gated_attempts: int
    other_failure_attempts: int   # error_*, skipped_schema_violation, etc.

    active_mode: Literal["trial", "formal"]
    vram_budget_gb: Optional[float]
    time_budget_minutes: Optional[float]

    # Round-0 (baseline) factors — diagnoses whether the proposer's own
    # baseline was already over budget vs the tuner mutating it heavier.
    baseline_vram_estimate_gb: Optional[float]
    baseline_vram_factor: Optional[float]
    baseline_time_estimate_minutes: Optional[float]
    baseline_time_factor: Optional[float]

    # Worst case across all attempts — bounds how much lighter the next
    # baseline must be.
    worst_vram_factor: Optional[float]
    worst_time_factor: Optional[float]

    summary_message: str   # human/LLM-readable one-paragraph synthesis


class HyperparamTuningOutput(BaseModel):
    ...existing fields...
    gate_exhaustion: Optional[GateExhaustionInfo] = Field(
        default=None,
        description=(
            "Populated only when the iteration ended without ever training "
            "successfully and ≥1 attempt was rejected by the pre-flight "
            "resource gate. Consumed by the next iteration's proposer."
        ),
    )
```

```python
# agent/schemas/proposal.py

class ProposalInput(BaseModel):
    ...existing fields...
    prior_iteration_gate_exhaustion: Optional[GateExhaustionInfo] = Field(
        default=None,
        description=(
            "When the previous iteration's tuner exited under gate "
            "exhaustion, this field carries the structured failure "
            "report. Surfaced to the proposer prompt as a hard "
            "learning signal."
        ),
    )
```

#### 10.13.3 Tuner population logic (at finalisation)

In `nodes/ml_hyperparameter_tune_agent.py`, just before constructing
the final `HyperparamTuningOutput`, scan `all_records` and populate
`gate_exhaustion` if the §10.13.1 criterion holds. Implementation
sketch:

```python
def _build_gate_exhaustion(records, plan_active_mode,
                           vram_budget_gb, time_budget_minutes):
    if not records:
        return None
    ever_trained = any(r.status == "success" for r in records)
    if ever_trained:
        return None
    vram_gated = [r for r in records if r.status == "skipped_oom_risk"]
    time_gated = [r for r in records if r.status == "skipped_time_risk"]
    if not vram_gated and not time_gated:
        return None   # all-failure but not budget-related
    other = [r for r in records
             if r.status not in {"skipped_oom_risk", "skipped_time_risk"}]
    baseline = records[0]   # round-0
    return GateExhaustionInfo(
        total_attempts=len(records),
        vram_gated_attempts=len(vram_gated),
        time_gated_attempts=len(time_gated),
        other_failure_attempts=len(other),
        active_mode=plan_active_mode,
        vram_budget_gb=vram_budget_gb,
        time_budget_minutes=time_budget_minutes,
        baseline_vram_estimate_gb=_safe_get(baseline.memory, "vram_estimate_gb"),
        baseline_vram_factor=_factor(baseline, "vram", vram_budget_gb),
        baseline_time_estimate_minutes=_safe_get(baseline.memory, "time_estimate_minutes"),
        baseline_time_factor=_factor(baseline, "time", time_budget_minutes),
        worst_vram_factor=_max_factor(records, "vram", vram_budget_gb),
        worst_time_factor=_max_factor(records, "time", time_budget_minutes),
        summary_message=_render_summary(...),
    )
```

`_render_summary` produces a one-paragraph LLM-readable synthesis like:

> "All 9 attempts (rounds 1–3, 3 attempts/round) were rejected by the
> pre-flight VRAM gate. The baseline already estimated 6.4 GB vs the
> 4.0 GB trial budget (factor 1.6×); the tuner's mutations went up to
> 8.1 GB (factor 2.0×). The proposed architecture is fundamentally too
> heavy for the active VRAM budget. Time estimates were within budget
> throughout (worst factor 0.6×)."

#### 10.13.4 Propagation through the workflow

```
tuner emits HyperparamTuningOutput.gate_exhaustion
  → workflow holds previous tune output
  → next-iteration interp→propose protocol surfaces it as
      ProposalInput.prior_iteration_gate_exhaustion
  → proposer prompt renders the [PRIOR ITERATION GATE EXHAUSTION] block
```

Concretely:

- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.local_full_context`:
  add a kwarg `prior_tune_output: Optional[HyperparamTuningOutput]`.
  When supplied AND its `gate_exhaustion` is non-None, copy the
  `GateExhaustionInfo` into the returned `ProposalInput`.
- `workflows/model_exploration.py`: after each tuner run, retain the
  output and pass it as `prior_tune_output` to the next iteration's
  `local_full_context` call.

#### 10.13.5 Proposer prompt section

`agent/prompts.py` gains a new conditional block in the proposer
template:

```
[PRIOR ITERATION GATE EXHAUSTION]
{summary_message}

Resource accounting:
  Mode active:       {active_mode}
  VRAM budget:       {vram_budget_gb} GB
  Time budget:       {time_budget_minutes} min
  Baseline factors:  VRAM {baseline_vram_factor}×   Time {baseline_time_factor}×
  Worst factors:     VRAM {worst_vram_factor}×      Time {worst_time_factor}×
  Attempt counts:    {total} total, {vram_gated} VRAM-gated,
                     {time_gated} time-gated, {other} other failures

For this iteration: propose an architecture that fits the budgets
shown above. The previous proposal could not be trained even after
the tuner attempted to adjust hyperparameters within its lever set
(batch_size, model depth/width). Reduce parameter count and/or layer
count enough that the resulting baseline estimates land below the
budgets.
```

The block renders only when `ProposalInput.prior_iteration_gate_exhaustion`
is non-None. Otherwise it is omitted entirely (no empty section).

#### 10.13.6 Why this is not the same as Deferred-1 (proposer-side gate)

Deferred-1 (§10.17) is a *pre-flight check* on the proposer's own
baseline — it would need `MODEL_REGISTRY` populated for the new
`model_name`, which doesn't happen until the implementor + validator
run. It is dead code today and stays deferred.

§10.13's feedback signal is *post-hoc*: it observes what happened
*after* the implementor + validator + tuner all ran, so the model_type
is registered, attempts have run, and we have measured estimates from
the per-round gate. No registry timing problem.

The two are complementary, not redundant. When Deferred-1 lands, it
catches over-budget proposals at proposal time (cheap, prevents the
whole impl→valid→tune cycle from being wasted). §10.13 catches the
case where the proposer's baseline passes the proposer-side check but
the tuner still can't find a working mutation — i.e. the architecture
is borderline-fit at baseline but every neighbour blows the budget.

#### 10.13.7 Tests

- Unit: `GateExhaustionInfo` schema validation + serialisation.
- Unit: `_build_gate_exhaustion` returns `None` when `ever_trained=True`.
- Unit: `_build_gate_exhaustion` returns `None` when `ever_trained=False`
  but `gate_skip_count == 0`.
- Unit: `_build_gate_exhaustion` populates correctly when both
  conditions hold; baseline factors come from round-0 record; worst
  factors are the max across all records.
- Unit: protocol surfaces `prior_iteration_gate_exhaustion` to
  `ProposalInput` when `prior_tune_output.gate_exhaustion` is non-None;
  leaves it None otherwise.
- Unit: proposer prompt builder includes the new block when the field
  is set; omits the block entirely when None.

### 10.14 Phased implementation checklist

Order matches Phase I + E2 logic: schema first, skill second, agent
integration third, prompt last (so the planner sees the new budgets only
after the gates that enforce them are wired). Each sub-phase ends with
its targeted pytest invocation green and a committable state.

**Top-level progress** (tick as each sub-phase commits + verifies):

- [x] K.0 — Skill rename (mechanical) *(2026-04-18)*
- [x] K.1 — Schema additions (tuner-side only) *(2026-04-18)*
- [x] K.2 — Skill `vram_budget_gb` kwarg + contention-detection log *(2026-04-18)*
- [ ] K.2.5 — Distribute per-phase estimators to owning skills (3 phases × 2 resources: VRAM=peak, time=sum)
- [ ] K.3 — Tuner integration (per-mode pick + memory fields)
- [ ] K.4 — Protocol pass-through (`valid→tune` only)
- [ ] K.5 — CLI + workflow fan-out
- [ ] K.6 — Planner prompt (numeric block + guidance block)
- [ ] K.7 — Iteration-boundary gate-exhaustion feedback (§10.13)
- [ ] K.8 — Smoke run on lilab under contention

#### K.0 Skill rename (mechanical) [ ]

- [ ] `git mv agent/skills/evaluate_resource_skill agent/skills/evaluate_vram_skill`.
- [ ] Search-replace `"evaluate_resource_skill"` → `"evaluate_vram_skill"`
      across all callers (currently `nodes/ml_hyperparameter_tune_agent.py`
      and any test fixtures referencing the skill name string).
- [ ] Verify: `pytest tests/unit/agent/ -q` → all green; no test refers
      to the old name.

#### K.1 Schema additions (tuner-side only) [ ]

- [ ] `HyperparamTuningInput`: add `trial_vram_budget_gb`,
      `formal_vram_budget_gb` (Optional[float], default None) with
      docstrings describing the per-mode behaviour.
- [ ] `ExperimentMemory`: add `vram_estimate_gb`, `vram_budget_gb` (both
      Optional[float], default None); pre-Phase-K records still validate.
- [ ] **Skipped (deferred per §10.17)**: `ProposalInput` /
      `ProposalOutput` additions.
- [ ] Tests: extend `test_hyperparam_schemas.py` with
      `TestExperimentMemoryVramFields` mirroring
      `TestExperimentMemoryTimeFields`.
- [ ] Tests: extend `test_hyperparam_schemas.py` with
      `TestVramBudgetFields` for the two new input fields (default-None,
      type validation, both-set, mode-pick semantics in protocol layer
      covered separately in K.4).
- [ ] Verify: `pytest tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py -q`.

#### K.2 Skill budget kwarg [ ]

- [ ] `evaluate_vram_skill/wrapper.py`: accept `vram_budget_gb`; compute
      `limit_bytes = min(defensive_limit, budget_limit)`; emit the
      contention-detection log line when
      `defensive_limit < budget_limit × 0.5`.
- [ ] When `vram_budget_gb is None`, behaviour is byte-identical to
      today (one regression test for this).
- [ ] Downgrade the `suggestion` field to a verdict-style summary; no
      per-lever branching inside the skill (guidance lives in the prompt
      per §10.3).
- [ ] `skill_config.json`: add `vram_budget_gb` to the parameters block
      (optional).
- [ ] Tests: budget pass-through, defensive vs budget min, contention
      log, None-disabled path, suggestion-string content.
- [ ] Verify: `pytest tests/unit/agent/skills/test_evaluate_vram_skill.py -q`.

#### K.2.5 Distribute per-phase estimators to owning skills (3 × 2) [ ]

Rationale + final aggregator contracts in §10.5. Mid-way between the
K.2 budget kwarg and the K.3 tuner integration. Applied symmetrically
to both resource skills: VRAM = peak over 3 phases, time = sum over 3
phases. **Interface-preserving** for both wrappers' existing return
fields, so K.3 / K.4 / K.5 / K.7 / K.8 are unaffected. The refactor
adds `dominant_phase: str` and `phase_breakdown: dict[str, dict]` to
each wrapper's return — K.6 may optionally surface these in the prompt.

Seven commits in order. Each commit must end with its targeted pytest
invocation green before the next begins. **Lilab is the priority
deployment target**; the SDSC hostname factor is a bootstrap guess
(1.0 + warn on unknown host) and is tuned in a later smoke run — not
in K.2.5.

**Commit 1 — `refactor(core): extract inference_batch_for to inference_defaults`**
- [ ] `core/inference_defaults.py` (new) — expose
      `inference_batch_for(model_type: str) -> int`. Lift the table
      currently at `core/sandbox_executor.py:346–350`
      (`transformer=1, rnn=10, fcnet=punet=wavenet=25`). Unknown
      model-type → `ValueError` (loud — callers must know the shape).
- [ ] `core/sandbox_executor.py` — replace the local
      `_INFERENCE_BATCH_SIZE` dict lookup with
      `inference_defaults.inference_batch_for(...)`.
- [ ] `tests/unit/core/test_inference_defaults.py` (new) — known
      model-types return expected integers; unknown model-type raises.
- [ ] Verify:
      `pytest tests/unit/core/test_inference_defaults.py tests/unit/core/test_sandbox_executor.py -q`.

**Commit 2 — `feat(skill): training_skill/estimator.py — peak VRAM + wall time`**
- [ ] `agent/skills/training_skill/estimator.py` (new) exports two
      functions:
      - `estimate_peak_bytes(model_type, model_config, train_config,
        loss_config, num_params) -> {"phase": "training", "total_bytes", "breakdown"}` —
        body is the current `_estimate_bytes` in the VRAM wrapper:
        `num_params × 16 B` + output logits + backward activations
        (2×) + focal one_hot + transformer attention at
        `train_config.batch_size`.
      - `estimate_wall_time_seconds(model_type, model_config,
        train_config, sample_set, *, ms_per_step=None, gpu_name=None) ->
        {"phase": "training", "seconds", "breakdown"}` — body is the
        step-count × ms/step × `k(gpu, model_type)` logic currently in
        `evaluate_time_skill/wrapper.py`. Imports
        `evaluate_time_skill.calibration` for the k lookup.
- [ ] `tests/unit/agent/training_skill/test_estimator.py` (new):
      - VRAM: CE vs focal, RNN vs transformer, batch/seg scaling.
      - Time: same inputs as an existing `test_evaluate_time_skill.py`
        case → same `seconds` output to within rounding (regression).
- [ ] Verify:
      `pytest tests/unit/agent/training_skill/test_estimator.py -q`.

**Commit 3 — `feat(skill): inference_skill/estimator.py — peak VRAM + wall time`**
- [ ] `agent/skills/inference_skill/estimator.py` (new) exports two
      functions:
      - `estimate_peak_bytes(model_type, model_config, num_params) ->
        {"phase": "inference", "total_bytes", "breakdown"}` —
        `num_params × 4 B` (weights only, no grads/Adam) + one
        inference-batch forward's output logits + forward activations
        (1×, no backward storage) + attention at `inference_batch`
        (from `inference_defaults.inference_batch_for`). No focal
        one_hot — loss is not computed at inference.
      - `estimate_wall_time_seconds(model_type, model_config,
        sample_set, *, inference_ms_per_step=None) ->
        {"phase": "inference", "seconds", "breakdown"}` — forward-only
        step count at `inference_batch` × inference-ms/step. Rough
        factor: `ms_per_step_inference ≈ ms_per_step_training / 3`
        (no backward pass). Phase F's `k(gpu, model_type)` is *not*
        applied — inference ms/step wasn't calibrated.
- [ ] `tests/unit/agent/inference_skill/test_estimator.py` (new):
      - VRAM numeric correctness.
      - `training ≥ inference` invariant holds for a representative
        RNN config.
      - Monkeypatched `inference_batch_for` → huge batch → inference
        wins; the aggregator (tested in commit 5) picks it as dominant.
      - Time monotone in `segments` and `inference_batch`.
- [ ] Verify:
      `pytest tests/unit/agent/inference_skill/test_estimator.py -q`.

**Commit 4 — `feat(skill): denoising_score_skill/estimator.py — 0 VRAM + CPU-FFT time`**
- [ ] `core/scoring_defaults.py` (new) — expose
      `server_cpu_factor(hostname: str) -> float`. Static table:
      `{"lilab": 1.0, "expanse": 2.5}`. Unknown host → 1.0 with
      one-time stderr warning (mirrors Phase F's unknown-GPU pattern).
      **Lilab-priority note**: `expanse: 2.5` is a bootstrap guess;
      real SDSC telemetry tunes it after Phase H2.
- [ ] `tests/unit/core/test_scoring_defaults.py` (new) — known hosts
      return expected factors; unknown host returns 1.0 + emits
      warning (captured via `capsys`/`caplog`).
- [ ] `agent/skills/denoising_score_skill/estimator.py` (new) exports:
      - `estimate_peak_bytes(...) -> {"phase": "scoring", "total_bytes": 0, "breakdown": {}}` —
        trivial (scoring is pure NumPy/FFT by design).
      - `estimate_wall_time_seconds(sample_set, *, num_workers=8,
        hostname=None) -> {"phase": "scoring", "seconds", "breakdown"}` —
        `segments × per_segment_seconds / max(num_workers, 1) ×
        server_cpu_factor(hostname)`. `per_segment_seconds` is a
        module-level constant seeded from lilab smoke.
- [ ] `tests/unit/agent/denoising_score_skill/test_estimator.py` (new):
      - VRAM always 0.
      - Time scales with segments; inversely with num_workers.
      - Hostname factor applied; unknown host warns once.
- [ ] Verify:
      `pytest tests/unit/core/test_scoring_defaults.py tests/unit/agent/denoising_score_skill/test_estimator.py -q`.

**Commit 5 — `refactor(skill): evaluate_vram_skill as peak aggregator over 3 phases`**
- [ ] `agent/skills/evaluate_vram_skill/wrapper.py` — delete
      `_estimate_bytes`; import the three
      `estimate_peak_bytes` functions; count params once; call each
      with the already-counted `num_params`; take
      `max(phases, key=lambda p: p["total_bytes"])`. Expose
      `dominant_phase` + `phase_breakdown` (all 3 phases) in the
      return dict. Keep the budget gate + contention log untouched.
- [ ] Extend `tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_vram_skill.py`:
      - Regression: training-dominant config returns same
        `estimated_gb` as K.2 within floating-point tolerance.
      - Crossover: monkeypatched `inference_batch_for` → inference
        dominates → `result["dominant_phase"] == "inference"`.
      - `phase_breakdown` contains all three phases, with
        `scoring.total_bytes == 0`.
- [ ] Verify:
      `pytest tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_vram_skill.py -q`.

**Commit 6 — `refactor(skill): evaluate_time_skill as sum aggregator over 3 phases`**

Riskier: this commit must preserve Phase B–F behaviour byte-for-byte
for the training-only path. Pre-refactor tests stay as regression.

- [ ] `agent/skills/evaluate_time_skill/wrapper.py` — delete the
      monolithic step-count body; call the three
      `estimate_wall_time_seconds` functions; sum `seconds`. Preserve
      existing return fields (`estimated_minutes`, `budget_minutes`,
      `feasible`, `verdict`, `suggestion`, …) + add
      `dominant_phase` + `phase_breakdown`.
- [ ] Keep `evaluate_time_skill/calibration.py` exactly as-is — it's
      imported only by `training_skill/estimator.py` now.
- [ ] Extend `tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py`:
      - Regression: every existing Phase B–F test (22 tests) still
        passes — the sum across training + 0 + 0 must equal today's
        training-only number (inference/scoring phases add non-zero
        seconds now; adjust assertions to tolerate, document the new
        baseline).
      - Sum semantics: training 60 s + inference 10 s + scoring 5 s
        → `estimated_minutes == 75/60`.
      - `dominant_phase == "training"` in typical case.
      - Budget gate feasibility keyed on the sum.
- [ ] Verify:
      `pytest tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py tests/unit/agent/training_skill tests/unit/agent/inference_skill tests/unit/agent/denoising_score_skill -q`.

**Commit 7 — `docs(resource_estimator): mark K.2.5 complete`**
- [ ] Flip K.2.5 checkboxes to `[x]` in §10.14 top-level progress list;
      add commit hash to the progress-log table row; update §10.5
      opening paragraph's "(K.2.5)" to "(K.2.5, shipped YYYY-MM-DD)".

#### K.3 Tuner integration [ ]

- [ ] `nodes/ml_hyperparameter_tune_agent.py`: per-round
      `chosen_vram_budget = trial if plan.is_trial else formal`; pass to
      `_run_skill("evaluate_vram_skill", ...)`.
- [ ] Stash the VRAM-skill result alongside `time_check` so the success
      record can lift `vram_estimate_gb` + `vram_budget_gb` into memory
      (mirrors Phase J).
- [ ] Same `vram_estimate_gb` + `vram_budget_gb` keys go on the
      `skipped_oom_risk` record (mirrors §J.3 for time).
- [ ] One-time startup warning when both VRAM budgets are None.
- [ ] Renumber the round-loop log lines from the current `[Step 1/3]`
      VRAM check + `[Step ?/3]` time check + `[Step 1/3]..[Step 3/3]`
      execution into the clean `[Pre-flight 1/2]` + `[Pre-flight 2/2]` +
      `[Step 1/3]..[Step 3/3]` scheme defined in §10.7.
- [ ] Tests: per-mode pick, joint short-circuit (VRAM fail → time skill
      not invoked), success-record memory, skipped-record memory,
      gate-disabled path.
- [ ] Verify: `pytest tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py -q`.

#### K.4 Protocol pass-through (`valid→tune` only) [ ]

- [ ] `ml_model_valid_to_ml_model_tune.local_validated_model`: add
      `trial_vram_budget_gb` + `formal_vram_budget_gb` kwargs;
      conditional-inclusion pattern (only added to `HyperparamTuningInput`
      when caller supplies them).
- [ ] **Do NOT** surface `proposal.vram_risk` (no such field in Phase K).
- [ ] **Do NOT** modify `ml_result_interp_to_ml_model_propose.py`
      (no proposer-side gate in Phase K).
- [ ] Tests: extend `test_ml_model_valid_to_ml_model_tune.py`; assert
      both VRAM kwargs survive default-None and user-supplied paths;
      assert independence (one set, other None).
- [ ] Verify: `pytest tests/unit/agent/protocols/ -q`.

#### K.5 CLI + workflow [ ]

- [ ] `run_exploration_adaptive.py`: `--trial_vram_budget_gb`,
      `--formal_vram_budget_gb`; startup banner extends to print both
      VRAM budgets next to the time budgets.
- [ ] `workflows/model_exploration.py`: forward both fields to
      `local_validated_model` only (no `local_full_context` touch).
- [ ] `nodes/ml_hyperparameter_tune_agent.py` argparse: add both flags.
- [ ] Verify: `--help` on both entry points lists the new flags.

#### K.6 Planner prompt [ ]

- [ ] `agent/prompts.py`: remove abstract "GPU MEMORY RULES" section
      (lines 74–82).
- [ ] Add `[ACTIVE RESOURCE BUDGETS]` block fed by the two tuner-input
      VRAM budget fields + active mode + current-round vram + time
      estimates + computed factors + current `batch_size`.
- [ ] Append `[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]` guidance
      block (verbatim text from §10.3).
- [ ] Wire the planner builder to pass current-round `vram_estimate_gb`
      + `time_estimate_minutes` + `batch_size` so the LLM sees the
      estimation pair plus the lever's current setting.
- [ ] *Optional (post-K.2.5)*: surface `dominant_phase` from the VRAM
      skill result so the `[ACTIVE RESOURCE BUDGETS]` block can say e.g.
      `dominant phase: training` — lets the planner distinguish between
      "the forward step is OOM" and "the whole train step is OOM" when
      choosing levers. Skip if it bloats the prompt without changing
      smoke-run decisions.
- [ ] Tests: prompt builder includes the new sections when budgets are
      set; renders `"(no budget — gate disabled)"` when they're None;
      omits `factor` when budget is None; guidance block text appears
      verbatim.
- [ ] Verify: `pytest tests/unit/agent/ -q`.

#### K.7 Iteration-boundary gate-exhaustion feedback (§10.13) [ ]

- [ ] `agent/schemas/hyperparam_tuning.py`: add `GateExhaustionInfo`
      Pydantic model per §10.13.2; add
      `HyperparamTuningOutput.gate_exhaustion: Optional[GateExhaustionInfo] = None`.
- [ ] `agent/schemas/proposal.py`: add
      `ProposalInput.prior_iteration_gate_exhaustion: Optional[GateExhaustionInfo] = None`
      (import `GateExhaustionInfo` from `hyperparam_tuning`).
- [ ] `nodes/ml_hyperparameter_tune_agent.py`: implement
      `_build_gate_exhaustion(...)` per §10.13.3; call at finalisation
      and pass the result into `HyperparamTuningOutput(gate_exhaustion=...)`.
- [ ] `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.local_full_context`:
      add `prior_tune_output: Optional[HyperparamTuningOutput] = None`
      kwarg; surface `prior_tune_output.gate_exhaustion` into the
      returned `ProposalInput`.
- [ ] `workflows/model_exploration.py`: retain previous tuner output;
      pass to next iteration's `local_full_context` call as
      `prior_tune_output=...`.
- [ ] `agent/prompts.py`: add the conditional
      `[PRIOR ITERATION GATE EXHAUSTION]` block per §10.13.5.
- [ ] Tests per §10.13.7: schema validation, `_build_gate_exhaustion`
      truth-table, protocol pass-through, prompt builder
      conditional-rendering.
- [ ] Verify: `pytest tests/unit/agent/tune_ml_hyperparam_agent/ tests/unit/agent/protocols/ tests/unit/agent/ml_model_proposal_agent/ -q`.

#### K.8 Smoke (mirror Phase H1b) [ ]

- [ ] Re-launch `explore_novel_v1` with
      `--trial_vram_budget_gb 4 --formal_vram_budget_gb 8` under
      intentional contention (a second process holding ~25 GB on the
      same GPU).
- [ ] Acceptance:
      - Gate rejects oversize configs against the 4 GB budget, **not**
        against momentary free-VRAM (no `"GPU has only 0.01 GB free"`
        aborts when budget is set).
      - The LLM's next attempt picks the right lever per the §10.3
        guidance — first batch_size when only one factor is over and
        the lever has room, depth/width when batch can't satisfy both.
      - Joint short-circuit holds: time skill's warmup not invoked on
        VRAM-failed attempts (verifiable from the skill's stdout
        signature in the run log).
      - `experiment_history` for round N+1 carries round N's
        `vram_estimate_gb` + `vram_budget_gb` alongside the
        time fields (Phase J already proved the time-side propagation
        works; this verifies the VRAM-side mirror).
- [ ] Gate-exhaustion exercise: deliberately under-budget one
      iteration (e.g. `--trial_vram_budget_gb 0.5`) so the tuner
      cannot escape the gate; verify the next iteration's proposer
      prompt includes `[PRIOR ITERATION GATE EXHAUSTION]` with the
      correct counts and factors, AND the next proposal proposes a
      qualitatively lighter architecture (parameters and/or layer
      count substantially reduced versus the failing baseline).

### 10.15 Acceptance + rollback

**Acceptance**: §10.14's K.8 smoke completes with a non-zero number of
`skipped_oom_risk` records that show the operator budget rather than
free-VRAM as the binding ceiling, and the `vram_estimate_gb` field
appears in the following round's `experiment_history` block
(planner-visible).

**Rollback**: per-skill, per-budget, additive, gated on
`vram_budget_gb is not None`. Setting both VRAM budgets to None reverts
to current behaviour (byte-identical to pre-Phase-K). Codebase
rollback: revert K.2–K.7 in reverse; K.1 (schema additions) is safe to
leave in place as dormant infrastructure. K.0 (skill rename) is the
only step coupled to all callers — if rolling K.0 back, also revert the
caller updates that reference the new name.

### 10.16 Phase K open questions

- **Q-K-1** (carries forward from §10.6): VRAM estimation drift. If
  post-K smoke shows `peak_vram_actual_gb` consistently exceeding
  `estimated_gb` by >20%, a term is missing from the per-phase estimator
  whose phase dominates (`training_skill/estimator.py` for training-bound
  workloads, `inference_skill/estimator.py` otherwise — use the wrapper's
  `dominant_phase` field to locate which one). Likely suspects: cuDNN
  workspace or the PyTorch caching allocator's fragmentation overhead.
  Decide whether to add a static safety multiplier (cheap) or a
  calibration file shaped like time's (more accurate, more code).
  Telemetry needed before deciding.
- **Q-K-2**: Budget defaults. Both VRAM budgets default to `None` for
  symmetry with time. If we want non-`None` defaults later: trial ≈ 4 GB
  (matches the prose ceiling currently in expert advice); formal ≈ 8 GB
  (educated guess; the formal-mode VRAM profile hasn't been
  characterised yet). Revisit once a few formal runs have completed.
- **Q-K-3**: Joint-record consistency. K.6's `[ACTIVE RESOURCE BUDGETS]`
  block surfaces previous-round estimates from `experiment_history`. If
  the previous round's record was a `skipped_*_risk` (not a success),
  some fields may be partially populated (the gate that ran has them;
  the gate that didn't run because of short-circuit doesn't). Decide
  whether the prompt should render `"(not measured — VRAM failed first)"`
  vs simply omitting the line. Lean toward explicit "not measured" so
  the LLM doesn't infer absence from silence.
- **Q-K-4** *(addressed by K.2.5)*: Time-side phase asymmetry. Before
  K.2.5 the time skill modelled training wall-time only, while the VRAM
  skill (post-K.2.5) spans training + inference + scoring. K.2.5
  resolves this by symmetrically distributing time estimators across
  the same three phases and summing. Kept here as a historical pointer
  for anyone reading the pre-K.2.5 doc.
- **Q-K-5**: Scoring-time EMA calibration. K.2.5 ships a static
  hostname-keyed multiplier (`core/scoring_defaults.py`) as a
  pragmatic v1. If post-K smoke shows the static factors drift by >30%
  on any server (particularly once SDSC H2 runs surface real
  `expanse` data), replace the static table with an asymmetric-EMA
  calibration of `k_scoring(hostname)` mirroring Phase F's
  `k(gpu, model_type)`. Until then, static table + "unknown host → 1.0
  + warn" is the contract.

### 10.17 Deferred from Phase K (future cleanup)

Two related cleanups are explicitly out of scope for Phase K. They are
captured here so they are easy to find later, not abandoned.

**Deferred-1 — Proposer-side VRAM gate.** Adding `_apply_vram_gate` to
`nodes/ml_model_proposal_agent.py` plus the `vram_risk` field on
`ProposalOutput` plus protocol pass-through plus
`test_baseline_vram_gate.py` would mirror Phase E2 perfectly — but
inherits E2's same dead-code property: the brand-new `model_name` the
proposer just invented isn't in `MODEL_REGISTRY` until the implementor
runs and the validator registers it, so `_count_params` raises and the
gate degrades to warn-and-proceed. Net behaviour today: no actual
gating. Defer until plugins can be tentatively registered at proposal
time (or until a parameter-counting path exists that doesn't need
`MODEL_REGISTRY`).

**Deferred-2 — Retire `time_risk` redundancy on `ProposalOutput`.**
Phase J's `time_risk → expert_advice` route was useful when the planner
had no other channel for time information. With Phase K's
`[ACTIVE RESOURCE BUDGETS]` prompt block carrying numeric estimates +
budgets + factors directly, `time_risk` becomes a redundant second
channel that violates the §10.3 "one channel only" rule. Phase K keeps
it to avoid retroactively breaking Phase J's tests and behaviour, but
the cleanup should: (a) remove `_apply_time_gate`'s
`output.time_risk = ...` write, (b) drop the `proposal.time_risk`
prepend in `local_validated_model`, (c) drop the field from
`ProposalOutput`, (d) update the relevant tests. Coordinate with
Deferred-1 — both touch the same files, so they should land together
when the proposer-side gate becomes activatable.
