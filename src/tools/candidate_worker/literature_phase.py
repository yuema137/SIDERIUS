"""Invoke one admitted native review and preserve its output format and accounting."""

from pathlib import Path

from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
from core.durable_io import publish_bytes_write_once
from nodes.ml_literature_review.ml_literature_review import MLLiteratureReviewAgent
from workflows.definition.fanout import execution_families
from workflows.run_context import contextual_bridge_factory

from .artifacts import capture_record
from .invocation import FixedInvocationContext
from .layout import graph_instance_dir, literature_cache_dir, literature_input_path
from .models import CandidateRunReceipt, CandidateRunRequest


def run_literature(
    context: FixedInvocationContext,
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    inputs: LiteratureReviewInput,
) -> tuple[LiteratureReviewOutput, Path]:
    """Bind the actual lazy bridges before the original native run method calls them."""
    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    if context.node_id not in shape.literature_reviews:
        raise ValueError("literature invocation is not a declared review")
    review = context.node_id
    directory = graph_instance_dir(
        Path(initial.workspace), request.run_name, review, iteration=context.iteration
    )
    if context.storage_workspace != str(directory):
        raise ValueError("literature invocation storage binding disagrees")
    context.require_resolved_binding(
        initial,
        run_name=request.run_name,
        node_id=review,
        phase="literature",
        storage=inputs.storage,
        implementation_directory="",
    )
    input_path = literature_input_path(Path(initial.workspace), review, iteration=context.iteration)
    input_path.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(str(input_path), inputs.model_dump_json(indent=2).encode())
    factory = contextual_bridge_factory(
        None,
        workspace=context.workspace,
        iteration=context.iteration,
        run_name=context.run_name,
        run_id=context.run_id,
    )
    agent = MLLiteratureReviewAgent(
        bridge_factory=factory,
        root_cache_dir=str(
            literature_cache_dir(
                Path(initial.workspace), request.run_name, review, iteration=context.iteration
            )
        ),
    )
    output = LiteratureReviewOutput.model_validate(agent.run(inputs))
    if output.run_name != request.run_name:
        raise ValueError("literature output run binding disagrees")
    path = directory / f"ml_literature_review_{request.run_name}.json"
    capture_record(path, output)
    return output, path
