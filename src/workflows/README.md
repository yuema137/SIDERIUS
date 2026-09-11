# `workflows/` — deterministic graph traversals + task composition

**Audience**: a coding agent or engineer about to modify the workflow layer.
**Authority**: the source. This README is a map; where they disagree, the
module is right. Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../../docs/agent-reference/MODULE_README_TEMPLATE.md).

## Purpose

The pre-designed, deterministic paths through the node graph, and the
task-composition manifest that binds a whole run to one task's declarations.
A workflow is a script with a fixed sequence — *"a workflow, not an
orchestrator"* — never an agent choosing its own tools. This package contains
no shell entrypoints: the chain launchers live in
[`sdsc_submission_scripts/`](../../sdsc_submission_scripts/README.md), which call
into here one iteration at a time.

## Public interface

| file | surface |
|---|---|
| `model_exploration.py` | `run_workflow(*, launch, workspace, run_name, …) -> list[HyperparamTuningOutput]` — THE workflow: per iteration interpret → *(literature review)* → propose → implement → validate → tune. Also a module CLI (`python workflows/model_exploration.py --help`) accepting `--task_composition` |
| `task_composition.py` | `compose_run_task_bindings(manifest_path) -> RunTaskComposition` (resolve the manifest) · `bind_run_task_composition(composition, *, physical_data_root)` (the run-scoped binding contextmanager) · `verify_composition_is_bound` · `active_composition_fingerprint` / `active_task_manifest_path` |
| `run_config.py` | `WorkflowLaunchConfig` — the pure-transit launch config |
| `llm_config.py` | `WorkflowLLMConfig` — per-node LLM routing, loaded from a `--llm_config` JSON |
| `run_bindings.py` | `WorkflowRunBindings` — run-scoped authorities settled at startup; refuses mutable chain state by construction |
| `strategy_modes.py` | the `Literal` vocabularies for exploration/strategy/formal-round modes |

## Inputs

`workspace` + `run_name`; a `WorkflowLaunchConfig`; optionally a composition
manifest path (with a **mandatory** `--data_dir` when composed); LLM routing
JSON; a `RestoredState` when resuming; pseudo-mode factories for $0 smokes.

## Outputs

A list of `HyperparamTuningOutput`; the workspace record tree
(`{workspace}/{run_name}/…` — layout in
[workspaces and resume](../../docs/guides/workspaces-and-resume.md)); the run
invariants lock and effective health config (written via `core` /
`execute_tools.health_checks` authorities at startup).

## Owned semantics

- **The fixed iteration path** and its retry loop (proposal attempts, tuner
  invocation, record persistence).
- **Manifest resolution**: ten sections, five required
  (`_REQUIRED_KEYS`); an unknown key is *refused, not ignored*; `file:` plugin
  refs resolve against the manifest's own directory and their content sha
  joins the semantic fingerprint.
- **Run-scoped binding**: a composed run binds data path, profile, metric,
  secondaries, deliverable naming, task config for the whole run; an
  explicitly composed run **never falls back to TIDMAD**.
- Plugin registration into the workspace (`plugins/{run_name}/`) and — ⚠ a
  known checkout-mutation, see below — promotion into the repo-level
  `agent_generated/` library.

## Non-owned semantics

- Node internals → each node's `.md` under [`nodes/`](../nodes).
- Subprocess execution, resource ceilings → `core/sandbox_executor.py`
  ([execution mechanism](../../docs/agent-reference/mechanisms/execution.md)).
- Health policy and gate actions →
  [`execute_tools/health_checks/`](../execute_tools/health_checks/README.md).
- Lock and resume mechanics → `core/run_invariants.py`, `core/resume.py`
  ([persistence and resume](../../docs/agent-reference/mechanisms/persistence-and-resume.md)).
- Metric direction → `execute_tools/metric_order.py` (one authority).

## Extension points

- **A new task never edits this package.** It authors a manifest + out-of-tree
  plugins — see [define a task](../../docs/guides/define-a-task.md) and the
  [composition mechanism](../../docs/agent-reference/mechanisms/composition.md).
- Adding a *manifest section* is a framework change to `task_composition.py`
  with its resolver, fingerprint entry and censuses — not routine.

## State and filesystem effects

Creates `run_dir = {workspace}/{run_name}` and the per-iteration tree; snapshots
`configs/task_config.yaml` into the run dir (only if absent); writes the
workflow summary; calls `ensure_run_invariants` (chain-level lock). Sets
`SIDERIUS_CHAIN_WORKSPACE`; mirrors validated plugins into workspace dirs and
**promotes them into the checkout-level `agent_generated/` library, which every
later run on the same checkout preloads** — workspace state is isolated, that
library is not (recorded product gap; see
[workspaces and resume](../../docs/guides/workspaces-and-resume.md)).

## Failure modes

| refusal | meaning |
|---|---|
| `TaskCompositionError` (unknown key, double ref, missing file) | the manifest is wrong — misspelled sections never silently resolve a default |
| `CompositionDataRootMissing` | composed run without `--data_dir`, before any LLM/GPU work |
| `CompositionNotBoundError` | a code path reached execution without the run-scoped binding — a wiring defect, not an operator error |
| `RunInvariantsViolation` at startup | workspace lock mismatch — use a new workspace |
| literature review enabled without an explicit config | refused by name (`require_lit_review_config_when_enabled`); a task- or experiment-owned config is accepted |

## Files normally edited

Adding a launch-config field (`run_config.py` + the launcher plumbing); LLM
routing shapes (`llm_config.py`). Both are transit layers — validation lives
with the consumer.

## Files normally NOT edited

`model_exploration.py`'s orchestration body: the responsibility-decomposition
rule (CLAUDE.md) forbids adding new branching to it — extract a typed boundary
instead. `task_composition.py`'s fail-closed resolvers and fingerprint: guarded;
weakening a refusal into a fallback is the defect class the guards exist for.

## Minimal example

```bash
# one composed dry iteration, directly through the module CLI
.venv/bin/python workflows/model_exploration.py \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir /tmp/quickstart-data --workspace /tmp/ws --run_name demo_v1 \
    --source_run_name seed --max_iterations 1
```

For real runs use the chain launcher
([entrypoints](../../docs/reference/entrypoints.md)); start with `--dry-run`.

## Related tests

`tests/unit/workflows/` (incl. the run-state/carrier oracles) and
`tests/integration/workflows/` (pseudo-mode full-loop). The composition
fail-closed behaviour and the findings-union single-authority rule carry
dedicated structural guards.
