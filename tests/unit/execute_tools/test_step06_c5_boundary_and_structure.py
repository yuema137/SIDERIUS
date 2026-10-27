"""Metric identity and direction retain one production authority.

Behavioral consumer coverage lives in the ordering scanner, tuner/interpreter
order-consumer tests, and workflow reconciliation/resume/persisted-consumer tests.
Completed migration string ledgers are not a runtime contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_DIRS = (
    "src/nodes",
    "src/agent",
    "src/core",
    "src/execute_tools",
    "src/ml_models",
    "src/workflows",
    "scripts",
    "src/dashboard",
)
METRIC_MODULE = "src/execute_tools/evaluation_metric.py"
#: Step 07 PR 07b added the ONE order authority. It is the only production
#: module besides the metric module that may execute a direction literal,
#: because interpreting ``MetricSpec.direction`` is precisely its job — and
#: doing it in exactly one place is the property 07b bought. Every consumer
#: asks this module instead of re-deriving the convention.
ORDER_MODULE = "src/execute_tools/metric_order.py"


def _production_files():
    for d in PRODUCTION_DIRS:
        yield from sorted((REPO_ROOT / d).rglob("*.py"))


def _executed_string_constants(source: str) -> list[str]:
    """Return executed string literals while excluding module docstrings."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


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
        REPO_ROOT / "src/execute_tools" / "per_file_best.py"
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
