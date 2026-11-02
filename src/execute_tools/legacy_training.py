"""Seed admission for direct legacy training; the engine owns the training loop.

Contract: execute_tools/execution-contract.md and the seeding mechanism.
"""

from typing import Any

from torch.utils.data import DataLoader

from agent.schemas.model_io_contract import ModelIOContract
from core.capability_registry import CapabilityContractSnapshot
from core.training_seeds import TrainingSeedPlan, require_seed_plan
from execute_tools.process_seeding import seed_process
from ml_models.models_format_sandbox import LossConfig, TrainConfig


def run_experiment(
    model_cfg: object,
    train_cfg: TrainConfig,
    loss_cfg: LossConfig,
    data_loader: DataLoader,
    sandbox_dirs: dict[str, str],
    exp_id: str,
    model_io: ModelIOContract | None = None,
    expected_custom_loss_snapshot: CapabilityContractSnapshot | None = None,
    *,
    seed_plan: TrainingSeedPlan,
) -> dict[str, Any]:
    """Train with a caller-owned loader and a required run-derived seed plan.

    Seed process RNGs before model construction. The caller owns data selection
    and loader generators; only the trainer CLI may generate a missing run seed.
    """
    # Import only at invocation: the engine re-exports this public entry.
    from execute_tools.train_engine_sandbox import _run_experiment

    seed_process(require_seed_plan(seed_plan))
    return _run_experiment(
        model_cfg,
        train_cfg,
        loss_cfg,
        data_loader,
        sandbox_dirs,
        exp_id,
        model_io,
        expected_custom_loss_snapshot,
    )
