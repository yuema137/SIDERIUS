"""Explicit task-reference update construction and shared publication inspection."""

from pathlib import Path

from workflows.definition import ReusableTaskReferences, ReusableWorkflowDocument

from .task_models import TaskReferenceReview, TaskReferenceTarget, TaskReferenceUpdateProposal
from .task_publication import review_publication, selected_target


def review_task_references(
    document: ReusableWorkflowDocument,
    proposal: TaskReferenceUpdateProposal,
    targets: tuple[TaskReferenceTarget, ...],
    project: Path,
) -> tuple[ReusableWorkflowDocument, TaskReferenceReview]:
    target = selected_target(proposal, targets)
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
    return updated, review_publication(document, updated, proposal, targets, project)
