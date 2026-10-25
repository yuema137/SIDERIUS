"""Explicit owner-backed task observation and a non-publishing update proposal."""

from uuid import uuid4

from tools.setup_review.composition_check import observe_composition
from tools.setup_review.composition_models import CompositionJob
from tools.setup_review.composition_transport import manifest_digest
from workflows.definition import ReusableTaskReferences, ReusableWorkflowDocument
from workflows.llm_config import WorkflowLLMConfig

from .task_models import (
    TaskReferenceFinding,
    TaskReferenceReview,
    TaskReferenceTarget,
    TaskReferenceUpdateProposal,
)


def review_task_references(
    document: ReusableWorkflowDocument,
    proposal: TaskReferenceUpdateProposal,
    target: TaskReferenceTarget,
) -> tuple[ReusableWorkflowDocument, TaskReferenceReview]:
    """Inspect only an explicitly selected configured target; no scientific compatibility guess."""
    if (
        target.choice_id != proposal.selected_choice_id
        or target.binding != proposal.expected_task_binding
    ):
        raise ValueError("configured task selection changed; select and review again")
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
    observed = observe_composition(job, target.read_only, data_root=target.data_root)
    facts = observed.result.task
    verified = (
        observed.result.outcome == "passed"
        and facts is not None
        and facts.semantic_fingerprint == target.binding.semantic_fingerprint
        and facts.task_data_path_id == target.binding.task_data_path_id
    )
    findings = []
    if not verified:
        findings.append(
            TaskReferenceFinding(
                code="inspection_failed"
                if observed.result.outcome != "passed"
                else "identity_mismatch",
                state="blocked",
                reference="task_binding",
                message="Target inspection failed or differs from the configured accepted native identity; do not accept changed contents under the same revision label",
            )
        )
    else:
        findings.append(
            TaskReferenceFinding(
                code="identity_verified",
                state="retained",
                reference="task_binding",
                message="The existing native composition owner observed the configured accepted identity",
            )
        )
    if document.task_binding != target.binding:
        findings.append(
            TaskReferenceFinding(
                code="compatibility_unresolved",
                state="blocked",
                reference="definition.task",
                message="Task binding changes require owner-backed historical facts and compatibility/remapping review; this slice does not certify scientific compatibility or legacy adoption",
            )
        )
    findings.append(
        TaskReferenceFinding(
            code="save_unsupported",
            state="blocked",
            reference="source",
            message="Bound Save and execution remain unsupported; this proposal is an inspectable unsaved draft",
        )
    )
    updated = document.model_copy(
        update={
            "task_binding": target.binding,
            "definition": document.definition.model_copy(
                update={
                    "task": ReusableTaskReferences(
                        manifest=str(target.manifest),
                        data_root=str(target.data_root),
                    )
                }
            ),
        }
    )
    return updated, TaskReferenceReview(
        selected_choice_id=target.choice_id,
        previous_binding=document.task_binding,
        target_binding=target.binding,
        observation=observed,
        findings=tuple(findings),
    )
