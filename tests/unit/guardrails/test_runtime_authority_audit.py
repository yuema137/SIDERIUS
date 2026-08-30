"""C8f — mechanical audit: no runtime consumer decides authority privately.

The V19 wave-1 failure was an uncalibrated formula holding blocking
authority in a consumer. The architectural fix is that authority lives in
exactly ONE place (``RuntimeDecisionPolicy``), and every consumer asks it.
This test greps the four consumer surfaces for the shape of a private
runtime gate — a budget comparison whose result is used to block — so a
future edit that reintroduces one fails here rather than in a campaign.

Static formulas are NOT banned: they remain legitimate typed PRIOR
PRODUCERS. What is banned is a consumer turning a projection into a
verdict without the shared policy.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: (path, must import the shared policy) — the C8-rewired consumers.
CONSUMERS = [
    ("nodes/ml_model_proposal_agent/ml_model_proposal_agent.py", True),
    ("agent/skills/evaluate_time_skill/wrapper.py", True),
    ("core/sandbox_executor.py", False),
    ("core/runtime_control/watchdog_deadline.py", True),
]

POLICY_MARKERS = (
    "RuntimeDecisionPolicy",
    "MEASUREMENT_BACKED_SOURCES",
    "_runtime_policy",
    "_gate_decision",
)


def _source(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), f"consumer moved or renamed: {rel}"
    return path.read_text(encoding="utf-8")


def _code_only(rel: str) -> str:
    """Source with comments and docstrings removed.

    A banned PATTERN must be searched for in executable code only —
    otherwise documenting the ban trips the ban.
    """
    import io
    import tokenize

    source = _source(rel)
    kept: list[str] = []
    prev_type = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and prev_type in (
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.NEWLINE,
            tokenize.NL,
        ):
            continue  # docstring / bare string expression
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            prev_type = tok.type
        else:
            prev_type = tok.type
        kept.append(tok.string)
    return "\n".join(kept)


@pytest.mark.parametrize(("rel", "needs_policy"), CONSUMERS)
def test_consumer_resolves_the_shared_policy(rel: str, needs_policy: bool):
    """Every rewired consumer reaches the shared authority surface."""
    source = _source(rel)
    if needs_policy:
        assert any(marker in source for marker in POLICY_MARKERS), (
            f"{rel} no longer references the shared runtime authority — "
            "a consumer that decides runtime authority must go through "
            "RuntimeDecisionPolicy (§2.3 / §9-directive)"
        )


def test_timeeval_feasibility_is_derived_from_the_policy():
    """``feasible`` must be the policy's verdict, not a local comparison."""
    source = _source("agent/skills/evaluate_time_skill/wrapper.py")
    assert 'feasible = runtime_decision["kind"] != "REJECT"' in source, (
        "the TimeEval gate must derive feasibility from the shared policy "
        "decision; a direct `total_min <= budget` assignment to `feasible` "
        "is the pre-C8 private gate"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "feasible" for t in node.targets
        ):
            assert isinstance(node.value, ast.Compare), ast.dump(node.value)
            # the only permitted assignment compares the decision kind
            assert "runtime_decision" in ast.dump(node.value), (
                "found a `feasible = ...` assignment that does not come from the runtime decision"
            )


def test_proposer_cannot_reject_on_static_evidence():
    """The proposer's advisory path asserts the invariant at runtime."""
    source = _source("nodes/ml_model_proposal_agent/ml_model_proposal_agent.py")
    assert 'if decision.kind in ("REJECT", "ABORT")' in source
    assert "advisory-only invariant is broken" in source
    code = _code_only("nodes/ml_model_proposal_agent/ml_model_proposal_agent.py")
    assert "factor > 1.0" not in code, (
        "the private `factor > 1.0` proposal gate is back in EXECUTABLE code "
        "— the C1/C8 contract is that static evidence is advisory only"
    )


def test_watchdog_deadline_requires_measurement_backed_evidence():
    source = _source("core/runtime_control/watchdog_deadline.py")
    assert "def has_measured_prediction" in source
    assert 'prediction.get("source") in MEASUREMENT_BACKED_SOURCES' in source
    assert "if has_measured_prediction(component)" in source, (
        "the watchdog deadline must be derived only from measurement-backed "
        "component predictions (§7.4 watchdog column)"
    )


def test_no_second_authoritative_contention_classifier():
    """C8e: the count-based classifier must not come back alongside the
    windowed D3 one."""
    from core.runtime_control import probe

    assert not hasattr(probe, "classify_concurrency")
    source = _source("core/runtime_control/probe.py")
    assert "sample_contention_window" in source


def test_all_consumers_resolve_one_shared_policy_identity():
    """C8g closure: the proposer and the TimeEval gate must decide with the
    SAME policy object, resolved from the process-wide factory — not with
    two independently constructed equals that could drift apart."""
    from agent.skills.evaluate_time_skill import wrapper as time_wrapper
    from core.runtime_control.estimator import shared_runtime_components
    from nodes.ml_model_proposal_agent.ml_model_proposal_agent import _runtime_policy

    estimator, policy = shared_runtime_components()
    assert shared_runtime_components() is shared_runtime_components()  # one per process
    assert _runtime_policy() is policy

    gate = time_wrapper._gate_decision(
        result_shape={
            "status": "success",
            "estimated_minutes": 1.0,
            "breakdown": {"source": "static_uncalibrated"},
            "phase_breakdown": {},
            "inference_batch_uncalibrated": False,
        },
        effective_budget_minutes=10.0,
        runtime_phase="trial",
    )
    assert gate["policy_identity"] == policy.identity
    assert estimator.identity.startswith("runtime_estimator@")


def test_no_consumer_constructs_its_own_policy():
    """A private `RuntimeDecisionPolicy()` in a consumer is the divergence
    this closure removes; the factory is the only construction site."""
    for rel, _ in CONSUMERS:
        code = _code_only(rel)
        assert "RuntimeDecisionPolicy()" not in code, (
            f"{rel} constructs its own policy — resolve shared_runtime_components() instead (C8g)"
        )
