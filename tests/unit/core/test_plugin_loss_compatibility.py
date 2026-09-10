"""Model/loss compatibility must govern the GENERATED-PLUGIN branch too.

V21 PR A2b. ``TidmadSandbox._validate_configs`` branches on registration:

    if model_type in PLUGIN_CONFIG_REGISTRY:   # generated models
        ... validate plugin config + TrainConfig + LossConfig
        return                                  # <- used to stop here
    exp_config = ExperimentConfig(**payload)    # built-ins only

``ExperimentConfig`` carries the compatibility rule, so before A2b the only
kind of model the agent actually invents was governed by **no** compatibility
rule at all. Verified on 2026-08-07 against the live registry: a registered
plugin declaring ``classifier`` paired with ``smooth_l1`` was ACCEPTED, and
failed later, deep in the loss, where a float32 ``[B, T]`` target meets a
``[B, 256, T]`` prediction.

MUTATION TARGET: remove the ``validate_output_loss_compatibility`` call from
the plugin branch of ``_validate_configs`` and every ``REFUSE`` case below
turns green — i.e. the tests stop failing because nothing refuses. That is the
proof the rule is actually delivered to this consumer, not merely defined.

These tests call the real production method (via ``__new__`` so no workspace
is created); they do not re-implement the branch.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.sandbox_executor import TidmadSandbox
from ml_models import plugin_loader
from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY

pytestmark = pytest.mark.usefixtures("synthetic_task_config")

CLASSIFICATION_LOSSES = ["ce", "focal", "focal_cw"]


class _FakePluginConfig(BaseModel):
    """Stand-in for an agent-generated plugin's PLUGIN_CONFIG_CLASS."""

    depth: int = 2


@pytest.fixture
def registered_plugin(monkeypatch):
    """Register a generated-style plugin under a chosen output contract.

    Mirrors what ``plugin_loader`` does at runtime: the config class lands in
    PLUGIN_CONFIG_REGISTRY and the declared contract in
    PLUGIN_OUTPUT_TYPE_REGISTRY.
    """

    def _register(output_type: str, name: str = "gen_probe_model") -> str:
        monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, name, _FakePluginConfig)
        monkeypatch.setitem(plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY, name, output_type)
        return name

    return _register


def _validate(model_type: str, loss_type: str):
    """Invoke the real production validator on the plugin branch."""
    loss_cfg: dict = {"loss_type": loss_type}
    if loss_type == "custom":
        # LossConfig.enforce_custom_loss_name requires this; unrelated to
        # output/loss compatibility but part of a well-formed custom config.
        loss_cfg["loss_name"] = "snr_weighted_mse"
    executor = TidmadSandbox.__new__(TidmadSandbox)  # no workspace needed
    return TidmadSandbox._validate_configs(
        executor,
        model_type,
        {"depth": 2},
        {"lr": 5e-4, "epochs": 1, "batch_size": 2},
        loss_cfg,
        "exp-compat",
        "run-compat",
    )


class TestGeneratedPluginLossCompatibility:
    def test_classifier_plugin_accepts_classification_losses(self, registered_plugin):
        name = registered_plugin("classifier")
        for loss in CLASSIFICATION_LOSSES:
            m, _t, loss_cfg = _validate(name, loss)
            assert m["model_type"] == name
            assert loss_cfg["loss_type"] == loss

    def test_classifier_plugin_refuses_smooth_l1(self, registered_plugin):
        """The case that was silently accepted before A2b."""
        name = registered_plugin("classifier")
        with pytest.raises(ValueError) as exc:
            _validate(name, "smooth_l1")
        # refused at CONFIG VALIDATION, not later in training
        assert "Plugin Experiment Configuration Rejected" in str(exc.value)
        assert "classifier" in str(exc.value)

    def test_regressor_plugin_accepts_smooth_l1(self, registered_plugin):
        name = registered_plugin("regressor")
        _m, _t, loss_cfg = _validate(name, "smooth_l1")
        assert loss_cfg["loss_type"] == "smooth_l1"

    @pytest.mark.parametrize("loss", CLASSIFICATION_LOSSES)
    def test_regressor_plugin_refuses_classification_losses(self, registered_plugin, loss):
        name = registered_plugin("regressor")
        with pytest.raises(ValueError) as exc:
            _validate(name, loss)
        assert "Plugin Experiment Configuration Rejected" in str(exc.value)
        assert "regressor" in str(exc.value)

    def test_custom_loss_still_defers_to_the_plugin(self, registered_plugin):
        """``custom`` is in neither loss family and must remain permitted for
        both contracts — the plugin's own forward raises at training time if
        its shape contract is violated."""
        for output_type in ("classifier", "regressor"):
            name = registered_plugin(output_type, name=f"gen_custom_{output_type}")
            _m, _t, loss_cfg = _validate(name, "custom")
            assert loss_cfg["loss_type"] == "custom"


class TestBothBranchesShareOneAuthority:
    """The rule must be one function with two consumers, not two rules.

    A1 deleted a second, contradictory compatibility rule. This test fails if
    someone re-inlines the pair logic into the executor instead of calling the
    shared authority.
    """

    def test_executor_does_not_reimplement_the_rule(self):
        """Comments and docstrings are stripped before scanning.

        Documenting *why* the rule lives elsewhere necessarily mentions the
        loss names; only EXECUTABLE code is checked, mirroring
        ``tests/unit/guardrails/test_runtime_authority_audit.py``.
        """
        import inspect
        import io
        import tokenize

        src = inspect.getsource(TidmadSandbox._validate_configs)
        assert "validate_output_loss_compatibility" in src, (
            "the plugin branch must call the shared authority"
        )

        code_only = "".join(
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        )
        # No inlined loss-family literals — those belong to the shared rule.
        assert "focal_cw" not in code_only
        assert "smooth_l1" not in code_only

    def test_builtin_and_plugin_paths_agree_on_the_same_pair(self, registered_plugin):
        """A classifier + smooth_l1 must be refused on BOTH branches."""
        from ml_models.models_format_sandbox import ExperimentConfig

        # built-in branch (wavenet is a classifier)
        with pytest.raises(ValueError):
            ExperimentConfig(
                exp_id="e",
                run_name="r",
                model_type="wavenet",
                network_config={"model_type": "wavenet"},
                train_config={"lr": 5e-4, "epochs": 1, "batch_size": 2},
                loss_config={"loss_type": "smooth_l1"},
            )

        # generated-plugin branch
        name = registered_plugin("classifier", name="gen_parity_model")
        with pytest.raises(ValueError):
            _validate(name, "smooth_l1")
