# Repository map

Use this page to find an existing capability, its source owner and its entrypoint.
The current physical source layout places eight packages under `src/`, with
unchanged Python import names. PR 03A relocated the advice guide and optional
provider diagnostic; PR 03B relocates the packages and their resources. Chain
and iteration CLI paths remain in `sdsc_submission_scripts/`.

## Start here

| Need | Entry |
| --- | --- |
| Learn without external data or credentials | [Quickstart](../examples/quickstart/README.md), then [masked regression](../examples/synthetic_masked_regression/README.md) |
| Declare a task | [Task composition reference](reference/task-composition.md), [define a task](guides/define-a-task.md) |
| Start a chain | [run_chain.sh](../sdsc_submission_scripts/run_chain.sh); [entrypoint reference](reference/entrypoints.md) |
| Inspect or resume a workspace | [inspect_run_state.py](../scripts/inspect_run_state.py); [workspace guide](guides/workspaces-and-resume.md) |
| Supply human advice | [Advice format and ownership](guides/advice.md) |
| Extend a model or loss | [Model and plugin loaders](../src/ml_models/README.md) |
| Develop the framework | [CLAUDE.md](../CLAUDE.md), then [agent reference](agent-reference/README.md) |

The launch chain is
[`run_chain.sh`](../sdsc_submission_scripts/run_chain.sh) →
[`run_one_iteration.py`](../sdsc_submission_scripts/run_one_iteration.py) →
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
├── sdsc_submission_scripts/
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
| [sdsc_submission_scripts/](../sdsc_submission_scripts/) | Existing chain/iteration launch, checkout environment binding and scheduler support |
| [tests/](../tests/) | Unit, integration and helpers; presence does not establish CI execution |
| [scripts/](../scripts/) | Active inspection/resume tools alongside dated diagnostic harnesses; [diagnostics](../scripts/diagnostics/README.md) remains opt-in |
| [docs/](./) | User/agent documentation and design history; includes the [advice guide](guides/advice.md) |
| [.github/](../.github/) | Automatic CI workflow |

The initial audit at `2091acdf` counted 19 visible tracked roots. PR 03A retired
`advice/` and `env_validation/`, leaving 17. PR 03B consolidates eight packages
under `src/`, leaving 10 visible roots plus `.github`. Ignored files left in old
locations are user state, not alternative source packages or cleanup targets.

Root files such as [`pyproject.toml`](../pyproject.toml),
[`uv.lock`](../uv.lock), [`Makefile`](../Makefile) and
[`CONTRIBUTING.md`](../CONTRIBUTING.md) own packaging, dependencies and developer
entry instructions. `.structured-coding/` holds local planning and session
records; it is ignored, untracked and absent from fresh clones. Published
documentation stays in README/docs; review evidence is recorded in the PR.
Ignored `.venv`, caches, local workspaces and old `agent_generated/` content
are not shipped capabilities. This inventory removes none of them.

## Six nodes and typed connections

Each public implementation has a neighboring `.md` contract. The
[node CLI table](agent-reference/README.md#nodes) preserves the six tested
`main()` source citations.

| Public class / implementation | Input → output | Responsibility |
| --- | --- | --- |
| [`ResultInterpretationAgent`](../src/nodes/result_interpretation_agent/result_interpretation_agent.py) | `InterpretationInput` → `InterpretationOutput` | Interpret accumulated results |
| [`MLLiteratureReviewAgent`](../src/nodes/ml_literature_review/ml_literature_review.py) | `LiteratureReviewInput` → `LiteratureReviewOutput` | Optional literature evidence |
| [`MLModelProposalAgent`](../src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.py) | `ProposalInput` → `ProposalOutput` | Propose architecture and prediction |
| [`MLModelImplementor`](../src/nodes/ml_model_implementor/ml_model_implementor.py) | `ImplementorInput` → `ImplementorOutput` | Implement model/loss plugins |
| [`MLCodeValidatorAgent`](../src/nodes/ml_code_validator_agent/ml_code_validator_agent.py) | `ValidatorInput` → `ValidatorOutput` | Check generated code |
| [`HyperparamTuningAgent`](../src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py) | `HyperparamTuningInput` → `HyperparamTuningOutput` | Plan, train, infer, score, check validity and reflect |

[`agent/schemas/protocols/`](../src/agent/schemas/protocols/__init__.py) owns six
edge adapters: tune → interpret, interpret → propose, literature → propose,
propose → implement, implement → validate, and validate → tune. The last also
consumes the proposal; literature contributes to the proposal input alongside
interpretation. [Schemas](../src/agent/schemas/README.md) define the transported
values. Each node's stored output is its log, not an inter-node channel.

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
remain external; tracked `reports/` is historical evidence. For generated
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

Inspected counterpart: `/home/yuema137/siderius-exp-current`, an explicit local
deployment path, on `recovery/persist-demo-run-records` at
`ae12ae13abb6e2c1618f0f185ba468d669868399`. This is a recovery branch, not exp
master. Its `SIDERIUS_REVISION`, `pyproject.toml` and `uv.lock` pin framework
`66d3edf2b2045eaf037fb5cc9ecb3dffee94523b`. Git confirms that pin and infra
`2091acdf` have identical tracked trees. Commit equality is a separate check.

The following paths are relative to the external
[exp tree at the inspected revision](https://github.com/Galileo-Sandbox/siderius-exp/tree/ae12ae13abb6e2c1618f0f185ba468d669868399).
They are not directories under SIDERIUS.

| Exp responsibility | Actual paths |
| --- | --- |
| Task declarations and manifests | `tasks/{tidmad,oxford_iiit_pet,davis_future_prediction,cancer_gene_identification,supernemo_signal_background,majorana_low_avse}/compositions/` and each package's declarations/plugins |
| TIDMAD / Pets / DAVIS data loading | `tasks/tidmad/runtime/tidmad_data_path.py`, `tasks/oxford_iiit_pet/runtime/pets_data_path.py`, `tasks/davis_future_prediction/runtime/davis_data_path.py` |
| Cancer data/task adapter | `tasks/cancer_gene_identification/plugins/_cancer_gene_task.py` |
| SuperNEMO data/task adapters | `tasks/supernemo_signal_background/plugins/_supernemo_data.py` and `_supernemo_task.py` |
| MAJORANA data/task adapters | `tasks/majorana_low_avse/plugins/_majorana_data.py` and `_majorana_task.py` |
| Independent baseline tools | `tasks/tidmad/tools/run_comparison.py`, `tasks/supernemo_signal_background/tools/run_baseline.py`; reference-model plugins elsewhere do not imply independent baseline campaigns |
| Experiment settings and launch | `experiments/*/launch.sh` or `experiments/*/two_iteration_qualification/launch.sh`; SuperNEMO also has `baseline_study/` |
| Campaign/deployment settings | `campaigns/`, `deployments/`; their existence grants no launch authority |
| Run records and receipts | `experiments/*/qualification_2026-09-02.md`, recovered demo notes and `receipts/` |
| Migration/dependency evidence | `provenance/validation/2026-09-09_pr422_candidate_pin.md` |
| Report generation | `reporting/metric_dashboard.py`; HTML/raw output remains in configured external storage |

TIDMAD's qualification launcher accepts `--siderius-checkout`, `--workspace`
and `--data_dir`, and checks the task's expected training/validation HDF5 names.
SuperNEMO additionally requires four process files and four event indexes; it
creates the workspace even when forwarding `--dry-run`. P0 established the
local TIDMAD data directory, not local SuperNEMO data availability.

The retained [PR #422 receipt](https://github.com/Galileo-Sandbox/siderius-exp/blob/ae12ae13abb6e2c1618f0f185ba468d669868399/provenance/validation/2026-09-09_pr422_candidate_pin.md)
records the earlier 40 migration checks, 37 pin/task checks and framework CI.
Those results are not reruns of this documentation change. The
[SuperNEMO recovery note](https://github.com/Galileo-Sandbox/siderius-exp/blob/ae12ae13abb6e2c1618f0f185ba468d669868399/experiments/supernemo_signal_background/recovered_model_demo_v3_2026-09-03.md)
states that exact executable provenance from the deleted RunPod is unavailable.
Recovered trajectories and plots must not be presented as complete provenance.

## Retained and mixed material

| Material | Actual reader/evidence and disposition |
| --- | --- |
| Trial anchor maps | [`trial_anchor_map.py`](../src/execute_tools/trial_anchor_map.py) reads an explicit caller/task-owned JSON artifact; no infra default or builder is shipped |
| Scientific scoring/Health compatibility | [`scoring_utils.py`](../src/execute_tools/scoring_utils.py) and [`Health evaluation`](../src/execute_tools/health_checks/evaluation.py) retain task-specific behavior; existing [#423](https://github.com/Galileo-Sandbox/SIDERIUS/issues/423) tracks the Health boundary |
| Default policy package resources | Existing [#424](https://github.com/Galileo-Sandbox/SIDERIUS/issues/424); exact-checkout entry checks do not qualify wheel-only execution |
| Mixed scripts/configs | `scripts/inspect_run_state.py` is active; dated harnesses and review material require caller-by-caller audit, not directory-wide deletion |
| Historical reports | Preserved externally by the owning experiment repository; not an infra runtime root |
| Former `advice/` root | Retired; the [format guide](guides/advice.md) documents caller-owned input |
| Old design records and dated CLAUDE status entries | Rationale and incident evidence; use [design index](design/README.md) for history and Git/source for capability |

Source consolidation was not performed. Packaging discovers the existing
top-level packages; child-script lookup and external imports depend on current
paths. Any future physical move needs its own caller/path audit and validation.

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
