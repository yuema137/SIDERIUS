"""End clean paused tails through Stop without rewriting their scientific evidence."""

from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_operations import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    CandidateOperation,
    OperationStoreConfig,
    loop_control_requests,
    read_operation,
    request_loop_pause,
    request_loop_stop,
    review_loop_resume,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_worker.models import CandidateRunReceipt
from workflows.definition import NoImprovementStop

from .test_finite_loop import loop_request
from .test_finite_loop import loop_tuner as loop_tuner
from .test_interpretation import interpretation_provider as interpretation_provider
from .test_loop_resume import process_segments as process_segments
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner


@pytest.mark.parametrize("pause_kind", ["operator", "condition", "resumed", "occupied_next"])
def test_stop_ends_paused_tail_without_changing_receipts(
    prepared,
    loop_tuner,
    interpretation_provider,
    process_segments,
    monkeypatch,
    tmp_path,
    pause_kind,
):
    """Old Stop rejects each paused tail. Guard regressions permit stale Resume or
    ending a historical predecessor; receipt rewrites break the byte comparison.
    """
    from tools.candidate_worker import training

    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    root_id, next_id = uuid4(), uuid4()
    real_tune = training.HyperparamTuningAgent.run

    def pause(self, value):
        result = real_tune(self, value)
        if pause_kind != "condition":
            for slot, operation_id in (("iteration_001", root_id), ("iteration_002", next_id)):
                if slot in value.storage.local.workspace:
                    request_loop_pause(config, operation_id)
        return result

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause)
    request = loop_request(
        prepared,
        final_iteration=4,
        stop_conditions=(NoImprovementStop(completed_bodies=1, on_met="request_input"),)
        if pause_kind == "condition"
        else (),
    )
    env = {"OPENAI_API_KEY": "offline-stub"}
    submit_operation(
        config, CandidateOperation(request_id=root_id, request=request), launch_environment=env
    )
    process_segments()
    selected = root_id
    if pause_kind == "resumed":
        review = review_loop_resume(config, root_id)
        assert review.receipt_digest is not None
        submit_operation(
            config,
            CandidateLoopResumeOperation(
                request_id=next_id,
                request=CandidateLoopResumeRequest(
                    predecessor_operation_id=root_id,
                    expected_receipt_digest=review.receipt_digest,
                ),
            ),
            launch_environment=env,
        )
        process_segments()
        with pytest.raises(OperationFailure) as refused:
            request_loop_stop(config, root_id)
        assert refused.value.detail.code == "loop_end"
        assert refused.value.detail.message == (
            "this segment has a successor; open the successor to Stop it, "
            "or use End loop there if it is paused"
        )
        selected = next_id

    review = review_loop_resume(config, selected)
    assert isinstance(review.receipt, CandidateRunReceipt)
    assert review.receipt.status == "paused" and review.receipt_digest is not None
    root = Path(review.receipt.workspace) / "candidate_run"
    if pause_kind == "occupied_next":
        # Completed evidence stays valid even when a future slot blocks Resume.
        (root / "iteration_002").mkdir()
        (root / "iteration_002" / "partial.txt").write_text("unfinished")
        with pytest.raises(OperationFailure, match="next iteration slot"):
            review_loop_resume(config, selected)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    # End uses its own refusal code and wording while supervision is uncertain.
    supervision_path = root / (
        f"continuations/{selected}/supervision.json"
        if pause_kind == "resumed"
        else "supervision.json"
    )
    supervision = supervision_path.read_bytes()
    supervision_path.unlink()
    with pytest.raises(OperationFailure) as refused:
        request_loop_stop(config, selected)
    assert refused.value.detail.code == "loop_end"
    assert refused.value.detail.message == "paused segment lacks clean supervision"
    with pytest.raises(OperationFailure) as resume_refusal:
        review_loop_resume(config, selected)
    assert resume_refusal.value.detail.code == "loop_resume"
    assert resume_refusal.value.detail.message == "paused segment lacks clean supervision"
    supervision_path.write_bytes(supervision)
    marker = request_loop_stop(config, selected)
    assert request_loop_stop(config, selected) == marker, "Stop retries are idempotent"
    assert loop_control_requests(config, selected)[0]
    ended = read_operation(config, selected)
    assert ended.receipt == review.receipt and ended.receipt_digest == review.receipt_digest
    assert {path: path.read_bytes() for path in before} == before
    assert set(path for path in root.rglob("*") if path.is_file()) == set(before) | {
        root / "stop.json"
    }
    with pytest.raises(OperationFailure, match="terminal"):
        review_loop_resume(config, selected)
    # A review obtained before End cannot admit a successor after Stop wins the lock.
    with pytest.raises(OperationFailure, match="terminal"):
        submit_operation(
            config,
            CandidateLoopResumeOperation(
                request_id=uuid4(),
                request=CandidateLoopResumeRequest(
                    predecessor_operation_id=selected,
                    expected_receipt_digest=review.receipt_digest,
                ),
            ),
            launch_environment=env,
        )
