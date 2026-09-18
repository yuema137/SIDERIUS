"""Names shared by the sandbox parent, training child, and round consumers."""

from __future__ import annotations

from pathlib import Path


def training_checkpoint_path(models_dir: str | Path, model_type: str, exp_id: str) -> Path:
    """Return the exact checkpoint this training attempt writes."""

    return Path(models_dir) / f"model_{model_type}_{exp_id}_agent.pth"
