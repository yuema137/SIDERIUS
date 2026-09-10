"""F2 — HealthGates must fire at the ROUND boundary, on every scoring route.

**The defect.** The tuner's only production gate call site sat inside the
``ScoringRoute.ANCHOR_NORMALIZED`` branch of the scoring block, which requires
an anchor map. So:

```text
un-composed + --is_trial    -> ANCHOR_NORMALIZED  -> gates evaluated
un-composed + --no-is_trial -> SUBPROCESS_LEGACY  -> gates NEVER evaluated
composed (any task)         -> TASK_OWNED         -> gates NEVER evaluated
```

A composed task could declare a roster, materialize it, have its sha pinned
into the run-invariants lock and pass ``--healthgate_mode blocking`` — and the
production path evaluated nothing, recording ``health_gate_results: []`` beside
``health_gate_enabled: true``. That is indistinguishable, to every downstream
reader, from a clean pass.

**Why the reachability test here is the load-bearing one.** The gate ENGINE was
never broken and is covered by ``tests/unit/execute_tools/health_checks/``. What
was broken was whether production could REACH it. A behavioural test that calls
the boundary directly cannot see that defect — the boundary works fine in
isolation; it was the call site that was unreachable. So the structural test
below asserts the property no behavioural test can: the gate call is not nested
under a scoring-route condition.
"""

from __future__ import annotations

import ast
import importlib
import textwrap
from pathlib import Path
from typing import Any

import pytest

from execute_tools.health_checks.schemas import (
    GateAction,
    HealthCheckResult,
    PerSampleEvidence,
)

# ``importlib``, not a plain import: the node package rebinds ``sys.modules`` so
# ``nodes.ml_hyperparameter_tune_agent`` IS the inner main module, which makes
# ``from nodes.ml_hyperparameter_tune_agent import round_health`` fail. This is
# the same idiom the tuner conftest uses to reach ``execution``.
round_health = importlib.import_module("nodes.ml_hyperparameter_tune_agent.round_health")

evaluate_round_health = round_health.evaluate_round_health
build_evaluation_payload_fn = round_health.build_evaluation_payload_fn

#: The orchestrator's round-boundary call. Stated ONCE: these guards anchor
#: on a SYMBOL, so a rename silently un-anchors them unless the name has a
#: single home. That is not hypothetical — the extraction that shrank the
#: orchestrator renamed this call and turned all three guards red at once.
BOUNDARY_CALL = "apply_round_health"

EXECUTION_PY = (
    Path(__file__).resolve().parents[3] / "nodes" / "ml_hyperparameter_tune_agent" / "execution.py"
)


def _route_conditions_guarding_the_gate_call(source: str) -> list[str]:
    """Every ``ScoringRoute`` condition the gate call sits INSIDE.

    Empty is the healthy answer: gate evaluation is a round-boundary concern
    and must not be reachable only on one scoring route. Takes source text
    rather than reading the file itself so the detector can be shown to fire
    on a known-bad input — a structural guard that cannot fail is decoration.
    """
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    target = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == BOUNDARY_CALL
        ):
            target = node
            break
    assert target is not None, (
        "the round-boundary HealthGate call disappeared — F2 regressed, or the "
        "helper was renamed without updating this guard"
    )

    offenders: list[str] = []
    cursor: ast.AST | None = target
    while cursor in parents:
        cursor = parents[cursor]
        if isinstance(cursor, ast.If) and "ScoringRoute" in ast.dump(cursor.test):
            offenders.append(ast.dump(cursor.test))
    return offenders


def _score_meta(gate_results: Any, resolved_action: Any):
    """Stand-in for the orchestrator's own projection, which has its own tests."""
    failed = [g for g in gate_results if not getattr(g, "passed", True)]
    if not failed:
        return False, None, None
    return True, "gate_failed", str(resolved_action)


class _Recorder:
    """Captures what the engine was handed, so 'it ran' is a fact not a guess."""

    def __init__(self, *, passed: bool):
        self.passed = passed
        self.calls: list[Any] = []

    def __call__(self, ctx, **kwargs):
        self.calls.append((ctx, kwargs))
        result = HealthCheckResult(check_name="probe", passed=self.passed, reason="probe")
        gate = type(
            "_GR",
            (),
            {"passed": self.passed, "check_results": [result], "gate_id": "g"},
        )()
        action = GateAction.CONTINUE if self.passed else GateAction.INVALIDATE_ROUND
        return [gate], [], action


@pytest.fixture
def _engine(monkeypatch):
    """Bind a recording engine + a non-empty gate set for this round."""

    def _bind(*, passed: bool):
        recorder = _Recorder(passed=passed)
        monkeypatch.setattr(round_health, "evaluate_and_persist_health_gates", recorder)
        monkeypatch.setattr(round_health, "get_gates_for_position", lambda *a, **k: ["g"])
        return recorder

    return _bind


def _call(**overrides):
    kwargs: dict[str, Any] = dict(
        enabled=True,
        round_index=1,
        config_path=None,
        production_config_path="/nonexistent/health_checks.yaml",
        healthgate_mode="blocking",
        result_authority="scientific",
        model_name="m",
        run_name="r",
        exp_id="e1",
        models_dir=None,
        denoised_filename_fn=lambda i: f"/tmp/deliverable_{i}",
        target_path_fn=lambda i: f"/tmp/target_{i}",
        file_vector=[1.0, 2.0],
        denoising_score=11.9,
        per_sample_evidence=PerSampleEvidence.AVAILABLE,
        gate_results_to_score_meta=_score_meta,
    )
    kwargs.update(overrides)
    return evaluate_round_health(**kwargs)


class TestTheGateCallIsReachableFromEveryScoringRoute:
    """The structural claim. This is the F2 test.

    ``run_inference_scoring_health`` must call the round-boundary helper
    OUTSIDE any ``ScoringRoute`` condition. Re-nesting it under one — the exact
    shape of the original defect — turns this red, and no behavioural test
    would notice.
    """

    def test_the_call_is_not_nested_under_a_scoring_route_condition(self):
        """Fails as: an ancestor `if` whose test mentions ScoringRoute.

        That is precisely how the defect was written — the gate block lived
        inside `if _scoring_route is ScoringRoute.ANCHOR_NORMALIZED:`, so two
        of the three routes evaluated nothing.
        """
        offenders = _route_conditions_guarding_the_gate_call(EXECUTION_PY.read_text())

        assert offenders == [], (
            "HealthGate evaluation is nested under a scoring-route condition "
            "again — composed (TASK_OWNED) and --no-is_trial "
            f"(SUBPROCESS_LEGACY) runs will evaluate ZERO gates. Offending "
            f"conditions: {offenders}"
        )

    def test_the_detector_itself_fires_on_the_original_defect_shape(self):
        """The guard above must be able to FAIL, or it asserts nothing.

        Re-indenting the real call under an `if` to prove this would be a
        large, error-prone edit to production, so the SAME detector is fed a
        synthetic module written in the defect's exact shape. If this returns
        no offenders, the test above is vacuous and would stay green through a
        full reintroduction of F2.
        """
        reintroduced = textwrap.dedent(
            """
            def run_inference_scoring_health():
                if _scoring_route is ScoringRoute.ANCHOR_NORMALIZED:
                    _round_health = apply_round_health(score_res, enabled=True)
                else:
                    score_res = _run_skill("denoising_score_skill")
            """
        )

        offenders = _route_conditions_guarding_the_gate_call(reintroduced)

        assert offenders, "the nesting detector cannot see the defect it guards against"

    def test_the_tuner_no_longer_calls_the_engine_from_the_scoring_branch(self):
        """One call site, and it is the round-boundary one.

        Fails as: `evaluate_and_persist_health_gates` reappearing in
        execution.py — i.e. a second gate call grown beside the boundary,
        which is how the coupling would come back without this guard.
        """
        source = EXECUTION_PY.read_text()

        assert "evaluate_and_persist_health_gates" not in source
        assert source.count(f"{BOUNDARY_CALL}(") == 1

    def test_production_wires_the_task_codec_into_the_round_context(self):
        """Fails if only direct tests can read task-owned Health payloads.

        The Pets incident existed because independently correct task codecs and
        Health providers were never joined at the production round boundary.
        """
        source = EXECUTION_PY.read_text()

        assert "evaluation_payload_fn=build_evaluation_payload_fn(" in source
        assert "task_data_path=bindings.run_task_data_path" in source
        assert "deliverable_dir=sandbox.base_dir" in source


class TestTheBoundaryReportsWhetherGatesActuallyRan:
    """`[]` must stop meaning two different things.

    An empty gate list cannot distinguish "the subsystem is off" from "gates
    ran and found nothing" — and it was that ambiguity which let F2 survive,
    because the silent state looked exactly like a clean pass.
    """

    def test_a_disabled_subsystem_reports_not_evaluated_and_calls_no_engine(self, _engine):
        recorder = _engine(passed=True)

        outcome = _call(enabled=False)

        assert outcome.evaluated is False
        assert recorder.calls == [], "the engine must not be invoked when gates are disabled"
        assert outcome.persisted == []
        assert outcome.resolved_action is GateAction.CONTINUE
        assert outcome.is_degenerate is False

    def test_an_enabled_round_reports_evaluated_and_hands_the_engine_the_round_facts(self, _engine):
        """WITNESS 1 — normal output: the gate engine EXECUTES.

        Fails as: `evaluated is False` or an empty call list, which is the
        production symptom F2 produced on every composed run.
        """
        recorder = _engine(passed=True)

        outcome = _call()

        assert outcome.evaluated is True
        assert len(recorder.calls) == 1
        ctx, kwargs = recorder.calls[0]
        # The round's own evidence reached the engine — not a placeholder.
        assert ctx.file_vector == [1.0, 2.0]
        assert ctx.denoising_score == 11.9
        assert ctx.per_sample_evidence is PerSampleEvidence.AVAILABLE
        # The run's DECLARED posture travelled, rather than defaulting.
        assert kwargs["healthgate_mode"] == "blocking"
        assert kwargs["result_authority"] == "scientific"
        assert outcome.is_degenerate is False

    def test_task_owned_evaluation_payload_reaches_the_view_context(self, _engine):
        """Catches Health providers falling back to indexed task filenames.

        The production incident was an external single-file deliverable whose
        provider called the legacy indexed-name resolver. This assertion fails
        if the task codec callback is dropped before the Health engine.
        """
        recorder = _engine(passed=True)
        expected = {"sample-a": 3}

        _call(evaluation_payload_fn=lambda: expected)

        ctx, _kwargs = recorder.calls[0]
        assert ctx.load_evaluation_payload() == expected


class TestTaskOwnedEvaluationPayloadReader:
    def test_it_builds_the_exact_attempt_request_for_the_task_codec(self):
        """Catches a Health read targeting a different round's deliverable."""

        class _Codec:
            def __init__(self):
                self.requests = []

            def read_evaluation_payload(self, request):
                self.requests.append(request)
                return {"decoded": True}

        codec = _Codec()
        reader = build_evaluation_payload_fn(
            task_data_path=codec,
            deliverable_dir="/tmp/current-attempt",
            exp_id="candidate_iter_002_004",
            run_name="iter_002",
            model_type="candidate",
        )

        assert reader() == {"decoded": True}
        assert codec.requests[0].model_dump() == {
            "deliverable_dir": "/tmp/current-attempt",
            "exp_id": "candidate_iter_002_004",
            "run_name": "iter_002",
            "model_type": "candidate",
        }

    def test_a_pathological_round_fires_the_blocking_disposition(self, _engine):
        """WITNESS 2 — pathological output: the blocking disposition FIRES.

        Fails as: `resolved_action` staying CONTINUE, or `is_degenerate` False
        — a collapsed deliverable recorded as a healthy round, which is what
        the onboarding witness observed when a zero-optimizer-step model
        scored and was reported as progress.
        """
        _engine(passed=False)

        outcome = _call()

        assert outcome.evaluated is True
        assert outcome.resolved_action is GateAction.INVALIDATE_ROUND
        assert outcome.is_degenerate is True
        assert outcome.failure_reason == "gate_failed"


class TestARunThatDeclaresNoHealthEvaluatesZeroGates:
    """F-6 — the run's OWN pinned effective config decides, AT THE FIRING SITE.

    A task may declare it has no Health family (``task_health: none: true``,
    the ``EXPLICIT_NONE`` binding state). The run then materializes
    ``health_checks_effective.yaml`` carrying ``health_gates: []`` plus the
    marker ``task_health_binding: explicit_none``, pins its sha into the
    run-invariants lock, and the tuner swaps that path into
    ``agent_input.health_checks_config`` — which is the ``config_path`` this
    boundary is handed.

    **Observed in production before the fix**, on two real composed
    non-TIDMAD chains: six TIDMAD gates fired on a run whose own pinned config
    declared none, every one of them raising ``ValueError: this dataset
    profile declares no TIDMAD topology``, invalidating the round. The
    composition layer was innocent — the artifact on disk was correct, pinned
    and hashed. The loader read ``health_gates: []`` as "no roster supplied"
    (its truthiness, not its declaration) and composed the LEGACY task's
    family in its place. The pinned sha therefore described something other
    than what executed, which is worse than an unpinned run.

    Why the assertions are HERE and not only at the loader: a test proving an
    ``EXPLICIT_NONE`` config round-trips through
    ``load_health_gates_config`` does not prove a composed ROUND fires zero
    gates. Both layers of the firing path re-ask the loader — the position
    lookup (``get_gates_for_position``) and the engine
    (``evaluate_and_persist_health_gates``) — so the discriminating witness is
    the one that drives them.
    """

    @pytest.fixture
    def explicit_none_config(self, tmp_path):
        """A REAL materialized effective config for a run declaring no Health.

        Produced by the production writer, not hand-written: the defect was
        invisible precisely because the artifact was correct.
        """
        from execute_tools.health_checks._composition import HealthBindingState
        from execute_tools.health_checks.config import materialize_effective_config

        path, _sha = materialize_effective_config(
            None,
            None,
            str(tmp_path / "ws"),
            task_health_binding=HealthBindingState.EXPLICIT_NONE,
        )
        return path

    def test_the_position_lookup_selects_no_gates(self, explicit_none_config):
        """Fails as: the shipped TIDMAD roster, for a run that declared none."""
        from execute_tools.health_checks import get_gates_for_position

        for round_index in (1, 2, 3, 7):
            assert get_gates_for_position(round_index, config_path=explicit_none_config) == [], (
                "a run whose pinned effective config declares EXPLICIT_NONE "
                "selected gates at the firing site"
            )

    def test_absent_and_explicitly_empty_paths_both_evaluate_zero_gates(self, tmp_path):
        """No path state may reconstruct an undeclared scientific family."""
        from execute_tools.health_checks import get_gates_for_position
        from execute_tools.health_checks._composition import HealthBindingState
        from execute_tools.health_checks.config import materialize_effective_config

        omitted, _ = materialize_effective_config(None, None, str(tmp_path / "ws_omitted"))
        explicit_none, _ = materialize_effective_config(
            None,
            None,
            str(tmp_path / "ws_none"),
            task_health_binding=HealthBindingState.EXPLICIT_NONE,
        )
        bare_empty = tmp_path / "bare_empty.yaml"
        bare_empty.write_text("health_gates: []\n", encoding="utf-8")

        # A materialized omission and a declared explicit absence are both
        # honest empty families. Neither selects a scientific default.
        assert get_gates_for_position(1, config_path=omitted) == []
        assert get_gates_for_position(1, config_path=explicit_none) == []
        # A hand-written empty effective file and no file at all also remain
        # empty; restoring task science in either branch would violate the
        # explicit-composition boundary.
        assert get_gates_for_position(1, config_path=str(bare_empty)) == []
        assert get_gates_for_position(1) == []
        assert get_gates_for_position(1, config_path=str(bare_empty)) == get_gates_for_position(1)

    def test_the_round_boundary_runs_the_real_engine_and_persists_nothing(
        self, explicit_none_config
    ):
        """The production question, asked of the production boundary.

        The engine is NOT stubbed here — this is the only test in the file
        that lets the real one run — because the defect lived in what the
        engine loaded, not in whether it was called. The deliverable and raw
        resolvers refuse by name: any gate that actually fires reaches for one
        of them, so a reintroduction fails LOUDLY and says which.
        """

        def _must_not_be_called(index):
            raise AssertionError(
                f"a HealthGate asked for input {index!r} on a run that "
                "declared it has no Health family"
            )

        outcome = _call(
            config_path=explicit_none_config,
            production_config_path=explicit_none_config,
            denoised_filename_fn=_must_not_be_called,
            target_path_fn=_must_not_be_called,
        )

        assert outcome.evaluated is True, (
            "the subsystem is ENABLED — 'evaluated' distinguishes that from "
            "'disabled', and conflating them is F2"
        )
        assert outcome.persisted == []
        assert outcome.resolved_action is GateAction.CONTINUE
        assert outcome.is_degenerate is False
        assert outcome.failure_reason is None
