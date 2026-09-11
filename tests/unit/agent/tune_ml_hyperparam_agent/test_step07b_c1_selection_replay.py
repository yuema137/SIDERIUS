"""Step 07 PR 07b — C1 / CHECKPOINT 0: the selection · threshold · reflection replay oracle.

Design: ``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §5 (Checkpoint 0) and its C1 checklist.

**Captured against byte-unchanged production code**, before the first 07b
production edit, so that C2 (the ``MetricOrder`` rewire) and C3 (the
scale-rule classification) can prove — not assert by construction — that
under the shipped ``higher``-is-better TIDMAD metric every policy decision
is deep-equal to what the tuner did before 07b existed.

What has no oracle today, and therefore is captured here
--------------------------------------------------------
§0.4 of the design audited the repository for a checked-in ``all_records``
corpus and found none: the only committed ``run_output_*.json`` fixture
carries no records. So the awkward inputs the rewire is most likely to get
wrong — ``-inf`` / ``+inf`` / ``None`` / ``NaN`` scores, a penalised
collapse record that would read as *best* under a ``lower`` metric, an
invalid HealthGate candidate that outscores every valid one, a tie at the
extreme, a trial/formal mixture, a history with no successes at all — have
never been pinned against any of the five consumers 07b rewires.

Two capture routes, because the consumers live at two different seams
---------------------------------------------------------------------
* **gate helpers** (``_best_trial_winner``, ``_should_skip_formal``,
  ``_should_bypass_formal_time_budget``, ``_resolve_formal_comparison_thresholds``)
  are module-level functions — the corpus is driven through them DIRECTLY,
  every history × every gate scenario.
* **the reflection context and the five ``best_*`` tracks** are still inline
  inside ``run()`` at this commit (they become typed boundaries in C2), so
  they are captured through the real production path — one bounded pseudo
  tuner iteration — at the ``reflect()`` boundary and in the output. C2
  extracts them VERBATIM first and re-proves these same goldens before the
  authority rewire (design §17 finding 14: two evidence points inside C2).

This module is a tautology the day it lands. That is the point: it is the
guard for the next four commits, and it is worthless unless it predates the
edit it guards.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _best_trial_winner,
    _resolve_formal_comparison_thresholds,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
)
from tests.helpers.golden import assert_json_golden
from tests.helpers.metric_fixtures import accuracy_like_spec
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

HERE = Path(__file__).parent
GOLDENS = HERE / "goldens"
FIXTURES = HERE / "fixtures"
_CORPUS_PATH = FIXTURES / "sel1_histories.json"
_PREFLIGHT_FIXTURE = FIXTURES / "step00_preflight_results.json"
REPLAY_REQUIRED_GATE_IDS = frozenset({"output_diversity"})

# The corpus cases the design (§5 / C1 goal) requires. Hardcoded here rather
# than derived from the fixture: deriving the checklist from the thing it
# checks would pass for any corpus (CLAUDE.md, "never assert a value read
# back from the thing under test").
REQUIRED_CASE_IDS = (
    "h_empty",
    "h_simple_trials",
    "h_tie_first_wins",
    "h_none_score",
    "h_neg_inf",
    "h_pos_inf",
    "h_nan",
    "h_collapse_penalty",
    "h_invalid_candidate",
    "h_trial_formal_mix",
    # Step 07 correction (2026-08-16): was `h_time_mode_mismatch`, whose
    # expectation encoded the trial/time-budget coupling defect.
    "h_time_metadata_not_role",
    "h_no_successes",
)

# ``run()``'s AST branch-node count at the 07b implementation base
# (f17bbdb8), measured with the node set below. The design's Checkpoint A
# requires that 07b add SEQUENCING calls only — extracted boundaries and
# renderer calls, never a new policy branch inside the orchestrator
# (CLAUDE.md's responsibility-decomposition rule, and the 2,487-line
# pyright-ceiling incident that motivated it).
RUN_BRANCH_NODE_BASELINE = 244

_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.With,
    ast.BoolOp,
    ast.IfExp,
    ast.comprehension,
    ast.Assert,
    ast.Match,
    ast.match_case,
)

_SENTINELS = {
    "__neg_inf__": float("-inf"),
    "__pos_inf__": float("inf"),
    "__nan__": float("nan"),
}


def _decode(value):
    """Decode the fixture's non-finite sentinel strings, recursively."""
    if isinstance(value, str):
        return _SENTINELS.get(value, value)
    if isinstance(value, dict):
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _encode_float(value):
    """Project a possibly non-finite float back to a JSON-safe token."""
    if isinstance(value, float):
        if math.isnan(value):
            return "__nan__"
        if value == float("inf"):
            return "__pos_inf__"
        if value == float("-inf"):
            return "__neg_inf__"
    return value


@pytest.fixture(scope="module")
def corpus() -> dict:
    return _decode(json.loads(_CORPUS_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def pseudo_run(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("step07b_c1")
    try:
        output, bridge, sandbox, workspace = run_bounded_pseudo_iteration(
            tmp, mp, preflight_results=preflight
        )
    finally:
        mp.undo()
    return output, bridge, sandbox, workspace


# ---------------------------------------------------------------------------
# Corpus integrity
# ---------------------------------------------------------------------------


def test_corpus_covers_every_required_case(corpus):
    """Every awkward input class the design names is actually in the corpus.

    Fails when a case is dropped or renamed — the replay goldens would then
    still be green while covering less than Checkpoint 0 promised.
    """
    assert tuple(sorted(corpus["histories"])) == tuple(sorted(REQUIRED_CASE_IDS))
    for case_id in REQUIRED_CASE_IDS:
        assert corpus["histories"][case_id]["case"], f"{case_id} must name the case it exercises"


# ---------------------------------------------------------------------------
# Baseline 1 — the gate helpers, corpus-driven
# ---------------------------------------------------------------------------


def project_gate_helpers(corpus: dict, order: MetricOrder | None = None) -> dict:
    """Drive the gate helpers over the whole corpus, projected for JSON.

    ``order`` defaults to a neutral ``higher``-is-better fixture. At C1 the
    helpers took no order at all; from C2 they route through the run's one
    authority, and passing the shipped order here is precisely the replay
    claim: the production default must reproduce the pre-07b goldens byte for
    byte. The C2 rung passes the ``lower`` order to the same projection and
    asserts the inversion against separate expectations.
    """
    order = order or MetricOrder(accuracy_like_spec())
    projected: dict = {"winners": {}, "gates": {}, "thresholds": {}}

    for case_id, case in sorted(corpus["histories"].items()):
        records = case["records"]
        winner = _best_trial_winner(
            records,
            order=order,
            required_gate_ids=REPLAY_REQUIRED_GATE_IDS,
        )
        projected["winners"][case_id] = {
            "exp_id": winner["exp_id"] if winner else None,
            "denoising_score": _encode_float(winner["denoising_score"]) if winner else None,
        }
        per_case: dict = {}
        for scenario in corpus["gate_scenarios"]["cases"]:
            per_case[scenario["id"]] = {
                "skip": _should_skip_formal(
                    winner,
                    threshold=scenario["threshold"],
                    gates_enabled=scenario["gates_enabled"],
                    order=order,
                ),
                "bypass": _should_bypass_formal_time_budget(
                    winner, threshold=scenario["threshold"], order=order
                ),
            }
        projected["gates"][case_id] = per_case

    for scenario in corpus["threshold_scenarios"]["cases"]:
        reference, skip_threshold, bypass_threshold, source = _resolve_formal_comparison_thresholds(
            reference_score=scenario["reference_score"],
            skip_min_delta=scenario["skip_min_delta"],
            bypass_min_delta=scenario["bypass_min_delta"],
            gates_enabled=scenario["gates_enabled"],
            order=order,
        )
        projected["thresholds"][scenario["id"]] = {
            "reference": _encode_float(reference),
            "skip_threshold": _encode_float(skip_threshold),
            "bypass_threshold": _encode_float(bypass_threshold),
            "source": source,
        }

    return projected


def test_gate_helper_replay(corpus):
    """SEL-1a: winner / skip / bypass / threshold resolution over the corpus."""
    assert_json_golden(
        project_gate_helpers(corpus),
        GOLDENS / "sel1_gate_helpers.json",
        surface="SEL-1a gate-helper replay (07b Checkpoint 0)",
    )


# ---------------------------------------------------------------------------
# Baseline 2 — the reflection context, through the real reflect() boundary
# ---------------------------------------------------------------------------


def project_reflection_contexts(bridge) -> list:
    """Every ``reflection_context`` the production path handed the reflector."""
    return [
        {k: _encode_float(v) for k, v in sorted(call[4].items())}
        for call in bridge.calls
        if call[0] == "reflect"
    ]


def test_reflection_context_replay(pseudo_run):
    """SEL-1b: the reflector's best/rank/band/new-best values, verbatim.

    ``best_score_so_far``, ``rank``, ``is_new_best`` and ``is_more_efficient``
    are exactly the values C2 rewires through the order authority and C3
    re-derives through the range-normalised band; a golden captured from the
    real call site is the only thing that can tell a faithful rewire from a
    plausible-looking one.
    """
    _output, bridge, _sandbox, _ws = pseudo_run
    assert_json_golden(
        {"contexts": project_reflection_contexts(bridge)},
        GOLDENS / "sel1_reflection_context.json",
        surface="SEL-1b reflection context replay (07b Checkpoint 0)",
    )


# ---------------------------------------------------------------------------
# Baseline 3 — the five best_* finalization tracks, from the output
# ---------------------------------------------------------------------------

_BEST_TRACK_FIELDS = (
    "best_exp_id",
    "best_denoising_score",
    "best_formal_denoising_score",
    "best_valid_exp_id",
    "best_valid_denoising_score",
    "best_valid_formal_exp_id",
    "best_valid_formal_denoising_score",
    "best_valid_trial_exp_id",
    "best_valid_trial_denoising_score",
)


def project_best_tracks(output) -> dict:
    return {field: _encode_float(getattr(output, field)) for field in _BEST_TRACK_FIELDS}


def test_best_tracks_replay(pseudo_run):
    """SEL-1c: all five ``best_*`` finalization tracks of the bounded run."""
    output, _bridge, _sandbox, _ws = pseudo_run
    assert_json_golden(
        project_best_tracks(output),
        GOLDENS / "sel1_best_tracks.json",
        surface="SEL-1c best_* finalization tracks (07b Checkpoint 0)",
    )


# ---------------------------------------------------------------------------
# Baseline 4 — run() must not grow a policy branch
# ---------------------------------------------------------------------------


def count_run_branch_nodes() -> int:
    """AST branch-node count of ``HyperparamTuningAgent.run``."""
    source = (
        Path(__file__).resolve().parents[4]
        / "src/nodes"
        / "ml_hyperparameter_tune_agent"
        / "ml_hyperparameter_tune_agent.py"
    ).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "HyperparamTuningAgent":
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == "run":
                    return sum(1 for n in ast.walk(member) if isinstance(n, _BRANCH_NODES))
    raise AssertionError("HyperparamTuningAgent.run not found")


def test_run_branch_count_not_increased():
    """07b adds sequencing calls to ``run()``, never a new policy branch.

    Fails the moment a commit puts an ``if``/loop/comprehension for the new
    policy inside the orchestrator instead of behind an extracted boundary.
    """
    assert count_run_branch_nodes() <= RUN_BRANCH_NODE_BASELINE, (
        "run() gained branching — 07b authorises sequencing calls only "
        f"(baseline {RUN_BRANCH_NODE_BASELINE} at f17bbdb8)"
    )


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
