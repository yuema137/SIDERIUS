"""Judge call/evidence core: one bounded effect, replay without a provider."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from agent.judge.call import JudgeCallRefused, JudgeRunContext, run_judge_call
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
from core.execution_deadline import ExecutionDeadlineExceeded

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


def stop_request(*, call_index: int = 0, prior_turns: tuple[str, ...] = ()) -> CallRequest:
    return CallRequest(
        invocation_sha256=None,
        call_role="stop",
        call_index=call_index,
        prior_turns=prior_turns,
        stop=StopJudgeRequest(
            condition_index=1,
            iteration=3,
            final_iteration=5,
            bodies=(
                JudgeBodyFacts(iteration=1, value=0.5, rank=2, health="valid"),
                JudgeBodyFacts(iteration=2, value=None, rank=None, health="unknown"),
                JudgeBodyFacts(iteration=3, value=0.25, rank=1, health="valid"),
            ),
            incumbent=0.25,
            incumbent_iteration=3,
            non_improving_bodies=0,
            metric_id="metric-fixture",
            direction_words=DirectionWords(verb="minimize", comparative="lower", antonym="higher"),
            interpretation_digests=("a" * 64,),
            interpretation_excerpts=("loss plateaued",),
            criterion="Stop when further bodies are unlikely to help.",
            task_guidance_sha256=None,
        ),
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


def run(tmp_path: Path, bridge: StubBridge, request: CallRequest | None = None, name="0.json"):
    return run_judge_call(
        request or stop_request(),
        template=STOP_TEMPLATE,
        route=ROUTE,
        context=JudgeRunContext(workspace=tmp_path, iteration=3, run_name="r", run_id="run-1"),
        evidence_path=tmp_path / "judge" / name,
        max_calls=4,
        bridge_factory=lambda _route: bridge,
    )


def test_stop_prompt_bytes_are_pinned_for_a_fixed_request():
    """Defect: rendering drifts (key order, clock, template edit) without a version bump."""
    identity = STOP_TEMPLATE.identity(stop_request())
    assert identity.template_sha256 == (
        "7dcdc035d67dd519b24d80190f4991b2046680d9957baf6b95c068d90e89a038"
    )
    assert identity.prompt_sha256 == (
        "cb0c52c75e2c96fc9904337f54b736ca2769f6033b5dbbd757489fbe60a068ec"
    )
    _, user = STOP_TEMPLATE.render(stop_request())
    assert "minimize it; lower values are better and higher values are worse" in user


def test_replay_reproduces_the_run_without_calling_a_provider(tmp_path, monkeypatch):
    """Defect: readback re-calls the LLM or rebuilds a different outcome."""
    bridge = StubBridge()
    recorded = run(tmp_path, bridge)
    assert recorded.status == "decided" and len(bridge.calls) == 1
    assert bridge.contexts == [
        {"workspace": tmp_path, "iter": 3, "run_name": "r", "run_id": "run-1"}
    ]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("replay called a provider")

    monkeypatch.setattr("agent.llm_bridge.LLMBridge.generate", forbidden)
    replayed = verify_call_evidence(
        tmp_path / "judge" / "0.json",
        expected_sha256=evidence_sha256(recorded),
        request=stop_request(),
        template=STOP_TEMPLATE,
        route=ROUTE,
    )
    assert replayed == recorded
    assert len(bridge.calls) == 1


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
        (lambda d: d["request"]["stop"].update(criterion="other"), "request differs"),
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


def test_reordered_call_chain_is_refused(tmp_path):
    """Defect: chained calls can be dropped, spliced or reordered undetected."""
    first = run(tmp_path, StubBridge(), name="0.json")
    second = run(
        tmp_path,
        StubBridge(),
        stop_request(call_index=1, prior_turns=chain_prior_turns([first])),
        name="1.json",
    )
    verify_call_chain([first, second])
    with pytest.raises(JudgeEvidenceError):
        verify_call_chain([second, first])


@pytest.mark.parametrize(
    ("result", "status", "code"),
    [
        ({**VERDICT, "decision": "maybe"}, "failed", "invalid_payload"),
        ({**VERDICT, "score": 1.0}, "failed", "invalid_payload"),
        (ValueError("not JSON after retries"), "failed", "provider_error"),
        (ExecutionDeadlineExceeded("judge"), "timed_out", "deadline"),
    ],
    ids=["bad_value", "extra_key", "provider", "deadline"],
)
def test_failed_calls_are_published_and_replayable(tmp_path, result, status, code):
    """Defect: an invalid or failed call is used, lost, or not inspectable."""
    recorded = run(tmp_path, StubBridge(result))
    assert (recorded.status, recorded.failure_code, recorded.payload) == (status, code, None)
    replayed = verify_call_evidence(
        tmp_path / "judge" / "0.json",
        expected_sha256=evidence_sha256(recorded),
        request=stop_request(),
        template=STOP_TEMPLATE,
        route=ROUTE,
    )
    assert replayed == recorded


def test_cap_and_existing_evidence_refuse_before_any_call(tmp_path):
    """Defect: a call exceeds its declared cap or silently reuses old evidence."""
    bridge = StubBridge()
    over_cap = stop_request(call_index=4, prior_turns=("c" * 64,) * 4)
    with pytest.raises(JudgeCallRefused, match="exceeds the declared cap"):
        run(tmp_path, bridge, over_cap)
    assert not (tmp_path / "judge").exists()
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
