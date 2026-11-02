"""CSV task workflow: edit task paths and review budgets before preparing a run."""

from workflows.definition import (
    ArgumentBinding,
    ExternalRequest,
    ExternalSource,
    ManagedCandidateBinding,
    NodeInstance,
    ProtocolRequest,
    ResultSource,
    ReusableTaskReferences,
    ReusableWorkflowDefinition,
    ReusableWorkflowDocument,
)

document = ReusableWorkflowDocument(
    definition=ReusableWorkflowDefinition(
        # EDIT HERE: paths relative to this workflow; data holds your two CSV files.
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
    training_settings={
        "launch": {
            # EDIT HERE: choose time budgets for your data before preparing a run.
            "trial_time_budget_minutes": 2.0,
            "formal_time_budget_minutes": 5.0,
            "healthgate_mode": "blocking",
            "result_authority": "scientific",
            "is_trial": True,
            # Use all small-example training data for the Formal tuning round.
            "formal_portion": 1.0,
            "max_rounds": 2,  # Allow Trial before the forced Formal tuning round.
        },
    },
)
