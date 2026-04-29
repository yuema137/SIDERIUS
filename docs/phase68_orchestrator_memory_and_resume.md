# Phase 6.8 — Orchestrator Memory Hygiene & Run Resume

**Status**: Task 1 (memory hygiene) shipped in PR #63. Task 2 (resume) pivoted on 2026-04-27 to a chain-first design — see Part 3. v6 post-mortem (2026-04-28) identified three additional failure modes — see Part 4. Commits 6 → 12 landed on `feat/phase68-task2-chain-resume` (Commit 11 split into atomic sub-commits 11.1–11.4 + doc-syncs; Commit 12 lands the chain-aware `inspect_run_state.py` with `--layout chain`, `--next-iter`, legacy guard, and 11 unit tests, verified live against the iter-1+iter-2 gate workspace). Next up: Commit 13 (unified `run_chain.sh` + `_chain_common.sh` widening, including the deferred shell-side `--data_dir` plumbing and the relocated three-way consistency tests).
**Driver**: v5 sanity-run host-OOM kill of `explore_novel_v5_0426` PID 4142820 at 2026-04-27 00:46:42 (kernel: 23.5 GB anon-RSS, total-vm 41.0 GB). v6 sanity-run host-OOM of `explore_novel_v6_0427` at 2026-04-28 01:54 (35.6 GB RSS — different root cause than v5, see Part 4 §4.1).
**Scope**: Two parallel work streams — (1) understand and stop the parent-process memory growth that produced the OOM; (2) make any run resumable from disk artifacts after `SIGKILL`. Extended by Part 4 to cover VRAM probe memory safety, time estimation accuracy, and LLM prompt size management.

> **Reading order**: Part 1 (memory hygiene, shipped) → Part 2 (in-process resume design, **superseded**) → Part 3 (chain-first pivot, **active plan**) → Part 4 (v6 countermeasures, **active plan**). Part 2 is preserved as design history; the active implementation plan with commit checklists is Parts 3 + 4.

---

## Part 1 — Memory Snapshot Audit (Diagnostic Report)

### 1.1 What we measured

Three independent data sources for the v5 runs:

1. **Workflow-scope RSS curve** — `{workspace}/memory_trace.jsonl`, written by `core.memory_probe.probe_memory(scope="workflow")` at start/end of each iter (`workflows/model_exploration.py:644, 948`).
2. **Tuner-scope RSS curve** — `{workspace}/{run_name}/iteration_NNN/{model}/memory_trace.jsonl`, written by the same probe at `pre_score`/`post_score` of each tuner round (`nodes/ml_hyperparameter_tune_agent.py:1455, 1480`).
3. **Kernel record at OOM** — `dmesg` line `Out of memory: Killed process 4142820 (python) total-vm:42931108kB, anon-rss:23492968kB`.

#### Workflow trace — explore_novel_v5_0426 (DEAD)

| Iter | Phase | RSS (GB) | VMS (GB) | Wall |
|---|---|---|---|---|
| 1 | start | 0.55 | 17.85 | 21:49 PDT |
| 1 | end   | 3.65 | 22.08 | 00:40 PDT |
| 2 | start | 3.65 | 22.08 | 00:40 PDT |
| 2 | (killed mid-scoring) | **23.50** (kernel) | 41.0 (kernel) | 00:46 PDT |

#### Workflow trace — exploit_cnn_v5_0426 (ALIVE through iter_004)

| Iter | start RSS | end RSS | Δ |
|---|---|---|---|
| 1 | 0.55 | 5.77 | **+5.22 GB** |
| 2 | 5.77 | 7.51 | +1.74 GB |
| 3 | 7.51 | 7.75 | +0.24 GB |
| 4 | 7.75 | 8.68 (mid-iter, post round 2) | +0.93 (partial) |

#### Tuner-scope (intra-iter, between rounds)

Exploit iter_001: round 1 pre/post 5.06 / 5.06 → round 2 pre 5.23 → round 3 pre 5.76. **Pre→post per scoring is essentially flat**, but **inter-round growth is real** (~+0.2–0.5 GB / round).

Explore iter_001: round 1 pre/post 1.51 / 1.52 → round 2 pre 2.56 → round 3 pre 3.64 / post 3.64. Same shape: scoring itself doesn't leak, but each round carries +1 GB into the next.

Explore iter_002 round 1: `pre_score = 8.11 GB` (from log line, no JSON row written — probe was killed before the disk append). The kernel reaped at 23.5 GB anon-RSS. **+15 GB transient inside one scoring call.**

### 1.2 Where the memory went — three distinct phenomena

#### Phenomenon A — steady-state per-iteration leak (~1–2 GB / iter on average; ~3 GB / iter on explore-iter-001)

The workflow trace shows monotonic RSS growth across iters with no per-iter return to baseline. This is the long-running parent process holding references to per-iteration objects. The orchestrator never calls `gc.collect()` and never `del`s the agents or their inputs.

#### Phenomenon B — per-round leak inside the tuner (~0.2–1 GB / round)

Within a single `HyperparamTuningAgent.run()`, the round loop carries memory forward. Pre→post-score is flat, so **the leak is in the round body, not in scoring itself**.

#### Phenomenon C — catastrophic +15 GB transient inside `score_vector` (the actual killer)

Explore went from 8.11 GB pre_score to 23.5 GB at OOM-kill. This is not a leak — it is a fork-amplification spike. Mechanism in §1.4 below.

### 1.3 Candidate accumulation sites in the parent process

Walked `workflows/model_exploration.py:run_workflow` and `nodes/ml_hyperparameter_tune_agent.py:HyperparamTuningAgent.run`. Sites ranked by likelihood and footprint:

#### High-confidence, bounded growth

| Site | Lifetime | Per-iter cost | File:line |
|---|---|---|---|
| `iteration_results: list[HyperparamTuningOutput]` | full workflow | ~50–500 KB / iter (depends on records-per-tuner) | `workflows/model_exploration.py:615, 904` |
| `MODEL_REGISTRY` / `PLUGIN_CONFIG_REGISTRY` extensions | process lifetime | ~1–10 MB / plugin (Python module objects + closures) | `workflows/model_exploration.py:387–388` |
| `current_runtime_vocab` | full workflow | ~KB / discovery | `workflows/model_exploration.py:620, 929` |
| `all_model_types: list[str]` | full workflow | ~bytes / iter | `workflows/model_exploration.py:596, 911` |
| `recent_tune_outputs: deque(maxlen=3)` | bounded | bounded — already hard-capped | `workflows/model_exploration.py:628` |

These are clearly accumulating but the magnitude (≤10 MB / iter combined) does not explain a 3 GB per-iter step. They are correctness concerns, not the leak source.

#### Medium-confidence, large unmanaged objects

| Site | What it holds | Why it might leak |
|---|---|---|
| `score_vector` parent-side state | `raw_pairs: dict[int, list[tuple[float, float]]]`, `tasks` list, ProcessPoolExecutor context | `concurrent.futures.ProcessPoolExecutor` workers are forked. After the executor's `__exit__`, the **parent's pages that were copied-on-write may not be promptly returned to the kernel** by glibc malloc on Linux. See §1.4. |
| Per-iter agents (`ResultInterpretationAgent`, `MLModelProposalAgent`, `MLModelImplementor`, `MLCodeValidatorAgent`, `HyperparamTuningAgent`) | LLM client objects, prompt buffers, sandbox handles, plugin module references | Re-instantiated per iter (`workflows/model_exploration.py:666, 752, 798, 815, 903`) — but parent doesn't `del` the previous iter's instances. The OpenAI/Gemini clients hold HTTP connection pools that pin descriptors. |
| `ReferenceScores` cached in tuner agent | 20 floats × ~6 numpy arrays per round | Loaded by `load_reference_scores` inside the tuner; small in itself, but each iter creates a fresh tuner that re-loads. Old tuner not freed → old reference held. |
| Validator subprocess output buffers | `subprocess.run(..., capture_output=True)` returns string-ified stdout/stderr | Returned in dicts that go through several layers; if any layer holds the dict for "diagnostic logging" the strings leak. |
| `h5py.File` handle cache | HDF5 library global state in the parent | h5py keeps a file-id cache that persists across `with h5py.File(...)` contexts unless `h5.get_config().fclose_degree` is tuned. Parent calls `h5py.File` in scoring (subprocess does too — that's separate). |

#### Low-confidence (verified not-the-source)

- `LLMBridge` is **stateless** — verified by grep: no `self.history`, `self.messages`, `self.cache`, `self.responses`. Each call sends fresh `system_prompt + user_prompt`; no conversation accumulation.
- `recent_tune_outputs` — bounded by `deque(maxlen=3)`.
- `model_knowledge_cache`, `latest_new_summary`, `previous_proposal_data` — **replaced** each iter (line 923, 919, 927), not appended. The OLD value becomes unreferenced and is eligible for GC.
- `hardware_ctx` — single object, fine.

### 1.4 The +15 GB scoring spike — root cause hypothesis

The smoking gun lives in `execute_tools/scoring_utils.py:471`:

```python
with concurrent.futures.ProcessPoolExecutor(
    max_workers=min(num_workers, len(tasks))
) as executor:
    for fi, pairs in executor.map(_collect_raw_pairs, tasks):
        raw_pairs[fi] = pairs
```

No `mp_context=` argument → on Linux, the default start method is **`fork`**. Each of the 8 worker processes is `os.fork()`-ed from the parent at its current RSS.

**With a small parent**, fork is cheap thanks to copy-on-write — children share read-only pages with the parent. **With a large parent (8 GB at scoring start)**, the cost is two compounding effects:

1. **VMS amplification** — each child immediately reserves the parent's address space. 8 children × 26 GB VMS ≈ 200 GB virtual. Linux overcommit usually allows this, but it surfaces in any monitoring system that flags VMS.
2. **RSS amplification via COW page-touching** — Python's reference-counting touches the refcount header on essentially every Python object the worker uses (pickling tasks, imports, deserializing args). Each touched page becomes a private copy in the child. With CPython 3.12 + numpy + h5py all imported in the parent, the worker can private-copy 1–3 GB very quickly. **8 workers × ~2 GB private copies = ~16 GB transient resident memory**.

The kernel OOM-killer fired against PID 4142820 (the parent) because the cgroup's combined RSS exceeded the host limit — and the parent had the largest individual RSS in the cgroup, so it was the natural target.

**Why it didn't kill exploit**: exploit's parent at scoring time was 5–8 GB at most. The fork-amplification transient was correspondingly smaller, and the host had enough headroom to absorb it. Explore's iter_002 entry RSS was already 8.11 GB — the same fork pattern that exploit survives at 5 GB, explore could not survive at 8 GB.

#### Confirming evidence

- `total-vm:42931108kB` (≈ 41 GB) in dmesg matches the 8 workers × ~5 GB VMS pattern exactly.
- `anon-rss:23492968kB` (≈ 23.5 GB) is roughly 3× the 8.11 GB self-report — consistent with the parent + a couple of workers' COW-private pages co-resident at the moment of the kill.
- Exploit's pre/post deltas are ~0.0 GB — meaning a full scoring cycle leaves no permanent residue. The spike is purely transient. The leak is elsewhere.

### 1.5 Proposed `del` and `gc.collect()` strategy

Proposing in two layers — bounded by what we should change and where.

#### Layer A — `score_vector` start-method fix (highest impact, smallest diff)

In `execute_tools/scoring_utils.py:470–474`, add `mp_context=multiprocessing.get_context("spawn")`:

```python
import multiprocessing as mp
with concurrent.futures.ProcessPoolExecutor(
    max_workers=min(num_workers, len(tasks)),
    mp_context=mp.get_context("spawn"),
) as executor:
    ...
```

**Effect**: workers start clean (re-import only what they need); no COW amplification of the parent.
**Cost**: each worker pays ~200–400 MB to import torch/numpy/h5py once. 8 workers × 300 MB = ~2.4 GB steady-state during scoring, **flat regardless of parent size**.
**Risk**: spawn-mode cannot pickle closures defined in `__main__`; `_collect_raw_pairs` is module-level so it's safe. Worker startup is ~1–2s slower per scoring call — negligible vs the per-call wall (10s–60s).
**Verdict**: this is the single change that would have prevented the host-OOM. Do it first.

#### Layer B — per-iteration cleanup in the workflow loop

In `workflows/model_exploration.py:run_workflow`, immediately after the `probe_memory(phase="end")` call (line 949) and before the `target_score` early-stop check:

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

**Why this works**: Python's GC reclaims unreferenced cycles only when generational thresholds fire. With long-lived `iteration_results` retaining a reference to each iter's `tune_output`, the cycle detector might not run often enough on the 1–2 GB / iter scale we're seeing. Explicit `gc.collect()` forces the issue. The new `phase="post_gc"` row in the trace gives us a measurable test for whether the strategy is working — diff `end` vs `post_gc` to see how much was actually freed.

**Risk**: if a downstream node holds a reference to `tune_output` that we've also `del`-ed locally, nothing breaks — Python refcounts handle it. The `del` on the local name just decrements the refcount; the live reference (in `iteration_results`) keeps the object alive.

#### Layer C — per-round cleanup in the tuner agent

In `nodes/ml_hyperparameter_tune_agent.py`, after the tuner finishes a round (after `sandbox.save_record(record)`) and before the next round starts:

```python
# Free per-round transients before the next plan() call
del train_results, score_results, score_table, file_vector
import gc
gc.collect()
```

This addresses Phenomenon B (per-round leak). Lower priority than A and B above — phenomenon B costs ~0.5 GB / round on explore, vs phenomenon C's +15 GB spike.

#### Layer D — long-term hygiene (lower priority)

- Re-instantiated agents per iter — consider re-using a single agent instance across iters where the schema allows, to avoid re-creating LLM client connection pools and prompt buffers.
- `MODEL_REGISTRY` / `PLUGIN_CONFIG_REGISTRY` — bounded growth (one entry per completed iter), but module objects can be ~10 MB each. After 20 iters that's 200 MB. Consider unloading old plugin modules from `sys.modules` once their iter is no longer the active one.
- `h5py` global file-id cache — set `h5py.get_config().fclose_degree = 'strong'` at module import in the parent to ensure file handles close cleanly when their last user goes out of scope.

### 1.6 Verification plan

After implementing Layer A + Layer B:

1. Re-run a 3-iteration exploit smoke (file_index=6, formal_time_budget=60min) on the same workload that produced the v5 traces.
2. Diff workflow-scope `memory_trace.jsonl`:
   - Pre-fix expected: 0.55 → 5.77 → 7.51 → 7.75 GB (v5 baseline)
   - Post-fix target: ≤ 3 GB at end of iter_3 (i.e. ≤ +1 GB / iter, +0.5 GB ideal)
3. Diff tuner-scope `pre_score` peaks across rounds — should be flat.
4. **Smoke-test the spawn switch**: confirm scoring runtime regression is < 10% (one extra worker-warmup cost per scoring call).
5. No new failure mode: validate that the seven Phase 6.7 unit tests under `tests/unit/agent/tune_ml_hyperparam_agent/` still pass with the spawn start method.

---

## Part 2 — Resume Technical Design (Breakpoint Continuity) — SUPERSEDED

> **This Part is superseded by Part 3.** It described a per-iteration resume mechanism for the **in-process** workflow loop (`run_exploration_adaptive.py`'s `for iteration in range(...)`). After the SDSC-chain evaluation
> (`reports/phase68_sdsc_chain_evaluation_20260427.md`), we adopted a **chain-first** runner — every iteration is a fresh OS process — for which resume becomes a much smaller change. The variable-by-variable rebuild in §2.5, the `_detect_resume_state` helper in §2.4, and the workflow-surface flag in §2.6 are no longer planned. The design is preserved here for context and for the day we need fine-grained mid-iter checkpointing.

### 2.1 Current State Audit — does resume work today?

**No.** `run_workflow()` always begins at `iteration=1` unconditionally (`workflows/model_exploration.py:633`):

```python
for iteration in range(1, max_iterations + 1):
    iter_dir = os.path.join(run_dir, f"iteration_{iteration:03d}")
    os.makedirs(iter_dir, exist_ok=True)
    ...
```

There is no resume detection, no completion check, and no state re-population. If the same `run_name` is re-invoked after a SIGKILL:

- `iteration_001/` will be re-created (`exist_ok=True` is permissive). It is **not cleared**.
- Interpretation, proposal, implementation, validation, and tuning will run again from scratch.
- The tuner writes into `{iter_dir}/{model}/records/{run_name}/`. If a previous run wrote partial records there, the new tuner will see them in `sandbox.get_summary()` (which scans the records dir) — a silent merge that the planner's `memory_history` will treat as legitimate prior rounds.
- `iteration_results` starts empty. `recent_tune_outputs` starts empty. `current_runtime_vocab` starts at the seed. **All long-term memory is lost.**

This means restart is destructive for partially-completed iterations and amnesic for completed ones. **It is not safe to restart any in-flight run today.**

### 2.2 Where save state already lives (no new state file needed)

Today's workflow already writes substantial on-disk state. The full inventory:

| Artifact | Path (relative to `{run_dir}`) | Written when | Carries |
|---|---|---|---|
| Interpretation output | `iteration_NNN/interpretation_{run_name}.json` | After interp completes | `runtime_vocab`, `model_knowledge_cache`, take-home, best score |
| Proposal output | `iteration_NNN/attempt_MMM_{model}/proposal_{run_name}.json` | After proposer completes | full `ProposalOutput` (model_name, model_description, hyperparam grid, …) |
| Implementor output | `iteration_NNN/attempt_MMM_{model}/implementor_{run_name}.json` | After implementor | model_file_path, description_file_path, plugin source |
| Validation output | `iteration_NNN/attempt_MMM_{model}/validation_{run_name}.json` | After validator | passed flag, error message, gradient/test results |
| Plugin source files | `iteration_NNN/attempt_MMM_{model}/models/{model_name}.py` + `tests/` | After implementor | the actual Python plugin |
| **Tuner full output** | `iteration_NNN/{model}/run_output_{run_name}.json` | At end of `HyperparamTuningAgent.run()` (clean exit only) | full `HyperparamTuningOutput` (all_records, best_score, gate_exhaustion, physical_rejections, …) |
| Tuner summary | `iteration_NNN/{model}/summary_{run_name}.json` | Same | condensed view |
| Per-round records | `iteration_NNN/{model}/records/{run_name}/*.json` | After each round | per-round/attempt records (training, scoring, memory, errors) |
| Sentinels | `iteration_NNN/{model}/cached_models/_OK_<exp_id>` | After clean training (Phase 6.7) | atomic train-success marker |
| Hardware context | `{run_name}_hardware_context.json` | First call to `get_or_create` | GPU info |
| Workflow summary | `{run_dir}/workflow_{run_name}.json` | At workflow exit (clean only) | final aggregate; **NOT WRITTEN ON SIGKILL** |
| Memory trace | `{run_dir}/memory_trace.jsonl` | Every probe call, append-only | diagnostic only — fine to keep accumulating |

**Key invariant for resume**: an iteration N is "committed" iff `iteration_NNN/{model}/run_output_{run_name}.json` exists AND validates as `HyperparamTuningOutput`. This file is the natural commit fence — the tuner writes it last in its run() exit path, so its presence proves every upstream artifact (interpretation, proposal, validation) and every per-round record is on disk.

No new state file is needed. **The resume mechanism is purely a reader of existing artifacts.**

### 2.3 Logical commit point — end of iteration

#### Coarse-grained (proposed primary): end of iteration

Place: `workflows/model_exploration.py:904`, immediately after `iteration_results.append(tune_output)`.

At this moment:
- `run_output_{run_name}.json` is on disk (tuner wrote it at the end of its run).
- All per-round records are on disk.
- All upstream attempt artifacts are on disk.
- The in-memory state for "iter N → iter N+1" is fully derivable from these files.

This is the only commit point that is both **easy to detect** (single boolean: does the JSON validate?) and **fully durable** (every artifact below this fence is written).

#### Fine-grained (deferred to a future phase)

Per-tuner-round commit. The tuner already writes per-round records, so a "resume mid-tune" would mean restarting `HyperparamTuningAgent.run()` from a partial set of records. Two issues:

1. The tuner's planner state machine (`gate_exhaustion`, `consecutive_fail_rounds`, `recent_round_summaries`) lives only in memory inside `run()`. A mid-tune resume would need to reconstruct this from records — doable but non-trivial.
2. Most iters are dominated by a single long round (v5 exploit iter_003: rid=3 alone was 222 min of 437 min total wall). Coarse-grained resume already protects 50–60% of any iter's work.

**Recommendation**: ship coarse-grained resume in Phase 6.8. Revisit fine-grained when a single iter regularly costs > 6 hours.

### 2.4 Resume detection algorithm

Pseudocode for a `_detect_resume_state(run_dir, run_name)` helper:

```
Inputs:  run_dir (str), run_name (str)
Outputs: completed_iters: list[(iter_dir, HyperparamTuningOutput)]
         next_iter_index: int
         partial_iter_dir: Optional[str]   # to be cleaned

iter_dirs = sorted(glob(f"{run_dir}/iteration_*"))
completed = []
partial = None

for d in iter_dirs:
    candidates = glob(f"{d}/*/run_output_{run_name}.json")
    if not candidates:
        partial = d        # interrupted before tuner finished
        break
    candidate = candidates[0]   # at most one model-named subdir per iter
    try:
        ho = HyperparamTuningOutput.model_validate_json(read(candidate))
    except ValidationError:
        partial = d        # corrupt write — also a partial
        break
    completed.append((d, ho))

next_iter_index = len(completed) + 1
return completed, next_iter_index, partial
```

**Key contract**: completed_iters is contiguous from iter_001 to iter_N. We refuse to "skip" a missing iter — if iteration_005 is missing but iteration_006 exists, we treat 005 as the partial and 006 as orphaned. (If this ever happens in practice, it's a bug, not a recoverable state.)

### 2.5 State re-population on resume — variable-by-variable

Each in-memory variable that the iter loop depends on, mapped to its on-disk source:

| Variable | Source | Rebuild |
|---|---|---|
| `iteration_results: list[HyperparamTuningOutput]` | `iteration_NNN/{model}/run_output_{run_name}.json` for each completed iter | already a list of these — populate from `completed` |
| `recent_tune_outputs: deque(maxlen=3)` | same | `deque(iteration_results[-3:], maxlen=3)` |
| `latest_new_summary: ModelRunSummary` | `iteration_results[-1]` | `tuning_outputs_to_summaries([iteration_results[-1]])[0]` (then attach `.model_description` from the corresponding proposal JSON) |
| `model_knowledge_cache: dict` | last completed iter's `interpretation_{run_name}.json` field `model_knowledge_cache` | load JSON + dict() |
| `current_runtime_vocab: list[VocabEntry]` | same JSON, field `runtime_vocab` | validate each as VocabEntry |
| `previous_proposal_data: dict` | last completed iter's `attempt_MMM_{model}/proposal_{run_name}.json` (the **accepted** attempt — model_name matches the iter's `<model>` subdir) | json.load |
| `all_model_types: list[str]` | initial seeds (`tuning_outputs`) ∪ completed iter model names | dedup union |
| `best_score_overall: float | None` | recompute from iteration_results | `max(o.best_denoising_score for o in iteration_results if not None)` |
| `previous_failures: list[str]` | always reset (only meaningful inside an iter's proposal loop) | `[]` |
| `hardware_ctx: HardwareContext` | `get_or_create` reads its own cache | call as before — first-caller-writes/later-callers-read |
| **Plugin registry** (`MODEL_REGISTRY` etc.) | `iteration_NNN/attempt_MMM_{accepted_model}/models/{model_name}.py` for each completed iter | for each completed iter, re-call `_register_plugin` with the on-disk plugin source (this also re-populates the run-scoped tuner plugin dir if missing) |
| `tuning_dir / dest_plugin_dir` for prior iters | `iteration_NNN/{model}/` | only relevant if we wanted to re-tune; we don't, so no rebuild needed |

**Critical detail — plugins**: the v5 explore run DID land its iter_001 plugin at `iteration_001/lite_dualpath_spectral_tcn/cached_models/`, but the parent's `MODEL_REGISTRY` would be empty on a fresh start. Iter_002's interpreter+proposer should not need to dispatch to the `lite_dualpath_spectral_tcn` model class (that model's record is already in `iteration_results`), but downstream code might. Re-registering all completed iters' plugins on resume is safer than skipping it.

**Critical detail — `latest_new_summary.model_description`**: this field is attached post-hoc at `workflows/model_exploration.py:917–918` (`s.model_description = proposal.model_description`). On resume we have to read the proposal JSON of the most recent completed iter to reconstruct it.

### 2.6 Resume wiring at the workflow surface

#### CLI

Add one flag to `run_exploration_adaptive.py`:

```
--resume        Auto-detect last completed iteration and resume from N+1.
                Refuses to start if {run_dir}/iteration_001/ already exists
                without --resume (prevents accidental destructive restarts).
```

#### Workflow entry behavior

```
if args.resume:
    completed, next_iter, partial = _detect_resume_state(run_dir, run_name)
    if completed:
        log "[RESUME] Found N completed iterations under {run_dir}"
        repopulate all in-memory vars per §2.5
        if partial:
            log "[RESUME] Removing incomplete iter dir {partial}"
            shutil.rmtree(partial)
        start_iter = next_iter
    else:
        log "[RESUME] No completed iterations found — starting fresh from iter 1"
        start_iter = 1
elif {run_dir}/iteration_001 exists:
    raise SystemExit(
        "Run dir already has iteration_001/ — pass --resume to continue, "
        "or pick a new --run_name. Refusing to clobber."
    )
else:
    start_iter = 1

for iteration in range(start_iter, max_iterations + 1):
    ...
```

#### Operator UX example

```
$ python run_exploration_adaptive.py --run_name explore_novel_v5_0426 --resume \
      --advice tuner_advice/explore_novel_v3.json \
      --llm_config llm_configs/openai_tiered_v1.json \
      ...

[RESUME] Found 1 completed iteration under .../explore_novel_v5_0426/
[RESUME] Removing incomplete iter dir: iteration_002 (no run_output_*.json)
[RESUME] Restored: iteration_results=1, recent_tune_outputs=1,
          vocab=23 entries, model_types=3, best_score=5.5763
[RESUME] Re-registered plugin: lite_dualpath_spectral_tcn
[RESUME] Resuming at iteration 2/20
```

### 2.7 Edge cases and contracts

| Case | Handling |
|---|---|
| Resume on a different host (different GPU) | `hardware_context.json` will be re-discovered; warn if `device_name` or `total_memory_gb` differs from the prior context. The VRAM gate is per-iter, so this only affects future iters — past records are not re-evaluated. |
| Resume with a different `--llm_config` | Log a warning. Different planner/reflector models will produce different plans for the same `memory_history`; that is the operator's choice. |
| Resume with a different `--max_iterations` | Allowed. If new max ≤ completed count, exit cleanly with "all iters already complete". |
| Resume with a different `--trial_time_budget_minutes` etc. | Allowed. Past records keep their original budgets in their JSON; new iters use the new budget. |
| Tuner output JSON corrupt (write killed mid-flush) | `model_validate_json` raises ValidationError → treated as partial → directory removed → iter re-runs. |
| Plugin source missing (`models/{name}.py` deleted by hand) | `_register_plugin` logs warning and skips. Iter is marked complete in `iteration_results` (its tuner output is valid), but the model class is not in the registry. Downstream code that needs the class will fail loudly — better than silently re-running. |
| `memory_trace.jsonl` exists from prior run | Append-only — new probe rows stack on. Diagnostic consumer must filter by timestamp / iter to separate runs. Acceptable. |
| `previous_failures` carry-over | These live only inside an iter's proposal-retry loop, never persisted. Always reset on resume. The next iter's proposer starts fresh as it would in a normal run. |
| `_aggregate_worst_offender_rejections` (line 685) on resume | Reads from `iteration_results[-1].physical_rejections`. The rebuild populates `iteration_results` correctly, so this works without special-casing. |

### 2.8 What this design explicitly does NOT do

- **No mid-iter checkpoint**: if the tuner is in the middle of round 2 of 3 when SIGKILL hits, that iter is restarted. We pay up to one full iter of re-work.
- **No state diff across resumes**: we don't snapshot the parent's full Python state (pickled). The on-disk artifacts are the contract.
- **No cross-host portability guarantees**: the hardware_context is host-specific, and plugin Python files might depend on host-specific module paths. Resume is intended for "same host, post-SIGKILL" not "migrate to a new host".
- **No Phase 6.7 contract changes**: sentinels, time-gate, ghost-score-fix all stay as-is. Resume is orthogonal.

### 2.9 Test strategy

1. **Unit**: `_detect_resume_state` against a fixture tree with (a) zero iters, (b) 3 clean iters, (c) 3 clean + 1 partial, (d) 2 clean + 1 corrupt JSON, (e) skipped iter (1 + 3 with no 2 — should raise).
2. **Unit**: `_repopulate_state` against the same fixtures, asserting each in-memory var matches the source JSON byte-for-byte where applicable.
3. **Integration (pseudo-mode)**: run a 3-iter `model_exploration` workflow to completion → kill the parent mid-iter-2 → restart with `--resume` → assert workflow finishes with the same final aggregates as a clean 3-iter run (modulo iter_002's content, which gets re-generated from scratch).
4. **Hostile case**: corrupt the iter_001 tuner JSON byte-by-byte and verify the resume safely refuses to start (or re-runs that iter, depending on the corruption mode).

---

## Phase 6.8 commit plan — Task 1 (shipped, PR #63)

| # | Commit | Layer | Effect |
|---|---|---|---|
| 1 | `fix(scoring): switch ProcessPoolExecutor to spawn` | Part 1 §1.5 Layer A | Eliminates fork-amplification — would have prevented the v5 host-OOM |
| 2 | `feat(memory_probe): add post_gc phase` | Part 1 §1.5 Layer B prep | Adds the diagnostic surface for measuring leak fixes |
| 3 | `fix(workflow): per-iter del + gc.collect with post_gc probe` | Part 1 §1.5 Layer B | Caps per-iter steady-state leak |
| 4 | `fix(tuner): per-round del + gc.collect` | Part 1 §1.5 Layer C | Caps per-round steady-state leak |
| 5 | `feat(scoring): compute_ground_truth.py — perfect-denoiser ceiling` | follow-up | Bounds the achievable denoising score — useful for diagnosing tuner saturation |

(Originally this table also held commits 5–7 for the in-process resume design from Part 2. Those are removed; the chain-first plan in Part 3 supersedes them.)

---

## Part 3 — Chain-first Resume (Active Plan)

**Trigger**: SDSC-chain evaluation report at `reports/phase68_sdsc_chain_evaluation_20260427.md` showed the existing per-iteration sbatch chain already provides process isolation and manifest-based handoff. Promoting the chain to be the **default** lilab runner, then layering resume detection on top, is strictly less code than the in-process resume design in Part 2 — and gives a structural memory floor that complements (and partially obviates) Task 1's mitigations.

### 3.1 Architecture

A single per-iteration runner serves three roles, distinguished only by which iteration it is launched at:

```
                         ┌─────────────────────────────────────┐
                         │  run_chain.sh --mode {lilab,sdsc}   │
                         │  (single shell entry point)         │
                         └─────────────────────────────────────┘
                                          │
                            (decides start_iter via auto-resume)
                                          │
                                          ▼
                         ┌─────────────────────────────────────┐
                         │  for ITER in start_iter..N:         │
                         │    submit_iteration(ITER)           │
                         └─────────────────────────────────────┘
                                          │
                  ┌───────────────────────┴───────────────────────┐
                  ▼ (lilab)                                       ▼ (sdsc)
        foreground subprocess                            sbatch + afterany dep.
                  │                                                │
                  ▼                                                ▼
                       ┌────────────────────────────────────────┐
                       │  python run_one_iteration.py           │
                       │  --workspace W --iteration N --...     │
                       └────────────────────────────────────────┘
                                          │
                            (1) restore_prior_state(W, N)  ← NEW
                            (2) run_workflow(max_iterations=1, ...)
                            (3) write_manifest(...)
```

The resume mechanism is the auto-detection step inside `run_chain.sh` plus the unconditional `restore_prior_state` call inside `run_one_iteration.py`. There is no in-Python iteration loop to interrupt, so there is no in-Python state to rebuild.

### 3.2 Input contract — unify with `run_exploration_adaptive.py`

The two runners do the same job differently. Their CLI flags should match. Today, `run_one_iteration.py` is missing several flags `run_exploration_adaptive.py` exposes. The chain runner must accept all of them.

| Flag | `run_exploration_adaptive.py` | `run_one_iteration.py` (today) | Action |
|---|---|---|---|
| `--run_name` | required | (synthesised: `iter_{N:03d}`) | chain stays auto-synth (per-iter), but `--workspace` is shared across iters |
| `--workspace` | optional (default `/home/klz/Data/SIDEREIS_DATA/exploration_{run_name}`) | required | unify on `--workspace` required at chain layer; lilab default same as adaptive |
| `--advice` (single JSON, propose/implement/tune/mindset) | ✅ | ❌ (uses `--human_advice_file` with 5 keys: interpret/propose/implement/validate/tune) | **switch chain to `--advice`**; adopt adaptive's 4-key schema (interpret + validate are unused today) |
| `--llm_config` (per-node JSON) | ✅ | ❌ (uses `--llm_model` + `--reflect_provider/model_id`, gemini-only) | **add `--llm_config`** to chain; deprecate `--llm_model` |
| `--max_iterations` | ✅ (default 20) | ❌ (`run_workflow` always called with =1) | add as `--num_iterations` to `run_chain.sh` (controls chain length); `run_one_iteration.py` keeps `max_iterations=1` internally |
| `--max_rounds` | ✅ (default 3) | ✅ (default 20 — stale) | sync default to 3 |
| `--max_proposal_attempts` | ✅ | ✅ | parity |
| `--max_impl_attempts` | ✅ | ❌ | add |
| `--trial_portion`, `--train_portion`, `--eval_portion`, `--max_epochs` | ✅ | ✅ | parity |
| `--trial_strategy` | ✅ | ✅ | parity |
| `--target_files` | ✅ | ❌ | add |
| `--sampling_seed` | ✅ | ❌ | add |
| `--trial_time_budget_minutes`, `--formal_time_budget_minutes` | ✅ | ❌ | add |
| `--data_dir` | ✅ | ❌ | add |
| `--trial_vram_budget_gb`, `--formal_vram_budget_gb` | ✅ | ❌ | add |
| `--formal_strategy`, `--formal_portion`, `--formal_train_portion` | ✅ | ✅ | parity |
| `--attempts_per_round`, `--attempts_per_formal_round`, `--max_fail_rounds` | ✅ | ❌ | add |
| `--exploration_mode`, `--minimum_boldness` | ✅ | ❌ | add |
| `--debug_dump_prompts` | ✅ | ❌ | add |
| `--source_paths` | ✅ (defaults to wavenet+punet seeds) | ✅ (required, includes `@manifest:` entries) | rename adaptive's flag to `--seed_paths` for chain to disambiguate from chained outputs; keep `--source_paths` as alias |
| Slurm-only: `--partition`, `--time`, `--mem`, `--gpus`, `--cpus` | ❌ (not applicable) | (in `_chain_common.sh`) | retain in `run_chain.sh`, ignored under `--mode lilab` |

**Default-shape rule**: any flag accepted by `run_exploration_adaptive.py` must have an identical default in `run_chain.sh`. The two runners should produce the same workflow behaviour given the same flags, modulo the per-iteration process boundary.

### 3.3 Plugin re-registration (Python-side repopulation)

#### Why this is not just a "resume" feature

In the chain paradigm, every iter > 1 launches a fresh Python interpreter. `MODEL_REGISTRY` starts at the built-in set; prior iters' plugin classes are absent until restored. This is the case both for a normal sequential chain (iter N+1 launched after iter N completes) and for a SIGKILL-then-restart. The same code path serves both — there is no "resume" branch in the Python.

#### Registry surfaces that must be in sync

| Registry | Module | Updated today by |
|---|---|---|
| `MODEL_REGISTRY` | `ml_models/models_sandbox.py` | `_register_plugin`, `extend_registries` |
| `PLUGIN_CONFIG_REGISTRY` (packaged) | `ml_models/models_format_sandbox.py` | `_register_plugin`, `extend_registries` |
| `PLUGIN_OUTPUT_TYPE_REGISTRY` | `ml_models/plugin_loader.py` | **only** `extend_registries` |
| Bare-name `models_format_sandbox.PLUGIN_CONFIG_REGISTRY` | sys.modules dual-identity (subprocess parity) | `models_sandbox.py:670–673`, **not** `_register_plugin` |

**Latent bug**: `_register_plugin` (`workflows/model_exploration.py:381–392`) updates the first two only. Resume must do better. Fix: extract the registry update into a helper that hits all four surfaces, then route both `_register_plugin` and resume through it.

#### `_add_plugin_to_registries(plugin_path)` — the primitive

Takes a plugin .py path on disk and:
1. Calls the canonical `_load_plugin` from `ml_models.plugin_loader` — this registers the module in `sys.modules` under `siderius_plugin_<stem>` so `inspect.getsource(cls)` resolves the source file (Phase D.1 planner-prompt excerpt depends on this).
2. Updates all four registry surfaces above.
3. Returns the model_type string on success, None on load failure.

`_register_plugin` is refactored to call this helper after its `shutil.copy2`. Single source of truth, zero behavioural drift.

#### Producer must mirror to chain-canonical path

`_register_plugin` historically wrote only to the tuner-scoped `get_plugin_dir(tuning_dir, run_name)` — that is what the training subprocess discovers via `SIDERIUS_PLUGIN_DIRS` (docs/run_scoped_plugins.md, Phase 4). But `restore_prior_state` reads from the **chain-canonical** `get_plugin_dir(workspace, run_name)`. Both paths are needed: one for sandbox isolation, the other for cross-iter handoff. The producer mirrors to both:

```python
from core.sandbox_executor import get_plugin_dir
_register_plugin(
    impl_output,
    proposal.model_name,
    [
        get_plugin_dir(tuning_dir, run_name),  # tuner-scoped — sandbox SIDERIUS_PLUGIN_DIRS
        get_plugin_dir(workspace,  run_name),  # chain-canonical — restore_prior_state
    ],
)
```

`_register_plugin` accepts `dest_plugin_dirs: list[str] | str` and copies both the `.py` and `description.md` to every dest. The first dest is the primary — its `.py` is fed to `_add_plugin_to_registries` (the in-process planner sees the new model type without a re-scan). A bare `str` is still accepted for back-compat with older call sites and unit tests.

#### Description loader anchored on the chain workspace

`ml_models.model_descriptions.get_model_description` is the second consumer of the chain-canonical plugin tree. The interpreter and proposer call it on every iter with the model_type they read from a prior iter's manifest; on iter > 1 the model_type is agent-generated and has no built-in description.md. To resolve it without threading workspace through every node schema, the entry scripts publish the workspace as a process-global env var:

- `sdsc_submission_scripts/run_one_iteration.py` and `run_exploration_adaptive.py` set `os.environ["SIDERIUS_CHAIN_WORKSPACE"] = os.path.abspath(workspace)` before any node init.
- `get_model_description(model_type)` searches in priority order:
  1. `ml_models/{model_type}/description.md` (built-in)
  2. `agent_generated/models/{model_type}/description.md` (legacy plugin global)
  3. `${SIDERIUS_CHAIN_WORKSPACE}/plugins/iter_NNN/{model_type}/description.md` — walked in descending iter order so the latest registration of a model_type wins.

This mirrors the existing `SIDERIUS_PLUGIN_DIRS` idiom (docs/run_scoped_plugins.md, Phase 2): each chain process has exactly one chain workspace, so a process-global value is the right shape. Schemas stay clean; only the entry scripts know about the env var; descendant calls read it transparently.

#### `restore_prior_state(workspace, current_iter, seed_paths)` — top-level

For each prior iter NNN in 1..current_iter-1:

1. Load `{workspace}/iter_NNN/manifest.json`. If missing or `status != "completed"`, raise. (Same contract as `resolve_source_paths` today.)
2. Validate `manifest["output_path"]` as `HyperparamTuningOutput` via Pydantic — same predicate `scripts/inspect_run_state.py:91–104` uses. Treat ValidationError as a hard failure.
3. Locate the plugin source at `{workspace}/plugins/iter_NNN/{model_name}.py` (path computed via `core.sandbox_executor.get_plugin_dir`). Call `_add_plugin_to_registries`. Warn but continue if the file is missing — the `HyperparamTuningOutput` JSON is enough for `memory_history` reconstruction; only training would dispatch on the class, and the chain never re-trains prior iters.
4. Append the validated output_path to `resolved_source_paths`.

Returns `RestoredState(resolved_source_paths, restored_plugins, committed_iters)`. The chain runner then calls `run_workflow(source_paths=state.resolved_source_paths, ...)` with `max_iterations=1`.

### 3.4 Auto-resume detection (shell side)

`run_chain.sh --auto_resume` (default ON) computes `start_iter` via:

```bash
NEXT=$(.venv/bin/python scripts/inspect_run_state.py \
           --workspace "$WORKSPACE" --layout chain --next-iter)
START_ITER=${NEXT:-1}
```

`scripts/inspect_run_state.py` gets:
- A new `--layout {run,chain}` flag selecting between the legacy `{run_dir}/{run_name}/iteration_NNN` layout and the chain `{workspace}/iter_NNN` layout.
- A new `--next-iter` flag that prints **only** the integer index of the first non-COMMITTED iteration on stdout (1 if no committed iters), suitable for shell capture.

Safety rules in the shell driver:
- If `$START_ITER == 1` and `$WORKSPACE` is non-empty, refuse to start unless `--force_fresh` is passed. Mirrors the "refuse to clobber iteration_001" guard from §2.6.
- If `$START_ITER > $NUM_ITERATIONS`, exit cleanly: "all iters already complete".
- If iters are non-contiguous (e.g. 1 + 3 with no 2), refuse — operator must inspect.

### 3.5 Commit plan — Task 2

Each commit ships its own design-doc update (per `feedback_plan_doc_sync.md`). Commits 6–9 are gated on unit tests passing locally before push. The chain commits (11–15) don't need to land in one PR — small wave of 3 PRs is fine. Commits 9–10 are v6 countermeasures (probe safety, LLM context) that can ship independently of the chain work; see Part 4 for the full design rationale.

#### Commit 6 — `refactor(workflow): extract _add_plugin_to_registries helper`

**Goal**: Single helper updates all four registry surfaces. Closes the latent bug.

- [x] Add `_add_plugin_to_registries(plugin_path: str) -> Optional[str]` to `workflows/model_exploration.py`.
- [x] Refactor `_register_plugin` to call it after the `shutil.copy2`.
- [x] Verify `PLUGIN_OUTPUT_TYPE_REGISTRY` and the bare-name mirror are now updated on every in-process plugin registration.
- [x] Unit test: a plugin with `PLUGIN_OUTPUT_TYPE = "regressor"` is registered and `get_output_type(model_type)` returns `"regressor"` (would have failed before).
- [x] Unit test: when both `models_format_sandbox` (bare) and `ml_models.models_format_sandbox` (packaged) modules are loaded, the bare one's `PLUGIN_CONFIG_REGISTRY` receives the new entry.
- [x] Run the relevant `tests/unit/ml_models/test_plugin_loader.py` and `tests/unit/agent/utils/test_proposer_preflight.py` (touches MODEL_REGISTRY). _45/45 green together with the new helper tests; see commit message._
- [ ] Doc-sync: this commit doesn't change Part 3's design — already documented above. Commit message references §3.3.

#### Commit 7 — `feat(resume): core/resume.py with restore_prior_state`

**Goal**: Top-level Python helper the chain runner calls before `run_workflow`.

- [x] Create `core/resume.py` with `RestoredState` dataclass and `restore_prior_state(workspace, current_iter, seed_paths)`.
- [x] Use `HyperparamTuningOutput.model_validate_json` as commit-fence predicate.
- [x] Use `core.sandbox_executor.get_plugin_dir` to compute the plugin path (do NOT hardcode `{workspace}/plugins/...`; reuse the canonical layout helper).
- [x] Use `_add_plugin_to_registries` from commit 6.
- [x] Refuse on missing manifest, missing run_output, non-completed status, malformed JSON, non-contiguous iters. _Also raises on workspace not found, missing `output_path`, and Pydantic ValidationError._
- [x] Warn (not raise) on missing plugin file; the JSON is the contract. _Same path also warns on a `.py` that fails `_load_plugin` validation (broken contract is a higher-tier corruption than missing file)._
- [x] Unit tests on a synthetic 3-iter workspace: clean run, missing iter_002, corrupt iter_002 JSON, missing plugin file (expect warn + continue), seed-paths-only (current_iter=1, returns seeds verbatim). _24/24 green; see `tests/unit/core/test_resume.py`._
- [x] Integration test: drive `restore_prior_state` after running a real 2-iter chain (use pseudo-mode if available) → verify `MODEL_REGISTRY` contains both iters' plugin classes. _High-fidelity 2-iter pseudo-integration test in `TestPseudoIntegrationTwoIterChain` uses real plugin .py files, verifies all four registry surfaces incl. bare-name mirror. The full run_workflow→manifest→restore loop is still scheduled for Commit 14._
- [ ] Doc-sync: §3.3 already describes this. Commit message references §3.3.

#### Commit 8 — `feat(chain): run_one_iteration.py calls restore_prior_state + --start_iteration`

**Goal**: Chain runner is correct on iter > 1 even on a fresh run (not just resume). Surface a manual-override flag for operators who bypass the shell auto-detection.

- [x] In `sdsc_submission_scripts/run_one_iteration.py:main()`, replace the bare `resolve_source_paths(args.source_paths)` call with `restore_prior_state(args.workspace, args.start_iteration, seed_paths)`. _Layered: `resolve_source_paths` runs first (back-compat for `@manifest:` strings from the legacy chain shell); its output is passed as `seed_paths` into `restore_prior_state`. New `run_chain.sh` (Commit 13) won't emit `@manifest:` strings, so the back-compat layer becomes a no-op then._
- [x] **Rename** `--iteration` → `--start_iteration` (positional meaning unchanged: which iter this invocation runs). Keep `--iteration` as a deprecated alias for one release; emit DeprecationWarning when used. The new name is consistent with `run_exploration_adaptive.py` (Commit 11) and with `run_chain.sh --start_iter`. _Implemented via `dest="iteration_legacy"` + post-parse mutex check in `normalize_args`. `test_legacy_iteration_alias_works_with_deprecation_warning` and `test_both_flags_supplied_is_an_error` cover the surface._
- [x] When `--start_iteration > 1`, restore is triggered automatically — no separate `--resume` flag needed. _`restore_prior_state` is called unconditionally; iter==1 short-circuits to seeds-verbatim, iter>1 walks the chain. No flag check needed in the runner._
- [x] Pass `state.resolved_source_paths` to `run_workflow`. _`resolved_paths = state.resolved_source_paths` and forwarded into `run_workflow(source_paths=resolved_paths, ...)`. Asserted by `test_start_iteration_2_restores_iter_1_plugin_and_prepends_path`._
- [x] Print `[CHAIN] Restored N prior plugin(s) from iters [...]` in the startup banner. _Banner only prints when `state.committed_iters` is non-empty (i.e. iter > 1). Asserted by `test_chain_banner_printed_when_priors_restored` (printed) and `test_chain_banner_omitted_for_iter_1` (omitted)._
- [x] On `--start_iteration == 1`, `restore_prior_state` returns `seed_paths` verbatim; verify no spurious behaviour. _Asserted by `test_start_iteration_1_passes_seeds_through_unchanged` — banner skipped, seeds passed through, no plugin registry mutation._
- [x] Wiring-level test: verify iter_002 restores iter_001 artifacts correctly (full integration in Commit 14). _Implemented as `test_missing_iter_1_plugin_warns_but_iteration_runs` — materialises iter_1 manifest + run_output without the plugin file, mocks `run_workflow` + `write_manifest`, asserts `UserWarning` emitted AND `runner.run_workflow` is still called with iter_1's output_path in `source_paths`. Full pseudo-mode 2-iter end-to-end run is scheduled for Commit 14 per §3.5._
- [x] Manual-override test: run `python run_one_iteration.py --workspace W --start_iteration 3 ...` against a workspace with iters 1+2 already on disk; verify it skips auto-detect and runs iter 3 directly. _Implemented as `test_manual_override_start_iteration_3_with_iters_1_and_2_on_disk`. Both prior iters' plugins re-registered into the four registry surfaces; `run_workflow` receives `source_paths = [seed, iter_1_output, iter_2_output]` and `run_name="iter_003"`._
- [x] Doc-sync: §3.3 already describes this. Commit message references §3.3 and §3.4. _Pending — to be referenced in the combined commit message._

#### Commit 9 — `fix(probe): memory-safe structural probe with cleanup between passes`

**Goal**: Prevent the 33 GB autograd-tape explosion that killed `explore_novel_v6_0427` iter_002 (`dual_selective_ssm_head`). See Part 4 §4.1 for full root cause analysis and `reports/v6_pr63_20260428.md §8` for the diagnostic data.

**Root cause recap**: `probe_activation_footprint` in `structural_probe.py` runs three consecutive forward passes (autograd tape, torchinfo, shape validation) with **no cleanup** between them. For models with Python-level sequential loops (SSM scan: 320K iterations), the autograd graph alone is ~15-18 GB. The wrapper then builds two more model instances for inference probing, also without freeing the first. Total observed: 35.6 GB RSS at OOM kill.

- [x] **`structural_probe.py:probe_autograd_tape`**: `pack_hook` now returns `None` instead of the original tensor, preventing autograd from retaining the actual tensor data. For 320K-step SSM models, this drops memory from ~15-18 GB (retained tensors) to ~350 MB (graph nodes only). `unpack_hook` raises `RuntimeError` if backward() is called. Explicit `del loss; gc.collect()` after the hooks context exits. _Stronger fix than the original plan — prevents the memory from being allocated, rather than cleaning it up after._
- [x] **`structural_probe.py:probe_activation_footprint`**: `del _fwd; gc.collect()` after the tape walk frees the closure. The subsequent `probe_forward_layers` and `model(input_sample)` calls are now wrapped in `torch.no_grad()`, preventing autograd graph rebuild during the torchinfo and shape-validation passes.
- [x] **`wrapper.py` (VRAM skill)**: `del model_for_train, loss_module, x_train, y_train; gc.collect()` after the training probe and before building inference models. `del model_for_resolve; gc.collect()` after batch resolution. `del model_for_bd; gc.collect()` after the inference breakdown probe.
- [x] **Host-RSS safety check**: `psutil.Process().memory_info().rss` read before and after the training probe. Delta > 8 GB logs `[PROBE_MEMORY_WARNING]`; otherwise logs `[Probe RSS] delta=X.XX GB`. Diagnostic only — not a gate.
- [x] **`torch.no_grad()` for inference probes**: verified — `probe_activation_footprint(mode="inference")` already runs `model.eval()` + `torch.no_grad()` internally. No change needed.
- [x] Unit test: `SequentialModel(steps=500)` — `test_sequential_model_training_probe_rss_bounded` asserts RSS delta < 500 MB. _Passes — delta is ~0 MB with the None-returning pack_hook._
- [x] Unit test: `test_sequential_model_probe_gc_called_between_phases` — mocks `gc.collect` and asserts call count >= 2.
- [x] Unit tests: `test_pack_hook_returns_none_not_tensor`, `test_probe_autograd_tape_unpack_raises_on_backward`, `test_torchinfo_runs_under_no_grad_in_training_mode`.
- [x] Regression test: 128/128 tests pass in `tests/unit/agent/evaluate_vram_skill/` (123 original + 5 new).
- [x] Doc-sync: Part 4 §4.1 describes this. Commit message references §4.1. _Commit `c0d96de`._

#### Commit 10 — `fix(prompts): sliding-window memory_history + context size caps`

**Goal**: Prevent unbounded LLM prompt growth across rounds and iterations. See Part 4 §4.3 for full design and `reports/v6_pr63_20260428.md §10` for the diagnostic data.

**Root cause recap**: Three growth vectors — (1) `memory_history` in tuner planner prompt serializes ALL experiment records with no sliding window (50-100KB at 10 rounds); (2) `model_knowledge_cache` in `InterpretationOutput` grows monotonically (352KB by iter 9 in v4); (3) `model_descriptions` rendered untruncated into proposer prompt (7KB per model). None of these caused OOM in v6's short runs, but they will degrade LLM reasoning quality and cost over 20-iteration chains.

**Sliding window for `memory_history`** (`agent/prompts.py`):
- [x] Add a `_truncate_memory_history(records: list[dict], full_window: int = 3) -> list[dict]` helper. _Non-destructive — returns a new list; original `memory_history` is never mutated. `build_exploration_checklist` continues to receive the full list._
- [x] Records within the last `full_window` rounds: kept verbatim (full params, score_table, loss_history, memory block).
- [x] Older records: condensed to `{exp_id, status, model_type, denoising_score, is_trial}` + `memory: {hypothesis, conclusion, round_index}`. Drops `params`, `score_table`, `loss_history`, `file_vector`, `timing`, and heavy memory keys (`key_factor`, `discovery`, `memory_update`).
- [x] Called at `get_planner_user_prompt` before `json.dumps`. Only the serialised prompt copy is truncated.
- [x] Unit tests (8): 10→3+7 split, exact key checks, non-destructive, empty list, missing memory block, JSON size reduction ≥30%. _All in `test_memory_history_truncation.py`._

**Model knowledge cache cap** (`InterpretationOutput` / proposer pipeline):
- [x] Extracted `_cap_knowledge_cache(cache, current_model, max_entries=5)` helper in `workflows/model_exploration.py`. Returns `(capped_cache, evicted_set)`. Keeps union of (top-N by `_stats.best_denoising_score`) + (current iteration's model). `None` scores rank below all scored models.
- [x] Applied in the iter loop after `model_knowledge_cache = dict(interpretation.model_knowledge_cache)`, before the cache is passed to the next iteration's proposer. Eviction logged as `[N] Cache capped: evicted [...]`.
- [x] Unit tests (6): under/exact limit, 8→5 by score, current model survives even if worst, None-scores evicted first, custom max_entries. _All in `test_knowledge_cache_cap.py`._

**Model descriptions truncation** (`nodes/ml_model_proposal_agent.py`):
- [x] Added `_truncate_description(text: str, max_chars: int = 1500) -> str`. Keeps the first `max_chars` characters and appends `\n[...truncated]`. Short descriptions returned unchanged.
- [x] Applied in `_build_reasoning_prompt` (line 621) inside the `descriptions` loop, before injecting into the prompt. Disk artifacts and `ModelRunSummary` remain untruncated.
- [x] Unit tests (5): short unchanged, exact limit unchanged, over-limit truncated with marker, custom limit, 7KB→1500+marker. _All in `test_description_truncation.py`._

**Prompt size diagnostic**:
- [x] `[PROMPT_SIZE] planner: N chars` logged in `llm_bridge.py:plan()` after assembling the final user prompt (includes history + checklist + plugin source + manual context).
- [x] `[PROMPT_SIZE] proposer_reasoning: N chars` logged in `ml_model_proposal_agent.py:_run_legacy()` before the reasoning LLM call.
- [x] `[PROMPT_SIZE] N chars` logged per pipeline stage in `_run_pipeline()` before each LLM call.

- [x] Regression: planner tests 21/21, proposer suite 396/396, preflight 18/18, workflow 105/105, llm_bridge 61/61. Zero regressions.
- [x] Doc-sync: Part 4 §4.3 describes this. Commit message references §4.3. _Commit `1b39fb9`._

#### Commit 11 — `feat(chain): unify CLI surface across run_one_iteration.py and run_exploration_adaptive.py`

**Goal**: Input contract parity per §3.2. Both Python entries accept the same flag set with identical names and defaults. `run_exploration_adaptive.py` gains `--start_iteration N` and converges on the chain workspace layout when N > 1.

**Atomic decomposition (sub-commits)** — landed progressively to keep history bisectable. The original "Parts A/B/C" framing below describes the engineering surface; the **landing order** was 11.1 → 11.2 → 11.3 → 11.4 + a final doc-sync. Each sub-commit verified independently before the next was touched.

| Sub-commit | Subject | Status | SHA |
|------------|---------|--------|-----|
| 11.1 | `test(cli): cover force_formal_round flag + catch up to seed_paths/start_iteration renames` — test-side catch-up to runtime renames already in HEAD (`a4238de`, `c38837e`); 45/45 unit tests green. | **Landed** | `a95eb92` |
| 11.2 | `fix(estimator): recalibrate static ms/step formula + add 2.0 ms floor (Phase 6.8 §4.2)` — `_STATIC_MS_PER_FLOP` 6e-10→3e-9, new `_MIN_MS_PER_STEP=2.0` floor, `SAFETY_MULTIPLIER` 1.1→2.0; preflight fixture rebalanced (50k params); 58/58 unit tests green. | **Landed** | `2d2a196` |
| 11.3 | `fix(prompts): implement generic conditional formal-round logic (conscious-physical alignment)` — `force_formal_round` plumbed through `LLMBridge.plan` → `get_planner_user_prompt`; final-round prompt renders MANDATORY when True / OPTIONAL when False; `_apply_mode_override_chain` helper extracted in tuner agent so prompt-side and override-side share a single flag; 40/40 unit tests green; prompt-diff inspection confirms toggle. | **Landed** | `6a03277` |
| 11.4 | `fix(handoff): implement producer-mirroring and workspace-anchored description loading` — `SIDERIUS_CHAIN_WORKSPACE` env-var anchor on both Python entries; `_register_plugin` accepts `dest_plugin_dirs: list[str] \| str` and run_workflow passes both tuner-scoped + chain-canonical dirs; `get_model_description` walks `${SIDERIUS_CHAIN_WORKSPACE}/plugins/iter_NNN/` newest-first; new `validate_workspace_layout` guard refuses legacy v5/v6 layouts on `run_exploration_adaptive.py`; 211/211 unit tests green. | **Landed** | `6c8130b` |
| Interim doc-sync | `docs(phase68): record Commit 11 atomic decomposition + Part A/B/C status to date` — added the table above, flipped Part A/B items to `[x]`, demoted `_chain_common.sh` plumbing to deferred-Commit-13. | **Landed** | `855117b` |
| Final doc-sync | This update — confirms 11.3 + 11.4 landed, captures end-to-end log gold, total test counts. | **Landed** | (this commit) |

The Part A/B/C block below remains the canonical engineering reference; sub-commits map onto it as: **11.2 ↔ Part A "Time Estimation Repair" sub-bullet + estimator constants** (the only Part A items still open at decomposition time, since flag-widening landed earlier in `a4238de`/`c38837e`); **11.4 ↔ Part C in full**; **11.3 ↔ a generic conditional that complements `force_formal_round` from Part A** (originally folded under the Generic Prompt Patch, now its own commit). Part B already landed earlier under Commit 8 (`c38837e`) plus the `--start_iteration` work; nothing pending in Part B at the time of decomposition.

**Cumulative test pass-count across the four sub-commits**: 45 (11.1) + 58 (11.2) + 40 (11.3) + 211 (11.4) = **354 unit tests** verifying the decomposition, plus the broader 925/925 sweep recorded under Part C and the end-to-end iter 1 + iter 2 chain run in `exploration_phase68_commit11_gate/` that produced `best_score=4.524` from a chain-restored handoff.

**Part A — `run_one_iteration.py` flag widening + time estimation repair:**

- [x] Add flags listed in §3.2 table that are missing today: `--llm_config`, `--advice`, `--target_files`, `--sampling_seed`, `--exploration_mode`, `--minimum_boldness`, `--debug_dump_prompts`, `--max_impl_attempts`, `--trial_time_budget_minutes`, `--formal_time_budget_minutes`, `--data_dir`, `--trial_vram_budget_gb`, `--formal_vram_budget_gb`, `--attempts_per_round`, `--attempts_per_formal_round`, `--max_fail_rounds`.
- [x] Switch `--max_rounds` default from 20 to 3 (sync with adaptive).
- [x] When `--llm_config` is provided, build `WorkflowLLMConfig.from_json`. Keep `--llm_model` as deprecated fallback for one release; emit DeprecationWarning if used without `--llm_config`.
- [x] Switch `--human_advice_file` schema from 5-key (interpret/propose/implement/validate/tune) to adaptive's 4-key (propose/implement/tune/mindset). Tolerate both schemas during transition (load both; missing keys are None).
- [x] Pass every new flag through to `run_workflow(...)`.
- [x] **`--data_dir` plumbing (v6 countermeasure — Time Estimation Repair)**: wire `--data_dir` through `run_workflow()` → `HyperparamTuningInput.data_dir` → time skill's `_measure_ms_per_step`. Without this, the warmup path is dead code and every run uses the static formula (5-10x underestimate for novel architectures). See `reports/v6_pr63_20260428.md §9.1`.
- [x] **Static formula patch**: in `agent/skills/training_skill/estimator.py`, raise `_STATIC_MS_PER_FLOP` from `6e-10` to `3e-9` and add a minimum ms/step floor of 2.0 ms (CUDA kernel launch + DataLoader overhead). Raise `SAFETY_MULTIPLIER` from `1.1` to `2.0` — the current value was calibrated for warmup variance, not formula error. See `reports/v6_pr63_20260428.md §9.2-§9.3`.
- [x] **`--train_portion` ruling**: set default to 0.1 on both Python entries (correcting the existing 1.0 in `run_exploration_adaptive.py`). Per Final Ruling 1 — 0.1 is the standard for trial rounds.
- [x] **`--max_epochs` ruling**: set default to 1 on both Python entries; install a `_positive_int` argparse validator that rejects 0/negative/None. Per Final Ruling 1.
- [x] **`--seed_paths` canonical / `--source_paths` deprecated alias**: Per Final Ruling 3, `--seed_paths` is the canonical name on both Python entries. `--source_paths` is kept as a deprecated alias (`dest="source_paths_legacy"`) that emits a `DeprecationWarning` and is mutually exclusive with the canonical name. Same pattern as the `--start_iteration` / `--iteration` alias from Commit 8.
- [x] **`--advice` 4-key help text**: adaptive's help string updated from "(propose/implement/tune keys)" to "(propose/implement/tune/mindset keys)" to match the actual schema.

**Part B — `run_exploration_adaptive.py` adopts `--start_iteration N` + chain workspace layout:**

This is the **convergence step** that makes the two Python entries truly equivalent. After this commit, `run_exploration_adaptive.py` is a "chain-in-one-process" runner: it loops over `run_workflow(max_iterations=1, run_name=f"iter_{N:03d}", ...)` calls, writing each iter to the chain workspace layout (`{workspace}/iter_NNN/`), exactly like the SDSC/lilab chain — minus the per-iter subprocess fork.

- [x] Add `--start_iteration N` (default 1).
- [x] When `N > 1`, call `restore_prior_state(workspace, N, seed_paths)` before entering the iter loop. Same trigger semantics as `run_one_iteration.py`.
- [x] Refactor the in-process iter loop: replace the single `run_workflow(max_iterations=20, ...)` call with `for ITER in range(start_iter, max_iterations + 1): run_workflow(max_iterations=1, run_name=f"iter_{ITER:03d}", ...)`.
- [x] Each iter call uses `source_paths=state.resolved_source_paths` (initially seeds + restored prior outputs); after each iter completes, append the new manifest's output_path to the list for the next iter (mirrors what the shell chain does between sbatch jobs).
- [x] Write `manifest.json` per iter (same format as `run_one_iteration.py:write_manifest`) so a workspace produced by `run_exploration_adaptive.py` is interoperable with `run_chain.sh`'s auto-resume.
- [x] **Behaviour change to flag in commit message**: workspace layout for `run_exploration_adaptive.py` now matches the chain (`{workspace}/iter_NNN/iteration_001/{model}/`) instead of the legacy `{run_dir}/{run_name}/iteration_NNN/{model}/`. Old workspaces from prior runs are not migrated automatically; operators rerun fresh or use the chain runner directly.
- [x] Workspace-layout guard: if `--workspace` already contains a legacy-layout directory (`{run_name}/iteration_NNN/...` siblings), exit with an error pointing operators at the migration note above.

**Part C — Body-Soul Alignment via Workspace Anchoring (chain-handoff fix):**

Added during the Commit 11 verification gate. Iter 2 crashed because the producer (`workflows/model_exploration.py:_register_plugin`) and the consumers (`core/resume.py:restore_prior_state`, `ml_models/model_descriptions.py:get_model_description`) had drifted on path conventions:

- **Bug 1 — chain restoration finds the JSON but not the plugin .py.** `restore_prior_state` reads from `{workspace}/plugins/iter_NNN/{model_type}.py`, but `_register_plugin` was writing only to the tuner-scoped `{tuning_dir}/plugins/{run_name}/{model_type}.py`. Iter 2 logged `[CHAIN] Restored 0 prior plugin(s)` even though iter 1's manifest existed.
- **Bug 2 — interpreter has no description.md fallback for agent-generated models.** `get_model_description` searched `ml_models/{type}/description.md` and `agent_generated/models/{type}/description.md` only — no workspace awareness. Iter 2's interpreter step crashed with `FileNotFoundError` for `wavenet_input_pe`.

**Fix — three coordinated changes** (see §3.3 for the architectural framing):

- [x] **Producer mirrors to chain-canonical path** (`workflows/model_exploration.py`). `_register_plugin` accepts `dest_plugin_dirs: list[str] | str` and writes the `.py` + `description.md` to every dest. Call site at `run_workflow` passes both `get_plugin_dir(tuning_dir, run_name)` (tuner-scoped, for `SIDERIUS_PLUGIN_DIRS` sandbox isolation) and `get_plugin_dir(workspace, run_name)` (chain-canonical, for `restore_prior_state` + description lookup). A bare `str` is still accepted for back-compat with older call sites and unit tests.
- [x] **Workspace-aware description loader** (`ml_models/model_descriptions.py`). Adds a third candidate to the search order: `${SIDERIUS_CHAIN_WORKSPACE}/plugins/iter_NNN/{model_type}/description.md`, walked in descending iter order so the latest registration of a model_type wins. Built-in and legacy global candidates are unchanged.
- [x] **Process-global anchor** (`sdsc_submission_scripts/run_one_iteration.py`, `run_exploration_adaptive.py`). Both entry scripts set `os.environ["SIDERIUS_CHAIN_WORKSPACE"] = os.path.abspath(workspace)` before any node init. Mirrors the existing `SIDERIUS_PLUGIN_DIRS` idiom (docs/run_scoped_plugins.md, Phase 2).

**Why env var instead of threading workspace through schemas**: each chain process has exactly one chain workspace. Threading it through `InterpretationInput`, `HyperparamTuningInput`, plus their protocols and tests would touch ~6 files for a process-global value. The env var keeps schemas clean; only the entry scripts know about it; descendant calls (`get_model_description` and any future workspace-scoped consumer) read it transparently.

**Verification gate** (must hold before landing Commit 11): **ALL GREEN** ✅

Run executed against `/home/klz/Data/SIDEREIS_DATA/exploration_phase68_commit11_gate/` (wiped fresh, iter 1 + iter 2 both `status="completed"`; iter 2 wall-clock 55:49). Models proposed by the chain: iter 1 → `posenc_causal_dilated_stack` (best_score = -3.22), iter 2 → `spectral_skip_residual_stack` (best_score = +4.524).

- [x] Wipe `/home/klz/Data/SIDEREIS_DATA/exploration_phase68_commit11_gate`.
- [x] Iter 1 with `--no-force_formal_round`: dual-path artifacts confirmed —
    - `{tuning_dir}/plugins/iter_001/posenc_causal_dilated_stack.py` (tuner-scoped) ✅
    - `{workspace}/plugins/iter_001/posenc_causal_dilated_stack.py` (chain-canonical) ✅
    - `description.md` mirrored in both `posenc_causal_dilated_stack/` subdirs ✅
    - Producer dual-write log lines: `/tmp/phase68_commit11_iter1.log` lines 84–87.
- [x] Iter 2: log gold —
    - `[CHAIN] Restored 1 prior plugin(s) from iters [1]` ✅ (`/tmp/phase68_commit11_iter2.log` line 44 — Bug 1 fixed; was `Restored 0` before).
    - Interpreter Step 1 resolves `posenc_causal_dilated_stack` description without crashing ✅ — Phase 1 returned 5 findings, 4 bottlenecks; Proposer prompt assembled cleanly with `Candidates: ['wavenet', 'punet', 'posenc_causal_dilated_stack']` (Bug 2 fixed).
    - `[PROMPT_SIZE]` telemetry visible ✅ at lines 99/101/158 of iter 2 log: planner 21,153 chars; comparison 36,123 chars; causal_reasoning 49,230 chars (Gate 4 evidence).
    - Iter 2 producer dual-write of `spectral_skip_residual_stack.py` + `description.md` — log lines 121–124.
- [x] End-to-end manifest: `iter_002/manifest.json` carries `status="completed"` with non-null `best_denoising_score` (4.524) — chain-restored handoff produces a real positive score.

**Unit test sweep results** (run before commit landing):

- `tests/unit/workflows/`, `tests/unit/core/test_resume.py`, `tests/unit/sdsc_submission_scripts/`, `tests/unit/scripts/test_chain_consistency.py`, `tests/unit/agent/ml_model_proposal_agent/test_force_formal_round*` — **116/116 passed**.
- Broader sweep `tests/unit/agent/test_llm_bridge_singleton.py + tests/unit/agent/ml_model_proposal_agent/ + tests/unit/ml_models/ + tests/unit/agent/tune_ml_hyperparam_agent/` — **925/925 passed in 221.70s**.
- One fixture had to be rebalanced for the new estimator calibration (Part A v6): `tests/unit/agent/ml_model_proposal_agent/test_preflight_revision_loop.py` — `FAKE_GOOD_DRAFT.num_params` reduced from `500_000` → `50_000` so the new tighter formula (`SAFETY_MULTIPLIER=2.0`, `_STATIC_MS_PER_FLOP=3e-9`, `_MIN_MS_PER_STEP=2.0`) yields the same "safely under-budget" preflight factor (~12 ms/step, factor ≤ 1.0) the fixture originally encoded under the old formula (~13.2 ms/step under `1.1 × 6e-10`). Two corresponding `assert out.parameter_count_estimate == 500_000` assertions updated to `== 50_000`. Math preserves the original semantics; the fixture is no longer over-budget under the new calibration.

**Common — consistency tests (gate for both Parts A and B):**

- [x] Unit test: every flag in §3.2 has the same name and default in both entries (`tests/unit/scripts/test_chain_consistency.py`).
- [x] Per Final Ruling 5 — for this commit, `test_chain_consistency.py` covers **Python-to-Python parser parity only**. Shell-side widening of `_chain_common.sh::parse_chain_args`, the shell-default tests, and three-way (Python ↔ Python ↔ shell) parity assertion are tracked under Commit 13.
- [x] Doc-sync: §3.2, §3.8 already describe this. Commit message references §3.2 (input contract), §3.8 (consistency), and §4.2 (time estimation repair in Part A).

_The two deferred items previously listed here — the `run_workflow` kwargs byte-for-byte snapshot test and the manual `--start_iteration 3` chain-layout sanity check — have been **relocated** to Commit 13 (test checklist) and Commit 13 (smoke tests) respectively, since both depend on the unified `run_chain.sh` runner whose flag-passing they validate. Tracked there._

#### Commit 12 — `feat(inspector): inspect_run_state.py supports chain layout + --next-iter`

**Goal**: Single inspector tool serves both layouts and offers a machine-readable mode for the shell driver.

- [x] Add `--layout {run,chain}` flag (default `run` for back-compat — flips to `chain` in Commit 15).
- [x] Under `--layout chain`, walk `{workspace}/iter_NNN/manifest.json` and validate the referenced `output_path` against `HyperparamTuningOutput`. The {COMMITTED, PARTIAL, CORRUPT, MISSING} predicate matches `core.resume._read_manifest` + `_validate_run_output` (single source of truth — auto-resume in Commit 13 depends on this agreement).
- [x] Add `--next-iter` flag (chain mode only): prints **only** the integer index of the first non-COMMITTED iteration to stdout (1 if empty workspace; `max_seen + 1` if all clean); exit 0; no banner, no table, errors to stderr — suitable for `NEXT=$(...)` shell capture by `run_chain.sh --auto_resume`.
- [x] Detect non-contiguous iters (1 + 3 with no 2) → exit non-zero with stderr message naming the gap. Stdout stays empty in `--next-iter` mode so a stale shell capture cannot accidentally proceed.
- [x] Legacy-layout guard: chain mode calls `core.resume.validate_workspace_layout(workspace)` before walking. Reuses the same helper Phase 6.8 §3.9 wired into `run_exploration_adaptive.py`.
- [x] Enriched human-view table: chain layout populates Model + Best Score columns from the parsed run_output (same shape as the legacy-layout table).
- [x] Unit tests (`tests/unit/scripts/test_inspect_run_state.py`, **11 cases passing**): 3 clean iters → `4`; 2 clean + missing manifest → `3`; 1 clean + failed-status manifest → `2`; 1 clean + malformed-JSON manifest → `2`; empty workspace → `1`; iter_001 + iter_003 gap → non-zero exit + stderr names `iter_002`; legacy `workflow_*.json` triggers guard → non-zero; `--layout run` back-compat regression; default layout resolves to `run`; chain table contains both model_type strings + both best_score values; argparse-level rejection of invalid flag combinations.
- [x] **Live verification gate** against `/home/klz/Data/SIDEREIS_DATA/exploration_phase68_commit11_gate/`: human view shows `iter_001 posenc_causal_dilated_stack COMMITTED -3.221148` + `iter_002 spectral_skip_residual_stack COMMITTED 4.524244`; machine view (`--next-iter`) prints exactly `3` and shell-captures cleanly into a 1-char `$NEXT` variable.
- [x] Doc-sync: §3.4 already describes the contract. Commit message references §3.4.

#### Commit 13 — `feat(chain): unified run_chain.sh --mode {lilab,sdsc} with auto-resume and dry-run`

**Goal**: One intelligent shell orchestrator that subsumes the legacy `run_iteration_chain.sh` (sdsc) and `run_iteration_chain_lilab.sh` (lilab) scripts, drives the full chain loop on top of the Commit 12 inspector, achieves byte-level flag parity with both Python entries, and lets operators preview every command before any sbatch or python call fires.

The plan below is structured as **6 implementation tasks + 3 verification gates** mirroring the Commit 13 directive. Each `[ ]` becomes an `[x]` only when the corresponding artefact is on disk and verified.

##### Task 1 — Consolidation (replace the two legacy scripts)

- [ ] Add `sdsc_submission_scripts/run_chain.sh`, sourcing `sdsc_submission_scripts/_chain_common.sh` for shared parse/build helpers.
- [ ] Mark `run_iteration_chain.sh` and `run_iteration_chain_lilab.sh` as **deprecated stubs** that delegate to `run_chain.sh --mode sdsc` / `--mode lilab` respectively. Print a one-line `DeprecationWarning` to stderr; do not break operator muscle memory mid-flight. Plan removal after the next stable run (tracked in Commit 15).
- [ ] Drop dead code in the legacy scripts that has no analogue in the unified entry; do not port quirks forward.

##### Task 2 — Mode Implementation (`--mode {lilab,sdsc}`, required)

- [ ] Add `--mode {lilab,sdsc}` to `_chain_common.sh::parse_chain_args`. No default — operator must declare. Failing fast here is preferable to defaulting to the wrong host.
- [ ] **`--mode lilab`**: `submit_iteration` runs the resolved Python interpreter as a **foreground subprocess** (`"${PY_CMD[@]}" "${RUNNER}" "${APP_ARGS[@]}"`). Iter N+1 cannot start until iter N's process exits with status 0; on non-zero exit, the chain halts with a clear error.
- [ ] **`--mode sdsc`**: `submit_iteration` runs `sbatch ${SBATCH_ARGS[@]} ${SLURM_SCRIPT} ${APP_ARGS[@]}` and captures the job ID. Iter N+1's submission adds `--dependency=afterany:${PREV_JOB_ID}` so the second job is queued only after iter N reaches any terminal state — even failure — so that operators can post-mortem on disk rather than have a silent gap.

##### Task 3 — Auto-Resume Wiring (this is what Commit 12 was built for)

- [ ] Add `--auto_resume` (default **ON**) and `--start_iter N` (manual override) to `_chain_common.sh::parse_chain_args`. Manual override wins over auto when both are provided.
- [ ] When `--auto_resume` is on, compute `START_ITER` via the Commit 12 inspector:
    ```bash
    NEXT=$(.venv/bin/python scripts/inspect_run_state.py \
              --layout chain --workspace "$WORKSPACE" --next-iter)
    START_ITER=${NEXT:-1}
    ```
    The inspector exits non-zero on legacy-layout detection or non-contiguous chains; propagate that exit code (do **not** ploughed through with a stale `START_ITER`).
- [ ] **Safety guard — refuse stale-fresh start**: if `START_ITER == 1` AND `WORKSPACE` is non-empty (any file or dir at the workspace root), refuse to launch with a clear error: `"workspace not empty — pass --force_fresh to clobber, or --start_iter N to resume."`
- [ ] Add `--force_fresh` to override the guard above. Mutually exclusive with `--auto_resume` — passing both is an operator-error and exits non-zero.
- [ ] If `--auto_resume` returns `START_ITER > NUM_ITERATIONS`, exit cleanly with `"all iters already complete — nothing to do"` (exit 0). Idempotent rerun behaviour is critical for cron-driven chains.

##### Task 4 — Flag Parity & Widening (close the §3.8 three-way contract)

- [ ] Add **all** flags from §3.2 to `_chain_common.sh::parse_chain_args` and propagate them through `build_app_args` with **identical names and defaults** to both Python entries. The §3.2 table is the single source of truth.
- [ ] **`--data_dir` plumbing** (relocated from Commit 11 Part A per Final Ruling 5 — Python-side already wired in `a4238de`/`c38837e`): add `DATA_DIR` to the shell variable set; default to `/home/klz/Data/TIDMAD/` on lilab, the Slurm-host data path on sdsc; emit `--data_dir "${DATA_DIR}"` in `build_app_args`. Closes the v6 Time-Estimation-Repair countermeasure end-to-end (warmup measurement was already wired in Commit 11.2; only the shell trampoline still needed the flag for chain mode).
- [ ] Top-of-file default block in `_chain_common.sh` declares one default per §3.2 flag. Drift between this block and the Python defaults is what the consistency test below catches.

##### Task 5 — Dry-Run Mode (`--dry-run`, default OFF)

- [ ] Add `--dry-run` to `_chain_common.sh::parse_chain_args`.
- [ ] When `--dry-run` is set, `run_chain.sh` walks the full `run_chain` loop (including `build_source_paths`, `build_app_args`, dependency wiring) but **does not call `submit_iteration`**. Instead, for each iter it prints the exact command that *would* have launched:
    - `--mode lilab`: `${PY_CMD[@]} ${RUNNER} ${APP_ARGS[@]}` with every element shell-quoted so a copy-paste reproduces the real launch.
    - `--mode sdsc`: `sbatch ${SBATCH_ARGS[@]} ${SLURM_SCRIPT} ${APP_ARGS[@]}` plus the `--dependency=afterany:$PREV_JOB_ID` line that *would* have been added (using a placeholder like `$JOB_ID_iterNNN` since real job IDs are unavailable in dry-run).
- [ ] Print a chain-header block resolving: workspace, start_iter, num_iterations, mode, Python interpreter (lilab) or partition/time/mem/gpus/cpus (sdsc), and every §3.2 flag value.
- [ ] **Side-effect-free guarantee**: a `--dry-run` invocation never creates `${WORKSPACE}/iter_*` directories, never writes manifests, never invokes `python` or `sbatch`. Exit 0 after the loop completes.

##### Task 6 — Virtualenv Detection (`--mode lilab` only)

The current `run_iteration_chain_lilab.sh:40–44` ignores `$VIRTUAL_ENV` and prefers `uv run python`, then falls back to `python3` (which on this host is Python 3.8 — too old; `CLAUDE.md` mandates `.venv/bin/python`). The unified runner must honour an operator-activated venv first.

- [ ] Detect the Python interpreter for `--mode lilab` in this order:
    1. `$VIRTUAL_ENV/bin/python` — if `$VIRTUAL_ENV` is set and the path is executable.
    2. `${PROJECT_DIR}/.venv/bin/python` — if it exists. (Project default per `CLAUDE.md`.)
    3. `uv run python` — if `uv` is on `$PATH`.
    4. `python3` — last resort, **with an explicit warning** that this may resolve to system Python 3.8.
- [ ] Print the resolved interpreter in the chain header: `Python: /path/to/python (source: VIRTUAL_ENV / project venv / uv / python3)`.
- [ ] **Version guard**: refuse to start (exit non-zero) if the resolved interpreter reports `sys.version_info < (3, 10)`. Implementation: `"${PY_CMD[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'`. Guards against an operator's stale `python3` symlink resolving to 3.8.
- [ ] Pass `$VIRTUAL_ENV` and the resolved `PATH` through to the iter subprocess so nested tools (training subprocess, plugin sandbox) inherit the same environment.
- [ ] **`--mode sdsc` is unchanged**: `submit_one_iteration.slurm` activates `.venv/bin/activate` inside the Slurm job, so the submit host's `$VIRTUAL_ENV` is irrelevant. This commit does not change the SDSC env-resolution path.

---

##### Verification gate A — Three-Way Consistency (extend `tests/unit/scripts/test_chain_consistency.py`)

- [ ] Extend the existing test from Python ↔ Python parity to **three-way Python ↔ Python ↔ shell** parity. The test parses `_chain_common.sh` for the top-of-file default block and the `case` arms of `parse_chain_args`, then asserts that every §3.2 flag has identical name, default, type/nargs, and required-vs-optional across all three sources.
- [ ] Drift on any single property fails the test with a human-readable diff naming the source of disagreement (Python adaptive / Python one-iter / shell).

##### Verification gate B — Kwargs Snapshot (deferred from Commit 11)

- [ ] Construct the same §3.2 flag set on both `run_exploration_adaptive.py` and `run_one_iteration.py` and assert the resulting `run_workflow(...)` kwargs dict is **byte-for-byte identical**, modulo:
    - `run_name` (per-iter `iter_{N:03d}` for the chain-in-process loop on adaptive; the same string on one-iter)
    - `max_iterations` (1 on one-iter; per-iter loop bound on adaptive)
- [ ] Test lives in `tests/unit/scripts/test_chain_consistency.py` next to the three-way test (Gate A); they share fixture infrastructure.

##### Verification gate C — Dry-Run Smoke

- [ ] Invoke `run_chain.sh --dry-run --mode lilab --workspace /tmp/dryrun_ws --num_iterations 3 ...` and assert:
    - 3 iter blocks are printed, each with the correct `--start_iteration {1,2,3}` value;
    - `${WORKSPACE}` (a fresh `/tmp` dir) stays **empty** after the invocation — no `iter_*` dirs, no manifests, no `python` or `sbatch` invocation;
    - exit code is 0.
- [ ] Same for `--mode sdsc`: assert each iter past the first carries a `--dependency=afterany:$JOB_ID_iterNNN` placeholder pointing at the prior iter.

##### Live smoke tests (run before commit)

- [ ] **lilab**: 2-iter chain on synthetic data; both iters complete and write manifests; chain header shows the project `.venv` interpreter.
- [ ] **sdsc**: 2-iter `--dry-run` (`--time 00:05:00`); confirm the second `sbatch` line carries the right dependency placeholder. (A real `sbatch` queue test is operator-driven post-merge.)
- [ ] **Resume**: 3-iter chain on lilab, kill mid-iter-2, rerun the same command — `--auto_resume` should pick up at iter_002 because iter_001's manifest is COMMITTED while iter_002's is missing/PARTIAL.
- [ ] **Manual `--start_iteration 3` sanity** (relocated from Commit 11): pre-populate workspace with iters 1+2; run `python run_exploration_adaptive.py --workspace W --start_iteration 3 ...`; verify the in-process `MODEL_REGISTRY` carries both prior plugins and `get_model_description` resolves prior `model_type`s via `${SIDERIUS_CHAIN_WORKSPACE}`. Human-in-the-loop counterpart to the unit test at `tests/unit/sdsc_submission_scripts/test_run_one_iteration.py::TestRestoreWiring::test_manual_override_start_iteration_3_with_iters_1_and_2_on_disk`.

##### Doc-sync (lands in the same commit)

- [ ] §3.4 (auto-resume) and §3.8 (consistency contract) already describe the design — flip `[ ]` boxes above and add the captured live-smoke evidence (header output snippet, dry-run sample, version-guard rejection example).
- [ ] Update `docs/running_chain_test.md` runbook to reference `run_chain.sh --mode {lilab,sdsc}` as the new operator entry-point and document `--dry-run` + venv detection.
- [ ] Top-of-doc Status line: bump from "Commits 6 → 12 landed" to "Commits 6 → 13 landed".

##### Out of scope (intentionally not in this commit)

- Removal of the deprecated stubs (`run_iteration_chain.sh`, `run_iteration_chain_lilab.sh`) — Commit 15.
- The migration tool referenced in the legacy-guard error message (`scripts/migrate_workspace.py`) — separate future commit.
- V7 pre-flight 5-iter real-LLM run — Commit 14.
- The default flip of `inspect_run_state.py --layout` from `run` → `chain` — Commit 15.

#### Commit 14 — `test(chain): V7 pre-flight simulation — 5-iter local-host real-LLM run`

**Goal**: High-fidelity end-to-end validation that the chain's memory / context / continuity
contracts hold under a real multi-iteration workload before the V7 production launch.
Pseudo-mode tests (Commits 7, 8, 11) prove the wiring; this commit proves the *system
behaviour* — the contract that wiring is supposed to enforce — under real LLM reasoning.

**Scenario**: Run `run_exploration_adaptive.py` for **5 iterations** on the local host with
real OpenAI calls and minimal compute, completing in **30–45 minutes** wall-time.

**Launch parameters** (run name `phase68_v7_preflight_<YYYYMMDD>`):

- `--max_iterations 5 --max_rounds 1 --max_proposal_attempts 1 --max_impl_attempts 1`
- `--is_trial --trial_strategy snapshot`
- `--no-force_formal_round` — last round honours the planner so the 0.01 portions actually
  take effect on the final round. The planner prompt also tells the LLM that formal mode is
  OPTIONAL on the last round. Without this flag, the production contract forces formal mode
  at portion=0.1 / train_portion=1.0 (planner is told formal is MANDATORY *and* the post-LLM
  override flips ``is_trial=False``) and the run cannot finish in 30–45 min.
- `--trial_portion 0.01 --train_portion 0.01 --eval_portion 0.01`
- `--max_epochs 1`
- `--trial_time_budget_minutes 15 --formal_time_budget_minutes 15` — headroom for sandbox
  compile + scoring; the Commit 11 gate test that produced this design used 5 min and
  exhausted all attempts on the time gate.
- `--trial_vram_budget_gb 8 --formal_vram_budget_gb 8`
- `--llm_config llm_configs/openai_tiered_v1.json` — real OpenAI calls (gpt-5.4 tiered).
- `--advice tuner_advice/exploration_adaptive_v1.json`

**Success criteria** (all three must hold):

- [ ] **Memory continuity** — `psutil` RSS sampled at the start of every iter via the
  existing `[MEM] scope=workflow iter=N phase=start` log line; assert
  `RSS(iter_5_start) ≤ 1.1 × RSS(iter_1_start)`. Validates that `del + gc.collect` in
  §2.3 / Commit 9 actually clears across the long span; a regression here means workspace
  state has accumulated tensors / module state across iters.
- [ ] **Context stability** — `[PROMPT_SIZE] planner: N chars` logged at every round; the
  sequence `planner@iter_1 … planner@iter_5` must show the bounded-growth signature: the
  delta from iter_4 → iter_5 must be within ±5 % of the iter_3 → iter_4 delta (growth has
  flattened). Validates the `_truncate_memory_history` sliding window from §2.4 / Commit 10
  is effective once the buffer is full.
- [ ] **Reasoning continuity** — the iter_5 proposer's `causal_reasoning` LLM output must
  reference at least one concrete discovery from iter_1 or iter_2 (architecture name,
  hyperparameter range, or specific bottleneck). Validates that the truncated memory_history
  still preserves long-range signal through the condensation pass — i.e. the sliding window
  is bounded but not amnesic.

**Artefacts**:

- `tests/integration/workflows/test_v7_preflight_chain.py` — `@real_run`-marked Tier 3
  driver that launches the run, parses logs and manifests, and asserts the three criteria.
  Skips by default when `OPENAI_API_KEY` is unset; opt-in via
  `pytest -m real_run tests/integration/workflows/`.
- A captured workspace lives at
  `/home/klz/Data/SIDEREIS_DATA/exploration_phase68_v7_preflight_<YYYYMMDD>/`. The test
  reads this workspace's logs and manifests rather than re-launching the chain on every
  pytest invocation (the run is expensive); re-recording is a manual step documented in
  the test docstring.

**Hostile-case sanity** (cheap, runs every CI):

- [ ] Pseudo-corrupt iter_001's `run_output_iter_001.json` in a fixture workspace; verify
  iter_002 refuses to start with a clear error rather than silently chaining off an
  incomplete output. _Unit-style, no LLM calls._

**Doc-sync**: §3.5 (this section) updated with the captured run's path, wall-time, and the
three measured numbers (Δ-RSS %, planner prompt-size series by iter, proposer continuity
excerpt) once green.

#### Commit 15 — `docs(chain): update runbook + retire run_exploration_adaptive.py from "primary" status`

**Goal**: Operator-facing documentation reflects the new default.

- [ ] Update `docs/running_chain_test.md` to recommend `run_chain.sh --mode lilab` as the default lilab runner for any `max_iterations >= 2`.
- [ ] Demote `run_exploration_adaptive.py` to "dev/debug" status in the doc (kept for short single-process iteration cycles).
- [ ] Update `MEMORY.md` if `run_exploration_adaptive.py` is referenced as primary.
- [ ] Add a "When to use which runner" decision table.
- [ ] Doc-sync: this commit IS the doc-sync; no separate design-doc edit needed.

### 3.6 Out of scope (deferred, not abandoned)

These were present in Part 2's design but are deliberately excluded from Task 2 under the chain-first plan:

- **Mid-iter checkpoint**: still costs up to one full iter on SIGKILL. Address only if a single iter regularly costs > 6 hours.
- **Variable-by-variable in-memory rebuild** (Part 2 §2.5): `run_exploration_adaptive.py` now achieves resume via the **chain workspace layout** + `restore_prior_state` (see Commit 11 Part B), not via in-process state-pickling. The Part 2 design is preserved as history but no longer planned.
- **Cross-host portability**: hardware_context is host-specific; the plugin Python files might depend on host-specific module paths. Resume is "same host, post-SIGKILL", not "migrate to new host" — same contract as Part 2 §2.8.

### 3.7 Test strategy summary

| Layer | Test | Commit | Tier |
|---|---|---|---|
| Unit | `_add_plugin_to_registries` updates all four registries | 6 | unit |
| Unit | `restore_prior_state` against synthetic 3-iter fixture (clean / partial / corrupt / missing-plugin / non-contiguous) | 7 | unit |
| Unit | Probe cleanup: mock sequential model, verify RSS delta < 500 MB and `gc.collect` call count ≥ 2 | 9 | unit |
| Unit | Probe regression: existing `test_evaluate_vram_skill.py` still passes | 9 | unit |
| Unit | `_truncate_memory_history`: 10 records → 3 full + 7 condensed, correct keys | 10 | unit |
| Unit | `model_knowledge_cache` cap: 8 entries → top-5 by score | 10 | unit |
| Unit | `_truncate_description`: 7KB → 1500 chars + marker | 10 | unit |
| Unit | §3.8 consistency contract — every flag has identical name + default across both Python entries (`tests/unit/scripts/test_chain_consistency.py`, Python-to-Python parity) | 11 | unit |
| Unit | CLI surface of `run_one_iteration.py` matches `run_exploration_adaptive.py` — snapshot of `run_workflow` kwargs is byte-for-byte identical (modulo `run_name`/`max_iterations`) | 13 | unit |
| Unit | §3.8 consistency contract extended to three-way (Python ↔ Python ↔ `_chain_common.sh`) once shell entry widened | 13 | unit |
| Unit | `inspect_run_state.py --next-iter` against fixtures | 12 | unit |
| Unit | `--dry-run` never touches the workspace and prints the right per-iter command | 13 | unit |
| Unit | venv detection picks `$VIRTUAL_ENV` first, project `.venv` second, `uv` third, `python3` last (with warning) | 13 | unit |
| Unit | Workspace layout guard: legacy layout detected → clear error with migration hint | 11 | unit |
| Tier 3 (`@real_run`) | V7 pre-flight: 5-iter local-host real-LLM chain; assert `RSS(iter_5) ≤ 1.1 × RSS(iter_1)`, planner `[PROMPT_SIZE]` flattens by iter_4, iter_5 proposer references iter_1–2 discoveries | 14 | integration (real) |
| Unit | Pseudo-corrupt iter_001 `run_output_iter_001.json` → iter_002 refuses to start with a clear error | 14 | unit |
| Smoke | 2-iter chain on lilab; manual SIGKILL mid-iter-2; rerun same command; verify iter_001 preserved | 14 | smoke |
| Smoke | 2-iter sbatch chain on SDSC; verify dependency wiring via `squeue` | 14 | smoke |

### 3.8 Consistency contract — flag parity across all three entries

Each flag in §3.2 must have **identical name and default value** across the three operator-facing entries:

1. `run_exploration_adaptive.py` (in-process Python entry)
2. `sdsc_submission_scripts/run_one_iteration.py` (per-iter Python entry, called by the chain)
3. `sdsc_submission_scripts/run_chain.sh` (shell entry, passes through to entry 2)

This is a hard test gate — Commit 11's "every flag in §3.2 has the same name and default" unit test enforces it programmatically. Drift introduces silent behaviour differences between operator-equivalent commands and is the single biggest predictable source of "it worked on lilab but not on SDSC" bugs.

#### The contract

For each row in the §3.2 table:

| Property | Required across all three entries |
|---|---|
| Flag name (long form) | identical (e.g. `--trial_time_budget_minutes`, never `--trial-time-budget-minutes` in one and `--trial_time_budget_minutes` in another) |
| Default value | identical (e.g. `--max_rounds` defaults to 3 in all three; `--trial_vram_budget_gb` defaults to `None` in all three) |
| Type / nargs | identical (e.g. `--target_files` is `int +` in all three) |
| Whether it can be omitted | identical (required vs optional) |

The shell entry's `_chain_common.sh::parse_chain_args` does not need to know how the underlying Python uses the value — it just needs to forward the value through `build_app_args` to `run_one_iteration.py`. A flag that affects only `run_workflow` internals still appears in all three layers so operators don't have to remember which layer accepts which.

#### Mechanism

The unit test at `tests/unit/scripts/test_chain_consistency.py` (new, Commit 11) does the following:

1. Parses the §3.2 table from this design doc into a list of expected flags.
2. Imports `run_exploration_adaptive.py:parse_args` and `run_one_iteration.py:main`'s argparse setup; reflects on the resulting `ArgumentParser` to extract `(name, default, type, nargs, required)` per flag.
3. Reads `_chain_common.sh` line-by-line, parsing the `case` arm in `parse_chain_args` and the default-assignment block at the top of the file.
4. Asserts that all three sources agree on every property for every §3.2 flag. Reports diffs in human-readable form.

This test runs in the standard unit-test suite, so any drift is caught at PR time, not at smoke-test time.

#### Default-value source of truth

When a default needs to change in the future, the order of operations is:

1. Update the §3.2 table in this doc.
2. Update `run_exploration_adaptive.py`'s `argparse` default.
3. Update `run_one_iteration.py`'s `argparse` default.
4. Update `_chain_common.sh`'s top-of-file default.
5. Run the consistency test; commit only when green.

The doc table is **authoritative** — implementations that disagree with the doc are bugs, not "configuration", per `feedback_plan_doc_sync.md`.

#### Allowed exceptions

The following flags are **layer-specific** and exempt from the consistency contract:

- `--mode {lilab,sdsc}` — shell only (Python entries don't have a mode).
- `--partition`, `--time`, `--mem`, `--gpus`, `--cpus` — Slurm-only, accepted but ignored under `--mode lilab`.
- `--dry-run`, `--auto_resume`, `--force_fresh`, `--num_iterations`, `--start_iter` — shell-orchestration flags. The Python `--start_iteration` (per-invocation) and the shell `--start_iter` (chain-level start point) serve different scopes; the unit test must permit the asymmetry but verify the spelling difference is intentional.
- Slurm-only env paths inside `submit_one_iteration.slurm` — not operator-facing.
- **`--run_name`** (Commit 11, Option β) — required on `run_exploration_adaptive.py` only. Used for the launch banner label and for deriving the default `--workspace` path (`/home/klz/Data/SIDEREIS_DATA/exploration_{run_name}`). In chain mode (`run_one_iteration.py` and `run_chain.sh`), per-iter identity is mechanically synthesised as `iter_{N:03d}` from the iteration index, so a run-level name carries no information for the runner and is omitted.
- **`--workspace`** (Commit 11, Option β) — required on `run_one_iteration.py` (chain) because there is no `--run_name` from which a default could be derived. Optional on `run_exploration_adaptive.py`, where it is derived from `--run_name` when omitted. The same workspace value is shared across every iter of a chain.
- **`--source_paths`** (Commit 11) — deprecated alias of `--seed_paths` on both Python entries. Parses to `dest="source_paths_legacy"` and is collapsed onto `args.seed_paths` after parsing with a `DeprecationWarning`. The canonical name `--seed_paths` is the one enforced by the consistency contract; the legacy alias is exempt because it exists solely for one-release back-compat.
- **`--iteration`** (Commit 8) — deprecated alias of `--start_iteration` on `run_one_iteration.py`. Same dest-rename + post-parse collapse pattern as `--source_paths` above; will be removed in a future commit.

The exemption list is canonical: any flag not on it must satisfy the contract.

### 3.9 Workspace layout guard — legacy detection and migration

The chain workspace layout (`{workspace}/iter_NNN/iteration_001/{model}/`) is structurally different from the legacy in-process layout (`{workspace}/{run_name}/iteration_NNN/{model}/`). Both `run_exploration_adaptive.py` (Commit 11 Part B) and `run_chain.sh` (Commit 13) write the chain layout exclusively. A workspace created by v5 or v6 runs (which used `run_exploration_adaptive.py` in single-process mode) has the legacy layout.

**The problem**: if an operator points `--workspace` at a legacy workspace, the chain will create `iter_001/` alongside the existing `{run_name}/iteration_001/`, silently producing a workspace with two incompatible layouts. `restore_prior_state` will not find prior iter data (it looks for `iter_NNN/manifest.json`), and the chain will start from scratch, discarding all prior work.

**The guard**: both Python entries (`run_exploration_adaptive.py`, `run_one_iteration.py`) and the shell entry (`run_chain.sh`) must detect legacy layout and refuse to start.

#### Detection heuristic

A workspace has legacy layout if **any** of these conditions hold:

1. `glob("{workspace}/*/iteration_001/")` matches (a `{run_name}/iteration_001/` subtree exists).
2. `glob("{workspace}/workflow_*.json")` matches (workflow summary from the in-process runner).
3. `glob("{workspace}/memory_trace.jsonl")` matches AND no `iter_001/` directory exists.

These patterns do not overlap with chain layout artifacts (`iter_NNN/`, `manifest.json`).

#### Error message

```
ERROR: Legacy workspace layout detected at {workspace}.
  Found: {matched_pattern}

This workspace was created by the in-process runner (v5/v6 era).
The chain runner uses a different layout ({workspace}/iter_NNN/).

To proceed:
  (a) Use a new --workspace path for the chain run.
  (b) To resume from legacy results, use the migration tool:
      python scripts/migrate_workspace.py --from {workspace} --to {new_workspace}
      (migration tool planned — not yet implemented)
```

#### Implementation location

- **Python**: `core/resume.py:validate_workspace_layout(workspace)` — called by both `restore_prior_state` (on iter > 1) and directly by the runner entry points (on iter == 1, before any work begins).
- **Shell**: `run_chain.sh` calls `inspect_run_state.py --layout chain --check-legacy` which delegates to the same Python function.

#### Migration tool (deferred)

`scripts/migrate_workspace.py` is **not** in scope for Task 2. The guard is sufficient: operators either start fresh or wait for the tool. Documenting the planned tool in the error message avoids confusion about whether migration is possible.

---

## Part 4 — v6 Countermeasures (Post-Mortem Findings)

**Trigger**: v6 sanity run report at `reports/v6_pr63_20260428.md` (2026-04-28) identified three failure modes not addressed by Part 1 (memory hygiene, shipped in PR #63) or Part 3 (chain-first resume). These are "physics-level" failures — they would recur in chain mode because the root causes are inside the per-iteration Python, not in the orchestration layer.

**Relationship to Part 1**: Part 1 §1.4–1.5 diagnosed and fixed the **scoring subprocess fork amplification** (v5 OOM root cause). The v6 OOM is a **completely different mechanism**: the parent process itself balloons to 35.6 GB during the VRAM/time probe for a model with sequential Python for-loops. The `spawn` fix from PR #63 is orthogonal.

**Relationship to Part 3**: the chain-first design gives each iteration a fresh process (structural memory floor), which mitigates Part 1's per-iteration leak. It does **not** help with Part 4's failures, which are intra-iteration: the probe OOM happens within a single `run_workflow(max_iterations=1)` call; the time estimation error happens within the same call; and the LLM context growth happens within a single tuner `run()`.

### 4.1 Probe Memory Safety (P0) — Autograd Tape Explosion

**Failure**: `explore_novel_v6_0427` iter_002 (`dual_selective_ssm_head`) killed by Linux OOM at 35.6 GB RSS.

**Mechanism**: The VRAM pre-flight probe (`evaluate_vram_skill/structural_probe.py:probe_activation_footprint`) runs the model in **training mode on CPU** to measure what PyTorch would allocate on GPU. For models with vectorised ops (convolutions, FFTs), this is cheap — hundreds of autograd graph nodes, sub-GB host memory. For models with **Python-level sequential for-loops** (this SSM model scans 40K timesteps × 4 blocks × 2 directions = 320K iterations), every loop iteration creates multiple tensors retained by the autograd engine. The result is ~3.2 million autograd nodes and ~15-18 GB of host-side graph metadata — for a model with only 195K parameters.

The code compounds this by running **three consecutive forward passes** with no cleanup:

```
structural_probe.py:261  probe_autograd_tape()        ← builds the massive graph
structural_probe.py:265  probe_forward_layers(model)  ← another full forward, old graph still live
structural_probe.py:269  model(input_sample)           ← third forward, previous two still live
```

Then `wrapper.py` builds **two more model instances** (lines 429, 433) for inference-mode probing without freeing the first model. The batch resolver runs up to 7 additional inference probes.

**Why Part 1's `gc.collect()` doesn't help**: the autograd graph is not cyclic garbage — it is live state retained by PyTorch's C++ engine until `backward()` is called or the loss tensor is deleted. `gc.collect()` cannot reclaim it. The fix requires explicit `del` of the loss tensor and `gc.collect()` between passes to release the C++ graph.

**Fix** (Commit 9):
1. Insert `del` + `gc.collect()` between the three forward passes in `probe_activation_footprint`.
2. Insert `del model; gc.collect()` in `wrapper.py` before constructing inference-mode model instances.
3. Add a diagnostic host-RSS delta check (warning, not gate) to catch future sequential-scan models early.

**Expected impact**: peak RSS during the SSM probe drops from ~35 GB to ~18 GB (one forward pass at a time instead of three overlapping). This is still high for a 195K-param model, but survivable on a 64 GB host. A harder gate (e.g., refusing to probe models with > N sequential steps) is deferred — the cleanup fix is sufficient and doesn't require model introspection.

### 4.2 Time Estimation Repair (P0) — Warmup Plumbing + Static Formula Patch

**Failure**: every v6 experiment used the static formula, which underestimates training time by 5-10x for novel architectures. Each exploit iteration took 5-7 hours instead of the expected 1-2 hours.

**Mechanism**: the time estimator has two paths:
- **Warmup path** (`_measure_ms_per_step`): runs 10 real training steps on GPU, measures actual ms/step. **Accurate to ±10%.**
- **Static fallback** (`_static_ms_per_step`): `ms/step = params × seg × bs × 6e-10`. **Architecture-blind, no fixed-overhead term, 5-10x wrong.**

The warmup path is gated on `data_dir` being non-None. In production, `data_dir` is never passed:

```
_chain_common.sh  →  does not pass --data_dir
run_one_iteration.py  →  does not accept --data_dir
run_workflow()  →  receives data_dir=None
time skill  →  logs "no data_dir; falling back to static formula"
```

The warmup infrastructure exists and works correctly. It was never wired into the production chain.

**Why the static formula is so wrong**:

1. **Architecture-blind**: treats every parameter as costing equal FLOPs. Dilated convolutions with irregular memory access, SSM sequential scans, and multi-rate upsampling all cost far more wall-clock per parameter than dense linear layers.
2. **No fixed-overhead term**: each training step has ~1-3 ms of fixed cost (CUDA kernel launch, synchronization, DataLoader fetch). At `seg_size=2000`, fixed overhead dominates compute for small models.
3. **Coefficient too low**: `6e-10` was calibrated on seed models (punet, wavenet) which have efficient GPU utilisation. Novel architectures are 3-5x less efficient per FLOP.

**Fix** (Commit 11 Part A, already integrated):
1. Wire `--data_dir` through `run_one_iteration.py` → `run_workflow()` → `HyperparamTuningInput` → time skill.
2. Wire `--data_dir` through `_chain_common.sh` → `build_app_args`.
3. Raise `_STATIC_MS_PER_FLOP` from `6e-10` to `3e-9`.
4. Add a minimum ms/step floor of 2.0 ms (fixed overhead).
5. Raise `SAFETY_MULTIPLIER` from `1.1` to `2.0`.

**The calibration system** (`agent/skills/evaluate_time_skill/calibration.py`) is also dead code in production — `k` correction only applies to warmup-sourced estimates, and the static fallback always uses `k=1.0`. Once `--data_dir` is wired, calibration will activate naturally. No separate fix needed.

**Expected impact**: with warmup active, estimates should be ±10-20% of actual (validated in v4 lilab runs where warmup was triggered manually). The static formula patches are a safety net for environments where `data_dir` is unavailable — they bring the error from 5-10x down to ~2x (still wrong, but survivable with the raised safety multiplier).

### 4.3 LLM Context Windowing (P1) — Prompt Size Management

**Failure mode**: not an OOM — a quality and cost degradation. Three growth vectors in the LLM prompt construction pipeline:

| Growth vector | File | Observed size | Growth rate |
|---|---|---|---|
| `memory_history` (tuner planner) | `agent/prompts.py:742` | 50-100KB at 10 rounds | linear in rounds |
| `model_knowledge_cache` (interpreter → proposer) | `InterpretationOutput` | 352KB by iter 9 (v4) | linear in distinct models |
| `model_descriptions` (proposer) | `ml_model_proposal_agent.py:615` | 7KB per model | linear in distinct models |

**Why this matters for chain mode**: a 20-iteration chain with 3 rounds/iter will accumulate 60 round records in `memory_history` and 20+ entries in `model_knowledge_cache`. The proposer prompt could exceed 500KB — well past the point where LLM reasoning degrades. Token cost also grows linearly.

**Fix** (Commit 10):

**Sliding window for `memory_history`**:
- Last 3 round records: kept verbatim (full `params`, `score_table`, `loss_history`, `memory` block).
- Older records: condensed to `{exp_id, round, status, score, hypothesis, conclusion}`.
- Rationale: the planner needs recent full context (what was tried, what worked, why) and older summary context (what directions have been explored, rough score landscape). The condensed form retains the planner's ability to avoid repeating old experiments while cutting token count 80-90% for old records.

**Model knowledge cache cap**:
- Retain top-5 models by most recent score + the current iteration's model.
- Evict the rest. The knowledge for evicted models is still on disk in the `interpretation_*.json` files — it can be reloaded if the model type reappears in a future iteration.
- Rationale: 5 models × ~35KB = ~175KB, bounded. Without the cap, 20 iterations could accumulate 700KB+.

**Model descriptions truncation**:
- Truncate each model description to 1500 characters in the proposer prompt.
- The full description remains in the markdown file on disk and in the `ModelRunSummary` — only the prompt copy is truncated.
- Rationale: the proposer needs the architectural concept and key equations, not the full implementation notes. 1500 chars is ~375 tokens — enough for a paragraph of design rationale.

**Prompt size diagnostic**:
- Log `[PROMPT_SIZE] {label}: {N} chars` at each LLM call entry point.
- No gating, no automatic truncation beyond the mechanisms above. This gives operators visibility into prompt growth without adding complexity.

### 4.4 v6 Countermeasures — commit map

| Commit | Title | Priority | Fixes |
|---|---|---|---|
| 9 | `fix(probe): memory-safe structural probe` | **P0** | §4.1 — autograd tape explosion |
| 10 | `fix(prompts): sliding-window memory_history + context caps` | **P1** | §4.3 — LLM prompt growth |
| 11 Part A | `feat(chain): ... + time estimation repair` | **P0** | §4.2 — `--data_dir` plumbing + static formula patch |

Commits 9 and 10 are independent of the chain infrastructure (11-15) and can ship as separate PRs. Commit 11 Part A bundles the time estimation repair with the CLI unification because `--data_dir` is a new CLI flag that must satisfy the §3.8 consistency contract across all three entry points.

### 4.5 Verification plan

After Commits 9-11 land:

1. **v7 sanity run — explore mode**: launch with a model known to produce sequential-scan architectures (use `explore_novel` advice with `minimum_boldness=0.7` to encourage novel proposals). Verify:
   - No HOST_OOM during VRAM probe (RSS delta logged, < 8 GB).
   - Time estimates within 2x of actual (warmup active, logged as `ms_source=real_dataset_warmup`).
   - Prompt sizes logged and bounded.
2. **v7 sanity run — exploit mode**: launch 3-iter chain with `formal_time_budget_minutes=60`. Verify:
   - Iterations complete within budget (no 5-7 hour iters).
   - Memory history stays bounded in tuner prompts (check `[PROMPT_SIZE]` logs).
3. **Regression check**: all existing unit + pseudo-integration tests green.
