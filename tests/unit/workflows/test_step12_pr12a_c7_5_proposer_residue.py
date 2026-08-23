"""Step 12 / PR-12a — C7-5: the Pr2/Pr3 residues C7-3 did not reach.

Design: ``pr_12a_composed_path_closure.md`` §8.9 (the frozen D-12a-5
classification) and §8.17 (F-12a-C9-1, how the gap was found).

The defect only this module catches
-----------------------------------
C7-3 tokenized the proposer's role line, its evidence-reading region and its
output-contract guidance, and proved the relocation byte-exact. It never
enumerated ``PROPOSAL_COMMIT_PROMPT``, so eight sites survived across two
constants — and a composed DAVIS run was still told that ``"regressor"`` emits
"the denoised waveform directly", that its input is "per-timestep ADC class
indices", that "256 denoising bins per time step is contract-fixed", and to
rank files by an ``Impact_Score`` column its evidence does not contain.

Nothing existing caught it. The banned-token census listed the surfaces it
knew about; the goldens pinned TIDMAD's own render, where every literal is
correct; and Step 01a's tests actively pinned the literals as *deliberately
retained*, because at that time no authority declared them. A census is only
as strong as the surfaces it enumerates.

So this module asserts the property on the RENDER of a real non-TIDMAD
composition, not on the template — the level at which "which surfaces did you
remember to list" stops being the question.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks
from agent.schemas.proposal import ProposalInput, ProposalTaskBlocks
from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
from agent.schemas.task_config import ForwardContract
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    PROPOSAL_COMMIT_PROMPT,
    PROPOSAL_REASONING_PROMPT,
    _build_reasoning_system_prompt,
    _render_commit_system_prompt,
    render_class_axis_note,
    render_classifier_output_shape,
    render_input_semantics,
    render_per_file_strategy_directions,
    render_regressor_output_form,
)
from workflows.task_composition import compose_run_task_bindings
from workflows.task_config import load_task_config

REPO_ROOT = Path(__file__).resolve().parents[3]
DAVIS = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "davis"

#: TIDMAD's SCIENCE, not merely its name. Any of these in a video task's prompt
#: arrived from somewhere other than that task's declaration.
BANNED = (
    "denois",
    "waveform",
    "squid",
    "dark matter",
    "256 amplitude",
    "amplitude bin",
    "adc class",
    "impact_score",
    "linear_weight",
)


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    registry, providers = dict(_REGISTRY), dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _davis_contract() -> ForwardContract:
    raw = yaml.safe_load((DAVIS / "task_config.yaml").read_text(encoding="utf-8"))
    return ForwardContract(**raw["forward_contract"])


def _tidmad_contract() -> ForwardContract:
    return ForwardContract(**load_task_config()["forward_contract"])


def _reasoning(blocks: Any, contract: ForwardContract) -> str:
    return _build_reasoning_system_prompt(
        ProposalInput(
            task_description="fixture",
            forward_contract=contract,
            proposal_blocks=blocks,
            interpretation_evidence=ProposerInterpretationEvidence(),
        )
    )


def _hits(text: str) -> list[str]:
    lowered = text.lower()
    return [token for token in BANNED if token in lowered]


class TestTheComposedSurfaceIsClean:
    """The property G-12a-1 probes with a real model, asserted deterministically
    first so the Gate spends its calls on model BEHAVIOUR rather than on bytes.
    """

    @pytest.mark.parametrize("declared", [True, False])
    def test_a_composed_video_task_is_told_no_tidmad_science(self, declared):
        blocks = (
            ProposalTaskBlocks(
                architect_role="video future-frame prediction",
                continuous_output_meaning="the next frames of the clip",
            )
            if declared
            else None
        )
        contract = _davis_contract()
        commit = _render_commit_system_prompt(contract, blocks)
        reasoning = _reasoning(blocks, contract)

        assert _hits(commit) == [], f"commit prompt: {_hits(commit)}"
        assert _hits(reasoning) == [], f"reasoning prompt: {_hits(reasoning)}"

    def test_the_declared_shapes_are_the_TASKS_shapes(self):
        commit = _render_commit_system_prompt(_davis_contract(), None)
        assert "[B, 3, 4, H, W]" in commit
        assert "[B, 256, T]" not in commit


class TestTheRenderersDeriveRatherThanRestate:
    """§8.9 Pr2 requires REPLACEMENT from a task-owned authority, never an
    invented framework phrase. Each renderer is checked at its own boundary,
    because a whole-prompt assertion cannot tell "derived" from "absent"."""

    def test_the_classifier_shape_comes_from_the_declaration(self):
        assert render_classifier_output_shape(_tidmad_contract()) == "[B, 256, T]"

    def test_a_contractless_task_keeps_the_pre_step03_behaviour(self):
        """A task declaring no ``model_io`` is a supported shape (Step 04a
        §15.1 row 1), and it must still render its own declared shape rather
        than raising or borrowing one."""
        bare = ForwardContract(
            input_shape="[B, S] float32",
            input_description="d",
            output_shape="[B, S, 7] float32",
            output_description="d",
        )
        assert render_classifier_output_shape(bare) == "[B, S, 7]"

    @pytest.mark.parametrize("with_dtype", [True, False])
    def test_an_undeclared_continuous_form_is_the_SHAPE_not_a_noun(self, with_dtype):
        rendered = render_regressor_output_form(_davis_contract(), None, with_dtype=with_dtype)
        assert "[B, 3, 4, H, W]" in rendered
        assert "waveform" not in rendered
        assert "(" not in rendered

    def test_a_declared_continuous_form_carries_the_TASKS_noun(self):
        blocks = ProposalTaskBlocks(continuous_output_meaning="the next frames of the clip")
        with_dtype = render_regressor_output_form(_davis_contract(), blocks, with_dtype=True)
        assert with_dtype.endswith("(the next frames of the clip)")

    def test_undeclared_input_semantics_render_nothing(self):
        assert render_input_semantics(None) == ""
        assert render_input_semantics(ProposalTaskBlocks()) == ""

    def test_an_undeclared_class_axis_note_is_GENERIC_not_invented(self):
        """The one place a framework sentence stands in for an absent
        declaration, and it is deliberate: that the DECLARED output dimension
        is contract-fixed is true of every task, so it is structure rather
        than science. It must name no count."""
        note = render_class_axis_note(_davis_contract(), None)
        assert note == "the declared output dimension is contract-fixed, not a hyperparameter"
        assert "256" not in note

    def test_the_task_writes_prose_and_the_framework_writes_JSON(self):
        """Pr3's list items. The task declares one sentence per line and never
        sees a comma or a quote — otherwise the declaration would have to know
        it is being spliced into a JSON example."""
        blocks = ProposalTaskBlocks(per_file_strategy_guidance="first line\nsecond line")
        rendered = render_per_file_strategy_directions(blocks)
        assert rendered == ',\n      "first line",\n      "second line"'

    def test_absent_pr3_guidance_renders_NOTHING(self):
        assert render_per_file_strategy_directions(None) == ""
        assert render_per_file_strategy_directions(ProposalTaskBlocks()) == ""


class TestLegacyIsByteIdentical:
    """The C7 acceptance criterion, proved against the recorded past.

    Two different strongest-available proofs, because the two constants are in
    different states: the reasoning prompt has a pre-C7 CONSTANT digest, while
    the commit prompt was already tokenized by Step 01a and therefore has a
    committed golden of its RENDER — which is what the model actually reads.
    """

    #: The C0 baseline, recorded at `eeb073dc` before any block moved.
    PRE_C7_REASONING_SHA = "7c69ce7bae2509b830ad2cdfd8c239390554215e9feed259e83488845f1b9071"

    def test_substituting_tidmads_blocks_reproduces_the_reasoning_bytes(self):
        blocks = load_proposal_task_blocks()
        rendered = _reasoning(blocks, _tidmad_contract())
        # `_build_reasoning_system_prompt` also substitutes {TASK_BACKGROUND},
        # so compare the template-substitution alone against the C0 digest.
        from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
            render_architect_role,
            render_proposal_evidence_reading,
        )

        template_only = (
            PROPOSAL_REASONING_PROMPT.replace("{ARCHITECT_ROLE}", render_architect_role(blocks))
            .replace("{EVIDENCE_READING}", render_proposal_evidence_reading(blocks))
            .replace("{TARGET_SELECTOR_CLAUSE}", blocks.target_strategy_selector_clause or "")
            .replace("{EVIDENCE_CITATION_CLAUSE}", blocks.evidence_citation_clause or "")
        )
        assert (
            hashlib.sha256(template_only.encode("utf-8")).hexdigest() == self.PRE_C7_REASONING_SHA
        )
        assert "Impact_Score" in rendered  # the declared science DID arrive

    def test_the_commit_render_still_matches_its_committed_golden(self):
        golden = (
            REPO_ROOT
            / "tests"
            / "unit"
            / "agent"
            / "ml_model_proposal_agent"
            / "goldens"
            / "pb4_legacy_commit_system.txt"
        ).read_text(encoding="utf-8")
        rendered = _render_commit_system_prompt(_tidmad_contract(), load_proposal_task_blocks())
        assert rendered == golden

    def test_every_new_token_is_actually_substituted(self):
        """Anti-vacuity. A token nobody replaces would ship a literal
        ``{CLASS_AXIS_NOTE}`` to the model, and both proofs above would still
        pass if the golden had been regenerated with it."""
        rendered = _render_commit_system_prompt(_tidmad_contract(), load_proposal_task_blocks())
        for token in (
            "{CLASSIFIER_OUTPUT_SHAPE}",
            "{REGRESSOR_EMITS}",
            "{REGRESSOR_OUTPUT_FORM}",
            "{INPUT_SEMANTICS}",
            "{CLASS_AXIS_NOTE}",
            "{PER_FILE_STRATEGY_DIRECTIONS}",
            "{EVIDENCE_RATIONALE_CLAUSE}",
        ):
            assert token in PROPOSAL_COMMIT_PROMPT, f"{token} vanished from the template"
            assert token not in rendered, f"{token} reached the model unsubstituted"


class TestFingerprintAndFailClosed:
    def test_editing_only_a_new_key_moves_the_composition_fingerprint(self, tmp_path):
        from tests.helpers.composed_manifest import write_complete_manifest

        prints = []
        for i, value in enumerate(("one", "two")):
            declaration = tmp_path / f"blocks_{i}.yaml"
            declaration.write_text(f"class_axis_note: {value}\n", encoding="utf-8")
            manifest = write_complete_manifest(
                tmp_path / f"w{i}", proposal_blocks={"config": str(declaration)}
            )
            prints.append(compose_run_task_bindings(str(manifest)).semantic_fingerprint)
        assert prints[0] != prints[1]

    def test_a_misspelled_new_key_fails_closed(self, tmp_path):
        bad = tmp_path / "typo.yaml"
        bad.write_text("class_axis_notes: oops\n", encoding="utf-8")
        with pytest.raises(ValueError, match="failed the ProposalTaskBlocks contract"):
            load_proposal_task_blocks(str(bad))
