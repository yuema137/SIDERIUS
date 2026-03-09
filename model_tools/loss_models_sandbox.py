import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional
from models_format_sandbox import LossConfig

class FocalLoss1D(nn.Module):
    """
    Standard Focal Loss for 1D sequences, initialized via LossConfig.
    """
    def __init__(self, config: LossConfig):
        super(FocalLoss1D, self).__init__()
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
        
        if self.reduction == 'mean':
            return loss.mean()
        elif self.reduction == 'sum':
            return loss.sum()
        else:
            return loss


class FocalLoss1DCW(nn.Module):
    """
    Class-Weighted Focal Loss, initialized via LossConfig and external class weights.
    """
    def __init__(self, config: LossConfig, class_weights: torch.Tensor):
        super(FocalLoss1DCW, self).__init__()
        # Extract from Pydantic config
        self.alpha = config.alpha # Can be None if using class_weights
        self.gamma = config.gamma if config.gamma is not None else 4.0
        self.reduction = config.reduction
        
        # Register class_weights as buffer for GPU movement
        if class_weights is not None:
            self.register_buffer('class_weights', torch.as_tensor(class_weights, dtype=torch.float32))
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
        
        if self.reduction == 'mean':
            return loss.mean()
        elif self.reduction == 'sum':
            return loss.sum()
        else:
            return loss

def get_criterion(config: LossConfig, class_weights: Optional[torch.Tensor] = None):
    """
    Helper function to instantiate the correct loss based on the Agent's LossConfig.
    """
    if config.loss_type == "focal":
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