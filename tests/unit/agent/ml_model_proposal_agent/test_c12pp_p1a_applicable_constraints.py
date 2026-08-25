"""C12-P-P / P1-A — the proposer states the rule its VALIDATOR actually enforces.

WHAT P1-A CHANGED
-----------------
``ml_model_proposal_agent._applicable_dataset_constraints`` replaced an
unconditional read of the module-scope ``TIDMAD`` singleton at the
``known_constraints_block`` call site. It mirrors C12-P / B3's applicability
decision in ``ProposalOutput._validate_baseline_segmentation_size``.

WHY THESE FIVE AND NOT FEWER
----------------------------
A1/A2 are the two regimes. A3 pins that applicability is a property of the
DECLARATION, not of what happens to be on disk. A4 is the one nobody writes by
accident and the only one that fails for the naive ``try/except`` shape. A5 is
the coupling itself — the prompt and the validator must agree, because their
disagreement is the "strictly worse than before" state the whole unit exists to
prevent.
"""

from __future__ import annotations

import sys

import pytest

from agent.prompts import _format_known_constraints_block
from agent.schemas.proposal import ExpertAdvice, ProposalOutput
from execute_tools.dataset_config import TIDMAD, DatasetProfile
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _applicable_dataset_constraints,
)

#: The node's private module object. Resolved through the function's own
#: ``__module__`` rather than an import path: the package ``__init__``
#: re-exports the symbol, which makes ``nodes.ml_model_proposal_agent`` resolve
#: to the MODULE in a ``from ... import`` and breaks the dotted form.
proposer_module = sys.modules[_applicable_dataset_constraints.__module__]

#: Hardcoded, never derived from TIDMAD — the marker that must vanish for a
#: task declaring no TIDMAD topology.
_BLOCK_HEADER = "## SYSTEM-ENFORCED DATASET CONSTRAINTS"

_PROPOSAL_BASE = {
    "model_name": "probe_net",
    "model_description": "d",
    "mathematical_definition": "m",
    "motivation": "mo",
    "expert_advice": ExpertAdvice(),
}


def _foreign_profile(*_args) -> DatasetProfile:
    """A profile that declares NO TIDMAD topology — the composed-foreign shape.

    ``topology`` is left unset: that IS the foreign case. Pets and DAVIS
    declare generic identity with no TIDMAD section, which is exactly what
    ``declares_tidmad_topology`` returns False for.
    """
    return DatasetProfile(
        partition_count=8,
        anchor_selection_files=[0],
        health_peek_files=[0],
    )


# ==========================================================================
# A1 — non-membership => the computed block is ABSENT
# ==========================================================================


def test_a1_non_membership_renders_no_constraint_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task declaring no TIDMAD topology gets no dataset-constraint block.

    DEFECT THIS ALONE CATCHES
        The P1-A call site regressing to an unconditional dataset. Nothing else
        asserts the proposer's *resolution* returns ``None`` off the TIDMAD path.

    HOW IT FAILS ON REGRESSION
        ``_applicable_dataset_constraints`` returns a dataset, the rendered
        block becomes non-empty, and the header assertion fires.
    """
    monkeypatch.setattr(proposer_module, "resolve_dataset_profile", _foreign_profile)
    resolved = _applicable_dataset_constraints()
    assert resolved is None
    assert _format_known_constraints_block(resolved) == ""
    assert _BLOCK_HEADER not in _format_known_constraints_block(resolved)


# ==========================================================================
# A2 — Regime A => byte-identical to what the singleton produced
# ==========================================================================


def test_a2_regime_a_block_is_byte_identical_to_the_singleton_rendering() -> None:
    """TIDMAD's block is unchanged, to the byte, by the P1-A migration.

    DEFECT THIS ALONE CATCHES
        A resolution that returns a *different* dataset for TIDMAD — e.g. a
        profile whose psd_segment_length drifted. The operator ruling makes
        Regime-A preservation a hard constraint, and the foreign-side tests
        cannot see a TIDMAD-side change.

    NOTE ON THE ASSERTION SHAPE
        Compared against ``_format_known_constraints_block(TIDMAD)`` — the
        pre-P1-A production expression — not against a captured string. The
        point is that the NEW resolution and the OLD one agree; an equality
        against a literal would not express that.
    """
    resolved = _applicable_dataset_constraints()
    assert resolved is not None
    rendered = _format_known_constraints_block(resolved)
    assert rendered == _format_known_constraints_block(TIDMAD)
    assert _BLOCK_HEADER in rendered
    # Value equivalence, NOT object identity — `tidmad_topology(...).dataset is
    # TIDMAD` is False. Pinned here so the distinction cannot be re-lost.
    assert resolved.psd_segment_length == TIDMAD.psd_segment_length
    assert resolved.valid_segmentation_sizes() == TIDMAD.valid_segmentation_sizes()


# ==========================================================================
# A3 — membership is a DECLARATION property, not artifact presence
# ==========================================================================


def test_a3_applicability_reads_the_declaration_not_the_filesystem(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A declared TIDMAD topology keeps the block with no data on disk.

    DEFECT THIS ALONE CATCHES
        A future "fix" that decides applicability by probing for data files or
        a workspace artifact. That would make prompt content depend on machine
        state, so the same run would render differently on two hosts — and it
        would pass A1 and A2, which say nothing about where the answer came
        from.

    HOW IT FAILS ON REGRESSION
        With CWD pointed at an empty directory the artifact probe finds
        nothing, the block disappears, and the header assertion fires.
    """
    monkeypatch.chdir(tmp_path)  # no data, no workspace, no configs
    resolved = _applicable_dataset_constraints()
    assert resolved is not None, (
        "applicability must follow the DECLARED profile; an empty working "
        "directory must not change which rule the prompt states"
    )
    assert _BLOCK_HEADER in _format_known_constraints_block(resolved)


# ==========================================================================
# A4 — a malformed declaration stays LOUD  (the try/except killer)
# ==========================================================================


def test_a4_malformed_topology_raises_and_is_never_silently_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PRESENT-BUT-MALFORMED TIDMAD topology must raise, not render "".

    DEFECT THIS ALONE CATCHES
        The single most tempting wrong implementation::

            try:
                return tidmad_topology(profile).dataset
            except ValueError:
                return None

        ``tidmad_topology`` raises for ABSENT *and* for MALFORMED sections, so
        that shape silently reclassifies a broken TIDMAD profile as "declares
        none" and ships a TIDMAD run with no constraint block at all — while
        B3's validator still enforces the rule. That is exactly the
        prompt/validator disagreement this unit exists to remove, and it passes
        A1, A2 and A3.

    HOW IT FAILS ON REGRESSION
        Swap the membership test for try/except and this stops raising.
    """
    marker = "malformed topology for the C12-P-P A4 falsifier"

    def _declares_but_malformed(_profile):
        return True

    def _raises(_profile):
        raise ValueError(marker)

    monkeypatch.setattr(proposer_module, "declares_tidmad_topology", _declares_but_malformed)
    monkeypatch.setattr(proposer_module, "tidmad_topology", _raises)

    with pytest.raises(ValueError, match=marker):
        _applicable_dataset_constraints()


# ==========================================================================
# A5 — the prompt and the validator agree  (the coupling invariant)
# ==========================================================================


@pytest.mark.parametrize("seg", [224, 37])
def test_a5_foreign_task_is_neither_told_nor_judged_by_the_tidmad_rule(
    monkeypatch: pytest.MonkeyPatch, seg: int
) -> None:
    """Off the TIDMAD path, the block is absent AND the value is accepted.

    DEFECT THIS ALONE CATCHES
        P1-A landing without B3, or B3 being reverted under it. Either leaves
        the foreign task judged by a rule it was never shown — the "strictly
        worse than before" state (design §4.1). No per-side test sees it: A1
        checks only the prompt, and B3's own tests check only the validator.
        This asserts the PAIR.

    HOW IT FAILS ON REGRESSION
        If the validator regains the TIDMAD rule unconditionally, constructing
        ``ProposalOutput`` raises and the test fails naming the rejected size.
    """
    import agent.schemas.proposal as proposal_schema

    if not hasattr(proposal_schema, "resolve_dataset_profile"):
        raise AssertionError(
            "C12-P / B3 IS NOT PRESENT on this source. P1-A must NOT land alone: "
            "the prompt would omit the TIDMAD rule while the validator still "
            "enforces it on a foreign task -- strictly worse than before the fix "
            "(design 4.1). This RED is the frozen landing-order interlock, and it "
            "clears by itself once core lands B3."
        )

    monkeypatch.setattr(proposer_module, "resolve_dataset_profile", _foreign_profile)
    monkeypatch.setattr(proposal_schema, "resolve_dataset_profile", _foreign_profile)

    assert _format_known_constraints_block(_applicable_dataset_constraints()) == ""

    out = ProposalOutput(
        baseline_config={"model_config": {"segmentation_size": seg}}, **_PROPOSAL_BASE
    )
    assert out.baseline_config["model_config"]["segmentation_size"] == seg
