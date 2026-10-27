"""Pure iteration-slot layout shared by preparation and worker reconciliation.

Explicit iterations come from the validated invocation identity. Preparation
and operation evidence readers retain the default first iteration.
"""

from pathlib import Path


def candidate_proposal_dir(workspace: Path, run_name: str, *, iteration: int = 1) -> Path:
    """Return the native proposal slot without creating any directory."""
    return workspace / run_name / f"iteration_{iteration:03d}" / "attempt_001"


def graph_instance_dir(workspace: Path, run_name: str, node_id: str, *, iteration: int = 1) -> Path:
    """A declared instance owns its native first-attempt namespace."""
    return candidate_proposal_dir(
        workspace / run_name / "graph_instances", node_id, iteration=iteration
    )


def _control_dir(workspace: Path, iteration: int) -> Path:
    # Existing captures bind the original unnumbered iteration-one diagnostics.
    control = workspace / "candidate_run"
    return control if iteration == 1 else control / f"iteration_{iteration:03d}"


def proposal_input_path(
    workspace: Path, profile: str | None, node_id: str, *, iteration: int = 1
) -> Path:
    """Isolate family diagnostics while retaining fixed and G1 bytes/paths."""
    control = _control_dir(workspace, iteration)
    if profile in ("native-proposal-families/v1", "native-literature-candidate/v1"):
        return control / "proposal_inputs" / f"{node_id}.json"
    return control / "proposal_input.json"


def proposal_debug_dir(
    workspace: Path, profile: str | None, node_id: str, *, iteration: int = 1
) -> Path:
    directory = _control_dir(workspace, iteration) / "debug"
    return (
        directory / node_id
        if profile in ("native-proposal-families/v1", "native-literature-candidate/v1")
        else directory
    )


def literature_input_path(workspace: Path, node_id: str, *, iteration: int = 1) -> Path:
    """Managed native review diagnostics, separate from proposal inputs."""
    return _control_dir(workspace, iteration) / "literature_inputs" / f"{node_id}.json"


def literature_cache_dir(
    workspace: Path, run_name: str, node_id: str, *, iteration: int = 1
) -> Path:
    return (
        graph_instance_dir(workspace, run_name, node_id, iteration=iteration)
        / "cache"
        / "root_papers"
    )
