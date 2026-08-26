"""Shard execution — one pytest process per shard, owned and isolated.

Each shard is a separate process in its **own process group**, with its own
``TMPDIR`` and pinned thread counts, writing its own JUnit XML. Nothing is
shared but the read-only source tree.

Three design points that exist because their opposites have caused real damage
in this repository:

* **Process ownership is by PID / process group, never by name matching.**
  ``pgrep -f`` patterns match the watcher's own shell and kill unrelated work;
  the harness therefore tracks the ``Popen`` objects it created and signals
  their process groups.
* **A failing shard does not abort its siblings.** Their evidence is worth
  keeping, and killing them would rebuild the fix-one/rerun loop this lane
  exists to remove. The aggregate is RED; the survivors still report.
* **Thread pinning is not a benchmark tweak.** torch defaults to 12 intra-op
  threads on this 24-core host, so unpinned shards multiply into uncontrolled
  oversubscription and the timing lane's assumptions break. The variables below
  were measured, not guessed.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tools.ci.shards import ShardPlan

#: Measured on this host at base 84d74280, not assumed:
#:   default              torch intra-op 12, numpy BLAS = scipy-openblas
#:   OMP_NUM_THREADS=2    torch intra-op -> 2
#:   MKL_NUM_THREADS=2    torch intra-op -> 2
#: OPENBLAS_NUM_THREADS is included because numpy's backend IS scipy-openblas.
#: Deliberately short: a long generic export list would be cargo cult.
THREAD_VARS: tuple[str, ...] = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
)

#: torch's INTER-op pool ignores the variables above and stays at cpu_count;
#: it is settable only in-process via torch.set_num_interop_threads(). Recorded
#: as a known residual rather than silently ignored.
UNPINNED_RESIDUAL = "torch inter-op threads (env-uncontrollable; defaults to cpu_count)"


class ShardResult(BaseModel):
    """What one shard produced. Enough to attribute a failure to it."""

    model_config = ConfigDict(extra="forbid")

    index: int
    files: tuple[str, ...]
    returncode: int | None
    duration_s: float
    tmpdir: str
    junit_xml: str | None = None
    log_path: str | None = None
    #: Set when the harness itself invalidated the shard (source mutated,
    #: killed, bootstrap missing). Such a shard is NOT a product failure.
    invalid_reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.invalid_reason is None and self.returncode == 0

    def size_str(self) -> str:
        return f"{len(self.files):>3} files"

    def failing_nodes(self, limit: int = 25) -> list[str]:
        """Node ids this shard reported as FAILED or ERROR.

        Read from the shard's own JUnit when present, falling back to the
        pytest log's ``FAILED``/``ERROR`` lines. Two sources because the point
        is that the operator sees the failures even when one of them is
        missing — which is how the first remote run produced a RED with no
        evidence at all.
        """
        nodes: list[str] = []
        if self.junit_xml and Path(self.junit_xml).is_file():
            try:
                root = ET.parse(self.junit_xml).getroot()
            except ET.ParseError:
                root = None
            if root is not None:
                for tc in root.iter("testcase"):
                    if any(ch.tag in ("failure", "error") for ch in tc):
                        nodes.append(f"{tc.get('classname')}::{tc.get('name')}")
        if not nodes and self.log_path and Path(self.log_path).is_file():
            text = Path(self.log_path).read_text(encoding="utf-8", errors="replace")
            nodes = [
                line.split(" ", 1)[1].strip()
                for line in text.splitlines()
                if line.startswith(("FAILED ", "ERROR "))
            ]
        deduped = list(dict.fromkeys(nodes))
        if len(deduped) > limit:
            return [*deduped[:limit], f"... and {len(deduped) - limit} more"]
        return deduped


class BulkResult(BaseModel):
    """Aggregate over all bulk shards."""

    model_config = ConfigDict(extra="forbid")

    sha: str
    shards: list[ShardResult] = Field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def wall_clock_s(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    @property
    def invalid(self) -> list[ShardResult]:
        """Shards whose evidence the harness itself invalidated."""
        return [s for s in self.shards if s.invalid_reason is not None]

    @property
    def failed(self) -> list[ShardResult]:
        """Genuine product failures — invalid shards are excluded on purpose."""
        return [s for s in self.shards if s.invalid_reason is None and s.returncode != 0]

    @property
    def ok(self) -> bool:
        """Green only when nothing failed AND nothing was invalidated.

        An invalidated shard is not a pass: its tests did not produce usable
        evidence, and reporting green would be the exact confident-nonsense
        failure the preflight exists to prevent.
        """
        return not self.failed and not self.invalid

    def longest(self) -> ShardResult | None:
        return max(self.shards, key=lambda s: s.duration_s, default=None)

    def render(self) -> str:
        """Summary, plus the failing nodes INLINE.

        A shard writes its pytest output to a file, which is invisible in a CI
        log. The first remote run reported ``shard 3 FAILED`` and nothing
        else — the artifact carrying the detail had silently uploaded nothing,
        so a RED run produced no attributable evidence whatsoever. That is the
        exact failure this harness exists to prevent, so the failing node ids
        are echoed here and never depend on an artifact surviving.
        """
        lines = [
            f"{'GREEN' if self.ok else 'RED'} — {len(self.shards)} shards @ {self.sha[:8]} "
            f"in {self.wall_clock_s:.1f}s"
        ]
        for s in sorted(self.shards, key=lambda s: -s.duration_s):
            state = "invalid" if s.invalid_reason else ("ok" if s.passed else "FAILED")
            lines.append(f"  shard {s.index:>2} {state:>7} {s.size_str()} {s.duration_s:7.1f}s")
            if s.invalid_reason:
                lines.append(f"      INVALID_HARNESS_EVIDENCE: {s.invalid_reason}")
        failing = [s for s in self.shards if not s.passed and s.invalid_reason is None]
        if failing:
            lines.append("")
            lines.append("FAILING NODES (from each shard's own log):")
            for s in sorted(failing, key=lambda s: s.index):
                for nid in s.failing_nodes():
                    lines.append(f"  shard {s.index:>2}  {nid}")
                lines.append(f"      full output: {s.log_path}")
        return "\n".join(lines)


def shard_environment(
    base: Mapping[str, str],
    *,
    tmpdir: Path,
    threads: int,
) -> dict[str, str]:
    """Environment for one shard: isolated TMPDIR, pinned threads.

    Returns a copy — a shard must never mutate the parent's environment, or
    concurrent shards would race through it.
    """
    env = dict(base)
    env["TMPDIR"] = str(tmpdir)
    for var in THREAD_VARS:
        env[var] = str(threads)
    return env


def run_shard(
    root: Path,
    index: int,
    files: Sequence[str],
    *,
    workdir: Path,
    threads: int,
    pytest_args: Sequence[str] = ("-q", "-p", "no:cacheprovider"),
    marker: str = "not real_run",
    timeout_s: float | None = None,
) -> ShardResult:
    """Run one shard to completion in its own process group.

    The process group matters: on timeout the whole tree is signalled, so a
    pytest that spawned children cannot leave orphans behind.
    """
    tmpdir = workdir / f"shard{index:02d}_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    junit = workdir / f"shard{index:02d}.xml"
    log = workdir / f"shard{index:02d}.log"

    python = root / ".venv" / "bin" / "python"
    cmd = [
        str(python),
        "-m",
        "pytest",
        *files,
        "-m",
        marker,
        *pytest_args,
        f"--junitxml={junit}",
    ]
    env = shard_environment(os.environ, tmpdir=tmpdir, threads=threads)

    started = time.monotonic()
    invalid: str | None = None
    returncode: int | None = None
    with log.open("wb") as sink:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=root,
                env=env,
                stdout=sink,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # own process group; see module docstring
            )
        except OSError as exc:
            # Typically a missing or unrunnable <root>/.venv/bin/python. That is
            # a harness fault, not a product failure, and must never be counted
            # as a test result.
            return ShardResult(
                index=index,
                files=tuple(files),
                returncode=None,
                duration_s=0.0,
                tmpdir=str(tmpdir),
                invalid_reason=f"could not start pytest: {exc}",
            )
        try:
            returncode = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _terminate_group(proc)
            invalid = f"shard exceeded {timeout_s}s and was terminated"
            returncode = None

    return ShardResult(
        index=index,
        files=tuple(files),
        returncode=returncode,
        duration_s=time.monotonic() - started,
        tmpdir=str(tmpdir),
        junit_xml=str(junit) if junit.exists() else None,
        log_path=str(log),
        invalid_reason=invalid,
    )


def _terminate_group(proc: subprocess.Popen[bytes]) -> None:
    """Signal the shard's own process group — never a name match.

    ``os.killpg`` on a group this harness created cannot reach a bystander's
    pytest, which a ``pgrep -f pytest`` sweep absolutely can.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


class WorkdirInsideSourceTree(RuntimeError):
    """The harness was asked to write inside the tree it is testing.

    Every shard's ``TMPDIR`` lives under the workdir, so a workdir inside the
    checkout puts every ``tmp_path`` inside the repository. Two real failures
    came from exactly that, in one remote run:

    * a test needing a NON-git directory got one inside the repo, so
      ``git rev-parse`` succeeded and the assertion inverted;
    * one shard's fixture wrote a deliberately-malformed ``.py`` file into its
      ``tmp_path``, and ANOTHER shard's repository-walking census parsed it and
      died on ``SyntaxError``.

    Cross-shard contamination of the source tree. The harness's own rule is
    that no shard mutates the checkout during execution, so this refuses rather
    than warns.
    """


def _reject_workdir_inside(root: Path, workdir: Path) -> None:
    root_r, work_r = root.resolve(), workdir.resolve()
    if work_r == root_r or root_r in work_r.parents:
        raise WorkdirInsideSourceTree(
            f"workdir {work_r} is inside the source tree {root_r}. Every shard's "
            f"TMPDIR would then live in the checkout, so tests observe harness "
            f"scratch as repository content. Use a path outside the tree — "
            f"$RUNNER_TEMP on CI, the system temp locally."
        )


def run_bulk(
    root: Path,
    plan: ShardPlan,
    *,
    sha: str,
    workdir: Path,
    threads: int,
    concurrency: int | None = None,
    timeout_s: float | None = None,
) -> BulkResult:
    """Run every bulk shard, letting siblings finish when one fails.

    ``concurrency`` bounds how many shards run at once. It defaults to the shard
    count, but the caller should size it against ``cpu_count // threads`` — one
    pytest process is not one CPU (docs/testing/ci_parity.md §3.1).
    """
    _reject_workdir_inside(root, workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    limit = concurrency or len(plan.shards)
    result = BulkResult(sha=sha, started_at=time.time())

    # A thread pool is safe here: each worker only waits on its own child
    # process, so the GIL is released and nothing is shared but the result list.
    with ThreadPoolExecutor(max_workers=max(1, limit)) as pool:
        futures = [
            pool.submit(
                run_shard,
                root,
                shard.index,
                shard.files,
                workdir=workdir,
                threads=threads,
                timeout_s=timeout_s,
            )
            for shard in plan.shards
        ]
        # No early cancellation: a failing shard must not discard the evidence
        # its siblings are still producing.
        for fut in futures:
            result.shards.append(fut.result())

    result.shards.sort(key=lambda s: s.index)
    result.finished_at = time.time()
    return result
