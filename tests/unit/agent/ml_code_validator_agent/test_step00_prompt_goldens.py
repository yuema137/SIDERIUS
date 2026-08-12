"""Step-00 PB-6 — validator code_review prompt goldens.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.1 / §15.1 (roadmap step 04 A-surface).

The clean branch is captured through the real ``_llm_review`` wrapper (the
smallest production-path invocation that still pins the label and the
system/user pairing at the boundary). The error branch's production drivers
(``pytest`` stdout, torch/pydantic exception text) are nondeterministic —
frozen substitutes are passed through the same real producer (design
§13.1: never let a golden capture a live validator error).
"""

from __future__ import annotations

from pathlib import Path

from agent.schemas.validator import ValidatorInput
from nodes.ml_code_validator_agent.ml_code_validator_agent import (
    MLCodeValidatorAgent,
)
from tests.helpers.golden import assert_golden
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge

GOLDENS = Path(__file__).parent / "goldens"

_FIXTURE_PLUGIN_SRC = (
    "# TEST-OWNED plugin source (design §13.1 — never production code)\n"
    "class Step00FixtureModel(nn.Module):\n"
    "    def __init__(self, config):\n"
    "        super().__init__()\n"
    "        self.net = nn.Conv1d(1, config.channels, 3)\n"
    "    def forward(self, x):\n"
    "        return self.net(x.float().unsqueeze(1))\n"
)


class _ReviewRecorder(BoundaryRecorderBridge):
    def _chat_json(self, *a, **k):
        super()._chat_json(*a, **k)
        return {
            "spec_alignment": True,
            "trainability_concerns": [],
            "implementation_issues": [],
            "passed": True,
            "notes": "ok",
        }


def fixture_input() -> ValidatorInput:
    return ValidatorInput(
        model_type="step00_fixture_model",
        model_file_path="/fixture/model.py",
        test_file_path="/fixture/test_model.py",
        description_file_path="/fixture/description.md",
        config_fields={"channels": 64, "depth": 2},
        model_description="Fixture description: a gated residual 1-D denoiser.",
        mathematical_definition="y = x + f(x) with f a dilated conv stack (fixture math).",
        expert_advice="Prefer small dilation stacks; keep channels <= 128.",
        human_advice="Keep the receptive field under 1000 samples.",
    )


class TestPB6CodeReview:
    def test_clean_branch(self):
        agent = MLCodeValidatorAgent(bridge_factory=_ReviewRecorder)
        agent._llm_review(fixture_input(), _FIXTURE_PLUGIN_SRC)
        assert len(agent.bridge.captures) == 1
        method, label, system, user = agent.bridge.captures[0]
        assert (method, label) == ("_chat_json", "validator.code_review")
        assert_golden(
            system, GOLDENS / "pb6_code_review_system.txt", surface="PB-6 code_review system"
        )
        assert_golden(
            user,
            GOLDENS / "pb6_code_review_user_clean.txt",
            surface="PB-6 code_review user (clean)",
        )

    def test_error_branch_with_frozen_errors(self):
        agent = MLCodeValidatorAgent(bridge_factory=_ReviewRecorder)
        agent._llm_review(
            fixture_input(),
            _FIXTURE_PLUGIN_SRC,
            test_output=(
                "FIXTURE PYTEST OUTPUT\nFAILED test_forward - RuntimeError: size mismatch\n"
            ),
            inst_err=("FIXTURE RUNTIME ERROR\nRuntimeError: shape [1, 64] is invalid\n"),
        )
        _, label, system, user = agent.bridge.captures[0]
        assert label == "validator.code_review"
        # System prompt is a static constant — identical across branches.
        assert_golden(
            system, GOLDENS / "pb6_code_review_system.txt", surface="PB-6 code_review system"
        )
        assert_golden(
            user,
            GOLDENS / "pb6_code_review_user_errors.txt",
            surface="PB-6 code_review user (errors)",
        )
