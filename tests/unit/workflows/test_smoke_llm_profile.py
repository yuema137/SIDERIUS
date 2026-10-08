"""The opt-in smoke profiles must not inherit a costly or foreign model route."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from core.layout import checkout_root
from tools.setup_review.routes import standard_llm_routes
from tools.setup_review.semantic_llm import request_judgement
from tools.setup_review.semantic_models import ReviewSnapshotRequest
from workflows.llm_config import WorkflowLLMConfig


def _profile_path(name: str) -> Path:
    root = checkout_root()
    assert root is not None
    return root / "configs" / "llm" / name


def _mock_provider(monkeypatch, content: dict) -> Mock:
    from agent import llm_bridge

    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))],
        usage=None,
    )
    monkeypatch.setattr(llm_bridge, "OpenAI", Mock(return_value=client))
    monkeypatch.setattr(llm_bridge, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    return client


def test_smoke_routes_reach_only_luna_requests(monkeypatch, tmp_path):
    """Missing slots, reflector routing or dropped effort fail at the SDK edge.

    Existing setup-route tests separately bind this inspection to real node
    factories and workflow forwarding. This test binds the shipped profile to
    those owners and the real gateway; no network request is made.
    """
    from agent.llm_bridge import LLMBridge

    config = WorkflowLLMConfig.from_json(str(_profile_path("openai_smoke_luna.json")))
    assert config.tune is not None
    assert config.tune.planner_strategy == "native-timing-v1"
    routes = standard_llm_routes(
        config, literature_enabled=True, analysis_enabled=True, pseudo_llm=False
    )
    assert {route.name for route in routes} == {
        "interpret",
        "data_analysis",
        "implement",
        "validate",
        "propose.comparison",
        "propose.reasoning",
        "propose.proposing",
        "tune.planner",
        "tune.reflector",
        "lit_review.main",
        "lit_review.search",
    }
    client = _mock_provider(monkeypatch, {"ok": True})
    for route in routes:
        assert route.issue is None
        assert route.transport is not None
        assert route.transport.provider == "openai"
        assert route.transport.model_id == "gpt-6-luna"
        assert route.transport.reasoning_effort == "medium"
        assert route.transport.max_retries == 1
        bridge = LLMBridge(**route.bridge_arguments)
        bridge.set_run_context(
            workspace=tmp_path, iter=0, run_name=route.name, run_id="smoke-profile"
        )
        if route.name == "tune.reflector":
            result = bridge._chat_json(
                bridge.reflect_client,
                bridge.reflect_model_name,
                "Return JSON.",
                "Offline route probe.",
                label="tuner.reflector",
                provider=bridge.reflect_provider,
            )
        else:
            result = bridge.generate("Return JSON.", "Offline route probe.", label=route.name)
        assert result == {"ok": True}
        request = client.chat.completions.create.call_args.kwargs
        assert request["model"] == "gpt-6-luna"
        assert request["reasoning_effort"] == "medium"
        assert request["response_format"] == {"type": "json_object"}
    assert client.chat.completions.create.call_count == 11


def test_smoke_reviewer_uses_its_separate_luna_profile(monkeypatch, tmp_path):
    """The optional reviewer is not governed by workflow routing; bind its edge too."""
    client = _mock_provider(
        monkeypatch, {"summary": "Offline fixture", "findings": [], "uncovered_checks": []}
    )
    operation = ReviewSnapshotRequest(
        kind="review",
        report=tmp_path / "report.json",
        expected_sha256="0" * 64,
        output=tmp_path / "review",
        input_max_bytes=1024,
        llm=json.loads(_profile_path("reviewers/openai_smoke_luna.json").read_text()),
        total_review_seconds=10,
        request_timeout_seconds=5,
    )
    operation.output.mkdir()
    judgement = request_judgement(operation, "Return JSON.", "Offline probe.", "smoke-review")
    assert judgement.summary == "Offline fixture"
    request = client.chat.completions.create.call_args.kwargs
    assert request["model"] == "gpt-6-luna"
    assert request["reasoning_effort"] == "medium"
    assert client.chat.completions.create.call_count == 1
