"""Issue 1423: pseudo scoring must satisfy the parent's formula evidence check.

The parent re-derives every term from the transported raw values
(``validate_child_evaluation``). A stub that omits ``evaluation_result``, or
draws source values outside a ``refuse`` term's bounds, fails that check the
same way the Pet weighted-selection pseudo run did. The masked pack's formula
references its primary (``masked_mse``, refuse in [0, 1]) and its secondary
(``masked_mae``, refuse in [0, 10]); the legacy synthetic band [-3, -2] is
outside both intervals, so in-bounds drawing is load-bearing.
"""

import random
from pathlib import Path

import pytest

from core.stub_sandbox import StubSandbox
from execute_tools.evaluation_child import EvaluationNotScoreableError, validate_child_evaluation
from tests.helpers.tuner_composed_fixture import _isolated_registrations
from tests.unit.nodes.test_formula_selection_tuner_wiring import FORMULA, _masked_manifest
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

ARGS = ("attempt", "run", "synthetic_model", {}, {}, {})


def _score(tmp_path: Path, evaluation, name: str) -> dict:
    with _isolated_registrations():
        composition = compose_run_task_bindings(str(_masked_manifest(tmp_path / name, evaluation)))
        with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
            sandbox = StubSandbox(workspace=str(tmp_path / f"{name}_ws"), run_id="stream")
            outcome = sandbox.execute_scoring(*ARGS)
    return {"outcome": outcome, "composition": composition}


def test_formula_scoring_passes_the_parent_evidence_check(tmp_path):
    scored = _score(tmp_path, FORMULA, "formula")
    outcome, composition = scored["outcome"], scored["composition"]
    assert outcome["status"] == "success"
    results = outcome["results"]
    evidence = validate_child_evaluation(results, composition)
    assert evidence is not None and evidence.aggregate == results["denoising_score"]
    assert [c.component_id for c in evidence.components] == ["mse", "mae"]
    assert not any(c.clipped for c in evidence.components)


def test_plain_composition_keeps_the_legacy_payload_and_stream(tmp_path):
    """Without formula terms the stub must not consume extra draws or add keys.

    The expectation follows the documented ``random.Random(run_id)`` stream:
    each legacy scoring call draws one scalar and nine vector values, so an
    extra draw shifts the second call's scalar.
    """
    stream = random.Random("stream")
    expected = []
    for _ in range(2):
        scalar = stream.uniform(-3.0, -2.0)
        expected.append((scalar, [stream.uniform(-3.0, -2.0) for _ in range(9)]))
    with _isolated_registrations():
        composition = compose_run_task_bindings(str(_masked_manifest(tmp_path / "plain", None)))
        with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
            sandbox = StubSandbox(workspace=str(tmp_path / "plain_ws"), run_id="stream")
            calls = [sandbox.execute_scoring(*ARGS)["results"] for _ in range(2)]
    assert [(r["denoising_score"], r["file_vector"]) for r in calls] == expected
    assert not any("evaluation_result" in r for r in calls)


def test_refused_formula_evidence_reaches_the_parent_as_a_typed_refusal(tmp_path, monkeypatch):
    """Without declared bounds the legacy band violates ``refuse`` terms.

    The stub must then return the child's refusal envelope (status ``error``
    with component evidence), which the parent raises as a typed refusal
    instead of a transport error or a silent success.
    """
    import core.pseudo_scoring as pseudo_scoring

    monkeypatch.setattr(pseudo_scoring, "_term_bounds", lambda composition: {})
    scored = _score(tmp_path, FORMULA, "refused")
    outcome = scored["outcome"]
    assert outcome["status"] == "error"
    assert outcome["results"]["denoising_score"] is None
    with pytest.raises(EvaluationNotScoreableError):
        validate_child_evaluation(outcome["results"], scored["composition"])
