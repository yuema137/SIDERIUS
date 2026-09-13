"""Unit tests for the post-v15 delta gates: ``skip_formal_min_delta`` and
``bypass_formal_time_budget_min_delta``.

V19 PR 1 (docs/design/v19_priorities/pr1_chain_incumbents.md, P1-C1):
``current_run_best_formal_score`` is the chain formal-incumbent
reference, ``float | None`` with ``None`` = "no incumbent". Defaults:
  * ``current_run_best_formal_score = None`` → no restored incumbent
  * ``skip_formal_min_delta = -1.0`` → skip formal when trial < (ref - 1.0)
  * ``bypass_formal_time_budget_min_delta = 0.0`` → bypass time gate when
    trial >= ref

``_resolve_formal_comparison_thresholds`` is the SINGLE authoritative
computation: the gates, the startup banner, and the persisted output
metadata all consume its values (no independent ``ref + delta`` copies).

**V20 PR D, D-C3 — the rule this module asserts changed.** Previously a
missing incumbent made both gates permanently inert:

    no incumbent  ->  reference None  ->  thresholds None  ->  no gate fires

§16.C replaces that with the negative-infinity bootstrap:

    no incumbent, gates ENABLED   ->  effective reference -inf
    no incumbent, gates DISABLED  ->  None, exactly as before

so on a fresh chain the first HealthGate-valid trial is never skipped,
always clears any finite bypass threshold, and establishes the first
formal baseline. The gates-disabled path is unchanged, which is why every
test below states which side of that switch it is on.

Motivation history (v15 retrospective) is retained on the schema block
comment; see ``agent/schemas/hyperparam_tuning.py``.
"""

from __future__ import annotations

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _best_trial_winner,
    _fmt_reference,
    _resolve_formal_comparison_thresholds,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
)
from tests.helpers.metric_fixtures import direction_only_spec, shipped_spec

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_input(**overrides) -> HyperparamTuningInput:
    """Construct a minimal valid HyperparamTuningInput; tests override the
    delta-gate fields to exercise the schema contract."""
    storage = StorageConfig(local=LocalStorageConfig(workspace="/tmp/test_delta_gates"))
    base = {
        "model_type": "punet",
        "run_name": "test_delta_gates",
        "storage": storage,
    }
    base.update(overrides)
    return HyperparamTuningInput(**base)


_BLOCKING_IDS = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)
# These fixtures model this nonempty roster; selection receives the same policy
# as the supplied verdicts instead of asking for an implicit default.


def _valid_trial(score: float) -> dict:
    """A HealthGate-valid trial record eligible for `_best_trial_winner`."""
    return {
        "exp_id": f"trial_{score}",
        "status": "success",
        "denoising_score": score,
        "is_trial": True,
        "health_gate_results": [
            {
                "gate_name": gate_id,
                "execution_status": "passed",
                "check_passed": True,
                "would_invalidate_under_production_policy": False,
                "resolved_action": "continue",
            }
            for gate_id in _BLOCKING_IDS
        ],
        "memory": {"time_mode": "trial"},
    }


#: Step 07 PR 07b — the gates now consume the run's ONE order authority.
#: The SHIPPED (higher-is-better) order is this module's default so every
#: pre-07b assertion below states exactly the property it stated before; the
#: direction-parametrized tests pass ``LOWER_ORDER`` explicitly.
HIGHER_ORDER = MetricOrder(shipped_spec())
LOWER_ORDER = MetricOrder(direction_only_spec())
ORDERS = {"higher": HIGHER_ORDER, "lower": LOWER_ORDER}


def _resolve(
    reference, skip_delta=-1.0, bypass_delta=0.0, *, gates_enabled=True, order=HIGHER_ORDER
):
    """The production resolver. ``gates_enabled`` defaults to the production
    posture (the switch is ON) so a test that does not mention it is
    asserting the enforced behaviour."""
    return _resolve_formal_comparison_thresholds(
        reference_score=reference,
        skip_min_delta=skip_delta,
        bypass_min_delta=bypass_delta,
        gates_enabled=gates_enabled,
        order=order,
    )


def _skip(records, *, threshold, gates_enabled=True, order=HIGHER_ORDER) -> bool:
    """Records → winner → gate, the way production does it.

    Deliberately routed through the real `_best_trial_winner` rather than
    handing the gate a winner dict: that is what keeps "a collapsed trial
    can never open a gate" a live assertion here instead of an assumption.
    """
    return _should_skip_formal(
        _best_trial_winner(records, order=order, required_gate_ids=frozenset(_BLOCKING_IDS)),
        threshold=threshold,
        gates_enabled=gates_enabled,
        order=order,
    )


def _bypass(records, *, threshold, order=HIGHER_ORDER) -> bool:
    """Records → winner → gate. See :func:`_skip`."""
    return _should_bypass_formal_time_budget(
        _best_trial_winner(records, order=order, required_gate_ids=frozenset(_BLOCKING_IDS)),
        threshold=threshold,
        order=order,
    )


# ---------------------------------------------------------------------------
# Schema defaults — the None incumbent sentinel
# ---------------------------------------------------------------------------


class TestDeltaGateSchema:
    def test_default_reference_is_none_no_incumbent(self):
        """V19 PR 1: default is ``None`` (no chain incumbent) — NOT the
        pre-V19 fixed 0.0 defect value."""
        inp = _make_input()
        assert inp.current_run_best_formal_score is None

    def test_explicit_zero_reference_remains_legal(self):
        """0.0 as an EXPLICIT reference stays valid (standalone runs) and
        behaves as an ordinary number, distinct from ``None``.

        D-C3 sharpens this: an explicit 0.0 must resolve through the
        *incumbent* branch, so the source proves it was not confused with
        the bootstrap. A missing incumbent and a real incumbent of 0.0 are
        different facts and now say so.
        """
        inp = _make_input(current_run_best_formal_score=0.0)
        assert inp.current_run_best_formal_score == 0.0
        ref, skip_t, bypass_t, source = _resolve(inp.current_run_best_formal_score)
        assert (ref, skip_t, bypass_t) == (0.0, -1.0, 0.0)
        assert source == "restored_valid_formal_incumbent"

    def test_skip_formal_min_delta_default_is_one_dB_floor(self):
        inp = _make_input()
        assert inp.skip_formal_min_delta == -1.0

    def test_bypass_formal_time_budget_min_delta_default_is_zero(self):
        inp = _make_input()
        assert inp.bypass_formal_time_budget_min_delta == 0.0


# ---------------------------------------------------------------------------
# Resolver — the single source of gate arithmetic
# ---------------------------------------------------------------------------


class TestResolver:
    def test_no_incumbent_bootstraps_to_negative_infinity_when_gates_are_on(self):
        """RULE CHANGE (§16.C). The old rule was:

            no incumbent -> (None, None, None)   # gates inert

        and this test asserted exactly that. It is now:

            no incumbent + gates ON -> -inf everywhere

        The original defect it protected — a missing incumbent must never
        silently become a NUMBER, above all not the pre-V19 fixed 0.0 —
        is preserved and is what the final assertion checks.
        """
        ref, skip_t, bypass_t, source = _resolve(None)
        assert (ref, skip_t, bypass_t) == (float("-inf"),) * 3
        assert source == "negative_infinity_bootstrap"
        # The original defect: never a finite stand-in, never 0.0.
        assert ref != 0.0

    def test_no_incumbent_with_the_gates_off_is_unchanged(self):
        """The other half of the rule change: with the feature switch OFF
        the deltas are not consumed at all, so the pre-V20 resolution
        survives byte for byte. This is what makes D-C3 safe to land
        without touching runs that never enabled the gates."""
        assert _resolve(None, gates_enabled=False) == (None, None, None, "gates_disabled")

    def test_numeric_reference_resolves_sums(self):
        assert _resolve(6.0, skip_delta=-1.0, bypass_delta=0.5) == (
            6.0,
            5.0,
            6.5,
            "restored_valid_formal_incumbent",
        )

    def test_a_real_incumbent_is_never_reported_as_the_bootstrap(self):
        """The provenance string is the only thing that distinguishes
        "we had a baseline" from "we invented one", and a report that
        confuses them would misdescribe the run's evidence."""
        for reference in (0.0, -3.5, 6.0, 5.5762667):
            assert _resolve(reference)[3] == "restored_valid_formal_incumbent"
        assert _resolve(None)[3] == "negative_infinity_bootstrap"

    def test_gates_consume_resolver_output_verbatim(self):
        """Single-source assertion: the values the gates receive are the
        resolver's outputs — recomputing ``ref + delta`` independently
        must give the identical threshold the gate fires on."""
        _ref, skip_t, bypass_t, _source = _resolve(6.0, skip_delta=-1.0, bypass_delta=0.0)
        # skip fires exactly below skip_t
        assert _skip([_valid_trial(skip_t - 0.01)], threshold=skip_t)
        assert not _skip([_valid_trial(skip_t)], threshold=skip_t)
        # bypass fires exactly at/above bypass_t
        assert _bypass([_valid_trial(bypass_t)], threshold=bypass_t)
        assert not _bypass([_valid_trial(bypass_t - 0.01)], threshold=bypass_t)

    def test_fmt_reference_renders_none_not_zero(self):
        """``None`` renders as 'none' — never as '0.0000' (the pre-V19
        defect value must be unrepresentable in banners)."""
        assert _fmt_reference(None) == "none"
        assert _fmt_reference(6.0) == "6.0000"


# ---------------------------------------------------------------------------
# The bootstrap, from the gates' side
# ---------------------------------------------------------------------------


class TestTheBootstrapArmsTheGates:
    """What used to be `TestNoneShortCircuit`.

    Both tests here asserted the same superseded rule — *no incumbent
    means no gate can fire*. Under §16.C the reference bootstraps to
    ``-inf`` instead, and the two gates respond differently, which is the
    whole point: the first valid trial must be able to bypass the time
    budget (the v15 failure `8f1cf528` was written to fix) while never
    being skipped.
    """

    def test_the_skip_gate_still_cannot_fire_on_a_valid_first_trial(self):
        """RULE CHANGE, same outcome, different reason.

        Was: threshold is ``None`` so the gate is inert.
        Now: threshold is ``-inf`` so no finite score can fall below it.

        The defect protected is unchanged — a chain with no baseline must
        not skip its first real candidate — but the mechanism is now the
        bootstrap, and the assertion on the threshold proves which one is
        actually running.
        """
        _, skip_t, _, source = _resolve(None)
        assert skip_t == float("-inf")
        assert source == "negative_infinity_bootstrap"
        assert not _skip([_valid_trial(-99.0)], threshold=skip_t)

    def test_the_bypass_gate_now_fires_where_it_previously_could_not(self):
        """RULE CHANGE, INVERTED outcome — the reason §16.C exists.

        Was: ``bypass_t is None`` → an excellent first trial was still
        blocked by the formal time budget, so the strongest candidate in
        a fresh chain never got formal validation. That is precisely the
        v15 failure re-appearing because the reference was absent rather
        than because the gate was wrong.
        Now: ``bypass_t == -inf`` → it clears, and the chain gets its
        first formal baseline.
        """
        _, _, bypass_t, _ = _resolve(None)
        assert bypass_t == float("-inf")
        assert _bypass([_valid_trial(99.0)], threshold=bypass_t)

    def test_with_the_gates_off_both_stay_inert(self):
        """The pre-V20 behaviour, still reachable and still asserted."""
        _, skip_t, bypass_t, _ = _resolve(None, gates_enabled=False)
        assert (skip_t, bypass_t) == (None, None)
        assert not _skip([_valid_trial(-99.0)], threshold=skip_t, gates_enabled=False)
        assert not _bypass([_valid_trial(99.0)], threshold=bypass_t)


# ---------------------------------------------------------------------------
# Numeric-threshold behavior (canonical operator scenarios, now through
# the real helpers)
# ---------------------------------------------------------------------------


class TestSkipFormalGate:
    def test_skip_fires_when_trial_well_below_best(self):
        """ref=6.0, delta=-1.0 → threshold=5.0 → trial 4.5 SKIPS formal."""
        _, skip_t, _, _ = _resolve(6.0, skip_delta=-1.0)
        assert skip_t == 5.0
        assert _skip([_valid_trial(4.5)], threshold=skip_t)

    def test_skip_does_not_fire_when_trial_close_to_best(self):
        """trial 5.2 >= threshold 5.0 → formal proceeds."""
        _, skip_t, _, _ = _resolve(6.0, skip_delta=-1.0)
        assert not _skip([_valid_trial(5.2)], threshold=skip_t)

    def test_skip_with_zero_delta_skips_anything_below_best(self):
        _, skip_t, _, _ = _resolve(6.0, skip_delta=0.0)
        assert skip_t == 6.0
        assert _skip([_valid_trial(5.99)], threshold=skip_t)
        assert not _skip([_valid_trial(6.01)], threshold=skip_t)


class TestBypassFormalTimeBudgetGate:
    def test_bypass_fires_when_trial_beats_best(self):
        _, _, bypass_t, _ = _resolve(6.0, bypass_delta=0.0)
        assert bypass_t == 6.0
        assert _bypass([_valid_trial(6.1)], threshold=bypass_t)

    def test_bypass_does_not_fire_when_trial_below_best(self):
        _, _, bypass_t, _ = _resolve(6.0, bypass_delta=0.0)
        assert not _bypass([_valid_trial(5.9)], threshold=bypass_t)

    def test_bypass_with_positive_delta_requires_clear_margin(self):
        _, _, bypass_t, _ = _resolve(6.0, bypass_delta=0.5)
        assert bypass_t == 6.5
        assert not _bypass([_valid_trial(6.4)], threshold=bypass_t)
        assert _bypass([_valid_trial(6.5)], threshold=bypass_t)


class TestDisableGatesViaInfinity:
    """Both gates can still be turned off via boundary deltas; the
    disable semantics moved INSIDE the helpers with the resolved-value
    signature."""

    def test_skip_gate_disabled_at_negative_infinity(self):
        _, skip_t, _, _ = _resolve(6.0, skip_delta=float("-inf"))
        assert skip_t == float("-inf")
        assert not _skip([_valid_trial(-99.0)], threshold=skip_t)

    def test_bypass_gate_disabled_at_positive_infinity(self):
        _, _, bypass_t, _ = _resolve(6.0, bypass_delta=float("inf"))
        assert bypass_t == float("inf")
        assert not _bypass([_valid_trial(99.0)], threshold=bypass_t)

    @pytest.mark.parametrize("direction", ["higher", "lower"], ids=["higher", "lower"])
    def test_the_disable_deltas_keep_disabling_under_either_direction(self, direction):
        """Step 07 PR 07b — the operator's documented disable values are
        ``skip_delta=-inf`` / ``bypass_delta=+inf``, and they must not acquire
        a second form when a campaign binds a lower-is-better metric.

        Under ``lower`` the resolver produces ``+inf`` for skip and ``-inf``
        for bypass, which are that metric's worst and best values — so the
        gates stay off. Left as raw addition, the skip threshold would resolve
        to ``-inf``, which under ``lower`` is the BEST possible score, and the
        gate would skip every formal round in the campaign.
        """
        order = ORDERS[direction]
        _, skip_t, bypass_t, _ = _resolve(
            6.0, skip_delta=float("-inf"), bypass_delta=float("inf"), order=order
        )
        assert skip_t == order.worst_sentinel
        assert bypass_t == order.best_sentinel
        assert not _skip([_valid_trial(-99.0)], threshold=skip_t, order=order)
        assert not _bypass([_valid_trial(99.0)], threshold=bypass_t, order=order)


# ---------------------------------------------------------------------------
# Persistence round-trip and the phantom negative
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_none_reference_round_trips_through_output(self):
        """``formal_reference_score=None`` survives HyperparamTuningOutput
        serialization → JSON null → parse."""
        out = HyperparamTuningOutput(
            run_name="rt",
            model_type="punet",
            file_index=0,
            status="completed",
            completed_rounds=0,
            total_attempts=0,
            all_records=[],
            started_at="2026-07-27 00:00:00",
            finished_at="2026-07-27 00:00:01",
            formal_reference_score=None,
            resolved_skip_formal_threshold=None,
            resolved_bypass_formal_threshold=None,
        )
        parsed = HyperparamTuningOutput.model_validate_json(out.model_dump_json())
        assert parsed.formal_reference_score is None
        assert parsed.resolved_skip_formal_threshold is None
        assert parsed.resolved_bypass_formal_threshold is None

    def test_phantom_family_reference_is_just_a_number(self):
        """5.5763 (class-127 phantom fingerprint) as an explicit reference
        gets no special-casing — it resolves like any float. Guarding
        against phantom DEFAULTS is the schema's job (default is None);
        eligibility filtering is reconstruction's job (P1-C2).

        D-C3 makes this MORE load-bearing, not less: §16.C withdrew the
        recommendation to seed the bootstrap from a configured baseline
        precisely because the historical seed was this phantom — a
        collapsed model scoring well by a PSD artifact. The bootstrap is
        ``-inf``, never a task-specific constant, and this test is what
        fails if one is ever introduced.
        """
        ref, skip_t, bypass_t, source = _resolve(5.5762667, skip_delta=-1.0, bypass_delta=0.0)
        assert ref == 5.5762667
        assert skip_t == 4.5762667
        assert bypass_t == 5.5762667
        assert source == "restored_valid_formal_incumbent"

    @pytest.mark.parametrize("phantom", [5.5763, 5.5762667, 0.0])
    def test_the_bootstrap_is_never_a_task_specific_constant(self, phantom):
        """MUTATION TARGET: seeding the bootstrap from a baseline artifact.

        Whatever value someone might reach for, the no-incumbent branch
        must not return it. `-inf` is the only admissible answer because
        every documented paper baseline is trained-but-collapsed, so
        there is no valid artifact to bootstrap from.
        """
        assert _resolve(None)[0] != phantom
