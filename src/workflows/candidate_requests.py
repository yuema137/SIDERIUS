"""Enrich native candidate requests with already resolved workflow context.

Directed protocols own field mapping and construction. Callers own resolution,
artifact paths and routing; these helpers only mutate the supplied request.
"""

from typing import TYPE_CHECKING, Literal

from agent.llm_settings import DEFAULT_LLM_PROVIDER
from agent.schemas.implementor import ImplementorInput, ImplementorTaskBlocks
from agent.schemas.proposal import InheritedComponent
from agent.schemas.task_config import ForwardContract
from agent.schemas.validator import ValidatorInput
from core.hardware_context import HardwareContext

if TYPE_CHECKING:
    from agent.schemas.constraint_disclosure import ConstraintContext
    from agent.schemas.implementor import ImplementorOutput
    from agent.schemas.proposal import ProposalOutput
    from agent.schemas.storage import StorageConfig


def enrich_implementation_request(
    request: ImplementorInput,
    *,
    task_description: str,
    forward_contract: ForwardContract,
    implementor_blocks: ImplementorTaskBlocks | None,
    hardware_context: HardwareContext | None,
    vram_budget_gb: float | None,
    human_advice: str | None,
    reference_code: dict[str, str],
    previous_validation_failure: str | None,
) -> None:
    """Attach task and attempt context without reconstructing the native input."""
    request.task_description = task_description
    request.forward_contract = forward_contract
    request.implementor_blocks = implementor_blocks
    request.hardware_context = hardware_context
    request.vram_budget_gb = vram_budget_gb
    if human_advice is not None:
        request.human_advice = human_advice
    if reference_code:
        request.reference_code = reference_code
    if previous_validation_failure is not None:
        request.previous_validation_failure = previous_validation_failure


def enrich_validation_request(
    request: ValidatorInput,
    *,
    human_advice: str | None,
    inherited_components: list[InheritedComponent],
) -> None:
    """Attach explicit advice and nonempty lineage, preserving protocol fields."""
    if human_advice is not None:
        request.human_advice = human_advice
    if inherited_components:
        request.inherited_components = inherited_components


def proposed_implementation_to_validation(
    proposal: "ProposalOutput",
    implementation: "ImplementorOutput",
    storage: "StorageConfig",
    llm_provider: "Literal['gemini', 'openai', 'deepseek']" = DEFAULT_LLM_PROVIDER,
    llm_model_id: str | None = None,
    *,
    constraint_context: "ConstraintContext | None" = None,
    human_advice: str | None = None,
) -> ValidatorInput:
    """Join explicit proposal lineage with the immediate implementation echo."""
    from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields

    if (
        not implementation.candidate_id
        or implementation.candidate_id != proposal.candidate_id
        or implementation.model_type != proposal.model_name
    ):
        raise ValueError("proposal/implementation candidate identity disagrees")
    request = local_all_fields(
        implementation,
        storage,
        llm_provider,
        llm_model_id,
        constraint_context=constraint_context,
    )
    enrich_validation_request(
        request,
        human_advice=human_advice,
        inherited_components=proposal.inherited_components,
    )
    return request
