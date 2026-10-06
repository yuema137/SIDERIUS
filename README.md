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

## Try a scientific task with siderius-exp

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

![Paper Figure 1: SIDERIUS infrastructure and typed capability contracts](docs/assets/paper/figure1.png)

**Figure 1 — Infrastructure.** A human scientist, a fixed workflow, or an LLM
orchestrator can call the same scientific capabilities through typed contracts.
The caller chooses the calls, assembles their inputs, and owns control and
history. Each capability owns its reasoning and tools, including executable
Data Analysis.

![Paper Figure 2: task specification and multilayer evaluation](docs/assets/paper/figure2.png)

**Figure 2 — Evaluation.** The task package separates training objectives,
validation monitoring, scientific ranking, and supporting evidence.
Scoreability checks whether the declared metric can be computed; Health
records applicable model/output checks and follows their configured blocking
or observational policy. Offline behavioral review adds evidence for scientific
acceptance without feeding its judgments back into search.

These figures are reproduced from the current SIDERIUS paper build. Their
source and checksums are recorded in
[`docs/assets/paper/README.md`](docs/assets/paper/README.md).

## What a task package contains

A task package is the scientific contract supplied to SIDERIUS. It is normally
one composition YAML plus the files it references. The manifest is resolved
relative to its own directory, unknown keys are rejected, and all declarations
are bound to the run identity.

| Part of the package | What it answers |
| --- | --- |
| Data contract | How inputs are read, which partitions/files are available, and where task deliverables are written. The actual data directory is supplied by the caller and normally stays outside this repository. |
| Dataset profile | Dataset topology, segment or sample anchors, scope rules, and any health peek set |
| Task configuration | What the task means, the model input/output contract, and the task description shown to agents |
| Primary metric | The metric declaration, implementation, direction, and scoreability rules used for scientific ordering |
| Secondary metrics | Optional observational metrics recorded for diagnosis; they never silently replace the primary metric |
| Objective or loss | The quantity used to update model parameters, either framework-provided or task-owned |
| Health checks | Deterministic validity checks, thresholds, and whether failures block a result or are observational |
| Deliverable rule | The output names and structure that inference and scoring expect, when the task does not name them itself |
| Agent guidance | Optional task-specific blocks for interpretation, proposal, implementation, and the literature channel |
| Model and loss plugins | Optional task-local implementations, with explicit symbols and content identity |
| Observables and parameter rules | Optional values recorded during/after training and deterministic constraints on configured parameters |
| Code package | An explicit, hashed set of task-local Python helpers when several plugin files share imports |

The package may also declare dynamic observables (measured during training),
static observables (read from a trained model), and a task-owned objective.
These are declarations, not suggestions: the execution core validates them
before using them. A task that has no Health family must say so explicitly with
`task_health: {none: true}`; omitting the section is not the same thing.

See the complete [task composition reference](docs/reference/task-composition.md)
for the manifest schema and the [task definition guide](docs/guides/define-a-task.md)
for a worked example.

## A person's step-by-step path

1. **Prepare a checkout.** Clone the framework, run `uv sync --group dev --frozen`,
   and use that checkout's `.venv/bin/python`.
2. **Prepare the task package.** Write the composition manifest, referenced
   declarations and plugins. Keep data and credentials outside the repository.
3. **Choose a caller.** Use the reference fixed workflow, or write a caller-owned
   workflow/orchestrator that composes the same typed capabilities.
4. **Choose the run identity and workspace.** Use a fresh workspace for a new
   experiment. A resume must keep the same workspace and pinned inputs.
5. **Set the run policy.** Select the enabled capabilities, LLM routing, data
   scope, Health policy, result authority, iteration/round counts, and resource
   budgets. Review these before sending any provider request.
6. **Preview the command.** The reference chain's `--dry-run` checks launcher
   inputs and prints child commands without running those children. It does
   not prove that task composition, provider access or training will succeed;
   qualify the selected task separately before a formal experiment.
7. **Launch the real run.** Load only the required provider keys from a
   mode-600 external file or managed secret in the same process that launches
   the run.
8. **Inspect evidence.** Review per-node records, validation reports, scores,
   Health results, provenance, and the effective configuration. Use the
   dashboard or the run-state inspector when useful.
9. **Decide whether to continue.** Resume only after checking the recorded
   invariants. For an intentional task or configuration change, compose a new
   run instead of editing an old workspace.

For the reference chain, supply `--mode`, `--workspace`, `--run_name`,
`--task_composition` and the external `--data_dir`. Set
`--healthgate_mode` and `--result_authority` explicitly so the intended policy
is visible. The shell wrapper otherwise supplies `blocking` and `scientific`;
the direct Python iteration entrypoint requires both declarations.
LLM routing, scope, iteration counts, rounds and budgets may have caller
defaults. Inspect the previewed command and the resulting run records;
experiment-specific launch receipts are owned by the caller.

The short offline path is:

```bash
git clone https://github.com/yuema137/SIDERIUS.git
cd SIDERIUS
uv sync --group dev --frozen
.venv/bin/python -m pytest \
  tests/unit/examples/test_quickstart_pack.py::test_composition_authority_resolves_from_this_checkout \
  tests/unit/examples/test_quickstart_pack.py::test_shipped_manifest_composes_with_the_declared_values -q
```

For a dry-run of a composed chain:

```bash
bash scripts/launch/run_chain.sh \
  --mode lilab \
  --workspace /path/to/new-run \
  --run_name first_run_v1 \
  --task_composition /path/to/task/composition.yaml \
  --data_dir /path/to/task/data \
  --llm_config /path/to/llm-config.json \
  --healthgate_mode blocking \
  --result_authority diagnostic \
  --num_iterations 1 \
  --max_rounds 1 \
  --dry-run
```

This example is a preview only. A formal run should keep the explicit
`--healthgate_mode` and `--result_authority` flags shown above rather than
relying on caller defaults.

## The important controls

The exact available flags depend on the caller, but these controls are common
to a real composed run:

| Control | Why it matters |
| --- | --- |
| `--task_composition` | Selects the task contract; it is required for composed runs |
| `--data_dir` and optional `--data_scope` | Select external data and a bounded subset. Scope support is task-dependent; effective HealthGate files, including any `--health_gate_files` override, must remain inside that subset. |
| `--llm_config` | Chooses provider/model routing and the planner strategy; see [strategy selection](docs/reference/planner-strategies.md) |
| `--healthgate_mode` | `blocking` enforces validity verdicts; `observe_only` records them without enforcing them |
| `--result_authority` | `diagnostic` or `scientific`; `observe_only` cannot be combined with `scientific` |
| `--num_iterations` | Number of research iterations in the caller's schedule |
| `--max_rounds` | Number of tuning rounds inside an iteration |
| Trial/Formal time and VRAM budgets | Bound candidate execution and are passed into planning and runtime checks |
| `--dry-run` | Previews child commands; does not execute or qualify the task |
| Resume / fresh workspace | Resume preserves identity and evidence; a fresh workspace starts a new experiment |

The framework also enforces typed Pydantic boundaries, a recorded content
identity for task code (verified when the composition is resolved),
deterministic metric ordering, scoreability before scoring, Health recording,
resource-aware execution, and provenance for the files and revisions used by a
run. LLM output is never sent directly to training or inference: it must first
pass the relevant schema.

## Ownership at a glance

| Owner | Responsibility |
| --- | --- |
| Task package | Scientific data, I/O, deliverables, metrics, objective, Health, and task guidance |
| Caller-owned workflow | Capability order, enabled nodes, advice, handoffs, workspace, and budgets |
| SIDERIUS framework | Schemas, adapters, execution, score ordering, validity enforcement, resource controls, and provenance |
| External storage | Datasets, generated plugins, checkpoints, reports, and run records |

Real scientific packages and campaigns—including TIDMAD, Oxford-IIIT Pet, and
DAVIS—belong in the external
[`siderius-exp`](https://github.com/yuema137/siderius-exp) repository.
The framework repository intentionally does not select a scientific task by
default.

## Extend and navigate

- [Define a task](docs/guides/define-a-task.md) through composition and plugin contracts.
- [Assemble a typed custom workflow](docs/guides/custom-workflow.md).
- [Supply human advice](docs/guides/advice.md) through supported caller input.
- Start with the [documentation map](docs/README.md) or [glossary](docs/concepts/glossary.md).
- Read the [first-run guide](docs/getting-started/first-run.md) before a real launch.

| Directory | Start here |
| --- | --- |
| [`src/`](src/README.md) | Package and checkout/workspace boundaries |
| [`src/nodes/`](src/nodes/README.md), [`src/workflows/`](src/workflows/README.md) | Capabilities and reference sequencing |
| [`src/core/`](src/core/README.md), [`src/execute_tools/`](src/execute_tools/README.md) | Execution, state, recovery, scoring, and Health |
| [`configs/`](configs/README.md) | Framework policy, routing, and synthetic manifests |
| [`scripts/`](scripts/README.md) | Launch, Slurm, runtime, and diagnostics entrypoints |
| [`examples/`](examples/README.md) | Synthetic task packages |

## Testing and contribution

Start with focused tests for the authority you changed, using this checkout's
`.venv/bin/python -m pytest`. Test ownership and bounded Gate requirements are
defined in [`CLAUDE.md`](CLAUDE.md) and the [Gate standard](docs/gates/gate_testing_standard.md).
The optional `make check` contributor target runs local lint, format, type, and
unit checks; it is not a substitute for the affected-test selection and exact
head PR CI described in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Availability and license

SIDERIUS is currently shared in a closed beta with invited collaborators. It is
not licensed for redistribution or reuse outside that collaboration; all rights
are reserved until a public license is chosen.
