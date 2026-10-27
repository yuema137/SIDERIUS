"""Captured native interpretation and its explicit directed proposal protocol."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.hyperparam_tuning import ExpertAdviceInput, TaskCompositionRef
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import ExpertContextItem, ProposalInput
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.durable_io import publish_bytes_write_once
from ml_models.model_descriptions import DescriptionSourcePolicy
from workflows.definition import ExternalSource, ProtocolRequest
from workflows.definition.fanout import InterpretationEdge
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition, build_task_composition_ref

from .artifacts import capture_record
from .inputs import check_constraints, require_storage
from .invocation import FixedInvocationContext
from .layout import graph_instance_dir, interpretation_input_path
from .models import CandidateRunReceipt, CandidateRunRequest

if TYPE_CHECKING:
    from .training_admission import TrainingAdmission


class InterpretationArguments(BaseModel):
    """The supported external arguments, using the native protocol's own types."""

    model_config = ConfigDict(extra="forbid")
    storage: StorageConfig
    data_dir: str
    task_composition_ref: TaskCompositionRef
    human_advice: ExpertAdviceInput | None = None
    expert_context: list[ExpertContextItem] | None = None
    constraint_context: ConstraintContext | None = None
    workflow_parameter_rules: ParameterRules | None = None

    def apply(self, output: InterpretationOutput) -> ProposalInput:
        # Keep nested native models and omit unsupplied optional arguments.
        return local_full_context(
            output, **{name: getattr(self, name) for name in self.model_fields_set}
        )


def read_arguments(
    protocol: ProtocolRequest, contents: Mapping[str, bytes]
) -> InterpretationArguments:
    values = {}
    for argument in protocol.arguments:
        if argument.name == "output":
            continue
        assert isinstance(argument.source, ExternalSource)
        values[argument.name] = json.loads(contents[f"external.{argument.source.binding}"])
    return InterpretationArguments.model_validate(values)


def prepare_interpretation(
    request: CandidateRunRequest,
    workspace: Path,
    edge: InterpretationEdge,
    contents: Mapping[str, bytes],
    composition: RunTaskComposition,
    *,
    iteration: int,
    admitted: "TrainingAdmission | None" = None,
) -> tuple[InterpretationInput, InterpretationArguments]:
    definition = request.preview.document.definition
    protocol = next(node.request for node in definition.nodes if node.id == edge.proposal)
    assert isinstance(protocol, ProtocolRequest)
    arguments = read_arguments(protocol, contents)
    value = InterpretationInput.model_validate_json(contents[f"external.{edge.input_binding}"])
    for node_id, storage in (
        (edge.interpretation, value.storage),
        (edge.proposal, arguments.storage),
    ):
        expected = StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(
                    graph_instance_dir(workspace, request.run_name, node_id, iteration=iteration)
                ),
                run_name=request.run_name,
            ),
        )
        require_storage(storage, expected)
    if value.iteration != iteration:
        raise ValueError("interpretation input iteration disagrees with invocation")
    if (value.task_description, value.task_blocks) != (
        composition.task_description,
        composition.interpretation_blocks,
    ):
        raise ValueError("interpretation input task disagrees with composed task")
    if value.description_source_policy != DescriptionSourcePolicy.COMPOSED:
        raise ValueError("interpretation requires composed description policy")
    if value.metric_spec is not None and value.metric_spec != composition.metric.spec:
        raise ValueError("interpretation metric disagrees with composed task")
    if arguments.task_composition_ref != build_task_composition_ref(composition):
        raise ValueError("interpretation protocol task identity disagrees with composed task")
    root = (Path(request.preview.project_root) / definition.task.data_root).resolve()
    if Path(arguments.data_dir).resolve() != root:
        raise ValueError("interpretation protocol data root disagrees with selected task")
    if value.constraint_context != arguments.constraint_context:
        raise ValueError("interpretation and proposal constraints disagree")
    if admitted is not None:
        from workflows.candidate_training_settings import reconcile_constraints

        reconcile_constraints(value.constraint_context, admitted.constraints)
        rules = admitted.settings.launch.workflow_parameter_rules
        if (
            "workflow_parameter_rules" in arguments.model_fields_set
            and arguments.workflow_parameter_rules != rules
        ):
            raise ValueError("interpretation workflow rules disagree with native training")
        enabled = admitted.bindings.enable_structured_health_feedback
        if (
            "enable_structured_health_feedback" in value.model_fields_set
            and value.enable_structured_health_feedback != enabled
        ):
            raise ValueError("interpretation health feedback disagrees with native training")
        value = value.model_copy(
            update={
                "constraint_context": admitted.constraints,
                "enable_structured_health_feedback": enabled,
            }
        )
        arguments = arguments.model_copy(
            update={"constraint_context": admitted.constraints, "workflow_parameter_rules": rules}
        )
    else:
        # These optional native adapter parameters are outside this bounded profile.
        # Compare disclosures to the native ProposalInput defaults, never invent locks.
        check_constraints(
            arguments.constraint_context,
            arguments.task_composition_ref,
            workflow_rules=arguments.workflow_parameter_rules,
            **{
                name: ProposalInput.model_fields[name].default
                for name in (
                    "trial_time_budget_minutes",
                    "formal_time_budget_minutes",
                    "vram_budget_gb",
                )
            },
        )
    return value, arguments


def run_interpretation(
    context: FixedInvocationContext,
    initial: CandidateRunReceipt,
    inputs: InterpretationInput,
    config: WorkflowLLMConfig,
) -> tuple[InterpretationOutput, Path]:
    from nodes.result_interpretation_agent.result_interpretation_agent import (
        ResultInterpretationAgent,
    )

    directory = graph_instance_dir(
        Path(initial.workspace), initial.run_name, context.node_id, iteration=context.iteration
    )
    if context.storage_workspace != str(directory) or inputs.iteration != context.iteration:
        raise ValueError("interpretation invocation slot disagrees")
    context.require_resolved_binding(
        initial,
        run_name=initial.run_name,
        node_id=context.node_id,
        phase="interpretation",
        storage=inputs.storage,
        implementation_directory="",
    )
    input_path = interpretation_input_path(
        Path(initial.workspace), context.node_id, iteration=context.iteration
    )
    output_path = directory / f"interpretation_{initial.run_name}.json"
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("interpretation output already exists")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(str(input_path), inputs.model_dump_json(indent=2).encode())
    directory.mkdir(parents=True, exist_ok=True)
    agent = ResultInterpretationAgent(**config.get("interpret"))
    context.bind(agent)
    output = InterpretationOutput.model_validate(agent.run(inputs))
    capture_record(output_path, output)
    return output, output_path
