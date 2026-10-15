"""Project existing workflow authorities without resolving or enforcing them."""

from agent.schemas.constraint_disclosure import (
    CONSTRAINT_SECTIONS,
    ConstraintContext,
    ConstraintSection,
    ExecutionConstraintFacts,
)
from workflows.run_config import WorkflowLaunchConfig, frozen_portion_overrides
from workflows.task_composition import RunTaskComposition, build_task_composition_ref


def workflow_constraint_context(
    launch: WorkflowLaunchConfig, composition: RunTaskComposition | None
) -> ConstraintContext | None:
    """Use the same override owner as the tuner edge; never infer from baseline."""
    if not launch.disclose_execution_constraints:
        return None
    ref = build_task_composition_ref(composition)
    known: list[ConstraintSection] = list(CONSTRAINT_SECTIONS)
    if ref is None:
        known = [name for name in known if name not in {"task_rules", "objective"}]
    return ConstraintContext(
        known_sections=tuple(known),
        task_rules=ref.parameter_rules if ref else None,
        workflow_rules=launch.workflow_parameter_rules,
        objective=ref.objective.model_dump(mode="json") if ref and ref.objective else None,
        overrides=frozen_portion_overrides(launch),
        execution=ExecutionConstraintFacts(
            **{name: getattr(launch, name) for name in ExecutionConstraintFacts.model_fields}
        ),
    )
