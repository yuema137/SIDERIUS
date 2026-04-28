# Phase 6.8 — Orchestrator Memory Hygiene & Run Resume

**Status**: Task 1 (memory hygiene) shipped in PR #63. Task 2 (resume) pivoted on 2026-04-27 to a chain-first design — see Part 3.
**Driver**: v5 sanity-run host-OOM kill of `explore_novel_v5_0426` PID 4142820 at 2026-04-27 00:46:42 (kernel: 23.5 GB anon-RSS, total-vm 41.0 GB).
**Scope**: Two parallel work streams — (1) understand and stop the parent-process memory growth that produced the OOM; (2) make any run resumable from disk artifacts after `SIGKILL`.

> **Reading order**: Part 1 (memory hygiene, shipped) → Part 2 (in-process resume design, **superseded**) → Part 3 (chain-first pivot, **active plan**). Part 2 is preserved as design history; the active implementation plan with commit checklists is Part 3.

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

Each commit ships its own design-doc update (per `feedback_plan_doc_sync.md`). Commits 6–8 are gated on Tier-1 / pseudo-mode tests passing locally before push. The chain commits (10–13) don't need to land in one PR — small wave of 3 PRs is fine.

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
- [x] Integration test: drive `restore_prior_state` after running a real 2-iter chain (use pseudo-mode if available) → verify `MODEL_REGISTRY` contains both iters' plugin classes. _High-fidelity 2-iter pseudo-integration test in `TestPseudoIntegrationTwoIterChain` uses real plugin .py files, verifies all four registry surfaces incl. bare-name mirror. The full run_workflow→manifest→restore loop is still scheduled for Commit 12._
- [ ] Doc-sync: §3.3 already describes this. Commit message references §3.3.

#### Commit 8 — `feat(chain): run_one_iteration.py calls restore_prior_state + --start_iteration`

**Goal**: Chain runner is correct on iter > 1 even on a fresh run (not just resume). Surface a manual-override flag for operators who bypass the shell auto-detection.

- [ ] In `sdsc_submission_scripts/run_one_iteration.py:main()`, replace the bare `resolve_source_paths(args.source_paths)` call with `restore_prior_state(args.workspace, args.start_iteration, seed_paths)`.
- [ ] **Rename** `--iteration` → `--start_iteration` (positional meaning unchanged: which iter this invocation runs). Keep `--iteration` as a deprecated alias for one release; emit DeprecationWarning when used. The new name is consistent with `run_exploration_adaptive.py` (Commit 9) and with `run_chain.sh --start_iter`.
- [ ] When `--start_iteration > 1`, restore is triggered automatically — no separate `--resume` flag needed.
- [ ] Pass `state.resolved_source_paths` to `run_workflow`.
- [ ] Print `[CHAIN] Restored N prior plugin(s) from iters [...]` in the startup banner.
- [ ] On `--start_iteration == 1`, `restore_prior_state` returns `seed_paths` verbatim; verify no spurious behaviour.
- [ ] Integration test: spin up a 2-iter chain on synthetic data; manually delete the iter_001 plugin file; rerun iter_002; verify the warning is emitted but the iter still runs (memory_history is built from JSON).
- [ ] Manual-override test: run `python run_one_iteration.py --workspace W --start_iteration 3 ...` against a workspace with iters 1+2 already on disk; verify it skips auto-detect and runs iter 3 directly.
- [ ] Doc-sync: §3.3 already describes this. Commit message references §3.3 and §3.4.

#### Commit 9 — `feat(chain): unify CLI surface across run_one_iteration.py and run_exploration_adaptive.py`

**Goal**: Input contract parity per §3.2. Both Python entries accept the same flag set with identical names and defaults. `run_exploration_adaptive.py` gains `--start_iteration N` and converges on the chain workspace layout when N > 1.

**Part A — `run_one_iteration.py` flag widening:**

- [ ] Add flags listed in §3.2 table that are missing today: `--llm_config`, `--advice`, `--target_files`, `--sampling_seed`, `--exploration_mode`, `--minimum_boldness`, `--debug_dump_prompts`, `--max_impl_attempts`, `--trial_time_budget_minutes`, `--formal_time_budget_minutes`, `--data_dir`, `--trial_vram_budget_gb`, `--formal_vram_budget_gb`, `--attempts_per_round`, `--attempts_per_formal_round`, `--max_fail_rounds`.
- [ ] Switch `--max_rounds` default from 20 to 3 (sync with adaptive).
- [ ] When `--llm_config` is provided, build `WorkflowLLMConfig.from_json`. Keep `--llm_model` as deprecated fallback for one release; emit DeprecationWarning if used without `--llm_config`.
- [ ] Switch `--human_advice_file` schema from 5-key (interpret/propose/implement/validate/tune) to adaptive's 4-key (propose/implement/tune/mindset). Tolerate both schemas during transition (load both; missing keys are None).
- [ ] Pass every new flag through to `run_workflow(...)`.

**Part B — `run_exploration_adaptive.py` adopts `--start_iteration N` + chain workspace layout:**

This is the **convergence step** that makes the two Python entries truly equivalent. After this commit, `run_exploration_adaptive.py` is a "chain-in-one-process" runner: it loops over `run_workflow(max_iterations=1, run_name=f"iter_{N:03d}", ...)` calls, writing each iter to the chain workspace layout (`{workspace}/iter_NNN/`), exactly like the SDSC/lilab chain — minus the per-iter subprocess fork.

- [ ] Add `--start_iteration N` (default 1).
- [ ] When `N > 1`, call `restore_prior_state(workspace, N, seed_paths)` before entering the iter loop. Same trigger semantics as `run_one_iteration.py`.
- [ ] Refactor the in-process iter loop: replace the single `run_workflow(max_iterations=20, ...)` call with `for ITER in range(start_iter, max_iterations + 1): run_workflow(max_iterations=1, run_name=f"iter_{ITER:03d}", ...)`.
- [ ] Each iter call uses `source_paths=state.resolved_source_paths` (initially seeds + restored prior outputs); after each iter completes, append the new manifest's output_path to the list for the next iter (mirrors what the shell chain does between sbatch jobs).
- [ ] Write `manifest.json` per iter (same format as `run_one_iteration.py:write_manifest`) so a workspace produced by `run_exploration_adaptive.py` is interoperable with `run_chain.sh`'s auto-resume.
- [ ] **Behaviour change to flag in commit message**: workspace layout for `run_exploration_adaptive.py` now matches the chain (`{workspace}/iter_NNN/iteration_001/{model}/`) instead of the legacy `{run_dir}/{run_name}/iteration_NNN/{model}/`. Old workspaces from prior runs are not migrated automatically; operators rerun fresh or use the chain runner directly.
- [ ] Workspace-layout guard: if `--workspace` already contains a legacy-layout directory (`{run_name}/iteration_NNN/...` siblings), exit with an error pointing operators at the migration note above.

**Common — consistency tests (gate for both Parts A and B):**

- [ ] Unit test: snapshot the kwargs `run_workflow` receives from each Python entry. Construct the same flag set on both (`run_exploration_adaptive.py` and `run_one_iteration.py`) and assert the resulting `run_workflow` call is byte-for-byte identical (modulo `run_name` and `max_iterations`, which are per-iter for the chain-in-process loop).
- [ ] Unit test: every flag in §3.2 has the same name and default in both entries.
- [ ] Manual-override test (Part B): run `python run_exploration_adaptive.py --workspace W --start_iteration 3 ...` against a workspace with iters 1+2 in chain layout; verify iter 3 starts in-process with `MODEL_REGISTRY` carrying both prior plugins.
- [ ] Doc-sync: §3.2, §3.8 already describe this. Commit message references §3.2 (input contract) and §3.8 (consistency).

#### Commit 10 — `feat(inspector): inspect_run_state.py supports chain layout + --next-iter`

**Goal**: Single inspector tool serves both layouts and offers a machine-readable mode for the shell driver.

- [ ] Add `--layout {run,chain}` flag (default `run` for back-compat).
- [ ] Under `--layout chain`, walk `{workspace}/iter_NNN/iteration_001/{model}/run_output_iter_NNN.json` (run_name varies per iter as `iter_{N:03d}`).
- [ ] Add `--next-iter` flag: prints only the integer index of the first non-COMMITTED iteration to stdout (1 if no committed iters); exit 0; no other output.
- [ ] Detect non-contiguous iters (1 + 3 with no 2) and exit non-zero with a clear error to stderr.
- [ ] Unit test: chain layout with 3 clean iters → `--next-iter` prints `4`. With 2 clean + 1 partial → prints `3`. With 1 + 3 missing 2 → exits non-zero.
- [ ] Doc-sync: §3.4 already describes this. Commit message references §3.4.

#### Commit 11 — `feat(chain): unified run_chain.sh --mode {lilab,sdsc} with --dry-run and venv detection`

**Goal**: Single shell entry point replaces `run_iteration_chain.sh` and `run_iteration_chain_lilab.sh`. Operators can preview every command (`--dry-run`) and the lilab path always uses the project virtualenv.

**Core unification:**

- [ ] Add `sdsc_submission_scripts/run_chain.sh` (or `scripts/run_chain.sh`) sourcing `_chain_common.sh`.
- [ ] Add `--mode {lilab,sdsc}` (required); switches the body of `submit_iteration` between foreground subprocess and `sbatch + afterany`.
- [ ] Add all flags from §3.2 to `_chain_common.sh::parse_chain_args` and propagate to `build_app_args` with **identical names and defaults** to both Python entries (see §3.8 consistency contract).
- [ ] Add `--auto_resume` (default ON) and `--start_iter N` (manual override) to `_chain_common.sh`.
- [ ] Add `--force_fresh` to override the "refuse to clobber non-empty workspace" guard.
- [ ] If `--auto_resume` and `inspect_run_state.py --next-iter` returns N > NUM_ITERATIONS, exit cleanly with a "nothing to do" message.
- [ ] Mark `run_iteration_chain.sh` and `run_iteration_chain_lilab.sh` as deprecated (one-line stub that delegates to `run_chain.sh --mode ...`); plan removal after the next stable run.

**`--dry-run` flag (new):**

- [ ] Add `--dry-run` to `_chain_common.sh::parse_chain_args` (default OFF).
- [ ] When `--dry-run` is set, `run_chain.sh` runs through the full `run_chain` loop including `build_source_paths` + `build_app_args` for every iter, but **does not call `submit_iteration`**.
- [ ] Instead, for each iter it prints the **exact command** it would have launched. For `--mode lilab`, this is `${PY_CMD[@]} ${RUNNER} ${APP_ARGS[@]}` with all elements quoted. For `--mode sdsc`, it is `sbatch ${SBATCH_ARGS[@]} ${SLURM_SCRIPT} ${APP_ARGS[@]}` plus the `--dependency=afterany:$PREV_JOB_ID` line that would have been added (using a placeholder like `$JOB_ID_iterNNN` for the dependency target since real job IDs are unavailable in dry-run).
- [ ] Print the resolved values of: workspace, start_iter, num_iterations, mode, py interpreter (lilab), partition/time/mem/gpus/cpus (sdsc), every §3.2 flag.
- [ ] Exit 0 after the loop completes; do not write manifests, do not create iter dirs, do not call sbatch.
- [ ] Unit test: invoke `run_chain.sh --dry-run --workspace /tmp/dryrun_ws --num_iterations 3 ...` and assert the printed commands include the expected `--start_iteration` value per iter and the right dependency wiring (sdsc).
- [ ] Behavioural test: a `--dry-run` invocation never creates `${WORKSPACE}/iter_*` directories, never calls `python` or `sbatch`. Verify by running into a fresh `/tmp` dir and asserting it stays empty.

**Active virtualenv detection (lilab mode):**

The current `run_iteration_chain_lilab.sh:40–44` ignores `$VIRTUAL_ENV` and prefers `uv run python` then falls back to `python3` (which on this host is Python 3.8 — too old; `CLAUDE.md` mandates `.venv/bin/python`). The unified `run_chain.sh --mode lilab` must use the active venv if one is set, otherwise fall back to the project venv at `${PROJECT_DIR}/.venv/bin/python`.

- [ ] In `run_chain.sh`, detect the Python interpreter for `--mode lilab` in this order:
    1. `$VIRTUAL_ENV/bin/python` — if `$VIRTUAL_ENV` is set and that path is executable. (Honours an operator-activated venv.)
    2. `${PROJECT_DIR}/.venv/bin/python` — if it exists. (Project default per `CLAUDE.md`.)
    3. `uv run python` — if `uv` is on `$PATH`.
    4. `python3` — last resort, **with an explicit warning** that this may resolve to system Python 3.8.
- [ ] Print the resolved interpreter path in the chain header (`Python: /path/to/python (source: VIRTUAL_ENV / project venv / uv / python3)`) so operators can spot mis-resolution before launch.
- [ ] Refuse to start (exit non-zero) if the resolved interpreter reports a Python version < 3.10 — guards against an operator's stale `python3` symlink. The check is `${PY_CMD[@]} -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'`.
- [ ] Pass `$VIRTUAL_ENV` and the resolved `PATH` through to the iteration subprocess so any nested tool the workflow invokes (e.g., training subprocesses) inherits the same environment.
- [ ] Unit test: with `VIRTUAL_ENV=/some/test/path` set, the chain header prints that path as the resolved interpreter; with it unset and `${PROJECT_DIR}/.venv/bin/python` present, that path is used; with both absent and `uv` on PATH, `uv run python` is used.
- [ ] Note: `--mode sdsc` keeps its existing pattern — `submit_one_iteration.slurm` activates `.venv/bin/activate` inside the Slurm job, so `$VIRTUAL_ENV` on the submit host is irrelevant. This commit does not change the SDSC env-resolution path.

**Smoke tests:**

- [ ] Smoke test (lilab): 2-iter chain on synthetic data, verify both iters complete and write manifests, and the chain header shows the project `.venv` interpreter.
- [ ] Smoke test (sdsc): submit a 2-iter chain dry-run (`--time 00:05:00`), verify the second job depends on the first via `squeue -j ... -o '%j %i %E'`.
- [ ] Resume smoke test: launch a 3-iter chain, kill mid-iter-2, rerun the same command, verify iter_001 is preserved and iter_002 restarts from scratch.
- [ ] Doc-sync: §3.4 (auto-resume), §3.8 (consistency) cover the design surface; update `docs/running_chain_test.md` runbook to reference the new entry-point and dry-run + venv-detection behaviours.

#### Commit 12 — `test(chain): full integration test + memory regression assertion`

**Goal**: Lock the contract.

- [ ] Pseudo-mode integration test: 2-iter chain end-to-end (synthetic seed, mocked LLM responses), verify both manifests written with status=completed and the iter_002 process's `MODEL_REGISTRY` contained iter_001's plugin at the time `run_workflow` was entered.
- [ ] Memory regression check: assert iter_001 process RSS-at-end is within 200 MB of iter_002 process RSS-at-start (process boundary as memory floor).
- [ ] Hostile case: pseudo-corrupt iter_001's run_output JSON; verify iter_002 refuses to start with a clear error rather than silently chaining off an incomplete output.
- [ ] Doc-sync: §3.5 (this section) updated with test results once green.

#### Commit 13 — `docs(chain): update runbook + retire run_exploration_adaptive.py from "primary" status`

**Goal**: Operator-facing documentation reflects the new default.

- [ ] Update `docs/running_chain_test.md` to recommend `run_chain.sh --mode lilab` as the default lilab runner for any `max_iterations >= 2`.
- [ ] Demote `run_exploration_adaptive.py` to "dev/debug" status in the doc (kept for short single-process iteration cycles).
- [ ] Update `MEMORY.md` if `run_exploration_adaptive.py` is referenced as primary.
- [ ] Add a "When to use which runner" decision table.
- [ ] Doc-sync: this commit IS the doc-sync; no separate design-doc edit needed.

### 3.6 Out of scope (deferred, not abandoned)

These were present in Part 2's design but are deliberately excluded from Task 2 under the chain-first plan:

- **Mid-iter checkpoint**: still costs up to one full iter on SIGKILL. Address only if a single iter regularly costs > 6 hours.
- **Variable-by-variable in-memory rebuild** (Part 2 §2.5): `run_exploration_adaptive.py` now achieves resume via the **chain workspace layout** + `restore_prior_state` (see Commit 9 Part B), not via in-process state-pickling. The Part 2 design is preserved as history but no longer planned.
- **Cross-host portability**: hardware_context is host-specific; the plugin Python files might depend on host-specific module paths. Resume is "same host, post-SIGKILL", not "migrate to new host" — same contract as Part 2 §2.8.

### 3.7 Test strategy summary

| Layer | Test | Tier |
|---|---|---|
| Unit | `_add_plugin_to_registries` updates all four registries | unit |
| Unit | `restore_prior_state` against synthetic 3-iter fixture (clean / partial / corrupt / missing-plugin / non-contiguous) | unit |
| Unit | `inspect_run_state.py --next-iter` against fixtures | unit |
| Unit | CLI surface of `run_one_iteration.py` matches `run_exploration_adaptive.py` (snapshot of `run_workflow` kwargs) | unit |
| Unit | §3.8 consistency contract — every flag has identical name + default in all three entries | unit |
| Unit | `--dry-run` never touches the workspace and prints the right per-iter command | unit |
| Unit | venv detection picks `$VIRTUAL_ENV` first, project `.venv` second, `uv` third, `python3` last (with warning) | unit |
| Pseudo-integration | 2-iter chain end-to-end with mocked LLM responses; verify cross-iter `MODEL_REGISTRY` restoration | integration (pseudo) |
| Pseudo-integration | `run_exploration_adaptive.py` with `--start_iteration 2` against a workspace where iter_001 is on disk; verify in-process iter_002 enters with `MODEL_REGISTRY` carrying iter_001's plugin | integration (pseudo) |
| Smoke | 2-iter chain on lilab; manual SIGKILL mid-iter-2; rerun same command; verify iter_001 preserved | smoke |
| Smoke | 2-iter sbatch chain on SDSC; verify dependency wiring via `squeue` | smoke |

### 3.8 Consistency contract — flag parity across all three entries

Each flag in §3.2 must have **identical name and default value** across the three operator-facing entries:

1. `run_exploration_adaptive.py` (in-process Python entry)
2. `sdsc_submission_scripts/run_one_iteration.py` (per-iter Python entry, called by the chain)
3. `sdsc_submission_scripts/run_chain.sh` (shell entry, passes through to entry 2)

This is a hard test gate — Commit 9's "every flag in §3.2 has the same name and default" unit test enforces it programmatically. Drift introduces silent behaviour differences between operator-equivalent commands and is the single biggest predictable source of "it worked on lilab but not on SDSC" bugs.

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

The unit test at `tests/unit/scripts/test_chain_consistency.py` (new, Commit 9) does the following:

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

The exemption list is canonical: any flag not on it must satisfy the contract.
