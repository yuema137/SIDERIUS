"""Pause evidence projection, compatibility and operator CLI reachability."""

import json
from uuid import uuid4

import pytest

from tools.candidate_operations import __main__ as cli
from tools.candidate_operations.models import (
    OperationSnapshot,
    OperationStoreConfig,
    ProcessObservation,
)
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.loop_evidence import summarize_tried_bodies, verify_loop
from tools.candidate_worker.loop_stop import InputRequestSummary, project_body_score
from workflows.definition import NoImprovementStop

from .test_finite_loop import loop_request, scored_bodies, threshold_for
from .test_finite_loop import loop_tuner as loop_tuner
from .test_graph import initial
from .test_interpretation import interpretation_provider as interpretation_provider
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner


@pytest.mark.parametrize("no_valid_score", [False, True])
def test_two_body_pause_projects_verified_attempts_and_cli(
    prepared, loop_tuner, interpretation_provider, monkeypatch, tmp_path, capsys, no_valid_score
):
    """Missing/swapped proposal, score or validation facts fail the literal projection;
    edited summaries must refuse, and CLI review must carry the same list."""
    metric, _, (low, high) = threshold_for(prepared)
    from tools.candidate_worker import training

    request = loop_request(
        prepared,
        final_iteration=4,
        stop_conditions=(
            NoImprovementStop(completed_bodies=2 if no_valid_score else 1, on_met="request_input"),
        ),
    )
    if no_valid_score:
        high = low = None
    scored_bodies(monkeypatch, (high, low))
    real = training.HyperparamTuningAgent.run

    def terminated(self, value):
        output = real(self, value)
        return (
            output.model_copy(update={"termination_reason": "aborted_fail_rounds"})
            if no_valid_score
            else output
        )

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", terminated)
    receipt = launch_candidate(request)
    assert receipt.status == "paused", receipt.error
    asked = receipt.loop_trace.input_request
    expected = [
        dict(
            iteration=i,
            model_name=f"worker_linear_{i}",
            validation_passed=True,
            best_valid_score=score,
            metric_id=metric.id,
            direction=metric.direction,
            stop_reason="aborted_fail_rounds" if no_valid_score else None,
        )
        for i, score in enumerate((high, low), 1)
    ]
    assert asked.summary.model_dump(mode="json")["what_was_tried"] == expected
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    bodies = verify_loop(request, parent, receipt)
    assert len(bodies) == 2
    forged = asked.model_copy(
        update={
            "summary": asked.summary.model_copy(
                update={
                    "what_was_tried": (
                        asked.summary.what_was_tried[0].model_copy(update={"model_name": "forged"}),
                        asked.summary.what_was_tried[1],
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="input request disagrees"):
        verify_loop(
            request,
            parent,
            receipt.model_copy(
                update={
                    "loop_trace": receipt.loop_trace.model_copy(update={"input_request": forged})
                }
            ),
        )
    legacy = asked.model_copy(
        update={"summary": asked.summary.model_copy(update={"what_was_tried": ()})}
    )
    assert (
        len(
            verify_loop(
                request,
                parent,
                receipt.model_copy(
                    update={
                        "loop_trace": receipt.loop_trace.model_copy(
                            update={"input_request": legacy}
                        )
                    }
                ),
            )
        )
        == 2
    )

    # The projection's bound and segment slice apply before reading records: old bodies
    # are excluded, including bodies before an operator Pause (not an input anchor).
    scores = tuple(project_body_score(request, bodies[0], i) for i in range(1, 24))
    bounded = summarize_tried_bodies(request, (bodies[0],) * 23, scores, asked, resumed_at=0)
    assert [item.iteration for item in bounded.summary.what_was_tried] == list(range(4, 24))
    segment = summarize_tried_bodies(request, (bodies[0],) * 23, scores, asked, resumed_at=21)
    assert [item.iteration for item in segment.summary.what_was_tried] == [22, 23]

    operation_id = uuid4()
    snapshot = OperationSnapshot(
        operation_id=operation_id,
        kind="candidate",
        request_digest="a" * 64,
        observed_at="fixture",
        state="completed",
        process=ProcessObservation(status="exited", reason="fixture"),
        reason="fixture",
        receipt_available=True,
        receipt_digest="b" * 64,
        receipt=receipt,
    )
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    path = tmp_path / "store.json"
    path.write_text(config.model_dump_json())
    monkeypatch.setattr(cli, "review_loop_resume", lambda *_: snapshot)
    monkeypatch.setattr(
        "sys.argv",
        [
            "operations",
            "review-loop-resume",
            "--store-config",
            str(path),
            "--operation-id",
            str(operation_id),
        ],
    )
    capsys.readouterr()
    assert cli.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["receipt"]["loop_trace"]["input_request"]["summary"]["what_was_tried"] == expected


def test_empty_projection_preserves_old_summary_bytes():
    """Adding the default field must not change existing serialized bytes/digests."""
    old = (
        '{"iteration":2,"final_iteration":4,"metric_id":"loss","direction":"lower",'
        '"incumbent":0.4,"incumbent_iteration":1,"non_improving_bodies":1,'
        '"input_anchor":0,"bodies_since_input":2}'
    )
    parsed = InputRequestSummary.model_validate_json(old)
    assert parsed.model_dump_json() == old
    explicit = InputRequestSummary(**json.loads(old), what_was_tried=())
    assert explicit.model_dump_json() == old
