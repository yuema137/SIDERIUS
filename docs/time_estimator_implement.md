# Time-Budget Estimator Skill

**Status**: implemented (Phases A–G complete; H1 lilab + H2 SDSC smoke runs deferred — different environments, see Phase H)
**Author**: design discussion 2026-04-16
**Motivation**: two trial-mode runs (`exploit_cnn_v1`, `explore_novel_v1`) stalled in Round 1 for 1h 50min and 2h 27min respectively, both blowing past the 1-hour trial budget stated in the expert advice. Neither was blocked, because the planner has no pre-flight wall-time estimate — only a VRAM check.

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
| H1 — lilab smoke run (interactive GPU) | deferred | — | local end-to-end; catches code-level bugs before SDSC |
| H2 — SDSC smoke run (Slurm batch, chained) | deferred | — | gated on H1 passing; tests batch-system specifics (env-var override, GPU stability across restarts, concurrent-writer safety) |

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

#### 2.6.7 Accuracy layers summary

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
| `time_budget_minutes` | ✅ yes (default `None`, gate disabled) | ✅ yes (default `None`, gate disabled) |
| `data_dir` | ✅ yes (default `None`) | ✅ yes (default `None`) |

The `constraints: List[str]` field on `ProposalInput` holds free-text prose like `'VRAM < 10 GB'`; the numeric channel now lives in the fields above. The `ProposalOutput.time_risk: Optional[str]` field (added in Phase E0) carries the gate-and-annotate suggestion text — see §2.7.4.

#### 2.7.2 Fan-in origin: workflow orchestrator

The trial-mode data-sampling set (`is_trial`, `trial_strategy`, `trial_portion`, `target_files`, `train_portion`, `sampling_seed`) and the budget set (`time_budget_minutes`, `data_dir`) are **run-level parameters** — they do not originate in the interpretation agent (upstream of the proposer) or the proposer (upstream of the tuner). They originate at the workflow/CLI entry point (`run_exploration_adaptive.py`) and fan out:

```
CLI args ──► workflow runner ─┬─► ProposalInput(is_trial, trial_strategy, trial_portion, target_files,
                              │                 train_portion, sampling_seed,
                              │                 time_budget_minutes, data_dir)
                              │
                              └─► HyperparamTuningInput(is_trial, trial_strategy, trial_portion, target_files,
                                                       train_portion, sampling_seed,
                                                       time_budget_minutes, data_dir, ...)
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
result = run_skill(sandbox, **{
    "model_type":          output.model_name,          # proposed name
    "model_config":        output.baseline_config["model_config"],
    "train_config":        output.baseline_config["train_config"],
    "loss_config":         output.baseline_config["loss_config"],
    "sample_set":          sample_set,
    "train_portion":       input.train_portion,
    "time_budget_minutes": input.time_budget_minutes,
    "data_dir":            input.data_dir,
})
# Act on result.feasible per §2.7.4 policy.

# In ml_hyperparameter_tune_agent, at [Step 0.5/3] each round:
result = run_skill(sandbox, **{
    "model_type":          input.model_type,
    "model_config":        trial.model_config,
    "train_config":        trial.train_config,
    "loss_config":         trial.loss_config,
    "sample_set":          self.sample_set,                           # already built in __init__
    "train_portion":       input.train_portion,
    "time_budget_minutes": input.time_budget_minutes,
    "data_dir":            input.data_dir,
})
# Act on result.feasible per existing VRAM-gate pattern.
```

Identical shape, identical skill body, identical trial-mode parameterisation of `sample_set` — the only difference is that the tuner caches `self.sample_set` for reuse across rounds, while the proposer builds it once for its single baseline estimate.

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
  - `ProposalInput` gains the training-side trial-mode mirror (`is_trial`, `trial_strategy`, `trial_portion`, `target_files`, `train_portion`, `sampling_seed`) plus `time_budget_minutes: Optional[float]` and `data_dir: Optional[str]`. Defaults match `HyperparamTuningInput` so an omitted CLI arg behaves identically across the two gates. Legacy single-file mode (`file_index`, `is_trial=False`) is intentionally not surfaced here — modern usage uses `is_trial=True` + `trial_strategy='target'` + `target_files=[N]`.
  - `ProposalOutput` gains `time_risk: Optional[str]` (gate-and-annotate, §2.7.4).
  - `HyperparamTuningInput` gains `time_budget_minutes: Optional[float]` and `data_dir: Optional[str]` (the trial-mode set already exists).
- **Workflow fan-out** in `run_exploration_adaptive.py` / `workflows/model_exploration.py`: a single CLI args block populates both `ProposalInput` and `HyperparamTuningInput` with the same trial-mode + budget set (§2.7.2 fan-in diagram).
- **Protocol pass-through**: `ml_result_interp_to_ml_model_propose.local_full_context` accepts the new fields as caller-supplied kwargs and forwards them into `ProposalInput`. `ml_model_valid_to_ml_model_tune.local_validated_model` accepts `time_budget_minutes` / `data_dir` (the trial-mode set was already wired) and surfaces `proposal.time_risk` to the tuner's `expert_advice` as round-0 guidance, ordered after spec/inheritance deviation notes.
- CLI flag `--time_budget_minutes` on `run_exploration_adaptive.py`.
- Unit tests: skill in isolation with mocked torch, asymmetric-EMA math, calibration-file I/O, proposer baseline-gate (annotate path). Integration test with a tiny real model on GPU; pseudo-mode test that an over-budget baseline yields a non-None `time_risk`.

### 3.2 Out of scope (deferred)

- Inference-time estimate (phase 2 — additive, same skill).
- Override-disclosure prompt change (separate doc/PR).
- Budget enforcement in formal (non-trial) mode — formal runs are expected to be long; phase 1 gates trial mode only.
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
| `nodes/ml_hyperparameter_tune_agent.py` | add `[Step 0.5/3]` call + `skipped_time_risk` branch; add post-training hook that writes back to calibration file |
| `nodes/ml_model_proposal_agent.py` | add baseline-gate skill call right before returning `ProposalOutput`; populate `time_risk` per §2.7.4 |
| `agent/schemas/proposal.py` | add the trial-mode mirror (`is_trial`, `trial_strategy`, `trial_portion`, `target_files`, `train_portion`, `sampling_seed`) + `time_budget_minutes` + `data_dir` to `ProposalInput`; add `time_risk: Optional[str]` to `ProposalOutput`. Defaults track `HyperparamTuningInput` exactly. |
| `agent/schemas/hyperparam_tuning.py` | add optional `time_budget_minutes: float`, `data_dir: Optional[str]` to `HyperparamTuningInput` (trial-mode set already present) |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | accept the trial-mode mirror + `time_budget_minutes` / `data_dir` as caller-supplied kwargs (each falls through to the schema default when `None`) and forward them into `ProposalInput`. Conditional-inclusion pattern: only added to the result dict when the caller supplied them, so partial workflow plumbing doesn't silently reset a field. |
| `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` | accept `time_budget_minutes` / `data_dir` as caller-supplied kwargs (the trial-mode set was already wired); read `proposal.time_risk` and prepend it to `expert_advice` after `spec_deviation_notes` / `inheritance_deviation_notes` (order: spec → inheritance → time_risk → base advice) |
| ~~`agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py`~~ | **no change** — `ImplementorInput` does not need any of these fields; the validator→tuner fan-in protocol reads `time_risk` from `ProposalOutput` directly |
| `run_exploration_adaptive.py` | add `--time_budget_minutes` CLI arg; forward the trial-mode + budget set into the workflow context |
| `workflows/model_exploration.py` (or equivalent entry) | fan out the trial-mode + budget set to **both** `ProposalInput` and `HyperparamTuningInput` (§2.7.2) |
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

- The skill is purely additive. Existing flows that don't pass `time_budget_minutes` see no behavior change — the tune agent treats a missing budget as "skip the time gate" (feasible=True, warning printed once).
- `HyperparamTuningInput.time_budget_minutes` is optional with default `None`. Existing config JSON round-trips unchanged.
- No changes to record schemas except adding `"skipped_time_risk"` as an allowed `status` value in `ExperimentRecord` (mirrors existing `"skipped_oom_risk"`).

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

The CLI surface (`--time_budget_minutes`, `--trial_strategy`, `--target_files`, `--sampling_seed`, `--data_dir`) and the startup-print block both landed in E0 (commit `f7d2f04`). The default for `--time_budget_minutes` is `None`, not 60 — this keeps the gate off until the user explicitly opts in, matching the "additive, opt-in" stance in §5.

What remains here is just the gitignore housekeeping:

- [x] `time_calibration_*.json` added to `.gitignore` (defensive — the file lives at `~/.siderius/` by default per §2.6.4, but the `SIDERIUS_CALIBRATION_DIR` env-var override could land it inside the repo tree).
- **Verified**: `git check-ignore time_calibration_test.json` → matches `.gitignore:47`.

### Phase H — First real-GPU smoke run

H is **two separate runs on two separate environments**. They test different things and the acceptance criteria only partially overlap. Do H1 first (faster iteration, no queue wait); only move to H2 once H1's calibration entries look sane.

---

#### Phase H1 — lilab (local interactive GPU) [deferred]

Lilab is a single-host interactive GPU box. The skill runs in-process, the calibration file lives at `~/.siderius/time_calibration_<gpu>.json`, and the `_measure_ms_per_step` warmup path is fully exercised. This is where we catch code-level bugs — torch device placement, DataLoader worker count, HDF5 access, `_count_params` for each real model class, the atomic-write race on a hot filesystem.

- [ ] Submit an over-budget config with `--time_budget_minutes 10` and a config known to need ~30 min → confirm the tuner gate blocks round 1 and a `skipped_time_risk` record lands in the workspace.
- [ ] Submit a ~5-min config with `--time_budget_minutes 30` → confirm the gate passes, training completes, `~/.siderius/time_calibration_<lilab_gpu>.json` gains a history entry, and `k` shifts in the right direction (down if warmup over-predicted, up if it under-predicted).
- [ ] Inspect the history entry: `ratio` finite, `estimate_violated` consistent with `actual_minutes > estimated_minutes`, UTC timestamp present.
- [ ] Run the same config a **second time** — confirm `k` is re-read from disk (no in-process cache) and the EMA blends the two entries as expected.
- [ ] Mark H1 `[x]` with the lilab GPU name and run_name in the Progress log.

H1 acceptance = the skill runs end-to-end on a real GPU with real data. No batch-system concerns.

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
2. **Budget default**: 60 min matches the current expert-advice prose. Formal-mode gate is deferred; if we enable it later, default is probably 4 h.
3. **EMA α constants**: `α_up=0.5, α_down=0.1` are educated guesses. Once a few real entries accumulate, sanity-check these by replay — do we converge too slow/fast? Tune then.
4. **Calibration file location**: `~/.siderius/` by default; override with `SIDERIUS_CALIBRATION_DIR` env var so SDSC users can point to `$HOME` or `$SCRATCH` depending on quota.
5. **`skipped_time_risk` enum location**: wherever `skipped_oom_risk` lives in the record schema — confirm path in Phase E1.
6. **Gate-and-revise switch threshold (§2.7.4)**: v1 ships gate-and-annotate. Concrete trigger to revisit: if >20% of baselines across a 2-week window get rejected by the tuner's round-0 gate, switch the proposer to gate-and-revise. Need a small telemetry counter on `ProposalOutput.time_risk is not None` to measure this — open whether that lives in the workspace records or a separate log.
7. **`build_sample_set` location (§2.7.5)**: currently inside `nodes/ml_hyperparameter_tune_agent.py`. Cleanest is to relocate to `agent/skills/evaluate_time_skill/sample_set_util.py` (or `agent/utils/`) so both nodes import from a neutral place. Defer the call: if Phase E2 finds the import works without circularity, leave it where it is; otherwise relocate. Decide in E2.
8. **Proposer's response to skill `status="error"`**: v1 silently warns and proceeds (no `time_risk` set). Alternative: hard-fail the proposal so the workflow can't silently emit an unestimated baseline. Lean toward warn-and-proceed because skill errors are usually environmental (no `data_dir`, CUDA hiccup) rather than the baseline being broken — but worth confirming in smoke testing.
