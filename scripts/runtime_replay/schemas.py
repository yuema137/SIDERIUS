"""Typed replay reports with SCHEMA-ENFORCED evidence labels (C11).

The replay tools exist because §15.6 could not answer one question: were
the wave-1 static rejections directionally right? The honest answer is
still "unverified", and the whole point of these schemas is to make it
impossible for a report to accidentally claim otherwise.

Two modes, and the type system keeps them apart:

* ``metadata`` — reads the forensic snapshot and reports what it SAYS.
  Every number is a static, LLM-authored or formula-derived ESTIMATE. A
  metadata report cannot carry a measurement: the validator rejects it.
* ``executable`` — additionally probes candidates that have a real,
  loadable implementation, and reports measured runtime beside the old
  estimate. Only here may a report carry empirical numbers.

A candidate with no implementation can never leave metadata territory,
in either mode. That is the case for the wave-1 drafts the static
formula rejected: they were never implemented, so nothing about their
true cost is knowable from this snapshot, and the report says exactly
that rather than implying the rejection was vindicated or refuted.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReplayMode = Literal["metadata", "executable"]

#: What KIND of number a field holds. Never inferred from context.
EvidenceLabel = Literal[
    "static_estimate",  # the uncalibrated formula / LLM-authored count
    "empirical_measurement",  # measured on this machine, now
    "not_available",  # no implementation, or not probed
]

CandidateStage = Literal["surviving_proposal", "rejected_draft"]


class MeasuredRuntime(BaseModel):
    """Empirical numbers. Present ONLY in executable mode."""

    model_config = ConfigDict(frozen=True)

    label: Literal["empirical_measurement"] = "empirical_measurement"
    train_ms_per_step: float | None = Field(default=None, gt=0.0)
    inference_ms_per_batch: float | None = Field(default=None, gt=0.0)
    setup_seconds: float | None = Field(default=None, ge=0.0)
    peak_vram_gb: float | None = Field(default=None, gt=0.0)
    realized_parameter_count: int | None = Field(default=None, gt=0)
    concurrency_identity: str | None = None
    probe_status: str | None = None
    observation_ids: tuple[str, ...] = ()


class ReplayCandidate(BaseModel):
    """One proposal or draft from the snapshot, with labeled evidence."""

    model_config = ConfigDict(frozen=True)

    model_name: str | None
    stage: CandidateStage
    source: str = Field(description="Path within the snapshot this came from.")

    # --- everything below is a STATIC estimate from the stopped run ---
    static_label: Literal["static_estimate"] = "static_estimate"
    parameter_count_estimate: int | None = Field(
        default=None,
        description="LLM-AUTHORED at proposal time. Not a realized count: "
        "§16.7 measured a 7.4x divergence on this very wave.",
    )
    static_estimated_minutes: float | None = None
    static_factor: float | None = Field(
        default=None, description="static_estimated_minutes / budget, as recorded then."
    )
    static_verdict: str | None = None

    # --- implementation reachability ---
    implementation_available: bool = False
    implementation_detail: str = ""

    # --- executable mode only ---
    measured: MeasuredRuntime | None = None

    @model_validator(mode="after")
    def _no_measurement_without_implementation(self) -> ReplayCandidate:
        if self.measured is not None and not self.implementation_available:
            raise ValueError(
                f"candidate {self.model_name!r} carries a measurement but has no "
                "loadable implementation — a runtime number cannot exist for code "
                "that does not exist"
            )
        if self.stage == "rejected_draft" and self.measured is not None:
            raise ValueError(
                f"draft {self.model_name!r} was rejected before implementation; it "
                "can never carry measured runtime"
            )
        return self

    @property
    def runtime_truth_known(self) -> bool:
        """Whether anything empirical is known about this candidate."""
        return self.measured is not None


class ReplayReport(BaseModel):
    """The complete replay result. Mode separation is schema-enforced."""

    model_config = ConfigDict(frozen=True)

    mode: ReplayMode
    snapshot_root: str
    snapshot_integrity: Literal["verified", "unverified", "mismatch"] = "unverified"
    integrity_detail: str = ""
    candidates: tuple[ReplayCandidate, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _metadata_mode_makes_no_runtime_claims(self) -> ReplayReport:
        if self.mode == "metadata":
            measured = [c.model_name for c in self.candidates if c.measured is not None]
            if measured:
                raise ValueError(
                    "a METADATA replay cannot carry measured runtime "
                    f"(offenders: {measured}). Metadata mode reports what the "
                    "snapshot says; it establishes no ground truth."
                )
        return self

    @property
    def metadata_only(self) -> tuple[ReplayCandidate, ...]:
        return tuple(c for c in self.candidates if not c.runtime_truth_known)

    def render(self) -> str:
        lines = ["", "=" * 76]
        lines.append(f"  Runtime replay — {self.mode.upper()} mode")
        lines.append(f"  snapshot : {self.snapshot_root}")
        lines.append(f"  integrity: {self.snapshot_integrity} ({self.integrity_detail})")
        lines.append("=" * 76)
        for candidate in self.candidates:
            lines.append(f"  {candidate.model_name or '<unnamed draft>'}  [{candidate.stage}]")
            lines.append(
                f"      static estimate : "
                f"{_fmt(candidate.static_estimated_minutes)} min, "
                f"factor {_fmt(candidate.static_factor)}x, "
                f"params(LLM) {_fmt_int(candidate.parameter_count_estimate)}"
            )
            lines.append(
                "      implementation  : "
                + ("available" if candidate.implementation_available else "NONE")
                + (
                    f" ({candidate.implementation_detail})"
                    if candidate.implementation_detail
                    else ""
                )
            )
            if candidate.measured is not None:
                measured = candidate.measured
                lines.append(
                    f"      MEASURED        : train {_fmt(measured.train_ms_per_step)} ms/step, "
                    f"inference {_fmt(measured.inference_ms_per_batch)} ms/batch, "
                    f"realized params {_fmt_int(measured.realized_parameter_count)}"
                )
            else:
                lines.append(
                    "      MEASURED        : none — no runtime ground truth for this candidate"
                )
        lines.append("")
        lines.append("  NOTE: static numbers above are UNCALIBRATED estimates recorded by the")
        lines.append("  stopped run. Where no measurement is shown, this report establishes")
        lines.append("  neither that the original verdict was right nor that it was wrong.")
        for note in self.notes:
            lines.append(f"  - {note}")
        lines.append("=" * 76)
        return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "n/a"


def _fmt_int(value: int | None) -> str:
    return f"{value:,}" if isinstance(value, int) else "n/a"
