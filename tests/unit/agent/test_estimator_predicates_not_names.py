"""V21 PR C3 — estimator behaviour keys on model properties, not names.

The five branches C3 replaced fed the **time and VRAM estimates that gate
admission**, so a generated model's *reachability* depended on whether its
name matched a hardcoded built-in string. The operator's rule is narrow and
worth restating, because the obvious over-reading is wrong:

    FINE       registry[model_name], artifact.model_name, logging
    FORBIDDEN  if model_type == "transformer": correctness_behaviour = X

Two properties are tested, and they fail for different reasons:

1. **Built-in parity** — the six built-ins must estimate *identically*.
   These are calibrated numbers; moving one silently is how an admission
   decision changes without anyone deciding to change it.
2. **Generated models get the property, not the fallback** — a plugin that
   genuinely has attention, or genuinely is a regressor, must be treated as
   such without being named.

``tests/unit/guardrails/test_no_model_name_branches.py`` is the companion:
it fails if a name branch comes back. It does not check that the
*replacement* is correct, which is what this module is for.
"""

from __future__ import annotations

import pytest

from agent.skills.training_skill.estimator import attention_shape

_BUILTINS = ("punet", "fcnet", "transformer", "wavenet", "rnn", "gated_fno")


class TestAttentionPredicate:
    """``attention_shape`` replaces ``if model_type == "transformer"``."""

    def test_only_the_attention_builtin_is_charged_for_attention(self):
        """Exactly one built-in has attention, and it is found by property.

        Hardcoded expectation rather than derived from the registry: reading
        the answer out of the thing under test would pass for any answer.
        """
        charged = {mt for mt in _BUILTINS if attention_shape(mt, {}) is not None}
        assert charged == {"transformer"}

    def test_builtin_attention_comes_from_the_declaration(self):
        """Pins the fallback at ``(4, 2)`` — the declared value. **FU-C-1.**

        **Updated by V21 PR B1, not deleted.** C3 wrote this to pin the
        defect at ``(2, 2)``: ``TransformerConfig`` declares ``nhead=4``,
        so ``.get("nhead", 2)`` under-counted attention memory by 2x
        whenever the caller's dict omitted the key. C3 preserved the wrong
        value deliberately, because changing a calibrated built-in estimate
        needed operator approval. Q-B-2 granted it, and B1 made the value
        come from the declaration.

        The guard survives the fix because the defect it protects against
        is *drift*, not any one number: it now fails if the resolution
        stops consulting ``TransformerConfig``, or regresses to the old
        literal, or lands on some third value.
        """
        from ml_models.models_format_sandbox import get_config_class

        assert attention_shape("transformer", {}) == (4, 2)

        # ...and (4, 2) is not a second hardcoded literal: it is what the
        # config class declares. A test asserting only the tuple would pass
        # if someone re-hardcoded it and the class later changed.
        declared = get_config_class("transformer").model_fields
        assert (declared["nhead"].default, declared["num_layers"].default) == (4, 2)

    def test_an_absent_key_estimates_exactly_as_the_declared_value_does(self):
        """B1's central property: omission must not change the forecast.

        Before B1 the same function resolved one absent key two ways —
        ``_count_params`` instantiated the model through Pydantic (getting
        the class default) while the step count used a literal. So a plan
        that simply left ``segmentation_size`` out was priced for a model
        nobody would run.

        Fails if: any estimator input reverts to a literal that disagrees
        with the declaration.
        """
        from agent.skills.inference_skill.estimator import (
            estimate_wall_time_seconds as inf_time,
        )
        from agent.skills.training_skill.estimator import (
            estimate_wall_time_seconds as train_time,
        )
        from ml_models.models_format_sandbox import get_config_class

        sample = {"0": list(range(20)), "1": list(range(20))}
        for mt in _BUILTINS:
            declared = get_config_class(mt).model_fields["segmentation_size"].default
            explicit = {"segmentation_size": declared}
            tc = {"batch_size": 1, "epochs": 1}

            absent_t = train_time(mt, {}, tc, sample, ms_per_step=44.3, num_params=10**6)
            explicit_t = train_time(mt, explicit, tc, sample, ms_per_step=44.3, num_params=10**6)
            assert absent_t["seconds"] == explicit_t["seconds"], mt

            absent_i = inf_time(mt, {}, sample, inference_ms_per_step=1.0, num_params=10**6)
            explicit_i = inf_time(mt, explicit, sample, inference_ms_per_step=1.0, num_params=10**6)
            assert absent_i["seconds"] == explicit_i["seconds"], mt

    def test_an_absent_epochs_is_priced_at_what_will_actually_run(self):
        """The one ACTIVE optimistic defect B1 closes.

        ``TrainConfig`` declares ``epochs=10`` and the trainer builds
        ``TrainConfig(**train_config)``, so an omitted key runs **ten**
        epochs. The estimator priced **one** — linear in epochs with
        nothing to cancel it, so a 10x optimistic forecast feeding
        ``skipped_time_risk`` and the formal time budget.

        Fails if: the fallback returns to ``1``, or stops consulting
        ``TrainConfig``.
        """
        from agent.skills.training_skill.estimator import estimate_wall_time_seconds
        from ml_models.models_format_sandbox import TrainConfig

        sample = {"0": list(range(20))}
        declared = TrainConfig.model_fields["epochs"].default
        assert declared == 10

        absent = estimate_wall_time_seconds(
            "punet", {}, {"batch_size": 1}, sample, ms_per_step=10.0, num_params=10**6
        )
        explicit = estimate_wall_time_seconds(
            "punet",
            {},
            {"batch_size": 1, "epochs": declared},
            sample,
            ms_per_step=10.0,
            num_params=10**6,
        )
        assert absent["seconds"] == explicit["seconds"]

        one = estimate_wall_time_seconds(
            "punet", {}, {"batch_size": 1, "epochs": 1}, sample, ms_per_step=10.0, num_params=10**6
        )
        assert absent["seconds"] == 10 * one["seconds"]

    def test_caller_supplied_values_win_over_the_fallback(self):
        assert attention_shape("transformer", {"nhead": 8, "num_layers": 6}) == (8, 6)

    def test_a_generated_attention_model_is_charged_without_being_named(self):
        """The reachability property, stated positively.

        Before C3 an agent-invented attention model received a **zero**
        attention term purely for not being named ``"transformer"``. Zero is
        the *optimistic* direction: the candidate looks cheaper than it is,
        gets admitted, and OOMs during training.

        A model is charged here on the strength of its own config declaring
        attention parameters — no registration and no name required.
        """
        assert attention_shape("some_invented_attention_net", {"nhead": 4}) == (4, 2)

    def test_a_generated_model_without_attention_is_not_charged(self):
        """The converse: no attention declared, no attention term.

        Guards against the lazy over-fix of charging every unregistered
        model for attention, which would inflate estimates and cause
        spurious ``skipped_time_risk`` rejections.
        """
        assert attention_shape("some_invented_conv_net", {"channels": 32}) is None


class TestOutputContractPredicate:
    """``_output_contract`` replaces ``if model_type == "fcnet"``."""

    def test_builtin_contracts_are_resolved_by_declaration(self):
        from agent.skills.training_skill.estimator import _output_contract

        assert {mt: _output_contract(mt) for mt in _BUILTINS} == {
            "punet": "classifier",
            "fcnet": "hybrid",
            "transformer": "classifier",
            "wavenet": "classifier",
            "rnn": "classifier",
            "gated_fno": "classifier",
        }

    def test_only_the_hybrid_builtin_gets_the_single_activation_factor(self):
        """The property the deleted ``fcnet`` branch actually encoded.

        ``act_factor`` is 1 for the hybrid contract and 2 otherwise. Asserted
        through the public estimate so this tracks what production computes,
        not a private helper that could drift away from it.
        """
        from agent.skills.training_skill.estimator import estimate_peak_bytes

        def activations(model_type):
            got = estimate_peak_bytes(
                model_type, {"segmentation_size": 1000}, {"batch_size": 1}, {"loss_type": "ce"}, 10
            )
            return got["breakdown"]["activations_bytes"], got["breakdown"]["output_logits_bytes"]

        hybrid_act, hybrid_out = activations("fcnet")
        classifier_act, classifier_out = activations("punet")
        assert hybrid_act == hybrid_out  # 1x
        assert classifier_act == 2 * classifier_out  # 2x

    def test_an_unresolvable_model_is_estimated_conservatively_not_refused(self):
        """Planning-time lookups must not fail closed the way execution does.

        Estimators run for models that are not registered yet (proposer-side
        pre-flight). C1 made ``get_output_type`` raise, so without a guard
        here a *missing* estimate would become a *rejected* candidate.

        The fallback is the classifier contract: identical to pre-C3
        behaviour and the memory-heavier of the two, so an unknown model is
        over-estimated rather than under-estimated.
        """
        from agent.skills.training_skill.estimator import _output_contract

        assert _output_contract("model_that_is_not_registered_anywhere") == "classifier"


class TestConstructorIntrospection:
    """``_instantiate_for_param_count`` replaces ``if model_type == "fcnet"``."""

    def test_loss_type_is_passed_only_to_classes_that_accept_it(self):
        """A real constructor API difference, detected by signature.

        ``fcnet``'s class takes ``loss_type`` because its head shape depends
        on it. Every other built-in, and every generated plugin (whose
        contract is ``__init__(self, config)``), takes the one-argument form.

        Fails if: the introspection is replaced by a name check, or inverted
        so plugins are handed an argument they cannot accept.
        """
        import inspect

        from ml_models.models_sandbox import MODEL_REGISTRY

        accepts = {
            mt
            for mt in _BUILTINS
            if "loss_type" in inspect.signature(MODEL_REGISTRY[mt].__init__).parameters
        }
        assert accepts == {"fcnet"}

    @pytest.mark.parametrize("model_type", _BUILTINS)
    def test_every_builtin_still_instantiates_for_a_param_count(self, model_type):
        """Reachability: the helper is exercised on all six, not just fcnet."""
        from agent.skills.training_skill.estimator import _count_params

        assert _count_params(model_type, {"segmentation_size": 1000}, loss_type="ce") > 0
