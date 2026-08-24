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

```mermaid
flowchart TD
    I["<b>interpret</b><br/>what does the evidence so far support?"] --> P["<b>propose</b><br/>an architecture + an explicit prediction"]
    P --> M["<b>implement</b><br/>write the model plugin"]
    M --> V["<b>validate</b><br/>does the code hold up?"]
    V --> T["<b>tune</b><br/>N rounds: plan → train → infer → score → health → reflect"]
    T --> I
```

An optional literature-review stage runs between interpretation and proposal,
surfacing recent papers as soft priors.

## Who provides what

```mermaid
flowchart LR
    subgraph you["YOU DECLARE — a task package"]
        direction TB
        A["how your data is read"]
        B["what a model reads and produces"]
        C["the training objective"]
        D["what 'better' means"]
        E["what makes an output invalid"]
    end
    subgraph fw["SIDERIUS PROVIDES"]
        direction TB
        F["the agent loop"]
        G["training / inference / scoring"]
        H["resource gating, retries, resume"]
        J["provenance and reproducibility"]
    end
    you -->|"one composition manifest"| fw
```

Nothing about your task is hardcoded in framework source. A **task package** is
one YAML manifest — ten possible sections, five required — plus whatever small
amount of Python the framework cannot supply generically for your data. A package
can live entirely outside this repository.

→ [What a task must provide](docs/concepts/task-package.md) ·
[the full section table](docs/reference/task-composition.md)

## Three numbers that are not the same thing

This distinction is the one most worth understanding before you start:

| | question | who consumes it |
|---|---|---|
| **training objective** | what is optimisation minimising right now? | the optimiser |
| **primary metric** | how good is the finished model, scientifically? | **model selection** |
| **health gate** | is this output valid enough to be worth trusting? | the loop's control flow |

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

SIDERIUS is contract-driven rather than modality-limited — nothing in its source
branches on a task name. Three example tasks exist as evidence of tested breadth,
**at deliberately different maturity**:

| example | shape | status |
|---|---|---|
| **TIDMAD** | 1-D scientific signal denoising (SQUID time series, axion dark-matter search) | ✅ runs the full agent loop end-to-end through the production chain |
| **Oxford-IIIT Pet** | RGB image, 37-way breed classification | 🟡 real data, training, inference and scoring — through a direct-execution harness, **not** the production chain |
| **DAVIS 2017** | RGB spatiotemporal, 8→4 future-frame prediction | 🟡 same |

The difference is real and this documentation states it everywhere it matters:
the execution path below the composition edge is not yet task-neutral end to end,
so the contrast tasks cannot currently run the chain. Closing that is in flight.

→ [Supported tasks and current maturity](docs/concepts/supported-tasks.md) —
current state and target state in one table

## Quickstart

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone git@github.com:Galileo-Sandbox/SIDERIUS.git && cd SIDERIUS
uv sync && source .venv/bin/activate

cp tidmad_data_config.example.yaml tidmad_data_config.yaml   # edit paths
cp dashboard_config.example.yaml   dashboard_config.yaml
printf 'OPENAI_API_KEY=...\n' > .env

python env_validation/test_agent_env.py     # environment + API reachability
uv run pytest tests/unit/ -q                # no GPU, no API calls
```

Then see what a real run would execute, without executing it:

```bash
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    --workspace /path/to/workspace --run_name first_run_v1 \
    --task_composition configs/task_composition/tidmad.yaml \
    --data_dir /path/to/tidmad/data \
    --num_iterations 1 --max_rounds 1 --dry-run
```

→ [Installation](docs/getting-started/installation.md) ·
[Your first run](docs/getting-started/first-run.md)

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
| developing the framework | [Agent reference](docs/agent-reference/README.md) → [`CLAUDE.md`](CLAUDE.md) |

Full map: [`docs/README.md`](docs/README.md). Glossary:
[`docs/concepts/glossary.md`](docs/concepts/glossary.md).

## Repository layout

```
agent/          LLM transport (one gateway), schemas, typed protocols, atomic skills
nodes/          the six workflow nodes, one directory each, each with its .md
workflows/      deterministic graph traversals + task composition
core/           sandbox executor, hardware context, resume, run invariants
execute_tools/  training / inference / scoring subprocesses, data paths, metrics,
                health checks
ml_models/      built-in models + loss configs + plugin loader
agent_generated/  LLM-written model and loss plugins (gitignored)
configs/        task semantics and framework policy — see the configuration map
examples/       the three example task packages
sdsc_submission_scripts/  chain launchers (--mode lilab | sdsc)
scripts/        standalone runners and baselines
dashboard/      FastAPI + Plotly result browser
docs/           documentation (see the map) + design history
tests/          unit + integration tiers
```

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

```bash
uv run pytest tests/unit/ -q          # CI gate: mocked LLM, no GPU
uv run pytest tests/integration/ -q   # full orchestration, predefined responses, ms
```

Real-API and real-training tiers are opt-in (`--real-api-call`,
`--real-training`, `-m real_run`) and skip automatically without the required
keys. They never run in CI.

## License

(To be added.)
