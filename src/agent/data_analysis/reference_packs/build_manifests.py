"""Deterministically build checked-in reference-pack manifests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agent.data_analysis.discovery import compute_pack_content_sha256
from agent.schemas.data_analysis.common import canonical_json_bytes
from agent.schemas.data_analysis.skills import (
    InvocationMetadataSelection,
    NumericalTolerance,
    SkillCard,
    SkillContentFile,
    SkillDeclaration,
    SkillEntrypoint,
    SkillInputSlot,
    SkillPackManifest,
    implementation_identity_sha256,
)
from agent.schemas.data_analysis.view_formats import NUMERIC_ARRAY_V1, TIMESERIES_ARRAY_V1

ROOT = Path(__file__).resolve().parent
TOLERANCE = NumericalTolerance(rtol=1e-7, atol=0.0)


def _slot(
    slot_id: str,
    information_class: str,
    *,
    formats: tuple[str, ...],
    asset_types: tuple[str, ...],
) -> SkillInputSlot:
    return SkillInputSlot.model_validate(
        {
            "slot_id": slot_id,
            "description": f"Authorized {information_class} values for {slot_id}.",
            "accepted_asset_types": asset_types,
            "accepted_view_formats": formats,
            "required_information": [{"information_class": information_class}],
        }
    )


def _declaration(
    root: Path,
    skill_id: str,
    title: str,
    description: str,
    keywords: tuple[str, ...],
    slots: tuple[SkillInputSlot, ...],
    applicable_when: str,
    *,
    cost: str = "cheap",
    artifacts: tuple[str, ...] = ("table",),
) -> SkillDeclaration:
    relative_source = f"skills/{skill_id}.py"
    files = tuple(
        SkillContentFile(
            relative_path=relative,
            sha256=hashlib.sha256((root / relative).read_bytes()).hexdigest(),
        )
        for relative in (relative_source, "_shared.py")
    )
    return SkillDeclaration(
        card=SkillCard(
            skill_id=skill_id,
            title=title,
            one_line_description=description,
            keywords=keywords,
            aliases=(),
            tags=("scientific-analysis", root.name.replace("_", "-")),
            input_slots=slots,
            produced_artifact_types=artifacts,
            applicable_when=applicable_when,
            time_cost=cost,
            memory_cost="medium" if cost != "cheap" else "low",
            preferred_device="cpu",
            supports_sampling=True,
            skill_version="1.0.0",
            determinism="deterministic",
            numerical_tolerance=TOLERANCE,
        ),
        entrypoint=SkillEntrypoint(module_path=relative_source),
        implementation_files=files,
        implementation_sha256=implementation_identity_sha256(files),
    )


def _core_manifest(root: Path) -> SkillPackManifest:
    numeric_assets = (
        "dataset",
        "predictions",
        "residuals",
        "analysis_artifact",
        "evaluation_artifact",
    )
    generic_values = _slot(
        "values",
        "data",
        formats=(NUMERIC_ARRAY_V1, TIMESERIES_ARRAY_V1),
        asset_types=numeric_assets,
    )
    prediction = _slot(
        "predictions", "prediction", formats=(NUMERIC_ARRAY_V1,), asset_types=("predictions",)
    )
    target = _slot(
        "targets",
        "target",
        formats=(NUMERIC_ARRAY_V1,),
        asset_types=("dataset", "evaluation_artifact"),
    )
    metadata_slot = SkillInputSlot(
        slot_id="slice_metadata",
        description="One invocation-selected, explicitly authorized metadata field.",
        accepted_asset_types=("dataset", "evaluation_artifact"),
        accepted_view_formats=(NUMERIC_ARRAY_V1,),
        required_information=(),
        invocation_metadata_selection=InvocationMetadataSelection(
            minimum_fields=1,
            maximum_fields=1,
            parameter_name="metadata_field",
        ),
    )
    specifications = (
        (
            "summary_statistics",
            "Summary statistics",
            "Finite-value descriptive statistics with explicit quantiles.",
            (
                "summary",
                "statistics",
                "mean",
                "quantile",
                "central",
                "tendency",
                "spread",
                "variability",
                "overview",
                "measurements",
            ),
            (generic_values,),
            "Numeric values require a bounded descriptive summary.",
        ),
        (
            "nonfinite_and_missingness",
            "Nonfinite and missingness",
            "Separates unavailable positions from NaN and infinite observed values.",
            ("missing", "nonfinite", "nan", "quality"),
            (generic_values,),
            "Numeric or time-series data quality must be inspected without repair.",
        ),
        (
            "distribution_quantiles_and_outliers",
            "Distribution quantiles and outliers",
            "Quantiles and descriptive Tukey-fence outlier counts.",
            ("distribution", "quantile", "outlier", "iqr"),
            (generic_values,),
            "Distribution spread, tails, or descriptive outliers are relevant.",
        ),
        (
            "correlation_matrix",
            "Correlation matrix",
            "Pairwise-complete Pearson correlations with support counts.",
            ("correlation", "pearson", "relationship", "matrix"),
            (_slot("matrix", "data", formats=(NUMERIC_ARRAY_V1,), asset_types=numeric_assets),),
            "Aligned numeric variables are available for linear-association inspection.",
        ),
        (
            "performance_slice_summary",
            "Performance slice summary",
            "Scalar prediction error conditioned on one authorized metadata variable.",
            ("performance", "error", "slice", "metadata", "bias", "rmse"),
            (prediction, target, metadata_slot),
            "Aligned predictions, targets, and an authorized scientific metadata field are available.",
        ),
        (
            "prediction_target_distribution",
            "Prediction-target distribution",
            "Detects scalar-regression bias, range compression, and support mismatch.",
            ("prediction", "target", "distribution", "bias", "collapse"),
            (prediction, target),
            "Aligned scalar regression predictions and targets are available.",
        ),
    )
    skills = tuple(_declaration(root, *specification) for specification in specifications)
    return SkillPackManifest(
        pack_id="core-analysis",
        pack_version="1.0.0",
        title="Core analysis",
        description="Small generic deterministic numeric and model-diagnostic skill pack.",
        skills=skills,
        pack_content_sha256="0" * 64,
    )


def _time_manifest(root: Path) -> SkillPackManifest:
    data = _slot(
        "series",
        "data",
        formats=(TIMESERIES_ARRAY_V1,),
        asset_types=("dataset", "analysis_artifact", "evaluation_artifact"),
    )
    residual = _slot(
        "residuals",
        "residual",
        formats=(TIMESERIES_ARRAY_V1,),
        asset_types=("residuals", "evaluation_artifact"),
    )
    specifications = (
        (
            "sampling_cadence_and_gaps",
            "Sampling cadence and gaps",
            "Measures cadence regularity, gaps, and usable duration without repair.",
            (
                "sampling",
                "cadence",
                "gaps",
                "irregular",
                "interval",
                "spacing",
                "evenly",
                "duration",
                "measurements",
            ),
            (data,),
            "Any time-series view with certified timing and masks is available.",
            "cheap",
        ),
        (
            "temporal_stability_summary",
            "Temporal stability summary",
            "Windowed local statistics characterize drift without stationarity claims.",
            ("temporal", "drift", "stability", "window"),
            (data,),
            "Time-local mean, scale, or energy variation is relevant.",
            "moderate",
        ),
        (
            "autocorrelation",
            "Autocorrelation",
            "Normalized lag structure for complete certified-regular series.",
            (
                "autocorrelation",
                "lag",
                "memory",
                "periodic",
                "repeat",
                "recurring",
                "sequence",
                "characteristic",
            ),
            (data,),
            "A complete finite certified-regular series is available.",
            "moderate",
        ),
        (
            "fft_peak_summary",
            "FFT peak summary",
            "One-sided amplitude peaks for complete certified-regular real series.",
            (
                "fft",
                "spectrum",
                "frequency",
                "frequencies",
                "peak",
                "amplitude",
                "amplitudes",
                "sharp",
                "periodic",
                "components",
                "regularly",
                "sampled",
            ),
            (data,),
            "A complete finite certified-regular series is available.",
            "moderate",
        ),
        (
            "welch_psd",
            "Welch PSD",
            "One-sided power spectral density with explicit segment resolution.",
            ("welch", "psd", "noise", "power", "frequency"),
            (data,),
            "Regular finite series and an explicit nperseg are available.",
            "moderate",
        ),
        (
            "band_power_summary",
            "Band power summary",
            "Welch-integrated power in explicit physical-frequency bands.",
            ("band", "power", "frequency", "psd"),
            (data,),
            "Scientifically meaningful frequency bands and explicit nperseg are known.",
            "moderate",
        ),
        (
            "stft_energy_map",
            "STFT energy map",
            "Unpadded time-frequency energy for nonstationary regular signals.",
            (
                "stft",
                "time-frequency",
                "nonstationary",
                "spectrogram",
                "transient",
                "spectral",
                "sequence",
                "sweep",
                "evolves",
                "evolution",
                "changing",
                "dominant",
            ),
            (data,),
            "Time-varying frequency content is suspected and explicit nperseg is known.",
            "expensive",
        ),
        (
            "lomb_scargle_periodogram",
            "Lomb-Scargle periodogram",
            "Normalized periodic power for irregular samples on an explicit grid.",
            ("lomb-scargle", "irregular", "periodic", "frequency"),
            (data,),
            "Irregular timestamps and an explicit physical-frequency search grid are available.",
            "moderate",
        ),
        (
            "cross_correlation",
            "Cross-correlation",
            "Lag correlation for an explicit ordered channel pair.",
            ("cross-correlation", "lag", "channels", "delay"),
            (data,),
            "Two complete finite channels share a certified regular axis.",
            "moderate",
        ),
        (
            "magnitude_squared_coherence",
            "Magnitude-squared coherence",
            "Frequency-localized dependence for an explicit channel pair.",
            (
                "coherence",
                "channels",
                "frequency",
                "frequencies",
                "relationship",
                "shared",
                "common",
                "oscillatory",
                "sensors",
                "localized",
                "variation",
            ),
            (data,),
            "Two complete regular channels and explicit nperseg are available.",
            "moderate",
        ),
        (
            "residual_spectrum",
            "Residual spectrum",
            "Welch spectral structure in already-certified residual series.",
            (
                "residual",
                "residuals",
                "error",
                "prediction",
                "spectrum",
                "spectrally",
                "frequencies",
                "white",
                "structured",
                "unexplained",
                "psd",
            ),
            (residual,),
            "A complete certified residual time-series artifact already exists.",
            "moderate",
        ),
    )
    skills = tuple(
        _declaration(root, *specification[:6], cost=specification[6])
        for specification in specifications
    )
    return SkillPackManifest(
        pack_id="time-series",
        pack_version="1.0.0",
        title="Time-series analysis",
        description="Small generic deterministic scientific time-series skill pack.",
        skills=skills,
        pack_content_sha256="0" * 64,
    )


def write_manifests() -> None:
    for directory, builder in (("core_analysis", _core_manifest), ("time_series", _time_manifest)):
        root = ROOT / directory
        manifest_path = root / "manifest.json"
        manifest = builder(root)
        manifest = manifest.model_copy(
            update={
                "pack_content_sha256": compute_pack_content_sha256(
                    root, manifest, manifest_path=manifest_path
                )
            }
        )
        manifest_path.write_bytes(canonical_json_bytes(manifest))


if __name__ == "__main__":
    write_manifests()
