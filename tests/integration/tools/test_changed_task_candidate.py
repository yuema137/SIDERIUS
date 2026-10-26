"""Real native checks, publication and fresh preparation for two separate task versions."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from tests.integration.tools.test_setup_composition_check import _external_hook_request
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_prepare import prepare_reusable_candidate
from tools.setup_review.composition_check import check_task
from tools.workflow_authoring.models import Project, ReviewRequest, SaveRequest
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from tools.workflow_authoring.task_models import (
    TaskReferenceAcceptance,
    TaskReferenceAcknowledgement,
    TaskReferenceTarget,
    TaskReferenceUpdateProposal,
)
from workflows.definition import TaskBinding, parse_workflow_source, render_workflow_source

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit authorization for real bubblewrap namespaces",
)


@pytest.fixture
def changed_candidate(tmp_path, monkeypatch, request):
    targets = []
    for version in ("old", "new"):
        root = tmp_path / version
        root.mkdir()
        setup = _external_hook_request(root, monkeypatch, f"# independently checked {version}")
        if version == "new":
            metric = root / "task/declared/metric_accuracy.json"
            declaration = json.loads(metric.read_text())
            declaration["direction"] = "lower"
            metric.write_text(json.dumps(declaration))
            if getattr(request, "param", None) == "different_io":
                contract = root / "task/declared/task_config.yaml"
                contract.write_text(contract.read_text().replace("fixed: 4", "fixed: 5"))
            if getattr(request, "param", None) == "continuous":
                contract = root / "task/declared/task_config.yaml"
                contract.write_text(
                    contract.read_text().replace(
                        "        - {role: class, dimension: {fixed: 2}}\n", ""
                    )
                )
        report = check_task(setup)
        assert report.result.outcome == "passed", report.result.failure
        facts = report.result.task
        assert facts is not None
        observations = root / "observations"
        observations.mkdir()
        targets.append(
            TaskReferenceTarget(
                choice_id=version,
                binding=TaskBinding(
                    package_id="external",
                    revision=version,
                    task_data_path_id=facts.task_data_path_id,
                    semantic_fingerprint=facts.semantic_fingerprint,
                ),
                manifest=Path(report.job.manifest),
                data_root=tmp_path / "data",
                llm_config_file=root / "agents.json",
                inspection_root=observations,
                read_only=setup.read_only,
                settings=setup.settings,
            )
        )
    selected = selection.__wrapped__(tmp_path).model_copy(
        update={
            "task_manifest": str(targets[0].manifest),
            "llm_config_file": str(targets[1].llm_config_file),
            "task_read_only": (str(tmp_path / "old/task"), str(tmp_path / "new/task")),
        }
    )
    preparation = reusable.__wrapped__(selected)
    source = Path(preparation.source_path)
    document = parse_workflow_source(source.read_text()).model_copy(
        update={"task_binding": targets[0].binding}
    )
    source.write_text(render_workflow_source(document))
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    author = WorkflowAuthoring(
        Project(
            project_id="changed",
            project_root=tmp_path,
            source_file=source,
            recovery_directory=recovery,
        ),
        tuple(targets),
    )
    return author, targets, preparation


def reviewed_request(author, target):
    selection = TaskReferenceUpdateProposal(
        selected_choice_id=target.choice_id, expected_task_binding=target.binding
    )
    reviewed = author.review(
        ReviewRequest(expected_sha256=author.read().sha256, proposal=selection)
    )
    task = reviewed.task_reference_update
    assert task is not None
    acceptance = TaskReferenceAcceptance(
        selection=selection,
        acknowledged_findings=tuple(
            TaskReferenceAcknowledgement(code=item.code, reference=item.reference)
            for item in task.findings
        ),
    )
    request = SaveRequest(
        source=reviewed.source,
        expected_sha256=author.read().sha256,
        proposal_sha256=reviewed.sha256,
        task_reference_acceptance=acceptance,
    )
    return reviewed, request


def test_changed_reference_saves_and_prepares_fresh_target(changed_candidate):
    author, targets, preparation = changed_candidate
    original = author.read()
    old_document = parse_workflow_source(original.source)
    old_preparation = prepare_reusable_candidate(
        preparation.model_copy(
            update={
                "expected_source_sha256": hashlib.sha256(
                    Path(preparation.source_path).read_bytes()
                ).hexdigest()
            }
        )
    )
    assert old_preparation.status == "prepared", old_preparation.error
    old_envelope = Path(old_preparation.envelope)
    old_files = {
        str(path.relative_to(old_envelope)): path.read_bytes()
        for path in old_envelope.rglob("*")
        if path.is_file()
    }
    reviewed, request = reviewed_request(author, targets[1])
    task = reviewed.task_reference_update
    assert task.save_supported, task.findings
    assert task.current_observation.result.candidate_check is not None
    assert task.observation.result.candidate_check is not None
    assert any(
        item.reference == "task.primary_metric" and item.state == "requires_review"
        for item in task.findings
    )
    assert not task.execution_ready
    author.save(request)
    document = parse_workflow_source(author.read().source)
    assert document.definition.nodes == old_document.definition.nodes
    assert document.positions == old_document.positions
    assert document.preparation_options == old_document.preparation_options
    assert document.task_binding == targets[1].binding
    result = prepare_reusable_candidate(
        preparation.model_copy(
            update={
                "run_id": uuid4(),
                "expected_source_sha256": hashlib.sha256(
                    Path(preparation.source_path).read_bytes()
                ).hexdigest(),
            }
        )
    )
    assert result.status == "prepared", result.error
    captured = Path(result.envelope) / "workflow.py.snapshot"
    assert captured.read_text() == author.read().source
    proposal = json.loads((Path(result.envelope) / "inputs/proposal.json").read_bytes())
    assert (
        proposal["task_composition_ref"]["semantic_fingerprint"]
        == targets[1].binding.semantic_fingerprint
    )
    assert not (Path(result.envelope) / "workspace").exists()
    assert {
        str(path.relative_to(old_envelope)): path.read_bytes()
        for path in old_envelope.rglob("*")
        if path.is_file()
    } == old_files
    assert original.source.encode() in {
        path.read_bytes() for path in author.project.recovery_directory.iterdir()
    }


@pytest.mark.parametrize("version", ("old", "new"))
def test_source_or_target_drift_blocks_save_without_partial_source(changed_candidate, version):
    author, targets, _ = changed_candidate
    reviewed, request = reviewed_request(author, targets[1])
    assert reviewed.task_reference_update.save_supported
    original = author.read().source
    plugin = targets[0 if version == "old" else 1].manifest.parent / "plugins/_quickstart_task.py"
    plugin.write_text(plugin.read_text() + "\n# changed after review\n")
    with pytest.raises(AuthoringError, match="publication is blocked"):
        author.save(request)
    assert author.read().source == original


def test_missing_previous_choice_blocks_changed_reference(changed_candidate):
    author, targets, _ = changed_candidate
    author = WorkflowAuthoring(author.project, (targets[1],))
    reviewed, request = reviewed_request(author, targets[1])
    assert not reviewed.task_reference_update.save_supported
    original = author.read().source
    with pytest.raises(AuthoringError, match="publication is blocked"):
        author.save(request)
    assert author.read().source == original


@pytest.mark.parametrize("changed_candidate", ("different_io",), indirect=True)
def test_structural_input_change_blocks_review_and_save(changed_candidate):
    author, targets, _ = changed_candidate
    reviewed, request = reviewed_request(author, targets[1])
    assert not reviewed.task_reference_update.save_supported
    assert any(
        item.reference == "forward_contract.model_io" and item.state == "blocked"
        for item in reviewed.task_reference_update.findings
    )
    original = author.read().source
    with pytest.raises(AuthoringError, match="publication is blocked"):
        author.save(request)
    assert author.read().source == original


@pytest.mark.parametrize("changed_candidate", ("continuous",), indirect=True)
def test_declared_classifier_without_target_class_axis_blocks_native_candidate_check(
    changed_candidate,
):
    author, targets, _ = changed_candidate
    reviewed, _ = reviewed_request(author, targets[1])
    task = reviewed.task_reference_update
    assert not task.save_supported
    assert task.observation.result.failure.stage == "candidate_check"
    assert "class-alphabet axis" in task.observation.result.failure.message


def test_categorical_regressor_uses_native_declared_output_policy(changed_candidate):
    author, targets, _ = changed_candidate
    document = parse_workflow_source(author.read().source)
    document = document.model_copy(
        update={
            "preparation_options": document.preparation_options.model_copy(
                update={"allowed_output_types": ("regressor",)}
            )
        }
    )
    author.project.source_file.write_text(render_workflow_source(document))
    reviewed, _ = reviewed_request(author, targets[1])
    assert reviewed.task_reference_update.save_supported
