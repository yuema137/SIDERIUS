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
    # Operator-approved replacement (2026-07-31) for the cell above, which
    # OOM'd on this device at the unchanged workload. Same family, same
    # workload shape, comparable large scale. It is NOT a 20M model and is
    # never relabelled as one; the original OOM stays in the report as
    # device-capacity evidence.
    {
        "family": "wavenet",
        "cell_label": "~9M",
        "target": 9_246_208,
        "realized": 9_246_208,
        "replacement_for": "wavenet@20M",
        "replacement_reason": "measured_device_capacity_boundary",
        "config": {
            "segmentation_size": 40000,
            "residual_channels": 128,
            "gate_channels": 256,
            "skip_channels": 128,
            "num_blocks": 20,
        },
    },
    # Final same-family replacement attempt (operator, 2026-07-31). The 20M
    # and ~9M cells both OOM'd on this device; if this one also fails,
    # wavenet@5M stands as the measured feasible family ceiling here and no
    # further sizes are searched.
    {
        "family": "wavenet",
        "cell_label": "~6M",
        "target": 6_009_408,
        "realized": 6_009_408,
        "replacement_for": "wavenet@20M",
        "replacement_reason": "measured_device_capacity_boundary",
        "config": {
            "segmentation_size": 40000,
            "residual_channels": 128,
            "gate_channels": 192,
            "skip_channels": 64,
            "num_blocks": 18,
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
        # Operator decision (2026-07-31): this is NOT a 20M cell and must
        # never be analyzed as one. Its REALIZED count is used everywhere.
        "cell_label": "8M-ceiling",
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
    {"label": "small_cross_family", "members": ("punet@50K", "wavenet@50K")},
    # wavenet@20M, ~9M and ~6M all OOM on this device (all measured), so
    # wavenet@5M is the largest FEASIBLE member of that family here.
    {"label": "largest_feasible_cross_family", "members": ("punet@20M", "wavenet@5M")},
    {"label": "heterogeneous_compute", "members": ("punet@5M", "transformer@5M")},
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
    replacement_for: str | None = Field(
        default=None,
        description="The cell this one replaces, when the original could not "
        "complete on this device. Never a relabelling: the original keeps its "
        "own record and its own realized scale.",
    )
    replacement_reason: str | None = None
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


def matrix_cell_id(entry: dict[str, Any]) -> str:
    """Stable id for a matrix entry. A cell that cannot reach its target
    carries an explicit label (e.g. `transformer@8M-ceiling`) so it is
    never analyzed as though it were the target size."""
    label = entry.get("cell_label")
    if not label:
        target = entry["target"]
        label = f"{target // 1_000_000}M" if target >= 1_000_000 else f"{target // 1_000}K"
    return f"{entry['family']}@{label}"


def required_cell_ids() -> tuple[str, ...]:
    """Every cell the campaign MUST cover to be eligible to pass.

    A REPLACEMENT cell is not independently required — it exists to cover
    its original, and a replacement that itself fails must not open a new
    hole of its own.
    """
    return tuple(matrix_cell_id(entry) for entry in MATRIX if not entry.get("replacement_for"))


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

    frozen_by: str = "operator 2026-07-31"
    median_absolute_percentage_error_max: float = 30.0
    p90_underprediction_ratio_max: float = 1.5
    large_model_underprediction_ratio_max: float = 2.0
    large_model_parameter_threshold: int = 5_000_000
    vram_underprediction_fraction_max: float = 0.20
    vram_underprediction_absolute_gb_max: float = 1.0
    #: Size bias: within a family with >= this many completed sizes, the
    #: largest-size underprediction ratio must not exceed the smallest by
    #: more than `size_bias_ratio_spread_max` WHILE a majority of adjacent
    #: sizes also trend upward. Both conditions are required: a spread
    #: alone can be noise, a trend alone can be immaterial.
    size_bias_min_completed_sizes: int = 3
    size_bias_ratio_spread_max: float = 0.25
    #: Family bias: within a family with >= this many completed cells, at
    #: least `family_bias_min_underestimated` are underestimated AND the
    #: family's MEDIAN underprediction ratio exceeds
    #: `family_bias_median_ratio_max`.
    family_bias_min_completed_cells: int = 3
    family_bias_min_underestimated: int = 3
    family_bias_median_ratio_max: float = 1.10

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


def evaluate_campaign(
    cells: list[CampaignCell],
    thresholds: CampaignThresholds,
    *,
    approved_replacements: frozenset[str] = frozenset(),
) -> CampaignReport:
    """Apply the frozen thresholds. Deterministic and order-independent.

    ``approved_replacements`` names required cells the operator has
    explicitly excused (same family, comparable scale). Nothing is excused
    by default: a missing cell blocks PASS until it is diagnosed.
    """
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
        "required_cells": len(required_cell_ids()),
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
            failures.add("C12 FAIL — SIZE BIAS")

    # FROZEN size-bias rule (operator 2026-07-31): a family trips it only
    # when the spread between its largest and smallest size is material
    # AND a majority of adjacent steps trend upward. Either alone is
    # insufficient — a spread can be noise, a trend can be immaterial.
    for family in sorted({c.family for c in scored}):
        ordered = sorted(
            (c for c in scored if c.family == family),
            key=lambda c: (c.probe.realized_parameter_count if c.probe else 0) or 0,
        )
        if len(ordered) < thresholds.size_bias_min_completed_sizes:
            continue
        ratios = [c.underprediction_ratio or 1.0 for c in ordered]
        spread = ratios[-1] - ratios[0]
        upward = sum(1 for a, b in itertools.pairwise(ratios) if b > a)
        adjacent = len(ratios) - 1
        if spread > thresholds.size_bias_ratio_spread_max and upward * 2 > adjacent:
            reasons.append(
                f"{family}: underprediction grows with size — largest-size ratio "
                f"exceeds smallest by {spread:.2f} (limit "
                f"{thresholds.size_bias_ratio_spread_max}), with {upward}/{adjacent} "
                f"adjacent sizes trending upward ({' -> '.join(f'{r:.2f}x' for r in ratios)})"
            )
            failures.add("C12 FAIL — SIZE BIAS")

    # FROZEN family-bias rule (operator 2026-07-31): enough completed
    # cells, at least N of them underestimated, and the family's MEDIAN
    # underprediction materially above 1.0.
    for family in sorted({c.family for c in scored}):
        family_cells = [c for c in scored if c.family == family]
        if len(family_cells) < thresholds.family_bias_min_completed_cells:
            continue
        ratios = [c.underprediction_ratio or 1.0 for c in family_cells]
        underestimated = sum(1 for r in ratios if r > 1.0)
        median_ratio = _percentile(ratios, 0.5)
        if (
            underestimated >= thresholds.family_bias_min_underestimated
            and median_ratio > thresholds.family_bias_median_ratio_max
        ):
            reasons.append(
                f"{family}: {underestimated}/{len(ratios)} cells underestimated with a "
                f"median ratio of {median_ratio:.2f}x (limit "
                f"{thresholds.family_bias_median_ratio_max})"
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

    # REQUIRED-CELL COVERAGE (operator 2026-07-31). A measured failure is
    # preserved as evidence but still leaves a hole in the matrix: C12
    # cannot PASS while a required cell has no completed measurement.
    completed = {c.cell_id for c in scored}
    # A cell whose operator-approved REPLACEMENT completed is covered: the
    # original stays in the report as evidence, the replacement supplies
    # the accuracy datum.
    satisfied_by_replacement = {
        str(entry["replacement_for"])
        for entry in MATRIX
        if entry.get("replacement_for") and matrix_cell_id(entry) in completed
    }
    missing = [
        cell_id
        for cell_id in required_cell_ids()
        if cell_id not in completed
        and cell_id not in approved_replacements
        and cell_id not in satisfied_by_replacement
    ]
    if missing:
        detail = {c.cell_id: (c.status, c.failure_detail) for c in cells if c.cell_id in missing}
        reasons.append(
            f"required cells without a completed measurement: {missing}. "
            f"Diagnosis needed before a verdict: {detail}"
        )

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
        # Coverage cannot be traded away by everything else looking fine.
        verdict = "STOPPED — RESOURCE / ENVIRONMENT" if missing else "C12 PASS"

    return CampaignReport(
        verdict=verdict,
        thresholds_identity=thresholds.identity,
        reasons=tuple(reasons),
        metrics=metrics,
        cells_evaluated=len(scored),
        cells_excluded=excluded,
    )


# ── C12-C: pairwise concurrency ─────────────────────────────────────────────


class PairwisePlan(BaseModel):
    """One concurrency cell: the same two models alone, then together."""

    model_config = ConfigDict(frozen=True)

    label: str
    members: tuple[str, ...]
    member_parameter_counts: tuple[int, ...] = ()
    execution_order: tuple[str, ...] = ()
    stagger_seconds: float = 0.0

    @property
    def stages(self) -> tuple[str, ...]:
        """Alone first, then together — an idle baseline must exist before
        a contention multiplier can mean anything."""
        return (
            f"{self.members[0]}_alone",
            f"{self.members[1]}_alone",
            f"{self.label}_pairwise",
        )


class PairwiseResult(BaseModel):
    """Measured concurrency evidence for one pair."""

    model_config = ConfigDict(frozen=True)

    label: str
    member: str
    alone_ms_per_step: float = Field(gt=0.0)
    paired_ms_per_step: float = Field(gt=0.0)
    alone_concurrency_identity: str
    paired_concurrency_identity: str
    peer_pid_registered: bool
    aggregate_peak_vram_gb: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _regimes_must_differ(self) -> PairwiseResult:
        if self.alone_concurrency_identity != "single_candidate_idle":
            raise ValueError(
                "the ALONE measurement must be single_candidate_idle; a contended "
                "baseline cannot define a contention multiplier"
            )
        if self.paired_concurrency_identity != "pairwise_expected_peer":
            raise ValueError(
                f"the PAIRED measurement is {self.paired_concurrency_identity!r}, not "
                "pairwise_expected_peer — an idle observation must never be recorded "
                "as a concurrent one, and a foreign process must never be accepted as "
                "the expected peer"
            )
        if not self.peer_pid_registered:
            raise ValueError(
                "the peer must be identified by REGISTERED PID; a peer is never "
                "inferred from a process name"
            )
        return self

    @property
    def contention_multiplier(self) -> float:
        """How much slower this member runs beside its peer."""
        return self.paired_ms_per_step / self.alone_ms_per_step


def build_pairwise_plans(
    realized_by_cell: dict[str, int] | None = None, *, stagger_seconds: float = 0.0
) -> list[PairwisePlan]:
    counts = realized_by_cell or {}
    plans = []
    for pair in PAIRWISE_PAIRS:
        members = tuple(pair["members"])
        plans.append(
            PairwisePlan(
                label=str(pair["label"]),
                members=members,
                member_parameter_counts=tuple(counts.get(m, 0) for m in members),
                execution_order=members,
                stagger_seconds=stagger_seconds,
            )
        )
    return plans
