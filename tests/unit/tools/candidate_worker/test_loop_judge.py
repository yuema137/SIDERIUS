"""JudgeStop through real authored bodies; only the provider, training and tuner are doubled.

The stub bridge is the only judge effect. Each test names the defect its assertions own.
"""

import hashlib
import json
from pathlib import Path

import pytest

from tools.candidate_worker import launch_candidate
from tools.candidate_worker.loop_evidence import verify_loop

from .conftest import refresh
from .test_finite_loop import loop_request, scored_bodies, threshold_for
from .test_finite_loop import loop_tuner as loop_tuner
from .test_graph import initial
from .test_interpretation import interpretation_provider as interpretation_provider
from .test_loop_resume import process_segments as process_segments
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner

ROUTE = {"provider": "openai", "model_id": "judge-test", "max_output_tokens": 400, "max_retries": 1}


def judged_request(prepared, conditions, *, final_iteration, judge=None):
    request = loop_request(prepared, final_iteration=final_iteration, stop_conditions=conditions)
    path = Path(request.preview.project_root) / "llm.json"
    config = json.loads(path.read_text())
    config["judge"] = {"stop": ROUTE, "max_judge_calls": 8} if judge is None else judge
    path.write_text(json.dumps(config))
    return refresh(request)


@pytest.fixture
def judge_bridge(monkeypatch):
    """Record each judge call; answer from ``decisions`` (an exception is raised as-is)."""
    from tools.candidate_worker import loop_judge

    calls, decisions, markers = [], [], []

    class Bridge:
        def __init__(self, route):
            self.route = route

        def set_run_context(self, *, workspace, iter, run_name, run_id):
            self.context = iter

        def generate(self, system, user, *, label):
            calls.append((self.context, label, self.route))
            answer = decisions.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return {
                "kind": "stop_decision",
                "decision": answer,
                "rationale": "the judged criterion",
                "confidence": "medium",
            }

        def emit_marker(self, *, label, extra=None):
            markers.append((self.context, label, extra))

    monkeypatch.setattr(loop_judge, "bridge_for_route", Bridge)
    return calls, decisions, markers


def evidence(workspace, iteration):
    control = Path(workspace) / "candidate_run"
    return (
        control if iteration == 1 else control / f"iteration_{iteration:03d}"
    ) / "judge/stop.json"


def test_judge_stop_completes_with_an_anchored_reason_and_replays_without_a_call(
    prepared, loop_tuner, judge_bridge, monkeypatch
):
    """Fails if the judge is called before min_completed_bodies, if a stop verdict does
    not complete the loop with its exact evidence reason, or if readback re-calls the
    provider or accepts missing, tampered, orphan or foreign-route evidence."""
    from agent.schemas.data_analysis.common import canonical_json_bytes
    from agent.schemas.judge import JudgeCallEvidence
    from tools.candidate_worker.loop_stop import JudgeStopReason
    from workflows.definition import JudgeStop

    calls, decisions, _ = judge_bridge
    decisions.extend(["stop"])
    request = judged_request(
        prepared, (JudgeStop(criterion="plateau", min_completed_bodies=2),), final_iteration=4
    )
    _, _, (low, high) = threshold_for(prepared)
    scored_bodies(monkeypatch, (low, high, low, low))
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    assert receipt.loop_trace.attempted_iterations == 2
    assert [(v.iteration, v.decision) for v in receipt.loop_trace.judge_verdicts] == [(2, "stop")]
    assert [(iteration, label) for iteration, label, _ in calls] == [(2, "judge.stop")]
    path = evidence(receipt.workspace, 2)
    reason = receipt.loop_trace.stop_reason
    assert isinstance(reason, JudgeStopReason)
    assert (reason.condition_index, reason.iteration) == (0, 2)
    assert reason.evidence_path == "candidate_run/iteration_002/judge/stop.json"
    assert reason.evidence_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    recorded = json.loads(path.read_bytes())
    # The judge sees the deterministic core's facts: both bodies valid, ranked by MetricOrder.
    facts = recorded["request"]["content"]["bodies"]
    assert [(item["value"], item["rank"], item["health"]) for item in facts] == [
        (low, 2, "valid"),
        (high, 1, "valid"),
    ]
    assert recorded["request"]["content"]["incumbent_iteration"] == 2
    assert recorded["route"]["model_id"] == "judge-test"
    assert not evidence(receipt.workspace, 1).exists()

    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    assert len(verify_loop(request, parent, receipt)) == 2
    assert len(calls) == 1  # readback never calls the provider

    original = path.read_bytes()
    tampered = json.loads(original)
    tampered["payload"]["rationale"] = "rewritten after the fact"
    path.write_bytes(
        canonical_json_bytes(JudgeCallEvidence.model_validate_json(json.dumps(tampered)))
    )
    # Canonical bytes replay, but the trace's evidence digest anchors the stop verdict.
    with pytest.raises(ValueError, match="stop reason disagrees"):
        verify_loop(request, parent, receipt)
    path.unlink()
    with pytest.raises(ValueError, match="lacks its judge evidence"):
        verify_loop(request, parent, receipt)
    path.write_bytes(original)
    orphan = evidence(receipt.workspace, 1)
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(original)
    with pytest.raises(ValueError, match="not accounted for by replay"):
        verify_loop(request, parent, receipt)
    orphan.unlink()
    lock = Path(receipt.workspace) / "run_invariants_lock.json"
    locked = json.loads(lock.read_text())
    locked["judge_routes"]["stop"]["model_id"] = "another-judge"
    lock.write_text(json.dumps(locked))
    with pytest.raises(ValueError, match="route differs"):
        verify_loop(request, parent, receipt)


def test_a_deterministic_stop_never_calls_the_judge(
    prepared, loop_tuner, judge_bridge, monkeypatch
):
    """Fails if the judge runs where a metric condition already decided: a provider call
    is spent and a judge declared first could veto the metric stop."""
    from workflows.definition import JudgeStop, MetricThresholdStop

    calls, _, markers = judge_bridge
    metric, threshold, (low, high) = threshold_for(prepared)
    request = judged_request(
        prepared,
        (
            JudgeStop(criterion="plateau"),
            MetricThresholdStop(metric_id=metric.id, threshold=threshold),
        ),
        final_iteration=3,
    )
    scored_bodies(monkeypatch, (high, low, low))
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    assert receipt.loop_trace.stop_reason.kind == "metric_threshold"
    assert receipt.loop_trace.stop_reason.condition_index == 1
    assert calls == [] and not evidence(receipt.workspace, 1).exists()
    # The pre-empted judge call is still visible in the usage ledger as a marker row.
    assert markers == [
        (
            1,
            "judge.stop.skipped",
            {
                "reason": "deterministic_stop",
                "judge_condition_index": 0,
                "deciding_condition_index": 1,
            },
        )
    ]
    verify_loop(request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt)


def test_continue_verdicts_run_to_the_limit_without_judging_the_final_body(
    prepared, loop_tuner, judge_bridge, monkeypatch
):
    """Fails if the final boundary (owned by the final limit) is judged, a continue
    verdict leaves a reason, replay does not reconstruct each boundary's verdict, or a
    continue verdict's evidence is not anchored (an edited rationale would pass)."""
    from agent.schemas.data_analysis.common import canonical_json_bytes
    from agent.schemas.judge import JudgeCallEvidence
    from workflows.definition import JudgeStop

    calls, decisions, _ = judge_bridge
    decisions.extend(["continue", "continue"])
    _, _, (low, _) = threshold_for(prepared)
    request = judged_request(prepared, (JudgeStop(criterion="plateau"),), final_iteration=3)
    scored_bodies(monkeypatch, (low, low, low))
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    trace = receipt.loop_trace
    assert trace.stop_reason is None and trace.judge_abstentions == 0
    assert [(item.iteration, item.decision) for item in trace.judge_verdicts] == [
        (1, "continue"),
        (2, "continue"),
    ]
    assert [item.evidence_sha256 for item in trace.judge_verdicts] == [
        hashlib.sha256(evidence(receipt.workspace, i).read_bytes()).hexdigest() for i in (1, 2)
    ]
    assert [iteration for iteration, _, _ in calls] == [1, 2]
    assert not evidence(receipt.workspace, 3).exists()
    # Replay reconstructs every boundary's verdict exactly (multi-boundary readback).
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    verify_loop(request, parent, receipt)
    assert len(calls) == 2

    # An edited continue rationale replays canonically, but its anchored digest refuses it.
    path = evidence(receipt.workspace, 1)
    original = path.read_bytes()
    tampered = json.loads(original)
    tampered["payload"]["rationale"] = "rewritten after the fact"
    path.write_bytes(
        canonical_json_bytes(JudgeCallEvidence.model_validate_json(json.dumps(tampered)))
    )
    with pytest.raises(ValueError, match="judge verdicts disagree"):
        verify_loop(request, parent, receipt)
    path.write_bytes(original)
    verify_loop(request, parent, receipt)

    # A lock whose cap is below the recorded calls refuses (two calls, cap one).
    lock = Path(receipt.workspace) / "run_invariants_lock.json"
    locked = lock.read_text()
    capped = json.loads(locked)
    capped["judge_routes"]["max_judge_calls"] = 1
    lock.write_text(json.dumps(capped))
    with pytest.raises(ValueError, match="exceed the run's cap"):
        verify_loop(request, parent, receipt)
    lock.write_text(locked)

    # Evidence no replayed verdict accounts for refuses, past the scored range too.
    for planted in (evidence(receipt.workspace, 9), path.parent / "extra.json"):
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_bytes(original)
        with pytest.raises(ValueError, match="not accounted for by replay"):
            verify_loop(request, parent, receipt)
        planted.unlink()


def test_planted_judge_evidence_in_a_judge_free_loop_is_refused(prepared, loop_tuner, monkeypatch):
    """Fails if readback skips the judge-evidence scan for loops without a judge."""
    request = loop_request(prepared, final_iteration=2)
    _, _, (low, _) = threshold_for(prepared)
    scored_bodies(monkeypatch, (low, low))
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    verify_loop(request, parent, receipt)
    planted = evidence(receipt.workspace, 1)
    planted.parent.mkdir(parents=True)
    planted.write_text("{}")
    with pytest.raises(ValueError, match="not accounted for by replay"):
        verify_loop(request, parent, receipt)


@pytest.mark.parametrize("on_failure", ["fail", "continue"])
def test_a_failed_judge_call_fails_the_loop_or_is_a_recorded_abstention(
    prepared, loop_tuner, judge_bridge, monkeypatch, on_failure
):
    """Fails if a declared judge failure is silently ignored under "fail", or if an
    abstention under "continue" stops the loop or loses its failure evidence."""
    from workflows.definition import JudgeStop

    calls, decisions, _ = judge_bridge
    decisions.extend([RuntimeError("provider down"), "continue"])
    request = judged_request(
        prepared, (JudgeStop(criterion="plateau", on_failure=on_failure),), final_iteration=3
    )
    _, _, (low, _) = threshold_for(prepared)
    scored_bodies(monkeypatch, (low, low, low))
    receipt = launch_candidate(request)
    recorded = json.loads(evidence(receipt.workspace, 1).read_bytes())
    assert (recorded["status"], recorded["failure_code"]) == ("failed", "provider_error")
    if on_failure == "fail":
        assert receipt.status == "failed"
        assert "stop condition 0 (judge) failed at body 1" in receipt.error
        assert not (Path(receipt.workspace) / "candidate_run/iteration_002").exists()
        return
    assert receipt.status == "completed", receipt.error
    assert receipt.loop_trace.attempted_iterations == 3
    # The readback summary counts the abstention; its failed record is anchored too.
    assert receipt.loop_trace.judge_abstentions == 1
    assert [item.decision for item in receipt.loop_trace.judge_verdicts] == [None, "continue"]
    assert [iteration for iteration, _, _ in calls] == [1, 2]
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    verify_loop(request, parent, receipt)
    # The same evidence replayed under on_failure="fail" refuses: a fail-policy judge
    # failure can only end a loop failed, never let it continue.
    from tools.candidate_worker.loop_evidence import derive_stop, replay_completed

    loop = request.preview.document.definition.loop
    failing = request.model_copy(
        update={
            "preview": request.preview.model_copy(
                update={
                    "document": request.preview.document.model_copy(
                        update={
                            "definition": request.preview.document.definition.model_copy(
                                update={
                                    "loop": loop.model_copy(
                                        update={
                                            "stop_conditions": (
                                                JudgeStop(criterion="plateau", on_failure="fail"),
                                            )
                                        }
                                    )
                                }
                            )
                        }
                    )
                }
            )
        }
    )
    _, bodies, scores = replay_completed(request, parent, 3)
    with pytest.raises(ValueError, match="loop continued after a failed judge"):
        derive_stop(failing, parent, bodies, scores)


@pytest.mark.parametrize(
    ("judge", "refusal"),
    [
        ({"aggregate": ROUTE, "max_judge_calls": 8}, "requires a WorkflowLLMConfig.judge.stop"),
        ({"stop": ROUTE}, "requires WorkflowLLMConfig.judge.max_judge_calls"),
        # final 4, min 1: three judgeable boundaries do not fit a cap of two (Q-B2-10).
        ({"stop": ROUTE, "max_judge_calls": 2}, "may make 3 judge calls; max_judge_calls is 2"),
    ],
)
def test_an_unroutable_or_uncapped_judge_is_refused_before_any_body(
    prepared, loop_tuner, judge_bridge, monkeypatch, judge, refusal
):
    """Fails if a judged loop dispatches bodies before discovering it has no route, no
    run-level call cap, or a static call bound above that cap."""
    from workflows.definition import JudgeStop

    request = judged_request(
        prepared, (JudgeStop(criterion="plateau"),), final_iteration=4, judge=judge
    )
    dispatched = []
    _, _, (low, _) = threshold_for(prepared)
    scored_bodies(monkeypatch, (low,) * 4, on_body=dispatched.append)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert refusal in receipt.error
    assert dispatched == []


def test_continue_leaves_a_pending_pause_in_force_and_resume_never_rejudges(
    prepared, loop_tuner, interpretation_provider, process_segments, monkeypatch, tmp_path
):
    """Fails if a continue verdict swallows a pending Pause, if the continuation judges
    the paused boundary again (write-once evidence would refuse it), or if the judge
    request of the resumed segment loses the bodies of the first segment."""
    from uuid import uuid4

    from tools.candidate_operations import (
        CandidateLoopResumeOperation,
        CandidateLoopResumeRequest,
        CandidateOperation,
        OperationStoreConfig,
        read_operation,
        request_loop_pause,
        review_loop_resume,
        submit_operation,
    )
    from tools.candidate_worker import loop_judge, training
    from tools.candidate_worker.models import CandidateRunReceipt
    from workflows.definition import JudgeStop

    class Bridge:
        def __init__(self, route):
            pass

        def set_run_context(self, *, workspace, iter, run_name, run_id):
            self.iteration = iter

        def generate(self, system, user, *, label):
            decision = {1: "continue", 2: "stop"}[self.iteration]
            return {
                "kind": "stop_decision",
                "decision": decision,
                "rationale": "r",
                "confidence": "low",
            }

        def emit_marker(self, *, label, extra=None):
            pass

    monkeypatch.setattr(loop_judge, "bridge_for_route", Bridge)
    request = judged_request(prepared, (JudgeStop(criterion="plateau"),), final_iteration=3)
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    env = {"OPENAI_API_KEY": "offline-stub"}
    root_id, next_id = uuid4(), uuid4()
    real_tune = training.HyperparamTuningAgent.run

    def pause_in_first(self, value):
        output = real_tune(self, value)
        if "iteration_001" in value.storage.local.workspace:
            request_loop_pause(config, root_id)
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause_in_first)
    submit_operation(
        config, CandidateOperation(request_id=root_id, request=request), launch_environment=env
    )
    process_segments()
    paused = read_operation(config, root_id).receipt
    assert paused.status == "paused" and paused.loop_trace.attempted_iterations == 1
    assert [item.decision for item in paused.loop_trace.judge_verdicts] == ["continue"]
    first = evidence(paused.workspace, 1).read_bytes()
    assert json.loads(first)["payload"]["decision"] == "continue"
    review = review_loop_resume(config, root_id)
    submit_operation(
        config,
        CandidateLoopResumeOperation(
            request_id=next_id,
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=root_id, expected_receipt_digest=review.receipt_digest
            ),
        ),
        launch_environment=env,
    )
    process_segments()
    resumed = read_operation(config, next_id).receipt
    assert resumed.status == "completed", resumed
    assert resumed.loop_trace.attempted_iterations == 2
    assert resumed.loop_trace.stop_reason.kind == "judge"
    assert resumed.loop_trace.stop_reason.iteration == 2
    # The continuation carries the predecessor's anchored verdict forward.
    assert [(item.iteration, item.decision) for item in resumed.loop_trace.judge_verdicts] == [
        (1, "continue"),
        (2, "stop"),
    ]
    assert evidence(resumed.workspace, 1).read_bytes() == first
    second = json.loads(evidence(resumed.workspace, 2).read_bytes())
    assert [item["iteration"] for item in second["request"]["content"]["bodies"]] == [1, 2]
    root = Path(resumed.workspace) / "candidate_run"
    launched = CandidateRunReceipt.model_validate_json((root / "launch.json").read_bytes())
    assert len(verify_loop(request, launched, resumed)) == 2


def _tuning_with(*records):
    from tests.unit.workflows.test_model_exploration import _make_tuning_output

    return _make_tuning_output(model_type="wavenet").model_copy(
        update={"best_valid_formal_denoising_score": None, "all_records": list(records)}
    )


def _record(exp_id, *, is_trial, status):
    from agent.schemas.hyperparam_tuning import ExperimentMemory, ExperimentRecord

    return ExperimentRecord(
        exp_id=exp_id,
        status=status,
        model_type="wavenet",
        timestamp="2026-10-28T00:00:00Z",
        params={},
        denoising_score=0.5,
        is_trial=is_trial,
        trial_portion=0.1 if is_trial else None,
        memory=ExperimentMemory(expert_advice_followed="n/a", hypothesis="n/a", round_index=1),
    )


@pytest.mark.parametrize(
    ("records", "expected"),
    [
        # No Formal record is not evidence of invalidity (a trial-only body included).
        ((), "unknown"),
        ((("t1", True, "error"),), "unknown"),
        # Every Formal record failed: provably invalid.
        ((("f1", False, "error"), ("f2", False, "error")), "invalid"),
        # One Formal record whose validity cannot be established keeps the body unknown.
        ((("f1", False, "error"), ("f2", False, "success")), "unknown"),
    ],
)
def test_body_health_is_invalid_only_when_every_formal_record_is_invalid(
    tmp_path, records, expected
):
    """Fails if a body without Formal evidence is reported ``invalid`` to the judge, or a
    body whose Formal records all failed is reported ``unknown``."""
    from tools.candidate_worker.loop_judge import _body_health
    from tools.candidate_worker.loop_stop import BodyScore

    tuning = _tuning_with(
        *(_record(exp_id, is_trial=trial, status=status) for exp_id, trial, status in records)
    )
    score = BodyScore(iteration=1, valid_formal=None, metric_spec=None)
    path = tmp_path / "run_output.json"
    assert _body_health(str(tmp_path), score, tuning, path) == expected
