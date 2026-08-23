"""Step 05b C5 — the live workload/time path prices the RUN-BOUND topology.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
C5, §8 subcase B2, §10 failure class 4.

Every live resolver on the resource path used to end in the same shape::

    profile = profile or resolve_dataset_profile()

An optional parameter with a singleton fallback. It looks like injection and
behaves like ambient state: a run bound to one decomposition topology is
PRICED against whatever singleton happens to be resolved, and the two agree
right up until they do not. Step 02b removed this shape from sample-set
construction and Step 05a from the rest of the tuner; C5 removes it from
workload and time resolution.

The failure classes guarded here:

1. **the fallback comes back.** A migrated site quietly regaining an ambient
   default would restore the defect while every step-count assertion in the
   repository stayed green, because under TIDMAD the two answers agree.
2. **TIDMAD parity moves.** Threading a value must not change one unit of
   any breakdown — failure class 3, a STOP rather than a tolerance.
3. **the derived terms do not actually follow the bound profile.** The
   mirror of (1): a resolver that ignored its new argument would also stay
   green under TIDMAD.

A dead or diagnostic-only estimator is deliberately NOT covered, because it
is deliberately not migrated (§4).
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from agent.skills.inference_skill.estimator import _total_inference_steps
from agent.skills.training_skill.estimator import _total_train_steps
from execute_tools import workload_resolvers
from execute_tools.dataset_config import (
    TIDMAD_PROFILE,
    tidmad_topology,
)

#: The incident scope the RT1 resolver tests use — 6 files x 20 PSD segments.
SS = {str(i): list(range(20)) for i in range(4, 10)}

#: A contrast that varies ONLY the decomposition length. Every other dataset,
#: channel and encoding fact is the shipped one, so anything that moves is
#: attributable to this single axis.
CONTRAST_PSD = 2_048_000


def _contrast_profile():
    return TIDMAD_PROFILE.model_copy(
        update={
            "dataset": tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(
                update={"psd_segment_length": CONTRAST_PSD}
            )
        }
    )


# ---------------------------------------------------------------------------
# 1. No ambient fallback remains on the live resource path
# ---------------------------------------------------------------------------

#: The live workload/time surfaces C5 migrated. `resolve_formal_workloads`
#: is in this module too but is DEAD (zero callers anywhere); it is threaded
#: for signature coherence, not genericized.
LIVE_RESOURCE_MODULES = (
    "execute_tools/workload_resolvers.py",
    "agent/skills/inference_skill/estimator.py",
    "agent/skills/training_skill/estimator.py",
    "agent/skills/evaluate_time_skill/wrapper.py",
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_no_live_resource_consumer_resolves_a_profile_of_its_own():
    """The architectural guard.

    Supporting evidence for the semantic assertions below, and the only one
    that catches a NEW consumer introduced later with the old shape — which
    a value-based test cannot, because it does not know the site exists.
    """
    offenders = []
    for rel in LIVE_RESOURCE_MODULES:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        if "resolve_dataset_profile" in source:
            offenders.append(rel)
    assert not offenders, (
        "a live resource/time consumer acquires a Dataset Profile on its own "
        f"authority instead of receiving the run-bound one: {offenders}"
    )


@pytest.mark.parametrize(
    ("func", "param"),
    [
        (workload_resolvers.resolve_training_workload, "profile"),
        (workload_resolvers.resolve_inference_workload, "profile"),
        (workload_resolvers._validate_seg, "profile"),
    ],
)
def test_the_profile_is_required_not_optional_with_a_fallback(func, param):
    """Required, because every production caller can supply it (the 05a
    precedent). An optional parameter no production caller omits is dead
    permission — and the one place it would be exercised is the defect."""
    assert inspect.signature(func).parameters[param].default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 2. TIDMAD parity
# ---------------------------------------------------------------------------


class TestTidmadParity:
    """Hardcoded expectations, taken from the resolvers' own incident cases.

    Comparing against a freshly resolved value would compare the code with
    itself and pass for any topology.
    """

    def test_training_workload_is_unchanged(self):
        w = workload_resolvers.resolve_training_workload(
            SS,
            seg_size=1250,
            profile=TIDMAD_PROFILE,
            batch_size=2,
            train_portion=1.0,
            epochs=1,
        )
        assert w.unit_count == 480_000
        assert w.detail["samples_per_epoch"] == 960_000
        assert w.detail["ml_segments_per_psd"] == 8_000

    def test_inference_workload_is_unchanged_including_output_bytes(self):
        w = workload_resolvers.resolve_inference_workload(
            SS, seg_size=1250, inference_batch_size=64, profile=TIDMAD_PROFILE
        )
        assert w.unit_count == 15_000
        assert w.detail["total_ml_segments"] == 960_000
        # denoised + injected, one int8 channel each
        assert w.detail["output_bytes"] == 120 * 10_000_000 * 2

    def test_both_step_resolvers_agree_with_their_workload(self):
        """`_total_train_steps` and `_total_inference_steps` are thin views
        over the resolvers; threading a profile must not have forked them."""
        assert _total_train_steps(SS, 1250, 2, 1.0, 1, TIDMAD_PROFILE) == 480_000
        assert _total_inference_steps(SS, 1250, 64, TIDMAD_PROFILE) == 15_000


# ---------------------------------------------------------------------------
# 3. B2 — the derived terms follow the bound profile
# ---------------------------------------------------------------------------


class TestDerivedTermsFollowTheBoundProfile:
    """Stage-B subcase B2: vary ONLY the decomposition fact.

    ``ModelIOContract``, calibration, hardware and policy are untouched, so
    a term that moves moved because of the topology and nothing else.
    """

    def test_training_step_count_follows_the_contrast_topology(self):
        contrast = _contrast_profile()
        w = workload_resolvers.resolve_training_workload(
            SS, seg_size=1250, profile=contrast, batch_size=2, train_portion=1.0, epochs=1
        )
        assert w.detail["ml_segments_per_psd"] == CONTRAST_PSD // 1250
        assert w.unit_count == (120 * (CONTRAST_PSD // 1250)) // 2
        assert w.unit_count != 480_000, "the TIDMAD answer under a contrast profile"

    def test_inference_output_bytes_follow_the_contrast_topology(self):
        """``output_bytes`` is priced separately from compute (§2.6), so it
        is the term a topology change is most likely to leave behind."""
        w = workload_resolvers.resolve_inference_workload(
            SS, seg_size=1250, inference_batch_size=64, profile=_contrast_profile()
        )
        assert w.detail["output_bytes"] == 120 * CONTRAST_PSD * 2

    def test_a_bound_contrast_does_not_leak_through_an_ambient_read(self):
        """The mirror of the architectural guard, at the value level: the
        resolver must answer from its ARGUMENT even while a different
        profile is the ambient one. Before C5 the argument was optional and
        the ambient value could win; this asserts it cannot."""
        from execute_tools.dataset_config import bind_dataset_profile

        with bind_dataset_profile(_contrast_profile()):
            w = workload_resolvers.resolve_training_workload(
                SS,
                seg_size=1250,
                profile=TIDMAD_PROFILE,
                batch_size=2,
                train_portion=1.0,
                epochs=1,
            )
        assert w.unit_count == 480_000, (
            "the resolver followed the ambient binding instead of its argument"
        )
