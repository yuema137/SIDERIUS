"""A later loop body may name an earlier experiment; the worker must not fail on it.

Release-gate run 25e91f63 failed at body 2 with "fresh candidate worker cannot
restore inherited experiment source" when the proposer built on body 1's model.
"""

import json
from pathlib import Path

from tools.candidate_worker import launch_candidate

from .conftest import refresh
from .test_native import native_runner as native_runner

CLAIM = {
    "component": "hidden_width",
    "source_type": "experiment",
    "source_id": "compact_tanh_mlp",
    "contribution_evidence": "Body 1 learned the boundary with this width.",
}


def test_experiment_inheritance_claim_is_kept_and_the_candidate_runs(
    prepared, native_runner, monkeypatch
):
    from agent.schemas.proposal import InheritedComponent
    from nodes.ml_model_proposal_agent.ml_model_proposal_agent import MLModelProposalAgent

    original = MLModelProposalAgent.run

    def run_with_claim(self, seed):
        # The native proposer writes its record and returns the same object; a
        # causal-stage claim reaches both. Reproduce that with one added claim.
        proposal = original(self, seed)
        proposal = proposal.model_copy(
            update={"inherited_components": [InheritedComponent.model_validate(CLAIM)]}
        )
        record = Path(seed.storage.local.workspace) / f"proposal_{seed.storage.local.run_name}.json"
        record.write_text(proposal.model_dump_json(indent=2))
        return proposal

    monkeypatch.setattr(MLModelProposalAgent, "run", run_with_claim)
    receipt = launch_candidate(refresh(prepared))

    assert receipt.status == "accepted", receipt.error
    proposal = json.loads(Path(receipt.native_output_paths[0]).read_text())
    assert [item["source_id"] for item in proposal["inherited_components"]] == ["compact_tanh_mlp"]
