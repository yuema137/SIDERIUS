"""One actual writer guards reviewed snapshots, races and no-op verification."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.tools.test_task_reference_review import (
    child_result,
    update,
)
from tests.unit.tools.test_task_reference_review import (
    configured as configured,
)
from tools.candidate_console.editor import editor_router, task_reference_targets
from tools.setup_review import composition_check
from tools.workflow_authoring.models import (
    DocumentProposal,
    ReviewRequest,
    SaveRequest,
    SourceProposal,
)
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from tools.workflow_authoring.task_models import (
    TaskReferenceAcceptance,
    TaskReferenceAcknowledgement,
)
from workflows.definition import (
    ReusableTaskReferences,
    parse_workflow_source,
    render_workflow_source,
)


def snapshot_author(configured):
    project, choice = configured
    plain = parse_workflow_source(project.source_file.read_text())
    plain = plain.model_copy(
        update={
            "definition": plain.definition.model_copy(
                update={
                    "task": ReusableTaskReferences(
                        manifest=choice.task_manifest, data_root=choice.data_root
                    ),
                }
            )
        }
    )
    project.source_file.write_text(render_workflow_source(plain))
    return WorkflowAuthoring(project, task_reference_targets((choice,))), choice


def acceptance(review, choice):
    from tools.workflow_authoring.task_models import TaskReferenceUpdateProposal

    report = review.task_reference_update
    return TaskReferenceAcceptance(
        selection=TaskReferenceUpdateProposal(
            selected_choice_id=choice.task_id, expected_task_binding=choice.task_revision
        ),
        acknowledged_findings=tuple(
            TaskReferenceAcknowledgement(code=value.code, reference=value.reference)
            for value in report.findings
        ),
        adopt_current_snapshot=any(
            value.code == "current_snapshot_adoption" for value in report.findings
        ),
    )


def save_request(author, review, choice):
    return SaveRequest(
        source=review.source,
        expected_sha256=author.read().sha256,
        proposal_sha256=review.sha256,
        task_reference_acceptance=acceptance(review, choice),
    )


def bound_edit(author, choice, source=None):
    selection = update(author, choice).proposal
    return author.review(
        ReviewRequest(
            expected_sha256=author.read().sha256,
            proposal=SourceProposal(kind="source", source=source or author.read().source),
            task_reference_selection=selection,
        )
    )


def test_http_adoption_then_code_edit_and_noop_share_writer(configured, monkeypatch):
    """Explicit adoption saves the observed current snapshot, then source/code edits reverify."""
    author, choice = snapshot_author(configured)
    calls = []

    def child(profile, argv):
        calls.append(profile.workspace)
        return child_result(profile, argv)

    monkeypatch.setattr(composition_check, "run", child)
    original = author.project.source_file.read_bytes()
    reviewed = author.review(update(author, choice))
    assert reviewed.task_reference_update.save_supported is True
    assert reviewed.task_reference_update.execution_ready is False
    app = FastAPI()
    app.include_router(
        editor_router((author.project,), task_targets=task_reference_targets((choice,)))
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/editor/edit/save",
            json=save_request(author, reviewed, choice).model_dump(mode="json"),
        )
    assert response.status_code == 200, response.text
    assert author.project.source_file.read_text() == reviewed.source
    assert parse_workflow_source(reviewed.source).task_binding == choice.task_revision
    assert original in {path.read_bytes() for path in author.project.recovery_directory.iterdir()}
    assert len(calls) == 2, "Review and final publication need independent owner observations"
    edited = bound_edit(
        author, choice, author.read().source + "\n# explicitly reviewed code edit\n"
    )
    author.save(save_request(author, edited, choice))
    assert "explicitly reviewed code edit" in author.read().source
    noop = bound_edit(author, choice)
    before = len(calls)
    result = author.save(save_request(author, noop, choice))
    assert result.unchanged and result.recovery_ids == ()
    assert len(calls) == before + 1, "No-op cannot skip native verification"


@pytest.mark.parametrize(
    "fault", ["acceptance", "adoption_intent", "pin_removal", "changed_identity"]
)
def test_unsupported_publication_cannot_overwrite_snapshot(configured, monkeypatch, fault):
    author, choice = snapshot_author(configured)
    monkeypatch.setattr(composition_check, "run", child_result)
    reviewed = author.review(update(author, choice))
    request = save_request(author, reviewed, choice)
    if fault == "acceptance":
        request = request.model_copy(
            update={
                "task_reference_acceptance": request.task_reference_acceptance.model_copy(
                    update={"acknowledged_findings": ()}
                )
            }
        )
    elif fault == "adoption_intent":
        request = request.model_copy(
            update={
                "task_reference_acceptance": request.task_reference_acceptance.model_copy(
                    update={"adopt_current_snapshot": False}
                )
            }
        )
    elif fault == "pin_removal":
        author.save(request)
        plain = parse_workflow_source(author.read().source).model_copy(
            update={"task_binding": None}
        )
        source = render_workflow_source(plain)
        from tools.workflow_authoring.service import digest

        request = SaveRequest(
            source=source,
            expected_sha256=author.read().sha256,
            proposal_sha256=digest(source.encode()),
            task_reference_acceptance=request.task_reference_acceptance,
        )
    else:
        # A reviewed label stays the same, but the original owner now reports different contents.
        monkeypatch.setattr(
            composition_check,
            "run",
            lambda profile, argv: child_result(profile, argv, fingerprint="b" * 64),
        )
    before = author.project.source_file.read_bytes()
    with pytest.raises(AuthoringError):
        author.save(request)
    assert author.project.source_file.read_bytes() == before


def test_task_edit_during_recovery_is_rechecked_before_publication(configured, monkeypatch):
    """Dropping the real post-recovery guard permits this modified task to publish."""
    author, choice = snapshot_author(configured)

    def observed(profile, argv):
        fingerprint = (
            "a" * 64
            if Path(choice.task_manifest).read_text() == "trusted fixture declaration"
            else "b" * 64
        )
        return child_result(profile, argv, fingerprint=fingerprint)

    monkeypatch.setattr(composition_check, "run", observed)
    review = author.review(update(author, choice))
    request = save_request(author, review, choice)
    original = author.project.source_file.read_bytes()
    recover = author._recover

    def race(payload):
        result = recover(payload)
        Path(choice.task_manifest).write_text("changed while recovering")
        return result

    monkeypatch.setattr(author, "_recover", race)
    with pytest.raises(AuthoringError, match="publication is blocked") as failure:
        author.save(request)
    assert failure.value.proposal.source == request.source
    assert failure.value.proposal.task_reference_update.findings[0].code == "identity_mismatch"
    assert author.project.source_file.read_bytes() == original


def test_source_agent_race_and_stale_noop_remain_refused(configured, monkeypatch):
    author, choice = snapshot_author(configured)
    monkeypatch.setattr(composition_check, "run", child_result)
    initial = author.review(update(author, choice))
    author.save(save_request(author, initial, choice))
    changed = bound_edit(author, choice, author.read().source + "\n# pending\n")
    request = save_request(author, changed, choice)
    recover = author._recover

    def race(payload):
        result = recover(payload)
        author.project.source_file.write_text(request.source + "\n# agent won\n")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(author, "_recover", race)
        with pytest.raises(AuthoringError, match="source changed before replacement"):
            author.save(request)
    assert "agent won" in author.read().source
    noop = bound_edit(author, choice)
    request = save_request(author, noop, choice)
    monkeypatch.setattr(
        composition_check,
        "run",
        lambda profile, argv: child_result(profile, argv, fingerprint="b" * 64),
    )
    with pytest.raises(AuthoringError, match="publication is blocked"):
        author.save(request)


def test_code_document_edits_need_selection_and_adoption_cannot_smuggle_settings(
    configured, monkeypatch
):
    author, choice = snapshot_author(configured)
    monkeypatch.setattr(composition_check, "run", child_result)
    review = author.review(update(author, choice))
    proposed = review.document.model_copy(
        update={
            "preparation_options": review.document.preparation_options.model_copy(
                update={"proposal_advice": "new scientific advice"}
            )
        }
    )
    selected = update(author, choice).proposal
    result = author.review(
        ReviewRequest(
            expected_sha256=author.read().sha256,
            proposal=DocumentProposal(kind="document", document=proposed),
            task_reference_selection=selected,
        )
    )
    assert not result.task_reference_update.save_supported
    with pytest.raises(AuthoringError, match="publication is blocked"):
        author.save(save_request(author, result, choice))
    author.save(save_request(author, review, choice))
    with pytest.raises(AuthoringError, match="requires explicit task-reference selection"):
        author.review(
            ReviewRequest(
                expected_sha256=author.read().sha256,
                proposal=SourceProposal(kind="source", source=author.read().source),
            )
        )


@pytest.mark.parametrize("tamper", ["source", "mode"])
def test_noop_rechecks_source_and_mode_after_native_observation(configured, monkeypatch, tamper):
    """A slow no-op inspection cannot report stale bytes/mode as confirmed unchanged."""
    author, choice = snapshot_author(configured)
    monkeypatch.setattr(composition_check, "run", child_result)
    initial = author.review(update(author, choice))
    author.save(save_request(author, initial, choice))
    review = bound_edit(author, choice)
    request = save_request(author, review, choice)
    source = author.project.source_file

    def race(profile, argv):
        result = child_result(profile, argv)
        if tamper == "source":
            source.write_text(request.source + "\n# external edit during no-op inspection\n")
        else:
            source.chmod(0o600 if source.stat().st_mode & 0o777 != 0o600 else 0o644)
        return result

    monkeypatch.setattr(composition_check, "run", race)
    with pytest.raises(AuthoringError, match="source changed before replacement"):
        author.save(request)
    if tamper == "source":
        assert "external edit during no-op" in source.read_text()


@pytest.mark.parametrize("previous_policy", ["configured", "missing", "ambiguous"])
def test_relocation_needs_unambiguous_original_policy(configured, monkeypatch, previous_policy):
    """Same native identity permits relocation only after both configured owners observe it."""
    author, choice = snapshot_author(configured)
    targets = task_reference_targets((choice,))
    old = targets[0]
    relocated_manifest = old.manifest.with_name("relocated.yaml")
    relocated_manifest.write_text(old.manifest.read_text())
    target = old.model_copy(
        update={
            "choice_id": "relocated",
            "manifest": relocated_manifest,
            "data_root": old.data_root.with_name("relocated-data"),
            "binding": old.binding.model_copy(update={"revision": "same-native-new-label"}),
        }
    )
    if previous_policy == "configured":
        configured_targets = (old, target)
    elif previous_policy == "missing":
        configured_targets = (target,)
    else:
        configured_targets = (old, old.model_copy(update={"choice_id": "ambiguous"}), target)
    author = WorkflowAuthoring(author.project, configured_targets)
    calls = []

    def child(profile, argv):
        calls.append(profile.workspace)
        return child_result(profile, argv)

    monkeypatch.setattr(composition_check, "run", child)
    from tools.workflow_authoring.task_models import TaskReferenceUpdateProposal

    result = author.review(
        ReviewRequest(
            expected_sha256=author.read().sha256,
            proposal=TaskReferenceUpdateProposal(
                selected_choice_id=target.choice_id, expected_task_binding=target.binding
            ),
        )
    )
    report = result.task_reference_update
    assert report.save_supported is (previous_policy == "configured")
    assert len(calls) == (2 if previous_policy == "configured" else 1)
    assert (report.current_observation is not None) is (previous_policy == "configured")
    assert author.read().document.task_binding is None, "Review never publishes"
