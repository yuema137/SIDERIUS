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

from agent.schemas.implementor import ImplementorInput, ImplementorTaskBlocks
from agent.schemas.proposal import CustomLossSpec
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_implementor.ml_model_implementor import (
    MLModelImplementor,
    _build_code_prompt,
    _build_loss_repair_prompt,
    _build_loss_repair_system_prompt,
    _build_reasoning_prompt,
    _build_repair_prompt,
    _build_repair_system_prompt,
)
from tests.helpers.constraint_disclosure import without_incomplete_disclosure
from tests.helpers.golden import assert_golden
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.helpers.probe_seed import PROBE_SEED

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

    Task prose is explicitly test-owned. The old no-path task-block loader
    correctly supplies no science after separation; it cannot provide this
    fixture's role specialism. Byte oracles continue to protect section order,
    code constraints and repair history, not an ambient scientific default.
    """
    base = dict(
        implementor_blocks=ImplementorTaskBlocks(
            science_domain="synthetic sequence reconstruction"
        ),
        model_name="step00_fixture_model",
        model_description="Fixture description: a gated residual 1-D denoiser.",
        mathematical_definition="y = x + f(x) with f a dilated conv stack (fixture math).",
        baseline_config={
            "model_config": {"channels": 64, "depth": 2},
            "train_config": {"batch_size": 1, "segmentation_size": 64},
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
            probe_seed=PROBE_SEED,
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
        assert_golden(
            without_incomplete_disclosure(u0),
            GOLDENS / "pb5_reasoning_user.txt",
            surface="PB-5 reasoning user",
        )
        assert_golden(s1, GOLDENS / "pb5_code_system.txt", surface="PB-5 code system")
        assert_golden(
            without_incomplete_disclosure(u1),
            GOLDENS / "pb5_code_user.txt",
            surface="PB-5 code user",
        )

    def test_loss_reasoning_and_code_prompts(self, tmp_path):
        agent = MLModelImplementor(
            bridge_factory=_AbortingRecorder,
            capability_index_path=str(tmp_path / "idx.json"),
            probe_seed=PROBE_SEED,
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
            without_incomplete_disclosure(u0),
            GOLDENS / "pb5_loss_reasoning_user.txt",
            surface="PB-5 loss reasoning user",
        )
        assert_golden(s1, GOLDENS / "pb5_loss_code_system.txt", surface="PB-5 loss code system")
        assert_golden(
            without_incomplete_disclosure(u1),
            GOLDENS / "pb5_loss_code_user.txt",
            surface="PB-5 loss code user",
        )


class TestPB5RepairPrompts:
    def test_repair_system_prompts(self):
        """Since #1574 a repair's system prompt carries the code call's contract."""
        assert_golden(
            _build_repair_system_prompt(fixture_input()),
            GOLDENS / "pb5_repair_system.txt",
            surface="PB-5 repair system",
        )
        assert_golden(
            _build_loss_repair_system_prompt(),
            GOLDENS / "pb5_loss_repair_system.txt",
            surface="PB-5 loss repair system",
        )

    def test_profile_restores_pre_1574_repair_system_prompts(self, tmp_path):
        """The siderius-exp pin: a profile returning the historical constant per
        ``kind`` reproduces the repair system prompts captured before #1574
        (``pb5_pre1574_*``, the former goldens of the removed constants). Fails
        if a builder bypasses the ``implementor.repair_system`` boundary or
        decorates its output."""
        from agent.prompt_rendering import PromptRenderingProfile, bind_prompt_profile

        historical = {
            kind: (GOLDENS / f"pb5_pre1574_{name}repair_system.txt").read_text(encoding="utf-8")
            for kind, name in (("model", ""), ("loss", "loss_"))
        }
        source = tmp_path / "provider.txt"
        source.write_text("pre-1574 repair system renderer")
        profile = PromptRenderingProfile(
            "pre-1574",
            "1",
            {"implementor.repair_system": lambda kind, code_contract: historical[kind]},
            frozenset({"native_training.appendix"}),
            {"source": source},
        )
        with bind_prompt_profile(profile):
            model = _build_repair_system_prompt(fixture_input())
            loss = _build_loss_repair_system_prompt()
        assert_golden(model, GOLDENS / "pb5_pre1574_repair_system.txt", surface="pre-1574 model")
        assert_golden(loss, GOLDENS / "pb5_pre1574_loss_repair_system.txt", surface="pre-1574 loss")

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


class TestPB5NoReferencePrompts:
    """Prompts for a proposal without ancestor source stay byte-identical (#1530).

    The goldens were captured at 5ccb436f8, before the code and repair calls
    gained the ancestor section, from ``fixture_input(reference_code={})``.
    They fail if supplying the section to more calls adds any byte (an empty
    heading, a separator) when no ancestor exists, which would move every
    paper-era implementor prompt. The fixture carries a validator rejection,
    which the code and repair calls render since #1572; the test pins that
    axis with the empty ``implementor.validator_feedback`` renderer (the
    siderius-exp pin) so it keeps isolating the reference axis.
    """

    def test_reasoning_code_and_repair_user_prompts(self, tmp_path):
        from agent.prompt_rendering import bind_prompt_profile

        inp = fixture_input(reference_code={})
        with bind_prompt_profile(_pinned_profile(tmp_path, {})):
            rendered = self._render(inp)
        for name, text in rendered.items():
            assert_golden(text, GOLDENS / name, surface=f"PB-5 no-reference {name}")

    @staticmethod
    def _render(inp):
        return {
            "pb5_no_reference_reasoning_user.txt": _build_reasoning_prompt(inp),
            "pb5_no_reference_code_user.txt": _build_code_prompt("FIXTURE REASONING", inp),
            "pb5_no_reference_repair_user.txt": _build_repair_prompt(
                _FROZEN_CODE_DICT, _FROZEN_ERROR, inp, [(1, "earlier")]
            ),
        }


def _pinned_profile(tmp_path, renderers):
    """A profile pinning the pre-#1572 code/repair prompts (empty feedback
    renderer) plus ``renderers``; other implementor boundaries stay native."""
    from agent.prompt_rendering import PromptRenderingProfile

    source = tmp_path / "provider.txt"
    source.write_text("pre-1572 validator feedback renderer")
    native = {"implementor.reference_code"} - set(renderers)
    return PromptRenderingProfile(
        "pre-1572",
        "1",
        {"implementor.validator_feedback": lambda **_: "", **renderers},
        frozenset(native),
        {"source": source},
    )


class TestPB5NoRejectionPrompts:
    """Without a validator rejection the code and repair calls gain no bytes
    (#1572). Goldens captured at 9910a2153 from
    ``fixture_input(previous_validation_failure=None)``; they fail if the
    feedback section adds a heading or separator when nothing was rejected."""

    def test_code_and_repair_user_prompts(self):
        inp = fixture_input(previous_validation_failure=None)
        rendered = {
            "pb5_no_rejection_code_user.txt": _build_code_prompt("R", inp),
            "pb5_no_rejection_repair_user.txt": _build_repair_prompt(
                _FROZEN_CODE_DICT, _FROZEN_ERROR, inp, [(1, "e")]
            ),
        }
        for name, text in rendered.items():
            assert_golden(text, GOLDENS / name, surface=f"PB-5 no-rejection {name}")


# Test-owned copy of the pre-#1530 reasoning-only reference block (5ccb436f8,
# ml_model_implementor.py:1389-1422). It is the renderer text an experiment
# profile declares to pin paper-era prompts for proposals with ancestors.
_PRE_1530_REFERENCE_PREAMBLE = (
    "## Reference Code (from ancestor models — for ARCHITECTURAL INSPIRATION ONLY)",
    "",
    "⚠ WARNING — read before using the snippets below:",
    "",
    "1. Private helper classes (e.g. `CausalConv1d`, `WaveNetBlock`,",
    "   `DoubleConv`, `PositionalEncoding`, `Down`, `Up`, etc.) shown below",
    "   are NOT available in your plugin's runtime — they live in",
    "   `ml_models/models_sandbox.py` which the plugin loader does not import.",
    "   You MUST inline their logic using only the allowed primitives",
    "   (torch, torch.nn, torch.nn.functional). Do NOT reference these helper",
    "   class names in your `init_body` or `forward_body` — that produces",
    "   `NameError` at smoke-test time.",
    "",
    "2. The `self.config = config` + `self.config.X` access pattern that some",
    "   reference samples use is FORBIDDEN in your plugin. The `config` object",
    "   is only in scope during `__init__`. Store every value you need as a",
    "   plain attribute on `self` (e.g. `self.channels = config.channels`)",
    "   inside `init_body`, then reference `self.channels` in `forward_body`.",
    "",
    "3. Use the references for architectural ideas (block structure, dilation",
    "   schedules, skip-connection topology) — not as code to copy verbatim.",
    "",
)


def _pre_1530_reference(reference_code: dict[str, str], stage: str) -> str:
    if stage != "reasoning":
        return ""
    lines = list(_PRE_1530_REFERENCE_PREAMBLE)
    for model_type, source in reference_code.items():
        lines += [
            f"### {model_type} (reference implementation — inspiration only)",
            "```python",
            source,
            "```",
            "",
        ]
    return "\n".join(lines).rstrip("\n")


class TestPB5PreFix1530ProfilePin:
    """The ``implementor.reference_code`` boundary can restore paper-era bytes.

    With the pre-#1530 renderer bound, the reasoning, code and repair prompts
    of a proposal WITH an ancestor must equal the goldens committed at
    5ccb436f8. Fails if the builders' separators or placement around the
    boundary drift, which would make the siderius-exp pin unable to reproduce
    the paper prompts it exists to preserve.
    """

    def test_profile_reproduces_5ccb436f8_goldens(self, tmp_path):
        from agent.prompt_rendering import bind_prompt_profile

        # The paper pin needs both renderers since #1572: the fixture carries a
        # validator rejection, which the code and repair calls now render.
        profile = _pinned_profile(tmp_path, {"implementor.reference_code": _pre_1530_reference})
        inp = fixture_input()
        with bind_prompt_profile(profile):
            rendered = {
                "pb5_pre1530_reasoning_user.txt": _build_reasoning_prompt(inp),
                "pb5_pre1530_code_user.txt": _build_code_prompt(
                    "FIXTURE REASONING TEXT (test-owned, frozen)", inp
                ),
                "pb5_pre1530_repair_user_attempt2.txt": _build_repair_prompt(
                    _FROZEN_CODE_DICT,
                    _FROZEN_ERROR,
                    inp,
                    [(1, "Attempt-1 frozen error: fixture forward returned [B, 255, T].")],
                ),
            }
        for name, text in rendered.items():
            assert_golden(text, GOLDENS / name, surface=f"PB-5 pre-#1530 pin {name}")


def test_ancestor_order_does_not_change_prompt_bytes():
    """Several ancestors render in one order whatever the mapping's insertion
    order. Fails if the renderer follows insertion order, which the native loop
    derives from a set whose order varies with PYTHONHASHSEED across processes."""
    first = {"alpha_model": "# alpha source\n", "beta_model": "# beta source\n"}
    second = dict(reversed(list(first.items())))
    for build in (
        _build_reasoning_prompt,
        lambda inp: _build_code_prompt("reasoning", inp),
        lambda inp: _build_repair_prompt(_FROZEN_CODE_DICT, _FROZEN_ERROR, inp, []),
    ):
        assert build(fixture_input(reference_code=first)) == build(
            fixture_input(reference_code=second)
        )
