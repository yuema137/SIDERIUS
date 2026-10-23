"""Retained receipt identity and cross-owner reconstruction, without mutable source."""

import hashlib
import importlib
import json
from collections import Counter
from pathlib import Path

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tools.candidate_prepare import (
    ReusablePreparedSelection,
    prepare_reusable_candidate,
    select_reusable_preparation,
    verify_reusable_preparation,
)
from tools.candidate_prepare.reusable_verify import encoded


@pytest.fixture
def published(reusable, direct_child):
    receipt = prepare_reusable_candidate(reusable)
    assert receipt.status == "prepared", receipt.error
    return reusable, Path(receipt.envelope), select_reusable_preparation(receipt.envelope)


def test_current_selection_pins_published_bytes_and_ignores_later_canonical_edit(published):
    """Hashing model JSON would pin wrong bytes; recapturing origin would reject a valid capture."""
    request, envelope, selection = published
    original = (envelope / "workflow.py.snapshot").read_bytes()
    assert (
        selection.expected_receipt_sha256
        == hashlib.sha256((envelope / "receipt.json").read_bytes()).hexdigest()
    )
    Path(request.source_path).write_text("# future workflow version\n")
    result = verify_reusable_preparation(selection)
    assert result.request.implementation_advice == "Keep diagnostics explicit"
    assert result.binding.original_source.sha256 == hashlib.sha256(original).hexdigest()
    assert not (envelope / "workspace").exists()


def test_verification_uses_one_read_per_path_with_fresh_passes(published, monkeypatch):
    """An observation then a second parse could otherwise mix two versions of proposal bytes."""
    _, envelope, selection = published
    module = importlib.import_module("tools.candidate_prepare.reusable_selection")
    original = module.safe_bytes
    counts = Counter()

    def read(path):
        counts[path] += 1
        value = original(path)
        if path == envelope / "inputs/proposal.json":
            path.write_bytes(b"changed after captured read")
        return value

    monkeypatch.setattr(module, "safe_bytes", read)
    verify_reusable_preparation(selection)
    assert counts and set(counts.values()) == {1}
    with pytest.raises(ValueError):
        verify_reusable_preparation(selection)


@pytest.mark.parametrize(
    "change",
    [
        "receipt",
        "binding",
        "snapshot",
        "request",
        "preview",
        "control",
        "native",
        "config",
        "missing",
        "failed",
        "symlink",
        "oversize",
    ],
)
def test_retained_selection_refuses_changed_or_unsafe_files(published, change):
    """Each mutation breaks a distinct capture/control/observed-input relationship, with no writes."""
    request, envelope, selection = published
    files = {
        "receipt": envelope / "receipt.json",
        "binding": envelope / "binding.json",
        "snapshot": envelope / "workflow.py.snapshot",
        "request": envelope / "inputs/candidate_request.json",
        "preview": envelope / "inputs/preview.json",
        "control": envelope / "inputs/preparation/request.json",
        "native": envelope / "inputs/preparation/receipt.json",
        "config": Path(request.llm_config_file),
    }
    if change == "missing":
        (envelope / "receipt.json").unlink()
    elif change == "failed":
        path = envelope / "receipt.json"
        value = json.loads(path.read_bytes())
        value["status"] = "failed"
        path.write_text(json.dumps(value))
        selection = ReusablePreparedSelection(
            envelope=str(envelope),
            expected_receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    elif change == "symlink":
        path = envelope / "inputs/proposal.json"
        saved = path.rename(envelope / "alias-target")
        path.symlink_to(saved)
    elif change == "oversize":
        (envelope / "inputs/proposal.json").write_bytes(b" " * (16 * 1024 * 1024 + 1))
    else:
        files[change].write_bytes(b"altered")
    with pytest.raises((ValueError, OSError)):
        verify_reusable_preparation(selection)
    assert not (envelope / "workspace").exists()


@pytest.mark.parametrize("change", ["locations", "options", "storage", "graph"])
def test_reconstruction_rejects_self_consistent_child_claims(published, change):
    """Even a caller selecting current bytes cannot bless locations/options/native payload mismatches."""
    _, envelope, _ = published
    binding_path = envelope / "binding.json"
    binding = json.loads(binding_path.read_bytes())
    if change == "locations":
        binding["locations"]["data_root"] += "/wrong"
    elif change == "options":
        binding["request"]["implementation_advice"] = "changed outside authored source"
    elif change == "storage":
        path = envelope / "inputs/storage.json"
        value = json.loads(path.read_bytes())
        value["local"]["workspace"] += "/wrong"
        path.write_text(json.dumps(value))
    else:
        path = envelope / "inputs/workflow.json"
        value = json.loads(path.read_bytes())
        value["positions"][0]["x"] = 999
        path.write_text(json.dumps(value))
    from tools.candidate_prepare.reusable_models import (
        ReusableBindingCapture,
        ReusablePreparationControl,
    )

    binding_path.write_bytes(
        encoded(ReusableBindingCapture.model_validate_json(json.dumps(binding)))
    )
    control_path = envelope / "inputs/preparation/request.json"
    control = json.loads(control_path.read_bytes())
    control["request"] = binding["request"]
    control["binding_sha256"] = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    control_path.write_bytes(
        encoded(ReusablePreparationControl.model_validate_json(json.dumps(control)))
    )
    index_path = envelope / "inputs/preparation/child.json"
    index = json.loads(index_path.read_bytes())
    index["control_sha256"] = hashlib.sha256(control_path.read_bytes()).hexdigest()
    for item in index["files"]:
        payload = Path(item["path"]).read_bytes()
        item.update(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
    index_path.write_text(json.dumps(index))
    receipt_path = envelope / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["binding_sha256"] = control["binding_sha256"]
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        select_reusable_preparation(str(envelope))


def test_coherent_replacement_cannot_replace_retained_selection(published, direct_child):
    """A wholly valid new publication at the old path cannot reuse the caller's retained identity."""
    request, envelope, retained = published
    envelope.rename(envelope.with_name("old-capture"))
    source = Path(request.source_path)
    source.write_text(
        source.read_text().replace("Keep diagnostics explicit", "Different future advice")
    )
    request = request.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )
    fresh = prepare_reusable_candidate(request)
    assert fresh.status == "prepared", fresh.error
    current = select_reusable_preparation(fresh.envelope)
    assert (
        verify_reusable_preparation(current).request.implementation_advice
        == "Different future advice"
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_reusable_preparation(retained)


def test_observed_manifest_drift_is_checked_without_import(published, monkeypatch):
    """The snapshot authorizes source edits, not changes to the observed task manifest."""
    _, _, selection = published
    module = importlib.import_module("tools.candidate_prepare.reusable_selection")
    original = module.safe_bytes
    manifest = verify_reusable_preparation(selection).binding.request.task_manifest
    monkeypatch.setattr(
        module,
        "safe_bytes",
        lambda path: original(path) + (b"\n# drift" if str(path) == manifest else b""),
    )
    with pytest.raises(ValueError, match=r"selected input changed: task.manifest"):
        verify_reusable_preparation(selection)


def test_b1_publication_second_pass_is_fresh(reusable, direct_child, monkeypatch):
    """Sharing a cache across B1's two passes would publish success after artifact drift."""
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    original = launch.publish

    def mutate(path, record):
        original(path, record)
        if path.name == "candidate_request.json":
            (path.parent / "proposal.json").write_bytes(b"late change")

    monkeypatch.setattr(launch, "publish", mutate)
    receipt = prepare_reusable_candidate(reusable)
    assert receipt.status == "failed"
    assert receipt.candidate_request_sha256 is None
