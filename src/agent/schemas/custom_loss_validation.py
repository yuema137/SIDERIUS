"""Data-free semantic and numerical validation for custom-loss plugins."""

from __future__ import annotations

import importlib.util
import math
import os
import tempfile
from collections.abc import Callable
from typing import Any

from agent.schemas.custom_loss_contract import (
    CustomLossApplicability,
    SyntheticLossPairProvider,
    resolve_custom_loss_applicability,
    validate_synthetic_loss_pair,
)
from agent.schemas.model_io_contract import ModelIOContract, TensorContract
from agent.skills.model_io_probe_skill import ProbeConstructionError, build_loss_probe_pair


def _resolve_declared_applicability(
    model_io: ModelIOContract | None,
    target: TensorContract | None,
    declaration: CustomLossApplicability | None,
) -> str | None:
    if declaration is None and target is None:
        return None
    verdict = resolve_custom_loss_applicability(
        model_io.output if model_io is not None else None,
        target,
        declaration,
    )
    if verdict.eligible:
        return None
    return f"Custom loss applicability refused: {verdict.reason}"


def _prepare_validation_pair(
    model_io: ModelIOContract | None,
    target_contract: TensorContract | None,
    applicability: CustomLossApplicability | None,
    provider: SyntheticLossPairProvider | None,
) -> tuple[tuple[Any, Any, str] | None, str | None]:
    if provider is None:
        try:
            prediction, target, description = build_loss_probe_pair(model_io)
        except ProbeConstructionError as exc:
            return None, f"Loss probe could not be constructed from the task contract: {exc}"
    else:
        try:
            supplied = provider()
            if not isinstance(supplied, tuple) or len(supplied) != 2:
                raise ValueError("provider must return a (prediction, target) tuple")
            prediction, target = supplied
            description = "the task-owned synthetic prediction/target pair"
        except Exception as exc:
            return None, (
                "Task-owned custom-loss validation pair provider refused: "
                f"{type(exc).__name__}: {exc}"
            )

    if model_io is not None and target_contract is not None:
        try:
            validate_synthetic_loss_pair(
                (prediction, target),
                model_io.output,
                target_contract,
                applicability=applicability,
            )
        except (TypeError, ValueError) as exc:
            provider_hint = "task-owned provider required; " if provider is None else ""
            return None, f"Loss probe contract refused: {provider_hint}{exc}"
    try:
        prediction = prediction.detach().clone().requires_grad_(True)
        target = target.detach().clone()
    except AttributeError as exc:
        return None, f"Loss probe tensors could not be prepared: {exc}"
    return (prediction, target, description), None


def _load_loss_factory(
    loss_name: str,
    module_path: str,
) -> tuple[Callable[[Any, Any], Any] | None, str | None]:
    spec = importlib.util.spec_from_file_location(f"siderius_loss_dummy_{loss_name}", module_path)
    if spec is None or spec.loader is None:
        return None, f"Could not resolve module spec for assembled loss plugin '{loss_name}'."
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        return None, f"Plugin source failed to import: {type(exc).__name__}: {exc}"

    from ml_models.loss_plugin_loader import REQUIRED_LOSS_PLUGIN_SYMBOLS

    for attr in REQUIRED_LOSS_PLUGIN_SYMBOLS:
        if not hasattr(module, attr):
            return None, f"Assembled plugin is missing required attribute '{attr}'."
    try:
        config = module.PLUGIN_LOSS_CONFIG_CLASS()
    except Exception as exc:
        return None, (
            "PLUGIN_LOSS_CONFIG_CLASS() failed to instantiate with defaults: "
            f"{type(exc).__name__}: {exc}. Every config field must have a default."
        )
    try:
        return module.PLUGIN_LOSS_CLASS(config), None
    except Exception as exc:
        return None, f"PLUGIN_LOSS_CLASS(config) failed to construct: {type(exc).__name__}: {exc}."


def _validate_loss_result(loss: Any, prediction: Any, *, loss_name: str) -> str | None:
    import torch

    if not isinstance(loss, torch.Tensor):
        return (
            f"forward returned {type(loss).__name__}, not a torch.Tensor. "
            "It must return a scalar tensor."
        )
    if loss.dim() != 0:
        return (
            f"forward returned a tensor of shape {tuple(loss.shape)}; "
            "expected a SCALAR (dim()==0). Reduce per-element loss to a "
            "scalar before returning (e.g. .mean() or .sum())."
        )
    try:
        value = loss.item()
    except Exception as exc:
        return f"loss.item() raised: {type(exc).__name__}: {exc}."
    if not math.isfinite(value):
        return f"forward returned a non-finite scalar (got {value!r})."
    try:
        loss.backward()
    except Exception as exc:
        return (
            f"loss.backward() raised: {type(exc).__name__}: {exc}. The loss graph is "
            "malformed — check for in-place ops on leaf tensors or operations that "
            "produce non-differentiable outputs on the main path from inputs."
        )
    if prediction.grad is None:
        return (
            f"Loss '{loss_name}': backward() ran but inputs.grad is None — gradient "
            "does not flow back to inputs. Check for .detach() or torch.no_grad() on "
            "the main computational path."
        )
    if not torch.isfinite(prediction.grad).all():
        return f"Loss '{loss_name}': inputs.grad contains NaN or Inf after backward()."
    return None


def validate_custom_loss_plugin(
    plugin_src: str,
    loss_name: str,
    model_io: ModelIOContract | None = None,
    supervision_target: TensorContract | None = None,
    applicability: CustomLossApplicability | None = None,
    pair_provider: SyntheticLossPairProvider | None = None,
) -> str | None:
    """Validate declarations, tiny tensors, plugin construction and gradients.

    The task-owned pair is constructed and checked before plugin source is
    written or imported. No cast, reshape or broadcast is invented here.
    """

    applicability_error = _resolve_declared_applicability(
        model_io,
        supervision_target,
        applicability,
    )
    if applicability_error is not None:
        return applicability_error
    prepared, pair_error = _prepare_validation_pair(
        model_io,
        supervision_target,
        applicability,
        pair_provider,
    )
    if pair_error is not None:
        return pair_error
    assert prepared is not None
    prediction, target, description = prepared

    with tempfile.TemporaryDirectory(prefix=f"siderius_loss_dummy_{loss_name}_") as tmp_dir:
        module_path = os.path.join(tmp_dir, "loss_plugin.py")
        with open(module_path, "w", encoding="utf-8") as handle:
            handle.write(plugin_src)
        loss_fn, load_error = _load_loss_factory(loss_name, module_path)
        if load_error is not None:
            return load_error
        assert loss_fn is not None
        try:
            loss = loss_fn(prediction, target)
        except Exception as exc:
            return (
                f"forward(inputs, targets) raised on dummy tensors: "
                f"{type(exc).__name__}: {exc}. The forward must accept {description}."
            )
        return _validate_loss_result(loss, prediction, loss_name=loss_name)
