"""Unit tests for the post-v15 delta gates: ``skip_formal_min_delta`` and
``bypass_formal_time_budget_min_delta``.

Both gates use ``current_run_best_formal_score`` as the reference point.
Defaults:
  * ``current_run_best_formal_score = 0.0`` (V17 fixed formal reference)
  * ``skip_formal_min_delta = -1.0`` → skip formal when trial < (best - 1.0)
  * ``bypass_formal_time_budget_min_delta = 0.0`` → bypass time gate when
    trial >= best

Motivation: v15 retrospective surfaced two failure modes —
  * trial scores well below baseline still burned formal-round budget
  * trial winners that beat the run best had every formal attempt
    rejected by the time-risk gate (mamba_multirate_fuser, dualpath_
    spectral_router)

See ``reports/v15_20260628.md`` §1.3 / §1.4 for the time-budget data and
``agent/schemas/hyperparam_tuning.py`` (the three field docstrings under
``current_run_best_formal_score``) for the schema definition.
"""

from __future__ import annotations

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig

# ---------------------------------------------------------------------------
# Test fixture — minimal valid HyperparamTuningInput
# ---------------------------------------------------------------------------


def _make_input(**overrides) -> HyperparamTuningInput:
    """Construct a minimal valid HyperparamTuningInput. Tests override the
    three delta-gate fields plus ``current_run_best_formal_score`` to set
    up the threshold arithmetic, then read the field values back to verify
    schema plumbing.

    Pydantic validation happens at construction; mutating the returned
    object afterwards is fine for these tests because we are testing the
    SCHEMA contract, not the tuner's runtime gate logic (which lives
    deeper in ``ml_hyperparameter_tune_agent.py`` and is exercised by
    integration tests).
    """
    storage = StorageConfig(local=LocalStorageConfig(workspace="/tmp/test_delta_gates"))
    base = {
        "model_type": "punet",
        "run_name": "test_delta_gates",
        "storage": storage,
    }
    base.update(overrides)
    return HyperparamTuningInput(**base)


# ---------------------------------------------------------------------------
# Schema-level tests for the three new fields
# ---------------------------------------------------------------------------


class TestDeltaGateSchema:
    def test_default_baseline_used_as_initial_reference(self):
        """V17 fixes ``current_run_best_formal_score`` at zero."""
        inp = _make_input()
        assert inp.current_run_best_formal_score == 0.0

    def test_skip_formal_min_delta_default_is_one_dB_floor(self):
        """Default ``-1.0`` means a trial score has to be more than 1.0
        dB below the current best formal to trigger a skip. Borderline
        scores still get a formal-round shot."""
        inp = _make_input()
        assert inp.skip_formal_min_delta == -1.0

    def test_bypass_formal_time_budget_min_delta_default_is_zero(self):
        """Default ``0.0`` means *any* trial winner that meets-or-beats
        the current best bypasses the time gate. The v15 arch chain's
        trial-only 7.65 and 7.77 would have bypassed at this default."""
        inp = _make_input()
        assert inp.bypass_formal_time_budget_min_delta == 0.0


# ---------------------------------------------------------------------------
# Threshold arithmetic — what the tuner runtime computes per round
# ---------------------------------------------------------------------------
#
# The runtime gates compute:
#   skip_threshold   = current_run_best + skip_formal_min_delta
#   bypass_threshold = current_run_best + bypass_formal_time_budget_min_delta
#
# and fire on:
#   skip   if best_trial_score < skip_threshold
#   bypass if best_trial_score >= bypass_threshold
#
# These tests exercise the arithmetic for the four canonical operator
# scenarios from the design spec.


class TestSkipFormalGate:
    def test_skip_formal_fires_when_trial_well_below_best(self):
        """best_formal=6.0, trial=4.5, delta=-1.0 → threshold=5.0 →
        trial(4.5) < 5.0 → formal SKIPPED."""
        inp = _make_input(
            current_run_best_formal_score=6.0,
            skip_formal_min_delta=-1.0,
        )
        best_trial_score = 4.5
        skip_threshold = inp.current_run_best_formal_score + inp.skip_formal_min_delta
        assert skip_threshold == 5.0
        assert best_trial_score < skip_threshold  # gate fires → skip

    def test_skip_formal_does_not_fire_when_trial_close_to_best(self):
        """best_formal=6.0, trial=5.2, delta=-1.0 → threshold=5.0 →
        trial(5.2) >= 5.0 → formal PROCEEDS.

        A borderline trial close to the current best is still worth a
        formal attempt — the formal eval might confirm or refute it. The
        default delta of -1.0 keeps the door open for these cases."""
        inp = _make_input(
            current_run_best_formal_score=6.0,
            skip_formal_min_delta=-1.0,
        )
        best_trial_score = 5.2
        skip_threshold = inp.current_run_best_formal_score + inp.skip_formal_min_delta
        assert skip_threshold == 5.0
        assert best_trial_score >= skip_threshold  # gate does NOT fire

    def test_skip_with_zero_delta_skips_anything_below_best(self):
        """delta=0.0 → threshold=current_best → trial below best at all
        triggers a skip. Operator may pick this when they only want to
        spend formal budget on actual SOTA-beaters."""
        inp = _make_input(
            current_run_best_formal_score=6.0,
            skip_formal_min_delta=0.0,
        )
        assert inp.current_run_best_formal_score + inp.skip_formal_min_delta == 6.0
        # trial 5.99 (very close, but below) is skipped
        assert 5.99 < 6.0
        # trial 6.01 (just above) proceeds
        assert 6.01 >= 6.0


class TestBypassFormalTimeBudgetGate:
    def test_bypass_fires_when_trial_beats_best(self):
        """best_formal=6.0, trial=6.1, delta=0.0 → threshold=6.0 →
        trial(6.1) >= 6.0 → time gate BYPASSED.

        The v15 arch chain's trial winners (7.65, 7.77) would have
        bypassed under this default — they beat any plausible
        current_run_best at any iter."""
        inp = _make_input(
            current_run_best_formal_score=6.0,
            bypass_formal_time_budget_min_delta=0.0,
        )
        best_trial_score = 6.1
        bypass_threshold = (
            inp.current_run_best_formal_score + inp.bypass_formal_time_budget_min_delta
        )
        assert bypass_threshold == 6.0
        assert best_trial_score >= bypass_threshold  # gate fires → bypass

    def test_bypass_does_not_fire_when_trial_below_best(self):
        """best_formal=6.0, trial=5.9, delta=0.0 → threshold=6.0 →
        trial(5.9) < 6.0 → time gate APPLIES (skipped_time_risk
        proceeds as before)."""
        inp = _make_input(
            current_run_best_formal_score=6.0,
            bypass_formal_time_budget_min_delta=0.0,
        )
        best_trial_score = 5.9
        bypass_threshold = (
            inp.current_run_best_formal_score + inp.bypass_formal_time_budget_min_delta
        )
        assert bypass_threshold == 6.0
        assert best_trial_score < bypass_threshold  # gate does NOT fire

    def test_bypass_with_positive_delta_requires_clear_margin(self):
        """delta=0.5 → only bypass when trial beats current_best by at
        least 0.5 dB. Operator uses this when they want formal budget
        spent only on clearly-beating candidates."""
        inp = _make_input(
            current_run_best_formal_score=6.0,
            bypass_formal_time_budget_min_delta=0.5,
        )
        bypass_threshold = (
            inp.current_run_best_formal_score + inp.bypass_formal_time_budget_min_delta
        )
        assert bypass_threshold == 6.5
        # trial 6.4 (positive but below margin) — time gate APPLIES
        assert 6.4 < bypass_threshold
        # trial 6.5 (at margin) — time gate BYPASSED
        assert 6.5 >= bypass_threshold


class TestDisableGatesViaInfinity:
    """Both gates can be turned off entirely by setting the delta to a
    boundary value. Documented on the field docstrings."""

    def test_skip_gate_disabled_at_negative_infinity(self):
        """``skip_formal_min_delta = -inf`` disables the gate: no trial
        score is below the resulting threshold (which is -inf)."""
        inp = _make_input(
            current_run_best_formal_score=6.0,
            skip_formal_min_delta=float("-inf"),
        )
        skip_threshold = inp.current_run_best_formal_score + inp.skip_formal_min_delta
        assert skip_threshold == float("-inf")
        # The tuner's runtime gate guards on ``_skip_threshold > float("-inf")``
        # so a -inf threshold short-circuits the gate entirely.
        assert not (skip_threshold > float("-inf"))

    def test_bypass_gate_disabled_at_positive_infinity(self):
        """``bypass_formal_time_budget_min_delta = +inf`` disables the
        gate: no trial score reaches the resulting threshold."""
        inp = _make_input(
            current_run_best_formal_score=6.0,
            bypass_formal_time_budget_min_delta=float("inf"),
        )
        bypass_threshold = (
            inp.current_run_best_formal_score + inp.bypass_formal_time_budget_min_delta
        )
        assert bypass_threshold == float("inf")
        # The tuner's runtime gate guards on ``_bypass_threshold < float("inf")``
        # so a +inf threshold short-circuits the gate entirely.
        assert not (bypass_threshold < float("inf"))
