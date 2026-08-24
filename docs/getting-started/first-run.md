# Your first run

**Prerequisite**: [Installation](installation.md).

This page is deliberately honest about what you can run today without a dataset,
with a dataset, and not at all yet.

---

## Level 0 — without any dataset

The unit suite exercises the whole workflow with mocked LLM calls and no GPU:

```bash
uv run pytest tests/unit/ -q
```

The integration suite runs the full node orchestration against **predefined**
LLM and subprocess responses — the complete plan → train → score → reflect wiring
in milliseconds, no API key, no GPU:

```bash
uv run pytest tests/integration/ -q
```

This is the fastest way to see the shape of the system. It is not a scientific
run.

## Level 1 — a dry run

If you want to see exactly what a real chain would execute, without executing it:

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /path/to/your/workspace \
    --run_name first_run_v1 \
    --task_composition configs/task_composition/tidmad.yaml \
    --data_dir /path/to/tidmad/data \
    --num_iterations 1 \
    --max_rounds 1 \
    --dry-run
```

`--dry-run` walks the chain and prints the exact child commands with no side
effects. Do this before every unfamiliar configuration.

## Level 2 — a real TIDMAD run

TIDMAD is currently the only task that runs end-to-end through the production
chain. You need the raw `.h5` files staged at `tidmad_data_dir` (~50 GB) and a
CUDA GPU.

Start small — one iteration, one round, trial budget, a bounded scope:

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /path/to/your/workspace \
    --run_name first_run_v1 \
    --task_composition configs/task_composition/tidmad.yaml \
    --data_dir /path/to/tidmad/data \
    --healthgate_mode blocking \
    --result_authority scientific \
    --num_iterations 1 \
    --max_rounds 1 \
    --data_scope 4-9 \
    --health_gate_files 4,7,9 \
    --trial_time_budget_minutes 20
```

Notes on the flags that are not obvious:

- `--healthgate_mode` and `--result_authority` have **no defaults**. A formal
  launch without both exits `2`.
- `--data_dir` is **required** for a composed run.
- `--data_scope` bounds the work; under a partial scope, `--health_gate_files`
  must be given and be in-scope.
- Time budgets prevent a badly chosen data portion from producing a multi-hour
  round.

Omitting `--task_composition` runs the ⚠ legacy un-composed path. It works, but
it is not the path to learn.

## What you will see

The run creates a workspace containing per-node output records, an effective
health config, an invariants lock, and the generated model plugins. Browse
results with the dashboard:

```bash
python dashboard/main.py     # http://localhost:8000
```

## Level 3 — the contrast example tasks

⏳ **Not available through the chain yet.**

The Oxford-IIIT Pet and DAVIS example packs execute real training, inference and
scoring — but through direct-execution harnesses
(`scripts/run_pets_gate2.py`, `scripts/run_davis_gate2.py`), not through the
production chain. The execution path below the composition edge is not yet
task-neutral end to end; closing that is the unmerged PR-12d.

🧭 A single documented run command per example pack is planned by PR-12e, whose
design is still a draft. **This documentation will not publish that command until
it exists.**

See [supported tasks and current maturity](../concepts/supported-tasks.md) for
exactly what each example can and cannot do today.

## When something refuses

Most first-run problems are deliberate refusals, not bugs. The table in
[operating a run](../guides/operating-a-run.md#failures-and-refusals) maps each
one to its cause.

---

## Next

- [What SIDERIUS is](../concepts/overview.md)
- [Operating a run](../guides/operating-a-run.md)
- [Define your own task](../guides/define-a-task.md)
