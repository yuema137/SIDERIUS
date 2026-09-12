"""Operator/user-facing docs must not instruct editing in-tree framework files
(issue #285).

The defect only this test catches: a user-facing document teaches
*edit-the-checkout* as the way to use SIDERIUS — "edit
``configs/health_checks.yaml`` to …", "add your task to ``configs/…``" —
contradicting the external-path contract (task composition manifests anywhere
on disk, ``SIDERIUS_GENERATED_LIBRARY_DIR``, run-level CLI inputs, user
workspaces). No other guard can see it: Pydantic/pyright never read prose,
``test_md_links.py`` checks that link *targets resolve*, not what the
sentence around them tells the reader to do, and no reviewer reliably re-reads
every doc after the contract that made such sentences wrong landed (the
generated-library migration made checkout-mutation a removed defect, not a
documented behaviour).

How it fails when the behaviour breaks: add a sentence like "Edit
``configs/health_checks.yaml`` to change the roster." to any file in the
census set and ``test_user_docs_never_instruct_in_tree_edits`` goes RED
listing ``path:line`` and the offending sentence. The ``TestMatcherOracle``
class is the oracle for the matcher itself — if the verb/path regexes or the
fence skipper silently stop matching, the sweep would stay green for the
wrong reason, and those synthetic cases go RED instead.

Mechanism — deliberately a small, high-precision pattern census, not NLP:

* a unit of prose is one sentence (or one table cell / heading line), with
  fenced code blocks removed first — command *examples* are not instructions
  about framework files, but inline-code path mentions are kept because that
  is exactly how docs spell paths;
* a unit is flagged when it contains an imperative-form edit verb
  (``edit`` / ``modify`` / ``change`` / ``update`` / ``add`` / ``tweak`` /
  ``adjust`` — base form only, so "changed", "edits", "adding" never match;
  a NEGATED verb — "do not change", "never edit" — is stripped first,
  because an instruction *not* to edit is the opposite of the defect)
  **and** an in-tree framework path (``configs/*.y[a]ml``,
  ``ml_models/*.py``, ``core/``, ``execute_tools/``, ``nodes/``,
  ``agent/``) appears in the same or the immediately adjacent unit
  ("within one sentence", per the issue);
* one structural allowance: a unit beginning ``**Audience**:`` is never
  flagged — the module-README template opens every map with an audience
  declaration ("… about to modify the execution substrate") adjacent to a
  title that names the module path; it names the reader and instructs
  nothing;
* legitimate mentions are ALLOWLISTED individually: each entry quotes the
  exact flagged sentence, names its file, and states WHY it is legitimate
  (a maintainer-facing module-README section, or a description of what the
  FRAMEWORK does rather than an instruction to the user). A stale allowlist
  entry — one that no longer matches anything — fails the test, so the list
  cannot silently rot.

File set (an omitted file set is a known census-defect class, so it is
derived, not hand-enumerated): the root ``README.md``, every ``.md`` under
``docs/getting-started``, ``docs/guides``, ``docs/concepts``,
``docs/reference``, ``examples/quickstart/README.md``, and every module
README — all tracked ``<dir>/README.md`` files plus the two nested module
maps the template names (``agent/schemas``, ``execute_tools/health_checks``).
``test_census_file_set_is_complete`` pins the required members so a rename
or deletion is loud.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[3]

DOC_TREES = (
    "docs/getting-started",
    "docs/guides",
    "docs/concepts",
    "docs/reference",
)

#: Files that must be part of the census whatever the dynamic sweep finds.
#: Every path here must exist — a rename must update this list consciously.
REQUIRED_MEMBERS: tuple[str, ...] = (
    "README.md",
    "examples/quickstart/README.md",
    "src/agent/schemas/README.md",
    "src/execute_tools/health_checks/README.md",
    "src/core/README.md",
    "src/execute_tools/README.md",
    "configs/README.md",
    "scripts/README.md",
    "examples/README.md",
    "src/agent/README.md",
    "src/nodes/README.md",
    "src/tools/README.md",
    "docs/getting-started/first-run.md",
    "docs/guides/define-a-task.md",
    "docs/concepts/health-gates.md",
    "docs/reference/configuration-map.md",
)

_FENCE = re.compile(r"^\s*(```|~~~)")

#: Imperative-form edit verbs — base form only. "changed" / "edits" /
#: "adding" / "updated" deliberately do not match: descriptions of what
#: HAPPENED or what the framework DOES are not instructions to the reader.
_EDIT_VERB = re.compile(r"\b(edit|modify|change|update|add|tweak|adjust)\b", re.IGNORECASE)

#: A negated verb phrase is an instruction NOT to edit — stripped before the
#: verb search so "do not change …", "never edit …" cannot flag a unit.
_NEGATED_VERB = re.compile(
    r"\b(?:do not|don't|never|not to|no)\s+(?:hand-)?"
    r"(?:edit|modify|change|update|add|tweak|adjust)\b",
    re.IGNORECASE,
)

#: The module-README template's audience declaration — names the reader,
#: instructs nothing; sits adjacent to a title naming the module path.
_AUDIENCE_HEADER = re.compile(r"^\*\*Audience\*\*")

#: In-tree framework paths a user-facing doc must not tell the reader to
#: edit. Exactly the issue's six classes. `\bagent/` does not match
#: `agent_generated/` (underscore continues the word) or `agent-reference`.
_IN_TREE_PATH = re.compile(
    r"(?:\bconfigs/[\w<>./-]*\.ya?ml\b|\bml_models/[\w<>./-]*\.py\b"
    r"|\bcore/|\bexecute_tools/|\bnodes/|\bagent/)"
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Finding:
    source: str  # repo-relative posix path
    line: int  # 1-based line the flagged unit starts on
    unit: str  # the flagged sentence/cell text


# --- allowlist --------------------------------------------------------------
#
# Each entry: (file, exact substring of the flagged unit, why it is
# legitimate). The substring must keep matching a *currently flagged* unit in
# that file, or the test fails as stale.
ALLOWLIST: tuple[tuple[str, str, str], ...] = (
    (
        "examples/quickstart/README.md",
        "add `configs/task_composition/quickstart.yaml` binding it",
        "A struck-through (~~…~~), completed item of the pack's own "
        "post-PR-12d finalization checklist — a historical record of "
        "framework-side maintenance already executed, addressed to the "
        "pack's maintainers at the time, not an instruction to a reader "
        "using the framework.",
    ),
)


def _tracked_files() -> frozenset[str] | None:
    """Every path git tracks, or None outside a checkout."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return frozenset(p.decode("utf-8") for p in r.stdout.split(b"\0") if p)


def census_files() -> list[str]:
    """The census file set, derived — see the module docstring."""
    tracked = _tracked_files()

    def exists(rel: str) -> bool:
        return rel in tracked if tracked is not None else (REPO_ROOT / rel).is_file()

    members: set[str] = {rel for rel in REQUIRED_MEMBERS if exists(rel)}
    # The four user-facing docs trees, every .md.
    for tree in DOC_TREES:
        if tracked is not None:
            members.update(p for p in tracked if p.startswith(tree + "/") and p.endswith(".md"))
        else:
            members.update(
                p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / tree).glob("*.md")
            )
    # Every top-level module README, including every direct src package map
    # (dynamic: an omitted new module README is swept in, not silently absent).
    if tracked is not None:
        for p in tracked:
            parts = PurePosixPath(p).parts
            if (len(parts) == 2 and parts[1] == "README.md") or (
                len(parts) == 3 and parts[0] == "src" and parts[2] == "README.md"
            ):
                members.add(p)
    else:
        for p in REPO_ROOT.glob("*/README.md"):
            members.add(p.relative_to(REPO_ROOT).as_posix())
        for p in (REPO_ROOT / "src").glob("*/README.md"):
            members.add(p.relative_to(REPO_ROOT).as_posix())
    return sorted(members)


def extract_units(text: str) -> list[tuple[int, str]]:
    """(start_line, unit) pairs: sentences of prose paragraphs, plus table
    cells and headings as their own units. Fenced code blocks are removed;
    inline code is KEPT (paths are spelled in backticks)."""
    units: list[tuple[int, str]] = []
    paragraph: list[str] = []
    paragraph_start = 0
    in_fence = False

    def flush() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        joined = " ".join(s.strip() for s in paragraph)
        for sentence in _SENTENCE_SPLIT.split(joined):
            if sentence.strip():
                units.append((paragraph_start, sentence.strip()))
        paragraph = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("|"):
            flush()
            for cell in stripped.strip("|").split("|"):
                if cell.strip():
                    units.append((lineno, cell.strip()))
            continue
        if stripped.startswith("#"):
            flush()
            units.append((lineno, stripped.lstrip("# ").strip()))
            continue
        if not paragraph:
            paragraph_start = lineno
        paragraph.append(stripped)
    flush()
    return units


def flag_units(units: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Units containing an edit verb with an in-tree path in the same or the
    immediately adjacent unit."""
    flagged: list[tuple[int, str]] = []
    for i, (line, unit) in enumerate(units):
        if _AUDIENCE_HEADER.match(unit):
            continue
        if not _EDIT_VERB.search(_NEGATED_VERB.sub("", unit)):
            continue
        window = [unit]
        if i > 0:
            window.append(units[i - 1][1])
        if i + 1 < len(units):
            window.append(units[i + 1][1])
        if any(_IN_TREE_PATH.search(w) for w in window):
            flagged.append((line, unit))
    return flagged


def census(files: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for rel in files:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line, unit in flag_units(extract_units(text)):
            out.append(Finding(rel, line, unit))
    return out


def _allowed(finding: Finding) -> bool:
    return any(
        finding.source == file and fragment in finding.unit for file, fragment, _ in ALLOWLIST
    )


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------


def test_census_file_set_is_complete() -> None:
    """Every required member exists and is swept — a rename or deletion of a
    census-covered doc must be conscious, not silent."""
    files = set(census_files())
    missing = [rel for rel in REQUIRED_MEMBERS if rel not in files]
    assert not missing, (
        "census no longer covers required user-facing docs (renamed or "
        f"deleted? update REQUIRED_MEMBERS deliberately): {missing}"
    )


def test_user_docs_never_instruct_in_tree_edits() -> None:
    findings = [f for f in census(census_files()) if not _allowed(f)]
    assert not findings, (
        "user-facing docs instruct editing in-tree framework files "
        "(reword to the external-path story — manifests anywhere on disk, "
        "SIDERIUS_GENERATED_LIBRARY_DIR, CLI inputs — or allowlist with a "
        "quoted reason):\n  " + "\n  ".join(f"{f.source}:{f.line}: {f.unit}" for f in findings)
    )


def test_allowlist_entries_are_not_stale() -> None:
    """Every allowlist entry still matches a currently flagged unit in its
    file; an entry that matches nothing is dead weight hiding future
    violations behind an unreviewed fragment."""
    findings = census(census_files())
    stale = [
        (file, fragment)
        for file, fragment, _ in ALLOWLIST
        if not any(f.source == file and fragment in f.unit for f in findings)
    ]
    assert not stale, f"allowlist entries no longer match any flagged unit: {stale}"


# ---------------------------------------------------------------------------
# Oracle: the matcher sees what it claims to, and skips what it claims to
# ---------------------------------------------------------------------------


class TestMatcherOracle:
    def test_verb_and_path_in_one_sentence_is_flagged(self) -> None:
        text = "Something else.\n\nEdit `configs/health_checks.yaml` to change the roster.\n"
        assert [u for _, u in flag_units(extract_units(text))] == [
            "Edit `configs/health_checks.yaml` to change the roster."
        ]

    def test_adjacent_sentence_window_is_flagged(self) -> None:
        text = (
            "The policy lives in `configs/health_checks.yaml`. "
            "Edit it to make failures observational.\n"
        )
        flagged = [u for _, u in flag_units(extract_units(text))]
        assert "Edit it to make failures observational." in flagged

    def test_fenced_blocks_are_skipped(self) -> None:
        text = "```bash\n$EDITOR configs/health_checks.yaml  # edit it\n```\nplain prose.\n"
        assert flag_units(extract_units(text)) == []

    def test_inflected_verbs_do_not_match(self) -> None:
        text = (
            "The composed result is written beside `configs/health_checks.yaml`; "
            "it changed owners and was edited in Step 08b, adding nothing.\n"
        )
        assert flag_units(extract_units(text)) == []

    def test_external_paths_do_not_match(self) -> None:
        text = (
            "Edit your task health config anywhere on disk, or update "
            "`~/.siderius/generated_library` via SIDERIUS_GENERATED_LIBRARY_DIR.\n"
        )
        assert flag_units(extract_units(text)) == []

    def test_table_cells_are_units(self) -> None:
        text = "| goal | do |\n|---|---|\n| stricter check | edit `configs/health_checks.yaml` |\n"
        flagged = [u for _, u in flag_units(extract_units(text))]
        assert flagged == ["edit `configs/health_checks.yaml`"]
