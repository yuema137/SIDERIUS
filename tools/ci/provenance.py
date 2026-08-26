"""The run manifest — what environment produced this result.

A test result is meaningful only if you can say what produced it, and the
question that motivated this lane — *"why did this pass locally but fail on
CI?"* — is unanswerable after the fact unless the answer was recorded during.

Designed to be **diffed**, not merely emitted: candidate vs base, local vs
remote. Fields are flat and typed for that reason.

**Secrets never appear.** Environment variables are recorded by NAME only, and
that is a tested property rather than a convention.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tools.ci.execution import THREAD_VARS, UNPINNED_RESIDUAL
from tools.ci.preflight import DECLARED_RESOURCES, MACHINE_CONFIG_FILES, resource_state

SCHEMA_VERSION = 1

#: Recorded by name only, never value. Anything matching these fragments is
#: additionally excluded from the name list — a variable called
#: ``OPENAI_API_KEY`` should not even have its existence advertised in an
#: artifact that may be attached to a public run.
_SECRET_FRAGMENTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")


class SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha: str | None = None
    branch: str | None = None
    dirty: bool = False
    untracked: int = 0
    root: str = ""


class InterpreterProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python_version: str = ""
    venv_path: str = ""
    lock_sha256: str | None = None


class PlatformProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str = ""
    release: str = ""
    machine: str = ""
    #: The number the host advertises. NOT necessarily the effective budget:
    #: sched_getaffinity ignores cgroup quotas and Python 3.12 has no
    #: os.process_cpu_count(), which is exactly why the CI shard profile is
    #: DECLARED rather than detected.
    cpu_count: int | None = None
    affinity_count: int | None = None
    cgroup_cpu_max: str | None = None
    load_avg: tuple[float, float, float] | None = None
    #: GitHub sets these; absent locally.
    runner_name: str | None = None
    runner_os: str | None = None


class ExecutionProfile(BaseModel):
    """What the run DECLARED, so a mismatch with platform facts is visible."""

    model_config = ConfigDict(extra="forbid")

    declared_shards: int = 0
    declared_threads_per_shard: int = 0
    thread_vars: tuple[str, ...] = THREAD_VARS
    unpinned_residual: str = UNPINNED_RESIDUAL
    home_strategy: str = "inherited"
    tmpdir_strategy: str = "per-shard"
    cwd: str = ""


class RunManifest(BaseModel):
    """One parity run, completely described."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    mode: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    source: SourceProvenance = Field(default_factory=SourceProvenance)
    interpreter: InterpreterProvenance = Field(default_factory=InterpreterProvenance)
    platform_facts: PlatformProvenance = Field(default_factory=PlatformProvenance)
    profile: ExecutionProfile = Field(default_factory=ExecutionProfile)
    config_presence: dict[str, bool] = Field(default_factory=dict)
    resource_presence: dict[str, str] = Field(default_factory=dict)
    selection: dict[str, object] = Field(default_factory=dict)
    env_var_names: list[str] = Field(default_factory=list)
    shards: list[dict[str, object]] = Field(default_factory=list)
    totals: dict[str, object] = Field(default_factory=dict)


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=60
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def safe_env_names(environ: dict[str, str] | None = None) -> list[str]:
    """Variable NAMES only, with anything secret-shaped omitted entirely.

    Recording a value would leak it; recording the name of a credential
    variable still advertises which secrets a runner holds, so both are
    dropped.
    """
    source = environ if environ is not None else dict(os.environ)
    return sorted(
        name
        for name in source
        if not any(fragment in name.upper() for fragment in _SECRET_FRAGMENTS)
    )


def _cgroup_cpu_max() -> str | None:
    for candidate in ("/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"):
        try:
            return Path(candidate).read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return None


def build_manifest(
    root: Path,
    *,
    mode: str,
    declared_shards: int,
    declared_threads: int,
    selection: dict[str, object] | None = None,
    started_at: float | None = None,
) -> RunManifest:
    """Capture everything needed to explain this run later."""
    lock = root / "uv.lock"
    lock_digest = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None
    modified = [ln for ln in _git(root, "diff", "--name-only").splitlines() if ln.strip()]
    untracked = [
        ln for ln in _git(root, "ls-files", "--others", "--exclude-standard").splitlines() if ln
    ]
    try:
        load = os.getloadavg()
    except OSError:
        load = None

    return RunManifest(
        mode=mode,
        started_at=started_at if started_at is not None else time.time(),
        source=SourceProvenance(
            sha=_git(root, "rev-parse", "HEAD") or None,
            branch=_git(root, "rev-parse", "--abbrev-ref", "HEAD") or None,
            dirty=bool(modified),
            untracked=len(untracked),
            root=str(root),
        ),
        interpreter=InterpreterProvenance(
            python_version=platform.python_version(),
            venv_path=str(root / ".venv"),
            lock_sha256=lock_digest,
        ),
        platform_facts=PlatformProvenance(
            system=platform.system(),
            release=platform.release(),
            machine=platform.machine(),
            cpu_count=os.cpu_count(),
            affinity_count=len(os.sched_getaffinity(0))
            if hasattr(os, "sched_getaffinity")
            else None,
            cgroup_cpu_max=_cgroup_cpu_max(),
            load_avg=load,
            runner_name=os.environ.get("RUNNER_NAME"),
            runner_os=os.environ.get("RUNNER_OS"),
        ),
        profile=ExecutionProfile(
            declared_shards=declared_shards,
            declared_threads_per_shard=declared_threads,
            home_strategy="inherited" if os.environ.get("HOME") else "unset",
            cwd=os.getcwd(),
        ),
        config_presence={name: (root / name).exists() for name in MACHINE_CONFIG_FILES},
        resource_presence={r.name: resource_state(r).value for r in DECLARED_RESOURCES},
        selection=selection or {},
        env_var_names=safe_env_names(),
    )
