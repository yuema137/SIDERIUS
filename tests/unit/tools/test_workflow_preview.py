"""Preview semantics: path ownership, captured bytes and selected native routes."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.layout import checkout_root
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
from workflows.definition import (
    ArgumentBinding,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
)


@pytest.fixture
def request_at(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "data").mkdir()
    for name in ("task.yaml", "proposal.json", "storage.json"):
        (project / name).write_bytes(b"opaque selected bytes\n")
    nodes = [
        NodeInstance(
            id="candidate", capability="proposal", request=ExternalRequest(binding="request")
        )
    ]
    for name, capability, upstream, protocol in (
        ("coder", "implementation", "candidate", "proposal-to-implementation"),
        ("checker", "validation", "coder", "implementation-to-validation"),
    ):
        nodes.append(
            NodeInstance(
                id=name,
                capability=capability,
                request=ProtocolRequest(
                    protocol=protocol,
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node=upstream)),
                        ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ),
                ),
            )
        )
    return WorkflowPreviewRequest(
        project_root=str(project),
        document=WorkflowDocument(
            definition=WorkflowDefinition(
                task=TaskReferences(manifest="task.yaml", data_root="data", workspace="workspace"),
                externals=(
                    ExternalBinding(
                        id="request", contract="proposal.input", location="proposal.json"
                    ),
                    ExternalBinding(id="storage", contract="storage", location="storage.json"),
                ),
                nodes=tuple(nodes),
            )
        ),
    )


def with_task(request, **updates):
    task = request.document.definition.task.model_copy(update=updates)
    definition = request.document.definition.model_copy(update={"task": task})
    return request.model_copy(
        update={"document": request.document.model_copy(update={"definition": definition})}
    )


def configured(request, payload):
    path = Path(request.project_root) / "llm.json"
    path.write_text(json.dumps(payload))
    return request.model_copy(update={"llm_config_file": "llm.json"})


def test_python_json_layout_and_cwd_select_identical_facts(request_at, monkeypatch, tmp_path):
    """Fails if CWD/layout influences resolution or JSON bypasses the common boundary."""
    expected = preview_workflow(request_at)
    moved = request_at.model_copy(
        update={
            "document": request_at.document.model_copy(
                update={"positions": (NodePosition(node="coder", x=999.0, y=-10.0),)}
            )
        }
    )
    monkeypatch.chdir(tmp_path)
    actual = preview_workflow(WorkflowPreviewRequest.model_validate_json(moved.model_dump_json()))
    assert actual == expected
    assert actual.workspace == str(Path(request_at.project_root) / "workspace")
    assert actual.workspace_state == "absent"
    assert actual.execution_ready is False
    assert [file.reference for file in actual.files] == [
        "task.manifest",
        "external.request",
        "external.storage",
    ]
    assert [route.name for route in actual.selected_constructor_routes] == [
        "candidate.comparison",
        "candidate.reasoning",
        "candidate.proposing",
        "coder.main",
        "checker.main",
    ]
    assert actual.selected_constructor_routes[0].shares_client_with == "candidate.reasoning"
    assert actual.selected_constructor_routes[2].shares_client_with == "candidate.reasoning"
    assert actual.selected_constructor_routes[3].shares_client_with is None
    assert "payload validation" in actual.pending_checks[0]


def test_captured_bytes_change_without_claiming_run_identity(request_at):
    """Fails if config is reopened or an observation digest ignores changed bytes."""
    request = configured(request_at, {})
    before = preview_workflow(request)
    path = Path(request.project_root) / "llm.json"
    content = b'{"implement":{"model_id":"selected"}}\n'
    path.write_bytes(content)
    after = preview_workflow(request)
    assert after.files[-1].sha256 == hashlib.sha256(content).hexdigest()
    assert after.files[-1].size_bytes == len(content)
    assert before.files[-1].sha256 != after.files[-1].sha256
    assert after.selected_constructor_routes[3].transport.model_id == "selected"
    assert (
        request.document.definition.declaration_digest()
        == request_at.document.definition.declaration_digest()
    )
    assert before.execution_ready is after.execution_ready is False


def test_symlinks_are_canonical_and_empty_workspace_is_allowed(request_at):
    project = Path(request_at.project_root)
    (project / "alias.yaml").symlink_to(project / "task.yaml")
    (project / "workspace").mkdir()
    result = preview_workflow(with_task(request_at, manifest="alias.yaml"))
    assert result.files[0].path == str(project / "task.yaml")
    assert result.workspace_state == "empty"


@pytest.mark.parametrize(
    "case",
    [
        "same_data",
        "below_data",
        "above_data",
        "source",
        "input",
        "config",
        "nonempty",
        "file",
        "file_parent",
        "symlink_data",
    ],
)
def test_workspace_refusals_name_violated_binding(request_at, case):
    """Each case fails if its containment direction or symlink normalization is removed."""
    project = Path(request_at.project_root)
    request = request_at
    if case == "same_data":
        workspace, match = "data", "data_root"
    elif case == "below_data":
        workspace, match = "data/new", "data_root"
    elif case == "above_data":
        workspace, match = ".", "data_root"
    elif case == "source":
        root = checkout_root()
        assert root is not None
        workspace, match = str(root / "unused-preview-workspace"), "framework source"
    elif case in {"input", "config"}:
        (project / "chosen").mkdir()
        if case == "input":
            (project / "chosen/task.yaml").write_text("opaque")
            request = with_task(request, manifest="chosen/task.yaml")
        else:
            (project / "chosen/llm.json").write_text("{}")
            request = request.model_copy(update={"llm_config_file": "chosen/llm.json"})
        workspace, match = "chosen", "selected input"
    elif case == "nonempty":
        (project / "workspace").mkdir()
        (project / "workspace/old").write_text("preserved")
        workspace, match = "workspace", "empty directory"
    elif case == "file":
        workspace, match = "storage.json", "selected input"
    elif case == "file_parent":
        workspace, match = "storage.json/child", "ancestor is not a directory"
    else:
        (project / "alias").symlink_to(project / "data", target_is_directory=True)
        workspace, match = "alias/new", "data_root"
    with pytest.raises(ValueError, match=match):
        preview_workflow(with_task(request, workspace=workspace))


@pytest.mark.parametrize(
    "case",
    [
        "manifest_missing",
        "manifest_directory",
        "external_missing",
        "fifo",
        "data_missing",
        "project_missing",
        "unreadable",
    ],
)
def test_bad_selected_locations_fail_closed(request_at, case, monkeypatch):
    """No omitted file, fallback configuration, or special-file read may produce a report."""
    project = Path(request_at.project_root)
    request = request_at
    if case == "manifest_missing":
        request = with_task(request, manifest="missing.yaml")
        match = "task.manifest"
    elif case == "manifest_directory":
        request = with_task(request, manifest="data")
        match = "task.manifest"
    elif case == "external_missing":
        (project / "proposal.json").unlink()
        match = "external.request"
    elif case == "fifo":
        os.mkfifo(project / "pipe")
        request = with_task(request, manifest="pipe")
        match = "regular readable file"
    elif case == "data_missing":
        request = with_task(request, data_root="missing")
        match = "task.data_root"
    elif case == "project_missing":
        request = request.model_copy(update={"project_root": str(project / "absent")})
        match = "project_root"
    else:
        original = os.open

        def refuse(path, flags, *args, **kwargs):
            if Path(path) == project / "task.yaml":
                raise PermissionError("denied")
            return original(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", refuse)
        match = "task.manifest.*denied"
    with pytest.raises(ValueError, match=match):
        preview_workflow(request)


def test_installed_source_guard_protects_only_actual_packages(request_at, monkeypatch, tmp_path):
    """An installed distribution must neither admit its own packages nor ban all site-packages."""
    from tools.workflow_preview import files

    installed = tmp_path / "site-packages"
    installed.mkdir()
    monkeypatch.setattr(files, "checkout_root", lambda: None)
    monkeypatch.setattr(files, "package_root", lambda: installed)
    with pytest.raises(ValueError, match="framework source"):
        preview_workflow(with_task(request_at, workspace=str(installed / "tools/new")))
    assert (
        preview_workflow(
            with_task(request_at, workspace=str(installed / "unrelated"))
        ).workspace_state
        == "absent"
    )


def test_unsupported_valid_graph_and_unchecked_copies_are_distinct(request_at):
    """Removing subset checks admits disconnected graphs; removing revalidation admits dangling wires."""
    definition = request_at.document.definition
    standalone = WorkflowDocument(
        definition=definition.model_copy(update={"nodes": definition.nodes[:1]})
    )
    with pytest.raises(ValueError, match="Unsupported preview"):
        preview_workflow(request_at.model_copy(update={"document": standalone}))
    broken = request_at.document.model_copy(
        update={"positions": (NodePosition(node="absent", x=0.0, y=0.0),)}
    )
    with pytest.raises(ValidationError, match="layout node"):
        preview_workflow(request_at.model_copy(update={"document": broken}))
    payload = request_at.model_dump(mode="json")
    payload["document"]["definition"]["externals"].append(
        {"id": "direct", "contract": "implementation.input", "location": "direct.json"}
    )
    payload["document"]["definition"]["nodes"][1]["request"] = {
        "kind": "external",
        "binding": "direct",
    }
    disconnected = WorkflowPreviewRequest.model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError, match="coder requires proposal-to-implementation"):
        preview_workflow(disconnected)


@pytest.mark.parametrize(
    "payload,match",
    [
        ({"implemnt": {}}, "llm_config.*implemnt"),
        ({"implement": {"model": "typo"}}, "llm_config.implement.*model"),
        ({"propose": {"reasonng": {}}}, "llm_config.propose.*reasonng"),
        ({"propose": {"comparison": {"max_retry": 2}}}, "llm_config.propose.comparison.*max_retry"),
        ({"validate": {}, "validate_model": {}}, "duplicate name/alias"),
    ],
)
def test_active_typos_and_duplicate_alias_refused(request_at, payload, match):
    """The native models ignore extras; only the preview's bounded key check catches these."""
    with pytest.raises(ValueError, match=match):
        preview_workflow(configured(request_at, payload))


def test_selected_roles_only_preserve_partial_and_stage_retry_semantics(request_at, monkeypatch):
    """Unselected role projection must never run; absent config differs from an explicit partial file."""
    from tools.setup_review import routes

    def forbidden(*args, **kwargs):
        raise AssertionError("unselected role projection")

    monkeypatch.setattr(routes, "_tuner_routes", forbidden)
    monkeypatch.setattr(routes, "_literature_routes", forbidden)
    default = preview_workflow(request_at)
    partial = preview_workflow(
        configured(request_at, {"tune": {}, "interpret": {"model_id": "unused"}})
    )
    assert default.selected_constructor_routes[3].transport.max_retries == 1
    assert partial.selected_constructor_routes[3].transport.max_retries is None
    assert partial.inactive_roles == ("interpret", "data_analysis", "tune", "lit_review")
    assert all(
        route.transport.model_id != "unused" for route in partial.selected_constructor_routes
    )
    asymmetric = preview_workflow(
        configured(
            request_at,
            {
                "propose": {
                    "comparison": {"provider": "deepseek", "model_id": "compare", "max_retries": 0},
                    "reasoning": {"provider": "openai", "model_id": "reason", "max_retries": 7},
                    "proposing": {"provider": "gemini", "model_id": "emit", "max_retries": None},
                },
                "validate_model": {"model_id": "validated"},
            },
        )
    )
    first = asymmetric.selected_constructor_routes[:3]
    assert [
        (r.transport.provider, r.transport.model_id, r.transport.max_retries) for r in first
    ] == [("deepseek", "compare", 0), ("openai", "reason", 7), ("gemini", "emit", None)]
    assert all(r.shares_client_with is None for r in first)
    assert asymmetric.selected_constructor_routes[-1].transport.model_id == "validated"


def test_captured_config_not_reopened(request_at, monkeypatch):
    """A mutation between capture and parse cannot make routes disagree with their observed digest."""
    from tools.workflow_preview import preview

    request = configured(request_at, {"implement": {"model_id": "captured"}})
    original = preview.observe_file

    def replace_after_capture(path, reference):
        observation, content = original(path, reference)
        if reference == "llm_config":
            path.write_text('{"implement":{"model_id":"later"}}')
        return observation, content

    monkeypatch.setattr(preview, "observe_file", replace_after_capture)
    result = preview_workflow(request)
    assert result.selected_constructor_routes[3].transport.model_id == "captured"
    assert (
        result.files[-1].sha256
        != hashlib.sha256((Path(request.project_root) / "llm.json").read_bytes()).hexdigest()
    )


def test_preview_has_no_execution_credentials_network_or_write_effects(request_at):
    """A fresh interpreter forbids effects/imports; opaque plugin-looking bytes must never execute."""
    project = Path(request_at.project_root)
    (project / "task.yaml").write_text("!!python/object/apply:os.system ['touch SHOULD_NOT_EXIST']")
    script = r"""
import os, sys
sys.dont_write_bytecode = True
def audit(event, args):
    if event == "open":
        mode, flags = args[1:]
        if (mode and any(c in mode for c in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError((event, args))
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event in {"os.system", "os.mkdir", "os.remove", "os.rename"}:
        raise AssertionError((event, args))
    if event == "import" and args[0].startswith(("agent.llm_bridge", "workflows.task_composition", "nodes.ml_", "openai")):
        raise AssertionError((event, args[0]))
sys.addaudithook(audit)
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
request = WorkflowPreviewRequest.model_validate_json(sys.stdin.read())
class NoEnvironment(dict):
    def get(self, key, default=None):
        if key == "PYDANTIC_DISABLE_PLUGINS":
            return None  # Pydantic reads its own plugin switch while building TypeAdapter.
        raise AssertionError(f"unexpected environment read: {key}")
    def __getitem__(self, key):
        raise AssertionError("environment read")
os.environ = NoEnvironment()
result = preview_workflow(request)
assert result.execution_ready is False
assert len(result.selected_constructor_routes) == 5
print("observation only")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        input=request_at.model_dump_json(),
        text=True,
        capture_output=True,
        cwd=project,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "observation only"
    assert not (project / "workspace").exists()


def test_uri_is_not_accidentally_resolved_as_local_filename(request_at):
    """Even an existing URI-shaped local filename must not turn a remote declaration into local input."""
    project = Path(request_at.project_root)
    fake = project / "https:/example.test/task.yaml"
    fake.parent.mkdir(parents=True)
    fake.write_text("opaque")
    with pytest.raises(ValueError, match=r"task.manifest.*local path, not a URI"):
        preview_workflow(with_task(request_at, manifest="https://example.test/task.yaml"))
