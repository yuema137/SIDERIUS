"""Pure reusable-to-v1 candidate declaration resolution; no resource admission.

Locations are explicit caller observations, never interpreted or opened here.
The result is not a prepared run and does not certify execution readiness.
"""

from typing import Self

from pydantic import model_validator

from workflows.definition import (
    CandidatePreparationOptions,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    ManagedCandidateBinding,
    ReusableWorkflowDocument,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
)
from workflows.definition.candidate import candidate_nodes
from workflows.definition.models import DeclarationModel, Identifier, Location


class ResolvedExternalLocation(DeclarationModel):
    binding: Identifier
    location: Location


class ReusableCandidateLocations(DeclarationModel):
    """All resolved task/external destinations supplied by the caller."""

    manifest: Location
    data_root: Location
    workspace: Location
    externals: tuple[ResolvedExternalLocation, ...]

    @model_validator(mode="after")
    def unique_bindings(self) -> Self:
        if len({item.binding for item in self.externals}) != len(self.externals):
            raise ValueError("Duplicate external location binding IDs")
        return self


class ResolvedReusableCandidate(DeclarationModel):
    document: WorkflowDocument
    preparation_options: CandidatePreparationOptions


def _check_roles(document: ReusableWorkflowDocument, proposal_id: str) -> None:
    """Require generated roles and supported literal roles at their actual usage."""
    externals = {item.id: item for item in document.definition.externals}
    used: set[str] = set()
    for node in document.definition.nodes:
        request = node.request
        if isinstance(request, ExternalRequest):
            external = externals[request.binding]
            if not (
                node.id == proposal_id
                and isinstance(external, ManagedCandidateBinding)
                and external.contract == "proposal.input"
            ):
                raise ValueError("Reusable proposal requires a managed proposal binding")
            used.add(external.id)
            continue
        for argument in request.arguments:
            if not isinstance(argument.source, ExternalSource):
                if argument.name != "output":
                    raise ValueError("Reusable candidate optional/storage roles require externals")
                continue
            external = externals[argument.source.binding]
            if isinstance(external, ManagedCandidateBinding):
                if external.contract != "storage" or argument.name != "storage":
                    raise ValueError("Misrouted managed candidate binding")
            elif external.contract in {"storage", "proposal.input"}:
                raise ValueError("Literal proposal/storage bindings cannot be resolved")
            elif external.contract not in {
                "optional.constraint-context",
                "optional.task-composition-ref",
                "llm-provider",
                "optional.model-id",
            }:
                raise ValueError("Unsupported reusable literal binding role")
            used.add(external.id)
    if used != externals.keys():
        raise ValueError("Unused reusable external bindings are unsupported")
    proposals = [
        item
        for item in externals.values()
        if isinstance(item, ManagedCandidateBinding) and item.contract == "proposal.input"
    ]
    if len(proposals) != 1:
        raise ValueError("Exactly one managed proposal binding is required")


def resolve_reusable_candidate(
    document: ReusableWorkflowDocument,
    bindings: ReusableCandidateLocations,
) -> ResolvedReusableCandidate:
    """Resolve validated declarations without reading sources or constructing native inputs."""
    document = ReusableWorkflowDocument.model_validate_json(
        document.model_dump_json(warnings=False)
    )
    bindings = ReusableCandidateLocations.model_validate_json(
        bindings.model_dump_json(warnings=False)
    )
    roles = candidate_nodes(document.definition)
    _check_roles(document, roles["proposal"])
    locations = {item.binding: item.location for item in bindings.externals}
    expected = {item.id for item in document.definition.externals}
    if locations.keys() != expected:
        raise ValueError("External location mappings must match declared bindings exactly")
    storage = {
        locations[item.id]
        for item in document.definition.externals
        if isinstance(item, ManagedCandidateBinding) and item.contract == "storage"
    }
    if len(storage) != 1:
        raise ValueError("Managed storage bindings must share one generated storage location")
    effective = WorkflowDocument(
        definition=WorkflowDefinition(
            task=TaskReferences(
                manifest=bindings.manifest,
                data_root=bindings.data_root,
                workspace=bindings.workspace,
            ),
            externals=tuple(
                ExternalBinding(id=item.id, contract=item.contract, location=locations[item.id])
                for item in document.definition.externals
            ),
            nodes=document.definition.nodes,
        ),
        positions=document.positions,
    )
    return ResolvedReusableCandidate.model_validate_json(
        ResolvedReusableCandidate(
            document=effective,
            preparation_options=document.preparation_options,
        ).model_dump_json()
    )
