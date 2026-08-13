"""PR-02b B2 — the selection path takes its profile EXPLICITLY.

Stage A: **same semantics, new transport.** Before this commit
`build_sample_set()` resolved the Dataset Profile ambiently, at three
separate points, so a run bound to a non-default topology would silently
select against the ambient one. The tuner now resolves the run's profile
ONCE and supplies it to both construction sites.

The question this module answers is *"is the explicit hop LIVE?"* — not
*"does a different topology work?"*, which is B4's question. Using a
non-TIDMAD contrast here would smuggle Stage B into Stage A, so every
profile below is TIDMAD-**equivalent**.

The proof technique is the one the design asks for: **ambient resolution is
made to FAIL if consulted.** A merely decorative parameter would fall
through to the ambient resolver and pass; a live one never reaches it.

Failure class guarded (design §8): **ambient-fallback reachability** — a
call site silently stopping supplying the profile explicitly.

Not re-asserted here: the five sha16 digests and the first-five segment
indices, which `tests/unit/execute_tools/test_sample_set_builder.py` already
pins and which must pass UNMODIFIED across this commit.
"""

from unittest.mock import patch

import pytest

from execute_tools import sample_set_builder
from execute_tools.dataset_config import TIDMAD_PROFILE, DataScope
from execute_tools.sample_set_builder import build_sample_set

# Equal to TIDMAD but a DISTINCT object, so a test cannot pass merely
# because the builder happened to reach the same singleton by another route.
TIDMAD_EQUIVALENT = TIDMAD_PROFILE.model_copy(deep=True)

SELECTIONS = [
    {"is_trial": True, "trial_strategy": "snapshot", "trial_portion": 0.05, "seed": 42},
    {"is_trial": True, "trial_strategy": "anchors", "trial_portion": 0.05, "seed": 42},
    {
        "is_trial": True,
        "trial_strategy": "target",
        "trial_portion": 0.05,
        "seed": 42,
        "target_files": [3, 11],
    },
    {"is_trial": False, "file_index": 6},
    {
        "is_trial": True,
        "trial_strategy": "snapshot",
        "trial_portion": 0.05,
        "seed": 42,
        "scope": DataScope(file_indices=[4, 5, 6, 7, 8, 9]),
    },
]


class _AmbientConsulted(RuntimeError):
    """Raised if the builder falls back to ambient resolution."""


def _ambient_disabled():
    """Patch the BUILDER's binding only.

    `sample_set_builder` binds `resolve_dataset_profile` at import, so this
    disables ambient resolution for the builder while leaving every other
    module — including the tuner, which legitimately resolves the run's
    profile — free to resolve normally.
    """
    return patch.object(
        sample_set_builder,
        "resolve_dataset_profile",
        side_effect=_AmbientConsulted("build_sample_set fell back to ambient resolution"),
    )


class TestExplicitProfileIsLive:
    @pytest.mark.parametrize("kwargs", SELECTIONS, ids=lambda k: str(k.get("trial_strategy", k)))
    def test_selection_succeeds_with_ambient_disabled(self, kwargs):
        """The sharpest available proof the parameter is not decorative."""
        with _ambient_disabled() as ambient:
            result = build_sample_set(profile=TIDMAD_EQUIVALENT, **kwargs)
        assert result, "explicit profile produced an empty SampleSet"
        ambient.assert_not_called()

    @pytest.mark.parametrize("kwargs", SELECTIONS, ids=lambda k: str(k.get("trial_strategy", k)))
    def test_explicit_path_is_identical_to_the_ambient_path(self, kwargs):
        """Stage A in one assertion: new transport, byte-identical selection.

        The digests remain the primary oracle (asserted unmodified in
        test_sample_set_builder.py); this pins the *equivalence of the two
        routes*, which no digest can express because only one route existed
        when they were captured.
        """
        ambient_result = build_sample_set(**kwargs)
        with _ambient_disabled():
            explicit_result = build_sample_set(profile=TIDMAD_EQUIVALENT, **kwargs)
        assert explicit_result == ambient_result

    def test_absent_profile_still_resolves_ambiently(self):
        """Regime-A preserved: un-migrated callers must not break (§1a-F).

        `scripts/run_comparison.py` and `agent/utils/proposer_preflight.py`
        have no profile in scope and deliberately keep this path.
        """
        with patch.object(
            sample_set_builder, "resolve_dataset_profile", return_value=TIDMAD_EQUIVALENT
        ) as ambient:
            result = build_sample_set(is_trial=True, trial_portion=0.05, seed=42)
        assert result
        assert ambient.called, "the None default stopped falling back to Regime-A"


class TestProfileIsConsumedNotRederived:
    """02b must consume 02a's authority, never create a second one."""

    def test_segment_count_follows_the_supplied_profile(self):
        """Normal mode reads its index space from the profile it was given.

        Regression guard for the specific bug the pre-B2 code had: three
        independent `resolve_dataset_profile()` calls inside one build, any
        of which could disagree with the caller.
        """
        narrow = TIDMAD_PROFILE.model_copy(deep=True)
        narrow.dataset.segments_per_file = 7
        with _ambient_disabled():
            result = build_sample_set(is_trial=False, file_index=6, profile=narrow)
        assert len(result[6]) == 7, (
            "normal mode did not read segments_per_file from the supplied profile"
        )

    def test_builder_declares_no_topology_constant(self):
        """No TIDMAD constant may reappear in the selection module.

        `ANCHOR_FILES` is deliberately exempt — it is 02c's group
        declaration, not 02b's to migrate.
        """
        source = sample_set_builder.__file__ or ""
        assert source
        with open(source) as f:
            text = f.read()
        for forbidden in ("NUM_FILES", "SEGMENTS_PER_FILE", "SEGMENT_LENGTH"):
            assert forbidden not in text, (
                f"{forbidden} reappeared in sample_set_builder.py — selection must "
                "consume the profile, never re-declare topology"
            )
