"""
Tests for ml_models/loss_models_sandbox.py

Verifies that all loss functions compute correctly on synthetic tensors
and that get_criterion instantiates the right class for each loss_type.
"""

import shutil
import sys
from pathlib import Path

import pytest
import torch
from pydantic import ValidationError

from ml_models.loss_models_sandbox import FocalLoss1D, FocalLoss1DCW, get_criterion
from ml_models.models_format_sandbox import LossConfig

# ==========================================
# Shared fixtures
# ==========================================

BATCH = 2
NUM_CLASSES = 256
SEQ_LEN = 1000


@pytest.fixture
def classification_inputs():
    """Synthetic logits: [Batch, NumClasses, SeqLen]"""
    torch.manual_seed(0)
    return torch.randn(BATCH, NUM_CLASSES, SEQ_LEN)


@pytest.fixture
def classification_targets():
    """Synthetic discrete targets: [Batch, SeqLen], values in [0, 255]"""
    torch.manual_seed(0)
    return torch.randint(0, NUM_CLASSES, (BATCH, SEQ_LEN))


@pytest.fixture
def regression_inputs():
    """Synthetic regression output: [Batch, SeqLen]"""
    torch.manual_seed(0)
    return torch.randn(BATCH, SEQ_LEN)


@pytest.fixture
def regression_targets():
    """Synthetic regression targets: [Batch, SeqLen]"""
    torch.manual_seed(0)
    return torch.randn(BATCH, SEQ_LEN)


@pytest.fixture
def class_weights():
    """Synthetic per-class weights: [NumClasses]"""
    return torch.ones(NUM_CLASSES) / NUM_CLASSES


# ==========================================
# FocalLoss1D
# ==========================================


class TestFocalLoss1D:
    def test_output_is_scalar(self, classification_inputs, classification_targets):
        cfg = LossConfig(loss_type="focal")
        loss_fn = FocalLoss1D(cfg)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.shape == torch.Size([])

    def test_output_is_non_negative(self, classification_inputs, classification_targets):
        cfg = LossConfig(loss_type="focal")
        loss_fn = FocalLoss1D(cfg)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_perfect_prediction_lower_than_random(self, classification_targets):
        """Loss on near-perfect logits should be lower than on random logits."""
        cfg = LossConfig(loss_type="focal")
        loss_fn = FocalLoss1D(cfg)

        # Near-perfect: high logit on the correct class
        perfect_logits = torch.full((BATCH, NUM_CLASSES, SEQ_LEN), -10.0)
        for b in range(BATCH):
            for t in range(SEQ_LEN):
                perfect_logits[b, classification_targets[b, t], t] = 10.0

        random_logits = torch.randn(BATCH, NUM_CLASSES, SEQ_LEN)

        loss_perfect = loss_fn(perfect_logits, classification_targets).item()
        loss_random = loss_fn(random_logits, classification_targets).item()
        assert loss_perfect < loss_random

    def test_reduction_sum_larger_than_mean(self, classification_inputs, classification_targets):
        loss_mean = FocalLoss1D(LossConfig(loss_type="focal", reduction="mean"))
        loss_sum = FocalLoss1D(LossConfig(loss_type="focal", reduction="sum"))
        assert (
            loss_sum(classification_inputs, classification_targets).item()
            > loss_mean(classification_inputs, classification_targets).item()
        )


# ==========================================
# FocalLoss1DCW
# ==========================================


class TestFocalLoss1DCW:
    def test_output_is_scalar(self, classification_inputs, classification_targets, class_weights):
        cfg = LossConfig(loss_type="focal_cw")
        loss_fn = FocalLoss1DCW(cfg, class_weights)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.shape == torch.Size([])

    def test_output_is_non_negative(
        self, classification_inputs, classification_targets, class_weights
    ):
        cfg = LossConfig(loss_type="focal_cw")
        loss_fn = FocalLoss1DCW(cfg, class_weights)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_none_class_weights_falls_back_gracefully(
        self, classification_inputs, classification_targets
    ):
        cfg = LossConfig(loss_type="focal_cw")
        loss_fn = FocalLoss1DCW(cfg, class_weights=None)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.shape == torch.Size([])


# ==========================================
# get_criterion factory
# ==========================================


class TestGetCriterion:
    def test_focal_returns_focal_loss(self):
        cfg = LossConfig(loss_type="focal")
        criterion = get_criterion(cfg)
        assert isinstance(criterion, FocalLoss1D)

    def test_focal_cw_returns_focal_cw_loss(self, class_weights):
        cfg = LossConfig(loss_type="focal_cw")
        criterion = get_criterion(cfg, class_weights)
        assert isinstance(criterion, FocalLoss1DCW)

    def test_ce_returns_cross_entropy(self):
        cfg = LossConfig(loss_type="ce")
        criterion = get_criterion(cfg)
        assert isinstance(criterion, torch.nn.CrossEntropyLoss)

    def test_smooth_l1_returns_smooth_l1_loss(self):
        cfg = LossConfig(loss_type="smooth_l1")
        criterion = get_criterion(cfg)
        assert isinstance(criterion, torch.nn.SmoothL1Loss)

    def test_unknown_loss_type_raises(self):
        cfg = LossConfig(loss_type="focal")
        cfg.loss_type = "unknown"  # bypass Pydantic to simulate bad state
        with pytest.raises(ValueError, match="Unknown loss_type"):
            get_criterion(cfg)

    def test_ce_computes_on_synthetic_data(self, classification_inputs, classification_targets):
        cfg = LossConfig(loss_type="ce")
        criterion = get_criterion(cfg)
        loss = criterion(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_smooth_l1_computes_on_synthetic_data(self, regression_inputs, regression_targets):
        cfg = LossConfig(loss_type="smooth_l1")
        criterion = get_criterion(cfg)
        loss = criterion(regression_inputs, regression_targets)
        assert loss.item() >= 0.0


# ==========================================
# L2 — LossConfig.loss_type="custom" + loss_name + get_criterion routing
# ==========================================
#
# Verifies the custom-loss routing path added by L2. See
# ``docs/design/enable_loss_inventory.md`` § Commit L2.

# Stub template lives in agent_generated/_stub_loss_template.py (committed in L1a).
# Tests copy it (without the leading ``_``) into a tmp loss dir and point
# SIDERIUS_LOSS_DIRS at that dir.
_STUB_TEMPLATE = Path(__file__).resolve().parents[3] / "agent_generated" / "_stub_loss_template.py"


@pytest.fixture
def loss_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a fresh tmp loss directory containing the stub plugin (loadable
    as ``stub_ce``) and point ``SIDERIUS_LOSS_DIRS`` at it.

    Also clears any pre-existing ``siderius_loss_plugin_*`` entries from
    ``sys.modules`` so a previous test run's stub doesn't shadow this one.
    """
    d = tmp_path / "losses"
    d.mkdir()
    shutil.copy2(_STUB_TEMPLATE, d / "stub_ce.py")
    monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(d))
    for k in list(sys.modules):
        if k.startswith("siderius_loss_plugin_"):
            sys.modules.pop(k, None)
    return d


# ---------------------------------------------------------------------------
# Schema: loss_type="custom" requires loss_name; non-custom forbids it
# ---------------------------------------------------------------------------


class TestLossConfigCustomValidation:
    def test_custom_without_loss_name_raises(self):
        with pytest.raises(ValidationError, match="loss_name is required"):
            LossConfig(loss_type="custom")

    def test_custom_with_explicit_none_loss_name_raises(self):
        with pytest.raises(ValidationError, match="loss_name is required"):
            LossConfig(loss_type="custom", loss_name=None)

    def test_custom_with_empty_loss_name_raises(self):
        with pytest.raises(ValidationError, match="loss_name is required"):
            LossConfig(loss_type="custom", loss_name="")

    def test_custom_with_loss_name_succeeds(self):
        cfg = LossConfig(loss_type="custom", loss_name="snr_weighted_mse")
        assert cfg.loss_type == "custom"
        assert cfg.loss_name == "snr_weighted_mse"

    @pytest.mark.parametrize("lt", ["focal", "focal_cw", "ce", "smooth_l1"])
    def test_non_custom_with_loss_name_raises(self, lt: str):
        with pytest.raises(ValidationError, match="loss_name must be None"):
            LossConfig(loss_type=lt, loss_name="something")  # type: ignore[arg-type]

    @pytest.mark.parametrize("lt", ["focal", "focal_cw", "ce", "smooth_l1"])
    def test_non_custom_without_loss_name_succeeds(self, lt: str):
        cfg = LossConfig(loss_type=lt)  # type: ignore[arg-type]
        assert cfg.loss_name is None


# ---------------------------------------------------------------------------
# Schema: enforce_parameter_consistency nullifies alpha/gamma/beta for custom
# ---------------------------------------------------------------------------


class TestEnforceParameterConsistencyCustom:
    def test_custom_nullifies_alpha_gamma_beta(self):
        cfg = LossConfig(
            loss_type="custom",
            loss_name="snr_weighted_mse",
            alpha=0.7,
            gamma=3.0,
            beta=2.0,
        )
        # The router-vs-plugin two-config design means LossConfig's
        # alpha/gamma/beta are dead weight for custom; the validator
        # nullifies them so the agent can't accidentally pass them through.
        assert cfg.alpha is None
        assert cfg.gamma is None
        assert cfg.beta is None


# ---------------------------------------------------------------------------
# Schema: check_compatibility is a no-op for custom (defers to plugin)
# ---------------------------------------------------------------------------


class TestCheckCompatibilityCustom:
    @pytest.mark.parametrize("model_type", ["punet", "fcnet", "wavenet", "any_plugin_model"])
    def test_custom_is_compatible_with_any_model(self, model_type: str):
        """``check_compatibility`` should not raise for ``loss_type='custom'``
        regardless of model_type — the plugin's own forward pass will raise
        at training time if the shape contract is violated."""
        cfg = LossConfig(loss_type="custom", loss_name="anything")
        cfg.check_compatibility(model_type)  # must not raise


# ---------------------------------------------------------------------------
# get_criterion routing for loss_type="custom"
# ---------------------------------------------------------------------------


class TestGetCriterionCustom:
    def test_custom_loads_plugin(self, loss_dir: Path):
        """Happy path: with a valid plugin in SIDERIUS_LOSS_DIRS, get_criterion
        returns an instance of the plugin's PLUGIN_LOSS_CLASS."""
        cfg = LossConfig(loss_type="custom", loss_name="stub_ce")
        criterion = get_criterion(cfg)
        # The stub_ce plugin's PLUGIN_LOSS_CLASS is named StubCE.
        assert criterion.__class__.__name__ == "StubCE"

    def test_custom_plugin_forward_pass_runs(
        self, loss_dir: Path, classification_inputs, classification_targets
    ):
        """Sanity check: the loaded plugin actually runs its forward pass
        on classifier-shaped tensors and returns a scalar with grad. We
        explicitly enable ``requires_grad`` on the inputs to mimic the real
        training path (model outputs always have grad)."""
        cfg = LossConfig(loss_type="custom", loss_name="stub_ce")
        criterion = get_criterion(cfg)
        inputs = classification_inputs.detach().clone().requires_grad_(True)
        loss = criterion(inputs, classification_targets)
        assert loss.dim() == 0  # scalar
        assert loss.requires_grad
        assert loss.item() >= 0.0

    def test_missing_plugin_raises_value_error(self, loss_dir: Path):
        """When the loss_name doesn't match any plugin in SIDERIUS_LOSS_DIRS,
        get_criterion raises ValueError with the documented remediation text."""
        cfg = LossConfig(loss_type="custom", loss_name="nonexistent_loss")
        with pytest.raises(ValueError, match="not found in agent_generated/losses/"):
            get_criterion(cfg)

    def test_missing_plugin_error_mentions_implementor_and_env_var(self, loss_dir: Path):
        """Verify both remediation paths are in the error message — operator
        running into this manually needs to know about both implementor
        generation AND SIDERIUS_LOSS_DIRS configuration."""
        cfg = LossConfig(loss_type="custom", loss_name="nonexistent_loss")
        try:
            get_criterion(cfg)
        except ValueError as e:
            msg = str(e)
            assert "Run the implementor first" in msg
            assert "SIDERIUS_LOSS_DIRS" in msg
        else:
            pytest.fail("Expected ValueError")


# ---------------------------------------------------------------------------
# Regression guard: the 4 built-in loss types still work after the
# custom-branch addition at the top of the if/elif chain.
# ---------------------------------------------------------------------------


class TestBuiltinsStillWorkAfterCustomBranch:
    @pytest.mark.parametrize("lt", ["focal", "focal_cw", "ce"])
    def test_classifier_branches_still_route_correctly(
        self, lt: str, classification_inputs, classification_targets
    ):
        cfg = LossConfig(loss_type=lt)  # type: ignore[arg-type]
        criterion = get_criterion(cfg)
        loss = criterion(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_smooth_l1_branch_still_routes_correctly(self, regression_inputs, regression_targets):
        cfg = LossConfig(loss_type="smooth_l1")
        criterion = get_criterion(cfg)
        loss = criterion(regression_inputs, regression_targets)
        assert loss.item() >= 0.0
