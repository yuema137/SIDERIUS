# tests/unit/execute_tools/health_checks/test_generic_collapse_checks.py
"""Step 08c C2 — the generic categorical collapse checks + cardinality injection.

Owns, with hand-computed expectations hardcoded:

* the four §2.5 real-collapse anchor values — n=370, distinct=2,
  occupancy=2/37, dominant=369/370 — driving FAILED at the frozen Pets
  floors, and a healthy spread driving PASSED;
* the §3.2a verdict boundary for the categorical family: empty → ERROR,
  out-of-range symbol → FAILED through the ONE shared validity mechanism
  (mutation-proven load-bearing for BOTH checks), foreign payload → ERROR,
  provider raise → ERROR;
* §3.3 cardinality injection: declaration-driven, table-bounded, refusing
  authored collisions on EVERY injected key, and provably entering the
  arithmetic (occupancy) through a composed → evaluated chain;
* the ordering contract: a task declaring no cardinality makes the
  categorical checks INAPPLICABLE (axis named) with ZERO provider
  materializations.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pytest

from execute_tools.health_checks import _plugin_binding, runner
from execute_tools.health_checks import categorical_distinct_symbols as cds_module
from execute_tools.health_checks import categorical_dominant_fraction as cdf_module
from execute_tools.health_checks._categorical_validity import (
    SymbolValidity,
    validate_symbols,
)
from execute_tools.health_checks._composition import (
    INJECTABLE_AXIS_PARAMETERS,
    INJECTED_PARAMETER_KEYS,
    HealthCompositionError,
    compose_health_gates,
    injected_parameters_for,
    resolve_composed_gates,
)
from execute_tools.health_checks._plugin_binding import resolve_task_health_bindings
from execute_tools.health_checks._task_health_config import TaskHealthConfig
from execute_tools.health_checks._view_provider import HealthView
from execute_tools.health_checks.categorical_distinct_symbols import (
    CategoricalDistinctSymbolsCheck,
)
from execute_tools.health_checks.categorical_dominant_fraction import (
    CategoricalDominantFractionCheck,
)
from execute_tools.health_checks.config import GateConfig, HealthChecksConfig
from execute_tools.health_checks.registry import register, register_view_provider
from execute_tools.health_checks.runner import evaluate_gate
from execute_tools.health_checks.sample_dispersion_floor import SampleDispersionFloorCheck
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    HealthCheckContext,
)
from execute_tools.health_checks.standard_views import (
    CATEGORICAL_PREDICTIONS,
    CategoricalPredictionsPayload,
)

# The four §2.5 anchor values, hardcoded — the real preserved D14 Pets
# collapse: 370 predictions, 369 of class 5 plus one of class 12, using 2
# of 37 classes.
PETS_CARDINALITY = 37
PETS_N = 370
PETS_DISTINCT = 2
PETS_OCCUPANCY = 0.05405405405405406  # 2/37
PETS_DOMINANT_FRACTION = 0.9972972972972973  # 369/370
PETS_DOMINANT_SYMBOL = 5

COLLAPSED_SYMBOLS = np.array([5] * 369 + [12], dtype=np.int64)
HEALTHY_SYMBOLS = np.array([i % PETS_CARDINALITY for i in range(PETS_N)], dtype=np.int64)

# The frozen Pets thresholds (§3.4) as the anchor tests exercise them.
PETS_FLOOR = 5
PETS_CEILING = 0.95


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _plugin_binding.reset_run_scope()


def _ctx() -> HealthCheckContext:
    return HealthCheckContext(model_name="m", run_name="r", round_index=1)


def _view(symbols: np.ndarray) -> HealthView:
    return HealthView(
        capability_key=CATEGORICAL_PREDICTIONS,
        provider_id="test.categorical_views",
        payload=CategoricalPredictionsPayload(symbols=symbols),
    )


def _cfg(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"symbol_cardinality": PETS_CARDINALITY}
    base.update(extra)
    return base


class TestDistinctSymbolsArithmetic:
    def test_the_real_collapse_fails_the_frozen_floor(self):
        result = CategoricalDistinctSymbolsCheck().run(
            _ctx(), _cfg(min_distinct_symbols=PETS_FLOOR), view=_view(COLLAPSED_SYMBOLS)
        )
        assert result.verdict is CheckVerdict.FAILED
        assert result.passed is False
        assert result.metrics["n_samples"] == PETS_N
        assert result.metrics["distinct_symbols"] == PETS_DISTINCT
        assert result.metrics["symbol_cardinality"] == PETS_CARDINALITY
        assert result.metrics["occupancy"] == PETS_OCCUPANCY
        assert result.metrics["min_distinct_symbols"] == PETS_FLOOR

    def test_a_healthy_spread_passes(self):
        result = CategoricalDistinctSymbolsCheck().run(
            _ctx(), _cfg(min_distinct_symbols=PETS_FLOOR), view=_view(HEALTHY_SYMBOLS)
        )
        assert result.verdict is CheckVerdict.PASSED
        assert result.metrics["distinct_symbols"] == PETS_CARDINALITY
        assert result.metrics["occupancy"] == 1.0

    def test_the_floor_is_inclusive_and_load_bearing(self):
        five_distinct = np.array([0, 1, 2, 3, 4] * 10, dtype=np.int64)
        check = CategoricalDistinctSymbolsCheck()
        at = check.run(_ctx(), _cfg(min_distinct_symbols=5), view=_view(five_distinct))
        above = check.run(_ctx(), _cfg(min_distinct_symbols=6), view=_view(five_distinct))
        assert at.passed is True
        assert above.passed is False

    def test_int8_symbols_with_a_wide_alphabet_do_not_overflow(self):
        symbols = np.arange(0, 128, dtype=np.int8)
        result = CategoricalDistinctSymbolsCheck().run(
            _ctx(),
            {"symbol_cardinality": 128, "min_distinct_symbols": 5},
            view=_view(symbols),
        )
        assert result.verdict is CheckVerdict.PASSED
        assert result.metrics["distinct_symbols"] == 128
        assert result.metrics["occupancy"] == 1.0


class TestDominantFractionArithmetic:
    def test_the_real_collapse_fails_the_frozen_ceiling(self):
        result = CategoricalDominantFractionCheck().run(
            _ctx(), _cfg(max_dominant_fraction=PETS_CEILING), view=_view(COLLAPSED_SYMBOLS)
        )
        assert result.verdict is CheckVerdict.FAILED
        assert result.passed is False
        assert result.metrics["n_samples"] == PETS_N
        assert result.metrics["dominant_fraction"] == PETS_DOMINANT_FRACTION
        assert result.metrics["dominant_symbol"] == PETS_DOMINANT_SYMBOL
        assert result.metrics["max_dominant_fraction"] == PETS_CEILING

    def test_a_healthy_spread_passes(self):
        result = CategoricalDominantFractionCheck().run(
            _ctx(), _cfg(max_dominant_fraction=PETS_CEILING), view=_view(HEALTHY_SYMBOLS)
        )
        assert result.verdict is CheckVerdict.PASSED
        # 370 = 37*10, so every symbol appears exactly 10 times.
        assert result.metrics["dominant_fraction"] == 10 / PETS_N

    def test_the_ceiling_is_inclusive_and_load_bearing(self):
        # 3 of 4 predictions are symbol 0: fraction exactly 0.75.
        symbols = np.array([0, 0, 0, 1], dtype=np.int64)
        check = CategoricalDominantFractionCheck()
        at = check.run(_ctx(), _cfg(max_dominant_fraction=0.75), view=_view(symbols))
        below = check.run(_ctx(), _cfg(max_dominant_fraction=0.74), view=_view(symbols))
        assert at.passed is True
        assert below.passed is False


CATEGORICAL_CHECKS = (CategoricalDistinctSymbolsCheck, CategoricalDominantFractionCheck)
CATEGORICAL_MODULES = {
    CategoricalDistinctSymbolsCheck: cds_module,
    CategoricalDominantFractionCheck: cdf_module,
}


class TestTheSharedValidityBoundary:
    """§3.2a for the categorical family, through the ONE shared mechanism."""

    def test_the_helper_rules_out_of_range_symbols_deterministically(self):
        ruling = validate_symbols(np.array([0, 37, -1, 5], dtype=np.int64), 37)
        assert ruling.valid is False
        assert ruling.invalid_count == 2
        assert ruling.first_invalid == 37
        assert "[0, 37)" in ruling.reason
        assert "index 1" in ruling.reason

    def test_the_helper_accepts_a_full_range_stream(self):
        ruling = validate_symbols(np.array([0, 36], dtype=np.int64), 37)
        assert ruling == SymbolValidity(valid=True, invalid_count=0, first_invalid=None, reason="")

    @pytest.mark.parametrize("check_cls", CATEGORICAL_CHECKS, ids=lambda c: c.name)
    def test_an_out_of_range_symbol_is_FAILED_naming_the_offender(self, check_cls):
        bad = np.array([5, 5, 41], dtype=np.int64)
        result = check_cls().run(_ctx(), _cfg(), view=_view(bad))
        assert result.verdict is CheckVerdict.FAILED
        assert "41" in result.reason
        assert "[0, 37)" in result.reason
        assert result.metrics["invalid_symbol_count"] == 1

    @pytest.mark.parametrize("check_cls", CATEGORICAL_CHECKS, ids=lambda c: c.name)
    def test_the_shared_helper_is_load_bearing_for_this_check(self, check_cls, monkeypatch):
        """Mutation: silence the helper → the FAILED ruling disappears.

        Proves the check consults the ONE shared mechanism rather than
        carrying a private copy of the range arithmetic — the drift the
        family invariant forbids.
        """
        monkeypatch.setattr(
            CATEGORICAL_MODULES[check_cls],
            "validate_symbols",
            lambda symbols, cardinality: SymbolValidity(
                valid=True, invalid_count=0, first_invalid=None, reason=""
            ),
        )
        bad = np.array([5, 5, 41], dtype=np.int64)
        result = check_cls().run(_ctx(), _cfg(), view=_view(bad))
        assert result.verdict is not CheckVerdict.ERROR
        assert "outside the declared alphabet" not in result.reason

    @pytest.mark.parametrize("check_cls", CATEGORICAL_CHECKS, ids=lambda c: c.name)
    def test_an_empty_stream_is_ERROR(self, check_cls):
        result = check_cls().run(_ctx(), _cfg(), view=_view(np.array([], dtype=np.int64)))
        assert result.verdict is CheckVerdict.ERROR
        assert result.passed is False
        assert result.metrics["n_samples"] == 0

    @pytest.mark.parametrize("check_cls", CATEGORICAL_CHECKS, ids=lambda c: c.name)
    def test_an_absent_view_is_ERROR(self, check_cls):
        result = check_cls().run(_ctx(), _cfg())
        assert result.verdict is CheckVerdict.ERROR
        assert CATEGORICAL_PREDICTIONS in result.reason

    @pytest.mark.parametrize("check_cls", CATEGORICAL_CHECKS, ids=lambda c: c.name)
    def test_a_foreign_payload_is_ERROR_naming_the_type(self, check_cls):
        foreign = HealthView(
            capability_key=CATEGORICAL_PREDICTIONS,
            provider_id="test.categorical_views",
            payload={"symbols": [1, 2, 3]},
        )
        result = check_cls().run(_ctx(), _cfg(), view=foreign)
        assert result.verdict is CheckVerdict.ERROR
        assert "dict" in result.reason

    @pytest.mark.parametrize("check_cls", CATEGORICAL_CHECKS, ids=lambda c: c.name)
    def test_a_missing_injected_cardinality_is_ERROR(self, check_cls):
        result = check_cls().run(_ctx(), {}, view=_view(COLLAPSED_SYMBOLS))
        assert result.verdict is CheckVerdict.ERROR
        assert "symbol_cardinality" in result.reason


class TestDeclarations:
    """The §3.3/§2.11 biconditional adjacencies for the grown family."""

    @pytest.mark.parametrize("check_cls", CATEGORICAL_CHECKS, ids=lambda c: c.name)
    def test_categorical_declarations_are_exact(self, check_cls):
        declaration = check_cls.declaration
        assert declaration.consumes_view == "categorical_predictions"
        assert declaration.requires_view is True
        assert declaration.required_context_inputs == ()
        assert [r.axis for r in declaration.required_facts] == ["symbol_cardinality"]
        assert all(r.equals is None for r in declaration.required_facts)

    def test_each_check_declares_exactly_its_one_threshold(self):
        assert CategoricalDistinctSymbolsCheck.declaration.threshold_parameter_names == (
            "min_distinct_symbols",
        )
        assert CategoricalDominantFractionCheck.declaration.threshold_parameter_names == (
            "max_dominant_fraction",
        )

    def test_symbol_cardinality_is_never_a_threshold(self):
        """It is an injected FACT (§3.3) — the 08a peek_samples lesson."""
        from execute_tools.health_checks.registry import _REGISTRY, all_registered

        for name in all_registered():
            declaration = getattr(_REGISTRY[name], "declaration", None)
            if declaration is None:
                continue
            assert "symbol_cardinality" not in declaration.threshold_parameter_names, name

    def test_new_checks_declare_no_value_scale_and_no_per_sample_evidence(self):
        """Thresholds are in the view's native units; the value-scale
        biconditional set stays exactly the four TIDMAD checks."""
        for check_cls in CATEGORICAL_CHECKS:
            axes = {r.axis for r in check_cls.declaration.required_facts}
            assert "value_scale_unit" not in axes, check_cls.name
            assert "per_sample_evidence" not in check_cls.declaration.required_context_inputs


def _pets_shaped_config(**overrides: Any) -> TaskHealthConfig:
    body: dict[str, Any] = {
        "facts": {
            "encoding_family": "categorical_labels",
            "symbol_cardinality": PETS_CARDINALITY,
        },
        "roster": [
            {
                "gate_id": "distinct_gate",
                "check": "categorical_distinct_symbols",
                "disposition": "blocking",
                "parameters": {"min_distinct_symbols": PETS_FLOOR},
            },
            {
                "gate_id": "dominant_gate",
                "check": "categorical_dominant_fraction",
                "disposition": "blocking",
                "parameters": {"max_dominant_fraction": PETS_CEILING},
            },
        ],
    }
    body.update(overrides)
    return TaskHealthConfig.model_validate(body)


class _CategoricalSpyProvider:
    provider_id: ClassVar[str] = "test.categorical_views"
    capabilities: ClassVar[frozenset[str]] = frozenset({CATEGORICAL_PREDICTIONS})

    def __init__(self, symbols: np.ndarray):
        self._symbols = symbols
        self.calls: list[str] = []

    def materialize(
        self,
        capability_key: str,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthView:
        self.calls.append(capability_key)
        return _view(self._symbols)


class TestCardinalityInjection:
    """§3.3 — declaration-driven, table-bounded, collision-refusing."""

    def test_the_frozen_injectable_table_is_exactly_the_frozen_table(self):
        """Hardcoded: growing it is a design decision, not a drive-by."""
        assert INJECTABLE_AXIS_PARAMETERS == {
            "value_scale_unit": ("value_scale_units_per_sample", "value_scale_unit"),
            "symbol_cardinality": ("symbol_cardinality",),
        }
        assert INJECTED_PARAMETER_KEYS == frozenset(
            {"value_scale_units_per_sample", "value_scale_unit", "symbol_cardinality"}
        )

    def test_a_declaring_check_receives_the_cardinality(self, preserved_registry):
        composed = compose_health_gates(_pets_shaped_config())
        by_id = {g["id"]: g for g in composed}
        for gate_id in ("distinct_gate", "dominant_gate"):
            config = by_id[gate_id]["checks"][0]["config"]
            assert config["symbol_cardinality"] == PETS_CARDINALITY

    def test_a_non_declaring_check_receives_nothing(self, preserved_registry):
        config = _pets_shaped_config(
            roster=[
                {
                    "gate_id": "dispersion_gate",
                    "check": "sample_dispersion_floor",
                    "disposition": "blocking",
                    "parameters": {"min_dispersion": 0.5},
                }
            ]
        )
        composed = compose_health_gates(config)
        assert "symbol_cardinality" not in composed[0]["checks"][0]["config"]
        assert injected_parameters_for("sample_dispersion_floor", config) == {}

    def test_a_task_declaring_no_cardinality_injects_nothing(self, preserved_registry):
        config = _pets_shaped_config(facts={"encoding_family": "categorical_labels"})
        for name in ("categorical_distinct_symbols", "categorical_dominant_fraction"):
            assert injected_parameters_for(name, config) == {}

    @pytest.mark.parametrize(
        "authored",
        [
            {"symbol_cardinality": 40},
            {"value_scale_unit": "mV"},
            {"value_scale_units_per_sample": 0.3125},
        ],
        ids=lambda d: next(iter(d)),
    )
    def test_an_authored_injected_key_is_refused_naming_it(self, authored, preserved_registry):
        key = next(iter(authored))
        config = _pets_shaped_config(
            roster=[
                {
                    "gate_id": "colliding_gate",
                    "check": "categorical_distinct_symbols",
                    "disposition": "blocking",
                    "parameters": {"min_distinct_symbols": 5, **authored},
                }
            ]
        )
        with pytest.raises(HealthCompositionError, match=key):
            compose_health_gates(config)

    def test_the_refusal_replaced_the_silent_overwrite(self, preserved_registry):
        """Before C2, compose_gate's update order silently overwrote an
        authored value with the injected one. The refusal must fire even
        when the authored value EQUALS what injection would have written —
        agreement by coincidence is still two authorities."""
        config = _pets_shaped_config(
            roster=[
                {
                    "gate_id": "agreeing_gate",
                    "check": "categorical_distinct_symbols",
                    "disposition": "blocking",
                    "parameters": {"symbol_cardinality": PETS_CARDINALITY},
                }
            ]
        )
        with pytest.raises(HealthCompositionError, match="symbol_cardinality"):
            compose_health_gates(config)

    def test_a_valid_task_roster_authors_no_injected_key(self):
        """Task rosters leave declaration-derived axes to composition."""
        config = _pets_shaped_config()
        for entry in config.roster:
            authored = set(entry.parameters) & INJECTED_PARAMETER_KEYS
            assert not authored, (entry.gate_id, sorted(authored))


class TestComposedChainEndToEnd:
    """compose → bind → evaluate: the injected fact provably enters run()."""

    def _evaluate(self, monkeypatch, symbols: np.ndarray, config: TaskHealthConfig):
        provider = _CategoricalSpyProvider(symbols)
        register(CategoricalDistinctSymbolsCheck())
        register(CategoricalDominantFractionCheck())
        register_view_provider(provider)
        resolve_task_health_bindings(config)
        composed = resolve_composed_gates([], config)
        gates = HealthChecksConfig(health_gates=[GateConfig.model_validate(g) for g in composed])
        monkeypatch.setattr(runner, "load_health_gates_config", lambda *a, **k: gates)
        results = {g.id: evaluate_gate(g.id, _ctx()) for g in gates.health_gates}
        return provider, results

    def test_the_real_collapse_fails_both_composed_gates(self, monkeypatch, clean_registry):
        config = _pets_shaped_config(providers=[{"provider_id": "test.categorical_views"}])
        provider, results = self._evaluate(monkeypatch, COLLAPSED_SYMBOLS, config)

        distinct = results["distinct_gate"].check_results[0]
        assert distinct.verdict is CheckVerdict.FAILED
        assert distinct.metrics["distinct_symbols"] == PETS_DISTINCT
        # The decisive injection evidence: occupancy needs the injected 37.
        assert distinct.metrics["occupancy"] == PETS_OCCUPANCY

        dominant = results["dominant_gate"].check_results[0]
        assert dominant.verdict is CheckVerdict.FAILED
        assert dominant.metrics["dominant_fraction"] == PETS_DOMINANT_FRACTION
        assert dominant.metrics["dominant_symbol"] == PETS_DOMINANT_SYMBOL

        assert results["distinct_gate"].action.value == "invalidate_round"
        assert results["dominant_gate"].action.value == "invalidate_round"
        # One materialization per evaluated gate — the provider was the
        # ONLY sample source (no config-borne symbols exist to fall back to).
        assert provider.calls == [CATEGORICAL_PREDICTIONS, CATEGORICAL_PREDICTIONS]

    def test_a_healthy_spread_passes_both_composed_gates(self, monkeypatch, clean_registry):
        config = _pets_shaped_config(providers=[{"provider_id": "test.categorical_views"}])
        _, results = self._evaluate(monkeypatch, HEALTHY_SYMBOLS, config)
        assert results["distinct_gate"].passed is True
        assert results["dominant_gate"].passed is True

    def test_aggregation_policy_key_is_harmless_for_single_view_checks(
        self, monkeypatch, clean_registry
    ):
        """The blocking policy injects ``aggregation`` (``all_pass`` since
        the C2 flip, 2026-08-26; ``any_pass`` before) into every blocking
        gate's check config. These checks evaluate ONE stream, so the key
        is inert — recorded here so the assumption is executable."""
        config = _pets_shaped_config(providers=[{"provider_id": "test.categorical_views"}])
        composed = resolve_composed_gates([], config)
        assert composed[0]["checks"][0]["config"]["aggregation"] == "all_pass"

        direct = CategoricalDistinctSymbolsCheck().run(
            _ctx(),
            _cfg(min_distinct_symbols=PETS_FLOOR, aggregation="all_pass"),
            view=_view(COLLAPSED_SYMBOLS),
        )
        bare = CategoricalDistinctSymbolsCheck().run(
            _ctx(), _cfg(min_distinct_symbols=PETS_FLOOR), view=_view(COLLAPSED_SYMBOLS)
        )
        assert direct.model_dump() == bare.model_dump()

    def test_a_task_declaring_no_cardinality_is_inapplicable_with_zero_reads(
        self, monkeypatch, clean_registry
    ):
        """The 08b ordering contract extended to the categorical family:
        INAPPLICABLE is decided from declarations alone, so the provider is
        never asked to materialize."""
        config = _pets_shaped_config(
            facts={"encoding_family": "categorical_labels"},
            providers=[{"provider_id": "test.categorical_views"}],
        )
        provider, results = self._evaluate(monkeypatch, COLLAPSED_SYMBOLS, config)
        for gate_id in ("distinct_gate", "dominant_gate"):
            (check_result,) = results[gate_id].check_results
            assert check_result.verdict is CheckVerdict.INAPPLICABLE
            assert check_result.metrics["inapplicable_axis"] == "symbol_cardinality"
        assert provider.calls == []

    def test_a_raising_provider_is_ERROR_through_the_gate(self, monkeypatch, clean_registry):
        class _RaisingProvider(_CategoricalSpyProvider):
            def materialize(self, capability_key, ctx, config=None):
                raise OSError("the artifact is unreadable")

        provider = _RaisingProvider(COLLAPSED_SYMBOLS)
        register(CategoricalDistinctSymbolsCheck())
        register(CategoricalDominantFractionCheck())
        register_view_provider(provider)
        config = _pets_shaped_config(providers=[{"provider_id": "test.categorical_views"}])
        resolve_task_health_bindings(config)
        composed = resolve_composed_gates([], config)
        gates = HealthChecksConfig(health_gates=[GateConfig.model_validate(g) for g in composed])
        monkeypatch.setattr(runner, "load_health_gates_config", lambda *a, **k: gates)
        result = evaluate_gate("distinct_gate", _ctx())
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.ERROR
        assert "view provider failed" in check_result.reason


class TestDispersionNonFiniteBoundary:
    """The continuous half of §3.2a not already owned by the rung module."""

    def test_a_nan_sample_is_FAILED_naming_it(self):
        from execute_tools.health_checks.standard_views import ContinuousSamplesPayload

        view = HealthView(
            capability_key="continuous_samples",
            provider_id="test.continuous_views",
            payload=ContinuousSamplesPayload(
                samples=np.array([1.0, np.nan, 3.0], dtype=np.float64)
            ),
        )
        result = SampleDispersionFloorCheck().run(_ctx(), {"min_dispersion": 0.5}, view=view)
        assert result.verdict is CheckVerdict.FAILED
        assert result.passed is False
        assert result.metrics["non_finite_samples"] == 1
        assert "index 1" in result.reason
