"""Legacy k-table migration — finalized as REFERENCE-ONLY (C11).

The per-GPU `time_calibration_*.json` files predate every provenance
rule this subsystem enforces. They contain useful history, and they
contain it in a form that cannot say how it was measured, under what
contention, or against which realized parameter count.

So "migration" here deliberately does NOT mean converting them into
observations. `CalibrationObservation` rejects non-measurement
provenance by schema, and that is correct: importing a legacy row as a
measured observation would launder an unlabeled number into the tier
that may block a formal decision.

What migration does instead:

* verify the file and record it by CONTENT HASH as a
  `LegacySourceReference` in the registry — the registry then knows the
  history exists and exactly which bytes it read;
* leave the original file untouched;
* expose its entries as `legacy_calibration_prior` estimates (tier 1)
  through the existing read-only adapter, for anyone who wants a prior.

The legacy file is never written, moved or rewritten.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.runtime_control.calibration_registry import (
    CalibrationRegistry,
    adapt_legacy_k_table,
)


def discover_legacy_tables(search_root: Path | None = None) -> list[Path]:
    """Legacy k-tables next to the registry (the historical location)."""
    root = search_root or (Path.home() / ".siderius")
    if not root.is_dir():
        return []
    return sorted(root.glob("time_calibration_*.json"))


def migrate_legacy_table(
    path: Path, *, registry: CalibrationRegistry | None = None, dry_run: bool = False
) -> dict[str, Any]:
    """Register one legacy table as a hash-identified source.

    Returns a summary. With ``dry_run`` nothing is written anywhere.
    """
    before = path.read_bytes()
    reference, entries = adapt_legacy_k_table(path)
    summary: dict[str, Any] = {
        "path": str(path),
        "gpu_slug": reference.gpu_slug,
        "file_sha256": reference.file_sha256,
        "entry_count": reference.entry_count,
        "adapter_version": reference.adapter_version,
        "imported_as_observations": 0,
        "provenance_of_entries": "legacy_calibration_prior",
        "dry_run": dry_run,
    }
    if not dry_run:
        (registry or CalibrationRegistry()).reference_legacy_source(reference)
        summary["registered"] = True
    else:
        summary["registered"] = False
    # The source file is evidence: prove we did not touch it.
    summary["source_unmodified"] = path.read_bytes() == before
    summary["sample_entry_keys"] = sorted(entries[0].keys()) if entries else []
    return summary


def legacy_entries_as_priors(path: Path) -> list[dict[str, Any]]:
    """The table's rows as TIER-1 prior estimates, never measurements."""
    from core.runtime_control.estimate_types import from_legacy_calibration_entry

    _, entries = adapt_legacy_k_table(path)
    priors = []
    for entry in entries:
        estimate = from_legacy_calibration_entry(entry)
        priors.append(
            {
                "provenance": estimate.provenance,
                "blocking_eligible": estimate.blocking_eligible,
                "expected_seconds": estimate.expected_seconds,
            }
        )
    return priors
