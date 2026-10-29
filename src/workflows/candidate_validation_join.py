"""Opt-in two-result mapping; fixed native assembly source identity is unchanged."""

from collections.abc import Callable
from types import MappingProxyType
from typing import TYPE_CHECKING

from agent.llm_settings import DEFAULT_LLM_PROVIDER, ProviderName
from agent.schemas.validator import ValidatorInput
from workflows.candidate_requests import enrich_validation_request

if TYPE_CHECKING:
    from agent.schemas.constraint_disclosure import ConstraintContext
    from agent.schemas.implementor import ImplementorOutput
    from agent.schemas.proposal import ProposalOutput
    from agent.schemas.storage import StorageConfig


def proposed_implementation_to_validation(
    proposal: "ProposalOutput",
    implementation: "ImplementorOutput",
    storage: "StorageConfig",
    llm_provider: ProviderName = DEFAULT_LLM_PROVIDER,
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


def implementation_to_validation(
    proposal: "ProposalOutput",
    implementation: "ImplementorOutput",
    storage: "StorageConfig",
    llm_provider: ProviderName = DEFAULT_LLM_PROVIDER,
    llm_model_id: str | None = None,
    *,
    constraint_context: "ConstraintContext | None" = None,
    human_advice: str | None = None,
) -> ValidatorInput:
    """``implementation-to-validation``: the implementation echo alone (``local_all_fields``).

    ``proposal`` supplies only the validation enrichment (``inherited_components``), as
    on the fixed native path; no proposal/implementation identity join is applied.
    """
    from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields

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


#: Catalog validation protocol id -> the function that executes it. The validation unit
#: runs the protocol its declaration names, for every profile (and the fixed native
#: path, which declares ``implementation-to-validation``). A catalog validation
#: protocol without a row here cannot execute.
VALIDATION_PROTOCOLS: MappingProxyType[str, Callable[..., ValidatorInput]] = MappingProxyType(
    {
        "implementation-to-validation": implementation_to_validation,
        "proposed-implementation-to-validation": proposed_implementation_to_validation,
    }
)
