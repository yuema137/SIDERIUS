"""The H100 posture file is a real, sourceable, documented contract (issue #261).

`sdsc_submission_scripts/h100_posture.env` is `source`d by the campaign
launcher after `--h100`. Three defects only these tests catch:

1. **A typo'd export.** `export SIDERIUS_PAIR_VRAM_CEILNG_GIB=64` is a valid
   bash line that sets a variable nothing reads, and the run then executes
   under the 28 GiB compatibility default it was meant to replace. The test
   resolves every exported `SIDERIUS_*` name against the string constants
   in production Python (AST, docstrings excluded) and the `$NAME` reads in
   the chain scripts — a name no production module reads is RED.
2. **A flag the chain would reject.** `_chain_common.sh`'s parser is a
   `case` statement; an unknown flag is not silently ignored, it aborts
   the launch. Every `--flag` in `H100_CHAIN_ARGS` must be a case label.
3. **Runbook/file drift.** The operator reads the table in
   `docs/guides/operating-a-run.md`; the launcher reads the file. Every
   value the file ships must appear in Table 1 under the same surface with
   the same value, and every row of Table 1 must be backed by the file
   (a value marked `unset` must be a commented placeholder, not an export).

How they fail when the behaviour breaks: change `64` to `56` in the file
without touching the table → `test_every_shipped_value_matches_the_runbook_table`
names the surface and both values; misspell an export → `test_every_exported_name_is_one_production_reads`
names it; add `--no_such_flag` → `test_every_chain_flag_is_accepted_by_the_chain_parser`
names it. Each was plant-proven at authoring time (see the PR body).

The file is sourced in a CLEAN environment (`env -i`) under
`set -euo pipefail`, exactly as a launcher would, so an unbound-variable
reference or a stray command in the file is also RED.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
POSTURE_FILE = REPO_ROOT / "sdsc_submission_scripts" / "h100_posture.env"
CHAIN_COMMON = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"
RUNBOOK = REPO_ROOT / "docs" / "guides" / "operating-a-run.md"

TABLE_BEGIN = "<!-- h100-posture-table:begin -->"
TABLE_END = "<!-- h100-posture-table:end -->"

#: Where the runtime lives. `tools/` and `tests/` are deliberately absent: a
#: name read only by tooling or by a test is not one a campaign executes under.
PRODUCTION_PY_ROOTS = ("core", "agent", "execute_tools", "nodes", "workflows")
PRODUCTION_SH_ROOT = "sdsc_submission_scripts"

_BASH = ["env", "-i", "PATH=/usr/bin:/bin", "bash", "-c"]


def _source_and_run(tail: str) -> subprocess.CompletedProcess[str]:
    script = f'set -euo pipefail\nsource "{POSTURE_FILE}"\n{tail}'
    return subprocess.run([*_BASH, script], capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def sourced() -> dict[str, object]:
    """The posture as bash sees it: scalars, exports and the array."""
    tail = (
        "printf 'VERSION=%s\\n' \"$H100_POSTURE_VERSION\"\n"
        "printf 'MAX_ACTIVE=%s\\n' \"$H100_MAX_ACTIVE_PER_CARD\"\n"
        "env | grep '^SIDERIUS_' | sed 's/^/EXPORT=/' || true\n"
        "printf 'ARG=%s\\n' \"${H100_CHAIN_ARGS[@]}\"\n"
    )
    r = _source_and_run(tail)
    assert r.returncode == 0, f"sourcing the posture failed:\n{r.stderr}"
    version = ""
    max_active = ""
    exports: dict[str, str] = {}
    args: list[str] = []
    for line in r.stdout.splitlines():
        key, _, value = line.partition("=")
        if key == "VERSION":
            version = value
        elif key == "MAX_ACTIVE":
            max_active = value
        elif key == "EXPORT":
            name, _, val = value.partition("=")
            exports[name] = val
        elif key == "ARG":
            args.append(value)
    return {"version": version, "max_active": max_active, "exports": exports, "args": args}


def _array_as_pairs(args: list[str]) -> dict[str, str]:
    """`--flag VALUE` -> {flag: VALUE}; a bare `--switch` -> {switch: "on"}."""
    out: dict[str, str] = {}
    i = 0
    while i < len(args):
        flag = args[i]
        assert flag.startswith("--"), f"array element {flag!r} is not a flag"
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            out[flag] = args[i + 1]
            i += 2
        else:
            out[flag] = "on"
            i += 1
    return out


# ---------------------------------------------------------------------------
# 1. Contract shape
# ---------------------------------------------------------------------------


class TestContractShape:
    def test_sourcing_is_side_effect_free_under_strict_mode(self) -> None:
        r = _source_and_run("")
        assert r.returncode == 0, r.stderr
        assert r.stdout == "", f"sourcing the posture must print nothing, got {r.stdout!r}"

    def test_version_and_topology_are_declared(self, sourced: dict[str, object]) -> None:
        # Declared delta (2026-08-25): v1 pinned "1" (one chain per card). The
        # author's fleet ruling (#261/#259 comments, 2026-08-25) moved the
        # campaign to FOUR co-resident band chains per 80 GB H100; posture v2
        # ships that topology, and this pin moves WITH the ruling — a drift
        # back to 1 (or any other value) without a new ruling is the defect.
        assert re.fullmatch(r"\d+", str(sourced["version"])), sourced["version"]
        assert sourced["max_active"] == "4", (
            "four co-resident band chains per card (fleet ruling 2026-08-25)"
        )

    def test_the_array_is_defined_and_non_empty(self, sourced: dict[str, object]) -> None:
        r = _source_and_run("declare -p H100_CHAIN_ARGS")
        assert r.returncode == 0 and r.stdout.startswith("declare -a H100_CHAIN_ARGS="), r.stdout
        assert sourced["args"], "H100_CHAIN_ARGS must carry at least one chain flag"
        assert "--trial_vram_budget_gb" in sourced["args"]
        assert "--formal_vram_budget_gb" in sourced["args"]

    def test_the_two_mandatory_exports_are_present(self, sourced: dict[str, object]) -> None:
        exports = sourced["exports"]
        assert isinstance(exports, dict)
        assert "SIDERIUS_PAIR_VRAM_CEILING_GIB" in exports
        assert "SIDERIUS_PREFLIGHT_WORKER_MEM_GIB" in exports


# ---------------------------------------------------------------------------
# 2. Every exported name is one production reads
# ---------------------------------------------------------------------------


def _production_string_constants() -> set[str]:
    """String constants in production Python, docstrings excluded, plus the
    `$NAME` / `${NAME` reads in the chain scripts."""
    names: set[str] = set()
    for root in PRODUCTION_PY_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - a broken module fails elsewhere
                continue
            docstring_nodes = {
                id(node.value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            }
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstring_nodes
                ):
                    names.add(node.value)
    shell_read = re.compile(r"\$\{?(SIDERIUS_[A-Z0-9_]+)")
    for path in (REPO_ROOT / PRODUCTION_SH_ROOT).glob("*.sh"):
        names.update(shell_read.findall(path.read_text(encoding="utf-8")))
    return names


def test_every_exported_name_is_one_production_reads(sourced: dict[str, object]) -> None:
    exports = sourced["exports"]
    assert isinstance(exports, dict)
    readable = _production_string_constants()
    unread = sorted(name for name in exports if name not in readable)
    assert not unread, (
        "exported by h100_posture.env but read by NO production module — a typo "
        f"here silently runs the campaign under the default: {unread}"
    )


# ---------------------------------------------------------------------------
# 3. Every flag is one the chain parser accepts
# ---------------------------------------------------------------------------


def _chain_parser_flags() -> set[str]:
    text = CHAIN_COMMON.read_text(encoding="utf-8")
    flags: set[str] = set()
    for m in re.finditer(r"^\s*(--[A-Za-z0-9_|-]+)\)", text, flags=re.MULTILINE):
        flags.update(m.group(1).split("|"))
    assert flags, "no case labels found in _chain_common.sh — the parser moved?"
    return flags


def test_every_chain_flag_is_accepted_by_the_chain_parser(sourced: dict[str, object]) -> None:
    args = sourced["args"]
    assert isinstance(args, list)
    accepted = _chain_parser_flags()
    rejected = sorted(f for f in _array_as_pairs(args) if f not in accepted)
    assert not rejected, (
        "H100_CHAIN_ARGS carries a flag `_chain_common.sh` has no case label for — "
        f"the launch would abort on it: {rejected}"
    )


# ---------------------------------------------------------------------------
# 4. Runbook <-> file drift
# ---------------------------------------------------------------------------


def _runbook_table() -> dict[str, str]:
    """`{surface: H100 value}` from Table 1, read between its markers."""
    text = RUNBOOK.read_text(encoding="utf-8")
    start = text.find(TABLE_BEGIN)
    end = text.find(TABLE_END)
    assert start != -1 and end != -1 and start < end, "Table 1 markers missing from the runbook"
    rows: dict[str, str] = {}
    for line in text[start + len(TABLE_BEGIN) : end].splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not (cells[0].startswith("`") and cells[0].endswith("`")):
            continue  # header / separator rows
        surface = cells[0].strip("`")
        value = cells[1].strip("`")
        assert surface not in rows, f"duplicate Table 1 row for {surface}"
        rows[surface] = value
    assert rows, "Table 1 parsed to zero rows"
    return rows


def _shipped_values(sourced: dict[str, object]) -> dict[str, str]:
    exports = sourced["exports"]
    args = sourced["args"]
    assert isinstance(exports, dict) and isinstance(args, list)
    shipped: dict[str, str] = {
        "H100_POSTURE_VERSION": str(sourced["version"]),
        "H100_MAX_ACTIVE_PER_CARD": str(sourced["max_active"]),
    }
    shipped.update(exports)
    shipped.update(_array_as_pairs(args))
    return shipped


def test_every_shipped_value_matches_the_runbook_table(sourced: dict[str, object]) -> None:
    table = _runbook_table()
    shipped = _shipped_values(sourced)
    mismatches = {
        surface: (value, table.get(surface))
        for surface, value in shipped.items()
        if table.get(surface) != value
    }
    assert not mismatches, (
        "h100_posture.env and the runbook's Table 1 disagree "
        f"({{surface: (file, table)}}): {mismatches}"
    )


def test_every_runbook_row_is_backed_by_the_file(sourced: dict[str, object]) -> None:
    table = _runbook_table()
    shipped = _shipped_values(sourced)
    text = POSTURE_FILE.read_text(encoding="utf-8")
    problems: list[str] = []
    for surface, value in table.items():
        if value == "unset":
            if surface in shipped:
                problems.append(f"{surface}: table says unset, file exports it")
            if not re.search(rf"^#\s*export {re.escape(surface)}=", text, flags=re.MULTILINE):
                problems.append(f"{surface}: table says unset, file has no commented placeholder")
        elif surface not in shipped:
            problems.append(f"{surface}: in the table, not shipped by the file")
    assert not problems, "\n".join(problems)


def test_the_measure_rows_are_placeholders_not_numbers(sourced: dict[str, object]) -> None:
    """Pins the two names this stream could NOT justify a value for. The drift
    test above stays green if someone types a number into BOTH the file and
    the table — consistent, and invented. Filling either one is a posture
    version bump that must cite the on-box measurement, and must change this
    pin deliberately."""
    exports = sourced["exports"]
    assert isinstance(exports, dict)
    for name in ("SIDERIUS_SUBPROCESS_RSS_GB", "SIDERIUS_GPU_VRAM_QUOTA_MIB"):
        assert name not in exports, f"{name} must not be exported before the MEASURE row is filled"
