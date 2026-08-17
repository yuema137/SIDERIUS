"""Every pre-flight outcome must reach a tuner action.

THE DEFECT (found 2026-08-02 by a test audit, verified against production).

`preflight_adapter.py:176` writes the `feasible` key only when it is not
`None`. Three outcomes map to a legacy pair whose second element IS
`None`:

    MEASURED_HARD_TIMEOUT            -> ("timeout", None)
    HOST_MEMORY_ALLOCATION_FAILURE   -> ("host_memory", None)
    MEASURED_HOST_MEMORY_EXCEEDED    -> ("host_memory", None)

so those results carry no `feasible` key at all. The tuner's only capacity
guard was:

    if not resource_check.get("feasible", True):

which therefore read the DEFAULT -- `True`, i.e. *feasible* -- and the
attempt proceeded to launch training. A worker RSS-killed exactly as on
2026-07-31 returned the correct outcome, the adapter mapped it correctly,
and the tuner started training anyway.

Every layer was individually correct and individually tested. The
81-test host-memory apparatus terminated in a consumer that ignored it.
That is the same shape as the A5 field-drop and the never-called isolated
worker: a component built, tested, and discarded by its only consumer.

So these tests are about the CONSUMER, and the first one is about the
whole class rather than the three known instances.
"""

from __future__ import annotations

import pytest

from agent.skills.evaluate_vram_skill.preflight_adapter import OUTCOME_TO_LEGACY
from agent.skills.evaluate_vram_skill.probe_budgets import InconclusivePreflight
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    PREFLIGHT_CONSUMER_ACTIONS,
    _classify_attempt_failure,
    _raise_if_preflight_blocks,
)
from tests.helpers.tuner_source import tuner_node_source

#: The three that fell through. Named so a regression says which.
FELL_THROUGH = ["timeout", "host_memory"]


class TestEveryOutcomeReachesAnAction:
    """The class-level guard. Fixing three instances leaves the fourth."""

    def test_every_adapter_status_has_a_consumer_action(self):
        """Mirrors the adapter's own `_assert_mapping_is_exhaustive`, one
        layer down. A new PreflightOutcome that nobody wires up fails here
        instead of silently meaning "safe to run"."""
        emitted = {status for status, _ in OUTCOME_TO_LEGACY.values()}
        unhandled = sorted(emitted - set(PREFLIGHT_CONSUMER_ACTIONS))
        assert unhandled == [], (
            f"pre-flight can emit {unhandled} but no consumer branch handles "
            "them; they would fall through to the feasible-default and start "
            "training"
        )

    def test_no_consumer_action_is_orphaned(self):
        """The other direction, which was not asserted.

        An action keyed on a status the adapter can no longer emit is dead
        policy that reads as coverage: the table still looks exhaustive, so
        the rename that orphaned it goes unnoticed -- and the status that
        REPLACED it has no action at all. Checking only
        `emitted - handled` cannot see that, because the orphan keeps the
        difference empty.
        """
        emitted = {status for status, _ in OUTCOME_TO_LEGACY.values()}
        orphaned = sorted(set(PREFLIGHT_CONSUMER_ACTIONS) - emitted)
        assert orphaned == [], (
            f"the consumer has actions for {orphaned}, which pre-flight "
            "cannot emit; the adapter was renamed out from under this table"
        )

    def test_an_unknown_status_refuses_rather_than_proceeding(self):
        """The failure mode, generalised: an unrecognised status must never
        be read as permission."""
        with pytest.raises(RuntimeError, match="never be read as permission"):
            _raise_if_preflight_blocks({"status": "some_future_outcome"})

    def test_a_missing_status_also_refuses(self):
        with pytest.raises(RuntimeError):
            _raise_if_preflight_blocks({})


class TestBlockingOutcomesStopTheAttempt:
    @pytest.mark.parametrize("status", FELL_THROUGH)
    def test_it_raises_instead_of_returning_an_action(self, status):
        """Before the fix these returned no action at all -- control simply
        continued past the guard and reached the training launch."""
        with pytest.raises(InconclusivePreflight):
            _raise_if_preflight_blocks({"status": status, "message": "m"})

    @pytest.mark.parametrize("status", [*FELL_THROUGH, "inconclusive"])
    def test_the_kinds_stay_distinguishable(self, status):
        """All three block identically but are different facts. A
        host-memory kill recorded as a measurement timeout is how a
        machine problem becomes a conclusion about the model."""
        with pytest.raises(InconclusivePreflight) as exc:
            _raise_if_preflight_blocks({"status": status, "message": "m"})
        assert exc.value.kind == ("inconclusive" if status == "inconclusive" else status)

    @pytest.mark.parametrize("status", [*FELL_THROUGH, "inconclusive"])
    def test_the_attempt_failure_classification_is_kind_specific(self, status):
        """Downstream feedback keys off this name."""
        exc = InconclusivePreflight(
            "m", kind="inconclusive" if status == "inconclusive" else status
        )
        assert _classify_attempt_failure(exc, None) == f"{exc.kind}_preflight"

    @pytest.mark.parametrize("status", [*FELL_THROUGH, "inconclusive"])
    def test_it_carries_no_shrink_advice_and_no_candidate_blame(self, status):
        """Lane discipline: nothing was measured, so nothing may be said
        about the candidate's size."""
        with pytest.raises(InconclusivePreflight) as exc:
            _raise_if_preflight_blocks(
                {
                    "status": status,
                    "message": "m",
                    # A hostile payload: even if the worker sent shrink text,
                    # a blocked pre-flight must not forward it.
                    "suggestion": "Reduce batch_size.",
                    "verdict": "model too large",
                }
            )
        blob = f"{exc.value} {exc.value.record}"
        for banned in ("Reduce batch_size", "too large", "reduce model", "shrink"):
            assert banned.lower() not in blob.lower()


class TestNonBlockingOutcomesStillFlowThrough:
    """The fix must not turn working paths into refusals."""

    @pytest.mark.parametrize(
        "status,expected",
        [
            ("success", "capacity_verdict"),
            ("error", "infrastructure_error"),
            ("schema_violation", "schema_violation"),
        ],
    )
    def test_it_returns_the_action_for_inline_handling(self, status, expected):
        assert _raise_if_preflight_blocks({"status": status}) == expected

    def test_a_feasible_success_is_not_blocked(self):
        assert (
            _raise_if_preflight_blocks({"status": "success", "feasible": True})
            == "capacity_verdict"
        )


class TestTheProductionPathUsesTheTable:
    """Reachability. A guard the production path can bypass is not a guard
    -- the whole defect was a correct decision nobody consumed."""

    @staticmethod
    def _tuner_source() -> str:
        # The node, not one of its files: the pre-flight resolver call moved
        # into the node's private `execution` module (Step 07 PR 07b, C7d) and
        # is still the same production call site.
        return tuner_node_source()

    def test_run_calls_the_resolver(self):
        assert "_raise_if_preflight_blocks(resource_check)" in self._tuner_source()

    def test_the_bare_feasible_default_is_gone(self):
        """`.get("feasible", True)` is the exact expression that read "no
        conclusion" as "safe to run". If it returns, every status reaching
        it has already been resolved by the table."""
        # Comment lines stripped first: the constant's own docstring QUOTES
        # the old expression to explain the defect, and a naive search finds
        # that quote before the real call site.
        code = "\n".join(
            line for line in self._tuner_source().splitlines() if not line.lstrip().startswith("#")
        )
        assert "_raise_if_preflight_blocks" in code
        # The capacity read may remain, but only downstream of the resolver.
        assert code.index("_raise_if_preflight_blocks(resource_check)") < code.index(
            'resource_check.get("feasible"'
        )
