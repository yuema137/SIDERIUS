"""Execution-root preflight — refuse early rather than mislead late.

The failure this exists to prevent is concrete and has already been paid for:
an unbootstrapped git worktree lacks ``<root>/.venv/bin/python``, two unit
tests execute that interpreter directly, and the run reports *product*
failures that are really harness failures. PR-12d spent a debugging cycle on
exactly that (docs/audit/ci_parity_audit.md, CP-3).

So before a parity run executes ~13,000 tests it answers a short list of
questions about the root it is about to run in. A violation yields
``HARNESS PREFLIGHT FAILURE`` naming the unmet condition and the remedy.

Design notes:

* Every check is a pure function of ``ExecutionRoot`` plus the filesystem, and
  returns a typed :class:`CheckResult`. There is no shared mutable state, so
  each check is independently testable.
* Checks never raise for an expected negative; they report. Only genuinely
  unexpected conditions propagate.
* This is NOT a second test suite (kickoff §8). It is a small set of
  preconditions whose violation invalidates every downstream result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# Machine-local files whose PRESENCE changes observable behaviour. Absence is
# the parity default: `tidmad_data_config.yaml` suppresses a UserWarning that a
# golden stderr comparison counted, which is how a green developer machine
# produced a red CI run (audit §2.A).
MACHINE_CONFIG_FILES: tuple[str, ...] = (
    "tidmad_data_config.yaml",
    "dashboard_config.yaml",
    ".env",
)

# pyright ships as a Python wrapper around a bundled Node program. A Node too
# old to run it makes the local type check unusable — not merely noisy — which
# is a limit on what a local parity run may CLAIM, not a reason to move the
# repository's pinned pyright version (audit CP-9).
MIN_NODE_MAJOR = 14


class Outcome(StrEnum):
    """Whether a single precondition is met."""

    OK = "ok"
    VIOLATION = "violation"
    #: The check could not be evaluated. Never silently treated as OK — an
    #: unevaluated precondition is not a satisfied one.
    UNKNOWN = "unknown"


class CheckResult(BaseModel):
    """One precondition, its verdict, and how to fix it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    outcome: Outcome
    detail: str
    remedy: str = ""


class ExecutionRoot(BaseModel):
    """A directory a parity run may execute in, and what is expected of it."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    #: Require a committed, non-dirty tree. The dirty-tree guard
    #: (scripts/pr3_l2_calibration/preflight.py:297) reads the live worktree,
    #: so a shard sharing a mutated tree produces invalid evidence.
    expect_clean: bool = True
    #: Require ``<root>/.venv/bin/python``. Two unit tests execute it.
    require_venv: bool = True
    #: Machine-local config files expected to be ABSENT (parity default).
    expect_absent: tuple[str, ...] = MACHINE_CONFIG_FILES
    #: Require a Node new enough to run pyright. Only for static-check runs.
    require_node_for_pyright: bool = False
    #: Claim CI parity for external resources: they must be ABSENT (CP-8).
    #: A misconfigured override is a violation regardless of this flag.
    expect_resources_absent: bool = False
    #: Require TMPDIR to be established in THIS process. Bulk/sensitive runs set
    #: this False: `run_shard` assigns each shard its own TMPDIR, so demanding
    #: one from the parent would be friction with no isolation benefit. It stays
    #: True for a bare preflight, where a human is about to run pytest directly
    #: and nothing else will set it.
    require_tmpdir: bool = True


class PreflightReport(BaseModel):
    """The full verdict for one execution root."""

    model_config = ConfigDict(extra="forbid")

    root: Path
    sha: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)

    @property
    def satisfied(self) -> bool:
        """True only if no check reported VIOLATION or UNKNOWN.

        UNKNOWN counts against the root deliberately: a precondition that could
        not be evaluated has not been met, and treating it as OK is how a
        harness starts producing confident nonsense.
        """
        return all(c.outcome is Outcome.OK for c in self.checks)

    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.outcome is not Outcome.OK]

    def render(self) -> str:
        """Operator-facing summary. Names the condition AND the remedy."""
        if self.satisfied:
            return f"PREFLIGHT OK — {self.root} @ {self.sha or 'unknown sha'}"
        lines = [f"HARNESS PREFLIGHT FAILURE — {self.root}"]
        for c in self.failures():
            lines.append(f"  [{c.outcome.value}] {c.name}: {c.detail}")
            if c.remedy:
                lines.append(f"      remedy: {c.remedy}")
        return "\n".join(lines)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def check_source_sha(root: Path) -> tuple[CheckResult, str | None]:
    """The root must resolve to an exact commit; results are attributed to it."""
    proc = _git(root, "rev-parse", "HEAD")
    if proc.returncode != 0:
        return (
            CheckResult(
                name="source_sha",
                outcome=Outcome.UNKNOWN,
                detail=f"git rev-parse HEAD failed in {root}: {proc.stderr.strip()}",
                remedy="run from inside a git checkout or worktree",
            ),
            None,
        )
    sha = proc.stdout.strip()
    return (
        CheckResult(name="source_sha", outcome=Outcome.OK, detail=sha),
        sha,
    )


def check_tree_clean(root: Path, *, expect_clean: bool) -> CheckResult:
    """Tracked files must be unmodified when the run declares a clean tree.

    Untracked files are NOT a violation: they are reported by the provenance
    manifest instead, so pollution stays observable without blocking a run.
    """
    if not expect_clean:
        return CheckResult(
            name="tree_clean",
            outcome=Outcome.OK,
            detail="not required by this run",
        )
    proc = _git(root, "diff", "--name-only")
    if proc.returncode != 0:
        return CheckResult(
            name="tree_clean",
            outcome=Outcome.UNKNOWN,
            detail=f"git diff failed: {proc.stderr.strip()}",
        )
    modified = [line for line in proc.stdout.splitlines() if line.strip()]
    if modified:
        shown = ", ".join(modified[:5]) + ("…" if len(modified) > 5 else "")
        return CheckResult(
            name="tree_clean",
            outcome=Outcome.VIOLATION,
            detail=f"{len(modified)} tracked file(s) modified: {shown}",
            remedy="commit or stash before a parity run; a mutating tree invalidates every shard",
        )
    return CheckResult(name="tree_clean", outcome=Outcome.OK, detail="no tracked modifications")


def venv_python(root: Path) -> Path:
    """The interpreter path tests rely on. One definition, used everywhere."""
    return root / ".venv" / "bin" / "python"


def check_venv(root: Path, *, require: bool) -> CheckResult:
    """``<root>/.venv/bin/python`` must exist AND run.

    Existence alone is insufficient — a symlink into another checkout's
    environment makes the path resolve while proving nothing about installed
    package identity, which is why the contract mandates a per-root
    ``uv sync --group dev --frozen`` (docs/testing/ci_parity.md §2.1).
    """
    if not require:
        return CheckResult(name="venv", outcome=Outcome.OK, detail="not required by this run")
    python = venv_python(root)
    if not python.exists():
        return CheckResult(
            name="venv",
            outcome=Outcome.VIOLATION,
            detail=f"{python} does not exist",
            remedy=f"cd {root} && uv sync --group dev --frozen",
        )
    try:
        proc = subprocess.run(
            [str(python), "-c", "import sys; print(sys.version.split()[0])"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # A path that exists but is not a runnable interpreter — a truncated
        # file, a dangling symlink, a wrong-architecture binary — raises here
        # rather than returning non-zero. Preflight must REPORT that, not
        # crash: a stack trace out of the guard is indistinguishable from the
        # harness itself being broken.
        return CheckResult(
            name="venv",
            outcome=Outcome.VIOLATION,
            detail=f"{python} exists but failed to execute: {exc}",
            remedy=f"cd {root} && uv sync --group dev --frozen",
        )
    if proc.returncode != 0:
        return CheckResult(
            name="venv",
            outcome=Outcome.VIOLATION,
            detail=f"{python} exists but failed to execute: {proc.stderr.strip()}",
            remedy=f"cd {root} && uv sync --group dev --frozen",
        )
    return CheckResult(
        name="venv",
        outcome=Outcome.OK,
        detail=f"{python} → Python {proc.stdout.strip()}",
    )


def check_machine_configs(root: Path, *, expect_absent: tuple[str, ...]) -> CheckResult:
    """Parity is defined partly by ABSENCE.

    A present machine-local config silently changes observable behaviour; the
    run must therefore know which are there, not assume.
    """
    present = [name for name in expect_absent if (root / name).exists()]
    if present:
        return CheckResult(
            name="machine_configs_absent",
            outcome=Outcome.VIOLATION,
            detail=f"present but expected absent: {', '.join(present)}",
            remedy="run in a tracked-only checkout, or declare their presence explicitly",
        )
    return CheckResult(
        name="machine_configs_absent",
        outcome=Outcome.OK,
        detail=f"absent as expected: {', '.join(expect_absent)}",
    )


def node_major(executable: str = "node") -> int | None:
    """Major version of the available Node, or None when unusable."""
    path = shutil.which(executable)
    if path is None:
        return None
    proc = subprocess.run(
        [path, "--version"], capture_output=True, text=True, check=False, timeout=60
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip().lstrip("v").split(".")[0]
    try:
        return int(raw)
    except ValueError:
        return None


#: Setting this false makes the pyright wheel provision its OWN Node via
#: nodeenv instead of using the system one. Measured: it yields the locked
#: pyright 1.1.409 on a host whose system Node is v10.19.0.
MANAGED_NODE_ENV = {"PYRIGHT_PYTHON_GLOBAL_NODE": "false"}


def check_node_for_pyright(*, require: bool) -> CheckResult:
    """pyright needs a modern Node; an old one makes the check unusable.

    The remedy is a usable Node for the parity environment, NOT a different
    pyright — the version is fixed by ``uv.lock`` and moving it to repair one
    developer machine would change the repository's typecheck authority.

    When ``PYRIGHT_PYTHON_GLOBAL_NODE`` is false the system Node is irrelevant:
    the wheel provisions its own, so checking the host's version would refuse a
    root that works perfectly.
    """
    if not require:
        return CheckResult(
            name="node_for_pyright", outcome=Outcome.OK, detail="not required by this run"
        )
    if os.environ.get("PYRIGHT_PYTHON_GLOBAL_NODE", "").lower() in {"false", "0", "no"}:
        return CheckResult(
            name="node_for_pyright",
            outcome=Outcome.OK,
            detail="managed node (PYRIGHT_PYTHON_GLOBAL_NODE=false); system node not used",
        )
    major = node_major()
    if major is None:
        return CheckResult(
            name="node_for_pyright",
            outcome=Outcome.VIOLATION,
            detail="node is unavailable or did not report a version",
            remedy=f"provide Node >= {MIN_NODE_MAJOR}; do NOT change the pinned pyright version",
        )
    if major < MIN_NODE_MAJOR:
        return CheckResult(
            name="node_for_pyright",
            outcome=Outcome.VIOLATION,
            detail=f"node v{major} is too old to run pyright; local type-check results are NOT VALID EVIDENCE",
            remedy=f"provide Node >= {MIN_NODE_MAJOR}; do NOT change the pinned pyright version",
        )
    return CheckResult(name="node_for_pyright", outcome=Outcome.OK, detail=f"node v{major}")


def check_tmpdir(*, require: bool = True) -> CheckResult:
    """TMPDIR must be established, so shards cannot collide in a shared temp."""
    if not require:
        return CheckResult(
            name="tmpdir", outcome=Outcome.OK, detail="assigned per shard by the harness"
        )
    value = os.environ.get("TMPDIR")
    if not value:
        return CheckResult(
            name="tmpdir",
            outcome=Outcome.VIOLATION,
            detail="TMPDIR is unset; shards would share the system default",
            remedy="set TMPDIR to a per-shard directory",
        )
    if not Path(value).is_dir():
        return CheckResult(
            name="tmpdir",
            outcome=Outcome.VIOLATION,
            detail=f"TMPDIR={value} is not an existing directory",
            remedy="create the directory before the run",
        )
    return CheckResult(name="tmpdir", outcome=Outcome.OK, detail=value)


def run_preflight(root: ExecutionRoot) -> PreflightReport:
    """Evaluate every precondition for one execution root.

    Checks are independent and ALL are evaluated — the report lists the
    complete set of violations rather than stopping at the first, because
    fixing one at a time and re-running is the very loop this lane exists to
    remove (kickoff §24.12).
    """
    resolved = root.path.resolve()
    sha_check, sha = check_source_sha(resolved)
    checks = [
        sha_check,
        check_tree_clean(resolved, expect_clean=root.expect_clean),
        check_venv(resolved, require=root.require_venv),
        check_machine_configs(resolved, expect_absent=root.expect_absent),
        check_node_for_pyright(require=root.require_node_for_pyright),
        check_tmpdir(require=root.require_tmpdir),
        check_external_resources(expect_absent=root.expect_resources_absent),
    ]
    return PreflightReport(root=resolved, sha=sha, checks=checks)


# --------------------------------------------------------------------------
# External resources (CP-8)
# --------------------------------------------------------------------------


class ResourceState(StrEnum):
    """The three distinct states an external resource can be in.

    Collapsing ABSENT and MISCONFIGURED is the mistake CP-8 caught me making:
    pointing an override at a non-existent path produced 4 hard errors, because
    the tests correctly refuse a *set but invalid* path rather than skipping.
    Absence is legitimate; misconfiguration is a fault.
    """

    AVAILABLE = "available"
    ABSENT = "absent"
    MISCONFIGURED = "misconfigured"


class ExternalResource(BaseModel):
    """A machine-local dataset or reference tree that gates test applicability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    #: Where it lives when no override is set. May be absent on any given host.
    default_path: Path | None = None
    #: Environment variable that overrides ``default_path``, when one exists.
    env_var: str | None = None
    #: How many unit tests skip when it is absent (measured, CP-8).
    gates_skips: int = 0


#: Measured at base 84d74280: hiding these and unsetting the overrides moved the
#: suite from 5 skips to 48, matching CI exactly. See the audit's CP-8 section.
DECLARED_RESOURCES: tuple[ExternalResource, ...] = (
    ExternalResource(
        name="legacy_tidmad_root",
        default_path=Path("/home/tidmad/TIDMAD"),
        env_var="SIDERIUS_LEGACY_TIDMAD_ROOT",
        gates_skips=18,
    ),
    ExternalResource(
        name="pets_images",
        default_path=Path("/home/klz/Data/OXFORD_IIIT_PET/images"),
        env_var="SIDERIUS_PETS_DATA_DIR",
        gates_skips=17,
    ),
    ExternalResource(
        name="davis_frames",
        default_path=Path("/home/klz/Data/DAVIS_2017"),
        env_var="SIDERIUS_DAVIS_DATA_DIR",
        gates_skips=5,
    ),
)


def resource_state(resource: ExternalResource) -> ResourceState:
    """Classify one resource without judging whether that state is wanted."""
    if resource.env_var:
        override = os.environ.get(resource.env_var)
        if override:
            # Set-but-invalid is a FAULT, never a quiet skip: the tests
            # themselves refuse it loudly, and the harness must agree.
            return (
                ResourceState.AVAILABLE if Path(override).is_dir() else ResourceState.MISCONFIGURED
            )
    if resource.default_path is None:
        return ResourceState.ABSENT
    return ResourceState.AVAILABLE if resource.default_path.is_dir() else ResourceState.ABSENT


def check_external_resources(
    *,
    expect_absent: bool,
    resources: tuple[ExternalResource, ...] = DECLARED_RESOURCES,
) -> CheckResult:
    """Report resource availability, and refuse on misconfiguration.

    ``expect_absent`` expresses what the run CLAIMS. A CI-parity run needs them
    absent; a developer run may legitimately have them. Either way a
    MISCONFIGURED resource is a violation, because it is neither.
    """
    states = {r.name: resource_state(r) for r in resources}
    bad = [n for n, s in states.items() if s is ResourceState.MISCONFIGURED]
    if bad:
        return CheckResult(
            name="external_resources",
            outcome=Outcome.VIOLATION,
            detail=f"override set but not a directory: {', '.join(bad)}",
            remedy="unset the override to declare absence, or point it at a real directory",
        )
    present = [n for n, s in states.items() if s is ResourceState.AVAILABLE]
    if expect_absent and present:
        gated = sum(r.gates_skips for r in resources if r.name in present)
        return CheckResult(
            name="external_resources",
            outcome=Outcome.VIOLATION,
            detail=(
                f"present but this run claims CI parity: {', '.join(present)} "
                f"— ~{gated} tests would RUN here that SKIP on CI"
            ),
            remedy="hide them or unset their overrides, or drop the CI-parity claim",
        )
    summary = ", ".join(f"{n}={s.value}" for n, s in sorted(states.items()))
    return CheckResult(name="external_resources", outcome=Outcome.OK, detail=summary)
