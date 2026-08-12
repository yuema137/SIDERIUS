"""PR 01a — unit pins for the proposer's contract/loss renderers.

Design: `docs/design/generic_framework_upgrade/
step_01_proposer_hypothesis_space/pr_01a_contract_derived_prompt_extraction.md`
(§3.2 import strategy, §4 commit S1-A) and parent §6.2 rules 5 and 6.

These are the renderer-level contracts. The end-to-end byte-parity claim
lives in `test_step00_prompt_goldens.py` (PB-4, captured at the LLM
boundary); this file pins the properties that golden alone cannot show:
deterministic ordering, authority-derivation, fail-closed behaviour and
opaque pass-through of an undeclared task.
"""

from __future__ import annotations

import re

import pytest

from agent.schemas.task_config import ForwardContract
from ml_models.models_format_sandbox import CLASSIFICATION_LOSSES, REGRESSION_LOSSES
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    PROPOSAL_COMMIT_PROMPT,
    ProposalContractRenderError,
    _render_commit_system_prompt,
    _render_loss_legality,
)


def _contract(**overrides) -> ForwardContract:
    base = dict(
        input_shape="[B, T] int64",
        input_description="per-timestep ADC class indices",
        output_shape="[B, 256, T] float32",
        output_description="per-timestep logits over 256 denoising classes",
        num_classes=256,
        task_type="classification",
    )
    base.update(overrides)
    return ForwardContract(**base)


class TestLossLegalityRenderer:
    def test_renders_sorted_backticked_list(self):
        assert _render_loss_legality(CLASSIFICATION_LOSSES) == "`ce`, `focal`, `focal_cw`"
        assert _render_loss_legality(REGRESSION_LOSSES) == "`smooth_l1`"

    def test_order_is_deterministic_not_set_iteration(self):
        """Parent §6.2 rule 5 (finding F4b): frozenset iteration order
        varies per process, so a renderer that iterated directly would
        make every prompt golden flaky. Feeding the same members in a
        different construction order must render identically."""
        shuffled = frozenset({"focal_cw", "ce", "focal"})
        assert _render_loss_legality(shuffled) == _render_loss_legality(CLASSIFICATION_LOSSES)

    def test_derives_from_the_authority_not_a_local_copy(self):
        """Adding a family member must change the render — proving the
        renderer reads the authority instead of restating it."""
        extended = CLASSIFICATION_LOSSES | {"aaa_probe_loss"}
        assert _render_loss_legality(extended) == "`aaa_probe_loss`, `ce`, `focal`, `focal_cw`"

    def test_empty_family_fails_closed(self):
        with pytest.raises(ProposalContractRenderError, match="declares no legal loss_type"):
            _render_loss_legality(frozenset())


class TestCommitSystemPromptRenderer:
    def test_no_placeholder_survives_the_render(self):
        """No `{UPPERCASE}` placeholder may reach the LLM.

        Scoped to the placeholder shape rather than a bare "{" because
        the prompt legitimately embeds a JSON skeleton (`{ "model_name":
        ... }`) — a naive brace check fails on the skeleton and would
        have to be weakened, hiding real unsubstituted tokens.
        """
        rendered = _render_commit_system_prompt(_contract())
        assert re.findall(r"\{[A-Z][A-Z_]*\}", rendered) == []

    def test_declared_values_reach_the_prompt(self):
        rendered = _render_commit_system_prompt(
            _contract(
                input_shape="[B, S, F1, F2] float32",
                output_shape="[B, S, F3] float32",
                output_description="per-sample target features",
            )
        )
        assert "[B, S, F1, F2] float32" in rendered
        assert "[B, S, F3] float32" in rendered
        assert "per-sample target features" in rendered

    def test_no_shadow_literal_survives_a_non_tidmad_profile(self):
        """A re-inlined literal at ANY substitution site must be caught.

        Mutation-architecture finding (S1-A battery): mutation M-4
        re-inlined `[B, T] int64` at one of the three `{INPUT_SHAPE}`
        sites and SURVIVED, because `"<declared>" in rendered` is
        satisfied by the OTHER sites still rendering correctly. An `in`
        assertion cannot see a partial shadow.

        This pin closes it at the renderer level: under a profile that
        declares neither TIDMAD shape, the TIDMAD shape tokens must be
        ABSENT from the render. Scoped to the two tokens that can only
        arrive via substitution — `[B, T] int64` (input) and
        `[B, 256, T] float32` (output-with-dtype). The parent §9.5
        whitelisted survivors are deliberately NOT asserted against:
        the dtype-dropped `[B, 256, T]` (tier ii), the regressor form
        `[B, T] float32 (the denoised waveform directly)` (tier iii)
        and the "256 denoising bins" noun all legitimately remain.
        """
        rendered = _render_commit_system_prompt(
            _contract(
                input_shape="[B, S, F1, F2] float32",
                output_shape="[B, S, F3] float32",
                output_description="per-sample target features",
            )
        )
        assert "[B, T] int64" not in rendered
        assert "[B, 256, T] float32" not in rendered
        # …while the whitelisted, unowned literals are still there:
        assert "[B, T] float32 (the denoised waveform directly)" in rendered
        assert "[B, 256, T] per-timestep class logits" in rendered

    def test_unfamiliar_task_type_and_rank_pass_through_opaquely(self):
        """Parent §6A.4: no renderer may branch on rank, axis names or
        `task_type` meaning. An unfamiliar declaration must render, not
        raise and not take a different path."""
        rendered = _render_commit_system_prompt(
            _contract(
                input_shape="[B, D1, D2, D3, D4] bfloat16",
                output_shape="[B, D1, D5] bfloat16",
                output_description="opaque declared output",
                task_type="operator_defined_xyz",
                num_classes=0,
            )
        )
        assert "[B, D1, D2, D3, D4] bfloat16" in rendered
        assert "opaque declared output" in rendered

    @pytest.mark.parametrize("missing", ["input_shape", "output_shape", "output_description"])
    def test_empty_declaration_fails_closed(self, missing):
        """Parent §6.2 rule 6 (finding F9): before extraction an absent
        contract was harmless because the prompt was a constant; now an
        empty field would silently delete the I/O contract from a
        production-reachable path. It must raise instead."""
        with pytest.raises(ProposalContractRenderError, match=missing):
            _render_commit_system_prompt(_contract(**{missing: ""}))

    def test_default_constructed_contract_fails_closed(self):
        with pytest.raises(ProposalContractRenderError):
            _render_commit_system_prompt(ForwardContract())

    def test_template_still_carries_the_placeholders(self):
        """If someone re-inlines the literals, the extraction is undone
        even though every golden would still pass."""
        for token in (
            "{INPUT_SHAPE}",
            "{OUTPUT_SHAPE}",
            "{OUTPUT_DESCRIPTION}",
            "{CLASSIFIER_LOSSES}",
            "{REGRESSOR_LOSSES}",
        ):
            assert token in PROPOSAL_COMMIT_PROMPT

    def test_tier_iii_literals_are_deliberately_retained(self):
        """Design §4.1 tier (iii): the regressor output form and the
        "denoising bins" nouns have NO authority to render from, so they
        stay literal and are routed to step 03. Pinned so a later
        contributor does not "finish the job" by inventing an authority.
        """
        rendered = _render_commit_system_prompt(_contract())
        assert "[B, T] float32 (the denoised waveform directly)" in rendered
        assert "256 denoising bins per time step is contract-fixed" in rendered
