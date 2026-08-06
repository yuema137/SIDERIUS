"""M6 — an unresolvable required probe must not become a proceed.

The pre-launch audit (2026-08-06) found the production path doing:

    REQUEST_PROBE -> production probe unavailable -> proceed using the prior

which is exactly the "a formal decision may not rest on a prior" defect
C8 exists to remove. The docstring claimed a launch guard prevented it;
it does not — `run_launch_self_test(require_probe_runner=True)` has one
caller, `bootstrap.run_bootstrap`, which the chain never executes.

The correction fails closed for the EXPENSIVE EXECUTION only: a
production scientific formal attempt is not launched, the reason is
persisted, and the campaign continues under normal skip semantics.

Only these tests catch it: the schema cannot express "which branch", and
the fail-open returned a perfectly valid `"proceed"` string.
"""

from __future__ import annotations

import pytest

from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _resolve_time_check_probe_request,
)


@pytest.fixture
def unavailable_probe(monkeypatch):
    """Make the production probe unresolvable, as on a CPU box."""
    import core.runtime_control.probe_wiring as wiring

    monkeypatch.setattr(
        wiring,
        "probe_runner_availability",
        lambda *_a, **_k: (False, "synthetic: no measurement capability"),
    )


def _time_check() -> dict:
    return {
        "feasible": True,
        "breakdown": {"runtime_decision": "REQUEST_PROBE", "total_train_steps": 100},
    }


def _resolve(time_check: dict, *, is_trial: bool, result_authority: str | None) -> str:
    return _resolve_time_check_probe_request(
        time_check,
        model_type="punet",
        active_params={"train_config": {"batch_size": 4}, "model_config": {}},
        time_budget_minutes=20.0,
        is_trial=is_trial,
        data_dir=None,
        run_name="m6_run",
        exp_id="exp_001",
        result_authority=result_authority,
    )


class TestAScientificFormalAttemptFailsClosed:
    def test_it_is_not_admitted(self, unavailable_probe):
        tc = _time_check()
        assert _resolve(tc, is_trial=False, result_authority="scientific") == "skip"

    def test_the_attempt_is_actually_stopped(self, unavailable_probe):
        # The caller only inspects `== "abort"`; the skip is realised by
        # this in-place mutation, so returning "skip" without it would
        # still run the attempt. That asymmetry is why this is asserted
        # separately from the return value.
        tc = _time_check()
        _resolve(tc, is_trial=False, result_authority="scientific")
        assert tc["feasible"] is False

    def test_the_reason_is_persisted_and_distinguishable(self, unavailable_probe):
        tc = _time_check()
        _resolve(tc, is_trial=False, result_authority="scientific")
        breakdown = tc["breakdown"]
        assert breakdown["probe_resolution"] == "unavailable"
        assert breakdown["probe_resolution_enforced"] is True
        # Resume and diagnostics must tell this apart from a resource
        # rejection, a HealthGate invalidity and a scientific failure.
        assert breakdown["measurement_evidence"] == "not_established"
        assert breakdown["admission"] == "not_admitted"

    def test_it_does_not_abort_the_whole_chain(self, unavailable_probe):
        # Fail closed for the execution, not for the campaign.
        tc = _time_check()
        assert _resolve(tc, is_trial=False, result_authority="scientific") != "abort"


class TestEverythingElseKeepsTheAdvisory:
    @pytest.mark.parametrize(
        ("is_trial", "authority"),
        [
            (True, "scientific"),  # the cheap screen, already proceeds unproven
            (False, "diagnostic"),  # results may not inform science anyway
            (False, None),  # pseudo / CPU / undeclared
            (True, None),
        ],
    )
    def test_proceed_with_a_visible_advisory(self, unavailable_probe, is_trial, authority):
        tc = _time_check()
        assert _resolve(tc, is_trial=is_trial, result_authority=authority) == "proceed"
        assert tc["feasible"] is True
        assert tc["breakdown"]["probe_resolution_enforced"] is False


class TestTheGateOnlyFiresOnARealRequest:
    def test_a_non_request_preflight_is_untouched(self, unavailable_probe):
        tc = {"feasible": True, "breakdown": {"runtime_decision": "ALLOW"}}
        assert _resolve(tc, is_trial=False, result_authority="scientific") == "proceed"
        assert tc["feasible"] is True
        assert "probe_resolution" not in tc["breakdown"]
