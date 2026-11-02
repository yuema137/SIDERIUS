"""Workflow-level formula selection wiring (#1294, PR #1377 review B2).

A real composition of the synthetic masked-regression pack plus a weighted_sum
formula: the SOURCE metric ``masked_mse`` prefers LOWER values while the
EFFECTIVE utility prefers HIGHER ones, so a consumer that falls back to the
source spec either refuses effective-stamped evidence or ranks the other
candidate. Offline; no provider, GPU or scoring subprocess.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from execute_tools.evaluation_metric import MetricIdentityConflictError, MetricSpec
from execute_tools.metric_order import MetricOrder
from tests.helpers.tuner_composed_fixture import _isolated_registrations
from tests.unit.nodes.test_formula_selection_tuner_wiring import FORMULA, _masked_manifest
from tests.unit.workflows.test_model_exploration import (
    _make_tuning_output,
    workflow_env,
)
from workflows import model_exploration
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import (
    RunTaskComposition,
    bind_run_task_composition,
    compose_run_task_bindings,
)


class _StartupReached(Exception):
    """Raised by the first post-admission startup effect."""


@pytest.fixture
def compose(tmp_path) -> Iterator[Any]:
    with _isolated_registrations():

        def _compose(evaluation: dict[str, Any] | None = FORMULA) -> RunTaskComposition:
            root = tmp_path / ("formula" if evaluation is not None else "plain")
            return compose_run_task_bindings(str(_masked_manifest(root, evaluation)))

        yield _compose


def _effective(composition: RunTaskComposition) -> MetricSpec:
    binding = composition.selection_binding
    assert binding is not None
    return binding.effective_metric


def _persisted(score: float, spec: MetricSpec, name: str) -> HyperparamTuningOutput:
    """A tuning output as resume and seed loading read it: through its JSON."""
    output = _make_tuning_output(model_type=name, run_name=name, score=score, metric_spec=spec)
    payload = json.loads(output.model_dump_json())
    payload["all_records"][0]["metric_result"] = {
        "metric_id": spec.id,
        "direction": spec.direction,
        "scalar": score,
    }
    return HyperparamTuningOutput.model_validate_json(json.dumps(payload))


def _record(output: HyperparamTuningOutput, exp_id: str) -> dict[str, Any]:
    return {**json.loads(output.all_records[0].model_dump_json()), "exp_id": exp_id}


@pytest.mark.parametrize(
    "launch",
    [
        {"target_score": 0.8},
        {"target_score": 0.8, "target_score_metric": "masked_mse"},
        {"degenerate_penalty_score": -1.0},
    ],
)
def test_direct_workflow_refuses_source_unit_settings_before_startup(
    compose, tmp_path, monkeypatch, launch
):
    """`run_workflow` must refuse source-unit thresholds before any startup effect.

    Without its admission call a 0.8 target in masked_mse units is compared
    silently against utility; the sentinel below is reached instead of the refusal.
    """
    composition = compose()
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", lambda c: None)

    def startup(**kwargs):
        raise _StartupReached

    monkeypatch.setattr(
        "execute_tools.model_output_retention.require_local_output_inventory", startup
    )
    workspace = tmp_path / "uncreated-run"
    with pytest.raises(ValueError, match=f"effective metric '{_effective(composition).id}'"):
        model_exploration.run_workflow(
            workspace=str(workspace),
            run_name="formula",
            launch=WorkflowLaunchConfig(**launch),
            task_composition=composition,
        )
    assert not workspace.exists()
    unit = "target_score_metric" if "target_score" in launch else "score_units_metric"
    with pytest.raises(_StartupReached):
        model_exploration.run_workflow(
            workspace=str(workspace),
            run_name="formula",
            launch=WorkflowLaunchConfig(**{**launch, unit: _effective(composition).id}),
            task_composition=composition,
        )


def test_run_binding_refuses_formula_with_an_external_executor(compose, tmp_path, monkeypatch):
    """The composition edge must refuse formula + CandidateEvaluationExecutor.

    That executor bypasses the scoring child that owns aggregation, so letting the
    binding succeed would run a formula task that never computes its utility.
    """
    formula, plain = compose(), compose(None)
    monkeypatch.setattr(
        "execute_tools.evaluation_execution.candidate_evaluation_executor", lambda: object()
    )
    with pytest.raises(ValueError, match="CandidateEvaluationExecutor"):
        with bind_run_task_composition(formula, physical_data_root=str(tmp_path)):
            pytest.fail("formula bound with an external executor")
    with bind_run_task_composition(plain, physical_data_root=str(tmp_path)):
        pass


def test_seed_and_interpretation_reconcile_bind_the_effective_spec(compose):
    """`_declared_metric_spec` is the bound spec for seed summaries and interpretation.

    Bound to the source spec, effective-stamped seeds are refused as a metric
    conflict; bound correctly, they reconcile and rank by utility (higher).
    """
    from nodes.result_interpretation_agent.evidence import (
        InterpretationContractError,
        reconcile_metric_spec,
    )

    composition = compose()
    effective = _effective(composition)
    seeds = [_persisted(0.3, effective, "a"), _persisted(0.7, effective, "b")]
    bound = model_exploration._declared_metric_spec(composition)
    assert reconcile_metric_spec(seeds, bound=bound) == effective
    best = MetricOrder(effective).best(seeds, key=lambda s: s.best_denoising_score)
    assert best.model_type == "b"
    with pytest.raises(InterpretationContractError, match="masked_mse"):
        reconcile_metric_spec([_persisted(0.3, composition.metric.spec, "c")], bound=bound)
    plain = compose(None)
    assert model_exploration._declared_metric_spec(plain) == plain.metric.spec


def test_chain_incumbent_folds_effective_utility_not_source_direction(compose):
    """The native completed-history fold must keep the HIGHER utility incumbent.

    The source spec prefers lower values; folding 0.7 then 0.3 under it would
    replace the incumbent with 0.3.
    """
    from core.chain_state import ChainState
    from tests.unit.workflows.test_model_exploration import (
        _make_interpretation_output,
        _make_proposal_output,
    )
    from workflows.research_history import advance_completed_history

    composition = compose()
    effective = _effective(composition)
    state = ChainState.cold_start()
    for name, value in (("m0", 0.7), ("m1", 0.3)):
        output = _persisted(value, effective, name)
        output.best_valid_formal_denoising_score = value
        advance_completed_history(
            state,
            _make_interpretation_output(),
            _make_proposal_output(name),
            output,
            required_gate_ids=None,
            run_metric_spec=effective,
            bound_metric_spec=model_exploration._declared_metric_spec(composition),
        )
    assert state.chain_formal_incumbent_reference == 0.7


def test_resume_ranks_persisted_formula_records_by_effective_utility(compose):
    """Resume reads the persisted effective stamp and ranks records by it.

    A source-stamped record in the same pool is a metric-identity conflict,
    never silently ranked in source units.
    """
    from core.resume import _pick_best, _rankable_pool

    composition = compose()
    effective = _effective(composition)
    parsed = _persisted(0.7, effective, "run")
    records = [
        _record(_persisted(score, effective, name), name)
        for name, score in (("low", 0.3), ("high", 0.7))
    ]
    pool, order = _rankable_pool(records, parsed, context="test")
    assert order is not None and order.direction == "higher"
    assert _pick_best(pool, order=order)["exp_id"] == "high"
    mixed = [*records, _record(_persisted(0.1, composition.metric.spec, "src"), "src")]
    with pytest.raises(MetricIdentityConflictError):
        _rankable_pool(mixed, parsed, context="test")
    assert json.loads(parsed.model_dump_json())["metric_spec"]["id"] == effective.id


def test_workflow_completed_history_uses_effective_metric(compose, workflow_env, tmp_path):
    """A source-spec mutation at the real history call must fail closed.

    Three mocked tuning calls let the real workflow fold 0.7 then 0.3 and
    transport the unchanged incumbent into the third tuner input.
    """
    from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig

    composition = compose()
    effective = _effective(composition)
    seed = _persisted(0.1, effective, "seed")
    seed.task_composition_fingerprint = composition.semantic_fingerprint
    source = tmp_path / "seed.json"
    source.write_text(seed.model_dump_json())
    outputs = [_persisted(value, effective, "punet") for value in (0.7, 0.3, 0.5)]
    for output in outputs:
        output.task_composition_fingerprint = composition.semantic_fingerprint
        output.best_valid_formal_denoising_score = output.best_denoising_score
    workflow_env["tune"].return_value.run.side_effect = outputs
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        results = model_exploration.run_workflow(
            workspace=workflow_env["workspace"],
            run_name="formula_history",
            launch=WorkflowLaunchConfig(source_paths=[str(source)], max_iterations=3),
            llm_config=WorkflowLLMConfig(tune=TunerLLMConfig(planner_strategy="native-timing-v1")),
            task_composition=composition,
        )
    assert results == outputs
    inputs = [call.args[0] for call in workflow_env["tune"].return_value.run.call_args_list]
    assert [item.current_run_best_formal_score for item in inputs] == [None, 0.7, 0.7]
