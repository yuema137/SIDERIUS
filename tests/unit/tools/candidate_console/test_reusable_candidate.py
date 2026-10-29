"""Console policy ordering and retained launch identity across mutable editor state."""

import hashlib
import importlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tests.unit.tools.candidate_prepare.test_reusable_selection import published
from tools.candidate_console.reusable_candidate import ReusableCandidate
from tools.candidate_console.reusable_models import (
    ReusableCaptureChoice,
    ReusableCaptureLaunch,
    ReusableCaptureSelection,
)
from tools.candidate_console.service import CandidateConsole, preparation_request
from tools.candidate_operations import build_reusable_operation, operation_request_digest
from tools.candidate_operations.models import OperationFailure
from tools.candidate_operations.store import load_record
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
    return _captured(published, console_config, monkeypatch)


def _captured(published, console_config, monkeypatch):
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

        monkeypatch.setattr("tools.candidate_console.service.submit_operation", uncertain)
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


def test_launch_review_refuses_a_request_loop_absent_from_the_capture(captured, monkeypatch):
    """Fails if launch review reports a loop for a loop-free capture, or accepts a
    request loop absent from the capture. The positive end-to-end statement is
    ``test_launch_review_of_a_real_looped_capture_states_its_bound_and_stops``."""
    from workflows.definition import AuthoredLoop

    adapter, project, choice, _ = captured
    selected = adapter.select(project.project_id, choice)
    plain = adapter.review(project.project_id, selected)
    assert plain.loop is None and '"loop"' not in plain.model_dump_json()

    loop = AuthoredLoop.model_validate(
        {
            "final_iteration": 2,
            "feedback": {
                "source": {"kind": "result", "node": "fit", "port": "result"},
                "target": "interpret",
                "protocol": "tuning-to-interpretation",
                "history": "native-research/v1",
            },
        }
    )
    task, inspected, operation = adapter._operation(project.project_id, selected, uuid4())
    document = operation.request.preview.document
    preview = operation.request.preview.model_copy(
        update={
            "document": document.model_copy(
                update={"definition": document.definition.model_copy(update={"loop": loop})}
            )
        }
    )
    looped = operation.model_copy(
        update={"request": operation.request.model_copy(update={"preview": preview})}
    )
    monkeypatch.setattr(adapter, "_operation", lambda *args: (task, inspected, looped))
    with pytest.raises(OperationFailure, match="research loop differs from captured"):
        adapter.review(project.project_id, selected)


# B2-5: a JudgeStop authored in the editor reaches the launch review as declared.
JUDGE = {
    "kind": "judge",
    "criterion": "Stop once a body adds no new insight.",
    "min_completed_bodies": 2,
    "on_failure": "continue",
}


# The operator's judge route (WorkflowLLMConfig.judge); the declaration never names it.
JUDGE_ROUTE = {
    "provider": "openai",
    "model_id": "judge-fixture",
    "max_output_tokens": 800,
    "max_retries": 2,
}


def _looped_capture(reusable, console_config, monkeypatch, llm: dict):
    """A real five-node interpretation source with an authored loop and stop conditions,
    captured with ``llm`` as its model settings through the ordinary preparation child."""
    Path(reusable.llm_config_file).write_text(json.dumps(llm))
    from tests.browser.workflow_editor_server import interpretation_profile_source
    from tools.candidate_prepare import prepare_reusable_candidate, select_reusable_preparation
    from workflows.definition import parse_workflow_source, render_workflow_source

    document = parse_workflow_source(interpretation_profile_source())
    raw = document.model_dump(mode="json")
    raw["definition"]["task"] = parse_workflow_source(
        Path(reusable.source_path).read_text()
    ).definition.task.model_dump(mode="json")
    raw["definition"]["loop"]["final_iteration"] = 4
    raw["definition"]["loop"]["stop_conditions"] = [
        {"kind": "metric_threshold", "metric_id": "accuracy", "threshold": 0.85},
        {"kind": "no_improvement", "completed_bodies": 2},
        JUDGE,
    ]
    source = Path(reusable.source_path)
    source.write_text(render_workflow_source(type(document).model_validate_json(json.dumps(raw))))
    request = reusable.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "prepared", receipt.error
    envelope = Path(receipt.envelope)
    published = (request, envelope, select_reusable_preparation(receipt.envelope))
    return _captured(published, console_config, monkeypatch)


@pytest.fixture
def looped_capture(reusable, direct_child, console_config, monkeypatch):
    # final_iteration 4, judged from body 2: a static bound of 2 judge calls fits a cap of 3.
    llm = {"judge": {"stop": JUDGE_ROUTE, "max_judge_calls": 3}}
    return _looped_capture(reusable, console_config, monkeypatch, llm)


@pytest.mark.parametrize(
    ("judge", "message"),
    [
        (None, "requires a WorkflowLLMConfig.judge.stop route"),
        (
            {"stop": JUDGE_ROUTE, "max_judge_calls": 1},
            "may make 2 judge calls; max_judge_calls is 1",
        ),
    ],
    ids=["missing-route", "cap-below-bound"],
)
def test_launch_review_refuses_a_judge_the_captured_settings_cannot_run(
    reusable, direct_child, console_config, monkeypatch, judge, message
):
    """B2-5: Fails if a JudgeStop the captured model settings cannot run (no judge route,
    or a static call bound above max_judge_calls) passes review and is only refused by
    the worker after launch. The refusal is the worker owner's, typed ``judge_route``."""
    adapter, project, choice, _ = _looped_capture(
        reusable, console_config, monkeypatch, {} if judge is None else {"judge": judge}
    )
    selected = adapter.select(project.project_id, choice)
    with pytest.raises(OperationFailure) as refused:
        adapter.review(project.project_id, selected)
    assert refused.value.detail.code == "judge_route"
    assert message in refused.value.detail.message


def test_launch_review_of_a_real_looped_capture_states_its_bound_and_stops(looped_capture):
    """Fails if the launch review of a really captured looped source loses the loop,
    its final_iteration or its stop conditions on the way from source to the request
    the worker executes (nothing on either side is patched)."""
    adapter, project, choice, _ = looped_capture
    review = adapter.review(project.project_id, adapter.select(project.project_id, choice))
    assert json.loads(review.model_dump_json())["loop"] == {
        "final_iteration": 4,
        "feedback": {
            "source": {"kind": "result", "node": "fit", "port": "result"},
            "target": "interpret",
            "protocol": "tuning-to-interpretation",
            "history": "native-research/v1",
        },
        "stop_conditions": [
            {"kind": "metric_threshold", "metric_id": "accuracy", "threshold": 0.85},
            {"kind": "no_improvement", "completed_bodies": 2},
            JUDGE,
        ],
    }


def test_reviewed_resources_bind_the_reusable_launch_and_replay_idempotently(captured):
    """B3-4c: the reservation is part of the reviewed request digest."""
    from tools.candidate_operations.models import OperationResources

    adapter, project, choice, _ = captured
    resources = OperationResources(
        gpu_count=0, host_memory_gib=2.0, cpu_slots=1, time_budgeted=False
    )
    selection = adapter.select(project.project_id, choice).model_copy(
        update={"resources": resources}
    )
    plain = adapter.review(project.project_id, adapter.select(project.project_id, choice))
    review = adapter.review(project.project_id, selection)
    assert review.request_digest != plain.request_digest
    launch = launch_payload(review)
    first = adapter.launch(project.project_id, launch)
    replay = adapter.launch(project.project_id, launch)
    assert replay.observation == "existing" and replay.request_digest == first.request_digest
    changed = launch.model_copy(
        update={
            "candidate_operation_id": uuid4(),
            "selection": selection.model_copy(
                update={"resources": resources.model_copy(update={"cpu_slots": 2})}
            ),
        }
    )
    with pytest.raises(OperationFailure, match="review again"):
        adapter.launch(project.project_id, changed)


#: Issue #983 S6. Above 2**52, so a float round-trip would corrupt it.
SEED = 4_503_599_627_370_497


def test_capture_seed_is_bound_by_the_reviewed_digest_and_admitted(captured):
    """Fails if the candidate seed is not part of the reviewed request digest
    (a launch could then run a seed the operator never reviewed) or is not the
    seed the admitted operation records."""
    adapter, project, choice, _ = captured
    chosen = adapter.select(project.project_id, choice)
    assert "run_seed" not in chosen.model_dump_json()
    blank = adapter.review(project.project_id, chosen)
    seeded = adapter.review(project.project_id, chosen.model_copy(update={"run_seed": SEED}))
    native = build_reusable_operation(
        adapter.console.config.operation_store, chosen.preparation, uuid4(), SEED
    )
    assert seeded.request_digest == operation_request_digest(native) != blank.request_digest
    assert (blank.seed, seeded.seed) == ("Seed: generated at launch", f"Seed: {SEED} (you set)")
    handle = adapter.launch(project.project_id, launch_payload(seeded))
    record = load_record(adapter.console.config.operation_store, handle.operation_id)
    assert (record.run_seed.value, record.run_seed.source) == (SEED, "operator")
    with pytest.raises(ValidationError):
        ReusableCaptureSelection.model_validate(
            {**chosen.model_dump(mode="json"), "run_seed": 2**53}
        )
