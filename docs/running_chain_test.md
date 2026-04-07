# Running the Chain Test (lilab vs SDSC)

Operational runbook for the SIDERIUS multi-iteration model exploration chain.
The chain runs the 5-agent loop (interpret → propose → implement → validate →
tune) once per iteration, and feeds each iteration's output back as a seed for
the next iteration.

There are **two environments** for running this test:

| Environment | Mechanism | Test entry point | Runtime |
|---|---|---|---|
| **lilab** (local GPU) | In-process: `run_workflow()` called twice in the same Python process | pytest (`test_chained_iterations`) | ~15–25 min |
| **SDSC Expanse** (Slurm HPC) | One Slurm job per iteration, chained via `--dependency=afterok` | `run_iteration_chain.sh` | hours, async |

Both paths exercise the same code (`run_workflow()`); the only difference is
whether iterations run sequentially in one process (lilab) or as separate
Slurm jobs that hand off via `manifest.json` files (SDSC).

The shared advice file `sdsc_submission_scripts/human_advice.json` is the
single source of truth for human guidance to the 5 agents. **Both lilab and
SDSC tests load from it** — edit one file to retune both environments.

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
   cat sdsc_submission_scripts/human_advice.json
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

## SDSC Expanse — Slurm chain submission

The real distributed test. Each iteration is its own Slurm job; iteration N+1
starts only after iteration N's `manifest.json` is written.

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
    --human_advice_file sdsc_submission_scripts/human_advice.json \
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

- `sdsc_submission_scripts/run_iteration_chain.sh` — orchestrator (submits N chained Slurm jobs)
- `sdsc_submission_scripts/submit_one_iteration.slurm` — Slurm wrapper for one iteration
- `sdsc_submission_scripts/run_one_iteration.py` — Python runner: `run_workflow(max_iterations=1)` + manifest write
- `sdsc_submission_scripts/human_advice.json` — shared advice file (5 keys)
- `tests/integration/workflows/test_full_exploration_loop.py` — lilab Tier 3 tests
- `workflows/model_exploration.py` — `run_workflow()` implementation
- `docs/full_loop_5_agents.md` — design doc (companion to this runbook)
