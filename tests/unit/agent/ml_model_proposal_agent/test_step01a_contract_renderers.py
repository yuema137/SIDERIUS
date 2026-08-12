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

import json
import pathlib
import re
import typing

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


class TestS1BProposingStageDerivation:
    """S1-B — the production proposing stage derives its loss legality.

    Byte-parity is proven by the nine PB-3 goldens (unchanged). These
    pins prove the *derivation* underneath that parity, which byte
    equality alone cannot distinguish from a lucky literal.
    """

    TEMPLATE = (
        pathlib.Path(__file__).resolve().parents[4]
        / "agent"
        / "prompt_templates"
        / "proposal"
        / "proposing_stage.md"
    )

    def test_template_no_longer_carries_the_extracted_legality_literals(self):
        """Template-layer ABSENCE pin (kept distinct from the rendered
        pins per the roadmap's §13.3 rule: template properties and
        output properties prove different things)."""
        raw = self.TEMPLATE.read_text(encoding="utf-8")
        assert "{CLASSIFIER_LOSS_LIST}" in raw
        assert "{REGRESSOR_LOSS_LIST}" in raw
        # the extracted cells must not survive as literals in the table
        assert "| `ce`, `focal`, `focal_cw` |" not in raw

    def test_tier_ii_shape_column_deliberately_stays_literal(self):
        """OD-S1-7: the table's dtype-dropped shape column has no declared
        formatting rule, so it is NOT extracted. Pinned so a later
        contributor does not "finish the job" by inventing one."""
        raw = self.TEMPLATE.read_text(encoding="utf-8")
        assert "`[B, 256, T]` float" in raw
        assert "`[B, T]` float" in raw

    def test_builtin_alphabet_count_matches_the_declaration(self):
        """The template says the slot "accepts five values". That count is
        a restatement of `LossConfig.loss_type`'s Literal alphabet, whose
        three prose sites each use a DIFFERENT surface form (slash-
        separated, "or"-joined, line-wrapped) and are therefore tier (ii)
        — not extracted here. This consistency pin catches the drift the
        extraction cannot: the alphabet growing while the prose still
        says five.
        """
        from ml_models.models_format_sandbox import LossConfig

        alphabet = typing.get_args(LossConfig.model_fields["loss_type"].annotation)
        assert len(alphabet) == 5, (
            f"loss_type alphabet is now {alphabet!r}; proposing_stage.md still "
            'says "accepts five values" at the built-in-loss section, and the '
            "three alphabet prose sites are tier-(ii) literals routed to step 03"
        )
        assert "accepts five values" in self.TEMPLATE.read_text(encoding="utf-8")


class TestStandaloneCliDisposition:
    """PR 01a §3.1 — the CLI must still reach a COMPLETE commit prompt.

    Before the extraction an absent contract was harmless (the prompt was
    a zero-placeholder constant). After it, the render is fail-closed, so
    a CLI that omitted the declaration would raise on a documented
    architectural surface (`docs/architecture.md` "Has CLI interface").
    This is the reachability evidence for the frozen disposition: the
    production entry point is exercised, not a helper standing in for it.
    """

    def _run_main_capturing_input(self, tmp_path, monkeypatch):
        import argparse
        import importlib

        mod = importlib.import_module("nodes.ml_model_proposal_agent.ml_model_proposal_agent")

        # The CLI derives its input path from --workspace/--run_name
        # (there is no --interpretation flag); mirror that exactly.
        (tmp_path / "interpretation_cli_probe.json").write_text(
            json.dumps({"model_types": ["punet"], "total_experiments": 1}),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            mod.argparse.ArgumentParser,
            "parse_args",
            lambda self: argparse.Namespace(
                workspace=str(tmp_path),
                run_name="cli_probe",
                provider="openai",
                model_id="gpt-5.5",
            ),
        )

        captured: dict[str, object] = {}

        class _CapturingAgent:
            def __init__(self, *a, **kw):
                pass

            def run(self, agent_input):
                captured["input"] = agent_input
                raise SystemExit(0)  # stop before any LLM call

        monkeypatch.setattr(mod, "MLModelProposalAgent", _CapturingAgent)
        with pytest.raises(SystemExit):
            mod.main()
        return captured["input"]

    def test_cli_supplies_a_contract_that_renders(self, tmp_path, monkeypatch):
        """The exact defect this catches: extraction silently breaking the
        standalone CLI, which no script or test invokes and which would
        therefore fail only in an operator's hands."""
        agent_input = self._run_main_capturing_input(tmp_path, monkeypatch)

        rendered = _render_commit_system_prompt(agent_input.forward_contract)
        assert re.findall(r"\{[A-Z][A-Z_]*\}", rendered) == []
        assert "[B, T] int64" in rendered

    def test_cli_contract_comes_from_the_canonical_loader(self, tmp_path, monkeypatch):
        """§3.1 forbids inventing a second config path: the CLI's contract
        must be byte-equal to what `load_task_config()` yields."""
        from workflows.task_config import load_task_config

        agent_input = self._run_main_capturing_input(tmp_path, monkeypatch)
        assert agent_input.forward_contract == ForwardContract(
            **load_task_config()["forward_contract"]
        )
