"""Judge call/evidence core: one bounded effect, replay without a provider."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from agent.judge.call import (
    JudgeCallRefused,
    JudgeEvidenceConflict,
    JudgeRunContext,
    run_judge_call,
)
from agent.judge.evidence import (
    JudgeEvidenceError,
    chain_prior_turns,
    evidence_sha256,
    verify_call_chain,
    verify_call_evidence,
)
from agent.judge.stop_template import STOP_TEMPLATE
from agent.schemas.data_analysis.common import canonical_json_bytes, canonical_sha256
from agent.schemas.judge import (
    CallRequest,
    DirectionWords,
    JudgeBodyFacts,
    JudgeCallEvidence,
    JudgeRoute,
    StopJudgeRequest,
)
from core.execution_deadline import ExecutionDeadlineExceeded, execution_deadline

_SRC = Path(__file__).resolve().parents[4] / "src"
ROUTE = JudgeRoute(
    provider="openai",
    model_id="judge-fixture",
    reasoning_effort=None,
    max_output_tokens=512,
    max_retries=2,
)
VERDICT = {
    "kind": "stop_decision",
    "decision": "stop",
    "rationale": "Two bodies without improvement.",
    "confidence": "medium",
}


def stop_content(**overrides) -> StopJudgeRequest:
    fields = {
        "condition_index": 1,
        "iteration": 3,
        "final_iteration": 5,
        "bodies": (
            JudgeBodyFacts(iteration=1, value=0.5, rank=2, health="valid"),
            JudgeBodyFacts(iteration=2, value=None, rank=None, health="unknown"),
            JudgeBodyFacts(iteration=3, value=0.25, rank=1, health="valid"),
        ),
        "incumbent": 0.25,
        "incumbent_iteration": 3,
        "non_improving_bodies": 0,
        "metric_id": "metric-fixture",
        "direction_words": DirectionWords(verb="minimize", comparative="lower", antonym="higher"),
        "interpretation_digests": ("a" * 64,),
        "interpretation_excerpts": ("loss plateaued",),
        "criterion": "Stop when further bodies are unlikely to help.",
        "task_guidance_sha256": None,
    }
    return StopJudgeRequest(**{**fields, **overrides})


def stop_request() -> CallRequest:
    return CallRequest(
        invocation_sha256=None,
        call_role="stop",
        call_index=0,
        prior_turns=(),
        content=stop_content(),
    )


class StubBridge:
    def __init__(self, result: object = VERDICT) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str]] = []
        self.contexts: list[dict] = []

    def set_run_context(self, **kwargs) -> None:
        self.contexts.append(kwargs)

    def generate(self, system_prompt: str, user_prompt: str, *, label: str):
        self.calls.append((system_prompt, user_prompt, label))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def run(tmp_path: Path, bridge: StubBridge, *, template=STOP_TEMPLATE, max_calls=4, iteration=3):
    return run_judge_call(
        stop_request(),
        template=template,
        route=ROUTE,
        context=JudgeRunContext(
            workspace=tmp_path, iteration=iteration, run_name="r", run_id="run-1"
        ),
        evidence_path=tmp_path / "judge" / "0.json",
        max_calls=max_calls,
        bridge_factory=lambda _route: bridge,
    )


def replay(tmp_path: Path, recorded: JudgeCallEvidence, template=STOP_TEMPLATE):
    return verify_call_evidence(
        tmp_path / "judge" / "0.json",
        expected_sha256=evidence_sha256(recorded),
        request=stop_request(),
        template=template,
        route=ROUTE,
    )


def test_stop_prompt_bytes_are_pinned_for_a_fixed_request():
    """Defect: rendering drifts (key order, clock, template edit) without a version bump."""
    assert canonical_sha256(stop_request()) == (
        "f9f4864d8ca9b5674bef2b96a8b47eb4e7e39da8acab106d6417b5bb5a8ec4c9"
    )
    identity = STOP_TEMPLATE.identity(stop_request())
    assert identity.template_sha256 == (
        "7dcdc035d67dd519b24d80190f4991b2046680d9957baf6b95c068d90e89a038"
    )
    assert identity.prompt_sha256 == (
        "0a1a9877a01eaf9cdfc35fb1e35e02638a604bed4c5cb74211828e07d373a302"
    )
    # Pydantic's JSON-schema output is part of the template version.
    assert identity.response_schema_sha256 == (
        "ba9971349c7096dbfbc356beddb080b967f0ed23f33e779125bfb8424a4da0c2"
    )
    _, user = STOP_TEMPLATE.render(stop_request())
    assert "minimize it; lower values are better and higher values are worse" in user


def test_replay_rebuilds_the_recorded_outcome(tmp_path):
    """Defect: readback rebuilds a different outcome than the recorded call.

    That readback cannot reach a provider is owned by the AST import guard below.
    """
    bridge = StubBridge()
    recorded = run(tmp_path, bridge)
    assert recorded.status == "decided" and len(bridge.calls) == 1
    assert bridge.contexts == [
        {"workspace": tmp_path, "iter": 3, "run_name": "r", "run_id": "run-1"}
    ]
    assert replay(tmp_path, recorded) == recorded


def _rewrite(path: Path, update) -> str:
    """Rewrite a self-consistent record (an attacker recomputing every digest)."""
    data = json.loads(path.read_bytes())
    update(data)
    data["request_sha256"] = canonical_sha256(data["request"])
    evidence = JudgeCallEvidence.model_validate_json(json.dumps(data))
    path.unlink()
    path.write_bytes(canonical_json_bytes(evidence))
    return evidence_sha256(evidence)


@pytest.mark.parametrize(
    ("update", "message"),
    [
        (lambda d: d["request"]["content"].update(criterion="other"), "request differs"),
        (lambda d: d["prompt"].update(response_schema_sha256="b" * 64), "prompt or response"),
        (lambda d: d["route"].update(model_id="other-model"), "route differs"),
    ],
    ids=["request", "schema_digest", "route"],
)
def test_consistent_but_foreign_evidence_is_refused(tmp_path, update, message):
    """Defect: a record that hashes correctly is accepted for different inputs."""
    path = tmp_path / "judge" / "0.json"
    run(tmp_path, StubBridge())
    digest = _rewrite(path, update)
    with pytest.raises(JudgeEvidenceError, match=message):
        verify_call_evidence(
            path,
            expected_sha256=digest,
            request=stop_request(),
            template=STOP_TEMPLATE,
            route=ROUTE,
        )


def test_payload_edit_is_refused_by_the_anchoring_digest(tmp_path):
    """Defect: a flipped verdict replays because only inputs are compared."""
    recorded = run(tmp_path, StubBridge())
    path = tmp_path / "judge" / "0.json"
    path.write_bytes(path.read_bytes().replace(b'"decision":"stop"', b'"decision":"continue"'))
    with pytest.raises(JudgeEvidenceError, match="digest mismatch"):
        verify_call_evidence(
            path,
            expected_sha256=evidence_sha256(recorded),
            request=stop_request(),
            template=STOP_TEMPLATE,
            route=ROUTE,
        )


def _chained(evidence: JudgeCallEvidence, earlier: list[JudgeCallEvidence]):
    """A later chain call; no multi-call content kind exists yet, so copy unvalidated."""
    request = evidence.request.model_copy(
        update={"call_index": len(earlier), "prior_turns": chain_prior_turns(earlier)}
    )
    return evidence.model_copy(update={"request": request})


def test_reordered_call_chain_is_refused(tmp_path):
    """Defect: chained calls can be dropped, spliced or reordered undetected."""
    first = run(tmp_path, StubBridge())
    second = _chained(first, [first])
    verify_call_chain([first, second])
    with pytest.raises(JudgeEvidenceError, match="call_index"):
        verify_call_chain([second, first])
    with pytest.raises(JudgeEvidenceError, match="earlier calls"):
        verify_call_chain([first, _chained(first, [second])])


@pytest.mark.parametrize(
    ("result", "status", "code"),
    [
        ({**VERDICT, "decision": "maybe"}, "failed", "invalid_payload"),
        ({**VERDICT, "score": 1.0}, "failed", "invalid_payload"),
        ("stop", "failed", "invalid_payload"),
        ([VERDICT], "failed", "invalid_payload"),
        (ValueError("not JSON after retries"), "failed", "provider_error"),
        (ExecutionDeadlineExceeded("judge"), "timed_out", "deadline"),
    ],
    ids=["bad_value", "extra_key", "string", "array", "provider", "deadline"],
)
def test_failed_calls_are_published_and_replayable(tmp_path, result, status, code):
    """Defect: an invalid or failed call is used, lost, or not inspectable."""
    recorded = run(tmp_path, StubBridge(result))
    assert (recorded.status, recorded.failure_code, recorded.payload) == (status, code, None)
    assert replay(tmp_path, recorded) == recorded


def test_inadmissible_payload_is_recorded_not_used(tmp_path):
    """Defect: a schema-valid choice outside the request's admissible set is accepted."""
    checked = replace(
        STOP_TEMPLATE,
        check_payload=lambda request, payload: (
            "stop not allowed" if request.content.iteration < 4 else None
        ),
    )
    recorded = run(tmp_path, StubBridge(), template=checked)
    assert (recorded.status, recorded.failure_code, recorded.failure_message) == (
        "failed",
        "inadmissible_choice",
        "stop not allowed",
    )
    assert replay(tmp_path, recorded, checked) == recorded


def _broken_factory(_route):
    raise KeyError("OPENAI_API_KEY")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_calls": 0}, "positive max_calls"),
        ({"iteration": 2}, "usage context iteration"),
    ],
    ids=["cap", "context_iteration"],
)
def test_admission_refuses_before_any_call(tmp_path, kwargs, message):
    """Defect: an uncapped or misattributed call reaches the provider."""
    bridge = StubBridge()
    with pytest.raises(JudgeCallRefused, match=message):
        run(tmp_path, bridge, **kwargs)
    assert not bridge.calls and not (tmp_path / "judge").exists()


def test_existing_evidence_and_unavailable_bridge_refuse_without_a_call(tmp_path):
    """Defect: old evidence is reused, or a setup failure escapes untyped."""
    with pytest.raises(JudgeCallRefused, match="bridge unavailable: KeyError") as raised:
        run_judge_call(
            stop_request(),
            template=STOP_TEMPLATE,
            route=ROUTE,
            context=JudgeRunContext(workspace=tmp_path, iteration=3, run_name="r", run_id="x"),
            evidence_path=tmp_path / "judge" / "0.json",
            max_calls=1,
            bridge_factory=_broken_factory,
        )
    assert isinstance(raised.value.__cause__, KeyError)
    assert not (tmp_path / "judge").exists()
    bridge = StubBridge()
    run(tmp_path, bridge)
    with pytest.raises(JudgeCallRefused, match="already exists"):
        run(tmp_path, bridge)
    assert len(bridge.calls) == 1


def test_usage_row_carries_the_judge_label_and_run_id(tmp_path, monkeypatch):
    """Defect: judge tokens bypass LLMBridge usage accounting or lose attribution."""
    monkeypatch.setattr("agent.llm_bridge.load_dotenv", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture")
    client = Mock(timeout=httpx.Timeout(600))
    client.chat.completions.create.return_value = SimpleNamespace(
        model="served-fixture",
        usage=SimpleNamespace(prompt_tokens=17, completion_tokens=9, total_tokens=26),
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(VERDICT), tool_calls=None))
        ],
    )
    monkeypatch.setattr("agent.llm_bridge.OpenAI", Mock(return_value=client))
    recorded = run_judge_call(
        stop_request(),
        template=STOP_TEMPLATE,
        route=ROUTE,
        context=JudgeRunContext(workspace=tmp_path, iteration=3, run_name="r", run_id="run-1"),
        evidence_path=tmp_path / "judge" / "0.json",
        max_calls=1,
    )
    assert recorded.status == "decided"
    rows = [json.loads(line) for line in (tmp_path / "token_usage.jsonl").read_text().splitlines()]
    judged = [row for row in rows if row["label"] == "judge.stop"]
    assert len(judged) == 1 and judged[0]["run_id"] == "run-1"
    assert judged[0]["model"] == "judge-fixture"


def test_readback_modules_never_import_the_bridge():
    """Defect: verification gains a path to a provider call."""
    for name in ("evidence.py", "template.py", "stop_template.py"):
        tree = ast.parse((_SRC / "agent" / "judge" / name).read_text())
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
        }
        assert not {m for m in imported if m and "llm_bridge" in m}, name


def test_a_health_invalid_body_cannot_present_a_metric_value():
    """Defect: the judge is shown an INVALID/UNKNOWN body's value as a usable score."""
    with pytest.raises(ValueError, match="Health-valid"):
        JudgeBodyFacts(iteration=1, value=0.1, rank=1, health="invalid")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"final_iteration": 3}, "final boundary is never judged"),
        ({"incumbent": 0.5, "incumbent_iteration": 1}, "rank-1 body"),
        ({"non_improving_bodies": 4}, "cannot exceed"),
        (
            {"interpretation_digests": ("a" * 64,) * 4, "interpretation_excerpts": ("x",) * 4},
            "one interpretation excerpt per",
        ),
    ],
    ids=["final_boundary_Q_B2_6", "incumbent_not_rank_1", "non_improving", "excerpts"],
)
def test_stop_request_refuses_incoherent_facts(overrides, message):
    """Defect: the judge sees a final-boundary call or facts the core could not produce."""
    with pytest.raises(ValueError, match=message):
        stop_content(**overrides)


def _refuse_all(_request, _payload):
    return "stop not allowed"


def test_replay_refuses_a_decided_payload_the_check_now_refuses(tmp_path):
    """Defect: replay accepts a decided choice that is inadmissible for its request."""
    recorded = run(tmp_path, StubBridge())
    assert recorded.status == "decided"
    with pytest.raises(JudgeEvidenceError, match="inadmissible"):
        replay(tmp_path, recorded, replace(STOP_TEMPLATE, check_payload=_refuse_all))


def _raising_check(_request, _payload):
    raise KeyError("unknown item")


def test_a_raising_payload_check_is_recorded_as_inadmissible(tmp_path):
    """Defect: a crashing admissibility check escapes without evidence of the paid call."""
    checked = replace(STOP_TEMPLATE, check_payload=_raising_check)
    recorded = run(tmp_path, StubBridge(), template=checked)
    assert (recorded.status, recorded.failure_code) == ("failed", "inadmissible_choice")
    assert recorded.failure_message == "KeyError: 'unknown item'"


def test_an_expired_deadline_propagates_unchanged_without_evidence(tmp_path, monkeypatch):
    """Defect: a deadline is disguised as a refusal, so callers misclassify it."""
    now = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: now[0])
    bridge = StubBridge()
    with execution_deadline(1.0):
        now[0] = 2.0
        with pytest.raises(ExecutionDeadlineExceeded):
            run(tmp_path, bridge)
    assert not bridge.calls and not (tmp_path / "judge").exists()


def test_a_stop_call_cannot_extend_a_chain():
    """Defect: a stop judgement is chained onto earlier calls and judged twice."""
    with pytest.raises(ValueError, match="single call"):
        CallRequest(
            invocation_sha256=None,
            call_role="stop",
            call_index=1,
            prior_turns=("a" * 64,),
            content=stop_content(),
        )


class RacingBridge(StubBridge):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def generate(self, system_prompt: str, user_prompt: str, *, label: str):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"{}")
        return super().generate(system_prompt, user_prompt, label=label)


def test_a_concurrent_publish_raises_a_typed_conflict(tmp_path):
    """Defect: a second writer's record is overwritten or the race surfaces untyped."""
    path = tmp_path / "judge" / "0.json"
    with pytest.raises(JudgeEvidenceConflict):
        run(tmp_path, RacingBridge(path))
    assert path.read_bytes() == b"{}"
