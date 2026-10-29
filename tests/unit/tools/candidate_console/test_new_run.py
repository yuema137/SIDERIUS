"""Fresh policy before content reads and exact recovery before mutable source access."""

from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_console.reusable_preparation import (
    NewRunIntent,
    NewRunSelection,
    ReusablePreparation,
)
from tools.candidate_console.service import CandidateConsole
from tools.candidate_operations.models import OperationFailure
from tools.candidate_operations.store import load_record
from tools.workflow_authoring.models import Project


@pytest.fixture
def selection(selection, tmp_path):
    # These tests exercise inert admission, not task imports. All mutable input
    # bytes belong to this test, including the otherwise checkout-owned manifest.
    manifest = tmp_path / "task.yaml"
    manifest.write_bytes(Path(selection.task_manifest).read_bytes())
    return selection.model_copy(update={"task_manifest": str(manifest)})


@pytest.fixture
def fresh(reusable, console_config):
    root = Path(reusable.project_root)
    recovery = root / "recovery"
    recovery.mkdir(mode=0o700)
    project = Project(
        project_id="fresh",
        project_root=root,
        source_file=Path(reusable.source_path),
        recovery_directory=recovery,
    )
    store = console_config.operation_store.model_copy(
        update={
            "preparation_roots": (
                *console_config.operation_store.preparation_roots,
                reusable.runs_root,
            ),
            "candidate_roots": (
                *console_config.operation_store.candidate_roots,
                reusable.runs_root,
            ),
        }
    )
    task = console_config.tasks[0].model_copy(update={"reusable_runs_root": reusable.runs_root})
    config = console_config.model_copy(
        update={
            "operation_store": store,
            "tasks": (task,),
            "editor_projects": (project,),
            "runnable_editor_projects": ("fresh",),
        }
    )
    adapter = ReusablePreparation(CandidateConsole(config))
    selection = NewRunSelection(
        task_id=task.task_id,
        run_name="new-run",
        run_id=uuid4(),
        preparation_operation_id=uuid4(),
        expected_source_sha256=reusable.expected_source_sha256,
    )
    return adapter, selection, project


def intent(review):
    return NewRunIntent(selection=review.selection, expectation=review.expectation)


def test_review_no_effect_and_recovery_without_source(fresh, monkeypatch):
    adapter, selection, project = fresh
    review = adapter.review("fresh", selection)
    assert not Path(review.inputs).parent.exists()
    calls = []
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: calls.append(args))
    first = adapter.prepare("fresh", intent(review))
    project.source_file.unlink()
    monkeypatch.setattr(
        "tools.candidate_console.reusable_preparation.inspect_reusable_source",
        lambda *args: pytest.fail("recovery read source"),
    )
    second = adapter.prepare("removed-project", intent(review))
    assert first.operation_id == second.operation_id == selection.preparation_operation_id
    assert len(calls) == 1
    wrong = intent(review).model_copy(
        update={"expectation": review.expectation.model_copy(update={"request_digest": "0" * 64})}
    )
    with pytest.raises(OperationFailure, match="reviewed intent"):
        adapter.prepare("fresh", wrong)


def test_policy_before_external_content_on_review_and_prepare(fresh, monkeypatch):
    adapter, selection, project = fresh
    review = adapter.review("fresh", selection)
    config = adapter.console.config
    task = config.tasks[0].model_copy(
        update={"task_manifest": str(project.project_root / "forbidden")}
    )
    adapter.console.config = config.model_copy(update={"tasks": (task,)})
    monkeypatch.setattr(
        "tools.candidate_prepare.reusable_admission.admit",
        lambda *args, **kwargs: pytest.fail("external content before policy"),
    )
    for action in (
        lambda: adapter.review("fresh", selection),
        lambda: adapter.prepare("fresh", intent(review)),
    ):
        with pytest.raises(OperationFailure, match="policy"):
            action()
    assert not Path(review.inputs).parent.exists()


@pytest.mark.parametrize("which", ["source", "manifest", "config"])
def test_reviewed_observation_drift_never_dispatches(fresh, monkeypatch, which):
    adapter, selection, _ = fresh
    review = adapter.review("fresh", selection)
    observed = getattr(review.expectation.observations, which)
    with Path(observed.path).open("a") as stream:
        stream.write("\n# changed\n")
    monkeypatch.setattr(
        "tools.candidate_operations.submit.spawn",
        lambda *args: pytest.fail("dispatch after reviewed input drift"),
    )
    with pytest.raises(OperationFailure):
        adapter.prepare("fresh", intent(review))
    assert not Path(review.inputs).parent.exists()


def test_http_code_parity_and_presubmit_marker_boundary(fresh, monkeypatch):
    from tests.unit.tools.candidate_console.test_http import client

    adapter, selection, project = fresh
    http = client(adapter.console.config)
    path = "/api/editor/fresh/reusable-preparations/"
    review = adapter.review("fresh", selection)
    response = http.post(path + "review", json=selection.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json() == review.model_dump(mode="json")
    assert not Path(review.inputs).parent.exists()
    # Untrusted browser path/resource fields never reach native inspection.
    invalid = selection.model_dump(mode="json") | {"source_path": "/forbidden"}
    assert http.post(path + "review", json=invalid).status_code == 422
    project.source_file.write_text("# changed")
    response = http.post(path + "prepare", json=intent(review).model_dump(mode="json"))
    assert response.status_code == 409
    assert response.json()["error"]["admission_not_attempted"] is True


def test_recovery_rejects_changed_run_metadata(fresh, monkeypatch):
    adapter, selection, _ = fresh
    review = adapter.review("fresh", selection)
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    adapter.prepare("fresh", intent(review))
    for change in (
        {"run_id": uuid4()},
        {"run_name": "different"},
        {"expected_source_sha256": "0" * 64},
    ):
        changed = intent(review).model_copy(
            update={"selection": selection.model_copy(update=change)}
        )
        with pytest.raises(OperationFailure, match="retained selection"):
            adapter.prepare("fresh", changed)


def test_source_task_escape_refused_before_content_reader(fresh, monkeypatch):
    import hashlib

    from workflows.definition import (
        ReusableWorkflowDocument,
        parse_workflow_source,
        render_workflow_source,
    )

    adapter, selection, project = fresh
    document = parse_workflow_source(project.source_file.read_text()).model_dump()
    forbidden = project.project_root / "unconfigured.yaml"
    forbidden.write_text("not authorized to read this content")
    document["definition"]["task"]["manifest"] = str(forbidden)
    project.source_file.write_text(
        render_workflow_source(ReusableWorkflowDocument.model_validate(document))
    )
    changed = selection.model_copy(
        update={
            "expected_source_sha256": hashlib.sha256(project.source_file.read_bytes()).hexdigest()
        }
    )
    monkeypatch.setattr(
        "tools.candidate_prepare.admission.observe_file",
        lambda *args: pytest.fail("read external content before configured policy"),
    )
    with pytest.raises(OperationFailure, match="policy"):
        adapter.review("fresh", changed)


def test_submit_failure_is_not_presubmit_refusal(fresh, monkeypatch):
    from tests.unit.tools.candidate_console.test_http import client

    adapter, selection, _ = fresh
    review = adapter.review("fresh", selection)

    def fail(*args, **kwargs):
        raise OperationFailure("busy", "fixture owner already entered")

    monkeypatch.setattr("tools.candidate_console.service.submit_operation", fail)
    response = client(adapter.console.config).post(
        "/api/editor/fresh/reusable-preparations/prepare",
        json=intent(review).model_dump(mode="json"),
    )
    assert response.status_code == 409
    assert "admission_not_attempted" not in response.json()["error"]


def test_review_shows_recorded_version_name_without_changing_identity(fresh):
    """Fails if the Save name is not projected for the bound SHA or alters the expectation."""
    from tools.workflow_authoring.versions import VersionRecord, encode_record, version_record_path

    adapter, selection, project = fresh
    unnamed = adapter.review("fresh", selection)
    assert unnamed.source_version_name is None
    record = VersionRecord.model_validate(
        {
            "source_name": project.source_file.name,
            "versions": [
                {
                    "sha256": selection.expected_source_sha256,
                    "name": "baseline",
                    "recorded_at": "2026-10-27T00:00:00Z",
                    "origin": "saved",
                }
            ],
        }
    )
    version_record_path(project.source_file).write_bytes(encode_record(record))
    named = adapter.review("fresh", selection)
    assert named.source_version_name == "baseline"
    assert named.expectation == unnamed.expectation
    assert "source_version_name" not in intent(named).model_dump()


def test_preparation_review_prechecks_configured_credential_names(fresh, tmp_path):
    """R-5: before Prepare the server reports which configured names are absent, and a
    missing file is distinguished from an unreadable one; values never leave the process."""
    adapter, selection, _ = fresh
    task = adapter.console.config.tasks[0].model_copy(
        update={"candidate_environment_names": ("OPENAI_API_KEY",)}
    )
    path = tmp_path / "keys.env"
    adapter.console.config = adapter.console.config.model_copy(
        update={"tasks": (task,), "credential_file": str(path)}
    )
    missing = adapter.review("fresh", selection).credential_readiness
    assert (missing.file_status, missing.ready) == ("missing", False)
    assert missing.missing_names == ("OPENAI_API_KEY",)
    path.write_text("OPENAI_API_KEY=SECRET-MARKER\n")
    path.chmod(0o644)
    assert adapter.review("fresh", selection).credential_readiness.file_status == "unavailable"
    path.chmod(0o600)
    ready = adapter.review("fresh", selection)
    assert ready.credential_readiness.ready
    assert "SECRET-MARKER" not in ready.model_dump_json()


def _training_document(**launch):
    from workflows.definition import parse_workflow_source

    root = Path(__file__).resolve().parents[4]
    source = (root / "examples/workflow_declarations/reusable_training.py").read_text()
    document = parse_workflow_source(source)
    settings = dict(document.training_settings)
    settings["launch"] = {
        key: value for key, value in {**settings["launch"], **launch}.items() if value is not None
    }
    return document.model_copy(update={"training_settings": settings})


@pytest.mark.parametrize(
    ("launch", "fragment"),
    [
        ({"healthgate_mode": None, "result_authority": None}, "must declare"),
        ({"result_authority": None}, "--result_authority"),
        ({"result_authority": "scientific"}, "contradiction"),
    ],
    ids=["both-missing", "authority-missing", "observe-only-scientific"],
)
def test_preparation_review_refuses_undeclared_launch_policy(launch, fragment):
    """L-1: Review refuses what training admission would refuse after launch, with the
    launch-policy owner's own message; a declared legal pair passes."""
    from tools.candidate_console.reusable_preparation import check_declared_launch_policy

    check_declared_launch_policy(_training_document())
    with pytest.raises(OperationFailure, match=fragment) as raised:
        check_declared_launch_policy(_training_document(**launch))
    assert raised.value.detail.code == "launch_policy"


@pytest.mark.parametrize("with_workspace", [False, True])
def test_console_app_protects_workspace_settings_at_admission(fresh, with_workspace):
    """Defect: the served app admits a read-only input over the workspace settings/library.

    ``create_app`` must pass the startup workspace into the reusable preparation
    route's protected set; without a workspace the same review is admitted.
    """
    from fastapi.testclient import TestClient

    from tools.candidate_console.app import create_app
    from tools.candidate_console.settings_models import SettingsContext

    adapter, selection, _ = fresh
    config = adapter.console.config
    # A workspace whose settings/ and library/ lie inside the task's data folder.
    context = SettingsContext(Path(config.tasks[0].data_root) / "ws", frozenset())
    api = TestClient(
        create_app(config, context if with_workspace else None),
        base_url=config.browser_origin,
        raise_server_exceptions=False,
    )
    api.headers.update(
        {
            "Authorization": "Bearer " + Path(config.auth_token_file).read_text(),
            "Origin": config.browser_origin,
        }
    )
    response = api.post(
        "/api/editor/fresh/reusable-preparations/review", json=selection.model_dump(mode="json")
    )
    if with_workspace:
        assert response.status_code == 409 and response.json()["error"]["code"] == "stale_review"
    else:
        assert response.status_code == 200, response.text


#: Issue #983 S6. Above 2**52, so a float round-trip would corrupt it.
SEED = 4_503_599_627_370_497


def test_new_run_seed_reaches_the_admitted_preparation_and_blank_keeps_bytes(fresh, monkeypatch):
    """Fails if the entered seed is dropped between review and admission, if a
    blank seed changes the reviewed selection bytes or request digest, or if
    recovery accepts a retained intent whose seed differs from the admitted one."""
    adapter, chosen, _ = fresh
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    blank = adapter.review("fresh", chosen)
    assert "run_seed" not in chosen.model_dump_json()
    assert blank.seed == "Seed: generated at launch"
    seeded_selection = chosen.model_copy(update={"run_seed": SEED})
    seeded = adapter.review("fresh", seeded_selection)
    assert seeded.seed == f"Seed: {SEED} (you set)"
    assert seeded.expectation.request_digest != blank.expectation.request_digest
    adapter.prepare("fresh", intent(seeded))
    record = load_record(adapter.console.config.operation_store, chosen.preparation_operation_id)
    assert (record.run_seed.value, record.run_seed.source) == (SEED, "operator")
    changed = intent(seeded).model_copy(
        update={"selection": seeded_selection.model_copy(update={"run_seed": SEED - 1})}
    )
    with pytest.raises(OperationFailure, match="retained selection"):
        adapter.prepare("fresh", changed)
