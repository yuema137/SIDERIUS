"""V21 PR B1b — a harness-owned bound applies to what will ACTUALLY run.

The binding rule is *the harness owns the bounds, not the planner*. It was
being defeated by silence rather than by a bad plan:

    plan omits `epochs`
      -> clamp reads .get("epochs", 1)  -> 1 > 1 is False -> no clamp
      -> trainer builds TrainConfig(**t_data) -> gets its declared 10
      -> ten epochs run under `--max_epochs 1`

Nothing in that chain is a bug in isolation. The defect is that the bound
was compared against the *planner's dict* while the run was configured
from the *schema's declaration*, so an absent key meant the planner's
silence decided a bound the operator owns.

The bounded sibling audit found the same shape once more, at
`max_steps_per_attempt`: the guardrail's step count was resolved at one
epoch, so it under-counted the workload tenfold and under-triggered.

Design doc: ``docs/design/v21_priorities/pr_b_resource_budget_semantics.md``
Commit B1b; ledger ``docs/design/v21_priorities.md`` §E.3c.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

import nodes.ml_hyperparameter_tune_agent as tuner


class TestResolvedEpochs:
    """``_resolve_effective_epochs`` answers "what will the trainer use?"."""

    def test_an_absent_key_resolves_to_what_the_trainer_will_use(self):
        from ml_models.models_format_sandbox import TrainConfig

        declared = TrainConfig.model_fields["epochs"].default
        assert declared == 10, "the canonical source moved; this test is the guard"
        assert tuner._resolve_effective_epochs({}) == declared

    def test_an_explicit_value_is_honoured(self):
        assert tuner._resolve_effective_epochs({"epochs": 3}) == 3

    def test_it_does_not_reintroduce_the_bypass_literal(self):
        """The specific regression: resolving an absent key to 1.

        That single value is what made the clamp compare ``1 > 1`` and
        decline to act.
        """
        assert tuner._resolve_effective_epochs({}) != 1

    def test_the_trainer_really_would_use_the_resolved_value(self):
        """Not a claim about a schema — a claim about the trainer.

        ``train_engine_sandbox`` builds ``TrainConfig(**t_data)``, so this
        constructs it the same way and reads back what training would get.
        Fails if the trainer's construction stops applying the default, or
        if the resolver and the trainer ever disagree.
        """
        from ml_models.models_format_sandbox import TrainConfig

        built = TrainConfig(**{"batch_size": 1, "lr": 1e-3, "optimizer_type": "adamw"})
        assert built.epochs == tuner._resolve_effective_epochs(
            {"batch_size": 1, "lr": 1e-3, "optimizer_type": "adamw"}
        )


class TestTheMaxEpochsBoundIsNotBypassable:
    """The clamp, driven through the production function itself.

    An earlier version of this class reimplemented the clamp locally
    because it lived inline in the 2,400-line ``run()``. A mutation
    deleting production's write-back then **survived**: the tests were
    asserting that the *test's* arithmetic worked. The clamp was
    extracted into ``_apply_epoch_bound`` so these can call it directly.

    Two properties, and both are needed — the behaviour, plus
    ``test_the_production_clamp_uses_the_resolver`` proving ``run()``
    still routes through it. Behaviour alone would pass even if
    production had stopped calling it.
    """

    @staticmethod
    def _clamp(train_cfg: dict, max_epochs: int | None) -> dict:
        """Drives PRODUCTION's ``_apply_epoch_bound``, not a copy of it.

        The first version of this helper reimplemented the clamp locally,
        and a mutation removing production's write-back **survived** — the
        tests were proving that the test's own arithmetic worked. The
        clamp was extracted from ``run()`` precisely so this could call
        the real thing.
        """
        cfg = dict(train_cfg)
        tuner._apply_epoch_bound(cfg, max_epochs)
        return cfg

    def test_an_omitted_epochs_is_clamped_to_the_operator_bound(self):
        """The V21 launch blocker, stated as a test.

        Before B1b this produced a config that trained ten epochs under
        ``--max_epochs 1``.
        """
        assert self._clamp({}, 1)["epochs"] == 1

    @pytest.mark.parametrize("max_epochs", [1, 2, 5])
    def test_the_resolved_value_never_exceeds_the_bound(self, max_epochs):
        for planned in ({}, {"epochs": 1}, {"epochs": 10}, {"epochs": 50}):
            assert self._clamp(planned, max_epochs)["epochs"] <= max_epochs

    def test_a_plan_below_the_bound_is_left_alone(self):
        assert self._clamp({"epochs": 1}, 5)["epochs"] == 1

    def test_a_non_binding_bound_preserves_the_RESOLVED_value(self):
        """The case that distinguishes resolving from not resolving.

        Added after a mutation survived. With ``max_epochs=1`` the wrong
        resolution (1) and the right one (10) both clamp to 1, so every
        assertion of the form ``effective <= bound`` passes either way.
        The bound has to be raised **above** the resolved value before the
        two diverge.

        Here the operator allows 50 and the plan omits ``epochs``: the
        trainer's declared 10 must survive. A resolver that returned 1
        would silently cut training tenfold while looking like a clamp
        that did nothing.
        """
        assert self._clamp({}, 50)["epochs"] == 10

    def test_the_effective_value_is_written_back_so_the_trainer_sees_it(self):
        """The operator's explicit requirement.

        A clamp that only informs the admission decision leaves the
        trainer free to resolve the absent key to ten. The effective value
        must be *in the config* that travels onward.
        """
        clamped = self._clamp({}, 1)
        assert "epochs" in clamped
        from ml_models.models_format_sandbox import TrainConfig

        assert TrainConfig(**clamped).epochs == 1

    def test_no_bound_configured_leaves_the_plan_untouched(self):
        assert self._clamp({}, None) == {}
        assert self._clamp({"epochs": 7}, None) == {"epochs": 7}

    def test_the_production_clamp_uses_the_resolver(self):
        """Reachability: the fix must be on the path, not merely defined.

        Fails if the clamp reverts to reading the raw dict, which is the
        exact bypass.
        """
        import inspect

        src = inspect.getsource(tuner)
        assert 'planned_epochs = plan.train_cfg.get("epochs", 1)' not in src, (
            "the clamp is reading the planner's dict again; an omitted "
            "epochs would bypass --max_epochs"
        )
        assert "_apply_epoch_bound(plan.train_cfg, agent_input.max_epochs)" in src

    def test_the_bound_is_applied_to_the_plan_the_run_carries(self):
        """The write-back, on the real object the run uses.

        ``_apply_epoch_bound`` mutates in place, so the plan that travels
        to ``TrialConfig`` and then to the trainer carries the effective
        value. Removing the write-back turns this red.
        """
        from ml_models.models_format_sandbox import TrainConfig

        plan_cfg: dict = {"batch_size": 1}
        returned = tuner._apply_epoch_bound(plan_cfg, 1)
        assert returned == 1
        assert plan_cfg["epochs"] == 1
        assert TrainConfig(**plan_cfg).epochs == 1

    def test_no_bound_configured_returns_None_and_mutates_nothing(self):
        plan_cfg: dict = {"batch_size": 1}
        assert tuner._apply_epoch_bound(plan_cfg, None) is None
        assert "epochs" not in plan_cfg


class TestGuardrailStepsUseTheResolvedWorkload:
    """The sibling the bounded audit found: ``max_steps_per_attempt``."""

    _SAMPLE: ClassVar[dict[str, list[int]]] = {"0": list(range(20)), "1": list(range(20))}

    def test_an_absent_epochs_no_longer_undercounts_the_workload(self):
        """10x low meant the bound under-triggered — the bypass direction."""
        absent = tuner._resolve_guardrail_steps(
            self._SAMPLE, {"segmentation_size": 40000}, {"batch_size": 1}, 1.0, model_type="punet"
        )
        ten = tuner._resolve_guardrail_steps(
            self._SAMPLE,
            {"segmentation_size": 40000},
            {"batch_size": 1, "epochs": 10},
            1.0,
            model_type="punet",
        )
        one = tuner._resolve_guardrail_steps(
            self._SAMPLE,
            {"segmentation_size": 40000},
            {"batch_size": 1, "epochs": 1},
            1.0,
            model_type="punet",
        )
        assert absent == ten
        assert absent == 10 * one

    def test_an_absent_segmentation_size_uses_the_declaration(self):
        """40x high meant spurious rejection — wrong in the other direction."""
        absent = tuner._resolve_guardrail_steps(
            self._SAMPLE, {}, {"batch_size": 1, "epochs": 1}, 1.0, model_type="punet"
        )
        declared = tuner._resolve_guardrail_steps(
            self._SAMPLE,
            {"segmentation_size": 40000},
            {"batch_size": 1, "epochs": 1},
            1.0,
            model_type="punet",
        )
        old_literal = tuner._resolve_guardrail_steps(
            self._SAMPLE,
            {"segmentation_size": 1000},
            {"batch_size": 1, "epochs": 1},
            1.0,
            model_type="punet",
        )
        assert absent == declared
        assert absent != old_literal

    def test_it_stays_best_effort_for_an_unknown_model(self):
        """Defense-in-depth must not become a new crash site."""
        assert (
            tuner._resolve_guardrail_steps(
                self._SAMPLE, {}, {"batch_size": 1}, 1.0, model_type="never_registered_xyz"
            )
            is not None
        )

    def test_an_explicitly_impossible_config_returns_None_not_a_substitute(self):
        """Absent is resolved; explicitly-invalid is refused.

        Caught by `test_rt5_guardrails::test_resolver_failure_returns_none`
        when B1b first landed: the new resolver treated
        ``segmentation_size: 0`` as absent and substituted a margin, so
        the guardrail would have judged a workload no run could produce.
        B1's own rule forbids that — "an explicitly invalid value must not
        silently become a fallback" — and the existing best-effort
        contract (unresolvable → ``None``) is preserved.
        """
        for bad_model, bad_train in (
            ({"segmentation_size": 0}, {"batch_size": 1}),
            ({"segmentation_size": -5}, {"batch_size": 1}),
            ({"segmentation_size": 40000}, {"batch_size": 1, "epochs": 0}),
        ):
            assert (
                tuner._resolve_guardrail_steps(
                    self._SAMPLE, bad_model, bad_train, 1.0, model_type="punet"
                )
                is None
            )

    def test_a_missing_sample_set_still_returns_None(self):
        assert tuner._resolve_guardrail_steps(None, {}, {}, 1.0, model_type="punet") is None
