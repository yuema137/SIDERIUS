"""
Unit tests for the T2 placeholder-substitution path in the implementor's
system + user prompts.

Coverage:

* ``_render_task_background`` — non-empty contract → "Background on the task:"
  header + bullet + rendered contract; empty contract → "".
* ``_build_reasoning_system_prompt`` — ``{TASK_BACKGROUND}`` placeholder is
  always substituted (custom task description replaces the SQUID hardcode,
  custom output_shape replaces the [B, 256, T] hardcode, the placeholder
  literal never survives into the rendered output).
* ``_build_code_system_prompt`` — ``{OUTPUT_SHAPE}`` placeholder is always
  substituted; custom output_shape replaces the [B, 256, T] hardcode.
* ``_build_reasoning_prompt`` (user prompt) — when ``forward_contract`` is
  populated, the rendered block contains the contract; when empty (test
  fixture), the "## Forward contract" section is omitted entirely.

See docs/design/enable_global_task_config.md § Commit T2.
"""

from __future__ import annotations

import pytest

from agent.schemas.implementor import ImplementorInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_implementor.ml_model_implementor import (
    IMPLEMENTOR_CODE_PROMPT,
    IMPLEMENTOR_REASONING_PROMPT,
    _build_code_system_prompt,
    _build_reasoning_prompt,
    _build_reasoning_system_prompt,
    _render_task_background,
)


def _make_input(
    task_description: str = "",
    fc: ForwardContract | None = None,
) -> ImplementorInput:
    """Minimal ImplementorInput with the two T2 fields injectable."""
    return ImplementorInput(
        model_name="test_model",
        model_description="A test model.",
        mathematical_definition="Linear → ReLU → Linear",
        baseline_config={"model_config": {}, "train_config": {}},
        task_description=task_description,
        forward_contract=fc if fc is not None else ForwardContract(),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="/tmp/test", run_name="r1"),
        ),
    )


def _squid_fc() -> ForwardContract:
    """Populated SQUID-style contract matching configs/task_config.yaml."""
    return ForwardContract(
        input_shape="[B, T] int64",
        input_description="raw signal, integer class indices 0-255",
        output_shape="[B, 256, T] float32",
        output_description="per-timestep logits over 256 denoising classes",
        num_classes=256,
        embedding_note="Use nn.Embedding(256, embed_dim).",
        output_head_note="Use a final Conv1d(channels, 256, 1) head.",
        task_type="classification",
        task_note="Offline denoising — non-causal.",
    )


def _custom_fc() -> ForwardContract:
    """Populated non-SQUID contract for the custom-shape test."""
    return ForwardContract(
        input_shape="[B, T] float32",
        input_description="raw audio, normalised",
        output_shape="[B, T] float32",
        output_description="denoised audio waveform",
        num_classes=0,
        embedding_note="",
        output_head_note="Use a Linear head.",
        task_type="regression",
        task_note="Causal masking required.",
    )


# ---------------------------------------------------------------------------
# _render_task_background
# ---------------------------------------------------------------------------


class TestRenderTaskBackground:
    def test_both_empty_returns_empty_string(self):
        assert _render_task_background("", ForwardContract()) == ""

    def test_full_populated_contains_header_description_and_contract(self):
        block = _render_task_background("denoising SQUID data", _squid_fc())
        assert "Background on the task:" in block
        assert "denoising SQUID data" in block
        # Forward-contract anchors from render_forward_contract():
        assert "[B, T] int64" in block
        assert "[B, 256, T] float32" in block
        assert "classification" in block
        # Trailing newline so the next template line starts cleanly.
        assert block.endswith("\n")

    def test_task_description_only_contains_bullet_no_contract_block(self):
        block = _render_task_background("solo task", ForwardContract())
        assert "Background on the task:" in block
        assert "solo task" in block
        # No contract → no shape literals.
        assert "[B," not in block

    def test_contract_only_no_description_omits_bullet(self):
        block = _render_task_background("", _squid_fc())
        assert "Background on the task:" in block
        # Forward-contract content is present.
        assert "[B, 256, T] float32" in block
        # No task-description bullet (the only bullet "- ..." we'd expect to
        # see when a description is set is its own line; verify the header
        # is immediately followed by the contract block, not a stray "- ").
        lines = block.splitlines()
        assert lines[0] == "Background on the task:"
        # Next non-empty line should NOT be a "- description" bullet.
        assert not lines[1].startswith("- ")


# ---------------------------------------------------------------------------
# _build_reasoning_system_prompt
# ---------------------------------------------------------------------------


class TestBuildReasoningSystemPrompt:
    def test_placeholder_never_survives_into_output(self):
        # Even on a fully-empty input — placeholder is replaced with "".
        prompt = _build_reasoning_system_prompt(_make_input())
        assert "{TASK_BACKGROUND}" not in prompt
        # And the template itself contains the placeholder (sanity check).
        assert "{TASK_BACKGROUND}" in IMPLEMENTOR_REASONING_PROMPT

    def test_custom_task_description_replaces_squid_hardcode(self):
        inp = _make_input(task_description="alt-domain audio enhancement", fc=_custom_fc())
        prompt = _build_reasoning_system_prompt(inp)
        # Custom value present:
        assert "alt-domain audio enhancement" in prompt
        # Old SQUID-specific hardcode is gone:
        assert "TIDMAD" not in prompt
        assert "SQUID" not in prompt
        assert "magnetometry" not in prompt
        # Custom output shape from the regressor contract:
        assert "[B, T] float32" in prompt
        # Old SQUID classifier shape from the rendered contract is gone:
        assert "[B, 256, T] float32" not in prompt

    def test_squid_input_reproduces_original_anchors(self):
        # When fed the SQUID defaults, the rendered output carries the same
        # task-anchoring strings the old hardcode used to provide — so
        # production behaviour is byte-equivalent at the LLM-prompt level.
        inp = _make_input(
            task_description="TIDMAD SQUID magnetometry denoising",
            fc=_squid_fc(),
        )
        prompt = _build_reasoning_system_prompt(inp)
        assert "TIDMAD SQUID" in prompt
        assert "[B, T] int64" in prompt
        assert "[B, 256, T] float32" in prompt

    def test_empty_input_renders_without_orphan_background_header(self):
        # Test fixtures that don't populate task_config should not surface
        # an empty "Background on the task:" header. Helper returns "" on
        # empty, so the template's surrounding lines collapse cleanly.
        prompt = _build_reasoning_system_prompt(_make_input())
        # No orphaned header without content.
        assert "Background on the task:\n\n- GPU budget" not in prompt
        assert "Background on the task:\n- GPU budget" not in prompt
        # The GPU-budget line (which is template-resident) still appears.
        assert "GPU budget" in prompt


# ---------------------------------------------------------------------------
# _build_code_system_prompt
# ---------------------------------------------------------------------------


class TestBuildCodeSystemPrompt:
    def test_placeholder_never_survives_into_output(self):
        prompt = _build_code_system_prompt(_make_input())
        assert "{OUTPUT_SHAPE}" not in prompt
        # Sanity: template carries the placeholder.
        assert "{OUTPUT_SHAPE}" in IMPLEMENTOR_CODE_PROMPT

    def test_squid_output_shape_substituted_twice(self):
        inp = _make_input(fc=_squid_fc())
        prompt = _build_code_system_prompt(inp)
        # IMPLEMENTOR_CODE_PROMPT contains {OUTPUT_SHAPE} twice (forward_body
        # description + hard-constraint bullet). Both must be substituted.
        assert prompt.count("[B, 256, T] float32") >= 2

    def test_custom_output_shape_replaces_squid_default(self):
        inp = _make_input(fc=_custom_fc())
        prompt = _build_code_system_prompt(inp)
        assert "[B, T] float32" in prompt
        # SQUID classifier shape is gone.
        assert "[B, 256, T] float32" not in prompt

    def test_empty_contract_falls_back_to_generic_shape(self):
        # Test-fixture-only path: the helper substitutes a generic
        # [B, C, T] float32 so the prompt reads naturally.
        prompt = _build_code_system_prompt(_make_input())
        assert "[B, C, T] float32" in prompt


# ---------------------------------------------------------------------------
# _build_reasoning_prompt (user prompt — has the second hardcode at the
# `## Forward contract` section)
# ---------------------------------------------------------------------------


class TestBuildReasoningUserPrompt:
    def test_contract_block_rendered_when_populated(self):
        inp = _make_input(fc=_squid_fc())
        prompt = _build_reasoning_prompt(inp)
        assert "## Forward contract (non-negotiable)" in prompt
        # Rendered contract content appears below the header.
        assert "[B, T] int64" in prompt
        assert "[B, 256, T] float32" in prompt

    def test_contract_block_omitted_when_empty(self):
        # When the contract is the default (empty) ForwardContract, the
        # whole "## Forward contract" section is suppressed — no orphan
        # header.
        inp = _make_input()
        prompt = _build_reasoning_prompt(inp)
        assert "## Forward contract" not in prompt

    def test_custom_contract_renders_custom_shapes_only(self):
        inp = _make_input(fc=_custom_fc())
        prompt = _build_reasoning_prompt(inp)
        assert "[B, T] float32" in prompt
        # No SQUID classifier shape leaked from the old hardcode.
        assert "[B, 256, T] float32" not in prompt
        # The user-prompt forward-contract section uses the new render path,
        # not the old "raw ADC signal" hardcode.
        assert "raw ADC signal" not in prompt


# ---------------------------------------------------------------------------
# Sanity guard — the deferred description.md output artifact
# (line 827 of ml_model_implementor.py) is intentionally NOT touched in T2.
# That hardcode is read by test_implementor_agent.py::TestDescriptionFile,
# so this guard fires only if a follow-up commit silently breaks the
# deferred scope.
# ---------------------------------------------------------------------------


class TestDeferredScope:
    @pytest.mark.parametrize(
        "deferred_phrase",
        [
            # Lines 80, 115, 120 — runtime dummy-tensor self-check
            "[1, 64] int64 → expected [1, 256, 64] float32",
            # Line 254 — plugin stub assembly comment
            "forward contract: input [B, T] int64 → output [B, 256, T] float32",
            # Line 827 — description.md auto-generation
            "**Forward contract:** `[B, T] int64 → [B, 256, T] float32`",
        ],
    )
    def test_deferred_hardcodes_still_present(self, deferred_phrase):
        """Failing this means a deferred Category B/C/D hardcode was
        accidentally touched without updating the design doc + the
        existing test_implementor_agent.py::TestDescriptionFile suite."""
        from pathlib import Path

        impl_path = (
            Path(__file__).resolve().parents[4]
            / "nodes/ml_model_implementor/ml_model_implementor.py"
        )
        source = impl_path.read_text(encoding="utf-8")
        assert deferred_phrase in source, (
            f"Deferred hardcode {deferred_phrase!r} was removed; either fold it "
            f"into T2's scope properly or revert. See "
            f"docs/design/enable_global_task_config.md § Commit T2."
        )
