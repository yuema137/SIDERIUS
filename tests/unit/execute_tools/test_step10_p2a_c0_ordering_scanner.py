"""Step 10 / P2a — C0: the structural scanner over the golden-metric ordering surface.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2a_golden_metric_order_closure.md`` §5 (the scanner), §2.1 (the surface),
§2.2 (the precision contract); parent §8.1 acceptance criterion 3.

What this module replaces, and why
----------------------------------
``NOT_REACHED_DIRECTION_CONSUMERS``
(``tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py``) is a
PRESENCE LIST: five hand-written ``(file, literal)`` pairs. A presence list can
only find what somebody remembered to write down, and the measurement is in the
design: it names four of the ten code sites the P2a audit found. The chain
formal incumbent advance and the proposer's production ``top_n`` cut — the two
highest-consequence sites on the surface — are invisible to it.

This scanner finds the SHAPE instead. It is therefore able to report a site
nobody listed, which is exactly what it did on its first run: the two
``core/resume.py`` chain-fold rows (now in :data:`MIGRATED_SITES`, retired by
C2) are absent from the frozen §2.1 twelve-surface table, because their
comparison text contains no golden-score NAME.

**Status: the standing guard.** As of P2a C4 the production surface is EMPTY —
every measured ordering site consults ``MetricOrder``. This module's job from
here is to stay red the moment a new one appears.

The standing-guard contract (BINDING — read before extending anything)
---------------------------------------------------------------------
This scanner is **exhaustive for the CURRENT known primary-score carrier
shapes** — the golden-score name vocabulary in :data:`GOLDEN_SCORE_NAMES` plus
same-function, one-hop aliases of those names. It is NOT, and does not claim to
be, a general dataflow analysis:

* there is **no interprocedural analysis** — a golden score passed into a
  helper as an untyped ``float`` parameter and compared there is NOT found;
* alias tracking is **one hop and shape-restricted** — ``x = rec["denoising_score"]``
  is tracked, ``x = compute(rec)`` is not;
* a carrier shape that does not exist today is not covered by construction.

**Therefore: introducing a NEW primary-score carrier shape REQUIRES extending
this scanner's vocabulary or shape rules in the SAME change that introduces
it.** A future field that holds a golden score under a name this module does
not know is a silent hole, and the person who introduces it is the only person
positioned to close it.

A MEASURED instance of the first bullet (F-P3-1, recorded per the F-P2b-4
per-census rule)
-----------------------------------------------------------------------
Step 10 / P3's source audit found a real direction site this scanner cannot
see, and it is worth naming concretely so nobody re-derives the limitation from
a green run: ``clamp_comparative_analysis`` (``nodes/proposal_helpers.py``)
selected which comparison entries survive prompt clamping with
``sorted(indexed, key=lambda it: (-_score(it), it[0]))``, where the local
helper ``_score`` reads ``item[1].get("best_score")`` — a name that IS in
:data:`GOLDEN_SCORE_NAMES`. The read and the ordering sit in different
functions, so the sort key's own text carries no golden token and the one-hop
alias rule (:func:`_golden_aliases`, assignment-shaped and same-scope by
design) does not bridge the call. The site was invisible here while being a
genuine primary-score preference decision.

**The deliberate disposition (operator freeze ruling Q-P3-4): the site was
MIGRATED onto ``MetricOrder``, and this scanner was NOT widened to catch it.**
Transitive taint was measured on this repository at 22 false positives against
12 real sites; buying this one site with that noise would trade a precise guard
for one nobody keeps green. The migrated site's standing guard is therefore
BEHAVIOURAL — the hand-computed retention fixtures (DAVIS lower / higher
regime / absent identity) in the P3 clamp test module — not this AST census.

The general lesson, which outlives the specific site: **a census can be green
for a reason narrower than the claim it appears to make.** When a primary-score
comparison is reached through a function call rather than a name, this module
is silent, and only a behavioural fixture can own it.

Precision, not volume
---------------------
A scanner that banned every ``>``/``<``/``max``/``min``/``reverse=True`` would
be noise: the repository legitimately compares losses, runtimes, memory,
timings, indices, parameter counts and magnitudes. Each exclusion below is
declared WITH ITS REASON in :data:`PRECISION_EXCLUSIONS`, and
:func:`test_every_allowlist_entry_carries_a_reason` fails on a reasonless
entry, so the allowlist cannot quietly absorb a real offender.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The production package directories the scanner walks. This is the same set
#: the design's §10.3 post-P1 re-scan used, and it INCLUDES
#: ``workflows/task_composition.py`` (added by P1) and ``dashboard/``.
PRODUCTION_DIRS = (
    "src/agent",
    "src/core",
    "src/dashboard",
    "src/execute_tools",
    "src/ml_models",
    "src/nodes",
    "scripts",
    "src/workflows",
)

#: Identifier tokens that ARE the primary golden metric.
#:
#: Every entry is a name under which a golden score is actually carried in
#: production source today. Extending this set is how a new carrier shape is
#: brought under the guard (see the standing-guard contract above).
GOLDEN_SCORE_NAMES = (
    # the metric's own record/field name, and every ``*_denoising_score``
    # aggregate derived from it (best/worst/formal/valid/trial)
    "denoising_score",
    # the workflow's raw-formal progress tracker and the proposer/dashboard
    # per-model aggregate
    "best_score",
    "best_score_overall",
    # the chain-level incumbent trackers folded on resume
    "chain_formal_incumbent_reference",
    "chain_best_valid_formal_score",
    "chain_best_trial_score",
    # per-file evidence in linear space (``per_file_best``)
    "best_linear",
)

_GOLDEN_RE = re.compile(r"\b\w*(?:" + "|".join(GOLDEN_SCORE_NAMES) + r")\w*\b")

#: A token that matched :data:`GOLDEN_SCORE_NAMES` but names a LOSS is not the
#: golden metric. A training loss is lower-is-better by definition of a loss and
#: must never flip with the metric's direction — ``metric_order``'s own module
#: docstring pins this, and the tuner's same-loss ``final_loss`` rank depends
#: on it.
_LOSS_RE = re.compile(r"\bloss\b|_loss\b|\bloss_", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    """One flagged ordering decision on a golden score."""

    relative_path: str
    lineno: int
    source: str

    def __str__(self) -> str:
        return f"{self.relative_path}:{self.lineno}: {self.source}"


# ---------------------------------------------------------------------------
# The precision contract — every exclusion carries its reason
# ---------------------------------------------------------------------------

#: Shapes that mention a golden-score name but are NOT metric-direction
#: decisions. The scanner suppresses each one, and the reason is mandatory:
#: ``test_every_allowlist_entry_carries_a_reason`` fails on an empty reason, so
#: no exclusion can be added without stating what makes it direction-neutral.
PRECISION_EXCLUSIONS: dict[str, str] = {
    "loss": (
        "a training loss is lower-is-better BY DEFINITION of a loss and is "
        "unrelated to the golden metric; routing it through MetricOrder would "
        "make it flip when the metric direction flips (metric_order.py's own "
        "'losses' contract, and the tuner's same-loss final_loss rank)"
    ),
    "abs": (
        "abs(...) is a MAGNITUDE — 'how far apart', not 'which is better' — so "
        "it is direction-free: the same predicate is correct under higher and "
        "lower alike (design §2.2, change-magnitude filters). Applied at BOTH "
        "the comparison and the alias binding: a name bound from abs(...) "
        "carries a distance, not a score, and ordering it says nothing about "
        "the metric's direction. The live example is interpretation_helpers' "
        "SOTA band, whose real direction decision one line above already asks "
        "order.is_better"
    ),
    "len": (
        "len(...) compares a COUNT of records, not the scores inside them; the "
        "K-most-recent retention caps in core/resume.py are the live example"
    ),
    "authority_call": (
        "order.is_better / is_at_least / best / worst / rank IS the migration "
        "target — MetricOrder's own methods must not be reported as offenders "
        "or the scanner would flag the fix"
    ),
    "unkeyed_sort": (
        "sorted(names) / sorted(a_set) with no golden key expression orders "
        "identifiers or labels for stable display, not scores; flagging it "
        "would bury the real sites under alphabetical listing noise"
    ),
}


def _is_excluded(text: str) -> str | None:
    """The exclusion reason-key that suppresses ``text``, or ``None``."""
    if _LOSS_RE.search(text):
        return "loss"
    if re.search(r"\babs\s*\(", text):
        return "abs"
    if re.search(r"\blen\s*\(", text):
        return "len"
    if re.search(r"\b\w*order\.(is_better|is_at_least|best|worst|rank)\s*\(", text):
        return "authority_call"
    return None


def _mentions_golden(text: str, aliases: frozenset[str]) -> bool:
    stripped = _GOLDEN_RE.sub(lambda m: "" if not _LOSS_RE.search(m.group(0)) else m.group(0), text)
    if stripped != text:
        return True
    return any(re.search(rf"\b{re.escape(a)}\b", text) for a in aliases)


# ---------------------------------------------------------------------------
# Same-function, one-hop alias tracking (dataflow-lite)
# ---------------------------------------------------------------------------

_ALIAS_SOURCE_NODES = (ast.Attribute, ast.Subscript, ast.Call, ast.Name)


def _golden_aliases(scope: ast.AST) -> frozenset[str]:
    """Local names bound, in THIS scope, DIRECTLY from a golden-score expression.

    One hop and shape-restricted on purpose. ``x = rec["denoising_score"]``,
    ``x = out.best_valid_formal_denoising_score`` and ``x = rec.get("denoising_score")``
    are tracked; ``x = summarize(rec)`` is not, and neither is any name derived
    from an already-tracked alias. Transitive taint was measured on this
    repository and produced 22 false positives against 12 real sites — a
    scanner nobody would keep green.
    """
    found: set[str] = set()
    for node in ast.walk(scope):
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.NamedExpr):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None:
            continue
        pairs = _unpack(targets, value)
        for target, bound in pairs:
            if not isinstance(target, ast.Name):
                continue
            if not isinstance(bound, _ALIAS_SOURCE_NODES):
                continue
            text = ast.unparse(bound)
            if _LOSS_RE.search(text):
                continue
            if re.search(r"\babs\s*\(", text):
                # A magnitude, not a score carrier — see PRECISION_EXCLUSIONS["abs"].
                continue
            if _GOLDEN_RE.search(text):
                found.add(target.id)
    return frozenset(found)


def _unpack(targets: list[ast.expr], value: ast.expr) -> list[tuple[ast.expr, ast.expr]]:
    """Pair assignment targets with their bound expressions, one tuple level deep.

    ``score, best_score = rec["denoising_score"], best["denoising_score"]`` is a
    real production line (core/resume.py:450); without unpacking, both aliases
    would be missed.
    """
    pairs: list[tuple[ast.expr, ast.expr]] = []
    for target in targets:
        if isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple):
            if len(target.elts) == len(value.elts):
                pairs.extend(zip(target.elts, value.elts, strict=True))
                continue
        pairs.append((target, value))
    return pairs


# ---------------------------------------------------------------------------
# The flagged shapes
# ---------------------------------------------------------------------------

_ORDERING_OPS = (ast.Gt, ast.GtE, ast.Lt, ast.LtE)
_EXTREMUM_CALLS = frozenset({"max", "min", "sort", "sorted"})


def _sort_orders_by_golden(call: ast.Call, aliases: frozenset[str]) -> bool:
    """Whether a ``sort``/``sorted`` call orders BY a golden score.

    The ordering direction of a sort lives in its ``key`` (which value is
    compared) together with ``reverse``. A sort with no golden key expression
    is ordering something else — names, ids, labels — and is not a
    metric-direction decision.
    """
    for kw in call.keywords:
        if kw.arg == "key" and _mentions_golden(ast.unparse(kw.value), aliases):
            return True
    if not any(kw.arg == "key" for kw in call.keywords):
        return any(_mentions_golden(ast.unparse(arg), aliases) for arg in call.args)
    return False


def _scan_scope(
    scope: ast.AST,
    relative_path: str,
    aliases: frozenset[str],
    nested: frozenset[int],
) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(scope):
        if id(node) in nested:
            continue
        if isinstance(node, ast.Compare) and any(isinstance(op, _ORDERING_OPS) for op in node.ops):
            text = ast.unparse(node)
            if _is_excluded(text) is None and _mentions_golden(text, aliases):
                findings.append(Finding(relative_path, node.lineno, text))
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if name not in _EXTREMUM_CALLS:
                continue
            text = ast.unparse(node)
            if _is_excluded(text) is not None:
                continue
            if name in {"sort", "sorted"}:
                if _sort_orders_by_golden(node, aliases):
                    findings.append(Finding(relative_path, node.lineno, text))
                continue
            if _orders_by_golden_extremum(node, aliases):
                findings.append(Finding(relative_path, node.lineno, text))
    return findings


def _orders_by_golden_extremum(call: ast.Call, aliases: frozenset[str]) -> bool:
    """Whether a ``max``/``min`` call selects by a golden score."""
    for kw in call.keywords:
        if kw.arg == "key" and _mentions_golden(ast.unparse(kw.value), aliases):
            return True
    if not any(kw.arg == "key" for kw in call.keywords):
        return any(_mentions_golden(ast.unparse(arg), aliases) for arg in call.args)
    return False


def scan_source(source: str, relative_path: str) -> list[Finding]:
    """Every golden-metric ordering decision in ``source``.

    Raises:
        SyntaxError: propagated deliberately. A production file the scanner
            cannot parse is an INVISIBLE SITE, so it must fail the census
            rather than be skipped (design §5, C0 failure table).
    """
    tree = ast.parse(source)
    findings: list[Finding] = []

    function_scopes = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    #: Nodes belonging to a nested function are scanned under that function's
    #: own alias set, never twice.
    for scope in function_scopes:
        inner = frozenset(
            id(child)
            for nested_fn in ast.walk(scope)
            if isinstance(nested_fn, ast.FunctionDef | ast.AsyncFunctionDef)
            and nested_fn is not scope
            for child in ast.walk(nested_fn)
        )
        findings += _scan_scope(scope, relative_path, _golden_aliases(scope), inner)

    in_function = frozenset(id(child) for scope in function_scopes for child in ast.walk(scope))
    findings += _scan_scope(tree, relative_path, _golden_aliases(tree), in_function)
    return findings


def production_files() -> list[Path]:
    """Every production ``.py`` file the scanner is responsible for.

    ``.py`` ONLY — and that is a real limit, not an implementation detail.
    ``dashboard/`` is in :data:`PRODUCTION_DIRS` but ``app.js`` is not a
    Python file, so this walk could never see the frontend's hardcoded
    higher-is-better sites, and it stayed green through all of P2a while they
    were live (**F-12e-UX-8** — the ``F-12bc-9`` shape: a census whose FILE
    SET omits where the code lives).

    The presentation layer is covered by the sibling census
    ``tests/unit/execute_tools/test_step12_pr12e_presentation_ordering_census.py``,
    which owns ``.js`` and ``.html`` because they need a textual scanner
    rather than ``ast.parse``. **The two together are the ordering census;
    neither alone is.** That sibling asserts this pointer still exists, so a
    reader who finds ``rglob("*.py")`` here cannot mistake it for the whole
    surface.
    """
    files: list[Path] = []
    for directory in PRODUCTION_DIRS:
        files += sorted((REPO_ROOT / directory).rglob("*.py"))
    return files


def scan_production() -> list[Finding]:
    """The whole production surface, sorted for a stable census."""
    findings: list[Finding] = []
    for path in production_files():
        relative = str(path.relative_to(REPO_ROOT))
        findings += scan_source(path.read_text(encoding="utf-8"), relative)
    return sorted(findings, key=lambda f: (f.relative_path, f.lineno))


# ---------------------------------------------------------------------------
# The census — the pre-migration surface, recorded site by site
# ---------------------------------------------------------------------------

#: Golden-metric ordering sites still awaiting migration, each naming the
#: commit that owns it.
#:
#: **EMPTY as of P2a C4 — this is the standing guard now.** Every one of the
#: twelve sites measured at the implementation base has been migrated and moved
#: to :data:`MIGRATED_SITES`. A non-empty entry here again means a new
#: unmigrated primary-score ordering decision reached production, and
#: ``test_the_production_surface_is_exactly_the_expected_set`` fails until it is
#: either migrated or deliberately recorded.
#:
#: The tuple is kept rather than deleted so the census keeps naming the
#: concept, and so a future unmigrated site has an obvious home.
EXPECTED_ORDERING_SURFACE: tuple[tuple[str, str, str], ...] = ()

#: Sites RETIRED from the surface above, each citing the commit that emptied
#: it. A row leaves ``EXPECTED_ORDERING_SURFACE`` only by moving here, in the
#: SAME commit that migrates the code — so "migrated" stays a visible recorded
#: act rather than a row that quietly stopped being listed.
MIGRATED_SITES: tuple[tuple[str, str, str], ...] = (
    (
        "C1",
        "src/workflows/model_exploration.py",
        "tune_output.best_formal_denoising_score > state.best_score_overall"
        "  ->  _iter_order.is_better(...)",
    ),
    (
        "C1",
        "src/workflows/model_exploration.py",
        "_iter_valid_formal > state.chain_formal_incumbent_reference"
        "  ->  _iter_order.is_better(...)",
    ),
    (
        "C1",
        "src/workflows/model_exploration.py",
        "state.best_score_overall >= launch.target_score  ->  _iter_order.is_at_least(...)",
    ),
    (
        "C2",
        "src/core/resume.py",
        "score > best_score  ->  order.is_better(score, best_score)",
    ),
    (
        "C2",
        "src/core/resume.py",
        "formal_cand['score'] > state.chain_best_valid_formal_score"
        "  ->  _chain_order.is_better(...)",
    ),
    (
        "C2",
        "src/core/resume.py",
        "trial_cand['score'] > state.chain_best_trial_score  ->  _chain_order.is_better(...)",
    ),
    (
        "C2",
        "src/execute_tools/per_file_best.py",
        "new.best_linear > current.best_linear  ->  order.is_better(...)",
    ),
    (
        "C3",
        "src/dashboard/data_sources/local_json.py",
        "score > best_score  ->  order.is_better(score, best_score)",
    ),
    (
        "C3",
        "src/dashboard/data_sources/local_json.py",
        "entries.sort(key=lambda e: e['denoising_score'], reverse=True)"
        "  ->  sort(key=order.rank(...))",
    ),
    (
        "C4",
        "src/nodes/proposal_helpers.py",
        "scored.sort(key=lambda m: m['best_score'], reverse=True)  ->  sorted(key=order.rank(...))",
    ),
)


def _surface_signature(findings: list[Finding]) -> set[tuple[str, str]]:
    return {(f.relative_path, f.source) for f in findings}


class TestTheScannerFindsTheWholeSurface:
    """The census itself — what the scanner reports on production today."""

    def test_the_production_surface_is_exactly_the_expected_set(self):
        """MUTATION TARGET: delete a row from ``EXPECTED_ORDERING_SURFACE``.

        The claim is exact in BOTH directions. A new unmigrated ordering site
        fails it (that is the standing guard), and a site that quietly
        disappears without its row being retired fails it too — which is what
        makes 'migrated' a visible, recorded act rather than an absence.
        """
        found = _surface_signature(scan_production())
        expected = {(path, source) for path, source, _ in EXPECTED_ORDERING_SURFACE}

        unexpected = found - expected
        missing = expected - found
        assert not unexpected, (
            "an unrecorded golden-metric ordering decision is live in production — "
            "it will invert silently under a lower-is-better metric: "
            f"{sorted(unexpected)}"
        )
        assert not missing, (
            "a recorded ordering site is no longer found; if it was migrated, "
            "retire its row in the migrating commit rather than leaving the "
            f"census describing a surface that does not exist: {sorted(missing)}"
        )

    def test_the_scanner_reads_the_whole_production_tree(self):
        """Anti-vacuity on the INPUT side: a census over no files is green.

        The count is a floor rather than a literal so ordinary repository
        growth does not fail it, but a collapsed walk (a bad glob, a renamed
        package) does.
        """
        files = production_files()
        assert len(files) >= 250, (
            f"the scanner walked only {len(files)} production files; the surface "
            "it claims to hold is larger than that"
        )
        walked = {
            root
            for root in PRODUCTION_DIRS
            if any(p.is_relative_to(REPO_ROOT / root) for p in files)
        }
        assert walked == set(PRODUCTION_DIRS), (
            f"a declared production directory produced no files: {set(PRODUCTION_DIRS) - walked}"
        )

    def test_every_expected_site_names_its_migrating_commit(self):
        """No row may sit on the surface without an owner."""
        for path, source, commit in EXPECTED_ORDERING_SURFACE:
            assert commit in {"C1", "C2", "C3", "C4"}, (
                f"{path}: {source} names no migrating commit ({commit!r})"
            )

    def test_no_retired_site_is_still_live(self):
        """A row moved to MIGRATED_SITES must actually be gone from production.

        Retiring a row is how the census shrinks, so a retirement that did not
        correspond to a real migration would be the one way to make this whole
        module lie.
        """
        # Compared as (path, source) PAIRS, never source alone: the same
        # comparison text legitimately appears in two different files —
        # `score > best_score` is both resume's (migrated by C2) and the
        # dashboard's (still owed to C3) — and a source-only check would
        # report the retirement of one as a failure of the other.
        live = _surface_signature(scan_production())
        for commit, path, transition in MIGRATED_SITES:
            before = transition.split("  ->  ")[0]
            assert (path, before) not in live, (
                f"{path}: {before!r} is recorded as migrated by {commit} but the "
                "scanner still finds it in production"
            )

    def test_the_empty_surface_is_not_vacuous(self):
        """A green census over an empty expected set proves nothing on its own.

        With ``EXPECTED_ORDERING_SURFACE`` empty (P2a C4 onward), "zero
        offenders" would also be the result if the scanner had stopped
        looking, or if the migrated code had simply been deleted. So this
        asserts the POSITIVE half: the migrated sites really do consult the
        order authority, in the files the census says they were migrated in.

        The detection half is covered by ``TestTheScannerCatchesOffenders``
        and by the recorded production plant-and-catch.
        """
        consumers = 0
        for _commit, relative, _transition in MIGRATED_SITES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            consumers += len(
                re.findall(r"\b\w*order\.(is_better|is_at_least|best|worst|rank)\s*\(", source)
            )
            # C3's consumers reach the authority through the shared composer.
            consumers += source.count("persisted_ranking")
        assert consumers >= 8, (
            f"the migrated files consult the order authority only {consumers} times; "
            "the surface may have gone empty by deletion rather than by migration"
        )

    def test_the_whole_surface_is_accounted_for(self):
        """Every surviving framework site is either pending or retired.

        The original C0 measurement found twelve sites. Two diagnostic
        consumers now live with experiment provenance, so ten framework
        consumers remain. The total must not drift as rows move from pending
        to retired.
        """
        assert len(EXPECTED_ORDERING_SURFACE) + len(MIGRATED_SITES) == 10


class TestThePrecisionContract:
    """§2.2 — the shapes the scanner must NOT flag, each asserted separately.

    Asserted individually rather than as one bulk census so a regression names
    WHICH precision class broke.
    """

    def test_every_allowlist_entry_carries_a_reason(self):
        """The scanner's own self-check: a reasonless exclusion is a hole."""
        for key, reason in PRECISION_EXCLUSIONS.items():
            assert reason and reason.strip(), (
                f"precision exclusion {key!r} has no reason — an exclusion "
                "without a stated justification can absorb a real offender"
            )
            assert len(reason.strip()) >= 40, (
                f"precision exclusion {key!r} has a reason too short to be one: {reason!r}"
            )

    def test_a_training_loss_comparison_is_not_flagged(self):
        source = (
            "def f(rows):\n"
            "    best_loss = min(rows, key=lambda r: r['final_loss'])\n"
            "    return best_loss\n"
        )
        assert scan_source(source, "fixture") == []

    def test_the_same_loss_final_rank_is_not_flagged(self):
        """The live §2.2 pin: policy.py's ``min(same_loss_finals)``."""
        source = "def f(same_loss_finals):\n    return min(same_loss_finals)\n"
        assert scan_source(source, "fixture") == []

    def test_a_runtime_extremum_is_not_flagged(self):
        source = (
            "def f(obs):\n"
            "    return max(o.elapsed_seconds for o in obs), min(o.rss_gb for o in obs)\n"
        )
        assert scan_source(source, "fixture") == []

    def test_an_index_tie_break_is_not_flagged(self):
        source = (
            "def f(a, b):\n"
            "    if a.iter_idx != b.iter_idx:\n"
            "        return a.iter_idx < b.iter_idx\n"
            "    return a.exp_id < b.exp_id\n"
        )
        assert scan_source(source, "fixture") == []

    def test_a_round_index_comparison_is_not_flagged(self):
        source = "def f(a, b):\n    return a.round_index < b.round_index\n"
        assert scan_source(source, "fixture") == []

    def test_an_abs_magnitude_filter_is_not_flagged(self):
        """``abs(delta) >= threshold`` is direction-free even on a golden score."""
        source = (
            "def f(rec, prev, threshold):\n"
            "    return abs(rec['denoising_score'] - prev) >= threshold\n"
        )
        assert scan_source(source, "fixture") == []

    def test_a_distance_alias_bound_from_abs_is_not_flagged(self):
        """The live shape in ``nodes/interpretation_helpers.py``'s SOTA band.

        ``distance`` is bound from ``abs(best_score - sota_score)``, so it
        mentions a golden name — but it carries a MAGNITUDE. Comparing it to a
        band width is not a direction decision, and the real direction decision
        one line above already asks ``order.is_better``. Found as a false
        positive on the scanner's first production run; the rule was corrected
        rather than the site allowlisted.
        """
        source = (
            "def f(best_score, sota_score, order, band):\n"
            "    distance = abs(best_score - sota_score)\n"
            "    if order.is_better(best_score, sota_score):\n"
            "        return 'better'\n"
            "    return 'within' if distance <= band else 'below'\n"
        )
        assert scan_source(source, "fixture") == []

    def test_a_count_cap_against_a_named_constant_is_not_flagged(self):
        source = (
            "def f(state):\n"
            "    return len(state.accumulated_denoising_score_rejections) > _MAX_KEPT\n"
        )
        assert scan_source(source, "fixture") == []

    def test_an_unkeyed_sort_of_names_is_not_flagged(self):
        source = "def f(evicted):\n    return sorted(evicted)\n"
        assert scan_source(source, "fixture") == []

    def test_a_golden_name_in_a_comment_or_string_is_not_flagged(self):
        """The census is AST-shaped, not grep-shaped."""
        source = (
            "def f(a, b):\n"
            "    # denoising_score > best_score used to be compared here\n"
            '    note = "denoising_score > best_score"\n'
            "    return note\n"
        )
        assert scan_source(source, "fixture") == []

    def test_the_authoritys_own_calls_are_not_flagged(self):
        """MetricOrder IS the fix; flagging it would flag the migration."""
        source = (
            "def f(rows, order):\n"
            "    best = order.best(rows, key=lambda r: r['denoising_score'])\n"
            "    return order.is_better(best['denoising_score'], 0.0)\n"
        )
        assert scan_source(source, "fixture") == []

    def test_an_unrelated_local_named_score_is_not_flagged(self):
        """Dataflow-lite is same-function only, and says so.

        ``score`` bound from something that is not a golden carrier is NOT
        tracked — the limit is stated rather than approximated.
        """
        source = "def f(rec, other):\n    score = rec['review_rating']\n    return score > other\n"
        assert scan_source(source, "fixture") == []


class TestTheScannerCatchesOffenders:
    """Anti-vacuity on the DETECTION side — one fixture per flagged shape."""

    def test_a_direct_comparison_offender_is_caught(self):
        source = (
            "def f(rec, incumbent):\n"
            "    if rec['denoising_score'] > incumbent:\n"
            "        return rec\n"
            "    return None\n"
        )
        assert [f.source for f in scan_source(source, "fixture")] == [
            "rec['denoising_score'] > incumbent"
        ]

    def test_a_local_alias_offender_is_caught(self):
        """The proof that same-function assignment tracking is REAL.

        This is the plant the design requires alongside the direct one (§5,
        'TWO plants'): a string matcher over the comparison text alone finds
        nothing here, because the comparison mentions no golden name at all.
        It is also the exact shape of production site 2 — the chain formal
        incumbent advance — which a name-only scan does not see.
        """
        source = (
            "def f(record, incumbent):\n"
            "    primary_score = record['denoising_score']\n"
            "    if primary_score > incumbent:\n"
            "        return primary_score\n"
            "    return incumbent\n"
        )
        assert [f.source for f in scan_source(source, "fixture")] == ["primary_score > incumbent"]

    def test_an_attribute_alias_offender_is_caught(self):
        """Production site 2's literal shape."""
        source = (
            "def f(out, state):\n"
            "    latest = out.best_valid_formal_denoising_score\n"
            "    if latest > state.incumbent:\n"
            "        state.incumbent = latest\n"
        )
        assert [f.source for f in scan_source(source, "fixture")] == ["latest > state.incumbent"]

    def test_a_tuple_unpacked_alias_offender_is_caught(self):
        """core/resume.py:450's literal shape."""
        source = (
            "def f(rec, best):\n"
            "    score, best_value = rec['denoising_score'], best['denoising_score']\n"
            "    return score > best_value\n"
        )
        assert [f.source for f in scan_source(source, "fixture")] == ["score > best_value"]

    def test_a_reverse_sort_offender_is_caught(self):
        source = (
            "def f(rows):\n"
            "    rows.sort(key=lambda r: r['denoising_score'], reverse=True)\n"
            "    return rows\n"
        )
        assert len(scan_source(source, "fixture")) == 1

    def test_an_ascending_sort_on_a_golden_key_is_caught(self):
        """Direction lives in key+reverse TOGETHER; an ascending sort by a
        golden score is just as direction-bound as a descending one."""
        source = "def f(rows):\n    return sorted(rows, key=lambda r: r['denoising_score'])\n"
        assert len(scan_source(source, "fixture")) == 1

    def test_a_max_offender_is_caught(self):
        source = "def f(rows):\n    return max(rows, key=lambda r: r['denoising_score'])\n"
        assert len(scan_source(source, "fixture")) == 1

    def test_a_min_offender_is_caught(self):
        source = "def f(rows):\n    return min(rows, key=lambda r: r.best_linear)\n"
        assert len(scan_source(source, "fixture")) == 1

    def test_a_gte_offender_is_caught(self):
        source = "def f(state, target):\n    return state.best_score_overall >= target\n"
        assert len(scan_source(source, "fixture")) == 1


class TestTheScannerFailsClosed:
    """A file the scanner cannot read is an invisible site, not a pass."""

    def test_unparseable_source_raises_rather_than_being_skipped(self):
        with pytest.raises(SyntaxError):
            scan_source("def f(:\n    pass\n", "fixture")

    def test_every_production_file_actually_parses(self):
        """Runs the fail-closed contract over the real tree."""
        unparseable: list[str] = []
        for path in production_files():
            try:
                ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:  # pragma: no cover - a red tree is the point
                unparseable.append(f"{path.relative_to(REPO_ROOT)}: {exc}")
        assert not unparseable, (
            f"the scanner cannot read these production files, so any ordering "
            f"decision inside them is invisible: {unparseable}"
        )
