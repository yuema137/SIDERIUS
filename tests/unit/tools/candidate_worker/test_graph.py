"""Fanout admission, AND readiness, terminal integrity and control-size boundaries."""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from tests.helpers.candidate_fanout import fanout_request
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import admit_graph_control, verify_graph_trace
from tools.candidate_worker.models import CandidateRunReceipt
from workflows.definition import WorkflowDocument
from workflows.definition.fanout import proposal_fanout

from .test_native import native_runner


def initial(request, workspace=None):
    workspace = workspace or request.preview.document.definition.task.workspace
    return CandidateRunReceipt(
        run_id="a" * 32,
        run_name=request.run_name,
        workspace=workspace,
        declaration_digest=request.declaration_digest,
        status="launched",
        node_ids=tuple(node.id for node in request.preview.document.definition.nodes),
        selected_constructor_routes=request.selected_constructor_routes,
        ledger_path=f"{workspace}/token_usage.jsonl",
        log_path=f"{workspace}/candidate_run/worker.log",
    )


def test_more_than_sixteen_branches_use_request_bytes_not_count(prepared):
    request = fanout_request(prepared, 17)
    shape = proposal_fanout(request.preview.document.definition)
    assert len(shape.branches) == 17
    assert dict(shape.predecessors)["check16"] == frozenset(("propose", "build16"))
    admit_graph_control(request, initial(request))


@pytest.mark.parametrize("missing", ["proposal", "implementation"])
def test_validation_never_dispatches_without_both_successful_results(
    prepared, native_runner, monkeypatch, missing
):
    from tools.candidate_worker import phases

    calls = []

    def failed(*args, **kwargs):
        calls.append(missing)
        raise RuntimeError("uncertain native failure")

    def forbidden(*args, **kwargs):
        raise AssertionError("validator ran without both inputs")

    monkeypatch.setattr(phases, f"run_{missing}", failed)
    monkeypatch.setattr(phases, "run_validation", forbidden)
    request = fanout_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert calls == [missing]
    trace = receipt.graph_trace
    assert trace is not None
    assert all(item.state == "blocked" for item in trace.nodes if item.capability == "validation")
    assert trace.nodes[-2].state == "blocked"  # no independent effects after uncertainty
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )


@pytest.mark.parametrize("defect", ["missing_proposal", "same_validator", "wrong_branch"])
def test_unsupported_join_shapes_refuse(prepared, defect):
    request = fanout_request(prepared)
    raw = request.preview.document.model_dump(mode="json")
    nodes = raw["definition"]["nodes"]
    if defect == "missing_proposal":
        nodes[2]["request"]["arguments"].pop(0)
    elif defect == "same_validator":
        nodes[4]["request"]["arguments"][1]["source"]["node"] = "build0"
    else:
        nodes[3]["request"]["arguments"][0]["source"]["node"] = "build0"
    with pytest.raises(ValueError):
        proposal_fanout(WorkflowDocument.model_validate_json(json.dumps(raw)).definition)


def test_control_exact_limit_and_one_byte_over(monkeypatch):
    from core import control_json

    class Record(BaseModel):
        value: str

    record = Record(value="内容")
    size = len(control_json.encode_control(record))
    monkeypatch.setattr(control_json, "JSON_LIMIT", size)
    assert len(control_json.encode_control(record)) == size
    monkeypatch.setattr(control_json, "JSON_LIMIT", size - 1)
    with pytest.raises(ValueError, match="exceeds"):
        control_json.encode_control(record)


def test_full_trace_budget_is_admitted_before_native_or_workspace_effects(prepared, monkeypatch):
    from core import control_json

    request = fanout_request(prepared, 17)
    launch = initial(request, "/" + ("长" * 10000))
    request_size = len(control_json.encode_control(request))
    initial_size = len(control_json.encode_control(launch))
    monkeypatch.setattr(control_json, "JSON_LIMIT", max(request_size, initial_size) + 1)
    with pytest.raises(ValueError, match="exceeds"):
        admit_graph_control(request, launch)
    assert not Path(request.preview.document.definition.task.workspace).exists()


def test_final_overflow_is_honest_failure_without_partial_trace(prepared, monkeypatch):
    from core import control_json
    from tools.candidate_worker.launch import bounded_terminal

    request = fanout_request(prepared)
    launch = initial(request)
    monkeypatch.setattr(control_json, "JSON_LIMIT", len(control_json.encode_control(launch)) + 100)
    terminal = launch.model_copy(update={"status": "accepted", "error": "x" * 10000})
    result = bounded_terminal(launch, terminal)
    assert result.status == "failed" and result.error == "graph_control_overflow"
    assert result.graph_trace is None and result.native_output_paths == ()


def test_fixed_serialization_omits_graph_fields(prepared):
    assert "execution_profile" not in prepared.preview.model_dump()
    assert "graph_trace" not in initial(prepared).model_dump()
