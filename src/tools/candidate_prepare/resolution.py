"""Pure reusable-to-v1 candidate declaration resolution; no resource admission.

Locations are explicit caller observations, never interpreted or opened here.
The result is not a prepared run and does not certify execution readiness.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from workflows.definition import (
    CandidatePreparationOptions,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    ManagedCandidateBinding,
    ProtocolRequest,
    ReusableWorkflowDocument,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
)
from workflows.definition.candidate import ADAPTORS_NOT_ADMITTED, candidate_nodes
from workflows.definition.fanout import execution_families
from workflows.definition.models import DeclarationModel, Identifier, Location

from .layout import (
    graph_literature_bindings,
    graph_proposal_bindings,
    graph_storage_bindings,
    interpretation_external_bindings,
)


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
    execution_profile: (
        Literal[
            "native-proposal-fanout/v1",
            "native-proposal-families/v1",
            "native-literature-candidate/v1",
            "native-interpretation-candidate/v1",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)


def check_candidate_roles(document: ReusableWorkflowDocument, proposal_ids: set[str]) -> None:
    """Require generated roles and supported literal roles at their actual usage."""
    result_roles = {"output", "proposal", "validation"}
    if document.execution_profile is not None:
        result_roles.add("implementation")
    managed_roles = {("storage", "storage"), ("native-training.settings", "settings")}
    if document.execution_profile == "native-interpretation-candidate/v1":
        managed_roles.update(
            (contract, name)
            for name, contract in {
                "data_dir": "optional.text",
                "task_composition_ref": "optional.task-composition-ref",
                "human_advice": "optional.expert-advice",
                "expert_context": "optional.expert-context",
                "constraint_context": "optional.constraint-context",
                "workflow_parameter_rules": "optional.parameter-rules",
            }.items()
        )
    if document.execution_profile == "native-literature-candidate/v1":
        managed_roles.add(("proposal.input", "proposal_input"))
    externals = {item.id: item for item in document.definition.externals}
    used: set[str] = set()
    for node in document.definition.nodes:
        request = node.request
        if isinstance(request, ExternalRequest):
            external = externals[request.binding]
            if not (
                isinstance(external, ManagedCandidateBinding)
                and (
                    (node.id in proposal_ids and external.contract == "proposal.input")
                    or (
                        document.execution_profile == "native-literature-candidate/v1"
                        and node.capability == "literature"
                        and external.contract == "literature.input"
                    )
                    or (
                        document.execution_profile == "native-interpretation-candidate/v1"
                        and node.capability == "interpretation"
                        and external.contract == "interpretation.input"
                    )
                )
            ):
                raise ValueError("Reusable proposal requires a managed proposal binding")
            used.add(external.id)
            continue
        if not isinstance(request, ProtocolRequest):
            raise ValueError(ADAPTORS_NOT_ADMITTED)
        for argument in request.arguments:
            if not isinstance(argument.source, ExternalSource):
                if argument.name not in result_roles:
                    raise ValueError("Reusable candidate optional/storage roles require externals")
                continue
            external = externals[argument.source.binding]
            if isinstance(external, ManagedCandidateBinding):
                if (external.contract, argument.name) not in managed_roles:
                    raise ValueError("Misrouted managed candidate binding")
            elif external.contract in {"storage", "proposal.input", "native-training.settings"}:
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
    expected_proposals = (
        0
        if document.execution_profile == "native-interpretation-candidate/v1"
        else len(proposal_ids)
    )
    if len(proposals) != expected_proposals:
        raise ValueError("Exactly one managed proposal binding per proposal is required")


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
    proposals = (
        {candidate_nodes(document.definition)["proposal"]}
        if document.execution_profile is None
        else {
            family.proposal
            for family in execution_families(
                document.definition, document.execution_profile
            ).families
        }
    )
    check_candidate_roles(document, proposals)
    locations = {item.binding: item.location for item in bindings.externals}
    expected = {item.id for item in document.definition.externals}
    if locations.keys() != expected:
        raise ValueError("External location mappings must match declared bindings exactly")
    storage = {
        locations[item.id]
        for item in document.definition.externals
        if isinstance(item, ManagedCandidateBinding) and item.contract == "storage"
    }
    if document.execution_profile is not None:
        output = Path(bindings.workspace).parent / "inputs"
        graph_files = graph_storage_bindings(document)
        graph_files.update(graph_proposal_bindings(document))
        graph_files.update(graph_literature_bindings(document))
        graph_files.update(interpretation_external_bindings(document))
        for alias, filename in graph_files.items():
            if locations[alias] != str(output / filename):
                raise ValueError("Graph storage differs from generated branch location")
    elif len(storage) != 1:
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
            loop=document.definition.loop,
        ),
        positions=document.positions,
    )
    return ResolvedReusableCandidate.model_validate_json(
        ResolvedReusableCandidate(
            document=effective,
            preparation_options=document.preparation_options,
            execution_profile=document.execution_profile,
        ).model_dump_json()
    )
