"""JudgeStop effect boundary: project verified bodies, call the stop judge once, replay it.

The pure evaluator (``loop_stop``) decides; this module only produces its recorded
input. ``call_stop_judge`` is the one place a loop contacts a provider, and
``replay_stop_judge`` re-derives the same verdict from evidence without one. Both
project the request from the same verified body records and read the route from the
run lock, so a replayed request, prompt and route must equal the recorded ones.
"""

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from agent.judge.call import JudgeRunContext, bridge_for_route, run_judge_call
from agent.judge.evidence import JudgeEvidenceError, evidence_sha256, verify_call_evidence
from agent.judge.stop_template import STOP_TEMPLATE
from agent.schemas.judge import (
    CallRequest,
    DirectionWords,
    HealthClass,
    JudgeBodyFacts,
    JudgeCallEvidence,
    JudgeRoute,
    StopJudgeRequest,
    StopVerdict,
)
from core.run_invariants import load_run_invariants
from execute_tools.metric_order import MetricOrder
from workflows.definition.models import AuthoredLoop, JudgeStop
from workflows.llm_config import WorkflowLLMConfig

from .layout import candidate_control_dir
from .loop_stop import (
    BodyScore,
    JudgeBoundaryVerdict,
    JudgeStopError,
    StopConditionError,
    StopEvaluationInput,
    incumbent_fold,
    pending_judge,
)

if TYPE_CHECKING:
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

    from .models import CandidateRunReceipt, CandidateRunRequest

#: Deterministic excerpt bound; equals ``StopJudgeRequest``'s per-excerpt limit.
EXCERPT_CHARS = 2000


def stop_evidence_path(workspace: Path, iteration: int) -> Path:
    """The one write-once JudgeStop evidence slot of a body boundary."""
    return candidate_control_dir(workspace, iteration=iteration) / "judge" / "stop.json"


def admit_judge_route(loop: AuthoredLoop, config: WorkflowLLMConfig) -> None:
    """Refuse a declared judge without its operator route before any body is dispatched."""
    judged = pending_judge(loop.stop_conditions)
    if judged is not None and (config.judge is None or config.judge.stop is None):
        raise StopConditionError(
            f"stop condition {judged[0]} (judge) requires a WorkflowLLMConfig.judge.stop route"
        )


def _locked_stop_route(workspace: str) -> JudgeRoute:
    invariants = load_run_invariants(workspace)
    routes = None if invariants is None else invariants.judge_routes
    if routes is None or routes.stop is None:
        raise StopConditionError("a judge stop condition requires the run lock's judge stop route")
    return routes.stop


def _record(body: "CandidateRunReceipt", node_id: str) -> Path:
    assert body.graph_trace is not None and body.status == "completed"
    path = next(item for item in body.graph_trace.nodes if item.node_id == node_id).record_path
    assert path is not None
    return Path(path)


def _body_health(
    workspace: str, score: BodyScore, tuning: "HyperparamTuningOutput", path: Path
) -> HealthClass:
    """Health of one body as the judge sees it, from the tuner's committed records.

    ``valid`` exactly when the tuner committed a best valid formal score (the same
    field the incumbent folds). Otherwise ``invalid`` only when every formal record
    classifies INVALID under the commit-time policy; anything else (no formal record,
    an UNKNOWN record) is ``unknown``, never upgraded.
    """
    from core.resume import classify_committed_record
    from execute_tools.health_checks.candidate_eligibility import CandidateHealthValidity

    if score.valid_formal is not None:
        return "valid"
    formal = [
        record
        for record in tuning.all_records
        if record.record_type == "experiment" and not record.is_trial
    ]
    validities = {
        classify_committed_record(record, tuning, str(path), workspace).validity
        for record in formal
    }
    return "invalid" if validities == {CandidateHealthValidity.INVALID} else "unknown"


def _body_projection(
    request: "CandidateRunRequest",
    initial: "CandidateRunReceipt",
    body: "CandidateRunReceipt",
    score: BodyScore,
    rank: int | None,
) -> tuple[JudgeBodyFacts, str, str]:
    """Facts, interpretation record digest and bounded excerpt of one verified body."""
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
    from agent.schemas.interpretation import InterpretationOutput
    from workflows.definition.fanout import execution_families

    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    assert shape.interpretation is not None and shape.tuning is not None
    tuning_path = _record(body, shape.tuning)
    tuning = HyperparamTuningOutput.model_validate_json(tuning_path.read_bytes())
    facts = JudgeBodyFacts(
        iteration=score.iteration,
        value=score.valid_formal,
        rank=rank,
        health=_body_health(initial.workspace, score, tuning, tuning_path),
    )
    payload = _record(body, shape.interpretation.interpretation).read_bytes()
    interpretation = InterpretationOutput.model_validate_json(payload)
    return (
        facts,
        hashlib.sha256(payload).hexdigest(),
        interpretation.take_home_message[:EXCERPT_CHARS],
    )


def project_stop_request(
    request: "CandidateRunRequest",
    initial: "CandidateRunReceipt",
    bodies: tuple["CandidateRunReceipt", ...],
    value: StopEvaluationInput,
) -> tuple[CallRequest, int, JudgeStop]:
    """The hashed stop-judge request for a judged boundary, from verified records only."""
    judged = pending_judge(value.conditions)
    assert judged is not None and value.metric is not None
    if tuple(body.status for body in bodies) != ("completed",) * len(value.bodies):
        raise ValueError("judge projection requires the boundary's completed bodies")
    index, condition = judged
    order = MetricOrder(value.metric)
    fold = incumbent_fold(value.bodies, order)
    valid = [score.valid_formal for score in value.bodies if score.valid_formal is not None]
    projected = [
        _body_projection(
            request,
            initial,
            body,
            score,
            None if score.valid_formal is None else order.rank(valid, score.valid_formal),
        )
        for body, score in zip(bodies, value.bodies, strict=True)
    ]
    content = StopJudgeRequest(
        condition_index=index,
        iteration=value.iteration,
        final_iteration=value.final_iteration,
        bodies=tuple(facts for facts, _, _ in projected),
        incumbent=fold.incumbent,
        incumbent_iteration=fold.incumbent_iteration,
        non_improving_bodies=fold.non_improving,
        metric_id=value.metric.id,
        direction_words=DirectionWords.model_validate(order.direction_words),
        interpretation_digests=tuple(digest for _, digest, _ in projected),
        interpretation_excerpts=tuple(excerpt for _, _, excerpt in projected),
        criterion=condition.criterion,
        # judge.stop/v1 renders no task guidance text, so the request claims none.
        task_guidance_sha256=None,
    )
    call = CallRequest(
        invocation_sha256=None, call_role="stop", call_index=0, prior_turns=(), content=content
    )
    return call, index, condition


def _boundary_verdict(
    evidence: JudgeCallEvidence, workspace: str, path: Path, index: int, condition: JudgeStop
) -> JudgeBoundaryVerdict:
    if evidence.status == "decided":
        assert isinstance(evidence.payload, StopVerdict)
        decision = evidence.payload.decision
    elif condition.on_failure == "continue":
        decision = None  # A recorded abstention: deterministic bounds still govern.
    else:
        raise JudgeStopError(
            f"stop condition {index} (judge) failed at body {evidence.request.content.iteration}: "
            f"{evidence.failure_code}: {evidence.failure_message}"
        )
    return JudgeBoundaryVerdict(
        iteration=evidence.request.content.iteration,
        decision=decision,
        evidence_path=str(path.relative_to(workspace)),
        evidence_sha256=evidence_sha256(evidence),
        request_sha256=evidence.request_sha256,
    )


def call_stop_judge(
    request: "CandidateRunRequest",
    initial: "CandidateRunReceipt",
    bodies: tuple["CandidateRunReceipt", ...],
    value: StopEvaluationInput,
) -> JudgeBoundaryVerdict:
    """Make the boundary's one judge call, publish its evidence, return its verdict.

    Raises ``JudgeStopError`` for a failed call under ``on_failure="fail"``; the
    evidence is published first, so the failure stays inspectable.
    """
    call, index, condition = project_stop_request(request, initial, bodies, value)
    path = stop_evidence_path(Path(initial.workspace), value.iteration)
    evidence = run_judge_call(
        call,
        template=STOP_TEMPLATE,
        route=_locked_stop_route(initial.workspace),
        context=JudgeRunContext(
            workspace=Path(initial.workspace),
            iteration=value.iteration,
            run_name=initial.run_name,
            run_id=initial.run_id,
        ),
        evidence_path=path,
        max_calls=1,
        bridge_factory=bridge_for_route,
    )
    return _boundary_verdict(evidence, initial.workspace, path, index, condition)


def replay_stop_judge(
    request: "CandidateRunRequest",
    initial: "CandidateRunReceipt",
    bodies: tuple["CandidateRunReceipt", ...],
    value: StopEvaluationInput,
) -> JudgeBoundaryVerdict:
    """Re-derive a judged boundary's verdict from its evidence; never calls a provider.

    Refuses missing or non-canonical evidence, a request, prompt, response schema or
    route that differs from the re-projection, and a failure recorded under
    ``on_failure="fail"`` (such a loop must have ended ``failed``).
    """
    call, index, condition = project_stop_request(request, initial, bodies, value)
    path = stop_evidence_path(Path(initial.workspace), value.iteration)
    try:
        data = path.read_bytes()
    except FileNotFoundError as error:
        raise ValueError(f"judged boundary {value.iteration} lacks its judge evidence") from error
    try:
        evidence = verify_call_evidence(
            path,
            expected_sha256=hashlib.sha256(data).hexdigest(),
            request=call,
            template=STOP_TEMPLATE,
            route=_locked_stop_route(initial.workspace),
        )
    except JudgeEvidenceError as error:
        raise ValueError(f"judge evidence at body {value.iteration} is refused: {error}") from error
    try:
        return _boundary_verdict(evidence, initial.workspace, path, index, condition)
    except JudgeStopError as error:
        raise ValueError(f"loop continued after a failed judge: {error}") from error
