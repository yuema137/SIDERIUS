from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from agent.data_analysis.view_formats import (
    ExplicitTimeAxis,
    MaterializedViewFormatError,
    RegularTimeAxis,
    load_materialized_view,
)
from agent.schemas.data_analysis.assets import (
    AnalysisAuthorizationReceipt,
    MaterializedAnalysisView,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef
from agent.schemas.data_analysis.time import TaskProvidedTimePrecisionRequirement


def _descriptor(path: Path, *, count: int) -> MaterializedAnalysisView:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    receipt = AnalysisAuthorizationReceipt(
        invocation_id="invocation-time-axis",
        binding_id="binding-series",
        slot_id="series",
        request_digest="1" * 64,
        policy_digest="2" * 64,
        asset_digest="3" * 64,
        authorized_at="2026-09-14T00:00:00+00:00",
    )
    with np.load(path, allow_pickle=False) as archive:
        has_explicit_time = "time" in archive.files
    return MaterializedAnalysisView(
        materialization_id="view-time-axis",
        invocation_id="invocation-time-axis",
        binding_id="binding-series",
        slot_id="series",
        asset_id="asset-series",
        split_id="validation",
        content_ref=CertifiedArtifactRef(
            logical_ref=path.name,
            sha256=digest,
            media_type="application/x-npz",
            byte_size=len(payload),
        ),
        format_id="siderius.timeseries-array.v1",
        time_precision_requirement=(
            TaskProvidedTimePrecisionRequirement(
                requirement_id="fixture-time-precision",
                source_sha256=digest,
            )
            if has_explicit_time
            else None
        ),
        population_unit="examples",
        total_available=count,
        materialized_count=count,
        certified_information=({"information_class": "data"},),
        selection_identity={
            "selection_id": "selection-time-axis",
            "selection_sha256": "4" * 64,
            "sampling_policy_sha256": "5" * 64,
            "sampling_mode": "full_if_feasible",
            "sampling_strategy": "uniform",
            "sampling_seed": 0,
            "population_unit": "examples",
            "total_available": count,
            "selected_count": count,
        },
        source_digests=(digest,),
        authorization_receipt=receipt,
    )


def _save_series(path: Path, values: np.ndarray, **axis_fields: np.ndarray) -> None:
    count, _channels, sample_count = values.shape
    np.savez(
        path,
        example_ids=np.asarray([f"example-{index}" for index in range(count)]),
        channel_ids=np.asarray(["signal"]),
        valid_mask=np.ones((count, sample_count), dtype=np.bool_),
        information__data=values,
        **axis_fields,
    )


def test_regular_axis_is_implicit_per_example_and_derives_sample_rate(tmp_path: Path) -> None:
    path = tmp_path / "regular.npz"
    values = np.ones((2, 1, 8), dtype=np.float64)
    _save_series(
        path,
        values,
        time_start_seconds=np.asarray([0.0, 12.5], dtype=np.float64),
        time_step_seconds=np.asarray([0.25, 0.002], dtype=np.float64),
    )

    loaded = load_materialized_view(_descriptor(path, count=2), path)

    assert isinstance(loaded.time_axis, RegularTimeAxis)
    assert loaded.time_axis.start_seconds.shape == (2,)
    assert not hasattr(loaded.time_axis, "sample_rate_hz_values")
    assert loaded.sample_rate_hz(0) == 4.0
    assert loaded.sample_rate_hz(1) == 500.0
    np.testing.assert_allclose(loaded.time_seconds(1), 12.5 + np.arange(8) * 0.002)
    assert loaded.time_seconds(1).flags.writeable is False


def test_explicit_regular_axis_is_equivalent_without_becoming_implicit(
    tmp_path: Path,
) -> None:
    regular_path = tmp_path / "regular.npz"
    explicit_path = tmp_path / "explicit.npz"
    values = np.ones((2, 1, 16), dtype=np.float64)
    starts = np.asarray([0.0, 100.0], dtype=np.float64)
    steps = np.asarray([0.125, 0.01], dtype=np.float64)
    explicit = starts[:, None] + np.arange(16, dtype=np.float64)[None, :] * steps[:, None]
    _save_series(
        regular_path,
        values,
        time_start_seconds=starts,
        time_step_seconds=steps,
    )
    _save_series(
        explicit_path,
        values,
        time=explicit,
        time_certified_regular=np.ones(2, dtype=np.bool_),
        time_required_resolution_seconds=np.full(2, 1e-12, dtype=np.float64),
    )

    regular = load_materialized_view(_descriptor(regular_path, count=2), regular_path)
    explicit_view = load_materialized_view(_descriptor(explicit_path, count=2), explicit_path)

    assert isinstance(explicit_view.time_axis, ExplicitTimeAxis)
    for index in range(2):
        np.testing.assert_allclose(
            regular.time_seconds(index),
            explicit_view.time_seconds(index),
            rtol=1e-7,
            atol=0.0,
        )
        assert explicit_view.is_time_certified_regular(index)
        assert explicit_view.sample_rate_hz(index) == pytest.approx(
            regular.sample_rate_hz(index), rel=1e-7
        )


def test_explicit_irregular_axis_preserves_order_and_is_not_upgraded(
    tmp_path: Path,
) -> None:
    path = tmp_path / "irregular.npz"
    values = np.ones((1, 1, 5), dtype=np.float64)
    source_order = np.asarray([[0.0, 0.2, 0.1, 0.35, 0.8]], dtype=np.float64)
    _save_series(
        path,
        values,
        time=source_order,
        time_certified_regular=np.zeros(1, dtype=np.bool_),
        time_required_resolution_seconds=np.asarray([1e-12], dtype=np.float64),
    )

    loaded = load_materialized_view(_descriptor(path, count=1), path)

    assert isinstance(loaded.time_axis, ExplicitTimeAxis)
    np.testing.assert_array_equal(loaded.time_seconds(0), source_order[0])
    assert not loaded.is_time_certified_regular(0)
    assert loaded.sample_rate_hz(0) is None


def test_loader_rejects_false_explicit_regularity_certification(tmp_path: Path) -> None:
    path = tmp_path / "false-regular.npz"
    _save_series(
        path,
        np.ones((1, 1, 5), dtype=np.float64),
        time=np.asarray([[0.0, 0.1, 0.21, 0.3, 0.4]], dtype=np.float64),
        time_certified_regular=np.ones(1, dtype=np.bool_),
        time_required_resolution_seconds=np.asarray([1e-12], dtype=np.float64),
    )

    with pytest.raises(MaterializedViewFormatError, match="regularity certification"):
        load_materialized_view(_descriptor(path, count=1), path)


def test_time_axis_requires_exactly_one_encoding_and_positive_step(tmp_path: Path) -> None:
    values = np.ones((1, 1, 4), dtype=np.float64)
    both = tmp_path / "both.npz"
    _save_series(
        both,
        values,
        time=np.asarray([[0.0, 0.1, 0.2, 0.3]], dtype=np.float64),
        time_certified_regular=np.ones(1, dtype=np.bool_),
        time_required_resolution_seconds=np.asarray([1e-12], dtype=np.float64),
        time_start_seconds=np.asarray([0.0], dtype=np.float64),
        time_step_seconds=np.asarray([0.1], dtype=np.float64),
    )
    with pytest.raises(MaterializedViewFormatError, match="exactly one"):
        load_materialized_view(_descriptor(both, count=1), both)

    invalid_step = tmp_path / "invalid-step.npz"
    _save_series(
        invalid_step,
        values,
        time_start_seconds=np.asarray([0.0], dtype=np.float64),
        time_step_seconds=np.asarray([0.0], dtype=np.float64),
    )
    with pytest.raises(MaterializedViewFormatError, match="finite and positive"):
        load_materialized_view(_descriptor(invalid_step, count=1), invalid_step)


def test_regular_axis_does_not_hide_masked_gaps(tmp_path: Path) -> None:
    path = tmp_path / "masked-regular.npz"
    mask = np.asarray([[True, True, False, True, True, True]], dtype=np.bool_)
    np.savez(
        path,
        example_ids=np.asarray(["example-0"]),
        channel_ids=np.asarray(["signal"]),
        valid_mask=mask,
        information__data=np.ones((1, 1, 6), dtype=np.float64),
        time_start_seconds=np.asarray([0.0], dtype=np.float64),
        time_step_seconds=np.asarray([0.1], dtype=np.float64),
    )

    loaded = load_materialized_view(_descriptor(path, count=1), path)

    assert loaded.is_time_certified_regular(0)
    np.testing.assert_array_equal(loaded.valid_mask, mask)
    assert not bool(np.all(loaded.valid_mask[0]))


def test_physical_frequency_is_stable_across_origins_and_sampling_rates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "multi-rate.npz"
    sample_count = 1_000
    starts = np.asarray([0.0, 50_000.0], dtype=np.float64)
    steps = np.asarray([1 / 50.0, 1 / 5_000.0], dtype=np.float64)
    physical_frequency_hz = 5.0
    relative = np.arange(sample_count, dtype=np.float64)[None, :] * steps[:, None]
    values = np.sin(2 * np.pi * physical_frequency_hz * relative)[:, None, :]
    _save_series(
        path,
        values,
        time_start_seconds=starts,
        time_step_seconds=steps,
    )
    loaded = load_materialized_view(_descriptor(path, count=2), path)

    recovered: list[float] = []
    for index in range(2):
        spectrum = np.abs(np.fft.rfft(loaded.information["data"][index, 0]))
        frequencies = np.fft.rfftfreq(
            sample_count,
            d=1.0 / float(loaded.sample_rate_hz(index)),
        )
        recovered.append(float(frequencies[np.argmax(spectrum[1:]) + 1]))
    assert recovered == pytest.approx([physical_frequency_hz, physical_frequency_hz])
    assert loaded.time_seconds(1)[0] == 50_000.0


def _local_worst_ulp(values: np.ndarray) -> float:
    upward = np.nextafter(values, np.inf) - values
    downward = values - np.nextafter(values, -np.inf)
    return float(np.max(np.maximum(upward, downward)))


def test_explicit_precision_requirement_passes_at_boundary_for_signed_times(
    tmp_path: Path,
) -> None:
    path = tmp_path / "precision-boundary.npz"
    times = np.asarray(
        [
            [-1_000_000.0, -0.5, 0.0, 0.5],
            [0.0, 1.0, 1_000.0, 1_000_000.0],
        ],
        dtype=np.float64,
    )
    requirements = np.asarray([_local_worst_ulp(row) for row in times], dtype=np.float64)
    _save_series(
        path,
        np.ones((2, 1, 4), dtype=np.float64),
        time=times,
        time_certified_regular=np.zeros(2, dtype=np.bool_),
        time_required_resolution_seconds=requirements,
    )

    loaded = load_materialized_view(_descriptor(path, count=2), path)

    assert isinstance(loaded.time_axis, ExplicitTimeAxis)
    np.testing.assert_array_equal(
        loaded.time_axis.required_resolution_seconds,
        requirements,
    )
    np.testing.assert_array_equal(loaded.time_axis.worst_ulp_seconds, requirements)


def test_explicit_precision_requirement_below_ulp_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "precision-inadequate.npz"
    times = np.asarray([[0.0, 1e12, 1e12]], dtype=np.float64)
    worst_ulp = _local_worst_ulp(times[0])
    _save_series(
        path,
        np.ones((1, 1, 3), dtype=np.float64),
        time=times,
        time_certified_regular=np.zeros(1, dtype=np.bool_),
        time_required_resolution_seconds=np.asarray(
            [np.nextafter(worst_ulp, 0.0)], dtype=np.float64
        ),
    )

    with pytest.raises(MaterializedViewFormatError, match="spacing exceeds"):
        load_materialized_view(_descriptor(path, count=1), path)


@pytest.mark.parametrize("invalid", [0.0, -1e-9, np.nan, np.inf])
def test_explicit_precision_requirement_must_be_finite_and_positive(
    tmp_path: Path,
    invalid: float,
) -> None:
    path = tmp_path / "invalid-requirement.npz"
    _save_series(
        path,
        np.ones((1, 1, 3), dtype=np.float64),
        time=np.asarray([[0.0, 0.1, 0.2]], dtype=np.float64),
        time_certified_regular=np.zeros(1, dtype=np.bool_),
        time_required_resolution_seconds=np.asarray([invalid], dtype=np.float64),
    )

    with pytest.raises(MaterializedViewFormatError, match="finite and positive"):
        load_materialized_view(_descriptor(path, count=1), path)


def test_repeated_explicit_timestamps_are_not_treated_as_source_precision_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "repeated.npz"
    times = np.asarray([[0.0, 0.1, 0.1, 0.2]], dtype=np.float64)
    _save_series(
        path,
        np.ones((1, 1, 4), dtype=np.float64),
        time=times,
        time_certified_regular=np.zeros(1, dtype=np.bool_),
        time_required_resolution_seconds=np.asarray([1e-12], dtype=np.float64),
    )

    loaded = load_materialized_view(_descriptor(path, count=1), path)

    np.testing.assert_array_equal(loaded.time_seconds(0), times[0])
    assert not loaded.is_time_certified_regular(0)


def test_precision_requirement_changes_materialized_view_identity(tmp_path: Path) -> None:
    first = tmp_path / "first.npz"
    second = tmp_path / "second.npz"
    fields = {
        "time": np.asarray([[0.0, 0.1, 0.2]], dtype=np.float64),
        "time_certified_regular": np.zeros(1, dtype=np.bool_),
    }
    _save_series(
        first,
        np.ones((1, 1, 3), dtype=np.float64),
        **fields,
        time_required_resolution_seconds=np.asarray([1e-10], dtype=np.float64),
    )
    _save_series(
        second,
        np.ones((1, 1, 3), dtype=np.float64),
        **fields,
        time_required_resolution_seconds=np.asarray([1e-9], dtype=np.float64),
    )

    first_view = _descriptor(first, count=1)
    second_view = _descriptor(second, count=1)

    assert first_view.content_ref.sha256 != second_view.content_ref.sha256
