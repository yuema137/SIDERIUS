"""V21 PR B1 — estimator inputs resolve the way the RUN will resolve them.

The defect class B1 closes is narrow and easy to restate: a resource
estimator substituted a hardcoded literal for an absent config key while
the production run substituted the **config class default** for the same
absent key. The forecast therefore described a model nobody would run.

The proof that the class default is canonical is internal to the
estimator — ``estimate_wall_time_seconds`` calls ``_count_params`` →
``config_cls(**model_config)``, so Pydantic already resolved that same
absent key one line away from where ``.get()`` resolved it differently.

    counted at  segmentation_size = 40000   (Pydantic)
    priced at   segmentation_size = 1000    (the literal)

``test_estimator_predicates_not_names.py`` is C3's module and guards a
different property — that behaviour keys on model *properties*, not
model *names*. This one guards the *values*. Both must hold: C3 made the
question truthful, B1 makes the answer truthful.

Design doc: ``docs/design/v21_priorities/pr_b_resource_budget_semantics.md``
§0.6 (the reachability audit) and Commit B1.
"""

from __future__ import annotations

import pytest

from agent.skills.training_skill.estimator import (
    resolve_model_field,
    resolve_train_field,
)
from execute_tools.dataset_config import TIDMAD_PROFILE

_UNDECLARED = "b1_generated_model_declaring_nothing"


class TestResolutionOrder:
    def test_an_explicit_value_wins_over_the_declaration(self):
        assert resolve_model_field("transformer", {"nhead": 8}, "nhead", safety_margin=2) == 8

    def test_an_explicit_value_equal_to_the_declaration_is_honoured(self):
        """The outcome must be identical, but not *because* of a coincidence.

        The edge case the design named: an explicit value that happens to
        equal the default must not take a different path from an explicit
        value that differs. Asserted by giving the same field both
        treatments and requiring the same answer.
        """
        explicit = resolve_model_field("transformer", {"nhead": 4}, "nhead", safety_margin=2)
        absent = resolve_model_field("transformer", {}, "nhead", safety_margin=2)
        assert explicit == absent == 4

    def test_an_absent_key_falls_to_the_declared_default(self):
        assert resolve_model_field("punet", {}, "segmentation_size", safety_margin=1000) == 40000
        assert (
            resolve_model_field("transformer", {}, "segmentation_size", safety_margin=1000) == 20000
        )

    def test_the_margin_is_reached_only_when_nothing_declares_the_field(self):
        """An unregistered model has no declaration to consult.

        ``get_config_class`` returns ``None``; the margin is the honest
        answer and is documented as a margin, never as "the model
        default".
        """
        assert resolve_model_field(_UNDECLARED, {}, "segmentation_size", safety_margin=1000) == 1000
        assert (
            resolve_model_field(_UNDECLARED, {}, "segmentation_size", safety_margin=40000) == 40000
        )

    def test_a_registered_model_that_declares_no_such_field_gets_the_margin(self):
        """``punet`` declares ``segmentation_size`` but not ``nhead``."""
        assert resolve_model_field("punet", {}, "nhead", safety_margin=2) == 2

    def test_train_fields_resolve_against_TrainConfig(self):
        from ml_models.models_format_sandbox import TrainConfig

        assert resolve_train_field({}, "epochs", safety_margin=1) == 10
        assert TrainConfig.model_fields["epochs"].default == 10
        assert resolve_train_field({"epochs": 3}, "epochs", safety_margin=1) == 3


class TestLossType:
    """The last member of the defect class, found by the §22 final audit.

    ``LossConfig`` declares ``"focal"``; every estimator substituted
    ``"ce"``. Unlike the VRAM sites this one is **reachable**: the warm-up
    builds the real criterion and the real model from it, and ``fcnet``'s
    head shape depends on it, so both the measured ms/step and the
    parameter count were taken for a configuration the run would not use.
    """

    def test_an_absent_loss_type_resolves_to_the_declared_default(self):
        from agent.skills.training_skill.estimator import resolve_loss_type
        from ml_models.models_format_sandbox import LossConfig

        assert LossConfig.model_fields["loss_type"].default == "focal"
        assert resolve_loss_type({}) == "focal"
        assert resolve_loss_type({"loss_type": None}) == "focal"
        assert resolve_loss_type({"loss_type": ""}) == "focal"

    def test_the_local_literal_matches_LossConfigs_declaration(self):
        """The estimator restates the legal set; it must not drift from it.

        ``LossTypeName`` is declared in the estimator rather than imported,
        to keep the module's lazy-import discipline. That is a duplicated
        fact, so it needs the test that duplication always needs — the
        alternative is a loss the schema accepts and the resolver silently
        rejects into the ``"ce"`` margin.
        """
        from typing import get_args

        from agent.skills.training_skill.estimator import _LEGAL_LOSS_TYPES
        from ml_models.models_format_sandbox import LossConfig

        declared = LossConfig.model_fields["loss_type"].annotation
        assert set(_LEGAL_LOSS_TYPES) == set(get_args(declared))

    def test_an_explicit_loss_type_wins(self):
        from agent.skills.training_skill.estimator import resolve_loss_type

        assert resolve_loss_type({"loss_type": "ce"}) == "ce"
        assert resolve_loss_type({"loss_type": "smooth_l1"}) == "smooth_l1"

    def test_the_correction_is_the_conservative_direction(self):
        """``focal`` adds the one-hot term that ``ce`` omits.

        Asserted through the public estimate, so it tracks what production
        computes rather than a private helper.
        """
        from agent.skills.training_skill.estimator import estimate_peak_bytes

        absent = estimate_peak_bytes("punet", {}, {"batch_size": 1}, {}, 10**6)
        as_ce = estimate_peak_bytes("punet", {}, {"batch_size": 1}, {"loss_type": "ce"}, 10**6)
        assert absent["breakdown"]["focal_onehot_bytes"] > 0
        assert as_ce["breakdown"]["focal_onehot_bytes"] == 0
        assert absent["total_bytes"] > as_ce["total_bytes"]

    def test_every_estimator_entry_point_resolves_it_the_same_way(self):
        """Reachability across all four sites, by source.

        A per-site literal is exactly how the 40000/1000/0 split for
        ``segmentation_size`` arose; this fails if one site drifts back.
        """
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[3]
        for rel in (
            "agent/skills/training_skill/estimator.py",
            "agent/skills/evaluate_time_skill/wrapper.py",
            "agent/utils/proposer_preflight.py",
        ):
            text = (repo / rel).read_text(encoding="utf-8")
            assert 'loss_config.get("loss_type", "ce")' not in text, (
                f"{rel} still substitutes 'ce' for an absent loss_type, which "
                "contradicts LossConfig's declared 'focal'"
            )


class TestUnusableValues:
    """Invalid input must not silently become the margin, and must not crash.

    Every field this resolver serves is declared ``ge=1``, so a
    non-positive value cannot train — the candidate will be rejected by
    Pydantic later. What the estimator must not do is price it: the old
    ``model_config.get("nhead") or 2`` turned ``0`` into ``2`` silently,
    and a bare ``.get`` would have returned ``0`` and zeroed the whole
    attention term, which is the optimistic direction.
    """

    @pytest.mark.parametrize("bad", [0, -1, None])
    def test_an_unusable_value_falls_to_the_declaration_not_the_margin(self, bad):
        assert resolve_model_field("transformer", {"nhead": bad}, "nhead", safety_margin=99) == 4

    @pytest.mark.parametrize("bad", [0, -1, None])
    def test_an_unusable_value_with_no_declaration_reaches_the_margin(self, bad):
        assert resolve_model_field(_UNDECLARED, {"nhead": bad}, "nhead", safety_margin=7) == 7

    def test_an_unregistered_model_never_raises(self):
        """Planning-time lookups must not fail closed.

        C3 established the precedent for ``_output_contract``: estimators
        run for models that are not registered yet, so a *refused*
        estimate becomes a *rejected* candidate. The same applies here.
        """
        assert resolve_model_field(_UNDECLARED, {}, "anything_at_all", safety_margin=5) == 5

    def test_a_boolean_is_not_treated_as_a_number(self):
        """``True`` is an ``int`` in Python; it is not a segmentation size.

        Guards the ``isinstance(value, int)`` shortcut, which would let
        ``True`` through as ``1``.
        """
        assert (
            resolve_model_field(
                "punet", {"segmentation_size": True}, "segmentation_size", safety_margin=1
            )
            == 1
        )


class TestPhaseMarginsDifferDeliberately:
    """The two phases pass opposite margins, and that is not an inconsistency.

    The approved design originally required the VRAM and wall-time paths
    to agree on one literal so "the 40x split cannot return". B1's audit
    showed that criterion is unsafe as stated: memory is conservative
    when ``seg`` is over-stated and wall time when it is under-stated, so
    forcing one value necessarily makes one phase more optimistic. See
    the design doc §0.6.7.

    What the paths must agree on is the **canonical value**, which they
    now do for every model that declares the field. The margins differ
    only where no declaration exists.
    """

    def test_the_paths_agree_wherever_a_declaration_exists(self):
        from agent.skills.inference_skill import estimator as inf
        from agent.skills.training_skill import estimator as train

        sample = {"0": list(range(20))}
        for mt in ("punet", "fcnet", "transformer", "wavenet", "rnn", "gated_fno"):
            vram = train.estimate_peak_bytes(mt, {}, {"batch_size": 1}, {"loss_type": "ce"}, 10**6)
            time = train.estimate_wall_time_seconds(
                mt,
                {},
                {"batch_size": 1, "epochs": 1},
                sample,
                ms_per_step=1.0,
                num_params=10**6,
                dataset_profile=TIDMAD_PROFILE,
            )
            # Both resolved the same field; recover each one's view of it.
            declared = resolve_model_field(mt, {}, "segmentation_size", safety_margin=-1)
            assert declared > 0, mt
            # VRAM output_logits = batch * 256 * seg * 4  ->  seg is recoverable
            assert vram["breakdown"]["output_logits_bytes"] == 1 * 256 * declared * 4, mt
            # inference agrees too
            inf_est = inf.estimate_peak_bytes(mt, {}, 10**6)
            batch = inf_est["breakdown"]["inference_batch"]
            assert inf_est["breakdown"]["output_logits_bytes"] == batch * 256 * declared * 4, mt
            assert time["seconds"] > 0, mt

    def test_the_margins_are_opposite_and_that_is_the_point(self):
        """Undeclared model: memory margin high, time margin low."""
        from agent.skills.inference_skill import estimator as inf
        from agent.skills.training_skill import estimator as train

        vram_seg = resolve_model_field(_UNDECLARED, {}, "segmentation_size", safety_margin=40000)
        time_seg = resolve_model_field(_UNDECLARED, {}, "segmentation_size", safety_margin=1000)
        assert vram_seg > time_seg

        # And the production call sites really pass those margins.
        est = train.estimate_peak_bytes(_UNDECLARED, {}, {"batch_size": 1}, {"loss_type": "ce"}, 1)
        assert est["breakdown"]["output_logits_bytes"] == 1 * 256 * 40000 * 4
        inf_est = inf.estimate_peak_bytes(_UNDECLARED, {}, 1)
        batch = inf_est["breakdown"]["inference_batch"]
        assert inf_est["breakdown"]["output_logits_bytes"] == batch * 256 * 40000 * 4


class TestGeneratedPluginDeclarations:
    """A generated model's OWN declaration must be consulted, not a literal.

    Added after mutation **M2** survived. Every built-in that declares
    ``num_layers`` declares it as ``2``, which is also the safety margin,
    so reverting that site to the old literal was undetectable across the
    whole built-in matrix — the mutation was *equivalent for built-ins*
    and a real gap for everything else.

    "Everything else" is exactly PR C's constituency: an agent-invented
    attention model. Its config class is the only source of truth for its
    depth, and a literal ``2`` would under-count a 6-layer model's
    attention memory by 3x.
    """

    @staticmethod
    def _register(monkeypatch, name, **fields):
        import pydantic

        import ml_models.models_format_sandbox as mfs

        cls = pydantic.create_model(
            "GeneratedAttentionConfig",
            **{k: (int, pydantic.Field(default=v)) for k, v in fields.items()},
        )
        monkeypatch.setitem(mfs.PLUGIN_CONFIG_REGISTRY, name, cls)
        return cls

    def test_a_generated_attention_plugin_uses_its_declared_depth(self, monkeypatch):
        from agent.skills.training_skill.estimator import attention_shape

        name = "b1_generated_deep_attention_net"
        self._register(monkeypatch, name, nhead=8, num_layers=6, segmentation_size=4000)

        # Not (8, 2) and emphatically not (2, 2): both numbers come from the
        # plugin's own declaration.
        assert attention_shape(name, {}) == (8, 6)

    def test_an_explicit_dict_still_overrides_the_plugin_declaration(self, monkeypatch):
        from agent.skills.training_skill.estimator import attention_shape

        name = "b1_generated_deep_attention_net_2"
        self._register(monkeypatch, name, nhead=8, num_layers=6)
        assert attention_shape(name, {"nhead": 3, "num_layers": 4}) == (3, 4)

    def test_the_declared_depth_reaches_the_attention_term(self, monkeypatch):
        """Reachability: the estimate, not just the helper.

        Charging 6 layers instead of 2 triples the attention term, which
        is the whole point of consulting the declaration.
        """
        from agent.skills.training_skill.estimator import estimate_peak_bytes

        shallow = "b1_gen_attn_shallow"
        deep = "b1_gen_attn_deep"
        self._register(monkeypatch, shallow, nhead=8, num_layers=2, segmentation_size=4000)
        self._register(monkeypatch, deep, nhead=8, num_layers=6, segmentation_size=4000)

        def attn(mt):
            got = estimate_peak_bytes(mt, {}, {"batch_size": 1}, {"loss_type": "ce"}, 1)
            return got["breakdown"]["transformer_attn_bytes"]

        assert attn(deep) == 3 * attn(shallow)


class TestProductionReachability:
    """The aggregator that production actually calls must use the resolver.

    PR A's lesson, restated by the mandate: a correct helper existing in
    source is not evidence that production reaches it. These drive
    ``evaluate_time_skill.run_skill`` — the entry point the tuner calls —
    rather than the estimator directly.

    Fails if: the wrapper or either estimator reverts to a literal.
    """

    @staticmethod
    def _run(monkeypatch, model_config):
        from agent.skills.evaluate_time_skill import wrapper as ts

        monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: 1_000_000)

        class FakeSandbox:
            pass

        return ts.run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config=model_config,
            train_config={"batch_size": 1, "epochs": 1, "device": "cpu"},
            loss_config={"loss_type": "focal"},
            sample_set={str(i): list(range(20)) for i in range(20)},
            train_portion=1.0,
            time_budget_minutes=60.0,
            dataset_profile=TIDMAD_PROFILE,
        )

    def test_an_absent_segmentation_size_is_priced_as_the_declaration(self, monkeypatch):
        from ml_models.models_format_sandbox import get_config_class

        declared = get_config_class("rnn").model_fields["segmentation_size"].default
        absent = self._run(monkeypatch, {})
        explicit = self._run(monkeypatch, {"segmentation_size": declared})
        assert absent["estimated_minutes"] == explicit["estimated_minutes"]
        assert (
            absent["breakdown"]["total_train_steps"] == explicit["breakdown"]["total_train_steps"]
        )

    def test_the_wrapper_does_not_price_it_at_the_old_literal(self, monkeypatch):
        """The specific regression: ``1000`` is not ``rnn``'s declaration.

        Asserted on the **step count**, not on estimated minutes. In the
        static path the two cancel exactly — ``total_steps ∝ 1/seg`` and
        ``_static_ms_per_step ∝ seg`` — so 40000 and 1000 yield the same
        minutes (100,000 × 120 ms == 4,000,000 × 3 ms) while describing
        completely different runs. That cancellation is precisely why
        §0.6.3 found this site neutral rather than optimistic, and why an
        assertion on minutes here would have passed for the wrong reason.

        The step count is the resolved fact, and it is the number that
        reaches the observation-store key and the RT1 workload resolver.
        """
        absent = self._run(monkeypatch, {})
        old_literal = self._run(monkeypatch, {"segmentation_size": 1000})
        assert (
            absent["breakdown"]["total_train_steps"]
            != old_literal["breakdown"]["total_train_steps"]
        )
        assert absent["breakdown"]["total_train_steps"] == 100_000
        assert old_literal["breakdown"]["total_train_steps"] == 4_000_000

    def test_the_store_calibration_key_is_built_from_the_declaration(self, monkeypatch):
        """Added after mutation **M9** survived.

        The wrapper's ``seg_size`` local does not feed the returned
        estimate at all — the estimators resolve the dict themselves — so
        reverting it to the old literal changed no number any earlier test
        looked at. What it *does* feed is the observation-store
        calibration key, and a run whose model really runs at 40000
        reading a bucket labelled 1000 mixes incomparable measurements
        (design doc §0.6.5b).

        This asserts the value the wrapper hands to the key builder.
        """
        from agent.skills.evaluate_time_skill import wrapper as ts
        from ml_models.models_format_sandbox import get_config_class

        monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: 1_000_000)
        seen = {}

        def capture(**kwargs):
            seen.update(kwargs)
            return None, None, None

        monkeypatch.setattr(ts, "_store_reuse_decision", capture)

        class FakeSandbox:
            pass

        ts.run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config={},  # segmentation_size ABSENT
            train_config={"batch_size": 1, "device": "cpu"},  # epochs ABSENT
            loss_config={"loss_type": "focal"},
            sample_set={str(i): list(range(20)) for i in range(20)},
            train_portion=1.0,
            time_budget_minutes=60.0,
            allow_store_reuse=True,
            observation_store_root="/nonexistent-store-root-for-this-test",
            dataset_profile=TIDMAD_PROFILE,
        )

        declared = get_config_class("rnn").model_fields["segmentation_size"].default
        assert seen["seg_size"] == declared
        assert seen["seg_size"] != 1000

    def test_the_store_reuse_step_count_uses_the_declared_epochs(self, monkeypatch, tmp_path):
        """Added after mutation **M8** survived.

        ``_store_reuse_decision`` recomputes the workload itself, so the
        estimator's corrected ``epochs`` does not reach it. Its own
        literal had to be corrected separately, and needs its own test:
        the trigger policy decides whether to skip a warm-up based on this
        step count, so a 10x-low count is a 10x-low sense of how much work
        is at stake.
        """
        from agent.skills.evaluate_time_skill import trigger_policy
        from agent.skills.evaluate_time_skill import wrapper as ts

        seen = {}

        def capture(**kwargs):
            seen.update(kwargs)
            return None

        monkeypatch.setattr(trigger_policy, "decide_nonformal_estimation", capture)

        sample = {str(i): list(range(20)) for i in range(20)}
        common = dict(
            store_root=str(tmp_path / "store"),
            model_type="rnn",
            sample_set=sample,
            train_portion=1.0,
            seg_size=40000,
            batch_size=1,
            num_params=1_000_000,
            gpu_name=None,
        )
        ts._store_reuse_decision(train_config={"batch_size": 1}, **common, profile=TIDMAD_PROFILE)
        absent = seen.get("n_steps")

        seen.clear()
        ts._store_reuse_decision(
            train_config={"batch_size": 1, "epochs": 10}, **common, profile=TIDMAD_PROFILE
        )
        ten = seen.get("n_steps")

        seen.clear()
        ts._store_reuse_decision(
            train_config={"batch_size": 1, "epochs": 1}, **common, profile=TIDMAD_PROFILE
        )
        one = seen.get("n_steps")

        assert absent is not None, "the trigger policy was never reached"
        assert absent == ten
        assert absent == 10 * one

    def test_the_operator_banner_reports_what_will_actually_run(self, monkeypatch, capsys):
        """Added after mutation **M10** survived.

        This one is observability-only — the wrapper's ``epochs`` local
        reaches nothing but the banner. It is still worth pinning: the
        printed line is the operator's map, and a banner reading
        ``epochs=1`` for a run that will do ten is precisely the kind of
        quiet mis-report that made the V20 post-mortems expensive.

        Classified honestly: this guards a LOG, not a decision.
        """
        from agent.skills.evaluate_time_skill import wrapper as ts

        monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: 1_000_000)

        class FakeSandbox:
            pass

        ts.run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config={},
            train_config={"batch_size": 1, "device": "cpu"},
            loss_config={"loss_type": "focal"},
            sample_set={str(i): list(range(20)) for i in range(20)},
            train_portion=1.0,
            time_budget_minutes=60.0,
            dataset_profile=TIDMAD_PROFILE,
        )
        banner = capsys.readouterr().out
        assert "epochs=10" in banner
        assert "seg=40000" in banner

    def test_an_absent_epochs_is_priced_at_ten_not_one(self, monkeypatch):
        """Reachability for the one ACTIVE optimistic defect.

        Driven through the aggregator so this fails if the wrapper stops
        forwarding the resolved value, not only if the estimator does.
        """
        from agent.skills.evaluate_time_skill import wrapper as ts

        monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: 1_000_000)

        class FakeSandbox:
            pass

        def run(train_config):
            return ts.run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config={"segmentation_size": 16000},
                train_config=train_config,
                loss_config={"loss_type": "focal"},
                sample_set={str(i): list(range(20)) for i in range(20)},
                train_portion=1.0,
                time_budget_minutes=60.0,
                dataset_profile=TIDMAD_PROFILE,
            )

        absent = run({"batch_size": 1, "device": "cpu"})
        ten = run({"batch_size": 1, "epochs": 10, "device": "cpu"})
        one = run({"batch_size": 1, "epochs": 1, "device": "cpu"})

        assert absent["estimated_minutes"] == ten["estimated_minutes"]
        assert absent["estimated_minutes"] != one["estimated_minutes"]
