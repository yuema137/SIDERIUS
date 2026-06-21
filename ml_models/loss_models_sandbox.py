"""Loss function sandbox for SIDERIUS model training.

Provides ``get_criterion(cfg)`` which routes ``LossConfig`` instances to the
appropriate loss class.  Built-in types (``focal``, ``focal_cw``, ``ce``,
``smooth_l1``) are imported directly.  Custom agent-generated losses
(``loss_type="custom"``) are loaded at call time from the loss-plugin
directory (``agent_generated/losses/`` by default, overridden via
``SIDERIUS_LOSS_DIRS`` env var).  See ``docs/design/enable_loss_inventory.md``
§ Commit L2 for the two-config design rationale.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from ml_models.models_format_sandbox import LossConfig


class FocalLoss1D(nn.Module):
    """
    Standard Focal Loss for 1D sequences, initialized via LossConfig.
    """

    def __init__(self, config: LossConfig):
        super().__init__()
        # Extract from Pydantic config
        self.alpha = config.alpha if config.alpha is not None else 0.5
        self.gamma = config.gamma if config.gamma is not None else 2.0
        self.reduction = config.reduction

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        # inputs shape: [batch_size, num_classes, length]
        # targets shape: [batch_size, length]
        log_pt = F.log_softmax(inputs, dim=1)
        pt = torch.exp(log_pt)

        # Convert targets to one-hot encoding
        targets_one_hot = F.one_hot(targets, num_classes=inputs.shape[1]).permute(0, 2, 1).float()

        # Calculate Focal Loss
        alpha_t = self.alpha * targets_one_hot + (1 - self.alpha) * (1 - targets_one_hot)
        loss = -alpha_t * ((1 - pt) ** self.gamma) * log_pt

        # Only keep loss where targets are valid
        loss = (targets_one_hot * loss).sum(dim=1)

        if self.reduction == "mean":
            return loss.mean()
        elif self.reduction == "sum":
            return loss.sum()
        else:
            return loss


class FocalLoss1DCW(nn.Module):
    """
    Class-Weighted Focal Loss, initialized via LossConfig and external class weights.
    """

    def __init__(self, config: LossConfig, class_weights: torch.Tensor | None):
        super().__init__()
        # Extract from Pydantic config
        self.alpha = config.alpha  # Can be None if using class_weights
        self.gamma = config.gamma if config.gamma is not None else 4.0
        self.reduction = config.reduction

        # Register class_weights as buffer for GPU movement
        if class_weights is not None:
            self.register_buffer(
                "class_weights", torch.as_tensor(class_weights, dtype=torch.float32)
            )
        else:
            self.class_weights = None

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        log_pt = F.log_softmax(inputs, dim=1)
        pt = torch.exp(log_pt)

        targets_one_hot = F.one_hot(targets, num_classes=inputs.shape[1]).permute(0, 2, 1).float()

        # Apply class weights if available
        if self.class_weights is not None:
            # Reshape for broadcasting: [1, num_classes, 1]
            weights = self.class_weights.view(1, -1, 1)
            alpha_t = weights * targets_one_hot + (1 - weights) * (1 - targets_one_hot)
        else:
            # Fallback to scalar alpha if weights are missing
            alpha_val = self.alpha if self.alpha is not None else 0.5
            alpha_t = alpha_val * targets_one_hot + (1 - alpha_val) * (1 - targets_one_hot)

        loss = -alpha_t * ((1 - pt) ** self.gamma) * log_pt
        loss = (targets_one_hot * loss).sum(dim=1)

        if self.reduction == "mean":
            return loss.mean()
        elif self.reduction == "sum":
            return loss.sum()
        else:
            return loss


def _load_custom_loss(loss_name: str) -> nn.Module:
    """Load a plugin loss from ``agent_generated/losses/{loss_name}.py``.

    LossConfig is the routing layer only — it carries ``loss_type="custom"``
    and ``loss_name``. The plugin's own ``PLUGIN_LOSS_CONFIG_CLASS`` is a
    completely separate Pydantic model with the plugin's own hyperparameters
    (e.g. ``snr_threshold``, ``stft_window_size``). The two configs are
    independent; ``LossConfig.alpha``/``gamma``/``beta`` are irrelevant for
    custom losses and have already been nullified by
    ``enforce_parameter_consistency`` upstream.

    Args:
        loss_name: The ``PLUGIN_LOSS_TYPE`` key of the plugin to load.

    Returns:
        Instantiated loss ``nn.Module`` ready for use as a training criterion.

    Raises:
        ValueError: When no plugin with this ``loss_name`` is found in any
            ``SIDERIUS_LOSS_DIRS`` directory (or the legacy
            ``agent_generated/losses/`` fallback when the env var is unset).
    """
    # Lazy import keeps ml_models loadable without agent_generated/ on the
    # Python path (e.g. in older tests that exercise loss_models_sandbox
    # in isolation). Agent_generated/ has no torch dependency at import time.
    from agent_generated._loss_loader import load_loss_plugin

    plugin = load_loss_plugin(loss_name)
    if plugin is None:
        raise ValueError(
            f"Custom loss '{loss_name}' not found in agent_generated/losses/. "
            f"Run the implementor first to generate the loss plugin, or check "
            f"that SIDERIUS_LOSS_DIRS points to the correct directory."
        )
    # Construct the plugin's own config with its own defaults. Do NOT pass
    # loss_type/loss_name here — those belong to LossConfig (the router),
    # not to the plugin's config class. The plugin's hyperparameters
    # (e.g. snr_threshold) come from the proposer's CustomLossSpec at L4,
    # which is plumbed via a separate channel TBD.
    loss_cfg = plugin["config_class"]()
    return plugin["loss_class"](loss_cfg)


def get_criterion(config: LossConfig, class_weights: torch.Tensor | None = None):
    """
    Helper function to instantiate the correct loss based on the Agent's LossConfig.
    """
    if config.loss_type == "custom":
        # ``loss_name`` is validated non-None upstream by LossConfig's
        # ``enforce_custom_loss_name``; the assert below is for pyright
        # narrowing only and never fires at runtime.
        assert config.loss_name is not None
        return _load_custom_loss(config.loss_name)
    elif config.loss_type == "focal":
        return FocalLoss1D(config)
    elif config.loss_type == "focal_cw":
        return FocalLoss1DCW(config, class_weights)
    elif config.loss_type == "ce":
        # CrossEntropy handles class weights internally via 'weight' param
        return nn.CrossEntropyLoss(weight=class_weights, reduction=config.reduction)
    elif config.loss_type == "smooth_l1":
        # SmoothL1 uses beta parameter
        beta_val = config.beta if config.beta is not None else 1.0
        return nn.SmoothL1Loss(reduction=config.reduction, beta=beta_val)
    else:
        raise ValueError(f"Unknown loss_type: {config.loss_type}")
