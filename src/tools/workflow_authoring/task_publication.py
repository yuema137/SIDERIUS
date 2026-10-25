"""Supported snapshot publication checks, not scientific task migration policy."""

from pathlib import Path
from typing import Literal

from tools.setup_review.composition_models import CompositionObservation
from tools.workflow_preview.files import resolve_location
from workflows.definition import ReusableWorkflowDocument, TaskBinding

from .task_models import (
    FindingCode,
    TaskReferenceAcceptance,
    TaskReferenceAcknowledgement,
    TaskReferenceFinding,
    TaskReferenceReview,
    TaskReferenceTarget,
    TaskReferenceUpdateProposal,
)
from .task_observation import identity_matches, observe_target


def selected_target(
    selection: TaskReferenceUpdateProposal, targets: tuple[TaskReferenceTarget, ...]
) -> TaskReferenceTarget:
    target = next(
        (value for value in targets if value.choice_id == selection.selected_choice_id), None
    )
    if target is None:
        raise ValueError("select a configured version-aware task choice")
    if target.binding != selection.expected_task_binding:
        raise ValueError("configured task selection changed; select and review again")
    return target


def same_identity(first: TaskBinding, second: TaskBinding) -> bool:
    return (first.semantic_fingerprint, first.task_data_path_id) == (
        second.semantic_fingerprint,
        second.task_data_path_id,
    )


def references(document: ReusableWorkflowDocument, project: Path) -> tuple[Path, Path]:
    task = document.definition.task
    return (
        resolve_location(project, task.manifest, "task.manifest"),
        resolve_location(project, task.data_root, "task.data_root"),
    )


def adoption_unchanged(
    current: ReusableWorkflowDocument, proposed: ReusableWorkflowDocument
) -> bool:
    return (
        current.definition.nodes == proposed.definition.nodes
        and current.definition.externals == proposed.definition.externals
        and current.preparation_options == proposed.preparation_options
        and current.training_settings == proposed.training_settings
    )


def source_policy(
    current: ReusableWorkflowDocument,
    project: Path,
    targets: tuple[TaskReferenceTarget, ...],
    selected: TaskReferenceTarget,
) -> TaskReferenceTarget | None:
    locations = references(current, project)
    if locations == (selected.manifest, selected.data_root):
        return selected
    candidates = [
        value
        for value in targets
        if locations == (value.manifest, value.data_root)
        and (current.task_binding is None or same_identity(current.task_binding, value.binding))
    ]
    return candidates[0] if len(candidates) == 1 else None


def current_observation(
    current: ReusableWorkflowDocument,
    project: Path,
    targets: tuple[TaskReferenceTarget, ...],
    target: TaskReferenceTarget,
) -> tuple[CompositionObservation | None, TaskReferenceFinding | None]:
    previous = source_policy(current, project, targets, target)
    if previous is None:
        return None, TaskReferenceFinding(
            code="compatibility_unresolved",
            state="blocked",
            reference="definition.task",
            message="The current source has no unambiguous configured inspection policy",
        )
    if previous == target:
        return None, None
    observed = observe_target(previous)
    if identity_matches(observed, previous) and same_identity(previous.binding, target.binding):
        return observed, None
    return observed, TaskReferenceFinding(
        code="compatibility_unresolved",
        state="blocked",
        reference="definition.task",
        message="The configured current task observation does not prove the same accepted native identity",
    )


def review_publication(
    current: ReusableWorkflowDocument,
    proposed: ReusableWorkflowDocument,
    selection: TaskReferenceUpdateProposal,
    targets: tuple[TaskReferenceTarget, ...],
    project: Path,
) -> TaskReferenceReview:
    target = selected_target(selection, targets)
    observed = observe_target(target)
    findings = []

    def finding(
        code: FindingCode,
        state: Literal["retained", "requires_review", "blocked"],
        reference: str,
        message: str,
    ) -> None:
        findings.append(
            TaskReferenceFinding(code=code, state=state, reference=reference, message=message)
        )

    if identity_matches(observed, target):
        finding(
            "identity_verified",
            "retained",
            "task_binding",
            "The original native owner observed the configured accepted identity",
        )
    else:
        finding(
            "inspection_failed" if observed.result.outcome != "passed" else "identity_mismatch",
            "blocked",
            "task_binding",
            "Native observation failed or differs from the configured pin; changed contents cannot inherit the same revision label",
        )
    if proposed.task_binding is None:
        finding("pin_removal", "blocked", "task_binding", "Removing an accepted pin is unsupported")
    elif proposed.task_binding != target.binding or references(proposed, project) != (
        target.manifest,
        target.data_root,
    ):
        finding(
            "reference_mismatch",
            "blocked",
            "definition.task",
            "Proposed pin and resolved task locations must match the explicitly configured selection",
        )
    if current.task_binding is not None and not same_identity(current.task_binding, target.binding):
        finding(
            "compatibility_unresolved",
            "blocked",
            "definition.task",
            "Changed native identity requires a separate owner-backed compatibility review; text differences cannot prove migration safety",
        )
    previous_observation, previous_failure = current_observation(current, project, targets, target)
    if previous_failure is not None:
        findings.append(previous_failure)
    if current.task_binding is None:
        if not adoption_unchanged(current, proposed):
            finding(
                "compatibility_unresolved",
                "blocked",
                "source",
                "Current-snapshot adoption must preserve the managed graph, preparation options and scientific settings",
            )
        finding(
            "current_snapshot_adoption",
            "requires_review",
            "task_binding",
            "Explicitly accept the currently observed unchanged snapshot; no historical identity is asserted",
        )
    else:
        finding(
            "authored_changes",
            "requires_review",
            "source",
            "Review the exact proposed source, advice and references; unchanged task identity does not certify authored scientific choices",
        )
    return TaskReferenceReview(
        selected_choice_id=target.choice_id,
        previous_binding=current.task_binding,
        target_binding=target.binding,
        observation=observed,
        current_observation=previous_observation,
        findings=tuple(findings),
        save_supported=not any(value.state == "blocked" for value in findings),
    )


def verify_acceptance(review: TaskReferenceReview, acceptance: TaskReferenceAcceptance) -> None:
    if (
        review.selected_choice_id != acceptance.selection.selected_choice_id
        or review.target_binding != acceptance.selection.expected_task_binding
    ):
        raise ValueError("accepted task selection does not match the reconstructed review")
    if not review.save_supported:
        raise ValueError("task-reference publication is blocked; keep the reviewed draft")
    required = tuple(
        TaskReferenceAcknowledgement(code=value.code, reference=value.reference)
        for value in review.findings
    )
    adoption = any(value.code == "current_snapshot_adoption" for value in review.findings)
    if (
        acceptance.adopt_current_snapshot != adoption
        or acceptance.acknowledged_findings != required
    ):
        raise ValueError(
            "task-reference findings or adoption intent changed; explicitly review and accept again"
        )
