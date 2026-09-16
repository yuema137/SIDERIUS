"""SIDERIUS-owned read-only loaders for the minimal v0.1 view ABI.

Both formats use an executor-certified NPZ transport, but NPZ is deliberately
not the skill-facing contract: a skill calls ``runtime.load_materialization``
and receives one of the read-only objects below. ``numeric-array.v1`` carries
``example_ids[N]``, one or more certified information arrays beginning with
``N``, optional scalar/per-example certified metadata, and an optional boolean
``valid_mask[N]``. ``timeseries-array.v1`` additionally fixes
``channel_ids[C]``, ``valid_mask[N,T]``, every certified information array to
``[N,C,T]``, and a SIDERIUS-owned explicit-or-regular time-axis union. The mask
describes valid observations separately from nominal timing; nonfinite values
remain observable values for a skill to report or filter.

Only information named by ``MaterializedAnalysisView.certified_information``
is admitted. This keeps storage representation private, gives out-of-tree
skills a versioned semantic ABI, and prevents the loader from becoming a way
to bypass the authorization receipt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import numpy as np

from agent.schemas.data_analysis.assets import MaterializedAnalysisView
from agent.schemas.data_analysis.time import FixedTimePrecisionRequirement
from agent.schemas.data_analysis.view_formats import NUMERIC_ARRAY_V1, TIMESERIES_ARRAY_V1

NPZ_MEDIA_TYPE = "application/x-npz"
CADENCE_RTOL = 1e-6
CADENCE_ATOL_SECONDS = 0.0


class MaterializedViewFormatError(ValueError):
    """Materialized bytes do not satisfy their declared, policy-bounded view format."""


@dataclass(frozen=True)
class NumericArrayView:
    binding_id: str
    example_ids: np.ndarray
    information: Mapping[str, np.ndarray]
    metadata: Mapping[str, np.ndarray]
    valid_mask: np.ndarray | None


@dataclass(frozen=True)
class RegularTimeAxis:
    """Per-example regular axes in relative seconds; step is authoritative."""

    start_seconds: np.ndarray
    step_seconds: np.ndarray
    sample_count: int
    kind: Literal["regular"] = "regular"

    def values_for(self, example_index: int) -> np.ndarray:
        _validate_example_index(example_index, len(self.start_seconds))
        values = (
            self.start_seconds[example_index]
            + np.arange(self.sample_count, dtype=np.float64) * self.step_seconds[example_index]
        )
        return _readonly(values)

    def is_certified_regular(self, example_index: int) -> bool:
        _validate_example_index(example_index, len(self.start_seconds))
        return True

    def sample_rate_hz(self, example_index: int) -> float:
        _validate_example_index(example_index, len(self.start_seconds))
        return 1.0 / float(self.step_seconds[example_index])


@dataclass(frozen=True)
class ExplicitTimeAxis:
    """Per-example timestamps preserved in source order and relative seconds."""

    time_seconds: np.ndarray
    certified_regular: np.ndarray
    required_resolution_seconds: np.ndarray
    worst_ulp_seconds: np.ndarray
    kind: Literal["explicit"] = "explicit"

    def values_for(self, example_index: int) -> np.ndarray:
        _validate_example_index(example_index, len(self.time_seconds))
        return self.time_seconds[example_index]

    def is_certified_regular(self, example_index: int) -> bool:
        _validate_example_index(example_index, len(self.time_seconds))
        return bool(self.certified_regular[example_index])

    def sample_rate_hz(self, example_index: int) -> float | None:
        if not self.is_certified_regular(example_index):
            return None
        deltas = np.diff(self.time_seconds[example_index])
        if not len(deltas):
            return None
        return 1.0 / float(np.median(deltas))


TimeAxis = RegularTimeAxis | ExplicitTimeAxis


@dataclass(frozen=True)
class TimeSeriesArrayView(NumericArrayView):
    time_axis: TimeAxis
    channel_ids: np.ndarray
    valid_mask: np.ndarray

    def time_seconds(self, example_index: int) -> np.ndarray:
        """Return one axis without materializing a dense regular ``N x T`` grid."""

        return self.time_axis.values_for(example_index)

    def is_time_certified_regular(self, example_index: int) -> bool:
        return self.time_axis.is_certified_regular(example_index)

    def sample_rate_hz(self, example_index: int) -> float | None:
        """Derive frequency from the sole authoritative timing representation."""

        return self.time_axis.sample_rate_hz(example_index)


LoadedMaterializedView = NumericArrayView | TimeSeriesArrayView


def _readonly(array: np.ndarray) -> np.ndarray:
    if array.dtype.hasobject:
        raise MaterializedViewFormatError("object-dtype arrays are forbidden")
    array.setflags(write=False)
    return array


def _validate_example_index(example_index: int, count: int) -> None:
    if not 0 <= example_index < count:
        raise IndexError(f"example_index {example_index} outside [0, {count})")


def _certified_keys(view: MaterializedAnalysisView) -> tuple[set[str], set[str]]:
    information: set[str] = set()
    metadata: set[str] = set()
    for requirement in view.certified_information:
        if requirement.information_class == "metadata":
            metadata.update(requirement.fields)
        else:
            information.add(requirement.information_class)
    return information, metadata


def _read_npz(
    descriptor: MaterializedAnalysisView,
    path: Path,
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray], dict[str, np.ndarray]]:
    if descriptor.content_ref.media_type != NPZ_MEDIA_TYPE:
        raise MaterializedViewFormatError(
            f"{descriptor.format_id} requires media type {NPZ_MEDIA_TYPE!r}"
        )
    certified_information, certified_metadata = _certified_keys(descriptor)
    expected_information_keys = {f"information__{name}" for name in certified_information}
    expected_metadata_keys = {f"metadata__{name}" for name in certified_metadata}
    with np.load(path, allow_pickle=False) as archive:
        keys = set(archive.files)
        common = {"example_ids"}
        format_keys = {"valid_mask"}
        if descriptor.format_id == TIMESERIES_ARRAY_V1:
            format_keys |= {
                "channel_ids",
                "time",
                "time_certified_regular",
                "time_required_resolution_seconds",
                "time_start_seconds",
                "time_step_seconds",
            }
        allowed = common | format_keys | expected_information_keys | expected_metadata_keys
        if not expected_information_keys.issubset(keys):
            raise MaterializedViewFormatError("materialization omits certified information arrays")
        if not expected_metadata_keys.issubset(keys):
            raise MaterializedViewFormatError("materialization omits certified metadata arrays")
        if not keys.issubset(allowed):
            raise MaterializedViewFormatError(
                "materialization contains fields not listed in certified_information"
            )
        if "example_ids" not in keys:
            raise MaterializedViewFormatError("materialization requires example_ids")
        example_ids = _readonly(np.asarray(archive["example_ids"]))
        information = {
            name.removeprefix("information__"): _readonly(np.asarray(archive[name]))
            for name in sorted(expected_information_keys)
        }
        metadata = {
            name.removeprefix("metadata__"): _readonly(np.asarray(archive[name]))
            for name in sorted(expected_metadata_keys)
        }
        extra = {name: _readonly(np.asarray(archive[name])) for name in sorted(format_keys & keys)}
    return example_ids, information, metadata, extra


def _validate_common(
    descriptor: MaterializedAnalysisView,
    example_ids: np.ndarray,
    information: dict[str, np.ndarray],
    metadata: dict[str, np.ndarray],
) -> int:
    if example_ids.ndim != 1:
        raise MaterializedViewFormatError("example_ids must have shape [N]")
    count = len(example_ids)
    if count != descriptor.materialized_count:
        raise MaterializedViewFormatError(
            "example_ids count differs from certified materialization"
        )
    if len({str(item) for item in example_ids.tolist()}) != count:
        raise MaterializedViewFormatError("example_ids must be unique")
    for name, array in information.items():
        if array.ndim < 1 or array.shape[0] != count:
            raise MaterializedViewFormatError(f"information array {name!r} must begin with [N]")
    for name, array in metadata.items():
        if array.ndim > 0 and array.shape[0] not in (1, count):
            raise MaterializedViewFormatError(
                f"metadata array {name!r} must be scalar, [1], or begin with [N]"
            )
    return count


def load_materialized_view(
    descriptor: MaterializedAnalysisView,
    path: Path,
) -> LoadedMaterializedView:
    """Load a versioned semantic view; skills never parse content_ref files themselves."""

    if descriptor.format_id not in {NUMERIC_ARRAY_V1, TIMESERIES_ARRAY_V1}:
        raise MaterializedViewFormatError(
            f"unsupported materialized view format {descriptor.format_id!r}"
        )
    example_ids, information, metadata, extra = _read_npz(descriptor, path)
    count = _validate_common(descriptor, example_ids, information, metadata)
    if descriptor.format_id == NUMERIC_ARRAY_V1:
        valid_mask = extra.get("valid_mask")
        if valid_mask is not None and (
            valid_mask.dtype != np.bool_ or valid_mask.shape != (count,)
        ):
            raise MaterializedViewFormatError("numeric valid_mask must be boolean [N]")
        return NumericArrayView(
            binding_id=descriptor.binding_id,
            example_ids=example_ids,
            information=MappingProxyType(information),
            metadata=MappingProxyType(metadata),
            valid_mask=valid_mask,
        )

    missing = {"channel_ids", "valid_mask"} - set(extra)
    if missing:
        raise MaterializedViewFormatError(f"time-series materialization omits {sorted(missing)}")
    channel_ids = extra["channel_ids"]
    valid_mask = extra["valid_mask"]
    if channel_ids.ndim != 1:
        raise MaterializedViewFormatError("channel_ids must have shape [C]")
    if valid_mask.dtype != np.bool_ or valid_mask.ndim != 2 or valid_mask.shape[0] != count:
        raise MaterializedViewFormatError("time-series valid_mask must be boolean [N, T]")
    sample_count = valid_mask.shape[1]
    expected_shape = (count, len(channel_ids), sample_count)
    for name, array in information.items():
        if array.shape != expected_shape:
            raise MaterializedViewFormatError(
                f"time-series information array {name!r} must have shape [N, C, T]"
            )
    time_axis = _load_time_axis(
        extra,
        count=count,
        sample_count=sample_count,
        descriptor=descriptor,
    )
    return TimeSeriesArrayView(
        binding_id=descriptor.binding_id,
        example_ids=example_ids,
        information=MappingProxyType(information),
        metadata=MappingProxyType(metadata),
        valid_mask=valid_mask,
        time_axis=time_axis,
        channel_ids=channel_ids,
    )


def _load_time_axis(
    extra: Mapping[str, np.ndarray],
    *,
    count: int,
    sample_count: int,
    descriptor: MaterializedAnalysisView,
) -> TimeAxis:
    explicit_keys = {
        "time",
        "time_certified_regular",
        "time_required_resolution_seconds",
    }
    regular_keys = {"time_start_seconds", "time_step_seconds"}
    has_explicit = bool(explicit_keys & set(extra))
    has_regular = bool(regular_keys & set(extra))
    if has_explicit == has_regular:
        raise MaterializedViewFormatError(
            "time-series materialization requires exactly one explicit or regular time axis"
        )
    if has_regular:
        if not regular_keys.issubset(extra):
            raise MaterializedViewFormatError("regular time axis requires start and step")
        start = extra["time_start_seconds"]
        step = extra["time_step_seconds"]
        if start.shape != (count,) or step.shape != (count,):
            raise MaterializedViewFormatError("regular time-axis fields must have shape [N]")
        if start.dtype != np.float64 or step.dtype != np.float64:
            raise MaterializedViewFormatError("regular time-axis fields must be float64 seconds")
        if not np.all(np.isfinite(start)):
            raise MaterializedViewFormatError("regular time-axis starts must be finite")
        if not np.all(np.isfinite(step)) or not np.all(step > 0):
            raise MaterializedViewFormatError("regular time-axis steps must be finite and positive")
        return RegularTimeAxis(
            start_seconds=start,
            step_seconds=step,
            sample_count=sample_count,
        )

    if not explicit_keys.issubset(extra):
        raise MaterializedViewFormatError(
            "explicit time axis requires timestamps and regularity certification"
        )
    time_values = extra["time"]
    certified_regular = extra["time_certified_regular"]
    required_resolution = extra["time_required_resolution_seconds"]
    precision_requirement = descriptor.time_precision_requirement
    if precision_requirement is None:
        raise MaterializedViewFormatError(
            "explicit time requires a certified time-precision requirement"
        )
    if time_values.shape != (count, sample_count):
        raise MaterializedViewFormatError("explicit time must have shape [N, T]")
    if time_values.dtype != np.float64:
        raise MaterializedViewFormatError("explicit time must be float64 seconds")
    if certified_regular.dtype != np.bool_ or certified_regular.shape != (count,):
        raise MaterializedViewFormatError(
            "explicit time regularity certification must be boolean [N]"
        )
    if required_resolution.dtype != np.float64 or required_resolution.shape != (count,):
        raise MaterializedViewFormatError("explicit time required resolution must be float64 [N]")
    if not np.all(np.isfinite(required_resolution)) or not np.all(required_resolution > 0):
        raise MaterializedViewFormatError(
            "explicit time required resolution must be finite and positive"
        )
    if isinstance(precision_requirement, FixedTimePrecisionRequirement) and not np.all(
        required_resolution == precision_requirement.required_resolution_seconds
    ):
        raise MaterializedViewFormatError(
            "explicit time resolution differs from its fixed upstream requirement"
        )
    worst_ulp = np.empty(count, dtype=np.float64)
    for example_index, values in enumerate(time_values):
        finite = values[np.isfinite(values)]
        if not len(finite):
            worst_ulp[example_index] = np.nan
            continue
        upward = np.nextafter(finite, np.inf) - finite
        downward = finite - np.nextafter(finite, -np.inf)
        worst_ulp[example_index] = float(np.max(np.maximum(upward, downward)))
        if worst_ulp[example_index] > required_resolution[example_index]:
            raise MaterializedViewFormatError(
                "explicit time float64 spacing exceeds required scientific resolution"
            )
    for example_index in np.flatnonzero(certified_regular):
        values = time_values[example_index]
        if not np.all(np.isfinite(values)):
            raise MaterializedViewFormatError(
                "certified-regular explicit timestamps must be finite"
            )
        deltas = np.diff(values)
        if not len(deltas) or not np.all(deltas > 0):
            raise MaterializedViewFormatError(
                "certified-regular explicit timestamps must be strictly increasing"
            )
        nominal = float(np.median(deltas))
        allowed_deviation = max(CADENCE_ATOL_SECONDS, CADENCE_RTOL * abs(nominal))
        if not np.all(np.abs(deltas - nominal) <= allowed_deviation):
            raise MaterializedViewFormatError(
                "explicit timestamps do not satisfy their regularity certification"
            )
    return ExplicitTimeAxis(
        time_seconds=time_values,
        certified_regular=certified_regular,
        required_resolution_seconds=required_resolution,
        worst_ulp_seconds=_readonly(worst_ulp),
    )
