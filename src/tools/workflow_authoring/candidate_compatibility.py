"""Changed references for fresh fixed candidates, never trained-state migration."""

from pathlib import Path

from tools.candidate_prepare.layout import graph_proposal_bindings, graph_storage_bindings
from tools.candidate_prepare.resolution import check_candidate_roles
from tools.setup_review.composition_models import CandidateCheckOptions, CompositionObservation
from workflows.definition import ManagedCandidateBinding, ReusableWorkflowDocument
from workflows.definition.candidate import candidate_nodes
from workflows.definition.fanout import execution_families

from .task_models import TaskReferenceFinding, TaskReferenceTarget
from .task_observation import identity_matches, observe_target


def _check_source(current: ReusableWorkflowDocument, proposed: ReusableWorkflowDocument) -> None:
    for document in (current, proposed):
        if not all(
            isinstance(item, ManagedCandidateBinding) for item in document.definition.externals
        ):
            raise ValueError("Changed references require managed proposal/storage bindings only")
        if document.execution_profile is None:
            roles = candidate_nodes(document.definition)
            check_candidate_roles(document, {roles["proposal"]})
        else:
            shape = execution_families(document.definition, document.execution_profile)
            check_candidate_roles(document, {family.proposal for family in shape.families})
            graph_proposal_bindings(document)
            graph_storage_bindings(document)
    if any(
        getattr(current, key) != getattr(proposed, key)
        for key in ("positions", "preparation_options", "execution_profile")
    ) or (
        current.definition.nodes != proposed.definition.nodes
        or current.definition.externals != proposed.definition.externals
        or current.training_settings != proposed.training_settings
    ):
        raise ValueError(
            "Save graph, profile, layout, option, training settings and advice edits before changing task references"
        )


def _changes(
    before: CompositionObservation, observed: CompositionObservation
) -> tuple[TaskReferenceFinding, ...]:
    assert before.result.candidate_check is not None and observed.result.candidate_check is not None
    assert before.result.task is not None and observed.result.task is not None
    changes = [
        (name, getattr(before.result.task, name), getattr(observed.result.task, name))
        for name in (
            "task_data_path_id",
            "task_config",
            "dataset_profile",
            "primary_metric",
            "secondary_metrics",
            "parameter_rules",
            "plugins",
            "code_package_identity",
            "task_health_declaration",
        )
    ]
    changes.extend(
        (
            (
                "objective",
                before.result.candidate_check.reference.objective,
                observed.result.candidate_check.reference.objective,
            ),
            (
                "custom_loss",
                before.result.candidate_check.reference.task_owned_custom_loss,
                observed.result.candidate_check.reference.task_owned_custom_loss,
            ),
            (
                "default_scope",
                before.result.candidate_check.default_scope,
                observed.result.candidate_check.default_scope,
            ),
        )
    )
    return tuple(
        TaskReferenceFinding(
            code="authored_changes",
            state="requires_review",
            reference=f"task.{name}",
            message=f"Task {name.replace('_', ' ')} changed. Inspect the task declaration details and explicitly review retained advice; no scientific equivalence is claimed.",
        )
        for name, first, second in changes
        if first != second
    )


def inspect_changed_candidate(
    current: ReusableWorkflowDocument,
    proposed: ReusableWorkflowDocument,
    locations: tuple[Path, Path],
    targets: tuple[TaskReferenceTarget, ...],
    target: TaskReferenceTarget,
) -> tuple[CompositionObservation, CompositionObservation | None, tuple[TaskReferenceFinding, ...]]:
    """Check each version against its own pin before deterministic workflow checks."""

    def blocked(message: str, reference: str = "definition.task") -> TaskReferenceFinding:
        return TaskReferenceFinding(
            code="compatibility_unresolved", state="blocked", reference=reference, message=message
        )

    try:
        _check_source(current, proposed)
    except ValueError as error:
        return observe_target(target), None, (blocked(str(error), "source"),)

    old_options = CandidateCheckOptions(
        allowed_output_types=proposed.preparation_options.allowed_output_types
    )
    observed_options = old_options
    if proposed.training_settings is not None:
        from tools.candidate_prepare.reusable_training import settings_payload

        payload = settings_payload(proposed)
        assert payload is not None
        observed_options = old_options.model_copy(update={"training_settings": payload.decode()})
    observed = observe_target(target, observed_options)
    previous = [
        value
        for value in targets
        if (value.manifest, value.data_root) == locations and value.binding == current.task_binding
    ]
    if len(previous) != 1:
        return (
            observed,
            None,
            (
                blocked(
                    "The previous task version needs one matching configured choice; keep separate version directories"
                ),
            ),
        )
    try:
        before = observe_target(previous[0], old_options)
    except (OSError, ValueError):
        return (
            observed,
            None,
            (
                blocked(
                    "The previous task version is unavailable; restore its unchanged source in a separate version directory"
                ),
            ),
        )
    old, new = before.result.candidate_check, observed.result.candidate_check
    if not identity_matches(before, previous[0]) or old is None or new is None:
        return (
            observed,
            before,
            (
                blocked(
                    "Both previous and target task versions must pass native candidate checks against their own pins"
                ),
            ),
        )
    for facts, selected in ((old, previous[0]), (new, target)):
        if (facts.reference.semantic_fingerprint, facts.reference.task_data_path_id) != (
            selected.binding.semantic_fingerprint,
            selected.binding.task_data_path_id,
        ):
            return (
                observed,
                before,
                (blocked("Candidate facts differ from the configured native identity"),),
            )
    for field in (
        "model_io",
        "supervision_target",
        "custom_loss_applicability",
        "segmentation_applicability",
    ):
        if getattr(old.forward_contract, field) != getattr(new.forward_contract, field):
            return (
                observed,
                before,
                (
                    blocked(
                        "Structured task interfaces changed; explicit I/O adaptation is outside this fixed-candidate update",
                        f"forward_contract.{field}",
                    ),
                ),
            )
    findings = list(_changes(before, observed))
    if proposed.training_settings is not None:
        findings.append(
            TaskReferenceFinding(
                code="authored_changes",
                state="requires_review",
                reference="workflow.training_settings",
                message="Retained native training settings were checked for a fresh target run; no old training state or run evidence is migrated.",
            )
        )
    message = "Both native versions passed; fixed candidate interfaces and authored graph, layout, options and advice are preserved. New runs use a fresh target proposal."
    if proposed.execution_profile is not None:
        shape = execution_families(proposed.definition, proposed.execution_profile)
        message = (
            f"Both native versions passed; {len(shape.families)} proposal families and "
            f"{len(shape.branches)} implementation branches keep their typed lineage, "
            "managed storage, layout and shared options/advice. New runs use fresh target proposals."
        )
    return (
        observed,
        before,
        (
            *findings,
            TaskReferenceFinding(
                code="identity_verified",
                state="retained",
                reference="workflow.candidate",
                message=message,
            ),
        ),
    )
