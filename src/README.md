# Framework source

This directory contains the existing Python packages. Install the selected
checkout with `uv sync --group dev --frozen` and use its `.venv/bin/python`.
Imports keep their names: `from core.layout import package_root`, never
`from src.core...`. Running from the repository root is not an installation.

| Package | Responsibility / entry documentation |
| --- | --- |
| [agent](agent/README.md) | LLM gateway, schemas, typed protocols, prompts and atomic skills |
| [nodes](nodes/README.md) | Six capabilities with adjacent contract documents; [node index](../docs/agent-reference/README.md#nodes) |
| [workflows](workflows/README.md) | Deterministic node sequencing, task composition and carried state |
| [core](core/README.md) | Subprocess isolation, workspace state, resources and recovery |
| [execute_tools](execute_tools/README.md) | Training, inference, scoring and [Health](execute_tools/health_checks/README.md) |
| [ml_models](ml_models/README.md) | Existing models, configurations and model/loss plugin loading |
| [dashboard](dashboard/README.md) | Read-only result API and packaged browser assets |
| [tools](tools/) | Importable developer tooling, including CI selection and execution |

Users start with [installation](../docs/getting-started/installation.md),
[examples](../examples/README.md) and [task declarations](../docs/reference/task-composition.md).
Developers follow [CLAUDE.md](../CLAUDE.md) and the [repository map](../docs/repository-map.md).

## Three locations, three owners

`core.layout.package_root()` locates installed code and adjacent assets: prompt
templates, vocabulary, skill declarations, model descriptions, dashboard files
and CI weights. The sandbox resolves its training/inference/scoring scripts
there and uses the selected interpreter; caller CWD and plugin transport retain
their existing meaning.

`core.layout.checkout_root()` returns only the exact source checkout, or `None`
for a wheel. Root configuration, examples, Git inventory and launch scripts are
checkout resources. Optional legacy reads retain their absence behavior;
checkout-required operations refuse when no checkout or explicit input exists.
A wheel does not discover a surrounding unrelated Git repository.

Task manifests, data, generated plugins and results belong to the caller's
workspace. Low-level consumers must bind the generated library before importing
its readers; see [workspace guidance](../docs/guides/workspaces-and-resume.md).
No writable run state belongs under `src/` or `site-packages`.

## Current entrypoints and installation checks

Chain scripts live in `scripts/launch/`; the one-iteration public entrypoint is
`src/workflows/run_one_iteration.py`, with supporting workflow code alongside
it in `src/workflows/`. Routing remains in `configs/llm/`,
and policy/manifests remain in `configs/`. Use the
[entrypoint reference](../docs/reference/entrypoints.md).
For package CLIs, `.venv/bin/python -m dashboard.main` retains the import name;
direct source paths now start with `src/`.

The wheel ships owned code/resources, not checkout launch scripts, synthetic
packs, machine configuration or scientific reference data. Wheel consumers
supply their task/config/data/workspace explicitly. Source checkout workflows
continue to use the checkout's frozen editable installation.

The [installation witness](../tests/integration/installed_package_witness.py)
is a manual CPU integration check, not part of ordinary unit execution. It
stages the shipped synthetic pack externally and runs actual training,
inference, scoring and Health persistence. Invoke it from a neutral CWD with
the selected environment's absolute Python path, `-I`, no `PYTHONPATH`, at most
two OMP/OpenBLAS/MKL threads and a 120-second timeout. Required arguments are
`--expected-root` (editable `src` or wheel `site-packages`), `--checkout`
(synthetic input source) and `--workspace` (new external directory).
`--resources-only` omits training. A valid Health rejection is retained; the
witness checks enforcement and installation, not trained-model quality.

Independent wheel and source-distribution builds, resource-byte comparisons,
wrong-origin/missing-asset controls and both installed lifecycle results are
recorded in the PR. External scientific qualification belongs to the paired
experiment repository and is not established by this synthetic check.
