"""Cross-boundary witnesses for truthful, read-only constraint disclosure."""

import json

import pytest
from pydantic import BaseModel

from agent.data_analysis.structured_output import generate_validated
from agent.prompt_templates.constraints import (
    append_constraint_disclosure,
    render_constraint_disclosure,
)
from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.parameter_rules import ParameterRules
from workflows.constraint_disclosure import workflow_constraint_context
from workflows.run_config import WorkflowLaunchConfig


def locked_context():
    return ConstraintContext(
        known_sections=("workflow_rules",),
        workflow_rules=ParameterRules.model_validate({"train_config.lr": {"exact": 0.01}}),
    )


def test_workflow_projection_uses_portion_owner_without_mutating_inputs():
    overrides = {"train_config": {"epochs": 11}}
    launch = WorkflowLaunchConfig(
        plan_overrides=overrides,
        trial_portion=0.4,
        formal_eval_portion=0.7,
        formal_training_scope_source="agent",
        workflow_parameter_rules=locked_context().workflow_rules,
    )
    context = workflow_constraint_context(launch, None)
    assert context.overrides["trial_portion"] == 0.4
    assert context.execution.formal_eval_portion == 0.7
    assert context.workflow_rules == launch.workflow_parameter_rules
    assert overrides == {"train_config": {"epochs": 11}}
    text = render_constraint_disclosure(context)
    assert "missing authority sections: task_rules, objective" in text
    assert "Trial portion overrides do not freeze Formal portions" in text
    assert "operator-owned only when formal_training_scope_source is operator" in text


def test_missing_context_is_not_unrestricted_and_known_empty_is_distinct():
    assert "missing authority sections: task_rules" in render_constraint_disclosure(None)
    text = render_constraint_disclosure(ConstraintContext(known_sections=("task_rules",)))
    assert "missing authority sections: workflow_rules" in text
    assert "exact values are locked even when a proposal already matches" in text


def test_shared_repair_receives_same_rules_and_does_not_change_authored_value():
    class Output(BaseModel):
        value: int

    class Bridge:
        def __init__(self):
            self.calls = []

        def generate(self, system, user, *, label):
            self.calls.append((label, user))
            return {"value": "bad"} if len(self.calls) == 1 else {"value": 3}

    class Store:
        def append_structured_output_receipt(self, receipt):
            pass

    bridge = Bridge()
    result = generate_validated(
        bridge,
        store=Store(),
        model_type=Output,
        system="schema",
        user="choose",
        label="analysis",
        semantic_projection=lambda _: "same",
        constraint_context=locked_context(),
    )
    assert result.value == 3
    assert [label for label, _ in bridge.calls] == ["analysis", "analysis.repair"]
    for _, prompt in bridge.calls:
        assert '"train_config.lr"' in prompt
        assert '"exact": 0.01' in prompt
        assert prompt.count("[CURRENT RUN EXECUTION CONSTRAINTS]") == 1


def test_exp_empty_renderer_preserves_prompt_bytes(monkeypatch):
    import agent.prompt_templates.constraints as module

    monkeypatch.setattr(module, "render_constraint_disclosure", lambda context: "")
    assert append_constraint_disclosure("old prompt\n", locked_context()) == "old prompt\n"


def test_exp_transport_opt_out_leaves_execution_authorities_in_place():
    rules = locked_context().workflow_rules
    launch = WorkflowLaunchConfig(
        disclose_execution_constraints=False, workflow_parameter_rules=rules
    )
    assert workflow_constraint_context(launch, None) is None
    assert launch.workflow_parameter_rules == rules


@pytest.mark.parametrize("previous", [None, False])
def test_disclosure_change_cannot_silently_resume_old_workspace(tmp_path, previous):
    from core.run_invariants import RunInvariantsViolation, ensure_run_invariants
    from tests.unit.core.test_workflow_parameter_rules_lock import _invariants

    old = _invariants(None).model_copy(update={"disclose_execution_constraints": previous})
    new = old.model_copy(update={"disclose_execution_constraints": True})
    ensure_run_invariants(str(tmp_path), old)
    with pytest.raises(RunInvariantsViolation, match="disclose_execution_constraints"):
        ensure_run_invariants(str(tmp_path), new)
