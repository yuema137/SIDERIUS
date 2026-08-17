"""Step 06 — C5: the boundary and the "declared once" property, executable.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§3, §7, §11 (structural guard), §16-Q6, §19 C5.

Three properties, each with the defect only it catches:

* **The loss boundary** is executable from C1 onward
  (``test_step06_c1_evaluation_metric.py`` §3: loss-shaped identities refused
  on every metric type, ``loss_history`` refused under any key, no loss field
  structurally). Not duplicated here; referenced.
* **Declared exactly once.** The TIDMAD metric identity and the metric
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


def test_per_file_best_still_emits_the_precedent_identity_through_the_import():
    import tempfile

    from execute_tools.evaluation_metric import TIDMAD_METRIC_ID
    from execute_tools.per_file_best import build_table
    from tests.unit.core.test_step00_resume_replay import stage_workspace

    ws = stage_workspace(Path(tempfile.mkdtemp(prefix="step06_c5_")))
    table = build_table(str(ws))
    assert table["metric_id"] == "tidmad_denoising_score" == TIDMAD_METRIC_ID
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
    DECLARES the vocabulary (``MetricDirection``) and TIDMAD's value; the
    order module (Step 07 PR 07b) INTERPRETS it. Anything else executing
    ``"higher"``/``"lower"`` is a third authority that a direction flip would
    leave behind — which is the entire defect 07b removed from 21 tuner sites.
    """
    offenders = {}
    for p in _production_files():
        rel = p.relative_to(REPO_ROOT).as_posix()
        found = [s for s in _executed(p) if s in ("higher", "lower")]
        if rel == METRIC_MODULE:
            # Literal["higher", "lower"] (vocabulary) + direction="higher" (TIDMAD).
            assert sorted(found) == ["higher", "higher", "lower"], found
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
    (
        "workflows/model_exploration.py",
        "tune_output.best_formal_denoising_score > best_score_overall",
    ),
    ("core/resume.py", "if score > best_score or ("),
    ("execute_tools/per_file_best.py", "return new.best_linear > current.best_linear"),
    (
        "dashboard/data_sources/local_json.py",
        'entries.sort(key=lambda e: e["denoising_score"], reverse=True)',
    ),
    ("dashboard/data_sources/base.py", "ranked by denoising_score descending (higher is better)"),
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
)


@pytest.mark.parametrize("relative, literal", MIGRATED_TO_THE_ORDER_AUTHORITY)
def test_the_migrated_tuner_consumers_no_longer_hold_their_literal(relative, literal):
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert literal not in source, (
        f"{relative} still contains {literal!r}: Step 07 PR 07b routed this consumer through "
        f"MetricOrder, so the hardcoded higher-is-better comparison must be gone"
    )
    assert "MetricOrder" in source
