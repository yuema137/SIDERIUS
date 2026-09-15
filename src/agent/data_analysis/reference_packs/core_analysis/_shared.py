"""Private deterministic helpers for core-analysis skills."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import numpy as np

from agent.schemas.data_analysis.skills import ProducedArtifact


def binding_id(skill_input, slot_id: str) -> str:
    matches = [view.binding_id for view in skill_input.materializations if view.slot_id == slot_id]
    if len(matches) != 1:
        raise ValueError(f"slot {slot_id!r} requires exactly one materialization")
    return matches[0]


def first_information(view, preferred: str | None = None) -> np.ndarray:
    if preferred is not None and preferred in view.information:
        return np.asarray(view.information[preferred])
    if len(view.information) != 1:
        raise ValueError("skill requires exactly one certified information array")
    return np.asarray(next(iter(view.information.values())))


def finite_values(array: np.ndarray, valid_mask: np.ndarray | None = None) -> np.ndarray:
    values = np.asarray(array, dtype=np.float64)
    if valid_mask is not None:
        mask = np.asarray(valid_mask, dtype=np.bool_)
        if values.ndim == 3 and mask.ndim == 2:
            mask = np.broadcast_to(mask[:, None, :], values.shape)
        elif mask.ndim == 1 and values.ndim > 1 and len(mask) == len(values):
            mask = np.broadcast_to(
                mask.reshape((len(mask),) + (1,) * (values.ndim - 1)), values.shape
            )
        elif mask.shape != values.shape:
            raise ValueError("valid mask cannot be aligned with the selected values")
        values = values[mask]
    else:
        values = values.reshape(-1)
    return values[np.isfinite(values)]


def descriptive(values: np.ndarray, quantiles: Iterable[float]) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    probabilities = tuple(float(item) for item in quantiles)
    result: dict[str, Any] = {
        "count": int(values.size),
        "mean": None,
        "standard_deviation": None,
        "minimum": None,
        "maximum": None,
        "quantiles": {},
    }
    if not values.size:
        return result
    result.update(
        mean=float(np.mean(values)),
        minimum=float(np.min(values)),
        maximum=float(np.max(values)),
        quantiles={
            str(probability): float(np.quantile(values, probability, method="linear"))
            for probability in probabilities
        },
    )
    if values.size >= 2:
        result["standard_deviation"] = float(np.std(values, ddof=1))
    return result


def write_json_artifact(runtime, filename: str, payload: Any, description: str) -> ProducedArtifact:
    path = runtime.artifact_path(filename)
    path.write_text(
        json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    return ProducedArtifact(
        artifact_type="table",
        logical_name=filename.removesuffix(".json"),
        media_type="application/json",
        relative_path=filename,
        description=description,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def aligned_scalar(view, information_class: str) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(view.information[information_class], dtype=np.float64)
    if values.ndim == 2 and values.shape[1] == 1:
        values = values[:, 0]
    if values.ndim != 1:
        raise ValueError(f"{information_class} must be a scalar [N] array")
    return np.asarray(view.example_ids), values


def join_scalar_inputs(*items: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, ...]:
    reference_ids = items[0][0]
    for example_ids, _values in items[1:]:
        if not np.array_equal(example_ids, reference_ids):
            raise ValueError("aligned scalar inputs have different example ID order")
    return tuple(values for _example_ids, values in items)
