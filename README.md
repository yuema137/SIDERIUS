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

## How the pieces fit together

![Task package, evaluation roles, and automatic checks](docs/assets/paper/figure1.png)

The first diagram shows the boundary that matters most: a task package declares
the science, while the framework keeps the evaluation roles separate. A
training loss is not automatically the ranking metric; validation history is
evidence about learning; Health and scoreability decide whether an output is
eligible to be considered.

![The SIDERIUS research loop](docs/assets/paper/figure2.png)

The second diagram shows one research loop. Data Analysis and literature review
are optional inputs. The caller assembles the requested capabilities and their
typed handoffs; the loop then interprets evidence, proposes a plan, implements
model code, validates it, trains and tunes it, and records the result for the
next iteration.

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
| Data path | How inputs are read, which partitions/files are available, and where task deliverables are written |
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
6. **Run a dry-run.** It resolves the manifest and prints the child commands
   without calling providers, training, or writing scientific results.
7. **Launch the real run.** Load only the required provider keys from a
   mode-600 external file or managed secret in the same process that launches
   the run.
8. **Inspect evidence.** Review per-node records, validation reports, scores,
   Health results, provenance, and the effective configuration. Use the
   dashboard or the run-state inspector when useful.
9. **Decide whether to continue.** Resume only after checking the recorded
   invariants. For an intentional task or configuration change, compose a new
   run instead of editing an old workspace.

The short offline path is:

```bash
git clone git@github.com:Galileo-Sandbox/SIDERIUS.git
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

## The important controls

The exact available flags depend on the caller, but these controls are common
to a real composed run:

| Control | Why it matters |
| --- | --- |
| `--task_composition` | Selects the task contract; it is required for composed runs |
| `--data_dir` and optional `--data_scope` | Select the caller-owned data location and bounded subset |
| `--llm_config` | Chooses provider/model routing for each enabled LLM capability |
| `--healthgate_mode` | Chooses blocking or observational Health behavior; formal runs must state it |
| `--result_authority` | Declares whether the run is diagnostic or scientific; formal runs must state it |
| `--num_iterations` | Number of research iterations in the caller's schedule |
| `--max_rounds` | Number of tuning rounds inside an iteration |
| Trial/Formal time and VRAM budgets | Bound candidate execution and are passed into planning and runtime checks |
| `--dry-run` | Resolves and previews the launch without effectful work |
| Resume / fresh workspace | Resume preserves identity and evidence; a fresh workspace starts a new experiment |

The framework also enforces typed Pydantic boundaries, content-pinned task code,
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
[`siderius-exp`](https://github.com/Galileo-Sandbox/siderius-exp) repository.
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
