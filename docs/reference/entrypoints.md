# Entrypoints and CLI

**Audience**: operators and anyone trying to find the right command.
**Authority**: `sdsc_submission_scripts/run_chain.sh`,
`sdsc_submission_scripts/_chain_common.sh`,
`sdsc_submission_scripts/run_one_iteration.py`,
`workflows/model_exploration.py`, `scripts/run_comparison.py`.

For exhaustive flag lists, run each entrypoint with `--help`. This page covers
the flags that decide *what a run is*.

---

## Which entrypoint

| you want to | use |
|---|---|
| run the full multi-iteration agent loop | `sdsc_submission_scripts/run_chain.sh` |
| run exactly one iteration (or debug one) | `sdsc_submission_scripts/run_one_iteration.py` |
| drive the workflow directly from Python | `workflows/model_exploration.py` |
| compare a built-in TIDMAD model against baselines | `scripts/run_comparison.py` |

> Note the directory: the chain launchers live in `sdsc_submission_scripts/`,
> **not** in `scripts/`. Several older documents said otherwise.

## `run_chain.sh` — the chain launcher

The primary user-facing entrypoint. Owns Python resolution, auto-resume, and
dispatch to either a foreground subprocess or a Slurm dependency chain.

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /path/to/workspace \
    --run_name my_run_v1 \
    --num_iterations 5 \
    --task_composition configs/task_composition/tidmad.yaml \
    --data_dir /path/to/data \
    --max_rounds 5
```

| flag | meaning |
|---|---|
| `--mode {lilab,sdsc}` | **the only flag the launcher validates as required.** `lilab` = foreground subprocess; `sdsc` = `sbatch` + `afterany` chain |
| `--workspace DIR` | chain workspace root — required in practice |
| `--run_name NAME` | pins the immutable run id — required in practice |
| `--task_composition FILE` | the task manifest. **Omitted = the legacy un-composed run** with byte-identical child argv |
| `--data_dir DIR` | physical data root. **Required for any composed run**; a composed run without it fails closed before any LLM or GPU work |
| `--num_iterations N` | default `2` |
| `--seed_paths P [P…]` | prior run outputs to seed from. **Optional** — an empty list is a valid cold start |
| `--auto_resume` / `--no_auto_resume` | default **ON**: pick up where a partial chain stopped |
| `--start_iter N` | manual override of auto-resume |
| `--dry-run` | walk the chain, print exact commands, no side effects |

Everything else is pass-through to the iteration: `--data_scope`,
`--health_gate_enabled` / `--no-health_gate_enabled`, `--health_gate_files`,
`--health_checks_config`, `--healthgate_mode`, `--max_rounds`, and the trial /
formal time and VRAM budgets.

> The header comment inside `run_chain.sh` lists `--seed_paths` under "Required
> flags". That comment is stale — `_chain_common.sh:403-406` documents the
> opposite and omits the flag entirely for a cold start. Cold start is in fact
> the required posture for gate runs.

## `run_one_iteration.py` — one iteration

This is where composition is actually entered. Useful for debugging a single
iteration without chain machinery.

Two flags have **no defaults and are required for a formal launch** — the run
exits `2` without them:

| flag | choices |
|---|---|
| `--healthgate_mode` | `blocking` \| `observe_only` |
| `--result_authority` | `scientific` \| `diagnostic` |

Other flags that define a run:

| flag | default |
|---|---|
| `--task_composition` | `None` (legacy un-composed) |
| `--data_dir` | `None` |
| `--data_scope` | `None` (full scope) |
| `--health_gate_enabled` / `--no-health_gate_enabled` | enabled |
| `--health_gate_files` | `None` |
| `--health_checks_config` | `None` (framework default) |
| `--max_rounds` | `3` |
| `--max_proposal_attempts` | `3` |
| `--llm_config` | `None` |

## `workflows/model_exploration.py` — the module CLI

The workflow itself, runnable directly. Accepts `--task_composition`,
`--run_name`, `--max_iterations` (default `1`), `--max_rounds` (default `10`),
`--max_proposal_attempts` (default `3`), `--target_score`, LLM routing flags and
advice flags.

## `scripts/run_comparison.py` — baseline comparison

⚠ **TIDMAD-only by construction.** It imports TIDMAD's dataset, file count,
sandbox and data directory directly, and it does **not** accept
`--task_composition`. It is a useful baseline harness for TIDMAD and is not a
general task runner.

```bash
python scripts/run_comparison.py --model punet --is_trial
```

Key flags: `--model` (required, single-valued), `--is_trial`, `--max_rounds`
(default `50`), `--provider` / `--model_id` and the `--reflect_*` split,
`--data_scope`, `--health_checks_config`.

## Data scope

`--data_scope` restricts everything a run touches — training, inference, scoring
and health peeks — to a subset of partitions. It is enforced constructively at
the sample-set builder and again at the sandbox I/O boundary, **never by prompts**.

```bash
--data_scope 4-9                 # or 4,5,6,7,8,9  or 0-3,7
--health_gate_files 4,7,9        # must be a subset of the scope
```

Under a partial scope, health-gate files must be declared explicitly and be
in-scope. Aggregate scores are **only comparable within one scope** — the
resolved scope is pinned by the workspace's invariants lock, and resuming with a
different one fails at startup.

> `--data_scope` is a partition-index concept from TIDMAD's topology. For a
> composed non-TIDMAD task it is refused by name; such a task expresses coverage
> through its own `TaskScopeCapability`.

## Which entrypoints accept `--task_composition`

| entrypoint | accepts it |
|---|:---:|
| `run_chain.sh` | ✅ (forwards) |
| `run_one_iteration.py` | ✅ |
| `workflows/model_exploration.py` | ✅ |
| `scripts/run_comparison.py` | ❌ |

---

## Next

- [Operating a run](../guides/operating-a-run.md) — resume, budgets, failure modes
- [Task composition reference](task-composition.md)
- [Configuration map](configuration-map.md)
