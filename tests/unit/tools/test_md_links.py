"""Relative Markdown links must resolve inside the repository (issue #265).

The defect only this test catches: a `.md` file links to a sibling document,
report or design plan that was never published, was deleted, or was renamed —
and nothing in CI reads Markdown links, so the dangling reference survives
every push. On master at `c991d6f6` six such links existed
(`docs/design/m7_…:271,272`, `m8_…:182`, `paper_and_collapse_…:196`,
`reports/health_metrics_scan.md:13`, `reports/v17_20260717.md:8`), all
pointing at targets that `git log --all --diff-filter=A` shows NEVER landed.

How it fails when the behaviour breaks: re-break any one of those links (or
add a new one) and `test_every_relative_markdown_link_resolves` lists it as
`path:line -> target`. `TestExtractorSeesWhatItClaims` is the oracle for the
extractor itself — if the regexes or the fenced-block skipper silently stop
matching, the repository sweep would stay green for the wrong reason, and
those synthetic cases go RED instead.

Scope, deliberately narrow (stdlib only, no link-tool dependency):

* files: every `*.md` **tracked by git** (falls back to a filesystem walk
  outside a checkout), excluding `.venv`, `node_modules`, `agent_generated`
  and `.git`;
* links: inline `[text](target)`, images `![alt](target)` and reference
  definitions `[id]: target`; fenced code blocks and inline code spans are
  skipped;
* targets: scheme-less only (`http:`, `mailto:` … are not this test's
  business); `path#anchor` is split and only the path is checked; a bare
  `#anchor` is skipped; a leading `/` is repository-root-relative.

A target resolves when it is a tracked file, or a directory containing at
least one tracked file — the same definition CI's checkout sees, so a
gitignored local file cannot make a link look valid.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

EXCLUDED_DIRS = frozenset({".venv", "node_modules", "agent_generated", ".git"})

#: Files whose links were broken on master at `c991d6f6` and were repaired by
#: this PR. Listed literally so (a) the repository sweep provably covers them
#: and (b) the CI selector derives an edge from each to this module.
REGRESSION_ANCHORS: tuple[str, ...] = (
    "docs/design/m7_loss_implementor_contract_execution_plan.md",
    "docs/design/m8_gate_coverage_and_diversity_metrics_execution_plan.md",
    "docs/design/paper_and_collapse_reference_baselines.md",
    "reports/health_metrics_scan.md",
    "reports/v17_20260717.md",
)

_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
#: `[text](target)` and `![alt](target)`; the target may be `<wrapped>` and
#: may carry a `"title"`. Nested brackets in the text are not supported —
#: they are not used in this repository's docs.
_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class MarkdownLink:
    source: str  # repo-relative posix path of the .md file
    line: int  # 1-based
    target: str  # the raw target as written


@dataclass(frozen=True)
class BrokenLink:
    link: MarkdownLink
    resolved: str  # repo-relative posix path that did not resolve


def _strip_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1]
    return raw.strip()


def extract_links(text: str, source: str) -> list[MarkdownLink]:
    """Every link target written in `text`, with fenced blocks and inline
    code removed first. Pure, so the oracle tests can drive it directly."""
    out: list[MarkdownLink] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        visible = _INLINE_CODE.sub("", line)
        ref = _REF_DEF.match(visible)
        if ref:
            out.append(MarkdownLink(source, lineno, _strip_target(ref.group(1))))
            continue
        for m in _INLINE_LINK.finditer(visible):
            out.append(MarkdownLink(source, lineno, _strip_target(m.group(1))))
    return out


def is_relative_target(target: str) -> bool:
    """Scheme-less, non-empty, and not a same-document anchor."""
    if not target or target.startswith("#"):
        return False
    return not _SCHEME.match(target)


def resolve_target(source: str, target: str) -> str:
    """Repo-relative posix path the link points at (anchor removed)."""
    path_part = target.split("#", 1)[0]
    if path_part.startswith("/"):
        return PurePosixPath(path_part.lstrip("/")).as_posix()
    base = PurePosixPath(source).parent
    joined = base / path_part
    # PurePosixPath keeps `..`; normalise it by hand so `a/../b` -> `b`.
    parts: list[str] = []
    for piece in joined.parts:
        if piece == "..":
            if parts:
                parts.pop()
            else:
                # Escaped above the repository root: keep the `..` so it
                # cannot accidentally match a real path.
                parts.append("..")
        elif piece not in ("", "."):
            parts.append(piece)
    return "/".join(parts)


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


def _excluded(rel: str) -> bool:
    return any(part in EXCLUDED_DIRS for part in PurePosixPath(rel).parts)


def markdown_files(tracked: frozenset[str] | None) -> list[str]:
    if tracked is not None:
        return sorted(p for p in tracked if p.endswith(".md") and not _excluded(p))
    out: list[str] = []
    for p in REPO_ROOT.rglob("*.md"):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if not _excluded(rel):
            out.append(rel)
    return sorted(out)


def _exists(resolved: str, tracked: frozenset[str] | None) -> bool:
    if tracked is None:
        return (REPO_ROOT / resolved).exists()
    if resolved in tracked:
        return True
    prefix = resolved.rstrip("/") + "/"
    return resolved == "" or any(p.startswith(prefix) for p in tracked)


def broken_links(files: list[str], tracked: frozenset[str] | None) -> list[BrokenLink]:
    out: list[BrokenLink] = []
    for rel in files:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for link in extract_links(text, rel):
            if not is_relative_target(link.target):
                continue
            resolved = resolve_target(rel, link.target)
            if not _exists(resolved, tracked):
                out.append(BrokenLink(link, resolved))
    return out


# ---------------------------------------------------------------------------
# The repository sweep
# ---------------------------------------------------------------------------


def test_every_relative_markdown_link_resolves() -> None:
    tracked = _tracked_files()
    files = markdown_files(tracked)
    missing_anchor = [a for a in REGRESSION_ANCHORS if a not in files]
    assert not missing_anchor, (
        "the sweep no longer covers a file whose links this PR repaired — update "
        f"REGRESSION_ANCHORS if the file was deliberately moved: {missing_anchor}"
    )
    broken = broken_links(files, tracked)
    assert not broken, "broken relative Markdown links (source:line -> target):\n  " + "\n  ".join(
        f"{b.link.source}:{b.link.line} -> {b.link.target}  (resolved {b.resolved!r})"
        for b in broken
    )


# ---------------------------------------------------------------------------
# Oracle: the extractor sees what it claims to, and skips what it claims to
# ---------------------------------------------------------------------------


class TestExtractorSeesWhatItClaims:
    def test_inline_image_and_reference_links_are_all_extracted(self) -> None:
        text = (
            'see [a](one.md) and ![img](figs/two.svg "title")\n'
            "[ref]: <three with space.md>\n"
            "[anchored](four.md#section)\n"
        )
        got = [(link.line, link.target) for link in extract_links(text, "docs/x.md")]
        assert got == [
            (1, "one.md"),
            (1, "figs/two.svg"),
            (2, "three with space.md"),
            (3, "four.md#section"),
        ]

    def test_fenced_blocks_and_inline_code_are_skipped(self) -> None:
        text = "```\n[in fence](nope.md)\n```\ntext `[in code](nope.md)` more\n[real](yes.md)\n"
        got = [link.target for link in extract_links(text, "docs/x.md")]
        assert got == ["yes.md"]

    @pytest.mark.parametrize(
        "target, relative",
        [
            ("https://example.org/x.md", False),
            ("mailto:someone@example.org", False),
            ("#same-document", False),
            ("", False),
            ("../guides/operating-a-run.md", True),
            ("/docs/README.md", True),
        ],
    )
    def test_only_scheme_less_targets_are_checked(self, target: str, relative: bool) -> None:
        assert is_relative_target(target) is relative

    def test_resolution_is_relative_to_the_source_and_drops_the_anchor(self) -> None:
        assert resolve_target("docs/design/a.md", "../guides/b.md#h") == "docs/guides/b.md"
        assert resolve_target("docs/design/a.md", "/reports/c.md") == "reports/c.md"
        assert resolve_target("docs/a.md", "../../escaped.md") == "../escaped.md"

    def test_a_broken_link_in_a_synthetic_tree_is_reported(self, tmp_path: Path) -> None:
        """The end-to-end oracle: a file linking to a target that does not
        exist is reported with its line number; the same link inside a
        fence is not. Drives the same functions the sweep uses, against a
        filesystem tree (`tracked=None`), so it needs no git."""
        doc = tmp_path / "doc.md"
        doc.write_text("ok [x](exists.md)\n```\n[y](missing.md)\n```\nbad [z](missing.md)\n")
        (tmp_path / "exists.md").write_text("")
        text = doc.read_text()
        links = [link for link in extract_links(text, "doc.md") if is_relative_target(link.target)]
        reported = [
            (link.line, link.target)
            for link in links
            if not (tmp_path / resolve_target("doc.md", link.target)).exists()
        ]
        assert reported == [(5, "missing.md")]
