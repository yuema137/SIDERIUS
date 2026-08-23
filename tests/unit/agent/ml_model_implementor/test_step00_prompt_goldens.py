"""Step-00 PB-5 — implementor prompt goldens (6 boundary surfaces).

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.1 / §15.1 (roadmap step 04 A-surface: "ALL remaining rendered prompts
EXACT-equal").

Capture strategy: model reasoning/code and loss reasoning/code are captured
through the REAL ``run()`` / ``_generate_loss()`` call sites with an
aborting boundary recorder (the run is stopped right after the last needed
capture, BEFORE the environment-coupled smoke test executes the canned
code). The repair prompts are branch-only surfaces whose production driver
is a nondeterministic validator error string, so they are rendered through
the real producers with FROZEN error strings (design §13.1: never let a
golden capture a live validator error — pydantic version URLs, absolute
temp paths, unseeded torch values).

All source-embedding inputs (``reference_code``, descriptions, configs)
are TEST-OWNED frozen values — no production source text in goldens. The
capability registry is always pointed at a tmp_path index (never the live
``agent_generated/_capability_index.json``).
"""

from __future__ import annotations

from pathlib import Path

from agent.prompt_templates.implementor.task_blocks import load_implementor_task_blocks
from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import CustomLossSpec
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_implementor.ml_model_implementor import (
    IMPLEMENTOR_LOSS_REPAIR_PROMPT,
    IMPLEMENTOR_REPAIR_PROMPT,
    MLModelImplementor,
    _build_loss_repair_prompt,
    _build_repair_prompt,
)
from tests.helpers.golden import assert_golden
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge

GOLDENS = Path(__file__).parent / "goldens"


class _StopCapture(Exception):
    """Abort the agent at the boundary, before env-coupled validation."""


class _AbortingRecorder(BoundaryRecorderBridge):
    """Records the first ``stop_after`` boundary calls, then raises."""

    stop_after = 2

    def _maybe_stop(self):
        if len(self.captures) >= self.stop_after:
            raise _StopCapture

    def generate_text(self, *a, **k):
        super().generate_text(*a, **k)
        self._maybe_stop()
        return "FIXTURE REASONING TEXT (test-owned, frozen)"

    def _chat_json(self, *a, **k):
        super()._chat_json(*a, **k)
        self._maybe_stop()
        return {}


def fixture_forward_contract() -> ForwardContract:
    return ForwardContract(
        input_shape="[B, T] int64",
        input_description="noisy int8 samples shifted to class indices",
        output_shape="[B, 256, T] float32",
        output_description="per-timestep logits over 256 denoising classes",
        num_classes=256,
        task_type="classification",
    )


def fixture_input(**overrides) -> ImplementorInput:
    """All-optional-sections-ON input: one golden pins the full section
    order (Expert < Human < Reference < PreviousFailure).

    Step 12 / PR-12a C7-4: the PB goldens pin the LEGACY un-composed prompt
    surface, so this fixture resolves the bounded Regime-A adapter exactly as
    the composition root does for a run with no manifest. The goldens are
    therefore unchanged — which is the property C7-4 had to preserve.
    """
    base = dict(
        implementor_blocks=load_implementor_task_blocks(),
        model_name="step00_fixture_model",
        model_description="Fixture description: a gated residual 1-D denoiser.",
        mathematical_definition="y = x + f(x) with f a dilated conv stack (fixture math).",
        baseline_config={
            "model_config": {"channels": 64, "depth": 2},
            "train_config": {"batch_size": 1, "segmentation_size": 40000},
            "loss_config": {"loss_type": "focal"},
        },
        task_description="Step-00 fixture task: denoise a synthetic 1-D int8 series.",
        forward_contract=fixture_forward_contract(),
        expert_advice="Prefer small dilation stacks; keep channels <= 128.",
        human_advice="Keep the receptive field under 1000 samples.",
        reference_code={
            "step00_fixture_ref": (
                "# TEST-OWNED reference snippet (design §13.1 — never production source)\n"
                "class Step00RefBlock(nn.Module):\n"
                "    def forward(self, x):\n"
                "        return x\n"
            )
        },
        previous_validation_failure="Previous attempt failed: fixture shape mismatch [B, 255, T].",
        max_retries=0,
    )
    base.update(overrides)
    return ImplementorInput(**base)


def fixture_loss_spec() -> CustomLossSpec:
    return CustomLossSpec(
        loss_name="step00_fixture_loss",
        description="Fixture loss: focal variant with amplitude weighting.",
        mathematical_definition="L = -(1-p)^gamma log(p) * w(a) (fixture math).",
        config_fields={"gamma": 2.0, "amp_weight": 0.5},
    )


_FROZEN_CODE_DICT = {
    "config_fields_code": 'channels: int = Field(default=64, description="width")',
    "init_body": "self.net = nn.Conv1d(1, config.channels, 3)",
    "forward_body": "return self.net(x.float().unsqueeze(1))",
}

_FROZEN_ERROR = (
    "Config field consistency: init_body references config fields not "
    "declared in config_fields_code: ['gate_channels']. Each config.<field> "
    "used in __init__ must have a corresponding Pydantic Field definition."
)


class TestPB5ModelPrompts:
    def test_reasoning_and_code_prompts_via_run(self, tmp_path):
        agent = MLModelImplementor(
            bridge_factory=_AbortingRecorder,
            capability_index_path=str(tmp_path / "idx.json"),
        )
        inp = fixture_input(
            plugin_dir=str(tmp_path / "m"),
            test_dir=str(tmp_path / "t"),
            loss_dir=str(tmp_path / "l"),
        )
        try:
            agent.run(inp)
        except _StopCapture:
            pass
        assert len(agent.bridge.captures) == 2, "recorder must capture reasoning + code"
        m0, l0, s0, u0 = agent.bridge.captures[0]
        assert (m0, l0) == ("generate_text", "implementor.reasoning")
        m1, l1, s1, u1 = agent.bridge.captures[1]
        assert (m1, l1) == ("_chat_json", "implementor.code")
        assert_golden(s0, GOLDENS / "pb5_reasoning_system.txt", surface="PB-5 reasoning system")
        assert_golden(u0, GOLDENS / "pb5_reasoning_user.txt", surface="PB-5 reasoning user")
        assert_golden(s1, GOLDENS / "pb5_code_system.txt", surface="PB-5 code system")
        assert_golden(u1, GOLDENS / "pb5_code_user.txt", surface="PB-5 code user")

    def test_loss_reasoning_and_code_prompts(self, tmp_path):
        agent = MLModelImplementor(
            bridge_factory=_AbortingRecorder,
            capability_index_path=str(tmp_path / "idx.json"),
        )
        inp = fixture_input(
            custom_loss_spec=fixture_loss_spec(),
            plugin_dir=str(tmp_path / "m"),
            test_dir=str(tmp_path / "t"),
            loss_dir=str(tmp_path / "l"),
        )
        try:
            agent._generate_loss(inp)
        except _StopCapture:
            pass
        assert len(agent.bridge.captures) == 2
        m0, l0, s0, u0 = agent.bridge.captures[0]
        assert (m0, l0) == ("generate_text", "implementor.loss.reasoning")
        m1, l1, s1, u1 = agent.bridge.captures[1]
        assert (m1, l1) == ("_chat_json", "implementor.loss.code")
        assert_golden(
            s0, GOLDENS / "pb5_loss_reasoning_system.txt", surface="PB-5 loss reasoning system"
        )
        assert_golden(
            u0, GOLDENS / "pb5_loss_reasoning_user.txt", surface="PB-5 loss reasoning user"
        )
        assert_golden(s1, GOLDENS / "pb5_loss_code_system.txt", surface="PB-5 loss code system")
        assert_golden(u1, GOLDENS / "pb5_loss_code_user.txt", surface="PB-5 loss code user")


class TestPB5RepairPrompts:
    def test_repair_system_constants(self):
        assert_golden(
            IMPLEMENTOR_REPAIR_PROMPT,
            GOLDENS / "pb5_repair_system.txt",
            surface="PB-5 repair system",
        )
        assert_golden(
            IMPLEMENTOR_LOSS_REPAIR_PROMPT,
            GOLDENS / "pb5_loss_repair_system.txt",
            surface="PB-5 loss repair system",
        )

    def test_repair_user_first_attempt_empty_history(self):
        u = _build_repair_prompt(_FROZEN_CODE_DICT, _FROZEN_ERROR, fixture_input(), [])
        assert_golden(
            u, GOLDENS / "pb5_repair_user_attempt1.txt", surface="PB-5 repair user (attempt 1)"
        )

    def test_repair_user_with_error_history(self):
        u = _build_repair_prompt(
            _FROZEN_CODE_DICT,
            _FROZEN_ERROR,
            fixture_input(),
            [(1, "Attempt-1 frozen error: fixture forward returned [B, 255, T].")],
        )
        assert_golden(
            u, GOLDENS / "pb5_repair_user_attempt2.txt", surface="PB-5 repair user (history)"
        )

    def test_loss_repair_user(self):
        u = _build_loss_repair_prompt(
            _FROZEN_CODE_DICT,
            _FROZEN_ERROR,
            fixture_loss_spec(),
            [(1, "Attempt-1 frozen error: fixture loss returned NaN.")],
        )
        assert_golden(u, GOLDENS / "pb5_loss_repair_user.txt", surface="PB-5 loss repair user")
