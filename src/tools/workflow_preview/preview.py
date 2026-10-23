"""Observe one declared native candidate chain, without executing its payloads."""

from collections.abc import Callable
from pathlib import Path

from tools.setup_review.route_models import LLMRoute
from tools.setup_review.routes import NodeRouteRole, node_llm_routes
from workflows.definition import ExternalRequest, ProtocolRequest, ResultSource, WorkflowDefinition
from workflows.llm_config import WorkflowLLMConfig

from .config import parse_config
from .files import inspect_workspace, observe_file, resolve_location
from .models import FileObservation, WorkflowBindings, WorkflowPreview, WorkflowPreviewRequest


def _candidate_nodes(definition: WorkflowDefinition) -> dict[str, str]:
    nodes = {node.capability: node for node in definition.nodes}
    if len(definition.nodes) != 3 or set(nodes) != {"proposal", "implementation", "validation"}:
        raise ValueError(
            "Unsupported preview: requires exactly one proposal, implementation and validation"
        )
    if not isinstance(nodes["proposal"].request, ExternalRequest):
        raise ValueError("Unsupported preview: proposal requires an external request")
    for role, upstream, protocol in (
        ("implementation", "proposal", "proposal-to-implementation"),
        ("validation", "implementation", "implementation-to-validation"),
    ):
        node = nodes[role]
        request = node.request
        if not isinstance(request, ProtocolRequest) or request.protocol != protocol:
            raise ValueError(f"Unsupported preview: {node.id} requires {protocol}")
        source = next(arg.source for arg in request.arguments if arg.name == "output")
        if not isinstance(source, ResultSource) or source.node != nodes[upstream].id:
            raise ValueError(f"Unsupported preview: {node.id}.output must use {nodes[upstream].id}")
    return {role: node.id for role, node in nodes.items()}


def _selected_routes(config: WorkflowLLMConfig, nodes: dict[str, str]) -> tuple[LLMRoute, ...]:
    selected = []
    roles: tuple[tuple[str, NodeRouteRole], ...] = (
        ("proposal", "propose"),
        ("implementation", "implement"),
        ("validation", "validate"),
    )
    for capability, role in roles:
        routes = node_llm_routes(config, role)
        names = {
            route.name: f"{nodes[capability]}.{route.name.partition('.')[2] or 'main'}"
            for route in routes
        }
        selected.extend(
            route.model_copy(
                update={
                    "name": names[route.name],
                    "shares_client_with": names[route.shares_client_with]
                    if route.shares_client_with
                    else None,
                }
            )
            for route in routes
        )
    return tuple(selected)


def observe_bindings(
    request: WorkflowPreviewRequest,
    *,
    read_file: Callable[[Path, str], tuple[FileObservation, bytes]] | None = None,
) -> WorkflowBindings:
    """Common Python/JSON boundary; even unchecked Pydantic copies are revalidated."""
    read_file = observe_file if read_file is None else read_file
    request = WorkflowPreviewRequest.model_validate_json(request.model_dump_json())
    definition = request.document.definition
    nodes = _candidate_nodes(definition)
    project = Path(request.project_root).resolve()
    if not project.is_dir():
        raise ValueError(f"project_root must be an existing directory: {project}")
    data = resolve_location(project, definition.task.data_root, "task.data_root")
    if not data.is_dir():
        raise ValueError(f"task.data_root must be an existing directory: {data}")
    workspace = resolve_location(project, definition.task.workspace, "task.workspace")
    locations = [("task.manifest", definition.task.manifest)]
    locations.extend((f"external.{item.id}", item.location) for item in definition.externals)
    if request.llm_config_file is not None:
        locations.append(("llm_config", request.llm_config_file))
    paths = [
        (reference, resolve_location(project, location, reference))
        for reference, location in locations
    ]
    observations = []
    config = WorkflowLLMConfig.default() if request.llm_config_file is None else None
    for reference, path in paths:
        observation, content = read_file(path, reference)
        observations.append(observation)
        if reference == "llm_config":
            config = parse_config(content)
    assert config is not None
    return WorkflowBindings(
        project_root=str(project),
        data_root=str(data),
        workspace=str(workspace),
        files=tuple(observations),
        config_source="workflow_default" if request.llm_config_file is None else "explicit_file",
        selected_constructor_routes=_selected_routes(config, nodes),
        inactive_roles=tuple(
            name
            for name in WorkflowLLMConfig.model_fields
            if name not in {"propose", "implement", "validate_model"}
        ),
    )


def preview_workflow(request: WorkflowPreviewRequest) -> WorkflowPreview:
    """Observe bindings and preserve the public absent/empty workspace admission."""
    bindings = observe_bindings(request)
    state = inspect_workspace(
        Path(bindings.workspace),
        Path(bindings.data_root),
        tuple(Path(item.path) for item in bindings.files),
    )
    return WorkflowPreview(**bindings.model_dump(), workspace_state=state)
