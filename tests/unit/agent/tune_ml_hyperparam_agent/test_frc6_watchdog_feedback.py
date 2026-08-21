"""F-RC-6 — an ACTUAL watchdog kill reaches the architectural-feedback trigger.

Gate-discovered generic prerequisite fix (runtime-control feedback
representation). **Not P5+P6 lifecycle semantics.**

**The defect.** `_collect_disallowed_patterns` is the mechanism that tells the
next proposer "this architecture is too expensive". It considered only
PREDICTED gate skips::

    status in {"skipped_oom_risk", "skipped_time_risk"}

An attempt that was admitted, executed, and then killed by the watchdog is
recorded with ``status="error"``
(`ml_hyperparameter_tune_agent.py:1404`), so it was excluded. The one
structured signal designed to end a "too slow" loop was unavailable for the
very failure that proves the candidate is too slow — leaving only the
free-text `memory_update` note, which the planner may or may not act on.

Observed in a real Gate run: three consecutive watchdog kills, no
architectural feedback emitted at any point.

**Why the discriminator is `failure_type`, not `status`.** A code bug, a schema
violation and an OOM are all ``status="error"`` too, and none is evidence about
architecture. `_classify_attempt_failure` (`runtime.py:518`) already emits the
typed ``"wall_clock_timeout"`` for exactly this case, and its docstring states
that downstream feedback keys off the name. No new taxonomy was introduced.

**Why it is categorical rather than factor-tested.** The watchdog kills AT the
deadline, so ``elapsed / deadline`` is ~1.003 by construction (60.166 s against
60.0 s in the run that found this). It could never clear
``TIME_FACTOR_THRESHOLD = 5.0``. That threshold separates a marginal
PREDICTION overshoot from a structural one; a real kill has nothing to
separate — the attempt demonstrably did not finish.

The defect class only this module catches: a real failure whose RECORD
REPRESENTATION excludes it from the recovery mechanism built for it. Every
individual component behaves correctly; the mismatch is between them.
"""

from __future__ import annotations

import pytest

from agent.utils.architectural_pattern_tagger import TIME_FACTOR_THRESHOLD
from nodes.ml_hyperparameter_tune_agent.feedback import _collect_disallowed_patterns

#: A model the tagger genuinely recognises, so a qualifying record produces a
#: NON-EMPTY tag set and "no tags" is never ambiguous.
#:
#: Verified against the live tagger rather than invented: its vocabulary is
#: narrow (`recurrent_over_T`, `dense_attention_over_T`, `scan_over_T`), and a
#: first draft used a plausible-sounding `wavenet_deep_stack`, which matches
#: NOTHING — making every assertion below vacuously green. The pre-existing
#: predicted-skip test failing is what exposed that.
MODEL_TYPE = "dual_path_gated_gru_stack"
MODEL_CONFIG = {"hidden_size": 128}
EXPECTED_TAGS = ["recurrent_over_T"]


def _watchdog_record(*, elapsed=60.166, deadline=60.0):
    """An attempt that RAN and was killed — the shape the tuner really writes."""
    return {
        "record_type": "attempt_failure",
        "status": "error",  # what a watchdog kill is actually recorded as
        "failure_type": "wall_clock_timeout",
        "failure_stage": "training",
        "model_type": MODEL_TYPE,
        "model_config": MODEL_CONFIG,
        "memory": {
            "watchdog_elapsed_s": elapsed,
            "watchdog_deadline_s": deadline,
            "watchdog_estimate_source": "verified_components",
        },
    }


def _predicted_skip_record(*, time_estimate_minutes=60.0):
    """An attempt REJECTED at admission — the pre-existing Trigger B input."""
    return {
        "record_type": "attempt_failure",
        "status": "skipped_time_risk",
        "model_type": MODEL_TYPE,
        "model_config": MODEL_CONFIG,
        "memory": {"time_estimate_minutes": time_estimate_minutes},
    }


def _ordinary_error_record(failure_type="ValueError"):
    """A NON-resource failure that also carries status='error'."""
    return {
        "record_type": "attempt_failure",
        "status": "error",
        "failure_type": failure_type,
        "failure_stage": "training",
        "model_type": MODEL_TYPE,
        "model_config": MODEL_CONFIG,
        "memory": {},
    }


def _collect(records):
    return _collect_disallowed_patterns(records, vram_budget_gb=4.0, time_budget_minutes=10.0)


# ---------------------------------------------------------------------------
# The four cases the operator required
# ---------------------------------------------------------------------------


class TestWhatReachesTheTrigger:
    def test_a_predicted_time_risk_skip_still_fires(self):
        """The pre-existing behaviour, unchanged. 60 min against a 10 min
        budget is a factor of 6, above the 5.0 threshold."""
        assert _collect([_predicted_skip_record()])

    def test_an_actual_watchdog_timeout_now_fires(self):
        """THE FIX. Before F-RC-6 this returned no tags."""
        assert _collect([_watchdog_record()])

    @pytest.mark.parametrize(
        "failure_type",
        ["ValueError", "ValidationError", "model_forward_error", "measurement_preflight"],
    )
    def test_no_other_error_type_fires(self, failure_type):
        """The guard against the naive `status == "error"` repair.

        A code bug carries the same status as a watchdog kill and must NOT be
        read as "your architecture is too expensive" — that would teach the
        proposer to shrink a model over a `ValueError`. Every neighbouring
        failure_type stays out, so the discrimination is on the typed name,
        not on the status lane.

        (`_ordinary_error_record()`'s default IS ``"ValueError"``, so a
        separate un-parametrized test for that case was the same call twice.)
        """
        assert _collect([_ordinary_error_record(failure_type)]) == []

    def test_a_successful_record_does_NOT_fire(self):
        record = {
            "record_type": "experiment",
            "status": "success",
            "model_type": MODEL_TYPE,
            "model_config": MODEL_CONFIG,
            "memory": {},
        }
        assert _collect([record]) == []


# ---------------------------------------------------------------------------
# Anti-vacuity: the tags are REAL, and the threshold genuinely excludes timeouts
# ---------------------------------------------------------------------------


class TestTheSignalIsReal:
    def test_the_fix_produces_the_SAME_tags_a_predicted_skip_would(self):
        """Not merely "non-empty" — a watchdog kill must produce the same
        structured architectural advice the predicted path produces for the
        same model, since it is the same claim about the same shape."""
        assert _collect([_watchdog_record()]) == _collect([_predicted_skip_record()])

    def test_the_tags_are_the_EXPECTED_ones_not_merely_non_empty(self):
        """Hardcoded expectation, not "truthy": a tag set that silently changed
        content would still be non-empty."""
        tags = _collect([_watchdog_record()])
        assert tags == EXPECTED_TAGS
        assert tags == sorted(tags)
        assert _collect([_watchdog_record()]) == tags

    def test_a_factor_test_could_NEVER_have_caught_a_real_timeout(self):
        """The reason the fix is categorical, made executable.

        The watchdog kills AT the deadline, so the observed ratio is ~1.003.
        Routing timeouts through the factor test would have been a silent
        no-op, and this pins why.
        """
        record = _watchdog_record(elapsed=60.166, deadline=60.0)
        mem = record["memory"]
        ratio = mem["watchdog_elapsed_s"] / mem["watchdog_deadline_s"]
        assert ratio < 1.01
        assert ratio < TIME_FACTOR_THRESHOLD
        # ...and yet it must still fire.
        assert _collect([record])

    def test_a_marginal_predicted_overshoot_is_still_ignored(self):
        """The threshold's original purpose survives: a 1.3x PREDICTION is a
        hyperparameter choice, not an architectural verdict."""
        assert _collect([_predicted_skip_record(time_estimate_minutes=13.0)]) == []


class TestMixedRecordSets:
    def test_a_timeout_among_ordinary_errors_still_contributes(self):
        records = [
            _ordinary_error_record(),
            _watchdog_record(),
            _ordinary_error_record("ValidationError"),
        ]
        assert _collect(records) == _collect([_watchdog_record()])

    def test_only_ordinary_errors_yields_nothing(self):
        assert _collect([_ordinary_error_record(), _ordinary_error_record()]) == []

    def test_an_empty_record_set_is_empty(self):
        assert _collect([]) == []
