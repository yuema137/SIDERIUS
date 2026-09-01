"""Step 06 — C5: the boundary and the "declared once" property, executable.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§3, §7, §11 (structural guard), §16-Q6, §19 C5.

Three properties, each with the defect only it catches:

* **The loss boundary** is executable from C1 onward
  (``test_step06_c1_evaluation_metric.py`` §3: loss-shaped identities refused
  on every metric type, ``loss_history`` refused under any key, no loss field
  structurally). Not duplicated here; referenced.
* **Declared exactly once.** The compatibility metric identity and the metric
  DIRECTION vocabulary live in ONE executed constant each, in the metric
  module. A second executed ``"tidmad_denoising_score"`` or a stray
  ``"higher"``/``"lower"`` literal anywhere in production is a second
  authority that a rename or a direction flip would leave behind (05c's
  "declared exactly once" pattern, AST over executed constants, docstrings
  excluded).
* **The D1 not-reached list is ASSERTED, not merely written** (§16-Q6). The
  direction consumers Step 06 does not reach still hold their literal
  comparisons — so the list cannot drift silently, and nobody can later claim
  the metric handle "covers" a consumer it never touched. If one of these
  goes red, someone migrated a consumer: record it as reached (Step 07a / D1),
  do not silence the guard.

**Step 07 PR 07b did exactly that** for the four tuner rows: they moved from
``NOT_REACHED_DIRECTION_CONSUMERS`` to ``MIGRATED_TO_THE_ORDER_AUTHORITY``,
where the assertion is inverted — the hardcoded comparison must now be
ABSENT and ``MetricOrder`` present. The D1 rows (chain / resume /
per_file_best / dashboard) are still debt and still hold their literals.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.scripts.test_step05c_c6_launcher_reconstruction import (
    _executed_string_constants,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_DIRS = (
    "nodes",
    "agent",
    "core",
    "execute_tools",
    "ml_models",
    "workflows",
    "scripts",
    "dashboard",
)
METRIC_MODULE = "execute_tools/evaluation_metric.py"
#: Step 07 PR 07b added the ONE order authority. It is the only production
#: module besides the metric module that may execute a direction literal,
#: because interpreting ``MetricSpec.direction`` is precisely its job — and
#: doing it in exactly one place is the property 07b bought. Every consumer
#: asks this module instead of re-deriving the convention.
ORDER_MODULE = "execute_tools/metric_order.py"


def _production_files():
    for d in PRODUCTION_DIRS:
        yield from sorted((REPO_ROOT / d).rglob("*.py"))


def _executed(path: Path) -> list[str]:
    return _executed_string_constants(path.read_text(encoding="utf-8", errors="ignore"))


# ---------------------------------------------------------------------------
# 1. Declared exactly once — identity
# ---------------------------------------------------------------------------


def test_the_tidmad_metric_identity_is_declared_in_exactly_one_executed_constant():
    """``per_file_best`` (the pre-Step-06 precedent) now IMPORTS the identity
    from the metric module; its emitted value and key set are unchanged
    (NUM-8 golden). Two literals would let a rename move one and not the
    other — the drift the interface exists to remove."""
    hits = {
        p.relative_to(REPO_ROOT).as_posix(): [
            s for s in _executed(p) if s == "tidmad_denoising_score"
        ]
        for p in _production_files()
    }
    hits = {k: v for k, v in hits.items() if v}
    assert hits == {METRIC_MODULE: ["tidmad_denoising_score"]}, hits


def test_per_file_best_emits_the_precedent_identity_only_when_it_is_declared():
    """UPGRADED (per-file-best identity fix).

    The original test asserted that ``per_file_best`` emits TIDMAD's identity
    "through the import" — and it did, unconditionally, as a literal imported
    from the metric module. That made the artifact stamp TIDMAD's identity onto
    every task's run; a composed California-housing run (metric ``mae``) wrote
    ``metric_id: "tidmad_denoising_score"``.

    The precedent identity is still emitted for TIDMAD, but now because the
    committed artifacts DECLARE it. The C5 boundary property this test exists
    to protect — the module never executes the identity as a literal — is
    unchanged and still asserted.
    """
    import tempfile

    from execute_tools.evaluation_metric import TIDMAD_METRIC_ID
    from execute_tools.per_file_best import build_table
    from tests.unit.core.test_step00_resume_replay import stage_workspace
    from tests.unit.execute_tools.test_per_file_best import _record, _write_iter

    # Declared: resolution reproduces the precedent identity.
    declared_ws = str(Path(tempfile.mkdtemp(prefix="step06_c5_declared_")) / "ws")
    _write_iter(
        declared_ws,
        1,
        [_record("a", file_vector=[1.0, 2.0] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    assert build_table(declared_ws)["metric_id"] == "tidmad_denoising_score" == TIDMAD_METRIC_ID

    # Undeclared (RES-1 holds zero records and no stamped spec): a named
    # absence, never the precedent identity as a default.
    ws = stage_workspace(Path(tempfile.mkdtemp(prefix="step06_c5_")))
    assert build_table(str(ws))["metric_id"] is None

    assert "tidmad_denoising_score" not in _executed(
        REPO_ROOT / "execute_tools" / "per_file_best.py"
    )


# ---------------------------------------------------------------------------
# 2. Declared exactly once — direction; no executed hardcoded direction where
#    the handle is available
# ---------------------------------------------------------------------------


def test_no_production_surface_executes_a_direction_literal_outside_the_metric_module():
    """The owned scoring surfaces (tuner live route, ``TidmadSandbox``, the
    scorer CLI) and every other production module read direction from the
    handle or not at all.

    TWO modules name it, and the split is the architecture: the metric module
    DECLARES the vocabulary (``MetricDirection``); the
    order module (Step 07 PR 07b) INTERPRETS it. Anything else executing
    ``"higher"``/``"lower"`` is a third authority that a direction flip would
    leave behind — which is the entire defect 07b removed from 21 tuner sites.
    """
    offenders = {}
    for p in _production_files():
        rel = p.relative_to(REPO_ROOT).as_posix()
        found = [s for s in _executed(p) if s in ("higher", "lower")]
        if rel == METRIC_MODULE:
            # Literal["higher", "lower"] is the complete direction vocabulary.
            # Scientific metric values are task declarations, not framework
            # constants.
            assert sorted(found) == ["higher", "lower"], found
            continue
        if rel == ORDER_MODULE:
            # Five executed literals, all in one place on purpose:
            #   `_HIGHER = "higher"`            — the single comparison every
            #                                     ordering decision derives from;
            #   `direction_words`               — comparative ("higher"/"lower")
            #                                     and antonym ("lower"/"higher"),
            #                                     for prose that must STATE the
            #                                     direction rather than apply it.
            # Pinned as an exact multiset, not merely "non-empty": the guard's
            # job is that no THIRD module reads the declaration, and an unpinned
            # allowance here would let this one quietly grow into a second
            # authority — the very thing it exists to prevent.
            assert sorted(found) == ["higher", "higher", "higher", "lower", "lower"], found
            continue
        if found:
            offenders[rel] = found
    assert offenders == {}, offenders


# ---------------------------------------------------------------------------
# 3. The D1 not-reached list — asserted (§16-Q6)
# ---------------------------------------------------------------------------

# Each entry: (file, exact executed comparison that encodes higher-is-better).
# These are NOT Step 06's; they are Step 07a (tuner incumbent selection) and
# D1 (workflow / resume / per_file_best / dashboard) debt, enumerated so the
# claim "the handle reaches only the live scoring route + record payload" is
# checkable, and so migrating one of them is a visible, recorded act.
NOT_REACHED_DIRECTION_CONSUMERS = (
    # D1 — chain / resume / artifacts / dashboard
    #
    # The `workflows/model_exploration.py` row that stood here was RETIRED by
    # Step 10 P2a C1, which routed the workflow's raw-formal best tracker, the
    # chain formal incumbent advance and the `target_score` early stop through
    # `MetricOrder`. Per this file's own rule it moved to
    # MIGRATED_TO_THE_ORDER_AUTHORITY rather than being deleted, so the
    # migration leaves a trace.
    # The `core/resume.py` and `execute_tools/per_file_best.py` rows that stood
    # here were RETIRED by Step 10 P2a C2, which routed `_pick_best`, the
    # chain-level incumbent fold and `_row_beats` through `MetricOrder`. Both
    # moved to MIGRATED_TO_THE_ORDER_AUTHORITY rather than being deleted.
    # The two `dashboard/` rows that stood here were RETIRED by Step 10 P2a
    # C3, which routed the leaderboard sort and the best_agent_score scan
    # through MetricOrder and replaced the "higher is better" prose with
    # direction-aware wording. Both moved to MIGRATED_TO_THE_ORDER_AUTHORITY.
    #
    # This tuple is now EMPTY: every D1 direction consumer Step 06 enumerated
    # as out of reach has been reached. It is kept rather than deleted so the
    # parametrized guard below still names the concept, and so a future
    # unmigrated consumer has an obvious home.
)


@pytest.mark.parametrize("relative, literal", NOT_REACHED_DIRECTION_CONSUMERS)
def test_the_not_reached_direction_consumers_still_hold_their_literal(relative, literal):
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert literal in source, (
        f"{relative} no longer contains {literal!r}: a direction consumer Step 06 listed as "
        f"NOT reached has changed — record it as reached (Step 07a / D1) rather than "
        f"silencing this guard"
    )


# ---------------------------------------------------------------------------
# 3b. MIGRATED (Step 07 PR 07b) — recorded as reached, per this file's own rule
# ---------------------------------------------------------------------------

# The four tuner entries above were Step 06's "not reached" debt. PR 07b
# migrated them to ``MetricOrder``; per the docstring's instruction they are
# RECORDED AS REACHED rather than deleted, and the guard is inverted — the
# literal must now be ABSENT. Deleting the rows instead would have left no
# evidence that the migration happened, which is the drift §16-Q6 was written
# to prevent.
MIGRATED_TO_THE_ORDER_AUTHORITY = (
    (
        "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
        'max(candidates, key=lambda r: r["denoising_score"])',
    ),
    (
        "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
        'max(successful, key=lambda r: r["denoising_score"]) if successful else None',
    ),
    (
        "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
        'max(successful_records, key=lambda r: r["denoising_score"])',
    ),
    (
        "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
        "current_score > best_score",
    ),
    # --- Step 09a C3: the INTERPRETER surface, same rule, same evidence ---
    # One literal per migrated site family. Recorded as reached rather than
    # deleted, so the migration leaves a trace that a later edit cannot
    # silently undo.
    (
        "nodes/result_interpretation_agent/ordering.py",
        "s.best_denoising_score > current_best",
    ),
    (
        "nodes/result_interpretation_agent/ordering.py",
        "s.worst_denoising_score < current_worst",
    ),
    (
        "nodes/result_interpretation_agent/ordering.py",
        "best > overall_best_score",
    ),
    (
        "nodes/result_interpretation_agent/evidence.py",
        "max(valid_records, key=_required_denoising_score)",
    ),
    (
        "nodes/result_interpretation_agent/evidence.py",
        "min(valid_scores)",
    ),
    (
        "nodes/interpretation_helpers.py",
        "scored.sort(key=lambda x: (-x[1], x[0]))",
    ),
    (
        "nodes/interpretation_helpers.py",
        "max(sota_from_prediction, overall_best_score)",
    ),
    (
        "nodes/interpretation_helpers.py",
        "best_score > sota_score * 0.95",
    ),
    (
        "workflows/model_exploration.py",
        'scored.sort(key=lambda x: x[1] if x[1] is not None else float("-inf"), reverse=True)',
    ),
    # --- Step 10 P2a C1: the live-workflow surface (sites 1-3) ---
    # The raw-formal best tracker, the chain formal incumbent advance and the
    # `target_score` early stop. All three now acquire ONE reconciled
    # `MetricOrder` per iteration and ask it; the first of these is the row
    # that moved out of NOT_REACHED_DIRECTION_CONSUMERS above.
    (
        "workflows/model_exploration.py",
        "tune_output.best_formal_denoising_score > state.best_score_overall",
    ),
    (
        "workflows/model_exploration.py",
        "_iter_valid_formal > state.chain_formal_incumbent_reference",
    ),
    (
        "workflows/model_exploration.py",
        "state.best_score_overall >= launch.target_score",
    ),
    # --- Step 10 P2a C2: resume selection and per-file best ---
    # `_pick_best` and `_row_beats` now take a keyword-only `MetricOrder`, and
    # the chain-level incumbent fold (found by the P2a scanner, absent from the
    # frozen site table) asks the same authority.
    ("core/resume.py", "if score > best_score or ("),
    ("core/resume.py", 'or formal_cand["score"] > state.chain_best_valid_formal_score'),
    ("core/resume.py", 'or trial_cand["score"] > state.chain_best_trial_score'),
    ("execute_tools/per_file_best.py", "return new.best_linear > current.best_linear"),
    # --- Step 10 P2a C3: the persisted-artifact consumers ---
    # The dashboard and the two diagnostic scripts now read the direction from
    # each record's persisted metric identity. The prose row is here too: it
    # stated a direction that was only ever true of TIDMAD.
    (
        "dashboard/data_sources/local_json.py",
        'entries.sort(key=lambda e: e["denoising_score"], reverse=True)',
    ),
    ("dashboard/data_sources/base.py", "ranked by denoising_score descending (higher is better)"),
    (
        "scripts/build_diagnostic_summary.py",
        'max(valid, key=lambda record: record["denoising_score"])',
    ),
    (
        "scripts/finalize_recovered_diagnostic_round.py",
        'max(valid, key=lambda item: item["denoising_score"])',
    ),
)


#: How each migrated consumer REACHES the order authority.
#:
#: Most name ``MetricOrder`` directly. Step 10 P2a C3's persisted-artifact
#: consumers reach it through ``execute_tools/persisted_ranking.py``, the one
#: shared composer that reconciles a corpus's declared identity and hands the
#: result to ``MetricOrder`` — written once rather than three times, because
#: three copies of a fail-closed rule are three chances for one to stop
#: failing. The marker is per row so "reaches the authority" stays an
#: ASSERTED property rather than becoming an unchecked exemption.
_AUTHORITY_MARKERS: dict[str, str] = {
    "dashboard/data_sources/local_json.py": "persisted_ranking",
    "scripts/build_diagnostic_summary.py": "persisted_ranking",
    "scripts/finalize_recovered_diagnostic_round.py": "persisted_ranking",
    # A prose-only row: an abstract method's docstring, which names no
    # authority because it executes nothing. What must be true of it is that
    # it no longer STATES a fixed direction — asserted below by the absence of
    # its old literal, and positively by the C3 prose test.
    "dashboard/data_sources/base.py": "metric identity",
}


@pytest.mark.parametrize("relative, literal", MIGRATED_TO_THE_ORDER_AUTHORITY)
def test_the_migrated_consumers_no_longer_hold_their_literal(relative, literal):
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert literal not in source, (
        f"{relative} still contains {literal!r}: this consumer was routed through "
        f"MetricOrder (tuner: Step 07 PR 07b; interpreter: Step 09a C3; "
        f"chain/resume/artifacts: Step 10 P2a), so the hardcoded "
        f"higher-is-better comparison must be gone"
    )
    marker = _AUTHORITY_MARKERS.get(relative, "MetricOrder")
    assert marker in source, (
        f"{relative} no longer reaches the order authority via {marker!r} — a "
        f"migrated consumer that stops consulting it has silently regained the "
        f"freedom to assume a direction"
    )
