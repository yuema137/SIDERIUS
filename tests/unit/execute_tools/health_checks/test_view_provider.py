"""Step 08b C3 — view providers, Phase-B binding resolution, view transport.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08b_extension_architecture.md`` §3.1,
§3.2, §3.3, §3.4, §4.3.

Defect classes owned here:

* **A configuration error becoming a Health verdict.** This is the single
  most consequential distinction in 08b. An unresolved binding means "this
  is not the run you configured"; ``INAPPLICABLE`` means "this validly-bound
  question does not arise here". Collapse them and every misconfiguration
  turns into a quietly healthier-looking result — the tests below assert the
  verdict vocabulary is not merely different but **not involved at all**.
* **Provider I/O happening for a check that does not apply.** 08a's whole
  guarantee is that inapplicability is decided before anything is opened.
  A provider materializing eagerly would undo it through the very mechanism
  meant to extend it.
* **A pre-08b check silently acquiring a new call shape.** Backward
  compatibility here is a DISPATCH rule, not a parameter default, so it is
  asserted with a spy on the INVOCATION — a check whose results are
  unchanged can still have been called differently.
* **Non-deterministic capability resolution.** Two providers advertising one
  key must be refused, not decided by binding order.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from execute_tools.health_checks import _plugin_binding, runner
from execute_tools.health_checks._plugin_binding import (
    HealthBindingError,
    bound_view_capabilities,
    materialize_view,
    resolve_task_health_bindings,
)
from execute_tools.health_checks._task_health_config import TaskHealthConfig
from execute_tools.health_checks._view_provider import (
    HealthView,
    HealthViewMaterializationError,
    HealthViewProvider,
)
from execute_tools.health_checks.config import (
    ActionConfig,
    CheckRef,
    GateConfig,
    HealthChecksConfig,
)
from execute_tools.health_checks.registry import register, register_view_provider
from execute_tools.health_checks.runner import evaluate_gate
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    CheckVerdict,
    FactRequirement,
    GateAction,
    HealthCheckContext,
    HealthCheckResult,
    TaskHealthFacts,
)

CAPABILITY = "vendor.sample_window"


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _plugin_binding.reset_run_scope()


class _SpyProvider:
    """A provider that records every materialization it was asked for."""

    provider_id: ClassVar[str] = "vendor.provider"
    capabilities: ClassVar[frozenset[str]] = frozenset({CAPABILITY})

    def __init__(self, *, payload: Any = None, raises: bool = False):
        self._payload = payload if payload is not None else {"samples": [1, 2, 3]}
        self._raises = raises
        self.calls: list[str] = []

    def materialize(
        self,
        capability_key: str,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthView:
        self.calls.append(capability_key)
        if self._raises:
            raise OSError("the artifact is unreadable")
        return HealthView(
            capability_key=capability_key,
            provider_id=self.provider_id,
            payload=self._payload,
        )


class _ViewConsumingCheck:
    """An external check that can only work from a provided view."""

    name: ClassVar[str] = "vendor.view_consumer"
    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        consumes_view=CAPABILITY,
        requires_view=True,
    )

    def __init__(self):
        self.received_views: list[HealthView | None] = []

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
        *,
        view: HealthView | None = None,
    ) -> HealthCheckResult:
        self.received_views.append(view)
        payload = view.payload if view is not None else None
        return HealthCheckResult(
            check_name=self.name,
            passed=bool(payload),
            reason=f"saw {payload!r}",
        )


class _LegacyCheck:
    """A pre-08b-shaped check: no ``view`` parameter at all.

    Its signature is the point. If the runner ever passed ``view=`` to a
    check that does not require one, this raises ``TypeError`` — which is a
    far more honest failure than a check quietly accepting and ignoring an
    argument it was never designed for.
    """

    name: ClassVar[str] = "legacy_shaped"

    def __init__(self):
        self.calls: list[tuple[tuple, dict]] = []

    def run(self, ctx, config=None):
        self.calls.append(((ctx,), {"config": config}))
        return HealthCheckResult(check_name=self.name, passed=True, reason="ok")


class _DeclaringLegacyCheck(_LegacyCheck):
    """Declares a capability but does NOT require a view — 08a's shape.

    All seven built-ins are this shape: they name what they conceptually
    read and then read their own artifacts.
    """

    name: ClassVar[str] = "declaring_but_self_reading"
    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        consumes_view="tidmad.int8_prefix_peek",
    )


def _gate(*check_names: str, short_circuit: bool = True) -> HealthChecksConfig:
    return HealthChecksConfig(
        health_gates=[
            GateConfig(
                id="g",
                after_round="every",
                short_circuit=short_circuit,
                checks=[CheckRef(name=n) for n in check_names],
                on_pass=ActionConfig(action=GateAction.CONTINUE),
                on_fail=ActionConfig(action=GateAction.INVALIDATE_ROUND),
            )
        ]
    )


def _ctx() -> HealthCheckContext:
    return HealthCheckContext(model_name="m", run_name="r", round_index=1)


def _config(**kwargs) -> TaskHealthConfig:
    return TaskHealthConfig.model_validate(kwargs)


class TestTheProviderToCheckPathWorksEndToEnd:
    """The seam's payoff: external provider → opaque payload → external check."""

    def test_a_view_consuming_check_receives_the_keyword_only_view(
        self, monkeypatch, clean_registry
    ):
        provider = _SpyProvider(payload={"window": [4, 5, 6]})
        check = _ViewConsumingCheck()
        register_view_provider(provider)
        register(check)
        resolve_task_health_bindings(
            _config(
                providers=[{"provider_id": provider.provider_id}],
                roster=[{"gate_id": "g", "check": check.name, "disposition": "recording"}],
            )
        )
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: _gate(check.name))

        result = evaluate_gate("g", _ctx())

        assert provider.calls == [CAPABILITY]
        assert len(check.received_views) == 1
        received = check.received_views[0]
        assert received is not None
        assert received.payload == {"window": [4, 5, 6]}
        assert received.provider_id == "vendor.provider"
        assert received.capability_key == CAPABILITY
        assert result.check_results[0].passed is True

    def test_provider_config_reaches_the_provider_untouched(self, clean_registry):
        """Provider-owned config is passed through, never interpreted."""
        seen: dict[str, Any] = {}

        class _ConfigRecordingProvider:
            provider_id: ClassVar[str] = "vendor.cfg"
            capabilities: ClassVar[frozenset[str]] = frozenset({CAPABILITY})

            def materialize(self, capability_key, ctx, config=None):
                seen.update({"config": config})
                return HealthView(
                    capability_key=capability_key, provider_id=self.provider_id, payload=1
                )

        register_view_provider(_ConfigRecordingProvider())
        resolve_task_health_bindings(
            _config(
                providers=[{"provider_id": "vendor.cfg", "config": {"anything": {"nested": True}}}]
            )
        )

        materialize_view(CheckInputDeclaration(consumes_view=CAPABILITY), _ctx())

        assert seen["config"] == {"anything": {"nested": True}}

    def test_a_provider_satisfies_the_runtime_protocol(self):
        """``runtime_checkable`` cannot see signatures, so this is shape only."""
        assert isinstance(_SpyProvider(), HealthViewProvider)


class TestUnresolvedBindingIsAnErrorNotAVerdict:
    """§3.2 — the distinction 08b exists to protect.

    Each test asserts not merely that the outcome differs from
    ``INAPPLICABLE``, but that the verdict vocabulary is **not involved** —
    the failure arrives as a startup exception, before any gate runs.
    """

    def test_a_check_requiring_an_unadvertised_capability_fails_at_startup(self, clean_registry):
        register(_ViewConsumingCheck())

        with pytest.raises(HealthBindingError) as excinfo:
            resolve_task_health_bindings(
                _config(
                    roster=[
                        {
                            "gate_id": "g",
                            "check": "vendor.view_consumer",
                            "disposition": "blocking",
                        }
                    ]
                )
            )

        assert CAPABILITY in str(excinfo.value)
        # The verdict vocabulary is not involved: this arrived as a startup
        # EXCEPTION, so no HealthCheckResult and no CheckVerdict was ever
        # produced. Contrast with the INAPPLICABLE test below, which runs the
        # same machinery correctly bound and does yield a typed verdict.
        assert not isinstance(excinfo.value, HealthCheckResult)
        # Fail-closed leaves no partial state behind.
        assert bound_view_capabilities() == ()

    def test_an_unregistered_roster_check_fails_at_startup(self, clean_registry):
        with pytest.raises(HealthBindingError) as excinfo:
            resolve_task_health_bindings(
                _config(
                    roster=[
                        {"gate_id": "g", "check": "never_registered", "disposition": "blocking"}
                    ]
                )
            )

        assert "never_registered" in str(excinfo.value)
        assert bound_view_capabilities() == ()

    def test_an_unregistered_provider_fails_at_startup(self, clean_registry):
        with pytest.raises(HealthBindingError) as excinfo:
            resolve_task_health_bindings(_config(providers=[{"provider_id": "vendor.absent"}]))

        assert "vendor.absent" in str(excinfo.value)

    def test_two_providers_advertising_one_capability_are_refused(self, clean_registry):
        """Resolution must be deterministic, not decided by binding order."""

        class _Rival(_SpyProvider):
            provider_id: ClassVar[str] = "vendor.rival"

        register_view_provider(_SpyProvider())
        register_view_provider(_Rival())

        with pytest.raises(HealthBindingError) as excinfo:
            resolve_task_health_bindings(
                _config(
                    providers=[
                        {"provider_id": "vendor.provider"},
                        {"provider_id": "vendor.rival"},
                    ]
                )
            )

        assert CAPABILITY in str(excinfo.value)

    def test_a_valid_binding_whose_facts_do_not_match_is_INAPPLICABLE(
        self, monkeypatch, clean_registry
    ):
        """The contrast case, and the reason the assertions above matter.

        Same machinery, correctly bound — and here the typed verdict IS the
        right answer, because the question genuinely does not arise.
        """

        class _FactDemandingCheck(_LegacyCheck):
            name: ClassVar[str] = "needs_float_family"
            declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
                consumes_view="vendor.whatever",
                required_facts=(
                    FactRequirement(axis="encoding_family", equals="continuous_float"),
                ),
            )

        register(_FactDemandingCheck())
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: _gate("needs_float_family"))
        monkeypatch.setattr(
            runner,
            "_resolve_task_facts",
            lambda: TaskHealthFacts(encoding_family="int8_symbol_stream"),
        )

        result = evaluate_gate("g", _ctx())

        assert result.check_results[0].verdict is CheckVerdict.INAPPLICABLE


class TestMaterializationHappensOnlyAfterApplicability:
    """§3.3/§3.4 — the ordering invariant, and 08a's guarantee preserved."""

    def test_an_inapplicable_check_causes_zero_materialize_calls(self, monkeypatch, clean_registry):
        provider = _SpyProvider()

        class _InapplicableViewCheck(_ViewConsumingCheck):
            name: ClassVar[str] = "vendor.inapplicable"
            declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
                consumes_view=CAPABILITY,
                requires_view=True,
                required_facts=(
                    FactRequirement(axis="encoding_family", equals="continuous_float"),
                ),
            )

        check = _InapplicableViewCheck()
        register_view_provider(provider)
        register(check)
        resolve_task_health_bindings(
            _config(
                providers=[{"provider_id": provider.provider_id}],
                roster=[{"gate_id": "g", "check": check.name, "disposition": "recording"}],
            )
        )
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: _gate(check.name))
        monkeypatch.setattr(
            runner,
            "_resolve_task_facts",
            lambda: TaskHealthFacts(encoding_family="int8_symbol_stream"),
        )

        result = evaluate_gate("g", _ctx())

        assert provider.calls == []
        assert check.received_views == []
        assert result.check_results[0].verdict is CheckVerdict.INAPPLICABLE

    def test_a_provider_that_raises_yields_ERROR_never_inapplicable(
        self, monkeypatch, clean_registry
    ):
        """A check that could not be given its inputs and one that could not
        compute are the same thing to a gate: a question left unanswered."""
        provider = _SpyProvider(raises=True)
        check = _ViewConsumingCheck()
        register_view_provider(provider)
        register(check)
        resolve_task_health_bindings(
            _config(
                providers=[{"provider_id": provider.provider_id}],
                roster=[{"gate_id": "g", "check": check.name, "disposition": "blocking"}],
            )
        )
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: _gate(check.name))

        result = evaluate_gate("g", _ctx())

        assert result.check_results[0].verdict is CheckVerdict.ERROR
        assert result.check_results[0].passed is False
        assert "view provider failed" in result.check_results[0].reason
        # The check itself was never invoked with a broken view.
        assert check.received_views == []
        # A blocking gate still fails closed, exactly as the Bug-B guard did.
        assert result.action is GateAction.INVALIDATE_ROUND

    def test_materialize_view_raises_a_named_error_rather_than_the_raw_exception(
        self, clean_registry
    ):
        register_view_provider(_SpyProvider(raises=True))
        resolve_task_health_bindings(_config(providers=[{"provider_id": "vendor.provider"}]))

        with pytest.raises(HealthViewMaterializationError) as excinfo:
            materialize_view(
                CheckInputDeclaration(consumes_view=CAPABILITY, requires_view=True), _ctx()
            )

        assert "vendor.provider" in str(excinfo.value)
        assert "OSError" in str(excinfo.value)


class TestNoViewMeansTheUnchangedCallPath:
    """The frozen dispatch rule (§3.3 amendment 1), asserted on the INVOCATION.

    A check whose results are unchanged can still have been called
    differently, so results are not the evidence — the call is.
    """

    def test_a_check_with_no_bound_provider_is_called_without_view(
        self, monkeypatch, clean_registry
    ):
        """``_LegacyCheck.run`` has no ``view`` parameter, so passing one
        would raise TypeError rather than being quietly absorbed."""
        check = _DeclaringLegacyCheck()
        register(check)
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: _gate(check.name))

        result = evaluate_gate("g", _ctx())

        assert len(check.calls) == 1
        _, kwargs = check.calls[0]
        assert "view" not in kwargs
        assert result.check_results[0].passed is True

    def test_a_declaration_less_check_is_called_without_view(self, monkeypatch, clean_registry):
        check = _LegacyCheck()
        register(check)
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: _gate(check.name))

        evaluate_gate("g", _ctx())

        assert len(check.calls) == 1
        assert "view" not in check.calls[0][1]

    def test_the_requires_view_partition_is_exactly_the_declared_one(self):
        """Which built-ins keep the legacy path, stated as a partition.

        The six TIDMAD checks name what they conceptually read and then
        read it themselves — ``requires_view=False``, the unchanged
        ``run(ctx, config)`` path. The Step-08c generic family consumes
        REAL views, so it requires a bound provider and fails closed at
        binding without one. Both sets are HARDCODED: a check drifting
        across this line is a real behavioural change that must not happen
        by accident (upgraded from 08b's all-seven form when 08c C2 grew
        the registry to nine).
        """
        from execute_tools.health_checks import registry

        view_requiring = {
            "sample_dispersion_floor",
            "categorical_distinct_symbols",
            "categorical_dominant_fraction",
        }
        for name in registry.all_registered():
            declaration = getattr(registry.get(name), "declaration", None)
            assert isinstance(declaration, CheckInputDeclaration), name
            assert declaration.consumes_view, name
            assert declaration.requires_view is (name in view_requiring), name

    def test_nothing_is_bound_by_default(self):
        """A run that binds no provider has no capabilities bound at all."""
        assert bound_view_capabilities() == ()


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
