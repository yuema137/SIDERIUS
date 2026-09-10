"""Generic proposer rendering derives task semantics from typed declarations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks
from agent.schemas.proposal import ProposalInput, ProposalTaskBlocks
from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    PROPOSAL_COMMIT_PROMPT,
    _build_reasoning_system_prompt,
    _render_commit_system_prompt,
    render_class_axis_note,
    render_classifier_output_shape,
    render_input_semantics,
    render_per_file_strategy_directions,
    render_regressor_output_form,
)
from tests.helpers.composed_manifest import write_complete_manifest
from workflows.task_composition import compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]


def _classification_contract() -> ForwardContract:
    return ForwardContract(
        input_shape="[B, S] float32",
        input_description="tabular features",
        output_shape="[B, S, 7] float32",
        output_description="seven class logits per row",
    )


def _regression_contract() -> ForwardContract:
    return ForwardContract(
        input_shape="[B, 3, 8, H, W] float32",
        input_description="an input frame stack",
        output_shape="[B, 3, 4, H, W] float32",
        output_description="a predicted frame stack",
    )


def _reasoning(blocks: Any, contract: ForwardContract) -> str:
    return _build_reasoning_system_prompt(
        ProposalInput(
            task_description="synthetic fixture",
            forward_contract=contract,
            proposal_blocks=blocks,
            interpretation_evidence=ProposerInterpretationEvidence(),
        )
    )


def test_composed_prompt_uses_declared_shapes_and_optional_prose():
    contract = _regression_contract()
    blocks = ProposalTaskBlocks(
        architect_role="multidimensional regression",
        continuous_output_meaning="the declared prediction tensor",
    )

    commit = _render_commit_system_prompt(contract, blocks)
    reasoning = _reasoning(blocks, contract)

    assert "[B, 3, 4, H, W]" in commit
    assert "the declared prediction tensor" in commit
    assert "multidimensional regression" in reasoning


def test_renderers_derive_shapes_without_inventing_task_nouns():
    classification = _classification_contract()
    regression = _regression_contract()

    assert render_classifier_output_shape(classification) == "[B, S, 7]"
    assert render_regressor_output_form(regression, None, with_dtype=True) == (
        "[B, 3, 4, H, W] float32"
    )
    assert render_class_axis_note(classification, None) == (
        "the declared output dimension is contract-fixed, not a hyperparameter"
    )
    assert render_input_semantics(None) == ""
    assert render_input_semantics(ProposalTaskBlocks()) == ""


def test_declared_task_prose_is_embedded_in_framework_owned_json_punctuation():
    blocks = ProposalTaskBlocks(per_file_strategy_guidance="first line\nsecond line")
    assert render_per_file_strategy_directions(blocks) == (
        ',\n      "first line",\n      "second line"'
    )
    assert render_per_file_strategy_directions(None) == ""


def test_every_declared_template_token_is_substituted():
    rendered = _render_commit_system_prompt(_classification_contract(), ProposalTaskBlocks())
    for token in (
        "{CLASSIFIER_OUTPUT_SHAPE}",
        "{REGRESSOR_EMITS}",
        "{REGRESSOR_OUTPUT_FORM}",
        "{INPUT_SEMANTICS}",
        "{CLASS_AXIS_NOTE}",
        "{PER_FILE_STRATEGY_DIRECTIONS}",
        "{EVIDENCE_RATIONALE_CLAUSE}",
    ):
        assert token in PROPOSAL_COMMIT_PROMPT
        assert token not in rendered


def test_editing_only_a_proposal_block_moves_the_composition_fingerprint(tmp_path):
    fingerprints = []
    for index, value in enumerate(("one", "two")):
        declaration = tmp_path / f"blocks_{index}.yaml"
        declaration.write_text(f"class_axis_note: {value}\n", encoding="utf-8")
        manifest = write_complete_manifest(
            tmp_path / f"workspace_{index}",
            proposal_blocks={"config": str(declaration)},
        )
        fingerprints.append(compose_run_task_bindings(str(manifest)).semantic_fingerprint)

    assert fingerprints[0] != fingerprints[1]


def test_a_misspelled_proposal_block_key_fails_closed(tmp_path):
    declaration = tmp_path / "typo.yaml"
    declaration.write_text("class_axis_notes: invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="failed the ProposalTaskBlocks contract"):
        load_proposal_task_blocks(str(declaration))
