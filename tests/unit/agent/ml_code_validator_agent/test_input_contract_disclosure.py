"""Declared inputs reach complete native requests without overriding review verdicts."""

import json

import pytest

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.validator import ValidatorInput
from nodes.ml_code_validator_agent.input_contract import render_input_contract
from nodes.ml_code_validator_agent.ml_code_validator_agent import MLCodeValidatorAgent


def contract(axes, dtypes=("float32",)):
    return ModelIOContract.model_validate(
        {
            "input": {"axes": axes, "dtype": {"admissible": dtypes}},
            "output": {
                "axes": [
                    {"role": "batch", "dimension": {"symbolic": "B"}},
                    {"dimension": {"fixed": 1}},
                ],
                "dtype": {"admissible": ["float32"]},
            },
        }
    )


class Recorder:
    def __init__(self, **kwargs):
        self.calls = []

    def generate(self, system, user, *, label):
        self.calls.append((system, user, label))
        return dict(
            spec_alignment=False,
            trainability_concerns=["fixture gradient failure"],
            implementation_issues=["fixture runtime failure"],
            passed=False,
            notes="failed fixture",
        )


@pytest.mark.parametrize("error_kind", ["clean", "pytest", "gradient"])
def test_complete_review_discloses_fixed_input_with_errors_advice_and_constraints(error_kind):
    """Removing the real caller's disclosure loses facts in every actual request branch."""
    declared = contract(
        [
            {"role": "batch", "dimension": {"symbolic": "B"}},
            {"dimension": {"fixed": 1}},
            {"dimension": {"fixed": 1024}},
        ]
    )
    inp = ValidatorInput(
        model_type="fixture",
        model_file_path="/fixture/model.py",
        test_file_path="/fixture/test.py",
        description_file_path="/fixture/description.md",
        config_fields={},
        model_description="fixture description",
        mathematical_definition="fixture specification",
        model_io_contract=declared,
        segmentation_applicability="not_applicable",
        expert_advice="fixture expert guidance",
        human_advice="fixture human guidance",
        constraint_context=ConstraintContext(known_sections=("task_rules",)),
    )
    agent = MLCodeValidatorAgent(bridge_factory=Recorder)
    result = agent._llm_review(
        inp,
        "# fixture plugin",
        test_output="fixture pytest failure" if error_kind == "pytest" else None,
        inst_err="fixture backward failure" if error_kind == "gradient" else None,
    )
    system, user, label = agent.bridge.calls[0]
    assert label == "validator.code_review"
    assert "Declared input shape: [B, 1, 1024]" in user
    assert "Segmentation applicability: not_applicable" in user
    assert "fixture expert guidance" in user and "fixture human guidance" in user
    assert "[CURRENT RUN EXECUTION CONSTRAINTS]" in user
    assert "fixture specification" in user and "fixture plugin" in user
    assert "trainability" in system.lower() and "spec_alignment" in system
    assert result.passed is False and result.spec_alignment is False
    if error_kind != "clean":
        expected = (
            "fixture pytest failure" if error_kind == "pytest" else "fixture backward failure"
        )
        assert expected in user and "Runtime errors were observed" in user
    else:
        assert "No runtime errors observed" in user


def test_renderer_preserves_shared_symbols_dynamic_roles_and_all_dtypes():
    """Canonical-dtype-only or probe-size rendering loses declared alternatives/identity."""
    declared = contract(
        [
            {"role": "batch", "dimension": {"symbolic": "B"}},
            {"dimension": {"fixed": 3}},
            {"dimension": {"symbolic": "L"}},
            {"dimension": {"symbolic": "L"}},
            {"dimension": {"dynamic": True}},
        ],
        ("float32", "float64"),
    )
    text = render_input_contract(declared, "temporal")
    line = next(line for line in text.splitlines() if line.startswith("Normalized input tensor"))
    payload = json.loads(line.split(": ", 1)[1])
    assert payload["dtype"]["admissible"] == ["float32", "float64"]
    assert payload["axes"][1]["dimension"]["fixed"] == 3
    assert payload["axes"][1]["role"] is None
    assert [a["dimension"]["symbolic"] for a in payload["axes"][2:4]] == ["L", "L"]
    assert payload["axes"][4]["dimension"]["dynamic"] is True
    assert "Segmentation applicability: temporal" in text
    assert "do not declare numeric ranges" in text


def test_absent_facts_do_not_invent_tensor_or_segmentation_authority():
    """Undeclared applicability must not turn into not_applicable or a default tensor."""
    assert render_input_contract(None, None) == ""
    text = render_input_contract(None, "temporal")
    assert "Normalized input tensor: undeclared." in text
    assert "Declared input shape" not in text
    declared = contract([{"role": "batch", "dimension": {"symbolic": "B"}}])
    text = render_input_contract(declared, None)
    assert "Segmentation applicability: undeclared." in text
    assert "Segmentation applicability: not_applicable" not in text
