from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pytest

from agent.data_analysis.discovery import discover_skills, search_skill_cards
from agent.data_analysis.loader import load_selected_skill
from agent.data_analysis.reference_packs import builtin_pack_refs
from agent.data_analysis.skill_runtime import SkillRuntime
from agent.schemas.data_analysis.assets import (
    AnalysisAuthorizationReceipt,
    MaterializedAnalysisView,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef
from agent.schemas.data_analysis.skills import ArtifactOutputContract, SkillInput
from agent.schemas.data_analysis.time import FixedTimePrecisionRequirement


def _snapshot():
    return discover_skills(builtin_pack_refs("core-analysis", "time-series"))


def _skill(skill_id: str):
    return next(item for item in _snapshot().skills if item.card.skill_id == skill_id)


def _descriptor(
    path: Path,
    *,
    binding_id: str,
    slot_id: str,
    format_id: str,
    certified_information: tuple[dict, ...],
    count: int,
    precision=None,
) -> MaterializedAnalysisView:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    return MaterializedAnalysisView(
        materialization_id=f"materialization-{binding_id}",
        invocation_id="reference-invocation",
        binding_id=binding_id,
        slot_id=slot_id,
        asset_id=f"asset-{binding_id}",
        split_id="validation",
        content_ref=CertifiedArtifactRef(
            logical_ref=path.name,
            sha256=digest,
            media_type="application/x-npz",
            byte_size=len(payload),
        ),
        format_id=format_id,
        time_precision_requirement=precision,
        population_unit="examples",
        total_available=count,
        materialized_count=count,
        certified_information=certified_information,
        selection_identity={
            "selection_id": "shared-selection",
            "selection_sha256": "4" * 64,
            "sampling_policy_sha256": "5" * 64,
            "sampling_mode": "full_if_feasible",
            "sampling_strategy": "uniform",
            "sampling_seed": 17,
            "population_unit": "examples",
            "total_available": count,
            "selected_count": count,
        },
        source_digests=(digest,),
        authorization_receipt=AnalysisAuthorizationReceipt(
            invocation_id="reference-invocation",
            binding_id=binding_id,
            slot_id=slot_id,
            request_digest="1" * 64,
            policy_digest="2" * 64,
            asset_digest="3" * 64,
            authorized_at="2026-09-14T00:00:00+00:00",
        ),
    )


def _run(tmp_path: Path, skill_id: str, parameters: dict, views_and_paths):
    discovered = _skill(skill_id)
    loaded = load_selected_skill(discovered)
    validated = loaded.validate_parameters(parameters)
    views = tuple(item[0] for item in views_and_paths)
    output = tmp_path / f"out-{skill_id}"
    output.mkdir()
    skill_input = SkillInput(
        invocation_id="reference-invocation",
        skill_identity=discovered.identity,
        materializations=views,
        question_ids=("question",),
        deadline_monotonic_s=time.monotonic() + 30,
        artifact_output_contract=ArtifactOutputContract(
            output_directory_ref=str(output),
            allowed_media_types=("application/json",),
        ),
    )
    runtime = SkillRuntime(
        materialization_paths={view.binding_id: str(path) for view, path in views_and_paths},
        materializations=views,
        artifact_directory=str(output),
    )
    payload = loaded.run(skill_input, validated, runtime)
    result_path = output / payload.produced_artifacts[0].relative_path
    return payload, json.loads(result_path.read_text())


def _regular_view(tmp_path: Path, values: np.ndarray, step: float, *, information="data"):
    path = tmp_path / f"regular-{information}-{len(list(tmp_path.iterdir()))}.npz"
    count, channels, length = values.shape
    np.savez(
        path,
        example_ids=np.asarray([f"example-{index}" for index in range(count)]),
        channel_ids=np.asarray([f"channel-{index}" for index in range(channels)]),
        valid_mask=np.ones((count, length), dtype=np.bool_),
        **{f"information__{information}": values},
        time_start_seconds=np.zeros(count, dtype=np.float64),
        time_step_seconds=np.full(count, step, dtype=np.float64),
    )
    descriptor = _descriptor(
        path,
        binding_id="binding-series" if information == "data" else "binding-residuals",
        slot_id="series" if information == "data" else "residuals",
        format_id="siderius.timeseries-array.v1",
        certified_information=({"information_class": information},),
        count=count,
    )
    return descriptor, path


def _scalar_model_views(
    tmp_path: Path,
    *,
    prediction: np.ndarray,
    target: np.ndarray,
    metadata: np.ndarray | None = None,
):
    count = len(target)
    entries = []
    for binding, slot, information, values in (
        ("binding-prediction", "predictions", "prediction", prediction),
        ("binding-target", "targets", "target", target),
    ):
        path = tmp_path / f"{binding}.npz"
        np.savez(path, example_ids=np.arange(count), **{f"information__{information}": values})
        entries.append(
            (
                _descriptor(
                    path,
                    binding_id=binding,
                    slot_id=slot,
                    format_id="siderius.numeric-array.v1",
                    certified_information=({"information_class": information},),
                    count=count,
                ),
                path,
            )
        )
    if metadata is not None:
        path = tmp_path / "binding-metadata.npz"
        np.savez(path, example_ids=np.arange(count), metadata__x=metadata)
        entries.append(
            (
                _descriptor(
                    path,
                    binding_id="binding-metadata",
                    slot_id="slice_metadata",
                    format_id="siderius.numeric-array.v1",
                    certified_information=({"information_class": "metadata", "fields": ["x"]},),
                    count=count,
                ),
                path,
            )
        )
    return tuple(entries)


def test_reference_inventory_is_discoverable_without_task_specific_api() -> None:
    snapshot = _snapshot()
    assert len(snapshot.skills) == 17
    forbidden = ("ligo", "tess", "tidmad", "project 8")
    for skill in snapshot.skills:
        serialized = json.dumps(skill.card.model_dump(mode="json")).casefold()
        assert not any(name in serialized for name in forbidden)

    assert search_skill_cards(snapshot, "timestamps irregular periodic structure")[
        0
    ].card.skill_id in {
        "sampling_cadence_and_gaps",
        "lomb_scargle_periodogram",
    }
    assert (
        search_skill_cards(snapshot, "channels share frequency structure")[0].card.skill_id
        == "magnitude_squared_coherence"
    )
    assert (
        search_skill_cards(snapshot, "model error changes with metadata")[0].card.skill_id
        == "performance_slice_summary"
    )


def test_every_reference_skill_resolves_an_agent_usable_interface() -> None:
    for discovered in _snapshot().skills:
        interface = load_selected_skill(discovered).resolved_interface()
        assert interface.selected_skill_instructions.strip()
        for name, property_schema in interface.parameter_json_schema.get("properties", {}).items():
            assert property_schema.get("description"), (
                f"{discovered.card.skill_id}.{name} lacks an LLM-facing description"
            )


@pytest.mark.parametrize(
    "step,frequency",
    [(1e-9, 125_000_000.0), (1e-3, 125.0), (60.0, 1 / 480.0), (86400.0, 1 / (8 * 86400.0))],
)
def test_fft_recovers_physical_frequency_across_time_scales(
    tmp_path: Path, step: float, frequency: float
) -> None:
    length = 1024
    time_values = np.arange(length) * step
    values = np.sin(2 * np.pi * frequency * time_values)[None, None, :]
    view = _regular_view(tmp_path, values, step)
    _payload, result = _run(tmp_path, "fft_peak_summary", {"maximum_peaks": 3}, (view,))
    peak = result["per_series"][0]["peaks"][0]["frequency_hz"]
    assert peak == pytest.approx(frequency, rel=1e-12)


def test_irregular_periodicity_uses_lomb_scargle_and_regular_fft_is_inapplicable(
    tmp_path: Path,
) -> None:
    rng = np.random.default_rng(12)
    count, length = 1, 600
    timestamps = np.sort(np.arange(length) * 0.1 + rng.normal(0, 0.015, length))[None, :]
    frequency = 1.75
    values = np.sin(2 * np.pi * frequency * timestamps)[:, None, :]
    path = tmp_path / "irregular.npz"
    np.savez(
        path,
        example_ids=np.asarray(["example-0"]),
        channel_ids=np.asarray(["channel-0"]),
        valid_mask=np.ones((count, length), dtype=np.bool_),
        information__data=values,
        time=timestamps.astype(np.float64),
        time_certified_regular=np.zeros(count, dtype=np.bool_),
        time_required_resolution_seconds=np.full(count, 1e-12, dtype=np.float64),
    )
    descriptor = _descriptor(
        path,
        binding_id="binding-series",
        slot_id="series",
        format_id="siderius.timeseries-array.v1",
        certified_information=({"information_class": "data"},),
        count=count,
        precision=FixedTimePrecisionRequirement(required_resolution_seconds=1e-12),
    )
    _payload, fft = _run(tmp_path, "fft_peak_summary", {}, ((descriptor, path),))
    assert "not certified regular" in fft["per_series"][0]["unusable_reason"]
    _payload, lomb = _run(
        tmp_path,
        "lomb_scargle_periodogram",
        {"minimum_frequency_hz": 0.5, "maximum_frequency_hz": 3.0, "frequency_count": 2000},
        ((descriptor, path),),
    )
    assert lomb["per_series"][0]["peaks"][0]["frequency_hz"] == pytest.approx(frequency, abs=0.01)


def test_delayed_coherent_channels_recover_positive_lag_and_frequency(tmp_path: Path) -> None:
    rng = np.random.default_rng(4)
    length = 2048
    step = 0.01
    delay = 7
    base = np.sin(2 * np.pi * 4 * np.arange(length) * step) + 0.2 * rng.normal(size=length)
    delayed = np.concatenate((np.zeros(delay), base[:-delay]))
    values = np.stack((base, delayed))[None, :, :]
    view = _regular_view(tmp_path, values, step)
    _payload, lag = _run(
        tmp_path,
        "cross_correlation",
        {
            "first_channel_id": "channel-0",
            "second_channel_id": "channel-1",
            "maximum_lag_samples": 20,
        },
        (view,),
    )
    assert lag["per_example"][0]["peak_lag_samples"] == delay
    _payload, coherence = _run(
        tmp_path,
        "magnitude_squared_coherence",
        {"first_channel_id": "channel-0", "second_channel_id": "channel-1", "nperseg": 256},
        (view,),
    )
    record = coherence["per_example"][0]
    peak = record["frequency_hz"][int(np.argmax(record["coherence"]))]
    assert peak == pytest.approx(4.0, abs=0.5)


def test_prediction_diagnostics_are_generic_and_sparse_groups_are_suppressed(
    tmp_path: Path,
) -> None:
    count = 60
    target = np.linspace(-2, 2, count)
    prediction = 0.6 * target + 0.4
    metadata = np.linspace(0, 1, count)
    entries = []
    for binding, slot, information, values in (
        ("binding-prediction", "predictions", "prediction", prediction),
        ("binding-target", "targets", "target", target),
    ):
        path = tmp_path / f"{binding}.npz"
        np.savez(path, example_ids=np.arange(count), **{f"information__{information}": values})
        entries.append(
            (
                _descriptor(
                    path,
                    binding_id=binding,
                    slot_id=slot,
                    format_id="siderius.numeric-array.v1",
                    certified_information=({"information_class": information},),
                    count=count,
                ),
                path,
            )
        )
    metadata_path = tmp_path / "metadata.npz"
    np.savez(metadata_path, example_ids=np.arange(count), metadata__x=metadata)
    entries.append(
        (
            _descriptor(
                metadata_path,
                binding_id="binding-metadata",
                slot_id="slice_metadata",
                format_id="siderius.numeric-array.v1",
                certified_information=({"information_class": "metadata", "fields": ["x"]},),
                count=count,
            ),
            metadata_path,
        )
    )
    distribution_payload, distribution = _run(
        tmp_path, "prediction_target_distribution", {}, tuple(entries[:2])
    )
    assert distribution["standard_deviation_ratio"] == pytest.approx(0.6)
    assert {item.result_key: item.value for item in distribution_payload.quantitative_results}[
        "standard_deviation_ratio"
    ] == pytest.approx(0.6)
    sliced_payload, sliced = _run(
        tmp_path,
        "performance_slice_summary",
        {
            "metadata_field": "x",
            "grouping": "quantile",
            "quantile_group_count": 5,
            "minimum_examples_per_group": 20,
        },
        tuple(entries),
    )
    assert all(group["metrics"] is None for group in sliced["groups"])
    assert all(group["suppression_reason"] == "insufficient_support" for group in sliced["groups"])
    canonical = {item.result_key: item.value for item in sliced_payload.quantitative_results}
    for index, group in enumerate(sliced["groups"]):
        assert canonical[f"group.{index}.label"] == group["label"]
        assert canonical[f"group.{index}.count"] == group["count"]
        assert canonical[f"group.{index}.metrics_suppression_reason"] == ("insufficient_support")


def test_performance_slice_canonical_evidence_matches_artifact_and_exposes_extremes(
    tmp_path: Path,
) -> None:
    count = 90
    target = np.linspace(-2.0, 2.0, count)
    metadata = np.linspace(0.0, 1.0, count)
    prediction = target + metadata**2
    payload, artifact = _run(
        tmp_path,
        "performance_slice_summary",
        {
            "metadata_field": "x",
            "grouping": "quantile",
            "quantile_group_count": 3,
            "minimum_examples_per_group": 10,
        },
        _scalar_model_views(
            tmp_path,
            prediction=prediction,
            target=target,
            metadata=metadata,
        ),
    )
    canonical = {item.result_key: item.value for item in payload.quantitative_results}
    assert canonical["group_count"] == 3
    for index, group in enumerate(artifact["groups"]):
        assert canonical[f"group.{index}.label"] == group["label"]
        assert canonical[f"group.{index}.count"] == group["count"]
        for metric in ("bias", "mae", "rmse", "r_squared"):
            assert canonical[f"group.{index}.{metric}"] == pytest.approx(group["metrics"][metric])
    rmse_by_group = [canonical[f"group.{index}.rmse"] for index in range(3)]
    assert int(np.argmax(rmse_by_group)) == 2
    assert int(np.argmin(rmse_by_group)) == 0


@pytest.mark.parametrize(
    ("prediction", "target", "expected_bias", "expected_ratio"),
    (
        (
            np.linspace(-2.0, 2.0, 80),
            np.linspace(-2.0, 2.0, 80),
            0.0,
            1.0,
        ),
        (
            0.5 * np.linspace(-2.0, 2.0, 80) + 0.3,
            np.linspace(-2.0, 2.0, 80),
            0.3,
            0.5,
        ),
    ),
)
def test_prediction_distribution_exposes_signed_bias_and_spread_evidence(
    tmp_path: Path,
    prediction: np.ndarray,
    target: np.ndarray,
    expected_bias: float,
    expected_ratio: float,
) -> None:
    payload, artifact = _run(
        tmp_path,
        "prediction_target_distribution",
        {},
        _scalar_model_views(tmp_path, prediction=prediction, target=target),
    )
    canonical = {item.result_key: item.value for item in payload.quantitative_results}
    assert canonical["bias"] == pytest.approx(expected_bias, abs=1e-12)
    assert canonical["standard_deviation_ratio"] == pytest.approx(expected_ratio)
    assert canonical["robust_span_ratio"] == pytest.approx(expected_ratio)
    assert canonical["prediction.mean"] == pytest.approx(artifact["prediction"]["mean"])
    assert canonical["target.mean"] == pytest.approx(artifact["target"]["mean"])
    assert "standard_deviation_ratio_suppression_reason" not in canonical
    assert "robust_span_ratio_suppression_reason" not in canonical


def test_prediction_distribution_suppresses_degenerate_target_spread(tmp_path: Path) -> None:
    target = np.ones(40)
    prediction = np.linspace(0.8, 1.2, 40)
    payload, artifact = _run(
        tmp_path,
        "prediction_target_distribution",
        {},
        _scalar_model_views(tmp_path, prediction=prediction, target=target),
    )
    canonical = {item.result_key: item.value for item in payload.quantitative_results}
    assert canonical["standard_deviation_ratio"] is None
    assert canonical["robust_span_ratio"] is None
    assert (
        canonical["standard_deviation_ratio_suppression_reason"]
        == (artifact["standard_deviation_ratio_suppression_reason"])
    )
    assert (
        canonical["robust_span_ratio_suppression_reason"]
        == (artifact["robust_span_ratio_suppression_reason"])
    )


def test_core_distribution_quality_and_correlation_skills(tmp_path: Path) -> None:
    values = np.asarray([[1.0, 2.0], [2.0, 4.0], [3.0, np.nan], [100.0, 200.0]], dtype=np.float64)
    path = tmp_path / "matrix.npz"
    np.savez(
        path,
        example_ids=np.arange(4),
        information__data=values,
        valid_mask=np.asarray([True, True, True, False]),
    )
    descriptor = _descriptor(
        path,
        binding_id="binding-values",
        slot_id="values",
        format_id="siderius.numeric-array.v1",
        certified_information=({"information_class": "data"},),
        count=4,
    )
    _payload, summary = _run(tmp_path, "summary_statistics", {}, ((descriptor, path),))
    assert summary["count"] == 5
    assert summary["nonfinite_count"] == 1
    _payload, missing = _run(tmp_path, "nonfinite_and_missingness", {}, ((descriptor, path),))
    assert missing["mask_false_count"] == 2
    assert missing["nan_count"] == 1
    _payload, outliers = _run(
        tmp_path,
        "distribution_quantiles_and_outliers",
        {},
        ((descriptor, path),),
    )
    assert outliers["count"] == 5

    matrix_descriptor = _descriptor(
        path,
        binding_id="binding-matrix",
        slot_id="matrix",
        format_id="siderius.numeric-array.v1",
        certified_information=({"information_class": "data"},),
        count=4,
    )
    _payload, correlation = _run(tmp_path, "correlation_matrix", {}, ((matrix_descriptor, path),))
    assert correlation["pearson_correlation"][0][1] == pytest.approx(1.0)
    assert correlation["pair_counts"][0][1] == 3


def test_regular_spectral_and_temporal_toolbox_on_generic_signal(tmp_path: Path) -> None:
    sample_rate = 128.0
    length = 2048
    time_values = np.arange(length) / sample_rate
    amplitude = np.where(time_values < time_values[-1] / 2, 1.0, 2.0)
    values = (amplitude * np.sin(2 * np.pi * 8.0 * time_values))[None, None, :]
    view = _regular_view(tmp_path, values, 1 / sample_rate)

    sampling_payload, sampling = _run(tmp_path, "sampling_cadence_and_gaps", {}, (view,))
    assert sampling["examples"][0]["uniform"] is True
    assert sampling["examples"][0]["gap_count"] == 0
    assert sampling_payload.quantitative_results

    stability_payload, stability = _run(
        tmp_path,
        "temporal_stability_summary",
        {"window_count": 4},
        (view,),
    )
    assert stability["per_series"][0]["window_scale_range"] > 0.5
    assert stability_payload.quantitative_results

    autocorrelation_payload, autocorrelation = _run(
        tmp_path,
        "autocorrelation",
        {"maximum_lag_samples": 64},
        (view,),
    )
    assert autocorrelation["per_series"][0]["coefficients"][0] == 1.0
    assert autocorrelation_payload.quantitative_results

    welch_payload, welch = _run(tmp_path, "welch_psd", {"nperseg": 512}, (view,))
    assert welch["per_series"][0]["frequency_resolution_hz"] == pytest.approx(0.25)
    assert welch["per_series"][0]["peaks"][0]["frequency_hz"] == pytest.approx(8.0)
    assert any(
        item.result_key.endswith("dominant_frequency_hz.median")
        for item in welch_payload.quantitative_results
    )

    band_payload, bands = _run(
        tmp_path,
        "band_power_summary",
        {
            "nperseg": 512,
            "bands": [
                {"name": "near", "minimum_hz": 6.0, "maximum_hz": 10.0},
                {"name": "far", "minimum_hz": 20.0, "maximum_hz": 30.0},
            ],
        },
        (view,),
    )
    assert bands["per_series"][0]["bands"][0]["power"] > bands["per_series"][0]["bands"][1]["power"]
    assert any("band.near.power" in item.result_key for item in band_payload.quantitative_results)

    stft_payload, stft = _run(tmp_path, "stft_energy_map", {"nperseg": 256}, (view,))
    assert stft["boundary"] is None
    assert stft["padded"] is False
    assert stft["per_series"][0]["usable_segment_count"] > 1
    assert stft_payload.quantitative_results


def test_residual_spectrum_consumes_certified_residuals_without_inference(tmp_path: Path) -> None:
    step = 0.01
    length = 2048
    frequency = 12.0
    residual = np.sin(2 * np.pi * frequency * np.arange(length) * step)[None, None, :]
    view = _regular_view(tmp_path, residual, step, information="residual")
    payload, result = _run(tmp_path, "residual_spectrum", {"nperseg": 512}, (view,))
    assert result["per_series"][0]["peaks"][0]["frequency_hz"] == pytest.approx(frequency, abs=0.25)
    assert result["residual_definition"] == "task-provenance-owned"
    assert any(
        item.result_key.endswith("dominant_frequency_hz.median")
        for item in payload.quantitative_results
    )
