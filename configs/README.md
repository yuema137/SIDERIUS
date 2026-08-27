# `configs/` — committed configuration: task reference packaging + framework policy

**Audience**: a coding agent or engineer wondering what a file in this
directory is, and who owns it.
**Authority**: the source that loads each file. The user-facing ownership map
is [docs/reference/configuration-map.md](../docs/reference/configuration-map.md)
— this README is the directory-level view and does not restate it.
Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../docs/agent-reference/MODULE_README_TEMPLATE.md).

## Purpose

The version-controlled configuration shipped with the repository. Two very
different kinds of thing live here, and confusing them is the classic
mistake: **task semantics** (TIDMAD's reference declarations, plus the
shipped example manifests — *reference packaging*, which an external task
replaces with its own files anywhere on disk) and **framework policy** (what
a health failure *does* — which no task file can express).

## Public interface

| path | kind | loaded by |
|---|---|---|
| `task_composition/{tidmad,pets,davis,quickstart}.yaml` | shipped composition manifests — pointers into task declarations, resolved relative to the manifest file | `workflows/task_composition.py` |
| `task_config.yaml` (+ `.example`) | TIDMAD's `task_description` + `forward_contract` (legacy un-composed runs read it directly) | task-config loader |
| `task_health/tidmad.yaml` | TIDMAD's task-owned health family: roster, thresholds, peek files, value scale, prose | `execute_tools/health_checks/_task_health_config.py` via composition |
| `task_proposal/` · `task_implementor/` · `task_interpretation/` | TIDMAD's task-science prompt blocks | the three task-blocks adapters |
| `health_checks.yaml` | **framework policy only**: per-disposition gate role, cadence, short-circuit, `on_pass`/`on_fail`, and the default `aggregation` | `execute_tools/health_checks/config.py` |
| `health_checks_baseline_observe_mode.yaml` | same policy with blocking failures downgraded to observation (differs only in `blocking.on_fail`) | selected via `--healthgate_mode observe_only` |
| `lit_review_config.yaml` | literature-review budget, root papers, rubric | the literature-review node |
| `v17_pregate_threshold_review.json` | a frozen point-in-time review artifact | nothing at runtime |

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
- **In-repo task files are reference packaging.** An external task supplies
  its own manifest and declaration files anywhere on disk; nothing requires
  a file to be added under `configs/` to run a new task.

## Non-owned semantics

- What a manifest may declare → the
  [task composition reference](../docs/reference/task-composition.md) and its
  authority `workflows/task_composition.py`.
- What each health field means →
  [`execute_tools/health_checks/`](../execute_tools/health_checks/README.md).
- Machine-local paths (`tidmad_data_config.yaml`, `dashboard_config.yaml`,
  `.env`) — gitignored siblings at the repository root, not here.

## Extension points

- **A new task is a new manifest anywhere on disk**, passed via
  `--task_composition` — not a file added here. The shipped manifests are
  worked examples.
- **A different framework policy** is a run input: `--healthgate_mode
  observe_only` for the shipped observe-mode variant, or
  `--health_checks_config /path/to/policy.yaml` for a custom policy file.
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
| resume after editing a composed-in file | the pinned digest moved — new semantics, new workspace |

## Files normally edited

`llm_configs/`-routed stages aside, the legitimate edits here are:
TIDMAD-reference maintenance with citation (the same discipline as
`ml_models/legacy_baseline_configs.json`), and framework-policy changes as
deliberate, reviewed framework PRs — never as a per-task step.

## Files normally NOT edited

`health_checks.yaml` to change a *threshold* (thresholds are task-owned);
any `task_*` file to onboard a *new* task (write your own files instead —
see [define a task](../docs/guides/define-a-task.md)).

## Minimal example

```bash
bash sdsc_submission_scripts/run_chain.sh … \
    --task_composition configs/task_composition/tidmad.yaml --data_dir …
```

## Related tests

`tests/unit/execute_tools/health_checks/` (policy shape, composition,
ownership refusals), `tests/unit/examples/test_quickstart_pack.py` (the
shipped quickstart manifest composes), workflow composition suites under
`tests/unit/workflows/`.
