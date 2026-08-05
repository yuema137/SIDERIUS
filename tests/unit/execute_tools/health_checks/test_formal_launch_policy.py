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


class TestRefusalIsNotAScientificEvent:
    def test_it_raises_the_startup_configuration_error_type(self):
        """A policy mismatch is a configuration refusal — not a candidate
        failure, a gate failure, an operator stop, or GPU evidence. It
        reuses `ValueError`, which is what `validate_runtime_config`
        already raises for startup configuration problems."""
        assert issubclass(FormalLaunchPolicyError, ValueError)
