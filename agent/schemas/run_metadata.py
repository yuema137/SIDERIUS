"""
Run-level metadata schemas.

Captures runtime context for any agent invocation: git state, host environment,
inputs (human + expert advice), and timing. Designed as a hierarchy so higher
levels (workflow, chain) can reference lower-level metadata files by path.

Levels (only the tuner level is implemented today):

| Level    | Scope                                 | File                              | Children                              |
|----------|---------------------------------------|-----------------------------------|---------------------------------------|
| tuner    | one ml_hyperparameter_tune_agent run  | {workspace}/tuner_run_metadata.json | none                                  |
| workflow | one run_workflow() call               | {workspace}/workflow_run_metadata.json | list of tuner_run_metadata.json paths |
| chain    | one chain submission (lilab or SDSC)  | {workspace}/chain_run_metadata.json    | list of workflow_run_metadata.json paths |

The hierarchy is encoded by `BaseRunMetadata.child_metadata_paths`. Higher
levels populate it with paths to their children's metadata files; the tuner
level (a leaf) leaves it empty.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from agent.schemas.hyperparam_tuning import ExpertAdvice


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

class GitInfo(BaseModel):
    """Snapshot of the git repository state at run start."""
    commit: Optional[str] = Field(
        default=None, description="Full SHA of HEAD."
    )
    short_commit: Optional[str] = Field(
        default=None, description="Abbreviated SHA (7 chars)."
    )
    branch: Optional[str] = Field(
        default=None, description="Active branch name, or detached-HEAD marker."
    )
    dirty: bool = Field(
        default=False,
        description="True if the working tree had uncommitted changes at run start.",
    )
    remote_url: Optional[str] = Field(
        default=None, description="Origin remote URL, if configured."
    )
    untracked_count: int = Field(
        default=0, description="Number of untracked files at run start."
    )


class EnvInfo(BaseModel):
    """Snapshot of the host environment at run start."""
    hostname: str
    user: str
    cwd: str
    python_version: str = Field(
        description="Output of sys.version (full version string)."
    )
    cuda_visible_devices: Optional[str] = Field(
        default=None,
        description="Value of CUDA_VISIBLE_DEVICES env var, or None if unset.",
    )
    gpu_name: Optional[str] = Field(
        default=None,
        description="Name of the visible GPU (best-effort, may be None).",
    )


class PerAgentAdvice(BaseModel):
    """
    Free-form advice channels for a single agent.

    Two parallel slots:
      - human:  free-form string injected by a human (CLI flag or advice file)
      - expert: structured guidance produced by an upstream agent or carried
                forward from a legacy free-form preamble (in which case the
                preamble lives in expert.freeform_notes)
    """
    human: str = Field(
        default="",
        description="Free-form advice from a human caller.",
    )
    expert: Optional[ExpertAdvice] = Field(
        default=None,
        description=(
            "Structured expert advice. None if no upstream agent contributed "
            "guidance to this agent on this run."
        ),
    )


# ---------------------------------------------------------------------------
# Base metadata (shared across all levels)
# ---------------------------------------------------------------------------

class BaseRunMetadata(BaseModel):
    """
    Common fields recorded for any run, at any level of the hierarchy.

    Subclasses pin `level` to a Literal value and add level-specific fields.
    The `advice` dict's keys are level-specific (one per agent the level
    invokes); subclasses document which keys they use.
    """
    schema_version: int = Field(
        default=1,
        description="Bump when the metadata schema changes incompatibly.",
    )
    level: Literal["tuner", "workflow", "chain"]

    run_name: str = Field(description="Human-readable run identifier.")
    workspace: str = Field(
        description="Absolute path to the directory holding this run's outputs."
    )

    started_at: str = Field(description="ISO-8601 timestamp with timezone (UTC).")
    finished_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp set when the run completes; None while running.",
    )

    git: GitInfo
    env: EnvInfo

    argv: List[str] = Field(
        default_factory=list,
        description="Original sys.argv that launched the run.",
    )

    advice: Dict[str, PerAgentAdvice] = Field(
        default_factory=dict,
        description=(
            "Per-agent advice this run injected. Keyed by agent name. "
            "Subclasses document which keys they use."
        ),
    )

    human_advice_file: Optional[str] = Field(
        default=None,
        description=(
            "Path to the human advice JSON file the advice was loaded from, "
            "or None if all advice was passed via CLI flags."
        ),
    )

    child_metadata_paths: List[str] = Field(
        default_factory=list,
        description=(
            "Paths to lower-level metadata files this run produced. Empty for "
            "the tuner (leaf) level. Workflow level lists tuner metadata files; "
            "chain level lists workflow metadata files."
        ),
    )

    notes: Optional[str] = Field(
        default=None,
        description="Free-form notes the caller may attach.",
    )


# ---------------------------------------------------------------------------
# Tuner-level metadata
# ---------------------------------------------------------------------------

class TunerRunMetadata(BaseRunMetadata):
    """
    Metadata for ONE invocation of ml_hyperparameter_tune_agent.

    The `advice` dict uses a single key: 'tune'.
    """
    level: Literal["tuner"] = "tuner"

    model_type: str = Field(description="Model architecture being tuned.")
    llm_provider: str = Field(
        description="LLM provider used by the tuner's planner sub-call. "
                    "Also the default for the reflector when reflect_provider is None.",
    )
    llm_model_id: str = Field(
        description="LLM model ID used by the tuner's planner sub-call. "
                    "Also the default for the reflector when reflect_model_id is None.",
    )
    reflect_provider: Optional[str] = Field(
        default=None,
        description="Optional separate provider for the tuner's reflector "
                    "sub-call. None means the reflector used llm_provider.",
    )
    reflect_model_id: Optional[str] = Field(
        default=None,
        description="Optional separate model ID for the tuner's reflector "
                    "sub-call. None means the reflector used llm_model_id.",
    )

    max_rounds: int = Field(description="Tuning round budget.")
    max_proposal_attempts: Optional[int] = Field(
        default=None,
        description="Retry budget for proposal validation (None = framework default).",
    )

    file_index: Optional[int] = Field(
        default=None,
        description="Validation file index when not in trial mode; None otherwise.",
    )
    is_trial: bool = Field(
        default=False,
        description="Whether the tuner ran in trial-explore mode.",
    )

    baseline_score: Optional[float] = Field(
        default=None,
        description="Baseline denoising score the tuner is trying to beat.",
    )


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------

def capture_git_info(repo_root: Optional[str] = None) -> GitInfo:
    """Best-effort capture of git state. Returns an empty GitInfo on any error."""
    import subprocess

    def _run(args: List[str]) -> Optional[str]:
        try:
            out = subprocess.run(
                args, cwd=repo_root, capture_output=True, text=True, check=True,
                timeout=5,
            )
            return out.stdout.strip() or None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            return None

    commit = _run(["git", "rev-parse", "HEAD"])
    short = _run(["git", "rev-parse", "--short", "HEAD"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    remote = _run(["git", "config", "--get", "remote.origin.url"])

    # Dirty / untracked counts
    status = _run(["git", "status", "--porcelain"])
    if status is None:
        dirty = False
        untracked_count = 0
    else:
        lines = [ln for ln in status.splitlines() if ln.strip()]
        untracked_count = sum(1 for ln in lines if ln.startswith("??"))
        dirty = any(not ln.startswith("??") for ln in lines)

    return GitInfo(
        commit=commit,
        short_commit=short,
        branch=branch,
        dirty=dirty,
        remote_url=remote,
        untracked_count=untracked_count,
    )


def capture_env_info() -> EnvInfo:
    """Capture host environment context."""
    import getpass
    import os
    import socket
    import sys

    gpu_name: Optional[str] = None
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        pass

    return EnvInfo(
        hostname=socket.gethostname(),
        user=getpass.getuser(),
        cwd=os.getcwd(),
        python_version=sys.version.replace("\n", " "),
        cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES"),
        gpu_name=gpu_name,
    )


def write_metadata(meta: BaseRunMetadata, path: str) -> None:
    """Write metadata to disk as indented JSON, creating parent dirs as needed."""
    import os

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(meta.model_dump_json(indent=2))
