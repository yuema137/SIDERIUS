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


def candidate_control_dir(workspace: Path, *, iteration: int = 1) -> Path:
    # Existing captures bind the original unnumbered iteration-one diagnostics.
    control = workspace / "candidate_run"
    return control if iteration == 1 else control / f"iteration_{iteration:03d}"


# Profiles whose proposal diagnostics are per node; every other profile keeps the
# fixed and G1 singular paths.
_PER_NODE_PROPOSAL_PROFILES = (
    "native-proposal-families/v1",
    "native-literature-candidate/v1",
    "native-interpretation-candidate/v1",
    "native-literature-collection/v1",
    "native-literature-split/v1",
    "native-literature-judged/v1",
)


def proposal_input_path(
    workspace: Path, profile: str | None, node_id: str, *, iteration: int = 1
) -> Path:
    """Isolate family diagnostics while retaining fixed and G1 bytes/paths."""
    control = candidate_control_dir(workspace, iteration=iteration)
    if profile in _PER_NODE_PROPOSAL_PROFILES:
        return control / "proposal_inputs" / f"{node_id}.json"
    return control / "proposal_input.json"


def proposal_debug_dir(
    workspace: Path, profile: str | None, node_id: str, *, iteration: int = 1
) -> Path:
    directory = candidate_control_dir(workspace, iteration=iteration) / "debug"
    return directory / node_id if profile in _PER_NODE_PROPOSAL_PROFILES else directory


def literature_input_path(workspace: Path, node_id: str, *, iteration: int = 1) -> Path:
    """Managed native review diagnostics, separate from proposal inputs."""
    return (
        candidate_control_dir(workspace, iteration=iteration)
        / "literature_inputs"
        / f"{node_id}.json"
    )


def literature_cache_dir(
    workspace: Path, run_name: str, node_id: str, *, iteration: int = 1
) -> Path:
    return (
        graph_instance_dir(workspace, run_name, node_id, iteration=iteration)
        / "cache"
        / "root_papers"
    )


def interpretation_input_path(workspace: Path, node_id: str, *, iteration: int = 1) -> Path:
    return (
        candidate_control_dir(workspace, iteration=iteration)
        / "interpretation_inputs"
        / f"{node_id}.json"
    )


def tuning_input_path(workspace: Path, node_id: str, *, iteration: int = 1) -> Path:
    return (
        candidate_control_dir(workspace, iteration=iteration) / "tuning_inputs" / f"{node_id}.json"
    )


def adaptor_dir(workspace: Path, *, iteration: int = 1) -> Path:
    """The adaptors' own records and published output values (B6-3)."""
    return candidate_control_dir(workspace, iteration=iteration) / "adaptors"


def adaptor_record_path(workspace: Path, adaptor_id: str, *, iteration: int = 1) -> Path:
    return adaptor_dir(workspace, iteration=iteration) / f"{adaptor_id}.json"


def adaptor_output_path(
    workspace: Path, adaptor_id: str, port: str, index: int | None, *, iteration: int = 1
) -> Path:
    suffix = port if index is None else f"{port}.{index}"
    return adaptor_dir(workspace, iteration=iteration) / f"{adaptor_id}.out.{suffix}.json"
