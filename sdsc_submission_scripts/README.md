# Chain entry points

This directory contains the reusable SIDERIUS chain entry points. Scientific
task packages, campaign launchers, frozen treatments, deployment inventories,
and scheduler state belong to the external experiment repository.

## Supported entry points

| File | Responsibility |
|---|---|
| `run_chain.sh` | Run a bounded multi-iteration chain against an explicit task composition and data root. |
| `_chain_common.sh` | Parse chain options, construct one-iteration arguments, and sequence iterations. |
| `run_one_iteration.py` | Execute exactly one research iteration and persist its manifest. |
| `_import_resolution_probe.py` | Verify that child processes import the explicitly selected SIDERIUS checkout. |

Every scientific run must provide `--task_composition`, `--data_dir`, and a
writable `--workspace`. The framework does not select a task, dataset,
campaign, advice artifact, or scientific policy by default.

## Minimal dry run

```bash
bash sdsc_submission_scripts/run_chain.sh \
  --mode lilab \
  --workspace /tmp/siderius_quickstart \
  --run_name quickstart_v1 \
  --task_composition configs/task_composition/quickstart.yaml \
  --data_dir /tmp/siderius_quickstart_data \
  --num_iterations 1 \
  --max_rounds 1 \
  --dry-run
```

The caller is responsible for materializing the Quickstart data before a real
execution. See `examples/quickstart/README.md`.

## External campaigns

A campaign may wrap `run_chain.sh`, but it must live outside this repository
and select an exact SIDERIUS revision. Campaign-specific concurrency,
monitoring, stop controls, resource allocations, task advice, and frozen
scientific treatment remain the caller's responsibility.

The generic CLI reference is `docs/reference/entrypoints.md`. Operational
guidance for one explicitly composed run is in
`docs/guides/operating-a-run.md`.
