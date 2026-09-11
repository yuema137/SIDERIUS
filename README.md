# SIDERIUS

### **S**cientific **I**nquiry, **D**esign, **E**xploration, and **R**easoning **I**ntegrated **U**sing multi-agent **S**ystems

**A closed-loop research framework for supervised scientific machine learning.**
You describe a scientific task; SIDERIUS runs the loop a research group would run
— read the evidence, propose a model, implement it, check it, train it, score it,
judge whether the result is trustworthy, interpret what happened, and go again.

> *"All truths are easy to understand once they are discovered; the point is to
> discover them."* — Galileo Galilei

---

## Why you might want it

You have a supervised scientific problem, a way to measure success, and more
architectural ideas than time to try them.

SIDERIUS automates the *research* loop, not just the search. The parts that
require judgement — reading diagnostic evidence, forming a hypothesis about why
the last attempt behaved as it did, deciding what to try next — are performed by
LLM agents. The parts that must be exact — data selection, training, scoring,
validity checking, provenance — are deterministic code, and no agent is allowed
to influence them.

It is **not** an AutoML library (it writes new model code rather than searching a
fixed space), **not** a general agent framework (the workflow is a fixed,
deterministic path), and **not** a hyperparameter sweeper (tuning is one phase
inside a larger loop).

## The loop

![The SIDERIUS discovery loop](docs/assets/discovery-loop.svg)

An optional literature-review stage runs between interpretation and proposal,
surfacing recent papers as soft priors.

## Who provides what

![What you declare versus what SIDERIUS provides](docs/assets/ownership-split.svg)

A **task package** declares your task through
one YAML manifest — thirteen possible sections, five required — plus whatever small
amount of Python the framework cannot supply generically for your data. A package
can live entirely outside this repository. Remaining scientific compatibility
helpers are listed in the [repository map](docs/repository-map.md#retained-and-mixed-material).

→ [What a task must provide](docs/concepts/task-package.md) ·
[the full section table](docs/reference/task-composition.md)

## Four numbers, and only one of them decides

This distinction is the one most worth understanding before you start:

![The four quantities a run produces and who consumes each](docs/assets/three-kinds-of-number.svg)

Only the **primary metric** selects models. Additional **secondary metrics** are
observational evidence and influence no ordering anywhere — deliberately, so that
watching six quantities does not silently turn your run into a multi-objective
optimisation nobody declared.

A **health gate PASS is not a scientific success.** It means nothing detectably
invalid — a model can pass every gate and be useless. Gates exist to catch
collapse before it burns GPU-hours.

→ [Objectives and metrics](docs/concepts/objectives-and-metrics.md) ·
[Health gates](docs/concepts/health-gates.md)

## What has actually been demonstrated

Two synthetic packages ship as executable framework specifications:

| package | contract coverage |
|---|---|
| [Quickstart](examples/quickstart/README.md) | caller-owned classification task, generated data and CPU lifecycle walkthrough |
| [Synthetic masked regression](examples/synthetic_masked_regression/README.md) | continuous targets with validity masks, lower-is-better primary metric, secondary metric and task-owned Health |

Real scientific packages, including TIDMAD, Oxford-IIIT Pet and DAVIS, now live
in the external `siderius-exp` repository. Its retained run receipts describe
their named revisions and workloads; they do not qualify today's checkout.
The current tuner invokes the inference/scoring/Health phase for composed runs;
which checks apply comes from task declarations and framework policy.
See the [external-consumer map and evidence](docs/repository-map.md#external-consumer-and-evidence)
for task locations, the inspected dependency pin and evidence limitations.

→ [Supported tasks and current maturity](docs/concepts/supported-tasks.md) —
current state and target state in one table

## Quickstart

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone git@github.com:Galileo-Sandbox/SIDERIUS.git && cd SIDERIUS
uv sync --group dev --frozen

cp dashboard_config.example.yaml   dashboard_config.yaml
printf 'OPENAI_API_KEY=...\n' > .env

.venv/bin/python scripts/diagnostics/check_agent_environment.py  # optional; calls provider APIs
```

Use this checkout's `.venv/bin/python`; do not reuse another checkout's venv
or source through `PYTHONPATH`. The API diagnostic requires configured
credentials. For a credential-free introduction, use the synthetic pack below.

Installation exposes the eight packages from `src/`. Existing imports such as
`from core.layout import package_root` keep their names. See the
[source guide](src/README.md) for package, checkout and workspace ownership.

Then see what a real run would execute, without executing it:

```bash
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    --workspace /path/to/workspace --run_name first_run_v1 \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir /path/to/workspace/quickstart_data \
    --llm_config llm_configs/openai_tiered_pro.json \
    --num_iterations 1 --max_rounds 1 --dry-run
```

Always pass an explicit `--llm_config` (the file shown is the canonical
example) — omitting it silently selects a deprecated all-Gemini default.

**The fastest way in is the synthetic quickstart pack**,
[`examples/quickstart/`](examples/quickstart/) — a 14-section executable
notebook that composes a real manifest, materializes generated data, and
walks the whole lifecycle on CPU in minutes, with no dataset download and no
GPU. It ships complete: declarations, three plugins, a shipped manifest at
`configs/task_composition/quickstart.yaml`, and its own pack tests.

→ [Installation](docs/getting-started/installation.md) ·
[Your first run](docs/getting-started/first-run.md)

## Fresh runs and resume

Two verbs, decided by the workspace you point at: a new directory is a
**fresh** run; re-running the same command against an existing workspace
**resumes** it from the first incomplete iteration (auto-resume is the
default). Changing the declared semantics — data scope, health configuration —
against an existing workspace is **refused at startup** by the invariants
lock, because aggregate scores are only comparable within one declared
identity. New settings, new workspace.

→ [Workspaces and resume](docs/guides/workspaces-and-resume.md)

## Extending SIDERIUS

The principle: **infrastructure specifies protocols; scientific semantics live in
task packages.** Adding a task should never require editing framework source.

You need only configuration when the framework already has a generic
implementation of what you need — several health checks, for instance, are
reusable by any task of the right shape. You need a plugin when your data access
or your metric mathematics is genuinely yours. Either can be declared by
importable module or by file path, and a file-declared plugin's content hash
joins the run's identity, so an edited plugin is detected rather than silently
used.

→ [Define your own task](docs/guides/define-a-task.md)

## Documentation

| you are… | start at |
|---|---|
| new here | [What SIDERIUS is](docs/concepts/overview.md) → [Quickstart](docs/getting-started/installation.md) |
| building a task | [What a task must provide](docs/concepts/task-package.md) → [Define your own task](docs/guides/define-a-task.md) |
| running experiments | [Operating a run](docs/guides/operating-a-run.md) → [Entrypoints](docs/reference/entrypoints.md) |
| looking at a workspace, or debugging one | [Workspaces and resume](docs/guides/workspaces-and-resume.md) → [Troubleshooting](docs/guides/troubleshooting.md) → [Dashboard](docs/guides/dashboard.md) |
| developing the framework | [Agent reference](docs/agent-reference/README.md) → [`CLAUDE.md`](CLAUDE.md) |

Full map: [`docs/README.md`](docs/README.md). Glossary:
[`docs/concepts/glossary.md`](docs/concepts/glossary.md).

## Repository layout

The eight framework packages live under `src/`; user inputs, examples and
developer tests remain separate at the root.
The [repository map](docs/repository-map.md) lists every tracked root, source
owners, launch paths, external data/workspaces and retained exceptions.

```text
SIDERIUS/
├── src/                     # agent, nodes, workflows, core, execute_tools,
│                            # ml_models, dashboard, tools
├── examples/                # synthetic executable specifications
├── configs/ + llm_configs/   # existing policy, manifests and routing
├── sdsc_submission_scripts/ # existing chain/iteration and scheduler entrypoints
├── tests/ + scripts/        # validation and checkout utilities
├── docs/                    # guides, references and design history
└── .github/                 # automatic CI
```

`scripts/`, `src/execute_tools/` and `configs/` contain mixed material.
Trial anchor maps are explicit caller/task-owned inputs read by
`execute_tools.trial_anchor_map.load_anchor_map`; this checkout provides no
scientific default or builder. Generated libraries and runtime results belong
to caller-owned storage, outside the source inventory.

The major modules carry their own contract READMEs —
[`workflows/`](src/workflows/README.md) · [`core/`](src/core/README.md) ·
[`execute_tools/`](src/execute_tools/README.md) ·
[`execute_tools/health_checks/`](src/execute_tools/health_checks/README.md) ·
[`ml_models/`](src/ml_models/README.md) ·
[`agent/schemas/`](src/agent/schemas/README.md) — all following one
[template](docs/agent-reference/MODULE_README_TEMPLATE.md).

## Key invariants

Before contributing, four rules that are enforced, not aspirational:

1. **Pydantic at every boundary.** LLM output → schema → execution. Execution
   reads the validated object, never a raw dict.
2. **Nodes communicate only through schemas, protocols and their own storage.**
   Storage is a log, not a channel; reading a peer's output file is a defect.
3. **One LLM gateway.** Every agent call routes through `agent/llm_bridge`;
   direct provider constructors elsewhere are CI-banned.
4. **One authority per rule.** Metric direction has exactly one interpreter;
   deliverable naming has one owner. Re-inlining any of them is the defect the
   guards exist to catch.

Full standards: [`CLAUDE.md`](CLAUDE.md).

## Testing

Use this checkout's `.venv/bin/python -m pytest` with the affected test files.
Test ownership and bounded Gate requirements are defined in
[`CLAUDE.md`](CLAUDE.md) and the [Gate standard](docs/gates/gate_testing_standard.md).
Integration tests include pseudo and opt-in real execution; the whole directory
is not a millisecond, credential-free smoke command. A tracked test is not
evidence that it ran in CI. The [repository map](docs/repository-map.md#minimal-entry-checks)
links the selected P0 checks and states what they establish.

## Contributing

One command is the local gate — no GPU, no dataset, no API key:

```bash
make check   # ruff check · ruff format --check · pyright (when runnable) · unit tier
```

It runs the same commands as CI's quality job (`.github/workflows/ci.yml`),
and the one supported environment for it is `uv sync --group dev --frozen` —
exactly what CI installs. The runtime bound, the pyright skip rule, what the
gate does *not* cover, and the pre-PR expectation:
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Availability and license

SIDERIUS is in a **closed beta**: the source is shared with invited
collaborators for research use, and is not yet licensed for redistribution
or reuse outside that collaboration. An open-source license will be chosen
before public release; until then, all rights are reserved and the package
metadata deliberately carries no license field.
