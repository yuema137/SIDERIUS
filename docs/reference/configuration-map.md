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

These describe your science. An external task supplies its own versions anywhere
on disk; the in-repo TIDMAD copies are **reference packaging, not a framework
dependency**.

| file | declares |
|---|---|
| `configs/task_composition/<task>.yaml` | the manifest — see [task composition](task-composition.md) |
| `configs/task_config.yaml` | `task_description` + `forward_contract` |
| `configs/task_health/<task>.yaml` | health roster, **thresholds**, peek files, value scale, prose |
| `configs/task_proposal/<task>.yaml` | task science rendered into proposer prompts |
| `configs/task_implementor/<task>.yaml` | task science rendered into implementor prompts |
| `configs/task_interpretation/<task>.yaml` | task science rendered into interpreter prompts |
| a metric declaration JSON | metric id, direction, aggregation, scoreability |
| a dataset profile JSON | partition count, anchors, peek set, opaque topology |

When a composed run omits a task-owned declaration, the corresponding binding
is absent and the task composition loader refuses any operation that requires
it; the framework does not silently select another task's science. Paths named
inside a composition manifest resolve relative to that manifest. Caller-owned
paths may also be absolute when the contract permits them.

### Framework policy — the framework's, selectable per run

| file | declares | when a run gets it |
|---|---|---|
| `configs/health/health_checks.yaml` | what a health failure **does**: gate role, cadence, short-circuit, `on_pass`/`on_fail` | the default |
| `configs/health/health_checks_baseline_observe_mode.yaml` | the same, with blocking failures downgraded to observation | `--healthgate_mode observe_only` — a diagnostic campaign |

A run that needs different consequences selects its own policy file with
`--health_checks_config /path/to/policy.yaml`; the shipped pair is the
framework's, not a per-task customization surface.

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

- **Model and loss plugins** are found by environment variable
  (`SIDERIUS_PLUGIN_DIRS`, `SIDERIUS_LOSS_DIRS`), not by any YAML file.
- **Data scope, budgets, round counts and gate enablement** are run-level CLI
  inputs, not configuration. `--health_gate_enabled` and `--health_gate_files` in
  particular are deliberately *not* YAML: they are per-run decisions that the
  invariants lock records.

## The most common confusion

> "I want the collapse check to be stricter."

The threshold lives in the roster entry's `parameters` in **your task's
health config** — the file your manifest's `task_health:` section names,
wherever it lives on disk. (The shipped TIDMAD reference is the in-repo
example of the format.)

> "I want a collapse to stop the round instead of just being recorded."

Flip that check's `disposition` to `blocking` in the same task health config.
What *blocking* then does is framework policy and you do not write it.

> "I want blocking failures to stop blocking, temporarily."

Launch with `--healthgate_mode observe_only`.

---

## Next

- [Task composition reference](task-composition.md)
- [Health gates](../concepts/health-gates.md)
- [Entrypoints and CLI](entrypoints.md)
