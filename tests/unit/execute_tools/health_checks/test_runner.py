"""Runner semantics — severity, action resolution, gate discovery, evaluation.

Covers the four rev-6 runner functions from design §8:
    * severity_of(action)
    * resolve_action(gate_results)
    * get_gates_for_position(round_index)
    * evaluate_gate(gate_id, ctx)

Test infrastructure:
    * ``_ScriptedCheck`` — a fake HealthCheckSkill whose verdict is scripted
      per test. Satisfies the rev-6 Protocol (no is_applicable, run returns
      HealthCheckResult, accepts config=None).
    * ``monkeypatch`` on ``runner.load_health_gates_config`` — injects a
      built HealthChecksConfig without touching disk or the process cache.
    * ``clean_registry`` fixture from conftest.py — isolates check
      registrations per test.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from execute_tools.health_checks import runner
from execute_tools.health_checks.config import (
    ActionConfig,
    CheckRef,
    GateConfig,
    HealthChecksConfig,
)
from execute_tools.health_checks.registry import register
from execute_tools.health_checks.runner import (
    evaluate_gate,
    get_gates_for_position,
    resolve_action,
    severity_of,
)
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    CheckVerdict,
    FactRequirement,
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
    TaskHealthFacts,
)

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


class _ScriptedCheck:
    """A fake check that satisfies the rev-6 Protocol.

    ``name`` is set per-instance in ``__init__`` (overrides the ClassVar so
    each test can register multiple distinct-name instances).
    ``run`` records call count and the config it was passed, then returns a
    HealthCheckResult built from the constructor's scripted verdict.
    """

    name: ClassVar[str] = "scripted"  # overwritten per instance

    def __init__(
        self,
        name: str,
        *,
        passed: bool = True,
        reason: str = "",
        metrics: dict[str, float | int | str] | None = None,
    ):
        self.name = name
        self._passed = passed
        self._reason = reason
        self._metrics = metrics or {}
        self.run_calls = 0
        self.last_config: dict[str, Any] | None = None

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        self.run_calls += 1
        self.last_config = config
        return HealthCheckResult(
            check_name=self.name,
            passed=self._passed,
            reason=self._reason,
            metrics=self._metrics,
        )


def _make_gate(
    gate_id: str,
    after_round: int,
    check_refs: list[CheckRef],
    *,
    short_circuit: bool = True,
    on_pass_action: GateAction = GateAction.CONTINUE,
    on_fail_action: GateAction = GateAction.INVALIDATE_ROUND,
) -> GateConfig:
    return GateConfig(
        id=gate_id,
        after_round=after_round,
        short_circuit=short_circuit,
        checks=check_refs,
        on_pass=ActionConfig(action=on_pass_action),
        on_fail=ActionConfig(action=on_fail_action),
    )


def _make_config(*gates: GateConfig) -> HealthChecksConfig:
    return HealthChecksConfig(health_gates=list(gates))


def _ctx(round_index: int = 1) -> HealthCheckContext:
    """Minimal valid HealthCheckContext. The runner only reads
    ``round_index``; other fields are passthrough to skills."""
    return HealthCheckContext(model_name="m", run_name="r", round_index=round_index)


def _gr(action: GateAction) -> GateResult:
    """Minimal GateResult carrying only the fields ``resolve_action`` reads."""
    return GateResult(gate_id="g", round_index=1, passed=True, action=action)


# ---------------------------------------------------------------------------
# severity_of
# ---------------------------------------------------------------------------


class TestSeverityOf:
    def test_all_actions_have_distinct_severity(self):
        seen = {severity_of(a) for a in GateAction}
        assert len(seen) == len(list(GateAction))

    def test_ordering_matches_spec(self):
        """INVALIDATE_ROUND > CONTINUE (design §8; the two skip actions
        were retired from the vocabulary — F-SCANC-1)."""
        assert severity_of(GateAction.INVALIDATE_ROUND) > severity_of(GateAction.CONTINUE)

    def test_invalidate_round_is_highest(self):
        assert all(severity_of(GateAction.INVALIDATE_ROUND) >= severity_of(a) for a in GateAction)

    def test_continue_is_lowest(self):
        assert all(severity_of(GateAction.CONTINUE) <= severity_of(a) for a in GateAction)


# ---------------------------------------------------------------------------
# resolve_action
# ---------------------------------------------------------------------------


class TestResolveAction:
    def test_empty_iterable_returns_continue(self):
        assert resolve_action([]) is GateAction.CONTINUE

    def test_single_result_returns_that_action(self):
        assert resolve_action([_gr(GateAction.INVALIDATE_ROUND)]) is GateAction.INVALIDATE_ROUND

    def test_multiple_mixed_picks_most_severe(self):
        actions = [
            _gr(GateAction.CONTINUE),
            _gr(GateAction.INVALIDATE_ROUND),
            _gr(GateAction.CONTINUE),
        ]
        assert resolve_action(actions) is GateAction.INVALIDATE_ROUND

    def test_all_continue_returns_continue(self):
        actions = [_gr(GateAction.CONTINUE) for _ in range(3)]
        assert resolve_action(actions) is GateAction.CONTINUE

    def test_generator_input_works(self):
        """resolve_action's signature is Iterable[GateResult] — must accept a
        generator, not require a list."""

        def gen():
            yield _gr(GateAction.CONTINUE)
            yield _gr(GateAction.INVALIDATE_ROUND)
            yield _gr(GateAction.CONTINUE)

        assert resolve_action(gen()) is GateAction.INVALIDATE_ROUND


# ---------------------------------------------------------------------------
# get_gates_for_position
# ---------------------------------------------------------------------------


class TestGetGatesForPosition:
    def test_returns_ids_for_configured_round(self, monkeypatch):
        cfg = _make_config(
            _make_gate("gate_a", after_round=1, check_refs=[CheckRef(name="dummy")]),
            _make_gate("gate_b", after_round=5, check_refs=[CheckRef(name="dummy")]),
        )
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: cfg)
        assert get_gates_for_position(1) == ["gate_a"]

    def test_unconfigured_round_returns_empty(self, monkeypatch):
        cfg = _make_config(
            _make_gate("gate_a", after_round=1, check_refs=[CheckRef(name="dummy")]),
        )
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: cfg)
        assert get_gates_for_position(2) == []

    def test_multiple_gates_at_same_round_returns_all(self, monkeypatch):
        cfg = _make_config(
            _make_gate("gate_a", after_round=3, check_refs=[CheckRef(name="dummy")]),
            _make_gate("gate_b", after_round=3, check_refs=[CheckRef(name="dummy")]),
            _make_gate("gate_c", after_round=5, check_refs=[CheckRef(name="dummy")]),
        )
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: cfg)
        assert get_gates_for_position(3) == ["gate_a", "gate_b"]

    def test_shipped_config_all_rounds(self):
        """The shipped configs/health_checks.yaml (M8 rev-7) fires all
        6 gates on every round via ``after_round: every``."""
        expected = [
            "output_diversity_blocking",
            "output_std_blocking",
            "amplitude_collapse_blocking",
            "pearson_dispersion_recording",
            "spectral_peak_ratio_recording",
            "per_file_output_std_recording",
        ]
        for r in [1, 2, 3, 4, 5, 7, 10]:
            assert get_gates_for_position(r) == expected, (
                f"round {r} did not return all 6 every-round gates"
            )


# ---------------------------------------------------------------------------
# evaluate_gate
# ---------------------------------------------------------------------------


class TestEvaluateGate:
    def _install(self, monkeypatch, config: HealthChecksConfig) -> None:
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: config)

    def test_all_pass_returns_on_pass_action(self, monkeypatch, clean_registry):
        a = _ScriptedCheck("a", passed=True)
        b = _ScriptedCheck("b", passed=True)
        register(a)
        register(b)
        self._install(
            monkeypatch,
            _make_config(
                _make_gate(
                    "g",
                    after_round=1,
                    check_refs=[CheckRef(name="a"), CheckRef(name="b")],
                    on_pass_action=GateAction.CONTINUE,
                    on_fail_action=GateAction.INVALIDATE_ROUND,
                ),
            ),
        )
        gr = evaluate_gate("g", _ctx())
        assert gr.passed is True
        assert gr.action is GateAction.CONTINUE
        assert gr.failure_reason == ""
        assert [r.check_name for r in gr.check_results] == ["a", "b"]
        assert a.run_calls == 1
        assert b.run_calls == 1

    def test_first_fails_short_circuits(self, monkeypatch, clean_registry):
        a = _ScriptedCheck("a", passed=False, reason="a: fail")
        b = _ScriptedCheck("b", passed=True)
        register(a)
        register(b)
        self._install(
            monkeypatch,
            _make_config(
                _make_gate(
                    "g",
                    after_round=1,
                    check_refs=[CheckRef(name="a"), CheckRef(name="b")],
                    on_fail_action=GateAction.INVALIDATE_ROUND,
                    short_circuit=True,
                ),
            ),
        )
        gr = evaluate_gate("g", _ctx())
        assert gr.passed is False
        assert gr.action is GateAction.INVALIDATE_ROUND
        assert gr.failure_reason == "a: fail"
        assert a.run_calls == 1
        assert b.run_calls == 0  # short-circuited

    def test_short_circuit_false_runs_all_checks(self, monkeypatch, clean_registry):
        """D4: short_circuit=False must run every check even after failure."""
        a = _ScriptedCheck("a", passed=False, reason="a: fail")
        b = _ScriptedCheck("b", passed=True)
        c = _ScriptedCheck("c", passed=False, reason="c: also fail")
        register(a)
        register(b)
        register(c)
        self._install(
            monkeypatch,
            _make_config(
                _make_gate(
                    "g",
                    after_round=1,
                    check_refs=[
                        CheckRef(name="a"),
                        CheckRef(name="b"),
                        CheckRef(name="c"),
                    ],
                    on_fail_action=GateAction.INVALIDATE_ROUND,
                    short_circuit=False,
                ),
            ),
        )
        gr = evaluate_gate("g", _ctx())
        assert gr.passed is False
        assert gr.action is GateAction.INVALIDATE_ROUND
        assert a.run_calls == 1
        assert b.run_calls == 1
        assert c.run_calls == 1
        assert [r.check_name for r in gr.check_results] == ["a", "b", "c"]

    def test_first_failure_reason_is_config_order(self, monkeypatch, clean_registry):
        """When short_circuit=False, failure_reason = FIRST failing check's
        reason (in gate-config order), not last."""
        a = _ScriptedCheck("a", passed=True)
        b = _ScriptedCheck("b", passed=False, reason="b: first failure")
        c = _ScriptedCheck("c", passed=False, reason="c: later failure")
        register(a)
        register(b)
        register(c)
        self._install(
            monkeypatch,
            _make_config(
                _make_gate(
                    "g",
                    after_round=1,
                    check_refs=[
                        CheckRef(name="a"),
                        CheckRef(name="b"),
                        CheckRef(name="c"),
                    ],
                    short_circuit=False,
                    on_fail_action=GateAction.INVALIDATE_ROUND,
                ),
            ),
        )
        gr = evaluate_gate("g", _ctx())
        assert gr.failure_reason == "b: first failure"

    def test_empty_check_config_passed_as_none(self, monkeypatch, clean_registry):
        """D8-B: CheckRef.config == {} should reach the skill as None (design §6
        semantic: None means 'use defaults')."""
        a = _ScriptedCheck("a", passed=True)
        register(a)
        self._install(
            monkeypatch,
            _make_config(
                _make_gate(
                    "g",
                    after_round=1,
                    check_refs=[CheckRef(name="a")],  # default config={}
                ),
            ),
        )
        evaluate_gate("g", _ctx())
        assert a.last_config is None

    def test_nonempty_check_config_passed_verbatim(self, monkeypatch, clean_registry):
        """When operator sets an override, the skill gets the dict as-is."""
        a = _ScriptedCheck("a", passed=True)
        register(a)
        override = {"min_unique_int8_values": 42, "peek_samples": 1000}
        self._install(
            monkeypatch,
            _make_config(
                _make_gate(
                    "g",
                    after_round=1,
                    check_refs=[CheckRef(name="a", config=override)],
                ),
            ),
        )
        evaluate_gate("g", _ctx())
        assert a.last_config == override

    def test_round_index_propagated_from_ctx(self, monkeypatch, clean_registry):
        a = _ScriptedCheck("a", passed=True)
        register(a)
        self._install(
            monkeypatch,
            _make_config(
                _make_gate("g", after_round=3, check_refs=[CheckRef(name="a")]),
            ),
        )
        gr = evaluate_gate("g", _ctx(round_index=7))
        assert gr.round_index == 7

    def test_unknown_gate_id_raises_value_error_with_available(self, monkeypatch, clean_registry):
        self._install(
            monkeypatch,
            _make_config(
                _make_gate("g1", after_round=1, check_refs=[CheckRef(name="dummy")]),
                _make_gate("g2", after_round=3, check_refs=[CheckRef(name="dummy")]),
            ),
        )
        with pytest.raises(ValueError) as exc_info:
            evaluate_gate("nonexistent", _ctx())
        msg = str(exc_info.value)
        assert "nonexistent" in msg
        assert "g1" in msg
        assert "g2" in msg

    def test_observer_gate_on_pass_equals_on_fail_allowed(self, monkeypatch, clean_registry):
        """C.1: an observer gate has on_pass == on_fail == CONTINUE. On
        failure we still report passed=False but the routing action is
        CONTINUE (log-only, no routing consequence)."""
        a = _ScriptedCheck("a", passed=False, reason="a: log-only")
        register(a)
        self._install(
            monkeypatch,
            _make_config(
                _make_gate(
                    "g",
                    after_round=1,
                    check_refs=[CheckRef(name="a")],
                    on_pass_action=GateAction.CONTINUE,
                    on_fail_action=GateAction.CONTINUE,
                ),
            ),
        )
        gr = evaluate_gate("g", _ctx())
        assert gr.passed is False
        assert gr.action is GateAction.CONTINUE
        assert gr.failure_reason == "a: log-only"

    def test_check_raising_unexpected_exception_treated_as_failure(
        self, monkeypatch, clean_registry, capsys
    ):
        """Bug B fix (PR #101 Gate 2 forensic, 2026-07-15).

        A HealthCheckSkill whose ``run`` raises an unhandled exception
        must not propagate the exception out of ``evaluate_gate`` and
        crash the tuner. The runner catches it, records
        ``passed=False`` with a ``failure_reason`` that names the check
        and the exception type, and applies the gate's configured
        ``on_fail.action`` (policy stays in YAML, not runtime).
        """

        class _RaisingCheck:
            name = "crashy"

            def run(self, ctx, config=None):
                raise ValueError("test crash")

        register(_RaisingCheck())
        self._install(
            monkeypatch,
            _make_config(
                _make_gate(
                    "g",
                    after_round=1,
                    check_refs=[CheckRef(name="crashy")],
                    on_pass_action=GateAction.CONTINUE,
                    on_fail_action=GateAction.INVALIDATE_ROUND,
                ),
            ),
        )

        # Must not raise — this is the core Bug B guarantee.
        gr = evaluate_gate("g", _ctx())

        # Gate result reflects check failure, and gate's configured
        # on_fail.action is applied.
        assert gr.passed is False
        assert gr.action is GateAction.INVALIDATE_ROUND

        # failure_reason names the check and the exception type/message.
        assert "crashy" in gr.failure_reason
        assert "ValueError" in gr.failure_reason
        assert "test crash" in gr.failure_reason

        # Recorded per-check result carries the same signal.
        assert len(gr.check_results) == 1
        cr = gr.check_results[0]
        assert cr.check_name == "crashy"
        assert cr.passed is False
        assert cr.metrics.get("exception_type") == "ValueError"

        # Runner logs the exception to stdout for the operator.
        captured = capsys.readouterr()
        assert "crashy" in captured.out
        assert "ValueError" in captured.out


# ---------------------------------------------------------------------------
# Step 08a C3 — applicability is decided BEFORE the skill is invoked
# ---------------------------------------------------------------------------


class _DeclaringCheck(_ScriptedCheck):
    """A scripted check that also carries a ``CheckInputDeclaration``.

    Hand-built rather than borrowed from a real check: C3 wires the ENGINE,
    and the six shipped checks deliberately still carry no declaration until
    C4. Using a real check here would test C4's content a commit early and
    would stop this test from failing if the wiring regressed.
    """

    def __init__(self, name: str, declaration: CheckInputDeclaration, **kwargs: Any):
        super().__init__(name, **kwargs)
        self.declaration = declaration


# Requires an encoding family no contrast task declares.
_INT8_ONLY = CheckInputDeclaration(
    consumes_view="tidmad.int8_prefix_peek",
    required_facts=(FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),),
)
# Requires only a context input, so it applies under any facts.
_ANY_TASK = CheckInputDeclaration(
    consumes_view="anything",
    required_context_inputs=(),
)

_CONTRAST_FACTS = TaskHealthFacts(encoding_family="continuous_float", file_group_size=4)
_TIDMAD_FACTS = TaskHealthFacts(encoding_family="int8_symbol_stream", symbol_cardinality=256)


@pytest.fixture
def contrast_task(monkeypatch):
    """Bind facts that make the int8 family inapplicable, and count resolutions."""
    calls = {"n": 0}

    def _facts() -> TaskHealthFacts:
        calls["n"] += 1
        return _CONTRAST_FACTS

    monkeypatch.setattr(runner, "_resolve_task_facts", _facts)
    return calls


@pytest.fixture
def no_file_may_be_opened(monkeypatch):
    """Fail loudly if anything opens an HDF5 file during the gate evaluation.

    This is the 8.4-B claim in its executable form: inapplicability must be
    decided BEFORE artifact I/O, not by opening the file and giving up. A
    test that only asserted ``run_calls == 0`` would still pass if the
    engine peeked first and skipped afterwards.
    """
    import h5py

    def _boom(*args: Any, **kwargs: Any):
        raise AssertionError(f"h5py.File opened during an inapplicable check: {args!r}")

    monkeypatch.setattr(h5py, "File", _boom)


class TestApplicabilityWiring:
    def test_inapplicable_check_is_not_invoked_and_opens_no_file(
        self, clean_registry, monkeypatch, contrast_task, no_file_may_be_opened
    ):
        """8.4-B: declared-float task ⇒ the int8 check does not run at all."""
        check = _DeclaringCheck("int8_only", _INT8_ONLY, passed=False, reason="should never run")
        register(check)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: _make_config(_make_gate("g", 1, [CheckRef(name="int8_only")])),
        )

        gr = evaluate_gate("g", _ctx())

        assert check.run_calls == 0
        assert len(gr.check_results) == 1
        result = gr.check_results[0]
        assert result.verdict is CheckVerdict.INAPPLICABLE
        assert result.passed is True
        assert result.reason == (
            "int8_only: not applicable — encoding_family is 'continuous_float', "
            "check requires 'int8_symbol_stream'"
        )
        assert result.metrics["inapplicable_axis"] == "encoding_family"

    def test_sibling_applicable_check_still_executes_in_config_order(
        self, clean_registry, monkeypatch, contrast_task
    ):
        """The engine skips ONE check, not the gate.

        Asserts the executed SEQUENCE, not the configuration: an
        implementation that dropped the applicable check, or reordered the
        results, fails here.
        """
        skipped = _DeclaringCheck("int8_only", _INT8_ONLY)
        ran = _DeclaringCheck("universal", _ANY_TASK)
        register(skipped)
        register(ran)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: _make_config(
                _make_gate("g", 1, [CheckRef(name="int8_only"), CheckRef(name="universal")])
            ),
        )

        gr = evaluate_gate("g", _ctx())

        assert skipped.run_calls == 0
        assert ran.run_calls == 1
        assert [r.check_name for r in gr.check_results] == ["int8_only", "universal"]
        assert [r.verdict for r in gr.check_results] == [
            CheckVerdict.INAPPLICABLE,
            CheckVerdict.PASSED,
        ]

    def test_declaration_less_check_is_unconditionally_applicable(
        self, clean_registry, monkeypatch, contrast_task
    ):
        """Pre-08a behaviour bit-for-bit — this is why C3 is a TIDMAD no-op.

        The six shipped checks carry no declaration until C4, so the whole
        wiring must be inert for them even under facts that would make a
        declaring check inapplicable.
        """
        plain = _ScriptedCheck("plain", passed=False, reason="plain: flagged")
        register(plain)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: _make_config(_make_gate("g", 1, [CheckRef(name="plain")])),
        )

        gr = evaluate_gate("g", _ctx())

        assert plain.run_calls == 1
        assert gr.passed is False
        assert gr.action is GateAction.INVALIDATE_ROUND
        assert gr.check_results[0].verdict is CheckVerdict.FAILED
        # Facts are never resolved when no check declares any.
        assert contrast_task["n"] == 0

    def test_task_facts_are_resolved_once_per_gate(
        self, clean_registry, monkeypatch, contrast_task
    ):
        """Two declaring checks must not each re-resolve the profile."""
        register(_DeclaringCheck("a", _INT8_ONLY))
        register(_DeclaringCheck("b", _INT8_ONLY))
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: _make_config(
                _make_gate("g", 1, [CheckRef(name="a"), CheckRef(name="b")])
            ),
        )

        evaluate_gate("g", _ctx())

        assert contrast_task["n"] == 1

    def test_all_inapplicable_gate_takes_on_pass_and_never_blocks(
        self, clean_registry, monkeypatch, contrast_task
    ):
        """Q-08a-2. 'Takes on_pass' is not 'counts as pass' — see the verdicts."""
        register(_DeclaringCheck("int8_only", _INT8_ONLY))
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: _make_config(
                _make_gate(
                    "g",
                    1,
                    [CheckRef(name="int8_only")],
                    on_pass_action=GateAction.CONTINUE,
                    on_fail_action=GateAction.INVALIDATE_ROUND,
                )
            ),
        )

        gr = evaluate_gate("g", _ctx())

        assert gr.passed is True
        assert gr.action is GateAction.CONTINUE
        assert gr.failure_reason == ""
        assert all(r.verdict is CheckVerdict.INAPPLICABLE for r in gr.check_results)

    def test_inapplicable_is_never_chosen_as_the_failure_reason(
        self, clean_registry, monkeypatch, contrast_task
    ):
        """Mixed gate: the FAILED check owns the reason, the skipped one does not."""
        register(_DeclaringCheck("int8_only", _INT8_ONLY))
        register(_ScriptedCheck("flagger", passed=False, reason="flagger: collapsed"))
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: _make_config(
                _make_gate("g", 1, [CheckRef(name="int8_only"), CheckRef(name="flagger")])
            ),
        )

        gr = evaluate_gate("g", _ctx())

        assert gr.passed is False
        assert gr.failure_reason == "flagger: collapsed"
        assert gr.action is GateAction.INVALIDATE_ROUND

    def test_inapplicable_does_not_trigger_short_circuit(
        self, clean_registry, monkeypatch, contrast_task
    ):
        """short_circuit stops on FAILURE. An inapplicable check is not one."""
        register(_DeclaringCheck("int8_only", _INT8_ONLY))
        later = _ScriptedCheck("later", passed=True)
        register(later)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: _make_config(
                _make_gate(
                    "g",
                    1,
                    [CheckRef(name="int8_only"), CheckRef(name="later")],
                    short_circuit=True,
                )
            ),
        )

        gr = evaluate_gate("g", _ctx())

        assert later.run_calls == 1
        assert len(gr.check_results) == 2

    def test_applicable_declaring_check_runs_normally(self, clean_registry, monkeypatch):
        """The other direction of the axis: matching facts ⇒ the check runs.

        Without this, a wiring bug that made EVERY declaring check
        inapplicable would pass every test above.
        """
        monkeypatch.setattr(runner, "_resolve_task_facts", lambda: _TIDMAD_FACTS)
        check = _DeclaringCheck("int8_only", _INT8_ONLY, passed=True)
        register(check)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: _make_config(_make_gate("g", 1, [CheckRef(name="int8_only")])),
        )

        gr = evaluate_gate("g", _ctx())

        assert check.run_calls == 1
        assert gr.check_results[0].verdict is CheckVerdict.PASSED


class TestApplicabilityIsReachableFromTheProductionEntryPoint:
    """Reachability: the boundary must sit on the path production actually takes.

    Every test above calls ``evaluate_gate`` directly. This one enters
    through ``evaluate_and_persist_health_gates`` — the function the tuner
    calls — so a refactor that bypassed the applicability step on the real
    path (a second gate loop, an inlined runner) fails here even while the
    direct-call tests stay green.
    """

    def test_production_entry_point_honours_applicability_and_persists_verdicts(
        self, clean_registry, monkeypatch, contrast_task, no_file_may_be_opened
    ):
        from execute_tools.health_checks import evaluation

        check = _DeclaringCheck("int8_only", _INT8_ONLY, passed=False, reason="never runs")
        register(check)
        config = _make_config(_make_gate("g", 1, [CheckRef(name="int8_only")]))
        monkeypatch.setattr(runner, "load_health_gates_config", lambda *a, **k: config)
        monkeypatch.setattr(evaluation, "load_health_gates_config", lambda *a, **k: config)

        _, persisted, action = evaluation.evaluate_and_persist_health_gates(_ctx())

        assert check.run_calls == 0
        assert action is GateAction.CONTINUE
        assert len(persisted) == 1
        assert persisted[0].check_verdicts == {"int8_only": "inapplicable"}
        assert persisted[0].execution_status == "not_run"
