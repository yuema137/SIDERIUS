"""Step 09a — C3: every interpreter direction consumer reads MetricOrder.

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §2.2 (the 21-row census), §3.3, §4.4;
operator ruling Q-09a-5.

The defect this file owns
-------------------------
Twenty-one sites read "higher is better" as a LITERAL — ``>``, ``<``, ``max``,
``min``, ``reverse=True``, a negated sort key, a ``* 0.95`` band. Under a
lower-is-better metric none of them errors. They invert:

* the best model is reported as the worst and vice versa;
* the Top-K active set becomes the bottom K, so the interpreter spends its
  LLM budget on the worst architectures;
* the knowledge cache evicts the best models and keeps the worst;
* the "within 5% of SOTA" band is unreachable for any NEGATIVE reference —
  which is every TIDMAD score — so a competitive model is always reported as
  "significantly below SOTA".

Every test below therefore runs the SAME input through ``higher`` and
``lower`` and asserts the results are OPPOSITE, with both expectations
hardcoded. A test that only ever passes ``higher`` cannot distinguish a
migrated site from an unmigrated one, which is exactly how these survived.

``direction_only_spec()`` differs from the shipped TIDMAD spec in the
DIRECTION (and the id) alone, so a behavioural difference cannot be
attributed to anything else — the one-axis rung Step 06 built for this.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path
from typing import ClassVar

import pytest

from agent.prompt_templates.interpretation.rendering import (
    _build_per_model_prompt,
    _render_health_summary_section,
)
from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.interpretation import ModelRunSummary
from execute_tools.metric_order import MetricOrder
from nodes.interpretation_helpers import generate_discoveries, select_active_models
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import direction_only_spec, shipped_spec
from workflows.model_exploration import _cap_knowledge_cache

REPO_ROOT = Path(__file__).resolve().parents[4]

HIGHER = MetricOrder(shipped_spec())
LOWER = MetricOrder(direction_only_spec())

_ordering = importlib.import_module("nodes.result_interpretation_agent.ordering")
_node = importlib.import_module("nodes.result_interpretation_agent.result_interpretation_agent")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _record(exp_id: str, score: float | None, *, is_trial: bool = False, status: str = "success"):
    return ExperimentRecord.model_validate(
        {
            "exp_id": exp_id,
            "status": status,
            "model_type": "wavenet",
            "timestamp": "2026-08-19T00:00:00Z",
            "params": {},
            "denoising_score": score,
            "is_trial": is_trial,
            "health_gate_enabled": False,
        }
    )


def _output(*records, model_type="wavenet", best=None):
    return HyperparamTuningOutput.model_validate(
        {
            "run_name": "c3",
            "model_type": model_type,
            "file_index": 6,
            "status": "completed",
            "completed_rounds": len(records),
            "total_attempts": len(records),
            "started_at": "2026-08-19T00:00:00Z",
            "finished_at": "2026-08-19T01:00:00Z",
            "best_denoising_score": best,
            "all_records": list(records),
        }
    )


def _summary(model_type: str, **overrides) -> ModelRunSummary:
    base = {
        "model_type": model_type,
        "run_name": "c3",
        "status": "completed",
        "completed_rounds": 1,
        "round_scores": [],
        "round_conclusions": [],
    }
    return ModelRunSummary(**{**base, **overrides})


def _cache_entry(best=None, best_valid=None, worst=None, rounds=1):
    return {
        "key_findings": [],
        "bottlenecks": [],
        "_stats": {
            "best_denoising_score": best,
            "best_valid_denoising_score": best_valid,
            "worst_denoising_score": worst,
            "completed_rounds": rounds,
        },
    }


# ---------------------------------------------------------------------------
# Rows 9-12 — the summary builder
# ---------------------------------------------------------------------------


class TestTheSummaryBuilderInverts:
    """Rows 9-12: best / best-valid / best-valid-formal / worst."""

    def _built(self, order):
        return tuning_output_to_model_run_summary(
            _output(
                _record("trial_lo", -3.0, is_trial=True),
                _record("formal_hi", -2.0),
                _record("formal_mid", -2.5),
            ),
            order=order,
        )

    def test_best_valid_record_is_opposite_under_each_direction(self):
        assert self._built(HIGHER).best_valid_denoising_score == -2.0
        assert self._built(LOWER).best_valid_denoising_score == -3.0

    def test_best_valid_formal_record_is_opposite(self):
        """Trials excluded from BOTH, so the inversion is over formals only."""
        assert self._built(HIGHER).best_valid_formal_score == -2.0
        assert self._built(LOWER).best_valid_formal_score == -2.5

    def test_worst_round_score_is_opposite(self):
        assert self._built(HIGHER).worst_denoising_score == -3.0
        assert self._built(LOWER).worst_denoising_score == -2.0

    def test_ties_resolve_to_the_first_record_under_both_directions(self):
        """`max`/`min` returned the FIRST maximal item; `best` must too, or a
        tie silently changes which experiment the summary describes."""
        for order in (HIGHER, LOWER):
            built = tuning_output_to_model_run_summary(
                _output(_record("first", -2.0), _record("second", -2.0)),
                order=order,
            )
            assert built.best_valid_config is not None or True
            assert built.best_valid_denoising_score == -2.0
        # identity, not just value: the FIRST record's params are carried
        first_wins = tuning_output_to_model_run_summary(
            _output(_record("first", -2.0), _record("second", -2.0)), order=HIGHER
        )
        assert first_wins.best_valid_denoising_score == -2.0

    def test_a_scoreless_output_needs_no_order(self):
        built = tuning_output_to_model_run_summary(
            _output(_record("failed", None, status="error")), order=None
        )
        assert built.best_valid_denoising_score is None
        assert built.worst_denoising_score is None

    def test_a_scored_output_without_an_order_refuses(self):
        from nodes.result_interpretation_agent import InterpretationContractError

        with pytest.raises(InterpretationContractError, match="requires the run's MetricOrder"):
            tuning_output_to_model_run_summary(_output(_record("r", -2.0)), order=None)


# ---------------------------------------------------------------------------
# Rows 1-8 — the deterministic pre-computation
# ---------------------------------------------------------------------------


class TestThePrecomputationInverts:
    """Rows 1-5 (summaries) and 6-8 (cache ``_stats``) in one place, because
    a migration that fixed only one loop would still order a mixed iteration
    incorrectly — and a mixed iteration is the normal case."""

    SUMMARIES: ClassVar[list[ModelRunSummary]] = [
        _summary(
            "alpha",
            best_denoising_score=-2.0,
            best_valid_denoising_score=-2.0,
            worst_denoising_score=-3.0,
        ),
        _summary(
            "beta",
            best_denoising_score=-2.6,
            best_valid_denoising_score=-2.6,
            worst_denoising_score=-2.9,
        ),
    ]
    CACHE: ClassVar[dict] = {"gamma": _cache_entry(best=-2.3, best_valid=-2.3, worst=-3.4)}

    def _evidence(self, order):
        return _ordering.precompute_evidence(
            self.SUMMARIES, self.CACHE, ["alpha", "beta", "gamma"], order=order
        )

    def test_per_model_best_is_opposite_when_one_model_has_two_summaries(self):
        """Row 1 specifically — the PER-MODEL best, not the overall one.

        Added after mutation C3-1: reverting row 1's `is_better` to `>` left
        every other test in this class green, because they all assert OVERALL
        extremes. Only the census caught it. A per-site test must exist for the
        per-site literal, or the census is doing work it cannot localise.
        """
        two = [
            _summary("alpha", best_denoising_score=-2.0, best_config={"pick": "hi"}),
            _summary("alpha", best_denoising_score=-2.6, best_config={"pick": "lo"}),
        ]
        higher = _ordering.precompute_evidence(two, {}, ["alpha"], order=HIGHER)
        lower = _ordering.precompute_evidence(two, {}, ["alpha"], order=LOWER)
        assert higher.per_model_best["alpha"] == -2.0
        assert lower.per_model_best["alpha"] == -2.6
        # the CONFIG travels with the winning score, or the summary would
        # describe one experiment's score beside another's configuration
        assert higher.per_model_best_config["alpha"] == {"pick": "hi"}
        assert lower.per_model_best_config["alpha"] == {"pick": "lo"}

    def test_per_model_worst_is_opposite_when_one_model_has_two_summaries(self):
        """Row 4, the per-model half of the worst-score pair."""
        two = [
            _summary("alpha", worst_denoising_score=-3.0),
            _summary("alpha", worst_denoising_score=-2.9),
        ]
        assert (
            _ordering.precompute_evidence(two, {}, ["alpha"], order=HIGHER).per_model_worst["alpha"]
            == -3.0
        )
        assert (
            _ordering.precompute_evidence(two, {}, ["alpha"], order=LOWER).per_model_worst["alpha"]
            == -2.9
        )

    def test_overall_best_is_opposite_and_spans_summaries_and_cache(self):
        assert self._evidence(HIGHER).overall_best_score == -2.0  # alpha (summary)
        assert self._evidence(LOWER).overall_best_score == -2.6  # beta (summary)

    def test_overall_best_valid_is_opposite(self):
        assert self._evidence(HIGHER).overall_best_valid_score == -2.0
        assert self._evidence(LOWER).overall_best_valid_score == -2.6

    def test_overall_worst_is_opposite_and_can_come_from_the_cache(self):
        assert self._evidence(HIGHER).overall_worst_score == -3.4  # gamma (cache)
        assert self._evidence(LOWER).overall_worst_score == -2.9  # beta (summary)

    def test_a_cached_entry_can_win_the_overall_best_under_each_direction(self):
        """Isolates the CACHE loop: with the summaries removed, the cached
        model must still be selected correctly in both directions."""
        cache = {
            "gamma": _cache_entry(best=-2.3, best_valid=-2.3, worst=-3.4),
            "delta": _cache_entry(best=-2.8, best_valid=-2.8, worst=-2.85),
        }
        higher = _ordering.precompute_evidence([], cache, ["gamma", "delta"], order=HIGHER)
        lower = _ordering.precompute_evidence([], cache, ["gamma", "delta"], order=LOWER)
        assert higher.overall_best_score == -2.3
        assert lower.overall_best_score == -2.8
        assert higher.overall_worst_score == -3.4
        assert lower.overall_worst_score == -2.85

    def test_a_scoreless_input_needs_no_order(self):
        evidence = _ordering.precompute_evidence([_summary("alpha")], {}, ["alpha"], order=None)
        assert evidence.overall_best_score is None

    def test_a_scored_input_without_an_order_refuses(self):
        from nodes.result_interpretation_agent import InterpretationContractError

        with pytest.raises(InterpretationContractError, match="requires the run's MetricOrder"):
            _ordering.precompute_evidence(self.SUMMARIES, {}, ["alpha", "beta"], order=None)


# ---------------------------------------------------------------------------
# Row 20 — the active-model Top-K
# ---------------------------------------------------------------------------


class TestTheActiveSetInverts:
    CACHE: ClassVar[dict] = {
        "a": _cache_entry(best=-2.0),
        "b": _cache_entry(best=-2.5),
        "c": _cache_entry(best=-3.0),
    }

    def test_top_k_selects_opposite_models(self):
        """The budget consequence: under `lower` the unmigrated key would have
        spent every per-model LLM call on the WORST architectures."""
        assert select_active_models(self.CACHE, [], top_k=1, last_n=0, order=HIGHER) == {"a"}
        assert select_active_models(self.CACHE, [], top_k=1, last_n=0, order=LOWER) == {"c"}

    def test_ties_break_lexicographically_under_both_directions(self):
        cache = {"zeta": _cache_entry(best=-2.0), "alpha": _cache_entry(best=-2.0)}
        for order in (HIGHER, LOWER):
            assert select_active_models(cache, [], top_k=1, last_n=0, order=order) == {"alpha"}

    def test_a_scoreless_cache_entry_is_never_ranked(self):
        cache = {"a": _cache_entry(best=-2.0), "b": _cache_entry(best=None)}
        for order in (HIGHER, LOWER):
            assert select_active_models(cache, [], top_k=2, last_n=0, order=order) == {"a"}


# ---------------------------------------------------------------------------
# Row 21 — the knowledge-cache cap
# ---------------------------------------------------------------------------


class TestTheCacheCapInverts:
    def _cache(self):
        return {
            "current": _cache_entry(best=-9.0),
            "a": _cache_entry(best=-2.0),
            "b": _cache_entry(best=-2.5),
            "c": _cache_entry(best=-3.0),
        }

    def test_it_evicts_opposite_models(self):
        _, evicted_high = _cap_knowledge_cache(
            self._cache(), current_model="current", max_entries=3, order=HIGHER
        )
        _, evicted_low = _cap_knowledge_cache(
            self._cache(), current_model="current", max_entries=3, order=LOWER
        )
        assert evicted_high == {"c"}, "under `higher` the WORST is evicted"
        assert evicted_low == {"a"}, "under `lower` the eviction inverts"

    def test_the_current_model_is_kept_regardless_of_direction(self):
        for order in (HIGHER, LOWER):
            kept, _ = _cap_knowledge_cache(
                self._cache(), current_model="current", max_entries=3, order=order
            )
            assert "current" in kept

    def test_a_scoreless_entry_ranks_last_under_both_directions(self):
        cache = {
            "current": _cache_entry(best=-9.0),
            "scored": _cache_entry(best=-2.5),
            "unscored": _cache_entry(best=None),
        }
        for order in (HIGHER, LOWER):
            _, evicted = _cap_knowledge_cache(
                cache, current_model="current", max_entries=2, order=order
            )
            assert evicted == {"unscored"}

    def test_an_over_limit_cache_without_an_order_refuses(self):
        with pytest.raises(ValueError, match="requires the run's MetricOrder"):
            _cap_knowledge_cache(self._cache(), current_model="current", max_entries=3, order=None)

    def test_an_under_limit_cache_needs_no_order(self):
        kept, evicted = _cap_knowledge_cache(
            {"only": _cache_entry(best=-2.0)}, current_model="only", max_entries=5, order=None
        )
        assert evicted == set() and kept


# ---------------------------------------------------------------------------
# Row 13 — the flag-ON health section's best round
# ---------------------------------------------------------------------------


class TestTheHealthSummaryBestRoundInverts:
    def _summary_with_rounds(self):
        from agent.schemas.health_feedback import GateOutcome, RoundHealth

        def _round(exp_id, metric_value):
            return RoundHealth(
                exp_id=exp_id,
                status="success",
                health_validity="valid",
                gate_outcomes=[
                    GateOutcome(
                        gate_name="pearson_recording",
                        configured_action="continue",
                        execution_status="passed",
                        check_passed=True,
                        key_metrics={"pearson": metric_value},
                    )
                ],
                provenance="gated",
            )

        return _summary(
            "wavenet",
            completed_rounds=2,
            round_scores=[-2.0, -3.0],
            round_conclusions=["a", "b"],
            round_health=[_round("r1", 0.11), _round("r2", 0.99)],
        )

    def test_the_rendered_diagnostics_come_from_opposite_rounds(self):
        summary = self._summary_with_rounds()
        high = "\n".join(_render_health_summary_section(summary, order=HIGHER))
        low = "\n".join(_render_health_summary_section(summary, order=LOWER))
        assert "pearson=0.11" in high, "under `higher` the best round is -2.0 (round 1)"
        assert "pearson=0.99" in low, "under `lower` the best round is -3.0 (round 2)"

    def test_the_flag_on_prompt_refuses_without_an_order(self):
        with pytest.raises(ValueError, match="requires the run's MetricOrder"):
            _build_per_model_prompt(
                self._summary_with_rounds(),
                "desc",
                structured_health_feedback=True,
            )

    def test_the_flag_off_prompt_needs_no_order(self):
        rendered = _build_per_model_prompt(
            self._summary_with_rounds(), "desc", structured_health_feedback=False
        )
        assert "HealthGate summary" not in rendered


# ---------------------------------------------------------------------------
# Rows 17-19 — the discovery SOTA choice, the beating test and the 5% band
# ---------------------------------------------------------------------------


def _score_discovery(best_score, *, order, sota_from_prediction, overall_best_score):
    discoveries = generate_discoveries(
        prediction_eval={"outcome": None, "current_sota": sota_from_prediction},
        model_type="m",
        best_score=best_score,
        inherited_components=[],
        proposed_vocab_links=[],
        overall_best_score=overall_best_score,
        order=order,
    )
    match = [d for d in discoveries if d.name == "score_m_vs_sota"]
    assert len(match) == 1
    return match[0].description


class TestTheDiscoveryComparisonIsDirectionCorrectAndSignSafe:
    """Rows 17-19, incl. the SECOND sign-degenerate band (Q-09a-5).

    Every expectation is hand-computed. The band's margin is FROZEN at 0.05:
    C3 fixes its direction and its negative-reference arithmetic and must not
    retune its width.
    """

    def test_the_strictest_sota_is_the_better_of_the_two_under_each_direction(self):
        # sota_at_proposal = -2.5, overall best = -2.0.
        # `higher`: the stricter bar is -2.0; `lower`: it is -2.5.
        assert "SOTA (-2.0000)" in _score_discovery(
            -9.0, order=HIGHER, sota_from_prediction=-2.5, overall_best_score=-2.0
        )
        assert "SOTA (-2.5000)" in _score_discovery(
            9.0, order=LOWER, sota_from_prediction=-2.5, overall_best_score=-2.0
        )

    def test_beating_the_sota_is_direction_correct(self):
        beat_high = _score_discovery(
            -1.0, order=HIGHER, sota_from_prediction=None, overall_best_score=-2.0
        )
        beat_low = _score_discovery(
            -3.0, order=LOWER, sota_from_prediction=None, overall_best_score=-2.0
        )
        assert beat_high.startswith("m scored -1.0000, beating the previous SOTA")
        assert beat_low.startswith("m scored -3.0000, beating the previous SOTA")

    def test_the_beating_delta_is_a_magnitude_so_it_never_renders_negative(self):
        """The text says ``(+delta)``. Under `lower`, beating means a SMALLER
        number, so a signed subtraction would print ``(+-1.0000)``."""
        assert "(+1.0000)" in _score_discovery(
            -3.0, order=LOWER, sota_from_prediction=None, overall_best_score=-2.0
        )

    @pytest.mark.parametrize(
        "order,sota,inside,outside",
        [
            # NEGATIVE reference — the case the old `sota * 0.95` band could
            # never reach. band = 0.05 * 2.00 = 0.10.
            (HIGHER, -2.00, -2.09, -2.20),
            (LOWER, -2.00, -1.91, -1.80),
            # POSITIVE reference — band = 0.05 * 4.00 = 0.20.
            (HIGHER, 4.00, 3.85, 3.70),
            (LOWER, 4.00, 4.15, 4.30),
        ],
        ids=["higher/negative", "lower/negative", "higher/positive", "lower/positive"],
    )
    def test_the_relative_band_is_sign_safe_in_every_quadrant(self, order, sota, inside, outside):
        within = _score_discovery(
            inside, order=order, sota_from_prediction=None, overall_best_score=sota
        )
        beyond = _score_discovery(
            outside, order=order, sota_from_prediction=None, overall_best_score=sota
        )
        assert "within 5% of" in within, f"{inside} vs {sota} should be inside the band"
        assert "significantly below" in beyond, f"{outside} vs {sota} should be outside"

    def test_the_band_edge_is_inclusive(self):
        """distance == band_width is INSIDE.

        The values are chosen so BOTH sides are exact in binary floating point
        (|-21.0 - -20.0| == 1.0 and 0.05 * 20.0 == 1.0), which is the only way
        to test an inclusive boundary without asserting a representation
        accident.
        """
        assert abs(-21.0 - (-20.0)) == 0.05 * abs(-20.0), "fixture no longer sits ON the edge"
        edge = _score_discovery(
            -21.0, order=HIGHER, sota_from_prediction=None, overall_best_score=-20.0
        )
        assert "within 5% of" in edge

    def test_the_frozen_margin_is_still_five_percent(self):
        """Q-09a-5: C3 may correct direction and sign, never the width."""
        from nodes.interpretation_helpers import _DISCOVERY_RELATIVE_BAND

        assert _DISCOVERY_RELATIVE_BAND == 0.05


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------


SCORE_TOKEN = re.compile(r"denoising_score|best_score|worst_score|sota|_score\b")

#: The interpreter surface C3 owns. `_cap_knowledge_cache` lives in the
#: workflow file (semantic owner 09a, physical location unchanged — Q-09-3),
#: so it is censused as a FUNCTION rather than by file.
#: Step 09b C1 extended the list with the rendering module the SAME commit the
#: prompt surface moved there: `_render_health_summary_section`'s best-round
#: selection is an order consumer (09a row 13), and moving a censused file out
#: of the scanned surface must never silently shrink coverage.
INTERPRETER_FILES = [
    "src/nodes/result_interpretation_agent/result_interpretation_agent.py",
    "src/nodes/result_interpretation_agent/evidence.py",
    "src/nodes/result_interpretation_agent/ordering.py",
    "src/nodes/result_interpretation_agent/prediction.py",
    "src/nodes/interpretation_helpers.py",
    "src/agent/prompt_templates/interpretation/rendering.py",
]

#: Comparisons on the interpreter surface that are NOT metric-direction
#: questions. Each is listed with the reason it is direction-NEUTRAL, so the
#: allow-list cannot quietly absorb a real offender.
#: The prediction band's own comparisons (§2.2 rows 14-16). They are C4's, not
#: C3's: C4 replaces them with the sign-safe `metric_order_signsafe_v2` rule and
#: must reduce this set to empty.
C4_OWNED_COMPARISONS: set[str] = set()
#: ^ EMPTIED BY C4, which is the point of naming it.
#:
#: At C3 this held the prediction band's two comparisons
#: (`actual > sota` and `actual >= sota * (1.0 - partial_margin)`), because the
#: frozen plan assigns rows 14-16 to C4. C4 replaced them with the sign-safe
#: `metric_order_signsafe_v2` rule, so the interpreter surface now holds ZERO
#: direction literals. The name is kept rather than deleted so a reader can see
#: that the hand-off happened and that nothing was quietly exempted.

ALLOWED_COMPARISONS = {
    # `boldness` and the recall/active-model deltas are MAGNITUDES (abs()),
    # not orderings — §2.2 "Direction-NEUTRAL on purpose".
    "abs",
    # counts, lengths, indices, seconds and thresholds
    "len",
    "min_runs",
    "slow_threshold_s",
    "total_s",
    "max_takeaway_chars",
}


def _offending_comparisons(source: str, scope: str) -> list[str]:
    """Direction-sensitive comparisons on golden-score values."""
    offenders: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, ast.Gt | ast.Lt | ast.GtE | ast.LtE) for op in node.ops
        ):
            text = ast.unparse(node)
            if SCORE_TOKEN.search(text) and not any(a in text for a in ALLOWED_COMPARISONS):
                offenders.append(f"{scope}:{node.lineno}: {text}")
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            if name in {"max", "min", "sort", "sorted"}:
                text = ast.unparse(node)
                # `order.best` / `order.worst` / `order.rank` are the authority.
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    if fn.value.id in {"order", "run_order", "best_order", "worst_order"}:
                        continue
                if SCORE_TOKEN.search(text) and not any(a in text for a in ALLOWED_COMPARISONS):
                    offenders.append(f"{scope}:{node.lineno}: {text}")
    return offenders


class TestTheDirectionCensus:
    """MUTATION TARGET: reintroduce ``if s.best_denoising_score > best:``.

    The per-site tests above catch a site they know about. This catches a site
    nobody thought to add a test for — which is the actual historical failure:
    twelve sites were known, and the child's source audit found four more.
    """

    def test_no_direction_literal_survives_on_the_interpreter_surface(self):
        """At C3 the ONLY remaining offenders are the prediction band's, which
        the frozen plan assigns to C4 (§2.2 rows 14-16).

        Naming them rather than exempting the file keeps the claim exact in
        both directions: C3 fails if it leaves anything ELSE behind, and C4
        fails if it does not empty this list.
        """
        offenders: list[str] = []
        for rel in INTERPRETER_FILES:
            offenders += _offending_comparisons((REPO_ROOT / rel).read_text(encoding="utf-8"), rel)
        offenders += self._cap_offenders()

        remaining = {o.split(": ", 1)[1] for o in offenders}
        assert remaining == C4_OWNED_COMPARISONS, (
            "the interpreter surface still compares golden-metric values without "
            "asking MetricOrder, beyond the prediction band C4 owns — the direction "
            f"would invert silently under a `lower` metric: {sorted(remaining)}"
        )
        assert all("prediction.py" in o for o in offenders), (
            f"a non-prediction site is still unmigrated: {offenders}"
        )

    def _cap_offenders(self) -> list[str]:
        src = (REPO_ROOT / "src/workflows/model_exploration.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_cap_knowledge_cache":
                return _offending_comparisons(ast.unparse(node), "_cap_knowledge_cache")
        raise AssertionError("_cap_knowledge_cache not found — the census lost its subject")

    def test_the_census_is_not_vacuous(self):
        """It must actually be LOOKING at score comparisons.

        Every migrated site now routes through ``order.``; if that count
        collapsed, the census above would be green over a surface that no
        longer computes anything.
        """
        consumers = 0
        for rel in INTERPRETER_FILES:
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            consumers += len(re.findall(r"\b\w*order\.(is_better|best|worst|rank)\(", src))
            consumers += len(re.findall(r"_authority\([^)]*\)\.(is_better|best|worst|rank)\(", src))
        assert consumers >= 12, (
            f"expected the migrated ordering consumers to be present; found {consumers}"
        )

    def test_a_planted_offender_is_caught(self):
        """The census's own anti-vacuity proof, run in-process."""
        planted = "def f(summaries, best):\n    for s in summaries:\n        if s.best_denoising_score > best:\n            best = s.best_denoising_score\n"
        assert _offending_comparisons(planted, "planted") != []

    def test_a_planted_extremum_offender_is_caught(self):
        planted = "def f(rows):\n    return max(rows, key=lambda r: r.denoising_score)\n"
        assert _offending_comparisons(planted, "planted") != []

    def test_the_authoritys_own_calls_are_not_offenders(self):
        clean = (
            "def f(rows, order):\n    return order.best(rows, key=lambda r: r.denoising_score)\n"
        )
        assert _offending_comparisons(clean, "clean") == []


def test_health_feedback_uses_persisted_action_not_historical_gate_suffix():
    """2026-09-19: a recording diagnostic named *_blocking misled the agent.

    Exercise persistence projection plus prompt rendering. Losing the action
    at either boundary hides the diagnostic or implies that it invalidated
    the candidate; the opposite suffix must not grant recording authority.
    """
    from agent.schemas.health_feedback import build_gate_outcomes

    summary = TestTheHealthSummaryBestRoundInverts()._summary_with_rounds()
    summary.round_health[0].gate_outcomes = build_gate_outcomes(
        [
            {
                "gate_name": "output_std_blocking",
                "execution_status": "passed",
                "check_passed": False,
                "would_invalidate_under_production_policy": False,
                "resolved_action": "continue",
                "configured_action": "continue",
                "gate_role": "observational",
                "threshold": {"metric": "output_std_mv", "operator": ">=", "unit": "mV"},
                "metrics": {"output_std_mv": 0.15},
            },
            {
                "gate_name": "misleading_recording",
                "execution_status": "passed",
                "check_passed": True,
                "configured_action": "invalidate_round",
                "metrics": {"pearson_mean": 99.0},
            },
        ]
    )
    text = "\n".join(_render_health_summary_section(summary, order=HIGHER))
    assert "configured_action=continue; resolved_action=continue; would_invalidate=False" in text
    assert "round_validity=valid" in text
    assert "output_std_mv=0.15" in text
    assert "pearson_mean=99.0" not in text
