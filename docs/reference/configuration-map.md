# Configuration map

**Audience**: anyone facing a directory of YAML files and wondering which ones
are theirs.
**Answers**: who owns each config, whether you may edit it, and what happens if
you do.

SIDERIUS has a lot of configuration, and it is *not* all the same kind of thing.
Four owners, three lifetimes.

---

## By owner

### Task semantics — yours to write

Task science is supplied through a composition manifest. The two in-repo
manifests are synthetic examples; real task packages keep their declarations
outside this repository.

| file | declares |
|---|---|
| caller-owned task-composition manifest | manifest sections such as `task_config`, `task_health`, `metric`, `secondary_metrics`, `objective`, `model_plugins`, `loss_plugins`, and task-block declarations — see [task composition](task-composition.md) |
| manifest-referenced task files | task config/model I/O, Health, metric, dataset profile, plugin and prompt-block declarations; paths resolve relative to the manifest |

When a composed run omits a task-owned declaration, the corresponding binding
is absent and the task composition loader refuses any operation that requires
it; the framework does not silently select another task's science. Paths named
inside a composition manifest resolve relative to that manifest. Caller-owned
paths may also be absolute when the contract permits them.

### Framework policy — the framework's, selectable per run

| file | declares | when a run gets it |
|---|---|---|
| packaged `execute_tools/health_checks/resources/health_checks.yaml` | what a health failure **does**: gate role, cadence, short-circuit, `on_pass`/`on_fail` | omitted `--health_checks_config` |
| `configs/health/health_checks_baseline_observe_mode.yaml` | optional policy with blocking failures downgraded to observation | explicit `--health_checks_config` plus `--healthgate_mode observe_only` |

A run that needs different consequences selects its own policy file with
`--health_checks_config /path/to/policy.yaml`. Missing or invalid nonempty
explicit paths refuse without falling back. The old checkout default path
`configs/health/health_checks.yaml` is removed; use omission or the public
`execute_tools.health_checks.config.default_health_policy_path()` accessor.
Users select external policy; framework developers maintain the packaged YAML.

The split is the point. **Thresholds are task policy; consequences are framework
policy.** Neither file can express the other's concern, so a task and the
framework cannot hold contradictory opinions about what a failure means.

### Operator / infrastructure

| file | declares | tracked? |
|---|---|---|
| caller-owned `--ml_lit_review_config` | literature-review budget, root papers, rubric | external task or experiment |
| `configs/llm/*.json` | per-stage LLM provider routing | yes |
| caller-owned advice files | human advice injected into the loop | external experiment |
| `--data_dir` / `--workspace` | explicit input-data / run-output roots | machine-local directories outside the checkout |
| `dashboard_config.yaml` | dashboard data root | **gitignored** — copy from `.example` |
| `.env` | API keys | **gitignored** |

### Generated — never edit

| artefact | written by | purpose |
|---|---|---|
| `{workspace}/health_checks_effective.yaml` | run startup | the composed framework-policy + task-policy result, sha256-pinned |
| `{workspace}/run_invariants_lock.json` | run startup | pins resolved data scope, health-gate enablement and effective-config hash |

Editing either by hand produces a run whose recorded provenance is a lie. If you
need different settings, change the source configs and start a new workspace —
resuming with different invariants fails at startup by design.

## By lifetime

```
committed, version-controlled        →  task semantics, framework policy, operator configs
machine-local, gitignored            →  data roots, dashboard root, API keys
generated per workspace, pinned      →  effective health config, invariants lock
```

## Two things that are *not* config

- **Environment-only discovery** is used for legacy model/loss library paths
  (`SIDERIUS_PLUGIN_DIRS`, `SIDERIUS_LOSS_DIRS`); composed manifests may instead
  declare `model_plugins` and `loss_plugins` explicitly. These are distinct
  routes, not a YAML fallback for task science.
- **Data scope, budgets, round counts and gate enablement** are run-level CLI
  inputs, not configuration. `--health_gate_enabled` and `--health_gate_files` in
  particular are deliberately *not* YAML: they are per-run decisions that the
  invariants lock records.

## The most common confusion

> "I want the collapse check to be stricter."

The threshold lives in the roster entry's `parameters` in **your task's
health config** — the file your manifest's `task_health:` section names,
wherever it lives on disk. The shipped synthetic manifests and their declaration
files provide the in-repo examples: [`quickstart`](../../configs/task_composition/quickstart.yaml)
and [`synthetic masked regression`](../../configs/task_composition/synthetic_masked_regression.yaml).

> "I want a collapse to stop the round instead of just being recorded."

Flip that check's `disposition` to `blocking` in the same task health config.
What *blocking* then does is framework policy and you do not write it.

> "I want blocking failures to stop blocking, temporarily."

Select an explicit observe policy with `--health_checks_config /path/to/policy.yaml`
and declare `--healthgate_mode observe_only --result_authority diagnostic`.
The mode declaration checks consistency; it does not choose a policy file.

---

## Next

- [Task composition reference](task-composition.md)
- [Health gates](../concepts/health-gates.md)
- [Entrypoints and CLI](entrypoints.md)
