"""Metadata replay of a stopped run's forensic snapshot (C11).

Reads ONLY. Reports what the snapshot recorded — the static pre-flight
numbers, the LLM-authored parameter counts, and whether each candidate
ever became runnable code — without claiming anything about what those
candidates would actually have cost.

Two candidate populations, and the difference matters:

* SURVIVING PROPOSALS are persisted as ``proposal_iter_*.json`` and name
  a model that may still be loadable today.
* REJECTED DRAFTS never reached persistence. The chain log preserves the
  factor the static formula assigned them and nothing else — not the
  architecture, not a parameter count, not an implementation. Their true
  cost is unknowable from this snapshot, and the report says so instead
  of reconstructing a number that would look like evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.runtime_replay.schemas import ReplayCandidate, ReplayReport

#: e.g. "   Pre-flight rejected (factor=84.64x); requesting revision 2/3."
_REJECTION = re.compile(r"Pre-flight rejected \(factor=([0-9.]+)x\)")


class SnapshotNotFound(FileNotFoundError):
    """The forensic snapshot is not where the caller said it was."""


def verify_snapshot_integrity(root: Path) -> tuple[str, str]:
    """Check the snapshot against its own SHA256SUMS manifest.

    Read-only. Returns ``(status, detail)`` where status is
    ``verified`` / ``unverified`` / ``mismatch``.
    """
    manifests = list(root.rglob("SHA256SUMS"))
    if not manifests:
        return "unverified", "no SHA256SUMS manifest in the snapshot"
    checked = 0
    mismatched: list[str] = []
    missing: list[str] = []
    for manifest in manifests:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            expected, _, path_text = line.partition("  ")
            path = Path(path_text.strip())
            if not path.is_file():
                missing.append(str(path))
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            checked += 1
            if actual != expected:
                mismatched.append(str(path))
    if mismatched:
        return "mismatch", f"{len(mismatched)} file(s) differ from the manifest"
    if missing:
        return "mismatch", f"{len(missing)} manifest file(s) are absent"
    return "verified", f"{checked} files hash-match the manifest"


def _implementation_status(model_name: str | None) -> tuple[bool, str]:
    """Is there loadable code for this candidate TODAY?

    Consults the live plugin registry — the same seam production loads
    from — rather than guessing from a file name.
    """
    if not model_name:
        return False, "no model name recorded"
    try:
        from ml_models.models_sandbox import MODEL_REGISTRY

        if model_name in MODEL_REGISTRY:
            return True, "registered in the live MODEL_REGISTRY"
        return False, "not present in the live MODEL_REGISTRY"
    except Exception as exc:  # pragma: no cover - import-shape guard
        return False, f"registry unavailable: {exc!r}"


def collect_surviving_proposals(root: Path) -> list[ReplayCandidate]:
    """Every persisted proposal in the snapshot, with its static numbers."""
    candidates: list[ReplayCandidate] = []
    for path in sorted(root.rglob("proposal_iter_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        model_name = payload.get("model_name")
        available, detail = _implementation_status(model_name)
        candidates.append(
            ReplayCandidate(
                model_name=model_name,
                stage="surviving_proposal",
                source=str(path.relative_to(root)),
                parameter_count_estimate=payload.get("parameter_count_estimate"),
                static_estimated_minutes=payload.get("preflight_estimated_minutes"),
                static_factor=payload.get("preflight_factor"),
                implementation_available=available,
                implementation_detail=detail,
            )
        )
    return candidates


def collect_rejected_drafts(root: Path) -> list[ReplayCandidate]:
    """Drafts the static pre-flight rejected before they were persisted.

    Only the factor survives. No architecture, no parameter count, no
    implementation — so nothing here can ever be measured, and the
    candidate is reported with `implementation_available=False` and every
    static field it genuinely lacks left as None rather than reconstructed.
    """
    candidates: list[ReplayCandidate] = []
    for log_path in sorted(root.rglob("chain.log")):
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _REJECTION.finditer(text):
            candidates.append(
                ReplayCandidate(
                    model_name=None,  # never named: rejected before commit
                    stage="rejected_draft",
                    source=str(log_path.relative_to(root)),
                    static_factor=float(match.group(1)),
                    static_verdict=f"rejected by the uncalibrated pre-flight at "
                    f"{match.group(1)}x budget",
                    implementation_available=False,
                    implementation_detail=(
                        "never implemented — rejected at proposal time, so no code, "
                        "no parameter count and no runtime truth exist for it"
                    ),
                )
            )
    return candidates


def run_metadata_replay(snapshot_root: str | Path) -> ReplayReport:
    """Replay a forensic snapshot in METADATA mode. Reads only."""
    root = Path(snapshot_root)
    if not root.is_dir():
        raise SnapshotNotFound(
            f"forensic snapshot not found at {root}. It is read-only evidence; if it "
            "was moved, pass the new location explicitly rather than regenerating it."
        )
    status, detail = verify_snapshot_integrity(root)
    surviving = collect_surviving_proposals(root)
    rejected = collect_rejected_drafts(root)
    notes = [
        f"{len(surviving)} surviving proposal(s) and {len(rejected)} rejected draft(s) found.",
        "Rejected drafts carry a factor and nothing else: they were never "
        "implemented, so this replay can neither confirm nor refute the "
        "verdicts that removed them.",
        "Parameter counts shown for surviving proposals are LLM-AUTHORED "
        "estimates; §16.7 measured a 7.4x divergence from realized counts on "
        "this same wave.",
    ]
    return ReplayReport(
        mode="metadata",
        snapshot_root=str(root),
        snapshot_integrity=status,  # type: ignore[arg-type]
        integrity_detail=detail,
        candidates=tuple(surviving + rejected),
        notes=tuple(notes),
    )
