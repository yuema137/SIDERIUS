# tests/unit/execute_tools/health_checks/test_step10_p4_c0_residual_census.py
"""Step 10 / P4 — C0: the residual per-check-NAME surface census.

The migration tracker. Every framework-owned surface keyed on a check NAME or
an evidence-metric NAME is enumerated here with its anchor, together with the
stage that removes it — and, for the two the operator DEFERRED, the stage that
must leave it alone.

    id   surface                                   owner       removed by
    ---  ----------------------------------------  ----------  ----------
    T1   evaluation.py::_threshold name branches   P4          C2
    T2   evaluation.py per-file metric-name dict   P4          C2
    T3   evaluation.py per-file unit dict          P4          C2
    L1   evaluation.py sampling-method literal     P4          C2
    D1   evaluation.py duplicated defaults         P4          C2
    T4   health_feedback.py _WORST_STAT_BY_METRIC  P4          C3'
    L2   exactness not derived from declared unit  P4          C3'
    T5   health_feedback.py _RECORDING_KEY_METRICS HD-T5       NEVER (deferred)
    T6   prompts.py _COLLAPSE_ADVICE_BY_CHECK      HD-T6       NEVER (deferred)

The T5/T6 rows are as load-bearing as the others. Q-P4-3 defers them because
each needs a NEW declaration capability rather than a derivation from
declarations that already exist; asserting they SURVIVE is what stops a later
session from quietly absorbing them and calling P4 "more complete".

``EXPECTED_PRESENT`` is the stage marker: C2 flips the five ``evaluation.py``
rows to False, C3' flips T4 and L2. Each flip is a deliberate, reviewable
edit recorded in the design ledger — and because the surfaces are located by
CONTENT rather than line number, the census does not rot when lines move.

**L2's detector was rewritten (2026-08-27).** Located by content is not the
same as located by BEHAVIOUR. L2's original detector matched an ``ast.Compare``
whose comparator was the constant ``"count"``; C3' replaced that literal with
``in _INTEGRAL_UNITS`` — an ``ast.Name`` comparator — in the same commit that
flipped the row to ``False``. Behaviour unchanged, detector blind, row green:
the row would have gone green for a cosmetic extraction that derived nothing.
It now asserts the property through the production function (see
``_l2_present``). The standing rule, which the other rows should be re-read
against as they are next touched: **a residual census must assert over
behaviour or over a named authority, never over a syntactic form of it** — and
the cheap test is to mentally perform a semantics-preserving refactor and ask
whether the row would flip.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

EVALUATION = REPO_ROOT / "execute_tools" / "health_checks" / "evaluation.py"
HEALTH_FEEDBACK = REPO_ROOT / "agent" / "schemas" / "health_feedback.py"
PROMPTS = REPO_ROOT / "agent" / "prompts.py"


# ---------------------------------------------------------------------------
# Stage marker — the ONLY thing C2 / C3' edit in this module
# ---------------------------------------------------------------------------

EXPECTED_PRESENT: dict[str, bool] = {
    # C2 removed the five evaluation.py surfaces.
    "T1": False,
    "T2": False,
    "T3": False,
    "L1": False,
    "D1": False,
    # C3' removed both: the worst-case direction is derived from the declared
    # operator and exactness from the declared unit.
    "T4": False,
    "L2": False,
    # Deferred by Q-P4-3. These must remain True for the whole of P4.
    "T5": True,
    "T6": True,
}

DEFERRED: dict[str, str] = {"T5": "HD-T5", "T6": "HD-T6"}


# ---------------------------------------------------------------------------
# Content-addressed detectors
# ---------------------------------------------------------------------------


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _assigned_names(tree: ast.Module) -> set[str]:
    """Module-level assignments, plain AND annotated.

    ``_WORST_STAT_BY_METRIC: dict[str, str] = {...}`` is an ``AnnAssign``;
    collecting only ``Assign`` would silently miss every annotated constant
    and make this census vacuous for exactly the surfaces it tracks.
    """
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            found |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    return found


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _registered_check_names() -> set[str]:
    from execute_tools.health_checks import registry

    return set(registry.all_registered())


def _string_literals(node: ast.AST) -> set[str]:
    return {
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def _probe_exactness(metric_name: str, unit: str, value: float = 4.0) -> bool:
    """Run the real derivation and report whether it called the value exact.

    Drives ``_extract_discriminating_metrics`` through a persisted-shaped
    result — a CEILING operator so the worst statistic is the maximum, and no
    ``aggregate_statistics`` so the scalar branch publishes the value under the
    declared metric name. Nothing about the shape is L2-specific; it is the
    smallest input that reaches the exactness decision.
    """
    from agent.schemas.health_feedback import _extract_discriminating_metrics

    _raw, exactness = _extract_discriminating_metrics(
        {
            "threshold": {"metric": metric_name, "operator": "<", "unit": unit},
            "metrics": {metric_name: value},
        }
    )
    return exactness[metric_name]


def _l2_present() -> bool:
    """Is exactness still decided by something other than the DECLARED unit?

    **Why this is behavioural and not syntactic.** The original detector
    matched ``ast.Compare`` with an ``ast.Constant`` comparator equal to
    ``"count"``. C3' replaced the inline literal with ``in _INTEGRAL_UNITS``
    — an ``ast.Name`` comparator — in the SAME commit that flipped this row to
    ``False``. The detector therefore stopped being able to see the surface it
    names, and would have gone green for a purely cosmetic extraction that did
    no derivation at all. A row that certifies a live constraint closed is
    worse than no row: it turns a known unknown into a positive claim.

    This is a FOURTH census-blindness shape, distinct from the three already
    catalogued (*names a symbol* · *matches a token exactly* · *omits the file
    set*): **keys on an AST node type in a syntactic position**. The cheap test
    that catches all four: mentally perform a semantics-preserving refactor —
    extract the literal, invert the comparison, wrap it in a helper — and ask
    whether the row would flip. If yes, the row is not evidence.

    So the row now asserts the PROPERTY C3' claims, through the production
    function:

    * exactness must FOLLOW the declared unit — a cardinal unit and a scale
      unit must not produce the same answer; and
    * exactness must not be keyed on the evidence-metric NAME — which is the
      surface the whole census exists to track.

    Neither can be satisfied by moving a literal.
    """
    if _probe_exactness("alpha", "count") == _probe_exactness("alpha", "mV"):
        return True
    return any(
        _probe_exactness("alpha", unit) != _probe_exactness("distinct_symbols", unit)
        for unit in ("count", "mV")
    )


def _detect() -> dict[str, bool]:
    """Present/absent for each tracked surface, by content."""
    checks = _registered_check_names()
    evaluation = _module(EVALUATION)
    feedback = _module(HEALTH_FEEDBACK)
    prompts = _module(PROMPTS)

    threshold_fn = _function(evaluation, "_threshold")
    per_file_fn = _function(evaluation, "_per_file_metrics")

    # T1 — `_threshold` compares check_name against check-name literals.
    t1 = bool(
        threshold_fn is not None
        and any(
            isinstance(n, ast.Compare) and _string_literals(n) & checks
            for n in ast.walk(threshold_fn)
        )
    )

    # D1 — `_threshold` carries numeric fallbacks in `config.get(key, default)`.
    d1 = bool(
        threshold_fn is not None
        and any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and len(n.args) == 2
            and isinstance(n.args[1], ast.Constant)
            and isinstance(n.args[1].value, (int, float))
            and not isinstance(n.args[1].value, bool)
            for n in ast.walk(threshold_fn)
        )
    )

    # T2 / T3 — dict literals in `_per_file_metrics` keyed by check names.
    # Distinguished by their VALUES: metric names vs unit vocabulary.
    units = {"count", "mV", "fraction", "correlation", "ratio"}
    t2 = t3 = False
    if per_file_fn is not None:
        for node in ast.walk(per_file_fn):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            values = {v.value for v in node.values if isinstance(v, ast.Constant)}
            if not keys & checks:
                continue
            if values <= units and values:
                t3 = True
            else:
                t2 = True

    # L1 — the TIDMAD channel sampling label, wherever it sits in the module.
    l1 = "channel0001_prefix_peek" in _string_literals(evaluation)

    # T4 / T5 — the two named constants.
    feedback_names = _assigned_names(feedback)
    t4 = "_WORST_STAT_BY_METRIC" in feedback_names
    t5 = "_RECORDING_KEY_METRICS" in feedback_names

    # L2 — exactness decided by anything other than the DECLARED unit.
    # Asserted over BEHAVIOUR, never over a syntactic form. See _l2_present.
    l2 = _l2_present()

    # T6 — the per-check advice table.
    t6 = "_COLLAPSE_ADVICE_BY_CHECK" in _assigned_names(prompts)

    return {
        "T1": t1,
        "T2": t2,
        "T3": t3,
        "L1": l1,
        "D1": d1,
        "T4": t4,
        "L2": l2,
        "T5": t5,
        "T6": t6,
    }


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------


class TestResidualSurfaceCensus:
    def test_every_tracked_surface_matches_the_stage_marker(self):
        assert _detect() == EXPECTED_PRESENT

    def test_the_l2_detector_can_see_the_surface_it_names(self, monkeypatch):
        """Anti-vacuity, and the reason this row was rewritten.

        The syntactic detector this replaced could not fail: after C3' moved
        the literal into ``_INTEGRAL_UNITS`` there was no ``ast.Constant``
        comparator left to match, so ``L2`` was green because the detector had
        gone blind, not because the surface had gone. Emptying the vocabulary
        makes exactness stop following the declared unit — the exact property
        the row claims — and the detector must say so.
        """
        import agent.schemas.health_feedback as feedback_module

        assert _l2_present() is False
        monkeypatch.setattr(feedback_module, "_INTEGRAL_UNITS", frozenset())
        assert _l2_present() is True, (
            "the L2 detector cannot distinguish 'exactness derives from the "
            "declared unit' from 'exactness derives from nothing' — it is "
            "certifying a closure it cannot observe"
        )

    def test_the_l2_detector_would_see_a_name_keyed_exactness_rule(self, monkeypatch):
        """The other half: a per-metric-NAME rule is the census's whole subject.

        Planted through the production entry point rather than described, so
        the detector is exercised against the shape it bans.
        """
        import agent.schemas.health_feedback as feedback_module

        real = feedback_module._extract_discriminating_metrics

        def name_keyed(result):
            raw, _exactness = real(result)
            name = (result.get("threshold") or {}).get("metric")
            return raw, {name: name == "distinct_symbols"}

        monkeypatch.setattr(feedback_module, "_extract_discriminating_metrics", name_keyed)
        assert _l2_present() is True

    @pytest.mark.parametrize("surface_id, debt", sorted(DEFERRED.items()))
    def test_deferred_surfaces_are_not_absorbed_by_p4(self, surface_id, debt):
        """Q-P4-3: P4 must leave these alone.

        A session that "helpfully" migrates them turns this RED. Each needs a
        NEW declaration capability, not a derivation from declarations that
        already exist, and HD-T6 additionally carries LLM-facing byte-parity
        obligations that would change P4's Gate disposition.
        """
        assert EXPECTED_PRESENT[surface_id] is True, (
            f"{surface_id} is owned by {debt}, which is deferred for the whole of P4"
        )
        assert _detect()[surface_id] is True, f"{surface_id} ({debt}) was absorbed — out of scope"


class TestCheckNameLiteralCensus:
    """The property C2 actually buys: the generic evidence builder stops
    knowing any check by name."""

    #: C2 must drive this to `set()`. Hardcoded — reading it back from the
    #: module would compare the census to itself.
    #: C2 drove this to empty: the generic evidence builder no longer knows
    #: any check by name.
    EVALUATION_CHECK_NAME_LITERALS: ClassVar[set[str]] = set()

    #: `pearson_dispersion` here is T5's, NOT T4's — it is a recording-scalar
    #: key in `_RECORDING_KEY_METRICS`. It must SURVIVE P4 (HD-T5 deferred),
    #: so C3' drives this set to exactly `{"pearson_dispersion"}`, not empty.
    HEALTH_FEEDBACK_CHECK_NAME_LITERALS: ClassVar[set[str]] = {"pearson_dispersion"}

    def test_evaluation_module_check_name_literals(self):
        actual = _string_literals(_module(EVALUATION)) & _registered_check_names()
        assert actual == self.EVALUATION_CHECK_NAME_LITERALS

    def test_health_feedback_check_name_literals(self):
        actual = _string_literals(_module(HEALTH_FEEDBACK)) & _registered_check_names()
        assert actual == self.HEALTH_FEEDBACK_CHECK_NAME_LITERALS


class TestCensusIsAntiVacuous:
    """Planted offenders — each detector must actually fire."""

    def test_name_branch_detector_fires(self):
        tree = ast.parse(
            'def _threshold(check_name, config):\n    if check_name == "output_std":\n        return 1\n'
        )
        fn = _function(tree, "_threshold")
        assert fn is not None
        assert any(
            isinstance(n, ast.Compare) and _string_literals(n) & {"output_std"}
            for n in ast.walk(fn)
        )

    def test_numeric_fallback_detector_fires_and_ignores_keyless_get(self):
        planted = ast.parse('x = config.get("min_std_mv", 1.0)\n')
        clean = ast.parse('x = config.get("min_std_mv")\n')

        def has_numeric_default(tree):
            return any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get"
                and len(n.args) == 2
                and isinstance(n.args[1], ast.Constant)
                and isinstance(n.args[1].value, (int, float))
                for n in ast.walk(tree)
            )

        assert has_numeric_default(planted)
        assert not has_numeric_default(clean)

    def test_annotated_constant_is_collected(self):
        """The AnnAssign trap: both tracked constants are annotated, so a
        collector seeing only `Assign` would report them absent and make the
        whole census vacuous."""
        tree = ast.parse('_WORST_STAT_BY_METRIC: dict[str, str] = {"a": "minimum"}\n')
        assert "_WORST_STAT_BY_METRIC" in _assigned_names(tree)

    def test_unit_literal_comparison_detector_fires(self):
        tree = ast.parse('exact = threshold.get("unit") == "count"\n')
        assert any(
            isinstance(n, ast.Compare)
            and any(isinstance(c, ast.Constant) and c.value == "count" for c in n.comparators)
            for n in ast.walk(tree)
        )

    def test_all_tracked_ids_are_detected(self):
        """No tracked id may silently fall out of the detector."""
        assert set(_detect()) == set(EXPECTED_PRESENT)
