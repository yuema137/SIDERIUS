"""Child-only native assembly; imported after generated-library binding."""

from pathlib import Path

from agent.schemas.interpretation import InterpretationInput
from agent.schemas.proposal import ProposalInput
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.durable_io import publish_bytes_write_once
from ml_models.model_descriptions import DescriptionSourcePolicy
from nodes.result_interpretation_agent import build_cold_start_interpretation
from tools.candidate_worker.layout import candidate_proposal_dir
from tools.workflow_preview.config import parse_config
from workflows.attempt_storage import impl_attempt_storage
from workflows.proposal_pipeline import get_reasoning_pipeline
from workflows.task_composition import (
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
)

from .declaration import candidate_document
from .models import CandidatePreparationRequest


def prepare_native(request: CandidatePreparationRequest) -> str:
    """Compose the selected task and save exact native inputs without a provider."""
    output = Path(request.output_dir)
    config_bytes = (output / "preparation/llm.snapshot").read_bytes()
    config = parse_config(config_bytes)
    composition = compose_run_task_bindings(request.task_manifest)
    with bind_run_task_composition(composition, physical_data_root=request.data_root):
        interpretation_input = InterpretationInput(
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(
                    workspace=str(output / "preparation"), run_name=request.run_name
                ),
            ),
            cold_start=True,
            model_types=None,
            summaries=[],
            model_knowledge_cache={},
            analysis_brief_requested=False,
            task_description=composition.task_description,
            task_blocks=composition.interpretation_blocks,
            metric_spec=composition.metric.spec,
            description_source_policy=DescriptionSourcePolicy.COMPOSED,
        )
        interpretation = build_cold_start_interpretation(interpretation_input)
        proposal_dir = candidate_proposal_dir(Path(request.candidate_workspace), request.run_name)
        storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(proposal_dir), run_name=request.run_name),
        )
        ref = build_task_composition_ref(composition)
        assert ref is not None
        proposal = local_full_context(
            interpretation,
            storage,
            reasoning_pipeline=get_reasoning_pipeline(config),
            human_advice=request.proposal_advice,
            data_dir=request.data_root,
            task_composition_ref=ref,
        )
        values = proposal.model_dump()
        values.update(
            task_description=composition.task_description,
            forward_contract=composition.forward_contract,
            proposal_blocks=composition.proposal_blocks,
            allowed_output_types=request.allowed_output_types,
        )
        proposal = ProposalInput.model_validate(values)
        attempt = impl_attempt_storage(str(proposal_dir), request.run_name, 1)
        records = (
            ("preparation/interpretation_input.json", interpretation_input),
            ("interpretation.json", interpretation),
            ("proposal.json", proposal),
            ("storage.json", attempt.storage),
            ("workflow.json", candidate_document(request)),
        )
        for name, record in records:
            publish_bytes_write_once(
                str(output / name), (record.model_dump_json(indent=2) + "\n").encode()
            )
        publish_bytes_write_once(str(output / "llm.json"), config_bytes)
        return ref.semantic_fingerprint
