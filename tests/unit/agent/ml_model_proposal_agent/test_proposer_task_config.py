"""
Unit tests for the T3 placeholder-substitution path in the proposer system
prompt and the proposal-stage ``.md`` templates.

Coverage:

* ``_render_task_background`` — non-empty contract → "Background on the task:"
  header + bullet + rendered contract; empty contract → "".
* ``_build_reasoning_system_prompt`` — ``{TASK_BACKGROUND}`` placeholder is
  always substituted; custom task description replaces the SQUID hardcode,
  custom output_shape replaces the [B, 256, T] hardcode, the placeholder
  literal never survives into the rendered output.
* ``proposing_stage.md`` — ``{forward_contract}`` placeholder is rendered via
  ``load_stage_prompt(template_vars=...)``; the SQUID classifier shape is
  substituted at render time, not hardcoded.
* ``comparison_stage.md`` — no longer mentions TIDMAD; persona reads
  "model architectures" (task-agnostic).
* ``search_decision_system.md`` — persona reads "ML research agent"
  (was "ML denoising research agent" — task framing now lives only in the
  existing ``{TASK_DESCRIPTION}`` placeholder at line 12).

See docs/design/enable_global_task_config.md § Commit T3.
"""

from __future__ import annotations

from pathlib import Path

from agent.prompt_templates.proposal import load_stage_prompt
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    PROPOSAL_REASONING_PROMPT,
    _build_reasoning_system_prompt,
    _render_task_background,
)
from workflows.task_config import render_forward_contract


def _make_input(
    task_description: str = "",
    fc: ForwardContract | None = None,
) -> ProposalInput:
    """Minimal ProposalInput with the two T3 fields injectable."""
    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(
            {"model_types": [], "key_findings": [], "bottlenecks": []}
        ),
        existing_model_types=[],
        task_description=task_description,
        forward_contract=fc if fc is not None else ForwardContract(),
    )


def _squid_fc() -> ForwardContract:
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
# _render_task_background (proposer)
# ---------------------------------------------------------------------------


class TestRenderTaskBackground:
    def test_both_empty_returns_empty_string(self):
        assert _render_task_background("", ForwardContract()) == ""

    def test_full_populated_contains_header_description_and_contract(self):
        block = _render_task_background("denoising SQUID data", _squid_fc())
        assert "Background on the task:" in block
        assert "denoising SQUID data" in block
        assert "[B, T] int64" in block
        assert "[B, 256, T] float32" in block
        assert "classification" in block
        assert block.endswith("\n")

    def test_task_description_only_contains_bullet_no_contract_block(self):
        block = _render_task_background("solo task", ForwardContract())
        assert "Background on the task:" in block
        assert "solo task" in block
        assert "[B," not in block


# ---------------------------------------------------------------------------
# _build_reasoning_system_prompt (proposer's PROPOSAL_REASONING_PROMPT)
# ---------------------------------------------------------------------------


class TestBuildReasoningSystemPrompt:
    def test_placeholder_never_survives_into_output(self):
        prompt = _build_reasoning_system_prompt(_make_input())
        assert "{TASK_BACKGROUND}" not in prompt
        # Sanity: template carries the placeholder.
        assert "{TASK_BACKGROUND}" in PROPOSAL_REASONING_PROMPT

    def test_custom_task_description_replaces_squid_hardcode(self):
        inp = _make_input(task_description="alt-domain audio enhancement", fc=_custom_fc())
        prompt = _build_reasoning_system_prompt(inp)
        assert "alt-domain audio enhancement" in prompt
        # Old SQUID-specific hardcodes are gone (they used to be in lines
        # 178-186 of PROPOSAL_REASONING_PROMPT pre-T3).
        assert "TIDMAD" not in prompt
        assert "SQUID" not in prompt
        assert "magnetometry" not in prompt
        assert "ADC" not in prompt
        # Custom regressor shape:
        assert "[B, T] float32" in prompt
        assert "[B, 256, T] float32" not in prompt

    def test_squid_input_reproduces_task_anchors(self):
        inp = _make_input(
            task_description="TIDMAD SQUID magnetometry denoising",
            fc=_squid_fc(),
        )
        prompt = _build_reasoning_system_prompt(inp)
        assert "TIDMAD SQUID" in prompt
        assert "[B, T] int64" in prompt
        assert "[B, 256, T] float32" in prompt

    def test_vram_ceiling_guidance_preserved(self):
        # The VRAM-ceiling guidance is template-resident (after the
        # {TASK_BACKGROUND} placeholder) and must remain regardless of input.
        prompt = _build_reasoning_system_prompt(_make_input())
        assert "VRAM ceiling" in prompt
        assert "HARDWARE CONTEXT" in prompt
        assert "parameter_count_estimate" in prompt

    def test_dropped_loss_line_is_gone(self):
        # The pre-T3 system prompt hardcoded
        #   "Loss is cross-entropy or focal loss: per-timestep 256-class classification."
        # T3 dropped this line — the proposer chooses a loss and the executor's
        # ExperimentConfig validator catches incompatible model/loss combos.
        prompt = _build_reasoning_system_prompt(_make_input(fc=_squid_fc()))
        assert "Loss is cross-entropy or focal loss" not in prompt

    def test_dropped_segment_length_is_gone(self):
        # The pre-T3 system prompt hardcoded
        #   "signal length up to 40000 timesteps per segment."
        # T3 dropped this line — segmentation_size is conveyed dynamically
        # via baseline_config.train_config in the user prompt.
        prompt = _build_reasoning_system_prompt(_make_input(fc=_squid_fc()))
        assert "40000" not in prompt


# ---------------------------------------------------------------------------
# proposing_stage.md — {forward_contract} substitution via load_stage_prompt
# ---------------------------------------------------------------------------


class TestProposingStageMdSubstitution:
    def test_placeholder_substituted_with_squid_default(self):
        template_vars = {
            "minimum_boldness": "0.05",
            "n_agent_proposed": "3",
            "n_confirmed_links": "0",
            "existing_model_types": "punet, wavenet",
            "known_constraints_block": "",
            "recent_gate_exhaustions_block": "",
            "task_description": "SQUID denoising",
            "forward_contract": render_forward_contract(_squid_fc()),
        }
        prompt = load_stage_prompt(
            "proposing_stage", exploration_mode="explore", template_vars=template_vars
        )
        # The placeholder literal must not survive.
        assert "{forward_contract}" not in prompt
        # The rendered SQUID contract appears in the prompt body.
        assert "[B, T] int64" in prompt
        assert "[B, 256, T] float32" in prompt

    def test_placeholder_substituted_with_custom_contract(self):
        template_vars = {
            "minimum_boldness": "0.05",
            "n_agent_proposed": "3",
            "n_confirmed_links": "0",
            "existing_model_types": "punet",
            "known_constraints_block": "",
            "recent_gate_exhaustions_block": "",
            "task_description": "audio enhancement",
            "forward_contract": render_forward_contract(_custom_fc()),
        }
        prompt = load_stage_prompt(
            "proposing_stage", exploration_mode="explore", template_vars=template_vars
        )
        assert "{forward_contract}" not in prompt
        # Custom regressor shape present:
        assert "[B, T] float32" in prompt
        # SQUID classifier shape gone — confirms the old hardcoded block was
        # replaced, not just supplemented.
        assert "[B, 256, T] float32" not in prompt


# ---------------------------------------------------------------------------
# comparison_stage.md — TIDMAD removed
# ---------------------------------------------------------------------------


class TestComparisonStageMdContent:
    def _md_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[4]
            / "src/agent/prompt_templates/proposal/comparison_stage.md"
        )

    def test_tidmad_no_longer_mentioned(self):
        body = self._md_path().read_text(encoding="utf-8")
        assert "TIDMAD" not in body

    def test_persona_reads_model_architectures(self):
        body = self._md_path().read_text(encoding="utf-8")
        # T3-chosen replacement phrasing — minimal substitution that keeps
        # the sentence natural without re-introducing task framing.
        assert "previously tested model architectures" in body


# ---------------------------------------------------------------------------
# search_decision_system.md — persona generalized
# ---------------------------------------------------------------------------


class TestLitReviewSearchDecisionPersona:
    def _md_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[4]
            / "src/agent/prompt_templates/literature_review/search_decision_system.md"
        )

    def test_persona_is_generic(self):
        body = self._md_path().read_text(encoding="utf-8")
        # First line is the persona anchor.
        first_line = body.splitlines()[0]
        assert first_line == "You are the search strategist for an automated ML research agent."

    def test_task_description_placeholder_still_present(self):
        # The {TASK_DESCRIPTION} placeholder at line 12 carries the actual
        # task framing; it must not have been accidentally removed.
        body = self._md_path().read_text(encoding="utf-8")
        assert "{TASK_DESCRIPTION}" in body


# ---------------------------------------------------------------------------
# Workflow injection — propose_input.task_description / forward_contract
# are mutated by the workflow at the proposer call site. The schema-default
# path is exercised here so a future regression on the field defaults fires.
# ---------------------------------------------------------------------------


class TestProposalInputTaskConfigFields:
    def test_defaults_are_empty(self):
        inp = ProposalInput(
            interpretation_evidence=build_proposer_evidence({}),
            existing_model_types=[],
        )
        assert inp.task_description == ""
        assert inp.forward_contract.is_empty()

    def test_fields_round_trip_through_pydantic(self):
        inp = ProposalInput(
            interpretation_evidence=build_proposer_evidence({}),
            existing_model_types=[],
            task_description="hello",
            forward_contract=_squid_fc(),
        )
        # Round-trip through model_dump / model_validate.
        as_dict = inp.model_dump()
        rehydrated = ProposalInput.model_validate(as_dict)
        assert rehydrated.task_description == "hello"
        assert rehydrated.forward_contract.input_shape == "[B, T] int64"
