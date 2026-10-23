"""Inert reusable candidate example: authoring and pure resolution only, no launch."""

from workflows.definition import (
    ArgumentBinding,
    CandidatePreparationOptions,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    ManagedCandidateBinding,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    ReusableTaskReferences,
    ReusableWorkflowDefinition,
    ReusableWorkflowDocument,
)

document = ReusableWorkflowDocument(
    definition=ReusableWorkflowDefinition(
        task=ReusableTaskReferences(manifest="task.yaml", data_root="data"),
        externals=(
            ManagedCandidateBinding(id="initial", contract="proposal.input"),
            ManagedCandidateBinding(id="build_store", contract="storage"),
            ManagedCandidateBinding(id="check_store", contract="storage"),
            ExternalBinding(
                id="context", contract="optional.constraint-context", location="context.json"
            ),
        ),
        nodes=(
            NodeInstance(
                id="hypothesis", capability="proposal", request=ExternalRequest(binding="initial")
            ),
            NodeInstance(
                id="build",
                capability="implementation",
                request=ProtocolRequest(
                    protocol="proposal-to-implementation",
                    arguments=(
                        ArgumentBinding(
                            name="storage", source=ExternalSource(binding="build_store")
                        ),
                        ArgumentBinding(name="output", source=ResultSource(node="hypothesis")),
                        ArgumentBinding(
                            name="constraint_context", source=ExternalSource(binding="context")
                        ),
                    ),
                ),
            ),
            NodeInstance(
                id="check",
                capability="validation",
                request=ProtocolRequest(
                    protocol="implementation-to-validation",
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node="build")),
                        ArgumentBinding(
                            name="storage", source=ExternalSource(binding="check_store")
                        ),
                    ),
                ),
            ),
        ),
    ),
    positions=(NodePosition(node="build", x=120.0, y=-30.0),),
    preparation_options=CandidatePreparationOptions(
        proposal_advice="Prefer a small interpretable baseline",
        implementation_advice="Keep diagnostics explicit",
        validation_advice="Inspect held-out residuals",
        allowed_output_types=("regressor",),
    ),
)
