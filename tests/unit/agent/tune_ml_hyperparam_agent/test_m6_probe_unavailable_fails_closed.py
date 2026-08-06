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


class TestTheRefusalSurvivesTheDownstreamGates:
    """Two holes found by tracing the reason to the persisted record.

    Neither was covered by the first version of these tests, and both
    would have made M6 unreachable or actively misleading in production.
    """

    def test_the_time_budget_bypass_cannot_clear_an_evidence_refusal(self, unavailable_probe):
        # The bypass gate runs AFTER this resolver and force-sets
        # `feasible = True`. On a fresh chain the `-inf` bootstrap makes it
        # fire unconditionally, so without the guard the refusal would be
        # erased on the very first formal round of every new campaign —
        # M6 would never be reached. The mandate is explicit that the
        # bypass may loosen the TIME decision and nothing else.
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _should_bypass_formal_time_budget,
            is_evidence_refusal,
        )

        # the bootstrap case: no incumbent -> the bypass always fires
        assert _should_bypass_formal_time_budget(
            {"denoising_score": -999.0}, threshold=float("-inf")
        ), "precondition: the -inf bootstrap must make the bypass fire"

        tc = _time_check()
        _resolve(tc, is_trial=False, result_authority="scientific")
        assert tc["feasible"] is False
        assert is_evidence_refusal(tc) is True, (
            "an attempt refused for missing measurement evidence is not "
            "time-gated; the bypass must not clear it"
        )

    def test_a_time_gated_skip_is_still_bypassable(self):
        # The guard must be narrow: an ordinary time rejection keeps its
        # pre-M6 bypass behaviour.
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            is_evidence_refusal,
        )

        assert is_evidence_refusal({"feasible": False, "breakdown": {}}) is False
        assert is_evidence_refusal({"feasible": False}) is False

    def test_both_production_call_sites_use_the_shared_predicate(self):
        # Reachability. The first version of this test re-implemented the
        # condition inline and passed while the production guard was
        # deleted. Parsed as call nodes, not grepped as a substring.
        import ast
        import importlib
        import inspect
        import pathlib

        mod = importlib.import_module(
            "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
        )
        tree = ast.parse(pathlib.Path(inspect.getfile(mod)).read_text())
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "is_evidence_refusal"
        ]
        assert len(calls) == 2, (
            f"expected the bypass guard and the record builder to call "
            f"is_evidence_refusal, found {len(calls)} call sites"
        )

    def test_the_record_does_not_blame_wall_time(self, unavailable_probe):
        # `skipped_time_risk` now carries two causes. A wall-time
        # conclusion on an evidence refusal tells the interpreter and the
        # proposer that the CANDIDATE was too slow — the contamination
        # failure V19 suffered, where an infrastructure condition was read
        # as evidence about the model.
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _build_skip_record,
        )

        tc = _time_check()
        _resolve(tc, is_trial=False, result_authority="scientific")
        evidence_refusal = (tc.get("breakdown") or {}).get("probe_resolution_enforced", False)
        assert evidence_refusal is True

        conclusion = (
            "Not admitted: a formal scientific decision requires a bounded probe "
            "and none could be resolved. This is an infrastructure condition and "
            "says nothing about the candidate's size, speed or design."
            if evidence_refusal
            else "Skipped: estimated wall-time exceeds budget."
        )
        record = _build_skip_record(
            status="skipped_time_risk",
            exp_id="exp_001",
            model_type="punet",
            file_index=0,
            record_params={},
            expert_advice_str="",
            hypothesis="",
            round_index=1,
            attempt_in_round=1,
            conclusion=conclusion,
            discovery=tc.get("verdict", ""),
            memory_update=tc.get("suggestion", ""),
            memory_extra=None,
        )
        memory = record["memory"]
        assert "wall-time" not in memory["conclusion"]
        assert "says nothing about the candidate" in memory["conclusion"]
        # The remedy must point at the environment, never at the model.
        # "Reduce model size / batch_size / segmentation_size" — the
        # time-gated advice — would be actively wrong here.
        assert "Restore the measurement capability" in memory["memory_update"]
        assert "Reduce model size" not in memory["memory_update"]


class TestTheGateOnlyFiresOnARealRequest:
    def test_a_non_request_preflight_is_untouched(self, unavailable_probe):
        tc = {"feasible": True, "breakdown": {"runtime_decision": "ALLOW"}}
        assert _resolve(tc, is_trial=False, result_authority="scientific") == "proceed"
        assert tc["feasible"] is True
        assert "probe_resolution" not in tc["breakdown"]
