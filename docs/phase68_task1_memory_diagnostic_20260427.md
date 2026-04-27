# Phase 6.8 — Task 1: Memory Hygiene (Diagnostic + Implementation Plan)

**Date**: 2026-04-27
**Status**: Implementation in progress. Diagnostic content ratified by user; Task 2 (resume) is deferred until Task 1 lands and verifies.
**Driver**: v5 sanity-run host-OOM kill of `explore_novel_v5_0426` (PID 4142820) at 2026-04-27 00:46:42 PDT — kernel reaped at `total-vm:42931108kB, anon-rss:23492968kB` while the agent self-reported `rss=8.11 GB`.

---

## 0. Implementation log

| # | Commit | SHA | Status | Verified by |
|---|---|---|---|---|
| 0 | `docs(phase68): task 1 implementation plan + audit reports` | `4905b35` | LANDED | doc-only |
| 1 | `fix(scoring): switch ProcessPoolExecutor to spawn` | `f54d3c3` | LANDED | scoring_utils tests (13) + phase67_scoring_precision (23) + spawn-ctx import sanity |
| 2 | `feat(memory_probe): formalize post_gc phase` | `a1e2faf` | LANDED | memory_probe tests 12 passed (was 10, +2 new under TestPostGcPhase) |
| 3 | `fix(workflow): per-iter del + gc.collect with post_gc probe` | _pending_ | STAGED, awaiting approval | tests/unit/workflows/ 91 passed; module imports clean |
| 4 | `fix(tuner): per-round del + gc.collect` | _pending_ | NOT STARTED | — |
| 5 | 1-iteration exploit smoke run (verification §3) | n/a | NOT STARTED | — |

**Branch**: `feat/dashboard-iteration-panel`. Doc commits + Commits 1 and 2 land on top of the prior Phase 6.7 work.

**Doc-sync rule** (per user direction 2026-04-27): every commit in this plan updates this doc's checklists and Implementation log in lock-step. No commit lands without its row above marked LANDED with the actual SHA.

---

## 1. Diagnostic recap (ratified)

The host-OOM has **two causes that compound**:

| Phenomenon | Magnitude | Root cause | Fix layer |
|---|---|---|---|
| **A — per-iter steady-state leak** | ~1–3 GB / iter | Orchestrator never `del`s per-iter agent instances; `gc.collect()` is never called; LLM-client connection pools / plugin module refs / sandbox handles linger | **B** (workflow) |
| **B — per-round leak inside tuner** | ~0.2–1 GB / round | Round body keeps train/score/score_table objects bound across rounds because Python locals persist | **C** (tuner) |
| **C — +15 GB transient inside one `score_vector` call** (the killer) | one-shot fork-amplification | `execute_tools/scoring_utils.py:471` ProcessPoolExecutor with no `mp_context` defaults to `fork` on Linux → 8 workers COW-amplify the parent's pages | **A** (scoring) |

**Single highest-impact fix**: Layer A (`mp_context="spawn"` in scoring). It is the change that would have prevented the v5 kill outright.

**Independent secondary fixes**: Layers B + C cap the steady-state growth that primed the parent for fork-amplification in the first place. Even with Layer A, an unbounded steady-state leak eventually wins.

Full reasoning, measurements, and confirming-evidence numbers: see `reports/phase68_task1_memory_diagnostic_20260427.md` §1–§4. This doc focuses on **what to change and how to measure that the change worked**.

---

## 2. Step-by-step commit plan

Four commits. Each is independent of the others — order matters only for verification (Commit 1 fixes the killer; Commits 2–4 cap the leak that primes it).

### Commit 1 — `fix(scoring): switch ProcessPoolExecutor to spawn`

**Site**: `execute_tools/scoring_utils.py:470–475` (the only `ProcessPoolExecutor` in the scoring path).

**Change**:

```python
# Before
with concurrent.futures.ProcessPoolExecutor(
    max_workers=min(num_workers, len(tasks))
) as executor:

# After
import multiprocessing as mp  # at module top
with concurrent.futures.ProcessPoolExecutor(
    max_workers=min(num_workers, len(tasks)),
    mp_context=mp.get_context("spawn"),
) as executor:
```

**Why this is safe**: `_collect_raw_pairs` is module-level (picklable). Workers re-import torch/numpy/h5py from a clean state — no closure-pickling concerns. Per-call wall regression: 1–2 s of worker warmup vs 10–60 s scoring wall (< 5%).

**Checklist** (LANDED `f54d3c3`):

- [x] `mp` import present at function-local scope of `score_vector` in `execute_tools/scoring_utils.py` (alongside the existing function-local `concurrent.futures` import — kept local for diff symmetry).
- [x] `mp_context=mp.get_context("spawn")` argument visible in the `ProcessPoolExecutor` ctor at line ~480.
- [x] No other `ProcessPoolExecutor` in `execute_tools/scoring_utils.py`. Out-of-scope for this commit but flagged: `execute_tools/build_anchor_map.py:94` and `compute_raw_baseline.py:104` also use the default fork start method; neither is in the OOM hot path.
- [x] `tests/unit/execute_tools/test_scoring_utils.py` — 13 passed; `tests/unit/execute_tools/test_phase67_scoring_precision.py` — 23 passed.
- [x] Spawn-ctx import sanity: `python -c "import multiprocessing as mp; ...; print(mp.get_context('spawn').get_start_method())"` → `spawn`.
- [ ] Smoke test (deferred to Verification §3 below) confirms scoring runtime regression < 10 % on a real call.

### Commit 2 — `feat(memory_probe): formalize post_gc phase`

**Site**: `core/memory_probe.py` (docstring) + a unit-test fixture.

**Why a separate commit**: `phase` is already a free-form `str` (docstring at lines 75–78 says "schema is open"), so the runtime accepts `phase="post_gc"` today without code change. This commit makes the new phase **discoverable** (canonical-values list in docstring) and **regression-locked** (a unit test asserts the JSONL row reflects it).

**Changes**:

1. Update the canonical-values docstring (`core/memory_probe.py:75–78`) to mention `post_gc` alongside `start`/`end`/`pre_score`/`post_score`.
2. Add a unit test under `tests/unit/core/` (or extend an existing memory-probe test) asserting `probe_memory(iter_idx=1, phase="post_gc", workspace=tmp, scope="workflow")` writes a row with `phase=="post_gc"`.

**Checklist** (LANDED `a1e2faf`):

- [x] Docstring of `core.memory_probe.probe_memory` lists `post_gc` as a canonical workflow-scope phase, with the freed-memory delta formula (`end.rss_gb - post_gc.rss_gb`) called out explicitly.
- [x] New unit-test class `TestPostGcPhase` in `tests/unit/agent/tune_ml_hyperparam_agent/test_memory_probe.py` covers (a) `phase="post_gc"` round-trip via JSONL, (b) the production `end` → `post_gc` ordering pair.
- [x] Full memory-probe suite: 12 passed (was 10, +2 new). No regressions.

### Commit 3 — `fix(workflow): per-iter del + gc.collect with post_gc probe`

**Site**: `workflows/model_exploration.py`, immediately after the existing `probe_memory(phase="end", ...)` call at line 948 and before the early-stop `if target_score is not None ...` check.

**Change** (as applied in working tree):

```python
        probe_memory(iter_idx=iteration, phase="end",
                     workspace=workspace, scope="workflow")

        # Phase 6.8 §2 Layer B (Commit 3) — per-iteration cleanup. Drop
        # local refs to per-iter agent outputs, force a GC cycle, then
        # emit a post_gc probe so the trace consumer can read the
        # freed-memory delta as ``end.rss_gb - post_gc.rss_gb``.
        # tune_output is also retained in iteration_results /
        # recent_tune_outputs (live refs); the local del here just
        # decrements the local-name refcount. NameError-guarded
        # because early-exit paths may leave some names unbound.
        # See docs/phase68_task1_memory_diagnostic_20260427.md §2 Commit 3.
        try: del proposal
        except NameError: pass
        try: del impl_output
        except NameError: pass
        try: del validation
        except NameError: pass
        try: del interpretation
        except NameError: pass
        try: del interp_input
        except NameError: pass
        try: del tune_input
        except NameError: pass
        try: del tune_output
        except NameError: pass
        gc.collect()
        probe_memory(iter_idx=iteration, phase="post_gc",
                     workspace=workspace, scope="workflow")
```

`import gc` is added at the top of `workflows/model_exploration.py` (alongside `os`, `sys`, `json`, …) so the call site stays clean.

**Why this works**: Python's GC reclaims unreferenced cycles only when generational thresholds fire. With long-lived `iteration_results` retaining a reference to each iter's `tune_output`, the cycle detector might not fire often enough on the 1–2 GB / iter scale we're seeing. Explicit `gc.collect()` forces the issue. The new `phase="post_gc"` row in the trace gives us a measurable regression test — diff `end` vs `post_gc` to see how much was actually freed.

**Why try/except del rather than a clean dict-style cleanup**: `locals()` returns a snapshot dict in CPython; mutating it does not affect the frame's actual local namespace. The only way to release a local-by-name is a top-level `del` statement. Names may be unbound on early-exit paths (e.g. proposer fails on attempt 1 → `validation` was never assigned), so each `del` is wrapped.

**Checklist** (STAGED, awaiting approval):

- [x] `import gc` added at module top of `workflows/model_exploration.py`.
- [x] All seven `try: del <name>` blocks land in order, between the `phase="end"` probe and the `target_score` check.
- [x] New `probe_memory(phase="post_gc", ...)` call lands immediately after `gc.collect()`.
- [x] Existing workflow unit tests pass: `pytest tests/unit/workflows/ -q` → 91 passed.
- [x] Module imports clean: `python -c "from workflows.model_exploration import run_workflow; print('OK')"`.
- [ ] Smoke run (Verification §3) shows a `phase: "post_gc"` row whose `rss_gb ≤` the immediately preceding `phase: "end"` row.

### Commit 4 — `fix(tuner): per-round del + gc.collect`

**Site**: `nodes/ml_hyperparameter_tune_agent.py`, at the end of the outer `while` body, immediately after line 1787 (`if not round_succeeded` block) and before the `while` re-evaluates its condition.

**Change**:

```python
            if not round_succeeded:
                consecutive_fails += 1
                print(
                    f"Round {round_index} exhausted all {N} attempt(s) "
                    f"without a successful experiment "
                    f"(consecutive_fail_rounds={consecutive_fails}/"
                    f"{max_fail_rounds_setting})."
                )

            # Phase 6.8 §2 Layer C — release per-round transients
            # before the next round's plan(). All names may be unbound
            # on early-exit paths (gate skip / training crash before
            # score), so guard each del with NameError.
            for _ in (None,):  # tiny scope to keep the import local
                import gc
                try: del train_results
                except NameError: pass
                try: del score_results
                except NameError: pass
                try: del score_table
                except NameError: pass
                try: del file_vector
                except NameError: pass
                try: del final_scalar
                except NameError: pass
                try: del reflect_results
                except NameError: pass
                try: del memory_history
                except NameError: pass
                gc.collect()
```

**Variables targeted**: the largest per-round transients identified in the diagnostic — `train_results` (training-loop output dict, can include loss histories), `score_results` (per-file scores + file_vector), `score_table` (rendered markdown table for next round's planner prompt — replaced fresh each round), `file_vector` and `final_scalar` (numpy arrays from scoring), `reflect_results` (concatenation of train+score for the LLM reflector), `memory_history` (whole-record summary returned by `sandbox.get_summary()` — re-fetched at top of next round).

**Why guard each del**: names defined inside the inner attempt `try` block at lines 1463–1613 may not bind if the attempt fails before reaching that line. The outer-while cleanup must tolerate that.

**Checklist**:

- [ ] `import gc` (or already at top).
- [ ] All seven `try: del <name>` blocks land in order, at the end of the outer while body.
- [ ] `gc.collect()` after the dels.
- [ ] Existing tuner unit tests pass: `pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q`.
- [ ] In a 1-iteration smoke run, the **per-round tuner-scope `pre_score` rows** are flat (each round's `pre_score` ≈ previous round's `post_score`, ± 0.1 GB) — i.e. inter-round growth has been capped.

---

## 3. Verification (after all four commits land)

Single 1-iteration exploit smoke (the cheapest run that exercises all four code paths). Goal: produce a `memory_trace.jsonl` we can read by eye.

**Command** (subject to user approval before launch):

```
SIDERIUS_RUN_NAME=phase68_smoke_$(date +%Y%m%d_%H%M%S) && \
.venv/bin/python run_exploration_adaptive.py \
    --mode exploit \
    --run_name "${SIDERIUS_RUN_NAME}" \
    --max_iterations 1 \
    --is_trial \
    --advice tuner_advice/exploit_cnn_v3.json \
    --llm_config llm_configs/openai_tiered_v1.json \
    2>&1 | tee /tmp/${SIDERIUS_RUN_NAME}.log
```

**Pass criteria**:

1. **JSONL contains a `post_gc` row**: `grep '"phase": "post_gc"' {workspace}/memory_trace.jsonl` returns at least one line.
2. **`post_gc.rss_gb ≤ end.rss_gb`** for the same iter (the cleanup released some memory, or at least did not grow).
3. **Tuner-scope `pre_score` rows are flat across rounds** (no monotonic per-round increase > 0.5 GB).
4. **No new failure modes**: workflow exits with status `completed`, all three rounds produce a record, no `_ArrayMemoryError` / `Killed` in the log.
5. **Scoring runtime regression < 10 %**: compare the v5 exploit's `pre_score`/`post_score` wall-clock delta to the smoke run's.

**Reporting back**: I'll show the exact `memory_trace.jsonl` contents (filtered to scope=workflow) so the `end` → `post_gc` deltas are explicit.

---

## 4. What this plan deliberately does NOT do

- **No mid-iter checkpoint** — Task 2 (resume) is deferred per user direction.
- **No agent re-use across iters** — keeping the per-iter `re-instantiate-agent` pattern (Layer D in the original diagnostic, parked).
- **No `MODEL_REGISTRY` pruning** — bounded, low priority.
- **No `h5py.get_config().fclose_degree = 'strong'`** — Layer D, parked.
- **No tests added beyond what each commit needs to lock in** (Layer A: scoring tests, Layer B: probe round-trip, Layer C: workflow tests pass, Layer D: tuner tests pass). The smoke run is the integration test.

---

## 5. Rollback plan

Each commit is small and independent:

- Commit 1 alone is safe to ship even if 3+4 fail review — it eliminates the killer.
- Commits 3 and 4 can be reverted independently if `gc.collect()` is shown to cause a measurable runtime regression (it shouldn't — `gc.collect()` on a 1–8 GB Python process takes < 200 ms).
- Commit 2 has no behavioural change; reverting only removes the docstring update and one test.

---

## 6. Out-of-band note

There is a still-running exploit sanity (PID 4142909, `exploit_cnn_v5_0426`) on iter_005 at the time of writing. The smoke run for verification will use a fresh `run_name` and a fresh workspace so it does not interfere. We will **not** signal or interrupt the live run.
