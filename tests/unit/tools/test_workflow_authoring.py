"""Disk boundary witnesses: race refusal, recovery and inert source handling.

Each assertion names disk/state behavior not enforced by declaration schemas.
"""

import multiprocessing
import os
from pathlib import Path

import pytest

from core.durable_io import publish_bytes_atomically
from tools.workflow_authoring.models import Project, ReviewRequest, SaveRequest, SourceProposal
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring

SOURCE = """from workflows.definition import WorkflowDocument, WorkflowDefinition, TaskReferences, ExternalBinding, NodeInstance, ExternalRequest
document = WorkflowDocument(definition=WorkflowDefinition(task=TaskReferences(manifest="missing.json", data_root="missing", workspace="missing"), externals=(ExternalBinding(id="seed", contract="proposal.input", location="old.json"),), nodes=(NodeInstance(id="p", capability="proposal", request=ExternalRequest(binding="seed")),)))
"""


@pytest.fixture
def editor(tmp_path):
    source = tmp_path / "workflow.py"
    source.write_text(SOURCE)
    source.chmod(0o644)
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    return WorkflowAuthoring(
        Project(
            project_id="test",
            project_root=tmp_path,
            source_file=source,
            recovery_directory=recovery,
        )
    )


def request(editor, text):
    review = editor.review(
        ReviewRequest(
            expected_sha256=editor.read().sha256,
            proposal=SourceProposal(kind="source", source=text),
        )
    )
    return SaveRequest(
        source=review.source, proposal_sha256=review.sha256, expected_sha256=editor.read().sha256
    )


def test_exact_recovery_mode_and_default_publication(editor, tmp_path):
    """Fails if save canonicalizes source, loses comments/base bytes, or chmods 0644."""
    proposed = "# keep this comment\n" + SOURCE.replace("old.json", "new.json")
    saved = editor.save(request(editor, proposed))
    assert editor.project.source_file.read_bytes() == proposed.encode()
    assert editor.project.source_file.stat().st_mode & 0o777 == 0o644
    assert {p.read_bytes() for p in editor.project.recovery_directory.iterdir()} == {
        SOURCE.encode(),
        proposed.encode(),
    }
    assert len(saved.recovery_ids) == 2
    default = tmp_path / "default"
    publish_bytes_atomically(str(default), b"default")
    assert default.stat().st_mode & 0o777 == 0o600


def test_stale_and_final_comparison_preserve_external_bytes(editor, monkeypatch):
    """Fails if either initial or post-backup comparison is bypassed."""
    proposal = request(editor, SOURCE.replace("old.json", "gui.json"))
    changed = SOURCE.replace("old.json", "agent.json")
    editor.project.source_file.write_text(changed)
    with pytest.raises(AuthoringError, match="changed"):
        editor.save(proposal)
    assert editor.project.source_file.read_text() == changed
    proposal = request(editor, SOURCE.replace("old.json", "gui.json"))
    original = editor._recover

    def race(payload):
        identity = original(payload)
        editor.project.source_file.write_text(SOURCE.replace("old.json", "second.json"))
        return identity

    monkeypatch.setattr(editor, "_recover", race)
    with pytest.raises(AuthoringError, match="before replacement"):
        editor.save(proposal)
    assert "second.json" in editor.project.source_file.read_text()


def test_recovery_failure_and_publish_failure_leave_base(editor, monkeypatch):
    """Fails if durability failures overwrite canonical before recovery completes."""
    proposal = request(editor, SOURCE.replace("old.json", "gui.json"))
    import tools.workflow_authoring.service as service

    def fail(*args, **kwargs):
        raise OSError("injected disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(service, "publish_bytes_write_once", fail)
        with pytest.raises(OSError):
            editor.save(proposal)
    assert editor.project.source_file.read_text() == SOURCE
    monkeypatch.setattr(service, "publish_bytes_atomically", fail)
    with pytest.raises(OSError):
        editor.save(proposal)
    assert editor.project.source_file.read_text() == SOURCE


def _writer(project, proposal, gate, output):
    editor = WorkflowAuthoring(Project.model_validate_json(project))
    gate.wait()
    try:
        editor.save(SaveRequest.model_validate_json(proposal))
        output.put("saved")
    except AuthoringError as error:
        output.put(error.code)


def test_real_cooperating_processes_and_stable_lock(editor):
    """A barrier releases two processes against one base; only one may replace it.

    Also holds the actual lock across a second config to distinguish locking from
    sequential digest comparison (same source, different recovery location).
    """
    context = multiprocessing.get_context("fork")
    gate, output = context.Barrier(2), context.Queue()
    proposals = [
        request(editor, SOURCE.replace("old.json", name)) for name in ("one.json", "two.json")
    ]
    processes = [
        context.Process(
            target=_writer,
            args=(editor.project.model_dump_json(), p.model_dump_json(), gate, output),
        )
        for p in proposals
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    outcomes = [output.get(timeout=2) for _ in processes]
    assert outcomes.count("saved") == 1
    assert any(x in {"conflict", "busy"} for x in outcomes)
    alternative = editor.project.project_root / "other-recovery"
    alternative.mkdir(mode=0o700)
    second = WorkflowAuthoring(
        editor.project.model_copy(update={"recovery_directory": alternative})
    )
    assert second.lock == editor.lock
    with editor._locked(), pytest.raises(AuthoringError, match="holds"):
        second.save(request(second, SOURCE.replace("old.json", "third.json")))


def test_inert_unsupported_and_bounded_paths(editor, tmp_path):
    """Opening executable source never imports it; observed path hazards refuse."""
    marker = tmp_path / "executed"
    editor.project.source_file.write_text(SOURCE + f'open({str(marker)!r}, "w").write("bad")\n')
    view = editor.read()
    assert view.document is None and view.diagnostics and not marker.exists()
    with pytest.raises(AuthoringError, match="read-only"):
        editor.save(
            SaveRequest(
                source=SOURCE,
                expected_sha256=view.sha256,
                proposal_sha256=__import__("hashlib").sha256(SOURCE.encode()).hexdigest(),
            )
        )
    editor.project.source_file.write_bytes(b"x" * 32769)
    with pytest.raises(AuthoringError, match="32 KiB"):
        editor.read()
    editor.project.source_file.unlink()
    editor.project.source_file.symlink_to(tmp_path / "other.py")
    with pytest.raises(AuthoringError, match="symlink"):
        editor.read()
