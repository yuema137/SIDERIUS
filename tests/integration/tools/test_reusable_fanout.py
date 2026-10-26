"""Real pinned v2 preparation to existing detached G1 runtime; no API or GPU."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from tests.helpers.candidate_literature import write_literature_provider
from tests.helpers.reusable_fanout import reusable_families, reusable_fanout
from tests.helpers.reusable_literature import reusable_literature
from tests.integration.tools.test_bound_reusable_preparation import bound, bound_console_config
from tests.integration.tools.test_candidate_operations import wait_for
from tests.integration.tools.test_candidate_operations_native import cli, native_submitter
from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_prepare.test_task_binding import bind_source
from tools.candidate_console.reusable_candidate import ReusableCandidate
from tools.candidate_console.reusable_models import ReusableCaptureChoice
from tools.candidate_console.service import CandidateConsole
from tools.candidate_operations import (
    ReusablePrepareOperation,
    build_reusable_operation,
    read_operation,
)
from tools.candidate_operations.process import environment
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import load_record
from tools.candidate_prepare import prepare_reusable_candidate
from tools.candidate_prepare.reusable_models import ReusablePreparationReceipt

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


@pytest.mark.parametrize("profile", ["fanout", "families", "literature"])
def test_bound_v2_fanout_detached_prepare_review_execute_and_http(
    bound, console_config, tmp_path, profile
):
    """Same-name models retain edge-owned sources through native preparation, UUID recovery and HTTP."""
    reusable, pin = bound
    families = profile == "families"
    literature = profile == "literature"
    factory = {
        "fanout": reusable_fanout,
        "families": reusable_families,
        "literature": reusable_literature,
    }[profile]
    reusable = factory(reusable).model_copy(
        update={"candidate_environment_names": ("EXPLICIT_TEST_KEY", "OPENAI_API_KEY")}
    )
    original = Path(reusable.source_path).read_bytes()
    config, project, task = bound_console_config(reusable, pin, console_config, tmp_path)
    store = config.operation_store
    store_path = tmp_path / "store.json"
    store_path.write_text(store.model_dump_json())
    preparation = ReusablePrepareOperation(request_id=uuid4(), request=reusable)
    preparation_path = tmp_path / "prepare.json"
    preparation_path.write_text(preparation.model_dump_json())
    assert (
        json.loads(cli(store_path, "submit", "--request", str(preparation_path)).stdout)[
            "observation"
        ]
        == "starting"
    )
    wait_for(lambda: releasable(store, preparation.request_id), timeout=60)
    prepared = read_operation(store, preparation.request_id)
    assert prepared.state == "completed" and prepared.receipt.status == "prepared", prepared
    envelope = Path(prepared.receipt.envelope)
    # A second fresh envelope proves source reuse without repeating model validation.
    second_request = tmp_path / "second-prepare.json"
    second_request.write_text(reusable.model_copy(update={"run_id": uuid4()}).model_dump_json())
    second_cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.candidate_prepare",
            "--reusable-request",
            str(second_request),
        ],
        env=environment((), {}),
        capture_output=True,
        text=True,
        timeout=45,
        check=True,
    )
    second = ReusablePreparationReceipt.model_validate_json(second_cli.stdout)
    assert second.status == "prepared", second.error
    assert (Path(second.envelope) / "workflow.py.snapshot").read_bytes() == original
    assert (envelope / "workflow.py.snapshot").read_bytes() == original
    adapter = ReusableCandidate(CandidateConsole(config))
    choice = ReusableCaptureChoice(task_id=task.task_id, run_id=reusable.run_id)
    selected = adapter.select(project.project_id, choice)
    expected_review = adapter.review(project.project_id, selected)
    with client(config) as http:
        base = "/api/editor/bound/reusable-captures".replace("bound", project.project_id)
        picked = http.post(base + "/select", json=choice.model_dump(mode="json"))
        assert picked.status_code == 200, picked.text
        reviewed = http.post(base + "/review", json=picked.json())
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json() == expected_review.model_dump(mode="json")
    candidate = build_reusable_operation(store, selected.preparation, uuid4())
    profile = (
        "native-literature-candidate/v1"
        if literature
        else ("native-proposal-families/v1" if families else "native-proposal-fanout/v1")
    )
    if literature:
        assert expected_review.literature_settings == {
            "review": {"dynamic_search": {"enabled": False}}
        }
    assert (
        candidate.request.preview.execution_profile == expected_review.execution_profile == profile
    )
    native_receipt = json.loads((envelope / "inputs/preparation/receipt.json").read_bytes())
    assert native_receipt["proposal_path"] == (
        None if families else str(envelope / "inputs/proposal.json")
    )
    terminal = json.loads(
        cli(store_path, "status", "--operation-id", str(preparation.request_id)).stdout
    )
    assert terminal["state"] == "completed" and terminal["receipt"]["status"] == "prepared"

    path = tmp_path / "candidate.json"
    path.write_text(candidate.model_dump_json())
    submitter = native_submitter(tmp_path, envelope / "inputs", distinct_branches=True)
    if literature:
        write_literature_provider(envelope / "inputs")
    cli(
        store_path,
        "submit",
        "--request",
        str(path),
        harness=submitter,
        env={
            **environment((), {}),
            "EXPLICIT_TEST_KEY": "bound-value",
            "OPENAI_API_KEY": "offline-test-key",
        },
    )
    wait_for(lambda: releasable(store, candidate.request_id), timeout=120)
    status = read_operation(store, candidate.request_id)
    assert status.state == "completed" and status.receipt.status == "accepted", status
    trace = status.receipt.model_dump(mode="json")["graph_trace"]
    nodes = {node["node_id"]: node for node in trace["nodes"]}
    implementations = []
    for side in (
        ("left",) if literature else (("left", "right", "other") if families else ("left", "right"))
    ):
        impl, valid = nodes["build_" + side], nodes["check_" + side]
        proposal_id = "alternate" if side == "other" else "hypothesis"
        assert valid["predecessors"] == sorted(["build_" + side, proposal_id])
        assert impl["state"] == valid["state"] == "succeeded"
        record = json.loads(Path(valid["record_path"]).read_bytes())
        assert record["tests_passed"] and record["gradient_check_passed"]
        implementation = json.loads(Path(impl["record_path"]).read_bytes())
        proposal = json.loads(Path(nodes[proposal_id]["record_path"]).read_bytes())
        assert implementation["candidate_id"] == record["candidate_id"] == proposal["candidate_id"]
        implementations.append(implementation)
        assert "/graph_instances/build_" + side + "/" in implementation["model_file_path"]
    if literature:
        assert len(nodes) == 4 and nodes["hypothesis"]["predecessors"] == ["review"]
        assert nodes["review"]["state"] == "succeeded"
        review_output = json.loads(Path(nodes["review"]["record_path"]).read_bytes())
        assert review_output["findings"] == [] and review_output["retrieved_papers"] == []
        rows = [
            json.loads(line) for line in Path(status.receipt.ledger_path).read_text().splitlines()
        ]
        assert len(rows) == 1 and rows[0]["label"] == "lit_review.synthesis"
    else:
        assert implementations[0]["model_type"] == implementations[1]["model_type"]
        assert (
            Path(implementations[0]["model_file_path"]).read_bytes()
            != Path(implementations[1]["model_file_path"]).read_bytes()
        )
    with client(config) as http:
        response = http.get(f"/api/operations/{candidate.request_id}")
        assert response.status_code == 200, response.text
        assert response.json()["graph_trace"] == trace
    if families:
        assert implementations[0]["candidate_id"] != implementations[2]["candidate_id"]
        assert len(trace["nodes"]) == 8
    assert Path(reusable.source_path).read_bytes() == original
    Path(reusable.source_path).unlink()
    native_id = load_record(store, candidate.request_id).native_id
    assert (
        json.loads(cli(store_path, "submit", "--request", str(path)).stdout)["observation"]
        == "existing"
    )
    assert load_record(store, candidate.request_id).native_id == native_id
    assert not Path(reusable.source_path).exists()


@pytest.mark.parametrize("profile", ["fanout", "families", "literature"])
def test_graph_pin_refusal_precedes_branch_publication(bound, profile):
    """The explicit graph route must retain A2's native check before any branch payload."""
    request, pin = bound
    request = {
        "fanout": reusable_fanout,
        "families": reusable_families,
        "literature": reusable_literature,
    }[profile](request)
    request = bind_source(request, pin.model_copy(update={"task_data_path_id": "wrong_path"}))
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "failed" and receipt.candidate_request_path is None
    output = Path(receipt.envelope) / "inputs"
    assert not list(output.glob("literature.*.json"))
    assert not list(output.glob("storage.*.json")) and not list(output.glob("proposal*.json"))
    assert "native task composition differs" in (output / "preparation/worker.log").read_text()
