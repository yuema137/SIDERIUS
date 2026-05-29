# agent/skills/paper_resolver_skill/arxiv_source.py
"""Tier-1 arXiv source parser for paper_resolver_skill.

Public entry point: ``parse_arxiv_source(tarball_bytes) -> str | None``.

Takes the bytes of an arXiv ``.tar.gz`` source bundle (downloaded by the
wrapper from ``https://arxiv.org/src/{id}``) and produces a clean Markdown
string suitable for the compression prompt's ``arxiv_source`` instruction
block.

Returns ``None`` on any unrecoverable failure (corrupt tarball, no main
``.tex``, parse error, empty body); the caller falls through to the next
tier in the cascade (Tier-2 marker if available, else Tier-3 pdfplumber).

Design rationale, key trade-offs, and the field/macro decisions are
recorded in ``docs/external_agents_for_proposer.md`` §5a and in the
Commit 2c-b implementation thread. In particular:

  - **Library**: ``pylatexenc>=2.10,<3`` (AST parser, pure Python, MIT).
    Probed against the v2.10 API; v3.x has a partial rewrite that may
    break these assumptions, so the pin caps at ``<3``.
  - **\\newcommand / \\def**: definitions are *collected* and emitted as a
    top-of-body ``$$\\newcommand…$$`` block; equations preserve the
    original macro usage. We do not expand macros (TeX is Turing-complete;
    partial expansion is worse than no expansion). The compression LLM
    resolves them.
  - **algorithm / algorithmic envs**: emitted as fenced ``algorithm``
    code blocks with ``\\State``, ``\\For`` etc. preserved raw. DeepSeek
    handles the formatting; lossy semi-conversion would discard fidelity.
  - **Multi-file projects**: ``\\input`` / ``\\include`` / ``\\subfile``
    are flattened pre-AST (recursive substitution within the tarball,
    depth cap 10, missing files leave a ``% [missing input]`` marker).
  - **Verbatim preservation**: math envs / inline math / unrecognised
    macros are sliced from the original source via ``(node.pos, node.len)``
    rather than reconstructed from the AST — this avoids any node-by-node
    re-serialisation logic and is exact by construction.
"""

from __future__ import annotations

import logging
import re
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Heavy import lives behind a guard so test fixtures can monkey-patch.
    from pylatexenc import latexwalker as _lw  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LaTeX-domain constants — which env names get which output treatment.
# ---------------------------------------------------------------------------

# Math environments: emit body verbatim wrapped in ``$$ … $$``.
_MATH_ENVS = frozenset(
    {
        "equation",
        "equation*",
        "align",
        "align*",
        "gather",
        "gather*",
        "multline",
        "multline*",
        "eqnarray",
        "eqnarray*",
        "displaymath",
    }
)

# Algorithm / listing environments: emit body verbatim inside a fenced
# ``algorithm`` code block. Macros inside (\State, \For, \EndFor) are
# preserved raw — DeepSeek handles them.
_ALGORITHM_ENVS = frozenset({"algorithm", "algorithm*", "algorithmic", "algorithm2e", "lstlisting"})

# Figure / table environments: drop the visual content, keep only the
# ``\caption{…}`` text as inline italic prose.
_FIGURE_ENVS = frozenset({"figure", "figure*", "table", "table*", "subfigure"})

# Macro names that define a macro (collected into the macros preamble; the
# definition does NOT appear in the body).
_MACRO_DEFINING = frozenset(
    {
        "newcommand",
        "renewcommand",
        "providecommand",
        "def",
        "edef",
        "gdef",
        "xdef",
        "DeclareMathOperator",
        "DeclareMathOperator*",
    }
)

# Sectioning macros → Markdown heading level.
_SECTION_LEVELS = {
    "chapter": "## ",
    "section": "## ",
    "subsection": "### ",
    "subsubsection": "#### ",
    "paragraph": "##### ",
    "subparagraph": "###### ",
}

# Macros to silently drop (no body emission) — they're metadata, layout, refs,
# or preamble commands, not content. Covers the macros that appear above
# ``\begin{document}`` plus the common refs/layout commands inside the body.
_DROP_MACROS = frozenset(
    {
        # Refs / labels / cites — metadata, not content.
        "label",
        "ref",
        "eqref",
        "pageref",
        "autoref",
        "nameref",
        "cite",
        "citep",
        "citet",
        "citeauthor",
        "citeyear",
        "bibliographystyle",
        "bibliography",
        # Document setup (preamble — appears before \begin{document}).
        "documentclass",
        "documentstyle",
        "LoadClass",
        "ProvidesPackage",
        "usepackage",
        "RequirePackage",
        "title",
        "author",
        "date",
        "address",
        "thanks",
        "affil",
        "email",
        "and",  # \author{X \and Y}
        "makeatletter",
        "makeatother",
        "DeclareUnicodeCharacter",
        # Layout / spacing — visual noise for the compression LLM.
        "vspace",
        "hspace",
        "noindent",
        "smallskip",
        "medskip",
        "bigskip",
        "newpage",
        "clearpage",
        "linebreak",
        "pagebreak",
        "maketitle",
        "tableofcontents",
        "listoffigures",
        "listoftables",
        "pagestyle",
        "thispagestyle",
        "fancyhf",
        "fancyhead",
        "fancyfoot",
        # Counters / lengths — preamble noise.
        "setlength",
        "setcounter",
        "settoheight",
        "newcounter",
        "newlength",
    }
)

# Pre-AST regex for \input/\include/\subfile. The body of these commands is
# a single brace-balanced path — for arXiv submissions it's always a simple
# filename, so a tolerant pattern is fine. Comments are stripped first to
# avoid following \input{...} that appears inside a comment.
_INCLUDE_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
_COMMENT_LINE_RE = re.compile(r"(?<!\\)%[^\n]*")

# Cap on recursive \input/\include depth (defends against pathological loops).
_MAX_INCLUDE_DEPTH = 10

# Sanity cap on input size to pylatexenc — protects against pathological
# inputs taking unbounded time. arXiv source tarballs are routinely <1MB
# of .tex; 5MB is a generous ceiling.
_MAX_FLATTENED_CHARS = 5_000_000


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_arxiv_source(tarball_bytes: bytes) -> str | None:
    """Parse an arXiv ``.tar.gz`` source bundle into a clean Markdown string.

    Args:
        tarball_bytes: Raw bytes of the source tarball as returned by
            ``arxiv.org/src/{id}``.

    Returns:
        Cleaned Markdown body suitable for the Tier-1 compression prompt, or
        ``None`` on any unrecoverable failure — caller falls through to the
        next extraction tier. Failure cases:
          - Tarball corrupt / not gzip;
          - No main ``.tex`` file (file with ``\\documentclass`` AND
            ``\\begin{document}``);
          - LaTeX walker raises (unrecoverable parse error);
          - Empty body after parsing (nothing useful extracted).
    """
    tempdir = _extract_tarball(tarball_bytes)
    if tempdir is None:
        return None
    try:
        main = _find_main_tex(tempdir)
        if main is None:
            logger.debug("arxiv_source: no main .tex with \\documentclass + \\begin{document}")
            return None

        flattened = _preflatten(main, base_dir=main.parent, visited=set(), depth=0)
        if len(flattened) > _MAX_FLATTENED_CHARS:
            logger.warning(
                "arxiv_source: flattened source %d chars > cap %d; truncating",
                len(flattened),
                _MAX_FLATTENED_CHARS,
            )
            flattened = flattened[:_MAX_FLATTENED_CHARS]

        markdown = _walk_and_emit(flattened)
        if not markdown or not markdown.strip():
            logger.debug("arxiv_source: empty body after walk")
            return None
        return markdown
    finally:
        _cleanup_tempdir(tempdir)


# ---------------------------------------------------------------------------
# Tarball extraction
# ---------------------------------------------------------------------------


def _extract_tarball(tarball_bytes: bytes) -> Path | None:
    """Untar ``tarball_bytes`` to a fresh tempdir; return its path or None.

    Uses ``filter='data'`` (Python 3.12+ safe-extraction) to refuse
    absolute paths, symlinks escaping the dir, and special files. We trust
    arXiv's tarballs, but defence-in-depth is cheap.
    """
    try:
        tmpdir = Path(tempfile.mkdtemp(prefix="arxiv_src_"))
        with tarfile.open(fileobj=BytesIO(tarball_bytes), mode="r:gz") as tar:
            try:
                tar.extractall(path=tmpdir, filter="data")
            except TypeError:
                # Python <3.12: ``filter`` kwarg not supported — fall back to
                # plain extractall. The deprecation warning is acceptable.
                tar.extractall(path=tmpdir)
        return tmpdir
    except (tarfile.ReadError, tarfile.CompressionError, OSError) as e:
        logger.debug("arxiv_source: tarball extraction failed: %s", e)
        return None


def _cleanup_tempdir(tempdir: Path) -> None:
    """Best-effort tempdir cleanup; never raises."""
    try:
        import shutil

        shutil.rmtree(tempdir, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main .tex detection + multi-file pre-flatten
# ---------------------------------------------------------------------------


def _find_main_tex(tempdir: Path) -> Path | None:
    """Locate the main ``.tex`` file in the tarball.

    Heuristic: any file containing both ``\\documentclass`` and
    ``\\begin{document}``. If multiple match, pick the longest (by char
    count) — submissions sometimes ship an unused ``supplement.tex`` that
    also has a documentclass.
    """
    candidates: list[tuple[Path, int]] = []
    for tex in tempdir.rglob("*.tex"):
        try:
            content = tex.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\\documentclass" in content and "\\begin{document}" in content:
            candidates.append((tex, len(content)))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[1])
    return candidates[0][0]


def _preflatten(tex_path: Path, base_dir: Path, visited: set[Path], depth: int) -> str:
    """Read ``tex_path`` and recursively substitute ``\\input``/``\\include``/
    ``\\subfile`` references with their file contents.

    Done as a string substitution BEFORE the AST parse so the walker sees a
    single self-contained source. Comments are pre-stripped (one-line ``%``)
    to avoid following ``\\input{...}`` directives that are inside a comment.
    """
    if depth > _MAX_INCLUDE_DEPTH:
        return f"% [pre-flatten depth cap hit at {tex_path.name}]\n"

    real = tex_path.resolve()
    if real in visited:
        return f"% [skipped duplicate include: {tex_path.name}]\n"
    visited.add(real)

    try:
        source = tex_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("arxiv_source: failed to read %s: %s", tex_path, e)
        return f"% [missing input: {tex_path.name}]\n"

    # Strip line comments before scanning for includes (so a commented-out
    # \input{...} is not followed). This is line-local; full-line ``%`` only.
    source_no_comments = _COMMENT_LINE_RE.sub("", source)

    def _expand(match: re.Match[str]) -> str:
        included = match.group(1).strip()
        for candidate in [
            tex_path.parent / included,
            tex_path.parent / f"{included}.tex",
            base_dir / included,
            base_dir / f"{included}.tex",
        ]:
            if candidate.is_file():
                return _preflatten(candidate, base_dir, visited, depth + 1)
        logger.debug("arxiv_source: missing include %r (from %s)", included, tex_path.name)
        return f"% [missing input: {included}]"

    return _INCLUDE_RE.sub(_expand, source_no_comments)


# ---------------------------------------------------------------------------
# AST walk + per-node emit
# ---------------------------------------------------------------------------


def _build_latex_context(lw):
    r"""Return a LatexContextDb with our additional macro specs registered.

    pylatexenc's default DB knows ``\section``, ``\subsection``, ``\input``,
    ``\newcommand`` (etc.) but not ``\caption`` — without registration,
    ``\caption{X}`` parses as a 0-arg macro plus a separate orphan
    ``LatexGroupNode``, and ``_macro_body_text`` returns ``""``. Registering
    ``\caption`` (and a few peers) here makes its body discoverable via the
    normal ``node.nodeargd.argnlist`` path.
    """
    from pylatexenc.macrospec import std_macro

    db = lw.get_default_latex_context_db()
    db.add_context_category(
        "siderius_lit_review",
        macros=[
            std_macro("caption", True, 1),  # \caption[short]{long}
            std_macro("subcaption", True, 1),
        ],
    )
    return db


def _walk_and_emit(source: str) -> str | None:
    """Parse ``source`` via pylatexenc and walk the AST, returning Markdown.

    Returns ``None`` on parse error or empty body — caller treats as Tier-1
    failure and falls through.
    """
    # Heavy import inside the function so the module is importable without
    # the dep installed (tests that don't exercise this path don't need it).
    try:
        from pylatexenc import latexwalker as lw
    except ImportError:
        logger.debug("arxiv_source: pylatexenc not installed; Tier-1 unavailable")
        return None

    try:
        walker = lw.LatexWalker(source, latex_context=_build_latex_context(lw))
        nodes, _, _ = walker.get_latex_nodes()
    except lw.LatexWalkerError as e:
        logger.debug("arxiv_source: LatexWalker raised: %s", e)
        return None

    if not nodes:
        return None

    macros: list[str] = []
    body: list[str] = []
    for node in nodes:
        _emit(node, source, body, macros, lw)

    body_text = _normalise_whitespace("".join(body))
    if not body_text.strip():
        return None

    if macros:
        macros_block = "## Macros\n\n$$\n" + "\n".join(macros) + "\n$$\n\n"
        return macros_block + body_text
    return body_text


def _emit(node, source: str, out: list[str], macros: list[str], lw) -> None:
    """Dispatch one AST node into either ``out`` (body) or ``macros`` (preamble).

    Recursive — environments and groups walk their children.
    """
    # --- Environments -----------------------------------------------------
    if isinstance(node, lw.LatexEnvironmentNode):
        name = node.envname
        if name in _MATH_ENVS:
            body = _slice_env_body(node, source)
            out.append(f"\n\n$$\n{body}\n$$\n\n")
            return
        if name in _ALGORITHM_ENVS:
            body = _slice_env_body(node, source)
            out.append(f"\n\n```algorithm\n{body}\n```\n\n")
            return
        if name in _FIGURE_ENVS:
            # Per Q2 of the design: math / algorithm envs nested inside a
            # figure are extracted to top-level body (so the equations list
            # captures them); the figure's own caption is inlined as italic
            # prose; everything else (\includegraphics, sub-positioning,
            # \centering, etc.) is dropped.
            for ch in node.nodelist:
                if isinstance(ch, lw.LatexEnvironmentNode):
                    if ch.envname in _MATH_ENVS or ch.envname in _ALGORITHM_ENVS:
                        _emit(ch, source, out, macros, lw)
                    elif ch.envname in _FIGURE_ENVS:
                        # Nested figure (e.g., subfigure) — recurse for its caption.
                        _emit(ch, source, out, macros, lw)
                elif isinstance(ch, lw.LatexMacroNode) and ch.macroname == "caption":
                    caption = _macro_body_text(ch, source)
                    if caption:
                        out.append(f"\n\n*Figure: {caption}*\n\n")
            return
        if name == "document":
            for ch in node.nodelist:
                _emit(ch, source, out, macros, lw)
            return
        # Other envs (abstract, theorem, itemize, ...): recurse into body.
        for ch in node.nodelist:
            _emit(ch, source, out, macros, lw)
        return

    # --- Macros -----------------------------------------------------------
    if isinstance(node, lw.LatexMacroNode):
        name = node.macroname
        if name in _MACRO_DEFINING:
            macros.append(source[node.pos : node.pos + node.len])
            return
        if name in _SECTION_LEVELS:
            title = _macro_body_text(node, source)
            out.append(f"\n\n{_SECTION_LEVELS[name]}{title}\n\n")
            return
        if name in _DROP_MACROS:
            return
        # Unknown macros: pass through verbatim — the consumer LLM resolves them.
        out.append(source[node.pos : node.pos + node.len])
        return

    # --- Math nodes -------------------------------------------------------
    if isinstance(node, lw.LatexMathNode):
        raw = source[node.pos : node.pos + node.len]
        delims = node.delimiters
        if delims == ("\\(", "\\)"):
            out.append("$" + raw[2:-2] + "$")
        elif delims == ("\\[", "\\]"):
            out.append("\n\n$$\n" + raw[2:-2].strip() + "\n$$\n\n")
        else:
            # ``$..$`` or ``$$..$$`` — preserve as-is (both are valid Markdown).
            out.append(raw)
        return

    # --- Group ------------------------------------------------------------
    if isinstance(node, lw.LatexGroupNode):
        for ch in node.nodelist:
            _emit(ch, source, out, macros, lw)
        return

    # --- Comments ---------------------------------------------------------
    if isinstance(node, lw.LatexCommentNode):
        return

    # --- Specials (& ~ ^ _ outside math, etc.) ----------------------------
    if hasattr(node, "specials_chars"):
        # LatexSpecialsNode — pass through verbatim.
        out.append(source[node.pos : node.pos + node.len])
        return

    # --- Plain text -------------------------------------------------------
    if isinstance(node, lw.LatexCharsNode):
        out.append(node.chars)
        return

    # --- Anything else: best-effort verbatim slice ------------------------
    if hasattr(node, "pos") and hasattr(node, "len"):
        out.append(source[node.pos : node.pos + node.len])


# ---------------------------------------------------------------------------
# Source-slice helpers
# ---------------------------------------------------------------------------


def _slice_env_body(node, source: str) -> str:
    r"""Return the body of an environment node verbatim (no \begin/\end).

    Strategy: slice from the first child's ``pos`` to the last child's
    ``pos + len``. Trailing whitespace is stripped — the caller wraps the
    body in $$ or fenced-code-block markers and the strip keeps the fences
    flush against content.

    Returns ``""`` when the env has no children (empty body — caller still
    emits the wrapping block; we don't drop the env entirely).
    """
    if not node.nodelist:
        return ""
    first = node.nodelist[0]
    last = node.nodelist[-1]
    if not (hasattr(first, "pos") and hasattr(last, "pos") and hasattr(last, "len")):
        return ""
    return source[first.pos : last.pos + last.len].strip()


def _macro_body_text(node, source: str) -> str:
    """Extract the textual body of a macro (e.g. ``\\section{Title}`` → ``Title``).

    Picks the **last** non-None ``LatexGroupNode`` in ``node.nodeargd.argnlist``
    — for sectioning / caption / labelled macros, that's the body (earlier
    args are stars or short-titles or `[n_args]` slots). Returns ``""`` when
    the macro has no group arg.
    """
    if not (node.nodeargd and node.nodeargd.argnlist):
        return ""
    for arg in reversed(node.nodeargd.argnlist):
        if arg is None:
            continue
        # Late-bound import: this function is only called from _emit, which
        # already has lw available, but keeping the helper independent is
        # cleaner for unit testing.
        from pylatexenc import latexwalker as lw

        if isinstance(arg, lw.LatexGroupNode):
            if not arg.nodelist:
                return ""
            first = arg.nodelist[0]
            last = arg.nodelist[-1]
            if hasattr(first, "pos") and hasattr(last, "pos") and hasattr(last, "len"):
                return source[first.pos : last.pos + last.len].strip()
    return ""


# ---------------------------------------------------------------------------
# Whitespace tidy-up
# ---------------------------------------------------------------------------


def _normalise_whitespace(text: str) -> str:
    """Collapse runs of >2 blank lines, trim trailing whitespace per line."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
