"""A formal launch whose declared policy is unusable is refused at startup.

V20 PR D, checkpoint D-C1b.

D-C1a made `healthgate_mode` and `result_authority` declared facts but let
anything through. This is what makes the declaration mean something.

**Where the refusal lives, and why not the schema.** The check runs at the
new-formal-launch boundary (`run_one_iteration.py`), not in
`HyperparamTuningInput`. Two reasons, both load-bearing:

- the permissive schema is what keeps historical artifacts readable. An
  artifact recorded under `observe_only + scientific` documents an
  incident; a schema that refused it would make the incident unopenable.
  `core/resume.py` reads manifests directly and never constructs a
  `HyperparamTuningInput`, so tightening the launch path cannot break it.
- `validate_runtime_config` runs for *every* tuner invocation, including
  diagnostic tooling — `scripts/bg_admission_validation.py` builds a tuner
  input. Refusing there would block diagnosis, and an exemption flag would
  be a bypass surface that can be used by accident.

**Roles are never re-derived here.** Scientific membership comes from the
shared resolver merged in the predecessor hotfix; only *enforcement* is
action-derived, which is the correct question for "does this config
actually invalidate anything".
"""

from __future__ import annotations

import pytest

from execute_tools.health_checks.launch_policy import (
    FormalLaunchPolicyError,
    validate_formal_launch,
)
from execute_tools.metric_order import MetricOrder
from tests.helpers.metric_fixtures import shipped_spec

BLOCKING = "configs/health_checks.yaml"
OBSERVE = "configs/health_checks_baseline_observe_mode.yaml"


def _check(**overrides) -> None:
    kwargs = {
        "healthgate_mode": "blocking",
        "result_authority": "scientific",
        "health_checks_config": BLOCKING,
        "gates_enabled": True,
        "skip_formal_min_delta": 0.0,
        "bypass_formal_time_budget_min_delta": 0.5,
    }
    kwargs.update(overrides)
    validate_formal_launch(**kwargs)  # type: ignore[arg-type]


class TestTheLegalCombinationsLaunch:
    def test_blocking_scientific_over_the_blocking_config(self):
        """The V19/V20 formal posture, which the chain shell now declares."""
        _check()

    def test_blocking_diagnostic_is_legal(self):
        """Enforced, deliberately not promoted. This is the combination that
        proves the two axes are independent — if they were one field it
        could not be expressed."""
        _check(result_authority="diagnostic")

    def test_observe_only_diagnostic_over_the_observe_config(self):
        _check(
            healthgate_mode="observe_only",
            result_authority="diagnostic",
            health_checks_config=OBSERVE,
        )


class TestOmissionIsRefused:
    @pytest.mark.parametrize(
        ("field", "flag"),
        [("healthgate_mode", "--healthgate_mode"), ("result_authority", "--result_authority")],
    )
    def test_each_axis_is_mandatory(self, field, flag):
        """MUTATION TARGET: giving either a default.

        Defaulting to blocking/scientific would let a run claim enforcement
        and standing nobody configured — the operator's ruling.
        """
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(**{field: None})
        assert flag in str(exc.value)

    def test_omitting_both_names_both(self):
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(healthgate_mode=None, result_authority=None)
        assert "--healthgate_mode" in str(exc.value)
        assert "--result_authority" in str(exc.value)


class TestTheContradictionIsRefused:
    def test_observe_only_scientific(self):
        """Gates that only record cannot certify anything."""
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(
                healthgate_mode="observe_only",
                result_authority="scientific",
                health_checks_config=OBSERVE,
            )
        assert "contradiction" in str(exc.value)


class TestTheDeclarationMustMatchTheConfig:
    def test_blocking_declared_over_an_observe_only_config(self):
        """THE 08:17-CLASS SHAPE: the artifact would say enforced while the
        run was not. Named gates, so an operator can fix it."""
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(health_checks_config=OBSERVE)
        message = str(exc.value)
        assert "cannot invalidate" in message
        assert "output_diversity_blocking" in message

    def test_observe_only_declared_over_a_blocking_config(self):
        """The other direction: an observe-only run must not be able to
        invalidate a round."""
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(healthgate_mode="observe_only", result_authority="diagnostic")
        assert "still invalidate" in str(exc.value)

    def test_a_mixed_role_config_is_legal(self):
        """Mixed roles are the NORMAL case — three blocking, three
        observational. Only the blocking-role gates must enforce; the
        observational ones continuing is correct, not a mismatch."""
        _check()

    def test_a_role_less_config_cannot_be_declared_blocking(self, tmp_path):
        """A new launch must declare every role. An unaudited role-less
        config is UNKNOWN, and UNKNOWN is not a licence to assume."""
        import yaml

        body = yaml.safe_load(open(BLOCKING, encoding="utf-8"))
        for gate in body["health_gates"]:
            gate.pop("gate_role", None)
        body["health_gates"][0]["checks"][0]["config"]["min_unique_ratio"] = 0.123456
        path = tmp_path / "unaudited.yaml"
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(body, handle, sort_keys=False)

        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(health_checks_config=str(path))
        assert "cannot be established" in str(exc.value)


class TestTheDeltaOrderingInvariant:
    def test_inverted_deltas_are_refused_when_the_gates_are_enabled(self):
        """Measured: inverted, BOTH gates fire for the same score and the
        outcome is decided by statement order rather than policy."""
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(skip_formal_min_delta=1.0, bypass_formal_time_budget_min_delta=0.0)
        assert "must not" in str(exc.value)

    def test_inverted_deltas_are_ignored_when_the_gates_are_disabled(self):
        """THE SCOPING RULE. With the gates off the deltas are not consumed
        at all, so an unused historical pair must not block a launch."""
        _check(
            gates_enabled=False,
            skip_formal_min_delta=1.0,
            bypass_formal_time_budget_min_delta=0.0,
        )

    def test_equal_deltas_are_legal(self):
        """The boundary: `<=`, not `<`. Equal thresholds leave no middle
        band, which is a coherent configuration."""
        _check(skip_formal_min_delta=0.5, bypass_formal_time_budget_min_delta=0.5)


class TestNonFiniteDeltasAreRefused:
    """FU-D-8, closed as D-C3 reinforcement.

    A NaN or infinite delta makes every gate comparison `False`, so both
    gates are SILENTLY DISABLED while the artifact still records an
    enforced run. That is the same fail-open shape §16.C eliminated for
    the missing bootstrap reference, and it is a configuration refusal for
    the same reason: the alternative is a run that looks enforced and
    gates nothing.

    Scope matters. What is refused is the OPERATOR-CONFIGURED delta. The
    internally resolved `-inf` comparison reference is a deliberate
    resolver value and stays legal — `TestTheBootstrapIsNotRefused` below
    is what stops a future edit from conflating them.
    """

    @pytest.mark.parametrize(
        "value", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
    )
    @pytest.mark.parametrize(
        "field", ["skip_formal_min_delta", "bypass_formal_time_budget_min_delta"]
    )
    def test_each_field_rejects_each_non_finite_value(self, field, value):
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(**{field: value})
        message = str(exc.value)
        assert "not finite" in message
        assert field in message

    def test_nan_cannot_hide_behind_the_ordering_check(self):
        """MUTATION TARGET: ordering checked BEFORE finiteness.

        `NaN > NaN` is `False`, so an inverted-and-unusable pair passes the
        ordering rule unnoticed. Finiteness must be evaluated first — this
        is the case that proves the order of the two checks matters.
        """
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(
                skip_formal_min_delta=float("nan"),
                bypass_formal_time_budget_min_delta=float("nan"),
            )
        assert "not finite" in str(exc.value)

    def test_both_non_finite_fields_are_named_at_once(self):
        """An operator fixing one should see the other without re-running."""
        with pytest.raises(FormalLaunchPolicyError) as exc:
            _check(
                skip_formal_min_delta=float("-inf"),
                bypass_formal_time_budget_min_delta=float("inf"),
            )
        message = str(exc.value)
        assert "skip_formal_min_delta" in message
        assert "bypass_formal_time_budget_min_delta" in message

    @pytest.mark.parametrize(
        "value", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
    )
    def test_the_gates_disabled_scoping_rule_still_holds(self, value):
        """THE COMPATIBILITY BOUNDARY, matching the established convention
        for inverted deltas: with the gates off the deltas are not consumed
        at all, so a malformed unused value must not block a launch."""
        _check(
            gates_enabled=False,
            skip_formal_min_delta=value,
            bypass_formal_time_budget_min_delta=value,
        )

    def test_ordinary_finite_deltas_including_negatives_still_launch(self):
        """The refusal is finiteness, NOT sign. `-1.0` is the production
        default for the skip delta and must stay legal."""
        _check(skip_formal_min_delta=-1.0, bypass_formal_time_budget_min_delta=0.0)


class TestTheBootstrapIsNotRefused:
    def test_the_internal_negative_infinity_reference_is_a_different_concept(self):
        """MUTATION TARGET: extending the finiteness refusal to the
        comparison REFERENCE.

        §16.C makes `-inf` the effective reference when no valid formal
        incumbent was restored — that is how a fresh chain's first valid
        trial gets its formal baseline. Refusing it would break the
        bootstrap outright. `validate_formal_launch` never receives the
        reference, and this test pins that separation by signature.
        """
        import inspect

        params = set(inspect.signature(validate_formal_launch).parameters)
        assert "current_run_best_formal_score" not in params
        assert "formal_reference_score" not in params
        assert "reference_score" not in params

        # And the resolver still bootstraps to -inf, unaffected by the
        # launch-time delta refusal.
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _resolve_formal_comparison_thresholds,
        )

        reference, _, _, source = _resolve_formal_comparison_thresholds(
            reference_score=None,
            skip_min_delta=0.0,
            bypass_min_delta=0.5,
            gates_enabled=True,
            order=MetricOrder(shipped_spec()),
        )
        assert reference == float("-inf")
        assert source == "negative_infinity_bootstrap"


class TestRefusalIsNotAScientificEvent:
    def test_it_raises_the_startup_configuration_error_type(self):
        """A policy mismatch is a configuration refusal — not a candidate
        failure, a gate failure, an operator stop, or GPU evidence. It
        reuses `ValueError`, which is what `validate_runtime_config`
        already raises for startup configuration problems."""
        assert issubclass(FormalLaunchPolicyError, ValueError)
