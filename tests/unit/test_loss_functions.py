"""
Tests for model_tools/loss_models_sandbox.py

Verifies that all loss functions compute correctly on synthetic tensors
and that get_criterion instantiates the right class for each loss_type.
"""
import pytest
import torch

from model_tools.loss_models_sandbox import FocalLoss1D, FocalLoss1DCW, get_criterion
from model_tools.models_format_sandbox import LossConfig


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
        assert loss_sum(classification_inputs, classification_targets).item() > \
               loss_mean(classification_inputs, classification_targets).item()


# ==========================================
# FocalLoss1DCW
# ==========================================

class TestFocalLoss1DCW:

    def test_output_is_scalar(self, classification_inputs, classification_targets, class_weights):
        cfg = LossConfig(loss_type="focal_cw")
        loss_fn = FocalLoss1DCW(cfg, class_weights)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.shape == torch.Size([])

    def test_output_is_non_negative(self, classification_inputs, classification_targets, class_weights):
        cfg = LossConfig(loss_type="focal_cw")
        loss_fn = FocalLoss1DCW(cfg, class_weights)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_none_class_weights_falls_back_gracefully(self, classification_inputs, classification_targets):
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
