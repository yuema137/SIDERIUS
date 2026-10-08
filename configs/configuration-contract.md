# `configs/` — committed framework policy and synthetic example composition

Technical inventory for this module. Start with [the directory guide](README.md)
for navigation. Source and tests determine current behavior.

## Purpose

The version-controlled configuration shipped with the repository contains
framework policy and pointers to lightweight synthetic examples. Real task
semantics and experiment treatment belong to caller-owned packages.

## Public interface

| path | kind | loaded by |
|---|---|---|
| `task_composition/{quickstart,synthetic_masked_regression}.yaml` | pointers to the two lightweight framework examples | `workflows/task_composition.py` |
| `task_config.example.yaml` | copyable shape example; never a runtime default | task-config documentation |
| packaged `execute_tools/health_checks/resources/health_checks.yaml` (outside this directory) | **framework policy only**: per-disposition role, cadence, short-circuit, actions and default aggregation | omitted `--health_checks_config`; public `default_health_policy_path()` accessor |
| `health/health_checks_baseline_observe_mode.yaml` | optional policy with blocking failures downgraded to observation | explicit `--health_checks_config` plus declared `--healthgate_mode observe_only` |

## Inputs

None — these files *are* inputs, to composition and to run startup.

## Outputs

At startup, framework policy + the task's health config compose into
`{workspace}/health_checks_effective.yaml`, sha256-pinned by the
run-invariants lock. Runtime reads the **composed** artifact, never the raw
pair.

## Owned semantics

- **The policy/threshold split**: `health_checks.yaml` carries no task
  identity — no roster, no thresholds, no science prose — and must never
  grow a `tidmad:`/`pets:`/`<task>:` branch. Thresholds live in the *task's*
  health config; a roster entry stating a framework key (`on_fail`,
  `gate_role`, `short_circuit`, …) is refused at parse time.
- **`aggregation` is the one declarable policy key** (F-SCAND-2). A roster
  entry may set it per gate — `any_pass`, `all_pass`, `max`, `min`, `mean`,
  `median` — and an unimplemented mode is refused at parse time, not at gate
  evaluation. The framework's `health_policy.<disposition>.check_config`
  value is the **default** for entries that stay silent, so a task may
  tighten one gate without touching the others. Everything else in
  `check_config` is injected unconditionally. See
  `TASK_DECLARABLE_POLICY_KEYS`.
- **Real task files are external inputs.** An external task supplies its own
  manifest and declaration files anywhere on disk; nothing requires a file to
  be added under `configs/` to run a new task.

## Non-owned semantics

- What a manifest may declare → the
  [task composition reference](../docs/reference/task-composition.md) and its
  authority `workflows/task_composition.py`.
- What each health field means →
  [`execute_tools/health_checks/`](../src/execute_tools/health_checks/README.md).
- Machine-local dashboards and secrets (`dashboard_config.yaml`, `.env`) —
  gitignored siblings at the repository root, not here. Physical dataset
  roots are explicit caller inputs (`--data_dir`), never framework config.

## Extension points

- **A new task is a new manifest anywhere on disk**, passed via
  `--task_composition` — not a file added here. The shipped manifests are
  worked examples.
- **A different framework policy** is a run input:
  `--health_checks_config /path/to/policy.yaml`. For observe-only consequences,
  select the optional observe file (or an external equivalent) and declare
  `--healthgate_mode observe_only --result_authority diagnostic`; mode alone
  does not select a policy. Installed users never need to edit site-packages.
- Run-level decisions (`health_gate_enabled`, `health_gate_files`, data
  scope, budgets) are deliberately **CLI inputs, not YAML**.

## State and filesystem effects

None at rest. Composition digests the resolved content of task files into
the run's semantic fingerprint, so an edit between a run and its resume is
detected at startup.

## Failure modes

| refusal | meaning |
|---|---|
| unknown manifest key | misspelled section — refused, never ignored |
| `task_health` declaring both `none: true` and `config:` | contradictory — a task has a family or explicitly has none |
| roster `parameters` carrying a framework-owned key | the ownership split working (see `FRAMEWORK_OWNED_PARAMETER_KEYS`) |
| roster `parameters` carrying an unimplemented `aggregation` | the one declarable policy key, checked against the runtime vocabulary at parse time |
| roster `parameters` carrying a blank `aggregation:` | YAML `null` is a declaration, so the framework default is withheld and nothing can act on the value — omit the key to inherit the default |
| resume after editing a composed-in file | the pinned digest moved — new semantics, new workspace |

## Files normally edited

`configs/llm/`-routed stages aside, the legitimate edits here are:
Framework-policy changes as deliberate, reviewed framework PRs — never as a
per-task step.

## Files normally NOT edited

`health_checks.yaml` to change a *threshold* (thresholds are task-owned);
any `task_*` file to onboard a *new* task (write your own files instead —
see [define a task](../docs/guides/define-a-task.md)).

## Minimal example

```bash
bash scripts/launch/run_chain.sh … \
    --task_composition configs/task_composition/quickstart.yaml --data_dir …
```

## Related tests

`tests/unit/execute_tools/health_checks/` (policy shape, composition,
ownership refusals), `tests/unit/examples/test_quickstart_pack.py` (the
shipped quickstart manifest composes), workflow composition suites under
`tests/unit/workflows/`.
