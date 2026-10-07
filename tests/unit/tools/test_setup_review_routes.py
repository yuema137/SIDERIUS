"""Static route reports match real node factories without provider requests."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.layout import checkout_root
from nodes.tuner_llm_settings import tuner_bridge_arguments
from tools.setup_review.environment import credential_name_checks
from tools.setup_review.routes import _route, standard_llm_routes
from workflows.llm_config import WorkflowLLMConfig, resolve_standard_tuner_llm_options


def route_map(payload, **options):
    return {
        route.name: route
        for route in standard_llm_routes(
            WorkflowLLMConfig.model_validate(payload),
            literature_enabled=options.get("literature_enabled", True),
            analysis_enabled=options.get("analysis_enabled"),
            pseudo_llm=options.get("pseudo_llm", False),
        )
    }


@pytest.mark.parametrize("slot", ["interpret", "implement", "validate", "data_analysis"])
@pytest.mark.parametrize(
    "setting",
    [
        None,
        {},
        {"provider": "openai", "model_id": "fixture", "max_retries": 0, "reasoning_effort": "high"},
    ],
)
def test_actual_node_factory_arguments(tmp_path, slot, setting):
    from nodes.data_analysis_agent import DataAnalysisAgent
    from nodes.ml_code_validator_agent import MLCodeValidatorAgent
    from nodes.ml_model_implementor import MLModelImplementor
    from nodes.result_interpretation_agent import ResultInterpretationAgent

    constructors = {
        "interpret": ResultInterpretationAgent,
        "implement": MLModelImplementor,
        "validate": MLCodeValidatorAgent,
        "data_analysis": DataAnalysisAgent,
    }
    payload = {} if setting is None else {slot: setting}
    factory = Mock()
    extra = {}
    if slot == "implement":
        extra["capability_index_path"] = str(tmp_path / "index.json")
    elif slot == "data_analysis":
        extra["task_analysis_capability"] = Mock()
    agent = constructors[slot](
        **WorkflowLLMConfig.model_validate(payload).get(slot), bridge_factory=factory, **extra
    )
    if slot == "data_analysis":
        agent._bridge()
    assert route_map(payload)[slot].bridge_arguments == factory.call_args.kwargs


def test_three_proposer_routes_match_actual_stage_factories(tmp_path):
    from nodes.ml_model_proposal_agent import MLModelProposalAgent

    payload = {
        "propose": {
            "comparison": {"provider": "deepseek", "model_id": "comparison", "max_retries": 0},
            "reasoning": {
                "provider": "openai",
                "model_id": "reasoning",
                "reasoning_effort": "high",
                "max_retries": 7,
            },
            "proposing": {"provider": "gemini", "model_id": "proposing", "max_retries": None},
        }
    }
    captures = {}

    def factory(**kwargs):
        bridge = Mock()
        captures[id(bridge)] = kwargs
        return bridge

    agent = MLModelProposalAgent(
        **WorkflowLLMConfig.model_validate(payload).get("propose"),
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
    )
    routes = route_map(payload)
    for stage in ("comparison", "reasoning", "proposing"):
        assert (
            routes[f"propose.{stage}"].bridge_arguments
            == captures[id(agent._bridge_for_stage(stage))]
        )
    shared = route_map({})
    assert shared["propose.comparison"].shares_client_with == "propose.reasoning"
    assert shared["propose.proposing"].shares_client_with == "propose.reasoning"


def test_shared_proposer_client_does_not_assume_comparison_runs_first(tmp_path):
    from nodes.ml_model_proposal_agent import MLModelProposalAgent

    shared = {"provider": "openai", "model_id": "shared"}
    payload = {
        "propose": {
            "comparison": shared,
            "proposing": shared,
            "reasoning": {"provider": "gemini", "model_id": "different"},
        }
    }
    factory = Mock(side_effect=lambda **kwargs: Mock())
    agent = MLModelProposalAgent(
        **WorkflowLLMConfig.model_validate(payload).get("propose"),
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
    )
    proposing = agent._bridge_for_stage("proposing")
    assert agent._bridge_for_stage("comparison") is proposing
    assert proposing is not agent.bridge
    assert factory.call_count == 2
    routes = route_map(payload)
    assert routes["propose.proposing"].shares_client_with == "propose.comparison"
    assert routes["propose.reasoning"].shares_client_with is None


@pytest.mark.parametrize("planner_retries", [None, 0, 6])
@pytest.mark.parametrize("reflect_provider", ["openai", "gemini"])
def test_actual_workflow_tuner_forwarding_and_protocol(tmp_path, planner_retries, reflect_provider):
    """Evaluate real forwarding expressions, then run the real typed protocol.

    This isolates the LLM edge; it does not claim to run a workflow or task.
    A deleted/changed workflow keyword fails independently of the report helper.
    """
    from agent.schemas.hyperparam_tuning import ExpertAdvice
    from agent.schemas.proposal import ProposalOutput
    from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from agent.schemas.validator import ValidatorOutput

    payload = {
        "tune": {
            "planner": {
                "provider": "openai",
                "model_id": "planner",
                "reasoning_effort": "high",
                "max_retries": planner_retries,
            },
            "reflector": {"provider": reflect_provider, "model_id": "reflector", "max_retries": 19},
        }
    }
    options = resolve_standard_tuner_llm_options(
        WorkflowLLMConfig.model_validate(payload).get("tune")
    )
    root = checkout_root()
    assert root is not None
    tree = ast.parse((root / "src/workflows/model_exploration.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "local_validated_model"
    ]
    assert len(calls) == 1
    fields = {
        "llm_provider",
        "llm_model_id",
        "reflect_provider",
        "reflect_model_id",
        "max_retries",
        "reasoning_effort",
        "reflect_reasoning_effort",
    }
    forwarded = {
        keyword.arg: eval(
            compile(ast.Expression(keyword.value), "<actual-workflow-forwarding>", "eval"),
            {"tune_llm": options},
        )
        for keyword in calls[0].keywords
        if keyword.arg in fields
    }
    assert set(forwarded) == fields
    validator = ValidatorOutput(
        passed=True,
        model_type="synthetic",
        plugin_registered=True,
        tests_passed=True,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=True,
        gradient_check_passed=True,
        llm_review_passed=True,
    )
    proposal = ProposalOutput(
        model_name="synthetic",
        model_description="Synthetic model",
        mathematical_definition="y = Wx",
        motivation="Test transport",
        expert_advice=ExpertAdvice(),
        baseline_config={},
    )
    storage = StorageConfig(
        backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="synthetic")
    )
    actual = local_validated_model(validator, proposal, storage, **forwarded)
    routes = route_map(payload)
    assert routes["tune.planner"].bridge_arguments == tuner_bridge_arguments(actual)
    planner, reflector = routes["tune.planner"].transport, routes["tune.reflector"].transport
    assert planner is not None and reflector is not None
    assert planner.max_retries == reflector.max_retries == planner_retries
    assert reflector.model_id == "reflector"
    assert reflector.reasoning_effort == ("high" if reflect_provider == "openai" else None)
    assert routes["tune.reflector"].shares_client_with == (
        "tune.planner" if reflect_provider == "openai" else None
    )


def test_missing_blocks_and_literature_inheritance():
    absent = route_map({})
    empty = route_map({"implement": {}, "tune": {}})
    assert absent["implement"].transport.model_id != empty["implement"].transport.model_id
    assert absent["tune.planner"].transport.model_id != empty["tune.planner"].transport.model_id
    assert absent["lit_review.main"].transport is None
    assert "requires a main provider/model" in absent["lit_review.main"].issue
    inherited = route_map(
        {
            "interpret": {
                "provider": "openai",
                "model_id": "shared",
                "reasoning_effort": "high",
                "max_retries": 0,
            }
        }
    )
    assert inherited["data_analysis"].bridge_arguments == inherited["interpret"].bridge_arguments
    assert inherited["lit_review.search"].shares_client_with == "lit_review.main"
    assert inherited["lit_review.main"].transport.max_retries is None
    assert inherited["data_analysis"].applicability == "task_dependent"


@pytest.mark.parametrize("separate_search", [False, True])
def test_actual_literature_factories_before_paper_resolution(tmp_path, separate_search):
    from agent.schemas.literature_review import LiteratureReviewInput
    from nodes.ml_literature_review import MLLiteratureReviewAgent

    main = {"provider": "openai", "model_id": "main", "reasoning_effort": "high"}
    payload = (
        {"lit_review": {"main": main, "search": {"provider": "gemini", "model_id": "search"}}}
        if separate_search
        else {"interpret": main}
    )
    settings = WorkflowLLMConfig.model_validate(payload)
    inp = LiteratureReviewInput(
        interpretation_evidence={},
        root_papers=[{"source_type": "local", "identifier": "fixture.txt"}],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "synthetic"},
        },
        run_name="synthetic",
        **settings.get("lit_review"),
    )
    factory = Mock(side_effect=lambda **kwargs: Mock())
    agent = MLLiteratureReviewAgent(bridge_factory=factory, root_cache_dir=str(tmp_path / "cache"))
    agent._resolve_root_paper = Mock(side_effect=RuntimeError("stop before paper IO"))
    with pytest.raises(RuntimeError, match="stop before paper IO"):
        agent.run(inp)
    routes = route_map(payload)
    assert factory.call_args_list[0].kwargs == routes["lit_review.main"].bridge_arguments
    assert factory.call_count == (2 if separate_search else 1)
    if separate_search:
        assert factory.call_args_list[1].kwargs == routes["lit_review.search"].bridge_arguments
    assert (agent.search_bridge is agent.bridge) is (not separate_search)


class NoEnvironmentRead(dict):
    def get(self, key, default=None):
        raise AssertionError(f"Unexpected environment read: {key}")


def test_key_access_requires_opt_in_and_potentially_active_route():
    routes = list(route_map({"interpret": {"provider": "openai", "model_id": "test"}}).values())
    checks = credential_name_checks(routes, requested=False, environment=NoEnvironmentRead())
    assert all(check.status == "not_checked" for check in checks)
    inactive = list(
        route_map({}, pseudo_llm=True, analysis_enabled=False, literature_enabled=False).values()
    )
    assert all(
        check.status == "not_required"
        for check in credential_name_checks(
            inactive, requested=True, environment=NoEnvironmentRead()
        )
    )
    checks = credential_name_checks(
        routes,
        requested=True,
        environment={"OPENAI_API_KEY": "secret-test-marker", "GEMINI_API_KEY": ""},
    )
    assert {check.name: check.status for check in checks} == {
        "GEMINI_API_KEY": "missing",
        "OPENAI_API_KEY": "present_nonempty",
    }
    assert "secret-test-marker" not in "".join(check.model_dump_json() for check in checks)


def test_unknown_provider_and_inactive_invalid_settings_are_explicit():
    route = _route("fixture", {"provider": "custom", "model_id": "custom"}, "conditional")
    assert "Credential name unresolved" in route.issue
    assert credential_name_checks([route], requested=True, environment=NoEnvironmentRead()) == []
    for state in ("disabled", "pseudo"):
        invalid = _route("fixture", {"provider": "gemini", "reasoning_effort": "high"}, state)
        assert invalid.transport is None
        assert "Inactive route settings" in invalid.issue
