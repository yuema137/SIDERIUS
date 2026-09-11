"""Step 12 / PR-12d — the task-owned route evaluates the DECLARED secondaries.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §I (the `G-12d` PASS lists), ruling
A2-b.

Three defects, all found by running the SHIPPED compositions through a real
scoring child rather than through a fixture written for the new call
convention. Each is asserted here as the property it violated.

* **F-12d-18** — no composed run evaluated ANY secondary metric.
  ``_evaluate_secondary_metrics`` has exactly one call site, inside the
  tuner's ``ScoringRoute.ANCHOR_NORMALIZED`` branch, and every composed
  contrast run takes ``TASK_OWNED``. So `macro_f1`, `log_loss`, `psnr` and
  `mae` were declared, composed, and never computed.
* **F-12d-19** — the shipped primaries could not accept the composed call.
  ``AccuracyMetric``/``GlobalMseMetric`` take ``predictions``/``truth``
  already assembled; the child owns ``evaluation_payload``/``task_scope``/
  ``data_dir``.
* **F-12d-20** — the generic call passed the DELIVERABLE directory as
  ``data_dir``, where the physical data root arrives as ``--raw_data_dir``.

The end-to-end witnesses live in `G-12d`; what is asserted here is the
structure that made each defect possible.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CHILD = REPO_ROOT / "src/execute_tools" / "denoising_score_single.py"
TUNER_EXEC = REPO_ROOT / "src/nodes" / "ml_hyperparameter_tune_agent" / "execution.py"


def _fn(path: pathlib.Path, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


# ======================================================================
# F-12d-18 — the route evaluates secondaries at all
# ======================================================================


class TestTheTaskOwnedRouteEvaluatesSecondaries:
    def test_the_child_evaluates_them_because_the_tuner_cannot(self):
        """Reachability, and the reason it must be the CHILD.

        On this route the deliverable is read by the child, so the child is
        the only party holding the evaluation payload and the scope. A tuner
        that "also" evaluated them would need a second reader.
        """
        source = CHILD.read_text(encoding="utf-8")
        assert "_evaluate_task_owned_secondaries(" in source
        emit = _fn(CHILD, "_emit_task_owned_score")
        called = {
            node.func.id
            for node in ast.walk(emit)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_evaluate_task_owned_secondaries" in called

    def test_the_tuner_still_evaluates_them_on_the_ANCHOR_route(self):
        """The in-process route is untouched — this is additive, not a move."""
        source = TUNER_EXEC.read_text(encoding="utf-8")
        assert "_evaluate_secondary_metrics(" in source
        assert "if _scoring_route is ScoringRoute.ANCHOR_NORMALIZED:" in source

    def test_the_child_composes_them_through_the_SAME_authority_as_the_primary(self):
        """No re-derivation: a child asks the composition layer what was declared."""
        fn = _fn(CHILD, "_compose_child_secondary_metrics")
        body = ast.unparse(fn)
        assert "compose_run_task_bindings" in body
        assert "secondary_metrics" in body

    def test_the_frozen_catch_ORDER_lives_in_the_SHARED_owner(self):
        """UPGRADED: the taxonomy was EXTRACTED, not duplicated (post-D8a).

        `_evaluate_task_owned_secondaries` no longer has its OWN try/except —
        it delegates to `evaluate_declared_secondaries`
        (`execute_tools/evaluation_metric.py`), the single owner both this
        route and the tuner's in-process ANCHOR route call. This closes the
        twinning hazard `test_the_secondary_evaluator_has_exactly_one_owner`
        (Step 09a C6) caught when this child first grew its own copy.

        `ScopeViolationError` subclasses `ValueError`, so ORDER is the
        contract: it must be caught BEFORE the generic clause and RE-RAISED.
        """
        from execute_tools.evaluation_metric import evaluate_declared_secondaries

        fn = ast.parse(inspect.getsource(evaluate_declared_secondaries)).body[0]
        handlers = [
            ast.unparse(h.type) if h.type is not None else "bare"
            for node in ast.walk(fn)
            if isinstance(node, ast.Try)
            for h in node.handlers
        ]
        assert handlers == ["NotScoreableError", "ScopeViolationError", "Exception"], handlers
        scope_handler = next(
            h
            for node in ast.walk(fn)
            if isinstance(node, ast.Try)
            for h in node.handlers
            if h.type is not None and ast.unparse(h.type) == "ScopeViolationError"
        )
        assert any(isinstance(stmt, ast.Raise) for stmt in scope_handler.body), (
            "a ScopeViolationError from a secondary must be RE-RAISED, not recorded"
        )

    def test_the_child_calls_the_shared_owner_rather_than_its_own_copy(self):
        """Reachability: the DELEGATION, not just the shared function's existence."""
        fn = _fn(CHILD, "_evaluate_task_owned_secondaries")
        assert not any(isinstance(node, ast.Try) for node in ast.walk(fn)), (
            "the child must not carry its own copy of the taxonomy"
        )
        called = {
            node.func.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "evaluate_declared_secondaries" in called

    def test_a_run_declaring_NO_secondaries_writes_no_key(self):
        """§4.7's semantic-emptiness rule, one route further along.

        A composed run with no declared secondaries must produce the same
        output payload it always did — no empty lists, no empty dict.
        """
        fn = _fn(CHILD, "_evaluate_task_owned_secondaries")
        returns = [ast.unparse(n.value) for n in ast.walk(fn) if isinstance(n, ast.Return)]
        assert "{}" in returns, "the no-secondaries case must return an empty mapping"
        emit = _fn(CHILD, "_emit_outcome")
        assert "if secondaries:" in ast.unparse(emit), (
            "the payload must be extended only when non-empty"
        )


# ======================================================================
# F-12d-19 — framework metrics retain their in-process vocabulary
# ======================================================================


class TestFrameworkMetricVocabulary:
    def test_the_FRAMEWORK_metrics_are_deliberately_left_alone(self):
        """They are the right shape for the in-process D14 runners.

        Changing their signature would have been the alternative fix and the
        wrong one: those runners assemble truth themselves and hand it over,
        which is what an in-process caller should do.
        """
        import inspect

        from execute_tools.evaluation_metric import AccuracyMetric, GlobalMseMetric

        for cls in (AccuracyMetric, GlobalMseMetric):
            params = set(inspect.signature(cls._compute).parameters)
            assert {"predictions", "truth"} <= params
            assert "evaluation_payload" not in params


# ======================================================================
# F-12d-20 — data_dir is the PHYSICAL root, not the deliverable dir
# ======================================================================


class TestTheGenericCallPassesThePhysicalDataRoot:
    def test_the_child_passes_raw_data_dir_as_data_dir(self):
        """The Step-11 distinction, asserted at the one site that conflated it.

        In the SCORING child ``--data_dir`` is the DELIVERABLE directory and
        the physical root arrives as ``--raw_data_dir``
        (`core/sandbox_executor.py:894`). A disk-backed metric would otherwise
        search below the workspace rather than the declared physical root.

        Fails when someone "simplifies" this back to ``args.data_dir``, which
        reads correctly and is wrong.
        """
        fn = _fn(CHILD, "_emit_task_owned_score")
        body = ast.unparse(fn)
        assert "'data_dir': args.raw_data_dir" in body or '"data_dir": args.raw_data_dir' in body
        assert "'data_dir': args.data_dir" not in body


# ======================================================================
# The record carries them, whichever route ran
# ======================================================================


class TestTheRecordHasOneShapeRegardlessOfRoute:
    def test_the_adoption_helper_is_TOTAL_so_the_caller_gains_no_branch(self):
        """§E.2's zero-net-growth budget, met by extraction not restraint.

        The precedence — anything already evaluated wins — lives inside the
        helper, so a child reporting none can never blank an anchor-route
        result, and the 27-branch orchestrator gains nothing.
        """
        fn = _fn(TUNER_EXEC, "_adopt_child_secondaries")
        body = ast.unparse(fn)
        assert "if results or refusals or errors:" in body
        # `ast.unparse` parenthesizes a bare tuple return, so compare against
        # what it emits rather than against the source spelling.
        assert "return (results, refusals, errors)" in body

    def test_the_child_values_are_VALIDATED_not_construct_shortcut(self):
        """They crossed a process boundary as JSON.

        `model_construct` would produce a half-typed record from a malformed
        entry; `model_validate` fails loudly instead.
        """
        fn = _fn(TUNER_EXEC, "_adopt_child_secondaries")
        body = ast.unparse(fn)
        assert "MetricResult.model_validate" in body
        assert "NotScoreableResult.model_validate" in body
        # Strip the docstring before the negative check: it MENTIONS
        # `model_construct` to say why it is not used, and a naive `not in`
        # over the whole function matched that prose. A negative assertion
        # that can be satisfied by a comment is not an assertion.
        executable = ast.unparse(ast.Module(body=fn.body[1:], type_ignores=[]))
        assert "model_construct" not in executable


class TestARETURNEDRefusalIsNotRecordedAsAScore:
    """F-12d-33 — the two shapes a secondary refusal arrives in.

    `EvaluationMetric.evaluate` declares
    ``MetricOutcome = MetricResult | NotScoreableResult`` and RETURNS the
    refusal. The anchor route never sees that shape, because
    `sandbox.evaluate_metric` converts it into a raised `NotScoreableError`.
    The TASK-OWNED route calls `secondary.evaluate(...)` directly, so the
    refusal comes back as a return value — and `evaluate_declared_secondaries`
    appended it straight into `results`, where `model_dump()` serialized a
    contract REFUSAL into `secondary_metric_results` as though a score had
    been produced.

    Found by CI pyright, not by any test: the callback was annotated
    `-> MetricResult` while the real callable returns the union. A type error
    that was also a semantic one.
    """

    def _refusal(self):
        from execute_tools.evaluation_metric import (
            NotScoreableResult,
            ScoreabilityFailure,
            ScoreabilityVerdict,
        )

        # A REAL refusal: the schema refuses an empty-failure verdict, because
        # "not scoreable with no failures" would be a scoreable verdict.
        return NotScoreableResult(
            metric_id="macro_f1",
            direction="higher",
            verdict=ScoreabilityVerdict(
                contract_id="presence",
                failures=[
                    ScoreabilityFailure(
                        requirement="deliverable_present",
                        input_identity=0,
                        detail="fixture refusal",
                    )
                ],
            ),
        )

    def test_a_returned_refusal_lands_in_refusals_not_results(self):
        from execute_tools.evaluation_metric import evaluate_declared_secondaries

        refusal = self._refusal()
        metric = _StubSecondary("macro_f1")
        results, refusals, errors = evaluate_declared_secondaries((metric,), lambda _s: refusal)
        assert results == [], "a refusal must never be recorded as a score"
        assert refusals == [refusal]
        assert errors == {}

    def test_a_raised_refusal_still_lands_in_refusals(self):
        """The anchor route's shape must keep working unchanged."""
        from execute_tools.evaluation_metric import (
            NotScoreableError,
            evaluate_declared_secondaries,
        )

        refusal = self._refusal()

        def _raise(_s):
            raise NotScoreableError(refusal)

        results, refusals, _errors = evaluate_declared_secondaries(
            (_StubSecondary("macro_f1"),), _raise
        )
        assert results == []
        assert refusals == [refusal]

    def test_a_real_result_still_lands_in_results(self):
        """Anti-vacuity: the happy path must not be swept into refusals."""
        from execute_tools.evaluation_metric import MetricResult, evaluate_declared_secondaries

        ok = MetricResult(metric_id="macro_f1", direction="higher", scalar=0.5)
        results, refusals, _errors = evaluate_declared_secondaries(
            (_StubSecondary("macro_f1"),), lambda _s: ok
        )
        assert results == [ok]
        assert refusals == []


class _StubSecondary:
    """Minimal stand-in exposing only the `.spec.id` the taxonomy reads."""

    def __init__(self, metric_id: str):
        self.spec = type("_Spec", (), {"id": metric_id})()
