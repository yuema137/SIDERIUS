"""Independent mapping/identity witnesses for inert reusable candidate resolution."""

import json
from pathlib import Path

import pytest

from tests.unit.workflows.reusable_fixture import EXAMPLE, reusable
from tools.candidate_prepare.resolution import (
    ResolvedExternalLocation,
    ReusableCandidateLocations,
    resolve_reusable_candidate,
)
from tools.workflow_authoring.models import DocumentProposal, Project, ReviewRequest, SaveRequest
from tools.workflow_authoring.service import WorkflowAuthoring
from tools.workflow_preview.models import WorkflowPreviewRequest
from workflows.definition import (
    CandidatePreparationOptions,
    ReusableWorkflowDocument,
    WorkflowDocument,
    WorkflowSourceError,
    inspect_declaration,
    parse_workflow_source,
    render_workflow_source,
)


def locations(root):
    return ReusableCandidateLocations(
        manifest=f"{root}/task.yaml",
        data_root=f"{root}/data",
        workspace=f"{root}/workspace",
        externals=tuple(
            ResolvedExternalLocation(binding=name, location=f"{root}/{file}")
            for name, file in (
                ("initial", "seed.json"),
                ("build_store", "attempt-storage.json"),
                ("check_store", "attempt-storage.json"),
                ("context", "constraints.json"),
            )
        ),
    )


def test_two_resolutions_preserve_authored_graph_and_options_without_io(monkeypatch):
    """Renaming, ordering and explicit targets fail if a legacy fixed graph is regenerated."""
    document = reusable()
    original = document.model_dump_json()
    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", lambda *args: pytest.fail("resolver traversed filesystem"))
        patch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("resolver read a payload"))
        for root in ("/first", "/second"):
            result = resolve_reusable_candidate(document, locations(root))
            effective = result.document
            assert effective.definition.task.workspace == root + "/workspace"
            assert effective.definition.task.manifest == root + "/task.yaml"
            assert effective.definition.task.data_root == root + "/data"
            assert [(item.id, item.location) for item in effective.definition.externals] == [
                ("initial", root + "/seed.json"),
                ("build_store", root + "/attempt-storage.json"),
                ("check_store", root + "/attempt-storage.json"),
                ("context", root + "/constraints.json"),
            ]
            assert [node.id for node in effective.definition.nodes] == [
                "hypothesis",
                "build",
                "check",
            ]
            assert effective.definition.nodes == document.definition.nodes
            assert effective.positions == document.positions
            assert result.preparation_options == CandidatePreparationOptions(
                proposal_advice="Prefer a small interpretable baseline",
                implementation_advice="Keep diagnostics explicit",
                validation_advice="Inspect held-out residuals",
                allowed_output_types=("regressor",),
            )
    assert document.model_dump_json() == original


def test_canonical_authoring_preserves_v2_options_aliases_and_layout(tmp_path):
    """Fails if authoring JSON coercion, rendering or saving loses the reusable variant."""
    source = tmp_path / "workflow.py"
    source.write_text(EXAMPLE.read_text())
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    author = WorkflowAuthoring(
        Project(
            project_id="reusable",
            project_root=tmp_path,
            source_file=source,
            recovery_directory=recovery,
        )
    )
    base = author.read()
    reviewed = author.review(
        ReviewRequest(
            expected_sha256=base.sha256,
            proposal=DocumentProposal(kind="document", document=reusable()),
        )
    )
    author.save(
        SaveRequest(
            expected_sha256=base.sha256, proposal_sha256=reviewed.sha256, source=reviewed.source
        )
    )
    actual = parse_workflow_source(source.read_text())
    assert actual == reusable()
    assert actual.definition.externals[2].id == "check_store"
    assert actual.positions[0].x == 120.0
    assert isinstance(actual, ReusableWorkflowDocument)
    assert actual.preparation_options.allowed_output_types == ("regressor",)
    assert inspect_declaration(actual).execution_ready is False
    assert (
        inspect_declaration(
            resolve_reusable_candidate(actual, locations("/run")).document
        ).execution_ready
        is False
    )
    with pytest.raises(ValueError):
        WorkflowPreviewRequest.model_validate_json(
            json.dumps({"document": actual.model_dump(mode="json"), "project_root": "/explicit"})
        )


def test_options_change_semantics_layout_does_not_and_unchecked_updates_revalidate():
    """Fails if semantic identity drops advice, includes positions, or trusts copied models."""
    document = reusable()
    payload = document.model_dump(mode="json")
    payload["positions"][0]["x"] = 900
    moved = ReusableWorkflowDocument.model_validate_json(json.dumps(payload))
    assert document.declaration_digest() == moved.declaration_digest()
    for field, value in (
        ("proposal_advice", "changed"),
        ("implementation_advice", "changed"),
        ("validation_advice", "changed"),
        ("allowed_output_types", ["classifier"]),
    ):
        changed = document.model_dump(mode="json")
        changed["preparation_options"][field] = value
        assert (
            document.declaration_digest()
            != ReusableWorkflowDocument.model_validate_json(
                json.dumps(changed)
            ).declaration_digest()
        )
    broken = document.model_copy(update={"preparation_options": {"allowed_output_types": []}})
    with pytest.raises(WorkflowSourceError):
        render_workflow_source(broken)
    with pytest.raises(ValueError):
        resolve_reusable_candidate(broken, locations("/run"))


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda p: p["externals"].pop(), "match declared"),
        (
            lambda p: p["externals"].append({"binding": "surplus", "location": "/extra"}),
            "match declared",
        ),
        (lambda p: p["externals"][2].update(location="/different-storage"), "share one"),
    ],
)
def test_mapping_admission(mutation, match):
    """Fails if explicit maps are silently completed, ignored or split across storage roots."""
    payload = locations("/run").model_dump(mode="json")
    mutation(payload)
    with pytest.raises(ValueError, match=match):
        resolve_reusable_candidate(
            reusable(), ReusableCandidateLocations.model_validate_json(json.dumps(payload))
        )


def test_declared_but_unsupported_roles_and_wrong_upstream_fail_before_resolution():
    """Structurally valid graphs still need candidate-shape and managed-role admission."""
    payload = reusable().model_dump(mode="json")
    # A second implementation is structurally valid but outside the candidate subset.
    payload["definition"]["nodes"].append(dict(payload["definition"]["nodes"][1], id="extra_build"))
    with pytest.raises(ValueError, match="exactly one"):
        resolve_reusable_candidate(
            ReusableWorkflowDocument.model_validate_json(json.dumps(payload)), locations("/run")
        )
    payload = reusable().model_dump(mode="json")
    payload["definition"]["externals"].append(
        {"id": "unused", "kind": "managed_candidate", "contract": "storage"}
    )
    with pytest.raises(ValueError, match="Unused"):
        resolve_reusable_candidate(
            ReusableWorkflowDocument.model_validate_json(json.dumps(payload)), locations("/run")
        )
    payload = reusable().model_dump(mode="json")
    payload["definition"]["externals"][0] = {
        "id": "initial",
        "contract": "proposal.input",
        "location": "seed.json",
    }
    with pytest.raises(ValueError, match="managed proposal"):
        resolve_reusable_candidate(
            ReusableWorkflowDocument.model_validate_json(json.dumps(payload)), locations("/run")
        )
    payload = reusable().model_dump(mode="json")
    payload["definition"]["externals"][1] = {
        "id": "build_store",
        "contract": "storage",
        "location": "storage.json",
    }
    with pytest.raises(ValueError, match="Literal proposal/storage"):
        resolve_reusable_candidate(
            ReusableWorkflowDocument.model_validate_json(json.dumps(payload)), locations("/run")
        )


def test_wrong_upstream_and_misrouted_managed_copy_cannot_bypass_resolution_validation():
    """Copied Python models must not bypass the boundary's graph/role admission."""
    from workflows.definition import ArgumentBinding, ExternalSource, ProtocolRequest, ResultSource

    document = reusable()
    build = document.definition.nodes[1]
    wrong_edge = build.model_copy(
        update={
            "request": ProtocolRequest(
                protocol="proposal-to-implementation",
                arguments=(
                    ArgumentBinding(name="output", source=ResultSource(node="check")),
                    ArgumentBinding(name="storage", source=ExternalSource(binding="build_store")),
                ),
            )
        }
    )
    misrouted = document.definition.nodes[0].model_copy(
        update={"request": {"kind": "external", "binding": "build_store"}}
    )
    for nodes in (
        (document.definition.nodes[0], wrong_edge, document.definition.nodes[2]),
        (misrouted, *document.definition.nodes[1:]),
    ):
        copied = document.model_copy(
            update={"definition": document.definition.model_copy(update={"nodes": nodes})}
        )
        with pytest.raises(ValueError):
            resolve_reusable_candidate(copied, locations("/run"))


def test_new_source_root_keeps_execution_syntax_inert_and_diagnostics_sanitized():
    """The second constructor root must not open an execution or diagnostic leakage route."""
    source = EXAMPLE.read_text()
    for changed in (
        source + "\nraise RuntimeError('must not execute')\n",
        source.replace('manifest="task.yaml"', 'manifest=__import__("os").getcwd()'),
    ):
        with pytest.raises(WorkflowSourceError) as error:
            parse_workflow_source(changed)
        assert error.value.diagnostics[0].code == "unsupported"
    with pytest.raises(WorkflowSourceError) as error:
        parse_workflow_source(
            source.replace(
                'id="initial", contract="proposal.input"',
                'id="SECRET/value", contract="proposal.input"',
            )
        )
    assert "SECRET" not in str(error.value)
