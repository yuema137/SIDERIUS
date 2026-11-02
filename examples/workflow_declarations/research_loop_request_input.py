"""Run B: reusable Quickstart loop, with advice and a plateau input request.

Copy this file to $SCENARIO/workflow.py. As described in README.md, point
$SCENARIO/task.yaml at this checkout's configs/task_composition/quickstart.yaml
and generate $SCENARIO/data. Before preparing, read run A's merged findings:
$SCENARIO/run-a/candidate_run/adaptors/judge.out.result.json. Paste/trim their
content, citations and caveats into preparation_options.proposal_advice below.
Keep the example's summary at most 4000 characters so it can also be used as
Resume advice (the native ExpertContextItem.content limit is 100000). The
human_advice protocol argument is bound explicitly; expert_context is not wired.

From the checkout root, with the README-generated b-prepare.json and store.json:

    .venv/bin/python -m tools.candidate_prepare \
        --reusable-request "$SCENARIO/b-prepare.json" > "$SCENARIO/b-prepared.json"

Require status=prepared, then use the README's receipt-to-submission snippet to
write b-submit.json (it pins the reusable receipt and candidate request):

    .venv/bin/python -m tools.candidate_operations submit \
        --store-config "$SCENARIO/store.json" --request "$SCENARIO/b-submit.json"

Set SEGMENT to the returned operation_id. To request a manual pause:

    .venv/bin/python -m tools.candidate_operations pause-loop \
        --store-config "$SCENARIO/store.json" --operation-id "$SEGMENT"
    .venv/bin/python -m tools.candidate_operations status \
        --store-config "$SCENARIO/store.json" --operation-id "$SEGMENT"

Pause is cooperative at a body boundary. NoImprovementStop also requests input
after one completed non-improving body, if another body remains. It is not a
promise to pause: continuing improvements can reach final_iteration=3.
Wait for a paused receipt and an exited wrapper, then save UTF-8 advice in
$SCENARIO/resume-advice.txt (1..4000 characters after trimming; optionally reuse
the trimmed findings with a concrete next experiment). Resume with:

    .venv/bin/python -m tools.candidate_operations write-loop-resume \
        --store-config "$SCENARIO/store.json" --operation-id "$SEGMENT" \
        --advice-file "$SCENARIO/resume-advice.txt" --output "$SCENARIO/resume.json"
    .venv/bin/python -m tools.candidate_operations submit \
        --store-config "$SCENARIO/store.json" --request "$SCENARIO/resume.json"

Follow the NEW operation_id for status or further pauses. Use a new output
filename for each Resume; retry a submission with the same saved request.
Resume advice augments the declared proposal advice for that segment; editing
workflow.py after preparation does not edit a captured run. Terminal runs cannot
be resumed. Training needs an explicitly selected GPU and provider credentials;
parsing/importing this declaration is inert and requires neither.
"""

from workflows.definition import (
    ArgumentBinding,
    AuthoredLoop,
    CandidatePreparationOptions,
    ExternalRequest,
    ExternalSource,
    LoopFeedback,
    ManagedCandidateBinding,
    NodeInstance,
    NoImprovementStop,
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
            ManagedCandidateBinding(id="initial", contract="interpretation.input"),
            ManagedCandidateBinding(id="proposal_store", contract="storage"),
            ManagedCandidateBinding(id="build_store", contract="storage"),
            ManagedCandidateBinding(id="data", contract="optional.text"),
            ManagedCandidateBinding(id="task_ref", contract="optional.task-composition-ref"),
            ManagedCandidateBinding(id="advice", contract="optional.expert-advice"),
            ManagedCandidateBinding(id="constraints", contract="optional.constraint-context"),
            ManagedCandidateBinding(id="rules", contract="optional.parameter-rules"),
            ManagedCandidateBinding(id="training", contract="native-training.settings"),
        ),
        nodes=(
            NodeInstance(
                id="interpretation",
                capability="interpretation",
                request=ExternalRequest(binding="initial"),
            ),
            NodeInstance(
                id="proposal",
                capability="proposal",
                request=ProtocolRequest(
                    protocol="interpretation-to-proposal",
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node="interpretation")),
                        ArgumentBinding(
                            name="storage", source=ExternalSource(binding="proposal_store")
                        ),
                        ArgumentBinding(name="data_dir", source=ExternalSource(binding="data")),
                        ArgumentBinding(
                            name="task_composition_ref", source=ExternalSource(binding="task_ref")
                        ),
                        ArgumentBinding(
                            name="human_advice", source=ExternalSource(binding="advice")
                        ),
                        ArgumentBinding(
                            name="constraint_context", source=ExternalSource(binding="constraints")
                        ),
                        ArgumentBinding(
                            name="workflow_parameter_rules", source=ExternalSource(binding="rules")
                        ),
                    ),
                ),
            ),
            NodeInstance(
                id="implementation",
                capability="implementation",
                request=ProtocolRequest(
                    protocol="proposal-to-implementation",
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node="proposal")),
                        ArgumentBinding(
                            name="storage", source=ExternalSource(binding="build_store")
                        ),
                    ),
                ),
            ),
            NodeInstance(
                id="validation",
                capability="validation",
                request=ProtocolRequest(
                    protocol="proposed-implementation-to-validation",
                    arguments=(
                        ArgumentBinding(name="proposal", source=ResultSource(node="proposal")),
                        ArgumentBinding(
                            name="implementation", source=ResultSource(node="implementation")
                        ),
                        ArgumentBinding(
                            name="storage", source=ExternalSource(binding="build_store")
                        ),
                    ),
                ),
            ),
            NodeInstance(
                id="tuning",
                capability="tuning",
                request=ProtocolRequest(
                    protocol="validated-candidate-to-tuning",
                    arguments=(
                        ArgumentBinding(name="proposal", source=ResultSource(node="proposal")),
                        ArgumentBinding(name="validation", source=ResultSource(node="validation")),
                        ArgumentBinding(name="settings", source=ExternalSource(binding="training")),
                    ),
                ),
            ),
        ),
        loop=AuthoredLoop(
            final_iteration=3,
            feedback=LoopFeedback(
                source=ResultSource(node="tuning"),
                target="interpretation",
                protocol="tuning-to-interpretation",
                history="native-research/v1",
            ),
            stop_conditions=(NoImprovementStop(completed_bodies=1, on_met="request_input"),),
        ),
    ),
    execution_profile="native-interpretation-candidate/v1",
    preparation_options=CandidatePreparationOptions(
        # Replace this literal with your reviewed summary from run A before preparation.
        proposal_advice="Start with a small four-feature classifier. Preserve two output logits and compare bounded changes against the incumbent.",
        implementation_advice="Keep the Quickstart model interface and diagnostics explicit.",
        validation_advice="Check feature and class dimensions before training.",
        allowed_output_types=("classifier",),
    ),
    training_settings={
        "launch": {
            "healthgate_mode": "observe_only",
            "result_authority": "diagnostic",
            "require_probe_runner": True,
            "is_trial": True,
            # Use all small-example training data for the Formal tuning round.
            "formal_portion": 1.0,
            "max_rounds": 2,
            "trial_max_epochs": 1,
            "formal_max_epochs": 2,
            "trial_time_budget_minutes": 2.0,
            "formal_time_budget_minutes": 5.0,
            "allowed_output_types": ["classifier"],
        },
    },
)
