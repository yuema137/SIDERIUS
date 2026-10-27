"""Optional routes must survive workflow projection and reach node bridges."""

from unittest.mock import Mock

import pytest

from agent.llm_settings import resolve_main_transport, resolve_reflect_transport
from nodes.llm_settings import literature_bridge_arguments
from nodes.proposer_routing import ProposerRoute, resolve_proposer_routing
from nodes.tuner_llm_settings import tuner_bridge_kwargs
from tools.setup_review.routes import node_llm_routes
from workflows.llm_config import NodeLLMConfig, WorkflowLLMConfig


@pytest.mark.parametrize("provider", ["anthropic", "moonshot", "zai"])
def test_new_routes_resolve_explicit_models_and_review_credentials(provider):
    """A valid JSON route must not be rejected by setup review as an unknown provider."""
    config = WorkflowLLMConfig.model_validate(
        {
            "implement": {
                "provider": provider,
                "model_id": "fixture-model",
                "max_output_tokens": 12000,
            }
        }
    )
    route = node_llm_routes(config, "implement")[0]
    assert route.issue is None
    assert route.transport.provider == provider
    assert route.bridge_arguments["max_output_tokens"] == 12000
    with pytest.raises(ValueError, match="explicit model_id"):
        NodeLLMConfig(provider=provider)
    with pytest.raises(ValueError, match="explicit model_id"):
        resolve_main_transport(provider=provider)


def test_old_route_serialization_omits_new_field():
    """Adding an unused token option must not change existing configuration hashes."""
    assert NodeLLMConfig(provider="openai", model_id="fixture").model_dump() == {
        "provider": "openai",
        "model_id": "fixture",
        "reasoning_effort": None,
    }


@pytest.mark.parametrize("slot", ["implement", "interpret", "validate", "data_analysis"])
def test_workflow_output_limit_reaches_real_node_constructor(slot, tmp_path):
    """Flat workflow options used to be silently swallowed by node **kwargs."""
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
    config = WorkflowLLMConfig.model_validate(
        {slot: {"provider": "anthropic", "model_id": "fixture", "max_output_tokens": 14000}}
    )
    factory = Mock(return_value=Mock())
    extras = {"capability_index_path": str(tmp_path / "index.json")} if slot == "implement" else {}
    if slot == "data_analysis":
        extras["task_analysis_capability"] = Mock()
    node = constructors[slot](**config.get(slot), bridge_factory=factory, **extras)
    if slot == "data_analysis":
        node._bridge()
    assert factory.call_args.kwargs["max_output_tokens"] == 14000
    assert factory.call_args.kwargs["provider"] == "anthropic"


def test_proposer_stage_token_limit_does_not_bleed_into_other_stages():
    """An omitted comparison cap must not inherit reasoning's independently configured cap."""
    config = WorkflowLLMConfig.model_validate(
        {
            "propose": {
                "comparison": {"provider": "openai", "model_id": "a"},
                "reasoning": {"provider": "anthropic", "model_id": "b", "max_output_tokens": 15000},
                "proposing": {"provider": "moonshot", "model_id": "c", "max_output_tokens": 9000},
            }
        }
    )
    routes = node_llm_routes(config, "propose")
    by_name = {r.name: r.bridge_arguments for r in routes}
    assert "max_output_tokens" not in by_name["propose.comparison"]
    assert by_name["propose.reasoning"]["max_output_tokens"] == 15000
    assert by_name["propose.proposing"]["max_output_tokens"] == 9000


def test_independent_tuner_and_literature_output_limits():
    """Both multi-client routes must retain their independently selected limits."""
    config = WorkflowLLMConfig.model_validate(
        {
            "tune": {
                "planner": {"provider": "anthropic", "model_id": "a", "max_output_tokens": 20000},
                "reflector": {"provider": "moonshot", "model_id": "b", "max_output_tokens": 4000},
            },
            "lit_review": {
                "main": {"provider": "anthropic", "model_id": "a", "max_output_tokens": 16000},
                "search": {"provider": "zai", "model_id": "c", "max_output_tokens": 3000},
            },
        }
    )
    planner, reflector = node_llm_routes(config, "tune")
    assert planner.bridge_arguments["max_output_tokens"] == 20000
    assert reflector.bridge_arguments["reflect_max_output_tokens"] == 4000
    main, search = node_llm_routes(config, "lit_review")
    assert main.bridge_arguments["max_output_tokens"] == 16000
    assert search.bridge_arguments["max_output_tokens"] == 3000


def test_cross_provider_reflector_requires_its_own_model():
    """A new provider must never accidentally inherit another vendor's model ID."""
    main = resolve_main_transport(provider="openai", model_id="old-model")
    with pytest.raises(ValueError, match="explicit reflect_model_id"):
        resolve_reflect_transport(main, provider="anthropic")


def test_new_provider_launch_requires_its_own_named_credentials():
    """Provider schema acceptance alone must not bypass launch credential checks."""
    from tools.candidate_worker.preflight import credential_requirements
    from tools.setup_review.environment import credential_name_checks

    config = WorkflowLLMConfig.model_validate(
        {"implement": {"provider": "anthropic", "model_id": "fixture"}}
    )
    routes = node_llm_routes(config, "implement")
    checks = credential_name_checks(
        routes, requested=True, environment={"OPENAI_API_KEY": "foreign"}
    )
    assert [(c.name, c.status) for c in checks] == [("ANTHROPIC_API_KEY", "missing")]
    required = credential_requirements(tuple(routes), ("OPENAI_API_KEY",))
    assert required.required_names == ("ANTHROPIC_API_KEY",)
    assert required.omitted_names == ("ANTHROPIC_API_KEY",)
    assert required.unresolved_routes == ()


def test_uniform_reflector_does_not_fabricate_cross_vendor_model():
    """The shorthand must not bypass explicit-model validation through fallback."""
    with pytest.raises(ValueError, match="explicit reflect_model_id"):
        WorkflowLLMConfig.uniform("openai", "fixture", reflect_provider="anthropic")
