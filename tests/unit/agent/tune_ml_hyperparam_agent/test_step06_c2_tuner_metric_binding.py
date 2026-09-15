"""Step 06 — C2: the tuner binds ONE metric at run scope and scores THROUGH it.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§9, §12, §19 C2 (acceptance: "asserted by reachability — a renamed/contrast
handle changes the observed behaviour — not by inspection alone").

Two properties, each with the defect only it catches:

1. **Composition reachability.** The framework-owned Quickstart composition
   binds its metric handle and the run resolver returns that exact object.

2. **The scoring-failure record helper.** ``_build_scoring_failure_record``
   was extracted from ``run()``'s scoring ``except`` so the ONE new outcome
   (``NotScoreableError``) has an honest description without adding a branch
   to a function at pyright's complexity ceiling. Parity for every other
   exception is pinned against the pre-extraction dict, key for key.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

from execute_tools.evaluation_metric import (
    NotScoreableError,
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
)
from tests.helpers.tuner_source import tuner_node_source

_TUNER = importlib.import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")
_REPO_ROOT = Path(__file__).resolve().parents[4]
_QUICKSTART = _REPO_ROOT / "configs/task_composition/quickstart.yaml"


def test_run_metric_is_the_handle_bound_by_the_quickstart_composition(tmp_path: Path):
    """The resolver returns the declared handle, never a task fallback."""
    from execute_tools.evaluation_metric import resolve_run_metric
    from workflows.task_composition import (
        bind_run_task_composition,
        compose_run_task_bindings,
    )

    data_root = tmp_path / "quickstart_data"
    data_root.mkdir()
    composition = compose_run_task_bindings(str(_QUICKSTART))
    with bind_run_task_composition(composition, physical_data_root=str(data_root)):
        assert resolve_run_metric() is composition.metric


# ---------------------------------------------------------------------------
# 2. The extracted scoring-failure record — parity + the one new outcome
# ---------------------------------------------------------------------------

_COMMON = dict(
    exp_id="e1",
    model_type="wavenet",
    file_index=6,
    record_params={"lr": 1e-3},
    timing={"train_time_s": 1.0, "inference_time_s": 2.0, "scoring_time_s": 0.5},
    expert_advice_str="advice",
    hypothesis="hyp",
    round_index=3,
    attempt_in_round=1,
)


def test_a_generic_scoring_exception_produces_the_pre_extraction_record(monkeypatch):
    """Byte-for-byte parity with the dict ``run()`` used to build inline
    (``ml_hyperparameter_tune_agent.py`` @530f574c :5448-5478): same keys,
    same prose, ``failure_stage``/``failure_type`` ABSENT."""
    monkeypatch.setattr(_TUNER.time, "strftime", lambda *_a, **_k: "2026-08-15 00:00:00")
    record = _TUNER._build_scoring_failure_record(KeyError("timeseries"), **_COMMON)
    assert record == {
        "exp_id": "e1",
        "status": "error_scoring",
        "model_type": "wavenet",
        "timestamp": "2026-08-15 00:00:00",
        "file_index": 6,
        "params": {"lr": 1e-3},
        "denoising_score": None,
        "timing": {"train_time_s": 1.0, "inference_time_s": 2.0, "scoring_time_s": 0.5},
        "memory": {
            "expert_advice_followed": "advice",
            "hypothesis": "hyp",
            "conclusion": "Scoring crashed: KeyError: 'timeseries'",
            # The pre-extraction prose doubles the type name (``{type}: {type}: msg``)
            # — preserved verbatim; parity is with what production wrote, warts included.
            "discovery": (
                "Training and inference completed but scoring raised KeyError: "
                "KeyError: 'timeseries'"
            ),
            "memory_update": (
                "Scoring crash — training succeeded so the "
                "checkpoint may be reusable. Investigate the "
                "scoring path (anchor map, sample_set, file "
                "vector shape) before retrying this config."
            ),
            "round_index": 3,
            "attempt_in_round": 1,
        },
    }


def test_a_not_scoreable_refusal_is_described_as_such_not_as_a_crash(monkeypatch):
    """The ONE new outcome: ``status`` stays ``error_scoring`` (no score, no
    gate evidence — its documented meaning) but the record says WHICH
    requirement the deliverable violated, marks ``failure_stage="scoring"`` /
    ``failure_type="not_scoreable"``, and never says "crashed"."""
    monkeypatch.setattr(_TUNER.time, "strftime", lambda *_a, **_k: "2026-08-15 00:00:00")
    refusal = NotScoreableResult(
        metric_id="synthetic_metric",
        direction="higher",
        verdict=ScoreabilityVerdict(
            contract_id="synthetic_deliverable_contract",
            failures=(
                ScoreabilityFailure(
                    requirement="required_attrs",
                    input_identity=4,
                    detail="attr 'unit_scale' missing on group predictions/output",
                ),
            ),
        ),
    )
    record = _TUNER._build_scoring_failure_record(NotScoreableError(refusal), **_COMMON)
    assert record["status"] == "error_scoring"
    assert record["denoising_score"] is None
    assert (record["failure_stage"], record["failure_type"]) == ("scoring", "not_scoreable")
    memory = record["memory"]
    assert "not scoreable" in memory["conclusion"]
    assert "required_attrs[file 4]" in memory["conclusion"]
    assert "unit_scale" in memory["conclusion"]
    assert "synthetic_deliverable_contract" in memory["conclusion"]
    assert "crash" not in memory["conclusion"].lower()
    assert "No scorer arithmetic was reached" in memory["discovery"]
    assert (memory["round_index"], memory["attempt_in_round"]) == (3, 1)


def test_the_helper_is_what_the_live_except_path_calls():
    """Reachability of the boundary: the scoring ``except`` in ``run()`` calls
    the helper and no longer inlines the record (a re-inlined dict would
    silently drop the not-scoreable description)."""
    source = tuner_node_source()
    handlers = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.ExceptHandler)
        and isinstance(n.type, ast.Name)
        and n.type.id == "Exception"
        and any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name)
            and c.func.id == "_build_scoring_failure_record"
            for c in ast.walk(n)
        )
    ]
    assert len(handlers) == 1
    handler = handlers[0]
    calls = {
        n.func.id: n.lineno
        for n in ast.walk(handler)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    # Named integrity refusal exits first; ordinary errors still use and emit
    # the shared scoring record rather than an inline lossy replacement.
    assert calls["raise_if_code_package_failure"] < calls["_build_scoring_failure_record"]
    emit = calls.get("_emit_record", calls.get("_emit_attempt_record"))
    assert emit is not None and calls["_build_scoring_failure_record"] < emit
    block = ast.get_source_segment(source, handler)
    assert block is not None
    assert '"status": "error_scoring"' not in block


@pytest.mark.parametrize("exc", [ValueError("x"), RuntimeError("y")])
def test_non_refusal_exceptions_never_gain_failure_type(exc):
    record = _TUNER._build_scoring_failure_record(exc, **_COMMON)
    assert "failure_stage" not in record and "failure_type" not in record


def test_failed_scoring_skill_is_infrastructure_failure_before_health():
    """A child crash is not a non-finite scientific result."""
    from nodes.ml_hyperparameter_tune_agent.execution import (
        ScoringSkillExecutionError,
        _require_successful_scoring_result,
    )

    with pytest.raises(ScoringSkillExecutionError, match="BrokenProcessPool"):
        _require_successful_scoring_result(
            {"status": "error", "message": "BrokenProcessPool: worker import failed"}
        )


def test_successful_scorer_may_still_return_nonfinite_scientific_evidence():
    """The boundary does not erase the existing successful-scorer policy."""
    from nodes.ml_hyperparameter_tune_agent.execution import (
        _require_successful_scoring_result,
    )

    _require_successful_scoring_result({"status": "success", "results": {"denoising_score": None}})


def test_live_subprocess_route_checks_status_before_results_and_health():
    """Reachability and order, not an isolated-helper-only assertion."""
    execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")

    source = inspect.getsource(execution.run_inference_scoring_health)
    run_skill = source.index('_runtime._run_skill("denoising_score_skill"')
    require_success = source.index("_require_successful_scoring_result(score_res)")
    unpack_results = source.index('_child_results = score_res.get("results"')
    health = source.index("apply_round_health(")
    assert run_skill < require_success < unpack_results < health
