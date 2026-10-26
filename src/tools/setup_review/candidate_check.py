"""Pure native checks for the actual options of a fresh managed candidate."""

from agent.schemas.parameter_rules import validate_parameter_rule_ownership
from agent.skills.model_io_probe_skill import declared_output_tensor
from execute_tools.dataset_config import DataScope
from workflows.task_composition import RunTaskComposition, build_task_composition_ref

from .composition_models import CandidateCheckFacts, CandidateCheckOptions


def check_candidate(
    composition: RunTaskComposition, options: CandidateCheckOptions
) -> CandidateCheckFacts:
    """Resolve native declarations without a model, data samples or run settings."""
    contract = composition.forward_contract
    if contract.model_io is None:
        raise ValueError("Changed references require a normalized structured Model-I/O contract")
    for form in options.allowed_output_types or ():
        declared_output_tensor(contract.model_io, form)
    validate_parameter_rule_ownership(
        objective_declared=composition.objective is not None,
        task_rules=composition.parameter_rules,
        workflow_rules=None,
    )
    reference = build_task_composition_ref(composition)
    assert reference is not None
    return CandidateCheckFacts(
        reference=reference,
        forward_contract=contract,
        default_scope=tuple(
            DataScope.default().resolve(composition.dataset_profile.partition_count)
        ),
    )
