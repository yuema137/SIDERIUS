"""Private deterministic helpers implementing frozen time-series semantics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import signal

from agent.data_analysis.view_formats import TimeSeriesArrayView
from agent.schemas.data_analysis.skills import ProducedArtifact, QuantitativeResult


@dataclass(frozen=True)
class AtomicSeries:
    example_index: int
    example_id: str
    channel_index: int
    channel_id: str
    time: np.ndarray
    values: np.ndarray
    mask: np.ndarray


def binding_id(skill_input, slot_id: str) -> str:
    matches = [view.binding_id for view in skill_input.materializations if view.slot_id == slot_id]
    if len(matches) != 1:
        raise ValueError(f"slot {slot_id!r} requires exactly one materialization")
    return matches[0]


def series_view(runtime, skill_input, slot_id: str = "series") -> TimeSeriesArrayView:
    view = runtime.load_materialization(binding_id(skill_input, slot_id))
    if not isinstance(view, TimeSeriesArrayView):
        raise ValueError(f"slot {slot_id!r} requires siderius.timeseries-array.v1")
    return view


def information_array(view: TimeSeriesArrayView, name: str) -> np.ndarray:
    if name not in view.information:
        raise ValueError(f"certified time-series view omits {name!r}")
    return np.asarray(view.information[name], dtype=np.float64)


def atomic_series(view: TimeSeriesArrayView, information_class: str) -> list[AtomicSeries]:
    values = information_array(view, information_class)
    result = []
    for example_index, example_id in enumerate(view.example_ids):
        time = np.asarray(view.time_seconds(example_index), dtype=np.float64)
        mask = np.asarray(view.valid_mask[example_index], dtype=np.bool_)
        for channel_index, channel_id in enumerate(view.channel_ids):
            result.append(
                AtomicSeries(
                    example_index=example_index,
                    example_id=str(example_id),
                    channel_index=channel_index,
                    channel_id=str(channel_id),
                    time=time,
                    values=values[example_index, channel_index],
                    mask=mask,
                )
            )
    return result


def regular_values(view: TimeSeriesArrayView, item: AtomicSeries) -> tuple[np.ndarray, float]:
    if not view.is_time_certified_regular(item.example_index):
        raise ValueError("time axis is not certified regular")
    if not np.all(item.mask):
        raise ValueError("regular spectral analysis does not repair gaps or masked samples")
    if not np.all(np.isfinite(item.values)):
        raise ValueError("regular spectral analysis does not drop nonfinite samples")
    sample_rate = view.sample_rate_hz(item.example_index)
    if sample_rate is None or not np.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError("certified regular series has no positive finite sample rate")
    return np.asarray(item.values, dtype=np.float64), float(sample_rate)


def spectral_parameters(nperseg: int, noverlap: int | None, length: int, sample_rate: float):
    if nperseg > length:
        raise ValueError("nperseg exceeds usable contiguous sequence length")
    overlap = nperseg // 2 if noverlap is None else noverlap
    if overlap < 0 or overlap >= nperseg:
        raise ValueError("noverlap must satisfy 0 <= noverlap < nperseg")
    segment_count = 1 + (length - nperseg) // (nperseg - overlap)
    return {
        "resolved_nperseg": nperseg,
        "resolved_noverlap": overlap,
        "segment_duration_seconds": nperseg / sample_rate,
        "frequency_resolution_hz": sample_rate / nperseg,
        "usable_segment_count": segment_count,
    }


def welch(values: np.ndarray, sample_rate: float, nperseg: int, noverlap: int | None):
    receipt = spectral_parameters(nperseg, noverlap, len(values), sample_rate)
    frequency, density = signal.welch(
        values,
        fs=sample_rate,
        window="hann_periodic",
        nperseg=nperseg,
        noverlap=receipt["resolved_noverlap"],
        detrend="constant",
        return_onesided=True,
        scaling="density",
        average="mean",
    )
    return frequency, density, receipt


def deterministic_peaks(
    frequency: np.ndarray,
    values: np.ndarray,
    *,
    maximum: int,
    minimum_hz: float | None = None,
    maximum_hz: float | None = None,
) -> list[dict[str, float]]:
    selected = np.ones(len(frequency), dtype=np.bool_)
    selected &= frequency > 0
    if minimum_hz is not None:
        selected &= frequency >= minimum_hz
    if maximum_hz is not None:
        selected &= frequency <= maximum_hz
    indices = signal.find_peaks(np.where(selected, values, -np.inf))[0]
    ordered = sorted(indices, key=lambda index: (-float(values[index]), float(frequency[index])))
    return [
        {"frequency_hz": float(frequency[index]), "value": float(values[index])}
        for index in ordered[:maximum]
    ]


def aggregate_channel_scalars(records: list[dict[str, Any]], keys: tuple[str, ...]):
    channels: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        channels.setdefault(record["channel_id"], []).append(record)
    output = {}
    for channel_id, items in sorted(channels.items()):
        summary: dict[str, Any] = {"example_count": len(items)}
        for key in keys:
            values = np.asarray(
                [item[key] for item in items if item.get(key) is not None], dtype=np.float64
            )
            summary[key] = (
                None
                if not len(values)
                else {
                    "median": float(np.median(values)),
                    "q25": float(np.quantile(values, 0.25)),
                    "q75": float(np.quantile(values, 0.75)),
                }
            )
        output[channel_id] = summary
    return output


def bounded_channel_measurements(
    aggregate: dict[str, dict[str, Any]],
    specifications: tuple[tuple[str, str | None, str], ...],
    *,
    maximum_results: int = 24,
) -> tuple[QuantitativeResult, ...]:
    """Expose a bounded scalar projection of already-computed channel summaries.

    Full per-series arrays stay in certified artifacts.  These median values
    are the compact evidence surface available to report synthesis; channels
    remain separate and are never pooled by this helper.
    """

    results: list[QuantitativeResult] = []
    for channel_id, channel in sorted(aggregate.items()):
        for key, unit, description in specifications:
            summary = channel.get(key)
            if not isinstance(summary, dict) or summary.get("median") is None:
                continue
            results.append(
                QuantitativeResult(
                    result_key=f"channel.{channel_id}.{key}.median",
                    value=summary["median"],
                    unit=unit,
                    description=f"{description}; median across usable examples in this channel",
                )
            )
            if len(results) >= maximum_results:
                return tuple(results)
    return tuple(results)


def usable_series_measurement(records: list[dict[str, Any]]) -> QuantitativeResult:
    """Return the bounded number of atomic series that produced measurements."""

    return QuantitativeResult(
        result_key="usable_series_count",
        value=sum(item.get("unusable_reason") is None for item in records),
        description="Number of example-channel atomic series with usable results",
    )


def bounded_example_measurements(
    records: list[dict[str, Any]],
    specifications: tuple[tuple[str, str | None, str], ...],
) -> tuple[QuantitativeResult, ...]:
    """Equal-example scalar summaries for one declared channel-pair analysis."""

    results: list[QuantitativeResult] = [usable_series_measurement(records)]
    usable = [item for item in records if item.get("unusable_reason") is None]
    for key, unit, description in specifications:
        values = np.asarray(
            [item[key] for item in usable if item.get(key) is not None], dtype=np.float64
        )
        if len(values):
            results.append(
                QuantitativeResult(
                    result_key=f"{key}.mean",
                    value=float(np.mean(values)),
                    unit=unit,
                    description=f"{description}; equal-weight mean across usable examples",
                )
            )
    return tuple(results)


def write_json_artifact(runtime, filename: str, payload: Any, description: str) -> ProducedArtifact:
    runtime.artifact_path(filename).write_text(
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
