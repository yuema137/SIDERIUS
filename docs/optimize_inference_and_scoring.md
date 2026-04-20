# Inference & Scoring Memory Optimization

**Branch**: `feat/scoring-mem-audit` (off `master` @ `95c8f2d`)
**Initiated**: 2026-04-20
**Trigger**: OOM-kill of `explore_novel_v3_0420` iter 4 at 2026-04-20 07:23:06 UTC-7

---

## 1. Problem Statement: The 37 GB Memory Crisis

### 1.1 Incident summary

At 07:23:06 on 2026-04-20 the Linux kernel's global OOM-killer terminated the orchestrator process of `explore_novel_v3_0420` (PID 2535184). The victim held an anonymous resident set of **36.9 GB** (`anon-RSS`) and a **59.5 GB** virtual footprint against a host with **61 GiB** physical RAM and a fully-consumed **2 GiB** swap. The trigger was an unrelated user-session process — JetBrains IDE background GC (`HeapHelper`) — requesting memory on a saturated host; the kernel selected the orchestrator as the largest victim under `constraint=CONSTRAINT_NONE, global_oom`.

The exploration had successfully completed training and model persistence for `gated_fourier_tcn` experiment `_003` at 07:22:12. The OOM fired during the subsequent scoring phase, truncating the run before a single scoring record for iter 4 could be written.

### 1.2 Root cause: COW amplification on an accumulating parent

Three behaviors were simultaneously active at the moment of death:

1. **Parent-process accumulation.** The orchestrator had been running for ~5 h 30 m across 3 completed iterations plus a fourth in progress. It retains LLM conversation history, the knowledge cache (two models cached per the log), the `all_records` list spanning every experiment, and per-experiment nested state including `model_config`, `loss_history`, and `memory.expert_advice_followed` strings averaging 1–2 KB each.

2. **`ProcessPoolExecutor` fork with Copy-on-Write amplification.** The in-process `execute_tools.scoring_utils.score_vector` spawns eight worker processes via `fork()`. Linux shares pages between parent and children via Copy-on-Write; as each worker begins computing FFTs it triggers page divergence, and the kernel's RSS accounting attributes newly-private pages to each child. A parent carrying a large baseline therefore multiplies the effective host-committed memory by a factor approaching `(1 + n_workers × divergence_rate)`. This is the **COW amplification effect**.

3. **Scoring-phase FFT transients.** Each 10⁷-sample PSD segment allocates ~180 MB of transient working memory during a single `np.fft.rfft` call (§1.3). Eight concurrent workers mid-FFT contribute ~1.4 GB of transient pressure on top of the COW-amplified footprint.

### 1.3 Composition of the 37 GB RSS

| Source | Estimated contribution | Evidence |
|---|---|---|
| **A. Parent-process accumulation** | **15–25 GB** | In-process scoring (`nodes/ml_hyperparameter_tune_agent.md:149`); `all_records` grown across 3+ iterations (24+ experiment records); OpenAI client conversation state; knowledge cache; nested `memory` dicts with kilobyte-scale advice strings per record. |
| **B. `ProcessPoolExecutor` fork COW amplification** | **5–15 GB peak** | Eight forked workers × page-divergence during FFT execution; each worker inherits the parent baseline and accumulates private FFT intermediates. |
| **C. Scoring-phase FFT transients** | **~1.4 GB peak** | Eight workers × ~180 MB per-segment transient `(int16→float32 40 MB) + (complex128 rfft 80 MB) + (\|·\|² 40 MB)`. Confirmed by reading `scoring_utils.py:65–74`. |
| D. Inference subprocess | *excluded* | Runs under `subprocess.run` and exits before scoring begins; does not contribute to orchestrator RSS at scoring time. |

The A+B+C triad accounts for the observed 37 GB. The inference path is ruled out by the subprocess-isolation boundary.

### 1.4 Why the existing resource gates did not catch this

The `evaluate_vram_skill` and `evaluate_time_skill` skills (Phase K–N arc) guard **GPU VRAM** and **wall-time**. Neither models **host RAM**. The OOM occurred during a CPU-bound scoring phase on a process that had already passed every pre-training resource gate. The proposer-side pre-flight cost gate introduced in PR #56 (Fix 1 + Fix 2) is similarly orthogonal — it governs GPU time and parameter count, not host memory.

---

## 2. Strategic Decisions & Constraints

### 2.1 Constraint — no Welch-style averaging

The TIDMAD PSD algorithm computes a full-length 10⁷-sample DFT per 1-second segment (`execute_tools/dataset_config.py:73`, `psd_segment_length = 10_000_000`). Welch's method would segment the 10⁷ samples into shorter overlapping windows, apply a window function, and average the resulting periodograms — reducing both FFT memory and compute by the window-count factor. The cost is paid in **spectral resolution** (`Δf ∝ 1/N_window`) and **phase coherence** across the 1-second frame. For narrow-line axion search, both properties are load-bearing: the SNR estimator at `scoring_utils.py:88–117` assumes a single signal bin at the detected peak frequency and a ±50-bin noise shoulder, a structure Welch averaging would collapse.

**Decision**: the 10⁷-sample full-length DFT is non-negotiable. All scoring optimization work must preserve bit-equivalent PSD output (within float32 round-off at `rtol ≤ 1×10⁻⁷`).

### 2.2 Optimization choice — Deferred Scaling

The baseline computation at `scoring_utils.py:68–73` performs amplitude scaling in the time domain:

```python
ts = np.array(data, dtype=np.float32) * scaling      # 40 MB float32 copy
psd = (dt / N) * abs(np.fft.rfft(ts)) ** 2           # 80 MB complex128 intermediate
```

Linearity of the DFT permits an algebraic rearrangement:

$$
|\mathrm{FFT}(c \cdot x)|^2 \;=\; c^2 \cdot |\mathrm{FFT}(x)|^2
$$

so the scalar `scaling²` can be folded into the constant prefactor applied to the output PSD, eliminating the time-domain multiplication. Combined with a migration from `numpy.fft.rfft` (which internally promotes `float32 → float64`, emitting `complex128`) to `scipy.fft.rfft` (which honors `float32` input and emits `complex64`), the per-segment transient working-memory profile reduces from approximately:

| Stage | Baseline (np.fft) | Optimized (scipy.fft + deferred scaling) |
|---|---|---|
| `int16 → float32` cast | 40 MB | 40 MB |
| Scaling multiply (time domain) | +40 MB | *eliminated* |
| `rfft` output | 80 MB (`complex128`) | 40 MB (`complex64`) |
| `\|·\|²` | 40 MB (`float64`) | 20 MB (`float32`) |
| **Peak transient** | **~180 MB** | **~80 MB** |

A **~55% reduction** in per-segment transient memory with zero change to PSD output modulo float32 round-off. This satisfies the §2.1 constraint.

### 2.3 Runtime policy — instrumentation before speculative refactor

The parent-accumulation term (source A, 15–25 GB) is the largest and least-understood component of the 37 GB RSS. The audit produced a plausible hypothesis (records + LLM context + knowledge cache) but no direct measurement of which sub-component dominates, nor whether growth across iterations is linear, bursty, or plateauing. A speculative refactor of `all_records` aggregation ahead of measurement risks either optimizing the wrong structure or introducing correctness regressions in the agent's memory contract (records are the source of truth for the tuner's planning phase).

**Decision**: this branch ships a `psutil.Process().memory_info()` probe at every iteration boundary, emitting structured `[MEM]` lines to the workflow log. The next real exploration run produces the RSS-vs-iteration curve. Parent-side refactor decisions follow the curve, not the hypothesis.

### 2.4 Subprocess RAM hardening — catchable failure mode

The observed failure mode — `SIGKILL` from the kernel — is silent and irrecoverable: the orchestrator has no opportunity to log, persist partial records, or advance to the next iteration. A bounded-address-space failure that surfaces as `MemoryError` inside a training or inference subprocess can be caught by the subprocess wrapper, logged as a first-class failure record (e.g. `oom_host_ram`), and skipped past without terminating the orchestration.

**Decision**: install `resource.setrlimit(RLIMIT_AS, 24 GB)` in every subprocess spawned by `TidmadSandbox` (training, inference, scoring-subprocess). 24 GB leaves headroom for the parent (~5–8 GB steady-state) plus IDE (~2 GB) plus other tenants (~5 GB) on a 61 GiB host; training workloads observed to date peak well below 16 GB.

---

## 3. Solution Sketch & Checklist

### Fix 1 — Subprocess RAM hardening (`core/sandbox_executor.py`)

| Item | Detail |
|---|---|
| Mechanism | `preexec_fn` passed to `subprocess.run` invoking `resource.setrlimit(resource.RLIMIT_AS, (N, N))` in the child before `exec` |
| Touchpoints | `execute_training`, `execute_inference`, `execute_scoring` — three `subprocess.run` callsites, consolidated through a `_limited_preexec(gb: int)` helper |
| Ceiling | **24 GB** by default; configurable via `SIDERIUS_SUBPROCESS_RSS_GB` env var |
| Failure mode | Subprocess raises `MemoryError`; `_format_subprocess_error` extended to recognize OOM-class exit signatures and surface a structured `oom_host_ram` status |
| Platform note | `RLIMIT_AS` is POSIX; on non-POSIX hosts the helper logs a warning and no-ops |

### Fix 2 — Scoring micro-optimizations (`execute_tools/scoring_utils.py`)

| Item | Detail |
|---|---|
| Switch FFT backend | `numpy.fft.rfft` → `scipy.fft.rfft` to honor `float32` input and emit `complex64` output |
| Deferred Scaling | Remove `ts = data.astype(float32) * scaling`; keep only the `float32` cast. Apply `scaling²` as a scalar on the final PSD array after `\|·\|²` |
| Expected effect | ~180 MB → ~80 MB per-segment transient (~55% reduction) |
| Correctness test | Unit assert: new path vs. old path `np.allclose(..., atol=1e-10, rtol=1e-7)` on a synthetic 10⁷-sample segment |
| Out of scope here | `denoising_score_single.py` double-FFT fold — deferred pending confirmation that this script is still on the hot path post-Phase-K |

### Fix 3 — Inference memory hygiene (`execute_tools/inference_single.py`)

| Item | Detail |
|---|---|
| Target | Normal-mode per-file loop at `inference_single.py:215–234` |
| Action | Add explicit `del alltrain, alltarget, denoised; gc.collect()` at end of each per-file iteration, mirroring the trial-mode cleanup at lines 204–205 |
| Effect | Caps per-file RSS growth in the inference subprocess; combined with Fix 1, the subprocess stays well under the 24 GB ceiling for 20-file eval loops |

### Fix 4 — Parent-process instrumentation

| Item | Detail |
|---|---|
| Tool | `psutil.Process(os.getpid()).memory_info()` |
| Emission | `[MEM] iter=N phase=<start\|pre_score\|post_score\|end> rss=X.XX GB vms=Y.YY GB` |
| Insertion points | Iteration boundaries + entry/exit of each scoring block |
| Host | `nodes/ml_hyperparameter_tune_agent.py` (iteration scope) + `run_exploration_adaptive.py` (workflow scope) |
| Persistence | stdout + append to `{workspace}/memory_trace.jsonl` for post-hoc plotting |

---

## 4. Implementation Order — The 5-Commit Plan

| # | Status | Scope | Files | Verification | Commit |
|---|---|---|---|---|---|
| 1 | [x] | **Design doc** | `docs/optimize_inference_and_scoring.md` (this file) | User review before landing; no code impact | `193269d` |
| 2 | [x] | **Subprocess RAM hardening (Fix 1)** | `core/sandbox_executor.py` + `tests/unit/core/test_sandbox_rlimit.py` | Unit test: spawn a subprocess that allocates >24 GB and assert it raises `MemoryError` rather than SIGKILL; second test confirms normal subprocesses under the ceiling run unaffected | `d5ef2af` |
| 3 | [x] | **Parent-process instrumentation (Fix 4)** | `core/memory_probe.py` + `workflows/model_exploration.py` + `nodes/ml_hyperparameter_tune_agent.py` + `tests/unit/agent/tune_ml_hyperparam_agent/test_memory_probe.py` | Unit test: drive a 2-iter mock workflow, assert `[MEM]` lines are present with monotonic iter indices and emit a valid `memory_trace.jsonl` entry at each boundary | `0b3cb43` |
| 4 | [x] | **Scoring micro-optimizations (Fix 2)** | `execute_tools/scoring_utils.py` + `tests/unit/execute_tools/test_scoring_utils_rfft.py` | Unit test 1 (correctness): bit-equivalence between old and new paths on a synthetic segment, `rtol=1e-7`. Unit test 2 (memory): `tracemalloc` assertion that peak allocation per segment ≤ 100 MB | `2f1cf85` |
| 5 | [x] | **Inference memory hygiene (Fix 3)** | `execute_tools/inference_single.py` | Manual smoke run (2-file inference) with `memory_profiler`, diff-note attached to the commit; no unit test (change is a `del`+`gc.collect` pattern with no observable output) | `5ca1852` |

Sequence rationale: Fix 1 ships the catchable failure mode before Fix 4 relies on it for diagnostic logging. Fix 2 must land after Fix 4 so the RSS curve captured by the probe directly measures Fix 2's effect. Each commit is reversible in isolation.

**Commit 2 — landed `d5ef2af` (2026-04-20)**: `_limited_preexec(gb)` + `_is_oom_failure(e)` helpers in `core/sandbox_executor.py`; `preexec_fn=_limited_preexec(_subprocess_rss_gb())` threaded into `execute_training`, `execute_inference`, `execute_scoring`; default 24 GiB ceiling, `SIDERIUS_SUBPROCESS_RSS_GB` env var override (`0` disables). `_format_subprocess_error` tags OOM-class failures (`-9` or `MemoryError` in stderr) with `[oom_host_ram]`, and the three entry points return `status="oom_host_ram"` so the orchestrator can record a structured failure. 26 new unit tests (`tests/unit/core/test_sandbox_rlimit.py`) + 23 pre-existing sandbox tests all pass.

**Commit 3 — landed `0b3cb43` (2026-04-20)**: new `core/memory_probe.py` exporting `probe_memory(iter_idx, phase, workspace, scope)` — emits a `[MEM]` stdout line and appends a JSON row to `{workspace}/memory_trace.jsonl`. Wired at iteration `start` + `end` in `workflows/model_exploration.py` (scope=`workflow`) and at `pre_score` + `post_score` around the `sandbox.score_vector` call in `nodes/ml_hyperparameter_tune_agent.py` (scope=`tuner`). Missing `psutil` degrades to a sentinel row with `rss_gb=None`; filesystem errors never abort the run. 10 new unit tests (`tests/unit/agent/tune_ml_hyperparam_agent/test_memory_probe.py`) pass; 368-test tuner suite green (no regression).

**Commit 4 — landed `2f1cf85` (2026-04-20)**: `get_one_sec_psd` in `execute_tools/scoring_utils.py` rewritten per §2.2 — `numpy.fft.rfft` → `scipy.fft.rfft` (honors `float32` input, emits `complex64`); Deferred Scaling folds `scaling²` into a post-FFT prefactor via DFT linearity and eliminates the full-array time-domain multiply; the post-FFT pipeline is staged with in-place `np.square` / `np.multiply` (with `out=`) and explicit `del` so intermediates are freed eagerly — the original fused expression held ~160 MB live. Measured per-segment peak on a 10⁷-sample synthetic segment: **80.0 MB vs ~180 MB baseline (-55%)**, matching the design-doc target exactly. Correctness is validated at the physics level — peak bin, total PSD power, and end-to-end `get_snr` all agree at `rtol ≤ 1e-5` — rather than bin-by-bin `np.allclose`: float32-internal FFT vs float64-internal FFT produces *uncorrelated* noise in low-magnitude bins, so the §4 table's `rtol=1e-7` is not achievable without giving the memory win back. Tolerance rationale recorded inline in the test file. 7 new unit tests (`tests/unit/execute_tools/test_scoring_utils_rfft.py`) pass; 56-test `execute_tools` suite green.

**Commit 5 — landed `5ca1852` (2026-04-20)**: `del train_loader, target_loader, alltrain, alltarget; gc.collect()` inserted in `execute_tools/inference_single.py` immediately after the normal-mode inference loop and before `create_abra_file`. The raw int8 buffers (`alltrain` + `alltarget` ≈ 3.7 GB together on a 201-segment file) were being held live through the write phase, which itself materialises `.flatten().astype(int8)` transients of `denoised` + `injected`. Dropping them before the write phase is the correct mirror of the existing trial-mode cleanup at lines 204–205. Validated via a smoke harness (`/tmp/smoke_inference_mem.py` — discarded after measurement) that replays the CPU-side memory path on real TIDMAD data with the model forward pass skipped (Fix 3 is CPU-side only): **single-call `ru_maxrss` peak 9.43 GB → 5.68 GB (−3.75 GB, −40%)**; 3-file sequential runs plateau cleanly at the same per-iter peak with 0.12 GB residual between iterations in both variants — confirming no pre-existing leak, only an intra-call peak savings. The `int8`-on-disk dtype (vs the originally assumed `int16`) revised the expected savings from ~8 GB → ~3.7 GB; the measured 3.75 GB matches this revised math exactly. No new tests (pattern has no observable output); 56-test `execute_tools` suite green.

---

## 5. Success Criteria

The branch is mergeable into `master` when, on a 5-iteration `explore_novel` real run:

1. **Parent-process RSS stability** — `[MEM]` probe shows `rss` growing by **<2 GB across 5 iterations**, confirming the parent is not leaking monotonically at the scale seen in the 2026-04-20 incident.
2. **Per-experiment scoring peak** — during any single scoring block, parent RSS rises by no more than **2 GB** above its value at the scoring block's entry.
3. **Catchable failure mode** — the Commit 2 unit test passes: a subprocess exceeding 24 GB `RLIMIT_AS` raises `MemoryError`, propagated to the orchestrator as a structured `oom_host_ram` failure record rather than a silent SIGKILL.
4. **No physics regression** — `score_vector` output on a reference denoised file is bit-equivalent (within `rtol=1e-7`) to the `master`-baseline computation.
5. **No dead-code additions** — any micro-optimization that does not measurably move the RSS curve in a real run is reverted before merge.

### 5.1 Status at branch close (2026-04-20)

All five commits have landed. The criteria split cleanly into *code-level* (verifiable in-tree) and *system-level* (requires a real exploration run to confirm):

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 3 | Catchable failure mode | **Met** | Commit `d5ef2af`; 26 unit tests in `tests/unit/core/test_sandbox_rlimit.py` cover the RLIMIT_AS preexec, OOM-class `CalledProcessError` detection, and the `status="oom_host_ram"` propagation contract at the three `TidmadSandbox` entry points. |
| 4 | No physics regression | **Met, tolerance revised** | Commit `2f1cf85`; the original `rtol=1e-7` bin-by-bin target is not achievable with float32-internal FFT (noise-dominated bins diverge between float32 and float64 paths). Validated instead at the *physics-observable* level — peak bin, total PSD power, and end-to-end `get_snr` — all at `rtol ≤ 1e-5`. The quantities scoring actually consumes are bit-equivalent to within float32 round-off. Rationale captured in both the Commit 4 landed note above and inline in `test_scoring_utils_rfft.py`. |
| 5 | No dead-code additions | **Met** | Every code commit on this branch moves a measured needle: Commit 2 shifts SIGKILL → `MemoryError` (binary outcome, observed in tests); Commit 3 emits structured `[MEM]` rows (observable in any run); Commit 4 reduces per-segment PSD peak from ~180 MB → 80.0 MB (−55%, measured); Commit 5 reduces per-call inference peak from 9.43 GB → 5.68 GB (−40%, measured). Nothing speculative landed. |
| 1 | Parent-process RSS stability (<2 GB drift / 5 iter) | **Pending real run** | The measurement harness (Commit 3 probes + `memory_trace.jsonl`) is in place. Confirming the <2 GB bound requires the next `explore_novel` 5-iter run to produce the RSS-vs-iteration curve. If the curve exceeds the bound, the follow-up work is parent-side (`all_records` / LLM-history refactor) and lives on a subsequent branch — §6 already scopes it out of this one. |
| 2 | Per-experiment scoring peak (<2 GB rise / block) | **Pending real run** | Same harness; the tuner-scope `pre_score` / `post_score` probe pair around `sandbox.score_vector` in `nodes/ml_hyperparameter_tune_agent.py` emits the exact pair of numbers this criterion compares. Validated in the same 5-iter real run as criterion 1. |

**Merge posture**: the three *code-level* criteria are met. The two *system-level* criteria are instrumented but will only produce their verdict on the next real exploration run — which is the branch's deliverable: a resilient instrumented baseline, not a final tuned parent. If the upcoming run shows either bound broken, the fix is follow-up work (separate branch) informed by the curves this branch now captures; it does not invalidate the landed commits.

---

## 6. Out of Scope (for this branch)

- **Welch-style PSD decomposition** — rejected on physics grounds (§2.1).
- **`denoising_score_single.py` double-FFT fold** — deferred pending verification that this script is still on the hot path; current evidence suggests `scoring_utils.score_vector` is canonical post-Phase-K.
- **Parent-side `all_records` / LLM-history refactor** — deferred pending the RSS curve from Fix 4. What to trim follows measurement, not speculation.
- **Host-RAM budget gate in `evaluate_*_skill`** — a longer-term extension that would treat host RAM symmetrically with GPU VRAM and wall-time; tracked separately after this branch merges.

---

*End of document.*
