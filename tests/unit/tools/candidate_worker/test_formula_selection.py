"""Issue #1294: worker admission binds formula thresholds and stamps to the effective metric.

``prepared`` is overridden here: the quickstart task plus a one-term weighted_sum
formula on its primary metric, so every imported request builder and tuner fixture
runs under formula selection. The effective id differs from the source ``accuracy``.
"""

import json
from pathlib import Path

import pytest
import yaml

from tests.helpers.formula_selection import FORMULA_EVALUATION
from tools.candidate_worker import graph, launch_candidate, training, training_admission
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.loop_evidence import verify_loop
from tools.candidate_worker.training_evidence import verify_training_evidence
from workflows.definition import MetricThresholdStop

from .conftest import QUICKSTART, _prepared, refresh
from .test_finite_loop import loop_request, scored_bodies
from .test_finite_loop import loop_tuner as loop_tuner
from .test_graph import initial
from .test_interpretation import interpretation_request
from .test_native import Provider
from .test_native import native_runner as native_runner
from .test_training import training_request as training_request
from .test_training import training_runner as training_runner


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """Like ``prepared_rubric``: verbatim pack refs resolve through an ``examples`` link."""
    project = tmp_path / "project"
    task = project / "task" / "formula"
    task.mkdir(parents=True)
    (project / "examples").symlink_to(QUICKSTART.parents[2] / "examples")
    raw = yaml.safe_load(QUICKSTART.read_text())
    raw["evaluation"] = FORMULA_EVALUATION
    manifest = task / "manifest.yaml"
    manifest.write_text(yaml.safe_dump(raw))
    yield from _prepared(tmp_path, monkeypatch, manifest)


def specs(request):
    from workflows.task_composition import compose_run_task_bindings

    composition = compose_run_task_bindings(request.preview.document.definition.task.manifest)
    assert composition.selection_metric_spec.id != composition.metric.spec.id
    return composition.metric.spec, composition.selection_metric_spec


def formula_loop(prepared, metric_id):
    """A two-body loop whose captured seed stamps the effective spec (as preparation does)."""
    request = loop_request(
        prepared, stop_conditions=(MetricThresholdStop(metric_id=metric_id, threshold=0.5),)
    )
    _, effective = specs(request)
    seed = Path(request.preview.project_root) / "interpret_input.json"
    value = json.loads(seed.read_text())
    value["metric_spec"] = effective.model_dump(mode="json")
    seed.write_text(json.dumps(value))
    return refresh(request)


@pytest.fixture
def dispatched(native_runner, monkeypatch):
    """Bodies the loop dispatched; the first dispatch ends the run (admission is the subject).

    ``native_runner`` runs the worker child in process, so this patch reaches it.
    """
    seen = []

    def first_body(*args, **kwargs):
        seen.append(kwargs["iteration"])
        raise RuntimeError("first body dispatched")

    monkeypatch.setattr(graph, "execute_fanout", first_body)
    return seen


def no_body_slot(receipt) -> bool:
    written = {
        p.relative_to(receipt.workspace).parts[:2] for p in Path(receipt.workspace).rglob("*")
    }
    return not [
        parts for parts in written if parts[0] != "candidate_run" or "iteration" in parts[-1]
    ]


def test_loop_threshold_on_the_effective_metric_is_admitted(prepared, dispatched):
    """Defect: loop stop admission compares against the source metric under formula, so
    the only correct declaration (the effective id) is refused before body 1."""
    request = formula_loop(prepared, specs(prepared)[1].id)
    receipt = launch_candidate(request)
    assert "first body dispatched" in receipt.error
    assert dispatched == [1]


def test_loop_threshold_on_the_source_metric_is_refused_before_any_body(prepared, dispatched):
    """Defect: a source-unit stop threshold (accuracy in [0, 1] vs utility) is admitted
    and later compared to utility scores, or refused only after a body ran."""
    source, effective = specs(prepared)
    receipt = launch_candidate(formula_loop(prepared, source.id))
    assert receipt.status == "failed"
    assert repr(effective.id) in receipt.error
    assert dispatched == []
    assert no_body_slot(receipt)


def test_loop_raw_component_threshold_is_refused_as_unsupported_before_any_body(
    prepared, dispatched
):
    """Defect: the loop-level formula admission is skipped, so a ``component:`` stop
    target gets only the generic metric-mismatch refusal instead of the contract's
    "raw component targets are not supported" reason (candidate-worker contract,
    "Formula selection binding").

    Routes and adaptors cannot reach a loop body (``admit_loop`` refuses the shape), so
    the stop condition is the only authored threshold a loop can carry.
    """
    _, effective = specs(prepared)
    receipt = launch_candidate(formula_loop(prepared, "component:quality"))
    assert receipt.status == "failed"
    assert "raw component targets are not supported" in receipt.error
    assert repr(effective.id) in receipt.error
    assert dispatched == []
    assert no_body_slot(receipt)


def test_source_stamped_interpretation_seed_is_refused_under_formula(prepared, native_runner):
    """Defect: interpretation input admission compares the seed's metric stamp with the
    source metric, so a source-unit stamp (scores in accuracy units) is interpreted as
    if it were the run's utility ranking."""
    request = interpretation_request(prepared)  # stamps composition.metric.spec (source)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert "interpretation metric disagrees with composed task" in receipt.error
    assert not Provider.calls


def _training_settings(request, **launch):
    path = Path(request.preview.project_root) / "training.json"
    settings = json.loads(path.read_text())
    settings["launch"].update(launch)
    path.write_text(json.dumps(settings))
    return refresh(request)


def test_degenerate_penalty_without_effective_units_is_refused_before_any_node(
    training_request, training_runner
):
    """Defect: a fresh candidate training run under formula admits
    ``degenerate_penalty_score`` (a value in source-metric units) without the explicit
    effective-unit acknowledgement, before proposal or tuning."""
    _, effective = specs(training_request)
    receipt = launch_candidate(_training_settings(training_request, degenerate_penalty_score=-1.0))
    assert receipt.status == "failed"
    assert "score_units_metric for degenerate_penalty_score" in receipt.error
    assert repr(effective.id) in receipt.error
    assert not Provider.calls
    assert [name for name, _ in training_runner if name in ("proposal", "tuner")] == []


def test_degenerate_penalty_with_effective_units_is_admitted(
    training_request, training_runner, monkeypatch
):
    """Defect (#1294 N4): candidate training settings classify ``score_units_metric`` as
    an unsupported fresh control, so the acknowledgement the formula rule requires can
    never be supplied and every penalty-bearing formula candidate is refused."""
    _, effective = specs(training_request)
    admitted = []
    real = training_admission.admit_training

    def observe(*args, **kwargs):
        admitted.append(real(*args, **kwargs))
        raise RuntimeError("training admitted")

    monkeypatch.setattr(training_admission, "admit_training", observe)
    request = _training_settings(
        training_request, degenerate_penalty_score=-1.0, score_units_metric=effective.id
    )
    receipt = launch_candidate(request)
    assert "training admitted" in receipt.error
    (admission,) = admitted
    launch = admission.settings.launch
    assert (launch.degenerate_penalty_score, launch.score_units_metric) == (-1.0, effective.id)


@pytest.fixture
def effective_tuner(loop_tuner, monkeypatch):
    """The loop tuner double, stamping the effective spec as the native tuner does."""
    real = training.HyperparamTuningAgent.run

    def run(self, value):
        output = real(self, value)
        _, effective = specs_from(value.task_composition_ref)
        return output.model_copy(update={"metric_spec": effective})

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", run)
    return loop_tuner


def specs_from(ref):
    binding = ref.selection_binding
    assert binding is not None
    return binding.source_metric, binding.effective_metric


def test_formula_loop_stops_on_the_effective_threshold_after_two_bodies(
    prepared, effective_tuner, monkeypatch
):
    """Defect: under formula the loop ranks bodies or reconciles their stamps against the
    source metric, so effective-stamped bodies conflict or the threshold is never met.

    Body scores are utility values; the incumbent (0.9, body 2) meets 0.8 and the
    loop completes before its four-body limit, re-derivable by readback.
    """
    from tools.candidate_worker.loop_stop import MetricThresholdReason

    _, effective = specs(prepared)
    request = loop_request(
        prepared,
        final_iteration=4,
        stop_conditions=(MetricThresholdStop(metric_id=effective.id, threshold=0.8),),
    )
    seed = Path(request.preview.project_root) / "interpret_input.json"
    value = json.loads(seed.read_text())
    value["metric_spec"] = effective.model_dump(mode="json")
    seed.write_text(json.dumps(value))
    request = refresh(request)
    scored_bodies(monkeypatch, (0.5, 0.9, 0.5, 0.5))
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    assert receipt.loop_trace.attempted_iterations == 2
    assert receipt.loop_trace.stop_reason == MetricThresholdReason(
        condition_index=0,
        iteration=2,
        metric_id=effective.id,
        direction="higher",
        threshold=0.8,
        incumbent=0.9,
        incumbent_iteration=2,
    )
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    assert len(verify_loop(request, parent, receipt)) == 2


def test_effective_stamped_interpretation_seed_is_accepted_under_formula(prepared, native_runner):
    """Defect: a correctly stamped (effective-spec) interpretation seed is refused because
    the stamp read back from JSON no longer equals the composed effective spec."""
    request = interpretation_request(prepared)
    _, effective = specs(request)
    seed = Path(request.preview.project_root) / "interpret_input.json"
    value = json.loads(seed.read_text())
    value["metric_spec"] = effective.model_dump(mode="json")
    seed.write_text(json.dumps(value))
    request = refresh(request)
    receipt = launch_candidate(request)
    assert receipt.status == "accepted", receipt.error
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )


def test_fixed_formula_training_candidate_completes(training_request, training_runner):
    """Defect: a fresh formula candidate's JSON seed carries a selection binding that no
    longer equals the composed one, so every formula training run is refused before
    proposal; the tuner must receive the effective binding."""
    _, effective = specs(training_request)
    receipt = launch_candidate(training_request)
    assert receipt.status == "completed", receipt.error
    (tuned,) = [value for name, value in training_runner if name == "tuner"]
    assert specs_from(tuned.task_composition_ref)[1] == effective
    verify_training_evidence(receipt)


def test_body_admission_refuses_a_source_unit_threshold_before_training(prepared, monkeypatch):
    """Defect: ``GraphBody.admit`` (the per-body boundary ``execute_fanout`` calls) admits
    a source-unit threshold and reaches training admission when it is entered without the
    loop-level check (e.g. a future caller or resume path dispatching a body directly)."""
    from workflows.llm_config import WorkflowLLMConfig
    from workflows.task_composition import compose_run_task_bindings

    source, effective = specs(prepared)
    request = loop_request(
        prepared, stop_conditions=(MetricThresholdStop(metric_id=source.id, threshold=0.5),)
    )
    composition = compose_run_task_bindings(request.preview.document.definition.task.manifest)
    trained = []
    monkeypatch.setattr(graph, "admit_training", lambda *a, **k: trained.append(a))
    with pytest.raises(ValueError, match=f"effective metric {effective.id!r}"):
        graph.GraphBody.admit(
            request, initial(request), composition, WorkflowLLMConfig.default(), 1, None, None
        )
    assert trained == []
