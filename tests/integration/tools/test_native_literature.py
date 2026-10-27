"""Native literature worker input plus detached empty-review route coverage."""

import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import AgentCard, ExpertContextItem, ProposalInput
from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import (
    NamedLiteratureReviewOutput,
    local_typed_evidence_many,
)
from tests.helpers.candidate_literature import literature_request, write_literature_provider
from tests.integration.tools.test_candidate_operations import wait_for
from tests.integration.tools.test_candidate_operations_native import cli, native_submitter
from tests.unit.tools.candidate_worker.conftest import prepared, refresh
from tests.unit.tools.candidate_worker.test_native import native_runner
from tools.candidate_console.app import create_app
from tools.candidate_console.models import ConsoleConfig
from tools.candidate_operations import CandidateOperation, OperationStoreConfig, read_operation
from tools.candidate_operations.process import environment
from tools.candidate_operations.read import releasable
from tools.candidate_worker import launch_candidate


@pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)
def test_detached_empty_review_cli_http_and_native_accounting(prepared, tmp_path):
    """Actual retained worker and independent readers; no real retrieval or provider requests."""
    request = literature_request(prepared).model_copy(
        update={
            "environment_names": ("EXPLICIT_TEST_KEY", "OPENAI_API_KEY"),
        }
    )
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    config_path = tmp_path / "store.json"
    config_path.write_text(config.model_dump_json())
    project = Path(request.preview.project_root)
    submitter = native_submitter(tmp_path, project)
    write_literature_provider(project)
    operation = CandidateOperation(request_id=uuid4(), request=request)
    envelope = tmp_path / "candidate.json"
    envelope.write_text(operation.model_dump_json())
    result = cli(
        config_path,
        "submit",
        "--request",
        str(envelope),
        harness=submitter,
        env={
            **environment((), {}),
            "EXPLICIT_TEST_KEY": "bound-value",
            "OPENAI_API_KEY": "offline-test-key",
        },
    )
    assert json.loads(result.stdout)["observation"] == "starting"
    wait_for(lambda: releasable(config, operation.request_id), timeout=90)
    status = json.loads(
        cli(config_path, "status", "--operation-id", str(operation.request_id)).stdout
    )
    assert status["state"] == "completed", status
    receipt = read_operation(config, operation.request_id).receipt
    assert receipt.status == "accepted", (
        status,
        Path(receipt.log_path).read_text() if Path(receipt.log_path).exists() else "no native log",
    )
    trace = {item.node_id: item for item in receipt.graph_trace.nodes}
    assert len(trace) == 4 and all(item.state == "succeeded" for item in trace.values())
    assert trace["propose"].predecessors == ("review",)
    review = json.loads(Path(trace["review"].record_path).read_bytes())
    assert review["findings"] == [] and review["retrieved_papers"] == []
    assert review["search_decisions"] == []
    proposal = json.loads(
        (Path(receipt.workspace) / "candidate_run/proposal_inputs/propose.json").read_bytes()
    )
    assert proposal["literature_review_evidence"]["findings"] == []
    validation = json.loads(Path(trace["check0"].record_path).read_bytes())
    assert validation["tests_passed"] and validation["gradient_check_passed"]
    rows = [json.loads(line) for line in Path(receipt.ledger_path).read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["label"] == "lit_review.synthesis"
    assert rows[0]["run_id"] == receipt.run_id and rows[0]["tokens"]["total"] == 18
    token = tmp_path / "token"
    token.write_text(secrets.token_urlsafe(32))
    token.chmod(0o600)
    app = create_app(
        ConsoleConfig(
            operation_store=config,
            port=8765,
            browser_origin="http://127.0.0.1:8765",
            auth_token_file=str(token),
        )
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get(
            f"/api/operations/{operation.request_id}",
            headers={"Authorization": "Bearer " + token.read_text()},
        )
    assert response.status_code == 200, response.text
    assert response.json()["graph_trace"] == status["receipt"]["graph_trace"]


def test_external_proposal_worker_carries_multiple_attributed_reviews(
    prepared, native_runner, monkeypatch
):
    """Actual worker sends and persists the collection through native fake-provider calls."""

    project = Path(prepared.preview.project_root)
    seed_path = project / "seed.json"
    seed = ProposalInput.model_validate_json(seed_path.read_bytes())

    def review(agent_name: str, source_ref: str, claim: str) -> LiteratureReviewOutput:
        return LiteratureReviewOutput(
            agent_card=AgentCard(
                agent_name=agent_name,
                role="Reviews a bounded scientific literature area.",
                expertise_domain="Synthetic sequence modeling.",
                coverage=f"Sources represented by {source_ref}.",
                limitations="Claims need validation on the declared task.",
                trust_level="soft_prior",
                trust_guidance="Treat findings as external hypotheses.",
            ),
            findings=[
                ExpertContextItem(
                    source=agent_name,
                    kind="literature",
                    content=claim,
                    source_ref=source_ref,
                    confidence=0.7,
                )
            ],
            retrieved_papers=[],
            run_name=prepared.run_name,
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:01:00Z",
        )

    seed = local_typed_evidence_many(
        [
            NamedLiteratureReviewOutput(
                contribution_id="review-spectral",
                output=review(
                    "spectral-reviewer",
                    "doi:10.0000/spectral",
                    "A spectral loss may improve localized frequency residuals.",
                ),
            ),
            NamedLiteratureReviewOutput(
                contribution_id="review-time-domain",
                output=review(
                    "time-domain-reviewer",
                    "doi:10.0000/time",
                    "A spectral loss may hide time-domain transients.",
                ),
            ),
        ],
        proposal_input=seed,
    )
    seed_payload = seed.model_dump(mode="json")
    seed_payload.pop("storage")
    seed_path.write_text(json.dumps(seed_payload))
    request = refresh(prepared)
    provider_requests = []
    for method in ("generate_text", "generate"):
        original = getattr(native_runner, method)

        def capture(self, system, user, _original=original, **kwargs):
            provider_requests.append({"label": kwargs.get("label"), "system": system, "user": user})
            return _original(self, system, user, **kwargs)

        monkeypatch.setattr(native_runner, method, capture)

    receipt = launch_candidate(request)
    assert receipt.status == "accepted", receipt.error

    persisted = json.loads(
        (Path(receipt.workspace) / "candidate_run/proposal_input.json").read_bytes()
    )
    contributions = persisted["literature_review_evidence"]["reviews"]
    assert [item["contribution_id"] for item in contributions] == [
        "review-spectral",
        "review-time-domain",
    ]
    assert [item["evidence"]["agent_card"]["agent_name"] for item in contributions] == [
        "spectral-reviewer",
        "time-domain-reviewer",
    ]

    proposer_requests = [
        item for item in provider_requests if (item["label"] or "").startswith("proposer")
    ]
    assert proposer_requests
    request_text = "\n".join(item["user"] for item in proposer_requests)
    for expected in (
        "review-spectral",
        "spectral-reviewer",
        "doi:10.0000/spectral",
        "A spectral loss may improve localized frequency residuals.",
        "review-time-domain",
        "time-domain-reviewer",
        "doi:10.0000/time",
        "A spectral loss may hide time-domain transients.",
    ):
        assert expected in request_text
