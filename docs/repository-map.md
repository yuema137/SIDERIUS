# Repository map

Use this page to find an existing capability, its source owner and its entrypoint.
The current physical source layout places eight packages under `src/`, with
unchanged Python import names. Chain and iteration CLI paths are under
`scripts/launch/` and `src/workflows/`. This map describes the landed framework;
consumer installations follow their own recorded dependency pin.

## Start here

| Need | Entry |
| --- | --- |
| Learn without external data or credentials | [Quickstart](../examples/quickstart/README.md), then [masked regression](../examples/synthetic_masked_regression/README.md) |
| Declare a task | [Task composition reference](reference/task-composition.md), [define a task](guides/define-a-task.md) |
| Start a chain | [run_chain.sh](../scripts/launch/run_chain.sh); [entrypoint reference](reference/entrypoints.md) |
| Inspect or resume a workspace | [inspect_run_state.py](../scripts/launch/inspect_run_state.py); [workspace guide](guides/workspaces-and-resume.md) |
| Supply human advice | [Advice format and ownership](guides/advice.md) |
| Extend a model or loss | [Model and plugin loaders](../src/ml_models/README.md) |
| Develop the framework | [CLAUDE.md](../CLAUDE.md), then [agent reference](agent-reference/index.md) |

The launch chain is
[`run_chain.sh`](../scripts/launch/run_chain.sh) →
[`run_one_iteration.py`](../src/workflows/run_one_iteration.py) →
[`run_workflow`](../src/workflows/model_exploration.py).
The workflow selects node order; each node receives typed input and returns
typed output. Standalone node CLIs exist, but callers must supply their declared
context; a CLI does not reconstruct missing workflow state automatically.

## Navigation tree and actual roots

```text
SIDERIUS/
├── src/
│   ├── agent/ + nodes/ + workflows/
│   ├── core/ + execute_tools/ + ml_models/
│   └── dashboard/ + tools/
├── examples/
├── configs/ (health/, llm/, runtime/, task_composition/)
├── tests/ + scripts/
├── docs/
└── .github/
```

| Actual root | Responsibility and status |
| --- | --- |
| [src/](../src/README.md) | Eight installed framework packages; the source guide identifies each owner |
| [examples/](../examples/) | Two synthetic specifications; no shipped real scientific task |
| [configs/](../configs/) | Framework policy, runtime profiles and synthetic manifests; also dated review material |
| [configs/llm/](../configs/llm/) | Provider/model routing, separate from scientific treatment |
| [scripts/launch/](../scripts/launch/) | Chain launch, checkout environment binding and auto-resume support |
| [tests/](../tests/) | Unit, integration and helpers; presence does not establish CI execution |
| [scripts/](../scripts/) | Chain launch, inspection/resume and runtime utilities; [diagnostics](../scripts/diagnostics/README.md) remains opt-in |
| [docs/](./) | User/agent documentation and design history; includes the [advice guide](guides/advice.md) |
| [.github/](../.github/) | Automatic CI workflow |

The source consolidation is landed. Ignored files left in old locations are
user state, not alternative source packages or cleanup targets.

Root files such as [`pyproject.toml`](../pyproject.toml),
[`uv.lock`](../uv.lock), [`Makefile`](../Makefile) and
[`CONTRIBUTING.md`](../CONTRIBUTING.md) own packaging, dependencies and developer
entry instructions. `.structured-coding/` holds local planning and session
records; it is ignored, untracked and absent from fresh clones. Published
documentation stays in README/docs; review evidence is recorded in the PR.
Ignored `.venv`, caches, local workspaces and old `agent_generated/` content
are not shipped capabilities. This inventory removes none of them.

## Seven nodes and typed connections

Each public implementation has a neighboring `.md` contract. The
[node CLI table](agent-reference/index.md#nodes) preserves the six tested
`main()` source citations; Data Analysis is intentionally API-only in v0.1.

| Public class / implementation | Input → output | Responsibility |
| --- | --- | --- |
| [`ResultInterpretationAgent`](../src/nodes/result_interpretation_agent/result_interpretation_agent.py) | `InterpretationInput` → `InterpretationOutput` | Interpret accumulated results |
| [`DataAnalysisAgent`](../src/nodes/data_analysis_agent/data_analysis_agent.py) | `DataAnalysisInput` → `DataAnalysisReport` | Execute authorized scientific analysis skills and synthesize structured evidence |
| [`MLLiteratureReviewAgent`](../src/nodes/ml_literature_review/ml_literature_review.py) | `LiteratureReviewInput` → `LiteratureReviewOutput` | Optional literature evidence |
| [`MLModelProposalAgent`](../src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.py) | `ProposalInput` → `ProposalOutput` | Propose architecture and prediction |
| [`MLModelImplementor`](../src/nodes/ml_model_implementor/ml_model_implementor.py) | `ImplementorInput` → `ImplementorOutput` | Implement model/loss plugins |
| [`MLCodeValidatorAgent`](../src/nodes/ml_code_validator_agent/ml_code_validator_agent.py) | `ValidatorInput` → `ValidatorOutput` | Check generated code |
| [`HyperparamTuningAgent`](../src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py) | `HyperparamTuningInput` → `HyperparamTuningOutput` | Plan, train, infer, score, check validity and reflect |

The [protocol directory](../src/agent/schemas/protocols/README.md) owns the
current edge adapters, including both configured scientific-evidence orders.
[Schemas](../src/agent/schemas/README.md) define transported values. Each node's
stored output is its log, not an inter-node channel. Follow the protocol owner
rather than copying an edge roster into workflow code.

## Deterministic owners

| Capability | Source to follow |
| --- | --- |
| Manifest resolution and run binding | [`compose_run_task_bindings`](../src/workflows/task_composition.py) |
| Task data, scopes, storage and inference batching interfaces | [`task_data_path.py`](../src/execute_tools/task_data_path.py); loaders supplied by task packages |
| Metric declaration and scoreability | [`evaluation_metric.py`](../src/execute_tools/evaluation_metric.py) |
| Primary-metric ordering | [`metric_order.py`](../src/execute_tools/metric_order.py), the direction interpreter |
| Process isolation and child paths | [`sandbox_executor.py`](../src/core/sandbox_executor.py), including `child_script_path` |
| Training / inference / composed scoring children | [`train_engine_sandbox.py`](../src/execute_tools/train_engine_sandbox.py), [`inference_single.py`](../src/execute_tools/inference_single.py), [`denoising_score_single.py`](../src/execute_tools/denoising_score_single.py) |
| Resource admission, probes, measurement, records and watchdog | [`core/runtime_control/`](../src/core/runtime_control) |
| Trained-model certification, historical reconstruction and bounded prediction | Training-side certification in [`trained_model_artifact.py`](../src/execute_tools/trained_model_artifact.py), descriptive contracts in [`trained_model.py`](../src/agent/schemas/data_analysis/trained_model.py), and caller-injected execution in [`historical_model_inference.py`](../src/execute_tools/historical_model_inference.py) |
| Round validity and Health | Tuner [`execution.py`](../src/nodes/ml_hyperparameter_tune_agent/execution.py) calls the [`round_health.py`](../src/nodes/ml_hyperparameter_tune_agent/round_health.py) boundary; checks live in [`health_checks/`](../src/execute_tools/health_checks/README.md) |
| Carried state, comparability and recovery | [`chain_state.py`](../src/core/chain_state.py), [`run_invariants.py`](../src/core/run_invariants.py), [`iteration_manifest.py`](../src/core/iteration_manifest.py), [`resume.py`](../src/core/resume.py) |
| Workspace validation | `core/resume.py::validate_workspace_layout`; no `core/workspace_layout.py` exists |
| Generated model/loss library location | [`generated_library.py`](../src/core/generated_library.py); bound/unbound behavior in the [model README](../src/ml_models/README.md) |

`run_inference_scoring_health` is reached by the current tuner. The historical
claim that composed runs never reach Health is superseded; source reachability
does not itself prove that a particular scientific run executed or passed checks.

## Environment, data and workspace

Run `uv sync --group dev --frozen` in each exact checkout, then use that
checkout's `.venv/bin/python`. The full binding rule is in
[CLAUDE](../CLAUDE.md#environment). Keep infra and exp environments separate.
The P0 pair uses infra's editable source and exp's pinned installed framework;
it does not borrow one environment for the other.

Pass the task manifest through `--task_composition`, physical input data through
`--data_dir`, and output storage through `--workspace`. Real tasks select these
in exp launchers. Data, generated models, workspaces, secrets and report outputs
remain external. Historical scientific reports are preserved in the experiment
repository; there is no tracked framework `reports/` root. For generated
synthetic data, follow the selected example's materialization instructions.
For scientific data, use the task package's declared files and input contract.

An existing workspace invokes recovery rules; use a distinct fresh workspace
for a new run identity. Supported entrypoints bind generated-library discovery
and writes to `{workspace}/generated_library`. Direct low-level composition
callers must bind explicitly before importing consumers to avoid reading ambient
generated models. See [workspace rules](guides/workspaces-and-resume.md) and
[library resolution](../src/ml_models/README.md#inputs).

The [root dry-run example](../README.md#quickstart) prints intended child
commands without running training. A launcher can still perform preflight
reads, and an external wrapper can create directories before forwarding
`--dry-run`; inspect that wrapper's contract.

## External consumer and evidence

The companion [siderius-exp](https://github.com/yuema137/siderius-exp) repository
owns real scientific task packages, experiments, campaigns, deployments and
result evidence. Start with its [task index](https://github.com/yuema137/siderius-exp/blob/main/tasks/README.md)
and [experiment index](https://github.com/yuema137/siderius-exp/blob/main/experiments/README.md).
The framework does not maintain a second scientific task roster.

Consumer installation is pinned by its `SIDERIUS_REVISION`, `pyproject.toml`
and `uv.lock`. The inspected private consumer default at `39100f7` pins
framework `e800fc1f08b0e067fc21076a200f3f70d04b38b8`; this is distinct from the
framework documentation baseline `69d20786`. Newer landed framework behavior
is not automatically available in that consumer installation. Historical units
may have still earlier source pairs.

Use the consumer's tutorials for simplified workflow demonstrations and its
[paper artifact reference](https://github.com/yuema137/siderius-exp/blob/main/experiments/paper-artifacts.md)
for frozen configurations, archived evidence and reproduction limits. Do not
infer complete paper reproducibility from a notebook or a successful prompt
comparison. These public entry URLs name the publication destinations; updating
documentation does not itself synchronize the private repositories.

Earlier separation receipts remain at their original evidence locations:
[PR #422 validation](https://github.com/Galileo-Sandbox/siderius-exp/blob/ae12ae13abb6e2c1618f0f185ba468d669868399/provenance/validation/2026-09-09_pr422_candidate_pin.md)
and [SuperNEMO recovery](https://github.com/Galileo-Sandbox/siderius-exp/blob/ae12ae13abb6e2c1618f0f185ba468d669868399/experiments/supernemo_signal_background/recovered_model_demo_v3_2026-09-03.md).
They describe those exact old revisions. The latter lacks complete executable
provenance from the deleted RunPod; recovered trajectories are not a substitute.

## Retained and mixed material

| Material | Actual reader/evidence and disposition |
| --- | --- |
| Trial anchor maps | [`trial_anchor_map.py`](../src/execute_tools/trial_anchor_map.py) reads an explicit caller/task-owned JSON artifact; no infra default or builder is shipped |
| Scientific compatibility vocabulary | Legacy record names remain readable, but active task scoring requires composition. Health eligibility uses declared roles and pinned policy; see the [Health contract](agent-reference/mechanisms/health-gates.md). |
| Default policy resources | The generic policy ships under `execute_tools/health_checks/resources/`; source and wheel callers use `default_health_policy_path()`. See [policy configuration](../configs/health/README.md). |
| Mixed scripts/configs | `scripts/launch/inspect_run_state.py` is active; dated harnesses and review material require caller-by-caller audit, not directory-wide deletion |
| Historical reports | Preserved externally by the owning experiment repository; not an infra runtime root |
| Former `advice/` root | Retired; the [format guide](guides/advice.md) documents caller-owned input |
| Old design records and dated CLAUDE status entries | Rationale and incident evidence; use [design index](design/README.md) for history and Git/source for capability |

The source consolidation is complete: eight framework packages live under
`src/`, while chain launchers and caller inputs remain at their actual root
locations above. Packaging and child-script lookup use those current paths;
any future physical move needs its own caller/path audit and validation.

## Minimal entry checks

The [Step 01 review record](https://github.com/Galileo-Sandbox/SIDERIUS/pull/426)
records dated validation outcomes: docs/rule guards, library-resolution tests,
six workspace-isolated external manifest compositions and one TIDMAD external
launcher dry-run. Its candidate and CI identifiers distinguish fresh results
from the planning baseline. Detailed working plans are maintained locally and
are not shipped with the repository. For supported entry commands, follow the
[Quickstart](../README.md#quickstart) and the selected external task's launcher.

These checks establish source/environment identity, manifest resolution and
command construction. They do not establish HDF5 content validity, successful
training/inference/scoring/Health, iteration-2 feedback, wheel-only deployment
or a new campaign qualification. Gate 1 and Gate 2 are not required for this
documentation-only change; real LLM/GPU/training were not part of these checks.
