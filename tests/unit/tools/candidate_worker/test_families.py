"""Independent proposal ownership across admission, native calls and terminal replay."""

import json
from pathlib import Path

import pytest

from tests.helpers.candidate_fanout import families_request
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.workflow_preview import preview_workflow
from tools.workflow_preview.models import WorkflowPreviewRequest
from workflows.definition import WorkflowDocument
from workflows.definition.fanout import proposal_fanout

from .conftest import refresh
from .test_graph import initial
from .test_native import native_runner


@pytest.mark.parametrize("defect", ["cross_family", "orphan", "legacy_profile"])
def test_family_admission_rejects_lineage_mismatch(prepared, defect):
    """A valid protocol type alone cannot prove common proposal ownership."""
    request = families_request(prepared)
    raw = request.preview.model_dump(mode="json")
    if defect == "cross_family":
        raw["document"]["definition"]["nodes"][0]["request"]["arguments"][0]["source"]["node"] = (
            "propose1"
        )
    elif defect == "orphan":
        raw["document"]["definition"]["nodes"] = raw["document"]["definition"]["nodes"][2:]
    else:
        raw["execution_profile"] = "native-proposal-fanout/v1"
    with pytest.raises(ValueError):
        preview_workflow(WorkflowPreviewRequest.model_validate_json(json.dumps(raw)))
    assert not Path(request.preview.document.definition.task.workspace).exists()


def test_families_keep_proposal_identity_inputs_debug_and_trace_separate(prepared, native_runner):
    """Fails for the old single input filename or first-proposal result dispatch."""
    request = families_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == "accepted", receipt.error
    trace = receipt.graph_trace
    assert trace is not None
    records = {
        item.node_id: json.loads(Path(item.record_path).read_bytes()) for item in trace.nodes
    }
    assert records["propose0"]["candidate_id"] != records["propose1"]["candidate_id"]
    control = Path(receipt.workspace) / "candidate_run"
    assert not (control / "proposal_input.json").exists()
    for index in range(2):
        proposal, impl, valid = f"propose{index}", f"build{index}", f"check{index}"
        assert (
            records[proposal]["candidate_id"]
            == records[impl]["candidate_id"]
            == records[valid]["candidate_id"]
        )
        assert records[valid]["tests_passed"] and records[valid]["gradient_check_passed"]
        seed = json.loads((control / "proposal_inputs" / f"{proposal}.json").read_bytes())
        assert seed["storage"]["local"]["workspace"].endswith(
            f"graph_instances/{proposal}/iteration_001/attempt_001"
        )
        assert Path(seed["debug_dump_proposing_prompt_path"]).is_file()
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )
    nodes = list(trace.nodes)
    nodes[0] = nodes[0].model_copy(update={"predecessors": ("build0", "propose1")})
    with pytest.raises(ValueError, match="binding mismatch"):
        verify_graph_trace(
            request,
            initial(request),
            receipt.model_copy(
                update={"graph_trace": trace.model_copy(update={"nodes": tuple(nodes)})}
            ),
        )


@pytest.mark.parametrize("collision", ["debug", "storage"])
def test_family_input_collision_refuses_before_any_native_call(prepared, native_runner, collision):
    request = families_request(prepared)
    project = Path(request.preview.project_root)
    path = project / ("seed1.json" if collision == "debug" else "slot1.json")
    other = json.loads(
        (project / ("seed0.json" if collision == "debug" else "slot0.json")).read_bytes()
    )
    data = json.loads(path.read_bytes())
    if collision == "debug":
        data["debug_dump_proposing_prompt_path"] = other["debug_dump_proposing_prompt_path"]
    else:
        data = other
    path.write_text(json.dumps(data))
    receipt = launch_candidate(refresh(request))
    assert receipt.status == "failed"
    assert not native_runner.calls
    assert not (Path(receipt.workspace) / "candidate_run/proposal_inputs").exists()


@pytest.mark.parametrize("failed", [False, True])
def test_family_rejection_continues_but_native_failure_stops_other_families(
    prepared, native_runner, monkeypatch, failed
):
    from tools.candidate_worker import phases

    original = phases.run_validation

    def first(*args, **kwargs):
        if args[0].node_id == "check0":
            if failed:
                raise RuntimeError("uncertain first-family validation")
            native_runner.reject = True
        else:
            native_runner.reject = False
        return original(*args, **kwargs)

    monkeypatch.setattr(phases, "run_validation", first)
    request = families_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == ("failed" if failed else "rejected")
    states = {item.node_id: item.state for item in receipt.graph_trace.nodes}
    assert states["check0"] == ("failed" if failed else "rejected")
    assert (
        states["propose1"]
        == states["build1"]
        == states["check1"]
        == ("blocked" if failed else "succeeded")
    )
    verify_graph_trace(request, initial(request), receipt)
