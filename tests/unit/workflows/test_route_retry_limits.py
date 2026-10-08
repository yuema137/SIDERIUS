"""Declared route limits reach real node bridges and network-attempt decisions."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from agent.llm_bridge import LLMBridge
from agent.schemas.literature_review import LiteratureReviewInput
from nodes.ml_literature_review import MLLiteratureReviewAgent
from tools.setup_review.routes import standard_llm_routes
from workflows.llm_config import WorkflowLLMConfig


@pytest.fixture
def provider(monkeypatch):
    clients = []

    def construct(**kwargs):
        client = Mock()
        clients.append(client)
        return client

    monkeypatch.setattr("agent.llm_bridge.OpenAI", construct)
    monkeypatch.setattr("agent.llm_bridge.load_dotenv", lambda: None)
    monkeypatch.setattr("agent.llm_bridge.deadline_sleep", lambda *args: None)
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "offline-fixture")
    return clients


def routes(config):
    return {
        item.name: item
        for item in standard_llm_routes(
            config, literature_enabled=True, analysis_enabled=False, pseudo_llm=False
        )
    }


def failure(kind):
    request = httpx.Request("POST", "https://example.invalid/v1")
    if kind == "timeout":
        return APITimeoutError(request=request)
    if kind == "connection":
        return APIConnectionError(request=request)
    return APIStatusError("fixture", response=httpx.Response(kind, request=request), body=None)


def count_requests(bridge, *, label, limit, kind=429):
    client = bridge.reflect_client if label == "tuner.reflector" else bridge.client
    create = client.chat.completions.create
    create.reset_mock()
    create.side_effect = failure(kind)
    with pytest.raises((APIStatusError, APIConnectionError)):
        bridge._chat_json(client, "fixture", "system", "user", label=label)
    expected = 1 if kind in (400, 401) else max(1, limit)
    assert create.call_count == expected


@pytest.mark.parametrize("planner_limit,reflector_limit", [(2, 1), (1, 2), (0, 1)])
@pytest.mark.parametrize("reflect_provider", ["openai", "gemini"])
@pytest.mark.parametrize("kind", [429, 503, "timeout", "connection", 400, 401])
def test_reflector_limits_are_independent_at_request_edge(
    provider, planner_limit, reflector_limit, reflect_provider, kind
):
    config = WorkflowLLMConfig.model_validate(
        {
            "tune": {
                "planner": {
                    "provider": "openai",
                    "model_id": "planner",
                    "max_retries": planner_limit,
                },
                "reflector": {
                    "provider": reflect_provider,
                    "model_id": "reflector",
                    "max_retries": reflector_limit,
                },
            }
        }
    )
    displayed = routes(config)
    bridge = LLMBridge(**displayed["tune.planner"].bridge_arguments)
    count_requests(bridge, label="tuner.planner", limit=planner_limit, kind=kind)
    count_requests(bridge, label="tuner.reflector", limit=reflector_limit, kind=kind)
    # Reflector calls must not mutate the planner's shared transport policy.
    assert bridge.max_retries == planner_limit
    assert displayed["tune.reflector"].transport.max_retries == reflector_limit


@pytest.mark.parametrize("reflector,expected", [({}, 1), ({"max_retries": None}, 3)])
def test_reflector_omission_inherits_but_explicit_null_is_unbounded(provider, reflector, expected):
    config = WorkflowLLMConfig.model_validate(
        {
            "tune": {
                "planner": {"provider": "openai", "max_retries": 1},
                "reflector": {"provider": "openai", **reflector},
            }
        }
    )
    report = routes(config)
    bridge = LLMBridge(**report["tune.planner"].bridge_arguments)
    create = bridge.reflect_client.chat.completions.create
    create.side_effect = [
        failure(429),
        failure(503),
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))], usage=None
        ),
    ]
    if expected == 1:
        with pytest.raises(APIStatusError):
            bridge._chat_json(
                bridge.reflect_client, "fixture", "system", "user", label="tuner.reflector"
            )
    else:
        assert bridge._chat_json(
            bridge.reflect_client, "fixture", "system", "user", label="tuner.reflector"
        ) == {"ok": True}
    assert create.call_count == expected
    assert report["tune.reflector"].transport.max_retries == (None if reflector else 1)


@pytest.mark.parametrize("main_limit,search_limit", [(1, 2), (2, 1), (0, 1)])
@pytest.mark.parametrize("same_model", [True, False])
def test_literature_actual_node_bridges_honor_both_limits(
    provider, tmp_path, main_limit, search_limit, same_model
):
    config = WorkflowLLMConfig.model_validate(
        {
            "lit_review": {
                "main": {"provider": "openai", "model_id": "main", "max_retries": main_limit},
                "search": {
                    "provider": "openai",
                    "model_id": "main" if same_model else "search",
                    "max_retries": search_limit,
                },
            }
        }
    )
    inp = LiteratureReviewInput(
        interpretation_evidence={},
        root_papers=[{"source_type": "local", "identifier": "fixture.txt"}],
        storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "fixture"}},
        run_name="fixture",
        **config.get("lit_review"),
    )
    # JSON transport must retain an explicit null/finite override as a typed value.
    inp = LiteratureReviewInput.model_validate_json(inp.model_dump_json())
    agent = MLLiteratureReviewAgent(root_cache_dir=str(tmp_path))
    agent._resolve_root_paper = Mock(side_effect=RuntimeError("stop before paper IO"))
    with pytest.raises(RuntimeError, match="stop before paper IO"):
        agent.run(inp)
    report = routes(config)
    for bridge, stage, limit in (
        (agent.bridge, "main", main_limit),
        (agent.search_bridge, "search", search_limit),
    ):
        count_requests(bridge, label="literature." + stage, limit=limit)
        assert report["lit_review." + stage].transport.max_retries == limit
    assert agent.bridge is not agent.search_bridge


def test_omitted_settings_preserve_prior_constructor_arguments(provider):
    config = WorkflowLLMConfig.model_validate({"tune": {}, "lit_review": {}})
    report = routes(config)
    assert "reflect_retry_policy" not in report["tune.planner"].bridge_arguments
    for name in ("tune.planner", "tune.reflector", "lit_review.main", "lit_review.search"):
        assert report[name].transport.max_retries is None
    assert "max_retries" not in report["lit_review.main"].bridge_arguments
    assert "max_retries" not in report["lit_review.search"].bridge_arguments


def test_search_retry_override_alone_splits_client_and_preserves_null(provider, tmp_path):
    from agent.schemas.llm_retry import RetryPolicy
    from nodes.llm_settings import literature_bridge_arguments

    common = dict(
        provider="openai",
        model_id="same",
        reasoning_effort=None,
        search_provider=None,
        search_model_id=None,
        search_reasoning_effort=None,
        max_retries=1,
    )
    inherited = literature_bridge_arguments(**common)
    assert inherited.search is None
    explicit = literature_bridge_arguments(
        **common, search_retry_policy=RetryPolicy(max_retries=None)
    )
    assert explicit.main["max_retries"] == 1
    assert explicit.search is not None
    bridge = LLMBridge(**explicit.search)
    assert bridge.max_retries is None
