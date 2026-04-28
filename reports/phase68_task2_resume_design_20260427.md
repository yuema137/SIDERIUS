# Phase 6.8 — Task 2: Resume Technical Design (Breakpoint Continuity)

**Date**: 2026-04-27
**Driver**: v5 sanity-run host-OOM kill of `explore_novel_v5_0426` (PID 4142820) at 2026-04-27 00:46:42 PDT — first SIGKILL the system has experienced under load. Sister run `exploit_cnn_v5_0426` survived but would have lost ~17 hours of work if it had also been killed.
**Status**: Design only. No code in this report.

---

## TL;DR

**Today's `run_workflow()` cannot resume.** It always starts at `iteration=1` (`workflows/model_exploration.py:633`), no completion check, no state re-population. A SIGKILL mid-run forces a full restart from scratch, with the additional hazard that pre-existing per-round records under `iteration_001/{model}/records/` get silently merged into the new tuner's `memory_history`.

**The natural commit fence already exists**: `iteration_NNN/{model}/run_output_{run_name}.json`. The tuner writes this last in its run() exit path, so its presence proves every upstream artifact (interpretation, proposal, validation) and every per-round record is on disk.

**No new state file is needed.** Resume is purely a reader of existing artifacts. Add `--resume` CLI flag, scan for the latest committed iteration, repopulate 9 in-memory variables from the on-disk JSONs, and continue at iter N+1. Any mid-iter-N state is discarded — the partial iter dir is removed and re-run.

---

## 1. Current State Audit — does resume work today?

**No.** `run_workflow()` always begins at `iteration=1` unconditionally (`workflows/model_exploration.py:633`):

```python
for iteration in range(1, max_iterations + 1):
    iter_dir = os.path.join(run_dir, f"iteration_{iteration:03d}")
    os.makedirs(iter_dir, exist_ok=True)
    ...
```

There is no resume detection, no completion check, and no state re-population. If the same `run_name` is re-invoked after a SIGKILL:

- `iteration_001/` is **not cleared** (`exist_ok=True` is permissive).
- Interpretation, proposal, implementation, validation, and tuning run again from scratch.
- The tuner writes into `{iter_dir}/{model}/records/{run_name}/`. **If a previous run wrote partial records there, the new tuner sees them in `sandbox.get_summary()`** (which scans the records dir) — a silent merge that the planner's `memory_history` will treat as legitimate prior rounds.
- `iteration_results` starts empty. `recent_tune_outputs` starts empty. `current_runtime_vocab` starts at the seed. **All long-term memory is lost.**

This means restart is destructive for partially-completed iterations and amnesic for completed ones. **It is not safe to restart any in-flight run today.**

---

## 2. Where save state already lives (no new state file needed)

Today's workflow already writes substantial on-disk state. Full inventory:

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

**Key invariant for resume**: an iteration N is "committed" iff `iteration_NNN/{model}/run_output_{run_name}.json` exists AND validates as `HyperparamTuningOutput`. This file is the natural commit fence — the tuner writes it last in its run() exit path, so its presence proves every upstream artifact and every per-round record is on disk.

**No new state file is needed. The resume mechanism is purely a reader of existing artifacts.**

---

## 3. Logical commit point — end of iteration

### 3.1 Coarse-grained (proposed primary): end of iteration

Place: `workflows/model_exploration.py:904`, immediately after `iteration_results.append(tune_output)`.

At this moment:

- `run_output_{run_name}.json` is on disk (tuner wrote it at the end of its run).
- All per-round records are on disk.
- All upstream attempt artifacts are on disk.
- The in-memory state for "iter N → iter N+1" is fully derivable from these files.

This is the only commit point that is both **easy to detect** (single boolean: does the JSON validate?) and **fully durable** (every artifact below this fence is written).

### 3.2 Fine-grained (deferred to a future phase)

Per-tuner-round commit. The tuner already writes per-round records, so a "resume mid-tune" would mean restarting `HyperparamTuningAgent.run()` from a partial set of records. Two issues:

1. The tuner's planner state machine (`gate_exhaustion`, `consecutive_fail_rounds`, `recent_round_summaries`) lives only in memory inside `run()`. A mid-tune resume would need to reconstruct this from records — doable but non-trivial.
2. Most iters are dominated by a single long round (v5 exploit iter_003: rid=3 alone was 222 min of 437 min total wall). Coarse-grained resume already protects 50–60% of any iter's work.

**Recommendation**: ship coarse-grained resume in Phase 6.8. Revisit fine-grained when a single iter regularly costs > 6 hours.

---

## 4. Resume detection algorithm

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

**Key contract**: `completed_iters` is contiguous from iter_001 to iter_N. We refuse to "skip" a missing iter — if iteration_005 is missing but iteration_006 exists, we treat 005 as the partial and 006 as orphaned. (If this ever happens in practice, it's a bug, not a recoverable state.)

---

## 5. State re-population on resume — variable-by-variable

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
| `best_score_overall: float \| None` | recompute from iteration_results | `max(o.best_denoising_score for o in iteration_results if not None)` |
| `previous_failures: list[str]` | always reset (only meaningful inside an iter's proposal loop) | `[]` |
| `hardware_ctx: HardwareContext` | `get_or_create` reads its own cache | call as before — first-caller-writes/later-callers-read |
| **Plugin registry** (`MODEL_REGISTRY` etc.) | `iteration_NNN/attempt_MMM_{accepted_model}/models/{model_name}.py` for each completed iter | for each completed iter, re-call `_register_plugin` with the on-disk plugin source |
| `tuning_dir / dest_plugin_dir` for prior iters | `iteration_NNN/{model}/` | only relevant if we wanted to re-tune; we don't, so no rebuild needed |

**Critical detail — plugins**: the v5 explore run DID land its iter_001 plugin at `iteration_001/lite_dualpath_spectral_tcn/cached_models/`, but the parent's `MODEL_REGISTRY` would be empty on a fresh start. Iter_002's interpreter+proposer should not need to dispatch to the `lite_dualpath_spectral_tcn` model class (that model's record is already in `iteration_results`), but downstream code might. Re-registering all completed iters' plugins on resume is safer than skipping it.

**Critical detail — `latest_new_summary.model_description`**: this field is attached post-hoc at `workflows/model_exploration.py:917–918` (`s.model_description = proposal.model_description`). On resume we have to read the proposal JSON of the most recent completed iter to reconstruct it.

---

## 6. Resume wiring at the workflow surface

### 6.1 CLI

Add one flag to `run_exploration_adaptive.py`:

```
--resume        Auto-detect last completed iteration and resume from N+1.
                Refuses to start if {run_dir}/iteration_001/ already exists
                without --resume (prevents accidental destructive restarts).
```

### 6.2 Workflow entry behavior

```
if args.resume:
    completed, next_iter, partial = _detect_resume_state(run_dir, run_name)
    if completed:
        log "[RESUME] Found N completed iterations under {run_dir}"
        repopulate all in-memory vars per §5
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

### 6.3 Operator UX example

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

---

## 7. Edge cases and contracts

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

---

## 8. What this design explicitly does NOT do

- **No mid-iter checkpoint**: if the tuner is in the middle of round 2 of 3 when SIGKILL hits, that iter is restarted. We pay up to one full iter of re-work.
- **No state diff across resumes**: we don't snapshot the parent's full Python state (pickled). The on-disk artifacts are the contract.
- **No cross-host portability guarantees**: the hardware_context is host-specific, and plugin Python files might depend on host-specific module paths. Resume is intended for "same host, post-SIGKILL" not "migrate to a new host".
- **No Phase 6.7 contract changes**: sentinels, time-gate, ghost-score-fix all stay as-is. Resume is orthogonal.

---

## 9. Test strategy

1. **Unit**: `_detect_resume_state` against a fixture tree with (a) zero iters, (b) 3 clean iters, (c) 3 clean + 1 partial, (d) 2 clean + 1 corrupt JSON, (e) skipped iter (1 + 3 with no 2 — should raise).
2. **Unit**: `_repopulate_state` against the same fixtures, asserting each in-memory var matches the source JSON byte-for-byte where applicable.
3. **Integration (pseudo-mode)**: run a 3-iter `model_exploration` workflow to completion → kill the parent mid-iter-2 → restart with `--resume` → assert workflow finishes with the same final aggregates as a clean 3-iter run (modulo iter_002's content, which gets re-generated from scratch).
4. **Hostile case**: corrupt the iter_001 tuner JSON byte-by-byte and verify the resume safely refuses to start (or re-runs that iter, depending on the corruption mode).

---

## 10. Provisional commit plan (Part 2 only)

| # | Commit | Effect |
|---|---|---|
| 5 | `feat(workflow): _detect_resume_state + _repopulate_state` | Pure readers — no behavior change |
| 6 | `feat(workflow): --resume CLI flag and gated startup` | Makes resume operator-accessible |
| 7 | `test(workflow): resume integration + memory regression` | Locks in the contract |

Commits 5–7 depend on Task 1 commits 1–4 only insofar as both should land before the next long sanity run. They are otherwise independent.
