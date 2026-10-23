"""Two B1 envelopes through actual detached operations, native sandbox and fake provider."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from tests.integration.tools.test_candidate_operations import wait_for
from tests.integration.tools.test_candidate_operations_native import cli, native_submitter
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_operations import build_reusable_operation, read_operation
from tools.candidate_operations.models import OperationStoreConfig
from tools.candidate_operations.process import environment
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import load_record
from tools.candidate_prepare import prepare_reusable_candidate, select_reusable_preparation

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


def test_two_captures_execute_isolated_native_candidates_and_retry_without_capture(
    reusable, tmp_path
):
    """Only provider responses are fake; preparation, detached dispatch and CPU validation are real."""
    reusable = reusable.model_copy(
        update={
            "candidate_environment_names": ("EXPLICIT_TEST_KEY", "OPENAI_API_KEY"),
        }
    )
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(reusable.runs_root,),
        candidate_roots=(reusable.runs_root,),
    )
    config_path = tmp_path / "store.json"
    config_path.write_text(config.model_dump_json())
    original = Path(reusable.source_path).read_bytes()
    submissions = []
    for request in (reusable, reusable.model_copy(update={"run_id": uuid4()})):
        prepared = prepare_reusable_candidate(request)
        assert prepared.status == "prepared", prepared.error
        selected = select_reusable_preparation(prepared.envelope)
        operation = build_reusable_operation(config, selected, uuid4())
        submissions.append((prepared, operation))
    assert Path(reusable.source_path).read_bytes() == original
    # An ordinary edit affects future preparations, never either retained selection.
    Path(reusable.source_path).write_text("# future source\n")
    native_ids = []
    outputs = []
    for number, (prepared, operation) in enumerate(submissions):
        envelope = Path(prepared.envelope)
        inputs = envelope / "inputs"
        harness = native_submitter(tmp_path, inputs)
        submission_path = tmp_path / f"candidate-{number}.json"
        submission_path.write_text(operation.model_dump_json())
        source_env = {
            **environment((), {}),
            "EXPLICIT_TEST_KEY": "bound-value",
            "OPENAI_API_KEY": "offline-test-key",
            "UNRELATED_SENTINEL": "do-not-pass",
        }
        admitted = json.loads(
            cli(
                config_path,
                "submit",
                "--request",
                str(submission_path),
                harness=harness,
                env=source_env,
            ).stdout
        )
        assert admitted["observation"] == "starting"
        wait_for(lambda operation=operation: releasable(config, operation.request_id), timeout=90)
        snapshot = read_operation(config, operation.request_id)
        receipt = snapshot.receipt
        assert snapshot.state == "completed" and receipt.status == "accepted", snapshot
        assert receipt.node_ids == ("hypothesis", "build", "check")
        record = load_record(config, operation.request_id)
        assert record.submission == operation
        assert record.native_id.hex == receipt.run_id
        assert record.native_id != operation.request_id and receipt.run_id != prepared.run_id.hex
        native_ids.append(receipt.run_id)
        proposal_dir = (
            envelope / "workspace" / operation.request.run_name / "iteration_001/attempt_001"
        )
        proposal = json.loads((inputs / "proposal.json").read_bytes())
        storage = json.loads((inputs / "storage.json").read_bytes())
        assert proposal["storage"]["local"]["workspace"] == str(proposal_dir)
        assert storage["local"]["workspace"] == str(proposal_dir / "impl_001")
        assert proposal["allowed_output_types"] == ["classifier"]
        assert proposal["expert_context"][0]["content"] == "Prefer a small interpretable baseline"
        assert operation.request.implementation_advice == "Keep diagnostics explicit"
        assert operation.request.validation_advice == "Inspect held-out residuals"
        assert (envelope / "workflow.py.snapshot").read_bytes() == original
        assert len(receipt.native_output_paths) == 3
        for path in receipt.native_output_paths:
            assert Path(path).is_file() and Path(path).is_relative_to(proposal_dir)
        validation = json.loads(Path(receipt.native_output_paths[-1]).read_bytes())
        assert (
            validation["tests_passed"]
            and validation["instantiation_passed"]
            and validation["gradient_check_passed"]
        )
        assert list((proposal_dir / "impl_001").rglob("*.py"))
        outputs.append(receipt.native_output_paths)
    # Retry is evidence recovery after lost response, even if the selected envelope vanished.
    for number, (prepared, operation) in enumerate(submissions):
        # Remove it from the selected path while preserving actual output evidence.
        Path(prepared.envelope).rename(tmp_path / f"native-evidence-{number}")
        submission_path = tmp_path / f"candidate-{number}.json"
        repeated = json.loads(cli(config_path, "submit", "--request", str(submission_path)).stdout)
        assert repeated["observation"] == "existing"
        assert load_record(config, operation.request_id).native_id.hex == native_ids[number]
    assert native_ids[0] != native_ids[1]
    assert set(outputs[0]).isdisjoint(outputs[1])
