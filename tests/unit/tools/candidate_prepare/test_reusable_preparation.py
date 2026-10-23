"""Publication identity, source preservation and no-write admission witnesses."""

import hashlib
import importlib
import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_prepare import (
    ReusableCandidatePreparationRequest,
    preflight_reusable_candidate,
    prepare_reusable_candidate,
)
from tools.candidate_worker import CandidateRunRequest
from tools.workspace_sandbox.runner import ExecutionResult
from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture
def reusable(selection):
    raw = parse_workflow_source(
        (REPO / "examples/workflow_declarations/reusable_candidate.py").read_text()
    ).model_dump()
    raw["definition"]["externals"] = tuple(
        e for e in raw["definition"]["externals"] if e["id"] != "context"
    )
    raw["definition"]["nodes"][1]["request"]["arguments"] = tuple(
        a
        for a in raw["definition"]["nodes"][1]["request"]["arguments"]
        if a["name"] != "constraint_context"
    )
    raw["definition"]["task"] = {"manifest": selection.task_manifest, "data_root": "data"}
    raw["preparation_options"]["allowed_output_types"] = ("classifier",)
    document = ReusableWorkflowDocument.model_validate(raw)
    root = Path(selection.data_root).parent
    source = root / "workflow.py"
    source.write_text("# exact authored comment\n" + render_workflow_source(document))
    runs = root / "runs"
    runs.mkdir()
    return ReusableCandidatePreparationRequest(
        source_path=str(source),
        project_root=str(root),
        expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        runs_root=str(runs),
        run_id=uuid4(),
        **selection.model_dump(
            include={
                "run_name",
                "llm_config_file",
                "preparation_timeout_seconds",
                "candidate_timeout_seconds",
                "task_read_only",
                "candidate_network",
                "candidate_devices",
                "candidate_environment_names",
            }
        ),
    )


@pytest.fixture
def direct_child(monkeypatch):
    """Real child/native imports without sandbox; sandbox coverage lives in integration."""

    def execute(profile, argv):
        child = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        if child.returncode:
            raise AssertionError(
                child.stderr + (profile.workspace / "preparation/worker.log").read_text()
            )
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)

    monkeypatch.setattr(importlib.import_module("tools.candidate_prepare.launch"), "run", execute)
    return execute


def test_two_fresh_envelopes_preserve_authored_graph_and_native_options(reusable, direct_child):
    """Same source yields distinct concrete storage paths, alias identities and v1 worker captures."""
    original = Path(reusable.source_path).read_bytes()
    outputs = []
    for request in (reusable, reusable.model_copy(update={"run_id": uuid4()})):
        result = prepare_reusable_candidate(request)
        assert result.status == "prepared", result.error
        envelope = Path(result.envelope)
        output = envelope / "inputs"
        candidate = CandidateRunRequest.model_validate_json(
            Path(result.candidate_request_path).read_bytes()
        )
        assert [n.id for n in candidate.preview.document.definition.nodes] == [
            "hypothesis",
            "build",
            "check",
        ]
        assert [
            a.name for a in candidate.preview.document.definition.nodes[1].request.arguments
        ] == ["storage", "output"]
        assert candidate.preview.document.positions[0].x == 120.0
        refs = [f for f in candidate.files if f.path == str(output / "storage.json")]
        assert len(refs) == 2 and refs[0].reference != refs[1].reference
        proposal = json.loads((output / "proposal.json").read_bytes())
        expected = str(envelope / "workspace" / request.run_name / "iteration_001/attempt_001")
        assert proposal["storage"]["local"] == {"workspace": expected, "run_name": request.run_name}
        assert (
            json.loads((output / "storage.json").read_bytes())["local"]["workspace"]
            == expected + "/impl_001"
        )
        assert proposal["expert_context"][0]["content"] == "Prefer a small interpretable baseline"
        assert proposal["allowed_output_types"] == ["classifier"]
        assert candidate.implementation_advice == "Keep diagnostics explicit"
        assert candidate.validation_advice == "Inspect held-out residuals"
        assert candidate.workflow_source.reviewed_context is None
        assert candidate.workflow_source.origin_path == str(output / "workflow.resolved.py")
        assert parse_workflow_source(candidate.workflow_source.source) == candidate.preview.document
        assert (envelope / "workflow.py.snapshot").read_bytes() == original
        assert not (envelope / "workspace").exists()
        assert (
            hashlib.sha256(Path(result.candidate_request_path).read_bytes()).hexdigest()
            == result.candidate_request_sha256
        )
        assert (
            hashlib.sha256((envelope / "binding.json").read_bytes()).hexdigest()
            == result.binding_sha256
        )
        outputs.append(expected)
    assert outputs[0] != outputs[1]
    assert Path(reusable.source_path).read_bytes() == original


@pytest.mark.parametrize(
    "change", ["hash", "literal", "source_type", "mount", "alias", "environment", "edge"]
)
def test_preflight_rejection_leaves_no_envelope(reusable, change):
    """Known unsupported or unsafe inputs refuse before exclusive mkdir."""
    source = Path(reusable.source_path)
    if change == "hash":
        reusable = reusable.model_copy(update={"expected_source_sha256": "0" * 64})
    elif change == "literal":
        source.write_text(
            (REPO / "examples/workflow_declarations/reusable_candidate.py").read_text()
        )
    elif change == "source_type":
        source.write_text(
            render_workflow_source(preflight_reusable_candidate(reusable).resolved_document)
        )
    elif change == "mount":
        reusable = reusable.model_copy(update={"task_read_only": (reusable.runs_root,)})
    elif change == "alias":
        reusable = reusable.model_copy(update={"runs_root": reusable.runs_root + "/."})
    elif change == "environment":
        reusable = reusable.model_copy(update={"candidate_environment_names": ("PYTHONPATH",)})
    else:
        source.write_text(source.read_text().replace("node='build'", "node='hypothesis'", 1))
    if change in {"literal", "source_type", "edge"}:
        reusable = reusable.model_copy(
            update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        )
    with pytest.raises(ValueError):
        prepare_reusable_candidate(reusable)
    assert list(Path(reusable.runs_root).iterdir()) == []


@pytest.mark.parametrize(
    "change",
    [
        "proposal_storage",
        "storage",
        "proposal_advice",
        "output_types",
        "workflow",
        "derived",
        "binding",
        "snapshot",
        "control",
        "source",
    ],
)
def test_parent_rejects_tampering_even_with_forged_child_index(
    reusable, direct_child, monkeypatch, change
):
    """Forged hashes cannot make wrong storage/options/graph agree with retained parent authority."""

    def tamper(profile, argv):
        result = direct_child(profile, argv)
        output = profile.workspace
        targets = {
            "proposal_storage": "proposal.json",
            "storage": "storage.json",
            "proposal_advice": "proposal.json",
            "output_types": "proposal.json",
            "workflow": "workflow.json",
            "binding": "../binding.json",
            "control": "preparation/request.json",
        }
        if change in targets:
            path = output / targets[change]
            value = json.loads(path.read_bytes())
            if change == "proposal_storage":
                value["storage"]["local"]["workspace"] += "/wrong"
            elif change == "storage":
                value["local"]["workspace"] += "/wrong"
            elif change == "proposal_advice":
                value["expert_context"][0]["content"] = "wrong"
            elif change == "output_types":
                value["allowed_output_types"] = ["regressor"]
            elif change == "workflow":
                value["positions"][0]["x"] = 999
            elif change == "binding":
                value["project_root"] = "/wrong"
            else:
                value["request"]["implementation_advice"] = "wrong"
            path.write_text(json.dumps(value))
        elif change == "derived":
            (output / "workflow.resolved.py").write_text("# altered\n")
        elif change == "snapshot":
            (output.parent / "workflow.py.snapshot").write_text("# altered\n")
        else:
            Path(reusable.source_path).write_text("# changed origin\n")
        index_path = output / "preparation/child.json"
        index = json.loads(index_path.read_bytes())
        for item in index["files"]:
            payload = Path(item["path"]).read_bytes()
            item.update(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
        index_path.write_text(json.dumps(index))
        return result

    monkeypatch.setattr(importlib.import_module("tools.candidate_prepare.launch"), "run", tamper)
    result = prepare_reusable_candidate(reusable)
    assert result.status == "failed" and result.candidate_request_path is None
    assert not (Path(result.envelope) / "inputs/candidate_request.json").exists()
    assert json.loads((Path(result.envelope) / "receipt.json").read_bytes())["status"] == "failed"


def test_same_identity_loser_preserves_winner_and_missing_receipt_is_not_reused(
    reusable, monkeypatch
):
    """Existing envelope is not a retry or permission to publish failure into another claim."""
    envelope = Path(reusable.runs_root) / str(reusable.run_id)
    envelope.mkdir()
    marker = envelope / "owned"
    marker.write_bytes(b"winner")
    with pytest.raises(ValueError, match="absent"):
        prepare_reusable_candidate(reusable)
    assert list(envelope.iterdir()) == [marker] and marker.read_bytes() == b"winner"


def test_capture_rechecks_origin_without_replacing_observed_bytes(reusable, monkeypatch):
    """An edit after the initial read refuses before claiming; no mixed source/hash capture."""
    admission = importlib.import_module("tools.candidate_prepare.reusable_admission")
    original = admission.admit

    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(reusable.source_path).write_text("# edited after capture\n")
        return result

    monkeypatch.setattr(admission, "admit", drift)
    with pytest.raises(ValueError, match="source changed"):
        prepare_reusable_candidate(reusable)
    assert list(Path(reusable.runs_root).iterdir()) == []


def test_relative_references_bind_project_base_and_named_sources(reusable, tmp_path):
    """Identical text under distinct explicit bases selects distinct resources, without writes."""
    source = Path(reusable.source_path)
    document = parse_workflow_source(source.read_text())
    raw = document.model_dump()
    raw["definition"]["task"]["manifest"] = "task.yaml"
    source.write_text(render_workflow_source(ReusableWorkflowDocument.model_validate(raw)))
    selected = []
    for label in ("one", "two"):
        project = tmp_path / label
        project.mkdir()
        (project / "data").mkdir()
        (project / "task.yaml").write_text("not imported by preflight")
        renamed = project / f"{label}.py"
        renamed.write_bytes(source.read_bytes())
        plan = preflight_reusable_candidate(
            reusable.model_copy(
                update={
                    "source_path": str(renamed),
                    "project_root": str(project),
                    "expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            )
        )
        assert plan.binding.request.task_manifest == str(project / "task.yaml")
        selected.append(plan.binding.request.data_root)
    assert selected == [str(tmp_path / "one/data"), str(tmp_path / "two/data")]
    assert list(Path(reusable.runs_root).iterdir()) == []


def test_late_failure_leaves_diagnostics_without_success_receipt(
    reusable, direct_child, monkeypatch
):
    """Published request-shaped files are not reusable success when final source check fails."""
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    original = launch.verify_origin
    checks = 0

    def fail_late(binding):
        nonlocal checks
        checks += 1
        if checks == 3:
            raise ValueError("late source drift")
        original(binding)

    monkeypatch.setattr(launch, "verify_origin", fail_late)
    result = prepare_reusable_candidate(reusable)
    assert result.status == "failed" and result.candidate_request_sha256 is None
    assert (Path(result.envelope) / "inputs/candidate_request.json").exists()
    assert json.loads((Path(result.envelope) / "receipt.json").read_bytes())["status"] == "failed"


def test_concurrent_claim_has_one_writer(reusable, monkeypatch):
    """Two fully admitted callers race the actual mkdir; loser never writes into winner."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    original = launch.verify_origin
    ready = Barrier(2)

    def align(binding):
        original(binding)
        ready.wait(timeout=10)

    monkeypatch.setattr(launch, "verify_origin", align)
    monkeypatch.setattr(
        launch,
        "supervise",
        lambda *args, **kwargs: ExecutionResult(status="failed", returncode=1, elapsed_seconds=0.0),
    )

    def attempt():
        try:
            return prepare_reusable_candidate(reusable)
        except FileExistsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result is not None)
    assert (
        json.loads((Path(winner.envelope) / "receipt.json").read_bytes())["binding_sha256"]
        == winner.binding_sha256
    )


def test_cli_dispatch_uses_public_owner_and_failure_exit(reusable, monkeypatch, capsys):
    """The reusable CLI selects the same typed owner and reports its terminal failure."""
    cli = importlib.import_module("tools.candidate_prepare.__main__")
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    path = Path(reusable.project_root) / "reusable-request.json"
    path.write_text(reusable.model_dump_json())
    monkeypatch.setattr(
        launch,
        "supervise",
        lambda *args, **kwargs: ExecutionResult(
            status="timed_out", returncode=-9, elapsed_seconds=1.0
        ),
    )
    monkeypatch.setattr("sys.argv", ["prepare", "--reusable-request", str(path)])
    assert cli.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "timed_out" and result["candidate_request_path"] is None


def test_replaced_envelope_cannot_receive_parent_receipt(reusable, monkeypatch):
    """Even a nonsymlink replacement directory is not owned by the original claim."""
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    envelope = Path(reusable.runs_root) / str(reusable.run_id)
    displaced = Path(reusable.runs_root) / "displaced"

    def replace(*args, **kwargs):
        envelope.rename(displaced)
        envelope.mkdir()
        (envelope / "other-owner").write_text("preserve")
        return ExecutionResult(status="failed", returncode=1, elapsed_seconds=0.0)

    monkeypatch.setattr(launch, "supervise", replace)
    with pytest.raises(ValueError, match="directory was replaced"):
        prepare_reusable_candidate(reusable)
    assert [path.name for path in envelope.iterdir()] == ["other-owner"]
    assert not (displaced / "receipt.json").exists()


def test_native_composition_failure_keeps_failed_capture(reusable, monkeypatch):
    """A manifest can pass read-only admission but fail trusted native decoding after claim."""
    source = Path(reusable.source_path)
    document = parse_workflow_source(source.read_text()).model_dump()
    manifest = Path(reusable.project_root) / "invalid.yaml"
    manifest.write_text("invalid: task\n")
    document["definition"]["task"]["manifest"] = str(manifest)
    source.write_text(render_workflow_source(ReusableWorkflowDocument.model_validate(document)))
    reusable = reusable.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )

    def execute(profile, argv):
        child = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return ExecutionResult(
            status="failed" if child.returncode else "completed",
            returncode=child.returncode,
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr(importlib.import_module("tools.candidate_prepare.launch"), "run", execute)
    receipt = prepare_reusable_candidate(reusable)
    assert receipt.status == "failed" and receipt.candidate_request_path is None
    envelope = Path(receipt.envelope)
    assert (envelope / "workflow.py.snapshot").read_bytes() == source.read_bytes()
    assert (envelope / "inputs/preparation/worker.log").stat().st_size > 0
    assert not (envelope / "workspace").exists()
