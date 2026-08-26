"""Assert which tree a child interpreter ACTUALLY imports (P0 launch blocker).

The deployment venv's editable install maps every package to the MAIN
checkout, which may sit on an unrelated branch. A chain child whose cwd
leaves the campaign worktree then silently imports THAT tree's code — the
concrete observed consequence being a campaign running WITHOUT #299's
divergence-record repair while its git SHA says otherwise (supervisor
finding, 2026-08-25; first seen as the lane's E1 trap). `PYTHONPATH=<tree>`
pins resolution; this probe proves the pin from a NEUTRAL cwd.

Run as a FILE from a directory OUTSIDE every checkout (the preflight copies
it to a fresh temp dir first): a `-c` probe is blind because the cwd itself
sits on sys.path. Exits 0 only when BOTH hold:

  1. ``agent.schemas.hyperparam_tuning.__file__`` resolves INSIDE the
     intended tree (argv[1]);
  2. its ``loss_history`` annotation is the #299-tolerant
     ``list[float | None]`` — the semantic witness that the resolved tree
     really carries the divergence-record repair, not merely the right path.

Usage: python _import_resolution_probe.py <intended-repo-root>
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: _import_resolution_probe.py <intended-repo-root>", file=sys.stderr)
        return 2
    intended = Path(sys.argv[1]).resolve()

    import agent.schemas.hyperparam_tuning as hpt

    resolved = Path(hpt.__file__).resolve()
    print(f"[import-probe] hyperparam_tuning -> {resolved}")
    if not str(resolved).startswith(str(intended) + "/"):
        print(
            f"[import-probe] FAIL: resolves OUTSIDE the intended tree {intended} — "
            "an unpinned child imports another checkout's code. Export "
            "PYTHONPATH=<campaign tree> (the launchers do this; a bespoke "
            "invocation must too).",
            file=sys.stderr,
        )
        return 1

    import inspect
    import re

    src = inspect.getsource(hpt)
    m = re.search(r"^\s+loss_history:\s*([^\n=]+?)\s*(?:=|$)", src, re.MULTILINE)
    ann = m.group(1).strip() if m else "<not found>"
    print(f"[import-probe] loss_history: {ann}")
    if "list[float | None]" not in ann:
        print(
            f"[import-probe] FAIL: loss_history is {ann!r}, not the #299-tolerant "
            "'list[float | None]' — the resolved tree predates the "
            "divergence-record repair; a diverged iteration would be DISCARDED.",
            file=sys.stderr,
        )
        return 1
    print("[import-probe] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
