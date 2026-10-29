# SIDERIUS

**S**cientific **I**nquiry, **D**esign, **E**xploration, and **R**easoning
**I**ntegrated **U**sing multi-agent **S**ystems

**Turn your dataset and research question into an iterative ML experiment.**
Work with your coding agent to define the task and write the experiment as a
short Python workflow file; SIDERIUS then helps propose models, implement them,
train and evaluate them, and use the results to guide the next attempt.

![Physics time-series results: SIDERIUS validation R² against S4D references](docs/assets/results/physics.svg)

![Cancer gene identification: best Formal test AUPRC with adaptive test feedback, against TREE references](docs/assets/results/cancer.svg)

Sources: [SIDERIUS paper (arXiv:2610.14024)](https://arxiv.org/abs/2610.14024) ·
[TREE paper](https://doi.org/10.1038/s41551-024-01312-5) ·
[Comparison data and evaluation conditions](docs/assets/results/provenance.md).

- **Run an experiment cycle:** go from a hypothesis to model code, measured results
  and the next experiment, with a record of each attempt.
- **Evaluate more than a score:** declare task-specific validity checks alongside
  your metric, with controlled data access and reproducible evaluation rules.
- **Choose how to explore:** start with a lightweight fixed workflow or let an
  LLM orchestrator compose research steps. Select models independently by role.

See [supported providers and models](docs/reference/model-qualification.md) for
required model capabilities and the configurations tested so far.

<a id="start-with-your-coding-agent"></a>

## Quick start with your coding agent

Before you start, you need **Python 3.12+ and uv**, your dataset location, and a
project directory outside this checkout for your task, settings and results.
A real run trains models and needs an **NVIDIA GPU with CUDA** on the machine
that runs it; there is no CPU mode. A run on a machine without one stops before
any model call and says so. Setup checks and the synthetic Quickstart checks
run on CPU.
Use this checkout's own `.venv/bin/python` after installation. Provider keys
are needed for real model calls; offline setup checks need none.
The command line and the experimental browser console read them from different places; see
[API keys](docs/getting-started/installation.md#api-keys).
Preparing and running a workflow uses the Linux sandbox bubblewrap; run the
[bubblewrap check](src/tools/workspace_sandbox/README.md#check-that-bubblewrap-works)
once on that machine.

Follow [getting started](docs/getting-started/README.md) for the ordered setup,
where to put credentials, and the commands that prepare and run a workflow.

Clone the repository and open it in your coding agent:

```bash
git clone https://github.com/yuema137/SIDERIUS.git
cd SIDERIUS
uv sync --group dev --frozen
```

**Professional and Assistant are the main ways to use SIDERIUS 1.1.** Both
start with a short request to your coding agent. They describe how you
collaborate, not software mode switches; both produce the same files and use
the same commands. You can also write everything by hand.

| Way of working | Who leads? |
| --- | --- |
| **Professional** | You choose the research plan; your agent helps implement it. |
| **Assistant** | You describe the problem; your agent guides you through the choices. |

### Professional: bring your plan

For a lightweight fixed workflow, paste:

```text
Use SIDERIUS in Professional style. My MNIST images and labels are in /data/mnist.
Build a digit-classification task package in ~/mnist-research, then write the
experiment as a workflow declaration ~/mnist-research/workflow.py: the interpreted
training workflow as a research loop of at most three iterations. Keep the test
split out of search feedback; optimize validation accuracy. Help me set model
routing, training budgets and stop conditions, then show me workflow.py, the
LLM profile, the preparation request and the result paths before preparing
or launching anything.
```

For orchestration, replace the execution request with:

```text
Use orchestration instead of the fixed workflow. Set up the external project and
sandbox so my agent can choose which SIDERIUS capabilities to call and when,
within the data-access rules and budgets we agree on.
```

You do not need to write configuration files first. Your agent can turn your
plan into a [task package](docs/reference/task-composition.md) and experiment.

### Assistant: describe your problem

Paste:

```text
Use SIDERIUS in Assistant style. I have MNIST images and labels in /data/mnist;
help me build and evaluate a digit classifier. Follow this repository's setup
guidance, help me choose workflow or orchestration, and prepare an external
project with the environment, task package, workflow declaration (workflow.py)
and the commands to prepare and run it.
```

Your agent follows the [setup guidance](docs/agent-reference/siderius-setup-review/SKILL.md):
it inspects your data and hardware, helps agree on splits and metrics, prepares
the environment and API-key setup, and saves the task and experiment in your own
project. It shows the exact launch command and where to find results.
No global skill installation is needed.

Replace the example data and project paths with your own. In either style,
you control the scientific choices and paid execution; the agent asks about
missing decisions before launching. A [configuration review and HTML report](src/tools/setup_review/README.md)
is optional. See [getting started](docs/getting-started/README.md) for installation
and detailed setup.

### What your agent sets up

With a fixed workflow, in either style, the experiment is an ordinary Python
file in your project, so you can read every setting before anything runs:

1. **Task package**: `task.yaml` and the plugins it names (data access, splits,
   model input and output, main score, Health checks).
2. **Workflow declaration** (`workflow.py`): which research steps run, your
   advice to each step, training budgets and, for a research loop, its
   iteration limit and stop conditions. Ready-made starting points are in
   [`examples/workflow_declarations/`](examples/workflow_declarations/).
3. **LLM profile** (`llm.json`): which model and provider serve each role.
4. **Preparation and launch**: the agent prepares the workflow offline with
   `python -m tools.candidate_prepare --reusable-request ...`, shows you what was
   captured, and launches only when you say so with
   `python -m tools.candidate_operations submit ...`. The same tool reports
   status and logs, and stops, pauses or resumes a research loop between
   iterations, optionally with new advice.

The [workflow guide](docs/getting-started/README.md#write-and-run-a-workflow-declaration)
lists these steps with their commands. An experimental browser console can also
show and run the same files; see [below](#try-the-browser-console-experimental).

### Choose the execution: workflow or orchestration

Either collaboration style can use either execution approach:

| Execution | What happens | When to choose it |
| --- | --- | --- |
| **Fixed workflow: lightweight starting point** | Research capabilities run in a predefined sequence, without an extra LLM deciding each next call. | Start quickly with lower coordination overhead and a predictable research loop. |
| **Orchestration: flexible exploration** | An LLM caller chooses and combines capabilities as evidence arrives. | Explore beyond a fixed sequence, with more setup and potentially higher LLM cost. |

**Workflow keeps coordination lightweight; orchestration offers more room to
adapt the research process.** In the paper's TIDMAD comparison, fixed workflows
had the lowest estimated LLM cost, while orchestration without Data Analysis
produced the most valid models and the best valid score. This demonstrates its
potential, not a guarantee that orchestration wins on every task.

[![Paper Figure 3: valid and non-valid TIDMAD models versus estimated LLM cost](docs/assets/paper/figure3.svg)](docs/assets/paper/figure3.svg)

**Figure 3. Exploration and LLM cost on TIDMAD.** The left panel counts valid
models; the right counts non-valid models. Costs are estimates and exclude GPU
training. See the [paper](https://arxiv.org/abs/2610.14024) for the experimental
conditions, or the [orchestration setup guide](src/tools/orchestration_setup/README.md)
to prepare your own caller and sandbox.

### Choose models by role

Without a model configuration, the standard workflow uses **GPT-5.6 Luna for
every role**, with medium reasoning and no automatic retries for 429/5xx
responses. Timeout and workflow retries have separate controls.
Start with a small flow check; stronger models are an explicit choice.
You can save the [default profile](configs/llm/default.json) with your experiment.
Your coding agent’s own model and the models called inside the experiment are
separate choices.

**For research runs, we recommend
[`openai-moderate-v1.json`](configs/llm/openai-moderate-v1.json).** It uses
`gpt-6-astra` for all three proposer stages and the validator, and
`gpt-5.6-luna` for the other workflow roles, all with `medium` reasoning.

SIDERIUS lets you choose a supported model and provider independently for each
role. You can allocate stronger models to proposal and validation while using
lighter models elsewhere, then adjust individual roles for your task and budget
without changing the workflow code. See the [configuration guide](configs/llm/README.md)
to copy a profile into your project and select it at launch. Model selection does
not set a spending limit or guarantee better scores; paper replay keeps its
[recorded experiment configurations](https://github.com/yuema137/siderius-exp).

## Try the browser console (experimental)

The browser console is **experimental** in SIDERIUS 1.1. It is useful for
seeing every step once on a small example, and it can open, edit and run a
workflow file, but its screens and settings may change between releases. Use
the coding-agent route above for your research runs, and check the saved
`workflow.py` rather than the screen when you need to know exactly what runs.

The console path has two stages, written out command by command, with the
output to expect, in the
[console first-hour path](docs/getting-started/README.md#your-first-hour-from-the-example-to-your-own-task):

1. **Run the example.** Install, get the example bundle, create a console
   workspace with `init --credential-file`, write the example data, register it
   with `add-task --from-bundle`, start the console with `serve` and open it.
   Then follow the tabs **Task → Workflow → Run → Monitor**.
2. **Bring your own task.** Package your task with your coding agent, place it in
   `siderius_workspace/tasks/<id>/`, register it with `add-task`, restart the
   console, build a workflow for it and run it.

The console needs a Linux machine with an NVIDIA GPU and bubblewrap; the
first-hour path lists the [prerequisites](docs/getting-started/README.md#before-you-start)
and defines its three terms: task, experiment setup and run.

## Try an existing task with siderius-exp

This repository provides the framework. Its companion,
[`siderius-exp`](https://github.com/yuema137/siderius-exp), provides scientific
task packages, experiment configurations, launch scripts, and tutorials.
**Start with the [tutorial guide](https://github.com/yuema137/siderius-exp/blob/main/tutorials/README.md)**
to learn the full path from editing a task to plotting score versus iteration.

The guide offers four notebook demos: **TESS** (stellar rotation), **TIDMAD**
(waveform denoising, one band), **Project8** (electron energy from time and
frequency inputs), and **LIGO** (chirp mass from two detector channels).
Each quick demo runs three research iterations. These are workflow demos,
not reproductions of the paper's artifacts or scores.

Follow the [installation and setup guide](https://github.com/yuema137/siderius-exp/blob/main/tutorials/paper/README.md)
for compatible repository revisions, data, NVIDIA GPU requirements, and API
keys. Work in your own external project directory: the copied notebook explains
and saves your task package and experiment settings, then invokes a saved
script to launch the run. Configurations, scripts, results, and plots stay in
that project; keep credentials outside both source repositories. The notebooks
show how to inspect the saved files and adjust iterations, data fractions,
splits, and time/VRAM budgets before running again. Real runs use GPU resources
and incur API charges.

<a id="paper"></a>

## Paper and architecture

Read [Beyond a Better Score: Long-Horizon Agentic ML Development and Evaluation Protocol for Physics Time Series](https://arxiv.org/abs/2610.14024).
The paper studies scientifically valid model development on TIDMAD, TESS,
Project8 and LIGO, combining composable research capabilities, scientific
checks and exploration within compute budgets.

### How the pieces fit together

[![Paper Figure 1: SIDERIUS infrastructure and typed capability contracts](docs/assets/paper/figure1.svg)](docs/assets/paper/figure1.svg)

**Figure 1. Infrastructure.** A human scientist, a fixed workflow, or an LLM
orchestrator can call the same scientific capabilities through typed contracts.
The caller chooses the calls, assembles their inputs, and owns control and
history. Each capability owns its reasoning and tools, including executable
Data Analysis.

[![Paper Figure 2: task specification and multilayer evaluation](docs/assets/paper/figure2.svg)](docs/assets/paper/figure2.svg)

**Figure 2. Evaluation.** The task package separates training objectives,
validation monitoring, scientific ranking, and supporting evidence.
Scoreability checks whether the declared metric can be computed; Health
records applicable model/output checks and follows their configured blocking
or observational policy. Offline behavioral review adds evidence for scientific
acceptance without feeding its judgments back into search.

These figures are exported from the [paper on arXiv](https://arxiv.org/abs/2610.14024).
Their source and export details are recorded in
[`docs/assets/paper/README.md`](docs/assets/paper/README.md).

<a id="quickstart"></a>

## Check your installation

To check a framework installation without credentials, GPU work or external
data, use the [synthetic Quickstart](examples/quickstart/README.md). It shows
how one small task supplies data access, a model contract and an accuracy metric.

```bash
git clone https://github.com/yuema137/SIDERIUS.git
cd SIDERIUS
uv sync --group dev --frozen
.venv/bin/python -m pytest \
  tests/unit/examples/test_quickstart_pack.py::test_composition_authority_resolves_from_this_checkout \
  tests/unit/examples/test_quickstart_pack.py::test_shipped_manifest_composes_with_the_declared_values -q
```

A real run needs a task package, external data, model/provider routing, a
workspace for results and an NVIDIA GPU with CUDA. Preview the chosen launch command before execution;
the chain's `--dry-run` prints child commands but does not prove that a task,
provider account or training attempt will succeed. The
[getting-started guide](docs/getting-started/README.md) leads to the exact setup
and first-run references.

## What you choose

| Choice | What it controls |
| --- | --- |
| Task package | Data meaning, model input/output, objective, metrics and validity checks |
| Workflow (`workflow.py`) | Which research steps run, what evidence passes between them, advice, the number of iterations and stop conditions of a research loop, tuning rounds per iteration, Trial/Formal tuning rounds and training budgets |
| Run settings | Provider/model routing (the LLM profile, `llm.json`), plus time limits, network, devices and provider key names (the preparation request) |
| Workspace | Where the run records its identity, generated models and results |

For example, changing the metric changes the task's scientific meaning.
Giving the same task more search time changes the experiment. Keep both choices
explicit so recorded results can be interpreted and compared. Use a fresh
workspace for an intentional new identity; resuming preserves the previous
run's recorded inputs.

## Find the right part

| Need | Start here |
| --- | --- |
| Learn, configure or operate SIDERIUS | [Documentation](docs/README.md) |
| Try framework contracts on synthetic data | [Examples](examples/README.md) |
| Find a research capability or execution owner | [Source map](src/README.md) |
| Choose policy or provider routing | [Configuration](configs/README.md) |
| Find launch and inspection commands | [Scripts](scripts/README.md) |
| Contribute a change | [Contribution reference](CONTRIBUTING.md), [tests](tests/README.md) |

Repository standards are owned by [CLAUDE.md](CLAUDE.md). Scientific packages,
campaigns and historical paper evidence are owned by
[siderius-exp](https://github.com/yuema137/siderius-exp), which pins its compatible
framework revision independently of this repository's latest development head.

## License

Original SIDERIUS software and documentation are available under the
[MIT License](LICENSE). Third-party portions retain their own terms and
attribution; see [NOTICE](NOTICE). External datasets and dependencies have
separate licenses. This repository's license does not replace them.
