"""Unit tests for agent/skills/paper_resolver_skill/arxiv_source.py.

Tier-1 arXiv source parser — pure, no network, no I/O beyond in-memory
tarballs. Covers the design promises in docs/external_agents_for_proposer.md
§5a and the Commit 2c-b implementation thread:

  - pylatexenc-based AST walk, verbatim slicing via (pos, len).
  - \\newcommand collected into a top-of-body Macros block.
  - Math envs (equation / align / ...) → $$...$$ blocks.
  - Algorithm envs → fenced ``algorithm`` blocks with raw \\State / \\For.
  - Figure envs → caption text inlined; nested math/algorithm extracted.
  - Multi-file: \\input / \\include / \\subfile recursively flattened.
  - Failure modes (no main .tex, corrupt tarball, malformed LaTeX, empty
    body, recursion depth cap) all return None for clean cascade.
"""

from __future__ import annotations

import io
import tarfile

import pytest

from agent.skills.paper_resolver_skill.arxiv_source import (
    _MAX_INCLUDE_DEPTH,
    _preflatten,
    _walk_and_emit,
    parse_arxiv_source,
)

# ---------------------------------------------------------------------------
# In-memory tarball helper
# ---------------------------------------------------------------------------


def _make_tarball(files: dict[str, str]) -> bytes:
    """Build an in-memory .tar.gz from {path: content} dict."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


_MIN_DOC = r"""\documentclass{article}
\begin{document}
\section{Hi}
Body text.
\end{document}
"""


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestParseHappyPath:
    def test_minimal_tarball_parses_to_markdown(self):
        out = parse_arxiv_source(_make_tarball({"main.tex": _MIN_DOC}))
        assert out is not None
        assert "## Hi" in out
        assert "Body text." in out
        # Preamble noise must NOT leak into body.
        assert "\\documentclass" not in out

    def test_equation_emitted_as_dollar_dollar_block(self):
        tex = r"""\documentclass{article}
\begin{document}
\begin{equation}
    a = b + c
\end{equation}
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        assert "$$" in out
        assert "a = b + c" in out

    def test_equation_star_and_align_extracted(self):
        # Math env variants — equation* / align / align* / gather all qualify.
        tex = r"""\documentclass{article}
\begin{document}
\begin{equation*}
    x = 1
\end{equation*}
\begin{align*}
    a &= b \\ c &= d
\end{align*}
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        assert "x = 1" in out
        assert "a &= b" in out
        # Two display-math blocks
        assert out.count("$$") >= 4

    def test_algorithm_emits_fenced_block_with_raw_state_for(self):
        # User decision: preserve \State / \For RAW — DeepSeek handles them.
        tex = r"""\documentclass{article}
\begin{document}
\begin{algorithm}
\caption{Train step}
\begin{algorithmic}[1]
\For{batch in data}
    \State $\theta \gets \theta - 1$
\EndFor
\end{algorithmic}
\end{algorithm}
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        assert "```algorithm" in out
        assert "\\State" in out  # raw, NOT semi-converted
        assert "\\For" in out
        assert "\\EndFor" in out


# ---------------------------------------------------------------------------
# Macros
# ---------------------------------------------------------------------------


class TestMacros:
    def test_newcommand_collected_into_top_of_body_block(self):
        tex = r"""\documentclass{article}
\newcommand{\R}{\mathbb{R}}
\newcommand{\norm}[1]{\left\|#1\right\|}
\begin{document}
$\R^n$ and $\norm{x}$.
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        # Macros block at the top
        macros_idx = out.find("## Macros")
        body_idx = out.find("$\\R^n$")
        assert macros_idx != -1
        assert body_idx > macros_idx  # macros come before body
        # Both definitions captured verbatim
        assert r"\newcommand{\R}{\mathbb{R}}" in out
        assert r"\newcommand{\norm}[1]{\left\|#1\right\|}" in out
        # Usage preserved in body (NOT expanded)
        assert r"\R^n" in out

    def test_no_macros_means_no_macros_block(self):
        tex = r"""\documentclass{article}
\begin{document}
Plain text only.
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        assert "## Macros" not in out


# ---------------------------------------------------------------------------
# Multi-file projects
# ---------------------------------------------------------------------------


class TestMultiFile:
    def test_input_followed_within_tarball(self):
        main = r"""\documentclass{article}
\begin{document}
Before include.
\input{sections/method}
After include.
\end{document}
"""
        method = r"""\section{Method}
Method content here.
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": main, "sections/method.tex": method}))
        assert out is not None
        assert "Before include." in out
        assert "## Method" in out
        assert "Method content here." in out
        assert "After include." in out

    def test_include_extension_optional(self):
        # \input{foo} should resolve to foo.tex.
        main = r"""\documentclass{article}
\begin{document}
\input{intro}
\end{document}
"""
        intro = r"\section{Intro}" + "\n"
        out = parse_arxiv_source(_make_tarball({"main.tex": main, "intro.tex": intro}))
        assert out is not None
        assert "## Intro" in out

    def test_missing_input_does_not_break_parse(self):
        tex = r"""\documentclass{article}
\begin{document}
\input{sections/nonexistent}
Still here.
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        # The missing-input marker is a LaTeX comment — pylatexenc strips it.
        assert "Still here." in out

    def test_input_inside_comment_not_followed(self):
        main = r"""\documentclass{article}
\begin{document}
% \input{should-not-be-followed}
Body.
\end{document}
"""
        # No such file in the tarball; if the commented \input were followed,
        # we'd emit a "[missing input: …]" marker. We strip line comments
        # before scanning, so it must NOT be followed.
        out = parse_arxiv_source(_make_tarball({"main.tex": main}))
        assert out is not None
        assert "should-not-be-followed" not in out

    def test_recursion_depth_cap_does_not_loop(self):
        # \input loop: a.tex inputs b.tex which inputs a.tex.
        a = r"""\documentclass{article}
\begin{document}
A start.
\input{b}
A end.
\end{document}
"""
        b = r"""\input{a}
B body.
"""
        out = parse_arxiv_source(_make_tarball({"a.tex": a, "b.tex": b}))
        # Must terminate — and the run-away guard ("skipped duplicate include"
        # via the visited-set) hits before the depth cap. Either way the parse
        # completes and we get a real body.
        assert out is not None
        assert "A start." in out


# ---------------------------------------------------------------------------
# Nested envs (Q2 of the design)
# ---------------------------------------------------------------------------


class TestNestedEnvs:
    def test_equation_inside_figure_extracted_to_body(self):
        tex = r"""\documentclass{article}
\begin{document}
\begin{figure}
\caption{A figure with an equation}
\begin{equation}
    y = x^2
\end{equation}
\end{figure}
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        # Equation pulled out to top-level $$ block
        assert "y = x^2" in out
        assert "$$" in out
        # Figure caption inlined as italic prose
        assert "*Figure:" in out

    def test_figure_with_includegraphics_drops_visuals(self):
        tex = r"""\documentclass{article}
\begin{document}
\begin{figure}
\centering
\includegraphics{some/image.png}
\caption{Caption text only}
\end{figure}
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        assert "*Figure: Caption text only*" in out
        # \includegraphics and \centering must NOT leak through
        assert "includegraphics" not in out
        assert "image.png" not in out


# ---------------------------------------------------------------------------
# Inline / display math normalisation
# ---------------------------------------------------------------------------


class TestMathNodes:
    def test_paren_math_normalised_to_dollar(self):
        tex = r"""\documentclass{article}
\begin{document}
Hello \(x^2\) world.
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        assert "$x^2$" in out
        assert "\\(" not in out

    def test_bracket_display_normalised_to_dollar_dollar(self):
        tex = r"""\documentclass{article}
\begin{document}
Display: \[ a = b \]
\end{document}
"""
        out = parse_arxiv_source(_make_tarball({"main.tex": tex}))
        assert out is not None
        assert "$$" in out
        assert "a = b" in out
        assert "\\[" not in out


# ---------------------------------------------------------------------------
# Failure modes (clean cascade to next tier)
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_no_main_tex_returns_none(self):
        tarball = _make_tarball({"refs.bib": "@article{foo,}"})
        assert parse_arxiv_source(tarball) is None

    def test_corrupt_bytes_returns_none(self):
        assert parse_arxiv_source(b"not a tarball at all") is None

    def test_empty_document_returns_none(self):
        tex = r"""\documentclass{article}
\begin{document}
\end{document}
"""
        assert parse_arxiv_source(_make_tarball({"main.tex": tex})) is None

    def test_tex_without_documentclass_skipped(self):
        # File doesn't qualify as "main" without \documentclass.
        tex = r"""\section{Hi}
Body text.
"""
        assert parse_arxiv_source(_make_tarball({"orphan.tex": tex})) is None


# ---------------------------------------------------------------------------
# Direct _walk_and_emit + _preflatten coverage (bypasses tarball)
# ---------------------------------------------------------------------------


class TestInternals:
    def test_walk_and_emit_drops_top_level_preamble_macros(self):
        # \documentclass, \usepackage, \title, \author, \maketitle must
        # all be silently dropped by the body walker.
        src = r"""\documentclass{article}
\usepackage{amsmath}
\title{Foo}
\author{A. Author}
\begin{document}
\maketitle
\section{Body}
Hello.
\end{document}
"""
        out = _walk_and_emit(src)
        assert out is not None
        assert "## Body" in out
        for noise in ("\\documentclass", "\\usepackage", "\\title", "\\author", "\\maketitle"):
            assert noise not in out

    def test_max_include_depth_is_a_real_int(self):
        # Sanity: the cap exists and is finite.
        assert isinstance(_MAX_INCLUDE_DEPTH, int)
        assert _MAX_INCLUDE_DEPTH >= 5
