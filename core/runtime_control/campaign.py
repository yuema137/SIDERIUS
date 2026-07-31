"""C12 validation campaign — matrix, typed results, and verdict (C12-A/C).

The campaign answers a question C10 deliberately did not: is the
estimator ACCURATE, across families, scales and concurrency regimes?

Structure of one cell:

```text
bounded live probe  ->  runtime projection
                    ->  bounded real execution (wall-capped)
                    ->  comparison  ->  ratios
```

Two rules the schemas enforce rather than assume:

* training and inference stay separate — a cell records both, never a
  blend, and the inference work unit is named on the record so a later
  reader cannot mistake batches for segments;
* a cell whose evidence is not measurement-backed cannot contribute to
  the verdict. The legacy static/fallback path can never appear as
  campaign evidence: `CampaignCell` rejects a non-measured provenance.

Per-cell results are written the moment they exist, so a failure at cell
9 never erases cells 1-8.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.records import MEASUREMENT_BACKED_SOURCES

CampaignTrack = Literal["A_matrix", "B_legacy_fcnet", "C_pairwise"]
CellStatus = Literal["ok", "measured_failure", "infrastructure_failure", "skipped"]

#: The C12-A matrix: three genuinely different compute structures, four
#: scales each, all from EXISTING registered implementations. Every
#: config below was resolved by searching the family's own VALIDATED
#: config bounds — no bound was raised to make a cell fit.
MATRIX: tuple[dict[str, Any], ...] = (
    # --- punet: convolutional / U-Net-like ---
    {
        "family": "punet",
        "target": 50_000,
        "realized": 69_328,
        "config": {"segmentation_size": 40000, "multi": 16, "depth": 2, "embedding_dim": 8},
    },
    {
        "family": "punet",
        "target": 500_000,
        "realized": 422_248,
        "config": {"segmentation_size": 40000, "multi": 40, "depth": 2, "embedding_dim": 32},
    },
    {
        "family": "punet",
        "target": 5_000_000,
        "realized": 4_297_024,
        "config": {"segmentation_size": 40000, "multi": 64, "depth": 3, "embedding_dim": 32},
    },
    {
        "family": "punet",
        "target": 20_000_000,
        "realized": 17_277_760,
        "config": {"segmentation_size": 40000, "multi": 64, "depth": 4, "embedding_dim": 32},
    },
    # --- wavenet: dilated temporal convolution ---
    {
        "family": "wavenet",
        "target": 50_000,
        "realized": 49_680,
        "config": {
            "segmentation_size": 40000,
            "residual_channels": 32,
            "gate_channels": 16,
            "skip_channels": 16,
            "num_blocks": 6,
        },
    },
    {
        "family": "wavenet",
        "target": 500_000,
        "realized": 500_448,
        "config": {
            "segmentation_size": 40000,
            "residual_channels": 16,
            "gate_channels": 128,
            "skip_channels": 16,
            "num_blocks": 14,
        },
    },
    {
        "family": "wavenet",
        "target": 5_000_000,
        "realized": 5_000_704,
        "config": {
            "segmentation_size": 40000,
            "input_channels": 32,
            "residual_channels": 128,
            "gate_channels": 128,
            "skip_channels": 128,
            "num_blocks": 14,
            "kernel_size": 20,
        },
    },
    {
        "family": "wavenet",
        "target": 20_000_000,
        "realized": 20_033_952,
        "config": {
            "segmentation_size": 40000,
            "input_channels": 16,
            "residual_channels": 128,
            "gate_channels": 256,
            "skip_channels": 96,
            "num_blocks": 18,
            "kernel_size": 32,
        },
    },
    # --- transformer: token-mixer / sequence model ---
    {
        "family": "transformer",
        "target": 50_000,
        "realized": 50_816,
        "config": {
            "segmentation_size": 20000,
            "embedding_dim": 32,
            "nhead": 4,
            "num_layers": 4,
            "dim_feedforward": 64,
        },
    },
    {
        "family": "transformer",
        "target": 500_000,
        "realized": 531_072,
        "config": {
            "segmentation_size": 20000,
            "embedding_dim": 64,
            "nhead": 4,
            "num_layers": 6,
            "dim_feedforward": 512,
        },
    },
    {
        "family": "transformer",
        "target": 5_000_000,
        "realized": 4_869_888,
        "config": {
            "segmentation_size": 20000,
            "embedding_dim": 256,
            "nhead": 4,
            "num_layers": 6,
            "dim_feedforward": 1024,
        },
    },
    # The transformer family's VALIDATED ceiling is ~8.03M
    # (embedding_dim<=256, num_layers<=10, dim_feedforward<=1024). Raising
    # a scientific config bound to manufacture a 20M cell is not a
    # validation decision, so the top cell is the real ceiling and is
    # labeled as such.
    {
        "family": "transformer",
        "target": 20_000_000,
        "realized": 8_028_928,
        "at_family_ceiling": True,
        "config": {
            "segmentation_size": 20000,
            "embedding_dim": 256,
            "nhead": 8,
            "num_layers": 10,
            "dim_feedforward": 1024,
        },
    },
)

#: C12-C pairs: small, large, and heterogeneous — drawn from the matrix.
PAIRWISE_PAIRS: tuple[dict[str, Any], ...] = (
    {"label": "small_homogeneous", "members": ("punet@50K", "wavenet@50K")},
    {"label": "large_homogeneous", "members": ("punet@20M", "wavenet@20M")},
    {"label": "heterogeneous", "members": ("punet@5M", "transformer@5M")},
)


class CellMeasurement(BaseModel):
    """Everything measured for one cell. Training and inference separate."""

    model_config = ConfigDict(frozen=True)

    provenance: str
    setup_seconds: float | None = Field(default=None, ge=0.0)
    data_indexing_seconds: float | None = Field(default=None, ge=0.0)
    train_ms_per_step: float | None = Field(default=None, gt=0.0)
    inference_ms_per_unit: float | None = Field(default=None, gt=0.0)
    inference_work_unit: str = Field(
        default="inference_batch",
        description="What one inference unit IS. Named so a reader cannot "
        "mistake batches for segments when comparing cells.",
    )
    peak_vram_allocated_gb: float | None = Field(default=None, gt=0.0)
    peak_vram_reserved_gb: float | None = Field(default=None, gt=0.0)
    realized_parameter_count: int | None = Field(default=None, gt=0)
    trainable_parameter_count: int | None = Field(default=None, ge=0)
    parameter_memory_gb: float | None = Field(default=None, gt=0.0)
    dtype: str | None = None
    concurrency_identity: str | None = None

    @model_validator(mode="after")
    def _measurement_backed_only(self) -> CellMeasurement:
        if self.provenance not in MEASUREMENT_BACKED_SOURCES:
            raise ValueError(
                f"campaign evidence must be measurement-backed; {self.provenance!r} "
                "is a prior. The legacy static/fallback path can never appear as "
                "campaign evidence."
            )
        return self


class CampaignCell(BaseModel):
    """One matrix cell: what was projected, what actually happened."""

    model_config = ConfigDict(frozen=True)

    track: CampaignTrack
    cell_id: str
    family: str
    target_parameter_count: int | None = None
    at_family_ceiling: bool = False
    status: CellStatus = "ok"
    failure_detail: str = ""

    probe: CellMeasurement | None = None
    projected_seconds: float | None = Field(default=None, gt=0.0)
    actual_seconds: float | None = Field(default=None, gt=0.0)
    actual_steps: int | None = Field(default=None, ge=0)
    actual_ms_per_step: float | None = Field(default=None, gt=0.0)
    predicted_peak_vram_gb: float | None = Field(default=None, gt=0.0)
    actual_peak_vram_gb: float | None = Field(default=None, gt=0.0)

    applicability: str | None = None
    calibration_identity: str | None = None
    hardware_profile_id: str | None = None
    environment_profile_id: str | None = None
    observation_ids: tuple[str, ...] = ()
    wall_cap_seconds: float | None = None

    @property
    def runtime_error_ratio(self) -> float | None:
        """projected / actual. >1 over-predicts, <1 UNDER-predicts."""
        if not self.projected_seconds or not self.actual_seconds:
            return None
        return self.projected_seconds / self.actual_seconds

    @property
    def underprediction_ratio(self) -> float | None:
        """actual / projected — how many times longer reality took."""
        ratio = self.runtime_error_ratio
        return (1.0 / ratio) if ratio else None

    @property
    def absolute_percentage_error(self) -> float | None:
        """|projected - actual| / actual, in percent. Actual is the
        denominator: the question is how wrong the prediction was about
        reality, not how wrong reality was about the prediction."""
        if not self.projected_seconds or not self.actual_seconds:
            return None
        return abs(self.projected_seconds - self.actual_seconds) / self.actual_seconds * 100.0

    @property
    def vram_underprediction_gb(self) -> float | None:
        if self.predicted_peak_vram_gb is None or self.actual_peak_vram_gb is None:
            return None
        return max(0.0, self.actual_peak_vram_gb - self.predicted_peak_vram_gb)

    @property
    def contributes_to_verdict(self) -> bool:
        """Only a completed, measured cell can support or refute a
        threshold. A measured FAILURE (OOM/wall-cap) is real evidence
        about the candidate but carries no accuracy datum."""
        return self.status == "ok" and self.absolute_percentage_error is not None


def write_cell(output_root: Path, cell: CampaignCell) -> Path:
    """Persist one cell IMMEDIATELY. A later failure never erases it."""
    directory = output_root / cell.track
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cell.cell_id}.json"
    path.write_text(json.dumps(cell.model_dump(mode="json"), indent=2))
    return path


def load_cells(output_root: Path) -> list[CampaignCell]:
    """Every cell recorded so far, across tracks."""
    cells: list[CampaignCell] = []
    for path in sorted(output_root.rglob("*.json")):
        if path.name.startswith("verdict"):
            continue
        try:
            cells.append(CampaignCell.model_validate_json(path.read_text()))
        except Exception:
            continue
    return cells


# ── frozen-threshold evaluation (definitions are part of the contract) ──────


class CampaignThresholds(BaseModel):
    """The acceptance criteria. FROZEN before execution, never revised
    after results are seen — the identity hash makes a silent edit
    visible."""

    model_config = ConfigDict(frozen=True)

    median_absolute_percentage_error_max: float = 30.0
    p90_underprediction_ratio_max: float = 1.5
    large_model_underprediction_ratio_max: float = 2.0
    large_model_parameter_threshold: int = 5_000_000
    vram_underprediction_fraction_max: float = 0.20
    vram_underprediction_absolute_gb_max: float = 1.0
    forbid_monotonic_size_underprediction: bool = True
    forbid_family_wide_underprediction: bool = True
    #: "Systematically underestimated" must mean MATERIALLY, not by any
    #: epsilon: a uniform 5% underprediction sits well inside the median
    #: threshold and is not a family defect. A family trips the rule only
    #: when every one of its sizes is underestimated by at least this
    #: ratio.
    family_underprediction_materiality_ratio: float = 1.10

    @property
    def identity(self) -> str:
        from core.runtime_control.identity import component_identity

        return component_identity("campaign_thresholds", "1.0.0", self.model_dump(mode="json"))


CampaignVerdict = Literal[
    "C12 PASS",
    "C12 FAIL — RUNTIME ACCURACY",
    "C12 FAIL — VRAM ACCURACY",
    "C12 FAIL — SIZE BIAS",
    "C12 FAIL — FAMILY BIAS",
    "C12 FAIL — CONCURRENCY MODEL",
    "C12 FAIL — PRODUCTION WIRING",
    "STOPPED — RESOURCE / ENVIRONMENT",
]


class CampaignReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: CampaignVerdict
    thresholds_identity: str
    reasons: tuple[str, ...] = ()
    metrics: dict[str, Any] = Field(default_factory=dict)
    cells_evaluated: int = 0
    cells_excluded: int = 0


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile — deterministic, no interpolation, so the
    same inputs always yield the same reported number."""
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    import math

    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def evaluate_campaign(cells: list[CampaignCell], thresholds: CampaignThresholds) -> CampaignReport:
    """Apply the frozen thresholds. Deterministic and order-independent."""
    scored = [c for c in cells if c.contributes_to_verdict]
    excluded = len(cells) - len(scored)
    if not scored:
        return CampaignReport(
            verdict="STOPPED — RESOURCE / ENVIRONMENT",
            thresholds_identity=thresholds.identity,
            reasons=("no cell produced a comparable measurement",),
            cells_excluded=excluded,
        )

    errors = [c.absolute_percentage_error for c in scored if c.absolute_percentage_error]
    under = [c.underprediction_ratio or 1.0 for c in scored]
    median_error = _percentile(errors, 0.5) if errors else 0.0
    p90_under = _percentile(under, 0.9)

    reasons: list[str] = []
    metrics: dict[str, Any] = {
        "median_absolute_percentage_error": round(median_error, 2),
        "p90_underprediction_ratio": round(p90_under, 3),
        "max_underprediction_ratio": round(max(under), 3),
        "max_overprediction_ratio": round(max(c.runtime_error_ratio or 1.0 for c in scored), 3),
        "cells_scored": len(scored),
    }

    # Every failing rule records its reason; the VERDICT is then chosen by
    # a fixed precedence, so the reported category never depends on the
    # order the rules happen to run in.
    failures: set[CampaignVerdict] = set()
    if median_error > thresholds.median_absolute_percentage_error_max:
        reasons.append(
            f"median absolute percentage error {median_error:.1f}% exceeds "
            f"{thresholds.median_absolute_percentage_error_max}%"
        )
        failures.add("C12 FAIL — RUNTIME ACCURACY")
    if p90_under > thresholds.p90_underprediction_ratio_max:
        reasons.append(
            f"90th-percentile underprediction {p90_under:.2f}x exceeds "
            f"{thresholds.p90_underprediction_ratio_max}x"
        )
        failures.add("C12 FAIL — RUNTIME ACCURACY")

    # Large models must not be badly underestimated.
    for cell in scored:
        params = cell.probe.realized_parameter_count if cell.probe else None
        ratio = cell.underprediction_ratio or 1.0
        if (
            params
            and params >= thresholds.large_model_parameter_threshold
            and ratio > thresholds.large_model_underprediction_ratio_max
        ):
            reasons.append(f"{cell.cell_id}: {params:,} parameters underestimated by {ratio:.2f}x")
            verdict = "C12 FAIL — SIZE BIAS"

    # Monotonic size-dependent underprediction, per family.
    if thresholds.forbid_monotonic_size_underprediction:
        for family in sorted({c.family for c in scored}):
            ordered = sorted(
                (c for c in scored if c.family == family),
                key=lambda c: (c.probe.realized_parameter_count if c.probe else 0) or 0,
            )
            ratios = [c.underprediction_ratio or 1.0 for c in ordered]
            if (
                len(ratios) >= 3
                and all(b > a for a, b in itertools.pairwise(ratios))
                and ratios[-1] > 1.0
            ):
                reasons.append(
                    f"{family}: underprediction grows monotonically with size "
                    f"({' -> '.join(f'{r:.2f}x' for r in ratios)})"
                )
                failures.add("C12 FAIL — SIZE BIAS")

    # A family underestimated at EVERY tested size.
    if thresholds.forbid_family_wide_underprediction:
        for family in sorted({c.family for c in scored}):
            family_cells = [c for c in scored if c.family == family]
            if len(family_cells) >= 3 and all(
                (c.underprediction_ratio or 1.0)
                >= thresholds.family_underprediction_materiality_ratio
                for c in family_cells
            ):
                reasons.append(
                    f"{family}: underestimated by at least "
                    f"{thresholds.family_underprediction_materiality_ratio:.2f}x at every "
                    "tested size"
                )
                failures.add("C12 FAIL — FAMILY BIAS")

    # VRAM.
    for cell in scored:
        gap = cell.vram_underprediction_gb
        if gap is None or not cell.actual_peak_vram_gb:
            continue
        allowed = max(
            thresholds.vram_underprediction_absolute_gb_max,
            thresholds.vram_underprediction_fraction_max * cell.actual_peak_vram_gb,
        )
        if gap > allowed:
            reasons.append(
                f"{cell.cell_id}: VRAM underpredicted by {gap:.2f} GB (allowed {allowed:.2f})"
            )
            failures.add("C12 FAIL — VRAM ACCURACY")

    # Precedence: the most specific, most actionable diagnosis wins.
    for candidate in (
        "C12 FAIL — PRODUCTION WIRING",
        "C12 FAIL — CONCURRENCY MODEL",
        "C12 FAIL — VRAM ACCURACY",
        "C12 FAIL — SIZE BIAS",
        "C12 FAIL — FAMILY BIAS",
        "C12 FAIL — RUNTIME ACCURACY",
    ):
        if candidate in failures:
            verdict = candidate
            break
    else:
        verdict = "C12 PASS"

    return CampaignReport(
        verdict=verdict,
        thresholds_identity=thresholds.identity,
        reasons=tuple(reasons),
        metrics=metrics,
        cells_evaluated=len(scored),
        cells_excluded=excluded,
    )
