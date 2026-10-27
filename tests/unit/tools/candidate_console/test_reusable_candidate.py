"""Console policy ordering and retained launch identity across mutable editor state."""

import hashlib
import importlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tests.unit.tools.candidate_prepare.test_reusable_selection import published
from tools.candidate_console.reusable_candidate import ReusableCandidate
from tools.candidate_console.reusable_models import ReusableCaptureChoice, ReusableCaptureLaunch
from tools.candidate_console.service import CandidateConsole, preparation_request
from tools.candidate_operations import build_reusable_operation, operation_request_digest
from tools.candidate_operations.models import OperationFailure
from tools.workflow_authoring.models import Project


@pytest.fixture
def selection(selection):
    return selection.model_copy(update={"candidate_environment_names": ("OPENAI_API_KEY",)})


@pytest.fixture
def console_config(console_config, tmp_path):
    private = tmp_path / "credentials.json"
    private.write_text(json.dumps({"OPENAI_API_KEY": "offline-test-key"}))
    private.chmod(0o600)
    return console_config.model_copy(update={"credential_file": str(private)})


@pytest.fixture
def captured(published, console_config, monkeypatch):
    request, envelope, _retained = published
    root = Path(request.project_root)
    recovery = root / "recovery"
    recovery.mkdir(mode=0o700)
    project = Project(
        project_id="captured",
        project_root=root,
        source_file=Path(request.source_path),
        recovery_directory=recovery,
    )
    store = console_config.operation_store.model_copy(
        update={
            "preparation_roots": (
                *console_config.operation_store.preparation_roots,
                request.runs_root,
            ),
            "candidate_roots": (*console_config.operation_store.candidate_roots, request.runs_root),
        }
    )
    task = console_config.tasks[0].model_copy(
        update={"reusable_runs_root": request.runs_root, "allowed_output_types": None}
    )
    config = console_config.model_copy(
        update={
            "operation_store": store,
            "tasks": (task,),
            "editor_projects": (project,),
            "runnable_editor_projects": (project.project_id,),
        }
    )
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    adapter = ReusableCandidate(CandidateConsole(config))
    choice = ReusableCaptureChoice(task_id=task.task_id, run_id=request.run_id)
    return adapter, project, choice, envelope


def launch_payload(review):
    return ReusableCaptureLaunch(
        selection=review.selection,
        expected_request_digest=review.request_digest,
        candidate_operation_id=uuid4(),
    )


def test_policy_selection_curated_review_and_native_builder_parity(captured):
    """Legacy serialization must exclude the opt-in; review must bind B2 exact request."""
    from tools.candidate_console.models import PrepareSelection

    adapter, project, choice, envelope = captured
    task = adapter.console.config.tasks[0]
    legacy = preparation_request(
        task, PrepareSelection(operation_id=uuid4(), task_id=task.task_id, run_name="legacy")
    )
    assert "reusable_runs_root" not in legacy.model_dump()
    selected = adapter.select(project.project_id, choice)
    project.source_file.write_text("# newer authored source")
    review = adapter.review(project.project_id, selected)
    native = build_reusable_operation(
        adapter.console.config.operation_store, selected.preparation, uuid4()
    )
    assert review.request_digest == operation_request_digest(native)
    assert review.nodes[0] == ("hypothesis", "proposal")
    assert review.proposal_advice == "Prefer a small interpretable baseline"
    assert (
        review.source_sha256
        == hashlib.sha256((envelope / "workflow.py.snapshot").read_bytes()).hexdigest()
    )
    assert review.workspace == str(envelope / "workspace")
    assert len(review.composition_fingerprint) == 64
    assert "bridge_arguments" not in review.model_dump_json()
    assert not (envelope / "workspace").exists()


def test_review_refuses_concrete_only_profile_against_captured_declaration(captured, monkeypatch):
    """A wider concrete preview cannot expand reusable preparation admission."""
    adapter, project, choice, envelope = captured
    selected = adapter.select(project.project_id, choice)
    task, inspected, operation = adapter._operation(project.project_id, selected, uuid4())
    preview = operation.request.preview.model_copy(
        update={"execution_profile": "native-interpretation-candidate/v1"}
    )
    changed = operation.model_copy(
        update={"request": operation.request.model_copy(update={"preview": preview})}
    )
    monkeypatch.setattr(adapter, "_operation", lambda *args: (task, inspected, changed))
    with pytest.raises(
        OperationFailure, match="profile differs from captured reusable declaration"
    ):
        adapter.review(project.project_id, selected)
    assert not (envelope / "workspace").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_output_types", ("regressor",)),
        ("candidate_network", True),
        ("candidate_timeout_seconds", 8.0),
        ("task_read_only", ("/tmp",)),
    ],
)
def test_policy_refusal_precedes_external_observation(captured, monkeypatch, field, value):
    """Policy mismatch must reject before the full verifier reads even an allowed manifest."""
    adapter, project, choice, _ = captured
    config = adapter.console.config
    adapter.console.config = config.model_copy(
        update={"tasks": (config.tasks[0].model_copy(update={field: value}),)}
    )
    monkeypatch.setattr(
        "tools.candidate_prepare.reusable_selection.verify_sources",
        lambda *a, **kw: pytest.fail("external content read before policy"),
    )
    with pytest.raises(OperationFailure, match="policy"):
        adapter.select(project.project_id, choice)


def test_coherent_malicious_control_sources_refused_before_file_read(captured, monkeypatch):
    """Matching forged binding/control cannot authorize another external source path."""
    adapter, project, choice, envelope = captured
    binding_path = envelope / "binding.json"
    binding = json.loads(binding_path.read_bytes())
    binding["sources"][0]["path"] = str(envelope.parent.parent / "forbidden")
    binding_path.write_text(json.dumps(binding))
    digest = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    control_path = envelope / "inputs/preparation/request.json"
    control = json.loads(control_path.read_bytes())
    control.update(sources=binding["sources"], binding_sha256=digest)
    control_path.write_text(json.dumps(control))
    receipt_path = envelope / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["binding_sha256"] = digest
    receipt_path.write_text(json.dumps(receipt))
    module = importlib.import_module("tools.candidate_prepare.reusable_selection")
    original = module.safe_bytes

    def guarded(path):
        assert path.is_relative_to(envelope), "read external before policy"
        return original(path)

    monkeypatch.setattr(module, "safe_bytes", guarded)
    with pytest.raises(OperationFailure, match="observations differ"):
        adapter.select(project.project_id, choice)


def test_discovery_keeps_corrupt_entries_and_retained_path_cannot_escape(captured):
    """A corrupt sibling or symlink must not hide the valid capture or redirect selection."""
    adapter, project, choice, envelope = captured
    bad = envelope.parent / str(uuid4())
    bad.mkdir()
    alias = envelope.parent / str(uuid4())
    alias.symlink_to(envelope, target_is_directory=True)
    page = adapter.list_captures(project.project_id, choice.task_id)
    assert len(page.captures) == 3
    assert [c.run_id for c in page.captures if c.available] == [choice.run_id]
    first = adapter.list_captures(project.project_id, choice.task_id, limit=1)
    second = adapter.list_captures(
        project.project_id, choice.task_id, cursor=first.next_cursor, limit=1
    )
    assert first.captures[0].run_id != second.captures[0].run_id
    selection = adapter.select(project.project_id, choice)
    changed = selection.model_copy(
        update={"preparation": selection.preparation.model_copy(update={"envelope": str(bad)})}
    )
    with pytest.raises(OperationFailure, match="outside selected task"):
        adapter.review(project.project_id, changed)
    with pytest.raises(OperationFailure, match="not enabled"):
        adapter.select("disabled", choice)


def test_exact_recovery_precedes_live_policy_files_and_credentials(captured, monkeypatch):
    """Admitted UUID remains recoverable after file loss and policy change, without respawn."""
    adapter, project, choice, envelope = captured
    review = adapter.review(project.project_id, adapter.select(project.project_id, choice))
    launch = launch_payload(review)
    first = adapter.launch(project.project_id, launch)
    shutil.rmtree(envelope)
    project.source_file.unlink()
    adapter.console.config = adapter.console.config.model_copy(
        update={"runnable_editor_projects": (), "tasks": ()}
    )
    monkeypatch.setattr(
        "tools.candidate_console.reusable_candidate.credentials",
        lambda *a: pytest.fail("recovery reads credentials"),
    )
    replay = adapter.launch("navigation-context-only", launch)
    assert replay.observation == "existing" and replay.request_digest == first.request_digest
    with pytest.raises(OperationFailure, match="another capture"):
        adapter.launch(
            project.project_id, launch.model_copy(update={"expected_request_digest": "0" * 64})
        )
    with pytest.raises(OperationFailure, match="not enabled"):
        adapter.launch(
            project.project_id, launch.model_copy(update={"candidate_operation_id": uuid4()})
        )


def test_http_and_python_review_share_capture_and_digest(captured):
    """Routes must use exact typed adapter, exposing no native source or credentials."""
    from tests.unit.tools.candidate_console.test_http import client

    adapter, project, choice, _ = captured
    base = f"/api/editor/{project.project_id}/reusable-captures"
    with client(adapter.console.config) as http:
        response = http.post(base + "/select", json=choice.model_dump(mode="json"))
        assert response.status_code == 200, response.text
        selected = response.json()
        review = http.post(base + "/review", json=selected)
        assert review.status_code == 200, review.text
        expected = adapter.review(project.project_id, adapter.select(project.project_id, choice))
        assert review.json() == expected.model_dump(mode="json")
        launch = launch_payload(expected)
        started = http.post(base + "/launch", json=launch.model_dump(mode="json"))
        assert started.status_code == 202, started.text
        assert started.json()["request_digest"] == expected.request_digest


def test_http_refusal_signal_only_before_submission(captured, monkeypatch):
    """A response can mark this dispatch unsubmitted only before entering the operation owner."""
    from tests.unit.tools.candidate_console.test_http import client

    adapter, project, choice, envelope = captured
    review = adapter.review(project.project_id, adapter.select(project.project_id, choice))
    launch = launch_payload(review)
    receipt = envelope / "receipt.json"
    original = receipt.read_bytes()
    receipt.write_bytes(b"changed")
    with client(adapter.console.config) as http:
        path = f"/api/editor/{project.project_id}/reusable-captures/launch"
        response = http.post(path, json=launch.model_dump(mode="json"))
        assert response.status_code == 409 and response.json()["error"]["admission_not_attempted"]
        receipt.write_bytes(original)

        def uncertain(*args, **kwargs):
            raise OperationFailure("busy", "operation owner entered")

        monkeypatch.setattr(
            "tools.candidate_console.reusable_candidate.submit_operation", uncertain
        )
        response = http.post(path, json=launch.model_dump(mode="json"))
        assert response.status_code == 409
        assert "admission_not_attempted" not in response.json()["error"]


def test_output_restriction_direction_and_startup_root_scope(captured):
    """None means configured unconstrained, never captured permission to bypass an explicit limit."""
    from tools.candidate_console.reusable_policy import check_capture_policy
    from tools.candidate_prepare import inspect_current_reusable_binding

    adapter, project, _choice, envelope = captured
    config = adapter.console.config
    task = config.tasks[0]
    inspected = inspect_current_reusable_binding(str(envelope))
    for restriction in (("classifier",), ("regressor",), None):
        changed = inspected.model_copy(
            update={
                "binding": inspected.binding.model_copy(
                    update={
                        "request": inspected.binding.request.model_copy(
                            update={"allowed_output_types": restriction}
                        )
                    }
                )
            }
        )
        check_capture_policy(project, task, changed)
        explicit = task.model_copy(update={"allowed_output_types": ("classifier",)})
        if restriction == ("classifier",):
            check_capture_policy(project, explicit, changed)
        else:
            with pytest.raises(OperationFailure, match="output restriction"):
                check_capture_policy(project, explicit, changed)
    bad_store = config.operation_store.model_copy(
        update={"candidate_roots": (task.candidate_root,)}
    )
    with pytest.raises(ValueError, match="within both"):
        CandidateConsole(config.model_copy(update={"operation_store": bad_store}))
