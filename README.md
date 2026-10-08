# SIDERIUS

**S**cientific **I**nquiry, **D**esign, **E**xploration, and **R**easoning
**I**ntegrated **U**sing multi-agent **S**ystems

SIDERIUS is a task-generic framework for supervised scientific machine
learning. An LLM can interpret results, propose a model, write model code, and
learn from previous attempts. The framework keeps the parts that must remain
reproducible and comparable under deterministic control: data access, training,
inference, scoring, validity checks, resource limits, and provenance.

The task owns the scientific meaning. The caller owns the workflow composition
and run settings. SIDERIUS supplies the typed interfaces and execution core
that connect them.

## Paper

Read [Beyond a Better Score: Long-Horizon Agentic ML Development and Evaluation Protocol for Physics Time Series](https://zenodo.org/records/23071121).
The paper studies how LLM agents can develop scientifically valid models,
combining reusable research capabilities, multiple layers of scientific
evaluation, and exploration within compute budgets. Experiments on TIDMAD,
TESS, Project8, and LIGO evaluate both model performance and scientific validity.

## Start with your coding agent

**We recommend using SIDERIUS together with your coding agent.** It can read the
repository, help turn your research question into a task package and experiment,
and prepare the files and launch command. You decide the scientific goal, data
split, models and budgets. You can write everything by hand, but that is not our
recommended starting path.

Choose how you want to work with the agent:

| Way of working | Who leads the setup? | Where to start |
| --- | --- | --- |
| **Assistant — recommended for a first task** | Describe your problem and data. Your agent handles setup and guides you through designing the task and experiment. | Start with the one-sentence example below. |
| **Professional** | You direct the task, workflow and experiment choices, working closely with your agent to inspect the code and implement your setup. | Give it your plan and the [task contract](docs/reference/task-composition.md). |

These are ways of collaborating, not software mode switches. Either can use the
same optional [configuration review and HTML report](src/tools/setup_review/README.md).
You can also launch directly without that review. Choosing a fixed workflow or
an external orchestrator is a separate [execution choice](src/tools/orchestration_setup/README.md).

### Assistant example: start with one sentence

Clone this repository and open it in your coding agent, then say:

```text
I have MNIST images and labels in /data/mnist; help me build and evaluate a digit classifier.
```

Replace the task and path with your own. You do not need to know the configuration
format or write a task package first. The agent follows the repository's
[setup guidance](docs/agent-reference/siderius-setup-review/SKILL.md) and takes
you through the whole preparation:

1. **Set up the environment:** inspect the data layout and available hardware,
   prepare the correct Python environment and explain which API keys to set.
2. **Design the task with you:** agree on inputs, labels, training/validation/test
   splits and the score. For this example, the task maps an image to a digit.
3. **Prepare the experiment:** help choose the model routing, data amount,
   iterations and time/memory budgets, then save the files in your own project.
4. **Show how to run and inspect results:** give you the exact saved script,
   settings and output paths; optionally produce a configuration-review HTML page.

The agent does the setup work and asks when a consequential choice is missing;
it should not hand you a list of unexplained files to author. You retain control
of the scientific choices and paid execution. Training starts once the required
environment, data and execution authorization are in place. This is guidance for
your coding agent, not a separate automatic service or a guarantee of model quality.

No global skill installation is required: the agent reads the linked repository file.
The [getting-started guide](docs/getting-started/README.md) links installation
and the next setup steps. Your coding agent's own model and the models called
inside a SIDERIUS experiment are separate choices. Use the
[Luna test configuration](configs/llm/README.md) for the latter during a first
flow check; for production research, start from the paper's LLM configuration
or supply your own supported model choices.

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

## How the pieces fit together

[![Paper Figure 1: SIDERIUS infrastructure and typed capability contracts](docs/assets/paper/figure1.svg)](docs/assets/paper/figure1.svg)

**Figure 1 — Infrastructure.** A human scientist, a fixed workflow, or an LLM
orchestrator can call the same scientific capabilities through typed contracts.
The caller chooses the calls, assembles their inputs, and owns control and
history. Each capability owns its reasoning and tools, including executable
Data Analysis.

[![Paper Figure 2: task specification and multilayer evaluation](docs/assets/paper/figure2.svg)](docs/assets/paper/figure2.svg)

**Figure 2 — Evaluation.** The task package separates training objectives,
validation monitoring, scientific ranking, and supporting evidence.
Scoreability checks whether the declared metric can be computed; Health
records applicable model/output checks and follows their configured blocking
or observational policy. Offline behavioral review adds evidence for scientific
acceptance without feeding its judgments back into search.

These figures are exported from the [paper on Zenodo](https://zenodo.org/records/23071121).
Their source and export details are recorded in
[`docs/assets/paper/README.md`](docs/assets/paper/README.md).

## Quickstart

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

A real run needs a task package, external data, model/provider routing and a
workspace for results. Preview the chosen launch command before execution;
the chain's `--dry-run` prints child commands but does not prove that a task,
provider account or training attempt will succeed. The
[getting-started guide](docs/getting-started/README.md) leads to the exact setup
and first-run references.

## What you choose

| Choice | What it controls |
| --- | --- |
| Task package | Data meaning, model input/output, objective, metrics and validity checks |
| Workflow | Which research steps run and what evidence passes between them |
| Experiment settings | Provider/model routing, data scope, iterations, Trial/Formal rounds and resource budgets |
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
