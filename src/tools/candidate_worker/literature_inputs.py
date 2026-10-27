"""Reconcile the explicit review input without changing native scientific fields."""

from pathlib import Path

from pydantic import TypeAdapter

from agent.schemas.literature_review import LiteratureReviewInput
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.llm_settings import literature_bridge_arguments
from tools.setup_review.routes import node_llm_routes
from workflows.candidate_literature_policy import require_candidate_literature_policy
from workflows.llm_config import WorkflowLLMConfig

from .inputs import require_storage
from .layout import graph_instance_dir, literature_cache_dir, literature_input_path
from .models import CandidateRunRequest


def materialize_literature(
    payload: bytes,
    *,
    request: CandidateRunRequest,
    workspace: Path,
    node_id: str,
    seed: ProposalInput,
    config: WorkflowLLMConfig,
    iteration: int = 1,
) -> LiteratureReviewInput:
    """Require selected task, routes, network policy and fresh managed ownership."""
    value = LiteratureReviewInput.model_validate_json(payload)
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=str(
                graph_instance_dir(workspace, request.run_name, node_id, iteration=iteration)
            ),
            run_name=request.run_name,
        ),
    )
    require_storage(value.storage, storage)
    if value.run_name != request.run_name or value.task_description != seed.task_description:
        raise ValueError("literature input task/run binding disagrees with selected candidate")
    if value.constraint_context != seed.constraint_context:
        raise ValueError("literature constraints disagree with the checked proposal seed")
    require_candidate_literature_policy(value, network=request.network)
    arguments = literature_bridge_arguments(
        provider=value.llm_provider,
        model_id=value.llm_model_id,
        reasoning_effort=value.llm_reasoning_effort,
        max_output_tokens=value.llm_max_output_tokens,
        search_max_output_tokens=value.search_llm_max_output_tokens,
        search_provider=value.search_llm_provider,
        search_model_id=value.search_llm_model_id,
        search_reasoning_effort=value.search_llm_reasoning_effort,
        max_retries=value.llm_max_retries,
        search_retry_policy=value.search_llm_retry_policy,
    )
    routes = node_llm_routes(config, "lit_review")
    actual = (arguments.main, arguments.search or arguments.main)
    for route, kwargs in zip(routes, actual, strict=True):
        if route.issue or route.bridge_arguments != TypeAdapter(dict).dump_python(
            kwargs, mode="json"
        ):
            raise ValueError("literature input routes disagree with selected LLM configuration")
    if (arguments.search is None) != (routes[1].shares_client_with is not None):
        raise ValueError("literature search bridge sharing disagrees with selected configuration")
    for path in (
        literature_cache_dir(workspace, request.run_name, node_id, iteration=iteration),
        literature_input_path(workspace, node_id, iteration=iteration),
        graph_instance_dir(workspace, request.run_name, node_id, iteration=iteration)
        / f"ml_literature_review_{request.run_name}.json",
    ):
        if path.exists() or path.is_symlink():
            raise ValueError("literature managed input/cache/output already exists")
    return value.model_copy(update={"storage": storage})
