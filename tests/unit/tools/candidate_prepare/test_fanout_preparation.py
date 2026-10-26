"""Reusable graph admission and independently reconstructed parent artifacts."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.helpers.reusable_fanout import reusable_fanout
from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tools.candidate_prepare import preflight_reusable_candidate, prepare_reusable_candidate
from tools.candidate_prepare.reusable_models import ReusablePreparationControl
from tools.candidate_prepare.reusable_verify import verify_reusable_bundle
from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)


def test_graph_preparation_rebuilds_branch_storage_and_profile(reusable, direct_child):
    """Forged child indexes cannot change storage ownership, file census or execution mode."""
    request = reusable_fanout(reusable)
    source = Path(request.source_path).read_bytes()
    plan = preflight_reusable_candidate(request)
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "prepared", receipt.error
    output = Path(receipt.envelope) / "inputs"
    control = ReusablePreparationControl.model_validate_json(
        (output / "preparation/request.json").read_bytes()
    )
    candidate, _, _ = verify_reusable_bundle(plan, source, control)
    assert candidate.preview.execution_profile == "native-proposal-fanout/v1"
    externals = {item.id: item.location for item in candidate.preview.document.definition.externals}
    assert externals["slot_left"] == str(output / "storage.build_left.json")
    assert externals["slot_right"] == str(output / "storage.build_right.json")
    index_path = output / "preparation/child.json"
    index_bytes = index_path.read_bytes()
    index = json.loads(index_bytes)
    assert [item["reference"] for item in index["files"]] == [
        "preparation/interpretation_input.json",
        "interpretation.json",
        "proposal.json",
        "storage.build_left.json",
        "storage.build_right.json",
        "llm.json",
        "workflow.json",
        "workflow.resolved.py",
    ]
    for fault in ("missing", "extra", "reordered", "storage", "profile"):
        changed = json.loads(index_bytes)
        storage_path = output / "storage.build_left.json"
        original_storage = storage_path.read_bytes()
        if fault == "missing":
            changed["files"].pop()
        elif fault == "extra":
            changed["files"].append(changed["files"][0])
        elif fault == "reordered":
            changed["files"].reverse()
        elif fault == "storage":
            storage_path.write_bytes((output / "storage.build_right.json").read_bytes())
            for item in changed["files"]:
                payload = Path(item["path"]).read_bytes()
                item.update(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
        else:
            from tools.candidate_prepare.resolution import resolve_reusable_candidate

            with pytest.raises(ValueError):
                resolve_reusable_candidate(
                    plan.document.model_copy(update={"execution_profile": None}),
                    plan.binding.locations,
                )
            continue
        index_path.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match=r"artifact set|attempt storage"):
            verify_reusable_bundle(plan, source, control)
        storage_path.write_bytes(original_storage)
        index_path.write_bytes(index_bytes)
    assert Path(request.source_path).read_bytes() == source
    # A child-selected mode cannot replace the captured source, even with repaired hashes.
    from tools.candidate_prepare import select_reusable_preparation

    candidate_path = output / "candidate_request.json"
    changed_candidate = json.loads(candidate_path.read_bytes())
    changed_candidate["preview"].pop("execution_profile")
    candidate_path.write_text(json.dumps(changed_candidate))
    receipt_path = output.parent / "receipt.json"
    changed_receipt = json.loads(receipt_path.read_bytes())
    changed_receipt["candidate_request_sha256"] = hashlib.sha256(
        candidate_path.read_bytes()
    ).hexdigest()
    receipt_path.write_text(json.dumps(changed_receipt))
    with pytest.raises(ValueError, match="independently verified inputs"):
        select_reusable_preparation(receipt.envelope)


def test_cross_branch_alias_and_arbitrary_storage_refuse_before_claim(reusable):
    """Valid graph edges cannot authorize cross-owner storage aliases or caller-picked locations."""
    request = reusable_fanout(reusable)
    plan = preflight_reusable_candidate(request)
    from tools.candidate_prepare.resolution import resolve_reusable_candidate

    locations = plan.binding.locations.model_copy(
        update={
            "externals": tuple(
                item.model_copy(update={"location": "/wrong"})
                if item.binding == "slot_left"
                else item
                for item in plan.binding.locations.externals
            )
        }
    )
    with pytest.raises(ValueError, match="generated branch"):
        resolve_reusable_candidate(plan.document, locations)
    raw = plan.document.model_dump(mode="json")
    raw["definition"]["externals"] = [
        item for item in raw["definition"]["externals"] if item["id"] != "slot_right"
    ]
    for node in raw["definition"]["nodes"]:
        for arg in node["request"].get("arguments", []):
            if arg["name"] == "storage":
                arg["source"]["binding"] = "slot_left"
    document = ReusableWorkflowDocument.model_validate_json(json.dumps(raw))
    with pytest.raises(ValueError, match="shared across"):
        resolve_reusable_candidate(
            document,
            plan.binding.locations.model_copy(
                update={
                    "externals": tuple(
                        item
                        for item in plan.binding.locations.externals
                        if item.binding != "slot_right"
                    )
                }
            ),
        )
    assert not list(Path(request.runs_root).iterdir())


def test_absent_profile_preserves_source_json_and_semantic_identity(reusable):
    """The new opt-in must not change existing source rendering or canonical semantic bytes."""
    document = parse_workflow_source(Path(reusable.source_path).read_text())
    assert isinstance(document, ReusableWorkflowDocument)
    raw = document.model_dump(mode="json")
    assert "execution_profile" not in raw
    expected = hashlib.sha256(
        json.dumps(
            {key: value for key, value in raw.items() if key != "positions"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert document.declaration_digest() == expected
    assert "execution_profile" not in render_workflow_source(document)
    from tools.workflow_authoring.task_publication import adoption_unchanged

    assert not adoption_unchanged(
        document, document.model_copy(update={"execution_profile": "native-proposal-fanout/v1"})
    )


def test_graph_control_overflow_never_publishes_success(reusable, direct_child, monkeypatch):
    """The parent must size the rebuilt candidate before publishing any candidate record."""
    from core.control_json import ControlOverflow
    from tools.candidate_prepare import reusable_launch
    from tools.candidate_worker import CandidateRunRequest

    original = reusable_launch.encode_control

    def overflow(record):
        if isinstance(record, CandidateRunRequest):
            raise ControlOverflow("JSON record exceeds 4 MiB")
        return original(record)

    monkeypatch.setattr(reusable_launch, "encode_control", overflow)
    receipt = prepare_reusable_candidate(reusable_fanout(reusable))
    assert receipt.status == "failed" and receipt.candidate_request_path is None
    output = Path(receipt.envelope) / "inputs"
    assert (output / "storage.build_left.json").exists()
    assert not (output / "candidate_request.json").exists()
    assert not (output / "preview.json").exists()


def test_graph_write_envelope_matches_existing_read_and_control_boundaries(tmp_path):
    """Exact ceiling succeeds; one additional byte fails at both bounded file owners."""
    from pydantic import BaseModel

    from core.control_json import JSON_LIMIT, ControlOverflow, encode_control
    from tools.candidate_prepare.limits import PREPARATION_FILE_LIMIT, bounded_payload
    from tools.candidate_prepare.reusable_admission import safe_bytes

    path = tmp_path / "payload"
    exact = b"x" * PREPARATION_FILE_LIMIT
    path.write_bytes(bounded_payload(exact))
    assert safe_bytes(path) == exact
    with pytest.raises(ValueError, match="preparation read limit"):
        bounded_payload(exact + b"x")
    path.write_bytes(exact + b"x")
    with pytest.raises(ValueError, match="preparation read limit"):
        safe_bytes(path)

    class Record(BaseModel):
        content: str

    overhead = len(encode_control(Record(content="")))
    record = Record(content="x" * (JSON_LIMIT - overhead))
    assert len(encode_control(record)) == JSON_LIMIT
    with pytest.raises(ControlOverflow):
        encode_control(Record(content=record.content + "x"))
