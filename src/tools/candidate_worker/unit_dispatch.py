"""Select one ready node's typed invocation from the body's in-memory results.

This is the parent half of the dispatch `graph.execute_fanout` performed
in-process before B3-3: input selection, storage selection and predecessor
results. The phase call itself runs in `unit_child`.
"""

from collections.abc import Mapping
from dataclasses import replace

from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationInput
from agent.schemas.literature_review import LiteratureReviewInput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from execute_tools.data_paths import active_physical_data_root
from workflows.adaptors import AdaptorOutcome
from workflows.definition.fanout import ProposalFamilies
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition

from .inputs import NativeInputs
from .literature_edges import proposal_input
from .models import CandidateRunReceipt, CandidateRunRequest
from .training_admission import TrainingAdmission
from .unit_models import (
    AdmittedTraining,
    ImplementationUnit,
    InterpretationUnit,
    LiteratureUnit,
    NodeInvocation,
    NodeOutput,
    PhaseUnit,
    ProposalUnit,
    TuningUnit,
    ValidationUnit,
    admission_from,
)

SelectedInput = NativeInputs | LiteratureReviewInput | InterpretationInput


def phase_unit(
    node_id: str,
    capability: str,
    selected: SelectedInput,
    shape: ProposalFamilies,
    results: dict[str, NodeOutput],
    outcomes: Mapping[str, AdaptorOutcome],
    admission: AdmittedTraining | None,
    tuning_branch: tuple[str, str] | None,
    incumbent: float | None,
) -> PhaseUnit:
    if capability == "tuning":
        # The adaptor-selected (implementation, validation) pair, chosen in the worker.
        assert admission is not None and tuning_branch is not None
        proposal = results[shape.families[0].proposal]
        implementation, validation = (results[key] for key in tuning_branch)
        assert isinstance(proposal, ProposalOutput)
        assert isinstance(implementation, ImplementorOutput)
        assert isinstance(validation, ValidatorOutput)
        return TuningUnit(
            phase="tuning",
            proposal=proposal,
            implementation=implementation,
            validation=validation,
            admission=admission,
            chain_formal_incumbent_reference=incumbent,
        )
    if capability == "interpretation":
        assert isinstance(selected, InterpretationInput)
        return InterpretationUnit(phase="interpretation", inputs=selected)
    if capability == "literature":
        assert isinstance(selected, LiteratureReviewInput)
        return LiteratureUnit(phase="literature", inputs=selected)
    assert isinstance(selected, NativeInputs)
    if capability == "proposal":
        if shape.literature_reviews:
            # The declared literature edge, applied by its one owner (also the verifier's).
            evidence = proposal_input(shape, node_id, selected.proposal, results, outcomes)
            selected = replace(selected, proposal=evidence)
        return ProposalUnit(phase="proposal", inputs=selected)
    proposal = results[shape.proposal_for(node_id)]
    assert isinstance(proposal, ProposalOutput)
    if capability == "implementation":
        return ImplementationUnit(phase="implementation", inputs=selected, proposal=proposal)
    parent = next(impl for impl, valid in shape.branches if valid == node_id)
    implemented = results[parent]
    assert isinstance(implemented, ImplementorOutput)
    return ValidationUnit(
        phase="validation", inputs=selected, proposal=proposal, implementation=implemented
    )


def node_invocation(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    *,
    node_id: str,
    capability: str,
    slot_storage: str,
    selected: SelectedInput,
    shape: ProposalFamilies,
    results: dict[str, NodeOutput],
    outcomes: Mapping[str, AdaptorOutcome],
    iteration: int,
    admitted: TrainingAdmission | None,
    tuning_branch: tuple[str, str] | None,
    incumbent: float | None,
) -> NodeInvocation:
    if capability == "tuning":
        storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=slot_storage, run_name=initial.run_name),
        )
    elif isinstance(selected, (LiteratureReviewInput, InterpretationInput)):
        storage = selected.storage
    elif capability == "proposal":
        storage = selected.proposal.storage
    else:
        storage = selected.attempt.storage
    data_root = active_physical_data_root()
    if data_root is None:
        raise ValueError("graph unit dispatch requires the bound physical data root")
    admission = None
    if capability == "tuning":
        assert admitted is not None
        admission = admission_from(admitted, composition, config)
    return NodeInvocation(
        request=request,
        initial=initial,
        config=config,
        manifest_path=composition.provenance.manifest_path,
        composition_fingerprint=composition.semantic_fingerprint,
        physical_data_root=data_root,
        node_id=node_id,
        iteration=iteration,
        storage=storage,
        unit=phase_unit(
            node_id,
            capability,
            selected,
            shape,
            results,
            outcomes,
            admission,
            tuning_branch,
            incumbent,
        ),
    )
