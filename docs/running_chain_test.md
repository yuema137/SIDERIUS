# Running the Chain Test (lilab vs SDSC)

Operational runbook for the SIDERIUS multi-iteration model exploration chain.
The chain runs the 5-agent loop (interpret → propose → implement → validate →
tune) once per iteration, and feeds each iteration's output back as a seed for
the next iteration.

## The three entry points

| # | Entry point | Environment | Mechanism | Use when |
|---|---|---|---|---|
| 1 | `tests/integration/workflows/test_full_exploration_loop.py::test_chained_iterations` | lilab | pytest, `tmp_path` workspace, in-process two `run_workflow()` calls | Quick smoke test / regression. Throwaway artifacts. |
| 2 | `sdsc_submission_scripts/run_iteration_chain_lilab.sh` | lilab | Bash orchestrator → `run_one_iteration.py` as foreground subprocess | **Real lilab run with durable workspace.** Mirrors the SDSC path 1:1. |
| 3 | `sdsc_submission_scripts/run_iteration_chain.sh` | SDSC Expanse | Bash orchestrator → `sbatch` with `--dependency=afterok` | Real distributed run on the cluster. |

**Entries 2 and 3 share all logic** via `sdsc_submission_scripts/_chain_common.sh`
(arg parsing, advice file loading, source-path building, APP_ARGS construction,
per-iteration loop). The only difference is the `submit_iteration` function:
on lilab it runs `python3 run_one_iteration.py` in the foreground, on SDSC it
runs `sbatch ... submit_one_iteration.slurm` with a dependency on the previous
job. **Iterations always hand off via `manifest.json` files**, regardless of
whether the previous iteration was a Python subprocess or a Slurm job. This
keeps the two paths identical for debugging.

The shared advice file `sdsc_submission_scripts/human_advice_chain_test.json` is the
single source of truth for human guidance to the 5 agents. **Both lilab and
SDSC tests load from it** — edit one file to retune both environments.

### Two levels of human-advice files

Human-advice files come in two distinct shapes, one per level of the run hierarchy.
Do not confuse them:

| Level | File shape | Used by | Example |
|---|---|---|---|
| **Aggregated** (workflow / chain) | Keyed by agent name — has all 5 keys, one per agent in the loop | `run_iteration_chain.sh`, `run_iteration_chain_lilab.sh`, `run_one_iteration.py` (chain test) | `{"interpret":"...", "propose":"...", "implement":"...", "validate":"...", "tune":"..."}` |
| **Per-agent** (single-agent run) | One key matching the single agent the script invokes | `run_comparison.py` (single-model hyperparameter tuning) | `{"tune":"..."}` |

The per-agent file is a strict subset of the aggregated file — pulling the
relevant key out of the aggregated file gives you a valid per-agent file.
Both formats are JSON; the chain runbook in this doc only uses the aggregated
format.

---

## Pre-flight (both environments)

1. **Pull latest code** on whichever box you're running on:
   ```bash
   cd ~/SIDERIUS
   git pull
   git log --oneline -3
   ```

2. **Inspect / edit shared advice** if needed:
   ```bash
   cat sdsc_submission_scripts/human_advice_chain_test.json
   ```
   Five keys, one per agent: `interpret`, `propose`, `implement`, `validate`,
   `tune`. Any key may be empty (`""`) — empty strings are not forwarded.

---

## Lilab — Tier 3 pytest

Two tests live in `tests/integration/workflows/test_full_exploration_loop.py`:

| Test | What it does | Runtime |
|---|---|---|
| `test_full_loop` | One iteration of the full 5-agent loop. Validates the loop end-to-end. | ~5–10 min |
| `test_chained_iterations` | Two sequential `run_workflow()` calls. Iteration 2 sees seeds + iteration 1's output. Mirrors the SDSC chain in-process. | ~15–25 min |

### Run the chain test (the one that mirrors SDSC)
```bash
cd ~/SIDERIUS
tmux new -s lilab_chain
uv run pytest -m real_run -v -s \
    tests/integration/workflows/test_full_exploration_loop.py::test_chained_iterations \
    2>&1 | tee /tmp/lilab_chain.log
```
Detach with `Ctrl-b d`. Reattach with `tmux attach -t lilab_chain`.

### Watch progress
```bash
tail -f /tmp/lilab_chain.log
nvidia-smi -l 5    # in another pane — watch GPU usage
```

### What "success" looks like
- Final pytest line: `PASSED` (exit code 0)
- Two model plugins were created and cleaned up under `agent_generated/models/`
- `pytest`'s `tmp_path` workspace contains:
  - `iter_001/iteration_001/{model1}/run_output_iter_001.json`
  - `iter_002/iteration_001/{model2}/run_output_iter_002.json`

### If it fails
The test prints a `[CLEANUP]` line for each registered plugin. Verify no
orphan plugins remain in `agent_generated/models/` before rerunning:
```bash
ls agent_generated/models/
```

### Optional: quick smoke test first
```bash
uv run pytest -m real_run -v -s \
    tests/integration/workflows/test_full_exploration_loop.py::test_full_loop
```

---

## Lilab — real durable chain run (entry point 2)

When you want a *real* lilab run with a fixed, persistent workspace
(not a pytest throwaway), use `run_iteration_chain_lilab.sh`. It is the
non-Slurm sibling of `run_iteration_chain.sh` — same flags, same behavior,
same shared logic — and the **only** legitimate difference is that
iterations run as foreground Python subprocesses instead of Slurm jobs.

### Submit
```bash
cd ~/SIDERIUS
tmux new -s lilab_real_chain
bash sdsc_submission_scripts/run_iteration_chain_lilab.sh \
    --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
    --num_iterations 2 \
    --seed_paths /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
    --max_rounds 5 \
    --max_epochs 5 \
    --trial_portion 0.02 \
    --eval_portion 0.02 \
    --human_advice_file sdsc_submission_scripts/human_advice_chain_test.json \
    2>&1 | tee /tmp/lilab_real_chain.log
```
Detach with `Ctrl-b d`. Reattach with `tmux attach -t lilab_real_chain`.

### Monitor (other pane)
```bash
tail -f /tmp/lilab_real_chain.log
nvidia-smi -l 5
```

### Success criteria (same as SDSC)
- Script exits 0
- Both `iter_001/manifest.json` and `iter_002/manifest.json` exist with
  `"status": "completed"`
- Round outputs present under `iter_NNN/iteration_001/{model}/`
- Iter 2's interpretation step references iter 1's model name (proves the
  manifest handoff carried real data)

### If iter 1 fails
The script aborts via `set -e`. Inspect `iter_001/` (the partial manifest
will not exist; runner only writes it on clean exit). Fix the bug, and
**always rerun with a fresh `--workspace`** — partial state from a killed
run can confuse manifest resolution on the next attempt.

### Differences vs the pytest test
| Aspect | pytest `test_chained_iterations` | `run_iteration_chain_lilab.sh` |
|---|---|---|
| Workspace | `tmp_path` (pytest, throwaway) | Fixed durable path you choose |
| Verification | strict assertions in test code | inspect manifests + outputs manually |
| Plugin cleanup | auto-removes registered plugins | leaves everything in place |
| Code path | calls `run_workflow()` directly in-process | calls `run_one_iteration.py` as a subprocess (same as SDSC) |
| Use when | CI / quick smoke / regression | real exploration, want artifacts to keep |

### Differences vs the SDSC orchestrator (entry point 3)
| Aspect | SDSC (`run_iteration_chain.sh`) | lilab (`run_iteration_chain_lilab.sh`) |
|---|---|---|
| Execution | Each iteration = separate Slurm job | Each iteration = foreground Python subprocess |
| Concurrency model | Async; orchestrator returns after submission | Sync; orchestrator blocks until chain finishes |
| Failure handling | `--kill-on-invalid-dep=yes` cancels downstream jobs | `set -e` aborts the script |
| Walltime cap | Slurm `--time` enforced by scheduler | None (runs until done or you Ctrl-C) |
| Slurm-only flags | `--partition`, `--time`, `--mem`, `--gpus`, `--cpus` | accepted but ignored |
| Shared code | `_chain_common.sh` | `_chain_common.sh` (same file) |

---

## SDSC Expanse — Slurm chain submission (entry point 3)

The real distributed test. Each iteration is its own Slurm job; iteration N+1
starts only after iteration N's `manifest.json` is written. Shares all
non-execution logic with the lilab orchestrator via `_chain_common.sh`.

### 1. Sync code on SDSC
```bash
ssh ym137@login.expanse.sdsc.edu
cd ~/SIDERIUS
git checkout small_sample_trial_fixed_config
git pull
git log --oneline -3
```

### 2. Submit the chain (use a fresh workspace each time)
```bash
bash sdsc_submission_scripts/run_iteration_chain.sh \
    --workspace /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_test_v3 \
    --num_iterations 2 \
    --seed_paths /expanse/lustre/projects/ddp433/ym137/siderius_workspace/punet/hpt_full_v1/agent/run_output_hpt_full_v1_agent.json \
    --max_rounds 5 \
    --max_epochs 5 \
    --human_advice_file sdsc_submission_scripts/human_advice_chain_test.json \
    --time 06:00:00 \
    --mem 24G \
    --cpus 8
```

Key flags:
- `--max_epochs 5` — hard cap on epochs per round (LLM cannot override)
- `--max_rounds 5` — total rounds per iteration (last round = formal mode)
- `--human_advice_file ...` — loads all 5 advice keys from JSON
- **Always use a fresh workspace** (`_v3`, `_v4`, …) — partial state from a
  killed run will confuse the manifest resolution.

### 3. Capture the two job IDs
The script prints something like:
```
  iter 1 → job XXXXXXXX
  iter 2 → job YYYYYYYY  (depends on XXXXXXXX, kill-on-invalid-dep=yes)
```
Save them — you need them for monitoring.

### 4. Monitor

While queued/running:
```bash
squeue -u ym137
squeue -j XXXXXXXX,YYYYYYYY -o "%.10i %.8T %.10M %.20R"
scontrol show job XXXXXXXX | grep -E "JobState|Reason|RunTime|TimeLimit"
```

Once iter 1 starts running, tail its log:
```bash
tail -f sdsc_submission_scripts/logs/iter_XXXXXXXX.out
tail -f sdsc_submission_scripts/logs/iter_XXXXXXXX.err
```

After iter 1 finishes, **verify the manifest** (this is the critical handoff
between iterations):
```bash
ls /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_test_v3/iter_001/
cat /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_test_v3/iter_001/manifest.json
```
Expected: `"status": "completed"` and an `output_path` that exists on disk.

When iter 2 starts, the **first lines of its log should show**:
```
  Resolved @manifest:.../iter_001/manifest.json → .../{model}/run_output_iter_001.json
```
That confirms the manifest indirection worked end-to-end. Tail it:
```bash
tail -f sdsc_submission_scripts/logs/iter_YYYYYYYY.out
```

### 5. Post-mortem after completion
```bash
sacct -j XXXXXXXX,YYYYYYYY --format=JobID,JobName,State,Elapsed,ExitCode,MaxRSS,Start,End
ls /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_test_v3/iter_*/manifest.json
```

### Success criteria
- Both jobs `State=COMPLETED`, `ExitCode=0:0`
- Both `iter_001/manifest.json` and `iter_002/manifest.json` exist with
  `"status": "completed"`
- Iter 2's log shows it resolved iter 1's manifest
- Iter 2's interpretation step references iter 1's model name (proves the
  chain handoff carried real data, not just a path)

### If iter 1 fails
Iter 2 auto-cancels (`State=CANCELLED` due to `--kill-on-invalid-dep=yes`).
No zombies in the queue.
1. Read `sdsc_submission_scripts/logs/iter_XXXXXXXX.err` first.
2. If it ends with `slurmstepd: ... CANCELLED ... DUE TO TIME LIMIT`, the
   walltime was too short — bump `--time` or reduce `--max_rounds` /
   `--max_epochs`, and check the runtime breakdown in `.out` (look for the
   gap between `[Step 1/3] Training...` and `[Step 2/3] Inference...`).
3. Fix, choose a new workspace dir, resubmit.

---

## Recommended order of operations

1. **Lilab `test_chained_iterations` first.** It runs in ~20 min in-process
   and exercises exactly the same code as SDSC. If this fails, do not burn
   SDSC quota — diagnose locally first.
2. **Once lilab passes, submit SDSC.** Watch iter 1 closely until you've
   confirmed the manifest is written *and* iter 2 has started — that's the
   moment of truth for the chain plumbing.
3. **Don't run lilab and other GPU work simultaneously** — the test will
   conflict with anything else using the lilab GPU and may hit CUDA launch
   timeouts (display GPU watchdog).

---

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Iter 1 hits walltime, iter 2 auto-cancelled | Single round took too long (LLM picked too many epochs) | Confirm `--max_epochs` is set; tighten `tune` advice in JSON |
| `manifest.json` missing after iter 1 "finished" | Workflow raised an exception before manifest write | Check `iter_XXXXX.err` — runner writes `manifest.json` only on clean exit |
| Iter 2 fails with `Manifest not found` | Iter 1 was killed before writing manifest | Iter 2 should never have started — check that `--kill-on-invalid-dep=yes` was applied |
| `Resolved @manifest:... → ...` shows wrong model name in iter 2 | Stale workspace from previous run | Always use a fresh `--workspace` directory |
| CUDA launch timeout on lilab only | Display GPU watchdog kills kernels >2s when GPU is shared | Don't run other GPU work concurrently |
| `bank_limit plugin` rejection on SDSC | Missing `--ntasks=1` or wrong GPU spec | Already handled by `run_iteration_chain.sh`; don't edit the sbatch args block |

---

## Files referenced

- `sdsc_submission_scripts/_chain_common.sh` — shared logic for both orchestrators (defaults, arg parsing, advice loading, source-path building, APP_ARGS construction, chain loop)
- `sdsc_submission_scripts/run_iteration_chain.sh` — SDSC orchestrator (sources `_chain_common.sh`, defines `submit_iteration` to call `sbatch` with dependency)
- `sdsc_submission_scripts/run_iteration_chain_lilab.sh` — lilab orchestrator (sources `_chain_common.sh`, defines `submit_iteration` to call `python3` in foreground)
- `sdsc_submission_scripts/submit_one_iteration.slurm` — Slurm wrapper for one iteration (SDSC only)
- `sdsc_submission_scripts/run_one_iteration.py` — Python runner: `run_workflow(max_iterations=1)` + manifest write (used by both lilab and SDSC)
- `sdsc_submission_scripts/human_advice_chain_test.json` — shared advice file (5 keys: interpret/propose/implement/validate/tune)
- `tests/integration/workflows/test_full_exploration_loop.py` — lilab Tier 3 pytest tests
- `workflows/model_exploration.py` — `run_workflow()` implementation
- `agent/schemas/run_metadata.py` — typed `BaseRunMetadata` hierarchy. Today only `TunerRunMetadata` is implemented (written by `run_comparison.py` to `{agent_workspace}/tuner_run_metadata.json`); workflow-level and chain-level subclasses will land later and reference lower-level metadata files via `child_metadata_paths`.
- `docs/full_loop_5_agents.md` — design doc (companion to this runbook)
