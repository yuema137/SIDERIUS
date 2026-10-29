"""Runs are attributed to their experiment setup and filtered by it before the list limit."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_console.test_new_run import fresh, intent, selection
from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_console.reusable_preparation import ReusablePreparation
from tools.candidate_console.service import CandidateConsole
from tools.candidate_console.settings_models import ExperimentSetupsPolicy
from tools.candidate_console.setups import SetupCreate, SetupStore
from tools.candidate_operations import operation_request_digest
from tools.candidate_operations.models import CandidateOperation, OperationFailure
from workflows.definition import ReusableWorkflowDocument, render_workflow_source
from workflows.definition.source import parse_workflow_source


@pytest.fixture
def attributed(fresh, tmp_path, monkeypatch):
    """The ``fresh`` legacy setup plus a registry setup ``created`` for the same task."""
    adapter, selection, project = fresh
    config = adapter.console.config
    workspace = tmp_path / "ws"
    (workspace / "settings").mkdir(parents=True, mode=0o700)
    workspace.chmod(0o700)
    store = SetupStore(workspace, ExperimentSetupsPolicy(browser_creatable=True))
    task = config.tasks[0]
    entry = store.create(config, task.task_id, SetupCreate(label="Created", template_id=None))
    # As an editor Save would: the setup's source becomes the runnable reusable declaration,
    # with the task's data root spelled absolutely (the setup folder has no ``data``).
    document = parse_workflow_source(project.source_file.read_text())
    assert isinstance(document, ReusableWorkflowDocument)
    task_refs = document.definition.task.model_copy(update={"data_root": task.data_root})
    document = document.model_copy(
        update={"definition": document.definition.model_copy(update={"task": task_refs})}
    )
    source = workspace / "projects" / entry.setup_id / "workflow.py"
    source.write_text(render_workflow_source(document))
    console = CandidateConsole(config, store)
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    # Several admitted, never-dispatched runs share one store in this test.
    monkeypatch.setattr("tools.candidate_operations.submit.releasable", lambda *a: True)
    return ReusablePreparation(console), selection, entry.setup_id, source


def _run(adapter, selection, setup_id, source=None):
    if source is not None:
        digest = hashlib.sha256(Path(source).read_bytes()).hexdigest()
        selection = selection.model_copy(update={"expected_source_sha256": digest})
    selection = selection.model_copy(
        update={"run_id": uuid4(), "preparation_operation_id": uuid4()}
    )
    review = adapter.review(setup_id, selection)
    adapter.prepare(setup_id, intent(review))
    return selection.preparation_operation_id


def test_filter_returns_the_setups_runs_and_keeps_unattributed_records(attributed):
    """Defect: a setup's Run list is empty (no recorded id), shows another setup's run,
    or drops records admitted before attribution existed."""
    adapter, selection, created, source = attributed
    console = adapter.console
    mine = _run(adapter, selection, created, source)
    other = _run(adapter, selection, "fresh")
    # A record admitted before attribution: the same request without ``setup_id``.
    old_selection = selection.model_copy(
        update={"run_id": uuid4(), "preparation_operation_id": uuid4()}
    )
    review, operation = adapter._review("fresh", old_selection)
    legacy = operation.model_copy(
        update={"request": operation.request.model_copy(update={"setup_id": None})}
    )
    expectation = review.expectation.model_copy(
        update={"request_digest": operation_request_digest(legacy)}
    )
    console.submit(legacy, launch_environment={}, expected_reusable_inputs=expectation)
    api = client(console.config)
    api.app.state.console.setup_store = console.setup_store  # same registry as the adapter

    def ids(query: str) -> list[str]:
        response = api.get("/api/operations" + query)
        assert response.status_code == 200, response.text
        return [row["operation_id"] for row in response.json()["operations"]]

    assert ids(f"?project_id={created}") == [str(mine)]
    assert ids("?project_id=fresh") == [str(other)]
    assert set(ids("")) == {str(mine), str(other), str(old_selection.preparation_operation_id)}
    rows = {
        r["operation_id"]: r["project_id"] for r in api.get("/api/operations").json()["operations"]
    }
    assert rows[str(old_selection.preparation_operation_id)] is None
    # Filtered before the limit: the older matching run survives newer unrelated ones.
    assert ids(f"?project_id={created}&limit=1") == [str(mine)]


def test_created_setup_run_under_another_task_is_refused(attributed):
    """Defect: attribution names a setup whose task differs from the run's task."""
    adapter, selection, created, _ = attributed
    console = adapter.console
    other = console.config.tasks[0].model_copy(update={"task_id": "other"})
    console.config = console.config.model_copy(update={"tasks": (*console.config.tasks, other)})
    with pytest.raises(OperationFailure) as refused:
        adapter.review(created, selection.model_copy(update={"task_id": "other"}))
    assert refused.value.detail.code == "task_policy"


def test_setup_id_is_bound_into_the_candidate_request_digest(attributed):
    """Defect: an operation ID replayed with another setup's attribution is accepted."""
    adapter, selection, created, source = attributed
    _, operation = adapter._review(
        created,
        selection.model_copy(
            update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        ),
    )
    assert operation.request.setup_id == created
    stripped = operation.model_copy(
        update={"request": operation.request.model_copy(update={"setup_id": None})}
    )
    assert operation_request_digest(stripped) != operation_request_digest(operation)
    assert '"setup_id"' not in stripped.request.model_dump_json()
    # The candidate submission binds its own attribution the same way (digest logic only).

    class Request:
        workflow_source = "captured"

        def model_dump(self, mode):
            return {"run_name": "r"}

    def candidate(setup_id):
        return CandidateOperation.model_construct(
            kind="candidate",
            request_id=uuid4(),
            request=Request(),
            reusable_preparation=None,
            resources=None,
            setup_id=setup_id,
        )

    assert operation_request_digest(candidate(None)) != operation_request_digest(candidate(created))
