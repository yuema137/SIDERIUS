"""Pure fixed-slot layout shared by preparation and worker reconciliation."""

from pathlib import Path


def candidate_proposal_dir(workspace: Path, run_name: str) -> Path:
    """Return the native first proposal slot without creating any directory."""
    return workspace / run_name / "iteration_001" / "attempt_001"
