"""PR-02b B4 — Stage B: a contrast topology travels through selection.

Stage A (B1-B3) proved the explicit hop is live while every TIDMAD identity
stayed byte-identical. That is parity evidence. It is not genericity
evidence: a parameter can be threaded perfectly and still be ignored by a
consumer that assumes 20 files.

This rung asks the one question Stage A cannot: **does the production
selection path actually follow a profile that is not TIDMAD?**

Approved axis (design §6.4) — `num_files` / file index-space ONLY:

    ambient  profile : TIDMAD, num_files = 20
    explicit profile : num_files != 20
    held identical   : segments_per_file, geometry, encoding, channel
                       identity, groups, strategy, seed, portion,
                       metric/model semantics

The single-axis promise is **machine-checked** against the TIDMAD
declaration below, not asserted in prose — a prose promise would not
survive a careless edit to the fixture.

Direction: DOWNWARD (20 -> 7). §6.4 specifies `!= 20`, not `> 20`, and the
downward direction keeps every selected index inside TIDMAD's `[0, 20)`,
so `validate_sample_set`'s still-TIDMAD-bound range check is never
consulted as a limit. See §13.1: choosing the unblocked direction is what
keeps 02b from silently absorbing a boundary-validator migration that has
no source evidence forcing it.

Failure class guarded (design §8): **topology-hardcode survival** — a
consumer still assuming 20 x 200.
"""

from unittest.mock import patch

import pytest

from execute_tools import sample_set_builder
from execute_tools.dataset_config import TIDMAD_PROFILE, DataScope
from execute_tools.sample_set_builder import build_sample_set

CONTRAST_NUM_FILES = 7


def _contrast_profile():
    """TIDMAD with exactly one field changed."""
    profile = TIDMAD_PROFILE.model_copy(deep=True)
    profile.dataset.num_files = CONTRAST_NUM_FILES
    return profile


class TestContrastFixtureIsAtomic:
    """The rung is only meaningful if it varies ONE axis."""

    def test_exactly_one_field_differs_from_the_tidmad_declaration(self):
        baseline = TIDMAD_PROFILE.model_dump()
        contrast = _contrast_profile().model_dump()

        differing = _diff_paths(baseline, contrast)
        assert differing == ["dataset.num_files"], (
            f"the contrast fixture varies {differing}; design §6.4 approves "
            "'dataset.num_files' ALONE. If a one-axis fixture cannot be valid, "
            "STOP and report the source reason — do not add a second axis."
        )

    def test_segments_per_file_is_explicitly_held(self):
        """Named separately because it is the axis most likely to drift in.

        02a already proved the profile can represent geometry; re-varying it
        here would re-answer 02a's question instead of 02b's.
        """
        assert _contrast_profile().dataset.segments_per_file == (
            TIDMAD_PROFILE.dataset.segments_per_file
        )


def _diff_paths(left, right, prefix=""):
    """Dotted paths at which two nested dicts differ."""
    paths = []
    for key in sorted(set(left) | set(right)):
        path = f"{prefix}{key}"
        lv, rv = left.get(key), right.get(key)
        if isinstance(lv, dict) and isinstance(rv, dict):
            paths.extend(_diff_paths(lv, rv, prefix=f"{path}."))
        elif lv != rv:
            paths.append(path)
    return paths


class TestSelectionFollowsTheContrastTopology:
    def test_file_population_is_the_contrast_not_tidmad(self):
        """The observable Stage-B property, at the selection boundary."""
        with patch.object(
            sample_set_builder,
            "resolve_dataset_profile",
            side_effect=AssertionError("ambient resolution was consulted"),
        ):
            result = build_sample_set(
                is_trial=True,
                trial_strategy="snapshot",
                trial_portion=0.05,
                seed=42,
                profile=_contrast_profile(),
            )

        assert sorted(result) == list(range(CONTRAST_NUM_FILES))
        assert len(result) != TIDMAD_PROFILE.dataset.num_files, (
            "selection produced TIDMAD's file population under a contrast "
            "profile — a consumer is still assuming 20 files"
        )

    def test_index_space_is_untouched_by_the_contrast(self):
        """num_files moved; segments_per_file must NOT have.

        Guards the rung against silently becoming two-axis: if a future
        edit varied geometry too, this would still pass only while the
        segment count matches TIDMAD's declaration.
        """
        with patch.object(
            sample_set_builder,
            "resolve_dataset_profile",
            side_effect=AssertionError("ambient resolution was consulted"),
        ):
            result = build_sample_set(is_trial=False, file_index=0, profile=_contrast_profile())
        assert len(result[0]) == TIDMAD_PROFILE.dataset.segments_per_file

    def test_scope_resolution_follows_the_contrast_population(self):
        """DataScope.default() must resolve against the SUPPLIED profile.

        This is the specific hop that would silently keep working against
        TIDMAD if the builder re-resolved the profile internally.
        """
        with patch.object(
            sample_set_builder,
            "resolve_dataset_profile",
            side_effect=AssertionError("ambient resolution was consulted"),
        ):
            result = build_sample_set(
                is_trial=True,
                trial_strategy="snapshot",
                trial_portion=0.05,
                seed=42,
                scope=DataScope.default(),
                profile=_contrast_profile(),
            )
        assert sorted(result) == list(range(CONTRAST_NUM_FILES))

    def test_out_of_contrast_file_is_rejected(self):
        """The contrast's index space is enforced, not merely described.

        File 12 exists under TIDMAD but not under a 7-file topology.
        """
        with pytest.raises(ValueError, match="outside the DataScope"):
            build_sample_set(is_trial=False, file_index=12, profile=_contrast_profile())
