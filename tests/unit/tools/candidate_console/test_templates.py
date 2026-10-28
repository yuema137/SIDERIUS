"""Workflow templates: task-agnostic shapes, preparable roles, and a write-free import."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.unit.tools.test_workflow_authoring import SOURCE
from tests.unit.workflows.reusable_fixture import EXAMPLE, reusable
from tools.candidate_console.app import create_app
from tools.candidate_prepare.resolution import check_candidate_roles
from tools.workflow_authoring.advice_targets import advice_targets
from tools.workflow_authoring.models import Project
from tools.workflow_authoring.templates import (
    TemplateRefusal,
    instantiate,
    template_catalog,
    template_document,
)
from workflows.definition import (
    ReusableTaskReferences,
    ReusableWorkflowDocument,
    TaskBinding,
    parse_workflow_source,
    render_workflow_source,
)
from workflows.definition.candidate import candidate_nodes
from workflows.definition.fanout import execution_families

TEMPLATE_IDS = [template.id for template in template_catalog().templates]
PIN = TaskBinding(
    package_id="example-task",
    revision="r1",
    task_data_path_id="example-data",
    semantic_fingerprint="a" * 64,
)


def _bound_source_document() -> ReusableWorkflowDocument:
    document = reusable()
    return document.model_copy(
        update={
            "task_binding": PIN,
            "definition": document.definition.model_copy(
                update={
                    "task": ReusableTaskReferences(manifest="pkg/manifest.yaml", data_root="d/x")
                }
            ),
        }
    )


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_keeps_project_task_and_passes_preparation_roles(template_id):
    """Fails if a template invents task/data references, drops the accepted pin, or
    is a shape the reusable preparation would refuse (misrouted/unused externals)."""
    imported = parse_workflow_source(instantiate(template_id, _bound_source_document()))
    assert isinstance(imported, ReusableWorkflowDocument)
    assert imported.definition.task == ReusableTaskReferences(
        manifest="pkg/manifest.yaml", data_root="d/x"
    )
    assert imported.task_binding == PIN
    proposals = (
        {candidate_nodes(imported.definition)["proposal"]}
        if imported.execution_profile is None
        else {
            family.proposal
            for family in execution_families(
                imported.definition, imported.execution_profile
            ).families
        }
    )
    check_candidate_roles(imported, proposals)


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_shapes_carry_no_scientific_values(template_id):
    """Fails if a template ships advice, output-type restrictions or training values,
    which would become an implicit scientific default for every task. The one declared
    pair is the launch policy (record-only, diagnostic): without it every template run
    fails at training admission (L-1), and it claims no scientific standing."""
    shape = template_document(template_id)
    options = shape.preparation_options
    assert (options.proposal_advice, options.implementation_advice, options.validation_advice) == (
        None,
        None,
        None,
    )
    assert options.allowed_output_types is None
    assert shape.training_settings == {
        "launch": {"healthgate_mode": "observe_only", "result_authority": "diagnostic"}
    }
    assert shape.task_binding is None


def test_v1_source_supplies_references_and_unparsed_source_is_refused():
    """Fails if a v1 project's manifest/data root are replaced by template placeholders,
    or if an unreadable source silently falls back to placeholder references."""
    from tests.unit.workflows.test_workflow_definition import definition
    from workflows.definition import WorkflowDocument

    v1 = WorkflowDocument(definition=definition())
    imported = parse_workflow_source(instantiate("single-step", v1))
    assert (imported.definition.task.manifest, imported.definition.task.data_root) == (
        v1.definition.task.manifest,
        v1.definition.task.data_root,
    )
    with pytest.raises(TemplateRefusal):
        instantiate("single-step", None)


def test_advice_targets_render_into_their_owning_fields():
    """Fails if an advice target names a field Review would refuse (e.g. a launch field
    the training admission rejects) or one that does not survive the source renderer."""
    document = template_document("single-loop-with-advice")
    raw = document.model_dump(mode="json")
    for target in advice_targets().targets:
        holder = (
            raw["preparation_options"]
            if target.location == "preparation_options"
            else raw["training_settings"].setdefault("launch", {})
        )
        holder[target.field] = f"advice for {target.capability}"
    rendered = parse_workflow_source(
        render_workflow_source(ReusableWorkflowDocument.model_validate_json(json.dumps(raw)))
    )
    assert isinstance(rendered, ReusableWorkflowDocument)
    assert rendered.preparation_options.proposal_advice == "advice for proposal"
    assert rendered.training_settings == {
        "launch": {
            "healthgate_mode": "observe_only",
            "result_authority": "diagnostic",
            "human_advice_tune": "advice for tuning",
        }
    }


@pytest.fixture
def template_config(console_config, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "workflow.py"
    source.write_text(EXAMPLE.read_text())
    recovery = root / "recovery"
    recovery.mkdir(mode=0o700)
    project = Project(
        project_id="example", project_root=root, source_file=source, recovery_directory=recovery
    )
    return console_config.model_copy(update={"editor_projects": (project,)})


def test_http_import_is_write_free_and_reviews_through_source_path(template_config):
    """Fails if import writes the source, ignores a stale base, or returns source the
    ordinary Review/Save path refuses."""
    path = template_config.editor_projects[0].source_file
    original = path.read_text()
    headers = {
        "Authorization": "Bearer " + open(template_config.auth_token_file).read(),
        "Origin": template_config.browser_origin,
    }
    app = create_app(template_config)
    with TestClient(app, base_url=template_config.browser_origin) as client:
        assert client.get("/api/editor/templates").status_code == 401
        catalog = client.get("/api/editor/templates", headers=headers).json()
        assert [item["id"] for item in catalog["templates"]] == TEMPLATE_IDS
        assert client.get("/api/editor/advice-targets", headers=headers).status_code == 200
        base = client.get("/api/editor/example", headers=headers).json()
        stale = client.post(
            "/api/editor/example/template",
            headers=headers,
            json={"template_id": "single-research-loop", "expected_sha256": "0" * 64},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "conflict"
        imported = client.post(
            "/api/editor/example/template",
            headers=headers,
            json={"template_id": "single-research-loop", "expected_sha256": base["sha256"]},
        )
        assert imported.status_code == 200, imported.text
        assert path.read_text() == original
        review = client.post(
            "/api/editor/example/review",
            headers=headers,
            json={
                "expected_sha256": base["sha256"],
                "proposal": {"kind": "source", "source": imported.json()["source"]},
            },
        )
        assert review.status_code == 200, review.text
        view = review.json()
        assert view["document"]["definition"]["loop"]["final_iteration"] == 1
        saved = client.post(
            "/api/editor/example/save",
            headers=headers,
            json={
                "expected_sha256": base["sha256"],
                "proposal_sha256": view["sha256"],
                "source": view["source"],
            },
        )
        assert saved.status_code == 200, saved.text
        assert path.read_text() == view["source"]


def test_unparsed_project_source_refuses_import(template_config):
    """Fails if a source the editor cannot parse still yields placeholder task references."""
    path = template_config.editor_projects[0].source_file
    path.write_text(SOURCE.replace("document =", "document = 1 +", 1))
    headers = {
        "Authorization": "Bearer " + open(template_config.auth_token_file).read(),
        "Origin": template_config.browser_origin,
    }
    with TestClient(create_app(template_config), base_url=template_config.browser_origin) as client:
        base = client.get("/api/editor/example", headers=headers).json()
        assert base["document"] is None
        refused = client.post(
            "/api/editor/example/template",
            headers=headers,
            json={"template_id": "single-step", "expected_sha256": base["sha256"]},
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "unsupported"


def test_training_inspector_projects_required_policy_choices():
    """L-1b: the Train & tune inspector shows both launch-policy choices with their
    authored value, and an undeclared one as unset (the author's problem to resolve);
    fails if a choice disappears or an option drifts from the native Literal values."""
    from tools.workflow_authoring.training import training_inspector

    shape = template_document("single-research-loop")
    policy = {item.name: item for item in training_inspector(shape).policy}
    assert {name: item.value for name, item in policy.items()} == {
        "healthgate_mode": "observe_only",
        "result_authority": "diagnostic",
    }
    assert [o.value for o in policy["healthgate_mode"].options] == ["observe_only", "blocking"]
    assert all(item.required for item in policy.values())
    unset = shape.model_copy(update={"training_settings": {}})
    assert [item.value for item in training_inspector(unset).policy] == [None, None]
