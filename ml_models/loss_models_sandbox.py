"""Loss function sandbox for SIDERIUS model training.

Provides ``get_criterion(cfg)`` which routes ``LossConfig`` instances to the
appropriate loss class.  Built-in types (``focal``, ``focal_cw``, ``ce``,
``smooth_l1``) are imported directly.  Custom agent-generated losses
(``loss_type="custom"``) are loaded via two paths:

  1. **In-memory ``LOSS_REGISTRY``** (L6c) — populated by the workflow's
     ``_register_plugin`` at iter-time AND by ``preload_global_losses()``
     at workflow startup. Mirrors ``ml_models.models_sandbox.MODEL_REGISTRY``
     for the loss surface so in-process consumers (e.g. ``evaluate_vram_skill``,
     ``evaluate_time_skill``) can resolve plugins without depending on
     ``SIDERIUS_LOSS_DIRS`` (which is set only for training subprocesses).
  2. **Filesystem fallback** via ``agent_generated/_loss_loader.load_loss_plugin``,
     which walks ``SIDERIUS_LOSS_DIRS`` ∪ ``agent_generated/losses/`` (L6c
     union mode). Used by training subprocesses that inherit the env var.

See ``docs/design/enable_loss_inventory.md`` § Commit L2 + § L6c for the
two-config design rationale and the in-memory registry symmetry with models.
"""

import os

import torch
import torch.nn as nn
import torch.nn.functional as F

from ml_models.models_format_sandbox import LossConfig

# ---------------------------------------------------------------------------
# L6c — In-process loss-plugin registry. Mirrors MODEL_REGISTRY.
# ---------------------------------------------------------------------------
#
# Module-level mutable state. Populated by:
#   * ``register_loss_in_memory(plugin_path)`` — called by the workflow's
#     ``_register_plugin`` for each loss it copies (action="generated").
#   * ``preload_global_losses()`` — called at workflow startup so cross-
#     process Branch B reuse (chain resume after restart) finds previously-
#     promoted losses without needing ``SIDERIUS_LOSS_DIRS``.
#
# Consumed by:
#   * ``_load_custom_loss(name)`` — checks ``LOSS_REGISTRY[name]`` first,
#     falls back to filesystem scan for subprocess callers.
#
# Test discipline: an ``autouse`` fixture in test files clears both dicts
# between tests; see ``tests/unit/ml_models/test_loss_models_sandbox.py``.
LOSS_REGISTRY: dict[str, type] = {}
LOSS_CONFIG_REGISTRY: dict[str, type] = {}


def register_loss_in_memory(plugin_path: str) -> str | None:
    """Load a loss plugin file and register its classes in ``LOSS_REGISTRY``.

    L6c — mirrors ``ml_models.plugin_loader.register_model_in_memory``
    for the loss surface. Called by the workflow's ``_register_plugin`` after
    L6a copies the plugin file, AND by ``preload_global_losses()`` at
    workflow startup.

    Idempotency: re-registering the same ``loss_type`` is allowed.
    When the new ``loss_class`` differs in ``__qualname__`` from the
    already-registered one, a warning is printed (subtle bug signal — a
    plugin was reloaded with different code under the same name).

    I13 — also populates ``LOSS_TARGET_DTYPE_REGISTRY`` from the plugin's
    ``PLUGIN_LOSS_TARGET_DTYPE`` declaration so consumers
    (``evaluate_time_skill``, ``train_engine_sandbox``) can resolve the
    correct target dtype without hardcoded loss_type lists.

    Args:
        plugin_path: Absolute path to the loss plugin ``.py`` file.

    Returns:
        The plugin's ``PLUGIN_LOSS_TYPE`` string on success, ``None`` on
        load failure (the loader logs the underlying error).
    """
    # Lazy import keeps ml_models loadable without agent_generated/ on the
    # Python path (legacy tests that exercise loss_models_sandbox in isolation).
    from agent_generated._loss_loader import (
        LOSS_REDUCTION_REGISTRY,
        LOSS_TARGET_DTYPE_REGISTRY,
        load_loss_plugin_from_path,
    )

    plugin = load_loss_plugin_from_path(plugin_path)
    if plugin is None:
        return None
    loss_type = plugin["loss_type"]
    new_cls = plugin["loss_class"]
    existing_cls = LOSS_REGISTRY.get(loss_type)
    if existing_cls is not None and getattr(existing_cls, "__qualname__", None) != getattr(
        new_cls, "__qualname__", None
    ):
        print(
            f"[LossRegistry] Warning: re-registering loss_type={loss_type!r} "
            f"with a different class ({existing_cls.__qualname__} → "
            f"{new_cls.__qualname__}). Most-recent registration wins."
        )
    LOSS_REGISTRY[loss_type] = new_cls
    LOSS_CONFIG_REGISTRY[loss_type] = plugin["config_class"]
    # I13 — register the target-dtype declaration alongside the class registry
    # so ``get_target_torch_dtype`` can resolve custom losses without scanning
    # disk on every call. ``load_loss_plugin_from_path`` always populates the
    # ``"target_dtype"`` key (defaulting to ``"long"`` when the plugin's
    # ``PLUGIN_LOSS_TARGET_DTYPE`` declaration is missing).
    LOSS_TARGET_DTYPE_REGISTRY[loss_type] = plugin["target_dtype"]
    # Step 12 / PR-12d D4c: the OPTIONAL declared normalization, recorded on
    # the SAME event as the dtype. Tier 1 and Tier 2 must agree about the same
    # plugin — F-12d-2 was exactly the cost of them not agreeing.
    if plugin["reduction"] is not None:
        LOSS_REDUCTION_REGISTRY[loss_type] = plugin["reduction"]
    return loss_type


def preload_global_losses() -> list[str]:
    """Load all promoted loss plugins into ``LOSS_REGISTRY``.

    L6c — called at workflow startup so cross-process Branch B reuse (e.g.
    chain resume after restart) finds previously-promoted losses in-memory
    without needing ``SIDERIUS_LOSS_DIRS``. Idempotent — safe to call
    multiple times; ``register_loss_in_memory`` handles re-registration.

    arXiv P1 — scans TWO locations, resolved library first:

      1. the resolved generated-library losses dir
         (``core.generated_library.generated_losses_dir()``), where every
         promotion writes now;
      2. the LEGACY CHECKOUT ``agent_generated/losses/``
         (``_loss_loader.LOSSES_DIR``) — read-only compatibility, so losses
         promoted before the migration keep preloading.

    A legacy file whose BASENAME already appeared in the resolved library is
    skipped entirely — promotion names files ``{loss_type}.py``, so a
    same-named pair is the same declared loss and the resolved-library copy
    is authoritative. The shadow applies even when the resolved copy fails
    to load: falling back to the legacy bytes there would silently register
    a STALE implementation under the type name, when the honest outcome is
    a loud loader log line and an absent type.

    Files starting with ``_`` are skipped (template / dunder convention,
    same as ``_loss_loader._load_loss_plugin``'s scan).

    Returns:
        List of ``loss_type`` strings successfully loaded. Empty list when
        neither directory exists or both are empty (first-run / fresh host).
    """
    from agent_generated._loss_loader import LOSSES_DIR
    from core.generated_library import generated_library_is_workspace_bound, generated_losses_dir

    loaded: list[str] = []
    seen_basenames: set[str] = set()
    loss_dirs = [generated_losses_dir()]
    if not generated_library_is_workspace_bound():
        loss_dirs.append(LOSSES_DIR)
    for losses_dir in loss_dirs:
        if not os.path.isdir(losses_dir):
            continue
        for fname in sorted(os.listdir(losses_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            if fname in seen_basenames:
                continue  # resolved-library copy shadows the legacy one
            seen_basenames.add(fname)
            plugin_path = os.path.join(losses_dir, fname)
            loss_type = register_loss_in_memory(plugin_path)
            if loss_type is not None:
                loaded.append(loss_type)
    return loaded


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
    """Load a plugin loss by name, preferring the in-memory ``LOSS_REGISTRY``.

    L6c — two-tier lookup:

      1. In-memory ``LOSS_REGISTRY`` — populated by the workflow's
         ``_register_plugin`` (same-process Branch C) and by
         ``preload_global_losses()`` at workflow startup (cross-process Branch B
         reuse of promoted losses). Hits here resolve without touching disk.
      2. Filesystem fallback via ``load_loss_plugin`` → ``_resolve_loss_dirs``
         (union: ``SIDERIUS_LOSS_DIRS`` ∪ ``agent_generated/losses/``).
         Hits here are typical inside training subprocesses that inherit the
         env var but do not share the parent process's module state.

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
        ValueError: When ``loss_name`` is not in ``LOSS_REGISTRY`` AND is
            not found in any directory returned by ``_resolve_loss_dirs``.
            The error message lists both surfaces so operators can diagnose
            either side.
    """
    # Tier 1 — in-memory registry hit (avoid disk).
    if loss_name in LOSS_REGISTRY:
        config_cls = LOSS_CONFIG_REGISTRY[loss_name]
        return LOSS_REGISTRY[loss_name](config_cls())

    # Tier 2 — filesystem fallback. Lazy import keeps ml_models loadable
    # without agent_generated/ on the Python path (legacy isolation tests).
    from agent_generated._loss_loader import load_loss_plugin

    plugin = load_loss_plugin(loss_name)
    if plugin is None:
        raise ValueError(
            f"Custom loss '{loss_name}' not found in LOSS_REGISTRY or "
            f"agent_generated/losses/. Run the implementor first to generate "
            f"the loss plugin, or check that SIDERIUS_LOSS_DIRS points to the "
            f"correct directory. Currently registered in LOSS_REGISTRY: "
            f"{sorted(LOSS_REGISTRY)!r}."
        )
    # Construct the plugin's own config with its own defaults. Do NOT pass
    # loss_type/loss_name here — those belong to LossConfig (the router),
    # not to the plugin's config class. The plugin's hyperparameters
    # (e.g. snr_threshold) come from the proposer's CustomLossSpec at L4,
    # which is plumbed via a separate channel TBD.
    loss_cfg = plugin["config_class"]()
    return plugin["loss_class"](loss_cfg)


def get_target_torch_dtype(config: LossConfig) -> torch.dtype:
    """Return the ``torch.dtype`` that ``targets`` must be cast to before
    invoking ``criterion(output, targets)`` for the given ``LossConfig``.

    I13 — single source of truth that replaces the hardcoded
    ``loss_type in ("ce", "focal", "focal_cw")`` checks that previously
    lived in ``evaluate_time_skill/wrapper.py`` and
    ``execute_tools/train_engine_sandbox.py``. Removing those checks closes
    a registry-asymmetry defect of the same family as I9 (tuner planner
    not registry-aware) and I12 (in-process pre-flight not aware of
    workspace losses).

    Routing:
      * ``"smooth_l1"``                  → ``torch.float32`` (regression head)
      * ``"ce" | "focal" | "focal_cw"``  → ``torch.long``    (built-in classifier)
      * ``"custom"``                     → looked up via
        ``LOSS_TARGET_DTYPE_REGISTRY`` (populated at plugin-load time from
        each plugin's ``PLUGIN_LOSS_TARGET_DTYPE`` declaration). Defaults to
        ``torch.long`` for pre-I13 plugins that don't declare the field,
        matching the int64 classifier contract documented in
        ``proposing_stage.md``.

    Args:
        config: A validated ``LossConfig`` instance.

    Returns:
        ``torch.long`` for classifier-style losses; ``torch.float32`` for
        regressor-style losses.
    """
    if config.loss_type == "smooth_l1":
        return torch.float32
    if config.loss_type in ("ce", "focal", "focal_cw"):
        return torch.long
    # config.loss_type == "custom" — read from the plugin's declaration.
    # Lazy import for the same reason ``_load_custom_loss`` uses it: keep
    # ``ml_models`` loadable without ``agent_generated/`` on the path.
    from agent_generated._loss_loader import get_loss_target_dtype

    declared = get_loss_target_dtype(config.loss_name or "")
    return torch.long if declared == "long" else torch.float32


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
