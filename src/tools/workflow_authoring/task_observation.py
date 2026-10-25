"""One explicit configured target uses the original native inspection owner."""

from uuid import uuid4

from tools.setup_review.composition_check import observe_composition
from tools.setup_review.composition_models import CompositionJob, CompositionObservation
from tools.setup_review.composition_transport import manifest_digest
from workflows.llm_config import WorkflowLLMConfig

from .task_models import TaskReferenceTarget


def observe_target(target: TaskReferenceTarget) -> CompositionObservation:
    for path in (target.manifest, target.data_root, target.llm_config_file, target.inspection_root):
        if not path.is_absolute() or path != path.resolve():
            raise ValueError("configured task references must be canonical absolute paths")
    if not target.inspection_root.is_dir():
        raise ValueError("configured task inspection parent must exist")
    config = WorkflowLLMConfig.model_validate_json(target.llm_config_file.read_bytes())
    job = CompositionJob(
        manifest=str(target.manifest),
        manifest_sha256=manifest_digest(str(target.manifest)),
        planner_strategy=config.get("tune").get("planner_strategy"),
        scratch=str(target.inspection_root / str(uuid4())),
        settings=target.settings,
    )
    return observe_composition(job, target.read_only, data_root=target.data_root)


def identity_matches(observed: CompositionObservation, target: TaskReferenceTarget) -> bool:
    facts = observed.result.task
    return (
        observed.result.outcome == "passed"
        and facts is not None
        and facts.semantic_fingerprint == target.binding.semantic_fingerprint
        and facts.task_data_path_id == target.binding.task_data_path_id
    )
