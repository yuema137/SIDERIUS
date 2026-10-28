"""Disk boundary witnesses: race refusal, recovery and inert source handling.

Each assertion names disk/state behavior not enforced by declaration schemas.
"""

import hashlib
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


def test_unchecked_configuration_uses_revalidated_paths(editor):
    """Unchecked model_copy strings must become validated Paths before admission."""
    unchecked = editor.project.model_copy(update={"source_file": str(editor.project.source_file)})
    assert WorkflowAuthoring(unchecked).read().source == SOURCE


def test_mode_failure_closes_temp_descriptor(editor, monkeypatch):
    """fchmod failure before fdopen must close the descriptor and leave source."""
    import core.durable_io as durable

    descriptor = []
    original = durable._open_temp_beside

    def tracked(path):
        fd, name = original(path)
        descriptor.append(fd)
        return fd, name

    def fail(*args):
        raise OSError("fchmod failed")

    monkeypatch.setattr(durable, "_open_temp_beside", tracked)
    monkeypatch.setattr(durable.os, "fchmod", fail)
    with pytest.raises(OSError, match="fchmod"):
        editor.save(request(editor, SOURCE.replace("old.json", "new.json")))
    with pytest.raises(OSError):
        os.fstat(descriptor[-1])
    assert editor.project.source_file.read_text() == SOURCE


def test_transport_escaped_exact_limit_and_rendered_output_limit(editor):
    """The editor bounds UTF-8, not JSON length; generated proposals are bounded too."""
    from tools.workflow_authoring.models import DocumentProposal
    from workflows.definition import WorkflowDocument

    exact = SOURCE + "#" + "\\" * (32768 - len(SOURCE.encode()) - 1)
    request_json = ReviewRequest(
        expected_sha256=editor.read().sha256, proposal=SourceProposal(kind="source", source=exact)
    ).model_dump_json()
    assert len(request_json.encode()) > 32768
    review = editor.review(ReviewRequest.model_validate_json(request_json))
    assert review.source == exact
    definition = editor.read().document.model_dump(mode="json")
    definition["definition"]["task"]["manifest"] = "x" * 32700
    document = WorkflowDocument.model_validate_json(__import__("json").dumps(definition))
    with pytest.raises(AuthoringError, match="rendered"):
        editor.review(
            ReviewRequest(
                expected_sha256=editor.read().sha256,
                proposal=DocumentProposal(kind="document", document=document),
            )
        )


def test_native_catalog_projection_and_semantic_edit_preserve_structure(editor):
    """Fails if GUI ports drift from the catalog or metadata projection alters source."""
    import json

    from tests.unit.workflows.test_workflow_definition import definition
    from tools.workflow_authoring.models import DocumentProposal
    from workflows.definition import (
        NodePosition,
        WorkflowDefinition,
        WorkflowDocument,
        render_workflow_source,
    )

    graph = definition().model_dump(mode="json")
    graph["nodes"][1]["request"]["arguments"].reverse()
    graph["externals"].append(
        {
            "id": "context",
            "contract": "optional.constraint-context",
            "location": "inputs/context.json",
        }
    )
    document = WorkflowDocument(
        definition=WorkflowDefinition.model_validate_json(json.dumps(graph)),
        positions=(NodePosition(node="propose", x=12.0, y=34.0),),
    )
    source = render_workflow_source(document)
    editor.project.source_file.write_text(source)
    view = editor.read()
    assert view.source == source
    options = {
        (item.node, item.argument): [choice.label for choice in item.choices]
        for item in view.binding_options
    }
    assert options[("propose", None)] == ["seed"]
    assert options[("implement", "output")] == ["propose.result"]
    assert options[("validate", "output")] == ["implement.result"]
    assert options[("implement", "storage")] == ["storage"]
    assert ("validate", "constraint_context") not in options
    legacy_json = view.model_dump(mode="json")["binding_options"]
    assert all(set(item) == {"node", "argument", "choices"} for item in legacy_json)
    assert all(
        set(choice) == {"label", "source"} for item in legacy_json for choice in item["choices"]
    )
    expected_legacy_order = []
    for node in document.definition.nodes:
        arguments = getattr(node.request, "arguments", None)
        if arguments is None:
            expected_legacy_order.append((node.id, None))
        else:
            expected_legacy_order.extend((node.id, argument.name) for argument in arguments)
    assert [(item.node, item.argument) for item in view.binding_options] == expected_legacy_order

    from tools.workflow_authoring.models import NativeContract
    from workflows.definition.catalog import CONTRACTS, PROTOCOLS
    from workflows.definition.contract_names import contract_name

    ports = {(item.node, item.argument): item for item in view.port_inventory}
    optional_context = ports[("validate", "constraint_context")]
    assert optional_context.required is False
    assert optional_context.bound is False
    assert optional_context.source is None
    assert optional_context.socket_contract == NativeContract(
        id="optional.constraint-context",
        native_type=CONTRACTS["optional.constraint-context"],
    )
    assert [choice.label for choice in optional_context.choices] == ["context"]
    assert optional_context.choices[0].contract == optional_context.socket_contract
    assert optional_context.protocol_mapping is not None
    assert optional_context.protocol_mapping.id == "implementation-to-validation"
    assert (
        optional_context.protocol_mapping.owner == PROTOCOLS["implementation-to-validation"].owner
    )
    assert optional_context.protocol_mapping.output_contract == NativeContract(
        id="validation.input", native_type=CONTRACTS["validation.input"]
    )
    assert optional_context.node_input_contract == optional_context.protocol_mapping.output_contract
    assert optional_context.node_output_contract == NativeContract(
        id="validation.output", native_type=CONTRACTS["validation.output"]
    )
    serialized = view.model_dump(mode="json")
    serialized_ports = {
        (item["node"], item["argument"]): item for item in serialized["port_inventory"]
    }
    serialized_optional = serialized_ports[("validate", "constraint_context")]
    assert serialized_optional["required"] is False
    assert serialized_optional["bound"] is False
    assert serialized_optional["source"] is None
    # Presentation travels with the id on every projected contract (additive fields).
    assert serialized_optional["socket_contract"] == {
        "id": "optional.constraint-context",
        "native_type": CONTRACTS["optional.constraint-context"],
        "name": "Run constraints",
        "description": contract_name("optional.constraint-context").description,
        "kind": "setting",
    }
    assert serialized_optional["protocol_mapping"]["id"] == "implementation-to-validation"
    reviewed_base = editor.review(
        ReviewRequest(
            expected_sha256=view.sha256,
            proposal=DocumentProposal(kind="document", document=document),
        )
    )
    assert reviewed_base.source == source
    assert reviewed_base.port_inventory == view.port_inventory
    review_json = reviewed_base.model_dump(mode="json")
    review_ports = {
        (item["node"], item["argument"]): item for item in review_json["port_inventory"]
    }
    assert review_ports[("validate", "constraint_context")]["source"] is None

    edited = document.model_dump(mode="json")
    edited["definition"]["externals"][1]["location"] = "edited-storage.json"
    reviewed = editor.review(
        ReviewRequest(
            expected_sha256=view.sha256,
            proposal=DocumentProposal(
                kind="document", document=WorkflowDocument.model_validate_json(json.dumps(edited))
            ),
        )
    )
    assert [(p.node, p.x, p.y) for p in reviewed.document.positions] == [("propose", 12.0, 34.0)]
    assert [a.name for a in reviewed.document.definition.nodes[1].request.arguments] == [
        "storage",
        "output",
    ]
    assert reviewed.document.definition.externals[1].location == "edited-storage.json"


def test_training_inspector_save_preserves_advanced_rules_and_presence(tmp_path):
    """Losing sparse read/review/save transport corrupts independent rule/null controls."""
    from tests.unit.workflows.test_reusable_training import training_document
    from tools.workflow_authoring.models import DocumentProposal
    from workflows.definition import parse_workflow_source, render_workflow_source

    supplied = {
        "launch": {
            "formal_time_budget_minutes": None,
            "workflow_parameter_rules": {
                "rules": {
                    "train_config.epochs": {"range": {"min": 1, "max": 3}},
                    "train_config.lr_schedule": {"exact": None},
                }
            },
        }
    }
    source = tmp_path / "workflow.py"
    source.write_text(render_workflow_source(training_document(supplied)))
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    author = WorkflowAuthoring(
        Project(
            project_id="training",
            project_root=tmp_path,
            source_file=source,
            recovery_directory=recovery,
        )
    )
    view = author.read()
    assert view.training.allowed_output_types == ("regressor",)
    controls = {c.name: c for c in view.training.controls}
    assert controls["formal_time_budget_minutes"].state == "null"
    assert controls["formal_time_budget_minutes"].nullable
    assert controls["sampling_seed"].state == "unset"
    assert view.document.training_settings == supplied
    document = view.document.model_copy(deep=True)
    document.training_settings["launch"]["sampling_seed"] = 31
    review = author.review(
        ReviewRequest(
            expected_sha256=view.sha256,
            proposal=DocumentProposal(kind="document", document=document),
        )
    )
    assert (
        review.training.workflow_parameter_rules == supplied["launch"]["workflow_parameter_rules"]
    )
    assert next(c for c in review.training.controls if c.name == "sampling_seed").effective == 31
    author.save(
        SaveRequest(
            expected_sha256=view.sha256, proposal_sha256=review.sha256, source=review.source
        )
    )
    saved = parse_workflow_source(source.read_text())
    assert saved.training_settings == {"launch": {**supplied["launch"], "sampling_seed": 31}}
    assert "train_base_seed" not in saved.training_settings["launch"]


def test_training_help_reads_nullable_schema_branches(monkeypatch):
    """Fails if help drops constraints that Pydantic emits inside a nullable
    ``anyOf`` branch, or reports a value the schema does not declare."""
    from tools.workflow_authoring import training

    schema = {
        "trial_portion": {
            "anyOf": [{"type": "number", "exclusiveMinimum": 0, "maximum": 1}, {"type": "null"}],
            "default": None,
            "description": "Share of rows used by trial rounds.",
        },
        "formal_portion": {"type": "number", "default": 0.1},
    }
    monkeypatch.setattr(training, "_launch_schema", lambda: schema)
    nullable = training.control_help("trial_portion")
    assert (nullable.exclusive_minimum, nullable.maximum) == (0, 1)
    assert nullable.description == "Share of rows used by trial rounds."
    plain = training.control_help("formal_portion")
    assert plain.schema_default == 0.1
    assert (plain.description, plain.unit, plain.minimum, plain.maximum) == (None,) * 4


def test_training_help_distinguishes_null_default_from_absent_default(monkeypatch):
    """Fails if a field without a schema default is reported as defaulting to null.

    Both cases leave ``schema_default`` as ``None``; only ``has_schema_default`` tells
    the editor whether to render "Schema default: null" or no default line at all.
    """
    from tools.workflow_authoring import training

    schema = {
        "declared_null": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None},
        "required_field": {"type": "integer"},
    }
    monkeypatch.setattr(training, "_launch_schema", lambda: schema)
    declared = training.control_help("declared_null")
    absent = training.control_help("required_field")
    assert (declared.has_schema_default, declared.schema_default) == (True, None)
    assert (absent.has_schema_default, absent.schema_default) == (False, None)


def test_training_help_default_is_the_launch_config_default():
    """Fails if inline help shows a default other than the native launch-config field's."""
    from dataclasses import fields

    from tools.workflow_authoring.training import CONTROLS, control_help
    from workflows.run_config import WorkflowLaunchConfig

    defaults = {item.name: item.default for item in fields(WorkflowLaunchConfig)}
    for name, _, _ in CONTROLS:
        assert control_help(name).schema_default == defaults[name], name


@pytest.mark.parametrize(
    "current_bound,proposed_bound", [(False, True), (True, False), (True, True)]
)
def test_bound_save_refuses_including_pin_removal(editor, current_bound, proposed_bound):
    """Direct Save cannot publish a bound document without explicit task acceptance."""
    from tests.unit.workflows.reusable_fixture import reusable
    from workflows.definition import TaskBinding, render_workflow_source

    plain = reusable()
    bound = plain.model_copy(
        update={
            "task_binding": TaskBinding(
                package_id="synthetic",
                revision="one",
                task_data_path_id="synthetic_path",
                semantic_fingerprint="a" * 64,
            )
        }
    )
    original = render_workflow_source(bound if current_bound else plain)
    editor.project.source_file.write_text(original)
    proposed = render_workflow_source(bound if proposed_bound else plain)
    with pytest.raises(
        AuthoringError, match="requires explicit task-reference findings acceptance"
    ):
        editor.save(
            SaveRequest(
                source=proposed,
                expected_sha256=editor.read().sha256,
                proposal_sha256=hashlib.sha256(proposed.encode()).hexdigest(),
            )
        )
    assert editor.project.source_file.read_text() == original
    assert not tuple(editor.project.recovery_directory.iterdir())


def test_review_reports_comments_the_checked_bytes_remove(editor):
    """Fails if a structured edit's re-render silently drops hand-written comments (red-team
    S-1), or if repeated comment texts are counted once (a set would hide the second loss)."""
    from tools.workflow_authoring.models import DocumentProposal

    commented = "# my note\n# repeated\n" + SOURCE + "# repeated\n"
    editor.project.source_file.write_text(commented)
    base = editor.read()
    assert base.document is not None
    rendered = editor.review(
        ReviewRequest(
            expected_sha256=base.sha256,
            proposal=DocumentProposal(kind="document", document=base.document),
        )
    )
    assert rendered.removed_comments == ("# my note", "# repeated", "# repeated")
    one_kept = "# repeated\n" + SOURCE.replace("old.json", "new.json")
    partial = editor.review(
        ReviewRequest(
            expected_sha256=base.sha256,
            proposal=SourceProposal(kind="source", source=one_kept),
        )
    )
    assert partial.removed_comments == ("# my note", "# repeated")
    kept = editor.review(
        ReviewRequest(
            expected_sha256=base.sha256,
            proposal=SourceProposal(kind="source", source=commented.replace("old", "new")),
        )
    )
    assert kept.removed_comments == ()


def test_save_refuses_a_read_only_source_without_writing(editor):
    """Fails if temp + rename replaces a file its owner made read-only (red-team E-3):
    the refusal is typed ``read_only`` and leaves bytes, mode and recovery untouched."""
    proposal = request(editor, SOURCE.replace("old.json", "new.json"))
    editor.project.source_file.chmod(0o444)
    try:
        with pytest.raises(AuthoringError, match="This file is read-only on disk") as refused:
            editor.save(proposal)
        assert refused.value.code == "read_only"
        assert editor.project.source_file.read_text() == SOURCE
        assert editor.project.source_file.stat().st_mode & 0o777 == 0o444
        assert list(editor.project.recovery_directory.iterdir()) == []
    finally:
        editor.project.source_file.chmod(0o644)


def test_open_failures_name_the_reason_and_the_path(editor):
    """Fails if a missing, unreadable or oversized file reaches the browser as a generic
    unavailable/unsaved error without its path (red-team E-4)."""
    path = editor.project.source_file
    path.write_bytes(b"#" * 32769)
    with pytest.raises(AuthoringError, match="larger than the 32 KiB editor limit") as large:
        editor.read()
    assert str(path) in str(large.value)
    path.write_text(SOURCE)
    if os.geteuid() != 0:
        path.chmod(0o000)
        try:
            with pytest.raises(AuthoringError) as unreadable:
                editor.read()
            assert unreadable.value.code == "not_readable" and str(path) in str(unreadable.value)
        finally:
            path.chmod(0o644)
    path.rename(path.with_name("aside.py"))
    with pytest.raises(AuthoringError) as missing:
        editor.read()
    assert missing.value.code == "not_found" and str(path) in str(missing.value)
