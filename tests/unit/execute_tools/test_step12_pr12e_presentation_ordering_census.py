"""Step 12 / PR-12e — the ordering census over the PRESENTATION layer.

Design: ``docs/design/generic_framework_upgrade/
step_12_external_extensibility_graduation/pr_12e_out_of_tree_graduation.md``
§V.14e (F-12e-UX-8), §V.13b item 1, §V.13e.

Why this module exists — a census blind to a file extension
-------------------------------------------------------------
Step 10 P2a built a scanner over every golden-metric ordering decision in
production and drove the surface to EMPTY. Its file set is::

    for directory in PRODUCTION_DIRS:
        files += sorted((REPO_ROOT / directory).rglob("*.py"))

``dashboard/`` **is** in ``PRODUCTION_DIRS``. ``app.js`` **is not a ``.py``
file.** So P2a genericized the dashboard's Python half — ``local_json.py``
routes its ordering through ``persisted_ranking`` — while the JavaScript half
kept ``Math.max(best, score)``, ``score > best`` and the axis label
``'Denoising score (higher = better)'``, and the census stayed green.

**This is the `F-12bc-9` shape verbatim**: a census whose FILE SET omits where
the code lives. It is the fourth time this project has hit the shape
(F-12bc-6 named a symbol, F-12bc-9 omitted a directory, F-P2b-4 anchored a
regex, F-12e-UX-8 omitted a file extension), which is why the extension is
part of the fix and not an optional extra: without it, the same gap reopens
the next time somebody adds a chart.

Why a SEPARATE module rather than a wider glob in the P2a scanner
------------------------------------------------------------------
The P2a scanner is an **AST** analysis — ``ast.parse`` over Python, with
one-hop alias tracking and scope-aware traversal. None of that applies to
JavaScript or HTML. Widening its glob would feed unparseable text to
``ast.parse``, and ``test_every_production_file_actually_parses`` would fail
by construction.

So the mechanism differs and the module does too — but the CLAIM is the same
and the two are joined: :func:`test_the_python_census_points_at_this_sibling`
fails if the P2a scanner stops naming this file, so a reader who finds
``rglob("*.py")`` there cannot conclude the presentation layer is unguarded.

What this scanner is, and is not
---------------------------------
It is a **precise textual** scanner over the presentation sources. It is NOT
a JavaScript parser and does not claim to be:

* comments and HTML comments are stripped before scanning, so prose ABOUT
  direction (including this repository's own explanatory comments) is not an
  offender;
* the ONE permitted JS direction authority — ``orderFor`` — has its body
  excluded, exactly as the P2a scanner excludes ``MetricOrder``'s own method
  calls, because otherwise the census would flag the fix;
* a score reached through a function call whose text carries no score token
  is not found. That is the same interprocedural limit the P2a scanner
  records for itself (F-P3-1), stated here so a green run is not read as a
  stronger claim than it makes.

**Introducing a new presentation-layer score carrier requires extending
:data:`PRESENTATION_SCORE_NAMES` in the same change.**
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit.execute_tools.test_step10_p2a_c0_ordering_scanner import (
    GOLDEN_SCORE_NAMES,
    PRODUCTION_DIRS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The file extensions the PYTHON census structurally cannot see. This tuple
#: is the whole point of the module: the Python scanner's ``rglob("*.py")``
#: and this one must together cover the production tree's executable and
#: rendered surfaces.
PRESENTATION_EXTENSIONS = (".js", ".html")

#: Names under which a golden score is carried in the presentation layer.
#:
#: The Python vocabulary plus the JS-local aliases the charts actually use.
#: ``score`` and ``best`` are here because that is what the frontend calls the
#: values it folds — the defect was ``Math.max(best, score)``, whose text
#: contains no ``denoising_score`` token at all, so a Python-vocabulary-only
#: scan would have been green for the wrong reason a second time.
PRESENTATION_SCORE_NAMES: tuple[str, ...] = (
    *GOLDEN_SCORE_NAMES,
    "score",
    "best",
    "bestData",
    "bestScore",
    "runningBest",
    "prevBest",
    "scoreYs",
)

#: The ONE JavaScript function permitted to turn a declared direction into a
#: comparison — the counterpart of ``execute_tools.metric_order.MetricOrder``.
#: Its body is excluded from the scan for the reason P2a excludes the
#: authority's own calls: a census that flags the fix is a census nobody keeps.
PRESENTATION_ORDER_AUTHORITY = "orderFor"

_SCORE_RE = re.compile(r"\b\w*(?:" + "|".join(PRESENTATION_SCORE_NAMES) + r")\w*\b")

#: An ordering operator. ``Math.max``/``Math.min`` and the four relational
#: operators. Equality (``==``, ``===``, ``!=``, ``!==``), arrows (``=>``) and
#: assignment are excluded by the lookarounds — a null check is not an order
#: decision.
_ORDER_RE = re.compile(r"Math\.(?:max|min)\s*\(|(?<![=!<>])(?:<=?|>=?)(?![=>])")

#: A HARDCODED direction claim in user-visible text. The label half of
#: F-12e-UX-3: ``'Denoising score (higher = better)'`` and index.html's
#: "Higher is better" were confidently wrong for a minimised metric, and a
#: fixed label is wrong in exactly the runs the direction work exists to
#: serve. A correct label is BUILT from the declared direction, so the words
#: arrive through interpolation and never appear as a literal.
_DIRECTION_CLAIM_RE = re.compile(r"(?:higher|lower)\s*(?:is|=)\s*better", re.IGNORECASE)

#: Shapes that mention a score name beside an operator but are NOT direction
#: decisions. Mandatory reasons, exactly as the P2a scanner requires.
PRESENTATION_EXCLUSIONS: dict[str, str] = {
    "loss": (
        "a training loss is lower-is-better BY DEFINITION of a loss and is "
        "unrelated to the golden metric; the same rule the P2a scanner "
        "applies on the Python side"
    ),
    "authority_body": (
        f"the body of `{PRESENTATION_ORDER_AUTHORITY}` IS the migration "
        "target — the one place a declared direction becomes a comparison. "
        "Flagging it would make the census report the fix as the defect"
    ),
    "comment": (
        "prose about direction is not a direction decision; this repository's "
        "own explanatory comments name the defect they replaced, and a "
        "scanner that could not tell a comment from code would be unkeepable"
    ),
    "markup": (
        "a `<` or `>` that delimits an HTML tag is not a comparison. Without "
        'this the census reports every `<div id="chart-score">` and every '
        "`<td>${fmt(r.denoising_score, 3)}</td>` as an ordering decision, and "
        "the three real sites drown in markup noise — the P2a scanner's "
        "'precision, not volume' rule, applied to a markup-bearing layer"
    ),
    "html_has_no_comparison": (
        "the ORDERING scan runs on .js only. HTML has no comparison "
        "semantics; its role in F-12e-UX-3 was the LABEL, which "
        "`_DIRECTION_CLAIM_RE` catches on both extensions independently"
    ),
}

#: A complete HTML tag. Attributes must be ``name="value"`` or ``name='value'``
#: so an expression like ``a <b && c> d`` cannot be mistaken for one.
_HTML_TAG_RE = re.compile(
    r"</?[A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z_:-]+=(?:\"[^\"]*\"|'[^']*'))*\s*/?>"
)

#: An HTML attribute assignment. Its presence marks the line as markup, which
#: is how a tag SPLIT ACROSS LINES is recognised — ``app.js`` builds its series
#: tags that way, so the closing ``>`` of a tag opened one line earlier has no
#: ``<`` to pair with and would otherwise read as a relational operator.
_HTML_ATTRIBUTE_RE = re.compile(r"[A-Za-z_:-]+=(?:\"|')")

_LOSS_RE = re.compile(r"\bloss\b|_loss\b|\bloss_", re.IGNORECASE)


@dataclass(frozen=True)
class PresentationFinding:
    """One flagged direction decision or hardcoded direction claim."""

    relative_path: str
    lineno: int
    source: str
    kind: str

    def __str__(self) -> str:
        return f"{self.relative_path}:{self.lineno} [{self.kind}]: {self.source}"


def _blank_comments(text: str) -> list[str]:
    """Replace comment content with spaces, preserving line numbering.

    Blanking rather than deleting keeps every reported line number equal to
    the real one in the file — a census whose line numbers are off by the
    comment count is a census nobody trusts twice.
    """
    lines = text.splitlines()
    out: list[str] = []
    in_block = False
    in_html = False
    for raw in lines:
        line = raw
        if in_block:
            end = line.find("*/")
            if end == -1:
                out.append("")
                continue
            line = " " * (end + 2) + line[end + 2 :]
            in_block = False
        if in_html:
            end = line.find("-->")
            if end == -1:
                out.append("")
                continue
            line = " " * (end + 3) + line[end + 3 :]
            in_html = False
        # Single-line block comments, then an unterminated block opener.
        line = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), line)
        line = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), line)
        if "/*" in line:
            line = line[: line.index("/*")]
            in_block = True
        if "<!--" in line:
            line = line[: line.index("<!--")]
            in_html = True
        # Line comments last, so a `//` inside an already-stripped block is
        # not mistaken for one.
        if "//" in line:
            line = line[: line.index("//")]
        out.append(line)
    return out


def _authority_lines(lines: list[str]) -> set[int]:
    """1-based line numbers inside the permitted direction authority's body.

    The body runs from ``function orderFor(`` to the next line that closes it
    at column zero. That is a style assumption, and it is a deliberate one:
    the alternative is a JavaScript parser, and a brace-depth counter would
    have to understand strings, regexes and template literals to be correct.
    :func:`test_the_authority_region_is_bounded_and_small` pins the region so
    the assumption cannot silently start swallowing the file.
    """
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if re.search(rf"function\s+{PRESENTATION_ORDER_AUTHORITY}\s*\(", line)
        ),
        None,
    )
    if start is None:
        return set()
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("}")), len(lines) - 1
    )
    return set(range(start + 1, end + 2))


def _strip_markup(line: str) -> str:
    """Blank the ``<``/``>`` that belong to HTML, keeping everything else.

    Two shapes, and the second is why the first is not enough: ``app.js``
    builds its series tags across several lines, so a closing ``>`` can sit on
    a line whose opening ``<`` was written above it. A line carrying an HTML
    attribute assignment is markup, and its stray angle brackets are treated
    as such.
    """
    line = _HTML_TAG_RE.sub(lambda m: " " * len(m.group(0)), line)
    if _HTML_ATTRIBUTE_RE.search(line):
        line = line.replace("<", " ").replace(">", " ")
    return line


def scan_presentation_source(text: str, relative_path: str) -> list[PresentationFinding]:
    """Flag ordering decisions and hardcoded direction claims in one file.

    The DIRECTION-CLAIM scan runs on every presentation source; the ORDERING
    scan runs on JavaScript only, because HTML has no comparison semantics and
    scanning it would report markup as ordering (see
    :data:`PRESENTATION_EXCLUSIONS`).
    """
    lines = _blank_comments(text)
    is_js = relative_path.endswith(".js")
    protected = _authority_lines(lines) if is_js else set()
    findings: list[PresentationFinding] = []
    for index, line in enumerate(lines):
        lineno = index + 1
        if lineno in protected or not line.strip():
            continue
        if _DIRECTION_CLAIM_RE.search(line):
            findings.append(
                PresentationFinding(relative_path, lineno, line.strip(), "hardcoded_direction")
            )
        if not is_js or _LOSS_RE.search(line):
            continue
        code = _strip_markup(line)
        if _SCORE_RE.search(code) and _ORDER_RE.search(code):
            findings.append(
                PresentationFinding(relative_path, lineno, line.strip(), "ordering_decision")
            )
    return findings


def presentation_files() -> list[Path]:
    """Every presentation source the Python census structurally cannot see."""
    files: list[Path] = []
    for directory in PRODUCTION_DIRS:
        for extension in PRESENTATION_EXTENSIONS:
            files += sorted((REPO_ROOT / directory).rglob(f"*{extension}"))
    return sorted(files)


def scan_presentation() -> list[PresentationFinding]:
    """The whole presentation surface, sorted for a stable census."""
    findings: list[PresentationFinding] = []
    for path in presentation_files():
        relative = str(path.relative_to(REPO_ROOT))
        findings += scan_presentation_source(path.read_text(encoding="utf-8"), relative)
    return sorted(findings, key=lambda f: (f.relative_path, f.lineno))


#: Presentation-layer ordering sites still awaiting migration.
#:
#: **EMPTY as of PR-12e.** The five sites F-12e-UX-3 measured — ``app.js``
#: ``Math.max(best, score)`` (twice), ``score > best``, and the two
#: ``'Denoising score (higher = better)'`` axis labels — plus
#: ``index.html``'s "Higher is better" caption are all migrated onto the
#: wire-borne direction. A non-empty entry here means a new hardcoded
#: direction reached the presentation layer.
EXPECTED_PRESENTATION_SURFACE: tuple[tuple[str, str], ...] = ()

#: The pre-12e surface, recorded verbatim so "migrated" stays a visible act.
#: Each row is ``(file, the exact text that used to be there)``.
MIGRATED_PRESENTATION_SITES: tuple[tuple[str, str], ...] = (
    ("src/dashboard/static/app.js", "best = best === null ? score : Math.max(best, score);"),
    ("src/dashboard/static/app.js", "if (score != null && (best === null || score > best)) {"),
    (
        "src/dashboard/static/app.js",
        "if (score != null) best = best === null ? score : Math.max(best, score);",
    ),
    (
        "src/dashboard/static/app.js",
        "const scoreLayout  = makePlotLayout('Denoising score (higher = better)');",
    ),
    (
        "src/dashboard/static/index.html",
        "Solid = cumulative best · Dashed = current experiment · Higher is better",
    ),
)


class TestThePresentationSurfaceIsClean:
    """The census itself."""

    def test_the_presentation_surface_is_exactly_the_expected_set(self):
        """MUTATION TARGET: restore ``Math.max(best, score)`` in ``app.js``.

        Fails the moment a hardcoded higher-is-better comparison or a fixed
        direction label reaches the presentation layer. That is the defect
        F-12e-UX-3 named, and it is invisible to every Python test in this
        repository — the P2a scanner cannot open a ``.js`` file.
        """
        found = {(f.relative_path, f.source) for f in scan_presentation()}
        expected = set(EXPECTED_PRESENTATION_SURFACE)
        unexpected = found - expected
        assert not unexpected, (
            "a hardcoded metric direction is live in the presentation layer — "
            "it will render an inverted best-curve under a lower-is-better "
            f"metric: {sorted(unexpected)}"
        )
        assert not (expected - found), (
            "a recorded presentation ordering site is no longer found; retire "
            f"its row in the migrating commit: {sorted(expected - found)}"
        )

    def test_the_scanner_reads_the_presentation_tree(self):
        """Anti-vacuity on the INPUT side — the F-12e-UX-8 shape itself.

        A census over no files is green, and that is exactly how the JS half
        went unguarded for a whole step. This asserts the scanner really
        opened the file the defect lived in.
        """
        files = presentation_files()
        relative = {str(p.relative_to(REPO_ROOT)) for p in files}
        assert "src/dashboard/static/app.js" in relative, (
            "the presentation census does not see app.js — the exact blindness "
            "(F-12e-UX-8) this module exists to close"
        )
        assert "src/dashboard/static/index.html" in relative
        assert len(files) >= 2

    def test_the_python_census_and_this_one_partition_the_tree(self):
        """Neither census alone covers the production tree; together they do.

        MUTATION TARGET: drop ``.js`` from :data:`PRESENTATION_EXTENSIONS`.

        This is the claim the two modules make jointly, asserted in one place
        so it cannot be true of each in isolation and false of the pair.
        """
        from tests.unit.execute_tools.test_step10_p2a_c0_ordering_scanner import production_files

        python_seen = {p.suffix for p in production_files()}
        presentation_seen = {p.suffix for p in presentation_files()}
        assert python_seen == {".py"}
        assert ".js" in presentation_seen, (
            "the presentation census claims to cover the layer the Python one "
            "cannot, but it is not looking at any JavaScript"
        )
        assert not (python_seen & presentation_seen), (
            "the two censuses overlap; each should own the extensions the "
            "other structurally cannot read"
        )

    def test_the_python_census_points_at_this_sibling(self):
        """A reader who finds ``rglob("*.py")`` must be told the JS half exists.

        MUTATION TARGET: delete the pointer comment from the P2a scanner.

        Without this, the P2a module still LOOKS like the whole ordering
        census, and the next person to add a chart has no reason to think
        otherwise. The pointer is the only thing joining two modules that a
        static reader cannot connect.
        """
        p2a = (
            REPO_ROOT / "tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py"
        ).read_text(encoding="utf-8")
        assert "test_step12_pr12e_presentation_ordering_census" in p2a, (
            "the Python ordering scanner no longer names the presentation "
            "census; a reader will take its .py-only file set for the whole "
            "surface, which is how F-12e-UX-8 happened"
        )

    def test_the_authority_region_is_bounded_and_small(self):
        """The exclusion must cover the authority, and nothing else.

        MUTATION TARGET: remove the ``}`` that closes ``orderFor``.

        The body exclusion is the one place this census deliberately stops
        looking, so its extent is asserted rather than assumed. A brace bug
        that let the region swallow the rest of the file would silence every
        finding below it — the census would go green by not looking, which is
        the failure mode this whole module is about.
        """
        lines = _blank_comments(
            (REPO_ROOT / "src/dashboard/static/app.js").read_text(encoding="utf-8")
        )
        region = _authority_lines(lines)
        assert region, "the permitted direction authority `orderFor` was not found in app.js"
        assert len(region) <= 25, (
            f"the authority exclusion covers {len(region)} lines; it is meant to "
            "cover one small function, not a region of the file"
        )
        assert len(region) < len(lines) / 4


class TestTheRetiredSitesAreRealAndWouldStillBeCaught:
    """The anti-vacuity pair. An empty surface proves nothing on its own.

    "Zero offenders" is also what you get from a scanner that stopped looking,
    or from code that was deleted rather than migrated. These two tests assert
    the other half.
    """

    def test_every_retired_site_would_still_be_flagged(self):
        """MUTATION TARGET: weaken ``_ORDER_RE`` or ``_DIRECTION_CLAIM_RE``.

        Each row of :data:`MIGRATED_PRESENTATION_SITES` is the exact text that
        used to be in the file. Running the scanner over those lines is the
        recorded proof that the census can see the defect it claims to have
        closed — verified when written against the real pre-12e bytes, where
        it reported all six at their audited line numbers (app.js 154, 345,
        372, 459, 503; index.html 95).
        """
        for path, historical in MIGRATED_PRESENTATION_SITES:
            found = scan_presentation_source(historical, path)
            assert found, (
                f"the census no longer flags {historical!r} — a site it "
                f"records as migrated from {path}. The surface is empty "
                "because the scanner stopped seeing, not because the code is "
                "clean."
            )

    def test_no_retired_site_is_still_live(self):
        """A row may only be retired by a migration that really happened."""
        for path, historical in MIGRATED_PRESENTATION_SITES:
            source = (REPO_ROOT / path).read_text(encoding="utf-8")
            assert historical not in source, (
                f"{path} still contains {historical!r}, which is recorded as migrated"
            )

    def test_the_authority_is_actually_consulted(self):
        """The positive half: the migrated sites really do ask ``orderFor``.

        Without this, deleting the charts outright would satisfy the census.
        """
        source = (REPO_ROOT / "src/dashboard/static/app.js").read_text(encoding="utf-8")
        consumers = len(re.findall(rf"\b{PRESENTATION_ORDER_AUTHORITY}\s*\(", source))
        assert consumers >= 4, (
            f"app.js consults the direction authority only {consumers} times; "
            "the presentation surface may have gone clean by deletion rather "
            "than by migration"
        )
        assert "series.metric" in source, (
            "app.js no longer reads the wire-borne metric identity, so the "
            "direction cannot be reaching it (F-12e-UX-9)"
        )


class TestTheScannerCatchesTheHistoricalOffenders:
    """Plant each defect the audit measured; the scanner must catch it."""

    @pytest.mark.parametrize(
        ("planted", "kind"),
        [
            ("best = best === null ? score : Math.max(best, score);", "ordering_decision"),
            ("if (score != null && (best === null || score > best)) {", "ordering_decision"),
            ("const top = records.filter(r => r.denoising_score > cutoff);", "ordering_decision"),
            ("if (r.best_score < worst) { worst = r.best_score; }", "ordering_decision"),
            ("const peak = Math.min(runningBest, score);", "ordering_decision"),
            ("makePlotLayout('Denoising score (higher = better)');", "hardcoded_direction"),
            ("<div>Higher is better</div>", "hardcoded_direction"),
            ("<span>lower = better</span>", "hardcoded_direction"),
        ],
    )
    def test_a_planted_offender_is_caught(self, planted: str, kind: str):
        found = scan_presentation_source(planted, "src/dashboard/static/planted.js")
        assert any(f.kind == kind for f in found), (
            f"the scanner did not flag {planted!r} as {kind}; findings={found}"
        )


class TestThePrecisionContract:
    """Each exclusion carries its reason, and each is falsifiable."""

    def test_every_exclusion_carries_a_reason(self):
        for key, reason in PRESENTATION_EXCLUSIONS.items():
            assert reason.strip(), f"exclusion {key!r} states no reason"

    def test_a_comment_about_direction_is_not_an_offender(self):
        """Otherwise this repository's own explanatory comments fail the census.

        A scanner that cannot tell prose from code is one nobody keeps green,
        and the first thing deleted to make it pass would be the comment
        explaining the defect.
        """
        source = (
            "// The old code did Math.max(best, score) and asserted "
            "higher = better.\n"
            "/* score > best was wrong under a minimised metric. */\n"
            "const x = 1;\n"
        )
        assert scan_presentation_source(source, "src/dashboard/static/x.js") == []

    def test_an_html_comment_about_direction_is_not_an_offender(self):
        source = "<!-- used to say Higher is better -->\n<div>ok</div>\n"
        assert scan_presentation_source(source, "src/dashboard/static/x.html") == []

    def test_a_null_check_is_not_an_ordering_decision(self):
        """``!==``/``!=``/``===`` are not order operators.

        Every real score read in the frontend is guarded by one, so a scanner
        that flagged them would report the whole data path and be useless.
        """
        source = "if (score !== null && score !== undefined) { best = score; }\n"
        assert scan_presentation_source(source, "src/dashboard/static/x.js") == []

    def test_an_arrow_function_is_not_an_ordering_decision(self):
        source = "const ys = records.map(r => r.denoising_score ?? null);\n"
        assert scan_presentation_source(source, "src/dashboard/static/x.js") == []

    def test_a_loss_comparison_is_not_flagged(self):
        """A loss is lower-is-better by definition — the P2a rule, unchanged."""
        source = "if (r.final_loss < bestLoss) { bestLoss = r.final_loss; }\n"
        assert scan_presentation_source(source, "src/dashboard/static/x.js") == []

    def test_an_unrelated_maximum_is_not_flagged(self):
        """``Math.max(0, countdown)`` carries no score token and must pass."""
        source = "el.textContent = Math.max(0, state.countdownValue);\n"
        assert scan_presentation_source(source, "src/dashboard/static/x.js") == []

    def test_html_markup_is_not_an_ordering_decision(self):
        """A tag's ``<``/``>`` are delimiters, not operators.

        MUTATION TARGET: delete ``_strip_markup``'s tag substitution.

        These four lines are real ones from ``index.html`` and ``app.js``.
        Without the markup exclusion the census reports every one of them and
        the three genuine sites are lost in the noise — the precision failure
        that makes a guard get deleted rather than kept.
        """
        source = (
            '<div id="chart-score" class="chart-wrap"></div>\n'
            '<input class="range-input" id="score-xmin" type="number" />\n'
            "<td>${fmt(r.denoising_score, 3)}</td>\n"
            '<span id="score-direction-note"></span>\n'
        )
        assert scan_presentation_source(source, "src/dashboard/static/x.js") == []

    def test_a_multiline_tag_terminator_is_not_an_ordering_decision(self):
        """``app.js`` builds its series tags across lines.

        The closing ``>`` then sits on a line with no ``<`` to pair with. The
        attribute-assignment rule is what recognises it as markup; this is the
        real line 650 from ``renderSeriesTags``.
        """
        source = (
            "      onclick=\"App.toggleHighlight('${s.id}')\" "
            'title="Highlight new-best points">★</button>\n'
        )
        assert scan_presentation_source(source, "src/dashboard/static/x.js") == []

    def test_the_markup_exclusion_does_not_hide_a_real_comparison(self):
        """MUTATION TARGET: make ``_HTML_TAG_RE`` accept bare attributes.

        The exclusion must be narrow enough that an expression cannot be
        mistaken for a tag. ``score`` is a letter, so a permissive tag pattern
        would swallow ``a <score && b> c`` — and, worse, any comparison on a
        line that also carries markup.
        """
        source = (
            'html += `<td class="x">ok</td>`;\n'
            "if (r.denoising_score > best) { best = r.denoising_score; }\n"
        )
        found = scan_presentation_source(source, "src/dashboard/static/x.js")
        assert [f.lineno for f in found] == [2], (
            f"the markup exclusion swallowed a real comparison; findings={found}"
        )

    def test_a_direction_claim_in_html_is_still_caught(self):
        """The ORDERING scan is JS-only; the LABEL scan is not.

        MUTATION TARGET: restrict ``_DIRECTION_CLAIM_RE`` to ``.js``.

        ``index.html:95`` asserted "Higher is better" in prose. Skipping HTML
        entirely — the tempting way to kill the markup noise — would reopen
        exactly half of F-12e-UX-3.
        """
        source = "<div>Solid = cumulative best · Higher is better</div>\n"
        found = scan_presentation_source(source, "src/dashboard/static/x.html")
        assert [f.kind for f in found] == ["hardcoded_direction"]

    def test_the_authority_body_is_excluded_but_only_there(self):
        """The exclusion is positional, and it is falsifiable in both directions."""
        source = (
            "function orderFor(metric) {\n"
            "  return { isBetter: (a, b) => (higher ? a > b : a < b) };\n"
            "}\n"
            "function elsewhere(records) {\n"
            "  return records.reduce((best, r) => Math.max(best, r.denoising_score), null);\n"
            "}\n"
        )
        found = scan_presentation_source(source, "src/dashboard/static/x.js")
        assert [f.lineno for f in found] == [5], (
            "the authority's own body must be excluded and the site outside it "
            f"must not be; findings={found}"
        )
