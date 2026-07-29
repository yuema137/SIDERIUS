"""The operator ordering override reaches every layer that locks or runs it.

Two failure modes this guards against, both silent until runtime:

1. **Lock collision.** The tuner, the workflow, and the chain runner all
   write the workspace's run-invariants lock. The override is part of that
   lock, so a site that omits it writes a contradictory lock and aborts the
   run with a RunInvariantsViolation. Caught during CB3-d authoring, when
   ``model_exploration.py`` still built a no-override lock while the tuner
   built one with the override.
2. **Sorted permutation.** ``DataScope.from_cli`` sorts and dedupes. Any
   layer that parses a file ORDER through it silently rewrites the
   operator's permutation into ascending order.
"""

import re
from pathlib import Path

import pytest

REPO = Path("/home/yuema137/SIDERIUS")

LOCK_SITES = [
    REPO / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
    REPO / "workflows/model_exploration.py",
    REPO / "sdsc_submission_scripts/run_one_iteration.py",
]

ORDER_PARSING_SITES = [
    REPO / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
    REPO / "sdsc_submission_scripts/run_one_iteration.py",
]


def _build_invariants_calls(source: str) -> list[str]:
    """Return the argument text of each build_run_invariants(...) call."""
    calls = []
    for match in re.finditer(r"build_run_invariants\(", source):
        start = match.end()
        depth = 1
        i = start
        while i < len(source) and depth:
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
            i += 1
        calls.append(source[start : i - 1])
    return calls


@pytest.mark.parametrize("path", LOCK_SITES, ids=lambda p: p.name)
def test_every_lock_site_passes_the_ordering_override(path):
    """A lock site that omits the override writes a contradictory lock, and
    the run dies on the next site's validation."""
    source = path.read_text()
    calls = _build_invariants_calls(source)
    assert calls, f"expected a build_run_invariants call in {path.name}"
    for call in calls:
        assert "ordering_override_strategy" in call, (
            f"{path.name} builds run invariants without the ordering override; "
            f"this workspace's lock would contradict the one written by the "
            f"other layers.\nCall args:\n{call}"
        )
        assert "ordering_override_file_order" in call, (
            f"{path.name} omits ordering_override_file_order from the lock."
        )


@pytest.mark.parametrize("path", ORDER_PARSING_SITES, ids=lambda p: p.name)
def test_file_order_is_never_parsed_through_datascope(path):
    """DataScope sorts; a visitation order must not be routed through it."""
    source = path.read_text()
    offenders = [
        line.strip()
        for line in source.splitlines()
        if "file_order" in line and "DataScope.from_cli" in line
    ]
    assert offenders == [], (
        f"{path.name} parses a file order through DataScope.from_cli, which "
        f"sorts and dedupes — the operator's permutation would be silently "
        f"rewritten into ascending order:\n" + "\n".join(offenders)
    )


def test_run_comparison_forwards_the_override_only_when_set():
    """Unset override must reproduce the pre-V19 tuner argv exactly."""
    source = (REPO / "scripts/run_comparison.py").read_text()
    assert '"--order_strategy_override", order_strategy_override' in source
    assert "if order_strategy_override is not None:" in source
    assert "if file_order_override is not None:" in source


def test_baseline_phase_does_not_receive_the_override():
    """The baseline is the frozen comparison anchor: its training stays on
    the pre-V19 global shuffle no matter what the agent phase is asked to do."""
    source = (REPO / "scripts/run_comparison.py").read_text()
    baseline_fn = source[source.index("def run_baseline_trial(") :]
    baseline_fn = baseline_fn[: baseline_fn.index("\ndef ")]
    assert "order_strategy" not in baseline_fn
    assert "file_order" not in baseline_fn
