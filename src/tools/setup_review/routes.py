"""Project the standard workflow's static LLM routes through existing owners."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import TypeAdapter

from agent.llm_settings import KNOWN_PROVIDERS, resolve_main_transport, resolve_reflect_transport
from nodes.llm_settings import (
    ANALYZE,
    IMPLEMENT,
    INTERPRET,
    PROPOSE,
    VALIDATE,
    literature_bridge_arguments,
    node_bridge_kwargs,
)
from nodes.proposer_routing import ProposerRoute, resolve_proposer_routing
from nodes.tuner_llm_settings import tuner_bridge_kwargs
from tools.setup_review.route_models import LLMRoute, RouteApplicability, RouteTransport
from workflows.llm_config import WorkflowLLMConfig, resolve_standard_tuner_llm_options


def _route(name: str, kwargs: dict[str, Any], applicability: RouteApplicability) -> LLMRoute:
    try:
        main = resolve_main_transport(
            provider=kwargs["provider"],
            model_id=kwargs.get("model_id"),
            reasoning_effort=kwargs.get("reasoning_effort"),
        )
    except ValueError as error:
        if applicability not in {"disabled", "pseudo"}:
            raise
        return LLMRoute(
            name=name,
            applicability=applicability,
            bridge_arguments=TypeAdapter(dict[str, Any]).dump_python(kwargs, mode="json"),
            transport=None,
            issue=f"Inactive route settings are unresolved: {error}",
        )
    return LLMRoute(
        name=name,
        applicability=applicability,
        bridge_arguments=TypeAdapter(dict[str, Any]).dump_python(kwargs, mode="json"),
        transport=RouteTransport(**asdict(main), max_retries=kwargs.get("max_retries")),
        issue=(
            "Credential name unresolved: this provider has no known key-name declaration."
            if main.provider not in KNOWN_PROVIDERS
            else None
        ),
    )


def _tuner_routes(config: WorkflowLLMConfig, state: RouteApplicability) -> list[LLMRoute]:
    options = resolve_standard_tuner_llm_options(config.get("tune"))
    # The standard workflow forwards these optional fields explicitly, including
    # None. It does not construct an independent reflector retry policy.
    kwargs = tuner_bridge_kwargs(
        llm_provider=options["provider"],
        llm_model_id=options["model_id"],
        reflect_provider=options.get("reflect_provider"),
        reflect_model_id=options.get("reflect_model_id"),
        max_retries=options.get("max_retries"),
        reasoning_effort=options.get("reasoning_effort"),
        reflect_reasoning_effort=options.get("reflect_reasoning_effort"),
        reflect_retry_policy=options.get("reflect_retry_policy"),
    )
    planner = _route("tune.planner", kwargs, state)
    main = resolve_main_transport(
        provider=kwargs["provider"],
        model_id=kwargs["model_id"],
        reasoning_effort=kwargs.get("reasoning_effort"),
    )
    reflect = resolve_reflect_transport(
        main,
        provider=kwargs["reflect_provider"],
        model_id=kwargs["reflect_model_id"],
        reasoning_effort=kwargs.get("reflect_reasoning_effort"),
    )
    reflector = LLMRoute(
        name="tune.reflector",
        applicability=state,
        bridge_arguments=TypeAdapter(dict[str, Any]).dump_python(kwargs, mode="json"),
        transport=RouteTransport(
            provider=reflect.provider,
            model_id=reflect.model_id,
            base_url=reflect.base_url,
            reasoning_effort=reflect.reasoning_effort,
            max_retries=(
                kwargs["reflect_retry_policy"].max_retries
                if "reflect_retry_policy" in kwargs
                else kwargs["max_retries"]
            ),
            request_timeout=main.request_timeout,
            timeout_retries=main.timeout_retries,
        ),
        shares_client_with=planner.name if reflect.reuse_main_client else None,
    )
    return [planner, reflector]


def _literature_routes(config: WorkflowLLMConfig, state: RouteApplicability) -> list[LLMRoute]:
    options = config.get("lit_review")
    if "llm_provider" not in options or "llm_model_id" not in options:
        return [
            LLMRoute(
                name=f"lit_review.{stage}",
                applicability=state,
                bridge_arguments={},
                transport=None,
                issue="Literature input requires a main provider/model. Configure lit_review "
                "or interpret; the standard workflow supplies no fallback when both are absent.",
            )
            for stage in ("main", "search")
        ]
    arguments = literature_bridge_arguments(
        provider=options["llm_provider"],
        model_id=options["llm_model_id"],
        reasoning_effort=options.get("llm_reasoning_effort"),
        search_provider=options.get("search_llm_provider"),
        search_model_id=options.get("search_llm_model_id"),
        search_reasoning_effort=options.get("search_llm_reasoning_effort"),
        max_retries=options.get("llm_max_retries"),
        search_retry_policy=options.get("search_llm_retry_policy"),
    )
    main = _route("lit_review.main", arguments.main, state)
    search = _route("lit_review.search", arguments.search or arguments.main, state)
    if arguments.search is None:
        search = search.model_copy(update={"shares_client_with": main.name})
    return [main, search]


def standard_llm_routes(
    config: WorkflowLLMConfig,
    *,
    literature_enabled: bool,
    analysis_enabled: bool | None,
    pseudo_llm: bool,
) -> list[LLMRoute]:
    """Describe possible calls, not stage activation, invocation counts or costs."""
    state: RouteApplicability = "pseudo" if pseudo_llm else "conditional"
    routes = []
    for node, defaults in (
        ("interpret", INTERPRET),
        ("implement", IMPLEMENT),
        ("validate", VALIDATE),
        ("data_analysis", ANALYZE),
    ):
        node_state = state
        if node == "data_analysis":
            if analysis_enabled is False:
                node_state = "disabled"
            elif analysis_enabled is None and not pseudo_llm:
                node_state = "task_dependent"
        options = config.get(node)
        kwargs = node_bridge_kwargs(
            provider=options.get("provider", defaults.provider),
            model_id=options.get("model_id", defaults.model_id),
            max_retries=options.get("max_retries", defaults.max_retries),
            reasoning_effort=options.get("reasoning_effort", defaults.reasoning_effort),
            omit_unset_retries=node == "data_analysis",
        )
        routes.append(_route(node, kwargs, node_state))
    options = config.get("propose")
    routing = resolve_proposer_routing(
        ProposerRoute(
            provider=options.get("provider", PROPOSE.provider),
            model_id=options.get("model_id", PROPOSE.model_id),
            max_retries=options.get("max_retries", PROPOSE.max_retries),
            reasoning_effort=options.get("reasoning_effort", PROPOSE.reasoning_effort),
        ),
        options,
    )
    shared_proposer_routes = [(routing.reasoning, "propose.reasoning")]
    for stage in type(routing).model_fields:
        stage_settings = routing.for_stage(stage)
        name = f"propose.{stage}"
        route = _route(name, stage_settings.bridge_kwargs(), state)
        shared = next(
            (
                other_name
                for settings, other_name in shared_proposer_routes
                if settings == stage_settings
            ),
            name,
        )
        if shared != name:
            route = route.model_copy(update={"shares_client_with": shared})
        else:
            shared_proposer_routes.append((stage_settings, name))
        routes.append(route)
    routes.extend(_tuner_routes(config, state))
    routes.extend(_literature_routes(config, state if literature_enabled else "disabled"))
    return routes
