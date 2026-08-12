"""PR 01a — Stage-B atomic contrast rungs (B-i, B-ii, FX-2, FX-5).

Design: parent §9.2 (rungs B-i/B-ii), §9.4 (rungs FX-2/FX-5) and §9.5
(the residue whitelist). Child: `pr_01a_contract_derived_prompt_
extraction.md` §4.4.

Each rung varies EXACTLY ONE axis. No fixture changes the task
description AND the rank AND the dtype together — that conflation is
what makes a "generic contrast" unfalsifiable.

Scope honesty (parent §6A.2): these prove PROMPT-CONTRACT compatibility
in Step-01-owned contract-derived blocks. They claim nothing about the
rest of SIDERIUS executing such a task, and they deliberately do NOT
assert whole-prompt absence of TIDMAD shape text — parent §9.5
enumerates three legitimate survivors (the shipped description's own
prose, the undeclared two-output-form catalogue, and
`render_forward_contract`'s `per-timestep` descriptor).
"""

from __future__ import annotations

import re

import pytest

from agent.prompt_templates.proposal import load_stage_prompt
from agent.schemas.task_config import ForwardContract
from ml_models.models_format_sandbox import CLASSIFICATION_LOSSES, REGRESSION_LOSSES
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _render_commit_system_prompt,
    _render_loss_legality,
)
from workflows.task_config import (
    get_task_description,
    load_task_config,
    render_forward_contract,
)


def _render_proposing_stage(fc: ForwardContract) -> str:
    """Render the SECOND Step-01 prompt surface under a declaration.

    The proposing stage receives the contract through the pre-existing
    `{forward_contract}` placeholder, fed at
    `ml_model_proposal_agent.py:1709` with
    `render_forward_contract(inp.forward_contract)`, and (since S1-B) its
    loss-legality cells through `{CLASSIFIER_LOSS_LIST}` /
    `{REGRESSOR_LOSS_LIST}`. Those three vars are what PR 01a owns here;
    the rest are held at fixture constants so the rung stays single-axis.
    """
    return load_stage_prompt(
        "proposing_stage",
        exploration_mode="explore",
        template_vars={
            "minimum_boldness": "0.05",
            "n_agent_proposed": "3",
            "n_confirmed_links": "0",
            "existing_model_types": "punet, wavenet",
            "known_constraints_block": "",
            "recent_gate_exhaustions_block": "",
            "recent_trial_validity_block": "",
            "healthgate_evidence_block": "",
            "available_losses_block": "",
            "available_models_block": "",
            "CLASSIFIER_LOSS_LIST": _render_loss_legality(CLASSIFICATION_LOSSES),
            "REGRESSOR_LOSS_LIST": _render_loss_legality(REGRESSION_LOSSES),
            "forward_contract": render_forward_contract(fc),
        },
    )


#: Tokens that can ONLY arrive by substitution of the TIDMAD declaration.
#: Excludes every parent-§9.5 whitelisted survivor: the dtype-dropped
#: `[B, 256, T]` (tier ii), `[B, T] float32 (the denoised waveform
#: directly)` (tier iii) and the "256 denoising bins" noun.
_TIDMAD_DERIVED_ONLY_TOKENS = ("[B, T] int64", "[B, 256, T] float32")


def _assert_no_tidmad_derived_residue(rendered: str) -> None:
    for token in _TIDMAD_DERIVED_ONLY_TOKENS:
        assert token not in rendered, (
            f"{token!r} survived under a non-TIDMAD declaration — a shadow "
            "literal is masking the declared contract. (Whitelisted "
            "survivors per design §9.5 are deliberately not checked here.)"
        )


def _assert_whitelisted_survivors_present(rendered: str) -> None:
    """The three survivors MUST still be there.

    Asserting their presence is as important as asserting the residue's
    absence: it stops a later contributor from "cleaning up" text that
    another step owns, and it keeps this rung honest about its scope.
    """
    assert "[B, 256, T] per-timestep class logits" in rendered  # tier (ii)
    assert "[B, T] float32 (the denoised waveform directly)" in rendered  # tier (iii)
    assert "256 denoising bins per time step is contract-fixed" in rendered  # tier (iii)


class TestRungBi:
    """B-i — regressor contract prose (the roadmap's named 13.4-B).

    Mirrors the in-tree precedent
    `tests/unit/workflows/test_task_config.py::
    test_custom_non_squid_shapes_replace_defaults` (regressor shapes,
    `num_classes=0`, `task_type="regression"`). ONE axis: the declared
    contract. The task description is NOT varied here.
    """

    CONTRACT = ForwardContract(
        input_shape="[B, T] float32",
        input_description="raw continuous samples",
        output_shape="[B, T] float32",
        output_description="the denoised continuous signal",
        num_classes=0,
        task_type="regression",
    )

    def test_declared_regressor_prose_reaches_the_prompt(self):
        rendered = _render_commit_system_prompt(self.CONTRACT)
        assert "[B, T] float32" in rendered
        assert "the denoised continuous signal" in rendered

    def test_no_classifier_derived_residue(self):
        rendered = _render_commit_system_prompt(self.CONTRACT)
        assert "[B, 256, T] float32" not in rendered
        assert "per-timestep logits over 256 denoising classes" not in rendered

    def test_whitelisted_survivors_remain(self):
        _assert_whitelisted_survivors_present(_render_commit_system_prompt(self.CONTRACT))

    def test_loss_legality_is_not_the_varied_axis(self):
        """The frozensets are production authorities, not per-task
        profile content (design §9.3), so legality prose must be
        IDENTICAL across every rung in this file."""
        rendered = _render_commit_system_prompt(self.CONTRACT)
        assert "`ce`, `focal`, `focal_cw`" in rendered
        assert "`smooth_l1`" in rendered


class TestRungBii:
    """B-ii — a 16-class classifier; ONE axis (the class count)."""

    CONTRACT = ForwardContract(
        input_shape="[B, T] int64",
        input_description="per-timestep ADC class indices",
        output_shape="[B, 16, T] float32",
        output_description="per-timestep logits over 16 quantisation bins",
        num_classes=16,
        task_type="classification",
    )

    def test_declared_class_count_tracks_the_declaration(self):
        rendered = _render_commit_system_prompt(self.CONTRACT)
        assert "[B, 16, T] float32" in rendered
        assert "per-timestep logits over 16 quantisation bins" in rendered

    def test_no_256_class_derived_residue(self):
        """`256` must be absent from every contract-DERIVED token — the
        pin that would catch a re-inlined class count."""
        rendered = _render_commit_system_prompt(self.CONTRACT)
        assert "[B, 256, T] float32" not in rendered
        assert "per-timestep logits over 256 denoising classes" not in rendered

    def test_whitelisted_survivors_remain(self):
        _assert_whitelisted_survivors_present(_render_commit_system_prompt(self.CONTRACT))


class TestRungFX2:
    """FX-2 — arbitrary rank with NEUTRAL axis names; ONE axis.

    Neutral names on purpose (parent §9.4): a fixture that swapped
    time-series wording for image wording would only prove the prompt
    can carry a *different domain's* assumptions, not that it carries
    no rank assumption. The declaration also uses an unfamiliar
    `task_type`, which must render verbatim (parent §6A.4: nothing may
    branch on its meaning).
    """

    CONTRACT = ForwardContract(
        input_shape="[B, S, F1, F2] float32",
        input_description="per-sample feature grid",
        output_shape="[B, S, F3] float32",
        output_description="per-sample target features",
        num_classes=0,
        task_type="operator_defined_xyz",
    )

    def test_rank4_declaration_renders_verbatim(self):
        rendered = _render_commit_system_prompt(self.CONTRACT)
        assert "[B, S, F1, F2] float32" in rendered
        assert "[B, S, F3] float32" in rendered
        assert "per-sample target features" in rendered

    def test_no_tidmad_derived_residue_in_derived_blocks(self):
        _assert_no_tidmad_derived_residue(_render_commit_system_prompt(self.CONTRACT))

    def test_whitelisted_survivors_remain(self):
        _assert_whitelisted_survivors_present(_render_commit_system_prompt(self.CONTRACT))

    def test_render_does_not_branch_on_rank_or_task_type(self):
        """A renderer that special-cased rank or `task_type` would have to
        emit something other than the declaration for an unfamiliar one.
        Equal-shaped declarations differing ONLY in rank must produce
        renders differing ONLY in those tokens."""
        rank2 = self.CONTRACT.model_copy(
            update={"input_shape": "[B, S] float32", "output_shape": "[B, S] float32"}
        )
        a = _render_commit_system_prompt(self.CONTRACT)
        b = _render_commit_system_prompt(rank2)
        assert a != b
        assert (
            a.replace("[B, S, F1, F2] float32", "[B, S] float32").replace(
                "[B, S, F3] float32", "[B, S] float32"
            )
            == b
        )


class TestRungFX5:
    """FX-5 — multi-channel time series; ONE axis.

    Proves "time series" is not assumed to mean a scalar `[B, T]`
    stream: a channel axis in the declaration must survive to the
    prompt intact.
    """

    CONTRACT = ForwardContract(
        input_shape="[B, C, T] float32",
        input_description="multi-channel sensor stream",
        output_shape="[B, C, T] float32",
        output_description="per-channel denoised stream",
        num_classes=0,
        task_type="regression",
    )

    def test_channel_axis_survives_to_the_prompt(self):
        rendered = _render_commit_system_prompt(self.CONTRACT)
        assert "[B, C, T] float32" in rendered
        assert "per-channel denoised stream" in rendered
        # NOTE (source finding, S1-A): `input_description` is NOT a
        # tier-(i) token for this surface — the prompt's input
        # parenthetical is the literal "(per-timestep ADC class
        # indices)", which differs from the shipped
        # input_description ("raw signal, integer class indices
        # 0-255"). It therefore stays literal and is routed with the
        # tier-(iii) set; asserting it here would pin a fact the
        # commit surface does not derive.
        assert "multi-channel sensor stream" not in rendered

    def test_no_scalar_tidmad_input_residue(self):
        rendered = _render_commit_system_prompt(self.CONTRACT)
        assert "[B, T] int64" not in rendered

    def test_whitelisted_survivors_remain(self):
        _assert_whitelisted_survivors_present(_render_commit_system_prompt(self.CONTRACT))


class TestSecondStepOneSurface:
    """§4.4 requires the rungs to hold on ALL Step-01 surfaces.

    The commit prompt above is one; the production proposing stage is
    the other. It carries the declaration through the pre-existing
    `render_forward_contract` block, so the rank-agnosticism claim has to
    be demonstrated there too — a rung that only ever exercised the
    legacy surface would leave the surface the PIPELINE actually uses
    unproven.
    """

    def test_fx2_rank4_and_opaque_task_type_render_on_the_proposing_stage(self):
        rendered = _render_proposing_stage(TestRungFX2.CONTRACT)
        assert "[B, S, F1, F2] float32" in rendered
        assert "[B, S, F3] float32" in rendered
        assert "per-sample feature grid" in rendered
        # The unfamiliar task_type renders as an OPAQUE label (§6A.4).
        # `num_classes=0` means the grandfathered per-timestep branch at
        # workflows/task_config.py:209 stays silent — pinned so a later
        # change that fires it for a non-classification task is caught.
        assert "Task type: operator_defined_xyz." in rendered
        assert "per-timestep 0-class" not in rendered

    def test_fx5_channel_axis_renders_on_the_proposing_stage(self):
        rendered = _render_proposing_stage(TestRungFX5.CONTRACT)
        assert "[B, C, T] float32" in rendered
        assert "multi-channel sensor stream" in rendered
        assert "per-channel denoised stream" in rendered

    def test_bii_class_count_tracks_the_declaration_on_this_surface(self):
        """The grandfathered `num_classes` branch must follow the
        declaration, not a frozen 256."""
        rendered = _render_proposing_stage(TestRungBii.CONTRACT)
        assert "Task type: classification (per-timestep 16-class)." in rendered
        assert "per-timestep 256-class" not in rendered

    @pytest.mark.parametrize(
        "rung",
        [TestRungBi.CONTRACT, TestRungBii.CONTRACT, TestRungFX2.CONTRACT, TestRungFX5.CONTRACT],
    )
    def test_derived_block_states_this_rung_and_nothing_else(self, rung):
        """Residue is judged RELATIVE TO EACH RUNG'S OWN DECLARATION.

        A blanket "no `[B, T] int64` anywhere" check is wrong here: B-ii
        is the class-count rung and legitimately DECLARES the TIDMAD
        input shape — that token is its declaration, not residue. So the
        pin is: the derived block states exactly what this rung declares,
        and any TIDMAD shape this rung does NOT declare is absent from
        it. Scoped to the derived block only (§9.5) — the surrounding
        stage keeps its tier-(ii) `[B, 256, T]` table cell and "256
        amplitude bins" prose, routed to step 03 by OD-S1-7.
        """
        derived_block = render_forward_contract(rung)
        assert rung.input_shape in derived_block
        assert rung.output_shape in derived_block
        for undeclared in {"[B, T] int64", "[B, 256, T] float32"} - {
            rung.input_shape,
            rung.output_shape,
        }:
            assert undeclared not in derived_block, (
                f"{undeclared!r} appears in the derived block of a rung that "
                "does not declare it — a shadow literal is masking the "
                "declaration on the proposing-stage surface"
            )
        assert derived_block in _render_proposing_stage(rung)

    def test_tier_ii_table_literals_deliberately_survive_the_contrast(self):
        """Scope honesty: PR 01a does NOT make this surface fully
        task-agnostic. The literal shape column and the "256 amplitude
        bins" sentence remain under every rung, and that is the frozen
        disposition — not an oversight to be cleaned up here.
        """
        rendered = _render_proposing_stage(TestRungFX2.CONTRACT)
        assert "`[B, 256, T]` float" in rendered
        assert "256 amplitude bins" in rendered

    def test_loss_legality_cells_derive_on_this_surface_too(self):
        rendered = _render_proposing_stage(TestRungFX2.CONTRACT)
        assert "{CLASSIFIER_LOSS_LIST}" not in rendered
        assert "| `ce`, `focal`, `focal_cw` |" in rendered
        assert "`smooth_l1`" in rendered


class TestContractReassertionContrast:
    """The S1-D half of the re-targeted contract-reassertion pins
    (child §11.1 row 1; `test_contract_reassertion.py:41-42`).

    That module pins the Golden-Paragraph markers under the SHIPPED
    profile. Byte-equality there cannot distinguish "the citation is
    derived from the declaration" from "the citation happens to be the
    frozen TIDMAD literal". This contrast supplies the missing half:
    under B-ii the forward-contract citation must MOVE with the
    declaration while the structural markers stay.
    """

    def _spec(self, fc: ForwardContract) -> str:
        m = re.search(
            r'"mathematical_definition":\s*"(.+?)"\s*,\s*\n',
            _render_commit_system_prompt(fc),
            re.DOTALL,
        )
        assert m is not None, "commit prompt lost its mathematical_definition field"
        return m.group(1)

    def test_golden_paragraph_citation_tracks_a_non_tidmad_declaration(self):
        spec = self._spec(TestRungBii.CONTRACT)
        assert "[B, 16, T] float32" in spec
        assert "[B, 256, T] float32" not in spec

    def test_structural_markers_survive_the_contrast(self):
        """The guard must still be a guard off-TIDMAD: the citation
        structure is contract-independent, so every marker that is not a
        contract token stays."""
        spec = self._spec(TestRungBii.CONTRACT)
        for marker in (
            "Golden Paragraph",
            "segment-local",
            "segment-cross",
            "causal masking",
            "Do NOT include concrete layer dimensions",
        ):
            assert marker in spec

    def test_tier_iii_bins_clause_is_whitelisted_not_derived(self):
        """§9.5: the "256 denoising bins ... contract-fixed" clause has no
        authority behind it and stays literal under every profile. Pinned
        so its survival is a recorded decision rather than a silent
        inconsistency someone later "fixes" inside this PR."""
        spec = self._spec(TestRungBii.CONTRACT)
        assert re.search(r"256 denoising bins[^\"]{0,60}contract-fixed", spec, re.DOTALL)


class TestRungAtomicity:
    """Every rung varies exactly one axis (parent §9/§9.4 atomicity)."""

    @pytest.mark.parametrize(
        "rung",
        [TestRungBi.CONTRACT, TestRungBii.CONTRACT, TestRungFX2.CONTRACT, TestRungFX5.CONTRACT],
    )
    def test_loss_legality_identical_across_every_rung(self, rung):
        rendered = _render_commit_system_prompt(rung)
        assert "`ce`, `focal`, `focal_cw`" in rendered
        assert "`smooth_l1`" in rendered

    def test_commit_surface_carries_no_task_description_prose(self):
        """The description axis belongs to PR 01b (rung FX-1).

        Pinned by CONTENT, from source: the legacy commit surface states
        the I/O contract but never the task narrative — it contains no
        sentence of the shipped `task_description`, and none of its
        domain nouns. That is exactly why a PR-01a rung can vary the
        contract while holding the description fixed and still be
        single-axis: on this surface the description is not an axis at
        all. Should the JOIN later route description prose here, this
        fires and the rungs must be re-derived before they can still be
        called atomic.
        """
        rendered = _render_commit_system_prompt(TestRungFX2.CONTRACT)
        shipped_description = get_task_description(load_task_config())
        assert shipped_description not in rendered
        for domain_noun in ("SQUID", "TIDMAD", "dark-matter"):
            assert domain_noun not in rendered
