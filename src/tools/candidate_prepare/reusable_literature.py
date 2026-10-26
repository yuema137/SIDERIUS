"""Typed source settings and native review projection for reusable candidates.

The child owns scientific composition. Parent reconstruction checks the projection
of its captured typed interpretation, not independent cold-start recomputation.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import (
    ConfidenceRubric,
    DynamicSearchConfig,
    LiteratureReviewInput,
    PaperSource,
    SynthesisConfig,
)
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tools.candidate_worker.layout import graph_instance_dir
from tools.workflow_preview.config import parse_config
from workflows.candidate_literature_policy import require_candidate_literature_policy
from workflows.definition import ManagedCandidateBinding, ReusableWorkflowDocument
from workflows.definition.fanout import execution_families
from workflows.literature_input import build_literature_input
from workflows.llm_config import WorkflowLLMConfig

from .layout import graph_literature_bindings
from .models import CandidatePreparationRequest


class LiteratureSettings(BaseModel):
    """Sparse existing native controls; None is internal omission, never authored null."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    root_papers: list[PaperSource] | None = None
    dynamic_search: DynamicSearchConfig | None = None
    confidence_rubric: ConfidenceRubric | None = None
    findings_verbosity: Literal[0, 1] | None = None
    synthesis: SynthesisConfig | None = None

    @model_validator(mode="after")
    def refuse_null(self) -> Self:
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("literature settings require omission rather than explicit null")
        return self


def review_settings(document: ReusableWorkflowDocument) -> tuple[str, LiteratureSettings] | None:
    if document.execution_profile != "native-literature-candidate/v1":
        return None
    edge = execution_families(document.definition, document.execution_profile).literature
    assert edge is not None
    binding = next(item for item in document.definition.externals if item.id == edge.review_binding)
    if not isinstance(binding, ManagedCandidateBinding) or binding.literature_settings is None:
        raise ValueError("Reusable literature requires source-owned managed settings")
    return edge.review, LiteratureSettings.model_validate(
        binding.literature_settings, extra="forbid"
    )


def prepare_literature(
    document: ReusableWorkflowDocument,
    request: CandidatePreparationRequest,
    interpretation: InterpretationOutput,
    seed: ProposalInput,
    config: WorkflowLLMConfig,
) -> tuple[str, LiteratureReviewInput] | None:
    selected = review_settings(document)
    if selected is None:
        return None
    node_id, settings = selected
    if seed.literature_review_evidence:
        raise ValueError("Prepared proposal seed must not contain literature review evidence")
    value = build_literature_input(
        settings.model_dump(exclude_unset=True),
        interpretation,
        task_description=seed.task_description,
        constraint_context=seed.constraint_context,
        llm_kwargs=config.get("lit_review"),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(
                    graph_instance_dir(Path(request.candidate_workspace), request.run_name, node_id)
                ),
                run_name=request.run_name,
            ),
        ),
        run_name=request.run_name,
    )
    require_candidate_literature_policy(value, network=request.candidate_network)
    filename = next(iter(graph_literature_bindings(document).values()))
    return filename, value


def verify_literature(
    document: ReusableWorkflowDocument,
    request: CandidatePreparationRequest,
    read_bytes: Callable[[Path], bytes],
) -> None:
    if document.execution_profile != "native-literature-candidate/v1":
        return
    output = Path(request.output_dir)
    expected = prepare_literature(
        document,
        request,
        InterpretationOutput.model_validate_json(read_bytes(output / "interpretation.json")),
        ProposalInput.model_validate_json(read_bytes(output / "proposal.json")),
        parse_config(read_bytes(output / "llm.json")),
    )
    assert expected is not None
    filename, value = expected
    if read_bytes(output / filename) != (value.model_dump_json(indent=2) + "\n").encode():
        raise ValueError("prepared literature differs from captured settings and native evidence")
