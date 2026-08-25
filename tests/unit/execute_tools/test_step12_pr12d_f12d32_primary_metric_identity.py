"""Step 12 / PR-12d — F-12d-32: the PRIMARY metric's identity must cross the
task-owned scoring child, not only its value.

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q D-12d-55.

**The defect, from two REAL completed contrast runs.** Both persisted a valid
score and ``"metric_result": null``:

```text
denoising_score           : 0.0945945945945946        <- the VALUE crossed
metric_result             : null                      <- the IDENTITY did not
secondary_metric_results  : [{"metric_id": "macro_f1", "direction": "higher", …},
                             {"metric_id": "log_loss", "direction": "lower",  …}]
```

The secondaries carried full identity; the primary carried none. Two causes,
one on each side of the process boundary:

* the task-owned child emitted only ``{denoising_score, file_vector}``,
  discarding the ``metric_id``/``direction`` its own ``MetricResult``
  already held;
* the tuner assigns ``metric_payload`` in exactly ONE place, inside the
  ``ANCHOR_NORMALIZED`` branch, so on the task-owned route nothing could
  supply it.

§I requires the terminal report to carry ``accuracy`` / **HIGHER** (Pets) and
``mse`` / **LOWER** (DAVIS), each **proven to be the implementation
production actually bound** — which a bare scalar cannot express. This is the
same shape as F-12d-27 and F-12d-28: a capability that worked on one route
and was simply never wired on the other.

Each test names a defect only it can catch.
"""

from __future__ import annotations

import pytest

from nodes.ml_hyperparameter_tune_agent.execution import _adopt_child_metric_result

#: What the task-owned child now emits, in the shape it really serializes.
CHILD_REPORTED = {
    "denoising_score": 0.0946,
    "metric_result": {
        "metric_id": "accuracy",
        "direction": "higher",
        "scalar": 0.0946,
        "references_used": [],
    },
}


class TestTheIdentityIsAdoptedFromTheChild:
    def test_the_task_owned_route_recovers_metric_id_and_direction(self):
        """THE regression. Before the fix this stayed None and the record
        persisted `metric_result: null` beside a valid score."""
        adopted = _adopt_child_metric_result(CHILD_REPORTED, current=None)
        assert adopted is not None
        assert adopted["metric_id"] == "accuracy"
        assert adopted["direction"] == "higher"

    def test_per_sample_is_excluded_exactly_as_the_anchor_route_excludes_it(self):
        """`per_sample` is a POINTER to `file_vector` on the same record, not
        a second copy. If it leaked in here the two routes would persist
        different record shapes."""
        adopted = _adopt_child_metric_result(CHILD_REPORTED, current=None)
        assert "per_sample" not in adopted


class TestAnchorRouteWins:
    def test_an_in_process_value_is_never_overwritten_by_the_child(self):
        """Total-function precedence, the same rule `_adopt_child_secondaries`
        follows. A child that also reports must never displace what the tuner
        computed in-process, or the two routes would race."""
        anchor = {"metric_id": "tidmad_denoising_score", "direction": "higher", "scalar": -1.4}
        assert _adopt_child_metric_result(CHILD_REPORTED, current=anchor) == anchor


class TestLegacyAndEmptyAreUnchanged:
    def test_a_child_that_reports_nothing_yields_none(self):
        """A legacy child predating this emission must not fabricate an
        identity — `metric_result` stays None, exactly as before."""
        assert _adopt_child_metric_result({"denoising_score": 1.0}, current=None) is None

    def test_an_explicit_null_is_also_none(self):
        assert _adopt_child_metric_result({"metric_result": None}, current=None) is None


class TestAMalformedIdentityFailsLoudly:
    def test_it_is_validated_not_trusted(self):
        """The payload crossed a process boundary as JSON. Re-typing through
        `MetricResult` means a malformed identity raises here rather than
        persisting a half-typed record — the same reason the secondaries
        helper validates instead of using `model_construct`."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _adopt_child_metric_result({"metric_result": {"direction": "higher"}}, current=None)


class TestTheChildActuallyEmitsIt:
    """Reachability. Without this the adopter could be perfect and unreachable
    — which is precisely how this defect survived: the tuner-side assignment
    existed, on a route contrast runs never take."""

    def test_the_task_owned_emitter_includes_metric_result(self):
        import inspect

        from execute_tools import denoising_score_single

        source = inspect.getsource(denoising_score_single._emit_outcome)
        assert '"metric_result"' in source, (
            "the scoring child must emit the primary's identity alongside its "
            "value; `outcome` is already a MetricResult carrying metric_id and "
            "direction"
        )

    def test_the_tuner_adopts_it_on_the_scoring_path(self):
        import importlib
        import inspect

        # The package name is rebound to the node's main module, so the
        # private `execution` module is reached through importlib.
        execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")
        source = inspect.getsource(execution)
        assert "_adopt_child_metric_result(score_results" in source
