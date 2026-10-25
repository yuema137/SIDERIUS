"""Guarded HTTP publication reuses real offline native composition, including drift refusal."""

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.tools.test_setup_composition_check import _external_hook_request
from tests.unit.workflows.reusable_fixture import reusable
from tools.candidate_console.editor import editor_router
from tools.setup_review.composition_check import check_task
from tools.workflow_authoring.models import Project, ReviewRequest, SaveRequest
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from tools.workflow_authoring.task_models import (
    TaskReferenceAcceptance,
    TaskReferenceAcknowledgement,
    TaskReferenceReview,
    TaskReferenceTarget,
    TaskReferenceUpdateProposal,
)
from workflows.definition import ReusableTaskReferences, TaskBinding, render_workflow_source

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit authorization for real bubblewrap namespaces",
)


def test_http_snapshot_publication_and_native_drift_after_recovery(tmp_path, monkeypatch):
    """A real original-owner observation permits adoption; changed plugin bytes cannot inherit its pin."""
    setup = _external_hook_request(tmp_path, monkeypatch, "")
    baseline = check_task(setup)
    assert baseline.result.outcome == "passed", baseline.result.failure
    facts = baseline.result.task
    pin = TaskBinding(
        package_id="external-quickstart",
        revision="explicit-snapshot",
        task_data_path_id=facts.task_data_path_id,
        semantic_fingerprint=facts.semantic_fingerprint,
    )
    manifest = Path(baseline.job.manifest)
    data = tmp_path / "unmounted-data"
    document = reusable()
    document = document.model_copy(
        update={
            "definition": document.definition.model_copy(
                update={"task": ReusableTaskReferences(manifest=str(manifest), data_root=str(data))}
            )
        }
    )
    source = tmp_path / "workflow.py"
    source.write_text(render_workflow_source(document))
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    observations = tmp_path / "observations"
    observations.mkdir()
    project = Project(
        project_id="publication",
        project_root=tmp_path,
        source_file=source,
        recovery_directory=recovery,
    )
    target = TaskReferenceTarget(
        choice_id="external-snapshot",
        binding=pin,
        manifest=manifest,
        data_root=data,
        llm_config_file=tmp_path / "agents.json",
        inspection_root=observations,
        read_only=setup.read_only,
        settings=setup.settings,
    )
    author = WorkflowAuthoring(project, (target,))
    selection = TaskReferenceUpdateProposal(
        selected_choice_id=target.choice_id, expected_task_binding=pin
    )
    app = FastAPI()
    app.include_router(editor_router((project,), task_targets=(target,)))
    original = source.read_bytes()
    with TestClient(app) as client:
        response = client.post(
            "/api/editor/publication/review",
            json=ReviewRequest(
                expected_sha256=author.read().sha256,
                proposal=selection,
            ).model_dump(mode="json"),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        review = TaskReferenceReview.model_validate(payload["task_reference_update"])
        assert review.save_supported and not review.execution_ready
        assert review.observation.sandbox.environment_names == ()
        assert review.observation.sandbox.devices == ()
        assert review.observation.sandbox.network is False
        acceptance = TaskReferenceAcceptance(
            selection=selection,
            adopt_current_snapshot=True,
            acknowledged_findings=tuple(
                TaskReferenceAcknowledgement(code=value.code, reference=value.reference)
                for value in review.findings
            ),
        )
        request = SaveRequest(
            source=payload["source"],
            expected_sha256=author.read().sha256,
            proposal_sha256=payload["sha256"],
            task_reference_acceptance=acceptance,
        )
        saved = client.post("/api/editor/publication/save", json=request.model_dump(mode="json"))
        assert saved.status_code == 200, saved.text
    assert source.read_text() == request.source
    assert original in {path.read_bytes() for path in recovery.iterdir()}
    assert len(tuple(observations.iterdir())) == 2
    assert not data.exists() and not (tmp_path / "real-run").exists()

    # Re-adoption on a fresh unbound snapshot exercises the actual post-recovery native guard.
    source.write_bytes(original)
    request = request.model_copy(update={"expected_sha256": author.read().sha256})
    recover = author._recover
    plugin = tmp_path / "task/plugins/_quickstart_task.py"

    def drift(payload):
        result = recover(payload)
        plugin.write_text(plugin.read_text() + "\n# changed after explicit review\n")
        return result

    monkeypatch.setattr(author, "_recover", drift)
    with pytest.raises(AuthoringError, match="publication is blocked") as failure:
        author.save(request)
    assert source.read_bytes() == original
    assert failure.value.proposal.source == request.source
    assert failure.value.proposal.task_reference_update.findings[0].code == "identity_mismatch"
    assert len(tuple(observations.iterdir())) == 3
