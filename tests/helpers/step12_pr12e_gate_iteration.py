"""Gate-time provenance wrapper for ONE chain iteration — PR-12e, workstream C.

Design §K requires `G-12e`'s evidence to *record* process provenance. Nothing
production writes carries it: ``iter_NNN/manifest.json`` has no pid,
``{workspace}/.token_run_id`` carries only the pid of whichever process created
it (iteration 1's), and ``owning_process_pid`` belongs to a training
grandchild's memory observation, which a CPU-only run never produces.

12e's whole graduation claim is that a fourth task needs **zero infrastructure
edits**, so the recorder cannot be added to ``run_one_iteration.py``. Instead
this wrapper runs the real runner **inside its own interpreter** via
``runpy``: the identity it records IS the identity of the process that then
executes the iteration, with no coupling to what that process does.

Usage — one invocation per iteration::

    .venv/bin/python tests/helpers/step12_pr12e_gate_iteration.py \\
        --provenance-workspace "$WS" \\
        --provenance-iteration 1 \\
        -- --workspace "$WS" --run_name g12e --start_iteration 1 ...

Everything after ``--`` is the target's own argv, forwarded byte-for-byte. The
wrapper parses no runner flag and forwards no flag of its own, so the launch it
performs is the launch the operator wrote.

**Why in-process and not "spawn the runner as a child".** A wrapper that
spawned the runner would record the WRAPPER's identity, and every iteration
would then share one wrapper lineage while the real runners went unrecorded.
``runpy`` keeps recorder and workload in one interpreter, which is exactly the
claim the evidence has to support.

The provenance is written BEFORE the runner starts, so an iteration that
crashes still leaves the evidence of which process attempted it.
"""

from __future__ import annotations

import os
import pathlib
import runpy
import sys
from collections.abc import Sequence

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The production per-iteration runner. Derived from this file's location so
#: the wrapper always drives the checkout it lives in (CLAUDE.md portability
#: rule) — never a differently-rooted clone that happens to be on the path.
DEFAULT_TARGET = REPO_ROOT / "src" / "workflows" / "run_one_iteration.py"

_USAGE = (
    "usage: step12_pr12e_gate_iteration.py --provenance-workspace WS "
    "--provenance-iteration N [--provenance-target PATH] -- <runner argv...>"
)


class WrapperUsageError(SystemExit):
    """The wrapper's own arguments are wrong. Distinct from a runner failure."""

    def __init__(self, message: str) -> None:
        super().__init__(f"[step12-pr12e] {message}\n{_USAGE}")


def _parse(argv: Sequence[str]) -> tuple[str, int, pathlib.Path, list[str]]:
    """Split the wrapper's own flags from the target's argv at ``--``.

    Hand-parsed rather than ``argparse``-parsed on purpose: ``argparse`` would
    claim runner flags it recognises (``--workspace`` is spelled the same on
    both sides), and a wrapper that rewrites the launch is a wrapper whose
    evidence describes a different run than the operator asked for.
    """
    if "--" not in argv:
        raise WrapperUsageError("the target's argv must follow a bare '--' separator")
    split = list(argv).index("--")
    mine, theirs = list(argv[:split]), list(argv[split + 1 :])
    workspace: str | None = None
    iteration: int | None = None
    target = DEFAULT_TARGET
    index = 0
    while index < len(mine):
        flag = mine[index]
        if index + 1 >= len(mine):
            raise WrapperUsageError(f"{flag} requires a value")
        value = mine[index + 1]
        if flag == "--provenance-workspace":
            workspace = value
        elif flag == "--provenance-iteration":
            try:
                iteration = int(value)
            except ValueError as exc:
                raise WrapperUsageError(
                    f"--provenance-iteration must be an int, got {value!r}"
                ) from exc
        elif flag == "--provenance-target":
            target = pathlib.Path(value)
        else:
            raise WrapperUsageError(f"unknown wrapper flag {flag!r}")
        index += 2
    if workspace is None or iteration is None:
        raise WrapperUsageError("--provenance-workspace and --provenance-iteration are required")
    if not theirs:
        raise WrapperUsageError("no target argv supplied after '--'")
    return workspace, iteration, target, theirs


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    workspace, iteration, target, target_argv = _parse(raw)

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tests.helpers.step12_pr12e_restore_harness import record_iteration_process

    os.makedirs(workspace, exist_ok=True)
    entry = record_iteration_process(workspace, iteration)
    print(
        f"[step12-pr12e] iteration {iteration} provenance: pid={entry.identity.pid} "
        f"nonce={entry.identity.interpreter_nonce}",
        flush=True,
    )

    if not target.is_file():
        raise WrapperUsageError(f"target {str(target)!r} does not exist")

    sys.argv = [str(target), *target_argv]
    try:
        runpy.run_path(str(target), run_name="__main__")
    except SystemExit as exit_signal:
        code = exit_signal.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
