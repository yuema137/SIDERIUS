# Phase 6.8 — Task 1: Memory Snapshot Audit (Diagnostic Report)

**Date**: 2026-04-27
**Driver**: v5 sanity-run host-OOM kill of `explore_novel_v5_0426` (PID 4142820) at 2026-04-27 00:46:42 PDT.
**Kernel record**: `Out of memory: Killed process 4142820 (python) total-vm:42931108kB, anon-rss:23492968kB`.
**Self-report at the same moment**: `[MEM] scope=tuner iter=2 phase=pre_score rss=8.11 GB vms=22.79 GB` — i.e. **a 15 GB gap between what the agent thought it was using and what the kernel observed when it pulled the trigger**.
**Status**: Diagnostic only. No code changes in this report.

---

## TL;DR

The host-OOM was caused by **fork-amplification in the scoring subprocess pool**, not by a slow leak. The single line responsible is `execute_tools/scoring_utils.py:471` — a `concurrent.futures.ProcessPoolExecutor` with no explicit `mp_context`, which on Linux defaults to `fork` and copies-on-write the entire 8 GB parent into 8 workers.

There is also a **secondary steady-state leak** of ~1–3 GB / iteration in the orchestrator loop, driven by per-iter agent re-instantiation without explicit `del` / `gc.collect()`. This leak is what raised the parent's RSS from 0.55 GB → 8.11 GB in two iterations and primed the fork bomb.

The single highest-impact fix is **switching the scoring `ProcessPoolExecutor` to `spawn`**. Adding per-iter `del` + `gc.collect()` is the second fix and is independent of the first.

---

## 1. What we measured

Three independent data sources for the v5 runs:

1. **Workflow-scope RSS curve** — `{workspace}/memory_trace.jsonl`, written by `core.memory_probe.probe_memory(scope="workflow")` at start/end of each iter (`workflows/model_exploration.py:644, 948`).
2. **Tuner-scope RSS curve** — `{workspace}/{run_name}/iteration_NNN/{model}/memory_trace.jsonl`, written by the same probe at `pre_score` / `post_score` of each tuner round (`nodes/ml_hyperparameter_tune_agent.py:1455, 1480`).
3. **Kernel record at OOM** — `dmesg` line above.

### 1.1 Workflow trace — explore_novel_v5_0426 (DEAD)

| Iter | Phase | RSS (GB) | VMS (GB) | Wall |
|---|---|---|---|---|
| 1 | start | 0.55 | 17.85 | 21:49 PDT |
| 1 | end   | 3.65 | 22.08 | 00:40 PDT |
| 2 | start | 3.65 | 22.08 | 00:40 PDT |
| 2 | (killed mid-scoring) | **23.50** (kernel) | 41.0 (kernel) | 00:46 PDT |

### 1.2 Workflow trace — exploit_cnn_v5_0426 (ALIVE through iter_005 at time of report)

| Iter | start RSS | end RSS | Δ |
|---|---|---|---|
| 1 | 0.55 | 5.77 | **+5.22 GB** |
| 2 | 5.77 | 7.51 | +1.74 GB |
| 3 | 7.51 | 7.75 | +0.24 GB |
| 4 | 7.75 | 8.68 (mid-iter, post round 2) | +0.93 (partial) |

### 1.3 Tuner-scope (intra-iter, between rounds)

- Exploit iter_001: round 1 pre/post 5.06 / 5.06 → round 2 pre 5.23 → round 3 pre 5.76. **Pre→post per scoring is essentially flat**, but **inter-round growth is real** (~+0.2–0.5 GB / round).
- Explore iter_001: round 1 pre/post 1.51 / 1.52 → round 2 pre 2.56 → round 3 pre 3.64 / post 3.64. Same shape.
- Explore iter_002 round 1: `pre_score = 8.11 GB` (only present in stdout log — the JSON append never fired because the parent was killed). Kernel reaped at 23.5 GB anon-RSS. **+15 GB transient inside one scoring call.**

---

## 2. Three distinct phenomena

### Phenomenon A — steady-state per-iteration leak (~1–3 GB / iter)

The workflow trace shows monotonic RSS growth across iters with no return to baseline. The orchestrator never calls `gc.collect()` and never `del`s the per-iter agent instances. Each iter creates fresh `ResultInterpretationAgent`, `MLModelProposalAgent`, `MLModelImplementor`, `MLCodeValidatorAgent`, and `HyperparamTuningAgent` instances; the previous iter's instances become unreferenced by name but their LLM-client connection pools, prompt buffers, and plugin module references are not aggressively reclaimed.

### Phenomenon B — per-round leak inside the tuner (~0.2–1 GB / round)

Within a single `HyperparamTuningAgent.run()`, the round loop carries memory forward. Pre→post-score is flat — **the leak is in the round body, not in scoring itself**. Likely sources: training intermediates pinned by closures, score-table data structures retained for the next planner call, plugin modules loaded into `sys.modules`.

### Phenomenon C — catastrophic +15 GB transient inside `score_vector` (the actual killer)

Explore went from 8.11 GB pre_score to 23.5 GB at OOM-kill in a single scoring call. This is not a leak — it is a fork-amplification spike. Mechanism in §4.

---

## 3. Candidate accumulation sites in the parent process

Walked `workflows/model_exploration.py:run_workflow` and `nodes/ml_hyperparameter_tune_agent.py:HyperparamTuningAgent.run`.

### High-confidence, bounded growth (correctness concerns, not the leak source)

| Site | Lifetime | Per-iter cost | File:line |
|---|---|---|---|
| `iteration_results: list[HyperparamTuningOutput]` | full workflow | ~50–500 KB / iter | `workflows/model_exploration.py:615, 904` |
| `MODEL_REGISTRY` / `PLUGIN_CONFIG_REGISTRY` extensions | process lifetime | ~1–10 MB / plugin (Python module objects + closures) | `workflows/model_exploration.py:387–388` |
| `current_runtime_vocab` | full workflow | ~KB / discovery | `workflows/model_exploration.py:620, 929` |
| `all_model_types: list[str]` | full workflow | ~bytes / iter | `workflows/model_exploration.py:596, 911` |
| `recent_tune_outputs: deque(maxlen=3)` | bounded | bounded — already hard-capped | `workflows/model_exploration.py:628` |

Combined ≤ 10 MB / iter — does not explain a 3 GB / iter step.

### Medium-confidence, large unmanaged objects

| Site | What it holds | Why it might leak |
|---|---|---|
| `score_vector` parent-side state | `raw_pairs: dict[int, list[tuple[float, float]]]`, `tasks` list, ProcessPoolExecutor context | After the executor's `__exit__`, the **parent's pages that were copied-on-write may not be promptly returned to the kernel** by glibc malloc on Linux. See §4. |
| Per-iter agents (Interpretation, Proposal, Implementor, Validator, Tuner) | LLM client objects, prompt buffers, sandbox handles, plugin module references | Re-instantiated per iter (`workflows/model_exploration.py:666, 752, 798, 815, 903`) — but parent doesn't `del` the previous iter's instances. The OpenAI / Gemini clients hold HTTP connection pools that pin descriptors. |
| `ReferenceScores` cached in tuner agent | 20 floats × ~6 numpy arrays per round | Loaded per round; small itself, but old tuner not freed → old reference held. |
| Validator subprocess output buffers | `subprocess.run(..., capture_output=True)` returns stringified stdout/stderr | If any layer holds the dict for "diagnostic logging" the strings leak. |
| `h5py.File` handle cache | HDF5 library global state in the parent | h5py keeps a file-id cache that persists across `with h5py.File(...)` contexts unless `h5.get_config().fclose_degree` is tuned. |

### Low-confidence (verified NOT the source)

- `LLMBridge` is **stateless** — verified by grep: no `self.history`, `self.messages`, `self.cache`, `self.responses`. Each call sends fresh `system_prompt + user_prompt`.
- `recent_tune_outputs` — bounded by `deque(maxlen=3)`.
- `model_knowledge_cache`, `latest_new_summary`, `previous_proposal_data` — **replaced** each iter (lines 919, 923, 927), not appended. The OLD value becomes unreferenced and is eligible for GC.
- `hardware_ctx` — single object, fine.

---

## 4. The +15 GB scoring spike — root cause

The smoking gun lives in `execute_tools/scoring_utils.py:470–475`:

```python
if parallel and len(tasks) > 1:
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=min(num_workers, len(tasks))
    ) as executor:
        for fi, pairs in executor.map(_collect_raw_pairs, tasks):
            raw_pairs[fi] = pairs
```

No `mp_context=` argument → on Linux, the default start method is **`fork`**. Each of the 8 worker processes is `os.fork()`-ed from the parent at its current RSS.

**With a small parent**, fork is cheap thanks to copy-on-write — children share read-only pages with the parent. **With a large parent (8 GB at scoring start)**, two effects compound:

1. **VMS amplification** — each child immediately reserves the parent's address space. 8 children × 26 GB VMS ≈ 200 GB virtual. Linux overcommit usually allows this, but it surfaces in monitoring as enormous VMS.
2. **RSS amplification via COW page-touching** — Python's reference-counting touches the refcount header on essentially every Python object the worker uses (pickling tasks, imports, deserializing args). Each touched page becomes a private copy in the child. With CPython 3.12 + numpy + h5py all imported in the parent, the worker can private-copy 1–3 GB very quickly. **8 workers × ~2 GB private copies ≈ 16 GB transient resident memory**.

The kernel OOM-killer fired against PID 4142820 (the parent) because the cgroup's combined RSS exceeded the host limit — and the parent had the largest individual RSS in the cgroup, so it was the natural target.

**Why it didn't kill exploit**: exploit's parent at scoring time was 5–8 GB at most. The fork-amplification transient was correspondingly smaller, and the host had enough headroom to absorb it. Explore's iter_002 entry RSS was already 8.11 GB — the same fork pattern that exploit survives at 5 GB, explore could not survive at 8 GB.

### Confirming evidence

- `total-vm:42931108kB` (≈ 41 GB) in dmesg matches the 8 workers × ~5 GB VMS pattern.
- `anon-rss:23492968kB` (≈ 23.5 GB) is roughly 3× the 8.11 GB self-report — consistent with the parent + a couple of workers' COW-private pages co-resident at the moment of the kill.
- Exploit's pre/post deltas are ~0.0 GB — meaning a full scoring cycle leaves no permanent residue. The spike is purely transient. The leak is elsewhere.

---

## 5. Proposed `del` and `gc.collect()` strategy

Four layers, ordered by impact / smallest-diff. **Layer A is the single change that would have prevented the host-OOM; everything else is steady-state hygiene.**

### Layer A — `score_vector` start-method fix (highest impact, smallest diff)

In `execute_tools/scoring_utils.py:470–475`, add `mp_context=multiprocessing.get_context("spawn")`:

```python
import multiprocessing as mp
with concurrent.futures.ProcessPoolExecutor(
    max_workers=min(num_workers, len(tasks)),
    mp_context=mp.get_context("spawn"),
) as executor:
    ...
```

- **Effect**: workers start clean (re-import only what they need); no COW amplification of the parent.
- **Cost**: each worker pays ~200–400 MB to import torch / numpy / h5py once. 8 workers × 300 MB ≈ 2.4 GB steady-state during scoring, **flat regardless of parent size**.
- **Risk**: spawn-mode cannot pickle closures defined in `__main__`; `_collect_raw_pairs` is module-level so it's safe. Worker startup is ~1–2s slower per scoring call — negligible vs the per-call wall (10s–60s).

### Layer B — per-iteration cleanup in the workflow loop

In `workflows/model_exploration.py:run_workflow`, immediately after the `probe_memory(phase="end")` call (line 948) and before the `target_score` early-stop check:

```python
# Free per-iter state before next iteration
del proposal, impl_output, validation
del interpretation, interp_input
del tune_input, tune_output  # tune_output already appended to iteration_results
import gc
gc.collect()
probe_memory(iter_idx=iteration, phase="post_gc",
             workspace=workspace, scope="workflow")
```

- **Why this works**: Python's GC reclaims unreferenced cycles only when generational thresholds fire. With long-lived `iteration_results` retaining a reference to each iter's `tune_output`, the cycle detector might not run often enough on the 1–2 GB / iter scale we're seeing. Explicit `gc.collect()` forces the issue. The new `phase="post_gc"` row in the trace gives us a measurable test for whether the strategy is working — diff `end` vs `post_gc` to see how much was actually freed.
- **Risk**: if a downstream node holds a reference to `tune_output` that we've also `del`-ed locally, nothing breaks — Python refcounts handle it. The `del` on the local name just decrements the refcount; the live reference (in `iteration_results`) keeps the object alive.

### Layer C — per-round cleanup in the tuner agent

In `nodes/ml_hyperparameter_tune_agent.py`, after the tuner finishes a round (after `sandbox.save_record(record)`) and before the next round starts:

```python
# Free per-round transients before the next plan() call
del train_results, score_results, score_table, file_vector
import gc
gc.collect()
```

Addresses Phenomenon B (per-round leak). Lower priority than A and B above.

### Layer D — long-term hygiene (lower priority)

- Re-instantiated agents per iter — consider re-using a single agent instance across iters where the schema allows, to avoid re-creating LLM client connection pools and prompt buffers.
- `MODEL_REGISTRY` / `PLUGIN_CONFIG_REGISTRY` — bounded growth (one entry per completed iter), but module objects can be ~10 MB each. After 20 iters that's 200 MB. Consider unloading old plugin modules from `sys.modules` once their iter is no longer the active one.
- `h5py` global file-id cache — set `h5py.get_config().fclose_degree = 'strong'` at module import in the parent to ensure file handles close cleanly when their last user goes out of scope.

---

## 6. Verification plan

After implementing Layer A + Layer B:

1. Re-run a 3-iteration exploit smoke (file_index=6, formal_time_budget=60min) on the same workload that produced the v5 traces.
2. Diff workflow-scope `memory_trace.jsonl`:
   - Pre-fix expected: 0.55 → 5.77 → 7.51 → 7.75 GB (v5 baseline)
   - Post-fix target: ≤ 3 GB at end of iter_3 (i.e. ≤ +1 GB / iter, +0.5 GB ideal)
3. Diff tuner-scope `pre_score` peaks across rounds — should be flat.
4. **Smoke-test the spawn switch**: confirm scoring runtime regression is < 10% (one extra worker-warmup cost per scoring call).
5. No new failure mode: validate that the seven Phase 6.7 unit tests under `tests/unit/agent/tune_ml_hyperparam_agent/` still pass with the spawn start method.

---

## 7. Provisional commit plan (Part 1 only)

| # | Commit | Layer | Effect |
|---|---|---|---|
| 1 | `fix(scoring): switch ProcessPoolExecutor to spawn` | §5 Layer A | Eliminates fork-amplification — would have prevented the v5 host-OOM |
| 2 | `feat(memory_probe): add post_gc phase` | §5 Layer B prep | Adds the diagnostic surface for measuring leak fixes |
| 3 | `fix(workflow): per-iter del + gc.collect with post_gc probe` | §5 Layer B | Caps per-iter steady-state leak |
| 4 | `fix(tuner): per-round del + gc.collect` | §5 Layer C | Caps per-round steady-state leak |

Commits 1–4 are independent of the resume work in Task 2 and can land first.
