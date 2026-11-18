"""Per-route OpenAI background opt-in must reach exactly its own bridge (#1533)."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools.setup_review.routes import standard_llm_routes
from workflows.llm_config import NodeLLMConfig, WorkflowLLMConfig, parse_llm_config_bytes

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKGROUND = {"completion_window": "8h", "max_wait_seconds": 36000}
ROUTES = (
    "interpret",
    "implement",
    "validate",
    "data_analysis",
    "propose.comparison",
    "propose.reasoning",
    "propose.proposing",
    "tune.planner",
    "tune.reflector",
    "lit_review.main",
    "lit_review.search",
)


def payload_with_background(target: str) -> dict:
    def leaf(name: str) -> dict:
        route = {"provider": "openai", "model_id": f"model-{name}"}
        if name == target:
            route["openai_background"] = BACKGROUND
        return route

    return {
        "interpret": leaf("interpret"),
        "implement": leaf("implement"),
        "validate": leaf("validate"),
        "data_analysis": leaf("data_analysis"),
        "propose": {s: leaf(f"propose.{s}") for s in ("comparison", "reasoning", "proposing")},
        "tune": {"planner": leaf("tune.planner"), "reflector": leaf("tune.reflector")},
        "lit_review": {"main": leaf("lit_review.main"), "search": leaf("lit_review.search")},
    }


def effective_background(route) -> dict | None:
    key = "reflect_transport" if route.name == "tune.reflector" else "transport"
    transport = route.bridge_arguments.get(key)
    return None if transport is None else transport.get("background")


@pytest.mark.parametrize("target", ROUTES)
def test_background_reaches_only_the_opted_in_route(target):
    """Inheritance would silently delay (and discount-route) steps that never opted in."""
    config = WorkflowLLMConfig.model_validate(payload_with_background(target))
    routes = {
        route.name: route
        for route in standard_llm_routes(
            config, literature_enabled=True, analysis_enabled=True, pseudo_llm=False
        )
    }
    assert set(ROUTES) <= set(routes)
    for name in ROUTES:
        expected = BACKGROUND if name == target else None
        assert effective_background(routes[name]) == expected, name
    if target == "tune.planner":
        assert routes["tune.reflector"].shares_client_with is None
    if target == "lit_review.main":
        assert routes["lit_review.search"].shares_client_with is None


@pytest.mark.parametrize("slot", ["implement", "interpret", "validate", "data_analysis"])
def test_background_reaches_real_node_constructors(slot, tmp_path):
    """Node constructors take **kwargs, so an unforwarded carrier would vanish silently."""
    from nodes.data_analysis_agent import DataAnalysisAgent
    from nodes.ml_code_validator_agent import MLCodeValidatorAgent
    from nodes.ml_model_implementor import MLModelImplementor
    from nodes.result_interpretation_agent import ResultInterpretationAgent

    constructors = {
        "implement": MLModelImplementor,
        "interpret": ResultInterpretationAgent,
        "validate": MLCodeValidatorAgent,
        "data_analysis": DataAnalysisAgent,
    }
    config = WorkflowLLMConfig.model_validate(payload_with_background(slot))
    factory = Mock(return_value=Mock())
    extras = {"capability_index_path": str(tmp_path / "index.json")} if slot == "implement" else {}
    if slot == "data_analysis":
        extras["task_analysis_capability"] = Mock()
    node = constructors[slot](**config.get(slot), bridge_factory=factory, **extras)
    if slot == "data_analysis":
        node._bridge()
    transport = factory.call_args.kwargs["transport"]
    assert transport.protocol == "openai-responses"
    assert transport.background.model_dump() == BACKGROUND


def test_proposer_stage_background_reaches_only_its_stage_bridge(tmp_path):
    """The real proposer must build a distinct background bridge for the opted-in stage only."""
    from nodes.ml_model_proposal_agent import MLModelProposalAgent

    captures = {}

    def factory(**kwargs):
        bridge = Mock()
        captures[id(bridge)] = kwargs
        return bridge

    config = WorkflowLLMConfig.model_validate(payload_with_background("propose.proposing"))
    agent = MLModelProposalAgent(
        **config.get("propose"),
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
    )
    stages = {s: captures[id(agent._bridge_for_stage(s))] for s in ("comparison", "proposing")}
    assert "transport" not in stages["comparison"]
    assert stages["proposing"]["transport"].background.completion_window == "8h"
    assert "transport" not in captures[id(agent.bridge)]


@pytest.mark.parametrize(
    "profile", sorted((REPO_ROOT / "configs" / "llm").glob("*.json")), ids=lambda p: p.name
)
def test_existing_profiles_keep_serialization_and_bridge_arguments(profile):
    """Profiles without the setting must keep their bytes and default requests."""
    config = parse_llm_config_bytes(profile.read_bytes())
    assert "openai_background" not in json.dumps(config.model_dump(mode="json", by_alias=True))
    for route in standard_llm_routes(
        config, literature_enabled=True, analysis_enabled=True, pseudo_llm=False
    ):
        assert "transport" not in route.bridge_arguments, route.name
        assert "reflect_transport" not in route.bridge_arguments, route.name


def test_background_is_refused_for_non_openai_routes():
    """The discounted windows exist only on the OpenAI Responses API."""
    with pytest.raises(ValueError, match="openai_background requires provider='openai'"):
        NodeLLMConfig(provider="deepseek", openai_background=BACKGROUND)
    with pytest.raises(ValueError, match="unknown configuration keys"):
        parse_llm_config_bytes(
            json.dumps(
                {"implement": {"openai_background": {**BACKGROUND, "window": "8h"}}}
            ).encode()
        )


def test_data_analysis_fallback_borrows_interpret_route_but_not_its_background():
    """Enabling background on interpret silently gave data analysis multi-hour waits."""
    config = WorkflowLLMConfig.model_validate(
        {"interpret": {**payload_with_background("interpret")["interpret"], "max_retries": 2}}
    )
    options = config.get("data_analysis")
    assert options == {"provider": "openai", "model_id": "model-interpret", "max_retries": 2}
    assert "transport" in config.get("interpret")


def test_literature_fallback_borrows_interpret_route_but_not_its_background():
    """An unconfigured literature main bridge must not inherit interpret's background wait."""
    config = WorkflowLLMConfig.model_validate(
        {"interpret": {**payload_with_background("interpret")["interpret"], "max_retries": 2}}
    )
    assert config.get("lit_review") == {
        "llm_provider": "openai",
        "llm_model_id": "model-interpret",
        "llm_max_retries": 2,
    }
