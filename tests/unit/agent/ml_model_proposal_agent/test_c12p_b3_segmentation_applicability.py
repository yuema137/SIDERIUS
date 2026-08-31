"""C12-P / B3 — the proposer's segmentation legality rule is TIDMAD physics.

``ProposalOutput._validate_baseline_segmentation_size`` used to read the
module-scope ``TIDMAD`` singleton and apply ``psd_segment_length % seg == 0``
to EVERY task. This module pins the four rows that separate a correct fix
from the three wrong ones (delete the rule / catch the decoder's exception /
invent a psd), and it pins them through the PRODUCTION entry point —
constructing a real ``ProposalOutput`` — so a fix that only moves a helper
around cannot make them green.

The witness is deliberately **Pets / 144**, not DAVIS / 128.
``10_000_000 == 2**7 * 5**7``, so 128 divides it and DAVIS passed the broken
rule by arithmetic coincidence; a suite built on DAVIS alone stays green
against a completely broken implementation. See
``test_davis_128_is_a_negative_control_not_evidence`` below, which exists to
make that coincidence unmissable to a future reader.
"""

from __future__ import annotations

from contextlib import nullcontext

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.proposal import ProposalOutput
from execute_tools.dataset_config import (
    TIDMAD_PROFILE,
    DatasetProfile,
    bind_dataset_profile,
)

# --- Hardcoded expectations. Never read back from the thing under test. ---

#: TIDMAD's PSD segment length. Stated as a literal on purpose: reading it
#: from ``TIDMAD.psd_segment_length`` would compare the rule to itself.
TIDMAD_PSD = 10_000_000

#: A non-divisor image-task segmentation size. ``10_000_000 % 144 == 64``.
PETS_SEGMENTATION_SIZE = 144

#: A divisor video-task segmentation size. ``10_000_000 % 128 == 0``.
DAVIS_SEGMENTATION_SIZE = 128

#: The value the production runs kept failing on under TIDMAD.
TIDMAD_ILLEGAL_SIZE = 16384


def _contrast_profile() -> DatasetProfile:
    """A task with no physical geometry at all — no PSD segments, no sampling
    frequency, no file-name pattern. The shape Pets and DAVIS declare."""
    return DatasetProfile(
        partition_count=3,
        anchor_selection_files=[0],
        health_peek_files=[1],
    )


def _malformed_tidmad_profile() -> DatasetProfile:
    """TIDMAD's three sections are PRESENT but do not satisfy the typed view.

    Row 2 of the 12bc row-2-vs-row-4 table: divergent, not absent.
    """
    return TIDMAD_PROFILE.model_copy(
        update={"topology": {"dataset": {"bogus": 1}, "channels": {}, "encoding": {}}}
    )


@pytest.fixture
def expert_advice() -> ExpertAdvice:
    return ExpertAdvice(
        focus_areas=["start with depth=2"],
        constraints=["VRAM < 8 GB"],
        known_failures=["large batch_size"],
        suggested_directions=["try focal gamma=2"],
        rationale="x",
    )


def _propose(expert_advice: ExpertAdvice, segmentation_size: object) -> ProposalOutput:
    """Build a minimal valid ``ProposalOutput`` — the production entry point."""
    return ProposalOutput(
        model_name="x",
        model_description="x",
        mathematical_definition="x",
        motivation="x",
        expert_advice=expert_advice,
        baseline_config={
            "model_config": {"segmentation_size": segmentation_size},
            "train_config": {"lr": 1e-4, "epochs": 1},
            "loss_config": {"loss_type": "focal"},
        },
    )


class TestATaskWithoutTidmadGeometrySkipsTheRule:
    def test_pets_own_declared_segmentation_size_is_accepted(self, expert_advice):
        """THE anti-vacuity witness. RED before C12-P / B3.

        Defect caught by this test alone: the divisibility rule is applied to a
        task that declares no PSD segments. Pets' own reference model declares
        ``segmentation_size=144``; ``10_000_000 % 144 == 64``, so before the
        fix the proposer rejected the Pets reference configuration at its own
        output gate and a composed Pets run could not emit a baseline.

        How it fails on regression: ``ProposalOutput`` raises
        ``ValidationError`` naming ``psd_segment_length (10000000)`` and
        ``Remainder: 64`` — for a task that has neither.
        """
        assert TIDMAD_PSD % PETS_SEGMENTATION_SIZE == 64, "witness must stay non-vacuous"
        with bind_dataset_profile(_contrast_profile()):
            out = _propose(expert_advice, PETS_SEGMENTATION_SIZE)
        assert out.baseline_config["model_config"]["segmentation_size"] == 144

    def test_a_tidmad_illegal_size_is_also_accepted_for_such_a_task(self, expert_advice):
        """The skip is total, not a widened divisor list.

        Defect caught: a fix that "generalises" the rule by inventing a psd for
        a geometry-less task, or by relaxing the divisor set, instead of
        skipping a rule that has no meaning there. 16384 is TIDMAD-illegal and
        must be accepted here precisely because the run has no PSD segments.

        How it fails on regression: ``ValidationError`` is raised.
        """
        with bind_dataset_profile(_contrast_profile()):
            out = _propose(expert_advice, TIDMAD_ILLEGAL_SIZE)
        assert out.baseline_config["model_config"]["segmentation_size"] == 16384

    def test_the_generic_positive_int_rule_stays_unguarded(self, expert_advice):
        """The task-neutral half of the validator must NOT move behind the
        applicability gate.

        Defect caught: the whole validator is wrapped in the membership test,
        so a geometry-less task can declare ``segmentation_size=-100`` or
        ``"16000"`` and have it validate. Positive-integer-ness is a property
        of the FIELD, not of TIDMAD's physics.

        How it fails on regression: no ``ValidationError`` is raised.
        """
        for illegal in (-100, 0, "16000"):
            with bind_dataset_profile(_contrast_profile()):
                with pytest.raises(ValidationError, match="must be a positive int"):
                    _propose(expert_advice, illegal)

    def test_davis_128_is_a_negative_control_not_evidence(self, expert_advice):
        """**NOT a witness. Kept so nobody mistakes it for one.**

        DAVIS declares ``segmentation_size=128`` and ``10_000_000 ==
        2**7 * 5**7``, so 128 divides it exactly. DAVIS therefore passed the
        BROKEN rule as well as it passes the fixed one, and a regression suite
        built on DAVIS alone would be green against an implementation that
        applies TIDMAD's physics to every task on earth.

        This test asserts the coincidence itself, so that if someone later
        "simplifies" the suite down to DAVIS the arithmetic reason it proves
        nothing is stated in the file they are reading.
        """
        assert TIDMAD_PSD % DAVIS_SEGMENTATION_SIZE == 0, (
            "128 divides 10^7; this value can never discriminate the defect"
        )
        with bind_dataset_profile(_contrast_profile()):
            out = _propose(expert_advice, DAVIS_SEGMENTATION_SIZE)
        assert out.baseline_config["model_config"]["segmentation_size"] == 128


class TestRegimeAParityIsUnchanged:
    """Nothing bound, or TIDMAD bound: the rule and its diagnostic must not move."""

    @pytest.mark.parametrize("bind_tidmad", [False, True])
    def test_a_tidmad_illegal_size_still_raises_with_the_same_diagnostic(
        self, expert_advice, bind_tidmad
    ):
        """Defect caught: "fixed by deleting the rule".

        A fix that removes the divisibility check outright, or that skips it
        whenever the profile came from the resolution seam rather than the
        module constant, makes every earlier row green while silently letting
        16384 through for TIDMAD — the exact value production kept failing on.

        How it fails on regression: no ``ValidationError``, or one whose text
        has lost the remainder or the actionable divisor list.
        """
        ctx = bind_dataset_profile(TIDMAD_PROFILE) if bind_tidmad else nullcontext()
        with ctx, pytest.raises(ValidationError) as exc:
            _propose(expert_advice, TIDMAD_ILLEGAL_SIZE)
        msg = str(exc.value)

        # Hardcoded, not read back from the validator or from TIDMAD.
        assert "segmentation_size" in msg
        assert "16384" in msg
        assert "10000000" in msg
        assert "Remainder: 5760" in msg
        assert "Valid segmentation_size values" in msg
        assert "16000" in msg

    def test_a_tidmad_legal_size_still_passes(self, expert_advice):
        """Defect caught: an applicability gate that misfires under TIDMAD and
        skips — or refuses — a value that has always been legal.

        How it fails on regression: ``ValidationError``, or the value not
        surviving onto the record.
        """
        with bind_dataset_profile(TIDMAD_PROFILE):
            out = _propose(expert_advice, 16000)
        assert out.baseline_config["model_config"]["segmentation_size"] == 16000


class TestMalformedTidmadTopologyStillRaises:
    def test_present_but_invalid_sections_are_not_treated_as_absent(self, expert_advice):
        """The row-2-vs-row-4 rule, and the reason applicability MUST be a
        membership test rather than ``try: tidmad_topology(...) except``.

        Defect caught by this test alone: implementing applicability as an
        except clause. ``tidmad_topology()`` raises for two different reasons —
        sections ABSENT, and sections PRESENT-BUT-MALFORMED — so catching its
        ``ValueError`` silently reclassifies a corrupt TIDMAD profile as "this
        task simply declares none" and SKIPS a rule that must instead fire.
        Every other test in this module passes under that wrong
        implementation; only this one turns red.

        How it fails on regression: the ``ProposalOutput`` constructs
        successfully instead of raising, i.e. a corrupt TIDMAD run reaches the
        implementor with an unchecked segmentation size.
        """
        with bind_dataset_profile(_malformed_tidmad_profile()):
            with pytest.raises(ValidationError) as exc:
                _propose(expert_advice, TIDMAD_ILLEGAL_SIZE)
        assert "typed view" in str(exc.value)

    def test_it_raises_even_for_a_size_tidmad_would_have_allowed(self, expert_advice):
        """The refusal is about the corrupt DECLARATION, not about the value.

        Defect caught: an implementation that decodes the topology lazily —
        only on the error path — so a malformed profile is silently accepted
        whenever the proposed size happens to be a divisor. That would make the
        corruption's visibility depend on the LLM's choice of hyperparameter.

        How it fails on regression: 16000 is accepted under a corrupt profile.
        """
        with bind_dataset_profile(_malformed_tidmad_profile()):
            with pytest.raises(ValidationError):
                _propose(expert_advice, 16000)
