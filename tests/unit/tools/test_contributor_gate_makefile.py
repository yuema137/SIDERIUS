"""The contributor gate (`make check`) must not drift from CI's commands (issue #292).

The defect only this suite catches: `Makefile` and `.github/workflows/ci.yml`
are two hand-maintained surfaces claiming to run the SAME checks. Nothing else
compares them — ruff, pyright and Pydantic read neither file — so a command
edited in one place survives every other test, and `make check` keeps printing
green for a set of checks CI no longer runs (or CI tightens a command and the
local gate silently stops reproducing it).

How it fails when the behaviour breaks: change any of ruff-check /
ruff-format / pyright / unit-tier pytest arguments in exactly one of the two
files and the corresponding assertion names the string that no longer matches.
Every CI-side expectation is EXTRACTED from the workflow file at test time,
never hardcoded twice, so a reworded CI step fails here first and forces the
comparison to be re-anchored instead of drifting.

Plant evidence (2026-08-25, S7): editing the Makefile's pytest recipe from
`tests/unit/` to `tests/` turned test_gate_runs_ci_unit_tier_pytest_args RED;
reverting restored green.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _makefile_text() -> str:
    assert MAKEFILE.is_file(), "the contributor gate requires a Makefile at the repository root"
    return MAKEFILE.read_text(encoding="utf-8")


def _ci_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def _resolved_recipe_lines() -> list[str]:
    """Makefile recipe lines (tab-indented) with `$(UV_RUN)` substituted."""
    text = _makefile_text()
    match = re.search(r"^UV_RUN\s*:?=\s*(.+)$", text, flags=re.MULTILINE)
    assert match, "Makefile must define UV_RUN (the uv invocation prefix its recipes share)"
    prefix = match.group(1).strip()
    assert prefix.startswith("uv run"), (
        "the gate must invoke tools through `uv run`, the same runner CI uses; "
        f"UV_RUN is {prefix!r}"
    )
    return [
        line.strip().replace("$(UV_RUN)", prefix)
        for line in text.splitlines()
        if line.startswith("\t")
    ]


def test_gate_runs_ci_ruff_commands() -> None:
    """Defect: a ruff invocation (check / format --check) drifts between the two files."""
    ruff_cmds = re.findall(r"run: uv run (ruff [^\n]+)", _ci_text())
    assert sorted(ruff_cmds) == ["ruff check .", "ruff format --check ."], (
        "ci.yml no longer carries the two expected `uv run ruff …` steps; "
        f"found {ruff_cmds!r} — re-anchor the Makefile comparison"
    )
    recipes = _resolved_recipe_lines()
    for cmd in ruff_cmds:
        assert any(line.startswith("uv run") and line.endswith(cmd) for line in recipes), (
            f"CI runs `uv run {cmd}` but no Makefile recipe line ends with `{cmd}`"
        )


def test_gate_runs_ci_unit_tier_pytest_args() -> None:
    """Defect: the local gate's pytest tier drifts from the CI unit tier.

    Triple anchor: the workflow's full-suite fallback line, the selector's
    FULL_SUITE_ARGS constant, and the Makefile recipe must all agree — any
    pairwise divergence is named.
    """
    match = re.search(r"pytest_args=([^'\n]+)'", _ci_text())
    assert match, "ci.yml no longer embeds the full-suite pytest_args fallback line"
    ci_args = match.group(1)

    from tools.ci_selection.__main__ import FULL_SUITE_ARGS

    assert ci_args == FULL_SUITE_ARGS, (
        "the workflow's inline full-suite fallback and tools.ci_selection.FULL_SUITE_ARGS "
        f"disagree: {ci_args!r} != {FULL_SUITE_ARGS!r}"
    )

    wanted = f"pytest {ci_args}"
    recipes = _resolved_recipe_lines()
    assert any(line.startswith("uv run") and line.endswith(wanted) for line in recipes), (
        f"CI's unit tier is `pytest {ci_args}` but no Makefile recipe line runs it verbatim"
    )


def test_gate_covers_pyright_or_names_ci_as_owner() -> None:
    """Defect: the type-check stage silently disappears from the local gate.

    CI runs pyright unconditionally; the Makefile must both invoke it (the
    probe's success branch) and, in the skip branch, name the CI workflow as
    the owner — a bare skip with no owner is how a check gets forgotten.
    """
    assert re.search(r"run: uv run pyright\b", _ci_text()), (
        "ci.yml no longer runs `uv run pyright` — re-anchor the Makefile comparison"
    )
    recipes = _resolved_recipe_lines()
    invocations = [
        line
        for line in recipes
        if "pyright" in line and "--version" not in line and "echo" not in line
    ]
    assert invocations, "no Makefile recipe line actually invokes pyright"
    assert any("SKIP" in line and "ci.yml" in line for line in recipes), (
        "the pyright skip branch must print a labelled SKIP line naming "
        ".github/workflows/ci.yml as the owner"
    )


def test_check_target_runs_all_four_stages_in_ci_order() -> None:
    """Defect: `make check` drops or reorders a stage while the per-stage
    targets stay defined — every string-level assertion above stays green,
    but the aggregate a contributor actually types no longer runs the stage."""
    match = re.search(r"^check:\s*(.+)$", _makefile_text(), flags=re.MULTILINE)
    assert match, "Makefile must define a `check` aggregate target"
    assert match.group(1).split() == ["lint", "format-check", "typecheck", "test"], (
        "`make check` must run lint, format-check, typecheck, test — in CI's "
        f"cheap-first order; found {match.group(1).split()!r}"
    )
