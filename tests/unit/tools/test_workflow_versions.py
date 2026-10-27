"""Named-version record beside the source: schema, atomic write, backward compatibility.

Each test names the record behavior that Save, history or run preparation would
silently lose; Pydantic field declarations themselves are not retested.
"""

import json

import pytest
from pydantic import ValidationError

import tools.workflow_authoring.versions as versions
from tests.unit.tools.test_workflow_authoring import SOURCE, request
from tools.workflow_authoring.models import Project
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring, digest
from tools.workflow_authoring.versions import (
    VersionRecord,
    recorded_name,
    version_record_path,
)


@pytest.fixture
def editor(tmp_path):
    source = tmp_path / "workflow.py"
    source.write_text(SOURCE)
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


def _save(editor, text, name=None):
    return editor.save(request(editor, text).model_copy(update={"version_name": name}))


def _record(editor) -> dict:
    return json.loads(version_record_path(editor.project.source_file).read_text())


def _snapshot(editor):
    record = version_record_path(editor.project.source_file)
    return (
        editor.project.source_file.read_bytes(),
        record.read_bytes() if record.exists() else None,
        sorted(p.name for p in editor.project.recovery_directory.iterdir()),
    )


def test_unrecorded_workflow_lists_current_and_first_save_records_base(editor):
    """Fails if a pre-record workflow breaks history/Save or its base bytes are not versioned."""
    listed = editor.versions()
    assert not listed.record_present and listed.next_name == "v1"
    (only,) = listed.versions
    assert (only.origin, only.current, only.name) == ("unrecorded", True, None)
    assert only.sha256 == digest(SOURCE.encode())

    proposed = SOURCE.replace("old.json", "new.json")
    saved = _save(editor, proposed)
    assert saved.version_name == "v1"
    assert version_record_path(editor.project.source_file).name == "workflow.py.versions.json"
    record = _record(editor)
    assert record["schema_id"] == "siderius.workflow-versions/v1"
    assert record["source_name"] == "workflow.py"
    assert [(v["origin"], v["name"], v["sha256"]) for v in record["versions"]] == [
        ("observed", None, digest(SOURCE.encode())),
        ("saved", "v1", digest(proposed.encode())),
    ]
    rows = editor.versions().versions
    assert [(row.name, row.current) for row in rows] == [(None, False), ("v1", True)]
    detail = editor.version(1, rows[1].sha256)
    assert detail.source == proposed
    assert detail.diff is not None and "-" in detail.diff and "+" in detail.diff
    assert "new.json" in detail.diff and "old.json" in detail.diff


def test_named_saves_external_edit_and_unchanged_save(editor):
    """Fails if names/order are lost, an external edit is hidden, or a no-op adds a version."""
    first = SOURCE.replace("old.json", "a.json")
    _save(editor, first, "baseline")
    external = SOURCE.replace("old.json", "agent.json")
    editor.project.source_file.write_text(external)
    rows = editor.versions().versions
    assert [(row.origin, row.current) for row in rows][-2:] == [
        ("saved", False),
        ("unrecorded", True),
    ]
    assert editor.versions().next_name == "v2"
    second = SOURCE.replace("old.json", "b.json")
    assert _save(editor, second).version_name == "v2"
    names = [(v["origin"], v["name"]) for v in _record(editor)["versions"]]
    assert names == [
        ("observed", None),
        ("saved", "baseline"),
        ("observed", None),
        ("saved", "v2"),
    ]
    before = _snapshot(editor)
    assert _save(editor, second, "ignored").unchanged
    assert _snapshot(editor) == before


def test_refusals_happen_before_any_write(editor):
    """Fails if a duplicate name or invalid record lets Save publish source/recovery bytes."""
    _save(editor, SOURCE.replace("old.json", "a.json"), "baseline")
    before = _snapshot(editor)
    with pytest.raises(AuthoringError, match="already used") as error:
        _save(editor, SOURCE.replace("old.json", "b.json"), "baseline")
    assert error.value.code == "version_record"
    assert _snapshot(editor) == before

    path = version_record_path(editor.project.source_file)
    original = path.read_bytes()
    for invalid in (
        b"{}",
        original.replace(b'"workflow.py"', b'"other.py"'),
        b" " * (versions.MAX_VERSION_RECORD_BYTES + 1),
    ):
        path.write_bytes(invalid)
        before = _snapshot(editor)
        with pytest.raises(AuthoringError) as error:
            _save(editor, SOURCE.replace("old.json", "c.json"))
        assert error.value.code == "version_record"
        assert _snapshot(editor) == before
        with pytest.raises(AuthoringError):
            editor.versions()
    path.unlink()
    path.symlink_to(editor.project.source_file)
    with pytest.raises(AuthoringError, match="symlink"):
        _save(editor, SOURCE.replace("old.json", "c.json"))
    assert editor.project.source_file.read_text() == SOURCE.replace("old.json", "a.json")


def test_record_write_failure_is_atomic_and_reported_after_source_save(editor, monkeypatch):
    """Fails if a failed record write tears the record or reports the saved source as unsaved."""
    _save(editor, SOURCE.replace("old.json", "a.json"), "baseline")
    record_before = version_record_path(editor.project.source_file).read_bytes()
    real = versions.publish_bytes_atomically

    def fail_record(path, payload, mode=None):
        if path.endswith(".versions.json"):
            raise OSError("injected record failure")
        real(path, payload, mode=mode)

    monkeypatch.setattr(versions, "publish_bytes_atomically", fail_record)
    proposed = SOURCE.replace("old.json", "b.json")
    with pytest.raises(AuthoringError) as error:
        _save(editor, proposed, "next")
    assert error.value.code == "version_record"
    assert error.value.current is not None and error.value.current.source == proposed
    assert version_record_path(editor.project.source_file).read_bytes() == record_before
    assert not [p for p in editor.project.source_file.parent.iterdir() if p.suffix == ".tmp"]
    monkeypatch.undo()
    # Self-healing: the unrecorded saved bytes become an observed version at the next Save.
    _save(editor, SOURCE.replace("old.json", "c.json"), "after")
    assert [(v["origin"], v["name"]) for v in _record(editor)["versions"]][-2:] == [
        ("observed", None),
        ("saved", "after"),
    ]


def test_record_schema_refuses_ambiguous_history():
    """Fails if a hand-edited record could duplicate a name or carry an unnamed Save."""
    base = {"sha256": "0" * 64, "recorded_at": "2026-10-27T00:00:00Z"}
    named = {**base, "name": "v1", "origin": "saved"}
    for versions_value in (
        [named, {**named}],
        [{**base, "name": None, "origin": "saved"}],
        [{**base, "name": "x", "origin": "observed"}],
    ):
        with pytest.raises(ValidationError):
            VersionRecord.model_validate({"source_name": "workflow.py", "versions": versions_value})
    with pytest.raises(ValidationError):
        VersionRecord.model_validate({"schema_id": "other/v1", "source_name": "workflow.py"})


def test_missing_recovery_copy_shows_sha_only_and_stale_index_conflicts(editor):
    """Fails if history fabricates bytes for a pruned copy or serves a reordered row."""
    _save(editor, SOURCE.replace("old.json", "a.json"), "first")
    second = SOURCE.replace("old.json", "b.json")
    _save(editor, second, "second")
    rows = editor.versions().versions
    (editor.project.recovery_directory / (rows[1].sha256 + ".py")).unlink()
    rows = editor.versions().versions
    assert [row.bytes_available for row in rows] == [True, False, True]
    assert editor.version(1, rows[1].sha256).source is None
    detail = editor.version(2, rows[2].sha256)
    assert detail.source == second and detail.diff is None
    with pytest.raises(AuthoringError) as error:
        editor.version(2, rows[0].sha256)
    assert error.value.code == "conflict"


def test_preparation_name_lookup_is_display_only(editor):
    """Fails if run preparation shows a wrong name or a bad record blocks preparation review."""
    first = SOURCE.replace("old.json", "a.json")
    _save(editor, first, "baseline")
    source = editor.project.source_file
    assert recorded_name(source, digest(first.encode())) == "baseline"
    assert recorded_name(source, digest(SOURCE.encode())) is None
    version_record_path(source).write_text("not json")
    assert recorded_name(source, digest(first.encode())) is None
