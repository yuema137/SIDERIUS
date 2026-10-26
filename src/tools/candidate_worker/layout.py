"""Pure fixed-slot layout shared by preparation and worker reconciliation."""

from pathlib import Path


def candidate_proposal_dir(workspace: Path, run_name: str) -> Path:
    """Return the native first proposal slot without creating any directory."""
    return workspace / run_name / "iteration_001" / "attempt_001"


def graph_instance_dir(workspace: Path, run_name: str, node_id: str) -> Path:
    """A declared instance owns its native first-attempt namespace."""
    return workspace / run_name / "graph_instances" / node_id / "iteration_001" / "attempt_001"


def proposal_input_path(workspace: Path, profile: str | None, node_id: str) -> Path:
    """Isolate family diagnostics while retaining fixed and G1 bytes/paths."""
    control = workspace / "candidate_run"
    if profile in ("native-proposal-families/v1", "native-literature-candidate/v1"):
        return control / "proposal_inputs" / f"{node_id}.json"
    return control / "proposal_input.json"


def proposal_debug_dir(workspace: Path, profile: str | None, node_id: str) -> Path:
    directory = workspace / "candidate_run" / "debug"
    return (
        directory / node_id
        if profile in ("native-proposal-families/v1", "native-literature-candidate/v1")
        else directory
    )


def literature_input_path(workspace: Path, node_id: str) -> Path:
    """Managed native review diagnostics, separate from proposal inputs."""
    return workspace / "candidate_run" / "literature_inputs" / f"{node_id}.json"


def literature_cache_dir(workspace: Path, run_name: str, node_id: str) -> Path:
    return graph_instance_dir(workspace, run_name, node_id) / "cache" / "root_papers"
