"""PR-02a commit C5 — one legality authority, one file-count authority.

Design:
``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md``
§6.5.

C5 is a refactor with no new capability, so its tests guard exactly two
things a refactor can break: that the de-duplicated sites still reject what
they rejected, with equally diagnostic messages, and that the rendered
prompt bytes did not move.

The parent's §1.3 audit found the legality rule stated in four places, two
of which already read the authority (``agent/prompts.py:746``,
``agent/schemas/proposal.py:1127``). Those are deliberately UNTOUCHED —
this module asserts they stay that way, because "de-duplicate" must not
turn into "rewrite the two sites that were already correct".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from execute_tools.dataset_config import (
    TIDMAD,
    TIDMAD_PROFILE,
    bind_dataset_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _profile_with_psd(psd_len: int):
    return TIDMAD_PROFILE.model_copy(
        update={
            "dataset": TIDMAD_PROFILE.dataset.model_copy(update={"psd_segment_length": psd_len})
        }
    )


# ---------------------------------------------------------------------------
# The rule now has ONE statement
# ---------------------------------------------------------------------------


class TestLegalityRuleIsNotRestated:
    def test_the_authority_and_the_old_inline_derivation_agree(self):
        """The tuner used to re-derive the legal list itself:

            sorted(d for d in range(100, psd + 1) if psd % d == 0 and d <= 100_000)

        Under TIDMAD that is a 10,000,000-iteration loop on the error path,
        and a second place the rule could drift. It now calls
        ``valid_segmentation_sizes()``. This pins that the swap changed no
        VALUE — if the two ever diverged, the tuner's diagnostic would list
        different legal sizes than the proposer and the planner prompt.
        """
        psd = TIDMAD.psd_segment_length
        old_derivation = sorted(d for d in range(100, psd + 1) if psd % d == 0 and d <= 100_000)
        assert TIDMAD.valid_segmentation_sizes() == old_derivation
        assert len(old_derivation) == 36

    def test_the_tuner_no_longer_re_derives_the_divisor_list(self):
        """Anti-regression: re-inlining the enumeration would restore both
        the drift risk and the 10M-iteration loop."""
        source = (
            REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
        ).read_text()
        offenders = [
            line.strip()
            for line in source.splitlines()
            # Comment lines are excluded deliberately: the migration's own
            # explanation quotes the removed expression, and a guard that
            # cannot tell code from prose about code is not a guard.
            if re.search(r"range\(\s*100\s*,\s*psd", line) and not line.lstrip().startswith("#")
        ]
        assert offenders == []

    def test_the_two_already_correct_sites_still_read_the_authority(self):
        """§6.5 scope: ``agent/prompts.py`` and ``agent/schemas/proposal.py``
        were already correct and are explicitly out of C5's diff."""
        for rel in ("agent/prompts.py", "agent/schemas/proposal.py"):
            assert "valid_segmentation_sizes()" in (REPO_ROOT / rel).read_text(), rel


# ---------------------------------------------------------------------------
# The rejection behaviour C5 must not change
# ---------------------------------------------------------------------------


class TestInvalidSegmentationSizeStillRejected:
    """The de-duplication must not weaken the guard or its diagnostic.

    A caller who supplies an illegal size needs to be told the remainder AND
    the legal values; losing either would make the error unactionable.
    """

    def _validate(self, segmentation_size: int):
        from agent.schemas.hyperparam_tuning import TrialConfig
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _validate_data_config,
        )

        return _validate_data_config(
            segmentation_size=segmentation_size,
            trial_config=TrialConfig.model_validate(
                {
                    "is_trial": True,
                    "mode": "trial",
                    "trial_portion": 0.1,
                    "train_sampling_seed": 1,
                    "eval_sampling_seed": 1,
                    "train_base_seed": 1,
                }
            ),
            dataset_config=TIDMAD,
        )

    def test_a_non_divisor_is_rejected_with_a_diagnostic(self):
        with pytest.raises(ValueError) as exc:
            self._validate(30_000)  # 10,000,000 % 30,000 != 0
        message = str(exc.value)
        assert "must be divisible by" in message
        assert "Remainder:" in message
        assert "Valid segmentation_size values:" in message
        # The legal list must actually be IN the message, not just promised.
        assert "10000" in message

    def test_a_divisor_is_accepted(self):
        self._validate(10_000)


# ---------------------------------------------------------------------------
# Prompt bytes — the C5 flip condition
# ---------------------------------------------------------------------------


class TestRenderedProseIsUnchanged:
    def test_the_time_skill_message_is_byte_identical_under_tidmad(self):
        """§6.5's stop condition: if a rendered byte moves, this child takes
        Gate 1. ``f"{10_000_000:,}"`` renders "10,000,000", the exact literal
        it replaced, so it does not.
        """
        from agent.skills.evaluate_time_skill.wrapper import _suggest_lever

        message = _suggest_lever(ms_per_step=10.0, seg_size=100_000, batch_size=8)
        assert message == (
            "Raise segmentation_size to the next valid divisor of 10,000,000 "
            "so fewer steps cover the same data."
        )

    def test_the_time_skill_message_follows_a_contrast_declaration(self):
        """Reachability: byte-identity alone would also hold if the value
        were still hardcoded."""
        from agent.skills.evaluate_time_skill.wrapper import _suggest_lever

        with bind_dataset_profile(_profile_with_psd(2_048_000)):
            message = _suggest_lever(ms_per_step=10.0, seg_size=100_000, batch_size=8)
        assert "2,048,000" in message
        assert "10,000,000" not in message


# ---------------------------------------------------------------------------
# §8 — the generator and its consumer cannot disagree
# ---------------------------------------------------------------------------


class TestReferenceArtifactFileCount:
    """``nodes/scoring_reference.py`` LOADS the per-file artifacts
    ``scripts/compute_raw_baseline.py`` writes. If the node migrated to the
    profile and its generator did not, the two would silently disagree about
    how many files exist — the measured-reachability argument that pulled
    this script into 02a (§8).
    """

    def test_both_derive_the_count_from_the_same_authority(self):
        import nodes.scoring_reference as reference

        for rel in ("scripts/compute_raw_baseline.py", "nodes/scoring_reference.py"):
            source = (REPO_ROOT / rel).read_text()
            assert "resolve_dataset_profile" in source, rel
            # Code lines only — both files' docstrings quote the removed
            # module-level tuple to explain what changed.
            code = [
                line
                for line in source.splitlines()
                if "tuple(range(NUM_FILES))" in line
                and not line.lstrip().startswith("#")
                and "``" not in line
            ]
            assert code == [], f"{rel} still builds the index tuple at import: {code}"

        assert len(reference._fine_indices()) == TIDMAD.num_files
        with bind_dataset_profile(
            TIDMAD_PROFILE.model_copy(
                update={"dataset": TIDMAD_PROFILE.dataset.model_copy(update={"num_files": 5})}
            )
        ):
            assert len(reference._fine_indices()) == 5
