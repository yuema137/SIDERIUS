"""Enrich native candidate requests with already resolved workflow context.

Directed protocols own field mapping and construction. Callers own resolution,
artifact paths and routing; these helpers only mutate the supplied request.
"""

from agent.schemas.implementor import ImplementorInput, ImplementorTaskBlocks
from agent.schemas.proposal import InheritedComponent
from agent.schemas.task_config import ForwardContract
from agent.schemas.validator import ValidatorInput
from core.hardware_context import HardwareContext


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
