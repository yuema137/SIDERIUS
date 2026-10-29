"""A later loop body may name an earlier experiment; the worker must not crash on it.

Release-gate run 25e91f63 failed at body 2 with "fresh candidate worker cannot
restore inherited experiment source" when the proposer built on body 1's model.
"""

from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.proposal import InheritedComponent, ProposalOutput
from tools.candidate_worker.phases import drop_experiment_inheritance


def _component(source_type: str, source_id: str) -> InheritedComponent:
    return InheritedComponent(
        component="hidden_width",
        source_type=source_type,
        source_id=source_id,
        contribution_evidence="Carried over from an earlier finding.",
    )


def _proposal(*components: InheritedComponent) -> ProposalOutput:
    return ProposalOutput(
        model_name="structured_feature_mlp",
        output_type="classifier",
        model_description="Second-body proposal.",
        mathematical_definition="MLP over engineered features.",
        motivation="Build on body 1.",
        expert_advice=ExpertAdvice(
            focus_areas=["capacity"],
            constraints=["tiny"],
            known_failures=[],
            suggested_directions=["wider hidden layer"],
            rationale="Fixture.",
        ),
        baseline_config={
            "model_config": {"hidden": 16},
            "train_config": {"lr": 1e-3, "epochs": 1, "batch_size": 4},
            "loss_config": {"loss_type": "focal"},
        },
        inherited_components=list(components),
    )


def test_experiment_claims_are_removed_and_other_sources_kept(capsys):
    human = _component("human", "human:instruction_1")
    proposal = _proposal(_component("experiment", "compact_tanh_mlp"), human)

    kept = drop_experiment_inheritance(proposal)

    assert kept.inherited_components == [human]
    assert "compact_tanh_mlp" in capsys.readouterr().out
    assert proposal.inherited_components[0].source_type == "experiment"


def test_a_proposal_without_experiment_claims_is_returned_unchanged():
    proposal = _proposal(_component("human", "human:instruction_1"))

    assert drop_experiment_inheritance(proposal) is proposal
