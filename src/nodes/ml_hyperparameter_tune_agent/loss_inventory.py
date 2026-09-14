"""Run-scoped custom-loss inventory binding for the tuner."""

from __future__ import annotations

from agent.prompt_templates.proposal import live_loss_metadata
from agent.schemas.custom_loss_contract import (
    build_custom_loss_contract_snapshot,
    resolve_custom_loss_inventory,
)


def resolve_run_custom_loss_inventory(registry, model_io, composition_ref):
    """Freeze the registry view against the composed task before planning."""

    snapshot = None
    if (
        composition_ref is not None
        and model_io is not None
        and composition_ref.supervision_target is not None
        and composition_ref.custom_loss_applicability is not None
    ):
        snapshot = build_custom_loss_contract_snapshot(
            model_io.output,
            composition_ref.supervision_target,
            composition_ref.custom_loss_applicability,
        )
    return resolve_custom_loss_inventory(
        live_loss_metadata(registry),
        snapshot,
        composition_ref,
    )
