"""Assemble native literature inputs from explicit workflow-owned selections.

No task lookup, file access, provider construction or orchestration occurs here.
The existing native schema owns validation and defaults; callers own enablement,
configuration loading, task description, storage and model-route selection.
"""

from collections.abc import Mapping

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.data_analysis.report import DataAnalysisReport
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewInput
from agent.schemas.protocols.data_analysis_to_ml_literature_review import (
    local_typed_evidence as project_analysis_for_literature,
)
from agent.schemas.protocols.interpreter_to_ml_literature_review import (
    local_typed_evidence as project_interpretation_for_literature,
)
from agent.schemas.storage import StorageConfig


def build_literature_input(
    config: Mapping[str, object],
    interpretation: InterpretationOutput,
    *,
    task_description: str,
    analysis_report: DataAnalysisReport | None = None,
    constraint_context: ConstraintContext | None = None,
    llm_kwargs: Mapping[str, object],
    storage: StorageConfig,
    run_name: str,
) -> LiteratureReviewInput:
    """Project upstream evidence and validate the existing native input.

    Only the established node knobs are selected from config. In particular,
    config's task_description and enabled keys are not input authorities.
    Preserve the native defaults for omitted knobs and routing fields.
    """
    payload = {
        "interpretation_evidence": project_interpretation_for_literature(interpretation),
        "root_papers": config.get("root_papers", []),
        "dynamic_search": config.get("dynamic_search", {}),
        "synthesis_config": config.get("synthesis", {}),
        "confidence_rubric": config.get("confidence_rubric", {}),
        "findings_verbosity": config.get("findings_verbosity", 1),
        "task_description": task_description,
        "storage": storage,
        "run_name": run_name,
        **llm_kwargs,
    }
    if analysis_report is not None:
        payload["data_analysis_evidence"] = project_analysis_for_literature(analysis_report)
    payload["constraint_context"] = constraint_context
    return LiteratureReviewInput.model_validate(payload)
