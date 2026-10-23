"""Write matched synthetic four-stage inputs; this script never launches a run.

Usage: python examples/workflow_declarations/native_training.py --project /path/inputs
       --data /path/quickstart_data --workspace /path/fresh_workspace
Generate the Quickstart dataset first using examples/quickstart/README.md.
"""

import argparse
from pathlib import Path

from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tools.candidate_worker import CandidateRunRequest
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.constraint_disclosure import workflow_constraint_context
from workflows.definition import (
    ArgumentBinding,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    NodeInstance,
    ProtocolRequest,
    ResultSource,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
)
from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings


def write_example(project: Path, data: Path, workspace: Path) -> Path:
    """Create explicit inputs at an external project, preserving existing files."""
    project, data, workspace = (path.resolve() for path in (project, data, workspace))
    if (
        workspace == project
        or workspace.is_relative_to(project)
        or project.is_relative_to(workspace)
    ):
        raise ValueError("project inputs and workspace must be separate directories")
    if not data.is_dir():
        raise ValueError("data must be an existing Quickstart dataset directory")
    manifest = Path(__file__).resolve().parents[2] / "configs/task_composition/quickstart.yaml"
    composition = compose_run_task_bindings(str(manifest))
    settings = CandidateTrainingSettings(
        launch=WorkflowLaunchConfig(
            healthgate_mode="observe_only",
            result_authority="diagnostic",
            require_probe_runner=True,
            max_rounds=2,
            trial_max_epochs=1,
            formal_max_epochs=2,
            trial_time_budget_minutes=2.0,
            formal_time_budget_minutes=5.0,
            trial_portion=0.2,
            train_portion=0.3,
            allowed_output_types=("classifier",),
        )
    )
    launch = settings.launch
    seed = ProposalInput(
        interpretation_evidence=ProposerInterpretationEvidence(),
        cold_start=True,
        task_description=composition.task_description,
        forward_contract=composition.forward_contract,
        proposal_blocks=composition.proposal_blocks,
        task_composition_ref=build_task_composition_ref(composition),
        data_dir=str(data),
        allowed_output_types=launch.allowed_output_types,
        trial_time_budget_minutes=launch.trial_time_budget_minutes,
        formal_time_budget_minutes=launch.formal_time_budget_minutes,
        trial_portion=0.2,
        train_portion=0.3,
        constraint_context=workflow_constraint_context(launch, composition),
    )
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=str(workspace / "candidate/iteration_001/attempt_001/impl_001"),
            run_name="candidate",
        ),
    )
    externals = tuple(
        ExternalBinding(id=name, contract=contract, location=f"{name}.json")
        for name, contract in (
            ("seed", "proposal.input"),
            ("storage", "storage"),
            ("settings", "native-training.settings"),
        )
    )
    nodes = [
        NodeInstance(id="proposal", capability="proposal", request=ExternalRequest(binding="seed"))
    ]
    for name, upstream, protocol in (
        ("implementation", "proposal", "proposal-to-implementation"),
        ("validation", "implementation", "implementation-to-validation"),
    ):
        nodes.append(
            NodeInstance(
                id=name,
                capability=name,
                request=ProtocolRequest(
                    protocol=protocol,
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node=upstream)),
                        ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ),
                ),
            )
        )
    nodes.append(
        NodeInstance(
            id="tuning",
            capability="tuning",
            request=ProtocolRequest(
                protocol="validated-candidate-to-tuning",
                arguments=(
                    ArgumentBinding(name="proposal", source=ResultSource(node="proposal")),
                    ArgumentBinding(name="validation", source=ResultSource(node="validation")),
                    ArgumentBinding(name="settings", source=ExternalSource(binding="settings")),
                ),
            ),
        )
    )
    document = WorkflowDocument(
        definition=WorkflowDefinition(
            task=TaskReferences(
                manifest=str(manifest), data_root=str(data), workspace=str(workspace)
            ),
            externals=externals,
            nodes=tuple(nodes),
        )
    )
    config = WorkflowLLMConfig(tune=TunerLLMConfig(planner_strategy="native-timing-v1"))
    project.mkdir(parents=True, exist_ok=True)
    payloads = {
        "seed": seed.model_dump_json(indent=2, exclude={"storage"}),
        "storage": storage.model_dump_json(indent=2),
        "settings": settings.model_dump_json(indent=2),
        "workflow": document.model_dump_json(indent=2),
        "llm": config.model_dump_json(indent=2),
    }
    for name, payload in payloads.items():
        with (project / f"{name}.json").open("x") as stream:
            stream.write(payload + "\n")
    preview = WorkflowPreviewRequest(
        document=document, project_root=str(project), llm_config_file="llm.json"
    )
    observed = preview_workflow(preview)
    request = CandidateRunRequest(
        preview=preview,
        declaration_digest=document.definition.declaration_digest(),
        files=observed.files,
        selected_constructor_routes=observed.selected_constructor_routes,
        storage_policy="managed_fresh",
        run_name="candidate",
        timeout_seconds=600.0,
        network=True,
        devices=(),
        read_only=(str(project), str(data), str(manifest.parents[2])),
        environment_names=("OPENAI_API_KEY",),
    )
    path = project / "candidate_request.json"
    with path.open("x") as stream:
        stream.write(request.model_dump_json(indent=2) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("project", "data", "workspace"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    args = parser.parse_args()
    print(write_example(args.project, args.data, args.workspace))
