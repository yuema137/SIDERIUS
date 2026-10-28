"""Inert reusable candidate example: source-owned native training; customize task/profile before launch."""

from workflows.definition import (
    ArgumentBinding,
    CandidatePreparationOptions,
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
            ManagedCandidateBinding(id="training", contract="native-training.settings"),
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
            NodeInstance(
                id="fit",
                capability="tuning",
                request=ProtocolRequest(
                    protocol="validated-candidate-to-tuning",
                    arguments=(
                        ArgumentBinding(name="proposal", source=ResultSource(node="hypothesis")),
                        ArgumentBinding(name="validation", source=ResultSource(node="check")),
                        ArgumentBinding(name="settings", source=ExternalSource(binding="training")),
                    ),
                ),
            ),
        ),
    ),
    positions=(NodePosition(node="build", x=120.0, y=-30.0),),
    training_settings={
        "launch": {
            "trial_time_budget_minutes": 2.0,
            "formal_time_budget_minutes": 5.0,
            "healthgate_mode": "observe_only",
            "result_authority": "diagnostic",
        },
    },
    preparation_options=CandidatePreparationOptions(
        proposal_advice="Prefer a small interpretable baseline",
        implementation_advice="Keep diagnostics explicit",
        validation_advice="Inspect held-out residuals",
        allowed_output_types=("classifier",),
    ),
)
