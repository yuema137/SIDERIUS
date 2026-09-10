"""PR 01b / commit S1-C2 — fixture 13.4-A, rung FX-1: the description axis.

Design: `pr_01b_task_description_join.md` §4.2; parent §9.1 (the fixture),
§9.4 (the rung), §9.5 (the residue whitelist).

S1-C proved the JOIN renders a supplied description. Byte-equality on
ONE profile cannot distinguish a live input from a constant. This rung
varies EXACTLY ONE axis — `task_description` — while holding one synthetic
ForwardContract fixed, and asserts that the only thing which moves is the
description-derived block.

The unique failure class, the one no golden can catch: a channel that
does not actually VARY. Every golden pins a single profile per process,
so a renderer that memoised, cached at import, or read a module-level
constant would leave all six green while silently serving the first
description it ever saw. Two profiles in one process is the only way to
see that.

Residue scoping is deliberate and load-bearing (parent §9.5). Absence
assertions are made against the description-derived block only.
"""

from __future__ import annotations

import pytest

from agent.schemas.task_config import ForwardContract
from tests.unit.agent.ml_model_proposal_agent.test_step01b_task_description_join import (
    LABEL,
    STAGES,
    TASK_DESCRIPTION,
    capture_stage_systems,
)

#: Tokens that may appear only because the first description is being
#: rendered. They are asserted absent from the
#: description-derived block, never from the whole prompt.
PRIMARY_DESCRIPTION_TOKENS = ("sensor frame", "multichannel context")
ALTERNATIVE_DESCRIPTION = "Estimate soil moisture from a compact spectral measurement."

#: Contract-derived tokens: they arrive from the ForwardContract, which
#: this rung holds FIXED, so they must survive the description swap
#: untouched. Rendered only by the proposing stage (invariant F10 keeps
#: the contract out of stages 1-2).
CONTRACT_DERIVED_TOKENS = ("[B, F] float32", "[B, 1] float32")


def synthetic_forward_contract() -> ForwardContract:
    """Return the contract held identical across both description variants."""
    return ForwardContract(
        input_shape="[B, F] float32",
        input_description="a compact feature vector",
        output_shape="[B, 1] float32",
        output_description="one continuous estimate",
        num_classes=0,
        task_type="regression",
    )


def task_background_block(system_prompt: str) -> str:
    """Return the description-DERIVED block, and nothing else.

    S1-C places the block between the stage persona and the ``## Your
    task`` heading, so the slice is deterministic. If this ever fails to
    locate the block, S1-C chose an unstable placement and THAT is the
    defect — do not loosen the residue assertion to compensate
    (design §4.2 failure cases).
    """
    assert LABEL in system_prompt, "task-background block not found — S1-C placement is unstable"
    after_label = system_prompt.split(LABEL, 1)[1]
    assert "## Your task" in after_label, (
        "task-background block has no terminating heading — S1-C placement is unstable"
    )
    return after_label.split("## Your task", 1)[0]


def capture_both_variants(tmp_path, monkeypatch, *, mode: str) -> tuple[dict, dict]:
    """Render the SAME fixture twice, varying ONLY the description.

    Both runs happen in ONE process, which is what makes a non-varying
    channel visible.
    """
    contract = synthetic_forward_contract()
    primary = capture_stage_systems(
        tmp_path / "primary",
        monkeypatch,
        mode=mode,
        task_description=TASK_DESCRIPTION,
        forward_contract=contract,
    )
    alt = capture_stage_systems(
        tmp_path / "alt",
        monkeypatch,
        mode=mode,
        task_description=ALTERNATIVE_DESCRIPTION,
        forward_contract=contract,
    )
    return primary, alt


@pytest.mark.parametrize("mode", ["explore", "exploit"])
class TestFixture134ADescriptionAxis:
    def test_alternative_description_reaches_every_stage(self, tmp_path, monkeypatch, mode):
        """The declared description flows — and DISPLACES the previous
        one. The `not in` half is what fails when the channel is a
        constant or a cache rather than a live read."""
        primary, alt = capture_both_variants(tmp_path, monkeypatch, mode=mode)
        for stage in STAGES:
            block = task_background_block(alt[stage])
            assert ALTERNATIVE_DESCRIPTION in block, (
                f"stage {stage!r} ({mode}): alternative description absent"
            )
            assert TASK_DESCRIPTION not in alt[stage], (
                f"stage {stage!r} ({mode}): the primary description is still present under "
                f"the alternative profile — the channel is not reading its input"
            )
            # Sanity that the comparison is not vacuous.
            assert TASK_DESCRIPTION in task_background_block(primary[stage])

    def test_no_primary_residue_inside_the_description_derived_block(
        self, tmp_path, monkeypatch, mode
    ):
        """Only the description-derived block must be free of the first task."""
        _tidmad, alt = capture_both_variants(tmp_path, monkeypatch, mode=mode)
        for stage in STAGES:
            block = task_background_block(alt[stage])
            for token in PRIMARY_DESCRIPTION_TOKENS:
                assert token not in block, (
                    f"stage {stage!r} ({mode}): {token!r} survives inside the "
                    f"description-derived block under the alternative profile — "
                    f"a hardcoded task literal is shadowing the declaration"
                )

    def test_only_the_description_block_moves(self, tmp_path, monkeypatch, mode):
        """Axis isolation, in its strongest form: delete the
        description-derived block from both renders and the remainders
        must be byte-identical. This subsumes 'contract-derived tokens
        are byte-identical' and additionally catches a description
        leaking into any OTHER part of the prompt."""
        primary, alt = capture_both_variants(tmp_path, monkeypatch, mode=mode)
        for stage in STAGES:
            without_primary = primary[stage].replace(task_background_block(primary[stage]), "", 1)
            without_alt = alt[stage].replace(task_background_block(alt[stage]), "", 1)
            assert without_primary == without_alt, (
                f"stage {stage!r} ({mode}): swapping ONLY the task description changed "
                f"something outside the description-derived block"
            )

    def test_contract_derived_tokens_are_unmoved_by_the_swap(self, tmp_path, monkeypatch, mode):
        """Positive half: the fixed synthetic contract really is rendered,
        identically, under both descriptions. Without this the isolation
        assertion above could pass by rendering no contract at all.

        Scoped to the proposing stage because invariant F10 keeps the
        forward contract OUT of the comparison and causal stages.
        """
        primary, alt = capture_both_variants(tmp_path, monkeypatch, mode=mode)
        for token in CONTRACT_DERIVED_TOKENS:
            assert token in primary["proposing"], f"{token!r} missing from the primary variant"
            assert token in alt["proposing"], (
                f"{token!r} missing from the alternative-description variant — the "
                f"contract channel moved when only the description was varied"
            )


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
