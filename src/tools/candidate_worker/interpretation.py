"""Captured native interpretation and its explicit directed proposal protocol."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.health_feedback import FormalValidityFeedback
from agent.schemas.hyperparam_tuning import (
    ExpertAdviceInput,
    TaskCompositionRef,
    serialize_expert_advice,
)
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import ExpertContextItem, ProposalInput
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.chain_state import ChainState
from core.durable_io import publish_bytes_write_once
from ml_models.model_descriptions import DescriptionSourcePolicy
from workflows.definition import ExternalSource, ProtocolRequest
from workflows.definition.fanout import InterpretationEdge
from workflows.llm_config import WorkflowLLMConfig
from workflows.proposal_pipeline import get_reasoning_pipeline
from workflows.research_history import (
    interpretation_history,
    prior_findings,
    recent_formal_feedback,
)
from workflows.task_composition import RunTaskComposition, build_task_composition_ref

from .artifacts import capture_record
from .inputs import check_constraints, require_storage
from .invocation import FixedInvocationContext
from .layout import graph_instance_dir, interpretation_input_path
from .loop_models import ResumeAdvice
from .models import CandidateRunReceipt, CandidateRunRequest
from .record_json import artifact_json

if TYPE_CHECKING:
    from .training_admission import TrainingAdmission


def compose_proposal_advice(
    declared: ExpertAdviceInput | None, advice: ResumeAdvice | None
) -> ExpertAdviceInput | None:
    """The proposer's ``human_advice``: the declared advice, plus operator Resume advice.

    Without operator advice the declared value is returned unchanged (same object), so
    proposal inputs of runs and segments without advice keep their bytes.
    """
    if advice is None:
        return declared
    note = f"Operator advice after body {advice.after_body}:\n{advice.text}"
    prior = "" if declared is None else serialize_expert_advice(declared)
    return f"{prior}\n\n{note}" if prior else note


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

    def apply(
        self,
        output: InterpretationOutput,
        *,
        config: WorkflowLLMConfig,
        history: ChainState | None = None,
        feedback: list[FormalValidityFeedback] | None = None,
        operator_advice: ResumeAdvice | None = None,
    ) -> ProposalInput:
        # Keep nested native models and omit unsupplied optional arguments.
        values = {name: getattr(self, name) for name in self.model_fields_set}
        if operator_advice is not None:
            values["human_advice"] = compose_proposal_advice(self.human_advice, operator_advice)
        if history is not None:
            values.update(
                expert_context=prior_findings(history) + list(self.expert_context or []),
                recent_tune_outputs=list(history.recent_tune_outputs),
                recent_formal_validity=feedback
                if feedback is not None
                else recent_formal_feedback(history, None),
            )
        result = local_full_context(
            output, reasoning_pipeline=get_reasoning_pipeline(config), **values
        )
        if history is not None:
            result.existing_model_types = list(history.all_model_types)
        return result


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
    history: ChainState | None = None,
) -> tuple[InterpretationInput, InterpretationArguments]:
    definition = request.preview.document.definition
    protocol = next(node.request for node in definition.nodes if node.id == edge.proposal)
    assert isinstance(protocol, ProtocolRequest)
    arguments = read_arguments(protocol, contents)
    value = InterpretationInput.model_validate_json(contents[f"external.{edge.input_binding}"])
    if history is not None and iteration > 1:
        value = value.model_copy(
            update={
                **interpretation_history(history, value),
                "iteration": iteration,
                "storage": StorageConfig(
                    backend="local",
                    local=LocalStorageConfig(
                        workspace=str(
                            graph_instance_dir(
                                workspace,
                                request.run_name,
                                edge.interpretation,
                                iteration=iteration,
                            )
                        ),
                        run_name=request.run_name,
                    ),
                ),
            }
        )
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
    publish_bytes_write_once(str(input_path), artifact_json(inputs, kind="internal", indent=2))
    directory.mkdir(parents=True, exist_ok=True)
    agent = ResultInterpretationAgent(**config.get("interpret"))
    context.bind(agent)
    output = InterpretationOutput.model_validate(agent.run(inputs))
    capture_record(output_path, output)
    return output, output_path
